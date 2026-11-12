# PR 15I-D3-A-F five-run performance

Status: `D3A_MEASUREMENT_BLOCKED`.

## Run inventory

| Run | Independent status | Slots | Timed | Notes |
|---|---|---:|---:|---|
| `d3af-unbatched-01` | `D3A_ATTRIBUTION_LOW_INTRUSION` | 24 | 4,320 | qualified, archived |
| `d3af-unbatched-02` | `D3A_ATTRIBUTION_LOW_INTRUSION` | 24 | 4,320 | qualified, archived |
| `d3af-unbatched-03` | `D3A_ATTRIBUTION_LOW_INTRUSION` | 24 | 4,320 | qualified, archived |
| `d3af-unbatched-04` | `D3A_UNSTABLE` | 24 | 4,320 | **blocked**; archived |
| `d3af-unbatched-05` | NOT RUN | 0 | 0 | not started after run 04 failure |

Run 04 failed the frozen paired A/A stability gate:
`pr15d_v1/10000/absent/k100` had a median A/A drift of `1.3135148292682906`
outside `[0.85, 1.15]` and 3 outlier blocks (maximum allowed: 1). No rerun,
replacement or sixth campaign was performed. The aggregate verifier therefore
returned exit 3 and no hotspot ranking was produced.

## Qualified-run observations (not an aggregate)

These are the three independently verified run-level values available before
the series was blocked. They are not a five-run decision and are not used to
claim a hotspot.

| Lane | Run | candidate ns | share | dominant child | intermediate ns | intermediate share |
|---|---|---:|---:|---|---:|---:|
| 100K medium/K100 | 01 | 8,516,546 | 0.4617 | candidate_duplicate | 228,573 | 0.0123 |
| 100K medium/K100 | 02 | 8,291,883 | 0.4588 | candidate_duplicate | 223,018 | 0.0123 |
| 100K medium/K100 | 03 | 8,317,367 | 0.4592 | candidate_duplicate | 223,480 | 0.0124 |
| 100K common/K100 | 01 | 23,776,421 | 0.5139 | candidate_duplicate | 1,017,509 | 0.0222 |
| 100K common/K100 | 02 | 23,187,887 | 0.5142 | candidate_duplicate | 956,500 | 0.0211 |
| 100K common/K100 | 03 | 23,043,174 | 0.5138 | candidate_duplicate | 958,307 | 0.0213 |
| 100K common/K10 | 01 | 12,427,500 | 0.3613 | none | 995,128 | 0.0290 |
| 100K common/K10 | 02 | 12,494,561 | 0.3635 | none | 954,500 | 0.0279 |
| 100K common/K10 | 03 | 12,104,070 | 0.3589 | none | 963,876 | 0.0286 |

Every qualified run had zero sampled fallbacks in these lanes. Candidate
sampling was FIRST=20,480 and STEADY=31,040 (medium) or 124,800 (common) per
lane/run. The `candidate_duplicate` dominance is a sampled-candidate diagnostic,
not a complete end-to-end claim. The intermediate region is far below its
3,000,000 ns / 10% gate.

## Decision

`D3A_MEASUREMENT_BLOCKED` overrides all rankings. No five-run median/MAD or
4-of-5 persistence conclusion is valid, and no optimization is authorized.
