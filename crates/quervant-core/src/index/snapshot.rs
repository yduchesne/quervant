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
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, PoisonError};

use quervant_objectstore::ContentDescriptor;

use crate::contract::document::DocumentKey;
use crate::segment::metadata::MetadataBudget;
use crate::segment::reader::VerifiedSegmentState;
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

/// Publication state of one snapshot-scoped segment cache slot.
enum SlotState {
    /// No verified state yet.
    Empty,
    /// One caller is validating and constructing the candidate state.
    Building,
    /// A fully validated immutable state is published.
    Ready(Arc<VerifiedSegmentState>),
}

/// One segment's verified immutable state slot.
///
/// The mutex guards only the state transition; hashing, decoding, allocation and
/// query execution always happen outside it.
struct SegmentCacheSlot {
    state: Mutex<SlotState>,
    ready: Condvar,
}

impl SegmentCacheSlot {
    fn new() -> Self {
        Self {
            state: Mutex::new(SlotState::Empty),
            ready: Condvar::new(),
        }
    }
}

/// Deterministic fail-closed error for a poisoned slot lock.
///
/// Adding a new public error variant would change the public error contract, so
/// the existing typed internal-state variant is used; the slot is never trusted
/// after poisoning.
fn cache_poisoned() -> IndexError {
    IndexError::CorruptCommittedState {
        detail: "segment reader cache lock poisoned".to_owned(),
    }
}

fn lock_slot(slot: &SegmentCacheSlot) -> IndexResult<MutexGuard<'_, SlotState>> {
    slot.state.lock().map_err(|_| cache_poisoned())
}

/// Restores `Building -> Empty` and wakes all waiters on error or unwind.
///
/// A poisoned lock is recovered here only to perform the cleanup transition; it
/// never publishes or serves any state.
struct SlotBuildGuard<'a> {
    slot: &'a SegmentCacheSlot,
    armed: bool,
}

impl<'a> SlotBuildGuard<'a> {
    fn new(slot: &'a SegmentCacheSlot) -> Self {
        Self { slot, armed: true }
    }

    /// Publication succeeded: no reset is required.
    fn disarm(mut self) {
        self.armed = false;
    }
}

impl Drop for SlotBuildGuard<'_> {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let mut state = self
            .slot
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if matches!(&*state, SlotState::Building) {
            *state = SlotState::Empty;
            drop(state);
            self.slot.ready.notify_all();
        }
    }
}

/// Test-only deterministic build fault injection.
#[cfg(test)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum BuildFault {
    /// No fault.
    None,
    /// Fail verification with a typed error.
    Fail,
    /// Panic during verification (unwind cleanup path).
    Panic,
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
    metadata_budget: Arc<MetadataBudget>,
    slots: Vec<SegmentCacheSlot>,
    #[cfg(test)]
    verifications: AtomicU64,
    #[cfg(test)]
    build_fault: AtomicU64,
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
        // G2-01: the retained-metadata cap is exactly the reader-copy limit.
        Self::build_with_metadata_cap(
            generation,
            view_ordinal,
            segments,
            masks,
            segment_limits,
            pins,
            reader_copy_limit,
            reader_copy_limit,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn build_with_metadata_cap(
        generation: Option<u64>,
        view_ordinal: u64,
        segments: Vec<SegmentSnapshot>,
        masks: Vec<Option<Arc<Vec<bool>>>>,
        segment_limits: SegmentLimits,
        pins: Arc<PinCounter>,
        reader_copy_limit: u64,
        metadata_cap: u64,
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
        let slots = (0..segments.len())
            .map(|_| SegmentCacheSlot::new())
            .collect();
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
            metadata_budget: MetadataBudget::new(metadata_cap),
            slots,
            #[cfg(test)]
            verifications: AtomicU64::new(0),
            #[cfg(test)]
            build_fault: AtomicU64::new(0),
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
    /// The encoded byte length is reserved **before** any reader is acquired; a
    /// cache hit does not remove or reduce that active-reader admission charge.
    /// On any failure the reservation is released by the guard's drop.
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
        let reader = self.acquire_reader(index, segment)?;
        Ok(GuardedSegmentReader {
            reader,
            _reservation: reservation,
        })
    }

    /// Acquire a query-local reader, reusing the snapshot-scoped verified state
    /// when it has been admitted and published.
    fn acquire_reader(
        &self,
        index: usize,
        segment: &SegmentSnapshot,
    ) -> IndexResult<SegmentReader> {
        // `metadata_cap == 0` disables reuse and always takes the independently
        // verified uncached path.
        if self.metadata_budget.limit() == 0 {
            return Ok(SegmentReader::open(
                segment.bytes.as_ref().clone(),
                self.segment_limits,
            )?);
        }
        let slot = &self.slots[index];
        loop {
            let mut state = lock_slot(slot)?;
            if let SlotState::Ready(shared) = &*state {
                let shared = Arc::clone(shared);
                drop(state);
                return Ok(SegmentReader::from_shared(shared));
            }
            if matches!(&*state, SlotState::Building) {
                // Spurious wakeups are allowed: the predicate is rechecked.
                let state = slot.ready.wait(state).map_err(|_| cache_poisoned())?;
                drop(state);
                continue;
            }
            *state = SlotState::Building;
            drop(state);
            break;
        }

        // Construction runs with no slot lock held. The RAII guard restores
        // `Empty` and wakes waiters on error, panic or unwind.
        let build_guard = SlotBuildGuard::new(slot);
        match self.build_verified_state(segment) {
            Ok(Some(shared)) => {
                let published = Arc::clone(&shared);
                let mut state = lock_slot(slot)?;
                *state = SlotState::Ready(shared);
                drop(state);
                slot.ready.notify_all();
                build_guard.disarm();
                #[cfg(test)]
                self.verifications.fetch_add(1, Ordering::AcqRel);
                Ok(SegmentReader::from_shared(published))
            }
            Ok(None) => {
                // Optional cache-capacity or allocation failure: release all
                // charges, wake waiters and use the verified uncached reader.
                drop(build_guard);
                Ok(SegmentReader::open(
                    segment.bytes.as_ref().clone(),
                    self.segment_limits,
                )?)
            }
            Err(error) => {
                // True corruption: propagate the original typed error.
                drop(build_guard);
                Err(error)
            }
        }
    }

    /// Build a charged candidate state outside any slot lock.
    fn build_verified_state(
        &self,
        segment: &SegmentSnapshot,
    ) -> IndexResult<Option<Arc<VerifiedSegmentState>>> {
        #[cfg(test)]
        match self.build_fault() {
            BuildFault::None => {}
            BuildFault::Fail => {
                return Err(IndexError::CorruptCommittedState {
                    detail: "injected segment verification failure".to_owned(),
                });
            }
            BuildFault::Panic => panic!("injected segment verification panic"),
        }
        Ok(VerifiedSegmentState::build_cached(
            Arc::clone(segment.shared_bytes()),
            self.segment_limits,
            &self.metadata_budget,
        )?)
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

    /// Build a snapshot with independently chosen admission and metadata caps.
    ///
    /// Test-only: production construction always sets
    /// `metadata_cap = reader_copy_limit`.
    #[cfg(test)]
    pub(crate) fn for_test(
        segments: Vec<SegmentSnapshot>,
        segment_limits: SegmentLimits,
        reader_copy_limit: u64,
        metadata_cap: u64,
    ) -> Self {
        let masks = vec![None; segments.len()];
        Self::build_with_metadata_cap(
            None,
            0,
            segments,
            masks,
            segment_limits,
            PinCounter::new(1).expect("pin counter"),
            reader_copy_limit,
            metadata_cap,
        )
    }

    /// Currently reserved retained-metadata bytes.
    #[cfg(test)]
    #[must_use]
    pub(crate) fn metadata_used(&self) -> u64 {
        self.metadata_budget.used()
    }

    /// The retained-metadata budget handle (survives snapshot drop).
    #[cfg(test)]
    pub(crate) fn metadata_budget_handle(&self) -> Arc<MetadataBudget> {
        Arc::clone(&self.metadata_budget)
    }

    /// Number of successful verifications published by this snapshot.
    #[cfg(test)]
    pub(crate) fn verification_count(&self) -> u64 {
        self.verifications.load(Ordering::Acquire)
    }

    /// Install a deterministic test-only build fault.
    #[cfg(test)]
    pub(crate) fn set_build_fault(&self, fault: BuildFault) {
        let raw = match fault {
            BuildFault::None => 0,
            BuildFault::Fail => 1,
            BuildFault::Panic => 2,
        };
        self.build_fault.store(raw, Ordering::Release);
    }

    #[cfg(test)]
    fn build_fault(&self) -> BuildFault {
        match self.build_fault.load(Ordering::Acquire) {
            1 => BuildFault::Fail,
            2 => BuildFault::Panic,
            _ => BuildFault::None,
        }
    }

    /// Whether the segment slot currently holds a published verified state.
    #[cfg(test)]
    pub(crate) fn slot_is_ready(&self, index: usize) -> bool {
        self.slots
            .get(index)
            .and_then(|slot| slot.state.lock().ok())
            .map(|state| matches!(&*state, SlotState::Ready(_)))
            .unwrap_or(false)
    }

    /// Whether the slot lock is free (no execution/initialization lock held).
    #[cfg(test)]
    pub(crate) fn slot_is_unlocked(&self, index: usize) -> bool {
        self.slots
            .get(index)
            .map(|slot| slot.state.try_lock().is_ok())
            .unwrap_or(false)
    }

    /// Poison one slot's lock deterministically.
    #[cfg(test)]
    pub(crate) fn poison_slot(&self, index: usize) {
        let slot = &self.slots[index];
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = slot.state.lock().expect("slot lock");
            panic!("poison slot lock");
        }));
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

#[cfg(test)]
mod verified_state_cache {
    //! PR 15C-A — snapshot-scoped verified immutable segment-state reuse.
    //!
    //! Covers G1 (field split and traits), G2 (accounted retained metadata and
    //! fallback), G3 (integrity provenance and snapshot isolation) and G4 (slot
    //! initialization, failure, poison and unwind).

    use std::sync::{Arc, Barrier};

    use super::*;
    use crate::analysis::AnalyzerRegistry;
    use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{
        FieldType, FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp,
    };
    use crate::segment::dictionary::DictionaryEntry;
    use crate::segment::format::{SectionKind, sha256};
    use crate::segment::json_paths::JsonPathDirectory;
    use crate::segment::spatial::SpatialNode;
    use crate::segment::{Layout, SegmentBuilder, SegmentDocument, SegmentLimits};
    use crate::storage::{Directory, MemoryDirectory, StorageKey};

    /// Compile-time `Send + Sync` probe (G1-01).
    fn assert_send_sync<T: Send + Sync>() {}

    fn fixture_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "body",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard"),
                FieldDefinition::new(
                    "host",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "meta",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "loc",
                    FieldType::GeoPoint,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "when",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "count",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
            ],
            Some("when".to_owned()),
        )
        .expect("fixture schema")
    }

    fn json_doc(severity: i64) -> JsonValue {
        JsonValue::Object(vec![
            (
                "severity".to_owned(),
                JsonValue::Number(JsonNumber::I64(severity)),
            ),
            (
                "tags".to_owned(),
                JsonValue::Array(vec![
                    JsonValue::String("red".to_owned()),
                    JsonValue::String("blue".to_owned()),
                ]),
            ),
        ])
    }

    /// A segment exercising every decoded immutable metadata type: schema with
    /// analyzer/normalizer bindings, dictionary terms, BM25 norms, doc remap,
    /// JSON-path directory, spatial KD trees, geo and temporal bounds.
    fn fixture_segment() -> (Vec<u8>, u64) {
        let mut builder = SegmentBuilder::new(fixture_schema(), AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion);
        for (index, key) in ["alpha", "beta", "gamma"].iter().enumerate() {
            let mut doc = SegmentDocument::new(DocumentKey::new(*key).expect("key"));
            doc.insert(
                "body",
                FieldValues::Single(FieldValue::Text("alpha beta gamma".to_owned())),
            )
            .expect("body");
            doc.insert(
                "host",
                FieldValues::Single(FieldValue::Keyword(format!("h{index}"))),
            )
            .expect("host");
            doc.insert(
                "meta",
                FieldValues::Single(FieldValue::Json(json_doc(index as i64))),
            )
            .expect("meta");
            doc.insert(
                "loc",
                FieldValues::Single(FieldValue::GeoPoint(
                    GeoPoint::new(-122.4 + index as f64, 37.8 + index as f64).expect("geo"),
                )),
            )
            .expect("loc");
            doc.insert(
                "when",
                FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(
                    1_000 + index as i64,
                ))),
            )
            .expect("when");
            doc.insert(
                "count",
                FieldValues::Single(FieldValue::I64(index as i64 * 7)),
            )
            .expect("count");
            builder.add_document(doc).expect("add");
        }
        let built = builder.build().expect("build");
        (built.bytes, 3)
    }

    /// A legacy-shaped segment: no scoring fields, no JSON, no geo, no bounds.
    fn legacy_segment() -> (Vec<u8>, u64) {
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            )],
            None,
        )
        .expect("legacy schema");
        let mut builder = SegmentBuilder::new(schema, AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion);
        let mut doc = SegmentDocument::new(DocumentKey::new("only").expect("key"));
        doc.insert("n", FieldValues::Single(FieldValue::I64(7)))
            .expect("n");
        builder.add_document(doc).expect("add");
        let built = builder.build().expect("build");
        (built.bytes, 1)
    }

    fn segment_snapshot(bytes: Vec<u8>, doc_count: u64, id: &str) -> SegmentSnapshot {
        let bytes = Arc::new(bytes);
        let meta = SegmentMeta::new(
            id,
            format!("index/segments/{id}.seg"),
            ContentDescriptor::of(&bytes),
            Vec::new(),
            Vec::new(),
            None,
        );
        SegmentSnapshot::new(meta, bytes, doc_count)
    }

    fn snapshot_of(
        bytes: Vec<u8>,
        doc_count: u64,
        admission: u64,
        metadata_cap: u64,
    ) -> ReaderSnapshot {
        ReaderSnapshot::for_test(
            vec![segment_snapshot(bytes, doc_count, "s-test")],
            SegmentLimits::default(),
            admission,
            metadata_cap,
        )
    }

    fn cached_snapshot() -> (ReaderSnapshot, Vec<u8>, u64) {
        let (bytes, doc_count) = fixture_segment();
        (
            snapshot_of(bytes.clone(), doc_count, 1 << 22, 1 << 22),
            bytes,
            doc_count,
        )
    }

    // -----------------------------------------------------------------------
    // G1 — extraction, traits, query-local caches, compatibility
    // -----------------------------------------------------------------------

    // G1-01 / VSR-I04 — compile-time thread-safety proof for shared state.
    #[test]
    fn g1_01_verified_state_and_snapshot_are_send_sync() {
        assert_send_sync::<VerifiedSegmentState>();
        assert_send_sync::<ReaderSnapshot>();
        assert_send_sync::<Arc<VerifiedSegmentState>>();
    }

    // G1-02 — every acquired reader owns independent query-local caches.
    #[test]
    fn g1_02_query_local_caches_are_per_reader() {
        let (snapshot, _, _) = cached_snapshot();
        let first = snapshot.open_segment_reader(0).expect("first");
        let second = snapshot.open_segment_reader(0).expect("second");
        let first_stored = first.reader().stored().expect("stored");
        let first_stored_again = first.reader().stored().expect("stored again");
        let second_stored = second.reader().stored().expect("stored");
        // Within one reader the Rc is reused …
        assert!(Rc::ptr_eq(&first_stored, &first_stored_again));
        // … but never shared with another reader.
        assert!(!Rc::ptr_eq(&first_stored, &second_stored));
        assert_eq!(*first_stored, *second_stored);
        let first_keys = first.reader().doc_keys().expect("keys");
        let second_keys = second.reader().doc_keys().expect("keys");
        assert!(!Rc::ptr_eq(&first_keys, &second_keys));
        assert_eq!(*first_keys, *second_keys);
        let first_live = first.reader().live_docs().expect("live");
        let second_live = second.reader().live_docs().expect("live");
        assert!(!Rc::ptr_eq(&first_live, &second_live));
        assert_eq!(*first_live, *second_live);
        // The shared immutable state is reused.
        assert!(Arc::ptr_eq(
            first.reader().shared_state(),
            second.reader().shared_state()
        ));
    }

    // G1-03 — standalone constructor and `open_directory` stay fully validating.
    #[test]
    fn g1_03_standalone_and_directory_open_unchanged() {
        let (snapshot, bytes, doc_count) = cached_snapshot();
        let cached = snapshot.open_segment_reader(0).expect("cached");
        let standalone =
            SegmentReader::open(bytes.clone(), SegmentLimits::default()).expect("standalone");
        assert_eq!(standalone.doc_count(), doc_count);
        assert_eq!(standalone.doc_count(), cached.reader().doc_count());
        assert_eq!(
            *standalone.doc_keys().expect("keys"),
            *cached.reader().doc_keys().expect("keys")
        );
        assert_eq!(
            standalone.required_features(),
            cached.reader().required_features()
        );
        assert_eq!(
            standalone.sections().len(),
            cached.reader().sections().len()
        );
        assert_eq!(standalone.schema(), cached.reader().schema());

        let directory = MemoryDirectory::new();
        let key = StorageKey::parse("index/segments/s-test.seg").expect("key");
        directory
            .atomic_write(&key, &bytes)
            .expect("write fixture segment");
        let from_directory =
            SegmentReader::open_directory(&directory, &key, SegmentLimits::default())
                .expect("open_directory");
        assert_eq!(from_directory.doc_count(), doc_count);
        assert_eq!(
            standalone
                .postings(0, "alpha")
                .expect("standalone postings")
                .is_some(),
            from_directory
                .postings(0, "alpha")
                .expect("directory postings")
                .is_some()
        );
        // Repository `Directory` object: unused variable guard for the trait import.
        let _: &dyn Directory = &directory;
    }

    // G1-04 — legacy/historical segment shapes are unchanged.
    #[test]
    fn g1_04_legacy_segment_features_unchanged() {
        // A builder-produced segment without JSON paths, spatial trees, bounds or
        // a dictionary: every optional accessor must report absence.
        let (bytes, doc_count) = legacy_segment();
        let snapshot = snapshot_of(bytes.clone(), doc_count, 1 << 22, 1 << 22);
        let guard = snapshot.open_segment_reader(0).expect("reader");
        let reader = guard.reader();
        assert_eq!(
            reader.field_norms().map(|norms| norms.field_ids().count()),
            Some(0)
        );
        assert!(reader.dictionary().is_none());
        assert!(reader.spatial().is_none());
        assert!(reader.time_bounds().is_none());
        assert!(reader.geo_bounds().is_empty());
        assert!(reader.open_json_paths().expect("json paths").is_none());
        assert!(reader.open_columns().expect("columns").is_some());
        let standalone =
            SegmentReader::open(bytes.clone(), SegmentLimits::default()).expect("standalone");
        assert_eq!(
            *reader.doc_keys().expect("keys"),
            *standalone.doc_keys().expect("keys")
        );

        // The frozen legacy golden fixture predates BM25 norms: the cached and
        // uncached paths must both report the absence.
        const LEGACY_GOLDEN: &[u8] = include_bytes!("../../tests/fixtures/segment/golden.seg");
        let legacy = SegmentReader::open(LEGACY_GOLDEN.to_vec(), SegmentLimits::default())
            .expect("legacy golden");
        assert!(legacy.field_norms().is_none());
        let golden_count = legacy.doc_count();
        let golden = snapshot_of(LEGACY_GOLDEN.to_vec(), golden_count, 1 << 22, 1 << 22);
        let golden_guard = golden.open_segment_reader(0).expect("cached legacy golden");
        assert!(golden_guard.reader().field_norms().is_none());
        assert_eq!(golden_guard.reader().doc_count(), golden_count);
        assert_eq!(golden.verification_count(), 1);
    }

    // G1-05 — the zero-cap (independently verified, uncached) reader and the
    // cached reader expose byte-for-byte identical immutable metadata, keys,
    // stored records, liveness, norms, dictionary postings, spatial trees and
    // typed columns.
    #[test]
    fn g1_05_zero_cap_and_cached_readers_are_equivalent() {
        let (bytes, doc_count) = fixture_segment();
        let uncached_snapshot = snapshot_of(bytes.clone(), doc_count, 1 << 22, 0);
        let cached_snapshot = snapshot_of(bytes, doc_count, 1 << 22, 1 << 22);
        let uncached = uncached_snapshot.open_segment_reader(0).expect("uncached");
        let cached = cached_snapshot.open_segment_reader(0).expect("cached");
        assert!(!uncached_snapshot.slot_is_ready(0));
        assert!(cached_snapshot.slot_is_ready(0));
        let (a, b) = (uncached.reader(), cached.reader());

        assert_eq!(a.doc_count(), b.doc_count());
        assert_eq!(a.schema(), b.schema());
        assert_eq!(a.remap(), b.remap());
        assert_eq!(a.required_features(), b.required_features());
        assert_eq!(a.optional_features(), b.optional_features());
        assert_eq!(a.sections(), b.sections());
        assert_eq!(a.geo_bounds(), b.geo_bounds());
        assert_eq!(a.time_bounds(), b.time_bounds());
        assert_eq!(*a.doc_keys().expect("keys"), *b.doc_keys().expect("keys"));
        assert_eq!(*a.stored().expect("stored"), *b.stored().expect("stored"));
        assert_eq!(*a.live_docs().expect("live"), *b.live_docs().expect("live"));

        let norms_a = a.field_norms().expect("norms");
        let norms_b = b.field_norms().expect("norms");
        assert_eq!(
            norms_a.field_ids().collect::<Vec<_>>(),
            norms_b.field_ids().collect::<Vec<_>>()
        );
        for field_id in norms_a.field_ids() {
            assert_eq!(
                norms_a.field(field_id).expect("a").lengths(),
                norms_b.field(field_id).expect("b").lengths()
            );
        }

        let dictionary_a = a.dictionary().expect("dictionary");
        let dictionary_b = b.dictionary().expect("dictionary");
        for (field_id, entries) in dictionary_a.fields() {
            let other = dictionary_b.field(*field_id).expect("field");
            assert_eq!(entries.len(), other.len());
            for (left, right) in entries.iter().zip(other) {
                assert_eq!(left.term, right.term);
                assert_eq!(left.doc_freq, right.doc_freq);
                assert_eq!(left.postings_offset, right.postings_offset);
                assert_eq!(left.postings_length, right.postings_length);
                let postings_left = a.postings_for_entry(left).expect("a postings");
                let postings_right = b.postings_for_entry(right).expect("b postings");
                assert_eq!(
                    postings_left.posting_doc_count(),
                    postings_right.posting_doc_count()
                );
            }
        }

        let spatial_a = a.spatial().expect("spatial");
        let spatial_b = b.spatial().expect("spatial");
        assert_eq!(spatial_a.fields(), spatial_b.fields());

        let count_field = a.schema().field_id("count").expect("count field");
        for doc_id in 0..doc_count {
            assert_eq!(
                a.column_value(count_field, doc_id).expect("a column"),
                b.column_value(count_field, doc_id).expect("b column"),
                "typed column value must match for doc {doc_id}"
            );
        }
        // The uncached path never charges retained metadata.
        assert_eq!(uncached_snapshot.metadata_used(), 0);
        assert!(cached_snapshot.metadata_used() > 0);
    }

    // -----------------------------------------------------------------------
    // G2 — accounted retained metadata, cap boundaries and fallback
    // -----------------------------------------------------------------------

    // G2-01 / VSR-I10 — zero metadata cap always uses the verified uncached path.
    #[test]
    fn g2_01_zero_metadata_cap_uses_uncached_reader() {
        let (bytes, doc_count) = fixture_segment();
        let snapshot = snapshot_of(bytes, doc_count, 1 << 22, 0);
        let guard = snapshot.open_segment_reader(0).expect("reader");
        assert_eq!(guard.reader().doc_count(), doc_count);
        assert_eq!(snapshot.metadata_used(), 0);
        assert_eq!(snapshot.verification_count(), 0);
        assert!(!snapshot.slot_is_ready(0));
        drop(guard);
        assert_eq!(snapshot.reader_copy_used(), 0);
    }

    // G2-02 / G2-03 / X41 — exact candidate allowance admits; one byte over
    // falls back, and the measured charge never exceeds the allowance.
    #[test]
    fn g2_02_exact_allowance_admits_and_one_byte_over_falls_back() {
        let (bytes, doc_count) = fixture_segment();
        let allowance =
            crate::segment::reader::candidate_allowance_for_test(&bytes, SegmentLimits::default())
                .expect("allowance");
        assert!(allowance > 0);
        let probe = snapshot_of(bytes.clone(), doc_count, 1 << 24, allowance);
        drop(probe.open_segment_reader(0).expect("probe"));
        let measured = probe.metadata_used();
        assert!(measured > 0, "verified state must be charged");
        assert!(
            measured <= allowance,
            "measured retained charge must fit the pre-reserved allowance"
        );
        assert!(probe.slot_is_ready(0));
        drop(probe);

        // Exact allowance: admitted and charged the measured amount.
        let exact = snapshot_of(bytes.clone(), doc_count, 1 << 24, allowance);
        drop(exact.open_segment_reader(0).expect("exact"));
        assert_eq!(exact.metadata_used(), measured);
        assert_eq!(exact.verification_count(), 1);
        assert!(exact.slot_is_ready(0));
        drop(exact);

        // One byte over the allowance: optional failure, verified fallback.
        let tight = snapshot_of(bytes.clone(), doc_count, 1 << 24, allowance - 1);
        let guard = tight.open_segment_reader(0).expect("fallback reader");
        assert_eq!(guard.reader().doc_count(), doc_count);
        assert_eq!(tight.metadata_used(), 0);
        assert_eq!(tight.verification_count(), 0);
        assert!(!tight.slot_is_ready(0));
        drop(guard);
        assert_eq!(tight.reader_copy_used(), 0);
    }

    // G2-04 / G2-17 — repeated optional-cap failures never leak a reservation.
    #[test]
    fn g2_04_repeated_failed_candidates_do_not_leak() {
        let (bytes, doc_count) = fixture_segment();
        let snapshot = snapshot_of(bytes, doc_count, 1 << 22, 1);
        for _ in 0..4 {
            let guard = snapshot.open_segment_reader(0).expect("fallback");
            assert_eq!(guard.reader().doc_count(), doc_count);
            drop(guard);
            assert_eq!(snapshot.metadata_used(), 0);
            assert_eq!(snapshot.reader_copy_used(), 0);
        }
        assert_eq!(snapshot.verification_count(), 0);
    }

    // G2-05 — a very large cap is still measured exactly, not accumulated twice.
    #[test]
    fn g2_05_single_state_is_charged_once_under_a_large_cap() {
        let (bytes, doc_count) = fixture_segment();
        let snapshot = snapshot_of(bytes, doc_count, 1 << 22, u64::MAX);
        let first = snapshot.open_segment_reader(0).expect("first");
        let charged = snapshot.metadata_used();
        let second = snapshot.open_segment_reader(0).expect("second");
        assert_eq!(snapshot.metadata_used(), charged);
        assert_eq!(snapshot.verification_count(), 1);
        assert!(Arc::ptr_eq(
            first.reader().shared_state(),
            second.reader().shared_state()
        ));
    }

    // G2-06 / G2-07 / G2-08 / G2-09 — every nested metadata class is charged.
    #[test]
    fn g2_06_to_09_nested_classes_are_accounted() {
        let (snapshot, _, _) = cached_snapshot();
        let guard = snapshot.open_segment_reader(0).expect("reader");
        let reader = guard.reader();
        let charged = snapshot.metadata_used();
        assert!(charged > 0);

        // Dictionary terms and entry vectors.
        let dictionary = reader.dictionary().expect("dictionary");
        let mut term_bytes = 0u64;
        for (_, entries) in dictionary.fields() {
            term_bytes += (entries.capacity() * std::mem::size_of::<DictionaryEntry>()) as u64;
            for entry in entries {
                term_bytes += entry.term.capacity() as u64;
            }
        }
        assert!(term_bytes > 0);
        assert!(charged >= term_bytes, "dictionary payload must be charged");

        // Schema field names and analyzer/normalizer binding payloads.
        let schema = reader.schema();
        let mut string_bytes = 0u64;
        for field in schema.fields() {
            string_bytes += field.name.capacity() as u64;
            for binding in [field.analyzer.as_ref(), field.normalizer.as_ref()]
                .into_iter()
                .flatten()
            {
                string_bytes += binding.id.capacity() as u64 + binding.version.capacity() as u64;
            }
        }
        assert!(string_bytes > 0, "bindings must retain strings");
        assert!(charged >= string_bytes, "schema strings must be charged");

        // Norms length vectors.
        let norms = reader.field_norms().expect("norms");
        let mut norms_bytes = 0u64;
        for field_id in norms.field_ids() {
            let lengths = norms.field(field_id).expect("norms field");
            norms_bytes += std::mem::size_of_val(lengths.lengths()) as u64;
        }
        assert!(norms_bytes > 0);
        assert!(charged >= norms_bytes, "norms lengths must be charged");

        // JSON-path directory payload and its offset vector.
        let directory_size = std::mem::size_of::<JsonPathDirectory>() as u64;
        assert!(charged >= directory_size);
        assert!(reader.open_json_paths().expect("json paths").is_some());

        // Spatial nested node vectors.
        let spatial = reader.spatial().expect("spatial");
        let mut node_bytes = 0u64;
        for field in spatial.fields() {
            node_bytes += (field.nodes.capacity() * std::mem::size_of::<SpatialNode>()) as u64;
        }
        assert!(node_bytes > 0);
        assert!(charged >= node_bytes, "spatial nodes must be charged");

        // Geo bounds and section directory retention.
        let geo_bytes = std::mem::size_of_val(reader.geo_bounds()) as u64;
        assert!(charged >= geo_bytes);
    }

    // G2-10 / VSR-I09 — the reservation releases on the last `Arc`, not on
    // snapshot drop, and a guard may outlive its snapshot.
    #[test]
    fn g2_10_reservation_releases_on_last_arc_after_snapshot_drop() {
        let (snapshot, _, doc_count) = cached_snapshot();
        let budget = Arc::clone(&snapshot.metadata_budget_handle());
        let guard = snapshot.open_segment_reader(0).expect("reader");
        let charged = snapshot.metadata_used();
        assert!(charged > 0);
        let snapshot = Arc::new(snapshot);
        let cloned = Arc::clone(&snapshot);
        drop(snapshot);
        drop(cloned);
        // The guard still keeps the immutable state (and its charge) alive.
        assert_eq!(budget.used(), charged);
        assert_eq!(guard.reader().doc_count(), doc_count);
        assert_eq!(
            guard.reader().doc_keys().expect("keys").len(),
            doc_count as usize
        );
        drop(guard);
        assert_eq!(budget.used(), 0);
    }

    // G2-11 / VSR-I05 — cache hits still charge the full active-reader admission.
    #[test]
    fn g2_11_cache_hits_keep_full_admission_charge() {
        let (snapshot, bytes, doc_count) = cached_snapshot();
        let snapshot = Arc::new(snapshot);
        let encoded = bytes.len() as u64;
        let first = snapshot.open_segment_reader(0).expect("first");
        let charged_metadata = snapshot.metadata_used();
        assert!(charged_metadata > 0);
        assert_eq!(snapshot.reader_copy_used(), encoded);
        let threads = 7;
        let barrier = Arc::new(Barrier::new(threads + 1));
        let mut handles = Vec::new();
        for _ in 0..threads {
            let snapshot = Arc::clone(&snapshot);
            let barrier = Arc::clone(&barrier);
            handles.push(std::thread::spawn(move || {
                barrier.wait();
                let guard = snapshot.open_segment_reader(0).expect("concurrent reader");
                // Hold the guard so its reservation stays outstanding.
                barrier.wait();
                guard.reader().doc_count()
            }));
        }
        barrier.wait();
        // All threads hold a guard: admission is charged per guard, metadata once.
        barrier.wait();
        for handle in handles {
            assert_eq!(handle.join().expect("thread"), doc_count);
        }
        // Guards are dropped inside the worker; the held `first` guard remains.
        assert_eq!(snapshot.reader_copy_used(), encoded);
        assert_eq!(snapshot.metadata_used(), charged_metadata);
        drop(first);
        assert_eq!(snapshot.reader_copy_used(), 0);
    }

    // G2-12 / X17 / X19 — a genuinely over-limit input is reported with its own
    // authoritative typed error after the optional cache path declines to publish.
    #[test]
    fn g2_12_over_limit_input_reports_authoritative_error() {
        let (bytes, _) = fixture_segment();
        let limits = SegmentLimits::default().with_accepted_segment_bytes(16);
        let snapshot = ReaderSnapshot::for_test(
            vec![segment_snapshot(bytes, 3, "s-limit")],
            limits,
            1 << 22,
            1 << 22,
        );
        let error = open_error(&snapshot);
        assert!(matches!(
            error,
            IndexError::Segment(crate::segment::SegmentError::LimitExceeded { .. })
        ));
        assert_eq!(snapshot.metadata_used(), 0);
        assert!(!snapshot.slot_is_ready(0));
    }

    // -----------------------------------------------------------------------
    // G3 — integrity provenance and snapshot isolation
    // -----------------------------------------------------------------------

    // G3-01 / VSR-I01 — repeated reads reuse the exact same verified state.
    #[test]
    fn g3_01_repeated_reads_reuse_same_verified_state() {
        let (snapshot, _, _) = cached_snapshot();
        let first = snapshot.open_segment_reader(0).expect("first");
        let first_ptr = Arc::as_ptr(first.reader().shared_state());
        for _ in 0..3 {
            let guard = snapshot.open_segment_reader(0).expect("repeat");
            assert_eq!(Arc::as_ptr(guard.reader().shared_state()), first_ptr);
            assert_eq!(
                *guard.reader().doc_keys().expect("keys"),
                *first.reader().doc_keys().expect("keys")
            );
        }
        assert_eq!(snapshot.verification_count(), 1);
    }

    /// Locate `(body_offset, body_len, digest_offset)` of one section by walking
    /// the fixed-width footer directory from the trailer.
    fn section_extents(bytes: &[u8], kind: SectionKind) -> (usize, usize, usize) {
        let trailer_offset = bytes.len() - 64;
        let section_count = u32::from_le_bytes(
            bytes[trailer_offset + 24..trailer_offset + 28]
                .try_into()
                .expect("count"),
        ) as usize;
        let directory_start = trailer_offset - section_count * 60;
        for index in 0..section_count {
            let entry = directory_start + index * 60;
            let raw = u16::from_le_bytes(bytes[entry..entry + 2].try_into().expect("kind"));
            if raw != kind as u16 {
                continue;
            }
            let offset =
                u64::from_le_bytes(bytes[entry + 12..entry + 20].try_into().expect("offset"))
                    as usize;
            let length =
                u64::from_le_bytes(bytes[entry + 20..entry + 28].try_into().expect("length"))
                    as usize;
            return (offset, length, entry + 28);
        }
        panic!("section not found");
    }

    /// Rewrite a section body, re-seal its digest and re-seal the envelope.
    fn retamper(bytes: &mut [u8], kind: SectionKind, mutate: impl Fn(&mut [u8])) {
        let (offset, length, digest_offset) = section_extents(bytes, kind);
        mutate(&mut bytes[offset..offset + length]);
        let digest = sha256(&bytes[offset..offset + length]);
        bytes[digest_offset..digest_offset + 32].copy_from_slice(&digest);
        let trailer_offset = bytes.len() - 64;
        let envelope = sha256(&bytes[..trailer_offset]);
        bytes[trailer_offset + 32..trailer_offset + 64].copy_from_slice(&envelope);
    }

    fn open_error(snapshot: &ReaderSnapshot) -> IndexError {
        snapshot.open_segment_reader(0).expect_err("must fail")
    }

    // G3-02 — envelope (whole-container) corruption fails closed, no fallback.
    #[test]
    fn g3_02_envelope_corruption_fails_closed() {
        let (bytes, doc_count) = fixture_segment();
        let mut corrupt = bytes;
        let last = corrupt.len() - 1;
        corrupt[last] ^= 0xFF;
        let snapshot = snapshot_of(corrupt, doc_count, 1 << 22, 1 << 22);
        let error = open_error(&snapshot);
        assert!(matches!(
            error,
            IndexError::Segment(crate::segment::SegmentError::DigestMismatch { .. })
        ));
        assert_eq!(snapshot.metadata_used(), 0);
        assert!(!snapshot.slot_is_ready(0));
        assert_eq!(snapshot.reader_copy_used(), 0);
        // A failed verification is never cached as a hit.
        assert!(matches!(
            open_error(&snapshot),
            IndexError::Segment(crate::segment::SegmentError::DigestMismatch { .. })
        ));
        assert!(!snapshot.slot_is_ready(0));
    }

    // G3-03 — a section digest mismatch fails closed even with a valid envelope.
    #[test]
    fn g3_03_section_digest_corruption_fails_closed() {
        let (bytes, doc_count) = fixture_segment();
        let mut corrupt = bytes;
        {
            let (offset, length, digest_offset) =
                section_extents(&corrupt, SectionKind::Dictionary);
            let mut body = corrupt[offset..offset + length].to_vec();
            body[0] ^= 0xFF;
            corrupt[offset..offset + length].copy_from_slice(&body);
            let trailer_offset = corrupt.len() - 64;
            let envelope = sha256(&corrupt[..trailer_offset]);
            corrupt[trailer_offset + 32..trailer_offset + 64].copy_from_slice(&envelope);
            let _ = digest_offset;
        }
        let snapshot = snapshot_of(corrupt, doc_count, 1 << 22, 1 << 22);
        assert!(matches!(
            open_error(&snapshot),
            IndexError::Segment(crate::segment::SegmentError::DigestMismatch { .. })
        ));
        assert_eq!(snapshot.metadata_used(), 0);
        assert!(!snapshot.slot_is_ready(0));
    }

    // G3-04 — malformed metadata (valid digests) still fails closed.
    #[test]
    fn g3_04_malformed_metadata_fails_closed() {
        let (bytes, doc_count) = fixture_segment();
        let mut corrupt = bytes;
        // Break the BM25 norms payload: declared doc count no longer matches.
        retamper(&mut corrupt, SectionKind::FieldNorms, |body| {
            body[2..10].copy_from_slice(&99u64.to_le_bytes());
        });
        let snapshot = snapshot_of(corrupt, doc_count, 1 << 22, 1 << 22);
        assert!(matches!(
            open_error(&snapshot),
            IndexError::Segment(crate::segment::SegmentError::Corrupt { .. })
        ));
        assert_eq!(snapshot.metadata_used(), 0);
        assert!(!snapshot.slot_is_ready(0));
    }

    // G3-04b — a malformed JSON-path directory also fails closed.
    #[test]
    fn g3_04b_malformed_json_paths_fail_closed() {
        let (bytes, doc_count) = fixture_segment();
        let mut corrupt = bytes;
        retamper(&mut corrupt, SectionKind::JsonPaths, |body| {
            body[0] = 9; // unsupported payload version
        });
        let snapshot = snapshot_of(corrupt, doc_count, 1 << 22, 1 << 22);
        assert!(matches!(
            open_error(&snapshot),
            IndexError::Segment(crate::segment::SegmentError::Corrupt { .. })
        ));
        assert_eq!(snapshot.metadata_used(), 0);
        assert!(!snapshot.slot_is_ready(0));
    }

    // G3-05 — descriptor verification stays authoritative on cached readers.
    #[test]
    fn g3_05_descriptor_verification_unchanged() {
        let (snapshot, bytes, _) = cached_snapshot();
        let guard = snapshot.open_segment_reader(0).expect("reader");
        let good = ContentDescriptor::of(&bytes);
        guard
            .reader()
            .verify_content_descriptor(&good)
            .expect("matching descriptor");
        let mut wrong_bytes = bytes.clone();
        wrong_bytes.push(0);
        let wrong = ContentDescriptor::of(&wrong_bytes);
        assert!(guard.reader().verify_content_descriptor(&wrong).is_err());
    }

    // G3-06 / X43 — identical ids with different bytes are never trusted.
    #[test]
    fn g3_06_same_ids_different_bytes_are_never_trusted() {
        let (bytes, doc_count) = fixture_segment();
        let (legacy_bytes, legacy_docs) = legacy_segment();
        let first = ReaderSnapshot::for_test(
            vec![segment_snapshot(bytes.clone(), doc_count, "s-same")],
            SegmentLimits::default(),
            1 << 22,
            1 << 22,
        );
        let second = ReaderSnapshot::for_test(
            vec![segment_snapshot(legacy_bytes, legacy_docs, "s-same")],
            SegmentLimits::default(),
            1 << 22,
            1 << 22,
        );
        let first_guard = first.open_segment_reader(0).expect("first");
        let second_guard = second.open_segment_reader(0).expect("second");
        assert_eq!(first_guard.reader().doc_count(), doc_count);
        assert_eq!(second_guard.reader().doc_count(), legacy_docs);
        assert!(!Arc::ptr_eq(
            first_guard.reader().shared_state(),
            second_guard.reader().shared_state()
        ));
        assert_eq!(first.verification_count(), 1);
        assert_eq!(second.verification_count(), 1);

        // Corrupt bytes under the same identifiers must not inherit state.
        let mut corrupt = bytes;
        let last = corrupt.len() - 1;
        corrupt[last] ^= 0x01;
        let third = ReaderSnapshot::for_test(
            vec![segment_snapshot(corrupt, doc_count, "s-same")],
            SegmentLimits::default(),
            1 << 22,
            1 << 22,
        );
        assert!(matches!(open_error(&third), IndexError::Segment(_)));
        assert_eq!(third.metadata_used(), 0);
    }

    // G3-07 / VSR-I03 — snapshot masks are never captured by cached state.
    #[test]
    fn g3_07_effective_masks_remain_snapshot_owned() {
        let (bytes, doc_count) = fixture_segment();
        let segment = segment_snapshot(bytes, doc_count, "s-mask");
        let limits = SegmentLimits::default();
        let pins = PinCounter::new(4).expect("pins");
        let all_live = ReaderSnapshot::new_with_masks(
            Some(1),
            1,
            vec![segment.clone()],
            vec![None],
            limits,
            Arc::clone(&pins),
            1 << 22,
        )
        .expect("all live");
        let masked = ReaderSnapshot::new_with_masks(
            Some(2),
            2,
            vec![segment],
            vec![Some(Arc::new(vec![true, false, true]))],
            limits,
            pins,
            1 << 22,
        )
        .expect("masked");
        let all_guard = all_live.open_segment_reader(0).expect("all");
        let masked_guard = masked.open_segment_reader(0).expect("masked");
        let all_live_flags = all_live
            .effective_live_docs(0, all_guard.reader())
            .expect("all flags");
        let masked_flags = masked
            .effective_live_docs(0, masked_guard.reader())
            .expect("masked flags");
        assert_eq!(*all_live_flags, vec![true, true, true]);
        assert_eq!(*masked_flags, vec![true, false, true]);
        // The immutable segment state (and its own live bitmap) is identical.
        assert_eq!(
            *all_guard.reader().live_docs().expect("live"),
            *masked_guard.reader().live_docs().expect("live")
        );
        assert_eq!(all_live.document_count(), 3);
        assert_eq!(masked.document_count(), 2);
    }

    // -----------------------------------------------------------------------
    // G4 — slot state machine, concurrency, failure and unwind
    // -----------------------------------------------------------------------

    fn race_first_open(threads: usize) {
        let (bytes, doc_count) = fixture_segment();
        let snapshot = Arc::new(snapshot_of(bytes, doc_count, 1 << 24, 1 << 22));
        let barrier = Arc::new(Barrier::new(threads));
        let mut handles = Vec::new();
        for _ in 0..threads {
            let snapshot = Arc::clone(&snapshot);
            let barrier = Arc::clone(&barrier);
            handles.push(std::thread::spawn(move || {
                barrier.wait();
                let guard = snapshot.open_segment_reader(0).expect("racing reader");
                let keys = guard.reader().doc_keys().expect("keys");
                (
                    guard.reader().doc_count(),
                    keys.as_ref().clone(),
                    Arc::as_ptr(guard.reader().shared_state()) as usize,
                )
            }));
        }
        let mut results = Vec::new();
        for handle in handles {
            results.push(handle.join().expect("thread"));
        }
        let reference = results.remove(0);
        for result in &results {
            assert_eq!(result.0, reference.0);
            assert_eq!(result.1, reference.1);
            assert_eq!(result.2, reference.2, "all threads must share one state");
        }
        assert_eq!(snapshot.verification_count(), 1, "exactly one verification");
        assert_eq!(snapshot.reader_copy_used(), 0, "all guards released");
    }

    // G4-01..G4-03 / VSR-I04 — racing first opens verify exactly once.
    #[test]
    fn g4_01_racing_first_opens_verify_once() {
        race_first_open(2);
        race_first_open(8);
        race_first_open(32);
    }

    // G4-04 — a failed validation wakes waiters and publishes nothing.
    #[test]
    fn g4_04_failed_validation_wakes_waiters() {
        let (bytes, doc_count) = fixture_segment();
        let mut corrupt = bytes;
        let last = corrupt.len() - 1;
        corrupt[last] ^= 0xFF;
        let snapshot = Arc::new(snapshot_of(corrupt, doc_count, 1 << 24, 1 << 22));
        let barrier = Arc::new(Barrier::new(8));
        let mut handles = Vec::new();
        for _ in 0..8 {
            let snapshot = Arc::clone(&snapshot);
            let barrier = Arc::clone(&barrier);
            handles.push(std::thread::spawn(move || {
                barrier.wait();
                snapshot.open_segment_reader(0).is_err()
            }));
        }
        for handle in handles {
            assert!(handle.join().expect("thread"), "every caller must fail");
        }
        assert_eq!(snapshot.metadata_used(), 0);
        assert_eq!(snapshot.reader_copy_used(), 0);
        assert!(!snapshot.slot_is_ready(0));
        assert_eq!(snapshot.verification_count(), 0);
    }

    // G4-05 / X23 — an injected build error propagates and leaves the slot empty.
    #[test]
    fn g4_05_artificial_build_failure_recovers() {
        let (snapshot, _, _) = cached_snapshot();
        snapshot.set_build_fault(BuildFault::Fail);
        let error = open_error(&snapshot);
        assert!(matches!(error, IndexError::CorruptCommittedState { .. }));
        assert!(!snapshot.slot_is_ready(0));
        assert_eq!(snapshot.metadata_used(), 0);
        assert_eq!(snapshot.reader_copy_used(), 0);
        snapshot.set_build_fault(BuildFault::None);
        drop(snapshot.open_segment_reader(0).expect("retry succeeds"));
        assert_eq!(snapshot.verification_count(), 1);
        assert!(snapshot.slot_is_ready(0));
    }

    // G4-06 / X24 — a poisoned slot lock fails closed without leaking.
    #[test]
    fn g4_06_poisoned_slot_fails_closed() {
        let (snapshot, _, _) = cached_snapshot();
        snapshot.poison_slot(0);
        let error = open_error(&snapshot);
        assert!(matches!(error, IndexError::CorruptCommittedState { .. }));
        assert_eq!(snapshot.metadata_used(), 0);
        assert_eq!(snapshot.reader_copy_used(), 0);
        assert!(!snapshot.slot_is_ready(0));
    }

    // G4-07 — a panic during verification unwinds with slot and budget cleanup.
    #[test]
    fn g4_07_panic_during_build_restores_slot() {
        let (snapshot, _, _) = cached_snapshot();
        snapshot.set_build_fault(BuildFault::Panic);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = snapshot.open_segment_reader(0);
        }));
        assert!(result.is_err(), "injected panic must unwind");
        assert!(!snapshot.slot_is_ready(0));
        assert_eq!(snapshot.metadata_used(), 0);
        assert_eq!(snapshot.reader_copy_used(), 0);
        snapshot.set_build_fault(BuildFault::None);
        drop(snapshot.open_segment_reader(0).expect("retry succeeds"));
        assert_eq!(snapshot.verification_count(), 1);
    }

    // G4-08 — the snapshot may be dropped while a guard is in use.
    #[test]
    fn g4_08_guard_outlives_snapshot() {
        let (snapshot, _, doc_count) = cached_snapshot();
        let snapshot = Arc::new(snapshot);
        let guard = snapshot.open_segment_reader(0).expect("reader");
        drop(snapshot);
        assert_eq!(guard.reader().doc_count(), doc_count);
        assert_eq!(
            guard.reader().stored().expect("stored").len(),
            doc_count as usize
        );
        assert_eq!(
            guard.reader().doc_keys().expect("keys").len(),
            doc_count as usize
        );
    }

    // G4-09 / VSR-I06 — no slot lock is held during or after acquisition.
    #[test]
    fn g4_09_no_lock_held_across_query() {
        let (snapshot, _, _) = cached_snapshot();
        let guard = snapshot.open_segment_reader(0).expect("reader");
        assert!(snapshot.slot_is_unlocked(0));
        let _ = guard.reader().stored().expect("stored");
        let _ = guard.reader().doc_keys().expect("keys");
        let _ = guard.reader().postings(0, "alpha").expect("postings");
        assert!(snapshot.slot_is_unlocked(0));
        // Concurrent acquisition still progresses while guards are held.
        let second = snapshot.open_segment_reader(0).expect("second");
        assert!(snapshot.slot_is_unlocked(0));
        drop(second);
        drop(guard);
    }

    // G4-10 — out-of-range indices remain typed and charge nothing.
    #[test]
    fn g4_10_out_of_range_index_is_typed() {
        let (snapshot, _, _) = cached_snapshot();
        assert!(matches!(
            snapshot.open_segment_reader(3),
            Err(IndexError::SegmentOutOfRange { index: 3, count: 1 })
        ));
        assert_eq!(snapshot.reader_copy_used(), 0);
        assert_eq!(snapshot.metadata_used(), 0);
    }

    // S4 — a cache hit still fails when the active-reader admission budget is
    // exhausted (X28: no cache bypass).
    #[test]
    fn g4_11_cache_hit_still_obeys_admission_budget() {
        let (bytes, doc_count) = fixture_segment();
        let encoded = bytes.len() as u64;
        let snapshot = snapshot_of(bytes, doc_count, encoded, 1 << 22);
        let guard = snapshot.open_segment_reader(0).expect("first");
        assert!(snapshot.slot_is_ready(0));
        assert!(matches!(
            snapshot.open_segment_reader(0),
            Err(IndexError::ResourceLimit { .. })
        ));
        drop(guard);
        assert_eq!(snapshot.reader_copy_used(), 0);
        assert!(snapshot.metadata_used() > 0);
    }
}
