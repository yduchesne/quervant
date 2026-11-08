//! PR 15I-C benchmark-only score/parity probe.
//!
//! Runs the frozen PR15D single-term query shape through the public
//! `UnifiedSearcher` and prints the exact `f64::to_bits` value of every returned
//! score. It is executed **outside** the official timing window; the PR15D adapter
//! only reports keys and counts and cannot prove score parity on its own.

use std::process::ExitCode;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::Cardinality;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::Index;
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory};

const SCHEMA_ID: &str = "pr15i-c-score-parity-v1";

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
}

fn parse_args() -> Result<Args, String> {
    let mut index_dir = None;
    let mut field = None;
    let mut term = None;
    let mut k = None;
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
                )
            }
            other => return Err(format!("unknown argument {other}")),
        }
    }
    Ok(Args {
        index_dir: index_dir.ok_or("--index-dir is required")?,
        field: field.ok_or("--field is required")?,
        term: term.ok_or("--term is required")?,
        k: k.ok_or("--k is required")?,
    })
}

fn run(args: &Args) -> Result<(), String> {
    let directory: Arc<dyn Directory> =
        Arc::new(FsDirectory::open(&args.index_dir).map_err(|error| format!("{error:?}"))?);
    let index = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin())
        .map_err(|error| format!("{error:?}"))?;
    let snapshot = index.snapshot();
    let contract = schema();
    let registry = AnalyzerRegistry::builtin();
    let mut request = UnifiedRequest::new(
        Query::Term {
            field: args.field.clone(),
            value: FieldValue::Keyword(args.term.clone()),
        },
        TopK::new(args.k).expect("valid k"),
    );
    request.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    request.projection = Projection::Source;
    let response = UnifiedSearcher::new(&snapshot, &contract, &registry, SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .map_err(|error| format!("{error:?}"))?;

    let mut json = String::new();
    json.push_str(&format!(
        "{{\"schema\": \"{SCHEMA_ID}\", \"field\": \"{}\", \"term\": \"{}\", \"k\": {}, ",
        args.field, args.term, args.k
    ));
    json.push_str(&format!("\"total_hits\": {}, \"hits\": [", response.total_hits));
    for (index, hit) in response.hits.iter().enumerate() {
        if index > 0 {
            json.push(',');
        }
        let score = hit
            .score
            .ok_or_else(|| "lexical hit without a score".to_owned())?;
        if !score.is_finite() {
            return Err("non-finite score".to_owned());
        }
        json.push_str(&format!(
            "{{\"key\": \"{}\", \"score_bits\": \"{:016x}\"}}",
            hit.key.as_str(),
            score.to_bits()
        ));
    }
    json.push_str("]}\n");
    print!("{json}");
    Ok(())
}

fn main() -> ExitCode {
    match parse_args().and_then(|args| run(&args)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("SCORE_PROBE_BLOCKED: {message}");
            ExitCode::FAILURE
        }
    }
}
