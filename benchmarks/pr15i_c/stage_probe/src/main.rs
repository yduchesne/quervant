//! PR 15I-C benchmark-only stage probe.
//!
//! Opens an existing committed index through the **public** `quervant-core` API,
//! runs the frozen PR15D single-term query shape, and writes one JSON file with
//! the per-stage durations accumulated by the opt-in `pr15ic-probe` feature.
//!
//! This binary is diagnostic only. It is never part of the official paired
//! measurement campaign and it never installs an alternate search or scoring
//! implementation.

use std::fs;
use std::process::ExitCode;
use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::Cardinality;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::Index;
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher, probe};
use quervant_core::storage::{Directory, FsDirectory};

const SCHEMA_ID: &str = "pr15i-c-stage-probe-v1";

/// The frozen PR15D adapter schema. Kept byte-identical in shape to
/// `benchmarks/pr15d/adapters/quervant` so the probe opens the same indexes.
fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "doc_id",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "key",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "group",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "body",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "payload",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
        ],
        None,
    )
    .expect("frozen probe schema")
}

struct Args {
    index_dir: String,
    field: String,
    term: String,
    k: usize,
    warmups: usize,
    runs: usize,
    out: String,
    source_sha: String,
}

fn parse_args() -> Result<Args, String> {
    let mut index_dir = None;
    let mut field = None;
    let mut term = None;
    let mut k = None;
    let mut warmups = 5usize;
    let mut runs = 4usize;
    let mut out = None;
    let mut source_sha = "unrecorded".to_owned();
    let mut arguments = std::env::args().skip(1);
    while let Some(flag) = arguments.next() {
        let mut value = || {
            arguments
                .next()
                .ok_or_else(|| format!("{flag} requires a value"))
        };
        match flag.as_str() {
            "--index-dir" => index_dir = Some(value()?),
            "--field" => field = Some(value()?),
            "--term" => term = Some(value()?),
            "--k" => {
                k = Some(
                    value()?
                        .parse::<usize>()
                        .map_err(|error| format!("--k: {error}"))?,
                );
            }
            "--warmups" => {
                warmups = value()?
                    .parse::<usize>()
                    .map_err(|error| format!("--warmups: {error}"))?;
            }
            "--runs" => {
                runs = value()?
                    .parse::<usize>()
                    .map_err(|error| format!("--runs: {error}"))?;
            }
            "--out" => out = Some(value()?),
            "--source-sha" => source_sha = value()?,
            other => return Err(format!("unknown argument {other}")),
        }
    }
    Ok(Args {
        index_dir: index_dir.ok_or("--index-dir is required")?,
        field: field.ok_or("--field is required")?,
        term: term.ok_or("--term is required")?,
        k: k.ok_or("--k is required")?,
        warmups,
        runs,
        out: out.ok_or("--out is required")?,
        source_sha,
    })
}

fn median(values: &[u64]) -> u64 {
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let count = sorted.len();
    if count == 0 {
        return 0;
    }
    if count % 2 == 1 {
        sorted[count / 2]
    } else {
        (sorted[count / 2 - 1] + sorted[count / 2]) / 2
    }
}

fn request(args: &Args) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(
        Query::Term {
            field: args.field.clone(),
            value: FieldValue::Keyword(args.term.clone()),
        },
        TopK::new(args.k).expect("valid k"),
    );
    request.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    request.projection = Projection::Source;
    request
}

fn run(args: &Args) -> Result<(), String> {
    let directory: Arc<dyn Directory> =
        Arc::new(FsDirectory::open(&args.index_dir).map_err(|error| format!("{error:?}"))?);
    let index = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin())
        .map_err(|error| format!("{error:?}"))?;
    let snapshot = index.snapshot();
    let request = request(args);
    let cancel = CancellationFlag::new();
    let contract = schema();
    let registry = AnalyzerRegistry::builtin();
    let searcher = UnifiedSearcher::new(
        &snapshot,
        &contract,
        &registry,
        SearchLimits::default(),
    );
    for _ in 0..args.warmups {
        searcher
            .search(&request, &Budgets::new(), &cancel)
            .map_err(|error| format!("{error:?}"))?;
    }

    let mut totals = Vec::new();
    let mut stages: Vec<Vec<(&'static str, u64)>> = Vec::new();
    for _ in 0..args.runs {
        probe::reset();
        let started = Instant::now();
        let response = searcher
            .search(&request, &Budgets::new(), &cancel)
            .map_err(|error| format!("{error:?}"))?;
        let total = u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
        if response.total_hits == 0 {
            return Err("probe query returned zero hits".to_owned());
        }
        totals.push(total);
        stages.push(probe::snapshot());
    }

    let names: Vec<&'static str> = stages
        .first()
        .map(|record| record.iter().map(|(name, _)| *name).collect())
        .unwrap_or_default();
    let mut medians = Vec::new();
    for (index, name) in names.iter().enumerate() {
        let values: Vec<u64> = stages.iter().map(|record| record[index].1).collect();
        medians.push((*name, median(&values)));
    }
    let median_total = median(&totals);
    let attributed: u64 = medians
        .iter()
        .map(|(_, value)| *value)
        .fold(0u64, |acc, value| acc.saturating_add(value));
    let other_unattributed = median_total.saturating_sub(attributed);

    let mut json = String::new();
    json.push_str("{\n");
    json.push_str(&format!("  \"schema\": \"{SCHEMA_ID}\",\n"));
    json.push_str(&format!(
        "  \"source_sha\": \"{}\",\n",
        args.source_sha
    ));
    json.push_str(&format!(
        "  \"lane\": {{\"field\": \"{}\", \"term\": \"{}\", \"k\": {}, \"warmups\": {}, \"runs\": {}}},\n",
        args.field, args.term, args.k, args.warmups, args.runs
    ));
    json.push_str(&format!("  \"total_search_ns\": {median_total},\n"));
    json.push_str(&format!(
        "  \"other_unattributed_ns\": {other_unattributed},\n"
    ));
    json.push_str("  \"stages_ns\": {");
    for (index, (name, value)) in medians.iter().enumerate() {
        if index > 0 {
            json.push_str(", ");
        }
        json.push_str(&format!("\"{name}\": {value}"));
    }
    json.push_str("},\n");
    json.push_str("  \"samples\": [");
    for (index, total) in totals.iter().enumerate() {
        if index > 0 {
            json.push_str(", ");
        }
        json.push_str(&format!("{{\"total_search_ns\": {total}, \"stages_ns\": {{"));
        for (position, (name, value)) in stages[index].iter().enumerate() {
            if position > 0 {
                json.push_str(", ");
            }
            json.push_str(&format!("\"{name}\": {value}"));
        }
        json.push_str("}}");
    }
    json.push_str("]\n}\n");

    if let Some(parent) = std::path::Path::new(&args.out).parent() {
        fs::create_dir_all(parent).map_err(|error| format!("{error:?}"))?;
    }
    if std::path::Path::new(&args.out).exists() {
        return Err(format!("refusing to replace {}", args.out));
    }
    fs::write(&args.out, json).map_err(|error| format!("{error:?}"))?;
    println!(
        "stage probe: lane={}/{} k={} total_median_ns={median_total} unattributed_ns={other_unattributed}",
        args.field, args.term, args.k
    );
    Ok(())
}

fn main() -> ExitCode {
    match parse_args().and_then(|args| run(&args)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("STAGE_PROBE_BLOCKED: {message}");
            ExitCode::FAILURE
        }
    }
}
