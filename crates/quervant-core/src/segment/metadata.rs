//! Accounted retained-metadata budget for verified immutable segment state.
//!
//! Two independent accounts govern a snapshot reader:
//!
//! 1. `index::snapshot::ReaderByteBudget` — the existing active-reader admission
//!    charge (encoded segment bytes per outstanding guard). It is unchanged and
//!    remains independent of this module.
//! 2. [`MetadataBudget`] — the accounted-retained-metadata account described by
//!    `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md` §13 G2. Its limit is
//!    exactly the `reader_copy_limit` constructor argument of `ReaderSnapshot`.
//!
//! *Accounted memory* here means the requested usable payload capacity of
//! additional retained metadata allocations (vector capacity and `String`
//! capacity). It is **not** an RSS bound: allocator headers, rounding and
//! fragmentation are excluded, and the already-resident encoded segment bytes
//! owned by the snapshot are never charged again.
//!
//! Every retained allocation is charged **before** it is allocated, fallibly
//! allocated with `try_reserve_exact`/equivalent, and reconciled against the
//! measured capacities of the finished candidate before publication. The final
//! [`MetadataReservation`] is owned by the immutable state itself, so it releases
//! on the last `Arc<VerifiedSegmentState>` drop instead of on slot or snapshot
//! drop.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use super::error::{SegmentError, SegmentResult};

/// A snapshot-shared budget for retained verified-segment metadata.
#[derive(Debug)]
pub(crate) struct MetadataBudget {
    used: AtomicU64,
    limit: u64,
}

impl MetadataBudget {
    /// Create an empty budget with an exact byte limit.
    pub(crate) fn new(limit: u64) -> Arc<Self> {
        Arc::new(Self {
            used: AtomicU64::new(0),
            limit,
        })
    }

    /// The configured capacity.
    pub(crate) const fn limit(&self) -> u64 {
        self.limit
    }

    /// Reserve `bytes` with checked arithmetic and a compare-and-swap loop.
    fn try_reserve(&self, bytes: u64) -> SegmentResult<()> {
        loop {
            let current = self.used.load(Ordering::Acquire);
            let projected = current
                .checked_add(bytes)
                .ok_or(SegmentError::LimitExceeded {
                    limit: self.limit,
                    requested: u64::MAX,
                })?;
            if projected > self.limit {
                return Err(SegmentError::LimitExceeded {
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

    /// Currently reserved retained-metadata bytes.
    #[cfg(test)]
    pub(crate) fn used(&self) -> u64 {
        self.used.load(Ordering::Acquire)
    }
}

/// RAII release of one retained-metadata reservation.
///
/// Owned by the immutable verified state so it survives snapshot drop for as
/// long as any guarded reader still references the state.
#[derive(Debug)]
pub(crate) struct MetadataReservation {
    budget: Arc<MetadataBudget>,
    bytes: u64,
}

impl Drop for MetadataReservation {
    fn drop(&mut self) {
        self.budget.release(self.bytes);
    }
}

/// A construction-time retained-metadata meter.
///
/// `reserved` is what the budget currently holds for this candidate;
/// `charged` is the audit total of per-allocation charges requested before each
/// allocation. On success the meter releases the unused allowance and returns a
/// [`MetadataReservation`] for the measured retained charge. On any failure or
/// unwind it releases the entire allowance.
#[derive(Debug)]
pub(crate) struct MetadataMeter {
    budget: Arc<MetadataBudget>,
    reserved: u64,
    charged: u64,
}

impl MetadataMeter {
    /// Reserve a candidate allowance from `budget`.
    pub(crate) fn reserve(budget: &Arc<MetadataBudget>, allowance: u64) -> SegmentResult<Self> {
        budget.try_reserve(allowance)?;
        Ok(Self {
            budget: Arc::clone(budget),
            reserved: allowance,
            charged: 0,
        })
    }

    /// Extend the candidate allowance once more of the encoded structure has
    /// been validated.
    pub(crate) fn extend(&mut self, extra: u64) -> SegmentResult<()> {
        self.budget.try_reserve(extra)?;
        self.reserved = self
            .reserved
            .checked_add(extra)
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
        Ok(())
    }

    /// Charge one retained allocation *before* performing it.
    pub(crate) fn charge(&mut self, bytes: u64) -> SegmentResult<()> {
        let next = self
            .charged
            .checked_add(bytes)
            .ok_or(SegmentError::LimitExceeded {
                limit: self.reserved,
                requested: u64::MAX,
            })?;
        if next > self.reserved {
            return Err(SegmentError::LimitExceeded {
                limit: self.reserved,
                requested: next,
            });
        }
        self.charged = next;
        Ok(())
    }

    /// Charge `count` elements of `T`.
    pub(crate) fn charge_vec<T>(&mut self, count: u64) -> SegmentResult<()> {
        let bytes = element_bytes::<T>(count)?;
        self.charge(bytes)
    }

    /// Charge an owned string payload.
    pub(crate) fn charge_str(&mut self, bytes: u64) -> SegmentResult<()> {
        self.charge(bytes)
    }

    /// Charge one separately allocated `Arc` payload.
    pub(crate) fn charge_arc<T>(&mut self) -> SegmentResult<()> {
        self.charge(std::mem::size_of::<T>() as u64)
    }

    /// Convert the candidate allowance into the final measured reservation.
    ///
    /// Fails closed when the measured retained charge exceeds the allowance; the
    /// caller then discards the candidate and uses the verified uncached path.
    pub(crate) fn finalize(mut self, measured: u64) -> SegmentResult<MetadataReservation> {
        if measured > self.reserved {
            return Err(SegmentError::LimitExceeded {
                limit: self.reserved,
                requested: measured,
            });
        }
        let surplus = self.reserved - measured;
        // Transfer ownership of the remaining charge to the reservation; the
        // meter must not release it again on drop.
        self.reserved = 0;
        self.budget.release(surplus);
        Ok(MetadataReservation {
            budget: Arc::clone(&self.budget),
            bytes: measured,
        })
    }
}

impl Drop for MetadataMeter {
    fn drop(&mut self) {
        if self.reserved > 0 {
            self.budget.release(self.reserved);
            self.reserved = 0;
        }
    }
}

/// `count * size_of::<T>()`, checked.
pub(crate) fn element_bytes<T>(count: u64) -> SegmentResult<u64> {
    count
        .checked_mul(std::mem::size_of::<T>() as u64)
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })
}

/// `capacity * size_of::<T>()` for an already allocated container, checked.
pub(crate) fn capacity_bytes<T>(capacity: usize) -> SegmentResult<u64> {
    let count = u64::try_from(capacity).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    element_bytes::<T>(count)
}

/// Checked accumulation for measured charges.
pub(crate) fn accumulate(total: u64, addend: u64) -> SegmentResult<u64> {
    total
        .checked_add(addend)
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })
}

/// A conservative element-count bound derived from encoded section bytes.
///
/// `min_bytes_per_item` must be the document format's proven minimum encoded
/// width for one item; the result is a sound upper bound on the item count in a
/// structurally validated section body.
pub(crate) fn count_bound(section_len: u64, min_bytes_per_item: u64) -> u64 {
    debug_assert!(min_bytes_per_item > 0);
    section_len / min_bytes_per_item.max(1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn budget_reserve_exact_and_one_over() {
        let budget = MetadataBudget::new(100);
        let meter = MetadataMeter::reserve(&budget, 100).unwrap();
        assert_eq!(budget.used(), 100);
        assert!(matches!(
            MetadataMeter::reserve(&budget, 1),
            Err(SegmentError::LimitExceeded { .. })
        ));
        assert_eq!(budget.used(), 100);
        drop(meter);
        assert_eq!(budget.used(), 0);
        MetadataMeter::reserve(&budget, 100).unwrap();
    }

    #[test]
    fn budget_overflow_fails_closed() {
        let budget = MetadataBudget::new(u64::MAX);
        let _meter = MetadataMeter::reserve(&budget, u64::MAX).unwrap();
        assert!(matches!(
            MetadataMeter::reserve(&budget, 1),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn charge_beyond_allowance_fails_without_leaking() {
        let budget = MetadataBudget::new(1_000);
        let mut meter = MetadataMeter::reserve(&budget, 10).unwrap();
        meter.charge(10).unwrap();
        assert!(matches!(
            meter.charge(1),
            Err(SegmentError::LimitExceeded {
                limit: 10,
                requested: 11
            })
        ));
        drop(meter);
        assert_eq!(budget.used(), 0);
    }

    #[test]
    fn charge_overflow_is_typed() {
        let budget = MetadataBudget::new(u64::MAX);
        let mut meter = MetadataMeter::reserve(&budget, 10).unwrap();
        meter.charge(10).unwrap();
        assert!(matches!(
            meter.charge(u64::MAX),
            Err(SegmentError::LimitExceeded { .. })
        ));
        assert!(matches!(
            meter.charge_vec::<u64>(u64::MAX),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn finalize_releases_unused_allowance() {
        let budget = MetadataBudget::new(1_000);
        let mut meter = MetadataMeter::reserve(&budget, 400).unwrap();
        meter.charge(120).unwrap();
        let reservation = meter.finalize(120).unwrap();
        assert_eq!(budget.used(), 120);
        drop(reservation);
        assert_eq!(budget.used(), 0);
    }

    #[test]
    fn finalize_rejects_measured_over_allowance_and_releases_all() {
        let budget = MetadataBudget::new(1_000);
        let meter = MetadataMeter::reserve(&budget, 10).unwrap();
        assert!(matches!(
            meter.finalize(11),
            Err(SegmentError::LimitExceeded {
                limit: 10,
                requested: 11
            })
        ));
        assert_eq!(budget.used(), 0);
    }

    #[test]
    fn extend_accumulates_and_releases() {
        let budget = MetadataBudget::new(1_000);
        let mut meter = MetadataMeter::reserve(&budget, 100).unwrap();
        meter.extend(150).unwrap();
        assert_eq!(budget.used(), 250);
        meter.charge(250).unwrap();
        let reservation = meter.finalize(250).unwrap();
        assert_eq!(budget.used(), 250);
        drop(reservation);
        assert_eq!(budget.used(), 0);
    }

    #[test]
    fn element_and_capacity_helpers_are_checked() {
        assert_eq!(element_bytes::<u64>(4).unwrap(), 32);
        assert!(element_bytes::<u64>(u64::MAX).is_err());
        assert_eq!(capacity_bytes::<u64>(2).unwrap(), 16);
        assert_eq!(accumulate(2, 3).unwrap(), 5);
        assert!(accumulate(u64::MAX, 1).is_err());
        assert_eq!(count_bound(100, 10), 10);
        assert_eq!(count_bound(9, 10), 0);
    }

    #[test]
    fn charge_helpers_cover_arc_and_strings() {
        let budget = MetadataBudget::new(1_000);
        let mut meter = MetadataMeter::reserve(&budget, 1_000).unwrap();
        meter.charge_arc::<MetadataBudget>().unwrap();
        meter.charge_str(7).unwrap();
        let measured = std::mem::size_of::<MetadataBudget>() as u64 + 7;
        let reservation = meter.finalize(measured).unwrap();
        assert_eq!(budget.used(), measured);
        drop(reservation);
        assert_eq!(budget.used(), 0);
    }
}
