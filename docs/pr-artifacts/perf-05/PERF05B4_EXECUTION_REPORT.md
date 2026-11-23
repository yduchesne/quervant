# PERF-05-B4 — Execution Report

**Milestone:** `v0.1-perf` · **Stage:** PERF-05-B4 (score strict single-term candidates without a full-M scored map)
**Branch / PR:** `dev/perf05-physical-execution-series` · PR [#117](https://github.com/yduchesne/quervant/pull/117)
**Plan of record:** [`PERF05B4_DETAILED_PLAN.md`](PERF05B4_DETAILED_PLAN.md) (verbatim copy; `cmp` identical, 0 trailing spaces)

---

## REPO / BRANCH / PR

- **Repository:** `yduchesne/quervant`
- **Branch:** `dev/perf05-physical-execution-series` (existing series branch; no new branch/PR)
- **PR:** #117 (OPEN / draft / unmerged)

## START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA

- **START_SHA:** `af69e3859f21fac9dcb0e254dab6a46e1b2cf5c8` (B3 head; B1 `668206b…`, B2 `dfa876c…`, B3 all
  verified ancestors)
- **MAIN_SHA:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8`
- **FINAL_SHA / REMOTE_VERIFIED_SHA:** a file inside the commit cannot embed that commit's own hash.
  `FINAL_SHA` is the containing pushed commit, retrieved with `git rev-parse HEAD`; the exact value
  is stated in the terminal agent response and is equal to
  `git rev-parse origin/dev/perf05-physical-execution-series` after push.

**Preflight (D02):** clean status. The previously recorded generated artifacts (`.coverage`,
`benchmark-results/**`, `benchmarks/quervant_bench.egg-info/**`) remain locally excluded; the exclude
file was not modified. No tracked change or unknown untracked path existed.

## S01–S15 SOURCE PROOFS / I01–I16 INVARIANT-TEST TRACE

Re-verified on the pulled B3 head before editing:

- **S01** `single_term_postings_eligible` = root `Lexical(0)`, one one-analyzed-term leaf, no typed
  leaves, positive `{0}`, no aggregation, no `after`. Confirmed.
- **S02** `collect_mixed` passes the flag and B1 callback; consumer untouched.
- **S03** `build_leaf_data` decodes effective-live `(doc_id, freq)` in sorted order with validity/
  work/memory charges before the target region. Confirmed.
- **S04** `evaluate_lexical_with` runtime shape guard `[LeafData::Term{terms}] if terms.len()==1 &&
  !typed_examination` precedes the eligible callback and yields the same `CorruptIndex` string.
- **S05** B2 verified live count + `effective_live_examination_count` polling and
  `meter.charge_lexical(live_count)` retained.
- **S06** Ascending-unique enumeration (postings or live bitmap); debug asserts preserved.
- **S07** 48-byte matched reservation then 64-byte scored reservation, with matched/leaf/scored
  release order preserved.
- **S08** Generic `score_segment` seeds `0.0`, finds one owner, adds one `bm25` contribution per
  accepted doc.
- **S09** `bm25` is the sole calculator; absent field stats leave `+0.0`; `df` defaults to 0.
- **S10** Sibling `execute_segment_inner` and generic scorer unchanged (only a `#[cfg(test)]` call
  counter added at the top of `score_segment`).
- **S11** Unified caller consumes the owned `Vec<(u64,f64)>`; key/sort/duplicate/heap unchanged.
- **S12** Existing B1/B2/B3/budget/score tests reused unmodified.
- **S13** Exactly two production `score_segment` call sites (sibling + unified fallback).
- **S14** Ledger/`SlotMemoryScope` fail-closed accounting retained for 48/64 logical units.
- **S15** Stage scoping: only B4 narrow scoring implemented; B5/C untouched.

**Invariant → evidence**

| Invariant | Evidence |
|---|---|
| I01 exact totals, no Top-K early stop | B4-U03; phase4 U09 |
| I02 eligible uses helper, fallback generic | B4-U03/U04 dispatch counters |
| I03 exact u64 freq, no second postings pass | B4-U01/U07, source audit |
| I04 bit-exact BM25 incl. zero/empty | B4-U01/U02/U06, B3 regressions |
| I05 B1 shortcut/fallback unchanged | B1 U01–U04, B4-U04 |
| I06 B2 counts/work/cancellation unchanged | B2 U01–U06, phase4 U10–U16 |
| I07 ordering/multi-segment unchanged | B4-U03, B3 U01–U03, `b_u12…` |
| I08 48M then 64M, release order, exact/one-below | B4-U05, C2 budget tests |
| I09 typed `InvalidScore` after admissions | B4-U06 |
| I10 callbacks before scoring; rejects excluded | B4-U02/U03, B1 predicate witness |
| I11 generic/sibling/Boolean/phrase intact | B4-U04, B3 U01/U02, `pr13_oracle` |
| I12 score/fields/sort/ties/cursor/duplicates | B4-U03/U04, `b_tests`, `pr13_oracle` |
| I13 query-local only | changed-path audit, local Fs/RustFS status |
| I14 no benchmark/profile, same PR | this report, allowlist |
| I15 typed errors not weakened | B4-U05/U06, negative suites |
| I16 stable + MSRV + coverage ≥85% | QA table below |

## IMPLEMENTED_FILES (four-path allowlist)

1. `crates/quervant-core/src/search/execute.rs` — private `score_single_term_candidates`, eligible
   `Vec<(u64,u64)>` candidate buffer + push, scoring-selection tail, test-only dispatch counters,
   B4-U01/U02/U05/U06/U07 and adapters.
2. `crates/quervant-core/src/search/unified.rs` — **tests only**: `phase4_b4_u03_…`,
   `phase4_b4_u04_…` in `phase4_tests`. No production change.
3. `docs/pr-artifacts/perf-05/PERF05B4_DETAILED_PLAN.md` (verbatim).
4. `docs/pr-artifacts/perf-05/PERF05B4_EXECUTION_REPORT.md` (this file).

`score.rs`, `work.rs`, `typed.rs`, `plan.rs`, `unified_plan.rs`, codecs/readers, storage/RustFS,
Cargo/CI/benchmarks and prior reports are untouched.

## PRODUCTION DIFFERENCE: helper, exact candidates, selected scorer branch

- Added `score_single_term_candidates(...)` immediately after `score_segment`: reserves
  `M*SCORED_MAP_BYTES_PER_ENTRY` via `reserve_with_memory`, then emits `Vec<(u64,f64)>` directly with
  `score = 0.0; score += bm25(freq, df, n, dl, avgdl)?` under `positive.contains(&0)` and
  `stats.field(field_id)`. No map, no second postings pass, no extra cancellation/work poll.
- Added `let mut single_term_matched: Vec<(u64,u64)> = Vec::new();`; the eligible loop copies
  `(doc_id, freq)` only after a successful `is_match`, with a strictly-ascending debug assert.
- The evaluation tail reserves `M*48` from the active buffer, dispatches the strict helper for the
  eligible branch (reconfirming the one-term shape) and the unchanged generic scorer otherwise, then
  drops `matched`/`single_term_matched`/`leaf_data` and releases matched/leaf/scored in the original
  order.
- Generic `score_segment` gained only `#[cfg(test)] test_observation::record_generic_scorer_call();`
  before its logical reservation.

## RED_FIRST: exact command, sole unresolved-helper diagnostic

- **Command:** `cargo test -p quervant-core --lib b4_u01_single_term_scores_match_generic_bm25_bits -- --nocapture`
- **Expected/actual:** `error[E0425]: cannot find function score_single_term_candidates in this scope`
  — the sole diagnostic, with the test-only adapter otherwise compiling. **PASS-as-expected (D05).**

## GREEN: test names/counts and comparisons

- `cargo test -p quervant-core --lib b4_` → **7 passed** (U01–U07).
- U01/U02: real `golden_norms.seg` decoded postings; generic vs helper `(doc_id, score.to_bits())`
  equal; empty/first/all subsets equal; charges equal (`M*64`).
- U03: direct strict query = `single_term_scorer_calls()==1`, `generic==0`; wrapped `And` = reverse;
  predicate calls and B1 lookup counts preserved; counts/keys/score bits/projection equal across
  relevance and sort, K1/10/100.
- U04: every ineligible shape and a valid `after` cursor select the strict helper **zero** times;
  an ineligible lexical fallback does call the generic scorer.
- U05: exact `M*48 + M*64` passes; one byte below returns `ResourceLimit { limit: peak-1,
  requested: peak }`; RAII drop clears the segment counters.
- U06: `df > n` → both `InvalidScore`; missing field stats and absent positive owner → both `+0.0`
  bits.
- U07: frequency `9_007_199_254_740_993` (>2^53) produces identical finite score bits in both paths.

## SCORER DISPATCH

- Strict eligible: `single_term_scorer_calls()==1`, `generic_scorer_calls()==0`.
- Wrapped `And` fallback: `single_term_scorer_calls()==0`, `generic_scorer_calls()==1`.
- Counters are `#[cfg(test)]` only; none in release/benchmark builds.

## BM25 / LOGICAL ACCOUNTING

- BM25 uses the existing `super::score::bm25` with original `u64` frequency, `df`, `n`,
  `dl`, `avgdl`; score starts at `0.0` and accumulates once per accepted doc.
- Matched reservation `M*SET_BYTES_PER_ENTRY (48)`, then scored reservation
  `M*SCORED_MAP_BYTES_PER_ENTRY (64)`; matched/leaf/scored release order unchanged. Exact/one-below
  behavior verified in B4-U05.

## TESTS: command | toolchain / topology | result | actual output

| Command | Toolchain/topology | Result | Output |
|---|---|---|---|
| `cargo test -p quervant-core --lib b4_` | stable 1.98.1, real fixtures | PASS | 7 passed |
| `cargo test -p quervant-core --lib phase4_tests` | stable | PASS | 14 passed |
| `cargo test -p quervant-core --lib b_tests` | stable | PASS | 20 passed |
| `cargo test -p quervant-core --lib budget_tests` | stable | PASS | 50 passed |
| `cargo test -p quervant-core --lib b2_` | stable | PASS | 6 passed |
| `cargo test -p quervant-core --lib b3_` | stable | PASS | 3 passed |
| `cargo test -p quervant-core --lib score::tests` | stable | PASS | 11 passed |
| `cargo test -p quervant-core --test pr13_oracle` | stable, oracle | PASS | 2 passed |
| `cargo test -p quervant-core --test pr15e_b1` | stable, batch parity | PASS | 17 passed |
| `cargo test -p quervant-core --test pr06_local_integration` | stable, real FsDirectory | PASS | 16 passed, 3 ignored |
| `cargo fmt --all -- --check` | stable | PASS | clean |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable | PASS | clean |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | PASS | clean |
| `cargo test --workspace --all-targets` | stable default | PASS | 2504 passed, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | stable all-features | PASS | 2549 passed, 0 failed, 94 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | stable | PASS | 92.16% lines |
| `cargo doc --workspace --all-features --no-deps` | stable | PASS | generated |
| `cargo +1.85.0 fmt --all -- --check` | MSRV 1.85.0 | PASS | clean |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | MSRV | PASS | clean |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | MSRV | PASS | 2549 passed, 0 failed, 94 ignored |
| `cargo bench --workspace --no-run` | compile only | PASS | all bench binaries built |
| `bash benchmarks/scripts/test-scripts.sh` | self-tests | PASS | 108 passed, 0 failed |
| `git diff --check` | housekeeping | PASS | clean |

## WORKSPACE_COVERAGE

`cargo-llvm-cov 0.9.1`, stable 1.98.1, `llvm-tools` installed:
`cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` →
**92.16% line coverage** (regions 92.84%, functions 87.84%); 61,786 lines, 4,841 missed; exit 0; no
exclusions or floor changes.

## REAL LOCAL FS / RUSTFS / CI

- Real local `FsDirectory` + writer/commit/reopen/query: PASS (`pr06_local_integration`,
  `pr13_oracle`).
- RustFS: **RUSTFS_LOCAL_BLOCKED** — no `QUERVANT_RUSTFS_*` service; `--ignored` real-service tests
  were not run and are not claimed.
- CI: **PENDING** — the pushed commit's hosted jobs have not run.

## EXCEPTION MATRIX ROWS

- **D02 (AUTO-RESOLVE)** — only known locally excluded generated artifacts; untouched.
- **D03 (DEFER AND CONTINUE)** — earlier-stage CI/RustFS unfinished; proceeded with B4 local work and
  recorded pending.
- **D04 (AUTO-RESOLVE)** — S01–S15 held; strict guard, decoded freq and two callers confirmed;
  implemented §§4–5 verbatim.
- **D05 (AUTO-RESOLVE)** — RED was solely the missing helper (`E0425`); continued to GREEN.
- **D07 (AUTO-RESOLVE)** — candidate `(doc_id, freq)` copied only after successful callback; checks
  and polls preserved.
- **D13 (AUTO-RESOLVE)** — rustfmt wraps confined to the new test lines; ran `cargo fmt --all`,
  inspected diff, reran affected QA.
- **D14 (AUTO-RESOLVE)** — test-only counters retained; dispatch witnesses agree with eligibility.
- **D16 (DEFER AND CONTINUE)** — RustFS unavailable / CI pending; completed local gates and pushed a
  truthful pending report.
- **D19 (AUTO-RESOLVE, twice)** — two deterministic test-scaffolding corrections in newly added
  tests: renamed a local `limits` binding that shadowed the `limits(entries, bytes)` helper (E0618),
  and used a >K-match fixture to obtain a valid `after` cursor. No expected values or limits were
  changed.
- **D21 (AUTO-RESOLVE)** — no benchmark/profiling performed.
- **D24 (DEFER AND CONTINUE)** — local gates pass with CI/RustFS pending; pushed and reported the
  local-pass/pending disposition.

No HARD-STOP row was triggered.

## OPEN GATES / RESIDUAL RISKS / FAILURE CLASSIFICATIONS

**Open gates:** hosted CI for the pushed commit; pinned RustFS acceptance
(`pr13_oracle --ignored`, `pr15g_b_rustfs --ignored`); independent reviewer checklist.

**Residual risks:** the equivalence proof depends on the strict eligible path remaining exactly one
positive single-term leaf; future eligibility changes require review. `Vec::with_capacity` may
allocate like the old map materialization, but modeled 48/64 accounting is unchanged and no physical
OOM gate is claimed. Strict ascending-unique production invariants are source-proven today. No
latency/throughput improvement is measured or claimed (PERF-05-C).

**Failure classification:** all executed commands passed. No introduced regression, feature defect,
deterministic pre-existing failure, flake, or environment/harness failure was observed. RustFS/CI are
environment-gated pending.

## NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE

No timed benchmark, `quervant-bench run`, `perf record`, `perf script`, CPU sampling, microbenchmark,
A/A, A/B, idle probe or profiler preflight was run. `cargo bench --workspace --no-run` is
compile-only; `benchmarks/scripts/test-scripts.sh` is non-timed script self-tests.

## B4_DISPOSITION

**`B4_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING`**

The strict single-positive-term path now scores from exact `(doc_id, u64 freq)` candidates after the
unchanged matching and modeled admissions, eliminating the eligible scored `BTreeMap`, its
`get_mut` searches and the second postings walk. Generic scoring, sibling execution, B1–B3, all
logical charges, cancellation, error precedence, counts, keys, score bits, sort, projection and
cursor behavior are preserved; local stable + MSRV + coverage gates pass. Hosted CI/RustFS remain
pending; PR #117 stays open, draft and unmerged.

## NEXT=independent B4 review; B5 separately gated
