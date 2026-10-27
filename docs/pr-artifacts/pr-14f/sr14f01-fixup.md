# PR 14F — SR-14F-01 fixup

**Status: `SR-14F-01 CORRECTED IN SOURCE; NEW CAMPAIGN BLOCKED — NEW OPERATOR
ATTESTATION REQUIRED`.** The first corrected attempt at source lock `8cfd2fc`
failed in the pre-cold oracle and is preserved as unqualified. The current
measurement source lock is `d12a97537a5131953c948c3a90065a73c3d24b40`. No new
qualified trial has been run. PR 14 remains **IN PROGRESS / NOT ACCEPTED**;
v0.1 is **NOT RELEASED**.

## 1. Finding

At reviewed head `dad3030…`, the timed `remote-cold` W01 loop ran before the
full remote `correctness()` oracle. The workload contract requires the complete
independent oracle before any timed workload. `correctness()` itself is
unchanged.

Note: `origin/main` advanced from `7b1b84be…` to `18c8fca8…` during this pass.
No PR-branch executable change was introduced by that drift; no rebase or merge
was performed.

## 2. Attempt 1 — source lock `8cfd2fce436ea99d57d2699471ab49d2cd1a3446`

Attempt 1 used `index.snapshot()` for the untimed validation oracle:

```rust
let validation_snapshot = index.snapshot();
correctness(&validation_snapshot);
```

The t1 trial failed inside `correctness()` at `pr14_bench_remote.rs:286`:
W01 returned `0` hits instead of `10_000`. `RemoteIndex::snapshot()` is the
generation observed at `create()` time, which is empty before the three writer
commits; it does not represent the committed generation. t2/t3 were not
started. No CSV or report JSON was written.

Preserved unqualified attempt (ignored `target/`):

```text
target/pr14-p4/attempts/8cfd2fce436e-t1-oracle-snapshot-failure/
  README.txt
  pr14-p4-contention-t1.json   sha256 615cf158ce715a071e66533c6122c7e2c8e3d8150eaf7185b4c80adf4a607232
  pr14-p4-t1-run.log           sha256 e0db1d18c8ddca69c6794581f0be30957b1993be7f580dfd270625d4f701aa7e
  SHA256SUMS
```

This attempt is not publishable, not reusable and not relabelled.

## 3. Correction — source lock `d12a97537a5131953c948c3a90065a73c3d24b40`

AD02's approved fallback is now used: open a fresh reader of the committed
generation for the untimed oracle, then drop it before clearing the disposable
workspace.

```rust
let mut remote_oracle_passed = false;
{
    let validation_reader = RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        limits(),
    )
    .await
    .unwrap();
    let validation_snapshot = validation_reader.snapshot();
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

The validation reader and snapshot are dropped at the end of the block; the
`index` created for writing is dropped next; only the disposable workspace is
cleared. The post-cold `correctness(&snapshot)` remains as a warm-boundary check.

## 4. Wrapper gate and regression tests

`run-pr14-p4.sh` rejects qualified logs missing the exact line
`PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS`.

| Test | Result |
|---|---|
| `bash benchmarks/scripts/test-scripts.sh` | **64/64 PASS** |
| `python3 benchmarks/scripts/test-pr14f-oracle-order.py` | **6/6 PASS** |
| Missing marker rejects qualified wrapper | PASS |
| Marker present accepts qualified wrapper | PASS |
| Baseline remote ordering rejected | PASS |
| Local W09 oracle cannot satisfy remote check | PASS |
| Marker after cold stopwatch rejected | PASS |
| Missing cold-loop assertion rejected | PASS |

## 5. Preflight gates at `d12a975`

| Gate | Result |
|---|---|
| Stable and MSRV `fmt` | PASS |
| Stable and MSRV Clippy, both feature sets, `-D warnings` | PASS |
| Workspace tests (stable/MSRV, ±all-features) | PASS — 2,044 / 2,048 passed, 0 failed |
| Coverage | PASS — **91.84% lines** |
| `cargo doc`, `cargo bench --no-run` | PASS |
| Validator `--self-test`, `--list`, `git diff --check` | PASS |
| Native Linux filesystem | PASS — ext4 |
| Pinned RustFS digest/health | PASS — `1803faef…6a3c`, `1.0.1` |
| Old reports and prior packages | unchanged |

## 6. Campaign state

| Item | State |
|---|---|
| Current measurement source lock | `d12a97537a5131953c948c3a90065a73c3d24b40` |
| New qualified trials | **NOT RUN** |
| New operator idle attestation for `d12a975` | **ABSENT** — attestation for `8cfd2fc` does not transfer |
| New report/raw directory | not created |
| Validator/auditor on new data | not run |
| New archive/Drive upload | not created |
| Final-head CI | pending after this evidence commit |

No diagnostic substitute was run. The next step requires a **new,
contemporaneous operator idle attestation for `d12a975`**, then:

```bash
bash benchmarks/scripts/run-pr14-p4.sh --trials=3 --idle-confirmed
```

## 7. Historical separation

The `7df4920…` campaign, its `pr14f-p4-7df492023397-t*.json` reports and its
Google Drive archive remain historical evidence only. The failed `8cfd2fc` t1
attempt is preserved as unqualified. Neither is current SR-14F-01 acceptance
evidence.
