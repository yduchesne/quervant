//! PR 15I-A benchmark-only real-RustFS cold-bootstrap probe.
//!
//! Uses **public** `quervant-core`/`quervant-objectstore` APIs only:
//! `RemoteIndex`, `S3ObjectStore`, `LexicalSearcher`. It never writes to the
//! production workspace and never fabricates query results.
//!
//! Modes:
//! ```text
//! prepare   --corpus <tsv> --prefix <p> --workspace <dir> [S3 flags]
//! bootstrap --prefix <p> --workspace <dir> --n 100000 [S3 flags]
//! ```
//!
//! Exactly one canonical JSON object is written to stdout.

use std::fs;
use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::IndexLimits;
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_objectstore::{S3Config, S3ObjectStore};
use serde_json::json;

const SCHEMA: &str = "pr15i-a-remote-probe-v1";
const MAX_BENCHMARK_DOCS: u64 = 1_000_000;

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

fn limits() -> IndexLimits {
    IndexLimits::new()
        .with_max_pending_docs(MAX_BENCHMARK_DOCS)
        .with_max_pending_bytes(512 * 1024 * 1024)
        .with_max_replay_entries(MAX_BENCHMARK_DOCS)
        .with_max_replay_bytes(512 * 1024 * 1024)
}

struct Args {
    mode: String,
    corpus: Option<String>,
    prefix: String,
    workspace: String,
    n: u64,
    endpoint: String,
    region: String,
    bucket: String,
    access: String,
    secret: String,
}

fn parse_args() -> Result<Args, String> {
    let mut mode = None;
    let mut corpus = None;
    let mut prefix = None;
    let mut workspace = None;
    let mut n = 100_000u64;
    let mut endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT").ok();
    let mut region = std::env::var("QUERVANT_RUSTFS_REGION").ok();
    let mut bucket = std::env::var("QUERVANT_RUSTFS_BUCKET").ok();
    let mut access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").ok();
    let mut secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY").ok();
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        let mut value = || args.next().ok_or_else(|| format!("missing value for {arg}"));
        match arg.as_str() {
            "prepare" | "bootstrap" => mode = Some(arg),
            "--corpus" => corpus = Some(value()?),
            "--prefix" => prefix = Some(value()?),
            "--workspace" => workspace = Some(value()?),
            "--n" => {
                n = value()?
                    .parse()
                    .map_err(|_| "invalid --n".to_owned())?;
            }
            "--endpoint" => endpoint = Some(value()?),
            "--region" => region = Some(value()?),
            "--bucket" => bucket = Some(value()?),
            "--access" => access = Some(value()?),
            "--secret" => secret = Some(value()?),
            other => return Err(format!("unexpected argument {other}")),
        }
    }
    Ok(Args {
        mode: mode.ok_or("mode (prepare|bootstrap) is required")?,
        corpus,
        prefix: prefix.ok_or("--prefix is required")?,
        workspace: workspace.ok_or("--workspace is required")?,
        n,
        endpoint: endpoint.ok_or("RustFS endpoint missing")?,
        region: region.unwrap_or_else(|| "us-east-1".to_owned()),
        bucket: bucket.ok_or("RustFS bucket missing")?,
        access: access.ok_or("RustFS access key missing")?,
        secret: secret.ok_or("RustFS secret key missing")?,
    })
}

fn document(line: &str) -> Result<Document, String> {
    let columns: Vec<&str> = line.split('\t').collect();
    if columns.len() != 5 {
        return Err(format!("expected 5 TSV columns, found {}", columns.len()));
    }
    let mut document = Document::new(DocumentKey::new(columns[0]).map_err(|e| e.to_string())?);
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
            .map_err(|e| e.to_string())?;
    }
    Ok(document)
}

async fn prepare(args: &Args, store: Arc<S3ObjectStore>) -> Result<serde_json::Value, String> {
    let corpus = args.corpus.as_ref().ok_or("prepare requires --corpus")?;
    let text = fs::read_to_string(corpus).map_err(|e| e.to_string())?;
    let mut lines = text.split('\n');
    let header = lines.next().ok_or("empty corpus")?;
    if header != "doc_id\tkey\tgroup\tbody\tpayload" {
        return Err(format!("unexpected corpus header {header:?}"));
    }
    let config = remote_config(args, "prepare");
    let index = RemoteIndex::create(store, config, schema(), AnalyzerRegistry::builtin(), limits())
        .await
        .map_err(|e| e.to_string())?;
    let mut writer = index.writer().await.map_err(|e| e.to_string())?;
    let mut documents = 0u64;
    for line in lines {
        if line.is_empty() {
            continue;
        }
        writer.insert(document(line)?).map_err(|e| e.to_string())?;
        documents += 1;
    }
    if documents != args.n {
        return Err(format!("read {documents} rows, expected {}", args.n));
    }
    writer.commit().await.map_err(|e| e.to_string())?;
    let generation = writer.generation();
    Ok(json!({
        "schema": SCHEMA,
        "mode": "prepare",
        "documents": documents,
        "generation": generation,
    }))
}

async fn bootstrap(args: &Args, store: Arc<S3ObjectStore>) -> Result<serde_json::Value, String> {
    let config = remote_config(args, "bootstrap");
    let started = Instant::now();
    let index = RemoteIndex::open_existing(
        store,
        config,
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .await
    .map_err(|e| e.to_string())?;
    let snapshot = index.snapshot();
    let response = LexicalSearcher::new(
        snapshot.as_ref(),
        &schema(),
        &AnalyzerRegistry::builtin(),
        SearchLimits::default(),
    )
    .search(
        &Query::MatchAll,
        TopK::new(10).map_err(|e| e.to_string())?,
        &Budgets::new(),
        &CancellationFlag::new(),
    )
    .map_err(|e| e.to_string())?;
    let open_ns = started.elapsed().as_nanos() as u64;
    if open_ns == 0 {
        return Err("zero open_ns".to_owned());
    }
    if response.total_hits != args.n {
        return Err(format!(
            "cold bootstrap returned {} hits, expected {}",
            response.total_hits, args.n
        ));
    }
    Ok(json!({
        "schema": SCHEMA,
        "mode": "bootstrap",
        "open_ns": open_ns,
        "generation": index.generation(),
        "documents": response.total_hits,
    }))
}

fn remote_config(args: &Args, suffix: &str) -> RemoteConfig {
    // The remote prefix identifies the authoritative generation; only the
    // disposable local workspace differs between modes/samples.
    let prefix = RemoteKeyPrefix::parse(args.prefix.clone()).expect("prefix");
    RemoteConfig::new(prefix, format!("{}/{}", args.workspace, suffix)).with_transfer(
        RemoteTransferConfig::default()
            .with_range_threshold(256 * 1024)
            .with_chunk_size(32 * 1024)
            .with_max_aggregate_response_bytes(2 * 1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16),
    )
}

fn main() {
    let result = (|| -> Result<serde_json::Value, String> {
        let args = parse_args()?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| e.to_string())?;
        runtime.block_on(async {
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(
                    args.endpoint.clone(),
                    args.region.clone(),
                    args.bucket.clone(),
                    args.access.clone(),
                    args.secret.clone(),
                ))
                .map_err(|e| e.to_string())?,
            );
            store
                .create_bucket_if_absent()
                .await
                .map_err(|e| e.to_string())?;
            match args.mode.as_str() {
                "prepare" => prepare(&args, store).await,
                "bootstrap" => bootstrap(&args, store).await,
                other => Err(format!("unknown mode {other}")),
            }
        })
    })();
    match result {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("pr15i-a-remote-probe: {error}");
            std::process::exit(3);
        }
    }
}
