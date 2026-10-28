# PR 15B qualification campaign

**Status:** three independent trials are structurally and environmentally
qualified. This is not maintainer acceptance and does not make PR 15B `DONE`.

## Source lock

| Item | Value |
|---|---|
| Campaign source SHA | `e8ca1b03420e1ffe8cb19fafac06b2fe8082866b` |
| Workload version | `pr15b_v1` |
| Canonical fixture SHA-256 | `104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087` |
| Command | `bash benchmarks/scripts/run-pr15b.sh --idle-confirmed --trials 3` |
| Campaign wall time | 19:42.53 |
| Raw artifact root | `target/pr15b/20261028T161528Z-e8ca1b03420e1ffe8cb19fafac06b2fe8082866b/` (ignored) |
| Checked-in summaries | `benchmarks/reports/pr15b-v1-e8ca1b0-*.json/.md` |

The qualification campaign ran from a clean working tree after the implementation
commit. The later checked-in report files are documentation-only and do not
change the executable/content source lock.

## Trial table

| Trial | Timestamp (UTC) | Run id | Source SHA | Dirty | Contention | Idle attestation | Oracle | Lanes | Samples per lane | Profilers |
|---|---|---|---|---|---|---:|---|---|---|
| 1 | 2026-10-28T16:22:06Z | `trial-1` | `e8ca1b0…` | false | clear | yes | PASS | 30 | 20–20 | UNAVAILABLE |
| 2 | 2026-10-28T16:28:34Z | `trial-2` | `e8ca1b0…` | false | clear | yes | PASS | 30 | 20–20 | UNAVAILABLE |
| 3 | 2026-10-28T16:35:11Z | `trial-3` | `e8ca1b0…` | false | clear | yes | PASS | 30 | 20–20 | UNAVAILABLE |

Each trial used a separate Criterion output directory
(`CRITERION_HOME=<trial>/criterion`), a separate fixture-metadata file and three
contention checks: before, after Criterion, and final. All checks were `clear`.
Criterion 0.7 was used with the release bench profile and the workload contract's
20-sample minimum. Slow lanes extended measurement time; no sample count fell
below 20.

## Environment

| Item | Value |
|---|---|
| OS | Linux `6.18.33.2-microsoft-standard-WSL2` |
| CPU | Intel Core i7-10750H @ 2.60 GHz, 12 logical CPUs |
| Memory | 32,774,780 kB |
| Filesystem | `ext4` (native Linux) |
| Criterion | `0.7.0` |
| Stable toolchain | `rustc 1.98.1` / `cargo 1.98.1` |
| Profilers | perf UNAVAILABLE, cargo-flamegraph UNAVAILABLE, heaptrack UNAVAILABLE |

A RustFS service process was present on the host during the campaign but was idle
(0.1% CPU in the pre-run process snapshot). The approved contention detector
reported `clear` with zero competing processes before, during and after each
trial. No benchmark workload was running and no external process was terminated.

## Validation

Each trial was validated with:

```sh
python3 benchmarks/scripts/validate-pr15b.py trial \
  --criterion-dir <trial>/criterion \
  --fixture-metadata <trial>/fixture-metadata.json \
  --env-file <trial>/env.txt \
  --out <trial>/trial.json \
  --run-id trial-N \
  --source-sha e8ca1b03420e1ffe8cb19fafac06b2fe8082866b \
  --contention-state clear \
  --idle-confirmed \
  --correctness-passed
```

The aggregate was produced with:

```sh
python3 benchmarks/scripts/validate-pr15b.py aggregate \
  --trial <trial-1>/trial.json \
  --trial <trial-2>/trial.json \
  --trial <trial-3>/trial.json \
  --out <base>/pr15b-qualified.json \
  --out-md <base>/pr15b-qualified.md
```

The validator rejects missing lanes, duplicate lanes, samples < 20, non-bracketing
confidence intervals, bad fixture digests, an oracle gate other than `PASS`, a
dirty tree, missing idle attestation, non-`clear` contention, non-native
filesystems, an unevidenced `AVAILABLE` profiler, source-SHA mismatch and an
aggregate with fewer than three trials. Its negative self-tests pass.

## Checked-in summary checksums (SHA-256)

| File | SHA-256 |
|---|---|
| `pr15b-v1-e8ca1b0-qualified.json` | `1b25275436f3ac0f91645adf0e2f2974e906ea400293c556c3edd399df596d29` |
| `pr15b-v1-e8ca1b0-qualified.md` | `17860f69efabb374a1c30fa62433f2e22dd697cb68e08decc0d359299c5f1953` |
| `pr15b-v1-e8ca1b0-trial-1.json` | `8feb896970328ff9f7e4af74fad9cfebcc5de048357486268967292478b77878` |
| `pr15b-v1-e8ca1b0-trial-2.json` | `6dc70f68299f7c1d1bd837ddfdffac563567304ee4755077b7db93ba335be407` |
| `pr15b-v1-e8ca1b0-trial-3.json` | `77d47d09fc7385a403e76244ec6d8e2a414d06524ae82ad224d961245bda39d2` |

Raw Criterion data remains under ignored `target/`; it is not staged or
committed.

## Dispersion

Across the 30 required lanes, the trial-to-trial median dispersion
(`max/min`) is **1.005–1.092**. The aggregate JSON retains each trial's median
and estimate so a reviewer can recompute dispersion. No result is presented as a
statistically significant speedup or regression.

## U14

`QUERVANT_PR15B_LARGE` and `QUERVANT_PR15B_SEG64` were not enabled. U14 is
`NOT RUN (OPTIONAL)` and is excluded from the required aggregate, exactly as the
workload contract specifies.
