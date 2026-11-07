# PR 15H-E — paired latency

Campaign: `target/pr15h-e/campaigns/paired-01`; 16 balanced warm slots, 9 frozen
PR15D lanes, 5 warmups + 20 samples per slot. Cold-open and build+commit used 4
balanced blocks × 2 samples per arm. Gating statistic is the conventional even-n
median of the four E/A block ratios; conventional medians are informational.

## Warm lanes

| Lane | Four block ratios | Median | Result |
|---|---|---:|---|
| 10K absent K100 | 1.113860, 0.911267, 1.011251, 1.027227 | 1.019239 | PASS |
| 10K rare K100 | 1.013088, 1.076369, 0.995060, 1.020202 | 1.016645 | PASS |
| 10K medium K100 | 0.982843, 0.967262, 1.020526, 0.956179 | 0.975053 | PASS |
| 10K common K100 | 0.980921, 1.004705, 1.005561, 1.014668 | 1.005133 | PASS |
| 100K absent K100 | 0.984995, 0.980954, 0.954995, 0.983746 | 0.982350 | PASS |
| 100K rare K100 | 0.962125, 0.908802, 1.003254, 0.940440 | 0.951283 | PASS |
| 100K medium K100 | 1.000237, 0.979631, 1.022046, 1.010502 | 1.005370 | PASS |
| 100K common K100 | 0.989229, 1.007964, 1.007016, 1.020591 | 1.007490 | PASS |
| 100K common K10 | 0.978319, 0.977196, 0.982121, 0.981381 | 0.979850 | PASS |

E-P08 (100K warm median ≤1.08, every block ≤1.30) and E-P09 (10K warm median
≤1.12, every block ≤1.40) pass.

## Cold-open and build+commit

- Cold-open ratios: 0.964526, 0.947170, 0.952540, 0.947493; conventional median
  0.950016. E-P10 (≤1.15 median, ≤1.35 blocks) passes.
- Build+commit ratios: 0.986721, 0.985637, 0.991426, 0.897092; conventional
  median 0.986179. E-P11 (≤1.15 median, ≤1.35 blocks) passes.

E-P12 provenance, idle-confirmation, seal integrity and source drift also pass.
The rejection is storage-only, not a latency regression.
