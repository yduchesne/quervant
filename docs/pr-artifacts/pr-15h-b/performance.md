# PR 15H-B — paired performance

**Campaign:** `target/pr15h-b/paired-01` (ignored raw evidence)
**Seal SHA-256:** `be76e32ba422cd4bc456045fa13fee50ec3a7ec4312f1b555e8e7c015f639043`
**Sanitized performance SHA-256:** `f0d5d083afcb0b913e3316df45b9d5e3ab6d3859e8272c107b4093ac2ad0d46b`

## Arms and identity

| Item | A | B |
|---|---|---|
| Source | `6e47eed3f35a5fad8db6dab24c66f386567e95c0` | `ae7e416a7d4d8a0ce179b64a15cafc2cb104f85e` |
| Release adapter SHA-256 | `d56d4b8e…cd02ba9e` | `e2ee4f8b…f462e2e7` |

Corpus `69052c66…681151`; host fingerprint `4f971362…e13598f`; index digests
byte-identical (`10000` `595b7783…`, `100000` `fd60b53f…`). Eight mirrored
slots, 48 lane records, 960 timed samples, 240 warmups, 16 clear probes,
48 independent oracle validations.

## Four paired differences per lane (`A − B`, ms; positive = B faster)

| Lane | A slot medians (ns) | B slot medians (ns) | Four diffs (ms) | Median Δ (ms) | Gate |
|---|---:|---:|---|---:|---|
| P1 common/100K/K100 | 66638938, 62418479, 59735732, 62968785 | 58101702, 57047483, 52804693, 56702400 | 8.537, 5.371, 6.931, 6.266 | **6.266** | PASS |
| P2 common/100K/K10 | 51490802, 55706873, 52842425, 49964379 | 39277510, 42443957, 39319211, 42618766 | 12.213, 13.263, 13.523, 7.346 | **12.213** | PASS |
| P3 medium/100K/K100 | 26202807, 23013261, 25502098, 26030506 | 22847754, 23698267, 21380232, 25487198 | 3.355, −0.685, 4.122, 0.543 | **0.543** | PASS |
| G1 common/10K/K100 | 6233897, 5429685, 6062594, 6399900 | 4818774, 5451984, 4685072, 5864192 | 1.415, −0.022, 1.378, 0.536 | **0.536** | PASS |
| G2 rare/100K/K100 | 299305, 300004, 292104, 294505 | 266404, 326805, 272804, 302105 | 0.033, −0.027, 0.019, −0.008 | **−0.008** | PASS |
| G3 absent/100K/K100 | 281704, 255904, 257204, 283305 | 255404, 309205, 263304, 308104 | 0.026, −0.053, −0.006, −0.025 | **−0.025** | PASS |

## Gates

| Gate | Result |
|---|---|
| HB-P00 measurement qualified | PASS |
| HB-P01 P1 median ≥ 5 ms, ≥3/4 ≥ 2 ms, no block < −3 ms | PASS |
| HB-P02 P2 same | PASS |
| HB-P03 P3 median > −3 ms, <3/4 blocks < −3 ms | PASS |
| HB-P04 G1 median > −2 ms | PASS |
| HB-P05 G2/G3 medians > −1 ms | PASS |
| HB-P06 correctness/oracle/index/scope | PASS |
| HB-P07 report hygiene | PASS |

**Decision: `PERFORMANCE_ACCEPTED`** (local QA). No cross-engine comparison and no
extrapolation beyond these six lanes.
