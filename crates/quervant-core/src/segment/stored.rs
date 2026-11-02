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
pub(crate) fn decode_stored_selected(
    schema: &CodecSchema,
    bytes: &[u8],
    limits: &SegmentLimits,
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
    // Full-decode modeled ceiling, even though only selected records are allocated.
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
                let values = decode_field_values_budgeted(
                    &mut reader,
                    field.field_type,
                    limits,
                    &mut budget,
                )?;
                fields.insert(field_id, values);
            } else {
                skip_field_values_budgeted(&mut reader, field.field_type, limits, &mut budget)?;
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
    reader.expect_end("stored")?;
    if selected.len() != selected_doc_ids.len() {
        return Err(SegmentError::Corrupt {
            context: "stored selection",
            detail: "selected doc id was not present in the stored section".to_owned(),
        });
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
