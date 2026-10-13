//! Snapshot-bound lexical execution (PR 7, D07-03).
//!
//! Evaluation is deliberately two-phase and materialized: snapshot-wide BM25
//! statistics are computed first, then each segment is evaluated into a bounded
//! per-segment doc-id/score map. Results are merged by logical `DocumentKey` across
//! segments. This is the simple, correct v1 baseline; it does not claim streaming
//! or WAND execution.

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use crate::analysis::Cancellation;
use crate::analysis::limits::CANCELLATION_POLL_INTERVAL;
use crate::contract::document::DocumentKey;
use crate::contract::result::TopK;
use crate::index::ReaderSnapshot;
use crate::segment::SegmentReader;

use super::error::{SearchError, SearchResult};
use super::limits::SearchLimits;
use super::phrase::{PhraseMatch, PhraseTermData, match_phrase};
use super::plan::{CompiledLeaf, CompiledNode, CompiledQuery, PhraseToken};
use super::score::{QueryTerms, SnapshotStats, compute_stats};
use super::topk::TopKSelector;
use super::{SearchHit, SearchResponse};

/// A checked deterministic work/candidate budget for one search.
pub(crate) struct SearchWork<'a> {
    limit: u64,
    consumed: u64,
    next_poll: u64,
    candidates: u64,
    candidate_limit: u64,
    cancel: &'a dyn Cancellation,
}

impl<'a> SearchWork<'a> {
    /// Create a work budget that polls `cancel` at fixed intervals.
    pub(crate) fn new(limit: u64, cancel: &'a dyn Cancellation) -> Self {
        Self {
            limit,
            consumed: 0,
            next_poll: CANCELLATION_POLL_INTERVAL,
            candidates: 0,
            candidate_limit: u64::MAX,
            cancel,
        }
    }

    /// Bound the total number of materialized candidate entries.
    pub(crate) fn with_candidate_limit(mut self, limit: u64) -> Self {
        self.candidate_limit = limit;
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

    /// Charge one posting document plus its occurrence count.
    pub(crate) fn charge_scanned(&mut self, freq: u64) -> SearchResult<()> {
        self.charge(freq.saturating_add(1))
    }

    /// Charge materialized candidate entries.
    pub(crate) fn charge_candidates(&mut self, entries: u64) -> SearchResult<()> {
        self.candidates =
            self.candidates
                .checked_add(entries)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.candidate_limit,
                    requested: u64::MAX,
                })?;
        if self.candidates > self.candidate_limit {
            return Err(SearchError::ResourceLimit {
                limit: self.candidate_limit,
                requested: self.candidates,
            });
        }
        Ok(())
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

/// Execute a compiled query against an immutable snapshot.
pub(crate) fn execute_search(
    snapshot: &ReaderSnapshot,
    compiled: &CompiledQuery,
    search_limits: &SearchLimits,
    top_k: TopK,
    cancel: &dyn Cancellation,
) -> SearchResult<SearchResponse> {
    let mut work = SearchWork::new(search_limits.max_total_work_units(), cancel)
        .with_candidate_limit(search_limits.max_segment_candidate_entries());
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

    let mut global: BTreeMap<DocumentKey, f64> = BTreeMap::new();
    let mut candidate_bytes: u64 = 0;
    for (segment_index, reader) in readers.iter().enumerate() {
        work.check_cancelled()?;
        let live_set = live_set(&live[segment_index], &mut work)?;
        let leaf_data = build_leaf_data(
            reader,
            compiled,
            &live[segment_index],
            search_limits,
            &mut work,
            cancel,
        )?;
        let matches = eval_node(&compiled.root, &leaf_data, &live_set, &mut work)?;
        work.charge_candidates(matches.len() as u64)?;
        let scored = score_segment(&matches, &leaf_data, &stats, segment_index)?;
        for (doc_id, score) in scored {
            work.check_cancelled()?;
            let key = reader.doc_key(doc_id)?;
            if global.contains_key(&key) {
                return Err(SearchError::CorruptIndex {
                    detail: format!(
                        "duplicate live document key across segments: {}",
                        key.as_str()
                    ),
                });
            }
            candidate_bytes = candidate_bytes
                .checked_add(key.as_str().len() as u64 + 16)
                .ok_or(SearchError::ResourceLimit {
                    limit: search_limits.max_total_candidate_bytes(),
                    requested: u64::MAX,
                })?;
            if candidate_bytes > search_limits.max_total_candidate_bytes() {
                return Err(SearchError::ResourceLimit {
                    limit: search_limits.max_total_candidate_bytes(),
                    requested: candidate_bytes,
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

fn query_terms(compiled: &CompiledQuery) -> QueryTerms {
    let mut terms: QueryTerms = BTreeMap::new();
    for leaf in &compiled.leaves {
        for (field_id, term) in leaf.scoring_terms() {
            terms.entry(field_id).or_default().insert(term);
        }
    }
    terms
}

fn live_set(live: &[bool], work: &mut SearchWork<'_>) -> SearchResult<BTreeSet<u64>> {
    work.charge_candidates(live.iter().filter(|flag| **flag).count() as u64)?;
    Ok(live
        .iter()
        .enumerate()
        .filter_map(|(index, flag)| flag.then_some(index as u64))
        .collect())
}

fn build_leaf_data(
    reader: &SegmentReader,
    compiled: &CompiledQuery,
    live: &[bool],
    limits: &SearchLimits,
    work: &mut SearchWork<'_>,
    cancel: &dyn Cancellation,
) -> SearchResult<Vec<LeafData>> {
    let mut data = Vec::new();
    data.try_reserve_exact(compiled.leaves.len())
        .map_err(|_| SearchError::ResourceLimit {
            limit: limits.max_segment_candidate_entries(),
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
                                postings_list.push((posting.doc_id, posting.freq));
                            }
                        }
                    }
                    work.charge_candidates(postings_list.len() as u64)?;
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
                let matches = build_phrase(reader, *field_id, tokens, live, work, cancel)?;
                work.charge_candidates(matches.len() as u64)?;
                data.push(LeafData::Phrase {
                    field_id: *field_id,
                    matches,
                });
            }
        }
    }
    Ok(data)
}

fn build_phrase(
    reader: &SegmentReader,
    field_id: u32,
    tokens: &[PhraseToken],
    live: &[bool],
    work: &mut SearchWork<'_>,
    cancel: &dyn Cancellation,
) -> SearchResult<Vec<PhraseMatch>> {
    if tokens.is_empty() {
        return Ok(Vec::new());
    }
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
                work.charge_candidates(posting.occurrences.len() as u64)?;
                term_data.docs.push(posting.doc_id);
                term_data
                    .occurrences
                    .insert(posting.doc_id, posting.occurrences);
            }
        }
        distinct.push(term_data);
    }
    let per_token: Vec<&PhraseTermData> = tokens
        .iter()
        .map(|token| {
            let index = index_of.get(token.term.as_str()).copied().unwrap_or(0);
            &distinct[index]
        })
        .collect();
    match_phrase(tokens, &per_token, work, cancel)
}

fn eval_node(
    node: &CompiledNode,
    leaf_data: &[LeafData],
    live_set: &BTreeSet<u64>,
    work: &mut SearchWork<'_>,
) -> SearchResult<BTreeSet<u64>> {
    match node {
        CompiledNode::MatchAll => {
            work.check_cancelled()?;
            Ok(live_set.clone())
        }
        CompiledNode::Leaf(index) => {
            work.check_cancelled()?;
            let data = leaf_data
                .get(*index)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "compiled leaf index is out of range".to_owned(),
                })?;
            let set = data.match_set();
            work.charge_candidates(set.len() as u64)?;
            Ok(set)
        }
        CompiledNode::And(children) => {
            let mut iter = children.iter();
            let Some(first) = iter.next() else {
                return Ok(BTreeSet::new());
            };
            let mut accumulator = eval_node(first, leaf_data, live_set, work)?;
            for child in iter {
                work.check_cancelled()?;
                let next = eval_node(child, leaf_data, live_set, work)?;
                accumulator = intersection(&accumulator, &next);
                work.charge_candidates(accumulator.len() as u64)?;
                if accumulator.is_empty() {
                    break;
                }
            }
            Ok(accumulator)
        }
        CompiledNode::Or(children) => {
            let mut accumulator: BTreeSet<u64> = BTreeSet::new();
            for child in children {
                work.check_cancelled()?;
                let next = eval_node(child, leaf_data, live_set, work)?;
                accumulator.extend(next);
                work.charge_candidates(accumulator.len() as u64)?;
            }
            Ok(accumulator)
        }
        CompiledNode::Not(inner) => {
            work.check_cancelled()?;
            let inner_set = eval_node(inner, leaf_data, live_set, work)?;
            let complement: BTreeSet<u64> = live_set.difference(&inner_set).copied().collect();
            work.charge_candidates(complement.len() as u64)?;
            Ok(complement)
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
) -> SearchResult<BTreeMap<u64, f64>> {
    let mut scores: BTreeMap<u64, f64> = matches.iter().map(|doc| (*doc, 0.0)).collect();
    if scores.is_empty() {
        return Ok(scores);
    }
    for leaf in leaf_data {
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
    Ok(scores)
}
