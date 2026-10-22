//! M1-V05 cross-version compatibility probe.
//!
//! This single source file is compiled twice by `run.sh`:
//!
//! * against a **baseline** Quervant revision (M1 `cd3b9ac`, no
//!   `contract::mutation`, no `IndexWriter::apply_batch`), with the batch modes
//!   compiled out; and
//! * against the **current** M1 revision with `--cfg m1_probe`, which enables
//!   the batch modes.
//!
//! It therefore proves compatibility with a genuinely older reader binary
//! rather than simulating one with the new decoder.
//!
//! Modes:
//!
//! * `mkv1 <dir>`            create a v1 index with a single-key idempotency
//!                           token, then commit.
//! * `inspect <dir>`         open the index with the public reader API and
//!                           print generation + physically stored keys.
//! * `live <dir>`            print the live (visible) keys via `MatchAll`.
//! * `replaysingle <dir>`    replay the single-key token through `apply`.
//! * `mkbatch <dir>`         (current only) apply + commit an idempotent batch,
//!                           upgrading the durable payload to v2.
//! * `replay <dir>`          (current only) replay the durable batch token.
//!
//! Exit codes: `0` success, `3` expected typed rejection, `4` unexpected error.
#![allow(unexpected_cfgs)]

use std::sync::Arc;

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey, MutationRequest,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits};
use quervant_core::storage::{Directory, FsDirectory};

const SINGLE_TOKEN: &str = "m1-compat-single-token";
#[cfg(m1_probe)]
const BATCH_TOKEN: &str = "m1-compat-batch-token";

fn schema() -> Schema {
    Schema::new(
        vec![FieldDefinition::new(
            "title",
            FieldType::Text,
            Cardinality::Single,
            FieldOptions::indexed_stored(),
        )
        .with_analyzer("standard_folded")],
        None,
    )
    .expect("schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn document(key: &str, title: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .expect("field");
    document
}

fn open(directory: &str) -> Result<Index, quervant_core::index::IndexError> {
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(directory)?);
    Index::open_with_limits(directory, schema(), registry(), IndexLimits::default())
}

/// Print a complete error chain, independent of how the public API wraps it.
fn report_chain(error: &quervant_core::index::IndexError) {
    println!("ERROR_DEBUG={error:?}");
    println!("ERROR_DISPLAY={error}");
    let mut depth = 0;
    let mut current: Option<&(dyn std::error::Error + 'static)> = std::error::Error::source(error);
    while let Some(source) = current {
        println!("ERROR_CHAIN[{depth}]={source}");
        depth += 1;
        current = source.source();
    }
    // The typed rejection identity is what the gate asserts on.
    let debug = format!("{error:?}");
    if debug.contains("UnsupportedFeature") {
        println!("REJECTION=UnsupportedFeature");
    } else if debug.contains("Corrupt") {
        println!("REJECTION=Corrupt");
    } else {
        println!("REJECTION=Other");
    }
}

fn mode_mkv1(directory: &str) {
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(directory).expect("directory"));
    let index = Index::create_with_limits(directory, schema(), registry(), IndexLimits::default())
        .expect("create");
    let mut writer = index.writer().expect("writer");
    writer
        .apply(
            MutationRequest::insert(document("a", "alpha one"))
                .with_idempotency_key(IdempotencyKey::new(SINGLE_TOKEN).expect("token")),
        )
        .expect("insert a");
    writer
        .apply(MutationRequest::insert(document("b", "beta two")))
        .expect("insert b");
    let outcome = writer.commit().expect("commit");
    writer.close().expect("close");
    println!("CREATED=1");
    println!("GENERATION={}", outcome.generation);
}

fn mode_inspect(directory: &str) {
    match open(directory) {
        Ok(index) => {
            let snapshot = index.snapshot();
            let mut keys: Vec<String> = snapshot
                .stored_keys()
                .expect("stored keys")
                .into_iter()
                .map(|key| key.as_str().to_owned())
                .collect();
            keys.sort();
            println!("OPEN=OK");
            println!("GENERATION={:?}", index.generation());
            println!("KEYS={}", keys.join(","));
        }
        Err(error) => {
            report_chain(&error);
            std::process::exit(3);
        }
    }
}

fn mode_live(directory: &str) {
    use quervant_core::analysis::CancellationFlag;
    use quervant_core::contract::budget::Budgets;
    use quervant_core::contract::query::Query;
    use quervant_core::contract::result::TopK;
    use quervant_core::search::{LexicalSearcher, SearchLimits};

    let index = open(directory).expect("open for live scan");
    let snapshot = index.snapshot();
    let cancel = CancellationFlag::new();
    let response = LexicalSearcher::new(
        snapshot.as_ref(),
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(
        &Query::MatchAll,
        TopK::new(100).expect("top-k"),
        &Budgets::new(),
        &cancel,
    )
    .expect("match-all search");
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort();
    println!("LIVE={}", keys.join(","));
}

fn mode_replaysingle(directory: &str) {
    let index = open(directory).expect("open for single-key replay");
    let mut writer = index.writer().expect("writer");
    let response = writer
        .apply(
            MutationRequest::insert(document("a", "alpha one"))
                .with_idempotency_key(IdempotencyKey::new(SINGLE_TOKEN).expect("token")),
        )
        .expect("single-key replay");
    writer.close().expect("close");
    println!("REPLAYED={}", response.replayed);
    println!("REVISION={:?}", response.revision);
}

#[cfg(m1_probe)]
fn batch() -> quervant_core::contract::mutation::MutationBatch {
    use quervant_core::contract::mutation::{
        MutationAction, MutationBatch, MutationCommand, MutationTarget,
    };
    MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("c").expect("key")),
            MutationAction::Insert(document("c", "gamma three")),
        ),
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("b").expect("key")),
            MutationAction::Delete,
        ),
    ])
    .with_idempotency_key(IdempotencyKey::new(BATCH_TOKEN).expect("token"))
}

#[cfg(m1_probe)]
fn mode_mkbatch(directory: &str) {
    use quervant_core::analysis::CancellationFlag;
    let index = open(directory).expect("open for batch");
    let mut writer = index.writer().expect("writer");
    let response = writer
        .apply_batch(&batch(), &CancellationFlag::new())
        .expect("apply batch");
    let outcome = writer.commit().expect("commit batch");
    writer.close().expect("close");
    println!("GENERATION={}", outcome.generation);
    for command in &response.outcomes {
        let keys: Vec<String> = command
            .keys
            .iter()
            .map(|key| format!("{}={:?}", key.key.as_str(), key.revision))
            .collect();
        println!("OUTCOME[{}]={}", command.command_index, keys.join(","));
    }
}

#[cfg(m1_probe)]
fn mode_replay(directory: &str) {
    use quervant_core::analysis::CancellationFlag;
    let index = open(directory).expect("open for batch replay");
    let mut writer = index.writer().expect("writer");
    let response = writer
        .apply_batch(&batch(), &CancellationFlag::new())
        .expect("batch replay");
    writer.close().expect("close");
    println!("REPLAYED={}", response.replayed);
    for command in &response.outcomes {
        let keys: Vec<String> = command
            .keys
            .iter()
            .map(|key| {
                format!(
                    "{}={:?}/replayed={}",
                    key.key.as_str(),
                    key.revision,
                    key.replayed
                )
            })
            .collect();
        println!("OUTCOME[{}]={}", command.command_index, keys.join(","));
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: <mode> <index-dir>");
        std::process::exit(64);
    }
    let mode = args[1].as_str();
    let directory = args[2].as_str();
    match mode {
        "mkv1" => mode_mkv1(directory),
        "inspect" => mode_inspect(directory),
        "live" => mode_live(directory),
        "replaysingle" => mode_replaysingle(directory),
        #[cfg(m1_probe)]
        "mkbatch" => mode_mkbatch(directory),
        #[cfg(m1_probe)]
        "replay" => mode_replay(directory),
        other => {
            eprintln!("unknown mode: {other}");
            std::process::exit(64);
        }
    }
}
