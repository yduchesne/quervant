//! Bounded immutable JSON-path section codec and exact per-document extractor
//! (PR 11).
//!
//! A JSON source structure stays recoverable byte-semantically from the
//! existing typed stored-value codec. This module adds a separately versioned,
//! immutable per-segment **path/leaf-value** index that accelerates exact
//! document-level existential predicates while retaining concrete array
//! ancestry. It is not a second JSON source codec and never reconstructs JSON
//! values: stored source remains authoritative.

use std::cmp::Ordering;
use std::rc::Rc;

use crate::contract::document::FieldValues;
use crate::contract::query::JsonPathSegment;
use crate::contract::value::{FieldType, FieldValue, JsonNumber, JsonValue};

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::schema::CodecSchema;

/// Maximum number of concrete path segments (depth) for an indexed node.
pub(crate) const MAX_JSON_PATH_DEPTH: usize = 128;
/// Maximum number of indexed occurrences produced by one physical document.
pub(crate) const MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT: u64 = 65_536;
/// Maximum number of indexed occurrences in one segment section.
pub(crate) const MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT: u64 = 8_000_000;
/// Maximum byte length of one object member name.
pub(crate) const MAX_JSON_PATH_MEMBER_BYTES: usize = 65_535;
/// Maximum encoded JSON-path section body size.
pub(crate) const MAX_JSON_PATH_SECTION_BYTES: u64 = 256 * 1024 * 1024;

/// The error wrapping a JSON-path section/feature presence mismatch.
const JSON_PATHS_CONTEXT: &str = "json paths";

/// One concrete path component. `Member` sorts before `Index`; members sort by
/// UTF-8 bytes and indices numerically, matching the canonical section order.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum JsonPathComponent {
    /// An object member name, byte-exact.
    Member(String),
    /// A nonnegative array index (or the virtual multi-root index).
    Index(u64),
}

/// The kind and scalar payload of one indexed node.
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum JsonNode {
    /// JSON null.
    Null,
    /// JSON boolean.
    Bool(bool),
    /// JSON signed integer.
    I64(i64),
    /// JSON unsigned integer.
    U64(u64),
    /// JSON finite float (signed zero normalized to `+0.0`).
    F64(f64),
    /// JSON string.
    String(String),
    /// JSON array (no payload; existence only).
    Array,
    /// JSON object (no payload; existence only).
    Object,
}

/// One indexed occurrence: physical document id, concrete path and node.
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct JsonOccurrence {
    /// Physical document id.
    pub doc_id: u64,
    /// Concrete path from the root (`$`) to the node.
    pub path: Vec<JsonPathComponent>,
    /// Kind and scalar payload.
    pub node: JsonNode,
}

/// A JSON scalar comparison representation used for exact equality.
///
/// Text and Keyword right-hand sides both compare to a JSON string by exact
/// UTF-8 bytes. Numeric variants stay distinct; F64 signed zero is normalized.
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum JsonScalar {
    /// Boolean scalar.
    Bool(bool),
    /// Signed integer scalar.
    I64(i64),
    /// Unsigned integer scalar.
    U64(u64),
    /// Finite float scalar with normalized signed zero.
    F64(f64),
    /// String bytes (from Text or Keyword).
    String(Vec<u8>),
}

impl JsonScalar {
    /// Map an accepted right-hand-side `FieldValue` to a JSON scalar.
    ///
    /// Returns `None` for variants that are not valid JSON equality operands.
    #[must_use]
    pub(crate) fn from_field_value(value: &FieldValue) -> Option<Self> {
        match value {
            FieldValue::Bool(flag) => Some(Self::Bool(*flag)),
            FieldValue::I64(number) => Some(Self::I64(*number)),
            FieldValue::U64(number) => Some(Self::U64(*number)),
            FieldValue::F64(number) => Some(Self::F64(normalize_zero(*number))),
            FieldValue::Text(text) | FieldValue::Keyword(text) => {
                Some(Self::String(text.as_bytes().to_vec()))
            }
            _ => None,
        }
    }
}

/// Normalize a negative zero to positive zero without touching the sign of any
/// other value.
#[must_use]
pub(crate) fn normalize_zero(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

/// Whether a node's scalar payload equals a JSON scalar. Containers and null
/// never equal a scalar.
#[must_use]
pub(crate) fn node_matches_scalar(node: &JsonNode, scalar: &JsonScalar) -> bool {
    match (node, scalar) {
        (JsonNode::Bool(a), JsonScalar::Bool(b)) => a == b,
        (JsonNode::I64(a), JsonScalar::I64(b)) => a == b,
        (JsonNode::U64(a), JsonScalar::U64(b)) => a == b,
        (JsonNode::F64(a), JsonScalar::F64(b)) => normalize_zero(*a) == normalize_zero(*b),
        (JsonNode::String(a), JsonScalar::String(b)) => a.as_bytes() == b.as_slice(),
        _ => false,
    }
}

/// Whether a concrete occurrence path matches a possibly-wildcard pattern. A
/// wildcard consumes exactly one `Index` segment (one array level); it never
/// matches a member and never spans levels.
#[must_use]
pub(crate) fn path_matches(pattern: &[JsonPathSegment], path: &[JsonPathComponent]) -> bool {
    if pattern.len() != path.len() {
        return false;
    }
    pattern
        .iter()
        .zip(path)
        .all(|(pattern, component)| component_matches(pattern, component))
}

/// Whether a concrete path pattern equals a concrete occurrence path.
#[must_use]
pub(crate) fn path_equals(pattern: &[JsonPathSegment], path: &[JsonPathComponent]) -> bool {
    if pattern.len() != path.len() {
        return false;
    }
    pattern
        .iter()
        .zip(path)
        .all(|(pattern, component)| match (pattern, component) {
            (JsonPathSegment::Member(member), JsonPathComponent::Member(candidate)) => {
                member.as_bytes() == candidate.as_bytes()
            }
            (JsonPathSegment::Index(index), JsonPathComponent::Index(candidate)) => {
                u64::try_from(*index).ok() == Some(*candidate)
            }
            _ => false,
        })
}

fn component_matches(pattern: &JsonPathSegment, component: &JsonPathComponent) -> bool {
    match (pattern, component) {
        (JsonPathSegment::Member(member), JsonPathComponent::Member(candidate)) => {
            member.as_bytes() == candidate.as_bytes()
        }
        (JsonPathSegment::Index(index), JsonPathComponent::Index(candidate)) => {
            u64::try_from(*index).ok() == Some(*candidate)
        }
        (JsonPathSegment::Wildcard, JsonPathComponent::Index(_)) => true,
        _ => false,
    }
}

// ---------------------------------------------------------------------------
// Deterministic bounded extraction
// ---------------------------------------------------------------------------

/// One borrowed child seed on the explicit DFS stack.
enum Seed<'a> {
    Member(&'a str),
    Index(u64),
}

/// One explicit DFS frame: the parent path length, the seed producing the node,
/// and the borrowed value.
struct Frame<'a> {
    parent_len: usize,
    seed: Option<Seed<'a>>,
    value: &'a JsonValue,
}

/// The effective per-node path depth limit.
fn effective_depth(limits: &SegmentLimits) -> usize {
    let configured = usize::try_from(limits.max_json_depth()).unwrap_or(usize::MAX);
    configured.min(MAX_JSON_PATH_DEPTH)
}

/// Extract every node occurrence for one JSON field state.
///
/// `FieldValues::Absent`/`Empty` produce nothing, `ExplicitNull` produces a root
/// `Null`, a single JSON value is rooted at `$`, and each multi-root value is
/// prefixed with its virtual outer array index. Object member names must be
/// unique; a repeated name is a typed limit/validation failure. The returned
/// occurrences are sorted by `(doc_id, concrete_path)`.
pub(crate) fn extract_field_paths(
    doc_id: u64,
    values: &FieldValues,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<JsonOccurrence>> {
    let mut out: Vec<JsonOccurrence> = Vec::new();
    let depth_limit = effective_depth(limits);
    let mut estimated: u64 = 0;
    match values {
        FieldValues::Absent | FieldValues::Empty => return Ok(out),
        FieldValues::ExplicitNull => {
            out.push(JsonOccurrence {
                doc_id,
                path: Vec::new(),
                node: JsonNode::Null,
            });
        }
        FieldValues::Single(value) => {
            if let FieldValue::Json(json) = value {
                extract_value(
                    doc_id,
                    json,
                    Vec::new(),
                    depth_limit,
                    limits,
                    &mut out,
                    &mut estimated,
                )?;
            }
        }
        FieldValues::Multi(values) => {
            for (index, value) in values.iter().enumerate() {
                let FieldValue::Json(json) = value else {
                    continue;
                };
                let index = u64::try_from(index).map_err(|_| SegmentError::LimitExceeded {
                    limit: limits.max_array_elements(),
                    requested: index as u64,
                })?;
                extract_value(
                    doc_id,
                    json,
                    vec![JsonPathComponent::Index(index)],
                    depth_limit,
                    limits,
                    &mut out,
                    &mut estimated,
                )?;
            }
        }
    }
    if !out.is_empty() {
        sort_occurrences(&mut out);
        reject_duplicate_paths(&out)?;
    }
    let count = out.len() as u64;
    if count > MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT {
        return Err(SegmentError::LimitExceeded {
            limit: MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT,
            requested: count,
        });
    }
    Ok(out)
}

#[allow(clippy::too_many_arguments)]
fn extract_value(
    doc_id: u64,
    root: &JsonValue,
    root_prefix: Vec<JsonPathComponent>,
    depth_limit: usize,
    limits: &SegmentLimits,
    out: &mut Vec<JsonOccurrence>,
    estimated: &mut u64,
) -> SegmentResult<()> {
    let mut path = root_prefix;
    let mut stack: Vec<Frame<'_>> = Vec::new();
    stack.push(Frame {
        parent_len: path.len(),
        seed: None,
        value: root,
    });
    while let Some(frame) = stack.pop() {
        path.truncate(frame.parent_len);
        if let Some(seed) = frame.seed {
            match seed {
                Seed::Member(member) => {
                    if member.len() > MAX_JSON_PATH_MEMBER_BYTES {
                        return Err(SegmentError::LimitExceeded {
                            limit: MAX_JSON_PATH_MEMBER_BYTES as u64,
                            requested: member.len() as u64,
                        });
                    }
                    path.push(JsonPathComponent::Member(member.to_owned()));
                }
                Seed::Index(index) => path.push(JsonPathComponent::Index(index)),
            }
        }
        if path.len() > depth_limit {
            return Err(SegmentError::LimitExceeded {
                limit: depth_limit as u64,
                requested: path.len() as u64,
            });
        }
        if out.len() as u64 >= MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT {
            return Err(SegmentError::LimitExceeded {
                limit: MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT,
                requested: out.len() as u64 + 1,
            });
        }
        let node = node_of(frame.value);
        charge_occurrence(estimated, &path, &node, limits)?;
        out.push(JsonOccurrence {
            doc_id,
            path: path.clone(),
            node,
        });
        match frame.value {
            JsonValue::Array(values) => {
                if values.len() as u64 > limits.max_array_elements() {
                    return Err(SegmentError::LimitExceeded {
                        limit: limits.max_array_elements(),
                        requested: values.len() as u64,
                    });
                }
                for (index, child) in values.iter().enumerate() {
                    let index = u64::try_from(index).map_err(|_| SegmentError::LimitExceeded {
                        limit: limits.max_array_elements(),
                        requested: index as u64,
                    })?;
                    stack.push(Frame {
                        parent_len: path.len(),
                        seed: Some(Seed::Index(index)),
                        value: child,
                    });
                }
            }
            JsonValue::Object(entries) => {
                for (key, child) in entries {
                    stack.push(Frame {
                        parent_len: path.len(),
                        seed: Some(Seed::Member(key)),
                        value: child,
                    });
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn node_of(value: &JsonValue) -> JsonNode {
    match value {
        JsonValue::Null => JsonNode::Null,
        JsonValue::Bool(flag) => JsonNode::Bool(*flag),
        JsonValue::Number(JsonNumber::I64(number)) => JsonNode::I64(*number),
        JsonValue::Number(JsonNumber::U64(number)) => JsonNode::U64(*number),
        JsonValue::Number(JsonNumber::F64(number)) => JsonNode::F64(normalize_zero(*number)),
        JsonValue::String(text) => JsonNode::String(text.clone()),
        JsonValue::Array(_) => JsonNode::Array,
        JsonValue::Object(_) => JsonNode::Object,
    }
}

fn charge_occurrence(
    estimated: &mut u64,
    path: &[JsonPathComponent],
    node: &JsonNode,
    limits: &SegmentLimits,
) -> SegmentResult<()> {
    let base = std::mem::size_of::<JsonOccurrence>() as u64;
    let path_bytes = (path.len() as u64)
        .checked_mul(std::mem::size_of::<JsonPathComponent>() as u64)
        .ok_or(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: u64::MAX,
        })?;
    let payload = match node {
        JsonNode::String(text) => text.len() as u64,
        _ => 0,
    };
    let charge = base
        .checked_add(path_bytes)
        .and_then(|value| value.checked_add(payload))
        .ok_or(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: u64::MAX,
        })?;
    *estimated = estimated
        .checked_add(charge)
        .ok_or(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: u64::MAX,
        })?;
    limits.check_allocation_bytes(*estimated)
}

fn sort_occurrences(occurrences: &mut [JsonOccurrence]) {
    occurrences.sort_by(|a, b| a.doc_id.cmp(&b.doc_id).then_with(|| a.path.cmp(&b.path)));
}

fn reject_duplicate_paths(occurrences: &[JsonOccurrence]) -> SegmentResult<()> {
    for pair in occurrences.windows(2) {
        if pair[0].doc_id == pair[1].doc_id && pair[0].path == pair[1].path {
            return Err(SegmentError::Corrupt {
                context: JSON_PATHS_CONTEXT,
                detail: "duplicate concrete path in indexed JSON field".to_owned(),
            });
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Encoding
// ---------------------------------------------------------------------------

/// One field's sorted occurrences for section encoding.
pub(crate) struct JsonFieldOccurrences {
    /// Dense schema field id (ascending across the slice).
    pub field_id: u32,
    /// Occurrences in `(doc_id, concrete_path)` order.
    pub occurrences: Vec<JsonOccurrence>,
}

/// Encode a JSON-path section body. Field ids must be strictly ascending.
pub(crate) fn encode_json_paths(
    document_count: u64,
    fields: &mut [JsonFieldOccurrences],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let section_ceiling = MAX_JSON_PATH_SECTION_BYTES.min(limits.max_section_decode_bytes());
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u64(document_count);
    writer.u32(
        u32::try_from(fields.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: fields.len() as u64,
        })?,
    );
    let mut previous_field: Option<u32> = None;
    for field in fields.iter_mut() {
        if let Some(previous) = previous_field {
            if field.field_id <= previous {
                return Err(SegmentError::Corrupt {
                    context: JSON_PATHS_CONTEXT,
                    detail: "field ids are not strictly ascending".to_owned(),
                });
            }
        }
        previous_field = Some(field.field_id);
        sort_occurrences(&mut field.occurrences);
        reject_duplicate_paths(&field.occurrences)?;
        let count = field.occurrences.len() as u64;
        if count > MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT {
            return Err(SegmentError::LimitExceeded {
                limit: MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT,
                requested: count,
            });
        }
        writer.u32(field.field_id);
        writer.u64(count);
        for occurrence in &field.occurrences {
            writer.u64(occurrence.doc_id);
            let depth = occurrence.path.len();
            if depth > MAX_JSON_PATH_DEPTH {
                return Err(SegmentError::LimitExceeded {
                    limit: MAX_JSON_PATH_DEPTH as u64,
                    requested: depth as u64,
                });
            }
            writer.varint(depth as u64);
            for component in &occurrence.path {
                match component {
                    JsonPathComponent::Member(member) => {
                        if member.len() > MAX_JSON_PATH_MEMBER_BYTES {
                            return Err(SegmentError::LimitExceeded {
                                limit: MAX_JSON_PATH_MEMBER_BYTES as u64,
                                requested: member.len() as u64,
                            });
                        }
                        writer.u8(0);
                        writer.varint(member.len() as u64);
                        writer.bytes(member.as_bytes());
                    }
                    JsonPathComponent::Index(index) => {
                        writer.u8(1);
                        writer.varint(*index);
                    }
                }
            }
            write_node(&mut writer, &occurrence.node)?;
            if writer.len() as u64 > section_ceiling {
                return Err(SegmentError::LimitExceeded {
                    limit: section_ceiling,
                    requested: writer.len() as u64,
                });
            }
        }
    }
    let body = writer.into_vec();
    if body.len() as u64 > section_ceiling {
        return Err(SegmentError::LimitExceeded {
            limit: section_ceiling,
            requested: body.len() as u64,
        });
    }
    Ok(body)
}

fn write_node(writer: &mut ByteWriter, node: &JsonNode) -> SegmentResult<()> {
    match node {
        JsonNode::Null => writer.u8(0),
        JsonNode::Bool(flag) => {
            writer.u8(1);
            writer.u8(u8::from(*flag));
        }
        JsonNode::I64(number) => {
            writer.u8(2);
            writer.i64(*number);
        }
        JsonNode::U64(number) => {
            writer.u8(3);
            writer.u64(*number);
        }
        JsonNode::F64(number) => {
            if !number.is_finite() {
                return Err(SegmentError::NonFiniteFloat {
                    context: "json path f64",
                });
            }
            writer.u8(4);
            writer.f64(normalize_zero(*number));
        }
        JsonNode::String(text) => {
            if text.len() > MAX_JSON_PATH_MEMBER_BYTES {
                return Err(SegmentError::LimitExceeded {
                    limit: MAX_JSON_PATH_MEMBER_BYTES as u64,
                    requested: text.len() as u64,
                });
            }
            writer.u8(5);
            writer.varint(text.len() as u64);
            writer.bytes(text.as_bytes());
        }
        JsonNode::Array => writer.u8(6),
        JsonNode::Object => writer.u8(7),
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Decoding
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct JsonDocOffset {
    field_id: u32,
    doc_id: u64,
    offset: usize,
    count: u32,
}

/// The owned, validated offset directory cached by the owning `SegmentReader`.
#[derive(Debug)]
pub(crate) struct JsonPathDirectory {
    doc_offsets: Vec<JsonDocOffset>,
}

/// A bounded reader over a validated JSON-path section body.
pub(crate) struct JsonPathsReader<'a> {
    body: &'a [u8],
    limits: SegmentLimits,
    directory: Rc<JsonPathDirectory>,
}

impl<'a> JsonPathsReader<'a> {
    /// Wrap a validated body and directory.
    pub(crate) fn new(
        body: &'a [u8],
        directory: Rc<JsonPathDirectory>,
        limits: SegmentLimits,
    ) -> Self {
        Self {
            body,
            limits,
            directory,
        }
    }

    /// Decode and fully validate a JSON-path section body.
    pub(crate) fn decode_directory(
        body: &[u8],
        document_count: u64,
        schema: &CodecSchema,
        limits: &SegmentLimits,
    ) -> SegmentResult<JsonPathDirectory> {
        if body.len() as u64 > MAX_JSON_PATH_SECTION_BYTES {
            return Err(SegmentError::LimitExceeded {
                limit: MAX_JSON_PATH_SECTION_BYTES,
                requested: body.len() as u64,
            });
        }
        let depth_limit = effective_depth(limits);
        let mut reader = ByteReader::new(body);
        let version = reader.u16("json paths version")?;
        if version != 1 {
            return Err(SegmentError::Corrupt {
                context: JSON_PATHS_CONTEXT,
                detail: format!("unsupported version {version}"),
            });
        }
        let declared = reader.u64("json paths document count")?;
        if declared != document_count {
            return Err(SegmentError::Corrupt {
                context: JSON_PATHS_CONTEXT,
                detail: "document count does not match segment".to_owned(),
            });
        }
        let field_count = reader.u32("json paths field count")?;
        let field_count_u64 = u64::from(field_count);
        limits.check_entries(field_count_u64)?;
        let mut budget = DecodeBudget::new(limits);
        let mut doc_offsets: Vec<JsonDocOffset> = Vec::new();
        let mut previous_field: Option<u32> = None;
        for _ in 0..field_count {
            let field_id = reader.u32("json paths field id")?;
            let field = schema.field(field_id).ok_or(SegmentError::Corrupt {
                context: JSON_PATHS_CONTEXT,
                detail: "unknown field id".to_owned(),
            })?;
            if field.field_type != FieldType::Json {
                return Err(SegmentError::Corrupt {
                    context: JSON_PATHS_CONTEXT,
                    detail: "non-json field id".to_owned(),
                });
            }
            if let Some(previous) = previous_field {
                if field_id <= previous {
                    return Err(SegmentError::Corrupt {
                        context: JSON_PATHS_CONTEXT,
                        detail: "field ids are not strictly ascending".to_owned(),
                    });
                }
            }
            previous_field = Some(field_id);
            let occurrence_count = reader.u64("json paths occurrence count")?;
            if occurrence_count > MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT {
                return Err(SegmentError::LimitExceeded {
                    limit: MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT,
                    requested: occurrence_count,
                });
            }
            limits.check_entries(occurrence_count)?;
            // `count_min_bytes` guards a hostile occurrence_count against the
            // remaining body before any per-occurrence decode.
            super::format::count_min_bytes(
                JSON_PATHS_CONTEXT,
                occurrence_count,
                10,
                reader.remaining() as u64,
            )?;
            let mut previous_doc: Option<u64> = None;
            let mut previous_path: Vec<JsonPathComponent> = Vec::new();
            let mut path: Vec<JsonPathComponent> = Vec::new();
            let mut run_doc = 0u64;
            let mut run_offset = 0usize;
            let mut run_count = 0u32;
            for _ in 0..occurrence_count {
                let start = reader.position();
                let doc_id = reader.u64("json paths doc id")?;
                if doc_id >= document_count {
                    return Err(SegmentError::Corrupt {
                        context: JSON_PATHS_CONTEXT,
                        detail: "doc id out of range".to_owned(),
                    });
                }
                decode_path(&mut reader, &mut path, depth_limit, limits)?;
                let node_kind = reader.u8("json paths node kind")?;
                skip_node(&mut reader, node_kind, limits)?;
                if let Some(previous) = previous_doc {
                    let ordering = doc_id.cmp(&previous).then_with(|| path.cmp(&previous_path));
                    if ordering != Ordering::Greater {
                        return Err(SegmentError::Corrupt {
                            context: JSON_PATHS_CONTEXT,
                            detail: "occurrences are not strictly ascending".to_owned(),
                        });
                    }
                }
                if run_count == 0 {
                    run_doc = doc_id;
                    run_offset = start;
                    run_count = 1;
                } else if doc_id == run_doc {
                    run_count = run_count.checked_add(1).ok_or(SegmentError::Corrupt {
                        context: JSON_PATHS_CONTEXT,
                        detail: "occurrence run count overflow".to_owned(),
                    })?;
                } else {
                    budget.reserve_bytes(doc_offset_charge())?;
                    doc_offsets.push(JsonDocOffset {
                        field_id,
                        doc_id: run_doc,
                        offset: run_offset,
                        count: run_count,
                    });
                    run_doc = doc_id;
                    run_offset = start;
                    run_count = 1;
                }
                previous_doc = Some(doc_id);
                std::mem::swap(&mut previous_path, &mut path);
            }
            if run_count > 0 {
                budget.reserve_bytes(doc_offset_charge())?;
                doc_offsets.push(JsonDocOffset {
                    field_id,
                    doc_id: run_doc,
                    offset: run_offset,
                    count: run_count,
                });
            }
        }
        reader.expect_end(JSON_PATHS_CONTEXT)?;
        Ok(JsonPathDirectory { doc_offsets })
    }

    /// Iterate the decoded occurrences of one `(field, doc)` pair.
    pub(crate) fn doc_occurrences(
        &self,
        field_id: u32,
        doc_id: u64,
    ) -> SegmentResult<Option<DocOccurrences<'_>>> {
        let offsets = &self.directory.doc_offsets;
        let start =
            offsets.partition_point(|entry| (entry.field_id, entry.doc_id) < (field_id, doc_id));
        let Some(entry) = offsets.get(start) else {
            return Ok(None);
        };
        if entry.field_id != field_id || entry.doc_id != doc_id {
            return Ok(None);
        }
        let slice = self.body.get(entry.offset..).ok_or(SegmentError::Corrupt {
            context: JSON_PATHS_CONTEXT,
            detail: "occurrence offset out of range".to_owned(),
        })?;
        Ok(Some(DocOccurrences {
            reader: ByteReader::new(slice),
            remaining: entry.count,
            depth_limit: effective_depth(&self.limits),
            limits: self.limits,
        }))
    }
}

fn doc_offset_charge() -> u64 {
    std::mem::size_of::<JsonDocOffset>() as u64 + 3 * std::mem::size_of::<usize>() as u64
}

/// A cursor over one document's occurrences within a field.
pub(crate) struct DocOccurrences<'a> {
    reader: ByteReader<'a>,
    remaining: u32,
    depth_limit: usize,
    limits: SegmentLimits,
}

impl DocOccurrences<'_> {
    /// Decode the next occurrence, or `None` when the run is exhausted.
    pub(crate) fn next_occurrence(&mut self) -> SegmentResult<Option<JsonOccurrence>> {
        if self.remaining == 0 {
            return Ok(None);
        }
        let doc_id = self.reader.u64("json paths doc id")?;
        let mut path = Vec::new();
        decode_path(&mut self.reader, &mut path, self.depth_limit, &self.limits)?;
        let node_kind = self.reader.u8("json paths node kind")?;
        let node = decode_node(&mut self.reader, node_kind, &self.limits)?;
        self.remaining -= 1;
        Ok(Some(JsonOccurrence { doc_id, path, node }))
    }
}

fn decode_path(
    reader: &mut ByteReader<'_>,
    path: &mut Vec<JsonPathComponent>,
    depth_limit: usize,
    limits: &SegmentLimits,
) -> SegmentResult<()> {
    path.clear();
    let count = reader.varint("json path segment count")?;
    if count > depth_limit as u64 {
        return Err(SegmentError::LimitExceeded {
            limit: depth_limit as u64,
            requested: count,
        });
    }
    limits.check_entries(count)?;
    for _ in 0..count {
        match reader.u8("json path segment tag")? {
            0 => {
                let len = reader.varint("json path member length")?;
                if len > MAX_JSON_PATH_MEMBER_BYTES as u64 {
                    return Err(SegmentError::LimitExceeded {
                        limit: MAX_JSON_PATH_MEMBER_BYTES as u64,
                        requested: len,
                    });
                }
                if len > limits.max_single_allocation() {
                    return Err(SegmentError::LimitExceeded {
                        limit: limits.max_single_allocation(),
                        requested: len,
                    });
                }
                let bytes = reader.bytes(len as usize, "json path member")?;
                let member = std::str::from_utf8(bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "json path member",
                })?;
                path.push(JsonPathComponent::Member(member.to_owned()));
            }
            1 => path.push(JsonPathComponent::Index(reader.varint("json path index")?)),
            tag => {
                return Err(SegmentError::Corrupt {
                    context: JSON_PATHS_CONTEXT,
                    detail: format!("invalid path segment tag {tag}"),
                });
            }
        }
    }
    Ok(())
}

fn skip_node(reader: &mut ByteReader<'_>, kind: u8, limits: &SegmentLimits) -> SegmentResult<()> {
    match kind {
        0 | 6 | 7 => Ok(()),
        1 => match reader.u8("json path bool")? {
            0 | 1 => Ok(()),
            _ => Err(SegmentError::Corrupt {
                context: JSON_PATHS_CONTEXT,
                detail: "invalid bool payload".to_owned(),
            }),
        },
        2 => {
            reader.i64("json path i64")?;
            Ok(())
        }
        3 => {
            reader.u64("json path u64")?;
            Ok(())
        }
        4 => {
            reader.f64("json path f64")?;
            Ok(())
        }
        5 => {
            let len = reader.varint("json path string length")?;
            if len > MAX_JSON_PATH_MEMBER_BYTES as u64 {
                return Err(SegmentError::LimitExceeded {
                    limit: MAX_JSON_PATH_MEMBER_BYTES as u64,
                    requested: len,
                });
            }
            if len > limits.max_single_allocation() {
                return Err(SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: len,
                });
            }
            let bytes = reader.bytes(len as usize, "json path string")?;
            std::str::from_utf8(bytes).map_err(|_| SegmentError::InvalidUtf8 {
                context: "json path string",
            })?;
            Ok(())
        }
        _ => Err(SegmentError::Corrupt {
            context: JSON_PATHS_CONTEXT,
            detail: format!("invalid node kind {kind}"),
        }),
    }
}

fn decode_node(
    reader: &mut ByteReader<'_>,
    kind: u8,
    limits: &SegmentLimits,
) -> SegmentResult<JsonNode> {
    match kind {
        0 => Ok(JsonNode::Null),
        1 => match reader.u8("json path bool")? {
            0 => Ok(JsonNode::Bool(false)),
            1 => Ok(JsonNode::Bool(true)),
            _ => Err(SegmentError::Corrupt {
                context: JSON_PATHS_CONTEXT,
                detail: "invalid bool payload".to_owned(),
            }),
        },
        2 => Ok(JsonNode::I64(reader.i64("json path i64")?)),
        3 => Ok(JsonNode::U64(reader.u64("json path u64")?)),
        4 => Ok(JsonNode::F64(normalize_zero(reader.f64("json path f64")?))),
        5 => {
            let len = reader.varint("json path string length")?;
            if len > MAX_JSON_PATH_MEMBER_BYTES as u64 {
                return Err(SegmentError::LimitExceeded {
                    limit: MAX_JSON_PATH_MEMBER_BYTES as u64,
                    requested: len,
                });
            }
            if len > limits.max_single_allocation() {
                return Err(SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: len,
                });
            }
            let bytes = reader.bytes(len as usize, "json path string")?;
            let text = std::str::from_utf8(bytes).map_err(|_| SegmentError::InvalidUtf8 {
                context: "json path string",
            })?;
            Ok(JsonNode::String(text.to_owned()))
        }
        6 => Ok(JsonNode::Array),
        7 => Ok(JsonNode::Object),
        _ => Err(SegmentError::Corrupt {
            context: JSON_PATHS_CONTEXT,
            detail: format!("invalid node kind {kind}"),
        }),
    }
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};

    fn codec_schema() -> CodecSchema {
        let schema = Schema::new(
            vec![
                FieldDefinition::new(
                    "body",
                    FieldType::Json,
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
        let bindings = crate::analysis::SchemaAnalyzerBindings::resolve(
            &schema,
            &crate::analysis::AnalyzerRegistry::builtin(),
        )
        .unwrap();
        CodecSchema::from_contract(&schema, &bindings).unwrap()
    }

    fn json(value: JsonValue) -> FieldValues {
        FieldValues::Single(FieldValue::Json(value))
    }

    fn section(body: &FieldValues) -> (Vec<u8>, CodecSchema) {
        let limits = SegmentLimits::default();
        let schema = codec_schema();
        let occurrences = extract_field_paths(0, body, &limits).unwrap();
        let mut fields = vec![JsonFieldOccurrences {
            field_id: 0,
            occurrences,
        }];
        let bytes = encode_json_paths(1, &mut fields, &limits).unwrap();
        (bytes, schema)
    }

    fn read_doc(
        bytes: &[u8],
        schema: &CodecSchema,
        field_id: u32,
        doc_id: u64,
    ) -> Vec<JsonOccurrence> {
        let limits = SegmentLimits::default();
        let directory = JsonPathsReader::decode_directory(bytes, 1, schema, &limits).unwrap();
        let reader = JsonPathsReader::new(bytes, Rc::new(directory), limits);
        let mut out = Vec::new();
        if let Some(mut cursor) = reader.doc_occurrences(field_id, doc_id).unwrap() {
            while let Some(occurrence) = cursor.next_occurrence().unwrap() {
                out.push(occurrence);
            }
        }
        out
    }

    #[test]
    fn round_trip_paths_and_nodes() {
        let body = json(JsonValue::Object(vec![
            (
                "a".into(),
                JsonValue::Array(vec![JsonValue::Number(JsonNumber::I64(1)), JsonValue::Null]),
            ),
            (
                "b".into(),
                JsonValue::Object(vec![("é".into(), JsonValue::Number(JsonNumber::F64(-0.0)))]),
            ),
        ]));
        let (bytes, schema) = section(&body);
        let occurrences = read_doc(&bytes, &schema, 0, 0);
        // Root + a + a[0] + a[1] + b + b.é == 6.
        assert_eq!(occurrences.len(), 6);
        assert!(occurrences.iter().any(|o| {
            o.path
                == vec![
                    JsonPathComponent::Member("a".into()),
                    JsonPathComponent::Index(0),
                ]
                && o.node == JsonNode::I64(1)
        }));
        // Signed zero is normalized on both encode and decode.
        let zero = occurrences
            .iter()
            .find(|o| {
                o.path
                    == vec![
                        JsonPathComponent::Member("b".into()),
                        JsonPathComponent::Member("é".into()),
                    ]
            })
            .unwrap();
        assert_eq!(zero.node, JsonNode::F64(0.0));
    }

    #[test]
    fn encoding_is_deterministic() {
        let body = json(JsonValue::Object(vec![
            ("z".into(), JsonValue::Bool(true)),
            ("a".into(), JsonValue::String("x".into())),
        ]));
        let (first, _) = section(&body);
        let (second, _) = section(&body);
        assert_eq!(first, second);
    }

    #[test]
    fn multi_root_prefixes_indices() {
        let values = FieldValues::Multi(vec![
            FieldValue::Json(JsonValue::Object(vec![("x".into(), JsonValue::Null)])),
            FieldValue::Json(JsonValue::Object(vec![("x".into(), JsonValue::Null)])),
        ]);
        let limits = SegmentLimits::default();
        let occurrences = extract_field_paths(0, &values, &limits).unwrap();
        assert!(occurrences.iter().any(|o| o.path
            == vec![
                JsonPathComponent::Index(0),
                JsonPathComponent::Member("x".into())
            ]));
        assert!(occurrences.iter().any(|o| o.path
            == vec![
                JsonPathComponent::Index(1),
                JsonPathComponent::Member("x".into())
            ]));
    }

    #[test]
    fn duplicate_members_are_rejected() {
        let values = json(JsonValue::Object(vec![
            ("a".into(), JsonValue::Null),
            ("a".into(), JsonValue::Null),
        ]));
        let limits = SegmentLimits::default();
        assert!(extract_field_paths(0, &values, &limits).is_err());
    }

    #[test]
    fn depth_and_member_bounds() {
        let limits = SegmentLimits::default().with_max_single_allocation(u64::MAX);
        // A chain deeper than 128 segments fails.
        let mut value = JsonValue::Null;
        for _ in 0..200 {
            value = JsonValue::Array(vec![value]);
        }
        assert!(extract_field_paths(0, &json(value), &limits).is_err());
        // A member longer than the wire bound fails.
        let long = "x".repeat(MAX_JSON_PATH_MEMBER_BYTES + 1);
        let value = JsonValue::Object(vec![(long, JsonValue::Null)]);
        assert!(extract_field_paths(0, &json(value), &limits).is_err());
    }

    #[test]
    fn corruption_fails_closed() {
        let body = json(JsonValue::Object(vec![("a".into(), JsonValue::Null)]));
        let (bytes, schema) = section(&body);
        let limits = SegmentLimits::default();
        // Trailing bytes.
        let mut trailing = bytes.clone();
        trailing.push(0);
        assert!(JsonPathsReader::decode_directory(&trailing, 1, &schema, &limits).is_err());
        // Truncation at every prefix boundary must be typed, never a panic.
        for cut in 0..bytes.len() {
            let truncated = &bytes[..cut];
            assert!(
                JsonPathsReader::decode_directory(truncated, 1, &schema, &limits).is_err(),
                "prefix {cut} unexpectedly decoded"
            );
        }
    }

    #[test]
    fn version_and_document_count_validation() {
        let body = json(JsonValue::Null);
        let (mut bytes, schema) = section(&body);
        let limits = SegmentLimits::default();
        bytes[0] = 2;
        assert!(JsonPathsReader::decode_directory(&bytes, 1, &schema, &limits).is_err());

        let (bytes, schema) = section(&body);
        // Declared document count must match.
        assert!(JsonPathsReader::decode_directory(&bytes, 2, &schema, &limits).is_err());
    }

    #[test]
    fn non_json_field_id_is_rejected() {
        let body = json(JsonValue::Null);
        let limits = SegmentLimits::default();
        let occurrences = extract_field_paths(0, &body, &limits).unwrap();
        let mut fields = vec![JsonFieldOccurrences {
            field_id: 1, // "n", not a JSON field
            occurrences,
        }];
        let bytes = encode_json_paths(1, &mut fields, &limits).unwrap();
        let schema = codec_schema();
        assert!(JsonPathsReader::decode_directory(&bytes, 1, &schema, &limits).is_err());
    }

    #[test]
    fn matching_helpers_are_exact() {
        let pattern = vec![
            JsonPathSegment::Member("a".into()),
            JsonPathSegment::Wildcard,
        ];
        let path = vec![
            JsonPathComponent::Member("a".into()),
            JsonPathComponent::Index(0),
        ];
        assert!(path_matches(&pattern, &path));
        assert!(!path_equals(&pattern, &path));
        let concrete = vec![
            JsonPathSegment::Member("a".into()),
            JsonPathSegment::Index(0),
        ];
        assert!(path_equals(&concrete, &path));
        assert!(node_matches_scalar(&JsonNode::I64(1), &JsonScalar::I64(1)));
        assert!(!node_matches_scalar(&JsonNode::I64(1), &JsonScalar::U64(1)));
        assert!(node_matches_scalar(
            &JsonNode::F64(-0.0),
            &JsonScalar::F64(0.0)
        ));
    }
}
