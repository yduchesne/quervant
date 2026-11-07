# PR 15H-D — paired performance

**Campaign:** `target/pr15h-d/paired-01` (ignored raw evidence)
**Seal SHA-256:** `902d8432a74225ccaab5a876d5bb51a38a1b7d0cb5b26824f6bd7fac08fbdcc5`
**Sanitized performance SHA-256:** `01a206203460ad6962922863000eef8a67b3f6ef5b9ce2ea204d0e9bc4958ad9`

| Item | A | B |
|---|---|---|
| Source | `c802f965…4baaf` | `0f977791…59522` |
| Adapter SHA-256 | `67c2806d…b3f62e` | `70e31fbf…2803eb5` |

Same host/corpus; index digests byte-identical (`10000` `595b7783…`,
`100000` `fd60b53f…`). 8 slots, 48 lane records, 960 samples, 240 warmups,
16 clear probes, 48 oracle validations. `--verify-only` passed.

`delta = A − B` (positive = D faster), milliseconds. Gating = conventional
even-n median; lower median is supplementary.

| Lane | Four deltas (ms) | Lower median | Conventional median | Gate |
|---|---|---:|---:|---|
| D-P1 common/100K/K100 | 0.511, 0.101, −0.402, 1.124 | 0.101 | **0.306** | FAIL |
| D-P2 common/100K/K10 | 0.930, 0.161, 0.435, −0.714 | 0.161 | **0.298** | FAIL |
| D-P3 medium/100K/K100 | 1.960, 0.420, 1.311, −0.079 | 0.420 | **0.866** | FAIL |
| D-G1 common/10K/K100 | 0.166, 0.037, −0.137, 0.182 | 0.037 | 0.101 | PASS |
| D-G2 rare/100K/K100 | 0.019, 0.008, 0.016, 0.003 | 0.008 | 0.012 | PASS |
| D-G3 absent/100K/K100 | −0.008, 0.003, 0.008, 0.000 | 0.000 | 0.001 | PASS |

Gates: D-P00 PASS, **D-P01 FAIL**, D-P02 PASS, D-P03 PASS.

**Decision: `D_FAILED` → `PERFORMANCE_REJECTED_SAFE_ROLLBACK`.** No primary
reached the required +2 ms conventional-median savings; guards passed. No
threshold, lane or sample was changed and no retry was run.
