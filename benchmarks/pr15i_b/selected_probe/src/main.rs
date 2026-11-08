//! PR 15I-B benchmark-only projected selected-read probe.
//!
//! Opens a local index through public APIs and times `UnifiedSearcher` with a
//! stored-field projection, which exercises the STORED selected-read path.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::Cardinality;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory};
use serde_json::json;

const SCHEMA: &str = "pr15i-b-selected-probe-v1";

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new("doc_id", FieldType::Keyword, Cardinality::Single, FieldOptions::new(true, true, true)),
            FieldDefinition::new("key", FieldType::Keyword, Cardinality::Single, FieldOptions::new(true, true, false)),
            FieldDefinition::new("group", FieldType::Keyword, Cardinality::Single, FieldOptions::new(true, true, false)),
            FieldDefinition::new("body", FieldType::Keyword, Cardinality::Single, FieldOptions::new(false, true, false)),
            FieldDefinition::new("payload", FieldType::Keyword, Cardinality::Single, FieldOptions::new(false, true, false)),
        ],
        None,
    )
    .expect("schema")
}

fn limits() -> IndexLimits {
    IndexLimits::new()
        .with_max_pending_docs(1_000_000)
        .with_max_pending_bytes(512 * 1024 * 1024)
        .with_max_replay_entries(1_000_000)
        .with_max_replay_bytes(512 * 1024 * 1024)
}

fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 6 || args[0] != "run" {
        return Err("usage: run --index-dir <abs> --k <1|10|100> --out <abs>".to_owned());
    }
    let mut index_dir = None;
    let mut k = None;
    let mut out = None;
    let mut cursor = 1;
    while cursor < args.len() {
        match args[cursor].as_str() {
            "--index-dir" => index_dir = Some(PathBuf::from(&args[cursor + 1])),
            "--k" => k = Some(args[cursor + 1].parse::<usize>().map_err(|_| "invalid --k".to_owned())?),
            "--out" => out = Some(PathBuf::from(&args[cursor + 1])),
            other => return Err(format!("unexpected argument {other}")),
        }
        cursor += 2;
    }
    let index_dir = index_dir.ok_or("--index-dir required")?;
    let k = k.ok_or("--k required")?;
    let out = out.ok_or("--out required")?;
    if !index_dir.is_absolute() || !out.is_absolute() {
        return Err("paths must be absolute".to_owned());
    }
    if !index_dir.is_dir() {
        return Err("--index-dir does not exist".to_owned());
    }
    let directory: Arc<dyn Directory> =
        Arc::new(FsDirectory::open(Path::new(&index_dir)).map_err(|e| e.to_string())?);
    let index = Index::open_with_limits(directory, schema(), AnalyzerRegistry::builtin(), limits())
        .map_err(|e| e.to_string())?;
    let snapshot = index.snapshot();
    let request = UnifiedRequest {
        query: Query::Term {
            field: "key".to_owned(),
            value: FieldValue::Keyword("common".to_owned()),
        },
        sort: quervant_core::contract::result::Sort::default(),
        top_k: TopK::new(k).map_err(|e| e.to_string())?,
        projection: Projection::Fields(vec!["doc_id".to_owned(), "body".to_owned(), "payload".to_owned()]),
        after: None,
    };
    let probe_schema = schema();
    let registry = AnalyzerRegistry::builtin();
    let searcher = UnifiedSearcher::new(
        snapshot.as_ref(),
        &probe_schema,
        &registry,
        SearchLimits::default(),
    );
    let started = Instant::now();
    let response = searcher
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .map_err(|e| e.to_string())?;
    let selected_ns = started.elapsed().as_nanos() as u64;
    if selected_ns == 0 {
        return Err("zero selected_ns".to_owned());
    }
    if response.hits.len() != k {
        return Err(format!("got {} hits, expected {k}", response.hits.len()));
    }
    let report = json!({
        "schema": SCHEMA,
        "k": k,
        "selected_ns": selected_ns,
        "hits": response.hits.len(),
        "total_hits": response.total_hits,
    });
    std::fs::write(&out, serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    println!("{report}");
    Ok(())
}
