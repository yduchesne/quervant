# PERF-06-B3-F1 — Matched-query corruption, failing-builder waiter recovery, and ExactSet acceptance

**Execution contract / revision 1 — 2026-11-25.** Repository: `yduchesne/quervant`. Continue the **existing draft PR #128**, branch `dev/perf06-b3`, base `main`; do not create a replacement PR or start B4. This is a **narrow acceptance-evidence fixup**, not a new optimization. The implementer is a low-reasoning coding agent: follow these decisions literally; do not design an alternative.

**Pinned reviewed source:** post-B2 `main` `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2`; B3 implementation/test SHA `aa5c4497bb2a1fcc99a6ab9d9731db86ef7a4479`; reviewed terminal PR head `76609e8348e4502b4e835d13d7a7facea13bffc1` (documentation/evidence-only delta from `aa5c4497`). Verify the *actual* remote head and current `main` before editing. Source may have advanced; follow matrix R01–R05, not a guessed rebase. PR URL: <https://github.com/yduchesne/quervant/pull/128>.

**Authoritative sources:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` (especially §§2, 3A–3F, 3E, 27, 37–38), `docs/ARCHITECTURE.md`, `docs/TESTING.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/pr-artifacts/perf-06-b/PERF06B3_EXECUTION_REPORT.md`, the accepted B2 source and its F1 test evidence. This fixup changes only the acceptance gaps described in the independent review, preserving completed B3 behavior and recorded negative evidence.

> **Continuous execution authorization:** Once execution of this plan is authorized, execute all prescribed stages without asking for routine reconfirmation after preflight, a test pass, a phase completion, an AUTO-RESOLVE decision or an evidence checkpoint. `AUTO-RESOLVE` means perform the specified action and continue. `DEFER AND CONTINUE` means record the blocked dependent gate and continue all independent safe work. `HARD STOP` means stop affected work immediately; if isolation is not safe, stop the whole task. Only the maintainer may approve any unanticipated semantic choice, scope expansion, gate waiver, re-architecture, merge, release, or benchmark acquisition. A condition not matched by an exact preauthorized matrix row is **HARD STOP R40**, never an invitation to improvise.

## 0. Disposition and ownership

- Target agent disposition: **`PERF06_B3_F1_READY_FOR_INDEPENDENT_REVIEW`**, only after G0–G9 are evidenced as PASS. G10 (independent acceptance and merge) **always stays OPEN** for the coding agent.
- If source changes are implemented but required verification is unavailable, report **`PERF06_B3_F1_IMPLEMENTED_VERIFICATION_BLOCKED`** with exact gates/reasons; never claim ready.
- If a required source/API condition cannot be met inside this allowlist, report **`PERF06_B3_F1_STOP_DESIGN_DECISION_REQUIRED`** with path, line, counterexample and smallest proposed amendment; make no unauthorized choice.
- Leave PR #128 **draft and unmerged**. Do not force-push, squash historical evidence, erase negative tests, rewrite committed objects or approve B3 yourself.
- **No warm/cold measurements, profiler, Criterion, cross-engine comparison, BM-10 acquisition, B4, new RustFS service or benchmark tuning.** Compilation-only `cargo bench --no-run` remains an ordinary QA check.

## 1. Source admission and frozen status reconciliation (G0)

Run from the existing checkout after `git fetch origin` (safe read-only fetch, no branch switches that discard user work):

```sh
set -euo pipefail
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git log -5 --oneline --decorate
# Authenticate where available; record the actual JSON result and current state.
gh pr view 128 --repo yduchesne/quervant --json number,state,isDraft,mergedAt,baseRefName,headRefName,headRefOid,url
# The known post-B2 main is the implementation baseline, not permission to reset it.
git merge-base --is-ancestor ce7dea12c0f8f84fdc3a80306083e38c8df30ce2 origin/main
# At the reviewed head, this must show only docs/evidence:
git diff --name-status aa5c4497bb2a1fcc99a6ab9d9731db86ef7a4479 76609e8348e4502b4e835d13d7a7facea13bffc1 -- crates/ .github/ benchmarks/ Cargo.toml Cargo.lock
```

Expected starting source: `search/unified.rs` contains `CompactHashAudit`, `KeyBinder`, `consider_compact_ordinal_candidate`, `d3c::State::check_compact`, `ReaderSnapshot::for_test` exists **under `#[cfg(test)]`**, and `reader.rs` contains `KeyFingerprintCache`, `KeyFingerprintBuildGuard`, `B3Probe::AfterHashAllocation`, and `bind_key_identity`. The existing integration test `b3_i08_resource_limits_and_exact_set_fallback` uses K=18 below the configured ExactSet threshold 32; `b3_u09_mode_gating_and_ineligible_shapes` contains a tautological result assertion. None of these are permission to refactor the underlying algorithm.

**Verified work to preserve:** accepted B1/B2 codec and ordinal maps, B3's 4-state fingerprint cache and retained-metadata accounting, shared hash/offset representation, original Linear/Prefilter/ExactSet duplicate semantics, owned-key/sort fallback, score bits, K+1 heap, cursor and PIT interfaces, all 19 B3 unit/adversarial + 8 B3 integration tests, hosted RustFS checks, existing green 2,697/2,742 test results and ~93% coverage **as historic B3 evidence only**. Those results do **not** prove the missing F1 assertions.

**Remaining delta, classified:**

| Finding | Implemented behavior | Remaining correction |
|---|---|---|
| F1-01 (P2): matching search over corrupt DOC_KEYS | Reader error and fallback tested directly; original pristine query tested | **New actual `UnifiedSearcher` test** on a checksum-valid corrupt `ReaderSnapshot`, with matched/error and zero-match/success paths |
| F1-02 (P2): failing builder wakes blocked waiter | Error/panic reset test and successful-builder concurrent test pass | Deterministic **blocked waiter behind error and behind unwind**, scoped wait/RAII-notify witnesses, resource release, poisoned mutex typed-error test |
| F1-03 (P3): ExactSet integration | K=18 with configured threshold=32 resolves Linear | Change B3-I08 to **K=32**, validate complete expected result, and prove resolved policy at the unit seam |
| F1-04 (P3): test assertions | U09 asserts `is_ok() || is_err()` and U21 observes an unscoped global wait count | Replace tautology with exact result assertions; make U21 wait observation **state-local** and race-safe |

Do not reimplement any DONE+VERIFIED B3 component. Capture `git diff --check` and exact changed-file inventory before and after. An existing foreign/untracked file, including the previously reported `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt`, is **not** task-owned: record and leave it untouched (R04). A tracked edit not authored by this task and not reconcilable with these exact sources is a HARD STOP.

## 2. Pre-implementation correctness worksheet (G1)

Before production/test edits, append the following exact invariant IDs to a new `# B3-F1 independent-review fixup` section of `docs/pr-artifacts/perf-06-b/PERF06B3_EXECUTION_REPORT.md`. For each, record source anchor, negative counterexample, test name, gate, and whether the test already exists. Do not erase the original report.

| Invariant | Required observable behavior | Plausible incorrect result | New proof |
|---|---|---|---|
| **F1-I01** | Valid checksum/version/section envelope with invalid unselected DOC_KEYS UTF-8 produces authoritative typed error on a query with a match | `bind_key_identity` returns optional None then search silently succeeds / returns partial hits | `b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key` |
| **F1-I02** | A zero-match query against that same snapshot succeeds without key resolution; a subsequent match still reports the corruption | Eager key work makes zero-hit fail; failure poisons unrelated queries | Same U01 test, explicit zero-match first and repeated matched-failure arm |
| **F1-I03** | A builder that returns a typed error **after allocating** drops its reservation, resets `Building→Empty`, notifies a **known blocked waiter**; that waiter succeeds on same verified state | Error resets without notification, leaves waiter or budget stranded | `b3_f1_u02_error_wakes_actual_waiter_and_retries` |
| **F1-I04** | A builder panicking after allocation has the same RAII cleanup/waiter recovery, without poisoning the cache mutex | Panic strands `Building`, deadlocks waiter, or leaks metadata | `b3_f1_u03_panic_wakes_actual_waiter_and_retries` |
| **F1-I05** | Deliberately poisoned fingerprint mutex returns exact typed Corrupt; does not become optional `Unavailable` or unwind at caller | `.unwrap()` panic, ignored poison, silent owned fallback | `b3_f1_u04_poisoned_fingerprint_lock_is_typed` |
| **F1-I06** | Wait-entry witness belongs to the **specific cache** under test, not a process-global counter reused by parallel tests | Earlier unrelated wait causes premature builder release | Updated B3-U21 and new U02/U03 |
| **F1-I07** | `TopK=32` with ExactSet threshold 32 selects resolved ExactSet, uses original owned B2 path, returns all 18 correct rows | K=18 accidentally tests Linear and passes | Corrected B3-I08 + exact resolved-mode unit assertion |
| **F1-I08** | Two-field sort is ineligible for B3, and returns exact expected keys/score bits/projection, not an always-true assertion | A sort failure hidden by `Ok || Err` | Corrected B3-U09 |
| **F1-I09** | No change to persisted data, original cache transition semantics, key hashing, B2 ranking, duplicate policy, or cursor; only specified test-only witness | New cache, altered policy, new index bytes, extra production metric | Source allowlist + B1/B2/B3 regressions, protected diff and CI |

**Required challenge before code:** record how the corrupt document-key body is rebuilt under a *valid* `ContainerBuilder` envelope; how the malformed key can remain **unselected yet validated** by the original full key scan; why the test-only `ReaderSnapshot` can open the segment without mutating a committed index; why the waiter cannot be released before its state-local wait-entry observation; and how budget zero-after-drop proves no leaked reservations. If any explanation contradicts current source, HARD STOP R14; do not manufacture a result.

## 3. Frozen implementation boundaries and impact matrix

| File/component | Authorized delta | Protected behavior |
|---|---|---|
| `crates/quervant-core/src/search/unified.rs` | Add **unit test U01** inside existing `#[cfg(test)] mod b3_tests`; strengthen existing `b3_u09` and resolved-mode assertion | Do not alter `UnifiedSearcher`, handlers, `d3c`, `KeyBinder`, comparator, costs, validation or `MixedEntry` production semantics |
| `crates/quervant-core/src/segment/reader.rs` | Add **two `#[cfg(test)]` per-cache counters** and increment sites; add **U02/U03/U04**, strengthen U21 | Do not change cache-state transitions, poll cadence, `notify_all`, public reader methods, metadata allowance, DOC_KEYS parsing, fingerprints or error mapping |
| `crates/quervant-core/tests/perf06_b3_keys.rs` | Correct **I08** K=32 ExactSet and strengthen expected result/projection; preserve I07 real boundary proof | No fixture regeneration, changed schema, writer, file format or added RustFS test |
| `docs/pr-artifacts/perf-06-b/PERF06B3_EXECUTION_REPORT.md` | Append F1 worksheet, red/green evidence, exact source identities, gate results, decision/STOP ledger | Preserve original B3 evidence, historic 15H-C/15I-D1-F rejected outcomes and G10 OPEN |
| `docs/pr-artifacts/perf-06-b/PERF06B3_F1_DETAILED_FIXUP_PLAN.md` | Commit **verbatim** copy of this authorized plan | Do not rewrite architecture or decision rules |
| `docs/pr-artifacts/perf-06-b/evidence/b3-f1-*` | New sanitized logs/evidence only | Existing B1/B2/B3 evidence immutable |

**Explicitly protected:** `index/**`, `segment/column.rs`, `segment/format.rs`, storage/objectstore/remote, `search/execute.rs`, `search/typed_compare.rs`, `search/limits.rs`, public contract and schema, Cargo/dependency/toolchain files, `.github/**`, `benchmarks/**`, B1/B2 fixture trees, all existing integration tests besides the single I08 change, `AGENTS.md`, `TESTING.md`, and the authoring guide. If an essential source change is outside these files, stop R35 rather than widen the allowlist. No unsafe code, extra metadata cache, new helper production API, or new performance diagnostic.

### Failure-mode and independence contracts

- **Corrupt segment:** the test creates a new immutable container whose inner `DOC_KEYS` payload is corrupt but outer checksum/features/sections are valid. The library reader opens lazily; matching search must yield the established `SearchError::Segment(SegmentError::InvalidUtf8 { context: "doc key" })`; no partial response or `NotAvailable` masquerading as success. A zero-hit query must succeed. Existing public committed-length validation remains untouched.
- **Error/panic:** the builder's already-allocated vector is released by `MetadataMeter` RAII, its guard restores `Building→Empty`, and `notify_all` is executed. The waiter observed in the same cache can claim a retry; one Ready owner remains. Other snapshots/caches are independent.
- **Poison:** poisoning the mutex intentionally is a **permanent typed failure** for that cache, not a retryable build failure. Do not call the normal cache-ready state accessor if it requires `Mutex::lock().unwrap()` on the poisoned lock.
- **Resource exhaustion:** no cap adjustment, special warning suppression or modified candidate accounting. Budget-after-drop must return to zero in isolated unit fixtures.
- **Concurrency:** `Duration::from_millis(5)` remains the production wait *poll cadence*, not a timeout error. Do not use timing sleeps as race control. Use channels and a per-cache wait-start counter. Failure notification plus actual waiter recovery are required; do not assert a wake-up was uniquely caused by notification if the timed waiter could also wake by cadence.
- **Not applicable:** this fixup introduces no network I/O, new persisted mutation, index-format migration, durable recovery or crash injection. Existing CI RustFS is regression evidence only.

## 4. F1-01: actual matching query on a checksum-valid corrupt snapshot (G2/G4)

**Only source file:** `crates/quervant-core/src/search/unified.rs`, append one new test inside **existing** `#[cfg(test)] mod b3_tests`. No production search or reader source changes are allowed for this finding. Name the test exactly:

```text
b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key
```

### 4.1 Construct the valid source segment without changing the public index

Use existing `b3_tests::{schema,document,term,request,sort_field,run_with,directory,large_limits}` and `Index`/`AnalyzerRegistry::builtin`. Create a **two-document, single-segment** real `MemoryDirectory` index through `Index::writer`, commit, reopen, and take its immutable snapshot. Do **not** use the B3 `build_segments` helper unchanged because it puts `grp=common` on both documents; we need the corrupt physical row to be **nonmatching**.

| Physical doc ID (assert using `doc_keys()`) | Key | `grp` | `doc_id` | Query `term()` matches? |
|---|---|---|---|---|
| `0` | `k0` | `common` | `a` | YES |
| `1` | `k1` | `other` | `b` | NO |

Construct the second document as `let mut other = document("k1", City::Value("b")); other.insert("grp", FieldValues::Single(FieldValue::Keyword("other".to_owned())))?;`, then insert normally. For both rows, use the existing `document` helper, not a new schema. Assert exactly one segment and physical `doc_keys()==["k0","k1"]`. On the pristine snapshot, `run_with(snapshot,&request(term(),1,sort_field(Asc,Last)),SearchLimits::default(),TopKDuplicateConfig::default())` must succeed with `total_hits=1`, key `k0` and the expected projection. This verifies a legitimate positive match exists.

### 4.2 Rebuild a *different*, checksum-valid container with one corrupt unselected key

Read the original immutable segment bytes from `snapshot.segments()[0].bytes()` and parse using `crate::segment::parse_container`. Clone the entire section table with **original section kinds, flags, aux, bodies, and required/optional features** exactly as in the already accepted `perf06_b3_keys.rs::b3_i07_corrupt_doc_keys_is_authoritative` test.

Operate **only** on the cloned `SectionKind::DocKeys` body. The `DOC_KEYS` body is `u16 version + u64 count + repeated (u16 byte-length + UTF-8 bytes)`. Locate the unique literal payload `b"k1"` *inside that DOC_KEYS body*: assert exactly one `windows(2)` hit and that it is the second key payload (not its framing). Replace **only** the first payload byte of that hit with `0xff`. Do not alter the length prefix, record count, live bitmap, postings, sort column or the original byte array. Use the original `ContainerBuilder::new(ContainerKind::Segment, doc_count)`, `require_feature`, `optional_feature`, and `section` methods to reconstruct a complete new container; call `build()` and require success. This recalculates the authoritative outer container framing/digests; **a raw mutated original file is not an acceptable test**.

The rebuilt segment must satisfy `SegmentReader::open(rebuilt.clone(), SegmentLimits::default())` (lazy DOC_KEYS validation), while that reader's `doc_key(0)` must return exactly `SegmentError::InvalidUtf8 { context: "doc key" }` because the full DOC_KEYS decoder checks the **unselected** corrupted key `k1`. Assert the original segment bytes remain byte-for-byte unchanged.

### 4.3 Wrap the rebuilt segment in a real in-memory `ReaderSnapshot` and search

For **this unit test only**, use the existing `#[cfg(test)]` constructor `crate::index::ReaderSnapshot::for_test`; do not introduce another snapshot constructor or modify `index/snapshot.rs`. Build exactly one `SegmentSnapshot` using the **rebuilt** bytes and **updated descriptor**:

```rust
// Illustrative near-copyable constructor; use the source-verified names.
let repaired_meta = crate::index::SegmentMeta::new(
    "b3-f1-corrupt",
    "test/b3-f1-corrupt",
    quervant_objectstore::ContentDescriptor::of(&rebuilt),
    original_view.required_features().to_vec(),
    original_view.optional_features().to_vec(),
    None, // The fixture has no time-bounds query dependency.
);
let corrupt_snapshot = crate::index::ReaderSnapshot::for_test(
    vec![crate::index::SegmentSnapshot::new(
        repaired_meta,
        std::sync::Arc::new(rebuilt),
        original_view.doc_count(),
    )],
    crate::segment::SegmentLimits::default(),
    256 * 1024 * 1024, // reader-copy admission; larger than this fixture
    256 * 1024 * 1024, // metadata admission; does not test cap refusal
);
```

The descriptor is recomputed for the new bytes. Do not reuse the pristine segment's descriptor, forge a committed `CURRENT`, replace the original segment inside a real Index, or bypass reader/container validation. The synthetic `ReaderSnapshot` exists only as an input to the **real `UnifiedSearcher`** in the unit test. Preflight assert that the fixture size fits the stated cap; if not, classify with R15 rather than silently changing the test topology.

**Execution and assertions, in this order:**

1. With the *corrupt snapshot*, search for `Query::Term {field:"grp", value:FieldValue::Keyword("no-such-group")}` and `TopK=1`, `doc_id ASC`. Require `Ok` with `total_hits=0`, empty hits and no cursor. This must happen **before** a matching query so the test proves that no eager key resolution is required for a zero-hit query.
2. On the **same corrupt snapshot**, execute `term()` (the strict single analyzed Keyword term, `TopK=1`, `doc_id ASC`). Require exactly `Err(SearchError::Segment(SegmentError::InvalidUtf8 { context: "doc key" }))`. No `SearchError::Index`, generic `CorruptIndex`, optional `NotAvailable`, partial response or panic is acceptable. The error is expected after the attempted B3 binding fails optional offset admission and the existing owned-key fallback decodes the full keys.
3. Repeat the same matching request on the same corrupt snapshot: same exact typed error. The cache must not turn this into a sticky successful fingerprint directory or silently skip the corrupted physical row.
4. Run semantically equivalent **ineligible** `legacy_term()` (an `And([term()])`) against the corrupt snapshot. Require the same exact typed DOC_KEYS error; this shows the original owned path has the same authoritative outcome.
5. Search the pristine original snapshot again: require success with `total_hits=1`, key `k0` and the same literal `doc_id="a"` projection; original bytes and index generation remain unchanged.

**Oracle:** the literal two-row table, exact `SegmentError` variant/context, and complete zero/positive result—not comparison solely against another B3 output. No external RustFS service. If the synthetic snapshot cannot open the rebuilt container or the accepted source routes the matching error through an incompatible error boundary, STOP R16 with exact source and error rather than changing expected error categories.

**Important:** The existing public integration I07 remains a valid **reader** test and must not be relabeled as collector-level proof. This new lib unit test supplies the actual missing collector evidence, without creating a second committed-file path.

## 5. F1-02: failing-builder waiter, cancellation/RAII and poisoned lock (G3/G4)

**Only source file:** `crates/quervant-core/src/segment/reader.rs`, inside the existing `KeyFingerprintCache` plus existing `#[cfg(test)] mod b3_key_identity_tests`. No normal-build behavior or state transition may change. Continue to use the accepted `B3Probe::AfterHashAllocation` hook, which runs outside the cache mutex after real hash-vector allocation. No new hook, fake build, injected cache state or changed wait duration is authorized.

### 5.1 Add two state-local, test-only `AtomicU64` witnesses

The existing `B3_GLOBAL_WAIT_STARTS` is process-global and therefore unsuitable to sequence a particular cache's test under parallel CI. Add **exactly** these two `#[cfg(test)]` fields to `KeyFingerprintCache`:

```rust
#[cfg(test)]
wait_entries: std::sync::atomic::AtomicU64,
#[cfg(test)]
raii_wake_notifications: std::sync::atomic::AtomicU64,
```

Initialize both to `AtomicU64::new(0)` in `KeyFingerprintCache::new()` under `#[cfg(test)]`.

- In the existing `Next::Wait` branch of `VerifiedSegmentState::ensure_key_fingerprints`, **after** the code has confirmed under the cache lock that the live predicate is still `Building`, and **immediately before** `.wait_timeout(state, KEY_FINGERPRINT_WAIT_INTERVAL)`, add `self.key_fingerprints.wait_entries.fetch_add(1, Ordering::SeqCst)` under `#[cfg(test)]`. Do not remove or otherwise change the original `B3_CACHE_WAIT_STARTS` / `B3_GLOBAL_WAIT_STARTS` counters; they are existing witnesses. No atomic is allocated per waiter or retained in release builds.
- In `KeyFingerprintBuildGuard::drop`, after the armed guard has reset `Building→Empty` and **before** the existing `self.cache.ready.notify_all()`, add `self.cache.raii_wake_notifications.fetch_add(1, Ordering::SeqCst)` under `#[cfg(test)]`. The counter proves the cleanup notification site ran, not that the waiter could never have awoken through its 5-ms polling cadence.
- Use `std::sync::atomic::Ordering::SeqCst` explicitly or import it only under `#[cfg(test)]`. Do **not** alter the existing production lock, `wait_timeout`, `poll_cancel`, `notify_all`, RAII guard disarm logic or cache state machine.
- Read the state-local counters directly inside the already nested `b3_key_identity_tests` module using `state.key_fingerprints.wait_entries.load(Ordering::SeqCst)` and `.raii_wake_notifications.load(...)`. Do not export them as public API or add a production diagnostic endpoint.

**Prove source-level isolation:** a later test cannot alter these counters unless it holds the *same* `Arc<VerifiedSegmentState>`, whereas global counters might have advanced in another parallel test. Test-only increments compile out under normal `cargo build` / benchmark builds.

### 5.2 `b3_f1_u02_error_wakes_actual_waiter_and_retries`

Re-use `column_geometry_tests::admitted_state(bytes_with(400))` to get one genuine `Arc<VerifiedSegmentState>` plus its `Arc<MetadataBudget>`. Do not use an already poisoned or Ready state. Record initial `budget.used()` and `state.key_fingerprints.wait_entries` / `raii_wake_notifications` values. Set the existing **thread-local** probe inside the **builder thread**, not the main test thread:

1. Create `std::sync::mpsc` channels `entered` (builder → main) and `release` (main → builder). Spawn builder thread with a clone of the verified state. Inside it create `SegmentReader::from_shared(builder_state)`; `set_b3_probe(B3Probe::AfterHashAllocation, move || { entered_tx.send(()).expect("signal"); release_rx.recv().expect("release"); Err(SegmentError::Corrupt { context: "doc key identity", detail: "b3-f1-injected-error".to_owned() }) })`. Then call `bind_key_identity(&NeverCancel)`, clear the probe in that same thread, and return only its `Result` **classification**, not a borrowed handle. Require the exact injected typed error.
2. Main thread waits on `entered_rx.recv_timeout(Duration::from_secs(10))`: builder is guaranteed to be post-real-allocation, holding the `Building` claim, with **no cache mutex held during the probe**.
3. Only now spawn a **second thread** with another `SegmentReader::from_shared(Arc::clone(&state))` and call `bind_key_identity(&NeverCancel)`. That waiter must eventually obtain `Some(BoundKeyIdentity)`, check `meta(399).utf8_len == 7`, and return only `true`/a small copied result. It must not export the borrowed handle across thread boundaries.
4. Main thread waits until **this same state's** `wait_entries` has increased by at least 1 above the recorded baseline, using `Instant::now()+Duration::from_secs(10)` and `std::thread::yield_now()`; **only then** send `release_tx.send(())`. Do not substitute a sleep or `B3_GLOBAL_WAIT_STARTS` observation for this state-local guard. Since the waiter increments while holding the mutex before `wait_timeout`, release cannot be observed as a completed cache reset until the waiter releases that mutex, so there is no lost-notify race.
5. Join both threads. Require builder typed error, successful waiter, state `key_fingerprints_state_code()==2` (`Ready`), exactly one successful retained directory in this verified state, and `raii_wake_notifications >= previous+1`. The failed builder's probe is consumed; the waiter retries without a hook.
6. Verify no retained-budget leak: after both threads have exited and all `BoundKeyIdentity`/`SegmentReader` values are dropped, record the final ready-state charge; `drop(state)` and require `budget.used()==0`. The ready owner legitimately keeps a charge **until** the last state/handle drops. Do not assert `budget.used()==0` while the Ready cache remains alive.

A test cannot claim **notification-only wake causality** because the production waiter uses five-millisecond timed polling. What is required is (i) actual state-local wait entry, (ii) observable execution of the RAII notify site, (iii) same-state successful recovery, and (iv) zero final accounting leak. On timeout, fail test with state and counter diagnostics; never silently retry, increase the wait interval or loosen a resource cap.

### 5.3 `b3_f1_u03_panic_wakes_actual_waiter_and_retries`

Use a **fresh** `Arc<VerifiedSegmentState>` from `admitted_state(bytes_with(400))` and the same exact channel / state-local wait-entry protocol as U02, but the builder thread's `AfterHashAllocation` callback is:

```rust
entered_tx.send(()).expect("signal");
release_rx.recv().expect("release");
panic!("b3-f1-injected-post-allocation-panic");
```

In the builder thread, wrap the `reader.bind_key_identity(&NeverCancel)` call with `std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| ...))`; return `result.is_err()`. The panic is **expected**; do not suppress panic test output or change production unwind handling. The main thread must wait until its specific cache's waiter enters, then release the builder, join, and require **panic caught, waiter successful, state Ready after retry, at least one RAII notification, final `budget.used()==0` on last-owner drop**. Do not reuse U02's cache, cancellation flag, global witness or test hooks across tests. A panic during RAII's own lock/drop handling is a failed test, not a permitted outcome.

### 5.4 `b3_f1_u04_poisoned_fingerprint_lock_is_typed`

Create a **third fresh** admitted verified state `state` (do not reuse U02/U03), plus its budget. In a separate thread holding `Arc::clone(&state)`, deliberately poison **only the fingerprint cache mutex**:

```rust
let poison = std::thread::spawn(move || {
    let _held = clone.key_fingerprints.state.lock().expect("initially unpoisoned");
    panic!("b3-f1-intentionally-poison-fingerprint-cache");
});
assert!(poison.join().is_err());
```

The main thread then constructs a `SegmentReader::from_shared(Arc::clone(&state))` and calls `bind_key_identity(&NeverCancel)`. Use `match`, **not** `unwrap_err()` if the success type does not implement `Debug`. Require exactly:

```rust
SegmentError::Corrupt {
    context: "doc key identity",
    detail: "fingerprint cache lock poisoned".to_owned(),
}
```

Require the same typed failure on one repeat bind, **not** `Ok(None)`, not panic and not a cache reset that masks poison. Do not call a test-only state accessor that unwraps a poisoned lock. You may use `state.key_fingerprints.state.is_poisoned()` and `lock().unwrap_err().into_inner()` for **read-only test inspection**; never clear the poisoned flag or mutate internal state. Drop all reader/state holders and assert `budget.used()==0`. This test must not run inside an already unwinding test thread. No changes to `fingerprint_lock_poisoned` or normal error conversion are permitted.

### 5.5 Strengthen existing `b3_u21_concurrent_binders_share_one_owner`

The accepted test currently polls `b3_global_wait_starts() == 0`, which can be satisfied by another parallel test. Replace only its synchronization predicate with the new state-local counter:

```rust
let baseline = state.key_fingerprints.wait_entries.load(Ordering::SeqCst);
// Spawn waiter here, after builder entered AfterHashAllocation probe.
while state.key_fingerprints.wait_entries.load(Ordering::SeqCst) == baseline {
    assert!(Instant::now() < deadline, "no wait entry in this cache");
    std::thread::yield_now();
}
```

Keep channel coordination, one owner identity, one successful build, shared pointer/Ready assertions and the original per-thread wait witness. Because the production waiter can time out and re-enter a 5-ms wait multiple times before the release signal, require `waiter_waits >= 1` instead of `==1`; this change corrects an invalid scheduling assumption and must be documented. Do not reset a process-global atomic, remove existing named counters or change wait cadence. Do not add sleep-based synchronization.

**Failure evidence:** U02/U03/U04 exercise independent sources of failure: typed error outside lock, unwind outside lock, and poisoned lock that is **intentionally not retryable**. Their classifications may not be conflated. Record exact cache state, source SHA, injected probe stage, attempted/actual wait counts, notification witnesses and budget before/after drop. No flaky labeling without deterministic reproduction evidence.

## 6. F1-03/F1-04: ExactSet threshold and non-vacuous ineligible assertions (G4/G5)

### 6.1 Correct `b3_i08_resource_limits_and_exact_set_fallback`

**Only file:** `crates/quervant-core/tests/perf06_b3_keys.rs`; edit the **second half** of the existing I08 test, not its original one-byte candidate-budget error, same-snapshot recovery or subsequent original results.

1. Retain `TopKDuplicateConfig::new(NonZeroUsize::new(32).unwrap(), TopKDuplicateStrategy::ExactSet)` **unchanged**. Do not lower the threshold to 18; the policy threshold is a contract, not a test adjustment.
2. Obtain a fresh `let exact_snapshot = index.snapshot();` **after** the preceding resource-budget test, so the request about to test ExactSet cannot benefit from a B3 fingerprint directory previously built on a different request's snapshot. This test-only fresh snapshot is expressly authorized. Do not call the B3 eligible default on `exact_snapshot` before the ExactSet request.
3. Execute the configured ExactSet request against `exact_snapshot` with **`request(body_term(), 32, sort.clone())`**. K=32 is the exact original mode threshold and the frozen corpus has exactly 18 matching rows. Require `Ok` and all of:
   - `exact.total_hits == 18`; `exact.hits.len() == 18`; `exact.next_cursor.is_none()`;
   - `keys(&exact) == order_for(&corpus_rows(), SortDirection::Asc, MissingValuePosition::Last)` (literal independent 18-key oracle, not another engine response);
   - every hit's full six-field projection equals `expected_projected_fields(hit.key.as_str())` from frozen B1 input data;
   - all returned `score` values are `Some(finite)` and match **bit-for-bit** a separately executed *ineligible* `fallback_query()` request at K=32 on `exact_snapshot`.
4. Execute the **default** duplicate configuration against the same snapshot at K=32; assert `keys`, `total_hits`, score bits, full projections and generation/view ordinal agree with the ExactSet response. The default mode at K=32 is Prefilter (not ExactSet), so it is a differential contract check, not proof of the ExactSet dispatch itself.
5. **Unit-level resolved-mode witness** (next subsection) proves that this exact K/config pair selects ExactSet and does not attempt B3. Do not assert a B3 `pub(crate)` test counter from this integration test; integration and unit test targets cannot share the unit-only counters.
6. Preserve I08's documented limitation that a metadata-only B3 fallback is proved privately, not through a public snapshot. Do not lower `IndexLimits` or `SegmentLimits` to fabricate that topology.

### 6.2 Strengthen existing `b3_u09_mode_gating_and_ineligible_shapes`

**Only file:** `crates/quervant-core/src/search/unified.rs`; update the existing B3 unit test. Keep its previous positive/ineligible examples.

- Use the exact source-resolved helper `d3c::State::production_mode_for_test(32, exact_set_config())` and assert equality to `(d3c::Kind::ExactSet, d3c::Profile::P2)`; add the corresponding `(31, exact_set_config()) == (Kind::Linear, Profile::P0)` threshold counterexample. The existing `b3_u09` K=100 ExactSet behavior remains as an additional positive check. For K=32, execute `run_with` on a **new** B3 test snapshot (or source-backed first-time snapshot) and assert `b3_build_attempts()==0`, `b3_directory_builds()==0` after reset; the result must equal the expected keys and count. The ExactSet request must be first on that snapshot; do not prove lack of building solely from an already cached directory.
- For the existing multi-sort request (`doc_id ASC` then `n ASC` on the three literal rows `k00000/a`, `k00001/b`, `k00002/c`), **replace** the currently vacuous `assert!(error.is_ok() || error.is_err())` with:

```rust
let response = run_with(
    &snapshot, &multi_sort, SearchLimits::default(), TopKDuplicateConfig::default()
).expect("valid two-column sort must succeed");
assert_eq!(response.total_hits, 3);
assert_eq!(keys(&response), vec!["k00000", "k00001", "k00002"]);
assert_eq!(response.hits.len(), 3);
assert!(response.next_cursor.is_none());
assert_eq!(b3_build_attempts(), 0);
```

  Use the existing `keys()` result type's appropriate `Vec<String>` literal construction (the string literals above are a **semantic oracle**, not a mandate to write a mismatched Rust literal type). Also execute the semantically equivalent `legacy_term()` with exactly the same valid two-column `Sort` and TopK; compare keys, total hits, score `to_bits()` and projected `FieldValues`. Reset B3 observations **before** the ineligible request being measured; the reference request runs after the zero-build assertion. There is no B3 map work in this ineligible shape.
- Do not replace one tautology with another (`is_ok() || is_err()`, `!is_empty() || is_empty()`, `.is_err()` without error classification) or remove the test. Retain the existing ineligible cursor, multi-sort and ExactSet regression coverage.

## 7. Exact tests, oracles, and QA protocol

### 7.1 Feature-specific tests — run before final workspace QA

Run from repo root after implementing a test group; record **actual** source SHA, exact command, exit code, number selected/passed/ignored, and log path. Use `set -o pipefail` with `tee` or the shell-equivalent so a failing test cannot become a green log. The following are **feature acceptance** tests (not just broad regression):

```sh
set -o pipefail
# New matched/corrupt collector and ExactSet/multisort unit checks:
cargo +1.98.1 test -p quervant-core --lib search::unified::b3_tests::b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key -- --exact --test-threads=1
# If the actual module name has moved, locate the test with cargo test -- --list,
# use that *exact full name*, and confirm precisely one named test executed.
cargo +1.98.1 test -p quervant-core --lib b3_f1_u02_error_wakes_actual_waiter_and_retries -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b3_f1_u03_panic_wakes_actual_waiter_and_retries -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b3_f1_u04_poisoned_fingerprint_lock_is_typed -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b3_u21_concurrent_binders_share_one_owner -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b3_u09_mode_gating_and_ineligible_shapes -- --test-threads=1
# Real FsDirectory / public request boundary, including corrected K32:
cargo +1.98.1 test -p quervant-core --test perf06_b3_keys b3_i08_resource_limits_and_exact_set_fallback -- --exact --test-threads=1
# If the test harness's full test-name form differs, remove --exact but verify
# that exactly the named test ran. Never treat a zero-test result as PASS.
```

**Red-first discipline:** the revised K32 boundary should expose the old insufficient K18 test; U01/U02/U03/U04 may **pass on existing production** after the new test is added, because the review identified *missing acceptance evidence*, not a proven production bug. Do **not** fabricate a RED result, inject extra production defects, change the implementation to force failure or claim every test was red. Where a genuinely failing test occurs, preserve the RED command/log and the narrow fix. A source-level test-seam compilation failure before the prescribed `#[cfg(test)]` fields are added is an ordinary implementation intermediate, **not** proof of a production correctness defect.

### 7.2 Existing B3/B2/B1 regression tests

After the new tests pass, run at least:

```sh
cargo +1.98.1 test -p quervant-core --lib b3_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b3_keys -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b2_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b1_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals -- --test-threads=1
```

The filters `b3_`, `b2_`, and `b1_` may also match earlier series. Record the actual **named F1 tests** and exact selected counts, not a generic “b3 tests passed.” Existing ignored helper or remote tests are not success evidence unless their parent/CI harness actually executes their body. Do not modify historical fixtures or old acceptance tests to obtain green results. The existing 64-case seeded B3 differential and B2 numeric/parity tests must remain intact and executed.

### 7.3 One final consolidated QA ledger on the frozen source (G7)

Run once **after the last source/test change**. Tests targeting `reader.rs` are test-only in release but still affect all-feature test builds; verify both normal/default and all-feature builds. Exact commands (no new exclusions, no changed minimums):

```sh
set -o pipefail
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
git diff --check origin/main...HEAD
```

Coverage must remain **≥85%** line coverage default and all-features. Record actual numerator/denominator and percentage; prior B3 93.09/92.67% is **not** the F1 result. Preserve existing MSRV 1.85.0 and Rust 1.98.1 without dependencies/toolchain changes. `cargo bench --no-run` is compile-only, **not** authorization to run samples. Do not run full QA again solely because documentation/evidence files were subsequently committed; instead prove `TESTED..FINAL` contains no executable/test/config changes and re-run `git diff --check`.

### 7.4 Existing hosted CI and real RustFS (G6/G8)

Use ordinary `.github/workflows/ci.yml` on the **existing draft PR #128**. Verify five jobs, terminal success on exact tested executable SHA or a head whose `crates/`, `.github/`, `benchmarks/`, `Cargo.*` diff from TESTED is **empty**: `rust`, `msrv`, `rustfs`, `benchmark-adapter-contract`, `python-benchmark-framework`. The hosted `rustfs` job must actually run its existing pinned real test `b1_r01_cold_shared_ordinals_and_pit ... ok`. Local unit/probe tests are **not** substitutes for real RustFS; conversely an unrelated historic RustFS PASS cannot establish new B3-F1 test execution.

Do **not** dispatch an extra CI workflow, cancel jobs, create a service, run a local RustFS instance, cherry-pick unrelated fixes, or treat pending CI as pass. If CI is pending/unavailable, classify R31 and complete independent local/report work; final disposition stays verification-blocked until terminal evidence exists.

### 7.5 Cross-component negative review

Before marking ready, explicitly verify and record these assertions in the F1 report:

- A hash match **never** establishes document identity; exact raw bytes remain authoritative for collision cases. Tests from accepted B3 remain unchanged.
- Neither a corrupt unselected key nor a poisoned metadata lock is downgraded to optional capacity failure in the **tested** path.
- `KeyFingerprintCache` state transitions, timeout cadence and existing RAII cleanup are byte-identical before/after F1 **outside `#[cfg(test)]`-guarded test observations**; no new producer of `DocumentKey` or `SortValue` was added to runtime.
- No change to score computation, effective-live masks, TopK K+1, cursor payload, identical fingerprints, null/missing lexical sort, retained duplicate policy, per-query budgets or B1/B2 metadata.
- All changed files satisfy the allowlist, no B3-B4 timing target was claimed, and G10 remains OPEN.

## 8. Ordered coding-agent procedure (execute without routine checkpoints)

1. **P0 / G0:** Refresh remote refs; reconcile PR #128, current main, source/test blob inventories, old and new evidence. Record preflight in `evidence/b3-f1-preflight.txt`. Branch must remain `dev/perf06-b3`. No destructive workspace action.
2. **P1 / G1:** Append invariant worksheet F1-I01..I09 and literal negative oracles to the B3 execution report before coding; inspect authoring guide and exact source anchors. STOP if an approved semantic contract is contradicted.
3. **P2 / G2:** Add new `b3_f1_u01` **test only** in `unified.rs`; use checksum-valid container reconstruction and `ReaderSnapshot::for_test`. Execute focused test after complete fixture. If green, record positive evidence; if a real defect appears, do not patch production without R16/R35 approval.
4. **P3 / G3:** Add only the two state-local `#[cfg(test)]` counters and increment sites to `reader.rs`; update `b3_u21`; add U02/U03/U04 with independent caches. Run the four targeted tests, verifying cleanup, budget and poison evidence.
5. **P4 / G4/G5:** Change the existing B3-I08 request to K=32 on a fresh snapshot; replace B3-U09 tautology with exact assertions and threshold proof; run both focused tests.
6. **P5 / G4/G5:** Run the complete focused B3-F1 + B1/B2/B3 regression matrix (§7.1–7.2), recording actual named tests and outcomes. Fix only narrowly introduced test/`cfg(test)` wiring bugs under R25; do not weaken an invariant.
7. **P6 / G7:** Freeze last source/test revision, commit it as `TESTED`, and perform the entire one-time QA ledger (§7.3). A correction to executable/test code after this point invalidates affected QA/CI gates, which must be re-executed; do not reuse source-stale evidence.
8. **P7 / G8/G9:** Commit the verbatim F1 plan, append a complete F1 execution report, preserve original evidence and add `evidence/b3-f1-*` logs. Push to the existing draft branch (normal fast-forward only). Observe ordinary CI to terminal state, or mark it pending with exact run/head/job. If only docs/evidence were added after TESTED, prove protected blob diff empty.
9. **P8 / G10:** Final read-only self-audit of all nine invariants and all three concerns; report `PERF06_B3_F1_READY_FOR_INDEPENDENT_REVIEW` only if gates G0–G9 passed. Leave G10 OPEN, PR draft/unmerged, B4 not started. Stop and request maintainer input only for unmatched HARD STOP conditions; no routine step approval.

## 9. Preauthorized Architectural Decisions and Exception-Handling Matrix — binding (40 rules)

Every row is **condition-specific authorization**, not a menu of design alternatives. Record the applicable ID, actual trigger/source check, chosen action, test/log evidence and gate in the append-only F1 report. If two rules apply, use the stricter category. `AUTO-RESOLVE` authorizes the narrow specified step **and continuous execution**; `DEFER AND CONTINUE` records a blocked gate but continues demonstrably independent work; `HARD STOP` halts affected work immediately. Human escalation owner is **maintainer** unless explicitly shown as infrastructure/repository owner. Never infer authorization from an unstated condition. Do not promote a blocked gate.

| ID | Trigger / source check | Category | Required action | Forbidden response | Evidence, gate / owner |
|---|---|---|---|---|---|
| **R01** | PR #128 still open/draft at the verified B3 head and `main` contains accepted B2 | AUTO-RESOLVE | Continue existing `dev/perf06-b3`, fast-forward-only normal push | New PR, merge, forced reset/rebase | G0, recorded PR metadata / agent |
| **R02** | PR or `main` advanced **only** in documentation/evidence, all executable and test blobs unchanged | AUTO-RESOLVE | Reconcile new head and carry forward same source anchors; record blob identities | Overwrite newer docs or assume source changed | G0/G9, diff inventory / agent |
| **R03** | PR head has substantive changes to any reviewed B3 symbol by another contributor | HARD STOP | Report new SHAs, changed paths/semantics, request revised fixup | Apply stale line-level edits or forcibly reset | G0/G1 / maintainer |
| **R04** | Foreign harmless untracked file (including prior `f2-ci-status.txt`) | AUTO-RESOLVE | Record path/hash if useful; leave untouched; continue scoped work | `git clean`, stash/remove foreign evidence | G0 / agent |
| **R05** | Tracked dirty changes not owned by F1, conflicting PR source, or branch identity mismatch | HARD STOP | Preserve worktree, report exact paths/branch; read-only inspection may continue | Stash/discard, force checkout or rebase | G0 / repository owner |
| **R06** | Existing B3 fingerprint/ordinal implementation is present and matches frozen behavior | AUTO-RESOLVE | Preserve production source byte-identically except specified `cfg(test)` fields/increments | Reimplement cache/hash/collector | G1/G9 / agent |
| **R07** | `ReaderSnapshot::for_test` and `SegmentSnapshot::new` available in current library test build | AUTO-RESOLVE | Use them for one synthetic checksum-valid corrupt snapshot (§4) | Add public snapshot API or rewrite committed CURRENT | G2 / agent |
| **R08** | DOC_KEYS body contains exactly one `k1` entry in two-row fixture | AUTO-RESOLVE | Corrupt first byte of its literal payload only, rebuild outer envelope | Corrupt prefix/count, live bits or checksum in place | G2, U01 / agent |
| **R09** | Original container has required/optional features and sections | AUTO-RESOLVE | Copy all feature declarations and sections unchanged except DOC_KEYS bytes via `ContainerBuilder` | Omit features/sections or bypass checksum | G2, U01 / agent |
| **R10** | Rebuilt container opens as a `SegmentReader`; `doc_key(0)` rejects unselected `k1` bytes | AUTO-RESOLVE | Use rebuilt bytes with new `ContentDescriptor::of(&rebuilt)` and `ReaderSnapshot::for_test` | Reuse old descriptor or mutate real index | G2, U01 / agent |
| **R11** | Zero-hit strict-term search on corrupt test snapshot succeeds with no hits | AUTO-RESOLVE | Record zero-match proof before matched query | Initialize/force key directory on zero-hit path | G2, F1-I02 / agent |
| **R12** | Matching strict-term search yields exact `SegmentError::InvalidUtf8 {context:"doc key"}` | AUTO-RESOLVE | Assert precise `SearchError::Segment` wrapping, repeat and check original index | Replace typed assertion with `is_err()` | G2, F1-I01 / agent |
| **R13** | Corrupt unselected-key query returns success, partial hits, different corruption class, or a panic | HARD STOP | Capture trace/source/error; request maintainer decision on newly exposed defect | Change production handler or weaken test without approval | G2 / maintainer |
| **R14** | Original snapshot/offset construction semantics contradict the proposed test design | HARD STOP | Stop corrupt-snapshot work; report precise incompatibility and smallest amendment | Invent private bypass, new raw scanner or fake response | G1/G2 / maintainer |
| **R15** | Rebuilt test segment too large for declared 256 MiB reader/metadata test budgets | HARD STOP affected case | Record size and source; request bounded fixture amendment | Blindly raise production limits or ignore admission | G2 / maintainer |
| **R16** | Rebuilt segment cannot open or error is mapped via unapproved search category | HARD STOP affected case | Preserve actual error and source location; request decision | Modify codec, error contracts or assert generic failure | G2 / maintainer |
| **R17** | Builder post-allocation probe exists and runs without fingerprint-cache lock | AUTO-RESOLVE | Use `B3Probe::AfterHashAllocation` for U02/U03 with channels | Add a new production hook or call callback under mutex | G3 / agent |
| **R18** | Per-cache atomic witnesses can be added under `#[cfg(test)]` | AUTO-RESOLVE | Add only `wait_entries`, `raii_wake_notifications`, initialization/increments (§5.1) | New release atomic, per-candidate counter, different lock | G3 / agent |
| **R19** | Waiter enters specific cache's `Building` predicate wait | AUTO-RESOLVE | Require local `wait_entries` delta before releasing builder channel | Observe process-global counter or use sleep | G3, U02/U03/U21 / agent |
| **R20** | AfterHashAllocation callback returns typed injected error | AUTO-RESOLVE | Builder error, RAII restore+notify, same-cache waiting retry, budget release | Cache injected error as Unavailable or rerun with different data | G3, U02 / agent |
| **R21** | AfterHashAllocation callback panics while cache mutex unlocked | AUTO-RESOLVE | Catch unwind in builder thread, prove RAII restore+notify and waiter recovery | Ignore panic, poison mutex intentionally in same scenario | G3, U03 / agent |
| **R22** | Failed-builder RAII guard reaches its existing notification site | AUTO-RESOLVE | Increment test-only local notification witness and assert delta | Change actual notify/poll cadence or claim exclusive wake cause | G3, U02/U03 / agent |
| **R23** | Waiter poll-cadence causes more than one wait entry before release | AUTO-RESOLVE | Assert `>=1` on state-local/per-thread counters; keep bounded channel/deadline | Require exactly one wait or increase 5 ms cadence | G3, U21 / agent |
| **R24** | Builder failed, waiter retried, Ready owner published | AUTO-RESOLVE | Drop threads/state, assert `budget.used()==0` after final owner | Require zero while Ready state still owns reservation | G3, U02/U03 / agent |
| **R25** | Introduced Rust test compile/lint fault inside newly authorized test-only symbols | AUTO-RESOLVE | Mechanically fix names/lifetimes/`Debug`-bound matches, then rerun invalidated tests | Rewrite prod API, delete assertions or blanket suppress warnings | G3/G7 / agent |
| **R26** | Waiter never actually enters the *same* cache before the 10-s bound | HARD STOP affected case | Preserve channels/state/counter logs and request fixture/source review | Sleep/retry indefinitely, call test flaky without evidence | G3 / maintainer |
| **R27** | Blocked waiter remains stuck, no RAII-notify counter, or budget leak after final drop | HARD STOP | Preserve first failure; report actual production behavior and smallest remedy | Introduce an unapproved concurrency algorithm or ignore evidence | G3 / maintainer |
| **R28** | Fresh deliberately poisoned cache mutex causes exactly the documented `Corrupt` | AUTO-RESOLVE | Assert typed result on two binds; retain poison; drop state and check budget | Clear poison or turn into optional fallback | G3, U04 / agent |
| **R29** | Poisoned-cache bind panics, succeeds or returns optional `None` | HARD STOP | Preserve source and traceback, request maintainer correction | Loosen assertion or silently recover | G3, U04 / maintainer |
| **R30** | ExactSet configured cutoff32 and request K32 with 18 live rows | AUTO-RESOLVE | Execute real I08 ExactSet on fresh snapshot and literal full 18-hit oracle | Lower threshold or treat K18 as ExactSet | G4/G5 / agent |
| **R31** | Ordinary CI pending/unavailable though local tests passed | DEFER AND CONTINUE | Finish report and safe source proof, mark G8 pending with run/head/jobs | Claim CI green, manually restart/cancel workflow | G8 / infrastructure + maintainer |
| **R32** | Existing U09 valid two-column sort returns exact expected keys/count/score bits | AUTO-RESOLVE | Replace tautology with `expect(...)` and literal oracle plus legacy comparison | `is_ok() || is_err()` or `is_err()` alone | G4, U09 / agent |
| **R33** | A valid two-column sort now unexpectedly errors or changes results | HARD STOP affected case | Capture error/plan/source; request maintainer triage | Adjust query/schema or weaken test to accept either | G4 / maintainer |
| **R34** | K32 resolved mode does not equal ExactSet with the unchanged config | HARD STOP | Report `production_mode_for_test` output and policy source | Change `TopKDuplicateConfig` defaults/threshold | G4/G5 / maintainer |
| **R35** | Fix requires changing any protected production path, public API, format, dependency, benchmark or CI topology | HARD STOP | Report minimal proposed amendment; continue independent tests only | Extend allowlist silently | G0–G9 / maintainer |
| **R36** | Existing B1/B2/B3 regression fails after F1 edits | AUTO-RESOLVE **only if** narrow introduced test-only wiring defect is proved | Correct within allowlist and rerun invalidated gates; otherwise R40 | Blanket retry, modify historic oracle, assume pre-existing | G4/G7 / agent or maintainer |
| **R37** | A failure is claimed pre-existing or flaky | DEFER AND CONTINUE | Reproduce with source-identical baseline or demonstrate nondeterminism; preserve both logs | Label by impression or delete negative evidence | Affected gate BLOCKED / maintainer |
| **R38** | Final source/test SHA differs from QA/CI-tested executable SHA | DEFER AND CONTINUE | Compare blob sets; re-execute affected gates on changed source; docs-only diff follows R39 | Reuse stale green source claims | G7/G8 / agent |
| **R39** | Only documentation/evidence changed since TESTED and source/test/config diffs are empty | AUTO-RESOLVE | Record exact protected diff and `git diff --check`; reuse source QA, verify final-head CI | Re-run full QA just for prose or assume CI success | G7–G9 / agent |
| **R40** | Unforeseen condition, semantic conflict, unlisted design choice or required witness unavailable | HARD STOP affected work | Preserve immutable state/evidence; report smallest maintainer decision and isolate unrelated safe steps | Improvise, move gate, change threshold, run B4 or merge | Relevant gate / maintainer |

**Matrix application protocol:** For every obstruction, identify the exact ID and observable evidence first; an `AUTO-RESOLVE` step cannot be generalized to a different trigger. A `DEFER AND CONTINUE` entry keeps its dependent gate BLOCKED and permits only independent tasks. `HARD STOP` protects the affected work; halt the entire PR if safe isolation is impossible. If several rows apply, pick the most restrictive. These 40 rules authorize *execution*, not independent architecture approval. Record each triggered row and all nontrivial errors in the append-only report.

## 10. Acceptance gates (G0–G10)

| Gate | PASS requires | Otherwise |
|---|---|---|
| **G0 — accepted source** | Open/draft PR #128, exact main/branch reconciliation, no foreign work erased, protected blob inventory | `STOP_SOURCE_MISMATCH` or documented pending identity |
| **G1 — frozen invariant worksheet** | F1-I01..I09 linked to source, plausible negative counterexample, named U/I test, owner and gate | HARD STOP contradictions; no implementation claims |
| **G2 — corrupt search** | New real `UnifiedSearcher` U01 actually executes zero-hit and matched cases over **same checksum-valid corrupt snapshot**; matched returns exact typed DOC_KEYS error, pristine index unaffected | BLOCKED; direct `reader.doc_key` alone is not sufficient |
| **G3 — concurrency/poison** | U02/U03 builder blocks after real allocation, waiter enters same cache, error/panic RAII notify and retry succeed, final budget zero; U04 exact poison error; U21 state-local sequencing | BLOCKED; one passing successful-publication waiter is insufficient |
| **G4 — policy/negative checks** | B3-U09 exact mode cutoff K31/K32 and valid two-field sort result; no tautology; all B1/B2/B3 unit groups green | BLOCKED on missing oracle or unexpected error |
| **G5 — public integration** | B3-I08 `K=32` really resolves ExactSet, 18 exact input-derived hits/projections/score bits, plus all existing I01–I08 and relevant B1/B2 integrations | BLOCKED; K18/threshold32 does not count |
| **G6 — real RustFS regression** | Existing unchanged remote `b1_r01_cold_shared_ordinals_and_pit` actually executed/pass in authorized hosted CI | BLOCKED if only registered/compiled/mocked |
| **G7 — final QA** | §7.3 commands successful on identical final tested source; Rust 1.85 MSRV, default/all feature coverage ≥85%, no test exclusions; exact counts/logs | Source-specific QA failure or unverified gate, no false PASS |
| **G8 — CI** | Five ordinary jobs terminal success on TESTED or exact source-equivalent final head; exact commit and run IDs | `IMPLEMENTED_VERIFICATION_BLOCKED` if pending/failing |
| **G9 — scope/delivery** | Only allowlisted files changed, plan verbatim, report/evidence append-only, draft PR retained, source identities/protected diff verified | Incomplete delivery; no promotion |
| **G10 — maintainer acceptance** | Independent reviewer accepts B3-F1 and maintainer decides merge | **Always OPEN for coding agent** |

## 11. Required final execution report and independent-review checklist

Append F1 findings and execution to **existing** `PERF06B3_EXECUTION_REPORT.md`; retain prior B3 report untouched above the F1 section. Minimum required content:

1. **Identity:** repo, branch, PR URL/state, accepted main, prior head, START, TESTED, FINAL, REMOTE_VERIFIED, ancestry/fast-forward proofs, exact source-equivalent diff including docs-only commits.
2. **Source scope:** files changed with function/test anchors, explicit `#[cfg(test)]` fields/increments, protected production bytes and statements on unchanged codec/storage/duplicate/cursor semantics.
3. **F1 invariant ledger:** each F1-I01..I09 → changed test → executed command and exact PASS; include actual negative counterexamples and why they reject the previous incomplete tests.
4. **Corrupt snapshot:** literal two rows/match flags, mutated DOC_KEYS byte at exact offset, rebuilt checksum/descriptor, original-vs-rebuilt identity, zero-hit success, matched typed error (twice), ineligible matched error and healthy baseline success; no simulated output.
5. **Waiter/recovery:** one state per U02/U03; explicit `AfterHashAllocation` probe, channel protocol, local wait count, RAII notify count, builder typed error or caught panic, eventual Ready owner, final metadata zero-after-last-drop; separately poison-test error. State whether any test timed out, without hiding attempts.
6. **ExactSet/I08:** threshold 32, TopK 32, complete 18-key literal oracle, full projection and score bits, independent resolved-mode unit evidence; U09 exact two-column oracle replacing vacuous assertion.
7. **Gate and QA evidence:** actual test identities/selected counts/ignored, both toolchains, Clippy/fmt/doc/bench-compile/scripts, default/all-feature numerators and line coverage, hosted five jobs and actual real RustFS body, or precise BLOCKED reasons.
8. **Decision-matrix ledger:** every triggered R row, red/green where a true RED occurred, issue classifications (introduced/pre-existing/nondeterministic/environment) with source proof; never invent RED or suppress an initial failure.
9. **Residuals:** no public committed corrupt-file injection and no public metadata-only fallback fixture (both remain explicitly separate and accurately labeled), cache wake causality bounded by timed polling, historical 15H-C / 15I-D1-F performance rejections unchanged, no warm/RSS claim. The new tests should close collector-level corrupt-query and blocked-waiter gaps without changing runtime behavior.
10. **Handoff:** G10 OPEN, no merge, no B4 start, maintainer acceptance required. Exact final disposition.

**Final adversarial self-review — explicitly answer before handoff:** Can a corrupted nonmatching key escape a matched search? Is the snapshot checksum valid and descriptor recomputed? Can a zero-hit query avoid key resolution? Did any waiter really reach its own cache's `Building` wait? Could an unrelated test satisfy a global counter? Does the RAII notify site actually execute on both error and panic? Does final budget drop to zero when no state owner remains? Does deliberate poison return the right error without clearing the poison? Is ExactSet actually selected for K32 rather than just configured? Does the multi-sort test demand valid output instead of accepting either result? Is release/benchmark source still unchanged? If an answer lacks an executed oracle, affected gate cannot pass.

**Terminal instruction:** Implement only this fixup on PR #128 with continuous authorized execution. Preserve working B3 production behavior. Provide precise evidence for the four identified test gaps and all relevant QA gates. **For every unanticipated requirement or mismatch, apply R40 HARD STOP rather than designing.** Do not rewrite history, adjust limits, waive gates, optimize performance, start B4 or merge.
