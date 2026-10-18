//! Cumulative batch-wide resource accounting (PR 14 P2).
//!
//! One [`BatchExecutionMeter`] is owned by `execute_batch` for the whole serial
//! run. It tracks:
//! - `BatchAggregate`: actual work units charged at the existing lexical/typed
//!   charge sites (never hit counts);
//! - `BatchMemoryBytes`: peak simultaneously retained logical bytes;
//! - `BatchResponseBytes`: cumulative successful response payload bytes.
//!
//! Every addition uses checked arithmetic. A rejected preflight leaves all
//! counters unchanged. Batch-origin exhaustion is reported as a tagged
//! [`BatchMeterError`] so the caller can map it to the exact `BudgetKind`
//! without mislabelling query-local limits.

use crate::contract::budget::BudgetKind;

use super::error::{SearchError, SearchResult};

/// An internal batch-origin resource failure with an exact budget kind.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct BatchMeterError {
    pub(crate) kind: BudgetKind,
    pub(crate) limit: u64,
    pub(crate) requested: u64,
}

impl BatchMeterError {
    /// Translate to the public typed budget error at the slot boundary.
    pub(crate) fn to_search_error(self) -> SearchError {
        SearchError::Query(crate::contract::error::QueryError::BudgetExceeded { kind: self.kind })
    }
}

/// The single cumulative meter for one accepted batch.
pub(crate) struct BatchExecutionMeter {
    work_limit: u64,
    work_used: u64,
    memory_limit: u64,
    memory_current: u64,
    memory_peak: u64,
    response_limit: u64,
    response_used: u64,
}

impl BatchExecutionMeter {
    pub(crate) fn new(work_limit: u64, memory_limit: u64, response_limit: u64) -> Self {
        Self {
            work_limit,
            work_used: 0,
            memory_limit,
            memory_current: 0,
            memory_peak: 0,
            response_limit,
            response_used: 0,
        }
    }

    /// Validate a work charge against the batch ceiling without committing.
    pub(crate) fn preflight_work(&self, units: u64) -> Result<(), BatchMeterError> {
        let projected = self.work_used.checked_add(units).ok_or(BatchMeterError {
            kind: BudgetKind::BatchAggregate,
            limit: self.work_limit,
            requested: u64::MAX,
        })?;
        if projected > self.work_limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchAggregate,
                limit: self.work_limit,
                requested: projected,
            });
        }
        Ok(())
    }

    /// Commit a previously preflighted work charge.
    pub(crate) fn commit_work(&mut self, units: u64) -> Result<(), BatchMeterError> {
        let projected = self.work_used.checked_add(units).ok_or(BatchMeterError {
            kind: BudgetKind::BatchAggregate,
            limit: self.work_limit,
            requested: u64::MAX,
        })?;
        if projected > self.work_limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchAggregate,
                limit: self.work_limit,
                requested: projected,
            });
        }
        self.work_used = projected;
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn charge_work(&mut self, units: u64) -> Result<(), BatchMeterError> {
        self.preflight_work(units)?;
        self.commit_work(units)
    }

    /// Reserve simultaneously retained logical memory.
    pub(crate) fn reserve_memory(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        let projected = self
            .memory_current
            .checked_add(bytes)
            .ok_or(BatchMeterError {
                kind: BudgetKind::BatchMemoryBytes,
                limit: self.memory_limit,
                requested: u64::MAX,
            })?;
        if projected > self.memory_limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchMemoryBytes,
                limit: self.memory_limit,
                requested: projected,
            });
        }
        self.memory_current = projected;
        self.memory_peak = self.memory_peak.max(projected);
        Ok(())
    }

    /// Release retained logical memory. Underflow is an internal invariant
    /// violation, reported rather than silently ignored.
    pub(crate) fn release_memory(&mut self, bytes: u64) -> SearchResult<()> {
        self.memory_current =
            self.memory_current
                .checked_sub(bytes)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "batch memory ledger underflow".to_owned(),
                })?;
        Ok(())
    }

    /// Charge one successful slot's response payload bytes.
    pub(crate) fn charge_response(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        let projected = self
            .response_used
            .checked_add(bytes)
            .ok_or(BatchMeterError {
                kind: BudgetKind::BatchResponseBytes,
                limit: self.response_limit,
                requested: u64::MAX,
            })?;
        if projected > self.response_limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchResponseBytes,
                limit: self.response_limit,
                requested: projected,
            });
        }
        self.response_used = projected;
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn work_used(&self) -> u64 {
        self.work_used
    }

    #[cfg(test)]
    pub(crate) fn memory_current(&self) -> u64 {
        self.memory_current
    }

    #[cfg(test)]
    pub(crate) fn memory_peak(&self) -> u64 {
        self.memory_peak
    }

    #[cfg(test)]
    pub(crate) fn response_used(&self) -> u64 {
        self.response_used
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn work_exact_limit_then_one_over_is_atomic() {
        let mut meter = BatchExecutionMeter::new(10, 100, 100);
        meter.charge_work(10).unwrap();
        assert_eq!(meter.work_used(), 10);
        assert!(matches!(
            meter.charge_work(1),
            Err(BatchMeterError {
                kind: BudgetKind::BatchAggregate,
                limit: 10,
                requested: 11
            })
        ));
        assert_eq!(meter.work_used(), 10);
    }

    #[test]
    fn response_exact_limit_then_one_over_is_atomic() {
        let mut meter = BatchExecutionMeter::new(100, 100, 10);
        meter.charge_response(10).unwrap();
        assert!(meter.charge_response(1).is_err());
        assert_eq!(meter.response_used(), 10);
    }

    #[test]
    fn memory_peak_tracks_simultaneous_reservations() {
        let mut meter = BatchExecutionMeter::new(100, 20, 100);
        meter.reserve_memory(12).unwrap();
        meter.reserve_memory(8).unwrap();
        assert_eq!(meter.memory_current(), 20);
        assert_eq!(meter.memory_peak(), 20);
        assert!(meter.reserve_memory(1).is_err());
        assert_eq!(meter.memory_current(), 20);
        meter.release_memory(20).unwrap();
        assert_eq!(meter.memory_current(), 0);
        assert_eq!(meter.memory_peak(), 20);
    }

    #[test]
    fn overflow_is_typed_not_wrapped() {
        let mut meter = BatchExecutionMeter::new(u64::MAX, u64::MAX, u64::MAX);
        meter.charge_work(u64::MAX).unwrap();
        assert!(matches!(
            meter.charge_work(1),
            Err(BatchMeterError {
                requested: u64::MAX,
                ..
            })
        ));
        assert_eq!(meter.work_used(), u64::MAX);
    }
}
