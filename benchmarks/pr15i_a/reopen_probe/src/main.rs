//! PR 15I-A benchmark-only fresh-process reopen probe.
//!
//! Uses **public** `quervant-core` APIs only: `FsDirectory`,
//! `Index::open_with_limits`, `Index::snapshot`. It never writes to the index
//! directory, never parses a private format and never changes production code.
//!
//! ```text
//! pr15i-a-reopen-probe --index-dir <absolute> --n 10000|100000
//! ```
//!
//! Exactly one canonical JSON object is written to stdout. Diagnostics go to
//! stderr and a failure exits non-zero with no JSON object.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::Cardinality;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::FieldType;
use quervant_core::index::{Index, IndexLimits};
use quervant_core::storage::{Directory, FsDirectory};
use serde_json::json;

const SCHEMA: &str = "pr15i-a-reopen-probe-v1";
const N_VALUES: [u64; 2] = [10_000, 100_000];

/// Mirror of the frozen PR15D adapter schema; the reopen probe must bind the
/// same schema/analyzer identity as the index it opens.
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
    .expect("frozen adapter schema")
}

fn benchmark_limits() -> IndexLimits {
    const MAX_BENCHMARK_DOCS: u64 = 1_000_000;
    IndexLimits::new()
        .with_max_pending_docs(MAX_BENCHMARK_DOCS)
        .with_max_pending_bytes(512 * 1024 * 1024)
        .with_max_replay_entries(MAX_BENCHMARK_DOCS)
        .with_max_replay_bytes(512 * 1024 * 1024)
}

fn parse_args() -> Result<(PathBuf, u64), String> {
    let mut args = std::env::args().skip(1);
    let mut index_dir: Option<PathBuf> = None;
    let mut n: Option<u64> = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--index-dir" => {
                index_dir = Some(PathBuf::from(args.next().ok_or("missing --index-dir value")?));
            }
            "--n" => {
                let value = args.next().ok_or("missing --n value")?;
                let parsed: u64 = value.parse().map_err(|_| format!("invalid --n {value}"))?;
                if !N_VALUES.contains(&parsed) {
                    return Err(format!("--n must be one of {N_VALUES:?}"));
                }
                n = Some(parsed);
            }
            other => return Err(format!("unexpected argument {other}")),
        }
    }
    let index_dir = index_dir.ok_or("--index-dir is required")?;
    if !index_dir.is_absolute() {
        return Err("--index-dir must be absolute".to_owned());
    }
    if !index_dir.is_dir() {
        return Err(format!("--index-dir does not exist: {}", index_dir.display()));
    }
    let n = n.ok_or("--n is required")?;
    Ok((index_dir, n))
}

fn run() -> Result<serde_json::Value, String> {
    let (index_dir, expected) = parse_args()?;
    let directory: Arc<dyn Directory> =
        Arc::new(FsDirectory::open(Path::new(&index_dir)).map_err(|e| e.to_string())?);
    let started = Instant::now();
    let index = Index::open_with_limits(
        directory,
        schema(),
        AnalyzerRegistry::builtin(),
        benchmark_limits(),
    )
    .map_err(|e| e.to_string())?;
    let snapshot = index.snapshot();
    let open_ns = started.elapsed().as_nanos() as u64;
    if open_ns == 0 {
        return Err("zero open_ns".to_owned());
    }
    let generation = index.generation().ok_or("missing generation")?;
    let documents = snapshot.stored_keys().map_err(|e| e.to_string())?.len() as u64;
    if documents != expected {
        return Err(format!("reopened {documents} documents, expected {expected}"));
    }
    Ok(json!({
        "schema": SCHEMA,
        "open_ns": open_ns,
        "generation": generation,
        "documents": documents,
    }))
}

fn main() {
    match run() {
        Ok(value) => {
            println!("{value}");
        }
        Err(error) => {
            eprintln!("pr15i-a-reopen-probe: {error}");
            std::process::exit(3);
        }
    }
}
