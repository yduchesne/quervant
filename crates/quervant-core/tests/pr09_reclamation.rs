//! PR 9 conservative reclamation planning and retention hooks (T31–T33, T38–T39).

mod pr09_common;

use pr09_common::{create, doc, hit_keys, memory, term};

use quervant_core::contract::document::{DocumentKey, MutationRequest};
use quervant_core::index::{Index, IndexError, ObjectClass};
use quervant_core::storage::StorageKey;

// T31 — current generation objects are never reported as reclaimable.
#[test]
fn t31_current_objects_never_reclaimable() {
    let directory = memory();
    let index = create(directory.clone());
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();
    }
    let plan = index.reclamation_plan().unwrap();
    assert!(plan.complete_inventory);
    assert!(!plan.online_deletion_supported);
    assert!(!plan.has_deletable_objects());
    assert!(plan.orphan_candidates.is_empty());
    assert!(
        plan.unknown.is_empty(),
        "unexpected unknown: {:?}",
        plan.unknown
    );
    assert!(
        plan.current_reachable
            .iter()
            .any(|object| object.key == "index/CURRENT")
    );
    assert!(
        plan.current_reachable
            .iter()
            .any(|object| object.key.contains("index/manifests/"))
    );
    assert!(
        plan.current_reachable
            .iter()
            .any(|object| object.key.starts_with("index/state/"))
    );
    let _ = ObjectClass::Unknown;
}

// T32 — an independently opened handle and PIT invalidate any online-delete claim.
#[test]
fn t32_independent_handles_prevent_deletion() {
    let directory = memory();
    let index = create(directory.clone());
    let pit;
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        pit = writer.pin().unwrap();
        writer
            .apply(MutationRequest::upsert(doc("a", "two", "", "x", 2)))
            .unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();
    }
    // A second independent handle observes the same authoritative generation.
    let independent = Index::open_existing(
        directory.clone(),
        pr09_common::pr09_schema(),
        pr09_common::pr09_registry(),
    )
    .unwrap();
    let plan = independent.reclamation_plan().unwrap();
    assert!(!plan.has_deletable_objects());
    assert!(plan.orphan_candidates.is_empty());
    // The historical objects are retained, not candidates.
    assert!(!plan.historical_reachable.is_empty());
    // The pinned old snapshot still resolves its pre-mutation document.
    assert_eq!(hit_keys(pit.snapshot(), &term("one")), ["a"]);
}

// T33 — an unreferenced orphan object is UNKNOWN, never a deletion candidate.
#[test]
fn t33_orphan_is_unknown() {
    let directory = memory();
    let index = create(directory.clone());
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();
    }
    // Simulate a crash that left an orphan immutable object behind.
    let orphan = StorageKey::parse("index/segments/orphan.seg").unwrap();
    let mut handle = directory.create(&orphan).unwrap();
    handle.write_all(b"orphan").unwrap();
    handle.sync_all().unwrap();
    directory.sync().unwrap();
    let plan = index.reclamation_plan().unwrap();
    assert!(plan.orphan_candidates.is_empty());
    assert!(
        plan.unknown
            .iter()
            .any(|object| object.key == "index/segments/orphan.seg")
    );
    assert!(!plan.has_deletable_objects());
}

// T38 — explicit retention deletes through the normal revisioned path.
#[test]
fn t38_explicit_retention_uses_normal_deletes() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    for (key, title) in [("a", "keep"), ("b", "drop"), ("c", "drop")] {
        writer
            .apply(MutationRequest::insert(doc(key, title, "", "x", 1)))
            .unwrap();
    }
    writer.commit().unwrap();
    let keys = [
        DocumentKey::new("b").unwrap(),
        DocumentKey::new("c").unwrap(),
    ];
    let outcome = writer
        .delete_keys_for_retention(&keys, "expired by caller policy")
        .unwrap();
    assert_eq!(outcome.reason, "expired by caller policy");
    assert_eq!(outcome.deleted.len(), 2);
    writer.commit().unwrap();
    assert_eq!(hit_keys(&writer.reader(), &term("keep")), ["a"]);
    assert!(hit_keys(&writer.reader(), &term("drop")).is_empty());
}

// T39 — retention validation is all-or-nothing.
#[test]
fn t39_retention_validation_is_atomic() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    // Empty reason is rejected.
    let error = writer
        .delete_keys_for_retention(&[DocumentKey::new("a").unwrap()], "   ")
        .unwrap_err();
    assert!(matches!(error, IndexError::InvalidRetention { .. }));
    assert_eq!(writer.pending_mutations(), 0);
    // Over-limit batches are rejected before any admission. The default
    // pending-document bound is used as the retention batch bound.
    let limit = index.limits().max_pending_docs();
    let many: Vec<DocumentKey> = (0..=limit)
        .map(|index| DocumentKey::new(format!("k{index}")).unwrap())
        .collect();
    let error = writer
        .delete_keys_for_retention(&many, "too many")
        .unwrap_err();
    assert!(matches!(error, IndexError::ResourceLimit { .. }));
    assert_eq!(writer.pending_mutations(), 0);
    // Duplicate keys are normalized by first occurrence.
    let duplicates = [
        DocumentKey::new("d").unwrap(),
        DocumentKey::new("d").unwrap(),
    ];
    let outcome = writer
        .delete_keys_for_retention(&duplicates, "dedup")
        .unwrap();
    assert_eq!(outcome.deleted.len(), 1);
}
