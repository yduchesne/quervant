# PR 15H-A2 — paired performance

**Campaign:** `target/pr15h-a2/paired-01` (inside the immutable tooling
checkout; ignored raw evidence)
**Seal SHA-256:** `aac028d5107c085872226edaf4756a80cb31ee5e047678a7abac3f8c0c0bbd2b`
**Sanitized report SHA-256:** `ecfe867a22f745a51d3b082cef190ae049766c1eba58e777a6c1771abcc004a5`

## Arms and schedule

| Arm | Source | Role |
|---|---|---|
| A | `7a136f7f299c2f460401b9d92dcef37d219ea98c` | A2 base / accepted production search |
| B | `569132dace8d92c103dfdebd5d24167d65c0c0c0` | cardinality-gated candidate |

Four mirrored blocks `A,B / B,A / B,A / A,B`; 8 slots, 56 lane records, 1,120
timed samples, 280 warmups, 16 clear contention probes, 56 independent oracle
validations. Corpus/index digests equal; same host fingerprint; no drift breach.

## Four paired B/A ratios

| Lane | A slot medians (ns) | B slot medians (ns) | B/A ratios | Verdict |
|---|---:|---:|---|---|
| `100000/medium/k100` | 22329789, 24751290, 21829500, 20782820 | 23687080, 23480896, 22645339, 20273522 | 1.061, 0.949, 1.037, 0.975 | INCONCLUSIVE |
| `100000/common/k100` | 56386754, 60804556, 55848285, 54281636 | 55768393, 54237582, 54869265, 50257171 | 0.989, 0.892, 0.982, 0.926 | **B_FASTER** |
| `100000/common/k10` | 45310587, 46650432, 43673392, 42143148 | 41360128, 40590309, 40731725, 36917966 | 0.913, 0.870, 0.933, 0.876 | **B_FASTER** |
| `10000/common/k100` | 5074377, 5403985, 5795792, 4971976 | 5344084, 5444282, 5099278, 4985376 | 1.053, 1.007, 0.880, 1.003 | INCONCLUSIVE |
| `10000/rare/k100` | 51700, 54001, 53701, 47701 | 69401, 81202, 68302, 60601 | 1.342, 1.504, 1.272, 1.270 | **A_FASTER** |
| `100000/rare/k100` | 278304, 261004, 263004, 266104 | 473708, 516309, 467006, 440707 | 1.702, 1.978, 1.776, 1.656 | **A_FASTER** |
| `100000/absent/k100` | 257504, 267205, 257304, 256204 | 464207, 448107, 419005, 425707 | 1.803, 1.677, 1.628, 1.662 | **A_FASTER** |

## Gates

| Gate | Result |
|---|---|
| HA2-P00 qualification | PASS |
| HA2-P01 100K common K100 `B_FASTER` | PASS |
| HA2-P02 100K common K10 `B_FASTER` | PASS |
| HA2-P03 100K medium not `A_FASTER` | PASS (INCONCLUSIVE) |
| HA2-P04 guards not `A_FASTER` | **FAIL** (G2, G3, G4) |
| HA2-P05 oracle + query-only index identity | PASS |
| HA2-P06 source scope/sanitization/verify-only | PASS |

**Decision: `PERFORMANCE_REJECTED`.** No speedup percentage is claimed. A bounded
post-campaign diagnostic reproduced the sparse-lane regression on the same
artifacts; no causal attribution is asserted.
