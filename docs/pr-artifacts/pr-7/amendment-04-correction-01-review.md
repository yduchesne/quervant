# PR 7 Amendment 04 Correction 01 review

**Scope:** benchmark evidence integrity and contention qualification. No
production code changed.
**Branch:** `dev/lexical-postings`; starting head `33d7177`; base `4f603ce1`.
**Disposition:** implementation complete; **qualified baseline rerun BLOCKED** by
contention (see below).

## Files

- `crates/quervant-core/examples/pr07_report_metadata.rs` — independent fixture
  metadata emitter.
- `crates/quervant-core/benches/common/mod.rs` — `generate_docs`, `digest_for`,
  `cases_for`, `all_workload_metadata` (no generator duplication).
- `crates/quervant-core/benches/dictionary.rs` — `Throughput::Elements(1)`.
- `crates/quervant-core/tests/pr07_amendment04.rs` — `c01_*` metadata tests.
- `benchmarks/scripts/{validate-report,build-pr07-report,check-pr07-contention,aggregate-pr07-baseline}.py`,
  `{run-pr07-baseline,test-scripts}.sh`.
- `benchmarks/reports/pr07-amendment04-baseline.{md,json}` — historical labeling.
- `benchmarks/{README.md,workloads/pr07_amendment04_v1.md}`, `docs/BENCHMARKING.md`.
- PR 7 artifacts.

## Invariant → evidence

| ID | Evidence |
|---|---|
| C01/C02 | `all_workload_metadata` computes counts from the token-list oracle; `c01_workload_metadata_counts`; script metadata check |
| C03 | v2 validator + `--fixture-metadata`; script cases `false-zero`, `wrong-corpus`, `wrong-ratio`, `nonquery-zero`, `duplicate`, `extra` |
| C04 | `dictionary.rs` asserts `Elements(1)`; script source check |
| C05 | `check-pr07-contention.py` `clear`/`suspected`/`unknown`; script synthetic snapshots |
| C06 | historical run untouched except `status`; `--historical` validation |
| C07 | validator `false-qualified`/`dirty-qualified`; runner fail-closed |
| C08 | `benchmarks/README.md`, `docs/BENCHMARKING.md` |
| C09 | git diff touches only dev-only files; production suites green |
| C10 | profiler `UNAVAILABLE`; script |

## Test results

- `cargo test -p quervant-core --test pr07_amendment04`: **11 passed** (9 original
  + `c01_workload_metadata_counts` + `c01_single_and_multi_segment_digests_differ`).
- `bash benchmarks/scripts/test-scripts.sh`: **30 passed, 0 failed** (profiling
  UNAVAILABLE/fake-perf, historical v1, metadata counts, dictionary unit, v2
  builder + 10 corruption cases, contention clear/suspected/unknown/exclusion).
- Real-artifact assembly smoke test: `build-pr07-report.py` parsed the existing
  Criterion 0.7 `target/criterion` output for all 34 workloads, joined the
  independent metadata, and `validate-report.py` accepted the resulting
  `quervant-bench-v2` report (e.g. `phrase-present` hits **8**, `term-common`
  100K hits **50000**, `bm25` hits **null**). Criterion `slope: null` fallback to
  `median` verified.

## Baseline qualification disposition — **BLOCKED**

The corrected runner was executed once with `--idle-confirmed`:

```
run_base=target/pr07-baseline/20261014T020236Z-33d7177
dirty=true trials=1 allow_contended=0 idle_confirmed=1
contention pre-check did not return clear for trial 1
BLOCKED: resolve contention or pass --allow-contended for a diagnostic-only run
runner_exit=3
```

Pre-check record:
`state=suspected`, `reason_codes=["unrelated_cpu_consumer"]`,
`process_class_counts={"java":1}`, `competing_process_count=1`,
`cpu_busy_fraction=0.157`. A live re-sample reproduced the same `java` consumer.

Post-commit re-checks (clean tree `1293a11`) confirmed the contention is
**intermittent**, not permanently absent:

```
sample 1: state=suspected reason=unrelated_cpu_consumer class={"other":1}
sample 2: state=clear
```

Because qualification requires every check to be `clear`, intermittent
contention still blocks a three-trial qualified run under the fail-closed policy.

Consequences (honest, not fabricated):

- No three-trial qualified baseline was collected; `pr07-amendment04-qualified-baseline.*`
  was **not** produced.
- The runner blocked **before** any Criterion work, preserving the audit trail
  under the run directory.
- The working tree was also dirty (uncommitted correction changes), which would
  independently forbid qualification.
- **C-T13** (preflight contention stops the runner) is demonstrated. **C-T14,
  C-T16–C-T19** (qualification/prerequisites/aggregation) are implemented and
  unit-tested at the validator/aggregator level but could not be exercised with
  real qualified trials.
- Profiling remains `UNAVAILABLE`; no `perf`/`heaptrack` claim.

To obtain a qualified baseline, the operator must stop the competing `java`
workload (for example MTMF), confirm with `--idle-confirmed` on a clean commit,
and run `bash benchmarks/scripts/run-pr07-baseline.sh --idle-confirmed --trials 3`
so three independently qualified trials can be aggregated.

## Residual risks

1. `/proc` cannot observe Windows-host processes or other WSL guests; `clear` is
   not a proof of physical isolation.
2. The detector is heuristic (2 s window); short-lived or low-duty-cycle consumers
   may be missed.
3. Absolute timings are host-specific; no cross-environment extrapolation.
4. No allocation counts (`heaptrack` unavailable); no competitor adapters/ratios
   (PR 15).
5. The qualified baseline remains open until a contention-free, clean-tree,
   operator-confirmed run completes three trials.
