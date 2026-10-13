//! Positional phrase verification (PR 7, D07-02/D07-04).
//!
//! A phrase matches iff there is an ordered chain of occurrences in the **same
//! field value** whose start positions follow the analyzed query positions and
//! the previous occurrence's `position_length`. Source byte offsets are never used
//! as a positional substitute, and multi-valued field boundaries are never
//! bridged (the `value_index` must be identical for the whole chain).

use std::collections::HashMap;

use crate::analysis::Cancellation;
use crate::segment::Occurrence;

use super::error::SearchResult;
use super::execute::SearchWork;
use super::plan::PhraseToken;

/// One document's matched phrase and the frequency of each distinct constituent
/// term used for BM25 ranking.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PhraseMatch {
    pub(crate) doc_id: u64,
    /// `(term, frequency)` for each distinct constituent term, deduplicated.
    pub(crate) term_freqs: Vec<(String, u64)>,
}

/// Occurrences for one distinct phrase term within a segment.
#[derive(Debug, Default)]
pub(crate) struct PhraseTermData {
    /// The analyzed term.
    pub(crate) term: String,
    /// Ascending live doc ids containing the term.
    pub(crate) docs: Vec<u64>,
    /// Occurrences by doc id.
    pub(crate) occurrences: HashMap<u64, Vec<Occurrence>>,
}

/// Verify a phrase for every candidate document and return the matching docs.
///
/// `per_token` is aligned with `tokens`; repeated tokens reuse the same
/// [`PhraseTermData`]. Candidate docs are the intersection of all distinct term
/// doc sets.
pub(crate) fn match_phrase(
    tokens: &[PhraseToken],
    per_token: &[&PhraseTermData],
    work: &mut SearchWork<'_>,
    _cancel: &dyn Cancellation,
) -> SearchResult<Vec<PhraseMatch>> {
    debug_assert_eq!(tokens.len(), per_token.len());
    if tokens.is_empty() {
        return Ok(Vec::new());
    }
    // Distinct term data, preserving first appearance for deterministic output.
    let mut distinct: Vec<&PhraseTermData> = Vec::new();
    'outer: for data in per_token {
        for existing in &distinct {
            if std::ptr::eq(*existing, *data) {
                continue 'outer;
            }
        }
        distinct.push(*data);
    }
    let mut candidates: Vec<u64> = Vec::new();
    if let Some(first) = distinct.first() {
        candidates.extend_from_slice(&first.docs);
    }
    for data in distinct.iter().skip(1) {
        candidates = intersect_sorted(&candidates, &data.docs);
        if candidates.is_empty() {
            break;
        }
    }

    let mut matches = Vec::new();
    for doc_id in candidates {
        work.check_cancelled()?;
        let mut token_occurrences: Vec<&[Occurrence]> = Vec::with_capacity(tokens.len());
        let mut complete = true;
        for data in per_token {
            match data.occurrences.get(&doc_id) {
                Some(occurrences) => token_occurrences.push(occurrences.as_slice()),
                None => {
                    complete = false;
                    break;
                }
            }
        }
        if !complete {
            continue;
        }
        if phrase_chains(tokens, &token_occurrences, work)? {
            let mut term_freqs = Vec::with_capacity(distinct.len());
            for data in &distinct {
                let freq = data
                    .occurrences
                    .get(&doc_id)
                    .map(|occurrences| occurrences.len() as u64)
                    .unwrap_or(0);
                term_freqs.push((data.term.clone(), freq));
            }
            term_freqs.sort();
            term_freqs.dedup_by(|left, right| left.0 == right.0);
            matches.push(PhraseMatch { doc_id, term_freqs });
        }
    }
    Ok(matches)
}

/// Whether any occurrence chain satisfies the query positions.
fn phrase_chains(
    tokens: &[PhraseToken],
    per_token: &[&[Occurrence]],
    work: &mut SearchWork<'_>,
) -> SearchResult<bool> {
    // Partial chains as occurrence references.
    let mut current: Vec<&Occurrence> = per_token[0].iter().collect();
    for index in 1..tokens.len() {
        work.check_cancelled()?;
        let previous = &tokens[index - 1];
        let next = &tokens[index];
        let gap = next
            .position
            .saturating_sub(previous.position)
            .saturating_sub(1);
        let mut advanced: Vec<&Occurrence> = Vec::new();
        for previous_occurrence in &current {
            work.charge(1)?;
            let required = previous_occurrence
                .position
                .checked_add(previous_occurrence.position_length)
                .and_then(|value| value.checked_add(gap));
            let Some(required) = required else {
                continue;
            };
            for occurrence in per_token[index] {
                if occurrence.position > required {
                    break;
                }
                if occurrence.position == required
                    && occurrence.value_index == previous_occurrence.value_index
                {
                    advanced.push(occurrence);
                    break;
                }
            }
        }
        if advanced.is_empty() {
            return Ok(false);
        }
        current = advanced;
    }
    Ok(!current.is_empty())
}

fn intersect_sorted(left: &[u64], right: &[u64]) -> Vec<u64> {
    let mut result = Vec::new();
    let (mut i, mut j) = (0usize, 0usize);
    while i < left.len() && j < right.len() {
        match left[i].cmp(&right[j]) {
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
            std::cmp::Ordering::Equal => {
                result.push(left[i]);
                i += 1;
                j += 1;
            }
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn occurrence(position: u64, position_length: u64, value_index: u64) -> Occurrence {
        Occurrence {
            position,
            position_length,
            value_index,
            start_offset: 0,
            end_offset: 1,
        }
    }

    fn token(term: &str, position: u64) -> PhraseToken {
        PhraseToken {
            term: term.to_owned(),
            position,
            position_length: 1,
        }
    }

    fn data(term: &str, docs: Vec<(u64, Vec<Occurrence>)>) -> PhraseTermData {
        let mut result = PhraseTermData {
            term: term.to_owned(),
            ..PhraseTermData::default()
        };
        for (doc, occurrences) in docs {
            result.docs.push(doc);
            result.occurrences.insert(doc, occurrences);
        }
        result
    }

    fn run(tokens: &[PhraseToken], data: &[&PhraseTermData]) -> Vec<PhraseMatch> {
        let limits = crate::search::SearchLimits::default();
        let cancel = crate::analysis::NeverCancel;
        let mut work = SearchWork::new(limits.max_total_work_units(), &cancel);
        match_phrase(tokens, data, &mut work, &cancel).unwrap()
    }

    #[test]
    fn adjacent_match() {
        let a = data("a", vec![(1, vec![occurrence(0, 1, 0)])]);
        let b = data("b", vec![(1, vec![occurrence(1, 1, 0)])]);
        let tokens = [token("a", 0), token("b", 1)];
        let matches = run(&tokens, &[&a, &b]);
        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].doc_id, 1);
        assert_eq!(matches[0].term_freqs.len(), 2);
    }

    #[test]
    fn stopword_gap_requires_the_hole() {
        let a = data("a", vec![(1, vec![occurrence(0, 1, 0)])]);
        let b = data("b", vec![(1, vec![occurrence(2, 1, 0)])]);
        // Query positions 0 and 2 (one dropped stopword between).
        let tokens = [token("a", 0), token("b", 2)];
        assert_eq!(run(&tokens, &[&a, &b]).len(), 1);
        // Same query positions must not match adjacent index positions.
        let adjacent = data("b", vec![(1, vec![occurrence(1, 1, 0)])]);
        assert!(run(&tokens, &[&a, &adjacent]).is_empty());
    }

    #[test]
    fn multi_value_boundaries_are_never_bridged() {
        // 'a' in value 0 at position 0; 'b' in value 1 at position 100.
        let a = data("a", vec![(1, vec![occurrence(0, 1, 0)])]);
        let b = data("b", vec![(1, vec![occurrence(100, 1, 1)])]);
        let tokens = [token("a", 0), token("b", 1)];
        assert!(run(&tokens, &[&a, &b]).is_empty());
    }

    #[test]
    fn repeated_words_require_distinct_successive_positions() {
        let a = data(
            "a",
            vec![(1, vec![occurrence(0, 1, 0), occurrence(1, 1, 0)])],
        );
        let tokens = [token("a", 0), token("a", 1)];
        let matches = run(&tokens, &[&a, &a]);
        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].term_freqs.len(), 1);
        assert_eq!(matches[0].term_freqs[0].1, 2);
    }

    #[test]
    fn position_length_is_respected() {
        // First token spans two positions; next must start at 0 + 2.
        let a = data("a", vec![(1, vec![occurrence(0, 2, 0)])]);
        let b = data("b", vec![(1, vec![occurrence(2, 1, 0)])]);
        let tokens = [token("a", 0), token("b", 1)];
        assert_eq!(run(&tokens, &[&a, &b]).len(), 1);
        let wrong = data("b", vec![(1, vec![occurrence(1, 1, 0)])]);
        assert!(run(&tokens, &[&a, &wrong]).is_empty());
    }

    #[test]
    fn no_candidates_is_empty() {
        let a = data("a", vec![(1, vec![occurrence(0, 1, 0)])]);
        let b = data("b", Vec::new());
        let tokens = [token("a", 0), token("b", 1)];
        assert!(run(&tokens, &[&a, &b]).is_empty());
    }
}
