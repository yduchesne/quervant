//! Benchmark-only fixture-metadata emitter (PR 7 Amendment 04 Correction 01).
//!
//! Emits machine-readable `quervant-fixture-metadata-v1` JSON for every workload
//! key measured by the five Criterion targets. Hit counts come from the
//! **independent fixture oracle** (`benches/common`), never from Criterion output
//! or the production search result. Non-query microbenchmarks carry
//! `actual_hits: null` with `hit_count_applicable: false`.
//!
//! Usage: `cargo run --release -p quervant-core --example pr07_report_metadata > meta.json`

#[path = "../benches/common/mod.rs"]
mod common;

use std::fmt::Write as _;

fn opt_usize(value: Option<usize>) -> String {
    match value {
        Some(value) => value.to_string(),
        None => "null".to_owned(),
    }
}

fn opt_u64(value: Option<u64>) -> String {
    match value {
        Some(value) => value.to_string(),
        None => "null".to_owned(),
    }
}

fn opt_f64(value: Option<f64>) -> String {
    match value {
        Some(value) => format!("{value:.17}"),
        None => "null".to_owned(),
    }
}

fn main() {
    let records = common::all_workload_metadata();
    let mut out = String::new();
    out.push_str("{\n");
    out.push_str("  \"schema\": \"quervant-fixture-metadata-v1\",\n");
    let _ = writeln!(
        out,
        "  \"fixture_version\": \"{}\",",
        common::FIXTURE_VERSION
    );
    let _ = writeln!(out, "  \"seed\": \"0x{:016X}\",", common::SEED);
    out.push_str("  \"records\": [\n");
    for (index, record) in records.iter().enumerate() {
        out.push_str("    {");
        let _ = write!(out, "\"workload_key\": \"{}\", ", record.workload_key);
        let _ = write!(out, "\"query_id\": \"{}\", ", record.query_id);
        let _ = write!(out, "\"operation\": \"{}\", ", record.operation);
        let _ = write!(out, "\"doc_count\": {}, ", record.doc_count);
        let _ = write!(out, "\"segments\": {}, ", record.segments);
        let _ = write!(out, "\"top_k\": {}, ", record.top_k);
        let _ = write!(out, "\"actual_hits\": {}, ", opt_usize(record.actual_hits));
        let _ = write!(
            out,
            "\"selectivity_ratio\": {}, ",
            opt_f64(record.selectivity_ratio)
        );
        let _ = write!(
            out,
            "\"hit_count_applicable\": {}, ",
            record.hit_count_applicable
        );
        let _ = write!(out, "\"dataset_sha256\": \"{}\", ", record.dataset_sha256);
        let _ = write!(
            out,
            "\"fixture_version\": \"{}\", ",
            common::FIXTURE_VERSION
        );
        let _ = write!(
            out,
            "\"posting_doc_count\": {}, ",
            opt_u64(record.posting_doc_count)
        );
        let _ = write!(
            out,
            "\"dictionary_doc_freq\": {}",
            opt_u64(record.dictionary_doc_freq)
        );
        out.push('}');
        if index + 1 != records.len() {
            out.push(',');
        }
        out.push('\n');
    }
    out.push_str("  ]\n}\n");
    print!("{out}");
}
