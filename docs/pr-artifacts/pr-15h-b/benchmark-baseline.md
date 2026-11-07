# PR 15H-B — baseline

**Campaign:** `target/pr15h-b/baseline-01` (ignored raw evidence)
**Seal SHA-256:** `28996cecc0560dbb19b938fd8b15aefd077ee20216884f48ea47bb551beea5d6`
**Sanitized baseline SHA-256:** `704ddd4fc7a54f726346e12e09e7cf6c7ea395660de00255dfe5efbc370640df`

## Chronology

1. Tooling-only commit `7959331` (`HB_TOOLING_SHA`).
2. Detached source-a worktree at `6e47eed`.
3. Baseline campaign (3 trials × 6 lanes × 5 warmups + 20 samples) sealed.
4. `--verify-only` reproduced the sanitized report byte-for-byte.
5. Only then was the production candidate implemented and committed `ae7e416`.

## Acquisition facts

| Fact | Value |
|---|---|
| Baseline source | `6e47eed3f35a5fad8db6dab24c66f386567e95c0` |
| Tooling | `79593314aa0525a1bb7d5f30c900a70e890e728a` |
| Frozen corpus | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Host fingerprint | `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f` |
| Samples / warmups / probes | 360 / 90 / 6 clear |
| Oracle checks | 18 |

## Six-lane baseline (median-of-three trial medians, ns)

| Lane | Trial medians | Median-of-medians |
|---|---:|---:|
| `pr15d_v1/100000/common/k100` | 60591424, 65926205, 58685804 | 60591424 |
| `pr15d_v1/100000/common/k10` | 46810938, 53036048, 45432599 | 46810938 |
| `pr15d_v1/100000/medium/k100` | 25157296, 26002015, 25784896 | 25784896 |
| `pr15d_v1/10000/common/k100` | 6003095, 6445803, 5955992 | 6003095 |
| `pr15d_v1/100000/rare/k100` | 288604, 365305, 271905 | 288604 |
| `pr15d_v1/100000/absent/k100` | 288304, 268504, 288705 | 288304 |

Qualification: `BASELINE_QUALIFIED`.
