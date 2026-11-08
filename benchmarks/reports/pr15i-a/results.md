# PR 15I-A — paired compact mutation-state campaign

- A: `888e819d85f0cde62a5040919ac5c96feca52f1f`
- B: `db9007fb7239a5cce94e20c7c43ac7200da8047f`
- decision: **A_CANDIDATE_ACCEPTED_PENDING_QA**

## Committed bytes

| Arm | n | Sidecar | Segments | Manifest | CURRENT | Total | Payload |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 10000 | 960180 | 2129038 | 636 | 183 | 3090037 | 1 |
| A | 100000 | 9600180 | 21364026 | 636 | 183 | 30965025 | 1 |
| B | 10000 | 230132 | 2129038 | 644 | 183 | 2359997 | 3 |
| B | 100000 | 2383748 | 21364026 | 644 | 183 | 23748601 | 3 |

## B/A ratios

- `100000_sidecar` = 0.248302
- `100000_total` = 0.766949
- `10000_sidecar` = 0.239676
- `10000_total` = 0.763744

## Block ratios (median of four blocks)

- `reopen_ratios`: 0.796492, 0.791235, 0.783605, 0.799905
- `build_commit_sum_ratios`: 0.931567, 0.974504, 0.947479, 0.917059
- `build_ratios`: 0.974301, 1.026293, 1.002040, 0.923730
- `commit_ratios`: 0.925709, 0.967093, 0.940588, 0.916105
- `remote_ratios`: 0.869053, 0.856471, 1.198612, 0.869778

## Warm lanes

| lane | four block ratios |
|---|---|
| `pr15d_v1/10000/absent/k100` | 0.990697, 0.984243, 1.109206, 1.085838 |
| `pr15d_v1/10000/rare/k100` | 1.131934, 1.081143, 0.953053, 1.036670 |
| `pr15d_v1/10000/medium/k100` | 0.971981, 0.990803, 0.983981, 0.984744 |
| `pr15d_v1/10000/common/k100` | 0.964416, 0.975500, 1.000457, 0.976769 |
| `pr15d_v1/100000/absent/k100` | 0.983044, 0.972488, 1.025498, 1.013672 |
| `pr15d_v1/100000/rare/k100` | 0.964469, 0.994048, 1.002111, 1.007647 |
| `pr15d_v1/100000/medium/k100` | 0.994204, 0.997097, 1.023304, 0.980313 |
| `pr15d_v1/100000/common/k100` | 0.988058, 0.989633, 0.959866, 0.987204 |
| `pr15d_v1/100000/common/k10` | 0.993649, 1.005110, 1.000988, 1.015330 |

## Gates

| Gate | Result |
|---|---|
| A-P01 | PASS |
| A-P02 | PASS |
| A-P03 | PASS |
| A-P04 | PASS |
| A-P05 | PASS |
| A-P06 | PASS |
| A-P07 | PASS |
| A-P08 | PASS |
| A-P09 | PASS |
| A-P10 | PASS |
| A-P11 | PASS |
| A-P12 | PASS |
