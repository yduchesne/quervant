# PR 4 review amendment 03 — test matrix execution

**Branch:** `dev/analyzer-contract`. Executed commands:

```text
cargo +1.85.0 test -p trawler-core --test analysis_review_amendment_03   # 27 passed; 0 failed
cargo +1.85.0 test -p trawler-core --test analysis_review_amendment_02   # 30 passed (A3-I03)
cargo +1.85.0 test --workspace --all-targets                             # see report
cargo test --workspace --all-targets                                     # see report
```

Reproduction status: 7 of these failed on the unmodified pinned baseline `66cfb5f`
(see `review-amendment-03-preflight.md`); all pass after the fix.

## A3-T matrix

| ID | Test function | File | Result |
|---|---|---|---|
| A3-T01 adjacent literal run composes | `a3_t01_adjacent_literal_run_composes` | `tests/analysis_review_amendment_03.rs` | PASS |
| A3-T02 combining mark at group start | `a3_t02_combining_mark_at_group_start_is_rejected` | same | PASS |
| A3-T03 capture-group start | `a3_t03_combining_mark_at_capture_group_start_is_rejected` | same | PASS |
| A3-T04 combining mark after group | `a3_t04_combining_mark_after_group_is_rejected` | same | PASS |
| A3-T05 after intervening group | `a3_t05_combining_mark_after_intervening_group_is_rejected` | same | PASS |
| A3-T06 self-contained group composes | `a3_t06_self_contained_group_composes_internally` | same | PASS |
| A3-T07 plain group unchanged | `a3_t07_plain_group_is_unchanged` | same | PASS |
| A3-T08 alternation + literal unchanged | `a3_t08_alternation_followed_by_literal_is_unchanged` | same | PASS |
| A3-T09 approved subset unchanged | `a3_t09_approved_subset_is_unchanged` | same | PASS |
| A3-T10 unsafe alternation branch | `a3_t10_unsafe_alternation_branch_at_group_start_is_rejected` | same | PASS |
| A3-T11 alternation before mark | `a3_t11_unsafe_alternation_before_combining_mark_is_rejected` | same | PASS |
| A3-T12 quantified group starting with mark | `a3_t12_quantified_group_starting_with_combining_mark_is_rejected` | same | PASS |
| A3-T13 quantified combining mark | `a3_t13_quantified_combining_mark_is_rejected` | same | PASS |
| A3-T14 case expansion accepted | `a3_t14_unquantified_case_expansion_is_accepted` | same | PASS |
| A3-T15 quantified expansion rejected | `a3_t15_quantified_case_expansion_is_rejected` | same | PASS |
| A3-T16 safe classes accepted | `a3_t16_safe_classes_remain_accepted` | same | PASS |
| A3-T17 case-sensitive range rejected | `a3_t17_case_sensitive_range_remains_rejected` | same | PASS |
| A3-T18 NFKC boundary rejected | `a3_t18_nfkc_boundary_combining_mark_is_rejected` | same | PASS |
| A3-T19 no normalization accepts | `a3_t19_no_normalization_accepts_boundary_pattern` | same | PASS |
| A3-T20 nested groups/alternations | `a3_t20_nested_groups_and_alternations_do_not_panic` | same | PASS |
| A3-T21 work budget | `a3_t21_work_budget_is_respected_during_boundary_inspection` | same | PASS |
| A3-T22 cancellation | `a3_t22_cancellation_is_respected_during_boundary_inspection` | same | PASS |
| A3-T23 existing rejections preserved | `a3_t23_existing_rejections_are_preserved` | same | PASS |
| A3-T24 determinism | `a3_t24_preparation_is_deterministic` | same | PASS |

## A3-I vertical slices

| ID | Test function | Result |
|---|---|---|
| A3-I01 real NFC pipeline + boundary rejection | `a3_i01_real_nfc_pipeline_and_boundary_rejection` | PASS |
| A3-I02 safe group preparation preserves metadata | `a3_i02_safe_group_preparation_preserves_metadata` | PASS |
| A3-I03 Amendment 02 integration regression | `cargo +1.85.0 test -p trawler-core --test analysis_review_amendment_02` (30 tests) | PASS |
| A3-I04 resource/cancellation boundaries | `a3_i04_resource_and_cancellation_boundaries_are_typed` | PASS |

## Notation coverage

Patterns are exercised both with an actual decoded combining scalar (`\u{0301}` in a Rust
`format!` string) and with regex escape syntax (`\u{0301}` and `\u0301` in raw strings), so the
AST decoded-literal path is covered for both. No regex execution is asserted; PR 8 owns it.
