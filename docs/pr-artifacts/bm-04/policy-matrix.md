# BM-04 — Policy matrix

The policy engine answers one question per candidate: *is this candidate
conclusively eligible under the frozen thresholds, and if several are, which one
does the frozen ranking select?* It never asserts that a candidate is faster, and
`INCONCLUSIVE` is a legitimate result.

All comparisons use the canonical 12-place `Decimal` values from the analysis
document. There is no float epsilon, no approximate equality, no operator
substitution and no silent clipping.

## 1. Operators

| Operator | Meaning | Boundary behaviour |
| --- | --- | --- |
| `point_upper` | point estimate `<= point_upper` | **inclusive** |
| `ci_operator: lt` | CI high `< ci_upper` | **strict**; equality fails |
| `ci_operator: le` | CI high `<= ci_upper` | **inclusive**; equality passes |
| resource `max_bytes` | observed `<= max_bytes` | **inclusive**; equality passes |

## 2. Target evaluation (per candidate, per campaign, per target lane)

```text
retained_blocks < max(protocol.minimum_retained_blocks, 2)
    -> status insufficient, reason INSUFFICIENT_RETAINED_BLOCKS, INCONCLUSIVE

point <= point_upper  AND  ci_high <op> ci_upper
    -> status pass, candidate ELIGIBLE for this lane

ci_low > ci_upper  AND  point > point_upper
    -> status decisive-failure, reason TARGET_DECISIVE_FAILURE, INELIGIBLE

otherwise
    -> status unproven, reason TARGET_UNPROVEN, INCONCLUSIVE
```

## 3. Guardrail evaluation

Identical arithmetic, with reasons `GUARDRAIL_DECISIVE_FAILURE` and
`GUARDRAIL_UNPROVEN`.

## 4. Boundary truth table

Target lane: `point_upper = 0.950000000000`, `ci_upper = 1.000000000000`,
`ci_operator = lt`.

| point | ci_low | ci_high | Classification |
| --- | --- | --- | --- |
| `0.900000000000` | `0.800000000000` | `0.999999999999` | pass |
| `0.950000000000` | `0.800000000000` | `0.999999999999` | pass (point bound is inclusive) |
| `0.900000000000` | `0.800000000000` | `1.000000000000` | **TARGET_UNPROVEN** (strict CI bound) |
| `0.960000000000` | `0.900000000000` | `0.999999999999` | TARGET_UNPROVEN (point over, CI under) |
| `0.960000000000` | `1.000000000001` | `1.100000000000` | TARGET_DECISIVE_FAILURE |

Guardrail lane: `point_upper = ci_upper = 1.100000000000`, `ci_operator = le`.

| point | ci_low | ci_high | Classification |
| --- | --- | --- | --- |
| `1.050000000000` | `1.000000000000` | `1.100000000000` | pass (inclusive CI bound) |
| `1.050000000000` | `1.000000000000` | `1.100000000001` | GUARDRAIL_UNPROVEN |
| `1.200000000000` | `1.150000000000` | `1.300000000000` | GUARDRAIL_DECISIVE_FAILURE |
| `1.100000000000` | `1.150000000000` | `1.300000000000` | GUARDRAIL_UNPROVEN (point is not strictly over) |

## 5. Resource matrix

Rule: `candidate / aux-memory-bytes / max_bytes = 2097152`.

| Observation | Classification |
| --- | --- |
| `1048576` | within cap |
| `2097152` | **exactly at the cap — eligible** |
| `2097153` | `RESOURCE_OVER_LIMIT` → INELIGIBLE |
| absent | `MISSING_RESOURCE` → INCONCLUSIVE (never treated as zero) |

## 6. Filter sensitivity

For every candidate × campaign × lane, the sign of `raw_point_effect - 1` is
compared with the sign of `retained_point_effect - 1`. When two or more candidates
exist, the pairwise relative ordering of their raw effects is compared with the
retained ordering. Any sign or tie change marks the candidate
`INCONCLUSIVE` / `FILTER_SENSITIVE` under the declared
`filter_sensitivity_action: inconclusive`.

The rule is **descriptive of selection sensitivity**. It is never an exclusion
trigger, it never deletes raw data, and it must never be used to justify pruning
additional blocks.

## 7. Campaign and candidate precedence

```text
per campaign : any INELIGIBLE -> INELIGIBLE
               else any INCONCLUSIVE -> INCONCLUSIVE
               else ELIGIBLE
per candidate: any INELIGIBLE campaign -> INELIGIBLE
               else any INCONCLUSIVE campaign -> INCONCLUSIVE
               else ELIGIBLE
```

A decisive structural violation dominates uncertainty: a candidate that is both
over its resource cap and missing a resource is recorded as `INELIGIBLE` with both
reason codes preserved. No early return conceals another failure.

## 8. Global selection

Order in `candidate_order` (declared order, never reordered) is the selection
precedence.

| Condition | `selected_arm_id` | `decision_status` |
| --- | --- | --- |
| no eligible candidate, at least one inconclusive | `null` | `INCONCLUSIVE` |
| every candidate conclusively ineligible | declared baseline | `BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE` |
| exactly one eligible candidate | that candidate | `SELECTED_ELIGIBLE_SYNTHETIC` |
| ≥2 eligible, clear winner | smallest `worst_campaign_gm` | `SELECTED_ELIGIBLE_SYNTHETIC` |
| ≥2 eligible, tie | first of the tied pair in `tie_preference` | `TIE_PREFERENCE_NOT_PROVEN_FASTER` |

A `null` `selected_arm_id` **must** carry `INCONCLUSIVE`. The baseline fallback is
used **only** when no candidate is inconclusive, and it is explicitly *not* a proof
that the baseline is faster. A tie preference is explicitly *not* proof of speed.

## 9. Tie boundary

`worst_campaign_gm` is `max` over campaigns of the geometric mean of the policy's
`ranking_lanes` retained effects (canonical 12-place values).

```text
delta = |a - b| / min(a, b)

best == second                       -> tie
delta <  tie_relative_delta          -> tie
delta >= tie_relative_delta          -> not a tie, choose the smaller GM
```

| `a` | `b` | delta | Result |
| --- | --- | --- | --- |
| `0.900000000000` | `0.920000000000` | `0.0222…` | tie |
| `0.900000000000` | `0.927000000000` | `0.030000000000` | **not a tie** (strictly-below rule) |
| `0.900000000000` | `0.900000000000` | `0` | tie |

## 10. Reason records

Closed shape `{candidate_arm_id, campaign_index, lane_id, code}` with a literal
`null` campaign/lane for global or resource decisions, sorted by
`(campaign_index, lane_id, code)` and de-duplicated exactly.

Closed code vocabulary:

```text
RESOURCE_OVER_LIMIT  MISSING_RESOURCE  INSUFFICIENT_RETAINED_BLOCKS
TARGET_DECISIVE_FAILURE  TARGET_UNPROVEN
GUARDRAIL_DECISIVE_FAILURE  GUARDRAIL_UNPROVEN
FILTER_SENSITIVE  MISSING_RANKING_GM
```

## 11. Forbidden outcomes

The policy output may never contain a field named `approved`, `release`,
`real_qualification`, `winner_proven`, `pass` or `attestation`; it may never be
validated as a BM-01 receipt; and it may never be persisted inside a sealed BM-03
run (that would invalidate the closed file inventory).
