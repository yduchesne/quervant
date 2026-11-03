//! PR15F benchmark-only reopen and read-only index-layout probe.
//!
//! This binary uses **public** `quervant-core` APIs only: `FsDirectory`,
//! `Index::open_with_limits`, `Index::snapshot`, and `segment::parse_container`.
//! It never writes to the index directory, never implements a private format
//! parser, and never changes production code or on-disk semantics.
//!
//! Fixed CLI (no other flags or modes are accepted):
//!
//! ```text
//! pr15f-reopen-probe --mode single    --index-dir <absolute> --n 10000|100000
//! pr15f-reopen-probe --mode loop      --index-dir <absolute> --n 10000|100000 --iterations 64|128
//! pr15f-reopen-probe --mode inventory --index-dir <absolute> --n 10000|100000
//! ```
//!
//! Exactly one canonical JSON object is written to stdout. Diagnostics go to
//! stderr only and a failure exits non-zero with no JSON object.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::Cardinality;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::FieldType;
use quervant_core::index::{Index, IndexLimits};
use quervant_core::segment::format::{MANIFEST_MAGIC, MUTATION_STATE_MAGIC, SEGMENT_MAGIC};
use quervant_core::segment::{ContainerKind, ContainerView, SectionKind, parse_container};
use quervant_core::storage::{Directory, FsDirectory};
use serde_json::{Value, json};

const PROBE_SCHEMA: &str = "pr15f-reopen-probe-v1";
const INVENTORY_SCHEMA: &str = "pr15f-index-inventory-v1";
const N_VALUES: [u64; 2] = [10_000, 100_000];
const LOOP_ITERATIONS: [u64; 2] = [64, 128];
const MAX_INVENTORY_FILE_BYTES: u64 = 8 * 1024 * 1024 * 1024;

const EXIT_USAGE: i32 = 2;
const EXIT_FAILED: i32 = 3;

#[derive(Debug)]
struct ProbeError {
    kind: &'static str,
    message: String,
}

impl ProbeError {
    fn usage(message: impl Into<String>) -> Self {
        Self {
            kind: "usage",
            message: message.into(),
        }
    }

    fn failed(kind: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for ProbeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.kind, self.message)
    }
}

// ---------------------------------------------------------------------------
// Frozen benchmark schema, analyzer registry and resource policy.
//
// These three functions are a byte-identical benchmark-only copy of the frozen
// PR 15D Quervant adapter definitions (`benchmarks/pr15d/adapters/quervant/
// src/main.rs`). The Python test module pins the adapter source SHA-256 and
// re-derives these definitions from the adapter source, so drift is a test
// failure rather than a silent schema change. They are private to the adapter,
// so a copy is the only way to reopen the prepared index with the exact same
// schema and limits.
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Single,
    Loop,
    Inventory,
}

#[derive(Debug)]
struct Args {
    mode: Mode,
    index_dir: PathBuf,
    n: u64,
    iterations: Option<u64>,
}

fn parse_args(argv: impl IntoIterator<Item = String>) -> Result<Args, ProbeError> {
    let mut mode: Option<String> = None;
    let mut index_dir: Option<String> = None;
    let mut n: Option<u64> = None;
    let mut iterations: Option<u64> = None;

    let mut arguments = argv.into_iter();
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--mode" => {
                let value = arguments
                    .next()
                    .ok_or_else(|| ProbeError::usage("--mode requires a value"))?;
                if mode.replace(value).is_some() {
                    return Err(ProbeError::usage("--mode was supplied more than once"));
                }
                continue;
            }
            "--index-dir" => {
                let value = arguments
                    .next()
                    .ok_or_else(|| ProbeError::usage("--index-dir requires a value"))?;
                if index_dir.replace(value).is_some() {
                    return Err(ProbeError::usage("--index-dir was supplied more than once"));
                }
                continue;
            }
            "--n" => {
                let value = arguments
                    .next()
                    .ok_or_else(|| ProbeError::usage("--n requires a value"))?;
                let parsed = value
                    .parse::<u64>()
                    .map_err(|_| ProbeError::usage(format!("--n is not an integer: {value}")))?;
                if n.replace(parsed).is_some() {
                    return Err(ProbeError::usage("--n was supplied more than once"));
                }
                continue;
            }
            "--iterations" => {
                let value = arguments
                    .next()
                    .ok_or_else(|| ProbeError::usage("--iterations requires a value"))?;
                let parsed = value.parse::<u64>().map_err(|_| {
                    ProbeError::usage(format!("--iterations is not an integer: {value}"))
                })?;
                if iterations.replace(parsed).is_some() {
                    return Err(ProbeError::usage(
                        "--iterations was supplied more than once",
                    ));
                }
                continue;
            }
            other => {
                return Err(ProbeError::usage(format!("unsupported argument: {other}")));
            }
        }
    }

    let mode = match mode.as_deref() {
        Some("single") => Mode::Single,
        Some("loop") => Mode::Loop,
        Some("inventory") => Mode::Inventory,
        Some(other) => {
            return Err(ProbeError::usage(format!(
                "unsupported --mode {other}; expected single, loop or inventory"
            )));
        }
        None => return Err(ProbeError::usage("--mode is required")),
    };
    let index_dir = index_dir.ok_or_else(|| ProbeError::usage("--index-dir is required"))?;
    let n = n.ok_or_else(|| ProbeError::usage("--n is required"))?;
    if !N_VALUES.contains(&n) {
        return Err(ProbeError::usage(format!(
            "--n must be one of {N_VALUES:?}, got {n}"
        )));
    }
    match (mode, iterations) {
        (Mode::Loop, None) => {
            return Err(ProbeError::usage("--mode loop requires --iterations"));
        }
        (Mode::Loop, Some(value)) if !LOOP_ITERATIONS.contains(&value) => {
            return Err(ProbeError::usage(format!(
                "--iterations must be one of {LOOP_ITERATIONS:?}, got {value}"
            )));
        }
        (Mode::Loop, Some(_)) => {}
        (_, Some(_)) => {
            return Err(ProbeError::usage(
                "--iterations is only valid with --mode loop",
            ));
        }
        (_, None) => {}
    }

    Ok(Args {
        mode,
        index_dir: PathBuf::from(index_dir),
        n,
        iterations,
    })
}

// ---------------------------------------------------------------------------
// Path and tree validation (never writes)
// ---------------------------------------------------------------------------

fn validate_index_dir(raw: &Path) -> Result<PathBuf, ProbeError> {
    if !raw.is_absolute() {
        return Err(ProbeError::usage(format!(
            "--index-dir must be an absolute path: {}",
            raw.display()
        )));
    }
    for component in raw.components() {
        if matches!(component, Component::ParentDir) {
            return Err(ProbeError::usage(
                "--index-dir may not contain a parent-directory component",
            ));
        }
    }
    let mut current = PathBuf::new();
    for component in raw.components() {
        current.push(component);
        let metadata = fs::symlink_metadata(&current).map_err(|error| {
            ProbeError::failed(
                "index_missing",
                format!("cannot stat {}: {error}", current.display()),
            )
        })?;
        if metadata.file_type().is_symlink() {
            return Err(ProbeError::failed(
                "index_symlink",
                format!("symlink in index path: {}", current.display()),
            ));
        }
    }
    let metadata = fs::metadata(raw).map_err(|error| {
        ProbeError::failed(
            "index_missing",
            format!("index directory is unavailable: {error}"),
        )
    })?;
    if !metadata.is_dir() {
        return Err(ProbeError::failed(
            "index_missing",
            "--index-dir is not a directory",
        ));
    }
    fs::canonicalize(raw).map_err(|error| {
        ProbeError::failed(
            "index_missing",
            format!("cannot resolve the index directory: {error}"),
        )
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FileRole {
    Segment,
    Manifest,
    MutationState,
    CurrentMetadata,
    LockMetadata,
}

impl FileRole {
    fn label(self) -> &'static str {
        match self {
            Self::Segment => "segment",
            Self::Manifest => "manifest",
            Self::MutationState => "mutation_state",
            Self::CurrentMetadata => "metadata_current",
            Self::LockMetadata => "metadata_lock",
        }
    }

    fn expected_container(self) -> Option<ContainerKind> {
        match self {
            Self::Segment => Some(ContainerKind::Segment),
            Self::Manifest => Some(ContainerKind::Manifest),
            Self::MutationState => Some(ContainerKind::MutationState),
            _ => None,
        }
    }
}

#[derive(Debug)]
struct IndexFile {
    relative: String,
    path: PathBuf,
    bytes: u64,
    role: FileRole,
}

fn classify_path(relative: &str) -> Result<FileRole, ProbeError> {
    if relative == "index/CURRENT" {
        return Ok(FileRole::CurrentMetadata);
    }
    if let Some(rest) = relative.strip_prefix("index/segments/") {
        if !rest.contains('/') && rest.ends_with(".seg") {
            return Ok(FileRole::Segment);
        }
    }
    if let Some(rest) = relative.strip_prefix("index/manifests/") {
        if !rest.contains('/') && rest.ends_with(".manifest") {
            return Ok(FileRole::Manifest);
        }
    }
    if let Some(rest) = relative.strip_prefix("index/state/") {
        if !rest.contains('/') && rest.ends_with(".state") {
            return Ok(FileRole::MutationState);
        }
    }
    if relative == "index/locks/WRITER_LOCK" {
        return Ok(FileRole::LockMetadata);
    }
    Err(ProbeError::failed(
        "index_foreign_file",
        format!("index file is not an allowed segment/manifest/state/metadata file: {relative}"),
    ))
}

fn collect_index_files(root: &Path) -> Result<Vec<IndexFile>, ProbeError> {
    let mut files = Vec::new();
    let mut directories = vec![root.to_path_buf()];
    while let Some(directory) = directories.pop() {
        let mut entries = Vec::new();
        for entry in fs::read_dir(&directory).map_err(|error| {
            ProbeError::failed(
                "index_unreadable",
                format!("cannot read {}: {error}", directory.display()),
            )
        })? {
            entries.push(entry.map_err(|error| {
                ProbeError::failed("index_unreadable", format!("directory entry: {error}"))
            })?);
        }
        entries.sort_by_key(|entry| entry.file_name());
        for entry in entries {
            let path = entry.path();
            let metadata = fs::symlink_metadata(&path).map_err(|error| {
                ProbeError::failed(
                    "index_unreadable",
                    format!("cannot stat {}: {error}", path.display()),
                )
            })?;
            let file_type = metadata.file_type();
            if file_type.is_symlink() {
                return Err(ProbeError::failed(
                    "index_symlink",
                    format!("symlink inside index tree: {}", path.display()),
                ));
            }
            if file_type.is_dir() {
                directories.push(path);
                continue;
            }
            if !file_type.is_file() {
                return Err(ProbeError::failed(
                    "index_foreign_file",
                    format!("special file inside index tree: {}", path.display()),
                ));
            }
            let relative = path
                .strip_prefix(root)
                .map_err(|_| {
                    ProbeError::failed("index_foreign_file", "path escaped the index root")
                })?
                .components()
                .map(|component| component.as_os_str().to_string_lossy())
                .collect::<Vec<_>>()
                .join("/");
            let role = classify_path(&relative)?;
            files.push(IndexFile {
                relative,
                path,
                bytes: metadata.len(),
                role,
            });
        }
    }
    files.sort_by(|left, right| left.relative.cmp(&right.relative));
    if files.is_empty() {
        return Err(ProbeError::failed(
            "index_empty",
            "index directory contains no files",
        ));
    }
    Ok(files)
}

fn read_container<'a>(
    bytes: &'a [u8],
    file: &IndexFile,
    limits: &quervant_core::segment::SegmentLimits,
) -> Result<ContainerView<'a>, ProbeError> {
    let expected = file.role.expected_container().ok_or_else(|| {
        ProbeError::failed(
            "index_foreign_file",
            format!("{} is not a container file", file.relative),
        )
    })?;
    let magic = &bytes[..bytes.len().min(8)];
    let observed = if magic == SEGMENT_MAGIC {
        ContainerKind::Segment
    } else if magic == MANIFEST_MAGIC {
        ContainerKind::Manifest
    } else if magic == MUTATION_STATE_MAGIC {
        ContainerKind::MutationState
    } else {
        return Err(ProbeError::failed(
            "index_magic",
            format!("{} has no recognized container magic", file.relative),
        ));
    };
    if observed != expected {
        return Err(ProbeError::failed(
            "index_container_kind",
            format!(
                "{} is classified {} but its magic is {:?}",
                file.relative,
                file.role.label(),
                observed
            ),
        ));
    }
    let view = parse_container(bytes, limits).map_err(|error| {
        ProbeError::failed(
            "index_container_parse",
            format!("{}: {error}", file.relative),
        )
    })?;
    if view.kind() != expected {
        return Err(ProbeError::failed(
            "index_container_kind",
            format!("{} parsed as {:?}", file.relative, view.kind()),
        ));
    }
    Ok(view)
}

/// Structural validation used before timed reopen work: names, sizes and
/// symlinks only. It never reads segment payloads, so it cannot change the
/// page-cache state the timed `Index::open_with_limits` observes.
fn validate_tree(root: &Path) -> Result<Vec<IndexFile>, ProbeError> {
    let files = collect_index_files(root)?;
    if !files
        .iter()
        .any(|file| file.role == FileRole::CurrentMetadata)
    {
        return Err(ProbeError::failed(
            "index_layout",
            "index/CURRENT is missing",
        ));
    }
    if !files.iter().any(|file| file.role == FileRole::Segment) {
        return Err(ProbeError::failed(
            "index_layout",
            "index contains no segment file",
        ));
    }
    Ok(files)
}

// ---------------------------------------------------------------------------
// Timed reopen stages
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy)]
struct StageSample {
    fs_directory_open_ns: u64,
    index_open_ns: u64,
    snapshot_acquire_ns: u64,
    reopen_core_ns: u64,
    reopen_total_ns: u64,
    documents: u64,
    segments: u64,
    generation: u64,
}

fn positive_ns(value: u128, label: &'static str) -> Result<u64, ProbeError> {
    if value == 0 || value > u128::from(u64::MAX) {
        return Err(ProbeError::failed(
            "stage_timer",
            format!("{label} is not a positive nanosecond count"),
        ));
    }
    Ok(value as u64)
}

fn checked_sum(left: u64, right: u64, label: &'static str) -> Result<u64, ProbeError> {
    left.checked_add(right).ok_or_else(|| {
        ProbeError::failed(
            "stage_timer",
            format!("{label} overflowed the u64 nanosecond range"),
        )
    })
}

fn one_reopen(index_dir: &Path, expected_documents: u64) -> Result<StageSample, ProbeError> {
    let directory_started = Instant::now();
    let directory = FsDirectory::open(index_dir).map_err(|error| {
        ProbeError::failed("fs_directory_open", format!("FsDirectory::open: {error}"))
    })?;
    let fs_directory_open_ns = positive_ns(
        directory_started.elapsed().as_nanos(),
        "fs_directory_open_ns",
    )?;

    let index_started = Instant::now();
    let index: Index = Index::open_with_limits(
        Arc::new(directory) as Arc<dyn Directory>,
        schema(),
        registry(),
        benchmark_limits(),
    )
    .map_err(|error| {
        ProbeError::failed("index_open", format!("Index::open_with_limits: {error}"))
    })?;
    let index_open_ns = positive_ns(index_started.elapsed().as_nanos(), "index_open_ns")?;

    let snapshot_started = Instant::now();
    let snapshot = index.snapshot();
    let snapshot_acquire_ns =
        positive_ns(snapshot_started.elapsed().as_nanos(), "snapshot_acquire_ns")?;

    // Everything below is outside every timed region.
    let documents = snapshot.document_count();
    let segments = snapshot.segment_count();
    let generation = index.generation();
    drop(snapshot);
    drop(index);

    if documents != expected_documents {
        return Err(ProbeError::failed(
            "snapshot_documents",
            format!("snapshot reports {documents} documents, expected {expected_documents}"),
        ));
    }
    if segments < 1 {
        return Err(ProbeError::failed(
            "snapshot_segments",
            "snapshot contains no segment",
        ));
    }
    let generation = generation.ok_or_else(|| {
        ProbeError::failed(
            "snapshot_generation",
            "opened index has no committed generation",
        )
    })?;
    if generation < 1 {
        return Err(ProbeError::failed(
            "snapshot_generation",
            format!("committed generation is {generation}"),
        ));
    }

    let reopen_core_ns = checked_sum(index_open_ns, snapshot_acquire_ns, "reopen_core_ns")?;
    let reopen_total_ns = checked_sum(fs_directory_open_ns, reopen_core_ns, "reopen_total_ns")?;

    Ok(StageSample {
        fs_directory_open_ns,
        index_open_ns,
        snapshot_acquire_ns,
        reopen_core_ns,
        reopen_total_ns,
        documents,
        segments: segments as u64,
        generation,
    })
}

fn stage_json(sample: &StageSample) -> Value {
    json!({
        "fs_directory_open_ns": sample.fs_directory_open_ns,
        "index_open_ns": sample.index_open_ns,
        "snapshot_acquire_ns": sample.snapshot_acquire_ns,
        "reopen_core_ns": sample.reopen_core_ns,
        "reopen_total_ns": sample.reopen_total_ns,
        "documents": sample.documents,
        "segments": sample.segments,
        "generation": sample.generation,
    })
}

fn stage_totals(samples: &[StageSample]) -> Result<Value, ProbeError> {
    let mut fs_directory_open_ns = 0u64;
    let mut index_open_ns = 0u64;
    let mut snapshot_acquire_ns = 0u64;
    let mut reopen_core_ns = 0u64;
    let mut reopen_total_ns = 0u64;
    for sample in samples {
        fs_directory_open_ns =
            checked_sum(fs_directory_open_ns, sample.fs_directory_open_ns, "total")?;
        index_open_ns = checked_sum(index_open_ns, sample.index_open_ns, "total")?;
        snapshot_acquire_ns =
            checked_sum(snapshot_acquire_ns, sample.snapshot_acquire_ns, "total")?;
        reopen_core_ns = checked_sum(reopen_core_ns, sample.reopen_core_ns, "total")?;
        reopen_total_ns = checked_sum(reopen_total_ns, sample.reopen_total_ns, "total")?;
    }
    Ok(json!({
        "fs_directory_open_ns": fs_directory_open_ns,
        "index_open_ns": index_open_ns,
        "snapshot_acquire_ns": snapshot_acquire_ns,
        "reopen_core_ns": reopen_core_ns,
        "reopen_total_ns": reopen_total_ns,
        "sample_count": samples.len(),
    }))
}

fn reopen_samples(
    index_dir: &Path,
    n: u64,
    iterations: u64,
) -> Result<Vec<StageSample>, ProbeError> {
    let mut samples = Vec::with_capacity(iterations as usize);
    for _ in 0..iterations {
        samples.push(one_reopen(index_dir, n)?);
    }
    Ok(samples)
}

fn reopen_output(mode: Mode, n: u64, samples: &[StageSample]) -> Result<Value, ProbeError> {
    let iterations = samples.iter().map(stage_json).collect::<Vec<_>>();
    Ok(json!({
        "schema": PROBE_SCHEMA,
        "mode": match mode {
            Mode::Single => "single",
            Mode::Loop => "loop",
            Mode::Inventory => "inventory",
        },
        "n": n,
        "iteration_count": samples.len(),
        "documents_verified": samples.first().map(|sample| sample.documents).unwrap_or(0),
        "segments_verified": samples.first().map(|sample| sample.segments).unwrap_or(0),
        "generation": samples.first().map(|sample| sample.generation).unwrap_or(0),
        "iterations": iterations,
        "stage_totals_ns": stage_totals(samples)?,
    }))
}

// ---------------------------------------------------------------------------
// Read-only inventory
// ---------------------------------------------------------------------------

#[derive(Default)]
struct SegmentInventory {
    documents: u64,
    section_bytes: BTreeMap<String, u64>,
    section_counts: BTreeMap<String, u64>,
    section_bytes_total: u64,
    nonsection_bytes: u64,
}

fn section_label(kind: SectionKind) -> String {
    format!("{kind:?}")
}

fn inventory_segment(
    bytes: &[u8],
    file: &IndexFile,
    limits: &quervant_core::segment::SegmentLimits,
) -> Result<SegmentInventory, ProbeError> {
    let view = read_container(bytes, file, limits)?;
    let mut inventory = SegmentInventory {
        documents: view.doc_count(),
        ..SegmentInventory::default()
    };
    for section in view.sections() {
        let label = section_label(section.kind);
        let entry = inventory.section_bytes.entry(label.clone()).or_insert(0);
        *entry = checked_sum(*entry, section.length, "section_bytes")?;
        let count = inventory.section_counts.entry(label).or_insert(0);
        *count = checked_sum(*count, 1, "section_count")?;
        inventory.section_bytes_total = checked_sum(
            inventory.section_bytes_total,
            section.length,
            "section_total",
        )?;
    }
    let file_bytes = u64::try_from(bytes.len()).map_err(|_| {
        ProbeError::failed("inventory_overflow", "segment file length does not fit u64")
    })?;
    inventory.nonsection_bytes = file_bytes
        .checked_sub(inventory.section_bytes_total)
        .ok_or_else(|| {
            ProbeError::failed(
                "inventory_sections",
                format!("{}: section bytes exceed the file length", file.relative),
            )
        })?;
    Ok(inventory)
}

fn run_inventory(root: &Path, n: u64) -> Result<Value, ProbeError> {
    let files = collect_index_files(root)?;
    let limits = benchmark_limits();
    let segment_limits = limits.segment_limits();

    let directory = FsDirectory::open(root).map_err(|error| {
        ProbeError::failed("fs_directory_open", format!("FsDirectory::open: {error}"))
    })?;
    let index = Index::open_with_limits(
        Arc::new(directory) as Arc<dyn Directory>,
        schema(),
        registry(),
        benchmark_limits(),
    )
    .map_err(|error| {
        ProbeError::failed("index_open", format!("Index::open_with_limits: {error}"))
    })?;
    let snapshot = index.snapshot();
    let snapshot_documents = snapshot.document_count();
    let snapshot_segments = snapshot.segment_count();
    let generation = index.generation();
    drop(snapshot);
    drop(index);
    if snapshot_documents != n {
        return Err(ProbeError::failed(
            "inventory_documents",
            format!("snapshot reports {snapshot_documents} documents, expected {n}"),
        ));
    }
    let generation = generation.ok_or_else(|| {
        ProbeError::failed(
            "inventory_generation",
            "opened index has no committed generation",
        )
    })?;

    let mut total_file_bytes = 0u64;
    let mut segment_file_bytes = 0u64;
    let mut manifest_file_bytes = 0u64;
    let mut mutation_state_file_bytes = 0u64;
    let mut metadata_file_bytes = 0u64;
    let mut section_bytes: BTreeMap<String, u64> = BTreeMap::new();
    let mut section_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut segment_section_bytes_total = 0u64;
    let mut segment_nonsection_bytes_total = 0u64;
    let mut segment_documents_total = 0u64;
    let mut segments = Vec::new();
    let mut file_records = Vec::new();

    for file in &files {
        total_file_bytes = checked_sum(total_file_bytes, file.bytes, "total_file_bytes")?;
        let record = match file.role {
            FileRole::Segment => {
                segment_file_bytes =
                    checked_sum(segment_file_bytes, file.bytes, "segment_file_bytes")?;
                if file.bytes > MAX_INVENTORY_FILE_BYTES {
                    return Err(ProbeError::failed(
                        "inventory_too_large",
                        format!("{} exceeds the inventory read bound", file.relative),
                    ));
                }
                let bytes = fs::read(&file.path).map_err(|error| {
                    ProbeError::failed(
                        "index_unreadable",
                        format!("cannot read {}: {error}", file.relative),
                    )
                })?;
                if u64::try_from(bytes.len()).ok() != Some(file.bytes) {
                    return Err(ProbeError::failed(
                        "index_changed",
                        format!("{} changed size during inventory", file.relative),
                    ));
                }
                let segment = inventory_segment(&bytes, file, segment_limits)?;
                segment_documents_total =
                    checked_sum(segment_documents_total, segment.documents, "documents")?;
                segment_section_bytes_total = checked_sum(
                    segment_section_bytes_total,
                    segment.section_bytes_total,
                    "section_total",
                )?;
                segment_nonsection_bytes_total = checked_sum(
                    segment_nonsection_bytes_total,
                    segment.nonsection_bytes,
                    "nonsection_total",
                )?;
                for (label, value) in &segment.section_bytes {
                    let entry = section_bytes.entry(label.clone()).or_insert(0);
                    *entry = checked_sum(*entry, *value, "section_bytes")?;
                }
                for (label, value) in &segment.section_counts {
                    let entry = section_counts.entry(label.clone()).or_insert(0);
                    *entry = checked_sum(*entry, *value, "section_count")?;
                }
                segments.push(json!({
                    "path": file.relative,
                    "file_bytes": file.bytes,
                    "documents": segment.documents,
                    "section_bytes": segment.section_bytes,
                    "section_bytes_total": segment.section_bytes_total,
                    "nonsection_bytes": segment.nonsection_bytes,
                }));
                json!({
                    "path": file.relative,
                    "bytes": file.bytes,
                    "kind": file.role.label(),
                    "container": true,
                })
            }
            FileRole::Manifest => {
                manifest_file_bytes =
                    checked_sum(manifest_file_bytes, file.bytes, "manifest_file_bytes")?;
                let bytes = fs::read(&file.path).map_err(|error| {
                    ProbeError::failed(
                        "index_unreadable",
                        format!("cannot read {}: {error}", file.relative),
                    )
                })?;
                let _ = read_container(&bytes, file, segment_limits)?;
                json!({
                    "path": file.relative,
                    "bytes": file.bytes,
                    "kind": file.role.label(),
                    "container": true,
                })
            }
            FileRole::MutationState => {
                mutation_state_file_bytes = checked_sum(
                    mutation_state_file_bytes,
                    file.bytes,
                    "mutation_state_file_bytes",
                )?;
                let bytes = fs::read(&file.path).map_err(|error| {
                    ProbeError::failed(
                        "index_unreadable",
                        format!("cannot read {}: {error}", file.relative),
                    )
                })?;
                let _ = read_container(&bytes, file, segment_limits)?;
                json!({
                    "path": file.relative,
                    "bytes": file.bytes,
                    "kind": file.role.label(),
                    "container": true,
                })
            }
            FileRole::CurrentMetadata | FileRole::LockMetadata => {
                metadata_file_bytes =
                    checked_sum(metadata_file_bytes, file.bytes, "metadata_file_bytes")?;
                json!({
                    "path": file.relative,
                    "bytes": file.bytes,
                    "kind": file.role.label(),
                    "container": false,
                })
            }
        };
        file_records.push(record);
    }

    let classified_total = segment_file_bytes
        .checked_add(manifest_file_bytes)
        .and_then(|value| value.checked_add(mutation_state_file_bytes))
        .and_then(|value| value.checked_add(metadata_file_bytes))
        .ok_or_else(|| {
            ProbeError::failed("inventory_overflow", "classified byte total overflowed")
        })?;
    if classified_total != total_file_bytes {
        return Err(ProbeError::failed(
            "inventory_reconcile",
            format!("classified {classified_total} bytes but enumerated {total_file_bytes}"),
        ));
    }
    if segment_documents_total != snapshot_documents {
        return Err(ProbeError::failed(
            "inventory_documents",
            format!(
                "segment containers declare {segment_documents_total} documents but the \
                 snapshot reports {snapshot_documents}"
            ),
        ));
    }
    if segments.len() != snapshot_segments {
        return Err(ProbeError::failed(
            "inventory_segments",
            format!(
                "{} segment files but the snapshot reports {snapshot_segments} segments",
                segments.len()
            ),
        ));
    }
    let nonsection_reconcile = segment_section_bytes_total
        .checked_add(segment_nonsection_bytes_total)
        .ok_or_else(|| ProbeError::failed("inventory_overflow", "segment byte total overflowed"))?;
    if nonsection_reconcile != segment_file_bytes {
        return Err(ProbeError::failed(
            "inventory_reconcile",
            format!(
                "segment sections {segment_section_bytes_total} + overhead \
                 {segment_nonsection_bytes_total} != {segment_file_bytes}"
            ),
        ));
    }

    Ok(json!({
        "schema": INVENTORY_SCHEMA,
        "mode": "inventory",
        "n": n,
        "documents_verified": snapshot_documents,
        "segments_verified": snapshot_segments,
        "generation": generation,
        "file_count": files.len(),
        "total_file_bytes": total_file_bytes,
        "segment_file_bytes": segment_file_bytes,
        "manifest_file_bytes": manifest_file_bytes,
        "mutation_state_file_bytes": mutation_state_file_bytes,
        "metadata_file_bytes": metadata_file_bytes,
        "segment_section_bytes_total": segment_section_bytes_total,
        "segment_nonsection_bytes_total": segment_nonsection_bytes_total,
        "segment_documents_total": segment_documents_total,
        "section_bytes": section_bytes,
        "section_counts": section_counts,
        "segments": segments,
        "files": file_records,
        "reconciliation": {
            "classified_file_bytes": classified_total,
            "total_file_bytes": total_file_bytes,
            "bytes_reconciled": classified_total == total_file_bytes,
            "segment_sections_plus_overhead": nonsection_reconcile,
            "segment_file_bytes": segment_file_bytes,
            "segments_reconciled": nonsection_reconcile == segment_file_bytes,
        },
    }))
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn run(args: &Args) -> Result<Value, ProbeError> {
    let root = validate_index_dir(&args.index_dir)?;
    match args.mode {
        Mode::Single => {
            validate_tree(&root)?;
            let samples = reopen_samples(&root, args.n, 1)?;
            reopen_output(Mode::Single, args.n, &samples)
        }
        Mode::Loop => {
            validate_tree(&root)?;
            let iterations = args.iterations.expect("validated by parse_args");
            let samples = reopen_samples(&root, args.n, iterations)?;
            reopen_output(Mode::Loop, args.n, &samples)
        }
        Mode::Inventory => run_inventory(&root, args.n),
    }
}

fn main() {
    let args = match parse_args(std::env::args().skip(1)) {
        Ok(args) => args,
        Err(error) => {
            eprintln!("pr15f-reopen-probe: {error}");
            std::process::exit(EXIT_USAGE);
        }
    };
    match run(&args) {
        Ok(payload) => {
            let encoded = serde_json::to_string(&payload).expect("serializable probe payload");
            println!("{encoded}");
        }
        Err(error) => {
            eprintln!("pr15f-reopen-probe: {error}");
            std::process::exit(EXIT_FAILED);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
    use quervant_core::contract::value::FieldValue;

    fn fixture_index(root: &Path, documents: u64) -> Index {
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(root).expect("fs open"));
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema(),
            registry(),
            benchmark_limits(),
        )
        .expect("create");
        let mut writer = index.writer().expect("writer");
        for offset in 0..documents {
            let doc_id = format!("d{offset:08}");
            let key = DocumentKey::new(doc_id.clone()).expect("key");
            let mut document = Document::new(key);
            for (name, value) in [
                ("doc_id", doc_id.clone()),
                ("key", "singleton".to_owned()),
                ("group", "medium".to_owned()),
                ("body", "alpha beta".to_owned()),
                ("payload", format!("payload-{offset:08}")),
            ] {
                document
                    .insert(name, FieldValues::Single(FieldValue::Keyword(value)))
                    .expect("field");
            }
            writer.insert(document).expect("insert");
        }
        writer.commit().expect("commit");
        writer.close().expect("close");
        Index::open_with_limits(
            Arc::clone(&directory),
            schema(),
            registry(),
            benchmark_limits(),
        )
        .expect("reopen")
    }

    fn scratch_root(label: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "pr15f-probe-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        fs::create_dir_all(&path).expect("scratch dir");
        path
    }

    #[test]
    fn frozen_schema_has_the_five_adapter_fields() {
        let schema = schema();
        assert_eq!(schema.field_count(), 5);
        let mut names = schema
            .fields()
            .map(|field| field.name.clone())
            .collect::<Vec<_>>();
        names.sort();
        assert_eq!(names, vec!["body", "doc_id", "group", "key", "payload"]);
        let doc_id = schema.get("doc_id").expect("doc_id field");
        assert_eq!(doc_id.field_type, FieldType::Keyword);
        assert_eq!(doc_id.cardinality, Cardinality::Single);
        assert!(doc_id.options.indexed);
        assert!(doc_id.options.stored);
        assert!(doc_id.options.columnar);
        let key = schema.get("key").expect("key field");
        assert!(key.options.indexed && key.options.stored);
        assert!(!key.options.columnar);
        let body = schema.get("body").expect("body field");
        assert!(!body.options.indexed);
        assert!(body.options.stored);
    }

    #[test]
    fn frozen_benchmark_limits_are_the_adapter_values() {
        let limits = benchmark_limits();
        assert_eq!(limits.max_pending_docs(), 1_000_000);
        assert_eq!(limits.max_pending_bytes(), 512 * 1024 * 1024);
        assert_eq!(limits.max_replay_entries(), 1_000_000);
        // The adapter request is clamped by the published replay ceiling.
        assert_eq!(limits.max_replay_bytes(), 256 * 1024 * 1024);
    }

    #[test]
    fn cli_accepts_only_the_fixed_forms() {
        let single = parse_args(
            ["--mode", "single", "--index-dir", "/tmp/x", "--n", "10000"].map(str::to_owned),
        )
        .expect("single");
        assert_eq!(single.mode, Mode::Single);
        assert_eq!(single.n, 10_000);
        assert_eq!(single.iterations, None);

        let looped = parse_args(
            [
                "--mode",
                "loop",
                "--index-dir",
                "/tmp/x",
                "--n",
                "100000",
                "--iterations",
                "64",
            ]
            .map(str::to_owned),
        )
        .expect("loop");
        assert_eq!(looped.iterations, Some(64));

        for arguments in [
            vec!["--mode", "single", "--index-dir", "/tmp/x", "--n", "123"],
            vec!["--mode", "bogus", "--index-dir", "/tmp/x", "--n", "10000"],
            vec!["--mode", "loop", "--index-dir", "/tmp/x", "--n", "10000"],
            vec![
                "--mode",
                "single",
                "--index-dir",
                "/tmp/x",
                "--n",
                "10000",
                "--iterations",
                "64",
            ],
            vec![
                "--mode",
                "single",
                "--index-dir",
                "/tmp/x",
                "--n",
                "10000",
                "--attestation",
                "fake",
            ],
            vec![
                "--mode",
                "single",
                "--index-dir",
                "/tmp/x",
                "--n",
                "10000",
                "--n",
                "10000",
            ],
        ] {
            assert!(
                parse_args(arguments.into_iter().map(str::to_owned)).is_err(),
                "arguments must be rejected"
            );
        }
    }

    #[test]
    fn timed_stages_are_positive_disjoint_and_add_up() {
        let root = scratch_root("timed");
        let index = fixture_index(&root, 8);
        drop(index);
        let sample = one_reopen(&root, 8).expect("sample");
        assert!(sample.fs_directory_open_ns > 0);
        assert!(sample.index_open_ns > 0);
        assert!(sample.snapshot_acquire_ns > 0);
        assert_eq!(
            sample.reopen_core_ns,
            sample.index_open_ns + sample.snapshot_acquire_ns
        );
        assert_eq!(
            sample.reopen_total_ns,
            sample.fs_directory_open_ns + sample.reopen_core_ns
        );
        assert_eq!(sample.documents, 8);
        assert_eq!(sample.segments, 1);
        assert!(sample.generation >= 1);
        fs::remove_dir_all(&root).expect("cleanup");
    }

    #[test]
    fn loop_retains_every_sample_and_rejects_wrong_document_count() {
        let root = scratch_root("loop");
        let index = fixture_index(&root, 4);
        drop(index);
        let samples = reopen_samples(&root, 4, 3).expect("samples");
        assert_eq!(samples.len(), 3);
        assert!(one_reopen(&root, 5).is_err());
        fs::remove_dir_all(&root).expect("cleanup");
    }

    #[test]
    fn inventory_reconciles_every_byte() {
        let root = scratch_root("inventory");
        let index = fixture_index(&root, 16);
        drop(index);
        let payload = run_inventory(&root, 16).expect("inventory");
        assert_eq!(payload["schema"], INVENTORY_SCHEMA);
        assert_eq!(payload["documents_verified"], 16);
        assert_eq!(payload["segments_verified"], 1);
        let total = payload["total_file_bytes"].as_u64().expect("total");
        let classified = payload["segment_file_bytes"].as_u64().expect("segments")
            + payload["manifest_file_bytes"].as_u64().expect("manifest")
            + payload["mutation_state_file_bytes"]
                .as_u64()
                .expect("mutation")
            + payload["metadata_file_bytes"].as_u64().expect("metadata");
        assert_eq!(total, classified);
        assert_eq!(
            payload["segment_section_bytes_total"]
                .as_u64()
                .expect("sections")
                + payload["segment_nonsection_bytes_total"]
                    .as_u64()
                    .expect("overhead"),
            payload["segment_file_bytes"]
                .as_u64()
                .expect("segment bytes")
        );
        assert!(payload["section_bytes"]["Stored"].as_u64().expect("stored") > 0);
        fs::remove_dir_all(&root).expect("cleanup");
    }

    #[test]
    fn inventory_rejects_foreign_files_and_container_kind_mismatch() {
        let root = scratch_root("foreign");
        let index = fixture_index(&root, 2);
        drop(index);
        fs::write(root.join("index/notes.txt"), b"nope").expect("foreign write");
        assert!(run_inventory(&root, 2).is_err());
        fs::remove_file(root.join("index/notes.txt")).expect("cleanup foreign");

        let segments = root.join("index/segments");
        let segment = fs::read_dir(&segments)
            .expect("segments")
            .next()
            .expect("one segment")
            .expect("entry")
            .path();
        let manifest = fs::read_dir(root.join("index/manifests"))
            .expect("manifests")
            .next()
            .expect("one manifest")
            .expect("entry")
            .path();
        fs::copy(&manifest, &segment).expect("swap bytes");
        assert!(run_inventory(&root, 2).is_err());
        fs::remove_dir_all(&root).expect("cleanup");
    }

    #[test]
    fn inventory_rejects_truncated_and_corrupt_containers() {
        let root = scratch_root("corrupt");
        let index = fixture_index(&root, 4);
        drop(index);
        let segment = fs::read_dir(root.join("index/segments"))
            .expect("segments")
            .next()
            .expect("one segment")
            .expect("entry")
            .path();
        let original = fs::read(&segment).expect("read segment");

        // Truncated footer.
        fs::write(&segment, &original[..original.len() - 8]).expect("truncate");
        assert!(run_inventory(&root, 4).is_err());

        // Corrupted envelope digest in the footer.
        let mut corrupted = original.clone();
        let len = corrupted.len();
        corrupted[len - 40] ^= 0xFF;
        fs::write(&segment, &corrupted).expect("corrupt");
        assert!(run_inventory(&root, 4).is_err());

        // Unrecognized magic is refused by the index open path and by the
        // explicit container classifier (tested below).
        let mut wrong_magic = original.clone();
        wrong_magic[..8].copy_from_slice(b"NOTASEG1");
        fs::write(&segment, &wrong_magic).expect("wrong magic");
        assert!(run_inventory(&root, 4).is_err());

        fs::write(&segment, &original).expect("restore");
        assert!(run_inventory(&root, 4).is_ok());
        fs::remove_dir_all(&root).expect("cleanup");
    }

    #[test]
    fn container_classifier_rejects_wrong_magic_and_kind() {
        let root = scratch_root("classifier");
        let index = fixture_index(&root, 2);
        drop(index);
        let manifest_path = fs::read_dir(root.join("index/manifests"))
            .expect("manifests")
            .next()
            .expect("one manifest")
            .expect("entry")
            .path();
        let manifest = fs::read(&manifest_path).expect("manifest bytes");
        let limits = benchmark_limits();
        let file = IndexFile {
            relative: "index/segments/fake.seg".to_owned(),
            path: manifest_path.clone(),
            bytes: manifest.len() as u64,
            role: FileRole::Segment,
        };
        let error = read_container(&manifest, &file, limits.segment_limits())
            .expect_err("manifest bytes are not a segment");
        assert_eq!(error.kind, "index_container_kind");

        let mut wrong = manifest.clone();
        wrong[..8].copy_from_slice(b"NOTASEG1");
        let error = read_container(&wrong, &file, limits.segment_limits())
            .expect_err("unknown magic is refused");
        assert_eq!(error.kind, "index_magic");
        fs::remove_dir_all(&root).expect("cleanup");
    }

    #[test]
    fn index_directory_rejects_symlinks_and_missing_paths() {
        let root = scratch_root("index-path");
        let index = fixture_index(&root, 2);
        drop(index);
        let link = root.with_extension("link");
        std::os::unix::fs::symlink(&root, &link).expect("symlink root");
        let error = validate_index_dir(&link).expect_err("symlink root refused");
        assert_eq!(error.kind, "index_symlink");
        std::fs::remove_file(&link).expect("cleanup link");
        assert!(validate_index_dir(&root.join("missing")).is_err());
        assert!(validate_index_dir(Path::new("relative/path")).is_err());
        fs::remove_dir_all(&root).expect("cleanup");
    }

    #[test]
    fn index_tree_rejects_symlinks() {
        let root = scratch_root("symlink");
        let index = fixture_index(&root, 2);
        drop(index);
        let target = root.join("index/state");
        std::os::unix::fs::symlink(&target, root.join("index/link")).expect("symlink");
        let error = validate_tree(&root).expect_err("symlink refused");
        assert_eq!(error.kind, "index_symlink");
        fs::remove_dir_all(&root).expect("cleanup");
    }
}
