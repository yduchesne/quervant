//! Typed columnar blocks with bounded document-N access (F07).
//!
//! Each column is split into uniform blocks of the **persisted** `block_docs`
//! rows. Doc `N` is located by O(1) directory arithmetic and touches at most its
//! containing block.

use std::cell::Cell;

use crate::contract::document::FieldValues;
use crate::contract::value::{FieldType, FieldValue};

use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::model::SegmentDocument;
use super::schema::{CodecSchema, field_type_tag};
use super::value::{
    STATE_ABSENT, STATE_EMPTY_MULTI, STATE_EXPLICIT_NULL, STATE_MULTI, STATE_SINGLE, decode_scalar,
    encode_scalar, state_of,
};

/// Fixed-width single-valued layout.
pub const LAYOUT_FIXED_SINGLE: u8 = 0x01;
/// Variable-length / multi-valued layout.
pub const LAYOUT_VARIABLE_MULTI: u8 = 0x02;

const COLUMN_HEADER_LEN: usize = 46;
const BLOCK_ENTRY_LEN: usize = 36;

/// A typed group-key component.
#[derive(Debug, Clone, Copy)]
pub enum GroupComponent<'a> {
    /// Field is absent.
    Missing,
    /// Field is explicitly null.
    Null,
    /// Field has a typed scalar value.
    Value(&'a FieldValue),
}

/// Encode a typed, collision-free group key.
pub fn encode_group_key(components: &[GroupComponent<'_>]) -> SegmentResult<Vec<u8>> {
    let mut writer = ByteWriter::new();
    writer.varint(components.len() as u64);
    for component in components {
        match component {
            GroupComponent::Missing => writer.u8(0),
            GroupComponent::Null => writer.u8(1),
            GroupComponent::Value(value) => {
                writer.u8(2);
                writer.u8(field_type_tag(value.field_type()));
                encode_scalar(&mut writer, value.field_type(), value)?;
            }
        }
    }
    Ok(writer.into_vec())
}

fn layout_for(field_type: FieldType, cardinality: crate::contract::document::Cardinality) -> u8 {
    if cardinality == crate::contract::document::Cardinality::Single
        && matches!(
            field_type,
            FieldType::Bool
                | FieldType::I64
                | FieldType::U64
                | FieldType::F64
                | FieldType::Timestamp
                | FieldType::GeoPoint
        )
    {
        LAYOUT_FIXED_SINGLE
    } else {
        LAYOUT_VARIABLE_MULTI
    }
}

fn slot_width(field_type: FieldType) -> usize {
    match field_type {
        FieldType::Bool => 1,
        FieldType::I64 | FieldType::U64 | FieldType::F64 | FieldType::Timestamp => 8,
        FieldType::GeoPoint => 16,
        _ => 0,
    }
}

struct BlockPlan {
    state: Vec<u8>,
    values: Vec<u8>,
}

struct ColumnPlan {
    field_id: u32,
    type_tag: u8,
    layout: u8,
    doc_count: u64,
    block_docs: u32,
    blocks: Vec<BlockPlan>,
}

/// Encode the COLUMNS section body.
pub fn encode_columns(
    schema: &CodecSchema,
    docs: &[SegmentDocument],
    block_docs: u32,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    if block_docs == 0 {
        return Err(SegmentError::InvalidColumnGeometry {
            detail: "zero block_docs",
        });
    }
    let mut plans: Vec<ColumnPlan> = Vec::new();
    for field in schema.fields() {
        if !field.is_columnar() {
            continue;
        }
        let layout = layout_for(field.field_type, field.cardinality);
        let width = slot_width(field.field_type);
        let mut blocks: Vec<BlockPlan> = Vec::new();
        for chunk in docs.chunks(block_docs as usize) {
            let mut state = Vec::with_capacity(chunk.len());
            let mut values = Vec::new();
            if layout == LAYOUT_FIXED_SINGLE {
                for doc in chunk {
                    let values_state = doc
                        .fields
                        .get(&field.name)
                        .cloned()
                        .unwrap_or(FieldValues::Absent);
                    state.push(state_of(&values_state));
                    match values_state {
                        FieldValues::Single(ref value) => {
                            let mut slot = ByteWriter::new();
                            encode_scalar(&mut slot, field.field_type, value)?;
                            debug_assert_eq!(slot.len(), width);
                            values.extend_from_slice(slot.as_slice());
                        }
                        _ => values.extend(std::iter::repeat_n(0u8, width)),
                    }
                }
            } else {
                let mut offsets: Vec<u64> = Vec::with_capacity(chunk.len() + 1);
                offsets.push(0);
                let mut value_area = ByteWriter::new();
                for doc in chunk {
                    let values_state = doc
                        .fields
                        .get(&field.name)
                        .cloned()
                        .unwrap_or(FieldValues::Absent);
                    state.push(state_of(&values_state));
                    match values_state {
                        FieldValues::Single(ref value) => {
                            encode_scalar(&mut value_area, field.field_type, value)?;
                        }
                        FieldValues::Multi(ref list) => {
                            let mut count = ByteWriter::new();
                            count.varint(list.len() as u64);
                            value_area.bytes(count.as_slice());
                            for value in list {
                                encode_scalar(&mut value_area, field.field_type, value)?;
                            }
                        }
                        _ => {}
                    }
                    offsets.push(value_area.len() as u64);
                }
                let mut table = ByteWriter::new();
                for offset in offsets {
                    table.u64(offset);
                }
                let mut combined = table.into_vec();
                combined.extend_from_slice(value_area.as_slice());
                values = combined;
            }
            blocks.push(BlockPlan { state, values });
        }
        plans.push(ColumnPlan {
            field_id: field.id,
            type_tag: field_type_tag(field.field_type),
            layout,
            doc_count: docs.len() as u64,
            block_docs,
            blocks,
        });
    }
    limits.check_entries(docs.len() as u64)?;

    let header_size = 6 + plans.len() * COLUMN_HEADER_LEN;
    let mut cursor = header_size;
    let mut placements: Vec<(u64, u64)> = Vec::with_capacity(plans.len());
    for plan in &plans {
        let dir_offset = cursor as u64;
        let dir_len = (plan.blocks.len() * BLOCK_ENTRY_LEN) as u64;
        cursor += dir_len as usize;
        for block in &plan.blocks {
            cursor += block.state.len() + block.values.len();
        }
        placements.push((dir_offset, dir_len));
    }

    let mut writer = ByteWriter::new();
    writer.u16(1); // columns_version
    writer.u32(
        u32::try_from(plans.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: plans.len() as u64,
        })?,
    );
    for (plan, (dir_offset, dir_len)) in plans.iter().zip(&placements) {
        writer.u32(plan.field_id);
        writer.u8(plan.type_tag);
        writer.u8(plan.layout);
        writer.u64(plan.doc_count);
        writer.u32(
            u32::try_from(plan.blocks.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: plan.blocks.len() as u64,
            })?,
        );
        writer.u32(plan.block_docs);
        writer.u64(0); // state_bitmap_len (reserved)
        writer.u64(*dir_offset);
        writer.u64(*dir_len);
    }
    debug_assert_eq!(writer.len(), header_size);
    for (plan, (dir_offset, dir_len)) in plans.iter().zip(&placements) {
        let data_base = *dir_offset as usize + *dir_len as usize;
        let mut cursor = data_base;
        for (block_index, block) in plan.blocks.iter().enumerate() {
            let first_doc = block_index as u64 * u64::from(plan.block_docs);
            writer.u64(first_doc);
            writer.u32(block.state.len() as u32);
            let state_offset = (cursor - data_base) as u64;
            cursor += block.state.len();
            let values_offset = (cursor - data_base) as u64;
            cursor += block.values.len();
            writer.u64(state_offset);
            writer.u64(values_offset);
            writer.u64(block.values.len() as u64);
        }
        for block in &plan.blocks {
            writer.bytes(&block.state);
            writer.bytes(&block.values);
        }
    }
    Ok(writer.into_vec())
}

#[derive(Debug, Clone, Copy)]
struct ColumnMeta {
    field_id: u32,
    type_tag: u8,
    layout: u8,
    doc_count: u64,
    block_count: u32,
    block_docs: u32,
    dir_offset: usize,
    data_base: usize,
}

/// A bounded column reader.
#[derive(Debug)]
pub struct ColumnReader<'a> {
    bytes: &'a [u8],
    schema: &'a CodecSchema,
    limits: SegmentLimits,
    columns: Vec<ColumnMeta>,
    blocks_read: Cell<u64>,
}

impl<'a> ColumnReader<'a> {
    /// Parse and validate the COLUMNS section body geometry.
    pub fn open(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
    ) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("columns version")?;
        if version != 1 {
            return Err(SegmentError::Corrupt {
                context: "columns version",
                detail: format!("unsupported {version}"),
            });
        }
        let column_count = reader.u32("column count")?;
        let mut columns = Vec::with_capacity(column_count as usize);
        let mut previous_field: Option<u32> = None;
        let header_end = 6 + column_count as usize * COLUMN_HEADER_LEN;
        if header_end > bytes.len() {
            return Err(SegmentError::Truncated {
                context: "column headers",
                needed: header_end as u64,
                available: bytes.len() as u64,
            });
        }
        for _ in 0..column_count {
            let field_id = reader.u32("column field id")?;
            if let Some(previous) = previous_field {
                if field_id <= previous {
                    return Err(SegmentError::Corrupt {
                        context: "columns",
                        detail: "field ids not ascending".to_owned(),
                    });
                }
            }
            previous_field = Some(field_id);
            let type_tag = reader.u8("column type tag")?;
            let layout = reader.u8("column layout")?;
            let doc_count = reader.u64("column doc count")?;
            let block_count = reader.u32("column block count")?;
            let block_docs = reader.u32("column block docs")?;
            let _state_bitmap_len = reader.u64("column state bitmap len")?;
            let dir_offset = reader.u64("column dir offset")?;
            let dir_len = reader.u64("column dir len")?;
            if block_docs == 0 {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "zero block_docs",
                });
            }
            let expected_blocks = doc_count.div_ceil(u64::from(block_docs));
            if u64::from(block_count) != expected_blocks {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "block_count does not match doc_count/block_docs",
                });
            }
            let dir_offset_usize =
                usize::try_from(dir_offset).map_err(|_| SegmentError::InvalidColumnGeometry {
                    detail: "dir offset out of range",
                })?;
            let dir_len_usize =
                usize::try_from(dir_len).map_err(|_| SegmentError::InvalidColumnGeometry {
                    detail: "dir len out of range",
                })?;
            let data_base = dir_offset_usize.checked_add(dir_len_usize).ok_or(
                SegmentError::InvalidColumnGeometry {
                    detail: "column data overflow",
                },
            )?;
            if data_base > bytes.len() {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "column data starts past section",
                });
            }
            // Validate the block directory geometry.
            for block_index in 0..block_count {
                let entry_offset = dir_offset_usize + block_index as usize * BLOCK_ENTRY_LEN;
                let slice = bytes
                    .get(entry_offset..entry_offset + BLOCK_ENTRY_LEN)
                    .ok_or(SegmentError::InvalidColumnGeometry {
                        detail: "block directory truncated",
                    })?;
                let mut entry = ByteReader::new(slice);
                let first_doc = entry.u64("block first doc")?;
                let rows = entry.u32("block rows")?;
                let _state_offset = entry.u64("block state offset")?;
                let _values_offset = entry.u64("block values offset")?;
                let _values_length = entry.u64("block values length")?;
                let expected_first = block_index as u64 * u64::from(block_docs);
                if first_doc != expected_first {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "block first_doc mismatch",
                    });
                }
                let remaining = doc_count - expected_first;
                let expected_rows = remaining.min(u64::from(block_docs));
                if u64::from(rows) != expected_rows {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "block row count mismatch",
                    });
                }
            }
            columns.push(ColumnMeta {
                field_id,
                type_tag,
                layout,
                doc_count,
                block_count,
                block_docs,
                dir_offset: dir_offset_usize,
                data_base,
            });
        }
        Ok(Self {
            bytes,
            schema,
            limits: *limits,
            columns,
            blocks_read: Cell::new(0),
        })
    }

    /// Number of column blocks read since open (for bounded-access assertions).
    #[must_use]
    pub fn blocks_read(&self) -> u64 {
        self.blocks_read.get()
    }

    /// Field ids that have a column.
    #[must_use]
    pub fn fields(&self) -> Vec<u32> {
        self.columns.iter().map(|column| column.field_id).collect()
    }

    /// Decode one document's column value. Returns `None` if no column exists.
    pub fn value(&self, field_id: u32, doc_id: u64) -> SegmentResult<Option<FieldValues>> {
        let Some(meta) = self.columns.iter().find(|c| c.field_id == field_id) else {
            return Ok(None);
        };
        if doc_id >= meta.doc_count {
            return Err(SegmentError::Corrupt {
                context: "column",
                detail: "doc id out of range".to_owned(),
            });
        }
        let block_index = doc_id / u64::from(meta.block_docs);
        debug_assert!(block_index < u64::from(meta.block_count));
        self.blocks_read.set(self.blocks_read.get() + 1);
        let entry_offset = meta.dir_offset + block_index as usize * BLOCK_ENTRY_LEN;
        let entry_slice = self
            .bytes
            .get(entry_offset..entry_offset + BLOCK_ENTRY_LEN)
            .ok_or(SegmentError::InvalidColumnGeometry {
                detail: "block entry out of range",
            })?;
        let mut entry = ByteReader::new(entry_slice);
        let first_doc = entry.u64("block first doc")?;
        let rows = entry.u32("block rows")?;
        let state_offset = entry.u64("block state offset")?;
        let values_offset = entry.u64("block values offset")?;
        let _values_length = entry.u64("block values length")?;
        let relative = doc_id - first_doc;
        let state = *self
            .bytes
            .get(meta.data_base + state_offset as usize + relative as usize)
            .ok_or(SegmentError::InvalidColumnGeometry {
                detail: "state byte out of range",
            })?;
        let field = self
            .schema
            .field(field_id)
            .ok_or(SegmentError::UnknownFieldId { field_id })?;
        if meta.type_tag != field_type_tag(field.field_type) {
            return Err(SegmentError::FieldTypeMismatch {
                field: field.name.clone(),
            });
        }
        if state == STATE_ABSENT || state == STATE_EXPLICIT_NULL || state == STATE_EMPTY_MULTI {
            return Ok(Some(match state {
                STATE_ABSENT => FieldValues::Absent,
                STATE_EXPLICIT_NULL => FieldValues::ExplicitNull,
                _ => FieldValues::Empty,
            }));
        }
        if meta.layout == LAYOUT_FIXED_SINGLE {
            if state != STATE_SINGLE {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "fixed column row is not SINGLE",
                });
            }
            let width = slot_width(field.field_type);
            let start = meta.data_base + values_offset as usize + relative as usize * width;
            let slice = self.bytes.get(start..start + width).ok_or(
                SegmentError::InvalidColumnGeometry {
                    detail: "slot out of range",
                },
            )?;
            let mut value_reader = ByteReader::new(slice);
            let value = decode_scalar(&mut value_reader, field.field_type, &self.limits)?;
            value_reader.expect_end("column slot")?;
            return Ok(Some(FieldValues::Single(value)));
        }
        // Variable layout: offset table then value area.
        let value_base = meta.data_base + values_offset as usize;
        let table_len = (rows as usize + 1) * 8;
        let start_offset = self.u64_at(value_base + relative as usize * 8)?;
        let end_offset = self.u64_at(value_base + relative as usize * 8 + 8)?;
        if start_offset > end_offset {
            return Err(SegmentError::InvalidColumnGeometry {
                detail: "descending offset table",
            });
        }
        let data_start = value_base + table_len;
        let start = data_start + start_offset as usize;
        let end = data_start + end_offset as usize;
        let slice = self
            .bytes
            .get(start..end)
            .ok_or(SegmentError::InvalidColumnGeometry {
                detail: "value range out of bounds",
            })?;
        let mut value_reader = ByteReader::new(slice);
        let values = match state {
            STATE_SINGLE => FieldValues::Single(decode_scalar(
                &mut value_reader,
                field.field_type,
                &self.limits,
            )?),
            STATE_MULTI => {
                let count = value_reader.varint("multi count")?;
                if count == 0 {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "zero multi count",
                    });
                }
                self.limits.check_entries(count)?;
                let mut list = Vec::with_capacity(count as usize);
                for _ in 0..count {
                    list.push(decode_scalar(
                        &mut value_reader,
                        field.field_type,
                        &self.limits,
                    )?);
                }
                FieldValues::Multi(list)
            }
            _ => {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "unexpected state",
                });
            }
        };
        value_reader.expect_end("column value")?;
        Ok(Some(values))
    }

    fn u64_at(&self, offset: usize) -> SegmentResult<u64> {
        let slice =
            self.bytes
                .get(offset..offset + 8)
                .ok_or(SegmentError::InvalidColumnGeometry {
                    detail: "offset table out of range",
                })?;
        let mut reader = ByteReader::new(slice);
        reader.u64("offset table")
    }
}
