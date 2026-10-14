//! B02 — whole-search benchmarks over a prebuilt committed index.
//!
//! Each `b.iter` performs exactly one `LexicalSearcher::search` with a fixed
//! query/top-K/budgets/cancellation. Expected hit sets are verified against an
//! independent oracle before any timing. This measures the **whole search**
//! (including the per-search `compute_stats` scan); it is not a direct
//! `compute_stats` microbenchmark.

mod common;

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::result::TopK;
use std::hint::black_box;

use common::{Case, Fixture};

fn bench_cases(
    c: &mut Criterion,
    fixture: &Fixture,
    group_name: &str,
    cases: &[&str],
    top_k: usize,
) {
    let searcher = fixture.searcher();
    let all = common::cases(fixture);
    let mut group = c.benchmark_group(group_name);
    group.throughput(Throughput::Elements(1));
    common::configure_group(&mut group, fixture.doc_count);
    for id in cases {
        let case: &Case = all.iter().find(|case| case.id == *id).expect("case");
        group.bench_function(BenchmarkId::new(*id, format!("k{top_k}")), |b| {
            b.iter(|| {
                let response = searcher
                    .search(
                        &case.query,
                        TopK::new(top_k).expect("topk"),
                        &Budgets::new(),
                        &NeverCancel,
                    )
                    .expect("search");
                black_box(response.total_hits)
            });
        });
    }
    group.finish();
}

fn search_bench(c: &mut Criterion) {
    let all_ids = common::query_ids();

    // All standard cases at 2K / 4 segments.
    let small = common::build(2_000, 4);
    common::assert_all_cases(&small);
    bench_cases(c, &small, "pr07_search_2000_4seg", all_ids, 10);
    bench_cases(
        c,
        &small,
        "pr07_search_2000_4seg_topk100",
        &["term-common"],
        100,
    );

    // Selectivity scaling for rare and common terms.
    let medium = common::build(10_000, 4);
    let large = common::build(100_000, 4);
    common::assert_all_cases(&medium);
    common::assert_all_cases(&large);
    for (fixture, tag) in [(&small, "2000"), (&medium, "10000"), (&large, "100000")] {
        let group_name = format!("pr07_search_scaling_{tag}");
        bench_cases(c, fixture, &group_name, &["term-rare", "term-common"], 10);
    }
}

criterion_group!(benches, search_bench);
criterion_main!(benches);
