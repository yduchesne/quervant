# PR 6 validation report

> **Tested working-tree state:** branch `dev/pr06-writer-lifecycle` based on
> `569f4a48f98e2f97d55686c5440588889fc66233` (`main`), with the PR 6 changes
> described in `implementation-report.md`. All commands below were executed
> locally after the final source change.
>
> **No merge performed.** CI has not yet run for a pushed head SHA.

## 1. Command results

| # | Command (workspace root) | Result |
|---|---|---|
| 1 | `git rev-parse HEAD` | PASS — `569f4a48f98e2f97d55686c5440588889fc66233` |
| 2 | `cargo +1.85.0 fmt --all -- --check` | PASS |
| 3 | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| 4 | `cargo +1.85.0 test --workspace --all-targets` | PASS — 831 passed, 0 failed, 5 ignored |
| 5 | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **92.30 % lines** |
| 6 | `cargo +1.85.0 doc --workspace --no-deps` | PASS |
| 7 | `cargo fmt --all -- --check` (stable 1.98.1) | PASS |
| 8 | `cargo clippy --workspace --all-targets -- -D warnings` (stable) | PASS |
| 9 | `cargo test --workspace --all-targets` (stable) | PASS — 831 passed, 0 failed, 5 ignored |
| 10 | `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` (stable) | PASS — **92.35 % lines** |
| 11 | `cargo doc --workspace --no-deps` (stable) | PASS |
| 12 | `git diff --check` | PASS |

Toolchains: stable `cargo 1.98.1`; MSRV `cargo 1.85.0`. Coverage tool
`cargo-llvm-cov 0.9.1` with `llvm-tools-preview` for both toolchains.

## 2. PR 6 targeted suites

| Suite | Command | Result |
|---|---|---|
| Unit U01–U17 | `cargo test -p quervant-core --test pr06_lifecycle_unit` | 18 passed |
| Integration I01–I12 | `cargo test -p quervant-core --test pr06_local_integration` | 13 passed, 3 ignored (child entry points spawned by parents) |
| Faults F01–F16 | `cargo test -p quervant-core --test pr06_faults` | 17 passed |

The three ignored integration tests (`i03_child_writer`,
`i04_child_writes_orphan`, `i05_child_reopens_and_commits`) are executed as
separate OS processes by their parent tests; a SKIP is not used to stand in for
them. The pre-existing RustFS harness SKIP is unchanged and is **not** claimed as
PR 6 evidence (production RustFS is PR 13).

## 3. Integration topology actually exercised

- Real `MemoryDirectory` + real analyzer/builder/reader/manifest.
- Real `FsDirectory` for I03–I08, I10–I12, including **separate-process restart**
  (I03, I04, I05).
- Threaded readers over independent `SegmentReader`s during a concurrent commit
  (I09).
- Deterministic fault injection wrapping the real `Directory`/`WriteHandle`
  methods (F01–F16); segment codecs, the analyzer and the manifest are never
  mocked.

## 4. Golden and regression evidence

- `crates/quervant-core/tests/fixtures/segment/golden.seg` SHA-256 unchanged:
  `ebb078004954c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979` (PR 5).
- All PR 3 storage, PR 4 analysis and PR 5 segment suites executed and passed on
  both toolchains, including PR 3 crash-point and subprocess-restart tests.

## 5. Failures, reruns and deviations

- No test failures. Two transient compile errors in in-crate unit tests
  (array-concat type inference and a missing `std::error::Error` import) were
  fixed before the final run; no test was skipped, and no failure was dismissed
  as unrelated.
- `cargo-llvm-cov` was not pre-installed; it was installed locally
  (`cargo install cargo-llvm-cov --locked`, v0.9.1) and the MSRV
  `llvm-tools-preview` component was added. The coverage gate therefore ran on
  both toolchains rather than being reported BLOCKED.
- GitHub Actions has **not** run for a pushed head SHA; the reviewer checklist
  item "final-head CI green" remains open until the branch is pushed.

## 6. Completion status separation

- Implementation: complete for the PR 6 scope.
- Tests exist: yes (U01–U17, I01–I12, F01–F16).
- Tests executed: yes, on both toolchains.
- Tests pass: yes.
- Local QA/coverage gates: pass.
- PR readiness: ready for review; no merge without explicit approval.
- Roadmap PR 6: **not** marked DONE (merge/CI pending).
