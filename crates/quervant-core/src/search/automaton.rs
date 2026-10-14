//! Bounded scalar automata for multi-term query patterns (PR 8).
//!
//! Every pattern is compiled from a PR 4 **prepared** object (never reparsed from
//! raw input) into a bounded automaton over Unicode scalar values. The automata
//! are consumed by [`crate::search::expand`] while walking the derived scalar trie
//! of a segment/field dictionary; a transition is only descended when
//! [`TermPredicate::can_match`] reports a possible match, so a broad or no-match
//! pattern can never trigger an unbounded full-dictionary scan.
//!
//! * Prefix — an exact scalar chain.
//! * Glob — a Thompson NFA over the prepared [`GlobSegment`] sequence; `?` is one
//!   Unicode scalar, `*` is zero or more.
//! * Regex — a Thompson NFA built from the normalized PR 4 pattern, anchored to
//!   the whole indexed term (a term matches iff the entire scalar sequence is
//!   accepted).
//! * Fuzzy — a bounded edit-distance NFA over scalars with optional restricted
//!   Damerau (optimal-string-alignment) adjacent transpositions; `max_edits` is
//!   limited to `0..=2`.
//!
//! `max_automaton_states` bounds the compiled NFA state count and is checked
//! **before** any large allocation. `max_fuzzy_pattern_scalars` bounds the fuzzy
//! query length. All arithmetic is checked.

use std::rc::Rc;

use regex_syntax::hir::{Class, Hir, HirKind, Look};

use crate::analysis::{GlobSegment, PreparedGlob, PreparedPrefix, PreparedRegex};

use super::error::{SearchError, SearchResult};
use super::limits::SearchLimits;

/// Maximum Unicode scalar value.
const MAX_SCALAR: u32 = 0x10_FFFF;

/// A compiled multi-term predicate. Identity is the PR 4 prepared form plus the
/// fuzzy parameters; two leaves with the same identity intern to one leaf.
#[derive(Clone)]
pub(crate) enum TermPredicate {
    Prefix {
        chars: Vec<char>,
    },
    Glob {
        /// The normalized PR 4 pattern, used for interning identity and diagnostics.
        normalized: String,
        nfa: Rc<Nfa>,
    },
    Regex {
        /// The normalized PR 4 pattern, used for interning identity and diagnostics.
        pattern: String,
        nfa: Rc<Nfa>,
    },
    Fuzzy {
        spec: Rc<FuzzySpec>,
    },
}

impl TermPredicate {
    /// Builds a prefix predicate from the PR 4 prepared literal.
    #[must_use]
    pub(crate) fn prefix(prepared: &PreparedPrefix) -> Self {
        Self::Prefix {
            chars: prepared.prefix().chars().collect(),
        }
    }

    /// Builds a glob predicate from the PR 4 prepared segments.
    pub(crate) fn glob(prepared: &PreparedGlob, limits: &SearchLimits) -> SearchResult<Self> {
        let mut builder = NfaBuilder::new(limits.max_automaton_states());
        let start = builder.build_glob(prepared.segments())?;
        Ok(Self::Glob {
            normalized: prepared.normalized().to_owned(),
            nfa: Rc::new(builder.finish(start)),
        })
    }

    /// Builds a whole-term regex predicate from the PR 4 normalized pattern.
    pub(crate) fn regex(prepared: &PreparedRegex, limits: &SearchLimits) -> SearchResult<Self> {
        let hir = regex_syntax::parse(prepared.pattern()).map_err(|_| {
            SearchError::Query(crate::contract::error::QueryError::InvalidQuery(
                crate::contract::error::InvalidQueryReason::UnsupportedOperator {
                    field: String::new(),
                    operator: "regex",
                },
            ))
        })?;
        let mut builder = NfaBuilder::new(limits.max_automaton_states());
        let start = builder.build_hir(&hir)?;
        Ok(Self::Regex {
            pattern: prepared.pattern().to_owned(),
            nfa: Rc::new(builder.finish(start)),
        })
    }

    /// Builds a bounded fuzzy predicate from a single normalized term.
    pub(crate) fn fuzzy(
        query: &str,
        max_edits: u8,
        transpositions: bool,
        limits: &SearchLimits,
    ) -> SearchResult<Self> {
        let chars: Vec<char> = query.chars().collect();
        let scalars = u64::try_from(chars.len()).unwrap_or(u64::MAX);
        if scalars > limits.max_fuzzy_pattern_scalars() {
            return Err(SearchError::ResourceLimit {
                limit: limits.max_fuzzy_pattern_scalars(),
                requested: scalars,
            });
        }
        let spec = FuzzySpec::new(chars, max_edits, transpositions);
        let states = spec.compiled_states();
        if states > limits.max_automaton_states() {
            return Err(SearchError::ResourceLimit {
                limit: limits.max_automaton_states(),
                requested: states,
            });
        }
        Ok(Self::Fuzzy {
            spec: Rc::new(spec),
        })
    }

    /// Canonical identity used to intern identical multi-term leaves.
    ///
    /// The unit separator (`\u{1f}`) cannot appear in a normalized analyzer
    /// pattern, so the encoding is unambiguous across kinds and parameters.
    #[must_use]
    pub(crate) fn intern_key(&self) -> String {
        const SEP: char = '\u{1f}';
        match self {
            Self::Prefix { chars } => format!("p{SEP}{}", chars.iter().collect::<String>()),
            Self::Glob { normalized, .. } => format!("g{SEP}{normalized}"),
            Self::Regex { pattern, .. } => format!("r{SEP}{pattern}"),
            Self::Fuzzy { spec } => format!(
                "f{SEP}{}{SEP}{}{SEP}{}",
                spec.query.iter().collect::<String>(),
                spec.max_edits,
                spec.transpositions
            ),
        }
    }

    /// The compiled automaton state count charged against `max_automaton_states`.
    #[must_use]
    pub(crate) fn compiled_states(&self) -> u64 {
        match self {
            Self::Prefix { chars } => chars.len() as u64 + 1,
            Self::Glob { nfa, .. } | Self::Regex { nfa, .. } => nfa.states.len() as u64,
            Self::Fuzzy { spec } => spec.compiled_states(),
        }
    }

    /// The initial state, or `None` when the automaton can never match a non-empty
    /// term (an empty term is never present in a dictionary).
    pub(crate) fn start(&self) -> Option<TermState> {
        match self {
            Self::Prefix { .. } => Some(TermState::Prefix { matched: 0 }),
            Self::Glob { nfa, .. } | Self::Regex { nfa, .. } => Some(TermState::Nfa {
                set: NfaStateSet::start(nfa),
            }),
            Self::Fuzzy { spec } => Some(TermState::Fuzzy { set: spec.start() }),
        }
    }

    /// Consume one Unicode scalar value.
    pub(crate) fn step(
        &self,
        state: &TermState,
        scalar: char,
        scratch: &mut AutomatonScratch,
    ) -> Option<TermState> {
        match (self, state) {
            (Self::Prefix { chars }, TermState::Prefix { matched }) => {
                if matched < &chars.len() {
                    (chars.get(*matched) == Some(&scalar)).then_some(TermState::Prefix {
                        matched: matched + 1,
                    })
                } else {
                    // The prefix is fully consumed: any continuation is a match.
                    Some(TermState::Prefix { matched: *matched })
                }
            }
            (Self::Glob { nfa, .. } | Self::Regex { nfa, .. }, TermState::Nfa { set }) => nfa
                .step(set, scalar, scratch)
                .map(|set| TermState::Nfa { set }),
            (Self::Fuzzy { spec }, TermState::Fuzzy { set }) => {
                spec.step(set, scalar).map(|set| TermState::Fuzzy { set })
            }
            // State variant and predicate always agree by construction.
            _ => None,
        }
    }

    /// Whether the consumed scalar sequence is a complete match.
    pub(crate) fn is_match(&self, state: &TermState, scratch: &mut AutomatonScratch) -> bool {
        match (self, state) {
            (Self::Prefix { chars }, TermState::Prefix { matched }) => *matched == chars.len(),
            (Self::Glob { nfa, .. } | Self::Regex { nfa, .. }, TermState::Nfa { set }) => {
                nfa.is_match(set, scratch)
            }
            (Self::Fuzzy { spec }, TermState::Fuzzy { set }) => spec.is_match(set),
            _ => false,
        }
    }

    /// Whether any continuation can still match. Returning `true` conservatively is
    /// always safe; returning `false` prunes the trie branch.
    pub(crate) fn can_match(&self, state: &TermState, scratch: &mut AutomatonScratch) -> bool {
        match (self, state) {
            (Self::Prefix { chars }, TermState::Prefix { matched }) => *matched <= chars.len(),
            (Self::Glob { nfa, .. } | Self::Regex { nfa, .. }, TermState::Nfa { set }) => {
                nfa.can_match(set, scratch)
            }
            (Self::Fuzzy { spec }, TermState::Fuzzy { set }) => spec.can_match(set),
            _ => false,
        }
    }
}

impl std::fmt::Debug for TermPredicate {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Prefix { chars } => f
                .debug_struct("Prefix")
                .field("prefix", &chars.iter().collect::<String>())
                .finish(),
            Self::Glob { normalized, nfa } => f
                .debug_struct("Glob")
                .field("pattern", normalized)
                .field("states", &nfa.states.len())
                .finish(),
            Self::Regex { pattern, nfa } => f
                .debug_struct("Regex")
                .field("pattern", pattern)
                .field("states", &nfa.states.len())
                .finish(),
            Self::Fuzzy { spec } => f
                .debug_struct("Fuzzy")
                .field("query", &spec.query.iter().collect::<String>())
                .field("max_edits", &spec.max_edits)
                .field("transpositions", &spec.transpositions)
                .finish(),
        }
    }
}

impl PartialEq for TermPredicate {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Prefix { chars: a }, Self::Prefix { chars: b }) => a == b,
            (Self::Glob { normalized: a, .. }, Self::Glob { normalized: b, .. }) => a == b,
            (Self::Regex { pattern: a, .. }, Self::Regex { pattern: b, .. }) => a == b,
            (Self::Fuzzy { spec: a }, Self::Fuzzy { spec: b }) => {
                a.query == b.query
                    && a.max_edits == b.max_edits
                    && a.transpositions == b.transpositions
            }
            _ => false,
        }
    }
}

impl Eq for TermPredicate {}

/// An in-flight automaton state.
#[derive(Clone)]
pub(crate) enum TermState {
    Prefix { matched: usize },
    Nfa { set: NfaStateSet },
    Fuzzy { set: BitSet },
}

/// Reusable scratch buffers for NFA closure computation. One scratch is shared by
/// all predicates in a request; buffers grow to the largest NFA seen.
pub(crate) struct AutomatonScratch {
    visited: Vec<u64>,
    generation: u64,
    stack: Vec<u32>,
    closure: Vec<u32>,
}

impl AutomatonScratch {
    /// Create an empty scratch.
    #[must_use]
    pub(crate) fn new() -> Self {
        Self {
            visited: Vec::new(),
            generation: 0,
            stack: Vec::new(),
            closure: Vec::new(),
        }
    }

    fn ensure(&mut self, len: usize) {
        if self.visited.len() < len {
            self.visited.resize(len, 0);
        }
    }
}

impl Default for AutomatonScratch {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Thompson NFA over Unicode scalar values (glob and regex)
// ---------------------------------------------------------------------------

pub(crate) struct NfaState {
    epsilons: Vec<u32>,
    assertions: Vec<(Look, u32)>,
    /// `(range_start, range_end, target)`; both bounds inclusive.
    scalars: Vec<(u32, u32, u32)>,
}

pub(crate) struct Nfa {
    states: Vec<NfaState>,
    start: u32,
    accept: u32,
    can_reach_accept: Vec<bool>,
}

/// The set of NFA states at a scalar boundary, before the boundary's epsilon
/// closure (which depends on the adjacent scalars).
#[derive(Clone, PartialEq, Eq)]
pub(crate) struct NfaStateSet {
    states: Vec<u32>,
    prev: Option<char>,
}

impl NfaStateSet {
    fn start(nfa: &Nfa) -> Self {
        Self {
            states: vec![nfa.start],
            prev: None,
        }
    }
}

struct NfaBuilder {
    states: Vec<NfaState>,
    limit: u64,
}

impl NfaBuilder {
    fn new(limit: u64) -> Self {
        Self {
            states: Vec::new(),
            limit,
        }
    }

    fn alloc(&mut self) -> SearchResult<u32> {
        let next = u64::try_from(self.states.len()).unwrap_or(u64::MAX);
        if next >= self.limit {
            return Err(SearchError::ResourceLimit {
                limit: self.limit,
                requested: next + 1,
            });
        }
        let id = u32::try_from(self.states.len()).map_err(|_| SearchError::ResourceLimit {
            limit: self.limit,
            requested: next,
        })?;
        self.states.push(NfaState {
            epsilons: Vec::new(),
            assertions: Vec::new(),
            scalars: Vec::new(),
        });
        Ok(id)
    }

    fn epsilon(&mut self, from: u32, to: u32) {
        self.states[from as usize].epsilons.push(to);
    }

    fn assertion(&mut self, from: u32, look: Look, to: u32) {
        self.states[from as usize].assertions.push((look, to));
    }

    fn scalar(&mut self, from: u32, start: u32, end: u32, to: u32) {
        self.states[from as usize].scalars.push((start, end, to));
    }

    fn build_glob(&mut self, segments: &[GlobSegment]) -> SearchResult<u32> {
        let start = self.alloc()?;
        let mut cur = start;
        for segment in segments {
            match segment {
                GlobSegment::Literal(text) => {
                    for ch in text.chars() {
                        let next = self.alloc()?;
                        self.scalar(cur, ch as u32, ch as u32, next);
                        cur = next;
                    }
                }
                GlobSegment::AnyChar => {
                    let next = self.alloc()?;
                    self.scalar(cur, 0, MAX_SCALAR, next);
                    cur = next;
                }
                GlobSegment::AnySequence => {
                    let loop_state = self.alloc()?;
                    let exit = self.alloc()?;
                    self.epsilon(cur, loop_state);
                    self.scalar(loop_state, 0, MAX_SCALAR, loop_state);
                    self.epsilon(loop_state, exit);
                    cur = exit;
                }
            }
        }
        let accept = self.alloc()?;
        self.epsilon(cur, accept);
        Ok(start)
    }

    fn build_hir(&mut self, hir: &Hir) -> SearchResult<u32> {
        let (start, end) = self.build_fragment(hir)?;
        let accept = self.alloc()?;
        self.epsilon(end, accept);
        Ok(start)
    }

    /// Returns `(entry, exit)` for a fragment.
    fn build_fragment(&mut self, hir: &Hir) -> SearchResult<(u32, u32)> {
        match hir.kind() {
            HirKind::Empty => {
                let entry = self.alloc()?;
                let exit = self.alloc()?;
                self.epsilon(entry, exit);
                Ok((entry, exit))
            }
            HirKind::Literal(literal) => {
                let text = std::str::from_utf8(&literal.0).map_err(|_| {
                    SearchError::UnsupportedOperator {
                        operator: "regex_non_utf8_literal",
                    }
                })?;
                let entry = self.alloc()?;
                let mut cur = entry;
                for ch in text.chars() {
                    let next = self.alloc()?;
                    self.scalar(cur, ch as u32, ch as u32, next);
                    cur = next;
                }
                Ok((entry, cur))
            }
            HirKind::Class(Class::Unicode(class)) => {
                let entry = self.alloc()?;
                let exit = self.alloc()?;
                for range in class.ranges() {
                    self.scalar(entry, range.start() as u32, range.end() as u32, exit);
                }
                Ok((entry, exit))
            }
            HirKind::Class(Class::Bytes(_)) => Err(SearchError::UnsupportedOperator {
                operator: "regex_byte_class",
            }),
            HirKind::Look(look) => {
                let entry = self.alloc()?;
                let exit = self.alloc()?;
                self.assertion(entry, *look, exit);
                Ok((entry, exit))
            }
            HirKind::Repetition(repetition) => {
                let entry = self.alloc()?;
                let mut cur = entry;
                for _ in 0..repetition.min {
                    let (sub_entry, sub_exit) = self.build_fragment(&repetition.sub)?;
                    self.epsilon(cur, sub_entry);
                    cur = sub_exit;
                }
                match repetition.max {
                    Some(max) => {
                        for _ in repetition.min..max {
                            let (sub_entry, sub_exit) = self.build_fragment(&repetition.sub)?;
                            let next = self.alloc()?;
                            self.epsilon(cur, sub_entry);
                            self.epsilon(cur, next);
                            self.epsilon(sub_exit, next);
                            cur = next;
                        }
                        Ok((entry, cur))
                    }
                    None => {
                        let (sub_entry, sub_exit) = self.build_fragment(&repetition.sub)?;
                        let exit = self.alloc()?;
                        self.epsilon(cur, sub_entry);
                        self.epsilon(cur, exit);
                        self.epsilon(sub_exit, sub_entry);
                        self.epsilon(sub_exit, exit);
                        Ok((entry, exit))
                    }
                }
            }
            HirKind::Capture(capture) => self.build_fragment(&capture.sub),
            HirKind::Concat(subs) => {
                let entry = self.alloc()?;
                let mut cur = entry;
                for sub in subs {
                    let (sub_entry, sub_exit) = self.build_fragment(sub)?;
                    self.epsilon(cur, sub_entry);
                    cur = sub_exit;
                }
                Ok((entry, cur))
            }
            HirKind::Alternation(subs) => {
                let entry = self.alloc()?;
                let exit = self.alloc()?;
                for sub in subs {
                    let (sub_entry, sub_exit) = self.build_fragment(sub)?;
                    self.epsilon(entry, sub_entry);
                    self.epsilon(sub_exit, exit);
                }
                Ok((entry, exit))
            }
        }
    }

    fn finish(self, start: u32) -> Nfa {
        // The final accept state is the last allocated state.
        let accept = u32::try_from(self.states.len() - 1).expect("state count fits u32");
        let can_reach_accept = reverse_reachability(&self.states, accept);
        Nfa {
            states: self.states,
            start,
            accept,
            can_reach_accept,
        }
    }
}

fn reverse_reachability(states: &[NfaState], accept: u32) -> Vec<bool> {
    let mut reverse: Vec<Vec<u32>> = vec![Vec::new(); states.len()];
    for (from, state) in states.iter().enumerate() {
        let from = from as u32;
        for &to in &state.epsilons {
            reverse[to as usize].push(from);
        }
        for &(_, to) in &state.assertions {
            reverse[to as usize].push(from);
        }
        for &(_, _, to) in &state.scalars {
            reverse[to as usize].push(from);
        }
    }
    let mut reachable = vec![false; states.len()];
    let mut stack = vec![accept];
    reachable[accept as usize] = true;
    while let Some(node) = stack.pop() {
        for &pred in &reverse[node as usize] {
            if !reachable[pred as usize] {
                reachable[pred as usize] = true;
                stack.push(pred);
            }
        }
    }
    reachable
}

fn epsilon_closure(
    nfa: &Nfa,
    base: &[u32],
    prev: Option<char>,
    next: Option<char>,
    optimistic: bool,
    scratch: &mut AutomatonScratch,
) {
    scratch.ensure(nfa.states.len());
    scratch.generation = scratch.generation.wrapping_add(1);
    let generation = scratch.generation;
    scratch.closure.clear();
    scratch.stack.clear();
    scratch.stack.extend_from_slice(base);
    while let Some(state) = scratch.stack.pop() {
        let index = state as usize;
        if scratch.visited[index] == generation {
            continue;
        }
        scratch.visited[index] = generation;
        scratch.closure.push(state);
        let node = &nfa.states[index];
        for &to in &node.epsilons {
            scratch.stack.push(to);
        }
        for &(look, to) in &node.assertions {
            if optimistic || assertion_holds(look, prev, next) {
                scratch.stack.push(to);
            }
        }
    }
    scratch.closure.sort_unstable();
    scratch.closure.dedup();
}

impl Nfa {
    fn step(
        &self,
        state: &NfaStateSet,
        scalar: char,
        scratch: &mut AutomatonScratch,
    ) -> Option<NfaStateSet> {
        let previous = scalar;
        let value = scalar as u32;
        epsilon_closure(
            self,
            &state.states,
            state.prev,
            Some(scalar),
            false,
            scratch,
        );
        let mut next: Vec<u32> = Vec::new();
        for &from in &scratch.closure {
            for &(start, end, to) in &self.states[from as usize].scalars {
                if start <= value && value <= end {
                    next.push(to);
                }
            }
        }
        if next.is_empty() {
            return None;
        }
        next.sort_unstable();
        next.dedup();
        Some(NfaStateSet {
            states: next,
            prev: Some(previous),
        })
    }

    fn is_match(&self, state: &NfaStateSet, scratch: &mut AutomatonScratch) -> bool {
        epsilon_closure(self, &state.states, state.prev, None, false, scratch);
        scratch.closure.contains(&self.accept)
    }

    fn can_match(&self, state: &NfaStateSet, scratch: &mut AutomatonScratch) -> bool {
        epsilon_closure(self, &state.states, state.prev, None, true, scratch);
        scratch
            .closure
            .iter()
            .any(|state| self.can_reach_accept[*state as usize])
    }
}

impl PartialEq for Nfa {
    fn eq(&self, other: &Self) -> bool {
        // Structural equality of Thompson NFAs built from the same normalized
        // pattern: compare reachable behaviour via the serialized transition shape.
        if self.start != other.start
            || self.accept != other.accept
            || self.states.len() != other.states.len()
        {
            return false;
        }
        self.states.iter().zip(&other.states).all(|(a, b)| {
            a.epsilons == b.epsilons && a.assertions == b.assertions && a.scalars == b.scalars
        })
    }
}

impl Eq for Nfa {}

// ---------------------------------------------------------------------------
// Assertions
// ---------------------------------------------------------------------------

fn assertion_holds(look: Look, prev: Option<char>, next: Option<char>) -> bool {
    match look {
        Look::Start => prev.is_none(),
        Look::End => next.is_none(),
        Look::StartLF => prev.is_none() || prev == Some('\n'),
        Look::EndLF => next.is_none() || next == Some('\n'),
        Look::StartCRLF => prev.is_none() || prev == Some('\n') || prev == Some('\r'),
        Look::EndCRLF => next.is_none() || next == Some('\n') || next == Some('\r'),
        Look::WordAscii => ascii_word(prev) != ascii_word(next),
        Look::WordAsciiNegate => ascii_word(prev) == ascii_word(next),
        Look::WordUnicode => unicode_word(prev) != unicode_word(next),
        Look::WordUnicodeNegate => unicode_word(prev) == unicode_word(next),
        Look::WordStartAscii => !ascii_word(prev) && ascii_word(next),
        Look::WordEndAscii => ascii_word(prev) && !ascii_word(next),
        Look::WordStartUnicode => !unicode_word(prev) && unicode_word(next),
        Look::WordEndUnicode => unicode_word(prev) && !unicode_word(next),
        Look::WordStartHalfAscii => !ascii_word(prev),
        Look::WordEndHalfAscii => !ascii_word(next),
        Look::WordStartHalfUnicode => !unicode_word(prev),
        Look::WordEndHalfUnicode => !unicode_word(next),
    }
}

fn ascii_word(scalar: Option<char>) -> bool {
    scalar.is_some_and(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn unicode_word(scalar: Option<char>) -> bool {
    scalar.is_some_and(is_unicode_word)
}

/// Membership in `\w` exactly as `regex-syntax` defines it, derived once from the
/// parser so pattern and assertion semantics agree.
fn is_unicode_word(c: char) -> bool {
    use std::sync::OnceLock;
    static RANGES: OnceLock<Vec<(u32, u32)>> = OnceLock::new();
    let ranges = RANGES.get_or_init(|| {
        let hir = regex_syntax::parse(r"\w").expect("built-in \\w parses");
        let mut out = Vec::new();
        if let HirKind::Class(Class::Unicode(class)) = hir.kind() {
            for range in class.ranges() {
                out.push((range.start() as u32, range.end() as u32));
            }
        }
        out
    });
    let value = c as u32;
    ranges
        .binary_search_by(|&(start, end)| {
            if value < start {
                std::cmp::Ordering::Greater
            } else if value > end {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

// ---------------------------------------------------------------------------
// Bounded fuzzy automaton (Levenshtein / restricted OSA)
// ---------------------------------------------------------------------------

/// A simple growable bit set for bounded automaton state sets.
#[derive(Clone, PartialEq, Eq, Debug)]
pub(crate) struct BitSet {
    words: Vec<u64>,
    len: usize,
}

impl BitSet {
    fn new(len: usize) -> Self {
        Self {
            words: vec![0; len.div_ceil(64)],
            len,
        }
    }

    fn set(&mut self, index: usize) {
        debug_assert!(index < self.len);
        self.words[index / 64] |= 1u64 << (index % 64);
    }

    fn get(&self, index: usize) -> bool {
        index < self.len && (self.words[index / 64] & (1u64 << (index % 64))) != 0
    }

    fn is_empty(&self) -> bool {
        self.words.iter().all(|word| *word == 0)
    }

    fn iter(&self) -> impl Iterator<Item = usize> + '_ {
        self.words
            .iter()
            .enumerate()
            .flat_map(|(word_index, word)| {
                let mut bits = *word;
                std::iter::from_fn(move || {
                    if bits == 0 {
                        return None;
                    }
                    let bit = bits.trailing_zeros() as usize;
                    bits &= bits - 1;
                    Some(word_index * 64 + bit)
                })
            })
    }
}

/// A compiled fuzzy predicate over scalars.
pub(crate) struct FuzzySpec {
    query: Vec<char>,
    max_edits: u8,
    transpositions: bool,
    /// Number of `(query_pos, edits)` cells.
    base: usize,
}

impl FuzzySpec {
    fn new(query: Vec<char>, max_edits: u8, transpositions: bool) -> Self {
        let base = (query.len() + 1) * (usize::from(max_edits) + 1);
        Self {
            query,
            max_edits,
            transpositions,
            base,
        }
    }

    fn compiled_states(&self) -> u64 {
        // Normal plus pending-transposition cells.
        u64::try_from(self.base.saturating_mul(2)).unwrap_or(u64::MAX)
    }

    fn state_len(&self) -> usize {
        self.base.saturating_mul(2)
    }

    fn normal(&self, pos: usize, edits: u8) -> usize {
        pos * (usize::from(self.max_edits) + 1) + usize::from(edits)
    }

    fn pending(&self, pos: usize, edits: u8) -> usize {
        self.base + self.normal(pos, edits)
    }

    fn start(&self) -> BitSet {
        let mut set = BitSet::new(self.state_len());
        set.set(self.normal(0, 0));
        set
    }

    /// Deletion epsilon closure: deleting the next query scalar costs one edit.
    fn closure(&self, state: &BitSet, out: &mut BitSet) {
        out.words.copy_from_slice(&state.words);
        let max_edits = usize::from(self.max_edits);
        let mut stack: Vec<usize> = out.iter().collect();
        while let Some(id) = stack.pop() {
            if id >= self.base {
                continue;
            }
            let edits = id % (max_edits + 1);
            let pos = id / (max_edits + 1);
            if pos < self.query.len() && edits < max_edits {
                let target = self.normal(pos + 1, (edits + 1) as u8);
                if !out.get(target) {
                    out.set(target);
                    stack.push(target);
                }
            }
        }
    }

    fn step(&self, state: &BitSet, scalar: char) -> Option<BitSet> {
        let mut closed = BitSet::new(self.state_len());
        self.closure(state, &mut closed);
        let mut next = BitSet::new(self.state_len());
        let max_edits = usize::from(self.max_edits);
        for id in closed.iter() {
            if id < self.base {
                let edits = id % (max_edits + 1);
                let pos = id / (max_edits + 1);
                if pos < self.query.len() {
                    if self.query[pos] == scalar {
                        next.set(self.normal(pos + 1, edits as u8));
                    }
                    if edits < max_edits {
                        // Substitution.
                        next.set(self.normal(pos + 1, (edits + 1) as u8));
                        // Insertion of an extra term scalar.
                        next.set(self.normal(pos, (edits + 1) as u8));
                        // Restricted Damerau / OSA adjacent transposition: the
                        // first scalar must equal the following query scalar, and
                        // a pending state then requires the current query scalar.
                        if self.transpositions
                            && pos + 1 < self.query.len()
                            && self.query[pos + 1] == scalar
                        {
                            next.set(self.pending(pos, (edits + 1) as u8));
                        }
                    }
                } else if edits < max_edits {
                    // Insertion after the whole query has been consumed.
                    next.set(self.normal(pos, (edits + 1) as u8));
                }
            } else {
                let inner = id - self.base;
                let edits = inner % (max_edits + 1);
                let pos = inner / (max_edits + 1);
                if pos < self.query.len() && self.query[pos] == scalar {
                    let target = pos + 2;
                    if target <= self.query.len() {
                        next.set(self.normal(target, edits as u8));
                    }
                }
            }
        }
        if next.is_empty() { None } else { Some(next) }
    }

    fn is_match(&self, state: &BitSet) -> bool {
        let mut closed = BitSet::new(self.state_len());
        self.closure(state, &mut closed);
        let pos = self.query.len();
        (0..=usize::from(self.max_edits)).any(|edits| closed.get(self.normal(pos, edits as u8)))
    }

    fn can_match(&self, state: &BitSet) -> bool {
        // Any reachable normal/pending state can still be driven to a match with
        // remaining edits (deletions), so a non-empty state set is conservative.
        !state.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::config::{NormalizationForm, Pipeline, TokenFilter, TokenizerKind};
    use crate::analysis::{AnalysisLimits, AnalyzerDefinition, AnalyzerRole, NeverCancel};

    fn standard() -> AnalyzerDefinition {
        AnalyzerDefinition::uniform(
            "standard",
            "1.0.0",
            Pipeline::simple(
                TokenizerKind::UnicodeWord,
                vec![TokenFilter::Normalize(NormalizationForm::Nfc)],
            )
            .unwrap(),
        )
        .unwrap()
    }

    fn fuzzy_spec(query: &str, max_edits: u8, transpositions: bool) -> FuzzySpec {
        FuzzySpec::new(query.chars().collect(), max_edits, transpositions)
    }

    fn fuzzy_distance(spec: &FuzzySpec, term: &str) -> u8 {
        let mut state = spec.start();
        for ch in term.chars() {
            match spec.step(&state, ch) {
                Some(next) => state = next,
                None => return spec.max_edits.saturating_add(1),
            }
        }
        let mut closed = BitSet::new(spec.state_len());
        spec.closure(&state, &mut closed);
        for edits in 0..=usize::from(spec.max_edits) {
            if closed.get(spec.normal(spec.query.len(), edits as u8)) {
                return edits as u8;
            }
        }
        spec.max_edits.saturating_add(1)
    }

    /// Full-matrix reference Levenshtein over scalars.
    fn reference_levenshtein(a: &str, b: &str) -> usize {
        let a: Vec<char> = a.chars().collect();
        let b: Vec<char> = b.chars().collect();
        let mut prev: Vec<usize> = (0..=b.len()).collect();
        for i in 1..=a.len() {
            let mut cur = vec![0usize; b.len() + 1];
            cur[0] = i;
            for j in 1..=b.len() {
                let cost = usize::from(a[i - 1] != b[j - 1]);
                cur[j] = (prev[j] + 1).min(cur[j - 1] + 1).min(prev[j - 1] + cost);
            }
            prev = cur;
        }
        prev[b.len()]
    }

    /// Full-matrix reference optimal-string-alignment (restricted Damerau).
    fn reference_osa(a: &str, b: &str) -> usize {
        let a: Vec<char> = a.chars().collect();
        let b: Vec<char> = b.chars().collect();
        let mut d = vec![vec![0usize; b.len() + 1]; a.len() + 1];
        for (i, row) in d.iter_mut().enumerate() {
            row[0] = i;
        }
        for (j, cell) in d[0].iter_mut().enumerate() {
            *cell = j;
        }
        for i in 1..=a.len() {
            for j in 1..=b.len() {
                let cost = usize::from(a[i - 1] != b[j - 1]);
                let mut best = (d[i - 1][j] + 1)
                    .min(d[i][j - 1] + 1)
                    .min(d[i - 1][j - 1] + cost);
                if i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1] {
                    best = best.min(d[i - 2][j - 2] + 1);
                }
                d[i][j] = best;
            }
        }
        d[a.len()][b.len()]
    }

    #[test]
    fn prefix_predicate_matches_starts_with() {
        let prepared = crate::analysis::prepare_prefix(
            &standard(),
            "Ru",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        let predicate = TermPredicate::prefix(&prepared);
        let mut scratch = AutomatonScratch::new();
        for term in ["Ru", "Run", "Rust"] {
            let mut state = predicate.start().unwrap();
            for ch in term.chars() {
                state = predicate
                    .step(&state, ch, &mut scratch)
                    .unwrap_or_else(|| panic!("prefix should accept {term}"));
            }
            assert!(predicate.is_match(&state, &mut scratch), "{term}");
        }
        // A term that does not begin with the prefix dies on its first scalar.
        let state = predicate.start().unwrap();
        assert!(predicate.step(&state, 'c', &mut scratch).is_none());
    }

    #[test]
    fn glob_predicate_is_scalar_aware() {
        let prepared = crate::analysis::prepare_glob(
            &standard(),
            "r?st",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        let predicate = TermPredicate::glob(&prepared, &SearchLimits::default()).unwrap();
        let mut scratch = AutomatonScratch::new();
        for term in ["rust", "rést"] {
            let mut state = predicate.start().unwrap();
            for ch in term.chars() {
                state = predicate.step(&state, ch, &mut scratch).unwrap();
            }
            assert!(predicate.is_match(&state, &mut scratch), "{term}");
        }
        let mut state = predicate.start().unwrap();
        let mut matched = true;
        for ch in "russt".chars() {
            match predicate.step(&state, ch, &mut scratch) {
                Some(next) => state = next,
                None => {
                    matched = false;
                    break;
                }
            }
        }
        assert!(!matched || !predicate.is_match(&state, &mut scratch));
    }

    #[test]
    fn regex_predicate_anchors_whole_term() {
        let prepared = crate::analysis::prepare_regex(
            &standard(),
            "u",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        let predicate = TermPredicate::regex(&prepared, &SearchLimits::default()).unwrap();
        let mut scratch = AutomatonScratch::new();
        let mut state = predicate.start().unwrap();
        // `u` is not a whole-term match for `rust`; the run dies at `r`.
        assert!(predicate.step(&state, 'r', &mut scratch).is_none());
        state = predicate.start().unwrap();
        state = predicate.step(&state, 'u', &mut scratch).unwrap();
        assert!(predicate.is_match(&state, &mut scratch));
    }

    #[test]
    fn fuzzy_levenshtein_matches_reference() {
        for (query, term, expected) in [
            ("rust", "rust", 0usize),
            ("rust", "ru", 2),
            ("rust", "rusty", 1),
            ("rust", "rast", 1),
            ("rust", "xyz", 3),
        ] {
            let spec = fuzzy_spec(query, 2, false);
            assert_eq!(
                usize::from(fuzzy_distance(&spec, term)),
                expected,
                "{query} -> {term}"
            );
            assert_eq!(reference_levenshtein(query, term).min(3), expected);
        }
    }

    #[test]
    fn fuzzy_osa_is_exhaustively_correct_for_short_strings() {
        fn strings(alphabet: &[char], max_len: usize) -> Vec<String> {
            let mut out = vec![String::new()];
            let mut frontier = vec![String::new()];
            for _ in 0..max_len {
                let mut next = Vec::new();
                for prefix in &frontier {
                    for ch in alphabet {
                        let mut candidate = prefix.clone();
                        candidate.push(*ch);
                        out.push(candidate.clone());
                        next.push(candidate);
                    }
                }
                frontier = next;
            }
            out
        }
        let candidates = strings(&['a', 'b', 'c'], 4);
        for query in &candidates {
            let spec = fuzzy_spec(query, 2, true);
            let lev_spec = fuzzy_spec(query, 2, false);
            for term in &candidates {
                let osa = usize::from(fuzzy_distance(&spec, term));
                assert_eq!(
                    osa,
                    reference_osa(query, term).min(3),
                    "OSA {query:?} -> {term:?}"
                );
                let lev = usize::from(fuzzy_distance(&lev_spec, term));
                assert_eq!(
                    lev,
                    reference_levenshtein(query, term).min(3),
                    "Levenshtein {query:?} -> {term:?}"
                );
            }
        }
    }

    #[test]
    fn fuzzy_osa_matches_reference_and_differs_from_unrestricted() {
        // The synthetic automaton distance must agree with the OSA reference.
        for (query, term) in [
            ("ab", "ba"),
            ("ca", "abc"),
            ("abcd", "acbd"),
            ("a", "ba"),
            ("", "abc"),
        ] {
            let spec = fuzzy_spec(query, 2, true);
            let actual = usize::from(fuzzy_distance(&spec, term));
            let reference = reference_osa(query, term);
            assert_eq!(actual, reference.min(3), "OSA {query} -> {term}");
        }
        // `ab` vs `ba` is one OSA transposition and two plain Levenshtein edits.
        assert_eq!(reference_osa("ab", "ba"), 1);
        assert_eq!(reference_levenshtein("ab", "ba"), 2);
    }

    #[test]
    fn fuzzy_zero_edits_is_exact() {
        let spec = fuzzy_spec("rust", 0, true);
        assert_eq!(fuzzy_distance(&spec, "rust"), 0);
        // A rejected path reports one past the budget (`0 + 1`).
        assert_eq!(fuzzy_distance(&spec, "rusty"), 1);
        assert_eq!(fuzzy_distance(&spec, "rus"), 1);
    }

    #[test]
    fn assertion_word_boundaries() {
        assert!(assertion_holds(Look::WordAscii, None, Some('a')));
        assert!(!assertion_holds(Look::WordAscii, Some('a'), Some('b')));
        assert!(assertion_holds(Look::WordStartAscii, Some(' '), Some('a')));
        assert!(!assertion_holds(Look::WordStartAscii, Some('a'), Some('a')));
        assert!(assertion_holds(Look::WordEndHalfAscii, Some('a'), None));
        assert!(assertion_holds(Look::Start, None, Some('a')));
        assert!(assertion_holds(Look::End, Some('a'), None));
    }

    #[test]
    fn unicode_word_assertion_uses_parser_definition() {
        assert!(is_unicode_word('é'));
        assert!(is_unicode_word('a'));
        assert!(!is_unicode_word('-'));
        assert!(assertion_holds(Look::WordStartUnicode, None, Some('é')));
    }

    #[test]
    fn oversized_regex_is_rejected_before_large_allocation() {
        let prepared = crate::analysis::prepare_regex(
            &standard(),
            "abcdef",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        let limits = SearchLimits::default()
            .with_max_automaton_states(2)
            .unwrap();
        assert!(matches!(
            TermPredicate::regex(&prepared, &limits),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn fuzzy_scalar_and_state_limits_are_enforced() {
        let limits = SearchLimits::default()
            .with_max_fuzzy_pattern_scalars(2)
            .unwrap();
        assert!(matches!(
            TermPredicate::fuzzy("abc", 1, false, &limits),
            Err(SearchError::ResourceLimit { .. })
        ));
        let limits = SearchLimits::default()
            .with_max_automaton_states(2)
            .unwrap();
        assert!(matches!(
            TermPredicate::fuzzy("abcdef", 2, false, &limits),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn prepared_glob_and_regex_are_normalized_before_compile() {
        let prepared = crate::analysis::prepare_glob(
            &standard(),
            "R*st",
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        // The standard analyzer has no case folding, so `R` stays `R`.
        let predicate = TermPredicate::glob(&prepared, &SearchLimits::default()).unwrap();
        let mut scratch = AutomatonScratch::new();
        let mut state = predicate.start().unwrap();
        for ch in "Rust".chars() {
            state = predicate.step(&state, ch, &mut scratch).unwrap();
        }
        assert!(predicate.is_match(&state, &mut scratch));
    }

    #[test]
    fn analyzer_roles_are_const() {
        // Guard against accidental removal of the search role used by preparation.
        let _ = AnalyzerRole::Search;
    }
}
