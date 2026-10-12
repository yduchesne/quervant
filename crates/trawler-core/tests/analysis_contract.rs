//! PR 4 analyzer contract integration tests (A4-01…A4-22, I4-01, I4-03, I4-04).
//!
//! These exercise the real exported analyzer API together with the existing schema contract;
//! they do not reimplement tokenization.

use std::cell::Cell;
use std::collections::BTreeMap;

use trawler_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerRegistry, AnalyzerRole, Cancellation, CancellationFlag,
    GlobSegment, NeverCancel, SchemaAnalyzerBindings, Token, prepare_glob, prepare_prefix,
    prepare_regex, prepare_term,
};
use trawler_core::contract::document::Cardinality;
use trawler_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use trawler_core::contract::value::FieldType;
use trawler_core::storage::{Directory, MemoryDirectory, StorageKey};

const GOLDEN: &str = include_str!("fixtures/analysis/golden.tsv");

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn limits() -> AnalysisLimits {
    AnalysisLimits::default()
}

fn decode_escapes(input: &str) -> String {
    let mut output = String::new();
    let mut chars = input.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\\' && chars.peek() == Some(&'u') {
            chars.next();
            assert_eq!(chars.next(), Some('{'));
            let mut hex = String::new();
            for next in chars.by_ref() {
                if next == '}' {
                    break;
                }
                hex.push(next);
            }
            let code = u32::from_str_radix(&hex, 16).expect("valid hex escape");
            output.push(char::from_u32(code).expect("valid scalar value"));
        } else {
            output.push(ch);
        }
    }
    output
}

#[test]
fn a4_01_baseline_tokenizers_exact_metadata() {
    let registry = registry();
    let limits = limits();

    let keyword = registry.get("keyword").expect("keyword");
    let tokens = keyword
        .collect_tokens(AnalyzerRole::Index, &["  Hello  "], &limits, &NeverCancel)
        .expect("keyword analysis");
    assert_eq!(tokens.len(), 1);
    assert_eq!(tokens[0].term(), "  Hello  ");
    assert_eq!(tokens[0].position(), 0);
    assert_eq!(tokens[0].position_increment(), 1);
    assert_eq!(tokens[0].position_length(), 1);
    assert_eq!(tokens[0].start_offset(), 0);
    assert_eq!(tokens[0].end_offset(), 9);

    let whitespace = registry.get("whitespace").expect("whitespace");
    let tokens = whitespace
        .collect_tokens(AnalyzerRole::Index, &["a\tb"], &limits, &NeverCancel)
        .expect("whitespace analysis");
    assert_eq!(tokens.len(), 2);
    assert_eq!(
        (
            tokens[0].term(),
            tokens[0].start_offset(),
            tokens[0].end_offset()
        ),
        ("a", 0, 1)
    );
    assert_eq!(
        (
            tokens[1].term(),
            tokens[1].start_offset(),
            tokens[1].end_offset()
        ),
        ("b", 2, 3)
    );
    assert_eq!(tokens[1].position(), 1);

    let word = registry.get("standard").expect("standard");
    let tokens = word
        .collect_tokens(AnalyzerRole::Index, &["The quick"], &limits, &NeverCancel)
        .expect("word analysis");
    assert_eq!(tokens.len(), 2);
    assert_eq!(tokens[0].term(), "The");
    assert_eq!(tokens[1].term(), "quick");
}

#[test]
fn a4_02_multibyte_offsets_are_utf8_boundaries() {
    let registry = registry();
    let values = ["café—naïve 😀"];
    let tokens = registry
        .get("standard")
        .expect("standard")
        .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
        .expect("analysis");
    assert!(!tokens.is_empty());
    for token in &tokens {
        token.validate_against(values[0]).expect("valid boundaries");
        assert_eq!(
            &values[0][token.start_offset() as usize..token.end_offset() as usize],
            token.term()
        );
    }
}

#[test]
fn a4_03_normalization_changes_term_length_but_not_offsets() {
    let registry = registry();
    let input = "Cafe\u{0301}";
    let tokens = registry
        .get("standard_folded")
        .expect("standard_folded")
        .collect_tokens(AnalyzerRole::Index, &[input], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens.len(), 1);
    assert_eq!(tokens[0].term(), "café");
    // Source span is the 6-byte decomposed sequence; the term is 5 bytes.
    assert_eq!((tokens[0].start_offset(), tokens[0].end_offset()), (0, 6));
    assert_ne!(tokens[0].term().len(), 6);
    assert_eq!(&input[0..6], "Cafe\u{0301}");
}

#[test]
fn a4_04_stopword_holes_are_preserved() {
    let registry = registry();
    let english = registry.get("english").expect("english");

    let tokens = english
        .collect_tokens(
            AnalyzerRole::Index,
            &["alpha the beta"],
            &limits(),
            &NeverCancel,
        )
        .expect("analysis");
    assert_eq!(tokens.len(), 2);
    assert_eq!(tokens[0].term(), "alpha");
    assert_eq!(tokens[0].position(), 0);
    assert_eq!(tokens[0].position_increment(), 1);
    assert_eq!(tokens[1].term(), "beta");
    assert_eq!(tokens[1].position(), 2);
    assert_eq!(tokens[1].position_increment(), 2);

    let leading = english
        .collect_tokens(AnalyzerRole::Index, &["the alpha"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(leading.len(), 1);
    assert_eq!(leading[0].position(), 1);
    assert_eq!(leading[0].position_increment(), 2);

    let trailing = english
        .collect_tokens(AnalyzerRole::Index, &["alpha the"], &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(trailing.len(), 1);
    assert_eq!(trailing[0].term(), "alpha");
}

#[test]
fn a4_05_multivalue_gap_and_per_value_offsets() {
    let registry = registry();
    let values = ["a b", "", "c d"];
    let tokens = registry
        .get("standard")
        .expect("standard")
        .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(tokens.len(), 4);

    assert_eq!(tokens[0].value_index(), 0);
    assert_eq!(tokens[1].value_index(), 0);
    assert_eq!(tokens[2].value_index(), 2);
    assert_eq!(tokens[3].value_index(), 2);

    // Empty value 1 consumes no positions; the gap to value 2 is still at least 100.
    assert_eq!(tokens[1].position(), 1);
    assert_eq!(tokens[2].position(), 101);
    assert!(tokens[2].position() - tokens[1].position() >= 100);
    assert!(tokens[2].position_increment() >= 100);

    // Offsets are relative to each source value.
    assert_eq!((tokens[2].start_offset(), tokens[2].end_offset()), (0, 1));
    assert_eq!((tokens[3].start_offset(), tokens[3].end_offset()), (2, 3));
}

#[test]
fn a4_06_zero_increment_is_rejected_and_never_emitted() {
    assert!(Token::new("a", 0, 0, 0, 1, 0, 1).is_err());
    let values = ["alpha the beta"];
    let tokens = registry()
        .get("english")
        .expect("english")
        .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
        .expect("analysis");
    assert!(tokens.iter().all(|token| token.position_increment() >= 1));
}

#[test]
fn a4_07_bounds_are_checked_not_saturated() {
    assert!(AnalysisLimits::new(u64::MAX, 1, 1, 1).is_err());
    let token = Token::new("a", 0, 0, 1, 1, 5, 4);
    assert!(token.is_err());
    // The position-overflow path is additionally exercised by the analyzer unit test
    // `position_overflow_is_checked`; here we confirm the public limits reject over-ceiling
    // configuration instead of clamping.
    assert!(AnalysisLimits::default().with_max_tokens(u64::MAX).is_err());
}

#[test]
fn a4_08_exact_limit_succeeds_and_one_over_fails() {
    let registry = registry();
    let standard = registry.get("standard").expect("standard");

    let exact = AnalysisLimits::default()
        .with_max_input_bytes(5)
        .expect("lower");
    assert!(
        standard
            .collect_tokens(AnalyzerRole::Index, &["hello"], &exact, &NeverCancel)
            .is_ok()
    );
    let under = AnalysisLimits::default()
        .with_max_input_bytes(4)
        .expect("lower");
    assert!(matches!(
        standard.collect_tokens(AnalyzerRole::Index, &["hello"], &under, &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));

    let whitespace = registry.get("whitespace").expect("whitespace");
    let exact_tokens = AnalysisLimits::default().with_max_tokens(3).expect("lower");
    assert!(
        whitespace
            .collect_tokens(AnalyzerRole::Index, &["a b c"], &exact_tokens, &NeverCancel)
            .is_ok()
    );
    let under_tokens = AnalysisLimits::default().with_max_tokens(2).expect("lower");
    assert!(matches!(
        whitespace.collect_tokens(AnalyzerRole::Index, &["a b c"], &under_tokens, &NeverCancel),
        Err(AnalysisError::TooManyTokens { .. })
    ));
}

struct CancelAfter {
    remaining: Cell<u32>,
}

impl Cancellation for CancelAfter {
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

#[test]
fn a4_09_cancellation_at_start_and_mid_analysis() {
    let registry = registry();
    let standard = registry.get("standard").expect("standard");

    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        standard.collect_tokens(AnalyzerRole::Index, &["hello"], &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));

    let long = "a ".repeat(3000);
    let canceller = CancelAfter {
        remaining: Cell::new(1),
    };
    assert!(matches!(
        standard.collect_tokens(AnalyzerRole::Index, &[long.as_str()], &limits(), &canceller),
        Err(AnalysisError::Cancelled)
    ));
}

#[test]
fn a4_10_analyzer_version_mismatch_fails_closed() {
    let registry = registry();
    let error = registry
        .resolve_compatible("standard", "2.0.0")
        .expect_err("mismatch");
    assert!(matches!(
        error,
        AnalysisError::AnalyzerVersionMismatch { .. }
    ));
    assert!(registry.resolve_compatible("standard", "1.0.0").is_ok());
}

#[test]
fn a4_11_determinism_across_runs_and_registries() {
    let values = ["The quick brown foxes jumped", "running"];
    let first = registry()
        .get("english")
        .expect("english")
        .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
        .expect("analysis");
    let second = registry()
        .get("english")
        .expect("english")
        .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
        .expect("analysis");
    assert_eq!(first, second);

    let first_fingerprint = registry().get("english").expect("english").fingerprint();
    let second_fingerprint = registry().get("english").expect("english").fingerprint();
    assert_eq!(first_fingerprint, second_fingerprint);
}

#[test]
fn a4_12_english_stopwords_and_stemming_pinned_fixture() {
    let registry = registry();
    let mut expected: BTreeMap<&str, Vec<Vec<&str>>> = BTreeMap::new();
    for line in GOLDEN.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let fields: Vec<&str> = line.split('\t').collect();
        expected.entry(fields[0]).or_default().push(fields.to_vec());
    }

    for (analyzer_name, rows) in expected {
        let analyzer = registry.get(analyzer_name).expect("analyzer");
        // All rows for one analyzer share the same input in this fixture.
        let input = decode_escapes(rows[0][1]);
        let tokens = analyzer
            .collect_tokens(
                AnalyzerRole::Index,
                &[input.as_str()],
                &limits(),
                &NeverCancel,
            )
            .expect("analysis");
        assert_eq!(tokens.len(), rows.len(), "token count for {analyzer_name}");
        for (token, row) in tokens.iter().zip(&rows) {
            assert_eq!(token.term(), row[2], "term for {analyzer_name}");
            assert_eq!(token.position(), row[3].parse::<u32>().expect("position"));
            assert_eq!(
                token.position_increment(),
                row[4].parse::<u32>().expect("increment")
            );
            assert_eq!(token.start_offset(), row[5].parse::<u32>().expect("start"));
            assert_eq!(token.end_offset(), row[6].parse::<u32>().expect("end"));
        }
    }
}

#[test]
fn a4_13_prefix_glob_regex_contract() {
    let registry = registry();
    let english = registry.get("english").expect("english");

    let prefix = prepare_prefix(english, "RUNNING", &limits(), &NeverCancel).expect("prefix");
    assert_eq!(prefix.prefix(), "running");

    let glob = prepare_glob(english, r"R*n\?ing", &limits(), &NeverCancel).expect("glob");
    assert_eq!(
        glob.segments(),
        &[
            GlobSegment::Literal("r".to_owned()),
            GlobSegment::AnySequence,
            GlobSegment::Literal("n?ing".to_owned()),
        ]
    );
    assert_eq!(glob.normalized(), r"r*n\?ing");

    assert!(prepare_regex(english, r"^run(ning)?$", &limits(), &NeverCancel).is_ok());
    assert!(matches!(
        prepare_regex(english, r"(?=run)", &limits(), &NeverCancel),
        Err(AnalysisError::UnsupportedPattern { .. })
    ));
}

#[test]
fn a4_18_schema_type_restrictions_are_preserved() {
    let text_with_normalizer = FieldDefinition::new(
        "body",
        FieldType::Text,
        Cardinality::Single,
        FieldOptions::indexed_stored(),
    )
    .with_normalizer("keyword");
    assert!(Schema::new(vec![text_with_normalizer], None).is_err());

    let keyword_with_analyzer = FieldDefinition::new(
        "tag",
        FieldType::Keyword,
        Cardinality::Single,
        FieldOptions::indexed_stored(),
    )
    .with_analyzer("standard");
    assert!(Schema::new(vec![keyword_with_analyzer], None).is_err());
}

#[test]
fn a4_19_no_analyzers_configured_is_valid() {
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
        ],
        None,
    )
    .expect("schema");
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry()).expect("bindings");
    assert!(bindings.get("body").expect("body").index.is_none());
    assert!(bindings.get("tag").expect("tag").index.is_none());
}

#[test]
fn a4_20_hostile_input_is_bounded_and_typed() {
    let registry = registry();
    let standard = registry.get("standard").expect("standard");

    // Oversized single term -> typed TermTooLarge (no panic, no truncation).
    let huge_term = "a".repeat(5000);
    assert!(matches!(
        standard.collect_tokens(
            AnalyzerRole::Index,
            &[huge_term.as_str()],
            &limits(),
            &NeverCancel
        ),
        Err(AnalysisError::TermTooLarge { .. })
    ));

    // Oversized input value -> typed InputTooLarge.
    let huge_input = "a".repeat((1 << 20) + 1);
    assert!(matches!(
        standard.collect_tokens(
            AnalyzerRole::Index,
            &[huge_input.as_str()],
            &limits(),
            &NeverCancel
        ),
        Err(AnalysisError::InputTooLarge { .. })
    ));

    // Control characters and invisible scalars do not panic.
    let weird = "\u{0000}\u{200b}\u{feff}word";
    let tokens = standard
        .collect_tokens(AnalyzerRole::Index, &[weird], &limits(), &NeverCancel)
        .expect("hostile input");
    assert!(tokens.iter().all(|token| !token.term().is_empty()));
}

#[test]
fn a4_21_parallel_analysis_is_deterministic() {
    let values = ["The quick brown foxes", "running runners"];
    let expected = registry()
        .get("english")
        .expect("english")
        .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
        .expect("analysis");

    std::thread::scope(|scope| {
        for _ in 0..8 {
            let expected = &expected;
            scope.spawn(move || {
                let registry = registry();
                let actual = registry
                    .get("english")
                    .expect("english")
                    .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
                    .expect("analysis");
                assert_eq!(&actual, expected);
            });
        }
    });
}

#[test]
fn a4_22_contract_and_storage_modules_coexist() {
    // Existing contract + storage behaviour remains usable alongside analysis.
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "body",
            FieldType::Text,
            Cardinality::Single,
            FieldOptions::indexed_stored(),
        )],
        None,
    )
    .expect("schema");
    assert_eq!(schema.field_count(), 1);

    let directory = MemoryDirectory::new();
    let key = StorageKey::parse("segments/seg-1").expect("key");
    directory.atomic_write(&key, b"data").expect("write");
    assert!(directory.exists(&key).expect("exists"));
    let handle = directory.open_read(&key).expect("open");
    assert_eq!(handle.len(), 4);
    let mut buffer = [0u8; 4];
    assert_eq!(handle.read_at(0, &mut buffer).expect("read"), 4);
    assert_eq!(&buffer, b"data");
}

#[test]
fn i4_01_real_schema_binding_multi_value_and_term_preparation() {
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("english"),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_normalizer("keyword"),
        ],
        None,
    )
    .expect("schema");

    let registry = registry();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry).expect("bindings");
    assert!(bindings.get("body").expect("body").index.is_some());
    assert!(bindings.get("host").expect("host").index.is_some());

    let analyzer = registry.get("english").expect("english");
    let values = ["The runners ran", "running fast"];
    let tokens = analyzer
        .collect_tokens(AnalyzerRole::Index, &values, &limits(), &NeverCancel)
        .expect("analysis");

    // Stopword "The" leaves a hole; "runners"/"running" stem.
    let terms: Vec<&str> = tokens.iter().map(Token::term).collect();
    assert_eq!(terms, vec!["runner", "ran", "run", "fast"]);
    assert_eq!(tokens[0].position(), 1);
    assert_eq!(tokens[0].position_increment(), 2);
    assert_eq!(tokens[2].value_index(), 1);
    assert_eq!(tokens[2].position() - tokens[1].position(), 100);

    let prepared = prepare_term(analyzer, "running", &limits(), &NeverCancel).expect("term");
    assert_eq!(prepared.term(), "run");
    assert_eq!(prepared.metadata().analyzer_id, "english");
    assert_eq!(prepared.metadata().analyzer_version, "1.0.0");
}

#[test]
fn i4_03_incompatible_analyzer_version_fails_closed_through_public_api() {
    let registry = registry();
    assert!(matches!(
        registry.resolve_compatible("english", "9.9.9"),
        Err(AnalysisError::AnalyzerVersionMismatch { .. })
    ));

    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("not-registered"),
        ],
        None,
    )
    .expect("schema");
    assert!(matches!(
        SchemaAnalyzerBindings::resolve(&schema, &registry),
        Err(AnalysisError::UnknownAnalyzer { .. })
    ));
}

#[test]
fn i4_04_cancellation_and_resource_bounds_through_public_api() {
    let registry = registry();
    let standard = registry.get("standard").expect("standard");

    let flag = CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        standard.collect_tokens(AnalyzerRole::Index, &["anything"], &limits(), &flag),
        Err(AnalysisError::Cancelled)
    ));

    let under = AnalysisLimits::default()
        .with_max_input_bytes(2)
        .expect("lower");
    assert!(matches!(
        standard.collect_tokens(AnalyzerRole::Index, &["hello"], &under, &NeverCancel),
        Err(AnalysisError::InputTooLarge { .. })
    ));
}
