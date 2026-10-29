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
use std::rc::Rc;
use std::sync::Arc;

use quervant_objectstore::ContentDescriptor;

use crate::contract::document::DocumentKey;

use super::bounds::{GeoBounds, TimeBounds};
use super::column::ColumnReader;
use super::dictionary::{DictionaryEntry, DictionaryReader};
use super::error::{SegmentError, SegmentResult};
use super::format::{
    ByteReader, ContainerKind, ContainerView, FEATURE_FIELD_NORMS, FEATURE_JSON_PATHS,
    FEATURE_SPATIAL_POINTS, SectionEntry, SectionKind, parse_container,
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
use super::stored::{StoredRecord, decode_stored};
use crate::storage::{Directory, ReadHandle, StorageKey};

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

/// The fully validated, immutable, shareable state of one segment.
///
/// Every field is immutable after construction and `Send + Sync`. The only
/// mutable state in the engine — the stored/document-key/live-doc caches — stays
/// query-local in [`SegmentReader`].
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
        Ok(Arc::new(candidate.with_metadata(reservation)))
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
            metadata: None,
        }
    }

    fn with_metadata(mut self, reservation: MetadataReservation) -> Self {
        self.metadata = Some(reservation);
        self
    }

    fn body(&self, kind: SectionKind) -> Option<&[u8]> {
        let entry = self.sections.iter().find(|entry| entry.kind == kind)?;
        let start = entry.offset as usize;
        let end = start + entry.length as usize;
        self.bytes.get(start..end)
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
        let Some(body) = self.body(SectionKind::Columns) else {
            return Ok(None);
        };
        let reader = ColumnReader::open(&self.shared.schema, body, &self.shared.limits)?;
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
    /// Returns `None` for a legacy segment without typed columns. This is a
    /// read-only accessor; callers that read many values should open once and
    /// reuse the reader instead of calling [`SegmentReader::column_value`] per
    /// value (which re-parses the column geometry each time). No wire bytes are
    /// changed.
    pub fn open_columns(&self) -> SegmentResult<Option<ColumnReader<'_>>> {
        match self.body(SectionKind::Columns) {
            Some(body) => Ok(Some(ColumnReader::open(
                &self.shared.schema,
                body,
                &self.shared.limits,
            )?)),
            None => Ok(None),
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
    // The parser already allocated these vectors under the parser allowance;
    // charge them here so the audit total matches the retained graph.
    if let Some(meter) = meter.as_deref_mut() {
        meter.charge_vec::<SectionEntry>(view.sections().len() as u64)?;
        meter.charge_vec::<(u16, u16)>(view.required_features().len() as u64)?;
        meter.charge_vec::<(u16, u16)>(view.optional_features().len() as u64)?;
    }
    let sections = view.sections().to_vec();
    let required = view.required_features().to_vec();
    let optional = view.optional_features().to_vec();
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
        None => {
            if let Some(meter) = meter.as_deref_mut() {
                meter.charge_vec::<u64>(doc_count)?;
                meter.charge_vec::<u64>(doc_count)?;
            }
            DocRemap::identity(doc_count as usize)
        }
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
    // individual column values remain lazily decoded.
    if let Some(body) = view.body(SectionKind::Columns) {
        let _ = ColumnReader::open_with_doc_count(&schema, body, &limits, Some(doc_count))?;
    }
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
    let mut bounds = Vec::with_capacity(count as usize);
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
