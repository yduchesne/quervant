//! Deterministic, correctness-gated benchmark fixtures for PR 7 Amendment 04.
//!
//! Everything here is **benchmark-only** code. It uses only the public
//! `quervant-core` writer/reader/search APIs and never changes production
//! behavior. Dataset generation, indexing, commit, snapshot opening and expected
//! result computation all happen before any timed region.

#![allow(dead_code)]

use std::collections::BTreeSet;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::storage::{Directory, MemoryDirectory};
use sha2::{Digest, Sha256};

use criterion::BenchmarkGroup;
use criterion::measurement::WallTime;
use std::time::Duration;

/// Fixed fixture seed (PR 7 Amendment 04).
pub const SEED: u64 = 0xA404_2026_0000_0001;
/// Versioned fixture identifier used by report metadata.
pub const FIXTURE_VERSION: &str = "pr07_amendment04_v1";
/// Tokens per document for the primary field.
pub const TOKENS_PER_DOC: usize = 8;
/// Background vocabulary size.
pub const VOCAB: u64 = 512;

pub const RARE_SENTINEL: &str = "rare_sentinel_zzz";
pub const ABSENT_SENTINEL: &str = "absent_sentinel_zzz";
pub const MEDIUM_TERM: &str = "mtoken";
pub const COMMON_TERM: &str = "ctoken";
pub const PHRASE_TOKENS: [&str; 3] = ["alpha", "beta", "gamma"];
pub const REPEATED_TOKEN: &str = "reptok";

/// One document's key and analyzed (whitespace) tokens.
#[derive(Clone)]
pub struct DocTokens {
    pub key: String,
    pub tokens: Vec<String>,
}

/// A built, committed, preopened benchmark fixture.
pub struct Fixture {
    pub schema: Schema,
    pub registry: AnalyzerRegistry,
    pub directory: Arc<dyn Directory>,
    pub snapshot: Arc<ReaderSnapshot>,
    pub docs: Vec<DocTokens>,
    pub doc_count: usize,
    pub segments: usize,
    pub seed: u64,
}

/// SplitMix64 for deterministic token selection from `(seed, doc, slot)`.
fn splitmix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^ (x >> 31)
}

fn token_for(seed: u64, doc: usize, slot: usize) -> String {
    let mixed = splitmix64(seed ^ (doc as u64).wrapping_mul(0x0001_0000_0001) ^ (slot as u64));
    format!("w{:04}", mixed % VOCAB)
}

/// Generate the deterministic token stream for one document.
fn tokens_for(seed: u64, doc: usize) -> Vec<String> {
    let mut tokens: Vec<String> = (0..TOKENS_PER_DOC)
        .map(|slot| token_for(seed, doc, slot))
        .collect();
    // Disjoint special-token slots keep expected counts exact and recomputable.
    if doc % 100 == 0 {
        tokens[0] = MEDIUM_TERM.to_owned();
    }
    if doc % 2 == 0 {
        tokens[1] = COMMON_TERM.to_owned();
    }
    if doc == 0 {
        tokens[2] = RARE_SENTINEL.to_owned();
    }
    if doc % 250 == 0 {
        tokens[3] = PHRASE_TOKENS[0].to_owned();
        tokens[4] = PHRASE_TOKENS[1].to_owned();
        tokens[5] = PHRASE_TOKENS[2].to_owned();
    }
    if doc % 125 == 0 {
        tokens[6] = REPEATED_TOKEN.to_owned();
        tokens[7] = REPEATED_TOKEN.to_owned();
    }
    tokens
}

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("whitespace"),
        ],
        None,
    )
    .expect("benchmark schema")
}

fn doc(key: &str, tokens: &[String]) -> Document {
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(tokens.join(" "))),
        )
        .expect("title");
    document
}

/// Generate the deterministic token ledger for `doc_count` documents without
/// building an index. This is the same token source used by [`build`], exposed so
/// the metadata emitter can compute oracle counts and digests independently of a
/// committed index.
pub fn generate_docs(seed: u64, doc_count: usize) -> Vec<DocTokens> {
    (0..doc_count)
        .map(|index| DocTokens {
            key: format!("d{index:08}"),
            tokens: tokens_for(seed, index),
        })
        .collect()
}

/// Build a committed fixture with `doc_count` documents partitioned into
/// `segments` immutable segments using the fixed Amendment 04 seed.
pub fn build(doc_count: usize, segments: usize) -> Fixture {
    build_with_seed(doc_count, segments, SEED)
}

/// Build a committed fixture with an explicit seed (used for digest-sensitivity
/// tests). Production/benchmark use calls [`build`].
pub fn build_with_seed(doc_count: usize, segments: usize, seed: u64) -> Fixture {
    assert!(segments >= 1, "segments must be >= 1");
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());

    let docs = generate_docs(seed, doc_count);
    let mut batches: Vec<Vec<Document>> = vec![Vec::new(); segments];
    for (index, doc_tokens) in docs.iter().enumerate() {
        let batch = index * segments / doc_count.max(1);
        batches[batch.min(segments - 1)].push(doc(&doc_tokens.key, &doc_tokens.tokens));
    }

    let limits = IndexLimits::new()
        .with_max_pending_docs(doc_count as u64 + 16)
        .with_max_pending_bytes(512 * 1024 * 1024)
        .with_max_segments_per_commit(64)
        .with_max_snapshot_bytes(1024 * 1024 * 1024);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema.clone(),
        registry.clone(),
        limits,
    )
    .expect("create index");
    let mut writer = index.writer().expect("writer");
    for batch in batches {
        for document in batch {
            writer.insert(document).expect("insert");
        }
        writer.flush().expect("flush");
    }
    writer.commit().expect("commit");
    drop(writer);

    let reopened = Index::open_existing(Arc::clone(&directory), schema.clone(), registry.clone())
        .expect("reopen");
    let snapshot = reopened.snapshot();
    Fixture {
        schema,
        registry,
        directory,
        snapshot,
        docs,
        doc_count,
        segments,
        seed,
    }
}

impl Fixture {
    pub fn field_id(&self) -> u32 {
        let reader = self.snapshot.open_segment_reader(0).expect("segment 0");
        reader
            .reader()
            .schema()
            .field_id("title")
            .expect("title field id")
    }

    pub fn searcher(&self) -> LexicalSearcher<'_> {
        LexicalSearcher::new(
            &self.snapshot,
            &self.schema,
            &self.registry,
            SearchLimits::default(),
        )
    }

    /// Canonical SHA-256 over keys, tokens, segment boundaries and query IDs.
    pub fn dataset_sha256(&self) -> String {
        digest_for(&self.docs, self.doc_count, self.segments, self.seed)
    }
}

/// Canonical dataset digest for a token ledger and partitioning. Independent of
/// whether an index was built, so the metadata emitter and the benchmark fixture
/// agree.
pub fn digest_for(docs: &[DocTokens], doc_count: usize, segments: usize, seed: u64) -> String {
    let mut hasher = Sha256::new();
    hasher.update(seed.to_be_bytes());
    hasher.update((doc_count as u64).to_be_bytes());
    hasher.update((segments as u64).to_be_bytes());
    let mut boundaries = Vec::new();
    for segment in 1..segments {
        boundaries.push(segment * doc_count / segments);
    }
    hasher.update((boundaries.len() as u64).to_be_bytes());
    for boundary in &boundaries {
        hasher.update((*boundary as u64).to_be_bytes());
    }
    for doc in docs {
        hasher.update((doc.key.len() as u64).to_be_bytes());
        hasher.update(doc.key.as_bytes());
        hasher.update((doc.tokens.len() as u64).to_be_bytes());
        for token in &doc.tokens {
            hasher.update((token.len() as u64).to_be_bytes());
            hasher.update(token.as_bytes());
        }
    }
    for id in query_ids() {
        hasher.update(id.as_bytes());
    }
    use std::fmt::Write as _;
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for byte in digest.iter() {
        write!(out, "{byte:02x}").expect("writing to String cannot fail");
    }
    out
}

/// The stable query IDs used by the fixture and report schema.
pub fn query_ids() -> &'static [&'static str] {
    &[
        "term-rare",
        "term-medium",
        "term-common",
        "term-absent",
        "and-common-medium",
        "or-common-rare",
        "phrase-present",
        "phrase-absent",
        "phrase-repeated",
        "match-all",
        "pure-negative",
    ]
}

/// Independent oracle for the benchmark query subset. It never calls the
/// production executor, postings codecs or phrase verifier.
pub fn oracle(query: &Query, docs: &[DocTokens]) -> BTreeSet<String> {
    match query {
        Query::MatchAll => docs.iter().map(|doc| doc.key.clone()).collect(),
        Query::Term { value, .. } => {
            let text = match value {
                FieldValue::Text(text) | FieldValue::Keyword(text) => text.as_str(),
                other => panic!("unsupported oracle term value {other:?}"),
            };
            docs.iter()
                .filter(|doc| doc.tokens.iter().any(|token| token == text))
                .map(|doc| doc.key.clone())
                .collect()
        }
        Query::Phrase { terms, .. } => docs
            .iter()
            .filter(|doc| phrase_matches(&doc.tokens, terms))
            .map(|doc| doc.key.clone())
            .collect(),
        Query::And(children) => {
            let mut iter = children.iter();
            let Some(first) = iter.next() else {
                return BTreeSet::new();
            };
            let mut set = oracle(first, docs);
            for child in iter {
                let next = oracle(child, docs);
                set = set.intersection(&next).cloned().collect();
            }
            set
        }
        Query::Or(children) => {
            let mut set = BTreeSet::new();
            for child in children {
                set.extend(oracle(child, docs));
            }
            set
        }
        Query::Not(inner) => {
            let universe: BTreeSet<String> = docs.iter().map(|doc| doc.key.clone()).collect();
            universe.difference(&oracle(inner, docs)).cloned().collect()
        }
        other => panic!("unsupported oracle query {other:?}"),
    }
}

fn phrase_matches(tokens: &[String], phrase_terms: &[String]) -> bool {
    // Query phrase components are analyzed exactly (whitespace) by joining with a
    // single boundary; single-token components cannot change the token sequence.
    let phrase: Vec<String> = phrase_terms
        .iter()
        .flat_map(|term| term.split_whitespace().map(str::to_owned))
        .collect();
    if phrase.is_empty() || phrase.len() > tokens.len() {
        return false;
    }
    (0..=tokens.len() - phrase.len()).any(|start| tokens[start..start + phrase.len()] == phrase[..])
}

/// One named, oracle-checked benchmark query.
pub struct Case {
    pub id: &'static str,
    pub query: Query,
    pub expected: BTreeSet<String>,
}

fn term(text: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(text.to_owned()),
    }
}

fn phrase(terms: &[&str]) -> Query {
    Query::Phrase {
        field: "title".into(),
        terms: terms.iter().map(|term| (*term).to_owned()).collect(),
    }
}

/// Build every standard case from the deterministic token ledger, computing
/// expected sets with the independent oracle. This does not require an index.
pub fn cases_for(docs: &[DocTokens]) -> Vec<Case> {
    let specs: Vec<(&'static str, Query)> = vec![
        ("term-rare", term(RARE_SENTINEL)),
        ("term-medium", term(MEDIUM_TERM)),
        ("term-common", term(COMMON_TERM)),
        ("term-absent", term(ABSENT_SENTINEL)),
        (
            "and-common-medium",
            Query::And(vec![term(COMMON_TERM), term(MEDIUM_TERM)]),
        ),
        (
            "or-common-rare",
            Query::Or(vec![term(COMMON_TERM), term(RARE_SENTINEL)]),
        ),
        ("phrase-present", phrase(&PHRASE_TOKENS)),
        ("phrase-absent", phrase(&["absent_a", "absent_b"])),
        ("phrase-repeated", phrase(&[REPEATED_TOKEN, REPEATED_TOKEN])),
        ("match-all", Query::MatchAll),
        ("pure-negative", Query::Not(Box::new(term(RARE_SENTINEL)))),
    ];
    specs
        .into_iter()
        .map(|(id, query)| {
            let expected = oracle(&query, docs);
            Case {
                id,
                query,
                expected,
            }
        })
        .collect()
}

/// Build every standard case from a committed fixture.
pub fn cases(fixture: &Fixture) -> Vec<Case> {
    cases_for(&fixture.docs)
}

/// Assert the production executor's hit set (with a large top-K) equals the oracle.
pub fn assert_case(fixture: &Fixture, case: &Case) {
    let searcher = fixture.searcher();
    let response = searcher
        .search(
            &case.query,
            TopK::new(fixture.doc_count.max(1)).expect("topk"),
            &Budgets::new(),
            &NeverCancel,
        )
        .unwrap_or_else(|error| panic!("search {} failed: {error}", case.id));
    let actual: BTreeSet<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    assert_eq!(
        actual,
        case.expected,
        "oracle mismatch for {} (total_hits={} expected={})",
        case.id,
        response.total_hits,
        case.expected.len()
    );
    assert_eq!(
        response.total_hits as usize,
        case.expected.len(),
        "exact total_hits mismatch for {}",
        case.id
    );
    for hit in &response.hits {
        assert!(
            hit.score.is_finite() && hit.score >= 0.0,
            "invalid score for {}",
            case.id
        );
    }
}

/// Verify every standard case against the oracle before timing.
pub fn assert_all_cases(fixture: &Fixture) {
    for case in cases(fixture) {
        assert_case(fixture, &case);
    }
}

/// Configure a Criterion group with warmup, measurement time and sample size
/// scaled by corpus size. Large corpora get longer measurements but no fewer
/// than 20 samples.
pub fn configure_group(group: &mut BenchmarkGroup<'_, WallTime>, doc_count: usize) {
    let (warm_up, measurement, samples) = match doc_count {
        0..=2_000 => (Duration::from_secs(2), Duration::from_secs(3), 30),
        2_001..=10_000 => (Duration::from_secs(2), Duration::from_secs(4), 30),
        _ => (Duration::from_secs(2), Duration::from_secs(6), 20),
    };
    group
        .warm_up_time(warm_up)
        .measurement_time(measurement)
        .sample_size(samples);
}

/// Deterministic metadata for one benchmark workload key.
///
/// `actual_hits` is the independent-oracle match count for search/phrase rows
/// (`hit_count_applicable = true`). For arithmetic/dictionary/postings rows it is
/// `None` and must never be replaced with a fabricated zero.
#[derive(Clone, Debug)]
pub struct WorkloadMeta {
    pub workload_key: String,
    pub query_id: String,
    pub operation: &'static str,
    pub doc_count: usize,
    pub segments: usize,
    pub top_k: usize,
    pub actual_hits: Option<usize>,
    pub selectivity_ratio: Option<f64>,
    pub hit_count_applicable: bool,
    pub dataset_sha256: String,
    pub posting_doc_count: Option<u64>,
    pub dictionary_doc_freq: Option<u64>,
}

#[allow(clippy::too_many_arguments)]
fn hit_meta(
    workload_key: String,
    query_id: &str,
    operation: &'static str,
    doc_count: usize,
    segments: usize,
    top_k: usize,
    hits: usize,
    digest: &str,
) -> WorkloadMeta {
    WorkloadMeta {
        workload_key,
        query_id: query_id.to_owned(),
        operation,
        doc_count,
        segments,
        top_k,
        actual_hits: Some(hits),
        selectivity_ratio: if doc_count > 0 {
            Some(hits as f64 / doc_count as f64)
        } else {
            None
        },
        hit_count_applicable: true,
        dataset_sha256: digest.to_owned(),
        posting_doc_count: None,
        dictionary_doc_freq: None,
    }
}

fn non_hit_meta(
    workload_key: String,
    query_id: &str,
    operation: &'static str,
    doc_count: usize,
    segments: usize,
    digest: &str,
) -> WorkloadMeta {
    WorkloadMeta {
        workload_key,
        query_id: query_id.to_owned(),
        operation,
        doc_count,
        segments,
        top_k: 0,
        actual_hits: None,
        selectivity_ratio: None,
        hit_count_applicable: false,
        dataset_sha256: digest.to_owned(),
        posting_doc_count: None,
        dictionary_doc_freq: None,
    }
}

/// Enumerate every workload key measured by the five Criterion targets, with
/// independently computed oracle hit counts and digests. This is the source of
/// truth joined by `build-pr07-report.py`; nothing here parses benchmark output.
pub fn all_workload_metadata() -> Vec<WorkloadMeta> {
    let sizes = [2_000usize, 10_000, 100_000];
    let mut records = Vec::new();

    // Per-size token ledgers and oracle cases (4 segments; digests vary by size).
    let mut by_size = Vec::new();
    for &doc_count in &sizes {
        let docs = generate_docs(SEED, doc_count);
        let digest = digest_for(&docs, doc_count, 4, SEED);
        let cases = cases_for(&docs);
        by_size.push((doc_count, docs, digest, cases));
    }
    let find = |doc_count: usize, id: &str| -> usize {
        by_size
            .iter()
            .find(|(n, _, _, _)| *n == doc_count)
            .expect("size")
            .3
            .iter()
            .find(|case| case.id == id)
            .expect("case")
            .expected
            .len()
    };

    // B01 — BM25 reference-arithmetic control.
    records.push(non_hit_meta(
        "pr07_bm25_reference_control/bm25_equation/fixed_inputs".to_owned(),
        "bm25-control",
        "bm25-control",
        0,
        0,
        &digest_for(&[], 0, 0, SEED),
    ));

    // B02 — all search cases at 2K/4seg and the top-K-100 case.
    for case in &by_size[0].3 {
        records.push(hit_meta(
            format!("pr07_search_2000_4seg/{}/k10", case.id),
            case.id,
            "search",
            2_000,
            4,
            10,
            case.expected.len(),
            &by_size[0].2,
        ));
    }
    records.push(hit_meta(
        "pr07_search_2000_4seg_topk100/term-common/k100".to_owned(),
        "term-common",
        "search",
        2_000,
        4,
        100,
        find(2_000, "term-common"),
        &by_size[0].2,
    ));

    // B02 scaling — rare/common at 2K/10K/100K.
    for (doc_count, _, digest, _) in &by_size {
        for id in ["term-rare", "term-common"] {
            records.push(hit_meta(
                format!("pr07_search_scaling_{doc_count}/{id}/k10"),
                id,
                "search",
                *doc_count,
                4,
                10,
                find(*doc_count, id),
                digest,
            ));
        }
    }

    // B05 — phrase end-to-end at 2K/10K/4seg.
    for doc_count in [2_000usize, 10_000] {
        let digest = by_size
            .iter()
            .find(|(n, _, _, _)| *n == doc_count)
            .expect("size")
            .2
            .clone();
        for id in ["phrase-present", "phrase-absent", "phrase-repeated"] {
            records.push(hit_meta(
                format!("pr07_phrase_{doc_count}_4seg/{id}/k10"),
                id,
                "phrase",
                doc_count,
                4,
                10,
                find(doc_count, id),
                &digest,
            ));
        }
    }

    // B03/B04 — dictionary and postings use single-segment fixtures; the digest
    // differs from the 4-segment groups.
    for &doc_count in &sizes {
        let docs = &by_size
            .iter()
            .find(|(n, _, _, _)| *n == doc_count)
            .expect("size")
            .1;
        let digest = digest_for(docs, doc_count, 1, SEED);
        let df = docs
            .iter()
            .filter(|doc| doc.tokens.iter().any(|token| token == COMMON_TERM))
            .count() as u64;
        for (lookup, term, freq) in [
            ("present", COMMON_TERM, Some(df)),
            ("absent", ABSENT_SENTINEL, None),
        ] {
            let mut meta = non_hit_meta(
                format!("pr07_dictionary_{doc_count}/dictionary_lookup_{lookup}/{term}"),
                &format!("dictionary-{lookup}"),
                "dictionary",
                doc_count,
                1,
                &digest,
            );
            meta.dictionary_doc_freq = freq;
            records.push(meta);
        }
        let mut meta = non_hit_meta(
            format!("pr07_postings_{doc_count}/cursor_open_plus_decode/ctoken"),
            "postings-ctoken",
            "postings",
            doc_count,
            1,
            &digest,
        );
        meta.posting_doc_count = Some(df);
        records.push(meta);
    }

    records
}
