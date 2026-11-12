//! PR 15I-D3-C real FsDirectory integration tests (I01/I03/I04/I05/I06/I10).
mod pr14_common;

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::aggregation::{Aggregate, Aggregation, GroupBy, GroupKey};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets as ContractBudgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::mutation::QueryMutationSelector;
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, GeoPoint, JsonValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedSearcher, execute_batch,
};
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

fn tree_bytes(root: &std::path::Path) -> Vec<(String, Vec<u8>)> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else {
                let rel = path
                    .strip_prefix(root)
                    .unwrap()
                    .to_string_lossy()
                    .into_owned();
                out.push((rel, std::fs::read(&path).unwrap()));
            }
        }
    }
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
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
        .env_remove("RUSTFLAGS")
        .env_remove("CARGO_ENCODED_RUSTFLAGS")
        .env_remove("CARGO_TARGET_DIR")
        .env_remove("RUSTC_WRAPPER")
        .env_remove("CARGO_LLVM_COV")
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

#[cfg(not(feature = "pr15i-d3c-experiment"))]
#[test]
fn i12_default_child_no_feature() {
    if std::env::var("D3C_I12_CHILD").as_deref() != Ok("1") {
        return;
    }
    let root = temp_path("i12-child");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    {
        let mut w = index.writer().unwrap();
        for i in 0..12 {
            w.insert(doc(&format!("d{i:08}"), "common", "different"))
                .unwrap();
        }
        w.commit().unwrap();
    }
    drop(index);
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let r = search(&reopened.snapshot(), &req("key", "common", 10));
    assert_eq!(r.total_hits, 12);
    assert_eq!(
        keys(&r),
        (0..10).map(|i| format!("d{i:08}")).collect::<Vec<_>>()
    );
    let _ = std::fs::remove_dir_all(root);
    println!("D3C_I12_DEFAULT_CHILD_OK");
}

#[cfg(not(feature = "pr15i-d3c-experiment"))]
#[test]
fn i12_default_build_ignores_experiment_env() {
    let exe = std::env::current_exe().unwrap();
    let out = std::process::Command::new(exe)
        .args(["--exact", "i12_default_child_no_feature", "--nocapture"])
        .env("D3C_I12_CHILD", "1")
        .env("QUERVANT_PR15I_D3C_STRATEGY", "bogus")
        .env("QUERVANT_PR15I_D3C_PREFILTER_PROFILE", "P9")
        .output()
        .expect("spawn child");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(out.status.success(), "child failed: {stdout}\n{stderr}");
    assert!(
        stdout.contains("D3C_I12_DEFAULT_CHILD_OK"),
        "missing marker: {stdout}"
    );
    assert!(
        stdout.contains("1 passed") || stderr.contains("1 passed"),
        "child did not run one test"
    );
    assert!(
        !stdout.contains("PR15I_D3C_MODE="),
        "mode marker leaked: {stdout}"
    );
    assert!(
        !stderr.contains("PR15I_D3C_MODE="),
        "mode marker leaked: {stderr}"
    );
}

#[test]
fn i09_cancel_budget_atomicity_fs() {
    let root = temp_path("i09");
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
    let generation = snap.generation();
    let expected: Vec<String> = (0..10).map(|i| format!("d{i:08}")).collect();
    let before = tree_bytes(&root.join("index"));
    let r = req("key", "common", 10);
    let cancelled = CancellationFlag::new();
    cancelled.cancel();
    let err = UnifiedSearcher::new(&snap, &schema(), &registry(), SearchLimits::default())
        .search(&r, &Budgets::new(), &cancelled)
        .unwrap_err();
    assert!(matches!(err, SearchError::Cancelled), "{err:?}");
    let work = SearchLimits::default()
        .with_max_total_work_units(1)
        .unwrap();
    let err = UnifiedSearcher::new(&snap, &schema(), &registry(), work)
        .search(&r, &Budgets::new(), &CancellationFlag::new())
        .unwrap_err();
    assert!(
        matches!(err, SearchError::ResourceLimit { limit: 1, .. }),
        "{err:?}"
    );
    let heap = SearchLimits::default()
        .with_max_total_candidate_bytes(1)
        .unwrap();
    let err = UnifiedSearcher::new(&snap, &schema(), &registry(), heap)
        .search(&r, &Budgets::new(), &CancellationFlag::new())
        .unwrap_err();
    assert!(
        matches!(err, SearchError::ResourceLimit { limit: 1, .. }),
        "{err:?}"
    );
    let after = tree_bytes(&root.join("index"));
    assert_eq!(before, after);
    let ok = search(&snap, &r);
    assert_eq!(snap.generation(), generation);
    assert_eq!(ok.total_hits, 120);
    assert_eq!(keys(&ok), expected);
    drop(reopened);
    let fresh = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    assert_eq!(keys(&search(&fresh.snapshot(), &r)), expected);
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn i08_malformed_sort_precedes_execution() {
    let root = temp_path("i08");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    {
        let mut w = index.writer().unwrap();
        for i in 0..20 {
            w.insert(doc(&format!("d{i:08}"), "common", "different"))
                .unwrap();
        }
        w.commit().unwrap();
    }
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let snap = reopened.snapshot();
    let mut bad = req("key", "common", 20);
    bad.sort = Sort::new(vec![SortField::new(
        "nonexistent_sort_column",
        SortDirection::Asc,
    )]);
    let err = UnifiedSearcher::new(&snap, &schema(), &registry(), SearchLimits::default())
        .search(&bad, &Budgets::new(), &CancellationFlag::new())
        .unwrap_err();
    assert!(matches!(err, SearchError::Query(_)), "{err:?}");
    let mut good = req("key", "common", 20);
    good.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    let r = search(&snap, &good);
    assert_eq!(r.total_hits, 20);
    assert_eq!(
        keys(&r),
        (0..20).map(|i| format!("d{i:08}")).collect::<Vec<_>>()
    );
    let _ = std::fs::remove_dir_all(root);
}

fn i07_schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "doc_id",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "meta",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "point",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
        ],
        None,
    )
    .unwrap()
}

fn i07_doc(id: &str, tag: &str, n: i64, kind: &str, lon: f64, lat: f64) -> Document {
    let mut d = Document::new(DocumentKey::new(id.to_owned()).unwrap());
    d.insert(
        "doc_id",
        FieldValues::Single(FieldValue::Keyword(id.to_owned())),
    )
    .unwrap();
    d.insert(
        "tag",
        FieldValues::Single(FieldValue::Keyword(tag.to_owned())),
    )
    .unwrap();
    d.insert("n", FieldValues::Single(FieldValue::I64(n)))
        .unwrap();
    d.insert(
        "meta",
        FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![(
            "kind".to_owned(),
            JsonValue::String(kind.to_owned()),
        )]))),
    )
    .unwrap();
    d.insert(
        "point",
        FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(lon, lat).unwrap())),
    )
    .unwrap();
    d
}

fn i07_index() -> (PathBuf, Arc<dyn Directory>, Index) {
    let root = temp_path("i07");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), i07_schema(), registry(), limits())
            .unwrap();
    {
        let mut w = index.writer().unwrap();
        w.insert(i07_doc("a", "red", 1, "one", 0.0, 0.0)).unwrap();
        w.insert(i07_doc("b", "red", 2, "two", 0.1, 0.1)).unwrap();
        w.insert(i07_doc("c", "blue", 3, "one", 5.0, 5.0)).unwrap();
        w.insert(i07_doc("d", "blue", 4, "two", 15.0, 15.0))
            .unwrap();
        w.insert(i07_doc("e", "green", 5, "one", 40.0, 40.0))
            .unwrap();
        w.commit().unwrap();
    }
    drop(index);
    let reopened = Index::open_existing(Arc::clone(&directory), i07_schema(), registry()).unwrap();
    (root, directory, reopened)
}

fn i07_search(
    snap: &ReaderSnapshot,
    query: Query,
    k: usize,
) -> quervant_core::search::UnifiedResponse {
    let mut r = UnifiedRequest::new(query, TopK::new(k).unwrap());
    r.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    UnifiedSearcher::new(snap, &i07_schema(), &registry(), SearchLimits::default())
        .search(&r, &Budgets::new(), &CancellationFlag::new())
        .unwrap()
}

#[test]
fn i07_negative_and_typed_json_geo() {
    let (root, _d, index) = i07_index();
    let snap = index.snapshot();
    let red = Query::Term {
        field: "tag".into(),
        value: FieldValue::Keyword("red".into()),
    };
    let blue = Query::Term {
        field: "tag".into(),
        value: FieldValue::Keyword("blue".into()),
    };
    let not_red = i07_search(&snap, Query::Not(Box::new(red.clone())), 10);
    assert_eq!(keys(&not_red), vec!["c", "d", "e"]);
    let and = i07_search(&snap, Query::And(vec![blue, Query::Not(Box::new(red))]), 10);
    assert_eq!(keys(&and), vec!["c", "d"]);
    let range = i07_search(
        &snap,
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(2)),
            upper: Bound::Included(FieldValue::I64(4)),
        },
        10,
    );
    assert_eq!(keys(&range), vec!["b", "c", "d"]);
    let json = i07_search(
        &snap,
        Query::JsonPathEquals {
            field: "meta".into(),
            path: JsonPathExpr::parse("$.kind").unwrap(),
            value: FieldValue::Keyword("one".into()),
        },
        10,
    );
    assert_eq!(keys(&json), vec!["a", "c", "e"]);
    let geo = i07_search(
        &snap,
        Query::GeoBoundingBox {
            field: "point".into(),
            bbox: GeoBoundingBox::new(-1.0, -1.0, 1.0, 1.0).unwrap(),
        },
        10,
    );
    assert_eq!(keys(&geo), vec!["a", "b"]);
    let absent = i07_search(
        &snap,
        Query::Term {
            field: "tag".into(),
            value: FieldValue::Keyword("missing".into()),
        },
        10,
    );
    assert_eq!(absent.total_hits, 0);
    let _ = std::fs::remove_dir_all(root);
}

fn i07_policy() -> BudgetPolicy {
    BudgetPolicy::new(
        ContractBudgets::new()
            .with(BudgetKind::QueriesPerBatch, 64)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 20)
            .unwrap(),
        ContractBudgets::new(),
        ContractBudgets::new(),
        ContractBudgets::new(),
    )
}

fn i07_batch(
    snap: &ReaderSnapshot,
    batch: &BatchQueryRequest,
) -> quervant_core::search::SearchResult<quervant_core::contract::batch::BatchQueryResponse> {
    execute_batch(
        snap,
        &i07_schema(),
        &registry(),
        SearchLimits::default(),
        batch,
        &i07_policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
}

#[test]
fn i07_aggregation_and_batch_parity() {
    let (root, _d, index) = i07_index();
    let snap = index.snapshot();
    let mut agg_req = QueryRequest::new(Query::MatchAll);
    agg_req.top_k = TopK::new(10).unwrap();
    agg_req.aggregation = Some(Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("tag".into())])),
        aggregates: vec![Aggregate::count()],
        ..Aggregation::default()
    });
    let batch = BatchQueryRequest::new(vec![agg_req], None, BatchBudget::new(4));
    let resp = i07_batch(&snap, &batch).unwrap();
    let PerQueryOutcome::Success(slot) = resp.slot(0).unwrap() else {
        panic!("aggregation slot failed")
    };
    let agg = slot.aggregation.as_ref().expect("aggregation result");
    assert_eq!(agg.groups.len(), 3);
    let mut counts = std::collections::BTreeMap::new();
    for g in &agg.groups {
        let quervant_core::contract::aggregation::AggregationGroupValue::Value(
            FieldValue::Keyword(tag),
        ) = &g.components[0]
        else {
            panic!("group key")
        };
        let quervant_core::contract::aggregation::AggregationMetricValue::Count(n) = g.metrics[0]
        else {
            panic!("count")
        };
        counts.insert(tag.clone(), n);
    }
    assert_eq!(counts.get("red").copied(), Some(2));
    assert_eq!(counts.get("blue").copied(), Some(2));
    assert_eq!(counts.get("green").copied(), Some(1));
    assert!(agg.groups.windows(2).all(|w| w[0].key <= w[1].key));
    let mut red = QueryRequest::new(Query::Term {
        field: "tag".into(),
        value: FieldValue::Keyword("red".into()),
    });
    red.top_k = TopK::new(2).unwrap();
    red.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    let mut blue = QueryRequest::new(Query::Term {
        field: "tag".into(),
        value: FieldValue::Keyword("blue".into()),
    });
    blue.top_k = TopK::new(2).unwrap();
    blue.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    let batch = BatchQueryRequest::new(vec![red.clone(), blue.clone()], None, BatchBudget::new(4));
    let resp = i07_batch(&snap, &batch).unwrap();
    for (i, req) in [red.clone(), blue.clone()].into_iter().enumerate() {
        let PerQueryOutcome::Success(slot) = resp.slot(i).unwrap() else {
            panic!("slot {i} failed")
        };
        let direct =
            UnifiedSearcher::new(&snap, &i07_schema(), &registry(), SearchLimits::default())
                .search(
                    &UnifiedRequest {
                        query: req.query.clone(),
                        top_k: req.top_k,
                        sort: req.sort.clone(),
                        ..UnifiedRequest::new(Query::MatchAll, TopK::new(1).unwrap())
                    },
                    &Budgets::new(),
                    &CancellationFlag::new(),
                )
                .unwrap();
        assert_eq!(slot.total_hits, direct.total_hits);
        assert_eq!(
            slot.hits
                .iter()
                .map(|h| h.key.as_str().to_owned())
                .collect::<Vec<_>>(),
            keys(&direct)
        );
    }
    let too_small = BatchQueryRequest::new(vec![red, blue_clone()], None, BatchBudget::new(1));
    let err = i07_batch(&snap, &too_small).unwrap_err();
    assert!(matches!(err, SearchError::Query(_)), "{err:?}");
    let _ = std::fs::remove_dir_all(root);
}

fn blue_clone() -> QueryRequest {
    let mut q = QueryRequest::new(Query::Term {
        field: "tag".into(),
        value: FieldValue::Keyword("blue".into()),
    });
    q.top_k = TopK::new(2).unwrap();
    q.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    q
}

#[test]
fn i04_upsert_delete_compaction_pinned() {
    let root = temp_path("i04b");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    let mut w = index.writer().unwrap();
    for id in ["a", "b", "c", "d"] {
        w.insert(doc(id, "common", "different")).unwrap();
    }
    w.commit().unwrap();
    let pinned = w.pin().unwrap();
    for id in ["e", "f"] {
        w.insert(doc(id, "common", "different")).unwrap();
    }
    w.commit().unwrap();
    assert_eq!(
        keys(&search(pinned.snapshot(), &req("key", "common", 10))),
        vec!["a", "b", "c", "d"]
    );
    assert_eq!(
        keys(&search(&w.reader(), &req("key", "common", 10))),
        vec!["a", "b", "c", "d", "e", "f"]
    );
    let replacement = doc("b", "other", "different");
    w.upsert_by_query(
        QueryMutationSelector {
            query: Query::Term {
                field: "doc_id".into(),
                value: FieldValue::Keyword("b".into()),
            },
            max_matches: 1,
            expected_generation: None,
        },
        replacement.clone(),
        replacement,
        &CancellationFlag::new(),
    )
    .unwrap();
    w.delete_keys_for_retention(&[DocumentKey::new("c").unwrap()], "pr15i-d3c test deletion")
        .unwrap();
    w.commit().unwrap();
    assert_eq!(
        keys(&search(pinned.snapshot(), &req("key", "common", 10))),
        vec!["a", "b", "c", "d"]
    );
    assert_eq!(
        keys(&search(&w.reader(), &req("key", "common", 10))),
        vec!["a", "d", "e", "f"]
    );
    assert_eq!(
        keys(&search(&w.reader(), &req("key", "other", 10))),
        vec!["b"]
    );
    w.compact().unwrap();
    assert_eq!(
        keys(&search(&w.reader(), &req("key", "common", 10))),
        vec!["a", "d", "e", "f"]
    );
    assert_eq!(
        keys(&search(pinned.snapshot(), &req("key", "common", 10))),
        vec!["a", "b", "c", "d"]
    );
    let generation = w.reader().generation();
    drop(pinned);
    w.close().unwrap();
    drop(index);
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let snap = reopened.snapshot();
    assert_eq!(snap.generation(), generation);
    assert_eq!(
        keys(&search(&snap, &req("key", "common", 10))),
        vec!["a", "d", "e", "f"]
    );
    assert_eq!(keys(&search(&snap, &req("key", "other", 10))), vec!["b"]);
    let _ = std::fs::remove_dir_all(root);
}
