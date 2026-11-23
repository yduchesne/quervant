# PERF-05-B3 — Execution Report

**Milestone:** `v0.1-perf` · **Stage:** PERF-05-B3 (replace unified matched-document tree with an ordered vector)
**Branch / PR:** `dev/perf05-physical-execution-series` · PR [#117](https://github.com/yduchesne/quervant/pull/117)
**Plan of record:** [`PERF05B3_DETAILED_PLAN.md`](PERF05B3_DETAILED_PLAN.md) (verbatim copy of the approved plan)

---

## REPO / BRANCH / PR

- **Repository:** `yduchesne/quervant`
- **Branch:** `dev/perf05-physical-execution-series` (existing series branch; no new branch/PR)
- **PR:** #117 (OPEN / draft / unmerged)

## START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA

- **START_SHA:** `dfa876c52d5227087ee2085525f64f9ce97600ed` (B2 head; B1 `668206b…` and B2 both
  verified ancestors)
- **MAIN_SHA:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8`
- **FINAL_SHA / REMOTE_VERIFIED_SHA:** a committed report cannot contain its own containing commit
  SHA. Retrieve with `git rev-parse HEAD` (FINAL_SHA) and
  `git rev-parse origin/dev/perf05-physical-execution-series` (remote); the two were verified equal
  at push time and are also stated in the terminal agent response.

**Preflight (D02):** status was clean. The previously recorded generated artifacts
(`.coverage`, `benchmark-results/**`, `benchmarks/quervant_bench.egg-info/**`) remain hidden by the
B1/B2 local-only `.git/info/exclude`; it was not modified. No tracked change, conflict or unknown
untracked path existed.

## IMPLEMENTED_FILES: 4-path exact allowlist

1. `crates/quervant-core/src/search/execute.rs` — `score_segment` input seam, two call-site
   `.iter()` adaptations, unified `Vec<u64>` matched collection + two appends, B3-U01/U02 tests and
   test-only adapter.
2. `crates/quervant-core/src/search/unified.rs` — **test only**: `phase4_b3_u03_…` in
   `phase4_tests`. Production B1 logic byte-identical to B2.
3. `docs/pr-artifacts/perf-05/PERF05B3_DETAILED_PLAN.md` (verbatim; `cmp` identical, 0 trailing
   spaces).
4. `docs/pr-artifacts/perf-05/PERF05B3_EXECUTION_REPORT.md` (this file).

No other tracked file changed. `score.rs`, `work.rs`, `typed.rs`, `plan.rs`, `unified_plan.rs`,
codecs/readers, RustFS, top-K/sort/duplicate, Cargo manifests, CI, benchmarks and B1/B2 reports are
untouched.

## SOURCE_PROOF_CHECKS S01–S13 / INVARIANTS I01–I16

Re-verified on the pulled B2 head before editing:

- **S01** `evaluate_lexical_with` declared `BTreeSet<u64>` with two `insert` arms; reserved
  `len()*SET_BYTES_PER_ENTRY`, passed `&matched` to `score_segment`, dropped it before release.
- **S02** Eligible branch: strict one-term shape guard + B2 verified-live helper, then a validated
  strictly ascending effective-live postings stream; B1 shortcut proves membership true.
- **S03** Fallback branch: ascending `live.iter().enumerate()`, each physical index once.
- **S04** `build_leaf_data`/`TermPostings` decode rejects nonincreasing IDs; no reordering.
- **S05** `score_segment` used the input only for `len()` and one map-seeding iteration.
- **S06** `execute_segment_inner` keeps its own `eval_node`/`ReservedSet` BTreeSet and passes
  `&matches.set` to the same scorer.
- **S07** `SET_BYTES_PER_ENTRY=48`, `SCORED_MAP_BYTES_PER_ENTRY=64`; charge site/time unchanged.
- **S08** `SegmentCandidateLedger`/`CandidateBudget`/RAII unchanged.
- **S09** `unified.rs::collect_mixed` caller/API unchanged (no production edit).
- **S10** Exactly two production `score_segment` call sites (sibling + unified); confirmed by grep.
- **S11** Existing `budget_tests`, `phase4_tests`, `b_tests` reused and extended, not rewritten.
- **S12** `score.rs::SnapshotStats` consumed unchanged; B2 cache retained.
- **S13** `BTreeSet::iter()` and `Vec::iter()` both satisfy `ExactSizeIterator<Item=&u64>`;
  `Option::is_none_or` is available on MSRV 1.85 (verified by MSRV build/tests).

**Invariant → evidence**

| Invariant | Evidence |
|---|---|
| I01 once, strictly ascending | §4.2 debug asserts, source audit, B3-U03, phase4 visitation |
| I02 no nonmatching/deleted IDs | phase4 U06–U08/U16, oracle |
| I03 enumerators/callback/B1 unchanged | phase4 B1-U01–U04 |
| I04 one scorer for both inputs | B3-U01/U02, sibling integration tests |
| I05 score bits unchanged | B3-U02, `b_tests::b_u12…`, `score::tests` |
| I06 hits/K/keys/sort/projection | B3-U03, phase4 U09 |
| I07 `SET_BYTES_PER_ENTRY=48` charge/site | B3-U01 charges, source diff, `c2_*` |
| I08 scored-map/heap/budget limits | B3-U01, `budget_tests`, `pr15e_b1` |
| I09 cancellation polls unchanged | B2-U06, phase4 U14 |
| I10 decode/validation not skipped | untouched `build_leaf_data`/`score_segment`, all-features suites |
| I11 sibling BTreeSet/eval_node intact | §4.1 call site A, oracle regressions |
| I12 typed/phrase/negation/mixed/cursor | unified fallback untouched, phase4 U01–U05 |
| I13 no sort/dedup/O(M) temp | source audit (`matched.push` only) |
| I14 conservative logical limits kept | source review + candidate budget tests |
| I15 no API/persistent/CI/benchmark changes | diff audit, stable/MSRV |
| I16 B1/B2 preserved | diff vs START_SHA, B1/B2 regressions |

## TESTS_FIRST RED

- **Command:** `cargo test -p quervant-core --lib b3_u01_scorer_accepts_tree_and_vec_iterators -- --nocapture`
- **Expected:** single type mismatch because the old `score_segment` required `&BTreeSet<u64>`.
- **Actual:** `error[E0308]: mismatched types … expected &BTreeSet<u64>, found type parameter impl
  ExactSizeIterator<Item=&u64>` — exactly one diagnostic, no unrelated errors. **PASS-as-expected
  (D05).**

## PRODUCTION_CHANGE

- `score_segment<'a>(matches: impl ExactSizeIterator<Item = &'a u64>, …)`; only the map-seeding
  expression changed to `matches.map(|doc| (*doc, 0.0))`. Body, BM25 loops, `scores.is_empty()`,
  charges and return unchanged.
- Sibling call site: `matches.set.iter()` (only change).
- Unified call site: `matched.iter()` (only change).
- Unified matched collection: `let mut matched: Vec<u64> = Vec::new();` and two success arms now
  `debug_assert!(matched.last().is_none_or(...)); matched.push(...)`, one per enumerator.
- `SET_BYTES_PER_ENTRY = 48` logical charge retained at the original site with `matched.len()`;
  reserve/drop/release order unchanged. Sibling `ReservedSet`/`eval_node` and scored `BTreeMap`
  unchanged.

## GREEN + FOCUSED_TESTS

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib b3_` | 3 passed (U01/U02/U03) |
| `cargo test -p quervant-core --lib phase4_tests` | 12 passed |
| `cargo test -p quervant-core --lib b_tests` | 20 passed |
| `cargo test -p quervant-core --lib budget_tests` | 45 passed |
| `cargo test -p quervant-core --lib score::tests` | 11 passed |
| `cargo test -p quervant-core --lib b2_` | 6 passed |
| `cargo test -p quervant-core --test pr13_oracle` | 2 passed |
| `cargo test -p quervant-core --test pr15e_b1` | 17 passed |
| `cargo test -p quervant-core --test pr06_local_integration` | 16 passed, 3 ignored |

## REGRESSION_QA

| Command | Toolchain/topology | Result | Evidence |
|---|---|---|---|
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS | clean |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable | PASS | clean |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | PASS | clean |
| `cargo test --workspace --all-targets` | stable default | PASS | 2497 passed, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | stable all-features | PASS | 2542 passed, 0 failed, 94 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | stable | PASS | 92.10% lines |
| `cargo doc --workspace --all-features --no-deps` | stable | PASS | docs generated |
| `cargo +1.85.0 fmt --all -- --check` | MSRV 1.85.0 | PASS | clean |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | MSRV | PASS | clean |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | MSRV | PASS | 2542 passed, 0 failed, 94 ignored |
| `cargo bench --workspace --no-run` | compile only | PASS | all bench binaries built |
| `bash benchmarks/scripts/test-scripts.sh` | script self-tests | PASS | 108 passed, 0 failed |
| `git diff --check` | housekeeping | PASS | clean |

## WORKSPACE_COVERAGE

- **Tool:** `cargo llvm-cov 0.9.1`, stable 1.98.1, `llvm-tools` installed.
- **Measured:** **92.10% line coverage** (regions 92.78%, functions 87.77%); 61,229 lines, 4,835
  missed; exit 0, no exclusions or floor change.

## REAL_LOCAL_FS / RUSTFS / CI

- **Real local FsDirectory path:** PASS — `pr06_local_integration` (16 passed, 3 ignored) and
  `pr13_oracle` (2 passed) over real writer/commit/reopen/query.
- **RustFS:** **LOCAL_BLOCKED** — no `QUERVANT_RUSTFS_*` service present; `--ignored` RustFS tests
  were not run and are not claimed.
- **CI:** **PENDING** — pushed commit's hosted jobs have not run; not asserted as passed.

## EXCEPTION_MATRIX_ROWS

- **D02 (AUTO-RESOLVE)** — only previously recorded generated untracked artifacts present, already
  locally excluded; untouched.
- **D03 (AUTO-RESOLVE)** — B1/B2 are ancestors; proceeded without waiting for their CI; recorded
  pending.
- **D04 (AUTO-RESOLVE)** — exactly two `score_segment` call sites and input used for `len`+seed only;
  applied the exact seam.
- **D05 (AUTO-RESOLVE)** — B3-U01 RED was exactly E0308 from the old `&BTreeSet` input; applied §4.1
  and continued.
- **D07 (AUTO-RESOLVE)** — both enumerators prove ascending uniqueness; replaced only the unified
  declaration and two inserts.
- **D13 (AUTO-RESOLVE)** — rustfmt wraps confined to the new B3 test in `unified.rs`; ran
  `cargo fmt --all`, inspected diff, reran affected QA.
- **D14 (AUTO-RESOLVE)** — plan copied byte-for-byte, whitespace-clean; staged diff clean.
- **D16 (DEFER AND CONTINUE)** — RustFS unavailable / CI pending; completed local QA and pushed a
  truthful pending report.
- **D19 (AUTO-RESOLVE)** — plain `Vec::new()`/`push`; no preallocation, sort, dedup or per-match
  reserve.
- **D22 (AUTO-RESOLVE)** — no intervening non-doc commits; START was exact B2 head.
- **D24 (AUTO-RESOLVE)** — local gates pass, scope/whitespace clean; pushed and reported local-pass/
  CI-pending.

No HARD-STOP row was triggered.

## OPEN_GATES / RESIDUAL_RISKS / FAILURE_CLASSIFICATION

**Open gates:** hosted CI for the pushed commit; pinned RustFS acceptance
(`pr13_oracle --ignored`, `pr15g_b_rustfs --ignored`); independent reviewer checklist.

**Residual risks:** the ascending-unique argument depends on the current eligible/fallback
enumerators; a future enumeration shape change requires review. The `Vec` has a different physical
allocation pattern than `BTreeSet` while retaining the conservative `SET_BYTES_PER_ENTRY` logical
charge; allocator OOM behavior is an environmental limitation. No latency/throughput improvement is
measured or claimed (PERF-05-C).

**Failure classification:** all executed commands passed. No introduced regression, B3 feature
defect, pre-existing failure, flake, or environment/harness failure was observed. RustFS/CI are
environment-gated pending, not failures.

## NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE

No timed benchmark, `quervant-bench run`, `perf record`, `perf script`, CPU sampling, microbenchmark,
A/A, A/B, idle probe or profiler preflight was run. `cargo bench --workspace --no-run` is
compile-only and `benchmarks/scripts/test-scripts.sh` is script self-tests.

## B3_DISPOSITION

**`B3_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING`**

One shared scorer now accepts an exact-sized iterator from either the sibling `BTreeSet` or the
unified ordered `Vec<u64>`; the unified matched tree and its two inserts are removed; all logical
charges, cancellation polls, BM25, counts, keys, sort, projection and B1/B2 behavior are preserved;
local stable + MSRV + coverage gates pass. Hosted CI/RustFS remain pending; PR #117 stays open,
draft and unmerged.

## NEXT=independent review; B4 NOT STARTED
