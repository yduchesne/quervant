//! Cumulative batch-wide resource accounting (PR 14 P2).
//!
//! One [`BatchExecutionMeter`] is owned by `execute_batch` for the whole serial
//! run. It holds three **disjoint** sub-meters so a slot can borrow work and
//! memory concurrently without interior mutability:
//! - [`BatchWorkMeter`]: cumulative actual work units (`BatchAggregate`);
//! - [`BatchMemoryMeter`]: current/peak simultaneously retained logical bytes;
//! - [`BatchResponseMeter`]: cumulative successful response payload bytes.
//!
//! Every addition/subtraction is checked; a rejected preflight leaves the
//! counter unchanged. Batch-origin exhaustion is tagged with an exact
//! [`BudgetKind`].

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
    pub(crate) fn to_search_error(self) -> SearchError {
        SearchError::Query(crate::contract::error::QueryError::BudgetExceeded { kind: self.kind })
    }
}

/// The single cumulative meter for one accepted batch.
pub(crate) struct BatchExecutionMeter {
    pub(crate) work: BatchWorkMeter,
    pub(crate) memory: BatchMemoryMeter,
    pub(crate) response: BatchResponseMeter,
}

impl BatchExecutionMeter {
    pub(crate) fn new(work_limit: u64, memory_limit: u64, response_limit: u64) -> Self {
        Self {
            work: BatchWorkMeter::new(work_limit),
            memory: BatchMemoryMeter::new(memory_limit),
            response: BatchResponseMeter::new(response_limit),
        }
    }
}

/// Cumulative actual work units (never hit counts).
pub(crate) struct BatchWorkMeter {
    limit: u64,
    used: u64,
}

impl BatchWorkMeter {
    pub(crate) fn new(limit: u64) -> Self {
        Self { limit, used: 0 }
    }

    pub(crate) fn preflight_work(&self, units: u64) -> Result<(), BatchMeterError> {
        let projected = self.used.checked_add(units).ok_or(BatchMeterError {
            kind: BudgetKind::BatchAggregate,
            limit: self.limit,
            requested: u64::MAX,
        })?;
        if projected > self.limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchAggregate,
                limit: self.limit,
                requested: projected,
            });
        }
        Ok(())
    }

    pub(crate) fn commit_work(&mut self, units: u64) -> Result<(), BatchMeterError> {
        let projected = self.used.checked_add(units).ok_or(BatchMeterError {
            kind: BudgetKind::BatchAggregate,
            limit: self.limit,
            requested: u64::MAX,
        })?;
        if projected > self.limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchAggregate,
                limit: self.limit,
                requested: projected,
            });
        }
        self.used = projected;
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn used(&self) -> u64 {
        self.used
    }
}

/// Simultaneously retained logical bytes (current and peak).
pub(crate) struct BatchMemoryMeter {
    limit: u64,
    current: u64,
    peak: u64,
}

impl BatchMemoryMeter {
    pub(crate) fn new(limit: u64) -> Self {
        Self {
            limit,
            current: 0,
            peak: 0,
        }
    }

    pub(crate) fn preflight_reserve(&self, bytes: u64) -> Result<(), BatchMeterError> {
        let projected = self.current.checked_add(bytes).ok_or(BatchMeterError {
            kind: BudgetKind::BatchMemoryBytes,
            limit: self.limit,
            requested: u64::MAX,
        })?;
        if projected > self.limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchMemoryBytes,
                limit: self.limit,
                requested: projected,
            });
        }
        Ok(())
    }

    pub(crate) fn commit_reserve(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        self.preflight_reserve(bytes)?;
        self.current += bytes;
        self.peak = self.peak.max(self.current);
        Ok(())
    }

    #[allow(dead_code)]
    pub(crate) fn reserve_memory(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        self.commit_reserve(bytes)
    }

    pub(crate) fn release_memory(&mut self, bytes: u64) -> SearchResult<()> {
        self.current =
            self.current
                .checked_sub(bytes)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "batch memory ledger underflow".to_owned(),
                })?;
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn current(&self) -> u64 {
        self.current
    }

    #[cfg(test)]
    pub(crate) fn peak(&self) -> u64 {
        self.peak
    }
}

/// Cumulative successful response payload bytes.
pub(crate) struct BatchResponseMeter {
    limit: u64,
    used: u64,
}

impl BatchResponseMeter {
    pub(crate) fn new(limit: u64) -> Self {
        Self { limit, used: 0 }
    }

    pub(crate) fn preflight_response(&self, bytes: u64) -> Result<(), BatchMeterError> {
        let projected = self.used.checked_add(bytes).ok_or(BatchMeterError {
            kind: BudgetKind::BatchResponseBytes,
            limit: self.limit,
            requested: u64::MAX,
        })?;
        if projected > self.limit {
            return Err(BatchMeterError {
                kind: BudgetKind::BatchResponseBytes,
                limit: self.limit,
                requested: projected,
            });
        }
        Ok(())
    }

    pub(crate) fn commit_response(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        self.preflight_response(bytes)?;
        self.used += bytes;
        Ok(())
    }

    pub(crate) fn charge_response(&mut self, bytes: u64) -> Result<(), BatchMeterError> {
        self.commit_response(bytes)
    }

    #[cfg(test)]
    pub(crate) fn used(&self) -> u64 {
        self.used
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// a01 — work and memory can be borrowed and mutated simultaneously.
    #[test]
    fn a01_disjoint_work_memory_borrows() {
        let mut meter = BatchExecutionMeter::new(100, 100, 100);
        let work = &mut meter.work;
        let memory = &mut meter.memory;
        work.preflight_work(10).unwrap();
        work.commit_work(10).unwrap();
        memory.reserve_memory(20).unwrap();
        assert_eq!(work.used(), 10);
        assert_eq!(memory.current(), 20);
        assert_eq!(memory.peak(), 20);
    }

    /// a02 — a rejected work charge is atomic.
    #[test]
    fn a02_work_rejection_is_atomic() {
        let mut meter = BatchExecutionMeter::new(10, 100, 100);
        meter.work.commit_work(10).unwrap();
        assert!(matches!(
            meter.work.preflight_work(1),
            Err(BatchMeterError {
                kind: BudgetKind::BatchAggregate,
                limit: 10,
                requested: 11
            })
        ));
        assert_eq!(meter.work.used(), 10);
    }

    #[test]
    fn memory_exact_limit_and_release() {
        let mut meter = BatchExecutionMeter::new(100, 20, 100);
        meter.memory.reserve_memory(20).unwrap();
        assert!(meter.memory.preflight_reserve(1).is_err());
        assert_eq!(meter.memory.current(), 20);
        meter.memory.release_memory(20).unwrap();
        assert_eq!(meter.memory.current(), 0);
        assert_eq!(meter.memory.peak(), 20);
        assert!(meter.memory.release_memory(1).is_err());
    }

    #[test]
    fn response_exact_limit_then_one_over_is_atomic() {
        let mut meter = BatchExecutionMeter::new(100, 100, 10);
        meter.response.charge_response(10).unwrap();
        assert!(meter.response.charge_response(1).is_err());
        assert_eq!(meter.response.used(), 10);
    }

    #[test]
    fn overflow_is_typed_not_wrapped() {
        let mut meter = BatchExecutionMeter::new(u64::MAX, u64::MAX, u64::MAX);
        meter.work.commit_work(u64::MAX).unwrap();
        assert!(matches!(
            meter.work.commit_work(1),
            Err(BatchMeterError {
                requested: u64::MAX,
                ..
            })
        ));
        assert_eq!(meter.work.used(), u64::MAX);
    }
}
