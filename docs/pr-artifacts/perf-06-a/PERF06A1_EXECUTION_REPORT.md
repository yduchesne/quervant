# PERF-06-A1 — Execution Report

**PR:** PERF-06-A1: Prepare query-local BM25 term weights
**Branch:** `dev/perf06-a1-precomputed-bm25`
**Base:** `origin/main` @ `2a74017958c8ac61948f931e8745bf8134827025` (required baseline)
**Start SHA:** `2a74017958c8ac61948f931e8745bf8134827025`
**Scope:** correctness-first implementation only. **No** benchmark acquisition, profiling,
service startup or format change. Performance qualification belongs to PERF-06-A4.

---

## 1. Status

`PERF06_A1_IMPLEMENTED_CORRECTNESS_READY_FOR_INDEPENDENT_REVIEW`

All mandatory local gates passed (stable + MSRV), workspace line coverage is above the
85 % floor, and no unresolved failure, withheld RED evidence or semantic deviation exists.
This is **not** a performance claim: no wall-clock measurement was taken or is claimed.

## 2. Source verification (P0)

| Blob | Expected (§3) | Observed | Result |
| --- | --- | --- | --- |
| `crates/quervant-core/src/search/score.rs` | `a843ddc5…` | `a843ddc52f8951b286c6ed69a33aa5d7d694c9fa` | MATCH |
| `crates/quervant-core/src/search/execute.rs` | `497c683a…` | `497c683a3553d30b8cd877652e4961eb300eda76` | MATCH |
| `crates/quervant-core/src/search/unified.rs` | `89419f64…` | `89419f6404ce248c5912be0565d8ed9e9eb7aedf` | MATCH |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | `dca43449…` | `dca43449e911343db24d14d350c01ca3cf8a2fb4` | MATCH |
| `AGENTS.md` | `08fcd3de…` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` | MATCH |
| `.github/workflows/ci.yml` | `df63adc4…` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` | MATCH |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | `d7b3e993…` | `d7b3e9934bf5f9abdeb6bccc42a2dfde734593b8` | MATCH |

* `origin/main` and `HEAD` were both `2a74017958c8ac61948f931e8745bf8134827025`; the working
  tree was clean (only ignored build output). D01/D03 applied.
* `FieldStats.df` was `HashMap<String, u64>`; exactly three production `bm25` call sites existed
  (generic term leaf, generic phrase leaf, strict one-term scorer). No additional real BM25
  production call site was found (D08 not triggered).
* The A1 branch was created from `origin/main`, never from the PERF-06-A charter branch or
  PR #119 (D28).

## 3. Baseline focused evidence (pre-change)

| Command | Result |
| --- | --- |
| `cargo test -p quervant-core --lib bm25` | 4 passed |
| `cargo test -p quervant-core --lib b4_u0` | 7 passed |
| `cargo test -p quervant-core --test pr15i_d2a_scoring_contract` | 15 passed |
| `cargo test -p quervant-core --test pr07_properties` | 4 passed |
| `cargo test -p quervant-core --test pr14_unified_mixed` | 14 passed |
| `cargo test -p quervant-core --test pr15h_b_sort_materialization` | 6 passed |

## 4. RED evidence

`cargo test -p quervant-core --lib a1_` before the implementation produced **29 compile
errors**, every one of them caused only by the not-yet-existing prepared scoring API:

* `cannot find struct … PreparedTermStat` (score.rs)
* `cannot find function prepare_idf` (score.rs)
* `no method named bm25_score found for struct FieldStats` (score.rs)
* `cannot find idf_observation in score` (execute.rs / score.rs)

No unrelated baseline assertion, fixture or environment failure occurred (D18/19).
The RED set was U01/U04/U06 plus the new real-FS acceptance parity test.

Note on A1-I01: it is an **invariant** acceptance test (externally returned scores must equal
the frozen formula both before and after A1), so it is green on the baseline as well as after
the change; it is not a RED-first feature test. Feature RED is carried by U01/U04/U06.

## 5. Implementation (P2/P3)

Changed production code is limited to the three intended call sites and the query-local
statistics record:

* `score.rs`
  * new private `idf_log(doc_freq, n)` — the only place the IDF logarithm is evaluated.
  * new private `prepare_idf(doc_freq, n) -> Option<f64>` with the frozen guards
    (`doc_freq == 0`, `n == 0`, `doc_freq > n` → `None`).
  * new private `bm25_with_idf(tf, dl, avgdl, idf)` holding exactly the old post-IDF
    arithmetic (same conversions, same grouping, same finite/non-negative check and detail).
  * `bm25()` keeps its signature, early-return order, `df > n` typed error and string.
  * `PreparedTermStat { pub(crate) doc_freq, idf }` replaces the `u64` map **value**;
    the map, keys and single clone per query term are unchanged.
  * `FieldStats::bm25_score(term, tf, dl)` implements the prescribed decision tree:
    absent-term scalar fallback → early `+0.0` guards → deferred `InvalidScore` for
    `df > n` → `df == 0` scalar fallback → prepared IDF → frozen arithmetic; a missing
    prepared IDF is a `CorruptIndex("prepared BM25 IDF missing for valid term")`.
  * the three existing `checked_add` df accumulation branches update `stat.doc_freq`
    with unchanged limits/values; a single preparation loop runs **after** `avgdl`.
  * `doc_freq()` keeps its contract, reading `stat.doc_freq`.
* `execute.rs` — exactly three substitutions to `FieldStats::bm25_score`; owner
  deduplication, addition order, `+0.0` initialization, `dl` retrieval, ledger
  reservations and error propagation are untouched. `b4_u06` now mutates the prepared
  record's `doc_freq` (the only test-local map mutation required by the value-type change).
* `tests/pr15i_d2a_scoring_contract.rs` — new `a1_i01_…` real `FsDirectory` acceptance test
  with an independently restated frozen formula.

No change to `unified.rs`, scoring order, Top-K, heap, plan/eligibility, segment formats,
codecs, writer/reader, budgets, public API, CI or benchmarks.

## 6. Invariant trace

| ID | Evidence |
| --- | --- |
| INV-01 | `a1_u01_prepared_idf_matches_frozen_scalar_bits` — 4 fixed cases (incl. `>2^53` inputs) + 256 seeded tuples (seed `0xa106_a106_2026_1123`), exact `f64::to_bits()`; `a1_u02`, `a1_u08`; `a1_i01` real-FS formula parity; SC02–SC06, P03. PASS |
| INV-02 | `a1_u04_idf_is_prepared_once_per_query_term` — counter is 1 after `compute_stats` over two segments and stays 1 across repeated generic + strict scoring of every hit in both segments. PASS |
| INV-03 | `a1_u02_early_guards_preserve_scalar_precedence`, `a1_u06_invalid_df_and_missing_idf_fail_closed` — `+0.0` precedes the invalid-`df` error; no eager preparation error; `b4_u06`, `bm25_boundaries_and_invalid` PASS |
| INV-04 | `a1_u03_missing_and_zero_df_skip_preparation` — zero-df/absent terms consume no logarithm and reproduce the `df=0` scalar fallback; `a1_u04` absent-term leg. `sc01_zero_matches_have_no_scores` PASS |
| INV-05 | `a1_u07_owner_attribution_matches_frozen_scalar` (duplicate term leaf deduplicated, phrase owner, strict scorer, no-positive `+0.0`); SC09, SC10, SC11, `pr14` M08/M13 PASS |
| INV-06 | `a1_u05_compute_stats_prepares_idf_after_accumulation` (all-live/partial/dead/two-segment counts, df, avgdl, lengths unchanged); `b4_u05` exact/one-below 48M+64M reservation, `b4_u06`, SC12/SC13 PASS |
| INV-07 | `a1_i01` (explicit + relevance sort, K10/K100, generic `And`), SC01–SC15 incl. commit/reopen/PIT/cursor/repeats, `pr07` P03/P05, `pr15h_b` PASS |
| INV-08 | Changed-path audit: only the two allowlisted source files, one allowlisted test file and the two allowlisted docs. No persisted field, global/static cache, writer change or remote call. `a1_u04` proves request-local preparation. PASS |

## 7. Test evidence (post-change)

| Command | Result |
| --- | --- |
| `cargo test -p quervant-core --lib a1_` | 36 passed (9 new A1 + 27 pre-existing `a1_` amendment tests) |
| `cargo test -p quervant-core --lib a1_u` | 9 passed (U01, U02, U03, U04, U05, U06, U07, U08, U10) |
| `cargo test -p quervant-core --lib bm25` | 4 passed |
| `cargo test -p quervant-core --lib b4_u0` | 7 passed |
| `cargo test -p quervant-core --test pr15i_d2a_scoring_contract` | 16 passed (SC01–SC15 + A1-I01) |
| `cargo test -p quervant-core --test pr07_properties` | 4 passed |
| `cargo test -p quervant-core --test pr14_unified_mixed` | 14 passed |
| `cargo test -p quervant-core --test pr15h_b_sort_materialization` | 6 passed |

Scoring bit parity: 260 frozen-formula unit cases + 9 documents × 4 real-path requests
(2 sorts × K10/K100), `And` generic fallback, plus 3-contribution ordered sums; **0 mismatches**.

IDF preparation count: exactly **1 logarithm per valid positive `(field, term)`** for a
two-segment, four-hit query, unchanged across both scorers and six scoring passes; 0 for
absent/zero-`df` terms; a fresh independent query re-prepares exactly once.

Resource/cancellation/corruption: `b4_u05` (exact peak, one byte below), `b4_u06`
(invalid `df` → `InvalidScore`; missing field stats → `+0.0`; no owner → `+0.0`),
`sc12`/`sc13`, and the new `CorruptIndex` fail-closed unit case all PASS.

## 8. Mandatory local QA

| Gate | Command | Result |
| --- | --- | --- |
| Stable fmt | `cargo fmt --all -- --check` | PASS |
| Stable clippy | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| Stable tests | `cargo test --workspace --all-targets` | PASS — 2519 passed, 0 failed, 13 ignored |
| Coverage | `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **93.26 % lines** (regions 88.07 %, functions 92.70 %) |
| Docs | `cargo doc --workspace --no-deps` | PASS |
| MSRV fmt | `cargo +1.85.0 fmt --all -- --check` | PASS |
| MSRV clippy | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| MSRV tests | `cargo +1.85.0 test --workspace --all-targets` | PASS — 2519 passed, 0 failed, 13 ignored |
| All-features clippy | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| All-features tests | `cargo test --workspace --all-targets --all-features` | PASS — 2564 passed, 0 failed, 94 ignored |
| Diff hygiene | `git diff --check` | PASS |

Per-file coverage for the changed modules: `search/score.rs` 94.93 % lines,
`search/execute.rs` 95.86 % lines. Every new A1 production region (`idf_log`,
`prepare_idf`, `bm25_with_idf`, `PreparedTermStat`, `bm25_score` and all of its
`df == 0` / `n == 0` / invalid-`df` / missing-term / prepared-IDF / non-finite branches) has
a non-zero execution count.

Hosted CI: **PENDING** at the time of this report; it is reported separately and is not
claimed green here.

## 9. Exception rows applied

| Row | Trigger | Action | Evidence |
| --- | --- | --- | --- |
| D01/D03 | `origin/main` exactly `2a740179…`, clean tree | branched from exact `origin/main` | §2 |
| D05/D06/D07 | Expected map type and exactly three call sites | changed map value only, updated three checked-add branches, replaced three call sites | §5 diff |
| D09 | B4 invalid-`df` test inserted a raw `u64` | now mutates `PreparedTermStat.doc_freq`, keeps `idf` private and the old assertions | `b4_u06` PASS |
| D20 | `doc_freq()` became unused in production after all three call sites moved to `bm25_score` (dead-code under `-D warnings`); one `clippy::unnecessary_min_or_max` in the new test | Bounded lint-only fix in allowlisted files: `#[allow(dead_code)]` with justification on the retained accessor, and `[..specs.len()]` | fmt/clippy PASS |

No HARD STOP condition (D02/D04/D08/D14/D15/D19/D21/D22/D25/D32) was triggered.

## 10. Boundaries honored

* No benchmark run, Criterion execution, profiler, `perf record`, timed query loop or
  benchmark/result edit: **TRUE**.
* No RustFS/S3/container/service startup: **TRUE**.
* No segment/wire-format, public API or storage change: **TRUE**.
* No implementation change on the PERF-06-A charter branch or PR #119: **TRUE**.
* No merge performed; no A2/A4 work started.

## 11. Residual risk

* The prepared record's `idf` is `None` for `df == 0`, `n == 0` and `df > n`; those inputs
  deliberately keep the scalar fallback so error timing is unchanged. A future stage that
  removes the scalar fallback must preserve the same precedence.
* A1 provides no wall-clock evidence by design; the cumulative A-series impact is measured
  only in the separately authorized A4 qualification.
