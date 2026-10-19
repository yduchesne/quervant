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
use super::score::{SnapshotStats, compute_stats};
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
    pub(crate) fn reserve_global_bytes(&mut self, bytes: u64) -> SearchResult<()> {
        self.preflight_global_bytes(bytes)?;
        self.commit_global_bytes(bytes);
        Ok(())
    }

    /// Release global-only bytes exactly once (e.g. on candidate eviction).
    pub(crate) fn release_global_bytes(&mut self, bytes: u64) -> SearchResult<()> {
        self.global_bytes =
            self.global_bytes
                .checked_sub(bytes)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "global candidate byte ledger underflow".to_owned(),
                })?;
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
    postings: Vec<(u64, u64)>,
}

impl LeafData {
    /// Whether this leaf matches one physical document.
    pub(crate) fn matches(&self, doc_id: u64) -> bool {
        match self {
            Self::Term { terms, .. } => terms
                .iter()
                .any(|term| term.postings.iter().any(|(doc, _)| *doc == doc_id)),
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
        &matches.set,
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
                    if let Some(mut postings) = reader.postings(*field_id, term)? {
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
                        let mut postings = reader.postings_for_entry(entry)?;
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

fn score_segment(
    matches: &BTreeSet<u64>,
    leaf_data: &[LeafData],
    stats: &SnapshotStats<'_>,
    segment_index: usize,
    positive: &BTreeSet<usize>,
    ledger: &mut SegmentCandidateLedger<'_>,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
) -> SearchResult<(BTreeMap<u64, f64>, Charges)> {
    let entries = matches.len() as u64;
    let bytes = bytes_for_count(entries, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(entries, bytes, memory)?;
    let charges = Charges { entries, bytes };
    let mut scores: BTreeMap<u64, f64> = matches.iter().map(|doc| (*doc, 0.0)).collect();
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
                    let df = field_stats.doc_freq(&term.term);
                    for (doc_id, freq) in &term.postings {
                        if let Some(current) = scores.get_mut(doc_id) {
                            let dl = field_stats.length(segment_index, *doc_id);
                            let contribution = super::score::bm25(
                                *freq,
                                df,
                                field_stats.n,
                                dl,
                                field_stats.avgdl,
                            )?;
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
                        let contribution = super::score::bm25(
                            *freq,
                            field_stats.doc_freq(term),
                            field_stats.n,
                            dl,
                            field_stats.avgdl,
                        )?;
                        *current += contribution;
                    }
                }
            }
        }
    }
    Ok((scores, charges))
}

/// Reusable per-segment lexical evaluation seam for the unified executor.
///
/// Builds the existing per-leaf postings/phrase data over the effective-live
/// universe, evaluates the caller's combined predicate (`is_match`, which may
/// consult lexical leaf membership via [`LeafData::matches`] and typed leaves),
/// then scores the matched set with the existing positive-leaf [`score_segment`]
/// BM25 path. Negative-only lexical leaves never score. Returns `(doc_id, score)`
/// pairs in ascending doc order.
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
    cancel: &dyn Cancellation,
    mut is_match: F,
) -> SearchResult<Vec<(u64, f64)>>
where
    F: FnMut(u64, &[LeafData], &mut MixedWorkMeter<'_>) -> SearchResult<bool>,
{
    let mut ledger = SegmentCandidateLedger::new(budget)?;
    let live_count = live.iter().filter(|flag| **flag).count() as u64;
    let live_bytes = bytes_for_count(live_count, LIVE_SET_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(live_count, live_bytes, memory.as_deref_mut())?;
    let live_set: BTreeSet<u64> = live
        .iter()
        .enumerate()
        .filter_map(|(index, flag)| flag.then_some(index as u64))
        .collect();
    // The shared-meter borrow is scoped to leaf construction only; the callback
    // below receives the meter directly, so no two mutable borrows overlap.
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
    let mut matched: BTreeSet<u64> = BTreeSet::new();
    for doc_id in &live_set {
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
        if is_match(*doc_id, &leaf_data, meter)? {
            matched.insert(*doc_id);
        }
    }
    drop(live_set);
    ledger.release_with_memory(live_count, live_bytes, memory.as_deref_mut())?;
    let matched_entries = matched.len() as u64;
    let matched_bytes = bytes_for_count(matched_entries, SET_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;
    let (scored, _scored_charges) = score_segment(
        &matched,
        &leaf_data,
        stats,
        segment_index,
        positive,
        &mut ledger,
        memory.as_deref_mut(),
    )?;
    // Segment-owned temporaries are released here; the returned scores are owned
    // by the caller. The ledger's Drop is the safety net on any early return.
    drop(matched);
    drop(leaf_data);
    ledger.release_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;
    ledger.release_with_memory(
        leaf_charges.entries,
        leaf_charges.bytes,
        memory.as_deref_mut(),
    )?;
    Ok(scored.into_iter().collect())
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

    fn term_leaf(field_id: u32, term: &str, docs: &[u64]) -> LeafData {
        LeafData::Term {
            field_id,
            terms: vec![TermPostings {
                term: term.to_owned(),
                postings: docs.iter().map(|doc| (*doc, 1)).collect(),
            }],
        }
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
}
