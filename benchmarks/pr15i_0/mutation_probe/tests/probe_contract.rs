//! PR15I-0 mutation-state sidecar probe contract tests (T11–T16).
//!
//! Every fixture is generated with the **public** `ContainerBuilder`, so an
//! intentional defect still carries a valid envelope unless the test explicitly
//! corrupts the original bytes. No real prepared index is modified and no
//! malformed sample is published as production evidence.

use std::collections::BTreeMap;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};

use pr15i0_mutation_probe::{
    BREAKDOWN_SCHEMA, MAX_SIDECAR_BYTES, analyze_breakdown, component_names, is_lower_hex_sha,
    probe_index_root, report_json, sum_component_map,
};
use quervant_core::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use quervant_core::contract::schema::Schema;
use quervant_core::index::CurrentPointer;
use quervant_core::segment::format::{
    ContainerBuilder, ContainerKind, FEATURE_MUTATION_STATE, FEATURE_MUTATION_STATE_V2, SectionKind,
};
use quervant_core::segment::{CodecSchema, Manifest, MutationStateRef};
use quervant_objectstore::ContentDigest;

// ---------------------------------------------------------------------------
// Test-only payload writer (never a production encoder)
// ---------------------------------------------------------------------------

#[derive(Default)]
struct Payload {
    bytes: Vec<u8>,
}

impl Payload {
    fn u8(&mut self, value: u8) -> &mut Self {
        self.bytes.push(value);
        self
    }

    fn u16(&mut self, value: u16) -> &mut Self {
        self.bytes.extend_from_slice(&value.to_le_bytes());
        self
    }

    fn u32(&mut self, value: u32) -> &mut Self {
        self.bytes.extend_from_slice(&value.to_le_bytes());
        self
    }

    fn u64(&mut self, value: u64) -> &mut Self {
        self.bytes.extend_from_slice(&value.to_le_bytes());
        self
    }

    fn raw(&mut self, value: &[u8]) -> &mut Self {
        self.bytes.extend_from_slice(value);
        self
    }

    fn len_prefixed(&mut self, value: &[u8]) -> &mut Self {
        assert!(u16::try_from(value.len()).is_ok(), "fixture key too long");
        self.u16(value.len() as u16).raw(value)
    }
}

/// Deterministic non-cryptographic test bytes for a 32-byte fingerprint.
fn fingerprint(tag: u8) -> [u8; 32] {
    let mut out = [0u8; 32];
    for (index, slot) in out.iter_mut().enumerate() {
        *slot = tag.wrapping_add(index as u8);
    }
    out
}

fn live_row(payload: &mut Payload, key: &str, revision: u64, segment: &str, doc_id: u64) {
    payload
        .len_prefixed(key.as_bytes())
        .u64(revision)
        .u8(1)
        .len_prefixed(segment.as_bytes())
        .u64(doc_id);
}

fn deleted_row(payload: &mut Payload, key: &str, revision: u64) {
    payload.len_prefixed(key.as_bytes()).u64(revision).u8(0);
}

fn replay_row(payload: &mut Payload, token: &str, key: &str, intent: u8, revision: u64) {
    payload
        .len_prefixed(token.as_bytes())
        .raw(&fingerprint(7))
        .len_prefixed(key.as_bytes())
        .u8(intent)
        .u64(revision);
}

fn wrap_payload(payload: &Payload, version: u16) -> Vec<u8> {
    let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
    builder.require_feature(FEATURE_MUTATION_STATE, 1);
    if version == 2 {
        builder.require_feature(FEATURE_MUTATION_STATE_V2, 1);
    }
    builder.section(SectionKind::MutationState, 0, 0, payload.bytes.clone());
    builder.build().expect("fixture container builds")
}

fn v1_payload(rows: u32) -> Payload {
    let mut payload = Payload::default();
    payload.u16(1).u32(rows);
    payload
}

fn v2_payload(rows: u32) -> Payload {
    let mut payload = Payload::default();
    payload.u16(2).u32(rows);
    payload
}

// ---------------------------------------------------------------------------
// Synthetic prepared index roots (public CURRENT/Manifest APIs only)
// ---------------------------------------------------------------------------

fn codec_schema() -> CodecSchema {
    let schema = Schema::new(Vec::new(), None).expect("empty schema is valid");
    let registry = AnalyzerRegistry::builtin();
    let bindings =
        SchemaAnalyzerBindings::resolve(&schema, &registry).expect("empty bindings resolve");
    CodecSchema::from_contract(&schema, &bindings).expect("empty codec schema encodes")
}

struct SyntheticIndex {
    root: PathBuf,
}

impl SyntheticIndex {
    /// Build a prepared-index-shaped directory holding `state_bytes` as the
    /// authoritative generation state object.
    fn new(parent: &Path, name: &str, state_bytes: &[u8]) -> Self {
        let root = parent.join(name).join("index-root");
        fs::create_dir_all(root.join("index/manifests")).expect("manifests dir");
        fs::create_dir_all(root.join("index/state")).expect("state dir");

        let digest = ContentDigest::sha256_v1(state_bytes);
        let object_key = format!("index/state/{}.state", digest.to_hex());
        fs::write(root.join(&object_key), state_bytes).expect("state write");

        let manifest = Manifest {
            schema: codec_schema(),
            segments: Vec::new(),
            required_features: vec![(FEATURE_MUTATION_STATE, 1)],
            optional_features: Vec::new(),
            mutation_state: Some(MutationStateRef {
                object_key,
                content_length: state_bytes.len() as u64,
                content_digest: *digest.as_bytes(),
            }),
        };
        let manifest_bytes = manifest.encode().expect("manifest encodes");
        let pointer = CurrentPointer::new(
            1,
            manifest_bytes.len() as u64,
            ContentDigest::sha256_v1(&manifest_bytes),
        )
        .expect("current pointer");
        fs::write(root.join(pointer.manifest_key().as_str()), &manifest_bytes)
            .expect("manifest write");
        fs::write(
            root.join("index/CURRENT"),
            pointer.encode().expect("CURRENT encodes"),
        )
        .expect("CURRENT write");

        Self { root }
    }
}

fn scratch(name: &str) -> PathBuf {
    let base = std::env::temp_dir().join(format!(
        "pr15i0-probe-{}-{}-{name}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    fs::create_dir_all(&base).expect("scratch dir");
    base
}

const GOOD_SHA: &str = "0123456789abcdef0123456789abcdef01234567";

// ---------------------------------------------------------------------------
// T11 — valid version-1 sidecars reconcile exactly
// ---------------------------------------------------------------------------

#[test]
fn t11_empty_v1_state_reconciles() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let breakdown = analyze_breakdown(&bytes).expect("empty state is valid");
    assert_eq!(breakdown.payload_version, 1);
    assert_eq!(breakdown.row_count, 0);
    assert_eq!(breakdown.replay_count, 0);
    assert_eq!(breakdown.components.state_header_bytes, 6);
    assert_eq!(breakdown.components.replay_header_bytes, 4);
    assert_eq!(breakdown.components.batch_replay_opaque_bytes, 0);
    assert_eq!(breakdown.payload_bytes, 10);
    assert_eq!(
        breakdown.sidecar_file_bytes,
        breakdown.payload_bytes + breakdown.container_overhead_bytes
    );
    assert!(breakdown.container_overhead_bytes > 0);
    assert_eq!(breakdown.key_validation, "PUBLIC_CONSTRUCTOR_VALIDATED");
}

#[test]
fn t11_single_live_row_is_exact() {
    let mut payload = v1_payload(1);
    live_row(&mut payload, "a", 1, "seg", 9);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let breakdown = analyze_breakdown(&bytes).expect("single live row");
    assert_eq!(breakdown.row_count, 1);
    assert_eq!(breakdown.live_count, 1);
    assert_eq!(breakdown.deleted_count, 0);
    assert_eq!(breakdown.components.row_key_prefix_bytes, 2);
    assert_eq!(breakdown.components.row_key_bytes, 1);
    assert_eq!(breakdown.components.row_revision_bytes, 8);
    assert_eq!(breakdown.components.row_status_bytes, 1);
    assert_eq!(breakdown.components.live_pointer_prefix_bytes, 2);
    assert_eq!(breakdown.components.live_pointer_id_bytes, 3);
    assert_eq!(breakdown.components.live_doc_id_bytes, 8);
    // 6 header + (2+1+8+1+2+3+8) row + 4 replay header = 35
    assert_eq!(breakdown.payload_bytes, 6 + 25 + 4);
}

#[test]
fn t11_live_and_deleted_rows_with_replay_reconcile() {
    let mut payload = v1_payload(2);
    deleted_row(&mut payload, "alpha", 2);
    live_row(&mut payload, "beta", 5, "seg-1", 42);
    payload.u32(2);
    replay_row(&mut payload, "tok-1", "alpha", 2, 2);
    replay_row(&mut payload, "tok-2", "beta", 1, 5);

    let bytes = wrap_payload(&payload, 1);
    let breakdown = analyze_breakdown(&bytes).expect("mixed state");
    assert_eq!(breakdown.row_count, 2);
    assert_eq!(breakdown.replay_count, 2);
    assert_eq!(breakdown.live_count, 1);
    assert_eq!(breakdown.deleted_count, 1);
    assert_eq!(breakdown.components.row_key_prefix_bytes, 4);
    assert_eq!(breakdown.components.row_key_bytes, 5 + 4);
    assert_eq!(breakdown.components.row_revision_bytes, 16);
    assert_eq!(breakdown.components.row_status_bytes, 2);
    assert_eq!(breakdown.components.live_pointer_prefix_bytes, 2);
    assert_eq!(breakdown.components.live_pointer_id_bytes, 5);
    assert_eq!(breakdown.components.live_doc_id_bytes, 8);
    assert_eq!(breakdown.components.replay_token_prefix_bytes, 4);
    assert_eq!(breakdown.components.replay_token_bytes, 10);
    assert_eq!(breakdown.components.replay_fingerprint_bytes, 64);
    assert_eq!(breakdown.components.replay_key_prefix_bytes, 4);
    assert_eq!(breakdown.components.replay_key_bytes, 9);
    assert_eq!(breakdown.components.replay_intent_bytes, 2);
    assert_eq!(breakdown.components.replay_revision_bytes, 16);
    assert_eq!(breakdown.payload_bytes, payload.bytes.len() as u64);

    let map: BTreeMap<String, u64> = breakdown
        .components
        .fields()
        .into_iter()
        .map(|(name, value)| (name.to_owned(), value))
        .collect();
    assert_eq!(
        sum_component_map(&map).expect("sum"),
        breakdown.payload_bytes
    );
    assert_eq!(
        component_names().len(),
        17,
        "the component vocabulary is frozen"
    );
}

#[test]
fn t11_unicode_key_is_charged_by_utf8_bytes() {
    // "é" is two UTF-8 bytes; "日本" is six.
    let mut payload = v1_payload(2);
    deleted_row(&mut payload, "é", 1);
    live_row(&mut payload, "日本", 2, "s", 1);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let breakdown = analyze_breakdown(&bytes).expect("unicode keys");
    assert_eq!(breakdown.components.row_key_bytes, 2 + 6);
    assert_eq!(breakdown.components.row_key_prefix_bytes, 4);
}

// ---------------------------------------------------------------------------
// T12 — envelope, kind, section and feature failures fail closed
// ---------------------------------------------------------------------------

#[test]
fn t12_wrong_container_kind_is_refused() {
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, 0);
    builder.require_feature(FEATURE_MUTATION_STATE, 1);
    builder.section(SectionKind::MutationState, 0, 0, v1_payload(0).bytes);
    let bytes = builder.build().expect("builds");
    let error = analyze_breakdown(&bytes).expect_err("wrong kind");
    assert_eq!(error.class(), "wrong_kind");
}

#[test]
fn t12_wrong_section_kind_is_refused() {
    let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
    builder.require_feature(FEATURE_MUTATION_STATE, 1);
    builder.section(SectionKind::Stored, 0, 0, v1_payload(0).bytes);
    let bytes = builder.build().expect("builds");
    let error = analyze_breakdown(&bytes).expect_err("wrong section");
    assert_eq!(error.class(), "wrong_kind");
}

#[test]
fn t12_unknown_required_feature_is_refused() {
    let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
    builder.require_feature(FEATURE_MUTATION_STATE, 1);
    builder.require_feature(0x00FF, 1);
    builder.section(SectionKind::MutationState, 0, 0, v1_payload(0).bytes);
    let bytes = builder.build().expect("builds");
    let error = analyze_breakdown(&bytes).expect_err("unknown feature");
    assert_eq!(error.class(), "unsupported_feature");
}

#[test]
fn t12_missing_mutation_state_feature_is_refused() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
    builder.section(SectionKind::MutationState, 0, 0, payload.bytes);
    let bytes = builder.build().expect("builds");
    let error = analyze_breakdown(&bytes).expect_err("missing feature");
    assert_eq!(error.class(), "unsupported_feature");
}

#[test]
fn t12_bad_envelope_digest_is_refused() {
    let mut bytes = wrap_payload(&v1_payload(0), 1);
    let last = bytes.len() - 1;
    bytes[last] ^= 0xFF;
    let error = analyze_breakdown(&bytes).expect_err("bad digest");
    assert_eq!(error.class(), "bad_container");
}

#[test]
fn t12_unsupported_payload_version_is_refused() {
    let mut payload = Payload::default();
    payload.u16(3).u32(0).u32(0);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("version 3");
    assert_eq!(error.class(), "unsupported_payload");
}

#[test]
fn t12_v2_payload_without_v2_feature_is_refused() {
    let mut payload = v2_payload(0);
    payload.u32(0).u32(0);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("v2 marker without feature");
    assert_eq!(error.class(), "unsupported_feature");
}

// ---------------------------------------------------------------------------
// T13 — row-level corruption fails closed
// ---------------------------------------------------------------------------

fn expect_row_failure(mut payload: Payload, class: &str, label: &str) {
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err(label);
    assert_eq!(error.class(), class, "{label}");
}

#[test]
fn t13_truncated_row_key_is_refused() {
    let mut payload = v1_payload(1);
    payload.u16(8).raw(b"abc");
    expect_row_failure(payload, "bad_container", "truncated key");
}

#[test]
fn t13_zero_row_revision_is_refused() {
    let mut payload = v1_payload(1);
    deleted_row(&mut payload, "a", 0);
    expect_row_failure(payload, "corrupt_payload", "zero revision");
}

#[test]
fn t13_invalid_status_is_refused() {
    let mut payload = v1_payload(1);
    payload.len_prefixed(b"a").u64(1).u8(2);
    expect_row_failure(payload, "corrupt_payload", "invalid status");
}

#[test]
fn t13_invalid_utf8_key_is_refused() {
    let mut payload = v1_payload(1);
    payload.len_prefixed(&[0xFF, 0xFE]).u64(1).u8(0);
    expect_row_failure(payload, "corrupt_payload", "invalid utf8");
}

#[test]
fn t13_empty_key_is_refused() {
    let mut payload = v1_payload(1);
    deleted_row(&mut payload, "", 1);
    expect_row_failure(payload, "corrupt_payload", "empty key");
}

#[test]
fn t13_duplicate_rows_are_refused() {
    let mut payload = v1_payload(2);
    deleted_row(&mut payload, "same", 1);
    deleted_row(&mut payload, "same", 2);
    expect_row_failure(payload, "corrupt_payload", "duplicate rows");
}

#[test]
fn t13_descending_rows_are_refused() {
    let mut payload = v1_payload(2);
    deleted_row(&mut payload, "b", 1);
    deleted_row(&mut payload, "a", 2);
    expect_row_failure(payload, "corrupt_payload", "descending rows");
}

#[test]
fn t13_empty_segment_id_is_refused() {
    let mut payload = v1_payload(1);
    payload.len_prefixed(b"a").u64(1).u8(1).u16(0).u64(1);
    expect_row_failure(payload, "corrupt_payload", "empty segment id");
}

#[test]
fn t13_truncated_live_pointer_is_refused() {
    let mut payload = v1_payload(1);
    payload.len_prefixed(b"a").u64(1).u8(1).len_prefixed(b"seg");
    // Missing the trailing u64 doc id.
    expect_row_failure(payload, "bad_container", "truncated pointer");
}

#[test]
fn t13_v1_trailing_bytes_are_refused() {
    let mut payload = v1_payload(0);
    payload.u32(0).u8(0);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("trailing bytes");
    assert_eq!(error.class(), "bad_container");
}

#[test]
fn t13_oversized_row_count_is_refused() {
    let mut payload = Payload::default();
    payload.u16(1).u32(1_000_000);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("row count");
    assert_eq!(error.class(), "bad_container");
}

// ---------------------------------------------------------------------------
// T14 — replay-level corruption fails closed
// ---------------------------------------------------------------------------

#[test]
fn t14_truncated_replay_token_is_refused() {
    let mut payload = v1_payload(0);
    payload.u32(1).u16(4).raw(b"ab");
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("truncated token");
    assert_eq!(error.class(), "bad_container");
}

#[test]
fn t14_short_fingerprint_is_refused() {
    let mut payload = v1_payload(0);
    payload.u32(1).len_prefixed(b"t").raw(&[0u8; 31]);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("short fingerprint");
    assert_eq!(error.class(), "bad_container");
}

#[test]
fn t14_invalid_intent_is_refused() {
    let mut payload = v1_payload(0);
    payload.u32(1);
    replay_row(&mut payload, "t", "k", 3, 1);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("invalid intent");
    assert_eq!(error.class(), "corrupt_payload");
}

#[test]
fn t14_zero_replay_revision_is_refused() {
    let mut payload = v1_payload(0);
    payload.u32(1);
    replay_row(&mut payload, "t", "k", 0, 0);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("zero replay revision");
    assert_eq!(error.class(), "corrupt_payload");
}

#[test]
fn t14_duplicate_replay_tokens_are_refused() {
    let mut payload = v1_payload(0);
    payload.u32(2);
    replay_row(&mut payload, "same", "a", 0, 1);
    replay_row(&mut payload, "same", "b", 0, 2);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("duplicate tokens");
    assert_eq!(error.class(), "corrupt_payload");
}

#[test]
fn t14_descending_replay_tokens_are_refused() {
    let mut payload = v1_payload(0);
    payload.u32(2);
    replay_row(&mut payload, "b", "a", 0, 1);
    replay_row(&mut payload, "a", "b", 0, 2);
    let bytes = wrap_payload(&payload, 1);
    let error = analyze_breakdown(&bytes).expect_err("descending tokens");
    assert_eq!(error.class(), "corrupt_payload");
}

// ---------------------------------------------------------------------------
// T15 — version-2 batch remainder is opaque and exactly accounted
// ---------------------------------------------------------------------------

#[test]
fn t15_v2_empty_batch_is_four_opaque_bytes() {
    let mut payload = v2_payload(0);
    payload.u32(0).u32(0);
    let bytes = wrap_payload(&payload, 2);
    let breakdown = analyze_breakdown(&bytes).expect("v2 with empty batch");
    assert_eq!(breakdown.payload_version, 2);
    assert_eq!(breakdown.components.batch_replay_opaque_bytes, 4);
    assert_eq!(breakdown.payload_bytes, 6 + 4 + 4);
    assert_eq!(
        breakdown.sidecar_file_bytes,
        breakdown.payload_bytes + breakdown.container_overhead_bytes
    );
}

#[test]
fn t15_v2_nonempty_batch_is_opaque_and_exact() {
    let mut payload = v2_payload(0);
    payload.u32(0);
    payload.u32(2).raw(&[0u8; 10]);
    let tail = payload.bytes.len() as u64 - 6 - 4;
    let bytes = wrap_payload(&payload, 2);
    let breakdown = analyze_breakdown(&bytes).expect("v2 with batch rows");
    assert_eq!(breakdown.components.batch_replay_opaque_bytes, tail);
    assert_eq!(breakdown.payload_bytes, 6 + 4 + tail);
}

#[test]
fn t15_v2_short_batch_span_is_refused() {
    let mut payload = v2_payload(0);
    payload.u32(0).raw(&[0, 0, 0]);
    let bytes = wrap_payload(&payload, 2);
    let error = analyze_breakdown(&bytes).expect_err("three trailing bytes");
    assert_eq!(error.class(), "corrupt_payload");
}

#[test]
fn t15_v2_empty_batch_span_is_refused() {
    let mut payload = v2_payload(0);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 2);
    let error = analyze_breakdown(&bytes).expect_err("no batch span");
    assert_eq!(error.class(), "corrupt_payload");
}

#[test]
fn t15_report_marks_batch_detail_unverified() {
    let mut payload = v2_payload(0);
    payload.u32(0).u32(0);
    let bytes = wrap_payload(&payload, 2);
    let scratch = scratch("report");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let report =
        probe_index_root(&index.root, MAX_SIDECAR_BYTES, GOOD_SHA).expect("probe succeeds");
    let json = report_json(&report, GOOD_SHA);
    assert_eq!(json["schema"], BREAKDOWN_SCHEMA);
    assert_eq!(
        json["batch_replay_detail"],
        "SEMANTIC_BATCH_DETAIL_NOT_VERIFIED"
    );
    // No semantic batch detail may be invented.
    let text = json.to_string();
    assert!(!text.contains("batch_row_count"));
    fs::remove_dir_all(scratch).ok();
}

// ---------------------------------------------------------------------------
// T16 — path, size and original-byte integrity failures
// ---------------------------------------------------------------------------

#[test]
fn t16_max_bytes_bound_is_enforced() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let scratch = scratch("maxbytes");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let error = probe_index_root(&index.root, 16, GOOD_SHA).expect_err("too large");
    assert_eq!(error.class(), "too_large");
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_symlinked_state_file_is_refused() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let scratch = scratch("symlink");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let state_dir = index.root.join("index/state");
    let entry = fs::read_dir(&state_dir)
        .expect("state dir")
        .next()
        .expect("one entry")
        .expect("entry")
        .path();
    let target = scratch.join("outside.state");
    fs::rename(&entry, &target).expect("move");
    symlink(&target, &entry).expect("symlink");
    let error = probe_index_root(&index.root, MAX_SIDECAR_BYTES, GOOD_SHA)
        .expect_err("symlink must be refused");
    assert_eq!(error.class(), "invalid_path");
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_stale_digest_is_refused() {
    let mut base = v1_payload(0);
    base.u32(0);
    let bytes = wrap_payload(&base, 1);
    let scratch = scratch("stale");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let state_dir = index.root.join("index/state");
    let entry = fs::read_dir(&state_dir)
        .expect("state dir")
        .next()
        .expect("one entry")
        .expect("entry")
        .path();
    // Rewrite the file with valid envelope bytes but a different content digest.
    let mut other = v1_payload(1);
    deleted_row(&mut other, "x", 1);
    other.u32(0);
    fs::write(&entry, wrap_payload(&other, 1)).expect("rewrite");
    let error =
        probe_index_root(&index.root, MAX_SIDECAR_BYTES, GOOD_SHA).expect_err("digest mismatch");
    assert_eq!(error.class(), "stale_or_unverified");
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_corrupted_original_bytes_fail_before_any_accounting() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let mut bytes = wrap_payload(&payload, 1);
    let middle = bytes.len() / 2;
    bytes[middle] ^= 0x01;
    let scratch = scratch("corrupt");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let error = probe_index_root(&index.root, MAX_SIDECAR_BYTES, GOOD_SHA)
        .expect_err("corruption is detected");
    assert!(matches!(
        error.class(),
        "bad_container" | "stale_or_unverified"
    ));
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_obsolete_state_objects_are_not_attributed() {
    let mut payload = v1_payload(1);
    deleted_row(&mut payload, "a", 1);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let scratch = scratch("obsolete");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    // An old-generation object that is *not* referenced by the committed manifest.
    let mut obsolete_payload = v1_payload(0);
    obsolete_payload.u32(0);
    let obsolete = wrap_payload(&obsolete_payload, 1);
    let obsolete_digest = ContentDigest::sha256_v1(&obsolete);
    fs::write(
        index
            .root
            .join(format!("index/state/{}.state", obsolete_digest.to_hex())),
        &obsolete,
    )
    .expect("obsolete write");

    let report =
        probe_index_root(&index.root, MAX_SIDECAR_BYTES, GOOD_SHA).expect("probe succeeds");
    assert_eq!(
        report.active.digest_hex,
        ContentDigest::sha256_v1(&bytes).to_hex()
    );
    assert_eq!(report.breakdown.sidecar_file_bytes, bytes.len() as u64);
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_missing_current_is_refused() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let scratch = scratch("nocurrent");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    fs::remove_file(index.root.join("index/CURRENT")).expect("remove CURRENT");
    let error =
        probe_index_root(&index.root, MAX_SIDECAR_BYTES, GOOD_SHA).expect_err("missing CURRENT");
    assert_eq!(error.class(), "invalid_path");
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_relative_index_root_is_refused() {
    let error = probe_index_root(Path::new("target/nowhere"), MAX_SIDECAR_BYTES, GOOD_SHA)
        .expect_err("relative root");
    assert_eq!(error.class(), "invalid_path");
}

#[test]
fn t16_invalid_source_sha_is_refused() {
    let bytes = wrap_payload(&v1_payload(0), 1);
    let scratch = scratch("sha");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let error = probe_index_root(&index.root, MAX_SIDECAR_BYTES, "ABCDEF").expect_err("bad sha");
    assert_eq!(error.class(), "usage");
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_source_sha_shape_is_strict() {
    assert!(is_lower_hex_sha(GOOD_SHA));
    assert!(!is_lower_hex_sha(
        "0123456789ABCDEF0123456789abcdef01234567"
    ));
    assert!(!is_lower_hex_sha("0123456789abcdef0123456789abcdef0123456"));
    assert!(!is_lower_hex_sha(
        "z123456789abcdef0123456789abcdef01234567"
    ));
}

// ---------------------------------------------------------------------------
// CLI-level exclusivity and classification
// ---------------------------------------------------------------------------

fn run_cli(args: &[&str]) -> std::process::Output {
    std::process::Command::new(env!("CARGO_BIN_EXE_mutation-probe"))
        .args(args)
        .output()
        .expect("spawn probe")
}

#[test]
fn t16_cli_rejects_missing_and_duplicate_flags() {
    let output = run_cli(&["--index-root", "/tmp"]);
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("\"class\":\"usage\""), "stderr: {stderr}");

    let output = run_cli(&[
        "--index-root",
        "/tmp",
        "--index-root",
        "/tmp",
        "--max-bytes",
        "1024",
        "--source-sha",
        GOOD_SHA,
        "--out",
        "/tmp/never.json",
    ]);
    assert_eq!(output.status.code(), Some(2));

    let output = run_cli(&[
        "--index-root",
        "/tmp",
        "--max-bytes",
        "1024",
        "--source-sha",
        GOOD_SHA,
        "--out",
        "/tmp/never.json",
        "--mode",
        "extra",
    ]);
    assert_eq!(output.status.code(), Some(2));
}

#[test]
fn t16_cli_writes_exclusive_output_only_on_success() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let bytes = wrap_payload(&payload, 1);
    let scratch = scratch("cli");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let out = scratch.join("out/breakdown.json");

    let output = run_cli(&[
        "--index-root",
        index.root.to_str().expect("utf8"),
        "--max-bytes",
        "268435456",
        "--source-sha",
        GOOD_SHA,
        "--out",
        out.to_str().expect("utf8"),
    ]);
    assert_eq!(
        output.status.code(),
        Some(0),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let written = fs::read_to_string(&out).expect("output written");
    assert!(written.contains(BREAKDOWN_SCHEMA));
    assert!(
        !written.contains("pr15i0-probe-"),
        "no absolute path leaked"
    );

    // A second run must never overwrite the sealed output.
    let output = run_cli(&[
        "--index-root",
        index.root.to_str().expect("utf8"),
        "--max-bytes",
        "268435456",
        "--source-sha",
        GOOD_SHA,
        "--out",
        out.to_str().expect("utf8"),
    ]);
    assert_eq!(output.status.code(), Some(3));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("\"class\":\"output_exists\""),
        "stderr: {stderr}"
    );
    fs::remove_dir_all(scratch).ok();
}

#[test]
fn t16_cli_failure_writes_no_output_file() {
    let mut payload = v1_payload(0);
    payload.u32(0);
    let mut bytes = wrap_payload(&payload, 1);
    let middle = bytes.len() / 2;
    bytes[middle] ^= 0x01;
    let scratch = scratch("clifail");
    let index = SyntheticIndex::new(&scratch, "index", &bytes);
    let out = scratch.join("out/breakdown.json");
    let output = run_cli(&[
        "--index-root",
        index.root.to_str().expect("utf8"),
        "--max-bytes",
        "268435456",
        "--source-sha",
        GOOD_SHA,
        "--out",
        out.to_str().expect("utf8"),
    ]);
    assert_eq!(output.status.code(), Some(3));
    assert!(!out.exists(), "a failed probe must not publish output");
    fs::remove_dir_all(scratch).ok();
}
