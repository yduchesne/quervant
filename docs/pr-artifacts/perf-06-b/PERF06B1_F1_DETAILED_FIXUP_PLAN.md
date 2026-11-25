# PERF-06-B1-F1 — Independent-review correction plan for PR #126

**Repository:** `yduchesne/quervant`  
**Existing pull request:** [#126](https://github.com/yduchesne/quervant/pull/126), branch `dev/perf06-b1` (keep the same draft PR; do **not** create another PR)  
**Frozen B1 base:** `480a77e78c6897e05cb7ceb76b01434974b82ec6`  
**Production source independently reviewed:** `8e11484af49e38243a97d765ef21662f7e3060a3`  
**Latest PR head observed while authoring:** `9c0009626bddb582a49bfb07d3d04abad82876ea` — exactly one commit after the reviewed source, affecting only `PERF06B1_EXECUTION_REPORT.md` and `evidence/ci-status.txt`  
**Precedence:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`; approved `docs/pr-artifacts/perf-06-b/PERF06B1_DETAILED_PLAN.md` (revision 1, SHA-256 `fe5ef98d100f8e1160e19c5d88663abde580d201d806c04721f94cb4a429f951`); `docs/ARCHITECTURE.md`; `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md`; `docs/TESTING.md`; current `AGENTS.md`.  
**Nature of work:** corrective implementation and missing acceptance evidence, **not** redesign, new feature, performance experiment, or permission to merge.

## 0. Absolute execution contract

**Continuous execution authorization:** Execute this approved fixup from preflight through all prescribed implementation, tests, documentation, one ordinary push and CI inspection without seeking routine reconfirmation. Continue automatically after successful checkpoints and predefined AUTO-RESOLVE decisions. Stop affected work only on an applicable HARD STOP, a genuinely missing human design decision, or an essential external dependency. For an isolated blocker, preserve evidence and continue demonstrably independent approved work; do not claim a blocked gate passed. No agent-originated architecture, API contract, performance campaign, release, merge, approval, or plan amendment is authorized.

1. **First pull the latest** from `origin/dev/perf06-b1` using a fast-forward-only operation. Keep PR #126 open and draft. Do not force-push, reset, rebase, cherry-pick or change the base without explicit approval.
2. Preserve every accepted B1 representation and API: `FEATURE_KEYWORD_ORDINALS = 0x0010/1`, COLUMNS v2/layout `0x03`, byte-exact keyword dictionaries, 46-byte header, 36-byte block directory, `KeywordOrdinalColumn`, `SnapshotKeywordOrdinals`, `KeywordOrdinalPreparation`, numeric per-segment translation and the one-field/one-snapshot cache. Keep COLUMNS v1 bytes immutable.
3. Fix **five implementation issues** (F1-01…F1-05), complete **three evidence families** (F1-06…F1-08), and correct **three narrow codec-contract discrepancies** (F1-09…F1-11). No query collector, comparator, scorer, cursor, Top-K, duplicate-identity, benchmark framework or benchmark acquisition changes.
4. Use existing `MetadataBudget`, `MetadataMeter`, `MetadataReservation`, `SegmentLimits`, `DecodeBudget`, `ByteReader`, `ObjectStore`, `CurrentPointer`, `Manifest`, `ReaderSnapshot`/PIT and the genuine frozen historical fixture. Do **not** create another cache, allocation framework, persisted mapping, field registry, migration utility or new public setting.
5. Observe and report actual test execution. **Test exists ≠ test ran ≠ test passed in the required topology.** A self-review and a green CI run alone do not close the frozen independent acceptance requirements. G10 stays maintainer-owned.

## 1. Source preflight and evidence reconciliation — before editing

Run from the repository root (save output in the B1 evidence directory; redact secrets):

```sh
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
git diff --name-status 8e11484af49e38243a97d765ef21662f7e3060a3..HEAD
git diff --name-status 480a77e78c6897e05cb7ceb76b01434974b82ec6..HEAD
```

Before switching, a dirty worktree is **HARD STOP** for mutation: do not discard someone else's files. `git fetch` may be run to inspect safely, but do not auto-stash, clean, or reset. Reconfirm that PR #126 is open/draft, targets `main`, and that the current head is the selected branch. Re-read the guide, the frozen B1 plan, the latest B1 execution report, and the exact source symbols listed below. Verify the recorded plan hash/blob is unchanged. If GitHub reports a newer head than `9c000962…`, compare its executable/test/CI files to `8e11484…` and apply decision D02; a **code-bearing intervening change** is not automatically superseded or overwritten.

**Reconciliation at authoring time:** the reviewed production code implements the B1 codec/map and had local/real-RustFS test passes, but the previous independent review identified resource-admission defects, a malformed-input panic, waiting/cancellation gaps, and missing proof obligations. The latest observed commit is documentation/CI-evidence only. In the existing report, G2/G3 are **implemented but need corrections**, G4/G5/G6 are **executed but inadequately verified**, G7 represents prior-source QA only, G8 represents the prior source/CI, G9 requires an additive correction and G10 remains **OPEN**. Do not preserve the earlier `PASS` labels as evidence for a changed source.

**Read-only source anchors** (line numbers are approximate at reviewed SHA; use symbols, not blind patches):

| Area | Existing symbol / path |
|---|---|
| Map, registry, wait, cancellation, reservations | `crates/quervant-core/src/index/keyword_ordinals.rs`: `KeywordOrdinalCache::prepare`, `wait`, `build_and_publish`, `initialize_registry`, `build_field_map`, `grow`, `RegistryInitGuard`, `FieldBuildGuard` |
| Existing memory meter — **reuse unchanged** | `crates/quervant-core/src/segment/metadata.rs`: `MetadataMeter::{reserve,extend,charge,charge_vec,charge_arc,finalize}`, `capacity_bytes`, `element_bytes`, `accumulate` |
| V2 codec/ordinary-plan accounting | `crates/quervant-core/src/segment/column.rs`: `encode_columns_with_ordinals`, `plan_ordinary_column`, `dictionary_geometry`, `validate_keyword_dictionary`, `ColumnReader::value`, `bind_keyword_ordinal_meta`, v2 row validation |
| Local lifecycle | `crates/quervant-core/tests/perf06_b1_ordinals.rs` and `tests/perf06_b1_common/mod.rs` |
| Real provider | `crates/quervant-core/tests/perf06_b1_rustfs.rs`; existing `quervant_objectstore::ObjectStore::get` and `RemoteKeyPrefix::object_key` |
| Frozen fixture | `crates/quervant-core/tests/fixtures/index/perf06_b1_columns_v1/` (six CURRENT-reachable objects and metadata files) |
| Source of required evidence | B1 original plan §§8.7–8.8, 9.1–9.5, 10–13, 15–18 |

### 1.1 Pre-implementation correctness challenge (mandatory)

Before production edits, fill a short invariant-to-test worksheet in the new F1 report: for every INV-F1 row below, state the affected source symbols, one positive case, a negative/counterexample case, and the exact acceptance test(s). Challenge each against a plausible wrong implementation: hidden vector capacity, a `U=u64::MAX` payload, notify-before-wait, cancellation immediately after entry, false `PASS` on a legacy index, and a cold-open that checks only some documents. Record any true contradiction; use the decision matrix in §10, never invent a new contract.

## 2. Frozen acceptance invariants and cross-component impact

| ID | Always-true observable property | Required positive and adversarial proof | Components changing / preserved |
|---|---|---|---|
| INV-F1-01 | Every new map scratch backing is checked, charged before allocation, within existing single-allocation cap and peak construction allowance; no partial owner published | G15 exact/one-below; G16 each allocation; G19 last-Arc release; G20 structural accounting | `keyword_ordinals.rs`; preserve `metadata.rs`, snapshot admission and production search |
| INV-F1-02 | Retained ordinary-column `Vec` backings each obey `max_single_allocation` even if the cumulative/output size fits | U09 mixed-column capacity-over-limit; exact/one-under success/failure; unchanged committed state | `column.rs`; unchanged legacy encoder temp behavior |
| INV-F1-03 | Malformed v2 bytes always fail typed, never panic or wrap | U05 `U=u64::MAX`, overflow, bad offsets/terms, standalone + valid outer container | `column.rs`; preserve COLUMNS wire and v1 behavior |
| INV-F1-04 | Notification cannot create a gratuitous full 5-ms wait after the predicate becomes false | G13 deterministic notify-before-reacquire, spurious wake, cancelled waiter | `keyword_ordinals.rs`; preserve Mutex/Condvar and existing 5-ms cooperative wait |
| INV-F1-05 | Cancelled construction publishes nothing; cancel after publication does not delete a valid cache; no cancellation while locked | G12 mid-registry/before allocation/before publication; G13 real waiter; G14 error and unwind | `keyword_ordinals.rs`; preserve RAII/typed sticky semantics |
| INV-F1-06 | All frozen U/G test groups exercise their named behavior, not merely related code | U09/U10/U14; G08/G13–G16/G20, with actual execution and logs | Unit tests, narrow test-only seams; no production hooks |
| INV-F1-07 | Genuine v1 → mixed → all-v2 compaction preserves **all** original and appended documents, all immutable old objects, and old PIT views | I03 intermediate state and inventories; I04 full g3/g4/g5 data, queries, aggregation, child process | Local test/helper only; fixture never regenerated |
| INV-F1-08 | Real-RustFS generation-3 immutable remote object bytes remain identical after g4 publication; repeated independent cold open proves full results | R01 direct five-object digest/byte check, full 18/19 rows, two independent g4 cold opens, PIT and request counter | RustFS test only; remote production publication untouched |
| INV-F1-09 | Frozen error labels and precedence are reproduced exactly | U05/U06 table-driven compound malformed cases; no `.is_err()` substitution | V2 decode only; v1 errors unchanged |
| INV-F1-10 | V2 materialized Keyword strings use checked/fallible allocation after old logical budget admission | U13 exact Single/MultiOne budgets and forced allocation/limit failures | V2 ordinal value branch only; public API shapes unchanged |
| INV-F1-11 | Final evidence belongs to the final executable source and honestly reports all skipped/blocked gates | source SHA/CI/log reconciliation, protected path diff, report correction notice | B1 evidence/report and additive status docs only |

**Boundary analysis:** check empty/single/multiple segments; empty dictionary, U=1 and width transitions; exact/one-byte under memory; zero/missing/null/Single/MultiOne; malformed prefix/overflow/unselected corruption; cancellation before claim, during registry, while waiting, during merge and around publication; error/unwind/poison; g3 old/g4 mixed/g5 compacted and held pins; real remote cold bootstrap. No network fault injection or performance test is introduced beyond existing RustFS/CI regressions. Failure is never converted to a successful partial result.

## 3. F1-01 — Repair optional map peak-memory admission [production]

**Observed defect:** `build_field_map` creates `Vec<KeywordOrdinalColumn<'_>>` with `try_reserve_exact(S)` before `MetadataMeter::reserve` and before `check_allocation_bytes`; it later estimates `scratch` from the *already allocated* vector and heap, omitting the concurrently live `Vec<Vec<u8>>` outer backing. The existing meter can therefore understate peak and miss the single-allocation ceiling.

**Prescribed algorithm, multi-segment path (`S = guards.len() > 1`):**

1. Poll cancellation before construction. Convert `S` to `u64` with `try_from`; map conversion/checked arithmetic and limit failures to sticky `ResourceBudget`. Compute checked exact requested-capacity bytes, **before any source allocation**:

   ```text
   source = S * size_of::<KeywordOrdinalColumn>()
   heads  = S * size_of::<MergeHead>()
   outer  = S * size_of::<Vec<u8>>()
   owner  = size_of::<SnapshotKeywordOrdinals>()
   fixed_allowance = checked_add(source, heads, outer, owner)
   ```

   Each `source`, `heads`, `outer`, `owner` backing individually goes through `SegmentLimits::check_allocation_bytes`; `fixed_allowance` is the shared **peak candidate budget**, not itself a single vector backing and is therefore not substituted for an individual check. Fail with `NotAvailable(ResourceBudget)` on nonrepresentable dimensions or budget admission. Do not create a new configured cap.
2. Call `MetadataMeter::reserve(budget, fixed_allowance)` **before** `sources.try_reserve_exact(S)`. Use the existing `grow` helper (correct it minimally if necessary) for `sources`, so it performs `alloc_fault_check`, per-backing limit checks, `meter.charge(requested_capacity_bytes)` *before* the fallible reserve and actual-capacity reconciliation. No special unmetered `Vec::reserve`, `Vec::with_capacity`, infallible `collect` or post-hoc-only charge.
3. With all source guards already validated, bind them exactly once (preserve `LegacySegment` and codec error precedence), calculate `T = checked_sum(U_i)` and `width = packed_width(T.saturating_sub(1))`; calculate `payload = checked_mul(T, width)`. Check each `U_i * width` for representability and `max_single_allocation`. Poll after bounded source work and before the next allocation.
4. Extend the **same** meter once by `payload` before allocating the inner map backing. Allocate outer `buffers: Vec<Vec<u8>>` through `grow` with `S` capacity; allocate each inner vector through `grow` with exactly `U_i * width`; charge actual capacities. Then allocate `heads: Vec<MergeHead>` through the same helper and heapify in place with `BinaryHeap::from(heads)`—no second heap backing. Charge `owner` exactly once via existing `charge_arc` before `Arc::new` (retain the approved fixed-size Arc convention).
5. Merge once with the existing borrowed-terms heap. Preserve `O(T log S)` comparisons, raw UTF-8 byte ordering, no string copy, one rank per local ordinal, no inverse table, no document or live-mask read. All nonempty outputs must fit their already-admitted capacities; no growing published map. Poll every 256 emitted terms and at specified transition boundaries.
6. Drop `heap` and `sources` **before** finalization; keep their allowance charge until `MetadataMeter::finalize`. Independently measure the retained charge = `size_of(owner) + actual outer capacity * size_of(Vec<u8>) + sum(actual inner byte capacities)`. Finalize against the same peak allowance (fixed + payload), releasing scratch/unused bytes. The resulting `MetadataReservation` belongs to the last `Arc<SnapshotKeywordOrdinals>`, not to the cache slot. On allocation failure/oversized actual capacity/limit fail, discard the candidate and let RAII release the full allowance.
7. Keep the one-segment identity path allocation-free except for its already-authorized charged owner and the zero/unsupported/legacy behavior unchanged. **Do not** add reserved source vectors there.

**Important meter distinction:** `MetadataMeter::reserve` increases the budget's reserved allowance; `charge` tracks allocations within that already-reserved allowance. Do not double-reserve the same backing. `grow` must check `desired * sizeof(T)` before calling `try_reserve_exact`, ensure a test fault results in `Allocation` (not `ResourceBudget`), reconcile actual capacity, and never allocate a replacement backing without its charge.

**Mandatory tests:** `b1_g15_...` with a private `KeywordOrdinalCache` and an explicitly supplied `MetadataBudget` is allowed under `cfg(test)` to *isolate ordinal construction* from verified-segment metadata. Reuse **real admitted guards** from a generously budgeted snapshot, pass their actual binding/id/segment count to the **existing production `cache.prepare`**; do not mock `KeywordOrdinalColumn`, the merger or meter. Determine `R = eligible_field_count * size_of::<RegistryEntry>()` and independently derive `P = fixed_allowance + T*width` from the fixture and Rust `size_of` (not from `map.retained_charge()` or production allowance as the only oracle). Require `R+P` success, `R+P-1` sticky `ResourceBudget`, and no additional build or reservation on second request. Separate tests may call the private real `build_field_map` directly to isolate P alone. Test individual source, heap, outer and each inner cap and cancellation after reserve. Measure actual capacity and report it; a larger-than-requested allocator capacity must be charged/rejected, never silently accepted. Verify drop of scratch and final Arc releases the modeled charges.

For G16, enumerate **all** actual `alloc_fault_check` call sites (registry entries, source, outer, each inner buffer, heap, and any extra site introduced). Use a counted table derived from the audited source rather than `0..6`; the reviewed three-segment case has an additional site at index 6. For **each** injected site, demand precisely `NotAvailable(Allocation)`, sticky on same snapshot/field, no published partial map and unchanged preexisting budget charge after candidate cleanup; a fresh independent snapshot succeeds. Never accept `ResourceBudget` as interchangeable with injected allocator failure.

## 4. F1-02 — Check every retained ordinary-column backing [production]

**Observed defect:** `encode_columns_with_ordinals` calls `plan_ordinary_column`, accumulates the capacities of its outer `Vec<BlockPlan>`, every `block.state` and `block.values`, then calls `budget.reserve_bytes(retained)` without **per-backing** `SegmentLimits::check_allocation_bytes`.

Insert these exact checks between constructing the ordinary plan and cumulative `reserve_bytes`:

```text
check_allocation_bytes(capacity_bytes::<BlockPlan>(blocks.capacity()))
for block in &blocks:
    check_allocation_bytes(capacity_bytes::<u8>(block.state.capacity()))
    check_allocation_bytes(capacity_bytes::<u8>(block.values.capacity()))
checked_sum of the same measured capacities -> budget.reserve_bytes(sum)
```

Return the existing `SegmentError::LimitExceeded { limit, requested }`, using the **actual backing capacity in bytes**. The checked sum is not a substitute for per-backing checks. Keep legacy temporary `ByteWriter` construction unchanged; it is the frozen B1 exception. Keep one output admission, the legacy v1 encoder, both producers, and all noneligible wire bytes unchanged.

**U09:** add a mixed eligible-Keyword/ordinary-Bool (or another already-defined ordinary single-layout) case with 65 all-missing rows, `block_docs=1`, and a cap chosen to expose retained vector capacity > cap even though the finished encoded bytes would fit; the previously observed 64-bit growth example is state-buffer capacity 6,144 bytes, cap 5,500, completed body 5,055. **Do not hardcode a guessed allocator capacity as a universal invariant.** Assert the exact measured backing capacity/requested bytes from the fixture's test-only observation; use a direct private helper test with a deterministically over-capacity retained backing to establish the check independent of allocator growth policy. Positive exact-cap and one-under cases must exercise the actual encoder as far as safely possible. I06 is an ordinal-only fixture and does **not** substitute for mixed U09.

## 5. F1-03, F1-09 and F1-11 — Hardening v2 decode and preserving error precedence [production]

### 5.1 Count overflow with frozen error precedence

**Observed:** `dictionary_geometry` derives `(terms + 1).checked_mul(...)` before `validate_keyword_dictionary` rejects `terms > meta.doc_count`. `U = u64::MAX` therefore panics with overflow checks enabled.

Change the private geometry derivation minimally:

1. Read the 16-byte `(U,L)` prefix through the existing `ByteReader` with contexts `keyword dictionary term count`, `keyword dictionary byte length`.
2. In authoritative validation, reject `U > doc_count` **first** with `InvalidColumnGeometry { detail: "keyword dictionary count exceeds document count" }`, then `U=0 && L!=0` with `"empty keyword dictionary has payload"`; preserve `limits.check_entries(U)` and the rest of §9.1 precedence.
3. Derive offsets only from validated `(U,L)` using `U.checked_add(1).and_then(|n| n.checked_mul(ow as u64))`; use the frozen `"keyword dictionary extent overflow"` detail on failure. `usize` conversions and `strings_base + L` must be checked; no `as` cast to index an unverified offset and no overflow-prone `a+b` before a `get` range.
4. Keep `dictionary_geometry` usable by the already-validated `bind_keyword_ordinal_meta`, but do **not** trust callers in place of checked geometry. A suitable private refactor is a checked `(U,L)` prefix reader plus a checked geometry constructor receiving the parsed values; validation performs the count-dependent checks first, and the bound reader invokes the same checked geometry constructor after authoritative opening. Do not change the public borrowed handle or store duplicate strings/offset arrays.
5. Add U05 regression: start with the frozen 116-byte valid v2 body; change only bytes `[88,96)` (dictionary U field) to `u64::MAX` and confirm the **exact typed count-exceeds-docs error** under debug and test builds, never unwind. Test `U` near representability limits in the pure geometry helper, and wrap changed bodies into valid `ContainerBuilder` envelope/checksums to exercise actual `SegmentReader::open`—not only standalone `ColumnReader::open`. Include corruption in an unselected term.

### 5.2 Offset/term validation order

The reviewed implementation makes **one pass over every offset** and then **another over terms**. Replace that with the frozen §9.1 single ordered validation: first-offset-zero; for each successive offset check `offset <= L`, monotonicity against previous, then validate the **just-delimited term** for length `<=65535`, UTF-8 and strictly ascending raw bytes, before reading the next term; finally terminal-offset-exactly-L. All geometry extents must be checked first. Do not let a later bad offset mask an earlier term's invalid UTF-8/order error. Add a compound-adversary where an early invalid term precedes a later malformed offset, and assert the frozen earlier error. Use only one bad earliest condition when testing an individual error label.

### 5.3 Layout-3 state error

At v2 row validation where `valid_state(*state, meta.layout)` fails, branch on `LAYOUT_KEYWORD_ORDINAL_SINGLE`: emit `InvalidColumnGeometry { detail: "invalid keyword ordinal state" }`; retain the historical `"invalid state tag"` label for other layouts/v1. Update only the new v2 test expectation (currently it asserts `"invalid state tag"`); leave legacy negative tests intact. Preserve state `0x00`, `0x01`, `0x03`, `0x04`, reject `0x02`, and ensure missing/null ordinal slots are zero.

## 6. F1-10 — Fallible owned Keyword materialization for ordinal rows [production]

**Observed:** `ColumnReader::value`'s `ValueSpan::Ordinal` creates both `Single` and `MultiOne` strings with `keyword.to_owned()` after logical budget admission; these are infallible allocations.

For both branches use a single small private fallible owned-string helper following the **existing** string admission:

```rust
// sketch of required operation, not permission to change earlier checks
let mut result = String::new();
result.try_reserve_exact(keyword.len()).map_err(|_| SegmentError::LimitExceeded {
    limit: self.limits.max_single_allocation(),
    requested: keyword.len() as u64,
})?;
result.push_str(keyword);
```

Keep the actual helper scoped to the ordinal branch; do not modify the original `decode_scalar` or all legacy value paths. For `Single`, preserve `DecodeBudget::reserve_string(len)` before calling the helper. For `MultiOne`, retain **exactly**: `limits.check_entries(1)` → `limits.check_alloc::<FieldValue>(1)` → `Vec::<FieldValue>::try_reserve_exact(1)` → a **separate** `DecodeBudget::reserve_string(len)` → fallible string copy → vector push. Never combine the two logical budgets or move string admission before the one-element vector check. Keep `keyword_sort_view` Single borrowed/charged and MultiOne `LegacyDecode`; keep `encoded_value_shape` length `len+2` / `len+3` and all public shapes and query work charges.

Use the frozen 80-byte U13 test: logical section budget 80 succeeds with `max_single_allocation >= max(80,size_of::<FieldValue>())`; section budget 79 fails requested 80; one byte below `size_of::<FieldValue>()` rejects MultiOne before string allocation. Add a scoped allocator-failure case using a test-only string-reservation seam if the existing project provides one; otherwise demonstrate the fallible code path by inspection and exact allocation-limit tests, **not** an invented global allocator or unsafe hook. Stop for an amendment if an exact injected OOM is made a mandatory test without an approved seam.

## 7. F1-04 and F1-05 — Predicate-driven wait and complete cancellation [production]

### 7.1 Lost notification / unnecessary timeout

**Observed:** `prepare` receives `Next::WaitRegistry` or `Next::WaitField`, drops its mutex, then `wait(cancellation)` takes it again and unconditionally `wait_timeout`s 5 ms. A builder can publish and notify in between; the waiter sleeps despite a ready result.

Use a private `WaitFor` discriminator with exactly two modes: `Registry` and `Field(field_id)` (numeric ID, not a stored reference to a movable registry vector). When entering the wait helper:

1. Poll cancellation outside locks, lock through existing poison-to-typed-error `lock()` method.
2. **Under this lock**, evaluate the actual predicate: `RegistryState::Initializing` for registry wait; `RegistryState::Ready(registry)` with the matching entry in `EntryState::Building` for field wait. For all other states—including a completed, unavailable or poisoned state—do not start a timed wait. If the field id is no longer present, return to `prepare` to apply the canonical typed result/check rather than fabricate a ready value.
3. Only while the appropriate predicate is still true call existing `Condvar::wait_timeout(..., WAIT_INTERVAL)`. Release lock; poll cancellation outside lock, then let `prepare` loop and re-read state. Recheck after spurious notifications in the next iteration; do not spin while holding the lock or create a second synchronization primitive.
4. On poison, return the existing `"keyword ordinal cache lock poisoned"` typed error, never `into_inner` on normal API paths. Keep existing registry/field RAII reset and `notify_all` on error/panic.

**G13 must prove the race deterministically** by a `cfg(test)` hook/barrier placed after `Next::Wait*` decision and before the new helper's mutex acquisition. Arrange builder publication and notification in that interval; release the waiter and assert it returns Ready/NotAvailable **without entering `wait_timeout`**. Use a test-only wait-invocation counter or deterministic state observation—not wall-clock elapsed time. Exercise both registry and field modes, a spurious notification while still `Building`, and a waiter cancelled *after it actually enters waiting* while the other builder publishes normally. No production-time diagnostics or sleeps used to establish event ordering.

### 7.2 Cancellation across registry, mapping and publication

`initialize_registry` presently has no cancellation argument and schema field/guard loops can run after only an entry poll. Add `&dyn Cancellation` to the private function and poll:

- at registry initialization entry; at least every 256 other-guard schema comparisons and field eligibility enumerations; before registry-entry vector reservation; after filling entries; immediately before returning the completed registry candidate;
- before multi-segment source vector reservation; at least every 256 bound sources; after T/width calculations and before each outer/inner/heap allocation (the build loop already has some polls, preserve them); every 256 emitted terms; and immediately before handing the completed owner to publication;
- immediately **before publication** outside the mutex in `Next::Initialize` and `build_and_publish`. On pre-publication cancellation, allow the existing RAII `RegistryInitGuard` / `FieldBuildGuard` to revert `Initializing→Uninitialized` or `Building→Empty`, notify waiters, release temporary reservations and return `IndexError::Cancelled`.

Maintain the frozen post-publication rule: disarm the relevant guard and notify before the final callback; if cancellation is observed after publication, only the cancelling caller returns `Cancelled`, while the published shared result remains available to another caller. Do not call `Cancellation::is_cancelled()` while holding the cache mutex. A `NotAvailable(Allocation/ResourceBudget/LegacySegment/UnsupportedField)` remains sticky if successfully published; an authoritative codec/schema error or pre-publication cancellation does not become sticky.

**G12/G14:** add deterministic hooks around the unlocked registry build, field merge, and just-before-publication boundary, scoped to the test module. Test cancellation in both phases; after error, build state is not stuck; a fresh request on **the same snapshot** can proceed for cancelled/errored construction. A separate scoped panic after the claim but outside the mutex, wrapped in `catch_unwind`, proves RAII reset and waiter wake-up for **both** registry and field. Verify the budget returns to prior value and that a subsequent valid call succeeds. Poisoning must still fail closed. Allocation refusals, unlike errors and panics, are sticky optional outcomes and must not be used as proof of RAII reset.

## 8. F1-06 and F1-07 — Restore mandatory unit and local lifecycle evidence

Keep all existing positive tests and frozen fixture payloads; add assertions/tests without reimplementing production queries or changing the corpus's first 18 rows.

### 8.1 Required unit cases

| Test group | Concrete correction | Independent oracle / expected failure |
|---|---|---|
| U05/U06 | Cases in §§5.1–5.3 | Exact static error labels at authoritative open; valid full outer checksums |
| **U09** | Mixed ordinary-vector capacity, exact allocation/failure/overflow and final output | Measured per-backing capacity; unchanged durable generation on failure |
| **U10** | Implement original §10.3 deterministic **64-case codec differential** | Input-only `BTreeSet`/sorted raw byte values; every document state/local dictionary/ordinal; include MultiOne. Do not use `ColumnReader` or production sort to compute expected values |
| **U14** | Real writer accepts `FieldValues::Multi(vec![])` into the pending columnar-only Keyword/Single document, then `commit()` rejects it | `IndexError::Segment(SegmentError::InvalidColumnGeometry { detail: "zero multi count" })`; g1 CURRENT, manifest, segment/state objects and values unchanged; writer dropped, fresh reader still opens g1 |
| **G08** | Observe deleted-only Boston *before* compaction | Physical local dictionary contains Boston in g5 delete-committed view; current live results exclude deleted document; new compacted view drops term; held g3 PIT still has it |
| **G13/G14** | Actual waiter, wake race, error/panic after claim | State and accounting transitions, not `cancelled` at entry or sticky allocation as substitute |
| **G15/G16** | Real exact peak and full fault-site ledger | Exact success and one-byte-under `ResourceBudget`; each injected site exactly `Allocation` |
| **G20** | Ordinary public query on fresh Uninitialized registry; direct reuse | Query does not create ordinal registry; prepare builds once, next call returns identical `Arc` without second merge |

For U10 implement the original plan's §10.3 deterministic generator **as written**; if the current file already contains a generator, show that it tests **codec** rather than only the cross-segment mapper. Use seed/family bounds from that plan; no new randomized dependency or broad unbounded fuzz campaign.

### 8.2 I03: append → delete → compaction with old views

Use fresh `Index::open_existing` after every commit; never assume a stale `Index` handle refreshes. Before and after each transition assert actual g3/g4/g5/g6 generation, 18/19/18 visible documents as appropriate, segment count, full sorted key and projection sets from a test-only expected table. Specifically:

1. Hold original g3 PIT/map and inventory hashes of its immutable segment, state and manifest objects.
2. Append d0 Chicago at g4 and prove 13 shared terms and shifted ranks in a new snapshot; old g3 rank values remain unchanged.
3. Delete b0 Boston and commit g5; **before compaction**, prepare the g5 map, find physical Boston in the segment dictionary/global map but prove b0 is absent from live search results; do not infer this from reading builder source.
4. Compact to g6; prove one new segment, Boston removed, rank numbers changed only for the new view, complete 18 visible keys and all values; verify old g3/g4/g5 immutable hashes remain identical (content-addressed files, not CURRENT); retained PITs stay exact.

### 8.3 I04: genuine frozen historical fixture, full evidence

Keep `tests/fixtures/index/perf06_b1_columns_v1/**` byte-for-byte identical. Verify its fixed `objects.tsv` inventory, six reachable entries, exact lengths/SHA-256, actual `CURRENT`→manifest→three segments+state closure. **Never regenerate the fixture with the B1 binary.** Copy only its `index/` subtree into a fresh test-owned local root.

1. **g3:** open genuine legacy `COLUMNS` v1 three segments, absent `0x0010/1`, 18 frozen rows. Run complete input-derived values, ASC/DESC with both missing placements, K prefixes, projections, counts, typed predicates, and the applicable public aggregation; check `LegacySegment` optional outcome. Save the five old immutable object bytes/digests excluding CURRENT. Hold g3 PIT/snapshot for later full-query comparison.
2. **g4:** append **both** `d0=(Chicago,type-d,n18)` and `d1=(Seattle,type-d,n19)` in one real commit, with all other fields matching the common schema. Do not use `Batch::A`/`type-a`. Add one small test-only `appended_document`/`expected_row` helper for the `type-d` rows; **do not alter `ROWS` or the A/B/C frozen first-18 corpus**. Assert g4/20 live docs/4 segments, precisely three v1 and one v2 by inspecting actual feature declarations and COLUMNS body versions. The map is still `LegacySegment`. Check all 20 values, full result orders and projections, exact category group counts (`type-a`, `type-b`, `type-c` each 6; `type-d` 2), sum(n)=190, distinct(n)=20, and relevant full corpus membership; pin g4 and hash its immutable-object inventory.
3. **g5:** run actual `IndexWriter::compact`, fresh reopen; one all-v2 segment, 20 docs, Ready identity map, exactly 13 raw city terms and four category terms. Assert exact city dictionary `["", "\0", "Austin", "Boston", "Chicago", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é", "😀"]`, full 20 document ranks/states, ASC/DESC, missing placement, K prefix, complete projections, typed predicates and aggregates. Verify g3/g4 immutable objects did not change. Assert both retained old PITs retain **complete** original views (g3 18, g4 20), not merely sample ranks/counts.
4. **Child:** drop current index/writer, spawn `std::process::Command::new(std::env::current_exe())`, pass the canonical local root and an explicit `PERF06_B1_I04_MODE=g5` environment value. The ignored child entrypoint must assert that the required variables are present (never silently return when invoked) and execute the **complete g5 20-row validation** after a fresh `Index::open_existing`. Require an unambiguous `PERF06_B1_I04_CHILD_PASS` marker, exit code 0 and exact child name filter; verify the child actually ran one test.
5. **Inventory:** derive reachable objects from `CURRENT` and `Manifest`, not directory order or “latest” filename. For g3 and g4 save immutable object bytes keyed by logical path; after g5 read those paths and compare **all bytes**, not merely file existence. CURRENT is mutable and deliberately excluded from immutable comparison. Test-owned temporary directories only; no mutation of the committed fixture.

**I04 oracle rule:** expected outcomes must come from frozen first-18 `ROWS` plus literal d0/d1, not from current query results, encoder dictionaries, translated ranks, or prior post-compaction output. A helper can compare actual `UnifiedSearcher` responses to that independent table; do not create a second production query engine.

## 9. F1-08 — Complete real-RustFS R01 proof on the existing test [no storage changes]

File: `crates/quervant-core/tests/perf06_b1_rustfs.rs`. Reuse `run`, `require_env`, `remote_config`, actual `S3ObjectStore`, `RemoteIndex`, `RemoteKeyPrefix`, Tokio current-thread runtime and existing B1 common oracle. Do not change `RemoteIndex`, `ObjectStore`, S3 adapter, transfer scheduler, cache, CAS, CI topology, or test's ignored status.

1. **Unique prefix:** use **one** `RemoteKeyPrefix` per R01 and unique workspaces for original writer, g3 cold, g4 cold A and g4 cold B. The reviewed `remote_config("main")` has the prefix suffix `-main`: preserve/reuse its `prefix().clone()` for all cold configurations. Do not create separate remote indexes by varying the suffix. All workspace roots must initially be empty and be removed only after dropping their owning readers/pins.
2. **g3 source:** three real remote commits of the immutable first 18 rows (generation 1,2,3). Before writer/index destruction capture the **five immutable generation-3 objects** (manifest + 3 segment blobs + mutation-state blob) by following **CURRENT and the parsed manifest**. Do not list or guess a newest manifest. `CURRENT` itself is mutable and excluded from the immutable comparison. Use:
   - `quervant_objectstore::ObjectStore::get(&store, &ObjectKey, None, &TransferLimits::new(exact_or_bounded_length))` (the trait method is available through `store.get` after importing `ObjectStore`);
   - `config.prefix().object_key(logical_key)` to construct the physical key; never perform a whole-bucket list;
   - `CurrentPointer::parse` for CURRENT, `Manifest::decode` with `SegmentLimits` for the manifest; check descriptor lengths and SHA-256 with `ContentDigest::sha256_v1(&bytes)` for the expected closure.
   Save the exact logical paths and bytes/digests in a bounded test-local `BTreeMap`. If a descriptor is absent/incompatible, STOP affected work rather than invent a separate remote inventory authority. The closure is the same six-object format as I04 (CURRENT plus five immutable objects).
3. **g3 cold:** drop the old remote handle, open g3 from a new empty local workspace, and pin it. Require generation 3, 18 live docs, 3 segments, full values and states, all local-to-shared rank vectors, both sort directions with explicit missing first/last, K prefixes, total counts and complete projections against the frozen table. After fully materializing the snapshot record `reopened.transfer_stats().requests()`; repeated preparations return `Arc::ptr_eq`, repeated ordinary queries add **zero** provider requests. Assert no automatic preparation on the ordinary path.
4. **g4 append:** keep the g3 PIT and prepared `Arc`, use the existing remote writer (through the g3 remote handle) to append only `d0=(Chicago,type-d,n18)` as one real commit to generation 4. Current source uses `Batch::A`; replace that in the test with the explicit `type-d` appended helper from §8.3. A fresh g4 cold workspace must show 19 live docs/4 segments, 13 city terms, all 19 states/values/ranks, full ordered key/projection/total results and unchanged held g3 values/ranks/queries. For g4 category counts: `type-a=6`, `type-b=6`, `type-c=6`, `type-d=1`; sum(n)=171 and exact-distinct(n)=19 when asserting aggregation.
5. **Second independent g4 cold:** drop the first g4 handle/snapshot/guards and open the same authoritative prefix a second time in a **third fresh empty reader workspace**. Require the same **complete** 19-key oracle, global rank map, and query assertions again. Do not reuse a snapshot, segment reader or prior local directory as proof of cold remote decoding.
6. **Immutable remote proof:** after g4 publication, GET the **same five recorded generation-3 logical keys** under the same prefix and compare every byte/length/digest to the g3 inventory; fail if any is absent or changed. A provider request counter or a retained PIT is not an immutable-object proof. Validate that `CURRENT` now resolves g4 normally. Keep old g3 PIT and original owned workspace alive until its assertions finish.
7. **Cleanup:** no remote compaction, no provider-wide deletion or bucket prune. Drop all handles; remove only paths constructed by R01 after verifying they are the recorded disposable roots, and propagate unexpected cleanup errors. Retain test-owned remote prefix on an external provider unless an already-approved scoped deletion helper is available. If task-owned RustFS container was started under original §13.2, retain its exact ID and remove it plus its anonymous volumes only.

The authoritative host command, if the pinned service is available, is:

```sh
cargo +1.98.1 test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored --test-threads=1 --nocapture
```

Require the executed `b1_r01_cold_shared_ordinals_and_pit` name and `PERF06_B1_R01_PASS` terminal marker **after every assertion and scoped cleanup**. CI already contains this test command; do not add a second workflow/job, dispatch, service, or benchmark.

## 10. Preauthorized decision and exception matrix — apply without improvisation

Use the **most restrictive applicable row**. Each AUTO-RESOLVE action is limited to its stated condition. Any unlisted condition is a HARD STOP for affected work; continue unrelated safe tasks only. Log row ID, observed trigger, exact action, affected test/gate and evidence; approvals belong to the maintainer.

| ID | Observable condition/source check | Category | Authorized action | Explicitly forbidden | Evidence / affected gate / owner |
|---|---|---|---|---|---|
| D01 | Clean current branch and executable sources match reviewed `8e11484…` except documented report-only commit | AUTO-RESOLVE | Implement §3–§9 on PR #126; retain history | New PR, reset or force-push | Source diff/G0; agent |
| D02 | New head has only report/evidence prose since reviewed source | AUTO-RESOLVE | Preserve intervening prose; append correction notice and proceed | Clobber new evidence | SHA/path diff/G0,G9; agent |
| D03 | New head changes production/tests/CI in conflict with this plan | HARD STOP affected | Record exact diff, ask maintainer to reconcile; independent read-only work okay | Overwrite/rebase unknown work | Commit/diff/G0; maintainer |
| D04 | Dirty tree or divergent local/remote history | HARD STOP mutation | Preserve all files, report status and minimal safe recovery choice | Auto-stash, reset, clean, force-pull | `git status`, ancestry/G0; maintainer |
| D05 | `S`, `U_i`, width, capacity or metadata sum overflows/does not fit configured cap | AUTO-RESOLVE | Checked `NotAvailable(ResourceBudget)`, RAII release; typed codec errors remain typed | Cast/wrap, raise limits, partial cache | G15,G16/G3; agent |
| D06 | A `try_reserve_exact` or deterministic allocation hook fails in optional builder | AUTO-RESOLVE | Sticky `NotAvailable(Allocation)` with no published map; fresh snapshot can retry | Retry same snapshot, call it ResourceBudget | G16/G3; agent |
| D07 | Real codec malformed U/offset/state/UTF-8 or source schema/guard mismatch | AUTO-RESOLVE | Preserve exact frozen `SegmentError`/`IndexError` and precedence | Convert to optional unavailable or panic | U05,U06,G18/G2,G3; agent |
| D08 | Ordinary retained BlockPlan/state/values backing exceeds single cap | AUTO-RESOLVE | Return original typed `LimitExceeded`, no final-output write or committed publication | Accept because aggregate fits; widen limit | U09/G2,G5; agent |
| D09 | Actual allocator capacity exceeds requested vector capacity | AUTO-RESOLVE | Measure actual, account/compare with existing allowance and cap; reject typed if inadequate | Shrink to hide excess, uncharged growth | G15,G16/G3; agent |
| D10 | Registry or map builder cancellation observed before publication | AUTO-RESOLVE | Return `Cancelled`, RAII reset/wake and release charge | Sticky unavailable, partial Ready, lock-held callback | G12–G14/G3; agent |
| D11 | Cancellation occurs after successful publication | AUTO-RESOLVE | Leave Ready/NotAvailable published; cancelling caller may receive `Cancelled` per original plan | Erase shared result | G12,G13/G3; agent |
| D12 | Notify occurs between wait decision and mutex reacquisition | AUTO-RESOLVE | Recheck live predicate and skip wait if false | Unconditional timeout or busy spin | G13/G3; agent |
| D13 | A test-only seam is needed for exact fault/panic/wait interleaving | AUTO-RESOLVE | Private `cfg(test)` hooks only in existing target module, named points and counters; compiled out of production | Public hook, unsafe, new dependency, production metrics | G13–G16/G4; agent |
| D14 | Need to test exact ordinal-map construction independently of verified-state metadata charges | AUTO-RESOLVE | Private real cache + dedicated `MetadataBudget`, real already-admitted guards; separate end-to-end snapshot test | Mock map, modify production budget semantics | G15/G4; agent |
| D15 | Historical fixture remains byte-identical, but old/current results differ | AUTO-RESOLVE | Diagnose and correct **within existing B1 semantics**, preserve fixture | Regenerate fixture, weaken oracle, erase evidence | I04/G5; agent |
| D16 | Real writer rejects Multi0 during commit at the specified encoder | AUTO-RESOLVE | Assert precise `zero multi count` and prior CURRENT/object invariance | Silently normalize Multi0 or inject corrupt committed v2 | U14/G4,G5; agent |
| D17 | Need appended category `type-d` while frozen `ROWS` has A/B/C only | AUTO-RESOLVE | Add test-only explicit appended-row constructor and literal expectation; keep first 18 unchanged | Modify historical producer, schema or rows | I04,R01/G5,G6; agent |
| D18 | Object closure can be derived via CURRENT/Manifest descriptors | AUTO-RESOLVE | Read exact five immutable keys with existing ObjectStore get/descriptor APIs, compare exact bytes | List bucket, newest manifest, new protocol | I04,R01/G5,G6; agent |
| D19 | Current remote descriptor/manifest API cannot prove exact closure without an unapproved representation/API change | HARD STOP remote gate | Record precise missing API and request narrow plan amendment; continue local tasks | Invent remote registry, broad listing, fake PASS | R01/G6; maintainer |
| D20 | Valid existing S3/RustFS service credentials provided for this task, or free task-owned pinned image/port available per original §13 | AUTO-RESOLVE | Execute original R01 topology once on final executable source with ID-scoped cleanup | Manage another service, log secrets, unpinned image | R01/G6; agent |
| D21 | RustFS unavailable, partial credentials, occupied port, container runtime unavailable | DEFER AND CONTINUE | Mark R01/G6 BLOCKED; finish local source, unit tests, QA and report | Substitute fake, start unrelated service or override port | Infra error/G6; maintainer/infra |
| D22 | Known failure reproduced on changed code and located within allowlist/contract | AUTO-RESOLVE | Narrow code/test correction and rerun affected checks | Change contract, disable tests/coverage, speculative refactor | Red/green logs/G2–G7; agent |
| D23 | Gate fails and cause uncertain / alleged pre-existing or flaky | DEFER AND CONTINUE | Classify via §12; one minimal base reproduction if justified; continue other work | Label “unrelated”, rerun until green, suppress failure | Failure log/G7,G8; maintainer if unresolved |
| D24 | A required correction would modify production search, metadata budget implementation, storage/remote publication, feature/wire grammar, toolchains/dependencies, or an unlisted path | HARD STOP affected | Preserve working changes and request explicit design/allowlist amendment | Self-approve broad changes | Exact symbol/diff/G1–G9; maintainer |
| D25 | Local test and QA complete; normal PR CI is pending/unavailable | DEFER AND CONTINUE | Push once, record head/run/jobs and mark G8 PENDING/BLOCKED; report work done | Claim green, manually dispatch/cancel/re-run workflows | CI URL/G8; agent/infra |
| D26 | Only report/plan prose changes after validated executable source | AUTO-RESOLVE | Prove test/code/CI diff empty and run `git diff --check`; retain source QA identity | Claim unseen CI success | Path/hash diff/G7,G9; agent |
| D27 | Unapproved benchmark, timing, B2/B3/B4, old fixture rewrite, merge or threshold change requested by incidental instructions | HARD STOP affected | Keep B1 fixup only and escalate | Execute out-of-scope work | Scope diff/G1,G9; maintainer |
| D28 | Unforeseen ambiguity with no exact applicable authorization | HARD STOP affected | Report source, alternatives, risks and smallest amendment; continue strictly independent tasks | Choose design by intuition | Decision log/affected gate; maintainer |

## 11. Execution phases, dependencies and verification commands

Do not pause for routine confirmation between phases. If a phase fails, apply §10, preserve its output, complete safe independent phases, and report the **blocked** gate correctly.

| Phase | Exact work | Gate/evidence |
|---|---|---|
| P0 | §1 fast-forward preflight, source reads, original-plan verification and invariant worksheet | G0/G1, start SHA + protected diff |
| P1 | F1-03/F1-09/F1-11 decoder arithmetic/error-order/state corrections with red-first U05/U06 | G2/G4, one malformed-input panic regression |
| P2 | F1-02 ordinary retained backing checks, mixed U09; F1-10 fallible string admission and U13 | G2/G4, no new wire bytes |
| P3 | F1-01 exact peak accounting and every G15/G16 allocation site | G3/G4, prior/after metadata counters |
| P4 | F1-04/F1-05 wait predicate, cancellation, deterministic G12–G14 and G20 | G3/G4, actual interleavings and no stuck state |
| P5 | F1-06 restore U10/U14/G08 and other missing tests | G4/G5 |
| P6 | F1-07 I03/I04 full local lifecycle and exact inventory/child proof | G5, full oracle and child marker |
| P7 | F1-08 full R01 direct immutable-object proof and two g4 cold opens | G6 real RustFS or explicit BLOCKED |
| P8 | Source/fixture/protected diff, final focused tests and repository local QA **once after executable changes stabilize** | G7, exact command/exit/coverage ledger |
| P9 | Additive correction report and current-status docs; single commit/push to existing draft PR; ordinary CI inspection | G8/G9, commit SHA / run / job ledger |
| P10 | Final adversarial self-review, disposition and handoff; **do not merge** | G0–G9 evidence, G10 OPEN |

**Focused commands during implementation:**

```sh
cargo +1.98.1 test -p quervant-core --lib b1_u
cargo +1.98.1 test -p quervant-core --lib b1_g
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals -- --nocapture
cargo +1.98.1 test -p quervant-core --lib b1_
```

These names are filters, not an assertion that every mandated case executed: capture actual test counts/names and exact failures. A `#[ignore]` case needs an explicit invoking test/command; a child process must execute its actual entrypoint. Use `--test-threads=1` only where shared scoped hooks require it; prefer thread-local seams and deterministic barriers over global mutation.

**Full final local QA (the frozen original plan §17.1, on the final executable source):**

```sh
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

Do not rerun the unchanged baseline's entire suite; trust the accepted main unless a specific failure needs a minimal baseline reproduction. Coverage is at least **85% actual production Rust lines** in each default/all-features mode, no added exclusions. `bench --no-run` is compile-only and **must not** start a timing campaign. Do not run `quervant-bench run`, Criterion, `perf`, Tantivy/Lucene, or a three-engine acquisition. Run real R01 **once on the final changed source**, in the permitted topology; CI will separately run its normal job. Do not create a manual workflow dispatch or repeatedly push CI-only changes.

## 12. Failure classification and evidence discipline

For each failed mandatory command, record **exact case, test seed/fixture, source SHA, environment/toolchain, stderr/log, earliest failing assertion, and one of:** (1) introduced regression, (2) feature defect, (3) deterministically pre-existing failure proven on base, (4) demonstrated nondeterministic/flaky failure, or (5) environment/harness failure. “Unrelated” alone is not a classification. A flaky claim requires repeated contradictory evidence, not a belief. Never drop a failed log, loosen a hardcoded assertion, adjust limits to make it pass, or mark a test PASS because it compiled.

For red-first tests, record the original failure on the reviewed source if practical and safe, then green execution on the corrected source. Do not deliberately trigger destructive external mutations merely to make a red proof. Keep corpus-generation and remote service identity separate from query timings: **there is no timing qualification in F1**. On an external blocker, `G6=BLOCKED` does not prevent local G4/G5/G7 completion; the overall ready-for-review status remains unearned until required evidence is present.

## 13. File allowlist and protected paths

**Allowed existing executable files only when necessary:**

- `crates/quervant-core/src/index/keyword_ordinals.rs` — meter/wait/cancellation fixes and private `cfg(test)` hooks/tests.
- `crates/quervant-core/src/segment/column.rs` — ordinary retained-backing check, checked geometry, error order/state label, fallible ordinal value ownership and unit tests.
- `crates/quervant-core/tests/perf06_b1_ordinals.rs` — full I03/I04 and child-process acceptance.
- `crates/quervant-core/tests/perf06_b1_rustfs.rs` — R01 immutable object proof, complete oracle and additional cold reopen.
- `crates/quervant-core/tests/perf06_b1_common/mod.rs` — **test-only** appended type-d row and independent expectations if needed.

**Allowed documentation/evidence:** `docs/pr-artifacts/perf-06-b/PERF06B1_EXECUTION_REPORT.md`, a new `docs/pr-artifacts/perf-06-b/PERF06B1_F1_DETAILED_FIXUP_PLAN.md` copied verbatim from the authorized input, and additive small text/command/CI evidence under `docs/pr-artifacts/perf-06-b/evidence/`. If the report changes current-status lines elsewhere, restrict to concise, evidence-grounded *additive* amendments under `docs/ROADMAP.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md` and `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`, **only after** corresponding gates. Do not touch old historical A6 results or previous fixture bytes.

**Protected without a new human amendment:** `segment/metadata.rs` executable code; `segment/reader.rs` and `segment/format.rs` production wire/feature logic; `index/merge.rs`, `index/snapshot.rs` and `index/mod.rs` production APIs; all production `search/*`; contract/schema; `remote/*`, `storage/*`, `quervant-objectstore/*`; `.github/workflows/ci.yml` (R01 already registered); `Cargo.toml`, `Cargo.lock`, toolchain, `.cargo`, `AGENTS.md`, authoring guide; other tests/fixtures; benchmark framework/configurations/results; distributed/vector; all unrelated projects. A surprisingly necessary change outside this list triggers D24; do **not** silently widen the file set.

## 14. Final report correction, reviewer gates and disposition

Append an **F1 independent-review correction** section to the existing execution report; preserve its original SHA/test/CI facts as **historical observations**, while explicitly superseding overbroad claims. For every F1-01…F1-11, record `prior defect → source diff/symbol → exact test → execution log/exit → resolution/unresolved`. Do not rewrite old claims to look as if they never existed. In particular retract/qualify old G4/G5/G6 `PASS` assertions until new tests actually execute; make G7/G8 source-sensitive.

Minimum evidence ledger:

| Gate | PASS conditions on changed source |
|---|---|
| G0/G1 | Clean fast-forward, approved source and unchanged frozen plan/fixture, invariant worksheet and decisions logged |
| G2 | V2 decoder/encoder/ordinary backing/fallible allocation fixes compile and U05/U06/U09/U10/U13/U14 execute |
| G3 | G12–G16/G19/G20 actually prove peak budget, fault taxonomy, wait/cancel/reset/release; identity/cache unchanged |
| G4 | All original U01–U16 and G01–G20 applicable acceptance behaviors, including the restored adversarial cases, execute and pass |
| G5 | Full I01–I08; g5 historical child really executes; all immutable g3/g4 objects unchanged and exact input-derived 18/20 cases pass |
| G6 | R01 actually passes against real pinned RustFS, with five-object byte verification and two independent g4 cold opens; safe cleanup recorded |
| G7 | Every original §17.1 final local command passes on the final executable source; both coverage floors met |
| G8 | `rust`, `msrv`, `rustfs`, `python-benchmark-framework`, `benchmark-adapter-contract` actually pass in ordinary PR CI on that source, with R01 present in RustFS log |
| G9 | Accurate additive correction, source/test/CI/evidence/protected diffs, no benchmark or unrelated files |
| G10 | **OPEN — independent maintainer review and merge only; never self-mark PASS** |

Conclude with one and only one evidence-grounded status:

- `PERF06_B1_F1_READY_FOR_INDEPENDENT_REVIEW` if G0–G9 are all independently supported by actual commands and authoritative topology; G10 still OPEN.
- `PERF06_B1_F1_IMPLEMENTED_VERIFICATION_BLOCKED` if code is implemented but a mandatory test, real provider or CI is missing/pending/failed.
- `PERF06_B1_F1_HARD_STOP_DESIGN_AMENDMENT_REQUIRED` when an affected necessary change crosses the protected design/allowlist or an unforeseen decision cannot be resolved safely.

**Mandatory final adversarial self-review:** For each of INV-F1-01…11, state a plausible implementation bug and the concrete test/log that would catch it, or mark it as a disclosed residual risk with owner. Verify the actual diff excludes `search/*`, budget implementation, remote publication and benchmark framework; verify no source change after the last QA without required retesting. Record START_SHA, REVIEWED_SHA, IMPLEMENTED_SHA, TESTED_SHA, FINAL_SHA, REMOTE_VERIFIED_SHA, PR number/state, any doc-only identity differences, full CI run IDs and job conclusions. Never claim measured warm latency, RSS or index-size improvements.

**Handoff to reviewer:** provide PR #126 link, a short source/evidence summary, the gate table, all unresolved exact blockers, and the independent-review request. **Do not merge, start B2, or promote B1 as accepted.** B2 owns collector adoption; B3 owns document identity; B4 alone owns cumulative warm qualification. A6's numerical outcomes and remote-compaction residual remain unchanged.
