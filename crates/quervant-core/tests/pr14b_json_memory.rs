//! PR 14B — `R-14A-JSON-MEM` observational characterization (B20/B21).
//!
//! This binary installs a test-only tracking global allocator so a freshly
//! spawned child process can report the peak heap active while a
//! high-occurrence JSON-path sort runs under exact and one-under
//! `BatchMemoryBytes`.
//!
//! After PR 14D the JSON sort path admits occurrence and winner scratch through
//! `BatchMemoryBytes` before the retained buffers grow. This probe records the
//! post-fix charged threshold and the tracked allocator-window peak side by side;
//! it is not an RSS bound and does not claim a physical memory cap.
//!
//! The child entrypoint runs in its own process so allocator accounting cannot
//! be polluted by other tests running concurrently in the same binary.

mod pr14_common;

use std::sync::Arc;
use std::sync::atomic::Ordering;

use pr14_common::{committed, doc, registry, schema, set};
use quervant_core::analysis::{Cancellation, CancellationFlag};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::error::QueryError;
use quervant_core::contract::query::{JsonPathExpr, Query};
use quervant_core::contract::result::{
    MultiValueSelector, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::value::{FieldValue, JsonNumber, JsonValue};
use quervant_core::index::ReaderSnapshot;
use quervant_core::search::{SearchLimits, execute_batch};

/// Test-only, coarse heap accounting. Active only inside an explicit
/// measurement window; otherwise it is a pair of relaxed atomic loads.
mod probe {
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    pub static RECORDING: AtomicBool = AtomicBool::new(false);
    pub static CURRENT: AtomicUsize = AtomicUsize::new(0);
    pub static PEAK: AtomicUsize = AtomicUsize::new(0);

    pub struct Tracking;

    unsafe impl GlobalAlloc for Tracking {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            let ptr = unsafe { System.alloc(layout) };
            if !ptr.is_null() && RECORDING.load(Ordering::Relaxed) {
                let now = CURRENT.fetch_add(layout.size(), Ordering::Relaxed) + layout.size();
                PEAK.fetch_max(now, Ordering::Relaxed);
            }
            ptr
        }

        unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
            if RECORDING.load(Ordering::Relaxed) {
                // Preserve saturating subtraction on both stable and the
                // workspace MSRV without the deprecated fetch_update API.
                let mut current = CURRENT.load(Ordering::Relaxed);
                loop {
                    match CURRENT.compare_exchange_weak(
                        current,
                        current.saturating_sub(layout.size()),
                        Ordering::Relaxed,
                        Ordering::Relaxed,
                    ) {
                        Ok(_) => break,
                        Err(observed) => current = observed,
                    }
                }
            }
            unsafe { System.dealloc(ptr, layout) };
        }
    }
}

#[global_allocator]
static GLOBAL: probe::Tracking = probe::Tracking;

fn measure_peak<T>(body: impl FnOnce() -> T) -> (T, usize) {
    probe::CURRENT.store(0, Ordering::SeqCst);
    probe::PEAK.store(0, Ordering::SeqCst);
    probe::RECORDING.store(true, Ordering::SeqCst);
    let value = body();
    probe::RECORDING.store(false, Ordering::SeqCst);
    (value, probe::PEAK.load(Ordering::SeqCst))
}

fn occurrence_doc(count: usize) -> quervant_core::contract::document::Document {
    let events: Vec<JsonValue> = (0..count)
        .map(|index| {
            JsonValue::Object(vec![(
                "v".to_owned(),
                JsonValue::Number(JsonNumber::I64(index as i64)),
            )])
        })
        .collect();
    let body = JsonValue::Object(vec![("events".to_owned(), JsonValue::Array(events))]);
    let mut document = doc("huge");
    set(&mut document, "body", FieldValue::Json(body));
    document
}

fn build_index(count: usize) -> quervant_core::index::Index {
    committed(vec![occurrence_doc(count)])
}

fn json_sort_request() -> QueryRequest {
    let mut request = QueryRequest::new(Query::MatchAll);
    request.sort = Sort::new(vec![
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.events[*].v").unwrap())
            .with_multi(MultiValueSelector::Min),
    ]);
    request.top_k = TopK::new(1).unwrap();
    // Keep the source projection out of the response so the logical meter
    // isolates the sort/budget path from per-document source bytes.
    request.projection = Projection::Fields(Vec::new());
    request
}

fn policy_with(memory: u64, response: u64, work: u64) -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 4)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, memory)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, response)
            .unwrap()
            .with(BudgetKind::BatchAggregate, work)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn run_batch(
    snapshot: &Arc<ReaderSnapshot>,
    memory: u64,
    response: u64,
    work: u64,
    cancel: &dyn Cancellation,
) -> quervant_core::contract::batch::BatchQueryResponse {
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![json_sort_request()], None, BatchBudget::new(4)),
        &policy_with(memory, response, work),
        &CapabilitySet::new(),
        cancel,
    )
    .unwrap()
}

fn succeeded(response: &quervant_core::contract::batch::BatchQueryResponse) -> bool {
    matches!(response.slot(0), Some(PerQueryOutcome::Success(_)))
}

/// Smallest `BatchMemoryBytes` for which the high-occurrence sort succeeds.
fn min_memory(snapshot: &Arc<ReaderSnapshot>) -> u64 {
    let cancel = CancellationFlag::new();
    let mut low = 1u64;
    let mut high = 1u64 << 40;
    while low < high {
        let mid = low + (high - low) / 2;
        if succeeded(&run_batch(snapshot, mid, 1 << 30, 1 << 30, &cancel)) {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

struct ImmediateCancel;

impl Cancellation for ImmediateCancel {
    fn is_cancelled(&self) -> bool {
        true
    }
}

/// Child entrypoint (invoked only by `b20_b21_json_occurrence_memory_characterization`).
#[test]
#[ignore = "internal child entrypoint for the B20/B21 memory probe"]
fn b20_child_json_memory_probe() {
    let count: usize = match std::env::var("QUERVANT_PR14B_JSON_MEM_COUNT") {
        Ok(value) => value.parse().expect("occurrence count"),
        Err(_) => return,
    };
    let index = build_index(count);
    let snapshot = index.snapshot();
    let logical = min_memory(&snapshot);

    let ((), peak_exact) = measure_peak(|| {
        let response = run_batch(
            &snapshot,
            logical,
            1 << 30,
            1 << 30,
            &CancellationFlag::new(),
        );
        assert!(succeeded(&response), "exact logical limit must succeed");
    });
    let ((), peak_one_under) = measure_peak(|| {
        let response = run_batch(
            &snapshot,
            logical - 1,
            1 << 30,
            1 << 30,
            &CancellationFlag::new(),
        );
        assert_eq!(
            response.slot(0),
            Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
                kind: BudgetKind::BatchMemoryBytes
            })),
            "one-under logical limit must fail typed"
        );
    });
    // Cancellation is typed and never reports a partial successful response.
    let ((), peak_cancelled) = measure_peak(|| {
        let response = run_batch(&snapshot, logical, 1 << 30, 1 << 30, &ImmediateCancel);
        assert!(matches!(
            response.slot(0),
            Some(PerQueryOutcome::Failure(QueryError::Cancelled { .. }))
        ));
    });
    println!(
        "PROBE count={count} logical_memory={logical} peak_exact={peak_exact} \
         peak_one_under={peak_one_under} peak_cancelled={peak_cancelled}"
    );
}

/// B20/B21 — observational characterization of unmetered temporary JSON
/// occurrence memory. Records logical metering separately from tracked heap.
#[test]
fn b20_b21_json_occurrence_memory_characterization() {
    let exe = std::env::current_exe().expect("current test binary");
    let mut rows = Vec::new();
    for count in [1usize, 128, 4096] {
        let output = std::process::Command::new(&exe)
            .args([
                "--ignored",
                "--exact",
                "b20_child_json_memory_probe",
                "--nocapture",
                "--test-threads=1",
            ])
            .env("QUERVANT_PR14B_JSON_MEM_COUNT", count.to_string())
            .output()
            .expect("spawn memory probe child");
        assert!(
            output.status.success(),
            "child count={count} failed: {}\n{}",
            String::from_utf8_lossy(&output.stderr),
            String::from_utf8_lossy(&output.stdout)
        );
        let stdout = String::from_utf8_lossy(&output.stdout);
        let parse = |name: &str| -> u64 {
            let prefix = format!("{name}=");
            stdout
                .split_whitespace()
                .find_map(|token| token.strip_prefix(&prefix))
                .unwrap_or_else(|| panic!("missing {name} in child output: {stdout}"))
                .trim_matches(|character: char| !character.is_ascii_digit())
                .parse()
                .expect("numeric measurement")
        };
        rows.push((
            count,
            parse("logical_memory"),
            parse("peak_exact"),
            parse("peak_one_under"),
            parse("peak_cancelled"),
        ));
    }
    for (count, logical, peak_exact, peak_one_under, peak_cancelled) in &rows {
        println!(
            "B20/B21 occurrences={count} logical_BatchMemoryBytes={logical} \
             tracked_peak_exact={peak_exact} tracked_peak_one_under={peak_one_under} \
             tracked_peak_cancelled={peak_cancelled}"
        );
    }
    // Post-fix governance: the charged logical boundary grows with the live
    // occurrence demand instead of staying at an occurrence-independent value.
    assert!(
        rows[0].1 > 0 && rows[1].1 > 0 && rows[2].1 > 0,
        "every charged threshold must be positive: {rows:?}"
    );
    assert!(
        rows[0].1 < rows[1].1 && rows[1].1 < rows[2].1,
        "charged BatchMemoryBytes threshold must grow with occurrences: {rows:?}"
    );
    // Immaterial to the claim: exact/one-under windows must be observed and the
    // one-under rejection must not produce a larger tracked window than exact.
    assert!(
        rows.iter().all(|row| row.2 > 0 && row.3 > 0),
        "tracked heap must be observed for every window: {rows:?}"
    );
    assert!(
        rows.iter().all(|row| row.3 <= row.2),
        "one-under must reject without exceeding the exact-limit window: {rows:?}"
    );
    assert!(
        rows[2].2 > rows[0].2,
        "tracked exact-limit heap still grows with occurrences: {rows:?}"
    );
}
