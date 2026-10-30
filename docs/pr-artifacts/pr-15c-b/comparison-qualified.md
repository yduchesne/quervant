# PR 15C-B before/after comparison — QUALIFIED

- Before source SHA: `f7d6be721ba625cbd90f24cfbcd8551cc8ba309a`
- After source SHA: `04ad3509c86d08fe296adde1d67c19aa7c7f2651`
- Workload version: `pr15b_v1`
- Canonical fixture: `104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087`
- Before trials: 3 (aggregate+trials)
- After trials: 3 (aggregate+trials)

`speedup = before_median_of_medians / after_median_of_medians` (> 1 means the after build is faster). `delta_pct = 100 * (after - before) / before` (> 0 means a regression).

Lane classification counts: 13 improvement, 0 regression, 17 inconclusive of 30 lanes.

## Descriptor groups

Descriptive only. Group figures are the median and range of the visible per-lane speedups; no cross-lane arithmetic average is computed.

| group | lanes | speedup median | speedup min | speedup max | impr | regr | inconc |
|---|---:|---:|---:|---:|---:|---:|---:|
| U01/U02 no/rare hits | 6 | 26.0535 | 9.3597 | 64.2472 | 1 | 0 | 5 |
| U03/U04 lexical mixed | 6 | 4.8789 | 1.8136 | 5.7439 | 2 | 0 | 4 |
| U05-U10 typed/JSON/sort/projection/aggregation/batch | 9 | 4.9651 | 2.0269 | 7.7358 | 2 | 0 | 7 |
| U11 segment topology | 6 | 6.5478 | 2.9108 | 16.1651 | 5 | 0 | 1 |
| U12 PIT pages | 2 | 5.0653 | 4.9706 | 5.1599 | 2 | 0 | 0 |
| U13 geo | 1 | 5.7588 | 5.7588 | 5.7588 | 1 | 0 | 0 |

## Lane detail

Raw three-trial medians are preserved. `INCONCLUSIVE` reflects the predeclared dispersion/overlap/effect-size heuristics, not a significance test.

| lane | N | S | K | before trials (ns) | after trials (ns) | before MoM | after MoM | speedup | delta % | classification |
|---|---:|---:|---:|---|---|---:|---:|---:|---:|---|
| `pr15b_v1/u01/n100000_s4/k100/absent` | 100000 | 4 | 100 | 259006861.0, 247212449.2, 277078680.5 | 4477714.0, 4031408.2, 3965256.0 | 259006861.0 | 4031408.2 | 64.2472 | -98.44 | INCONCLUSIVE |
| `pr15b_v1/u01/n10000_s4/k100/absent` | 10000 | 4 | 100 | 26567598.7, 25417068.1, 27319872.4 | 481683.5, 457888.7, 452909.9 | 26567598.7 | 457888.7 | 58.0220 | -98.28 | IMPROVEMENT |
| `pr15b_v1/u01/n2000_s4/k100/absent` | 2000 | 4 | 100 | 5376475.7, 5260026.4, 5682245.0 | 138827.2, 128161.5, 123723.2 | 5376475.7 | 128161.5 | 41.9508 | -97.62 | INCONCLUSIVE |
| `pr15b_v1/u02/n100000_s4/k100/rare` | 100000 | 4 | 100 | 373485489.5, 340007050.5, 384896874.5 | 42875930.2, 39550860.9, 39903469.6 | 373485489.5 | 39903469.6 | 9.3597 | -89.32 | INCONCLUSIVE |
| `pr15b_v1/u02/n10000_s4/k100/rare` | 10000 | 4 | 100 | 38932970.4, 33988855.2, 38123974.9 | 3932334.8, 3668296.5, 3753779.7 | 38123974.9 | 3753779.7 | 10.1562 | -90.15 | INCONCLUSIVE |
| `pr15b_v1/u02/n2000_s4/k100/rare` | 2000 | 4 | 100 | 7763881.6, 7149390.8, 7857703.3 | 880225.1, 793858.2, 790768.2 | 7763881.6 | 793858.2 | 9.7799 | -89.77 | INCONCLUSIVE |
| `pr15b_v1/u03/n100000_s4/k100/medium` | 100000 | 4 | 100 | 766145770.0, 703254817.5, 790007681.0 | 408466933.5, 383212085.5, 385349049.5 | 766145770.0 | 385349049.5 | 1.9882 | -49.70 | INCONCLUSIVE |
| `pr15b_v1/u03/n10000_s4/k100/medium` | 10000 | 4 | 100 | 42849033.6, 38461470.9, 44276613.3 | 8737000.9, 8372108.8, 8575254.2 | 42849033.6 | 8575254.2 | 4.9968 | -79.99 | INCONCLUSIVE |
| `pr15b_v1/u03/n2000_s4/k100/medium` | 2000 | 4 | 100 | 10273880.9, 9454461.8, 10466586.6 | 2026253.2, 1956533.5, 1939613.9 | 10273880.9 | 1956533.5 | 5.2511 | -80.96 | INCONCLUSIVE |
| `pr15b_v1/u04/n100000_s4/k100/common-mixed` | 100000 | 4 | 100 | 915058473.0, 829342561.5, 827018135.0 | 476873362.0, 457278837.0, 456786355.5 | 829342561.5 | 457278837.0 | 1.8136 | -44.86 | INCONCLUSIVE |
| `pr15b_v1/u04/n10000_s4/k100/common-mixed` | 10000 | 4 | 100 | 44174958.3, 40797480.3, 42718074.0 | 9200367.5, 8825445.1, 8972400.6 | 42718074.0 | 8972400.6 | 4.7611 | -79.00 | IMPROVEMENT |
| `pr15b_v1/u04/n2000_s4/k100/common-mixed` | 2000 | 4 | 100 | 8470797.4, 7738333.2, 8450027.4 | 1507718.3, 1471134.0, 1440576.8 | 8450027.4 | 1471134.0 | 5.7439 | -82.59 | IMPROVEMENT |
| `pr15b_v1/u05/n10000_s4/k100/cidr-time` | 10000 | 4 | 100 | 40349234.9, 37401120.8, 37735493.4 | 5003106.5, 4878026.1, 4806810.5 | 37735493.4 | 4878026.1 | 7.7358 | -87.07 | IMPROVEMENT |
| `pr15b_v1/u06/n10000_s4/k100/json-scalar` | 10000 | 4 | 100 | 48867311.2, 41960680.7, 43509010.8 | 10147179.5, 9806425.2, 9867031.2 | 43509010.8 | 9867031.2 | 4.4095 | -77.32 | INCONCLUSIVE |
| `pr15b_v1/u07/n10000_s4/k10/sort-n` | 10000 | 4 | 10 | 40106643.9, 37485935.8, 39424523.6 | 6089517.0, 5986604.9, 5991483.8 | 39424523.6 | 5991483.8 | 6.5801 | -84.80 | IMPROVEMENT |
| `pr15b_v1/u07/n10000_s4/k100/sort-n` | 10000 | 4 | 100 | 45211614.8, 39339248.0, 42143474.2 | 8633349.2, 8388758.4, 8336447.0 | 42143474.2 | 8388758.4 | 5.0238 | -80.09 | INCONCLUSIVE |
| `pr15b_v1/u07/n10000_s4/k1000/sort-n` | 10000 | 4 | 1000 | 80889227.2, 69429509.2, 76519886.0 | 38302873.6, 37404462.4, 37752864.7 | 76519886.0 | 37752864.7 | 2.0269 | -50.66 | INCONCLUSIVE |
| `pr15b_v1/u08/n10000_s4/k100/fields-host-n` | 10000 | 4 | 100 | 43775669.8, 38903450.4, 41513214.9 | 8492296.7, 8322298.3, 8282984.3 | 41513214.9 | 8322298.3 | 4.9882 | -79.95 | INCONCLUSIVE |
| `pr15b_v1/u08/n10000_s4/k100/source` | 10000 | 4 | 100 | 44796043.0, 39097423.6, 41506857.3 | 8554236.9, 8338470.1, 8359732.1 | 41506857.3 | 8359732.1 | 4.9651 | -79.86 | INCONCLUSIVE |
| `pr15b_v1/u09/n10000_s4/k100/aggregate-host` | 10000 | 4 | 100 | 51916498.8, 60581363.4, 50332323.3 | 15895599.4, 15802288.0, 15834031.2 | 51916498.8 | 15834031.2 | 3.2788 | -69.50 | INCONCLUSIVE |
| `pr15b_v1/u10/n10000_s4/k100/serial-batch` | 10000 | 4 | 100 | 134656927.2, 157675626.0, 130836670.5 | 29825024.4, 29551850.3, 29110278.9 | 134656927.2 | 29551850.3 | 4.5566 | -78.05 | INCONCLUSIVE |
| `pr15b_v1/u11/n10000_s1/k100/common-mixed` | 10000 | 1 | 100 | 86556654.3, 87582320.7, 86793438.3 | 29894019.0, 29592074.3, 29817783.6 | 86793438.3 | 29817783.6 | 2.9108 | -65.65 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s1/k100/rare` | 10000 | 1 | 100 | 67483014.8, 76437693.4, 65133194.1 | 11809348.9, 11441246.2, 11438036.4 | 67483014.8 | 11441246.2 | 5.8982 | -83.05 | INCONCLUSIVE |
| `pr15b_v1/u11/n10000_s16/k100/common-mixed` | 10000 | 16 | 100 | 33915589.1, 34598531.4, 32771766.4 | 4759238.1, 4674771.9, 4712237.1 | 33915589.1 | 4712237.1 | 7.1973 | -86.11 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s16/k100/rare` | 10000 | 16 | 100 | 30144176.7, 31777402.8, 29975667.8 | 1926731.2, 1864770.1, 1863309.0 | 30144176.7 | 1864770.1 | 16.1651 | -93.81 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s4/k100/common-mixed` | 10000 | 4 | 100 | 42902705.4, 44048103.3, 41868041.4 | 9022123.9, 8730968.9, 8740574.7 | 42902705.4 | 8740574.7 | 4.9085 | -79.63 | IMPROVEMENT |
| `pr15b_v1/u11/n10000_s4/k100/rare` | 10000 | 4 | 100 | 37096827.7, 37813975.8, 36135374.0 | 3686767.4, 3601268.0, 3642609.6 | 37096827.7 | 3642609.6 | 10.1841 | -90.18 | IMPROVEMENT |
| `pr15b_v1/u12/n10000_s4/k100/page-1` | 10000 | 4 | 100 | 43368740.1, 43367030.2, 41068009.5 | 8659114.7, 8404544.7, 8240053.8 | 43367030.2 | 8404544.7 | 5.1599 | -80.62 | IMPROVEMENT |
| `pr15b_v1/u12/n10000_s4/k100/page-2` | 10000 | 4 | 100 | 42418931.5, 44140742.3, 41576373.8 | 8534001.2, 8563114.3, 8347613.3 | 42418931.5 | 8534001.2 | 4.9706 | -79.88 | IMPROVEMENT |
| `pr15b_v1/u13/geo_n8_s1/k100/geo-bbox` | 8 | 1 | 100 | 59473.6, 58976.0, 56770.2 | 10375.4, 10241.1, 10184.5 | 58976.0 | 10241.1 | 5.7588 | -82.64 | IMPROVEMENT |

## Limitations

- Per-lane ratios are descriptive medians of three independent trial medians.
- Independent trials do not estimate production request p95 or p99 latency.
- No cross-lane arithmetic average of speedups is computed or published.
- Group figures are descriptive medians and ranges over visible lanes only.
- INCONCLUSIVE means the predeclared noise/effect heuristics cannot separate the measured difference from trial-to-trial dispersion; it is not a significance test and not evidence of no effect.
- Criterion estimates are microbenchmark iteration distributions, not an SLA.
