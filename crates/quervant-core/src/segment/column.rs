//! Typed columnar blocks with bounded document-N access (F07).
//!
//! Each column is split into uniform blocks of the **persisted** `block_docs`
//! rows. Doc `N` is located by O(1) directory arithmetic and touches at most its
//! containing block.

use std::cell::Cell;

use crate::contract::document::{Cardinality, FieldValues};
use crate::contract::value::{FieldType, FieldValue};

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::metadata::{MetadataMeter, accumulate, capacity_bytes, element_bytes};
use super::model::SegmentDocument;
use super::schema::{CodecField, CodecSchema, field_type_tag};
use super::value::{
    STATE_ABSENT, STATE_EMPTY_MULTI, STATE_EXPLICIT_NULL, STATE_MULTI, STATE_SINGLE, decode_scalar,
    encode_scalar, state_of,
};

/// Fixed-width single-valued layout.
pub const LAYOUT_FIXED_SINGLE: u8 = 0x01;
/// Variable-length / multi-valued layout.
pub const LAYOUT_VARIABLE_MULTI: u8 = 0x02;
/// Sorted raw-keyword dictionary plus compact per-document ordinals (v2).
pub const LAYOUT_KEYWORD_ORDINAL_SINGLE: u8 = 0x03;

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

/// Legacy v1 column planning record (unchanged bytes/grammar).
struct ColumnPlan {
    field_id: u32,
    type_tag: u8,
    layout: u8,
    doc_count: u64,
    block_docs: u32,
    blocks: Vec<BlockPlan>,
}

/// How a caller supplies documents to the column encoder.
///
/// `References` lets ordinary building reuse the already borrowed physical-order
/// document list instead of cloning it a second time for columns alone.
pub(crate) enum ColumnDocuments<'a> {
    /// A contiguous borrowed document slice.
    Documents(&'a [SegmentDocument]),
    /// A borrowed list of borrowed documents.
    References(&'a [&'a SegmentDocument]),
}

impl<'a> ColumnDocuments<'a> {
    /// Number of documents offered to the encoder.
    pub(crate) fn len(&self) -> usize {
        match self {
            Self::Documents(docs) => docs.len(),
            Self::References(docs) => docs.len(),
        }
    }

    fn get(&self, index: usize) -> Option<&'a SegmentDocument> {
        match self {
            Self::Documents(docs) => docs.get(index),
            Self::References(docs) => docs.get(index).copied(),
        }
    }
}

/// An encoded COLUMNS body plus whether it carries keyword ordinals.
#[derive(Debug)]
pub(crate) struct EncodedColumns {
    pub(crate) bytes: Vec<u8>,
    pub(crate) has_keyword_ordinals: bool,
}

/// Whether a field is eligible for the persistent single-valued keyword ordinal
/// layout: columnar, single-cardinality Keyword.
pub(crate) fn is_keyword_ordinal_field(field: &CodecField) -> bool {
    field.is_columnar()
        && field.field_type == FieldType::Keyword
        && field.cardinality == Cardinality::Single
}

/// Smallest packed little-endian width in `1..=8` that can hold `max_value`.
///
/// A zero value uses width 1. Shared by the column codec and the snapshot-wide
/// ordinal maps so both use exactly one width algorithm.
pub(crate) const fn packed_width(max_value: u64) -> u8 {
    let bits = u64::BITS - max_value.leading_zeros();
    let bytes = bits.div_ceil(8);
    if bytes == 0 { 1 } else { bytes as u8 }
}

fn output_overflow() -> SegmentError {
    SegmentError::InvalidColumnGeometry {
        detail: "column output overflow",
    }
}

fn invalid_geometry(detail: &'static str) -> SegmentError {
    SegmentError::InvalidColumnGeometry { detail }
}

fn invalid_geometry_dictionary_extent() -> SegmentError {
    invalid_geometry("keyword dictionary extent overflow")
}

fn dictionary_lookup_out_of_bounds() -> SegmentError {
    SegmentError::InvalidColumnGeometry {
        detail: "keyword dictionary ordinal out of range",
    }
}

fn write_packed_at(buf: &mut [u8], at: usize, width: u8, value: u64) -> SegmentResult<()> {
    let end = at.checked_add(width as usize).ok_or_else(output_overflow)?;
    let slot = buf.get_mut(at..end).ok_or_else(output_overflow)?;
    let raw = value.to_le_bytes();
    slot.copy_from_slice(&raw[..width as usize]);
    Ok(())
}

fn read_packed_at(bytes: &[u8], at: usize, width: u8) -> SegmentResult<u64> {
    let end = at
        .checked_add(width as usize)
        .ok_or_else(dictionary_lookup_out_of_bounds)?;
    let slot = bytes
        .get(at..end)
        .ok_or_else(dictionary_lookup_out_of_bounds)?;
    let mut raw = [0u8; 8];
    raw[..width as usize].copy_from_slice(slot);
    Ok(u64::from_le_bytes(raw))
}

/// A sequential writer over the pre-admitted final COLUMNS buffer.
struct FixedBuf<'a> {
    buf: &'a mut [u8],
    pos: usize,
}

impl<'a> FixedBuf<'a> {
    fn new(buf: &'a mut [u8]) -> Self {
        Self { buf, pos: 0 }
    }

    fn put(&mut self, bytes: &[u8]) -> SegmentResult<()> {
        let end = self
            .pos
            .checked_add(bytes.len())
            .ok_or_else(output_overflow)?;
        let slot = self
            .buf
            .get_mut(self.pos..end)
            .ok_or_else(output_overflow)?;
        slot.copy_from_slice(bytes);
        self.pos = end;
        Ok(())
    }

    fn u8(&mut self, value: u8) -> SegmentResult<()> {
        self.put(&[value])
    }

    fn u16(&mut self, value: u16) -> SegmentResult<()> {
        self.put(&value.to_le_bytes())
    }

    fn u32(&mut self, value: u32) -> SegmentResult<()> {
        self.put(&value.to_le_bytes())
    }

    fn u64(&mut self, value: u64) -> SegmentResult<()> {
        self.put(&value.to_le_bytes())
    }

    fn buffer_mut(&mut self) -> &mut [u8] {
        &mut *self.buf
    }

    fn advance(&mut self, len: usize) -> SegmentResult<()> {
        let end = self.pos.checked_add(len).ok_or_else(output_overflow)?;
        if end > self.buf.len() {
            return Err(output_overflow());
        }
        self.pos = end;
        Ok(())
    }
}

/// One admitted fallible growth of a new B1 encoding buffer.
///
/// The requested total backing bytes are checked against
/// `max_single_allocation`; only the capacity delta is charged against the
/// operation's cumulative budget; the actual post-allocation capacity is
/// reconciled and charged. An allocator refusal is reported in bytes.
fn reserve_growth<T>(
    values: &mut Vec<T>,
    desired_capacity: usize,
    budget: &mut DecodeBudget<'_>,
    limits: &SegmentLimits,
) -> SegmentResult<()> {
    if desired_capacity <= values.capacity() {
        return Ok(());
    }
    let total = capacity_bytes::<T>(desired_capacity)?;
    limits.check_allocation_bytes(total)?;
    let additional = capacity_bytes::<T>(desired_capacity - values.capacity())?;
    budget.reserve_bytes(additional)?;
    values
        .try_reserve_exact(desired_capacity - values.len())
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: total,
        })?;
    let actual = values.capacity();
    if actual > desired_capacity {
        let measured = capacity_bytes::<T>(actual)?;
        if measured > limits.max_single_allocation() {
            return Err(SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: measured,
            });
        }
        budget.reserve_bytes(capacity_bytes::<T>(actual - desired_capacity)?)?;
    }
    Ok(())
}

fn keyword_term<'v>(field: &CodecField, value: &'v FieldValue) -> SegmentResult<&'v str> {
    match value {
        FieldValue::Keyword(text) => {
            if text.len() > usize::from(u16::MAX) {
                return Err(SegmentError::LengthMismatch {
                    context: "u16 length prefix",
                    expected: u64::from(u16::MAX),
                    actual: text.len() as u64,
                });
            }
            Ok(text.as_str())
        }
        _ => Err(SegmentError::FieldTypeMismatch {
            field: field.name.clone(),
        }),
    }
}

/// Rows in one column block for a uniform `block_docs` policy.
fn block_rows(doc_count: usize, block_docs: u32, block: usize) -> usize {
    let start = block * block_docs as usize;
    doc_count.saturating_sub(start).min(block_docs as usize)
}

/// Byte offsets (relative to `data_base`) of one layout-3 block's state and
/// ordinal-slot extents. All preceding blocks are full `block_docs` blocks.
fn ordinal_block_offsets(
    dict_len: usize,
    block_docs: u32,
    dw: usize,
    block: usize,
    rows: usize,
) -> SegmentResult<(usize, usize)> {
    let bd = block_docs as usize;
    let state_offset = block
        .checked_mul(bd)
        .and_then(|value| value.checked_mul(1 + dw))
        .and_then(|value| value.checked_add(dict_len))
        .ok_or_else(output_overflow)?;
    Ok((state_offset, state_offset + rows))
}

/// Plan one ordinary (non-ordinal) column exactly as the legacy v1 encoder did,
/// borrowing the source values instead of cloning them.
fn plan_ordinary_column(
    field: &CodecField,
    docs: &ColumnDocuments<'_>,
    block_docs: u32,
) -> SegmentResult<Vec<BlockPlan>> {
    let layout = layout_for(field.field_type, field.cardinality);
    let width = slot_width(field.field_type);
    let doc_count = docs.len();
    let block_count = doc_count.div_ceil(block_docs as usize);
    let mut blocks: Vec<BlockPlan> = Vec::new();
    for block in 0..block_count {
        let rows = block_rows(doc_count, block_docs, block);
        let start = block * block_docs as usize;
        let mut state = Vec::with_capacity(rows);
        let mut values = Vec::new();
        if layout == LAYOUT_FIXED_SINGLE {
            for offset in 0..rows {
                let values_state = docs
                    .get(start + offset)
                    .ok_or_else(output_overflow)?
                    .fields
                    .get(&field.name);
                state.push(values_state.map_or(STATE_ABSENT, state_of));
                match values_state {
                    Some(FieldValues::Single(value)) => {
                        let mut slot = ByteWriter::new();
                        encode_scalar(&mut slot, field.field_type, value)?;
                        debug_assert_eq!(slot.len(), width);
                        values.extend_from_slice(slot.as_slice());
                    }
                    _ => values.extend(std::iter::repeat_n(0u8, width)),
                }
            }
        } else {
            let mut offsets: Vec<u64> = Vec::with_capacity(rows + 1);
            offsets.push(0);
            let mut value_area = ByteWriter::new();
            for offset in 0..rows {
                let values_state = docs
                    .get(start + offset)
                    .ok_or_else(output_overflow)?
                    .fields
                    .get(&field.name);
                state.push(values_state.map_or(STATE_ABSENT, state_of));
                match values_state {
                    Some(FieldValues::Single(value)) => {
                        encode_scalar(&mut value_area, field.field_type, value)?;
                    }
                    Some(FieldValues::Multi(list)) => {
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
    Ok(blocks)
}

/// Encode the COLUMNS section body in the legacy version-1 grammar.
///
/// This is the unchanged public compatibility entry point. Its bytes and its
/// error timing are frozen: B1 adds a separate v2 production entry point.
pub fn encode_columns(
    schema: &CodecSchema,
    docs: &[SegmentDocument],
    block_docs: u32,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    encode_legacy(schema, ColumnDocuments::Documents(docs), block_docs, limits)
}

fn encode_legacy(
    schema: &CodecSchema,
    docs: ColumnDocuments<'_>,
    block_docs: u32,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    if block_docs == 0 {
        return Err(SegmentError::InvalidColumnGeometry {
            detail: "zero block_docs",
        });
    }
    let doc_count = docs.len();
    let mut plans: Vec<ColumnPlan> = Vec::new();
    for field in schema.fields() {
        if !field.is_columnar() {
            continue;
        }
        let blocks = plan_ordinary_column(field, &docs, block_docs)?;
        plans.push(ColumnPlan {
            field_id: field.id,
            type_tag: field_type_tag(field.field_type),
            layout: layout_for(field.field_type, field.cardinality),
            doc_count: doc_count as u64,
            block_docs,
            blocks,
        });
    }
    limits.check_entries(doc_count as u64)?;

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

struct OrdinalPlan<'a> {
    state: Vec<u8>,
    /// `(raw term, physical doc id)` in strict byte order.
    records: Vec<(&'a str, u32)>,
    u: u64,
    l: u64,
    ow: u8,
    dw: u8,
    dict_len: usize,
    doc_count: usize,
    block_count: usize,
}

struct PlanHeader {
    field_id: u32,
    type_tag: u8,
    layout: u8,
    doc_count: u64,
    block_docs: u32,
    block_count: u32,
    dir_offset: usize,
    dir_len: usize,
    data_base: usize,
}

enum PlanKind<'a> {
    Ordinary(Vec<BlockPlan>),
    Ordinal(OrdinalPlan<'a>),
}

struct OrdinalColumnPlan<'a> {
    header: PlanHeader,
    kind: PlanKind<'a>,
}

fn push_occurrence<'a>(
    records: &mut Vec<(&'a str, u32)>,
    term: &'a str,
    index: usize,
    doc_count: usize,
    budget: &mut DecodeBudget<'_>,
    limits: &SegmentLimits,
) -> SegmentResult<()> {
    if records.len() == records.capacity() {
        // Geometric growth, capped at the document count; never one-by-one.
        let desired = if records.capacity() == 0 {
            doc_count.min(8)
        } else {
            doc_count.min(records.capacity().saturating_mul(2))
        };
        if desired > records.capacity() {
            reserve_growth(records, desired, budget, limits)?;
        }
    }
    let doc_id = u32::try_from(index).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::from(u32::MAX),
        requested: index as u64,
    })?;
    records.push((term, doc_id));
    Ok(())
}

fn plan_ordinal_column<'a>(
    field: &CodecField,
    docs: &ColumnDocuments<'a>,
    block_docs: u32,
    limits: &SegmentLimits,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<OrdinalPlan<'a>> {
    let doc_count = docs.len();
    let mut state: Vec<u8> = Vec::new();
    reserve_growth(&mut state, doc_count, budget, limits)?;
    state.resize(doc_count, STATE_ABSENT);
    let mut records: Vec<(&'a str, u32)> = Vec::new();
    for (index, state_slot) in state.iter_mut().enumerate() {
        let doc = docs.get(index).ok_or_else(output_overflow)?;
        match doc.fields.get(&field.name) {
            None | Some(FieldValues::Absent) => *state_slot = STATE_ABSENT,
            Some(FieldValues::ExplicitNull) => *state_slot = STATE_EXPLICIT_NULL,
            Some(FieldValues::Empty) => {
                return Err(SegmentError::InvalidColumnGeometry {
                    detail: "empty multi in single keyword column",
                });
            }
            Some(FieldValues::Single(value)) => {
                let term = keyword_term(field, value)?;
                *state_slot = STATE_SINGLE;
                push_occurrence(&mut records, term, index, doc_count, budget, limits)?;
            }
            Some(FieldValues::Multi(list)) => {
                if list.is_empty() {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "zero multi count",
                    });
                }
                if list.len() > 1 {
                    return Err(SegmentError::InvalidColumnGeometry {
                        detail: "multiple values in single keyword column",
                    });
                }
                let term = keyword_term(field, &list[0])?;
                *state_slot = STATE_MULTI;
                push_occurrence(&mut records, term, index, doc_count, budget, limits)?;
            }
        }
    }
    records.sort_unstable_by(|left, right| left.0.as_bytes().cmp(right.0.as_bytes()));

    // One read-only pass determines the exact distinct count and payload size.
    let mut u: u64 = 0;
    let mut l: u64 = 0;
    let mut previous: Option<&str> = None;
    for (term, _) in &records {
        if previous != Some(*term) {
            u = u.checked_add(1).ok_or_else(output_overflow)?;
            l = l
                .checked_add(term.len() as u64)
                .ok_or_else(output_overflow)?;
            previous = Some(*term);
        }
    }
    let ow = packed_width(l);
    let dw = packed_width(u.saturating_sub(1));
    let dictionary_len = 16u64
        .checked_add(
            (u + 1)
                .checked_mul(u64::from(ow))
                .ok_or_else(invalid_geometry_dictionary_extent)?,
        )
        .and_then(|value| value.checked_add(l))
        .ok_or_else(invalid_geometry_dictionary_extent)?;
    let dict_len =
        usize::try_from(dictionary_len).map_err(|_| SegmentError::InvalidColumnGeometry {
            detail: "keyword dictionary extent overflow",
        })?;
    let block_count = doc_count.div_ceil(block_docs as usize);
    Ok(OrdinalPlan {
        state,
        records,
        u,
        l,
        ow,
        dw,
        dict_len,
        doc_count,
        block_count,
    })
}

fn ordinal_data_len(plan: &OrdinalPlan<'_>, block_docs: u32) -> SegmentResult<usize> {
    let mut total = plan.dict_len;
    for block in 0..plan.block_count {
        let rows = block_rows(plan.doc_count, block_docs, block);
        total = total
            .checked_add(rows)
            .and_then(|value| value.checked_add(rows.checked_mul(plan.dw as usize)?))
            .ok_or_else(output_overflow)?;
    }
    Ok(total)
}

/// Check every retained ordinary-column backing individually, then return the
/// checked sum of the same measured capacities.
///
/// The sum is charged to the operation budget by the caller; it is never a
/// substitute for the per-backing single-allocation checks.
fn check_ordinary_retained(
    blocks: &[BlockPlan],
    outer_capacity: usize,
    limits: &SegmentLimits,
) -> SegmentResult<u64> {
    let outer = capacity_bytes::<BlockPlan>(outer_capacity)?;
    limits.check_allocation_bytes(outer)?;
    let mut retained = outer;
    for block in blocks {
        let state = capacity_bytes::<u8>(block.state.capacity())?;
        limits.check_allocation_bytes(state)?;
        let values = capacity_bytes::<u8>(block.values.capacity())?;
        limits.check_allocation_bytes(values)?;
        retained = accumulate(retained, state)?;
        retained = accumulate(retained, values)?;
    }
    Ok(retained)
}

fn plan_data_len(plan: &OrdinalColumnPlan<'_>) -> SegmentResult<usize> {
    match &plan.kind {
        PlanKind::Ordinary(blocks) => {
            let mut total = 0usize;
            for block in blocks {
                total = total
                    .checked_add(block.state.len())
                    .and_then(|value| value.checked_add(block.values.len()))
                    .ok_or_else(output_overflow)?;
            }
            Ok(total)
        }
        PlanKind::Ordinal(ordinal) => ordinal_data_len(ordinal, plan.header.block_docs),
    }
}

fn emit_ordinal_column(
    ordinal: &OrdinalPlan<'_>,
    data_base: usize,
    block_docs: u32,
    buf: &mut [u8],
) -> SegmentResult<()> {
    let dw = ordinal.dw as usize;
    let ow = ordinal.ow;
    write_packed_at(buf, data_base, 8, ordinal.u)?;
    write_packed_at(buf, data_base + 8, 8, ordinal.l)?;
    let offsets_base = data_base + 16;
    let strings_base = offsets_base + (ordinal.u as usize + 1) * ow as usize;
    for block in 0..ordinal.block_count {
        let rows = block_rows(ordinal.doc_count, block_docs, block);
        let (state_offset, _) =
            ordinal_block_offsets(ordinal.dict_len, block_docs, dw, block, rows)?;
        let start = block * block_docs as usize;
        let at = data_base + state_offset;
        let slot = buf.get_mut(at..at + rows).ok_or_else(output_overflow)?;
        slot.copy_from_slice(&ordinal.state[start..start + rows]);
    }
    let mut rank: u64 = 0;
    let mut string_cursor: usize = 0;
    let mut previous: Option<&str> = None;
    for (term, doc) in &ordinal.records {
        if previous != Some(*term) {
            write_packed_at(
                buf,
                offsets_base + rank as usize * ow as usize,
                ow,
                string_cursor as u64,
            )?;
            let at = strings_base + string_cursor;
            let slot = buf
                .get_mut(at..at + term.len())
                .ok_or_else(output_overflow)?;
            slot.copy_from_slice(term.as_bytes());
            string_cursor += term.len();
            rank += 1;
            previous = Some(*term);
        }
        let local = rank - 1;
        let block = *doc as usize / block_docs as usize;
        let relative = *doc as usize % block_docs as usize;
        let rows = block_rows(ordinal.doc_count, block_docs, block);
        let (_, values_offset) =
            ordinal_block_offsets(ordinal.dict_len, block_docs, dw, block, rows)?;
        write_packed_at(
            buf,
            data_base + values_offset + relative * dw,
            ordinal.dw,
            local,
        )?;
    }
    write_packed_at(
        buf,
        offsets_base + ordinal.u as usize * ow as usize,
        ow,
        ordinal.l,
    )?;
    Ok(())
}

/// Encode the production COLUMNS body.
///
/// Emits version 2 with a layout-3 sorted raw-value dictionary and compact
/// document ordinals for every eligible single-valued columnar Keyword field.
/// When the schema has no eligible field the unchanged legacy v1 body is
/// returned byte-identically and no new feature is required.
pub(crate) fn encode_columns_with_ordinals(
    schema: &CodecSchema,
    docs: ColumnDocuments<'_>,
    block_docs: u32,
    limits: &SegmentLimits,
) -> SegmentResult<EncodedColumns> {
    if block_docs == 0 {
        return Err(SegmentError::InvalidColumnGeometry {
            detail: "zero block_docs",
        });
    }
    let doc_count = docs.len();
    limits.check_entries(doc_count as u64)?;
    let has_eligible = schema.fields().iter().any(is_keyword_ordinal_field);
    if !has_eligible {
        return Ok(EncodedColumns {
            bytes: encode_legacy(schema, docs, block_docs, limits)?,
            has_keyword_ordinals: false,
        });
    }
    let columnar_count = schema
        .fields()
        .iter()
        .filter(|field| field.is_columnar())
        .count();
    let block_count = doc_count.div_ceil(block_docs as usize);
    let mut budget = DecodeBudget::new(limits);
    let mut plans: Vec<OrdinalColumnPlan<'_>> = Vec::new();
    reserve_growth(&mut plans, columnar_count, &mut budget, limits)?;
    for field in schema.fields() {
        if !field.is_columnar() {
            continue;
        }
        let eligible = is_keyword_ordinal_field(field);
        let header = PlanHeader {
            field_id: field.id,
            type_tag: field_type_tag(field.field_type),
            layout: if eligible {
                LAYOUT_KEYWORD_ORDINAL_SINGLE
            } else {
                layout_for(field.field_type, field.cardinality)
            },
            doc_count: doc_count as u64,
            block_docs,
            block_count: u32::try_from(block_count).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: block_count as u64,
            })?,
            dir_offset: 0,
            dir_len: 0,
            data_base: 0,
        };
        let kind = if eligible {
            PlanKind::Ordinal(plan_ordinal_column(
                field,
                &docs,
                block_docs,
                limits,
                &mut budget,
            )?)
        } else {
            let blocks = plan_ordinary_column(field, &docs, block_docs)?;
            // Every retained ordinary backing is checked individually against
            // the single-allocation ceiling, then the measured sum is charged to
            // the cumulative budget. The inherited temporary construction
            // buffers inside `plan_ordinary_column` remain the documented B1
            // exception and are not newly pre-admitted here.
            let retained = check_ordinary_retained(&blocks, blocks.capacity(), limits)?;
            budget.reserve_bytes(retained)?;
            PlanKind::Ordinary(blocks)
        };
        plans.push(OrdinalColumnPlan { header, kind });
    }

    let header_size = 6usize
        .checked_add(
            plans
                .len()
                .checked_mul(COLUMN_HEADER_LEN)
                .ok_or_else(output_overflow)?,
        )
        .ok_or_else(output_overflow)?;
    let mut cursor = header_size;
    for plan in &mut plans {
        plan.header.dir_offset = cursor;
        plan.header.dir_len = (plan.header.block_count as usize)
            .checked_mul(BLOCK_ENTRY_LEN)
            .ok_or_else(output_overflow)?;
        cursor = cursor
            .checked_add(plan.header.dir_len)
            .ok_or_else(output_overflow)?;
        plan.header.data_base = cursor;
        cursor = cursor
            .checked_add(plan_data_len(plan)?)
            .ok_or_else(output_overflow)?;
    }
    let total = cursor;
    let mut out: Vec<u8> = Vec::new();
    reserve_growth(&mut out, total, &mut budget, limits)?;
    out.resize(total, 0);

    let mut writer = FixedBuf::new(out.as_mut_slice());
    writer.u16(2)?;
    writer.u32(
        u32::try_from(plans.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: plans.len() as u64,
        })?,
    )?;
    for plan in &plans {
        writer.u32(plan.header.field_id)?;
        writer.u8(plan.header.type_tag)?;
        writer.u8(plan.header.layout)?;
        writer.u64(plan.header.doc_count)?;
        writer.u32(plan.header.block_count)?;
        writer.u32(plan.header.block_docs)?;
        writer.u64(0)?; // reserved state_bitmap_len
        writer.u64(plan.header.dir_offset as u64)?;
        writer.u64(plan.header.dir_len as u64)?;
    }
    debug_assert_eq!(writer.pos, header_size);
    // Directory and data extents are interleaved per column, exactly like the
    // legacy encoder: `[dir_0][data_0][dir_1][data_1]...`.
    for plan in &plans {
        let data_base = plan.header.data_base;
        match &plan.kind {
            PlanKind::Ordinary(blocks) => {
                let mut cursor = data_base;
                for (index, block) in blocks.iter().enumerate() {
                    let first_doc = index as u64 * u64::from(plan.header.block_docs);
                    writer.u64(first_doc)?;
                    writer.u32(block.state.len() as u32)?;
                    let state_offset = cursor - data_base;
                    cursor += block.state.len();
                    let values_offset = cursor - data_base;
                    cursor += block.values.len();
                    writer.u64(state_offset as u64)?;
                    writer.u64(values_offset as u64)?;
                    writer.u64(block.values.len() as u64)?;
                }
                for block in blocks {
                    writer.put(&block.state)?;
                    writer.put(&block.values)?;
                }
            }
            PlanKind::Ordinal(ordinal) => {
                for block in 0..ordinal.block_count {
                    let first_doc = block as u64 * u64::from(plan.header.block_docs);
                    let rows = block_rows(ordinal.doc_count, plan.header.block_docs, block);
                    let (state_offset, values_offset) = ordinal_block_offsets(
                        ordinal.dict_len,
                        plan.header.block_docs,
                        ordinal.dw as usize,
                        block,
                        rows,
                    )?;
                    writer.u64(first_doc)?;
                    writer.u32(rows as u32)?;
                    writer.u64(state_offset as u64)?;
                    writer.u64(values_offset as u64)?;
                    writer.u64(rows as u64 * u64::from(ordinal.dw))?;
                }
                emit_ordinal_column(
                    ordinal,
                    plan.header.data_base,
                    plan.header.block_docs,
                    writer.buffer_mut(),
                )?;
                writer.advance(ordinal_data_len(ordinal, plan.header.block_docs)?)?;
            }
        }
    }
    debug_assert_eq!(writer.pos, total);
    Ok(EncodedColumns {
        bytes: out,
        has_keyword_ordinals: true,
    })
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
    /// Shared raw-term bytes of one layout-3 ordinal row, `start..end` being
    /// absolute offsets into the same immutable `COLUMNS` body.
    Ordinal { state: u8, start: usize, end: usize },
}

/// Preserved source row shape of one layout-3 keyword ordinal value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeywordOrdinalState {
    /// The row held `FieldValues::Single`.
    Single,
    /// The row held the allowed single-element `FieldValues::Multi`.
    MultiOne,
}

/// One layout-3 keyword row read without decoding or allocating.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeywordOrdinalValue {
    /// The field is absent for this document.
    Missing,
    /// The field is explicitly null for this document.
    Null,
    /// A keyword value with its preserved source state.
    Value {
        /// Segment-local dictionary ordinal.
        ordinal: u64,
        /// Preserved `Single` versus single-element `Multi` shape.
        state: KeywordOrdinalState,
    },
}

/// A borrowed, fully validated numeric ordinal view over one keyword column.
///
/// The handle borrows the original immutable section bytes for `'a` and copies
/// only its validated per-field geometry. It owns no `Arc`, clones no data and
/// performs no schema, field-name or dictionary-string search per document.
pub struct KeywordOrdinalColumn<'a> {
    bytes: &'a [u8],
    meta: ColumnMeta,
    dictionary: DictionaryGeometry,
    #[cfg(test)]
    blocks_read: Cell<u64>,
}

impl<'a> KeywordOrdinalColumn<'a> {
    /// Number of distinct raw terms in this segment's dictionary.
    #[must_use]
    pub const fn dictionary_len(&self) -> u64 {
        self.dictionary.terms
    }

    /// Borrow one validated raw dictionary term without allocating.
    pub fn dictionary_term(&self, local_ord: u64) -> SegmentResult<&'a [u8]> {
        let (start, end) = self.dictionary_range(local_ord)?;
        self.bytes
            .get(start..end)
            .ok_or_else(dictionary_lookup_out_of_bounds)
    }

    /// Read one document's local ordinal and preserved source state.
    pub fn doc_ordinal(&self, doc_id: u64) -> SegmentResult<KeywordOrdinalValue> {
        let (state, values_start, relative, _rows) = locate_row(self.bytes, &self.meta, doc_id)?;
        #[cfg(test)]
        self.blocks_read.set(self.blocks_read.get() + 1);
        match state {
            STATE_ABSENT => Ok(KeywordOrdinalValue::Missing),
            STATE_EXPLICIT_NULL => Ok(KeywordOrdinalValue::Null),
            STATE_SINGLE | STATE_MULTI => {
                let width = self.dictionary.ordinal_width;
                let at = values_start + relative as usize * width as usize;
                let ordinal = read_packed_at(self.bytes, at, width)?;
                if ordinal >= self.dictionary.terms {
                    return Err(invalid_geometry("keyword ordinal out of range"));
                }
                Ok(KeywordOrdinalValue::Value {
                    ordinal,
                    state: if state == STATE_SINGLE {
                        KeywordOrdinalState::Single
                    } else {
                        KeywordOrdinalState::MultiOne
                    },
                })
            }
            _ => Err(invalid_geometry("invalid keyword ordinal state")),
        }
    }

    /// Test-only observation of block-directory reads.
    #[cfg(test)]
    pub(crate) fn blocks_read(&self) -> u64 {
        self.blocks_read.get()
    }

    fn dictionary_range(&self, local_ord: u64) -> SegmentResult<(usize, usize)> {
        if local_ord >= self.dictionary.terms {
            return Err(invalid_geometry("keyword dictionary ordinal out of range"));
        }
        let width = self.dictionary.offset_width as usize;
        let offsets_base = self.dictionary.offsets_base;
        let start = read_packed_at(
            self.bytes,
            offsets_base + local_ord as usize * width,
            width as u8,
        )?;
        let end = read_packed_at(
            self.bytes,
            offsets_base + (local_ord + 1) as usize * width,
            width as u8,
        )?;
        if end < start || end > self.dictionary.payload_len {
            return Err(invalid_geometry("keyword dictionary ordinal out of range"));
        }
        Ok((
            self.dictionary.strings_base + start as usize,
            self.dictionary.strings_base + end as usize,
        ))
    }
}

/// A borrowed, fully validated view of one single-valued Keyword column value.
///
/// `Missing`/`Null` mirror the two stateless sort ranks; `Value` borrows the
/// encoded UTF-8 payload from the immutable segment bytes. `LegacyDecode` means
/// the candidate must use the original decoding path (unexpected layout/state).
#[derive(Debug)]
pub(crate) enum ColumnKeywordView<'a> {
    /// No column for the field, absent, or empty multi-value.
    Missing,
    /// Explicit null.
    Null,
    /// A validated borrowed keyword payload.
    Value(&'a str),
    /// Malformed/unexpected state that requires the legacy decoder.
    LegacyDecode,
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
        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("columns version")?;
        match version {
            1 => Self::parse_v1(schema, bytes, limits, expected_doc_count, meter),
            2 => Self::parse_v2(schema, bytes, limits, expected_doc_count, meter),
            other => Err(SegmentError::Corrupt {
                context: "columns version",
                detail: format!("unsupported {other}"),
            }),
        }
    }

    /// The unchanged version-1 parser body.
    fn parse_v1(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
        expected_doc_count: Option<u64>,
        meter: &mut Option<&mut MetadataMeter>,
    ) -> SegmentResult<Self> {
        const HEADER_PREFIX: u64 = 6;
        let mut reader = ByteReader::new(&bytes[2..]);
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

    /// The version-2 parser: header/inventory, dictionary, then block extents.
    ///
    /// New-format dictionary integrity is validated eagerly at open (an explicit
    /// new-feature trust boundary); version-1 keeps its established deferred
    /// value-validation timing.
    fn parse_v2(
        schema: &'a CodecSchema,
        bytes: &'a [u8],
        limits: &SegmentLimits,
        expected_doc_count: Option<u64>,
        meter: &mut Option<&mut MetadataMeter>,
    ) -> SegmentResult<Self> {
        const HEADER_PREFIX: u64 = 6;
        let mut reader = ByteReader::new(&bytes[2..]);
        let column_count = reader.u32("column count")?;
        let column_count_u64 = u64::from(column_count);
        limits.check_entries(column_count_u64)?;
        limits.check_alloc::<ColumnMeta>(column_count_u64)?;
        let header_end_u64 = HEADER_PREFIX
            .checked_add(
                column_count_u64
                    .checked_mul(COLUMN_HEADER_LEN as u64)
                    .ok_or_else(|| invalid_geometry("column header size overflow"))?,
            )
            .ok_or_else(|| invalid_geometry("column header size overflow"))?;
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
        let column_capacity = usize::try_from(column_count)
            .map_err(|_| invalid_geometry("column count out of range"))?;
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
        let mut previous_data_base: u64 = header_end_u64;
        for _ in 0..column_count {
            let field_id = reader.u32("column field id")?;
            if let Some(previous) = previous_field {
                if field_id <= previous {
                    return Err(invalid_geometry("field ids not ascending"));
                }
            }
            previous_field = Some(field_id);
            let field = schema
                .field(field_id)
                .ok_or(SegmentError::UnknownFieldId { field_id })?;
            if !field.is_columnar() {
                return Err(invalid_geometry("field is not columnar"));
            }
            let type_tag = reader.u8("column type tag")?;
            if type_tag != field_type_tag(field.field_type) {
                return Err(SegmentError::FieldTypeMismatch {
                    field: field.name.clone(),
                });
            }
            let layout = reader.u8("column layout")?;
            let expected_layout = if is_keyword_ordinal_field(field) {
                LAYOUT_KEYWORD_ORDINAL_SINGLE
            } else {
                layout_for(field.field_type, field.cardinality)
            };
            if layout != expected_layout {
                return Err(invalid_geometry("column layout does not match schema"));
            }
            let doc_count = reader.u64("column doc count")?;
            if let Some(expected) = expected_doc_count {
                if doc_count != expected {
                    return Err(invalid_geometry(
                        "column doc_count does not match segment doc_count",
                    ));
                }
            }
            let block_count = reader.u32("column block count")?;
            let block_docs = reader.u32("column block docs")?;
            let reserved = reader.u64("column state bitmap len")?;
            if reserved != 0 {
                return Err(invalid_geometry("nonzero v2 column reserved field"));
            }
            let dir_offset = reader.u64("column dir offset")?;
            let dir_len = reader.u64("column dir len")?;
            if block_docs == 0 {
                return Err(invalid_geometry("zero block_docs"));
            }
            let expected_blocks = doc_count.div_ceil(u64::from(block_docs));
            if u64::from(block_count) != expected_blocks {
                return Err(invalid_geometry(
                    "block_count does not match doc_count/block_docs",
                ));
            }
            let expected_dir_len = u64::from(block_count)
                .checked_mul(BLOCK_ENTRY_LEN as u64)
                .ok_or_else(|| invalid_geometry("directory length overflow"))?;
            if dir_len != expected_dir_len {
                return Err(invalid_geometry("dir_len does not match block_count"));
            }
            if dir_offset < header_end_u64 || dir_offset < previous_data_base {
                return Err(invalid_geometry("noncanonical v2 column extent"));
            }
            let dir_offset_usize = usize::try_from(dir_offset)
                .map_err(|_| invalid_geometry("dir offset out of range"))?;
            let data_base_u64 = dir_offset
                .checked_add(dir_len)
                .ok_or_else(|| invalid_geometry("column data overflow"))?;
            if data_base_u64 > bytes.len() as u64 {
                return Err(invalid_geometry("noncanonical v2 column extent"));
            }
            previous_data_base = data_base_u64;
            columns.push(ColumnMeta {
                field_id,
                type_tag,
                layout,
                doc_count,
                block_count,
                block_docs,
                dir_offset: dir_offset_usize,
                data_base: data_base_u64 as usize,
            });
        }

        // Complete ordered field-ID inventory must equal the canonical
        // columnar-field inventory, including empty/all-missing fields.
        let mut expected_ids = schema
            .fields()
            .iter()
            .filter(|field| field.is_columnar())
            .map(|field| field.id);
        let mut ordinal_columns = 0usize;
        for meta in &columns {
            match expected_ids.next() {
                Some(id) if id == meta.field_id => {}
                _ => return Err(invalid_geometry("column inventory does not match schema")),
            }
            if meta.layout == LAYOUT_KEYWORD_ORDINAL_SINGLE {
                ordinal_columns += 1;
            }
        }
        if expected_ids.next().is_some() {
            return Err(invalid_geometry("column inventory does not match schema"));
        }
        if ordinal_columns == 0 {
            return Err(invalid_geometry("v2 columns require keyword ordinals"));
        }

        let mut expected_start = header_end_u64;
        for meta in &columns {
            if meta.dir_offset as u64 != expected_start {
                return Err(invalid_geometry("noncanonical v2 column extent"));
            }
            let field = schema
                .field(meta.field_id)
                .ok_or(SegmentError::UnknownFieldId {
                    field_id: meta.field_id,
                })?;
            let data_base = meta.data_base as u64;
            let mut cursor = data_base;
            let mut dictionary_terms = 0u64;
            let mut dw = 0usize;
            if meta.layout == LAYOUT_KEYWORD_ORDINAL_SINGLE {
                let (dictionary_end, terms, width) =
                    validate_keyword_dictionary(bytes, meta, limits)?;
                cursor = dictionary_end;
                dictionary_terms = terms;
                dw = width;
            }
            for block_index in 0..meta.block_count {
                let entry_offset = meta.dir_offset + block_index as usize * BLOCK_ENTRY_LEN;
                let slice = bytes
                    .get(entry_offset..entry_offset + BLOCK_ENTRY_LEN)
                    .ok_or_else(|| invalid_geometry("block directory truncated"))?;
                let mut entry = ByteReader::new(slice);
                let first_doc = entry.u64("block first doc")?;
                let rows = entry.u32("block rows")?;
                let state_offset = entry.u64("block state offset")?;
                let values_offset = entry.u64("block values offset")?;
                let values_length = entry.u64("block values length")?;
                let expected_first = block_index as u64 * u64::from(meta.block_docs);
                if first_doc != expected_first {
                    return Err(invalid_geometry("block first_doc mismatch"));
                }
                let remaining = meta.doc_count - expected_first;
                let expected_rows = remaining.min(u64::from(meta.block_docs));
                if u64::from(rows) != expected_rows {
                    return Err(invalid_geometry("block row count mismatch"));
                }
                let rows_u64 = u64::from(rows);
                if state_offset != cursor - data_base {
                    return Err(invalid_geometry("noncanonical v2 column extent"));
                }
                let state_end = cursor
                    .checked_add(rows_u64)
                    .ok_or_else(|| invalid_geometry("state extent overflow"))?;
                if values_offset != state_end - data_base {
                    return Err(invalid_geometry("noncanonical v2 column extent"));
                }
                // Layout-specific slot-length validation comes before the
                // section-end check so each fixture reaches its intended bound.
                if meta.layout == LAYOUT_KEYWORD_ORDINAL_SINGLE {
                    let expected_values_len = rows_u64
                        .checked_mul(dw as u64)
                        .ok_or_else(|| invalid_geometry("keyword ordinal slots length mismatch"))?;
                    if values_length != expected_values_len {
                        return Err(invalid_geometry("keyword ordinal slots length mismatch"));
                    }
                } else if meta.layout == LAYOUT_FIXED_SINGLE {
                    let width = slot_width(field.field_type) as u64;
                    let expected_values_len = rows_u64
                        .checked_mul(width)
                        .ok_or_else(|| invalid_geometry("slot extent overflow"))?;
                    if values_length != expected_values_len {
                        return Err(invalid_geometry("fixed slot length mismatch"));
                    }
                }
                let values_end = state_end
                    .checked_add(values_length)
                    .ok_or_else(|| invalid_geometry("values extent overflow"))?;
                if values_end > bytes.len() as u64 {
                    return Err(invalid_geometry("block extent past section"));
                }
                let state_bytes = bytes
                    .get(cursor as usize..state_end as usize)
                    .ok_or_else(|| invalid_geometry("state range out of bounds"))?;
                for state in state_bytes {
                    if !valid_state(*state, meta.layout) {
                        // Layout-3 has its own frozen label; v1/other layouts
                        // keep the historical one.
                        return Err(if meta.layout == LAYOUT_KEYWORD_ORDINAL_SINGLE {
                            invalid_geometry("invalid keyword ordinal state")
                        } else {
                            invalid_geometry("invalid state tag")
                        });
                    }
                }
                match meta.layout {
                    LAYOUT_KEYWORD_ORDINAL_SINGLE => {
                        let values = bytes
                            .get(state_end as usize..values_end as usize)
                            .ok_or_else(|| invalid_geometry("block extent past section"))?;
                        for (index, state) in state_bytes.iter().enumerate() {
                            let ordinal = read_packed_at(values, index * dw, dw as u8)?;
                            match *state {
                                STATE_SINGLE | STATE_MULTI => {
                                    if ordinal >= dictionary_terms {
                                        return Err(invalid_geometry(
                                            "keyword ordinal out of range",
                                        ));
                                    }
                                }
                                _ => {
                                    if ordinal != 0 {
                                        return Err(invalid_geometry(
                                            "stateless keyword ordinal is not zero",
                                        ));
                                    }
                                }
                            }
                        }
                    }
                    LAYOUT_FIXED_SINGLE => {}
                    _ => {
                        let table_len = rows_u64
                            .checked_add(1)
                            .and_then(|value| value.checked_mul(8))
                            .ok_or_else(|| invalid_geometry("offset table overflow"))?;
                        if values_length < table_len {
                            return Err(invalid_geometry("offset table exceeds values extent"));
                        }
                        let value_area_len = values_length - table_len;
                        let mut previous_offset = 0u64;
                        for index in 0..=rows_u64 {
                            let at = state_end as usize + index as usize * 8;
                            let offset = read_u64_at(bytes, at)?;
                            if offset > value_area_len {
                                return Err(invalid_geometry("offset beyond value area"));
                            }
                            if index == 0 && offset != 0 {
                                return Err(invalid_geometry("offset table must start at zero"));
                            }
                            if index > 0 && offset < previous_offset {
                                return Err(invalid_geometry("descending offset table"));
                            }
                            previous_offset = offset;
                        }
                        if previous_offset != value_area_len {
                            return Err(invalid_geometry(
                                "terminal offset does not match value area",
                            ));
                        }
                    }
                }
                cursor = values_end;
            }
            expected_start = cursor;
        }
        if expected_start != bytes.len() as u64 {
            return Err(invalid_geometry("trailing v2 columns bytes"));
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
            ValueSpan::Ordinal { state, start, end } => {
                let term =
                    self.bytes
                        .get(start..end)
                        .ok_or(SegmentError::InvalidColumnGeometry {
                            detail: "value range out of bounds",
                        })?;
                let keyword = std::str::from_utf8(term)
                    .map_err(|_| SegmentError::InvalidUtf8 { context: "keyword" })?;
                match state {
                    STATE_SINGLE => {
                        let mut budget = DecodeBudget::new(&self.limits);
                        budget.reserve_string(keyword.len() as u64)?;
                        let owned = fallible_owned_keyword(keyword, &self.limits)?;
                        Ok(Some(FieldValues::Single(FieldValue::Keyword(owned))))
                    }
                    STATE_MULTI => {
                        // Preserve the original logical admission sequence:
                        // entry count, one-element `FieldValue` vector, then the
                        // keyword string's own decode-budget check.
                        self.limits.check_entries(1)?;
                        self.limits.check_alloc::<FieldValue>(1)?;
                        let mut list: Vec<FieldValue> = Vec::new();
                        list.try_reserve_exact(1)
                            .map_err(|_| SegmentError::LimitExceeded {
                                limit: self.limits.max_single_allocation(),
                                requested: std::mem::size_of::<FieldValue>() as u64,
                            })?;
                        let mut budget = DecodeBudget::new(&self.limits);
                        budget.reserve_string(keyword.len() as u64)?;
                        let owned = fallible_owned_keyword(keyword, &self.limits)?;
                        list.push(FieldValue::Keyword(owned));
                        Ok(Some(FieldValues::Multi(list)))
                    }
                    _ => Err(SegmentError::InvalidColumnGeometry {
                        detail: "unexpected state",
                    }),
                }
            }
        }
    }

    /// Borrow and fully validate one single-valued Keyword column value without
    /// allocating an owned `String`.
    ///
    /// The validation order mirrors `value()` + `decode_scalar()`: u16 length,
    /// range/bounds, UTF-8, decode budget, then `expect_end("column value")`.
    /// Unexpected layouts/states return [`ColumnKeywordView::LegacyDecode`] so
    /// the caller can run the original per-candidate decoder unchanged.
    pub(crate) fn keyword_sort_view(
        &self,
        field_id: u32,
        doc_id: u64,
    ) -> SegmentResult<ColumnKeywordView<'_>> {
        let Some(meta) = self
            .geometry
            .columns()
            .iter()
            .find(|c| c.field_id == field_id)
        else {
            return Ok(ColumnKeywordView::Missing);
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
        if field.field_type != FieldType::Keyword || field.cardinality != Cardinality::Single {
            return Ok(ColumnKeywordView::LegacyDecode);
        }
        match self.span_of(meta, field.field_type, doc_id)? {
            ValueSpan::Stateless(STATE_ABSENT | STATE_EMPTY_MULTI) => {
                Ok(ColumnKeywordView::Missing)
            }
            ValueSpan::Stateless(STATE_EXPLICIT_NULL) => Ok(ColumnKeywordView::Null),
            ValueSpan::Stateless(_) => Ok(ColumnKeywordView::LegacyDecode),
            ValueSpan::Fixed { .. } => Ok(ColumnKeywordView::LegacyDecode),
            ValueSpan::Variable { state, start, end } => {
                if state != STATE_SINGLE {
                    return Ok(ColumnKeywordView::LegacyDecode);
                }
                let slice =
                    self.bytes
                        .get(start..end)
                        .ok_or(SegmentError::InvalidColumnGeometry {
                            detail: "value range out of bounds",
                        })?;
                let mut reader = ByteReader::new(slice);
                let bytes = reader.len_prefixed_u16("keyword")?;
                let keyword = std::str::from_utf8(bytes)
                    .map_err(|_| SegmentError::InvalidUtf8 { context: "keyword" })?;
                let mut budget = DecodeBudget::new(&self.limits);
                budget.reserve_string(keyword.len() as u64)?;
                reader.expect_end("column value")?;
                Ok(ColumnKeywordView::Value(keyword))
            }
            ValueSpan::Ordinal { state, start, end } => {
                if state != STATE_SINGLE {
                    // Do not silently widen sort eligibility: a single-element
                    // multi keeps using the legacy decoder.
                    return Ok(ColumnKeywordView::LegacyDecode);
                }
                let slice =
                    self.bytes
                        .get(start..end)
                        .ok_or(SegmentError::InvalidColumnGeometry {
                            detail: "value range out of bounds",
                        })?;
                let keyword = std::str::from_utf8(slice)
                    .map_err(|_| SegmentError::InvalidUtf8 { context: "keyword" })?;
                let mut budget = DecodeBudget::new(&self.limits);
                budget.reserve_string(keyword.len() as u64)?;
                Ok(ColumnKeywordView::Value(keyword))
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
            ValueSpan::Ordinal { state, start, end } => {
                // Legacy-equivalent *logical* span, never the packed ordinal
                // width: admission must keep charging materialized strings.
                let term_len = u64::try_from(end - start).unwrap_or(u64::MAX);
                let span = term_len.saturating_add(if state == STATE_MULTI { 3 } else { 2 });
                Ok(Some((state, span, 1)))
            }
        }
    }

    fn span_of(
        &self,
        meta: &ColumnMeta,
        field_type: FieldType,
        doc_id: u64,
    ) -> SegmentResult<ValueSpan> {
        let (state, values_start, relative, rows) = locate_row(self.bytes, meta, doc_id)?;
        self.blocks_read.set(self.blocks_read.get() + 1);
        if state == STATE_ABSENT || state == STATE_EXPLICIT_NULL || state == STATE_EMPTY_MULTI {
            return Ok(ValueSpan::Stateless(state));
        }
        if meta.layout == LAYOUT_FIXED_SINGLE {
            let width = slot_width(field_type);
            let start = values_start + relative as usize * width;
            return Ok(ValueSpan::Fixed {
                state,
                start,
                width,
            });
        }
        if meta.layout == LAYOUT_KEYWORD_ORDINAL_SINGLE {
            // The selected metadata is reused directly: no schema or geometry
            // search is repeated per candidate row.
            let handle = self.bind_keyword_ordinal_meta(meta)?;
            let width = handle.dictionary.ordinal_width as usize;
            let ordinal = read_packed_at(
                self.bytes,
                values_start + relative as usize * width,
                width as u8,
            )?;
            let (start, end) = handle.dictionary_range(ordinal)?;
            return Ok(ValueSpan::Ordinal { state, start, end });
        }
        let value_base = values_start;
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

    /// Bind a borrowed numeric-ordinal view over one eligible keyword column.
    ///
    /// Returns `None` when the field has no column or the column is not the
    /// version-2 single-cardinality ordinal layout. The returned handle borrows
    /// the immutable section bytes for `'a`, so it may outlive the temporary
    /// reader that produced it while its owning guarded reader is alive.
    pub fn bind_keyword_ordinals(
        &self,
        field_id: u32,
    ) -> SegmentResult<Option<KeywordOrdinalColumn<'a>>> {
        let Some(meta) = self
            .geometry
            .columns()
            .iter()
            .find(|column| column.field_id == field_id)
        else {
            return Ok(None);
        };
        if meta.layout != LAYOUT_KEYWORD_ORDINAL_SINGLE {
            return Ok(None);
        }
        Ok(Some(self.bind_keyword_ordinal_meta(meta)?))
    }

    /// The shared private constructor: copies only the small validated geometry.
    fn bind_keyword_ordinal_meta(
        &self,
        meta: &ColumnMeta,
    ) -> SegmentResult<KeywordOrdinalColumn<'a>> {
        let dictionary = dictionary_geometry(self.bytes, meta.data_base)?;
        Ok(KeywordOrdinalColumn {
            bytes: self.bytes,
            meta: *meta,
            dictionary,
            #[cfg(test)]
            blocks_read: Cell::new(0),
        })
    }
}

/// Fallible owned copy of one already validated keyword payload.
///
/// Only the layout-3 ordinal branch uses this helper: the legacy scalar decoder
/// keeps its frozen infallible behaviour. Logical string admission
/// (`DecodeBudget::reserve_string`) has already run for the same length.
fn fallible_owned_keyword(keyword: &str, limits: &SegmentLimits) -> SegmentResult<String> {
    let mut owned = String::new();
    owned
        .try_reserve_exact(keyword.len())
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: keyword.len() as u64,
        })?;
    owned.push_str(keyword);
    Ok(owned)
}

/// Locate one document row's shared block/state geometry.
///
/// Both the ordinary span accessors and the bound ordinal handle use this one
/// helper, so neither repeats the block-directory arithmetic or reads the same
/// row twice.
fn locate_row(
    bytes: &[u8],
    meta: &ColumnMeta,
    doc_id: u64,
) -> SegmentResult<(u8, usize, u32, u32)> {
    if doc_id >= meta.doc_count {
        return Err(SegmentError::Corrupt {
            context: "column",
            detail: "doc id out of range".to_owned(),
        });
    }
    let block_index = doc_id / u64::from(meta.block_docs);
    debug_assert!(block_index < u64::from(meta.block_count));
    let entry_offset = meta.dir_offset + block_index as usize * BLOCK_ENTRY_LEN;
    let entry_slice = bytes
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
    let state = *bytes
        .get(meta.data_base + state_offset as usize + relative as usize)
        .ok_or(SegmentError::InvalidColumnGeometry {
            detail: "state byte out of range",
        })?;
    Ok((
        state,
        meta.data_base + values_offset as usize,
        relative as u32,
        rows,
    ))
}

/// Read the two-byte COLUMNS payload version without parsing the body.
///
/// Used by the containing segment reader to enforce required-feature agreement
/// before any payload decoding. A truncated prefix keeps the existing
/// `Truncated` error class with the `columns version` context.
pub(crate) fn columns_body_version(bytes: &[u8]) -> SegmentResult<u16> {
    let mut reader = ByteReader::new(bytes);
    reader.u16("columns version")
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
        // The single-cardinality ordinal layout accepts exactly one keyword
        // value per row; a zero-count multi (`STATE_EMPTY_MULTI`) is illegal.
        LAYOUT_KEYWORD_ORDINAL_SINGLE => matches!(
            state,
            STATE_ABSENT | STATE_EXPLICIT_NULL | STATE_SINGLE | STATE_MULTI
        ),
        _ => state <= STATE_MULTI,
    }
}

/// Derived, non-retained geometry of one layout-3 keyword dictionary.
#[derive(Debug, Clone, Copy)]
struct DictionaryGeometry {
    terms: u64,
    payload_len: u64,
    offset_width: u8,
    ordinal_width: u8,
    offsets_base: usize,
    strings_base: usize,
    strings_end: usize,
    dictionary_end: u64,
}

/// Derive the fixed dictionary geometry from its 16-byte prefix.
///
/// Nothing is retained: callers copy this small handle. The authoritative
/// parser has already validated every referenced byte.
/// The checked 16-byte `(U, L)` prefix of a layout-3 dictionary.
#[derive(Debug, Clone, Copy)]
struct DictionaryPrefix {
    terms: u64,
    payload_len: u64,
}

/// Read the two `u64` prefix fields with the frozen contexts only.
///
/// This performs no count-dependent arithmetic, so an arbitrary hostile `U`
/// cannot overflow before the authoritative count checks run.
fn read_dictionary_prefix(bytes: &[u8], data_base: usize) -> SegmentResult<DictionaryPrefix> {
    let prefix = bytes
        .get(data_base..)
        .ok_or_else(|| invalid_geometry("keyword dictionary extent out of range"))?;
    let mut reader = ByteReader::new(prefix);
    let terms = reader.u64("keyword dictionary term count")?;
    let payload_len = reader.u64("keyword dictionary byte length")?;
    Ok(DictionaryPrefix { terms, payload_len })
}

/// Derive checked geometry from already validated `(U, L)`.
fn dictionary_geometry_from(
    prefix: DictionaryPrefix,
    data_base: usize,
) -> SegmentResult<DictionaryGeometry> {
    let terms = prefix.terms;
    let payload_len = prefix.payload_len;
    let offset_width = packed_width(payload_len);
    let ordinal_width = packed_width(terms.saturating_sub(1));
    let offsets_len = terms
        .checked_add(1)
        .and_then(|count| count.checked_mul(u64::from(offset_width)))
        .ok_or_else(|| invalid_geometry("keyword dictionary extent overflow"))?;
    let offsets_base = data_base
        .checked_add(16)
        .ok_or_else(|| invalid_geometry("keyword dictionary extent overflow"))?;
    let offsets_len_usize = usize::try_from(offsets_len)
        .map_err(|_| invalid_geometry("keyword dictionary extent overflow"))?;
    let strings_base = offsets_base
        .checked_add(offsets_len_usize)
        .ok_or_else(|| invalid_geometry("keyword dictionary extent overflow"))?;
    let payload_len_usize = usize::try_from(payload_len)
        .map_err(|_| invalid_geometry("keyword dictionary extent overflow"))?;
    let strings_end = strings_base
        .checked_add(payload_len_usize)
        .ok_or_else(|| invalid_geometry("keyword dictionary extent overflow"))?;
    let dictionary_len = 16u64
        .checked_add(offsets_len)
        .and_then(|value| value.checked_add(payload_len))
        .ok_or_else(|| invalid_geometry("keyword dictionary extent overflow"))?;
    let dictionary_end = (data_base as u64)
        .checked_add(dictionary_len)
        .ok_or_else(|| invalid_geometry("keyword dictionary extent overflow"))?;
    Ok(DictionaryGeometry {
        terms,
        payload_len,
        offset_width,
        ordinal_width,
        offsets_base,
        strings_base,
        strings_end,
        dictionary_end,
    })
}

/// Derive geometry for an already authoritatively validated dictionary.
fn dictionary_geometry(bytes: &[u8], data_base: usize) -> SegmentResult<DictionaryGeometry> {
    dictionary_geometry_from(read_dictionary_prefix(bytes, data_base)?, data_base)
}

/// Validate one layout-3 dictionary and return `(end offset, U, dw)`.
///
/// Frozen precedence: `U > doc_count`, then `U=0 && L!=0`, configured entry
/// limits, checked geometry/extents, then one ordered pass that validates each
/// just-delimited term (length, UTF-8, strict raw-byte order) before reading the
/// next offset, and finally the terminal offset.
fn validate_keyword_dictionary(
    bytes: &[u8],
    meta: &ColumnMeta,
    limits: &SegmentLimits,
) -> SegmentResult<(u64, u64, usize)> {
    let prefix = read_dictionary_prefix(bytes, meta.data_base)?;
    if prefix.terms > meta.doc_count {
        return Err(invalid_geometry(
            "keyword dictionary count exceeds document count",
        ));
    }
    if prefix.terms == 0 && prefix.payload_len != 0 {
        return Err(invalid_geometry("empty keyword dictionary has payload"));
    }
    limits.check_entries(prefix.terms)?;
    let geometry = dictionary_geometry_from(prefix, meta.data_base)?;
    if geometry.dictionary_end > bytes.len() as u64 {
        return Err(invalid_geometry("keyword dictionary extent out of range"));
    }
    if geometry.strings_end > bytes.len() {
        return Err(invalid_geometry("keyword dictionary extent out of range"));
    }
    let width = geometry.offset_width as usize;
    let terms = geometry.terms;
    let payload_len = geometry.payload_len;
    let read_offset = |index: u64| {
        read_packed_at(
            bytes,
            geometry.offsets_base + index as usize * width,
            geometry.offset_width,
        )
        .map_err(|_| invalid_geometry("keyword dictionary extent out of range"))
    };
    let mut start = read_offset(0)?;
    if start != 0 {
        return Err(invalid_geometry(
            "keyword dictionary offsets must start at zero",
        ));
    }
    let mut previous_term: Option<&[u8]> = None;
    for index in 0..terms {
        let end = read_offset(index + 1)?;
        if end > payload_len {
            return Err(invalid_geometry(
                "keyword dictionary offset exceeds payload",
            ));
        }
        if end < start {
            return Err(invalid_geometry("keyword dictionary offsets descend"));
        }
        let term_len = end - start;
        if term_len > u64::from(u16::MAX) {
            return Err(SegmentError::LengthMismatch {
                context: "u16 length prefix",
                expected: u64::from(u16::MAX),
                actual: term_len,
            });
        }
        let from = geometry.strings_base + start as usize;
        let to = geometry.strings_base + end as usize;
        let term = bytes
            .get(from..to)
            .ok_or_else(|| invalid_geometry("keyword dictionary extent out of range"))?;
        std::str::from_utf8(term).map_err(|_| SegmentError::InvalidUtf8 { context: "keyword" })?;
        if let Some(previous) = previous_term {
            if previous >= term {
                return Err(invalid_geometry(
                    "keyword dictionary terms are not strictly ascending",
                ));
            }
        }
        previous_term = Some(term);
        start = end;
    }
    if start != payload_len {
        return Err(invalid_geometry(
            "keyword dictionary terminal offset mismatch",
        ));
    }
    Ok((
        geometry.dictionary_end,
        terms,
        geometry.ordinal_width as usize,
    ))
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

/// PR 15H-B — borrowed keyword view validation tests.
#[cfg(test)]
mod b_keyword_view_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
    use crate::contract::document::{Cardinality, DocumentKey};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};

    fn codec(cardinality: Cardinality) -> CodecSchema {
        let schema = Schema::new(
            vec![
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    cardinality,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
            ],
            None,
        )
        .expect("schema");
        let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin())
            .expect("bindings");
        CodecSchema::from_contract(&schema, &bindings).expect("codec")
    }

    fn document(key: &str, values: FieldValues) -> SegmentDocument {
        let mut doc = SegmentDocument::new(DocumentKey::new(key).expect("key"));
        doc.insert("tag", values).expect("insert");
        doc
    }

    fn keyword(value: &str) -> FieldValues {
        FieldValues::Single(FieldValue::Keyword(value.to_owned()))
    }

    fn fixture() -> (CodecSchema, Vec<u8>) {
        let schema = codec(Cardinality::Single);
        let docs = vec![
            document("k0", keyword("alpha")),
            document("k1", FieldValues::ExplicitNull),
            document("k2", FieldValues::Absent),
            document("k3", keyword("beta")),
            document("k4", keyword("gamma")),
        ];
        let body = encode_columns(&schema, &docs, 2, &SegmentLimits::default()).expect("columns");
        (schema, body)
    }

    fn open<'a>(
        schema: &'a CodecSchema,
        body: &'a [u8],
        limits: &SegmentLimits,
    ) -> ColumnReader<'a> {
        ColumnReader::open(schema, body, limits).expect("parse")
    }

    #[test]
    fn b_u06_u16_missing_null_value_and_multi_fallback() {
        let (schema, body) = fixture();
        let limits = SegmentLimits::default();
        let field = schema.field_id("tag").expect("tag");
        let reader = open(&schema, &body, &limits);
        assert!(matches!(
            reader.keyword_sort_view(field, 0).unwrap(),
            ColumnKeywordView::Value("alpha")
        ));
        assert!(matches!(
            reader.keyword_sort_view(field, 1).unwrap(),
            ColumnKeywordView::Null
        ));
        assert!(matches!(
            reader.keyword_sort_view(field, 2).unwrap(),
            ColumnKeywordView::Missing
        ));
        assert!(matches!(
            reader.keyword_sort_view(field, 3).unwrap(),
            ColumnKeywordView::Value("beta")
        ));

        // Multi cardinality is explicitly a legacy decode, not an approximation.
        let multi_schema = codec(Cardinality::Multi);
        let docs = vec![document("k0", keyword("alpha"))];
        let multi_body = encode_columns(&multi_schema, &docs, 1, &limits).expect("multi columns");
        let field = multi_schema.field_id("tag").expect("tag");
        let reader = ColumnReader::open(&multi_schema, &multi_body, &limits).expect("parse");
        assert!(matches!(
            reader.keyword_sort_view(field, 0).unwrap(),
            ColumnKeywordView::LegacyDecode
        ));
    }

    #[test]
    fn b_u14_invalid_utf8_rejected() {
        let (schema, mut body) = fixture();
        let position = body
            .windows(5)
            .position(|window| window == b"alpha")
            .expect("alpha payload");
        body[position] = 0xFF;
        let field = schema.field_id("tag").expect("tag");
        let reader = open(&schema, &body, &SegmentLimits::default());
        assert!(matches!(
            reader.keyword_sort_view(field, 0),
            Err(SegmentError::InvalidUtf8 { context: "keyword" })
        ));
    }

    #[test]
    fn b_u17_out_of_range_rejected() {
        let (schema, body) = fixture();
        let field = schema.field_id("tag").expect("tag");
        let reader = open(&schema, &body, &SegmentLimits::default());
        assert!(matches!(
            reader.keyword_sort_view(field, 5),
            Err(SegmentError::Corrupt {
                context: "column",
                ..
            })
        ));
    }

    #[test]
    fn b_u18_decode_budget_rejected() {
        let (schema, body) = fixture();
        let default = SegmentLimits::default();
        let geometry = ColumnReader::open(&schema, &body, &default)
            .expect("parse")
            .into_geometry();
        let tiny = SegmentLimits::default()
            .with_max_single_allocation(2)
            .with_max_section_decode_bytes(2);
        let reader = ColumnReader::from_validated_geometry(&schema, &body, &tiny, &geometry);
        let field = schema.field_id("tag").expect("tag");
        assert!(matches!(
            reader.keyword_sort_view(field, 0),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }
}

/// PERF-06-B1 — persistent keyword ordinal codec tests.
#[cfg(test)]
mod b1_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
    use crate::contract::document::{Cardinality, DocumentKey};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};

    fn codec(fields: Vec<FieldDefinition>) -> CodecSchema {
        let schema = Schema::new(fields, None).expect("contract schema");
        let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin())
            .expect("bindings");
        CodecSchema::from_contract(&schema, &bindings).expect("codec schema")
    }

    fn keyword_single(name: &str) -> FieldDefinition {
        FieldDefinition::new(
            name,
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, true, true),
        )
        .with_normalizer("keyword")
    }

    fn keyword_multi(name: &str) -> FieldDefinition {
        FieldDefinition::new(
            name,
            FieldType::Keyword,
            Cardinality::Multi,
            FieldOptions::new(true, true, true),
        )
        .with_normalizer("keyword")
    }

    fn i64_field(name: &str) -> FieldDefinition {
        FieldDefinition::new(
            name,
            FieldType::I64,
            Cardinality::Single,
            FieldOptions::new(false, true, true),
        )
    }

    fn doc(key: &str) -> SegmentDocument {
        SegmentDocument::new(DocumentKey::new(key).expect("key"))
    }

    fn put(document: &mut SegmentDocument, field: &str, values: FieldValues) {
        document.insert(field, values).expect("insert");
    }

    fn single(value: &str) -> FieldValues {
        FieldValues::Single(FieldValue::Keyword(value.to_owned()))
    }

    fn multi_one(value: &str) -> FieldValues {
        FieldValues::Multi(vec![FieldValue::Keyword(value.to_owned())])
    }

    fn hex(text: &str) -> Vec<u8> {
        let digits: Vec<u8> = text
            .split_whitespace()
            .map(|byte| u8::from_str_radix(byte, 16).expect("hex byte"))
            .collect();
        digits
    }

    fn encode_v2(
        schema: &CodecSchema,
        docs: &[SegmentDocument],
        block_docs: u32,
    ) -> EncodedColumns {
        encode_columns_with_ordinals(
            schema,
            ColumnDocuments::Documents(docs),
            block_docs,
            &SegmentLimits::default(),
        )
        .expect("v2 columns")
    }

    fn dictionary_terms(reader: &ColumnReader<'_>, field_id: u32) -> Vec<String> {
        let handle = reader
            .bind_keyword_ordinals(field_id)
            .expect("bind")
            .expect("ordinal column");
        (0..handle.dictionary_len())
            .map(|ordinal| {
                String::from_utf8(handle.dictionary_term(ordinal).expect("term").to_vec())
                    .expect("utf8")
            })
            .collect()
    }

    // B1-U02 — the frozen 116-byte v2 wire witness and the 137-byte v1 control.
    #[test]
    fn b1_u02_literal_wire_witness_is_exact() {
        let schema = codec(vec![keyword_single("city")]);
        let mut docs = Vec::new();
        for (index, values) in [
            FieldValues::Absent,
            FieldValues::ExplicitNull,
            single("b"),
            single(""),
        ]
        .into_iter()
        .enumerate()
        {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", values);
            docs.push(document);
        }
        let encoded = encode_v2(&schema, &docs, 4);
        assert!(encoded.has_keyword_ordinals);
        let expected = hex("02 00 01 00 00 00
             00 00 00 00 02 03
             04 00 00 00 00 00 00 00
             01 00 00 00 04 00 00 00
             00 00 00 00 00 00 00 00
             34 00 00 00 00 00 00 00
             24 00 00 00 00 00 00 00
             00 00 00 00 00 00 00 00
             04 00 00 00
             14 00 00 00 00 00 00 00
             18 00 00 00 00 00 00 00
             04 00 00 00 00 00 00 00
             02 00 00 00 00 00 00 00
             01 00 00 00 00 00 00 00
             00 00 01 62
             00 01 03 03
             00 00 01 00");
        assert_eq!(expected.len(), 116);
        assert_eq!(encoded.bytes, expected);

        // The legacy encoder keeps its own grammar and size for the same input.
        let legacy = encode_columns(&schema, &docs, 4, &SegmentLimits::default()).expect("v1");
        assert_eq!(&legacy[..2], &1u16.to_le_bytes());
        assert_eq!(legacy.len(), 137);
    }

    // B1-U01 — empty, value-less and mixed state/dictionary cases.
    #[test]
    fn b1_u01_empty_and_stateless_documents_are_exact() {
        let schema = codec(vec![keyword_single("city")]);
        let empty = encode_v2(&schema, &[], 4);
        assert_eq!(&empty.bytes[..2], &2u16.to_le_bytes());
        // 6 prefix + 46 header + 0 directory (no blocks) + 17 dictionary bytes.
        assert_eq!(empty.bytes.len(), 6 + 46 + 17);
        assert_eq!(empty.bytes[6 + 46..].to_vec(), {
            let mut expected = vec![0u8; 16];
            expected.push(0);
            expected
        });

        let mut all_absent = Vec::new();
        let mut all_null = Vec::new();
        let mut mixed = Vec::new();
        for index in 0..3 {
            let mut a = doc(&format!("a{index}"));
            put(&mut a, "city", FieldValues::Absent);
            all_absent.push(a);
            let mut n = doc(&format!("n{index}"));
            put(&mut n, "city", FieldValues::ExplicitNull);
            all_null.push(n);
        }
        let mut m0 = doc("m0");
        put(&mut m0, "city", FieldValues::Absent);
        let mut m1 = doc("m1");
        put(&mut m1, "city", FieldValues::ExplicitNull);
        let mut m2 = doc("m2");
        put(&mut m2, "city", single(""));
        mixed.push(m0);
        mixed.push(m1);
        mixed.push(m2);

        for docs in [&all_absent, &all_null] {
            let encoded = encode_v2(&schema, docs, 4);
            let reader = ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default())
                .expect("parse");
            let field = schema.field_id("city").expect("city");
            let handle = reader
                .bind_keyword_ordinals(field)
                .expect("bind")
                .expect("ordinal");
            assert_eq!(handle.dictionary_len(), 0);
            for doc_id in 0..3 {
                assert_ne!(
                    handle.doc_ordinal(doc_id).expect("row"),
                    KeywordOrdinalValue::Value {
                        ordinal: 0,
                        state: KeywordOrdinalState::Single
                    }
                );
            }
        }

        let encoded = encode_v2(&schema, &mixed, 4);
        let reader =
            ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default()).expect("parse");
        let field = schema.field_id("city").expect("city");
        let handle = reader
            .bind_keyword_ordinals(field)
            .expect("bind")
            .expect("ordinal");
        assert_eq!(dictionary_terms(&reader, field), vec![String::new()]);
        assert_eq!(
            handle.doc_ordinal(0).expect("row"),
            KeywordOrdinalValue::Missing
        );
        assert_eq!(
            handle.doc_ordinal(1).expect("row"),
            KeywordOrdinalValue::Null
        );
        assert_eq!(
            handle.doc_ordinal(2).expect("row"),
            KeywordOrdinalValue::Value {
                ordinal: 0,
                state: KeywordOrdinalState::Single
            }
        );
        // The empty string is a real value, never a missing/null sentinel.
        assert_eq!(reader.value(field, 2).expect("value"), Some(single("")));
    }

    // B1-U03 — raw byte order, duplicates, NUL, prefixes and Unicode.
    #[test]
    fn b1_u03_dictionary_order_is_raw_and_duplicate_free() {
        let schema = codec(vec![keyword_single("city")]);
        let raw = [
            "é", "e\u{301}", "Z", "aa", "a", "Seattle", "Austin", "\0", "",
        ];
        let mut docs = Vec::new();
        for (index, value) in raw.iter().enumerate() {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", single(value));
            docs.push(document);
        }
        // Duplicate values across documents must not duplicate dictionary terms.
        let mut duplicate = doc("dup");
        put(&mut duplicate, "city", single("Austin"));
        docs.push(duplicate);

        let encoded = encode_v2(&schema, &docs, 16);
        let reader =
            ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default()).expect("parse");
        let field = schema.field_id("city").expect("city");
        let terms = dictionary_terms(&reader, field);
        let mut expected: Vec<&str> = raw.to_vec();
        expected.sort_by(|left, right| left.as_bytes().cmp(right.as_bytes()));
        expected.dedup();
        let expected: Vec<String> = expected.into_iter().map(str::to_owned).collect();
        assert_eq!(terms, expected);
        // Composed and decomposed forms stay distinct: no normalization.
        assert_ne!(
            terms.iter().position(|t| t == "é"),
            terms.iter().position(|t| t == "e\u{301}")
        );
    }

    // B1-U04 — packed width boundaries and block boundaries.
    #[test]
    fn b1_u04_packed_width_and_block_boundaries() {
        assert_eq!(packed_width(0), 1);
        assert_eq!(packed_width(1), 1);
        assert_eq!(packed_width(255), 1);
        assert_eq!(packed_width(256), 2);
        assert_eq!(packed_width(65_535), 2);
        assert_eq!(packed_width(65_536), 3);
        assert_eq!(packed_width(1 << 24), 4);
        assert_eq!(packed_width(u32::MAX as u64), 4);
        assert_eq!(packed_width((1 << 40) - 1), 5);
        assert_eq!(packed_width(u64::MAX), 8);

        let schema = codec(vec![keyword_single("city")]);
        for count in [254usize, 255, 256, 257] {
            let mut docs = Vec::new();
            for index in 0..count {
                let mut document = doc(&format!("k{index}"));
                put(&mut document, "city", single(&format!("t{index:04}")));
                docs.push(document);
            }
            let encoded = encode_v2(&schema, &docs, 1024);
            let reader = ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default())
                .expect("parse");
            let field = schema.field_id("city").expect("city");
            let handle = reader
                .bind_keyword_ordinals(field)
                .expect("bind")
                .expect("ordinal");
            assert_eq!(handle.dictionary_len(), count as u64);
            let dw = packed_width(count as u64 - 1) as usize;
            for index in 0..count {
                assert_eq!(
                    handle.doc_ordinal(index as u64).expect("row"),
                    KeywordOrdinalValue::Value {
                        ordinal: index as u64,
                        state: KeywordOrdinalState::Single
                    }
                );
            }
            // The ordinal slots of one block must be exactly rows*dw bytes.
            let dir_offset = 6 + 46;
            let data_base = dir_offset + 36;
            let entry = &encoded.bytes[dir_offset..dir_offset + 36];
            let mut entry_reader = ByteReader::new(entry);
            let _first = entry_reader.u64("first").expect("first");
            let rows = entry_reader.u32("rows").expect("rows");
            assert_eq!(rows as usize, count);
            let _state = entry_reader.u64("state").expect("state");
            let _values = entry_reader.u64("values").expect("values");
            let values_length = entry_reader.u64("length").expect("length");
            assert_eq!(values_length as usize, count * dw);
            assert!(data_base > 0);
        }

        // N at the block boundary keeps single-block document-N access.
        for count in [3usize, 4, 5, 8] {
            let mut docs = Vec::new();
            for index in 0..count {
                let mut document = doc(&format!("k{index}"));
                put(
                    &mut document,
                    "city",
                    if index % 2 == 0 {
                        single("even")
                    } else {
                        single("odd")
                    },
                );
                docs.push(document);
            }
            let encoded = encode_v2(&schema, &docs, 4);
            let reader = ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default())
                .expect("parse");
            let field = schema.field_id("city").expect("city");
            let handle = reader
                .bind_keyword_ordinals(field)
                .expect("bind")
                .expect("ordinal");
            let before = handle.blocks_read();
            let last = handle.doc_ordinal(count as u64 - 1).expect("row");
            assert_eq!(handle.blocks_read(), before + 1);
            assert!(matches!(last, KeywordOrdinalValue::Value { .. }));
        }
    }

    // B1-U07 — the new encoder rejects illegal source shapes before publication.
    #[test]
    fn b1_u07_illegal_source_shapes_are_typed() {
        let schema = codec(vec![keyword_single("city")]);
        let limits = SegmentLimits::default();
        let cases: Vec<(FieldValues, &'static str)> = vec![
            (FieldValues::Multi(Vec::new()), "zero multi count"),
            (
                FieldValues::Multi(vec![
                    FieldValue::Keyword("a".to_owned()),
                    FieldValue::Keyword("b".to_owned()),
                ]),
                "multiple values in single keyword column",
            ),
            (FieldValues::Empty, "empty multi in single keyword column"),
        ];
        for (values, detail) in cases {
            let mut document = doc("k");
            put(&mut document, "city", values);
            let error = encode_columns_with_ordinals(
                &schema,
                ColumnDocuments::Documents(&[document]),
                4,
                &limits,
            )
            .expect_err("rejected");
            assert!(
                matches!(
                    error,
                    SegmentError::InvalidColumnGeometry { detail: actual } if actual == detail
                ),
                "expected {detail}, got {error:?}"
            );
        }

        let mut wrong_type = doc("k");
        put(
            &mut wrong_type,
            "city",
            FieldValues::Single(FieldValue::I64(7)),
        );
        assert!(matches!(
            encode_columns_with_ordinals(
                &schema,
                ColumnDocuments::Documents(&[wrong_type]),
                4,
                &limits
            ),
            Err(SegmentError::FieldTypeMismatch { .. })
        ));

        let long = "x".repeat(65_536);
        let mut overlong = doc("k");
        put(&mut overlong, "city", single(&long));
        assert!(matches!(
            encode_columns_with_ordinals(
                &schema,
                ColumnDocuments::Documents(&[overlong]),
                4,
                &limits
            ),
            Err(SegmentError::LengthMismatch {
                context: "u16 length prefix",
                expected: 65_535,
                actual: 65_536
            })
        ));

        assert!(matches!(
            encode_columns_with_ordinals(&schema, ColumnDocuments::Documents(&[]), 0, &limits),
            Err(SegmentError::InvalidColumnGeometry {
                detail: "zero block_docs"
            })
        ));
    }

    // B1-U08 — every ordinary accessor is logically equivalent for v2.
    #[test]
    fn b1_u08_ordinary_accessors_match_input() {
        let schema = codec(vec![
            keyword_single("city"),
            keyword_multi("tags"),
            i64_field("n"),
        ]);
        let rows = vec![
            ("absent", FieldValues::Absent, FieldValues::Absent, None),
            (
                "null",
                FieldValues::ExplicitNull,
                FieldValues::ExplicitNull,
                None,
            ),
            ("empty", single(""), FieldValues::Empty, Some(0)),
            (
                "one",
                single("Austin"),
                FieldValues::Multi(vec![
                    FieldValue::Keyword("one".to_owned()),
                    FieldValue::Keyword("two".to_owned()),
                ]),
                Some(5),
            ),
            (
                "multi",
                multi_one("Austin"),
                FieldValues::Multi(vec![FieldValue::Keyword("solo".to_owned())]),
                Some(-2),
            ),
        ];
        let mut docs = Vec::new();
        for (key, city, tags, n) in rows {
            let mut document = doc(key);
            put(&mut document, "city", city);
            put(&mut document, "tags", tags);
            match n {
                Some(value) => put(
                    &mut document,
                    "n",
                    FieldValues::Single(FieldValue::I64(value)),
                ),
                None => put(&mut document, "n", FieldValues::Absent),
            }
            docs.push(document);
        }
        let encoded = encode_v2(&schema, &docs, 2);
        let reader =
            ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default()).expect("parse");
        let legacy = encode_columns(&schema, &docs, 2, &SegmentLimits::default()).expect("v1");
        let legacy_reader =
            ColumnReader::open(&schema, &legacy, &SegmentLimits::default()).expect("parse");
        for field in schema.fields() {
            for doc_id in 0..docs.len() as u64 {
                assert_eq!(
                    reader.value(field.id, doc_id).expect("v2 value"),
                    legacy_reader.value(field.id, doc_id).expect("v1 value"),
                    "field {} doc {doc_id}",
                    field.name
                );
                assert_eq!(
                    reader.encoded_value_shape(field.id, doc_id).expect("shape"),
                    legacy_reader
                        .encoded_value_shape(field.id, doc_id)
                        .expect("shape"),
                    "shape field {} doc {doc_id}",
                    field.name
                );
            }
        }
        let city = schema.field_id("city").expect("city");
        assert!(matches!(
            reader.keyword_sort_view(city, 2).expect("view"),
            ColumnKeywordView::Value("")
        ));
        assert!(matches!(
            reader.keyword_sort_view(city, 3).expect("view"),
            ColumnKeywordView::Value("Austin")
        ));
        // Single-element multi keeps the legacy decode path (no widened sort).
        assert!(matches!(
            reader.keyword_sort_view(city, 4).expect("view"),
            ColumnKeywordView::LegacyDecode
        ));
        assert!(matches!(
            reader.keyword_sort_view(city, 0).expect("view"),
            ColumnKeywordView::Missing
        ));
        assert!(matches!(
            reader.keyword_sort_view(city, 1).expect("view"),
            ColumnKeywordView::Null
        ));
    }

    // B1-U13 — Single versus allowed MultiOne shapes and their logical budgets.
    #[test]
    fn b1_u13_single_and_multi_one_shapes_and_budgets() {
        let schema = codec(vec![keyword_single("city")]);
        let value = "k".repeat(80);
        let mut docs = Vec::new();
        for (index, values) in [single(&value), multi_one(&value)].into_iter().enumerate() {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", values);
            docs.push(document);
        }
        let encoded = encode_v2(&schema, &docs, 16);
        let field = schema.field_id("city").expect("city");
        let default = SegmentLimits::default();
        let geometry = ColumnReader::open(&schema, &encoded.bytes, &default)
            .expect("parse")
            .into_geometry();
        let reader =
            ColumnReader::from_validated_geometry(&schema, &encoded.bytes, &default, &geometry);
        let handle = reader
            .bind_keyword_ordinals(field)
            .expect("bind")
            .expect("ordinal");
        assert_eq!(
            handle.doc_ordinal(0).expect("row"),
            KeywordOrdinalValue::Value {
                ordinal: 0,
                state: KeywordOrdinalState::Single
            }
        );
        assert_eq!(
            handle.doc_ordinal(1).expect("row"),
            KeywordOrdinalValue::Value {
                ordinal: 0,
                state: KeywordOrdinalState::MultiOne
            }
        );
        assert_eq!(
            reader.encoded_value_shape(field, 0).expect("shape"),
            Some((STATE_SINGLE, 82, 1))
        );
        assert_eq!(
            reader.encoded_value_shape(field, 1).expect("shape"),
            Some((STATE_MULTI, 83, 1))
        );
        assert!(matches!(
            reader.value(field, 0).expect("single"),
            Some(FieldValues::Single(_))
        ));
        assert!(matches!(
            reader.value(field, 1).expect("multi"),
            Some(FieldValues::Multi(list)) if list.len() == 1
        ));

        // Exact legacy logical budgets: section budget 80 succeeds for both.
        let exact = SegmentLimits::default().with_max_section_decode_bytes(80);
        let tight =
            ColumnReader::from_validated_geometry(&schema, &encoded.bytes, &exact, &geometry);
        tight.value(field, 1).expect("exactly 80 decoded bytes");
        // 79 fails with requested 80.
        let under = SegmentLimits::default().with_max_section_decode_bytes(79);
        let rejected =
            ColumnReader::from_validated_geometry(&schema, &encoded.bytes, &under, &geometry);
        assert!(matches!(
            rejected.value(field, 1),
            Err(SegmentError::LimitExceeded {
                limit: 79,
                requested: 80
            })
        ));
        // A one-element FieldValue vector one byte below fails before decoding.
        let vector_bytes = std::mem::size_of::<FieldValue>() as u64;
        let vector_tight = SegmentLimits::default().with_max_single_allocation(vector_bytes - 1);
        let vector_reader = ColumnReader::from_validated_geometry(
            &schema,
            &encoded.bytes,
            &vector_tight,
            &geometry,
        );
        assert!(matches!(
            vector_reader.value(field, 1),
            Err(SegmentError::LimitExceeded {
                limit: actual, requested
            }) if actual == vector_bytes - 1 && requested == vector_bytes
        ));
    }

    // B1-U04/U15 — the independent size formula and tiny-overhead ceiling.
    #[test]
    fn b1_u15_size_formula_witnesses() {
        let schema = codec(vec![keyword_single("city")]);
        let limits = SegmentLimits::default();
        let cases: Vec<(Vec<FieldValues>, usize)> = vec![
            (Vec::new(), 17),
            (vec![single("")], 1),
            (vec![single(&"y".repeat(65_535))], 3),
            (vec![FieldValues::Absent], 2),
        ];
        for (values, extra) in cases {
            let mut docs = Vec::new();
            for (index, values) in values.into_iter().enumerate() {
                let mut document = doc(&format!("k{index}"));
                put(&mut document, "city", values);
                docs.push(document);
            }
            let v1 = encode_columns(&schema, &docs, 1024, &limits).expect("v1");
            let v2 = encode_v2(&schema, &docs, 1024);
            assert_eq!(v2.bytes.len(), v1.len() + extra);
        }

        // Repeated high-cardinality input never exceeds the +17 ceiling.
        let mut docs = Vec::new();
        for index in 0..64usize {
            let mut document = doc(&format!("k{index}"));
            put(
                &mut document,
                "city",
                single(&format!("value-{}", index % 7)),
            );
            docs.push(document);
        }
        let v1 = encode_columns(&schema, &docs, 1024, &limits).expect("v1");
        let v2 = encode_v2(&schema, &docs, 1024);
        assert!(v2.bytes.len() <= v1.len() + 17);
    }

    fn ordinal_fixture() -> (CodecSchema, Vec<u8>, ColumnMeta, DictionaryGeometry) {
        let schema = codec(vec![keyword_single("city")]);
        let mut docs = Vec::new();
        for (index, values) in [
            FieldValues::Absent,
            FieldValues::ExplicitNull,
            single("a"),
            single("b"),
            single(""),
        ]
        .into_iter()
        .enumerate()
        {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", values);
            docs.push(document);
        }
        let encoded = encode_v2(&schema, &docs, 2);
        let reader = ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default())
            .expect("parse")
            .into_geometry();
        let meta = *reader.columns.first().expect("column");
        let dictionary =
            dictionary_geometry(&encoded.bytes, meta.data_base).expect("dictionary geometry");
        (schema, encoded.bytes, meta, dictionary)
    }

    fn expect_geometry(body: &[u8], schema: &CodecSchema, detail: &'static str) {
        match ColumnReader::open(schema, body, &SegmentLimits::default()) {
            Err(SegmentError::InvalidColumnGeometry { detail: actual }) => {
                assert_eq!(actual, detail)
            }
            other => panic!("expected {detail}, got {other:?}"),
        }
    }

    // B1-U05 — dictionary header/offset/term corruption fails at open.
    #[test]
    fn b1_u05_dictionary_corruption_is_rejected_at_open() {
        let (schema, body, meta, dictionary) = ordinal_fixture();
        let base = meta.data_base;

        // Truncated 16-byte prefix keeps the existing `Truncated` class.
        assert!(matches!(
            ColumnReader::open(&schema, &body[..base + 8], &SegmentLimits::default()),
            Err(SegmentError::Truncated {
                context: "keyword dictionary byte length",
                ..
            })
        ));

        // U exceeds the document count.
        let mut corrupt = body.clone();
        write_packed_at(&mut corrupt, base, 8, 99).expect("write");
        expect_geometry(
            &corrupt,
            &schema,
            "keyword dictionary count exceeds document count",
        );

        // First offset must be zero.
        let mut corrupt = body.clone();
        write_packed_at(
            &mut corrupt,
            dictionary.offsets_base,
            dictionary.offset_width,
            1,
        )
        .expect("write");
        expect_geometry(
            &corrupt,
            &schema,
            "keyword dictionary offsets must start at zero",
        );

        // Descending offsets: the terminal offset moves below its predecessor.
        let mut corrupt = body.clone();
        write_packed_at(
            &mut corrupt,
            dictionary.offsets_base + dictionary.terms as usize * dictionary.offset_width as usize,
            dictionary.offset_width,
            0,
        )
        .expect("write");
        expect_geometry(&corrupt, &schema, "keyword dictionary offsets descend");

        // An offset beyond the payload.
        let mut corrupt = body.clone();
        write_packed_at(
            &mut corrupt,
            dictionary.offsets_base + dictionary.offset_width as usize,
            dictionary.offset_width,
            dictionary.payload_len + 1,
        )
        .expect("write");
        expect_geometry(
            &corrupt,
            &schema,
            "keyword dictionary offset exceeds payload",
        );

        // Terminal offset mismatch on a single-term dictionary (no ordering
        // violation can mask it).
        {
            let one = codec(vec![keyword_single("city")]);
            let mut document = doc("k0");
            put(&mut document, "city", single("ab"));
            let encoded = encode_v2(&one, &[document], 16);
            let geometry = ColumnReader::open(&one, &encoded.bytes, &SegmentLimits::default())
                .expect("parse")
                .into_geometry();
            let meta = *geometry.columns.first().expect("column");
            let dictionary = dictionary_geometry(&encoded.bytes, meta.data_base).expect("geometry");
            assert_eq!(dictionary.terms, 1);
            let mut corrupt = encoded.bytes.clone();
            write_packed_at(
                &mut corrupt,
                dictionary.offsets_base + dictionary.offset_width as usize,
                dictionary.offset_width,
                dictionary.payload_len - 1,
            )
            .expect("write");
            expect_geometry(
                &corrupt,
                &one,
                "keyword dictionary terminal offset mismatch",
            );
        }

        // Invalid UTF-8 in a dictionary term (including unreferenced corruption
        // of an unselected row is covered by eager dict validation).
        let mut corrupt = body.clone();
        corrupt[dictionary.strings_base] = 0xFF;
        assert!(matches!(
            ColumnReader::open(&schema, &corrupt, &SegmentLimits::default()),
            Err(SegmentError::InvalidUtf8 { context: "keyword" })
        ));

        // Not-strictly-ascending terms: force two adjacent terms to be equal.
        let mut corrupt = body.clone();
        let first_len = {
            let start = read_packed_at(&corrupt, dictionary.offsets_base, dictionary.offset_width)
                .expect("start");
            let end = read_packed_at(
                &corrupt,
                dictionary.offsets_base + dictionary.offset_width as usize,
                dictionary.offset_width,
            )
            .expect("end");
            (end - start) as usize
        };
        let second_start = dictionary.strings_base + first_len;
        let second_len = {
            let start = read_packed_at(
                &corrupt,
                dictionary.offsets_base + dictionary.offset_width as usize,
                dictionary.offset_width,
            )
            .expect("start");
            let end = read_packed_at(
                &corrupt,
                dictionary.offsets_base + 2 * dictionary.offset_width as usize,
                dictionary.offset_width,
            )
            .expect("end");
            (end - start) as usize
        };
        if second_len == 1 {
            // Duplicate the following one-byte term: strict byte order rejects it.
            corrupt[second_start] = corrupt[second_start + 1];
            expect_geometry(
                &corrupt,
                &schema,
                "keyword dictionary terms are not strictly ascending",
            );
        }

        // U=0 with a nonzero payload.
        let (zero_schema, zero_body, zero_meta, _) = {
            let schema = codec(vec![keyword_single("city")]);
            let mut document = doc("k");
            put(&mut document, "city", FieldValues::Absent);
            let encoded = encode_v2(&schema, &[document], 2);
            let reader = ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default())
                .expect("parse")
                .into_geometry();
            let meta = *reader.columns.first().expect("column");
            (schema, encoded.bytes, meta, ())
        };
        let mut corrupt = zero_body;
        write_packed_at(&mut corrupt, zero_meta.data_base + 8, 8, 1).expect("write");
        expect_geometry(
            &corrupt,
            &zero_schema,
            "empty keyword dictionary has payload",
        );
    }

    // B1-U05 — a term longer than the 16-bit wire ceiling is rejected.
    #[test]
    fn b1_u05_overlong_dictionary_term_is_rejected() {
        let schema = codec(vec![keyword_single("city")]);
        let chunk = "x".repeat(700);
        let mut docs = Vec::new();
        for index in 0..100usize {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", single(&format!("{chunk}{index:03}")));
            docs.push(document);
        }
        let encoded = encode_v2(&schema, &docs, 1024);
        let reader = ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default())
            .expect("parse")
            .into_geometry();
        let meta = *reader.columns.first().expect("column");
        let dictionary = dictionary_geometry(&encoded.bytes, meta.data_base).expect("geometry");
        let mut corrupt = encoded.bytes.clone();
        let width = dictionary.offset_width as usize;
        let offsets_base = dictionary.offsets_base;
        // Make the first term span the entire payload.
        write_packed_at(
            &mut corrupt,
            offsets_base + width,
            width as u8,
            dictionary.payload_len,
        )
        .expect("write");
        for index in 2..=dictionary.terms as usize {
            write_packed_at(
                &mut corrupt,
                offsets_base + index * width,
                width as u8,
                dictionary.payload_len,
            )
            .expect("write");
        }
        assert!(matches!(
            ColumnReader::open(&schema, &corrupt, &SegmentLimits::default()),
            Err(SegmentError::LengthMismatch {
                context: "u16 length prefix",
                expected: 65_535,
                ..
            })
        ));
    }

    // F1-03 / B1-U05 — a hostile dictionary count cannot overflow: it is
    // rejected by the frozen count check first, with a typed error.
    #[test]
    fn b1_u05_hostile_dictionary_count_is_typed_not_a_panic() {
        let (_schema, body, meta, _dictionary) = ordinal_fixture();
        // The frozen 116-byte witness is used independently as well.
        let schema = codec(vec![keyword_single("city")]);
        let mut docs = Vec::new();
        for (index, values) in [
            FieldValues::Absent,
            FieldValues::ExplicitNull,
            single("b"),
            single(""),
        ]
        .into_iter()
        .enumerate()
        {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", values);
            docs.push(document);
        }
        let witness = encode_v2(&schema, &docs, 4);
        assert_eq!(witness.bytes.len(), 116);
        let mut hostile = witness.bytes.clone();
        hostile[88..96].copy_from_slice(&u64::MAX.to_le_bytes());
        expect_geometry(
            &hostile,
            &schema,
            "keyword dictionary count exceeds document count",
        );
        // Extreme but representable counts also stay typed.
        for count in [u64::MAX - 1, u64::MAX / 2, 5] {
            let mut hostile = witness.bytes.clone();
            hostile[88..96].copy_from_slice(&count.to_le_bytes());
            expect_geometry(
                &hostile,
                &schema,
                "keyword dictionary count exceeds document count",
            );
        }
        let _ = meta;
        let _ = body;
    }

    // F1-03 — the pure geometry helper is checked for every extreme `(U, L)`.
    #[test]
    fn b1_u05_geometry_helper_is_checked() {
        let base = 64usize;
        assert!(matches!(
            dictionary_geometry_from(
                DictionaryPrefix {
                    terms: u64::MAX,
                    payload_len: 0
                },
                base
            ),
            Err(SegmentError::InvalidColumnGeometry {
                detail: "keyword dictionary extent overflow"
            })
        ));
        assert!(matches!(
            dictionary_geometry_from(
                DictionaryPrefix {
                    terms: u64::MAX - 1,
                    payload_len: u64::MAX
                },
                base
            ),
            Err(SegmentError::InvalidColumnGeometry { .. })
        ));
        // A huge payload is representable but not addressable on this platform.
        assert!(matches!(
            dictionary_geometry_from(
                DictionaryPrefix {
                    terms: 0,
                    payload_len: u64::MAX
                },
                base
            ),
            Err(SegmentError::InvalidColumnGeometry { .. })
        ));
        let geometry = dictionary_geometry_from(
            DictionaryPrefix {
                terms: 3,
                payload_len: 2,
            },
            base,
        )
        .expect("small geometry");
        assert_eq!(geometry.terms, 3);
        assert_eq!(geometry.offsets_base, base + 16);
        assert_eq!(geometry.strings_base, base + 16 + 4);
        assert_eq!(geometry.strings_end, base + 16 + 4 + 2);
        assert_eq!(geometry.dictionary_end, (base + 16 + 4 + 2) as u64);
    }

    // F1-09 — one ordered validation pass: an early invalid term wins over a
    // later malformed offset.
    #[test]
    fn b1_u05_early_term_error_precedes_later_offset_error() {
        let (schema, body, _meta, dictionary) = ordinal_fixture();
        // dictionary is ["", "a", "b"] with L=2 and 1-byte offsets [0,0,1,2].
        let mut corrupt = body.clone();
        // Make the first non-empty term invalid UTF-8 (delimits 0..1).
        corrupt[dictionary.strings_base] = 0x80;
        // Also make a later offset descend; the earlier term error must win.
        write_packed_at(
            &mut corrupt,
            dictionary.offsets_base + 3 * dictionary.offset_width as usize,
            dictionary.offset_width,
            0,
        )
        .expect("write");
        assert!(matches!(
            ColumnReader::open(&schema, &corrupt, &SegmentLimits::default()),
            Err(SegmentError::InvalidUtf8 { context: "keyword" })
        ));

        // With the UTF-8 corruption removed, the offset error is reached.
        let mut corrupt = body.clone();
        write_packed_at(
            &mut corrupt,
            dictionary.offsets_base + 3 * dictionary.offset_width as usize,
            dictionary.offset_width,
            0,
        )
        .expect("write");
        expect_geometry(&corrupt, &schema, "keyword dictionary offsets descend");
    }

    // B1-U06 — row-state, ordinal and extent corruption fails at open.
    #[test]
    fn b1_u06_row_state_and_extent_corruption_is_rejected() {
        let (schema, body, meta, dictionary) = ordinal_fixture();

        let block_entry = |body: &[u8], block: usize| {
            let at = meta.dir_offset + block * BLOCK_ENTRY_LEN;
            let mut reader = ByteReader::new(&body[at..at + BLOCK_ENTRY_LEN]);
            (
                reader.u64("first").expect("first"),
                reader.u32("rows").expect("rows"),
                reader.u64("state").expect("state"),
                reader.u64("values").expect("values"),
                reader.u64("length").expect("length"),
            )
        };

        // Invalid state tag in the single-valued ordinal layout (0x02).
        let mut corrupt = body.clone();
        let (_, _, state_offset, _, _) = block_entry(&corrupt, 0);
        corrupt[meta.data_base + state_offset as usize] = STATE_EMPTY_MULTI;
        expect_geometry(&corrupt, &schema, "invalid keyword ordinal state");

        // A missing row must carry a zero slot.
        let mut corrupt = body.clone();
        let (_, _, _, values_offset, _) = block_entry(&corrupt, 0);
        corrupt[meta.data_base + values_offset as usize] = 1;
        expect_geometry(&corrupt, &schema, "stateless keyword ordinal is not zero");

        // An ordinal at the dictionary count is out of range.
        let mut corrupt = body.clone();
        let (_, _, _, values_offset, _) = block_entry(&corrupt, 1);
        write_packed_at(
            &mut corrupt,
            meta.data_base + values_offset as usize,
            dictionary.ordinal_width,
            9,
        )
        .expect("write");
        expect_geometry(&corrupt, &schema, "keyword ordinal out of range");

        // Wrong slots length for the row count.
        let mut corrupt = body.clone();
        let entry_at = meta.dir_offset + BLOCK_ENTRY_LEN + 32;
        let mut encoded_length = corrupt[entry_at..entry_at + 8].to_vec();
        encoded_length[0] = encoded_length[0].wrapping_add(1);
        corrupt[entry_at..entry_at + 8].copy_from_slice(&encoded_length);
        expect_geometry(&corrupt, &schema, "keyword ordinal slots length mismatch");

        // A gap between the dictionary and the first block.
        let mut corrupt = body.clone();
        let entry_at = meta.dir_offset + 20;
        let mut encoded_offset = corrupt[entry_at..entry_at + 8].to_vec();
        encoded_offset[0] = encoded_offset[0].wrapping_add(1);
        corrupt[entry_at..entry_at + 8].copy_from_slice(&encoded_offset);
        expect_geometry(&corrupt, &schema, "noncanonical v2 column extent");

        // Trailing bytes after the last column.
        let mut corrupt = body.clone();
        corrupt.push(0);
        expect_geometry(&corrupt, &schema, "trailing v2 columns bytes");

        // A public out-of-range dictionary lookup is typed and bounded.
        let reader = ColumnReader::open(&schema, &body, &SegmentLimits::default()).expect("parse");
        let handle = reader
            .bind_keyword_ordinals(schema.field_id("city").expect("city"))
            .expect("bind")
            .expect("ordinal");
        assert!(matches!(
            handle.dictionary_term(handle.dictionary_len()),
            Err(SegmentError::InvalidColumnGeometry {
                detail: "keyword dictionary ordinal out of range"
            })
        ));
        assert!(matches!(
            handle.doc_ordinal(5),
            Err(SegmentError::Corrupt {
                context: "column",
                ..
            })
        ));
    }

    // B1-U06/U02 — container-level feature/version agreement is enforced by the
    // containing reader, not by the standalone parser.
    #[test]
    fn b1_u02_standalone_parser_accepts_both_known_versions() {
        let schema = codec(vec![keyword_single("city")]);
        let mut document = doc("k");
        put(&mut document, "city", single("a"));
        let v2 = encode_v2(&schema, &[document.clone()], 4);
        assert!(ColumnReader::open(&schema, &v2.bytes, &SegmentLimits::default()).is_ok());
        let v1 = encode_columns(&schema, &[document], 4, &SegmentLimits::default()).expect("v1");
        assert!(ColumnReader::open(&schema, &v1, &SegmentLimits::default()).is_ok());
        // A v2 body without any eligible ordinal column is not a valid upgrade.
        let keyword_multi_only = codec(vec![keyword_multi("tags")]);
        let mut document = doc("k");
        put(
            &mut document,
            "tags",
            FieldValues::Multi(vec![FieldValue::Keyword("s".into())]),
        );
        let v1_body = encode_columns(
            &keyword_multi_only,
            &[document],
            4,
            &SegmentLimits::default(),
        )
        .expect("v1");
        let mut as_v2 = v1_body.clone();
        as_v2[0] = 2;
        expect_geometry(
            &as_v2,
            &keyword_multi_only,
            "v2 columns require keyword ordinals",
        );
    }

    // F1-02 / B1-U09 — every retained ordinary backing obeys the single
    // allocation ceiling even when the finished body would fit.
    #[test]
    fn b1_u09_ordinary_retained_backings_are_checked_individually() {
        // A deterministic outer-vector over-capacity, independent of allocator
        // growth policy: the reported capacity is the one requested here.
        let mut blocks: Vec<BlockPlan> = Vec::new();
        blocks.try_reserve_exact(1_000).expect("reserve");
        blocks.push(BlockPlan {
            state: vec![0u8],
            values: vec![0u8],
        });
        let outer_bytes = 1_000 * std::mem::size_of::<BlockPlan>() as u64;
        let limits = SegmentLimits::default().with_max_single_allocation(outer_bytes - 1);
        assert!(matches!(
            check_ordinary_retained(&blocks, blocks.capacity(), &limits),
            Err(SegmentError::LimitExceeded { limit, requested })
                if limit == outer_bytes - 1 && requested == outer_bytes
        ));
        let exact = SegmentLimits::default().with_max_single_allocation(outer_bytes);
        assert!(check_ordinary_retained(&blocks, blocks.capacity(), &exact).is_ok());

        // A single retained state buffer above the ceiling is also rejected.
        let mut over_state: Vec<BlockPlan> = Vec::new();
        over_state.try_reserve_exact(1).expect("reserve one");
        let mut state: Vec<u8> = Vec::new();
        state.try_reserve_exact(6_000).expect("reserve state");
        state.push(0);
        over_state.push(BlockPlan {
            state,
            values: Vec::new(),
        });
        let tight = SegmentLimits::default().with_max_single_allocation(5_500);
        assert!(matches!(
            check_ordinary_retained(&over_state, over_state.capacity(), &tight),
            Err(SegmentError::LimitExceeded { limit, requested })
                if limit == 5_500 && requested >= 6_000
        ));

        // The real encoder reaches the same checks: 65 all-missing mixed rows
        // with one block per row fail under a one-byte ceiling.
        let schema = codec(vec![
            keyword_single("city"),
            FieldDefinition::new(
                "flag",
                FieldType::Bool,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ]);
        let mut docs = Vec::new();
        for index in 0..65usize {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", FieldValues::Absent);
            put(&mut document, "flag", FieldValues::Absent);
            docs.push(document);
        }
        let tiny = SegmentLimits::default().with_max_single_allocation(1);
        assert!(matches!(
            encode_columns_with_ordinals(&schema, ColumnDocuments::Documents(&docs), 1, &tiny),
            Err(SegmentError::LimitExceeded { limit: 1, .. })
        ));
        // Generous limits still encode the same fixture.
        let generous = encode_columns_with_ordinals(
            &schema,
            ColumnDocuments::Documents(&docs),
            1,
            &SegmentLimits::default(),
        )
        .expect("generous encode");
        // The exact boundary of this fixture is found through the real encoder
        // (deterministic for a fixed allocator), then one byte under must fail.
        let mut boundary = None;
        // Success is monotone in the single-allocation ceiling, so an ascending
        // scan finds the exact minimum for this deterministic fixture.
        for candidate in 2..=64u64 * 1024 {
            let limits = SegmentLimits::default().with_max_single_allocation(candidate);
            if encode_columns_with_ordinals(&schema, ColumnDocuments::Documents(&docs), 1, &limits)
                .is_ok()
            {
                boundary = Some(candidate);
                break;
            }
        }
        let boundary = boundary.expect("some allocation cap must succeed");
        let at = SegmentLimits::default().with_max_single_allocation(boundary);
        let encoded =
            encode_columns_with_ordinals(&schema, ColumnDocuments::Documents(&docs), 1, &at)
                .expect("exact cap");
        let under = SegmentLimits::default().with_max_single_allocation(boundary - 1);
        match encode_columns_with_ordinals(&schema, ColumnDocuments::Documents(&docs), 1, &under) {
            Err(SegmentError::LimitExceeded { limit, .. }) => {
                assert_eq!(limit, boundary - 1, "boundary {boundary}");
            }
            Ok(_) => panic!("boundary {boundary}: encoding must fail one byte under"),
            Err(error) => panic!("boundary {boundary}: unexpected {error:?}"),
        }
        // The two encodings agree byte-for-byte.
        assert_eq!(encoded.bytes, generous.bytes);
    }

    // F1-10 / B1-U13 — the ordinal branch's owned keyword copy is fallible and
    // the frozen logical budgets are unchanged.
    #[test]
    fn b1_u13_ordinal_branch_budgets_and_fallback_copy() {
        let schema = codec(vec![keyword_single("city")]);
        let value = "k".repeat(80);
        let mut docs = Vec::new();
        for (index, values) in [single(&value), multi_one(&value)].into_iter().enumerate() {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", values);
            docs.push(document);
        }
        let encoded = encode_v2(&schema, &docs, 16);
        let field = schema.field_id("city").expect("city");
        let default = SegmentLimits::default();
        let geometry = ColumnReader::open(&schema, &encoded.bytes, &default)
            .expect("parse")
            .into_geometry();

        // The fallible helper copies a validated payload exactly.
        let copied = fallible_owned_keyword(&value, &default).expect("copy");
        assert_eq!(copied, value);
        // The *logical admission* (not the helper) enforces the single-allocation
        // ceiling, and reports it in bytes before the copy is attempted.
        let tight = SegmentLimits::default().with_max_single_allocation(79);
        let tight_reader =
            ColumnReader::from_validated_geometry(&schema, &encoded.bytes, &tight, &geometry);
        assert!(matches!(
            tight_reader.value(field, 0),
            Err(SegmentError::LimitExceeded {
                limit: 79,
                requested: 80
            })
        ));

        // MultiOne keeps the frozen ordering: one-element vector check first,
        // then the string's own logical budget.
        let exact = SegmentLimits::default().with_max_section_decode_bytes(80);
        let reader =
            ColumnReader::from_validated_geometry(&schema, &encoded.bytes, &exact, &geometry);
        assert!(matches!(
            reader.value(field, 1).expect("multi one"),
            Some(FieldValues::Multi(ref list)) if list.len() == 1
        ));
        let under = SegmentLimits::default().with_max_section_decode_bytes(79);
        let reader =
            ColumnReader::from_validated_geometry(&schema, &encoded.bytes, &under, &geometry);
        assert!(matches!(
            reader.value(field, 1),
            Err(SegmentError::LimitExceeded {
                limit: 79,
                requested: 80
            })
        ));
        let vector_bytes = std::mem::size_of::<FieldValue>() as u64;
        let vector_tight = SegmentLimits::default().with_max_single_allocation(vector_bytes - 1);
        let reader = ColumnReader::from_validated_geometry(
            &schema,
            &encoded.bytes,
            &vector_tight,
            &geometry,
        );
        assert!(matches!(
            reader.value(field, 1),
            Err(SegmentError::LimitExceeded { limit, requested })
                if limit == vector_bytes - 1 && requested == vector_bytes
        ));
        // Single goes through the same fallible helper and shape.
        let single_reader =
            ColumnReader::from_validated_geometry(&schema, &encoded.bytes, &default, &geometry);
        assert!(matches!(
            single_reader.value(field, 0).expect("single"),
            Some(FieldValues::Single(FieldValue::Keyword(ref text))) if text.len() == 80
        ));
    }

    // F1-06 / B1-U10 — the frozen 64-case codec differential (input-only oracle).
    #[test]
    fn b1_u10_frozen_codec_differential_families() {
        const ALPHABET: [&str; 10] = [
            "", "\0", "a", "aa", "A", "Austin", "Seattle", "e\u{301}", "é", "😀",
        ];
        for case in 0..64u64 {
            let segment_count = 1 + (case % 5) as usize;
            let mut docs: Vec<SegmentDocument> = Vec::new();
            // The expected row is captured from the *input* values being encoded.
            struct ExpectedRow {
                key: String,
                values: FieldValues,
                term: Option<&'static str>,
                state: Option<KeywordOrdinalState>,
            }
            let mut expected: Vec<ExpectedRow> = Vec::new();
            // One column spans all documents, so this is one dictionary.
            let mut all_terms: Vec<&'static str> = Vec::new();
            for source in 0..segment_count as u64 {
                let row_count = ((case + 3 * source) % 13) as usize;
                for row in 0..row_count as u64 {
                    let selector = (case + 7 * source + 5 * row) % 13;
                    let key = format!("c{case}s{source}r{row}");
                    let mut document = doc(&key);
                    match selector {
                        0 => {
                            let values = FieldValues::Absent;
                            put(&mut document, "city", values.clone());
                            expected.push(ExpectedRow {
                                key,
                                values,
                                term: None,
                                state: None,
                            });
                        }
                        1 => {
                            let values = FieldValues::ExplicitNull;
                            put(&mut document, "city", values.clone());
                            expected.push(ExpectedRow {
                                key,
                                values,
                                term: None,
                                state: None,
                            });
                        }
                        2 => {
                            let term = ALPHABET[((case + row) % 10) as usize];
                            let values = multi_one(term);
                            put(&mut document, "city", values.clone());
                            all_terms.push(term);
                            expected.push(ExpectedRow {
                                key,
                                values,
                                term: Some(term),
                                state: Some(KeywordOrdinalState::MultiOne),
                            });
                        }
                        _ => {
                            let term = ALPHABET[((case + source + row) % 10) as usize];
                            let values = single(term);
                            put(&mut document, "city", values.clone());
                            all_terms.push(term);
                            expected.push(ExpectedRow {
                                key,
                                values,
                                term: Some(term),
                                state: Some(KeywordOrdinalState::Single),
                            });
                        }
                    }
                    docs.push(document);
                }
            }
            let schema = codec(vec![keyword_single("city")]);
            let encoded = encode_v2(&schema, &docs, 3);
            let reader = ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default())
                .expect("parse");
            let field = schema.field_id("city").expect("city");
            let handle = reader
                .bind_keyword_ordinals(field)
                .expect("bind")
                .expect("ordinal column");
            // The column dictionary is the sorted distinct input terms.
            let mut expected_terms: Vec<Vec<u8>> = all_terms
                .iter()
                .map(|term| term.as_bytes().to_vec())
                .collect();
            expected_terms.sort();
            expected_terms.dedup();
            assert_eq!(handle.dictionary_len(), expected_terms.len() as u64);
            for (ordinal, term) in expected_terms.iter().enumerate() {
                assert_eq!(
                    handle.dictionary_term(ordinal as u64).expect("term"),
                    term.as_slice(),
                    "case {case}"
                );
            }
            // Every document's complete value, state and local ordinal match the
            // input-derived oracle (including the exact MultiOne member).
            for (doc_id, row) in expected.iter().enumerate() {
                let value = reader
                    .value(field, doc_id as u64)
                    .expect("value")
                    .expect("column");
                assert_eq!(
                    value, row.values,
                    "case {case} {}: complete value mismatch",
                    row.key
                );
                match row.term {
                    Some(term) => {
                        let ordinal = expected_terms
                            .binary_search_by(|candidate| candidate.as_slice().cmp(term.as_bytes()))
                            .expect("term in dictionary")
                            as u64;
                        match handle.doc_ordinal(doc_id as u64).expect("row") {
                            KeywordOrdinalValue::Value {
                                ordinal: actual,
                                state,
                            } => {
                                assert_eq!(actual, ordinal, "case {case} {}", row.key);
                                assert_eq!(state, row.state.expect("state"), "case {case}");
                            }
                            other => panic!("case {case} {}: unexpected {other:?}", row.key),
                        }
                        match (&value, row.state) {
                            (FieldValues::Multi(list), Some(KeywordOrdinalState::MultiOne)) => {
                                // The exact contained member, not just its count.
                                assert_eq!(list.len(), 1);
                                assert_eq!(list[0], FieldValue::Keyword(term.to_owned()));
                                // Negative oracle sanity: a wrong expected member
                                // must not compare equal.
                                let wrong = FieldValues::Multi(vec![FieldValue::Keyword(format!(
                                    "{term}-wrong"
                                ))]);
                                assert_ne!(value, wrong, "case {case} {}", row.key);
                            }
                            (
                                FieldValues::Single(FieldValue::Keyword(text)),
                                Some(KeywordOrdinalState::Single),
                            ) => {
                                assert_eq!(text, term);
                            }
                            _ => panic!("case {case} {}: state/shape mismatch", row.key),
                        }
                    }
                    None => {
                        // Absent and explicit null stay distinct.
                        match &row.values {
                            FieldValues::Absent => {
                                assert_eq!(value, FieldValues::Absent);
                                assert_eq!(
                                    handle.doc_ordinal(doc_id as u64).expect("row"),
                                    KeywordOrdinalValue::Missing,
                                    "case {case} {}",
                                    row.key
                                );
                            }
                            FieldValues::ExplicitNull => {
                                assert_eq!(value, FieldValues::ExplicitNull);
                                assert_eq!(
                                    handle.doc_ordinal(doc_id as u64).expect("row"),
                                    KeywordOrdinalValue::Null,
                                    "case {case} {}",
                                    row.key
                                );
                            }
                            other => panic!("case {case} {}: {other:?}", row.key),
                        }
                    }
                }
            }
        }
    }

    // B1-U11 — the referenced-document adapter emits identical bytes and the
    // same feature flag as the owned-slice adapter.
    #[test]
    fn b1_u11_reference_and_slice_encoders_agree() {
        let schema = codec(vec![keyword_single("city"), i64_field("n")]);
        let mut docs = Vec::new();
        for index in 0..4usize {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", single(&format!("v{index}")));
            put(
                &mut document,
                "n",
                FieldValues::Single(FieldValue::I64(index as i64)),
            );
            docs.push(document);
        }
        let borrowed: Vec<&SegmentDocument> = docs.iter().collect();
        let from_slice = encode_v2(&schema, &docs, 2);
        let from_refs = encode_columns_with_ordinals(
            &schema,
            ColumnDocuments::References(&borrowed),
            2,
            &SegmentLimits::default(),
        )
        .expect("references");
        assert_eq!(from_slice.bytes, from_refs.bytes);
        assert!(from_refs.has_keyword_ordinals);

        // No eligible field keeps byte-identical legacy output and no feature.
        let no_keyword = codec(vec![i64_field("n")]);
        let legacy = encode_columns(&no_keyword, &docs, 2, &SegmentLimits::default()).expect("v1");
        let encoded = encode_columns_with_ordinals(
            &no_keyword,
            ColumnDocuments::Documents(&docs),
            2,
            &SegmentLimits::default(),
        )
        .expect("no eligible");
        assert_eq!(encoded.bytes, legacy);
        assert!(!encoded.has_keyword_ordinals);

        // Zero documents still emits the v2 feature for an eligible field.
        let empty = encode_v2(&schema, &[], 2);
        assert!(empty.has_keyword_ordinals);
    }

    // B1-U16 — bound lookups read one block row and never scan fields per doc.
    #[test]
    fn b1_u16_bound_lookup_is_document_n() {
        let schema = codec(vec![keyword_single("city")]);
        let mut docs = Vec::new();
        for index in 0..10usize {
            let mut document = doc(&format!("k{index}"));
            put(&mut document, "city", single(&format!("v{index}")));
            docs.push(document);
        }
        let encoded = encode_v2(&schema, &docs, 4);
        let reader =
            ColumnReader::open(&schema, &encoded.bytes, &SegmentLimits::default()).expect("parse");
        let field = schema.field_id("city").expect("city");
        assert_eq!(reader.blocks_read(), 0);
        let handle = reader
            .bind_keyword_ordinals(field)
            .expect("bind")
            .expect("ordinal");
        assert_eq!(handle.blocks_read(), 0);
        for doc_id in 0..10u64 {
            handle.doc_ordinal(doc_id).expect("row");
            assert_eq!(handle.blocks_read(), doc_id + 1);
        }
        // Binding a non-ordinal field returns None rather than an error.
        assert!(reader.bind_keyword_ordinals(99).expect("bind").is_none());
    }
}
