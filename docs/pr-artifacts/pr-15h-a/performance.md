# PR 15H-A — paired performance campaign

**Campaign directory:** `target/pr15h-a/paired-01` (ignored raw evidence)
**Seal file SHA-256:** `ee42614555aaa5a3ba268dc1f45c6fa1c9eddc1d696841241c7d39c215427a4e`
**Sanitized report SHA-256:** `fe674ce058045618340057d1daa4bad39764372d6688e7419c01246090eb71d0`

## Source arms

| Arm | Source | Role |
|---|---|---|
| A | `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078` | pinned baseline |
| B | `dce8f02405e6541d478c2072a0332af192ed2945` | linear single-term candidate |

Candidate is a committed descendant of the baseline. The tooling checkout was
clean and detached source worktrees were pinned. Frozen files matched. The arms
produced byte-identical query-only index digests.

## Frozen schedule and completeness

Four mirrored blocks: `A,B` / `B,A` / `B,A` / `A,B` (8 timed slots).

| Quantity | Required | Observed |
|---|---:|---:|
| Timed slots | 8 | 8 |
| Lane records | 56 | 56 |
| Timed samples | 1,120 | 1,120 |
| Warmups | 280 | 280 |
| Clear contention probes | 16 | 16 |
| Independent oracle validations | 56 | 56 |

Sample summaries are the frozen nearest-rank statistics; every 20-sample series
was recomputed from raw values.

## Four paired B/A ratios per lane

| Lane | A slot medians (ns) | B slot medians (ns) | B/A ratios | Verdict |
|---|---:|---:|---|---|
| `pr15d_v1/100000/medium/k100` | 23433849, 22834474, 21997328, 22097730 | 21329616, 23104951, 22143532, 21460626 | 0.910, 1.012, 1.007, 0.971 | INCONCLUSIVE |
| `pr15d_v1/100000/common/k100` | 57469255, 59464890, 56712045, 55801234 | 53034686, 54110522, 52672889, 54917522 | 0.923, 0.910, 0.929, 0.984 | B_FASTER |
| `pr15d_v1/100000/common/k10` | 44683312, 45360879, 43168443, 43566151 | 38812679, 40289912, 42558636, 38794380 | 0.869, 0.888, 0.986, 0.890 | B_FASTER |
| `pr15d_v1/10000/common/k100` | 5268884, 5293580, 5030975, 5139577 | 4812172, 5410897, 5111676, 5024175 | 0.913, 1.022, 1.016, 0.978 | INCONCLUSIVE |
| `pr15d_v1/10000/rare/k100` | 53300, 53801, 53600, 52201 | 66101, 67601, 71201, 75101 | 1.240, 1.257, 1.328, 1.439 | A_FASTER |
| `pr15d_v1/100000/rare/k100` | 273605, 278404, 269904, 272604 | 468207, 460609, 452907, 463207 | 1.711, 1.654, 1.678, 1.699 | A_FASTER |
| `pr15d_v1/100000/absent/k100` | 242204, 267604, 256604, 256204 | 440306, 451907, 463607, 438107 | 1.818, 1.689, 1.807, 1.710 | A_FASTER |

## Drift

Cross-session (sealed baseline historical median-of-3 vs paired A median-of-4,
1.25 cap for 100K / 1.50 for 10K) and within-arm cross-block drift checks all
passed. No `MEASUREMENT_BLOCKED_*` condition occurred.

## Frozen gates

| Gate | Result |
|---|---|
| HA-P00 baseline + paired qualification | PASS |
| HA-P01 100K common K100 `B_FASTER` | PASS |
| HA-P02 100K common K10 `B_FASTER` | PASS |
| HA-P03 100K medium K100 not `A_FASTER` | PASS (INCONCLUSIVE) |
| HA-P04 all guards not `A_FASTER` | **FAIL** (G2, G3, G4 are `A_FASTER`) |
| HA-P05 oracle + byte-identical query-only indexes | PASS |
| HA-P06 source-scope audit | PASS |

**Decision: `PERFORMANCE_REJECTED`.** The qualified campaign regressed every
low-hit guard, so the optimization must not be retained. No speedup percentage
is claimed; the blocking evidence is the sign of all four ratios per lane.
