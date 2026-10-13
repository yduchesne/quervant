//! Process-local pinned point-in-time handles (PR 6).
//!
//! A `PitHandle` pins exactly one immutable [`ReaderSnapshot`] until it is
//! explicitly closed or dropped. Pins are process-local, bounded and reference
//! counted; there is no distributed registry, expiry or TTL. A PIT created
//! against a volatile refresh view does not survive a process restart.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use crate::contract::result::PitId;

use super::error::IndexResult;
use super::snapshot::ReaderSnapshot;

/// An index-wide bound on simultaneously pinned PIT handles.
#[derive(Debug)]
pub(crate) struct PinCounter {
    pinned: AtomicUsize,
    max: usize,
    next: AtomicU64,
}

impl PinCounter {
    pub(crate) fn new(max: u64) -> Arc<Self> {
        Arc::new(Self {
            pinned: AtomicUsize::new(0),
            max: usize::try_from(max).unwrap_or(usize::MAX),
            next: AtomicU64::new(1),
        })
    }

    /// Reserve one pin, returning a fresh opaque id, or `None` at the bound.
    pub(crate) fn try_pin(&self) -> Option<String> {
        loop {
            let current = self.pinned.load(Ordering::Acquire);
            if current >= self.max {
                return None;
            }
            if self
                .pinned
                .compare_exchange_weak(current, current + 1, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                let ordinal = self.next.fetch_add(1, Ordering::Relaxed);
                return Some(format!("pit-{ordinal}"));
            }
        }
    }

    pub(crate) fn release(&self) {
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

/// Pin `snapshot`, or fail with [`IndexError::PitLimitExceeded`].
pub(crate) fn pin(snapshot: &Arc<ReaderSnapshot>) -> IndexResult<PitHandle> {
    match snapshot.try_pin() {
        Some(id) => {
            let id = PitId::new(id).expect("generated PIT id is nonempty");
            Ok(PitHandle::new(id, Arc::clone(snapshot)))
        }
        None => Err(super::error::IndexError::PitLimitExceeded {
            limit: snapshot.pin_limit(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pin_counter_bounds_and_releases() {
        let counter = PinCounter::new(2);
        assert_eq!(counter.max(), 2);
        assert_eq!(counter.pinned(), 0);
        let first = counter.try_pin().unwrap();
        let second = counter.try_pin().unwrap();
        assert_ne!(first, second);
        assert_eq!(counter.pinned(), 2);
        assert!(counter.try_pin().is_none());
        counter.release();
        assert_eq!(counter.pinned(), 1);
        assert!(counter.try_pin().is_some());
    }

    #[test]
    fn zero_bound_rejects_every_pin() {
        let counter = PinCounter::new(0);
        assert!(counter.try_pin().is_none());
    }
}
