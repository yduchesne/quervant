# PERF-06-B1-F2 — Final cancellation, RAII adversaries and complete-value oracles

**Repository:** `yduchesne/quervant`  
**Existing PR / branch:** [PR #126](https://github.com/yduchesne/quervant/pull/126), `dev/perf06-b1`  
**Accepted base:** `main@480a77e78c6897e05cb7ceb76b01434974b82ec6`  
**F1 executable source, already reviewed:** `1b9621e2d089f7658e5749a8ad73e3153d1b2045`  
**F1 final head observed during F2 authoring:** `d579b7fd926ee96f0f79df6b74c58bd8ff61c51a`  
**F1 predecessor:** `8e11484af49e38243a97d765ef21662f7e3060a3`  
**Precedence:** current repo `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` §§3A–3F, 27, 37–38, frozen `docs/pr-artifacts/perf-06-b/PERF06B1_DETAILED_PLAN.md` §§8.5–8.8, 9.5, 12–18, F1 detailed fixup plan and current architecture. Where F2 is narrower, it does not revoke any inherited invariant.  
**Purpose:** close the two remaining publication/RAII correctness gaps and two narrower coverage gaps from the independent F1 review. **Do not redesign B1.**

> **PR-state observation, not an instruction to change it:** GitHub reported PR #126 open, `draft=false` at the frozen F1 head. Retain the existing actual PR state. The earlier agent report describing it as draft is not an authorization to toggle its state. Do not merge, approve, release or begin B2.

## 0. Absolute execution contract (read first)

**Continuous execution authorization:** Execute this approved plan from exact preflight through implementation, focused tests, final applicable QA, documentation, one normal push and observation of ordinary CI **without asking for routine permission**. Advance automatically after successful steps and applicable **AUTO-RESOLVE** rules. On a scoped **HARD STOP**, preserve its evidence and continue only genuinely independent permitted tasks. On an unresolved decision, record it and stop the dependent work; never invent a new design. Host-load/stability observations are **informative and non-blocking**; storage-service reachability, correctness, budget and source-identity gates are not.

Non-negotiable restrictions:

1. **Same PR and same branch.** Fetch and fast-forward only; no rebase, reset, force push, auto-stash, broad cleanup or new PR. If the branch is dirty, **HARD STOP mutations**, preserving the user-owned files.
2. **Preserve the established physical design:** `FEATURE_KEYWORD_ORDINALS=0x0010/1`; COLUMNS v2/layout 3; ordered local dictionaries; compact per-document ordinal slots; exact snapshot-bound numeric translation; sticky optional outcomes; existing `MetadataBudget` and `MetadataMeter`. No new persisted feature, metadata account, public parameter, cache, executor or cross-segment identity scheme.
3. **Protect all already-qualified F1 work.** No changes to segment format, column encoder/decoder except the permitted test-only U10 assertion, immutable fixture bytes, source `segment/metadata.rs`, production `search/*`, storage/remote/provider, schema contracts, index writer/merge, benchmarks, A4–A6 evidence, CI topology, Cargo files, toolchains, `AGENTS.md` or the authoring guide.
4. **F2 production code change only** in `crates/quervant-core/src/index/keyword_ordinals.rs`: cooperative cancellation at every remaining publication boundary and periodic schema-enumeration cancellation. Test-only fault/wait instrumentation belongs in that same file. No source change elsewhere is authorized.
5. **F2 test changes only** in the `b1_tests` module of `crates/quervant-core/src/segment/column.rs` (U10), in `tests/perf06_b1_common/mod.rs` (independent expected projection), `tests/perf06_b1_ordinals.rs` (I04 full projected fields), and `tests/perf06_b1_rustfs.rs` (R01 full projected fields). Scope these to assertions/oracles, not new production behavior.
6. **Evidence/docs only** in `docs/pr-artifacts/perf-06-b/PERF06B1_F2_DETAILED_FIXUP_PLAN.md`, additive `PERF06B1_EXECUTION_REPORT.md` F2 section and new `docs/pr-artifacts/perf-06-b/evidence/f2-*`. Do not rewrite or delete the original/F1 negative evidence or plans. No broad roadmap edits.
7. No performance acquisition, profiling, Tantivy/Lucene execution, A6 rerun, new RustFS system, background service or benchmark-framework work. Ordinary `cargo bench --no-run` is a compilation gate, **not** an acquisition.
8. Real correctness acceptance is mandatory. A test existing or compiling is not evidence that it ran. A green old-head CI result is not evidence of F2 success. **G10 stays explicitly maintainer-owned and open.**

## 1. Mandatory exact source preflight and in-progress reconciliation

From the repo root, before editing, execute and save output to `docs/pr-artifacts/perf-06-b/evidence/f2-preflight.txt` (never dump credentials):

```bash
set -euo pipefail
git status --porcelain=v1
git fetch origin
git switch dev/perf06-b1
git pull --ff-only origin dev/perf06-b1
git status --porcelain=v1
git rev-parse HEAD
git rev-parse origin/dev/perf06-b1
git rev-parse origin/main
git merge-base HEAD origin/main
git diff --name-status 1b9621e2d089f7658e5749a8ad73e3153d1b2045..HEAD
git diff --name-status 480a77e78c6897e05cb7ceb76b01434974b82ec6..HEAD
```

Verify the PR still targets `main` and the accepted base is its actual merge-base. Verify the original B1 plan and F1 plan and source code are present. The accepted base is stable: **do not rerun a suite on `main`**. Read the following exact symbols from the fast-forwarded F1 tree:

- `index/keyword_ordinals.rs`: `KeywordOrdinalCache::prepare`, `build_and_publish`, `initialize_registry`, `RegistryInitGuard`, `FieldBuildGuard`, `EntryState`, `RegistryState`, `run_after_claim_hook`, `WAIT_STARTS`, `build_field_map`, `set_alloc_fault`, and the G12–G16 test helpers.
- `segment/column.rs`: `b1_u10_frozen_codec_differential_families`.
- `tests/perf06_b1_common/mod.rs`: `ROWS`, `City`, `document_at`, `projection`, `projection_without_city`, and `Batch::category`.
- `tests/perf06_b1_ordinals.rs`: `assert_city_view`, `assert_legacy_city_view`, `b1_i04_historical_fixture_append_compact_and_reopen`, `b1_i04_child_body`.
- `tests/perf06_b1_rustfs.rs`: `sorted_keys`, `assert_full_view`, the `b1_r01_...` test and existing provider-only immutable-closure verification.

**Expected current reconciliation:** F1 has corrected the original memory admission, decoder overflow, error precedence, fallible string copy and wait predicate. F1's original source and CI checks passed. The only unresolved *production* contract is cancellation polling before four publication transitions and through registry field scans; the only unresolved acceptance proofs are actual field-claim cleanup/error/panic/waiter tests, U10 one-element-Multi value equality and six-field I04/R01 projected-value equality.

If current head equals `d579b7fd926ee96f0f79df6b74c58bd8ff61c51a`, proceed. If newer commits changed **only** B1 report/evidence, AUTO-RESOLVE by pinning the newer full SHA and checking that all four original F1 executable/test file blobs equal F1. If a newer executable/test/CI file differs, **HARD STOP affected implementation**: do not overwrite work; report the precise diff for maintainer reconciliation. If `main` has advanced or branch diverged, preserve state and **HARD STOP** dependent edits instead of silently rebasing. Do not claim the PR is draft unless the API actually says so.

### 1.1 Correctness challenge before code edits

Populate a short invariant worksheet in the F2 report: for each F2 invariant below, identify a *positive* case and one plausible counterexample, exact production symbol, test entry point, observed expected result, and cleanup state. Explicitly challenge: cancellation after a build succeeded but before publication; map field already in `Building`; registry `NotAvailable` construction; panic after memory reservation; waiter already in a timed wait; MultiOne carrying the wrong string with the correct cardinality; and projection returning six wrong fields. Unlisted scope/API contradictions invoke decision row X24, not agent design authority.

## 2. Frozen invariants, state transitions and traceability

| Invariant | Required observable contract | Positive witness | Counterexample / negative witness | Affected gates |
|---|---|---|---|---|
| **F2-I01** registry ready publication | A successful registry candidate is cancelled **outside the mutex immediately before** `Uninitialized/Initializing → Ready` publication; on observed cancellation RAII resets to `Uninitialized`, wakes waiters and frees candidate charge | `Ready` registry followed by successful field preparation | Hook cancels after registry built, before lock; `Cancelled`, no published registry | G3/G4 |
| **F2-I02** registry optional publication | Same pre-publication poll before `Initializing → NotAvailable(reason)` | `NotAvailable(Allocation)` sticky when not cancelled | Injected Allocation plus pre-publication cancellation resets to `Uninitialized` rather than sticky | G3/G4 |
| **F2-I03** field ready publication | Poll before publishing `Building → Ready(map)`; on observed cancellation drop built map/reservation, reset field to Empty and wake waiters; retry on same snapshot can succeed | Ready Arc shared after normal completion | Cancel after map built, before lock; no map published | G3/G4 |
| **F2-I04** field optional publication | Poll before publishing `Building → NotAvailable(reason)`; observed cancellation resets to Empty | Noncancelled Allocation remains sticky | Alloc-refusal followed by pre-publication cancel is not sticky | G3/G4 |
| **F2-I05** post-publication behavior | Disarm and notify before the existing final callback; a **subsequent** cancellation does not erase the published result. Polls never run under cache mutex | Another caller can reuse ready map | Cancelling caller sees `Cancelled`, no published map erased | G3/G4 |
| **F2-I06** registry scan cancellation | Poll entry, at least every 256 schema comparisons, eligibility-count items and entry-fill items, before allocation and before return/publish | Large valid schema initializes normally | Cancellable large scan aborts without partially ready registry | G3/G4 |
| **F2-I07** claim failure cleanup | Typed injected error or panic after real admission in **both registry and field** leaves no `Initializing`/`Building`, releases candidate reservations, wakes a real waiter; same snapshot can retry | Successful retry | Injected error/panic under the respective claimed state | G3/G4 |
| **F2-I08** exact codec differential | All 64 existing cases check `Single(x)` vs `MultiOne(x)` **including exact contained string**, state, local ordinal and dictionary | Every generator case equals frozen input-derived `FieldValues` | Wrong MultiOne member with same list length must fail | G4 |
| **F2-I09** complete projection | I04 and R01 compare actual ordered `(field_name, FieldValues)` tuples for **all six fields**, not counts, for every hit in both sort directions and missing placements | Historical g3/g4/g5 and R01 g3/g4 values match literal rows | One field's wrong value or missing/null shape fails | G5/G6 |
| **F2-I10** scope/provenance | No change to wire bytes, existing ordinal semantics, A6 evidence, search or storage publication; F2 tests/CI execute on declared source | Diff and CI/source ledger | Any protected-path delta or stale-head pass blocks acceptance | G0/G7/G8/G9 |

**State matrix (all four publication results):**

| Claim/state before candidate | Candidate outcome | Cancellation observed by pre-publication poll | State after operation | Caller outcome |
|---|---|---|---|---|
| Registry `Initializing` | `Ok(Registry)` | No | `Ready(Registry)` | continue field preparation |
| Registry `Initializing` | `Ok(Registry)` | Yes | `Uninitialized` via guard | `IndexError::Cancelled`; notify/release |
| Registry `Initializing` | optional `Err(reason)` | No | `NotAvailable(reason)` | sticky outcome |
| Registry `Initializing` | optional `Err(reason)` | Yes | `Uninitialized` via guard | `Cancelled`; no stickiness |
| Field `Building` | `Ok(Arc<Map>)` | No | `Ready(map)` | Ready; original after-publication poll retained |
| Field `Building` | `Ok(Arc<Map>)` | Yes | `Empty` via guard | `Cancelled`; map charge released |
| Field `Building` | optional `Err(reason)` | No | `NotAvailable(reason)` | sticky outcome |
| Field `Building` | optional `Err(reason)` | Yes | `Empty` via guard | `Cancelled`; no stickiness |
| Either | authoritative error | n/a | reset claim through RAII | preserve existing exact typed error |
| Either | unwind/panic after claim | n/a | reset claim through RAII; wake | panic caught **in test only**; never poison normal cache path |

**Cooperative-race boundary:** the final cancellation poll occurs just before acquiring the publication mutex. If cancellation becomes true *after that final poll*, the already-existing post-publication poll may report `Cancelled` while leaving the now-published result intact. Do **not** claim an atomic cancellation-versus-publication ordering that the current API cannot provide. Never invoke `Cancellation::is_cancelled` while the mutex is held; no new lock/atomic publication protocol is authorized.

## 3. F2-01 — Fix the four publication transitions (single production file)

**File:** `crates/quervant-core/src/index/keyword_ordinals.rs`.

### 3.1 Exact operation order

Use this sequence for **all four branches**. Keep the existing success/optional result representation and RAII guard. The pre-publication hook below is **test-only**, is invoked outside the mutex, and is an identity/no-op in production builds.

For `KeywordOrdinalCache::prepare` → `Next::Initialize`, replace the body of the `match initialize_registry(...)` success branches with the following sequence, retaining the original result objects and existing branch return types:

```text
Ok(Ok(registry)):
    f2_probe(BeforeRegistryReadyPublish)?       // test-only hook; no-op in release
    poll(cancellation)?                         // LAST poll BEFORE lock and publication
    state = self.lock()?                         // existing poison semantics
    assert via existing branch invariant: Initializing
    *state = Ready(registry)
    drop(state)
    init_guard.disarm()
    self.ready.notify_all()
    continue                                    // existing field lookup behavior

Ok(Err(reason)):
    f2_probe(BeforeRegistryUnavailablePublish)?
    poll(cancellation)?
    state = self.lock()?
    assert via existing branch invariant: Initializing
    *state = NotAvailable(reason)
    drop(state)
    init_guard.disarm()
    self.ready.notify_all()
    poll(cancellation)?                         // preserve existing post-publication callback
    return Ok(NotAvailable(reason))
```

For `KeywordOrdinalCache::build_and_publish`, in **both** `Ok(Ok(owner))` and `Ok(Err(reason))`:

```text
    f2_probe(BeforeFieldReadyPublish or BeforeFieldUnavailablePublish)?
    poll(cancellation)?                         // LAST poll BEFORE lock and publication
    state = self.lock()?
    existing registry / expected Building entry  // no silent publication on an unexpected state
    replace the entry with Ready(owner) or NotAvailable(reason)
    drop(state)
    build_guard.disarm()
    self.ready.notify_all()
    poll(cancellation)?                         // retain existing post-publication semantics
    return the original result
```

The expected state must be the one claimed by the guarded builder; do **not** silently succeed if the registry/entry is missing. If it is unexpectedly missing, return a fixed existing typed `IndexError::CorruptCommittedState` (details may be a new **bounded static** F2 internal detail only if no prior canonical detail matches); keep the guard armed to clean up. **HARD STOP** if the only way to implement this would be an API/state-machine redesign. Do not hold a lock during the test hook, the `poll` call, source dictionary access, callback, or caller work.

On `?` from the test hook, `poll`, or `lock`, Rust's existing guards automatically drop; their `Drop` implementations reset `Initializing→Uninitialized` and `Building→Empty`, wake waiters, and release the candidate/owner reservation. Do not explicitly reset the state in a second code path or bypass the guards. Test-only panic must occur outside the lock. Do not change sticky optional outcomes **unless pre-publication cancellation is actually observed**.

### 3.2 Small, scoped deterministic F2 fault probes

Implement one `#[cfg(test)]` thread-local, one-shot probe in `keyword_ordinals.rs`; it must not exist as a production handler. Use this frozen representation, with a no-op stub for the calls in normal builds:

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum F2Probe {
    RegistryAfterEntries,
    FieldAfterFirstPackedBuffer,
    BeforeRegistryReadyPublish,
    BeforeRegistryUnavailablePublish,
    BeforeFieldReadyPublish,
    BeforeFieldUnavailablePublish,
    RegistryEligibilityIndex256,
    RegistryFillIndex256,
}

#[cfg(test)]
thread_local! {
    static F2_PROBE: std::cell::RefCell<
        Option<(F2Probe, Box<dyn FnOnce() -> IndexResult<()>>)> 
    > = const { std::cell::RefCell::new(None) };
}
```

Provide a test-only `set_f2_probe(point, callback)` with the exact type above, and a private `f2_probe(point) -> IndexResult<()>`. The latter must: (1) take the registered closure only if its `F2Probe` matches; (2) **release the `RefCell` borrow before calling the closure**; (3) propagate the returned `IndexError` with `?`; (4) permit the closure to panic for `catch_unwind` tests. A different probe point does nothing and does not consume a pending callback. In non-test builds, `#[inline] fn f2_probe(_: F2Probe) -> IndexResult<()> { Ok(()) }`. The enum is a private zero-data discriminator; no public/test/dependency feature flag. For release tests prove no test callback/atomic remains via source `#[cfg(test)]` inspection; do not add production metrics.

Place `RegistryAfterEntries` **after** registry-entry vector population and **before** `meter.finalize`, while the registry construction allowance and vector are still live. Place `FieldAfterFirstPackedBuffer` in `build_field_map` immediately after the first inner packed buffer is successfully allocated/pushed and **before** the heap is created or the output map is published. In the no-buffer case this probe is not required; use the frozen three-segment nonempty fixture in tests. The four `Before*Publish` points go at the transitions specified above. Additionally, place `RegistryEligibilityIndex256` and `RegistryFillIndex256` at the respective field enumeration loop's **index 256**, immediately **before** the periodic `poll(cancellation)?`. These two probes enable a deterministic cancellation at a known real scan boundary. All eight points are invoked only outside cache locks; none changes production error precedence or cancellation behavior.

The existing F1 `AFTER_CLAIM_HOOK`, `PRE_WAIT_HOOK`, and allocation-fault seam remain. Do not replace them or introduce a general-purpose fault-injection subsystem. Only this one F2 probe (including its two registry-scan points) and the minimal wait-entry observer below are authorized.

## 4. F2-02 — Complete cancellation during registry enumeration

**File:** `crates/quervant-core/src/index/keyword_ordinals.rs`, `initialize_registry`.

The existing function already polls before and during comparisons of guards; preserve that. Change only the two unpolled schema-field iterations:

1. Replace `.filter(is_eligible_field).count()` with an explicit `for (index, field) in schema.fields().iter().enumerate()`. On `index == 256`, invoke `f2_probe(F2Probe::RegistryEligibilityIndex256)?` first. On `index % 256 == 0`, invoke `poll(cancellation)?`; increment `eligible` with checked arithmetic if eligible. Immediately after the loop, invoke `poll(cancellation)?`. Preserve canonical ascending field-ID order. On theoretical count overflow, use the existing optional `ResourceBudget` classification, not panic.
2. Retain `MetadataMeter::reserve`, `check_allocation_bytes`, the existing fallible `try_reserve_exact`, and `charge_vec` semantics; poll immediately before the reservation as F1 already does. No budget adjustment is authorized.
3. In the later entry-population loop, again use `enumerate()`; when `index == 256`, invoke `f2_probe(F2Probe::RegistryFillIndex256)?` first, then poll on `index % 256 == 0`; push the unchanged `RegistryEntry` only for eligible fields, then `poll(cancellation)?` after the loop and before capacity measurement/finalization. Keep the existing last poll in `initialize_registry`.
4. Optionally poll every 256 existing guard-binding checks in `prepare` too, **only** if needed to maintain the exact existing guard scan; the same `poll(cancellation)?` outside locks is the entire approved change. Do not make a schema or guard lookup per document.
5. Do not change how zero eligible fields, schema mismatch, unsupported IDs, legacy layouts or poisoned state are classified. A cancelled scan returns `IndexError::Cancelled`; the armed registry guard restores `Uninitialized` and notifies any waiting callers.

**Test (`b1_g12_f2_registry_scan_periodic_cancellation`):** Construct a real `Schema::new` with **exactly 257 fields**: eligible `city` as `Keyword/Single/FieldOptions::new(true,true,true)` with `.with_normalizer("keyword")`, plus 256 noneligible fields named `z000` through `z255`, each `FieldType::Bool`, `Cardinality::Single`, `FieldOptions::new(false,false,true)`. These names sort after `city`, so `city` keeps field ID 0 and both loops traverse index 256. Use the existing `SegmentBuilder`, analyzer registry and two genuine `SegmentSnapshot`s containing the same compatible schema, with one input document per segment whose `city` is valid and all other fields are absent; admit both guards under explicit generous test reader limits. No fake production schema. Run **two separate snapshot/cache attempts**, with an initial uncancelled flag and one probe armed respectively at `RegistryEligibilityIndex256` and `RegistryFillIndex256`: its callback calls `flag.cancel()` and returns `Ok(())`; the immediately following periodic poll must return `IndexError::Cancelled`. Assert `Uninitialized` registry, no Ready/NotAvailable publication, **zero** ordinal-budget residue in the isolated account and successful **same-snapshot** retry with a fresh uncancelled flag. Check the normal successful registry has exactly one entry with numeric field ID 0. Do not depend on a fragile global callback-count threshold. If constructing 257 real fields violates an immutable current schema hard limit, **HARD STOP that subtest** and report the actual bound—do not increase limits, silently test 2 fields, or claim to have verified a 256-periodic scan. Other independent tests proceed.

## 5. F2-03 — Deterministic G12 and G14 proof (actual claims, budget release and waiters)

**File:** the `b1_ordinals_tests` module inside `keyword_ordinals.rs`. Preserve existing G10, G12, G13, G14, G15, G16 and G19 tests. Add distinct `b1_g12_f2_...`, `b1_g14_f2_...` tests, or narrow extensions that display those precise roles in the test inventory. Do not change names/expected outcomes of prior passing tests.

### 5.1 Reuse real admitted guards and an isolated ordinal budget

Reuse `three_segment_snapshot()`, `guards_of`, `KeywordOrdinalCache::new`, `MetadataBudget::new(u64::MAX)` and `isolated_prepare` from F1. They exercise actual, already-admitted `GuardedSegmentReader`s and real dictionaries, not mock ordinal sources. For **field-stage** cases, first initialize and publish a genuine `Registry` by calling the existing private `initialize_registry(budget, SegmentLimits::default(), &guards, &CancellationFlag::new())`; put it into the private `cache.state` under the lock as `RegistryState::Ready(registry)` and then release the lock. Assert its one eligible field starts at `EntryState::Empty`. The subsequent `cache.prepare(...)` must take `Next::Build`, **never `Next::Initialize`**. Record the retained registry charge `R` before the field attempt. For registry cases use a fresh uninitialized cache and `R=0`.

The `MetadataBudget` for these tests is independent of the snapshot's already-retained verified-segment metadata, as explicitly authorized by F1's isolated-account decision. **Do not** treat a sticky `Allocation` result as evidence that an in-progress claim resets.

### 5.2 Four pre-publication cancellation cases

| Test ID | Setup / exact probe | Expected |
|---|---|---|
| `b1_g12_f2_registry_ready_cancel_before_publish` | Fresh uninitialized cache, `BeforeRegistryReadyPublish` closure cancels shared `CancellationFlag` and returns `Ok(())` | `Err(IndexError::Cancelled)`; state `Uninitialized`; ordinal budget returns to 0; subsequent same-cache valid preparation returns Ready |
| `b1_g12_f2_registry_optional_cancel_before_publish` | Fresh cache, `set_alloc_fault(Some(0))` so registry returns optional `Allocation`, `BeforeRegistryUnavailablePublish` cancels flag | `Cancelled`, not sticky; clear fault, same-cache valid preparation returns Ready |
| `b1_g12_f2_field_ready_cancel_before_publish` | Genuine registry already `Ready`, entry `Empty`, `BeforeFieldReadyPublish` cancels after complete map built | `Cancelled`; entry `Empty`; measured account returns **exactly R**; clear hook, same-cache call returns Ready |
| `b1_g12_f2_field_optional_cancel_before_publish` | Genuine registry `Ready`, `set_alloc_fault(Some(0))` hits the first **field** allocation, `BeforeFieldUnavailablePublish` cancels | `Cancelled`, no sticky `NotAvailable`; clear fault; entry `Empty`, account R; same-cache retry returns Ready |

For all tests reset `set_alloc_fault(None)` and any test-only thread-local probe when unwinding; a scoped cleanup guard in the tests is allowed. Inspect both the registry/field state **after** the cancelled call and the returning result; a `Cancelled` return alone is insufficient. Use the same snapshot and same cache on retry, not a new snapshot. Assert `Arc` and registry charges are released as appropriate; other F1 G15/G19 tests remain authoritative for published-map lifetime.

### 5.3 Genuine post-claim error and panic with live allocations

Create the following matrix; execute **both injected typed error and panic** for **both construction kinds**. The two construction-fault points are deliberately inside actual constructors after real charged allocation, not at API entry or in a different cache state. The two scan points belong only to §4's cancellation checks.

| Test ID family | Probe | Error run | Panic run | Expected after error/unwind |
|---|---|---|---|---|
| `b1_g14_f2_registry_after_entries` | `RegistryAfterEntries` | closure returns `Err(IndexError::CorruptCommittedState { detail: "f2 injected registry failure".to_owned() })` | closure `panic!("f2 injected registry panic")` inside `catch_unwind(AssertUnwindSafe(...))` | cache `Uninitialized`, ordinal budget 0; next same-snapshot call creates a registry and Ready map |
| `b1_g14_f2_field_after_buffer` | `FieldAfterFirstPackedBuffer` | exact injected `IndexError::CorruptCommittedState { detail: "f2 injected field failure".to_owned() }` | catch controlled panic outside mutex | genuine registry stays Ready, its claimed entry `Empty`, budget exactly R; next same-snapshot field preparation succeeds |

For error tests assert the exact injected typed error detail, not merely `.is_err()`. For panic tests assert `catch_unwind` returned `Err` and that the cache **was not poisoned**: subsequent preparation must succeed. Assert the budget values *before* retry and after final owner drops. The test-only injected details must never become production error variants, catch-all fallback handling, or user-data strings in the normal path.

### 5.4 Real blocked waiter and RAII `notify_all` witness

A waiter that returns only because it was never blocked does **not** prove F2-I07. For each claim kind (`Initializing` and a genuinely `Ready(registry)`/`EntryState::Building`), run one failure case with a real waiter:

1. Spawn **builder thread A**, with its own acquired ordered guard set from an `Arc<ReaderSnapshot>`; install a thread-local `BeforeRegistryReadyPublish` or `BeforeFieldReadyPublish` probe that **signals candidate-ready** over a test-only channel, then waits on a second channel without holding the cache mutex. For these two cases the callback returns the fixed injected typed error after main releases it. (A separate panic matrix under §5.3 already proves unwind.)
2. Main waits for `candidate-ready` and observes the correct in-progress state. Spawn **waiter thread B**, which acquires its **own** guard set and calls the same cache's `prepare` with an uncancelled flag.
3. Add one test-only `WAIT_ENTERED_OBSERVER: RefCell<Option<Arc<AtomicBool>>>` attached to the waiter thread. In `KeywordOrdinalCache::wait`, after the predicate is verified true under the mutex and **immediately before** `wait_timeout`, set that observer to `true` using `AtomicBool::store(SeqCst)` in `#[cfg(test)]` code only. No callback, channel send, allocation, cancellation poll or arbitrary user code runs under the mutex. Main waits for the observer using a bounded test-only channel/spin/yield deadline; timeout is an assertion failure, not an application retry or performance gate.
4. Release builder A's probe. It must return the exact injected error; its RAII guard resets `Initializing→Uninitialized` or `Building→Empty`, drops candidate allocation and `notify_all`s. Waiter B wakes and **without a new external notification requirement** can complete the same registry or field preparation to Ready. Verify `Arc` and numerical result as in the existing G01. If waiter B becomes the new builder this is allowed; its preparatory state must be from the same real guards and schema.
5. Both threads join without hang, the candidate's charge is released and only the later published value remains accounted. Drop map/cache/guards and assert ordinal-budget charge returns to 0. No fixed sleeps, elapsed-time "win" or retry loop to make this gate pass.

Use `std::thread`, `Arc`, `std::sync::mpsc` and existing test synchronization; no external concurrency library. A bounded observation timeout may abort the **test** with a clear failure, but does not change production `WAIT_INTERVAL=5ms`. Test-only observability must not be required by normal program behavior. `GuardedSegmentReader` is not `Send`: **construct guards inside each thread**, never send them across threads.

### 5.5 Additional cancellation coverage checklist

Prove all these distinct transitions, not substitutes: (a) registry after its entries are allocated, (b) field after a map candidate is built, (c) registry and field **optional** results before publication, (d) actual entry claimed at field stage, (e) both error and panic with live candidate memory, (f) a waiter that demonstrably entered `wait_timeout` and was released by RAII, (g) an already-published Ready map stays `Arc`-identical when a later caller is cancelled. Preserve existing F1 G13 lost-notification/spurious-wake checks and G16's seven allocation sites.

## 6. F2-04 — U10 checks the exact one-element Multi string

**File:** `crates/quervant-core/src/segment/column.rs`, in `b1_u10_frozen_codec_differential_families` only.

Keep the existing **64 deterministic cases**, fixed `ALPHABET`, selectivity generator, raw-byte sorted dictionary, and numeric ordinals. Strengthen the test-only expected rows to record the complete **input-derived `FieldValues`** and expected `KeywordOrdinalState`. The expected object must be captured from the values being placed into `SegmentDocument` (e.g. clone the generated `FieldValues` in the test), not decoded from `ColumnReader`. For every produced doc:

- Assert `reader.value(field_id, doc_id) == expected_values` **including** `FieldValues::Multi(vec![FieldValue::Keyword(expected_text)])` with the exact keyword bytes. No `len()==1`-only proof.
- For `Single(x)` and `MultiOne(x)`, verify the exact `doc_ordinal` `Value { state, ordinal }`, and compute the expected local ordinal by binary searching the independently sorted/deduplicated input terms.
- For `Absent` and `ExplicitNull`, verify distinct states and unchanged string absence semantics.
- Add a negative oracle sanity check: intentionally change the expected MultiOne string in a **test-only expected object**, assert that the correct production value is **not equal**; this demonstrates the test would detect a wrong string without corrupting the production codec.

Do not change encoded bytes, the frozen 116-byte literal, public codec APIs, or the 64-case generator. Do not broaden to a new property-testing dependency.

## 7. F2-05 — Full six-field projected-value oracles in I04 and R01

### 7.1 One independent shared test helper

**File:** `crates/quervant-core/tests/perf06_b1_common/mod.rs`.

Add exactly one test-only helper `pub fn expected_projected_fields(key: &str) -> Vec<(String, FieldValues)>` with this **literal input-to-output contract**. It must *not* use a production reader, query result, codec, segment map, or ordinal translator to generate expected values.

For each `key` in `ROWS`, find its `(row, Batch, City)` and its 0-based array position `n`. For appended keys use the fixed exceptions: `d0` means city `Chicago`, category `type-d`, n=18; `d1` means city `Seattle`, category `type-d`, n=19. Any other key panics in the **test helper**. Construct the six fields in exactly `projection()` order:

| Field name | Expected `FieldValues` |
|---|---|
| `body` | `Single(Text("common"))` |
| `category` | `Single(Keyword(batch.category()))` for original rows; `Single(Keyword("type-d"))` for `d0`/`d1` |
| `city` | Original row's `City::values()` (`Absent`, `ExplicitNull` or `Single(Keyword(raw_value))`); for `d0`/`d1` respective Single city |
| `n` | `Single(I64(original_position))`; for `d0` 18, `d1` 19 |
| `stored_tag` | `Single(Keyword("stored"))` |
| `tags` | `Multi([Keyword("one"), Keyword("two")])` in this order |

Use existing `FieldValues`, `FieldValue`, `ROWS`, `City`, `Batch`, `projection`. This is an input oracle, not another implementation of decoding, sorting or aggregation. Do not change the frozen 18 rows, schema, historical producer, on-disk fixture or projection configuration.

### 7.2 Local historical I04 and held views

**File:** `crates/quervant-core/tests/perf06_b1_ordinals.rs`.

In both `assert_legacy_city_view` (g3/g4) and `assert_city_view` (g5, child) replace the weak assertion `hit.fields.len()==6` with:

```rust
assert_eq!(
    hit.fields,
    perf06_b1_common::expected_projected_fields(hit.key.as_str()),
    "full projection mismatch for {}",
    hit.key.as_str(),
);
```

If this file imports the shared module under an alias, use that existing alias; **do not create a second oracle**. Apply to every hit in both ASC and DESC, missing-first/missing-last, and all specified K-prefix requests, **including the actual generation-5 child subprocess**. For original g3/g4 (which has no ready ordinal map), the ordinary query with projections must still return the same six values. Preserve g3→g4→g5 generations, the genuine old fixture and its hashes, immutable object proof, complete city rank tests, aggregate counts/sum190/distinct20, type-d append, held PITs and child marker.

### 7.3 Real RustFS R01

**File:** `crates/quervant-core/tests/perf06_b1_rustfs.rs`.

In `sorted_keys`, before reducing `response.hits` to keys, assert **each hit's actual `fields`** equals `corpus::expected_projected_fields(hit.key.as_str())`. The existing `sorted_keys` signature and its exact ordering/total comparisons stay unchanged. Thus every call in `assert_full_view` now verifies all six fields for all 18/19 hits and the K=1,5,N prefixes under both directions and both missing placements. Include the `d0` appended type-d case; no `d1` is present in R01. The provider-only five-object generation-3 closure, two separate g4 cold workspaces, held g3 PIT, request-count checks and cleanup remain unchanged.

**R01 must really execute** against the repository's pinned real RustFS image in ordinary CI on the F2 executable source, with `b1_r01_cold_shared_ordinals_and_pit ... ok`. Do not substitute a mock, a compile-only gate or the already-green F1 RustFS log. **Do not start a second local RustFS container just to duplicate ordinary hosted CI**; if CI is unavailable, report G6/G8 blocked and continue local independent work. No remote compaction publication is authorized; A6's residual remains.

## 8. Ordered steps and exact test/CI procedure

### P0. Inspect and preserve evidence

Perform §1, read all authority and classify inherited G0–G9 evidence. Freeze the actual starting head SHA in `f2-preflight.txt`. Preserve F1 source/QA/CI evidence unchanged. No baseline suite rerun. Ensure the F2 plan file is copied verbatim into the approved B1 artifact directory before coding, recording its actual SHA-256/blob in the report; do not claim a hash until computed from the actual copied bytes.

### P1. Invariant worksheet and red-first tests

Write the worksheet from §2 and test-case expectations from §§5–7. First add narrowly failing targeted tests where feasible: one pre-publication cancellation for each of four branches, field-stage real claim, error/panic after reservations and full projections/MultiOne value. Record **actual red output** only when a test genuinely ran against the old F1 source; a compile error due to a not-yet-created F2 test hook is *not* a valid red proof. Do not weaken assertions to make a red phase convenient.

### P2. Implement the small cancellation/RAII source correction

Implement §§3–4, including `f2_probe` and the test-only waiter witness. Preserve public/protected code and existing `MetadataBudget`/`MetadataMeter` ownership. Ensure none of the test-only actions is called with the cache mutex held.

### P3. Complete deterministic G12/G14 acceptance

Implement §5 using true registry and field claims, typed injected error and panic, cancellation at the pre-publication boundary, budget release, same-snapshot retry, and observed waiter wake. Run these targeted commands to green:

```sh
cargo +1.98.1 test -p quervant-core --lib b1_g12 -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b1_g14 -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b1_g13 -- --test-threads=1
```

Also run the targeted registry scan test by its new exact `b1_g12_f2_...` or similarly named prefix. Do not introduce arbitrary sleep timing as an assertion threshold. If failure/hang occurs, record the exact phase and source; apply §10, not a repeated-test-until-green strategy.

### P4. Complete U10/I04/R01 full-value oracles

Implement §§6–7. Run:

```sh
cargo +1.98.1 test -p quervant-core --lib b1_u10 -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals -- --test-threads=1 --nocapture
```

Require actual full I04 parent completion and `PERF06_B1_I04_CHILD_PASS` in recorded output. Confirm both child entrypoints are actually launched by their parents; an ignored child entry in the test list alone is not proof. Preserve the historical fixtures byte-for-byte. For R01, rely on the next ordinary hosted CI run on final F2 source; do not rerun all RustFS infrastructure locally.

### P5. Consolidated final local QA after the **last** executable/test edit

Run the required B1 ledger from frozen plan §17.1 **once on the final executable source**. These commands are applicable because F2 changes production code and correctness tests; previous F1 QA is preserved as historical evidence, **not** reused as F2 pass. No baseline `main` suite and no extra profiling/benchmark run. Keep commands, toolchains, exit codes, test counts, coverage and source SHA in `evidence/f2-qa-ledger.txt` and `f2-*.log` (redact credentials, keep logs reasonably sized):

```bash
cargo +1.98.1 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
git diff --check
```

Apply `set -o pipefail` to commands piped through `tee`. Enforce both line coverages ≥85%, no exclusions or ignored-test additions. If one command fails on F2 code, fix only within allowlist, then rerun targeted failures and every final gate invalidated by subsequent executable/test edits. A later report-only change requires source-object equivalence and `git diff --check`, **not** another full QA battery. Do not assume counts from F1.

### P6. Package an additive report and push the existing PR once

Append **`# F2 independent-review closure`** to `docs/pr-artifacts/perf-06-b/PERF06B1_EXECUTION_REPORT.md`. Identify the earlier G12/G14 and projection assertions as superseded and include the F2 matrix/proofs; do not delete previous recorded findings. Record: base, F1 tested source, F2 start/tested/final SHA; exact changed-file inventory; source/test/CI equivalence proof for doc-only commits; test commands and executions; F2-I01–I10 trace; open residual risks; terminal or pending CI; explicit G10 still open.

Create a single normal implementation/report commit, fast-forward push to `origin/dev/perf06-b1`, and let the ordinary PR workflow start automatically. No manual `workflow_dispatch`, CI cancellation, forced rerun, or repeated evidence-only push is authorized. When all jobs finish, **prefer updating PR body with their run ID/status without pushing a second documentation-only commit**. If service remains pending/unavailable, report this honestly; do not hold independent work idle or call G8 PASS. Actual final source remains immutable while CI is checked.

### P7. Hosted CI and independent handoff

Inspect the ordinary workflow associated with the F2 code-bearing PR head. Require actual success of `rust`, `msrv`, `rustfs`, `python-benchmark-framework`, `benchmark-adapter-contract`, plus B1-R01 test execution in the `rustfs` log. The compiled checkout may be a GitHub synthetic PR merge commit; record actual checkout SHA and parents and establish source-tree equivalence to tested code before attributing results. Do not present the head SHA as the literal CI checkout SHA unless verified.

**Completion categories:**

- `PERF06_B1_F2_READY_FOR_INDEPENDENT_REVIEW` only if G0–G9 pass on the final code, including real R01 and CI, with G10 OPEN.
- `PERF06_B1_F2_IMPLEMENTED_VERIFICATION_BLOCKED` if code is complete but CI/R01/mandatory evidence is still pending or unavailable.
- `PERF06_B1_F2_HARD_STOP_AMENDMENT_REQUIRED` if a safety/API/contract contradiction prevents the fixed behavior. Do not self-approve or merge.

## 9. Exact allowed paths and protected-scope checks

**Existing production path (one):** `crates/quervant-core/src/index/keyword_ordinals.rs` — last publication polls, schema-scan polls, scoped F2 test seams, G12/G14 tests.  
**Existing test files (four):** `crates/quervant-core/src/segment/column.rs` — existing U10 test module only; `crates/quervant-core/tests/perf06_b1_common/mod.rs` — one expected-projection helper; `crates/quervant-core/tests/perf06_b1_ordinals.rs` — full projection checks in existing I04/helper; `crates/quervant-core/tests/perf06_b1_rustfs.rs` — existing R01 full projected values.  
**Documentation:** copied `docs/pr-artifacts/perf-06-b/PERF06B1_F2_DETAILED_FIXUP_PLAN.md`, additive `docs/pr-artifacts/perf-06-b/PERF06B1_EXECUTION_REPORT.md`, and new `docs/pr-artifacts/perf-06-b/evidence/f2-*` only.

Everything else is **protected**, including `crates/quervant-core/src/segment/column.rs` **production** portions, `src/segment/metadata.rs`, `segment/reader.rs`, `format.rs`, `build.rs`, `index/merge.rs`, `snapshot.rs`, `index/mod.rs`, production query/sort/score/mutation, storage/remote/objectstore, `.github/workflows/ci.yml`, Cargo/dependencies/toolchains, any authoritative benchmark config/result, frozen B1 fixture package, original/F1 plan and all earlier B1 evidence. Ensure diff against **`1b9621e2d089f7658e5749a8ad73e3153d1b2045`** contains only the allowed code/test/report additions and preserved previously added evidence; verify the protected-path diff is empty. Do not remove preexisting files or clean the worktree broadly.

No test-only fault hook may leak into production builds; use `#[cfg(test)]` guards and a no-op production stub for code calls only. Do not change public `KeywordOrdinalPreparation`, `SnapshotKeywordOrdinals`, `SegmentOrdinalMap` or column reader APIs. No `unsafe`, no dependency, no new feature switch.

## 10. Preauthorized architectural decisions and exception-handling matrix

Evaluate each row by its **observable trigger** before acting. Every row's owner is **agent** for narrowly specified AUTO actions; **maintainer** for new choices/acceptance, **infrastructure** for external blockers. Higher severity takes precedence. **Any unlisted condition is HARD STOP for affected work**, even when a general planning heuristic might permit improvisation. Each rule must be logged with observed trigger, action, evidence path and resulting gate.

| ID | Observable trigger | Category | Preauthorized action / fallback | Explicit prohibition | Evidence / gate / owner |
|---|---|---|---|---|---|
| X01 | Clean fast-forward at exact expected reviewed F1 source or docs-only descendants | AUTO-RESOLVE | Pin new head; preserve all earlier evidence; proceed | Reset/rebase/force, baseline rerun | `f2-preflight`, G0; agent |
| X02 | Local worktree dirty or PR branch diverges from origin | HARD STOP | Preserve state and list changed files | Stash/clean/overwrite | Status/diff; G0; maintainer |
| X03 | F2 source head has intervening non-docs edit to a protected/test file | HARD STOP | Report exact blob/diff; continue unrelated read-only plan analysis only | Overwrite or silently reconcile | Compare; G0; maintainer |
| X04 | New main SHA no longer equals accepted A6 base, or PR base differs | HARD STOP | Preserve branch and report actual ancestry | Silent rebase/change base | Git ancestry; G0; maintainer |
| X05 | F1 source tests and original plan hashes match recorded values | AUTO-RESOLVE | Reuse verified F1 assets; implement only remaining delta | Rebuild/redesign codec or data model | Hash report; G0/G1; agent |
| X06 | Registry candidate Ready and not cancelled at prepublish poll | AUTO-RESOLVE | Existing Ready publication and continue | Move `poll` under mutex | G12/identity; G3; agent |
| X07 | Registry optional candidate and not cancelled | AUTO-RESOLVE | Publish original sticky NotAvailable | Treat `Allocation` as fatal codec corruption | G12; G3; agent |
| X08 | Field candidate Ready and not cancelled | AUTO-RESOLVE | Publish Arc map after poll, disarm, notify, postpoll | New cache or extra publication lock | G12/G19; G3; agent |
| X09 | Field optional candidate and not cancelled | AUTO-RESOLVE | Publish original sticky optional outcome | Silent retry/change budget | G12; G3; agent |
| X10 | Any candidate cancelled at required prepublish poll | AUTO-RESOLVE | `Cancelled`; existing RAII resets claim, wakes; candidate drops | Publish then pretend state reset | G12; G3/G4; agent |
| X11 | Cancellation is observed only after publication's final pre-lock check | AUTO-RESOLVE | Preserve existing postpublish poll and published value | Retract already-published map or claim atomic race semantics | Test/report; G3; agent |
| X12 | Registry field list reaches index 0/256/512/... | AUTO-RESOLVE | Poll outside mutex at count and fill loops | Global scan cache, new bound | Scan test; G3/G4; agent |
| X13 | Schema/guard limits make requested 257-field fixture genuinely illegal | DEFER AND CONTINUE | Mark scan-specific test BLOCKED with exact bound; complete other F2 work; request narrow test-design amendment | Raise limits, silently reduce test, G4 PASS | Error/limit; G4; maintainer |
| X14 | Test-only one-shot hook matches a declared `F2Probe` | AUTO-RESOLVE | Invoke outside mutex; propagate typed error/panic in test; clear hook | Production observable fault behavior | G14 test; G4; agent |
| X15 | Injection site is unexpectedly inside cache mutex | HARD STOP | Do not install callback there; report exact lock scope | Invoke arbitrary test closure while locked | Source witness; G3; maintainer |
| X16 | Actual field is `Empty` under a test-only populated registry | AUTO-RESOLVE | Call same production `prepare` to claim `Building` | Use fresh Uninitialized registry to claim field | Test state logs; G14; agent |
| X17 | Typed injected error or panic after admission | AUTO-RESOLVE | Assert RAII reset, budget return, same-snapshot retry, wake; use catch_unwind **in tests** | Make error sticky; catch panic in production | G14; G3/G4; agent |
| X18 | Actual waiter has not entered `wait_timeout` before builder release | HARD STOP affected witness | Fail deterministic test and record witness; continue independent tests | Sleep/retry until green or claim wake proof | Wait observer; G4; agent/maintainer |
| X19 | Candidate full oracle returns wrong projection or row state | AUTO-RESOLVE if test-only expectation typo demonstrably contradicts frozen ROWS | Fix exact **test-only** oracle to frozen literal | Change production data/query, accept six-field count alone | Input-vs-output; G5/G6; agent |
| X20 | Frozen ROWS/append expectations and actual query result disagree with no oracle typo | HARD STOP | Preserve input/result; stop affected lifecycle acceptance | Normalize semantics or suppress assertion | Test output; G5/G6; maintainer |
| X21 | U10 MultiOne list has length 1 but wrong value | HARD STOP acceptance (feature bug) | Record mismatch; no automatic codec change in F2 | Treat length as sufficient, edit production codec | U10 counterexample; G4; maintainer |
| X22 | CI hosted real RustFS passes on F2 source | AUTO-RESOLVE | Record exact run/test/source; close G6/G8 | Rely on old F1 CI alone | Actions/test log; G6/G8; agent |
| X23 | CI/service pending or unavailable | DEFER AND CONTINUE | Finish independent local/report work; leave G6/G8 BLOCKED/PENDING | Start unrelated service, fake green, merge | Error/run status; infrastructure |
| X24 | Any new architecture decision, unexpected interface incompatibility or unlisted condition | HARD STOP | Report source, alternatives, narrow needed approval; independent tasks only | Improvise new API/seam/format | Decision register; maintainer |
| X25 | Targeted test reveals introduced F2 bug within exact authorized algorithm | AUTO-RESOLVE | Correct the bounded defect and rerun affected tests/final invalidated gates | Remove assertions, alter limits, ignore tests | Red/fix/green logs; agent |
| X26 | QA gate failure claimed preexisting/flaky without baseline evidence | HARD STOP acceptance | Classify introduced/pre-existing/flaky/environment; allow only smallest needed baseline reproduction | Claim unrelated, rerun until favorable | Error + classification; G7; maintainer |
| X27 | Doc/evidence-only commit after final QA | AUTO-RESOLVE | Prove executable/test/CI blobs identical, `git diff --check`; reuse code QA | Rerun full suites for prose | Commit tree diff; G7/G9; agent |
| X28 | Change would touch protected path, RustFS publication, benchmark or public API | HARD STOP | Preserve branch and request amendment | Scope expansion | Changed-path review; maintainer |
| X29 | Test output reports zero tests, child not executed or only fake store | HARD STOP gate | Mark NOT RUN/BLOCKED and preserve evidence | Convert compile/existence into PASS | Exact logs; G4/G5/G6; agent |
| X30 | Host idle/stability observation absent or unfavorable | AUTO-RESOLVE | Record informational/NOT OBSERVED and continue | Use as correctness stop, retune or rerun | Advisory only; agent |
| X31 | All G0–G9 actual gates pass and branch source verified | AUTO-RESOLVE | Report READY_FOR_INDEPENDENT_REVIEW and request independent acceptance | Self-merge/self-approve/start B2 | G0–G10 ledger; maintainer |
| X32 | Mandatory gate remains incomplete for unrelated external condition | DEFER AND CONTINUE | Record exact blocked gate; do every independent safe task | Upgrade incomplete to PASS | Report; owner as relevant |

## 11. Failure classification and final evidence package

Record each mandatory gate as `EXISTS`, `EXECUTED`, and `PASSED` separately. Classify failures as: introduced F2 regression; underlying B1 defect newly exposed; deterministic pre-existing failure (**requires comparative evidence**); nondeterministic/flaky (**requires actual nondeterministic evidence**); or environment/harness failure. Do not use "unrelated" as a classification. Retain failures immutably and never overwrite a negative log with a later green run.

Required F2 execution-report addendum:

1. The authoritative F2 start SHA, accepted main, reviewed F1 SHA, plan SHA-256/blob, actual tested and final Git commit identities, and source-tree equivalence for any report-only commit.
2. A scope table listing each changed path and a negative protected-path diff.
3. F2-I01–I10 invariant-to-source-to-test-to-command/log trace, including the four publication outcomes and same-snapshot cancellation/error/panic tests.
4. Actual test **results**, not names only: candidate-ready/cancelled/optional states, registry/field RAII states, pre- and post-charge figures, actual blocked waiter, same-snapshot retry, U10 exact one-element string and its negative assertion.
5. I04 g3/g4/g5 + child result and R01 g3/g4 real service result; every selected hit's six ordered projected fields must equal literal expected values; old immutable-object and held-PIT proofs remain intact.
6. Final local ledger commands/exits/counts, toolchains, line coverage and source identity; no excluded test/coverage path.
7. CI workflow run ID, event, actual checkout/parent, source equivalence and all five job statuses, with explicit `b1_r01_cold_shared_ordinals_and_pit ... ok` if passed; no assertion that an unobserved job is green.
8. Applied X-rule IDs, blockers, negative cases, remaining known residuals, G0–G9 status and **G10 OPEN**; no performance claim or B2 authorization.

## 12. Independent reviewer checklist / acceptance

- [ ] PR #126 remains open and on the correct branch/base; no accidental state change or force push.
- [ ] Current accepted main and F1 baseline are pinned; older F1 report remains historical, with an additive F2 correction.
- [ ] Ready and optional **registry** transitions poll cancellation before locking/publication; pre-cancel resets `Initializing`.
- [ ] Ready and optional **field** transitions poll before locking/publication; pre-cancel resets `Building` and releases the candidate.
- [ ] Existing post-publication semantics retained, with no cancellation checks under mutex.
- [ ] Schema eligibility count/entry fill polls every 256; cancellation during scan verified.
- [ ] A test-only probe after actually charged registry/field allocations injects typed error **and** panic; after each, budget and state reset; same snapshot retries successfully.
- [ ] Real waiter entered the wait and was awakened by RAII failure, in registry **and** field case; no timing assumptions or production callbacks under lock.
- [ ] U10 checks the entire MultiOne contained string for all fixed 64 cases; wrong-string negative oracle fails equality.
- [ ] I04 legacy g3, mixed g4, compacted g5 and child assert every hit's six-field **value** projection (not count).
- [ ] R01 asserts all 18/19 hit projections for both sorts/missing placements/K guards, real five-object immutability and two g4 cold opens.
- [ ] No change to B1 format, public API, immutable fixture, segment metadata budget implementation, query production code, storage, CI workflow or benchmarks.
- [ ] All applicable final QA checks passed on code under review, coverage ≥85%, genuine hosted RustFS R01 actually executed; CI source/checkout proven.
- [ ] G10 remains maintainer-only; B2/B3/B4 untouched; prior A6 measurements unaffected.

**Final coding-agent instruction:** Execute this plan, not a redesign. If and only if every source, correctness, local QA, real-provider and hosted CI gate passes, deliver `PERF06_B1_F2_READY_FOR_INDEPENDENT_REVIEW`; otherwise preserve exact blocked/failed status and stop the affected work. **Do not merge PR #126 or begin PERF-06-B2.**
