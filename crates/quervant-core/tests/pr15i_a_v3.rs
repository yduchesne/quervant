//! PR 15I-A compact mutation-state payload version 3: real index integration,
//! restart, point-in-time, fault injection and recovery (I01–I12, F01–F08).

mod common;
mod pr09_common;

use std::collections::BTreeSet;
use std::process::Command;
use std::sync::Arc;

use common::TempDir;
use pr09_common::{create, doc, hit_keys, memory, pr09_registry, pr09_schema, term};

use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::document::{DocumentKey, MutationRequest};
use quervant_core::contract::mutation::{
    MutationAction, MutationBatch, MutationCommand, MutationTarget,
};
use quervant_core::contract::query::Query;
use quervant_core::index::{
    CURRENT_KEY, CurrentPointer, Index, IndexError, IndexLimits, manifest_key_for,
};
use quervant_core::segment::format::{
    ByteWriter, ContainerBuilder, ContainerKind, FEATURE_MUTATION_STATE, FEATURE_MUTATION_STATE_V2,
    FEATURE_MUTATION_STATE_V3, SectionKind, parse_container, sha256,
};
use quervant_core::segment::{Manifest, MutationStateRef, SegmentLimits};
use quervant_core::storage::{
    Directory, FsDirectory, MemoryDirectory, ReadHandle, StorageError, StorageKey, StorageOp,
    WriteHandle,
};

const V3_VERSION: u16 = 3;
const FS_ENV: &str = "QUERVANT_PR15IA_DIR";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn fs_dir(path: &std::path::Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("fs directory"))
}

fn insert(writer: &mut quervant_core::index::IndexWriter, key: &str, title: &str) {
    writer
        .apply(MutationRequest::insert(doc(key, title, "", "x", 1)))
        .expect("insert");
}

fn upsert(writer: &mut quervant_core::index::IndexWriter, key: &str, title: &str) {
    writer
        .apply(MutationRequest::upsert(doc(key, title, "", "x", 2)))
        .expect("upsert");
}

fn delete(writer: &mut quervant_core::index::IndexWriter, key: &str) {
    writer
        .apply(MutationRequest::delete(DocumentKey::new(key).unwrap()))
        .expect("delete");
}

/// Live winner keys: the visibility-masked `MatchAll` result, never raw STORED
/// keys (which intentionally still contain superseded documents).
fn keys_of(snapshot: &quervant_core::index::ReaderSnapshot) -> BTreeSet<String> {
    hit_keys(snapshot, &Query::MatchAll).into_iter().collect()
}

fn read_bytes(directory: &Arc<dyn Directory>, key: &StorageKey) -> Vec<u8> {
    let handle = directory.open_read(key).expect("open read");
    let len = handle.len() as usize;
    let mut buffer = vec![0u8; len];
    let mut offset = 0;
    while offset < len {
        let read = handle
            .read_at(offset as u64, &mut buffer[offset..])
            .unwrap();
        assert!(read > 0, "short read");
        offset += read;
    }
    buffer
}

fn current(directory: &Arc<dyn Directory>) -> CurrentPointer {
    CurrentPointer::parse(&read_bytes(
        directory,
        &StorageKey::parse(CURRENT_KEY).unwrap(),
    ))
    .expect("parse CURRENT")
}

fn committed_manifest(directory: &Arc<dyn Directory>) -> (Manifest, u64) {
    let pointer = current(directory);
    let bytes = read_bytes(directory, pointer.manifest_key());
    (
        Manifest::decode(&bytes, &SegmentLimits::default()).expect("decode manifest"),
        pointer.generation(),
    )
}

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(out, "{byte:02x}").expect("writing to a String cannot fail");
    }
    out
}

/// The committed sidecar payload version plus the manifest required features.
fn committed_payload(directory: &Arc<dyn Directory>) -> (u16, Vec<(u16, u16)>) {
    let (manifest, _) = committed_manifest(directory);
    let reference = manifest.mutation_state.clone().expect("sidecar reference");
    let bytes = read_bytes(
        directory,
        &StorageKey::parse(&reference.object_key).unwrap(),
    );
    let view = parse_container(&bytes, &SegmentLimits::default()).expect("sidecar container");
    let body = view
        .body(SectionKind::MutationState)
        .expect("mutation-state section");
    (
        u16::from_le_bytes([body[0], body[1]]),
        manifest.required_features,
    )
}

fn has_feature(features: &[(u16, u16)], id: u16) -> bool {
    features.contains(&(id, 1))
}

fn install_bytes(directory: &Arc<dyn Directory>, key: &str, bytes: &[u8]) {
    let storage_key = StorageKey::parse(key).expect("storage key");
    let mut handle = directory.create(&storage_key).expect("create object");
    handle.write_all(bytes).expect("write object");
    handle.sync_all().expect("sync object");
    directory.sync().expect("sync directory");
}

fn publish(directory: &Arc<dyn Directory>, manifest: &Manifest, generation: u64) {
    let bytes = manifest.encode().expect("encode manifest");
    install_bytes(directory, &manifest_key_for(generation), &bytes);
    let pointer = CurrentPointer::new(
        generation,
        bytes.len() as u64,
        quervant_objectstore::ContentDigest::sha256_v1(&bytes),
    )
    .expect("pointer");
    directory
        .atomic_write(
            &StorageKey::parse(CURRENT_KEY).unwrap(),
            &pointer.encode().expect("encode pointer"),
        )
        .expect("publish CURRENT");
}

fn state_reference(bytes: &[u8]) -> MutationStateRef {
    let digest = sha256(bytes);
    MutationStateRef {
        object_key: format!("index/state/{}.state", hex(&digest)),
        content_length: bytes.len() as u64,
        content_digest: digest,
    }
}

fn no_cancel() -> CancellationFlag {
    CancellationFlag::new()
}

fn object_count(directory: &Arc<dyn Directory>) -> usize {
    let mut total = 0;
    for prefix in ["index/segments", "index/state", "index/manifests"] {
        total += directory.list(prefix, 100_000).expect("list").len();
    }
    total
}

fn run_child(test_name: &str, directory: &std::path::Path) -> bool {
    let executable = std::env::current_exe().expect("current exe");
    let status = Command::new(executable)
        .args(["--ignored", "--exact", test_name, "--nocapture"])
        .env(FS_ENV, directory)
        .status()
        .expect("spawn child test process");
    status.success()
}

fn legacy_v1_sidecar() -> Vec<u8> {
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(0); // rows
    payload.u32(0); // single-key replay
    let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
    builder.require_feature(FEATURE_MUTATION_STATE, 1);
    builder.section(SectionKind::MutationState, 0, 0, payload.into_vec());
    builder.build().expect("v1 sidecar")
}

fn legacy_v2_sidecar() -> Vec<u8> {
    let mut payload = ByteWriter::new();
    payload.u16(2);
    payload.u32(0); // rows
    payload.u32(0); // single-key replay
    payload.u32(1); // one batch replay record
    payload.len_prefixed_u16(b"legacy-batch").unwrap();
    payload.bytes(&[3u8; 32]);
    // Batch response: one Delete command with one key outcome at revision 5.
    payload.u32(1);
    payload.u8(0);
    payload.u32(0);
    payload.u64(1);
    payload.u32(1);
    payload.len_prefixed_u16(b"a").unwrap();
    payload.u8(2);
    payload.u8(1);
    payload.u64(5);
    payload.u8(0);
    let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
    builder.require_feature(FEATURE_MUTATION_STATE, 1);
    builder.require_feature(FEATURE_MUTATION_STATE_V2, 1);
    builder.section(SectionKind::MutationState, 0, 0, payload.into_vec());
    builder.build().expect("v2 sidecar")
}

// ---------------------------------------------------------------------------
// I01–I12: real index integration
// ---------------------------------------------------------------------------

#[test]
fn i01_memory_lifecycle_writes_v3_and_keeps_winners() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();

    insert(&mut writer, "a", "first");
    insert(&mut writer, "b", "keep");
    writer.flush().unwrap();
    upsert(&mut writer, "a", "second");
    delete(&mut writer, "b");
    writer.commit().unwrap();
    writer.close().unwrap();

    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));
    assert!(!has_feature(&features, FEATURE_MUTATION_STATE_V2));

    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(hit_keys(&reopened.snapshot(), &term("second")), vec!["a"]);
    assert!(hit_keys(&reopened.snapshot(), &term("first")).is_empty());
    assert!(hit_keys(&reopened.snapshot(), &term("keep")).is_empty());
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned()])
    );
}

#[test]
#[ignore = "child entrypoint for i02; run through the parent test"]
fn i02_child_reopen_verifies_v3_state() {
    let path = std::env::var(FS_ENV).expect("directory env");
    let directory = fs_dir(std::path::Path::new(&path));
    let index = Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry())
        .expect("child reopen");
    assert_eq!(hit_keys(&index.snapshot(), &term("second")), vec!["a"]);
    assert!(hit_keys(&index.snapshot(), &term("first")).is_empty());
    assert_eq!(keys_of(&index.snapshot()), BTreeSet::from(["a".to_owned()]));
    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));
}

#[test]
fn i02_filesystem_reopen_in_a_fresh_process_sees_v3() {
    let temp = TempDir::new("pr15ia-i02");
    {
        let directory = fs_dir(temp.path());
        let index = Index::create(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
        let mut writer = index.writer().unwrap();
        insert(&mut writer, "a", "first");
        insert(&mut writer, "b", "keep");
        writer.flush().unwrap();
        upsert(&mut writer, "a", "second");
        delete(&mut writer, "b");
        writer.commit().unwrap();
        writer.close().unwrap();
        let (version, _) = committed_payload(&directory);
        assert_eq!(version, V3_VERSION);
    }
    assert!(
        run_child("i02_child_reopen_verifies_v3_state", temp.path()),
        "fresh-process reopen failed"
    );
}

#[test]
fn i03_sidecar_manifest_v3_feature_mismatch_fails_closed() {
    // Direction 1: a V3 sidecar whose manifest does not require V3.
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.commit().unwrap();
    writer.close().unwrap();
    let (manifest, generation) = committed_manifest(&directory);
    assert!(
        manifest
            .required_features
            .contains(&(FEATURE_MUTATION_STATE_V3, 1))
    );
    let mut without_v3 = manifest.clone();
    without_v3
        .required_features
        .retain(|feature| *feature != (FEATURE_MUTATION_STATE_V3, 1));
    publish(&directory, &without_v3, generation + 1);
    let before = current(&directory).generation();
    let error =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap_err();
    assert!(
        matches!(error, IndexError::CorruptCommittedState { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(current(&directory).generation(), before);

    // Direction 2: a manifest requiring V3 over a legacy V1 payload.
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.commit().unwrap();
    writer.close().unwrap();
    let (mut manifest, generation) = committed_manifest(&directory);
    let sidecar = legacy_v1_sidecar();
    let reference = state_reference(&sidecar);
    install_bytes(&directory, &reference.object_key, &sidecar);
    manifest.mutation_state = Some(reference);
    manifest
        .required_features
        .push((FEATURE_MUTATION_STATE_V3, 1));
    manifest.required_features.sort_unstable();
    manifest.required_features.dedup();
    publish(&directory, &manifest, generation + 1);
    let before = current(&directory).generation();
    let error =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap_err();
    assert!(
        matches!(error, IndexError::CorruptCommittedState { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(current(&directory).generation(), before);
}

#[test]
fn i04_legacy_v1_generation_upgrades_on_a_real_commit() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.commit().unwrap();
    writer.close().unwrap();
    let (mut manifest, generation) = committed_manifest(&directory);
    let original_manifest_key = manifest_key_for(generation);
    let original_manifest_bytes = read_bytes(
        &directory,
        &StorageKey::parse(&original_manifest_key).unwrap(),
    );

    // Replace the generation with a digest-valid legacy V1 sidecar/manifest pair.
    let sidecar = legacy_v1_sidecar();
    let reference = state_reference(&sidecar);
    install_bytes(&directory, &reference.object_key, &sidecar);
    manifest.mutation_state = Some(reference);
    manifest
        .required_features
        .retain(|feature| *feature != (FEATURE_MUTATION_STATE_V3, 1));
    publish(&directory, &manifest, generation + 1);

    let legacy = Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry())
        .expect("legacy V1 generation opens");
    let (version, _) = committed_payload(&directory);
    assert_eq!(version, 1);

    let mut writer = legacy.writer().unwrap();
    insert(&mut writer, "b", "two");
    writer.commit().unwrap();
    writer.close().unwrap();

    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION, "a real commit must write V3");
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));
    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["b".to_owned()])
    );

    // The superseded legacy manifest object is still present and unchanged.
    assert_eq!(
        read_bytes(
            &directory,
            &StorageKey::parse(&original_manifest_key).unwrap()
        ),
        original_manifest_bytes
    );
}

#[test]
fn i05_legacy_v2_history_is_retained_and_replay_is_not_lost() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.commit().unwrap();
    writer.close().unwrap();
    let (mut manifest, generation) = committed_manifest(&directory);

    // Digest-valid legacy V2 sidecar with one batch replay record and no V3.
    let sidecar = legacy_v2_sidecar();
    let reference = state_reference(&sidecar);
    install_bytes(&directory, &reference.object_key, &sidecar);
    manifest.mutation_state = Some(reference);
    manifest
        .required_features
        .retain(|feature| *feature != (FEATURE_MUTATION_STATE_V3, 1));
    manifest
        .required_features
        .push((FEATURE_MUTATION_STATE_V2, 1));
    manifest.required_features.sort_unstable();
    manifest.required_features.dedup();
    publish(&directory, &manifest, generation + 1);

    let legacy = Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry())
        .expect("legacy V2 generation opens");
    let (version, features) = committed_payload(&directory);
    assert_eq!(version, 2);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V2));

    let mut writer = legacy.writer().unwrap();
    insert(&mut writer, "b", "two");
    writer.commit().unwrap();
    writer.close().unwrap();

    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));
    assert!(
        has_feature(&features, FEATURE_MUTATION_STATE_V2),
        "inherited V2 history must be retained"
    );
    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    // The crafted legacy state carries no key rows, so the segment document `a`
    // is not live; the upgrade must not resurrect it.
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["b".to_owned()])
    );
}

#[test]
fn i06_tokened_batch_then_untokened_commit_keeps_v2_history() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    let token = quervant_core::contract::document::IdempotencyKey::new("batch-1").unwrap();
    let batch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(DocumentKey::new("a").unwrap()),
        MutationAction::Insert(doc("a", "one", "", "x", 1)),
    )])
    .with_idempotency_key(token.clone());
    writer.apply_batch(&batch, &no_cancel()).unwrap();
    writer.commit().unwrap();

    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V2));
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));

    insert(&mut writer, "b", "two");
    writer.commit().unwrap();
    writer.close().unwrap();
    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V2));

    // The tokened batch still replays exactly after the untokened commit.
    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let replayed = writer.apply_batch(&batch, &no_cancel()).unwrap();
    assert!(replayed.replayed);
    assert!(
        replayed
            .outcomes
            .iter()
            .flat_map(|command| command.keys.iter())
            .all(|outcome| outcome.replayed)
    );
}

#[test]
fn i07_compaction_remaps_v3_pointers_and_preserves_an_old_pit() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "old");
    insert(&mut writer, "b", "keep");
    writer.flush().unwrap();
    upsert(&mut writer, "a", "new");
    writer.flush().unwrap();
    writer.commit().unwrap();

    let pit = writer.pin().unwrap();
    let before = keys_of(pit.snapshot());
    assert_eq!(before, BTreeSet::from(["a".to_owned(), "b".to_owned()]));

    let outcome = writer.compact().unwrap();
    assert!(
        !outcome.no_op,
        "compaction with multiple segments must rewrite"
    );
    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));

    // The old PIT still sees its pinned generation; a fresh reader sees the
    // remapped winners with no resurrection of the superseded document.
    assert_eq!(keys_of(pit.snapshot()), before);
    assert_eq!(hit_keys(pit.snapshot().as_ref(), &term("new")), vec!["a"]);
    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned(), "b".to_owned()])
    );
}

#[test]
fn i08_no_op_commit_and_no_op_compaction_do_not_rewrite() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.commit().unwrap();
    let generation = writer.generation().unwrap();
    let objects = object_count(&directory);

    let no_op = writer.commit().unwrap();
    assert!(no_op.no_op);
    assert_eq!(writer.generation().unwrap(), generation);
    assert_eq!(object_count(&directory), objects);

    let merge = writer.compact().unwrap();
    assert!(merge.no_op, "single segment without tombstones is a no-op");
    assert_eq!(writer.generation().unwrap(), generation);
    assert_eq!(object_count(&directory), objects);
}

#[test]
fn i09_tight_mutation_state_limit_rejects_without_advancing_current() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        pr09_schema(),
        pr09_registry(),
        IndexLimits::new().with_max_mutation_state_bytes(64),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    let error = writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(DocumentKey::new("a").unwrap()),
                MutationAction::Insert(doc("a", "one", "", "x", 1)),
            )]),
            &no_cancel(),
        )
        .unwrap_err();
    assert!(
        matches!(error, IndexError::ResourceLimit { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(writer.pending_documents(), 0);
    assert_eq!(writer.generation(), None);
    // No commit can succeed under the same bound, so `CURRENT` never appears.
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert!(
        !directory
            .exists(&StorageKey::parse(CURRENT_KEY).unwrap())
            .unwrap()
    );
    assert!(matches!(
        Index::open_existing(directory, pr09_schema(), pr09_registry()),
        Err(IndexError::NotInitialized)
    ));
}

#[test]
fn i10_replay_heavy_state_survives_restart_without_new_writes() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    let token = quervant_core::contract::document::IdempotencyKey::new("batch-heavy").unwrap();
    let batch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Keys(vec![
            DocumentKey::new("a").unwrap(),
            DocumentKey::new("b").unwrap(),
        ]),
        MutationAction::Delete,
    )])
    .with_idempotency_key(token.clone());
    writer.apply_batch(&batch, &no_cancel()).unwrap();
    for index in 0..100 {
        writer
            .apply(
                MutationRequest::insert(doc(&format!("k{index:03}"), "token", "", "x", 1))
                    .with_idempotency_key(
                        quervant_core::contract::document::IdempotencyKey::new(format!(
                            "single-{index:03}"
                        ))
                        .unwrap(),
                    ),
            )
            .unwrap();
    }
    writer.commit().unwrap();
    writer.close().unwrap();

    let generation = current(&directory).generation();
    let objects = object_count(&directory);
    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let replayed = writer.apply_batch(&batch, &no_cancel()).unwrap();
    assert!(replayed.replayed);
    assert_eq!(replayed.outcomes[0].keys.len(), 2);
    // Replaying the batch and committing the untouched writer is a no-op.
    let no_op = writer.commit().unwrap();
    assert!(no_op.no_op);
    assert_eq!(current(&directory).generation(), generation);
    assert_eq!(object_count(&directory), objects);
}

#[test]
fn i11_more_than_128_live_segments_resolve_high_ordinals() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    for i in 0..129 {
        insert(&mut writer, &format!("k{i:03}"), &format!("term{i}"));
        writer.flush().unwrap();
        writer.commit().unwrap();
    }
    writer.close().unwrap();

    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));
    assert_eq!(committed_manifest(&directory).0.segments.len(), 129);

    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(reopened.snapshot().stored_keys().unwrap().len(), 129);
    for i in [0usize, 127, 128] {
        assert_eq!(
            hit_keys(&reopened.snapshot(), &term(&format!("term{i}"))),
            vec![format!("k{i:03}")],
            "ordinal-bearing winner {i} must resolve"
        );
    }
}

#[test]
fn i12_zero_live_keys_after_compaction_reopens() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    insert(&mut writer, "b", "two");
    writer.flush().unwrap();
    delete(&mut writer, "a");
    delete(&mut writer, "b");
    writer.commit().unwrap();
    writer.compact().unwrap();
    writer.close().unwrap();

    let (version, features) = committed_payload(&directory);
    assert_eq!(version, V3_VERSION);
    assert!(has_feature(&features, FEATURE_MUTATION_STATE_V3));
    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    assert!(keys_of(&reopened.snapshot()).is_empty());
    assert!(hit_keys(&reopened.snapshot(), &Query::MatchAll).is_empty());
}

// ---------------------------------------------------------------------------
// F01–F08: deterministic faults and recovery
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq)]
enum FaultOp {
    Create,
    AtomicWrite,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum FaultMode {
    Before,
    AfterReplace,
    PartialWrite,
}

#[derive(Clone)]
struct FaultDirectory {
    inner: Arc<dyn Directory>,
    needle: String,
    op: FaultOp,
    mode: FaultMode,
}

impl FaultDirectory {
    fn new(inner: Arc<dyn Directory>, needle: &str, op: FaultOp, mode: FaultMode) -> Self {
        Self {
            inner,
            needle: needle.to_owned(),
            op,
            mode,
        }
    }

    fn matches(&self, key: &StorageKey) -> bool {
        key.as_str().contains(&self.needle)
    }
}

fn injected(operation: StorageOp) -> StorageError {
    StorageError::io(operation, std::io::Error::other("injected failure"))
}

struct PartialWriter {
    inner: Box<dyn WriteHandle>,
    written: bool,
}

impl WriteHandle for PartialWriter {
    fn write_all(&mut self, buf: &[u8]) -> Result<(), StorageError> {
        if !self.written {
            self.written = true;
            let half = buf.len() / 2;
            self.inner.write_all(&buf[..half])?;
            return Err(injected(StorageOp::Write));
        }
        self.inner.write_all(buf)
    }

    fn sync_all(&mut self) -> Result<(), StorageError> {
        self.inner.sync_all()
    }
}

impl Directory for FaultDirectory {
    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        if self.matches(key) {
            match (self.op, self.mode) {
                (FaultOp::Create, FaultMode::Before) => return Err(injected(StorageOp::Create)),
                (FaultOp::Create, FaultMode::PartialWrite) => {
                    let inner = self.inner.create(key)?;
                    return Ok(Box::new(PartialWriter {
                        inner,
                        written: false,
                    }));
                }
                _ => {}
            }
        }
        self.inner.create(key)
    }

    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        self.inner.create_dir_all(prefix)
    }

    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        self.inner.open_read(key)
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        self.inner.exists(key)
    }

    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        if self.matches(key) && self.op == FaultOp::AtomicWrite {
            if self.mode == FaultMode::AfterReplace {
                self.inner.atomic_write(key, data)?;
            }
            return Err(injected(StorageOp::AtomicWrite));
        }
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        self.inner.sync()
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        self.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        self.inner.file_len(key)
    }
}

fn seeded(directory: Arc<dyn Directory>) -> (Index, u64) {
    let index = Index::create(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.commit().unwrap();
    let generation = writer.generation().unwrap();
    writer.close().unwrap();
    (index, generation)
}

#[test]
fn f01_sidecar_install_failure_leaves_the_previous_generation() {
    let inner = memory();
    let (_, generation) = seeded(Arc::clone(&inner));
    let faulty: Arc<dyn Directory> = Arc::new(FaultDirectory::new(
        Arc::clone(&inner),
        "index/state/",
        FaultOp::Create,
        FaultMode::Before,
    ));
    let index = Index::open_existing(Arc::clone(&faulty), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "b", "two");
    let error = writer.commit().unwrap_err();
    assert!(
        matches!(error, IndexError::Storage(_)),
        "unexpected: {error:?}"
    );
    assert_eq!(current(&inner).generation(), generation);
    let reopened =
        Index::open_existing(Arc::clone(&inner), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned()])
    );
}

#[test]
fn f02_partial_sidecar_write_is_never_readable_as_committed_v3() {
    let inner = memory();
    let (_, generation) = seeded(Arc::clone(&inner));
    let faulty: Arc<dyn Directory> = Arc::new(FaultDirectory::new(
        Arc::clone(&inner),
        "index/state/",
        FaultOp::Create,
        FaultMode::PartialWrite,
    ));
    let index = Index::open_existing(Arc::clone(&faulty), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "b", "two");
    let error = writer.commit().unwrap_err();
    assert!(
        matches!(error, IndexError::Storage(_)),
        "unexpected: {error:?}"
    );
    assert_eq!(current(&inner).generation(), generation);
    // The orphan partial object exists but no committed generation references it.
    let reopened =
        Index::open_existing(Arc::clone(&inner), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned()])
    );
    assert_eq!(committed_payload(&inner).0, V3_VERSION);
}

#[test]
fn f03_manifest_failure_after_sidecar_leaves_an_orphan_and_the_old_generation() {
    let inner = memory();
    let (_, generation) = seeded(Arc::clone(&inner));
    let faulty: Arc<dyn Directory> = Arc::new(FaultDirectory::new(
        Arc::clone(&inner),
        "index/manifests/",
        FaultOp::Create,
        FaultMode::Before,
    ));
    let index = Index::open_existing(Arc::clone(&faulty), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "b", "two");
    let error = writer.commit().unwrap_err();
    assert!(
        matches!(error, IndexError::Storage(_)),
        "unexpected: {error:?}"
    );
    assert_eq!(current(&inner).generation(), generation);

    let reopened =
        Index::open_existing(Arc::clone(&inner), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned()])
    );
    // Both the previous and the orphan sidecar are immutable and valid V3.
    assert_eq!(
        inner.list("index/state", 100).unwrap().len(),
        2,
        "the orphan sidecar is safe and immutable"
    );
}

#[test]
fn f04_current_failure_before_replace_keeps_the_old_generation() {
    let inner = memory();
    let (_, generation) = seeded(Arc::clone(&inner));
    let faulty: Arc<dyn Directory> = Arc::new(FaultDirectory::new(
        Arc::clone(&inner),
        "index/CURRENT",
        FaultOp::AtomicWrite,
        FaultMode::Before,
    ));
    let index = Index::open_existing(Arc::clone(&faulty), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "b", "two");
    let error = writer.commit().unwrap_err();
    assert!(
        matches!(error, IndexError::Storage(_)),
        "unexpected: {error:?}"
    );
    assert_eq!(current(&inner).generation(), generation);
    let reopened =
        Index::open_existing(Arc::clone(&inner), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned()])
    );
}

#[test]
fn f05_current_failure_after_replace_requires_recovery_without_false_ack() {
    let inner = memory();
    let (_, generation) = seeded(Arc::clone(&inner));
    let faulty: Arc<dyn Directory> = Arc::new(FaultDirectory::new(
        Arc::clone(&inner),
        "index/CURRENT",
        FaultOp::AtomicWrite,
        FaultMode::AfterReplace,
    ));
    let index = Index::open_existing(Arc::clone(&faulty), pr09_schema(), pr09_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "b", "two");
    let error = writer.commit().unwrap_err();
    assert!(
        matches!(error, IndexError::RecoveryRequired { .. }),
        "unexpected: {error:?}"
    );
    // The new generation is visible and complete after reopen.
    assert!(current(&inner).generation() > generation);
    let reopened =
        Index::open_existing(Arc::clone(&inner), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned(), "b".to_owned()])
    );
    assert_eq!(committed_payload(&inner).0, V3_VERSION);
}

#[test]
fn f06_pit_held_across_v3_commit_and_compaction() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.flush().unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    let pinned_generation = pit.snapshot().generation();

    insert(&mut writer, "b", "two");
    writer.flush().unwrap();
    writer.commit().unwrap();
    writer.compact().unwrap();
    assert_eq!(pit.snapshot().generation(), pinned_generation);
    assert_eq!(keys_of(pit.snapshot()), BTreeSet::from(["a".to_owned()]));
    assert_eq!(committed_payload(&directory).0, V3_VERSION);
}

#[test]
fn f07_withheld_committed_sidecar_fails_closed() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.flush().unwrap();
    insert(&mut writer, "b", "two");
    writer.commit().unwrap();
    writer.close().unwrap();

    let (manifest, _) = committed_manifest(&directory);
    let reference = manifest.mutation_state.expect("sidecar");
    directory
        .delete(&StorageKey::parse(&reference.object_key).unwrap())
        .unwrap();
    let error =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap_err();
    assert!(
        matches!(error, IndexError::Storage(_)),
        "unexpected: {error:?}"
    );
}

#[test]
fn f08_decode_budget_failure_yields_no_partial_snapshot() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    insert(&mut writer, "a", "one");
    writer.commit().unwrap();
    writer.close().unwrap();

    let tight = IndexLimits::new()
        .with_segment_limits(SegmentLimits::default().with_max_section_decode_bytes(1));
    let error = Index::open_with_limits(
        Arc::clone(&directory),
        pr09_schema(),
        pr09_registry(),
        tight,
    )
    .unwrap_err();
    assert!(
        matches!(error, IndexError::Segment(_))
            || matches!(error, IndexError::ResourceLimit { .. }),
        "unexpected: {error:?}"
    );
    // The committed generation is untouched and still opens with the defaults.
    let reopened =
        Index::open_existing(Arc::clone(&directory), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(
        keys_of(&reopened.snapshot()),
        BTreeSet::from(["a".to_owned()])
    );
}
