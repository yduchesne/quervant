//! PR 15B release-build profiling driver.
//!
//! The driver builds the same deterministic 10K/4 corpus and uses exactly the
//! same request constructors as the Criterion target. It executes the untimed
//! independent oracle once, then repeatedly executes the real production search
//! entrypoint for a bounded duration. Time/iteration controls are outside query
//! semantics and never modify search budgets.
//!
//! Accepted CLI:
//! `pr15b_profile --workload <absent|rare|mixed|json|sort|aggregation|batch> --seconds <1..=120>`

#[path = "../benches/unified_diag_common/mod.rs"]
mod unified_diag_common;

use std::hint::black_box;
use std::time::{Duration, Instant};

use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::value::Timestamp;
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher, execute_batch_pinned};

use unified_diag_common as common;

const N: usize = 10_000;
const S: usize = 4;

enum Mode {
    Unified(Box<UnifiedRequest>),
    Aggregation,
    Batch,
}

fn usage() -> &'static str {
    "usage: pr15b_profile --workload <absent|rare|mixed|json|sort|aggregation|batch> --seconds <1..=120>"
}

fn parse_args() -> Result<(String, u64), String> {
    let mut workload = None;
    let mut seconds = None;
    let mut args = std::env::args().skip(1);
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--workload" => {
                workload = Some(
                    args.next()
                        .ok_or_else(|| "--workload requires a value".to_owned())?,
                );
            }
            "--seconds" => {
                seconds = Some(
                    args.next()
                        .ok_or_else(|| "--seconds requires a value".to_owned())?,
                );
            }
            "-h" | "--help" => return Err(usage().to_owned()),
            other => return Err(format!("unknown argument {other}; {}", usage())),
        }
    }
    let workload = workload.ok_or_else(|| format!("--workload is required; {}", usage()))?;
    let seconds = seconds.ok_or_else(|| format!("--seconds is required; {}", usage()))?;
    let workload = common::parse_profile_workload(&workload)?;
    let seconds = common::parse_profile_seconds(&seconds)?;
    Ok((workload.as_str().to_owned(), seconds))
}

fn mode_for(workload: &str) -> Mode {
    match workload {
        "absent" => Mode::Unified(Box::new(common::request_absent())),
        "rare" => Mode::Unified(Box::new(common::request_rare())),
        "mixed" => Mode::Unified(Box::new(common::request_common_mixed(N))),
        "json" => Mode::Unified(Box::new(common::request_json_severity())),
        "sort" => Mode::Unified(Box::new(common::request_sort_n(100))),
        "aggregation" => Mode::Aggregation,
        "batch" => Mode::Batch,
        other => unreachable!("validated workload {other}"),
    }
}

fn run(workload: &str, seconds: u64) {
    let corpus = common::build_corpus(N, S);
    common::assert_corpus_shape(&corpus);
    let mode = mode_for(workload);

    // Untimed independent oracle gate.
    match workload {
        "absent" => common::assert_absent(&corpus),
        "rare" => common::assert_rare(&corpus),
        "mixed" => common::assert_common_mixed(&corpus),
        "json" => common::assert_json_severity(&corpus),
        "sort" => common::assert_sort_n(&corpus, 100),
        "aggregation" => common::assert_aggregation(&corpus),
        "batch" => common::assert_batch(&corpus),
        other => unreachable!("validated workload {other}"),
    }

    let duration = Duration::from_secs(seconds);
    let start = Instant::now();
    let mut iterations = 0u64;
    let mut checksum = 0u64;
    match mode {
        Mode::Unified(request) => {
            let budgets = Budgets::new();
            let searcher = UnifiedSearcher::new(
                &corpus.snapshot,
                &corpus.schema,
                &corpus.registry,
                SearchLimits::default(),
            );
            while start.elapsed() < duration {
                let response = searcher
                    .search(&request, &budgets, &NeverCancel)
                    .expect("profile search");
                checksum = checksum
                    .wrapping_add(response.total_hits)
                    .wrapping_add(response.hits.len() as u64);
                black_box(&response);
                iterations += 1;
            }
        }
        Mode::Aggregation => {
            let pit = corpus.index.pin().expect("profile pit");
            let batch = common::batch_u09(&pit);
            let policy = common::batch_policy();
            let capabilities = CapabilitySet::new();
            let limits = SearchLimits::default();
            let now = Timestamp::from_micros(common::NOW_MICROS);
            let deadline = Timestamp::from_micros(common::DEADLINE_MICROS);
            while start.elapsed() < duration {
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
                .expect("profile aggregation");
                let slot = common::success(&response, 0);
                checksum = checksum.wrapping_add(slot.total_hits);
                black_box(&response);
                iterations += 1;
            }
        }
        Mode::Batch => {
            let pit = corpus.index.pin().expect("profile pit");
            let batch = common::batch_u10(&pit, N);
            let policy = common::batch_policy();
            let capabilities = CapabilitySet::new();
            let limits = SearchLimits::default();
            let now = Timestamp::from_micros(common::NOW_MICROS);
            let deadline = Timestamp::from_micros(common::DEADLINE_MICROS);
            while start.elapsed() < duration {
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
                .expect("profile batch");
                checksum = checksum.wrapping_add(response.len() as u64);
                black_box(&response);
                iterations += 1;
            }
        }
    }

    println!(
        "workload={workload} seconds={seconds} iterations={iterations} checksum={checksum} profile=release status=ok"
    );
}

fn main() {
    let (workload, seconds) = match parse_args() {
        Ok(parsed) => parsed,
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(64);
        }
    };
    println!("workload={workload} seconds={seconds} profile=release status=started");
    let outcome =
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| run(&workload, seconds)));
    match outcome {
        Ok(()) => {}
        Err(_) => {
            eprintln!("workload={workload} profile=release status=oracle_failure");
            std::process::exit(1);
        }
    }
}
