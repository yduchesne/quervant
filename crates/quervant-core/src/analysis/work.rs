//! Deterministic work accounting and cancellation polling (V4).

use super::cancellation::Cancellation;
use super::error::AnalysisError;
use super::limits::CANCELLATION_POLL_INTERVAL;

/// A checked, deterministic work budget shared by tokenization and filtering.
pub(crate) struct WorkBudget<'a> {
    limit: u64,
    consumed: u64,
    next_poll: u64,
    cancellation: &'a dyn Cancellation,
}

impl<'a> WorkBudget<'a> {
    pub(crate) fn new(limit: u64, cancellation: &'a dyn Cancellation) -> Self {
        Self {
            limit,
            consumed: 0,
            next_poll: CANCELLATION_POLL_INTERVAL,
            cancellation,
        }
    }

    /// Charges `units`, enforcing the budget and polling cancellation at fixed boundaries.
    pub(crate) fn charge(&mut self, units: u64) -> Result<(), AnalysisError> {
        self.consumed = self
            .consumed
            .checked_add(units)
            .ok_or(AnalysisError::WorkBudgetExceeded { limit: self.limit })?;
        if self.consumed > self.limit {
            return Err(AnalysisError::WorkBudgetExceeded { limit: self.limit });
        }
        if self.consumed >= self.next_poll {
            // Advance deterministically past the current point; polling interval is fixed.
            self.next_poll = self.consumed.saturating_add(CANCELLATION_POLL_INTERVAL);
            self.check_cancelled()?;
        }
        Ok(())
    }

    /// Polls cancellation explicitly (used at value boundaries and before work).
    pub(crate) fn check_cancelled(&self) -> Result<(), AnalysisError> {
        if self.cancellation.is_cancelled() {
            return Err(AnalysisError::Cancelled);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::cancellation::{Cancellation, NeverCancel};
    use std::cell::Cell;

    struct CancelAfterChecks {
        remaining: Cell<u32>,
    }

    impl Cancellation for CancelAfterChecks {
        fn is_cancelled(&self) -> bool {
            let left = self.remaining.get();
            if left == 0 {
                true
            } else {
                self.remaining.set(left - 1);
                false
            }
        }
    }

    #[test]
    fn charges_and_enforces_limit() {
        let mut budget = WorkBudget::new(10, &NeverCancel);
        budget.charge(10).expect("exact limit succeeds");
        assert!(budget.charge(1).is_err());
    }

    #[test]
    fn overflow_is_checked() {
        let mut budget = WorkBudget::new(u64::MAX, &NeverCancel);
        assert!(budget.charge(u64::MAX).is_ok());
        assert!(budget.charge(1).is_err());
    }

    #[test]
    fn polls_cancellation_at_boundaries() {
        let canceller = CancelAfterChecks {
            remaining: Cell::new(0),
        };
        let mut budget = WorkBudget::new(1_000_000, &canceller);
        // The first poll happens when consuming crosses the poll interval.
        let result = budget.charge(CANCELLATION_POLL_INTERVAL);
        assert!(matches!(result, Err(AnalysisError::Cancelled)));
    }

    #[test]
    fn explicit_check_polls_cancellation() {
        let canceller = CancelAfterChecks {
            remaining: Cell::new(2),
        };
        let budget = WorkBudget::new(10, &canceller);
        assert!(budget.check_cancelled().is_ok());
        assert!(budget.check_cancelled().is_ok());
        assert!(budget.check_cancelled().is_err());
    }
}
