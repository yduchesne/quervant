# PERF-05-C — Second B-Only Acquisition Report

**Scope:** one separately authorized, independently recorded B-only warm acquisition after the first
attempt failed its B/B stability gate. This report does **not** modify or supersede
[`PERF05C_EXECUTION_REPORT.md`](PERF05C_EXECUTION_REPORT.md), which documents the first attempt.

## Repository / branch / PR / SHAs

- Repository: `yduchesne/quervant`
- Branch / PR: `dev/perf05-physical-execution-series` / PR #117 (OPEN, unmerged; draft untouched)
- Required branch HEAD before this operation: `ea55efc66bc9e9d49cbcec86f16dfd81874e710e`
- **Measured B source (unchanged):** `ee18ed63bbeeb54b544393ee0f676987ff9987d1` (PERF-05-B1…B5)
- Historical A measured source (read-only): `256501f0e700ed199f316e79d128389375177530`
- Pre-PERF-05 base (not measured A): `9775bfca4c58a27e65ca28c1d705efad00a65ec8`
- FINAL/remote SHA: the commit containing this report and the new result, verified equal to
  `origin/dev/perf05-physical-execution-series` after push (exact value in the terminal response).

## Frozen inputs verified (read-only preflight)

- Configuration `benchmarks/studies/perf-05/warm/configurations/quervant-perf05-b-only-warm-2026-11-23.json`,
  Git blob `8cd3dec3f361c4c421fda9c89b11ca86fd25c1a6`, configuration ID
  `f4e2b8a4-db2b-4dcf-8e68-3bdf207389a4`, `arms.B.revision = ee18ed63…`, 16 warm lanes,
  `blocks=12`, `slots_per_arm=1`, `warmups=5`, `samples=20`, `max_aa_gain_percent=15`,
  `exclude_blocks={}` — all unchanged.
- Previous INCOMPLETE result `…-001.json`, Git blob `eb732df9b88ee9b0b1e160bcf26e2d826a9b2bbf`,
  preserved byte-for-byte (re-hashed before and after the new run).
- Exactly one prior result existed before the run; no other PERF-05 result files were present.
- Prepared cache reused by `run` (no separate `stage` invocation, no cache deletion/rebuild):
  `PREPARATION=HIT`, key `022379cd0598d9a93c2382e9a6dfbd142069e9b42705c9045d664c9770e593b8`.

## Acquisition (exactly one)

```
PYTHONPATH=benchmarks python -m quervant_bench run --config \
  benchmarks/studies/perf-05/warm/configurations/quervant-perf05-b-only-warm-2026-11-23.json
```

- Exit code: **0**.
- Result: `benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-002.json`
- Run ID: `0d5d2bfd-9f46-4df0-8c33-2d6768922333` (distinct from the first run)
- Sequence: `2`; configuration ID matches the frozen config; executed UTC `2026-11-23T15:38:59Z`.
- Status: **`COMPLETE`**.

No `stage`, no second `run`, no `compare`, no A/Tantivy/Lucene/RustFS/profiler/Criterion/throughput
or process-cold work occurred.

## Provenance and measurement integrity

- B executable: detached worktree at `ee18ed63…`, `cargo build --release --locked`, experimental
  feature `false`; `context.build.arm_source_revisions.B = ee18ed63…`.
- Indexes (one segment each): 10K `1,560,111` bytes; 100K `15,747,551` bytes — matching the historical
  Q diagnostics.
- Raw records: **384** total (192 `BB`, 192 `BB2`), exactly 24 per lane across 16 lanes; each record
  has 20 timed samples; every `oracle_ok = true`.
- Readiness: `readiness_index_pre = clear`, `readiness_pre = clear`, `readiness_post = clear`.
- `BB` and `BB2` both invoked the same B executable/index; neither is A.
- Historical A was loaded read-only and verified by blob/IDs/source/16 lanes/16 A/A PASS/medians; it
  was never executed.

## B/B stability gate

**All 16/16 B/B controls PASS** (16 lanes × one `BB2` comparison against `BB`). No lane failed, so the
runner computed the B absolute estimates and the descriptive historical comparison.

## Historical descriptive comparison (HISTORICAL, UNPAIRED, DESCRIPTIVE)

| Lane | Class | A historical (ms) | B (ms) | B/A | Gain % | Max ratio | Within |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `10000/absent/k10/warm` | GUARD | 0.039013 | 0.031075 | 0.796536 | 20.3464 | 1.10 | True |
| `10000/absent/k100/warm` | GUARD | 0.038825 | 0.029975 | 0.772059 | 22.7941 | 1.10 | True |
| `10000/common/k10/warm` | GUARD | 3.239065 | 2.626522 | 0.810889 | 18.9111 | 1.10 | True |
| `10000/common/k100/warm` | GUARD | 3.273317 | 2.704748 | 0.826302 | 17.3698 | 1.10 | True |
| `10000/medium/k10/warm` | GUARD | 1.487246 | 1.346880 | 0.905620 | 9.4380 | 1.10 | True |
| `10000/medium/k100/warm` | GUARD | 1.593145 | 1.441507 | 0.904818 | 9.5182 | 1.10 | True |
| `10000/rare/k10/warm` | GUARD | 0.047526 | 0.039101 | 0.822721 | 17.7279 | 1.10 | True |
| `10000/rare/k100/warm` | GUARD | 0.047150 | 0.038313 | 0.812568 | 18.7432 | 1.10 | True |
| `100000/absent/k10/warm` | GUARD | 0.231716 | 0.166414 | 0.718184 | 28.1816 | 1.10 | True |
| `100000/absent/k100/warm` | GUARD | 0.232478 | 0.150427 | 0.647059 | 35.2941 | 1.10 | True |
| `100000/common/k10/warm` | PRIMARY | 33.829324 | 26.432598 | 0.781352 | 21.8648 | 0.95 | True |
| `100000/common/k100/warm` | PRIMARY | 33.481857 | 25.999295 | 0.776519 | 22.3481 | 0.95 | True |
| `100000/medium/k10/warm` | PRIMARY | 15.438919 | 13.485129 | 0.873450 | 12.6550 | 0.95 | True |
| `100000/medium/k100/warm` | PRIMARY | 15.528063 | 13.446290 | 0.865935 | 13.4065 | 0.95 | True |
| `100000/rare/k10/warm` | GUARD | 0.242403 | 0.170165 | 0.701990 | 29.8010 | 1.10 | True |
| `100000/rare/k100/warm` | GUARD | 0.241366 | 0.161827 | 0.670464 | 32.9536 | 1.10 | True |

- Primary lanes (100K medium/common, K10/K100): all four ratios ≤ 0.95.
- Guard lanes (remaining 12): all ratios ≤ 1.10.
- Context: matches the historical reference; no differences reported.
- Estimator `median-of-two-b-slot-medians-per-block-v1`; uncertainty
  `NONE_FOR_HISTORICAL_COMPARISON`; `comparison_kind = HISTORICAL_UNPAIRED_ABSOLUTE`.
- **These are between-session absolute ratios. They are not a paired A/B confidence interval, not a
  contemporaneous comparison, and not a source-only causal claim.** The `TARGETS_MET` flag is a
  predeclared review signal, not merge authorization.

## Preserved first attempt

The first acquisition remains unchanged as
`benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-001.json`
(run `1e22a06c-acee-422d-9a7e-c50cde543d20`, blob `eb732df9…`, status `INCOMPLETE`). Its single B/B
failure was `10000/absent/k10/warm` (`BB2` vs `BB`, point gain `+0.82%`, 95% gain interval
`[-5.0621%, +16.9045%]`, beyond the ±15% bound). Samples from the two attempts were **not** pooled,
excluded or cherry-picked; the second attempt is reported in full and independently.

## CI and QA

- No code, tests, configuration, thresholds or methodology were changed; no Python/Rust QA was
  re-executed because there was no source change (per the authorization).
- Hosted CI on the PERF-05-C framework commit `6764fe6a8d4e534af1a52b8838683f7981e69e98`:
  `rust`, `python-benchmark-framework`, `msrv`, `rustfs`, `benchmark-adapter-contract` — all
  `completed/success`.
- Prior B5 Rust CI run #45126782770 (#522) remains the applicable Rust-source evidence.
- `git diff --check` on the staged new report/result: clean.

## Limitations

- Historical A and B were measured in different sessions; this report makes no paired or causal claim.
- No RustFS, profiling, CPU attribution, Criterion or process-cold measurement occurred.
- The result is an independent B-session qualification against a retained historical reference and
  requires human review before any adoption, merge or methodology decision.

## Disposition

**`PERF05C_SECOND_B_ONLY_COMPLETE_HISTORICAL_TARGETS_MET_REVIEW_REQUIRED`**

All 16 B/B controls passed, the acquisition is `COMPLETE`, the context matches the historical
reference, all four primary lanes meet `B/A ≤ 0.95`, and all twelve guard lanes meet `B/A ≤ 1.10`
under the predeclared descriptive review thresholds. PR #117 remains open and unmerged; no further
acquisition is authorized.
