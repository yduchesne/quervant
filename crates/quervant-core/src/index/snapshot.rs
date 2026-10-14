//! Immutable reader snapshots over committed or volatile segment bytes (PR 6).
//!
//! A `ReaderSnapshot` owns immutable segment descriptors and `Arc`-held segment
//! bytes. It is `Send + Sync` and remains valid across writer refresh, commit
//! and close. The existing [`crate::segment::SegmentReader`] internally uses
//! `Rc<RefCell<..>>` and is **not** shared across threads; callers construct an
//! independent reader from the snapshot's shared bytes when they need one.
//!
//! Managed reader materialization is bounded: [`ReaderSnapshot::open_segment_reader`]
//! reserves the encoded segment length against a snapshot-shared byte budget
//! **before** cloning the bytes, and returns a [`GuardedSegmentReader`] whose
//! RAII reservation is released on drop. The reservation bounds cloned encoded
//! bytes only — not decoder allocations, process RSS, or raw user clones of
//! [`SegmentSnapshot::bytes`].

use std::collections::BTreeSet;
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_objectstore::ContentDescriptor;

use crate::contract::document::DocumentKey;
use crate::segment::{SegmentLimits, SegmentReader, TimeBounds};

use super::error::{IndexError, IndexResult};
use super::pit::PinCounter;

/// Process-wide monotonic allocator for snapshot identity bindings.
static NEXT_SNAPSHOT_BINDING: AtomicU64 = AtomicU64::new(1);

/// Reserve one nonzero, never-reused snapshot identity.
/// `u64::MAX` is a permanent exhaustion sentinel, never an issued ID.
///
/// Newer toolchains deprecate `AtomicU64::fetch_update` in favour of
/// `AtomicU64::try_update`, but `try_update` is not available on the workspace
/// MSRV (Rust 1.85.0). `fetch_update` is therefore retained with a narrowly
/// scoped allowance; the checked compare-and-swap semantics and all allocator
/// invariants are unchanged.
#[allow(deprecated)]
fn allocate_snapshot_binding(counter: &AtomicU64) -> u64 {
    counter
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
            if current == 0 || current == u64::MAX {
                None
            } else {
                current.checked_add(1)
            }
        })
        .unwrap_or_else(|_| panic!("snapshot binding identifier space exhausted"))
}

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

    /// Open an independent bounded reader over this segment's shared bytes.
    pub(crate) fn open_reader(&self, limits: SegmentLimits) -> IndexResult<SegmentReader> {
        Ok(SegmentReader::open(self.bytes.as_ref().clone(), limits)?)
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

/// A snapshot-shared budget for simultaneous managed reader byte copies.
#[derive(Debug)]
struct ReaderByteBudget {
    used: AtomicU64,
    limit: u64,
}

impl ReaderByteBudget {
    fn new(limit: u64) -> Arc<Self> {
        Arc::new(Self {
            used: AtomicU64::new(0),
            limit,
        })
    }

    /// Reserve `bytes` before a clone, using checked arithmetic and CAS.
    fn try_reserve(&self, bytes: u64) -> IndexResult<()> {
        loop {
            let current = self.used.load(Ordering::Acquire);
            let projected = current
                .checked_add(bytes)
                .ok_or(IndexError::ResourceLimit {
                    limit: self.limit,
                    requested: u64::MAX,
                })?;
            if projected > self.limit {
                return Err(IndexError::ResourceLimit {
                    limit: self.limit,
                    requested: projected,
                });
            }
            if self
                .used
                .compare_exchange_weak(current, projected, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                return Ok(());
            }
        }
    }

    fn release(&self, bytes: u64) {
        // Paired with exactly one successful `try_reserve`.
        self.used.fetch_sub(bytes, Ordering::AcqRel);
    }

    #[cfg(test)]
    fn used(&self) -> u64 {
        self.used.load(Ordering::Acquire)
    }
}

/// RAII release of a managed reader copy reservation.
struct ReaderReservation {
    budget: Arc<ReaderByteBudget>,
    bytes: u64,
}

impl Drop for ReaderReservation {
    fn drop(&mut self) {
        self.budget.release(self.bytes);
    }
}

/// A `SegmentReader` whose encoded-byte copy is charged against a snapshot
/// budget until the guard is dropped.
///
/// The guard is deliberately **not** `Clone` and does not transfer or deref to
/// the owned reader; callers borrow it through [`GuardedSegmentReader::reader`].
pub struct GuardedSegmentReader {
    reader: SegmentReader,
    _reservation: ReaderReservation,
}

impl GuardedSegmentReader {
    /// Borrow the guarded reader.
    #[must_use]
    pub const fn reader(&self) -> &SegmentReader {
        &self.reader
    }
}

impl std::fmt::Debug for GuardedSegmentReader {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("GuardedSegmentReader").finish()
    }
}

/// An immutable, thread-safe view of one generation or volatile refresh.
pub struct ReaderSnapshot {
    generation: Option<u64>,
    view_ordinal: u64,
    binding_id: u64,
    segments: Vec<SegmentSnapshot>,
    masks: Vec<Option<Arc<Vec<bool>>>>,
    document_count: u64,
    resident_bytes: u64,
    segment_limits: SegmentLimits,
    pins: Arc<PinCounter>,
    reader_budget: Arc<ReaderByteBudget>,
}

impl ReaderSnapshot {
    #[allow(dead_code)]
    pub(crate) fn new(
        generation: Option<u64>,
        view_ordinal: u64,
        segments: Vec<SegmentSnapshot>,
        segment_limits: SegmentLimits,
        pins: Arc<PinCounter>,
        reader_copy_limit: u64,
    ) -> Self {
        let masks = vec![None; segments.len()];
        Self::build(
            generation,
            view_ordinal,
            segments,
            masks,
            segment_limits,
            pins,
            reader_copy_limit,
        )
    }

    /// Construct a snapshot with generation-specific effective live masks.
    ///
    /// A `Some(mask)` for a segment must be exactly `doc_count` long; a physical
    /// document is live iff both the segment's own live bitmap and the mask are
    /// true. Mask lengths are validated before publication.
    pub(crate) fn new_with_masks(
        generation: Option<u64>,
        view_ordinal: u64,
        segments: Vec<SegmentSnapshot>,
        masks: Vec<Option<Arc<Vec<bool>>>>,
        segment_limits: SegmentLimits,
        pins: Arc<PinCounter>,
        reader_copy_limit: u64,
    ) -> IndexResult<Self> {
        if masks.len() != segments.len() {
            return Err(IndexError::CorruptCommittedState {
                detail: "snapshot mask count does not match segment count".to_owned(),
            });
        }
        for (segment, mask) in segments.iter().zip(&masks) {
            if let Some(mask) = mask {
                if mask.len() as u64 != segment.doc_count() {
                    return Err(IndexError::CorruptCommittedState {
                        detail: "snapshot mask length does not match segment doc count".to_owned(),
                    });
                }
            }
        }
        Ok(Self::build(
            generation,
            view_ordinal,
            segments,
            masks,
            segment_limits,
            pins,
            reader_copy_limit,
        ))
    }

    fn build(
        generation: Option<u64>,
        view_ordinal: u64,
        segments: Vec<SegmentSnapshot>,
        masks: Vec<Option<Arc<Vec<bool>>>>,
        segment_limits: SegmentLimits,
        pins: Arc<PinCounter>,
        reader_copy_limit: u64,
    ) -> Self {
        let document_count = segments
            .iter()
            .zip(&masks)
            .map(|(segment, mask)| match mask {
                Some(mask) => mask.iter().filter(|flag| **flag).count() as u64,
                None => segment.doc_count(),
            })
            .sum();
        let resident_bytes = segments
            .iter()
            .map(|segment| segment.bytes.len() as u64)
            .sum();
        Self {
            generation,
            view_ordinal,
            binding_id: allocate_snapshot_binding(&NEXT_SNAPSHOT_BINDING),
            segments,
            masks,
            document_count,
            resident_bytes,
            segment_limits,
            pins,
            reader_budget: ReaderByteBudget::new(reader_copy_limit),
        }
    }

    /// The generation-specific effective live mask for `index`, if any.
    #[must_use]
    pub(crate) fn live_mask(&self, index: usize) -> Option<&Arc<Vec<bool>>> {
        self.masks.get(index).and_then(|mask| mask.as_ref())
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

    /// Process-wide unique identity for this snapshot instance.
    ///
    /// All `Arc` clones of one snapshot share the same binding. It is used by
    /// typed search cursors to reject continuation against a different
    /// snapshot; it is not persisted and never leaves the process.
    #[must_use]
    pub const fn binding_id(&self) -> u64 {
        self.binding_id
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

    /// Open a budgeted, RAII-guarded reader over the segment at `index`.
    ///
    /// The encoded byte length is reserved **before** the bytes are cloned; on
    /// any failure the reservation is released by the guard's drop.
    pub fn open_segment_reader(&self, index: usize) -> IndexResult<GuardedSegmentReader> {
        let segment = self
            .segments
            .get(index)
            .ok_or(IndexError::SegmentOutOfRange {
                index,
                count: self.segments.len(),
            })?;
        let bytes = segment.bytes.len() as u64;
        self.reader_budget.try_reserve(bytes)?;
        let reservation = ReaderReservation {
            budget: Arc::clone(&self.reader_budget),
            bytes,
        };
        let reader = SegmentReader::open(segment.bytes.as_ref().clone(), self.segment_limits)?;
        Ok(GuardedSegmentReader {
            reader,
            _reservation: reservation,
        })
    }

    /// The effective live flags for one segment: the segment's own live bitmap
    /// intersected with the generation mask, if present.
    pub(crate) fn effective_live_docs(
        &self,
        index: usize,
        reader: &SegmentReader,
    ) -> IndexResult<Rc<Vec<bool>>> {
        if index >= self.segments.len() {
            return Err(IndexError::SegmentOutOfRange {
                index,
                count: self.segments.len(),
            });
        }
        let base = reader.live_docs()?;
        match self.live_mask(index) {
            Some(mask) => {
                let combined: Vec<bool> = base
                    .iter()
                    .zip(mask.iter())
                    .map(|(live, masked)| *live && *masked)
                    .collect();
                Ok(Rc::new(combined))
            }
            None => Ok(base),
        }
    }

    /// All stored logical document keys, in segment-then-physical order.
    pub fn stored_keys(&self) -> IndexResult<Vec<DocumentKey>> {
        let mut keys: Vec<DocumentKey> = Vec::new();
        keys.try_reserve(usize::try_from(self.document_count).unwrap_or(usize::MAX))
            .map_err(|_| IndexError::ResourceLimit {
                limit: self.document_count,
                requested: self.document_count,
            })?;
        for index in 0..self.segments.len() {
            let guard = self.open_segment_reader(index)?;
            for record in guard.reader().stored()?.iter() {
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
        for index in 0..self.segments.len() {
            let guard = self.open_segment_reader(index)?;
            for record in guard.reader().stored()?.iter() {
                if &record.key == key {
                    return Ok(true);
                }
            }
        }
        Ok(false)
    }

    /// Currently reserved managed reader-copy bytes.
    #[cfg(test)]
    #[must_use]
    pub(crate) fn reader_copy_used(&self) -> u64 {
        self.reader_budget.used()
    }

    pub(crate) fn release_pin(&self) {
        self.pins.release();
    }

    pub(crate) fn try_pin(&self) -> IndexResult<Option<String>> {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn invalid_segment(len: usize) -> SegmentSnapshot {
        let bytes = Arc::new(vec![0u8; len]);
        let meta = SegmentMeta::new(
            "s-test",
            "index/segments/test.seg",
            ContentDescriptor::of(&bytes),
            Vec::new(),
            Vec::new(),
            None,
        );
        SegmentSnapshot::new(meta, bytes, 0)
    }

    fn pins() -> Arc<PinCounter> {
        PinCounter::new(1).unwrap()
    }

    #[test]
    fn reader_budget_exact_and_one_over() {
        let budget = ReaderByteBudget::new(100);
        budget.try_reserve(100).unwrap();
        assert_eq!(budget.used(), 100);
        assert!(matches!(
            budget.try_reserve(1),
            Err(IndexError::ResourceLimit { .. })
        ));
        budget.release(100);
        assert_eq!(budget.used(), 0);
        budget.try_reserve(100).unwrap();
    }

    #[test]
    fn reader_budget_overflow_fails_closed() {
        let budget = ReaderByteBudget::new(u64::MAX);
        budget.try_reserve(u64::MAX).unwrap();
        let error = budget.try_reserve(1).unwrap_err();
        assert!(matches!(error, IndexError::ResourceLimit { .. }));
    }

    #[test]
    fn decoder_failure_releases_reservation() {
        let snapshot = ReaderSnapshot::new(
            None,
            0,
            vec![invalid_segment(64)],
            SegmentLimits::default(),
            pins(),
            1024,
        );
        assert!(matches!(
            snapshot.open_segment_reader(0),
            Err(IndexError::Segment(_))
        ));
        assert_eq!(snapshot.reader_copy_used(), 0);
    }

    #[test]
    fn out_of_range_index_is_typed() {
        let snapshot =
            ReaderSnapshot::new(None, 0, Vec::new(), SegmentLimits::default(), pins(), 1024);
        assert!(matches!(
            snapshot.open_segment_reader(0),
            Err(IndexError::SegmentOutOfRange { index: 0, count: 0 })
        ));
    }

    #[test]
    fn reservation_is_released_on_guard_drop() {
        // A valid reader cannot be built from zeros, so exercise the budget and
        // guard directly through the budget API.
        let budget = ReaderByteBudget::new(64);
        budget.try_reserve(64).unwrap();
        {
            let _reservation = ReaderReservation {
                budget: Arc::clone(&budget),
                bytes: 64,
            };
            assert_eq!(budget.used(), 64);
        }
        assert_eq!(budget.used(), 0);
    }

    const EXHAUSTED_MESSAGE: &str = "snapshot binding identifier space exhausted";

    fn panic_text(result: std::thread::Result<u64>) -> String {
        match result {
            Ok(id) => panic!("expected exhaustion panic, got id {id}"),
            Err(payload) => {
                if let Some(text) = payload.downcast_ref::<&str>() {
                    (*text).to_owned()
                } else if let Some(text) = payload.downcast_ref::<String>() {
                    text.clone()
                } else {
                    panic!("unexpected panic payload type")
                }
            }
        }
    }

    // A1-T01 — sequential allocation is strictly increasing and nonzero.
    #[test]
    fn snapshot_binding_allocates_monotonically() {
        let counter = AtomicU64::new(1);
        assert_eq!(allocate_snapshot_binding(&counter), 1);
        assert_eq!(allocate_snapshot_binding(&counter), 2);
        assert_eq!(allocate_snapshot_binding(&counter), 3);
        assert_eq!(counter.load(Ordering::Relaxed), 4);
    }

    // A1-T02 — near-exhaustion issues MAX-2 then MAX-1, leaving the sentinel.
    #[test]
    fn snapshot_binding_near_exhaustion() {
        let counter = AtomicU64::new(u64::MAX - 2);
        assert_eq!(allocate_snapshot_binding(&counter), u64::MAX - 2);
        assert_eq!(allocate_snapshot_binding(&counter), u64::MAX - 1);
        assert_eq!(counter.load(Ordering::Relaxed), u64::MAX);
    }

    // A1-T03 — MAX-1 is the last success; the next call panics and leaves the sentinel.
    #[test]
    fn snapshot_binding_exhaustion_after_last_success() {
        let counter = AtomicU64::new(u64::MAX - 1);
        assert_eq!(allocate_snapshot_binding(&counter), u64::MAX - 1);
        assert_eq!(counter.load(Ordering::Relaxed), u64::MAX);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            allocate_snapshot_binding(&counter)
        }));
        assert_eq!(panic_text(result), EXHAUSTED_MESSAGE);
        assert_eq!(counter.load(Ordering::Relaxed), u64::MAX);
    }

    // A1-T04 — reserved `0` and the exhausted sentinel are rejected without change.
    #[test]
    fn snapshot_binding_rejects_reserved_and_exhausted() {
        let zero = AtomicU64::new(0);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            allocate_snapshot_binding(&zero)
        }));
        assert_eq!(panic_text(result), EXHAUSTED_MESSAGE);
        assert_eq!(zero.load(Ordering::Relaxed), 0);

        let exhausted = AtomicU64::new(u64::MAX);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            allocate_snapshot_binding(&exhausted)
        }));
        assert_eq!(panic_text(result), EXHAUSTED_MESSAGE);
        assert_eq!(exhausted.load(Ordering::Relaxed), u64::MAX);
    }

    // A1-T05 — concurrent allocation cannot duplicate IDs.
    #[test]
    fn snapshot_binding_concurrent_uniqueness() {
        let counter = Arc::new(AtomicU64::new(1));
        let mut handles = Vec::new();
        for _ in 0..8 {
            let counter = Arc::clone(&counter);
            handles.push(std::thread::spawn(move || {
                let mut ids = Vec::with_capacity(1_000);
                for _ in 0..1_000 {
                    ids.push(allocate_snapshot_binding(&counter));
                }
                ids
            }));
        }
        let mut all = Vec::new();
        for handle in handles {
            all.extend(handle.join().expect("worker thread"));
        }
        all.sort_unstable();
        let expected: Vec<u64> = (1..=8_000).collect();
        assert_eq!(all, expected);
        assert_eq!(counter.load(Ordering::Relaxed), 8_001);
    }

    // A1-T05b — racing contenders at the boundary get exactly the remaining
    // IDs; the rest panic and the sentinel is unchanged.
    #[test]
    fn snapshot_binding_concurrent_near_exhaustion() {
        let counter = Arc::new(AtomicU64::new(u64::MAX - 4));
        let barrier = Arc::new(std::sync::Barrier::new(8));
        let mut handles = Vec::new();
        for _ in 0..8 {
            let counter = Arc::clone(&counter);
            let barrier = Arc::clone(&barrier);
            handles.push(std::thread::spawn(move || {
                barrier.wait();
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    allocate_snapshot_binding(&counter)
                }))
            }));
        }
        let mut successes = Vec::new();
        let mut panics = 0usize;
        for handle in handles {
            match handle.join().expect("worker thread") {
                Ok(id) => successes.push(id),
                Err(payload) => {
                    panics += 1;
                    let text = if let Some(text) = payload.downcast_ref::<&str>() {
                        (*text).to_owned()
                    } else if let Some(text) = payload.downcast_ref::<String>() {
                        text.clone()
                    } else {
                        panic!("unexpected panic payload type")
                    };
                    assert_eq!(text, EXHAUSTED_MESSAGE);
                }
            }
        }
        successes.sort_unstable();
        assert_eq!(
            successes,
            vec![u64::MAX - 4, u64::MAX - 3, u64::MAX - 2, u64::MAX - 1]
        );
        assert_eq!(panics, 4);
        assert_eq!(counter.load(Ordering::Relaxed), u64::MAX);
    }

    // A1-T06 — distinct snapshots receive distinct nonzero bindings even with
    // identical generation and view ordinal.
    #[test]
    fn snapshot_binding_distinct_snapshot_identity() {
        let first =
            ReaderSnapshot::new(None, 7, Vec::new(), SegmentLimits::default(), pins(), 1024);
        let second =
            ReaderSnapshot::new(None, 7, Vec::new(), SegmentLimits::default(), pins(), 1024);
        assert_ne!(first.binding_id(), 0);
        assert_ne!(second.binding_id(), 0);
        assert_ne!(first.binding_id(), second.binding_id());
        assert_eq!(first.generation(), second.generation());
        assert_eq!(first.view_ordinal(), second.view_ordinal());
    }

    // A1-T07 — an `Arc` clone shares the binding and allocates no new ID.
    #[test]
    fn snapshot_binding_arc_clone_identity() {
        let snapshot = Arc::new(ReaderSnapshot::new(
            None,
            0,
            Vec::new(),
            SegmentLimits::default(),
            pins(),
            1024,
        ));
        let before = NEXT_SNAPSHOT_BINDING.load(Ordering::Relaxed);
        let clone = Arc::clone(&snapshot);
        assert_eq!(clone.binding_id(), snapshot.binding_id());
        let after = NEXT_SNAPSHOT_BINDING.load(Ordering::Relaxed);
        assert_eq!(before, after);
    }
}
