# PR 14F — `pr14_p4_v1` benchmark report

**Status: `QUALIFIED BENCHMARK — PASS` (3 of 3 source-identical trials).**
Source SHA `7df492023397a512e400b03865a989020eff1430` (2026-10-26).
PR 14F overall remains **NOT ACCEPTED** pending final binding-head CI,
independent review and merge authorization. PR 14 is **IN PROGRESS / NOT
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
| Raw CSV local package | **VERIFIED** — deterministic `tar.gz`, self-verifying checksums |
| Durable raw archive | **PASS (operator-attested)** — Google Drive file `1nt02UI8…`, declared SHA-256 matches local package |
| Baseline-head CI (`4c94ba8`) | **PASS** — `rust`, `msrv`, `rustfs` (PR #67 run 40424504536) |
| Archival-head CI (`bd1fed7`) | **PASS** — `rust`, `msrv`, `rustfs` (PR #67 run 40441448948) |
| Previous final-binding-head CI (`8887541`) | **PASS** — `rust`, `msrv`, `rustfs` (PR #67 run 40443185707) |
| Current binding-head CI | **PENDING** — this documentation commit advances the head |

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
| `summarize-pr14f-trials.py` (read-only analysis) | `d82f0521c0d86015fc02ab8a777f351ba19b5e9cb79a3a4913564f0d6d460ed1` |

Deterministic archive package:

| Item | Value |
|---|---|
| Package | `target/pr14-p4/package/quervant-pr14f-p4-7df492023397-raw-evidence.tar.gz` |
| SHA-256 | `6cef9c713012c9040391b7a57c82027295781dcf2b42228f7912f2c5578fe66d` |
| Size | 15,491 bytes |
| Determinism | rebuild byte-identical |
| Package checksums | `PACKAGE-SHA256SUMS` verifies; `original-archive/SHA256SUMS` verifies |
| Members | 21 files (3 CSVs, 3 contention JSON, 3 logs, 3 published reports, manifest, original checksums, analysis helper, READMEs) |
| Inventory SHA-256 | `d7c5c707a3f040ab5710e0dad86d5de5d44a7d2238ab9e147c328568123788f5` |

**RAW ARCHIVE VERIFIED — DURABLE ARCHIVE ESTABLISHED (operator-attested).** The
maintainer uploaded the package to Google Drive and declared the same SHA-256 as
the local package:

| Durable archive item | Value |
|---|---|
| Location | `https://drive.google.com/file/d/1nt02UI8WFui4xDRv5Oxuh5RKM77oeIVY/view?usp=drive_link` |
| File id | `1nt02UI8WFui4xDRv5Oxuh5RKM77oeIVY` |
| Declared SHA-256 | `6cef9c713012c9040391b7a57c82027295781dcf2b42228f7912f2c5578fe66d` |
| Local SHA-256 | `6cef9c713012c9040391b7a57c82027295781dcf2b42228f7912f2c5578fe66d` |
| Size | 15,491 bytes (local package) |
| Retention | operator-managed Google Drive storage, independent of the local checkout |

Residual verification limitation: the agent could not independently re-download
the remote object without Google credentials (the public endpoints returned a
sign-in page). Remote integrity is therefore **operator-attested**, not
agent-verified. The local package remains staged under ignored `target/` and is
not itself the durable copy.

The historical `benchmarks/reports/pr14-p4-t{1,2,3}.json` remain byte-identical
(SHA-256 in `baseline-inventory.md`) and are provenance only.

## 7. Non-claims

- No cross-engine (Tantivy/Lucene) comparison or superiority claim.
- No production p99, SLO, throughput or capacity claim.
- No claim that W08 was measured or passed.
- No pooling of cold/warm or local/remote lanes.
- No statistical-significance claim from three trials.
- No claim of independent agent-side remote re-download; durable integrity is
  operator-attested. No final binding-head CI, independent review, merge, PR 14
  acceptance or v0.1 release is claimed.

## 8. SR-14F-01 fixup note — 2026-10-27

The performance numbers in sections 4–5 belong to the historical campaign at
`7df4920…`, whose remote-cold W01 timing preceded the full remote correctness
oracle. They are **not** current acceptance evidence for SR-14F-01 and are not
relabelled or reused.

Source lock `8cfd2fce436ea99d57d2699471ab49d2cd1a3446` corrects the ordering:
the complete oracle runs untimed before the first cold stopwatch, with marker
`PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS`. No new benchmark campaign has been run,
so this report contains **no new latency values**. A new campaign and new
archive are required.

## 9. SR-14F-01 source-lock update — 2026-10-27

Source lock `8cfd2fc` was superseded after its first trial failed in the
pre-cold oracle (`RemoteIndex::snapshot()` was the create-time empty
generation). The current measurement source lock is
`d12a97537a5131953c948c3a90065a73c3d24b40`, which uses
`RemoteIndex::open_existing` for the committed-generation oracle.

No new benchmark campaign has been run and no new latency values exist. All
numbers in this report remain historical `7df4920…` evidence only.


## 10. SR-14F-01 qualified campaign — source lock `d12a975` — 2026-10-27

This is the current qualified campaign for SR-14F-01. Sections 4–5 above remain
the historical `7df4920…` campaign and are not mixed with these numbers.

All three trials ran the full remote correctness oracle before the first timed
remote-cold W01 open, emitted `PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS`, and passed
the validator and strict auditor. The current report paths are
`benchmarks/reports/pr14f-p4-d12a97537a51-t{1,2,3}.json`.

### Per-trial lane percentiles (milliseconds)

| Lane | Workload | Trial | n | p50 | p95 | p99 |
|---|---|---|---:|---:|---:|---:|
| local-cold | W09 | t1 | 20 | 3039.016 | 3296.783 | 3412.460 |
| local-warm | W02 | t1 | 20 | 1448.696 | 1470.743 | 1479.947 |
| local-warm | W03 | t1 | 20 | 1280.037 | 1316.269 | 1321.386 |
| local-warm | W04 | t1 | 20 | 1248.255 | 1259.301 | 1260.771 |
| local-warm | W05 | t1 | 20 | 1240.162 | 1250.824 | 1252.158 |
| local-warm | W06 | t1 | 20 | 1480.148 | 1495.049 | 1570.648 |
| local-warm | W07 | t1 | 20 | 2831.476 | 2939.945 | 2964.279 |
| remote-cold | W01 | t1 | 20 | 3540.953 | 3612.046 | 3612.558 |
| remote-warm | W02 | t1 | 20 | 1436.184 | 1459.367 | 1480.092 |
| remote-warm | W03 | t1 | 20 | 1258.109 | 1283.036 | 1291.473 |
| remote-warm | W04 | t1 | 20 | 1230.266 | 1242.398 | 1279.543 |
| remote-warm | W05 | t1 | 20 | 1230.398 | 1244.330 | 1287.837 |
| remote-warm | W06 | t1 | 20 | 1486.509 | 1541.438 | 1549.473 |
| remote-warm | W07 | t1 | 20 | 2793.201 | 2827.992 | 2846.907 |
| local-cold | W09 | t2 | 20 | 2949.229 | 2976.962 | 3037.494 |
| local-warm | W02 | t2 | 20 | 1424.519 | 1445.863 | 1456.156 |
| local-warm | W03 | t2 | 20 | 1253.914 | 1267.422 | 1272.960 |
| local-warm | W04 | t2 | 20 | 1225.624 | 1261.869 | 1263.492 |
| local-warm | W05 | t2 | 20 | 1227.445 | 1239.246 | 1257.093 |
| local-warm | W06 | t2 | 20 | 1488.068 | 1547.814 | 1571.946 |
| local-warm | W07 | t2 | 20 | 2794.092 | 2831.158 | 2854.793 |
| remote-cold | W01 | t2 | 20 | 3500.131 | 3549.085 | 3564.323 |
| remote-warm | W02 | t2 | 20 | 1420.116 | 1432.437 | 1437.727 |
| remote-warm | W03 | t2 | 20 | 1246.563 | 1260.088 | 1260.725 |
| remote-warm | W04 | t2 | 20 | 1215.212 | 1233.747 | 1239.168 |
| remote-warm | W05 | t2 | 20 | 1217.794 | 1262.890 | 1268.416 |
| remote-warm | W06 | t2 | 20 | 1456.904 | 1477.826 | 1543.335 |
| remote-warm | W07 | t2 | 20 | 2780.488 | 2961.996 | 3268.642 |
| local-cold | W09 | t3 | 20 | 2921.333 | 2947.898 | 2970.965 |
| local-warm | W02 | t3 | 20 | 1402.529 | 1421.785 | 1430.930 |
| local-warm | W03 | t3 | 20 | 1238.851 | 1271.341 | 1277.975 |
| local-warm | W04 | t3 | 20 | 1205.796 | 1227.776 | 1238.797 |
| local-warm | W05 | t3 | 20 | 1213.090 | 1879.526 | 2089.151 |
| local-warm | W06 | t3 | 20 | 1492.731 | 1676.955 | 1737.331 |
| local-warm | W07 | t3 | 20 | 2800.083 | 2928.701 | 3263.819 |
| remote-cold | W01 | t3 | 20 | 3486.366 | 3536.468 | 3561.283 |
| remote-warm | W02 | t3 | 20 | 1424.406 | 1442.962 | 1460.684 |
| remote-warm | W03 | t3 | 20 | 1245.666 | 1269.318 | 1278.869 |
| remote-warm | W04 | t3 | 20 | 1223.063 | 1236.854 | 1288.889 |
| remote-warm | W05 | t3 | 20 | 1243.010 | 1299.340 | 1307.184 |
| remote-warm | W06 | t3 | 20 | 1446.319 | 1469.470 | 1472.482 |
| remote-warm | W07 | t3 | 20 | 2768.627 | 2827.341 | 2856.214 |

### Median-of-trial percentiles and observed range (milliseconds)

| Lane | Workload | Trials | Median p50 | Median p95 | Median p99 | p50 range | p95 range | p99 range |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| local-cold | W09 | 3 | 2949.229 | 2976.962 | 3037.494 | 2921.333–3039.016 | 2947.898–3296.783 | 2970.965–3412.460 |
| local-warm | W02 | 3 | 1424.519 | 1445.863 | 1456.156 | 1402.529–1448.696 | 1421.785–1470.743 | 1430.930–1479.947 |
| local-warm | W03 | 3 | 1253.914 | 1271.341 | 1277.975 | 1238.851–1280.037 | 1267.422–1316.269 | 1272.960–1321.386 |
| local-warm | W04 | 3 | 1225.624 | 1259.301 | 1260.771 | 1205.796–1248.255 | 1227.776–1261.869 | 1238.797–1263.492 |
| local-warm | W05 | 3 | 1227.445 | 1250.824 | 1257.093 | 1213.090–1240.162 | 1239.246–1879.526 | 1252.158–2089.151 |
| local-warm | W06 | 3 | 1488.068 | 1547.814 | 1571.946 | 1480.148–1492.731 | 1495.049–1676.955 | 1570.648–1737.331 |
| local-warm | W07 | 3 | 2800.083 | 2928.701 | 2964.279 | 2794.092–2831.476 | 2831.158–2939.945 | 2854.793–3263.819 |
| remote-cold | W01 | 3 | 3500.131 | 3549.085 | 3564.323 | 3486.366–3540.953 | 3536.468–3612.046 | 3561.283–3612.558 |
| remote-warm | W02 | 3 | 1424.406 | 1442.962 | 1460.684 | 1420.116–1436.184 | 1432.437–1459.367 | 1437.727–1480.092 |
| remote-warm | W03 | 3 | 1246.563 | 1269.318 | 1278.869 | 1245.666–1258.109 | 1260.088–1283.036 | 1260.725–1291.473 |
| remote-warm | W04 | 3 | 1223.063 | 1236.854 | 1279.543 | 1215.212–1230.266 | 1233.747–1242.398 | 1239.168–1288.889 |
| remote-warm | W05 | 3 | 1230.398 | 1262.890 | 1287.837 | 1217.794–1243.010 | 1244.330–1299.340 | 1268.416–1307.184 |
| remote-warm | W06 | 3 | 1456.904 | 1477.826 | 1543.335 | 1446.319–1486.509 | 1469.470–1541.438 | 1472.482–1549.473 |
| remote-warm | W07 | 3 | 2780.488 | 2827.992 | 2856.214 | 2768.627–2793.201 | 2827.341–2961.996 | 2846.907–3268.642 |


Cold/warm and local/remote lanes are not pooled. Values are host-specific
descriptive quantiles, not an SLO or cross-engine comparison. The new durable
archive upload is pending; see `sr14f01-fixup.md`.

## 11. SR-14F-01 durable archive — 2026-10-27

The new SR-14F-01 package is durably archived at Google Drive file
`18VqahZSMlRRnijXppRlJCVcUzTi9Zp4z` with declared SHA-256
`373d3b756598b1a70f1501530167e7399a47d9172799b0bf05a40ee6ada181e2`
(17,674 bytes), matching the local package. Remote integrity is
operator-attested; the agent could not re-download the object without Google
credentials. The prior `7df4920` Drive archive is historical only.
