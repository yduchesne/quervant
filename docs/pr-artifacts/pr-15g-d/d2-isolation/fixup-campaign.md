# PR 15G-D D2-only isolation — qualified campaign

**Campaign:** opaque `d2-only-fixup-new-campaign-01`
**Status:** `D2_ONLY_PERFORMANCE_REJECTED`
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**X:** `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6`
**Harness commit:** `74f495cc580a746ada6facda7c44363499273481`
**Raw seal:** `fbdba7771397e1078281cb414ad1c4537afafcb167f4344e1e4967e89e338046` (v2, exactly 18 files)
**Sanitized JSON:** `554b75ee6c0456c854fa474700b80f860b8e450542db0b21b2240d46fe1fe5a1`
**Sanitized Markdown:** `ff6eeb503e27397bd09ef76a27861e12ddcb155c047d77ac51a4e7136f5a2ca4`

## Acquisition

| Item | Result |
|---|---|
| Slots | 16/16 |
| Arms | 8 A, 8 X |
| Lane records | 144 |
| Samples | 2,880 |
| Warmups | 720 |
| Oracle checks | 144 pass |
| Contention probes | 32/32 clear |
| Frozen source/binaries/indexes | immutable |
| Drift, both arms/nine lanes | within 1.25 (100K) / 1.50 (10K) |
| `--verify-only` | PASS — byte-identical |

The complete raw inventory was sealed before drift classification. The campaign
qualified; the performance gates then rejected D2-only.

# PR 15G-D D2-only isolation performance

- A: `ca065a212987284144d8901aa5c54de093d6dbfc`
- X (D2 only): `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6`
- status: `D2_ONLY_PERFORMANCE_REJECTED`

| lane | A block medians (ns) | X block medians (ns) | X/A ratios | verdict |
|---|---|---|---|---|
| `pr15d_v1/10000/absent/k100` | 45650.5, 46500.5, 41700, 45150.5 | 44200, 42551, 43150.5, 50600.5 | 0.968226, 0.915065, 1.03478, 1.12071 | INCONCLUSIVE |
| `pr15d_v1/10000/rare/k100` | 54301, 51551, 51451, 49751 | 54851, 52251, 52650.5, 58051 | 1.01013, 1.01358, 1.02331, 1.16683 | A_FASTER |
| `pr15d_v1/10000/medium/k100` | 2.54284e+06, 2.15553e+06, 2.10118e+06, 2.27268e+06 | 2.37718e+06, 2.11293e+06, 2.13778e+06, 2.42434e+06 | 0.934854, 0.980237, 1.01742, 1.06673 | INCONCLUSIVE |
| `pr15d_v1/10000/common/k100` | 5.55409e+06, 5.47778e+06, 5.21753e+06, 5.78148e+06 | 5.49088e+06, 4.92077e+06, 5.00367e+06, 5.60883e+06 | 0.988619, 0.898315, 0.959011, 0.970137 | X_FASTER |
| `pr15d_v1/100000/absent/k100` | 261054, 284654, 256204, 272654 | 282854, 267504, 253654, 289054 | 1.08351, 0.939751, 0.990049, 1.06015 | INCONCLUSIVE |
| `pr15d_v1/100000/rare/k100` | 266703, 272654, 262254, 283004 | 275004, 257804, 270802, 282854 | 1.03112, 0.945539, 1.0326, 0.999468 | INCONCLUSIVE |
| `pr15d_v1/100000/medium/k100` | 2.37767e+07, 2.32764e+07, 2.28604e+07, 2.4914e+07 | 2.44809e+07, 2.33023e+07, 2.16967e+07, 2.37479e+07 | 1.02961, 1.00111, 0.949096, 0.953196 | INCONCLUSIVE |
| `pr15d_v1/100000/common/k100` | 6.15137e+07, 5.82215e+07, 5.73317e+07, 6.06027e+07 | 6.0404e+07, 5.58841e+07, 5.49422e+07, 5.79031e+07 | 0.981961, 0.959852, 0.958321, 0.955455 | X_FASTER |
| `pr15d_v1/100000/common/k10` | 4.76216e+07, 4.35054e+07, 4.48565e+07, 4.70465e+07 | 4.28433e+07, 4.4782e+07, 4.12546e+07, 4.50007e+07 | 0.899662, 1.02934, 0.919703, 0.956515 | INCONCLUSIVE |

Gates: DX-P01=FAIL, DX-P02=FAIL, status=D2_ONLY_PERFORMANCE_REJECTED, DX-P03=PASS

