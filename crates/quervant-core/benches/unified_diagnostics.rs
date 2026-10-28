//! PR 15B unified whole-query Criterion diagnostics.
//!
//! Every timed closure invokes the real public production entrypoint once and
//! black-boxes the response. Fixture construction, index/commit/reopen, the
//! independent oracle gate and pagination cursor discovery all happen before any
//! timed region. A failed oracle aborts the entire process, so no qualifying
//! timing is emitted for a mismatched lane.
//!
//! This target is diagnostic only: it changes no search semantics, formats,
//! budgets or public contracts.

mod unified_diag_common;

use criterion::measurement::WallTime;
use criterion::{BenchmarkGroup, Criterion, Throughput, criterion_group, criterion_main};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::result::Projection;
use quervant_core::contract::value::Timestamp;
use quervant_core::search::{SearchLimits, UnifiedSearcher, execute_batch_pinned};
use std::hint::black_box;
use std::time::Duration;

use unified_diag_common as common;

const PAGE_SIZE: usize = 100;
const N10K: usize = 10_000;
const N100K: usize = 100_000;

fn configure(group: &mut BenchmarkGroup<'_, WallTime>) {
    group
        .throughput(Throughput::Elements(1))
        .warm_up_time(Duration::from_secs(3))
        .measurement_time(Duration::from_secs(5))
        .sample_size(20);
}

fn find_corpus(corpora: &[common::Corpus], n: usize, s: usize) -> &common::Corpus {
    corpora
        .iter()
        .find(|corpus| corpus.n == n && corpus.s == s)
        .unwrap_or_else(|| panic!("fixture N={n} S={s} was not built"))
}

/// Corpus sizes that carry the U01–U04 scaling lanes.
fn scaling_sizes(corpora: &[common::Corpus]) -> Vec<(usize, usize)> {
    corpora
        .iter()
        .filter(|corpus| corpus.s == 4 && matches!(corpus.n, 2_000 | N10K | N100K | 1_000_000))
        .map(|corpus| (corpus.n, corpus.s))
        .collect()
}

/// Segment topologies that carry the U11 fan-out lanes.
fn segment_sizes(corpora: &[common::Corpus]) -> Vec<(usize, usize)> {
    corpora
        .iter()
        .filter(|corpus| {
            (corpus.n == N10K && matches!(corpus.s, 1 | 4 | 16))
                || (corpus.n == N100K && corpus.s == 64)
        })
        .map(|corpus| (corpus.n, corpus.s))
        .collect()
}

fn build_corpora() -> Vec<common::Corpus> {
    let mut corpora = vec![
        common::build_corpus(2_000, 4),
        common::build_corpus(N10K, 1),
        common::build_corpus(N10K, 4),
        common::build_corpus(N10K, 16),
        common::build_corpus(N100K, 4),
    ];
    if std::env::var(common::LARGE_ENV).ok().as_deref() == Some("1") {
        corpora.push(common::build_corpus(1_000_000, 4));
    }
    if std::env::var(common::SEG64_ENV).ok().as_deref() == Some("1") {
        corpora.push(common::build_corpus(N100K, 64));
    }
    corpora
}

/// Execute every mandatory oracle gate exactly once, before any timing.
fn validate_all(corpora: &[common::Corpus], geo: &common::GeoCorpus) {
    common::assert_canonical_fixture_digest();
    for corpus in corpora {
        common::assert_corpus_shape(corpus);
    }
    for (n, s) in scaling_sizes(corpora) {
        let corpus = find_corpus(corpora, n, s);
        common::assert_absent(corpus);
        common::assert_rare(corpus);
        common::assert_medium(corpus);
        common::assert_common_mixed(corpus);
    }
    let standard = find_corpus(corpora, N10K, 4);
    common::assert_cidr_time(standard);
    common::assert_json_severity(standard);
    for k in [10, 100, 1_000] {
        common::assert_sort_n(standard, k);
    }
    common::assert_sort_host(standard, 100);
    common::assert_projection(standard);
    common::assert_aggregation(standard);
    common::assert_batch(standard);
    common::assert_pinned_pages(standard, PAGE_SIZE);
    for (n, s) in segment_sizes(corpora) {
        let corpus = find_corpus(corpora, n, s);
        common::assert_rare(corpus);
        common::assert_common_mixed(corpus);
    }
    common::assert_geo(geo);
}

fn validate_and_emit_metadata(corpora: &[common::Corpus], geo: &common::GeoCorpus) {
    validate_all(corpora, geo);
    let mut metas: Vec<common::CorpusMeta> = corpora.iter().map(common::corpus_meta).collect();
    metas.push(common::geo_meta(geo));
    common::emit_fixture_metadata(&metas);
}

// ---------------------------------------------------------------------------
// U01–U04 selectivity scaling
// ---------------------------------------------------------------------------

fn bench_absent(c: &mut Criterion, corpora: &[common::Corpus]) {
    let budgets = Budgets::new();
    for (n, s) in scaling_sizes(corpora) {
        let corpus = find_corpus(corpora, n, s);
        let request = common::request_absent();
        let searcher = UnifiedSearcher::new(
            &corpus.snapshot,
            &corpus.schema,
            &corpus.registry,
            SearchLimits::default(),
        );
        let mut group = c.benchmark_group(format!("pr15b_v1/u01/n{n}_s{s}/k100"));
        configure(&mut group);
        group.bench_function("absent", |b| {
            b.iter(|| {
                let response = searcher
                    .search(&request, &budgets, &NeverCancel)
                    .expect("absent search");
                black_box((response.hits.len(), response.total_hits))
            });
        });
        group.finish();
    }
}

fn bench_rare(c: &mut Criterion, corpora: &[common::Corpus]) {
    let budgets = Budgets::new();
    for (n, s) in scaling_sizes(corpora) {
        let corpus = find_corpus(corpora, n, s);
        let request = common::request_rare();
        let searcher = UnifiedSearcher::new(
            &corpus.snapshot,
            &corpus.schema,
            &corpus.registry,
            SearchLimits::default(),
        );
        let mut group = c.benchmark_group(format!("pr15b_v1/u02/n{n}_s{s}/k100"));
        configure(&mut group);
        group.bench_function("rare", |b| {
            b.iter(|| {
                let response = searcher
                    .search(&request, &budgets, &NeverCancel)
                    .expect("rare search");
                black_box((response.hits.len(), response.total_hits))
            });
        });
        group.finish();
    }
}

fn bench_medium(c: &mut Criterion, corpora: &[common::Corpus]) {
    let budgets = Budgets::new();
    for (n, s) in scaling_sizes(corpora) {
        let corpus = find_corpus(corpora, n, s);
        let request = common::request_medium();
        let searcher = UnifiedSearcher::new(
            &corpus.snapshot,
            &corpus.schema,
            &corpus.registry,
            SearchLimits::default(),
        );
        let mut group = c.benchmark_group(format!("pr15b_v1/u03/n{n}_s{s}/k100"));
        configure(&mut group);
        group.bench_function("medium", |b| {
            b.iter(|| {
                let response = searcher
                    .search(&request, &budgets, &NeverCancel)
                    .expect("medium search");
                black_box((response.hits.len(), response.total_hits))
            });
        });
        group.finish();
    }
}

fn bench_common_mixed(c: &mut Criterion, corpora: &[common::Corpus]) {
    let budgets = Budgets::new();
    for (n, s) in scaling_sizes(corpora) {
        let corpus = find_corpus(corpora, n, s);
        let request = common::request_common_mixed(n);
        let searcher = UnifiedSearcher::new(
            &corpus.snapshot,
            &corpus.schema,
            &corpus.registry,
            SearchLimits::default(),
        );
        let mut group = c.benchmark_group(format!("pr15b_v1/u04/n{n}_s{s}/k100"));
        configure(&mut group);
        group.bench_function("common-mixed", |b| {
            b.iter(|| {
                let response = searcher
                    .search(&request, &budgets, &NeverCancel)
                    .expect("common-mixed search");
                black_box((response.hits.len(), response.total_hits))
            });
        });
        group.finish();
    }
}

// ---------------------------------------------------------------------------
// U05–U06 typed composition and JSON
// ---------------------------------------------------------------------------

fn bench_cidr_time(c: &mut Criterion, corpora: &[common::Corpus]) {
    let corpus = find_corpus(corpora, N10K, 4);
    let request = common::request_cidr_time(N10K);
    let budgets = Budgets::new();
    let searcher = UnifiedSearcher::new(
        &corpus.snapshot,
        &corpus.schema,
        &corpus.registry,
        SearchLimits::default(),
    );
    let mut group = c.benchmark_group(format!("pr15b_v1/u05/n{N10K}_s4/k100"));
    configure(&mut group);
    group.bench_function("cidr-time", |b| {
        b.iter(|| {
            let response = searcher
                .search(&request, &budgets, &NeverCancel)
                .expect("cidr-time search");
            black_box((response.hits.len(), response.total_hits))
        });
    });
    group.finish();
}

fn bench_json_scalar(c: &mut Criterion, corpora: &[common::Corpus]) {
    let corpus = find_corpus(corpora, N10K, 4);
    let request = common::request_json_severity();
    let budgets = Budgets::new();
    let searcher = UnifiedSearcher::new(
        &corpus.snapshot,
        &corpus.schema,
        &corpus.registry,
        SearchLimits::default(),
    );
    let mut group = c.benchmark_group(format!("pr15b_v1/u06/n{N10K}_s4/k100"));
    configure(&mut group);
    group.bench_function("json-scalar", |b| {
        b.iter(|| {
            let response = searcher
                .search(&request, &budgets, &NeverCancel)
                .expect("json search");
            black_box((response.hits.len(), response.total_hits))
        });
    });
    group.finish();
}

// ---------------------------------------------------------------------------
// U07–U08 sort and projection
// ---------------------------------------------------------------------------

fn bench_sort_n(c: &mut Criterion, corpora: &[common::Corpus]) {
    let corpus = find_corpus(corpora, N10K, 4);
    let budgets = Budgets::new();
    let searcher = UnifiedSearcher::new(
        &corpus.snapshot,
        &corpus.schema,
        &corpus.registry,
        SearchLimits::default(),
    );
    for k in [10, 100, 1_000] {
        let request = common::request_sort_n(k);
        let mut group = c.benchmark_group(format!("pr15b_v1/u07/n{N10K}_s4/k{k}"));
        configure(&mut group);
        group.bench_function("sort-n", |b| {
            b.iter(|| {
                let response = searcher
                    .search(&request, &budgets, &NeverCancel)
                    .expect("sort search");
                black_box((response.hits.len(), response.total_hits))
            });
        });
        group.finish();
    }
}

fn bench_projection(c: &mut Criterion, corpora: &[common::Corpus]) {
    let corpus = find_corpus(corpora, N10K, 4);
    let budgets = Budgets::new();
    let searcher = UnifiedSearcher::new(
        &corpus.snapshot,
        &corpus.schema,
        &corpus.registry,
        SearchLimits::default(),
    );
    let variants = [
        ("source", Projection::Source),
        (
            "fields-host-n",
            Projection::Fields(vec!["host".into(), "n".into()]),
        ),
    ];
    for (variant, projection) in variants {
        let request = common::request_projection(100, projection);
        let mut group = c.benchmark_group(format!("pr15b_v1/u08/n{N10K}_s4/k100"));
        configure(&mut group);
        group.bench_function(variant, |b| {
            b.iter(|| {
                let response = searcher
                    .search(&request, &budgets, &NeverCancel)
                    .expect("projection search");
                black_box((response.hits.len(), response.total_hits))
            });
        });
        group.finish();
    }
}

// ---------------------------------------------------------------------------
// U09–U10 aggregation and serial batch (pinned batch public surface)
// ---------------------------------------------------------------------------

fn bench_aggregation(c: &mut Criterion, corpora: &[common::Corpus]) {
    let corpus = find_corpus(corpora, N10K, 4);
    let pit = corpus.index.pin().expect("aggregation pit");
    let batch = common::batch_u09(&pit);
    let policy = common::batch_policy();
    let capabilities = CapabilitySet::new();
    let limits = SearchLimits::default();
    let now = Timestamp::from_micros(common::NOW_MICROS);
    let deadline = Timestamp::from_micros(common::DEADLINE_MICROS);
    let mut group = c.benchmark_group(format!("pr15b_v1/u09/n{N10K}_s4/k100"));
    configure(&mut group);
    group.bench_function("aggregate-host", |b| {
        b.iter(|| {
            let response = execute_batch_pinned(
                &pit,
                &corpus.schema,
                &corpus.registry,
                limits,
                &batch,
                &policy,
                &capabilities,
                &NeverCancel,
                now,
                deadline,
            )
            .expect("aggregation batch");
            let slot = common::success(&response, 0);
            black_box((
                slot.total_hits,
                slot.aggregation
                    .as_ref()
                    .map_or(0, |aggregation| aggregation.groups.len()),
            ))
        });
    });
    group.finish();
}

fn bench_serial_batch(c: &mut Criterion, corpora: &[common::Corpus]) {
    let corpus = find_corpus(corpora, N10K, 4);
    let pit = corpus.index.pin().expect("batch pit");
    let batch = common::batch_u10(&pit, N10K);
    let policy = common::batch_policy();
    let capabilities = CapabilitySet::new();
    let limits = SearchLimits::default();
    let now = Timestamp::from_micros(common::NOW_MICROS);
    let deadline = Timestamp::from_micros(common::DEADLINE_MICROS);
    let mut group = c.benchmark_group(format!("pr15b_v1/u10/n{N10K}_s4/k100"));
    configure(&mut group);
    group.bench_function("serial-batch", |b| {
        b.iter(|| {
            let response = execute_batch_pinned(
                &pit,
                &corpus.schema,
                &corpus.registry,
                limits,
                &batch,
                &policy,
                &capabilities,
                &NeverCancel,
                now,
                deadline,
            )
            .expect("serial batch");
            let mut totals = [0u64; 3];
            for (slot, total) in totals.iter_mut().enumerate() {
                *total = common::success(&response, slot).total_hits;
            }
            black_box(totals)
        });
    });
    group.finish();
}

// ---------------------------------------------------------------------------
// U11 segment fan-out
// ---------------------------------------------------------------------------

fn bench_segments(c: &mut Criterion, corpora: &[common::Corpus]) {
    let budgets = Budgets::new();
    for (n, s) in segment_sizes(corpora) {
        let corpus = find_corpus(corpora, n, s);
        let searcher = UnifiedSearcher::new(
            &corpus.snapshot,
            &corpus.schema,
            &corpus.registry,
            SearchLimits::default(),
        );
        let variants = [
            ("rare", common::request_rare()),
            ("common-mixed", common::request_common_mixed(n)),
        ];
        for (variant, request) in variants {
            let mut group = c.benchmark_group(format!("pr15b_v1/u11/n{n}_s{s}/k100"));
            configure(&mut group);
            group.bench_function(variant, |b| {
                b.iter(|| {
                    let response = searcher
                        .search(&request, &budgets, &NeverCancel)
                        .expect("segment search");
                    black_box((response.hits.len(), response.total_hits))
                });
            });
            group.finish();
        }
    }
}

// ---------------------------------------------------------------------------
// U12 pinned pagination
// ---------------------------------------------------------------------------

fn bench_pinned_pages(c: &mut Criterion, corpora: &[common::Corpus]) {
    let corpus = find_corpus(corpora, N10K, 4);
    let pit = corpus.index.pin().expect("pagination pit");
    let policy = common::batch_policy();
    let capabilities = CapabilitySet::new();
    let limits = SearchLimits::default();
    let now = Timestamp::from_micros(common::NOW_MICROS);
    let deadline = Timestamp::from_micros(common::DEADLINE_MICROS);

    let page_one = common::pinned_batch(
        &pit,
        vec![common::to_query_request(&common::request_sort_n(PAGE_SIZE))],
    );
    let first = corpus.run_batch(&pit, &page_one);
    let first_slot = common::success(&first, 0);
    assert_eq!(first_slot.total_hits, N10K as u64);
    let cursor = first_slot.next_cursor.clone().expect("page 2 cursor");
    let mut page_two_request = common::to_query_request(&common::request_sort_n(PAGE_SIZE));
    page_two_request.cursor = Some(cursor);
    let page_two = common::pinned_batch(&pit, vec![page_two_request]);

    for (variant, batch) in [("page-1", &page_one), ("page-2", &page_two)] {
        let mut group = c.benchmark_group(format!("pr15b_v1/u12/n{N10K}_s4/k100"));
        configure(&mut group);
        group.bench_function(variant, |b| {
            b.iter(|| {
                let response = execute_batch_pinned(
                    &pit,
                    &corpus.schema,
                    &corpus.registry,
                    limits,
                    batch,
                    &policy,
                    &capabilities,
                    &NeverCancel,
                    now,
                    deadline,
                )
                .expect("pinned page");
                let slot = common::success(&response, 0);
                black_box((slot.hits.len(), slot.total_hits))
            });
        });
        group.finish();
    }
}

// ---------------------------------------------------------------------------
// U13 separate geo provenance case
// ---------------------------------------------------------------------------

fn bench_geo(c: &mut Criterion, geo: &common::GeoCorpus) {
    let request = common::request_geo_bbox();
    let budgets = Budgets::new();
    let searcher = UnifiedSearcher::new(
        &geo.snapshot,
        &geo.schema,
        &geo.registry,
        SearchLimits::default(),
    );
    let mut group = c.benchmark_group("pr15b_v1/u13/geo_n8_s1/k100");
    configure(&mut group);
    group.bench_function("geo-bbox", |b| {
        b.iter(|| {
            let response = searcher
                .search(&request, &budgets, &NeverCancel)
                .expect("geo search");
            black_box((response.hits.len(), response.total_hits))
        });
    });
    group.finish();
}

fn unified_bench(c: &mut Criterion) {
    let corpora = build_corpora();
    let geo = common::build_geo_corpus();
    validate_and_emit_metadata(&corpora, &geo);

    bench_absent(c, &corpora);
    bench_rare(c, &corpora);
    bench_medium(c, &corpora);
    bench_common_mixed(c, &corpora);
    bench_cidr_time(c, &corpora);
    bench_json_scalar(c, &corpora);
    bench_sort_n(c, &corpora);
    bench_projection(c, &corpora);
    bench_aggregation(c, &corpora);
    bench_serial_batch(c, &corpora);
    bench_segments(c, &corpora);
    bench_pinned_pages(c, &corpora);
    bench_geo(c, &geo);
}

criterion_group!(benches, unified_bench);
criterion_main!(benches);
