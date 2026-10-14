//! B03 — real term-dictionary lookup benchmarks.
//!
//! Uses the public `SegmentReader::dictionary()` / `DictionaryReader::lookup`
//! path on the production dictionary codec. Present and absent terms are
//! measured separately; lookups are validated against the codec's own
//! `doc_freq` before timing.

mod common;

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::hint::black_box;

fn bench_term(c: &mut Criterion, doc_count: usize) {
    let fixture = common::build(doc_count, 1);
    let guard = fixture.snapshot.open_segment_reader(0).expect("segment 0");
    let reader = guard.reader();
    let field_id = reader.schema().field_id("title").expect("field id");
    let dictionary = reader.dictionary().expect("dictionary");

    let present = dictionary
        .lookup(field_id, common::COMMON_TERM)
        .expect("present term");
    let present_df = present.doc_freq;
    assert!(present_df > 0);
    assert!(
        dictionary
            .lookup(field_id, common::ABSENT_SENTINEL)
            .is_none()
    );

    let mut group = c.benchmark_group(format!("pr07_dictionary_{doc_count}"));
    // Exactly one lookup per timed iteration. `ctoken` sorts early in the
    // dictionary while an absent term scans to the end, so the two rows exercise
    // different scan lengths; neither represents a randomized lookup workload.
    group.throughput(Throughput::Elements(1));
    common::configure_group(&mut group, doc_count);
    group.bench_function(
        BenchmarkId::new("dictionary_lookup_present", "ctoken"),
        |b| {
            b.iter(|| {
                let entry = dictionary
                    .lookup(black_box(field_id), black_box(common::COMMON_TERM))
                    .expect("present");
                black_box(entry.doc_freq)
            });
        },
    );
    group.bench_function(
        BenchmarkId::new("dictionary_lookup_absent", "absent_sentinel_zzz"),
        |b| {
            b.iter(|| {
                black_box(
                    dictionary.lookup(black_box(field_id), black_box(common::ABSENT_SENTINEL)),
                )
            });
        },
    );
    group.finish();
}

fn dictionary_bench(c: &mut Criterion) {
    for doc_count in [2_000usize, 10_000, 100_000] {
        bench_term(c, doc_count);
    }
}

criterion_group!(benches, dictionary_bench);
criterion_main!(benches);
