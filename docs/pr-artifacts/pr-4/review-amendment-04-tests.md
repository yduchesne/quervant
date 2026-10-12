# PR 4 review amendment 04 — test matrix execution

**Branch:** `dev/analyzer-contract`. Reproductions first (baseline `1de1fe0`): the A4 file was
**39 passed / 6 failed**; after the fix it is **45 passed / 0 failed**. Negative assertions check
`AnalysisError::UnsupportedPattern`.

Executed commands (final):

```text
cargo +1.85.0 check --workspace --all-targets
cargo +1.85.0 test --workspace --all-targets
cargo test -p trawler-core --test analysis_review_amendment_04
cargo test -p trawler-core --test analysis_review_amendment_03
cargo test -p trawler-core --test analysis_review_amendment_02
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo llvm-cov --workspace --all-targets --fail-under-lines 85
cargo doc --workspace --no-deps
```

## A4-T matrix

| ID | Test function | Baseline | Final |
|---|---|---|---|
| A4-T01 optional prefix exposes mark | `a4_t01_optional_prefix_exposes_mark` | already safe | PASS |
| A4-T02 zero repetition exposes mark | `a4_t02_zero_repetition_exposes_mark` | already safe | PASS |
| A4-T03 bounded optional prefix | `a4_t03_bounded_optional_prefix_exposes_mark` | already safe | PASS |
| A4-T04 nested nullable group | `a4_t04_nested_nullable_group_exposes_mark` | already safe | PASS |
| A4-T05 nullable alternation before mark | `a4_t05_nullable_alternation_before_mark` | already safe | PASS |
| A4-T06 unsafe alternation branch | `a4_t06_unsafe_alternation_branch` | already safe | PASS |
| A4-T07 multiple nullable prefixes | `a4_t07_multiple_nullable_prefixes` | already safe | PASS |
| A4-T08 explicit stable combining class | `a4_t08_explicit_stable_combining_class` | **FAIL (bypass)** | PASS |
| A4-T09 combining range | `a4_t09_combining_range` | **FAIL (bypass)** | PASS |
| A4-T10 class inside alternative | `a4_t10_class_inside_alternative` | **FAIL (bypass)** | PASS |
| A4-T11 dot after literal | `a4_t11_dot_after_literal_is_rejected` | **FAIL (bypass)** | PASS |
| A4-T12 Perl `\w` after literal | `a4_t12_perl_word_class_after_literal_is_rejected` | **FAIL (bypass)** | PASS |
| A4-T13 NFKC nullable boundary | `a4_t13_nfkc_nullable_boundary_is_rejected` | already safe | PASS |
| A4-T14 zero-exact repetition | `a4_t14_zero_exact_repetition_exposes_mark` | already safe | PASS |
| A4-T15 adjacent literal run | `a4_t15_adjacent_literal_run_composes` | PASS | PASS |
| A4-T16 self-contained group | `a4_t16_self_contained_group_composes` | PASS | PASS |
| A4-T17 plain group | `a4_t17_plain_group_unchanged` | PASS | PASS |
| A4-T18 required literal prevents mark | `a4_t18_required_literal_prevents_leading_mark` | PASS | PASS |
| A4-T19 digit class after literal | `a4_t19_digit_class_after_literal_unchanged` | PASS | PASS |
| A4-T20 ASCII range after literal | `a4_t20_ascii_range_after_literal_unchanged` | PASS | PASS |
| A4-T21 alternation after literal | `a4_t21_alternation_after_literal_unchanged` | PASS | PASS |
| A4-T22 group then literal | `a4_t22_group_then_literal_unchanged` | PASS | PASS |
| A4-T23 case expansion | `a4_t23_case_expansion_accepted` | PASS | PASS |
| A4-T24 NFD nullable boundary | `a4_t24_nfd_nullable_boundary_accepted` | PASS | PASS |
| A4-T25 NFKD nullable boundary | `a4_t25_nfkd_nullable_boundary_accepted` | PASS | PASS |
| A4-T26 no-normalization boundary | `a4_t26_no_normalization_nullable_boundary_accepted` | PASS | PASS |
| A4-T27 leading standalone mark | `a4_t27_leading_standalone_mark_preserved` | PASS | PASS |
| A4-T28 quantified group then mark | `a4_t28_quantified_group_then_mark_rejected` | PASS | PASS |
| A4-T29 leading combining class | `a4_t29_leading_combining_class_preserved` | PASS | PASS |
| A4-T30 bounded repetition required literal | `a4_t30_bounded_repetition_required_literal_accepted` | PASS | PASS |
| A4-T31 malformed/forbidden | `a4_t31_existing_rejections_preserved` | PASS | PASS |
| A4-T32 input ceiling | `a4_t32_input_ceiling_is_enforced` | PASS | PASS |
| A4-T33 work budget | `a4_t33_work_budget_is_enforced` | PASS | PASS |
| A4-T34 cancellation | `a4_t34_cancellation_is_enforced` | PASS | PASS |
| A4-T35 40-level nesting | `a4_t35_deep_nesting_does_not_panic` | **FAIL (bypass)** | PASS |
| A4-T36 oversized class range | `a4_t36_oversized_class_range_is_rejected` | PASS | PASS |
| A4-T37 exact work budget boundary | `a4_t37_exact_work_budget_boundary` | PASS | PASS |
| A4-T38 determinism | `a4_t38_repeated_preparation_is_deterministic` | PASS | PASS |
| A4-T39 A3 regressions | `a4_t39_amendment03_regressions_preserved` | PASS | PASS |
| A4-T40 A2 regressions | `a4_t40_amendment02_regressions_preserved` | PASS | PASS |

## A4-I vertical slices

| ID | Test function / suite | Result |
|---|---|---|
| A4-I01 production NFC path blocks nullable mismatch | `a4_i01_production_path_blocks_nullable_boundary_mismatch` | PASS |
| A4-I02 safe group preparation + fingerprint | `a4_i02_safe_group_preparation_and_metadata` | PASS |
| A4-I03 NFD/no-normalization preserved | `a4_i03_decomposition_and_noop_pipelines_preserved` | PASS |
| A4-I04 A3/A2 suites rerun | `analysis_review_amendment_03` (27) + `analysis_review_amendment_02` (30) | PASS |
| A4-I05 safe classes after literal | `a4_i05_safe_classes_after_literal_are_accepted` | PASS |
| A4-I06 cancellation + budget with nested nullable AST | `a4_i06_cancellation_and_budget_with_nested_nullable_ast` | PASS |

## Conservative narrowing recorded (not regressions)

Under composing normalization the following previously accepted patterns now reject typed:
`e.`, `e.*`, `e\w` (and by the same rule `e\d`, `e\s`, `e\p{...}`). Each can match a combining
scalar after a starter and therefore risked a silent false negative. Standalone/leading forms
(`.e`, `\w`, `\d`, `\s`, `[0-9]`, `[a-z]`) and the approved A2/A3 safe cases remain accepted.
No existing test asserted `e.`/`e\w`; no prior test was edited to accommodate the change.
