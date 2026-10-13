//! PR 4 review amendment 05 regression matrix (A5-T01…A5-T50, A5-I01…A5-I07).
//!
//! Negated bracketed classes and negated POSIX/ASCII classes can match Unicode combining marks
//! even when their excluded members are ASCII-safe, so they are conservatively unsafe at a
//! composing-normalization concatenation boundary.

use quervant_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerDefinition, AnalyzerRegistry, AnalyzerRole,
    CancellationFlag, NeverCancel, NormalizationForm, Pipeline, TokenFilter, TokenizerKind,
    prepare_regex,
};

const COMB: char = '\u{0301}'; // COMBINING ACUTE ACCENT

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn limits() -> AnalysisLimits {
    AnalysisLimits::default()
}

fn standard() -> AnalyzerDefinition {
    registry().get("standard").expect("standard").clone()
}

fn uniform(name: &str, form: NormalizationForm) -> AnalyzerDefinition {
    AnalyzerDefinition::uniform(
        name,
        "1.0.0",
        Pipeline::simple(
            TokenizerKind::UnicodeWord,
            vec![TokenFilter::Normalize(form)],
        )
        .expect("pipeline"),
    )
    .expect("definition")
}

fn pattern(analyzer: &AnalyzerDefinition, raw: &str) -> String {
    prepare_regex(analyzer, raw, &limits(), &NeverCancel)
        .expect("regex accepted")
        .pattern()
        .to_owned()
}

fn expect_reject(analyzer: &AnalyzerDefinition, raw: &str) {
    assert!(
        matches!(
            prepare_regex(analyzer, raw, &limits(), &NeverCancel),
            Err(AnalysisError::UnsupportedPattern { .. })
        ),
        "expected UnsupportedPattern for {raw:?}"
    );
}

// ---------------------------------------------------------------------------
// A5-T01..T18: negated classes at a composing boundary must reject
// ---------------------------------------------------------------------------

#[test]
fn a5_t01_outer_negated_class_nfc() {
    expect_reject(&standard(), "e[^x]");
}

#[test]
fn a5_t02_outer_negated_class_nfkc() {
    expect_reject(&uniform("nfkc-test", NormalizationForm::Nfkc), "e[^x]");
}

#[test]
fn a5_t03_noncapturing_wrapped_negated_class() {
    expect_reject(&standard(), "e(?:[^x])");
}

#[test]
fn a5_t04_capturing_wrapped_negated_class() {
    expect_reject(&standard(), "e([^x])");
}

#[test]
fn a5_t05_nullable_prefix_before_negated_class() {
    expect_reject(&standard(), "e(?:x?[^x])");
}

#[test]
fn a5_t06_zero_or_more_prefix_before_negated_class() {
    expect_reject(&standard(), "e(?:x*[^x])");
}

#[test]
fn a5_t07_bounded_prefix_before_negated_class() {
    expect_reject(&standard(), "e(?:x{0,2}[^x])");
}

#[test]
fn a5_t08_negated_class_alternative() {
    expect_reject(&standard(), "e(?:x|[^x])");
}

#[test]
fn a5_t09_negated_class_first_alternative() {
    expect_reject(&standard(), "e(?:[^x]|x)");
}

#[test]
fn a5_t10_quantified_wrapped_negated_class() {
    expect_reject(&standard(), "e(?:[^x])+");
}

#[test]
fn a5_t11_negated_posix_class() {
    expect_reject(&standard(), "e[[:^digit:]]");
}

#[test]
fn a5_t12_wrapped_negated_posix_class() {
    expect_reject(&standard(), "e(?:[[:^alpha:]])");
}

#[test]
fn a5_t13_negated_class_excluding_mark_still_rejected() {
    expect_reject(&standard(), &format!("e[^{COMB}]"));
}

#[test]
fn a5_t14_negated_digit_range() {
    expect_reject(&standard(), "e[^0-9]");
}

#[test]
fn a5_t15_negated_ascii_range() {
    expect_reject(&standard(), "e[^a-z]");
}

#[test]
fn a5_t16_nullable_prefix_negated_digit_range() {
    expect_reject(&standard(), "e(?:x?[^0-9])");
}

#[test]
fn a5_t17_bounded_repetition_negated_class() {
    expect_reject(&standard(), "e[^x]{1,3}");
}

#[test]
fn a5_t18_optional_negated_class() {
    expect_reject(&standard(), "e[^x]?");
}

// ---------------------------------------------------------------------------
// A5-T19..T31: accepted forms preserved
// ---------------------------------------------------------------------------

#[test]
fn a5_t19_standalone_negated_class() {
    assert_eq!(pattern(&standard(), "[^x]"), "[^x]");
}

#[test]
fn a5_t20_standalone_wrapped_negated_class() {
    assert_eq!(pattern(&standard(), "(?:[^x])"), "(?:[^x])");
}

#[test]
fn a5_t21_negated_class_before_literal() {
    assert_eq!(pattern(&standard(), "[^x]e"), "[^x]e");
}

#[test]
fn a5_t22_digit_class_after_literal() {
    assert_eq!(pattern(&standard(), "e[0-9]"), "e[0-9]");
}

#[test]
fn a5_t23_ascii_range_after_literal() {
    assert_eq!(pattern(&standard(), "e[a-z]"), "e[a-z]");
}

#[test]
fn a5_t24_positive_posix_digit_class() {
    assert_eq!(pattern(&standard(), "e[[:digit:]]"), "e[[:digit:]]");
}

#[test]
fn a5_t25_positive_posix_alpha_class() {
    assert_eq!(pattern(&standard(), "e[[:alpha:]]"), "e[[:alpha:]]");
}

#[test]
fn a5_t26_plain_group_after_literal() {
    assert_eq!(pattern(&standard(), "e(?:xy)"), "e(?:xy)");
}

#[test]
fn a5_t27_nullable_group_required_literal() {
    assert_eq!(pattern(&standard(), "e(?:x?y)"), "e(?:x?y)");
}

#[test]
fn a5_t28_group_with_composed_literal() {
    assert_eq!(pattern(&standard(), "e(?:é)"), "e(?:é)");
}

#[test]
fn a5_t29_negated_class_nfd_preserved() {
    let analyzer = uniform("nfd-test", NormalizationForm::Nfd);
    assert_eq!(pattern(&analyzer, "e[^x]"), "e[^x]");
}

#[test]
fn a5_t30_negated_class_nfkd_preserved() {
    let analyzer = uniform("nfkd-test", NormalizationForm::Nfkd);
    assert_eq!(pattern(&analyzer, "e[^x]"), "e[^x]");
}

#[test]
fn a5_t31_negated_class_no_normalization_preserved() {
    let analyzer = uniform("none-test", NormalizationForm::None);
    assert_eq!(pattern(&analyzer, "e[^x]"), "e[^x]");
}

// ---------------------------------------------------------------------------
// A5-T32..T39: edge cases
// ---------------------------------------------------------------------------

#[test]
fn a5_t32_escaped_caret_is_literal() {
    assert_eq!(pattern(&standard(), r"e[\^x]"), r"e[\^x]");
}

#[test]
fn a5_t33_negated_caret_class_rejected() {
    expect_reject(&standard(), "e[^^]");
}

#[test]
fn a5_t34_empty_negated_class_grammar() {
    // `[^]` is rejected by the pinned parser; assert the typed error, never a panic.
    expect_reject(&standard(), "e[^]");
}

#[test]
fn a5_t35_negated_posix_in_union() {
    expect_reject(&standard(), "e[[:^digit:]a]");
}

#[test]
fn a5_t36_nullable_alternation_with_negated_class() {
    expect_reject(&standard(), "e(?:x?[^x]|y)");
}

#[test]
fn a5_t37_quantified_nullable_negated_group() {
    expect_reject(&standard(), "e(?:x?[^x]){0,2}");
}

#[test]
fn a5_t38_negated_class_repeated_preparation_deterministic() {
    let analyzer = standard();
    for _ in 0..3 {
        assert!(matches!(
            prepare_regex(&analyzer, "e[^x]", &limits(), &NeverCancel),
            Err(AnalysisError::UnsupportedPattern { .. })
        ));
    }
}

#[test]
fn a5_t39_positive_class_repeated_preparation_deterministic() {
    let analyzer = standard();
    let first = prepare_regex(&analyzer, "e[0-9]", &limits(), &NeverCancel).expect("regex");
    let second = prepare_regex(&analyzer, "e[0-9]", &limits(), &NeverCancel).expect("regex");
    assert_eq!(first.pattern(), second.pattern());
    assert_eq!(first.metadata().fingerprint, second.metadata().fingerprint);
}

// ---------------------------------------------------------------------------
// A5-T40..T46: resource and nesting bounds
// ---------------------------------------------------------------------------

#[test]
fn a5_t40_input_ceiling() {
    let bounded = AnalysisLimits::default()
        .with_max_input_bytes(4)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&standard(), "e[^x]", &bounded, &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a5_t41_cancellation() {
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&standard(), "e[^x]", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}

#[test]
fn a5_t42_work_budget() {
    let small = AnalysisLimits::default()
        .with_max_work_units(1)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&standard(), "e[^x]", &small, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a5_t43_max_range_bound_is_bounded_and_safe() {
    // 4096-scalar CJK range: exactly the bounded scan limit, all combining-class zero.
    assert_eq!(
        pattern(&standard(), r"e[\u{4E00}-\u{5DFF}]"),
        r"e[\u{4E00}-\u{5DFF}]"
    );
}

#[test]
fn a5_t44_range_beyond_bound_is_conservatively_rejected() {
    expect_reject(&standard(), r"e[\u{4E00}-\u{5E00}]");
}

#[test]
fn a5_t45_deep_nesting_within_limit() {
    let depth = 40;
    let deep = format!("{}e[0-9]{}", "(?:".repeat(depth), ")".repeat(depth));
    assert!(prepare_regex(&standard(), &deep, &limits(), &NeverCancel).is_ok());
}

#[test]
fn a5_t46_beyond_nesting_limit_is_typed() {
    let depth = 300;
    let deep = format!("{}e{}", "(?:".repeat(depth), ")".repeat(depth));
    expect_reject(&standard(), &deep);
}

// ---------------------------------------------------------------------------
// A5-T47..T50: regression to amendments 03/04
// ---------------------------------------------------------------------------

#[test]
fn a5_t47_amendment03_group_boundary() {
    expect_reject(&standard(), &format!("e(?:{COMB})"));
}

#[test]
fn a5_t48_amendment04_nullable_boundary() {
    expect_reject(&standard(), &format!("e(?:x?{COMB})"));
}

#[test]
fn a5_t49_self_contained_group_composes() {
    assert_eq!(pattern(&standard(), &format!("(?:e{COMB})")), "(?:é)");
}

#[test]
fn a5_t50_amendment04_combining_class() {
    expect_reject(&standard(), &format!("e[{COMB}]"));
}

// ---------------------------------------------------------------------------
// A5-I vertical slices
// ---------------------------------------------------------------------------

#[test]
fn a5_i01_nfc_index_and_boundary_rejection() {
    let analyzer = standard();
    let source = format!("e{COMB}");
    let tokens = analyzer
        .collect_tokens(
            AnalyzerRole::Index,
            &[source.as_str()],
            &limits(),
            &NeverCancel,
        )
        .expect("analysis");
    assert_eq!(tokens[0].term(), "é");
    expect_reject(&analyzer, "e[^x]");
    let safe = prepare_regex(&analyzer, "e[0-9]", &limits(), &NeverCancel).expect("regex");
    assert_eq!(safe.metadata().fingerprint, analyzer.fingerprint());
}

#[test]
fn a5_i02_nfkc_composition_and_rejection() {
    let analyzer = uniform("nfkc-test", NormalizationForm::Nfkc);
    let source = format!("e{COMB}");
    let tokens = analyzer
        .collect_tokens(
            AnalyzerRole::Index,
            &[source.as_str()],
            &limits(),
            &NeverCancel,
        )
        .expect("analysis");
    assert_eq!(tokens[0].term(), "é");
    expect_reject(&analyzer, "e[^x]");
}

#[test]
fn a5_i03_nfd_preserved() {
    let analyzer = uniform("nfd-test", NormalizationForm::Nfd);
    let source = format!("e{COMB}");
    let tokens = analyzer
        .collect_tokens(
            AnalyzerRole::Index,
            &[source.as_str()],
            &limits(),
            &NeverCancel,
        )
        .expect("analysis");
    assert_eq!(tokens[0].term(), source);
    assert_eq!(pattern(&analyzer, "e[^x]"), "e[^x]");
}

#[test]
fn a5_i04_positive_and_standalone_negated_classes() {
    let analyzer = standard();
    let safe = prepare_regex(&analyzer, "e[0-9]", &limits(), &NeverCancel).expect("regex");
    assert_eq!(safe.pattern(), "e[0-9]");
    assert_eq!(safe.metadata().fingerprint, analyzer.fingerprint());
    assert_eq!(pattern(&analyzer, "[^x]"), "[^x]");
}

#[test]
fn a5_i05_nested_nullable_negated_posix_rejected() {
    expect_reject(&standard(), "e(?:x?[[:^digit:]])");
}

#[test]
fn a5_i06_cancellation_and_budget_no_partial_success() {
    let analyzer = standard();
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&analyzer, "e(?:x?[^x])", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
    let small = AnalysisLimits::default()
        .with_max_work_units(1)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&analyzer, "e(?:x?[^x])", &small, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}
