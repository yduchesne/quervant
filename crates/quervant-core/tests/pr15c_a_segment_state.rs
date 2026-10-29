//! PR 15C-A — snapshot-scoped verified segment-state reuse, integration witness.
//!
//! The production `ReaderSnapshot::open_segment_reader` path now reuses fully
//! verified immutable segment state within one snapshot. These tests exercise the
//! real index/search/writer/filesystem paths and compare them against:
//!
//! * the frozen PR 15A/PR 15B independent oracle (never a production evaluator),
//! * an independently constructed `SegmentReader::open` over the very same
//!   snapshot bytes (the fully validating *uncached* path), and
//! * repeated queries over the same snapshot (the cache-reuse path).
//!
//! No expected value is read back from the cache itself.

mod pr14_common;
mod pr15a_common;

use pr14_common::registry;
use pr15a_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::DocumentKey;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::segment::SegmentReader;

fn sorted_keys(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    let request = UnifiedRequest::new(query, TopK::new(256).expect("top-k"));
    let mut keys: Vec<String> = UnifiedSearcher::new(
        snapshot,
        &pr14_common::schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &CancellationFlag::new())
    .expect("unified search")
    .hits
    .iter()
    .map(|hit| hit.key.as_str().to_owned())
    .collect();
    keys.sort_unstable();
    keys
}

fn alpha_query() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    }
}

fn host_query(host: &str) -> Query {
    Query::Term {
        field: "host".into(),
        value: FieldValue::Keyword(host.into()),
    }
}

fn oracle(query: &Query) -> Vec<String> {
    let predicate = match query {
        Query::Term { field, value } if field == "title" => {
            assert_eq!(value, &FieldValue::Text("alpha".into()));
            Predicate::Alpha
        }
        Query::Term { field, value } if field == "host" => {
            let FieldValue::Keyword(host) = value else {
                panic!("host term must be a keyword");
            };
            match host.as_str() {
                "h1" => Predicate::Alpha,
                "h2" => Predicate::HostH2,
                other => panic!("unexpected host {other}"),
            }
        }
        other => panic!("unexpected query {other:?}"),
    };
    oracle_sorted(predicate)
        .into_iter()
        .map(str::to_owned)
        .collect()
}

/// The complete immutable view of one segment, read through one reader.
#[derive(Debug, PartialEq)]
struct SegmentView {
    doc_count: u64,
    keys: Vec<String>,
    stored_keys: Vec<String>,
    live: Vec<bool>,
    required_features: Vec<(u16, u16)>,
    optional_features: Vec<(u16, u16)>,
    geo_bounds: usize,
    spatial_fields: Vec<(u32, Option<u32>, usize)>,
    columns: Vec<Vec<Option<i64>>>,
    terms: Vec<(u32, String, u64)>,
}

fn segment_view(reader: &SegmentReader, columns: &[(&str, usize)]) -> SegmentView {
    let schema = reader.schema();
    let mut terms = Vec::new();
    if let Some(dictionary) = reader.dictionary() {
        for (field_id, entries) in dictionary.fields() {
            for entry in entries {
                terms.push((*field_id, entry.term.clone(), entry.doc_freq));
                let postings = reader
                    .postings_for_entry(entry)
                    .expect("postings for dictionary entry");
                assert_eq!(postings.posting_doc_count(), entry.doc_freq);
            }
        }
    }
    let spatial_fields = reader
        .spatial()
        .map(|index| {
            index
                .fields()
                .iter()
                .map(|field| (field.field_id, field.root, field.nodes.len()))
                .collect()
        })
        .unwrap_or_default();
    let columns = columns
        .iter()
        .map(|(name, docs)| {
            let field_id = schema.field_id(name).expect("column field");
            (0..*docs)
                .map(|doc_id| {
                    reader
                        .column_value(field_id, doc_id as u64)
                        .expect("column value")
                        .and_then(|values| match values {
                            quervant_core::contract::document::FieldValues::Single(
                                FieldValue::I64(value),
                            ) => Some(value),
                            _ => None,
                        })
                })
                .collect()
        })
        .collect();
    SegmentView {
        doc_count: reader.doc_count(),
        keys: reader
            .doc_keys()
            .expect("doc keys")
            .iter()
            .map(|key| key.as_str().to_owned())
            .collect(),
        stored_keys: reader
            .stored()
            .expect("stored")
            .iter()
            .map(|record| record.key.as_str().to_owned())
            .collect(),
        live: reader.live_docs().expect("live docs").as_ref().clone(),
        required_features: reader.required_features().to_vec(),
        optional_features: reader.optional_features().to_vec(),
        geo_bounds: reader.geo_bounds().len(),
        spatial_fields,
        columns,
        terms,
    }
}

fn assert_cached_matches_uncached(snapshot: &ReaderSnapshot) {
    let mut compared = 0usize;
    for index in 0..snapshot.segment_count() {
        let segment = &snapshot.segments()[index];
        let doc_count = segment.doc_count();
        let cached = snapshot.open_segment_reader(index).expect("cached reader");
        let uncached = SegmentReader::open(segment.bytes().to_vec(), *snapshot.segment_limits())
            .expect("uncached reader");
        // `n` is the single-valued integer column in the frozen fixture schema.
        let columns = [("n", doc_count as usize)];
        let cached_view = segment_view(cached.reader(), &columns);
        let uncached_view = segment_view(&uncached, &columns);
        assert_eq!(
            cached_view, uncached_view,
            "cached and uncached views must be byte-for-byte equivalent for segment {index}"
        );
        compared += 1;
    }
    assert!(compared > 0, "the fixture must contain segments");
}

fn open(path: &std::path::Path) -> Index {
    reopen_fs(path)
}

// C-A T01 — repeated queries over one snapshot reuse verified state and still
// match the frozen oracle exactly.
#[test]
fn pr15c_a_t01_repeated_queries_reuse_state_and_match_oracle() {
    let index = build_memory();
    let snapshot = index.snapshot();
    for _ in 0..3 {
        for query in [alpha_query(), host_query("h2")] {
            assert_eq!(
                sorted_keys(&snapshot, query.clone()),
                oracle(&query),
                "cached production path must match the frozen oracle for {query:?}"
            );
        }
        assert_cached_matches_uncached(&snapshot);
    }
}

// C-A T02 — pinned point-in-time snapshots keep their own cache and semantics.
#[test]
fn pr15c_a_t02_pinned_snapshot_matches_oracle() {
    let index = build_memory();
    let pit = index.pin().expect("pin");
    let alpha = sorted_keys(pit.snapshot(), alpha_query());
    assert_eq!(alpha, oracle(&alpha_query()));
    assert_eq!(alpha, sorted_keys(&index.snapshot(), alpha_query()));
    assert_cached_matches_uncached(pit.snapshot());
}

// C-A T03 — an older snapshot is unaffected by later commits (VSR-I03).
#[test]
fn pr15c_a_t03_old_snapshot_isolated_from_new_commit() {
    let (directory, index) = build_memory_with_dir();
    let before = index.snapshot();
    let before_alpha = sorted_keys(&before, alpha_query());
    assert_eq!(before_alpha, oracle(&alpha_query()));

    commit_segment(&index, vec![c0_document()]);
    // `Index::snapshot` is pinned to the generation observed at open; a fresh
    // handle observes the new committed generation with its own cache.
    let reopened = Index::open_existing(directory, pr14_common::schema(), registry())
        .expect("reopen after commit");
    let after = reopened.snapshot();
    let after_alpha = sorted_keys(&after, alpha_query());
    // Both views are self-consistent; the old snapshot's cache did not absorb the
    // new generation's documents.
    assert_eq!(before_alpha, oracle(&alpha_query()));
    assert_cached_matches_uncached(&before);
    assert_cached_matches_uncached(&after);
    assert!(after.segment_count() >= 1);
    assert_eq!(after.generation().is_some(), before.generation().is_some());
    // The committed document is now visible in the new snapshot only.
    let c0 = DocumentKey::new("c0").expect("key");
    assert!(after.contains_key(&c0).expect("after"));
    assert!(!before.contains_key(&c0).expect("before"));
    assert!(after_alpha.iter().any(|key| key == "c0"));
    assert_eq!(
        sorted_keys(&before, host_query("h2")),
        oracle(&host_query("h2"))
    );
}

// C-A T04 — real local filesystem commit, restart and cold reopen.
#[test]
fn pr15c_a_t04_real_filesystem_restart_matches_oracle() {
    let (path, index) = build_fs("pr15c-a-cache");
    assert_eq!(
        sorted_keys(&index.snapshot(), alpha_query()),
        oracle(&alpha_query())
    );
    assert_cached_matches_uncached(&index.snapshot());
    drop(index);

    // Fresh handle, cold in-process cache: the same verified-state boundary.
    let reopened = open(&path);
    assert_eq!(
        sorted_keys(&reopened.snapshot(), alpha_query()),
        oracle(&alpha_query())
    );
    assert_eq!(
        sorted_keys(&reopened.snapshot(), host_query("h2")),
        oracle(&host_query("h2"))
    );
    assert_cached_matches_uncached(&reopened.snapshot());

    // Restart again and confirm deterministic repeated results (cache reuse).
    drop(reopened);
    let restarted = open(&path);
    let first = sorted_keys(&restarted.snapshot(), alpha_query());
    let second = sorted_keys(&restarted.snapshot(), alpha_query());
    assert_eq!(first, second);
    assert_eq!(first, oracle(&alpha_query()));
    let _ = std::fs::remove_dir_all(&path);
}

// C-A T05 — stored keys, contains-key and reclamation-free read paths are
// identical on the cached and uncached readers.
#[test]
fn pr15c_a_t05_key_accessors_are_identical() {
    let index = build_memory();
    let snapshot = index.snapshot();
    let mut expected: Vec<String> = Vec::new();
    let mut cached_keys: Vec<String> = Vec::new();
    for segment in snapshot.segments() {
        let reader = SegmentReader::open(segment.bytes().to_vec(), *snapshot.segment_limits())
            .expect("uncached reader");
        expected.extend(
            reader
                .doc_keys()
                .expect("keys")
                .iter()
                .map(|key| key.as_str().to_owned()),
        );
    }
    for index in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(index).expect("cached reader");
        cached_keys.extend(
            guard
                .reader()
                .doc_keys()
                .expect("keys")
                .iter()
                .map(|key| key.as_str().to_owned()),
        );
    }
    assert_eq!(cached_keys, expected);
    assert_eq!(
        snapshot.stored_keys().expect("stored keys").len(),
        expected.len()
    );
    let key = DocumentKey::new("a0").expect("key");
    assert!(snapshot.contains_key(&key).expect("contains"));
}
