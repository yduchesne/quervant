# PR 15G-A performance qualification

**Status:** `PERFORMANCE_QUALIFIED` (P01–P04 PASS)
**Measured arm A:** `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc`
**Measured arm B:** `9ddff6a79a7a9fa1932c5de7f37065252673397d`
**Campaign stage root:** `target/pr15g-a/qualified-pair-9ddff6a-20261104T0437Z/`
**Scope:** one authorized same-host Quervant-only A/B campaign; no source,
format, workload, oracle or runner semantics changed.

This report is committed after the measurement as documentation only. The
measured code tree is exactly arm B above; the later documentation commit does
not alter the measured production, benchmark or corpus inputs.

## Host and authorization evidence

The operator explicitly authorized this campaign. `--idle-confirmed` was passed
only after the repository contention probe reported `clear` and direct system
inspection showed:

- load average `0.00` (1/5/15-minute windows);
- CPU busy fraction `0.0096` in the standalone preflight probe;
- zero competing benchmark-class processes;
- ~30 GiB free memory, no swap activity;
- `vmstat` disk I/O idle after the initial sample;
- native `ext4` on WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`;
- 12 logical CPUs, Intel Core i7-10750H, Rust/cargo 1.98.1, Python 3.12.3.

A between-arm probe was also `clear` (busy fraction `0.0063`, zero competing
processes). Every one of the six arm-trials reported `clear` contention before
and after measurement.

## Method

- Two separate clean detached worktrees: arm A and arm B.
- Frozen PR 15D corpus/adapters/oracle unchanged.
- Nine warm lanes: 10K/100K × absent/rare/medium/common at K100, plus 100K
  common at K10.
- 5 warmups + 20 timed samples per lane/trial, exactly 3 trials per arm.
- Both arms produced identical corpus manifest SHA-256
  `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`
  and identical index digests for both 10K and 100K.
- Exact `total_hits` and ordered keys matched the independent oracle for every
  lane and both arms.
- Arm A/B binary SHA-256 values differ as expected:
  `08d6f068...a7d3a` vs `d56cf658...64a1f`.

## Results

Medians are median-of-trial-medians in nanoseconds. Improvement is measured
latency reduction `(A−B)/A`; a negative value is a measured slowdown.

| Lane | A median (ns) | B median (ns) | B/A | Improvement | Paired trial ratios | Verdict |
|---|---:|---:|---:|---:|---|---|
| 10K absent/K100 | 124,926 | 61,823 | 0.495 | +50.5% | 0.441, 0.469, 0.496 | B_FASTER |
| 10K rare/K100 | 2,710,331 | 2,679,396 | 0.989 | +1.1% | 0.827, 0.980, 0.989 | B_FASTER |
| 10K medium/K100 | 4,453,025 | 4,426,228 | 0.994 | +0.6% | 0.889, 0.994, 1.030 | INCONCLUSIVE |
| 10K common/K100 | 8,152,933 | 7,698,250 | 0.944 | +5.6% | 0.915, 0.932, 1.101 | INCONCLUSIVE |
| 100K absent/K100 | 1,210,100 | 444,282 | 0.367 | +63.3% | 0.362, 0.394, 0.357 | B_FASTER |
| 100K rare/K100 | 27,765,974 | 29,077,172 | 1.047 | −4.7% | 0.928, 1.059, 1.047 | INCONCLUSIVE |
| 100K medium/K100 | 49,342,547 | 49,000,528 | 0.993 | +0.7% | 0.959, 1.065, 0.993 | INCONCLUSIVE |
| 100K common/K100 | 85,121,524 | 84,662,464 | 0.995 | +0.5% | 0.968, 1.048, 0.992 | INCONCLUSIVE |
| 100K common/K10 | 71,236,136 | 70,088,334 | 0.984 | +1.6% | 0.935, 1.022, 0.984 | INCONCLUSIVE |

**Supplementary aggregate (not an acceptance substitute):** geometric mean of
the nine per-lane median ratios = `0.822121`, equivalent to a `1.216×` A/B
speedup or `17.79%` lower median latency.

## Acceptance

| Gate | Status | Evidence |
|---|---|---|
| P01 qualified nine-lane A/B | PASS | 3 trials/arm, all clear, exact oracle, identical corpus/index inputs |
| P02 100K absent/K100 `B_FASTER` | PASS | ratio 0.367, all paired ratios < 1.0 |
| P03 10K absent/K100 `B_FASTER` | PASS | ratio 0.495, all paired ratios < 1.0 |
| P04 no other lane `A_FASTER` | PASS | no lane classified `A_FASTER` |
| P05 no byte/codec/correctness/memory-cap violation | PASS | no production/format change; index digests identical |
| P06 report without unsupported speedup promise | PASS | measured table plus clearly marked supplementary geomean |

## Interpretation and remaining bottlenecks

- PR 15G-A clearly improves the two mandatory absent lanes: about **2.02×** on
  10K absent/K100 and **2.72×** on 100K absent/K100.
- The other seven lanes are not regressions. Five are `INCONCLUSIVE`; 10K rare
  is `B_FASTER`. The 100K rare median is 4.7% higher but its paired ratios cross
  1.0, so the sign-consistency rule correctly reports `INCONCLUSIVE`, not a
  regression.
- Absolute cost remains concentrated in medium/common/high-hit queries:
  approximately 44–49 ms for 100K medium and 85 ms for 100K common at K100.
  These lanes are the natural target for subsequent streaming/top-K and
  collector work (PR 15G-C), not additional column-geometry optimization.
- This campaign does not measure CPU, allocations, code size, reopen time or
  index bytes, and does not establish cross-engine parity. It is one host and
  one workload matrix.

## Artifacts

- Sanitized: `target/pr15g-a/qualified-pair-9ddff6a-20261104T0437Z/comparison.json`
  and `comparison.md`.
- Derived gate summary:
  `target/pr15g-a/qualified-pair-9ddff6a-20261104T0437Z/qualification-summary.json`.
- Raw samples, per-trial contention, setup/environment and index metadata remain
  under the same stage root inside ignored `target/`.

## Unresolved acceptance blockers

- Exact-head hosted `rust`/`msrv`/`rustfs` CI is not observed; no PR was opened
  because the local `gh` credential is invalid.
- Independent human review/approval (FX-A10/A10) has not occurred.
- `NOT_MERGED`; this qualification does not self-approve the PR.
