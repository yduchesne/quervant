//! BM25 scoring and snapshot-wide field statistics (PR 7, D07-04; Amendment 05).
//!
//! Statistics are computed from immutable per-segment field norms when available
//! and from the original all-postings reconstruction only for genuine legacy
//! segments (no `FieldNorms` section). Document frequencies are retrieved for the
//! **queried terms only**, never by scanning unrelated dictionary entries or
//! postings.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::rc::Rc;

use crate::analysis::Cancellation;
use crate::segment::{DictionaryEntry, FieldNorms, SegmentReader};

use super::error::{SearchError, SearchResult};
use super::execute::SearchWork;
use super::limits::SearchLimits;

/// Approved BM25 term-frequency saturation (fixed in PR 7).
pub(crate) const BM25_K1: f64 = 1.2;
/// Approved BM25 length-normalization (fixed in PR 7).
pub(crate) const BM25_B: f64 = 0.75;

/// Compute one BM25 contribution with explicit input validation.
///
/// Returns `0.0` when the collection is empty, the term frequency is zero, or no
/// term can be present (`avgdl == 0`). A non-finite or negative result is a typed
/// failure, never a silently accepted score.
///
/// This is the frozen scalar reference used for synthetic inputs whose term has no
/// prepared query-local weight (see [`FieldStats::bm25_score`]).
pub(crate) fn bm25(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> SearchResult<f64> {
    if tf == 0 || n == 0 || avgdl <= 0.0 {
        return Ok(0.0);
    }
    if df > n {
        return Err(SearchError::InvalidScore {
            detail: "document frequency exceeds the live-document count",
        });
    }
    bm25_with_idf(tf, dl, avgdl, idf_log(df, n))
}

/// Evaluate the BM25 inverse document frequency for one `(df, n)` pair.
///
/// This is the only place the IDF logarithm is evaluated, and it keeps the
/// original expression, conversions and grouping so prepared and scalar scores
/// are bit-identical.
fn idf_log(doc_freq: u64, n: u64) -> f64 {
    let df = doc_freq as f64;
    let n = n as f64;
    #[cfg(test)]
    idf_observation::note_idf_eval();
    (1.0 + (n - df + 0.5) / (df + 0.5)).ln()
}

/// Prepare the query-constant IDF for one finalized term statistic.
///
/// Returns `None` when no logarithm is needed or allowed: an absent term
/// (`doc_freq == 0`), an empty snapshot (`n == 0`), or an invalid statistic
/// (`doc_freq > n`, whose original typed error is deferred to the scoring site).
fn prepare_idf(doc_freq: u64, n: u64) -> Option<f64> {
    if doc_freq == 0 || n == 0 || doc_freq > n {
        return None;
    }
    Some(idf_log(doc_freq, n))
}

/// BM25 arithmetic once the IDF is known: the original operation order, unchanged.
fn bm25_with_idf(tf: u64, dl: u64, avgdl: f64, idf: f64) -> SearchResult<f64> {
    let tf = tf as f64;
    let dl = dl as f64;
    let denominator = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * dl / avgdl);
    let score = idf * (tf * (BM25_K1 + 1.0)) / denominator;
    if score.is_finite() && score >= 0.0 {
        Ok(score)
    } else {
        Err(SearchError::InvalidScore {
            detail: "BM25 produced a non-finite or negative score",
        })
    }
}

/// Test-only observation of how many IDF logarithms were evaluated on this
/// thread.
///
/// This is deliberately thread-local and compiled only in test builds. It proves
/// one-time preparation without adding a production counter, metric, tracing
/// label or synchronization primitive.
#[cfg(test)]
pub(crate) mod idf_observation {
    use std::cell::Cell;

    thread_local! {
        static PREPARED_IDF_EVALS: Cell<u64> = const { Cell::new(0) };
    }

    /// Record one evaluated IDF logarithm on the current thread.
    pub(crate) fn note_idf_eval() {
        PREPARED_IDF_EVALS.with(|cell| cell.set(cell.get() + 1));
    }

    /// Reset the current thread's counter.
    pub(crate) fn reset() {
        PREPARED_IDF_EVALS.with(|cell| cell.set(0));
    }

    /// Read the current thread's counter.
    pub(crate) fn count() -> u64 {
        PREPARED_IDF_EVALS.with(Cell::get)
    }
}

/// How one segment's lengths for one field are sourced.
pub(crate) enum SegmentLengths<'a> {
    /// Immutable persisted norms (physical-doc order).
    Persisted(&'a [u64]),
    /// Reconstructed from postings for a legacy segment.
    Legacy(HashMap<u64, u64>),
}

/// Query-local prepared BM25 data for one scoring term on one field.
///
/// The record is built once per query by [`compute_stats`], owned by
/// [`SnapshotStats`] and never shared across requests, segments or threads.
#[derive(Debug, Clone, Copy)]
pub(crate) struct PreparedTermStat {
    /// Live documents in the snapshot containing this term.
    pub(crate) doc_freq: u64,
    /// Query-constant IDF, prepared once `doc_freq` is final.
    idf: Option<f64>,
}

/// Per-field snapshot statistics.
pub(crate) struct FieldStats<'a> {
    /// Live documents in the whole snapshot.
    pub(crate) n: u64,
    /// Average live document field length (`0.0` when empty).
    pub(crate) avgdl: f64,
    /// Document frequency and prepared IDF for each scoring term on this field.
    pub(crate) df: HashMap<String, PreparedTermStat>,
    /// Per-segment length source (`segment index -> lengths`).
    lengths: Vec<SegmentLengths<'a>>,
}

impl std::fmt::Debug for FieldStats<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FieldStats")
            .field("n", &self.n)
            .field("avgdl", &self.avgdl)
            .field("df", &self.df)
            .field("segments", &self.lengths.len())
            .finish()
    }
}

impl FieldStats<'_> {
    /// Field length for a physical doc in a segment (0 if the field is absent).
    pub(crate) fn length(&self, segment: usize, doc_id: u64) -> u64 {
        match self.lengths.get(segment) {
            Some(SegmentLengths::Persisted(lengths)) => {
                lengths.get(doc_id as usize).copied().unwrap_or(0)
            }
            Some(SegmentLengths::Legacy(map)) => map.get(&doc_id).copied().unwrap_or(0),
            None => 0,
        }
    }

    /// Document frequency for a scoring term (0 if absent).
    ///
    /// Prepared scoring reads the same record through
    /// [`FieldStats::bm25_score`]; this accessor is retained for parity checks and
    /// for tests that inspect raw frequencies.
    #[allow(dead_code)] // Prepared scoring goes through `bm25_score`.
    pub(crate) fn doc_freq(&self, term: &str) -> u64 {
        self.df.get(term).map_or(0, |stat| stat.doc_freq)
    }

    /// One BM25 contribution using the query-local prepared IDF.
    ///
    /// The decision order mirrors the removed per-hit scalar path exactly: the
    /// absent-term fallback, then the early zero guards, then the invalid-frequency
    /// error, then the anomalous zero-frequency fallback, and only then the prepared
    /// arithmetic. No logarithm is evaluated on the prepared path.
    pub(crate) fn bm25_score(&self, term: &str, tf: u64, dl: u64) -> SearchResult<f64> {
        let Some(stat) = self.df.get(term) else {
            return bm25(tf, 0, self.n, dl, self.avgdl);
        };
        if tf == 0 || self.n == 0 || self.avgdl <= 0.0 {
            return Ok(0.0);
        }
        if stat.doc_freq > self.n {
            return Err(SearchError::InvalidScore {
                detail: "document frequency exceeds the live-document count",
            });
        }
        if stat.doc_freq == 0 {
            return bm25(tf, 0, self.n, dl, self.avgdl);
        }
        let Some(idf) = stat.idf else {
            return Err(SearchError::CorruptIndex {
                detail: "prepared BM25 IDF missing for valid term".to_owned(),
            });
        };
        bm25_with_idf(tf, dl, self.avgdl, idf)
    }
}

/// Query-local per-segment effective-live metadata captured from the single
/// initial bitmap count pass. Numbers only: no bitmap bytes are owned or shared.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct SegmentLiveSummary {
    slot_count: usize,
    live_count: u64,
}

/// Snapshot-wide statistics for every scoring field.
#[derive(Debug)]
pub(crate) struct SnapshotStats<'a> {
    pub(crate) fields: BTreeMap<u32, FieldStats<'a>>,
    segment_live: Vec<SegmentLiveSummary>,
}

impl<'a> SnapshotStats<'a> {
    pub(crate) fn field(&self, field_id: u32) -> Option<&FieldStats<'a>> {
        self.fields.get(&field_id)
    }

    /// Checked, constant-time read of the query-local effective-live count for one
    /// segment. No recount, allocation, work charge or segment re-open.
    pub(crate) fn verified_segment_live_count(
        &self,
        segment_index: usize,
        bitmap_slots: usize,
    ) -> SearchResult<u64> {
        let Some(summary) = self.segment_live.get(segment_index) else {
            return Err(SearchError::CorruptIndex {
                detail: "snapshot live summary segment index is missing".to_owned(),
            });
        };
        if summary.slot_count != bitmap_slots {
            return Err(SearchError::CorruptIndex {
                detail: "snapshot live summary slot count mismatch".to_owned(),
            });
        }
        Ok(summary.live_count)
    }
}

/// The per-field query terms whose document frequency must be materialized.
pub(crate) type QueryTerms = BTreeMap<u32, BTreeSet<String>>;

/// Accumulate one term posting into a legacy document field-length map.
///
/// Occupancy is determined by the `HashMap::Entry` state, never by the stored
/// length value. Bounds are enforced **before** insertion so a rejected call
/// leaves the map unchanged.
fn accumulate_length(
    map: &mut HashMap<u64, u64>,
    doc_id: u64,
    freq: u64,
    max_entries: u64,
    max_bytes: u64,
    entries: &mut u64,
    bytes: &mut u64,
) -> SearchResult<()> {
    match map.entry(doc_id) {
        std::collections::hash_map::Entry::Occupied(mut slot) => {
            let updated = slot
                .get()
                .checked_add(freq)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            *slot.get_mut() = updated;
        }
        std::collections::hash_map::Entry::Vacant(slot) => {
            let new_entries = entries.checked_add(1).ok_or(SearchError::ResourceLimit {
                limit: max_entries,
                requested: u64::MAX,
            })?;
            if new_entries > max_entries {
                return Err(SearchError::ResourceLimit {
                    limit: max_entries,
                    requested: new_entries,
                });
            }
            let new_bytes = bytes.checked_add(16).ok_or(SearchError::ResourceLimit {
                limit: max_bytes,
                requested: u64::MAX,
            })?;
            if new_bytes > max_bytes {
                return Err(SearchError::ResourceLimit {
                    limit: max_bytes,
                    requested: new_bytes,
                });
            }
            slot.insert(freq);
            *entries = new_entries;
            *bytes = new_bytes;
        }
    }
    Ok(())
}

/// Bounded binary search over the sorted field dictionary, charging each probe.
fn lookup_term<'d>(
    entries: &'d [DictionaryEntry],
    term: &str,
    dictionary_terms: &mut u64,
    limits: &SearchLimits,
    work: &mut SearchWork<'_>,
) -> SearchResult<Option<&'d DictionaryEntry>> {
    let mut low = 0usize;
    let mut high = entries.len();
    while low < high {
        *dictionary_terms = dictionary_terms
            .checked_add(1)
            .ok_or(SearchError::ResourceLimit {
                limit: limits.max_dictionary_terms_examined(),
                requested: u64::MAX,
            })?;
        if *dictionary_terms > limits.max_dictionary_terms_examined() {
            return Err(SearchError::ResourceLimit {
                limit: limits.max_dictionary_terms_examined(),
                requested: *dictionary_terms,
            });
        }
        work.charge(1)?;
        let mid = low + (high - low) / 2;
        match entries[mid].term.as_str().cmp(term) {
            std::cmp::Ordering::Less => low = mid + 1,
            std::cmp::Ordering::Greater => high = mid,
            std::cmp::Ordering::Equal => return Ok(Some(&entries[mid])),
        }
    }
    Ok(None)
}

/// Compute live counts, document frequencies and document lengths for every
/// scoring field across the whole snapshot.
#[allow(clippy::too_many_arguments)]
pub(crate) fn compute_stats<'a>(
    readers: &'a [&'a SegmentReader],
    live: &[Rc<Vec<bool>>],
    scoring_field_ids: &[u32],
    query_terms: &QueryTerms,
    limits: &SearchLimits,
    work: &mut SearchWork<'_>,
    cancel: &dyn Cancellation,
) -> SearchResult<SnapshotStats<'a>> {
    // B2: this remains the single initial per-bitmap pass; it now also retains the
    // exact per-segment counts for the query-local summary.
    let mut live_summaries: Vec<SegmentLiveSummary> = Vec::new();
    live_summaries
        .try_reserve_exact(live.len())
        .map_err(|_| SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: live.len() as u64,
        })?;
    let mut n = 0u64;
    for bitmap in live {
        let count = bitmap.iter().filter(|flag| **flag).count() as u64;
        n = n.checked_add(count).ok_or(SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
        live_summaries.push(SegmentLiveSummary {
            slot_count: bitmap.len(),
            live_count: count,
        });
    }
    let mut length_entries: u64 = 0;
    let mut length_bytes: u64 = 0;
    let mut dictionary_terms: u64 = 0;
    let mut fields: BTreeMap<u32, FieldStats<'a>> = BTreeMap::new();

    for field_id in scoring_field_ids {
        let mut stats = FieldStats {
            n,
            avgdl: 0.0,
            df: HashMap::new(),
            lengths: Vec::with_capacity(readers.len()),
        };
        let query = query_terms.get(field_id);
        if let Some(terms) = query {
            for term in terms {
                stats.df.insert(
                    term.clone(),
                    PreparedTermStat {
                        doc_freq: 0,
                        idf: None,
                    },
                );
            }
        }
        let mut total_length: u64 = 0;

        for (segment_index, reader) in readers.iter().enumerate() {
            work.check_cancelled()?;
            if reader.doc_count() != live[segment_index].len() as u64 {
                return Err(SearchError::CorruptIndex {
                    detail: "segment live bitmap length does not match doc count".to_owned(),
                });
            }
            let persisted = reader
                .field_norms()
                .and_then(|norms| norms.field(*field_id));
            match persisted {
                Some(norms) => {
                    let segment_live = &live[segment_index];
                    let all_live = live_summaries[segment_index].live_count
                        == live_summaries[segment_index].slot_count as u64;
                    if all_live {
                        total_length = total_length.checked_add(norms.total_token_count()).ok_or(
                            SearchError::ResourceLimit {
                                limit: u64::MAX,
                                requested: u64::MAX,
                            },
                        )?;
                        // All live: lexical dictionary doc_freq equals unique physical
                        // documents in the postings list (one posting per doc).
                        if let Some(terms) = query {
                            let entries =
                                reader.dictionary().and_then(|dict| dict.field(*field_id));
                            for term in terms {
                                let Some(entries) = entries else { break };
                                if let Some(entry) =
                                    lookup_term(entries, term, &mut dictionary_terms, limits, work)?
                                {
                                    let stat = stats.df.get_mut(term).ok_or_else(|| {
                                        SearchError::CorruptIndex {
                                            detail: "term df slot missing".to_owned(),
                                        }
                                    })?;
                                    stat.doc_freq = stat
                                        .doc_freq
                                        .checked_add(entry.doc_freq)
                                        .ok_or(SearchError::ResourceLimit {
                                            limit: n,
                                            requested: u64::MAX,
                                        })?;
                                }
                            }
                        }
                    } else {
                        for (doc, is_live) in segment_live.iter().enumerate() {
                            if !*is_live {
                                continue;
                            }
                            let length = norms.lengths().get(doc).copied().ok_or_else(|| {
                                SearchError::CorruptIndex {
                                    detail: "norms length out of range".to_owned(),
                                }
                            })?;
                            total_length = total_length.checked_add(length).ok_or(
                                SearchError::ResourceLimit {
                                    limit: u64::MAX,
                                    requested: u64::MAX,
                                },
                            )?;
                        }
                        if let Some(terms) = query {
                            for term in terms {
                                let Some(mut postings) = reader.postings(*field_id, term)? else {
                                    continue;
                                };
                                while let Some(posting) = postings.next_with(cancel)? {
                                    work.charge_scanned(posting.freq)?;
                                    let is_live = *segment_live
                                        .get(usize::try_from(posting.doc_id).unwrap_or(usize::MAX))
                                        .ok_or_else(|| SearchError::CorruptIndex {
                                            detail: "posting doc id is out of range".to_owned(),
                                        })?;
                                    if !is_live {
                                        continue;
                                    }
                                    let stat = stats.df.get_mut(term).ok_or_else(|| {
                                        SearchError::CorruptIndex {
                                            detail: "term df slot missing".to_owned(),
                                        }
                                    })?;
                                    stat.doc_freq = stat.doc_freq.checked_add(1).ok_or(
                                        SearchError::ResourceLimit {
                                            limit: n,
                                            requested: u64::MAX,
                                        },
                                    )?;
                                }
                            }
                        }
                    }
                    stats
                        .lengths
                        .push(SegmentLengths::Persisted(norms.lengths()));
                }
                None => {
                    // Legacy segment: reconstruct this field's lengths and totals
                    // from all of its postings, with the same bounds as before.
                    let segment_live = &live[segment_index];
                    let mut map: HashMap<u64, u64> = HashMap::new();
                    if let Some(entries) =
                        reader.dictionary().and_then(|dict| dict.field(*field_id))
                    {
                        for entry in entries {
                            work.check_cancelled()?;
                            dictionary_terms = dictionary_terms.checked_add(1).ok_or(
                                SearchError::ResourceLimit {
                                    limit: limits.max_dictionary_terms_examined(),
                                    requested: u64::MAX,
                                },
                            )?;
                            if dictionary_terms > limits.max_dictionary_terms_examined() {
                                return Err(SearchError::ResourceLimit {
                                    limit: limits.max_dictionary_terms_examined(),
                                    requested: dictionary_terms,
                                });
                            }
                            work.charge(1)?;
                            let is_query_term = stats.df.contains_key(&entry.term);
                            let mut postings = reader.postings_for_entry(entry)?;
                            while let Some(posting) = postings.next_with(cancel)? {
                                work.charge_scanned(posting.freq)?;
                                let is_live = *segment_live
                                    .get(usize::try_from(posting.doc_id).unwrap_or(usize::MAX))
                                    .ok_or_else(|| SearchError::CorruptIndex {
                                        detail: "posting doc id is out of range".to_owned(),
                                    })?;
                                if !is_live {
                                    continue;
                                }
                                total_length = total_length.checked_add(posting.freq).ok_or(
                                    SearchError::ResourceLimit {
                                        limit: u64::MAX,
                                        requested: u64::MAX,
                                    },
                                )?;
                                accumulate_length(
                                    &mut map,
                                    posting.doc_id,
                                    posting.freq,
                                    limits.max_field_length_entries(),
                                    limits.max_field_length_bytes(),
                                    &mut length_entries,
                                    &mut length_bytes,
                                )?;
                                if is_query_term {
                                    let stat = stats.df.get_mut(&entry.term).ok_or_else(|| {
                                        SearchError::CorruptIndex {
                                            detail: "term df slot missing".to_owned(),
                                        }
                                    })?;
                                    stat.doc_freq = stat.doc_freq.checked_add(1).ok_or(
                                        SearchError::ResourceLimit {
                                            limit: n,
                                            requested: u64::MAX,
                                        },
                                    )?;
                                }
                            }
                        }
                    }
                    stats.lengths.push(SegmentLengths::Legacy(map));
                }
            }
        }

        stats.avgdl = if n > 0 {
            total_length as f64 / n as f64
        } else {
            0.0
        };
        // A1: summarize the query-constant IDF once, now that every segment's
        // document frequency and the snapshot-wide `n` are final. Terms with no
        // valid positive frequency stay unresolved and reuse the scalar fallback.
        for stat in stats.df.values_mut() {
            stat.idf = prepare_idf(stat.doc_freq, stats.n);
        }
        fields.insert(*field_id, stats);
    }
    Ok(SnapshotStats {
        fields,
        segment_live: live_summaries,
    })
}

// Keep `FieldNorms` in scope for the type-level docs and future direct use.
#[allow(dead_code)]
type _FieldNormsRef<'a> = &'a FieldNorms;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bm25_golden_values() {
        // Hand-computed reference values for the approved constants.
        let score = bm25(1, 1, 3, 2, 2.0).unwrap();
        let n = 3.0_f64;
        let df = 1.0_f64;
        let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
        let expected =
            idf * (1.0 * (BM25_K1 + 1.0)) / (1.0 + BM25_K1 * (1.0 - BM25_B + BM25_B * 2.0 / 2.0));
        assert!((score - expected).abs() < 1e-12);

        let score = bm25(3, 2, 5, 10, 4.5).unwrap();
        let n = 5.0_f64;
        let df = 2.0_f64;
        let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
        let expected =
            idf * (3.0 * (BM25_K1 + 1.0)) / (3.0 + BM25_K1 * (1.0 - BM25_B + BM25_B * 10.0 / 4.5));
        assert!((score - expected).abs() < 1e-12);
    }

    #[test]
    fn bm25_boundaries_and_invalid() {
        assert_eq!(bm25(0, 0, 0, 0, 0.0).unwrap(), 0.0);
        assert_eq!(bm25(1, 0, 0, 1, 0.0).unwrap(), 0.0);
        assert_eq!(bm25(1, 0, 1, 1, 0.0).unwrap(), 0.0);
        assert!(matches!(
            bm25(1, 2, 1, 1, 1.0),
            Err(SearchError::InvalidScore { .. })
        ));
        assert!(bm25(1, 1, 1, 1, 1.0).unwrap() > 0.0);
    }

    #[test]
    fn field_stats_lookup_defaults() {
        let stats = FieldStats {
            n: 0,
            avgdl: 0.0,
            df: HashMap::new(),
            lengths: Vec::new(),
        };
        assert_eq!(stats.length(0, 1), 0);
        assert_eq!(stats.doc_freq("missing"), 0);
    }

    // L03 — an occupied zero-valued entry is not charged again when its length grows.
    #[test]
    fn l03_occupied_zero_entry_is_not_recharged() {
        let mut map: HashMap<u64, u64> = HashMap::new();
        map.insert(7, 0);
        let mut entries = 0u64;
        let mut bytes = 0u64;
        accumulate_length(&mut map, 7, 5, 10, 1_000, &mut entries, &mut bytes).unwrap();
        assert_eq!(map.get(&7), Some(&5));
        assert_eq!(entries, 0);
        assert_eq!(bytes, 0);
        // A vacant entry is charged exactly once and accumulates thereafter.
        accumulate_length(&mut map, 8, 3, 10, 1_000, &mut entries, &mut bytes).unwrap();
        accumulate_length(&mut map, 8, 4, 10, 1_000, &mut entries, &mut bytes).unwrap();
        assert_eq!(map.get(&8), Some(&7));
        assert_eq!(entries, 1);
        assert_eq!(bytes, 16);
    }

    #[test]
    fn l03_entry_bound_rejection_leaves_map_unchanged() {
        let mut map: HashMap<u64, u64> = HashMap::new();
        let mut entries = 0u64;
        let mut bytes = 0u64;
        assert!(matches!(
            accumulate_length(&mut map, 1, 1, 0, 1_000, &mut entries, &mut bytes),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert!(map.is_empty());
        assert_eq!(entries, 0);
        assert!(matches!(
            accumulate_length(&mut map, 2, 1, 10, 8, &mut entries, &mut bytes),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert!(map.is_empty());
        assert_eq!(bytes, 0);
    }

    // A5-T28 — the legacy fallback still bounds its reconstructed length map.
    #[test]
    fn legacy_segment_field_length_budget_is_enforced() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const GOLDEN: &[u8] = include_bytes!("../../tests/fixtures/segment/golden.seg");
        let reader =
            SegmentReader::open(GOLDEN.to_vec(), SegmentLimits::default()).expect("golden");
        assert!(
            reader.field_norms().is_none(),
            "the checked-in golden fixture is a legacy segment"
        );
        let field_id = reader.schema().field_id("title").expect("title");
        let mut terms: QueryTerms = BTreeMap::new();
        let mut set = BTreeSet::new();
        set.insert("hello".to_owned());
        terms.insert(field_id, set);
        let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
        let readers = [&reader];

        let ok = SearchLimits::default();
        let mut work = SearchWork::new(ok.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &terms,
            &ok,
            &mut work,
            &NeverCancel,
        )
        .expect("legacy stats");
        let stats = stats.field(field_id).expect("field stats");
        assert_eq!(stats.n, 2);
        assert_eq!(stats.doc_freq("hello"), 2);
        assert_eq!(stats.length(0, 0), 2);
        assert_eq!(stats.length(0, 1), 2);

        let tight = SearchLimits::default()
            .with_max_field_length_entries(1)
            .expect("tight");
        let mut work = SearchWork::new(tight.max_total_work_units(), &NeverCancel);
        assert!(matches!(
            compute_stats(
                &readers,
                &live,
                &[field_id],
                &terms,
                &tight,
                &mut work,
                &NeverCancel
            ),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    fn query_for(field_id: u32, term: &str) -> QueryTerms {
        let mut terms: QueryTerms = BTreeMap::new();
        let mut set = BTreeSet::new();
        set.insert(term.to_owned());
        terms.insert(field_id, set);
        terms
    }

    // A5-T21 — a synthetic live bitmap excludes dead docs from n, df and lengths.
    #[test]
    fn live_bitmap_excludes_dead_documents_from_stats() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const NORMS_GOLDEN: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS_GOLDEN.to_vec(), SegmentLimits::default())
            .expect("norms golden");
        let field_id = reader.schema().field_id("title").expect("title");
        let terms = query_for(field_id, "hello");
        let readers = [&reader];
        let limits = SearchLimits::default();

        let all = vec![Rc::new(vec![true, true])];
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &all,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .expect("all live");
        let field = stats.field(field_id).expect("field");
        assert_eq!(field.n, 2);
        assert_eq!(field.doc_freq("hello"), 2);
        assert!((field.avgdl - 2.0).abs() < 1e-12);

        let one_dead = vec![Rc::new(vec![false, true])];
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &one_dead,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .expect("one dead");
        let field = stats.field(field_id).expect("field");
        assert_eq!(field.n, 1, "dead doc excluded from n");
        assert_eq!(field.doc_freq("hello"), 1, "dead doc excluded from df");
        assert!((field.avgdl - 2.0).abs() < 1e-12, "dead length excluded");
        assert_eq!(field.length(0, 1), 2);
    }

    // A5-T20/T24 — mixed legacy + new-format segments aggregate exactly.
    #[test]
    fn mixed_legacy_and_norms_segments_aggregate() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const LEGACY: &[u8] = include_bytes!("../../tests/fixtures/segment/golden.seg");
        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let legacy =
            SegmentReader::open(LEGACY.to_vec(), SegmentLimits::default()).expect("legacy golden");
        let norms =
            SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).expect("norms golden");
        assert!(legacy.field_norms().is_none(), "legacy segment");
        assert!(norms.field_norms().is_some(), "new-format segment");
        let legacy_id = legacy.schema().field_id("title").expect("title");
        let norms_id = norms.schema().field_id("title").expect("title");
        assert_eq!(legacy_id, norms_id, "fixtures share the title field id");
        let field_id = legacy_id;
        let terms = query_for(field_id, "hello");
        let readers = [&legacy, &norms];
        let live = vec![Rc::new(vec![true, true]), Rc::new(vec![true, true])];
        let limits = SearchLimits::default();
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
        .expect("mixed stats");
        let field = stats.field(field_id).expect("field");
        // Two legacy docs and two new-format docs, all matching "hello".
        assert_eq!(field.n, 4);
        assert_eq!(field.doc_freq("hello"), 4);
        assert!((field.avgdl - 2.0).abs() < 1e-12);
        assert_eq!(field.length(0, 0), 2);
        assert_eq!(field.length(1, 1), 2);
    }

    // PERF-05-B2 U01: the per-segment summary tracks exact effective-live counts
    // for all-live, partially-live and fully-dead bitmaps, and n/df follow it.
    #[test]
    fn b2_u01_live_summary_all_and_partial() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const NORMS_GOLDEN: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS_GOLDEN.to_vec(), SegmentLimits::default())
            .expect("norms golden");
        let field_id = reader.schema().field_id("title").expect("title");
        let terms = query_for(field_id, "hello");
        let readers = [&reader];
        let limits = SearchLimits::default();

        for (flags, expected_live, expected_df) in [
            (vec![true, true], 2u64, 2u64),
            (vec![false, true], 1, 1),
            (vec![false, false], 0, 0),
        ] {
            let live = vec![Rc::new(flags)];
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
            .expect("live summary stats");
            assert_eq!(
                stats.verified_segment_live_count(0, 2).expect("summary"),
                expected_live
            );
            let field = stats.field(field_id).expect("field");
            assert_eq!(field.n, expected_live);
            assert_eq!(field.doc_freq("hello"), expected_df);
            // The persisted-norm lengths remain the physical per-doc lengths.
            assert_eq!(field.length(0, 1), 2);
        }
    }

    // PERF-05-B2 U02: each segment uses its own ordinal-specific count and the
    // snapshot-wide n is the checked sum across legacy and norms segments.
    #[test]
    fn b2_u02_two_segment_mixed_counts() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const LEGACY: &[u8] = include_bytes!("../../tests/fixtures/segment/golden.seg");
        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let legacy =
            SegmentReader::open(LEGACY.to_vec(), SegmentLimits::default()).expect("legacy golden");
        let norms =
            SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).expect("norms golden");
        let field_id = legacy.schema().field_id("title").expect("title");
        let terms = query_for(field_id, "hello");
        let readers = [&legacy, &norms];
        let limits = SearchLimits::default();

        for (second_flags, expected_second, expected_n, expected_df) in [
            (vec![true, true], 2u64, 4u64, 4u64),
            (vec![false, true], 1, 3, 3),
            (vec![false, false], 0, 2, 2),
        ] {
            let live = vec![Rc::new(vec![true, true]), Rc::new(second_flags)];
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
            .expect("mixed summary stats");
            assert_eq!(stats.verified_segment_live_count(0, 2).expect("first"), 2);
            assert_eq!(
                stats.verified_segment_live_count(1, 2).expect("second"),
                expected_second
            );
            let field = stats.field(field_id).expect("field");
            assert_eq!(field.n, expected_n);
            assert_eq!(field.doc_freq("hello"), expected_df);
        }
    }

    // PERF-05-B2 U03: a missing ordinal or a slot-count mismatch fails closed with
    // the exact prescribed CorruptIndex detail strings; no recount fallback.
    #[test]
    fn b2_u03_invalid_summary_lookup_fails_closed() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const NORMS_GOLDEN: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader = SegmentReader::open(NORMS_GOLDEN.to_vec(), SegmentLimits::default())
            .expect("norms golden");
        let field_id = reader.schema().field_id("title").expect("title");
        let terms = query_for(field_id, "hello");
        let readers = [&reader];
        let limits = SearchLimits::default();
        let live = vec![Rc::new(vec![true, true])];
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
        .expect("valid stats");
        assert_eq!(stats.verified_segment_live_count(0, 2).expect("valid"), 2);

        match stats.verified_segment_live_count(1, 2) {
            Err(SearchError::CorruptIndex { detail }) => {
                assert_eq!(detail, "snapshot live summary segment index is missing");
            }
            other => panic!("unexpected missing-ordinal result: {other:?}"),
        }
        match stats.verified_segment_live_count(0, 3) {
            Err(SearchError::CorruptIndex { detail }) => {
                assert_eq!(detail, "snapshot live summary slot count mismatch");
            }
            other => panic!("unexpected slot-mismatch result: {other:?}"),
        }
    }

    // ===== PERF-06-A1: query-local prepared BM25 term weights =====

    /// Frozen pre-A1 scalar BM25. This is the independent oracle for every A1
    /// test: it repeats the original five-argument formula, conversions and
    /// early-return order, and never calls the code under test.
    fn frozen_scalar_bm25(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> SearchResult<f64> {
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
        let denominator = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * dl / avgdl);
        let score = idf * (tf * (BM25_K1 + 1.0)) / denominator;
        if score.is_finite() && score >= 0.0 {
            Ok(score)
        } else {
            Err(SearchError::InvalidScore {
                detail: "BM25 produced a non-finite or negative score",
            })
        }
    }

    /// Build finalized query-local stats the way `compute_stats` does after all
    /// document-frequency accumulation: one prepared record per query term.
    fn prepared_stats(n: u64, avgdl: f64, terms: &[(&str, u64)]) -> FieldStats<'static> {
        let mut df = HashMap::new();
        for (term, doc_freq) in terms {
            df.insert(
                (*term).to_owned(),
                PreparedTermStat {
                    doc_freq: *doc_freq,
                    idf: prepare_idf(*doc_freq, n),
                },
            );
        }
        FieldStats {
            n,
            avgdl,
            df,
            lengths: Vec::new(),
        }
    }

    #[track_caller]
    fn assert_bit_equal(got: SearchResult<f64>, expected: SearchResult<f64>, context: &str) {
        match (got, expected) {
            (Ok(got), Ok(expected)) => {
                assert_eq!(
                    got.to_bits(),
                    expected.to_bits(),
                    "score bits differ: {context}"
                );
            }
            (
                Err(SearchError::InvalidScore { detail: got }),
                Err(SearchError::InvalidScore { detail: expected }),
            ) => assert_eq!(got, expected, "error detail differs: {context}"),
            (got, expected) => panic!("result shape differs: {context}: {got:?} vs {expected:?}"),
        }
    }

    // A1-U01 — every valid prepared score is bit-identical to the frozen scalar
    // formula, including fixed golden values, u64 inputs above 2^53 and 256
    // seeded tuples.
    #[test]
    fn a1_u01_prepared_idf_matches_frozen_scalar_bits() {
        const SEED: u64 = 0xa106_a106_2026_1123;
        let fixed: [(u64, u64, u64, u64, f64); 4] = [
            (1, 1, 3, 2, 2.0),
            (3, 2, 5, 10, 4.5),
            (
                9_007_199_254_740_993,
                9_007_199_254_740_993,
                9_007_199_254_740_995,
                0,
                1.0,
            ),
            (
                9_007_199_254_740_997,
                4,
                9_007_199_254_740_993,
                9_007_199_254_740_993,
                2_500.0,
            ),
        ];
        let mut checked = 0usize;
        for (tf, df, n, dl, avgdl) in fixed {
            let stats = prepared_stats(n, avgdl, &[("t", df)]);
            let got = stats.bm25_score("t", tf, dl);
            let expected = frozen_scalar_bm25(tf, df, n, dl, avgdl);
            assert_bit_equal(
                got,
                expected,
                &format!("fixed ({tf},{df},{n},{dl},{avgdl})"),
            );
            checked += 1;
        }

        let mut state = SEED;
        for case in 1..=256usize {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            let r = state >> 11;
            let n = 1 + r % 1_000_000;
            let df = 1 + (r >> 20) % n;
            let tf = 1 + (r >> 3) % 1_000_000;
            let dl = (r >> 40) % 1_000_001;
            let avgdl = ((r >> 7) % 10_000 + 1) as f64 / 4.0;
            let stats = prepared_stats(n, avgdl, &[("t", df)]);
            let got = stats.bm25_score("t", tf, dl);
            let expected = frozen_scalar_bm25(tf, df, n, dl, avgdl);
            assert_bit_equal(
                got,
                expected,
                &format!("seed {SEED:#x} case {case} ({tf},{df},{n},{dl},{avgdl})"),
            );
            checked += 1;
        }
        assert_eq!(checked, 260, "fixed plus seeded tuple count");
    }

    // A1-U02 — the early guards keep their exact order and precedence, including
    // `-0.0`, negatives, infinities and NaN average lengths.
    #[test]
    fn a1_u02_early_guards_preserve_scalar_precedence() {
        let mut checked = 0usize;
        for avgdl in [0.0f64, -0.0, -1.0, f64::NEG_INFINITY] {
            for (df, n) in [(1u64, 3u64), (4, 3), (0, 3), (1, 0)] {
                let stats = prepared_stats(n, avgdl, &[("t", df)]);
                for tf in [0u64, 1, 5] {
                    let got = stats.bm25_score("t", tf, 3);
                    let expected = frozen_scalar_bm25(tf, df, n, 3, avgdl);
                    assert_bit_equal(
                        got,
                        expected,
                        &format!("avgdl={avgdl} df={df} n={n} tf={tf}"),
                    );
                    checked += 1;
                }
            }
        }
        // NaN and +Infinity are not early returns: the denominator decides.
        for avgdl in [f64::NAN, f64::INFINITY] {
            for tf in [1u64, 7] {
                let stats = prepared_stats(3, avgdl, &[("t", 2)]);
                let got = stats.bm25_score("t", tf, 2);
                let expected = frozen_scalar_bm25(tf, 2, 3, 2, avgdl);
                assert_bit_equal(got, expected, &format!("avgdl={avgdl} tf={tf}"));
                checked += 1;
            }
        }
        assert_eq!(checked, 4 * 4 * 3 + 4);
    }

    // A1-U03 — absent and zero-df terms consume no logarithm during preparation
    // and still reproduce the scalar `df=0` fallback on synthetic inputs.
    #[test]
    fn a1_u03_missing_and_zero_df_skip_preparation() {
        super::idf_observation::reset();
        let stats = prepared_stats(5, 3.5, &[("present", 2), ("zero", 0)]);
        assert_eq!(
            super::idf_observation::count(),
            1,
            "only the valid positive term may be prepared"
        );
        for tf in [0u64, 4] {
            for term in ["missing", "zero"] {
                let got = stats.bm25_score(term, tf, 7);
                let expected = frozen_scalar_bm25(tf, 0, 5, 7, 3.5);
                assert_bit_equal(got, expected, &format!("{term} tf={tf}"));
            }
        }
        // The zero-tf calls short-circuit; the two positive calls evaluate the
        // legacy logarithm exactly once each.
        assert_eq!(super::idf_observation::count(), 3);
        assert!(!stats.df.contains_key("missing"));
        assert!(stats.df.get("zero").expect("zero record").idf.is_none());
    }

    // A1-U05 — `compute_stats` prepares the IDF only after all document-frequency
    // accumulation, for all-live, partially-live, fully-dead and two-segment
    // snapshots alike.
    #[test]
    fn a1_u05_compute_stats_prepares_idf_after_accumulation() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const LEGACY: &[u8] = include_bytes!("../../tests/fixtures/segment/golden.seg");
        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let legacy =
            SegmentReader::open(LEGACY.to_vec(), SegmentLimits::default()).expect("legacy golden");
        let norms =
            SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).expect("norms golden");
        let field_id = legacy.schema().field_id("title").expect("title");
        assert_eq!(field_id, norms.schema().field_id("title").expect("title"));
        let terms = query_for(field_id, "hello");
        let limits = SearchLimits::default();

        let cases: [(&[&SegmentReader], Vec<Vec<bool>>); 4] = [
            (&[&norms], vec![vec![true, true]]),
            (&[&norms], vec![vec![false, true]]),
            (&[&norms], vec![vec![false, false]]),
            (&[&legacy, &norms], vec![vec![true, true], vec![true, true]]),
        ];
        for (readers, flags) in cases {
            let live: Vec<Rc<Vec<bool>>> = flags.into_iter().map(Rc::new).collect();
            let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
            let stats = compute_stats(
                readers,
                &live,
                &[field_id],
                &terms,
                &limits,
                &mut work,
                &NeverCancel,
            )
            .expect("stats");
            let field = stats.field(field_id).expect("field stats");
            let df = field.doc_freq("hello");
            assert_eq!(df, field.n, "the fixture matches `hello` in every live doc");
            for (tf, dl) in [(1u64, 2u64), (3, 2)] {
                let got = field.bm25_score("hello", tf, dl);
                let expected = frozen_scalar_bm25(tf, df, field.n, dl, field.avgdl);
                assert_bit_equal(got, expected, &format!("n={} df={df} tf={tf}", field.n));
            }
        }
    }

    // A1-U06 — an invalid document frequency is surfaced only when positive
    // scoring reaches it, and a missing prepared IDF fails closed.
    #[test]
    fn a1_u06_invalid_df_and_missing_idf_fail_closed() {
        let invalid = prepared_stats(3, 2.0, &[("t", 4)]);
        assert_eq!(
            invalid.bm25_score("t", 0, 2).unwrap().to_bits(),
            0.0f64.to_bits(),
            "the tf==0 guard precedes the invalid-df error"
        );
        match invalid.bm25_score("t", 1, 2) {
            Err(SearchError::InvalidScore { detail }) => {
                assert_eq!(detail, "document frequency exceeds the live-document count");
            }
            other => panic!("unexpected invalid-df outcome: {other:?}"),
        }

        let empty_snapshot = prepared_stats(0, 0.0, &[("t", 1)]);
        assert_eq!(
            empty_snapshot.bm25_score("t", 2, 0).unwrap().to_bits(),
            0.0f64.to_bits(),
            "n==0 wins over an invalid df"
        );

        let mut broken = prepared_stats(3, 2.0, &[("t", 2)]);
        broken.df.get_mut("t").expect("prepared record").idf = None;
        match broken.bm25_score("t", 1, 2) {
            Err(SearchError::CorruptIndex { detail }) => {
                assert_eq!(detail, "prepared BM25 IDF missing for valid term");
            }
            other => panic!("unexpected missing-idf outcome: {other:?}"),
        }
    }

    // A1-U10 — empty term sets and empty snapshots prepare nothing and score
    // nothing, without new allocations or eager errors.
    #[test]
    fn a1_u10_empty_inputs_prepare_nothing() {
        use crate::analysis::NeverCancel;
        use crate::segment::SegmentLimits;
        const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
        let reader =
            SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).expect("norms golden");
        let field_id = reader.schema().field_id("title").expect("title");
        let limits = SearchLimits::default();
        let readers = [&reader];
        let empty_terms: QueryTerms = BTreeMap::new();
        let live = vec![Rc::new(vec![true, true])];

        super::idf_observation::reset();
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &live,
            &[field_id],
            &empty_terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .expect("empty query terms");
        let field = stats.field(field_id).expect("field stats");
        assert!(field.df.is_empty());
        assert_eq!(super::idf_observation::count(), 0);
        assert_eq!(
            field.bm25_score("hello", 1, 2).unwrap().to_bits(),
            frozen_scalar_bm25(1, 0, 2, 2, field.avgdl)
                .unwrap()
                .to_bits()
        );

        // An all-zero live snapshot keeps `n == 0` and scores `+0.0`.
        let dead = vec![Rc::new(vec![false, false])];
        let terms = query_for(field_id, "hello");
        super::idf_observation::reset();
        let mut work = SearchWork::new(limits.max_total_work_units(), &NeverCancel);
        let stats = compute_stats(
            &readers,
            &dead,
            &[field_id],
            &terms,
            &limits,
            &mut work,
            &NeverCancel,
        )
        .expect("dead snapshot");
        let field = stats.field(field_id).expect("field stats");
        assert_eq!(field.n, 0);
        assert_eq!(field.doc_freq("hello"), 0);
        assert_eq!(super::idf_observation::count(), 0);
        assert_eq!(
            field.bm25_score("hello", 4, 0).unwrap().to_bits(),
            0.0f64.to_bits()
        );
    }
}
