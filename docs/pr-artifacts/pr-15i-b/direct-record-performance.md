# PR 15I-B direct-record — performance result

Both new candidates were measured against P0 with the frozen protocol and
independently verified. Direct intra-block access removed most of the earlier
rare-query regression (for example 10K rare 1.664/1.691 → **1.152/1.158**;
100K rare 1.168/1.165 → **1.042/1.066**), but the frozen `B-P06` median
ceiling for 10K rare is still exceeded by both codecs, so neither is eligible.

| Metric (B/A) | LZ4 direct | Zstd1 direct | Gate |
|---|---:|---:|---|
| 100K STORED bytes | 1,661,455 / 9,662,513 = 0.1719 | 628,025 / 9,662,513 = 0.0650 | B-P03 <=0.85 PASS |
| 100K total committed | 15,747,551 / 23,748,601 = 0.6631 | 14,714,121 / 23,748,601 = 0.6196 | B-P04 <=0.95 PASS |
| 10K STORED / total | 0.1722 / 0.6611 | 0.0652 / 0.6173 | B-P05 PASS |
| 10K rare median | **1.152** | **1.158** | B-P06 <=1.10 **FAIL** |
| 10K rare blocks | 1.231/1.077/1.076/1.227 | 1.104/1.158/1.159/1.297 | each <=1.30 |
| 10K medium median | 1.035 | 0.999 | B-P06 PASS |
| 100K rare median | 1.042 | 1.066 | B-P06 PASS |
| 100K medium median | 1.023 | 1.017 | B-P06 PASS |
| Other warm lanes | all PASS | all PASS | B-P07 |
| Reopen median | ~0.703 | ~0.674 | B-P08 |
| Build+commit median | ~0.848 | ~0.845 | B-P10 |
| RustFS cold median | ~0.658 | ~0.638 | B-P09 |
| Selected K100 median | 0.744 | 0.740 | B-P12 |
| RSS ratios / absolute | PASS (negative delta) | PASS (negative delta) | B-P11 |
| `C = S × R` | 0.1295 | 0.0481 | C < 1 necessary |
| Verified decision | `B_CANDIDATE_INELIGIBLE` | `B_CANDIDATE_INELIGIBLE` | |

Structural counters prove the hot path: for a certified one-document read,
`inflated=1`, `direct=1`, `hot_lookups=1`, `full_scan=0`; two docs in the same
block use one inflation/two direct reads; two blocks use two inflations/two
lookups; empty selection does no work. The remaining 10K rare cost is therefore
not the removed 128-record scan; it is dominated by certificate/first-use or
touched-block decompression and surrounding search work. No further
architecture change is authorized.
