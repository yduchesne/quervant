//! PR 15H-E cold process open timing helper (ignored; invoked per arm by the
//! benchmark controller). Opens the already committed 100K index with the same
//! schema and limits as the frozen PR15D adapter and writes `open_ns` JSON.

use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::Cardinality;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::FieldType;
use quervant_core::index::{Index, IndexLimits};
use quervant_core::storage::FsDirectory;

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
    .expect("adapter schema")
}

fn limits() -> IndexLimits {
    const MAX_BENCHMARK_DOCS: u64 = 1_000_000;
    IndexLimits::new()
        .with_max_pending_docs(MAX_BENCHMARK_DOCS)
        .with_max_pending_bytes(512 * 1024 * 1024)
        .with_max_replay_entries(MAX_BENCHMARK_DOCS)
        .with_max_replay_bytes(512 * 1024 * 1024)
}

#[test]
#[ignore = "benchmark open-timing helper; run explicitly from the E controller"]
fn measure_cold_open() {
    let index_dir = std::env::var("QUERVANT_E_INDEX_DIR")
        .expect("QUERVANT_E_INDEX_DIR must name the built index");
    let out = std::env::var("QUERVANT_E_OPEN_OUT")
        .expect("QUERVANT_E_OPEN_OUT must name the JSON output");
    let directory = FsDirectory::open(&index_dir).expect("fs directory");
    let started = Instant::now();
    let index = Index::open_with_limits(
        Arc::new(directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .expect("open index");
    let snapshot = index.snapshot();
    let open_ns = started.elapsed().as_nanos();
    let body = format!(
        "{{\"open_ns\":{open_ns},\"segments\":{},\"generation\":{}}}\n",
        snapshot.segment_count(),
        snapshot.generation().is_some()
    );
    std::fs::write(out, body).expect("write open timing");
}
