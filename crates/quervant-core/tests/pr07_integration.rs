//! PR 7 real production-path integration (I01–I10).
//!
//! These tests build real immutable segments through `IndexWriter`, commit them
//! through the real `CURRENT`/manifest path and execute queries with the real
//! `LexicalSearcher`. They do not simulate power loss.

mod common;

use std::collections::BTreeSet;
use std::sync::Arc;

use common::{Pr07Doc, TempDir, pr07_commit_batches, pr07_registry, pr07_schema};
use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::Schema;
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

fn fs_directory(path: &std::path::Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("fs directory"))
}

/// The shared 12-document fixture corpus partitioned into three segments.
fn fixture_batches() -> Vec<Vec<quervant_core::contract::document::Document>> {
    let batch_one = vec![
        Pr07Doc::new("alpha")
            .title("The quick brown fox jumps over the lazy dog")
            .body(vec!["Rust search engine"])
            .host("Example.COM")
            .tags(vec!["rust", "Search"])
            .raw("Exact Raw")
            .n(1)
            .build(),
        Pr07Doc::new("beta")
            .title("Quick brown foxes jump")
            .body(vec!["Rust and C++"])
            .host("example.com")
            .tags(vec!["cpp"])
            .raw("exact raw")
            .n(2)
            .build(),
        Pr07Doc::new("gamma")
            .title("The lazy dog sleeps")
            .body(vec!["Searching with Rust"])
            .host("Other.org")
            .tags(vec!["rust"])
            .raw("Exact Raw")
            .n(3)
            .build(),
        Pr07Doc::new("delta")
            .title("Café naïve résumé")
            .body(vec!["Unicode"])
            .host("café.example")
            .tags(vec!["unicode"])
            .raw("Café")
            .n(4)
            .build(),
    ];
    let batch_two = vec![
        Pr07Doc::new("epsilon")
            .title("Alpha beta gamma")
            .body(vec!["a b c"])
            .tags(vec!["Greek"])
            .n(5)
            .build(),
        Pr07Doc::new("zeta")
            .title("Running runners run")
            .body(vec!["runner runs"])
            .host("example.com")
            .raw("run")
            .n(6)
            .build(),
        Pr07Doc::new("eta")
            .title("The fox and the hound")
            .body(vec!["Hound fox"])
            .host("other.org")
            .tags(vec!["fox"])
            .raw("Fox")
            .n(7)
            .build(),
        Pr07Doc::new("theta")
            .body(vec!["rust"])
            .host("example.com")
            .tags(vec!["rust", "rust"])
            .n(8)
            .build(),
    ];
    let batch_three = vec![
        Pr07Doc::new("iota")
            .title("Rust rust rust")
            .body(vec!["Rust Rust"])
            .host("EXAMPLE.com")
            .tags(vec!["Rust"])
            .raw("rust")
            .n(9)
            .build(),
        Pr07Doc::new("kappa").title("").body(vec![""]).n(10).build(),
        Pr07Doc::new("lambda")
            .title("the the the")
            .body(vec!["the"])
            .host("example.com")
            .tags(vec!["the"])
            .raw("the")
            .n(11)
            .build(),
        Pr07Doc::new("mu")
            .title("quick running")
            .body(vec!["quick brown", "fox"])
            .host("cafe.example")
            .tags(vec!["unicode"])
            .raw("quick")
            .n(12)
            .build(),
    ];
    vec![batch_one, batch_two, batch_three]
}

fn searcher<'a>(
    snapshot: &'a ReaderSnapshot,
    schema: &'a Schema,
    registry: &'a AnalyzerRegistry,
) -> LexicalSearcher<'a> {
    LexicalSearcher::new(snapshot, schema, registry, SearchLimits::default())
}

fn keys(response: &quervant_core::search::SearchResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn search(snapshot: &ReaderSnapshot, query: &Query) -> quervant_core::search::SearchResponse {
    let schema = pr07_schema();
    let registry = pr07_registry();
    let cancel = CancellationFlag::new();
    searcher(snapshot, &schema, &registry)
        .search(query, TopK::new(20).unwrap(), &Budgets::new(), &cancel)
        .expect("search")
}

// I01 — writer -> refresh -> term.
#[test]
fn i01_writer_refresh_term() {
    let directory = memory();
    let index = Index::create(directory, pr07_schema(), pr07_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .insert(Pr07Doc::new("a").title("Rust search").build())
        .unwrap();
    let snapshot = writer.refresh().unwrap();
    let response = search(
        &snapshot,
        &Query::Term {
            field: "title".into(),
            value: FieldValue::Text("rust".into()),
        },
    );
    assert_eq!(keys(&response), vec!["a"]);
    assert_eq!(response.total_hits, 1);
    assert!(response.generation.is_none());
}

// I02 — writer -> commit -> reopen -> search.
#[test]
fn i02_commit_reopen_search() {
    let directory = memory();
    pr07_commit_batches(
        Arc::clone(&directory),
        vec![vec![
            Pr07Doc::new("a").title("Rust search").build(),
            Pr07Doc::new("b").title("Python search").build(),
        ]],
    );
    let index = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let snapshot = index.snapshot();
    let response = search(
        &snapshot,
        &Query::Term {
            field: "title".into(),
            value: FieldValue::Text("search".into()),
        },
    );
    assert_eq!(response.total_hits, 2);
    assert_eq!(response.generation, Some(1));
    assert_eq!(response.view_ordinal, 0);
}

// I03 — multiple flushes and segments.
#[test]
fn i03_multiple_segments() {
    let directory = memory();
    let generation = pr07_commit_batches(Arc::clone(&directory), fixture_batches());
    assert_eq!(generation, 1);
    let index = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let snapshot = index.snapshot();
    assert_eq!(snapshot.segment_count(), 3);
    let response = search(
        &snapshot,
        &Query::Term {
            field: "host".into(),
            value: FieldValue::Keyword("example.com".into()),
        },
    );
    let mut found = keys(&response);
    found.sort();
    assert_eq!(found, vec!["beta", "lambda", "theta", "zeta"]);
}

// I04 — stored source is untouched by search.
#[test]
fn i04_search_is_read_only() {
    let directory = memory();
    pr07_commit_batches(Arc::clone(&directory), fixture_batches());
    let index = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let snapshot = index.snapshot();
    let before = snapshot.stored_keys().unwrap();
    let _ = search(
        &snapshot,
        &Query::Phrase {
            field: "title".into(),
            terms: vec!["quick".into(), "brown".into(), "fox".into()],
        },
    );
    let after = snapshot.stored_keys().unwrap();
    assert_eq!(before, after);
}

// I05 — FsDirectory real process restart.
#[test]
fn i05_fs_restart_search() {
    let dir = TempDir::new("pr07-i05");
    {
        let directory = fs_directory(dir.path());
        pr07_commit_batches(directory, fixture_batches());
    }
    let directory = fs_directory(dir.path());
    let index = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let response = search(
        &index.snapshot(),
        &Query::Phrase {
            field: "title".into(),
            terms: vec!["quick".into(), "brown".into(), "fox".into()],
        },
    );
    let mut found = keys(&response);
    found.sort();
    assert_eq!(found, vec!["alpha", "beta"]);
}

// I06 — concurrent immutable readers over the same snapshot.
#[test]
fn i06_concurrent_immutable_readers() {
    let directory = memory();
    pr07_commit_batches(Arc::clone(&directory), fixture_batches());
    let index = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let snapshot = index.snapshot();
    let schema = pr07_schema();
    let registry = pr07_registry();
    std::thread::scope(|scope| {
        for _ in 0..4 {
            let snapshot = Arc::clone(&snapshot);
            let schema = schema.clone();
            let registry = registry.clone();
            scope.spawn(move || {
                let cancel = CancellationFlag::new();
                let searcher =
                    LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
                let response = searcher
                    .search(
                        &Query::Term {
                            field: "host".into(),
                            value: FieldValue::Keyword("EXAMPLE.com".into()),
                        },
                        TopK::new(10).unwrap(),
                        &Budgets::new(),
                        &cancel,
                    )
                    .unwrap();
                let mut found: Vec<String> = response
                    .hits
                    .iter()
                    .map(|hit| hit.key.as_str().to_owned())
                    .collect();
                found.sort();
                assert_eq!(found, vec!["iota"]);
            });
        }
    });
}

// I07 — refresh before/after snapshot isolation.
#[test]
fn i07_refresh_snapshot_isolated() {
    let directory = memory();
    let index = Index::create(directory, pr07_schema(), pr07_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .insert(Pr07Doc::new("a").title("shared term").build())
        .unwrap();
    let before = writer.refresh().unwrap();
    writer
        .insert(Pr07Doc::new("b").title("shared term").build())
        .unwrap();
    let after = writer.refresh().unwrap();
    let query = Query::Term {
        field: "title".into(),
        value: FieldValue::Text("shared".into()),
    };
    assert_eq!(search(&before, &query).total_hits, 1);
    assert_eq!(search(&after, &query).total_hits, 2);
}

// I08 — PIT pinned across commits.
#[test]
fn i08_pit_pinned_across_commit() {
    let directory = memory();
    let index = Index::create(Arc::clone(&directory), pr07_schema(), pr07_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .insert(Pr07Doc::new("a").title("pinned term").build())
        .unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    writer
        .insert(Pr07Doc::new("b").title("pinned term").build())
        .unwrap();
    writer.commit().unwrap();
    let query = Query::Term {
        field: "title".into(),
        value: FieldValue::Text("pinned".into()),
    };
    assert_eq!(search(pit.snapshot(), &query).total_hits, 1);
    assert_eq!(search(&writer.reader(), &query).total_hits, 2);
}

// I09 — empty index and a no-op commit.
#[test]
fn i09_empty_index_and_noop_commit() {
    let directory = memory();
    let index = Index::create(Arc::clone(&directory), pr07_schema(), pr07_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let snapshot = writer.refresh().unwrap();
    let response = search(&snapshot, &Query::MatchAll);
    assert_eq!(response.total_hits, 0);
    assert!(keys(&response).is_empty());
    // Committing an empty index publishes generation 1 with no segments.
    let outcome = writer.commit().unwrap();
    assert_eq!(outcome.generation, 1);
    assert!(!outcome.no_op);
    // A subsequent no-change commit is a no-op.
    let no_op = writer.commit().unwrap();
    assert!(no_op.no_op);
    assert_eq!(no_op.generation, 1);
    let committed = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let response = search(&committed.snapshot(), &Query::MatchAll);
    assert_eq!(response.total_hits, 0);
}

// I10 — same corpus in one vs many segments produces identical hits and scores.
#[test]
fn i10_single_vs_multi_segment_equivalence() {
    let batches = fixture_batches();
    let mut all_docs = Vec::new();
    for batch in &batches {
        all_docs.extend(batch.iter().cloned());
    }

    let multi_directory = memory();
    pr07_commit_batches(Arc::clone(&multi_directory), batches);
    let multi = Index::open_existing(multi_directory, pr07_schema(), pr07_registry()).unwrap();

    let single_directory = memory();
    pr07_commit_batches(Arc::clone(&single_directory), vec![all_docs]);
    let single = Index::open_existing(single_directory, pr07_schema(), pr07_registry()).unwrap();

    let query = Query::Or(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("quick".into()),
        },
        Query::Term {
            field: "body".into(),
            value: FieldValue::Text("rust".into()),
        },
    ]);
    let single_response = search(&single.snapshot(), &query);
    let multi_response = search(&multi.snapshot(), &query);
    assert_eq!(single_response.total_hits, multi_response.total_hits);
    assert_eq!(keys(&single_response), keys(&multi_response));
    let single_scores: Vec<f64> = single_response.hits.iter().map(|hit| hit.score).collect();
    let multi_scores: Vec<f64> = multi_response.hits.iter().map(|hit| hit.score).collect();
    for (left, right) in single_scores.iter().zip(&multi_scores) {
        assert!((left - right).abs() < 1e-10, "{left} vs {right}");
    }
}

// Cancellation passed to the executor is observed.
#[test]
fn cancellation_before_search_yields_typed_error() {
    let directory = memory();
    pr07_commit_batches(Arc::clone(&directory), fixture_batches());
    let index = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let snapshot = index.snapshot();
    let schema = pr07_schema();
    let registry = pr07_registry();
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let result = searcher(&snapshot, &schema, &registry).search(
        &Query::MatchAll,
        TopK::new(5).unwrap(),
        &Budgets::new(),
        &cancel,
    );
    assert!(matches!(result, Err(SearchError::Cancelled)));
}

// `NeverCancel` remains a valid cancellation source for the public API.
#[test]
fn never_cancel_is_accepted() {
    let directory = memory();
    pr07_commit_batches(Arc::clone(&directory), fixture_batches());
    let index = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let schema = pr07_schema();
    let registry = pr07_registry();
    let response = searcher(&index.snapshot(), &schema, &registry)
        .search(
            &Query::MatchAll,
            TopK::new(3).unwrap(),
            &Budgets::new(),
            &quervant_core::analysis::NeverCancel,
        )
        .unwrap();
    assert_eq!(response.total_hits, 12);
    assert_eq!(response.hits.len(), 3);
}

fn _assert_keys(snapshot: &ReaderSnapshot) -> BTreeSet<String> {
    snapshot
        .stored_keys()
        .unwrap()
        .into_iter()
        .map(|key| key.as_str().to_owned())
        .collect()
}
