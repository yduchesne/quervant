//! PR 15E-B1a — live-bitmap traversal invariants (U01–U05, U11–U14).
//!
//! Every expected outcome below is derived from the fixture model defined in
//! this file, never from the executor under test. The observable used to prove
//! "each effective-live document is examined exactly once" is the cumulative
//! work meter: the unified executor charges exactly one unit per examined live
//! document for a leaf-free/typed-only predicate, so the smallest admitted
//! `max_total_work_units` equals the effective-live document count. A dead
//! slot that were examined (or a duplicated visit) would change that number.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, Cancellation, CancellationFlag, NeverCancel};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, MutationRequest,
};
use quervant_core::contract::query::{Bound, Query};
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
};
use quervant_core::storage::{Directory, MemoryDirectory};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ],
        None,
    )
    .expect("pr15e schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn document(key: &str, title: &str, tag: &str, n: i64) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert("title", FieldValues::Single(FieldValue::Text(title.into())))
        .unwrap();
    document
        .insert("tag", FieldValues::Single(FieldValue::Keyword(tag.into())))
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .unwrap();
    document
}

fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

/// The fixture model: `(key, title, tag, n)` in physical insertion order.
fn model() -> Vec<(&'static str, &'static str, &'static str, i64)> {
    vec![
        ("k00", "alpha", "even", 0),
        ("k01", "beta", "odd", 1),
        ("k02", "alpha", "even", 2),
        ("k03", "beta", "odd", 3),
        ("k04", "alpha", "even", 4),
        ("k05", "beta", "odd", 5),
        ("k06", "alpha", "even", 6),
        ("k07", "beta", "odd", 7),
        ("k08", "alpha", "even", 8),
        ("k09", "beta", "odd", 9),
        ("k10", "alpha", "even", 10),
        ("k11", "beta", "odd", 11),
        ("k12", "alpha", "even", 12),
        ("k13", "beta", "odd", 13),
        ("k14", "alpha", "even", 14),
        ("k15", "beta", "odd", 15),
        ("k16", "alpha", "even", 16),
        ("k17", "beta", "odd", 17),
    ]
}

/// Physical documents removed from the effective-live view.
const DELETED: [&str; 5] = ["k00", "k05", "k06", "k11", "k15"];
/// The replacement document: physical `k12` is superseded (a tombstone).
const REPLACED: (&str, &str, &str, i64) = ("k12", "gamma", "even", 12);

fn is_deleted(key: &str) -> bool {
    DELETED.contains(&key)
}

/// Effective-live model rows after deletes and the `k12` upsert, ascending by key.
fn live_model() -> Vec<(&'static str, &'static str, &'static str, i64)> {
    let mut rows: Vec<_> = model()
        .into_iter()
        .filter(|(key, ..)| !is_deleted(key))
        .map(|(key, title, tag, n)| {
            if key == REPLACED.0 {
                REPLACED
            } else {
                (key, title, tag, n)
            }
        })
        .collect();
    rows.sort_unstable_by_key(|(key, ..)| *key);
    rows
}

/// Three committed segments of six documents, five deletes and one upsert.
///
/// Physical layout: seg0 = k00..k05, seg1 = k06..k11, seg2 = k12..k17, and the
/// upsert appends one replacement segment. Tombstones therefore sit at the first
/// and last physical slot of every sealed segment plus one interior slot.
fn tombstoned_index() -> Index {
    let directory = memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create index");
    let rows = model();
    let mut writer = index.writer().unwrap();
    for chunk in rows.chunks(6) {
        for (key, title, tag, n) in chunk {
            writer
                .apply(MutationRequest::insert(document(key, title, tag, *n)))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    for key in DELETED {
        writer
            .apply(MutationRequest::delete(DocumentKey::new(key).unwrap()))
            .unwrap();
    }
    let (key, title, tag, n) = REPLACED;
    writer
        .apply(MutationRequest::upsert(document(key, title, tag, n)))
        .unwrap();
    writer.commit().unwrap();
    drop(writer);
    Index::open_existing(directory, schema(), registry()).expect("reopen index")
}

/// The same 18 physical documents with no deletes, in four segments so the
/// segment geometry matches (the `k12` replacement is an ordinary insert).
fn fully_live_index() -> Index {
    let directory = memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create index");
    let mut writer = index.writer().unwrap();
    for chunk in model().chunks(6) {
        for (key, title, tag, n) in chunk {
            writer
                .apply(MutationRequest::insert(document(key, title, tag, *n)))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    drop(writer);
    Index::open_existing(directory, schema(), registry()).expect("reopen index")
}

fn term(field: &str, value: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Text(value.to_owned()),
    }
}

/// A typed-only predicate that every live document satisfies.
fn typed_all() -> Query {
    Query::Range {
        field: "n".to_owned(),
        lower: Bound::Included(FieldValue::I64(0)),
        upper: Bound::Unbounded,
    }
}

fn typed_at_least(min: i64) -> Query {
    Query::Range {
        field: "n".to_owned(),
        lower: Bound::Included(FieldValue::I64(min)),
        upper: Bound::Unbounded,
    }
}

// ---------------------------------------------------------------------------
// Execution helpers
// ---------------------------------------------------------------------------

fn run(
    snapshot: &ReaderSnapshot,
    query: &Query,
    limits: SearchLimits,
    cancel: &dyn Cancellation,
) -> Result<UnifiedResponse, SearchError> {
    let request = UnifiedRequest::new(query.clone(), TopK::new(64).unwrap());
    let schema = schema();
    let registry = registry();
    let searcher = UnifiedSearcher::new(snapshot, &schema, &registry, limits);
    searcher.search(&request, &Budgets::new(), cancel)
}

fn run_default(snapshot: &ReaderSnapshot, query: &Query) -> UnifiedResponse {
    run(snapshot, query, SearchLimits::default(), &NeverCancel).expect("search")
}

fn limits_with_work(units: u64) -> SearchLimits {
    SearchLimits::default()
        .with_max_total_work_units(units)
        .unwrap()
}

fn limits_with_typed_work(units: u64) -> SearchLimits {
    SearchLimits::default()
        .with_max_typed_work_units(units)
        .unwrap()
}

fn limits_with_bytes(bytes: u64) -> SearchLimits {
    SearchLimits::default()
        .with_max_total_candidate_bytes(bytes)
        .unwrap()
}

/// Smallest `max_total_work_units` for which the query succeeds.
fn min_work(snapshot: &ReaderSnapshot, query: &Query) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 24;
    while low < high {
        let mid = low + (high - low) / 2;
        if run(snapshot, query, limits_with_work(mid), &NeverCancel).is_ok() {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

/// Smallest `max_typed_work_units` for which the query succeeds.
fn min_typed_work(snapshot: &ReaderSnapshot, query: &Query) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 24;
    while low < high {
        let mid = low + (high - low) / 2;
        if run(snapshot, query, limits_with_typed_work(mid), &NeverCancel).is_ok() {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

/// Smallest `max_total_candidate_bytes` for which the query succeeds.
fn min_bytes(snapshot: &ReaderSnapshot, query: &Query) -> u64 {
    let mut low = 1u64;
    // The hard repository ceiling for this limit is 1 GiB.
    let mut high = 1u64 << 30;
    while low < high {
        let mid = low + (high - low) / 2;
        if run(snapshot, query, limits_with_bytes(mid), &NeverCancel).is_ok() {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    let mut out: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    out.sort_unstable();
    out
}

/// Cancellation that flips to `true` on the `cancel_at`-th poll (0 = first).
struct CancelAt {
    polls: AtomicU64,
    cancel_at: u64,
}

impl CancelAt {
    fn new(cancel_at: u64) -> Self {
        Self {
            polls: AtomicU64::new(0),
            cancel_at,
        }
    }

    fn polls(&self) -> u64 {
        self.polls.load(Ordering::Relaxed)
    }
}

impl Cancellation for CancelAt {
    fn is_cancelled(&self) -> bool {
        self.polls.fetch_add(1, Ordering::Relaxed) >= self.cancel_at
    }
}

// ---------------------------------------------------------------------------
// U01/U02 — bitmap traversal sees exactly the effective-live slots
// ---------------------------------------------------------------------------

#[test]
fn u01_match_all_examines_exactly_the_live_ids_once_each() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();
    let expected = live_model();
    assert_eq!(expected.len(), 13, "fixture model");

    let response = run_default(&snapshot, &Query::MatchAll);
    assert_eq!(response.total_hits, 13);
    assert_eq!(
        keys(&response),
        expected.iter().map(|(key, ..)| *key).collect::<Vec<_>>()
    );

    // One cumulative work unit per examined live document and nothing else.
    assert_eq!(min_work(&snapshot, &Query::MatchAll), 13);
    assert!(
        matches!(
            run(
                &snapshot,
                &Query::MatchAll,
                limits_with_work(12),
                &NeverCancel
            ),
            Err(SearchError::ResourceLimit { .. })
        ),
        "a 12-unit budget must not admit 13 examinations"
    );
}

#[test]
fn u02_no_charge_for_tombstoned_or_superseded_slots() {
    let tombstoned = tombstoned_index();
    let live = tombstoned.snapshot();
    let fully_live = fully_live_index();
    let all = fully_live.snapshot();

    // Identical physical layout: 18 examinations when nothing is dead, 13 when
    // five slots are dead. A visited/charged false slot would break this.
    assert_eq!(min_work(&all, &Query::MatchAll), 18);
    assert_eq!(min_work(&live, &Query::MatchAll), 13);

    // The superseded `k12` physical document is not live; its replacement is.
    let response = run_default(&live, &term("title", "gamma"));
    assert_eq!(keys(&response), vec!["k12"]);
    assert_eq!(response.total_hits, 1);
    assert!(run_default(&all, &term("title", "gamma")).hits.is_empty());
}

#[test]
fn u02_typed_only_examinations_equal_live_count() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();
    let query = typed_all();

    assert_eq!(min_work(&snapshot, &query), 13);
    assert_eq!(min_typed_work(&snapshot, &query), 13);

    let response = run_default(&snapshot, &query);
    assert_eq!(response.total_hits, 13);
    assert!(response.hits.iter().all(|hit| hit.score.is_none()));
}

// ---------------------------------------------------------------------------
// U03 — mixed lexical + typed membership against the fixture oracle
// ---------------------------------------------------------------------------

#[test]
fn u03_mixed_bitmap_traversal_matches_independent_oracle() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();
    let expected: Vec<&str> = live_model()
        .into_iter()
        .filter(|(_, title, _, n)| *title == "alpha" && *n >= 8)
        .map(|(key, ..)| key)
        .collect();

    let query = Query::And(vec![term("title", "alpha"), typed_at_least(8)]);
    let response = run_default(&snapshot, &query);
    assert_eq!(response.total_hits, expected.len() as u64);
    assert_eq!(keys(&response), expected);
    // A positive lexical leaf scores every returned hit.
    assert!(
        response
            .hits
            .iter()
            .all(|hit| hit.score.is_some_and(|score| score.is_finite()))
    );

    // Sharp work boundary: the request is admitted exactly once below/at the
    // smallest sufficient budget and never bypasses the cap.
    let exact = min_work(&snapshot, &query);
    assert!(run(&snapshot, &query, limits_with_work(exact), &NeverCancel).is_ok());
    assert!(matches!(
        run(&snapshot, &query, limits_with_work(exact - 1), &NeverCancel),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// ---------------------------------------------------------------------------
// U04 — cancellation before the first and after the k-th examined document
// ---------------------------------------------------------------------------

#[test]
fn u04_cancellation_stops_without_partial_results_and_leaks_nothing() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();
    let query = Query::MatchAll;

    let complete = run(&snapshot, &query, SearchLimits::default(), &NeverCancel).unwrap();
    assert_eq!(complete.total_hits, 13);

    // Cancel before the first examination.
    let early = CancelAt::new(0);
    assert!(matches!(
        run(&snapshot, &query, SearchLimits::default(), &early),
        Err(SearchError::Cancelled)
    ));
    assert_eq!(early.polls(), 1);

    // Cancel part-way through: no successful (partial) response is produced.
    let probe = CancelAt::new(u64::MAX);
    let _ = run(&snapshot, &query, SearchLimits::default(), &probe).unwrap();
    let total_polls = probe.polls();
    assert!(total_polls > 2);
    let midway = CancelAt::new(total_polls / 2);
    assert!(matches!(
        run(&snapshot, &query, SearchLimits::default(), &midway),
        Err(SearchError::Cancelled)
    ));

    // A cancelled request leaves no ledger/budget residue behind: the identical
    // request at the identical tight budget succeeds afterwards.
    let exact = min_work(&snapshot, &query);
    assert!(run(&snapshot, &query, limits_with_work(exact), &NeverCancel).is_ok());
    let after = run(&snapshot, &query, SearchLimits::default(), &NeverCancel).unwrap();
    assert_eq!(after.total_hits, 13);
    assert_eq!(keys(&after), keys(&complete));
}

// ---------------------------------------------------------------------------
// U05 — work caps are exact and sharp for zero-hit, MatchAll, typed, high-match
// ---------------------------------------------------------------------------

#[test]
fn u05_work_caps_are_exact_and_sharp_for_all_lanes() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();
    let lanes = [
        ("zero-hit", term("title", "absent")),
        ("match-all", Query::MatchAll),
        ("typed-only", typed_all()),
        (
            "mixed-typed",
            Query::And(vec![term("title", "alpha"), typed_at_least(8)]),
        ),
        ("high-match", term("title", "alpha")),
    ];
    for (name, query) in lanes {
        let exact = min_work(&snapshot, &query);
        assert!(exact > 0, "{name}: a nonzero budget must be required");
        assert!(
            run(&snapshot, &query, limits_with_work(exact), &NeverCancel).is_ok(),
            "{name}: exact budget must be admitted"
        );
        assert!(
            matches!(
                run(&snapshot, &query, limits_with_work(exact - 1), &NeverCancel),
                Err(SearchError::ResourceLimit { .. })
            ),
            "{name}: one-below budget must be rejected"
        );
    }
}

// ---------------------------------------------------------------------------
// U11/U12 — retained memory boundaries and the intentional admissibility change
// ---------------------------------------------------------------------------

/// 1000 live documents in one segment; only `d0000` contains `alpha`.
fn wide_index(extra_documents: usize) -> Index {
    let directory = memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create index");
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(document(
            "d0000", "alpha", "even", 0,
        )))
        .unwrap();
    for n in 1..extra_documents {
        let key = format!("d{n:04}");
        writer
            .apply(MutationRequest::insert(document(
                &key,
                "beta gamma",
                "odd",
                n as i64,
            )))
            .unwrap();
    }
    writer.commit().unwrap();
    drop(writer);
    Index::open_existing(directory, schema(), registry()).expect("reopen index")
}

#[test]
fn u11_u12_retained_memory_caps_still_reject_but_the_transient_live_set_is_gone() {
    let wide = wide_index(1000);
    let narrow = wide_index(10);
    let wide_snapshot = wide.snapshot();
    let narrow_snapshot = narrow.snapshot();
    let query = term("title", "alpha");

    // The single match and its single posting are the only retained lexical
    // allocations, so the logical ceiling is independent of the 1000 live docs.
    let wide_min = min_bytes(&wide_snapshot, &query);
    let narrow_min = min_bytes(&narrow_snapshot, &query);

    // U12: a budget sufficient for the 10-document index is now sufficient for
    // the 1000-document index. The removed transient `BTreeSet<u64>` previously
    // charged 48 logical bytes per live document (48_000 here) on its own.
    assert_eq!(
        wide_min, narrow_min,
        "no per-live-document transient charge may remain (wide={wide_min}, narrow={narrow_min})"
    );
    assert!(
        wide_min < 48 * 1000,
        "the removed live-set reservation (48_000) must not still be charged: {wide_min}"
    );
    let response = run(
        &wide_snapshot,
        &query,
        limits_with_bytes(narrow_min),
        &NeverCancel,
    )
    .expect("former live-set-only rejection must now succeed");
    assert_eq!(response.total_hits, 1);
    assert_eq!(keys(&response), vec!["d0000"]);

    // U11: real retained memory is still enforced exactly, one byte below the
    // peak the successful request needs.
    assert!(matches!(
        run(
            &wide_snapshot,
            &query,
            limits_with_bytes(wide_min - 1),
            &NeverCancel
        ),
        Err(SearchError::ResourceLimit { .. })
    ));

    // A high-match request retains one matched/scored entry per hit, so its
    // ceiling still scales with the retained (not transient) state.
    let all_min = min_bytes(&wide_snapshot, &Query::MatchAll);
    assert!(
        all_min > wide_min,
        "retaining 1000 hits must cost more than retaining one: all={all_min} one={wide_min}"
    );
}

// ---------------------------------------------------------------------------
// U13/U14 — batch cap parity and cancellation cleanup through the batch path
// ---------------------------------------------------------------------------

fn batch_policy(memory: u64) -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 8)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, memory)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 20)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn batch_requests() -> Vec<QueryRequest> {
    let mut first = QueryRequest::new(term("title", "alpha"));
    first.top_k = TopK::new(64).unwrap();
    let mut second = QueryRequest::new(typed_all());
    second.top_k = TopK::new(64).unwrap();
    vec![first, second]
}

fn run_batch(
    snapshot: &ReaderSnapshot,
    policy: &BudgetPolicy,
    cancel: &dyn Cancellation,
) -> Vec<Result<Vec<String>, String>> {
    let response = execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(batch_requests(), None, BatchBudget::new(8)),
        policy,
        &CapabilitySet::new(),
        cancel,
    )
    .expect("batch request envelope");
    response
        .results()
        .iter()
        .map(|outcome| match outcome {
            PerQueryOutcome::Success(response) => {
                let mut keys: Vec<String> = response
                    .hits
                    .iter()
                    .map(|hit| hit.key.as_str().to_owned())
                    .collect();
                keys.sort_unstable();
                Ok(keys)
            }
            PerQueryOutcome::Failure(error) => Err(format!("{error:?}")),
        })
        .collect()
}

#[test]
fn u13_batch_memory_caps_keep_slot_ownership_without_cross_slot_bypass() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();

    // A single-byte aggregate ceiling cannot admit either slot's retained state.
    let tight = run_batch(&snapshot, &batch_policy(1), &NeverCancel);
    assert_eq!(tight.len(), 2);
    assert!(
        tight.iter().all(|slot| slot.is_err()),
        "tight batch memory must fail every slot, got {tight:?}"
    );

    // Generous ceiling: each slot matches its standalone result exactly.
    let generous = run_batch(&snapshot, &batch_policy(1 << 20), &NeverCancel);
    let standalone_alpha = keys(&run_default(&snapshot, &term("title", "alpha")));
    let standalone_typed = keys(&run_default(&snapshot, &typed_all()));
    assert_eq!(generous[0].as_ref().unwrap(), &standalone_alpha);
    assert_eq!(generous[1].as_ref().unwrap(), &standalone_typed);
}

#[test]
fn u14_batch_cancellation_charges_nothing_to_the_next_slot() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();

    // Baseline: the same batch fully succeeds at this ceiling.
    let baseline = run_batch(&snapshot, &batch_policy(1 << 20), &NeverCancel);
    assert!(baseline.iter().all(Result::is_ok));

    // A cancelled batch fails its slots as cancelled, never partially.
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let cancelled = run_batch(&snapshot, &batch_policy(1 << 20), &cancel);
    assert_eq!(cancelled.len(), 2);
    assert!(
        cancelled.iter().all(|slot| slot
            .as_ref()
            .is_err_and(|error| error.contains("Cancelled"))),
        "cancelled batch slots must report Cancelled, got {cancelled:?}"
    );

    // The failed batch released every reservation: the identical ceiling admits
    // a fresh batch with the unchanged results.
    let after = run_batch(&snapshot, &batch_policy(1 << 20), &NeverCancel);
    assert_eq!(after, baseline);
}

// ---------------------------------------------------------------------------
// PR 15E Phase 4 — postings-driven single-term candidate enumeration
// (production writer -> snapshot -> unified search path)
// ---------------------------------------------------------------------------

/// Expected live keys for one fixture predicate, derived from the model only.
fn phase4_expected(
    predicate: impl Fn(&(&'static str, &'static str, &'static str, i64)) -> bool,
) -> Vec<String> {
    live_model()
        .into_iter()
        .filter(|row| predicate(row))
        .map(|(key, ..)| key.to_owned())
        .collect()
}

/// I01/I02: an eligible exact-term query returns exactly the model's live matches
/// across four segments with deletes and one upsert, and the sorted variant is
/// equally exact (the frozen adapter sorts too).
#[test]
fn phase4_i01_i02_exact_term_is_exact_across_generations() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();
    let query = Query::Term {
        field: "tag".to_owned(),
        value: FieldValue::Keyword("even".to_owned()),
    };
    let mut expected = phase4_expected(|(_, _, tag, _)| *tag == "even");
    expected.sort();

    let response = run_default(&snapshot, &query);
    assert_eq!(response.total_hits, expected.len() as u64);
    assert_eq!(keys(&response), expected);
    assert!(response.hits.iter().all(|hit| hit.score.is_some()));

    // Sorted request (doc-values sort) stays exact and ordered by `n`.
    let mut request = UnifiedRequest::new(query.clone(), TopK::new(64).unwrap());
    request.sort = quervant_core::contract::result::Sort::new(vec![
        quervant_core::contract::result::SortField::new(
            "n",
            quervant_core::contract::result::SortDirection::Asc,
        ),
    ]);
    let schema = schema();
    let registry = registry();
    let sorted = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .expect("sorted exact-term query");
    assert_eq!(sorted.total_hits, expected.len() as u64);
    let mut sorted_ns: Vec<i64> = Vec::new();
    for hit in &sorted.hits {
        let n: i64 = hit.key.as_str()[1..].parse().unwrap();
        sorted_ns.push(n);
    }
    assert!(sorted_ns.windows(2).all(|pair| pair[0] <= pair[1]));
    let mut sorted_keys: Vec<String> = sorted
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    sorted_keys.sort();
    assert_eq!(sorted_keys, expected);
}

/// I04: every non-eligible shape keeps the legacy path and its exact results.
#[test]
fn phase4_i04_fallback_shapes_match_model() {
    let index = tombstoned_index();
    let snapshot = index.snapshot();

    let cases: Vec<(Query, Vec<String>)> = vec![
        (
            Query::And(vec![
                Query::Term {
                    field: "tag".to_owned(),
                    value: FieldValue::Keyword("even".to_owned()),
                },
                typed_at_least(8),
            ]),
            phase4_expected(|(_, _, tag, n)| *tag == "even" && *n >= 8),
        ),
        (
            Query::Or(vec![
                Query::Term {
                    field: "tag".to_owned(),
                    value: FieldValue::Keyword("odd".to_owned()),
                },
                typed_at_least(16),
            ]),
            phase4_expected(|(_, _, tag, n)| *tag == "odd" || *n >= 16),
        ),
        (
            Query::Not(Box::new(Query::Term {
                field: "tag".to_owned(),
                value: FieldValue::Keyword("even".to_owned()),
            })),
            phase4_expected(|(_, _, tag, _)| *tag != "even"),
        ),
        (
            Query::Phrase {
                field: "title".to_owned(),
                terms: vec!["alpha".to_owned()],
            },
            phase4_expected(|(_, title, _, _)| *title == "alpha"),
        ),
        (Query::MatchAll, phase4_expected(|_| true)),
    ];

    for (query, expected) in cases {
        let response = run_default(&snapshot, &query);
        assert_eq!(response.total_hits, expected.len() as u64, "{query:?}");
        assert_eq!(keys(&response), expected, "{query:?}");
    }
}
