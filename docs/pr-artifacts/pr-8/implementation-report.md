# PR 8 implementation report — advanced lexical multi-term operators

**Branch:** `dev/advanced-lexical`
**Base:** `main` @ `17305caa653751152972ea1677e1bdc93f8d30a6` (PR 7 merged)
**Working tree:** all PR 8 changes committed to the branch (see `git log`).

## Summary

PR 8 adds bounded execution for `Query::Prefix`, `Query::Glob`, `Query::Regex`
and the new `Query::Fuzzy` over existing immutable PR 7 snapshots. The entire
query is validated and each pattern is normalized by the PR 4 preparation
functions **before any segment is opened**. For each open segment and target
field, a runtime-only derived term FST is built from the existing sorted UTF-8
dictionary and intersected with a bounded Unicode-scalar automaton. The resulting
ordered, deduplicated expanded terms feed the existing PR 7 postings/Boolean/BM25
and top-K execution. No segment section, feature id or dictionary wire encoding
changed.

## Files

| File | Change |
|---|---|
| `contract/query.rs` | New `Query::Fuzzy { field, value, max_edits, transpositions }`; `max_edits > 2` rejected in `validate` with `InvalidQueryReason::UnsupportedOperator`. |
| `search/limits.rs` | Four new checked fields/accessors/setters: `max_expanded_terms` (default 1,024 / ceiling 65,536), `max_automaton_states` (10,000 / 100,000), `max_fst_bytes` (32 MiB / 512 MiB), `max_fuzzy_pattern_scalars` (128 / 1,024). `SearchLimits::new` keeps its ten-argument signature and initializes the new fields to defaults. |
| `search/automaton.rs` (new) | `TermPredicate`/`TermState` over Unicode scalars: prefix (start-match), glob (Thompson NFA from `GlobSegment`), regex (Thompson NFA from the normalized PR 4 pattern, whole-term), fuzzy (bounded Levenshtein/restricted-OSA NFA). Assertion evaluation (`^`, `$`, ASCII/Unicode word boundaries), state budgets, `intern_key`. |
| `search/term_fst.rs` (new) | `TermFst` wraps an in-memory `fst::Set` built from the segment dictionary plus a `fst::Automaton` adapter that decodes UTF-8 bytes into scalar transitions, charges work, and polls cancellation every 256 transitions. Logical-byte accounting and pre-build estimate. |
| `search/expand.rs` (new) | Request-wide expansion: cache one `TermFst` per `(segment, field)`, intersect every multi-term leaf, build the positive scoring union, and enforce `max_expanded_terms`, `max_unique_query_terms` and `max_fst_bytes`. |
| `search/plan.rs` | `CompiledLeaf::MultiTerm`; compile `Prefix`/`Glob`/`Regex`/`Fuzzy` from PR 4 prepared objects; `LeafKey::MultiTerm` canonical interning; automaton-state accounting. |
| `search/execute.rs` | Expansion runs after reader open and before `compute_stats`; `compute_stats` receives the combined ordinary + expanded positive term union; multi-term leaves are evaluated as ORs of postings; `score_segment` deduplicates each `(field, term)` to a single BM25 contribution per document. |
| `search/mod.rs` | Module declarations. |
| Tests | `tests/pr08_{unit,properties,faults,integration,domain}.rs`, shared helpers in `tests/common/mod.rs`, exhaustive automaton tests in `automaton.rs`. |
| `examples/pr08_bench.rs` (new) | Diagnostic 2K/10K/100K vocabulary latency harness. |

## FST dependency decision

The plan suggested a mature `fst` library but required exact UTF-8 scalar
semantics. `fst 0.4.7` (Unlicense/MIT, edition 2018, MSRV-compatible) is used for
the compact derived term index and its pruned intersection engine. Its **built-in**
`fst::automaton::Levenshtein` implements plain Levenshtein only (no
transpositions/OSA) and it ships no regex automaton, so PR 8 supplies its own
`fst::Automaton` implementations in `search/term_fst.rs` / `search/automaton.rs`.
The FST is built in memory from the existing dictionary and is never persisted;
`max_fst_bytes` accounts its logical encoded size (documented as an estimate, not
RSS).

## Operator semantics

- **Prefix** matches any indexed term that *begins with* the normalized literal
  prefix (no stemming, no token splitting). Empty prefix is an existing typed
  `AnalysisError::EmptyTerm`.
- **Glob** uses `PreparedGlob::segments()` directly; `?` is exactly one Unicode
  scalar, `*` is zero or more, backslash escapes, whole-term match.
- **Regex** is compiled from `PreparedRegex::pattern()` and anchored to the whole
  term; the PR 4 grammar is authoritative. Unsupported constructs and invalid
  flags are rejected by PR 4 before reader open; oversized automata are rejected
  with `ResourceLimit` before large allocation.
- **Fuzzy** normalizes `value` through the field-bound `prepare_term` (exactly one
  token), supports `max_edits` 0–2, measures distance over normalized Unicode
  scalars, and computes restricted OSA when `transpositions = true`. An exhaustive
  unit test compares the automaton distance to a full-matrix OSA DP for all
  strings of length ≤ 4 over `{a,b,c}`.
- **Domain** reuses the same `Fuzzy` operator over a canonical domain keyword
  field produced by the PR 4 `analyze_domain` IDNA/UTS #46 analysis. There is no
  new API, writer behavior, PSL/TLD weighting or confusable-skeleton equivalence;
  original document keys are preserved.

## Scoring

Each multi-term leaf matches a document when at least one expanded term has a live
posting. The score is the sum of existing BM25 contributions for **distinct**
matched `(field, term)` pairs. `score_segment` assigns each `(field, term)` to a
single positive owner leaf (term-like leaves over phrase leaves) so overlapping
`Term`/`Prefix`/`Glob` leaves never double count. Global `n`/`df`/`avgdl`/`dl`
come from the whole snapshot, including mixed legacy/norms segments.

## Known limitations / notes

- The derived FST is rebuilt per request (no cross-request cache) and is charged to
  `max_fst_bytes` as logical bytes. This is the deferred performance optimization
  noted in the roadmap, not a semantic limitation.
- Under a composing-normalization analyzer (e.g. NFC), PR 4 conservatively rejects
  regex constructs such as `.`/`.*` immediately after a literal because a combining
  mark could compose across the boundary. This is inherited PR 4 behavior, not a
  PR 8 regression; identity/no-normalization fields accept those constructs.
- Broad patterns that exceed a published budget fail closed with
  `SearchError::ResourceLimit`; they are never silently truncated or promoted to
  `MatchAll`.
