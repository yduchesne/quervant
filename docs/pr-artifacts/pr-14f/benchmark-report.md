# PR 14F — `pr14_p4_v1` benchmark report

**Status: `QUALIFIED BENCHMARK — PASS` (3 of 3 source-identical trials).**
Source SHA `7df492023397a512e400b03865a989020eff1430` (2026-10-26).
PR 14F overall remains **NOT ACCEPTED** pending durable raw archiving, final-head
CI, independent review and merge authorization. PR 14 is **IN PROGRESS / NOT
ACCEPTED**; v0.1 is **NOT RELEASED**.

## 1. Result boundary

`pr14_p4_v1` compares Quervant local `FsDirectory` with Quervant backed by the
pinned real RustFS. It is **not** a Quervant-vs-Tantivy/Lucene comparison and
**not** a production p99 SLO. Lanes `local-cold`, `local-warm`, `remote-cold` and
`remote-warm` are never pooled. Absolute latencies are host-specific.

## 2. Qualification evidence

| Gate | Result |
|---|---|
| Source SHA | `7df492023397a512e400b03865a989020eff1430` (clean tracked tree) |
| Trials | `t1`, `t2`, `t3` — three independent executions |
| Runner qualification | all `qualified=true`, `idle_confirmed=true`, `dirty=false` |
| Correctness oracle (before timing) | PASS for every trial (W01–W07, W09) |
| Corpus | 20,000 docs, 3 immutable segments, seed `0x14F4_2026` |
| Corpus digest | `80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768` (all trials) |
| Live contention | `clear` for each trial; CPU busy 0.003331 / 0.004990 / 0.003744; competing 0 |
| Provider | `docker.io/rustfs/rustfs@sha256:1803faef…6a3c`, health `1.0.1` |
| W08 | **NOT APPLICABLE (APPROVED)**, never measured |
| `validate-pr14-p4.py --w08-exemption` | `PASS: 3 qualified pr14_p4_v1 trials` |
| `audit-pr14f-trials.py` | `PASS PR14F audit` |
| Raw CSV durable archive | **RAW ARCHIVE BLOCKED** (staged under ignored `target/`; no durable external archive designated) |

## 3. Method

- 3 warmups and 20 measured samples per `(lane, workload)` pair; 14 pairs.
- Local cold (`W09`) and remote cold (`W01`) time open + first query; warm lanes
  time query execution against an already-open snapshot.
- Dataset generation, indexing, commit, oracle evaluation and cache warmup are
  outside every timed region.
- Percentiles use the runner convention: sort samples, index
  `round((n-1)*p)` (half away from zero, clamped); for `n=20`, p50 is the 11th,
  p95 the 19th and p99 the 20th sorted sample.
- Values below are milliseconds, converted from the raw CSV `micros` column.
- `W06`/`W07` CSV `hits` are batch response lengths (`1` and `3`); the separate
  oracle asserts W06 `4 × 5,000 = 20,000` and W07 `S/F/S` before timing.

## 4. Per-trial distributions

### Per-trial lane percentiles (milliseconds)

| Lane | Workload | Trial | n | p50 | p95 | p99 |
|---|---|---|---:|---:|---:|---:|
| local-cold | W09 | t1 | 20 | 3203.178 | 3361.156 | 3366.886 |
| local-warm | W02 | t1 | 20 | 1548.714 | 1639.651 | 1647.372 |
| local-warm | W03 | t1 | 20 | 1364.839 | 1444.822 | 1450.816 |
| local-warm | W04 | t1 | 20 | 1313.949 | 1347.373 | 1358.378 |
| local-warm | W05 | t1 | 20 | 1324.824 | 1349.292 | 1353.332 |
| local-warm | W06 | t1 | 20 | 1568.425 | 1616.971 | 1807.149 |
| local-warm | W07 | t1 | 20 | 2862.781 | 3122.500 | 3280.434 |
| remote-cold | W01 | t1 | 20 | 3516.091 | 3557.184 | 3559.738 |
| remote-warm | W02 | t1 | 20 | 1413.216 | 1434.737 | 1440.284 |
| remote-warm | W03 | t1 | 20 | 1245.983 | 1256.616 | 1256.900 |
| remote-warm | W04 | t1 | 20 | 1212.400 | 1226.050 | 1228.962 |
| remote-warm | W05 | t1 | 20 | 1214.672 | 1225.439 | 1237.108 |
| remote-warm | W06 | t1 | 20 | 1447.598 | 1460.422 | 1515.084 |
| remote-warm | W07 | t1 | 20 | 2747.256 | 2772.637 | 2795.796 |
| local-cold | W09 | t2 | 20 | 2901.792 | 2925.241 | 2930.315 |
| local-warm | W02 | t2 | 20 | 1397.632 | 1410.439 | 1411.300 |
| local-warm | W03 | t2 | 20 | 1228.244 | 1237.251 | 1237.643 |
| local-warm | W04 | t2 | 20 | 1203.588 | 1216.730 | 1218.739 |
| local-warm | W05 | t2 | 20 | 1200.556 | 1213.101 | 1213.676 |
| local-warm | W06 | t2 | 20 | 1437.302 | 1447.363 | 1447.454 |
| local-warm | W07 | t2 | 20 | 2725.252 | 2739.235 | 2739.870 |
| remote-cold | W01 | t2 | 20 | 3429.323 | 3463.362 | 3469.530 |
| remote-warm | W02 | t2 | 20 | 1385.754 | 1403.016 | 1406.399 |
| remote-warm | W03 | t2 | 20 | 1216.481 | 1230.704 | 1233.030 |
| remote-warm | W04 | t2 | 20 | 1192.462 | 1393.423 | 1473.118 |
| remote-warm | W05 | t2 | 20 | 1206.511 | 1239.317 | 1250.493 |
| remote-warm | W06 | t2 | 20 | 1432.107 | 1441.269 | 1457.156 |
| remote-warm | W07 | t2 | 20 | 2708.886 | 2733.318 | 2807.260 |
| local-cold | W09 | t3 | 20 | 2852.247 | 2867.067 | 2926.905 |
| local-warm | W02 | t3 | 20 | 1371.981 | 1386.726 | 1393.518 |
| local-warm | W03 | t3 | 20 | 1210.933 | 1215.810 | 1220.204 |
| local-warm | W04 | t3 | 20 | 1178.904 | 1194.121 | 1195.164 |
| local-warm | W05 | t3 | 20 | 1179.825 | 1188.757 | 1206.308 |
| local-warm | W06 | t3 | 20 | 1411.694 | 1421.088 | 1421.392 |
| local-warm | W07 | t3 | 20 | 2674.793 | 2699.943 | 2709.603 |
| remote-cold | W01 | t3 | 20 | 3380.586 | 4410.201 | 5092.555 |
| remote-warm | W02 | t3 | 20 | 1362.149 | 1377.407 | 1392.775 |
| remote-warm | W03 | t3 | 20 | 1196.551 | 1208.422 | 1209.363 |
| remote-warm | W04 | t3 | 20 | 1168.691 | 1178.390 | 1181.009 |
| remote-warm | W05 | t3 | 20 | 1175.737 | 1183.239 | 1186.679 |
| remote-warm | W06 | t3 | 20 | 1398.550 | 1405.847 | 1412.604 |
| remote-warm | W07 | t3 | 20 | 2668.166 | 2716.069 | 2724.843 |

### Median-of-trial percentiles and observed range (milliseconds)

| Lane | Workload | Trials | Median p50 | Median p95 | Median p99 | p50 range | p95 range | p99 range |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| local-cold | W09 | 3 | 2901.792 | 2925.241 | 2930.315 | 2852.247–3203.178 | 2867.067–3361.156 | 2926.905–3366.886 |
| local-warm | W02 | 3 | 1397.632 | 1410.439 | 1411.300 | 1371.981–1548.714 | 1386.726–1639.651 | 1393.518–1647.372 |
| local-warm | W03 | 3 | 1228.244 | 1237.251 | 1237.643 | 1210.933–1364.839 | 1215.810–1444.822 | 1220.204–1450.816 |
| local-warm | W04 | 3 | 1203.588 | 1216.730 | 1218.739 | 1178.904–1313.949 | 1194.121–1347.373 | 1195.164–1358.378 |
| local-warm | W05 | 3 | 1200.556 | 1213.101 | 1213.676 | 1179.825–1324.824 | 1188.757–1349.292 | 1206.308–1353.332 |
| local-warm | W06 | 3 | 1437.302 | 1447.363 | 1447.454 | 1411.694–1568.425 | 1421.088–1616.971 | 1421.392–1807.149 |
| local-warm | W07 | 3 | 2725.252 | 2739.235 | 2739.870 | 2674.793–2862.781 | 2699.943–3122.500 | 2709.603–3280.434 |
| remote-cold | W01 | 3 | 3429.323 | 3557.184 | 3559.738 | 3380.586–3516.091 | 3463.362–4410.201 | 3469.530–5092.555 |
| remote-warm | W02 | 3 | 1385.754 | 1403.016 | 1406.399 | 1362.149–1413.216 | 1377.407–1434.737 | 1392.775–1440.284 |
| remote-warm | W03 | 3 | 1216.481 | 1230.704 | 1233.030 | 1196.551–1245.983 | 1208.422–1256.616 | 1209.363–1256.900 |
| remote-warm | W04 | 3 | 1192.462 | 1226.050 | 1228.962 | 1168.691–1212.400 | 1178.390–1393.423 | 1181.009–1473.118 |
| remote-warm | W05 | 3 | 1206.511 | 1225.439 | 1237.108 | 1175.737–1214.672 | 1183.239–1239.317 | 1186.679–1250.493 |
| remote-warm | W06 | 3 | 1432.107 | 1441.269 | 1457.156 | 1398.550–1447.598 | 1405.847–1460.422 | 1412.604–1515.084 |
| remote-warm | W07 | 3 | 2708.886 | 2733.318 | 2795.796 | 2668.166–2747.256 | 2716.069–2772.637 | 2724.843–2807.260 |

## 5. Descriptive observations (not a superiority or SLO claim)

- Local cold W09 median-of-trial p50 is 2901.792 ms (trial p50 range
  2852.247–3203.178 ms); remote cold W01 is 3429.323 ms (3380.586–3516.091 ms).
  t3's remote-cold tail is the widest observed (p95 4410.201 ms, p99
  5092.555 ms), consistent with an individual cold-open outlier.
- Warm lanes cluster around 1.17–1.55 s p50 across local and remote in these
  runs. W07 (~2.67–2.86 s) is the largest warm workload because it executes a
  three-query ordered batch; W06 (~1.40–1.57 s) executes the aggregation batch.
- Local and remote warm medians are close on this host. No claim is made that
  one storage mode is faster in general; the differences are host-, cache- and
  provider-configuration-specific and are reported as observed dispersion only.
- Trial-to-trial ranges are displayed in the consolidated table; they are not a
  confidence interval and do not establish statistical significance.

## 6. Provenance and raw evidence

Tracked sanitized reports (original `sha` and `trial` fields preserved; the
`raw_csv` field remains the acquisition-time pointer and is not rewritten):

| Trial | Tracked report | SHA-256 |
|---|---|---|
| t1 | `benchmarks/reports/pr14f-p4-7df492023397-t1.json` | `e7173b0afdee5c2bc883a030df0803810c2ac44aeb902422783ad0c5f47c27a4` |
| t2 | `benchmarks/reports/pr14f-p4-7df492023397-t2.json` | `f7d74b9e6de815c03df2a8f801b035569b6fc48e821882b633ec3b14ec69f2c8` |
| t3 | `benchmarks/reports/pr14f-p4-7df492023397-t3.json` | `8f8086eb424bdb4b766c4ee2d16b14b949c197616cc138432dec938f26de3935` |

Raw CSV and supporting artifacts are staged under the ignored directory
`target/pr14-p4/archive/7df492023397a512e400b03865a989020eff1430/` with a
`SHA256SUMS` manifest:

| Artifact | SHA-256 |
|---|---|
| `pr14-p4-t1.csv` | `e46e27d1eee9e90bd0515c58910aca89886cb1b7ff49a141f92cb3b59f40d5e9` |
| `pr14-p4-t2.csv` | `f31594b5a3a6e5d82bd6bfdfb1710e3090069644c8c5af91728d49b65f801d28` |
| `pr14-p4-t3.csv` | `6df036b37a49e6f8f75142773691e0c2b9118036343bf395f49a8e9b13bae558` |
| `pr14-p4-contention-t1.json` | `7cf80a420622c129c1bfa50b7d65b6e211677eb14f40abd51982d4f253fd0de7` |
| `pr14-p4-contention-t2.json` | `8ee3efd02505f58c70b1774108d2668a2630285a1d0c5f1817031ae5f9f0ff99` |
| `pr14-p4-contention-t3.json` | `314d555947a21da7b9ca9a811272742095d9621218a304ad6b1908e8c36c59b2` |
| `pr14-p4-t1-run.log` | `86e37671fdcdaf3ee396af031d7787267c41cfd7a00525eb69893f8c3e465e73` |
| `pr14-p4-t2-run.log` | `408f1549c000d3658ae3825e918428acda1731db5559b4246fa87e431c090a64` |
| `pr14-p4-t3-run.log` | `d081bafcb4780f02110b0e72ed3e12febd8bc7dcad4c4228a97b22ef5af1baca` |

**RAW ARCHIVE BLOCKED.** The staging directory is disposable and is not claimed
as a durable archive. `target/` is not checked in; validator/auditor revalidation
requires the archived CSV files. A durable operator-designated archive locator
must be recorded before any fully reproducible acceptance claim.

The historical `benchmarks/reports/pr14-p4-t{1,2,3}.json` remain byte-identical
(SHA-256 in `baseline-inventory.md`) and are provenance only.

## 7. Non-claims

- No cross-engine (Tantivy/Lucene) comparison or superiority claim.
- No production p99, SLO, throughput or capacity claim.
- No claim that W08 was measured or passed.
- No pooling of cold/warm or local/remote lanes.
- No statistical-significance claim from three trials.
- No claim of durable raw archiving, final-head CI, independent review, merge,
  PR 14 acceptance or v0.1 release.
