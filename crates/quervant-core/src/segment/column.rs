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
use super::metadata::{MetadataMeter, capacity_bytes, element_bytes};
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
///
/// Approved F07 encodes each component as `type_tag u8`, then a state tag
/// (`0x00` missing, `0x01` null, `0x02` value), then the value bytes. The field
/// type must be supplied for missing/null because the type tag is always
/// present. `EMPTY_MULTI` is not representable: it expands to zero groups.
#[derive(Debug, Clone, Copy)]
pub enum GroupComponent<'a> {
    /// Field is absent; carries the field's declared type.
    Missing(FieldType),
    /// Field is explicitly null; carries the field's declared type.
    Null(FieldType),
    /// Field has a typed scalar value.
    Value(&'a FieldValue),
}

/// Group-key state tag: component value is absent.
pub const GROUP_STATE_MISSING: u8 = 0x00;
/// Group-key state tag: component value is explicitly null.
pub const GROUP_STATE_NULL: u8 = 0x01;
/// Group-key state tag: component carries a value.
pub const GROUP_STATE_VALUE: u8 = 0x02;

/// Encode a typed, collision-free group key.
///
/// Wire bytes follow approved F07 exactly: `tuple_len varint`, then per
/// component `type_tag u8`, state tag, and (for values) canonical value bytes.
pub fn encode_group_key(components: &[GroupComponent<'_>]) -> SegmentResult<Vec<u8>> {
    let mut writer = ByteWriter::new();
    writer.varint(components.len() as u64);
    for component in components {
        match component {
            GroupComponent::Missing(field_type) => {
                writer.u8(field_type_tag(*field_type));
                writer.u8(GROUP_STATE_MISSING);
            }
            GroupComponent::Null(field_type) => {
                writer.u8(field_type_tag(*field_type));
                writer.u8(GROUP_STATE_NULL);
            }
            GroupComponent::Value(value) => {
                writer.u8(field_type_tag(value.field_type()));
                writer.u8(GROUP_STATE_VALUE);
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

/// Immutable per-field column geometry retained by a verified segment state.
///
/// Holds only the parsed fixed-size [`ColumnMeta`] table. Block directories,
/// variable-offset tables and decoded values are always read from the immutable
/// section bytes; nothing borrows a temporary container view.
#[derive(Debug)]
pub(crate) struct ColumnGeometry {
    columns: Vec<ColumnMeta>,
}

impl ColumnGeometry {
    /// Measured retained charge of the parsed column table.
    pub(crate) fn metadata_charge(&self) -> SegmentResult<u64> {
        capacity_bytes::<ColumnMeta>(self.columns.capacity())
    }

    /// Test-only identity witness for the retained column table buffer.
    #[cfg(test)]
    pub(crate) fn buffer_ptr(&self) -> usize {
        self.columns.as_ptr() as usize
    }
}

/// Where one query-local reader gets its immutable column table.
#[derive(Debug)]
enum GeometrySource<'a> {
    /// Parsed by this reader on the standalone/uncached path.
    Owned(ColumnGeometry),
    /// Borrowed from a budget-admitted verified segment state.
    Borrowed(&'a ColumnGeometry),
}

impl GeometrySource<'_> {
    fn columns(&self) -> &[ColumnMeta] {
        match self {
            Self::Owned(geometry) => &geometry.columns,
            Self::Borrowed(geometry) => &geometry.columns,
        }
    }
}

/// A bounded column reader.
#[derive(Debug)]
pub struct ColumnReader<'a> {
    bytes: &'a [u8],
    schema: &'a CodecSchema,
    limits: SegmentLimits,
    geometry: GeometrySource<'a>,
    blocks_read: Cell<u64>,
}

/// The allocation shape of one document's column value, without decoding it.
enum ValueSpan {
    /// Absent, explicit null or empty multi-value: no payload bytes.
    Stateless(u8),
    /// Fixed-width single value at `start` with `width` bytes.
    Fixed {
        state: u8,
        start: usize,
        width: usize,
    },
    /// Variable value occupying `start..end`.
    Variable { state: u8, start: usize, end: usize },
}

impl<'a> ColumnReader<'a> {
    /// Parse and validate the COLUMNS section body geometry.
    pub fn open(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
    ) -> SegmentResult<Self> {
        Self::open_with_doc_count(schema, bytes, limits, None)
    }

    /// Open with an optional expected container document count.
    ///
    /// When `expected_doc_count` is supplied, every column must agree with it.
    /// This lets `SegmentReader::open` validate cross-section geometry eagerly.
    pub fn open_with_doc_count(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
        expected_doc_count: Option<u64>,
    ) -> SegmentResult<Self> {
        Self::parse(schema, bytes, limits, expected_doc_count, &mut None)
    }

    /// Parse and validate the COLUMNS body, charging the retained per-field
    /// geometry against `meter` before that vector is allocated.
    pub(crate) fn open_with_doc_count_metered(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
        expected_doc_count: Option<u64>,
        meter: &mut MetadataMeter,
    ) -> SegmentResult<Self> {
        Self::parse(schema, bytes, limits, expected_doc_count, &mut Some(meter))
    }

    /// The one authoritative parser body shared by every entry point.
    ///
    /// `meter`, when present, charges the actual parsed column count before the
    /// metadata vector is allocated. Validation checks and their relative order
    /// are identical in both modes.
    fn parse(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
        expected_doc_count: Option<u64>,
        meter: &mut Option<&mut MetadataMeter>,
    ) -> SegmentResult<Self> {
        const HEADER_PREFIX: u64 = 6;
        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("columns version")?;
        if version != 1 {
            return Err(SegmentError::Corrupt {
                context: "columns version",
                detail: format!("unsupported {version}"),
            });
        }
        let column_count = reader.u32("column count")?;
        let column_count_u64 = u64::from(column_count);
        limits.check_entries(column_count_u64)?;
        limits.check_alloc::<ColumnMeta>(column_count_u64)?;
        let header_end_u64 = HEADER_PREFIX
            .checked_add(
                column_count_u64
                    .checked_mul(COLUMN_HEADER_LEN as u64)
                    .ok_or(SegmentError::InvalidColumnGeometry {
                        detail: "column header size overflow",
                    })?,
            )
            .ok_or(SegmentError::InvalidColumnGeometry {
                detail: "column header size overflow",
            })?;
        super::format::count_min_bytes(
            "column headers",
            column_count_u64,
            COLUMN_HEADER_LEN as u64,
            reader.remaining() as u64,
        )?;
        if header_end_u64 > bytes.len() as u64 {
            return Err(SegmentError::Truncated {
                context: "column headers",
                needed: header_end_u64,
                available: bytes.len() as u64,
            });
        }
        let column_capacity =
            usize::try_from(column_count).map_err(|_| SegmentError::InvalidColumnGeometry {
                detail: "column count out of range",
            })?;
        if let Some(meter) = meter.as_deref_mut() {
            meter.charge_vec::<ColumnMeta>(column_count_u64)?;
        }
        let mut columns: Vec<ColumnMeta> = Vec::new();
        columns
            .try_reserve_exact(column_capacity)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: column_count_u64,
            })?;

        let mut previous_field: Option<u32> = None;
        let mut previous_end: u64 = header_end_u64;
        for _ in 0..column_count {
            let field_id = reader.u32("column field id")?;
            if let Some(previous) = previous_field {
                if field_id <= previous {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "field ids not ascending",
                    });
                }
            }
            previous_field = Some(field_id);
            let field = schema
                .field(field_id)
                .ok_or(SegmentError::UnknownFieldId { field_id })?;
            if !field.is_columnar() {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "field is not columnar",
                });
            }
            let type_tag = reader.u8("column type tag")?;
            if type_tag != field_type_tag(field.field_type) {
                return Err(SegmentError::FieldTypeMismatch {
                    field: field.name.clone(),
                });
            }
            let layout = reader.u8("column layout")?;
            if layout != layout_for(field.field_type, field.cardinality) {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "layout does not match field type/cardinality",
                });
            }
            let doc_count = reader.u64("column doc count")?;
            if let Some(expected) = expected_doc_count {
                if doc_count != expected {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "column doc_count does not match segment doc_count",
                    });
                }
            }
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
            let expected_dir_len = u64::from(block_count)
                .checked_mul(BLOCK_ENTRY_LEN as u64)
                .ok_or(SegmentError::InvalidColumnGeometry {
                    detail: "directory length overflow",
                })?;
            if dir_len != expected_dir_len {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "dir_len does not match block_count",
                });
            }
            if dir_offset < previous_end {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "column directory overlaps previous column",
                });
            }
            let dir_offset_usize =
                usize::try_from(dir_offset).map_err(|_| SegmentError::InvalidColumnGeometry {
                    detail: "dir offset out of range",
                })?;
            let data_base_u64 =
                dir_offset
                    .checked_add(dir_len)
                    .ok_or(SegmentError::InvalidColumnGeometry {
                        detail: "column data overflow",
                    })?;
            let data_base = data_base_u64 as usize;
            if data_base > bytes.len() {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "column data starts past section",
                });
            }

            let width = slot_width(field.field_type) as u64;
            let mut column_end = previous_end;
            for block_index in 0..block_count {
                let entry_offset = dir_offset_usize
                    .checked_add(block_index as usize * BLOCK_ENTRY_LEN)
                    .ok_or(SegmentError::InvalidColumnGeometry {
                        detail: "block entry offset overflow",
                    })?;
                let slice = bytes
                    .get(entry_offset..entry_offset + BLOCK_ENTRY_LEN)
                    .ok_or(SegmentError::InvalidColumnGeometry {
                        detail: "block directory truncated",
                    })?;
                let mut entry = ByteReader::new(slice);
                let first_doc = entry.u64("block first doc")?;
                let rows = entry.u32("block rows")?;
                let state_offset = entry.u64("block state offset")?;
                let values_offset = entry.u64("block values offset")?;
                let values_length = entry.u64("block values length")?;
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
                let rows_u64 = u64::from(rows);
                let state_start = data_base_u64.checked_add(state_offset).ok_or(
                    SegmentError::InvalidColumnGeometry {
                        detail: "state offset overflow",
                    },
                )?;
                let state_end = state_start.checked_add(rows_u64).ok_or(
                    SegmentError::InvalidColumnGeometry {
                        detail: "state extent overflow",
                    },
                )?;
                let values_start = data_base_u64.checked_add(values_offset).ok_or(
                    SegmentError::InvalidColumnGeometry {
                        detail: "values offset overflow",
                    },
                )?;
                let values_end = values_start.checked_add(values_length).ok_or(
                    SegmentError::InvalidColumnGeometry {
                        detail: "values extent overflow",
                    },
                )?;
                if state_start < data_base_u64
                    || state_end > bytes.len() as u64
                    || values_end > bytes.len() as u64
                {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "block extent past section",
                    });
                }
                if state_end > values_start {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "state overlaps values",
                    });
                }
                let state_bytes = bytes.get(state_start as usize..state_end as usize).ok_or(
                    SegmentError::InvalidColumnGeometry {
                        detail: "state range out of bounds",
                    },
                )?;
                for state in state_bytes {
                    if !valid_state(*state, layout) {
                        return Err(SegmentError::InvalidColumnGeometry {
                            detail: "invalid state tag",
                        });
                    }
                }
                if layout == LAYOUT_FIXED_SINGLE {
                    let expected_values_len =
                        rows_u64
                            .checked_mul(width)
                            .ok_or(SegmentError::InvalidColumnGeometry {
                                detail: "slot extent overflow",
                            })?;
                    if values_length != expected_values_len {
                        return Err(SegmentError::InvalidColumnGeometry {
                            detail: "fixed slot length mismatch",
                        });
                    }
                } else {
                    let table_len = rows_u64
                        .checked_add(1)
                        .and_then(|value| value.checked_mul(8))
                        .ok_or(SegmentError::InvalidColumnGeometry {
                            detail: "offset table overflow",
                        })?;
                    if values_length < table_len {
                        return Err(SegmentError::InvalidColumnGeometry {
                            detail: "offset table exceeds values extent",
                        });
                    }
                    let value_area_len = values_length - table_len;
                    let mut previous_offset = 0u64;
                    for index in 0..=rows_u64 {
                        let at = values_start as usize + index as usize * 8;
                        let offset = read_u64_at(bytes, at)?;
                        if offset > value_area_len {
                            return Err(SegmentError::InvalidColumnGeometry {
                                detail: "offset beyond value area",
                            });
                        }
                        if index == 0 && offset != 0 {
                            return Err(SegmentError::InvalidColumnGeometry {
                                detail: "offset table must start at zero",
                            });
                        }
                        if index > 0 && offset < previous_offset {
                            return Err(SegmentError::InvalidColumnGeometry {
                                detail: "descending offset table",
                            });
                        }
                        previous_offset = offset;
                    }
                    if previous_offset != value_area_len {
                        return Err(SegmentError::InvalidColumnGeometry {
                            detail: "terminal offset does not match value area",
                        });
                    }
                }
                let block_end = state_end.max(values_end);
                if block_end > column_end {
                    column_end = block_end;
                }
            }
            if column_end > bytes.len() as u64 {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "column extends past section",
                });
            }
            previous_end = column_end;
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
            geometry: GeometrySource::Owned(ColumnGeometry { columns }),
            blocks_read: Cell::new(0),
        })
    }

    /// Consume a fully parsed owned reader and return its geometry.
    ///
    /// This is called only immediately after successful eager validation. It
    /// never copies the table; reaching it on a borrowed reader is a call-site
    /// invariant violation, not a reason to clone.
    pub(crate) fn into_geometry(self) -> ColumnGeometry {
        match self.geometry {
            GeometrySource::Owned(geometry) => geometry,
            GeometrySource::Borrowed(_) => {
                unreachable!("into_geometry called on a borrowed column reader")
            }
        }
    }

    /// Open a query-local reader borrowing already validated geometry.
    ///
    /// No parsing or allocation happens here; the query-local `blocks_read`
    /// counter starts at zero.
    pub(crate) fn from_validated_geometry(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
        geometry: &'a ColumnGeometry,
    ) -> Self {
        Self {
            bytes,
            schema,
            limits: *limits,
            geometry: GeometrySource::Borrowed(geometry),
            blocks_read: Cell::new(0),
        }
    }

    /// Test-only identity witness for the retained/parsed column table.
    #[cfg(test)]
    pub(crate) fn geometry_ptr(&self) -> usize {
        self.geometry.columns().as_ptr() as usize
    }

    /// Number of column blocks read since open (for bounded-access assertions).
    #[must_use]
    pub fn blocks_read(&self) -> u64 {
        self.blocks_read.get()
    }

    /// Field ids that have a column.
    #[must_use]
    pub fn fields(&self) -> Vec<u32> {
        self.geometry
            .columns()
            .iter()
            .map(|column| column.field_id)
            .collect()
    }

    /// Decode one document's column value. Returns `None` if no column exists.
    pub fn value(&self, field_id: u32, doc_id: u64) -> SegmentResult<Option<FieldValues>> {
        let Some(meta) = self
            .geometry
            .columns()
            .iter()
            .find(|c| c.field_id == field_id)
        else {
            return Ok(None);
        };
        let field = self
            .schema
            .field(field_id)
            .ok_or(SegmentError::UnknownFieldId { field_id })?;
        if meta.type_tag != field_type_tag(field.field_type) {
            return Err(SegmentError::FieldTypeMismatch {
                field: field.name.clone(),
            });
        }
        match self.span_of(meta, field.field_type, doc_id)? {
            ValueSpan::Stateless(state) => Ok(Some(match state {
                STATE_ABSENT => FieldValues::Absent,
                STATE_EXPLICIT_NULL => FieldValues::ExplicitNull,
                _ => FieldValues::Empty,
            })),
            ValueSpan::Fixed {
                state,
                start,
                width,
            } => {
                if state != STATE_SINGLE {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "fixed column row is not SINGLE",
                    });
                }
                let slice = self.bytes.get(start..start + width).ok_or(
                    SegmentError::InvalidColumnGeometry {
                        detail: "slot out of range",
                    },
                )?;
                let mut value_reader = ByteReader::new(slice);
                let value = decode_scalar(&mut value_reader, field.field_type, &self.limits)?;
                value_reader.expect_end("column slot")?;
                Ok(Some(FieldValues::Single(value)))
            }
            ValueSpan::Variable { state, start, end } => {
                let slice =
                    self.bytes
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
                        self.limits.check_alloc::<FieldValue>(count)?;
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
        }
    }

    /// Encoded shape of one document's column value without decoding it.
    ///
    /// Returns `None` when the field has no column. Otherwise returns
    /// `(state, encoded_span_bytes, element_count)` where `element_count` is `0`
    /// for absent/null/empty, `1` for a single value and the declared count for a
    /// multi-value. This is a read-only admission seam: it does not decode or
    /// allocate and does not change the wire format.
    pub(crate) fn encoded_value_shape(
        &self,
        field_id: u32,
        doc_id: u64,
    ) -> SegmentResult<Option<(u8, u64, u64)>> {
        let Some(meta) = self
            .geometry
            .columns()
            .iter()
            .find(|c| c.field_id == field_id)
        else {
            return Ok(None);
        };
        let field = self
            .schema
            .field(field_id)
            .ok_or(SegmentError::UnknownFieldId { field_id })?;
        if meta.type_tag != field_type_tag(field.field_type) {
            return Err(SegmentError::FieldTypeMismatch {
                field: field.name.clone(),
            });
        }
        match self.span_of(meta, field.field_type, doc_id)? {
            ValueSpan::Stateless(state) => Ok(Some((state, 0, 0))),
            ValueSpan::Fixed { state, width, .. } => Ok(Some((state, width as u64, 1))),
            ValueSpan::Variable { state, start, end } => {
                let span = u64::try_from(end - start).unwrap_or(u64::MAX);
                let count = if state == STATE_MULTI {
                    let slice =
                        self.bytes
                            .get(start..end)
                            .ok_or(SegmentError::InvalidColumnGeometry {
                                detail: "value range out of bounds",
                            })?;
                    let mut reader = ByteReader::new(slice);
                    reader.varint("multi count")?
                } else {
                    1
                };
                Ok(Some((state, span, count)))
            }
        }
    }

    fn span_of(
        &self,
        meta: &ColumnMeta,
        field_type: FieldType,
        doc_id: u64,
    ) -> SegmentResult<ValueSpan> {
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
        if state == STATE_ABSENT || state == STATE_EXPLICIT_NULL || state == STATE_EMPTY_MULTI {
            return Ok(ValueSpan::Stateless(state));
        }
        if meta.layout == LAYOUT_FIXED_SINGLE {
            let width = slot_width(field_type);
            let start = meta.data_base + values_offset as usize + relative as usize * width;
            return Ok(ValueSpan::Fixed {
                state,
                start,
                width,
            });
        }
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
        Ok(ValueSpan::Variable {
            state,
            start: data_start + start_offset as usize,
            end: data_start + end_offset as usize,
        })
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

/// Conservative retained-geometry allowance derived from the COLUMNS body size.
///
/// Every column consumes one fixed 46-byte header after the 6-byte section
/// prefix, so this is a sound upper bound on the number of parsed
/// [`ColumnMeta`] entries. A section shorter than the prefix yields `0`; the
/// authoritative parser subsequently fails as before.
pub(crate) fn column_geometry_allowance(section_len: u64) -> SegmentResult<u64> {
    let Some(payload) = section_len.checked_sub(6) else {
        return Ok(0);
    };
    let max_column_headers = payload / COLUMN_HEADER_LEN as u64;
    element_bytes::<ColumnMeta>(max_column_headers)
}

fn valid_state(state: u8, layout: u8) -> bool {
    match layout {
        LAYOUT_FIXED_SINGLE => {
            matches!(state, STATE_ABSENT | STATE_EXPLICIT_NULL | STATE_SINGLE)
        }
        _ => state <= STATE_MULTI,
    }
}

fn read_u64_at(bytes: &[u8], offset: usize) -> SegmentResult<u64> {
    let slice = bytes
        .get(offset..offset + 8)
        .ok_or(SegmentError::InvalidColumnGeometry {
            detail: "offset table out of range",
        })?;
    let mut reader = ByteReader::new(slice);
    reader.u64("offset table")
}

#[cfg(test)]
mod tests {
    //! PR 15G-A — retained immutable column geometry tests.

    use super::*;
    use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
    use crate::contract::document::{Cardinality, DocumentKey};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::segment::metadata::{MetadataBudget, MetadataMeter};

    fn codec(fields: Vec<FieldDefinition>) -> CodecSchema {
        let schema = Schema::new(fields, None).expect("contract schema");
        let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin())
            .expect("bindings");
        CodecSchema::from_contract(&schema, &bindings).expect("codec schema")
    }

    fn count_field() -> FieldDefinition {
        FieldDefinition::new(
            "count",
            FieldType::I64,
            Cardinality::Single,
            FieldOptions::new(false, true, true),
        )
    }

    fn keyword_field(name: &str, cardinality: Cardinality) -> FieldDefinition {
        FieldDefinition::new(
            name,
            FieldType::Keyword,
            cardinality,
            FieldOptions::new(true, true, true),
        )
        .with_normalizer("keyword")
    }

    fn document(key: &str) -> SegmentDocument {
        SegmentDocument::new(DocumentKey::new(key).expect("key"))
    }

    fn insert(doc: &mut SegmentDocument, field: &str, values: FieldValues) {
        doc.insert(field, values).expect("insert");
    }

    fn single_i64(value: i64) -> FieldValues {
        FieldValues::Single(FieldValue::I64(value))
    }

    fn single_keyword(value: &str) -> FieldValues {
        FieldValues::Single(FieldValue::Keyword(value.to_owned()))
    }

    fn two_block_keyword_fixture() -> (CodecSchema, Vec<u8>) {
        let schema = codec(vec![keyword_field("tag", Cardinality::Single)]);
        let mut docs = Vec::new();
        for (index, values) in [
            single_keyword("alpha"),
            FieldValues::ExplicitNull,
            FieldValues::Absent,
            single_keyword("beta"),
            single_keyword("gamma"),
        ]
        .into_iter()
        .enumerate()
        {
            let mut doc = document(&format!("k{index}"));
            insert(&mut doc, "tag", values);
            docs.push(doc);
        }
        let body = encode_columns(&schema, &docs, 2, &SegmentLimits::default()).expect("columns");
        (schema, body)
    }

    // GA-U01 — owned and borrowed readers return identical typed values and
    // shapes, with independent block counters.
    #[test]
    fn u01_owned_and_borrowed_readers_are_value_identical() {
        let schema = codec(vec![count_field()]);
        let mut docs = Vec::new();
        for (index, values) in [
            single_i64(7),
            FieldValues::ExplicitNull,
            FieldValues::Absent,
            single_i64(-3),
        ]
        .into_iter()
        .enumerate()
        {
            let mut doc = document(&format!("k{index}"));
            insert(&mut doc, "count", values);
            docs.push(doc);
        }
        let limits = SegmentLimits::default();
        let body = encode_columns(&schema, &docs, 2, &limits).expect("columns");
        let field_id = schema.field_id("count").expect("count");
        let geometry = ColumnReader::open(&schema, &body, &limits)
            .expect("owned parse")
            .into_geometry();
        let borrowed = ColumnReader::from_validated_geometry(&schema, &body, &limits, &geometry);
        let standalone = ColumnReader::open(&schema, &body, &limits).expect("standalone");
        assert_eq!(borrowed.fields(), standalone.fields());
        assert_eq!(borrowed.blocks_read(), 0);
        for doc_id in 0..4 {
            assert_eq!(
                borrowed.value(field_id, doc_id).expect("borrowed value"),
                standalone
                    .value(field_id, doc_id)
                    .expect("standalone value"),
                "doc {doc_id}"
            );
            assert_eq!(
                borrowed
                    .encoded_value_shape(field_id, doc_id)
                    .expect("borrowed shape"),
                standalone
                    .encoded_value_shape(field_id, doc_id)
                    .expect("standalone shape"),
                "shape doc {doc_id}"
            );
        }
        assert_eq!(borrowed.blocks_read(), 8);
        assert_eq!(standalone.blocks_read(), 8);
    }

    // GA-U02 — variable multi/keyword values across blocks keep the exact
    // bounded block-visit behaviour.
    #[test]
    fn u02_variable_multi_and_keyword_values_are_unchanged() {
        let schema = codec(vec![keyword_field("tags", Cardinality::Multi)]);
        let mut docs = Vec::new();
        for (index, values) in [
            FieldValues::Multi(vec![
                FieldValue::Keyword("red".to_owned()),
                FieldValue::Keyword("blue".to_owned()),
            ]),
            FieldValues::Empty,
            FieldValues::ExplicitNull,
            FieldValues::Absent,
            single_keyword("solo"),
        ]
        .into_iter()
        .enumerate()
        {
            let mut doc = document(&format!("k{index}"));
            insert(&mut doc, "tags", values);
            docs.push(doc);
        }
        let limits = SegmentLimits::default();
        let body = encode_columns(&schema, &docs, 2, &limits).expect("columns");
        let field_id = schema.field_id("tags").expect("tags");
        let geometry = ColumnReader::open(&schema, &body, &limits)
            .expect("parse")
            .into_geometry();
        let borrowed = ColumnReader::from_validated_geometry(&schema, &body, &limits, &geometry);
        let standalone = ColumnReader::open(&schema, &body, &limits).expect("standalone");
        for doc_id in 0..5 {
            assert_eq!(
                borrowed.value(field_id, doc_id).expect("borrowed"),
                standalone.value(field_id, doc_id).expect("standalone"),
                "doc {doc_id}"
            );
            assert_eq!(
                borrowed
                    .encoded_value_shape(field_id, doc_id)
                    .expect("shape"),
                standalone
                    .encoded_value_shape(field_id, doc_id)
                    .expect("shape"),
                "shape doc {doc_id}"
            );
        }
        assert_eq!(borrowed.blocks_read(), 10);
        assert_eq!(standalone.blocks_read(), 10);
    }

    // GA-U03 — field order and `doc_id` semantics are unchanged for more than
    // one column with a non-uniform last block.
    #[test]
    fn u03_multiple_columns_keep_order_and_doc_semantics() {
        let schema = codec(vec![
            count_field(),
            keyword_field("tag", Cardinality::Single),
        ]);
        let mut docs = Vec::new();
        for index in 0..5i64 {
            let mut doc = document(&format!("k{index}"));
            insert(&mut doc, "count", single_i64(index * 10));
            insert(&mut doc, "tag", single_keyword(&format!("t{index}")));
            docs.push(doc);
        }
        let limits = SegmentLimits::default();
        let body = encode_columns(&schema, &docs, 3, &limits).expect("columns");
        let count = schema.field_id("count").expect("count");
        let tag = schema.field_id("tag").expect("tag");
        let reader = ColumnReader::open(&schema, &body, &limits).expect("parse");
        assert_eq!(reader.fields(), vec![count, tag]);
        for doc_id in 0..5u64 {
            assert_eq!(
                reader.value(count, doc_id).expect("count"),
                Some(single_i64(doc_id as i64 * 10))
            );
            assert_eq!(
                reader.value(tag, doc_id).expect("tag"),
                Some(single_keyword(&format!("t{doc_id}")))
            );
        }
        assert!(reader.value(count, 5).is_err());
    }

    // GA-U04 — a present version-1 zero-column section stays `Some` with no
    // fields; an absent COLUMNS section is a reader-level `None`.
    #[test]
    fn u04_zero_column_section_is_present_but_empty() {
        let schema = codec(vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard"),
        ]);
        let mut doc = document("k");
        insert(&mut doc, "body", single_keyword("unused"));
        let limits = SegmentLimits::default();
        let body = encode_columns(&schema, &[doc], 16, &limits).expect("columns");
        assert_eq!(&body[..6], &[1, 0, 0, 0, 0, 0]);
        let geometry = ColumnReader::open(&schema, &body, &limits)
            .expect("parse")
            .into_geometry();
        assert_eq!(geometry.columns.len(), 0);
        let borrowed = ColumnReader::from_validated_geometry(&schema, &body, &limits, &geometry);
        assert!(borrowed.fields().is_empty());
        assert_eq!(borrowed.value(0, 0).expect("value"), None);
    }

    fn first_column_state_offset(body: &[u8], geometry: &ColumnGeometry) -> usize {
        let meta = geometry.columns.first().expect("column");
        let entry = &body[meta.dir_offset..meta.dir_offset + BLOCK_ENTRY_LEN];
        let mut reader = ByteReader::new(entry);
        let _first_doc = reader.u64("first doc").expect("first doc");
        let _rows = reader.u32("rows").expect("rows");
        let state_offset = reader.u64("state offset").expect("state offset");
        meta.data_base + state_offset as usize
    }

    // GA-U05 — an invalid state tag in otherwise unselected data fails closed
    // with the same typed class on the metered and unmetered parsers.
    #[test]
    fn u05_corrupt_state_tag_is_the_same_typed_error() {
        let (schema, body) = two_block_keyword_fixture();
        let limits = SegmentLimits::default();
        let mut corrupt = body.clone();
        let geometry = ColumnReader::open(&schema, &corrupt, &limits)
            .expect("parse")
            .into_geometry();
        let at = first_column_state_offset(&corrupt, &geometry);
        corrupt[at] = 0xFF;

        let unmetered = ColumnReader::open(&schema, &corrupt, &limits).expect_err("corrupt");
        assert!(matches!(
            unmetered,
            SegmentError::InvalidColumnGeometry {
                detail: "invalid state tag"
            }
        ));

        let budget = MetadataBudget::new(u64::MAX);
        let mut meter = MetadataMeter::reserve(&budget, 1_000_000).expect("reserve");
        let metered = ColumnReader::open_with_doc_count_metered(
            &schema,
            &corrupt,
            &limits,
            Some(5),
            &mut meter,
        )
        .expect_err("corrupt");
        assert!(matches!(
            metered,
            SegmentError::InvalidColumnGeometry {
                detail: "invalid state tag"
            }
        ));
        drop(meter);
        assert_eq!(budget.used(), 0);
    }

    // GA-U06 — truncated headers, wrong type tags and doc-count mismatches keep
    // their authoritative typed errors on both parser entry points.
    #[test]
    fn u06_truncation_and_header_errors_are_typed() {
        let (schema, body) = two_block_keyword_fixture();
        let limits = SegmentLimits::default();
        assert!(matches!(
            ColumnReader::open(&schema, &body[..5], &limits),
            Err(SegmentError::Truncated { .. })
        ));
        let budget = MetadataBudget::new(u64::MAX);
        let mut meter = MetadataMeter::reserve(&budget, 1_000_000).expect("reserve");
        assert!(matches!(
            ColumnReader::open_with_doc_count_metered(
                &schema,
                &body[..5],
                &limits,
                None,
                &mut meter
            ),
            Err(SegmentError::Truncated { .. })
        ));
        drop(meter);
        assert_eq!(budget.used(), 0);

        let mut wrong_type = body.clone();
        wrong_type[10] = 0x7F;
        assert!(matches!(
            ColumnReader::open(&schema, &wrong_type, &limits),
            Err(SegmentError::FieldTypeMismatch { .. })
        ));
        assert!(matches!(
            ColumnReader::open_with_doc_count(&schema, &body, &limits, Some(4)),
            Err(SegmentError::InvalidColumnGeometry {
                detail: "column doc_count does not match segment doc_count"
            })
        ));
    }

    // GA-U07 — `into_geometry` moves the parsed table without copying, and a
    // borrowed reader is not a valid source for it.
    #[test]
    fn u07_into_geometry_moves_and_rejects_borrowed_sources() {
        let (schema, body) = two_block_keyword_fixture();
        let limits = SegmentLimits::default();
        let reader = ColumnReader::open(&schema, &body, &limits).expect("parse");
        let address = reader.geometry_ptr();
        let geometry = reader.into_geometry();
        let borrowed = ColumnReader::from_validated_geometry(&schema, &body, &limits, &geometry);
        assert_eq!(borrowed.geometry_ptr(), address);
        assert_eq!(borrowed.geometry_ptr(), geometry.columns.as_ptr() as usize);
    }

    #[test]
    #[should_panic(expected = "into_geometry called on a borrowed column reader")]
    fn u07_borrowed_reader_cannot_be_consumed_as_owned_geometry() {
        let (schema, body) = two_block_keyword_fixture();
        let limits = SegmentLimits::default();
        let geometry = ColumnReader::open(&schema, &body, &limits)
            .expect("parse")
            .into_geometry();
        let borrowed = ColumnReader::from_validated_geometry(&schema, &body, &limits, &geometry);
        let _ = borrowed.into_geometry();
    }

    // GA-U10 — the size-derived allowance is at least the measured retained
    // charge, and finalization stays inside it.
    #[test]
    fn u10_allowance_covers_measured_charge_for_many_columns() {
        let fields: Vec<FieldDefinition> = (0..40)
            .map(|index| {
                FieldDefinition::new(
                    format!("f{index:02}"),
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                )
            })
            .collect();
        let schema = codec(fields);
        let mut docs = Vec::new();
        for index in 0..3i64 {
            let mut doc = document(&format!("k{index}"));
            for field in schema.fields() {
                insert(&mut doc, &field.name, single_i64(index));
            }
            docs.push(doc);
        }
        let limits = SegmentLimits::default();
        let body = encode_columns(&schema, &docs, 2, &limits).expect("columns");
        let allowance = column_geometry_allowance(body.len() as u64).expect("allowance");
        let budget = MetadataBudget::new(u64::MAX);
        let mut meter = MetadataMeter::reserve(&budget, allowance).expect("reserve");
        let geometry =
            ColumnReader::open_with_doc_count_metered(&schema, &body, &limits, Some(3), &mut meter)
                .expect("metered parse")
                .into_geometry();
        let measured = geometry.metadata_charge().expect("charge");
        assert!(allowance >= measured);
        assert_eq!(geometry.columns.len(), 40);
        assert_eq!(measured, 40 * std::mem::size_of::<ColumnMeta>() as u64);
        let reservation = meter.finalize(measured).expect("finalize");
        assert_eq!(budget.used(), measured);
        drop(geometry);
        drop(reservation);
        assert_eq!(budget.used(), 0);
    }

    // GA-U11 — short/oversized allowance inputs and impossible allocation
    // limits are typed or bounded, never panics.
    #[test]
    fn u11_allowance_and_allocation_bounds_are_typed() {
        assert_eq!(column_geometry_allowance(0).expect("zero"), 0);
        assert_eq!(column_geometry_allowance(5).expect("short"), 0);
        assert_eq!(column_geometry_allowance(6).expect("prefix"), 0);
        assert_eq!(
            column_geometry_allowance(6 + 46).expect("one header"),
            std::mem::size_of::<ColumnMeta>() as u64
        );
        assert!(column_geometry_allowance(u64::MAX).is_ok());
        assert!(element_bytes::<ColumnMeta>(u64::MAX).is_err());

        let (schema, body) = two_block_keyword_fixture();
        let tiny = SegmentLimits::default().with_max_single_allocation(1);
        assert!(matches!(
            ColumnReader::open(&schema, &body, &tiny),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    // GA-U12 — two readers from one admitted state borrow the same table and
    // keep independent query-local counters.
    #[test]
    fn u12_repeated_borrows_share_identity_but_not_counters() {
        let (schema, body) = two_block_keyword_fixture();
        let limits = SegmentLimits::default();
        let geometry = ColumnReader::open(&schema, &body, &limits)
            .expect("parse")
            .into_geometry();
        let first = ColumnReader::from_validated_geometry(&schema, &body, &limits, &geometry);
        let second = ColumnReader::from_validated_geometry(&schema, &body, &limits, &geometry);
        assert_eq!(first.geometry_ptr(), second.geometry_ptr());
        assert_eq!(first.blocks_read(), 0);
        assert_eq!(second.blocks_read(), 0);
        let field_id = schema.field_id("tag").expect("tag");
        first.value(field_id, 0).expect("first");
        assert_eq!(first.blocks_read(), 1);
        assert_eq!(second.blocks_read(), 0);
        second.value(field_id, 3).expect("second");
        assert_eq!(first.blocks_read(), 1);
        assert_eq!(second.blocks_read(), 1);
    }
}
