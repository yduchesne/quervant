//! PR 8 integration tests — real local directory lifecycle, frozen legacy
//! fixtures, PIT isolation and format stability (T14, T33–T37, T42–T44).

mod common;

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use common::{
    Pr07Doc, TempDir, pr07_registry, pr07_schema, pr08_commit_batches, pr08_registry, pr08_schema,
};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};
use sha2::Digest as _;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

fn fs_directory(path: &Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("fs directory"))
}

fn search(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    LexicalSearcher::new(
        snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(
        query,
        TopK::new(100).expect("topk"),
        &Budgets::new(),
        &NeverCancel,
    )
    .expect("search")
}

/// Search a fixture committed with the PR 7 schema (no PR 8 domain field).
fn search_pr07(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    LexicalSearcher::new(
        snapshot,
        &pr07_schema(),
        &pr07_registry(),
        SearchLimits::default(),
    )
    .search(
        query,
        TopK::new(100).expect("topk"),
        &Budgets::new(),
        &NeverCancel,
    )
    .expect("search")
}

fn keys(response: &SearchResponse) -> Vec<String> {
    let mut found: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    found.sort();
    found
}

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(out, "{byte:02x}").expect("write");
    }
    out
}

fn hash_tree(root: &Path) -> BTreeMap<String, String> {
    fn walk(root: &Path, dir: &Path, out: &mut BTreeMap<String, String>) {
        for entry in std::fs::read_dir(dir).expect("read_dir") {
            let entry = entry.expect("entry");
            let path = entry.path();
            if entry.file_type().expect("type").is_dir() {
                walk(root, &path, out);
            } else {
                let relative = path
                    .strip_prefix(root)
                    .expect("relative")
                    .to_string_lossy()
                    .into_owned();
                let digest = sha2::Sha256::digest(std::fs::read(&path).expect("read"));
                out.insert(relative, hex(&digest));
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(root, root, &mut out);
    out
}

fn corpus() -> Vec<Pr07Doc<'static>> {
    vec![
        Pr07Doc::new("h1")
            .host("rust")
            .tags(vec!["rust"])
            .title("rust search"),
        Pr07Doc::new("h2")
            .host("crust")
            .tags(vec!["crust"])
            .title("crusty"),
        Pr07Doc::new("h3")
            .host("rusty")
            .tags(vec!["rusty"])
            .title("rusty"),
        Pr07Doc::new("h4")
            .host("run")
            .tags(vec!["run"])
            .title("run"),
        Pr07Doc::new("h5")
            .host("rést")
            .tags(vec!["rést"])
            .title("resting"),
    ]
}

/// A fixed operator suite used across lifecycle tests.
fn operator_queries() -> Vec<(&'static str, Query)> {
    vec![
        (
            "prefix",
            Query::Prefix {
                field: "host".into(),
                prefix: "rust".into(),
            },
        ),
        (
            "glob",
            Query::Glob {
                field: "host".into(),
                pattern: "r*st".into(),
            },
        ),
        (
            "regex",
            Query::Regex {
                field: "tags".into(),
                pattern: "ru.*".into(),
            },
        ),
        (
            "fuzzy",
            Query::Fuzzy {
                field: "host".into(),
                value: "rust".into(),
                max_edits: 1,
                transpositions: true,
            },
        ),
    ]
}

// T33 — MemoryDirectory commit/reopen with every PR 8 operator.
#[test]
fn p8_t33_memory_commit_reopen() {
    let directory = memory();
    let generation = pr08_commit_batches(
        Arc::clone(&directory),
        vec![corpus().into_iter().map(|d| d.build()).collect()],
    );
    assert_eq!(generation, 1);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    assert_eq!(snapshot.generation(), Some(1));
    for (name, query) in operator_queries() {
        let response = search(&snapshot, &query);
        assert!(response.total_hits > 0, "{name} returned no hits");
    }
}

// T34 — FsDirectory commit/reopen and read-only search.
#[test]
fn p8_t34_fs_commit_reopen_no_writes() {
    let temp = TempDir::new("pr08-t34");
    let directory = fs_directory(temp.path());
    pr08_commit_batches(
        Arc::clone(&directory),
        vec![corpus().into_iter().map(|d| d.build()).collect()],
    );
    drop(directory);

    let before = hash_tree(temp.path());
    let index = Index::open_existing(fs_directory(temp.path()), pr08_schema(), pr08_registry())
        .expect("reopen");
    let snapshot = index.snapshot();
    for (_, query) in operator_queries() {
        let _ = search(&snapshot, &query);
    }
    let after = hash_tree(temp.path());
    assert_eq!(
        before, after,
        "read-only PR 8 search must not rewrite files"
    );
}

// T35 — a pinned PIT sees its generation; a fresh open sees the newer one.
#[test]
fn p8_t35_pit_vs_fresh() {
    let directory = memory();
    pr08_commit_batches(
        Arc::clone(&directory),
        vec![vec![Pr07Doc::new("a").host("rust").build()]],
    );
    let index =
        Index::open_existing(Arc::clone(&directory), pr08_schema(), pr08_registry()).unwrap();
    let pinned = index.pin().expect("pin");
    let pinned_snapshot = Arc::clone(pinned.snapshot());
    assert_eq!(pinned_snapshot.generation(), Some(1));

    let mut writer = index.writer().expect("writer");
    writer
        .insert(Pr07Doc::new("b").host("rusty").build())
        .unwrap();
    writer.flush().unwrap();
    writer.commit().unwrap();
    drop(writer);

    let pattern = Query::Prefix {
        field: "host".into(),
        prefix: "rust".into(),
    };
    assert_eq!(keys(&search(&pinned_snapshot, &pattern)), ["a"]);
    let fresh = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    assert_eq!(fresh.generation(), Some(2));
    assert_eq!(keys(&search(&fresh.snapshot(), &pattern)), ["a", "b"]);
}

// T37 — single-segment and multi-segment (sorted-remap) results are equivalent.
#[test]
fn p8_t37_single_vs_multisegment_remap() {
    let docs: Vec<_> = corpus().into_iter().map(|d| d.build()).collect();
    let single = {
        let directory = memory();
        pr08_commit_batches(Arc::clone(&directory), vec![docs.clone()]);
        Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap()
    };
    let multi = {
        let directory = memory();
        let batches: Vec<Vec<_>> = docs.chunks(2).map(|chunk| chunk.to_vec()).collect();
        pr08_commit_batches(Arc::clone(&directory), batches);
        Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap()
    };
    assert!(single.snapshot().segment_count() < multi.snapshot().segment_count());
    for (name, query) in operator_queries() {
        let a = search(&single.snapshot(), &query);
        let b = search(&multi.snapshot(), &query);
        assert_eq!(a.total_hits, b.total_hits, "{name} total");
        assert_eq!(keys(&a), keys(&b), "{name} keys");
        for (left, right) in a.hits.iter().zip(&b.hits) {
            assert!((left.score - right.score).abs() < 1e-9, "{name} score");
        }
    }
}

// ---------------------------------------------------------------------------
// Frozen pre-norms legacy fixture (T14, T36)
// ---------------------------------------------------------------------------

fn fixture_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/index/pr07_pre_norms_v1")
}

fn copy_dir(src: &Path, dst: &Path) {
    std::fs::create_dir_all(dst).expect("mkdir");
    for entry in std::fs::read_dir(src).expect("read_dir") {
        let entry = entry.expect("entry");
        let to = dst.join(entry.file_name());
        if entry.file_type().expect("type").is_dir() {
            copy_dir(&entry.path(), &to);
        } else {
            std::fs::copy(entry.path(), &to).expect("copy");
        }
    }
}

fn stage_fixture(tag: &str) -> TempDir {
    let temp = TempDir::new(tag);
    copy_dir(&fixture_root().join("index"), &temp.path().join("index"));
    temp
}

const APPENDED: [(&str, &str, &[&str]); 2] = [
    ("n1", "rust async runtime", &["tokio rust"]),
    ("n2", "generic rust traits", &["rust abstractions"]),
];

fn append_document(
    key: &str,
    title: &str,
    body: &[&str],
) -> quervant_core::contract::document::Document {
    use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
    let mut doc = Document::new(DocumentKey::new(key).expect("key"));
    doc.insert(
        "title",
        FieldValues::Single(FieldValue::Text(title.to_owned())),
    )
    .unwrap();
    if !body.is_empty() {
        let values = if body.len() == 1 {
            FieldValues::Single(FieldValue::Text(body[0].to_owned()))
        } else {
            FieldValues::Multi(
                body.iter()
                    .map(|value| FieldValue::Text((*value).to_owned()))
                    .collect(),
            )
        };
        doc.insert("body", values).unwrap();
    }
    doc.insert("n", FieldValues::Single(FieldValue::I64(0)))
        .unwrap();
    doc
}

// T36 — every PR 8 operator works over a frozen legacy (pre-norms) generation.
#[test]
fn p8_t36_frozen_legacy_all_operators() {
    let temp = stage_fixture("pr08-t36");
    let index = Index::open_existing(fs_directory(temp.path()), pr07_schema(), pr07_registry())
        .expect("legacy reopen");
    let snapshot = index.snapshot();
    assert_eq!(snapshot.generation(), Some(1));
    // Legacy segments carry no field norms.
    for segment in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(segment).unwrap();
        assert!(guard.reader().field_norms().is_none(), "segment {segment}");
    }
    let expected = vec!["d1", "d2", "d5", "d6"];
    let title_rust = |query: Query| {
        let response = search_pr07(&snapshot, &query);
        assert_eq!(keys(&response), expected, "query {query:?}");
    };
    title_rust(Query::Prefix {
        field: "title".into(),
        prefix: "ru".into(),
    });
    title_rust(Query::Glob {
        field: "title".into(),
        pattern: "r*st".into(),
    });
    title_rust(Query::Regex {
        field: "title".into(),
        pattern: "rust".into(),
    });
    title_rust(Query::Fuzzy {
        field: "title".into(),
        value: "rust".into(),
        max_edits: 1,
        transpositions: true,
    });
}

// T14 — mixed legacy + new-format BM25 equals an all-new equivalent corpus.
#[test]
fn p8_t14_mixed_legacy_new_bm25() {
    let temp = stage_fixture("pr08-t14");
    let index =
        Index::open_existing(fs_directory(temp.path()), pr07_schema(), pr07_registry()).unwrap();
    let mut writer = index.writer().expect("writer");
    for (key, title, body) in APPENDED {
        writer.insert(append_document(key, title, body)).unwrap();
    }
    writer.flush().unwrap();
    writer.commit().unwrap();
    drop(writer);
    let mixed =
        Index::open_existing(fs_directory(temp.path()), pr07_schema(), pr07_registry()).unwrap();
    assert_eq!(mixed.generation(), Some(2));

    // The equivalent all-new corpus, one segment per original batch.
    let legacy = [
        (
            "d1",
            "rust systems search",
            &["rust is fast", "memory safety"][..],
        ),
        ("d2", "rust language guide", &["rust and cargo"][..]),
        ("d3", "python scripting", &[][..]),
        ("d4", "java virtual machine", &["java rust"][..]),
        ("d5", "rust basics", &["introductory rust"][..]),
        ("d6", "rust manual", &["advanced rust"][..]),
        ("d7", "search engines", &["search and rust"][..]),
        ("d8", "", &["empty title doc"][..]),
    ];
    let all_new_dir = memory();
    let created = Index::create(all_new_dir.clone(), pr07_schema(), pr07_registry()).unwrap();
    let mut writer = created.writer().unwrap();
    for batch in [&legacy[0..4], &legacy[4..8], &APPENDED[..]] {
        for (key, title, body) in batch.iter() {
            writer.insert(append_document(key, title, body)).unwrap();
        }
        writer.flush().unwrap();
    }
    writer.commit().unwrap();
    drop(writer);
    let all_new = Index::open_existing(all_new_dir, pr07_schema(), pr07_registry()).unwrap();

    let queries = [
        Query::Prefix {
            field: "title".into(),
            prefix: "ru".into(),
        },
        Query::Glob {
            field: "title".into(),
            pattern: "r*st".into(),
        },
        Query::Regex {
            field: "title".into(),
            pattern: "rust".into(),
        },
        Query::Fuzzy {
            field: "title".into(),
            value: "rust".into(),
            max_edits: 1,
            transpositions: true,
        },
    ];
    for query in &queries {
        let mixed_response = {
            let snapshot = mixed.snapshot();
            LexicalSearcher::new(
                &snapshot,
                &pr07_schema(),
                &pr07_registry(),
                SearchLimits::default(),
            )
            .search(
                query,
                TopK::new(100).unwrap(),
                &Budgets::new(),
                &NeverCancel,
            )
            .unwrap()
        };
        let new_response = {
            let snapshot = all_new.snapshot();
            LexicalSearcher::new(
                &snapshot,
                &pr07_schema(),
                &pr07_registry(),
                SearchLimits::default(),
            )
            .search(
                query,
                TopK::new(100).unwrap(),
                &Budgets::new(),
                &NeverCancel,
            )
            .unwrap()
        };
        assert_eq!(
            mixed_response.total_hits, new_response.total_hits,
            "{query:?} total"
        );
        for (left, right) in mixed_response.hits.iter().zip(&new_response.hits) {
            assert_eq!(left.key, right.key, "{query:?} key");
            assert!(
                (left.score - right.score).abs() < 1e-9,
                "{query:?} score for {}",
                left.key.as_str()
            );
        }
    }
}

// T42 — PR 8 introduces no new segment section or feature.
#[test]
fn p8_t42_golden_bytes_features_unchanged() {
    use quervant_core::segment::format::{
        FEATURE_BASELINE, FEATURE_BOUNDS, FEATURE_COLUMNS, FEATURE_FIELD_NORMS, FEATURE_POSITIONAL,
        FEATURE_REMAP, FEATURE_STORED,
    };
    let directory = memory();
    pr08_commit_batches(
        Arc::clone(&directory),
        vec![vec![Pr07Doc::new("a").host("rust").build()]],
    );
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let guard = snapshot.open_segment_reader(0).unwrap();
    let required = guard.reader().required_features();
    let known = [
        FEATURE_BASELINE,
        FEATURE_STORED,
        FEATURE_POSITIONAL,
        FEATURE_COLUMNS,
        FEATURE_BOUNDS,
        FEATURE_REMAP,
        FEATURE_FIELD_NORMS,
    ];
    assert!(
        required
            .iter()
            .all(|(id, version)| *version == 1 && known.contains(id)),
        "unexpected required feature: {required:?}"
    );
    assert!(
        required.iter().any(|(id, _)| *id == FEATURE_FIELD_NORMS),
        "field norms must still be declared"
    );
    // The frozen legacy golden segment still opens unchanged.
    const GOLDEN: &[u8] = include_bytes!("fixtures/segment/golden.seg");
    let reader = quervant_core::segment::SegmentReader::open(
        GOLDEN.to_vec(),
        quervant_core::segment::SegmentLimits::default(),
    )
    .expect("golden segment");
    assert!(reader.field_norms().is_none());
}

// T44 — the standalone core has no remote/distributed dependency.
#[test]
fn p8_t44_core_is_standalone() {
    let manifest = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml"))
        .expect("read manifest");
    for forbidden in ["quervant-distributed", "etcd", "tonic", "aws-sdk", "rustfs"] {
        assert!(
            !manifest.contains(forbidden),
            "quervant-core must not depend on {forbidden}"
        );
    }
    // A real core search path works without any service.
    let index = {
        let directory = memory();
        pr08_commit_batches(
            Arc::clone(&directory),
            vec![vec![Pr07Doc::new("solo").host("standalone").build()]],
        );
        Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap()
    };
    let response = search(
        &index.snapshot(),
        &Query::Prefix {
            field: "host".into(),
            prefix: "stand".into(),
        },
    );
    assert_eq!(response.total_hits, 1);
}
