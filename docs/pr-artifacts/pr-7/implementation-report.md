# PR 7 implementation report

## Summary

Adds a standalone, snapshot-bound lexical search executor to `quervant-core`:
exact lexical `Term` (Text/Keyword), positional `Phrase` on Text, arbitrarily
nested `And`/`Or`/`Not`, `MatchAll`, deterministic BM25 top-K and exact hit
counts. It reads PR 5 immutable postings through PR 6 `ReaderSnapshot`s and does
not change the segment format, manifest, writer, commit path or lifecycle.

## Public API (`quervant_core::search`)

- `SearchHit { key: DocumentKey, score: f64 }`
- `SearchResponse { hits, total_hits, generation, view_ordinal }`
- `LexicalSearcher<'a>::new(&ReaderSnapshot, &Schema, &AnalyzerRegistry, SearchLimits)`
  with `with_analysis_limits`, `limits`, and
  `search(&Query, TopK, &Budgets, &dyn Cancellation) -> Result<SearchResponse, SearchError>`.
- `SearchError` (wraps `QueryError`, `AnalysisError`, `SegmentError`, `IndexError`,
  plus `UnsupportedOperator`, `ResourceLimit`, `Cancelled`, `CorruptIndex`,
  `InvalidScore`).
- `SearchLimits` with ten explicit, hard-ceilinged bounds.

## Module layout

`search/{mod,error,limits,plan,execute,phrase,score,topk}.rs` as prescribed.

- `plan.rs` — fail-closed compilation: unsupported operators rejected before any
  segment read; field ids from `CodecSchema`; search-pipeline analysis; duplicate
  clause interning; compiled-node and unique-term bounds.
- `execute.rs` — two-phase execution: snapshot statistics first, then bounded
  per-segment doc-id/score maps; boolean evaluation over PR 6 live flags; key
  resolution; duplicate-key detection; top-K; RAII guarded readers.
- `phrase.rs` — positional chain verification across `position_length`,
  `position_length`-aware gaps and identical `value_index`.
- `score.rs` — `bm25(k1=1.2, b=0.75)` and snapshot-wide field-length/document
  frequency preparation with checked arithmetic and work/entry bounds.
- `topk.rs` — bounded binary heap, score descending then key ascending.

## Semantics decisions (within D07-01..D07-06)

- **Term**: Text is analyzed with the field's search pipeline; zero terms match
  nothing; multiple terms are an OR with one scoring contribution per distinct
  term. Keyword requires exactly one normalized term. Unsupported field types are
  `UnsupportedOperator`.
- **Phrase**: ordered components are concatenated with a single tokenization
  boundary and analyzed once, which preserves analyzer position holes; matching
  requires an ordered occurrence chain in the same `value_index` and respects
  `position_length`. Doc-only postings are a typed corruption failure.
  Phrase on non-Text fields is unsupported.
- **Boolean**: `And` intersection, `Or` union/dedup, `Not` live-universe
  complement. `Not(Not(X)) == X`; repeated clauses share one compiled leaf so
  scores cannot inflate; negation contributes zero.
- **Ranking**: `idf = ln(1 + (N - df + 0.5)/(df + 0.5))`,
  `score = idf * (tf * 2.2) / (tf + 1.2 * (1 - 0.75 + 0.75 * dl/avgdl))`.
  `dl` is rebuilt from dictionary/posting frequencies (no on-disk norms). `N`,
  `df` and `dl` use live documents only. Non-finite/negative scores fail typed.
- **Top-K**: exact `total_hits` independent of `K`; deterministic ties.

## Read-only seam additions (no encoding change)

`SegmentReader::{doc_keys, doc_key, live_docs, is_live, postings_for_entry}` and
`PostingsReader::is_positional`. These decode existing `DOC_KEYS`/`LIVE_DOCS`
sections and reuse existing postings extents. No segment-format, writer, manifest,
`CURRENT`, storage or distributed code was modified.

## Known limitations / residual risks

- Field lengths are recomputed for every searched field per query (O(indexed
  postings)); this is the approved v1 reference behaviour. A future separately
  approved format extension may add norms.
- The executor materializes per-segment candidate maps and a global key map
  (bounded); it does not claim streaming, WAND or block skipping.
- Duplicate live keys across segments are detected while merging matches, not
  eagerly before matching.
- Phrase concatenation uses a single ASCII-space boundary; this is documented as
  the v1 positional semantics and does not change PR 4 contracts.

## Amendment 01 changes

**Scoring polarity (`plan.rs`, `execute.rs`).** Added
`CompiledQuery::positive_leaf_indices` (even-`Not`-parity leaves computed once
from the finished tree) and filtered `score_segment` to eligible leaves only.
`query_terms` and `scoring_field_ids` are derived from eligible leaves, so a
negative-only field is never scanned for BM25 statistics. Boolean membership and
`eval_node` are unchanged.

**Resource accounting (`execute.rs`).** Removed the cumulative
`SearchWork::{candidates, candidate_limit, with_candidate_limit,
charge_candidates}`. Added `CandidateBudget` (per-segment entries + search-wide
segment/global bytes) and an RAII `SegmentCandidateLedger`; introduced
`execute_segment`/`execute_segment_inner` so all segment temporaries and their
reservations have a bounded lexical scope and reset between segments.
`SearchWork` now enforces a cumulative scanned-occurrence counter independent of
`max_total_work_units`.

**Field lengths (`score.rs`).** Replaced the `*slot == 0` heuristic with explicit
`HashMap::Entry` occupancy and a `accumulate_length` helper that enforces the
entry/byte bounds before insertion and leaves the map unchanged on rejection.

**Top-K (`topk.rs`).** Both initial insertion and replacement now compute the
resulting byte total and enforce the bound **before** mutating the heap or
counters; a failed replacement leaves the selector unchanged.

**Unchanged by design:** segment/manifest/index/storage encodings, snapshots,
phrase position arithmetic, BM25 constants, boolean membership, public
`SearchLimits` shape and ceilings, and no distributed/object-store/vector code.

**Accepted scope/approximation:** the byte figures are deterministic logical
accounting units (with tree/hash overhead allowances), not exact heap bytes or
RSS. `match_phrase`'s internal scratch vectors are not separately charged; the
occurrence ownership map and match reservations dominate that leaf's cost.

## Amendment 02 changes

**Atomic transport (`execute.rs`).** Added
`CandidateBudget::transfer_segment_to_global` and
`SegmentCandidateLedger::transfer_to_global`; both validate entries, bytes and
checked global arithmetic before mutating, and preserve the
`segment_bytes + global_bytes` total. `SegmentCandidateLedger::finish` is now a
verification boundary that **errors** if any segment reservation remains, rather
than a bulk release.

**Explicit ownership (`execute.rs`).** Added `Charges` records and a private
`SegmentResults { entries, reserved_bytes }`. `execute_segment_inner` now drops
and releases `live_set` after `eval_node`, `matches`/`leaf_data` after
`score_segment`, and the scored map after doc-id→key conversion, in source-visible
order. The output batch is reserved as a segment charge, then transferred to
global ownership **before** `finish()` and before returning; `execute_search`
drains the already-charged batch into the global map without re-reserving.

**Phrase scratch lifetime.** `build_phrase` tracks scratch charges separately,
drops `per_token`/`index_of`/`distinct`, then releases the scratch reservation
before returning the match charges. `build_leaf_data` aggregates retained term
postings and phrase matches into `Charges`. `ReservedSet::release` drops its set
before releasing the ledger reservation.

**Unchanged:** public `SearchLimits`, public `search/mod.rs` API, `phrase.rs`,
`plan.rs`, `score.rs`, `topk.rs`, segment/index/storage encodings, BM25, phrase
position rules and positive-leaf policy.

**Accepted residual risk:** `match_phrase`'s internal scratch vectors remain not
individually byte-charged (bounded work); logical accounting is not RSS.

## Amendment 03 changes

**Transactional ledger (`execute.rs`).** Added `LedgerState`, `snapshot`/`commit`,
and pure `checked_reserve`/`checked_release`/`checked_transfer` calculations.
`reserve`/`release`/`transfer_to_global` now preflight both budget and ledger
state (including cross-counter consistency) and commit all five fields at once;
a rejected transition mutates nothing. `CandidateBudget::release_segment` now
validates both subtractions before assigning. `finish()` stays verification-only.
The test-only direct `reserve_segment`/`transfer_segment_to_global` remain atomic.

**Bounded phrase scratch (`execute.rs`, `phrase.rs`).** Added `PhraseScratch` (a
`pub(super)` scoped owner over the segment ledger) and `PHRASE_SCRATCH_{REF,DOC,
OCC_SLICE,FREQ}_BYTES` logical units. `match_phrase` now reserves fixed-capacity
scratch before `try_reserve_exact` for `distinct`, `candidates`, the bounded
intersection result, `token_occurrences`, and `phrase_chains::{current,
advanced}`, releasing each after its vector is dropped. Retained `matches` and
`term_freqs` remain covered by the caller's existing phrase-match reservation
and are not charged twice. `PhraseScratch::Drop` is the cleanup safety net.

**Unchanged:** public `SearchLimits`/API, `plan.rs`, `score.rs`, `topk.rs`,
segment/index/storage encodings, BM25, phrase position semantics and
positive-leaf policy. No `unsafe` or new dependencies.

**Accepted residual risk:** scratch units are conservative logical estimates, not
allocator-exact RSS; field-length recomputation remains O(indexed postings).

## Amendment 04 changes

Measurement infrastructure only; **no production source changed**.

- `crates/quervant-core/Cargo.toml`: `autobenches = false`; five explicit
  `[[bench]]` targets (`bm25`, `search`, `postings`, `phrase`, `dictionary`, all
  `harness = false`); dev-only `criterion = "=0.7.0"` with
  `default-features = false, features = ["cargo_bench_support"]` (builds on Rust
  1.85). `Cargo.lock` updated.
- `benches/common/mod.rs`: deterministic SplitMix64 fixture, independent token-list
  oracle, canonical SHA-256 dataset digest, shared Criterion group configuration.
- `benches/{bm25,search,postings,phrase,dictionary}.rs`: reference-arithmetic
  control, whole-search, real postings decode, end-to-end phrase, and real
  dictionary lookup.
- `examples/pr07_profile.rs`: benchmark-only profiling entrypoint reusing the same
  fixture (`--workload`, `--seconds`, `--print-digest`).
- `tests/pr07_amendment04.rs`: A4-T01–T08 and A4-T12.
- `benchmarks/scripts/{capture-pr07-env,profile-pr07,run-pr07-baseline,test-scripts}.sh`
  and `validate-report.py`; `benchmarks/{README.md,workloads/pr07_amendment04_v1.md,reports/*}`.
- `docs/BENCHMARKING.md`: permanent Linux/WSL2 microbenchmark/profiling policy.

**Unchanged:** all of `src/search/**`, `src/segment/**`, `src/index/**`,
`src/storage/**`, public APIs, resource limits, scoring, query semantics and the
on-disk format.

**Accepted residual risks:** profilers unavailable on this WSL2 host (profiling
classified BLOCKED); absolute timings host-specific; no allocation counts; no
competitor adapters/ratios (PR 15); 1M extended lane and 25% tombstone lane not
run (the latter NOT APPLICABLE for insert-only PR 7).
