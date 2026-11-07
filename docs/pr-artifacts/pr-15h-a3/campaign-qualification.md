# PR 15H-A3 — campaign qualification

## A/A environment control (`aa-01`)

**Result: `MEASUREMENT_BLOCKED_AA_CONTROL`.** Preserved and verified; not retried
(A3-D24).

| Fact | Value |
|---|---|
| Tooling | `7e23335ef1862d27801b198965ebc4a4804becde` |
| Source (both arms) | `7a136f7f299c2f460401b9d92dcef37d219ea98c` |
| Arm binary SHA (A and A_PRIME) | `3370083e501931f412a6a914730d2538b717900c22904d3fe83e39acdbaaf14f` (identical) |
| Environment fingerprint | `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f` |
| Slots / lane records / samples | 4 / 16 / 320 |
| Warmups / probes / oracle checks | 80 / 8 clear / 16 |
| Seal SHA-256 | `b1579ba18c012c2d9be838e212ff32a7f6b3310cc2099e5cf2dd425eec2966a2` |
| Sanitized blocked SHA-256 | `ecd38608ffe1460302549a15e00de74dd448027d3168fe9c358b3b42e391ee50` |
| `verify` | PASS (byte-exact recomputation) |

### Slot medians (ns)

| Slot | Block | Arm | absent 100K | rare 100K | rare 10K | common 100K |
|---|---|---|---:|---:|---:|---:|
| 1 | 1 | A | 364,908 | 278,106 | 59,201 | 59,217,473 |
| 2 | 1 | A_PRIME | 285,806 | 298,808 | 67,402 | 67,141,553 |
| 3 | 2 | A_PRIME | 347,008 | 333,508 | 60,501 | 69,692,538 |
| 4 | 2 | A | 253,307 | 272,107 | 55,902 | 60,354,504 |

### A/A ratios (max/min per block) vs caps

| Lane | Ratios | Cap | Qualified |
|---|---|---:|---|
| `100000/absent/k100` | 1.277, 1.370 | 1.15 | **NO** |
| `100000/rare/k100` | 1.074, 1.226 | 1.15 | **NO** |
| `10000/rare/k100` | 1.139, 1.082 | 1.20 | yes |
| `100000/common/k100` | 1.134, 1.155 | 1.15 | **NO** |

Both arms were built from the same source and produced **byte-identical**
binaries, so this is host/session variability, not a source/build difference.
The session cannot resolve a ~1.3–1.4× difference at the frozen AA caps.

## A/B reproduction

**NOT RUN.** The plan requires a qualified A/A before A/B attribution
(A3-D23/D24; S4). No A/B campaign directory was created.

## BV2 / BV3 interventions

**PREREQ_BLOCKED.** `bv2` requires a `REPRODUCED` A/B and `bv3` requires a
qualified `V2_EFFECT_PRESENT`; neither prerequisite exists. No variant source
commit or campaign was created.

## Overall

`MEASUREMENT_BLOCKED`. No source-performance verdict, no causal claim and no
retained optimization.
