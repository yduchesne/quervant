//! PR 9 merge/compaction benchmark.
//!
//! Measures explicit `IndexWriter::compact()` over a prebuilt committed
//! generation with half the logical keys tombstoned, plus whole-search latency
//! before and after compaction. The document count is configurable through
//! `QUERVANT_MERGE_BENCH_DOCS` (default `2000`); valid values are listed in the
//! PR 9 validation report.

use std::sync::Arc;

use criterion::{Criterion, Throughput, criterion_group, criterion_main};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, MutationRequest,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexWriter};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::storage::MemoryDirectory;

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .expect("schema")
}

fn doc(index: usize) -> Document {
    let key = DocumentKey::new(format!("doc-{index:08}")).unwrap();
    let mut document = Document::new(key);
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(format!(
                "term{} shared lexical payload",
                index % 97
            ))),
        )
        .unwrap();
    document
}

/// Build a committed index with `doc_count` documents in 1 000-doc segments,
/// then tombstone every other key.
fn build(doc_count: usize) -> (Arc<dyn quervant_core::storage::Directory>, Index) {
    let directory = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory) as Arc<dyn quervant_core::storage::Directory>,
        schema(),
        quervant_core::analysis::AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer: IndexWriter = index.writer().unwrap();
    for i in 0..doc_count {
        writer.insert(doc(i)).unwrap();
        if i % 1_000 == 999 {
            writer.flush().unwrap();
        }
    }
    if writer.pending_documents() > 0 {
        writer.flush().unwrap();
    }
    for i in (0..doc_count).step_by(2) {
        writer
            .apply(MutationRequest::delete(
                DocumentKey::new(format!("doc-{i:08}")).unwrap(),
            ))
            .unwrap();
    }
    writer.commit().unwrap();
    (directory, index)
}

fn bench_merge(c: &mut Criterion) {
    let doc_counts: Vec<usize> = std::env::var("QUERVANT_MERGE_BENCH_DOCS")
        .unwrap_or_else(|_| "2000".to_owned())
        .split(',')
        .filter_map(|value| value.trim().parse().ok())
        .collect();
    let mut group = c.benchmark_group("pr09_merge");
    for doc_count in doc_counts {
        let (_, index) = build(doc_count);
        group.throughput(Throughput::Elements(doc_count as u64));
        group.bench_function(format!("compact_{doc_count}"), |b| {
            b.iter_batched(
                || index.writer().unwrap(),
                |mut writer| {
                    let outcome = writer.compact().unwrap();
                    std::hint::black_box(outcome.documents);
                },
                criterion::BatchSize::PerIteration,
            );
        });
    }
    group.finish();
}

fn bench_search_before_after(c: &mut Criterion) {
    let doc_count: usize = std::env::var("QUERVANT_MERGE_BENCH_DOCS")
        .ok()
        .and_then(|value| value.split(',').next().and_then(|v| v.trim().parse().ok()))
        .unwrap_or(2000);
    let (_, index) = build(doc_count);
    let schema = schema();
    let registry = quervant_core::analysis::AnalyzerRegistry::builtin();
    let query = Query::Term {
        field: "title".into(),
        value: FieldValue::Text("shared".into()),
    };
    let mut writer = index.writer().unwrap();
    let mut group = c.benchmark_group("pr09_search");
    group.throughput(Throughput::Elements(1));
    {
        let snapshot = writer.reader();
        let searcher = LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        group.bench_function("before_compact".to_owned(), |b| {
            b.iter(|| {
                let response = searcher
                    .search(
                        &query,
                        TopK::new(20).unwrap(),
                        &Budgets::new(),
                        &NeverCancel,
                    )
                    .unwrap();
                std::hint::black_box(response.total_hits);
            });
        });
    }
    writer.compact().unwrap();
    {
        let snapshot = writer.reader();
        let searcher = LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        group.bench_function("after_compact".to_owned(), |b| {
            b.iter(|| {
                let response = searcher
                    .search(
                        &query,
                        TopK::new(20).unwrap(),
                        &Budgets::new(),
                        &NeverCancel,
                    )
                    .unwrap();
                std::hint::black_box(response.total_hits);
            });
        });
    }
    group.finish();
}

criterion_group!(benches, bench_merge, bench_search_before_after);
criterion_main!(benches);
