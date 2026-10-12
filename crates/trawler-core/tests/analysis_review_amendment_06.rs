//! PR 4 review amendment 06 regression matrix (A6-T01…A6-T42, A6-I01…A6-I08).
//!
//! Negated classes match the complement of their explicit members. Under full Unicode case
//! folding the complement is not membership-stable (`[^a]` matches source `A`, but the folded
//! indexed term `a` is excluded), so negated bracketed/POSIX classes are rejected typed when
//! the search pipeline case-folds.

use trawler_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerDefinition, AnalyzerRegistry, AnalyzerRole,
    CancellationFlag, NeverCancel, NormalizationForm, Pipeline, TokenFilter, TokenizerKind,
    prepare_regex,
};

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn limits() -> AnalysisLimits {
    AnalysisLimits::default()
}

fn standard() -> AnalyzerDefinition {
    registry().get("standard").expect("standard").clone()
}

fn analyzer_with(name: &str, filters: Vec<TokenFilter>) -> AnalyzerDefinition {
    AnalyzerDefinition::uniform(
        name,
        "1.0.0",
        Pipeline::simple(TokenizerKind::UnicodeWord, filters).expect("pipeline"),
    )
    .expect("definition")
}

fn casefold_only() -> AnalyzerDefinition {
    analyzer_with("cf-only-test", vec![TokenFilter::CaseFold])
}
fn nfc_casefold() -> AnalyzerDefinition {
    analyzer_with(
        "nfc-cf-test",
        vec![
            TokenFilter::Normalize(NormalizationForm::Nfc),
            TokenFilter::CaseFold,
        ],
    )
}
fn casefold_nfc() -> AnalyzerDefinition {
    analyzer_with(
        "cf-nfc-test",
        vec![
            TokenFilter::CaseFold,
            TokenFilter::Normalize(NormalizationForm::Nfc),
        ],
    )
}
fn nfd() -> AnalyzerDefinition {
    analyzer_with(
        "nfd-test",
        vec![TokenFilter::Normalize(NormalizationForm::Nfd)],
    )
}
fn nfd_casefold() -> AnalyzerDefinition {
    analyzer_with(
        "nfd-cf-test",
        vec![
            TokenFilter::Normalize(NormalizationForm::Nfd),
            TokenFilter::CaseFold,
        ],
    )
}
fn nfkd() -> AnalyzerDefinition {
    analyzer_with(
        "nfkd-test",
        vec![TokenFilter::Normalize(NormalizationForm::Nfkd)],
    )
}
fn nfkd_casefold() -> AnalyzerDefinition {
    analyzer_with(
        "nfkd-cf-test",
        vec![
            TokenFilter::Normalize(NormalizationForm::Nfkd),
            TokenFilter::CaseFold,
        ],
    )
}
fn none() -> AnalyzerDefinition {
    analyzer_with(
        "none-test",
        vec![TokenFilter::Normalize(NormalizationForm::None)],
    )
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
// A6-T01..T19: negated classes under case folding must reject
// ---------------------------------------------------------------------------

#[test]
fn a6_t01_negated_class_casefold_only() {
    expect_reject(&casefold_only(), "[^a]");
}

#[test]
fn a6_t02_negated_class_nfc_then_casefold() {
    expect_reject(&nfc_casefold(), "[^a]");
}

#[test]
fn a6_t03_negated_class_casefold_then_nfc() {
    expect_reject(&casefold_nfc(), "[^a]");
}

#[test]
fn a6_t04_negated_uppercase_literal() {
    expect_reject(&casefold_only(), "[^A]");
}

#[test]
fn a6_t05_negated_sharp_s() {
    expect_reject(&casefold_only(), "[^ß]");
}

#[test]
fn a6_t06_negated_greek_sigma() {
    expect_reject(&casefold_only(), "[^Σ]");
}

#[test]
fn a6_t07_negated_class_in_capture_group() {
    expect_reject(&casefold_only(), "([^a])");
}

#[test]
fn a6_t08_negated_class_in_noncapture_group() {
    expect_reject(&casefold_only(), "(?:[^a])");
}

#[test]
fn a6_t09_negated_class_alternation() {
    expect_reject(&casefold_only(), "(?:x|[^a])");
}

#[test]
fn a6_t10_nullable_prefix_then_negated_class() {
    expect_reject(&casefold_only(), "(?:x?[^a])");
}

#[test]
fn a6_t11_optional_negated_class() {
    expect_reject(&casefold_only(), "[^a]?");
}

#[test]
fn a6_t12_star_negated_class() {
    expect_reject(&casefold_only(), "[^a]*");
}

#[test]
fn a6_t13_bounded_negated_class() {
    expect_reject(&casefold_only(), "[^a]{1,3}");
}

#[test]
fn a6_t14_negated_posix_lower() {
    expect_reject(&casefold_only(), "[[:^lower:]]");
}

#[test]
fn a6_t15_negated_posix_digit() {
    expect_reject(&casefold_only(), "[[:^digit:]]");
}

#[test]
fn a6_t16_negated_posix_alpha() {
    expect_reject(&casefold_only(), "[[:^alpha:]]");
}

#[test]
fn a6_t17_negated_posix_union() {
    expect_reject(&casefold_only(), "[[:^lower:]x]");
}

#[test]
fn a6_t18_nested_negated_bracket() {
    expect_reject(&casefold_only(), "[[^a]x]");
}

#[test]
fn a6_t19_doubly_nested_negated_bracket() {
    expect_reject(&casefold_only(), "[[[^a]]]");
}

// ---------------------------------------------------------------------------
// A6-T20..T30: safe positives and non-case-folding pipelines preserved
// ---------------------------------------------------------------------------

#[test]
fn a6_t20_digit_range_casefold() {
    assert_eq!(pattern(&casefold_only(), "[0-9]"), "[0-9]");
}

#[test]
fn a6_t21_ascii_range_casefold() {
    assert_eq!(pattern(&casefold_only(), "[a-z]"), "[a-z]");
}

#[test]
fn a6_t22_positive_posix_digit_casefold() {
    assert_eq!(pattern(&casefold_only(), "[[:digit:]]"), "[[:digit:]]");
}

#[test]
fn a6_t23_positive_posix_lower_casefold() {
    assert_eq!(pattern(&casefold_only(), "[[:lower:]]"), "[[:lower:]]");
}

#[test]
fn a6_t24_digit_class_after_literal_nfc_casefold() {
    assert_eq!(pattern(&nfc_casefold(), "e[0-9]"), "e[0-9]");
}

#[test]
fn a6_t25_plain_group_casefold() {
    assert_eq!(pattern(&casefold_only(), "(?:abc)"), "(?:abc)");
}

#[test]
fn a6_t26_case_expansion_accepted() {
    assert_eq!(pattern(&casefold_only(), "Straße"), "strasse");
}

#[test]
fn a6_t27_negated_class_nfc_without_casefold() {
    assert_eq!(pattern(&standard(), "[^a]"), "[^a]");
}

#[test]
fn a6_t28_negated_class_no_transform() {
    assert_eq!(pattern(&none(), "[^a]"), "[^a]");
}

#[test]
fn a6_t29_negated_class_nfd_without_casefold() {
    assert_eq!(pattern(&nfd(), "[^a]"), "[^a]");
}

#[test]
fn a6_t30_negated_class_nfkd_without_casefold() {
    assert_eq!(pattern(&nfkd(), "[^a]"), "[^a]");
}

// ---------------------------------------------------------------------------
// A6-T31..T42: cross-policy and resource behavior
// ---------------------------------------------------------------------------

#[test]
fn a6_t31_negated_class_nfd_casefold() {
    expect_reject(&nfd_casefold(), "[^a]");
}

#[test]
fn a6_t32_negated_class_nfkd_casefold() {
    expect_reject(&nfkd_casefold(), "[^a]");
}

#[test]
fn a6_t33_negated_class_boundary_nfc_without_casefold() {
    // Amendment 05 boundary rule still applies.
    expect_reject(&standard(), "e[^a]");
}

#[test]
fn a6_t34_negated_posix_boundary_nfc_without_casefold() {
    expect_reject(&standard(), "e[[:^digit:]]");
}

#[test]
fn a6_t35_positive_class_boundary_nfc_without_casefold() {
    assert_eq!(pattern(&standard(), "e[0-9]"), "e[0-9]");
}

#[test]
fn a6_t36_escaped_caret_literal() {
    assert_eq!(pattern(&standard(), r"e[\^x]"), r"e[\^x]");
}

#[test]
fn a6_t37_malformed_empty_negated_class() {
    expect_reject(&standard(), "[^]");
}

#[test]
fn a6_t38_cancellation() {
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&casefold_only(), "[^a]", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}

#[test]
fn a6_t39_work_budget() {
    let small = AnalysisLimits::default()
        .with_max_work_units(1)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&casefold_only(), "[^a]", &small, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a6_t40_input_ceiling() {
    let bounded = AnalysisLimits::default()
        .with_max_input_bytes(4)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&casefold_only(), "e[^a]", &bounded, &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a6_t41_exact_max_safe_range_under_casefold() {
    assert_eq!(
        pattern(&casefold_only(), r"[\u{4E00}-\u{5DFF}]"),
        r"[\u{4E00}-\u{5DFF}]"
    );
}

#[test]
fn a6_t42_range_beyond_bound_rejected() {
    expect_reject(&casefold_only(), r"[\u{4E00}-\u{5E00}]");
}

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

#[test]
fn a6_t43_empty_alternative_and_nullable_edges() {
    // `a|` is supported (discussed in earlier amendments); `[^a]` still rejects under folding.
    assert!(prepare_regex(&casefold_only(), "a|", &limits(), &NeverCancel).is_ok());
    expect_reject(&casefold_only(), "(?:x?|y?)[^a]");
}

#[test]
fn a6_t44_repeated_preparation_is_deterministic() {
    let analyzer = casefold_only();
    for _ in 0..3 {
        assert!(matches!(
            prepare_regex(&analyzer, "[^a]", &limits(), &NeverCancel),
            Err(AnalysisError::UnsupportedPattern { .. })
        ));
    }
    let first = prepare_regex(&analyzer, "[0-9]", &limits(), &NeverCancel).expect("regex");
    let second = prepare_regex(&analyzer, "[0-9]", &limits(), &NeverCancel).expect("regex");
    assert_eq!(first.pattern(), second.pattern());
    assert_eq!(first.metadata().fingerprint, second.metadata().fingerprint);
}

#[test]
fn a6_t45_nesting_bounds() {
    let within = format!("{}e{}", "(?:".repeat(40), ")".repeat(40));
    assert!(prepare_regex(&casefold_only(), &within, &limits(), &NeverCancel).is_ok());
    let beyond = format!("{}e{}", "(?:".repeat(300), ")".repeat(300));
    expect_reject(&casefold_only(), &beyond);
}

#[test]
fn a6_t46_negated_class_inside_intersection_rejected() {
    // A negated bracket nested inside a set operator is still a complement and is rejected.
    expect_reject(&casefold_only(), r"[a-z&&[^x]]");
}

// ---------------------------------------------------------------------------
// A6-I integration slices
// ---------------------------------------------------------------------------

#[test]
fn a6_i01_casefold_index_and_negated_class_rejection() {
    let analyzer = casefold_only();
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &["A"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens[0].term(), "a");
    expect_reject(&analyzer, "[^a]");
}

#[test]
fn a6_i02_nfc_casefold_index_and_rejection_with_fingerprint() {
    let analyzer = nfc_casefold();
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &["A"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens[0].term(), "a");
    expect_reject(&analyzer, "[^a]");
    let safe = prepare_regex(&analyzer, "[0-9]", &limits(), &NeverCancel).expect("regex");
    assert_eq!(safe.metadata().fingerprint, analyzer.fingerprint());
}

#[test]
fn a6_i03_casefold_expansion_index_and_prepared_literal() {
    let analyzer = casefold_only();
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &["Straße"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens[0].term(), "strasse");
    assert_eq!(pattern(&analyzer, "Straße"), "strasse");
}

#[test]
fn a6_i04_nfc_without_casefold_standalone_negated_class_preserved() {
    let analyzer = standard();
    assert_eq!(pattern(&analyzer, "[^a]"), "[^a]");
    let prepared = prepare_regex(&analyzer, "[^a]", &limits(), &NeverCancel).expect("regex");
    assert_eq!(prepared.metadata().fingerprint, analyzer.fingerprint());
}

#[test]
fn a6_i05_nfc_boundary_negated_class_rejected() {
    expect_reject(&standard(), "e[^a]");
}

#[test]
fn a6_i06_casefold_nested_posix_negation_rejected() {
    expect_reject(&casefold_only(), "e(?:x?[[:^digit:]])");
}

#[test]
fn a6_i07_cancellation_and_budget_no_partial_result() {
    let analyzer = casefold_only();
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&analyzer, "e(?:x?[^a])", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
    let small = AnalysisLimits::default()
        .with_max_work_units(1)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&analyzer, "e(?:x?[^a])", &small, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a6_i08_distinct_analyzers_have_distinct_fingerprints() {
    let folding = casefold_only();
    let plain = none();
    assert_ne!(folding.fingerprint(), plain.fingerprint());
    expect_reject(&folding, "[^a]");
    assert_eq!(pattern(&plain, "[^a]"), "[^a]");
}

#[test]
fn a6_i_semantic_witness_casefold_membership_changes() {
    // Independently of preparation: source `A` is accepted by `[^a]`, but folds to `a`.
    let analyzer = casefold_only();
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &["A"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens[0].term(), "a");
    assert_ne!(tokens[0].term(), "A");
}
