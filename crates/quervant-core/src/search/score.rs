//! BM25 scoring and snapshot-wide field statistics (PR 7, D07-04).
//!
//! This is the deliberately simple v1 reference implementation: no on-disk norms
//! are added. Per-field document lengths and document frequencies are recomputed
//! from the immutable dictionary/postings once per search, with explicit work and
//! allocation bounds. All statistics are computed across every segment before any
//! segment is scored.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::rc::Rc;

use crate::analysis::Cancellation;
use crate::segment::SegmentReader;

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

/// Per-field snapshot statistics.
#[derive(Debug, Default)]
pub(crate) struct FieldStats {
    /// Live documents in the whole snapshot.
    pub(crate) n: u64,
    /// Average live document field length (`0.0` when empty).
    pub(crate) avgdl: f64,
    /// Document frequency for each scoring term on this field.
    pub(crate) df: HashMap<String, u64>,
    /// Per-segment document field lengths (`segment index -> doc -> length`).
    pub(crate) lengths: Vec<HashMap<u64, u64>>,
}

impl FieldStats {
    /// Field length for a physical doc in a segment (0 if the field is absent).
    pub(crate) fn length(&self, segment: usize, doc_id: u64) -> u64 {
        self.lengths
            .get(segment)
            .and_then(|map| map.get(&doc_id))
            .copied()
            .unwrap_or(0)
    }

    /// Document frequency for a scoring term (0 if absent).
    pub(crate) fn doc_freq(&self, term: &str) -> u64 {
        self.df.get(term).copied().unwrap_or(0)
    }
}

/// Snapshot-wide statistics for every scoring field.
#[derive(Debug, Default)]
pub(crate) struct SnapshotStats {
    pub(crate) fields: BTreeMap<u32, FieldStats>,
}

impl SnapshotStats {
    pub(crate) fn field(&self, field_id: u32) -> Option<&FieldStats> {
        self.fields.get(&field_id)
    }
}

/// The per-field query terms whose document frequency must be materialized.
pub(crate) type QueryTerms = BTreeMap<u32, BTreeSet<String>>;

/// Accumulate one term posting into a document field-length map.
///
/// Occupancy is determined by the `HashMap::Entry` state, never by the stored
/// length value: a legitimately present zero-length entry is occupied and must not
/// be charged again when its next positive posting arrives. A new entry's
/// entry/byte bounds are enforced **before** insertion so a rejected call leaves the
/// map unchanged.
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

/// Compute live counts, document frequencies and document lengths for every
/// scoring field across the whole snapshot.
#[allow(clippy::too_many_arguments)]
pub(crate) fn compute_stats(
    readers: &[&SegmentReader],
    live: &[Rc<Vec<bool>>],
    scoring_field_ids: &[u32],
    query_terms: &QueryTerms,
    limits: &SearchLimits,
    work: &mut SearchWork<'_>,
    cancel: &dyn Cancellation,
) -> SearchResult<SnapshotStats> {
    let n: u64 = live.iter().try_fold(0u64, |acc, segment| {
        let count = segment.iter().filter(|flag| **flag).count() as u64;
        acc.checked_add(count).ok_or(SearchError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })
    })?;
    let mut fields: BTreeMap<u32, FieldStats> = BTreeMap::new();
    for field_id in scoring_field_ids {
        let mut stats = FieldStats {
            n,
            avgdl: 0.0,
            df: HashMap::new(),
            lengths: (0..readers.len()).map(|_| HashMap::new()).collect(),
        };
        if let Some(terms) = query_terms.get(field_id) {
            for term in terms {
                stats.df.insert(term.clone(), 0);
            }
        }
        fields.insert(*field_id, stats);
    }

    let mut total_lengths: BTreeMap<u32, u64> = BTreeMap::new();
    for field_id in scoring_field_ids {
        total_lengths.insert(*field_id, 0);
    }

    let mut length_entries: u64 = 0;
    let mut length_bytes: u64 = 0;
    let mut dictionary_terms: u64 = 0;

    for (segment_index, reader) in readers.iter().enumerate() {
        work.check_cancelled()?;
        if reader.doc_count() != live[segment_index].len() as u64 {
            return Err(SearchError::CorruptIndex {
                detail: "segment live bitmap length does not match doc count".to_owned(),
            });
        }
        for field_id in scoring_field_ids {
            let entries = reader
                .dictionary()
                .and_then(|dictionary| dictionary.field(*field_id));
            let Some(entries) = entries else {
                continue;
            };
            let stats = fields
                .get_mut(field_id)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "field statistics were not initialized".to_owned(),
                })?;
            for entry in entries {
                work.check_cancelled()?;
                dictionary_terms =
                    dictionary_terms
                        .checked_add(1)
                        .ok_or(SearchError::ResourceLimit {
                            limit: limits.max_dictionary_terms_examined(),
                            requested: u64::MAX,
                        })?;
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
                    let doc_id = posting.doc_id;
                    let is_live = *live[segment_index]
                        .get(usize::try_from(doc_id).unwrap_or(usize::MAX))
                        .ok_or_else(|| SearchError::CorruptIndex {
                            detail: "posting doc id is out of range".to_owned(),
                        })?;
                    if !is_live {
                        continue;
                    }
                    let total = total_lengths.get_mut(field_id).ok_or_else(|| {
                        SearchError::CorruptIndex {
                            detail: "field length accumulator missing".to_owned(),
                        }
                    })?;
                    *total = total
                        .checked_add(posting.freq)
                        .ok_or(SearchError::ResourceLimit {
                            limit: u64::MAX,
                            requested: u64::MAX,
                        })?;
                    let segment_lengths =
                        stats.lengths.get_mut(segment_index).ok_or_else(|| {
                            SearchError::CorruptIndex {
                                detail: "segment length map missing".to_owned(),
                            }
                        })?;
                    accumulate_length(
                        segment_lengths,
                        doc_id,
                        posting.freq,
                        limits.max_field_length_entries(),
                        limits.max_field_length_bytes(),
                        &mut length_entries,
                        &mut length_bytes,
                    )?;
                    if is_query_term {
                        let df = stats.df.get_mut(&entry.term).ok_or_else(|| {
                            SearchError::CorruptIndex {
                                detail: "term document-frequency slot missing".to_owned(),
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
    }

    for (field_id, stats) in &mut fields {
        let total = total_lengths.get(field_id).copied().unwrap_or(0);
        stats.avgdl = if stats.n > 0 {
            total as f64 / stats.n as f64
        } else {
            0.0
        };
    }
    Ok(SnapshotStats { fields })
}

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
        let stats = FieldStats::default();
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
}
