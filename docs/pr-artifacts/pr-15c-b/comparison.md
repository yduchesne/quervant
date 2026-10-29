# PR 15C-B before/after comparison — UNQUALIFIED

- Before source SHA: `42b19445dd79a90d8701b4306e305c6e4e44cd57`
- After source SHA: `b4682d0fdebaa691b55bb29b32f3499781a8fc04`
- Workload version: `pr15b_v1`
- Canonical fixture: `104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087`
- Before trials: 3 (none)
- After trials: 3 (none)

> **UNQUALIFIED — no speedup claim is made.** Every published comparison
> requires all of the following, and at least one failed:
>
> - before: before/trial-1/trial.json: frozen validator rejection ['operator idle attestation missing']
> - before: before/trial-2/trial.json: frozen validator rejection ['operator idle attestation missing']
> - before: before/trial-3/trial.json: frozen validator rejection ['operator idle attestation missing']
> - before: profiler_status is AVAILABLE on this host but profiler_evidence is empty in 3 trial(s) (before/trial-1/trial.json); the frozen validate-pr15b.py requires captured evidence in that case and the frozen run-pr15b.sh never records any, so these trials are unqualified independently of the idle attestation (STOP-15CB-01)
> - after: after/trial-1/trial.json: frozen validator rejection ['operator idle attestation missing']
> - after: after/trial-2/trial.json: frozen validator rejection ['operator idle attestation missing']
> - after: after/trial-3/trial.json: frozen validator rejection ['operator idle attestation missing']
> - after: profiler_status is AVAILABLE on this host but profiler_evidence is empty in 3 trial(s) (after/trial-1/trial.json); the frozen validate-pr15b.py requires captured evidence in that case and the frozen run-pr15b.sh never records any, so these trials are unqualified independently of the idle attestation (STOP-15CB-01)

`speedup = before_median_of_medians / after_median_of_medians` (> 1 means the after build is faster). `delta_pct = 100 * (after - before) / before` (> 0 means a regression).

Lane classification counts: 30 improvement, 0 regression, 0 inconclusive of 30 lanes.

## Descriptor groups

Descriptive only. Group figures are the median and range of the visible per-lane speedups; no cross-lane arithmetic average is computed.

| group | lanes | speedup median | speedup min | speedup max | impr | regr | inconc |
|---|---:|---:|---:|---:|---:|---:|---:|
| U01/U02 no/rare hits | 6 | 24.3174 | 8.3197 | 59.1406 | 6 | 0 | 0 |
| U03/U04 lexical mixed | 6 | 4.4868 | 1.6281 | 5.1254 | 6 | 0 | 0 |
| U05-U10 typed/JSON/sort/projection/aggregation/batch | 9 | 4.4900 | 1.7978 | 7.2707 | 9 | 0 | 0 |
| U11 segment topology | 6 | 5.7027 | 2.5559 | 14.5317 | 6 | 0 | 0 |
| U12 PIT pages | 2 | 4.4883 | 4.4788 | 4.4978 | 2 | 0 | 0 |
| U13 geo | 1 | 5.1458 | 5.1458 | 5.1458 | 1 | 0 | 0 |

## Lane detail

Raw three-trial medians are preserved. `INCONCLUSIVE` reflects the predeclared dispersion/overlap/effect-size heuristics, not a significance test.

| lane | N | S | K | before trials (ns) | after trials (ns) | before MoM | after MoM | speedup | delta % | classification |
|---|---:|---:|---:|---|---|---:|---:|---:|---:|---|
| `pr15b_v1/u01/n100000_s4/k100/absent` | 100000 | 4 | 100 | 239055800.8, 230405156.5, 230994792.2 | 3910901.5, 3893589.6, 3905856.5 | 230994792.2 | 3905856.5 | 59.1406 | -98.31 | IMPROVEMENT |
| `pr15b_v1/u01/n10000_s4/k100/absent` | 10000 | 4 | 100 | 24563546.3, 23355584.4, 23137735.6 | 443589.4, 438819.9, 441927.0 | 23355584.4 | 441927.0 | 52.8494 | -98.11 | IMPROVEMENT |
| `pr15b_v1/u01/n2000_s4/k100/absent` | 2000 | 4 | 100 | 4891569.4, 4776582.6, 4776198.2 | 120758.7, 120934.7, 122259.6 | 4776582.6 | 120934.7 | 39.4972 | -97.47 | IMPROVEMENT |
| `pr15b_v1/u02/n100000_s4/k100/rare` | 100000 | 4 | 100 | 330581121.0, 325464665.0, 326020279.5 | 39768854.6, 38943681.6, 39186455.2 | 326020279.5 | 39186455.2 | 8.3197 | -87.98 | IMPROVEMENT |
| `pr15b_v1/u02/n10000_s4/k100/rare` | 10000 | 4 | 100 | 33566823.4, 32298230.4, 32208716.3 | 3534684.5, 3521830.7, 3560194.1 | 32298230.4 | 3534684.5 | 9.1375 | -89.06 | IMPROVEMENT |
| `pr15b_v1/u02/n2000_s4/k100/rare` | 2000 | 4 | 100 | 6880787.5, 6584673.4, 6468146.9 | 749632.6, 759212.8, 780990.3 | 6584673.4 | 759212.8 | 8.6730 | -88.47 | IMPROVEMENT |
| `pr15b_v1/u03/n100000_s4/k100/medium` | 100000 | 4 | 100 | 679839237.0, 663516234.5, 669264336.0 | 378641435.0, 378711910.5, 375117981.0 | 669264336.0 | 378641435.0 | 1.7675 | -43.42 | IMPROVEMENT |
| `pr15b_v1/u03/n10000_s4/k100/medium` | 10000 | 4 | 100 | 37720416.4, 36933339.8, 36847221.9 | 8067204.9, 8096753.3, 8058124.1 | 36933339.8 | 8067204.9 | 4.5782 | -78.16 | IMPROVEMENT |
| `pr15b_v1/u03/n2000_s4/k100/medium` | 2000 | 4 | 100 | 9163747.6, 8839874.0, 8782006.9 | 1865859.4, 1876899.6, 1874549.4 | 8839874.0 | 1874549.4 | 4.7157 | -78.79 | IMPROVEMENT |
| `pr15b_v1/u04/n100000_s4/k100/common-mixed` | 100000 | 4 | 100 | 752673763.0, 738290290.5, 743931673.0 | 458084358.5, 456926205.5, 452597530.0 | 743931673.0 | 456926205.5 | 1.6281 | -38.58 | IMPROVEMENT |
| `pr15b_v1/u04/n10000_s4/k100/common-mixed` | 10000 | 4 | 100 | 38033572.3, 37622082.9, 37263377.7 | 8631484.4, 8559567.3, 8518747.7 | 37622082.9 | 8559567.3 | 4.3953 | -77.25 | IMPROVEMENT |
| `pr15b_v1/u04/n2000_s4/k100/common-mixed` | 2000 | 4 | 100 | 7269358.2, 7185472.0, 7191545.9 | 1399140.3, 1403107.3, 1403417.3 | 7191545.9 | 1403107.3 | 5.1254 | -80.49 | IMPROVEMENT |
| `pr15b_v1/u05/n10000_s4/k100/cidr-time` | 10000 | 4 | 100 | 33687460.9, 33667070.7, 33706410.0 | 4632983.9, 4633340.2, 4731979.9 | 33687460.9 | 4633340.2 | 7.2707 | -86.25 | IMPROVEMENT |
| `pr15b_v1/u06/n10000_s4/k100/json-scalar` | 10000 | 4 | 100 | 38583087.6, 38300619.0, 38432030.7 | 9513473.7, 9639997.4, 9532547.7 | 38432030.7 | 9532547.7 | 4.0317 | -75.20 | IMPROVEMENT |
| `pr15b_v1/u07/n10000_s4/k10/sort-n` | 10000 | 4 | 10 | 35020084.4, 34526066.5, 34412324.3 | 5780118.6, 5910323.0, 5779028.0 | 34526066.5 | 5780118.6 | 5.9732 | -83.26 | IMPROVEMENT |
| `pr15b_v1/u07/n10000_s4/k100/sort-n` | 10000 | 4 | 100 | 37106894.7, 37087149.4, 37294596.8 | 8141521.5, 8270735.9, 8264352.6 | 37106894.7 | 8264352.6 | 4.4900 | -77.73 | IMPROVEMENT |
| `pr15b_v1/u07/n10000_s4/k1000/sort-n` | 10000 | 4 | 1000 | 67366858.0, 67458106.9, 66835437.4 | 37254754.2, 37940838.6, 37472016.5 | 67366858.0 | 37472016.5 | 1.7978 | -44.38 | IMPROVEMENT |
| `pr15b_v1/u08/n10000_s4/k100/fields-host-n` | 10000 | 4 | 100 | 37593136.6, 36760213.0, 37028325.4 | 7998289.2, 8196670.6, 8200943.3 | 37028325.4 | 8196670.6 | 4.5175 | -77.86 | IMPROVEMENT |
| `pr15b_v1/u08/n10000_s4/k100/source` | 10000 | 4 | 100 | 37260824.0, 36871998.5, 36628860.3 | 8082092.2, 8209332.5, 8163928.8 | 36871998.5 | 8163928.8 | 4.5165 | -77.86 | IMPROVEMENT |
| `pr15b_v1/u09/n10000_s4/k100/aggregate-host` | 10000 | 4 | 100 | 45072756.0, 43894939.0, 43819498.2 | 15163172.8, 15260954.0, 15275238.5 | 43894939.0 | 15260954.0 | 2.8763 | -65.23 | IMPROVEMENT |
| `pr15b_v1/u10/n10000_s4/k100/serial-batch` | 10000 | 4 | 100 | 116960464.2, 117465969.5, 114981195.7 | 28581621.7, 28636823.2, 28804176.4 | 116960464.2 | 28636823.2 | 4.0843 | -75.52 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s1/k100/common-mixed` | 10000 | 1 | 100 | 75994491.9, 74485291.5, 74038599.9 | 29213638.1, 29109694.3, 29142323.1 | 74485291.5 | 29142323.1 | 2.5559 | -60.88 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s1/k100/rare` | 10000 | 1 | 100 | 58617764.2, 56859959.7, 57348942.4 | 11438810.9, 11420484.5, 11620974.9 | 57348942.4 | 11438810.9 | 5.0135 | -80.05 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s16/k100/common-mixed` | 10000 | 16 | 100 | 29588873.0, 29517452.5, 29125996.7 | 4647353.3, 4588805.7, 4618045.6 | 29517452.5 | 4618045.6 | 6.3918 | -84.35 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s16/k100/rare` | 10000 | 16 | 100 | 26876820.6, 26400117.0, 26661100.5 | 1791455.1, 1834686.4, 1834829.1 | 26661100.5 | 1834686.4 | 14.5317 | -93.12 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s4/k100/common-mixed` | 10000 | 4 | 100 | 37704163.8, 36722919.7, 37301112.6 | 8601717.3, 8687887.5, 8711354.5 | 37301112.6 | 8687887.5 | 4.2935 | -76.71 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s4/k100/rare` | 10000 | 4 | 100 | 32801273.6, 32393250.0, 32175599.8 | 3538763.5, 3517073.4, 3577909.8 | 32393250.0 | 3538763.5 | 9.1538 | -89.08 | IMPROVEMENT |
| `pr15b_v1/u12/n10000_s4/k100/page-1` | 10000 | 4 | 100 | 37433155.0, 36554474.7, 36933485.5 | 8249419.0, 8164453.3, 8211386.0 | 36933485.5 | 8211386.0 | 4.4978 | -77.77 | IMPROVEMENT |
| `pr15b_v1/u12/n10000_s4/k100/page-2` | 10000 | 4 | 100 | 37418955.7, 36776260.7, 37094182.2 | 8278834.2, 8391396.4, 8282221.7 | 37094182.2 | 8282221.7 | 4.4788 | -77.67 | IMPROVEMENT |
| `pr15b_v1/u13/geo_n8_s1/k100/geo-bbox` | 8 | 1 | 100 | 51246.8, 51172.2, 50416.8 | 10062.8, 9944.4, 9907.3 | 51172.2 | 9944.4 | 5.1458 | -80.57 | IMPROVEMENT |

## Limitations

- Per-lane ratios are descriptive medians of three independent trial medians.
- Independent trials do not estimate production request p95 or p99 latency.
- No cross-lane arithmetic average of speedups is computed or published.
- Group figures are descriptive medians and ranges over visible lanes only.
- INCONCLUSIVE means the predeclared noise/effect heuristics cannot separate the measured difference from trial-to-trial dispersion; it is not a significance test and not evidence of no effect.
- Criterion estimates are microbenchmark iteration distributions, not an SLA.
