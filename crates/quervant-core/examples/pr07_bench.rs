//! PR 7 correctness-gated microbenchmark (not release qualification).
//!
//! Run with:
//!
//! ```text
//! cargo run --release -p quervant-core --example pr07_bench
//! ```
//!
//! This example is deliberately dependency-free. It builds a synthetic corpus
//! through the real writer/reader path, verifies query results against a naive
//! in-memory oracle, then reports p50/p95/p99 latency and throughput for term,
//! AND, OR, phrase, MatchAll/pure-negative and multi-segment queries. It also
//! compares concrete, enum and `dyn Trait` postings cursors at representative
//! sizes. It does not measure process RSS or allocations; PR 15 owns the full
//! comparative harness.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::{AnalyzerRegistry, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::Index;
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::storage::{Directory, MemoryDirectory};

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let index = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[index]
}

fn report(label: &str, mut samples: Vec<f64>, work_units: usize) {
    samples.sort_by(|left, right| left.total_cmp(right));
    let p50 = percentile(&samples, 0.50);
    let p95 = percentile(&samples, 0.95);
    let p99 = percentile(&samples, 0.99);
    let mean: f64 = samples.iter().sum::<f64>() / samples.len() as f64;
    let throughput = if mean > 0.0 {
        work_units as f64 / mean
    } else {
        0.0
    };
    println!(
        "{label:<28} n={:<4} p50={:>9.3}us p95={:>9.3}us p99={:>9.3}us throughput={:>12.1}/s",
        samples.len(),
        p50 * 1e6,
        p95 * 1e6,
        p99 * 1e6,
        throughput
    );
}

// ---------------------------------------------------------------------------
// Corpus and query benchmark
// ---------------------------------------------------------------------------

const VOCAB: usize = 64;
const DOCS: usize = 2_000;
const SEGMENTS: usize = 4;

fn word(index: usize) -> String {
    format!("w{index:03}")
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
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            ),
        ],
        None,
    )
    .expect("schema")
}

fn build_corpus() -> (Arc<dyn Directory>, Vec<Vec<String>>) {
    let mut state: u64 = 0x1234_5678_9abc_def0;
    let mut next = move || {
        state = state
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        state >> 33
    };
    let mut token_lists: Vec<Vec<String>> = Vec::with_capacity(DOCS);
    let mut batches: Vec<Vec<Document>> = Vec::with_capacity(SEGMENTS);
    let per_segment = DOCS / SEGMENTS;
    for segment in 0..SEGMENTS {
        let mut batch = Vec::with_capacity(per_segment);
        for offset in 0..per_segment {
            let index = segment * per_segment + offset;
            let mut tokens = Vec::with_capacity(8);
            for _ in 0..8 {
                tokens.push(word((next() as usize) % VOCAB));
            }
            let mut document = Document::new(DocumentKey::new(format!("d{index:05}")).unwrap());
            document
                .insert(
                    "title",
                    FieldValues::Single(FieldValue::Text(tokens.join(" "))),
                )
                .unwrap();
            document
                .insert(
                    "tag",
                    FieldValues::Multi(vec![
                        FieldValue::Keyword(word((next() as usize) % VOCAB)),
                        FieldValue::Keyword(word((next() as usize) % VOCAB)),
                    ]),
                )
                .unwrap();
            token_lists.push(tokens);
            batch.push(document);
        }
        batches.push(batch);
    }

    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(directory.clone(), schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    for batch in batches {
        for document in batch {
            writer.insert(document).unwrap();
        }
        writer.flush().unwrap();
    }
    writer.commit().unwrap();
    drop(writer);
    (directory, token_lists)
}

fn oracle_term(token_lists: &[Vec<String>], term: &str) -> BTreeSet<String> {
    token_lists
        .iter()
        .enumerate()
        .filter(|(_, tokens)| tokens.iter().any(|token| token == term))
        .map(|(index, _)| format!("d{index:05}"))
        .collect()
}

fn oracle_phrase(token_lists: &[Vec<String>], phrase: &[String]) -> BTreeSet<String> {
    token_lists
        .iter()
        .enumerate()
        .filter(|(_, tokens)| {
            tokens.len() >= phrase.len()
                && (0..=tokens.len() - phrase.len())
                    .any(|start| tokens[start..start + phrase.len()] == *phrase)
        })
        .map(|(index, _)| format!("d{index:05}"))
        .collect()
}

fn term(token: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(token.to_owned()),
    }
}

fn run_queries() {
    let (directory, token_lists) = build_corpus();
    let index = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let snapshot = index.snapshot();
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
    let searcher = LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
    let budgets = Budgets::new();
    let top_k = TopK::new(10).unwrap();

    let term_a = word(3);
    let term_b = word(17);
    let term_c = word(42);
    let phrase: Vec<String> = vec![word(7), word(11), word(29)];

    let term_a_set = oracle_term(&token_lists, &term_a);
    let term_b_set = oracle_term(&token_lists, &term_b);
    let term_c_set = oracle_term(&token_lists, &term_c);
    let and_set = term_a_set.intersection(&term_b_set).cloned().collect();
    let mut or_set = term_a_set.clone();
    or_set.extend(term_b_set.iter().cloned());
    or_set.extend(term_c_set.iter().cloned());
    let all_docs: BTreeSet<String> = (0..DOCS).map(|index| format!("d{index:05}")).collect();
    let negative_set = all_docs.difference(&term_a_set).cloned().collect();

    let cases: Vec<(&str, Query, BTreeSet<String>)> = vec![
        ("term", term(&term_a), term_a_set.clone()),
        (
            "and",
            Query::And(vec![term(&term_a), term(&term_b)]),
            and_set,
        ),
        (
            "or",
            Query::Or(vec![term(&term_a), term(&term_b), term(&term_c)]),
            or_set,
        ),
        (
            "phrase",
            Query::Phrase {
                field: "title".into(),
                terms: phrase.clone(),
            },
            oracle_phrase(&token_lists, &phrase),
        ),
        ("match_all", Query::MatchAll, all_docs),
        (
            "pure_negative",
            Query::Not(Box::new(term(&term_a))),
            negative_set,
        ),
    ];

    for (label, query, expected) in &cases {
        let actual: BTreeSet<String> = searcher
            .search(query, TopK::new(5_000).unwrap(), &budgets, &NeverCancel)
            .unwrap()
            .hits
            .into_iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect();
        assert_eq!(&actual, expected, "oracle mismatch for {label}");
    }

    for (label, query, _) in &cases {
        let rounds = 100;
        let mut samples = Vec::with_capacity(rounds);
        for _ in 0..rounds {
            let start = Instant::now();
            let response = searcher
                .search(query, top_k, &budgets, &NeverCancel)
                .unwrap();
            let _ = response.total_hits;
            samples.push(start.elapsed().as_secs_f64());
        }
        report(label, samples, 1);
    }
}

// ---------------------------------------------------------------------------
// Dispatch microbenchmark: concrete vs enum vs dyn postings cursors.
// ---------------------------------------------------------------------------

trait Cursor {
    fn next_doc(&mut self) -> Option<u32>;
}

#[derive(Clone)]
struct VecCursor {
    docs: Vec<u32>,
    position: usize,
}

impl VecCursor {
    fn new(docs: Vec<u32>) -> Self {
        Self { docs, position: 0 }
    }
}

impl Cursor for VecCursor {
    fn next_doc(&mut self) -> Option<u32> {
        let value = self.docs.get(self.position).copied();
        self.position += usize::from(value.is_some());
        value
    }
}

enum EnumCursor {
    Vec(VecCursor),
    Empty,
}

impl Cursor for EnumCursor {
    fn next_doc(&mut self) -> Option<u32> {
        match self {
            Self::Vec(cursor) => cursor.next_doc(),
            Self::Empty => None,
        }
    }
}

fn concrete_sum(cursor: &mut VecCursor) -> u64 {
    let mut total = 0u64;
    while let Some(doc) = cursor.next_doc() {
        total += u64::from(doc);
    }
    total
}

fn enum_sum(cursor: &mut EnumCursor) -> u64 {
    let mut total = 0u64;
    while let Some(doc) = cursor.next_doc() {
        total += u64::from(doc);
    }
    total
}

fn dyn_sum(cursor: &mut dyn Cursor) -> u64 {
    let mut total = 0u64;
    while let Some(doc) = cursor.next_doc() {
        total += u64::from(doc);
    }
    total
}

fn bench_dispatch() {
    const POSTINGS: u32 = 1_000_000;
    const ROUNDS: usize = 100;
    let docs: Vec<u32> = (0..POSTINGS).collect();
    let expected: u64 = (0..POSTINGS).map(u64::from).sum();
    // Exercise the empty enum arm so no variant is dead.
    assert_eq!(enum_sum(&mut EnumCursor::Empty), 0);

    let mut concrete = Vec::new();
    for _ in 0..ROUNDS {
        let mut cursor = VecCursor::new(docs.clone());
        let start = Instant::now();
        assert_eq!(concrete_sum(&mut cursor), expected);
        concrete.push(start.elapsed().as_secs_f64());
    }
    report("dispatch/concrete", concrete, POSTINGS as usize);

    let mut enum_times = Vec::new();
    for _ in 0..ROUNDS {
        let mut cursor = EnumCursor::Vec(VecCursor::new(docs.clone()));
        let start = Instant::now();
        assert_eq!(enum_sum(&mut cursor), expected);
        enum_times.push(start.elapsed().as_secs_f64());
    }
    report("dispatch/enum", enum_times, POSTINGS as usize);

    let mut dyn_times = Vec::new();
    for _ in 0..ROUNDS {
        let mut cursor = VecCursor::new(docs.clone());
        let start = Instant::now();
        assert_eq!(dyn_sum(&mut cursor), expected);
        dyn_times.push(start.elapsed().as_secs_f64());
    }
    report("dispatch/dyn", dyn_times, POSTINGS as usize);
}

fn main() {
    let build_start = Instant::now();
    run_queries();
    println!(
        "corpus build + query run wall time: {:.3}s",
        build_start.elapsed().as_secs_f64()
    );
    bench_dispatch();
}
