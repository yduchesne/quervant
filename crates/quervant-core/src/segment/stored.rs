//! Stored source documents with the shared five-state vocabulary (F06).

use std::collections::BTreeMap;

use crate::contract::document::{DocumentKey, FieldValues};

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::model::SegmentDocument;
use super::schema::CodecSchema;
use super::value::{decode_field_values_budgeted, encode_field_values, skip_field_values_budgeted};

/// A decoded stored record addressed by physical doc id.
#[derive(Debug, Clone, PartialEq)]
pub struct StoredRecord {
    /// Byte-exact logical key.
    pub key: DocumentKey,
    /// Present stored field states by field id.
    pub fields: BTreeMap<u32, FieldValues>,
}

impl StoredRecord {
    /// Look up a stored field state (defaults to `Absent`).
    #[must_use]
    pub fn get(&self, field_id: u32) -> FieldValues {
        self.fields
            .get(&field_id)
            .cloned()
            .unwrap_or(FieldValues::Absent)
    }
}

/// Encode the STORED section body.
pub fn encode_stored(
    schema: &CodecSchema,
    docs: &[SegmentDocument],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let field_count = schema.field_count();
    let bitmap_len = field_count.div_ceil(8);
    let mut writer = ByteWriter::new();
    writer.u16(1); // stored_version
    writer.u64(docs.len() as u64);
    for doc in docs {
        writer.len_prefixed_u16(doc.key.as_str().as_bytes())?;
        let mut bitmap = vec![0u8; bitmap_len];
        let mut present: Vec<(u32, &FieldValues)> = Vec::new();
        for field in schema.fields() {
            if !field.is_stored() {
                continue;
            }
            let values = doc.fields.get(&field.name);
            if let Some(values) = values {
                if !values.is_absent() {
                    bitmap[field.id as usize / 8] |= 1 << (field.id % 8);
                    present.push((field.id, values));
                }
            }
        }
        writer.bytes(&bitmap);
        for (field_id, values) in present {
            let field = schema
                .field(field_id)
                .ok_or(SegmentError::UnknownFieldId { field_id })?;
            writer.u32(field_id);
            encode_field_values(&mut writer, field.field_type, values, limits)?;
        }
    }
    Ok(writer.into_vec())
}

/// Decode the STORED section body, materializing only the selected physical doc ids.
///
/// Every record in the section — selected or not — is fully parsed, validated and
/// charged against one shared [`DecodeBudget`]; only the selected records are
/// materialized as owned values. Selected records are byte-for-byte identical to
/// the corresponding entries from [`decode_stored`].
///
/// `selected_doc_ids` must be strictly increasing, duplicate-free physical doc ids
/// within the section's declared count. The caller owns sorting/deduplication; this
/// codec never reorders or repairs the request.
///
/// The modeled budget deliberately reserves the **full-decode** charges (one
/// `StoredRecord` vector of length `count`, every key, every present field entry and
/// every nested value) so the pre-existing decode-admissibility surface is
/// unchanged. Physical allocation, not modeled accounting, is what becomes
/// selective.
fn position_u64(reader: &ByteReader<'_>) -> SegmentResult<u64> {
    u64::try_from(reader.position()).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::MAX,
        requested: u64::MAX,
    })
}

pub(crate) fn decode_stored_selected(
    schema: &CodecSchema,
    bytes: &[u8],
    limits: &SegmentLimits,
    selected_doc_ids: &[u64],
) -> SegmentResult<Vec<(u64, StoredRecord)>> {
    decode_stored_selected_impl(schema, bytes, limits, selected_doc_ids, None)
}

/// Validate every stored record and capture one start offset per record plus a
/// terminal offset, without materializing any record.
///
/// The caller reserves exactly `count + 1` entries before calling. Offsets are
/// relative to the start of `bytes`.
pub(crate) fn validate_stored_and_capture_offsets(
    schema: &CodecSchema,
    bytes: &[u8],
    limits: &SegmentLimits,
    offsets: &mut Vec<u64>,
) -> SegmentResult<()> {
    decode_stored_selected_impl(schema, bytes, limits, &[], Some(offsets))?;
    Ok(())
}

/// Validate one complete STORED v1 payload using a caller-owned shared budget.
///
/// The caller charges the full-decode `StoredRecord` vector exactly once. This
/// helper is shared by the legacy v1 entry points and by each 128-doc STORED v2
/// block so there is no second record/field parser.
pub(crate) fn scan_stored_v1_with_budget(
    schema: &CodecSchema,
    bytes: &[u8],
    limits: &SegmentLimits,
    budget: &mut DecodeBudget<'_>,
    selected_doc_ids: &[u64],
    mut offsets: Option<&mut Vec<u64>>,
) -> SegmentResult<Vec<(u64, StoredRecord)>> {
    for pair in selected_doc_ids.windows(2) {
        if pair[0] >= pair[1] {
            return Err(SegmentError::Corrupt {
                context: "stored selection",
                detail: "selected doc ids must be strictly increasing".to_owned(),
            });
        }
    }
    let mut reader = ByteReader::new(bytes);
    let version = reader.u16("stored version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "stored version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = reader.u64("stored count")?;
    if count > limits.max_docs() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_docs(),
            requested: count,
        });
    }
    limits.check_entries(count)?;
    let field_count = schema.field_count();
    let bitmap_len = field_count.div_ceil(8);
    // Minimum record: key length prefix(2) + key length prefix(2)
    // + bitmap(bitmap_len) + no field entries.
    super::format::count_min_bytes(
        "stored records",
        count,
        (3u64 + bitmap_len as u64).max(1),
        reader.remaining() as u64,
    )?;
    if selected_doc_ids.last().is_some_and(|last| *last >= count) {
        return Err(SegmentError::Corrupt {
            context: "stored",
            detail: "doc id out of range".to_owned(),
        });
    }
    let mut selected: Vec<(u64, StoredRecord)> = Vec::new();
    selected
        .try_reserve_exact(selected_doc_ids.len())
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: selected_doc_ids.len() as u64,
        })?;
    let mut cursor = 0usize;
    for doc_id in 0..count {
        if let Some(offsets) = offsets.as_mut() {
            let offsets = &mut **offsets;
            if offsets.len() == offsets.capacity() {
                offsets
                    .try_reserve(1)
                    .map_err(|_| SegmentError::LimitExceeded {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
            }
            offsets.push(position_u64(&reader)?);
        }
        #[cfg(test)]
        test_observation::record_full_scan_record();
        let wanted = selected_doc_ids.get(cursor).copied() == Some(doc_id);
        let key_bytes = reader.len_prefixed_u16("stored key")?;
        let key_ref = std::str::from_utf8(key_bytes).map_err(|_| SegmentError::InvalidUtf8 {
            context: "stored key",
        })?;
        budget.reserve_string(key_ref.len() as u64)?;
        let key = if wanted {
            Some(
                DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
                    context: "stored key",
                    detail: "invalid document key".to_owned(),
                })?,
            )
        } else {
            // Borrowed validation with the constructor's exact rules: non-empty and
            // at most `DocumentKey::MAX_BYTES`. No owned key is built.
            if key_ref.is_empty() || key_ref.len() > DocumentKey::MAX_BYTES {
                return Err(SegmentError::Corrupt {
                    context: "stored key",
                    detail: "invalid document key".to_owned(),
                });
            }
            None
        };
        let bitmap = reader.bytes(bitmap_len, "stored presence bitmap")?;
        let mut fields = BTreeMap::new();
        for field in schema.fields() {
            let bit = bitmap[field.id as usize / 8] & (1 << (field.id % 8)) != 0;
            if !bit {
                continue;
            }
            if !field.is_stored() {
                return Err(SegmentError::Corrupt {
                    context: "stored presence",
                    detail: "non-stored field marked present".to_owned(),
                });
            }
            let field_id = reader.u32("stored field id")?;
            if field_id != field.id {
                return Err(SegmentError::Corrupt {
                    context: "stored field order",
                    detail: "field id does not match presence bitmap".to_owned(),
                });
            }
            budget.reserve_btree_entry::<u32, FieldValues>()?;
            if wanted {
                let values =
                    decode_field_values_budgeted(&mut reader, field.field_type, limits, budget)?;
                fields.insert(field_id, values);
            } else {
                skip_field_values_budgeted(&mut reader, field.field_type, limits, budget)?;
            }
        }
        if wanted {
            let key = key.ok_or(SegmentError::Corrupt {
                context: "stored selection",
                detail: "selected record was not materialized".to_owned(),
            })?;
            selected.push((doc_id, StoredRecord { key, fields }));
            cursor += 1;
        }
    }
    if let Some(offsets) = offsets.as_mut() {
        let offsets = &mut **offsets;
        if offsets.len() == offsets.capacity() {
            offsets
                .try_reserve(1)
                .map_err(|_| SegmentError::LimitExceeded {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
        }
        offsets.push(position_u64(&reader)?);
    }
    reader.expect_end("stored")?;
    if selected.len() != selected_doc_ids.len() {
        return Err(SegmentError::Corrupt {
            context: "stored selection",
            detail: "selected doc id was not present in the stored section".to_owned(),
        });
    }
    Ok(selected)
}

/// Declared v1 record count from the 10-byte STORED header.
fn stored_v1_count(bytes: &[u8], limits: &SegmentLimits) -> SegmentResult<u64> {
    let mut reader = ByteReader::new(bytes);
    let version = reader.u16("stored version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "stored version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = reader.u64("stored count")?;
    if count > limits.max_docs() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_docs(),
            requested: count,
        });
    }
    limits.check_entries(count)?;
    Ok(count)
}

/// Legacy v1 selection entry point: one logical budget for the whole payload.
fn decode_stored_selected_impl(
    schema: &CodecSchema,
    bytes: &[u8],
    limits: &SegmentLimits,
    selected_doc_ids: &[u64],
    offsets: Option<&mut Vec<u64>>,
) -> SegmentResult<Vec<(u64, StoredRecord)>> {
    let count = stored_v1_count(bytes, limits)?;
    let mut budget = DecodeBudget::new(limits);
    // Full-decode modeled ceiling, even though only selected records are allocated.
    budget.reserve_vec::<StoredRecord>(count)?;
    scan_stored_v1_with_budget(
        schema,
        bytes,
        limits,
        &mut budget,
        selected_doc_ids,
        offsets,
    )
}

/// Decode only selected records from a previously validated offset directory.
///
/// The directory certificate was produced from the exact same immutable bytes
/// under the same limits, so this path never scans unselected records and only
/// protects the selected values' own allocations with a fresh `DecodeBudget`.
pub(crate) fn decode_stored_from_validated_offsets(
    schema: &CodecSchema,
    bytes: &[u8],
    limits: &SegmentLimits,
    ends: &[u64],
    selected_doc_ids: &[u64],
) -> SegmentResult<Vec<(u64, StoredRecord)>> {
    for pair in selected_doc_ids.windows(2) {
        if pair[0] >= pair[1] {
            return Err(SegmentError::Corrupt {
                context: "stored selection",
                detail: "selected doc ids must be strictly increasing".to_owned(),
            });
        }
    }
    let count = ends.len().checked_sub(1).ok_or(SegmentError::Corrupt {
        context: "stored",
        detail: "validated offset directory is empty".to_owned(),
    })?;
    if let Some(last) = selected_doc_ids.last() {
        if *last >= count as u64 {
            return Err(SegmentError::Corrupt {
                context: "stored",
                detail: "doc id out of range".to_owned(),
            });
        }
    }
    let field_count = schema.field_count();
    let bitmap_len = field_count.div_ceil(8);
    let mut selected: Vec<(u64, StoredRecord)> = Vec::new();
    selected
        .try_reserve_exact(selected_doc_ids.len())
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: selected_doc_ids.len() as u64,
        })?;
    let mut budget = DecodeBudget::new(limits);
    for doc_id in selected_doc_ids {
        let index = usize::try_from(*doc_id).map_err(|_| SegmentError::Corrupt {
            context: "stored",
            detail: "doc id out of range".to_owned(),
        })?;
        let start = ends.get(index).copied().ok_or(SegmentError::Corrupt {
            context: "stored",
            detail: "validated record offset out of range".to_owned(),
        })?;
        let end = ends.get(index + 1).copied().ok_or(SegmentError::Corrupt {
            context: "stored",
            detail: "validated record offset out of range".to_owned(),
        })?;
        if start > end {
            return Err(SegmentError::Corrupt {
                context: "stored",
                detail: "validated record offsets are descending".to_owned(),
            });
        }
        let start = usize::try_from(start).map_err(|_| SegmentError::Corrupt {
            context: "stored",
            detail: "validated record offset out of range".to_owned(),
        })?;
        let end = usize::try_from(end).map_err(|_| SegmentError::Corrupt {
            context: "stored",
            detail: "validated record offset out of range".to_owned(),
        })?;
        let slice = bytes.get(start..end).ok_or(SegmentError::Corrupt {
            context: "stored",
            detail: "validated record slice out of range".to_owned(),
        })?;
        #[cfg(test)]
        test_observation::record_direct_record();
        let mut reader = ByteReader::new(slice);
        let key_bytes = reader.len_prefixed_u16("stored key")?;
        let key_ref = std::str::from_utf8(key_bytes).map_err(|_| SegmentError::InvalidUtf8 {
            context: "stored key",
        })?;
        budget.reserve_string(key_ref.len() as u64)?;
        let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
            context: "stored key",
            detail: "invalid document key".to_owned(),
        })?;
        let bitmap = reader.bytes(bitmap_len, "stored presence bitmap")?;
        let mut fields = BTreeMap::new();
        for field in schema.fields() {
            let bit = bitmap[field.id as usize / 8] & (1 << (field.id % 8)) != 0;
            if !bit {
                continue;
            }
            if !field.is_stored() {
                return Err(SegmentError::Corrupt {
                    context: "stored presence",
                    detail: "non-stored field marked present".to_owned(),
                });
            }
            let field_id = reader.u32("stored field id")?;
            if field_id != field.id {
                return Err(SegmentError::Corrupt {
                    context: "stored field order",
                    detail: "field id does not match presence bitmap".to_owned(),
                });
            }
            budget.reserve_btree_entry::<u32, FieldValues>()?;
            let values =
                decode_field_values_budgeted(&mut reader, field.field_type, limits, &mut budget)?;
            fields.insert(field_id, values);
        }
        reader.expect_end("stored")?;
        selected.push((*doc_id, StoredRecord { key, fields }));
    }
    Ok(selected)
}

/// Decode the STORED section body into one record per physical doc id.
pub fn decode_stored(
    schema: &CodecSchema,
    bytes: &[u8],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<StoredRecord>> {
    let mut reader = ByteReader::new(bytes);
    let version = reader.u16("stored version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "stored version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = reader.u64("stored count")?;
    if count > limits.max_docs() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_docs(),
            requested: count,
        });
    }
    limits.check_entries(count)?;
    let mut budget = DecodeBudget::new(limits);
    budget.reserve_vec::<StoredRecord>(count)?;
    let field_count = schema.field_count();
    let bitmap_len = field_count.div_ceil(8);
    // Minimum record: key length prefix(2) + key length prefix(2)
    // + bitmap(bitmap_len) + no field entries.
    super::format::count_min_bytes(
        "stored records",
        count,
        (3u64 + bitmap_len as u64).max(1),
        reader.remaining() as u64,
    )?;
    let mut records: Vec<StoredRecord> = Vec::new();
    records
        .try_reserve_exact(
            usize::try_from(count).map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: count,
            })?,
        )
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: count,
        })?;
    for _ in 0..count {
        let key_bytes = reader.len_prefixed_u16("stored key")?;
        let key_ref = std::str::from_utf8(key_bytes).map_err(|_| SegmentError::InvalidUtf8 {
            context: "stored key",
        })?;
        budget.reserve_string(key_ref.len() as u64)?;
        let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
            context: "stored key",
            detail: "invalid document key".to_owned(),
        })?;
        let bitmap = reader.bytes(bitmap_len, "stored presence bitmap")?;
        let mut fields = BTreeMap::new();
        for field in schema.fields() {
            let bit = bitmap[field.id as usize / 8] & (1 << (field.id % 8)) != 0;
            if !bit {
                continue;
            }
            if !field.is_stored() {
                return Err(SegmentError::Corrupt {
                    context: "stored presence",
                    detail: "non-stored field marked present".to_owned(),
                });
            }
            let field_id = reader.u32("stored field id")?;
            if field_id != field.id {
                return Err(SegmentError::Corrupt {
                    context: "stored field order",
                    detail: "field id does not match presence bitmap".to_owned(),
                });
            }
            budget.reserve_btree_entry::<u32, FieldValues>()?;
            let values =
                decode_field_values_budgeted(&mut reader, field.field_type, limits, &mut budget)?;
            fields.insert(field_id, values);
        }
        records.push(StoredRecord { key, fields });
    }
    reader.expect_end("stored")?;
    Ok(records)
}

#[cfg(test)]
pub(crate) mod test_observation {
    use std::cell::Cell;

    thread_local! {
        static FULL_SCAN_RECORDS: Cell<u64> = const { Cell::new(0) };
        static DIRECT_RECORDS: Cell<u64> = const { Cell::new(0) };
    }

    pub(crate) fn reset() {
        FULL_SCAN_RECORDS.with(|value| value.set(0));
        DIRECT_RECORDS.with(|value| value.set(0));
    }

    pub(crate) fn record_full_scan_record() {
        FULL_SCAN_RECORDS.with(|value| value.set(value.get() + 1));
    }

    pub(crate) fn record_direct_record() {
        DIRECT_RECORDS.with(|value| value.set(value.get() + 1));
    }

    pub(crate) fn full_scan_records() -> u64 {
        FULL_SCAN_RECORDS.with(Cell::get)
    }

    pub(crate) fn direct_records() -> u64 {
        DIRECT_RECORDS.with(Cell::get)
    }
}

#[cfg(test)]
mod pr15g_b_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue, JsonNumber, JsonValue};
    use crate::segment::model::SegmentDocument;

    fn schema() -> CodecSchema {
        let contract = Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard"),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "tags",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "meta",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::new(true, true, false),
                ),
            ],
            None,
        )
        .expect("schema");
        let bindings = SchemaAnalyzerBindings::resolve(&contract, &AnalyzerRegistry::builtin())
            .expect("bindings");
        CodecSchema::from_contract(&contract, &bindings).expect("codec schema")
    }

    fn doc(key: &str) -> SegmentDocument {
        SegmentDocument::new(DocumentKey::new(key).expect("key"))
    }

    fn json_doc() -> FieldValue {
        FieldValue::Json(JsonValue::Object(vec![
            ("severity".to_owned(), JsonValue::Number(JsonNumber::I64(1))),
            (
                "tags".to_owned(),
                JsonValue::Array(vec![
                    JsonValue::String("red".to_owned()),
                    JsonValue::String("blue".to_owned()),
                ]),
            ),
        ]))
    }

    fn documents() -> Vec<SegmentDocument> {
        let mut zero = doc("a0");
        zero.insert(
            "title",
            FieldValues::Single(FieldValue::Text("alpha".to_owned())),
        )
        .expect("title");
        zero.insert("n", FieldValues::Single(FieldValue::I64(10)))
            .expect("n");
        zero.insert(
            "tags",
            FieldValues::Multi(vec![
                FieldValue::Keyword("red".to_owned()),
                FieldValue::Keyword("blue".to_owned()),
            ]),
        )
        .expect("tags");
        zero.insert("meta", FieldValues::Single(json_doc()))
            .expect("meta");

        let mut one = doc("a1");
        one.insert(
            "title",
            FieldValues::Single(FieldValue::Text("beta".to_owned())),
        )
        .expect("title");
        one.insert("n", FieldValues::ExplicitNull).expect("n");
        one.insert("tags", FieldValues::Empty).expect("tags");
        one.insert("meta", FieldValues::ExplicitNull).expect("meta");

        let mut two = doc("a2");
        two.insert(
            "title",
            FieldValues::Single(FieldValue::Text("gamma".to_owned())),
        )
        .expect("title");
        two.insert(
            "tags",
            FieldValues::Multi(vec![FieldValue::Keyword("green".to_owned())]),
        )
        .expect("tags");

        let mut three = doc("a3");
        three
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("delta".to_owned())),
            )
            .expect("title");
        three
            .insert("n", FieldValues::Single(FieldValue::I64(40)))
            .expect("n");
        three.insert("tags", FieldValues::Absent).expect("tags");

        let mut four = doc("a4");
        four.insert(
            "title",
            FieldValues::Single(FieldValue::Text("epsilon".to_owned())),
        )
        .expect("title");
        four.insert("n", FieldValues::Single(FieldValue::I64(50)))
            .expect("n");
        four.insert(
            "tags",
            FieldValues::Multi(vec![FieldValue::Keyword("yellow".to_owned())]),
        )
        .expect("tags");
        four.insert("meta", FieldValues::Empty).expect("meta");
        vec![zero, one, two, three, four]
    }

    fn capture(schema: &CodecSchema, body: &[u8], limits: &SegmentLimits) -> Vec<u64> {
        let mut offsets = Vec::with_capacity(16);
        validate_stored_and_capture_offsets(schema, body, limits, &mut offsets).expect("offsets");
        offsets
    }

    #[test]
    fn gbu01_zero_records_offsets_and_empty_selection() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &[], &limits).expect("encode");
        let offsets = capture(&schema, &body, &limits);
        assert_eq!(offsets, vec![10]);
        assert_eq!(body.len(), 10);
        assert!(
            decode_stored_selected(&schema, &body, &limits, &[])
                .expect("selected")
                .is_empty()
        );
        assert_eq!(
            decode_stored(&schema, &body, &limits).expect("full").len(),
            0
        );
    }

    #[test]
    fn gbu02_single_and_many_record_boundaries_are_consistent() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let docs = documents();
        for count in [1usize, 4, docs.len()] {
            let body = encode_stored(&schema, &docs[..count], &limits).expect("encode");
            let offsets = capture(&schema, &body, &limits);
            assert_eq!(offsets.len(), count + 1);
            assert_eq!(offsets[0], 10);
            assert_eq!(offsets[count], body.len() as u64);
            assert!(offsets.windows(2).all(|pair| pair[0] <= pair[1]));
            let full = decode_stored(&schema, &body, &limits).expect("full");
            for doc_id in 0..count as u64 {
                let direct = decode_stored_from_validated_offsets(
                    &schema,
                    &body,
                    &limits,
                    &offsets,
                    &[doc_id],
                )
                .expect("direct");
                assert_eq!(direct.len(), 1);
                assert_eq!(direct[0].0, doc_id);
                assert_eq!(direct[0].1, full[doc_id as usize]);
            }
        }
    }

    #[test]
    fn gbu03_selected_states_match_legacy_and_full_decode() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &documents(), &limits).expect("encode");
        let offsets = capture(&schema, &body, &limits);
        let selected = [0u64, 2, 4];
        let legacy =
            decode_stored_selected(&schema, &body, &limits, &selected).expect("legacy selected");
        let direct =
            decode_stored_from_validated_offsets(&schema, &body, &limits, &offsets, &selected)
                .expect("direct selected");
        assert_eq!(direct, legacy);
        let full = decode_stored(&schema, &body, &limits).expect("full");
        for (doc_id, record) in &direct {
            assert_eq!(record, &full[*doc_id as usize]);
        }
    }

    #[test]
    fn gbu04_invalid_unselected_key_fails_validation_and_legacy_alike() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &documents(), &limits).expect("encode");
        let offsets = capture(&schema, &body, &limits);
        let mut corrupt = body.clone();
        let record_start = offsets[1] as usize;
        // Record 1 is unselected in the access below; corrupt its first key byte.
        corrupt[record_start + 2] = 0xFF;
        let selected_error =
            decode_stored_selected(&schema, &corrupt, &limits, &[0]).expect_err("legacy");
        assert!(matches!(selected_error, SegmentError::InvalidUtf8 { .. }));
        let mut rejected = Vec::with_capacity(8);
        let capture_error =
            validate_stored_and_capture_offsets(&schema, &corrupt, &limits, &mut rejected)
                .expect_err("capture");
        assert!(matches!(capture_error, SegmentError::InvalidUtf8 { .. }));
    }

    #[test]
    fn gbu05_corrupt_unselected_nested_json_is_rejected() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let mut first = documents()[0].clone();
        let mut second = doc("b1");
        second
            .insert("meta", FieldValues::Single(json_doc()))
            .expect("meta");
        first
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("first".to_owned())),
            )
            .expect("title");
        let docs = vec![first, second];
        let body = encode_stored(&schema, &docs, &limits).expect("encode");
        let offsets = capture(&schema, &body, &limits);
        let mut corrupt = body.clone();
        // The final byte of the second JSON object's closing brace is unselected.
        corrupt[offsets[2] as usize - 1] ^= 0xFF;
        let selected = decode_stored_selected(&schema, &corrupt, &limits, &[0])
            .expect_err("legacy must validate the unselected JSON");
        let mut rejected = Vec::new();
        let captured =
            validate_stored_and_capture_offsets(&schema, &corrupt, &limits, &mut rejected)
                .expect_err("capture must validate the unselected JSON");
        assert_eq!(
            std::mem::discriminant(&selected),
            std::mem::discriminant(&captured),
            "legacy={selected:?} capture={captured:?}"
        );
    }

    #[test]
    fn gbu06_modeled_decode_limit_is_not_bypassed() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &documents(), &limits).expect("encode");
        let tiny = limits.with_max_section_decode_bytes(0);
        assert!(matches!(
            decode_stored_selected(&schema, &body, &tiny, &[0]),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn gbu07_tiny_allocation_and_entry_limits_are_typed() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &documents(), &limits).expect("encode");
        let tiny = limits.with_max_single_allocation(1);
        assert!(matches!(
            decode_stored_selected(&schema, &body, &tiny, &[0]),
            Err(SegmentError::LimitExceeded { .. })
        ));
        let tiny_entries = limits.with_max_decoded_entries(1);
        assert!(matches!(
            decode_stored_selected(&schema, &body, &tiny_entries, &[0]),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn gbu08_malformed_selection_errors_match_legacy_order() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &documents(), &limits).expect("encode");
        let offsets = capture(&schema, &body, &limits);
        for selection in [&[2u64, 2][..], &[3, 1][..], &[99][..]] {
            let legacy = decode_stored_selected(&schema, &body, &limits, selection)
                .expect_err("legacy invalid selection");
            assert!(matches!(legacy, SegmentError::Corrupt { .. }));
            let direct =
                decode_stored_from_validated_offsets(&schema, &body, &limits, &offsets, selection)
                    .expect_err("direct invalid selection");
            assert!(matches!(direct, SegmentError::Corrupt { .. }));
        }
    }

    #[test]
    fn gbu09_empty_selection_validates_every_record() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let docs = documents();
        let body = encode_stored(&schema, &docs, &limits).expect("encode");
        test_observation::reset();
        let mut offsets = Vec::with_capacity(16);
        validate_stored_and_capture_offsets(&schema, &body, &limits, &mut offsets)
            .expect("capture");
        assert_eq!(test_observation::full_scan_records(), docs.len() as u64);
        assert_eq!(test_observation::direct_records(), 0);
        test_observation::reset();
        assert!(
            decode_stored_selected(&schema, &body, &limits, &[])
                .expect("empty")
                .is_empty()
        );
        assert_eq!(test_observation::full_scan_records(), docs.len() as u64);
    }

    #[test]
    fn gbu11_nested_json_direct_matches_full() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &documents(), &limits).expect("encode");
        let offsets = capture(&schema, &body, &limits);
        let direct =
            decode_stored_from_validated_offsets(&schema, &body, &limits, &offsets, &[0, 1, 4])
                .expect("direct");
        let full = decode_stored(&schema, &body, &limits).expect("full");
        assert_eq!(direct[0].1, full[0]);
        assert_eq!(direct[1].1, full[1]);
        assert_eq!(direct[2].1, full[4]);
        let meta_id = schema.field_id("meta").expect("meta field");
        assert!(matches!(
            direct[0].1.get(meta_id),
            FieldValues::Single(FieldValue::Json(_))
        ));
    }

    #[test]
    fn gbu12_injected_invalid_offsets_are_typed_and_never_panic() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored(&schema, &documents(), &limits).expect("encode");
        assert!(matches!(
            decode_stored_from_validated_offsets(&schema, &body, &limits, &[], &[0]),
            Err(SegmentError::Corrupt { .. })
        ));
        assert!(matches!(
            decode_stored_from_validated_offsets(&schema, &body, &limits, &[10, 5], &[0]),
            Err(SegmentError::Corrupt { .. })
        ));
        assert!(matches!(
            decode_stored_from_validated_offsets(
                &schema,
                &body,
                &limits,
                &[10, body.len() as u64 + 1],
                &[0]
            ),
            Err(SegmentError::Corrupt { .. })
        ));
        assert!(matches!(
            decode_stored_from_validated_offsets(&schema, &body, &limits, &[10, 10], &[1]),
            Err(SegmentError::Corrupt { .. })
        ));
    }

    fn many_docs(count: usize) -> Vec<SegmentDocument> {
        (0..count)
            .map(|index| doc(&format!("k{index:04}")))
            .collect()
    }

    #[test]
    fn gc_br02a_k100_from_128_visits_only_selected() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let docs = many_docs(128);
        let body = encode_stored(&schema, &docs, &limits).expect("encode");
        let full = decode_stored(&schema, &body, &limits).expect("full");
        let offsets = capture(&schema, &body, &limits);
        let selected: Vec<u64> = (0..100).collect();
        test_observation::reset();
        let direct =
            decode_stored_from_validated_offsets(&schema, &body, &limits, &offsets, &selected)
                .expect("direct");
        assert_eq!(test_observation::direct_records(), 100);
        assert_eq!(test_observation::full_scan_records(), 0);
        assert_eq!(direct.len(), 100);
        for (doc_id, record) in &direct {
            assert_eq!(record, &full[*doc_id as usize]);
        }
    }

    #[test]
    fn gc_br02b_k100_strided_from_1024_visits_only_selected() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let docs = many_docs(1024);
        let body = encode_stored(&schema, &docs, &limits).expect("encode");
        let full = decode_stored(&schema, &body, &limits).expect("full");
        let offsets = capture(&schema, &body, &limits);
        let selected: Vec<u64> = (0..100).map(|index| index * 10).collect();
        test_observation::reset();
        let direct =
            decode_stored_from_validated_offsets(&schema, &body, &limits, &offsets, &selected)
                .expect("direct");
        assert_eq!(test_observation::direct_records(), 100);
        assert_eq!(test_observation::full_scan_records(), 0);
        let ids: Vec<u64> = direct.iter().map(|(doc_id, _)| *doc_id).collect();
        assert_eq!(ids, selected);
        for (doc_id, record) in &direct {
            assert_eq!(record, &full[*doc_id as usize]);
        }
    }

    #[test]
    fn gbu15_direct_reads_visit_only_selected_records() {
        let schema = schema();
        let limits = SegmentLimits::default();
        let docs = documents();
        let body = encode_stored(&schema, &docs, &limits).expect("encode");
        let offsets = capture(&schema, &body, &limits);
        test_observation::reset();
        let _ = decode_stored_from_validated_offsets(&schema, &body, &limits, &offsets, &[0])
            .expect("one");
        assert_eq!(test_observation::direct_records(), 1);
        assert_eq!(test_observation::full_scan_records(), 0);
        let _ = decode_stored_from_validated_offsets(&schema, &body, &limits, &offsets, &[1, 3, 4])
            .expect("three");
        assert_eq!(test_observation::direct_records(), 4);
        assert_eq!(test_observation::full_scan_records(), 0);
    }
}
