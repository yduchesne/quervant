//! Bounded segment reader over the real `Directory` seam (Phase E).
//!
//! The reader validates the full envelope, exposes typed accessors, and never
//! publishes a generation or implements PR 6 lifecycle.
//!
//! # Verified immutable state
//!
//! Opening a segment validates the whole container: SHA-256 envelope, per-section
//! digests, feature/section agreement, column geometry and every decoded metadata
//! structure. That validation produces a `VerifiedSegmentState` which is
//! immutable, `Send + Sync` and shareable through `Arc` (architecture
//! `VERIFIED_SEGMENT_READER_REUSE.md` §13 G1). A [`SegmentReader`] is a
//! **query-local** handle over that shared state: it owns only the lazily decoded
//! `Rc`/`RefCell` caches for stored records, document keys and the live bitmap.
//!
//! A `ReaderSnapshot` may retain one verified state per segment for the lifetime
//! of the snapshot. Reuse never skips verification for new bytes: state is only
//! published after the same parser/validator ran against the snapshot's exact
//! immutable `Arc<Vec<u8>>` allocation.

use std::cell::RefCell;
use std::ops::Range;
use std::rc::Rc;
use std::sync::{Arc, OnceLock};

use quervant_objectstore::ContentDescriptor;

use crate::contract::document::DocumentKey;

use super::bounds::{GeoBounds, TimeBounds};
use super::column::{ColumnGeometry, ColumnReader, column_geometry_allowance};
use super::dictionary::{DictionaryEntry, DictionaryReader};
use super::error::{SegmentError, SegmentResult};
use super::format::{
    ByteReader, ContainerKind, ContainerView, FEATURE_FIELD_NORMS, FEATURE_JSON_PATHS,
    FEATURE_SPATIAL_POINTS, SectionEntry, SectionKind, parse_container, reserve_exact_vec,
};
use super::json_paths::{JsonDocOffset, JsonPathDirectory, JsonPathsReader};
use super::limits::SegmentLimits;
use super::metadata::{
    MetadataBudget, MetadataMeter, MetadataReservation, accumulate, capacity_bytes, count_bound,
    element_bytes,
};
use super::norms::{FieldNorms, FieldNormsReader};
use super::postings::PostingsReader;
use super::remap::DocRemap;
use super::schema::{CodecField, CodecSchema};
use super::spatial::{SpatialField, SpatialIndex, SpatialNode};
use super::stored::{
    StoredRecord, decode_stored, decode_stored_from_validated_offsets, decode_stored_selected,
    validate_stored_and_capture_offsets,
};
use crate::storage::{Directory, ReadHandle, StorageKey};

/// Fallibly copy a validated slice into a retained vector.
///
/// The capacity is reserved explicitly before any element is copied, so an
/// allocation failure on the cached construction path yields the typed
/// [`SegmentError::LimitExceeded`] that routes to the verified uncached fallback
/// instead of aborting the process. `extend_from_slice` cannot grow past the
/// reserved capacity.
fn copy_slice_fallible<T: Copy>(
    source: &[T],
    limits: &SegmentLimits,
    meter: &mut Option<&mut MetadataMeter>,
) -> SegmentResult<Vec<T>> {
    meter
        .as_deref_mut()
        .map_or(Ok(()), |meter| meter.charge_vec::<T>(source.len() as u64))?;
    let mut copy: Vec<T> = Vec::new();
    reserve_exact_vec(&mut copy, source.len(), limits)?;
    copy.extend_from_slice(source);
    Ok(copy)
}

/// Minimum encoded width of one schema field body.
const SCHEMA_MIN_FIELD_BYTES: u64 = 13;
/// Minimum encoded width of one dictionary field header.
const DICTIONARY_MIN_FIELD_BYTES: u64 = 12;
/// Minimum encoded width of one dictionary term entry.
const DICTIONARY_MIN_TERM_BYTES: u64 = 26;
/// Fixed per-field norms header width (id, declared total, declared nonzero).
const NORMS_MIN_FIELD_HEADER_BYTES: u64 = 20;
/// Minimum encoded width of one JSON-path occurrence.
const JSON_PATH_MIN_OCCURRENCE_BYTES: u64 = 10;
/// Fixed per-field spatial header width (`field_id`, `point_count`, `root`).
const SPATIAL_MIN_FIELD_BYTES: u64 = 20;
/// Fixed width of one encoded spatial node.
const SPATIAL_MIN_NODE_BYTES: u64 = 77;
/// Fixed width of one encoded geo-bounds entry.
const GEO_BOUNDS_ENTRY_LEN: usize = 55;

/// A verified offset certificate for one immutable section body.
///
/// `ends` has `count + 1` relative byte positions. `ends[i]` is the start of
/// record `i`; `ends[i + 1]` is its exclusive end. The RAII reservation keeps the
/// retained vector charged for as long as its owning verified state survives.
struct ValidatedOffsets {
    ends: Vec<u64>,
    _reservation: MetadataReservation,
}

impl ValidatedOffsets {
    /// Checked record range for `doc_id`, converted to local slice indices.
    fn range(&self, doc_id: u64) -> SegmentResult<Range<usize>> {
        let count = self
            .ends
            .len()
            .checked_sub(1)
            .ok_or(SegmentError::Corrupt {
                context: "validated offsets",
                detail: "offset directory is empty".to_owned(),
            })?;
        let count_u64 = u64::try_from(count).map_err(|_| SegmentError::Corrupt {
            context: "validated offsets",
            detail: "offset count is not representable".to_owned(),
        })?;
        if doc_id >= count_u64 {
            return Err(SegmentError::Corrupt {
                context: "validated offsets",
                detail: "doc id out of range".to_owned(),
            });
        }
        let index = usize::try_from(doc_id).map_err(|_| SegmentError::Corrupt {
            context: "validated offsets",
            detail: "doc id out of range".to_owned(),
        })?;
        let start = self.ends.get(index).copied().ok_or(SegmentError::Corrupt {
            context: "validated offsets",
            detail: "start offset out of range".to_owned(),
        })?;
        let end = self
            .ends
            .get(index + 1)
            .copied()
            .ok_or(SegmentError::Corrupt {
                context: "validated offsets",
                detail: "end offset out of range".to_owned(),
            })?;
        if start > end {
            return Err(SegmentError::Corrupt {
                context: "validated offsets",
                detail: "record offsets are descending".to_owned(),
            });
        }
        let start = usize::try_from(start).map_err(|_| SegmentError::Corrupt {
            context: "validated offsets",
            detail: "start offset is not representable".to_owned(),
        })?;
        let end = usize::try_from(end).map_err(|_| SegmentError::Corrupt {
            context: "validated offsets",
            detail: "end offset is not representable".to_owned(),
        })?;
        Ok(start..end)
    }
}

/// Reserve, collect, validate and finalize one optional offset directory.
fn build_validated_offsets<F>(
    section: &[u8],
    count: u64,
    limits: &SegmentLimits,
    budget: &Arc<MetadataBudget>,
    validate: F,
) -> SegmentResult<ValidatedOffsets>
where
    F: FnOnce(&mut Vec<u64>) -> SegmentResult<()>,
{
    let entries = count.checked_add(1).ok_or(SegmentError::LimitExceeded {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    limits.check_alloc::<u64>(entries)?;
    limits.check_entries(count)?;
    let allowance = element_bytes::<u64>(entries)?;
    let meter = MetadataMeter::reserve(budget, allowance)?;
    let entries_usize = usize::try_from(entries).map_err(|_| SegmentError::LimitExceeded {
        limit: limits.max_single_allocation(),
        requested: entries,
    })?;
    let mut offsets: Vec<u64> = Vec::new();
    offsets
        .try_reserve_exact(entries_usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: entries,
        })?;
    validate(&mut offsets)?;
    let terminal = u64::try_from(section.len()).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    if offsets.len() != entries_usize
        || offsets.first().copied() != Some(10)
        || offsets.last().copied() != Some(terminal)
    {
        return Err(SegmentError::Corrupt {
            context: "validated offsets",
            detail: "offset directory has inconsistent boundaries".to_owned(),
        });
    }
    if offsets.windows(2).any(|pair| pair[0] > pair[1]) {
        return Err(SegmentError::Corrupt {
            context: "validated offsets",
            detail: "offset directory is not monotonic".to_owned(),
        });
    }
    let measured = capacity_bytes::<u64>(offsets.capacity())?;
    let reservation = meter.finalize(measured)?;
    Ok(ValidatedOffsets {
        ends: offsets,
        _reservation: reservation,
    })
}

#[cfg(test)]
thread_local! {
    static FAIL_STORED_DIRECTORY_BUILD: std::cell::Cell<bool> =
        const { std::cell::Cell::new(false) };
}

#[cfg(test)]
pub(crate) fn set_fail_stored_directory_build(value: bool) {
    FAIL_STORED_DIRECTORY_BUILD.with(|flag| flag.set(value));
}

#[cfg(test)]
fn maybe_fail_stored_directory_build() {
    if FAIL_STORED_DIRECTORY_BUILD.with(std::cell::Cell::get) {
        panic!("injected stored directory initialization panic");
    }
}

fn try_build_stored_directory(
    shared: &VerifiedSegmentState,
    body: &[u8],
    budget: &Arc<MetadataBudget>,
) -> SegmentResult<ValidatedOffsets> {
    #[cfg(test)]
    maybe_fail_stored_directory_build();
    build_validated_offsets(body, shared.doc_count, &shared.limits, budget, |offsets| {
        validate_stored_and_capture_offsets(&shared.schema, body, &shared.limits, offsets)
    })
}

fn try_build_key_directory(
    shared: &VerifiedSegmentState,
    body: &[u8],
    budget: &Arc<MetadataBudget>,
) -> SegmentResult<ValidatedOffsets> {
    build_validated_offsets(body, shared.doc_count, &shared.limits, budget, |offsets| {
        validate_doc_keys_and_capture_offsets(shared, body, offsets)
    })
}

fn position_u64(reader: &ByteReader<'_>) -> SegmentResult<u64> {
    u64::try_from(reader.position()).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::MAX,
        requested: u64::MAX,
    })
}

/// The fully validated, immutable, shareable state of one segment.
///
/// Decoded payload fields are immutable after construction and `Send + Sync`.
/// The two validated-offset cells are monotonic lazy memoization, populated only
/// on a metadata-admitted state. The only query-mutable state in the engine —
/// the stored/document-key/live-doc caches — stays query-local in
/// [`SegmentReader`].
pub(crate) struct VerifiedSegmentState {
    bytes: Arc<Vec<u8>>,
    limits: SegmentLimits,
    doc_count: u64,
    sections: Vec<SectionEntry>,
    required: Vec<(u16, u16)>,
    optional: Vec<(u16, u16)>,
    schema: CodecSchema,
    remap: DocRemap,
    dictionary: Option<DictionaryReader>,
    norms: Option<FieldNormsReader>,
    time_bounds: Option<TimeBounds>,
    geo_bounds: Vec<GeoBounds>,
    json_paths: Option<Arc<JsonPathDirectory>>,
    spatial: Option<SpatialIndex>,
    /// Fully validated per-field COLUMNS geometry, retained only when the
    /// snapshot-scoped candidate was budget-admitted.
    column_geometry: Option<ColumnGeometry>,
    /// Lazy validated STORED offsets, only on a metadata-admitted state.
    stored_offsets: OnceLock<Option<ValidatedOffsets>>,
    /// Lazy validated DOC_KEYS offsets, only on a metadata-admitted state.
    key_offsets: OnceLock<Option<ValidatedOffsets>>,
    /// Metadata account used only to retain optional lazy offset directories.
    access_budget: Option<Arc<MetadataBudget>>,
    /// Retained-metadata reservation, released when the last `Arc` drops.
    metadata: Option<MetadataReservation>,
}

/// Decoded (but not yet owned) immutable metadata of one segment.
struct DecodedMetadata {
    doc_count: u64,
    sections: Vec<SectionEntry>,
    required: Vec<(u16, u16)>,
    optional: Vec<(u16, u16)>,
    schema: CodecSchema,
    remap: DocRemap,
    dictionary: Option<DictionaryReader>,
    norms: Option<FieldNormsReader>,
    time_bounds: Option<TimeBounds>,
    geo_bounds: Vec<GeoBounds>,
    json_paths: Option<Arc<JsonPathDirectory>>,
    spatial: Option<SpatialIndex>,
    column_geometry: Option<ColumnGeometry>,
}

/// A validated, bounded reader over an immutable segment container.
pub struct SegmentReader {
    shared: Arc<VerifiedSegmentState>,
    stored_cache: RefCell<Option<Rc<Vec<StoredRecord>>>>,
    doc_keys_cache: RefCell<Option<Rc<Vec<DocumentKey>>>>,
    live_docs_cache: RefCell<Option<Rc<Vec<bool>>>>,
}

impl VerifiedSegmentState {
    /// Validate `bytes` and build the shared state without metadata accounting.
    fn validate(bytes: Arc<Vec<u8>>, limits: SegmentLimits) -> SegmentResult<Arc<Self>> {
        let file_len = bytes.len() as u64;
        if file_len > limits.accepted_segment_bytes() {
            return Err(SegmentError::LimitExceeded {
                limit: limits.accepted_segment_bytes(),
                requested: file_len,
            });
        }
        let view = parse_container(&bytes, &limits)?;
        let decoded = decode_metadata(&view, limits, &mut None)?;
        drop(view);
        Ok(Arc::new(Self::from_decoded(bytes, limits, decoded)))
    }

    /// Validate `bytes` and build a candidate state charged against `budget`.
    ///
    /// Returns `Ok(None)` when the candidate is not admissible — a zero cap, a
    /// rejected candidate reservation, a fallible allocation failure or a
    /// measured charge above the reserved allowance. The caller must then use the
    /// independently validated uncached reader; no state is published.
    ///
    /// Genuine corruption (digest, feature, structure, schema, metadata) is
    /// returned as the original typed error and is never converted into a
    /// fallback: those errors are not optional-capacity failures.
    pub(crate) fn build_cached(
        bytes: Arc<Vec<u8>>,
        limits: SegmentLimits,
        budget: &Arc<MetadataBudget>,
    ) -> SegmentResult<Option<Arc<Self>>> {
        match Self::try_build_cached(bytes, limits, budget) {
            Ok(state) => Ok(Some(state)),
            // Resource/capacity bound: the authoritative uncached path re-raises
            // the identical typed error when the input genuinely exceeds it.
            Err(SegmentError::LimitExceeded { .. }) => Ok(None),
            Err(other) => Err(other),
        }
    }

    fn try_build_cached(
        bytes: Arc<Vec<u8>>,
        limits: SegmentLimits,
        budget: &Arc<MetadataBudget>,
    ) -> SegmentResult<Arc<Self>> {
        let file_len = bytes.len() as u64;
        if file_len > limits.accepted_segment_bytes() {
            return Err(SegmentError::LimitExceeded {
                limit: limits.accepted_segment_bytes(),
                requested: file_len,
            });
        }
        // The parser itself allocates the retained section/feature vectors, so the
        // whole parser-side upper bound is reserved before it runs.
        let mut meter = MetadataMeter::reserve(budget, parser_allowance(&limits)?)?;
        let view = parse_container(&bytes, &limits)?;
        // Now the validated section lengths are available: reserve the remaining
        // conservative upper bound *before* any metadata decode.
        meter.extend(decode_allowance(&view)?)?;
        let decoded = {
            let mut meter_slot = Some(&mut meter);
            decode_metadata(&view, limits, &mut meter_slot)?
        };
        drop(view);
        let measured = decoded.measured_charge()?;
        let candidate = Self::from_decoded(bytes, limits, decoded);
        let reservation = meter.finalize(measured)?;
        Ok(Arc::new(
            candidate
                .with_metadata(reservation)
                .with_access_budget(Arc::clone(budget)),
        ))
    }

    fn from_decoded(bytes: Arc<Vec<u8>>, limits: SegmentLimits, decoded: DecodedMetadata) -> Self {
        Self {
            bytes,
            limits,
            doc_count: decoded.doc_count,
            sections: decoded.sections,
            required: decoded.required,
            optional: decoded.optional,
            schema: decoded.schema,
            remap: decoded.remap,
            dictionary: decoded.dictionary,
            norms: decoded.norms,
            time_bounds: decoded.time_bounds,
            geo_bounds: decoded.geo_bounds,
            json_paths: decoded.json_paths,
            spatial: decoded.spatial,
            column_geometry: decoded.column_geometry,
            stored_offsets: OnceLock::new(),
            key_offsets: OnceLock::new(),
            access_budget: None,
            metadata: None,
        }
    }

    fn with_metadata(mut self, reservation: MetadataReservation) -> Self {
        self.metadata = Some(reservation);
        self
    }

    fn with_access_budget(mut self, budget: Arc<MetadataBudget>) -> Self {
        self.access_budget = Some(budget);
        self
    }

    fn body(&self, kind: SectionKind) -> Option<&[u8]> {
        let entry = self.sections.iter().find(|entry| entry.kind == kind)?;
        let start = entry.offset as usize;
        let end = start + entry.length as usize;
        self.bytes.get(start..end)
    }

    /// Test-only witness that a metered candidate retained validated geometry.
    #[cfg(test)]
    pub(crate) const fn has_column_geometry(&self) -> bool {
        self.column_geometry.is_some()
    }

    /// Test-only identity of the retained geometry table.
    #[cfg(test)]
    pub(crate) fn column_geometry_ptr(&self) -> Option<usize> {
        self.column_geometry
            .as_ref()
            .map(ColumnGeometry::buffer_ptr)
    }

    /// Test-only state of the STORED offset cell: `None` uninitialized,
    /// `Some(true)` ready, `Some(false)` disabled.
    #[cfg(test)]
    pub(crate) fn stored_offsets_state(&self) -> Option<bool> {
        self.stored_offsets.get().map(Option::is_some)
    }

    /// Test-only state of the DOC_KEYS offset cell.
    #[cfg(test)]
    pub(crate) fn key_offsets_state(&self) -> Option<bool> {
        self.key_offsets.get().map(Option::is_some)
    }

    #[cfg(test)]
    pub(crate) fn stored_offsets_ptr(&self) -> Option<usize> {
        self.stored_offsets
            .get()
            .and_then(|offsets| offsets.as_ref())
            .map(|offsets| offsets.ends.as_ptr() as usize)
    }

    #[cfg(test)]
    pub(crate) fn key_offsets_ptr(&self) -> Option<usize> {
        self.key_offsets
            .get()
            .and_then(|offsets| offsets.as_ref())
            .map(|offsets| offsets.ends.as_ptr() as usize)
    }

    #[cfg(test)]
    pub(crate) fn access_budget_used(&self) -> Option<u64> {
        self.access_budget.as_ref().map(|budget| budget.used())
    }

    #[cfg(test)]
    pub(crate) fn has_access_budget(&self) -> bool {
        self.access_budget.is_some()
    }
}

impl SegmentReader {
    /// Parse and validate a segment from owned bytes.
    pub fn open(bytes: Vec<u8>, limits: SegmentLimits) -> SegmentResult<Self> {
        let shared = VerifiedSegmentState::validate(Arc::new(bytes), limits)?;
        Ok(Self::from_shared(shared))
    }

    /// Read an entire segment from a `Directory` with bounded positional reads.
    pub fn open_directory(
        directory: &dyn Directory,
        key: &StorageKey,
        limits: SegmentLimits,
    ) -> SegmentResult<Self> {
        let bytes = read_all(directory, key, &limits)?;
        Self::open(bytes, limits)
    }

    /// Create a query-local reader over already verified shared state.
    ///
    /// All three lazy caches start empty for this reader; the shared state is
    /// never mutated.
    pub(crate) fn from_shared(shared: Arc<VerifiedSegmentState>) -> Self {
        Self {
            shared,
            stored_cache: RefCell::new(None),
            doc_keys_cache: RefCell::new(None),
            live_docs_cache: RefCell::new(None),
        }
    }

    /// The shared verified state (test-only identity witness).
    #[cfg(test)]
    pub(crate) fn shared_state(&self) -> &Arc<VerifiedSegmentState> {
        &self.shared
    }

    /// Verify the whole file (including trailer) against a trusted descriptor.
    pub fn verify_content_descriptor(&self, expected: &ContentDescriptor) -> SegmentResult<()> {
        verify_bytes(&self.shared.bytes, expected)
    }

    /// Declared document count.
    #[must_use]
    pub fn doc_count(&self) -> u64 {
        self.shared.doc_count
    }

    /// Canonical schema.
    #[must_use]
    pub fn schema(&self) -> &CodecSchema {
        &self.shared.schema
    }

    /// Doc-id remap.
    #[must_use]
    pub fn remap(&self) -> &DocRemap {
        &self.shared.remap
    }

    /// Raw container bytes.
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.shared.bytes
    }

    /// Required features.
    #[must_use]
    pub fn required_features(&self) -> &[(u16, u16)] {
        &self.shared.required
    }

    /// Optional features.
    #[must_use]
    pub fn optional_features(&self) -> &[(u16, u16)] {
        &self.shared.optional
    }

    /// Parsed section entries.
    #[must_use]
    pub fn sections(&self) -> &[SectionEntry] {
        &self.shared.sections
    }

    /// The term dictionary, if present.
    #[must_use]
    pub fn dictionary(&self) -> Option<&DictionaryReader> {
        self.shared.dictionary.as_ref()
    }

    /// Persistent BM25 field norms, or `None` for a legacy segment.
    #[must_use]
    pub fn field_norms(&self) -> Option<&FieldNormsReader> {
        self.shared.norms.as_ref()
    }

    /// Temporal bounds, if present.
    #[must_use]
    pub fn time_bounds(&self) -> Option<&TimeBounds> {
        self.shared.time_bounds.as_ref()
    }

    /// Geographic bounds.
    #[must_use]
    pub fn geo_bounds(&self) -> &[GeoBounds] {
        &self.shared.geo_bounds
    }

    /// The immutable spatial KD trees, or `None` for a legacy segment.
    #[must_use]
    pub fn spatial(&self) -> Option<&SpatialIndex> {
        self.shared.spatial.as_ref()
    }

    /// Lazily decode and cache all stored records.
    pub fn stored(&self) -> SegmentResult<Rc<Vec<StoredRecord>>> {
        if let Some(records) = self.stored_cache.borrow().as_ref() {
            return Ok(Rc::clone(records));
        }
        let body = self
            .body(SectionKind::Stored)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::Stored as u16,
            })?;
        let records = Rc::new(decode_stored(
            &self.shared.schema,
            body,
            &self.shared.limits,
        )?);
        *self.stored_cache.borrow_mut() = Some(Rc::clone(&records));
        Ok(records)
    }

    /// Decode one document's stored record.
    pub fn stored_doc(&self, doc_id: u64) -> SegmentResult<StoredRecord> {
        let records = self.stored()?;
        records
            .get(doc_id as usize)
            .cloned()
            .ok_or(SegmentError::Corrupt {
                context: "stored",
                detail: "doc id out of range".to_owned(),
            })
    }

    /// Whether this query-local reader holds a fully decoded stored cache.
    ///
    /// Test-only witness for the Phase 3 requirement that the selective accessor
    /// never installs an all-documents cache.
    #[cfg(test)]
    pub(crate) fn stored_cache_is_populated(&self) -> bool {
        self.stored_cache.borrow().is_some()
    }

    /// Decode only the selected physical stored records (PR 15E Phase 3).
    ///
    /// `ascending_unique_ids` must be strictly increasing physical doc ids. The
    /// STORED section is scanned exactly once and every record — selected or not —
    /// is fully validated; only the selected records are materialized.
    ///
    /// This accessor is query-local: it never populates `stored_cache` and never
    /// writes to the shared verified state. If a previous caller already performed a
    /// full decode in this reader, the requested records are cloned from that cache.
    pub(crate) fn stored_docs_selected(
        &self,
        ascending_unique_ids: &[u64],
    ) -> SegmentResult<Vec<(u64, StoredRecord)>> {
        let cached = self.stored_cache.borrow().as_ref().map(Rc::clone);
        if let Some(records) = cached {
            let mut selected: Vec<(u64, StoredRecord)> = Vec::new();
            selected
                .try_reserve_exact(ascending_unique_ids.len())
                .map_err(|_| SegmentError::LimitExceeded {
                    limit: self.shared.limits.max_single_allocation(),
                    requested: ascending_unique_ids.len() as u64,
                })?;
            for doc_id in ascending_unique_ids {
                let index = usize::try_from(*doc_id).map_err(|_| SegmentError::Corrupt {
                    context: "stored",
                    detail: "doc id out of range".to_owned(),
                })?;
                let record = records.get(index).cloned().ok_or(SegmentError::Corrupt {
                    context: "stored",
                    detail: "doc id out of range".to_owned(),
                })?;
                selected.push((*doc_id, record));
            }
            return Ok(selected);
        }
        let body = self
            .body(SectionKind::Stored)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::Stored as u16,
            })?;
        let shared = &self.shared;
        if let Some(budget) = &shared.access_budget {
            // Malformed/out-of-range selections must reach the original scanner
            // before any optional directory allocation, preserving error order.
            if ascending_unique_ids
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
                || ascending_unique_ids
                    .last()
                    .is_some_and(|last| *last >= shared.doc_count)
            {
                return decode_stored_selected(
                    &shared.schema,
                    body,
                    &shared.limits,
                    ascending_unique_ids,
                );
            }
            let directory = shared
                .stored_offsets
                .get_or_init(|| try_build_stored_directory(shared, body, budget).ok());
            if let Some(validated) = directory {
                return decode_stored_from_validated_offsets(
                    &shared.schema,
                    body,
                    &shared.limits,
                    &validated.ends,
                    ascending_unique_ids,
                );
            }
        }
        decode_stored_selected(&shared.schema, body, &shared.limits, ascending_unique_ids)
    }

    /// Lazily decode and cache the byte-exact logical document keys.
    ///
    /// This is a read-only accessor over the existing `DOC_KEYS` section; it does
    /// not alter the on-disk encoding.
    pub fn doc_keys(&self) -> SegmentResult<Rc<Vec<DocumentKey>>> {
        if let Some(keys) = self.doc_keys_cache.borrow().as_ref() {
            return Ok(Rc::clone(keys));
        }
        let keys = Rc::new(decode_doc_keys(self)?);
        *self.doc_keys_cache.borrow_mut() = Some(Rc::clone(&keys));
        Ok(keys)
    }

    /// The logical key for one physical doc id.
    pub fn doc_key(&self, doc_id: u64) -> SegmentResult<DocumentKey> {
        let index = usize::try_from(doc_id).map_err(|_| SegmentError::Corrupt {
            context: "doc keys",
            detail: "doc id out of range".to_owned(),
        })?;
        self.doc_keys()?
            .get(index)
            .cloned()
            .ok_or(SegmentError::Corrupt {
                context: "doc keys",
                detail: "doc id out of range".to_owned(),
            })
    }

    /// The logical key for one physical doc id without materializing every key.
    ///
    /// PR 15E Phase 5: when this query-local reader has no full key cache, the
    /// `DOC_KEYS` section is scanned once and only the requested key is owned; the
    /// scan still validates every entry and never installs the full cache. If a full
    /// decode already happened in this reader, the requested key is cloned from it.
    /// A pre-existing full cache is never replaced or invalidated.
    pub(crate) fn doc_key_selected(&self, doc_id: u64) -> SegmentResult<DocumentKey> {
        let cached = self.doc_keys_cache.borrow().as_ref().map(Rc::clone);
        if let Some(keys) = cached {
            let index = usize::try_from(doc_id).map_err(|_| SegmentError::Corrupt {
                context: "doc keys",
                detail: "doc id out of range".to_owned(),
            })?;
            return keys.get(index).cloned().ok_or(SegmentError::Corrupt {
                context: "doc keys",
                detail: "doc id out of range".to_owned(),
            });
        }
        let body = self
            .body(SectionKind::DocKeys)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::DocKeys as u16,
            })?;
        let shared = &self.shared;
        if let Some(budget) = &shared.access_budget {
            if doc_id >= shared.doc_count {
                return decode_doc_key_selected(self, doc_id);
            }
            let directory = shared
                .key_offsets
                .get_or_init(|| try_build_key_directory(shared, body, budget).ok());
            if let Some(validated) = directory {
                return decode_doc_key_at_validated_offset(body, validated, doc_id);
            }
        }
        decode_doc_key_selected(self, doc_id)
    }

    /// Whether this query-local reader holds a fully decoded document-key cache.
    ///
    /// Test-only witness for the Phase 5 requirement that the selective accessor
    /// never installs the all-documents cache.
    #[cfg(test)]
    pub(crate) fn doc_keys_cache_is_populated(&self) -> bool {
        self.doc_keys_cache.borrow().is_some()
    }

    /// Lazily decode and cache the live-doc bitmap.
    ///
    /// This is a read-only accessor over the existing `LIVE_DOCS` section; it does
    /// not alter the on-disk encoding.
    pub fn live_docs(&self) -> SegmentResult<Rc<Vec<bool>>> {
        if let Some(live) = self.live_docs_cache.borrow().as_ref() {
            return Ok(Rc::clone(live));
        }
        let live = Rc::new(decode_live_docs(self)?);
        *self.live_docs_cache.borrow_mut() = Some(Rc::clone(&live));
        Ok(live)
    }

    /// Whether one physical doc id is live.
    pub fn is_live(&self, doc_id: u64) -> SegmentResult<bool> {
        let index = usize::try_from(doc_id).map_err(|_| SegmentError::Corrupt {
            context: "live docs",
            detail: "doc id out of range".to_owned(),
        })?;
        self.live_docs()?
            .get(index)
            .copied()
            .ok_or(SegmentError::Corrupt {
                context: "live docs",
                detail: "doc id out of range".to_owned(),
            })
    }

    /// Decode one document's column value for a field.
    pub fn column_value(
        &self,
        field_id: u32,
        doc_id: u64,
    ) -> SegmentResult<Option<crate::contract::document::FieldValues>> {
        let Some(reader) = self.open_columns()? else {
            return Ok(None);
        };
        reader.value(field_id, doc_id)
    }

    /// Segment codec limits.
    #[must_use]
    pub(crate) fn limits(&self) -> &SegmentLimits {
        &self.shared.limits
    }

    /// Open a bounded reader over this segment's `JSON_PATHS` section.
    ///
    /// Returns `None` for a legacy segment without a JSON-path index. The
    /// validated offset directory is decoded once at segment open and reused for
    /// every query over this reader; no wire bytes are changed.
    pub(crate) fn open_json_paths(&self) -> SegmentResult<Option<JsonPathsReader<'_>>> {
        match &self.shared.json_paths {
            None => Ok(None),
            Some(directory) => {
                let body =
                    self.body(SectionKind::JsonPaths)
                        .ok_or(SegmentError::MissingSection {
                            kind: SectionKind::JsonPaths as u16,
                        })?;
                Ok(Some(JsonPathsReader::new(
                    body,
                    Arc::clone(directory),
                    self.shared.limits,
                )))
            }
        }
    }

    /// Open a bounded column reader over this segment's `COLUMNS` section.
    ///
    /// Returns `None` for a legacy segment without typed columns. When the
    /// snapshot-scoped verified state retained budget-admitted geometry, the
    /// reader borrows it directly and performs no structural reparse; otherwise
    /// this is the original fully validating standalone parser. This is a
    /// read-only accessor; callers that read many values should open once and
    /// reuse the reader. No wire bytes are changed.
    pub fn open_columns(&self) -> SegmentResult<Option<ColumnReader<'_>>> {
        let Some(body) = self.body(SectionKind::Columns) else {
            return Ok(None);
        };
        match &self.shared.column_geometry {
            Some(geometry) => Ok(Some(ColumnReader::from_validated_geometry(
                &self.shared.schema,
                body,
                &self.shared.limits,
                geometry,
            ))),
            None => Ok(Some(ColumnReader::open(
                &self.shared.schema,
                body,
                &self.shared.limits,
            )?)),
        }
    }

    /// Open a bounded postings reader for `(field, term)`.
    pub fn postings(&self, field_id: u32, term: &str) -> SegmentResult<Option<PostingsReader<'_>>> {
        let Some(dictionary) = &self.shared.dictionary else {
            return Ok(None);
        };
        let Some(entry) = dictionary.lookup(field_id, term) else {
            return Ok(None);
        };
        Ok(Some(self.postings_for_entry(entry)?))
    }

    /// Open a bounded postings reader for an already-resolved dictionary entry.
    ///
    /// This avoids a redundant linear dictionary lookup when a caller is already
    /// iterating `dictionary().field(field_id)` (for example BM25 field-length and
    /// document-frequency preparation). It is a read-only accessor; the posting
    /// encoding is unchanged.
    pub fn postings_for_entry(&self, entry: &DictionaryEntry) -> SegmentResult<PostingsReader<'_>> {
        let body = self
            .body(SectionKind::Postings)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::Postings as u16,
            })?;
        let start = entry.postings_offset as usize;
        let end =
            start
                .checked_add(entry.postings_length as usize)
                .ok_or(SegmentError::Corrupt {
                    context: "postings",
                    detail: "posting extent overflow".to_owned(),
                })?;
        let slice = body.get(start..end).ok_or(SegmentError::Corrupt {
            context: "postings",
            detail: "posting extent out of range".to_owned(),
        })?;
        let reader = PostingsReader::new(slice, self.shared.doc_count, &self.shared.limits)?;
        if reader.posting_doc_count() != entry.doc_freq {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "dictionary doc_freq does not match posting count".to_owned(),
            });
        }
        Ok(reader)
    }

    fn body(&self, kind: SectionKind) -> Option<&[u8]> {
        self.shared.body(kind)
    }
}

/// Verify whole-file bytes against a trusted content descriptor.
pub fn verify_bytes(bytes: &[u8], expected: &ContentDescriptor) -> SegmentResult<()> {
    if expected.length != bytes.len() as u64 {
        return Err(SegmentError::LengthMismatch {
            context: "content descriptor",
            expected: expected.length,
            actual: bytes.len() as u64,
        });
    }
    if !expected.matches(bytes) {
        return Err(SegmentError::DigestMismatch {
            context: "content descriptor",
        });
    }
    Ok(())
}

/// Parser-side retained-allocation upper bound.
///
/// `parse_container` retains the section directory and both feature lists. Their
/// counts are bounded by the configured limits, so this fixed bound is reserved
/// before parsing; it also includes the one shared-state `Arc` payload.
fn parser_allowance(limits: &SegmentLimits) -> SegmentResult<u64> {
    let sections = element_bytes::<SectionEntry>(limits.max_sections() as u64)?;
    let features = element_bytes::<(u16, u16)>(2 * limits.max_features() as u64)?;
    let state = std::mem::size_of::<VerifiedSegmentState>() as u64;
    accumulate(accumulate(sections, features)?, state)
}

/// The complete conservative candidate allowance for one segment (test witness).
#[cfg(test)]
pub(crate) fn candidate_allowance_for_test(
    bytes: &[u8],
    limits: SegmentLimits,
) -> SegmentResult<u64> {
    let view = parse_container(bytes, &limits)?;
    accumulate(parser_allowance(&limits)?, decode_allowance(&view)?)
}

/// Metadata-decode retained-allocation upper bound for a validated container.
///
/// Every term is derived from the section body length and the document format's
/// proven minimum encoded width (see `docs/pr-artifacts/pr-15c-a/preflight.md`
/// §5); no multiplier is guessed and no post-decode size is used.
fn decode_allowance(view: &ContainerView<'_>) -> SegmentResult<u64> {
    let mut total = 0u64;
    if let Some(body) = view.body(SectionKind::Schema) {
        let len = body.len() as u64;
        let fields = count_bound(len, SCHEMA_MIN_FIELD_BYTES);
        total = accumulate(total, element_bytes::<CodecField>(fields)?)?;
        // Every retained field/binding string is contained in the section bytes.
        total = accumulate(total, len)?;
    }
    // Both explicit and implicit identity remaps retain two u64 vectors: an
    // absent `SortedRemap` section is not a zero-cost identity representation,
    // so this allowance is unconditional.
    let doubled = view
        .doc_count()
        .checked_mul(2)
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    total = accumulate(total, element_bytes::<u64>(doubled)?)?;
    if let Some(body) = view.body(SectionKind::Dictionary) {
        let len = body.len() as u64;
        total = accumulate(
            total,
            element_bytes::<(u32, Vec<DictionaryEntry>)>(count_bound(
                len,
                DICTIONARY_MIN_FIELD_BYTES,
            ))?,
        )?;
        total = accumulate(
            total,
            element_bytes::<DictionaryEntry>(count_bound(len, DICTIONARY_MIN_TERM_BYTES))?,
        )?;
        // Every retained term string is contained in the section bytes.
        total = accumulate(total, len)?;
    }
    if let Some(body) = view.body(SectionKind::FieldNorms) {
        let len = body.len() as u64;
        let per_field = NORMS_MIN_FIELD_HEADER_BYTES
            .checked_add(view.doc_count())
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
        total = accumulate(
            total,
            element_bytes::<(u32, FieldNorms)>(count_bound(len, per_field.max(1)))?,
        )?;
        // Total retained length elements are bounded by the section byte count
        // because every length occupies at least one varint byte.
        total = accumulate(total, element_bytes::<u64>(len)?)?;
    }
    if let Some(body) = view.body(SectionKind::JsonPaths) {
        let len = body.len() as u64;
        // `Vec::push` growth keeps `capacity < 2 * len + 4`.
        let capacity_bound = count_bound(len, JSON_PATH_MIN_OCCURRENCE_BYTES)
            .checked_mul(2)
            .and_then(|bound| bound.checked_add(4))
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
        total = accumulate(total, element_bytes::<JsonDocOffset>(capacity_bound)?)?;
        total = accumulate(total, std::mem::size_of::<JsonPathDirectory>() as u64)?;
    }
    if let Some(body) = view.body(SectionKind::SpatialPoints) {
        let len = body.len() as u64;
        total = accumulate(
            total,
            element_bytes::<SpatialField>(count_bound(len, SPATIAL_MIN_FIELD_BYTES))?,
        )?;
        total = accumulate(
            total,
            element_bytes::<SpatialNode>(count_bound(len, SPATIAL_MIN_NODE_BYTES))?,
        )?;
    }
    if let Some(body) = view.body(SectionKind::GeoBounds) {
        total = accumulate(
            total,
            element_bytes::<GeoBounds>(count_bound(
                body.len() as u64,
                GEO_BOUNDS_ENTRY_LEN as u64,
            ))?,
        )?;
    }
    if let Some(body) = view.body(SectionKind::Columns) {
        total = accumulate(total, column_geometry_allowance(body.len() as u64)?)?;
    }
    Ok(total)
}

impl DecodedMetadata {
    /// Measured retained charge from the actual final capacities.
    fn measured_charge(&self) -> SegmentResult<u64> {
        let mut total = 0u64;
        total = accumulate(total, std::mem::size_of::<VerifiedSegmentState>() as u64)?;
        total = accumulate(
            total,
            capacity_bytes::<SectionEntry>(self.sections.capacity())?,
        )?;
        total = accumulate(
            total,
            capacity_bytes::<(u16, u16)>(self.required.capacity())?,
        )?;
        total = accumulate(
            total,
            capacity_bytes::<(u16, u16)>(self.optional.capacity())?,
        )?;
        total = accumulate(total, self.schema.metadata_charge()?)?;
        total = accumulate(total, self.remap.metadata_charge()?)?;
        if let Some(dictionary) = &self.dictionary {
            total = accumulate(total, dictionary.metadata_charge()?)?;
        }
        if let Some(norms) = &self.norms {
            total = accumulate(total, norms.metadata_charge()?)?;
        }
        total = accumulate(
            total,
            capacity_bytes::<GeoBounds>(self.geo_bounds.capacity())?,
        )?;
        if let Some(json_paths) = &self.json_paths {
            total = accumulate(total, json_paths.metadata_charge()?)?;
        }
        if let Some(spatial) = &self.spatial {
            total = accumulate(total, spatial.metadata_charge()?)?;
        }
        if let Some(geometry) = &self.column_geometry {
            total = accumulate(total, geometry.metadata_charge()?)?;
        }
        Ok(total)
    }
}

/// Decode and validate every immutable metadata structure of a segment.
fn decode_metadata(
    view: &ContainerView<'_>,
    limits: SegmentLimits,
    meter: &mut Option<&mut MetadataMeter>,
) -> SegmentResult<DecodedMetadata> {
    if view.kind() != ContainerKind::Segment {
        return Err(SegmentError::Corrupt {
            context: "segment",
            detail: "not a segment container".to_owned(),
        });
    }
    view.ensure_supported_features()?;
    let doc_count = view.doc_count();
    // The parser already allocated its own vectors under the parser allowance;
    // these are the retained copies, charged before allocation by the helper.
    let sections = copy_slice_fallible(view.sections(), &limits, meter)?;
    let required = copy_slice_fallible(view.required_features(), &limits, meter)?;
    let optional = copy_slice_fallible(view.optional_features(), &limits, meter)?;
    let schema = CodecSchema::decode_metered(
        view.body(SectionKind::Schema)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::Schema as u16,
            })?,
        &limits,
        meter,
    )?;
    // BM25 field norms: section and required feature must agree. Neither is a
    // valid legacy segment; both must be validated; a mismatch is corruption.
    let norms = match (
        view.body(SectionKind::FieldNorms),
        required.contains(&(FEATURE_FIELD_NORMS, 1)),
    ) {
        (None, false) => None,
        (Some(body), true) => Some(FieldNormsReader::decode_metered(
            body, doc_count, &schema, &limits, meter,
        )?),
        _ => {
            return Err(SegmentError::Corrupt {
                context: "field norms",
                detail: "section/feature presence mismatch".to_owned(),
            });
        }
    };
    let remap = match view.body(SectionKind::SortedRemap) {
        Some(body) => DocRemap::decode_metered(body, doc_count as usize, &limits, meter)?,
        // The implicit identity remap retains the same two `u64` arrays; it is
        // charged once and allocated fallibly by `identity_metered`.
        None => DocRemap::identity_metered(doc_count as usize, meter)?,
    };
    let dictionary = match view.body(SectionKind::Dictionary) {
        Some(body) => Some(DictionaryReader::new_metered(body, &limits, meter)?),
        None => None,
    };
    match (dictionary.as_ref(), view.body(SectionKind::Postings)) {
        (Some(dictionary), Some(postings_body)) => {
            let postings_len = postings_body.len() as u64;
            for (_, entries) in dictionary.fields() {
                for entry in entries {
                    let end = entry
                        .postings_offset
                        .checked_add(entry.postings_length)
                        .ok_or(SegmentError::Corrupt {
                            context: "dictionary",
                            detail: "posting extent overflow".to_owned(),
                        })?;
                    if end > postings_len {
                        return Err(SegmentError::Corrupt {
                            context: "dictionary",
                            detail: "posting extent out of range".to_owned(),
                        });
                    }
                }
            }
        }
        (Some(_), None) => {
            return Err(SegmentError::MissingSection {
                kind: SectionKind::Postings as u16,
            });
        }
        (None, Some(_)) => {
            return Err(SegmentError::MissingSection {
                kind: SectionKind::Dictionary as u16,
            });
        }
        (None, None) => {}
    }
    // Eager structural validation: column geometry is checked at open while
    // individual column values remain lazily decoded. A budget-admitted
    // candidate retains the already validated per-field table; the unmetered
    // path parses and discards it exactly as before.
    let column_geometry = match view.body(SectionKind::Columns) {
        None => None,
        Some(body) => match meter.as_deref_mut() {
            Some(meter) => Some(
                ColumnReader::open_with_doc_count_metered(
                    &schema,
                    body,
                    &limits,
                    Some(doc_count),
                    meter,
                )?
                .into_geometry(),
            ),
            None => {
                let _ = ColumnReader::open_with_doc_count(&schema, body, &limits, Some(doc_count))?;
                None
            }
        },
    };
    // Stored count must agree with the container doc count.
    if let Some(body) = view.body(SectionKind::Stored) {
        validate_stored_header(body, doc_count)?;
    }
    let time_bounds = match view.body(SectionKind::TimeBounds) {
        Some(body) => Some(TimeBounds::decode(body)?),
        None => None,
    };
    let geo_bounds = match view.body(SectionKind::GeoBounds) {
        Some(body) => decode_geo_bounds(body, &limits, meter)?,
        None => Vec::new(),
    };
    // JSON-path section and required feature must agree: neither alone is a
    // valid segment. A declared but malformed section fails closed here and is
    // never bypassed by a source fallback.
    let json_paths = match (
        view.body(SectionKind::JsonPaths),
        required.contains(&(FEATURE_JSON_PATHS, 1)),
    ) {
        (None, false) => None,
        (Some(body), true) => {
            if let Some(meter) = meter.as_deref_mut() {
                meter.charge_arc::<JsonPathDirectory>()?;
            }
            Some(Arc::new(JsonPathsReader::decode_directory_metered(
                body, doc_count, &schema, &limits, meter,
            )?))
        }
        _ => {
            return Err(SegmentError::Corrupt {
                context: "json paths",
                detail: "section/feature presence mismatch".to_owned(),
            });
        }
    };
    // Spatial KD tree: section and required feature must agree. A declared but
    // malformed section fails closed here and is never bypassed by a legacy
    // fallback.
    let spatial = match (
        view.body(SectionKind::SpatialPoints),
        required.contains(&(FEATURE_SPATIAL_POINTS, 1)),
    ) {
        (None, false) => None,
        (Some(body), true) => Some(SpatialIndex::decode_metered(
            body, &schema, doc_count, &limits, meter,
        )?),
        _ => {
            return Err(SegmentError::Corrupt {
                context: "spatial points",
                detail: "section/feature presence mismatch".to_owned(),
            });
        }
    };
    Ok(DecodedMetadata {
        doc_count,
        sections,
        required,
        optional,
        schema,
        remap,
        dictionary,
        norms,
        time_bounds,
        geo_bounds,
        json_paths,
        spatial,
        column_geometry,
    })
}

fn read_all(
    directory: &dyn Directory,
    key: &StorageKey,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let handle: Box<dyn ReadHandle> = directory.open_read(key)?;
    let len = handle.len();
    if len > limits.accepted_segment_bytes() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.accepted_segment_bytes(),
            requested: len,
        });
    }
    let max_read = limits.max_read_bytes();
    if len > 0 && max_read == 0 {
        return Err(SegmentError::LimitExceeded {
            limit: 0,
            requested: 1,
        });
    }
    let capacity = usize::try_from(len).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::from(u32::MAX),
        requested: len,
    })?;
    let max_read_usize = usize::try_from(max_read).unwrap_or(usize::MAX);
    let mut bytes = vec![0u8; capacity];
    let mut offset = 0usize;
    while offset < capacity {
        let remaining = capacity - offset;
        let request = remaining.min(max_read_usize);
        if request == 0 {
            return Err(SegmentError::LimitExceeded {
                limit: max_read,
                requested: 1,
            });
        }
        let read = handle.read_at(offset as u64, &mut bytes[offset..offset + request])?;
        if read > request {
            return Err(SegmentError::Corrupt {
                context: "directory read",
                detail: "read_at returned more bytes than requested".to_owned(),
            });
        }
        if read == 0 {
            return Err(SegmentError::LengthMismatch {
                context: "directory read",
                expected: len,
                actual: offset as u64,
            });
        }
        offset = offset.checked_add(read).ok_or(SegmentError::Corrupt {
            context: "directory read",
            detail: "read offset overflow".to_owned(),
        })?;
    }
    Ok(bytes)
}

fn decode_geo_bounds(
    body: &[u8],
    limits: &SegmentLimits,
    meter: &mut Option<&mut MetadataMeter>,
) -> SegmentResult<Vec<GeoBounds>> {
    let mut reader = ByteReader::new(body);
    let count = reader.u32("geo bound count")?;
    limits.check_entries(u64::from(count))?;
    limits.check_alloc::<GeoBounds>(u64::from(count))?;
    super::format::count_min_bytes(
        "geo bounds",
        u64::from(count),
        GEO_BOUNDS_ENTRY_LEN as u64,
        reader.remaining() as u64,
    )?;
    if let Some(meter) = meter.as_deref_mut() {
        meter.charge_vec::<GeoBounds>(u64::from(count))?;
    }
    let mut bounds: Vec<GeoBounds> = Vec::new();
    reserve_exact_vec(&mut bounds, count as usize, limits)?;
    for _ in 0..count {
        let entry = reader.bytes(GEO_BOUNDS_ENTRY_LEN, "geo bounds entry")?;
        bounds.push(GeoBounds::decode(entry)?);
    }
    reader.expect_end("geo bounds")?;
    Ok(bounds)
}

fn decode_doc_keys(reader: &SegmentReader) -> SegmentResult<Vec<DocumentKey>> {
    let body = reader
        .body(SectionKind::DocKeys)
        .ok_or(SegmentError::MissingSection {
            kind: SectionKind::DocKeys as u16,
        })?;
    let mut bytes = ByteReader::new(body);
    let version = bytes.u16("doc keys version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "doc keys version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = bytes.u64("doc keys count")?;
    if count != reader.shared.doc_count {
        return Err(SegmentError::Corrupt {
            context: "doc keys",
            detail: "doc key count does not match segment doc_count".to_owned(),
        });
    }
    reader.shared.limits.check_entries(count)?;
    let capacity = usize::try_from(count).map_err(|_| SegmentError::LimitExceeded {
        limit: reader.shared.limits.max_single_allocation(),
        requested: count,
    })?;
    // Minimum entry: a 2-byte length prefix plus at least one key byte.
    super::format::count_min_bytes("doc keys", count, 3, bytes.remaining() as u64)?;
    let mut keys: Vec<DocumentKey> = Vec::new();
    keys.try_reserve_exact(capacity)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: reader.shared.limits.max_single_allocation(),
            requested: count,
        })?;
    for _ in 0..count {
        let key_bytes = bytes.len_prefixed_u16("doc key")?;
        let key_ref = std::str::from_utf8(key_bytes)
            .map_err(|_| SegmentError::InvalidUtf8 { context: "doc key" })?;
        let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
            context: "doc key",
            detail: "invalid document key".to_owned(),
        })?;
        keys.push(key);
    }
    bytes.expect_end("doc keys")?;
    Ok(keys)
}

#[cfg(test)]
pub(crate) mod test_observation {
    use std::cell::Cell;

    thread_local! {
        static SELECTED_KEYS_OWNED: Cell<usize> = const { Cell::new(0) };
    }

    pub(crate) fn reset() {
        SELECTED_KEYS_OWNED.with(|value| value.set(0));
    }

    pub(crate) fn selected_keys_owned() -> usize {
        SELECTED_KEYS_OWNED.with(Cell::get)
    }

    pub(crate) fn record_selected_key_owned() {
        SELECTED_KEYS_OWNED.with(|value| value.set(value.get() + 1));
    }
}

/// Decode exactly one physical document key (PR 15E Phase 5).
///
/// Performs the same ordered framing, count, limit and trailing-data checks as
/// [`decode_doc_keys`] and validates **every** key in the section without allocating
/// an owned key for the unselected ones; only the requested physical id is
/// materialized as a `DocumentKey`. No full `Vec<DocumentKey>` is built.
fn validate_doc_keys_and_capture_offsets(
    shared: &VerifiedSegmentState,
    body: &[u8],
    offsets: &mut Vec<u64>,
) -> SegmentResult<()> {
    scan_doc_keys(body, shared.doc_count, &shared.limits, None, Some(offsets))?;
    Ok(())
}

fn decode_doc_key_selected(
    reader: &SegmentReader,
    selected_doc_id: u64,
) -> SegmentResult<DocumentKey> {
    let body = reader
        .body(SectionKind::DocKeys)
        .ok_or(SegmentError::MissingSection {
            kind: SectionKind::DocKeys as u16,
        })?;
    scan_doc_keys(
        body,
        reader.shared.doc_count,
        &reader.shared.limits,
        Some(selected_doc_id),
        None,
    )?
    .ok_or(SegmentError::Corrupt {
        context: "doc key",
        detail: "selected document key was not decoded".to_owned(),
    })
}

fn decode_doc_key_at_validated_offset(
    body: &[u8],
    offsets: &ValidatedOffsets,
    doc_id: u64,
) -> SegmentResult<DocumentKey> {
    let range = offsets.range(doc_id)?;
    let slice = body.get(range).ok_or(SegmentError::Corrupt {
        context: "doc key",
        detail: "validated key slice out of range".to_owned(),
    })?;
    let mut bytes = ByteReader::new(slice);
    let key_bytes = bytes.len_prefixed_u16("doc key")?;
    let key_ref = std::str::from_utf8(key_bytes)
        .map_err(|_| SegmentError::InvalidUtf8 { context: "doc key" })?;
    let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
        context: "doc key",
        detail: "invalid document key".to_owned(),
    })?;
    bytes.expect_end("doc keys")?;
    #[cfg(test)]
    test_observation::record_selected_key_owned();
    Ok(key)
}

/// Shared DOC_KEYS scanning body for validation capture and selection.
///
/// When `offsets` is supplied, every key is validated and one start offset per
/// key plus a terminal offset is captured. When `selected_doc_id` is supplied,
/// only that key is materialized.
fn scan_doc_keys(
    body: &[u8],
    expected_count: u64,
    limits: &SegmentLimits,
    selected_doc_id: Option<u64>,
    mut offsets: Option<&mut Vec<u64>>,
) -> SegmentResult<Option<DocumentKey>> {
    let mut bytes = ByteReader::new(body);
    let version = bytes.u16("doc keys version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "doc keys version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = bytes.u64("doc keys count")?;
    if count != expected_count {
        return Err(SegmentError::Corrupt {
            context: "doc keys",
            detail: "doc key count does not match segment doc_count".to_owned(),
        });
    }
    limits.check_entries(count)?;
    // Kept for parity with the full decoder even though no vector is reserved: the
    // declared count must remain representable in the same way.
    usize::try_from(count).map_err(|_| SegmentError::LimitExceeded {
        limit: limits.max_single_allocation(),
        requested: count,
    })?;
    // Minimum entry: a 2-byte length prefix plus at least one key byte.
    super::format::count_min_bytes("doc keys", count, 3, bytes.remaining() as u64)?;
    if let Some(selected_doc_id) = selected_doc_id {
        if selected_doc_id >= count {
            return Err(SegmentError::Corrupt {
                context: "doc keys",
                detail: "doc id out of range".to_owned(),
            });
        }
    }
    let mut selected: Option<DocumentKey> = None;
    for physical_doc_id in 0..count {
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
            offsets.push(position_u64(&bytes)?);
        }
        let key_bytes = bytes.len_prefixed_u16("doc key")?;
        let key_ref = std::str::from_utf8(key_bytes)
            .map_err(|_| SegmentError::InvalidUtf8 { context: "doc key" })?;
        if selected_doc_id == Some(physical_doc_id) {
            let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
                context: "doc key",
                detail: "invalid document key".to_owned(),
            })?;
            #[cfg(test)]
            test_observation::record_selected_key_owned();
            selected = Some(key);
        } else {
            // Borrowed validation with the constructor's exact rules; no owned key.
            if key_ref.is_empty() || key_ref.len() > DocumentKey::MAX_BYTES {
                return Err(SegmentError::Corrupt {
                    context: "doc key",
                    detail: "invalid document key".to_owned(),
                });
            }
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
        offsets.push(position_u64(&bytes)?);
    }
    bytes.expect_end("doc keys")?;
    if selected_doc_id.is_some() {
        match selected {
            Some(key) => Ok(Some(key)),
            None => Err(SegmentError::Corrupt {
                context: "doc key",
                detail: "selected document key was not decoded".to_owned(),
            }),
        }
    } else {
        Ok(None)
    }
}

fn decode_live_docs(reader: &SegmentReader) -> SegmentResult<Vec<bool>> {
    let body = reader
        .body(SectionKind::LiveDocs)
        .ok_or(SegmentError::MissingSection {
            kind: SectionKind::LiveDocs as u16,
        })?;
    let mut bytes = ByteReader::new(body);
    let version = bytes.u16("live docs version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "live docs version",
            detail: format!("unsupported {version}"),
        });
    }
    let present = bytes.u8("live docs present")?;
    if present != 1 {
        return Err(SegmentError::Corrupt {
            context: "live docs",
            detail: "unexpected presence tag".to_owned(),
        });
    }
    let count = bytes.u64("live docs count")?;
    if count != reader.shared.doc_count {
        return Err(SegmentError::Corrupt {
            context: "live docs",
            detail: "live-doc count does not match segment doc_count".to_owned(),
        });
    }
    let count_usize = usize::try_from(count).map_err(|_| SegmentError::LimitExceeded {
        limit: reader.shared.limits.max_single_allocation(),
        requested: count,
    })?;
    let bitmap_len = count_usize.div_ceil(8);
    let bitmap = bytes.bytes(bitmap_len, "live docs bitmap")?;
    bytes.expect_end("live docs")?;
    let mut live = Vec::new();
    live.try_reserve_exact(count_usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: reader.shared.limits.max_single_allocation(),
            requested: count,
        })?;
    for index in 0..count_usize {
        live.push(bitmap[index / 8] & (1 << (index % 8)) != 0);
    }
    Ok(live)
}

fn validate_stored_header(body: &[u8], expected_doc_count: u64) -> SegmentResult<()> {
    let mut reader = ByteReader::new(body);
    let version = reader.u16("stored version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "stored version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = reader.u64("stored count")?;
    if count != expected_doc_count {
        return Err(SegmentError::Corrupt {
            context: "stored",
            detail: "stored count does not match segment doc_count".to_owned(),
        });
    }
    Ok(())
}

#[cfg(test)]
mod fallible_metadata_tests {
    //! F2/F3 — retained metadata copies and geo-bounds vectors are reserved
    //! fallibly with unchanged decode semantics.

    use super::*;
    use crate::segment::format::{ByteWriter, SectionEntry, sha256};

    fn sample_section(index: usize) -> SectionEntry {
        SectionEntry {
            kind: SectionKind::Schema,
            flags: index as u16,
            aux: index as u64,
            offset: index as u64,
            length: index as u64,
            digest: sha256(&[index as u8]),
        }
    }

    // T03 — slice copies are byte-identical, order-preserving, exactly sized, and
    // charged before allocation.
    #[test]
    fn f2_t03_slice_copies_are_exact() {
        let limits = SegmentLimits::default();
        for len in [0usize, 1, 9] {
            let source: Vec<SectionEntry> = (0..len).map(sample_section).collect();
            let copy = copy_slice_fallible(&source, &limits, &mut None).expect("section copy");
            assert_eq!(copy, source, "len {len}");
            assert_eq!(copy.capacity(), len);
            assert_eq!(copy.len(), len);

            let features: Vec<(u16, u16)> = (0..len).map(|i| (i as u16, 7)).collect();
            let copy = copy_slice_fallible(&features, &limits, &mut None).expect("feature copy");
            assert_eq!(copy, features, "len {len}");
            assert_eq!(copy.capacity(), len);

            // An absent source slice copies to an empty, unallocated vector.
            let empty: &[SectionEntry] = &[];
            let copy = copy_slice_fallible(empty, &limits, &mut None).expect("empty copy");
            assert!(copy.is_empty());
            assert_eq!(copy.capacity(), 0);
        }

        // The retained charge is issued before the allocation: an allowance of
        // exactly nine entries admits, one entry less is rejected and refunded.
        let element = std::mem::size_of::<SectionEntry>() as u64;
        let source: Vec<SectionEntry> = (0..9).map(sample_section).collect();
        let budget = crate::segment::metadata::MetadataBudget::new(u64::MAX);
        let mut meter = crate::segment::metadata::MetadataMeter::reserve(&budget, 9 * element)
            .expect("allowance");
        {
            let mut slot = Some(&mut meter);
            let copy = copy_slice_fallible(&source, &limits, &mut slot).expect("metered copy");
            assert_eq!(copy, source);
        }
        drop(meter);
        assert_eq!(budget.used(), 0);

        let tight_budget = crate::segment::metadata::MetadataBudget::new(u64::MAX);
        let mut tight =
            crate::segment::metadata::MetadataMeter::reserve(&tight_budget, 9 * element - 1)
                .expect("allowance");
        {
            let mut slot = Some(&mut tight);
            assert!(matches!(
                copy_slice_fallible(&source, &limits, &mut slot),
                Err(SegmentError::LimitExceeded { .. })
            ));
        }
        drop(tight);
        assert_eq!(tight_budget.used(), 0);

        // An unrepresentable request is a typed error, not a panic.
        let mut huge: Vec<SectionEntry> = Vec::new();
        assert!(matches!(
            reserve_exact_vec(&mut huge, usize::MAX, &limits),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    fn geo_body(bounds: &[GeoBounds]) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        writer.u32(bounds.len() as u32);
        for bound in bounds {
            writer.bytes(&bound.encode());
        }
        writer.into_vec()
    }

    // T04 — geo bounds decode empty/singleton/many with identical values, and
    // malformed input keeps its typed error.
    #[test]
    fn f3_t04_geo_bounds_decode_unchanged() {
        let limits = SegmentLimits::default();

        let empty = geo_body(&[]);
        assert!(
            decode_geo_bounds(&empty, &limits, &mut None)
                .expect("empty")
                .is_empty()
        );

        let one = GeoBounds {
            known: true,
            presence: super::super::bounds::PRESENCE_ALL,
            live_count: 4,
            present_count: 4,
            west: -122.5,
            south: 37.0,
            east: -121.5,
            north: 38.0,
            crosses_antimeridian: false,
            ..GeoBounds::unknown(3, 4)
        };
        let bytes = geo_body(&[one]);
        let decoded = decode_geo_bounds(&bytes, &limits, &mut None).expect("singleton");
        assert_eq!(decoded, vec![one]);

        let many: Vec<GeoBounds> = (0..12)
            .map(|index| GeoBounds {
                presence: super::super::bounds::PRESENCE_SOME,
                live_count: 12,
                present_count: 6,
                west: index as f64,
                south: index as f64,
                east: index as f64 + 0.5,
                north: index as f64 + 0.5,
                crosses_antimeridian: index % 2 == 0,
                ..GeoBounds::unknown(index, 12)
            })
            .collect();
        let bytes = geo_body(&many);
        assert_eq!(
            decode_geo_bounds(&bytes, &limits, &mut None).expect("many"),
            many
        );

        // Truncated entry and trailing bytes keep their typed errors.
        assert!(matches!(
            decode_geo_bounds(&bytes[..bytes.len() - 1], &limits, &mut None),
            Err(SegmentError::Truncated { .. })
        ));
        let mut trailing = bytes.clone();
        trailing.push(0);
        assert!(matches!(
            decode_geo_bounds(&trailing, &limits, &mut None),
            Err(SegmentError::Corrupt { .. })
        ));

        // An over-limit count is rejected by the existing allocation check.
        let mut writer = ByteWriter::new();
        writer.u32(u32::MAX);
        let tiny = SegmentLimits::default().with_max_single_allocation(1);
        assert!(matches!(
            decode_geo_bounds(&writer.into_vec(), &tiny, &mut None),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }
}

#[cfg(test)]
mod column_geometry_tests {
    //! PR 15G-A — retained geometry admission, dispatch and fallback tests.

    use super::*;
    use crate::analysis::AnalyzerRegistry;
    use crate::contract::document::{Cardinality, DocumentKey};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::segment::build::{Layout, SegmentBuilder};
    use crate::segment::model::SegmentDocument;

    fn fixture_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "count",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "tags",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
            ],
            None,
        )
        .expect("schema")
    }

    fn doc(key: &str) -> SegmentDocument {
        SegmentDocument::new(DocumentKey::new(key).expect("key"))
    }

    /// A real built segment with three columnar fields (fixed single, variable
    /// single, variable multi) spread over multiple blocks.
    fn fixture() -> Vec<u8> {
        let mut builder = SegmentBuilder::new(fixture_schema(), AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion)
            .with_limits(SegmentLimits::default().with_block_docs_default(2));
        let mut first = doc("k0");
        first
            .insert(
                "count",
                crate::contract::document::FieldValues::Single(FieldValue::I64(10)),
            )
            .expect("count");
        first
            .insert(
                "tag",
                crate::contract::document::FieldValues::Single(FieldValue::Keyword("a".to_owned())),
            )
            .expect("tag");
        first
            .insert(
                "tags",
                crate::contract::document::FieldValues::Multi(vec![
                    FieldValue::Keyword("red".to_owned()),
                    FieldValue::Keyword("blue".to_owned()),
                ]),
            )
            .expect("tags");
        builder.add_document(first).expect("add");

        let mut second = doc("k1");
        second
            .insert(
                "count",
                crate::contract::document::FieldValues::ExplicitNull,
            )
            .expect("count");
        second
            .insert("tag", crate::contract::document::FieldValues::ExplicitNull)
            .expect("tag");
        second
            .insert("tags", crate::contract::document::FieldValues::Empty)
            .expect("tags");
        builder.add_document(second).expect("add");

        let mut third = doc("k2");
        third
            .insert(
                "tag",
                crate::contract::document::FieldValues::Single(FieldValue::Keyword("b".to_owned())),
            )
            .expect("tag");
        third
            .insert(
                "tags",
                crate::contract::document::FieldValues::Multi(vec![FieldValue::Keyword(
                    "green".to_owned(),
                )]),
            )
            .expect("tags");
        builder.add_document(third).expect("add");

        let mut fourth = doc("k3");
        fourth
            .insert(
                "count",
                crate::contract::document::FieldValues::Single(FieldValue::I64(40)),
            )
            .expect("count");
        fourth
            .insert("tags", crate::contract::document::FieldValues::ExplicitNull)
            .expect("tags");
        builder.add_document(fourth).expect("add");

        let mut fifth = doc("k4");
        fifth
            .insert(
                "count",
                crate::contract::document::FieldValues::Single(FieldValue::I64(50)),
            )
            .expect("count");
        fifth
            .insert(
                "tag",
                crate::contract::document::FieldValues::Single(FieldValue::Keyword("c".to_owned())),
            )
            .expect("tag");
        builder.add_document(fifth).expect("add");

        builder.build().expect("build").bytes
    }

    fn standalone_body(bytes: &[u8], limits: SegmentLimits) -> Vec<u8> {
        let reader = SegmentReader::open(bytes.to_vec(), limits).expect("uncached");
        let entry = reader
            .sections()
            .iter()
            .find(|entry| entry.kind == SectionKind::Columns)
            .expect("columns section");
        let start = entry.offset as usize;
        let end = start + entry.length as usize;
        bytes[start..end].to_vec()
    }

    // GA-U08 — a zero metadata cap retains no geometry and the verified
    // uncached reader keeps full column correctness.
    #[test]
    fn u08_zero_cap_retains_no_geometry_and_reads_correctly() {
        let bytes = fixture();
        let limits = SegmentLimits::default();
        let budget = MetadataBudget::new(0);
        let candidate =
            VerifiedSegmentState::build_cached(Arc::new(bytes.clone()), limits, &budget)
                .expect("optional failure");
        assert!(candidate.is_none());
        assert_eq!(budget.used(), 0);

        let reader = SegmentReader::open(bytes, limits).expect("uncached");
        assert!(!reader.shared_state().has_column_geometry());
        assert!(reader.shared_state().column_geometry_ptr().is_none());
        let columns = reader.open_columns().expect("columns").expect("present");
        assert!(!columns.fields().is_empty());
    }

    // GA-U09 — the exact candidate allowance admits and retains geometry; one
    // byte less takes the independently validating fallback with no leak.
    #[test]
    fn u09_exact_allowance_admits_and_one_under_falls_back() {
        let bytes = fixture();
        let limits = SegmentLimits::default();
        let allowance = candidate_allowance_for_test(&bytes, limits).expect("allowance");
        assert!(allowance > 0);

        let exact = MetadataBudget::new(allowance);
        let state = VerifiedSegmentState::build_cached(Arc::new(bytes.clone()), limits, &exact)
            .expect("candidate")
            .expect("admitted");
        let charged = exact.used();
        assert!(charged > 0);
        assert!(charged <= allowance);
        let reader = SegmentReader::from_shared(state);
        assert!(reader.shared_state().has_column_geometry());
        let retained = reader
            .shared_state()
            .column_geometry_ptr()
            .expect("retained geometry");
        let first = reader.open_columns().expect("columns").expect("present");
        let second = reader.open_columns().expect("columns").expect("present");
        assert_eq!(first.geometry_ptr(), retained);
        assert_eq!(second.geometry_ptr(), retained);
        assert_eq!(first.blocks_read(), 0);
        assert_eq!(second.blocks_read(), 0);
        drop(first);
        drop(second);
        drop(reader);
        assert_eq!(exact.used(), 0);

        let tight = MetadataBudget::new(allowance - 1);
        let candidate = VerifiedSegmentState::build_cached(Arc::new(bytes.clone()), limits, &tight)
            .expect("optional failure");
        assert!(candidate.is_none());
        assert_eq!(tight.used(), 0);
        // The fallback re-validates and answers identically.
        let fallback = SegmentReader::open(bytes, limits).expect("fallback");
        assert!(!fallback.shared_state().has_column_geometry());
        let columns = fallback.open_columns().expect("columns").expect("present");
        assert!(!columns.fields().is_empty());
    }

    // GA-U12 — repeated `open_columns` borrows one retained table and each
    // reader keeps an independent query-local counter.
    #[test]
    fn u12_repeated_open_columns_share_geometry_and_reset_counters() {
        let bytes = fixture();
        let limits = SegmentLimits::default();
        let allowance = candidate_allowance_for_test(&bytes, limits).expect("allowance");
        let budget = MetadataBudget::new(allowance);
        let state = VerifiedSegmentState::build_cached(Arc::new(bytes), limits, &budget)
            .expect("candidate")
            .expect("admitted");
        let reader = SegmentReader::from_shared(state);
        let retained = reader
            .shared_state()
            .column_geometry_ptr()
            .expect("retained geometry");
        let tag = reader.schema().field_id("tag").expect("tag");
        let first = reader.open_columns().expect("columns").expect("present");
        assert_eq!(first.geometry_ptr(), retained);
        assert_eq!(first.blocks_read(), 0);
        let second = reader.open_columns().expect("columns").expect("present");
        assert_eq!(second.geometry_ptr(), retained);
        assert_eq!(second.blocks_read(), 0);
        first.value(tag, 0).expect("first value");
        assert_eq!(first.blocks_read(), 1);
        assert_eq!(second.blocks_read(), 0);
        drop(first);
        drop(second);
        let third = reader.open_columns().expect("columns").expect("present");
        assert_eq!(third.geometry_ptr(), retained);
        assert_eq!(third.blocks_read(), 0);
    }

    // GA-U13 — direct `column_value`, `open_columns().value` and an independent
    // standalone parse return identical results, including absent/null/multi and
    // out-of-range errors.
    #[test]
    fn u13_direct_and_unified_column_access_match_standalone() {
        let bytes = fixture();
        let limits = SegmentLimits::default();
        let allowance = candidate_allowance_for_test(&bytes, limits).expect("allowance");
        let budget = MetadataBudget::new(allowance);
        let state = VerifiedSegmentState::build_cached(Arc::new(bytes.clone()), limits, &budget)
            .expect("candidate")
            .expect("admitted");
        let cached = SegmentReader::from_shared(state);
        let body = standalone_body(&bytes, limits);
        let standalone =
            ColumnReader::open(cached.schema(), &body, &limits).expect("standalone parser");
        for field in ["count", "tag", "tags"] {
            let field_id = cached.schema().field_id(field).expect("field");
            for doc_id in 0..6u64 {
                let direct = cached.column_value(field_id, doc_id);
                let unified = cached
                    .open_columns()
                    .expect("columns")
                    .expect("present")
                    .value(field_id, doc_id);
                let oracle = standalone.value(field_id, doc_id);
                match (&direct, &unified, &oracle) {
                    (Ok(a), Ok(b), Ok(c)) => {
                        assert_eq!(a, b, "{field} {doc_id} direct vs unified");
                        assert_eq!(a, c, "{field} {doc_id} direct vs standalone");
                    }
                    (Err(_), Err(_), Err(_)) => {}
                    other => panic!("unexpected error split for {field} {doc_id}: {other:?}"),
                }
            }
        }
        let count = cached.schema().field_id("count").expect("count");
        assert!(cached.column_value(count, 5).is_err());
        assert!(standalone.value(count, 5).is_err());
    }

    // GA-U14 — a corrupt container is a typed integrity error, never an
    // optional cache miss or a silently published state.
    #[test]
    fn u14_corrupt_container_never_becomes_a_cache_hit() {
        let mut bytes = fixture();
        let last = bytes.len() - 1;
        bytes[last] ^= 0xFF;
        let limits = SegmentLimits::default();
        let allowance = candidate_allowance_for_test(&bytes, limits);
        // The corrupt container may fail before or during allowance derivation;
        // either way the candidate build must not publish a state.
        if let Ok(allowance) = allowance {
            let budget = MetadataBudget::new(allowance.max(1));
            let result =
                VerifiedSegmentState::build_cached(Arc::new(bytes.clone()), limits, &budget);
            assert!(result.is_err(), "corruption must propagate");
            assert_eq!(budget.used(), 0);
        }
        assert!(SegmentReader::open(bytes, limits).is_err());
    }

    // GA-U18 / PR 15G-A FX-I04 — digest-valid but schema-invalid COLUMNS must be
    // rejected by both the standalone and metered candidate constructors, with
    // no publication and a fully released budget.
    #[test]
    fn u18_valid_envelope_bad_columns_rejected_by_metered_candidate() {
        let original = fixture();
        let limits = SegmentLimits::default();
        let view = parse_container(&original, &limits).expect("original container");
        let columns_body = view
            .body(SectionKind::Columns)
            .expect("columns body")
            .to_vec();
        assert!(columns_body.len() >= 11);
        let required = view.required_features().to_vec();
        let optional = view.optional_features().to_vec();
        let mut corrupt_body = columns_body.clone();
        corrupt_body[10] ^= 0xFF;

        let mut builder =
            crate::segment::format::ContainerBuilder::new(view.kind(), view.doc_count());
        // `ContainerBuilder::new` already contributes one baseline feature.
        // Preserve every original tuple, including any duplicate baseline entry,
        // by skipping exactly one baseline occurrence.
        let mut baseline_skipped = false;
        for (feature, version) in &required {
            if !baseline_skipped && (*feature, *version) == (1, 1) {
                baseline_skipped = true;
                continue;
            }
            builder.require_feature(*feature, *version);
        }
        assert!(baseline_skipped, "original segment must declare baseline");
        for (feature, version) in &optional {
            builder.optional_feature(*feature, *version);
        }
        for section in view.sections() {
            let body = if section.kind == SectionKind::Columns {
                corrupt_body.clone()
            } else {
                let start = section.offset as usize;
                original[start..start + section.length as usize].to_vec()
            };
            builder.section(section.kind, section.flags, section.aux, body);
        }
        let rebuilt = builder.build().expect("rebuild with valid digests");

        // The rebuilt outer container and every non-COLUMNS section remain valid.
        let reparsed = parse_container(&rebuilt, &limits).expect("valid rebuilt container");
        assert_eq!(reparsed.required_features(), required.as_slice());
        assert_eq!(reparsed.optional_features(), optional.as_slice());
        assert_eq!(reparsed.sections().len(), view.sections().len());
        for (before, after) in view.sections().iter().zip(reparsed.sections()) {
            assert_eq!(before.kind, after.kind);
            assert_eq!(before.flags, after.flags);
            assert_eq!(before.aux, after.aux);
            if before.kind != SectionKind::Columns {
                let start = before.offset as usize;
                assert_eq!(
                    &original[start..start + before.length as usize],
                    reparsed.body(before.kind).expect("section body"),
                    "{:?} body must be unchanged",
                    before.kind
                );
            }
        }
        let rebuilt_columns = reparsed.body(SectionKind::Columns).expect("columns body");
        assert_eq!(rebuilt_columns.len(), columns_body.len());
        for (index, (before, after)) in columns_body.iter().zip(rebuilt_columns).enumerate() {
            if index == 10 {
                assert_ne!(before, after, "type tag must be corrupted");
            } else {
                assert_eq!(before, after, "byte {index} must be unchanged");
            }
        }

        let standalone = match SegmentReader::open(rebuilt.clone(), limits) {
            Ok(_) => panic!("standalone must reject malformed columns"),
            Err(error) => error,
        };
        assert!(matches!(standalone, SegmentError::FieldTypeMismatch { .. }));

        let allowance = candidate_allowance_for_test(&rebuilt, limits).expect("allowance");
        let budget = MetadataBudget::new(allowance);
        match VerifiedSegmentState::build_cached(Arc::new(rebuilt), limits, &budget) {
            Err(SegmentError::FieldTypeMismatch { .. }) => {}
            Err(other) => panic!("unexpected metered error: {other:?}"),
            Ok(None) => panic!("corruption must not become an optional cache miss"),
            Ok(Some(_)) => panic!("corruption must not publish a cached state"),
        }
        assert_eq!(budget.used(), 0, "failed candidate must release its charge");

        // The same budget handle accepts the pristine bytes and releases again.
        let state = VerifiedSegmentState::build_cached(Arc::new(original), limits, &budget)
            .expect("valid candidate")
            .expect("valid bytes admit");
        assert!(state.has_column_geometry());
        assert!(budget.used() > 0);
        drop(state);
        assert_eq!(budget.used(), 0);
    }

    // GA-U15 — retained geometry and verified state stay `Send + Sync`, and the
    // query-local reader keeps its `Cell` counter rather than shared mutability.
    #[test]
    fn u15_shared_geometry_is_send_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<VerifiedSegmentState>();
        assert_send_sync::<ColumnGeometry>();
    }

    fn admitted_state(bytes: Vec<u8>) -> (Arc<VerifiedSegmentState>, Arc<MetadataBudget>) {
        let limits = SegmentLimits::default();
        let allowance = candidate_allowance_for_test(&bytes, limits).expect("allowance");
        let budget = MetadataBudget::new(allowance);
        let state = VerifiedSegmentState::build_cached(Arc::new(bytes), limits, &budget)
            .expect("candidate")
            .expect("admitted");
        (state, budget)
    }

    fn rebuild_section(
        original: &[u8],
        kind: SectionKind,
        mutate: impl FnOnce(&mut Vec<u8>),
    ) -> Vec<u8> {
        let limits = SegmentLimits::default();
        let view = parse_container(original, &limits).expect("container");
        let mut replacement = view.body(kind).expect("section body").to_vec();
        mutate(&mut replacement);
        let mut builder =
            crate::segment::format::ContainerBuilder::new(view.kind(), view.doc_count());
        let mut baseline_skipped = false;
        for (feature, version) in view.required_features() {
            if !baseline_skipped && (*feature, *version) == (1, 1) {
                baseline_skipped = true;
                continue;
            }
            builder.require_feature(*feature, *version);
        }
        for (feature, version) in view.optional_features() {
            builder.optional_feature(*feature, *version);
        }
        for section in view.sections() {
            let body = if section.kind == kind {
                replacement.clone()
            } else {
                let start = section.offset as usize;
                original[start..start + section.length as usize].to_vec()
            };
            builder.section(section.kind, section.flags, section.aux, body);
        }
        builder.build().expect("rebuilt valid container")
    }

    fn build_with_docs(docs: Vec<SegmentDocument>) -> Vec<u8> {
        let mut builder = SegmentBuilder::new(fixture_schema(), AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion)
            .with_limits(SegmentLimits::default().with_block_docs_default(2));
        for document in docs {
            builder.add_document(document).expect("add");
        }
        builder.build().expect("build").bytes
    }

    #[test]
    fn gbu16_doc_keys_zero_one_and_many_match_legacy() {
        let limits = SegmentLimits::default();
        let empty = build_with_docs(Vec::new());
        let reader = SegmentReader::open(empty, limits).expect("empty");
        assert_eq!(reader.doc_count(), 0);
        assert_eq!(reader.shared_state().key_offsets_state(), None);
        assert!(
            reader
                .doc_key_selected(0)
                .expect_err("out of range")
                .to_string()
                .contains("doc id out of range")
        );
        assert!(reader.doc_keys().expect("empty keys").is_empty());

        for docs in [vec![doc("k0")], vec![doc("k0"), doc("k1"), doc("k2")]] {
            let bytes = build_with_docs(docs);
            let standalone = SegmentReader::open(bytes.clone(), limits).expect("standalone");
            let expected = standalone.doc_keys().expect("full keys").to_vec();
            let (state, _) = admitted_state(bytes);
            let cached = SegmentReader::from_shared(state);
            for doc_id in 0..expected.len() as u64 {
                assert_eq!(
                    cached.doc_key_selected(doc_id).expect("selected"),
                    expected[doc_id as usize]
                );
            }
            assert_eq!(
                cached.shared_state().key_offsets_state(),
                Some(true),
                "key offsets should publish after validation"
            );
            assert!(!cached.doc_keys_cache_is_populated());
        }
    }

    #[test]
    fn gbu19_exact_budget_retains_and_one_under_falls_back() {
        let bytes = fixture();
        let limits = SegmentLimits::default();
        let allowance = candidate_allowance_for_test(&bytes, limits).expect("allowance");
        let (state, budget) = admitted_state(bytes.clone());
        let reader = SegmentReader::from_shared(state);
        let before = reader.shared_state().access_budget_used().expect("budget");
        let expected = SegmentReader::open(bytes.clone(), limits)
            .expect("standalone")
            .stored_docs_selected(&[0, 2])
            .expect("legacy");
        assert_eq!(
            reader.stored_docs_selected(&[0, 2]).expect("selected"),
            expected
        );
        let after = reader.shared_state().access_budget_used().expect("budget");
        assert!(after > before, "directory must be charged");
        assert_eq!(reader.shared_state().stored_offsets_state(), Some(true));
        assert_eq!(
            reader.stored_docs_selected(&[0, 2]).expect("repeat"),
            expected
        );
        assert_eq!(
            reader.shared_state().access_budget_used(),
            Some(after),
            "repeat must not re-charge"
        );
        drop(reader);
        drop(budget);

        let tight = MetadataBudget::new(allowance - 1);
        let candidate = VerifiedSegmentState::build_cached(Arc::new(bytes.clone()), limits, &tight)
            .expect("optional failure");
        assert!(candidate.is_none());
        assert_eq!(tight.used(), 0);
        let fallback = SegmentReader::open(bytes, limits).expect("fallback");
        assert!(!fallback.shared_state().has_access_budget());
        assert_eq!(
            fallback.stored_docs_selected(&[0, 2]).expect("fallback"),
            expected
        );
        assert_eq!(fallback.shared_state().stored_offsets_state(), None);
    }

    #[test]
    fn gbu20_two_readers_share_one_retained_directory() {
        let bytes = fixture();
        let (state, _) = admitted_state(bytes);
        let first = SegmentReader::from_shared(Arc::clone(&state));
        let second = SegmentReader::from_shared(Arc::clone(&state));
        let expected = first.stored_docs_selected(&[0, 1]).expect("first");
        assert_eq!(
            second.stored_docs_selected(&[0, 1]).expect("second"),
            expected
        );
        assert_eq!(
            first.shared_state().stored_offsets_ptr(),
            second.shared_state().stored_offsets_ptr()
        );
        assert_eq!(first.shared_state().key_offsets_state(), None);
        let key = first.doc_key_selected(0).expect("key");
        assert_eq!(second.doc_key_selected(0).expect("key"), key);
        assert_eq!(
            first.shared_state().key_offsets_ptr(),
            second.shared_state().key_offsets_ptr()
        );
    }

    #[test]
    fn gbu21_concurrent_first_access_publishes_once() {
        let bytes = fixture();
        let (state, _) = admitted_state(bytes);
        std::thread::scope(|scope| {
            for _ in 0..8 {
                let state = Arc::clone(&state);
                scope.spawn(move || {
                    let reader = SegmentReader::from_shared(state);
                    let records = reader.stored_docs_selected(&[0, 2]).expect("stored");
                    assert_eq!(records.len(), 2);
                    assert!(!reader.doc_key_selected(0).expect("key").as_str().is_empty());
                    assert!(!reader.stored_cache_is_populated());
                    assert!(!reader.doc_keys_cache_is_populated());
                });
            }
        });
        assert_eq!(state.stored_offsets_state(), Some(true));
        assert_eq!(state.key_offsets_state(), Some(true));
        assert!(state.stored_offsets_ptr().is_some());
        assert!(state.key_offsets_ptr().is_some());
    }

    #[test]
    fn gbu22_validated_offsets_are_send_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<ValidatedOffsets>();
        assert_send_sync::<OnceLock<Option<ValidatedOffsets>>>();
    }

    #[test]
    fn gbu23_full_caches_take_precedence_and_do_not_initialize_offsets() {
        let bytes = fixture();
        let (state, _) = admitted_state(bytes.clone());
        let reader = SegmentReader::from_shared(state);
        let full_stored = reader.stored().expect("full stored");
        let full_keys = reader.doc_keys().expect("full keys");
        assert_eq!(
            reader.stored_docs_selected(&[0, 2]).expect("stored"),
            [
                (0u64, full_stored[0].clone()),
                (2u64, full_stored[2].clone())
            ]
        );
        assert_eq!(
            reader.doc_key_selected(1).expect("key"),
            full_keys[1].clone()
        );
        assert_eq!(reader.shared_state().stored_offsets_state(), None);
        assert_eq!(reader.shared_state().key_offsets_state(), None);
        assert!(reader.stored_cache_is_populated());
        assert!(reader.doc_keys_cache_is_populated());
    }

    #[test]
    fn gbu24_unmetered_and_zero_cap_never_allocate_offsets() {
        let bytes = fixture();
        let limits = SegmentLimits::default();
        let standalone = SegmentReader::open(bytes.clone(), limits).expect("standalone");
        assert!(!standalone.shared_state().has_access_budget());
        assert!(
            !standalone
                .stored_docs_selected(&[0])
                .expect("stored")
                .is_empty()
        );
        assert!(
            !standalone
                .doc_key_selected(0)
                .expect("key")
                .as_str()
                .is_empty()
        );
        assert_eq!(standalone.shared_state().stored_offsets_state(), None);
        assert_eq!(standalone.shared_state().key_offsets_state(), None);

        let zero = MetadataBudget::new(0);
        assert!(
            VerifiedSegmentState::build_cached(Arc::new(bytes.clone()), limits, &zero)
                .expect("optional")
                .is_none()
        );
        assert_eq!(zero.used(), 0);
        let fallback = SegmentReader::open(bytes, limits).expect("fallback");
        assert!(!fallback.shared_state().has_access_budget());
        assert!(
            !fallback
                .stored_docs_selected(&[0])
                .expect("stored")
                .is_empty()
        );
        assert_eq!(fallback.shared_state().stored_offsets_state(), None);
    }

    #[test]
    fn gbu25_directory_charge_releases_with_last_state_owner() {
        let bytes = fixture();
        let limits = SegmentLimits::default();
        let allowance = candidate_allowance_for_test(&bytes, limits).expect("allowance");
        let budget = MetadataBudget::new(allowance);
        let state = VerifiedSegmentState::build_cached(Arc::new(bytes), limits, &budget)
            .expect("candidate")
            .expect("admitted");
        let reader = SegmentReader::from_shared(Arc::clone(&state));
        let _ = reader.stored_docs_selected(&[0]).expect("stored");
        let _ = reader.doc_key_selected(0).expect("key");
        assert!(budget.used() > 0);
        drop(reader);
        assert!(budget.used() > 0, "state still owns both reservations");
        drop(state);
        assert_eq!(budget.used(), 0);
    }

    #[test]
    fn gbu26_initializer_panic_publishes_nothing_and_releases_budget() {
        let bytes = fixture();
        let (state, budget) = admitted_state(bytes);
        let reader = SegmentReader::from_shared(state);
        let before = reader.shared_state().access_budget_used().expect("budget");
        super::set_fail_stored_directory_build(true);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = reader.stored_docs_selected(&[0]);
        }));
        super::set_fail_stored_directory_build(false);
        assert!(result.is_err(), "initializer panic must propagate in test");
        assert_eq!(reader.shared_state().stored_offsets_state(), None);
        assert_eq!(
            reader.shared_state().access_budget_used(),
            Some(before),
            "failed initializer must release its transient reservation"
        );
        assert_eq!(reader.stored_docs_selected(&[0]).expect("retry").len(), 1);
        assert_eq!(reader.shared_state().stored_offsets_state(), Some(true));
        assert!(budget.used() > 0);
    }

    fn key_body(keys: &[&[u8]]) -> Vec<u8> {
        let mut writer = crate::segment::format::ByteWriter::new();
        writer.u16(1);
        writer.u64(keys.len() as u64);
        for key in keys {
            writer.len_prefixed_u16(key).expect("key prefix");
        }
        writer.into_vec()
    }

    #[test]
    fn gbu17_invalid_unselected_keys_are_typed_on_both_paths() {
        let limits = SegmentLimits::default();
        let long = vec![b'a'; 1025];
        let cases: Vec<Vec<u8>> = vec![
            key_body(&[b"ok", b"\xff"]),
            key_body(&[b"ok", b""]),
            key_body(&[b"ok", &long]),
        ];
        for body in cases {
            let selected =
                super::scan_doc_keys(&body, 2, &limits, None, None).expect_err("invalid key");
            assert!(
                matches!(
                    selected,
                    SegmentError::InvalidUtf8 { .. } | SegmentError::Corrupt { .. }
                ),
                "{selected:?}"
            );
            let mut offsets = Vec::new();
            let captured = super::scan_doc_keys(&body, 2, &limits, None, Some(&mut offsets))
                .expect_err("invalid key capture");
            assert!(
                matches!(
                    captured,
                    SegmentError::InvalidUtf8 { .. } | SegmentError::Corrupt { .. }
                ),
                "{captured:?}"
            );
        }
        let mut trailing = key_body(&[b"ok"]);
        trailing.push(0);
        assert!(matches!(
            super::scan_doc_keys(&trailing, 1, &limits, None, None),
            Err(SegmentError::Corrupt { .. })
        ));
    }

    #[test]
    fn gbu18_count_version_and_range_errors_are_typed() {
        let limits = SegmentLimits::default();
        let mut wrong_version = crate::segment::format::ByteWriter::new();
        wrong_version.u16(9);
        wrong_version.u64(0);
        assert!(matches!(
            super::scan_doc_keys(&wrong_version.into_vec(), 0, &limits, None, None),
            Err(SegmentError::Corrupt { .. })
        ));
        let body = key_body(&[b"ok"]);
        assert!(matches!(
            super::scan_doc_keys(&body, 2, &limits, None, None),
            Err(SegmentError::Corrupt { .. })
        ));
        assert!(matches!(
            super::scan_doc_keys(&body, 1, &limits, Some(1), None),
            Err(SegmentError::Corrupt { .. })
        ));
        let tiny = limits.with_max_decoded_entries(0);
        assert!(matches!(
            super::scan_doc_keys(&body, 1, &tiny, None, None),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn gbu27_corrupt_unselected_stored_and_key_bytes_fail_closed() {
        let original = fixture();
        let limits = SegmentLimits::default();
        let standalone = SegmentReader::open(original.clone(), limits).expect("standalone");
        let schema = standalone.schema().clone();
        let stored_body = standalone
            .sections()
            .iter()
            .find(|entry| entry.kind == SectionKind::Stored)
            .and_then(|_entry| standalone.body(SectionKind::Stored))
            .expect("stored body")
            .to_vec();
        let mut stored_offsets = Vec::new();
        super::validate_stored_and_capture_offsets(
            &schema,
            &stored_body,
            &limits,
            &mut stored_offsets,
        )
        .expect("stored offsets");
        let corrupt_stored = rebuild_section(&original, SectionKind::Stored, |body| {
            body[stored_offsets[1] as usize + 2] ^= 0xFF;
        });
        let (state, budget) = admitted_state(corrupt_stored);
        let reader = SegmentReader::from_shared(state);
        let before = reader.shared_state().access_budget_used().expect("budget");
        let error = reader
            .stored_docs_selected(&[0])
            .expect_err("corrupt unselected stored record");
        assert!(
            matches!(error, SegmentError::InvalidUtf8 { .. }),
            "{error:?}"
        );
        assert_eq!(reader.shared_state().stored_offsets_state(), Some(false));
        assert_eq!(
            reader.shared_state().access_budget_used(),
            Some(before),
            "failed directory must not retain extra charge"
        );
        assert!(reader.stored_docs_selected(&[0]).is_err());
        drop(reader);
        drop(budget);

        let original = fixture();
        let standalone = SegmentReader::open(original.clone(), limits).expect("standalone");
        let key_body = standalone
            .body(SectionKind::DocKeys)
            .expect("keys body")
            .to_vec();
        let mut key_offsets = Vec::new();
        super::validate_doc_keys_and_capture_offsets(
            standalone.shared_state(),
            &key_body,
            &mut key_offsets,
        )
        .expect("key offsets");
        let corrupt_keys = rebuild_section(&original, SectionKind::DocKeys, |body| {
            body[key_offsets[1] as usize + 2] ^= 0xFF;
        });
        let (state, _) = admitted_state(corrupt_keys);
        let reader = SegmentReader::from_shared(state);
        let error = reader
            .doc_key_selected(0)
            .expect_err("corrupt unselected key");
        assert!(
            matches!(error, SegmentError::InvalidUtf8 { .. }),
            "{error:?}"
        );
        assert_eq!(reader.shared_state().key_offsets_state(), Some(false));
        assert!(reader.doc_key_selected(0).is_err());
    }
}
