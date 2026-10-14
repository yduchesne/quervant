//! B05 — end-to-end phrase-query benchmarks.
//!
//! These time `Query::Phrase` through `LexicalSearcher::search` (including
//! snapshot statistics), not isolated `phrase_chains` calls. Present, absent and
//! repeated-token phrases are verified against the independent token-array oracle
//! before timing.

mod common;

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::result::TopK;
use std::hint::black_box;

fn bench_phrases(c: &mut Criterion, doc_count: usize) {
    let fixture = common::build(doc_count, 4);
    common::assert_all_cases(&fixture);
    let searcher = fixture.searcher();
    let all = common::cases(&fixture);
    let ids = ["phrase-present", "phrase-absent", "phrase-repeated"];
    let mut group = c.benchmark_group(format!("pr07_phrase_{doc_count}_4seg"));
    group.throughput(Throughput::Elements(1));
    common::configure_group(&mut group, doc_count);
    for id in ids {
        let case = all.iter().find(|case| case.id == id).expect("case");
        group.bench_function(BenchmarkId::new(id, "k10"), |b| {
            b.iter(|| {
                let response = searcher
                    .search(
                        &case.query,
                        TopK::new(10).expect("topk"),
                        &Budgets::new(),
                        &NeverCancel,
                    )
                    .expect("search");
                black_box(response.total_hits)
            });
        });
    }
    group.finish();

    // Independent oracle agreement (untimed): phrase hit sets and total counts.
    for case in &all {
        if ids.contains(&case.id) {
            common::assert_case(&fixture, case);
        }
    }
}

fn phrase_bench(c: &mut Criterion) {
    bench_phrases(c, 2_000);
    bench_phrases(c, 10_000);
}

criterion_group!(benches, phrase_bench);
criterion_main!(benches);
