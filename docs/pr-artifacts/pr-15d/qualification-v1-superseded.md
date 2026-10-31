# PR 15D comparative qualification

- Workload: `pr15d_v1`
- Source SHA: `c9e982fec5b21ca542f76d0d7940ef796a4c7474`
- Host fingerprint: `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f`
- Filesystem: `ext4`
- Trials: 3 x 20 samples/lane
- Status: **QUALIFIED**
- Score comparison: `NOT_APPLICABLE`
- Scored lane: `SEMANTICALLY_NONCOMPARABLE`
- Performance threshold failure: `False`

## Exact-term latency (median of three trial medians, ns)

| Lane | Regime | Quervant | Tantivy | Lucene | Tantivy/Quervant | Lucene/Quervant |
|---|---|---:|---:|---:|---:|---:|
| pr15d_v1/10000/absent/k10 | process_cold | 18505272 | 54801 | 18261246 | 0.002961 (INCONCLUSIVE) | 0.986813 (INCONCLUSIVE) |
| pr15d_v1/10000/absent/k10 | warm | 17701152 | 11500 | 294107 | 0.00065 (INCONCLUSIVE) | 0.016615 (INCONCLUSIVE) |
| pr15d_v1/10000/absent/k100 | process_cold | 18521571 | 38800 | 18768236 | 0.002095 | 1.013318 (INCONCLUSIVE) |
| pr15d_v1/10000/absent/k100 | warm | 17745450 | 11400 | 286807 | 0.000642 (INCONCLUSIVE) | 0.016162 (INCONCLUSIVE) |
| pr15d_v1/10000/rare/k10 | process_cold | 28167917 | 36501 | 22274329 | 0.001296 (INCONCLUSIVE) | 0.790769 |
| pr15d_v1/10000/rare/k10 | warm | 25809702 | 12201 | 408809 | 0.000473 (INCONCLUSIVE) | 0.015839 (INCONCLUSIVE) |
| pr15d_v1/10000/rare/k100 | process_cold | 28241516 | 39700 | 22216816 | 0.001406 (INCONCLUSIVE) | 0.786672 |
| pr15d_v1/10000/rare/k100 | warm | 25228148 | 12701 | 456011 | 0.000503 (INCONCLUSIVE) | 0.018075 |
| pr15d_v1/10000/medium/k10 | process_cold | 33130018 | 66802 | 27231222 | 0.002016 (INCONCLUSIVE) | 0.82195 |
| pr15d_v1/10000/medium/k10 | warm | 30036440 | 28701 | 847737 | 0.000956 | 0.028224 |
| pr15d_v1/10000/medium/k100 | process_cold | 33349622 | 85703 | 35571244 | 0.00257 (INCONCLUSIVE) | 1.066616 (INCONCLUSIVE) |
| pr15d_v1/10000/medium/k100 | warm | 31300728 | 39701 | 2094048 | 0.001268 (INCONCLUSIVE) | 0.066901 (INCONCLUSIVE) |
| pr15d_v1/10000/common/k10 | process_cold | 48717931 | 110204 | 26457158 | 0.002262 (INCONCLUSIVE) | 0.543068 |
| pr15d_v1/10000/common/k10 | warm | 45125885 | 69302 | 870020 | 0.001536 | 0.01928 (INCONCLUSIVE) |
| pr15d_v1/10000/common/k100 | process_cold | 49606492 | 138399 | 29074960 | 0.00279 (INCONCLUSIVE) | 0.586112 |
| pr15d_v1/10000/common/k100 | warm | 47567116 | 81302 | 1025830 | 0.001709 | 0.021566 (INCONCLUSIVE) |
| pr15d_v1/100000/absent/k10 | process_cold | 186457903 | 86602 | 18801328 | 0.000464 (INCONCLUSIVE) | 0.100834 |
| pr15d_v1/100000/absent/k10 | warm | 183016750 | 16101 | 358909 | 8.8e-05 | 0.001961 (INCONCLUSIVE) |
| pr15d_v1/100000/absent/k100 | process_cold | 185566614 | 59398 | 18680227 | 0.00032 (INCONCLUSIVE) | 0.100666 |
| pr15d_v1/100000/absent/k100 | warm | 183079849 | 16300 | 347808 | 8.9e-05 (INCONCLUSIVE) | 0.0019 (INCONCLUSIVE) |
| pr15d_v1/100000/rare/k10 | process_cold | 284083066 | 49901 | 22813140 | 0.000176 | 0.080304 |
| pr15d_v1/100000/rare/k10 | warm | 264097614 | 19101 | 423510 | 7.2e-05 (INCONCLUSIVE) | 0.001604 (INCONCLUSIVE) |
| pr15d_v1/100000/rare/k100 | process_cold | 284374040 | 55298 | 22658718 | 0.000194 (INCONCLUSIVE) | 0.079679 |
| pr15d_v1/100000/rare/k100 | warm | 263730297 | 17401 | 456011 | 6.6e-05 | 0.001729 |
| pr15d_v1/100000/medium/k10 | process_cold | 817552423 | 210095 | 27973182 | 0.000257 (INCONCLUSIVE) | 0.034216 |
| pr15d_v1/100000/medium/k10 | warm | 797432649 | 164396 | 935328 | 0.000206 (INCONCLUSIVE) | 0.001173 (INCONCLUSIVE) |
| pr15d_v1/100000/medium/k100 | process_cold | 820766616 | 253406 | 35633125 | 0.000309 (INCONCLUSIVE) | 0.043414 |
| pr15d_v1/100000/medium/k100 | warm | 800347939 | 175804 | 2091548 | 0.00022 | 0.002613 |
| pr15d_v1/100000/common/k10 | process_cold | 2085138195 | 677118 | 27164414 | 0.000325 (INCONCLUSIVE) | 0.013028 |
| pr15d_v1/100000/common/k10 | warm | 2100625922 | 584015 | 827221 | 0.000278 | 0.000394 (INCONCLUSIVE) |
| pr15d_v1/100000/common/k100 | process_cold | 2130387638 | 677583 | 29997098 | 0.000318 | 0.014081 |
| pr15d_v1/100000/common/k100 | warm | 2091731269 | 594316 | 1138931 | 0.000284 | 0.000544 (INCONCLUSIVE) |

## Indexing, commit, reopen and size

### quervant

| N | index_ns | commit_ns | reopen_ns | index_bytes | segments |
|---:|---:|---:|---:|---:|---:|
| 10000 | 22313421 | 166034361 | 39812731 | 3090037 | 1 |
| 100000 | 222964281 | 1590419230 | 425926080 | 30965025 | 1 |

### tantivy

| N | index_ns | commit_ns | reopen_ns | index_bytes | segments |
|---:|---:|---:|---:|---:|---:|
| 10000 | 4098795 | 83934454 | 426514 | 298793 | 4 |
| 100000 | 139936750 | 44316106 | 461412 | 2962820 | 4 |

### lucene

| N | index_ns | commit_ns | reopen_ns | index_bytes | segments |
|---:|---:|---:|---:|---:|---:|
| 10000 | 136663678 | 126650855 | 29985162 | 186052 | 1 |
| 100000 | 458095717 | 295606858 | 26384023 | 1858642 | 1 |

## Index artifact size variation (descriptive, never an equality invariant)

Physical byte totals are reported per trial. Differing positive values do
not invalidate a trial; they expose engine layout differences such as
scheduling-dependent segment boundaries.

| Engine | N | trial 1 | trial 2 | trial 3 | min | max | max/min |
|---|---:|---:|---:|---:|---:|---:|---:|
| quervant | 10000 | 3090037 | 3090037 | 3090037 | 3090037 | 3090037 | 1.0 |
| quervant | 100000 | 30965025 | 30965025 | 30965025 | 30965025 | 30965025 | 1.0 |
| tantivy | 10000 | 277739 | 299700 | 298793 | 277739 | 299700 | 1.079071 |
| tantivy | 100000 | 2961601 | 2963073 | 2962820 | 2961601 | 2963073 | 1.000497 |
| lucene | 10000 | 186052 | 186052 | 186052 | 186052 | 186052 | 1.0 |
| lucene | 100000 | 1858642 | 1858642 | 1858642 | 1858642 | 1858642 | 1.0 |

## Serial throughput (`serial_ops_per_second`)

| Engine | N | median ops/s | dispersion |
|---|---:|---:|---:|
| quervant | 10000 | 32.573666 | 1.026212 |
| quervant | 100000 | 1.252022 | 1.017146 |
| tantivy | 10000 | 8323.72498 | 1.031535 |
| tantivy | 100000 | 3678.063379 | 1.077593 |
| lucene | 10000 | 803.448827 | 1.023365 |
| lucene | 100000 | 751.079991 | 1.039523 |

## Measurement limitations

- process_cold means a fresh process and unopened reader, never OS-cold page cache
- 20-sample nearest-rank p95/p99 is a sample distribution, not a production SLA
- serial_ops_per_second is a single sustained serial window, not multi-thread QPS
- RSS/CPU/allocation metrics are NOT_MEASURED when no common method exists
- physical segment counts may differ by engine and are reported, never normalized
- index_bytes may differ across trials for engines whose segment layout is scheduling-dependent; all three observations, min, max and max/min are reported descriptively and are never used to accept or reject a trial
