//! PR 15I-B benchmark-only codec laboratory.
//!
//! Reads a post-15I-A baseline index read-only, reconstructs exact 128-doc
//! STORED v1 block bodies through public `quervant-core` APIs, proves byte
//! identity with the index's STORED section, then compresses/decompresses those
//! identical block bodies with LZ4 (`lz4_flex` 0.11.6) and Zstd level 1
//! (`zstd` 0.13.3). No production code is modified.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use quervant_core::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use quervant_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::FieldType;
use quervant_core::contract::value::{FieldValue, JsonNumber, JsonValue};
use quervant_core::segment::format::{SectionKind, parse_container};
use quervant_core::segment::stored::encode_stored;
use quervant_core::segment::{CodecSchema, SegmentDocument, SegmentLimits, SegmentReader, StoredRecord};
use serde_json::json;

const BLOCK_DOCS: usize = 128;
const WARMUPS: usize = 5;
const SAMPLES: usize = 20;
const SCHEMA: &str = "pr15i-b-codec-lab-v1";

#[derive(Clone, Copy, PartialEq, Eq)]
enum Codec {
    Lz4,
    Zstd1,
}

impl Codec {
    fn id(self) -> u8 {
        match self {
            Self::Lz4 => 1,
            Self::Zstd1 => 2,
        }
    }
    fn name(self) -> &'static str {
        match self {
            Self::Lz4 => "lz4",
            Self::Zstd1 => "zstd1",
        }
    }
}

fn compress(codec: Codec, input: &[u8]) -> Result<Vec<u8>, String> {
    match codec {
        Codec::Lz4 => {
            let mut output = vec![0u8; lz4_flex::block::get_maximum_output_size(input.len())];
            let written = lz4_flex::block::compress_into(input, &mut output)
                .map_err(|error| format!("lz4 compress: {error}"))?;
            output.truncate(written);
            Ok(output)
        }
        Codec::Zstd1 => zstd::bulk::Compressor::new(1)
            .and_then(|mut compressor| compressor.compress(input))
            .map_err(|error| format!("zstd compress: {error}")),
    }
}

fn decompress(codec: Codec, input: &[u8], expected: usize) -> Result<Vec<u8>, String> {
    let mut output = vec![0u8; expected];
    let written = match codec {
        Codec::Lz4 => lz4_flex::block::decompress_into(input, &mut output)
            .map_err(|error| format!("lz4 decompress: {error}"))?,
        Codec::Zstd1 => zstd::bulk::Decompressor::new()
            .and_then(|mut decompressor| decompressor.decompress_to_buffer(input, &mut output))
            .map_err(|error| format!("zstd decompress: {error}"))?,
    };
    if written != expected {
        return Err(format!("decompressed {written} bytes, expected {expected}"));
    }
    Ok(output)
}

fn summarize(mut samples: Vec<u64>) -> serde_json::Value {
    samples.sort_unstable();
    let count = samples.len();
    let rank = |percent: f64| -> u64 {
        let index = ((percent / 100.0) * count as f64).ceil() as usize;
        samples[index.saturating_sub(1).min(count - 1)]
    };
    json!({
        "count": count,
        "min": samples[0],
        "median": rank(50.0),
        "p95": rank(95.0),
        "max": samples[count - 1],
    })
}

fn find_segment(index_dir: &Path) -> Result<PathBuf, String> {
    let directory = index_dir.join("index").join("segments");
    let mut segments = Vec::new();
    for entry in fs::read_dir(&directory).map_err(|error| format!("{}: {error}", directory.display()))? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path.extension().and_then(|value| value.to_str()) == Some("seg") {
            segments.push(path);
        }
    }
    if segments.len() != 1 {
        return Err(format!("expected one segment, found {}", segments.len()));
    }
    Ok(segments.remove(0))
}

fn segment_document(schema: &CodecSchema, record: &StoredRecord) -> SegmentDocument {
    let mut fields = BTreeMap::new();
    for (id, values) in &record.fields {
        if let Some(field) = schema.field(*id) {
            fields.insert(field.name.clone(), values.clone());
        }
    }
    let mut document = SegmentDocument::new(record.key.clone());
    document.fields = fields;
    document
}

fn synthetic_document(index: usize, field: &str, values: FieldValues) -> SegmentDocument {
    let mut document = SegmentDocument::new(DocumentKey::new(format!("control-{index:06}")).unwrap());
    document.fields.insert(field.to_owned(), values);
    document
}

fn json_control_schema() -> Result<CodecSchema, String> {
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "payload",
            FieldType::Json,
            Cardinality::Single,
            FieldOptions::new(true, true, false),
        )],
        None,
    )
    .map_err(|error| error.to_string())?;
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin())
        .map_err(|error| error.to_string())?;
    CodecSchema::from_contract(&schema, &bindings).map_err(|error| error.to_string())
}

fn controls(
    schema: &CodecSchema,
    records: &[StoredRecord],
) -> Result<Vec<(String, CodecSchema, Vec<SegmentDocument>)>, String> {
    let json_schema = json_control_schema()?;
    let field = schema
        .fields()
        .iter()
        .find(|candidate| candidate.name == "key")
        .or_else(|| schema.fields().first())
        .map(|candidate| candidate.name.clone())
        .unwrap_or_else(|| "key".to_owned());
    let mut groups = Vec::new();
    for count in [0usize, 1, 127, 128, 129, 255, 256] {
        let docs = records.iter().take(count).map(|record| segment_document(schema, record)).collect();
        groups.push((format!("records-{count}"), schema.clone(), docs));
    }
    let mut five_state = Vec::new();
    for (index, values) in [
        FieldValues::Absent,
        FieldValues::ExplicitNull,
        FieldValues::Empty,
        FieldValues::Single(FieldValue::Keyword("single".to_owned())),
        FieldValues::Multi(vec![
            FieldValue::Keyword("a".to_owned()),
            FieldValue::Keyword("b".to_owned()),
        ]),
    ]
    .into_iter()
    .enumerate()
    {
        five_state.push(synthetic_document(index, &field, values));
    }
    groups.push(("five-state".to_owned(), schema.clone(), five_state));
    let nested = JsonValue::Object(vec![
        ("alpha".to_owned(), JsonValue::String("beta".to_owned())),
        (
            "gamma".to_owned(),
            JsonValue::Array(vec![JsonValue::Number(JsonNumber::U64(1))]),
        ),
    ]);
    groups.push((
        "nested-json".to_owned(),
        json_schema,
        vec![synthetic_document(
            900,
            "payload",
            FieldValues::Single(FieldValue::Json(nested)),
        )],
    ));
    let entropy: String = (0..60_000u32)
        .map(|index| {
            let value = (index.wrapping_mul(2_654_435_761) >> 13) & 0xff;
            char::from_u32(0x21 + (value % 94)).unwrap()
        })
        .collect();
    groups.push((
        "high-entropy-1mib".to_owned(),
        schema.clone(),
        vec![synthetic_document(
            901,
            &field,
            FieldValues::Single(FieldValue::Keyword(entropy)),
        )],
    ));
    Ok(groups)
}

fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 7 || args[0] != "encode" {
        return Err(
            "usage: encode --index-dir <abs> --n <10000|100000> --out <abs>".to_owned(),
        );
    }
    let mut index_dir = None;
    let mut n = None;
    let mut out = None;
    let mut cursor = 1;
    while cursor < args.len() {
        match args[cursor].as_str() {
            "--index-dir" => index_dir = Some(PathBuf::from(&args[cursor + 1])),
            "--n" => {
                n = Some(
                    args[cursor + 1]
                        .parse::<u64>()
                        .map_err(|_| "invalid --n".to_owned())?,
                )
            }
            "--out" => out = Some(PathBuf::from(&args[cursor + 1])),
            other => return Err(format!("unexpected argument {other}")),
        }
        cursor += 2;
    }
    let index_dir = index_dir.ok_or("--index-dir required")?;
    let n = n.ok_or("--n required")?;
    let out = out.ok_or("--out required")?;
    if !index_dir.is_absolute() || !out.is_absolute() {
        return Err("paths must be absolute".to_owned());
    }
    let allowed = fs::canonicalize(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..")
            .join("target")
            .join("pr15i-b"),
    )
    .map_err(|error| format!("cannot resolve allowed output root: {error}"))?;
    let out = fs::canonicalize(&out)
        .or_else(|_| {
            let parent = out
                .parent()
                .ok_or_else(|| std::io::Error::other("invalid --out"))?;
            fs::create_dir_all(parent)?;
            fs::canonicalize(parent).map(|base| base.join(out.file_name().unwrap()))
        })
        .map_err(|error| format!("cannot resolve --out: {error}"))?;
    if !out.starts_with(&allowed) {
        return Err(format!("--out must be under {}", allowed.display()));
    }
    fs::create_dir_all(&out).map_err(|error| error.to_string())?;

    let segment_path = find_segment(&index_dir)?;
    let bytes = fs::read(&segment_path).map_err(|error| error.to_string())?;
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).map_err(|error| error.to_string())?;
    let stored_body = view
        .body(SectionKind::Stored)
        .ok_or("STORED section missing")?
        .to_vec();
    let reader = SegmentReader::open(bytes.clone(), limits).map_err(|error| error.to_string())?;
    if reader.doc_count() != n {
        return Err(format!("index doc_count {} != requested {n}", reader.doc_count()));
    }
    let schema = reader.schema().clone();
    let records = reader.stored().map_err(|error| error.to_string())?;

    // The v1 body is `u16(1) + u64(total)` followed by concatenated record
    // sequences. Each v2 block body is a complete v1 payload for its 128 docs,
    // so block[10..] must match the original bytes after the global header.
    if stored_body.len() < 10
        || u16::from_le_bytes([stored_body[0], stored_body[1]]) != 1
        || u64::from_le_bytes(stored_body[2..10].try_into().unwrap()) != n
    {
        return Err("unexpected v1 global header".to_owned());
    }
    let mut offset = 10usize;
    let mut blocks: Vec<Vec<u8>> = Vec::new();
    for chunk in records.chunks(BLOCK_DOCS) {
        let docs: Vec<SegmentDocument> = chunk
            .iter()
            .map(|record| segment_document(&schema, record))
            .collect();
        let encoded = encode_stored(&schema, &docs, &limits).map_err(|error| error.to_string())?;
        let record_bytes = &encoded[10..];
        if stored_body.len() < offset + record_bytes.len()
            || stored_body[offset..offset + record_bytes.len()] != *record_bytes
        {
            let mismatch = stored_body
                .iter()
                .zip(record_bytes.iter())
                .position(|(left, right)| left != right)
                .unwrap_or(offset);
            return Err(format!(
                "v1 block byte identity failed at block {} first_mismatch_at={mismatch}",
                blocks.len()
            ));
        }
        offset += record_bytes.len();
        blocks.push(encoded);
    }
    if offset != stored_body.len() {
        return Err(format!(
            "v1 block reconstruction ended at {offset}, section is {}",
            stored_body.len()
        ));
    }

    let directory_overhead = 40u64 * (blocks.len() as u64);
    let mut codec_results = serde_json::Map::new();
    for codec in [Codec::Lz4, Codec::Zstd1] {
        let mut compressed_total = 0u64;
        let mut raw_total = 0u64;
        let mut block_bytes = Vec::new();
        for block in &blocks {
            let compressed = compress(codec, block)?;
            let decoded = decompress(codec, &compressed, block.len())?;
            if decoded != *block {
                return Err(format!("{} roundtrip mismatch", codec.name()));
            }
            raw_total += block.len() as u64;
            compressed_total += compressed.len() as u64;
            block_bytes.push(compressed);
        }
        let candidate_section = 22 + directory_overhead + compressed_total;
        codec_results.insert(
            codec.name().to_owned(),
            json!({
                "codec_id": codec.id(),
                "blocks": blocks.len(),
                "raw_block_bytes": raw_total,
                "compressed_block_bytes": compressed_total,
                "directory_overhead_bytes": directory_overhead,
                "candidate_stored_section_bytes": candidate_section,
                "block_compressed_lengths": block_bytes.iter().map(|block| block.len()).collect::<Vec<_>>(),
            }),
        );
        let _ = block_bytes;
    }

    // Selected-block decompression timing: five boundary IDs + 100 strided IDs.
    let doc_count = blocks.len() * BLOCK_DOCS;
    let mut selected: Vec<usize> = vec![0, 127, 128, 129, doc_count.saturating_sub(1)];
    for index in 0..100usize {
        selected.push((index * doc_count.saturating_sub(1)) / 99);
    }
    selected.sort_unstable();
    selected.dedup();
    let selected_blocks: Vec<usize> = selected.iter().map(|doc| doc / BLOCK_DOCS).collect();
    let mut unique_blocks = selected_blocks.clone();
    unique_blocks.sort_unstable();
    unique_blocks.dedup();
    let schedule = [
        [Codec::Lz4, Codec::Zstd1, Codec::Zstd1, Codec::Lz4],
        [Codec::Zstd1, Codec::Lz4, Codec::Lz4, Codec::Zstd1],
        [Codec::Zstd1, Codec::Lz4, Codec::Lz4, Codec::Zstd1],
        [Codec::Lz4, Codec::Zstd1, Codec::Zstd1, Codec::Lz4],
    ];
    let mut timing = serde_json::Map::new();
    for codec in [Codec::Lz4, Codec::Zstd1] {
        let compressed: Vec<Vec<u8>> = blocks
            .iter()
            .map(|block| compress(codec, block))
            .collect::<Result<_, _>>()?;
        let mut per_block: BTreeMap<usize, Vec<u64>> = BTreeMap::new();
        for (block_index, block) in blocks.iter().enumerate() {
            if !unique_blocks.contains(&block_index) {
                continue;
            }
            for _ in 0..WARMUPS {
                let _ = decompress(codec, &compressed[block_index], block.len())?;
            }
            let mut samples = Vec::with_capacity(SAMPLES);
            for _ in 0..SAMPLES {
                let started = Instant::now();
                let decoded = decompress(codec, &compressed[block_index], block.len())?;
                samples.push(started.elapsed().as_nanos() as u64);
                if decoded.len() != block.len() {
                    return Err("selected decompression length mismatch".to_owned());
                }
            }
            per_block.insert(block_index, samples);
        }
        let summaries: serde_json::Map<String, serde_json::Value> = per_block
            .into_iter()
            .map(|(index, samples)| (index.to_string(), summarize(samples)))
            .collect();
        timing.insert(
            codec.name().to_owned(),
            json!({
                "selected_blocks": unique_blocks,
                "selected_block_count": unique_blocks.len(),
                "per_block": summaries,
                "schedule": schedule.iter().map(|order| order.iter().map(|entry| entry.name()).collect::<Vec<_>>()).collect::<Vec<_>>(),
            }),
        );
    }

    let mut control_results = serde_json::Map::new();
    for (name, control_schema, docs) in controls(&schema, &records)? {
        let body = encode_stored(&control_schema, &docs, &limits).map_err(|error| error.to_string())?;
        let mut entry = serde_json::Map::new();
        entry.insert("documents".to_owned(), json!(docs.len()));
        entry.insert("v1_bytes".to_owned(), json!(body.len()));
        for codec in [Codec::Lz4, Codec::Zstd1] {
            let compressed = compress(codec, &body)?;
            let decoded = decompress(codec, &compressed, body.len())?;
            if decoded != body {
                return Err(format!("control {name} {} roundtrip failed", codec.name()));
            }
            entry.insert(
                format!("{}_bytes", codec.name()),
                json!(compressed.len()),
            );
        }
        control_results.insert(name, serde_json::Value::Object(entry));
    }

    let report = json!({
        "schema": SCHEMA,
        "index_dir": index_dir.display().to_string(),
        "segment": segment_path.display().to_string(),
        "n": n,
        "block_docs": BLOCK_DOCS,
        "block_count": blocks.len(),
        "stored_section_bytes": stored_body.len(),
        "directory_overhead_bytes": directory_overhead,
        "v1_block_byte_identity": "PASS",
        "codecs": codec_results,
        "timing": timing,
        "controls": control_results,
        "libraries": {
            "lz4_flex": "0.11.6",
            "zstd": "0.13.3",
            "zstd_level": 1,
        },
    });
    let path = out.join("codec_lab.json");
    fs::write(&path, serde_json::to_vec_pretty(&report).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())?;
    println!("{}", serde_json::to_string(&report).map_err(|error| error.to_string())?);
    Ok(())
}
