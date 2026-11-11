# PR 15I-D3-A-F2 five-run performance

Status: `D3AF2_ATTRIBUTION_QUALIFIED`; priority verdict
`D3A_CANDIDATE_HOTSPOT_LOCALIZED` for the sampled
`candidate_duplicate` child.

## Priority lanes (n=5 eligible runs; lower median/MAD)

| Lane | candidate ns median (MAD) | candidate share median | duplicate steady share | document-key steady share | sort-view steady share | heap compare+update steady share | materialize steady share | match-insert sampled ns | scored map+vector share | intermediate ns (share) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100K medium/K100 | 8,524,489 (71,522) | 0.4599 | 0.3482 | 0.1272 | 0.2383 | 0.0371 | 0.0000 | 15,855 | 0.0083 | 230,869 (0.0123) |
| 100K common/K100 | 22,852,025 (91,901) | 0.5071 | 0.4115 | 0.0797 | 0.1758 | 0.0421 | 0.0000 | 68,049 | 0.0147 | 987,877 (0.0221) |
| 100K common/K10 | 12,427,773 (168,858) | 0.3585 | 0.1114 | 0.1268 | 0.2626 | 0.0640 | 0.0000 | 68,278 | 0.0189 | 980,870 (0.0286) |

All three primary lanes meet the unchanged candidate materiality gate in all
five eligible runs. The intermediate disjoint region is far below its
3,000,000 ns / 10% gate and does not qualify. Candidate materialization is zero
in the STEADY stratum for these lanes because steady candidates commonly reject
before materialization; FIRST/STEADY remain separately reported in
`five-run-areas-v3.json`.

Run-level candidate nanoseconds:

| Lane | Run 01 | Run 02 | Run 03 | Run 04 | Run 05 |
|---|---:|---:|---:|---:|---:|
| 100K medium/K100 | 8,695,506 | 8,764,758 | 8,477,600 | 8,524,489 | 8,452,967 |
| 100K common/K100 | 23,252,385 | 23,152,648 | 22,852,025 | 22,760,124 | 22,849,102 |
| 100K common/K10 | 12,538,125 | 12,646,519 | 12,203,209 | 12,258,915 | 12,427,773 |

## Decision

- Joint gate: `100K medium/K100` and `100K common/K100` share the same
  `candidate_duplicate` dominant component in **all five** run IDs
  (`d3af2-unbatched-01` … `-05`), satisfying the ≥4 shared-run/two-lane rule.
- Completion state: `D3AF2_ATTRIBUTION_QUALIFIED`.
- Priority verdict: `D3A_CANDIDATE_HOTSPOT_LOCALIZED`,
  component `candidate_duplicate`.
- The 10K rare lane is ineligible in run 03 and therefore not used in any
  priority or guardrail claim.

## Interpretation limits

`candidate_duplicate` is a sampled child of the sampled candidate parent. Its
share is **not** the removable end-to-end cost of duplicate detection and does
not authorize an optimization. Any future change requires a separate design,
full correctness/budget/cancellation parity and independent A/B acceptance
across all nine lanes, including low-hit and K10 guardrails. The earlier 44–49%
candidate-stage context is not substituted for this measurement.
