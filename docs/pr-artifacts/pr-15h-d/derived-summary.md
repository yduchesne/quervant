# PR 15H-D — derived unsealed summary

Derived from `target/pr15h-d/paired-01/sanitized/performance.json` (raw seal
`902d8432…`). Values are unrounded integer-nanosecond-derived statistics;
milliseconds are display conversions. **Binding** D statistic: conventional
even-n median of four `A − B` deltas (positive = D faster).

| Lane | Four deltas (ns) | Lower median (ns) | Conventional median (ns / ms) | Gate |
|---|---|---:|---:|---|
| D-P1 common/100K/K100 | 510868, 101396, −402406, 1124011 | 101396 | 306132 / 0.306132 | FAIL |
| D-P2 common/100K/K10 | 929736, 161498, 434705, −714016 | 161498 | 298101.5 / 0.2981015 | FAIL |
| D-P3 medium/100K/K100 | 1959734, 419705, 1311320, −79001 | 419705 | 865512.5 / 0.8655125 | FAIL |
| D-G1 common/10K/K100 | 166104, 36700, −137302, 182203 | 36700 | 101402 / 0.101402 | PASS |
| D-G2 rare/100K/K100 | 19400, 8300, 15700, 2900 | 8300 | 12000 / 0.012 | PASS |
| D-G3 absent/100K/K100 | −7800, 2500, 7701, 300 | 300 | 1400 / 0.0014 | PASS |

Threshold: at least two of P1/P2/P3 must have conventional median `>= +2.000 ms`
with ≥3/4 positive deltas; none did. Guards pass. Decision: **D_FAILED**,
`PERFORMANCE_REJECTED_SAFE_ROLLBACK`.
