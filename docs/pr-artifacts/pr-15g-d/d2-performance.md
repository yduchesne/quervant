# PR 15G-D D2 performance qualification

**Status:** `QUALIFIED_D2`
**Arm A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**D2 candidate (includes qualified D1):** `dae598758a433ecdc0d9af37e15194e948bbc788`
**Stage root:** `target/pr15g-d/d2-dae5987-20261104T2203Z/`

| Lane | A median (ns) | B median (ns) | B/A | Paired ratios | Verdict |
|---|---:|---:|---:|---|---|
| 10K absent/K100 | 44,800 | 43,100 | 0.962 | 0.969, 0.900, 1.051 | INCONCLUSIVE |
| 10K rare/K100 | 56,001 | 53,600 | 0.957 | 0.907, 1.038, 0.932 | INCONCLUSIVE |
| 10K medium/K100 | 2,127,226 | 2,097,823 | 0.986 | 0.919, 0.991, 1.074 | INCONCLUSIVE |
| 10K common/K100 | 5,291,964 | 5,015,066 | 0.948 | 0.918, 0.964, 1.104 | INCONCLUSIVE |
| 100K absent/K100 | 256,805 | 261,104 | 1.017 | 1.114, 1.017, 0.984 | INCONCLUSIVE |
| 100K rare/K100 | 269,205 | 271,404 | 1.008 | 0.973, 1.048, 1.057 | INCONCLUSIVE |
| 100K medium/K100 | 22,767,675 | 21,976,187 | 0.965 | 0.955, 0.963, 0.978 | **B_FASTER** |
| 100K common/K100 | 58,413,400 | 54,923,866 | 0.940 | 0.929, 0.946, 0.970 | **B_FASTER** |
| 100K common/K10 | 43,918,444 | 41,953,081 | 0.955 | 0.955, 0.978, 0.960 | B_FASTER |

GD-P03 PASS (both 100K medium and common K100 B_FASTER), GD-P04 PASS
(no lane A_FASTER), GD-P05 PASS. Supplementary geomean B/A `0.970640`
(1.030× speedup).

Artifacts: `comparison.json` `2daa24129cf7c1995047b495fdfd8ba6feb0bdb4adf3a9f57f2c1d3e44d7eaf2`;
`comparison.md` `131b443322bfe0b4bc993623c3136c9ceef64811363a431af9eda49e11646c40`.
