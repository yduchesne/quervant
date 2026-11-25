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
use crate::segment::error::SegmentError;
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
                    match initialize_registry(budget, limits, guards) {
                        Ok(Ok(registry)) => {
                            let mut state = self.lock()?;
                            *state = RegistryState::Ready(registry);
                            drop(state);
                            init_guard.disarm();
                            self.ready.notify_all();
                            // Continue to this caller's field lookup.
                            continue;
                        }
                        Ok(Err(reason)) => {
                            let mut state = self.lock()?;
                            *state = RegistryState::NotAvailable(reason);
                            drop(state);
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
                    self.wait(cancellation)?;
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

    /// Timed wait with predicate recheck after every wake-up.
    fn wait(&self, cancellation: &dyn Cancellation) -> IndexResult<()> {
        let state = self.lock()?;
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
        match build_field_map(
            snapshot_binding,
            budget,
            limits,
            field_id,
            guards,
            cancellation,
        ) {
            Ok(Ok(owner)) => {
                let mut state = self.lock()?;
                if let RegistryState::Ready(registry) = &mut *state {
                    registry.entries[index].state = EntryState::Ready(Arc::clone(&owner));
                }
                drop(state);
                build_guard.disarm();
                self.ready.notify_all();
                poll(cancellation)?;
                Ok(KeywordOrdinalPreparation::Ready(owner))
            }
            Ok(Err(reason)) => {
                let mut state = self.lock()?;
                if let RegistryState::Ready(registry) = &mut *state {
                    registry.entries[index].state = EntryState::NotAvailable(reason);
                }
                drop(state);
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
) -> IndexResult<Result<Registry, KeywordOrdinalUnavailable>> {
    let Some(first) = guards.first() else {
        return Err(guard_mismatch());
    };
    let schema: &CodecSchema = first.reader().schema();
    for guard in guards.iter().skip(1) {
        if guard.reader().schema() != schema {
            return Err(schema_mismatch());
        }
    }
    let eligible = schema
        .fields()
        .iter()
        .filter(|f| is_eligible_field(f))
        .count();
    let allowance = match element_bytes::<RegistryEntry>(eligible as u64) {
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
    if meter.charge_vec::<RegistryEntry>(eligible as u64).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
    }
    let mut entries: Vec<RegistryEntry> = Vec::new();
    if alloc_fault_check().is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::Allocation));
    }
    if entries.try_reserve_exact(eligible).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::Allocation));
    }
    // Entries are already in ascending field-id order: no name strings retained.
    for field in schema.fields() {
        if is_eligible_field(field) {
            entries.push(RegistryEntry {
                field_id: field.id,
                state: EntryState::Empty,
            });
        }
    }
    let measured = match capacity_bytes::<RegistryEntry>(entries.capacity()) {
        Ok(bytes) => bytes,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    let reservation = match meter.finalize(measured) {
        Ok(reservation) => reservation,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
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

    // Bind every source exactly once and validate new-layout availability first.
    let mut sources: Vec<KeywordOrdinalColumn<'_>> = Vec::new();
    if alloc_fault_check().is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::Allocation));
    }
    if sources.try_reserve_exact(segment_count).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::Allocation));
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

    // One meter holds the construction scratch plus the final retained payload.
    let scratch = match capacity_bytes::<KeywordOrdinalColumn>(sources.capacity())
        .and_then(|bytes| accumulate(bytes, capacity_bytes::<MergeHead>(segment_count)?))
    {
        Ok(bytes) => bytes,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    let mut meter = match MetadataMeter::reserve(budget, scratch) {
        Ok(meter) => meter,
        Err(_) => return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget)),
    };
    if meter.extend(payload_bytes).is_err() {
        return Ok(Err(KeywordOrdinalUnavailable::ResourceBudget));
    }

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

    // B1-G15 — sticky resource-budget refusal and exact retained accounting.
    #[test]
    fn b1_g15_resource_budget_is_sticky_and_retained_accounting_is_exact() {
        let segments = || {
            vec![
                segment_of("s1", &[("k0", Some("a")), ("k1", Some("b"))]),
                segment_of("s2", &[("k2", Some("c"))]),
            ]
        };
        // The verified-reader state is a separate pre-existing charge; the
        // ordinal layer models its own scratch and payload on top of it.
        let verified = {
            let probe = snapshot_with(segments(), u64::MAX);
            let _probe_guards = guards_of(&probe);
            probe.metadata_used()
        };

        // A zero metadata cap cannot admit even the registry: sticky refusal.
        let short = snapshot_with(segments(), 0);
        let short_guards = guards_of(&short);
        let used = short.metadata_used();
        let first = prepare(&short, &short_guards, &CancellationFlag::new()).expect("prepare");
        assert_eq!(
            first.unavailable(),
            Some(KeywordOrdinalUnavailable::ResourceBudget)
        );
        // Sticky: a second request performs no further reservation attempt.
        assert_eq!(
            prepare(&short, &short_guards, &CancellationFlag::new())
                .expect("prepare")
                .unavailable(),
            Some(KeywordOrdinalUnavailable::ResourceBudget)
        );
        assert_eq!(short.metadata_used(), used);

        // Exact retained accounting: final accounting equals the registry plus
        // the measured finished map, with the construction scratch released.
        let generous = snapshot_with(segments(), 1 << 22);
        let generous_guards = guards_of(&generous);
        let before = generous.metadata_used();
        assert!(before >= verified);
        let map = ready(&generous, &generous_guards);
        let retained = map.retained_charge().expect("charge");
        assert!(retained > 0);
        assert!(generous.metadata_used() > before, "the registry is charged");
        // Dropping the only map releases its own reservation; the registry entry
        // remains charged until the snapshot is dropped.
        let with_map = generous.metadata_used();
        drop(map);
        // The registry retains its own reference, so the reservation outlives the
        // caller's `Arc` and is released with the snapshot.
        assert_eq!(generous.metadata_used(), with_map);
        drop(generous_guards);
        drop(generous);
    }

    // B1-G16 — every new fallible allocation site can fail stickily.
    #[test]
    fn b1_g16_allocation_faults_are_sticky() {
        for fault in 0..6u64 {
            let snapshot = snapshot_with(
                vec![
                    segment_of("s1", &[("k0", Some("a")), ("k1", Some("b"))]),
                    segment_of("s2", &[("k2", Some("c"))]),
                    segment_of("s3", &[("k3", Some("d"))]),
                ],
                1 << 24,
            );
            let guards = guards_of(&snapshot);
            set_alloc_fault(Some(fault));
            let outcome = prepare(&snapshot, &guards, &CancellationFlag::new());
            set_alloc_fault(None);
            let outcome = outcome.expect("prepare");
            match outcome.unavailable() {
                Some(KeywordOrdinalUnavailable::Allocation)
                | Some(KeywordOrdinalUnavailable::ResourceBudget) => {}
                other => panic!("fault {fault}: unexpected {other:?}"),
            }
            // No partial map is ever published.
            assert!(outcome.ready().is_none());
            // A fresh snapshot can attempt again.
            let fresh = snapshot_with(
                vec![
                    segment_of("s1", &[("k0", Some("a")), ("k1", Some("b"))]),
                    segment_of("s2", &[("k2", Some("c"))]),
                    segment_of("s3", &[("k3", Some("d"))]),
                ],
                1 << 24,
            );
            let fresh_guards = guards_of(&fresh);
            assert_eq!(ready(&fresh, &fresh_guards).term_count(), 4);
        }
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
}
