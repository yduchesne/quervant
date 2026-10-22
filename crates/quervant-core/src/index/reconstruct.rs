//! Lossless document reconstruction and deterministic patch transforms (M2).
//!
//! Everything in this module is pure with respect to writer state: it reads an
//! already-verified physical or in-memory source, applies an ordered patch, and
//! validates the complete result. It never publishes, stores or mutates writer
//! state.
//!
//! Source policy is deliberately conservative. A stored field is authoritative
//! when present; otherwise a columnar field is authoritative. A schema-legal
//! field that has neither a stored nor a columnar source is unrecoverable and
//! rejects the whole update, regardless of whether the patch targets that field.

use std::collections::BTreeSet;

use crate::contract::budget::{BudgetKind, Budgets};
use crate::contract::document::{Document, DocumentKey, FieldValues};
use crate::contract::error::{DocumentError, QueryError};
use crate::contract::mutation::{
    DocumentPatch, MutationRejection, PatchOperation, ReconstructionFailure,
};
use crate::contract::schema::Schema;
use crate::segment::{SegmentDocument, SegmentReader};

use super::error::{IndexError, IndexResult};

/// Per-batch physical-source byte meter.
///
/// Each distinct physical segment is charged its full encoded length before a
/// reader is opened. Repeated reconstructions from one segment do not charge
/// again; the meter bounds the aggregate bytes of distinct source segments.
pub(crate) struct SourceMeter {
    limit: u64,
    charged: u64,
    segments: BTreeSet<String>,
}

impl SourceMeter {
    pub(crate) fn new(limit: u64) -> Self {
        Self {
            limit,
            charged: 0,
            segments: BTreeSet::new(),
        }
    }

    /// Charge one physical segment once, before opening or decoding it.
    pub(crate) fn charge(&mut self, segment_id: &str, bytes: u64) -> IndexResult<()> {
        if self.segments.contains(segment_id) {
            return Ok(());
        }
        let projected = self
            .charged
            .checked_add(bytes)
            .ok_or(IndexError::ResourceLimit {
                limit: self.limit,
                requested: u64::MAX,
            })?;
        if projected > self.limit {
            return Err(IndexError::ResourceLimit {
                limit: self.limit,
                requested: projected,
            });
        }
        self.charged = projected;
        self.segments.insert(segment_id.to_owned());
        Ok(())
    }
}

/// Validate patch structure that does not depend on the current source value.
///
/// This runs in phase A, before the whole-batch fingerprint and durable replay
/// lookup, so a malformed request is rejected consistently even when it carries
/// a matching idempotency token. It does not validate the final document against
/// field types/cardinality; that happens after the patch is applied.
pub(crate) fn validate_patch_shape(patch: &DocumentPatch, schema: &Schema) -> IndexResult<()> {
    if patch.operations.is_empty() {
        return Err(invalid_patch(
            "a document patch must contain at least one operation",
        ));
    }
    for operation in &patch.operations {
        let (field, is_absent_set) = match operation {
            PatchOperation::Set { field, values } => (field, values.is_absent()),
            PatchOperation::Unset { field } => (field, false),
        };
        if schema.get(field).is_none() {
            return Err(IndexError::Contract(QueryError::InvalidDocument(
                DocumentError::UnknownField {
                    field: field.clone(),
                },
            )));
        }
        if is_absent_set {
            return Err(invalid_patch(
                "patch Set(Absent) is invalid; use Unset to remove a field",
            ));
        }
    }
    Ok(())
}

/// Apply an ordered patch to a complete source document.
///
/// Operations are applied left to right with last-write-wins semantics.
/// `Set(Absent)` is rejected; `Unset` removes the field. The final document is
/// fully schema-validated. The helper never touches writer state.
pub(crate) fn apply_document_patch(
    base: &Document,
    patch: &DocumentPatch,
    schema: &Schema,
    budgets: &Budgets,
) -> IndexResult<Document> {
    validate_patch_shape(patch, schema)?;
    precheck_patch_admission(base, patch, budgets)?;

    let mut result = base.clone();
    for operation in &patch.operations {
        match operation {
            PatchOperation::Set { field, values } => {
                result.insert(field.clone(), values.clone())?;
            }
            PatchOperation::Unset { field } => {
                result.insert(field.clone(), FieldValues::Absent)?;
            }
        }
        check_document_budget(&result, budgets)?;
    }
    schema.validate_document(&result, budgets)?;
    Ok(result)
}

/// Reconstruct a complete document from a verified physical segment record.
///
/// The physical key is checked against `expected_key`. Every codec schema field
/// must agree with the contract schema. A field that is neither stored nor
/// columnar rejects the whole reconstruction before any value is accepted.
pub(crate) fn reconstruct_from_segment(
    reader: &SegmentReader,
    schema: &Schema,
    doc_id: u64,
    expected_key: &DocumentKey,
    budgets: &Budgets,
) -> IndexResult<Document> {
    let physical_key = reader.doc_key(doc_id)?;
    if &physical_key != expected_key {
        return Err(reconstruction_unavailable(
            expected_key.clone(),
            None,
            ReconstructionFailure::SourceMismatch,
        ));
    }

    let codec = reader.schema();
    if codec.field_count() != schema.field_count() {
        return Err(reconstruction_unavailable(
            expected_key.clone(),
            None,
            ReconstructionFailure::SourceMismatch,
        ));
    }
    for field in codec.fields() {
        let definition = schema.get(&field.name).ok_or_else(|| {
            reconstruction_unavailable(
                expected_key.clone(),
                None,
                ReconstructionFailure::SourceMismatch,
            )
        })?;
        if definition.field_type != field.field_type
            || definition.cardinality != field.cardinality
            || definition.options != field.options
        {
            return Err(reconstruction_unavailable(
                expected_key.clone(),
                None,
                ReconstructionFailure::SourceMismatch,
            ));
        }
        if !field.is_stored() && !field.is_columnar() {
            return Err(reconstruction_unavailable(
                expected_key.clone(),
                Some(field.name.clone()),
                ReconstructionFailure::UnrecoverableField,
            ));
        }
    }

    let needs_stored = codec.fields().iter().any(|field| field.is_stored());
    let stored = if needs_stored {
        Some(reader.stored_doc(doc_id)?)
    } else {
        None
    };
    if let Some(record) = &stored {
        if &record.key != expected_key {
            return Err(reconstruction_unavailable(
                expected_key.clone(),
                None,
                ReconstructionFailure::SourceMismatch,
            ));
        }
    }

    let needs_columns = codec.fields().iter().any(|field| field.is_columnar());
    let columns = if needs_columns {
        Some(reader.open_columns()?.ok_or_else(|| {
            reconstruction_unavailable(
                expected_key.clone(),
                None,
                ReconstructionFailure::MissingSource,
            )
        })?)
    } else {
        None
    };

    let mut document = Document::new(expected_key.clone());
    for field in codec.fields() {
        let values = if field.is_stored() {
            // `stored` is present because `needs_stored` covered this field.
            stored
                .as_ref()
                .map(|record| record.get(field.id))
                .ok_or_else(|| {
                    reconstruction_unavailable(
                        expected_key.clone(),
                        None,
                        ReconstructionFailure::MissingSource,
                    )
                })?
        } else {
            let columns = columns.as_ref().ok_or_else(|| {
                reconstruction_unavailable(
                    expected_key.clone(),
                    None,
                    ReconstructionFailure::MissingSource,
                )
            })?;
            columns.value(field.id, doc_id)?.ok_or_else(|| {
                reconstruction_unavailable(
                    expected_key.clone(),
                    None,
                    ReconstructionFailure::MissingSource,
                )
            })?
        };
        if !values.is_absent() {
            document.insert(field.name.clone(), values)?;
        }
    }
    schema.validate_document(&document, budgets)?;
    Ok(document)
}

/// Convert an in-memory writer source without lossy stored-record decoding.
///
/// `pending` and same-batch staged documents retain the original
/// [`SegmentDocument`] field map, including fields that would not be recoverable
/// after a flush/commit.
pub(crate) fn reconstruct_from_document(
    source: &SegmentDocument,
    schema: &Schema,
    expected_key: &DocumentKey,
    budgets: &Budgets,
) -> IndexResult<Document> {
    if source.key != *expected_key {
        return Err(reconstruction_unavailable(
            expected_key.clone(),
            None,
            ReconstructionFailure::SourceMismatch,
        ));
    }
    let mut document = Document::new(expected_key.clone());
    for (name, values) in &source.fields {
        if !values.is_absent() {
            document.insert(name.clone(), values.clone())?;
        }
    }
    schema.validate_document(&document, budgets)?;
    Ok(document)
}

fn precheck_patch_admission(
    base: &Document,
    patch: &DocumentPatch,
    budgets: &Budgets,
) -> IndexResult<()> {
    let limit = budgets.get(BudgetKind::DocumentBytes);
    let mut total = u64::try_from(base.approx_size()).map_err(|_| IndexError::ResourceLimit {
        limit: limit.unwrap_or(u64::MAX),
        requested: u64::MAX,
    })?;
    for operation in &patch.operations {
        match operation {
            PatchOperation::Set { field, values } => {
                total = checked_add(
                    total,
                    u64::try_from(field.len()).map_err(|_| IndexError::ResourceLimit {
                        limit: limit.unwrap_or(u64::MAX),
                        requested: u64::MAX,
                    })?,
                    limit,
                )?;
                total = checked_add(
                    total,
                    u64::try_from(values.approx_size()).map_err(|_| IndexError::ResourceLimit {
                        limit: limit.unwrap_or(u64::MAX),
                        requested: u64::MAX,
                    })?,
                    limit,
                )?;
            }
            PatchOperation::Unset { field } => {
                total = checked_add(
                    total,
                    u64::try_from(field.len()).map_err(|_| IndexError::ResourceLimit {
                        limit: limit.unwrap_or(u64::MAX),
                        requested: u64::MAX,
                    })?,
                    limit,
                )?;
            }
        }
    }
    if let Some(limit) = limit {
        if total > limit {
            return Err(IndexError::ResourceLimit {
                limit,
                requested: total,
            });
        }
    }
    Ok(())
}

fn checked_add(current: u64, add: u64, limit: Option<u64>) -> IndexResult<u64> {
    current.checked_add(add).ok_or(IndexError::ResourceLimit {
        limit: limit.unwrap_or(u64::MAX),
        requested: u64::MAX,
    })
}

fn check_document_budget(document: &Document, budgets: &Budgets) -> IndexResult<()> {
    if let Some(limit) = budgets.get(BudgetKind::Fields) {
        let count = u64::try_from(document.field_count()).unwrap_or(u64::MAX);
        if count > limit {
            return Err(IndexError::ResourceLimit {
                limit,
                requested: count,
            });
        }
    }
    if let Some(limit) = budgets.get(BudgetKind::DocumentBytes) {
        let bytes = u64::try_from(document.approx_size()).unwrap_or(u64::MAX);
        if bytes > limit {
            return Err(IndexError::ResourceLimit {
                limit,
                requested: bytes,
            });
        }
    }
    Ok(())
}

fn invalid_patch(detail: &'static str) -> IndexError {
    IndexError::MutationRejected {
        rejection: MutationRejection::InvalidBatch {
            detail: detail.to_owned(),
        },
    }
}

fn reconstruction_unavailable(
    key: DocumentKey,
    field: Option<String>,
    reason: ReconstructionFailure,
) -> IndexError {
    IndexError::MutationRejected {
        rejection: MutationRejection::reconstruction_unavailable(key, field, reason),
    }
}

#[cfg(test)]
mod tests {
    use std::net::{IpAddr, Ipv4Addr};

    use crate::analysis::AnalyzerRegistry;
    use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
    use crate::contract::error::{DocumentError, QueryError};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{
        FieldType, FieldValue, GeoPoint, IpNetwork, JsonNumber, JsonValue, Timestamp,
    };
    use crate::segment::{SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader};

    use super::*;

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).expect("key")
    }

    fn full_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "text",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard_folded"),
                FieldDefinition::new(
                    "json",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "kw",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, false, true),
                ),
                FieldDefinition::new(
                    "empty_kw",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "u",
                    FieldType::U64,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "f",
                    FieldType::F64,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "b",
                    FieldType::Bool,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "geo",
                    FieldType::GeoPoint,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "ip",
                    FieldType::IpAddress,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "cidr",
                    FieldType::IpNetwork,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
                FieldDefinition::new(
                    "both",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "single_kw",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(false, false, true),
                ),
            ],
            None,
        )
        .expect("schema")
    }

    fn json_object() -> JsonValue {
        JsonValue::Object(vec![
            ("a".to_owned(), JsonValue::Number(JsonNumber::I64(1))),
            ("b".to_owned(), JsonValue::String("two".to_owned())),
        ])
    }

    fn full_document(key_value: &str) -> Document {
        let mut document = Document::new(key(key_value));
        document
            .insert(
                "text",
                FieldValues::Single(FieldValue::Text("hello world".to_owned())),
            )
            .unwrap();
        document
            .insert("json", FieldValues::Single(FieldValue::Json(json_object())))
            .unwrap();
        document
            .insert(
                "kw",
                FieldValues::Multi(vec![
                    FieldValue::Keyword("a".to_owned()),
                    FieldValue::Keyword("b".to_owned()),
                ]),
            )
            .unwrap();
        document.insert("empty_kw", FieldValues::Empty).unwrap();
        document
            .insert("n", FieldValues::Single(FieldValue::I64(7)))
            .unwrap();
        document
            .insert("u", FieldValues::Single(FieldValue::U64(9)))
            .unwrap();
        document
            .insert("f", FieldValues::Single(FieldValue::F64(1.5)))
            .unwrap();
        document
            .insert("b", FieldValues::Single(FieldValue::Bool(true)))
            .unwrap();
        document
            .insert(
                "ts",
                FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(1_000))),
            )
            .unwrap();
        document
            .insert(
                "geo",
                FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(1.0, 2.0).unwrap())),
            )
            .unwrap();
        document
            .insert(
                "ip",
                FieldValues::Single(FieldValue::Ip("10.0.0.1".parse().unwrap())),
            )
            .unwrap();
        document
            .insert(
                "cidr",
                FieldValues::Single(FieldValue::Cidr(
                    IpNetwork::new(IpAddr::V4(Ipv4Addr::new(10, 0, 0, 0)), 24).unwrap(),
                )),
            )
            .unwrap();
        document
            .insert(
                "both",
                FieldValues::Single(FieldValue::Keyword("both".to_owned())),
            )
            .unwrap();
        document
            .insert(
                "single_kw",
                FieldValues::Single(FieldValue::Keyword("single".to_owned())),
            )
            .unwrap();
        document
    }

    fn null_state_document(key_value: &str) -> Document {
        let mut document = Document::new(key(key_value));
        document.insert("text", FieldValues::ExplicitNull).unwrap();
        document.insert("json", FieldValues::ExplicitNull).unwrap();
        document.insert("kw", FieldValues::Empty).unwrap();
        document.insert("empty_kw", FieldValues::Empty).unwrap();
        document.insert("n", FieldValues::ExplicitNull).unwrap();
        // u, ts, ip, and cidr remain absent.
        document
            .insert("f", FieldValues::Single(FieldValue::F64(2.5)))
            .unwrap();
        document.insert("b", FieldValues::ExplicitNull).unwrap();
        document.insert("geo", FieldValues::ExplicitNull).unwrap();
        document.insert("both", FieldValues::ExplicitNull).unwrap();
        document
            .insert("single_kw", FieldValues::ExplicitNull)
            .unwrap();
        document
    }

    fn segment_document_from(document: &Document) -> SegmentDocument {
        let mut segment = SegmentDocument::new(document.key().clone());
        for (name, values) in document.fields() {
            segment.fields.insert(name.to_owned(), values.clone());
        }
        segment
    }

    fn build_reader(schema: &Schema, documents: &[Document]) -> SegmentReader {
        let mut builder =
            SegmentBuilder::new(schema.clone(), AnalyzerRegistry::builtin()).expect("builder");
        for document in documents {
            builder
                .add_document(segment_document_from(document))
                .expect("add document");
        }
        let built = builder.build().expect("build segment");
        SegmentReader::open(built.bytes, SegmentLimits::default()).expect("reader")
    }

    #[test]
    fn reconstruct_from_document_preserves_all_five_states_without_decoding() {
        let schema = full_schema();
        let budgets = Budgets::new();
        for source in [full_document("k1"), null_state_document("k1")] {
            let segment = segment_document_from(&source);
            let reconstructed =
                reconstruct_from_document(&segment, &schema, source.key(), &budgets)
                    .expect("reconstruct");
            assert_eq!(reconstructed, source);
        }
    }

    #[test]
    fn reconstruct_from_segment_round_trips_stored_and_columnar_values() {
        let schema = full_schema();
        let budgets = Budgets::new();
        let full = full_document("k1");
        let nulls = null_state_document("k2");
        let reader = build_reader(&schema, &[full.clone(), nulls.clone()]);

        assert_eq!(
            reconstruct_from_segment(&reader, &schema, 0, full.key(), &budgets).unwrap(),
            full
        );
        assert_eq!(
            reconstruct_from_segment(&reader, &schema, 1, nulls.key(), &budgets).unwrap(),
            nulls
        );
    }

    #[test]
    fn reconstruct_rejects_indexed_only_physical_field_schema_wide() {
        let schema = Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard_folded"),
                FieldDefinition::new(
                    "lost",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                )
                .with_analyzer("standard_folded"),
            ],
            None,
        )
        .unwrap();
        let mut document = Document::new(key("k1"));
        document
            .insert("title", FieldValues::Single(FieldValue::Text("t".into())))
            .unwrap();
        document
            .insert("lost", FieldValues::Single(FieldValue::Text("gone".into())))
            .unwrap();
        let reader = build_reader(&schema, &[document]);
        let error =
            reconstruct_from_segment(&reader, &schema, 0, &key("k1"), &Budgets::new()).unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::ReconstructionUnavailable {
                    field: Some(field),
                    reason: ReconstructionFailure::UnrecoverableField,
                    ..
                }
            } if field == "lost"
        ));
    }

    #[test]
    fn reconstruct_rejects_key_and_schema_mismatch() {
        let schema = full_schema();
        let document = full_document("k1");
        let reader = build_reader(&schema, &[document]);
        let error = reconstruct_from_segment(&reader, &schema, 0, &key("other"), &Budgets::new())
            .unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::ReconstructionUnavailable {
                    reason: ReconstructionFailure::SourceMismatch,
                    ..
                }
            }
        ));

        let other_schema = Schema::new(
            vec![
                FieldDefinition::new(
                    "different",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard_folded"),
            ],
            None,
        )
        .unwrap();
        let error =
            reconstruct_from_segment(&reader, &other_schema, 0, &key("k1"), &Budgets::new())
                .unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::ReconstructionUnavailable {
                    reason: ReconstructionFailure::SourceMismatch,
                    ..
                }
            }
        ));
    }

    #[test]
    fn patch_applies_ordered_set_and_unset_with_five_state_fidelity() {
        let schema = full_schema();
        let base = full_document("k1");
        let expected = {
            let mut document = Document::new(key("k1"));
            document
                .insert(
                    "text",
                    FieldValues::Single(FieldValue::Text("final title".to_owned())),
                )
                .unwrap();
            // json is removed by Unset.
            document
                .insert(
                    "kw",
                    FieldValues::Multi(vec![FieldValue::Keyword("z".to_owned())]),
                )
                .unwrap();
            document
                .insert("empty_kw", FieldValues::ExplicitNull)
                .unwrap();
            document.insert("n", FieldValues::ExplicitNull).unwrap();
            document
                .insert("u", FieldValues::Single(FieldValue::U64(11)))
                .unwrap();
            document
                .insert("f", FieldValues::Single(FieldValue::F64(3.5)))
                .unwrap();
            document
                .insert("b", FieldValues::Single(FieldValue::Bool(false)))
                .unwrap();
            document
                .insert(
                    "ts",
                    FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(2_000))),
                )
                .unwrap();
            document
                .insert(
                    "geo",
                    FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(3.0, 4.0).unwrap())),
                )
                .unwrap();
            document
                .insert(
                    "ip",
                    FieldValues::Single(FieldValue::Ip("192.0.2.1".parse().unwrap())),
                )
                .unwrap();
            document
                .insert(
                    "cidr",
                    FieldValues::Single(FieldValue::Cidr(
                        IpNetwork::new(IpAddr::V4(Ipv4Addr::new(192, 0, 2, 0)), 24).unwrap(),
                    )),
                )
                .unwrap();
            document
                .insert(
                    "both",
                    FieldValues::Single(FieldValue::Keyword("both".to_owned())),
                )
                .unwrap();
            document
                .insert(
                    "single_kw",
                    FieldValues::Single(FieldValue::Keyword("changed".to_owned())),
                )
                .unwrap();
            document
        };
        let patch = DocumentPatch {
            operations: vec![
                PatchOperation::Set {
                    field: "text".to_owned(),
                    values: FieldValues::Single(FieldValue::Text("first".to_owned())),
                },
                PatchOperation::Set {
                    field: "text".to_owned(),
                    values: FieldValues::Single(FieldValue::Text("final title".to_owned())),
                },
                PatchOperation::Unset {
                    field: "json".to_owned(),
                },
                PatchOperation::Set {
                    field: "kw".to_owned(),
                    values: FieldValues::Multi(vec![FieldValue::Keyword("z".to_owned())]),
                },
                PatchOperation::Set {
                    field: "empty_kw".to_owned(),
                    values: FieldValues::ExplicitNull,
                },
                PatchOperation::Set {
                    field: "n".to_owned(),
                    values: FieldValues::ExplicitNull,
                },
                PatchOperation::Set {
                    field: "u".to_owned(),
                    values: FieldValues::Single(FieldValue::U64(11)),
                },
                PatchOperation::Set {
                    field: "f".to_owned(),
                    values: FieldValues::Single(FieldValue::F64(3.5)),
                },
                PatchOperation::Set {
                    field: "b".to_owned(),
                    values: FieldValues::Single(FieldValue::Bool(false)),
                },
                PatchOperation::Set {
                    field: "ts".to_owned(),
                    values: FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(
                        2_000,
                    ))),
                },
                PatchOperation::Set {
                    field: "geo".to_owned(),
                    values: FieldValues::Single(FieldValue::GeoPoint(
                        GeoPoint::new(3.0, 4.0).unwrap(),
                    )),
                },
                PatchOperation::Set {
                    field: "ip".to_owned(),
                    values: FieldValues::Single(FieldValue::Ip("192.0.2.1".parse().unwrap())),
                },
                PatchOperation::Set {
                    field: "cidr".to_owned(),
                    values: FieldValues::Single(FieldValue::Cidr(
                        IpNetwork::new(IpAddr::V4(Ipv4Addr::new(192, 0, 2, 0)), 24).unwrap(),
                    )),
                },
                PatchOperation::Set {
                    field: "single_kw".to_owned(),
                    values: FieldValues::Single(FieldValue::Keyword("changed".to_owned())),
                },
            ],
        };
        let patched = apply_document_patch(&base, &patch, &schema, &Budgets::new()).expect("patch");
        assert_eq!(patched, expected);
        assert_eq!(base, full_document("k1"), "patch never mutates the source");
    }

    #[test]
    fn patch_shape_rejections_are_typed_and_bounded() {
        let schema = full_schema();
        let base = full_document("k1");
        let empty = DocumentPatch {
            operations: Vec::new(),
        };
        assert!(matches!(
            apply_document_patch(&base, &empty, &schema, &Budgets::new()),
            Err(IndexError::MutationRejected {
                rejection: MutationRejection::InvalidBatch { .. }
            })
        ));

        let absent = DocumentPatch {
            operations: vec![PatchOperation::Set {
                field: "text".to_owned(),
                values: FieldValues::Absent,
            }],
        };
        assert!(matches!(
            apply_document_patch(&base, &absent, &schema, &Budgets::new()),
            Err(IndexError::MutationRejected {
                rejection: MutationRejection::InvalidBatch { .. }
            })
        ));

        let unknown = DocumentPatch {
            operations: vec![PatchOperation::Unset {
                field: "missing".to_owned(),
            }],
        };
        assert!(matches!(
            apply_document_patch(&base, &unknown, &schema, &Budgets::new()),
            Err(IndexError::Contract(QueryError::InvalidDocument(
                DocumentError::UnknownField { field }
            ))) if field == "missing"
        ));
    }

    #[test]
    fn patch_rejects_invalid_final_document_and_budget_overflow() {
        let schema = full_schema();
        let base = full_document("k1");
        let wrong_type = DocumentPatch {
            operations: vec![PatchOperation::Set {
                field: "n".to_owned(),
                values: FieldValues::Single(FieldValue::Text("not a number".to_owned())),
            }],
        };
        assert!(matches!(
            apply_document_patch(&base, &wrong_type, &schema, &Budgets::new()),
            Err(IndexError::Contract(QueryError::InvalidDocument(
                DocumentError::TypeMismatch { .. }
            )))
        ));

        let empty_single = DocumentPatch {
            operations: vec![PatchOperation::Set {
                field: "single_kw".to_owned(),
                values: FieldValues::Empty,
            }],
        };
        assert!(matches!(
            apply_document_patch(&base, &empty_single, &schema, &Budgets::new()),
            Err(IndexError::Contract(QueryError::InvalidDocument(
                DocumentError::CardinalityMismatch { .. }
            )))
        ));

        let budgets = Budgets::new()
            .with(BudgetKind::DocumentBytes, 64)
            .expect("budget");
        let huge = DocumentPatch {
            operations: vec![PatchOperation::Set {
                field: "text".to_owned(),
                values: FieldValues::Single(FieldValue::Text("x".repeat(256))),
            }],
        };
        assert!(matches!(
            apply_document_patch(&base, &huge, &schema, &budgets),
            Err(IndexError::ResourceLimit { limit: 64, requested }) if requested > 64
        ));
    }

    #[test]
    fn unset_of_absent_field_is_legal_and_result_matches_base() {
        let schema = full_schema();
        let mut base = Document::new(key("k1"));
        base.insert(
            "text",
            FieldValues::Single(FieldValue::Text("stable".to_owned())),
        )
        .unwrap();
        let patch = DocumentPatch {
            operations: vec![PatchOperation::Unset {
                field: "n".to_owned(),
            }],
        };
        let patched = apply_document_patch(&base, &patch, &schema, &Budgets::new()).expect("patch");
        assert_eq!(patched, base);
    }
}
