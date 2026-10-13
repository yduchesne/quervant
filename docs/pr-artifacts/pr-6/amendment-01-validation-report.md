# PR 6 Amendment 01 validation report

> **Validated code commit:** `f7a1715290d399d9c17fdeab17f812a6db3f000c`
> (branch `dev/pr06-writer-lifecycle`, parent `e1ef195`)
> **Tested tree:** the clean worktree at that commit. This report and the
> amendment prose were committed in a docs-only follow-up; no code changed
> between that commit and the QA runs below.
> **Toolchains:** stable `1.98.1`; MSRV `1.85.0`; `cargo-llvm-cov` with
> `llvm-tools-preview` for both.
> **No merge performed.** CI has not run for a pushed head SHA.

## 1. Command results (final committed SHA)

| # | Command | Toolchain | Result |
|---|---|---|---|
| 1 | `git rev-parse HEAD` | — | `f7a1715290d399d9c17fdeab17f812a6db3f000c` |
| 2 | `cargo +1.85.0 fmt --all -- --check` | MSRV | PASS |
| 3 | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | MSRV | PASS |
| 4 | `cargo +1.85.0 test --workspace --all-targets` | MSRV | PASS — **859 passed, 0 failed, 6 ignored** |
| 5 | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | MSRV | PASS — **92.27 % lines** |
| 6 | `cargo +1.85.0 doc --workspace --no-deps` | MSRV | PASS |
| 7 | `cargo fmt --all -- --check` | stable | PASS |
| 8 | `cargo clippy --workspace --all-targets -- -D warnings` | stable | PASS |
| 9 | `cargo test --workspace --all-targets` | stable | PASS — **859 passed, 0 failed, 6 ignored** |
| 10 | `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | PASS — **91.94 % lines** |
| 11 | `cargo doc --workspace --no-deps` | stable | PASS |
| 12 | `git diff --check` | — | PASS |

Coverage header: `Regions / Functions / Lines / Branches`. Both runs have zero
instrumented branches. The earlier PR 6 report labelled the Regions figure as
"lines"; the correct line figures there were 91.98 % (stable) and 92.30 % (MSRV).
This amendment reports the true Lines column and leaves the historical file
unmodified.

## 2. Targeted PR 6 suites

| Suite | Result |
|---|---|
| `pr06_lifecycle_unit` (U01–U17) | 18 passed |
| `pr06_local_integration` (I01–I12) | 13 passed, 3 ignored child entry points (spawned by parents) |
| `pr06_faults` (F01–F16) | 17 passed |
| `pr06_amendment_01` (T01–T25) | 16 passed, 1 ignored separate-process child (`t02_child_commits_gen2`, spawned by its parent) |

The ignored tests are child-process entry points executed by their parent tests;
they are not counted as independent acceptance passes or silently treated as
PASS.

## 3. T01–T25 outcomes

| Test | Status | Evidence |
|---|---|---|
| T01 sequential writers reload generation | PASS | `t01_sequential_writers_reload_committed_generation` |
| T02 stale opened handle reloads CURRENT (in-process) | PASS | `t02_stale_opened_handle_reloads_current` |
| T02 stale handle across a separate process | PASS | `t02_stale_handle_reloads_current_across_process` + child |
| T03 created handle reloads first commit | PASS | `t03_created_handle_reloads_first_commit` |
| T04 corrupt CURRENT prevents admission | PASS | `t04_corrupt_current_prevents_writer_admission` |
| T05 exact aggregate limit succeeds | PASS | `t05_exact_aggregate_snapshot_limit_succeeds` |
| T06 aggregate over-limit rejects before reads | PASS | counting `Directory` asserts zero segment opens |
| T07 individual oversize rejects before reads | PASS | counting `Directory` asserts zero segment opens |
| T08 checked-total overflow | PASS | `support.rs::bounded_total_detects_overflow` |
| T09 failed delete keeps guard unreleased / retry | PASS | `writer.rs::t09_failed_delete_keeps_guard_unreleased_and_retry_succeeds` |
| T10 failed release blocks competing writer | PASS | `t10_failed_release_does_not_admit_second_writer` |
| T11 `close(self)` failure + Drop retry (one-time) | PASS | `t11_close_failure_drop_retry_releases_one_time_failure`; permanent case in `t10` |
| T12–T14 session-qualified distinct PIT ids / no leak | PASS | `t12_pit_ids_are_session_qualified_and_distinct` |
| T15 ordinal exhaustion rollback | PASS | `pit.rs::pin_ordinal_exhaustion_does_not_leak` |
| T16 exact reader-copy budget | PASS | `t16_t17_t18_managed_reader_copy_budget` |
| T17 second simultaneous copy rejects before clone | PASS | same test; first reader still usable |
| T18 budget reusable after drop | PASS | same test |
| T19 decoder failure releases reservation | PASS | `snapshot.rs::decoder_failure_releases_reservation` |
| T20 independent guarded readers during commit | PASS | `t20_independent_guarded_readers_survive_concurrent_commit` |
| T21 old PIT guarded reader survives commit | PASS | `t21_old_pit_guarded_reader_survives_commit` (and I10) |
| T22 PR 5 golden byte-identical | PASS | `t22_pr5_golden_fixture_is_byte_identical`; SHA `ebb07800…dae979` |
| T23 CURRENT/manifest/segment encoding unchanged | PASS | existing codec/golden suites green; no codec edits |
| T24 commit/recovery fault semantics preserved | PASS | F01–F16 unchanged and green |
| T25 no unmetered managed reader path | PASS | `t25_out_of_range_guarded_read_is_typed`; static source audit (below) |

## 4. Independent oracles used

- Stale-handle tests read the committed stored-key set rather than trusting a
  writer return value.
- T06/T07 count real `Directory::open_read` calls for segment keys and assert
  **zero** before the aggregate/individual rejection.
- T09–T11 count real `Directory::delete` calls to distinguish "marked released"
  from "deleted".
- T15 uses a local private ordinal counter at `u64::MAX-1`, so it neither mutates
  the process-global session sequence nor depends on test order.
- `support::bounded_segment_total` is tested directly for arithmetic overflow
  rather than fabricating an invalid persisted length.

## 5. Static API audit (T25)

`rg "SegmentSnapshot::reader|\.reader\(" crates/quervant-core/src` shows:
`ReaderSnapshot::open_segment_reader` is the only managed segment-reader entry
point; `IndexWriter::reader` and `Index::snapshot` are snapshot handles, not
segment readers. `SegmentSnapshot::reader` no longer exists. Raw
`SegmentSnapshot::bytes`/`shared_bytes` remain public and are explicitly
**not** budget-enforced (documented residual risk).

## 6. Failures, classification and deviations

- No failing tests. No introduced regression, amendment defect, pre-existing
  failure, flake or harness failure was observed.
- No deviation from the plan's binding design decisions and no STOP condition
  applied.
- `cargo-llvm-cov` ran on both toolchains; the coverage gate is not BLOCKED.
- GitHub Actions is **BLOCKED/unverified** because the branch has not been
  pushed; this is recorded, not reported as green.

## 7. Completion status separation

- Implementation: complete for the amendment scope.
- Tests exist / executed / pass: yes, on both toolchains.
- Local QA and coverage gates: pass.
- PR readiness: ready for review; no merge without explicit approval.
- Roadmap PR 6: **not** marked DONE.
