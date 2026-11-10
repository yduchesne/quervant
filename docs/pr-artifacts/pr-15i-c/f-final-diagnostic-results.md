# PR 15I-C-F — diagnostic results

Status: **`F_GENERIC_BOUNDARY_REJECTED`** · diagnostic only · protocol
`benchmarks/pr15i_c/f_final_protocol_v1.json` SHA-256
`5ca968c2e8f6cbfbca88357651d66a1cacace3b45def3ad25fefc1d0228a7dba`.

## 1. Campaign inventory

| Campaign | Regime | Slots | Timed observations | Warmups | Adapter rebuilds | Verifier status |
| --- | --- | --- | --- | --- | --- | --- |
| `unbatched-01` | unbatched | 32 | 5 760 | 1 440 | 18 | `F_GENERIC_BOUNDARY_REJECTED` |
| `batched-01` | batched | 32 | 2 880 | 1 440 | 18 | `F_BATCHED_OBSERVATION_ONLY` |
| `unbatched-02` | unbatched | 32 | 5 760 | 1 440 | 18 | `F_GENERIC_BOUNDARY_REJECTED` |
| `batched-02` | batched | 32 | 2 880 | 1 440 | 18 | `F_BATCHED_OBSERVATION_ONLY` |

Totals: 128 slots, 17 280 timed observations, 5 760 warmups, 276 480 executed
query/batch queries, 72 fresh adapter builds, 256 contention probes. Every
campaign ran from a clean worktree at the pinned SHA, on `ext4`, with adapter
CPU 0 / controller CPU 1, and every probe reported `clear`.

## 2. A/A stability (pre-gate)

Per lane, the median of the four within-block A/A drift ratios lies in
`[0.85, 1.15]` in all four campaigns, and no lane has more than one block
outside `[0.80, 1.25]`.

| Campaign | Worst lane median A/A drift | Blocks outside `[0.80, 1.25]` |
| --- | --- | --- |
| `unbatched-01` | 1.0587 (`10000/absent`) | 0 |
| `unbatched-02` | 0.9455 (`10000/absent`) | 1 (`10000/absent`, `10000/medium`, `100000/absent`) |
| `batched-01` | 1.0551 (`10000/absent`) | 0 |
| `batched-02` | 1.0230 (`10000/absent`) | 1 (`10000/absent`) |

Evidence is therefore valid and stable; no `F_DIAGNOSTIC_UNSTABLE`.

## 3. Historical C reproduction (pre-gate)

Median C/A over four blocks, per unbatched campaign (floor 1.15 at 10K, 1.40 at
100K):

| Lane | `unbatched-01` | `unbatched-02` |
| --- | --- | --- |
| `10000/absent` | 1.5402 | 1.5006 |
| `10000/rare` | 1.3856 | 1.6175 |
| `100000/absent` | 1.7852 | 1.8000 |
| `100000/rare` | 1.7375 | 1.7293 |

The historical negative reproduces on all eight cells, so
`F_C_REPRODUCTION_MISSING` does not apply.

## 4. Generic-boundary neutrality (the deciding gate)

Aggregate G/A (mean of the two unbatched campaign medians) and per-campaign
values, against the frozen ceilings (`≤ 1.10` each campaign, `≤ 1.05`
aggregate):

| Lane | G/A aggregate | `unbatched-01` | `unbatched-02` | Verdict |
| --- | --- | --- | --- | --- |
| `10000/absent` | **1.4382** | 1.4720 | 1.4045 | fail |
| `10000/rare` | **1.3568** | 1.2979 | 1.4156 | fail |
| `10000/medium` | 1.0380 | 1.0376 | 1.0383 | pass |
| `10000/common` | 1.0057 | 1.0218 | 0.9895 | pass |
| `100000/absent` | **1.7737** | 1.7491 | 1.7984 | fail |
| `100000/rare` | **1.7310** | 1.7240 | 1.7381 | fail |
| `100000/medium` | 1.0230 | 0.9990 | 1.0469 | pass |
| `100000/common` | 0.9982 | 0.9816 | 1.0148 | pass |
| `100000/common/k10` | 1.0264 | 1.0239 | 1.0288 | pass |

Four of nine lanes exceed both ceilings in both campaigns, so the frozen
decision is `F_GENERIC_BOUNDARY_REJECTED`. Per-block G/A above 1.15 is recorded
only as an observation (see `raw/measurements.json`); no block-level value is
used to fail the diagnostic.

## 5. Physical operator (observation only)

P/A and P/G, aggregate over the two unbatched campaigns:

| Lane | C/A | G/A | P/A | P/G |
| --- | --- | --- | --- | --- |
| `10000/absent` | 1.5204 | 1.4382 | 1.4212 | 0.9941 |
| `10000/rare` | 1.5015 | 1.3568 | 1.4291 | 1.0435 |
| `100000/absent` | 1.7926 | 1.7737 | 1.7291 | 0.9679 |
| `100000/rare` | 1.7334 | 1.7310 | 1.6970 | 0.9930 |
| `10000/common` | 0.9812 | 1.0057 | 0.8652 | 0.8575 |
| `100000/common` | 1.0159 | 0.9982 | 0.8383 | 0.8459 |
| `100000/common/k10` | 1.0403 | 1.0264 | 0.8026 | 0.7731 |

`P/G ≈ 0.97–1.06` on the four low-match lanes and `0.77–0.92` on the primary
common lanes: with the physical operator enabled, latency is close to the
generic-boundary arm on the regressed lanes and faster on the common lanes,
while never removing the low-match regression.

## 6. Batched observation (never used for classification)

Batched campaigns reproduce the same shape: C/A ≈ G/A on the low-match lanes
(`batched-01` 1.4643/1.5068, 1.5077/1.4246, 1.7688/1.8049, 1.7958/1.8113;
`batched-02` 1.4811/1.4836, 1.4834/1.4477, 1.7808/1.7831, 1.7978/1.7427) and
`P/G` between 0.94 and 1.07. These values are reported, not classified.

## 7. What the pattern supports

The historical low-match regression is reproduced by **the generic boundary
alone**: arm G runs the unmodified generic collector out of line, with the
physical collector never executed, and reaches G/A ≈ C/A. The physical operator
is therefore not required to produce the regression, and enabling it (P) does
not recover the low-match lanes. This is consistent with a code-placement
effect of removing the shared generic collector from the caller, and is *not*
evidence about instruction-level causes: no hardware counters were available.

No claim is made here about the frozen PR 15I-C acceptance criteria, which
remain unmet.
