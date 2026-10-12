//! PR 4 review amendment 02 regression matrix (A2-T01…A2-T27, A2-I01…A2-I04).
//!
//! Negative tests assert the specific error variant. Values use actual decomposed/composed
//! Unicode scalars rather than regex escapes unless an escape is the point of the test.

use std::cell::Cell;

use trawler_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerDefinition, AnalyzerRegistry, AnalyzerRole,
    Cancellation, CancellationFlag, DomainConfig, NeverCancel, NormalizationForm, Pipeline,
    PslPrivateSuffixPolicy, SchemaAnalyzerBindings, TokenFilter, TokenizerKind, analyze_domain,
    domain_dataset_identity, prepare_regex, prepare_term,
};
use trawler_core::contract::document::Cardinality;
use trawler_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use trawler_core::contract::value::FieldType;

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn limits() -> AnalysisLimits {
    AnalysisLimits::default()
}

fn english() -> AnalyzerDefinition {
    registry().get("english").expect("english").clone()
}

fn standard() -> AnalyzerDefinition {
    registry().get("standard").expect("standard").clone()
}

fn nfd() -> AnalyzerDefinition {
    AnalyzerDefinition::uniform(
        "nfd-test",
        "1.0.0",
        Pipeline::simple(
            TokenizerKind::UnicodeWord,
            vec![TokenFilter::Normalize(NormalizationForm::Nfd)],
        )
        .expect("pipeline"),
    )
    .expect("definition")
}

fn keyword_bare() -> AnalyzerDefinition {
    AnalyzerDefinition::uniform(
        "keyword-bare-test",
        "1.0.0",
        Pipeline::simple(TokenizerKind::Keyword, vec![]).expect("pipeline"),
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

struct CountingCancellation {
    count: Cell<u32>,
}

impl Cancellation for CountingCancellation {
    fn is_cancelled(&self) -> bool {
        self.count.set(self.count.get() + 1);
        false
    }
}

struct CancelAfterChecks {
    remaining: Cell<u32>,
}

impl Cancellation for CancelAfterChecks {
    fn is_cancelled(&self) -> bool {
        let left = self.remaining.get();
        if left == 0 {
            true
        } else {
            self.remaining.set(left - 1);
            false
        }
    }
}

// ---------------------------------------------------------------------------
// A2-01: regex literal-run normalization
// ---------------------------------------------------------------------------

#[test]
fn a2_t01_nfc_literal_run_composes_across_scalars() {
    let analyzer = standard();
    let decomposed = "e\u{0301}";
    assert_eq!(pattern(&analyzer, decomposed), "é");
    // Reference: the indexed term for the same source must be the composed form.
    let indexed = analyzer
        .collect_tokens(AnalyzerRole::Index, &[decomposed], &limits(), &NeverCancel)
        .expect("indexed");
    assert_eq!(indexed.len(), 1);
    assert_eq!(indexed[0].term(), "é");
}

#[test]
fn a2_t02_already_composed_nfc_is_stable() {
    assert_eq!(pattern(&standard(), "é"), "é");
}

#[test]
fn a2_t03_nfd_decomposes_composed_literal() {
    assert_eq!(pattern(&nfd(), "é"), "e\u{0301}");
}

#[test]
fn a2_t04_escaped_metacharacter_is_preserved() {
    assert_eq!(pattern(&standard(), r"a\.b"), r"a\.b");
}

#[test]
fn a2_t05_quantified_combining_mark_is_rejected() {
    // A combining mark governed by a quantifier can compose with a preceding base across the
    // quantifier boundary; reject rather than risk a silent scope change.
    expect_reject(&standard(), "e\u{0301}+");
    expect_reject(&standard(), "\u{0301}*");
}

#[test]
fn a2_t06_no_composition_across_alternation_branches() {
    assert_eq!(pattern(&standard(), "(e|é)"), "(e|é)");
}

#[test]
fn a2_t07_group_anchor_repetition_do_not_drift() {
    assert_eq!(pattern(&standard(), r"^(ab){2}$"), r"^(ab){2}$");
    assert_eq!(pattern(&standard(), r"[a-z]+"), r"[a-z]+");
}

#[test]
fn a2_t08_expansion_policy_is_safe() {
    // Unquantified run expansion is re-escaped as literal scalars.
    assert_eq!(pattern(&english(), "Straße"), "strasse");
    assert_eq!(pattern(&english(), "Straße+"), "strasse+");
    // A quantified scalar that expands cannot preserve quantifier scope.
    expect_reject(&english(), "ß+");
}

#[test]
fn a2_t09_long_run_respects_work_budget_and_cancellation() {
    let long = "a".repeat(10_000);
    let small = AnalysisLimits::default()
        .with_max_work_units(100)
        .expect("lower");
    assert!(matches!(
        prepare_regex(&standard(), &long, &small, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        prepare_regex(&standard(), &long, &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));
}

// ---------------------------------------------------------------------------
// A2-03: fail-closed class/range semantics
// ---------------------------------------------------------------------------

#[test]
fn a2_t10_case_sensitive_range_is_rejected_when_folding() {
    expect_reject(&english(), "[A-Z]");
}

#[test]
fn a2_t11_stable_endpoints_unsafe_interior_is_rejected() {
    // '@'..'a' contains 'A'..'Z', whose case-folded forms are not all in the range.
    expect_reject(&english(), "[@-a]");
}

#[test]
fn a2_t12_predefined_case_classes_are_rejected_when_folding() {
    expect_reject(&english(), "[[:upper:]]");
    expect_reject(&english(), r"\p{Lu}");
}

#[test]
fn a2_t13_safe_predefined_classes_are_accepted_with_proof() {
    for good in [r"\w", r"\d", r"\s", "[[:lower:]]", "[[:alpha:]]"] {
        assert!(
            prepare_regex(&english(), good, &limits(), &NeverCancel).is_ok(),
            "expected acceptance for {good:?}"
        );
    }
}

#[test]
fn a2_t14_digit_class_under_nfc_only_is_accepted() {
    assert_eq!(pattern(&standard(), "[0-9]"), "[0-9]");
}

#[test]
fn a2_t15_class_with_quantifier_and_escaped_bracket_preserved() {
    assert_eq!(pattern(&standard(), r"[\]]{2,4}"), r"[\]]{2,4}");
}

// ---------------------------------------------------------------------------
// A2-02: truthful incremental work and cancellation
// ---------------------------------------------------------------------------

#[test]
fn a2_t16_keyword_charges_incrementally() {
    let analyzer = keyword_bare();
    let value = "a".repeat(4_000);
    let values = [value.as_str()];
    let counter = CountingCancellation {
        count: Cell::new(0),
    };
    let limits = limits();
    let mut cursor = analyzer
        .analyze(AnalyzerRole::Index, &values, &limits, &counter)
        .expect("cursor");
    let token = cursor.next_token().expect("no error").expect("token");
    assert_eq!(token.term().chars().count(), 4_000);
    // Incremental charging polls cancellation ~5,000/1,024 times; a single whole-value charge
    // would poll only once after scanning the entire value.
    assert!(
        counter.count.get() >= 5,
        "keyword did not charge incrementally: polls={}",
        counter.count.get()
    );

    // Cancellation after a fixed checkpoint is observed before the token is emitted.
    let cancel_after = CancelAfterChecks {
        remaining: Cell::new(2),
    };
    let mut cursor = analyzer
        .analyze(AnalyzerRole::Index, &values, &limits, &cancel_after)
        .expect("cursor");
    assert!(matches!(cursor.next_token(), Err(AnalysisError::Cancelled)));
}

#[test]
fn a2_t17_keyword_exact_work_budget() {
    let analyzer = keyword_bare();
    let exact = AnalysisLimits::default()
        .with_max_work_units(5)
        .expect("lower");
    assert!(
        analyzer
            .collect_tokens(AnalyzerRole::Index, &["hello"], &exact, &NeverCancel)
            .is_ok()
    );
    let under = AnalysisLimits::default()
        .with_max_work_units(4)
        .expect("lower");
    assert!(matches!(
        analyzer.collect_tokens(AnalyzerRole::Index, &["hello"], &under, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a2_t18_uax29_single_word_exact_segmentation() {
    let analyzer = standard();
    let value = "a".repeat(4_000);
    let tokens = analyzer
        .collect_tokens(
            AnalyzerRole::Index,
            &[value.as_str()],
            &limits(),
            &NeverCancel,
        )
        .expect("analysis");
    assert_eq!(tokens.len(), 1);
    assert_eq!(tokens[0].term().chars().count(), 4_000);
    assert_eq!(
        (tokens[0].start_offset(), tokens[0].end_offset()),
        (0, 4_000)
    );
}

#[test]
fn a2_t19_long_punctuation_before_first_word_is_charged_and_bounded() {
    let analyzer = standard();
    let value = format!("{}word", "!".repeat(5_000));
    let tokens = analyzer
        .collect_tokens(
            AnalyzerRole::Index,
            &[value.as_str()],
            &limits(),
            &NeverCancel,
        )
        .expect("analysis");
    assert_eq!(tokens.len(), 1);
    assert_eq!(tokens[0].term(), "word");
    assert_eq!(
        (tokens[0].start_offset(), tokens[0].end_offset()),
        (5_000, 5_004)
    );

    let tiny = AnalysisLimits::default()
        .with_max_work_units(10)
        .expect("lower");
    assert!(matches!(
        analyzer.collect_tokens(AnalyzerRole::Index, &[value.as_str()], &tiny, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn a2_t20_multibyte_offsets_are_unchanged() {
    let analyzer = standard();
    let value = "héllo—wörld";
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &[value], &limits(), &NeverCancel)
        .expect("analysis");
    for token in &tokens {
        token.validate_against(value).expect("boundaries");
        assert_eq!(
            &value[token.start_offset() as usize..token.end_offset() as usize],
            token.term()
        );
    }
}

#[test]
fn a2_t21_call_wide_work_budget_and_per_value_token_ceiling() {
    let analyzer = registry().get("whitespace").expect("whitespace").clone();
    let capped = AnalysisLimits::default().with_max_tokens(2).expect("lower");
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &["a b", "c d"], &capped, &NeverCancel)
        .expect("per-value cap");
    assert_eq!(tokens.len(), 4);

    let tiny = AnalysisLimits::default()
        .with_max_work_units(2)
        .expect("lower");
    assert!(matches!(
        analyzer.collect_tokens(AnalyzerRole::Index, &["a b", "c d"], &tiny, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

// ---------------------------------------------------------------------------
// A2-04: terminal cursor errors
// ---------------------------------------------------------------------------

#[test]
fn a2_t22_terminal_error_is_latched() {
    // Per-value token ceiling exceeded mid-stream: the first error must be terminal.
    let analyzer = registry().get("whitespace").expect("whitespace").clone();
    let capped = AnalysisLimits::default().with_max_tokens(2).expect("lower");
    let values = ["a b c d"];
    let mut cursor = analyzer
        .analyze(AnalyzerRole::Index, &values, &capped, &NeverCancel)
        .expect("cursor");
    assert!(cursor.next_token().expect("token a").is_some());
    assert!(cursor.next_token().expect("token b").is_some());
    assert!(matches!(
        cursor.next_token(),
        Err(AnalysisError::TooManyTokens { .. })
    ));
    for _ in 0..2 {
        assert!(matches!(
            cursor.next_token(),
            Err(AnalysisError::TooManyTokens { .. })
        ));
    }
}

#[test]
fn a2_t23_cancellation_after_token_is_terminal() {
    let analyzer = registry().get("whitespace").expect("whitespace").clone();
    let values = ["one two three"];
    let flag = CancellationFlag::new();
    let limits = limits();
    let mut cursor = analyzer
        .analyze(AnalyzerRole::Index, &values, &limits, &flag)
        .expect("cursor");
    assert!(cursor.next_token().expect("token").is_some());
    flag.cancel();
    for _ in 0..2 {
        assert!(matches!(cursor.next_token(), Err(AnalysisError::Cancelled)));
    }
}

#[test]
fn a2_t24_too_many_tokens_is_terminal() {
    let analyzer = registry().get("whitespace").expect("whitespace").clone();
    let capped = AnalysisLimits::default().with_max_tokens(1).expect("lower");
    let values = ["a b c"];
    let mut cursor = analyzer
        .analyze(AnalyzerRole::Index, &values, &capped, &NeverCancel)
        .expect("cursor");
    assert!(cursor.next_token().expect("token a").is_some());
    assert!(matches!(
        cursor.next_token(),
        Err(AnalysisError::TooManyTokens { .. })
    ));
    assert!(matches!(
        cursor.next_token(),
        Err(AnalysisError::TooManyTokens { .. })
    ));
}

#[test]
fn a2_t26_eof_is_idempotent() {
    let analyzer = keyword_bare();
    let values = ["hello"];
    let limits = limits();
    let mut cursor = analyzer
        .analyze(AnalyzerRole::Index, &values, &limits, &NeverCancel)
        .expect("cursor");
    assert!(cursor.next_token().expect("token").is_some());
    assert!(cursor.next_token().expect("eof").is_none());
    assert!(cursor.next_token().expect("eof").is_none());
    assert!(cursor.next_token().expect("eof").is_none());
}

#[test]
fn a2_t27_collect_tokens_never_returns_partial_success() {
    let analyzer = registry().get("whitespace").expect("whitespace").clone();
    let capped = AnalysisLimits::default().with_max_tokens(1).expect("lower");
    assert!(matches!(
        analyzer.collect_tokens(AnalyzerRole::Index, &["a b c"], &capped, &NeverCancel),
        Err(AnalysisError::TooManyTokens { .. })
    ));
}

// ---------------------------------------------------------------------------
// A2-I vertical slices
// ---------------------------------------------------------------------------

#[test]
fn a2_i01_nfc_indexing_and_literal_preparation_agree() {
    let analyzer = standard();
    let decomposed = "e\u{0301}";
    let indexed = analyzer
        .collect_tokens(AnalyzerRole::Index, &[decomposed], &limits(), &NeverCancel)
        .expect("indexed");
    let prepared = prepare_regex(&analyzer, decomposed, &limits(), &NeverCancel).expect("regex");
    assert_eq!(indexed[0].term(), prepared.pattern());
}

#[test]
fn a2_i02_folded_analyzer_rejects_unsafe_class() {
    assert!(matches!(
        prepare_regex(&english(), "[@-a]", &limits(), &NeverCancel),
        Err(AnalysisError::UnsupportedPattern { .. })
    ));
}

#[test]
fn a2_i03_schema_binding_cursor_and_mid_stream_cancellation() {
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("english"),
        ],
        None,
    )
    .expect("schema");
    let registry = registry();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry).expect("bindings");
    assert!(bindings.get("body").expect("body").index.is_some());

    let analyzer = registry.get("english").expect("english");
    let values = ["alpha beta gamma"];
    let flag = CancellationFlag::new();
    let limits = limits();
    let mut cursor = analyzer
        .analyze(AnalyzerRole::Index, &values, &limits, &flag)
        .expect("cursor");
    assert!(cursor.next_token().expect("first").is_some());
    flag.cancel();
    assert!(matches!(cursor.next_token(), Err(AnalysisError::Cancelled)));
    assert!(matches!(cursor.next_token(), Err(AnalysisError::Cancelled)));
}

#[test]
fn a2_i04_fingerprint_domain_and_term_seams_preserved() {
    let registry = registry();
    let definition = registry.get("standard").expect("standard");
    assert!(
        registry
            .resolve_fingerprint("standard", definition.version(), definition.fingerprint())
            .is_ok()
    );
    let term = prepare_term(definition, "Hello", &limits(), &NeverCancel).expect("term");
    assert_eq!(term.term(), "Hello");

    assert!(domain_dataset_identity().matches_embedded());
    let domain = analyze_domain(
        "www.foo.github.io",
        DomainConfig {
            psl_private_suffix_policy: PslPrivateSuffixPolicy::IncludePrivate,
        },
        &limits(),
        &NeverCancel,
    )
    .expect("domain");
    assert_eq!(domain.public_suffix(), Some("github.io"));
}
