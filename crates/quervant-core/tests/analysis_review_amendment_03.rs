//! PR 4 review amendment 03 regression matrix (A3-T01…A3-T24, A3-I01…A3-I04).
//!
//! Cross-boundary Unicode composition: a combining mark at the start of a nested group (or
//! otherwise adjacent to a preceding matched character) must not be silently accepted when the
//! configured normalization could compose it with that preceding character.

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

fn english() -> AnalyzerDefinition {
    registry().get("english").expect("english").clone()
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

#[test]
fn a3_t01_adjacent_literal_run_composes() {
    assert_eq!(pattern(&standard(), &format!("e{COMB}")), "é");
}

#[test]
fn a3_t02_combining_mark_at_group_start_is_rejected() {
    let analyzer = standard();
    // Literal Unicode mark and regex escape form must both be rejected.
    expect_reject(&analyzer, &format!("e(?:{COMB})"));
    expect_reject(&analyzer, r"e(?:\u{0301})");
    expect_reject(&analyzer, r"e(?:\u0301)");
}

#[test]
fn a3_t03_combining_mark_at_capture_group_start_is_rejected() {
    expect_reject(&standard(), &format!("e({COMB})"));
}

#[test]
fn a3_t04_combining_mark_after_group_is_rejected() {
    let analyzer = standard();
    expect_reject(&analyzer, &format!("(?:e){COMB}"));
    expect_reject(&analyzer, r"(?:e)\u{0301}");
}

#[test]
fn a3_t05_combining_mark_after_intervening_group_is_rejected() {
    expect_reject(&standard(), &format!("e(?:x){COMB}"));
}

#[test]
fn a3_t06_self_contained_group_composes_internally() {
    let result = pattern(&standard(), &format!("(?:e{COMB})"));
    assert_eq!(result, "(?:é)");
}

#[test]
fn a3_t07_plain_group_is_unchanged() {
    assert_eq!(pattern(&standard(), "ab(?:cd)"), "ab(?:cd)");
}

#[test]
fn a3_t08_alternation_followed_by_literal_is_unchanged() {
    assert_eq!(pattern(&standard(), "(a|b)c"), "(a|b)c");
}

#[test]
fn a3_t09_approved_subset_is_unchanged() {
    assert_eq!(
        pattern(&standard(), r"^ab(c|d)[0-9]{2,4}$"),
        r"^ab(c|d)[0-9]{2,4}$"
    );
}

#[test]
fn a3_t10_unsafe_alternation_branch_at_group_start_is_rejected() {
    expect_reject(&standard(), &format!("e(?:{COMB}|x)"));
}

#[test]
fn a3_t11_unsafe_alternation_before_combining_mark_is_rejected() {
    expect_reject(&standard(), &format!("(?:e|x){COMB}"));
}

#[test]
fn a3_t12_quantified_group_starting_with_combining_mark_is_rejected() {
    expect_reject(&standard(), &format!("e(?:{COMB})+"));
}

#[test]
fn a3_t13_quantified_combining_mark_is_rejected() {
    expect_reject(&standard(), &format!("e{COMB}+"));
}

#[test]
fn a3_t14_unquantified_case_expansion_is_accepted() {
    assert_eq!(pattern(&english(), "Straße"), "strasse");
}

#[test]
fn a3_t15_quantified_case_expansion_is_rejected() {
    expect_reject(&english(), "ß+");
}

#[test]
fn a3_t16_safe_classes_remain_accepted() {
    for good in ["[0-9]", "[a-z]", r"\d", r"\w", r"\s"] {
        assert!(
            prepare_regex(&english(), good, &limits(), &NeverCancel).is_ok(),
            "expected acceptance for {good:?}"
        );
    }
}

#[test]
fn a3_t17_case_sensitive_range_remains_rejected() {
    expect_reject(&english(), "[A-Z]");
}

#[test]
fn a3_t18_nfkc_boundary_combining_mark_is_rejected() {
    expect_reject(
        &uniform("nfkc-test", NormalizationForm::Nfkc),
        &format!("e(?:{COMB})"),
    );
}

#[test]
fn a3_t19_no_normalization_accepts_boundary_pattern() {
    let analyzer = uniform("none-test", NormalizationForm::None);
    let raw = format!("e(?:{COMB})");
    assert_eq!(pattern(&analyzer, &raw), raw);
}

#[test]
fn a3_t20_nested_groups_and_alternations_do_not_panic() {
    let analyzer = standard();
    expect_reject(&analyzer, &format!("a(?:b(?:{COMB}))"));
    expect_reject(&analyzer, &format!("a(?:(?:{COMB}))"));
    expect_reject(&analyzer, &format!("(?:a|b(?:{COMB}))c"));
    // Deep nesting must be rejected without stack overflow (parser nest limit bounds recursion).
    let depth = 40;
    let deep = format!("{}e{}{}", "(?:".repeat(depth), "", ")".repeat(depth));
    let nested_comb = format!("a{}{}{}", "(?:".repeat(depth), COMB, ")".repeat(depth));
    assert!(prepare_regex(&analyzer, &deep, &limits(), &NeverCancel).is_ok());
    assert!(matches!(
        prepare_regex(&analyzer, &nested_comb, &limits(), &NeverCancel),
        Err(AnalysisError::UnsupportedPattern { .. })
    ));
}

#[test]
fn a3_t21_work_budget_is_respected_during_boundary_inspection() {
    let analyzer = standard();
    let long = "a".repeat(200);
    let small = AnalysisLimits::default()
        .with_max_work_units(10)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&analyzer, &long, &small, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a3_t22_cancellation_is_respected_during_boundary_inspection() {
    let analyzer = standard();
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&analyzer, "abcdef", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}

#[test]
fn a3_t23_existing_rejections_are_preserved() {
    let analyzer = standard();
    for bad in [r"a{3,2}", "(?i)abc", "(?<name>a)", r"(a)\1", "a(?=b)"] {
        expect_reject(&analyzer, bad);
    }
}

#[test]
fn a3_t24_preparation_is_deterministic() {
    let analyzer = standard();
    let raw = format!("(?:e{COMB})");
    let first = prepare_regex(&analyzer, &raw, &limits(), &NeverCancel).expect("regex");
    let second = prepare_regex(&analyzer, &raw, &limits(), &NeverCancel).expect("regex");
    assert_eq!(first.pattern(), second.pattern());
    assert_eq!(first.metadata().fingerprint, second.metadata().fingerprint);
}

#[test]
fn a3_i01_real_nfc_pipeline_and_boundary_rejection() {
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
    assert_eq!(tokens.len(), 1);
    assert_eq!(tokens[0].term(), "é");

    expect_reject(&analyzer, &format!("e(?:{COMB})"));
}

#[test]
fn a3_i02_safe_group_preparation_preserves_metadata() {
    let analyzer = standard();
    let prepared =
        prepare_regex(&analyzer, &format!("(?:e{COMB})"), &limits(), &NeverCancel).expect("regex");
    assert_eq!(prepared.pattern(), "(?:é)");
    assert_eq!(prepared.metadata().fingerprint, analyzer.fingerprint());
}

#[test]
fn a3_i04_resource_and_cancellation_boundaries_are_typed() {
    let analyzer = standard();
    let bounded = AnalysisLimits::default()
        .with_max_input_bytes(4)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&analyzer, "abcdef", &bounded, &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));

    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&analyzer, "abc", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}
