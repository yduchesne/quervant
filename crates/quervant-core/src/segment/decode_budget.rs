//! A shared, deterministic modeled retained-byte budget for one logical decode.
//!
//! This centralizes the preallocation accounting used by the dictionary, schema,
//! stored/recursive-JSON and remap decoders. It models retained bytes
//! conservatively; it is **not** a hard allocator, RSS, or whole-process memory
//! bound. Each logical decoding operation owns one budget, passed mutably to
//! nested operations, so sibling records/children cannot accidentally reset it.

use super::error::{SegmentError, SegmentResult};
use super::limits::SegmentLimits;

/// A cumulative modeled retained-byte budget.
pub(crate) struct DecodeBudget<'a> {
    limits: &'a SegmentLimits,
    retained: u64,
}

impl<'a> DecodeBudget<'a> {
    /// Create an empty budget for one logical decode.
    pub(crate) const fn new(limits: &'a SegmentLimits) -> Self {
        Self {
            limits,
            retained: 0,
        }
    }

    /// Bytes reserved so far.
    ///
    /// Diagnostic/verification accessor; used by unit tests and available to
    /// future cross-checks.
    #[allow(dead_code)]
    pub(crate) const fn retained(&self) -> u64 {
        self.retained
    }

    /// Reserve `charge` bytes against the cumulative budget.
    ///
    /// On failure the budget is left unchanged and a typed error is returned.
    pub(crate) fn reserve_bytes(&mut self, charge: u64) -> SegmentResult<()> {
        let candidate = self
            .retained
            .checked_add(charge)
            .ok_or(SegmentError::LimitExceeded {
                limit: self.limits.max_section_decode_bytes(),
                requested: u64::MAX,
            })?;
        self.limits.check_decoded_bytes(candidate)?;
        self.retained = candidate;
        Ok(())
    }

    /// Reserve the backing of a `Vec<T>` with `count` elements.
    ///
    /// Applies the per-allocation ceiling and the cumulative budget; on failure
    /// the budget is unchanged.
    pub(crate) fn reserve_vec<T>(&mut self, count: u64) -> SegmentResult<()> {
        let bytes = count.checked_mul(std::mem::size_of::<T>() as u64).ok_or(
            SegmentError::LimitExceeded {
                limit: self.limits.max_section_decode_bytes(),
                requested: u64::MAX,
            },
        )?;
        self.limits.check_alloc::<T>(count)?;
        self.reserve_bytes(bytes)
    }

    /// Reserve an owned string payload of `bytes` bytes.
    ///
    /// Applies the per-allocation ceiling and the cumulative budget; on failure
    /// the budget is unchanged.
    pub(crate) fn reserve_string(&mut self, bytes: u64) -> SegmentResult<()> {
        self.limits.check_allocation_bytes(bytes)?;
        self.reserve_bytes(bytes)
    }

    /// Reserve one `BTreeMap<K, V>` entry conservatively.
    ///
    /// Charges the inline `(K, V)` struct plus an estimated node overhead of
    /// three `usize` words. This is a documented model, not allocator telemetry.
    pub(crate) fn reserve_btree_entry<K, V>(&mut self) -> SegmentResult<()> {
        let charge = (std::mem::size_of::<(K, V)>() as u64)
            .checked_add(3 * std::mem::size_of::<usize>() as u64)
            .ok_or(SegmentError::LimitExceeded {
                limit: self.limits.max_section_decode_bytes(),
                requested: u64::MAX,
            })?;
        self.reserve_bytes(charge)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failed_reservation_leaves_budget_unchanged() {
        let limits = SegmentLimits::default().with_max_section_decode_bytes(100);
        let mut budget = DecodeBudget::new(&limits);
        budget.reserve_bytes(40).unwrap();
        assert_eq!(budget.retained(), 40);
        // One byte over the cumulative ceiling fails without mutating.
        assert!(matches!(
            budget.reserve_bytes(61),
            Err(SegmentError::LimitExceeded { .. })
        ));
        assert_eq!(budget.retained(), 40);
        // Exact budget succeeds.
        budget.reserve_bytes(60).unwrap();
        assert_eq!(budget.retained(), 100);
    }

    #[test]
    fn vector_cumulative_and_single_allocation_limits() {
        let limits = SegmentLimits::default()
            .with_max_section_decode_bytes(64)
            .with_max_single_allocation(16);
        let mut budget = DecodeBudget::new(&limits);
        // 4 * 8 = 32 bytes exceeds the 16-byte single-allocation cap.
        assert!(matches!(
            budget.reserve_vec::<u64>(4),
            Err(SegmentError::LimitExceeded { .. })
        ));
        assert_eq!(budget.retained(), 0);
        // 2 * 8 = 16 fits the single cap and cumulative budget.
        budget.reserve_vec::<u64>(2).unwrap();
        assert_eq!(budget.retained(), 16);
        // A second 2-element vector exceeds the 64-byte cumulative budget only
        // after 8 total elements (8*8=64).
        budget.reserve_vec::<u64>(2).unwrap();
        budget.reserve_vec::<u64>(2).unwrap();
        assert_eq!(budget.retained(), 48);
        // The fourth vector reaches exactly the 64-byte cumulative limit.
        budget.reserve_vec::<u64>(2).unwrap();
        assert_eq!(budget.retained(), 64);
        // A fifth would exceed the cumulative budget.
        assert!(matches!(
            budget.reserve_vec::<u64>(2),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn vector_multiplication_overflow_is_typed() {
        let limits = SegmentLimits::default();
        let mut budget = DecodeBudget::new(&limits);
        assert!(matches!(
            budget.reserve_vec::<u64>(u64::MAX),
            Err(SegmentError::LimitExceeded { .. })
        ));
        assert_eq!(budget.retained(), 0);
    }

    #[test]
    fn byte_addition_overflow_is_typed_and_unchanged() {
        let limits = SegmentLimits::default();
        let mut budget = DecodeBudget::new(&limits);
        budget.reserve_bytes(5).unwrap();
        assert!(matches!(
            budget.reserve_bytes(u64::MAX),
            Err(SegmentError::LimitExceeded {
                requested: u64::MAX,
                ..
            })
        ));
        assert_eq!(budget.retained(), 5);
    }

    #[test]
    fn string_and_btree_entry_charges() {
        let limits = SegmentLimits::default();
        let mut budget = DecodeBudget::new(&limits);
        budget.reserve_string(10).unwrap();
        assert_eq!(budget.retained(), 10);
        budget.reserve_btree_entry::<u32, u32>().unwrap();
        assert_eq!(
            budget.retained(),
            10 + std::mem::size_of::<(u32, u32)>() as u64 + 3 * std::mem::size_of::<usize>() as u64
        );
        // A string allocation above the single-allocation ceiling fails without
        // mutating the cumulative budget.
        let tight = SegmentLimits::default().with_max_single_allocation(4);
        let mut budget = DecodeBudget::new(&tight);
        budget.reserve_bytes(1).unwrap();
        assert!(matches!(
            budget.reserve_string(5),
            Err(SegmentError::LimitExceeded { .. })
        ));
        assert_eq!(budget.retained(), 1);
    }
}
