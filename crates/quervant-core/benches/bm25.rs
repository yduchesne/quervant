//! B01 — BM25 **reference-arithmetic control** benchmark.
//!
//! The production `search::score::bm25` function is crate-private and is not
//! exposed here. This target times the exact published BM25 equation with fixed
//! `k1 = 1.2`, `b = 0.75` inputs. It is a labeled control, **not** a direct
//! measurement of the production function; whole-search scoring is timed in
//! `search.rs`.

mod common;

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::hint::black_box;

const K1: f64 = 1.2;
const B: f64 = 0.75;

/// The published BM25 contribution equation (control implementation).
fn bm25_control(tf: f64, df: f64, n: f64, dl: f64, avgdl: f64) -> f64 {
    if tf == 0.0 || n == 0.0 || avgdl <= 0.0 {
        return 0.0;
    }
    let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
    idf * (tf * (K1 + 1.0)) / (tf + K1 * (1.0 - B + B * dl / avgdl))
}

fn bench(c: &mut Criterion) {
    let inputs: [(f64, f64, f64, f64, f64); 4] = [
        (1.0, 1.0, 3.0, 2.0, 2.0),
        (3.0, 2.0, 5.0, 10.0, 4.5),
        (7.0, 50.0, 1_000.0, 20.0, 15.0),
        (120.0, 5_000.0, 100_000.0, 64.0, 40.0),
    ];
    let oracle: Vec<f64> = inputs
        .iter()
        .map(|(tf, df, n, dl, avgdl)| bm25_control(*tf, *df, *n, *dl, *avgdl))
        .collect();

    let mut group = c.benchmark_group("pr07_bm25_reference_control");
    group.throughput(Throughput::Elements(inputs.len() as u64));
    group.bench_function(BenchmarkId::new("bm25_equation", "fixed_inputs"), |b| {
        b.iter(|| {
            let mut accumulator = 0.0;
            for (tf, df, n, dl, avgdl) in inputs {
                accumulator += bm25_control(
                    black_box(tf),
                    black_box(df),
                    black_box(n),
                    black_box(dl),
                    black_box(avgdl),
                );
            }
            black_box(accumulator)
        });
    });
    group.finish();

    // The oracle is validated once, outside the timed region.
    for (index, (tf, df, n, dl, avgdl)) in inputs.iter().enumerate() {
        let value = bm25_control(*tf, *df, *n, *dl, *avgdl);
        assert!((value - oracle[index]).abs() < 1e-12);
    }
}

criterion_group!(benches, bench);
criterion_main!(benches);
