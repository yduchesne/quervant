//! PR 8 domain-aware fuzzy tests (T38–T41).
//!
//! PR 8 does not add a `DomainFuzzy` API. Domain matching reuses the same bounded
//! `Fuzzy` operator over an indexed **canonical** domain keyword field produced by
//! the PR 4 `analyze_domain` IDNA/UTS #46 analysis. Original document keys are
//! preserved and no confusable-skeleton or PSL/TLD weighting is applied.

mod common;

use std::sync::Arc;

use common::{pr08_commit_batches, pr08_registry, pr08_schema};
use quervant_core::analysis::{AnalysisLimits, DomainConfig, NeverCancel, analyze_domain};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, MemoryDirectory};

fn canonical(input: &str) -> String {
    analyze_domain(
        input,
        DomainConfig::default(),
        &AnalysisLimits::default(),
        &NeverCancel,
    )
    .expect("domain analysis")
    .canonical_ascii()
    .to_owned()
}

fn domain_document(key: &str, canonical_ascii: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
    document
        .insert(
            "domain_canonical",
            FieldValues::Single(FieldValue::Keyword(canonical_ascii.to_owned())),
        )
        .expect("domain_canonical");
    document
}

fn build(docs: Vec<Document>) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    pr08_commit_batches(directory.clone(), vec![docs]);
    Index::open_existing(directory, pr08_schema(), pr08_registry()).expect("reopen")
}

fn search(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    LexicalSearcher::new(
        snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(
        query,
        TopK::new(100).expect("topk"),
        &Budgets::new(),
        &NeverCancel,
    )
    .expect("search")
}

fn keys(response: &SearchResponse) -> Vec<String> {
    let mut found: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    found.sort();
    found
}

fn fuzzy(value: &str, max_edits: u8, transpositions: bool) -> Query {
    Query::Fuzzy {
        field: "domain_canonical".into(),
        value: value.to_owned(),
        max_edits,
        transpositions,
    }
}

fn schema_has_domain_field() -> bool {
    let schema = pr08_schema();
    schema.get("domain_canonical").is_some()
}

// T38 — canonical IDNA/case normalization; original keys preserved.
#[test]
fn p8_t38_domain_canonical() {
    assert!(schema_has_domain_field());
    let unicode = canonical("BÜCHER.example");
    let ascii = canonical("xn--bcher-kva.example");
    assert_eq!(
        unicode, ascii,
        "IDNA canonicalization is case/Unicode stable"
    );
    let index = build(vec![
        domain_document("bücher.example", &unicode),
        domain_document("xn--bcher-kva.example", &ascii),
    ]);
    let snapshot = index.snapshot();
    let response = search(
        &snapshot,
        &Query::Term {
            field: "domain_canonical".into(),
            value: FieldValue::Keyword(ascii.clone()),
        },
    );
    assert_eq!(
        keys(&response),
        ["bücher.example", "xn--bcher-kva.example"],
        "both source spellings index to one canonical identity"
    );
    // Invalid domains are rejected by the PR 4 analysis, never silently matched.
    assert!(
        analyze_domain(
            "bad domain",
            DomainConfig::default(),
            &AnalysisLimits::default(),
            &NeverCancel
        )
        .is_err()
    );
}

// T39 — a one-scalar typo / adjacent transposition is distance one under OSA.
#[test]
fn p8_t39_domain_typo_transposition() {
    let index = build(vec![domain_document("example.com", "example.com")]);
    let snapshot = index.snapshot();
    // `exmaple.com` is one adjacent transposition of `example.com`.
    assert_eq!(
        keys(&search(&snapshot, &fuzzy("exmaple.com", 1, true))),
        ["example.com"]
    );
    assert!(
        keys(&search(&snapshot, &fuzzy("exmaple.com", 1, false))).is_empty(),
        "plain Levenshtein needs two edits for a transposition"
    );
    // A substitution typo is distance one under both distance definitions.
    assert_eq!(
        keys(&search(&snapshot, &fuzzy("exampld.com", 1, false))),
        ["example.com"]
    );
}

// T40 — a TLD change is compared by raw edit distance, with no TLD weighting.
#[test]
fn p8_t40_domain_tld_raw_distance() {
    let index = build(vec![domain_document("example.com", "example.com")]);
    let snapshot = index.snapshot();
    // `com` -> `net` is three substitutions, so it is out of a two-edit budget.
    assert!(keys(&search(&snapshot, &fuzzy("example.net", 2, true))).is_empty());
    // A one-scalar TLD deletion is within budget and matches by raw distance.
    assert_eq!(
        keys(&search(&snapshot, &fuzzy("example.co", 1, true))),
        ["example.com"]
    );
    // A dropped label is four deletions away.
    assert!(keys(&search(&snapshot, &fuzzy("www.example.com", 2, true))).is_empty());
}

// T41 — no implicit confusable-skeleton equivalence or weighting.
#[test]
fn p8_t41_domain_identity_preserved() {
    // U+0430 CYRILLIC SMALL LETTER A collides visually with Latin `a`.
    let spoof = canonical("аpple.com");
    let genuine = canonical("apple.com");
    assert_ne!(spoof, genuine, "canonical identities stay distinct");
    let index = build(vec![
        domain_document("аpple.com", &spoof),
        domain_document("apple.com", &genuine),
    ]);
    let snapshot = index.snapshot();
    // Searching the genuine identity matches only the genuine document.
    assert_eq!(
        keys(&search(
            &snapshot,
            &Query::Term {
                field: "domain_canonical".into(),
                value: FieldValue::Keyword(genuine.clone()),
            }
        )),
        ["apple.com"]
    );
    // The confusable does not fuzzy-match the genuine identity at distance 2.
    assert!(keys(&search(&snapshot, &fuzzy(&genuine, 2, true))).contains(&"apple.com".to_owned()));
    assert!(!keys(&search(&snapshot, &fuzzy(&genuine, 2, true))).contains(&"аpple.com".to_owned()));
    // A schema type check: the domain field is a lexical keyword, not a special type.
    let schema: &Schema = &pr08_schema();
    let definition: &FieldDefinition = schema.get("domain_canonical").expect("field");
    assert_eq!(definition.field_type, FieldType::Keyword);
}
