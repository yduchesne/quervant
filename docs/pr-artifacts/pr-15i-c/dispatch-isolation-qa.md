# PR 15I-C dispatch-isolation — QA record

## Final settled tree

Production paths are byte-identical to merged PR 15I-B (arm D and E live only on
their own diagnostic branches/worktrees), so the QA below is the ordinary
workspace gate at the diagnostic-tooling tip.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS (135 test binaries) |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — `TOTAL` lines **92.68%** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| `python3 -m unittest discover -s benchmarks/pr15d/harness` | PASS (139) |
| `python3 -m unittest discover -s benchmarks/pr15i_b` | PASS (10) |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | PASS (382, one skip) |
| `python3 -m unittest discover -s benchmarks/pr15i_a` | 87 tests, 1 failure + 3 errors — `DETERMINISTIC_PREEXISTING` / `SOURCE_BOUND_HISTORICAL_ONLY` (reproduced at `BASE_A`, unchanged, not edited) |
| `git diff --check` | CLEAN |

Arm-specific checks (in the D and E worktrees): `cargo +1.85.0 check --locked`
with and without `pr15ic-causal` (D) / `pr15ic-dispatch-isolation` (E), plus the
feature-enabled query suites. D's historical *specialized-execution* unit tests are
`NOT APPLICABLE` for the compile-time-disabled arm and were neither edited nor
counted as passing (`DC-V`/plan §10.1). E's suites pass with the feature enabled in
both modes and with the feature off.

## Failure classification (five classes)

| Item | Class | Evidence |
|---|---|---|
| `pr15i_a::RealCampaignTests` 1F/3E | `DETERMINISTIC_PREEXISTING` | reproduces at `BASE_A` with the same raw campaign |
| First campaign attempt (score probe resolved from A's tree) | `ENVIRONMENT_OR_HARNESS_FAILURE` | preserved as `unbatched-01-attempt-01`, fixed pre-sampling, whole series restarted |
| Codegen symbol-set omission in the first capture wrapper | `IMPLEMENTATION_DEFECT` (diagnostic tooling) | fixed; verifier now re-captures independently; raw untouched, no re-measurement (measurement path unaffected) |
| Everything else in this study | PASS | see the QA table |

## Real storage boundary

| Gate | Status |
|---|---|
| Local `FsDirectory` commit/reopen, PIT, delete+compaction, multi-segment fallback, concurrent readers | covered by the workspace suites above (`pr06`–`pr14`, `pr15*`, `m2`–`m5`) |
| Genuine pinned RustFS + PR13 proxy | **`REAL_RUSTFS_BLOCKED`** — `docker` absent and no verified access to
`rustfs/rustfs@sha256:1803faef…`; no fake store substituted, no ignored test
counted, and no feature acceptance claimed |
