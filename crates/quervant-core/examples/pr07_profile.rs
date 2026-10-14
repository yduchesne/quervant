//! Benchmark-only profiling entrypoint for PR 7 Amendment 04.
//!
//! Reuses the exact Criterion fixture (`benches/common`) so the profiled workload
//! is identical to the timed one. It validates the oracle, then loops a fixed
//! workload for a bounded duration so `perf`/`heaptrack` can sample it. This is
//! not a Criterion timing target; profiling-instrumented runs are never mixed
//! with uninstrumented Criterion baselines.

#[path = "../benches/common/mod.rs"]
mod common;

use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::result::TopK;
use std::hint::black_box;
use std::time::{Duration, Instant};

fn main() {
    let mut workload = String::from("rare-2k");
    let mut seconds = 20u64;
    let mut print_digest = false;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--workload" => workload = args.next().expect("--workload value"),
            "--seconds" => {
                seconds = args
                    .next()
                    .expect("--seconds value")
                    .parse()
                    .expect("seconds")
            }
            "--print-digest" => print_digest = true,
            other => {
                eprintln!("unknown argument: {other}");
                std::process::exit(64);
            }
        }
    }

    let (case_id, doc_count) = match workload.as_str() {
        "rare-2k" => ("term-rare", 2_000usize),
        "rare-10k" => ("term-rare", 10_000),
        "rare-100k" => ("term-rare", 100_000),
        "common-2k" => ("term-common", 2_000),
        "common-10k" => ("term-common", 10_000),
        "common-100k" => ("term-common", 100_000),
        "phrase-2k" => ("phrase-present", 2_000),
        "phrase-10k" => ("phrase-present", 10_000),
        other => {
            eprintln!("unknown workload: {other}");
            std::process::exit(64);
        }
    };

    let fixture = common::build(doc_count, 4);
    if print_digest {
        println!("{}", fixture.dataset_sha256());
        return;
    }
    common::assert_all_cases(&fixture);
    let case = common::cases(&fixture)
        .into_iter()
        .find(|case| case.id == case_id)
        .expect("case");
    common::assert_case(&fixture, &case);

    let searcher = fixture.searcher();
    let deadline = Instant::now() + Duration::from_secs(seconds);
    let mut iterations = 0u64;
    while Instant::now() < deadline {
        let response = searcher
            .search(
                &case.query,
                TopK::new(10).expect("topk"),
                &Budgets::new(),
                &NeverCancel,
            )
            .expect("search");
        black_box(response.total_hits);
        iterations += 1;
    }
    println!("profile workload {workload}: {iterations} iterations of {case_id} in {seconds}s");
}
