//! PR 4 review amendment 04 regression matrix (A4-T01…A4-T40, A4-I01…A4-I06).
//!
//! Nullable-aware leading-combining-mark safety: optional/empty prefixes and accepted character
//! classes must not hide a combining scalar that can compose with a preceding matched character.

use quervant_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerDefinition, AnalyzerRegistry, AnalyzerRole,
    CancellationFlag, NeverCancel, NormalizationForm, Pipeline, TokenFilter, TokenizerKind,
    prepare_regex,
};

const COMB: char = '\u{0301}'; // COMBINING ACUTE ACCENT
const COMB_LO: char = '\u{0300}';
const COMB_HI: char = '\u{0302}';

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

// ---------------------------------------------------------------------------
// A4-T01..T14: nullable prefixes and class starts must be rejected
// ---------------------------------------------------------------------------

#[test]
fn a4_t01_optional_prefix_exposes_mark() {
    expect_reject(&standard(), &format!("e(?:x?{COMB})"));
}

#[test]
fn a4_t02_zero_repetition_exposes_mark() {
    expect_reject(&standard(), &format!("e(?:x*{COMB})"));
}

#[test]
fn a4_t03_bounded_optional_prefix_exposes_mark() {
    expect_reject(&standard(), &format!("e(?:x{{0,2}}{COMB})"));
}

#[test]
fn a4_t04_nested_nullable_group_exposes_mark() {
    expect_reject(&standard(), &format!("e(?:(?:x)?{COMB})"));
}

#[test]
fn a4_t05_nullable_alternation_before_mark() {
    expect_reject(&standard(), &format!("e(?:x?|y?){COMB}"));
}

#[test]
fn a4_t06_unsafe_alternation_branch() {
    expect_reject(&standard(), &format!("e(?:x?|{COMB})"));
}

#[test]
fn a4_t07_multiple_nullable_prefixes() {
    expect_reject(&standard(), &format!("e(?:x?y?{COMB})"));
}

#[test]
fn a4_t08_explicit_stable_combining_class() {
    expect_reject(&standard(), &format!("e[{COMB}]"));
}

#[test]
fn a4_t09_combining_range() {
    expect_reject(&standard(), &format!("e[{COMB_LO}-{COMB_HI}]"));
}

#[test]
fn a4_t10_class_inside_alternative() {
    expect_reject(&standard(), &format!("e(?:[{COMB}]|x)"));
}

#[test]
fn a4_t11_dot_after_literal_is_rejected() {
    expect_reject(&standard(), "e.");
    expect_reject(&standard(), "e.*");
}

#[test]
fn a4_t12_perl_word_class_after_literal_is_rejected() {
    expect_reject(&standard(), r"e\w");
}

#[test]
fn a4_t13_nfkc_nullable_boundary_is_rejected() {
    expect_reject(
        &uniform("nfkc-test", NormalizationForm::Nfkc),
        &format!("e(?:x?{COMB})"),
    );
}

#[test]
fn a4_t14_zero_exact_repetition_exposes_mark() {
    expect_reject(&standard(), &format!("e(?:x{{0}}{COMB})"));
}

// ---------------------------------------------------------------------------
// A4-T15..T30: safe patterns stay accepted
// ---------------------------------------------------------------------------

#[test]
fn a4_t15_adjacent_literal_run_composes() {
    assert_eq!(pattern(&standard(), &format!("e{COMB}")), "é");
}

#[test]
fn a4_t16_self_contained_group_composes() {
    assert_eq!(pattern(&standard(), &format!("(?:e{COMB})")), "(?:é)");
}

#[test]
fn a4_t17_plain_group_unchanged() {
    assert_eq!(pattern(&standard(), "e(?:xy)"), "e(?:xy)");
}

#[test]
fn a4_t18_required_literal_prevents_leading_mark() {
    assert_eq!(pattern(&standard(), "e(?:x?y)"), "e(?:x?y)");
}

#[test]
fn a4_t19_digit_class_after_literal_unchanged() {
    assert_eq!(pattern(&standard(), "e[0-9]"), "e[0-9]");
}

#[test]
fn a4_t20_ascii_range_after_literal_unchanged() {
    assert_eq!(pattern(&standard(), "e[a-z]"), "e[a-z]");
}

#[test]
fn a4_t21_alternation_after_literal_unchanged() {
    assert_eq!(pattern(&standard(), "e(?:x|y)"), "e(?:x|y)");
}

#[test]
fn a4_t22_group_then_literal_unchanged() {
    assert_eq!(pattern(&standard(), "(?:e|x)z"), "(?:e|x)z");
}

#[test]
fn a4_t23_case_expansion_accepted() {
    assert_eq!(pattern(&english(), "Straße"), "strasse");
}

#[test]
fn a4_t24_nfd_nullable_boundary_accepted() {
    let analyzer = uniform("nfd-test", NormalizationForm::Nfd);
    let raw = format!("e(?:x?{COMB})");
    assert_eq!(pattern(&analyzer, &raw), raw);
}

#[test]
fn a4_t25_nfkd_nullable_boundary_accepted() {
    let analyzer = uniform("nfkd-test", NormalizationForm::Nfkd);
    let raw = format!("e(?:x?{COMB})");
    assert_eq!(pattern(&analyzer, &raw), raw);
}

#[test]
fn a4_t26_no_normalization_nullable_boundary_accepted() {
    let analyzer = uniform("none-test", NormalizationForm::None);
    let raw = format!("e(?:x?{COMB})");
    assert_eq!(pattern(&analyzer, &raw), raw);
}

#[test]
fn a4_t27_leading_standalone_mark_preserved() {
    let raw = format!("{COMB}");
    assert_eq!(pattern(&standard(), &raw), raw);
    let grouped = format!("(?:{COMB})");
    assert_eq!(pattern(&standard(), &grouped), grouped);
}

#[test]
fn a4_t28_quantified_group_then_mark_rejected() {
    expect_reject(&standard(), &format!("e(?:x+){COMB}"));
}

#[test]
fn a4_t29_leading_combining_class_preserved() {
    let raw = format!("[{COMB}]");
    assert_eq!(pattern(&standard(), &raw), raw);
}

#[test]
fn a4_t30_bounded_repetition_required_literal_accepted() {
    assert_eq!(pattern(&standard(), "e(?:x{1,2}y)"), "e(?:x{1,2}y)");
}

// ---------------------------------------------------------------------------
// A4-T31..T38: failure modes, limits, edges
// ---------------------------------------------------------------------------

#[test]
fn a4_t31_existing_rejections_preserved() {
    let analyzer = standard();
    for bad in [r"a{3,2}", "(?i)abc", "(?<name>a)", r"(a)\1", "a(?=b)"] {
        expect_reject(&analyzer, bad);
    }
}

#[test]
fn a4_t32_input_ceiling_is_enforced() {
    let analyzer = standard();
    let bounded = AnalysisLimits::default()
        .with_max_input_bytes(4)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&analyzer, "abcdef", &bounded, &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a4_t33_work_budget_is_enforced() {
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
fn a4_t34_cancellation_is_enforced() {
    let analyzer = standard();
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&analyzer, "abcdef", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}

#[test]
fn a4_t35_deep_nesting_does_not_panic() {
    let analyzer = standard();
    let depth = 40;
    let deep = format!("{}e{}", "(?:".repeat(depth), ")".repeat(depth));
    assert!(prepare_regex(&analyzer, &deep, &limits(), &NeverCancel).is_ok());
    let deep_comb = format!("e{}{}{}", "(?:".repeat(depth), COMB, ")".repeat(depth));
    expect_reject(&analyzer, &deep_comb);
}

#[test]
fn a4_t36_oversized_class_range_is_rejected() {
    // Range exceeds the bounded interior scan; the existing class-stability validator rejects it.
    expect_reject(&standard(), r"e[\u{0}-\u{FFFF}]");
}

#[test]
fn a4_t37_exact_work_budget_boundary() {
    let analyzer = standard();
    let raw = "e(?:x?y)";
    let mut threshold = None;
    for work in 1..2000u64 {
        let limits = AnalysisLimits::default()
            .with_max_work_units(work)
            .expect("lower");
        if prepare_regex(&analyzer, raw, &limits, &NeverCancel).is_ok() {
            threshold = Some(work);
            break;
        }
    }
    let threshold = threshold.expect("some budget accepts the pattern");
    let exact = AnalysisLimits::default()
        .with_max_work_units(threshold)
        .expect("lower");
    assert!(prepare_regex(&analyzer, raw, &exact, &NeverCancel).is_ok());
    let under = AnalysisLimits::default()
        .with_max_work_units(threshold - 1)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&analyzer, raw, &under, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a4_t38_repeated_preparation_is_deterministic() {
    let analyzer = standard();
    let raw = "e(?:xy)";
    let first = prepare_regex(&analyzer, raw, &limits(), &NeverCancel).expect("regex");
    let second = prepare_regex(&analyzer, raw, &limits(), &NeverCancel).expect("regex");
    assert_eq!(first.pattern(), second.pattern());
    assert_eq!(first.metadata().fingerprint, second.metadata().fingerprint);
}

#[test]
fn a4_t39_amendment03_regressions_preserved() {
    let analyzer = standard();
    expect_reject(&analyzer, &format!("e(?:{COMB})"));
    expect_reject(&analyzer, &format!("(?:e){COMB}"));
}

#[test]
fn a4_t40_amendment02_regressions_preserved() {
    let analyzer = english();
    expect_reject(&analyzer, "ß+");
    assert_eq!(pattern(&analyzer, "Straße+"), "strasse+");
    expect_reject(&analyzer, "[A-Z]");
}

// ---------------------------------------------------------------------------
// A4-I vertical slices
// ---------------------------------------------------------------------------

#[test]
fn a4_i01_production_path_blocks_nullable_boundary_mismatch() {
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
    expect_reject(&analyzer, &format!("e(?:x?{COMB})"));
}

#[test]
fn a4_i02_safe_group_preparation_and_metadata() {
    let analyzer = standard();
    let prepared =
        prepare_regex(&analyzer, &format!("(?:e{COMB})"), &limits(), &NeverCancel).expect("regex");
    assert_eq!(prepared.pattern(), "(?:é)");
    assert_eq!(prepared.metadata().fingerprint, analyzer.fingerprint());
}

#[test]
fn a4_i03_decomposition_and_noop_pipelines_preserved() {
    let source = format!("e{COMB}");
    for analyzer in [
        uniform("nfd-test", NormalizationForm::Nfd),
        uniform("none-test", NormalizationForm::None),
    ] {
        let tokens = analyzer
            .collect_tokens(
                AnalyzerRole::Index,
                &[source.as_str()],
                &limits(),
                &NeverCancel,
            )
            .expect("analysis");
        assert_eq!(tokens[0].term(), source);
        let raw = format!("e(?:x?{COMB})");
        assert_eq!(pattern(&analyzer, &raw), raw);
    }
}

#[test]
fn a4_i05_safe_classes_after_literal_are_accepted() {
    let analyzer = english();
    assert_eq!(pattern(&analyzer, "e[0-9]"), "e[0-9]");
    assert_eq!(pattern(&analyzer, "e[a-z]"), "e[a-z]");
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &["e1", "ea"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens[0].term(), "e1");
    assert_eq!(tokens[1].term(), "ea");
}

#[test]
fn a4_i06_cancellation_and_budget_with_nested_nullable_ast() {
    let analyzer = standard();
    let nested = format!("e(?:x?y?{COMB})");
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&analyzer, &nested, &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
    let small = AnalysisLimits::default()
        .with_max_work_units(1)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&analyzer, &nested, &small, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}
