//! Query-wide multi-term expansion (PR 8, step 8; Amendment 01).
//!
//! Expansion runs once per request, after every segment reader is open and
//! **before** snapshot-wide BM25 statistics are computed. For each segment, each
//! multi-term leaf's compiled scalar automaton is intersected with the segment's
//! derived term FST. Matching terms are interned into one request-owned canonical
//! table and each per-segment/per-leaf vector stores only `u32` term ids, so a
//! term matching many leaves/segments occupies one canonical text and many 4-byte
//! references rather than many cloned strings.
//!
//! Amendment 01 accounting:
//!
//! * FST construction input is charged to the single request-wide [`SearchWork`]
//!   ledger in [`super::term_fst::TermFst::preflight_build`] before the build.
//! * Retained derived FSTs are accounted by the conservative preflight reservation
//!   (cumulative against `max_fst_bytes`), not by the encoded `fst::Set` size.
//! * Simultaneously retained canonical texts, occurrence ids (charged by vector
//!   capacity) and positive scoring-term copies are bounded by
//!   `max_expansion_bytes` through [`ExpansionBudget`].
//!
//! The derived FSTs are cached per `(segment, field)` for the lifetime of the
//! request so several leaves on the same field share one index. They are dropped
//! with the request and are never written or cached globally.

use std::collections::BTreeMap;
use std::collections::btree_map::Entry as BTreeEntry;

use crate::analysis::Cancellation;
use crate::segment::{DictionaryEntry, SegmentReader};

use super::error::{SearchError, SearchResult};
use super::execute::SearchWork;
use super::limits::SearchLimits;
use super::plan::{CompiledLeaf, CompiledQuery};
use super::score::QueryTerms;
use super::term_fst::TermFst;

/// A request-local index into the canonical expanded-term table.
pub(crate) type TermId = u32;

/// Logical overhead charged once per newly interned `(field, term)` pair. It
/// covers the intern-map node and key bookkeeping; the term text bytes are
/// charged separately. This is a logical estimate, not measured RSS.
const TERM_ENTRY_OVERHEAD: u64 = 32;
/// Logical bytes charged per retained occurrence id (by allocated capacity).
const TERM_ID_BYTES: u64 = 4;
/// Logical overhead charged once per positive scoring `(field, term)` copy that
/// is retained in `positive_terms`.
const POSITIVE_TERM_COPY_OVERHEAD: u64 = 24;
/// Deterministic occurrence-vector growth unit in ids.
const ID_CHUNK: usize = 64;

/// The materialized expansion for one search request.
pub(crate) struct Expansion {
    /// `per_segment[segment][leaf]` holds the expanded `TermId`s for multi-term
    /// leaves (in original UTF-8 term order) and `None` for ordinary leaves.
    per_segment: Vec<Vec<Option<Vec<TermId>>>>,
    /// Canonical term text indexed by [`TermId`], stored exactly once.
    canonical: Vec<String>,
    /// Query-wide positive scoring terms (ordinary plus expanded).
    positive_terms: QueryTerms,
    /// Total expansion bytes charged to `max_expansion_bytes` (diagnostic only).
    #[allow(dead_code)]
    retained_bytes: u64,
}

impl Expansion {
    /// Expanded term ids for one multi-term leaf in one segment.
    pub(crate) fn terms_for(&self, segment: usize, leaf: usize) -> Option<&[TermId]> {
        self.per_segment.get(segment)?.get(leaf)?.as_deref()
    }

    /// Canonical text for a `TermId`.
    pub(crate) fn term(&self, id: TermId) -> &str {
        debug_assert!(self.canonical.get(id as usize).is_some());
        self.canonical.get(id as usize).map_or("", String::as_str)
    }

    /// The query-wide positive scoring term union used for snapshot statistics.
    pub(crate) fn positive_terms(&self) -> &QueryTerms {
        &self.positive_terms
    }

    /// Retained expansion bytes; internal test diagnostic only.
    #[cfg(test)]
    pub(crate) fn retained_bytes(&self) -> u64 {
        self.retained_bytes
    }

    /// Number of distinct canonical terms; internal test diagnostic only.
    #[cfg(test)]
    pub(crate) fn canonical_count(&self) -> usize {
        self.canonical.len()
    }

    /// Total retained occurrence ids; internal test diagnostic only.
    #[cfg(test)]
    pub(crate) fn occurrence_count(&self) -> usize {
        self.per_segment
            .iter()
            .flat_map(|row| row.iter())
            .filter_map(|slot| slot.as_ref())
            .map(Vec::len)
            .sum()
    }
}

/// A checked, request-wide retained-expansion byte budget.
struct ExpansionBudget {
    limit: u64,
    retained: u64,
}

impl ExpansionBudget {
    fn new(limit: u64) -> Self {
        Self { limit, retained: 0 }
    }

    /// Reserve `bytes`, returning a typed error at one-over with no mutation.
    fn reserve(&mut self, bytes: u64) -> SearchResult<()> {
        let next = self
            .retained
            .checked_add(bytes)
            .ok_or(SearchError::ResourceLimit {
                limit: self.limit,
                requested: u64::MAX,
            })?;
        if next > self.limit {
            return Err(SearchError::ResourceLimit {
                limit: self.limit,
                requested: next,
            });
        }
        self.retained = next;
        Ok(())
    }
}

/// Mutable builder for one request's [`Expansion`].
struct ExpansionBuilder {
    max_expanded_terms: u64,
    max_unique_query_terms: u64,
    budget: ExpansionBudget,
    /// Canonical intern table keyed by `(field_id, term)`; the term text is stored
    /// once as the key and moved into [`Expansion::canonical`] on finish.
    intern: BTreeMap<u32, BTreeMap<String, TermId>>,
    expanded_unique: u64,
    positive_terms: QueryTerms,
    positive_unique: u64,
    per_segment: Vec<Vec<Option<Vec<TermId>>>>,
}

impl ExpansionBuilder {
    fn new(compiled: &CompiledQuery, readers: usize, limits: &SearchLimits) -> SearchResult<Self> {
        Self::new_with_terms(
            compiled.leaves.len(),
            ordinary_positive_terms(compiled),
            readers,
            limits,
        )
    }

    fn new_with_terms(
        leaves: usize,
        positive_terms: QueryTerms,
        readers: usize,
        limits: &SearchLimits,
    ) -> SearchResult<Self> {
        let positive_unique: u64 = positive_terms
            .values()
            .map(|terms| terms.len() as u64)
            .sum();
        let mut per_segment: Vec<Vec<Option<Vec<TermId>>>> = Vec::new();
        per_segment
            .try_reserve_exact(readers)
            .map_err(|_| SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: readers as u64,
            })?;
        for _ in 0..readers {
            let mut row: Vec<Option<Vec<TermId>>> = Vec::new();
            row.try_reserve_exact(leaves)
                .map_err(|_| SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: leaves as u64,
                })?;
            row.resize_with(leaves, || None);
            per_segment.push(row);
        }
        Ok(Self {
            max_expanded_terms: limits.max_expanded_terms(),
            max_unique_query_terms: limits.max_unique_query_terms(),
            budget: ExpansionBudget::new(limits.max_expansion_bytes()),
            intern: BTreeMap::new(),
            expanded_unique: 0,
            positive_terms,
            positive_unique,
            per_segment,
        })
    }

    /// Mark a `(segment, leaf)` slot as expanded (possibly empty) so that a leaf
    /// matching nothing is not mistaken for an unexpanded leaf during execution.
    fn begin_leaf(&mut self, segment: usize, leaf: usize) {
        if self.per_segment[segment][leaf].is_none() {
            self.per_segment[segment][leaf] = Some(Vec::new());
        }
    }

    fn positive_contains(&self, field_id: u32, term: &str) -> bool {
        self.positive_terms
            .get(&field_id)
            .is_some_and(|terms| terms.contains(term))
    }

    /// Intern a matched expanded term, charging canonical and positive-copy bytes
    /// before insertion. Existing terms are reused without a new charge.
    fn intern_term(
        &mut self,
        field_id: u32,
        term: &str,
        is_positive: bool,
    ) -> SearchResult<TermId> {
        if let Some(existing) = self.intern.get(&field_id).and_then(|inner| inner.get(term)) {
            return Ok(*existing);
        }

        let term_bytes = u64::try_from(term.len()).map_err(|_| SearchError::ResourceLimit {
            limit: self.budget.limit,
            requested: u64::MAX,
        })?;
        let canonical_charge =
            term_bytes
                .checked_add(TERM_ENTRY_OVERHEAD)
                .ok_or(SearchError::ResourceLimit {
                    limit: self.budget.limit,
                    requested: u64::MAX,
                })?;
        // Distinct expanded identity limit (positive or negative).
        if self.expanded_unique + 1 > self.max_expanded_terms {
            return Err(SearchError::ResourceLimit {
                limit: self.max_expanded_terms,
                requested: self.expanded_unique + 1,
            });
        }
        // Distinct positive scoring identity limit + optional String copy.
        let new_positive = is_positive && !self.positive_contains(field_id, term);
        let positive_charge = if new_positive {
            if self.positive_unique + 1 > self.max_unique_query_terms {
                return Err(SearchError::ResourceLimit {
                    limit: self.max_unique_query_terms,
                    requested: self.positive_unique + 1,
                });
            }
            term_bytes.checked_add(POSITIVE_TERM_COPY_OVERHEAD).ok_or(
                SearchError::ResourceLimit {
                    limit: self.budget.limit,
                    requested: u64::MAX,
                },
            )?
        } else {
            0
        };
        self.budget
            .reserve(canonical_charge.checked_add(positive_charge).ok_or(
                SearchError::ResourceLimit {
                    limit: self.budget.limit,
                    requested: u64::MAX,
                },
            )?)?;

        let mut owned = String::new();
        owned
            .try_reserve_exact(term.len())
            .map_err(|_| SearchError::ResourceLimit {
                limit: self.budget.limit,
                requested: u64::MAX,
            })?;
        owned.push_str(term);
        let id = u32::try_from(self.expanded_unique).map_err(|_| SearchError::ResourceLimit {
            limit: self.budget.limit,
            requested: self.expanded_unique + 1,
        })?;
        self.intern.entry(field_id).or_default().insert(owned, id);
        self.expanded_unique += 1;
        if new_positive {
            self.positive_terms
                .entry(field_id)
                .or_default()
                .insert(term.to_owned());
            self.positive_unique += 1;
        }
        Ok(id)
    }

    /// Append one occurrence id, charging the vector's allocated capacity in
    /// deterministic chunks before retaining it.
    fn push_occurrence(&mut self, segment: usize, leaf: usize, id: TermId) -> SearchResult<()> {
        let slot = self.per_segment[segment][leaf].get_or_insert_with(Vec::new);
        if slot.len() == slot.capacity() {
            self.budget
                .reserve((ID_CHUNK as u64).checked_mul(TERM_ID_BYTES).ok_or(
                    SearchError::ResourceLimit {
                        limit: self.budget.limit,
                        requested: u64::MAX,
                    },
                )?)?;
            slot.try_reserve_exact(ID_CHUNK)
                .map_err(|_| SearchError::ResourceLimit {
                    limit: self.budget.limit,
                    requested: u64::MAX,
                })?;
            // Account any allocator capacity overshoot before retaining it.
            let actual = slot.capacity() as u64;
            let expected = (slot.len() as u64).checked_add(ID_CHUNK as u64).ok_or(
                SearchError::ResourceLimit {
                    limit: self.budget.limit,
                    requested: u64::MAX,
                },
            )?;
            if actual > expected {
                self.budget
                    .reserve((actual - expected).checked_mul(TERM_ID_BYTES).ok_or(
                        SearchError::ResourceLimit {
                            limit: self.budget.limit,
                            requested: u64::MAX,
                        },
                    )?)?;
            }
        }
        slot.push(id);
        Ok(())
    }

    /// Consume the builder into the immutable request expansion, moving canonical
    /// term text (stored once as intern-map keys) into an id-indexed vector.
    fn finish(self) -> Expansion {
        let ExpansionBuilder {
            intern,
            positive_terms,
            per_segment,
            budget,
            ..
        } = self;
        let mut canonical: Vec<Option<String>> = Vec::new();
        canonical.resize_with(intern.values().map(BTreeMap::len).sum(), || None);
        for inner in intern.into_values() {
            for (text, id) in inner {
                if let Some(slot) = canonical.get_mut(id as usize) {
                    *slot = Some(text);
                }
            }
        }
        let canonical: Vec<String> = canonical
            .into_iter()
            .map(Option::unwrap_or_default)
            .collect();
        Expansion {
            per_segment,
            canonical,
            positive_terms,
            retained_bytes: budget.retained,
        }
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

    let mut builder = ExpansionBuilder::new(compiled, readers.len(), limits)?;
    if multi_term_leaves.is_empty() {
        return Ok(builder.finish());
    }

    let mut fsts: BTreeMap<(usize, u32), TermFst> = BTreeMap::new();
    let mut fst_reserved_total: u64 = 0;

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
            if let BTreeEntry::Vacant(slot) = fsts.entry(index_key) {
                let entries = reader
                    .dictionary()
                    .and_then(|dictionary| dictionary.field(*field_id))
                    .unwrap_or(&[]);
                if entries.is_empty() {
                    // No dictionary entries: an explicitly empty derived FST with a
                    // truthful zero reservation.
                    slot.insert(TermFst::empty());
                } else {
                    // Charge all build work and validate the cumulative derived-FST
                    // byte reservation before any allocation.
                    let reservation = TermFst::preflight_build(
                        entries,
                        fst_reserved_total,
                        limits.max_fst_bytes(),
                        work,
                        cancel,
                    )?;
                    let fst = TermFst::build(entries)?;
                    if !fst.reservation_fits(reservation) {
                        return Err(SearchError::ResourceLimit {
                            limit: reservation,
                            requested: fst.logical_bytes(),
                        });
                    }
                    fst_reserved_total = fst_reserved_total.checked_add(reservation).ok_or(
                        SearchError::ResourceLimit {
                            limit: limits.max_fst_bytes(),
                            requested: u64::MAX,
                        },
                    )?;
                    slot.insert(fst);
                }
            }

            let fst = &fsts[&index_key];
            let is_positive = compiled.positive_leaf_indices.contains(&leaf_index);
            builder.begin_leaf(segment_index, leaf_index);
            let allowance = work.remaining();
            let units = fst.visit_matches(predicate, cancel, allowance, |term| {
                let id = builder.intern_term(*field_id, term, is_positive)?;
                builder.push_occurrence(segment_index, leaf_index, id)
            })?;
            work.charge(units)?;
        }
    }

    Ok(builder.finish())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn limits_with(bytes: u64) -> SearchLimits {
        SearchLimits::default()
            .with_max_expansion_bytes(bytes)
            .unwrap()
    }

    fn empty_positive() -> QueryTerms {
        QueryTerms::new()
    }

    #[test]
    fn budget_reserve_is_exact_and_typed() {
        let mut budget = ExpansionBudget::new(10);
        budget.reserve(10).unwrap();
        assert_eq!(budget.retained, 10);
        assert!(matches!(
            budget.reserve(1),
            Err(SearchError::ResourceLimit {
                limit: 10,
                requested: 11
            })
        ));
        assert_eq!(budget.retained, 10, "failed reserve must not mutate");

        let mut overflow = ExpansionBudget {
            limit: u64::MAX,
            retained: u64::MAX,
        };
        assert!(matches!(
            overflow.reserve(1),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(overflow.retained, u64::MAX);
    }

    #[test]
    fn intern_deduplicates_and_charges_once() {
        let limits = limits_with(1_000_000);
        let mut builder =
            ExpansionBuilder::new_with_terms(1, empty_positive(), 1, &limits).unwrap();
        let first = builder.intern_term(0, "rust", true).unwrap();
        // 32 + 4 canonical + 24 + 4 positive copy.
        let after_first = builder.budget.retained;
        assert_eq!(after_first, (32 + 4) + (24 + 4));
        let second = builder.intern_term(0, "rust", true).unwrap();
        assert_eq!(first, second);
        assert_eq!(builder.budget.retained, after_first, "reuse is free");
        // A negative term interned once costs only the canonical entry.
        let third = builder.intern_term(0, "rusty", false).unwrap();
        assert_ne!(third, first);
        assert_eq!(builder.budget.retained, after_first + (32 + 5));

        let expansion = builder.finish();
        assert_eq!(expansion.retained_bytes(), (32 + 4) + (24 + 4) + (32 + 5));
        assert_eq!(expansion.term(first), "rust");
        assert_eq!(expansion.term(third), "rusty");
    }

    #[test]
    fn intern_unicode_and_long_terms_charge_utf8_bytes() {
        let limits = limits_with(1_000_000);
        let mut builder =
            ExpansionBuilder::new_with_terms(1, empty_positive(), 1, &limits).unwrap();
        let id = builder.intern_term(0, "é", true).unwrap();
        // "é" is two UTF-8 bytes.
        assert_eq!(builder.budget.retained, (32 + 2) + (24 + 2));
        assert_eq!(builder.finish().term(id), "é");
    }

    #[test]
    fn expanded_unique_limit_is_enforced() {
        let limits = SearchLimits::default().with_max_expanded_terms(1).unwrap();
        let mut builder =
            ExpansionBuilder::new_with_terms(1, empty_positive(), 1, &limits).unwrap();
        builder.intern_term(0, "a", true).unwrap();
        assert!(matches!(
            builder.intern_term(0, "b", true),
            Err(SearchError::ResourceLimit {
                limit: 1,
                requested: 2
            })
        ));
        // Re-interning an existing term is not a new expanded identity.
        assert!(builder.intern_term(0, "a", true).is_ok());
    }

    #[test]
    fn positive_unique_limit_is_enforced() {
        let limits = SearchLimits::default()
            .with_max_unique_query_terms(1)
            .unwrap();
        let mut builder =
            ExpansionBuilder::new_with_terms(1, empty_positive(), 1, &limits).unwrap();
        builder.intern_term(0, "a", true).unwrap();
        assert!(matches!(
            builder.intern_term(0, "b", true),
            Err(SearchError::ResourceLimit {
                limit: 1,
                requested: 2
            })
        ));
        // A negative term can still be interned; only positive scoring is capped.
        assert!(builder.intern_term(0, "c", false).is_ok());
    }

    #[test]
    fn positive_copy_is_not_charged_twice() {
        let limits = limits_with(1_000_000);
        let mut positive = QueryTerms::new();
        positive.entry(0).or_default().insert("rust".to_owned());
        let mut builder = ExpansionBuilder::new_with_terms(1, positive, 1, &limits).unwrap();
        // `rust` is already an ordinary positive term: no new String copy.
        builder.intern_term(0, "rust", true).unwrap();
        assert_eq!(builder.budget.retained, 32 + 4);
    }

    #[test]
    fn occurrence_capacity_is_charged_in_chunks() {
        let limits = limits_with(1_000_000);
        let mut builder =
            ExpansionBuilder::new_with_terms(1, empty_positive(), 1, &limits).unwrap();
        for id in 0..64 {
            builder.push_occurrence(0, 0, id).unwrap();
        }
        assert_eq!(builder.budget.retained, 64 * TERM_ID_BYTES);
        builder.push_occurrence(0, 0, 64).unwrap();
        assert_eq!(builder.budget.retained, 128 * TERM_ID_BYTES);
        assert_eq!(
            builder.finish().terms_for(0, 0).unwrap().len(),
            65,
            "all occurrences retained in order"
        );
    }

    #[test]
    fn occurrence_bytes_one_over_fails_closed() {
        let exact = 64 * TERM_ID_BYTES;
        let limits = limits_with(exact);
        let mut builder =
            ExpansionBuilder::new_with_terms(1, empty_positive(), 1, &limits).unwrap();
        // The 64th push grows capacity to 64 and fits exactly.
        for id in 0..64 {
            builder.push_occurrence(0, 0, id).unwrap();
        }
        // The 65th requires another 256-byte chunk and fails with no partial success.
        assert!(matches!(
            builder.push_occurrence(0, 0, 64),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn duplicate_term_amplification_is_bounded_by_occurrences_not_strings() {
        // One canonical term retained across 20 segments x 20 leaves.
        let leaves = 20;
        let segments = 20;
        let exact_occurrences = (segments * leaves * 64) as u64 * TERM_ID_BYTES;
        let limits = limits_with(exact_occurrences + (32 + 5) + (24 + 5));
        let mut builder =
            ExpansionBuilder::new_with_terms(leaves, empty_positive(), segments, &limits).unwrap();
        let id = builder.intern_term(0, "term!", true).unwrap();
        for segment in 0..segments {
            for leaf in 0..leaves {
                builder.push_occurrence(segment, leaf, id).unwrap();
            }
        }
        let expansion = builder.finish();
        assert_eq!(expansion.canonical_count(), 1, "one canonical text");
        assert_eq!(expansion.occurrence_count(), 400, "one id per leaf/segment");
        assert!(expansion.term(id) == "term!");
    }

    #[test]
    fn occurrence_amplification_fails_even_when_unique_terms_fit() {
        let leaves = 20;
        let segments = 20;
        let limits = SearchLimits::default()
            .with_max_expanded_terms(1)
            .unwrap()
            .with_max_expansion_bytes(1_000)
            .unwrap();
        let mut builder =
            ExpansionBuilder::new_with_terms(leaves, empty_positive(), segments, &limits).unwrap();
        let id = builder.intern_term(0, "term!", true).unwrap();
        let mut failed = false;
        'outer: for segment in 0..segments {
            for leaf in 0..leaves {
                if builder.push_occurrence(segment, leaf, id).is_err() {
                    failed = true;
                    break 'outer;
                }
            }
        }
        assert!(
            failed,
            "occurrence bytes must fail even with one unique term"
        );
        assert!(builder.expanded_unique <= 1);
    }
}
