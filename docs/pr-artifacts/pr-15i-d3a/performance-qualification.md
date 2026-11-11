# PR 15I-D3-A performance qualification

Status: `NOT_RUN`.

This page will contain, from sealed raw evidence only:

- A/A, Q/A and P/Q per-lane medians and block ratios.
- Inclusive `candidate_ns` and `evaluate_ns` shares.
- Complete intermediate-stage costs (`score_map`, `scored_vec_build`,
  `matched_reserve`, `temp_release`) as disjoint intervals.
- FIRST/STEADY sample counts, per-sampled-hit child ranking, residual share.
- The closed priority verdict and the campaign-specific inputs.

Limitations that will be restated even for a positive result: instrumentation
overhead, deterministic non-random samples, section/strata effects, warm process
and page caches, `SAME_DISK_ONLY` archival, no cross-engine physical parity and
no claim of an exactly removable cost.
