# PERF-05-B5 — Execution Report

**Milestone:** `v0.1-perf` · **Stage:** PERF-05-B5 (reuse validated strict-term postings allocation by ownership handoff)
**Branch / PR:** `dev/perf05-physical-execution-series` · PR [#117](https://github.com/yduchesne/quervant/pull/117)
**Plan of record:** [`PERF05B5_DETAILED_PLAN.md`](PERF05B5_DETAILED_PLAN.md) · **Feasibility review:** [`PERF05B5_FEASIBILITY_REVIEW.md`](PERF05B5_FEASIBILITY_REVIEW.md) (both verbatim; `cmp` identical, 0 trailing spaces)

---

## REPO / BRANCH / PR

- **Repository:** `yduchesne/quervant`
- **Branch:** `dev/perf05-physical-execution-series` (existing series branch; no new branch/PR)
- **PR:** #117 (OPEN, unmerged). Observed `isDraft:false`; this was already the externally observed state at B4 start and was **left untouched** (D27).

## START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA

- **START_SHA:** `3b25a76b99f699c45aa2050c4f889880a138948a` (B4 head; B1/B2/B3/B4 verified ancestors)
- **MAIN_SHA:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8`
- **FINAL_SHA / REMOTE_VERIFIED_SHA:** a file inside a commit cannot embed that commit's own hash.
  FINAL_SHA is the containing pushed commit (`git rev-parse HEAD`); the exact value is in the
  terminal agent response and equals `git rev-parse origin/dev/perf05-physical-execution-series`
  after push.

**Preflight (D01/D04):** clean status; PR head matched the inspected B4 SHA; the previously recorded
generated artifacts (`.coverage`, `benchmark-results/**`, `benchmarks/quervant_bench.egg-info/**`)
remain locally excluded and untouched. No unknown tracked/untracked source.

## S01–S15 SOURCE PROOFS / I01–I14 INVARIANT-TEST TRACE

Re-verified on the pulled B4 head:

- **S01** `single_term_postings_eligible` = root `Lexical(0)`, one one-analyzed-term leaf, positive
  `{0}`, no typed leaves, no aggregation, no `after`. Confirmed.
- **S02** `collect_mixed` passes the flag; the strict callback returns `true` but is still invoked for
  every posting. Confirmed.
- **S03** `build_leaf_data` fully decodes/validates/charges before any callback. Confirmed.
- **S04** `TermPostings { term: String, postings: Vec<(u64,u64)> }`, ascending-unique, `freq` stays
  `u64`. Types unchanged.
- **S05** `evaluate_lexical_with` performs the strict shape guard with the exact
  `"single-term postings eligibility mismatch"` detail.
- **S06** B2 verified-live count, `charge_lexical`, cancellation polls and one callback per candidate
  preserved.
- **S07** B4 copied every accepted pair into `single_term_matched`; the production eligible callback
  accepts all.
- **S08** Post-callback `M*48` matched then `M*64` scored admissions and BM25 unchanged.
- **S09** `score_single_term_candidates` needs only accepted pairs, field id, term, stats, segment
  index.
- **S10** Tail drop order `matched`/candidate/`leaf_data` then release matched/leaf/scored preserved.
- **S11** Generic fallback `matched: Vec<u64>` + `score_segment` and sibling executor unchanged.
- **S12** Unified consumer still validates all scored candidates before bounded Top-K.
- **S13/S15** Feasibility review confirms GO only for borrow-then-move and NO-GO for streaming
  reader/cursor/physical collector; no retired mechanism introduced.
- **S14** Test witnesses remain thread-local `#[cfg(test)]`.

**Invariant → evidence**

| Invariant | Evidence |
|---|---|
| I01 no second full-M accepted-pair Vec; original moved after callbacks | B5-U01 pointer/len/capacity identity; B5-U04 move witness; source audit |
| I02 no posting omitted; full validation before callbacks | source S03; existing corruption regressions |
| I03 callbacks see intact leaf; no re-call | B5-U02; B1 predicate counts |
| I04 false callbacks yield exact subset without mutation | B5-U02 |
| I05 eligibility/fallback policy unchanged | B5-U04/U05, B1/B4 tests |
| I06 ascending IDs, exact `u64` freq | B5-U01/U02, B4-U07 |
| I07 all-M BM25/total hits/score bits | B5-U04, B4-U01/U02/U06, oracle |
| I08 P*16 + M*48 + M*64 admissions/order | source tail, B4-U05, C2/batch regressions |
| I09 ownership dies before leaf-charge release | source tail, budget/fault suites |
| I10 typed error/`InvalidScore`/`Cancelled`/`CorruptIndex`/`ResourceLimit` precedence | B5-U03, B2/B4 regressions |
| I11 generic/sibling/unified consumer/cursor/batch unaffected | `unified.rs` production diff empty; B5-U05; `b_tests`; `pr13_oracle` |
| I12 witnesses `#[cfg(test)]` only | source audit; `cargo bench --no-run` |
| I13 stable+MSRV+≥85% coverage | QA table |
| I14 no benchmark/profiler/C work | this report |

## IMPLEMENTED_FILES (five-path allowlist)

1. `crates/quervant-core/src/search/execute.rs` — `take_strict_one_term_postings`,
   `StrictTermMatchSelection`, `mut leaf_data` + eligible borrow/move loop, test-only handoff
   witnesses, B5-U01/U02/U03.
2. `crates/quervant-core/src/search/unified.rs` — **tests only**: `phase4_b5_u04_…`,
   `phase4_b5_u05_…` in `phase4_tests`. Production diff is empty (single test-module hunk).
3. `docs/pr-artifacts/perf-05/PERF05B5_FEASIBILITY_REVIEW.md` (verbatim; `cmp` identical).
4. `docs/pr-artifacts/perf-05/PERF05B5_DETAILED_PLAN.md` (verbatim; `cmp` identical).
5. `docs/pr-artifacts/perf-05/PERF05B5_EXECUTION_REPORT.md` (this file).

No changes to `score.rs`, `work.rs`, `typed.rs`, codecs/readers, storage/RustFS, Cargo/CI/benchmarks,
or prior-stage reports.

## PRODUCTION DIFFERENCE

- Added checked `take_strict_one_term_postings(&mut [LeafData], typed_examination)` that validates
  the single one-term shape, records a test-only move witness, and returns
  `std::mem::take(&mut terms[0].postings)` (same allocation).
- Added `StrictTermMatchSelection` with `observe(postings, index, accepted)` (first-rejection prefix
  copy, then subsequent accepted appends) and `finish(...)` (rejection → copied subset; all-accepted
  → move).
- `evaluate_lexical_with` now binds `let (mut leaf_data, leaf_charges)` and, in the eligible branch,
  borrows `postings` for the unchanged cancellation poll + one `is_match` call per candidate, then
  `single_term_matched = selection.finish(&mut leaf_data, typed_examination)?` **after** the final
  callback. The generic fallback, 48/64 reservations, B4 scorer dispatch, drops and releases are
  unchanged.

## RED_FIRST

- **Command:** `cargo test -p quervant-core --lib b5_u01_handoff_moves_exact_vec_allocation -- --nocapture`
- **Order note:** the §5.4 `#[cfg(test)]` handoff witnesses were added first so the only missing
  symbol in the RED is the prescribed helper.
- **Actual:** sole `error[E0425]: cannot find function take_strict_one_term_postings in this scope`.
  **PASS-as-expected (D06).**

## GREEN: test names/counts and comparisons

- `cargo test -p quervant-core --lib b5_` → **5 passed** (U01–U05).
- U01: moved vector keeps the exact original pointer, length and capacity; the leaf keeps field id
  and term text with an empty posting Vec; move witness 1, fallback 0.
- U02: empty, singleton, all-true, interspersed-false, false-first, all-false and false-last masks
  yield the exact accepted `(doc_id, u64 freq)` subset; all-accepted/empty move, any-false keeps the
  original intact and uses the fallback.
- U03: empty slice, phrase, two leaves, `typed_examination=true` and two-term leaf all return the
  exact `CorruptIndex` detail with no mutation and zero witnesses.
- U04: real indexed corpora (0/1/sparse/dense/all matches; relevance + `n ASC`; K1/10/100) — direct
  strict query moves once and uses the strict scorer only; wrapped `And` moves zero and uses the
  generic scorer only; totals, keys, score bits, projection, predicate counts and B1 lookup counts
  agree.
- U05: ineligible shapes, cursor continuation, a real two-segment index and an ineligible batch
  request never move, never fall back and never select the strict scorer; results remain correct.

## TESTS: command | toolchain / topology | result | actual output

| Command | Toolchain/topology | Result | Output |
|---|---|---|---|
| `cargo test -p quervant-core --lib b5_` | stable 1.98.1, real fixtures | PASS | 5 passed |
| `cargo test -p quervant-core --lib phase4_tests` | stable | PASS | 16 passed |
| `cargo test -p quervant-core --lib b4_` | stable | PASS | 7 passed |
| `cargo test -p quervant-core --lib b3_` | stable | PASS | 3 passed |
| `cargo test -p quervant-core --lib b2_` | stable | PASS | 6 passed |
| `cargo test -p quervant-core --lib b_tests` | stable | PASS | 20 passed |
| `cargo test -p quervant-core --lib budget_tests` | stable | PASS | 53 passed |
| `cargo test -p quervant-core --lib score::tests` | stable | PASS | 11 passed |
| `cargo test -p quervant-core --test pr13_oracle` | stable, oracle | PASS | 2 passed |
| `cargo test -p quervant-core --test pr15e_b1` | stable, batch parity | PASS | 17 passed |
| `cargo test -p quervant-core --test pr06_local_integration` | stable, real FsDirectory | PASS | 16 passed, 3 ignored |
| `cargo fmt --all -- --check` | stable | PASS | clean |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable | PASS | clean |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | PASS | clean |
| `cargo test --workspace --all-targets` | stable default | PASS | 2509 passed, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | stable all-features | PASS | 2554 passed, 0 failed, 94 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | stable | PASS | 92.20% lines |
| `cargo doc --workspace --all-features --no-deps` | stable | PASS | generated |
| `cargo +1.85.0 fmt --all -- --check` | MSRV 1.85.0 | PASS | clean |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | MSRV | PASS | clean |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | MSRV | PASS | 2554 passed, 0 failed, 94 ignored |
| `cargo bench --workspace --no-run` | compile only | PASS | all bench binaries built |
| `bash benchmarks/scripts/test-scripts.sh` | self-tests | PASS | 108 passed, 0 failed |
| `git diff --check` / staged `--check` | housekeeping | PASS | clean |

## WORKSPACE_COVERAGE

`cargo-llvm-cov 0.9.1`, stable 1.98.1, `llvm-tools` installed:
**92.20% line coverage** (regions 92.87%, functions 87.90%); 62,141 lines, 4,846 missed; exit 0; no
exclusions or floor changes.

## REAL LOCAL FS / RUSTFS / CI

- Real local `FsDirectory` + writer/commit/reopen/query: PASS (`pr06_local_integration`,
  `pr13_oracle`, `pr15e_b1`).
- RustFS: **RUSTFS_LOCAL_BLOCKED** — no `QUERVANT_RUSTFS_*` service; `--ignored` real-service tests
  were not run and are not claimed.
- CI: **HOSTED_CI_PENDING** — the pushed commit's hosted jobs have not run.

## EXCEPTION MATRIX ROWS

- **D01 (AUTO-RESOLVE)** — exact PR head `3b25a76…`, B4 anchors unchanged, clean tree; proceeded.
- **D04 (AUTO-RESOLVE)** — known generated artifacts remain locally excluded; stage only explicit
  paths.
- **D06 (AUTO-RESOLVE)** — RED was solely `E0425` for the missing helper; implemented §5 and reran.
- **D08 (AUTO-RESOLVE, not needed)** — the borrow/move loop compiled without the nested-scope repair;
  no borrow diagnostic arose.
- **D10/D11/D12 (AUTO-RESOLVE)** — normal path moves the exact Vec; any false uses the lazy fallback;
  shape mismatch returns the exact typed error.
- **D13 (AUTO-RESOLVE)** — Clippy `type_complexity` on the new U02 data tuple; replaced it with a
  local test struct (deterministic adjustment in new test code, no lint suppression).
- **D18 (AUTO-RESOLVE)** — real local `FsDirectory` integration passed.
- **D19 (DEFER AND CONTINUE)** — RustFS unavailable locally; recorded BLOCKED.
- **D20 (DEFER AND CONTINUE)** — hosted CI pending; not claimed as PASS.
- **D25 (AUTO-RESOLVE)** — `cargo bench --no-run` compiled; no samples acquired.
- **D27 (AUTO-RESOLVE)** — PR `isDraft` observed `false`; left metadata untouched.

No HARD-STOP row was triggered.

## OPEN GATES / RESIDUAL RISKS / FAILURE CLASSIFICATION

**Open gates:** hosted CI for the pushed commit; pinned RustFS acceptance
(`pr13_oracle --ignored`, `pr15g_b_rustfs --ignored`); independent reviewer checklist.

**Residual risks:** the equivalence/ownership proof depends on the strict eligible path remaining one
positive single-term leaf and on all callbacks completing before the move; allocator timing differs
and no machine-level OOM or instruction-layout neutrality is claimed. The feasibility review notes
source-layout risk for low-hit cases; only PERF-05-C can measure warm A/B. No latency/throughput
claim is made here.

**Failure classification:** all executed commands passed after the single Clippy test-code
adjustment. No introduced production regression, pre-existing failure, flake, or environment/harness
failure was observed. RustFS/CI are environment-gated pending.

## NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE

No timed benchmark, `quervant-bench run`, `perf record`, `perf script`, CPU sampling, microbenchmark,
A/A, A/B, idle probe or profiler preflight was run. `cargo bench --workspace --no-run` is
compile-only; script tests are non-timed.

## B5_DISPOSITION

**`B5_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING`**

The strict eligible path now borrows the intact validated leaf through every callback and, on the
normal all-accepted path, moves the original `TermPostings.postings` allocation into the B4 scorer
input; a first-rejection lazy copy preserves the general callback contract. No second full-M
accepted-pair allocation occurs on the normal path. BM25, full validation, 16/48/64 logical
accounting, releases, error precedence, counts, keys, score bits, sort, projection, cursor, batch and
B1–B4 behavior are preserved. Local stable + MSRV + coverage gates pass; hosted CI/RustFS remain
pending; PR #117 stays open and unmerged.

## NEXT=independent B5 review; PERF-05-C only after that, separately gated
