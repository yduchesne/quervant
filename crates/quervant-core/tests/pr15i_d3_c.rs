//! PR 15I-D3-C real FsDirectory integration tests (I01/I03/I04/I05/I06/I10).
mod pr14_common;

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory};

static DIRS: AtomicU64 = AtomicU64::new(0);

fn temp_path(name: &str) -> PathBuf {
    let p = std::env::temp_dir().join(format!(
        "d3c-{}-{}-{}",
        std::process::id(),
        DIRS.fetch_add(1, Ordering::SeqCst),
        name
    ));
    let _ = std::fs::remove_dir_all(&p);
    p
}

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "key",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            ),
            FieldDefinition::new(
                "group",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            ),
            FieldDefinition::new(
                "doc_id",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
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
    .unwrap()
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn limits() -> IndexLimits {
    IndexLimits::default()
        .with_max_pending_docs(200_000)
        .with_max_pending_bytes(512 * 1024 * 1024)
}

fn pr15d(i: usize) -> Document {
    let doc_id = format!("d{i:08}");
    let key = if i == 0 {
        "singleton"
    } else if i % 2 == 0 {
        "common"
    } else {
        "other"
    };
    let group = if i % 8 == 0 { "medium" } else { "different" };
    let body = if i % 2 == 0 {
        "alpha beta"
    } else {
        "gamma delta"
    };
    let mut d = Document::new(DocumentKey::new(doc_id.clone()).unwrap());
    for (n, v) in [
        ("key", key.to_owned()),
        ("group", group.to_owned()),
        ("doc_id", doc_id),
        ("payload", format!("payload-{i:08}")),
    ] {
        d.insert(n, FieldValues::Single(FieldValue::Keyword(v)))
            .unwrap();
    }
    d.insert(
        "body",
        FieldValues::Single(FieldValue::Text(body.to_owned())),
    )
    .unwrap();
    d
}

fn doc(id: &str, key: &str, group: &str) -> Document {
    let mut d = Document::new(DocumentKey::new(id.to_owned()).unwrap());
    for (n, v) in [
        ("key", key.to_owned()),
        ("group", group.to_owned()),
        ("doc_id", id.to_owned()),
        ("payload", "p".to_owned()),
    ] {
        d.insert(n, FieldValues::Single(FieldValue::Keyword(v)))
            .unwrap();
    }
    d.insert(
        "body",
        FieldValues::Single(FieldValue::Text("alpha beta".to_owned())),
    )
    .unwrap();
    d
}

fn build_fs(n: usize) -> (PathBuf, Arc<dyn Directory>, Index) {
    let root = temp_path(&format!("n{n}"));
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    {
        let mut w = index.writer().unwrap();
        for i in 0..n {
            w.insert(pr15d(i)).unwrap();
        }
        w.commit().unwrap();
    }
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    (root, directory, reopened)
}

fn req(field: &str, term: &str, k: usize) -> UnifiedRequest {
    UnifiedRequest::new(
        Query::Term {
            field: field.into(),
            value: FieldValue::Keyword(term.into()),
        },
        TopK::new(k).unwrap(),
    )
}

fn search(s: &ReaderSnapshot, r: &UnifiedRequest) -> quervant_core::search::UnifiedResponse {
    UnifiedSearcher::new(s, &schema(), &registry(), SearchLimits::default())
        .search(r, &Budgets::new(), &CancellationFlag::new())
        .unwrap()
}

fn expected(n: usize, cls: &str, k: usize) -> (u64, Vec<String>) {
    let ids: Vec<String> = match cls {
        "absent" => vec![],
        "rare" => vec!["d00000000".into()],
        "medium" => (0..n).step_by(8).map(|i| format!("d{i:08}")).collect(),
        _ => (2..n).step_by(2).map(|i| format!("d{i:08}")).collect(),
    };
    (ids.len() as u64, ids.into_iter().take(k).collect())
}

fn keys(r: &quervant_core::search::UnifiedResponse) -> Vec<String> {
    r.hits.iter().map(|h| h.key.as_str().to_owned()).collect()
}

#[test]
fn i02_three_strategy_adapter_parity_all_72_lanes() {
    use std::process::Command;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let out = root
        .join("target/pr15i-d3-c")
        .join(format!("i02-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&out);
    let status = Command::new("python3")
        .arg("benchmarks/pr15i_d3_c/run.py")
        .arg("adapter-compare")
        .arg("--out")
        .arg(&out)
        .current_dir(&root)
        .status()
        .expect("python3 available");
    assert!(status.success(), "adapter-compare failed");
    let report = std::fs::read_to_string(out.join("adapter-compare.json")).expect("report");
    assert!(report.contains("THREE_STRATEGY_PARITY_OK"));
    let _ = std::fs::remove_dir_all(out);
}

#[test]
fn i01_all_72_lanes_10k_and_100k() {
    for n in [10_000usize, 100_000] {
        let (root, _d, index) = build_fs(n);
        let snap = index.snapshot();
        for (field, cls) in [
            ("key", "absent"),
            ("key", "rare"),
            ("group", "medium"),
            ("key", "common"),
        ] {
            let term = match cls {
                "absent" => "never",
                "rare" => "singleton",
                "medium" => "medium",
                _ => "common",
            };
            for k in [1usize, 10, 32, 64, 100, 128, 256, 512, 1024] {
                let (total, ids) = expected(n, cls, k);
                let r = search(&snap, &req(field, term, k));
                assert_eq!(r.total_hits, total, "n={n} {cls} K{k}");
                assert_eq!(keys(&r), ids, "n={n} {cls} K{k}");
            }
        }
        let _ = std::fs::remove_dir_all(root);
    }
}

#[test]
fn i03_k_boundaries_medium_common() {
    let (root, _d, index) = build_fs(10_000);
    let snap = index.snapshot();
    for k in [1usize, 10, 100, 1024] {
        for (field, term, cls) in [("key", "common", "common"), ("group", "medium", "medium")] {
            let (total, ids) = expected(10_000, cls, k);
            let r = search(&snap, &req(field, term, k));
            assert_eq!(r.total_hits, total);
            assert_eq!(keys(&r), ids);
        }
    }
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn i04_multi_segment_and_old_snapshot() {
    let root = temp_path("seg");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    let mut w = index.writer().unwrap();
    for i in 0..100 {
        w.insert(pr15d(i)).unwrap();
    }
    w.commit().unwrap();
    let pinned = w.pin().unwrap();
    for i in 100..200 {
        w.insert(pr15d(i)).unwrap();
    }
    w.commit().unwrap();
    let old = search(pinned.snapshot(), &req("key", "common", 100));
    assert_eq!(old.total_hits, 49);
    let fresh = search(&w.reader(), &req("key", "common", 100));
    assert_eq!(fresh.total_hits, 99);
    drop(pinned);
    drop(w);
    drop(index);
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn i05_equal_sort_unicode_both_directions() {
    let root = temp_path("sort");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    {
        let mut w = index.writer().unwrap();
        for id in ["a", "b", "c", "z", "é"] {
            w.insert(doc(id, "common", "different")).unwrap();
        }
        w.commit().unwrap();
    }
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let snap = reopened.snapshot();
    let mut r = req("key", "common", 5);
    r.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    let asc = search(&snap, &r);
    assert_eq!(keys(&asc), vec!["a", "b", "c", "z", "é"]);
    r.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Desc)]);
    let desc = search(&snap, &r);
    assert_eq!(keys(&desc), vec!["é", "z", "c", "b", "a"]);
    let bits: Vec<u64> = asc
        .hits
        .iter()
        .map(|h| h.score.unwrap().to_bits())
        .collect();
    assert!(bits.windows(2).all(|p| p[0] == p[1]));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn i06_pagination_sentinel() {
    let root = temp_path("page");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    {
        let mut w = index.writer().unwrap();
        for i in 0..120 {
            w.insert(doc(&format!("d{i:08}"), "common", "different"))
                .unwrap();
        }
        w.commit().unwrap();
    }
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let snap = reopened.snapshot();
    let mut r = req("key", "common", 100);
    r.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    let first = search(&snap, &r);
    assert_eq!(first.hits.len(), 100);
    let cursor = first.next_cursor.clone().expect("sentinel cursor");
    r.after = Some(cursor);
    let second = search(&snap, &r);
    assert_eq!(
        keys(&second),
        (100..120).map(|i| format!("d{i:08}")).collect::<Vec<_>>()
    );
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn i10_durable_reopen_identity() {
    let root = temp_path("reopen");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    {
        let mut w = index.writer().unwrap();
        for i in 0..150 {
            w.insert(pr15d(i)).unwrap();
        }
        w.commit().unwrap();
    }
    drop(index);
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let r = search(&reopened.snapshot(), &req("key", "common", 100));
    assert_eq!(r.total_hits, 74);
    let files: Vec<String> = std::fs::read_dir(root.join("index"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    assert!(files.iter().any(|f| f == "CURRENT"));
    let _ = std::fs::remove_dir_all(root);
}
