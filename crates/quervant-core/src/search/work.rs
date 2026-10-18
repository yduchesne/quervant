//! One authoritative work meter for a mixed lexical+typed query (PR 14 F1 H1).
//!
//! The mixed executor owns exactly one [`MixedWorkMeter`]. Lexical and typed
//! components charge it through the narrow [`WorkCharge`] seam at their existing
//! charge sites, so the cumulative total cannot exceed the request budget even
//! when the lexical and typed sub-limits are each individually satisfied.
//!
//! Existing units are preserved: `charge` is one work unit, and
//! `charge_scanned` is `1 + freq` (the PR 7 scanned-posting formula). Typed
//! charges also count against a separate typed ceiling, and scanned postings
//! against a separate scanned ceiling.

use crate::analysis::Cancellation;

use super::batch_meter::BatchExecutionMeter;
use super::error::{SearchError, SearchResult};

/// Cancellation polling interval, matching the existing `SearchWork` policy.
const CANCELLATION_POLL_INTERVAL: u64 = 256;

/// A narrow, allocation-free adapter over the approved work-charge sites.
///
/// Implemented by `SearchWork` (pure lexical), `ScanGuard` (pure typed),
/// `MixedWorkMeter` (mixed lexical) and [`TypedCharge`] (mixed typed). Charge
/// units, ordering and error semantics match the existing executors exactly.
pub(crate) trait WorkCharge {
    fn check_cancelled(&self) -> SearchResult<()>;
    fn charge(&mut self, units: u64) -> SearchResult<()>;
    fn charge_scanned(&mut self, freq: u64) -> SearchResult<()>;
}

/// A [`WorkCharge`] that can also report remaining total work (expansion/FST).
pub(crate) trait WorkBudget: WorkCharge {
    fn remaining(&self) -> u64;
}

/// The single authoritative work meter for one mixed request.
pub(crate) struct MixedWorkMeter<'a> {
    total_used: u64,
    typed_used: u64,
    scanned_used: u64,
    total_limit: u64,
    typed_limit: u64,
    scanned_limit: u64,
    next_poll: u64,
    cancel: &'a dyn Cancellation,
    /// Optional cumulative batch sink; charges are committed atomically with the
    /// local counters.
    batch: Option<&'a mut BatchExecutionMeter>,
}

impl<'a> MixedWorkMeter<'a> {
    pub(crate) fn new(
        total_limit: u64,
        typed_limit: u64,
        scanned_limit: u64,
        cancel: &'a dyn Cancellation,
    ) -> Self {
        Self {
            total_used: 0,
            typed_used: 0,
            scanned_used: 0,
            total_limit,
            typed_limit,
            scanned_limit,
            next_poll: CANCELLATION_POLL_INTERVAL,
            cancel,
            batch: None,
        }
    }

    /// Bind the meter to the cumulative batch sink for a batch slot.
    pub(crate) fn with_batch(
        total_limit: u64,
        typed_limit: u64,
        scanned_limit: u64,
        cancel: &'a dyn Cancellation,
        batch: &'a mut BatchExecutionMeter,
    ) -> Self {
        let mut meter = Self::new(total_limit, typed_limit, scanned_limit, cancel);
        meter.batch = Some(batch);
        meter
    }

    #[cfg(test)]
    #[must_use]
    pub(crate) fn total_used(&self) -> u64 {
        self.total_used
    }

    pub(crate) fn check_cancelled(&self) -> SearchResult<()> {
        if self.cancel.is_cancelled() {
            Err(SearchError::Cancelled)
        } else {
            Ok(())
        }
    }

    /// Charge lexical work: one total unit per `units`.
    pub(crate) fn charge_lexical(&mut self, units: u64) -> SearchResult<()> {
        let projected = self
            .total_used
            .checked_add(units)
            .ok_or(SearchError::ResourceLimit {
                limit: self.total_limit,
                requested: u64::MAX,
            })?;
        if projected > self.total_limit {
            return Err(SearchError::ResourceLimit {
                limit: self.total_limit,
                requested: projected,
            });
        }
        if let Some(batch) = self.batch.as_mut() {
            batch
                .preflight_work(units)
                .map_err(|error| error.to_search_error())?;
        }
        self.total_used = projected;
        if let Some(batch) = self.batch.as_mut() {
            batch
                .commit_work(units)
                .map_err(|error| error.to_search_error())?;
        }
        self.poll_if_due()
    }

    /// Charge typed work: one total unit and one typed unit per `units`.
    pub(crate) fn charge_typed(&mut self, units: u64) -> SearchResult<()> {
        let typed = self
            .typed_used
            .checked_add(units)
            .ok_or(SearchError::ResourceLimit {
                limit: self.typed_limit,
                requested: u64::MAX,
            })?;
        if typed > self.typed_limit {
            return Err(SearchError::ResourceLimit {
                limit: self.typed_limit,
                requested: typed,
            });
        }
        let total = self
            .total_used
            .checked_add(units)
            .ok_or(SearchError::ResourceLimit {
                limit: self.total_limit,
                requested: u64::MAX,
            })?;
        if total > self.total_limit {
            return Err(SearchError::ResourceLimit {
                limit: self.total_limit,
                requested: total,
            });
        }
        if let Some(batch) = self.batch.as_mut() {
            batch
                .preflight_work(units)
                .map_err(|error| error.to_search_error())?;
        }
        self.typed_used = typed;
        self.total_used = total;
        if let Some(batch) = self.batch.as_mut() {
            batch
                .commit_work(units)
                .map_err(|error| error.to_search_error())?;
        }
        self.poll_if_due()
    }

    /// Charge scanned posting occurrences using the PR 7 formula (`1 + freq`),
    /// plus the independent scanned-occurrence ceiling.
    pub(crate) fn charge_scanned_postings(&mut self, freq: u64) -> SearchResult<()> {
        let scanned = self
            .scanned_used
            .checked_add(freq)
            .ok_or(SearchError::ResourceLimit {
                limit: self.scanned_limit,
                requested: u64::MAX,
            })?;
        if scanned > self.scanned_limit {
            return Err(SearchError::ResourceLimit {
                limit: self.scanned_limit,
                requested: scanned,
            });
        }
        let units = freq.saturating_add(1);
        let total = self
            .total_used
            .checked_add(units)
            .ok_or(SearchError::ResourceLimit {
                limit: self.total_limit,
                requested: u64::MAX,
            })?;
        if total > self.total_limit {
            return Err(SearchError::ResourceLimit {
                limit: self.total_limit,
                requested: total,
            });
        }
        if let Some(batch) = self.batch.as_mut() {
            batch
                .preflight_work(units)
                .map_err(|error| error.to_search_error())?;
        }
        self.scanned_used = scanned;
        self.total_used = total;
        if let Some(batch) = self.batch.as_mut() {
            batch
                .commit_work(units)
                .map_err(|error| error.to_search_error())?;
        }
        self.poll_if_due()
    }

    fn poll_if_due(&mut self) -> SearchResult<()> {
        if self.total_used >= self.next_poll {
            self.next_poll = self.total_used.saturating_add(CANCELLATION_POLL_INTERVAL);
            self.check_cancelled()
        } else {
            Ok(())
        }
    }
}

impl WorkCharge for MixedWorkMeter<'_> {
    fn check_cancelled(&self) -> SearchResult<()> {
        MixedWorkMeter::check_cancelled(self)
    }

    fn charge(&mut self, units: u64) -> SearchResult<()> {
        self.charge_lexical(units)
    }

    fn charge_scanned(&mut self, freq: u64) -> SearchResult<()> {
        self.charge_scanned_postings(freq)
    }
}

impl WorkBudget for MixedWorkMeter<'_> {
    fn remaining(&self) -> u64 {
        self.total_limit.saturating_sub(self.total_used)
    }
}

/// Short-lived typed adapter over the shared mixed meter.
///
/// `evaluate_query`/geo preparation charge typed work through this adapter, so
/// their counters advance the one authoritative total. The borrow is scoped to
/// a single typed evaluation and never overlaps the lexical meter borrow.
pub(crate) struct TypedCharge<'m, 'a> {
    meter: &'m mut MixedWorkMeter<'a>,
}

impl<'m, 'a> TypedCharge<'m, 'a> {
    pub(crate) fn new(meter: &'m mut MixedWorkMeter<'a>) -> Self {
        Self { meter }
    }
}

impl WorkCharge for TypedCharge<'_, '_> {
    fn check_cancelled(&self) -> SearchResult<()> {
        self.meter.check_cancelled()
    }

    fn charge(&mut self, units: u64) -> SearchResult<()> {
        self.meter.charge_typed(units)
    }

    fn charge_scanned(&mut self, freq: u64) -> SearchResult<()> {
        self.meter.charge_typed(freq)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::{CancellationFlag, NeverCancel};

    #[test]
    fn aggregate_exhaustion_blocks_typed_after_lexical() {
        let mut meter = MixedWorkMeter::new(10, 100, 100, &NeverCancel);
        meter.charge_lexical(6).unwrap();
        meter.charge_typed(4).unwrap();
        assert_eq!(meter.total_used(), 10);
        // At the aggregate limit, the next unit fails even though typed is far
        // below its own ceiling.
        assert!(matches!(
            meter.charge_typed(1),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(meter.total_used(), 10);
    }

    #[test]
    fn total_exact_limit_then_one_over() {
        let mut meter = MixedWorkMeter::new(10, 100, 100, &NeverCancel);
        meter.charge_lexical(10).unwrap();
        assert_eq!(meter.total_used(), 10);
        assert!(matches!(
            meter.charge_lexical(1),
            Err(SearchError::ResourceLimit {
                limit: 10,
                requested: 11
            })
        ));
        // A rejected charge does not advance the total.
        assert_eq!(meter.total_used(), 10);
    }

    #[test]
    fn typed_exact_limit_then_one_over() {
        let mut meter = MixedWorkMeter::new(100, 5, 100, &NeverCancel);
        meter.charge_typed(5).unwrap();
        assert_eq!(meter.total_used(), 5);
        assert!(matches!(
            meter.charge_typed(1),
            Err(SearchError::ResourceLimit {
                limit: 5,
                requested: 6
            })
        ));
        assert_eq!(meter.total_used(), 5);
    }

    #[test]
    fn scanned_exact_limit_then_one_over() {
        let mut meter = MixedWorkMeter::new(100, 100, 10, &NeverCancel);
        meter.charge_scanned_postings(10).unwrap();
        // At the scanned ceiling the total advanced by `1 + freq`.
        assert_eq!(meter.total_used(), 11);
        assert!(matches!(
            meter.charge_scanned_postings(1),
            Err(SearchError::ResourceLimit {
                limit: 10,
                requested: 11
            })
        ));
        assert_eq!(meter.total_used(), 11);
    }

    #[test]
    fn scanned_charges_add_one_plus_freq() {
        let mut meter = MixedWorkMeter::new(100, 100, 10, &NeverCancel);
        meter.charge_scanned_postings(4).unwrap();
        assert_eq!(meter.total_used(), 5);
        assert!(matches!(
            meter.charge_scanned_postings(7),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn rejected_typed_charge_does_not_mutate_counters() {
        let mut meter = MixedWorkMeter::new(100, 3, 100, &NeverCancel);
        meter.charge_typed(3).unwrap();
        let before = meter.total_used();
        assert!(meter.charge_typed(1).is_err());
        assert_eq!(meter.total_used(), before);
    }

    #[test]
    fn shared_adapters_forward_charges_and_cancellation() {
        let flag = CancellationFlag::new();
        let mut meter = MixedWorkMeter::new(100, 100, 100, &flag);
        {
            let mut work = super::super::execute::SearchWork::shared(&mut meter);
            work.charge(3).unwrap();
            assert!(work.check_cancelled().is_ok());
        }
        assert_eq!(meter.total_used(), 3);
        {
            let mut typed = TypedCharge::new(&mut meter);
            let mut guard = super::super::typed::ScanGuard::shared(&mut typed);
            guard.charge(2).unwrap();
            assert!(guard.poll().is_ok());
        }
        assert_eq!(meter.total_used(), 5);
        flag.cancel();
        {
            let work = super::super::execute::SearchWork::shared(&mut meter);
            assert!(matches!(
                work.check_cancelled(),
                Err(SearchError::Cancelled)
            ));
        }
        {
            let mut typed = TypedCharge::new(&mut meter);
            let guard = super::super::typed::ScanGuard::shared(&mut typed);
            assert!(matches!(guard.poll(), Err(SearchError::Cancelled)));
        }
    }
}
