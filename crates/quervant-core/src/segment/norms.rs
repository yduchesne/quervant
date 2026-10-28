//! Persistent BM25 field norms (PR 7 Amendment 05).
//!
//! An immutable, optional segment section holding one analyzed-token count per
//! physical document and scoring field. The section is optional for legacy
//! compatibility, but a segment that emits it must also declare
//! `FEATURE_FIELD_NORMS` as a **required** feature (see `format`). Section and
//! feature must agree: neither is a valid legacy segment, both are validated and
//! used, and any mismatch is corruption.
//!
//! The unit of a norm is an analyzed [`crate::analysis::Token`] occurrence that
//! is emitted to postings for the field (including repetitions and multi-valued
//! values, excluding stopwords that were filtered out). It is not a unique-term
//! count, a position, or a source-byte length.

use crate::contract::value::FieldType;

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::schema::CodecSchema;

/// Payload version for the `FieldNorms` section.
pub const FIELD_NORMS_PAYLOAD_VERSION: u16 = 1;

/// Decoded norms for one scoring field.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FieldNorms {
    field_id: u32,
    lengths: Vec<u64>,
    total_token_count: u64,
    documents_with_tokens: u64,
}

impl FieldNorms {
    /// Field id.
    #[must_use]
    pub const fn field_id(&self) -> u32 {
        self.field_id
    }

    /// Token count for one physical document id, bounds-checked.
    pub fn length(&self, physical_doc_id: u64) -> SegmentResult<u64> {
        let index = usize::try_from(physical_doc_id).map_err(|_| SegmentError::Corrupt {
            context: "field norms",
            detail: "physical doc id out of range".to_owned(),
        })?;
        self.lengths
            .get(index)
            .copied()
            .ok_or(SegmentError::Corrupt {
                context: "field norms",
                detail: "physical doc id out of range".to_owned(),
            })
    }

    /// All physical-doc lengths in physical order.
    #[must_use]
    pub fn lengths(&self) -> &[u64] {
        &self.lengths
    }

    /// Sum of all physical-doc lengths.
    #[must_use]
    pub const fn total_token_count(&self) -> u64 {
        self.total_token_count
    }

    /// Number of physical docs with a nonzero length.
    #[must_use]
    pub const fn documents_with_tokens(&self) -> u64 {
        self.documents_with_tokens
    }
}

/// Decoded norms for every scoring field of one segment.
///
/// `fields` is a strictly ascending `(field_id, norms)` vector rather than a
/// `BTreeMap`: the verified immutable segment state must have a closed,
/// auditable allocation graph (`Vec`/`String`/`Arc` only) that can be charged
/// before allocation. Lookup is a binary search and the acceptance/rejection
/// semantics are unchanged.
#[derive(Debug, Default)]
pub struct FieldNormsReader {
    doc_count: u64,
    fields: Vec<(u32, FieldNorms)>,
}

impl FieldNormsReader {
    /// Physical document count the norms were validated against.
    #[must_use]
    pub const fn doc_count(&self) -> u64 {
        self.doc_count
    }

    /// Norms for one field, if present.
    #[must_use]
    pub fn field(&self, field_id: u32) -> Option<&FieldNorms> {
        self.fields
            .binary_search_by_key(&field_id, |(id, _)| *id)
            .ok()
            .map(|index| &self.fields[index].1)
    }

    /// Field ids present, ascending.
    pub fn field_ids(&self) -> impl Iterator<Item = u32> + '_ {
        self.fields.iter().map(|(field_id, _)| *field_id)
    }

    /// Decode and fully validate a `FieldNorms` payload.
    ///
    /// The schema is required to reject unknown/non-scoring/duplicate/missing
    /// field ids and to assert exactly the scoring fields are present.
    pub fn decode(
        bytes: &[u8],
        doc_count: u64,
        schema: &CodecSchema,
        limits: &SegmentLimits,
    ) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("field norms version")?;
        if version != FIELD_NORMS_PAYLOAD_VERSION {
            return Err(SegmentError::Corrupt {
                context: "field norms version",
                detail: format!("unsupported {version}"),
            });
        }
        let declared_doc_count = reader.u64("field norms doc count")?;
        if declared_doc_count != doc_count {
            return Err(SegmentError::Corrupt {
                context: "field norms",
                detail: "declared doc count does not match segment doc count".to_owned(),
            });
        }
        let field_count = reader.u32("field norms field count")?;
        let total_entries =
            u64::from(field_count)
                .checked_mul(doc_count)
                .ok_or(SegmentError::LimitExceeded {
                    limit: limits.max_decoded_entries(),
                    requested: u64::MAX,
                })?;
        limits.check_entries(total_entries)?;
        // Minimum encoded bytes per field header and per length varint.
        super::format::count_min_bytes(
            "field norms entries",
            total_entries,
            1,
            reader.remaining() as u64,
        )?;

        let expected: Vec<u32> = scoring_field_ids(schema);
        let mut budget = DecodeBudget::new(limits);
        budget.reserve_vec::<(u32, FieldNorms)>(u64::from(field_count))?;
        let mut fields: Vec<(u32, FieldNorms)> = Vec::new();
        fields
            .try_reserve_exact(usize::try_from(field_count).map_err(|_| {
                SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: u64::from(field_count),
                }
            })?)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: u64::from(field_count),
            })?;
        let mut previous: Option<u32> = None;
        for _ in 0..field_count {
            let field_id = reader.u32("field norms field id")?;
            if let Some(previous) = previous {
                if field_id <= previous {
                    return Err(SegmentError::Corrupt {
                        context: "field norms",
                        detail: "field ids are not strictly increasing".to_owned(),
                    });
                }
            }
            previous = Some(field_id);
            let codec_field = schema.field(field_id).ok_or(SegmentError::Corrupt {
                context: "field norms",
                detail: "unknown field id".to_owned(),
            })?;
            if !is_scoring_field_type(codec_field.field_type) || !codec_field.is_indexed() {
                return Err(SegmentError::Corrupt {
                    context: "field norms",
                    detail: "field id is not an indexed scoring field".to_owned(),
                });
            }
            let declared_total = reader.u64("field norms total")?;
            let declared_nonzero = reader.u64("field norms documents with tokens")?;
            if declared_nonzero > doc_count {
                return Err(SegmentError::Corrupt {
                    context: "field norms",
                    detail: "documents-with-tokens exceeds doc count".to_owned(),
                });
            }
            budget.reserve_vec::<u64>(doc_count)?;
            let capacity = usize::try_from(doc_count).map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: doc_count,
            })?;
            let mut lengths: Vec<u64> = Vec::new();
            lengths
                .try_reserve_exact(capacity)
                .map_err(|_| SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: doc_count,
                })?;
            let mut computed_total: u64 = 0;
            let mut computed_nonzero: u64 = 0;
            for _ in 0..doc_count {
                let length = reader.varint("field norms length")?;
                computed_total =
                    computed_total
                        .checked_add(length)
                        .ok_or(SegmentError::LimitExceeded {
                            limit: u64::MAX,
                            requested: u64::MAX,
                        })?;
                if length > 0 {
                    computed_nonzero += 1;
                }
                lengths.push(length);
            }
            if computed_total != declared_total || computed_nonzero != declared_nonzero {
                return Err(SegmentError::Corrupt {
                    context: "field norms",
                    detail: "declared totals do not match decoded lengths".to_owned(),
                });
            }
            fields.push((
                field_id,
                FieldNorms {
                    field_id,
                    lengths,
                    total_token_count: declared_total,
                    documents_with_tokens: declared_nonzero,
                },
            ));
        }
        reader.expect_end("field norms")?;

        for field_id in expected {
            if fields
                .binary_search_by_key(&field_id, |(id, _)| *id)
                .is_err()
            {
                return Err(SegmentError::Corrupt {
                    context: "field norms",
                    detail: "missing required scoring field".to_owned(),
                });
            }
        }
        Ok(Self { doc_count, fields })
    }
}

/// The ordered scoring field ids for a schema: indexed `Text`/`Keyword` fields,
/// which are exactly the fields the builder analyzes into postings.
#[must_use]
pub fn scoring_field_ids(schema: &CodecSchema) -> Vec<u32> {
    schema
        .fields()
        .iter()
        .filter(|field| field.is_indexed() && is_scoring_field_type(field.field_type))
        .map(|field| field.id)
        .collect()
}

fn is_scoring_field_type(field_type: FieldType) -> bool {
    matches!(field_type, FieldType::Text | FieldType::Keyword)
}

/// Encode a `FieldNorms` payload. `fields` must be ordered by ascending field id
/// and each length vector must be exactly `doc_count` long.
pub fn encode_field_norms(
    doc_count: u64,
    fields: &[(u32, Vec<u64>)],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let mut total_entries: u64 = 0;
    for (_, lengths) in fields {
        if lengths.len() as u64 != doc_count {
            return Err(SegmentError::Corrupt {
                context: "field norms",
                detail: "length vector does not match doc count".to_owned(),
            });
        }
        total_entries =
            total_entries
                .checked_add(doc_count)
                .ok_or(SegmentError::LimitExceeded {
                    limit: limits.max_decoded_entries(),
                    requested: u64::MAX,
                })?;
    }
    limits.check_entries(total_entries)?;
    let mut writer = ByteWriter::new();
    writer.u16(FIELD_NORMS_PAYLOAD_VERSION);
    writer.u64(doc_count);
    writer.u32(
        u32::try_from(fields.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: fields.len() as u64,
        })?,
    );
    let mut previous: Option<u32> = None;
    for (field_id, lengths) in fields {
        if let Some(previous) = previous {
            if *field_id <= previous {
                return Err(SegmentError::Corrupt {
                    context: "field norms",
                    detail: "field ids are not strictly increasing".to_owned(),
                });
            }
        }
        previous = Some(*field_id);
        let mut total: u64 = 0;
        let mut nonzero: u64 = 0;
        for &length in lengths {
            total = total
                .checked_add(length)
                .ok_or(SegmentError::LimitExceeded {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            if length > 0 {
                nonzero += 1;
            }
        }
        writer.u32(*field_id);
        writer.u64(total);
        writer.u64(nonzero);
        for &length in lengths {
            writer.varint(length);
        }
    }
    Ok(writer.into_vec())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};

    fn schema() -> CodecSchema {
        let contract = crate::contract::schema::Schema::new(
            vec![
                FieldDefinition::new(
                    "body",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
            ],
            None,
        )
        .unwrap();
        let registry = crate::analysis::AnalyzerRegistry::builtin();
        let bindings =
            crate::analysis::SchemaAnalyzerBindings::resolve(&contract, &registry).unwrap();
        CodecSchema::from_contract(&contract, &bindings).unwrap()
    }

    #[test]
    fn round_trip_and_lookup() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        assert_eq!(ids.len(), 2);
        let payload = encode_field_norms(
            3,
            &[(ids[0], vec![0, 2, 5]), (ids[1], vec![1, 0, 0])],
            &SegmentLimits::default(),
        )
        .unwrap();
        let reader =
            FieldNormsReader::decode(&payload, 3, &schema, &SegmentLimits::default()).unwrap();
        let first = reader.field(ids[0]).unwrap();
        assert_eq!(first.length(0).unwrap(), 0);
        assert_eq!(first.length(1).unwrap(), 2);
        assert_eq!(first.length(2).unwrap(), 5);
        assert_eq!(first.total_token_count(), 7);
        assert_eq!(first.documents_with_tokens(), 2);
        assert!(first.length(3).is_err());
    }

    #[test]
    fn missing_required_field_is_corrupt() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let payload =
            encode_field_norms(1, &[(ids[0], vec![1])], &SegmentLimits::default()).unwrap();
        assert!(matches!(
            FieldNormsReader::decode(&payload, 1, &schema, &SegmentLimits::default()),
            Err(SegmentError::Corrupt { .. })
        ));
    }

    #[test]
    fn wrong_total_or_nonzero_is_corrupt() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let bad = {
            let mut writer = ByteWriter::new();
            writer.u16(FIELD_NORMS_PAYLOAD_VERSION);
            writer.u64(2);
            writer.u32(2);
            writer.u32(ids[0]);
            writer.u64(99); // wrong total
            writer.u64(2);
            writer.varint(3);
            writer.varint(4);
            writer.u32(ids[1]);
            writer.u64(0);
            writer.u64(0);
            writer.varint(0);
            writer.varint(0);
            writer.into_vec()
        };
        assert!(matches!(
            FieldNormsReader::decode(&bad, 2, &schema, &SegmentLimits::default()),
            Err(SegmentError::Corrupt { .. })
        ));
    }

    #[test]
    fn trailing_bytes_and_bad_version_are_corrupt() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let mut payload = encode_field_norms(
            1,
            &[(ids[0], vec![1]), (ids[1], vec![0])],
            &SegmentLimits::default(),
        )
        .unwrap();
        payload.push(0xFF);
        assert!(matches!(
            FieldNormsReader::decode(&payload, 1, &schema, &SegmentLimits::default()),
            Err(SegmentError::Corrupt { .. })
        ));

        let mut bad_version = encode_field_norms(
            1,
            &[(ids[0], vec![1]), (ids[1], vec![0])],
            &SegmentLimits::default(),
        )
        .unwrap();
        bad_version[0] = 2;
        assert!(matches!(
            FieldNormsReader::decode(&bad_version, 1, &schema, &SegmentLimits::default()),
            Err(SegmentError::Corrupt { .. })
        ));
    }

    // A5-T15 — declared sizes are rejected against decoder budgets before allocation.
    #[test]
    fn declared_size_beyond_budget_is_rejected() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let payload = encode_field_norms(
            2_000,
            &[(ids[0], vec![1; 2_000]), (ids[1], vec![0; 2_000])],
            &SegmentLimits::default(),
        )
        .unwrap();
        let tight = SegmentLimits::default().with_max_section_decode_bytes(100);
        assert!(matches!(
            FieldNormsReader::decode(&payload, 2_000, &schema, &tight),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    // S1 — the sorted-vector representation preserves ordering, exact lookup and
    // the duplicate/out-of-order rejection of the former map.
    #[test]
    fn sorted_vec_lookup_matches_former_map_semantics() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let payload = encode_field_norms(
            4,
            &[(ids[0], vec![7, 0, 3, 1]), (ids[1], vec![0, 0, 2, 9])],
            &SegmentLimits::default(),
        )
        .unwrap();
        let reader =
            FieldNormsReader::decode(&payload, 4, &schema, &SegmentLimits::default()).unwrap();
        assert_eq!(reader.field_ids().collect::<Vec<_>>(), ids);
        for field_id in [ids[0], ids[1]] {
            assert!(reader.field(field_id).is_some());
        }
        assert!(reader.field(u32::MAX).is_none());
        assert_eq!(reader.field(ids[0]).unwrap().lengths(), &[7, 0, 3, 1]);
        assert_eq!(reader.field(ids[1]).unwrap().lengths(), &[0, 0, 2, 9]);
        assert_eq!(reader.doc_count(), 4);
    }

    #[test]
    fn empty_and_singleton_field_sets_are_supported() {
        // A schema with no indexed text/keyword field has no scoring fields, so a
        // zero-length norms payload is valid for it.
        let non_scoring = {
            let contract = crate::contract::schema::Schema::new(
                vec![FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                )],
                None,
            )
            .unwrap();
            let registry = crate::analysis::AnalyzerRegistry::builtin();
            let bindings =
                crate::analysis::SchemaAnalyzerBindings::resolve(&contract, &registry).unwrap();
            CodecSchema::from_contract(&contract, &bindings).unwrap()
        };
        assert!(scoring_field_ids(&non_scoring).is_empty());
        let empty = {
            let mut writer = ByteWriter::new();
            writer.u16(FIELD_NORMS_PAYLOAD_VERSION);
            writer.u64(0);
            writer.u32(0);
            writer.into_vec()
        };
        let reader =
            FieldNormsReader::decode(&empty, 0, &non_scoring, &SegmentLimits::default()).unwrap();
        assert_eq!(reader.field_ids().count(), 0);

        let schema = schema();
        let ids = scoring_field_ids(&schema);
        assert!(reader.field(ids[0]).is_none());

        let singleton = encode_field_norms(
            1,
            &[(ids[0], vec![4]), (ids[1], vec![0])],
            &SegmentLimits::default(),
        )
        .unwrap();
        let reader =
            FieldNormsReader::decode(&singleton, 1, &schema, &SegmentLimits::default()).unwrap();
        assert_eq!(reader.field_ids().collect::<Vec<_>>(), ids);
        assert_eq!(reader.field(ids[0]).unwrap().length(0).unwrap(), 4);
    }

    // A5-T13 — duplicate/out-of-order field ids are corruption.
    #[test]
    fn field_id_ordering_violations_are_corrupt() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let duplicate = {
            let mut writer = ByteWriter::new();
            writer.u16(FIELD_NORMS_PAYLOAD_VERSION);
            writer.u64(1);
            writer.u32(2);
            writer.u32(ids[0]);
            writer.u64(1);
            writer.u64(1);
            writer.varint(1);
            writer.u32(ids[0]);
            writer.u64(0);
            writer.u64(0);
            writer.varint(0);
            writer.into_vec()
        };
        assert!(matches!(
            FieldNormsReader::decode(&duplicate, 1, &schema, &SegmentLimits::default()),
            Err(SegmentError::Corrupt { .. })
        ));
        let out_of_order = {
            let mut writer = ByteWriter::new();
            writer.u16(FIELD_NORMS_PAYLOAD_VERSION);
            writer.u64(1);
            writer.u32(2);
            writer.u32(ids[1]);
            writer.u64(0);
            writer.u64(0);
            writer.varint(0);
            writer.u32(ids[0]);
            writer.u64(1);
            writer.u64(1);
            writer.varint(1);
            writer.into_vec()
        };
        assert!(matches!(
            FieldNormsReader::decode(&out_of_order, 1, &schema, &SegmentLimits::default()),
            Err(SegmentError::Corrupt { .. })
        ));
    }

    // A5-T14 — declared doc count must match the segment doc count.
    #[test]
    fn wrong_doc_count_is_corrupt() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let payload = encode_field_norms(
            1,
            &[(ids[0], vec![1]), (ids[1], vec![0])],
            &SegmentLimits::default(),
        )
        .unwrap();
        assert!(matches!(
            FieldNormsReader::decode(&payload, 2, &schema, &SegmentLimits::default()),
            Err(SegmentError::Corrupt { .. })
        ));
    }

    // A5-T11 — every truncation is rejected without panic or fallback.
    #[test]
    fn truncated_payload_is_rejected() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let payload = encode_field_norms(
            4,
            &[(ids[0], vec![1, 2, 3, 4]), (ids[1], vec![0, 0, 0, 0])],
            &SegmentLimits::default(),
        )
        .unwrap();
        for cut in 1..payload.len() {
            assert!(
                FieldNormsReader::decode(&payload[..cut], 4, &schema, &SegmentLimits::default())
                    .is_err(),
                "truncated payload at {cut} bytes must be rejected"
            );
        }
    }

    // A5-T15 — the entry budget accepts the exact count and rejects one over.
    #[test]
    fn entry_budget_exact_is_accepted_one_over_rejected() {
        let schema = schema();
        let ids = scoring_field_ids(&schema);
        let payload = encode_field_norms(
            3,
            &[(ids[0], vec![1, 2, 3]), (ids[1], vec![0, 0, 0])],
            &SegmentLimits::default(),
        )
        .unwrap();
        // 2 fields * 3 docs = 6 entries.
        assert!(
            FieldNormsReader::decode(
                &payload,
                3,
                &schema,
                &SegmentLimits::default().with_max_decoded_entries(6)
            )
            .is_ok()
        );
        assert!(matches!(
            FieldNormsReader::decode(
                &payload,
                3,
                &schema,
                &SegmentLimits::default().with_max_decoded_entries(5)
            ),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }
}
