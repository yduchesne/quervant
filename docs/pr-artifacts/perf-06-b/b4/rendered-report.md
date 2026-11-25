# Benchmark results: quervant-perf06b4-paired-warm

- Run ID: `86fe9601-2574-4335-a673-63de7d0dcc26`
- Configuration: `quervant-perf06b4-paired-warm-2026-11-25.json` (`4608c79a-c5a3-4d24-bec9-4ad61cd7bd94`)
- Executed (UTC): 2026-11-25T22:29:15Z
- Family: perf-06
- Overall status: **COMPLETE**

Results show within-run treatment/baseline ratios (B/A). Positive gain means improvement.
Separate runs must be compared using the change in within-run gain in percentage points, not absolute timings.

| Lane | Metric | Arm | Absolute median per block (ns) | B/A | Gain % | 95% ratio CI | Status |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 10000/absent/k10/warm | search_latency (ns; lower better) | A | 30838 | — | — | — | REFERENCE |
| 10000/absent/k10/warm | search_latency (ns; lower better) | B | 31175 | 1.0088 | -0.88408 | [0.97461, 1.0246] | INCONCLUSIVE |
| 10000/absent/k100/warm | search_latency (ns; lower better) | A | 30300 | — | — | — | REFERENCE |
| 10000/absent/k100/warm | search_latency (ns; lower better) | B | 30688 | 1.012 | -1.1986 | [1.0086, 1.0215] | REGRESSED |
| 10000/common/k10/warm | search_latency (ns; lower better) | A | 2.4119e+06 | — | — | — | REFERENCE |
| 10000/common/k10/warm | search_latency (ns; lower better) | B | 1.8618e+06 | 0.76749 | 23.251 | [0.75919, 0.77875] | IMPROVED |
| 10000/common/k100/warm | search_latency (ns; lower better) | A | 2.4823e+06 | — | — | — | REFERENCE |
| 10000/common/k100/warm | search_latency (ns; lower better) | B | 1.9194e+06 | 0.77801 | 22.199 | [0.76963, 0.78697] | IMPROVED |
| 10000/medium/k10/warm | search_latency (ns; lower better) | A | 1.2822e+06 | — | — | — | REFERENCE |
| 10000/medium/k10/warm | search_latency (ns; lower better) | B | 8.3907e+05 | 0.65075 | 34.925 | [0.6423, 0.66669] | IMPROVED |
| 10000/medium/k100/warm | search_latency (ns; lower better) | A | 1.3886e+06 | — | — | — | REFERENCE |
| 10000/medium/k100/warm | search_latency (ns; lower better) | B | 9.2948e+05 | 0.66676 | 33.324 | [0.65674, 0.68579] | IMPROVED |
| 10000/rare/k10/warm | search_latency (ns; lower better) | A | 38951 | — | — | — | REFERENCE |
| 10000/rare/k10/warm | search_latency (ns; lower better) | B | 39538 | 1.0268 | -2.6848 | [1.0086, 1.0285] | REGRESSED |
| 10000/rare/k100/warm | search_latency (ns; lower better) | A | 38563 | — | — | — | REFERENCE |
| 10000/rare/k100/warm | search_latency (ns; lower better) | B | 39163 | 1.0205 | -2.0469 | [1.0006, 1.0337] | REGRESSED |
| 100000/absent/k10/warm | search_latency (ns; lower better) | A | 1.5948e+05 | — | — | — | REFERENCE |
| 100000/absent/k10/warm | search_latency (ns; lower better) | B | 1.5725e+05 | 1.0014 | -0.13603 | [0.97152, 1.0357] | INCONCLUSIVE |
| 100000/absent/k100/warm | search_latency (ns; lower better) | A | 1.5008e+05 | — | — | — | REFERENCE |
| 100000/absent/k100/warm | search_latency (ns; lower better) | B | 1.5036e+05 | 1.0033 | -0.3258 | [1.0003, 1.0296] | REGRESSED |
| 100000/common/k10/warm | search_latency (ns; lower better) | A | 2.4615e+07 | — | — | — | REFERENCE |
| 100000/common/k10/warm | search_latency (ns; lower better) | B | 1.8373e+07 | 0.74637 | 25.363 | [0.73833, 0.75157] | IMPROVED |
| 100000/common/k100/warm | search_latency (ns; lower better) | A | 2.4117e+07 | — | — | — | REFERENCE |
| 100000/common/k100/warm | search_latency (ns; lower better) | B | 1.8079e+07 | 0.75127 | 24.873 | [0.74757, 0.75586] | IMPROVED |
| 100000/medium/k10/warm | search_latency (ns; lower better) | A | 1.2767e+07 | — | — | — | REFERENCE |
| 100000/medium/k10/warm | search_latency (ns; lower better) | B | 8.1939e+06 | 0.64181 | 35.819 | [0.6357, 0.64589] | IMPROVED |
| 100000/medium/k100/warm | search_latency (ns; lower better) | A | 1.2736e+07 | — | — | — | REFERENCE |
| 100000/medium/k100/warm | search_latency (ns; lower better) | B | 8.1889e+06 | 0.64591 | 35.409 | [0.63495, 0.64959] | IMPROVED |
| 100000/rare/k10/warm | search_latency (ns; lower better) | A | 1.6468e+05 | — | — | — | REFERENCE |
| 100000/rare/k10/warm | search_latency (ns; lower better) | B | 1.6476e+05 | 1.0172 | -1.7224 | [0.98429, 1.0298] | INCONCLUSIVE |
| 100000/rare/k100/warm | search_latency (ns; lower better) | A | 1.5789e+05 | — | — | — | REFERENCE |
| 100000/rare/k100/warm | search_latency (ns; lower better) | B | 1.6003e+05 | 1.013 | -1.3019 | [1.0032, 1.0185] | REGRESSED |

## Indexing, commit and size

| Arm | Corpus | Insert ms | Commit ms | Open ms | Index bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 10000 | 22.728 | 127.38 | 21.369 | 1456779 |
| A | 100000 | 209.23 | 1231.2 | 212.59 | 14713132 |
| B | 10000 | 20.332 | 105.13 | 20.381 | 1406726 |
| B | 100000 | 217.46 | 1165 | 210.61 | 14312375 |

## Phase durations (wall-clock)

Measured query values exclude indexing and compilation. These wall durations represent orchestration phases; preparation component rows are included within preparation total and must **not** be added again.

| Phase | Elapsed seconds |
| --- | ---: |
| aa_acquisition_ns | 121.46 |
| aa_analysis_ns | 0.769 |
| host_preflight_ns | 0.081 |
| preparation_lookup_ns | 0.104 |
| preparation_ns | 1.148 |
| preparation_oracle_ns | 0.974 |
| run_before_save_ns | 234.26 |
| treatment_acquisition_ns | 106.95 |
| treatment_analysis_ns | 0.754 |

- Prepared inputs: **HIT**, created 2026-11-25T22:29:02Z UTC; previously staged indexing durations are historical descriptive metrics, not part of this run's query timings.


## Method and limitations

- Estimator: `median-paired-ratios-v1`
- Uncertainty: `paired-whole-block-percentile-v1`
- Source/build/host context: `{'adapter_cpu': 2, 'build': {'arm_source_revisions': {'A': '480a77e78c6897e05cb7ceb76b01434974b82ec6', 'B': 'd660ca9f487d5c54363d790a240abb7da30af245'}, 'compiler_options': 'cargo --release --locked', 'quervant_strategy_feature_enabled': False, 'source_revision': 'c874748a9acffb65d59f34cda88d861d7542df3e'}, 'controller_cpu': 0, 'host': {'architecture': 'x86_64', 'cpu': 'x86_64', 'filesystem': 'ext4', 'kernel': '6.18.33.2-microsoft-standard-WSL2', 'physical_core_candidates': [[0, 0, 0], [2, 0, 1], [4, 0, 2], [6, 0, 3], [8, 0, 4], [10, 0, 5]], 'system': 'Linux', 'toolchains': {'cargo': 'cargo 1.98.1 (797e8a9bc 2026-08-05)', 'java': 'openjdk 21.0.13.1 2026-11-17', 'python': '3.12.3', 'rustc': 'rustc 1.98.1 (48a229cea 2026-09-01)'}, 'wsl': True}, 'host_readiness_mode': 'advisory', 'preparation': {'cache_key': '5c3f64949c52d6bb2c68572342b3432a10efc265e1abba6c09e52d85232d96dc', 'cache_status': 'HIT', 'index_metrics_provenance': 'preparation stage (not the current query window)', 'prepared_utc': '2026-11-25T22:29:02Z', 'verified_oracles': True}, 'source_revision': 'c874748a9acffb65d59f34cda88d861d7542df3e'}`
- Process-cold does not necessarily mean cold operating-system page cache.
- NON_COMPARABLE lanes are excluded from combined claims and ranking.
- A slowdown or INCONCLUSIVE result is evidence, not a pipeline error.

## Run notes

No historical performance comparison is implied.
