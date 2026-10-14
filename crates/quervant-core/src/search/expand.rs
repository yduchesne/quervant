//! Query-wide multi-term expansion (PR 8, step 8).
//!
//! Expansion runs once per request, after every segment reader is open and
//! **before** snapshot-wide BM25 statistics are computed. For each segment, each
//! multi-term leaf's compiled scalar automaton is intersected with the segment's
//! derived term FST, producing an ordered, deduplicated term list. Expansion is
//! charged to the single request-wide work budget and is bounded by
//! `max_expanded_terms`, `max_unique_query_terms` and `max_fst_bytes`.
//!
//! The derived FSTs are cached per `(segment, field)` for the lifetime of the
//! request so several leaves on the same field share one index. They are dropped
//! with the request and are never written or cached globally.

use std::collections::{BTreeMap, BTreeSet};

use crate::analysis::Cancellation;
use crate::segment::{DictionaryEntry, SegmentReader};

use super::error::{SearchError, SearchResult};
use super::execute::SearchWork;
use super::limits::SearchLimits;
use super::plan::{CompiledLeaf, CompiledQuery};
use super::score::QueryTerms;
use super::term_fst::TermFst;

/// The materialized expansion for one search request.
pub(crate) struct Expansion {
    /// `per_segment[segment][leaf]` is the expanded term list for multi-term
    /// leaves and `None` for ordinary term/phrase leaves.
    per_segment: Vec<Vec<Option<Vec<String>>>>,
    /// Query-wide positive scoring terms (ordinary plus expanded).
    positive_terms: QueryTerms,
}

impl Expansion {
    /// Expanded terms for one multi-term leaf in one segment.
    pub(crate) fn terms_for(&self, segment: usize, leaf: usize) -> Option<&[String]> {
        self.per_segment.get(segment)?.get(leaf)?.as_deref()
    }

    /// The query-wide positive scoring term union used for snapshot statistics.
    pub(crate) fn positive_terms(&self) -> &QueryTerms {
        &self.positive_terms
    }
}

/// Binary search a sorted field dictionary for an exact term.
pub(crate) fn lookup_entry<'a>(
    entries: &'a [DictionaryEntry],
    term: &str,
) -> Option<&'a DictionaryEntry> {
    entries
        .binary_search_by(|entry| entry.term.as_str().cmp(term))
        .ok()
        .map(|index| &entries[index])
}

/// Ordinary (term/phrase) positive scoring terms contributed by the compiled query.
fn ordinary_positive_terms(compiled: &CompiledQuery) -> QueryTerms {
    let mut terms: QueryTerms = BTreeMap::new();
    for index in &compiled.positive_leaf_indices {
        for (field_id, term) in compiled.leaves[*index].scoring_terms() {
            terms.entry(field_id).or_default().insert(term);
        }
    }
    terms
}

/// Expand every multi-term leaf across every open segment.
pub(crate) fn expand_query(
    readers: &[&SegmentReader],
    compiled: &CompiledQuery,
    limits: &SearchLimits,
    work: &mut SearchWork<'_>,
    cancel: &dyn Cancellation,
) -> SearchResult<Expansion> {
    let multi_term_leaves: Vec<usize> = compiled
        .leaves
        .iter()
        .enumerate()
        .filter_map(|(index, leaf)| matches!(leaf, CompiledLeaf::MultiTerm { .. }).then_some(index))
        .collect();

    let mut positive_terms = ordinary_positive_terms(compiled);
    let mut per_segment: Vec<Vec<Option<Vec<String>>>> =
        vec![vec![None; compiled.leaves.len()]; readers.len()];
    if multi_term_leaves.is_empty() {
        return Ok(Expansion {
            per_segment,
            positive_terms,
        });
    }

    // Combined ordinary + expanded **scoring** terms (positive leaves only).
    let mut combined: BTreeSet<(u32, String)> = positive_terms
        .iter()
        .flat_map(|(field_id, terms)| terms.iter().map(move |term| (*field_id, term.clone())))
        .collect();
    // Unique expanded `(field, term)` pairs across **all** leaves and segments.
    let mut unique_expanded: BTreeSet<(u32, String)> = BTreeSet::new();

    let mut fsts: BTreeMap<(usize, u32), TermFst> = BTreeMap::new();
    let mut fst_bytes: u64 = 0;

    for (segment_index, reader) in readers.iter().enumerate() {
        for &leaf_index in &multi_term_leaves {
            work.check_cancelled()?;
            let CompiledLeaf::MultiTerm {
                field_id,
                predicate,
            } = &compiled.leaves[leaf_index]
            else {
                return Err(SearchError::CorruptIndex {
                    detail: "multi-term leaf index is not a multi-term leaf".to_owned(),
                });
            };

            let index_key = (segment_index, *field_id);
            if let std::collections::btree_map::Entry::Vacant(slot) = fsts.entry(index_key) {
                let entries = reader
                    .dictionary()
                    .and_then(|dictionary| dictionary.field(*field_id))
                    .unwrap_or(&[]);
                // Pre-flight before building so an over-budget dictionary fails
                // before the large allocation.
                let estimate = TermFst::estimate_bytes(entries)?;
                let projected =
                    fst_bytes
                        .checked_add(estimate)
                        .ok_or(SearchError::ResourceLimit {
                            limit: limits.max_fst_bytes(),
                            requested: u64::MAX,
                        })?;
                if projected > limits.max_fst_bytes() {
                    return Err(SearchError::ResourceLimit {
                        limit: limits.max_fst_bytes(),
                        requested: projected,
                    });
                }
                let fst = TermFst::build(entries)?;
                fst_bytes = fst_bytes.checked_add(fst.logical_bytes()).ok_or(
                    SearchError::ResourceLimit {
                        limit: limits.max_fst_bytes(),
                        requested: u64::MAX,
                    },
                )?;
                if fst_bytes > limits.max_fst_bytes() {
                    return Err(SearchError::ResourceLimit {
                        limit: limits.max_fst_bytes(),
                        requested: fst_bytes,
                    });
                }
                slot.insert(fst);
            }

            let allowance = work.remaining();
            let (terms, units) = fsts[&(segment_index, *field_id)].matches(
                predicate,
                cancel,
                allowance,
                limits.max_expanded_terms(),
            )?;
            work.charge(units)?;

            let is_positive = compiled.positive_leaf_indices.contains(&leaf_index);
            for term in &terms {
                let pair = (*field_id, term.clone());
                if unique_expanded.insert(pair.clone())
                    && unique_expanded.len() as u64 > limits.max_expanded_terms()
                {
                    return Err(SearchError::ResourceLimit {
                        limit: limits.max_expanded_terms(),
                        requested: unique_expanded.len() as u64,
                    });
                }
                if is_positive
                    && combined.insert(pair)
                    && combined.len() as u64 > limits.max_unique_query_terms()
                {
                    return Err(SearchError::ResourceLimit {
                        limit: limits.max_unique_query_terms(),
                        requested: combined.len() as u64,
                    });
                }
            }
            if is_positive {
                let set = positive_terms.entry(*field_id).or_default();
                for term in &terms {
                    set.insert(term.clone());
                }
            }
            per_segment[segment_index][leaf_index] = Some(terms);
        }
    }

    // Silence the intentionally retained scratch buffer for read-only callers.
    Ok(Expansion {
        per_segment,
        positive_terms,
    })
}
