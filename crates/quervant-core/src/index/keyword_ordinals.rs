//! Snapshot-wide numeric keyword ordinals (PERF-06-B1).
//!
//! For one eligible field in one exact [`crate::index::ReaderSnapshot`], this
//! module merges every admitted segment's persistent distinct-term dictionary
//! into one exact, order-preserving numeric space. Translation is numeric and
//! allocation-free; the strings themselves never leave their immutable segment
//! bytes.
//!
//! Scope and lifetime rules:
//!
//! * A mapping is identified by `(snapshot binding, field id)`. Shared ranks may
//!   change in a new snapshot; old [`crate::index::PitHandle`] views keep their
//!   old map.
//! * Availability is an optional acceleration. A mixed legacy/new snapshot and
//!   any resource-bounded case return a typed
//!   [`KeywordOrdinalUnavailable`] result that is sticky for the snapshot
//!   lifetime. Codec corruption, schema disagreement, wrong guard binding,
//!   cancellation and a poisoned cache are always typed errors, never optional
//!   fallbacks.
//! * The retained payload is numeric only (`width * distinct_local_terms` plus
//!   its measured headers). No string pool, inverse table, reader, segment
//!   bytes, `Arc<ReaderSnapshot>` or active-reader charge is retained, so there
//!   is no snapshot → cache → snapshot cycle.
//!
//! Nothing here changes candidate selection, comparison dispatch, cursors,
//! scoring or Top-K behaviour; that adoption belongs to a later plan.

use std::collections::BinaryHeap;
use std::sync::{Arc, Condvar, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

use crate::analysis::Cancellation;
use crate::contract::document::Cardinality;
use crate::contract::value::FieldType;
use crate::segment::SegmentLimits;
use crate::segment::column::{KeywordOrdinalColumn, packed_width};
use crate::segment::error::{SegmentError, SegmentResult};
use crate::segment::metadata::{
    MetadataBudget, MetadataMeter, MetadataReservation, accumulate, capacity_bytes, element_bytes,
};
use crate::segment::schema::{CodecField, CodecSchema};

use super::error::{IndexError, IndexResult};
use super::snapshot::GuardedSegmentReader;

/// Fixed cooperative wait interval for a concurrent builder.
const WAIT_INTERVAL: Duration = Duration::from_millis(5);

// Scoped, test-only deterministic allocation-fault seam: counts down one unit
// per optional-layer reservation attempt and reports an allocator refusal when
// it reaches zero. No production build contains this hook.
#[cfg(test)]
thread_local! {
    static ALLOC_FAULT: std::cell::Cell<Option<u64>> = const { std::cell::Cell::new(None) };
}

/// Arm the deterministic allocation fault after `after` successful attempts.
#[cfg(test)]
pub(crate) fn set_alloc_fault(after: Option<u64>) {
    ALLOC_FAULT.with(|cell| cell.set(after));
}

#[cfg(test)]
fn alloc_fault_check() -> Result<(), KeywordOrdinalUnavailable> {
    ALLOC_FAULT.with(|cell| match cell.get() {
        Some(0) => Err(KeywordOrdinalUnavailable::Allocation),
        Some(remaining) => {
            cell.set(Some(remaining - 1));
            Ok(())
        }
        None => Ok(()),
    })
}

#[cfg(not(test))]
#[inline]
fn alloc_fault_check() -> Result<(), KeywordOrdinalUnavailable> {
    Ok(())
}
/// Cancellation poll interval, in emitted dictionary entries or segments.
const CANCELLATION_INTERVAL: u64 = 256;

/// Why a snapshot-wide ordinal map is not available for one field.
///
/// These outcomes are sticky for the snapshot lifetime; only a new snapshot may
/// attempt construction again.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeywordOrdinalUnavailable {
    /// At least one admitted segment still stores the genuine legacy column
    /// layout, so no numeric dictionary exists for it.
    LegacySegment,
    /// The requested map cannot fit the configured limits or the snapshot's
    /// retained-metadata allowance.
    ResourceBudget,
    /// A fallible vector/heap reservation for the optional map was refused.
    Allocation,
    /// The field id does not exist, is not columnar, is not a `Keyword`, or is
    /// not single-cardinality.
    UnsupportedField,
}

/// The result of one explicit preparation request.
pub enum KeywordOrdinalPreparation {
    /// A complete map, identical (`Arc`-shared) for every successful request on
    /// the same snapshot and field.
    Ready(Arc<SnapshotKeywordOrdinals>),
    /// A documented optional-capability outcome.
    NotAvailable(KeywordOrdinalUnavailable),
}

impl std::fmt::Debug for KeywordOrdinalPreparation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Ready(map) => f
                .debug_struct("Ready")
                .field("field_id", &map.field_id())
                .field("term_count", &map.term_count())
                .finish(),
            Self::NotAvailable(reason) => f.debug_tuple("NotAvailable").field(reason).finish(),
        }
    }
}

impl KeywordOrdinalPreparation {
    /// The prepared map, when available.
    #[must_use]
    pub fn ready(&self) -> Option<&Arc<SnapshotKeywordOrdinals>> {
        match self {
            Self::Ready(map) => Some(map),
            Self::NotAvailable(_) => None,
        }
    }

    /// The optional-capability reason, when not available.
    #[must_use]
    pub fn unavailable(&self) -> Option<KeywordOrdinalUnavailable> {
        match self {
            Self::Ready(_) => None,
            Self::NotAvailable(reason) => Some(*reason),
        }
    }
}

/// The retained numeric representation of one prepared field map.
enum MapPayload {
    /// One segment: the local dictionary already *is* the shared ordering.
    Identity { terms: u64 },
    /// Many segments: one packed rank per local ordinal, per segment.
    Packed { width: u8, buffers: Vec<Vec<u8>> },
}

/// One field's exact snapshot-wide numeric ordering.
///
/// All fields are private: the value is bound to a specific snapshot instance
/// and is never persisted or serialized.
pub struct SnapshotKeywordOrdinals {
    snapshot_binding: u64,
    field_id: u32,
    term_count: u64,
    payload: MapPayload,
    /// Keeps the retained-metadata charge alive for as long as this map lives,
    /// including after the owning snapshot and cache are dropped.
    _reservation: MetadataReservation,
}

impl SnapshotKeywordOrdinals {
    /// Numeric field id this map was prepared for.
    #[must_use]
    pub const fn field_id(&self) -> u32 {
        self.field_id
    }

    /// Number of globally distinct raw terms across the snapshot's segments.
    #[must_use]
    pub const fn term_count(&self) -> u64 {
        self.term_count
    }

    /// Bind the numeric translation for one admitted segment of this snapshot.
    ///
    /// The binding check happens once here, never per document.
    pub fn bind_segment(&self, guard: &GuardedSegmentReader) -> IndexResult<SegmentOrdinalMap<'_>> {
        let mismatch = || IndexError::CorruptCommittedState {
            detail: "keyword ordinal map does not match snapshot".to_owned(),
        };
        if guard.snapshot_binding() != self.snapshot_binding {
            return Err(mismatch());
        }
        let segment_index = guard.segment_index();
        if segment_index >= self.segment_count() {
            return Err(mismatch());
        }
        Ok(SegmentOrdinalMap {
            map: self,
            segment_index,
        })
    }

    fn segment_count(&self) -> usize {
        match &self.payload {
            MapPayload::Identity { .. } => 1,
            MapPayload::Packed { buffers, .. } => buffers.len(),
        }
    }

    /// Measured retained payload of this map (test-only accounting witness).
    #[cfg(test)]
    pub(crate) fn retained_charge(&self) -> crate::segment::error::SegmentResult<u64> {
        let mut total = element_bytes::<SnapshotKeywordOrdinals>(1)?;
        if let MapPayload::Packed { buffers, .. } = &self.payload {
            total = accumulate(total, capacity_bytes::<Vec<u8>>(buffers.capacity())?)?;
            for buffer in buffers {
                total = accumulate(total, capacity_bytes::<u8>(buffer.capacity())?)?;
            }
        }
        Ok(total)
    }
}

/// One segment's translation from local dictionary ordinals to shared ranks.
pub struct SegmentOrdinalMap<'a> {
    map: &'a SnapshotKeywordOrdinals,
    segment_index: usize,
}

impl SegmentOrdinalMap<'_> {
    /// Translate one segment-local ordinal into the snapshot-wide numeric space.
    ///
    /// # Errors
    ///
    /// [`SegmentError::InvalidColumnGeometry`] with the bounded detail
    /// `global ordinal lookup out of bounds` for an out-of-range ordinal or an
    /// impossible map slice. The success path allocates nothing.
    pub fn translate(&self, local_ordinal: u64) -> crate::segment::error::SegmentResult<u64> {
        match &self.map.payload {
            MapPayload::Identity { terms } => {
                if local_ordinal >= *terms {
                    return Err(global_ordinal_out_of_bounds());
                }
                Ok(local_ordinal)
            }
            MapPayload::Packed { width, buffers } => {
                let buffer = buffers
                    .get(self.segment_index)
                    .ok_or_else(global_ordinal_out_of_bounds)?;
                let width = *width as usize;
                let count = (buffer.len() / width) as u64;
                if local_ordinal >= count {
                    return Err(global_ordinal_out_of_bounds());
                }
                let at = local_ordinal as usize * width;
                let slot = buffer
                    .get(at..at + width)
                    .ok_or_else(global_ordinal_out_of_bounds)?;
                let mut raw = [0u8; 8];
                raw[..width].copy_from_slice(slot);
                Ok(u64::from_le_bytes(raw))
            }
        }
    }
}

fn global_ordinal_out_of_bounds() -> SegmentError {
    SegmentError::InvalidColumnGeometry {
        detail: "global ordinal lookup out of bounds",
    }
}

/// One field's entry state inside the snapshot registry.
enum EntryState {
    Empty,
    Building,
    Ready(Arc<SnapshotKeywordOrdinals>),
    NotAvailable(KeywordOrdinalUnavailable),
}

struct RegistryEntry {
    field_id: u32,
    state: EntryState,
}

/// The lazily allocated per-field registry for one snapshot.
struct Registry {
    entries: Vec<RegistryEntry>,
    _reservation: MetadataReservation,
}

enum RegistryState {
    Uninitialized,
    Initializing,
    Ready(Registry),
    NotAvailable(KeywordOrdinalUnavailable),
}

fn cache_poisoned() -> IndexError {
    IndexError::CorruptCommittedState {
        detail: "keyword ordinal cache lock poisoned".to_owned(),
    }
}

fn guard_mismatch() -> IndexError {
    IndexError::CorruptCommittedState {
        detail: "keyword ordinal readers do not match snapshot".to_owned(),
    }
}

fn publication_state_changed() -> IndexError {
    IndexError::CorruptCommittedState {
        detail: "keyword ordinal cache publication state changed".to_owned(),
    }
}

fn schema_mismatch() -> IndexError {
    IndexError::SchemaMismatch {
        detail: "keyword ordinal source schemas differ".to_owned(),
    }
}

/// The snapshot-scoped ordinal cache: one registry plus one field state machine.
pub(crate) struct KeywordOrdinalCache {
    state: Mutex<RegistryState>,
    ready: Condvar,
}

impl KeywordOrdinalCache {
    pub(crate) fn new() -> Self {
        Self {
            state: Mutex::new(RegistryState::Uninitialized),
            ready: Condvar::new(),
        }
    }

    fn lock(&self) -> IndexResult<MutexGuard<'_, RegistryState>> {
        self.state.lock().map_err(|_| cache_poisoned())
    }

    /// Prepare (or reuse) the shared ordinal map for one eligible field.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn prepare(
        &self,
        snapshot_binding: u64,
        budget: &Arc<MetadataBudget>,
        limits: SegmentLimits,
        segment_count: usize,
        field_id: u32,
        guards: &[GuardedSegmentReader],
        cancellation: &dyn Cancellation,
    ) -> IndexResult<KeywordOrdinalPreparation> {
        poll(cancellation)?;
        // Ordered, complete, same-snapshot guard admission happens before any
        // ready-cache lookup.
        if guards.len() != segment_count {
            return Err(guard_mismatch());
        }
        for (index, guard) in guards.iter().enumerate() {
            if guard.snapshot_binding() != snapshot_binding || guard.segment_index() != index {
                return Err(guard_mismatch());
            }
        }
        let Some(first) = guards.first() else {
            return Ok(KeywordOrdinalPreparation::NotAvailable(
                KeywordOrdinalUnavailable::UnsupportedField,
            ));
        };
        let schema = first.reader().schema();
        match schema.field(field_id) {
            Some(field) if is_eligible_field(field) => {}
            _ => {
                return Ok(KeywordOrdinalPreparation::NotAvailable(
                    KeywordOrdinalUnavailable::UnsupportedField,
                ));
            }
        }

        loop {
            enum Next {
                Initialize,
                WaitRegistry,
                RegistryUnavailable(KeywordOrdinalUnavailable),
                Build(usize),
                WaitField,
                Ready(Arc<SnapshotKeywordOrdinals>),
                FieldUnavailable(KeywordOrdinalUnavailable),
                Unsupported,
            }
            let next = {
                let mut state = self.lock()?;
                match &mut *state {
                    RegistryState::Uninitialized => {
                        *state = RegistryState::Initializing;
                        Next::Initialize
                    }
                    RegistryState::Initializing => Next::WaitRegistry,
                    RegistryState::NotAvailable(reason) => Next::RegistryUnavailable(*reason),
                    RegistryState::Ready(registry) => {
                        match registry
                            .entries
                            .binary_search_by_key(&field_id, |entry| entry.field_id)
                        {
                            Err(_) => Next::Unsupported,
                            Ok(index) => match &mut registry.entries[index].state {
                                EntryState::Empty => {
                                    registry.entries[index].state = EntryState::Building;
                                    Next::Build(index)
                                }
                                EntryState::Building => Next::WaitField,
                                EntryState::Ready(map) => Next::Ready(Arc::clone(map)),
                                EntryState::NotAvailable(reason) => Next::FieldUnavailable(*reason),
                            },
                        }
                    }
                }
            };
            match next {
                Next::Initialize => {
                    let init_guard = RegistryInitGuard::new(self);
                    run_after_claim_hook();
                    match initialize_registry(budget, limits, guards, cancellation) {
                        Ok(Ok(registry)) => {
                            // F2-I01: the LAST cancellation poll happens outside the
                            // cache mutex immediately before publication.
                            f2_probe(F2Probe::BeforeRegistryReadyPublish)?;
                            poll(cancellation)?;
                            self.publish_registry(RegistryState::Ready(registry))?;
                            init_guard.disarm();
                            self.ready.notify_all();
                            // Continue to this caller's field lookup.
                            continue;
                        }
                        Ok(Err(reason)) => {
                            // F2-I02: same pre-publication poll for the sticky
                            // optional registry outcome.
                            f2_probe(F2Probe::BeforeRegistryUnavailablePublish)?;
                            poll(cancellation)?;
                            self.publish_registry(RegistryState::NotAvailable(reason))?;
                            init_guard.disarm();
                            self.ready.notify_all();
                            poll(cancellation)?;
                            return Ok(KeywordOrdinalPreparation::NotAvailable(reason));
                        }
                        Err(error) => {
                            drop(init_guard);
                            return Err(error);
                        }
                    }
                }
                Next::WaitRegistry | Next::WaitField => {
                    poll(cancellation)?;
                    run_pre_wait_hook();
                    let wait_for = match next {
                        Next::WaitRegistry => WaitFor::Registry,
                        _ => WaitFor::Field(field_id),
                    };
                    self.wait(wait_for, cancellation)?;
                }
                Next::RegistryUnavailable(reason) => {
                    poll(cancellation)?;
                    return Ok(KeywordOrdinalPreparation::NotAvailable(reason));
                }
                Next::Build(index) => {
                    return self.build_and_publish(
                        snapshot_binding,
                        budget,
                        limits,
                        field_id,
                        index,
                        guards,
                        cancellation,
                    );
                }
                Next::Ready(map) => {
                    poll(cancellation)?;
                    return Ok(KeywordOrdinalPreparation::Ready(map));
                }
                Next::FieldUnavailable(reason) => {
                    poll(cancellation)?;
                    return Ok(KeywordOrdinalPreparation::NotAvailable(reason));
                }
                Next::Unsupported => {
                    poll(cancellation)?;
                    return Ok(KeywordOrdinalPreparation::NotAvailable(
                        KeywordOrdinalUnavailable::UnsupportedField,
                    ));
                }
            }
        }
    }

    /// Predicate-driven timed wait.
    ///
    /// The live predicate is re-evaluated under the lock before any timed wait,
    /// so a publication that happened between the caller's state decision and
    /// this call cannot cause a gratuitous 5 ms sleep. Spurious notifications are
    /// rechecked by the caller's loop; the lock is never held across cancellation
    /// or user code.
    fn wait(&self, wait_for: WaitFor, cancellation: &dyn Cancellation) -> IndexResult<()> {
        poll(cancellation)?;
        let state = self.lock()?;
        let still_waiting = match (&*state, wait_for) {
            (RegistryState::Initializing, WaitFor::Registry) => true,
            (RegistryState::Ready(registry), WaitFor::Field(field_id)) => registry
                .entries
                .binary_search_by_key(&field_id, |entry| entry.field_id)
                .ok()
                .is_some_and(|index| matches!(registry.entries[index].state, EntryState::Building)),
            _ => false,
        };
        if !still_waiting {
            drop(state);
            return Ok(());
        }
        #[cfg(test)]
        WAIT_STARTS.with(|cell| cell.set(cell.get() + 1));
        observe_wait_entered();
        let (state, _timeout) = self
            .ready
            .wait_timeout(state, WAIT_INTERVAL)
            .map_err(|_| cache_poisoned())?;
        drop(state);
        poll(cancellation)
    }

    #[allow(clippy::too_many_arguments)]
    fn build_and_publish(
        &self,
        snapshot_binding: u64,
        budget: &Arc<MetadataBudget>,
        limits: SegmentLimits,
        field_id: u32,
        index: usize,
        guards: &[GuardedSegmentReader],
        cancellation: &dyn Cancellation,
    ) -> IndexResult<KeywordOrdinalPreparation> {
        let build_guard = FieldBuildGuard::new(self, index);
        run_after_claim_hook();
        match build_field_map(
            snapshot_binding,
            budget,
            limits,
            field_id,
            guards,
            cancellation,
        ) {
            Ok(Ok(owner)) => {
                // F2-I03: LAST poll outside the mutex before publishing the map.
                f2_probe(F2Probe::BeforeFieldReadyPublish)?;
                poll(cancellation)?;
                self.publish_field(index, EntryState::Ready(Arc::clone(&owner)))?;
                build_guard.disarm();
                self.ready.notify_all();
                poll(cancellation)?;
                Ok(KeywordOrdinalPreparation::Ready(owner))
            }
            Ok(Err(reason)) => {
                // F2-I04: same pre-publication poll for the sticky field outcome.
                f2_probe(F2Probe::BeforeFieldUnavailablePublish)?;
                poll(cancellation)?;
                self.publish_field(index, EntryState::NotAvailable(reason))?;
                build_guard.disarm();
                self.ready.notify_all();
                poll(cancellation)?;
                Ok(KeywordOrdinalPreparation::NotAvailable(reason))
            }
            Err(error) => {
                // RAII restores `Building -> Empty` and wakes waiters.
                drop(build_guard);
                Err(error)
            }
        }
    }

    /// Publish a completed registry candidate under the cache lock.
    ///
    /// The claimed state must still be `Initializing`; anything else is a typed
    /// internal-state error and leaves the caller's RAII guard armed so the claim
    /// is cleaned up instead of silently overwriting another state.
    fn publish_registry(&self, next: RegistryState) -> IndexResult<()> {
        let mut state = self.lock()?;
        if !matches!(&*state, RegistryState::Initializing) {
            return Err(publication_state_changed());
        }
        *state = next;
        drop(state);
        Ok(())
    }

    /// Publish a completed field candidate for the entry this caller claimed.
    fn publish_field(&self, index: usize, next: EntryState) -> IndexResult<()> {
        let mut state = self.lock()?;
        let RegistryState::Ready(registry) = &mut *state else {
            return Err(publication_state_changed());
        };
        let Some(entry) = registry.entries.get_mut(index) else {
            return Err(publication_state_changed());
        };
        if !matches!(entry.state, EntryState::Building) {
            return Err(publication_state_changed());
        }
        entry.state = next;
        drop(state);
        Ok(())
    }

    /// Poison the cache lock deterministically (test-only).
    #[cfg(test)]
    pub(crate) fn poison_lock(&self) {
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = self.state.lock().expect("ordinal lock");
            panic!("poison ordinal cache");
        }));
    }

    #[cfg(test)]
    pub(crate) fn registry_is_uninitialized(&self) -> bool {
        self.state
            .lock()
            .map(|state| matches!(&*state, RegistryState::Uninitialized))
            .unwrap_or(false)
    }
}

fn poll(cancellation: &dyn Cancellation) -> IndexResult<()> {
    if cancellation.is_cancelled() {
        Err(IndexError::Cancelled)
    } else {
        Ok(())
    }
}

/// Frozen zero-data discriminator for the scoped F2 test probes.
///
/// This is a private test seam: the production build only ever calls the no-op
/// stub below, so no fault behaviour, atomic or callback exists there.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum F2Probe {
    RegistryAfterEntries,
    FieldAfterFirstPackedBuffer,
    BeforeRegistryReadyPublish,
    BeforeRegistryUnavailablePublish,
    BeforeFieldReadyPublish,
    BeforeFieldUnavailablePublish,
    RegistryEligibilityIndex256,
    RegistryFillIndex256,
}

/// One registered F2 probe callback and the point it belongs to.
#[cfg(test)]
pub(crate) type F2ProbeCallback = Box<dyn FnOnce() -> IndexResult<()>>;

#[cfg(test)]
thread_local! {
    static F2_PROBE: std::cell::RefCell<Option<(F2Probe, F2ProbeCallback)>> =
        const { std::cell::RefCell::new(None) };
}

/// Install a one-shot probe callback for `point`.
#[cfg(test)]
pub(crate) fn set_f2_probe(point: F2Probe, callback: impl FnOnce() -> IndexResult<()> + 'static) {
    F2_PROBE.with(|cell| *cell.borrow_mut() = Some((point, Box::new(callback))));
}

/// Clear any pending probe callback.
#[cfg(test)]
pub(crate) fn clear_f2_probe() {
    F2_PROBE.with(|cell| *cell.borrow_mut() = None);
}

/// Run the registered one-shot probe when its point matches.
///
/// The `RefCell` borrow is released before the callback runs, so a callback may
/// panic (caught by the test) or perform arbitrary work. A different point does
/// not consume a pending callback.
#[cfg(test)]
fn f2_probe(point: F2Probe) -> IndexResult<()> {
    let callback = F2_PROBE.with(|cell| {
        let mut slot = cell.borrow_mut();
        match slot.as_ref() {
            Some((registered, _)) if *registered == point => slot.take(),
            _ => None,
        }
    });
    match callback {
        Some((_, callback)) => callback(),
        None => Ok(()),
    }
}

#[cfg(not(test))]
#[inline]
fn f2_probe(_: F2Probe) -> IndexResult<()> {
    Ok(())
}

// Wait-entry observer: set to `true` immediately before a real `wait_timeout`.
#[cfg(test)]
thread_local! {
    static WAIT_ENTERED_OBSERVER: std::cell::RefCell<Option<Arc<std::sync::atomic::AtomicBool>>> =
        const { std::cell::RefCell::new(None) };
}

#[cfg(test)]
pub(crate) fn set_wait_entered_observer(flag: Arc<std::sync::atomic::AtomicBool>) {
    WAIT_ENTERED_OBSERVER.with(|cell| *cell.borrow_mut() = Some(flag));
}

#[cfg(test)]
fn observe_wait_entered() {
    WAIT_ENTERED_OBSERVER.with(|cell| {
        if let Some(flag) = cell.borrow().as_ref() {
            flag.store(true, std::sync::atomic::Ordering::SeqCst);
        }
    });
}

#[cfg(not(test))]
#[inline]
fn observe_wait_entered() {}

// Test-only deterministic interleaving hooks. They are compiled out entirely in
// non-test builds and never touch production state.
#[cfg(test)]
thread_local! {
    static WAIT_STARTS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static PRE_WAIT_HOOK: std::cell::RefCell<Option<Box<dyn FnOnce()>>> =
        const { std::cell::RefCell::new(None) };
    static AFTER_CLAIM_HOOK: std::cell::RefCell<Option<Box<dyn FnOnce()>>> =
        const { std::cell::RefCell::new(None) };
}

/// Number of times this thread actually entered `Condvar::wait_timeout`.
#[cfg(test)]
pub(crate) fn wait_starts() -> u64 {
    WAIT_STARTS.with(std::cell::Cell::get)
}

#[cfg(test)]
fn reset_wait_starts() {
    WAIT_STARTS.with(|cell| cell.set(0));
}

/// Install a hook that runs after the wait decision and before the waiter takes
/// the cache lock again.
#[cfg(test)]
pub(crate) fn set_pre_wait_hook(hook: impl FnOnce() + 'static) {
    PRE_WAIT_HOOK.with(|cell| *cell.borrow_mut() = Some(Box::new(hook)));
}

/// Install a hook that runs after this caller claimed a registry/field build and
/// before construction starts.
#[cfg(test)]
pub(crate) fn set_after_claim_hook(hook: impl FnOnce() + 'static) {
    AFTER_CLAIM_HOOK.with(|cell| *cell.borrow_mut() = Some(Box::new(hook)));
}

#[cfg(test)]
fn run_pre_wait_hook() {
    let hook = PRE_WAIT_HOOK.with(|cell| cell.borrow_mut().take());
    if let Some(hook) = hook {
        hook();
    }
}

#[cfg(test)]
fn run_after_claim_hook() {
    let hook = AFTER_CLAIM_HOOK.with(|cell| cell.borrow_mut().take());
    if let Some(hook) = hook {
        hook();
    }
}

#[cfg(not(test))]
#[inline]
fn run_pre_wait_hook() {}

#[cfg(not(test))]
#[inline]
fn run_after_claim_hook() {}

/// Which published state a waiter is still waiting for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WaitFor {
    Registry,
    Field(u32),
}

/// Whether one codec field is eligible for a persistent keyword ordinal column.
pub(crate) fn is_eligible_field(field: &CodecField) -> bool {
    field.is_columnar()
        && field.field_type == FieldType::Keyword
        && field.cardinality == Cardinality::Single
}

/// Restores `Initializing -> Uninitialized` and wakes waiters on error/unwind.
struct RegistryInitGuard<'a> {
    cache: &'a KeywordOrdinalCache,
    armed: bool,
}

impl<'a> RegistryInitGuard<'a> {
    fn new(cache: &'a KeywordOrdinalCache) -> Self {
        Self { cache, armed: true }
    }

    fn disarm(mut self) {
        self.armed = false;
    }
}

impl Drop for RegistryInitGuard<'_> {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let mut state = self
            .cache
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if matches!(&*state, RegistryState::Initializing) {
            *state = RegistryState::Uninitialized;
            drop(state);
            self.cache.ready.notify_all();
        }
    }
}

/// Restores one field `Building -> Empty` and wakes waiters on error/unwind.
struct FieldBuildGuard<'a> {
    cache: &'a KeywordOrdinalCache,
    index: usize,
    armed: bool,
}

impl<'a> FieldBuildGuard<'a> {
    fn new(cache: &'a KeywordOrdinalCache, index: usize) -> Self {
        Self {
            cache,
            index,
            armed: true,
        }
    }

    fn disarm(mut self) {
        self.armed = false;
    }
}

impl Drop for FieldBuildGuard<'_> {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let mut state = self
            .cache
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if let RegistryState::Ready(registry) = &mut *state {
            if let Some(entry) = registry.entries.get_mut(self.index) {
                if matches!(entry.state, EntryState::Building) {
                    entry.state = EntryState::Empty;
                }
            }
        }
        drop(state);
        self.cache.ready.notify_all();
    }
}

fn initialize_registry(
    budget: &Arc<MetadataBudget>,
    limits: SegmentLimits,
    guards: &[GuardedSegmentReader],
    cancellation: &dyn Cancellation,
) -> IndexResult<Result<Registry, KeywordOrdinalUnavailable>> {
    poll(cancellation)?;
    let Some(first) = guards.first() else {
        return Err(guard_mismatch());
    };
    let schema: &CodecSchema = first.reader().schema();
    for (index, guard) in guards.iter().skip(1).enumerate() {
        if index as u64 % CANCELLATION_INTERVAL == 0 {
            poll(cancellation)?;
        }
        if guard.reader().schema() != schema {
            return Err(schema_mismatch());
        }
    }
    poll(cancellation)?;
    // F2-I06: the registry scans are cooperatively cancellable at a fixed,
    // testable period rather than one uninterruptible pass over the schema.
    let mut eligible: u64 = 0;
    for (index, field) in schema.fields().iter().enumerate() {
        if index == CANCELLATION_INTERVAL as usize {
            f2_probe(F2Probe::RegistryEligibilityIndex256)?;
        }
        if index as u64 % CANCELLATION_INTERVAL == 0 {
            poll(cancellation)?;
        }
        if is_eligible_field(field) {
            eligible = match eligible.checked_add(1) {
                Some(value) => value,
                None => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
            };
        }
    }
    poll(cancellation)?;
    let allowance = match element_bytes::<RegistryEntry>(eligible) {
        Ok(bytes) => bytes,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    if limits.check_allocation_bytes(allowance).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
    }
    let mut meter = match MetadataMeter::reserve(budget, allowance) {
        Ok(meter) => meter,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    if meter.charge_vec::<RegistryEntry>(eligible).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
    }
    poll(cancellation)?;
    let mut entries: Vec<RegistryEntry> = Vec::new();
    if alloc_fault_check().is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::Allocation));
    }
    let eligible_count = match usize::try_from(eligible) {
        Ok(count) => count,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    if entries.try_reserve_exact(eligible_count).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::Allocation));
    }
    // Entries are already in ascending field-id order: no name strings retained.
    for (index, field) in schema.fields().iter().enumerate() {
        if index == CANCELLATION_INTERVAL as usize {
            f2_probe(F2Probe::RegistryFillIndex256)?;
        }
        if index as u64 % CANCELLATION_INTERVAL == 0 {
            poll(cancellation)?;
        }
        if is_eligible_field(field) {
            entries.push(RegistryEntry {
                field_id: field.id,
                state: EntryState::Empty,
            });
        }
    }
    poll(cancellation)?;
    // F2 probe: the entry vector and the construction allowance are both live.
    f2_probe(F2Probe::RegistryAfterEntries)?;
    let measured = match capacity_bytes::<RegistryEntry>(entries.capacity()) {
        Ok(bytes) => bytes,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    let reservation = match meter.finalize(measured) {
        Ok(reservation) => reservation,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    // Immediately before handing the completed registry candidate to publication.
    poll(cancellation)?;
    Ok(Ok(Registry {
        entries,
        _reservation: reservation,
    }))
}

/// One borrowed heap head of the k-way dictionary merge.
struct MergeHead<'a> {
    term: &'a [u8],
    segment_index: usize,
    local_ordinal: u64,
}

impl PartialEq for MergeHead<'_> {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == std::cmp::Ordering::Equal
    }
}

impl Eq for MergeHead<'_> {}

impl PartialOrd for MergeHead<'_> {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for MergeHead<'_> {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        // Reversed so the `BinaryHeap` top is the lexically smallest head. The
        // numeric tie breakers make construction deterministic; they never
        // influence equality or rank.
        other
            .term
            .cmp(self.term)
            .then_with(|| other.segment_index.cmp(&self.segment_index))
            .then_with(|| other.local_ordinal.cmp(&self.local_ordinal))
    }
}

/// Checked peak construction allowance for the multi-segment builder.
///
/// Every concurrently live backing is checked individually against
/// `max_single_allocation`; the returned sum is the shared peak candidate
/// budget reserved before the first of them is allocated. The sum is never a
/// substitute for those individual checks.
fn fixed_peak_allowance(segments: u64, limits: &SegmentLimits) -> SegmentResult<u64> {
    let source = element_bytes::<KeywordOrdinalColumn>(segments)?;
    let heads = element_bytes::<MergeHead>(segments)?;
    let outer = element_bytes::<Vec<u8>>(segments)?;
    let owner = element_bytes::<SnapshotKeywordOrdinals>(1)?;
    for bytes in [source, heads, outer, owner] {
        limits.check_allocation_bytes(bytes)?;
    }
    let mut total = 0u64;
    for bytes in [source, heads, outer, owner] {
        total = accumulate(total, bytes)?;
    }
    Ok(total)
}

/// Grow `values` to `desired` capacity against the optional-layer allowance.
fn grow<T>(
    values: &mut Vec<T>,
    desired: usize,
    meter: &mut MetadataMeter,
    limits: &SegmentLimits,
) -> Result<(), KeywordOrdinalUnavailable> {
    if desired <= values.capacity() {
        return Ok(());
    }
    alloc_fault_check()?;
    let total =
        capacity_bytes::<T>(desired).map_err(|_| KeywordOrdinalUnavailable::ResourceBudget)?;
    limits
        .check_allocation_bytes(total)
        .map_err(|_| KeywordOrdinalUnavailable::ResourceBudget)?;
    let additional = capacity_bytes::<T>(desired - values.capacity())
        .map_err(|_| KeywordOrdinalUnavailable::ResourceBudget)?;
    meter
        .charge(additional)
        .map_err(|_| KeywordOrdinalUnavailable::ResourceBudget)?;
    values
        .try_reserve_exact(desired - values.len())
        .map_err(|_| KeywordOrdinalUnavailable::Allocation)?;
    let actual = values.capacity();
    if actual > desired {
        let measured =
            capacity_bytes::<T>(actual).map_err(|_| KeywordOrdinalUnavailable::ResourceBudget)?;
        if measured > limits.max_single_allocation() {
            return Err(KeywordOrdinalUnavailable::ResourceBudget);
        }
        let over = capacity_bytes::<T>(actual - desired)
            .map_err(|_| KeywordOrdinalUnavailable::ResourceBudget)?;
        meter
            .charge(over)
            .map_err(|_| KeywordOrdinalUnavailable::ResourceBudget)?;
    }
    Ok(())
}

fn bind_source(
    guard: &GuardedSegmentReader,
    field_id: u32,
) -> IndexResult<Option<KeywordOrdinalColumn<'_>>> {
    let Some(columns) = guard.reader().open_columns()? else {
        return Ok(None);
    };
    // The bound handle borrows the immutable section bytes for the guard's
    // lifetime; the temporary column view is dropped here.
    Ok(columns.bind_keyword_ordinals(field_id)?)
}

/// Build one field map. `Ok(Err(reason))` is a documented optional outcome;
/// `Err(error)` preserves an authoritative codec error.
fn build_field_map(
    snapshot_binding: u64,
    budget: &Arc<MetadataBudget>,
    limits: SegmentLimits,
    field_id: u32,
    guards: &[GuardedSegmentReader],
    cancellation: &dyn Cancellation,
) -> IndexResult<Result<Arc<SnapshotKeywordOrdinals>, KeywordOrdinalUnavailable>> {
    let segment_count = guards.len();
    if segment_count == 1 {
        // Identity fast path: no source/heap/outer-map vectors, no term reread.
        poll(cancellation)?;
        let Some(handle) = bind_source(&guards[0], field_id)? else {
            return Ok(Err(KeywordOrdinalUnavailable::LegacySegment));
        };
        poll(cancellation)?;
        let terms = handle.dictionary_len();
        let measured = match element_bytes::<SnapshotKeywordOrdinals>(1) {
            Ok(bytes) => bytes,
            Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
        };
        if limits.check_allocation_bytes(measured).is_err() {
            return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
        }
        let mut meter = match MetadataMeter::reserve(budget, measured) {
            Ok(meter) => meter,
            Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
        };
        if meter.charge_arc::<SnapshotKeywordOrdinals>().is_err() {
            return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
        }
        let reservation = match meter.finalize(measured) {
            Ok(reservation) => reservation,
            Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
        };
        poll(cancellation)?;
        return Ok(Ok(Arc::new(SnapshotKeywordOrdinals {
            snapshot_binding,
            field_id,
            term_count: terms,
            payload: MapPayload::Identity { terms },
            _reservation: reservation,
        })));
    }

    // Exact peak admission for every backing that is live at the same time:
    // bound-source handles, heap heads, the outer map vector and the owner.
    // Each backing is checked individually against the single-allocation
    // ceiling; the sum is the shared peak construction allowance reserved
    // *before* any of those allocations happens.
    let segments_u64 = match u64::try_from(segment_count) {
        Ok(value) => value,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    let fixed_allowance = match fixed_peak_allowance(segments_u64, &limits) {
        Ok(bytes) => bytes,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    let mut meter = match MetadataMeter::reserve(budget, fixed_allowance) {
        Ok(meter) => meter,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };

    // Bind every source exactly once and validate new-layout availability first.
    let mut sources: Vec<KeywordOrdinalColumn<'_>> = Vec::new();
    if let Err(reason) = grow(&mut sources, segment_count, &mut meter, &limits) {
        return Ok(Err(reason));
    }
    for (index, guard) in guards.iter().enumerate() {
        if index as u64 % CANCELLATION_INTERVAL == 0 {
            poll(cancellation)?;
        }
        let Some(handle) = bind_source(guard, field_id)? else {
            return Ok(Err(KeywordOrdinalUnavailable::LegacySegment));
        };
        sources.push(handle);
    }
    poll(cancellation)?;
    let mut total_terms: u64 = 0;
    for source in &sources {
        total_terms = match total_terms.checked_add(source.dictionary_len()) {
            Some(total) => total,
            None => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
        };
    }
    let width = packed_width(total_terms.saturating_sub(1));
    let payload_bytes = match total_terms.checked_mul(u64::from(width)) {
        Some(bytes) => bytes,
        None => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    // Every inner packed buffer must individually fit the single-allocation cap.
    for source in &sources {
        let wanted = match (source.dictionary_len() as usize).checked_mul(width as usize) {
            Some(bytes) => bytes,
            None => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
        };
        if limits
            .check_allocation_bytes(match u64::try_from(wanted) {
                Ok(bytes) => bytes,
                Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
            })
            .is_err()
        {
            return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
        }
    }
    // One more extension of the same meter covers the retained packed payload.
    if meter.extend(payload_bytes).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
    }
    poll(cancellation)?;

    let mut buffers: Vec<Vec<u8>> = Vec::new();
    if let Err(reason) = grow(&mut buffers, segment_count, &mut meter, &limits) {
        return Ok(Err(reason));
    }
    for source in &sources {
        poll(cancellation)?;
        let wanted = match (source.dictionary_len() as usize).checked_mul(width as usize) {
            Some(bytes) => bytes,
            None => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
        };
        let mut buffer: Vec<u8> = Vec::new();
        if let Err(reason) = grow(&mut buffer, wanted, &mut meter, &limits) {
            return Ok(Err(reason));
        }
        buffers.push(buffer);
        if buffers.len() == 1 {
            // F2 probe: a real charged packed buffer exists, no heap/output yet.
            f2_probe(F2Probe::FieldAfterFirstPackedBuffer)?;
        }
    }

    let mut heads: Vec<MergeHead<'_>> = Vec::new();
    if let Err(reason) = grow(&mut heads, segment_count, &mut meter, &limits) {
        return Ok(Err(reason));
    }
    for (index, source) in sources.iter().enumerate() {
        if source.dictionary_len() > 0 {
            let term = source.dictionary_term(0)?;
            heads.push(MergeHead {
                term,
                segment_index: index,
                local_ordinal: 0,
            });
        }
    }
    // `BinaryHeap::from` heapifies the pre-admitted backing vector in O(S).
    let mut heap = BinaryHeap::from(heads);
    let mut previous: Option<&[u8]> = None;
    let mut next_global: u64 = 0;
    let mut rank: u64 = 0;
    let mut emitted: u64 = 0;
    while let Some(mut head) = heap.peek_mut() {
        let term = head.term;
        let segment_index = head.segment_index;
        let local_ordinal = head.local_ordinal;
        if previous != Some(term) {
            rank = next_global;
            next_global = match next_global.checked_add(1) {
                Some(next) => next,
                None => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
            };
            previous = Some(term);
        }
        {
            // Capacity was pre-admitted for exactly `Ui * width` bytes, so this
            // append cannot reallocate or exceed the retained allowance.
            let buffer = &mut buffers[segment_index];
            buffer.extend_from_slice(&rank.to_le_bytes()[..width as usize]);
        }
        let next_local = local_ordinal + 1;
        let source = &sources[segment_index];
        if next_local < source.dictionary_len() {
            let next_term = source.dictionary_term(next_local)?;
            head.term = next_term;
            head.local_ordinal = next_local;
            drop(head);
        } else {
            std::collections::binary_heap::PeekMut::pop(head);
        }
        emitted += 1;
        if emitted % CANCELLATION_INTERVAL == 0 {
            poll(cancellation)?;
        }
    }
    if emitted != total_terms {
        return Err(IndexError::CorruptCommittedState {
            detail: "keyword ordinal merge did not emit every local term".to_owned(),
        });
    }
    // Release construction scratch before finalizing the retained charge.
    drop(heap);
    drop(sources);
    poll(cancellation)?;

    let mut measured = match element_bytes::<SnapshotKeywordOrdinals>(1) {
        Ok(bytes) => bytes,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    measured = match capacity_bytes::<Vec<u8>>(buffers.capacity())
        .and_then(|bytes| accumulate(measured, bytes))
    {
        Ok(bytes) => bytes,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    for buffer in &buffers {
        measured = match capacity_bytes::<u8>(buffer.capacity())
            .and_then(|bytes| accumulate(measured, bytes))
        {
            Ok(bytes) => bytes,
            Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
        };
    }
    if meter.charge_arc::<SnapshotKeywordOrdinals>().is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
    }
    let reservation = match meter.finalize(measured) {
        Ok(reservation) => reservation,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    poll(cancellation)?;
    Ok(Ok(Arc::new(SnapshotKeywordOrdinals {
        snapshot_binding,
        field_id,
        term_count: next_global,
        payload: MapPayload::Packed { width, buffers },
        _reservation: reservation,
    })))
}

/// PERF-06-B1 — snapshot-wide numeric ordinal map tests (B1-G01 … B1-G20).
#[cfg(test)]
mod b1_ordinals_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, CancellationFlag};
    use crate::contract::document::{Cardinality, DocumentKey};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::FieldValue;
    use crate::index::{ReaderSnapshot, SegmentMeta, SegmentSnapshot};
    use crate::segment::{Layout, SegmentBuilder, SegmentLimits};
    use quervant_objectstore::ContentDescriptor;
    use std::sync::{Arc, Barrier};

    const FIELD: u32 = 0;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "city",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
            ],
            None,
        )
        .expect("schema")
    }

    fn segment_of(id: &str, rows: &[(&str, Option<&str>)]) -> SegmentSnapshot {
        let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion);
        for (index, (key, value)) in rows.iter().enumerate() {
            let mut doc =
                crate::segment::SegmentDocument::new(DocumentKey::new(*key).expect("key"));
            match value {
                Some(value) => doc
                    .insert(
                        "city",
                        crate::contract::document::FieldValues::Single(FieldValue::Keyword(
                            (*value).to_owned(),
                        )),
                    )
                    .expect("city"),
                None => {
                    if index % 2 == 0 {
                        doc.insert("city", crate::contract::document::FieldValues::Absent)
                            .expect("absent");
                    } else {
                        doc.insert("city", crate::contract::document::FieldValues::ExplicitNull)
                            .expect("null");
                    }
                }
            }
            builder.add_document(doc).expect("add");
        }
        let built = builder.build().expect("build");
        let bytes = Arc::new(built.bytes);
        let meta = SegmentMeta::new(
            id,
            format!("index/segments/{id}.seg"),
            ContentDescriptor::of(&bytes),
            Vec::new(),
            Vec::new(),
            None,
        );
        SegmentSnapshot::new(meta, bytes, rows.len() as u64)
    }

    fn snapshot_with(segments: Vec<SegmentSnapshot>, metadata_cap: u64) -> ReaderSnapshot {
        ReaderSnapshot::for_test(segments, SegmentLimits::default(), 1 << 30, metadata_cap)
    }

    fn guards_of(snapshot: &ReaderSnapshot) -> Vec<GuardedSegmentReader> {
        (0..snapshot.segment_count())
            .map(|index| snapshot.open_segment_reader(index).expect("guard"))
            .collect()
    }

    fn prepare(
        snapshot: &ReaderSnapshot,
        guards: &[GuardedSegmentReader],
        cancellation: &dyn Cancellation,
    ) -> IndexResult<KeywordOrdinalPreparation> {
        snapshot.prepare_keyword_ordinals(FIELD, guards, cancellation)
    }

    fn ready(
        snapshot: &ReaderSnapshot,
        guards: &[GuardedSegmentReader],
    ) -> Arc<SnapshotKeywordOrdinals> {
        match prepare(snapshot, guards, &CancellationFlag::new()).expect("prepare") {
            KeywordOrdinalPreparation::Ready(map) => map,
            other => panic!("expected ready, got {other:?}"),
        }
    }

    fn local_dictionary(
        guard: &GuardedSegmentReader,
        map: &SnapshotKeywordOrdinals,
    ) -> (Vec<Vec<u8>>, Vec<u64>) {
        let columns = guard
            .reader()
            .open_columns()
            .expect("columns")
            .expect("section");
        let handle = columns
            .bind_keyword_ordinals(FIELD)
            .expect("bind")
            .expect("ordinal column");
        let translation = map.bind_segment(guard).expect("segment map");
        let mut terms = Vec::new();
        let mut ranks = Vec::new();
        for ordinal in 0..handle.dictionary_len() {
            terms.push(handle.dictionary_term(ordinal).expect("term").to_vec());
            ranks.push(translation.translate(ordinal).expect("translate"));
        }
        (terms, ranks)
    }

    fn byte_ranks(dictionaries: &[&[&str]]) -> Vec<(Vec<u8>, u64)> {
        let mut all: Vec<Vec<u8>> = dictionaries
            .iter()
            .flat_map(|dictionary| dictionary.iter())
            .map(|term| term.as_bytes().to_vec())
            .collect();
        all.sort();
        all.dedup();
        all.into_iter()
            .enumerate()
            .map(|(rank, term)| (term, rank as u64))
            .collect()
    }

    // B1-G01 — the frozen three-batch translation table.
    #[test]
    fn b1_g01_cross_segment_translation_matches_byte_order() {
        let snapshot = snapshot_with(
            vec![
                segment_of(
                    "a",
                    &[
                        ("a2", Some("")),
                        ("a3", Some("Austin")),
                        ("a4", Some("Seattle")),
                        ("a5", Some("é")),
                    ],
                ),
                segment_of(
                    "b",
                    &[
                        ("b4", Some("\0")),
                        ("b0", Some("Boston")),
                        ("b1", Some("Dallas")),
                        ("b2", Some("Seattle")),
                        ("b3", Some("e\u{301}")),
                        ("b5", Some("😀")),
                    ],
                ),
                segment_of(
                    "c",
                    &[
                        ("c0", Some("Austin")),
                        ("c3", Some("Z")),
                        ("c1", Some("a")),
                        ("c2", Some("aa")),
                    ],
                ),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        let map = ready(&snapshot, &guards);
        assert_eq!(map.term_count(), 12);
        let expected: Vec<(&[&str], Vec<u64>)> = vec![
            (&["", "Austin", "Seattle", "é"], vec![0, 2, 5, 10]),
            (
                &["\0", "Boston", "Dallas", "Seattle", "e\u{301}", "😀"],
                vec![1, 3, 4, 5, 9, 11],
            ),
            (&["Austin", "Z", "a", "aa"], vec![2, 6, 7, 8]),
        ];
        for (guard, (terms, ranks)) in guards.iter().zip(expected) {
            let (actual_terms, actual_ranks) = local_dictionary(guard, &map);
            let expected_terms: Vec<Vec<u8>> =
                terms.iter().map(|term| term.as_bytes().to_vec()).collect();
            assert_eq!(actual_terms, expected_terms);
            assert_eq!(actual_ranks, ranks);
        }
        // Integer comparison equals independent byte comparison for every pair.
        let mut all_terms: Vec<(Vec<u8>, u64)> = Vec::new();
        for guard in &guards {
            let (terms, ranks) = local_dictionary(guard, &map);
            all_terms.extend(terms.into_iter().zip(ranks));
        }
        for (left, left_rank) in &all_terms {
            for (right, right_rank) in &all_terms {
                assert_eq!(left.cmp(right), left_rank.cmp(right_rank));
            }
        }
    }

    // B1-G02 — a single segment uses the identity representation.
    #[test]
    fn b1_g02_single_segment_is_identity_and_empty_is_supported() {
        let snapshot = snapshot_with(
            vec![segment_of("only", &[("k0", Some("b")), ("k1", Some("a"))])],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        let map = ready(&snapshot, &guards);
        assert_eq!(map.term_count(), 2);
        let segment_map = map.bind_segment(&guards[0]).expect("bind");
        for ordinal in 0..2 {
            assert_eq!(segment_map.translate(ordinal).expect("x"), ordinal);
        }
        assert!(segment_map.translate(2).is_err());

        let empty = snapshot_with(vec![segment_of("empty", &[])], 1 << 22);
        let empty_guards = guards_of(&empty);
        let empty_map = ready(&empty, &empty_guards);
        assert_eq!(empty_map.term_count(), 0);
        assert!(
            empty_map
                .bind_segment(&empty_guards[0])
                .expect("bind")
                .translate(0)
                .is_err()
        );
    }

    // B1-G03 — many empty dictionaries publish the zero-term shape.
    #[test]
    fn b1_g03_multiple_empty_dictionaries_have_no_terms() {
        let snapshot = snapshot_with(
            vec![
                segment_of("e1", &[("k0", None), ("k1", None)]),
                segment_of("e2", &[("k2", None)]),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        let map = ready(&snapshot, &guards);
        assert_eq!(map.term_count(), 0);
        for guard in &guards {
            let (terms, ranks) = local_dictionary(guard, &map);
            assert!(terms.is_empty());
            assert!(ranks.is_empty());
            assert!(map.bind_segment(guard).expect("bind").translate(0).is_err());
        }
    }

    // B1-G04 — raw byte equality/order, no normalization.
    #[test]
    fn b1_g04_raw_bytes_not_normalized() {
        let left = ["", "A", "a", "ab", "\u{e9}"];
        let right = ["\0", "B", "e\u{301}", "aa"];
        let snapshot = snapshot_with(
            vec![
                segment_of(
                    "l",
                    &left
                        .iter()
                        .enumerate()
                        .map(|(i, term)| {
                            (
                                Box::leak(format!("l{i}").into_boxed_str()) as &str,
                                Some(*term),
                            )
                        })
                        .collect::<Vec<_>>(),
                ),
                segment_of(
                    "r",
                    &right
                        .iter()
                        .enumerate()
                        .map(|(i, term)| {
                            (
                                Box::leak(format!("r{i}").into_boxed_str()) as &str,
                                Some(*term),
                            )
                        })
                        .collect::<Vec<_>>(),
                ),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        let map = ready(&snapshot, &guards);
        let expected = byte_ranks(&[&left, &right]);
        assert_eq!(map.term_count(), expected.len() as u64);
        for (index, guard) in guards.iter().enumerate() {
            let source: Vec<&str> = if index == 0 {
                let mut values = left.to_vec();
                values.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
                values.dedup();
                values
            } else {
                let mut values = right.to_vec();
                values.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
                values.dedup();
                values
            };
            let (_, ranks) = local_dictionary(guard, &map);
            for (term, rank) in source.iter().zip(ranks) {
                let expected_rank = expected
                    .iter()
                    .find(|(bytes, _)| bytes.as_slice() == term.as_bytes())
                    .map(|(_, rank)| *rank)
                    .expect("term");
                assert_eq!(rank, expected_rank);
            }
        }
        // Composed and decomposed forms stay distinct.
        let compose = expected
            .iter()
            .position(|(bytes, _)| bytes.as_slice() == "\u{e9}".as_bytes())
            .expect("é");
        let decompose = expected
            .iter()
            .position(|(bytes, _)| bytes.as_slice() == "e\u{301}".as_bytes())
            .expect("e+combining");
        assert_ne!(compose, decompose);
    }

    // B1-G05 — the frozen 64-case differential family with an independent oracle.
    #[test]
    fn b1_g05_frozen_differential_families() {
        const ALPHABET: [&str; 10] = [
            "", "\0", "a", "aa", "A", "Austin", "Seattle", "e\u{301}", "é", "😀",
        ];
        for case in 0u64..64 {
            let segment_count = 1 + (case % 5) as usize;
            let mut segments = Vec::new();
            let mut dictionaries: Vec<Vec<&str>> = Vec::new();
            for source in 0..segment_count as u64 {
                let row_count = ((case + 3 * source) % 13) as usize;
                let mut rows: Vec<(&str, Option<&str>)> = Vec::new();
                let mut dictionary = Vec::new();
                for row in 0..row_count as u64 {
                    let selector = (case + 7 * source + 5 * row) % 13;
                    let key: &'static str =
                        Box::leak(format!("c{case}s{source}r{row}").into_boxed_str());
                    match selector {
                        0 | 1 => rows.push((key, None)),
                        2 => {
                            let term = ALPHABET[((case + row) % 10) as usize];
                            dictionary.push(term);
                            rows.push((key, Some(term)));
                        }
                        _ => {
                            let term = ALPHABET[((case + source + row) % 10) as usize];
                            dictionary.push(term);
                            rows.push((key, Some(term)));
                        }
                    }
                }
                segments.push(segment_of(
                    Box::leak(format!("seg{case}-{source}").into_boxed_str()),
                    &rows,
                ));
                dictionaries.push(dictionary);
            }
            let snapshot = snapshot_with(segments, 1 << 24);
            let guards = guards_of(&snapshot);
            let map = ready(&snapshot, &guards);
            let oracle: Vec<Vec<u8>> = {
                let mut all: Vec<Vec<u8>> = dictionaries
                    .iter()
                    .flat_map(|dictionary| dictionary.iter())
                    .map(|term| term.as_bytes().to_vec())
                    .collect();
                all.sort();
                all.dedup();
                all
            };
            assert_eq!(map.term_count(), oracle.len() as u64, "case {case}");
            for (index, guard) in guards.iter().enumerate() {
                let (terms, ranks) = local_dictionary(guard, &map);
                let mut expected_local: Vec<&str> = dictionaries[index].clone();
                expected_local.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
                expected_local.dedup();
                assert_eq!(terms.len(), expected_local.len(), "case {case}");
                for (term, rank) in terms.iter().zip(&ranks) {
                    let expected = oracle.binary_search(term).expect("term in oracle") as u64;
                    assert_eq!(*rank, expected, "case {case}");
                }
            }
        }
    }

    // B1-G06 — identical and disjoint dictionaries.
    #[test]
    fn b1_g06_identical_and_disjoint_dictionaries() {
        let rows: [(&str, Option<&str>); 3] =
            [("k0", Some("a")), ("k1", Some("b")), ("k2", Some("c"))];
        let identical = snapshot_with(
            vec![
                segment_of("i1", &rows),
                segment_of("i2", &rows),
                segment_of("i3", &rows),
            ],
            1 << 22,
        );
        let guards = guards_of(&identical);
        let map = ready(&identical, &guards);
        assert_eq!(map.term_count(), 3);
        let translations: Vec<Vec<u64>> = guards
            .iter()
            .map(|guard| local_dictionary(guard, &map).1)
            .collect();
        assert_eq!(translations[0], translations[1]);
        assert_eq!(translations[1], translations[2]);

        let disjoint = snapshot_with(
            vec![
                segment_of("d1", &[("k0", Some("a"))]),
                segment_of("d2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let disjoint_guards = guards_of(&disjoint);
        let disjoint_map = ready(&disjoint, &disjoint_guards);
        assert_eq!(disjoint_map.term_count(), 2);
        assert_eq!(
            local_dictionary(&disjoint_guards[0], &disjoint_map).1,
            vec![0]
        );
        assert_eq!(
            local_dictionary(&disjoint_guards[1], &disjoint_map).1,
            vec![1]
        );
    }

    // B1-G07 — packed width selection uses the checked upper bound T.
    #[test]
    fn b1_g07_packed_width_uses_the_upper_bound() {
        assert_eq!(packed_width(0), 1);
        assert_eq!(packed_width(255), 1);
        assert_eq!(packed_width(256), 2);
        assert_eq!(packed_width(65_535), 2);
        assert_eq!(packed_width(65_536), 3);
        assert_eq!(packed_width(u64::MAX), 8);

        // Two segments, one shared and one disjoint term: T=3 but U=2.
        let snapshot = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a")), ("k1", Some("b"))]),
                segment_of("s2", &[("k2", Some("a")), ("k3", Some("c"))]),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        let map = ready(&snapshot, &guards);
        assert_eq!(map.term_count(), 3);
        let expected = byte_ranks(&[&["a", "b"], &["a", "c"]]);
        let mut actual: Vec<(Vec<u8>, u64)> = Vec::new();
        for guard in &guards {
            let (terms, ranks) = local_dictionary(guard, &map);
            actual.extend(terms.into_iter().zip(ranks));
        }
        for (term, rank) in actual {
            let expected_rank = expected
                .iter()
                .find(|(bytes, _)| *bytes == term)
                .map(|(_, rank)| *rank)
                .expect("term");
            assert_eq!(rank, expected_rank);
        }
    }

    // B1-G08 — deleted-only terms stay in the physical map.
    #[test]
    fn b1_g08_deleted_only_terms_remain_in_the_physical_map() {
        // The mapping is over physical dictionaries, not visibility masks.
        let snapshot = snapshot_with(
            vec![
                segment_of("d1", &[("k0", Some("a")), ("k1", Some("b"))]),
                segment_of("d2", &[("k2", Some("c"))]),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        let map = ready(&snapshot, &guards);
        // Every physical term is representable even when no live mask selects it.
        assert_eq!(map.term_count(), 3);
        for guard in &guards {
            let (terms, _) = local_dictionary(guard, &map);
            assert!(!terms.is_empty());
        }
    }

    // B1-G09 — bindings never cross snapshot instances.
    #[test]
    fn b1_g09_bindings_are_snapshot_scoped() {
        let segments = || {
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ]
        };
        let first = snapshot_with(segments(), 1 << 22);
        let second = snapshot_with(segments(), 1 << 22);
        assert_ne!(first.binding_id(), second.binding_id());

        let first_guards = guards_of(&first);
        let map = ready(&first, &first_guards);
        let foreign = second.open_segment_reader(0).expect("guard");
        assert!(matches!(
            map.bind_segment(&foreign),
            Err(IndexError::CorruptCommittedState { detail })
                if detail == "keyword ordinal map does not match snapshot"
        ));
        // Reordered / foreign / incomplete guard slices are rejected.
        let mut reordered = guards_of(&first);
        reordered.swap(0, 1);
        assert!(matches!(
            prepare(&first, &reordered, &CancellationFlag::new()),
            Err(IndexError::CorruptCommittedState { detail })
                if detail == "keyword ordinal readers do not match snapshot"
        ));
        let mut foreign_slice = guards_of(&first);
        foreign_slice[0] = foreign;
        assert!(matches!(
            prepare(&first, &foreign_slice, &CancellationFlag::new()),
            Err(IndexError::CorruptCommittedState { .. })
        ));
        let incomplete = &guards_of(&first)[..1];
        assert!(matches!(
            prepare(&first, incomplete, &CancellationFlag::new()),
            Err(IndexError::CorruptCommittedState { .. })
        ));
    }

    // B1-G10 — eight contenders publish exactly one map.
    #[test]
    fn b1_g10_concurrent_requests_publish_one_map() {
        let snapshot = Arc::new(snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a")), ("k1", Some("b"))]),
                segment_of("s2", &[("k2", Some("c"))]),
                segment_of("s3", &[("k3", Some("a"))]),
            ],
            1 << 24,
        ));
        let barrier = Arc::new(Barrier::new(8));
        let mut handles = Vec::new();
        for _ in 0..8 {
            let snapshot = Arc::clone(&snapshot);
            let barrier = Arc::clone(&barrier);
            handles.push(std::thread::spawn(move || {
                let guards = guards_of(&snapshot);
                barrier.wait();
                let map = ready(&snapshot, &guards);
                (Arc::as_ptr(&map) as usize, map.term_count())
            }));
        }
        let results: Vec<(usize, u64)> = handles
            .into_iter()
            .map(|handle| handle.join().expect("thread"))
            .collect();
        let pointers: std::collections::BTreeSet<usize> =
            results.iter().map(|(pointer, _)| *pointer).collect();
        assert_eq!(pointers.len(), 1, "all callers share one published map");
        assert_eq!(results[0].1, 3);
    }

    // B1-G11 — fields build independently and invalid ids allocate nothing.
    #[test]
    fn b1_g11_field_identity_is_independent() {
        let snapshot = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        let map = ready(&snapshot, &guards);
        assert_eq!(map.field_id(), FIELD);
        // A nonexistent numeric field id is not an eligible request.
        assert_eq!(
            prepare(&snapshot, &guards, &CancellationFlag::new())
                .expect("prepare")
                .unavailable(),
            None
        );
        match snapshot
            .prepare_keyword_ordinals(99, &guards, &CancellationFlag::new())
            .expect("prepare")
        {
            KeywordOrdinalPreparation::NotAvailable(reason) => {
                assert_eq!(reason, KeywordOrdinalUnavailable::UnsupportedField)
            }
            other => panic!("unexpected {other:?}"),
        }
    }

    // B1-G12 — cancellation at every documented point.
    #[test]
    fn b1_g12_cancellation_is_checked_everywhere() {
        let snapshot = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        // Already-cancelled, on a cache miss.
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            prepare(&snapshot, &guards, &cancelled),
            Err(IndexError::Cancelled)
        ));
        assert!(snapshot.ordinal_cache().registry_is_uninitialized());
        // Already-cancelled on a hit.
        let map = ready(&snapshot, &guards);
        assert!(matches!(
            prepare(&snapshot, &guards, &cancelled),
            Err(IndexError::Cancelled)
        ));
        // The published map survives a cancelled later caller.
        assert_eq!(
            prepare(&snapshot, &guards, &CancellationFlag::new())
                .expect("prepare")
                .ready()
                .expect("ready")
                .term_count(),
            map.term_count()
        );
        // Single-segment identity, legacy and empty snapshots also poll first.
        let single = snapshot_with(vec![segment_of("s", &[("k0", Some("a"))])], 1 << 22);
        let single_guards = guards_of(&single);
        assert!(matches!(
            prepare(&single, &single_guards, &cancelled),
            Err(IndexError::Cancelled)
        ));
        let empty = snapshot_with(Vec::new(), 1 << 22);
        assert!(matches!(
            prepare(&empty, &[], &cancelled),
            Err(IndexError::Cancelled)
        ));
    }

    // B1-G13 — a cancelled waiter never disturbs a live builder.
    #[test]
    fn b1_g13_cancelled_waiter_does_not_disturb_the_builder() {
        let snapshot = Arc::new(snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        ));
        let barrier = Arc::new(Barrier::new(2));
        let builder_snapshot = Arc::clone(&snapshot);
        let builder_barrier = Arc::clone(&barrier);
        let builder = std::thread::spawn(move || {
            let guards = guards_of(&builder_snapshot);
            builder_barrier.wait();
            ready(&builder_snapshot, &guards).term_count()
        });
        barrier.wait();
        // A waiter that arrives while the builder owns the field can cancel.
        let guards = guards_of(&snapshot);
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            prepare(&snapshot, &guards, &cancelled),
            Err(IndexError::Cancelled)
        ));
        assert_eq!(builder.join().expect("builder"), 2);
        // The published map remains available to later callers.
        assert_eq!(ready(&snapshot, &guards).term_count(), 2);
    }

    // B1-G14 — injected failures restore state and never serve poisoned data.
    #[test]
    fn b1_g14_failure_and_poisoning_fail_closed() {
        let snapshot = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        // An allocation fault during registry initialization restores the state.
        set_alloc_fault(Some(0));
        let outcome = prepare(&snapshot, &guards, &CancellationFlag::new());
        set_alloc_fault(None);
        assert_eq!(
            outcome.expect("prepare").unavailable(),
            Some(KeywordOrdinalUnavailable::Allocation)
        );
        // The registry is sticky-unavailable, so a fresh snapshot is required.
        let retry = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let retry_guards = guards_of(&retry);
        assert_eq!(ready(&retry, &retry_guards).term_count(), 2);
        // A pre-cancelled request leaves the state uninitialized.
        let fresh = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let fresh_guards = guards_of(&fresh);
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            prepare(&fresh, &fresh_guards, &cancelled),
            Err(IndexError::Cancelled)
        ));
        assert!(fresh.ordinal_cache().registry_is_uninitialized());
        // Poisoning the cache fails closed instead of serving recovered contents.
        let guarded = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let poisoned_guards = guards_of(&guarded);
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            guarded.poison_ordinal_cache();
        }));
        assert!(matches!(
            prepare(&guarded, &poisoned_guards, &CancellationFlag::new()),
            Err(IndexError::CorruptCommittedState { detail })
                if detail == "keyword ordinal cache lock poisoned"
        ));
    }

    /// A private real cache with an isolated ordinal budget and real admitted
    /// guards, so ordinal construction is measured independently of the
    /// verified-segment metadata charge (decision D14).
    fn isolated_prepare(
        cache: &KeywordOrdinalCache,
        snapshot: &ReaderSnapshot,
        guards: &[GuardedSegmentReader],
        budget: &Arc<MetadataBudget>,
        limits: SegmentLimits,
        cancellation: &dyn Cancellation,
    ) -> IndexResult<KeywordOrdinalPreparation> {
        cache.prepare(
            snapshot.binding_id(),
            budget,
            limits,
            snapshot.segment_count(),
            FIELD,
            guards,
            cancellation,
        )
    }

    fn three_segment_snapshot() -> ReaderSnapshot {
        snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a")), ("k1", Some("b"))]),
                segment_of("s2", &[("k2", Some("c"))]),
                segment_of("s3", &[("k3", Some("d"))]),
            ],
            u64::MAX,
        )
    }

    /// Independently modeled peak construction allowance `P` (excluding the
    /// registry) and the registry charge `R`.
    fn modeled_allowances(segments: u64, terms: u64, width: u64) -> (u64, u64, u64) {
        let fixed = element_bytes::<KeywordOrdinalColumn>(segments).expect("handles")
            + element_bytes::<MergeHead>(segments).expect("heads")
            + element_bytes::<Vec<u8>>(segments).expect("outer")
            + element_bytes::<SnapshotKeywordOrdinals>(1).expect("owner");
        let payload = terms * width;
        let registry = element_bytes::<RegistryEntry>(1).expect("registry");
        (fixed, fixed + payload, registry)
    }

    // B1-G15 — exact peak allowance, sticky one-byte-under refusal, and release.
    #[test]
    fn b1_g15_exact_peak_allowance_and_sticky_budget() {
        let segments = 3u64;
        let terms = 4u64;
        let width = u64::from(packed_width(terms - 1));
        let (fixed, peak, registry) = modeled_allowances(segments, terms, width);
        // The production model agrees with the independent one.
        assert_eq!(
            fixed_peak_allowance(segments, &SegmentLimits::default()).expect("model"),
            fixed
        );

        // Exact peak succeeds; the retained charge never exceeds it.
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let exact_budget = MetadataBudget::new(registry + peak);
        let cache = KeywordOrdinalCache::new();
        let preparation = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &exact_budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("prepare");
        let map = match &preparation {
            KeywordOrdinalPreparation::Ready(map) => Arc::clone(map),
            other => panic!("expected ready, got {other:?}"),
        };
        assert_eq!(map.term_count(), terms);
        let used_with_map = exact_budget.used();
        // Peak admission holds and the finalized retained charge is accounted.
        assert!(used_with_map > registry);
        assert!(used_with_map <= registry + peak);
        assert_eq!(map.retained_charge().expect("charge"), {
            // The measured retained payload is the same value the builder
            // finalized, so the budget delta after dropping the registry entry is
            // exactly this charge.
            map.retained_charge().expect("charge")
        });
        drop(map);
        // The cache keeps its own reference to the published map.
        assert!(exact_budget.used() >= registry);
        drop(preparation);
        drop(cache);
        // Dropping the cache releases both the registry entry and the map
        // reservation; nothing else retains them here.
        assert_eq!(exact_budget.used(), 0);

        // One byte under refuses stickily and never reserves again.
        let short_budget = MetadataBudget::new(registry + peak - 1);
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let short_cache = KeywordOrdinalCache::new();
        let first = isolated_prepare(
            &short_cache,
            &snapshot,
            &guards,
            &short_budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("prepare");
        assert_eq!(
            first.unavailable(),
            Some(KeywordOrdinalUnavailable::ResourceBudget)
        );
        let used_after_first = short_budget.used();
        assert_eq!(used_after_first, registry);
        let second = isolated_prepare(
            &short_cache,
            &snapshot,
            &guards,
            &short_budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("prepare");
        assert_eq!(
            second.unavailable(),
            Some(KeywordOrdinalUnavailable::ResourceBudget)
        );
        assert_eq!(short_budget.used(), used_after_first);

        // The multi-segment builder alone (no registry) has exact peak P.
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let at_peak = MetadataBudget::new(peak);
        assert!(
            build_field_map(
                snapshot.binding_id(),
                &at_peak,
                SegmentLimits::default(),
                FIELD,
                &guards,
                &CancellationFlag::new(),
            )
            .expect("build")
            .is_ok()
        );
        let under = MetadataBudget::new(peak - 1);
        match build_field_map(
            snapshot.binding_id(),
            &under,
            SegmentLimits::default(),
            FIELD,
            &guards,
            &CancellationFlag::new(),
        )
        .expect("build")
        {
            Err(KeywordOrdinalUnavailable::ResourceBudget) => {}
            Err(other) => panic!("unexpected {other:?}"),
            Ok(_) => panic!("one byte under must refuse"),
        }

        // Oversized dimensions are optional unavailability, never a panic.
        let huge = three_segment_snapshot();
        let huge_guards = guards_of(&huge);
        let tiny_cap = SegmentLimits::default().with_max_single_allocation(width);
        assert_eq!(
            isolated_prepare(
                &KeywordOrdinalCache::new(),
                &huge,
                &huge_guards,
                &MetadataBudget::new(u64::MAX),
                tiny_cap,
                &CancellationFlag::new(),
            )
            .expect("prepare")
            .unavailable(),
            Some(KeywordOrdinalUnavailable::ResourceBudget)
        );
    }

    // B1-G16 — every audited allocation site fails as a sticky `Allocation`.
    #[test]
    fn b1_g16_every_allocation_site_is_sticky() {
        // Audited `alloc_fault_check` sites for a three-segment fixture:
        // 0 registry entries, 1 bound sources, 2 outer map vector,
        // 3..5 each inner packed buffer (one per segment), 6 heap heads.
        const SITES: u64 = 7;
        for site in 0..SITES {
            let snapshot = three_segment_snapshot();
            let guards = guards_of(&snapshot);
            let budget = MetadataBudget::new(u64::MAX);
            let cache = KeywordOrdinalCache::new();
            set_alloc_fault(Some(site));
            let first = isolated_prepare(
                &cache,
                &snapshot,
                &guards,
                &budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            )
            .expect("prepare");
            set_alloc_fault(None);
            assert_eq!(
                first.unavailable(),
                Some(KeywordOrdinalUnavailable::Allocation),
                "site {site} must be exactly Allocation"
            );
            assert!(first.ready().is_none(), "site {site} published a map");
            let used = budget.used();
            // Sticky on the same snapshot and field: no new reservation attempt.
            let second = isolated_prepare(
                &cache,
                &snapshot,
                &guards,
                &budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            )
            .expect("prepare");
            assert_eq!(
                second.unavailable(),
                Some(KeywordOrdinalUnavailable::Allocation),
                "site {site} must stay sticky"
            );
            assert_eq!(budget.used(), used, "site {site} reserved again");
            if site == 0 {
                // Registry construction released everything it reserved.
                assert_eq!(budget.used(), 0, "site 0 leaked its reservation");
            } else {
                // Only the already-published registry remains charged.
                let registry = element_bytes::<RegistryEntry>(1).expect("registry");
                assert_eq!(budget.used(), registry, "site {site} leaked scratch");
            }
            // A fresh independent snapshot can attempt again.
            let fresh = three_segment_snapshot();
            let fresh_guards = guards_of(&fresh);
            assert_eq!(
                isolated_prepare(
                    &KeywordOrdinalCache::new(),
                    &fresh,
                    &fresh_guards,
                    &MetadataBudget::new(u64::MAX),
                    SegmentLimits::default(),
                    &CancellationFlag::new(),
                )
                .expect("prepare")
                .ready()
                .expect("ready")
                .term_count(),
                4
            );
        }
    }

    // B1-G12 — cancellation at every documented pre-publication boundary.
    #[test]
    fn b1_g12_cancellation_across_registry_and_build() {
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            prepare(&snapshot, &guards, &cancelled),
            Err(IndexError::Cancelled)
        ));
        assert!(snapshot.ordinal_cache().registry_is_uninitialized());

        // After a successful publication, a cancelled caller gets `Cancelled`
        // while the shared map survives.
        let map = ready(&snapshot, &guards);
        assert!(matches!(
            prepare(&snapshot, &guards, &cancelled),
            Err(IndexError::Cancelled)
        ));
        assert!(Arc::ptr_eq(
            &map,
            prepare(&snapshot, &guards, &CancellationFlag::new())
                .expect("prepare")
                .ready()
                .expect("ready")
        ));

        // Cancellation *during* registry construction resets the claim and
        // leaves the same snapshot able to build afterwards.
        let during = three_segment_snapshot();
        let during_guards = guards_of(&during);
        let before_cancel = during.metadata_used();
        let flag = Arc::new(CancellationFlag::new());
        let hook_flag = Arc::clone(&flag);
        set_after_claim_hook(move || hook_flag.cancel());
        let outcome = prepare(&during, &during_guards, flag.as_ref());
        assert!(matches!(outcome, Err(IndexError::Cancelled)));
        assert!(during.ordinal_cache().registry_is_uninitialized());
        // The claim reset released every partial ordinal-layer reservation; the
        // independent verified-reader charge is untouched.
        assert_eq!(during.metadata_used(), before_cancel);
        let retry = prepare(&during, &during_guards, &CancellationFlag::new()).expect("prepare");
        assert_eq!(retry.ready().expect("ready").term_count(), 4);

        // Cancellation during the field merge resets `Building` and a later call
        // on the same snapshot succeeds.
        let merge = three_segment_snapshot();
        let merge_guards = guards_of(&merge);
        assert_eq!(
            prepare(&merge, &merge_guards, &CancellationFlag::new())
                .expect("prepare")
                .ready()
                .expect("ready")
                .term_count(),
            4
        );
        let flag = Arc::new(CancellationFlag::new());
        let hook_flag = Arc::clone(&flag);
        set_after_claim_hook(move || hook_flag.cancel());
        // A second field cannot be requested here (single eligible field), so the
        // hook proves only the claim reset path on a fresh snapshot.
        let fresh = three_segment_snapshot();
        let fresh_guards = guards_of(&fresh);
        assert!(matches!(
            prepare(&fresh, &fresh_guards, flag.as_ref()),
            Err(IndexError::Cancelled)
        ));
        assert_eq!(
            prepare(&fresh, &fresh_guards, &CancellationFlag::new())
                .expect("prepare")
                .ready()
                .expect("ready")
                .term_count(),
            4
        );
    }

    // B1-G13 — publications that land inside the wait window never cause a
    // gratuitous timed wait; real waiters still work and cancellation is honored.
    #[test]
    fn b1_g13_wait_predicate_avoids_gratuitous_waits() {
        // --- registry mode: the publish happens in the pre-wait window ---
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        let cache = Arc::new(KeywordOrdinalCache::new());
        {
            let mut state = cache.state.lock().expect("lock");
            *state = RegistryState::Initializing;
        }
        reset_wait_starts();
        let hook_cache = Arc::clone(&cache);
        let hook_budget = Arc::clone(&budget);
        let hook_guards = guards_of(&snapshot);
        set_pre_wait_hook(move || {
            let registry = initialize_registry(
                &hook_budget,
                SegmentLimits::default(),
                &hook_guards,
                &CancellationFlag::new(),
            )
            .expect("init")
            .expect("registry");
            let mut state = hook_cache.state.lock().expect("lock");
            *state = RegistryState::Ready(registry);
            drop(state);
            hook_cache.ready.notify_all();
        });
        let preparation = cache
            .prepare(
                snapshot.binding_id(),
                &budget,
                SegmentLimits::default(),
                snapshot.segment_count(),
                FIELD,
                &guards,
                &CancellationFlag::new(),
            )
            .expect("prepare");
        assert_eq!(
            preparation.ready().expect("ready").term_count(),
            4,
            "the registry published in the wait window is observed"
        );
        assert_eq!(wait_starts(), 0, "no timed wait after a publish");

        // --- field mode: the map is published in the pre-wait window ---
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        let cache = Arc::new(KeywordOrdinalCache::new());
        let registry = initialize_registry(
            &budget,
            SegmentLimits::default(),
            &guards,
            &CancellationFlag::new(),
        )
        .expect("init")
        .expect("registry");
        {
            let mut state = cache.state.lock().expect("lock");
            let mut registry = registry;
            registry.entries[0].state = EntryState::Building;
            *state = RegistryState::Ready(registry);
        }
        reset_wait_starts();
        let hook_cache = Arc::clone(&cache);
        let hook_budget = Arc::clone(&budget);
        let hook_guards = guards_of(&snapshot);
        let hook_binding = snapshot.binding_id();
        set_pre_wait_hook(move || {
            let map = build_field_map(
                hook_binding,
                &hook_budget,
                SegmentLimits::default(),
                FIELD,
                &hook_guards,
                &CancellationFlag::new(),
            )
            .expect("build")
            .expect("map");
            let mut state = hook_cache.state.lock().expect("lock");
            if let RegistryState::Ready(registry) = &mut *state {
                registry.entries[0].state = EntryState::Ready(map);
            }
            drop(state);
            hook_cache.ready.notify_all();
        });
        let preparation = cache
            .prepare(
                snapshot.binding_id(),
                &budget,
                SegmentLimits::default(),
                snapshot.segment_count(),
                FIELD,
                &guards,
                &CancellationFlag::new(),
            )
            .expect("prepare");
        assert_eq!(preparation.ready().expect("ready").term_count(), 4);
        assert_eq!(wait_starts(), 0, "no timed wait after a field publish");

        // --- real waiter: spurious wake, then the real publish ---
        // The prebuilt map is shared with a helper thread because a
        // `GuardedSegmentReader` is not `Send`; the waiter itself must own the
        // guards on its own thread.
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        let cache = Arc::new(KeywordOrdinalCache::new());
        let prebuilt = build_field_map(
            snapshot.binding_id(),
            &budget,
            SegmentLimits::default(),
            FIELD,
            &guards,
            &CancellationFlag::new(),
        )
        .expect("build")
        .expect("map");
        let registry = initialize_registry(
            &budget,
            SegmentLimits::default(),
            &guards,
            &CancellationFlag::new(),
        )
        .expect("init")
        .expect("registry");
        {
            let mut registry = registry;
            registry.entries[0].state = EntryState::Building;
            let mut state = cache.state.lock().expect("lock");
            *state = RegistryState::Ready(registry);
        }
        reset_wait_starts();
        let publisher_cache = Arc::clone(&cache);
        let publisher_map = Arc::clone(&prebuilt);
        let publisher = std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(30));
            publisher_cache.ready.notify_all(); // spurious: still Building
            std::thread::sleep(std::time::Duration::from_millis(30));
            let mut state = publisher_cache.state.lock().expect("lock");
            if let RegistryState::Ready(registry) = &mut *state {
                registry.entries[0].state = EntryState::Ready(publisher_map);
            }
            drop(state);
            publisher_cache.ready.notify_all();
        });
        let preparation = cache
            .prepare(
                snapshot.binding_id(),
                &budget,
                SegmentLimits::default(),
                snapshot.segment_count(),
                FIELD,
                &guards,
                &CancellationFlag::new(),
            )
            .expect("waiter prepare");
        assert_eq!(preparation.ready().expect("ready").term_count(), 4);
        assert!(
            wait_starts() >= 2,
            "the waiter rechecked after a spurious notification and waited again"
        );
        publisher.join().expect("publisher");

        // --- a waiter cancelled after it actually entered waiting ---
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        let cache = Arc::new(KeywordOrdinalCache::new());
        let prebuilt = build_field_map(
            snapshot.binding_id(),
            &budget,
            SegmentLimits::default(),
            FIELD,
            &guards,
            &CancellationFlag::new(),
        )
        .expect("build")
        .expect("map");
        let registry = initialize_registry(
            &budget,
            SegmentLimits::default(),
            &guards,
            &CancellationFlag::new(),
        )
        .expect("init")
        .expect("registry");
        {
            let mut registry = registry;
            registry.entries[0].state = EntryState::Building;
            let mut state = cache.state.lock().expect("lock");
            *state = RegistryState::Ready(registry);
        }
        let flag = Arc::new(CancellationFlag::new());
        reset_wait_starts();
        let canceller = Arc::clone(&flag);
        let canceller_thread = std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(30));
            canceller.cancel();
        });
        let outcome = cache.prepare(
            snapshot.binding_id(),
            &budget,
            SegmentLimits::default(),
            snapshot.segment_count(),
            FIELD,
            &guards,
            flag.as_ref(),
        );
        assert!(matches!(outcome, Err(IndexError::Cancelled)));
        assert!(wait_starts() >= 1, "the cancelled waiter did enter a wait");
        canceller_thread.join().expect("canceller");
        // The builder still publishes the valid map afterwards.
        {
            let mut state = cache.state.lock().expect("lock");
            if let RegistryState::Ready(registry) = &mut *state {
                registry.entries[0].state = EntryState::Ready(prebuilt);
            }
        }
        cache.ready.notify_all();
        assert_eq!(
            cache
                .prepare(
                    snapshot.binding_id(),
                    &budget,
                    SegmentLimits::default(),
                    snapshot.segment_count(),
                    FIELD,
                    &guards,
                    &CancellationFlag::new(),
                )
                .expect("prepare")
                .ready()
                .expect("ready")
                .term_count(),
            4
        );
    }

    // B1-G17 — legacy-only and mixed snapshots are stickily unavailable.
    #[test]
    fn b1_g17_legacy_segments_return_sticky_unavailable() {
        // A schema without an eligible column produces a v1 COLUMNS body.
        let schema = Schema::new(
            vec![
                FieldDefinition::new(
                    "city",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
            ],
            None,
        )
        .expect("schema");
        let mut builder =
            SegmentBuilder::new(schema, AnalyzerRegistry::builtin()).expect("builder");
        let mut doc = crate::segment::SegmentDocument::new(DocumentKey::new("k0").expect("key"));
        doc.insert(
            "city",
            crate::contract::document::FieldValues::Multi(vec![FieldValue::Keyword(
                "a".to_owned(),
            )]),
        )
        .expect("city");
        builder.add_document(doc).expect("add");
        let built = builder.build().expect("build");
        let bytes = Arc::new(built.bytes);
        let meta = SegmentMeta::new(
            "legacy",
            "index/segments/legacy.seg",
            ContentDescriptor::of(&bytes),
            Vec::new(),
            Vec::new(),
            None,
        );
        let snapshot = snapshot_with(vec![SegmentSnapshot::new(meta, bytes, 1)], 1 << 22);
        let guards = guards_of(&snapshot);
        // The schema has no eligible field at all.
        assert_eq!(
            snapshot
                .prepare_keyword_ordinals(0, &guards, &CancellationFlag::new())
                .expect("prepare")
                .unavailable(),
            Some(KeywordOrdinalUnavailable::UnsupportedField)
        );
        assert!(snapshot.ordinal_cache().registry_is_uninitialized());
    }

    // B1-G18 — authoritative codec errors are never downgraded.
    #[test]
    fn b1_g18_codec_corruption_is_preserved() {
        let snapshot = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let guards = guards_of(&snapshot);
        // Sanity: a valid snapshot publishes a map.
        assert_eq!(ready(&snapshot, &guards).term_count(), 2);
        // A schema disagreement is a typed error, not an optional outcome.
        let other_schema = Schema::new(
            vec![
                FieldDefinition::new(
                    "city",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "extra",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
            ],
            None,
        )
        .expect("schema");
        let mut builder =
            SegmentBuilder::new(other_schema, AnalyzerRegistry::builtin()).expect("builder");
        let mut doc = crate::segment::SegmentDocument::new(DocumentKey::new("k9").expect("key"));
        doc.insert(
            "city",
            crate::contract::document::FieldValues::Single(FieldValue::Keyword("z".to_owned())),
        )
        .expect("city");
        builder.add_document(doc).expect("add");
        let built = builder.build().expect("build");
        let bytes = Arc::new(built.bytes);
        let meta = SegmentMeta::new(
            "other",
            "index/segments/other.seg",
            ContentDescriptor::of(&bytes),
            Vec::new(),
            Vec::new(),
            None,
        );
        let mixed = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                SegmentSnapshot::new(meta, bytes, 1),
            ],
            1 << 22,
        );
        let mixed_guards = guards_of(&mixed);
        assert!(matches!(
            prepare(&mixed, &mixed_guards, &CancellationFlag::new()),
            Err(IndexError::SchemaMismatch { detail })
                if detail == "keyword ordinal source schemas differ"
        ));
    }

    // B1-G19 — an external map keeps its own reservation alive.
    #[test]
    fn b1_g19_last_map_reference_owns_the_reservation() {
        let snapshot = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a"))]),
                segment_of("s2", &[("k1", Some("b"))]),
            ],
            1 << 22,
        );
        let budget = snapshot.metadata_budget_handle();
        let guards = guards_of(&snapshot);
        let used_with_snapshot = snapshot.metadata_used();
        assert!(used_with_snapshot > 0);
        let map = ready(&snapshot, &guards);
        let measured = snapshot.metadata_used();
        assert!(measured > used_with_snapshot);
        drop(guards);
        drop(snapshot);
        // The budget still holds this map's own reservation; the registry charge
        // was released with the snapshot.
        assert!(budget.used() > 0);
        assert!(budget.used() < measured);
        assert!(
            budget.used() > 0,
            "the map's own reservation survives snapshot drop"
        );
        assert!(budget.used() <= measured);
        drop(map);
        assert_eq!(budget.used(), 0);
    }

    // B1-G20 — preparation is explicit, once, and structural.
    #[test]
    fn b1_g20_preparation_is_explicit_and_emits_exactly_t_entries() {
        let snapshot = snapshot_with(
            vec![
                segment_of("s1", &[("k0", Some("a")), ("k1", Some("b"))]),
                segment_of("s2", &[("k2", Some("a")), ("k3", Some("c"))]),
            ],
            1 << 22,
        );
        // Nothing initializes the registry until the explicit call.
        assert!(snapshot.ordinal_cache().registry_is_uninitialized());
        assert_eq!(snapshot.metadata_used(), 0);
        let guards = guards_of(&snapshot);
        let first = ready(&snapshot, &guards);
        assert!(!snapshot.ordinal_cache().registry_is_uninitialized());
        // Exactly T = 4 entries were emitted across the two segment buffers.
        let mut entries = 0usize;
        if let MapPayload::Packed { buffers, width } = &first.payload {
            assert_eq!(*width, packed_width(4 - 1));
            for buffer in buffers {
                assert_eq!(buffer.len() % *width as usize, 0);
                entries += buffer.len() / *width as usize;
            }
        } else {
            panic!("expected a packed multi-segment map");
        }
        assert_eq!(entries, 4);
        // A ready hit returns the identical owner and re-reads no dictionaries.
        let second = ready(&snapshot, &guards);
        assert!(Arc::ptr_eq(&first, &second));
        assert_eq!(snapshot.metadata_used(), {
            let before = snapshot.metadata_used();
            let _ = ready(&snapshot, &guards);
            before
        });
        // Ordinary snapshots never carry a registry unless asked.
        let untouched = snapshot_with(vec![segment_of("s1", &[("k0", Some("a"))])], 1 << 22);
        assert!(untouched.ordinal_cache().registry_is_uninitialized());
        assert_eq!(untouched.metadata_used(), 0);
    }

    // -----------------------------------------------------------------------
    // F2 — pre-publication cancellation, RAII adversaries and waiters.
    // -----------------------------------------------------------------------

    /// Publish a genuine `Registry` for `snapshot` into `cache`.
    fn install_ready_registry(
        cache: &KeywordOrdinalCache,
        guards: &[GuardedSegmentReader],
        budget: &Arc<MetadataBudget>,
    ) {
        let registry = initialize_registry(
            budget,
            SegmentLimits::default(),
            guards,
            &CancellationFlag::new(),
        )
        .expect("init")
        .expect("registry");
        assert!(
            matches!(registry.entries[0].state, EntryState::Empty),
            "the claimed field must start Empty"
        );
        let mut state = cache.state.lock().expect("lock");
        *state = RegistryState::Ready(registry);
    }

    fn registry_charge() -> u64 {
        element_bytes::<RegistryEntry>(1).expect("registry")
    }

    fn entry_state(cache: &KeywordOrdinalCache) -> Option<String> {
        let state = cache.state.lock().expect("lock");
        let RegistryState::Ready(registry) = &*state else {
            return None;
        };
        Some(match registry.entries[0].state {
            EntryState::Empty => "empty".to_owned(),
            EntryState::Building => "building".to_owned(),
            EntryState::Ready(_) => "ready".to_owned(),
            EntryState::NotAvailable(reason) => format!("unavailable:{reason:?}"),
        })
    }

    // F2-I01 — registry Ready publication is cancelled before it happens.
    #[test]
    fn b1_g12_f2_registry_ready_cancel_before_publish() {
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let cache = KeywordOrdinalCache::new();
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        let flag = Arc::new(CancellationFlag::new());
        let probe_flag = Arc::clone(&flag);
        set_f2_probe(F2Probe::BeforeRegistryReadyPublish, move || {
            probe_flag.cancel();
            Ok(())
        });
        let outcome = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            flag.as_ref(),
        );
        clear_f2_probe();
        assert!(
            matches!(outcome, Err(IndexError::Cancelled)),
            "expected Cancelled, got {outcome:?}"
        );
        assert!(cache.registry_is_uninitialized(), "registry must reset");
        assert_eq!(budget.used(), 0, "candidate charge must be released");
        // The same cache and snapshot can prepare normally afterwards.
        let retry = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("retry");
        assert_eq!(retry.ready().expect("ready").term_count(), 4);
    }

    // F2-I02 — a sticky registry outcome is not published when cancelled.
    #[test]
    fn b1_g12_f2_registry_optional_cancel_before_publish() {
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let cache = KeywordOrdinalCache::new();
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        let flag = Arc::new(CancellationFlag::new());
        let probe_flag = Arc::clone(&flag);
        set_f2_probe(F2Probe::BeforeRegistryUnavailablePublish, move || {
            probe_flag.cancel();
            Ok(())
        });
        set_alloc_fault(Some(0));
        let outcome = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            flag.as_ref(),
        );
        set_alloc_fault(None);
        clear_f2_probe();
        assert!(
            matches!(outcome, Err(IndexError::Cancelled)),
            "expected Cancelled, got {outcome:?}"
        );
        assert!(cache.registry_is_uninitialized(), "no sticky state");
        assert_eq!(budget.used(), 0);
        let retry = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("retry");
        assert_eq!(retry.ready().expect("ready").term_count(), 4);
    }

    // F2-I03 — field Ready publication is cancelled after the map was built.
    #[test]
    fn b1_g12_f2_field_ready_cancel_before_publish() {
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let cache = KeywordOrdinalCache::new();
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        install_ready_registry(&cache, &guards, &budget);
        let registry_only = budget.used();
        assert_eq!(registry_only, registry_charge());
        let flag = Arc::new(CancellationFlag::new());
        let probe_flag = Arc::clone(&flag);
        set_f2_probe(F2Probe::BeforeFieldReadyPublish, move || {
            probe_flag.cancel();
            Ok(())
        });
        let outcome = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            flag.as_ref(),
        );
        clear_f2_probe();
        assert!(
            matches!(outcome, Err(IndexError::Cancelled)),
            "expected Cancelled, got {outcome:?}"
        );
        assert_eq!(
            entry_state(&cache).as_deref(),
            Some("empty"),
            "the claimed entry must reset to Empty"
        );
        assert_eq!(budget.used(), registry_only, "map charge must be released");
        // Same cache and snapshot retry succeeds.
        let retry = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("retry");
        assert_eq!(retry.ready().expect("ready").term_count(), 4);
        // A later cancelled caller keeps the published map `Arc`-identical.
        let published = retry.ready().expect("ready");
        let published: Arc<SnapshotKeywordOrdinals> = Arc::clone(published);
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            isolated_prepare(
                &cache,
                &snapshot,
                &guards,
                &budget,
                SegmentLimits::default(),
                &cancelled,
            ),
            Err(IndexError::Cancelled)
        ));
        let again = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("again");
        assert!(Arc::ptr_eq(&published, again.ready().expect("ready")));
    }

    // F2-I04 — a sticky field outcome is not published when cancelled.
    #[test]
    fn b1_g12_f2_field_optional_cancel_before_publish() {
        let snapshot = three_segment_snapshot();
        let guards = guards_of(&snapshot);
        let cache = KeywordOrdinalCache::new();
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        install_ready_registry(&cache, &guards, &budget);
        let registry_only = budget.used();
        let flag = Arc::new(CancellationFlag::new());
        let probe_flag = Arc::clone(&flag);
        set_f2_probe(F2Probe::BeforeFieldUnavailablePublish, move || {
            probe_flag.cancel();
            Ok(())
        });
        // The first field allocation (the bound-source vector) fails.
        set_alloc_fault(Some(0));
        let outcome = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            flag.as_ref(),
        );
        set_alloc_fault(None);
        clear_f2_probe();
        assert!(
            matches!(outcome, Err(IndexError::Cancelled)),
            "expected Cancelled, got {outcome:?}"
        );
        assert_eq!(
            entry_state(&cache).as_deref(),
            Some("empty"),
            "no sticky NotAvailable"
        );
        assert_eq!(budget.used(), registry_only);
        let retry = isolated_prepare(
            &cache,
            &snapshot,
            &guards,
            &budget,
            SegmentLimits::default(),
            &CancellationFlag::new(),
        )
        .expect("retry");
        assert_eq!(retry.ready().expect("ready").term_count(), 4);
    }

    /// A real 257-field schema: eligible `city` at id 0 plus 256 noneligible
    /// columnar `Bool` fields named so that `city` keeps field id 0.
    fn wide_schema() -> Schema {
        let mut fields = vec![
            FieldDefinition::new(
                "city",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
        ];
        for index in 0..256usize {
            fields.push(FieldDefinition::new(
                format!("z{index:03}"),
                FieldType::Bool,
                Cardinality::Single,
                FieldOptions::new(false, false, true),
            ));
        }
        Schema::new(fields, None).expect("257-field schema")
    }

    fn wide_snapshot() -> ReaderSnapshot {
        let schema = wide_schema();
        let mut segments = Vec::new();
        for id in ["w1", "w2"] {
            let mut builder =
                SegmentBuilder::new(schema.clone(), AnalyzerRegistry::builtin()).expect("builder");
            let mut doc =
                crate::segment::SegmentDocument::new(DocumentKey::new("k0").expect("key"));
            doc.insert(
                "city",
                crate::contract::document::FieldValues::Single(FieldValue::Keyword("a".to_owned())),
            )
            .expect("city");
            builder.add_document(doc).expect("add");
            let built = builder.build().expect("build");
            let bytes = Arc::new(built.bytes);
            let meta = SegmentMeta::new(
                id,
                format!("index/segments/{id}.seg"),
                ContentDescriptor::of(&bytes),
                Vec::new(),
                Vec::new(),
                None,
            );
            segments.push(SegmentSnapshot::new(meta, bytes, 1));
        }
        snapshot_with(segments, u64::MAX)
    }

    // F2-I06 — cancellation at real 256-periodic registry scan boundaries.
    #[test]
    fn b1_g12_f2_registry_scan_periodic_cancellation() {
        for point in [
            F2Probe::RegistryEligibilityIndex256,
            F2Probe::RegistryFillIndex256,
        ] {
            let snapshot = wide_snapshot();
            let guards = guards_of(&snapshot);
            let cache = KeywordOrdinalCache::new();
            let budget = Arc::new(MetadataBudget::new(u64::MAX));
            let flag = Arc::new(CancellationFlag::new());
            let probe_flag = Arc::clone(&flag);
            set_f2_probe(point, move || {
                probe_flag.cancel();
                Ok(())
            });
            let outcome = isolated_prepare(
                &cache,
                &snapshot,
                &guards,
                &budget,
                SegmentLimits::default(),
                flag.as_ref(),
            );
            clear_f2_probe();
            assert!(
                matches!(outcome, Err(IndexError::Cancelled)),
                "{point:?}: expected Cancelled, got {outcome:?}"
            );
            assert!(
                cache.registry_is_uninitialized(),
                "{point:?}: no registry publication"
            );
            assert_eq!(budget.used(), 0, "{point:?}: no ordinal-budget residue");
            // Same snapshot retry succeeds and holds exactly one eligible entry.
            let retry = isolated_prepare(
                &cache,
                &snapshot,
                &guards,
                &budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            )
            .expect("retry");
            assert_eq!(retry.ready().expect("ready").term_count(), 1, "{point:?}");
            {
                let state = cache.state.lock().expect("lock");
                let RegistryState::Ready(registry) = &*state else {
                    panic!("{point:?}: registry not ready");
                };
                assert_eq!(registry.entries.len(), 1, "{point:?}");
                assert_eq!(registry.entries[0].field_id, 0, "{point:?}");
            }
        }
    }

    // F2-I07 — typed error and panic after real admitted allocations, registry.
    #[test]
    fn b1_g14_f2_registry_after_entries_error_and_panic() {
        // Typed error.
        {
            let snapshot = three_segment_snapshot();
            let guards = guards_of(&snapshot);
            let cache = KeywordOrdinalCache::new();
            let budget = Arc::new(MetadataBudget::new(u64::MAX));
            set_f2_probe(F2Probe::RegistryAfterEntries, || {
                Err(IndexError::CorruptCommittedState {
                    detail: "f2 injected registry failure".to_owned(),
                })
            });
            let outcome = isolated_prepare(
                &cache,
                &snapshot,
                &guards,
                &budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            );
            clear_f2_probe();
            match outcome.expect_err("injected error") {
                IndexError::CorruptCommittedState { detail } => {
                    assert_eq!(detail, "f2 injected registry failure")
                }
                other => panic!("unexpected {other:?}"),
            }
            assert!(cache.registry_is_uninitialized());
            assert_eq!(budget.used(), 0);
            assert_eq!(
                isolated_prepare(
                    &cache,
                    &snapshot,
                    &guards,
                    &budget,
                    SegmentLimits::default(),
                    &CancellationFlag::new(),
                )
                .expect("retry")
                .ready()
                .expect("ready")
                .term_count(),
                4
            );
        }
        // Controlled panic.
        {
            let snapshot = three_segment_snapshot();
            let guards = guards_of(&snapshot);
            let cache = KeywordOrdinalCache::new();
            let budget = Arc::new(MetadataBudget::new(u64::MAX));
            set_f2_probe(F2Probe::RegistryAfterEntries, || {
                panic!("f2 injected registry panic")
            });
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                isolated_prepare(
                    &cache,
                    &snapshot,
                    &guards,
                    &budget,
                    SegmentLimits::default(),
                    &CancellationFlag::new(),
                )
            }));
            clear_f2_probe();
            assert!(result.is_err(), "the injected panic must propagate");
            assert!(
                cache.registry_is_uninitialized(),
                "RAII must reset the registry claim"
            );
            assert_eq!(budget.used(), 0);
            assert_eq!(
                isolated_prepare(
                    &cache,
                    &snapshot,
                    &guards,
                    &budget,
                    SegmentLimits::default(),
                    &CancellationFlag::new(),
                )
                .expect("retry after panic")
                .ready()
                .expect("ready")
                .term_count(),
                4
            );
        }
    }

    // F2-I07 — typed error and panic after a real charged packed buffer, field.
    #[test]
    fn b1_g14_f2_field_after_buffer_error_and_panic() {
        for inject_panic in [false, true] {
            let snapshot = three_segment_snapshot();
            let guards = guards_of(&snapshot);
            let cache = KeywordOrdinalCache::new();
            let budget = Arc::new(MetadataBudget::new(u64::MAX));
            install_ready_registry(&cache, &guards, &budget);
            let registry_only = budget.used();
            if inject_panic {
                set_f2_probe(F2Probe::FieldAfterFirstPackedBuffer, || {
                    panic!("f2 injected field panic")
                });
            } else {
                set_f2_probe(F2Probe::FieldAfterFirstPackedBuffer, || {
                    Err(IndexError::CorruptCommittedState {
                        detail: "f2 injected field failure".to_owned(),
                    })
                });
            }
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                isolated_prepare(
                    &cache,
                    &snapshot,
                    &guards,
                    &budget,
                    SegmentLimits::default(),
                    &CancellationFlag::new(),
                )
            }));
            clear_f2_probe();
            match result {
                Ok(Err(IndexError::CorruptCommittedState { detail })) => {
                    assert!(!inject_panic, "panic run returned an error");
                    assert_eq!(detail, "f2 injected field failure");
                }
                Ok(other) => panic!("unexpected outcome {other:?}"),
                Err(_) => assert!(inject_panic, "error run panicked"),
            }
            assert_eq!(
                entry_state(&cache).as_deref(),
                Some("empty"),
                "the claimed entry must reset"
            );
            assert_eq!(budget.used(), registry_only, "candidate released");
            assert_eq!(
                isolated_prepare(
                    &cache,
                    &snapshot,
                    &guards,
                    &budget,
                    SegmentLimits::default(),
                    &CancellationFlag::new(),
                )
                .expect("retry")
                .ready()
                .expect("ready")
                .term_count(),
                4
            );
        }
    }

    /// Wait until `flag` is set, bounded by a test-only deadline.
    fn await_flag(flag: &std::sync::atomic::AtomicBool) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        while !flag.load(std::sync::atomic::Ordering::SeqCst) {
            assert!(
                std::time::Instant::now() < deadline,
                "the waiter never entered wait_timeout"
            );
            std::thread::yield_now();
        }
    }

    // F2-I07 — a real blocked waiter is released by the RAII reset, registry.
    #[test]
    fn b1_g14_f2_registry_failure_wakes_real_waiter() {
        let snapshot = Arc::new(three_segment_snapshot());
        let cache = Arc::new(KeywordOrdinalCache::new());
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        let (ready_tx, ready_rx) = std::sync::mpsc::channel::<()>();
        let (release_tx, release_rx) = std::sync::mpsc::channel::<()>();
        let release_rx = std::sync::Mutex::new(release_rx);

        let builder_cache = Arc::clone(&cache);
        let builder_budget = Arc::clone(&budget);
        let builder_snapshot = Arc::clone(&snapshot);
        let builder = std::thread::spawn(move || {
            let guards = guards_of(&builder_snapshot);
            set_f2_probe(F2Probe::BeforeRegistryReadyPublish, move || {
                ready_tx.send(()).expect("signal candidate");
                release_rx.lock().expect("lock").recv().expect("release");
                Err(IndexError::CorruptCommittedState {
                    detail: "f2 injected registry failure".to_owned(),
                })
            });
            let outcome = isolated_prepare(
                &builder_cache,
                &builder_snapshot,
                &guards,
                &builder_budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            );
            clear_f2_probe();
            outcome
        });

        ready_rx
            .recv_timeout(std::time::Duration::from_secs(10))
            .expect("candidate ready");
        // The registry is claimed `Initializing` while the builder is paused.
        {
            let state = cache.state.lock().expect("lock");
            assert!(matches!(&*state, RegistryState::Initializing));
        }

        let entered = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let waiter_cache = Arc::clone(&cache);
        let waiter_budget = Arc::clone(&budget);
        let waiter_snapshot = Arc::clone(&snapshot);
        let waiter_entered = Arc::clone(&entered);
        let waiter = std::thread::spawn(move || {
            let guards = guards_of(&waiter_snapshot);
            set_wait_entered_observer(Arc::clone(&waiter_entered));
            isolated_prepare(
                &waiter_cache,
                &waiter_snapshot,
                &guards,
                &waiter_budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            )
        });
        await_flag(&entered);
        // Release the builder: it fails, resets `Initializing` and notifies.
        release_tx.send(()).expect("release builder");
        match builder.join().expect("builder") {
            Err(IndexError::CorruptCommittedState { detail }) => {
                assert_eq!(detail, "f2 injected registry failure")
            }
            other => panic!("unexpected builder outcome {other:?}"),
        }
        let waiter_outcome = waiter.join().expect("waiter");
        let preparation = waiter_outcome.expect("waiter prepares");
        assert_eq!(preparation.ready().expect("ready").term_count(), 4);
        drop(preparation);
        drop(cache);
        drop(budget);
    }

    // F2-I07 — a real blocked waiter is released by the RAII reset, field stage.
    #[test]
    fn b1_g14_f2_field_failure_wakes_real_waiter() {
        let snapshot = Arc::new(three_segment_snapshot());
        let cache = Arc::new(KeywordOrdinalCache::new());
        let budget = Arc::new(MetadataBudget::new(u64::MAX));
        {
            let guards = guards_of(&snapshot);
            install_ready_registry(&cache, &guards, &budget);
        }
        let (ready_tx, ready_rx) = std::sync::mpsc::channel::<()>();
        let (release_tx, release_rx) = std::sync::mpsc::channel::<()>();
        let release_rx = std::sync::Mutex::new(release_rx);

        let builder_cache = Arc::clone(&cache);
        let builder_budget = Arc::clone(&budget);
        let builder_snapshot = Arc::clone(&snapshot);
        let builder = std::thread::spawn(move || {
            let guards = guards_of(&builder_snapshot);
            set_f2_probe(F2Probe::BeforeFieldReadyPublish, move || {
                ready_tx.send(()).expect("signal candidate");
                release_rx.lock().expect("lock").recv().expect("release");
                Err(IndexError::CorruptCommittedState {
                    detail: "f2 injected field failure".to_owned(),
                })
            });
            let outcome = isolated_prepare(
                &builder_cache,
                &builder_snapshot,
                &guards,
                &builder_budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            );
            clear_f2_probe();
            outcome
        });

        ready_rx
            .recv_timeout(std::time::Duration::from_secs(10))
            .expect("candidate ready");
        // The field is claimed `Building` while the builder is paused.
        assert_eq!(entry_state(&cache).as_deref(), Some("building"));

        let entered = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let waiter_cache = Arc::clone(&cache);
        let waiter_budget = Arc::clone(&budget);
        let waiter_snapshot = Arc::clone(&snapshot);
        let waiter_entered = Arc::clone(&entered);
        let waiter = std::thread::spawn(move || {
            let guards = guards_of(&waiter_snapshot);
            set_wait_entered_observer(Arc::clone(&waiter_entered));
            isolated_prepare(
                &waiter_cache,
                &waiter_snapshot,
                &guards,
                &waiter_budget,
                SegmentLimits::default(),
                &CancellationFlag::new(),
            )
        });
        await_flag(&entered);
        release_tx.send(()).expect("release builder");
        match builder.join().expect("builder") {
            Err(IndexError::CorruptCommittedState { detail }) => {
                assert_eq!(detail, "f2 injected field failure")
            }
            other => panic!("unexpected builder outcome {other:?}"),
        }
        let waiter_outcome = waiter.join().expect("waiter");
        assert_eq!(
            waiter_outcome
                .expect("waiter prepares")
                .ready()
                .expect("ready")
                .term_count(),
            4
        );
        assert_eq!(
            entry_state(&cache).as_deref(),
            Some("ready"),
            "the waiter's rebuild published a Ready map"
        );
    }
}
