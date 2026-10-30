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
use super::execute::SearchWork;

/// Conservative logical per-term overhead used to pre-flight the derived FST
/// before it is built, so an over-budget dictionary is rejected before the large
/// allocation rather than after.
const TERM_OVERHEAD_ESTIMATE: u64 = 16;
/// Fixed logical reservation for the encoded FST header/index. A non-empty
/// `fst::Set` always carries a small fixed header (~39 bytes measured), so a
/// per-term-only estimate would under-reserve tiny dictionaries. This is a
/// required correction to the amendment's per-term model; it is a private logical
/// constant, not a published default.
const FST_BASE_RESERVATION: u64 = 64;

/// A derived FST over one `(segment, field)` dictionary, or an explicit empty
/// marker for a dictionary with no entries.
pub(crate) struct TermFst {
    set: Option<Set<Vec<u8>>>,
    logical_bytes: u64,
}

// Test-only per-thread count of `Set::from_iter` invocations, used to prove that
// an over-budget request never starts a build.
//
// The counter is thread-local on purpose: these preflight witnesses reset and
// assert it while the whole library test binary runs in parallel, so a
// process-global counter would observe unrelated concurrent builds. The tracked
// builds in the two preflight tests are synchronous and run on the calling test
// thread, which makes a per-thread count an exact witness for them.
#[cfg(test)]
thread_local! {
    static BUILD_INVOCATIONS: Cell<u64> = const { Cell::new(0) };
}

#[cfg(test)]
pub(crate) fn build_invocations() -> u64 {
    BUILD_INVOCATIONS.with(Cell::get)
}

#[cfg(test)]
pub(crate) fn reset_build_invocations() {
    BUILD_INVOCATIONS.with(|counter| counter.set(0));
}

impl TermFst {
    /// An explicit empty derived FST (no dictionary entries). It never builds an
    /// `fst::Set`, so a zero reservation is truthful.
    pub(crate) fn empty() -> Self {
        Self {
            set: None,
            logical_bytes: 0,
        }
    }

    /// Deterministic work model for building the FST over `entries`: one unit per
    /// insertion plus one unit per UTF-8 input byte.
    ///
    /// This is the reference model used to verify the charged production preflight
    /// ([`Self::preflight_build`]); it is test-only so production never performs an
    /// uncharged second scan over the dictionary.
    #[cfg(test)]
    pub(crate) fn estimate_build_work(entries: &[DictionaryEntry]) -> SearchResult<u64> {
        let mut total: u64 = 0;
        for entry in entries {
            let term_bytes =
                u64::try_from(entry.term.len()).map_err(|_| SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            total = total
                .checked_add(term_bytes)
                .and_then(|value| value.checked_add(1))
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
        }
        Ok(total)
    }

    /// Single charged preflight walk.
    ///
    /// Charges `1 + term_bytes` per entry to the shared request-wide work ledger,
    /// polls cancellation at least every 256 entries (and after the final entry),
    /// and returns the conservative retained-memory reservation for this FST. The
    /// cumulative `current_total + reservation` is checked against `max_fst_bytes`
    /// as it grows, so an over-budget dictionary is rejected **before** any build.
    pub(crate) fn preflight_build(
        entries: &[DictionaryEntry],
        current_total: u64,
        max_fst_bytes: u64,
        work: &mut SearchWork<'_>,
        cancel: &dyn Cancellation,
    ) -> SearchResult<u64> {
        work.check_cancelled()?;
        let mut reservation: u64 = FST_BASE_RESERVATION;
        for (index, entry) in entries.iter().enumerate() {
            let term_bytes =
                u64::try_from(entry.term.len()).map_err(|_| SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            let units = term_bytes
                .checked_add(1)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            work.charge(units)?;
            reservation = reservation
                .checked_add(term_bytes)
                .and_then(|value| value.checked_add(TERM_OVERHEAD_ESTIMATE))
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            let projected =
                current_total
                    .checked_add(reservation)
                    .ok_or(SearchError::ResourceLimit {
                        limit: max_fst_bytes,
                        requested: u64::MAX,
                    })?;
            if projected > max_fst_bytes {
                return Err(SearchError::ResourceLimit {
                    limit: max_fst_bytes,
                    requested: projected,
                });
            }
            if index % 256 == 0 && cancel.is_cancelled() {
                return Err(SearchError::Cancelled);
            }
        }
        if cancel.is_cancelled() {
            return Err(SearchError::Cancelled);
        }
        Ok(reservation)
    }

    /// Build the FST from the segment's sorted dictionary terms. Callers must have
    /// completed [`Self::preflight_build`] for these exact entries first.
    pub(crate) fn build(entries: &[DictionaryEntry]) -> SearchResult<Self> {
        #[cfg(test)]
        BUILD_INVOCATIONS.with(|counter| {
            counter.set(
                counter
                    .get()
                    .checked_add(1)
                    .expect("test FST invocation counter overflow"),
            );
        });
        let set =
            Set::from_iter(entries.iter().map(|entry| entry.term.as_bytes())).map_err(|_| {
                SearchError::CorruptIndex {
                    detail: "dictionary terms are not strictly sorted".to_owned(),
                }
            })?;
        let logical_bytes = u64::try_from(set.as_fst().size()).unwrap_or(u64::MAX);
        Ok(Self {
            set: Some(set),
            logical_bytes,
        })
    }

    /// Logical encoded bytes retained for this derived FST.
    #[must_use]
    pub(crate) fn logical_bytes(&self) -> u64 {
        self.logical_bytes
    }

    /// Build an FST but override the reported encoded size (test-only injection
    /// for the reservation-overshoot failure path).
    #[cfg(test)]
    pub(crate) fn build_with_logical_bytes(
        entries: &[DictionaryEntry],
        logical_bytes: u64,
    ) -> SearchResult<Self> {
        let mut fst = Self::build(entries)?;
        fst.logical_bytes = logical_bytes;
        Ok(fst)
    }

    /// Whether the built FST's encoded size fits the preflight reservation.
    #[must_use]
    pub(crate) fn reservation_fits(&self, reservation: u64) -> bool {
        self.logical_bytes <= reservation
    }

    /// Stream matching dictionary terms (ascending) to `on_term` without ever
    /// materializing an owned match vector. Returns the matcher's consumed work
    /// units for the caller to charge. Cancellation is polled by the matcher and
    /// every 256 emitted terms.
    pub(crate) fn visit_matches<F>(
        &self,
        predicate: &TermPredicate,
        cancellation: &dyn Cancellation,
        work_allowance: u64,
        mut on_term: F,
    ) -> SearchResult<u64>
    where
        F: FnMut(&str) -> SearchResult<()>,
    {
        let Some(set) = &self.set else {
            if cancellation.is_cancelled() {
                return Err(SearchError::Cancelled);
            }
            return Ok(0);
        };
        let matcher = FstMatcher::new(predicate, cancellation, work_allowance);
        let mut stream = set.search(&matcher).into_stream();
        let mut emitted: u64 = 0;
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
            let term = std::str::from_utf8(key).map_err(|_| SearchError::CorruptIndex {
                detail: "dictionary term is not valid UTF-8".to_owned(),
            })?;
            on_term(term)?;
            emitted = emitted.checked_add(1).ok_or(SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
            if emitted % 256 == 0 && cancellation.is_cancelled() {
                return Err(SearchError::Cancelled);
            }
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
        if cancellation.is_cancelled() {
            return Err(SearchError::Cancelled);
        }
        Ok(matcher.work.get())
    }

    /// Test-only convenience that collects matches into an owned vector.
    #[cfg(test)]
    pub(crate) fn matches(
        &self,
        predicate: &TermPredicate,
        cancellation: &dyn Cancellation,
        work_allowance: u64,
        max_terms: u64,
    ) -> SearchResult<(Vec<String>, u64)> {
        let mut terms: Vec<String> = Vec::new();
        let units = self.visit_matches(predicate, cancellation, work_allowance, |term| {
            if terms.len() as u64 >= max_terms {
                return Err(SearchError::ResourceLimit {
                    limit: max_terms,
                    requested: terms.len() as u64 + 1,
                });
            }
            terms.push(term.to_owned());
            Ok(())
        })?;
        Ok((terms, units))
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
    use crate::analysis::{
        AnalysisLimits, AnalyzerDefinition, CancellationFlag, NeverCancel, prepare_prefix,
    };

    /// A cancellation source that trips after a fixed number of polls.
    struct CancelAfter {
        remaining: std::cell::Cell<u32>,
    }

    impl CancelAfter {
        fn new(remaining: u32) -> Self {
            Self {
                remaining: std::cell::Cell::new(remaining),
            }
        }
    }

    impl Cancellation for CancelAfter {
        fn is_cancelled(&self) -> bool {
            let left = self.remaining.get();
            if left == 0 {
                true
            } else {
                self.remaining.set(left - 1);
                false
            }
        }
    }

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
    fn estimate_build_work_sums_insert_and_bytes() {
        let entries = entries(&["abc", "de"]);
        // (1 + 3) + (1 + 2) = 7.
        assert_eq!(TermFst::estimate_build_work(&entries).unwrap(), 7);
        assert_eq!(TermFst::estimate_build_work(&[]).unwrap(), 0);
    }

    #[test]
    fn preflight_charges_work_and_reserves_conservatively() {
        let entries = entries(&["abc", "de"]);
        let mut work = SearchWork::new(1_000, &NeverCancel);
        let reservation =
            TermFst::preflight_build(&entries, 0, u64::MAX, &mut work, &NeverCancel).unwrap();
        // FST_BASE_RESERVATION + sum(term.len() + 16) = 64 + (3 + 16) + (2 + 16) = 101.
        assert_eq!(reservation, 64 + 37);
        assert_eq!(work.remaining(), 1_000 - 7);
    }

    #[test]
    fn build_invocations_are_thread_local() {
        reset_build_invocations();
        TermFst::build(&entries(&["parent"])).unwrap();
        assert_eq!(
            build_invocations(),
            1,
            "the parent thread must observe exactly its own build"
        );

        let child = std::thread::spawn(|| {
            reset_build_invocations();
            assert_eq!(build_invocations(), 0, "a fresh thread starts at zero");
            TermFst::build(&entries(&["child"])).unwrap();
            build_invocations()
        });
        let child_count = child.join().expect("child thread panicked");
        assert_eq!(
            child_count, 1,
            "the child thread must observe exactly its own build"
        );

        assert_eq!(
            build_invocations(),
            1,
            "a concurrent thread's build must not be visible on the parent thread"
        );
        reset_build_invocations();
        assert_eq!(build_invocations(), 0);
    }

    #[test]
    fn preflight_work_limit_prevents_build() {
        reset_build_invocations();
        let entries = entries(&["aaaa", "bbbb"]);
        let expected = TermFst::estimate_build_work(&entries).unwrap();
        let mut work = SearchWork::new(expected - 1, &NeverCancel);
        assert!(matches!(
            TermFst::preflight_build(&entries, 0, u64::MAX, &mut work, &NeverCancel),
            Err(SearchError::ResourceLimit { .. })
        ));
        // The build must never start when the preflight work budget is exceeded.
        assert_eq!(build_invocations(), 0);
    }

    #[test]
    fn preflight_fst_budget_one_over_prevents_build() {
        reset_build_invocations();
        let entries = entries(&["abc"]);
        let reservation = 64 + 3 + 16;
        let mut work = SearchWork::new(1_000, &NeverCancel);
        assert!(matches!(
            TermFst::preflight_build(&entries, 0, reservation - 1, &mut work, &NeverCancel),
            Err(SearchError::ResourceLimit { .. })
        ));
        assert_eq!(build_invocations(), 0);
        // Exactly at the budget is accepted.
        let mut work = SearchWork::new(1_000, &NeverCancel);
        assert_eq!(
            TermFst::preflight_build(&entries, 0, reservation, &mut work, &NeverCancel).unwrap(),
            reservation
        );
    }

    #[test]
    fn preflight_is_cumulative_across_fields() {
        let first = entries(&["abc"]);
        let second = entries(&["defg", "h"]);
        let mut work = SearchWork::new(1_000, &NeverCancel);
        let a = TermFst::preflight_build(&first, 0, 1_000, &mut work, &NeverCancel).unwrap();
        let b = TermFst::preflight_build(&second, a, 1_000, &mut work, &NeverCancel).unwrap();
        assert_eq!(a, 64 + 3 + 16);
        assert_eq!(b, 64 + (4 + 16) + (1 + 16));
        // The cumulative total is the relevant budget.
        assert!(matches!(
            TermFst::preflight_build(&second, a, a + b - 1, &mut work, &NeverCancel),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn preflight_empty_dictionary_checks_cancellation() {
        let mut work = SearchWork::new(1_000, &NeverCancel);
        assert_eq!(
            TermFst::preflight_build(&[], 0, u64::MAX, &mut work, &NeverCancel).unwrap(),
            64,
            "empty dictionaries reserve only the fixed FST header"
        );
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        let mut work = SearchWork::new(1_000, &cancelled);
        assert!(matches!(
            TermFst::preflight_build(&[], 0, u64::MAX, &mut work, &cancelled),
            Err(SearchError::Cancelled)
        ));
    }

    #[test]
    fn preflight_cancellation_during_walk() {
        let entries: Vec<DictionaryEntry> = (0..2_000)
            .map(|index| DictionaryEntry {
                term: format!("term{index:05}"),
                doc_freq: 1,
                postings_offset: index as u64,
                postings_length: 1,
            })
            .collect();
        let cancel = CancelAfter::new(2);
        let mut work = SearchWork::new(1_000_000, &cancel);
        assert!(matches!(
            TermFst::preflight_build(&entries, 0, u64::MAX, &mut work, &cancel),
            Err(SearchError::Cancelled)
        ));
    }

    #[test]
    fn preflight_overflow_is_typed() {
        let entries = entries(&["abc"]);
        let mut work = SearchWork::new(1_000, &NeverCancel);
        assert!(matches!(
            TermFst::preflight_build(&entries, u64::MAX, u64::MAX, &mut work, &NeverCancel),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn empty_fst_matches_nothing() {
        let prepared =
            prepare_prefix(&analyzer(), "r", &AnalysisLimits::default(), &NeverCancel).unwrap();
        let predicate = TermPredicate::prefix(&prepared);
        let (terms, work) = TermFst::empty()
            .matches(&predicate, &NeverCancel, 1_000, 100)
            .unwrap();
        assert!(terms.is_empty());
        assert_eq!(work, 0);
    }

    #[test]
    fn reservation_rejects_encoded_oversize() {
        let entries = entries(&["abc"]);
        let reservation = 64 + 3 + 16;
        let fst = TermFst::build(&entries).unwrap();
        assert!(fst.reservation_fits(reservation));
        let inflated = TermFst::build_with_logical_bytes(&entries, reservation + 1).unwrap();
        assert!(!inflated.reservation_fits(reservation));
    }
}
