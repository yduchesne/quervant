# PR 15G-A qualification and blocked gates

**Status:** `FIXUP_IMPLEMENTED_PERF_QUALIFIED_CI_BLOCKED`
**Original implementation SHA:** `73cbc78441ae9e97f58942a72ccdc4276db4590d`
**Reviewed starting SHA:** `b120f9f8d63901cd4bdc9bb83fb4462a5b11d6ad`
**Fixup commit:** recorded in the final report/PR metadata after commit.
**Performance:** P01–P04 **PASS** (one authorized nine-lane A/B campaign)
**Real RustFS:** GA-I07/GA-I08 **EXECUTED LOCALLY PASS** on the pinned image
**Exact-head hosted CI:** **BLOCKED_CREDENTIALS / NOT OBSERVED**

## Performance qualification (P01–P04) — COMPLETED

The operator authorized one complete nine-lane A/B campaign and the runner was
invoked with `--idle-confirmed` only after the repository contention probe
reported `clear` and `vmstat`/`free`/process inspection showed an idle host
(load average 0.00, CPU busy fraction 0.0096, no competing processes, ~30 GiB
free, idle disk after warmup).

Sources and environment:

- Arm A: `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc` (merged PR 15F baseline).
- Arm B: `9ddff6a79a7a9fa1932c5de7f37065252673397d` (PR 15G-A).
- Separate clean detached worktrees; no tracked changes.
- Same host, native `ext4`, WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`,
  12 logical CPUs (Intel i7-10750H), Rust 1.98.1, Python 3.12.3.
- Fresh stage root `target/pr15g-a/qualified-pair-9ddff6a-20261104T0437Z/`.
- Frozen corpus manifest SHA-256
  `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`;
  both arms produced identical index digests.
- 5 warmups + 20 samples per lane/trial, 3 trials per arm, 9 warm lanes.
- Every trial reported `clear` contention before and after; every lane's exact
  oracle hit count matched between arms.

| Gate | Status | Evidence |
|---|---|---|
| P01 same-host 3-trial nine-lane A/B | **PASS** | both arms qualified; identical corpus/environment/index digests |
| P02 100K absent/K100 `B_FASTER` | **PASS** | ratio 0.367; all three paired ratios < 1.0 |
| P03 10K absent/K100 `B_FASTER` | **PASS** | ratio 0.495; all three paired ratios < 1.0 |
| P04 no other-lane `A_FASTER` | **PASS** | no lane classified `A_FASTER` |
| P05 no byte/codec/correctness/memory-cap violation | **PASS** | no format/storage/query change; index digests identical |
| P06 report context without promising a speedup | **PASS** | measured table and supplementary geometric mean below |

Per-lane medians are median-of-trial-medians; percentages are measured latency
differences, not estimates. Full sanitized output:
`target/pr15g-a/qualified-pair-9ddff6a-20261104T0437Z/comparison.{json,md}`.

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

**Supplementary aggregate only:** the geometric mean of the nine per-lane median
ratios is `0.822121`, i.e. a `1.216×` A/B speedup or `17.79%` lower median
latency. This aggregate is not a substitute for any mandatory per-lane criterion.

Interpretation: PR 15G-A delivers a clear, reproducible improvement on the two
mandatory absent lanes, and no lane is classified as a regression. The remaining
medium/common lanes are effectively unchanged/inconclusive on this run and still
dominate absolute latency (roughly 44–85 ms per 100K query). The 100K rare lane's
4.7% median increase is not a significant regression: its paired trials span
0.928–1.059 and the verdict is `INCONCLUSIVE`.

## Campaign provenance and residual performance limits

- Raw samples, per-trial contention JSON, setup metadata and sanitized comparison
  remain under ignored `target/pr15g-a/`.
- This is one host and one campaign; it does not establish Tantivy/Lucene parity,
  distributed throughput, or vector/hybrid performance.
- CPU, allocation and code-size attribution were not measured; the observed
  latency result is the accepted performance criterion, not a causal profile.
- PR 15G-C (streaming/top-K) and later phases still need their own approved
  plans and measurements; no further optimization is authorized by this result.

## Real RustFS and integration gates

The pinned RustFS image
`rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
was already present locally and was run in a disposable local container with the
CI-equivalent test credentials. No fake adapter or substitute was used, and no
production credential or external port was created outside localhost.

| Gate | Status |
|---|---|
| GA-I01 memory index/query/column parity | PASS |
| GA-I02 real `FsDirectory` commit/reopen | PASS |
| GA-I03 PIT vs delete/insert/commit | PASS |
| GA-I04 concurrent snapshot readers | PASS |
| GA-I05 reduced public limit + private observable fallback | PASS — three complementary witnesses |
| GA-I06 corrupt column geometry | PASS — standalone and metered constructors |
| GA-I07 real RustFS empty-cache bootstrap/typed/sort/warm reread | PASS locally (hosted exact-head pending) |
| GA-I08 fault proxy/restart/interrupted download | PASS locally — H06/H07/H09, K01–K05, K05 10x (hosted exact-head pending) |
| Hosted `rust`, `msrv`, `rustfs` jobs at exact PR HEAD | BLOCKED_CREDENTIALS / NOT OBSERVED |

GA-I07 execution: `ga_i07_real_rustfs_cold_bootstrap_typed_sort_and_warm_reread`
passed against the pinned image. GA-I08 execution: `pr13_remote_proxy` 7 passed;
`pr13_crash_rustfs k0` 5 passed; `pr13_crash_rustfs k05` passed 10/10 repeated
runs. Logs are under `target/pr15g-a/fixup/`.

## Gate summary

| Gate | Status |
|---|---|
| A00 exact base/preflight | PASS |
| A01 borrowed immutable geometry, no reparse on admitted hit | PASS locally |
| A02 exact allowance/charge, zero-cap and cap-rejection fallback | PASS locally |
| A03 typed errors/value/validation parity | PASS locally |
| A04 concurrent/guard/PIT/refresh identity | PASS locally |
| A05 no format/bytes/forbidden production change | PASS locally |
| A06 real local writer/commit/reopen | PASS locally |
| A07 nine-lane A/B qualification | PASS |
| A08 stable/MSRV/coverage/scripts/docs | PASS locally |
| A09 exact-final-HEAD hosted CI | BLOCKED_CREDENTIALS / NOT OBSERVED |
| A10 independent review/approval | NOT STARTED |

Fixup-specific evidence: FX-A00 PASS; FX-A01 PASS; FX-A02 PASS; FX-A03 PASS;
FX-A04 PASS locally / hosted pending; FX-A05 PASS locally / hosted pending;
FX-A06 PASS; FX-A07 PASS; FX-A08 PASS; FX-A09 BLOCKED; FX-A10 NOT STARTED.

## Residual risks

- Performance is qualified for this campaign/host only; it is not evidence of
  cross-engine parity or other workload classes.
- Retained geometry increases the measured metadata charge by the actual
  `Vec<ColumnMeta>` capacity; candidate admission is the only gate, and rejected
  candidates retain nothing. This was verified locally but not RSS-profiled.
- Local real-RustFS execution is strong supporting evidence, but hosted
  `rustfs` acceptance at the exact final PR HEAD must still run before merge.
- The fixup exercised existing remote fault/crash harnesses; it did not add new
  fault-injection behavior.
