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
pub(crate) fn bm25(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> SearchResult<f64> {
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

/// How one segment's lengths for one field are sourced.
pub(crate) enum SegmentLengths<'a> {
    /// Immutable persisted norms (physical-doc order).
    Persisted(&'a [u64]),
    /// Reconstructed from postings for a legacy segment.
    Legacy(HashMap<u64, u64>),
}

/// Per-field snapshot statistics.
pub(crate) struct FieldStats<'a> {
    /// Live documents in the whole snapshot.
    pub(crate) n: u64,
    /// Average live document field length (`0.0` when empty).
    pub(crate) avgdl: f64,
    /// Document frequency for each scoring term on this field.
    pub(crate) df: HashMap<String, u64>,
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
    pub(crate) fn doc_freq(&self, term: &str) -> u64 {
        self.df.get(term).copied().unwrap_or(0)
    }
}

/// Snapshot-wide statistics for every scoring field.
#[derive(Debug)]
pub(crate) struct SnapshotStats<'a> {
    pub(crate) fields: BTreeMap<u32, FieldStats<'a>>,
}

impl<'a> SnapshotStats<'a> {
    pub(crate) fn field(&self, field_id: u32) -> Option<&FieldStats<'a>> {
        self.fields.get(&field_id)
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
    let n: u64 = live.iter().try_fold(0u64, |acc, segment| {
        let count = segment.iter().filter(|flag| **flag).count() as u64;
        acc.checked_add(count).ok_or(SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })
    })?;
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
                stats.df.insert(term.clone(), 0);
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
                    let all_live = segment_live.iter().all(|flag| *flag);
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
                                    let df = stats.df.get_mut(term).ok_or_else(|| {
                                        SearchError::CorruptIndex {
                                            detail: "term df slot missing".to_owned(),
                                        }
                                    })?;
                                    *df = df.checked_add(entry.doc_freq).ok_or(
                                        SearchError::ResourceLimit {
                                            limit: n,
                                            requested: u64::MAX,
                                        },
                                    )?;
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
                                    let df = stats.df.get_mut(term).ok_or_else(|| {
                                        SearchError::CorruptIndex {
                                            detail: "term df slot missing".to_owned(),
                                        }
                                    })?;
                                    *df = df.checked_add(1).ok_or(SearchError::ResourceLimit {
                                        limit: n,
                                        requested: u64::MAX,
                                    })?;
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
                                    let df = stats.df.get_mut(&entry.term).ok_or_else(|| {
                                        SearchError::CorruptIndex {
                                            detail: "term df slot missing".to_owned(),
                                        }
                                    })?;
                                    *df = df.checked_add(1).ok_or(SearchError::ResourceLimit {
                                        limit: n,
                                        requested: u64::MAX,
                                    })?;
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
        fields.insert(*field_id, stats);
    }
    Ok(SnapshotStats { fields })
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
}
