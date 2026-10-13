# PR 6 Amendment 02 validation report

> **Validated code commit:** `ca89ec9cedfc186d668c195d82583858da0cebcf`
> (branch `dev/pr06-writer-lifecycle`, parent `321147f`; Amendment 01 code
> `f7a1715`; original PR 6 `e1ef195`; base `569f4a4`).
> **Tested tree:** the clean worktree at that commit. This report and the
> amendment prose were committed in a docs-only follow-up; no code changed
> between that commit and the QA runs below.
> **Toolchains:** stable `1.98.1`; MSRV `1.85.0`; `cargo-llvm-cov` with
> `llvm-tools-preview` for both.
> **No merge performed.** CI has not run for a pushed head SHA.

## 1. Command results (final committed SHA)

| # | Command | Toolchain | Result |
|---|---|---|---|
| 1 | `git rev-parse HEAD` | — | `ca89ec9cedfc186d668c195d82583858da0cebcf` |
| 2 | `cargo +1.85.0 fmt --all -- --check` | MSRV | PASS |
| 3 | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | MSRV | PASS |
| 4 | `cargo +1.85.0 test --workspace --all-targets` | MSRV | PASS — **874 passed, 0 failed, 7 ignored** |
| 5 | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | MSRV | PASS — **92.33 % Lines** |
| 6 | `cargo +1.85.0 doc --workspace --no-deps` | MSRV | PASS |
| 7 | `cargo fmt --all -- --check` | stable | PASS |
| 8 | `cargo clippy --workspace --all-targets -- -D warnings` | stable | PASS |
| 9 | `cargo test --workspace --all-targets` | stable | PASS — **874 passed, 0 failed, 7 ignored** |
| 10 | `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | PASS — **92.00 % Lines** |
| 11 | `cargo doc --workspace --no-deps` | stable | PASS |
| 12 | `git diff --check` | — | PASS |
| 13 | `git status --porcelain` | — | clean |

Coverage is read from the **Lines** column (the header is `Regions / Functions /
Lines / Branches`).

## 2. Targeted PR 6 suites (MSRV)

| Suite | Result |
|---|---|
| `pr06_amendment_02` (C01–C15) | 14 passed, 1 ignored separate-process child (`c07_child_reopen`) |
| `pr06_amendment_01` (T01–T25) | 16 passed, 1 ignored child |
| `pr06_faults` (F01–F16) | 17 passed |
| `pr06_local_integration` (I01–I12) | 13 passed, 3 ignored child entry points |
| `pr06_lifecycle_unit` (U01–U17) | 18 passed |

Ignored tests are child-process entry points executed by their parents; a SKIP
is never counted as an independent acceptance pass.

## 3. C01–C15 outcomes

| Test | Status | Evidence |
|---|---|---|
| C01 existing + new over budget | PASS | `c01_c04_pair_rejected_preserves_state` |
| C02 three-generation cumulative growth | PASS | `c02_multigeneration_cumulative_budget` |
| C03 exact boundary commit/reopen | PASS | `c03_exact_boundary_commit_and_reopen`, `c15_exact_boundary_on_fs_directory` |
| C04 one-over with exact requested sum | PASS | `c01_c04_pair_rejected_preserves_state` |
| C05 per-segment codec bound | PASS | `c05_per_segment_codec_bound_rejects_before_durable_write` (earlier codec rejection while building; no persisted data) |
| C06 zero writes on rejection | PASS | `c06_budget_rejection_performs_zero_commit_writes` (counting Directory: 0 segment creates, 0 manifest creates, 0 `CURRENT` writes, 0 syncs) |
| C07 Fs durability + separate-process reopen | PASS | `c07_fs_durability_after_rejection` + `c07_child_reopen` |
| C08 pending preserved | PASS | `c08_pending_preserved_after_rejection` |
| C09 flushed + pending preserved | PASS | `c09_flushed_and_pending_preserved_after_rejection` |
| C10 no-op / empty-initial unchanged | PASS | `c10_noop_and_empty_initial_commit_unchanged` |
| C11 counted exactly once | PASS | `c11_committed_flushed_pending_counted_once` |
| C12 overflow typed | PASS | `c12_overflow_is_typed` + `support.rs::bounded_total_detects_overflow` |
| C13 fault/regression | PASS | `pr06_faults` and `pr06_lifecycle_unit` green |
| C14 PR 5 golden unchanged | PASS | `c14_pr5_golden_fixture_is_byte_identical` (`ebb07800…dae979`); codec suites green |
| C15 storage parity | PASS | `c15_pair_rejected_on_fs_directory`, `c15_exact_boundary_on_fs_directory` |

## 4. Independent oracles

- Expected key sets are hand-authored `BTreeSet`s, not derived from `commit()`.
- Expected totals are computed from independently measured real encoded segment
  lengths in isolated fixtures with identical schema/documents.
- Rejected commits are checked against raw `CURRENT` bytes and manifest/segment
  listings, not only decoded generation.
- C06 uses a delegating counting `Directory` and distinguishes the preflight
  rejection from a storage failure via the typed error and zero write counts.

## 5. Failures, classification and deviations

- No failing tests and no introduced regression, amendment defect, pre-existing
  failure, flake or harness failure.
- No deviation from the plan's binding design; no STOP condition applied.
- GitHub Actions is **BLOCKED/unverified** because the branch is unpushed; this
  is recorded, not reported as green.

## 6. Completion status separation

- Implementation: complete for the Amendment 02 scope.
- Tests exist / executed / pass: yes, on both toolchains.
- Local QA and coverage gates: pass.
- PR readiness: ready for review; no merge without explicit approval.
- Roadmap PR 6: **not** marked DONE.
