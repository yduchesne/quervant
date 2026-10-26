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
use crate::contract::query::{Bound, JsonPathSegment};
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

/// Admission sink for transient JSON occurrence scratch growth.
///
/// [`push_occurrence`] and [`extract_field_paths_charged`] call [`Self::charge`]
/// **before** a capacity-increasing allocation and [`Self::release`] when a
/// reservation proves larger than the allocator's actual growth. `charge`
/// returning `false` means the caller must stop with a typed limit failure; the
/// owner of the sink decides how that failure is surfaced (batch memory budgets
/// map it back to `BatchMemoryBytes`).
pub(crate) trait ScratchCharge {
    /// Admit `bytes` before the backing allocation grows.
    fn charge(&mut self, bytes: u64) -> bool;
    /// Return `bytes` after a reservation exceeded the real growth.
    fn release(&mut self, bytes: u64);
}

/// No-op sink used by non-batch callers with existing query-local limits.
pub(crate) struct NoScratchCharge;

impl ScratchCharge for NoScratchCharge {
    fn charge(&mut self, _bytes: u64) -> bool {
        true
    }

    fn release(&mut self, _bytes: u64) {}
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

/// Scalar-kind tag. `None` for null and containers.
fn node_tag(node: &JsonNode) -> Option<u8> {
    match node {
        JsonNode::Bool(_) => Some(0),
        JsonNode::I64(_) => Some(1),
        JsonNode::U64(_) => Some(2),
        JsonNode::F64(_) => Some(3),
        JsonNode::String(_) => Some(4),
        JsonNode::Null | JsonNode::Array | JsonNode::Object => None,
    }
}

fn scalar_tag(scalar: &JsonScalar) -> u8 {
    match scalar {
        JsonScalar::Bool(_) => 0,
        JsonScalar::I64(_) => 1,
        JsonScalar::U64(_) => 2,
        JsonScalar::F64(_) => 3,
        JsonScalar::String(_) => 4,
    }
}

/// Same-type scalar comparison of an indexed node against a query scalar.
/// Returns `None` when either side is not a scalar or the types differ; a type
/// mismatch never matches a range (no numeric coercion).
fn cmp_node_scalar(node: &JsonNode, scalar: &JsonScalar) -> Option<Ordering> {
    if node_tag(node)? != scalar_tag(scalar) {
        return None;
    }
    match (node, scalar) {
        (JsonNode::Bool(a), JsonScalar::Bool(b)) => Some(a.cmp(b)),
        (JsonNode::I64(a), JsonScalar::I64(b)) => Some(a.cmp(b)),
        (JsonNode::U64(a), JsonScalar::U64(b)) => Some(a.cmp(b)),
        (JsonNode::F64(a), JsonScalar::F64(b)) => Some(a.total_cmp(b)),
        (JsonNode::String(a), JsonScalar::String(b)) => Some(a.as_bytes().cmp(b.as_slice())),
        _ => None,
    }
}

/// Whether one occurrence at `pattern` satisfies a same-type scalar range.
#[must_use]
pub(crate) fn occurrence_matches_range(
    occurrence: &JsonOccurrence,
    pattern: &[JsonPathSegment],
    lower: &Bound<JsonScalar>,
    upper: &Bound<JsonScalar>,
) -> bool {
    if !path_equals(pattern, &occurrence.path) {
        return false;
    }
    if node_tag(&occurrence.node).is_none() {
        return false;
    }
    let lower_ok = match lower {
        Bound::Unbounded => true,
        Bound::Included(scalar) => cmp_node_scalar(&occurrence.node, scalar)
            .is_some_and(|ordering| ordering != Ordering::Less),
        Bound::Excluded(scalar) => cmp_node_scalar(&occurrence.node, scalar)
            .is_some_and(|ordering| ordering == Ordering::Greater),
    };
    let upper_ok = match upper {
        Bound::Unbounded => true,
        Bound::Included(scalar) => cmp_node_scalar(&occurrence.node, scalar)
            .is_some_and(|ordering| ordering != Ordering::Greater),
        Bound::Excluded(scalar) => cmp_node_scalar(&occurrence.node, scalar)
            .is_some_and(|ordering| ordering == Ordering::Less),
    };
    lower_ok && upper_ok
}

/// Whether `path` is exactly one immediate array-index child of `parent`.
#[must_use]
pub(crate) fn occurrence_is_immediate_index_child(
    parent: &[JsonPathSegment],
    path: &[JsonPathComponent],
) -> bool {
    path.len() == parent.len() + 1
        && matches!(path.last(), Some(JsonPathComponent::Index(_)))
        && path_equals(parent, &path[..parent.len()])
}

/// Whether an occurrence is an indexed array node.
#[must_use]
pub(crate) fn node_is_array(node: &JsonNode) -> bool {
    matches!(node, JsonNode::Array)
}

/// Whether an indexed node is JSON null.
#[must_use]
pub(crate) fn node_is_null(node: &JsonNode) -> bool {
    matches!(node, JsonNode::Null)
}

/// Convert a scalar indexed node into a canonical typed value for sorting.
/// JSON strings map to `Keyword` so the shared byte comparator applies.
#[must_use]
pub(crate) fn node_to_field_value(node: &JsonNode) -> Option<FieldValue> {
    match node {
        JsonNode::Bool(flag) => Some(FieldValue::Bool(*flag)),
        JsonNode::I64(number) => Some(FieldValue::I64(*number)),
        JsonNode::U64(number) => Some(FieldValue::U64(*number)),
        JsonNode::F64(number) => Some(FieldValue::F64(*number)),
        JsonNode::String(text) => Some(FieldValue::Keyword(text.clone())),
        JsonNode::Null | JsonNode::Array | JsonNode::Object => None,
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

/// A depth-first cursor over one already-visited container.
///
/// Only the container reference and the index of its next child are retained,
/// so the frontier is proportional to nesting depth rather than sibling width.
/// It never owns or clones child JSON values.
struct DfsFrame<'a> {
    parent_len: usize,
    next_child: usize,
    value: &'a JsonValue,
}

#[cfg(test)]
thread_local! {
    /// Test-only high-water mark of the DFS pending-child frontier.
    static DFS_FRAME_HIGH_WATER: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

#[cfg(test)]
fn reset_dfs_frame_high_water() {
    DFS_FRAME_HIGH_WATER.with(|cell| cell.set(0));
}

#[cfg(test)]
fn dfs_frame_high_water() -> usize {
    DFS_FRAME_HIGH_WATER.with(std::cell::Cell::get)
}

#[cfg(test)]
fn note_dfs_frames(len: usize) {
    DFS_FRAME_HIGH_WATER.with(|cell| cell.set(cell.get().max(len)));
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
    extract_field_paths_charged(doc_id, values, limits, &mut NoScratchCharge)
}

/// Extract one JSON field's occurrences, admitting every retained growth through
/// `charge` before the allocation happens.
///
/// The returned vector plus the owned path/member/node data it holds is what the
/// sink admitted; the caller must release that amount after dropping the vector.
/// The walker's own bounded traversal scratch (one reusable path and a
/// depth-bounded cursor stack) is transient and is qualified separately.
pub(crate) fn extract_field_paths_charged(
    doc_id: u64,
    values: &FieldValues,
    limits: &SegmentLimits,
    charge: &mut dyn ScratchCharge,
) -> SegmentResult<Vec<JsonOccurrence>> {
    let mut out: Vec<JsonOccurrence> = Vec::new();
    let depth_limit = effective_depth(limits);
    let mut estimated: u64 = 0;
    match values {
        FieldValues::Absent | FieldValues::Empty => return Ok(out),
        FieldValues::ExplicitNull => {
            push_occurrence(
                &mut out,
                JsonOccurrence {
                    doc_id,
                    path: Vec::new(),
                    node: JsonNode::Null,
                },
                charge,
                limits,
            )?;
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
                    charge,
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
                    charge,
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
    charge: &mut dyn ScratchCharge,
) -> SegmentResult<()> {
    let mut path = root_prefix;
    // At most one cursor frame per currently active container is retained, so
    // the pending frontier is bounded by nesting depth, never sibling width.
    let mut stack: Vec<DfsFrame<'_>> = Vec::new();
    let mut current_value: &JsonValue = root;
    let mut current_seed: Option<Seed<'_>> = None;
    let mut current_parent_len = path.len();

    loop {
        // Materialize the current node exactly once, before any children.
        path.truncate(current_parent_len);
        if let Some(seed) = current_seed.take() {
            let next_len = path
                .len()
                .checked_add(1)
                .ok_or(SegmentError::LimitExceeded {
                    limit: depth_limit as u64,
                    requested: u64::MAX,
                })?;
            if next_len > depth_limit {
                return Err(SegmentError::LimitExceeded {
                    limit: depth_limit as u64,
                    requested: next_len as u64,
                });
            }
            limits.check_alloc::<JsonPathComponent>(next_len as u64)?;
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
        let node = node_of(current_value);
        charge_occurrence(estimated, &path, &node, limits)?;
        push_occurrence(
            out,
            JsonOccurrence {
                doc_id,
                path: path.clone(),
                node,
            },
            charge,
            limits,
        )?;

        // Prepare a cursor only for a nonempty container; scalars need none.
        match current_value {
            JsonValue::Array(values) => {
                if values.len() as u64 > limits.max_array_elements() {
                    return Err(SegmentError::LimitExceeded {
                        limit: limits.max_array_elements(),
                        requested: values.len() as u64,
                    });
                }
                if !values.is_empty() {
                    push_frame(
                        &mut stack,
                        DfsFrame {
                            parent_len: path.len(),
                            next_child: 0,
                            value: current_value,
                        },
                        limits,
                    )?;
                }
            }
            JsonValue::Object(entries) if !entries.is_empty() => {
                push_frame(
                    &mut stack,
                    DfsFrame {
                        parent_len: path.len(),
                        next_child: 0,
                        value: current_value,
                    },
                    limits,
                )?;
            }
            _ => {}
        }

        // Descend to the next child, popping exhausted ancestors.
        loop {
            let next =
                {
                    let Some(frame) = stack.last_mut() else {
                        return Ok(());
                    };
                    let container = frame.value;
                    match child_at(container, frame.next_child) {
                        Some((child, seed)) => {
                            frame.next_child = frame.next_child.checked_add(1).ok_or(
                                SegmentError::LimitExceeded {
                                    limit: limits.max_array_elements(),
                                    requested: u64::MAX,
                                },
                            )?;
                            Some((child, seed, frame.parent_len))
                        }
                        None => None,
                    }
                };
            match next {
                Some((child, seed, parent_len)) => {
                    current_value = child;
                    current_seed = Some(seed);
                    current_parent_len = parent_len;
                    break;
                }
                None => {
                    stack.pop();
                }
            }
        }
    }
}

/// Borrow the child at `index`, or `None` when the container is exhausted.
fn child_at(value: &JsonValue, index: usize) -> Option<(&JsonValue, Seed<'_>)> {
    match value {
        JsonValue::Array(values) => {
            let child = values.get(index)?;
            Some((child, Seed::Index(index as u64)))
        }
        JsonValue::Object(entries) => {
            let (key, child) = entries.get(index)?;
            Some((child, Seed::Member(key.as_str())))
        }
        _ => None,
    }
}

/// Append one cursor frame, preflighting the retained frontier capacity before
/// any growth. Allocation failures are typed, never panics.
fn push_frame<'a>(
    stack: &mut Vec<DfsFrame<'a>>,
    frame: DfsFrame<'a>,
    limits: &SegmentLimits,
) -> SegmentResult<()> {
    let frame_bytes = std::mem::size_of::<DfsFrame<'a>>() as u64;
    let next_frames = (stack.len() as u64)
        .checked_add(1)
        .ok_or(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: u64::MAX,
        })?;
    let requested = next_frames
        .checked_mul(frame_bytes)
        .ok_or(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: u64::MAX,
        })?;
    limits.check_allocation_bytes(requested)?;
    if stack.len() == stack.capacity() {
        let proposed_capacity = (stack.capacity() as u64).saturating_mul(2).max(next_frames);
        let proposed_bytes =
            proposed_capacity
                .checked_mul(frame_bytes)
                .ok_or(SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: u64::MAX,
                })?;
        limits.check_allocation_bytes(proposed_bytes)?;
        stack
            .try_reserve(1)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested,
            })?;
        let actual_bytes = (stack.capacity() as u64).checked_mul(frame_bytes).ok_or(
            SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: u64::MAX,
            },
        )?;
        limits.check_allocation_bytes(actual_bytes)?;
    }
    stack.push(frame);
    #[cfg(test)]
    note_dfs_frames(stack.len());
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

/// Owned heap bytes retained by one pushed occurrence: the path component array,
/// the member-string payloads, and any node string payload. The `Vec` slot
/// itself is charged separately when the occurrence vector grows.
fn retained_owned_bytes(
    path: &[JsonPathComponent],
    node: &JsonNode,
    limits: &SegmentLimits,
) -> SegmentResult<u64> {
    let overflow = || SegmentError::LimitExceeded {
        limit: limits.max_single_allocation(),
        requested: u64::MAX,
    };
    let mut bytes = (path.len() as u64)
        .checked_mul(std::mem::size_of::<JsonPathComponent>() as u64)
        .ok_or_else(overflow)?;
    for component in path {
        if let JsonPathComponent::Member(member) = component {
            bytes = bytes
                .checked_add(member.len() as u64)
                .ok_or_else(overflow)?;
        }
    }
    if let JsonNode::String(text) = node {
        bytes = bytes.checked_add(text.len() as u64).ok_or_else(overflow)?;
    }
    Ok(bytes)
}

fn scratch_rejected(bytes: u64) -> SegmentError {
    // The owning sink records the precise typed failure (for example
    // `BatchMemoryBytes`) and the search layer re-raises it.
    SegmentError::LimitExceeded {
        limit: bytes,
        requested: bytes,
    }
}

/// Push one occurrence, admitting vector growth and owned path/node bytes
/// through `charge` **before** the allocation happens.
///
/// Capacity growth is reserved before `try_reserve_exact` and reconciled with the
/// allocator's actual capacity. A rejected admission or failed allocation
/// returns a typed limit failure with the prior reservations left to the sink
/// owner to release.
pub(crate) fn push_occurrence(
    out: &mut Vec<JsonOccurrence>,
    occurrence: JsonOccurrence,
    charge: &mut dyn ScratchCharge,
    limits: &SegmentLimits,
) -> SegmentResult<()> {
    if out.len() == out.capacity() {
        let additional = if out.capacity() == 0 {
            4
        } else {
            out.capacity()
        };
        let slot = std::mem::size_of::<JsonOccurrence>() as u64;
        let requested =
            (additional as u64)
                .checked_mul(slot)
                .ok_or(SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: u64::MAX,
                })?;
        if !charge.charge(requested) {
            return Err(scratch_rejected(requested));
        }
        let before = out.capacity();
        if out.try_reserve_exact(additional).is_err() {
            charge.release(requested);
            return Err(SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested,
            });
        }
        let actual = ((out.capacity() - before) as u64).checked_mul(slot).ok_or(
            SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: u64::MAX,
            },
        )?;
        if actual > requested {
            let extra = actual - requested;
            if !charge.charge(extra) {
                charge.release(requested);
                return Err(scratch_rejected(extra));
            }
        } else {
            charge.release(requested - actual);
        }
    }
    let owned = retained_owned_bytes(&occurrence.path, &occurrence.node, limits)?;
    if !charge.charge(owned) {
        return Err(scratch_rejected(owned));
    }
    out.push(occurrence);
    Ok(())
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

    fn raw_f64(value: f64) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        writer.f64(value);
        writer.into_vec()
    }

    #[test]
    fn nonfinite_f64_rejected_by_directory_skip() {
        for (label, value) in [
            ("nan", f64::NAN),
            ("positive_infinity", f64::INFINITY),
            ("negative_infinity", f64::NEG_INFINITY),
        ] {
            let bytes = raw_f64(value);
            let mut reader = ByteReader::new(&bytes);
            let result = skip_node(&mut reader, 4, &SegmentLimits::default());
            assert!(
                matches!(
                    result,
                    Err(SegmentError::NonFiniteFloat {
                        context: "json path f64"
                    })
                ),
                "{label}: {result:?}"
            );
        }
    }

    #[test]
    fn nonfinite_f64_rejected_by_occurrence_decode() {
        for (label, value) in [
            ("nan", f64::NAN),
            ("positive_infinity", f64::INFINITY),
            ("negative_infinity", f64::NEG_INFINITY),
        ] {
            let bytes = raw_f64(value);
            let mut reader = ByteReader::new(&bytes);
            let result = decode_node(&mut reader, 4, &SegmentLimits::default());
            assert!(
                matches!(
                    result,
                    Err(SegmentError::NonFiniteFloat {
                        context: "json path f64"
                    })
                ),
                "{label}: {result:?}"
            );
        }
    }

    #[test]
    fn finite_f64_and_signed_zero_still_decode() {
        for input in [-1.5, 0.0, -0.0, 1.5] {
            let expected = normalize_zero(input);
            let bytes = raw_f64(input);

            let mut skip_reader = ByteReader::new(&bytes);
            assert!(skip_node(&mut skip_reader, 4, &SegmentLimits::default()).is_ok());
            skip_reader.expect_end("json path f64").unwrap();

            let mut decode_reader = ByteReader::new(&bytes);
            let node = decode_node(&mut decode_reader, 4, &SegmentLimits::default()).unwrap();
            decode_reader.expect_end("json path f64").unwrap();
            match node {
                JsonNode::F64(actual) => {
                    assert_eq!(actual, expected, "input {input}");
                    if input == 0.0 || input == -0.0 {
                        assert_eq!(
                            actual.to_bits(),
                            0.0f64.to_bits(),
                            "signed zero for {input}"
                        );
                    }
                }
                other => panic!("expected f64, got {other:?}"),
            }
        }
    }

    #[test]
    fn b1_wide_object_frontier_is_bounded() {
        let mut entries = Vec::new();
        for index in 0..10_000i64 {
            entries.push((
                format!("k{index:05}"),
                JsonValue::Number(JsonNumber::I64(index)),
            ));
        }
        let values = FieldValues::Single(FieldValue::Json(JsonValue::Object(entries)));
        let limits = SegmentLimits::default();
        reset_dfs_frame_high_water();
        let occurrences = extract_field_paths(0, &values, &limits).unwrap();
        assert_eq!(occurrences.len(), 10_001);
        let high_water = dfs_frame_high_water();
        assert!(high_water <= 1, "frontier high-water {high_water}");
        let last = occurrences
            .iter()
            .find(|occ| occ.path == [JsonPathComponent::Member("k09999".into())])
            .unwrap();
        assert_eq!(last.node, JsonNode::I64(9_999));
    }

    #[test]
    fn b1_wide_array_frontier_is_bounded() {
        let values = FieldValues::Single(FieldValue::Json(JsonValue::Array(
            (0..10_000i64)
                .map(|index| JsonValue::Number(JsonNumber::I64(index)))
                .collect(),
        )));
        let limits = SegmentLimits::default();
        reset_dfs_frame_high_water();
        let occurrences = extract_field_paths(0, &values, &limits).unwrap();
        assert_eq!(occurrences.len(), 10_001);
        let high_water = dfs_frame_high_water();
        assert!(high_water <= 1, "frontier high-water {high_water}");
        assert!(
            occurrences
                .iter()
                .any(|occ| occ.path == [JsonPathComponent::Index(0)])
        );
        assert!(
            occurrences
                .iter()
                .any(|occ| occ.path == [JsonPathComponent::Index(9_999)])
        );
    }

    #[test]
    fn b1_nested_mixed_matches_manual_expected() {
        let value = JsonValue::Object(vec![
            (
                "a".into(),
                JsonValue::Array(vec![
                    JsonValue::Object(vec![
                        ("b".into(), JsonValue::Number(JsonNumber::I64(1))),
                        ("c".into(), JsonValue::Null),
                    ]),
                    JsonValue::Array(vec![]),
                ]),
            ),
            (
                "é".into(),
                JsonValue::Object(vec![("d".into(), JsonValue::Bool(true))]),
            ),
            ("e".into(), JsonValue::Null),
        ]);
        let values = FieldValues::Single(FieldValue::Json(value));
        let occurrences = extract_field_paths(0, &values, &SegmentLimits::default()).unwrap();
        let m = |name: &str| JsonPathComponent::Member(name.to_owned());
        let expected = vec![
            (vec![], JsonNode::Object),
            (vec![m("a")], JsonNode::Array),
            (vec![m("a"), JsonPathComponent::Index(0)], JsonNode::Object),
            (
                vec![m("a"), JsonPathComponent::Index(0), m("b")],
                JsonNode::I64(1),
            ),
            (
                vec![m("a"), JsonPathComponent::Index(0), m("c")],
                JsonNode::Null,
            ),
            (vec![m("a"), JsonPathComponent::Index(1)], JsonNode::Array),
            (vec![m("e")], JsonNode::Null),
            (vec![m("é")], JsonNode::Object),
            (vec![m("é"), m("d")], JsonNode::Bool(true)),
        ];
        let actual: Vec<(Vec<JsonPathComponent>, JsonNode)> = occurrences
            .into_iter()
            .map(|occ| (occ.path, occ.node))
            .collect();
        assert_eq!(actual, expected);
    }

    #[test]
    fn b1_multi_root_prefixes_and_duplicates() {
        let values = FieldValues::Multi(vec![
            FieldValue::Json(JsonValue::Object(vec![(
                "x".into(),
                JsonValue::Number(JsonNumber::I64(1)),
            )])),
            FieldValue::Json(JsonValue::Array(vec![JsonValue::Null])),
        ]);
        let occurrences = extract_field_paths(0, &values, &SegmentLimits::default()).unwrap();
        assert!(occurrences.iter().any(|occ| {
            occ.path
                == [
                    JsonPathComponent::Index(0),
                    JsonPathComponent::Member("x".into()),
                ]
                && occ.node == JsonNode::I64(1)
        }));
        assert!(occurrences.iter().any(|occ| {
            occ.path == [JsonPathComponent::Index(1), JsonPathComponent::Index(0)]
                && occ.node == JsonNode::Null
        }));
        let duplicate = FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![
            ("a".into(), JsonValue::Null),
            ("a".into(), JsonValue::Null),
        ])));
        assert!(extract_field_paths(0, &duplicate, &SegmentLimits::default()).is_err());
    }

    #[test]
    fn b1_depth_boundary_at_and_over() {
        let limits = SegmentLimits::default();
        let depth = effective_depth(&limits);
        let mut at = JsonValue::Null;
        for _ in 0..depth {
            at = JsonValue::Array(vec![at]);
        }
        extract_field_paths(0, &FieldValues::Single(FieldValue::Json(at)), &limits).unwrap();
        let mut over = JsonValue::Null;
        for _ in 0..=depth {
            over = JsonValue::Array(vec![over]);
        }
        assert!(matches!(
            extract_field_paths(0, &FieldValues::Single(FieldValue::Json(over)), &limits),
            Err(SegmentError::LimitExceeded { .. })
        ));
        let mut obj = JsonValue::Null;
        for _ in 0..depth {
            obj = JsonValue::Object(vec![("a".into(), obj)]);
        }
        extract_field_paths(0, &FieldValues::Single(FieldValue::Json(obj)), &limits).unwrap();
        let mut obj_over = JsonValue::Null;
        for _ in 0..=depth {
            obj_over = JsonValue::Object(vec![("a".into(), obj_over)]);
        }
        assert!(matches!(
            extract_field_paths(0, &FieldValues::Single(FieldValue::Json(obj_over)), &limits),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn b1_member_bytes_and_array_boundaries() {
        let limits = SegmentLimits::default();
        let accepted = "x".repeat(MAX_JSON_PATH_MEMBER_BYTES);
        let value = FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![(
            accepted,
            JsonValue::Null,
        )])));
        extract_field_paths(0, &value, &limits).unwrap();

        let rejected = "x".repeat(MAX_JSON_PATH_MEMBER_BYTES + 1);
        let value = FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![(
            rejected,
            JsonValue::Null,
        )])));
        assert!(matches!(
            extract_field_paths(0, &value, &limits),
            Err(SegmentError::LimitExceeded { .. })
        ));

        let array_limits = SegmentLimits::default().with_max_array_elements_for_test(3);
        let at = FieldValues::Single(FieldValue::Json(JsonValue::Array(vec![
            JsonValue::Null,
            JsonValue::Null,
            JsonValue::Null,
        ])));
        extract_field_paths(0, &at, &array_limits).unwrap();
        let over = FieldValues::Single(FieldValue::Json(JsonValue::Array(vec![
            JsonValue::Null,
            JsonValue::Null,
            JsonValue::Null,
            JsonValue::Null,
        ])));
        assert!(matches!(
            extract_field_paths(0, &over, &array_limits),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn b1_wide_shallow_survives_modest_frontier_budget() {
        let mut entries = Vec::new();
        for index in 0..5_000i64 {
            entries.push((
                format!("k{index:05}"),
                JsonValue::Number(JsonNumber::I64(index)),
            ));
        }
        let values = FieldValues::Single(FieldValue::Json(JsonValue::Object(entries)));
        let frame_bytes = std::mem::size_of::<DfsFrame<'_>>() as u64;
        // A charged pending-child frontier would need `5000 * frame_bytes`; only
        // one cursor frame is retained. The budget must still cover the separate
        // retained-occurrence charge, which dominates the same ceiling.
        let modest = SegmentLimits::default().with_max_single_allocation(1_000_000);
        assert!(5_000 * frame_bytes <= 1_000_000);
        reset_dfs_frame_high_water();
        let occurrences = extract_field_paths(0, &values, &modest).unwrap();
        assert_eq!(occurrences.len(), 5_001);
        assert!(dfs_frame_high_water() <= 1, "frontier high-water");

        // The retained-occurrence ceiling is still enforced separately.
        let starved = SegmentLimits::default().with_max_single_allocation(1_024);
        assert!(matches!(
            extract_field_paths(0, &values, &starved),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn b1_stack_capacity_preflight() {
        let value = JsonValue::Null;
        let frame_bytes = std::mem::size_of::<DfsFrame<'_>>() as u64;
        let make = || DfsFrame {
            parent_len: 0,
            next_child: 0,
            value: &value,
        };

        let mut probe: Vec<DfsFrame<'_>> = Vec::new();
        probe.try_reserve(1).unwrap();
        let growth_capacity = probe.capacity() as u64;
        drop(probe);

        let mut stack: Vec<DfsFrame<'_>> = Vec::new();
        let exact =
            SegmentLimits::default().with_max_single_allocation(growth_capacity * frame_bytes);
        push_frame(&mut stack, make(), &exact).unwrap();
        assert_eq!(stack.len(), 1);

        let mut stack: Vec<DfsFrame<'_>> = Vec::new();
        let below =
            SegmentLimits::default().with_max_single_allocation(growth_capacity * frame_bytes - 1);
        let error =
            push_frame(&mut stack, make(), &below).expect_err("one byte below capacity must fail");
        assert!(matches!(error, SegmentError::LimitExceeded { .. }));
        assert!(stack.is_empty());
    }

    struct B1Rng(u64);

    impl B1Rng {
        fn next_u64(&mut self) -> u64 {
            let mut x = self.0;
            x ^= x >> 12;
            x ^= x << 25;
            x ^= x >> 27;
            self.0 = x;
            x.wrapping_mul(0x2545_F491_4F6C_DD1D)
        }

        fn below(&mut self, n: u64) -> u64 {
            if n == 0 { 0 } else { self.next_u64() % n }
        }
    }

    fn b1_scalar(rng: &mut B1Rng) -> JsonValue {
        match rng.below(5) {
            0 => JsonValue::Null,
            1 => JsonValue::Bool(rng.below(2) == 1),
            2 => JsonValue::Number(JsonNumber::I64(rng.below(9) as i64 - 4)),
            3 => JsonValue::Number(JsonNumber::F64(rng.below(9) as f64 - 4.0)),
            _ => JsonValue::String(format!("s{}", rng.below(5))),
        }
    }

    fn b1_generate(rng: &mut B1Rng, depth: u32, budget: &mut u32) -> JsonValue {
        if *budget == 0 || depth == 0 {
            return b1_scalar(rng);
        }
        *budget -= 1;
        match rng.below(5) {
            1 => {
                let count = rng.below(33) as usize;
                JsonValue::Array(
                    (0..count)
                        .map(|_| b1_generate(rng, depth - 1, budget))
                        .collect(),
                )
            }
            2 => {
                let count = rng.below(33) as usize;
                let mut entries = Vec::new();
                for index in 0..count {
                    entries.push((format!("k{index}"), b1_generate(rng, depth - 1, budget)));
                }
                JsonValue::Object(entries)
            }
            _ => b1_scalar(rng),
        }
    }

    fn b1_reference_walk(
        value: &JsonValue,
        path: &mut Vec<JsonPathComponent>,
        out: &mut Vec<(Vec<JsonPathComponent>, JsonNode)>,
    ) {
        out.push((path.clone(), node_of(value)));
        match value {
            JsonValue::Array(values) => {
                for (index, child) in values.iter().enumerate() {
                    path.push(JsonPathComponent::Index(index as u64));
                    b1_reference_walk(child, path, out);
                    path.pop();
                }
            }
            JsonValue::Object(entries) => {
                for (key, child) in entries {
                    path.push(JsonPathComponent::Member(key.clone()));
                    b1_reference_walk(child, path, out);
                    path.pop();
                }
            }
            _ => {}
        }
    }

    #[test]
    fn b1_property_vs_recursive_reference() {
        let mut rng = B1Rng(0xB1_2026);
        for case in 0..250 {
            let mut budget = 512u32;
            let value = b1_generate(&mut rng, 8, &mut budget);
            let values = FieldValues::Single(FieldValue::Json(value.clone()));
            let occurrences = match extract_field_paths(0, &values, &SegmentLimits::default()) {
                Ok(occurrences) => occurrences,
                Err(error) => panic!("case {case} (seed 0xB1_2026) failed: {error}"),
            };
            let mut expected = Vec::new();
            b1_reference_walk(&value, &mut Vec::new(), &mut expected);
            expected.sort_by(|a, b| a.0.cmp(&b.0));
            let actual: Vec<(Vec<JsonPathComponent>, JsonNode)> = occurrences
                .into_iter()
                .map(|occ| (occ.path, occ.node))
                .collect();
            assert_eq!(actual, expected, "case {case} (seed 0xB1_2026)");
        }
    }
}
