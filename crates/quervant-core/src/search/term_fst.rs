//! Runtime derived term FST and bounded automaton intersection (PR 8).
//!
//! For each `(segment, field)` that a multi-term leaf targets, a
//! [`fst::Set`] is built once per request from the segment's existing sorted
//! UTF-8 dictionary. The FST is derived **in memory only**: no segment section,
//! feature id or dictionary wire encoding changes. The set is queried with the
//! PR 8 scalar automaton through [`fst::Automaton`], which prunes every branch
//! whose automaton state cannot match (`can_match`), so a selective pattern never
//! walks the whole dictionary and a no-match pattern does bounded work.
//!
//! Work is charged per byte transition and cancellation is polled at fixed
//! intervals from inside the automaton, because the `fst` streaming API does not
//! expose a per-transition callback otherwise. `max_fst_bytes` accounts the
//! derived FST's logical encoded size (an estimate, never measured RSS).

use std::cell::{Cell, RefCell};

use fst::automaton::Automaton;
use fst::{IntoStreamer, Set, Streamer};

use crate::analysis::Cancellation;
use crate::analysis::limits::CANCELLATION_POLL_INTERVAL;
use crate::segment::DictionaryEntry;

use super::automaton::{AutomatonScratch, TermPredicate, TermState};
use super::error::{SearchError, SearchResult};

/// Conservative logical per-term overhead used to pre-flight the derived FST
/// before it is built, so an over-budget dictionary is rejected before the large
/// allocation rather than after.
const TERM_OVERHEAD_ESTIMATE: u64 = 16;

/// A derived FST over one `(segment, field)` dictionary.
pub(crate) struct TermFst {
    set: Set<Vec<u8>>,
    logical_bytes: u64,
}

impl TermFst {
    /// Upper-bound the derived FST bytes for `entries` without building it.
    pub(crate) fn estimate_bytes(entries: &[DictionaryEntry]) -> SearchResult<u64> {
        let mut total: u64 = 0;
        for entry in entries {
            let term = u64::try_from(entry.term.len()).unwrap_or(u64::MAX);
            total = total
                .checked_add(term)
                .and_then(|value| value.checked_add(TERM_OVERHEAD_ESTIMATE))
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
        }
        Ok(total)
    }

    /// Build the FST from the segment's sorted dictionary terms.
    pub(crate) fn build(entries: &[DictionaryEntry]) -> SearchResult<Self> {
        let set =
            Set::from_iter(entries.iter().map(|entry| entry.term.as_bytes())).map_err(|_| {
                SearchError::CorruptIndex {
                    detail: "dictionary terms are not strictly sorted".to_owned(),
                }
            })?;
        let logical_bytes = u64::try_from(set.as_fst().size()).unwrap_or(u64::MAX);
        Ok(Self { set, logical_bytes })
    }

    /// Logical encoded bytes retained for this derived FST.
    #[must_use]
    pub(crate) fn logical_bytes(&self) -> u64 {
        self.logical_bytes
    }

    /// Intersect `predicate` with the FST, returning matching dictionary terms in
    /// ascending order. Stops with a typed error when `work_allowance` is spent,
    /// cancellation is observed, or more than `max_terms` terms match. The returned
    /// work count must be charged to the request-wide work budget by the caller.
    pub(crate) fn matches(
        &self,
        predicate: &TermPredicate,
        cancellation: &dyn Cancellation,
        work_allowance: u64,
        max_terms: u64,
    ) -> SearchResult<(Vec<String>, u64)> {
        let matcher = FstMatcher::new(predicate, cancellation, work_allowance);
        let mut terms: Vec<String> = Vec::new();
        let mut stream = self.set.search(&matcher).into_stream();
        while let Some(key) = stream.next() {
            if matcher.cancelled.get() {
                return Err(SearchError::Cancelled);
            }
            if matcher.limit_hit.get() {
                return Err(SearchError::ResourceLimit {
                    limit: work_allowance,
                    requested: matcher.work.get(),
                });
            }
            if terms.len() as u64 >= max_terms {
                return Err(SearchError::ResourceLimit {
                    limit: max_terms,
                    requested: terms.len() as u64 + 1,
                });
            }
            let term = std::str::from_utf8(key).map_err(|_| SearchError::CorruptIndex {
                detail: "dictionary term is not valid UTF-8".to_owned(),
            })?;
            terms.push(term.to_owned());
        }
        if matcher.cancelled.get() {
            return Err(SearchError::Cancelled);
        }
        if matcher.limit_hit.get() {
            return Err(SearchError::ResourceLimit {
                limit: work_allowance,
                requested: matcher.work.get(),
            });
        }
        Ok((terms, matcher.work.get()))
    }
}

/// Partial UTF-8 decoder state.
#[derive(Clone, Copy, Debug, Default)]
struct Decoder {
    remaining: u8,
    value: u32,
}

/// Result of feeding one byte to the decoder.
enum Decoded {
    Complete(char),
    Pending(Decoder),
    Invalid,
}

fn decode_byte(decoder: Decoder, byte: u8) -> Decoded {
    if decoder.remaining == 0 {
        match byte {
            0x00..=0x7F => Decoded::Complete(byte as char),
            0xC2..=0xDF => Decoded::Pending(Decoder {
                remaining: 1,
                value: u32::from(byte & 0x1F),
            }),
            0xE0..=0xEF => Decoded::Pending(Decoder {
                remaining: 2,
                value: u32::from(byte & 0x0F),
            }),
            0xF0..=0xF4 => Decoded::Pending(Decoder {
                remaining: 3,
                value: u32::from(byte & 0x07),
            }),
            _ => Decoded::Invalid,
        }
    } else {
        if byte & 0xC0 != 0x80 {
            return Decoded::Invalid;
        }
        let value = (decoder.value << 6) | u32::from(byte & 0x3F);
        let remaining = decoder.remaining - 1;
        if remaining == 0 {
            match char::from_u32(value) {
                Some(schalar) => Decoded::Complete(schalar),
                None => Decoded::Invalid,
            }
        } else {
            Decoded::Pending(Decoder { remaining, value })
        }
    }
}

/// `fst::Automaton` state: the decoder plus the last complete predicate state.
#[derive(Clone)]
struct MatcherState {
    decoder: Decoder,
    inner: Option<TermState>,
}

impl MatcherState {
    fn dead() -> Self {
        Self {
            decoder: Decoder::default(),
            inner: None,
        }
    }
}

/// Adapter that drives a scalar [`TermPredicate`] from `fst` byte transitions.
struct FstMatcher<'a> {
    predicate: &'a TermPredicate,
    scratch: RefCell<AutomatonScratch>,
    cancellation: &'a dyn Cancellation,
    work_allowance: u64,
    work: Cell<u64>,
    cancelled: Cell<bool>,
    limit_hit: Cell<bool>,
}

impl<'a> FstMatcher<'a> {
    fn new(
        predicate: &'a TermPredicate,
        cancellation: &'a dyn Cancellation,
        work_allowance: u64,
    ) -> Self {
        Self {
            predicate,
            scratch: RefCell::new(AutomatonScratch::new()),
            cancellation,
            work_allowance,
            work: Cell::new(0),
            cancelled: Cell::new(false),
            limit_hit: Cell::new(false),
        }
    }

    fn stopped(&self) -> bool {
        self.cancelled.get() || self.limit_hit.get()
    }

    fn charge_one(&self) -> bool {
        let work = self.work.get().saturating_add(1);
        self.work.set(work);
        if work % CANCELLATION_POLL_INTERVAL == 0 && self.cancellation.is_cancelled() {
            self.cancelled.set(true);
            return false;
        }
        if work > self.work_allowance {
            self.limit_hit.set(true);
            return false;
        }
        true
    }
}

impl Automaton for FstMatcher<'_> {
    type State = MatcherState;

    fn start(&self) -> Self::State {
        MatcherState {
            decoder: Decoder::default(),
            inner: self.predicate.start(),
        }
    }

    fn is_match(&self, state: &Self::State) -> bool {
        if state.decoder.remaining != 0 {
            return false;
        }
        let Some(inner) = &state.inner else {
            return false;
        };
        let mut scratch = self.scratch.borrow_mut();
        self.predicate.is_match(inner, &mut scratch)
    }

    fn can_match(&self, state: &Self::State) -> bool {
        if self.stopped() {
            return false;
        }
        let Some(inner) = &state.inner else {
            return false;
        };
        if state.decoder.remaining != 0 {
            // A scalar is mid-decoding; it can still complete.
            return true;
        }
        let mut scratch = self.scratch.borrow_mut();
        self.predicate.can_match(inner, &mut scratch)
    }

    fn accept(&self, state: &Self::State, byte: u8) -> Self::State {
        if self.stopped() || !self.charge_one() {
            return MatcherState::dead();
        }
        let Some(inner) = &state.inner else {
            return MatcherState::dead();
        };
        match decode_byte(state.decoder, byte) {
            Decoded::Complete(schalar) => {
                let mut scratch = self.scratch.borrow_mut();
                match self.predicate.step(inner, schalar, &mut scratch) {
                    Some(next) => MatcherState {
                        decoder: Decoder::default(),
                        inner: Some(next),
                    },
                    None => MatcherState::dead(),
                }
            }
            Decoded::Pending(decoder) => MatcherState {
                decoder,
                inner: Some(inner.clone()),
            },
            Decoded::Invalid => MatcherState::dead(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::config::{NormalizationForm, Pipeline, TokenFilter, TokenizerKind};
    use crate::analysis::{AnalysisLimits, AnalyzerDefinition, NeverCancel, prepare_prefix};

    fn entries(terms: &[&str]) -> Vec<DictionaryEntry> {
        terms
            .iter()
            .enumerate()
            .map(|(index, term)| DictionaryEntry {
                term: (*term).to_owned(),
                doc_freq: 1,
                postings_offset: index as u64,
                postings_length: 1,
            })
            .collect()
    }

    fn analyzer() -> AnalyzerDefinition {
        AnalyzerDefinition::uniform(
            "kw",
            "1.0.0",
            Pipeline::simple(
                TokenizerKind::Keyword,
                vec![TokenFilter::Normalize(NormalizationForm::None)],
            )
            .unwrap(),
        )
        .unwrap()
    }

    #[test]
    fn fst_intersects_prefix_in_order() {
        let entries = entries(&["crust", "rust", "rusty", "trust"]);
        let fst = TermFst::build(&entries).unwrap();
        let prepared = prepare_prefix(
            &analyzer(),
            "rust",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        let predicate = TermPredicate::prefix(&prepared);
        let (terms, work) = fst.matches(&predicate, &NeverCancel, 10_000, 100).unwrap();
        assert_eq!(terms, vec!["rust", "rusty"]);
        assert!(work > 0);
    }

    #[test]
    fn fst_no_match_does_bounded_work() {
        let entries = entries(&["alpha", "beta", "gamma"]);
        let fst = TermFst::build(&entries).unwrap();
        let prepared =
            prepare_prefix(&analyzer(), "zzz", &AnalysisLimits::default(), &NeverCancel).unwrap();
        let predicate = TermPredicate::prefix(&prepared);
        let (terms, work) = fst.matches(&predicate, &NeverCancel, 10_000, 100).unwrap();
        assert!(terms.is_empty());
        // Only the root transitions were charged, not one per dictionary entry.
        assert!(work <= 3);
    }

    #[test]
    fn fst_expansion_limit_is_typed() {
        let entries = entries(&["ra", "rb", "rc"]);
        let fst = TermFst::build(&entries).unwrap();
        let prepared =
            prepare_prefix(&analyzer(), "r", &AnalysisLimits::default(), &NeverCancel).unwrap();
        let predicate = TermPredicate::prefix(&prepared);
        assert!(matches!(
            fst.matches(&predicate, &NeverCancel, 10_000, 2),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn fst_work_allowance_is_enforced() {
        let entries = entries(&["ra", "rb", "rc"]);
        let fst = TermFst::build(&entries).unwrap();
        let prepared =
            prepare_prefix(&analyzer(), "r", &AnalysisLimits::default(), &NeverCancel).unwrap();
        let predicate = TermPredicate::prefix(&prepared);
        assert!(matches!(
            fst.matches(&predicate, &NeverCancel, 1, 100),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn build_rejects_unsorted_terms() {
        let entries = entries(&["b", "a"]);
        assert!(matches!(
            TermFst::build(&entries),
            Err(SearchError::CorruptIndex { .. })
        ));
    }

    #[test]
    fn estimate_is_an_upper_bound_guard() {
        let entries = entries(&["abc", "abd"]);
        let estimate = TermFst::estimate_bytes(&entries).unwrap();
        assert!(estimate >= 6);
    }
}
