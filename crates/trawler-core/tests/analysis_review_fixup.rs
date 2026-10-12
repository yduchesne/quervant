//! PR 4 review-fixup deterministic regression matrix (F4-01…F4-24, IF4-01…IF4-04).
//!
//! Each negative test asserts the specific error variant, not merely `is_err()`.

use std::cell::Cell;

use trawler_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerDefinition, AnalyzerRegistry, AnalyzerRole,
    Cancellation, CancellationFlag, DomainConfig, NeverCancel, NormalizationForm, Pipeline,
    PslPrivateSuffixPolicy, SchemaAnalyzerBindings, StopwordDataset, TokenFilter, TokenizerKind,
    analyze_domain, domain_dataset_identity, prepare_glob, prepare_regex, prepare_term,
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

fn flat_tokens(analyzer: &AnalyzerDefinition, values: &[&str]) -> Vec<String> {
    analyzer
        .collect_tokens(AnalyzerRole::Index, values, &limits(), &NeverCancel)
        .expect("analysis")
        .into_iter()
        .map(|token| token.term().to_owned())
        .collect()
}

fn expect_unsupported(pattern: &str) {
    assert!(
        matches!(
            prepare_regex(&english(), pattern, &limits(), &NeverCancel),
            Err(AnalysisError::UnsupportedPattern { .. })
        ),
        "expected UnsupportedPattern for {pattern:?}"
    );
}

#[test]
fn f4_01_to_f4_06_regex_grammar_is_validated_fail_closed() {
    // F4-01 invalid repetition; F4-02 leading quantifier; F4-04 invalid range;
    // F4-05 dangling escape / unclosed group / unclosed class;
    // F4-06 backreference / lookaround.
    for bad in [
        r"a{3,2}", r"*abc", r"[z-a]", r"(ab", r"a\", r"[a", r"(a)\1", r"a(?=b)",
    ] {
        expect_unsupported(bad);
    }
}

#[test]
fn f4_03_empty_alternation_has_documented_supported_semantics() {
    let regex = prepare_regex(&english(), "a|", &limits(), &NeverCancel).expect("regex");
    assert_eq!(regex.pattern(), "a|");
}

#[test]
fn f4_07_approved_subset_is_accepted() {
    let regex =
        prepare_regex(&english(), r"^ab(c|d)[0-9]{2,4}$", &limits(), &NeverCancel).expect("regex");
    assert_eq!(regex.pattern(), r"^ab(c|d)[0-9]{2,4}$");
}

#[test]
fn f4_08_folded_literal_matches_indexed_term() {
    // Indexed "RUN" on a case-folding analyzer becomes "run".
    assert_eq!(flat_tokens(&english(), &["RUN"]), vec!["run"]);
    let regex = prepare_regex(&english(), "RUN", &limits(), &NeverCancel).expect("regex");
    assert_eq!(regex.pattern(), "run");
}

#[test]
fn f4_09_expansion_policy_is_safe() {
    // Amendment 02 / A2-T08: an unquantified run expansion is re-escaped as literal scalars
    // (safe); a quantified scalar that expands cannot preserve quantifier scope and is rejected.
    assert_eq!(
        prepare_regex(&english(), "Straße", &limits(), &NeverCancel)
            .expect("regex")
            .pattern(),
        "strasse"
    );
    expect_unsupported("ß+");
}

#[test]
fn f4_10_syntax_and_case_sensitive_classes_are_preserved_or_rejected() {
    // Escaped operators and Perl classes are preserved / accepted.
    let escaped = prepare_regex(&english(), r"a\.b", &limits(), &NeverCancel).expect("regex");
    assert_eq!(escaped.pattern(), r"a\.b");
    assert!(prepare_regex(&english(), r"\d+", &limits(), &NeverCancel).is_ok());

    // Case-sensitive ranges are unsafe under folding -> typed rejection.
    expect_unsupported(r"[A-Z]");
    // ... but preserved by a non-folding analyzer.
    let preserved = prepare_regex(&standard(), r"[A-Z]+", &limits(), &NeverCancel).expect("regex");
    assert_eq!(preserved.pattern(), r"[A-Z]+");
}

#[test]
fn f4_11_f4_12_f4_13_fingerprint_aware_compatibility() {
    let registry = registry();
    let baseline = registry.get("english").expect("english").fingerprint();

    // F4-12 exact id/version/fingerprint accepted.
    assert!(
        registry
            .resolve_fingerprint("english", "1.0.0", baseline)
            .is_ok()
    );

    // F4-11 same id/version but different filter order -> fingerprint mismatch.
    let reordered = AnalyzerDefinition::uniform(
        "english",
        "1.0.0",
        Pipeline::simple(
            TokenizerKind::UnicodeWord,
            vec![
                TokenFilter::CaseFold,
                TokenFilter::Normalize(NormalizationForm::Nfc),
            ],
        )
        .expect("pipeline"),
    )
    .expect("definition");
    assert_ne!(baseline, reordered.fingerprint());
    assert!(matches!(
        registry.resolve_fingerprint("english", "1.0.0", reordered.fingerprint()),
        Err(AnalysisError::AnalyzerFingerprintMismatch { .. })
    ));

    // F4-13 wrong version and unknown analyzer.
    assert!(matches!(
        registry.resolve_fingerprint("english", "9.9.9", baseline),
        Err(AnalysisError::AnalyzerVersionMismatch { .. })
    ));
    assert!(matches!(
        registry.resolve_fingerprint("missing", "1.0.0", baseline),
        Err(AnalysisError::UnknownAnalyzer { .. })
    ));
}

#[test]
fn f4_15_f4_22_domain_policy_identity_and_bounds() {
    let include = analyze_domain(
        "www.foo.github.io",
        DomainConfig::default(),
        &limits(),
        &NeverCancel,
    )
    .expect("domain");
    assert_eq!(include.public_suffix(), Some("github.io"));
    assert_eq!(include.registered_domain(), Some("foo.github.io"));

    let icann = analyze_domain(
        "www.foo.github.io",
        DomainConfig {
            psl_private_suffix_policy: PslPrivateSuffixPolicy::IcannOnly,
        },
        &limits(),
        &NeverCancel,
    )
    .expect("domain");
    assert_eq!(icann.public_suffix(), Some("io"));

    // Cancelled domain analysis is typed.
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        analyze_domain("example.com", DomainConfig::default(), &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));

    // Input bound is enforced before the opaque UTS #46 call.
    let bounded = AnalysisLimits::default()
        .with_max_input_bytes(4)
        .expect("lower");
    assert!(matches!(
        analyze_domain(
            "example.com",
            DomainConfig::default(),
            &bounded,
            &NeverCancel
        ),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}

#[test]
fn f4_16_f4_17_token_cap_is_per_value() {
    let registry = registry();
    let whitespace = registry.get("whitespace").expect("whitespace");
    let capped = AnalysisLimits::default().with_max_tokens(2).expect("lower");

    // F4-16 two values, each exactly at the cap, both pass.
    let tokens = whitespace
        .collect_tokens(AnalyzerRole::Index, &["a b", "c d"], &capped, &NeverCancel)
        .expect("each value at cap passes");
    assert_eq!(tokens.len(), 4);

    // F4-17 one value over the cap fails typed.
    assert!(matches!(
        whitespace.collect_tokens(AnalyzerRole::Index, &["a b c"], &capped, &NeverCancel),
        Err(AnalysisError::TooManyTokens { .. })
    ));
}

#[test]
fn f4_18_empty_values_stopwords_and_gap_are_preserved() {
    let english = english();
    let tokens = english
        .collect_tokens(
            AnalyzerRole::Index,
            &["alpha the beta", "", "gamma"],
            &limits(),
            &NeverCancel,
        )
        .expect("analysis");
    let values: Vec<(u32, u32, u32)> = tokens
        .iter()
        .map(|token| {
            (
                token.value_index(),
                token.position(),
                token.position_increment(),
            )
        })
        .collect();
    // alpha(0,pos0,inc1), beta(0,pos2,inc2), gamma(2,pos102,inc100).
    assert_eq!(values, vec![(0, 0, 1), (0, 2, 2), (2, 102, 100)]);
}

#[test]
fn f4_19_first_token_does_not_eagerly_scan_the_whole_value() {
    let registry = registry();
    let whitespace = registry.get("whitespace").expect("whitespace");
    let limits = limits();
    let long = "a ".repeat(50_000);
    let values = [long.as_str()];
    let canceller = CountingCancellation {
        count: Cell::new(0),
    };
    let mut cursor = whitespace
        .analyze(AnalyzerRole::Index, &values, &limits, &canceller)
        .expect("cursor");
    let first = cursor.next_token().expect("no error").expect("first token");
    assert_eq!(first.term(), "a");
    assert_eq!(first.position(), 0);
    // Eager full-value scanning would poll cancellation ~100k/1024 times; lazy scanning polls
    // only at the start/pipeline checkpoints.
    assert!(
        canceller.count.get() <= 8,
        "unexpected cancellation polls: {}",
        canceller.count.get()
    );
}

#[test]
fn f4_20_cancellation_checkpoints_are_typed() {
    let registry = registry();
    let whitespace = registry.get("whitespace").expect("whitespace");
    let limits = limits();

    // Cancelled at start.
    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        whitespace.collect_tokens(AnalyzerRole::Index, &["hello"], &limits, &flag),
        Err(AnalysisError::Cancelled)
    ));

    // Cancelled mid-scan: a long single word charges past the first poll interval.
    let long_word = "a".repeat(5_000);
    let mid = CancelAfterChecks {
        remaining: Cell::new(2),
    };
    assert!(matches!(
        whitespace.collect_tokens(AnalyzerRole::Index, &[long_word.as_str()], &limits, &mid),
        Err(AnalysisError::Cancelled)
    ));

    // Cancelled after the first token was produced.
    let after = CancellationFlag::new();
    let mut cursor = whitespace
        .analyze(AnalyzerRole::Index, &["one two"], &limits, &after)
        .expect("cursor");
    assert!(cursor.next_token().expect("no error").is_some());
    after.cancel();
    assert!(matches!(cursor.next_token(), Err(AnalysisError::Cancelled)));
}

#[test]
fn f4_21_exact_work_capacity_succeeds_and_one_over_fails() {
    let registry = registry();
    let whitespace = registry.get("whitespace").expect("whitespace");
    // One scalar span charge (1) + NFC filter charge (len 1 + 1) = 3 work units.
    let exact = AnalysisLimits::default()
        .with_max_work_units(3)
        .expect("lower");
    assert!(
        whitespace
            .collect_tokens(AnalyzerRole::Index, &["x"], &exact, &NeverCancel)
            .is_ok()
    );
    let under = AnalysisLimits::default()
        .with_max_work_units(2)
        .expect("lower");
    assert!(matches!(
        whitespace.collect_tokens(AnalyzerRole::Index, &["x"], &under, &NeverCancel),
        Err(AnalysisError::WorkBudgetExceeded { .. })
    ));
}

#[test]
fn f4_23_normalization_offsets_reference_original_input() {
    let registry = registry();
    let folded = registry.get("standard_folded").expect("standard_folded");
    let input = "Cafe\u{0301} Straße";
    let tokens = folded
        .collect_tokens(AnalyzerRole::Index, &[input], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens.len(), 2);
    assert_eq!(tokens[0].term(), "café");
    assert_eq!((tokens[0].start_offset(), tokens[0].end_offset()), (0, 6));
    assert_eq!(tokens[1].term(), "strasse");
    assert_eq!((tokens[1].start_offset(), tokens[1].end_offset()), (7, 14));
    for token in &tokens {
        token.validate_against(input).expect("valid boundaries");
    }
}

#[test]
fn if4_01_real_schema_to_term_and_pattern_preparation() {
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
    let term = prepare_term(analyzer, "Running", &limits(), &NeverCancel).expect("term");
    assert_eq!(term.term(), "run");
    let regex = prepare_regex(analyzer, "RUN", &limits(), &NeverCancel).expect("regex");
    assert_eq!(regex.pattern(), "run");
}

#[test]
fn if4_02_cursor_and_collect_agree_with_deterministic_cancellation() {
    let english = english();
    let limits = limits();
    let values = ["The runners ran", "running fast"];
    let collected = english
        .collect_tokens(AnalyzerRole::Index, &values, &limits, &NeverCancel)
        .expect("collect");

    let mut cursor = english
        .analyze(AnalyzerRole::Index, &values, &limits, &NeverCancel)
        .expect("cursor");
    let mut streamed = Vec::new();
    while let Some(token) = cursor.next_token().expect("no error") {
        streamed.push(token);
    }
    assert_eq!(streamed, collected);
    assert_eq!(
        collected
            .iter()
            .map(|token| (token.value_index(), token.position()))
            .collect::<Vec<_>>(),
        vec![(0, 1), (0, 2), (1, 102), (1, 103)]
    );

    // Terminal error leaves no partial success in `collect_tokens`.
    let flag = CancellationFlag::new();
    let mut cursor = english
        .analyze(AnalyzerRole::Index, &["one", "two"], &limits, &flag)
        .expect("cursor");
    assert!(cursor.next_token().expect("no error").is_some());
    flag.cancel();
    assert!(matches!(cursor.next_token(), Err(AnalysisError::Cancelled)));
}

#[test]
fn if4_03_real_domain_analysis_with_pinned_dataset() {
    assert!(domain_dataset_identity().matches_embedded());
    let representations = analyze_domain(
        "sub.Example.co.uk.",
        DomainConfig::default(),
        &limits(),
        &NeverCancel,
    )
    .expect("domain");
    assert!(representations.has_root_dot());
    assert_eq!(representations.reversed_labels(), "uk.co.example.sub");
    assert_eq!(representations.public_suffix(), Some("co.uk"));
    assert_ne!(
        representations.skeleton(),
        representations.canonical_ascii()
    );
}

#[test]
fn if4_04_registry_fingerprint_seam_fails_closed() {
    let registry = registry();
    let definition = registry.get("standard").expect("standard");
    let fingerprint = definition.fingerprint();
    assert!(
        registry
            .resolve_fingerprint("standard", definition.version(), fingerprint)
            .is_ok()
    );

    let conflicting = AnalyzerDefinition::uniform(
        "standard",
        definition.version(),
        Pipeline::simple(
            TokenizerKind::Whitespace,
            vec![TokenFilter::Normalize(NormalizationForm::Nfc)],
        )
        .expect("pipeline"),
    )
    .expect("definition");
    assert!(matches!(
        registry.resolve_fingerprint("standard", definition.version(), conflicting.fingerprint()),
        Err(AnalysisError::AnalyzerFingerprintMismatch { .. })
    ));
}

#[test]
fn f4_24_stopwords_and_prefix_contract_remain_stable() {
    // Uses the pre-existing pinned dataset/stopword behavior; complements the full A4/I4 suite.
    let english = english();
    assert_eq!(
        flat_tokens(&english, &["the running dogs"]),
        vec!["run", "dog"]
    );
    let glob = prepare_glob(&english, "R*n", &limits(), &NeverCancel).expect("glob");
    assert_eq!(glob.normalized(), "r*n");
    assert_eq!(
        StopwordDataset::EnglishSnowball.id(),
        "snowball-english-stopwords"
    );
}
