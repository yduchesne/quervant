# PR 7 Amendment 04 Correction 01 preflight

**Branch:** `dev/lexical-postings`
**Reviewed starting head:** `33d7177` (Amendment 04 finalization); benchmark implementation `dad2514`
**Base `main`:** `4f603ce1c0dafd994918bb5291d4b0584d9f001c` (unchanged)
**Working tree at preflight:** clean.
**Environment:** Linux 6.18.33.2-microsoft-standard-WSL2 x86_64, Intel(R)
Core(TM) i7-10750H @ 2.60GHz, 12 logical CPUs, ext4; Rust 1.98.1 / 1.85.0;
Criterion 0.7.0; `perf`/`cargo-flamegraph`/`heaptrack` UNAVAILABLE.

## Confirmed defects at `33d7177`

1. **False-zero semantic metadata.** `benchmarks/reports/pr07-amendment04-baseline.json`
   records `actual_hits: 0` for positive-hit workloads (e.g.
   `pr07_phrase_2000_4seg/phrase-present/k10`, true value **8**). The committed
   validator accepted the report: `validate-report.py …baseline.json` printed
   `VALID: 34 results` (expected red-test gap).
2. **No contention qualification.** `run-pr07-baseline.sh` performs no
   competing-workload check, so a contended run (e.g. a concurrent MTMF/Java
   benchmark) could be published as a baseline. A live sample at preflight
   detected a `java` process consuming ≥0.5 core → `suspected`.
3. **Wrong dictionary throughput unit.** `benches/dictionary.rs` declared
   `Throughput::Elements(entry_count)` while each timed iteration performs one
   lookup.

## Observed red evidence

```
$ python3 benchmarks/scripts/validate-report.py benchmarks/reports/pr07-amendment04-baseline.json
VALID: 34 results                       # accepts phrase-present actual_hits=0 (true 8)

$ python3 benchmarks/scripts/check-pr07-contention.py --sample-seconds 2
state=suspected reason=unrelated_cpu_consumer class=java competing=1
```

## Invariant → test mapping

| Invariant | Tests |
|---|---|
| C01/C02 semantic counts from the oracle | C-T01, C-T02, C-T03; `pr07_amendment04::c01_*` |
| C03 validator rejects fabricated/contradictory metadata | C-T03–C-T07 |
| C04 one dictionary lookup per iteration | C-T08 (source assertion) |
| C05 contention is best-effort, fail-closed | C-T09–C-T14 |
| C06 historical evidence preserved | C-T15; `--historical` validator tests |
| C07 qualification prerequisites | C-T16–C-T19 |
| C08 relative comparison policy | C-T20 (docs) |
| C09 no production change | diff gate + full workspace suite |
| C10 profiler status independent | C-T21 |

## Reconciliation / STOP checks

- Branch HEAD matches the reviewed `33d7177`; no intervening commits.
- Criterion 0.7 output layout inspected: `<group>/[<function>/]<param>/new/{estimates.json,sample.json}`;
  `slope` may be `null` (fallback to `median`/`mean`), handled explicitly.
- `CRITERION_HOME` is a supported Criterion 0.7 output-directory override
  (verified in `criterion-0.7.0/src/lib.rs`), enabling per-run isolation without a
  separate `CARGO_TARGET_DIR`.
- No production source change is required; no STOP condition triggered.
