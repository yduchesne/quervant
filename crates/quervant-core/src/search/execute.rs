//! Snapshot-bound lexical execution (PR 7, D07-03; Amendment 01).
//!
//! Evaluation is deliberately two-phase and materialized: snapshot-wide BM25
//! statistics are computed first (from **positive/scoring-eligible** leaves only),
//! then each segment is evaluated into a bounded per-segment doc-id/score map.
//! Results are merged by logical `DocumentKey` across segments. This is the simple,
//! correct v1 baseline; it does not claim streaming or WAND execution.
//!
//! Resource accounting is split into three independent contracts:
//!
//! * **Cumulative work / scanned occurrences** — monotonic for the whole request
//!   (`SearchWork`).
//! * **Per-segment logical candidate entries** — the peak concurrently
//!   materialized entries for the segment currently being evaluated
//!   (`CandidateBudget::segment_entries`), reset per segment.
//! * **Search-wide logical candidate bytes** — simultaneously retained global
//!   result bytes plus the current segment's temporary bytes.
//!
//! The byte figures are conservative logical accounting units, not process RSS.

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use crate::analysis::Cancellation;
use crate::analysis::limits::CANCELLATION_POLL_INTERVAL;
use crate::contract::document::DocumentKey;
use crate::contract::result::TopK;
use crate::index::ReaderSnapshot;
use crate::segment::{Occurrence, SegmentReader};

use super::error::{SearchError, SearchResult};
use super::expand::{Expansion, expand_query};
use super::limits::SearchLimits;
use super::phrase::{PhraseMatch, PhraseTermData, match_phrase};
use super::plan::{CompiledLeaf, CompiledNode, CompiledQuery, PhraseToken};
use super::score::{DeferredBm25, SnapshotStats, compute_stats};
use super::topk::TopKSelector;
use super::{SearchHit, SearchResponse};

// Conservative logical accounting units (bytes), including a tree/hash node
// overhead allowance. They are deterministic and overflow-checked.
const LIVE_SET_BYTES_PER_ENTRY: u64 = 48;
const SET_BYTES_PER_ENTRY: u64 = 48;
const TERM_POSTING_BYTES: u64 = 16;
const SCORED_MAP_BYTES_PER_ENTRY: u64 = 64;
const PHRASE_DOC_BYTES: u64 = 16;
const PHRASE_MATCH_BYTES: u64 = 64;
const PHRASE_MATCH_TERM_BYTES: u64 = 32;
const GLOBAL_ENTRY_OVERHEAD: u64 = 96;

// Bounded phrase-verification scratch accounting units. These cover the internal
// vectors in `phrase.rs` that are not retained output; the retained phrase-match
// output (`term_freqs`, matches) is covered by the caller's `PHRASE_MATCH*`
// reservation and is deliberately **not** charged a second time here.
// Visible to the sibling `phrase` module's bounded verification code.
pub(super) const PHRASE_SCRATCH_REF_BYTES: u64 = 16;
pub(super) const PHRASE_SCRATCH_DOC_BYTES: u64 = 16;
pub(super) const PHRASE_SCRATCH_OCC_SLICE_BYTES: u64 = 16;
#[allow(dead_code)]
const PHRASE_SCRATCH_FREQ_BYTES: u64 = 48;
// The retained-output unit must be at least the caller's phrase-match term unit.
const _: () = assert!(PHRASE_SCRATCH_FREQ_BYTES >= PHRASE_MATCH_TERM_BYTES);

fn phrase_occurrence_bytes() -> u64 {
    std::mem::size_of::<Occurrence>() as u64 + 32
}

/// Exact bytes for `entries` items of `bytes_each`, using checked arithmetic.
fn bytes_for_count(entries: u64, bytes_each: u64) -> SearchResult<u64> {
    entries
        .checked_mul(bytes_each)
        .ok_or(SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })
}

/// Logical bytes charged for retaining one logical document key.
fn bytes_for_key(key: &DocumentKey) -> SearchResult<u64> {
    let len = u64::try_from(key.as_str().len()).map_err(|_| SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    GLOBAL_ENTRY_OVERHEAD
        .checked_add(len)
        .ok_or(SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })
}

/// A pair of live logical candidate reservations (entries and bytes).
///
/// These are metadata records only: each has exactly one owner and one
/// release/transfer site in the segment execution flow.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct Charges {
    entries: u64,
    bytes: u64,
}

impl Charges {
    const ZERO: Self = Self {
        entries: 0,
        bytes: 0,
    };

    fn add(self, entries: u64, bytes: u64) -> SearchResult<Self> {
        Ok(Self {
            entries: self
                .entries
                .checked_add(entries)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?,
            bytes: self
                .bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?,
        })
    }
}

/// A segment's matched keys and scores whose logical bytes have already been
/// transferred to global ownership. The caller must not reserve them again.
struct SegmentResults {
    entries: Vec<(DocumentKey, f64)>,
    reserved_bytes: u64,
}

use super::memory::MemoryCharge;
use super::work::MixedWorkMeter;

/// A checked deterministic work/candidate budget for one search.
///
/// In `Owned` mode it is the standalone lexical meter. In `Shared` mode it
/// forwards every charge to the single mixed-query meter; it owns no counter.
pub(crate) struct SearchWork<'a> {
    inner: SearchWorkInner<'a>,
}

enum SearchWorkInner<'a> {
    Owned {
        limit: u64,
        consumed: u64,
        next_poll: u64,
        scanned: u64,
        scanned_limit: u64,
        cancel: &'a dyn Cancellation,
    },
    Shared(&'a mut dyn super::work::WorkBudget),
}

impl<'a> SearchWork<'a> {
    /// Create a work budget that polls `cancel` at fixed intervals.
    pub(crate) fn new(limit: u64, cancel: &'a dyn Cancellation) -> Self {
        Self {
            inner: SearchWorkInner::Owned {
                limit,
                consumed: 0,
                next_poll: CANCELLATION_POLL_INTERVAL,
                scanned: 0,
                scanned_limit: u64::MAX,
                cancel,
            },
        }
    }

    /// Bind lexical execution to the shared mixed-query meter. The borrow must
    /// be scoped so it never overlaps a typed meter borrow.
    pub(crate) fn shared(work: &'a mut dyn super::work::WorkBudget) -> Self {
        Self {
            inner: SearchWorkInner::Shared(work),
        }
    }

    /// Bound cumulative scanned posting occurrences independently of total work.
    pub(crate) fn with_scanned_limit(mut self, limit: u64) -> Self {
        if let SearchWorkInner::Owned { scanned_limit, .. } = &mut self.inner {
            *scanned_limit = limit;
        }
        self
    }

    /// Poll cancellation explicitly (boundaries and no-match paths).
    pub(crate) fn check_cancelled(&self) -> SearchResult<()> {
        match &self.inner {
            SearchWorkInner::Shared(work) => work.check_cancelled(),
            SearchWorkInner::Owned { cancel, .. } => {
                if cancel.is_cancelled() {
                    Err(SearchError::Cancelled)
                } else {
                    Ok(())
                }
            }
        }
    }

    /// Work units still available under this budget.
    pub(crate) fn remaining(&self) -> u64 {
        match &self.inner {
            SearchWorkInner::Shared(work) => work.remaining(),
            SearchWorkInner::Owned {
                limit, consumed, ..
            } => limit.saturating_sub(*consumed),
        }
    }

    /// Charge deterministic work units and poll cancellation at fixed boundaries.
    pub(crate) fn charge(&mut self, units: u64) -> SearchResult<()> {
        match &mut self.inner {
            SearchWorkInner::Shared(work) => work.charge(units),
            SearchWorkInner::Owned {
                limit,
                consumed,
                next_poll,
                cancel,
                ..
            } => {
                *consumed = consumed
                    .checked_add(units)
                    .ok_or(SearchError::ResourceLimit {
                        limit: *limit,
                        requested: u64::MAX,
                    })?;
                if *consumed > *limit {
                    return Err(SearchError::ResourceLimit {
                        limit: *limit,
                        requested: *consumed,
                    });
                }
                if *consumed >= *next_poll {
                    *next_poll = consumed.saturating_add(CANCELLATION_POLL_INTERVAL);
                    if cancel.is_cancelled() {
                        return Err(SearchError::Cancelled);
                    }
                }
                Ok(())
            }
        }
    }

    /// Charge `freq` scanned occurrences (checked, one-over rejected) and the
    /// corresponding deterministic work (`1 + freq`).
    pub(crate) fn charge_scanned(&mut self, freq: u64) -> SearchResult<()> {
        match &mut self.inner {
            SearchWorkInner::Shared(work) => work.charge_scanned(freq),
            SearchWorkInner::Owned {
                scanned,
                scanned_limit,
                ..
            } => {
                *scanned = scanned
                    .checked_add(freq)
                    .ok_or(SearchError::ResourceLimit {
                        limit: *scanned_limit,
                        requested: u64::MAX,
                    })?;
                if *scanned > *scanned_limit {
                    return Err(SearchError::ResourceLimit {
                        limit: *scanned_limit,
                        requested: *scanned,
                    });
                }
                self.charge(freq.saturating_add(1))
            }
        }
    }
}

/// Logical per-segment and search-wide candidate byte accounting.
///
/// `segment_entries`/`segment_bytes` bound the **currently evaluated segment** and
/// reset between segments. `global_bytes` bounds simultaneously retained global
/// result map entries. `reserve_global` checks the combined total so a segment's
/// live temporaries and the global map cannot jointly exceed the byte budget.
pub(crate) struct CandidateBudget {
    max_segment_entries: u64,
    max_total_bytes: u64,
    global_bytes: u64,
    segment_entries: u64,
    segment_bytes: u64,
}

impl CandidateBudget {
    pub(crate) fn new(limits: &SearchLimits) -> Self {
        Self {
            max_segment_entries: limits.max_segment_candidate_entries(),
            max_total_bytes: limits.max_total_candidate_bytes(),
            global_bytes: 0,
            segment_entries: 0,
            segment_bytes: 0,
        }
    }

    fn begin_segment(&mut self) -> SearchResult<()> {
        if self.segment_entries != 0 || self.segment_bytes != 0 {
            return Err(SearchError::CorruptIndex {
                detail: "candidate ledger was not released before a new segment".to_owned(),
            });
        }
        Ok(())
    }

    /// Checked, non-mutating segment admission. Checks every addition and both
    /// local ceilings without changing any counter.
    #[allow(dead_code)] // Wired into the segment ledger in Phase C2.
    fn preflight_segment(&self, entries: u64, bytes: u64) -> SearchResult<()> {
        let new_entries =
            self.segment_entries
                .checked_add(entries)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_segment_entries,
                    requested: u64::MAX,
                })?;
        let new_segment_bytes =
            self.segment_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        let new_total =
            self.global_bytes
                .checked_add(new_segment_bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        if new_entries > self.max_segment_entries {
            return Err(SearchError::ResourceLimit {
                limit: self.max_segment_entries,
                requested: new_entries,
            });
        }
        if new_total > self.max_total_bytes {
            return Err(SearchError::ResourceLimit {
                limit: self.max_total_bytes,
                requested: new_total,
            });
        }
        Ok(())
    }

    /// Infallible-after-preflight segment commit. Panics only on an internal
    /// contract breach (commit without a matching preflight).
    #[allow(dead_code)] // Wired into the segment ledger in Phase C2.
    fn commit_segment(&mut self, entries: u64, bytes: u64) {
        self.segment_entries = self
            .segment_entries
            .checked_add(entries)
            .expect("segment commit requires a prior preflight");
        self.segment_bytes = self
            .segment_bytes
            .checked_add(bytes)
            .expect("segment commit requires a prior preflight");
    }

    /// Atomically reserve segment entries/bytes. Neither counter changes if either
    /// bound would be exceeded or on arithmetic overflow.
    #[cfg(test)]
    fn reserve_segment(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        self.preflight_segment(entries, bytes)?;
        self.commit_segment(entries, bytes);
        Ok(())
    }

    fn release_segment(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        // Validate both subtractions into locals before mutating either field, so a
        // mixed-validity release cannot leave a half-updated segment.
        let new_entries =
            self.segment_entries
                .checked_sub(entries)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "candidate entry ledger underflow".to_owned(),
                })?;
        let new_bytes =
            self.segment_bytes
                .checked_sub(bytes)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "candidate byte ledger underflow".to_owned(),
                })?;
        self.segment_entries = new_entries;
        self.segment_bytes = new_bytes;
        Ok(())
    }

    /// Checked, non-mutating global admission.
    pub(crate) fn preflight_global_bytes(&self, bytes: u64) -> SearchResult<()> {
        let new_global =
            self.global_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        let total =
            new_global
                .checked_add(self.segment_bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        if total > self.max_total_bytes {
            return Err(SearchError::ResourceLimit {
                limit: self.max_total_bytes,
                requested: total,
            });
        }
        Ok(())
    }

    /// Infallible-after-preflight global commit.
    pub(crate) fn commit_global_bytes(&mut self, bytes: u64) {
        self.global_bytes = self
            .global_bytes
            .checked_add(bytes)
            .expect("global commit requires a prior preflight");
    }

    /// Reserve global-only bytes (production: retained top-K candidates).
    ///
    /// The combined `global_bytes + segment_bytes` peak is checked so retained
    /// candidates and live segment scratch cannot jointly exceed the budget.
    #[cfg(test)]
    pub(crate) fn reserve_global_bytes(&mut self, bytes: u64) -> SearchResult<()> {
        self.preflight_global_bytes(bytes)?;
        self.commit_global_bytes(bytes);
        Ok(())
    }

    /// Release global-only bytes exactly once (e.g. on candidate eviction).
    /// Validate that `bytes` can be released from the global candidate ledger
    /// without mutating it.
    pub(crate) fn preflight_release_global_bytes(&self, bytes: u64) -> SearchResult<()> {
        self.global_bytes
            .checked_sub(bytes)
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: "global candidate byte ledger underflow".to_owned(),
            })?;
        Ok(())
    }

    pub(crate) fn release_global_bytes(&mut self, bytes: u64) -> SearchResult<()> {
        self.preflight_release_global_bytes(bytes)?;
        self.global_bytes -= bytes;
        Ok(())
    }

    /// Reserve global-only bytes (test fixture for the combined segment/global
    /// byte invariant; production transfers with [`Self::transfer_segment_to_global`]).
    #[cfg(test)]
    fn reserve_global(&mut self, bytes: u64) -> SearchResult<()> {
        let new_global =
            self.global_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        let total =
            new_global
                .checked_add(self.segment_bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        if total > self.max_total_bytes {
            return Err(SearchError::ResourceLimit {
                limit: self.max_total_bytes,
                requested: total,
            });
        }
        self.global_bytes = new_global;
        Ok(())
    }

    /// Atomically move `entries`/`bytes` from segment to global ownership.
    ///
    /// The total (`segment_bytes + global_bytes`) is preserved. All checks run
    /// before any counter mutation, so a rejected transfer leaves every counter
    /// unchanged. Test-only: production transfers through the ledger transition.
    #[cfg(test)]
    fn transfer_segment_to_global(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        if entries > self.segment_entries {
            return Err(SearchError::CorruptIndex {
                detail: "transfer entries exceed the live segment reservation".to_owned(),
            });
        }
        if bytes > self.segment_bytes {
            return Err(SearchError::CorruptIndex {
                detail: "transfer bytes exceed the live segment reservation".to_owned(),
            });
        }
        let new_global =
            self.global_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        let new_segment_bytes = self.segment_bytes - bytes;
        let total =
            new_global
                .checked_add(new_segment_bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_total_bytes,
                    requested: u64::MAX,
                })?;
        if total > self.max_total_bytes {
            return Err(SearchError::ResourceLimit {
                limit: self.max_total_bytes,
                requested: total,
            });
        }
        // All checks passed: commit atomically.
        self.segment_entries -= entries;
        self.segment_bytes = new_segment_bytes;
        self.global_bytes = new_global;
        Ok(())
    }

    fn end_segment(&self) -> SearchResult<()> {
        if self.segment_entries != 0 || self.segment_bytes != 0 {
            return Err(SearchError::CorruptIndex {
                detail: "candidate ledger was not zeroed at segment end".to_owned(),
            });
        }
        Ok(())
    }
}

/// A complete, checked snapshot of the segment ledger and its owning budget.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct LedgerState {
    global_bytes: u64,
    segment_entries: u64,
    segment_bytes: u64,
    outstanding_entries: u64,
    outstanding_bytes: u64,
}

/// RAII tracking of the outstanding segment reservations made during one segment.
///
/// Reservations are released explicitly as temporary collections are dropped and,
/// on any early return, by [`Drop`]. The ledger never owns a collection, so it can
/// be dropped independently of them.
struct SegmentCandidateLedger<'a> {
    budget: &'a mut CandidateBudget,
    outstanding_entries: u64,
    outstanding_bytes: u64,
}

impl<'a> SegmentCandidateLedger<'a> {
    fn new(budget: &'a mut CandidateBudget) -> SearchResult<Self> {
        budget.begin_segment()?;
        Ok(Self {
            budget,
            outstanding_entries: 0,
            outstanding_bytes: 0,
        })
    }

    fn snapshot(&self) -> LedgerState {
        LedgerState {
            global_bytes: self.budget.global_bytes,
            segment_entries: self.budget.segment_entries,
            segment_bytes: self.budget.segment_bytes,
            outstanding_entries: self.outstanding_entries,
            outstanding_bytes: self.outstanding_bytes,
        }
    }

    /// Commit a fully validated transition. Assignment only; cannot fail.
    fn commit(&mut self, next: LedgerState) {
        self.budget.global_bytes = next.global_bytes;
        self.budget.segment_entries = next.segment_entries;
        self.budget.segment_bytes = next.segment_bytes;
        self.outstanding_entries = next.outstanding_entries;
        self.outstanding_bytes = next.outstanding_bytes;
    }

    /// Single-ledger ownership contract: the ledger counters must equal the
    /// budget's segment counters before any transition.
    fn ensure_consistent(state: LedgerState) -> SearchResult<()> {
        if state.outstanding_entries != state.segment_entries
            || state.outstanding_bytes != state.segment_bytes
        {
            return Err(SearchError::CorruptIndex {
                detail: "segment ledger and candidate budget disagree".to_owned(),
            });
        }
        Ok(())
    }

    fn checked_reserve(&self, entries: u64, bytes: u64) -> SearchResult<LedgerState> {
        let state = self.snapshot();
        Self::ensure_consistent(state)?;
        let new_segment_entries =
            state
                .segment_entries
                .checked_add(entries)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_segment_entries,
                    requested: u64::MAX,
                })?;
        let new_segment_bytes =
            state
                .segment_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_total_bytes,
                    requested: u64::MAX,
                })?;
        let new_outstanding_entries =
            state
                .outstanding_entries
                .checked_add(entries)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_segment_entries,
                    requested: u64::MAX,
                })?;
        let new_outstanding_bytes =
            state
                .outstanding_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_total_bytes,
                    requested: u64::MAX,
                })?;
        if new_segment_entries > self.budget.max_segment_entries {
            return Err(SearchError::ResourceLimit {
                limit: self.budget.max_segment_entries,
                requested: new_segment_entries,
            });
        }
        let new_total = state.global_bytes.checked_add(new_segment_bytes).ok_or(
            SearchError::ResourceLimit {
                limit: self.budget.max_total_bytes,
                requested: u64::MAX,
            },
        )?;
        if new_total > self.budget.max_total_bytes {
            return Err(SearchError::ResourceLimit {
                limit: self.budget.max_total_bytes,
                requested: new_total,
            });
        }
        Ok(LedgerState {
            global_bytes: state.global_bytes,
            segment_entries: new_segment_entries,
            segment_bytes: new_segment_bytes,
            outstanding_entries: new_outstanding_entries,
            outstanding_bytes: new_outstanding_bytes,
        })
    }

    fn checked_release(&self, entries: u64, bytes: u64) -> SearchResult<LedgerState> {
        let state = self.snapshot();
        Self::ensure_consistent(state)?;
        if entries > state.segment_entries || entries > state.outstanding_entries {
            return Err(SearchError::CorruptIndex {
                detail: "candidate entry release underflow".to_owned(),
            });
        }
        if bytes > state.segment_bytes || bytes > state.outstanding_bytes {
            return Err(SearchError::CorruptIndex {
                detail: "candidate byte release underflow".to_owned(),
            });
        }
        Ok(LedgerState {
            global_bytes: state.global_bytes,
            segment_entries: state.segment_entries - entries,
            segment_bytes: state.segment_bytes - bytes,
            outstanding_entries: state.outstanding_entries - entries,
            outstanding_bytes: state.outstanding_bytes - bytes,
        })
    }

    fn checked_transfer(&self, entries: u64, bytes: u64) -> SearchResult<LedgerState> {
        let state = self.snapshot();
        Self::ensure_consistent(state)?;
        if entries > state.segment_entries || entries > state.outstanding_entries {
            return Err(SearchError::CorruptIndex {
                detail: "transfer entries exceed the live segment reservation".to_owned(),
            });
        }
        if bytes > state.segment_bytes || bytes > state.outstanding_bytes {
            return Err(SearchError::CorruptIndex {
                detail: "transfer bytes exceed the live segment reservation".to_owned(),
            });
        }
        let new_global =
            state
                .global_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_total_bytes,
                    requested: u64::MAX,
                })?;
        let new_segment_bytes = state.segment_bytes - bytes;
        let total =
            new_global
                .checked_add(new_segment_bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_total_bytes,
                    requested: u64::MAX,
                })?;
        if total > self.budget.max_total_bytes {
            return Err(SearchError::ResourceLimit {
                limit: self.budget.max_total_bytes,
                requested: total,
            });
        }
        Ok(LedgerState {
            global_bytes: new_global,
            segment_entries: state.segment_entries - entries,
            segment_bytes: new_segment_bytes,
            outstanding_entries: state.outstanding_entries - entries,
            outstanding_bytes: state.outstanding_bytes - bytes,
        })
    }

    /// All-or-nothing segment reservation (standalone/local only).
    fn reserve(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        self.reserve_with_memory(entries, bytes, None)
    }

    /// All-or-nothing reservation with an ephemeral batch-memory sink: local
    /// preflight, batch preflight, batch commit, then the local commit.
    fn reserve_with_memory(
        &mut self,
        entries: u64,
        bytes: u64,
        mut memory: Option<&mut (dyn MemoryCharge + '_)>,
    ) -> SearchResult<()> {
        let next = self.checked_reserve(entries, bytes)?;
        if let Some(sink) = memory.as_deref_mut() {
            sink.preflight(bytes)
                .map_err(|error| error.to_search_error())?;
        }
        if let Some(sink) = memory {
            sink.commit(bytes)
                .map_err(|error| error.to_search_error())?;
        }
        self.commit(next);
        Ok(())
    }

    /// All-or-nothing segment release (standalone/local only).
    fn release(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        self.release_with_memory(entries, bytes, None)
    }

    /// All-or-nothing release: validate both balances, release batch, commit local.
    fn release_with_memory(
        &mut self,
        entries: u64,
        bytes: u64,
        mut memory: Option<&mut (dyn MemoryCharge + '_)>,
    ) -> SearchResult<()> {
        let next = self.checked_release(entries, bytes)?;
        if let Some(sink) = memory.as_deref_mut() {
            sink.preflight_release(bytes)?;
        }
        if let Some(sink) = memory {
            sink.release(bytes)?;
        }
        self.commit(next);
        Ok(())
    }

    /// All-or-nothing transfer of outstanding segment ownership to global bytes.
    fn transfer_to_global(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        let next = self.checked_transfer(entries, bytes)?;
        self.commit(next);
        Ok(())
    }

    /// Verify that every owned segment temporary was released or transferred, then
    /// close the segment. This is deliberately **not** a bulk release: leaving an
    /// outstanding reservation is an internal invariant failure.
    fn finish(&mut self) -> SearchResult<()> {
        if self.outstanding_entries != 0 || self.outstanding_bytes != 0 {
            return Err(SearchError::CorruptIndex {
                detail: "segment ledger still owns reservations at finish".to_owned(),
            });
        }
        self.budget.end_segment()
    }
}

impl Drop for SegmentCandidateLedger<'_> {
    fn drop(&mut self) {
        if self.outstanding_entries != 0 || self.outstanding_bytes != 0 {
            // Best-effort cleanup of outstanding segment charges. With the atomic
            // release a partial underflow cannot occur; a genuinely inconsistent
            // injected state is not silently repaired with fabricated counters.
            let _ = self
                .budget
                .release_segment(self.outstanding_entries, self.outstanding_bytes);
            self.outstanding_entries = 0;
            self.outstanding_bytes = 0;
        }
    }
}

/// A scoped owner for phrase-verification scratch reservations.
///
/// Wraps a segment ledger and tracks only the scratch charged by one
/// `match_phrase` invocation. The guard releases any outstanding scratch on drop;
/// it never owns the collections themselves, so callers must drop a collection
/// before releasing its charge (or rely on the guard being declared after the
/// scratch vectors, which makes Rust drop the vectors first).
pub(super) struct PhraseScratch<'l, 'b> {
    ledger: &'l mut SegmentCandidateLedger<'b>,
    charges: Charges,
}

impl<'l, 'b> PhraseScratch<'l, 'b> {
    fn new(ledger: &'l mut SegmentCandidateLedger<'b>) -> Self {
        Self {
            ledger,
            charges: Charges::ZERO,
        }
    }

    /// Reserve scratch for `entries` elements of `bytes_each`, committing local
    /// totals only after the ledger transition succeeds.
    pub(super) fn reserve(
        &mut self,
        entries: u64,
        bytes_each: u64,
        memory: Option<&mut (dyn MemoryCharge + '_)>,
    ) -> SearchResult<()> {
        let bytes = bytes_for_count(entries, bytes_each)?;
        let next = self.charges.add(entries, bytes)?;
        self.ledger.reserve_with_memory(entries, bytes, memory)?;
        self.charges = next;
        Ok(())
    }

    /// Release previously reserved scratch, validating local totals before the
    /// ledger transition.
    pub(super) fn release(
        &mut self,
        entries: u64,
        bytes_each: u64,
        memory: Option<&mut (dyn MemoryCharge + '_)>,
    ) -> SearchResult<()> {
        let bytes = bytes_for_count(entries, bytes_each)?;
        if entries > self.charges.entries || bytes > self.charges.bytes {
            return Err(SearchError::CorruptIndex {
                detail: "phrase scratch release underflow".to_owned(),
            });
        }
        self.ledger.release_with_memory(entries, bytes, memory)?;
        self.charges.entries -= entries;
        self.charges.bytes -= bytes;
        Ok(())
    }

    /// Test-only view of the currently outstanding scratch `(entries, bytes)`.
    #[cfg(test)]
    pub(super) fn test_charges(&self) -> (u64, u64) {
        (self.charges.entries, self.charges.bytes)
    }
}

impl Drop for PhraseScratch<'_, '_> {
    fn drop(&mut self) {
        if self.charges.entries != 0 || self.charges.bytes != 0 {
            let _ = self
                .ledger
                .release(self.charges.entries, self.charges.bytes);
            self.charges = Charges::ZERO;
        }
    }
}

/// Test-only scratch owner for direct `phrase.rs` unit tests.
#[cfg(test)]
pub(super) fn phrase_scratch_for_test() -> PhraseScratch<'static, 'static> {
    let limits = SearchLimits::default();
    let budget: &'static mut CandidateBudget = Box::leak(Box::new(CandidateBudget::new(&limits)));
    let ledger: &'static mut SegmentCandidateLedger<'static> = Box::leak(Box::new(
        SegmentCandidateLedger::new(budget).expect("fresh budget"),
    ));
    PhraseScratch::new(ledger)
}

/// Per-leaf postings for one segment.
pub(crate) enum LeafData {
    Term {
        field_id: u32,
        terms: Vec<TermPostings>,
    },
    Phrase {
        field_id: u32,
        matches: Vec<PhraseMatch>,
    },
}

pub(crate) struct TermPostings {
    term: String,
    /// Decoded `(doc_id, freq)` pairs in strictly ascending `doc_id` order.
    ///
    /// PR 15E-B1b relies on this invariant: [`LeafData::matches`] binary-searches
    /// this vector instead of scanning it. The order comes from
    /// `PostingsReader::next_with`, which rejects non-increasing doc-id deltas, and
    /// `build_leaf_data` pushes the decoded postings without reordering them. No
    /// other production constructor exists, so this vector must never be sorted or
    /// reordered after construction (that would only add work, not correctness).
    postings: Vec<(u64, u64)>,
}

impl LeafData {
    /// Whether this leaf matches one physical document.
    pub(crate) fn matches(&self, doc_id: u64) -> bool {
        match self {
            // Sorted-decoded postings (see [`TermPostings::postings`]) make each
            // term's membership a binary search: no copy, no extra index and no
            // re-sort per examined document. The outer `any` keeps the existing OR
            // semantics across the expanded terms of one leaf.
            Self::Term { terms, .. } => {
                #[cfg(test)]
                test_observation::record_term_membership_lookup();
                terms.iter().any(|term| {
                    term.postings
                        .binary_search_by_key(&doc_id, |(posting_doc_id, _)| *posting_doc_id)
                        .is_ok()
                })
            }
            // Phrase membership is unchanged: phrase verification already produced
            // the matching doc ids, so a linear membership scan is retained.
            Self::Phrase { matches, .. } => matches.iter().any(|matched| matched.doc_id == doc_id),
        }
    }

    /// Upper bound on the number of docs this leaf can match.
    fn entry_upper_bound(&self) -> u64 {
        match self {
            Self::Term { terms, .. } => terms
                .iter()
                .map(|term| term.postings.len() as u64)
                .fold(0u64, |acc, value| acc.saturating_add(value)),
            Self::Phrase { matches, .. } => matches.len() as u64,
        }
    }

    fn match_set(&self) -> BTreeSet<u64> {
        let mut set = BTreeSet::new();
        match self {
            Self::Term { terms, .. } => {
                for term in terms {
                    for (doc_id, _) in &term.postings {
                        set.insert(*doc_id);
                    }
                }
            }
            Self::Phrase { matches, .. } => {
                for matched in matches {
                    set.insert(matched.doc_id);
                }
            }
        }
        set
    }
}

/// A boolean intermediate set together with its live segment reservation.
struct ReservedSet {
    set: BTreeSet<u64>,
    entries: u64,
}

impl ReservedSet {
    fn release(self, ledger: &mut SegmentCandidateLedger<'_>) -> SearchResult<()> {
        // Drop the set before releasing its ledger reservation so the release is
        // observably tied to the storage death.
        let ReservedSet { set, entries } = self;
        drop(set);
        let bytes = bytes_for_count(entries, SET_BYTES_PER_ENTRY)?;
        ledger.release(entries, bytes)
    }
}

/// Bitmap positions inspected per cancellation poll while the postings-driven
/// path counts effective-live documents (PR 15E Phase 4).
const EXAMINATION_COUNT_CHUNK: usize = 4096;

/// Reuse the query-local, verified effective-live count for the unchanged
/// logical examination charge on the strict postings-driven path.
///
/// Poll exactly as the previous bitmap recount: once before processing,
/// once for each physical 4096-slot chunk, and once afterward. No bitmap
/// element is read here; `compute_stats` already counted the same immutable data.
fn effective_live_examination_count(
    live: &[bool],
    verified_live_count: u64,
    meter: &MixedWorkMeter<'_>,
) -> SearchResult<u64> {
    meter.check_cancelled()?;
    for _ in live.chunks(EXAMINATION_COUNT_CHUNK) {
        meter.check_cancelled()?;
    }
    meter.check_cancelled()?;
    Ok(verified_live_count)
}

/// Execute a compiled query against an immutable snapshot.
pub(crate) fn execute_search(
    snapshot: &ReaderSnapshot,
    compiled: &CompiledQuery,
    search_limits: &SearchLimits,
    top_k: TopK,
    cancel: &dyn Cancellation,
) -> SearchResult<SearchResponse> {
    let mut work = SearchWork::new(search_limits.max_total_work_units(), cancel)
        .with_scanned_limit(search_limits.max_scanned_posting_occurrences());
    work.check_cancelled()?;

    // Open every segment once for the whole search. The guarded readers hold a
    // bounded encoded-byte reservation and are released by RAII on any exit.
    let mut guards = Vec::new();
    guards
        .try_reserve_exact(snapshot.segment_count())
        .map_err(|_| SearchError::ResourceLimit {
            limit: search_limits.max_segment_candidate_entries(),
            requested: snapshot.segment_count() as u64,
        })?;
    for index in 0..snapshot.segment_count() {
        guards.push(snapshot.open_segment_reader(index)?);
    }
    let readers: Vec<&SegmentReader> = guards.iter().map(|guard| guard.reader()).collect();
    for reader in &readers {
        if reader.schema() != &compiled.codec {
            return Err(SearchError::CorruptIndex {
                detail: "segment schema/analyzer bindings do not match the supplied schema"
                    .to_owned(),
            });
        }
    }

    let mut live: Vec<Rc<Vec<bool>>> = Vec::new();
    live.try_reserve_exact(readers.len())
        .map_err(|_| SearchError::ResourceLimit {
            limit: search_limits.max_segment_candidate_entries(),
            requested: readers.len() as u64,
        })?;
    for (index, reader) in readers.iter().enumerate() {
        live.push(snapshot.effective_live_docs(index, reader)?);
    }

    let expansion = expand_query(&readers, compiled, search_limits, &mut work, cancel)?;
    let stats = compute_stats(
        &readers,
        &live,
        &compiled.scoring_field_ids,
        expansion.positive_terms(),
        search_limits,
        &mut work,
        cancel,
    )?;

    let mut budget = CandidateBudget::new(search_limits);
    let mut global: BTreeMap<DocumentKey, f64> = BTreeMap::new();
    for (segment_index, reader) in readers.iter().enumerate() {
        work.check_cancelled()?;
        let batch = execute_segment(
            reader,
            compiled,
            &stats,
            &expansion,
            &live[segment_index],
            segment_index,
            &mut work,
            &mut budget,
            cancel,
        )?;
        // The batch bytes are already charged to `global_bytes`; moving keys into
        // the global map does not change the accounting and must not re-reserve.
        let SegmentResults {
            entries,
            reserved_bytes: _reserved_bytes,
        } = batch;
        for (key, score) in entries {
            work.check_cancelled()?;
            if global.contains_key(&key) {
                return Err(SearchError::CorruptIndex {
                    detail: format!(
                        "duplicate live document key across segments: {}",
                        key.as_str()
                    ),
                });
            }
            global.insert(key, score);
        }
    }

    let total_hits = global.len() as u64;
    let mut selector = TopKSelector::new(top_k.limit, search_limits.max_topk_heap_bytes())?;
    for (key, score) in global {
        selector.push(key, score)?;
    }
    let hits = selector
        .finish()
        .into_iter()
        .map(|(key, score)| SearchHit { key, score })
        .collect();
    Ok(SearchResponse {
        hits,
        total_hits,
        generation: snapshot.generation(),
        view_ordinal: snapshot.view_ordinal(),
    })
}

/// Evaluate and score one segment, returning its resolved logical keys and scores
/// whose byte reservation has already been transferred to global ownership.
///
/// All segment temporaries and their reservations are explicitly released inside
/// this function; the output batch reservation is transferred to `global_bytes`
/// before returning. `finish` only verifies that no segment reservation remains.
/// The caller must never re-reserve the batch bytes.
#[allow(clippy::too_many_arguments)]
fn execute_segment(
    reader: &SegmentReader,
    compiled: &CompiledQuery,
    stats: &SnapshotStats<'_>,
    expansion: &Expansion,
    live: &[bool],
    segment_index: usize,
    work: &mut SearchWork<'_>,
    budget: &mut CandidateBudget,
    cancel: &dyn Cancellation,
) -> SearchResult<SegmentResults> {
    let mut ledger = SegmentCandidateLedger::new(budget)?;
    let outcome = execute_segment_inner(
        reader,
        compiled,
        stats,
        expansion,
        live,
        segment_index,
        work,
        &mut ledger,
        cancel,
    );
    match outcome {
        Ok((results, charges)) => {
            // Transfer before closing the segment: the output batch is never
            // uncharged between segment and global ownership.
            ledger.transfer_to_global(charges.entries, charges.bytes)?;
            ledger.finish()?;
            Ok(SegmentResults {
                entries: results,
                reserved_bytes: charges.bytes,
            })
        }
        // The ledger's `Drop` releases every outstanding segment reservation.
        Err(error) => Err(error),
    }
}

#[allow(clippy::too_many_arguments)]
fn execute_segment_inner(
    reader: &SegmentReader,
    compiled: &CompiledQuery,
    stats: &SnapshotStats<'_>,
    expansion: &Expansion,
    live: &[bool],
    segment_index: usize,
    work: &mut SearchWork<'_>,
    ledger: &mut SegmentCandidateLedger<'_>,
    cancel: &dyn Cancellation,
) -> SearchResult<(Vec<(DocumentKey, f64)>, Charges)> {
    // 1. Live-document universe: charged, alive through `eval_node`.
    let live_count = live.iter().filter(|flag| **flag).count() as u64;
    let live_bytes = bytes_for_count(live_count, LIVE_SET_BYTES_PER_ENTRY)?;
    ledger.reserve(live_count, live_bytes)?;
    let live_set: BTreeSet<u64> = live
        .iter()
        .enumerate()
        .filter_map(|(index, flag)| flag.then_some(index as u64))
        .collect();

    // 2. Retained leaf postings/matches: charged, alive through `score_segment`.
    let (leaf_data, leaf_charges) = build_leaf_data(
        reader,
        &compiled.leaves,
        expansion,
        segment_index,
        live,
        work,
        ledger,
        None,
        cancel,
    )?;

    // 3. Boolean result set: charged until scoring consumes it.
    let matches = eval_node(&compiled.root, &leaf_data, &live_set, ledger, work)?;

    // `live_set`'s last use is `eval_node`; drop before releasing its charge.
    drop(live_set);
    ledger.release(live_count, live_bytes)?;

    // 4. Scored map: charged until doc-id-to-key conversion completes.
    let (scored, scored_charges) = score_segment(
        matches.set.iter(), // ONLY change from &matches.set
        &leaf_data,
        stats,
        segment_index,
        &compiled.positive_leaf_indices,
        ledger,
        None,
    )?;

    // `matches` and `leaf_data`'s last use is `score_segment`.
    matches.release(ledger)?;
    drop(leaf_data);
    ledger.release(leaf_charges.entries, leaf_charges.bytes)?;

    // 5. Output batch: segment-owned until `execute_segment` transfers it.
    let mut results: Vec<(DocumentKey, f64)> = Vec::new();
    results
        .try_reserve_exact(scored.len())
        .map_err(|_| SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    let mut result_charges = Charges::ZERO;
    for (doc_id, score) in scored {
        work.check_cancelled()?;
        let key = reader.doc_key(doc_id)?;
        let bytes = bytes_for_key(&key)?;
        ledger.reserve(1, bytes)?;
        result_charges = result_charges.add(1, bytes)?;
        results.push((key, score));
    }
    // The scored map was consumed by the loop; release its charge now.
    ledger.release(scored_charges.entries, scored_charges.bytes)?;

    Ok((results, result_charges))
}

#[allow(clippy::too_many_arguments)]
fn build_leaf_data(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    segment_index: usize,
    live: &[bool],
    work: &mut SearchWork<'_>,
    ledger: &mut SegmentCandidateLedger<'_>,
    mut memory: Option<&mut (dyn MemoryCharge + '_)>,
    cancel: &dyn Cancellation,
) -> SearchResult<(Vec<LeafData>, Charges)> {
    let mut charges = Charges::ZERO;
    let mut data = Vec::new();
    data.try_reserve_exact(leaves.len())
        .map_err(|_| SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: leaves.len() as u64,
        })?;
    for (leaf_index, leaf) in leaves.iter().enumerate() {
        work.check_cancelled()?;
        match leaf {
            CompiledLeaf::Term { field_id, terms } => {
                let mut collected = Vec::new();
                for term in terms {
                    let mut postings_list = Vec::new();
                    if let Some(postings) = reader.postings(*field_id, term)? {
                        let mut postings = postings.into_doc_freq();
                        while let Some(posting) = postings.next_with(cancel)? {
                            work.charge_scanned(posting.freq)?;
                            let is_live = *live
                                .get(usize::try_from(posting.doc_id).unwrap_or(usize::MAX))
                                .ok_or_else(|| SearchError::CorruptIndex {
                                    detail: "posting doc id is out of range".to_owned(),
                                })?;
                            if is_live {
                                ledger.reserve_with_memory(
                                    1,
                                    TERM_POSTING_BYTES,
                                    memory.as_deref_mut(),
                                )?;
                                charges = charges.add(1, TERM_POSTING_BYTES)?;
                                postings_list.push((posting.doc_id, posting.freq));
                            }
                        }
                    }
                    collected.push(TermPostings {
                        term: term.clone(),
                        postings: postings_list,
                    });
                }
                data.push(LeafData::Term {
                    field_id: *field_id,
                    terms: collected,
                });
            }
            CompiledLeaf::MultiTerm { field_id, .. } => {
                let terms = expansion
                    .terms_for(segment_index, leaf_index)
                    .ok_or_else(|| SearchError::CorruptIndex {
                        detail: "multi-term leaf was not expanded before execution".to_owned(),
                    })?;
                let entries = reader
                    .dictionary()
                    .and_then(|dictionary| dictionary.field(*field_id));
                let mut collected = Vec::new();
                collected.try_reserve_exact(terms.len()).map_err(|_| {
                    SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: terms.len() as u64,
                    }
                })?;
                for term_id in terms {
                    let term = expansion.term(*term_id);
                    let entry =
                        entries.and_then(|entries| super::expand::lookup_entry(entries, term));
                    let mut postings_list = Vec::new();
                    if let Some(entry) = entry {
                        let mut postings = reader.postings_for_entry(entry)?.into_doc_freq();
                        while let Some(posting) = postings.next_with(cancel)? {
                            work.charge_scanned(posting.freq)?;
                            let is_live = *live
                                .get(usize::try_from(posting.doc_id).unwrap_or(usize::MAX))
                                .ok_or_else(|| SearchError::CorruptIndex {
                                    detail: "posting doc id is out of range".to_owned(),
                                })?;
                            if is_live {
                                ledger.reserve_with_memory(
                                    1,
                                    TERM_POSTING_BYTES,
                                    memory.as_deref_mut(),
                                )?;
                                charges = charges.add(1, TERM_POSTING_BYTES)?;
                                postings_list.push((posting.doc_id, posting.freq));
                            }
                        }
                    }
                    collected.push(TermPostings {
                        term: term.to_owned(),
                        postings: postings_list,
                    });
                }
                data.push(LeafData::Term {
                    field_id: *field_id,
                    terms: collected,
                });
            }
            CompiledLeaf::Phrase { field_id, tokens } => {
                let (matches, phrase_charges) = build_phrase(
                    reader,
                    *field_id,
                    tokens,
                    live,
                    work,
                    ledger,
                    memory.as_deref_mut(),
                    cancel,
                )?;
                charges = charges.add(phrase_charges.entries, phrase_charges.bytes)?;
                data.push(LeafData::Phrase {
                    field_id: *field_id,
                    matches,
                });
            }
        }
    }
    Ok((data, charges))
}

#[allow(clippy::too_many_arguments)]
fn build_phrase(
    reader: &SegmentReader,
    field_id: u32,
    tokens: &[PhraseToken],
    live: &[bool],
    work: &mut SearchWork<'_>,
    ledger: &mut SegmentCandidateLedger<'_>,
    mut memory: Option<&mut (dyn MemoryCharge + '_)>,
    cancel: &dyn Cancellation,
) -> SearchResult<(Vec<PhraseMatch>, Charges)> {
    if tokens.is_empty() {
        return Ok((Vec::new(), Charges::ZERO));
    }
    // Scratch postings are charged separately and released as soon as `distinct`
    // dies, before any sibling phrase leaf is processed.
    let mut scratch = Charges::ZERO;
    // Distinct term data in first-appearance order.
    let mut distinct: Vec<PhraseTermData> = Vec::new();
    let mut index_of: BTreeMap<&str, usize> = BTreeMap::new();
    for token in tokens {
        if index_of.contains_key(token.term.as_str()) {
            continue;
        }
        let index = distinct.len();
        index_of.insert(token.term.as_str(), index);
        let mut term_data = PhraseTermData {
            term: token.term.clone(),
            ..PhraseTermData::default()
        };
        if let Some(mut postings) = reader.postings(field_id, &token.term)? {
            if !postings.is_positional() {
                return Err(SearchError::CorruptIndex {
                    detail: "phrase requires positional postings".to_owned(),
                });
            }
            while let Some(posting) = postings.next_with(cancel)? {
                work.charge_scanned(posting.freq)?;
                let is_live = *live
                    .get(usize::try_from(posting.doc_id).unwrap_or(usize::MAX))
                    .ok_or_else(|| SearchError::CorruptIndex {
                        detail: "posting doc id is out of range".to_owned(),
                    })?;
                if !is_live {
                    continue;
                }
                ledger.reserve_with_memory(1, PHRASE_DOC_BYTES, memory.as_deref_mut())?;
                scratch = scratch.add(1, PHRASE_DOC_BYTES)?;
                term_data.docs.push(posting.doc_id);
                let occurrences = posting.occurrences.len() as u64;
                let occurrence_bytes = bytes_for_count(occurrences, phrase_occurrence_bytes())?;
                ledger.reserve_with_memory(occurrences, occurrence_bytes, memory.as_deref_mut())?;
                scratch = scratch.add(occurrences, occurrence_bytes)?;
                term_data
                    .occurrences
                    .insert(posting.doc_id, posting.occurrences);
            }
        }
        distinct.push(term_data);
    }
    // Worst-case match reservation: at most the smallest distinct term doc set,
    // each with at most `distinct.len()` constituent term frequencies.
    let candidate_upper = distinct
        .iter()
        .map(|data| data.docs.len() as u64)
        .min()
        .unwrap_or(0);
    let per_match_bytes = PHRASE_MATCH_BYTES
        .checked_add(
            PHRASE_MATCH_TERM_BYTES
                .checked_mul(distinct.len() as u64)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?,
        )
        .ok_or(SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    let upper_bytes = bytes_for_count(candidate_upper, per_match_bytes)?;
    ledger.reserve_with_memory(candidate_upper, upper_bytes, memory.as_deref_mut())?;

    let per_token: Vec<&PhraseTermData> = tokens
        .iter()
        .map(|token| {
            let index = index_of.get(token.term.as_str()).copied().unwrap_or(0);
            &distinct[index]
        })
        .collect();
    // Bounded phrase-verification scratch owns exactly the internal vectors; the
    // caller's worst-case match reservation below covers retained
    // `matches`/`term_freqs` and is not charged again.
    let matches = {
        let mut phrase_scratch = PhraseScratch::new(ledger);
        let result = match_phrase(
            tokens,
            &per_token,
            work,
            cancel,
            &mut phrase_scratch,
            memory.as_deref_mut(),
        );
        // Release all phrase scratch before returning; Drop is the safety net.
        drop(phrase_scratch);
        result?
    };

    // Release the unused portion of the worst-case match reservation; the actual
    // match bytes remain charged as part of `LeafData`.
    let actual_entries = matches.len() as u64;
    let mut actual_bytes = 0u64;
    for matched in &matches {
        let term_bytes = PHRASE_MATCH_TERM_BYTES
            .checked_mul(matched.term_freqs.len() as u64)
            .ok_or(SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
        actual_bytes = actual_bytes
            .checked_add(PHRASE_MATCH_BYTES)
            .and_then(|value| value.checked_add(term_bytes))
            .ok_or(SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
    }
    if candidate_upper > actual_entries || upper_bytes > actual_bytes {
        ledger.release_with_memory(
            candidate_upper - actual_entries,
            upper_bytes - actual_bytes,
            memory.as_deref_mut(),
        )?;
    }
    // End all borrows of `distinct`/`index_of`, then drop the scratch storage
    // before releasing its reservation.
    drop(per_token);
    drop(index_of);
    drop(distinct);
    ledger.release_with_memory(scratch.entries, scratch.bytes, memory)?;
    Ok((
        matches,
        Charges {
            entries: actual_entries,
            bytes: actual_bytes,
        },
    ))
}

fn eval_node(
    node: &CompiledNode,
    leaf_data: &[LeafData],
    live_set: &BTreeSet<u64>,
    ledger: &mut SegmentCandidateLedger<'_>,
    work: &mut SearchWork<'_>,
) -> SearchResult<ReservedSet> {
    match node {
        CompiledNode::MatchAll => {
            work.check_cancelled()?;
            let entries = live_set.len() as u64;
            ledger.reserve(entries, bytes_for_count(entries, SET_BYTES_PER_ENTRY)?)?;
            Ok(ReservedSet {
                set: live_set.clone(),
                entries,
            })
        }
        CompiledNode::Leaf(index) => {
            work.check_cancelled()?;
            let data = leaf_data
                .get(*index)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "compiled leaf index is out of range".to_owned(),
                })?;
            let upper = data.entry_upper_bound();
            ledger.reserve(upper, bytes_for_count(upper, SET_BYTES_PER_ENTRY)?)?;
            let set = data.match_set();
            let actual = set.len() as u64;
            if upper > actual {
                ledger.release(
                    upper - actual,
                    bytes_for_count(upper - actual, SET_BYTES_PER_ENTRY)?,
                )?;
            }
            Ok(ReservedSet {
                set,
                entries: actual,
            })
        }
        CompiledNode::And(children) => {
            let mut iter = children.iter();
            let Some(first) = iter.next() else {
                return Ok(ReservedSet {
                    set: BTreeSet::new(),
                    entries: 0,
                });
            };
            let mut accumulator = eval_node(first, leaf_data, live_set, ledger, work)?;
            for child in iter {
                work.check_cancelled()?;
                let next = eval_node(child, leaf_data, live_set, ledger, work)?;
                let upper = accumulator.entries.min(next.entries);
                ledger.reserve(upper, bytes_for_count(upper, SET_BYTES_PER_ENTRY)?)?;
                let set = intersection(&accumulator.set, &next.set);
                let actual = set.len() as u64;
                if upper > actual {
                    ledger.release(
                        upper - actual,
                        bytes_for_count(upper - actual, SET_BYTES_PER_ENTRY)?,
                    )?;
                }
                accumulator.release(ledger)?;
                next.release(ledger)?;
                accumulator = ReservedSet {
                    set,
                    entries: actual,
                };
                if accumulator.set.is_empty() {
                    break;
                }
            }
            Ok(accumulator)
        }
        CompiledNode::Or(children) => {
            let mut accumulator = ReservedSet {
                set: BTreeSet::new(),
                entries: 0,
            };
            for child in children {
                work.check_cancelled()?;
                let next = eval_node(child, leaf_data, live_set, ledger, work)?;
                let upper = next.entries;
                ledger.reserve(upper, bytes_for_count(upper, SET_BYTES_PER_ENTRY)?)?;
                let before = accumulator.set.len() as u64;
                let ReservedSet {
                    set: mut next_set,
                    entries: next_entries,
                } = next;
                accumulator.set.append(&mut next_set);
                let added = accumulator.set.len() as u64 - before;
                if upper > added {
                    ledger.release(
                        upper - added,
                        bytes_for_count(upper - added, SET_BYTES_PER_ENTRY)?,
                    )?;
                }
                ledger.release(
                    next_entries,
                    bytes_for_count(next_entries, SET_BYTES_PER_ENTRY)?,
                )?;
                accumulator.entries = accumulator.set.len() as u64;
            }
            Ok(accumulator)
        }
        CompiledNode::Not(inner) => {
            work.check_cancelled()?;
            let inner_set = eval_node(inner, leaf_data, live_set, ledger, work)?;
            let upper = live_set.len() as u64;
            ledger.reserve(upper, bytes_for_count(upper, SET_BYTES_PER_ENTRY)?)?;
            let complement: BTreeSet<u64> = live_set.difference(&inner_set.set).copied().collect();
            let actual = complement.len() as u64;
            if upper > actual {
                ledger.release(
                    upper - actual,
                    bytes_for_count(upper - actual, SET_BYTES_PER_ENTRY)?,
                )?;
            }
            inner_set.release(ledger)?;
            Ok(ReservedSet {
                set: complement,
                entries: actual,
            })
        }
    }
}

fn intersection(left: &BTreeSet<u64>, right: &BTreeSet<u64>) -> BTreeSet<u64> {
    if left.len() <= right.len() {
        left.iter()
            .filter(|value| right.contains(*value))
            .copied()
            .collect()
    } else {
        right
            .iter()
            .filter(|value| left.contains(*value))
            .copied()
            .collect()
    }
}

fn score_segment<'a>(
    matches: impl ExactSizeIterator<Item = &'a u64>,
    leaf_data: &[LeafData],
    stats: &SnapshotStats<'_>,
    segment_index: usize,
    positive: &BTreeSet<usize>,
    ledger: &mut SegmentCandidateLedger<'_>,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
) -> SearchResult<(BTreeMap<u64, f64>, Charges)> {
    #[cfg(test)]
    test_observation::record_generic_scorer_call();
    let entries = matches.len() as u64;
    let bytes = bytes_for_count(entries, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(entries, bytes, memory)?;
    let charges = Charges { entries, bytes };
    let mut scores: BTreeMap<u64, f64> = matches.map(|doc| (*doc, 0.0)).collect();
    if scores.is_empty() {
        return Ok((scores, charges));
    }

    // A distinct `(field, term)` contributes **once per document**, even when
    // several positive leaves contain it (e.g. `Term(rust) OR Prefix(ru)`).
    // Term-like leaves own their terms over phrase leaves because their postings
    // cover every document that contains the term; if a term appears only in
    // phrase leaves the first one owns it.
    let mut owner: BTreeMap<(u32, &str), usize> = BTreeMap::new();
    for (index, leaf) in leaf_data.iter().enumerate() {
        if !positive.contains(&index) {
            continue;
        }
        if let LeafData::Term { field_id, terms } = leaf {
            for term in terms {
                owner
                    .entry((*field_id, term.term.as_str()))
                    .or_insert(index);
            }
        }
    }
    for (index, leaf) in leaf_data.iter().enumerate() {
        if !positive.contains(&index) {
            continue;
        }
        if let LeafData::Phrase { field_id, matches } = leaf {
            for phrase_match in matches {
                for (term, _) in &phrase_match.term_freqs {
                    owner.entry((*field_id, term.as_str())).or_insert(index);
                }
            }
        }
    }

    for (index, leaf) in leaf_data.iter().enumerate() {
        // Only scoring-eligible (positive/even-`Not`-parity) leaves contribute.
        if !positive.contains(&index) {
            continue;
        }
        match leaf {
            LeafData::Term { field_id, terms } => {
                let Some(field_stats) = stats.field(*field_id) else {
                    continue;
                };
                for term in terms {
                    if owner.get(&(*field_id, term.term.as_str())) != Some(&index) {
                        continue;
                    }
                    for (doc_id, freq) in &term.postings {
                        if let Some(current) = scores.get_mut(doc_id) {
                            let dl = field_stats.length(segment_index, *doc_id);
                            let contribution = field_stats.bm25_score(&term.term, *freq, dl)?;
                            *current += contribution;
                        }
                    }
                }
            }
            LeafData::Phrase { field_id, matches } => {
                let Some(field_stats) = stats.field(*field_id) else {
                    continue;
                };
                for phrase_match in matches {
                    let Some(current) = scores.get_mut(&phrase_match.doc_id) else {
                        continue;
                    };
                    for (term, freq) in &phrase_match.term_freqs {
                        if owner.get(&(*field_id, term.as_str())) != Some(&index) {
                            continue;
                        }
                        let dl = field_stats.length(segment_index, phrase_match.doc_id);
                        let contribution = field_stats.bm25_score(term, *freq, dl)?;
                        *current += contribution;
                    }
                }
            }
        }
    }
    Ok((scores, charges))
}

/// Strict single-positive-term scorer: consume exact `(doc_id, freq)` candidates
/// collected after matching and logical admissions, and emit the final scores
/// directly (no full-M scored map and no second postings traversal).
#[allow(clippy::too_many_arguments)]
fn score_single_term_candidates(
    matches: &[(u64, u64)],
    field_id: u32,
    term: &str,
    stats: &SnapshotStats<'_>,
    segment_index: usize,
    positive: &BTreeSet<usize>,
    ledger: &mut SegmentCandidateLedger<'_>,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
) -> SearchResult<(Vec<(u64, f64)>, Charges)> {
    #[cfg(test)]
    test_observation::record_single_term_scorer_call();

    // Preserve the old scored-map admission even without the physical map.
    let entries = matches.len() as u64;
    let bytes = bytes_for_count(entries, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(entries, bytes, memory)?;
    let charges = Charges { entries, bytes };

    // Direct final output: no scored BTreeMap, no second postings walk.
    let mut scored: Vec<(u64, f64)> = Vec::with_capacity(matches.len());
    let field_stats = if positive.contains(&0) {
        stats.field(field_id)
    } else {
        None
    };

    for &(doc_id, freq) in matches {
        let mut score = 0.0_f64;
        if let Some(field) = field_stats {
            let dl = field.length(segment_index, doc_id);
            let contribution = field.bm25_score(term, freq, dl)?;
            // Generic score_segment adds to an initially +0.0 map slot.
            score += contribution;
        }
        scored.push((doc_id, score));
    }
    Ok((scored, charges))
}

/// Move the already decoded and validated sole term's posting Vec into the
/// strict candidate owner. Call only after every matching callback completed.
fn take_strict_one_term_postings(
    leaf_data: &mut [LeafData],
    typed_examination: bool,
) -> SearchResult<Vec<(u64, u64)>> {
    match leaf_data {
        [LeafData::Term { terms, .. }] if terms.len() == 1 && !typed_examination => {
            #[cfg(test)]
            test_observation::record_postings_move();
            Ok(std::mem::take(&mut terms[0].postings))
        }
        _ => Err(SearchError::CorruptIndex {
            detail: "single-term postings eligibility mismatch".to_owned(),
        }),
    }
}

/// Record whether an eligible caller ever rejected a decoded posting.
/// Normally the B1 callback accepts all; only a rejection needs a copied Vec.
#[derive(Default)]
struct StrictTermMatchSelection {
    saw_rejection: bool,
    copied_matches: Vec<(u64, u64)>,
}

impl StrictTermMatchSelection {
    fn observe(&mut self, postings: &[(u64, u64)], index: usize, accepted: bool) {
        if !accepted {
            if !self.saw_rejection {
                // All positions before the first rejection were accepted.
                self.copied_matches.extend_from_slice(&postings[..index]);
                self.saw_rejection = true;
            }
        } else if self.saw_rejection {
            self.copied_matches.push(postings[index]);
        }
    }

    fn finish(
        self,
        leaf_data: &mut [LeafData],
        typed_examination: bool,
    ) -> SearchResult<Vec<(u64, u64)>> {
        if self.saw_rejection {
            #[cfg(test)]
            test_observation::record_postings_rejection_fallback();
            Ok(self.copied_matches)
        } else {
            take_strict_one_term_postings(leaf_data, typed_examination)
        }
    }
}

/// Test-only observation of membership callbacks.
///
/// This is deliberately thread-local and compiled only in test builds. It
/// proves early-stop behavior without adding a production counter or exposing a
/// test-only public API.
#[cfg(test)]
pub(crate) mod test_observation {
    use std::cell::Cell;

    thread_local! {
        static CALLBACKS: Cell<usize> = const { Cell::new(0) };
        static PREDICATE_CALLS: Cell<usize> = const { Cell::new(0) };
        static TERM_MEMBERSHIP_LOOKUPS: Cell<usize> = const { Cell::new(0) };
        static GENERIC_SCORER_CALLS: Cell<usize> = const { Cell::new(0) };
        static SINGLE_TERM_SCORER_CALLS: Cell<usize> = const { Cell::new(0) };
        static POSTINGS_MOVES: Cell<usize> = const { Cell::new(0) };
        static POSTINGS_REJECTION_FALLBACKS: Cell<usize> = const { Cell::new(0) };
    }

    pub(crate) fn reset() {
        CALLBACKS.with(|value| value.set(0));
    }

    pub(crate) fn count() -> usize {
        CALLBACKS.with(Cell::get)
    }

    pub(crate) fn record() {
        CALLBACKS.with(|value| value.set(value.get() + 1));
    }

    /// PR 15E Phase 4 witness: how many times the membership predicate was
    /// invoked. Compiled out of production and benchmark builds.
    pub(crate) fn reset_predicate_calls() {
        PREDICATE_CALLS.with(|value| value.set(0));
    }

    pub(crate) fn predicate_calls() -> usize {
        PREDICATE_CALLS.with(Cell::get)
    }

    pub(crate) fn record_predicate_call() {
        PREDICATE_CALLS.with(|value| value.set(value.get() + 1));
    }

    /// PERF-05-B1 witness: how many times a positive lexical `Term` leaf performed
    /// its binary-search membership proof. Compiled out of production builds.
    pub(crate) fn reset_term_membership_lookups() {
        TERM_MEMBERSHIP_LOOKUPS.with(|value| value.set(0));
    }

    pub(crate) fn term_membership_lookups() -> usize {
        TERM_MEMBERSHIP_LOOKUPS.with(Cell::get)
    }

    pub(crate) fn record_term_membership_lookup() {
        TERM_MEMBERSHIP_LOOKUPS.with(|value| value.set(value.get() + 1));
    }

    /// PERF-05-B4 witness: which scorer the unified evaluator selected.
    pub(crate) fn reset_scorer_calls() {
        GENERIC_SCORER_CALLS.with(|v| v.set(0));
        SINGLE_TERM_SCORER_CALLS.with(|v| v.set(0));
    }

    pub(crate) fn generic_scorer_calls() -> usize {
        GENERIC_SCORER_CALLS.with(Cell::get)
    }

    pub(crate) fn single_term_scorer_calls() -> usize {
        SINGLE_TERM_SCORER_CALLS.with(Cell::get)
    }

    pub(crate) fn record_generic_scorer_call() {
        GENERIC_SCORER_CALLS.with(|v| v.set(v.get() + 1));
    }

    pub(crate) fn record_single_term_scorer_call() {
        SINGLE_TERM_SCORER_CALLS.with(|v| v.set(v.get() + 1));
    }

    /// PERF-05-B5 witness: strict-term ownership handoff path selection.
    pub(crate) fn reset_postings_handoff() {
        POSTINGS_MOVES.with(|v| v.set(0));
        POSTINGS_REJECTION_FALLBACKS.with(|v| v.set(0));
    }

    pub(crate) fn postings_moves() -> usize {
        POSTINGS_MOVES.with(Cell::get)
    }

    pub(crate) fn postings_rejection_fallbacks() -> usize {
        POSTINGS_REJECTION_FALLBACKS.with(Cell::get)
    }

    pub(crate) fn record_postings_move() {
        POSTINGS_MOVES.with(|v| v.set(v.get() + 1));
    }

    pub(crate) fn record_postings_rejection_fallback() {
        POSTINGS_REJECTION_FALLBACKS.with(|v| v.set(v.get() + 1));
    }
}

/// PERF-06-C2 test-only structural witnesses and one synthetic score-fault seam.
///
/// Deliberately thread-local and compiled out of every non-test build: no
/// production counter, no runtime strategy flag, no environment variable and no
/// `tracing` dependency. The score fault injector deliberately does **not** modify
/// [`super::score::FieldStats::bm25_score`]; it only proves the C2 error/heap
/// precedence structure and its evidence is labelled `INJECTED_C2_ONLY`.
#[cfg(test)]
pub(crate) mod c2_observation {
    use std::cell::Cell;

    thread_local! {
        static STRICT_EVALUATOR_CALLS: Cell<usize> = const { Cell::new(0) };
        static STRICT_MEMBERSHIP_OBSERVATIONS: Cell<usize> = const { Cell::new(0) };
        static CONVERTED_ROWS: Cell<usize> = const { Cell::new(0) };
        static CALLBACKS: Cell<usize> = const { Cell::new(0) };
        static INPLACE_POINTER: Cell<usize> = const { Cell::new(0) };
        static INPLACE_CAPACITY: Cell<usize> = const { Cell::new(0) };
        static INPLACE_PRESERVED: Cell<bool> = const { Cell::new(false) };
        static SCORE_FAILURE_DOC: Cell<Option<u64>> = const { Cell::new(None) };
    }

    pub(crate) fn reset() {
        STRICT_EVALUATOR_CALLS.with(|value| value.set(0));
        STRICT_MEMBERSHIP_OBSERVATIONS.with(|value| value.set(0));
        CONVERTED_ROWS.with(|value| value.set(0));
        CALLBACKS.with(|value| value.set(0));
        INPLACE_POINTER.with(|value| value.set(0));
        INPLACE_CAPACITY.with(|value| value.set(0));
        INPLACE_PRESERVED.with(|value| value.set(false));
        SCORE_FAILURE_DOC.with(|value| value.set(None));
    }

    pub(crate) fn strict_evaluator_calls() -> usize {
        STRICT_EVALUATOR_CALLS.with(Cell::get)
    }

    pub(crate) fn strict_membership_observations() -> usize {
        STRICT_MEMBERSHIP_OBSERVATIONS.with(Cell::get)
    }

    pub(crate) fn converted_rows() -> usize {
        CONVERTED_ROWS.with(Cell::get)
    }

    pub(crate) fn callbacks() -> usize {
        CALLBACKS.with(Cell::get)
    }

    /// Whether the sole decoded posting vector kept both its address and its
    /// capacity across the in-place frequency -> score-bits rewrite.
    pub(crate) fn inplace_preserved() -> bool {
        INPLACE_PRESERVED.with(Cell::get)
    }

    pub(crate) fn record_strict_evaluator_call() {
        STRICT_EVALUATOR_CALLS.with(|value| value.set(value.get() + 1));
    }

    pub(crate) fn record_strict_membership_observation() {
        STRICT_MEMBERSHIP_OBSERVATIONS.with(|value| value.set(value.get() + 1));
    }

    pub(crate) fn record_callback() {
        CALLBACKS.with(|value| value.set(value.get() + 1));
    }

    pub(crate) fn record_inplace_start(postings: &Vec<(u64, u64)>) {
        INPLACE_POINTER.with(|value| value.set(postings.as_ptr() as usize));
        INPLACE_CAPACITY.with(|value| value.set(postings.capacity()));
        INPLACE_PRESERVED.with(|value| value.set(false));
    }

    pub(crate) fn record_inplace_finish(postings: &Vec<(u64, u64)>) {
        CONVERTED_ROWS.with(|value| value.set(value.get() + postings.len()));
        let same_pointer = INPLACE_POINTER.with(Cell::get) == postings.as_ptr() as usize;
        let same_capacity = INPLACE_CAPACITY.with(Cell::get) == postings.capacity();
        INPLACE_PRESERVED.with(|value| value.set(same_pointer && same_capacity));
    }

    /// Whether the armed synthetic score fault targets this document.
    pub(crate) fn injected_score_failure(doc_id: u64) -> bool {
        SCORE_FAILURE_DOC.with(Cell::get) == Some(doc_id)
    }

    /// Whether the synthetic C2 score fault is armed at all, without resetting it.
    ///
    /// PERF-06-C3 uses this to force the eager C2 route so an armed synthetic
    /// fault still surfaces exactly at its accepted score checkpoint.
    pub(crate) fn score_failure_armed() -> bool {
        SCORE_FAILURE_DOC.with(Cell::get).is_some()
    }

    /// Thread-local RAII arm for the synthetic C2 score fault.
    pub(crate) struct ScoreFailureArm;

    impl ScoreFailureArm {
        pub(crate) fn arm(doc_id: u64) -> Self {
            SCORE_FAILURE_DOC.with(|value| value.set(Some(doc_id)));
            Self
        }
    }

    impl Drop for ScoreFailureArm {
        fn drop(&mut self) {
            SCORE_FAILURE_DOC.with(|value| value.set(None));
        }
    }
}

/// Control returned by a membership visitor callback.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum VisitControl {
    /// Continue traversing effective-live documents.
    Continue,
    /// Stop immediately without examining another document.
    Stop,
}

/// Streaming, non-scoring lexical/typed membership visitor.
///
/// This mirrors the setup and accounting of [`evaluate_lexical_with`] but never
/// builds a matched set, never calls [`score_segment`] and never materializes a
/// scored result vector. The caller's `is_match` predicate performs the same
/// lexical/typed membership decision; on a true result `on_match` is invoked
/// immediately with the shared candidate budget so it can apply distinct-key
/// and resource accounting before traversal continues.
///
/// The callback receives the already-borrowed candidate budget because the
/// segment ledger owns it for the duration of the traversal. This preserves one
/// combined candidate budget and prevents a separate-budget cap bypass.
///
/// Traversal iterates `live` directly (PR 15E-B1, B1a) instead of materializing a
/// transient `BTreeSet<u64>` of live document ids. That set had no reader-visible
/// role: it carried neither ordering beyond the snapshot's ascending index order
/// nor any membership semantics, so it is not charged as retained memory
/// anywhere. Only physically retained collections (leaf postings/matches,
/// matched/scored maps, global candidates) remain reserved through the ledger.
#[allow(clippy::too_many_arguments)]
pub(crate) fn visit_lexical_membership_with<F, G>(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    segment_index: usize,
    live: &[bool],
    budget: &mut CandidateBudget,
    meter: &mut MixedWorkMeter<'_>,
    memory: &mut Option<&mut (dyn MemoryCharge + '_)>,
    typed_examination: bool,
    cancel: &dyn Cancellation,
    mut is_match: F,
    mut on_match: G,
) -> SearchResult<VisitControl>
where
    F: FnMut(
        u64,
        &[LeafData],
        &mut MixedWorkMeter<'_>,
        Option<&mut (dyn MemoryCharge + '_)>,
    ) -> SearchResult<bool>,
    G: FnMut(u64, &mut CandidateBudget) -> SearchResult<VisitControl>,
{
    let mut ledger = SegmentCandidateLedger::new(budget)?;
    let (leaf_data, leaf_charges) = {
        let mut work = SearchWork::shared(meter);
        build_leaf_data(
            reader,
            leaves,
            expansion,
            segment_index,
            live,
            &mut work,
            &mut ledger,
            memory.as_deref_mut(),
            cancel,
        )?
    };
    let mut control = VisitControl::Continue;
    // Ascending physical doc-id order, each effective-live document exactly once.
    for (index, flag) in live.iter().enumerate() {
        if !*flag {
            continue;
        }
        let doc_id = index as u64;
        meter.check_cancelled()?;
        if typed_examination {
            meter.charge_typed(1)?;
        } else {
            meter.charge_lexical(1)?;
        }
        let matched = is_match(doc_id, &leaf_data, meter, memory.as_deref_mut())?;
        #[cfg(test)]
        if matched {
            test_observation::record();
        }
        // The ledger owns the sole mutable borrow of the shared budget.
        // Reborrow it only for the callback so one combined cap is kept.
        if matched && on_match(doc_id, &mut *ledger.budget)? == VisitControl::Stop {
            control = VisitControl::Stop;
            break;
        }
    }
    drop(leaf_data);
    ledger.release_with_memory(
        leaf_charges.entries,
        leaf_charges.bytes,
        memory.as_deref_mut(),
    )?;
    Ok(control)
}

/// Reusable per-segment lexical evaluation seam for the unified executor.
///
/// Builds the existing per-leaf postings/phrase data over the effective-live
/// universe, evaluates the caller's combined predicate (`is_match`, which may
/// consult lexical leaf membership via [`LeafData::matches`] and typed leaves),
/// then scores the matched set with the existing positive-leaf [`score_segment`]
/// BM25 path. Negative-only lexical leaves never score. Returns `(doc_id, score)`
/// pairs in ascending doc order.
///
/// Traversal iterates `live` directly (PR 15E-B1, B1a) instead of materializing a
/// transient `BTreeSet<u64>` of live document ids; only retained collections are
/// charged (see [`visit_lexical_membership_with`]).
#[allow(clippy::too_many_arguments)]
pub(crate) fn evaluate_lexical_with<F>(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    stats: &SnapshotStats<'_>,
    positive: &BTreeSet<usize>,
    segment_index: usize,
    live: &[bool],
    budget: &mut CandidateBudget,
    meter: &mut MixedWorkMeter<'_>,
    memory: &mut Option<&mut (dyn MemoryCharge + '_)>,
    typed_examination: bool,
    postings_candidate_eligible: bool,
    cancel: &dyn Cancellation,
    mut is_match: F,
) -> SearchResult<Vec<(u64, f64)>>
where
    F: FnMut(
        u64,
        &[LeafData],
        &mut MixedWorkMeter<'_>,
        Option<&mut (dyn MemoryCharge + '_)>,
    ) -> SearchResult<bool>,
{
    let mut ledger = SegmentCandidateLedger::new(budget)?;
    // The shared-meter borrow is scoped to leaf construction only; the callback
    // below receives the meter directly, so no two mutable borrows overlap.
    let (mut leaf_data, leaf_charges) = {
        let mut work = SearchWork::shared(meter);
        build_leaf_data(
            reader,
            leaves,
            expansion,
            segment_index,
            live,
            &mut work,
            &mut ledger,
            memory.as_deref_mut(),
            cancel,
        )?
    };
    // Both enumerators visit each effective-live physical doc ID once and in
    // strictly ascending order. Keep the old logical SET_BYTES_PER_ENTRY charge.
    let mut matched: Vec<u64> = Vec::new();
    // Only the eligible one-term branch fills this ordered (doc_id, freq) buffer.
    // The generic `matched` Vec stays empty for that branch.
    let mut single_term_matched: Vec<(u64, u64)> = Vec::new();
    if postings_candidate_eligible {
        // Runtime guard (P4-AD-01 clause 6): only exactly one single-analyzed-term
        // leaf with one postings stream may take this branch. Any other shape is an
        // internal invariant mismatch, never a silent partial enumeration.
        let postings = match leaf_data.as_slice() {
            [LeafData::Term { terms, .. }] if terms.len() == 1 && !typed_examination => {
                &terms[0].postings
            }
            _ => {
                return Err(SearchError::CorruptIndex {
                    detail: "single-term postings eligibility mismatch".to_owned(),
                });
            }
        };
        // Preserve the legacy logical charge: one examination per effective-live
        // document, not one per candidate posting and not `postings.len()`.
        let verified_live_count = stats.verified_segment_live_count(segment_index, live.len())?;
        let live_count = effective_live_examination_count(live, verified_live_count, meter)?;
        if live_count > 0 {
            meter.charge_lexical(live_count)?;
        }
        meter.check_cancelled()?;
        // Candidate order is the decoder's strictly ascending, effective-live
        // filtered order: no copy, re-sort, extra set or index seek. Every
        // callback observes the complete original leaf data; the sole posting
        // allocation is moved only after the final callback returns.
        let mut selection = StrictTermMatchSelection::default();
        let mut last_accepted: Option<u64> = None;
        for (index, (doc_id, _freq)) in postings.iter().enumerate() {
            meter.check_cancelled()?;
            #[cfg(test)]
            test_observation::record_predicate_call();
            let accepted = is_match(*doc_id, &leaf_data, meter, memory.as_deref_mut())?;
            if accepted {
                debug_assert!(last_accepted.is_none_or(|last| last < *doc_id));
                last_accepted = Some(*doc_id);
            }
            selection.observe(postings, index, accepted);
        }
        // All callbacks finished while the full original leaf_data remained intact.
        single_term_matched = selection.finish(&mut leaf_data, typed_examination)?;
    } else {
        // Unmodified live-bitmap scan (fallback for every ineligible shape).
        // Ascending physical doc-id order, each effective-live document exactly once.
        for (index, flag) in live.iter().enumerate() {
            if !*flag {
                continue;
            }
            let doc_id = index as u64;
            // Poll cancellation once per examined document (in addition to the
            // interval poll inside `charge`).
            meter.check_cancelled()?;
            // Charge the per-document examination itself so zero-hit, MatchAll and
            // typed-only scans never bypass work accounting. Typed queries charge the
            // typed sub-counter; lexical/neutral scans charge total work only.
            if typed_examination {
                meter.charge_typed(1)?;
            } else {
                meter.charge_lexical(1)?;
            }
            #[cfg(test)]
            test_observation::record_predicate_call();
            if is_match(doc_id, &leaf_data, meter, memory.as_deref_mut())? {
                debug_assert!(matched.last().is_none_or(|last| *last < doc_id));
                matched.push(doc_id);
            }
        }
    }
    let matched_entries = if postings_candidate_eligible {
        single_term_matched.len() as u64
    } else {
        matched.len() as u64
    };
    let matched_bytes = bytes_for_count(matched_entries, SET_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;

    let (scored_vec, scored_charges): (Vec<(u64, f64)>, Charges) = if postings_candidate_eligible {
        // Reconfirm only the already runtime-validated one-term shape.
        let (field_id, term) = match leaf_data.as_slice() {
            [LeafData::Term { field_id, terms }] if terms.len() == 1 && !typed_examination => {
                (*field_id, terms[0].term.as_str())
            }
            _ => {
                return Err(SearchError::CorruptIndex {
                    detail: "single-term postings eligibility mismatch".to_owned(),
                });
            }
        };
        score_single_term_candidates(
            &single_term_matched,
            field_id,
            term,
            stats,
            segment_index,
            positive,
            &mut ledger,
            memory.as_deref_mut(),
        )?
    } else {
        // The existing scorer is unchanged for all other query shapes.
        let (scored, charges) = score_segment(
            matched.iter(),
            &leaf_data,
            stats,
            segment_index,
            positive,
            &mut ledger,
            memory.as_deref_mut(),
        )?;
        (scored.into_iter().collect(), charges)
    };

    // Drop both buffers and decoded leaves before their logical reservations.
    drop(matched);
    drop(single_term_matched);
    drop(leaf_data);
    ledger.release_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;
    ledger.release_with_memory(
        leaf_charges.entries,
        leaf_charges.bytes,
        memory.as_deref_mut(),
    )?;
    ledger.release_with_memory(
        scored_charges.entries,
        scored_charges.bytes,
        memory.as_deref_mut(),
    )?;
    Ok(scored_vec)
}

/// PERF-06-C2: the strict-term, in-place scored-posting executor.
///
/// Preconditions (checked again at runtime, fail-closed):
///
/// * `leaves` is exactly one [`CompiledLeaf::Term`] with exactly one analyzed
///   term, `positive == {0}`, and no typed examination is involved (C2 never
///   admits a typed leaf, so there is no argument for it).
/// * the caller already proved the request-wide C1 eligibility, the request-wide
///   B1 ordinal map is `Ready`, and the effective-live document frequency of that
///   single term exceeds `top_k + 1`.
///
/// Mechanism (see the C2 plan §4.2): the sole validated `(doc_id, freq)` posting
/// allocation produced by [`build_leaf_data`] is kept, every matched document is
/// scored eagerly with the unchanged [`super::score::FieldStats::bm25_score`], and its
/// frequency word is rewritten **in place** as `score.to_bits()`. Only after the
/// whole segment is scored, every logical reservation has been released in the
/// accepted order and `ledger.finish()` succeeded, the caller's callback receives
/// `(doc_id, f64::from_bits(bits))` for every matched document, in ascending
/// physical `doc_id` order. No second full-M scored vector, score array, second
/// postings reader or second BM25 implementation exists.
#[allow(clippy::too_many_arguments)]
fn visit_strict_term_payload_with<const DEFERRED: bool, F>(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    stats: &SnapshotStats<'_>,
    positive: &BTreeSet<usize>,
    segment_index: usize,
    live: &[bool],
    budget: &mut CandidateBudget,
    meter: &mut MixedWorkMeter<'_>,
    cancel: &dyn Cancellation,
    certificate: Option<&DeferredBm25<'_, '_>>,
    mut on_payload: F,
) -> SearchResult<()>
where
    F: FnMut(u64, u64, usize, &mut CandidateBudget) -> SearchResult<()>,
{
    #[cfg(test)]
    c2_observation::record_strict_evaluator_call();

    let mut ledger = SegmentCandidateLedger::new(budget)?;
    // Standalone-only path: no batch memory sink (batch requests stay Legacy).
    let (mut leaf_data, leaf_charges) = {
        let mut work = SearchWork::shared(meter);
        build_leaf_data(
            reader,
            leaves,
            expansion,
            segment_index,
            live,
            &mut work,
            &mut ledger,
            None,
            cancel,
        )?
    };

    // Runtime guard: the statically eligible shape must still hold. Capture only
    // the field id; no `&str` borrow into `leaf_data` is retained across the
    // upcoming mutable `take_strict_one_term_postings` call.
    let field_id = match leaf_data.as_slice() {
        [LeafData::Term { field_id, terms }] if terms.len() == 1 => *field_id,
        _ => return Err(strict_term_shape_error()),
    };
    if positive.len() != 1 || !positive.contains(&0) {
        return Err(strict_term_shape_error());
    }

    // Accepted strict N examination charge: once per effective-live document, not
    // once per candidate posting. Same polls, same order as `evaluate_lexical_with`.
    let verified_live_count = stats.verified_segment_live_count(segment_index, live.len())?;
    let live_count = effective_live_examination_count(live, verified_live_count, meter)?;
    if live_count > 0 {
        meter.charge_lexical(live_count)?;
    }
    meter.check_cancelled()?;

    // Enumerate every decoded posting while the sole leaf allocation is still
    // intact. The root is exactly this term, so every decoded (already
    // effective-live filtered) posting is a true match: no membership relookup and
    // no typed/Boolean evaluation is performed. Cancellation is polled per
    // posting exactly as the accepted strict callback loop did.
    {
        let postings = match leaf_data.as_slice() {
            [LeafData::Term { terms, .. }] => terms[0].postings.as_slice(),
            _ => return Err(strict_term_shape_error()),
        };
        let mut last: Option<u64> = None;
        for (doc_id, _freq) in postings {
            meter.check_cancelled()?;
            debug_assert!(last.is_none_or(|previous| previous < *doc_id));
            last = Some(*doc_id);
            #[cfg(test)]
            c2_observation::record_strict_membership_observation();
        }
    }

    // Move the sole posting allocation out of the validated leaf data. The term
    // string stays owned by `leaf_data`, so it is borrowed only now.
    let mut scored_postings = take_strict_one_term_postings(&mut leaf_data, false)?;
    let term = match leaf_data.as_slice() {
        [LeafData::Term { field_id: f, terms }] if terms.len() == 1 && *f == field_id => {
            terms[0].term.as_str()
        }
        _ => return Err(strict_term_shape_error()),
    };

    // PERF-06-C3: the mode is a compile-time constant, so the certificate is
    // verified once against the already validated shape boundary, never per
    // document. A request-wide certificate rejection has already selected eager
    // C2, so a mismatch here is only private internal misuse.
    if DEFERRED {
        let cert = certificate.ok_or_else(strict_term_shape_error)?;
        let field = stats.field(field_id).ok_or_else(strict_term_shape_error)?;
        if !cert.matches(field, term) {
            return Err(strict_term_shape_error());
        }
    } else if certificate.is_some() {
        return Err(strict_term_shape_error());
    }

    let m = u64::try_from(scored_postings.len()).map_err(|_| SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    // Accepted logical matched-set admission (no physical tree is created).
    let matched_bytes = bytes_for_count(m, SET_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(m, matched_bytes, None)?;
    // Accepted logical scored-map admission, kept even though the physical map is
    // replaced by the in-place rewrite. Removing it would weaken a resource limit.
    let scored_bytes = bytes_for_count(m, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(m, scored_bytes, None)?;

    // Under the certified `DEFERRED` mode this phase is absent: the decoder already
    // proved every frequency positive, so the second word stays the raw integer
    // term frequency and only retained returned hits are scored after heap
    // selection. The eager statements below are the accepted C2 block verbatim.
    if !DEFERRED {
        #[cfg(test)]
        c2_observation::record_inplace_start(&scored_postings);
        let field_stats = if positive.contains(&0) {
            stats.field(field_id)
        } else {
            None
        };
        // Eager, complete scoring of every matched document, including those that
        // will lose numeric Top-K. One deliberate `+0.0` accumulation per document
        // preserves the accepted float grouping and signed-zero behavior.
        for row in &mut scored_postings {
            let (doc_id, freq) = *row;
            #[cfg(test)]
            if c2_observation::injected_score_failure(doc_id) {
                return Err(SearchError::InvalidScore {
                    detail: "injected C2 score failure",
                });
            }
            let mut score = 0.0_f64;
            if let Some(field) = field_stats {
                let dl = field.length(segment_index, doc_id);
                let contribution = field.bm25_score(term, freq, dl)?;
                score += contribution;
            }
            row.1 = score.to_bits();
        }
        #[cfg(test)]
        c2_observation::record_inplace_finish(&scored_postings);
    }

    // The term borrow ends here; discard the now-empty leaf allocation and
    // release the logical charges in the accepted order.
    drop(leaf_data);
    ledger.release_with_memory(m, matched_bytes, None)?;
    ledger.release_with_memory(leaf_charges.entries, leaf_charges.bytes, None)?;
    ledger.release_with_memory(m, scored_bytes, None)?;
    ledger.finish()?;
    drop(ledger);

    let matched_count = usize::try_from(m).map_err(|_| SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    for (doc_id, word) in &scored_postings {
        on_payload(*doc_id, *word, matched_count, budget)?;
        #[cfg(test)]
        c2_observation::record_callback();
    }
    Ok(())
}

/// PERF-06-C2: eager all-match scoring entry point (the accepted default).
///
/// This wrapper is byte-equivalent to the pre-C3 executor: it runs the shared
/// const-generic body in eager mode and hands the caller the decoded score as
/// `f64`. Every original C2 unit test and the production eager fallback call this.
#[allow(clippy::too_many_arguments)]
pub(crate) fn visit_strict_term_scored_with<F>(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    stats: &SnapshotStats<'_>,
    positive: &BTreeSet<usize>,
    segment_index: usize,
    live: &[bool],
    budget: &mut CandidateBudget,
    meter: &mut MixedWorkMeter<'_>,
    cancel: &dyn Cancellation,
    mut on_scored: F,
) -> SearchResult<()>
where
    F: FnMut(u64, f64, usize, &mut CandidateBudget) -> SearchResult<()>,
{
    visit_strict_term_payload_with::<false, _>(
        reader,
        leaves,
        expansion,
        stats,
        positive,
        segment_index,
        live,
        budget,
        meter,
        cancel,
        None,
        |doc_id, bits, matched_count, budget| {
            on_scored(doc_id, f64::from_bits(bits), matched_count, budget)
        },
    )
}

/// PERF-06-C3: certified deferred-scoring entry point.
///
/// Identical decoding, `N` examination, membership polling, logical admissions
/// and release order as [`visit_strict_term_scored_with`], but the raw positive
/// integer term frequency is handed to the callback instead of a score. The
/// caller holds a [`DeferredBm25`] certificate for this exact field/term.
#[allow(clippy::too_many_arguments)]
pub(crate) fn visit_strict_term_deferred_with<F>(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    stats: &SnapshotStats<'_>,
    positive: &BTreeSet<usize>,
    segment_index: usize,
    live: &[bool],
    budget: &mut CandidateBudget,
    meter: &mut MixedWorkMeter<'_>,
    cancel: &dyn Cancellation,
    certificate: &DeferredBm25<'_, '_>,
    mut on_candidate: F,
) -> SearchResult<()>
where
    F: FnMut(u64, std::num::NonZeroU64, usize, &mut CandidateBudget) -> SearchResult<()>,
{
    visit_strict_term_payload_with::<true, _>(
        reader,
        leaves,
        expansion,
        stats,
        positive,
        segment_index,
        live,
        budget,
        meter,
        cancel,
        Some(certificate),
        |doc_id, tf, matched_count, budget| {
            // Defensive only: the sole producer is the full decoder, which already
            // rejects a zero frequency before any callback.
            let tf = std::num::NonZeroU64::new(tf).ok_or(SearchError::Segment(
                crate::segment::SegmentError::ZeroFrequency { doc_id },
            ))?;
            on_candidate(doc_id, tf, matched_count, budget)
        },
    )
}

/// The established C2 runtime-shape failure. Never a fallback and never a panic.
fn strict_term_shape_error() -> SearchError {
    SearchError::CorruptIndex {
        detail: "single-term postings eligibility mismatch".to_owned(),
    }
}

/// PERF-06-C2 crate-level adversarial tests for the in-place evaluator.
///
/// These are the only tests that exercise the evaluator directly, which is what
/// makes two things provable that the public search path cannot express:
///
/// * a runtime shape disagreement returns the established typed corruption
///   instead of a panic or a silent fallback, and
/// * a checksum-valid segment container rebuilt with a corrupted `POSTINGS` or
///   `DOC_KEYS` body proves that the *whole* posting stream is validated before
///   any candidate callback and that a late scoring failure precedes every key
///   resolution (the synthetic fault is labelled `INJECTED_C2_ONLY`).
#[cfg(test)]
mod c2_physical_tests {
    use super::*;
    use crate::analysis::{AnalysisLimits, AnalyzerRegistry, NeverCancel};
    use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
    use crate::contract::query::Query;
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::index::{Index, IndexLimits};
    use crate::segment::SegmentReader;
    use crate::segment::{
        ContainerBuilder, ContainerKind, SectionKind, SegmentLimits, parse_container,
    };
    use crate::storage::{Directory, MemoryDirectory};
    use std::rc::Rc;
    use std::sync::Arc;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "grp",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
                FieldDefinition::new(
                    "doc_id",
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

    fn document(index: usize) -> Document {
        let key = format!("doc{index:06}");
        let mut document = Document::new(DocumentKey::new(key.clone()).expect("key"));
        document
            .insert(
                "grp",
                FieldValues::Single(FieldValue::Keyword("common".to_owned())),
            )
            .expect("grp");
        document
            .insert("doc_id", FieldValues::Single(FieldValue::Keyword(key)))
            .expect("doc_id");
        document
    }

    fn term_query() -> Query {
        Query::Term {
            field: "grp".to_owned(),
            value: FieldValue::Keyword("common".to_owned()),
        }
    }

    /// A real native single-segment index and its snapshot.
    fn index(count: usize) -> (Index, Arc<crate::index::ReaderSnapshot>) {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let schema = schema();
        let registry = AnalyzerRegistry::builtin();
        let limits = IndexLimits::new()
            .with_max_pending_docs(100_000)
            .with_max_pending_bytes(64 * 1024 * 1024);
        {
            let index = Index::create_with_limits(
                Arc::clone(&directory),
                schema.clone(),
                registry.clone(),
                limits.clone(),
            )
            .expect("create");
            let mut writer = index.writer().expect("writer");
            for position in 0..count {
                writer.insert(document(position)).expect("insert");
            }
            writer.commit().expect("commit");
        }
        let index = Index::open_with_limits(directory, schema, registry, limits).expect("reopen");
        let snapshot = index.snapshot();
        (index, snapshot)
    }

    struct StrictInputs<'a> {
        leaves: Vec<CompiledLeaf>,
        expansion: crate::search::expand::Expansion,
        stats: SnapshotStats<'a>,
        positive: BTreeSet<usize>,
    }

    /// Build the real compiled leaves, real expansion and real prepared statistics
    /// for one single-term query, exactly as `collect_mixed` does.
    fn strict_inputs<'a>(
        readers: &'a [&'a SegmentReader],
        live: &Rc<Vec<bool>>,
    ) -> StrictInputs<'a> {
        let schema = schema();
        let registry = AnalyzerRegistry::builtin();
        let limits = SearchLimits::default();
        let compiled = crate::search::plan::compile(
            &term_query(),
            &schema,
            &registry,
            &limits,
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("compile");
        let live_rows: Vec<Rc<Vec<bool>>> = vec![Rc::clone(live)];
        let mut meter = MixedWorkMeter::new(
            limits.max_total_work_units(),
            limits.max_typed_work_units(),
            limits.max_scanned_posting_occurrences(),
            &NeverCancel,
        );
        let expansion = {
            let mut work = SearchWork::shared(&mut meter);
            expand_query(readers, &compiled, &limits, &mut work, &NeverCancel).expect("expand")
        };
        let stats = {
            let mut work = SearchWork::shared(&mut meter);
            compute_stats(
                readers,
                &live_rows,
                &compiled.scoring_field_ids,
                expansion.positive_terms(),
                &limits,
                &mut work,
                &NeverCancel,
            )
            .expect("stats")
        };
        let positive = compiled.positive_leaf_indices.clone();
        StrictInputs {
            leaves: compiled.leaves,
            expansion,
            stats,
            positive,
        }
    }

    fn live_all(reader: &SegmentReader) -> Rc<Vec<bool>> {
        Rc::new(vec![true; reader.doc_count() as usize])
    }

    fn make_budget() -> CandidateBudget {
        CandidateBudget::new(&SearchLimits::default())
    }

    fn make_meter() -> MixedWorkMeter<'static> {
        MixedWorkMeter::new(u64::MAX, u64::MAX, u64::MAX, &NeverCancel)
    }

    #[test]
    fn c2_p01_shape_mismatch_fails_closed() {
        let (_index, snapshot) = index(8);
        let guard = snapshot.open_segment_reader(0).expect("guard");
        let reader = guard.reader();
        let live = live_all(reader);
        let readers = [reader];
        let inputs = strict_inputs(&readers, &live);
        // Wrong positive set.
        let mut budget = make_budget();
        let mut meter = make_meter();
        let error = visit_strict_term_scored_with(
            reader,
            &inputs.leaves,
            &inputs.expansion,
            &inputs.stats,
            &BTreeSet::from([1usize]),
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            |_, _, _, _| panic!("no callback on a shape mismatch"),
        )
        .expect_err("positive set mismatch");
        assert!(
            matches!(error, SearchError::CorruptIndex { ref detail } if detail == "single-term postings eligibility mismatch"),
            "{error:?}"
        );
        // Extra leaf shape.
        let mut leaves = inputs.leaves.clone();
        leaves.push(leaves[0].clone());
        let mut budget = make_budget();
        let error = visit_strict_term_scored_with(
            reader,
            &leaves,
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            |_, _, _, _| panic!("no callback on a shape mismatch"),
        )
        .expect_err("two leaves");
        assert!(
            matches!(error, SearchError::CorruptIndex { .. }),
            "{error:?}"
        );
        // Empty leaf list.
        let mut budget = make_budget();
        let error = visit_strict_term_scored_with(
            reader,
            &[],
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            |_, _, _, _| panic!("no callback on a shape mismatch"),
        )
        .expect_err("no leaves");
        assert!(
            matches!(error, SearchError::CorruptIndex { .. }),
            "{error:?}"
        );
        // The budget is reusable: the failed attempts released every charge.
        let mut budget = make_budget();
        let mut meter = make_meter();
        let mut callbacks = 0usize;
        visit_strict_term_scored_with(
            reader,
            &inputs.leaves,
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            |_, score, matched, _| {
                assert!(score.is_finite());
                assert_eq!(matched, 8);
                callbacks += 1;
                Ok(())
            },
        )
        .expect("happy path");
        assert_eq!(callbacks, 8);
    }

    #[test]
    fn c2_p02_inplace_reuse_and_callback_order() {
        let (_index, snapshot) = index(40);
        let guard = snapshot.open_segment_reader(0).expect("guard");
        let reader = guard.reader();
        let live = live_all(reader);
        let readers = [reader];
        let inputs = strict_inputs(&readers, &live);
        c2_observation::reset();
        let mut budget = make_budget();
        let mut meter = make_meter();
        let mut observed: Vec<(u64, u64)> = Vec::new();
        visit_strict_term_scored_with(
            reader,
            &inputs.leaves,
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            |doc_id, score, matched, _| {
                assert_eq!(matched, 40);
                observed.push((doc_id, score.to_bits()));
                Ok(())
            },
        )
        .expect("strict evaluation");
        assert!(c2_observation::inplace_preserved());
        assert_eq!(c2_observation::converted_rows(), 40);
        assert_eq!(c2_observation::callbacks(), 40);
        // Ascending physical order, one entry per matched document.
        let ids: Vec<u64> = observed.iter().map(|(doc, _)| *doc).collect();
        assert_eq!(ids, (0..40u64).collect::<Vec<_>>());
        // The accepted strict scorer never ran: no second full-M scored vector.
        assert_eq!(test_observation::single_term_scorer_calls(), 0);
        // The score of doc 0 equals the unchanged BM25 of an explicit recompute
        // through the same prepared statistics.
        let field_id = reader.schema().field_id("grp").expect("field");
        let field = inputs.stats.field(field_id).expect("stats");
        let expected = field.bm25_score("common", 1, 1).expect("bm25");
        assert_eq!(observed[0].1, expected.to_bits());
    }

    /// Rebuild a checksum-valid container with one section body replaced.
    fn rebuild_with(
        original: &[u8],
        kind: SectionKind,
        mutate: impl FnOnce(Vec<u8>) -> Vec<u8>,
    ) -> Vec<u8> {
        let view = parse_container(original, &SegmentLimits::default()).expect("container");
        let doc_count = view.doc_count();
        let features: Vec<(u16, u16)> = view.required_features().to_vec();
        let optional: Vec<(u16, u16)> = view.optional_features().to_vec();
        let sections: Vec<(SectionKind, u16, u64, Vec<u8>)> = view
            .sections()
            .iter()
            .map(|entry| {
                (
                    entry.kind,
                    entry.flags,
                    entry.aux,
                    view.body(entry.kind).expect("body").to_vec(),
                )
            })
            .collect();
        let mut builder = ContainerBuilder::new(ContainerKind::Segment, doc_count);
        for (id, version) in &features {
            builder.require_feature(*id, *version);
        }
        for (id, version) in &optional {
            builder.optional_feature(*id, *version);
        }
        let mut mutate = Some(mutate);
        for (section, flags, aux, body) in &sections {
            let body = match (mutate.take(), *section == kind) {
                (Some(apply), true) => apply(body.clone()),
                (taken, _) => {
                    mutate = taken;
                    body.clone()
                }
            };
            builder.section(*section, *flags, *aux, body);
        }
        builder.build().expect("rebuild")
    }

    #[test]
    fn c2_p03_corrupt_postings_precede_every_callback() {
        let (_index, snapshot) = index(24);
        let guard = snapshot.open_segment_reader(0).expect("guard");
        let original = guard.reader().bytes().to_vec();
        drop(guard);
        let corrupted = rebuild_with(&original, SectionKind::Postings, |mut body| {
            // Keep every section length (so the dictionary extent check still
            // passes) but make the final varint unterminated.
            let len = body.len();
            for byte in &mut body[len.saturating_sub(4)..] {
                *byte = 0xFF;
            }
            body
        });
        let reader = SegmentReader::open(corrupted, SegmentLimits::default())
            .expect("a corrupt POSTINGS body is not validated at open");
        let live = live_all(&reader);
        let readers = [&reader];
        let inputs = strict_inputs(&readers, &live);
        c2_observation::reset();
        let mut budget = make_budget();
        let mut meter = make_meter();
        let error = visit_strict_term_scored_with(
            &reader,
            &inputs.leaves,
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            |_, _, _, _| panic!("a malformed posting stream must not reach a candidate"),
        )
        .expect_err("corrupt postings");
        assert!(
            matches!(
                error,
                SearchError::Segment(_) | SearchError::Index(_) | SearchError::CorruptIndex { .. }
            ),
            "{error:?}"
        );
        assert_eq!(c2_observation::callbacks(), 0);
        // No reservation leaked: a fresh ledger on the same budget succeeds.
        let mut ledger = SegmentCandidateLedger::new(&mut budget).expect("fresh segment");
        ledger.reserve(1, 16).expect("reserve");
        ledger.release(1, 16).expect("release");
        ledger.finish().expect("finish");
    }

    #[test]
    fn c2_p04_late_score_fault_precedes_corrupt_doc_keys() {
        let (_index, snapshot) = index(30);
        let guard = snapshot.open_segment_reader(0).expect("guard");
        let original = guard.reader().bytes().to_vec();
        drop(guard);
        let corrupted = rebuild_with(&original, SectionKind::DocKeys, |mut body| {
            // Byte 12 is inside the first key body (u16 version + u64 count).
            if body.len() > 12 {
                body[12] ^= 0xFF;
            }
            body
        });
        let reader = SegmentReader::open(corrupted, SegmentLimits::default())
            .expect("a corrupt DOC_KEYS body is not validated at open");
        let live = live_all(&reader);
        let readers = [&reader];
        let inputs = strict_inputs(&readers, &live);

        // Control: without a scoring fault, the callback's key resolution raises
        // the original typed corruption (so the key error is genuinely reachable).
        let mut budget = make_budget();
        let mut meter = make_meter();
        let mut key_errors = 0usize;
        let outcome = visit_strict_term_scored_with(
            &reader,
            &inputs.leaves,
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            |doc_id, _, _, _| {
                if reader.doc_key(doc_id).is_err() {
                    key_errors += 1;
                    return Err(SearchError::CorruptIndex {
                        detail: "corrupt doc keys".to_owned(),
                    });
                }
                Ok(())
            },
        );
        assert!(outcome.is_err(), "the corrupt key must surface");
        assert!(key_errors > 0);

        // Structural adversarial case: a late synthetic scoring failure wins,
        // because the whole segment is scored before any candidate exists.
        // Evidence class: INJECTED_C2_ONLY.
        c2_observation::reset();
        let mut budget = make_budget();
        let mut meter = make_meter();
        let mut callbacks = 0usize;
        let outcome = {
            let _arm = c2_observation::ScoreFailureArm::arm(29);
            visit_strict_term_scored_with(
                &reader,
                &inputs.leaves,
                &inputs.expansion,
                &inputs.stats,
                &inputs.positive,
                0,
                &live,
                &mut budget,
                &mut meter,
                &NeverCancel,
                |_, _, _, _| {
                    callbacks += 1;
                    Ok(())
                },
            )
        };
        let error = outcome.expect_err("late score fault");
        assert!(
            matches!(error, SearchError::InvalidScore { detail } if detail == "injected C2 score failure"),
            "{error:?}"
        );
        assert_eq!(callbacks, 0, "no candidate callback in that segment");
    }

    #[test]
    fn c2_p05_n_examination_and_scanned_frequency() {
        let (_index, snapshot) = index(20);
        let guard = snapshot.open_segment_reader(0).expect("guard");
        let reader = guard.reader();
        let mut live = vec![true; reader.doc_count() as usize];
        // Tombstone every third physical document.
        for (position, flag) in live.iter_mut().enumerate() {
            if position % 3 == 0 {
                *flag = false;
            }
        }
        let expected_live: Vec<u64> = vec![1, 2, 4, 5, 7, 8, 10, 11, 13, 14, 16, 17, 19];
        assert_eq!(
            (0..live.len() as u64)
                .filter(|doc| live[*doc as usize])
                .collect::<Vec<u64>>(),
            expected_live,
            "the effective-live mask is the deterministic test input"
        );
        let live_rows: Vec<Rc<Vec<bool>>> = vec![Rc::new(live.clone())];
        let readers = [reader];
        let inputs = strict_inputs(&readers, &live_rows[0]);

        // Every direct evaluator call gets a fresh meter starting at zero; the
        // prepared inputs above used their own, separate meter.
        //   scanned postings: 20 physical postings of frequency 1
        //   N examination:    13 effective-live documents
        //   work units:       20 * (1 + 1) + 13 = 53
        struct Row {
            total: u64,
            scanned: u64,
            /// `None` means success; `Some((limit, requested))` is the exact
            /// ResourceLimit payload.
            failure: Option<(u64, u64)>,
            callbacks: usize,
            meter_total: u64,
        }
        let rows = [
            Row {
                total: u64::MAX,
                scanned: 10,
                failure: Some((10, 11)),
                callbacks: 0,
                meter_total: 20,
            },
            Row {
                total: u64::MAX,
                scanned: 19,
                failure: Some((19, 20)),
                callbacks: 0,
                meter_total: 38,
            },
            Row {
                total: u64::MAX,
                scanned: 20,
                failure: None,
                callbacks: 13,
                meter_total: 53,
            },
            Row {
                total: u64::MAX,
                scanned: 21,
                failure: None,
                callbacks: 13,
                meter_total: 53,
            },
            Row {
                total: 52,
                scanned: 20,
                failure: Some((52, 53)),
                callbacks: 0,
                meter_total: 40,
            },
            Row {
                total: 53,
                scanned: 20,
                failure: None,
                callbacks: 13,
                meter_total: 53,
            },
        ];

        for row in rows {
            let mut budget = make_budget();
            let mut meter = MixedWorkMeter::new(row.total, u64::MAX, row.scanned, &NeverCancel);
            let mut observed: Vec<u64> = Vec::new();
            let result = visit_strict_term_scored_with(
                reader,
                &inputs.leaves,
                &inputs.expansion,
                &inputs.stats,
                &inputs.positive,
                0,
                &live,
                &mut budget,
                &mut meter,
                &NeverCancel,
                |doc_id, score, matched, _| {
                    assert_eq!(matched, 13, "matched count is the live count");
                    assert!(score.is_finite(), "the score is finite");
                    observed.push(doc_id);
                    Ok(())
                },
            );
            assert_eq!(
                meter.total_used(),
                row.meter_total,
                "total work for total={} scanned={}",
                row.total,
                row.scanned
            );
            assert_eq!(
                observed.len(),
                row.callbacks,
                "completed callbacks for total={} scanned={}",
                row.total,
                row.scanned
            );
            match row.failure {
                Some((limit, requested)) => {
                    let error = result.expect_err("this row must be rejected");
                    match error {
                        SearchError::ResourceLimit {
                            limit: got_limit,
                            requested: got_requested,
                        } => assert_eq!(
                            (got_limit, got_requested),
                            (limit, requested),
                            "exact resource payload"
                        ),
                        other => {
                            panic!("expected ResourceLimit {{{limit}, {requested}}}, got {other:?}")
                        }
                    }
                }
                None => {
                    result.expect("this row must succeed");
                    assert_eq!(observed, expected_live, "exact live doc-id order");
                }
            }
            // The ledger returned to zero in every outcome.
            assert_eq!(budget.segment_entries, 0, "segment entries released");
            assert_eq!(budget.segment_bytes, 0, "segment bytes released");
            assert_eq!(budget.global_bytes, 0, "global bytes released");
            eprintln!(
                "C2-F1 P05: total={} scanned={} failure={:?} callbacks={} work={}",
                row.total, row.scanned, row.failure, row.callbacks, row.meter_total
            );
            // A rejected admission must leave the *same* budget reusable.
            let mut recovery = make_meter_with(53, 20);
            let mut recovered: Vec<u64> = Vec::new();
            visit_strict_term_scored_with(
                reader,
                &inputs.leaves,
                &inputs.expansion,
                &inputs.stats,
                &inputs.positive,
                0,
                &live,
                &mut budget,
                &mut recovery,
                &NeverCancel,
                |doc_id, _, _, _| {
                    recovered.push(doc_id);
                    Ok(())
                },
            )
            .expect("the same budget admits the recovery run");
            assert_eq!(recovered, expected_live, "recovery doc-id order");
            assert_eq!(recovery.total_used(), 53, "recovery work");
            assert_eq!(budget.segment_entries, 0);
            assert_eq!(budget.segment_bytes, 0);
            assert_eq!(budget.global_bytes, 0);
        }
    }

    /// PERF-06-C3 P01: the deferred visitor is the same validated decoder, `N`
    /// examination, membership poll, logical admissions and release sequence as
    /// the eager one, but it hands the caller the raw positive integer frequency
    /// and invokes no scorer at all.
    #[test]
    fn c3_p01_deferred_decode_and_ledger() {
        use crate::search::score::c3_score_observation;

        let (_index, snapshot) = index(20);
        let guard = snapshot.open_segment_reader(0).expect("guard");
        let reader = guard.reader();
        let mut live = vec![true; reader.doc_count() as usize];
        for (position, flag) in live.iter_mut().enumerate() {
            if position % 3 == 0 {
                *flag = false;
            }
        }
        let expected_live: Vec<u64> = vec![1, 2, 4, 5, 7, 8, 10, 11, 13, 14, 16, 17, 19];
        let live_rows: Vec<Rc<Vec<bool>>> = vec![Rc::new(live.clone())];
        let readers = [reader];
        let inputs = strict_inputs(&readers, &live_rows[0]);
        let field_id = reader.schema().field_id("grp").expect("field");
        let cert = inputs
            .stats
            .field(field_id)
            .expect("grp stats")
            .certify_deferred("common")
            .expect("the 13-live-doc /grp/common fixture is certifiable");

        struct Row {
            total: u64,
            scanned: u64,
            failure: Option<(u64, u64)>,
            callbacks: usize,
            meter_total: u64,
        }
        let rows = [
            Row {
                total: u64::MAX,
                scanned: 10,
                failure: Some((10, 11)),
                callbacks: 0,
                meter_total: 20,
            },
            Row {
                total: u64::MAX,
                scanned: 19,
                failure: Some((19, 20)),
                callbacks: 0,
                meter_total: 38,
            },
            Row {
                total: u64::MAX,
                scanned: 20,
                failure: None,
                callbacks: 13,
                meter_total: 53,
            },
            Row {
                total: u64::MAX,
                scanned: 21,
                failure: None,
                callbacks: 13,
                meter_total: 53,
            },
            Row {
                total: 52,
                scanned: 20,
                failure: Some((52, 53)),
                callbacks: 0,
                meter_total: 40,
            },
            Row {
                total: 53,
                scanned: 20,
                failure: None,
                callbacks: 13,
                meter_total: 53,
            },
        ];

        let mut completed = 0usize;
        for row in rows {
            let mut budget = make_budget();
            let mut meter = MixedWorkMeter::new(row.total, u64::MAX, row.scanned, &NeverCancel);
            let mut observed: Vec<u64> = Vec::new();
            c2_observation::reset();
            c3_score_observation::reset();
            let result = visit_strict_term_deferred_with(
                reader,
                &inputs.leaves,
                &inputs.expansion,
                &inputs.stats,
                &inputs.positive,
                0,
                &live,
                &mut budget,
                &mut meter,
                &NeverCancel,
                &cert,
                |doc_id, tf, matched, _| {
                    assert_eq!(tf.get(), 1, "raw positive frequency is preserved");
                    assert_eq!(matched, 13, "matched count is the live count");
                    observed.push(doc_id);
                    Ok(())
                },
            );
            assert_eq!(
                meter.total_used(),
                row.meter_total,
                "total work for total={} scanned={}",
                row.total,
                row.scanned
            );
            assert_eq!(
                observed.len(),
                row.callbacks,
                "completed callbacks for total={} scanned={}",
                row.total,
                row.scanned
            );
            assert_eq!(
                c3_score_observation::calls(),
                0,
                "deferred mode never scores"
            );
            assert_eq!(
                c2_observation::converted_rows(),
                0,
                "no in-place frequency -> score rewrite happened"
            );
            match row.failure {
                Some((limit, requested)) => {
                    let error = result.expect_err("this row must be rejected");
                    match error {
                        SearchError::ResourceLimit {
                            limit: got_limit,
                            requested: got_requested,
                        } => assert_eq!(
                            (got_limit, got_requested),
                            (limit, requested),
                            "exact resource payload"
                        ),
                        other => {
                            panic!("expected ResourceLimit {{{limit}, {requested}}}, got {other:?}")
                        }
                    }
                }
                None => {
                    result.expect("this row must succeed");
                    assert_eq!(observed, expected_live, "exact live doc-id order");
                }
            }
            assert_eq!(budget.segment_entries, 0, "segment entries released");
            assert_eq!(budget.segment_bytes, 0, "segment bytes released");
            assert_eq!(budget.global_bytes, 0, "global bytes released");
            eprintln!(
                "C3 P01: total={} scanned={} failure={:?} callbacks={} work={}",
                row.total, row.scanned, row.failure, row.callbacks, row.meter_total
            );

            // A rejected admission leaves the same budget reusable; the recovery
            // run also never scores.
            let mut recovery = make_meter_with(53, 20);
            let mut recovered: Vec<u64> = Vec::new();
            c3_score_observation::reset();
            visit_strict_term_deferred_with(
                reader,
                &inputs.leaves,
                &inputs.expansion,
                &inputs.stats,
                &inputs.positive,
                0,
                &live,
                &mut budget,
                &mut recovery,
                &NeverCancel,
                &cert,
                |doc_id, tf, _, _| {
                    assert_eq!(tf.get(), 1);
                    recovered.push(doc_id);
                    Ok(())
                },
            )
            .expect("the same budget admits the recovery run");
            assert_eq!(recovered, expected_live, "recovery doc-id order");
            assert_eq!(recovery.total_used(), 53, "recovery work");
            assert_eq!(c3_score_observation::calls(), 0, "recovery never scores");
            assert_eq!(budget.segment_entries, 0);
            assert_eq!(budget.segment_bytes, 0);
            assert_eq!(budget.global_bytes, 0);
            completed += 1;
        }
        assert_eq!(completed, 6, "six deferred ledger rows completed");

        // Internal misuse guard: a certificate issued for a *different* prepared
        // statistics object must fail closed before any callback, and the same
        // budget must still admit a correct retry.
        let other_inputs = strict_inputs(&readers, &live_rows[0]);
        let other_cert = other_inputs
            .stats
            .field(field_id)
            .expect("second grp stats")
            .certify_deferred("common")
            .expect("second stats are also certifiable");
        let mut budget = make_budget();
        let mut meter = make_meter();
        c3_score_observation::reset();
        let error = visit_strict_term_deferred_with(
            reader,
            &inputs.leaves,
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            &other_cert,
            |_, _, _, _| panic!("no callback for a foreign certificate"),
        )
        .expect_err("a certificate for another stats object must be rejected");
        assert!(
            matches!(error, SearchError::CorruptIndex { ref detail } if detail == "single-term postings eligibility mismatch"),
            "{error:?}"
        );
        assert_eq!(c3_score_observation::calls(), 0);
        assert_eq!(budget.segment_entries, 0, "entries released on misuse");
        assert_eq!(budget.segment_bytes, 0, "bytes released on misuse");
        assert_eq!(budget.global_bytes, 0, "global bytes released on misuse");
        let mut recovered: Vec<u64> = Vec::new();
        visit_strict_term_deferred_with(
            reader,
            &inputs.leaves,
            &inputs.expansion,
            &inputs.stats,
            &inputs.positive,
            0,
            &live,
            &mut budget,
            &mut meter,
            &NeverCancel,
            &cert,
            |doc_id, tf, _, _| {
                assert_eq!(tf.get(), 1);
                recovered.push(doc_id);
                Ok(())
            },
        )
        .expect("the same budget and the correct certificate recover");
        assert_eq!(recovered, expected_live, "recovery after misuse guard");
        assert_eq!(c3_score_observation::calls(), 0, "recovery never scores");
        eprintln!("C3 P01 misuse-guard=ok recovery=ok rows={completed}");
    }

    fn make_meter_with(total: u64, scanned: u64) -> MixedWorkMeter<'static> {
        MixedWorkMeter::new(total, u64::MAX, scanned, &NeverCancel)
    }
}

#[cfg(test)]
mod budget_tests {
    use super::*;

    fn limits(entries: u64, bytes: u64) -> SearchLimits {
        SearchLimits::default()
            .with_max_segment_candidate_entries(entries)
            .unwrap()
            .with_max_total_candidate_bytes(bytes)
            .unwrap()
    }

    #[test]
    fn reserve_release_round_trip_and_reset() {
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(10, 1_000).unwrap();
        budget.reserve_segment(5, 500).unwrap();
        assert_eq!(budget.segment_entries, 15);
        assert_eq!(budget.segment_bytes, 1_500);
        budget.release_segment(5, 500).unwrap();
        assert_eq!(budget.segment_entries, 10);
        budget.release_segment(10, 1_000).unwrap();
        budget.end_segment().unwrap();
    }

    #[test]
    fn segment_entry_limit_is_exact_and_atomic() {
        let mut budget = CandidateBudget::new(&limits(10, 10_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(10, 0).unwrap();
        let error = budget.reserve_segment(1, 0).unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        // Failed reservation did not mutate the counters.
        assert_eq!(budget.segment_entries, 10);
        assert_eq!(budget.segment_bytes, 0);
    }

    #[test]
    fn global_plus_segment_byte_sum_is_enforced() {
        // Each budget passes alone; combined they exceed the total.
        let mut budget = CandidateBudget::new(&limits(1_000, 1_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(1, 600).unwrap();
        budget.reserve_global(300).unwrap();
        let error = budget.reserve_global(200).unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        // Atomic: the failed reserve did not change global bytes.
        assert_eq!(budget.global_bytes, 300);
        // Releasing the segment then retrying succeeds.
        budget.release_segment(1, 600).unwrap();
        budget.reserve_global(200).unwrap();
        assert_eq!(budget.global_bytes, 500);
    }

    #[test]
    fn global_byte_boundary_is_exact() {
        let mut budget = CandidateBudget::new(&limits(1_000, 194));
        budget.begin_segment().unwrap();
        budget.reserve_global(97).unwrap();
        budget.reserve_global(97).unwrap();
        assert!(matches!(
            budget.reserve_global(1),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(budget.global_bytes, 194);
    }

    #[test]
    fn production_global_bytes_exact_then_one_over_and_release() {
        let mut budget = CandidateBudget::new(&limits(1_000, 100));
        budget.reserve_global_bytes(100).unwrap();
        assert!(matches!(
            budget.reserve_global_bytes(1),
            Err(SearchError::ResourceLimit {
                limit: 100,
                requested: 101
            })
        ));
        // The rejected reservation did not change the counter.
        assert_eq!(budget.global_bytes, 100);
        budget.release_global_bytes(100).unwrap();
        budget.reserve_global_bytes(100).unwrap();
        assert_eq!(budget.global_bytes, 100);
    }

    #[test]
    fn overflow_is_typed_and_atomic() {
        // Constructed directly so the hard-ceiling validation of public limits does
        // not mask the checked-arithmetic paths under test.
        let mut budget = CandidateBudget {
            max_segment_entries: u64::MAX,
            max_total_bytes: u64::MAX,
            global_bytes: 0,
            segment_entries: 0,
            segment_bytes: 0,
        };
        budget.begin_segment().unwrap();
        budget.reserve_segment(u64::MAX, 0).unwrap();
        assert!(matches!(
            budget.reserve_segment(1, 0),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(budget.segment_entries, u64::MAX);
        // Segment bytes can also overflow independently; entries must be freed first
        // because the entry bound is already saturated.
        budget.release_segment(u64::MAX, 0).unwrap();
        budget.reserve_segment(0, u64::MAX).unwrap();
        assert!(matches!(
            budget.reserve_segment(0, 1),
            Err(SearchError::ResourceLimit { .. })
        ));
        budget.release_segment(0, u64::MAX).unwrap();
        budget.end_segment().unwrap();

        let mut budget = CandidateBudget {
            max_segment_entries: 10,
            max_total_bytes: u64::MAX,
            global_bytes: 0,
            segment_entries: 0,
            segment_bytes: 0,
        };
        budget.begin_segment().unwrap();
        budget.reserve_global(u64::MAX).unwrap();
        assert!(matches!(
            budget.reserve_global(1),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(budget.global_bytes, u64::MAX);
    }

    #[test]
    fn begin_and_end_require_zero() {
        let mut budget = CandidateBudget::new(&limits(10, 1_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(1, 10).unwrap();
        assert!(matches!(
            budget.begin_segment(),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert!(matches!(
            budget.end_segment(),
            Err(SearchError::CorruptIndex { .. })
        ));
        budget.release_segment(1, 10).unwrap();
        budget.end_segment().unwrap();
        budget.begin_segment().unwrap();
    }

    #[test]
    fn ledger_releases_outstanding_reservations_on_drop() {
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        {
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger.reserve(5, 100).unwrap();
            ledger.reserve(3, 60).unwrap();
            assert_eq!(ledger.outstanding_entries, 8);
        }
        assert_eq!(budget.segment_entries, 0);
        assert_eq!(budget.segment_bytes, 0);
        budget.begin_segment().unwrap();
    }

    #[test]
    fn release_underflow_is_typed() {
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(1, 10).unwrap();
        assert!(matches!(
            budget.release_segment(2, 10),
            Err(SearchError::CorruptIndex { .. })
        ));
    }

    // A2-01 — segment-to-global transfer is atomic and preserves the total.
    #[test]
    fn a2_01_transfer_is_atomic_and_preserves_total() {
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(3, 300).unwrap();
        let total_before = budget.segment_bytes + budget.global_bytes;
        budget.transfer_segment_to_global(2, 200).unwrap();
        assert_eq!(budget.segment_entries, 1);
        assert_eq!(budget.segment_bytes, 100);
        assert_eq!(budget.global_bytes, 200);
        assert_eq!(budget.segment_bytes + budget.global_bytes, total_before);
        // The ledger mirrors the transfer.
        let mut ledger_budget = CandidateBudget::new(&limits(100, 1_000));
        {
            let mut ledger = SegmentCandidateLedger::new(&mut ledger_budget).unwrap();
            ledger.reserve(3, 300).unwrap();
            ledger.transfer_to_global(2, 200).unwrap();
            assert_eq!(ledger.outstanding_entries, 1);
            assert_eq!(ledger.outstanding_bytes, 100);
            assert!(ledger.finish().is_err(), "one outstanding reservation");
            ledger.release(1, 100).unwrap();
            ledger.finish().unwrap();
        }
        assert_eq!(ledger_budget.global_bytes, 200);
        // A release-then-reserve sequence would transiently drop the total; the
        // atomic transfer never does.
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(1, 300).unwrap();
        budget.release_segment(1, 300).unwrap();
        assert_eq!(budget.segment_bytes + budget.global_bytes, 0);
        budget.reserve_global(300).unwrap();
        assert_eq!(budget.segment_bytes + budget.global_bytes, 300);
    }

    // A2-04 — every rejected transfer leaves all counters unchanged.
    #[test]
    fn a2_04_transfer_rejections_are_atomic() {
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        budget.begin_segment().unwrap();
        budget.reserve_segment(2, 200).unwrap();
        let snapshot = (
            budget.segment_entries,
            budget.segment_bytes,
            budget.global_bytes,
        );
        assert!(matches!(
            budget.transfer_segment_to_global(3, 200),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert!(matches!(
            budget.transfer_segment_to_global(2, 201),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert_eq!(
            (
                budget.segment_entries,
                budget.segment_bytes,
                budget.global_bytes
            ),
            snapshot
        );
        // Overflow on global bytes is typed and atomic.
        let mut budget = CandidateBudget {
            max_segment_entries: 100,
            max_total_bytes: u64::MAX,
            global_bytes: u64::MAX,
            segment_entries: 1,
            segment_bytes: 10,
        };
        assert!(matches!(
            budget.transfer_segment_to_global(1, 10),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(budget.global_bytes, u64::MAX);
        assert_eq!(budget.segment_bytes, 10);
    }

    // A2-05 — a segment reservation that would join an at-limit global fails before mutation.
    #[test]
    fn a2_05_global_plus_segment_boundary_is_atomic() {
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        budget.begin_segment().unwrap();
        budget.transfer_segment_to_global(0, 0).unwrap();
        budget.reserve_global(700).unwrap();
        budget.reserve_segment(1, 300).unwrap();
        let snapshot = (budget.segment_entries, budget.segment_bytes);
        assert!(matches!(
            budget.reserve_segment(1, 1),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!((budget.segment_entries, budget.segment_bytes), snapshot);
        assert_eq!(budget.global_bytes, 700);
    }

    // A2-07 — charge records use checked addition.
    #[test]
    fn a2_07_charges_overflow_is_typed() {
        let charges = Charges {
            entries: u64::MAX,
            bytes: 0,
        };
        assert!(matches!(
            charges.add(1, 0),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(
            charges,
            Charges {
                entries: u64::MAX,
                bytes: 0
            }
        );
        assert_eq!(
            Charges::ZERO.add(2, 3).unwrap(),
            Charges {
                entries: 2,
                bytes: 3
            }
        );
    }

    /// Test helper: one expanded term whose postings are supplied in ascending
    /// doc-id order (the invariant production decoding guarantees).
    fn term_leaf(field_id: u32, term: &str, docs: &[u64]) -> LeafData {
        LeafData::Term {
            field_id,
            terms: vec![TermPostings {
                term: term.to_owned(),
                postings: docs.iter().map(|doc| (*doc, 1)).collect(),
            }],
        }
    }

    // -----------------------------------------------------------------------
    // PR 15E-B1b — sorted-postings membership (U07–U10)
    // -----------------------------------------------------------------------

    /// One leaf with several expanded terms, each with ascending-doc postings.
    fn term_leaf_multi(field_id: u32, terms: &[(&str, &[u64])]) -> LeafData {
        LeafData::Term {
            field_id,
            terms: terms
                .iter()
                .map(|(term, docs)| TermPostings {
                    term: (*term).to_owned(),
                    postings: docs.iter().map(|doc| (*doc, 1)).collect(),
                })
                .collect(),
        }
    }

    /// Independent reference membership: materialize the union of the supplied
    /// postings into a `BTreeSet` and test it directly. This never consults the
    /// executor's representation.
    fn reference_membership(terms: &[&[u64]], doc_id: u64) -> bool {
        terms.iter().any(|docs| {
            docs.iter()
                .copied()
                .collect::<BTreeSet<u64>>()
                .contains(&doc_id)
        })
    }

    fn assert_membership_matches_oracle(leaf: &LeafData, terms: &[&[u64]], doc_range: u64) {
        for doc_id in 0..doc_range {
            assert_eq!(
                leaf.matches(doc_id),
                reference_membership(terms, doc_id),
                "doc_id {doc_id}"
            );
        }
    }

    // U07 — empty, single-element and boundary vectors.
    #[test]
    fn u07_term_membership_boundaries_match_oracle() {
        // Empty postings never match, including doc 0.
        let empty = term_leaf_multi(0, &[("empty", &[])]);
        assert_membership_matches_oracle(&empty, &[&[]], 8);

        // A single posting at the very first and very last valid doc id.
        let first = term_leaf_multi(0, &[("first", &[0])]);
        assert_membership_matches_oracle(&first, &[&[0]], 8);
        assert!(first.matches(0));
        let last = term_leaf_multi(0, &[("last", &[7])]);
        assert_membership_matches_oracle(&last, &[&[7]], 8);
        assert!(last.matches(7));
        // Immediately past the maximum and one below the first entry.
        assert!(!last.matches(8));
        assert!(!last.matches(u64::MAX));
        assert!(!first.matches(1));

        // Gaps: only the encoded document ids are members.
        let gapped = term_leaf_multi(0, &[("gap", &[0, 3, 4, 9])]);
        assert_membership_matches_oracle(&gapped, &[&[0, 3, 4, 9]], 12);
    }

    // U08 — multiple expanded terms OR together without double counting.
    #[test]
    fn u08_multi_term_or_with_overlapping_postings_matches_oracle() {
        let terms: [&[u64]; 3] = [&[1, 2, 5, 8], &[2, 3, 8], &[0, 8, 9]];
        let leaf = term_leaf_multi(0, &[("a", terms[0]), ("b", terms[1]), ("c", terms[2])]);
        assert_membership_matches_oracle(&leaf, &terms, 12);
        // Overlaps and duplicates in the union do not change membership.
        assert!(leaf.matches(8));
        assert!(leaf.matches(0));
        assert!(!leaf.matches(4));
    }

    // U09 — deterministic generated sparse/dense sets against the reference sets.
    #[test]
    fn u09_seeded_generated_postings_match_reference_sets() {
        // Fixed seed: every case is reproducible from this constant alone.
        let mut state: u64 = 0x5EED_0B1B_0000_0001;
        let mut next = || {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            state >> 11
        };
        for case in 0..256u64 {
            let max_doc = 1 + next() % 40;
            // Alternate dense and sparse generation to cover both profiles.
            let density = if case % 2 == 0 { 3 } else { 9 };
            let mut docs: Vec<u64> = (0..max_doc).filter(|_doc| next() % density == 0).collect();
            docs.sort_unstable();
            docs.dedup();
            let mut second: Vec<u64> = (0..max_doc)
                .filter(|_doc| next() % (density + 2) == 0)
                .collect();
            second.sort_unstable();
            second.dedup();
            let leaf = term_leaf_multi(0, &[("a", &docs), ("b", &second)]);
            assert_membership_matches_oracle(&leaf, &[&docs, &second], max_doc + 2);
        }
    }

    // U10 — the phrase arm is unchanged (set membership over verified matches).
    #[test]
    fn u10_phrase_membership_unchanged() {
        let matched = [2u64, 5, 11];
        let leaf = LeafData::Phrase {
            field_id: 0,
            matches: matched
                .iter()
                .map(|doc_id| PhraseMatch {
                    doc_id: *doc_id,
                    term_freqs: Vec::new(),
                })
                .collect(),
        };
        for doc_id in 0..14 {
            assert_eq!(
                leaf.matches(doc_id),
                matched.contains(&doc_id),
                "doc_id {doc_id}"
            );
        }
        // An empty phrase match set matches nothing.
        let empty = LeafData::Phrase {
            field_id: 0,
            matches: Vec::new(),
        };
        assert!((0..8).all(|doc_id| !empty.matches(doc_id)));
    }

    fn eval_reserved(
        node: &CompiledNode,
        leaves: &[LeafData],
        universe: &BTreeSet<u64>,
        work: &mut SearchWork<'_>,
    ) -> BTreeSet<u64> {
        let mut budget = CandidateBudget::new(&limits(100, 100_000));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        let reserved = eval_node(node, leaves, universe, &mut ledger, work).unwrap();
        let entries = reserved.entries;
        let set = reserved.set;
        ledger
            .release(
                entries,
                bytes_for_count(entries, SET_BYTES_PER_ENTRY).unwrap(),
            )
            .unwrap();
        ledger.finish().unwrap();
        set
    }

    // A2-08 — Boolean set algebra and peak-entry accounting against a std-set oracle.
    #[test]
    fn a2_08_boolean_set_algebra_and_peak() {
        let leaves = vec![term_leaf(0, "a", &[1, 2]), term_leaf(0, "b", &[2, 3])];
        let universe: BTreeSet<u64> = [1, 2, 3].into_iter().collect();
        let mut work = SearchWork::new(1_000_000, &crate::analysis::NeverCancel);

        let a: BTreeSet<u64> = [1, 2].into_iter().collect();
        let b: BTreeSet<u64> = [2, 3].into_iter().collect();
        let and = eval_reserved(
            &CompiledNode::And(vec![CompiledNode::Leaf(0), CompiledNode::Leaf(1)]),
            &leaves,
            &universe,
            &mut work,
        );
        assert_eq!(and, a.intersection(&b).cloned().collect::<BTreeSet<_>>());
        let or = eval_reserved(
            &CompiledNode::Or(vec![CompiledNode::Leaf(0), CompiledNode::Leaf(1)]),
            &leaves,
            &universe,
            &mut work,
        );
        assert_eq!(or, a.union(&b).cloned().collect::<BTreeSet<_>>());
        let not = eval_reserved(
            &CompiledNode::Not(Box::new(CompiledNode::Leaf(0))),
            &leaves,
            &universe,
            &mut work,
        );
        assert_eq!(
            not,
            universe.difference(&a).cloned().collect::<BTreeSet<_>>()
        );
        let nested = eval_reserved(
            &CompiledNode::Or(vec![
                CompiledNode::And(vec![CompiledNode::Leaf(0), CompiledNode::Leaf(1)]),
                CompiledNode::Not(Box::new(CompiledNode::Leaf(1))),
            ]),
            &leaves,
            &universe,
            &mut work,
        );
        let expected: BTreeSet<u64> = a
            .intersection(&b)
            .cloned()
            .collect::<BTreeSet<_>>()
            .union(&universe.difference(&b).cloned().collect::<BTreeSet<_>>())
            .cloned()
            .collect();
        assert_eq!(nested, expected);

        // A one-entry per-segment bound rejects while a generous bound passes.
        let mut tight = CandidateBudget::new(&limits(1, 100_000));
        let mut ledger = SegmentCandidateLedger::new(&mut tight).unwrap();
        let node = CompiledNode::Or(vec![CompiledNode::Leaf(0), CompiledNode::Leaf(1)]);
        assert!(matches!(
            eval_node(&node, &leaves, &universe, &mut ledger, &mut work),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    // -----------------------------------------------------------------------
    // T — transactional ledger accounting
    // -----------------------------------------------------------------------

    // T01 — a direct release with valid entries but excessive bytes mutates nothing.
    #[test]
    fn t01_direct_release_is_atomic_on_mixed_underflow() {
        let mut budget = CandidateBudget::new(&limits(100, 100));
        budget.begin_segment().unwrap();
        budget.reserve_segment(2, 10).unwrap();
        assert!(matches!(
            budget.release_segment(1, 11),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert_eq!(budget.segment_entries, 2);
        assert_eq!(budget.segment_bytes, 10);
        // A later valid release still succeeds.
        budget.release_segment(2, 10).unwrap();
        budget.end_segment().unwrap();
    }

    // T02 — ledger release preflights the ledger-local counters before the budget.
    #[test]
    fn t02_ledger_release_preflights_before_budget_mutation() {
        let mut budget = CandidateBudget::new(&limits(100, 100));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        ledger.reserve(2, 10).unwrap();
        // Inject an inconsistent local counter (fewer outstanding entries).
        ledger.outstanding_entries = 1;
        assert!(matches!(
            ledger.release(2, 5),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert_eq!(ledger.budget.segment_entries, 2);
        assert_eq!(ledger.budget.segment_bytes, 10);
        assert_eq!(ledger.outstanding_entries, 1);
        assert_eq!(ledger.outstanding_bytes, 10);
    }

    // T03 — transfer preflights both owners before any mutation.
    #[test]
    fn t03_transfer_preflights_ledger_state() {
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        ledger.reserve(2, 10).unwrap();
        ledger.outstanding_bytes = 5;
        assert!(matches!(
            ledger.transfer_to_global(1, 10),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert_eq!(ledger.budget.segment_entries, 2);
        assert_eq!(ledger.budget.segment_bytes, 10);
        assert_eq!(ledger.budget.global_bytes, 0);
        assert_eq!(ledger.outstanding_entries, 2);
        assert_eq!(ledger.outstanding_bytes, 5);
    }

    // T04 — reserve rejects an inconsistent ledger without touching the budget.
    #[test]
    fn t04_reserve_preflights_ledger_state() {
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        ledger.reserve(2, 10).unwrap();
        ledger.outstanding_entries = u64::MAX;
        assert!(matches!(
            ledger.reserve(1, 1),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert_eq!(ledger.budget.segment_entries, 2);
        assert_eq!(ledger.budget.segment_bytes, 10);
    }

    // T05 — checked overflow in reserve/transfer is typed and atomic.
    #[test]
    fn t05_near_max_overflow_is_typed_and_atomic() {
        let mut budget = CandidateBudget {
            max_segment_entries: u64::MAX,
            max_total_bytes: u64::MAX,
            global_bytes: 0,
            segment_entries: 0,
            segment_bytes: 0,
        };
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        ledger.reserve(u64::MAX, 0).unwrap();
        assert!(matches!(
            ledger.reserve(1, 0),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(ledger.budget.segment_entries, u64::MAX);
        assert_eq!(ledger.outstanding_entries, u64::MAX);
        assert!(matches!(
            ledger.transfer_to_global(1, 1),
            Err(SearchError::CorruptIndex { .. })
        ));
        assert_eq!(ledger.budget.global_bytes, 0);
    }

    // T06 — a valid sequence reaches zero with global bytes retained.
    #[test]
    fn t06_valid_sequence_reaches_consistent_zero() {
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        ledger.reserve(2, 10).unwrap();
        ledger.release(1, 4).unwrap();
        ledger.reserve(3, 6).unwrap();
        ledger.transfer_to_global(2, 8).unwrap();
        ledger.release(2, 4).unwrap();
        ledger.finish().unwrap();
        assert_eq!(ledger.budget.segment_entries, 0);
        assert_eq!(ledger.budget.segment_bytes, 0);
        assert_eq!(ledger.budget.global_bytes, 8);
    }

    // T07 — seeded operation sequence against an independent tuple model.
    #[test]
    fn t07_seeded_transactions_match_tuple_model() {
        #[derive(Clone, Copy, Debug)]
        enum Op {
            Reserve(u64, u64),
            Release(u64, u64),
            Transfer(u64, u64),
        }
        #[derive(Clone, Copy, Debug, PartialEq, Eq)]
        struct Model {
            global: u64,
            seg_e: u64,
            seg_b: u64,
            out_e: u64,
            out_b: u64,
        }
        const MAX_E: u64 = 50;
        const MAX_B: u64 = 300;
        let mut rng_state: u64 = 0xA303_0000_0000_0001;
        let mut next = move || {
            rng_state = rng_state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            rng_state >> 33
        };
        let mut budget = CandidateBudget::new(&limits(MAX_E, MAX_B));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        let mut model = Model {
            global: 0,
            seg_e: 0,
            seg_b: 0,
            out_e: 0,
            out_b: 0,
        };

        let apply = |model: &mut Model, op: Op| -> bool {
            let consistent = model.out_e == model.seg_e && model.out_b == model.seg_b;
            match op {
                Op::Reserve(e, b) => {
                    if !consistent {
                        return false;
                    }
                    let (Some(ne), Some(nb), Some(oe), Some(ob)) = (
                        model.seg_e.checked_add(e),
                        model.seg_b.checked_add(b),
                        model.out_e.checked_add(e),
                        model.out_b.checked_add(b),
                    ) else {
                        return false;
                    };
                    let Some(total) = model.global.checked_add(nb) else {
                        return false;
                    };
                    if ne > MAX_E || total > MAX_B {
                        return false;
                    }
                    model.seg_e = ne;
                    model.seg_b = nb;
                    model.out_e = oe;
                    model.out_b = ob;
                    true
                }
                Op::Release(e, b) => {
                    if consistent
                        && e <= model.seg_e
                        && e <= model.out_e
                        && b <= model.seg_b
                        && b <= model.out_b
                    {
                        model.seg_e -= e;
                        model.seg_b -= b;
                        model.out_e -= e;
                        model.out_b -= b;
                        true
                    } else {
                        false
                    }
                }
                Op::Transfer(e, b) => {
                    if consistent
                        && e <= model.seg_e
                        && e <= model.out_e
                        && b <= model.seg_b
                        && b <= model.out_b
                    {
                        let new_global = model.global.checked_add(b);
                        let new_seg_b = model.seg_b - b;
                        let total = new_global.and_then(|g| g.checked_add(new_seg_b));
                        if let (Some(g), Some(t)) = (new_global, total) {
                            if t <= MAX_B {
                                model.global = g;
                                model.seg_e -= e;
                                model.seg_b = new_seg_b;
                                model.out_e -= e;
                                model.out_b -= b;
                                return true;
                            }
                        }
                        false
                    } else {
                        false
                    }
                }
            }
        };

        // Seed a non-zero consistent state.
        assert!(apply(&mut model, Op::Reserve(10, 100)));
        ledger.reserve(10, 100).unwrap();

        for step in 0..300 {
            let op = match next() % 3 {
                0 => Op::Reserve(next() % 9, next() % 31),
                1 => Op::Release(next() % 9, next() % 31),
                _ => Op::Transfer(next() % 9, next() % 31),
            };
            let expected = apply(&mut model, op);
            let actual = match op {
                Op::Reserve(e, b) => ledger.reserve(e, b),
                Op::Release(e, b) => ledger.release(e, b),
                Op::Transfer(e, b) => ledger.transfer_to_global(e, b),
            };
            assert_eq!(actual.is_ok(), expected, "step {step} op {op:?}");
            assert_eq!(
                ledger.budget.global_bytes, model.global,
                "step {step} global"
            );
            assert_eq!(
                ledger.budget.segment_entries, model.seg_e,
                "step {step} seg_e"
            );
            assert_eq!(
                ledger.budget.segment_bytes, model.seg_b,
                "step {step} seg_b"
            );
            assert_eq!(ledger.outstanding_entries, model.out_e, "step {step} out_e");
            assert_eq!(ledger.outstanding_bytes, model.out_b, "step {step} out_b");
        }
    }

    // T08 — Drop cleans up consistent state and never fabricates a repair.
    #[test]
    fn t08_drop_cleanup_and_injected_inconsistency() {
        // Consistent state cleans up fully.
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        {
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger.reserve(2, 10).unwrap();
        }
        assert_eq!(budget.segment_entries, 0);
        assert_eq!(budget.segment_bytes, 0);
        budget.begin_segment().unwrap();

        // Injected inconsistency cannot silently touch unrelated global bytes.
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        {
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger.reserve(2, 10).unwrap();
            ledger.outstanding_entries = 1;
            assert!(ledger.release(2, 10).is_err());
        }
        assert_eq!(budget.global_bytes, 0);
        assert_eq!(budget.segment_entries, 1);
    }
    // C1 — candidate local preflight/commit transactional primitives.
    #[test]
    fn c1_local_segment_exact_then_one_over_atomic() {
        let mut budget = CandidateBudget::new(&limits(100, 100));
        budget.reserve_segment(100, 50).unwrap();
        let snapshot = (
            budget.segment_entries,
            budget.segment_bytes,
            budget.global_bytes,
        );
        assert_eq!(snapshot, (100, 50, 0));
        // Entry ceiling one-over.
        assert!(budget.reserve_segment(1, 0).is_err());
        assert_eq!(
            (
                budget.segment_entries,
                budget.segment_bytes,
                budget.global_bytes
            ),
            snapshot
        );
        // Byte ceiling one-over.
        assert!(budget.preflight_segment(0, 51).is_err());
        assert_eq!(
            (
                budget.segment_entries,
                budget.segment_bytes,
                budget.global_bytes
            ),
            snapshot
        );
    }

    #[test]
    fn c1_global_exact_then_one_over_atomic() {
        let mut budget = CandidateBudget::new(&limits(100, 100));
        budget.reserve_global_bytes(100).unwrap();
        assert_eq!(budget.global_bytes, 100);
        assert!(budget.reserve_global_bytes(1).is_err());
        assert_eq!(budget.global_bytes, 100);
    }

    #[test]
    fn c1_overflow_atomic() {
        let budget = CandidateBudget {
            max_segment_entries: u64::MAX,
            max_total_bytes: u64::MAX,
            global_bytes: u64::MAX,
            segment_entries: 0,
            segment_bytes: 0,
        };
        assert!(budget.preflight_global_bytes(1).is_err());
        assert_eq!(budget.global_bytes, u64::MAX);
        assert!(budget.preflight_segment(0, 1).is_err());
        assert_eq!(budget.segment_bytes, 0);
        assert_eq!(budget.global_bytes, u64::MAX);
    }

    #[test]
    fn c1_release_underflow_atomic() {
        let mut budget = CandidateBudget {
            max_segment_entries: 100,
            max_total_bytes: 100,
            global_bytes: 10,
            segment_entries: 5,
            segment_bytes: 5,
        };
        assert!(budget.release_global_bytes(11).is_err());
        assert_eq!(budget.global_bytes, 10);
        assert!(budget.release_segment(6, 0).is_err());
        assert_eq!(budget.segment_entries, 5);
        assert!(budget.release_segment(0, 6).is_err());
        assert_eq!(budget.segment_bytes, 5);
    }

    #[test]
    fn c1_existing_callers_parity() {
        let mut combined = CandidateBudget::new(&limits(100, 1_000));
        combined.reserve_global_bytes(50).unwrap();
        combined.reserve_segment(3, 40).unwrap();

        let mut split = CandidateBudget::new(&limits(100, 1_000));
        split.preflight_global_bytes(50).unwrap();
        split.commit_global_bytes(50);
        split.preflight_segment(3, 40).unwrap();
        split.commit_segment(3, 40);

        assert_eq!(combined.global_bytes, split.global_bytes);
        assert_eq!(combined.segment_entries, split.segment_entries);
        assert_eq!(combined.segment_bytes, split.segment_bytes);
    }
    // C2 — segment ledger ephemeral batch-memory sink.
    #[test]
    fn c2_segment_exact_and_one_over_atomic() {
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(100);
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger
                .reserve_with_memory(1, 100, Some(&mut scope))
                .unwrap();
            assert_eq!(scope.temporary_bytes(), 100);
            // Local would allow 101 bytes; batch rejects first.
            assert!(ledger.reserve_with_memory(0, 1, Some(&mut scope)).is_err());
            assert_eq!(scope.temporary_bytes(), 100);
            ledger
                .release_with_memory(1, 100, Some(&mut scope))
                .unwrap();
            assert_eq!(scope.temporary_bytes(), 0);
            ledger.finish().unwrap();
        }
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn c2_local_reject_no_batch_change() {
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(1_000);
        let mut budget = CandidateBudget::new(&limits(100, 10));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger.reserve_with_memory(1, 10, Some(&mut scope)).unwrap();
            assert!(ledger.reserve_with_memory(0, 1, Some(&mut scope)).is_err());
            assert_eq!(scope.temporary_bytes(), 10);
        }
        // Scope drop releases the batch reservation without a leak.
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn c2_release_underflow_no_mutation() {
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(100);
        let mut budget = CandidateBudget::new(&limits(100, 100));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger.reserve_with_memory(1, 10, Some(&mut scope)).unwrap();
            assert!(ledger.release_with_memory(2, 10, Some(&mut scope)).is_err());
            assert_eq!(scope.temporary_bytes(), 10);
        }
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn c2_two_segment_reuse_single_scope() {
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(100);
        let mut budget = CandidateBudget::new(&limits(100, 100));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            for _ in 0..2 {
                let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
                ledger.reserve_with_memory(1, 10, Some(&mut scope)).unwrap();
                assert_eq!(scope.temporary_bytes(), 10);
                ledger.release_with_memory(1, 10, Some(&mut scope)).unwrap();
                assert_eq!(scope.temporary_bytes(), 0);
                ledger.finish().unwrap();
            }
        }
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn c2_standalone_none_parity() {
        let mut local = CandidateBudget::new(&limits(100, 1_000));
        let mut none = CandidateBudget::new(&limits(100, 1_000));
        {
            let mut ledger = SegmentCandidateLedger::new(&mut local).unwrap();
            ledger.reserve(2, 20).unwrap();
            ledger.release(2, 20).unwrap();
            ledger.finish().unwrap();
        }
        {
            let mut ledger = SegmentCandidateLedger::new(&mut none).unwrap();
            ledger.reserve_with_memory(2, 20, None).unwrap();
            ledger.release_with_memory(2, 20, None).unwrap();
            ledger.finish().unwrap();
        }
        assert_eq!(local.segment_entries, none.segment_entries);
        assert_eq!(local.segment_bytes, none.segment_bytes);
        assert_eq!(local.global_bytes, none.global_bytes);
    }
    // C2 acceptance — postings materialization uses the batch sink.
    #[test]
    fn c2_postings_exact_and_one_over() {
        // 3 live docs and 3 term postings; independent constants.
        let live = 3 * LIVE_SET_BYTES_PER_ENTRY;
        let postings = 3 * TERM_POSTING_BYTES;

        // Exact peak (live + postings) succeeds.
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(live + postings);
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger
                .reserve_with_memory(3, live, Some(&mut scope))
                .unwrap();
            ledger
                .reserve_with_memory(3, postings, Some(&mut scope))
                .unwrap();
            assert_eq!(scope.temporary_bytes(), live + postings);
            ledger
                .release_with_memory(3, postings, Some(&mut scope))
                .unwrap();
            ledger
                .release_with_memory(3, live, Some(&mut scope))
                .unwrap();
            ledger.finish().unwrap();
        }
        assert_eq!(meter.current(), 0);

        // One byte under the peak rejects the postings reservation atomically.
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(live + postings - 1);
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger
                .reserve_with_memory(3, live, Some(&mut scope))
                .unwrap();
            assert!(
                ledger
                    .reserve_with_memory(3, postings, Some(&mut scope))
                    .is_err()
            );
            assert_eq!(scope.temporary_bytes(), live);
            // Local still owns the live reservation; release succeeds.
            ledger
                .release_with_memory(3, live, Some(&mut scope))
                .unwrap();
            ledger.finish().unwrap();
        }
        assert_eq!(meter.current(), 0);
    }

    // C2 acceptance — phrase scratch uses the batch sink and cleans up.
    #[test]
    fn c2_phrase_scratch_exact_and_one_over() {
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(PHRASE_SCRATCH_REF_BYTES);
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            {
                let mut scratch = PhraseScratch::new(&mut ledger);
                scratch
                    .reserve(1, PHRASE_SCRATCH_REF_BYTES, Some(&mut scope))
                    .unwrap();
                assert_eq!(scope.temporary_bytes(), PHRASE_SCRATCH_REF_BYTES);
                assert!(scratch.reserve(1, 1, Some(&mut scope)).is_err());
                assert_eq!(scope.temporary_bytes(), PHRASE_SCRATCH_REF_BYTES);
                scratch
                    .release(1, PHRASE_SCRATCH_REF_BYTES, Some(&mut scope))
                    .unwrap();
                assert_eq!(scope.temporary_bytes(), 0);
            }
            ledger.finish().unwrap();
        }
        assert_eq!(meter.current(), 0);
    }

    // C2 acceptance — scored-map materialization uses the batch sink.
    #[test]
    fn c2_scored_map_exact_and_one_over() {
        let matched = SET_BYTES_PER_ENTRY;
        let scored = SCORED_MAP_BYTES_PER_ENTRY;
        let exact = matched + scored;

        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(exact);
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger
                .reserve_with_memory(1, matched, Some(&mut scope))
                .unwrap();
            ledger
                .reserve_with_memory(1, scored, Some(&mut scope))
                .unwrap();
            assert_eq!(scope.temporary_bytes(), exact);
            ledger
                .release_with_memory(1, scored, Some(&mut scope))
                .unwrap();
            ledger
                .release_with_memory(1, matched, Some(&mut scope))
                .unwrap();
            ledger.finish().unwrap();
        }
        assert_eq!(meter.current(), 0);

        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(exact - 1);
        let mut budget = CandidateBudget::new(&limits(100, 10_000));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
            ledger
                .reserve_with_memory(1, matched, Some(&mut scope))
                .unwrap();
            assert!(
                ledger
                    .reserve_with_memory(1, scored, Some(&mut scope))
                    .is_err()
            );
            assert_eq!(scope.temporary_bytes(), matched);
            ledger
                .release_with_memory(1, matched, Some(&mut scope))
                .unwrap();
            ledger.finish().unwrap();
        }
        assert_eq!(meter.current(), 0);
    }

    // C2 acceptance — cancellation abandons phrase scratch; the slot scope
    // releases the batch charge even though PhraseScratch::Drop is local-only.
    #[test]
    fn c2_cancel_phrase_cleanup() {
        let mut meter = super::super::batch_meter::BatchMemoryMeter::new(100);
        let mut budget = CandidateBudget::new(&limits(100, 1_000));
        {
            let mut scope = super::super::memory::SlotMemoryScope::new(&mut meter);
            {
                let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
                {
                    let mut scratch = PhraseScratch::new(&mut ledger);
                    scratch
                        .reserve(1, PHRASE_SCRATCH_DOC_BYTES, Some(&mut scope))
                        .unwrap();
                    // Abandon without explicit release (cancellation path).
                }
                // PhraseScratch::Drop released the local charge only.
            }
            // Slot scope releases the remaining batch temporary charge.
        }
        assert_eq!(meter.current(), 0);
    }

    /// Deterministic cancellation object for polling-parity tests. Its counter is
    /// not a timer: it only controls when `is_cancelled` first returns `true`.
    struct B2PollCancel {
        checks: std::cell::Cell<usize>,
        fail_at: usize,
    }

    impl crate::analysis::Cancellation for B2PollCancel {
        fn is_cancelled(&self) -> bool {
            let before = self.checks.get();
            self.checks.set(before + 1);
            before >= self.fail_at
        }
    }

    /// Test-only preserved copy of the historical bitmap-recounting helper body.
    /// Used solely to compare cancellation-poll schedules; never production code.
    fn b2_legacy_recount_for_test(live: &[bool], meter: &MixedWorkMeter<'_>) -> SearchResult<u64> {
        meter.check_cancelled()?;
        let mut count: u64 = 0;
        for chunk in live.chunks(EXAMINATION_COUNT_CHUNK) {
            for flag in chunk {
                if *flag {
                    count = count.checked_add(1).ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
                }
            }
            meter.check_cancelled()?;
        }
        meter.check_cancelled()?;
        Ok(count)
    }

    // PERF-05-B2 U04: the reuse helper returns the verified count at every chunk
    // edge (empty, exact chunk, one over, multiples) for dead/live/mixed bitmaps.
    #[test]
    fn b2_u04_count_helper_chunk_edges() {
        use crate::analysis::NeverCancel;
        for slots in [0usize, 1, 4095, 4096, 4097, 8192, 8193] {
            let patterns = [
                vec![false; slots],
                vec![true; slots],
                (0..slots).map(|index| index % 5 != 0).collect::<Vec<_>>(),
            ];
            for flags in patterns {
                let expected = flags.iter().filter(|flag| **flag).count() as u64;
                let meter = MixedWorkMeter::new(u64::MAX, u64::MAX, u64::MAX, &NeverCancel);
                let count = effective_live_examination_count(&flags, expected, &meter)
                    .expect("verified count");
                assert_eq!(count, expected, "slots={slots}");
            }
        }
    }

    // PERF-05-B2 U05: the logical charge still equals the exact number of
    // effective-live flags, not the bitmap slot count or a postings count.
    #[test]
    fn b2_u05_helper_preserves_work_charge() {
        use crate::analysis::NeverCancel;
        for slots in [0usize, 1, 4095, 4096, 4097, 8192, 8193] {
            let flags: Vec<bool> = (0..slots).map(|index| index % 4 != 0).collect();
            let expected = flags.iter().filter(|flag| **flag).count() as u64;

            let mut meter = MixedWorkMeter::new(u64::MAX, u64::MAX, u64::MAX, &NeverCancel);
            let count =
                effective_live_examination_count(&flags, expected, &meter).expect("verified count");
            if count > 0 {
                meter.charge_lexical(count).expect("charge");
            }
            assert_eq!(count, expected, "slots={slots}");
            assert_eq!(meter.total_used(), expected, "slots={slots}");
        }

        // Exact limit passes; one below is a typed ResourceLimit.
        let flags = vec![true; 10];
        let expected = 10u64;
        let mut exact = MixedWorkMeter::new(expected, u64::MAX, u64::MAX, &NeverCancel);
        let count = effective_live_examination_count(&flags, expected, &exact).expect("count");
        exact.charge_lexical(count).expect("exact limit");
        assert_eq!(exact.total_used(), expected);

        let mut tight = MixedWorkMeter::new(expected - 1, u64::MAX, u64::MAX, &NeverCancel);
        let count = effective_live_examination_count(&flags, expected, &tight).expect("count");
        assert!(matches!(
            tight.charge_lexical(count),
            Err(SearchError::ResourceLimit { .. })
        ));

        // All-dead: no charge at all.
        let flags = vec![false; 4097];
        let mut meter = MixedWorkMeter::new(u64::MAX, u64::MAX, u64::MAX, &NeverCancel);
        let count = effective_live_examination_count(&flags, 0, &meter).expect("count");
        if count > 0 {
            meter.charge_lexical(count).expect("charge");
        }
        assert_eq!(count, 0);
        assert_eq!(meter.total_used(), 0);
    }

    // PERF-05-B2 U06: reuse helper and the preserved legacy recount perform the
    // same cancellation polls in the same order at every chunk edge.
    #[test]
    fn b2_u06_cancel_poll_schedule_same_as_legacy() {
        // Expected successful cancellation checks: leading + per chunk + trailing.
        let cases = [
            (0usize, 2usize),
            (1, 3),
            (4095, 3),
            (4096, 3),
            (4097, 4),
            (8192, 4),
            (8193, 5),
        ];
        for (slots, required) in cases {
            let flags: Vec<bool> = (0..slots).map(|index| index % 3 != 0).collect();
            let expected = flags.iter().filter(|flag| **flag).count() as u64;
            for fail_at in 0..=(required + 1) {
                let old_cancel = B2PollCancel {
                    checks: std::cell::Cell::new(0),
                    fail_at,
                };
                let old_meter = MixedWorkMeter::new(u64::MAX, u64::MAX, u64::MAX, &old_cancel);
                let old = b2_legacy_recount_for_test(&flags, &old_meter);

                let new_cancel = B2PollCancel {
                    checks: std::cell::Cell::new(0),
                    fail_at,
                };
                let new_meter = MixedWorkMeter::new(u64::MAX, u64::MAX, u64::MAX, &new_cancel);
                let new = effective_live_examination_count(&flags, expected, &new_meter);

                match (&old, &new) {
                    (Ok(old_count), Ok(new_count)) => {
                        assert_eq!(*old_count, expected);
                        assert_eq!(*new_count, expected);
                        // With no cancellation triggered, exactly `required` polls ran.
                        assert_eq!(old_cancel.checks.get(), required);
                        assert_eq!(new_cancel.checks.get(), required);
                    }
                    (Err(SearchError::Cancelled), Err(SearchError::Cancelled)) => {}
                    _ => panic!(
                        "divergent outcomes slots={slots} fail_at={fail_at}: old={old:?} new={new:?}"
                    ),
                }
                assert_eq!(
                    old_cancel.checks.get(),
                    new_cancel.checks.get(),
                    "poll count divergence slots={slots} fail_at={fail_at}"
                );
            }
        }
    }

    /// Test-only adapter: drive the real production `score_segment` from either a
    /// `BTreeSet` or a `Vec` exact-sized iterator, then release the real reservation.
    fn b3_score_from_iterator<'a>(
        ids: impl ExactSizeIterator<Item = &'a u64>,
        leaf_data: &[LeafData],
        stats: &SnapshotStats<'_>,
        positive: &BTreeSet<usize>,
    ) -> (Vec<(u64, u64)>, Charges) {
        let limits = SearchLimits::default();
        let mut budget = CandidateBudget::new(&limits);
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        let (scored, charges) =
            score_segment(ids, leaf_data, stats, 0, positive, &mut ledger, None).unwrap();
        let result_bits = scored
            .into_iter()
            .map(|(doc_id, score)| (doc_id, score.to_bits()))
            .collect::<Vec<_>>();
        ledger.release(charges.entries, charges.bytes).unwrap();
        ledger.finish().unwrap();
        (result_bits, charges)
    }

    // PERF-05-B3 U01: one scorer accepts the sibling BTreeSet iterator and the new
    // unified ordered-Vec iterator with identical keys, zero scores and charges.
    #[test]
    fn b3_u01_scorer_accepts_tree_and_vec_iterators() {
        use crate::analysis::NeverCancel;

        let cancel = NeverCancel;
        let limits = SearchLimits::default();
        let readers: [&SegmentReader; 0] = [];
        let live: Vec<Rc<Vec<bool>>> = Vec::new();
        let terms: super::super::score::QueryTerms = BTreeMap::new();
        let mut work = SearchWork::new(limits.max_total_work_units(), &cancel);
        let stats = compute_stats(&readers, &live, &[], &terms, &limits, &mut work, &cancel)
            .expect("empty scoring stats");
        let positive = BTreeSet::<usize>::new();
        let leaves: Vec<LeafData> = Vec::new();
        let cases: [&[u64]; 4] = [&[], &[0], &[0, 3, 9], &[0, 1, 2, 3]];

        for case in cases {
            let ordered = case.to_vec();
            let tree: BTreeSet<u64> = ordered.iter().copied().collect();
            let (from_tree, tree_charge) =
                b3_score_from_iterator(tree.iter(), &leaves, &stats, &positive);
            let (from_vec, vec_charge) =
                b3_score_from_iterator(ordered.iter(), &leaves, &stats, &positive);
            let expected: Vec<(u64, u64)> =
                case.iter().map(|doc| (*doc, 0.0f64.to_bits())).collect();
            assert_eq!(from_tree, expected);
            assert_eq!(from_vec, expected);
            assert_eq!(tree_charge, vec_charge);
            assert_eq!(vec_charge.entries, case.len() as u64);
            assert_eq!(
                vec_charge.bytes,
                case.len() as u64 * SCORED_MAP_BYTES_PER_ENTRY
            );
        }
    }

    // PERF-05-B3 U02: real decoded postings over the real norms fixture produce
    // bit-identical BM25 from the BTreeSet and ordered-Vec iterator sources.
    #[test]
    fn b3_u02_positive_bm25_tree_and_vec_score_bits_match() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = reader.schema().field_id("title").expect("title field");
        let cancel = NeverCancel;
        let limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));
        let mut work = SearchWork::new(limits.max_total_work_units(), &cancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &cancel,
        )
        .expect("real field norms");

        let mut source = reader
            .postings(field_id, "hello")
            .unwrap()
            .expect("hello postings");
        let mut postings: Vec<(u64, u64)> = Vec::new();
        while let Some(posting) = source.next_with(&cancel).unwrap() {
            postings.push((posting.doc_id, posting.freq));
        }
        assert!(!postings.is_empty());
        let ordered: Vec<u64> = postings.iter().map(|(doc_id, _)| *doc_id).collect();
        let tree: BTreeSet<u64> = ordered.iter().copied().collect();
        assert_eq!(tree.len(), ordered.len());
        let leaf_data = vec![LeafData::Term {
            field_id,
            terms: vec![TermPostings {
                term: "hello".to_owned(),
                postings,
            }],
        }];
        let positive = BTreeSet::from([0usize]);

        let (tree_bits, tree_charge) =
            b3_score_from_iterator(tree.iter(), &leaf_data, &stats, &positive);
        let (vec_bits, vec_charge) =
            b3_score_from_iterator(ordered.iter(), &leaf_data, &stats, &positive);
        assert_eq!(tree_bits, vec_bits);
        assert_eq!(tree_charge, vec_charge);
        assert_eq!(vec_charge.entries, ordered.len() as u64);
        assert!(
            tree_bits
                .iter()
                .all(|(_, bits)| f64::from_bits(*bits).is_finite())
        );
        assert!(
            tree_bits
                .iter()
                .all(|(_, bits)| f64::from_bits(*bits) > 0.0)
        );
    }

    /// Test-only adapter: run the generic `score_segment` under the evaluator's
    /// modeled protocol (48-byte matched reservation, then 64-byte scored).
    fn b4_generic_scored_bits_result(
        ids: &[u64],
        leaf_data: &[LeafData],
        stats: &SnapshotStats<'_>,
        positive: &BTreeSet<usize>,
    ) -> SearchResult<(Vec<(u64, u64)>, Charges)> {
        let limits = SearchLimits::default();
        let mut budget = CandidateBudget::new(&limits);
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        let entries = ids.len() as u64;
        let bytes = bytes_for_count(entries, SET_BYTES_PER_ENTRY)?;
        ledger.reserve(entries, bytes)?;
        let (scored, charges) =
            score_segment(ids.iter(), leaf_data, stats, 0, positive, &mut ledger, None)?;
        let bits = scored
            .into_iter()
            .map(|(doc_id, score)| (doc_id, score.to_bits()))
            .collect();
        ledger.release(entries, bytes)?;
        ledger.release(charges.entries, charges.bytes)?;
        ledger.finish()?;
        Ok((bits, charges))
    }

    fn b4_generic_scored_bits(
        ids: &[u64],
        leaf_data: &[LeafData],
        stats: &SnapshotStats<'_>,
        positive: &BTreeSet<usize>,
    ) -> (Vec<(u64, u64)>, Charges) {
        b4_generic_scored_bits_result(ids, leaf_data, stats, positive).unwrap()
    }

    /// Test-only adapter: run the B4 strict single-term helper under the same
    /// matched-then-scored modeled reservation protocol.
    fn b4_single_term_scored_bits_result(
        pairs: &[(u64, u64)],
        field_id: u32,
        term: &str,
        stats: &SnapshotStats<'_>,
        positive: &BTreeSet<usize>,
    ) -> SearchResult<(Vec<(u64, u64)>, Charges)> {
        let limits = SearchLimits::default();
        let mut budget = CandidateBudget::new(&limits);
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        let entries = pairs.len() as u64;
        let bytes = bytes_for_count(entries, SET_BYTES_PER_ENTRY)?;
        ledger.reserve(entries, bytes)?;
        let (scored, charges) = score_single_term_candidates(
            pairs,
            field_id,
            term,
            stats,
            0,
            positive,
            &mut ledger,
            None,
        )?;
        let bits = scored
            .into_iter()
            .map(|(doc_id, score)| (doc_id, score.to_bits()))
            .collect();
        ledger.release(entries, bytes)?;
        ledger.release(charges.entries, charges.bytes)?;
        ledger.finish()?;
        Ok((bits, charges))
    }

    fn b4_single_term_scored_bits(
        pairs: &[(u64, u64)],
        field_id: u32,
        term: &str,
        stats: &SnapshotStats<'_>,
        positive: &BTreeSet<usize>,
    ) -> (Vec<(u64, u64)>, Charges) {
        b4_single_term_scored_bits_result(pairs, field_id, term, stats, positive).unwrap()
    }

    // PERF-05-B4 U01 — red-first: the strict single-term helper must reproduce the
    // generic scorer's bit-exact BM25 over real decoded norms postings.
    #[test]
    fn b4_u01_single_term_scores_match_generic_bm25_bits() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = reader.schema().field_id("title").expect("title field");
        let limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();

        let mut source = reader
            .postings(field_id, "hello")
            .unwrap()
            .expect("hello postings");
        let mut postings: Vec<(u64, u64)> = Vec::new();
        while let Some(posting) = source.next_with(&NeverCancel).unwrap() {
            postings.push((posting.doc_id, posting.freq));
        }
        assert!(!postings.is_empty());
        let ids: Vec<u64> = postings.iter().map(|(doc_id, _)| *doc_id).collect();
        let leaf_data = vec![LeafData::Term {
            field_id,
            terms: vec![TermPostings {
                term: "hello".to_owned(),
                postings: postings.clone(),
            }],
        }];
        let positive = BTreeSet::from([0usize]);

        let (generic_bits, generic_charge) =
            b4_generic_scored_bits(&ids, &leaf_data, &stats, &positive);
        let (single_bits, single_charge) =
            b4_single_term_scored_bits(&postings, field_id, "hello", &stats, &positive);

        assert_eq!(generic_bits, single_bits);
        assert_eq!(generic_charge, single_charge);
        assert_eq!(single_charge.entries, postings.len() as u64);
        assert_eq!(
            single_charge.bytes,
            postings.len() as u64 * SCORED_MAP_BYTES_PER_ENTRY
        );
        assert!(
            single_bits
                .iter()
                .all(|(_, bits)| f64::from_bits(*bits).is_finite())
        );
        assert!(
            single_bits
                .iter()
                .all(|(_, bits)| f64::from_bits(*bits) > 0.0)
        );
    }

    // PERF-05-B4 U02 — empty and selected subsets keep bit-exact parity; the
    // reference leaf still contains every decoded posting.
    #[test]
    fn b4_u02_empty_and_selected_subset_score_parity() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = reader.schema().field_id("title").expect("title field");
        let limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();

        let mut source = reader
            .postings(field_id, "hello")
            .unwrap()
            .expect("hello postings");
        let mut postings: Vec<(u64, u64)> = Vec::new();
        while let Some(posting) = source.next_with(&NeverCancel).unwrap() {
            postings.push((posting.doc_id, posting.freq));
        }
        let leaf_data = vec![LeafData::Term {
            field_id,
            terms: vec![TermPostings {
                term: "hello".to_owned(),
                postings: postings.clone(),
            }],
        }];
        let positive = BTreeSet::from([0usize]);
        let mut subsets: Vec<Vec<(u64, u64)>> = vec![Vec::new()];
        subsets.push(postings.iter().take(1).copied().collect());
        subsets.push(postings.clone());

        for subset in subsets {
            let ids: Vec<u64> = subset.iter().map(|(doc_id, _)| *doc_id).collect();
            let (generic_bits, generic_charge) =
                b4_generic_scored_bits(&ids, &leaf_data, &stats, &positive);
            let (single_bits, single_charge) =
                b4_single_term_scored_bits(&subset, field_id, "hello", &stats, &positive);
            assert_eq!(generic_bits, single_bits);
            assert_eq!(generic_charge, single_charge);
            assert_eq!(generic_bits.len(), subset.len());
            if subset.is_empty() {
                assert!(generic_bits.is_empty());
                assert_eq!(single_charge.entries, 0);
                assert_eq!(single_charge.bytes, 0);
            }
        }
    }

    // PERF-05-B4 U05 — modeled 48M matched + 64M scored peak is exact; one below
    // fails with the same typed ResourceLimit and RAII cleanup.
    #[test]
    fn b4_u05_scored_reservation_exact_and_one_below() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = reader.schema().field_id("title").expect("title field");
        let base_limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));
        let mut work = SearchWork::new(base_limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &base_limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();
        let mut source = reader
            .postings(field_id, "hello")
            .unwrap()
            .expect("hello postings");
        let mut postings: Vec<(u64, u64)> = Vec::new();
        while let Some(posting) = source.next_with(&NeverCancel).unwrap() {
            postings.push((posting.doc_id, posting.freq));
        }
        let positive = BTreeSet::from([0usize]);
        let m = postings.len() as u64;
        let matched_bytes = bytes_for_count(m, SET_BYTES_PER_ENTRY).unwrap();
        let scored_bytes = bytes_for_count(m, SCORED_MAP_BYTES_PER_ENTRY).unwrap();
        let peak = matched_bytes + scored_bytes;

        // Exact modeled peak passes and charges the same 64-byte scored entries.
        let mut budget = CandidateBudget::new(&limits(1000, peak));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        ledger.reserve(m, matched_bytes).unwrap();
        let (_scored, charges) = score_single_term_candidates(
            &postings,
            field_id,
            "hello",
            &stats,
            0,
            &positive,
            &mut ledger,
            None,
        )
        .unwrap();
        assert_eq!(charges.entries, m);
        assert_eq!(charges.bytes, scored_bytes);
        ledger.release(m, matched_bytes).unwrap();
        ledger.release(charges.entries, charges.bytes).unwrap();
        ledger.finish().unwrap();

        // One byte below the peak fails at the scored admission with typed bounds.
        let mut budget = CandidateBudget::new(&limits(1000, peak - 1));
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        ledger.reserve(m, matched_bytes).unwrap();
        match score_single_term_candidates(
            &postings,
            field_id,
            "hello",
            &stats,
            0,
            &positive,
            &mut ledger,
            None,
        ) {
            Err(SearchError::ResourceLimit { limit, requested }) => {
                assert_eq!(limit, peak - 1);
                assert_eq!(requested, peak);
            }
            other => panic!("unexpected one-below outcome: {other:?}"),
        }
        drop(ledger);
        assert_eq!(budget.segment_entries, 0);
        assert_eq!(budget.segment_bytes, 0);
    }

    // PERF-05-B4 U06 — invalid df, missing field stats and absent owner all keep
    // the generic scorer's exact typed error / +0.0 score-bit behavior.
    #[test]
    fn b4_u06_invalid_df_and_zero_score_parity() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = reader.schema().field_id("title").expect("title field");
        let limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));

        let mut source = reader
            .postings(field_id, "hello")
            .unwrap()
            .expect("hello postings");
        let mut postings: Vec<(u64, u64)> = Vec::new();
        while let Some(posting) = source.next_with(&NeverCancel).unwrap() {
            postings.push((posting.doc_id, posting.freq));
        }
        let ids: Vec<u64> = postings.iter().map(|(doc_id, _)| *doc_id).collect();
        let leaf_data = vec![LeafData::Term {
            field_id,
            terms: vec![TermPostings {
                term: "hello".to_owned(),
                postings: postings.clone(),
            }],
        }];
        let positive = BTreeSet::from([0usize]);

        // Invalid df: mutate only the test-local prepared record's frequency, so
        // the deferred invalid-frequency error path is exercised unchanged.
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let mut stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();
        let n = stats.field(field_id).expect("field").n;
        stats
            .fields
            .get_mut(&field_id)
            .unwrap()
            .df
            .get_mut("hello")
            .expect("prepared record")
            .doc_freq = n + 1;
        let generic_err = b4_generic_scored_bits_result(&ids, &leaf_data, &stats, &positive);
        let single_err =
            b4_single_term_scored_bits_result(&postings, field_id, "hello", &stats, &positive);
        assert!(matches!(generic_err, Err(SearchError::InvalidScore { .. })));
        assert!(matches!(single_err, Err(SearchError::InvalidScore { .. })));

        // Missing field stats: both leave the initialized +0.0 score untouched.
        let empty_terms: super::super::score::QueryTerms = BTreeMap::new();
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let no_stats = compute_stats(
            &readers,
            &live,
            &[],
            &empty_terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();
        assert!(no_stats.field(field_id).is_none());
        let (generic_bits, _) = b4_generic_scored_bits(&ids, &leaf_data, &no_stats, &positive);
        let (single_bits, _) =
            b4_single_term_scored_bits(&postings, field_id, "hello", &no_stats, &positive);
        assert_eq!(generic_bits, single_bits);
        assert!(
            generic_bits
                .iter()
                .all(|(_, bits)| *bits == 0.0f64.to_bits())
        );

        // No positive owner: also +0.0 in both paths.
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let real_stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();
        let no_owner = BTreeSet::<usize>::new();
        let (generic_bits, _) = b4_generic_scored_bits(&ids, &leaf_data, &real_stats, &no_owner);
        let (single_bits, _) =
            b4_single_term_scored_bits(&postings, field_id, "hello", &real_stats, &no_owner);
        assert_eq!(generic_bits, single_bits);
        assert!(
            generic_bits
                .iter()
                .all(|(_, bits)| *bits == 0.0f64.to_bits())
        );
    }

    // PERF-05-B4 U07 — a frequency above 2^53 is carried as exact u64 until the
    // existing BM25 conversion, so both paths produce identical score bits.
    #[test]
    fn b4_u07_exact_u64_frequency_transport() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = reader.schema().field_id("title").expect("title field");
        let limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();

        let large = 9_007_199_254_740_993u64;
        let pairs = vec![(0u64, large)];
        let leaf_data = vec![LeafData::Term {
            field_id,
            terms: vec![TermPostings {
                term: "hello".to_owned(),
                postings: pairs.clone(),
            }],
        }];
        let positive = BTreeSet::from([0usize]);
        let ids = vec![0u64];
        let (generic_bits, _) = b4_generic_scored_bits(&ids, &leaf_data, &stats, &positive);
        let (single_bits, _) =
            b4_single_term_scored_bits(&pairs, field_id, "hello", &stats, &positive);
        assert_eq!(generic_bits, single_bits);
        assert!(
            single_bits
                .iter()
                .all(|(_, bits)| f64::from_bits(*bits).is_finite())
        );
    }

    // PERF-05-B5 U01 — red-first: the checked handoff must move the exact
    // original posting allocation (same pointer, length and capacity).
    #[test]
    fn b5_u01_handoff_moves_exact_vec_allocation() {
        test_observation::reset_postings_handoff();
        let original = vec![(0u64, 1u64), (3, 2), (9, 4)];
        let mut leaf_data = vec![LeafData::Term {
            field_id: 7,
            terms: vec![TermPostings {
                term: "alpha".to_owned(),
                postings: original.clone(),
            }],
        }];
        let (ptr, len, capacity) = match &leaf_data[0] {
            LeafData::Term { terms, .. } => {
                let postings = &terms[0].postings;
                (postings.as_ptr(), postings.len(), postings.capacity())
            }
            _ => panic!("expected term leaf"),
        };

        let moved = take_strict_one_term_postings(&mut leaf_data, false).unwrap();
        assert_eq!(moved, original);
        assert_eq!(moved.as_ptr(), ptr);
        assert_eq!(moved.len(), len);
        assert_eq!(moved.capacity(), capacity);
        match &leaf_data[0] {
            LeafData::Term { field_id, terms } => {
                assert_eq!(*field_id, 7);
                assert_eq!(terms[0].term, "alpha");
                assert!(terms[0].postings.is_empty());
            }
            _ => panic!("expected term leaf"),
        }
        assert_eq!(test_observation::postings_moves(), 1);
        assert_eq!(test_observation::postings_rejection_fallbacks(), 0);
    }

    // PERF-05-B5 U02 — lazy rejection selection keeps exact accepted subsets and
    // frequencies; only all-accepted/empty cases move the original allocation.
    #[test]
    fn b5_u02_lazy_rejection_selection_preserves_subsets() {
        struct B5Case {
            postings: Vec<(u64, u64)>,
            mask: Vec<bool>,
            expected: Vec<(u64, u64)>,
        }
        let base = vec![(0u64, 1u64), (3, 2), (7, 3), (9, 4)];
        let cases = vec![
            B5Case {
                postings: vec![],
                mask: vec![],
                expected: vec![],
            },
            B5Case {
                postings: base[..1].to_vec(),
                mask: vec![true],
                expected: base[..1].to_vec(),
            },
            B5Case {
                postings: base.clone(),
                mask: vec![true, true, true, true],
                expected: base.clone(),
            },
            B5Case {
                postings: base.clone(),
                mask: vec![true, true, false, true],
                expected: vec![(0, 1), (3, 2), (9, 4)],
            },
            B5Case {
                postings: base.clone(),
                mask: vec![false, true, false, true],
                expected: vec![(3, 2), (9, 4)],
            },
            B5Case {
                postings: base.clone(),
                mask: vec![false, false, false, false],
                expected: vec![],
            },
            B5Case {
                postings: base.clone(),
                mask: vec![true, true, true, false],
                expected: vec![(0, 1), (3, 2), (7, 3)],
            },
        ];

        for B5Case {
            postings,
            mask,
            expected,
        } in cases
        {
            let mut leaf_data = vec![LeafData::Term {
                field_id: 7,
                terms: vec![TermPostings {
                    term: "alpha".to_owned(),
                    postings: postings.clone(),
                }],
            }];
            test_observation::reset_postings_handoff();
            let mut selection = StrictTermMatchSelection::default();
            for (index, accepted) in mask.iter().copied().enumerate() {
                selection.observe(&postings, index, accepted);
            }
            let selected = selection.finish(&mut leaf_data, false).unwrap();
            assert_eq!(selected, expected);

            let saw_rejection = mask.iter().any(|accepted| !accepted);
            match &leaf_data[0] {
                LeafData::Term { terms, .. } => {
                    if saw_rejection {
                        assert_eq!(terms[0].postings, postings, "original must stay intact");
                        assert_eq!(test_observation::postings_moves(), 0);
                        assert_eq!(test_observation::postings_rejection_fallbacks(), 1);
                    } else {
                        assert!(terms[0].postings.is_empty());
                        assert_eq!(test_observation::postings_moves(), 1);
                        assert_eq!(test_observation::postings_rejection_fallbacks(), 0);
                    }
                }
                _ => panic!("expected term leaf"),
            }
        }
    }

    // PERF-05-B5 U03 — every non-eligible shape fails closed with the exact typed
    // detail and no mutation or witness activity.
    #[test]
    fn b5_u03_strict_handoff_shape_failure_nonmutating() {
        fn assert_shape_error(leaf_data: &mut [LeafData], typed_examination: bool) {
            match take_strict_one_term_postings(leaf_data, typed_examination) {
                Err(SearchError::CorruptIndex { detail }) => {
                    assert_eq!(detail, "single-term postings eligibility mismatch");
                }
                other => panic!("unexpected shape result: {other:?}"),
            }
        }

        test_observation::reset_postings_handoff();

        let mut empty: Vec<LeafData> = Vec::new();
        assert_shape_error(&mut empty, false);

        let mut phrase = vec![LeafData::Phrase {
            field_id: 7,
            matches: Vec::new(),
        }];
        assert_shape_error(&mut phrase, false);

        let make_term = || LeafData::Term {
            field_id: 7,
            terms: vec![TermPostings {
                term: "alpha".to_owned(),
                postings: vec![(0u64, 1u64)],
            }],
        };
        let mut two_leaves = vec![make_term(), make_term()];
        assert_shape_error(&mut two_leaves, false);

        let mut typed = vec![make_term()];
        assert_shape_error(&mut typed, true);

        let mut two_terms = vec![LeafData::Term {
            field_id: 7,
            terms: vec![
                TermPostings {
                    term: "alpha".to_owned(),
                    postings: vec![(0u64, 1u64)],
                },
                TermPostings {
                    term: "beta".to_owned(),
                    postings: vec![(2u64, 1u64)],
                },
            ],
        }];
        assert_shape_error(&mut two_terms, false);

        // The failing calls did not mutate the non-empty leaves.
        for leaf in [&two_leaves[0], &typed[0], &two_terms[0]] {
            match leaf {
                LeafData::Term { terms, .. } => {
                    assert!(terms.iter().all(|term| !term.postings.is_empty()));
                }
                _ => panic!("expected term leaf"),
            }
        }
        assert_eq!(test_observation::postings_moves(), 0);
        assert_eq!(test_observation::postings_rejection_fallbacks(), 0);
    }

    // ===== PERF-06-A1: query-local prepared BM25 term weights =====

    /// Frozen pre-A1 scalar BM25, restated in `execute.rs` so the referee never
    /// calls the prepared accessor it is checking.
    fn a1_frozen_scalar_bm25(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> SearchResult<f64> {
        if tf == 0 || n == 0 || avgdl <= 0.0 {
            return Ok(0.0);
        }
        if df > n {
            return Err(SearchError::InvalidScore {
                detail: "document frequency exceeds the live-document count",
            });
        }
        let tf = tf as f64;
        let df = df as f64;
        let n = n as f64;
        let dl = dl as f64;
        let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
        let k1 = super::super::score::BM25_K1;
        let b = super::super::score::BM25_B;
        let denominator = tf + k1 * (1.0 - b + b * dl / avgdl);
        let score = idf * (tf * (k1 + 1.0)) / denominator;
        if score.is_finite() && score >= 0.0 {
            Ok(score)
        } else {
            Err(SearchError::InvalidScore {
                detail: "BM25 produced a non-finite or negative score",
            })
        }
    }

    /// Test-only adapter: run the generic `score_segment` for an explicit segment
    /// ordinal under the modeled matched-then-scored reservation protocol.
    fn b4_generic_scored_bits_at(
        segment_index: usize,
        ids: &[u64],
        leaf_data: &[LeafData],
        stats: &SnapshotStats<'_>,
        positive: &BTreeSet<usize>,
    ) -> SearchResult<(Vec<(u64, u64)>, Charges)> {
        let limits = SearchLimits::default();
        let mut budget = CandidateBudget::new(&limits);
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        let entries = ids.len() as u64;
        let bytes = bytes_for_count(entries, SET_BYTES_PER_ENTRY)?;
        ledger.reserve(entries, bytes)?;
        let (scored, charges) = score_segment(
            ids.iter(),
            leaf_data,
            stats,
            segment_index,
            positive,
            &mut ledger,
            None,
        )?;
        let bits = scored
            .into_iter()
            .map(|(doc_id, score)| (doc_id, score.to_bits()))
            .collect();
        ledger.release(entries, bytes)?;
        ledger.release(charges.entries, charges.bytes)?;
        ledger.finish()?;
        Ok((bits, charges))
    }

    /// Test-only adapter: run the strict single-term helper for an explicit
    /// segment ordinal under the same modeled reservation protocol.
    #[allow(clippy::too_many_arguments)]
    fn b4_single_term_scored_bits_at(
        segment_index: usize,
        pairs: &[(u64, u64)],
        field_id: u32,
        term: &str,
        stats: &SnapshotStats<'_>,
        positive: &BTreeSet<usize>,
    ) -> SearchResult<(Vec<(u64, u64)>, Charges)> {
        let limits = SearchLimits::default();
        let mut budget = CandidateBudget::new(&limits);
        let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
        let entries = pairs.len() as u64;
        let bytes = bytes_for_count(entries, SET_BYTES_PER_ENTRY)?;
        ledger.reserve(entries, bytes)?;
        let (scored, charges) = score_single_term_candidates(
            pairs,
            field_id,
            term,
            stats,
            segment_index,
            positive,
            &mut ledger,
            None,
        )?;
        let bits = scored
            .into_iter()
            .map(|(doc_id, score)| (doc_id, score.to_bits()))
            .collect();
        ledger.release(entries, bytes)?;
        ledger.release(charges.entries, charges.bytes)?;
        ledger.finish()?;
        Ok((bits, charges))
    }

    fn a1_score_bits(pairs: &[(u64, u64)]) -> BTreeMap<u64, u64> {
        pairs.iter().copied().collect()
    }

    // A1-U04 — IDF is prepared once per valid positive `(field, term)`, across
    // every hit, repetition, scorer and segment, never per hit.
    #[test]
    fn a1_u04_idf_is_prepared_once_per_query_term() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const LEGACY: &[u8] = include_bytes!("../../tests/fixtures/segment/golden.seg");
        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let legacy = SegmentReader::open(LEGACY.to_vec(), SegmentLimits::default()).unwrap();
        let norms = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = legacy.schema().field_id("title").expect("title field");
        let limits = SearchLimits::default();
        let readers = [&legacy, &norms];
        let live = vec![Rc::new(vec![true, true]), Rc::new(vec![true, true])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));

        super::super::score::idf_observation::reset();
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .expect("two-segment stats");
        assert_eq!(
            super::super::score::idf_observation::count(),
            1,
            "one valid positive (field, term) prepares exactly one IDF"
        );
        assert_eq!(stats.field(field_id).expect("field").doc_freq("hello"), 4);

        let mut per_segment = Vec::new();
        for reader in [&legacy, &norms] {
            let mut source = reader
                .postings(field_id, "hello")
                .unwrap()
                .expect("hello postings");
            let mut postings: Vec<(u64, u64)> = Vec::new();
            while let Some(posting) = source.next_with(&NeverCancel).unwrap() {
                postings.push((posting.doc_id, posting.freq));
            }
            assert!(!postings.is_empty());
            per_segment.push(postings);
        }

        for (segment_index, postings) in per_segment.iter().enumerate() {
            let ids: Vec<u64> = postings.iter().map(|(doc_id, _)| *doc_id).collect();
            let leaf_data = vec![LeafData::Term {
                field_id,
                terms: vec![TermPostings {
                    term: "hello".to_owned(),
                    postings: postings.clone(),
                }],
            }];
            let positive = BTreeSet::from([0usize]);
            for _ in 0..3 {
                let (generic_bits, _) =
                    b4_generic_scored_bits_at(segment_index, &ids, &leaf_data, &stats, &positive)
                        .expect("generic score");
                let (single_bits, _) = b4_single_term_scored_bits_at(
                    segment_index,
                    postings,
                    field_id,
                    "hello",
                    &stats,
                    &positive,
                )
                .expect("strict score");
                assert_eq!(generic_bits, single_bits);
            }
        }
        assert_eq!(
            super::super::score::idf_observation::count(),
            1,
            "hits, repetitions, both scorers and both segments must reuse the weight"
        );

        // An independent query re-prepares; an absent (zero-df) term never does.
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .expect("fresh query stats");
        assert_eq!(super::super::score::idf_observation::count(), 2);

        let mut absent: super::super::score::QueryTerms = BTreeMap::new();
        absent.insert(field_id, BTreeSet::from(["absent_term".to_owned()]));
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let absent_stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &absent,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .expect("absent-term stats");
        assert_eq!(
            super::super::score::idf_observation::count(),
            2,
            "zero-df terms must not consume a logarithm"
        );
        assert_eq!(
            absent_stats
                .field(field_id)
                .expect("field")
                .doc_freq("absent_term"),
            0
        );
    }

    // A1-U07 — generic term/phrase owner attribution and the strict single-term
    // scorer agree with the frozen scalar formula per owner, never double-scoring
    // a repeated term and never scoring a non-positive leaf.
    #[test]
    fn a1_u07_owner_attribution_matches_frozen_scalar() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let field_id = reader.schema().field_id("title").expect("title field");
        let limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(
            field_id,
            BTreeSet::from(["hello".to_owned(), "there".to_owned()]),
        );
        super::super::score::idf_observation::reset();
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();
        assert_eq!(
            super::super::score::idf_observation::count(),
            2,
            "both present query terms must be prepared exactly once"
        );
        let field = stats.field(field_id).expect("field");
        let n = field.n;
        let avgdl = field.avgdl;
        let hello_df = field.doc_freq("hello");
        let there_df = field.doc_freq("there");
        // Both phrase and term contributions must come from prepared weights, so
        // their document frequencies have to be real, nonzero statistics.
        assert_eq!(hello_df, 2, "hello is in both fixture documents");
        assert_eq!(there_df, 1, "there is only in the first fixture document");
        let dl = field.length(0, 0);
        assert_eq!(field.length(0, 0), field.length(0, 1));

        // A duplicated term leaf must be scored exactly once per document.
        let hello = vec![(0u64, 1u64), (1, 1)];
        let leaf_data = vec![
            LeafData::Term {
                field_id,
                terms: vec![TermPostings {
                    term: "hello".to_owned(),
                    postings: hello.clone(),
                }],
            },
            LeafData::Term {
                field_id,
                terms: vec![TermPostings {
                    term: "hello".to_owned(),
                    postings: hello.clone(),
                }],
            },
            LeafData::Phrase {
                field_id,
                matches: vec![PhraseMatch {
                    doc_id: 0,
                    term_freqs: vec![("there".to_owned(), 1)],
                }],
            },
        ];
        let ids = vec![0u64, 1];
        let positive = BTreeSet::from([0usize, 1, 2]);
        let (bits, charges) = b4_generic_scored_bits_at(0, &ids, &leaf_data, &stats, &positive)
            .expect("generic score");
        let bits = a1_score_bits(&bits);

        let hello_contribution =
            a1_frozen_scalar_bm25(1, hello_df, n, dl, avgdl).expect("hello reference");
        let there_contribution =
            a1_frozen_scalar_bm25(1, there_df, n, dl, avgdl).expect("there reference");
        let expected_doc0 = (0.0_f64 + hello_contribution) + there_contribution;
        assert_eq!(
            bits[&0],
            expected_doc0.to_bits(),
            "doc 0 = hello (owned once) + phrase there"
        );
        assert_eq!(
            bits[&1],
            hello_contribution.to_bits(),
            "doc 1 = hello only, with the duplicated leaf deduplicated"
        );
        assert_eq!(charges.entries, ids.len() as u64);

        // Strict single-term scoring matches the same frozen formula.
        let (single_bits, _) =
            b4_single_term_scored_bits_at(0, &hello, field_id, "hello", &stats, &positive)
                .expect("strict score");
        for (doc_id, score_bits) in single_bits {
            assert_eq!(score_bits, hello_contribution.to_bits(), "doc {doc_id}");
        }

        // No positive leaf (negative-only / typed-only parity) leaves `+0.0`.
        let no_positive = BTreeSet::<usize>::new();
        let (zero_bits, _) = b4_generic_scored_bits_at(0, &ids, &leaf_data, &stats, &no_positive)
            .expect("unscored generic");
        assert!(
            zero_bits.iter().all(|(_, bits)| *bits == 0.0f64.to_bits()),
            "non-positive leaves keep the initialized +0.0 score"
        );
        let (strict_zero_bits, _) =
            b4_single_term_scored_bits_at(0, &hello, field_id, "hello", &stats, &no_positive)
                .expect("unscored strict");
        assert!(
            strict_zero_bits
                .iter()
                .all(|(_, bits)| *bits == 0.0f64.to_bits()),
            "strict scorer keeps the initialized +0.0 score without a positive owner"
        );

        // Every contribution above used a prepared weight: term, phrase and strict
        // scoring must not evaluate another IDF logarithm after preparation.
        assert_eq!(
            super::super::score::idf_observation::count(),
            2,
            "phrase and strict scoring must reuse the prepared IDFs"
        );
    }

    // A1-U08 — several contributions to one document (different fields, term
    // lengths and frequencies above 2^53) sum in the original order with exact
    // frozen-scalar bits.
    #[test]
    fn a1_u08_ordered_contribution_sum_matches_frozen_scalar() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;

        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
        let title_id = reader.schema().field_id("title").expect("title field");
        let path_id = reader.schema().field_id("path").expect("path field");
        let limits = SearchLimits::default();
        let readers = [&reader];
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let mut terms: super::super::score::QueryTerms = BTreeMap::new();
        terms.insert(
            title_id,
            BTreeSet::from(["hello".to_owned(), "there".to_owned()]),
        );
        terms.insert(path_id, BTreeSet::from(["/b".to_owned()]));
        super::super::score::idf_observation::reset();
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[title_id, path_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .unwrap();
        assert_eq!(
            super::super::score::idf_observation::count(),
            3,
            "hello, there and /b are each prepared exactly once"
        );
        let title = stats.field(title_id).expect("title stats");
        let path = stats.field(path_id).expect("path stats");
        assert_eq!(title.doc_freq("hello"), 2);
        assert_eq!(
            title.doc_freq("there"),
            1,
            "the multi-contribution sum must use a prepared nonzero df"
        );
        assert_eq!(path.doc_freq("/b"), 1);
        let n = title.n;
        assert_eq!(path.n, n);

        let large = 9_007_199_254_740_993u64;
        let leaf_data = vec![
            LeafData::Term {
                field_id: title_id,
                terms: vec![
                    TermPostings {
                        term: "hello".to_owned(),
                        postings: vec![(0, large), (1, 1)],
                    },
                    TermPostings {
                        term: "there".to_owned(),
                        postings: vec![(0, 1)],
                    },
                ],
            },
            LeafData::Term {
                field_id: path_id,
                terms: vec![TermPostings {
                    term: "/b".to_owned(),
                    postings: vec![(0, 1)],
                }],
            },
        ];
        let ids = vec![0u64, 1];
        let positive = BTreeSet::from([0usize, 1]);
        let (bits, _) = b4_generic_scored_bits_at(0, &ids, &leaf_data, &stats, &positive)
            .expect("generic score");
        let bits = a1_score_bits(&bits);

        let hello = a1_frozen_scalar_bm25(
            large,
            title.doc_freq("hello"),
            n,
            title.length(0, 0),
            title.avgdl,
        )
        .expect("hello reference");
        let there = a1_frozen_scalar_bm25(
            1,
            title.doc_freq("there"),
            n,
            title.length(0, 0),
            title.avgdl,
        )
        .expect("there reference");
        let path_b =
            a1_frozen_scalar_bm25(1, path.doc_freq("/b"), n, path.length(0, 0), path.avgdl)
                .expect("path reference");
        let expected_doc0 = ((0.0_f64 + hello) + there) + path_b;
        assert_eq!(
            bits[&0],
            expected_doc0.to_bits(),
            "ordered contribution sum"
        );

        let expected_doc1 = a1_frozen_scalar_bm25(
            1,
            title.doc_freq("hello"),
            n,
            title.length(0, 1),
            title.avgdl,
        )
        .expect("doc 1 reference");
        assert_eq!(bits[&1], expected_doc1.to_bits(), "single contribution");

        // All three contributions came from prepared weights: scoring must not
        // evaluate any additional IDF logarithm.
        assert_eq!(
            super::super::score::idf_observation::count(),
            3,
            "multi-contribution scoring must reuse the prepared IDFs"
        );
    }
}
