//! PR 8 diagnostic multi-term benchmark (not release qualification).
//!
//! Run with:
//!
//! ```text
//! cargo run --release -p quervant-core --example pr08_bench -- 10000
//! ```
//!
//! The argument is the vocabulary size (default 2000). This example builds a
//! synthetic identity-keyword corpus through the real writer/reader path and
//! measures per-query latency for selective/broad/no-match prefix, glob, regex
//! and fuzzy patterns plus `Term`/`Phrase` controls.
//!
//! **Disclosure:** the derived term FST is rebuilt per request (no cross-request
//! cache), so every latency below includes FST construction. Logical FST bytes and
//! work accounting are asserted by the PR 8 unit tests (T25/T26); this harness
//! does not measure process RSS and makes no cross-engine speedup claim. Broad
//! patterns that exceed a published budget fail closed and are reported as such.

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
use quervant_core::search::{LexicalSearcher, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, MemoryDirectory};

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let index = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[index]
}

fn report(label: &str, mut samples: Vec<f64>) {
    samples.sort_by(|left, right| left.total_cmp(right));
    let p50 = percentile(&samples, 0.50) * 1e3;
    let p95 = percentile(&samples, 0.95) * 1e3;
    let p99 = percentile(&samples, 0.99) * 1e3;
    println!("{label:<24} p50={p50:>8.3}ms p95={p95:>8.3}ms p99={p99:>8.3}ms");
}

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("english"),
        ],
        None,
    )
    .expect("schema")
}

fn document(index: usize) -> Document {
    // A deterministic synthetic vocabulary with shared prefixes.
    let term = format!("term{:07}", index * 7 % 10_000_000);
    let mut document = Document::new(DocumentKey::new(format!("d{index:08}")).unwrap());
    document
        .insert(
            "host",
            FieldValues::Single(FieldValue::Keyword(term.clone())),
        )
        .unwrap();
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(format!("rust search document {term}"))),
        )
        .unwrap();
    document
}

fn keywords(field: &str, value: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Keyword(value.to_owned()),
    }
}

fn queries() -> Vec<(&'static str, Query)> {
    vec![
        ("term-exact", keywords("host", "term0000000")),
        (
            "prefix-selective",
            Query::Prefix {
                field: "host".into(),
                prefix: "term00000".into(),
            },
        ),
        (
            "prefix-broad",
            Query::Prefix {
                field: "host".into(),
                prefix: "term".into(),
            },
        ),
        (
            "prefix-nomatch",
            Query::Prefix {
                field: "host".into(),
                prefix: "zzz".into(),
            },
        ),
        (
            "glob-selective",
            Query::Glob {
                field: "host".into(),
                pattern: "term00000*".into(),
            },
        ),
        (
            "glob-broad",
            Query::Glob {
                field: "host".into(),
                pattern: "term*".into(),
            },
        ),
        (
            "regex-selective",
            Query::Regex {
                field: "host".into(),
                pattern: "term00000.*".into(),
            },
        ),
        (
            "regex-broad",
            Query::Regex {
                field: "host".into(),
                pattern: "term.*".into(),
            },
        ),
        (
            "fuzzy-1",
            Query::Fuzzy {
                field: "host".into(),
                value: "term0000000".into(),
                max_edits: 1,
                transpositions: true,
            },
        ),
        (
            "phrase-control",
            Query::Phrase {
                field: "title".into(),
                terms: vec!["rust".into(), "search".into()],
            },
        ),
    ]
}

fn run(
    snapshot: &quervant_core::index::ReaderSnapshot,
    query: &Query,
) -> Result<SearchResponse, quervant_core::search::SearchError> {
    LexicalSearcher::new(
        snapshot,
        &schema(),
        &AnalyzerRegistry::builtin(),
        SearchLimits::default(),
    )
    .search(query, TopK::new(10).unwrap(), &Budgets::new(), &NeverCancel)
}

fn main() {
    let vocab: usize = std::env::args()
        .nth(1)
        .and_then(|value| value.parse().ok())
        .unwrap_or(2_000);
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let build_start = Instant::now();
    {
        let index = Index::create(
            Arc::clone(&directory),
            schema(),
            AnalyzerRegistry::builtin(),
        )
        .expect("create");
        let mut writer = index.writer().expect("writer");
        for start in (0..vocab).step_by(10_000) {
            for i in start..(start + 10_000).min(vocab) {
                writer.insert(document(i)).expect("insert");
            }
            writer.flush().expect("flush");
        }
        writer.commit().expect("commit");
    }
    let index =
        Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).expect("reopen");
    let snapshot = index.snapshot();
    println!(
        "vocabulary={vocab} segments={} index_build={:.2}ms",
        snapshot.segment_count(),
        build_start.elapsed().as_secs_f64() * 1e3
    );
    println!("{:<24} {:>10} {:>10}", "query", "total_hits", "result");
    const RUNS: usize = 12;
    for (label, query) in queries() {
        // One unmeasured warm-up (the FST is per request, so this is not cached
        // across runs; it only warms the allocator).
        let first = run(&snapshot, &query);
        match &first {
            Ok(response) => {
                let mut samples = Vec::with_capacity(RUNS);
                for _ in 0..RUNS {
                    let start = Instant::now();
                    let response = run(&snapshot, &query).expect("repeat");
                    samples.push(start.elapsed().as_secs_f64());
                    std::hint::black_box(response);
                }
                println!("{label:<24} {:>10} {:>10}", response.total_hits, "ok");
                report(label, samples);
            }
            Err(error) => {
                println!("{label:<24} {:>10} {:>10?}", "-", error);
            }
        }
    }
}
