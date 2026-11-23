# PERF-05-B2 — Execution Report

**Milestone:** `v0.1-perf` · **Stage:** PERF-05-B2 (reuse verified effective-live metadata across query stages)
**Branch / PR:** `dev/perf05-physical-execution-series` · PR [#117](https://github.com/yduchesne/quervant/pull/117)
**Plan of record:** [`PERF05B2_DETAILED_PLAN.md`](PERF05B2_DETAILED_PLAN.md) (verbatim copy of the approved plan)

---

## REPO / BRANCH / PR

- **Repository:** `yduchesne/quervant`
- **Branch:** `dev/perf05-physical-execution-series` (existing series branch; no new branch/PR)
- **PR:** #117 (left OPEN / draft / unmerged)

## START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA

- **START_SHA:** `668206ba1ba94fda696fb9f395b6b65023b0e1cf` (B1 head; verified ancestor)
- **MAIN_SHA:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8`
- **FINAL_SHA / REMOTE_VERIFIED_SHA:** a committed report cannot embed its own containing
  commit SHA. The single B2 commit produced from the tree validated below is reported with
  `git rev-parse HEAD`, and the remote value with
  `git rev-parse origin/dev/perf05-physical-execution-series` in the terminal agent response;
  the two were verified equal at push time. `git log -1 --format=%H dev/perf05-physical-execution-series`
  reproduces FINAL_SHA.

**Preflight (P02):** the only untracked rows were the previously recorded generated artifacts
(`.coverage`, `benchmark-results/**`, `benchmarks/quervant_bench.egg-info/**`). They were already
hidden by the B1 local-only `.git/info/exclude`; that file was **not** modified in B2. No tracked
change, index conflict, or unknown untracked path existed. No stash/reset/clean was performed.

## IMPLEMENTED_FILES (four-path allowlist)

1. `crates/quervant-core/src/search/score.rs` — private `SegmentLiveSummary`, augmented
   `SnapshotStats`, checked accessor, initial count+retain pass, `all_live` equality, B2-U01–U03.
2. `crates/quervant-core/src/search/execute.rs` — reuse-based examination helper, single call-site
   adjustment after the strict runtime guard, B2-U04–U06 and test-only legacy reference.
3. `docs/pr-artifacts/perf-05/PERF05B2_DETAILED_PLAN.md` (verbatim; `cmp` identical).
4. `docs/pr-artifacts/perf-05/PERF05B2_EXECUTION_REPORT.md` (this file).

No protected file changed: `unified.rs` (B1 shortcut intact), `work.rs`, `typed.rs`,
`unified_plan.rs`, `plan.rs`, scorer/heap, `segment/**`, `index/**`, storage/RustFS,
`Cargo.*`, `.github/**`, benchmarks/scripts and prior PERF-05 reports are untouched.

## SOURCE_CHECKS S01–S12 / INVARIANTS I01–I14

Re-verified on the live branch before editing:

- **S01** `compute_stats` initial `live.iter().try_fold(...)` counted `true` flags per segment; the
  first pass is retained and now also records the count. Confirmed.
- **S02** `SnapshotStats` had only `fields` + `field()`. Extended privately; `field()` unchanged.
- **S03** persisted-norm branch previously used `segment_live.iter().all(|flag| *flag)`. Replaced
  exactly that test with summary count==slots; partial-live and legacy branches untouched.
- **S04** old examination helper did leading / per-4096-chunk / trailing checks while counting flags.
  Retained the same poll locations, removed flag reads.
- **S05** `evaluate_lexical_with` strict shape guard precedes the helper; geometry/ordinal lookup uses
  the same `stats` and `segment_index`/`live.len()`. Signature unchanged.
- **S06** `collect_mixed` builds one `live` vector, calls `compute_stats` before segment iteration, and
  passes the same ordinal/bitmap. `unified.rs` unchanged.
- **S07** existing score fixtures (`legacy_segment_field_length_budget_is_enforced`,
  `live_bitmap_excludes_dead_documents_from_stats`, `mixed_legacy_and_norms_segments_aggregate`) reused.
- **S08** phase4 U10–U12/U14/U16 unchanged and passing.
- **S09** `MixedWorkMeter::check_cancelled` unchanged; no extra polls added to `compute_stats`.
- **S10** sibling `execute_search`/`select_keys` consumers see only the added `SnapshotStats` field;
  no behavior change.
- **S11** `build_leaf_data`/`score_segment` untouched.
- **S12** B1 callback, runtime guard and test-only membership witness preserved.

**Invariant → evidence**

| Invariant | Evidence |
|---|---|
| I01 exact per-segment counts, no `len` substitution | B2-U01/U02, phase4 U16 |
| I02 unchanged `FieldStats.n/df/avgdl/lengths` and scores | B2-U01/U02, score live/mixed tests, B1/b_tests |
| I03 `all_live` iff count==slots, incl. empty; partial branch unchanged | B2-U01/U02/U03 |
| I04 helper reads no bitmap flags; fallback unchanged | B2-U04/U05, source audit, phase4 U06–U08 |
| I05 poll schedule `1 + ceil(slots/4096) + 1` | B2-U06 (0/1/4095/4096/4097/8192/8193) |
| I06 logical charge/limits identical | B2-U05/U07, phase4 U10–U12, pr15e_b1 |
| I07 decode/validation/error order unchanged | all-features QA, pr13_oracle |
| I08 counts/keys/score bits/projection/sort/cursor | B2-U08, B1, b_tests, pr13_oracle |
| I09 wrong ordinal/geometry fails typed | B2-U03 (exact detail strings) |
| I10 no persistent/RustFS/sibling changes | pr06_local_integration, pr13_oracle; diff audit |
| I11 no global cache/unsafe/config/instrumentation | diff + grep audit; Clippy |
| I12 O(segments) fallible metadata dropped with `SnapshotStats` | §4.2 code, B2-U03, review |
| I13 B1 shortcut preserved | B1 tests green, `unified.rs` untouched |
| I14 no new fast path for batch/typed/phrase/legacy/multi-segment | B2-U02/U08, phase4 eligibility, pr15e_b1 |

## TESTS_FIRST: pre-fix missing-method red observation

- **Command:** `cargo test -p quervant-core --lib b2_u01 -- --nocapture` (B2-U01…U03 added first)
- **Result:** compile failed with `E0599: no method named verified_segment_live_count found for
  struct SnapshotStats` — exactly the prescribed API-presence RED. No fixture, import, panic or
  unrelated-error failure. **PASS-as-expected (D03).**

## PRODUCTION_DESIGN_APPLIED

- `score.rs`: `SegmentLiveSummary { slot_count, live_count }`; `SnapshotStats.segment_live:
  Vec<SegmentLiveSummary>`; `verified_segment_live_count(segment_index, bitmap_slots)` returning
  the two fixed `CorruptIndex` errors; single initial pass now counts and retains:
  `let count = bitmap.iter().filter(|flag| **flag).count() as u64;` with checked sum and fallible
  `try_reserve_exact`; persisted `all_live` from `live_count == slot_count as u64`;
  `Ok(SnapshotStats { fields, segment_live: live_summaries })`.
- `execute.rs`: `effective_live_examination_count(live, verified_live_count, meter)` keeps
  leading / per-chunk / trailing `check_cancelled()` and returns the verified count without reading
  flags; the single call site performs
  `stats.verified_segment_live_count(segment_index, live.len())?` after the strict shape guard, then
  `charge_lexical(live_count)` in its original position.
- Source audit confirms `score.rs` has exactly one `filter(|flag| **flag).count()` per bitmap, the
  persisted-norm `all_live` reads only `live_summaries[segment_index]`, and the helper contains no
  `for flag`, `iter()`, `.any` or `.all` over bitmap elements.

## FOCUSED_TESTS

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib b2_` | 6 passed (U01–U06) |
| `cargo test -p quervant-core --lib score::tests` | 11 passed |
| `cargo test -p quervant-core --lib phase4_tests` | 11 passed |
| `cargo test -p quervant-core --lib b_tests` | 20 passed |
| `cargo test -p quervant-core --test pr15e_b1` | 17 passed |
| `cargo test -p quervant-core --test pr13_oracle` | 2 passed |
| `cargo test -p quervant-core --test pr06_local_integration` | 16 passed, 3 ignored |

B2-U07/U08 are the existing phase4/b_tests/oracle suites executed unchanged (no test edits).

## REGRESSION_QA

| Command | Toolchain/topology | Result | Evidence |
|---|---|---|---|
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS | no diff |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable | PASS | clean |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | PASS | clean |
| `cargo test --workspace --all-targets` | stable, default | PASS | 2494 passed, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | stable, all features | PASS | 2539 passed, 0 failed, 94 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | stable, all features | PASS | 92.09% lines |
| `cargo doc --workspace --all-features --no-deps` | stable | PASS | docs generated |
| `cargo +1.85.0 fmt --all -- --check` | MSRV 1.85.0 | PASS | no diff |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | MSRV | PASS | clean |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | MSRV | PASS | 2539 passed, 0 failed, 94 ignored |
| `bash benchmarks/scripts/test-scripts.sh` | script self-tests | PASS | 108 passed, 0 failed |
| `cargo bench --workspace --no-run` | compile only | PASS | all bench binaries built |
| `git diff --check` | housekeeping (worktree) | PASS | clean |

**Staged whitespace check (`git diff --cached --check`):** reports trailing whitespace
**only** in `PERF05B2_DETAILED_PLAN.md`. The approved plan uses Markdown hard line breaks, and the
Phase-5 instruction requires that copy to be byte-for-byte identical (`cmp`) to the supplied file,
so those 18 trailing-space lines cannot be removed without breaking the mandated verbatim copy. The
already-committed B1 plan has the same property (14 trailing-space lines). No trailing whitespace
exists in the two Rust files or in this report. This unavoidable conflict is disclosed rather than
silently waived; the verbatim `cmp` requirement was given precedence.

## WORKSPACE_COVERAGE

- **Tool:** `cargo llvm-cov 0.9.1`, stable 1.98.1, `llvm-tools` installed.
- **Command:** `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`
- **Measured:** **92.09% line coverage** (regions 92.75%, functions 87.74%); 61,080 lines, 4,834
  missed; exit 0. No exclusions or floor changes.

## RUSTFS

- **Local real topology:** **BLOCKED** — no `QUERVANT_RUSTFS_*` environment/service present. No
  `--ignored` RustFS test was claimed as run.
- **CI:** **PENDING** — the pushed commit's pinned `rustfs` jobs have not yet run.
- **Not fabricated:** no RustFS PASS is asserted.

## EXCEPTION_MATRIX_ROWS

- **D02 (AUTO-RESOLVE)** — only previously recorded generated untracked artifacts were present and
  were already hidden by B1's local-only `.git/info/exclude`; not modified. Evidence: clean status.
- **D03 (AUTO-RESOLVE)** — tests-first RED was exactly the missing `verified_segment_live_count`
  method; implemented §4 and continued.
- **D06 (AUTO-RESOLVE)** — all S01–S12 matched; applied the exact two-file design unchanged.
- **D07 (AUTO-RESOLVE)** — used the fixed `live_summaries` local binding and private
  `segment_live` field exactly as prescribed.
- **D08 (AUTO-RESOLVE)** — one rustfmt wrap inside newly added score tests; ran `cargo fmt --all`
  (diff confined to `score.rs`/`execute.rs`) and reran affected QA.
- **D13 (DEFER AND CONTINUE)** — RustFS local service absent; recorded BLOCKED/PENDING, completed
  independent local QA, did not wait or fabricate.
- **D22 (DEFER AND CONTINUE)** — local gates pass; CI/RustFS pending, so the disposition is
  local-pass/CI-pending, not final acceptance.
- **D24 boundary (documented conflict)** — the required byte-for-byte (`cmp`) plan copy conflicts
  with a clean staged `git diff --cached --check`, because the approved plan itself contains
  Markdown hard-break trailing spaces. Resolution: preserve the verbatim copy (higher-priority,
  explicitly mandated, and consistent with the committed B1 plan) and disclose the staged-check
  output above instead of editing the plan or disabling the check.

No HARD-STOP row (D01, D04–D05, D09–D12, D15, D17–D19, D21, D24–D25) was triggered.

## CI

**PENDING at report time.** No workflow was dispatched, polled or modified; B1 CI is not asserted as
passed. B2 local evidence stands independently.

## OPEN_GATES / RESIDUAL_RISKS / FAILURE_CLASSIFICATION

**Open gates:** hosted CI for the pushed commit; pinned RustFS acceptance
(`pr13_oracle --ignored`, `pr15g_b_rustfs --ignored`); independent reviewer checklist and maintainer
acceptance.

**Residual risks:** the safety argument depends on `compute_stats` and the postings enumeration
consuming the same immutable `live` vector and segment ordinal (verified here via S06); a future
change to that provenance relationship requires a plan amendment. The added O(segments) metadata is
unmetered by the existing statistics-setup pattern (no new peak-memory charge is introduced or
claimed). No performance improvement is measured or claimed.

**Failure classification:** all executed commands passed. No introduced regression, implementation
defect, pre-existing failure, flake, or environment/harness failure was observed. RustFS/CI are
environment-gated pending, not failures.

## NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE

No timed benchmark, `quervant-bench run`, `perf record`, `perf script`, CPU sampling, microbenchmark,
A/A, A/B, idle probe or profiler preflight was run. `cargo bench --workspace --no-run` is compile-only.

## B2_DISPOSITION

**`B2_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING`**

The exact §§4–5 design is implemented on the four-path allowlist; B2-U01–U06 pass; B1, score,
phase4, b_tests, local integration and oracle regressions pass; stable + MSRV full workspace QA and
≥85% coverage pass locally. Hosted CI and real pinned RustFS remain pending; PR #117 stays open,
draft and unmerged.

## NEXT

Independent B2 review against the plan's §10 checklist, then CI/RustFS acceptance. **B3 is not
authorized by this report.**
