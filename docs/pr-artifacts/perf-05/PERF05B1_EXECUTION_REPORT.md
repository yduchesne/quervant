# PERF-05-B1 — Execution Report

**Milestone:** `v0.1-perf` · **Stage:** PERF-05-B1 (redundant single-term membership re-lookup)
**Branch / PR:** `dev/perf05-physical-execution-series` · PR [#117](https://github.com/yduchesne/quervant/pull/117)
**Plan of record:** [`PERF05B1_DETAILED_PLAN.md`](PERF05B1_DETAILED_PLAN.md) (verbatim copy of the approved plan)

---

## REPO / BRANCH / PR

- **Repository:** `yduchesne/quervant`
- **Branch:** `dev/perf05-physical-execution-series` (existing series branch; no new branch/PR created)
- **PR:** #117 (left open and unmerged)

## START_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA / MAIN_SHA

- **START_SHA:** `0bd712dee5bfbc378e7c9830e83a104997be1529`
- **MAIN_SHA:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8`
- **FINAL_SHA:** the single PERF-05-B1 commit produced from the tree validated below; recorded as
  `git rev-parse HEAD` on the pushed branch. (A file cannot embed the hash of the commit that
  contains it; the exact value is reported in the PR execution summary / terminal report and is
  reproducible with `git log -1 --format=%H dev/perf05-physical-execution-series`.)
- **REMOTE_VERIFIED_SHA:** verified post-push with `git rev-parse origin/dev/perf05-physical-execution-series`;
  equals FINAL_SHA at push time.

**Preflight note (housekeeping only):** the checkout initially carried three pre-existing
*untracked* generated artifacts (`.coverage`, `benchmark-results/`, `benchmarks/quervant_bench.egg-info/`).
They are not tracked on `main` or on the series branch. To satisfy the clean-tree preflight without
discarding user data they were added to the **local-only** `.git/info/exclude` (never a tracked
file, never committed). No tracked local change existed; no stash/reset/discard was performed.

## IMPLEMENTED_FILES (exact list)

1. `crates/quervant-core/src/search/unified.rs`
   - One production conditional inside the existing `collect_mixed()` `is_match` callback.
   - New B1 tests in the existing `#[cfg(test)] mod phase4_tests`.
2. `crates/quervant-core/src/search/execute.rs`
   - `#[cfg(test)]`-only term-membership witness in `test_observation`.
   - `#[cfg(test)]`-only counter call in `LeafData::matches` `Self::Term` arm.
   - Production `LeafData::matches` algorithm unchanged.
3. `docs/pr-artifacts/perf-05/PERF05B1_DETAILED_PLAN.md` (verbatim approved plan; `cmp` identical).
4. `docs/pr-artifacts/perf-05/PERF05B1_EXECUTION_REPORT.md` (this file).

No other tracked path changed. `Cargo.toml`/`Cargo.lock`, `.github/**`, benchmarks, scorers, heap,
codecs, readers/writers, storage/RustFS and `evaluate_lexical_with` were not modified.

## SOURCE_PROOF_CHECKS: S01–S10; INVARIANTS: I01–I12

Re-verified on the checked-out source at START_SHA before editing:

- **S01 `single_term_postings_eligible` (`unified.rs:120`)** — true only for root `Lexical(0)`, exactly
  one lexical leaf, one analyzed term, no typed leaves, exactly one positive lexical leaf index 0,
  no aggregation, no `after` cursor. Sorting is deliberately unrestricted. Confirmed.
- **S02 `collect_mixed` (`unified.rs:619`)** — computes `postings_candidate_eligible`, passes it to
  `execute::evaluate_lexical_with`, whose `is_match` builds `TypedCharge` + `ScanGuard` and calls
  `evaluate_unified`. Confirmed; the only behavioral edit is inside that callback.
- **S03 `evaluate_lexical_with` (`execute.rs:1936`)** — eligible branch validates
  `[LeafData::Term { terms, .. }]` with `terms.len() == 1 && !typed_examination` **before** iterating
  and **before** invoking `is_match`; otherwise returns `SearchError::CorruptIndex`. Confirmed guard
  precedes the callback.
- **S04 `build_leaf_data` (`execute.rs:1256`) / `TermPostings` (`execute.rs:908`)** — decoder order is
  strictly ascending, resource-charged, bounds-checked, effective-live filtered; no reordering.
  Confirmed.
- **S05 `LeafData::matches` (`execute.rs:923`)** — `Self::Term` binary-searches the same sorted
  postings. Generic production routine unchanged; only a `#[cfg(test)]` counter call was added.
- **S06 `evaluate_unified` (`unified.rs:2130`)** — `UnifiedNode::Lexical(index)` only reads the leaf and
  calls `leaf.matches(doc_id)`; no work charge, state change, or fallible operation. Confirmed, so
  returning `true` for the already-proven shape has no side effects.
- **S07 `ScanGuard::shared` (`typed.rs:179`)** — constructor only borrows the shared work meter; no
  charge without typed predicates. Construction is preserved at the callback site.
- **S08 `mod phase4_tests` (`unified.rs:4342`)** — real analyzer→writer→commit→reader→search fixtures
  and eligibility/visitation/work/cancellation/cursor regressions. Reused; not rewritten.
- **S09 `mod test_observation` (`execute.rs:1787`)** — existing `PREDICATE_CALLS` witness; extended in
  the same test-only module with `TERM_MEMBERSHIP_LOOKUPS`.
- **S10 `mod b_tests` (`unified.rs:4877`)** — one-term vs `And` parity already includes count, key
  order, score bits, null/ties and two segments. Reused as regressions.

**Invariant → acceptance evidence**

| Invariant | Evidence |
|---|---|
| I01 Exact hits | B1-U01/U03 (exact `total_hits`, K truncation), phase4 U09 |
| I02 No redundant lookup | B1-U01/U02/U03 (direct = 0 lookups, M callbacks) |
| I03 Fallback unchanged | B1-U04 (expanded / mixed typed), phase4 U01–U05, cursor test |
| I04 Scores bit-identical | B1-U01/U03 (`to_bits()` parity), `b_tests::b_u12_two_segment_score_bits` |
| I05 Determinism/order | B1-U01 (keys/fields), `b_tests::b_u01_u08_u36...`, `b_u06_u09_u10...`, `b_u07_utf8_ordering` |
| I06 Work/budget | `phase4_u10_u11_u12_work_charge_parity` |
| I07 Cancellation | `phase4_u14_cancellation_unwinds_cleanly` |
| I08 Corruption/error | S03 runtime guard untouched; full `execute` corruption suites |
| I09 Batch & aggregation | `phase4_u01_u05_eligibility_matrix` (aggregation disables branch), `pr15e_b1` batch parity |
| I10 Snapshot/topology | Read-only callback; `pr06_local_integration`, `pr13_oracle`, `pr15e_b1`; no storage change |
| I11 No production instrument | `#[cfg(test)]` only; default/all-features Clippy + tests clean |
| I12 Baseline defaults | Diff audit: no change to Top-K prefilter or keyword sort gate |

## RED_FIRST: command, expected-vs-actual assertion, status

- **Command:** `cargo test -p quervant-core --lib phase4_b1_u01_u02 -- --nocapture`
- **State:** witness + test added, §4 production fix **not** yet applied.
- **Expected:** eligible direct path reports **4** term-membership lookups (asserted 0) → RED.
- **Actual:** `assertion left == right failed  left: 4  right: 0` at
  `phase4_tests::phase4_b1_u01_u02_proven_term_skips_relookup_with_fallback_parity`. Test compiled
  and failed **only** on the lookup count; no unrelated assertion, panic, or harness error.
- **Status:** **PASS-as-expected** (exception row D03).

## GREEN: command, test count, status

- **Command:** `cargo test -p quervant-core --lib phase4_b1_u01_u02 -- --nocapture`
- **Result:** 1 passed, 0 failed. Direct = 0 lookups, 4 callbacks; wrapped fallback = 40 lookups,
  40 callbacks; keys / count / score bits / projection parity.
- **Status:** **PASS**.

## TESTS: command | toolchain/topology | PASS/FAIL/BLOCKED/NOT_APPLICABLE | evidence

| Command | Toolchain / topology | Result | Evidence |
|---|---|---|---|
| `cargo test -p quervant-core --lib phase4_b1 -- --nocapture` | stable 1.98.1, in-crate real index | PASS | 3 passed |
| `cargo test -p quervant-core --lib phase4_tests -- --nocapture` | stable 1.98.1 | PASS | 11 passed |
| `cargo test -p quervant-core --lib b_tests -- --nocapture` | stable 1.98.1 | PASS | 20 passed |
| `cargo test -p quervant-core --test pr06_local_integration` | stable 1.98.1, real `FsDirectory`/`MemoryDirectory` lifecycle | PASS | 16 passed, 3 ignored |
| `cargo test -p quervant-core --test pr13_oracle` | stable 1.98.1, independent-expectation oracle | PASS | 2 passed |
| `cargo test -p quervant-core --test pr15e_b1` | stable 1.98.1, batch/standalone parity | PASS | 17 passed |
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS | no diff |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable 1.98.1 | PASS | clean |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable 1.98.1 | PASS | clean |
| `cargo test --workspace --all-targets` | stable 1.98.1, default features | PASS | 2488 passed, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | stable 1.98.1, all features | PASS | 2533 passed, 0 failed, 94 ignored |
| `cargo doc --workspace --all-features --no-deps` | stable 1.98.1 | PASS | docs generated |
| `cargo +1.85.0 fmt --all -- --check` | MSRV 1.85.0 | PASS | no diff |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | MSRV 1.85.0 | PASS | clean |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | MSRV 1.85.0, all features | PASS | 2533 passed, 0 failed, 94 ignored |
| `bash benchmarks/scripts/test-scripts.sh` | script self-tests (no timed benchmark) | PASS | 108 passed, 0 failed |
| `git diff --check` | repository housekeeping | PASS | no whitespace errors |

**RustFS ignored tests:** the `--all-features` suites report 94 ignored tests, including the pinned
RustFS integration tests (`pr13_proxy_rustfs`, `pr13_s3_rustfs`, and the RustFS oracle target). They
are `#[ignore]`-gated and require a running pinned service; see `RUSTFS` below.

## WORKSPACE_COVERAGE: real percentage or BLOCKED

- **Command:** `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`
- **Toolchain:** stable 1.98.1, `cargo-llvm-cov 0.9.1`, `llvm-tools` installed.
- **Result:** **92.07% line coverage** (regions 92.73%, functions 87.73%); total 60,862 lines with
  4,828 missed. Exit code 0 (≥85% floor). No exclusions or floor changes applied.

## RUSTFS: service/execution/CI status, do not invent PASS

- **Local real-service execution:** **BLOCKED** — no `QUERVANT_RUSTFS_*` environment was present in
  this environment; the pinned RustFS service was not provisioned (and was not to be provisioned).
- **CI:** **PENDING** — the pushed commit's `rustfs` CI jobs have not yet run; they must execute
  `pr13_oracle --ignored` and `pr15g_b_rustfs --ignored` under the pinned service.
- **Not fabricated:** no RustFS result is claimed as PASS. The ignored tests were *not* invoked with
  `--ignored` locally.

## EXCEPTION_MATRIX_ROWS: trigger, action, evidence (or NONE)

- **D02 (AUTO-RESOLVE)** — source matched S01–S10; applied §4 verbatim inside the existing callback
  and continued. Evidence: unified.rs diff.
- **D03 (AUTO-RESOLVE)** — red-first failed exactly with 4 direct lookups vs 0; applied §4 and
  continued to GREEN. Evidence: RED/GREEN commands above.
- **D06 (AUTO-RESOLVE)** — a single Rustfmt line-wrap finding in the newly added B1 test; ran
  `cargo fmt --all` (diff confined to `unified.rs`), re-verified `--check` and all affected gates.
- **D13 (DEFER AND CONTINUE)** — `cargo llvm-cov` and MSRV were present and passed; the real RustFS
  service was unavailable locally, so it is reported BLOCKED/PENDING rather than faked.
- **D20 (DEFER AND CONTINUE)** — all local gates pass; hosted CI / real RustFS remain pending, so the
  disposition is the local-pass/CI-pending stage, not final acceptance.

No HARD-STOP row (D01, D04–D05, D07–D10, D15–D16, D19, D22) was triggered.

## OPEN_GATES / RESIDUAL_RISKS / FAILURE_CLASSIFICATION

**Open gates**

1. Hosted CI for the pushed commit (all jobs, including `cargo bench --no-run` compile-only).
2. Pinned RustFS CI acceptance (`pr13_oracle --ignored`, `pr15g_b_rustfs --ignored`) — **PENDING**.
3. Independent reviewer checklist (§11 of the plan) and maintainer acceptance.

**Residual risks**

- The safety argument depends on S01/S03 remaining the sole gate for the postings branch; any future
  widening of eligibility or movement of the runtime guard invalidates the proof and requires a plan
  amendment.
- The test-only witness is `#[cfg(test)]`; it cannot observe release/benchmark builds by design.
- No performance improvement is measured or claimed here (PERF-05-C owns acquisition).

**Failure classification:** all executed commands passed. No introduced regression, implementation
defect, pre-existing failure, flake, or environment failure was observed in the run. RustFS/CI are
**environment-gated pending**, not failures.

## NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE

No timed A/B campaign, `quervant-bench run`, `perf record`, `perf script`, CPU profiling, custom
microbenchmark, or host-idle probe was executed. Only correctness/build/documentation and the
compile-only script self-tests ran.

## B1_DISPOSITION and reasons

**`B1_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING`**

Reasons: the single authorized production conditional is implemented; the test-only witness proves
zero redundant lookups in the eligible path and preserved lookups on ineligible controls; red→green
is demonstrated; full stable + MSRV workspace QA and ≥85% coverage pass locally. Hosted CI and the
real pinned RustFS acceptance are still pending, so B1 is not claimed as finally accepted and PR #117
remains open/unmerged.

## NEXT=independent review; B2 not authorized by this report

Next step is independent review against the plan's §11 checklist, followed by CI/RustFS acceptance.
PERF-05-B2 is **not** started or authorized by this report.
