# PR 15A — local validation report

**Status:** `PASS (EXECUTED)` for every local gate below. **No CI PASS is
claimed**, no PR was opened from this environment, and v0.1 remains
**NOT RELEASED**.

- Validated implementation head: `f8392db` (`test(pr15a): add fake and real RustFS v1 vertical`)
- Base: `80a38643878681b2ae53f90c281b52f6aa4bd9a1`
- Branch: `test/pr15a-regression-compatibility`
- Tracked working tree: clean at validation time
- Evidence-only commits after `f8392db` add these documents and change no
  executable source, test, manifest, fixture or CI path (X40).

Environment: stable `rustc 1.98.1`; MSRV `rustc 1.85.0`; native Linux WSL2
filesystem; 12 CPU / 31 GiB; pinned RustFS `1.0.1`
(`sha256:1803faef…6a3c`) for provider gates.

## 1. Mandatory gates

| Gate | Exact command | Result | Evidence |
|---|---|---|---|
| Formatting (stable) | `cargo +stable fmt --all -- --check` | **PASS** | `target/pr15a/p5-fmt-stable.log` |
| Formatting (MSRV) | `cargo +1.85.0 fmt --all -- --check` | **PASS** | `target/pr15a/p5-fmt-msrv.log` |
| Clippy stable default | `cargo +stable clippy --workspace --all-targets -- -D warnings` | **PASS** | `target/pr15a/p5-clippy-stable.log` |
| Clippy stable all-features | `cargo +stable clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** | `target/pr15a/p5-clippy-stable-allfeat.log` |
| Clippy MSRV default | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | **PASS** | `target/pr15a/p5-clippy-msrv.log` |
| Clippy MSRV all-features | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** | `target/pr15a/p5-clippy-msrv-allfeat.log` |
| Workspace tests stable default | `cargo +stable test --workspace --all-targets` | **PASS** — 113 targets, 2072 passed, 0 failed, 10 ignored | `target/pr15a/p5-test-stable.log` |
| Workspace tests stable all-features | `cargo +stable test --workspace --all-targets --all-features` | **PASS** — 113 targets, 2076 passed, 0 failed, 75 ignored | `target/pr15a/p5-test-stable-allfeat.log` |
| Workspace tests MSRV default | `cargo +1.85.0 test --workspace --all-targets` | **PASS** — 113 targets, 2072 passed, 0 failed, 10 ignored | `target/pr15a/p5-test-msrv.log` |
| Workspace tests MSRV all-features | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** — 113 targets, 2076 passed, 0 failed, 75 ignored | `target/pr15a/p5-test-msrv-allfeat.log` |
| Coverage (≥ 85 % lines) | `cargo +stable llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** — region 91.94 %, function 87.41 %, **line 91.38 %** | `target/pr15a/p5-coverage.log` |
| Docs | `cargo +stable doc --workspace --all-features --no-deps` | **PASS** | `target/pr15a/p5-doc.log` |
| Bench compilation only | `cargo +stable bench --workspace --no-run` | **PASS** | `target/pr15a/p5-bench-norun.log` |
| Script tests | `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 64 passed, 0 failed | `target/pr15a/p5-scripts.log` |
| Validator self-test | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | **PASS** | `target/pr15a/p5-validate-self-test.log` |
| Whitespace | `git diff --check` | **PASS** | command output |

Ignored counts are reported separately and are **not** counted as passes.
`cargo bench --no-run` was used only: PR 15A times no workload (X28).

## 2. Targeted PR 15A / reused suites

| Target | Command | Result |
|---|---|---|
| `pr15a_regression` | `cargo +stable test -p quervant-core --test pr15a_regression -- --nocapture` | 14 passed, 0 failed, 0 ignored |
| `pr15a_compatibility` | `cargo +stable test -p quervant-core --test pr15a_compatibility -- --nocapture` | 3 passed, 0 failed, 0 ignored |
| `pr15a_provider` (fake) | `cargo +stable test -p quervant-core --test pr15a_provider` | 1 passed, 0 failed |
| `pr14a_public_cursor` | `cargo +stable test -p quervant-core --test pr14a_public_cursor` | 29 passed, 0 failed, 0 ignored |
| `m5_mutation_qualification` | `cargo +stable test -p quervant-core --test m5_mutation_qualification` | 26 passed, 0 failed, 0 ignored |
| `pr11_json_corruption` | `cargo +stable test -p quervant-core --test pr11_json_corruption` | 8 passed, 0 failed, 1 ignored (generator) |
| `segment_golden` | `cargo +stable test -p quervant-core --test segment_golden` | 2 passed, 0 failed, 1 ignored (generator) |
| `pr14_unified_mixed` (P0 baseline) | `cargo +stable test -p quervant-core --test pr14_unified_mixed` | 29 passed, 0 failed, 0 ignored |
| Compatibility inherited run | `pr07_compatibility`, `pr09_recovery`, `pr09_merge`, `pr14_storage_vertical` local | 14 + 4 + 6 + 5 passed, 0 failed |

Real-provider commands and counts are in `provider-validation.md`.

## 3. Failure dispositions during implementation

| Observation | Rule | Disposition |
|---|---|---|
| Authored truth table omitted `a3` from `NOT title=alpha` | X07/X35 | Corrected oracle derivation by record-by-record set logic; engine output matched the corrected 4-key complement |
| Authored expectation treated IPv4 `/0` as `/24` | X07/X35 | Corrected to all six IPv4 rows; engine output matched |
| Compaction advances the generation beyond the mutation commit | X07 | A-T13 asserts `> 2`; A-T11 keeps the exact generation-3 assertion before compaction |
| Cursor / mutation / budget negatives already authoritative in PR 14A/M5 | X02 | Reused and rerun; not duplicated |
| Internal ignored child entrypoints exist | X36 | Parent harnesses only; child standalone runs excluded from evidence |

No production source change was needed. No HARD STOP condition remains.

## 4. Coverage

`TOTAL` row from `cargo llvm-cov`:

```
TOTAL  77092  6214  91.94%  4097  516  87.41%  48699  4199  91.38%  0  0  -
```

The line gate (`--fail-under-lines 85`) passed at **91.38 %**. No exclusion,
floor change or coverage-config change was made.
