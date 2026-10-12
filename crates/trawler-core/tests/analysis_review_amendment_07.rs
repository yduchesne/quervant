//! PR 4 review amendment 07 regression matrix (A7-T01…A7-T48, A7-I01…A7-I08).
//!
//! R4-11: bounded input/work/term/output for prefix and glob preparation.
//! R4-12: wildcard operators must not hide cross-boundary Unicode composition.

use trawler_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerDefinition, AnalyzerRegistry, AnalyzerRole,
    CancellationFlag, GlobSegment, NeverCancel, NormalizationForm, Pipeline, TokenFilter,
    TokenizerKind, prepare_glob, prepare_prefix, prepare_regex, prepare_term,
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

fn analyzer_with(name: &str, filters: Vec<TokenFilter>) -> AnalyzerDefinition {
    AnalyzerDefinition::uniform(
        name,
        "1.0.0",
        Pipeline::simple(TokenizerKind::UnicodeWord, filters).expect("pipeline"),
    )
    .expect("definition")
}

fn no_filters() -> AnalyzerDefinition {
    analyzer_with("no-filters-test", vec![])
}
fn casefold_only() -> AnalyzerDefinition {
    analyzer_with("cf-only-test", vec![TokenFilter::CaseFold])
}
fn asciifold_only() -> AnalyzerDefinition {
    analyzer_with("af-only-test", vec![TokenFilter::AsciiFold])
}
fn nfd() -> AnalyzerDefinition {
    analyzer_with(
        "nfd-test",
        vec![TokenFilter::Normalize(NormalizationForm::Nfd)],
    )
}
fn nfkd() -> AnalyzerDefinition {
    analyzer_with(
        "nfkd-test",
        vec![TokenFilter::Normalize(NormalizationForm::Nfkd)],
    )
}
fn none() -> AnalyzerDefinition {
    analyzer_with(
        "none-test",
        vec![TokenFilter::Normalize(NormalizationForm::None)],
    )
}
fn nfkc() -> AnalyzerDefinition {
    analyzer_with(
        "nfkc-test",
        vec![TokenFilter::Normalize(NormalizationForm::Nfkc)],
    )
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

fn glob_text(analyzer: &AnalyzerDefinition, pattern: &str) -> String {
    prepare_glob(analyzer, pattern, &limits(), &NeverCancel)
        .expect("glob accepted")
        .normalized()
        .to_owned()
}

fn glob_segments(analyzer: &AnalyzerDefinition, pattern: &str) -> Vec<GlobSegment> {
    prepare_glob(analyzer, pattern, &limits(), &NeverCancel)
        .expect("glob accepted")
        .segments()
        .to_vec()
}

fn expect_glob_reject(analyzer: &AnalyzerDefinition, pattern: &str) {
    assert!(
        matches!(
            prepare_glob(analyzer, pattern, &limits(), &NeverCancel),
            Err(AnalysisError::UnsupportedPattern { .. })
        ),
        "expected UnsupportedPattern for glob {pattern:?}"
    );
}

fn lowered_input(bytes: u64) -> AnalysisLimits {
    AnalysisLimits::default()
        .with_max_input_bytes(bytes)
        .expect("lower")
}

fn lowered_work(work: u64) -> AnalysisLimits {
    AnalysisLimits::default()
        .with_max_work_units(work)
        .expect("lower")
}

// ---------------------------------------------------------------------------
// A7-T01..T09: input and work budgets
// ---------------------------------------------------------------------------

#[test]
fn a7_t01_prefix_one_over_input_ceiling() {
    assert!(matches!(
        prepare_prefix(&no_filters(), "abcd", &lowered_input(3), &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a7_t02_prefix_exactly_at_input_ceiling() {
    let prepared = prepare_prefix(&no_filters(), "abc", &lowered_input(3), &NeverCancel)
        .expect("prefix at ceiling");
    assert_eq!(prepared.prefix(), "abc");
}

#[test]
fn a7_t03_glob_one_over_input_ceiling() {
    assert!(matches!(
        prepare_glob(&no_filters(), "abcd", &lowered_input(3), &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a7_t04_glob_exactly_at_input_ceiling() {
    let glob = prepare_glob(&no_filters(), "abc", &lowered_input(3), &NeverCancel)
        .expect("glob at ceiling");
    assert_eq!(glob.normalized(), "abc");
    assert_eq!(glob.segments(), &[GlobSegment::Literal("abc".to_owned())]);
}

#[test]
fn a7_t05_multibyte_counted_in_bytes() {
    assert!(matches!(
        prepare_prefix(&no_filters(), "é", &lowered_input(1), &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a7_t06_no_transform_prefix_work_budget() {
    assert!(matches!(
        prepare_prefix(&no_filters(), "abcd", &lowered_work(2), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a7_t07_wildcard_only_glob_work_budget() {
    assert!(matches!(
        prepare_glob(&no_filters(), "****", &lowered_work(2), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a7_t08_escape_heavy_glob_work_budget() {
    let pattern = r"\*".repeat(10);
    assert!(matches!(
        prepare_glob(&no_filters(), &pattern, &lowered_work(5), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a7_t09_exact_work_budget_boundary() {
    // no_filters prefix "abc": 3 input scalars, no filter charges.
    assert!(prepare_prefix(&no_filters(), "abc", &lowered_work(3), &NeverCancel).is_ok());
    assert!(matches!(
        prepare_prefix(&no_filters(), "abc", &lowered_work(2), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

// ---------------------------------------------------------------------------
// A7-T10..T17: cancellation, term and output bounds
// ---------------------------------------------------------------------------

#[test]
fn a7_t10_pre_cancelled_prefix() {
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_prefix(&standard(), "abc", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}

#[test]
fn a7_t11_pre_cancelled_glob() {
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_glob(&standard(), "a*b", &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}

#[test]
fn a7_t12_normalized_prefix_exceeds_term_bytes() {
    let prefix = "ß".repeat(2049); // case-folds to "ss" -> 4098 bytes
    assert!(matches!(
        prepare_prefix(&casefold_only(), &prefix, &limits(), &NeverCancel),
        Err(AnalysisError::TermTooLarge { .. })
    ));
}

#[test]
fn a7_t13_normalized_prefix_exactly_at_term_bytes() {
    let prefix = "a".repeat(4096);
    let prepared = prepare_prefix(&no_filters(), &prefix, &limits(), &NeverCancel)
        .expect("prefix at term ceiling");
    assert_eq!(prepared.prefix().len(), 4096);
}

#[test]
fn a7_t14_glob_segment_exceeds_term_bytes() {
    let pattern = "ß".repeat(2049);
    assert!(matches!(
        prepare_glob(&casefold_only(), &pattern, &limits(), &NeverCancel),
        Err(AnalysisError::TermTooLarge { .. })
    ));
}

#[test]
fn a7_t15_multiple_segments_each_within_term_bound() {
    let pattern = format!("{}*{}", "a".repeat(4000), "b".repeat(4000));
    let glob = prepare_glob(&no_filters(), &pattern, &limits(), &NeverCancel).expect("glob");
    assert_eq!(glob.segments().len(), 3);
    assert_eq!(glob.normalized().len(), 8001);
}

#[test]
fn a7_t16_total_glob_output_exceeds_bound() {
    // "İ" (2 bytes) folds to "i\u{0307}" (3 bytes); input 20 bytes but output 30 bytes.
    let pattern = "İ".repeat(10);
    assert!(matches!(
        prepare_glob(&casefold_only(), &pattern, &lowered_input(20), &NeverCancel),
        Err(AnalysisError::TermTooLarge { .. })
    ));
}

#[test]
fn a7_t17_wildcard_only_long_pattern_is_bounded() {
    let pattern = "*".repeat(1000);
    let glob = prepare_glob(&no_filters(), &pattern, &limits(), &NeverCancel).expect("glob");
    assert_eq!(glob.segments(), &[GlobSegment::AnySequence]);
    assert_eq!(glob.normalized(), "*");
    assert!(matches!(
        prepare_glob(&no_filters(), &pattern, &lowered_work(500), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

// ---------------------------------------------------------------------------
// A7-T18..T20: grammar preservation
// ---------------------------------------------------------------------------

#[test]
fn a7_t18_empty_and_dangling_forms() {
    assert!(matches!(
        prepare_prefix(&standard(), "", &limits(), &NeverCancel),
        Err(AnalysisError::EmptyTerm)
    ));
    assert!(matches!(
        prepare_glob(&standard(), "", &limits(), &NeverCancel),
        Err(AnalysisError::EmptyTerm)
    ));
    assert!(matches!(
        prepare_glob(&standard(), "abc\\", &limits(), &NeverCancel),
        Err(AnalysisError::UnsupportedPattern { .. })
    ));
}

#[test]
fn a7_t19_escaped_operators_stay_literal() {
    let glob = glob_text(&no_filters(), r"a\*b\?c\\d");
    assert_eq!(glob, r"a\*b\?c\\d");
    assert_eq!(
        glob_segments(&no_filters(), r"a\*b\?c\\d"),
        vec![GlobSegment::Literal("a*b?c\\d".to_owned())]
    );
}

#[test]
fn a7_t20_consecutive_operators_collapse() {
    let glob = glob_text(&no_filters(), "a**b");
    assert_eq!(glob, "a*b");
    assert_eq!(
        glob_segments(&no_filters(), "a**b"),
        vec![
            GlobSegment::Literal("a".to_owned()),
            GlobSegment::AnySequence,
            GlobSegment::Literal("b".to_owned()),
        ]
    );
}

// ---------------------------------------------------------------------------
// A7-T21..T36: wildcard normalization safety
// ---------------------------------------------------------------------------

#[test]
fn a7_t21_glob_composition_across_star_rejected() {
    expect_glob_reject(&standard(), &format!("e*{COMB}"));
}

#[test]
fn a7_t22_repeated_zero_width_operators_rejected() {
    expect_glob_reject(&standard(), &format!("e**{COMB}"));
}

#[test]
fn a7_t23_leading_star_then_mark_rejected() {
    expect_glob_reject(&standard(), &format!("*{COMB}"));
}

#[test]
fn a7_t24_literal_only_run_composes() {
    let glob = glob_text(&standard(), &format!("e{COMB}"));
    assert_eq!(glob, "é");
    assert_eq!(
        glob_segments(&standard(), &format!("e{COMB}")),
        vec![GlobSegment::Literal("é".to_owned())]
    );
}

#[test]
fn a7_t25_simple_ascii_star_accepted() {
    assert_eq!(glob_text(&standard(), "a*b"), "a*b");
}

#[test]
fn a7_t26_simple_ascii_question_accepted() {
    assert_eq!(glob_text(&standard(), "a?b"), "a?b");
}

#[test]
fn a7_t27_question_then_mark_rejected() {
    expect_glob_reject(&standard(), &format!("e?{COMB}"));
}

#[test]
fn a7_t28_question_with_casefold_expansion_documented_semantics() {
    // `?` matches one scalar of the indexed term; `ß` folds to the two-scalar literal `ss`.
    assert_eq!(glob_text(&casefold_only(), "?ß"), "?ss");
}

#[test]
fn a7_t29_asciifold_removed_literal_rejected() {
    expect_glob_reject(&asciifold_only(), &format!("?{COMB}"));
}

#[test]
fn a7_t30_leading_trailing_and_mixed_operators() {
    assert_eq!(glob_text(&standard(), "*a"), "*a");
    assert_eq!(glob_text(&standard(), "a*"), "a*");
    assert_eq!(glob_text(&standard(), "?a"), "?a");
    assert_eq!(glob_text(&standard(), "a?"), "a?");
    assert_eq!(glob_text(&standard(), "*?*"), "*?*");
}

#[test]
fn a7_t31_escaped_mark_after_wildcard_rejected() {
    expect_glob_reject(&standard(), &format!("*\\{COMB}"));
}

#[test]
fn a7_t32_escaped_wildcard_next_to_mark_is_literal() {
    let pattern = format!("\\*{COMB}");
    let glob = glob_text(&standard(), &pattern);
    assert_eq!(glob, pattern);
    assert_eq!(
        glob_segments(&standard(), &pattern),
        vec![GlobSegment::Literal(format!("*{COMB}"))]
    );
}

#[test]
fn a7_t33_nfkc_boundary_fails_closed() {
    expect_glob_reject(&nfkc(), &format!("e*{COMB}"));
}

#[test]
fn a7_t34_decomposition_and_noop_pipelines_preserved() {
    let pattern = format!("e*{COMB}");
    assert_eq!(glob_text(&nfd(), &pattern), pattern);
    assert_eq!(glob_text(&nfkd(), &pattern), pattern);
    assert_eq!(glob_text(&none(), &pattern), pattern);
}

#[test]
fn a7_t35_filter_order_evaluated() {
    assert_eq!(glob_text(&nfc_casefold(), "Straße"), "strasse");
    assert_eq!(glob_text(&casefold_nfc(), "Straße"), "strasse");
}

#[test]
fn a7_t36_literal_only_casefold_without_stemming() {
    assert_eq!(glob_text(&casefold_only(), "Straße"), "strasse");
}

// ---------------------------------------------------------------------------
// A7-T37..T48: metadata, determinism, limits, regression
// ---------------------------------------------------------------------------

#[test]
fn a7_t37_metadata_fingerprint_matches_analyzer() {
    let analyzer = standard();
    let prefix = prepare_prefix(&analyzer, "abc", &limits(), &NeverCancel).expect("prefix");
    assert_eq!(prefix.metadata().fingerprint, analyzer.fingerprint());
    let glob = prepare_glob(&analyzer, "a*b", &limits(), &NeverCancel).expect("glob");
    assert_eq!(glob.metadata().fingerprint, analyzer.fingerprint());
}

#[test]
fn a7_t38_repeated_preparation_is_deterministic() {
    let analyzer = standard();
    let first = prepare_glob(&analyzer, "a*b", &limits(), &NeverCancel).expect("glob");
    let second = prepare_glob(&analyzer, "a*b", &limits(), &NeverCancel).expect("glob");
    assert_eq!(first.normalized(), second.normalized());
    assert_eq!(first.segments(), second.segments());
    assert_eq!(first.metadata().fingerprint, second.metadata().fingerprint);
}

#[test]
fn a7_t39_large_input_small_budget_fails_cleanly() {
    let pattern = "a".repeat(1000);
    assert!(matches!(
        prepare_glob(&no_filters(), &pattern, &lowered_work(100), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a7_t40_tiny_term_limit_does_not_panic() {
    let tiny = AnalysisLimits::default()
        .with_max_term_bytes(1)
        .expect("lower");
    assert!(matches!(
        prepare_prefix(&no_filters(), "ab", &tiny, &NeverCancel),
        Err(AnalysisError::TermTooLarge { .. })
    ));
}

#[test]
fn a7_t41_term_stems_but_prefix_and_glob_do_not() {
    let analyzer = english();
    let term = prepare_term(&analyzer, "Running", &limits(), &NeverCancel).expect("term");
    assert_eq!(term.term(), "run");
    assert_eq!(
        prepare_prefix(&analyzer, "running", &limits(), &NeverCancel)
            .expect("prefix")
            .prefix(),
        "running"
    );
    assert_eq!(glob_text(&analyzer, "running"), "running");
}

#[test]
fn a7_t42_prepare_regex_unchanged() {
    assert!(matches!(
        prepare_regex(&standard(), "e[^a]", &limits(), &NeverCancel),
        Err(AnalysisError::UnsupportedPattern { .. })
    ));
    assert_eq!(
        prepare_regex(&standard(), "e[0-9]", &limits(), &NeverCancel)
            .expect("regex")
            .pattern(),
        "e[0-9]"
    );
}

#[test]
fn a7_t43_limits_ceilings_cannot_be_raised() {
    assert!(AnalysisLimits::new(u64::MAX, 1, 1, 1).is_err());
    assert!(AnalysisLimits::default().with_max_work_units(0).is_err());
    assert!(AnalysisLimits::default().with_max_input_bytes(0).is_err());
}

#[test]
fn a7_t44_empty_literal_segments_do_not_bypass() {
    assert_eq!(glob_text(&no_filters(), "a**b"), "a*b");
    assert_eq!(glob_text(&no_filters(), "a??b"), "a??b");
}

#[test]
fn a7_t45_multibyte_escaped_scalar_accounting() {
    // Backslash + é (2 bytes) = 3 input bytes, one literal scalar.
    let prepared = prepare_prefix(&no_filters(), "é", &limits(), &NeverCancel).expect("prefix");
    assert_eq!(prepared.prefix(), "é");
    assert!(matches!(
        prepare_prefix(&no_filters(), "é", &lowered_input(1), &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a7_t46_zero_filter_work_accounting_is_filter_independent() {
    assert!(matches!(
        prepare_prefix(&no_filters(), "abcdef", &lowered_work(3), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a7_t47_input_preflight_before_work() {
    // Input ceiling wins over a too-small work budget.
    let limits = AnalysisLimits::default()
        .with_max_input_bytes(3)
        .expect("lower")
        .with_max_work_units(1)
        .expect("lower");
    assert!(matches!(
        prepare_prefix(&no_filters(), "abcde", &limits, &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a7_t48_existing_glob_contract_remains_valid() {
    let glob = prepare_glob(&english(), r"F*oo\?b?r", &limits(), &NeverCancel).expect("glob");
    assert_eq!(glob.normalized(), r"f*oo\?b?r");
    assert_eq!(
        glob.segments(),
        &[
            GlobSegment::Literal("f".to_owned()),
            GlobSegment::AnySequence,
            GlobSegment::Literal("oo?b".to_owned()),
            GlobSegment::AnyChar,
            GlobSegment::Literal("r".to_owned()),
        ]
    );
}

// ---------------------------------------------------------------------------
// A7-I integration slices
// ---------------------------------------------------------------------------

#[test]
fn a7_i01_index_composition_and_glob_rejection() {
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
    expect_glob_reject(&analyzer, &format!("e*{COMB}"));
}

#[test]
fn a7_i02_casefold_index_and_literal_glob() {
    let analyzer = casefold_only();
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &["Straße"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens[0].term(), "strasse");
    assert_eq!(glob_text(&analyzer, "Straße"), "strasse");
}

#[test]
fn a7_i03_no_filter_analyzer_budgets() {
    assert!(matches!(
        prepare_prefix(&no_filters(), "abcd", &lowered_work(2), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
    assert!(matches!(
        prepare_glob(&no_filters(), "****", &lowered_work(2), &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a7_i04_safe_operators_shape_and_serialization() {
    let glob = prepare_glob(&standard(), r"a?b\*c", &limits(), &NeverCancel).expect("glob");
    assert_eq!(glob.normalized(), r"a?b\*c");
    assert_eq!(
        glob.segments(),
        &[
            GlobSegment::Literal("a".to_owned()),
            GlobSegment::AnyChar,
            GlobSegment::Literal("b*c".to_owned()),
        ]
    );
}

#[test]
fn a7_i05_filter_orders_and_fingerprint() {
    let a = nfc_casefold();
    let b = casefold_nfc();
    assert_ne!(a.fingerprint(), b.fingerprint());
    assert_eq!(glob_text(&a, "Straße"), "strasse");
    assert_eq!(glob_text(&b, "Straße"), "strasse");
    expect_glob_reject(&a, &format!("e*{COMB}"));
    expect_glob_reject(&b, &format!("e*{COMB}"));
}

#[test]
fn a7_i06_exact_and_one_over_limits() {
    assert!(prepare_prefix(&no_filters(), "abc", &lowered_input(3), &NeverCancel).is_ok());
    assert!(matches!(
        prepare_prefix(&no_filters(), "abcd", &lowered_input(3), &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
    assert!(prepare_glob(&no_filters(), "abc", &lowered_input(3), &NeverCancel).is_ok());
    assert!(matches!(
        prepare_glob(&no_filters(), "abcd", &lowered_input(3), &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn a7_i07_failures_leave_no_prepared_object_then_recover() {
    let analyzer = no_filters();
    let small = lowered_work(2);
    assert!(prepare_prefix(&analyzer, "abcd", &small, &NeverCancel).is_err());
    // A subsequent independent valid call succeeds.
    assert!(prepare_prefix(&analyzer, "ab", &limits(), &NeverCancel).is_ok());
    assert!(prepare_glob(&analyzer, "a*b", &limits(), &NeverCancel).is_ok());
}
