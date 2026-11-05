# D2 isolation harness fixup — test matrix

**Command:** `python3 -m unittest discover -s benchmarks/pr15g_d -p 'test_*.py' -v`
**Result:** 48 passed, 0 failed (22 isolated-D2 tests + 26 historical).

| HX area | Executed assertion |
|---|---|
| Schedule/balance | `test_literal_schedule_and_balance`; `test_raw_validation_rejects_partial_sample_and_contention`; `test_raw_validation_rejects_lane_reorder` |
| Manifest/warmups | `test_raw_validation_rejects_manifest_identity_and_warmups` |
| Frozen summary | `test_nearest_rank_summary_is_authoritative`; `test_tampered_summary_is_rejected`; `test_invalid_sample_types_are_rejected` |
| Block arithmetic | `test_block_medians_and_ratios`; `test_arithmetic_median_of_two_slots`; `test_verdict_equality_and_mixed_signs` |
| Drift | `test_drift_boundaries_and_violations`; `test_blocked_report_has_no_performance_table` |
| Gates | `test_both_common_lanes_required`; `test_guardrail_blocks_acceptance` |
| Output/sanitizer | `test_out_must_be_inside_campaign_tree`; `test_sanitizer_rejects_absolute_paths`; `test_render_json_and_markdown_are_canonical_bytes` |
| Seal/verify | `test_blocked_seal_and_verify`; `test_qualified_seal_and_verify`; `test_tampered_slot_and_report_are_rejected`; `test_legacy_unsealed_is_refused` |
| Real source proof | `test_real_local_a_x_exact_edits` — 15/0 and 43/1 edit counts |

## Coverage honesty

This suite asserts the implemented source-proof, summary, manifest, sealing,
drift, blocked-report, byte-verification and gate semantics. It does not claim
a one-to-one explicit test for every HX-T01–HX-T47 adversarial row. Missing
individual mutations include a synthetic source fixture for each of HX-T02,
T04, T06–T10 and T12, and report-pair coexistence beyond the exercised
tamper/legacy cases. Those remain residual harness-test gaps for review.
