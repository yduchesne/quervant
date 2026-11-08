# PR 15I-B residual — performance result

Both candidates used the same R1–R3 common source and frozen 16-slot/9-lane
protocol against A=P0. New campaigns: `lz4-residual-01`, `zstd-residual-01`.

| Metric (B/A) | LZ4 residual | Zstd1 residual |
|---|---:|---:|
| 100K STORED bytes | 1,661,455 / 9,662,513 = 0.1719 | 628,025 / 9,662,513 = 0.0650 |
| 100K total committed | 15,747,551 / 23,748,601 = 0.6631 | 14,714,121 / 23,748,601 = 0.6196 |
| 10K STORED / total | 0.1722 / 0.6611 | 0.0652 / 0.6173 |
| 10K rare blocks | **1.0141 / 1.0497 / 1.0687 / 1.1594** | 1.1745 / 1.1064 / 1.2832 / 1.2101 |
| 10K rare median | **1.0592 PASS** | **1.1923 FAIL** |
| 10K medium median | 1.0010 | 1.0148 |
| 100K rare median | 1.0151 | 1.0518 |
| 100K medium median | 1.0197 | 1.0203 |
| Other warm lanes | PASS | PASS |
| Reopen / build+commit / RustFS / selected / RSS | PASS | PASS |
| `C = S × R` | 0.1260 | 0.0478 |
| Verifier decision | **`B_CANDIDATE_QUALIFIED`** | `B_CANDIDATE_INELIGIBLE` |

LZ4 improves 10K rare from the prior direct-record 1.152 to **1.0592** and passes
every frozen gate; Zstd remains above the 1.10 ceiling. Seals: LZ4
`b5cf7fd4c057d6880036c4d490226570c57a24398bc8909609eba825be5bf740`; Zstd
`2a589854b810379ae04e3951f8d54afe3727782fdad75fc05c9c4ae5a39b4c61`.
No threshold, schedule, block size or codec was changed.
