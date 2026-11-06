# PR 15H-C — paired performance

**Campaign:** `target/pr15h-c/paired-01` (ignored raw evidence)
**Seal SHA-256:** `f5bd95095ee4eeef6b36a5eb954eeb4683e8c9bc2b9ad9b61e7a0aa233e1f463`
**Sanitized performance SHA-256:** `0bdae64ee30c4a8408b74dae0a6ea3dd6f61567780ec47049d1e6b2f6322d6fb`

| Item | A | B |
|---|---|---|
| Source | `e8744d3…059b809` | `fee4edb…15483b8` |
| Adapter SHA-256 | `17fe9bb6…b5d2632b` | `428d677e…d2410670` |

Same host/corpus; index digests byte-identical (`10000` `595b7783…`,
`100000` `fd60b53f…`). 8 slots, 48 lane records, 960 samples, 240 warmups,
16 clear probes, 48 oracle validations. `--verify-only` passed.

`delta = A − B` (positive = C faster), milliseconds:

| Lane | A slot medians (ns) | B slot medians (ns) | Four deltas (ms) | Median | Gate |
|---|---:|---:|---|---:|---|
| P1 common/100K/K100 | 52556702, 53881457, 52837118, 57543286 | 57036650, 58154895, 51778326, 59185429 | −4.480, −4.273, 1.059, −1.642 | **−4.273** | FAIL |
| P2 common/100K/K10 | 38571914, 41307156, 39529511, 43888875 | 42813146, 42260750, 36928188, 42245063 | −4.241, −0.954, 2.601, 1.644 | **−0.954** | FAIL |
| P3 medium/100K/K100 | 21289238, 21141325, 26421108, 24899283 | 27179814, 25208593, 21024252, 24316281 | −5.891, −4.067, 5.397, 0.583 | **−4.067** | FAIL |
| G1 common/10K/K100 | 4732275, 4947976, 4958277, 5560985 | 5678787, 5769790, 4676778, 5854092 | −0.947, −0.822, 0.281, −0.293 | −0.822 | PASS |
| G2 rare/100K/K100 | 263604, 266604, 320706, 335105 | 315505, 266005, 258904, 371606 | −0.052, 0.001, 0.062, −0.037 | −0.037 | PASS |
| G3 absent/100K/K100 | 281704, 264504, 305205, 304004 | 318305, 284204, 269705, 330405 | −0.037, −0.020, 0.035, −0.026 | −0.026 | PASS |

Gates: HC-P00 PASS, HC-P01 **FAIL**, HC-P02 **FAIL**, HC-P03 **FAIL**,
HC-P04 PASS, HC-P05 PASS, HC-P06 PASS, HC-P07 PASS.

**Decision: `PERFORMANCE_REJECTED`.** Neither primary reached the >=2 ms
median improvement; P1/P2/P3 were slower. No threshold, lane or sample was
changed and no retry was run.
