//! PR15D benchmark-only Quervant adapter.
//!
//! This binary uses **public** `quervant-core` APIs only: `FsDirectory`,
//! `Index`, `IndexWriter::commit`, `Index::open_existing`, and
//! `UnifiedSearcher`. It never touches production source, private modules or
//! `MemoryDirectory`/RustFS.
//!
//! Protocol: one UTF-8 JSON request per stdin line, one JSON response per stdout
//! line. `engine_ns` is measured with `std::time::Instant` around the named
//! public engine operation only; process start, index open, TSV parsing, oracle
//! work and JSON serialization are outside the timer.

use std::fs;
use std::io::{self, BufRead, Write};
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory};
use serde_json::{Value, json};

const SCHEMA: &str = "pr15d-adapter-v1";
const ENGINE: &str = "quervant";
/// Kept in lockstep with `crates/quervant-core/Cargo.toml`. The authoritative
/// identity remains the recorded source SHA and lockfile hash.
const ENGINE_VERSION: &str = "quervant-core 0.1.0";
const ANALYZER: &str = "keyword-exact";
const HEADER: &str = "doc_id\tkey\tgroup\tbody\tpayload";

struct AdapterError {
    kind: &'static str,
    message: String,
}

impl AdapterError {
    fn new(kind: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for AdapterError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.kind, self.message)
    }
}

fn schema() -> Schema {
    Schema::new(
        vec![
            // Sortable exact identifier: indexed + stored + columnar.
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
            // Stored only: the mandatory lane never searches body or payload.
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

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// Benchmark-only bounded resource policy. The production defaults cap
/// uncommitted pending documents at 10,000, which is below the frozen 100,000
/// row workload. This raises only operational resource limits; query, term,
/// ordering and scoring semantics are unchanged.
fn benchmark_limits() -> IndexLimits {
    const MAX_BENCHMARK_DOCS: u64 = 1_000_000;
    IndexLimits::new()
        .with_max_pending_docs(MAX_BENCHMARK_DOCS)
        .with_max_pending_bytes(512 * 1024 * 1024)
        .with_max_replay_entries(MAX_BENCHMARK_DOCS)
        .with_max_replay_bytes(512 * 1024 * 1024)
}

fn parse_tsv(path: &Path) -> Result<Vec<Document>, AdapterError> {
    let text = fs::read_to_string(path)
        .map_err(|error| AdapterError::new("corpus_unreadable", error.to_string()))?;
    let mut lines = text.split('\n');
    match lines.next() {
        Some(header) if header == HEADER => {}
        _ => {
            return Err(AdapterError::new("corpus_header", "unexpected TSV header"));
        }
    }
    let mut documents = Vec::new();
    let mut previous: Option<String> = None;
    for (offset, line) in lines.enumerate() {
        if line.is_empty() {
            continue;
        }
        let columns: Vec<&str> = line.split('\t').collect();
        if columns.len() != 5 {
            return Err(AdapterError::new(
                "corpus_row",
                format!("line {}: expected 5 columns", offset + 2),
            ));
        }
        let doc_id = columns[0];
        if previous.as_deref().is_some_and(|value| doc_id <= value) {
            return Err(AdapterError::new(
                "corpus_order",
                format!("line {}: doc_id not strictly increasing", offset + 2),
            ));
        }
        previous = Some(doc_id.to_owned());
        let key = DocumentKey::new(doc_id)
            .map_err(|error| AdapterError::new("corpus_key", error.to_string()))?;
        let mut document = Document::new(key);
        for (name, value) in [
            ("doc_id", columns[0]),
            ("key", columns[1]),
            ("group", columns[2]),
            ("body", columns[3]),
            ("payload", columns[4]),
        ] {
            document
                .insert(
                    name,
                    FieldValues::Single(FieldValue::Keyword(value.to_owned())),
                )
                .map_err(|error| AdapterError::new("corpus_field", error.to_string()))?;
        }
        documents.push(document);
    }
    Ok(documents)
}

fn directory_bytes(path: &Path) -> Result<u64, AdapterError> {
    let mut total = 0u64;
    let mut stack = vec![path.to_path_buf()];
    while let Some(current) = stack.pop() {
        let entries = fs::read_dir(&current)
            .map_err(|error| AdapterError::new("index_unreadable", error.to_string()))?;
        for entry in entries {
            let entry =
                entry.map_err(|error| AdapterError::new("index_unreadable", error.to_string()))?;
            let metadata = entry
                .metadata()
                .map_err(|error| AdapterError::new("index_unreadable", error.to_string()))?;
            if metadata.is_dir() {
                stack.push(entry.path());
            } else if metadata.is_file() {
                total += metadata.len();
            }
        }
    }
    Ok(total)
}

fn handle_build(request: &Value) -> Result<Value, AdapterError> {
    let corpus_path = request
        .get("corpus_path")
        .and_then(Value::as_str)
        .ok_or_else(|| AdapterError::new("request", "build requires corpus_path"))?;
    let index_dir = request
        .get("index_dir")
        .and_then(Value::as_str)
        .ok_or_else(|| AdapterError::new("request", "build requires index_dir"))?;

    // Parse the complete corpus and resolve all documents before the timer.
    let documents = parse_tsv(Path::new(corpus_path))?;
    let expected = documents.len();

    let directory: Arc<dyn Directory> = Arc::new(
        FsDirectory::open(index_dir)
            .map_err(|error| AdapterError::new("index_create", error.to_string()))?,
    );
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        benchmark_limits(),
    )
    .map_err(|error| AdapterError::new("index_create", error.to_string()))?;
    let mut writer = index
        .writer()
        .map_err(|error| AdapterError::new("writer", error.to_string()))?;

    let insert_started = Instant::now();
    for document in documents {
        writer
            .insert(document)
            .map_err(|error| AdapterError::new("insert", error.to_string()))?;
    }
    let index_ns = insert_started.elapsed().as_nanos();

    let commit_started = Instant::now();
    let commit = writer
        .commit()
        .map_err(|error| AdapterError::new("commit", error.to_string()))?;
    let commit_ns = commit_started.elapsed().as_nanos();
    writer
        .close()
        .map_err(|error| AdapterError::new("writer_close", error.to_string()))?;

    let reopen_started = Instant::now();
    let reopened = Index::open_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        benchmark_limits(),
    )
    .map_err(|error| AdapterError::new("reopen", error.to_string()))?;
    let snapshot = reopened.snapshot();
    let reopen_ns = reopen_started.elapsed().as_nanos();

    let verified = snapshot.document_count();
    if verified != expected as u64 || commit.documents != expected as u64 {
        return Err(AdapterError::new(
            "verification",
            format!(
                "reopened {verified} documents, commit {} and parsed {expected}",
                commit.documents
            ),
        ));
    }
    let index_bytes = directory_bytes(Path::new(index_dir))?;

    Ok(json!({
        "documents_indexed": expected,
        "documents_verified": verified,
        "index_ns": positive(index_ns, "index_ns")?,
        "commit_ns": positive(commit_ns, "commit_ns")?,
        "reopen_ns": positive(reopen_ns, "reopen_ns")?,
        "index_bytes": index_bytes,
        "segment_count": snapshot.segment_count(),
    }))
}

fn positive(value: u128, field: &'static str) -> Result<u64, AdapterError> {
    if value == 0 || value > u128::from(u64::MAX) {
        return Err(AdapterError::new(
            "duration",
            format!("{field} is not a positive integer nanosecond count"),
        ));
    }
    Ok(value as u64)
}

fn projected_doc_id(hit: &quervant_core::search::ProjectedHit) -> Option<String> {
    for (name, values) in &hit.fields {
        if name == "doc_id" {
            if let Some(FieldValue::Keyword(value)) = values.values().next() {
                return Some(value.clone());
            }
        }
    }
    None
}

fn search(
    index: &Index,
    field: &str,
    term: &str,
    k: usize,
) -> Result<(Vec<String>, u64, u64), AdapterError> {
    let snapshot = index.snapshot();
    let request = UnifiedRequest {
        query: Query::Term {
            field: field.to_owned(),
            value: FieldValue::Keyword(term.to_owned()),
        },
        sort: Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]),
        top_k: TopK::new(k).map_err(|error| AdapterError::new("request", error.to_string()))?,
        projection: Projection::Fields(vec!["doc_id".to_owned()]),
        after: None,
    };
    let adapter_schema = schema();
    let adapter_registry = registry();
    let searcher = UnifiedSearcher::new(
        snapshot.as_ref(),
        &adapter_schema,
        &adapter_registry,
        SearchLimits::default(),
    );

    let started = Instant::now();
    let response = searcher
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .map_err(|error| AdapterError::new("search", error.to_string()))?;

    let mut doc_ids = Vec::with_capacity(response.hits.len());
    for hit in &response.hits {
        let doc_id = projected_doc_id(hit).ok_or_else(|| {
            AdapterError::new("projection", "hit is missing the projected doc_id")
        })?;
        if doc_id != hit.key.as_str() {
            return Err(AdapterError::new(
                "projection",
                "projected doc_id differs from the logical document key",
            ));
        }
        doc_ids.push(doc_id);
    }
    // The measured engine operation is the search plus materialising every
    // returned doc_id into an owned collection, matching the Tantivy and Lucene
    // adapters. Ordering and count sanity checks below stay outside the timer.
    let engine_ns = positive(started.elapsed().as_nanos(), "engine_ns")?;
    let sorted = doc_ids.windows(2).all(|pair| pair[0] < pair[1]);
    if !sorted {
        return Err(AdapterError::new(
            "ordering",
            "engine returned doc_ids outside ascending order",
        ));
    }
    Ok((doc_ids, response.total_hits, engine_ns))
}

fn handle_query(index: &Index, request: &Value) -> Result<Value, AdapterError> {
    let field = request
        .get("field")
        .and_then(Value::as_str)
        .ok_or_else(|| AdapterError::new("request", "query requires field"))?;
    if field != "key" && field != "group" {
        return Err(AdapterError::new(
            "request",
            "mandatory lane only searches key/group",
        ));
    }
    let term = request
        .get("term")
        .and_then(Value::as_str)
        .ok_or_else(|| AdapterError::new("request", "query requires term"))?;
    let k = request
        .get("k")
        .and_then(Value::as_u64)
        .ok_or_else(|| AdapterError::new("request", "query requires positive k"))?;
    let k = usize::try_from(k).map_err(|error| AdapterError::new("request", error.to_string()))?;
    if k == 0 {
        return Err(AdapterError::new("request", "k must be positive"));
    }
    let (doc_ids, total_hits, engine_ns) = search(index, field, term, k)?;
    Ok(json!({
        "doc_ids": doc_ids,
        "total_hits": total_hits,
        "engine_ns": engine_ns,
    }))
}

fn response(request_id: &str, status: &str, mut body: Value) -> Value {
    let object = body
        .as_object_mut()
        .expect("response body must be an object");
    object.insert("schema".into(), json!(SCHEMA));
    object.insert("engine".into(), json!(ENGINE));
    object.insert("request_id".into(), json!(request_id));
    object.insert("status".into(), json!(status));
    body
}

fn main() {
    if let Err(error) = run() {
        eprintln!("pr15d-quervant-adapter: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), AdapterError> {
    let mut index_dir: Option<String> = None;
    let mut arguments = std::env::args().skip(1);
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--index-dir" => {
                index_dir = arguments.next();
                if index_dir.is_none() {
                    return Err(AdapterError::new("cli", "--index-dir requires a value"));
                }
            }
            other => {
                return Err(AdapterError::new(
                    "cli",
                    format!("unknown argument: {other}"),
                ));
            }
        }
    }

    let mut opened: Option<Index> = None;
    let mut active_index_dir = index_dir.clone();
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    for line in stdin.lock().lines() {
        let line = line.map_err(|error| AdapterError::new("protocol", error.to_string()))?;
        if line.trim().is_empty() {
            continue;
        }
        let request: Value = serde_json::from_str(&line).map_err(|error| {
            // Malformed JSON is a terminal protocol failure; never a zero-hit success.
            AdapterError::new("protocol", format!("malformed request JSON: {error}"))
        })?;
        let request_id = request
            .get("request_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let op = request.get("op").and_then(Value::as_str).unwrap_or("");

        let result: Result<Value, AdapterError> = match op {
            "build" => {
                let result = handle_build(&request);
                if result.is_ok() {
                    if let Some(dir) = request.get("index_dir").and_then(Value::as_str) {
                        active_index_dir = Some(dir.to_owned());
                    }
                }
                result
            }
            "query" => {
                let index = match &opened {
                    Some(index) => index,
                    None => {
                        let path = active_index_dir.as_deref().ok_or_else(|| {
                            AdapterError::new("request", "query mode requires --index-dir")
                        })?;
                        let opened_index = Index::open_with_limits(
                            Arc::new(FsDirectory::open(path).map_err(|error| {
                                AdapterError::new("index_open", error.to_string())
                            })?),
                            schema(),
                            registry(),
                            benchmark_limits(),
                        )
                        .map_err(|error| AdapterError::new("index_open", error.to_string()))?;
                        opened = Some(opened_index);
                        opened.as_ref().expect("just inserted")
                    }
                };
                handle_query(index, &request)
            }
            "metadata" => Ok(json!({
                "engine_version": ENGINE_VERSION,
                "adapter_version": env!("CARGO_PKG_VERSION"),
                "analyzer": ANALYZER,
                "schema": schema().field_count(),
                "index_backend": "FsDirectory",
            })),
            "shutdown" => {
                let reply = response(&request_id, "ok", json!({}));
                writeln!(stdout, "{reply}")
                    .map_err(|error| AdapterError::new("protocol", error.to_string()))?;
                stdout
                    .flush()
                    .map_err(|error| AdapterError::new("protocol", error.to_string()))?;
                return Ok(());
            }
            other => Err(AdapterError::new("request", format!("unknown op: {other}"))),
        };

        let reply = match result {
            Ok(body) => response(&request_id, "ok", body),
            Err(error) => response(
                &request_id,
                "error",
                json!({"error": {"kind": error.kind, "message": error.message}}),
            ),
        };
        writeln!(stdout, "{reply}")
            .map_err(|error| AdapterError::new("protocol", error.to_string()))?;
        stdout
            .flush()
            .map_err(|error| AdapterError::new("protocol", error.to_string()))?;
        if reply.get("status").and_then(Value::as_str) == Some("error") {
            std::process::exit(1);
        }
    }
    Ok(())
}
