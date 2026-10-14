//! Deterministic bounded top-K selection (PR 7, D07-05).
//!
//! Results are ordered by BM25 score descending, then by `DocumentKey` bytewise
//! ascending. A bounded binary heap keeps only `K` entries (O(K) result memory);
//! the full candidate map is bounded separately by the caller.

use std::cmp::Ordering;
use std::collections::BinaryHeap;

use crate::contract::document::DocumentKey;

use super::error::{SearchError, SearchResult};

/// One scored document in the heap. `Ord` is inverted so the heap root is the
/// *worst* retained hit: lower score first, then larger key.
#[derive(Debug, Clone)]
struct HeapEntry {
    key: DocumentKey,
    score: f64,
}

impl PartialEq for HeapEntry {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == Ordering::Equal
    }
}

impl Eq for HeapEntry {}

impl PartialOrd for HeapEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        self.score
            .total_cmp(&other.score)
            .reverse()
            .then_with(|| self.key.cmp(&other.key))
    }
}

/// A bounded top-K selector.
#[derive(Debug)]
pub(crate) struct TopKSelector {
    heap: BinaryHeap<HeapEntry>,
    limit: usize,
    bytes: u64,
    max_bytes: u64,
}

impl TopKSelector {
    /// Build a selector for at most `limit` hits, bounded by `max_bytes`.
    pub(crate) fn new(limit: usize, max_bytes: u64) -> SearchResult<Self> {
        if limit == 0 {
            return Err(SearchError::ResourceLimit {
                limit: 0,
                requested: 0,
            });
        }
        let base = u64::try_from(limit)
            .unwrap_or(u64::MAX)
            .checked_mul(std::mem::size_of::<HeapEntry>() as u64)
            .ok_or(SearchError::ResourceLimit {
                limit: max_bytes,
                requested: u64::MAX,
            })?;
        if base > max_bytes {
            return Err(SearchError::ResourceLimit {
                limit: max_bytes,
                requested: base,
            });
        }
        Ok(Self {
            heap: BinaryHeap::new(),
            limit,
            bytes: 0,
            max_bytes,
        })
    }

    /// Offer one scored document. Never fails on a valid finite score; a
    /// non-finite score is a typed failure.
    pub(crate) fn push(&mut self, key: DocumentKey, score: f64) -> SearchResult<()> {
        if !score.is_finite() || score < 0.0 {
            return Err(SearchError::InvalidScore {
                detail: "top-K received a non-finite or negative score",
            });
        }
        let entry = HeapEntry { key, score };
        let entry_size = std::mem::size_of::<HeapEntry>() as u64;
        if self.heap.len() < self.limit {
            let entry_bytes = entry_size + entry.key.as_str().len() as u64;
            let new_bytes =
                self.bytes
                    .checked_add(entry_bytes)
                    .ok_or(SearchError::ResourceLimit {
                        limit: self.max_bytes,
                        requested: u64::MAX,
                    })?;
            if new_bytes > self.max_bytes {
                return Err(SearchError::ResourceLimit {
                    limit: self.max_bytes,
                    requested: new_bytes,
                });
            }
            self.bytes = new_bytes;
            self.heap.push(entry);
            return Ok(());
        }
        let is_better = self
            .heap
            .peek()
            .is_some_and(|worst| entry.cmp(worst) == Ordering::Less);
        if is_better {
            // Compute the replacement total and enforce the bound **before** any
            // mutation so a failed replacement leaves the selector unchanged.
            let worst = self.heap.peek().expect("heap is non-empty");
            let evicted_bytes = entry_size + worst.key.as_str().len() as u64;
            let entry_bytes = entry_size + entry.key.as_str().len() as u64;
            let replacement = self
                .bytes
                .checked_sub(evicted_bytes)
                .and_then(|bytes| bytes.checked_add(entry_bytes))
                .ok_or(SearchError::ResourceLimit {
                    limit: self.max_bytes,
                    requested: u64::MAX,
                })?;
            if replacement > self.max_bytes {
                return Err(SearchError::ResourceLimit {
                    limit: self.max_bytes,
                    requested: replacement,
                });
            }
            let evicted = self.heap.pop().expect("heap is non-empty");
            debug_assert_eq!(
                evicted_bytes,
                entry_size + evicted.key.as_str().len() as u64
            );
            self.bytes = replacement;
            self.heap.push(entry);
        }
        Ok(())
    }

    /// Consume the selector, returning hits best-first.
    pub(crate) fn finish(self) -> Vec<(DocumentKey, f64)> {
        self.heap
            .into_sorted_vec()
            .into_iter()
            .map(|entry| (entry.key, entry.score))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn select(input: Vec<(&str, f64)>, k: usize) -> Vec<(String, f64)> {
        let mut selector = TopKSelector::new(k, u64::MAX).unwrap();
        for (value, score) in input {
            selector.push(key(value), score).unwrap();
        }
        selector
            .finish()
            .into_iter()
            .map(|(key, score)| (key.as_str().to_owned(), score))
            .collect()
    }

    #[test]
    fn orders_by_score_then_key() {
        let hits = select(vec![("b", 1.0), ("a", 1.0), ("c", 2.0), ("d", 0.5)], 4);
        assert_eq!(
            hits,
            vec![
                ("c".to_owned(), 2.0),
                ("a".to_owned(), 1.0),
                ("b".to_owned(), 1.0),
                ("d".to_owned(), 0.5),
            ]
        );
    }

    #[test]
    fn matches_full_sort_prefix() {
        let input: Vec<(&str, f64)> =
            vec![("g", 0.1), ("a", 3.0), ("f", 2.5), ("b", 2.5), ("c", 0.0)];
        for k in 1..=5 {
            let selected = select(input.clone(), k);
            let mut full = input.clone();
            full.sort_by(|left, right| {
                right.1.total_cmp(&left.1).then_with(|| left.0.cmp(right.0))
            });
            let expected: Vec<(String, f64)> = full
                .into_iter()
                .take(k)
                .map(|(key, score)| (key.to_owned(), score))
                .collect();
            assert_eq!(selected, expected, "k={k}");
        }
    }

    #[test]
    fn limit_and_byte_bounds_are_enforced() {
        assert!(TopKSelector::new(0, u64::MAX).is_err());
        assert!(TopKSelector::new(1, 1).is_err());
        let mut selector = TopKSelector::new(1, u64::MAX).unwrap();
        assert!(matches!(
            selector.push(key("a"), f64::NAN),
            Err(SearchError::InvalidScore { .. })
        ));
        assert!(selector.push(key("a"), 1.0).is_ok());
    }

    #[test]
    fn tie_breaks_are_stable_for_many_entries() {
        let input: Vec<(&str, f64)> = (0..50)
            .map(|index| {
                let leaked: &'static str = Box::leak(format!("k{index:02}").into_boxed_str());
                (leaked, 1.0)
            })
            .collect();
        let hits = select(input, 10);
        let keys: Vec<&str> = hits.iter().map(|(key, _)| key.as_str()).collect();
        assert_eq!(
            keys,
            vec![
                "k00", "k01", "k02", "k03", "k04", "k05", "k06", "k07", "k08", "k09"
            ]
        );
    }

    // P04 — bounded heap equals the full-sort prefix for seeded random input.
    #[test]
    fn p04_heap_matches_full_sort_for_seeded_cases() {
        let mut state: u64 = 0x1234_5678_9abc_def0;
        let mut next = || {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            state
        };
        for case in 0..200 {
            let count = (next() % 40) as usize + 1;
            let mut input: Vec<(String, f64)> = Vec::with_capacity(count);
            for index in 0..count {
                // Small score domain to force frequent ties.
                let score = ((next() % 5) as f64) / 2.0;
                input.push((format!("k{index:03}"), score));
            }
            let k = (next() % count as u64) as usize + 1;
            let mut selector = TopKSelector::new(k, u64::MAX).unwrap();
            for (key, score) in &input {
                selector
                    .push(DocumentKey::new(key.clone()).unwrap(), *score)
                    .unwrap();
            }
            let selected: Vec<(String, f64)> = selector
                .finish()
                .into_iter()
                .map(|(key, score)| (key.as_str().to_owned(), score))
                .collect();
            let mut full = input.clone();
            full.sort_by(|left, right| {
                right
                    .1
                    .total_cmp(&left.1)
                    .then_with(|| left.0.cmp(&right.0))
            });
            let expected: Vec<(String, f64)> = full.into_iter().take(k).collect();
            assert_eq!(selected, expected, "case {case} k={k}");
        }
    }

    // H01 — a replacement that would grow past the byte bound fails before mutation.
    #[test]
    fn h01_replacement_growth_is_checked_before_mutation() {
        let entry_size = std::mem::size_of::<HeapEntry>() as u64;
        // Exactly enough for two one-byte keys.
        let max_bytes = 2 * entry_size + 2;
        let mut selector = TopKSelector::new(2, max_bytes).unwrap();
        selector.push(key("a"), 1.0).unwrap();
        selector.push(key("b"), 2.0).unwrap();
        let long = "z".repeat(64);
        let error = selector.push(key(&long), 3.0).unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        // The heap is unchanged and still usable.
        assert_eq!(
            selector.clone_finish_keys(),
            vec!["b".to_owned(), "a".to_owned()]
        );
        // A replacement with a one-byte key fits and succeeds.
        let mut selector = TopKSelector::new(2, max_bytes).unwrap();
        selector.push(key("a"), 1.0).unwrap();
        selector.push(key("b"), 2.0).unwrap();
        selector.push(key("c"), 3.0).unwrap();
        assert_eq!(
            selector
                .finish()
                .into_iter()
                .map(|(key, _)| key.as_str().to_owned())
                .collect::<Vec<_>>(),
            vec!["c".to_owned(), "b".to_owned()]
        );
    }

    // H02 — shorter/equal-key replacements match the full-sort ordering.
    #[test]
    fn h02_shorter_replacement_matches_full_sort() {
        let input: Vec<(&str, f64)> = vec![
            ("aaa", 1.0),
            ("bb", 2.0),
            ("c", 3.0),
            ("dddd", 0.5),
            ("e", 4.0),
        ];
        for k in 1..=input.len() {
            let selected = select(input.clone(), k);
            let mut full = input.clone();
            full.sort_by(|left, right| {
                right.1.total_cmp(&left.1).then_with(|| left.0.cmp(right.0))
            });
            let expected: Vec<(String, f64)> = full
                .into_iter()
                .take(k)
                .map(|(key, score)| (key.to_owned(), score))
                .collect();
            assert_eq!(selected, expected, "k={k}");
        }
    }

    impl TopKSelector {
        /// Test-only: drain a clone of the current ordering without consuming self.
        fn clone_finish_keys(&self) -> Vec<String> {
            self.heap
                .clone()
                .into_sorted_vec()
                .into_iter()
                .map(|entry| entry.key.as_str().to_owned())
                .collect()
        }
    }
}
