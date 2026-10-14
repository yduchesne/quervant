# PR 8 preflight — advanced lexical multi-term operators and safety budgets

**Branch:** `dev/advanced-lexical` (created from `main`)
**Base:** `main` @ `17305caa653751152972ea1677e1bdc93f8d30a6` (PR #24 / PR 7 merged)
**Remote main at start:** `origin/main` @ `17305caa653751152972ea1677e1bdc93f8d30a6` (identical; no divergence)
**Toolchain:** stable Rust 1.98.1 (CI `stable`); MSRV Rust 1.85.0 (`workspace rust-version = "1.85"`).

This document records the verified source seams and the pre-implementation
compatibility checks required by the PR 8 plan (Phase 0). Every item below was
inspected on the base commit before production code was written.

## Baseline validation on the base commit

Run from the workspace root on `17305caa653751152972ea1677e1bdc93f8d30a6`:

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 1063 passed, 0 failed, 7 ignored |

## Verified source APIs (reused, not rebuilt)

- `contract::query::Query` already has `Term`, `Phrase`, `Prefix { field, prefix }`,
  `Glob { field, pattern }`, `Regex { field, pattern }`, `And`/`Or`/`Not`; there is
  **no** `Fuzzy` variant. `Query::validate(&Schema, &Budgets)` runs before segment open.
- `analysis::prepare_term`, `prepare_prefix`, `prepare_glob`, `prepare_regex`
  return `PreparedTerm`/`PreparedPrefix`/`PreparedGlob`/`PreparedRegex`.
  `PreparedGlob::segments()` yields `GlobSegment::{Literal, AnySequence, AnyChar}`
  with exact Unicode-scalar semantics; `PreparedRegex::pattern()` is the normalized
  bounded-subset pattern (parser-only `regex-syntax` validation, case/Unicode
  normalization applied to literal runs, stopwords/stemming never applied).
- `analysis::registry::{AnalyzerRegistry, SchemaAnalyzerBindings}`; built-ins
  `keyword`, `keyword_noop` (identity), `standard`, `standard_folded`, `english`,
  `whitespace`, `domain`, `domain_icann`.
- `search::plan` compiles the tree before any segment is opened and currently
  rejects `Prefix`/`Glob`/`Regex` with `SearchError::UnsupportedOperator`.
- `search::execute` owns reader opening, per-leaf postings materialization,
  Boolean set algebra, snapshot-wide stats and deterministic top-K. `SearchWork`
  charges work and polls cancellation every `CANCELLATION_POLL_INTERVAL` (256)
  units. `CandidateBudget`/`SegmentCandidateLedger` bound segment/global candidates.
- `search::score::{compute_stats, bm25, QueryTerms}` computes snapshot-wide
  `n`/`df`/`dl`/`avgdl` from persisted norms with a legacy all-postings fallback;
  `FieldStats::doc_freq`/`length`.
- `segment::dictionary::{DictionaryEntry, DictionaryReader::field}` is a sorted
  UTF-8 term list; `SegmentReader::postings(field_id, term)` and
  `postings_for_entry(&DictionaryEntry)` are read-only.
- `index::{Index, IndexWriter, ReaderSnapshot, PitHandle}`; `MemoryDirectory`
  and `FsDirectory` are the local backends available to PR 8.

## Dependency evaluation (plan §2)

The plan permits a mature `fst` library **only if** it can perform bounded
automaton intersection with exact UTF-8 scalar semantics. Evaluated `fst 0.4.7`
(Unlicense/MIT, edition 2018, MSRV compatible): its built-in
`fst::automaton::Levenshtein` implements **plain Levenshtein only** (no
transpositions/OSA) and it ships no regex/glob automaton. Because PR 8 requires
**restricted OSA** (`transpositions = true`) and whole-term regex semantics, the
library's built-in automata cannot satisfy the contract. Per plan §2 the
alternative to an unbounded dictionary scan is a bounded, derived term index.

**Decision:** implement a runtime **derived scalar trie** (`search::term_fst`)
built from each segment/field dictionary, with explicit logical byte accounting
against `max_fst_bytes`, and a pruned scalar-automaton intersection
(`search::expand`). This is a deterministic finite-state term index equivalent in
pruning behaviour to an FST intersection; it never falls back to an unbounded
full-dictionary scan. No segment section, feature id or dictionary wire change is
introduced. `fst` is **not** added as a dependency. This decision is recorded in
the adversarial review and implementation report; it is a deviation from the
"prefer `fst`" suggestion that is justified by the exact-semantics failure of the
library's built-in automata, not an architecture change.

## Frozen public contracts preserved

- `SearchLimits::new` keeps its ten-argument signature; four new fields are added
  with defaults set inside `new` and checked `with_*` setters.
- `Query::Prefix`/`Glob`/`Regex` shapes and error policy are unchanged.
- No `segment/{format,build,reader,dictionary}.rs`, `index/*`, `storage/*` or
  `quervant-objectstore/*` wire/manifest change is required; PR 8 is read-only.
- `docs/ROADMAP_V01.md` PR 8 remains PLANNED until all gates and merge evidence exist.
