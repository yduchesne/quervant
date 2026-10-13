//! Process-local pinned point-in-time handles (PR 6).
//!
//! A `PitHandle` pins exactly one immutable [`ReaderSnapshot`] until it is
//! explicitly closed or dropped. Pins are process-local, bounded and reference
//! counted; there is no distributed registry, expiry or TTL. A PIT created
//! against a volatile refresh view does not survive a process restart.
//!
//! PIT ids are session-qualified to be unique **within one process lifetime**:
//! a process-global session sequence is combined with a per-session ordinal as
//! `pit-<16 lowercase hex session>-<16 lowercase hex ordinal>`. There is no
//! uniqueness guarantee after a process restart, and no randomness dependency.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use crate::contract::result::PitId;

use super::error::{IndexError, IndexResult};
use super::snapshot::ReaderSnapshot;

/// Process-global session sequence. Starts at 1 and never wraps.
static NEXT_SESSION: AtomicU64 = AtomicU64::new(1);

/// An index-wide bound on simultaneously pinned PIT handles.
#[derive(Debug)]
pub(crate) struct PinCounter {
    pinned: AtomicUsize,
    max: usize,
    session: u64,
    next: AtomicU64,
}

impl PinCounter {
    /// Create a counter with a fresh process-local session id.
    ///
    /// Returns [`IndexError::PitIdExhausted`] if the session id space is
    /// exhausted; it never wraps.
    // MSRV compatibility: retain fetch_update until the minimum supported Rust version supports its replacement.
    #[allow(deprecated)]
    pub(crate) fn new(max: u64) -> IndexResult<Arc<Self>> {
        let session = NEXT_SESSION
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| IndexError::PitIdExhausted)?;
        Ok(Arc::new(Self {
            pinned: AtomicUsize::new(0),
            max: usize::try_from(max).unwrap_or(usize::MAX),
            session,
            next: AtomicU64::new(1),
        }))
    }

    /// Reserve one pin, returning a fresh opaque id.
    ///
    /// Returns `Ok(None)` only when the capacity bound is reached. On ordinal
    /// exhaustion the reserved pin is rolled back exactly once and
    /// [`IndexError::PitIdExhausted`] is returned. The pin count and ordinal
    /// never wrap.
    // MSRV compatibility: retain fetch_update until the minimum supported Rust version supports its replacement.
    #[allow(deprecated)]
    pub(crate) fn try_pin(&self) -> IndexResult<Option<String>> {
        loop {
            let current = self.pinned.load(Ordering::Acquire);
            if current >= self.max {
                return Ok(None);
            }
            if self
                .pinned
                .compare_exchange_weak(current, current + 1, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                match self
                    .next
                    .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                        value.checked_add(1)
                    }) {
                    Ok(ordinal) => {
                        return Ok(Some(format!("pit-{:016x}-{:016x}", self.session, ordinal)));
                    }
                    Err(_) => {
                        self.release();
                        return Err(IndexError::PitIdExhausted);
                    }
                }
            }
        }
    }

    pub(crate) fn release(&self) {
        // A reservation is always made before `release` is called; the count
        // cannot underflow.
        self.pinned.fetch_sub(1, Ordering::AcqRel);
    }

    /// Current pinned count.
    #[must_use]
    pub(crate) fn pinned(&self) -> usize {
        self.pinned.load(Ordering::Acquire)
    }

    /// The configured maximum.
    #[must_use]
    pub(crate) const fn max(&self) -> usize {
        self.max
    }

    /// The process-local session id.
    #[cfg(test)]
    #[must_use]
    pub(crate) const fn session(&self) -> u64 {
        self.session
    }
}

/// A live pin on one immutable reader snapshot.
///
/// Dropping or [`PitHandle::close`] releases the pin. `PitHandle` is
/// deliberately not `Clone`: each pin is an explicit reservation.
pub struct PitHandle {
    id: PitId,
    snapshot: Arc<ReaderSnapshot>,
}

impl PitHandle {
    pub(crate) fn new(id: PitId, snapshot: Arc<ReaderSnapshot>) -> Self {
        Self { id, snapshot }
    }

    /// The opaque PIT identity.
    #[must_use]
    pub const fn id(&self) -> &PitId {
        &self.id
    }

    /// The pinned immutable snapshot.
    #[must_use]
    pub const fn snapshot(&self) -> &Arc<ReaderSnapshot> {
        &self.snapshot
    }

    /// Explicitly release the pin.
    pub fn close(self) {}
}

impl Drop for PitHandle {
    fn drop(&mut self) {
        self.snapshot.release_pin();
    }
}

impl std::fmt::Debug for PitHandle {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PitHandle").field("id", &self.id).finish()
    }
}

/// Pin `snapshot`, mapping capacity exhaustion to [`IndexError::PitLimitExceeded`].
pub(crate) fn pin(snapshot: &Arc<ReaderSnapshot>) -> IndexResult<PitHandle> {
    match snapshot.try_pin()? {
        Some(id) => {
            let id = PitId::new(id).expect("generated PIT id is nonempty");
            Ok(PitHandle::new(id, Arc::clone(snapshot)))
        }
        None => Err(IndexError::PitLimitExceeded {
            limit: snapshot.pin_limit(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pin_counter_bounds_and_releases() {
        let counter = PinCounter::new(2).unwrap();
        assert_eq!(counter.max(), 2);
        assert_eq!(counter.pinned(), 0);
        let first = counter.try_pin().unwrap().unwrap();
        let second = counter.try_pin().unwrap().unwrap();
        assert_ne!(first, second);
        assert!(first.starts_with("pit-"));
        assert_eq!(first.len(), 4 + 16 + 1 + 16);
        assert_eq!(counter.pinned(), 2);
        assert!(counter.try_pin().unwrap().is_none());
        counter.release();
        assert_eq!(counter.pinned(), 1);
        assert!(counter.try_pin().unwrap().is_some());
    }

    #[test]
    fn zero_bound_rejects_every_pin() {
        let counter = PinCounter::new(0).unwrap();
        assert!(counter.try_pin().unwrap().is_none());
    }

    // T12/T13: distinct sessions produce distinct id prefixes; format is exact.
    #[test]
    fn distinct_sessions_produce_distinct_qualified_ids() {
        let first = PinCounter::new(1).unwrap();
        let second = PinCounter::new(1).unwrap();
        assert_ne!(first.session(), second.session());
        let first_id = first.try_pin().unwrap().unwrap();
        let second_id = second.try_pin().unwrap().unwrap();
        assert_ne!(first_id, second_id);
        let expected_prefix = format!("pit-{:016x}-", first.session());
        assert!(first_id.starts_with(&expected_prefix));
    }

    // T15: ordinal exhaustion rolls back the reserved pin exactly once.
    #[test]
    fn pin_ordinal_exhaustion_does_not_leak() {
        let counter = PinCounter::new(2).unwrap();
        counter.next.store(u64::MAX - 1, Ordering::SeqCst);
        let first = counter.try_pin().unwrap().unwrap();
        assert!(first.ends_with(&format!("{:016x}", u64::MAX - 1)));
        let error = counter.try_pin().unwrap_err();
        assert!(matches!(error, IndexError::PitIdExhausted));
        // The second reservation was rolled back; only the first pin remains.
        assert_eq!(counter.pinned(), 1);
    }
}
