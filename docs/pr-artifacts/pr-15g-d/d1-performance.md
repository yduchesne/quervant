# PR 15G-D D1 performance qualification

**Status:** `QUALIFIED_D1`
**Arm A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**D1 candidate:** `1d2a6b0f08bf68994699e1f3e37f163347492cd1`
**Stage root:** `target/pr15g-d/d1-1d2a6b0-20261104T2134Z/`

Nine frozen lanes, 3 trials/arm, 5 warmups + 20 samples, clear probes,
identical corpus/index digests, exact oracle.

| Lane | A median (ns) | B median (ns) | B/A | Paired ratios | Verdict |
|---|---:|---:|---:|---|---|
| 10K absent/K100 | 48,000 | 45,901 | 0.956 | 0.945, 0.971, 0.856 | B_FASTER |
| 10K rare/K100 | 64,101 | 51,001 | 0.796 | 0.932, 0.722, 0.752 | B_FASTER |
| 10K medium/K100 | 2,479,426 | 2,223,729 | 0.897 | 0.897, 0.870, 0.850 | B_FASTER |
| 10K common/K100 | 5,874,363 | 5,383,371 | 0.916 | 0.959, 0.810, 0.911 | B_FASTER |
| 100K absent/K100 | 323,605 | 259,303 | 0.801 | 0.789, 0.785, 0.969 | **B_FASTER** |
| 100K rare/K100 | 279,004 | 266,604 | 0.956 | 0.970, 0.399, 0.985 | B_FASTER |
| 100K medium/K100 | 23,715,196 | 22,969,000 | 0.969 | 0.971, 0.645, 0.944 | B_FASTER |
| 100K common/K100 | 59,238,355 | 57,745,115 | 0.975 | 1.009, 0.705, 0.959 | INCONCLUSIVE |
| 100K common/K10 | 49,286,803 | 44,839,554 | 0.910 | 0.630, 0.910, 0.918 | B_FASTER |

GD-P01 PASS (100K absent B_FASTER), GD-P02 PASS (no guardrail A_FASTER),
GD-P05 PASS. Supplementary geomean B/A `0.905994` (1.104× speedup).

Artifacts: `comparison.json` `feceeca881a1d5f04e6d572e1c2085d9839ff0768b522e9857b5582a972810f5`;
`comparison.md` `84be6911f1a88583174ca8847ff9ecbde3f7fd4d5a8f15ed8ba106fa0fea6353`.
