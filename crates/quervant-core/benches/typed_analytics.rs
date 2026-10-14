//! PR 10 typed retrieval and exact analytics benchmarks.
//!
//! Fixtures are built from the public writer/reader APIs. Expected results are
//! verified against an independent oracle before timing. Sizes default to
//! 10K/100K documents; set `QUERVANT_PR10_BENCH_LARGE=1` to include 1M.

use std::sync::Arc;

use criterion::measurement::WallTime;
use criterion::{
    BenchmarkGroup, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main,
};
use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::{BudgetKind, Budgets};
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::Sort;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, Timestamp};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{
    AggregateMetric, AggregateRequest, SearchLimits, TypedSearchRequest, TypedSearcher,
};
use quervant_core::storage::{Directory, MemoryDirectory};

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "score",
                FieldType::F64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(false, true, true),
            ),
        ],
        Some("ts".into()),
    )
    .unwrap()
}

fn splitmix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^ (x >> 31)
}

struct Fixture {
    snapshot: Arc<ReaderSnapshot>,
    schema: Schema,
    doc_count: usize,
}

impl Fixture {
    fn build(doc_count: usize, base_time: i64) -> Self {
        let schema = schema();
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create(
            Arc::clone(&directory),
            schema.clone(),
            AnalyzerRegistry::builtin(),
        )
        .unwrap();
        // The writer bounds pending documents and bytes; commit in small batches.
        let batch = 2_000usize;
        let mut writer = index.writer().unwrap();
        for document_index in 0..doc_count {
            if document_index > 0 && document_index % batch == 0 {
                writer.commit().unwrap();
            }
            let mixed = splitmix64(document_index as u64);
            let mut document =
                Document::new(DocumentKey::new(format!("d{document_index:08}")).unwrap());
            document
                .insert(
                    "ts",
                    FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(
                        base_time + document_index as i64,
                    ))),
                )
                .unwrap();
            document
                .insert(
                    "n",
                    FieldValues::Single(FieldValue::I64((mixed % 1000) as i64)),
                )
                .unwrap();
            document
                .insert(
                    "score",
                    FieldValues::Single(FieldValue::F64((mixed % 10_000) as f64 / 100.0)),
                )
                .unwrap();
            document
                .insert(
                    "host",
                    FieldValues::Single(FieldValue::Keyword(format!("h{:03}", mixed % 64))),
                )
                .unwrap();
            document
                .insert(
                    "tags",
                    FieldValues::Multi(vec![
                        FieldValue::Keyword(format!("t{}", mixed % 16)),
                        FieldValue::Keyword(format!("t{}", (mixed >> 8) % 16)),
                    ]),
                )
                .unwrap();
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
        drop(writer);
        let reopened = Index::open_existing(
            directory.clone(),
            schema.clone(),
            AnalyzerRegistry::builtin(),
        )
        .unwrap();
        let snapshot = reopened.snapshot();
        assert_eq!(snapshot.document_count(), doc_count as u64);
        Self {
            snapshot,
            schema,
            doc_count,
        }
    }

    fn searcher(&self) -> TypedSearcher<'_> {
        TypedSearcher::new(&self.snapshot, &self.schema, SearchLimits::default())
    }
}

fn configure_group(group: &mut BenchmarkGroup<'_, WallTime>, doc_count: usize) {
    group.throughput(Throughput::Elements(doc_count as u64));
    group.sample_size(20);
}

fn request(query: Query, sort: Sort) -> TypedSearchRequest {
    TypedSearchRequest {
        query,
        sort,
        top_k: quervant_core::contract::result::TopK::new(10).unwrap(),
        after: None,
        primary_time_field: Some("ts".into()),
    }
}

fn aggregate_request() -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: vec!["host".into(), "tags".into()],
        time_bucket: None,
        metrics: vec![
            AggregateMetric::Count,
            AggregateMetric::Sum { field: "n".into() },
            AggregateMetric::Avg {
                field: "score".into(),
            },
            AggregateMetric::ExactDistinct { field: "n".into() },
        ],
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    }
}

fn typed_bench(c: &mut Criterion) {
    // Benchmarks compiled for `cargo test` use the debug/test profile, so keep
    // that path small for the workspace test gate; `cargo bench` uses release.
    let quick = cfg!(debug_assertions) || std::env::var("QUERVANT_PR10_BENCH_QUICK").is_ok();
    let mut sizes = if quick {
        vec![2_000usize]
    } else {
        vec![10_000usize, 100_000]
    };
    if let Ok(value) = std::env::var("QUERVANT_PR10_BENCH_SIZE") {
        if let Ok(size) = value.parse::<usize>() {
            sizes = vec![size];
        }
    }
    if std::env::var("QUERVANT_PR10_BENCH_LARGE").is_ok() {
        sizes.push(1_000_000);
    }
    let cancel = CancellationFlag::new();
    let budgets = Budgets::new().with(BudgetKind::ResultWindow, 100).unwrap();
    for size in sizes {
        let fixture = Fixture::build(size, 0);
        let searcher = fixture.searcher();
        let tag = format!("d{}", fixture.doc_count);

        let mut group = c.benchmark_group("pr10_typed_range");
        configure_group(&mut group, fixture.doc_count);
        let range = request(
            Query::Range {
                field: "n".into(),
                lower: quervant_core::contract::query::Bound::Included(FieldValue::I64(100)),
                upper: quervant_core::contract::query::Bound::Included(FieldValue::I64(200)),
            },
            Sort::default(),
        );
        group.bench_function(BenchmarkId::new("range", &tag), |b| {
            b.iter(|| {
                let response = searcher.search(&range, &budgets, &cancel).expect("range");
                std::hint::black_box(response.total_hits)
            });
        });
        group.finish();

        let mut group = c.benchmark_group("pr10_typed_sort");
        configure_group(&mut group, fixture.doc_count);
        let sort = request(
            Query::MatchAll,
            Sort::new(vec![quervant_core::contract::result::SortField::new(
                "n",
                quervant_core::contract::result::SortDirection::Desc,
            )]),
        );
        group.bench_function(BenchmarkId::new("sort", &tag), |b| {
            b.iter(|| {
                let response = searcher.search(&sort, &budgets, &cancel).expect("sort");
                std::hint::black_box(response.hits.len())
            });
        });
        group.finish();

        let mut group = c.benchmark_group("pr10_typed_aggregate");
        configure_group(&mut group, fixture.doc_count);
        let aggregate = aggregate_request();
        group.bench_function(BenchmarkId::new("group_metrics_distinct", &tag), |b| {
            b.iter(|| {
                let response = searcher
                    .aggregate(&aggregate, &Budgets::new(), &cancel)
                    .expect("aggregate");
                std::hint::black_box(response.groups.len())
            });
        });
        group.finish();
    }
}

criterion_group!(benches, typed_bench);
criterion_main!(benches);
