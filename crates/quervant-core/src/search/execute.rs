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
use super::limits::SearchLimits;
use super::phrase::{PhraseMatch, PhraseTermData, match_phrase};
use super::plan::{CompiledLeaf, CompiledNode, CompiledQuery, PhraseToken};
use super::score::{QueryTerms, SnapshotStats, compute_stats};
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
struct Charges {
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

/// A checked deterministic work/candidate budget for one search.
pub(crate) struct SearchWork<'a> {
    limit: u64,
    consumed: u64,
    next_poll: u64,
    scanned: u64,
    scanned_limit: u64,
    cancel: &'a dyn Cancellation,
}

impl<'a> SearchWork<'a> {
    /// Create a work budget that polls `cancel` at fixed intervals.
    pub(crate) fn new(limit: u64, cancel: &'a dyn Cancellation) -> Self {
        Self {
            limit,
            consumed: 0,
            next_poll: CANCELLATION_POLL_INTERVAL,
            scanned: 0,
            scanned_limit: u64::MAX,
            cancel,
        }
    }

    /// Bound cumulative scanned posting occurrences independently of total work.
    pub(crate) fn with_scanned_limit(mut self, limit: u64) -> Self {
        self.scanned_limit = limit;
        self
    }

    /// Poll cancellation explicitly (boundaries and no-match paths).
    pub(crate) fn check_cancelled(&self) -> SearchResult<()> {
        if self.cancel.is_cancelled() {
            Err(SearchError::Cancelled)
        } else {
            Ok(())
        }
    }

    /// Charge deterministic work units and poll cancellation at fixed boundaries.
    pub(crate) fn charge(&mut self, units: u64) -> SearchResult<()> {
        self.consumed = self
            .consumed
            .checked_add(units)
            .ok_or(SearchError::ResourceLimit {
                limit: self.limit,
                requested: u64::MAX,
            })?;
        if self.consumed > self.limit {
            return Err(SearchError::ResourceLimit {
                limit: self.limit,
                requested: self.consumed,
            });
        }
        if self.consumed >= self.next_poll {
            self.next_poll = self.consumed.saturating_add(CANCELLATION_POLL_INTERVAL);
            self.check_cancelled()?;
        }
        Ok(())
    }

    /// Charge `freq` scanned occurrences (checked, one-over rejected) and the
    /// corresponding deterministic work (`1 + freq`).
    pub(crate) fn charge_scanned(&mut self, freq: u64) -> SearchResult<()> {
        self.scanned = self
            .scanned
            .checked_add(freq)
            .ok_or(SearchError::ResourceLimit {
                limit: self.scanned_limit,
                requested: u64::MAX,
            })?;
        if self.scanned > self.scanned_limit {
            return Err(SearchError::ResourceLimit {
                limit: self.scanned_limit,
                requested: self.scanned,
            });
        }
        self.charge(freq.saturating_add(1))
    }
}

/// Logical per-segment and search-wide candidate byte accounting.
///
/// `segment_entries`/`segment_bytes` bound the **currently evaluated segment** and
/// reset between segments. `global_bytes` bounds simultaneously retained global
/// result map entries. `reserve_global` checks the combined total so a segment's
/// live temporaries and the global map cannot jointly exceed the byte budget.
struct CandidateBudget {
    max_segment_entries: u64,
    max_total_bytes: u64,
    global_bytes: u64,
    segment_entries: u64,
    segment_bytes: u64,
}

impl CandidateBudget {
    fn new(limits: &SearchLimits) -> Self {
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

    /// Atomically reserve segment entries/bytes. Neither counter changes if either
    /// bound would be exceeded or on arithmetic overflow.
    fn reserve_segment(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
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
        self.segment_entries = new_entries;
        self.segment_bytes = new_segment_bytes;
        Ok(())
    }

    fn release_segment(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        self.segment_entries =
            self.segment_entries
                .checked_sub(entries)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "candidate entry ledger underflow".to_owned(),
                })?;
        self.segment_bytes =
            self.segment_bytes
                .checked_sub(bytes)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "candidate byte ledger underflow".to_owned(),
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
    /// unchanged.
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

    fn reserve(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        self.budget.reserve_segment(entries, bytes)?;
        self.outstanding_entries =
            self.outstanding_entries
                .checked_add(entries)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_segment_entries,
                    requested: u64::MAX,
                })?;
        self.outstanding_bytes =
            self.outstanding_bytes
                .checked_add(bytes)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.max_total_bytes,
                    requested: u64::MAX,
                })?;
        Ok(())
    }

    fn release(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        self.budget.release_segment(entries, bytes)?;
        self.outstanding_entries =
            self.outstanding_entries
                .checked_sub(entries)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "segment ledger entry underflow".to_owned(),
                })?;
        self.outstanding_bytes =
            self.outstanding_bytes
                .checked_sub(bytes)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "segment ledger byte underflow".to_owned(),
                })?;
        Ok(())
    }

    /// Atomically transfer outstanding segment ownership of `entries`/`bytes` to
    /// global ownership, updating both the budget and this ledger's counters.
    fn transfer_to_global(&mut self, entries: u64, bytes: u64) -> SearchResult<()> {
        self.budget.transfer_segment_to_global(entries, bytes)?;
        self.outstanding_entries =
            self.outstanding_entries
                .checked_sub(entries)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "segment ledger entry underflow during transfer".to_owned(),
                })?;
        self.outstanding_bytes =
            self.outstanding_bytes
                .checked_sub(bytes)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "segment ledger byte underflow during transfer".to_owned(),
                })?;
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
            let _ = self
                .budget
                .release_segment(self.outstanding_entries, self.outstanding_bytes);
            self.outstanding_entries = 0;
            self.outstanding_bytes = 0;
        }
    }
}

/// Per-leaf postings for one segment.
enum LeafData {
    Term {
        field_id: u32,
        terms: Vec<TermPostings>,
    },
    Phrase {
        field_id: u32,
        matches: Vec<PhraseMatch>,
    },
}

struct TermPostings {
    term: String,
    postings: Vec<(u64, u64)>,
}

impl LeafData {
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
    for reader in &readers {
        live.push(reader.live_docs()?);
    }

    let query_terms = query_terms(compiled);
    let stats = compute_stats(
        &readers,
        &live,
        &compiled.scoring_field_ids,
        &query_terms,
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
    stats: &SnapshotStats,
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
    stats: &SnapshotStats,
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
    let (leaf_data, leaf_charges) = build_leaf_data(reader, compiled, live, work, ledger, cancel)?;

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

fn query_terms(compiled: &CompiledQuery) -> QueryTerms {
    let mut terms: QueryTerms = BTreeMap::new();
    for index in &compiled.positive_leaf_indices {
        let leaf = &compiled.leaves[*index];
        for (field_id, term) in leaf.scoring_terms() {
            terms.entry(field_id).or_default().insert(term);
        }
    }
    terms
}

fn build_leaf_data(
    reader: &SegmentReader,
    compiled: &CompiledQuery,
    live: &[bool],
    work: &mut SearchWork<'_>,
    ledger: &mut SegmentCandidateLedger<'_>,
    cancel: &dyn Cancellation,
) -> SearchResult<(Vec<LeafData>, Charges)> {
    let mut charges = Charges::ZERO;
    let mut data = Vec::new();
    data.try_reserve_exact(compiled.leaves.len())
        .map_err(|_| SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: compiled.leaves.len() as u64,
        })?;
    for leaf in &compiled.leaves {
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
                                ledger.reserve(1, TERM_POSTING_BYTES)?;
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
            CompiledLeaf::Phrase { field_id, tokens } => {
                let (matches, phrase_charges) =
                    build_phrase(reader, *field_id, tokens, live, work, ledger, cancel)?;
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
                ledger.reserve(1, PHRASE_DOC_BYTES)?;
                scratch = scratch.add(1, PHRASE_DOC_BYTES)?;
                term_data.docs.push(posting.doc_id);
                let occurrences = posting.occurrences.len() as u64;
                let occurrence_bytes = bytes_for_count(occurrences, phrase_occurrence_bytes())?;
                ledger.reserve(occurrences, occurrence_bytes)?;
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
    ledger.reserve(candidate_upper, upper_bytes)?;

    let per_token: Vec<&PhraseTermData> = tokens
        .iter()
        .map(|token| {
            let index = index_of.get(token.term.as_str()).copied().unwrap_or(0);
            &distinct[index]
        })
        .collect();
    let matches = match_phrase(tokens, &per_token, work, cancel)?;

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
        ledger.release(candidate_upper - actual_entries, upper_bytes - actual_bytes)?;
    }
    // End all borrows of `distinct`/`index_of`, then drop the scratch storage
    // before releasing its reservation.
    drop(per_token);
    drop(index_of);
    drop(distinct);
    ledger.release(scratch.entries, scratch.bytes)?;
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
    stats: &SnapshotStats,
    segment_index: usize,
    positive: &BTreeSet<usize>,
    ledger: &mut SegmentCandidateLedger<'_>,
) -> SearchResult<(BTreeMap<u64, f64>, Charges)> {
    let entries = matches.len() as u64;
    let bytes = bytes_for_count(entries, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve(entries, bytes)?;
    let charges = Charges { entries, bytes };
    let mut scores: BTreeMap<u64, f64> = matches.iter().map(|doc| (*doc, 0.0)).collect();
    if scores.is_empty() {
        return Ok((scores, charges));
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
}
