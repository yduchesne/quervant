//! PR15D/BM-10 Tantivy adapter (pin `tantivy = "=0.25.0"`).
//!
//! The index is always created and reopened through an on-disk
//! `MmapDirectory`; never `create_in_ram`. The native string FAST field
//! `doc_id` is indexed as an exact keyword, stored for projection and sorted
//! lexicographically ascending. Never substitute a numeric ordinal surrogate.
//!
//! `engine_ns` wraps only the public Tantivy search calls: the exhaustive
//! `Count` collector for exact `total_hits` plus the sorted `TopDocs` collection.
//! Process start, index open, TSV parsing and JSON serialization are outside
//! the timer; stored-field materialization is part of engine_ns. On the first
//! query of a session, index_open_ns separately times index/reader open/reload
//! and is excluded from the search-only engine_ns measurement.

use std::fs;
use std::io::{self, BufRead, Write};
use std::path::Path;
use std::time::Instant;

use serde_json::{json, Value};
use tantivy::collector::{Count, TopDocs};
use tantivy::query::TermQuery;
use tantivy::schema::{
    Field, IndexRecordOption, Schema, TextOptions, Value as TantivyValue, FAST, STORED, STRING,
};
use tantivy::{Index, IndexReader, IndexWriter, Order, TantivyDocument, Term};

const SCHEMA: &str = "pr15d-adapter-v1";
const ENGINE: &str = "tantivy";
const ENGINE_VERSION: &str = "tantivy 0.25.0";
const ANALYZER: &str = "keyword-exact";
const HEADER: &str = "doc_id\tkey\tgroup\tbody\tpayload";
const WRITER_MEMORY_BUDGET: usize = 64 * 1024 * 1024;

#[derive(Debug)]
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

#[derive(Clone, Copy)]
struct Fields {
    doc_id: Field,
    key: Field,
    group: Field,
}

impl Fields {
    fn from_schema(schema: &Schema) -> Result<Self, AdapterError> {
        let field = |name: &str| {
            schema
                .get_field(name)
                .map_err(|_| AdapterError::new("schema", format!("missing field {name}")))
        };
        Ok(Self {
            doc_id: field("doc_id")?,
            key: field("key")?,
            group: field("group")?,
        })
    }
}

fn schema() -> Schema {
    let mut builder = Schema::builder();
    // Exact, un-tokenized identifiers. `STRING` uses the no-tokenizer so a
    // `TermQuery` matches the complete field value byte-for-byte.
    // Native lexical order by the actual identifier, matching Quervant's
    // Keyword and Lucene's SortedDocValuesField.
    builder.add_text_field("doc_id", STRING | STORED | FAST);
    builder.add_text_field("key", STRING | STORED);
    builder.add_text_field("group", STRING | STORED);
    // Stored only: never searched or sorted in the mandatory lane.
    builder.add_text_field("body", TextOptions::default().set_stored());
    builder.add_text_field("payload", TextOptions::default().set_stored());
    builder.build()
}

struct CorpusRow {
    doc_id: String,
    key: String,
    group: String,
    body: String,
    payload: String,
}

fn parse_tsv(path: &Path) -> Result<Vec<CorpusRow>, AdapterError> {
    let text = fs::read_to_string(path)
        .map_err(|error| AdapterError::new("corpus_unreadable", error.to_string()))?;
    let mut lines = text.split('\n');
    match lines.next() {
        Some(header) if header == HEADER => {}
        _ => return Err(AdapterError::new("corpus_header", "unexpected TSV header")),
    }
    let mut rows = Vec::new();
    let mut previous_doc_id: Option<String> = None;
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
        if previous_doc_id
            .as_deref()
            .is_some_and(|previous| doc_id <= previous)
        {
            return Err(AdapterError::new(
                "corpus_order",
                format!("line {}: doc_id not strictly increasing", offset + 2),
            ));
        }
        previous_doc_id = Some(doc_id.to_owned());
        rows.push(CorpusRow {
            doc_id: doc_id.to_owned(),
            key: columns[1].to_owned(),
            group: columns[2].to_owned(),
            body: columns[3].to_owned(),
            payload: columns[4].to_owned(),
        });
    }
    Ok(rows)
}

fn make_document(
    doc_id: Field,
    key: Field,
    group: Field,
    body: Field,
    payload: Field,
    row: CorpusRow,
) -> TantivyDocument {
    let mut document = TantivyDocument::new();
    document.add_text(doc_id, row.doc_id);
    document.add_text(key, row.key);
    document.add_text(group, row.group);
    document.add_text(body, row.body);
    document.add_text(payload, row.payload);
    document
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

fn positive(value: u128, field: &'static str) -> Result<u64, AdapterError> {
    if value == 0 || value > u128::from(u64::MAX) {
        return Err(AdapterError::new(
            "duration",
            format!("{field} is not a positive integer nanosecond count"),
        ));
    }
    Ok(value as u64)
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
    let rows = parse_tsv(Path::new(corpus_path))?;
    let expected = rows.len();
    if expected == 0 {
        return Err(AdapterError::new("corpus_empty", "no documents"));
    }

    let schema = schema();
    let fields = Fields::from_schema(&schema)?;
    let body = schema
        .get_field("body")
        .map_err(|_| AdapterError::new("schema", "missing body"))?;
    let payload = schema
        .get_field("payload")
        .map_err(|_| AdapterError::new("schema", "missing payload"))?;

    fs::create_dir_all(index_dir)
        .map_err(|error| AdapterError::new("index_create", error.to_string()))?;
    if Path::new(index_dir).exists()
        && fs::read_dir(index_dir)
            .map_err(|error| AdapterError::new("index_create", error.to_string()))?
            .next()
            .is_some()
    {
        return Err(AdapterError::new(
            "index_create",
            "index directory must be empty",
        ));
    }

    // On-disk MmapDirectory through the public `create_in_dir` constructor.
    let index = Index::create_in_dir(index_dir, schema.clone())
        .map_err(|error| AdapterError::new("index_create", error.to_string()))?;
    let mut writer: IndexWriter<TantivyDocument> = index
        .writer(WRITER_MEMORY_BUDGET)
        .map_err(|error| AdapterError::new("writer", error.to_string()))?;

    // Document construction is preparation, not ingestion. It must be completed
    // before the timer starts, exactly as Quervant builds its owned documents and
    // Lucene builds its Document list before timing.
    let documents: Vec<TantivyDocument> = rows
        .into_iter()
        .map(|row| {
            make_document(
                fields.doc_id,
                fields.key,
                fields.group,
                body,
                payload,
                row,
            )
        })
        .collect();

    let insert_started = Instant::now();
    for document in documents {
        writer
            .add_document(document)
            .map_err(|error| AdapterError::new("insert", error.to_string()))?;
    }
    let index_ns = insert_started.elapsed().as_nanos();

    let commit_started = Instant::now();
    writer
        .commit()
        .map_err(|error| AdapterError::new("commit", error.to_string()))?;
    let commit_ns = commit_started.elapsed().as_nanos();
    drop(writer);

    let reopen_started = Instant::now();
    let reopened = Index::open_in_dir(index_dir)
        .map_err(|error| AdapterError::new("reopen", error.to_string()))?;
    let reader = reopened
        .reader()
        .map_err(|error| AdapterError::new("reopen", error.to_string()))?;
    let verified = reader.searcher().num_docs();
    let reopen_ns = reopen_started.elapsed().as_nanos();
    if verified != expected as u64 {
        return Err(AdapterError::new(
            "verification",
            format!("reopened {verified} documents, expected {expected}"),
        ));
    }
    let index_bytes = directory_bytes(Path::new(index_dir))?;
    let segment_count = reopened
        .searchable_segment_ids()
        .map_err(|error| AdapterError::new("reopen", error.to_string()))?
        .len();

    Ok(json!({
        "documents_indexed": expected,
        "documents_verified": verified,
        "index_ns": positive(index_ns, "index_ns")?,
        "commit_ns": positive(commit_ns, "commit_ns")?,
        "reopen_ns": positive(reopen_ns, "reopen_ns")?,
        "index_bytes": index_bytes,
        "segment_count": segment_count.max(1),
    }))
}

struct Opened {
    reader: IndexReader,
    fields: Fields,
}

fn open_index(index_dir: &str) -> Result<Opened, AdapterError> {
    let index = Index::open_in_dir(index_dir)
        .map_err(|error| AdapterError::new("index_open", error.to_string()))?;
    let fields = Fields::from_schema(&index.schema())?;
    let reader = index
        .reader()
        .map_err(|error| AdapterError::new("index_open", error.to_string()))?;
    reader
        .reload()
        .map_err(|error| AdapterError::new("index_open", error.to_string()))?;
    Ok(Opened { reader, fields })
}

fn handle_query(opened: &Opened, request: &Value) -> Result<Value, AdapterError> {
    let field_name = request
        .get("field")
        .and_then(Value::as_str)
        .ok_or_else(|| AdapterError::new("request", "query requires field"))?;
    let field = match field_name {
        "key" => opened.fields.key,
        "group" => opened.fields.group,
        _ => {
            return Err(AdapterError::new(
                "request",
                "mandatory lane only searches key/group",
            ));
        }
    };
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

    let searcher = opened.reader.searcher();
    let query = TermQuery::new(Term::from_field_text(field, term), IndexRecordOption::Basic);
    let top_collector = TopDocs::with_limit(k).order_by_string_fast_field("doc_id", Order::Asc);

    let started = Instant::now();
    let total_hits = searcher
        .search(&query, &Count)
        .map_err(|error| AdapterError::new("search", error.to_string()))?;
    let top = searcher
        .search(&query, &top_collector)
        .map_err(|error| AdapterError::new("search", error.to_string()))?;

    // Stored-field decoding is part of the measured engine operation, matching
    // the Quervant and Lucene adapters.
    let mut doc_ids = Vec::with_capacity(top.len());
    for (_sort_value, address) in &top {
        let document: TantivyDocument = searcher
            .doc(*address)
            .map_err(|error| AdapterError::new("projection", error.to_string()))?;
        let doc_id = document
            .get_first(opened.fields.doc_id)
            .and_then(|value| value.as_value().as_str().map(str::to_owned))
            .ok_or_else(|| {
                AdapterError::new("projection", "hit is missing the stored doc_id")
            })?;
        doc_ids.push(doc_id);
    }
    let engine_ns = positive(started.elapsed().as_nanos(), "engine_ns")?;
    // Compare native FAST sort strings with stored doc_ids after timing,
    // without allocating a second result vector inside engine_ns.
    if top.iter().zip(&doc_ids).any(|((sort_key, _address), doc_id)| {
        sort_key.as_str() != doc_id.as_str()
    }) {
        return Err(AdapterError::new(
            "ordering",
            "native doc_id string sort key disagrees with stored doc_id",
        ));
    }
    if doc_ids.len() != k.min(total_hits) {
        return Err(AdapterError::new(
            "count",
            format!(
                "returned {} hits for k={k}, total={total_hits}",
                doc_ids.len()
            ),
        ));
    }
    if !doc_ids.windows(2).all(|pair| pair[0] < pair[1]) {
        return Err(AdapterError::new(
            "ordering",
            "engine returned doc_ids outside ascending order",
        ));
    }
    Ok(json!({
        "doc_ids": doc_ids,
        "total_hits": u64::try_from(total_hits)
            .map_err(|error| AdapterError::new("count", error.to_string()))?,
        "engine_ns": engine_ns,
    }))
}

/// Open the index/reader on the first query, reporting the opening duration
/// once, independently from the query-only engine_ns clock.
fn handle_session_query(
    opened: &mut Option<Opened>,
    index_dir: &str,
    request: &Value,
) -> Result<Value, AdapterError> {
    let opened_ns = if opened.is_none() {
        let started = Instant::now();
        *opened = Some(open_index(index_dir)?);
        Some(positive(started.elapsed().as_nanos(), "index_open_ns")?)
    } else {
        None
    };
    let mut result = handle_query(opened.as_ref().expect("index opened"), request)?;
    if let Some(duration) = opened_ns {
        result
            .as_object_mut()
            .expect("query response is a JSON object")
            .insert("index_open_ns".into(), json!(duration));
    }
    Ok(result)
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
        eprintln!("pr15d-tantivy-adapter: {error}");
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

    let mut opened: Option<Opened> = None;
    let mut active_index_dir = index_dir.clone();
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    for line in stdin.lock().lines() {
        let line = line.map_err(|error| AdapterError::new("protocol", error.to_string()))?;
        if line.trim().is_empty() {
            continue;
        }
        let request: Value = serde_json::from_str(&line).map_err(|error| {
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
                        opened = None;
                    }
                }
                result
            }
            "query" => {
                let path = active_index_dir.as_deref().ok_or_else(|| {
                    AdapterError::new("request", "query mode requires --index-dir")
                })?;
                handle_session_query(&mut opened, path, &request)
            }
            "metadata" => Ok(json!({
                "engine_version": ENGINE_VERSION,
                "adapter_version": env!("CARGO_PKG_VERSION"),
                "analyzer": ANALYZER,
                "index_backend": "MmapDirectory",
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

#[cfg(test)]
mod session_timing_tests {
    use super::*;

    #[test]
    fn first_query_reports_open_time_once_and_search_time_is_independent() {
        let root = std::env::temp_dir().join(format!(
            "pr15d-tantivy-open-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        fs::create_dir_all(&root).expect("fixture root");
        let corpus = root.join("corpus.tsv");
        let index = root.join("index");
        let mut rows = String::from(HEADER);
        rows.push('\n');
        for i in 0..16 {
            rows.push_str(&format!(
                "d{i:08}\tcommon\tmedium\tbody\tpayload-{i}\n"
            ));
        }
        fs::write(&corpus, rows).expect("fixture corpus");
        let built = handle_build(&json!({
            "request_id":"build", "op":"build",
            "corpus_path":corpus.to_str().expect("utf-8 corpus"),
            "index_dir":index.to_str().expect("utf-8 index")
        }));
        built.expect("fixture index build");
        let mut session = None;
        let request = json!({
            "request_id":"q", "op":"query", "field":"group",
            "term":"medium", "k":10, "mode":"warm"
        });
        let path = index.to_str().expect("utf-8");
        let first = handle_session_query(&mut session, path, &request).expect("first");
        assert!(first["index_open_ns"].as_u64().is_some_and(|n| n > 0));
        assert!(first["engine_ns"].as_u64().is_some_and(|n| n > 0));
        let next = handle_session_query(&mut session, path, &request).expect("reused");
        assert!(next.get("index_open_ns").is_none());
        assert_eq!(first["doc_ids"], next["doc_ids"]);
        session = None;
        let reopened = handle_session_query(&mut session, path, &request).expect("reopen");
        assert!(reopened["index_open_ns"].as_u64().is_some_and(|n| n > 0));
        drop(session);
        fs::remove_dir_all(root).expect("fixture cleanup");
    }
    #[test]
    fn native_doc_id_sort_is_lexical_not_numeric() {
        // The prior ordinal surrogate ordered d2 before d10.
        let root = std::env::temp_dir().join(format!(
            "pr15d-tantivy-lex-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        fs::create_dir_all(&root).expect("fixture root");
        let corpus = root.join("lex-corpus.tsv");
        let index = root.join("lex-index");
        let mut rows = String::from(HEADER);
        rows.push('\n');
        for id in ["d1", "d10", "d2", "d20"] {
            rows.push_str(&format!("{id}\tcommon\tmedium\tbody\tpayload\n"));
        }
        fs::write(&corpus, rows).expect("fixture corpus");
        handle_build(&json!({
            "request_id": "build", "op": "build",
            "corpus_path": corpus.to_str().expect("utf8 corpus"),
            "index_dir": index.to_str().expect("utf8 index")
        }))
        .expect("fixture build");
        let mut session = None;
        let request = json!({
            "request_id": "q", "op": "query", "field": "group",
            "term": "medium", "k": 2, "mode": "warm"
        });
        let first = handle_session_query(
            &mut session, index.to_str().expect("utf8"), &request
        ).expect("first query");
        assert_eq!(first["total_hits"], 4);
        assert_eq!(first["doc_ids"], json!(["d1", "d10"]));
        assert!(first["index_open_ns"].as_u64().is_some_and(|ns| ns > 0));
        let all = handle_session_query(
            &mut session, index.to_str().expect("utf8"),
            &json!({
                "request_id": "all", "op": "query", "field": "group",
                "term": "medium", "k": 4, "mode": "warm"
            })
        ).expect("all hits");
        assert_eq!(all["doc_ids"], json!(["d1", "d10", "d2", "d20"]));
        assert!(all.get("index_open_ns").is_none());
        assert!(schema().get_field("ordinal").is_err(), "numeric ordinal field must not exist");
        drop(session);
        fs::remove_dir_all(root).expect("fixture cleanup");
    }

    #[test]
    fn native_doc_id_sort_orders_across_immutable_segments() {
        let root = std::env::temp_dir().join(format!(
            "pr15d-tantivy-multiseg-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        fs::create_dir_all(&root).expect("fixture root");
        let index_dir = root.join("index");
        fs::create_dir_all(&index_dir).expect("index directory");
        let schema = schema();
        let fields = Fields::from_schema(&schema).expect("schema fields");
        let body = schema.get_field("body").expect("body");
        let payload = schema.get_field("payload").expect("payload");
        let index = Index::create_in_dir(&index_dir, schema).expect("create index");
        let mut writer: IndexWriter<TantivyDocument> =
            index.writer(WRITER_MEMORY_BUDGET).expect("writer");
        writer.set_merge_policy(Box::new(tantivy::indexer::NoMergePolicy));
        for partition in [["d2", "d20"], ["d1", "d10"]] {
            for id in partition {
                writer.add_document(make_document(
                    fields.doc_id, fields.key, fields.group, body, payload,
                    CorpusRow {
                        doc_id: id.to_owned(),
                        key: "common".into(),
                        group: "medium".into(),
                        body: "body".into(),
                        payload: "payload".into(),
                    },
                )).expect("add document");
            }
            writer.commit().expect("commit segment");
        }
        drop(writer);
        let opened = open_index(index_dir.to_str().expect("utf8")).expect("open reader");
        assert!(
            opened.reader.searcher().segment_readers().len() >= 2,
            "must actually exercise cross-segment sorting"
        );
        let response = handle_query(&opened, &json!({
            "request_id": "q", "op": "query", "field": "group",
            "term": "medium", "k": 3, "mode": "warm"
        })).expect("cross-segment query");
        assert_eq!(response["total_hits"], 4);
        assert_eq!(response["doc_ids"], json!(["d1", "d10", "d2"]));
        drop(opened);
        fs::remove_dir_all(root).expect("fixture cleanup");
    }

}
