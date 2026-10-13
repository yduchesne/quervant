//! Stored source documents with the shared five-state vocabulary (F06).

use std::collections::BTreeMap;

use crate::contract::document::{DocumentKey, FieldValues};

use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::model::SegmentDocument;
use super::schema::CodecSchema;
use super::value::{decode_field_values, encode_field_values};

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
    limits.check_alloc::<StoredRecord>(count)?;
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
        let key = std::str::from_utf8(key_bytes)
            .map_err(|_| SegmentError::InvalidUtf8 {
                context: "stored key",
            })
            .and_then(|text| {
                DocumentKey::new(text).map_err(|_| SegmentError::Corrupt {
                    context: "stored key",
                    detail: "invalid document key".to_owned(),
                })
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
            let values = decode_field_values(&mut reader, field.field_type, limits)?;
            fields.insert(field_id, values);
        }
        records.push(StoredRecord { key, fields });
    }
    reader.expect_end("stored")?;
    Ok(records)
}
