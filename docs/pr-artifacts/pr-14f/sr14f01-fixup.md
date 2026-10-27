# PR 14F — SR-14F-01 fixup

**Status: `SR-14F-01 CORRECTED IN SOURCE; NEW CAMPAIGN BLOCKED — OPERATOR
ATTESTATION REQUIRED`.** No new qualified trial was executed. The previous
campaign at `7df4920…` is historical evidence only. PR 14 remains **IN PROGRESS /
NOT ACCEPTED**; v0.1 is **NOT RELEASED**.

## 1. Finding

At reviewed head `dad3030…`, the remote block in
`crates/quervant-core/tests/pr14_bench_remote.rs` ran the timed `remote-cold`
W01 loop first (baseline line 552) and only afterwards called the full
`correctness(&snapshot)` oracle (baseline line 592). The workload contract
requires the complete independent correctness oracle before any timed workload.

Baseline sequence (abridged):

```text
commits 0..7000 / 7000..14000 / 14000..20000
remove workspace
let mut cold = ...            // timed remote-cold W01 starts here
for sample in 0..SAMPLES { ... Instant::now() ... }
...
let snapshot = reader.snapshot();
correctness(&snapshot);       // too late
```

`correctness()` itself is unchanged.

Note: `origin/main` advanced from `7b1b84be…` to `18c8fca8…` during this pass.
No PR-branch executable change was introduced by that drift; no rebase or merge
was performed, and PR #67 remains targeted at its existing base.

## 2. Fix (source lock `8cfd2fce436ea99d57d2699471ab49d2cd1a3446`)

The remote block now performs this sequence before the first cold stopwatch:

```rust
let mut remote_oracle_passed = false;
{
    let validation_snapshot = index.snapshot();
    assert!(!remote_oracle_passed);
    correctness(&validation_snapshot);
    remote_oracle_passed = true;
}
drop(index);
match std::fs::remove_dir_all(&workspace) {
    Ok(()) => (),
    Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
    Err(error) => panic!("remote oracle cache reset failed: {error}"),
}
assert!(remote_oracle_passed);
println!("PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS");

let mut cold = Vec::with_capacity(SAMPLES);
for sample in 0..SAMPLES {
    assert!(remote_oracle_passed);
    let _ = std::fs::remove_dir_all(&workspace);
    let start = Instant::now();
    // unchanged open_existing + first W01 query
```

The `assert!(!remote_oracle_passed)` read keeps the required fail-closed
initialization meaningful to Clippy; it does not change the invariant. The
post-cold `correctness(&snapshot)` remains as an additional warm-boundary check.

## 3. Wrapper gate

`benchmarks/scripts/run-pr14-p4.sh` now rejects a qualified trial log that does
not contain the exact line:

```text
PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS
```

The check is immediately after the existing `qualified=true` check and before
the report-existence check. Missing marker exits nonzero and preserves
artifacts.

## 4. Regression tests

| Test | Result |
|---|---|
| `bash benchmarks/scripts/test-scripts.sh` | **64/64 PASS** |
| `python3 benchmarks/scripts/test-pr14f-oracle-order.py` | **6/6 PASS** |
| Missing marker rejects qualified wrapper | PASS (exit 1; validator not called) |
| Marker present accepts qualified wrapper | PASS (3 logs contain exact line) |
| Baseline remote ordering rejected | PASS |
| Corrected remote block accepted | PASS |
| Local W09 oracle cannot satisfy remote check | PASS |
| Marker after cold stopwatch rejected | PASS |
| Missing cold-loop assertion rejected | PASS |

## 5. Preflight gates at the new source lock

| Gate | Result |
|---|---|
| Stable and MSRV `fmt` | PASS |
| Stable and MSRV Clippy, both feature sets, `-D warnings` | PASS |
| `cargo test --workspace --all-targets` (stable + MSRV) | PASS — 2,044 passed, 0 failed, 10 ignored |
| `--all-features` workspace tests (stable + MSRV) | PASS — 2,048 passed, 0 failed, 73 ignored |
| `cargo llvm-cov … --fail-under-lines 85` | PASS — **91.84% lines** |
| `cargo doc`, `cargo bench --no-run` | PASS |
| Validator `--self-test` | PASS |
| `test-pr14_bench_remote -- --list` | `pr14_p4_benchmark: test` |
| `git diff --check` | PASS |
| Native Linux filesystem | PASS — ext4 in WSL2 |
| Pinned RustFS digest + health | PASS — `1803faef…6a3c`, health `1.0.1` |
| Old reports and prior raw package | unchanged |

## 6. Campaign state

| Item | State |
|---|---|
| New source lock | `8cfd2fce436ea99d57d2699471ab49d2cd1a3446` |
| New qualified trials | **NOT RUN** |
| New operator idle attestation | **ABSENT** — prior consent does not transfer |
| New report/raw directory | not created |
| Validator/auditor on new data | not run |
| New archive/Drive upload | not created |
| Final-head CI | pending after this evidence commit |

No diagnostic or substitute campaign was run. The next executable step requires
a **new, contemporaneous operator idle attestation** for source lock `8cfd2fc`,
then:

```bash
bash benchmarks/scripts/run-pr14-p4.sh --trials=3 --idle-confirmed
```

Each trial log must show the pre-cold marker. Only then can the validator,
auditor, new archive, Google Drive upload and final evidence be produced.

## 7. Historical separation

The three `pr14f-p4-7df492023397-t*.json` reports and the old Google Drive
archive remain historical evidence for the prior campaign. They are not current
acceptance evidence for SR-14F-01 and are not reused, relabelled or modified.
