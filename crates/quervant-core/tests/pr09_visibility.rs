//! PR 9 generation visibility, statistics and legacy compatibility (T16–T19, T27, T37).

mod pr09_common;

use pr09_common::{
    create, doc, hit_keys, memory, pr09_registry, pr09_schema, read_file, search, term,
};

use quervant_core::contract::document::{DocumentKey, MutationRequest};
use quervant_core::contract::query::Query;
use quervant_core::index::{Index, IndexError};
use quervant_core::segment::Manifest;
use quervant_core::storage::StorageKey;
use quervant_objectstore::ContentDigest;

// T16 — term and phrase membership excludes obsolete physical documents.
#[test]
fn t16_term_and_phrase_exclude_deleted() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "a",
            "quick brown fox",
            "shared body",
            "x",
            1,
        )))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "b",
            "quick brown fox",
            "other body",
            "x",
            2,
        )))
        .unwrap();
    writer.commit().unwrap();
    // Upsert replaces a's physical document; the old one is still on disk but dead.
    writer
        .apply(MutationRequest::upsert(doc(
            "a",
            "slow green turtle",
            "shared body",
            "x",
            3,
        )))
        .unwrap();
    writer.commit().unwrap();

    assert_eq!(hit_keys(&writer.reader(), &term("quick")), ["b"]);
    assert_eq!(hit_keys(&writer.reader(), &term("turtle")), ["a"]);
    let phrase = Query::Phrase {
        field: "title".into(),
        terms: vec!["quick".into(), "brown".into(), "fox".into()],
    };
    assert_eq!(hit_keys(&writer.reader(), &phrase), ["b"]);
}

// T17 — prefix/glob/regex/fuzzy and NOT exclude dead docs.
#[test]
fn t17_multi_term_operators_and_not_exclude_dead() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "a",
            "alpha shared",
            "",
            "x",
            1,
        )))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "b",
            "alpine shared",
            "",
            "x",
            2,
        )))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc("c", "gamma other", "", "x", 3)))
        .unwrap();
    writer.commit().unwrap();
    writer
        .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
        .unwrap();
    writer.commit().unwrap();

    let prefix = Query::Prefix {
        field: "title".into(),
        prefix: "al".into(),
    };
    assert_eq!(hit_keys(&writer.reader(), &prefix), ["b"]);
    let glob = Query::Glob {
        field: "title".into(),
        pattern: "alp*".into(),
    };
    assert_eq!(hit_keys(&writer.reader(), &glob), ["b"]);
    let regex = Query::Regex {
        field: "title".into(),
        pattern: "alpine".into(),
    };
    assert_eq!(hit_keys(&writer.reader(), &regex), ["b"]);
    let fuzzy = Query::Fuzzy {
        field: "title".into(),
        value: "gamme".into(),
        max_edits: 1,
        transpositions: true,
    };
    assert_eq!(hit_keys(&writer.reader(), &fuzzy), ["c"]);
    // A deleted doc can never be resurrected by a negative-only clause.
    let not_shared = Query::Not(Box::new(term("shared")));
    assert_eq!(hit_keys(&writer.reader(), &not_shared), ["c"]);
}

// T18 — BM25 corpus statistics use only live documents.
#[test]
fn t18_bm25_statistics_reference_after_delete() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "term term", "", "x", 1)))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc("b", "term other", "", "x", 2)))
        .unwrap();
    writer.commit().unwrap();
    writer
        .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
        .unwrap();
    writer.commit().unwrap();

    let response = search(&writer.reader(), &term("term"));
    assert_eq!(response.total_hits, 1);
    assert_eq!(response.hits[0].key.as_str(), "b");
    // n = 1 live doc, df = 1, tf = 1, dl = 2, avgdl = 2.
    let k1 = 1.2_f64;
    let b = 0.75_f64;
    let n = 1.0_f64;
    let df = 1.0_f64;
    let tf = 1.0_f64;
    let dl = 2.0_f64;
    let avgdl = 2.0_f64;
    let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
    let expected = idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl));
    assert!((response.hits[0].score - expected).abs() < 1e-9);
}

// T19 — a negative-only query yields zero scores and no ghost hits.
#[test]
fn t19_negative_only_has_no_ghost_scores() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "shared", "", "x", 1)))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc("b", "other", "", "x", 2)))
        .unwrap();
    writer.commit().unwrap();
    let not_shared = Query::Not(Box::new(term("shared")));
    let response = search(&writer.reader(), &not_shared);
    assert_eq!(response.total_hits, 1);
    assert!(response.hits.iter().all(|hit| hit.score == 0.0));
}

// T27 — a corrupt mutation-state sidecar fails closed with no all-live fallback.
#[test]
fn t27_corrupt_state_fails_closed() {
    let directory = memory();
    let index = create(directory.clone());
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
    }
    let state_keys = directory.list("index/state", 16).unwrap();
    assert_eq!(state_keys.len(), 1);
    directory
        .atomic_write(&state_keys[0], b"not a valid sidecar")
        .unwrap();
    let error =
        Index::open_existing(directory.clone(), pr09_schema(), pr09_registry()).unwrap_err();
    assert!(matches!(
        error,
        IndexError::CorruptCommittedState { .. } | IndexError::Storage(_)
    ));
    // Missing sidecar also fails closed.
    directory.delete(&state_keys[0]).unwrap();
    let error = Index::open_existing(directory, pr09_schema(), pr09_registry()).unwrap_err();
    assert!(matches!(
        error,
        IndexError::CorruptCommittedState { .. } | IndexError::Storage(_)
    ));
}

// T37 — a legacy v1 manifest is readable and migrates to v2 on the next commit.
#[test]
fn t37_v1_manifest_readable_and_migrates() {
    let directory = memory();
    let index = create(directory.clone());
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "legacy", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
    }
    // Rewrite the current manifest as payload version 1 (no mutation state) and
    // republish CURRENT so it references the v1 bytes.
    let current_key = StorageKey::parse("index/CURRENT").unwrap();
    let pointer =
        quervant_core::index::CurrentPointer::parse(&read_file(&directory, "index/CURRENT"))
            .unwrap();
    let manifest_bytes = read_file(&directory, pointer.manifest_key().as_str());
    let mut manifest = Manifest::decode(&manifest_bytes, index.limits().segment_limits()).unwrap();
    manifest.mutation_state = None;
    manifest
        .required_features
        .retain(|feature| *feature != (quervant_core::segment::format::FEATURE_MUTATION_STATE, 1));
    let v1_bytes = manifest.encode().unwrap();
    assert!(v1_bytes.len() < manifest_bytes.len() + 64);
    directory
        .atomic_write(pointer.manifest_key(), &v1_bytes)
        .unwrap();
    let new_pointer = quervant_core::index::CurrentPointer::new(
        pointer.generation(),
        v1_bytes.len() as u64,
        ContentDigest::sha256_v1(&v1_bytes),
    )
    .unwrap();
    directory
        .atomic_write(&current_key, &new_pointer.encode().unwrap())
        .unwrap();

    // Legacy state is synthesized with all keys live at revision 1.
    let legacy = Index::open_existing(directory.clone(), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(hit_keys(&legacy.snapshot(), &term("legacy")), ["a"]);

    // The next commit emits a version-2 manifest.
    {
        let mut writer = legacy.writer().unwrap();
        writer
            .apply(MutationRequest::upsert(doc("a", "migrated", "", "x", 2)))
            .unwrap();
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory.clone(), pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(hit_keys(&reopened.snapshot(), &term("migrated")), ["a"]);
    // And compaction still works on the migrated generation.
    {
        let mut writer = reopened.writer().unwrap();
        let outcome = writer.compact().unwrap();
        assert!(!outcome.no_op);
    }
    let final_index = Index::open_existing(directory, pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(hit_keys(&final_index.snapshot(), &term("migrated")), ["a"]);
}
