//! Slot-scoped logical-memory reservations (PR 14 P2B, Phase B).
//!
//! A [`SlotMemoryScope`] owns a short-lived mutable borrow of the batch memory
//! sub-meter and tracks the temporary logical bytes currently retained by one
//! batch slot. Reservations are admitted with a checked preflight + commit and
//! released exactly once, on success (`finish_success`), failure
//! (`finish_failure`) or the non-panicking `Drop` fallback.
//!
//! This module is intentionally not wired into query execution yet; Phase C/E
//! bind `CandidateBudget` and `ProjectionLedger` to [`MemoryCharge`].

use super::batch_meter::{BatchMemoryMeter, BatchMeterError};
use super::error::{SearchError, SearchResult};

/// A narrow, synchronous reservation sink over logical bytes.
pub(crate) trait MemoryCharge {
    fn preflight(&self, bytes: u64) -> Result<(), BatchMeterError>;
    fn commit(&mut self, bytes: u64) -> Result<(), BatchMeterError>;
    /// Validate that `bytes` may be released from this owner without mutating
    /// either the scope or the meter. Used so a release can be preflighted before
    /// any ledger mutation.
    fn preflight_release(&self, bytes: u64) -> SearchResult<()>;
    fn release(&mut self, bytes: u64) -> SearchResult<()>;
}

/// Temporary reservations owned by one batch slot.
pub(crate) struct SlotMemoryScope<'m> {
    meter: &'m mut BatchMemoryMeter,
    temporary_bytes: u64,
    finished: bool,
}

impl<'m> SlotMemoryScope<'m> {
    pub(crate) fn new(meter: &'m mut BatchMemoryMeter) -> Self {
        Self {
            meter,
            temporary_bytes: 0,
            finished: false,
        }
    }

    #[must_use]
    pub(crate) fn temporary_bytes(&self) -> u64 {
        self.temporary_bytes
    }

    /// Reserve `bytes` against both the meter ceiling and the scope tracker.
    pub(crate) fn reserve(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        self.preflight(bytes)?;
        self.commit(bytes)
    }

    /// Release `bytes` previously reserved in this scope.
    pub(crate) fn release(&mut self, bytes: u64) -> SearchResult<()> {
        self.preflight_release(bytes)?;
        self.temporary_bytes -= bytes;
        self.meter.release_memory(bytes)
    }

    /// Validate a release without mutating scope or meter.
    pub(crate) fn preflight_release(&self, bytes: u64) -> SearchResult<()> {
        if bytes > self.temporary_bytes {
            return Err(SearchError::CorruptIndex {
                detail: "slot memory scope release exceeds its reservation".to_owned(),
            });
        }
        Ok(())
    }

    /// Release every temporary reservation (failed/cancelled slot).
    pub(crate) fn finish_failure(&mut self) -> SearchResult<()> {
        let bytes = self.temporary_bytes;
        self.temporary_bytes = 0;
        self.finished = true;
        self.meter.release_memory(bytes)
    }

    /// Transfer `retained_bytes` to the retained/response owner and release the
    /// rest of the slot's temporary reservations.
    pub(crate) fn finish_success(&mut self, retained_bytes: u64) -> SearchResult<()> {
        if retained_bytes > self.temporary_bytes {
            return Err(SearchError::CorruptIndex {
                detail: "retained bytes exceed the slot's temporary reservation".to_owned(),
            });
        }
        let release = self.temporary_bytes - retained_bytes;
        self.temporary_bytes = 0;
        self.finished = true;
        self.meter.release_memory(release)
    }

    fn checked_temporary_add(&self, bytes: u64) -> Result<u64, BatchMeterError> {
        self.temporary_bytes
            .checked_add(bytes)
            .ok_or(BatchMeterError {
                kind: crate::contract::budget::BudgetKind::BatchMemoryBytes,
                limit: self.temporary_bytes,
                requested: u64::MAX,
            })
    }
}

impl MemoryCharge for SlotMemoryScope<'_> {
    fn preflight(&self, bytes: u64) -> Result<(), BatchMeterError> {
        self.meter.preflight_reserve(bytes)?;
        self.checked_temporary_add(bytes)?;
        Ok(())
    }

    fn commit(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        // Preflight is a caller contract; re-check to keep the scope safe if a
        // caller commits directly.
        self.meter.commit_reserve(bytes)?;
        self.temporary_bytes += bytes;
        Ok(())
    }

    fn preflight_release(&self, bytes: u64) -> SearchResult<()> {
        // The scope is the sole owner of its temporary bytes, and the meter's
        // current total is always at least `temporary_bytes`; validating the
        // scope balance therefore also guarantees the meter release will not
        // underflow.
        if bytes > self.temporary_bytes {
            return Err(SearchError::CorruptIndex {
                detail: "slot memory scope release exceeds its reservation".to_owned(),
            });
        }
        Ok(())
    }

    fn release(&mut self, bytes: u64) -> SearchResult<()> {
        self.preflight_release(bytes)?;
        self.temporary_bytes -= bytes;
        self.meter.release_memory(bytes)
    }
}

impl Drop for SlotMemoryScope<'_> {
    fn drop(&mut self) {
        if self.finished || self.temporary_bytes == 0 {
            return;
        }
        let bytes = self.temporary_bytes;
        self.temporary_bytes = 0;
        if self.meter.release_memory(bytes).is_err() {
            // Drop cannot return an error; surface the invariant breach in tests
            // without panicking while unwinding.
            debug_assert!(false, "slot memory scope drop underflow");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn meter(limit: u64) -> BatchMemoryMeter {
        BatchMemoryMeter::new(limit)
    }

    #[test]
    fn b01_exact_limit_and_one_over() {
        let mut meter = meter(10);
        let mut scope = SlotMemoryScope::new(&mut meter);
        scope.reserve(10).unwrap();
        assert_eq!(scope.temporary_bytes(), 10);
        assert!(scope.reserve(1).is_err());
        assert_eq!(scope.temporary_bytes(), 10);
    }

    #[test]
    fn b02_overflow_is_atomic() {
        let mut meter = meter(u64::MAX);
        let mut scope = SlotMemoryScope::new(&mut meter);
        scope.reserve(u64::MAX).unwrap();
        assert!(scope.reserve(1).is_err());
        assert_eq!(scope.temporary_bytes(), u64::MAX);
    }

    #[test]
    fn b03_underflow_does_not_mutate() {
        let mut meter = meter(100);
        let mut scope = SlotMemoryScope::new(&mut meter);
        scope.reserve(10).unwrap();
        assert!(scope.release(11).is_err());
        assert_eq!(scope.temporary_bytes(), 10);
    }

    #[test]
    fn b04_explicit_failure_cleanup() {
        let mut meter = meter(100);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(10).unwrap();
            scope.finish_failure().unwrap();
            assert_eq!(scope.temporary_bytes(), 0);
        }
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn b05_drop_cleanup() {
        let mut meter = meter(100);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(10).unwrap();
        }
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn b06_cancellation_cleanup() {
        let mut meter = meter(100);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(10).unwrap();
            scope.finish_failure().unwrap();
        }
        assert_eq!(meter.current(), 0);
        assert_eq!(meter.peak(), 10);
    }

    #[test]
    fn b07_successful_retained_transfer() {
        let mut meter = meter(100);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(10).unwrap();
            scope.finish_success(4).unwrap();
            assert_eq!(scope.temporary_bytes(), 0);
        }
        assert_eq!(meter.current(), 4);
    }

    #[test]
    fn b08_retained_exceeds_temporary_rejected() {
        let mut meter = meter(100);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(10).unwrap();
            assert!(scope.finish_success(11).is_err());
            assert_eq!(scope.temporary_bytes(), 10);
            scope.finish_failure().unwrap();
        }
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn b09_peak_across_scopes_with_retained() {
        let mut meter = meter(12);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(5).unwrap();
            scope.finish_success(5).unwrap();
        }
        assert_eq!(meter.current(), 5);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(7).unwrap();
            scope.finish_failure().unwrap();
        }
        assert_eq!(meter.current(), 5);
        assert_eq!(meter.peak(), 12);
    }

    #[test]
    fn b10_zero_byte_reserve_release() {
        let mut meter = meter(10);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(0).unwrap();
            scope.release(0).unwrap();
            assert_eq!(scope.temporary_bytes(), 0);
        }
        assert_eq!(meter.current(), 0);
    }
    #[test]
    fn c2_memory_preflight_release_balances() {
        let mut meter = meter(100);
        {
            let mut scope = SlotMemoryScope::new(&mut meter);
            scope.reserve(10).unwrap();
            assert!(MemoryCharge::preflight_release(&scope, 10).is_ok());
            assert!(MemoryCharge::preflight_release(&scope, 11).is_err());
            assert_eq!(scope.temporary_bytes(), 10);
        }
        assert_eq!(meter.current(), 0);
    }
}
