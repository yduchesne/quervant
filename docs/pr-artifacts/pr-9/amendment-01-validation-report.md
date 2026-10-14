# PR 9 Amendment 01 — validation report

**Base:** `950583c43ea11773e59971e3e330064bd7f67c14` (original PR 9), on top of
`main` at `17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`.
**Tested implementation:** commit `b8c63f9` (`PR 9 Amendment 01: overflow proof,
ambiguous CURRENT, merge cancellation`) on `dev/stable-key-mutations`. All
commands below were executed on that commit's tree (the amendment changes were
validated before the commit and the tree was clean when committed).
**Toolchains:** Rust `1.98.1` (active stable) and Rust `1.85.0` (workspace MSRV).

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (1.98.1) | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` (1.98.1) | PASS — 1234 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 0 failures |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **91.67%** workspace line coverage |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench -p quervant-core --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |

## Amendment test totals

| Suite | Result |
|---|---|
| `cargo test -p quervant-core --lib amendment01` | PASS — 25 passed |
| `cargo test -p quervant-core --lib merge::tests` | PASS — 2 passed |
| Original PR 9 suites (`pr09_*`) | PASS (unchanged) |
| Original PR 5/6/7/8 frozen-fixture suites | PASS (unchanged) |

## Coverage

Baseline before the amendment was 91.33%; the amendment raises it to
**91.67%** (no exclusions). The new `amendment01` fixture/error-path code and the
merge cancellation checkpoints are exercised by the 27 new tests.

## Failure classification

- **Introduced regressions:** none. The full workspace suite, including every
  frozen PR 5–8 fixture and every original PR 9 test, passes on stable and MSRV.
- **Feature defects fixed during the amendment:** the merge compaction publication
  path previously always poisoned on any `CURRENT` error; it now uses the shared
  reconciliation contract, so a proven pre-write failure remains retryable while
  a write-then-error still poisons. This was found while implementing A1-T15c and
  is covered by A1-T15b/T15c.
- **Deterministic pre-existing failures:** none encountered.
- **Flaky:** none observed; cancellation is deterministic via stage/unit hooks.
- **Environment/harness:** none.

## Not run / residual

- No real RustFS or network path (out of scope; PR 13).
- Cancellation is cooperative; the maximum polling interval is 256 logical units,
  but a single bounded codec allocation call is not interruptible. No wall-clock
  deadline is claimed.
- No online destructive reclamation (PR 9 policy unchanged).

No mandatory gate was waived or skipped. No roadmap status was changed.
