# PR 15H-A3 — diagnostic variants (V2/V3)

**Status: `PREREQ_BLOCKED` — not created, not measured.**

The frozen triggers are conjunctive:

| Variant | Required prerequisite | Observed |
|---|---|---|
| V2 (single-line `H_A2_MIN_POSTINGS = usize::MAX`) | Qualified A/B with `REPRODUCED` and exactly one constant line | A/A blocked; A/B not authorized/run |
| V3 (single `#[inline(never)]`) | Qualified BV2 and `V2_EFFECT_PRESENT` | V2 not created |

Therefore:

- no V2/V3 source commit exists;
- no BV2/BV3 campaign directory exists;
- no `V2_EFFECT_*`/`V3_EFFECT_*` outcome is claimed;
- the controller's one-line/one-attribute diff checks remain tested by the
  synthetic A3 suite but were never applied to a real variant.

This is the prescribed prereq-blocked outcome (A3-D59/D65; G11/G12 recorded as
`PREREQ_BLOCKED`). No parameter tuning or substitute annotation was attempted.
