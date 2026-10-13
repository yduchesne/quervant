//! Immutable reader snapshots over committed or volatile segment bytes (PR 6).
//!
//! A `ReaderSnapshot` owns immutable segment descriptors and `Arc`-held segment
//! bytes. It is `Send + Sync` and remains valid across writer refresh, commit
//! and close. The existing [`crate::segment::SegmentReader`] internally uses
//! `Rc<RefCell<..>>` and is **not** shared across threads; callers construct an
//! independent reader from the snapshot's shared bytes when they need one.

use std::collections::BTreeSet;
use std::sync::Arc;

use quervant_objectstore::ContentDescriptor;

use crate::contract::document::DocumentKey;
use crate::segment::{SegmentError, SegmentLimits, SegmentReader, TimeBounds};

use super::error::IndexResult;
use super::pit::PinCounter;

/// The immutable identity and declared features of one segment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SegmentMeta {
    segment_id: String,
    object_key: String,
    descriptor: ContentDescriptor,
    required_features: Vec<(u16, u16)>,
    optional_features: Vec<(u16, u16)>,
    time_bounds: Option<TimeBounds>,
}

impl SegmentMeta {
    /// Construct a segment descriptor.
    #[must_use]
    pub fn new(
        segment_id: impl Into<String>,
        object_key: impl Into<String>,
        descriptor: ContentDescriptor,
        required_features: Vec<(u16, u16)>,
        optional_features: Vec<(u16, u16)>,
        time_bounds: Option<TimeBounds>,
    ) -> Self {
        Self {
            segment_id: segment_id.into(),
            object_key: object_key.into(),
            descriptor,
            required_features,
            optional_features,
            time_bounds,
        }
    }

    /// Logical segment id.
    #[must_use]
    pub fn segment_id(&self) -> &str {
        &self.segment_id
    }

    /// Authoritative object key.
    #[must_use]
    pub fn object_key(&self) -> &str {
        &self.object_key
    }

    /// Content identity (exact length plus SHA-256).
    #[must_use]
    pub const fn descriptor(&self) -> ContentDescriptor {
        self.descriptor
    }

    /// Required segment features.
    #[must_use]
    pub fn required_features(&self) -> &[(u16, u16)] {
        &self.required_features
    }

    /// Optional segment features.
    #[must_use]
    pub fn optional_features(&self) -> &[(u16, u16)] {
        &self.optional_features
    }

    /// Temporal bounds, if any.
    #[must_use]
    pub const fn time_bounds(&self) -> Option<&TimeBounds> {
        self.time_bounds.as_ref()
    }
}

/// One immutable segment held by a snapshot.
#[derive(Clone)]
pub struct SegmentSnapshot {
    meta: SegmentMeta,
    bytes: Arc<Vec<u8>>,
    doc_count: u64,
}

impl SegmentSnapshot {
    /// Construct a segment snapshot from verified or freshly built bytes.
    #[must_use]
    pub fn new(meta: SegmentMeta, bytes: Arc<Vec<u8>>, doc_count: u64) -> Self {
        Self {
            meta,
            bytes,
            doc_count,
        }
    }

    /// The segment descriptor.
    #[must_use]
    pub const fn meta(&self) -> &SegmentMeta {
        &self.meta
    }

    /// The immutable segment bytes.
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.bytes.as_slice()
    }

    /// Shared immutable segment bytes.
    #[must_use]
    pub const fn shared_bytes(&self) -> &Arc<Vec<u8>> {
        &self.bytes
    }

    /// Number of physical (live) documents in this segment.
    #[must_use]
    pub const fn doc_count(&self) -> u64 {
        self.doc_count
    }

    /// Open an independent bounded reader over a clone of these bytes.
    pub fn reader(&self, limits: SegmentLimits) -> Result<SegmentReader, SegmentError> {
        SegmentReader::open(self.bytes.as_ref().clone(), limits)
    }
}

impl std::fmt::Debug for SegmentSnapshot {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SegmentSnapshot")
            .field("segment_id", &self.meta.segment_id)
            .field("doc_count", &self.doc_count)
            .field("bytes", &self.bytes.len())
            .finish()
    }
}

/// An immutable, thread-safe view of one generation or volatile refresh.
pub struct ReaderSnapshot {
    generation: Option<u64>,
    view_ordinal: u64,
    segments: Vec<SegmentSnapshot>,
    document_count: u64,
    resident_bytes: u64,
    segment_limits: SegmentLimits,
    pins: Arc<PinCounter>,
}

impl ReaderSnapshot {
    pub(crate) fn new(
        generation: Option<u64>,
        view_ordinal: u64,
        segments: Vec<SegmentSnapshot>,
        segment_limits: SegmentLimits,
        pins: Arc<PinCounter>,
    ) -> Self {
        let document_count = segments.iter().map(SegmentSnapshot::doc_count).sum();
        let resident_bytes = segments
            .iter()
            .map(|segment| segment.bytes.len() as u64)
            .sum();
        Self {
            generation,
            view_ordinal,
            segments,
            document_count,
            resident_bytes,
            segment_limits,
            pins,
        }
    }

    /// The committed generation, or `None` for a volatile pre-commit view.
    #[must_use]
    pub const fn generation(&self) -> Option<u64> {
        self.generation
    }

    /// Process-local monotonic view ordinal.
    #[must_use]
    pub const fn view_ordinal(&self) -> u64 {
        self.view_ordinal
    }

    /// Number of segments in this view.
    #[must_use]
    pub fn segment_count(&self) -> usize {
        self.segments.len()
    }

    /// Total live documents in this view.
    #[must_use]
    pub const fn document_count(&self) -> u64 {
        self.document_count
    }

    /// Total resident segment bytes in this view.
    #[must_use]
    pub const fn resident_bytes(&self) -> u64 {
        self.resident_bytes
    }

    /// The segments in canonical order.
    #[must_use]
    pub fn segments(&self) -> &[SegmentSnapshot] {
        &self.segments
    }

    /// Segment codec limits used by this snapshot.
    #[must_use]
    pub const fn segment_limits(&self) -> &SegmentLimits {
        &self.segment_limits
    }

    /// All stored logical document keys, in segment-then-physical order.
    pub fn stored_keys(&self) -> IndexResult<Vec<DocumentKey>> {
        let mut keys = Vec::with_capacity(self.document_count as usize);
        for segment in &self.segments {
            let reader = segment.reader(self.segment_limits)?;
            for record in reader.stored()?.iter() {
                keys.push(record.key.clone());
            }
        }
        Ok(keys)
    }

    /// The distinct set of stored logical document keys.
    pub fn stored_key_set(&self) -> IndexResult<BTreeSet<DocumentKey>> {
        Ok(self.stored_keys()?.into_iter().collect())
    }

    /// Whether the snapshot contains `key`.
    pub fn contains_key(&self, key: &DocumentKey) -> IndexResult<bool> {
        for segment in &self.segments {
            let reader = segment.reader(self.segment_limits)?;
            for record in reader.stored()?.iter() {
                if &record.key == key {
                    return Ok(true);
                }
            }
        }
        Ok(false)
    }

    pub(crate) fn release_pin(&self) {
        self.pins.release();
    }

    pub(crate) fn try_pin(&self) -> Option<String> {
        self.pins.try_pin()
    }

    pub(crate) fn pin_limit(&self) -> u64 {
        u64::try_from(self.pins.max()).unwrap_or(u64::MAX)
    }
}

impl std::fmt::Debug for ReaderSnapshot {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ReaderSnapshot")
            .field("generation", &self.generation)
            .field("view_ordinal", &self.view_ordinal)
            .field("segments", &self.segments.len())
            .field("document_count", &self.document_count)
            .finish()
    }
}
