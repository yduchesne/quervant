//! B04 — real postings decode/iteration benchmarks.
//!
//! Cursor construction (`SegmentReader::postings` → `PostingsReader::new`) occurs
//! per iteration, so the measured operation is labeled
//! `cursor_open_plus_decode`; its cost is not hidden. Counts are verified against
//! the codec's own `posting_doc_count` before timing. The production codec is
//! used, not a synthetic vector cursor.

mod common;

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::hint::black_box;

fn bench_term(c: &mut Criterion, doc_count: usize, term: &str) {
    let fixture = common::build(doc_count, 1);
    let guard = fixture.snapshot.open_segment_reader(0).expect("segment 0");
    let reader = guard.reader();
    let field_id = reader.schema().field_id("title").expect("field id");
    let expected = reader
        .postings(field_id, term)
        .expect("postings")
        .map(|postings| postings.posting_doc_count())
        .unwrap_or(0);

    // Verify the decoded stream before timing.
    {
        let mut decoded = 0u64;
        let mut previous: Option<u64> = None;
        if let Some(mut postings) = reader.postings(field_id, term).expect("postings") {
            while let Some(posting) = postings.next().expect("posting") {
                if let Some(previous) = previous {
                    assert!(posting.doc_id > previous, "doc ids must ascend");
                }
                previous = Some(posting.doc_id);
                decoded += 1;
            }
        }
        assert_eq!(decoded, expected, "decoded posting count mismatch");
    }

    let mut group = c.benchmark_group(format!("pr07_postings_{doc_count}"));
    group.throughput(Throughput::Elements(expected.max(1)));
    common::configure_group(&mut group, doc_count);
    group.bench_function(BenchmarkId::new("cursor_open_plus_decode", term), |b| {
        b.iter(|| {
            let mut count = 0u64;
            if let Some(mut postings) = reader.postings(field_id, term).expect("postings") {
                while let Some(posting) = postings.next().expect("posting") {
                    count += 1;
                    black_box(posting.doc_id);
                    black_box(posting.freq);
                }
            }
            black_box(count)
        });
    });
    group.finish();
}

fn postings_bench(c: &mut Criterion) {
    for doc_count in [2_000usize, 10_000, 100_000] {
        bench_term(c, doc_count, common::COMMON_TERM);
    }
}

criterion_group!(benches, postings_bench);
criterion_main!(benches);
