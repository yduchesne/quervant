# PR 14A — Public PIT-bound batch search-after: implementation evidence

**Status:** IMPLEMENTED — local and workspace qualification PASS; real-RustFS
14B qualification, final-SHA CI and human review pending. **Not accepted/DONE.**
The implementation commit above passed every local gate; CI could not be started
because the local GitHub CLI token is invalid and the branch has no PR.
Correction 02 now resolves the unified JSON-path ordering gap documented below.

## Base and scope

| Item | Value |
|---|---|
| Branch | `dev/pr14a-pit-public-cursor` |
| Base / fresh `main` | `8517499cea67c865958ed7deddbd8c966c6dcc83` |
| Host | Linux x86-64; stable `rustc 1.98.1`; MSRV `rustc 1.85.0` |
| Implementation commit | `9c7215f9758e200e47a84280673709fdd6428a3d` |
| Pushed branch | `dev/pr14a-pit-public-cursor` (GitHub PR not created: local credential invalid) |
| Scope | Public PIT-bound batch continuation, explicit handle authority, full-tuple cursor bridge, expiry/query/sort/snapshot validation, budget accounting, local `FsDirectory` oracle tests |

No segment, manifest, `CURRENT`, `PitHandle`, remote protocol or distributed
format changed. Public cursors remain process-local, in-memory Rust values and
are not serializable. No PIT registry was introduced.

## Implemented surface

- `contract/result.rs`: private Eq-safe `CursorAtom` and
  `CursorContinuationV1`; `Cursor` retains `pit`, `sort`, `last_key`,
  `expires_at` and adds an optional private continuation. `Cursor::new` remains
  source-compatible and creates a legacy position-only cursor.
- `search/batch_cursor.rs`: exhaustive `SortValue ↔ CursorAtom` conversion,
  exact IEEE-754 score bits, typed rejection of unsupported/non-finite values,
  legacy-cursor rejection, and one deterministic logical-size formula for
  response/memory accounting.
- `search/batch.rs`: new public
  `execute_batch_pinned(&PitHandle, ..., now, cursor_deadline)`; the handle is
  the only snapshot authority. The naked `execute_batch(snapshot, ...)` entry
  rejects every PIT/cursor-bearing request with
  `InvalidBatch(PinnedContextRequired)` before running slots. Shared PIT,
  inherited per-slot PIT, deadline admission, expiry, and no-renewal rules are
  enforced.
- `contract/batch.rs`: crate-private pinned per-slot validation lets a cursor
  inherit the shared PIT without weakening legacy `QueryRequest::validate`.
- Cursor payload bytes are charged once in `BatchResponseBytes` and once in
  retained `BatchMemoryBytes`; failed slots release their retained reservations.

## Acceptance trace

| ID | Test | Result |
|---|---|---|
| T01 | `t01_naked_snapshot_rejects_pit_and_cursor_before_slots` | PASS |
| T02 | `t02_two_field_pages_are_exact_and_metamorphic` | PASS |
| T03 | `t03_typed_tuples_missing_null_keyword_time_ip_and_negative_zero` | PASS |
| T04 | `t04_relevance_pages_match_full_unpaginated_search_and_score_bits` | PASS |
| T05 | `t05_mixed_filter_aggregation_and_projection_are_page_size_invariant` | PASS |
| T06 | `t06_wrong_handle_and_snapshot_binding_fail_without_fallback` | PASS |
| T07 | `t07_query_and_sort_mismatch_fail_typed` | PASS |
| T08 | `t08_three_slot_batch_isolates_cursor_failure_in_input_order` | PASS |
| T09 | `t09_retained_pit_survives_mutation_refresh_commit_and_compaction` | PASS |
| T10 | `t10_expiry_boundaries_and_no_renewal` | PASS |
| T11 | `t11_response_and_memory_budgets_include_cursor_exactly_once` | PASS |
| T12 | `search::batch_cursor::tests::b01..b04` | PASS — 4 unit tests |
| T13 | `t13_cancellation_after_prior_success_is_slot_local_and_emits_no_cursor` | PASS |

Local integration uses a real `FsDirectory`, two committed segments, a retained
`Index::pin()` handle, and the actual public `execute_batch_pinned` path.
Expected ordering is a test-owned table over `k00`–`k11`; the production
comparator is never used to compute it.

## QA evidence

| Gate | Result |
|---|---|
| `cargo test -p quervant-core --all-features --test pr14a_public_cursor` | PASS — 12 tests |
| `cargo test --workspace --all-targets` | PASS — 1996 passed, 0 failed, 9 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 2000 passed, 0 failed, 67 ignored |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2000 passed, 0 failed, 67 ignored |
| Stable/MSRV fmt and Clippy (`-D warnings`) | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.21% lines** (47507 lines, 4174 missed) |
| `cargo doc`, `cargo bench --no-run`, benchmark scripts, `git diff --check` | PASS |

Ignored tests are existing real-RustFS suites; they were not executed for 14A.
14B owns real-provider compound/PIT/fault/reopen qualification.

## Residual risks

- Cursor continuations are process-local and invalid after process exit or
  dropping the issuing `PitHandle`; there is no serialization/restart promise.
- Snapshot binding is checked by the existing unified comparator, but different
  live handles necessarily have different PIT ids; the wrong-handle case is
  tested through that id boundary.
- Memory exact-limit evidence uses the real cumulative meter boundary because
  the peak includes executor candidate/projection retention in addition to the
  cursor payload. Response-byte exact/one-over uses the documented cursor size
  formula.
- 14B/14C remain incomplete; PR 15 and v0.1 release are not claimed.

## Correction 01 — JSON sort-path cursor accounting

**Base:** driven from pushed PR 14A head `52c811ad19b176660622dbb781e97e2b01e3ae2c`.
**Correction commit:** `def011fef1961459820c88f0f3fed2404ffc8f3f`.
**Production file:** `crates/quervant-core/src/search/batch_cursor.rs` only.

The previous fixed 64-byte JSON-path allowance was replaced by a checked,
componentwise logical charge:

```text
path_charge = 24 + 24 * segment_count + sum(UTF-8 member byte lengths)
```

`JsonPathSegment::Member` is charged by `str::len()` bytes; `Index` and
`Wildcard` each incur a segment base; root `$` charges 24. All additions use
checked arithmetic and propagate `None` on overflow. `cursor_logical_bytes`
remains the single charge consumed by both response-byte and retained-memory
meters; `search/batch.rs` was not changed.

### Correction test evidence

| ID | Test | Result |
|---|---|---|
| T01 | `search::batch_cursor::accounting_tests::t01_path_root_charges_base` | PASS — `$`=24, `$.x`=49 |
| T02 | `t02_path_long_member_is_not_fixed_64` | PASS — 256-byte member=304, 1024=1072; cursor delta=768 |
| T03 | `t03_path_unicode_bytes` | PASS — `$["é"]`=50 |
| T04 | `t04_path_segments_all_metered` | PASS — 4 segments + 2 member bytes=122 |
| T05 | `t05_path_checked_arithmetic` | PASS — overflow returns `None` |
| T06 | `t06_sort_and_cursor_charge_grows_with_path` | PASS — 16→256 member delta=240, including multi-field sort |
| T07 | `t07_json_path_long_member_response_boundary` | PASS — cursor response accounting and numeric JSON ordering (resolved by Correction 02) |
| T08 | `t08_json_path_long_member_memory_boundary_and_sibling_rollback` | PASS — memory boundary and sibling rollback, with numeric JSON ordering |
| T09 | `t09_non_json_cursor_regressions_remain_unchanged` | PASS |

### Historical limitation — resolved by Correction 02

`UnifiedSearcher` (the executor behind public batch search) does not evaluate
`SortField::json_path` values; it leaves the tuple `Missing`, so documents tie
and fall back to the key tie-break. `TypedSearcher` does evaluate JSON paths, but
changing the unified executor is explicitly outside CA-06 and this accounting
correction. The real-boundary tests therefore validate cursor accounting with a
long path present, but do **not** claim numeric JSON-path ordering acceptance.
Recorded behavior with values `k00=30,k01=10,k02=20` is key order
`k00,k01,k02`; desired numeric order would be `k01,k02,k00`. This is a
pre-existing executor gap requiring a separate approved correction; it is not
caused by the accounting change and is not silently marked PASS.

### Correction QA

Local gates were rerun after the correction: `cargo fmt`, stable/MSRV Clippy,
workspace default/all-features/MSRV tests, `pr14a_public_cursor`,
`pr14_storage_vertical`, coverage, docs, benchmark build/scripts and
`git diff --check`. Exact counts and coverage are recorded in the final report
and refreshed below when final gates complete.

**Status:** cursor accounting implemented and locally qualified. The numeric
JSON-path ordering limitation discovered here was resolved by Correction 02;
CI/human review remain pending and PR 14A is not accepted.

### Correction 01 final local gates

| Gate | Result |
|---|---|
| `cargo test -p quervant-core --all-features --test pr14a_public_cursor` | PASS — 15 tests |
| `cargo test -p quervant-core --lib --all-features batch_cursor` | PASS — 10 tests |
| Workspace default tests | PASS — 2005 passed, 0 failed, 9 ignored |
| Workspace all-features tests | PASS — 2009 passed, 0 failed, 67 ignored |
| MSRV all-features tests | PASS — 2009 passed, 0 failed, 67 ignored |
| Stable/MSRV fmt and Clippy (`-D warnings`) | PASS |
| Coverage | PASS — **91.25% lines** (47587 lines, 4163 missed) |
| `pr14_storage_vertical` local (non-ignored) | PASS — 3 passed, 9 ignored |
| `cargo doc`, bench build, 33 script tests, `git diff --check` | PASS |

Ignored real-RustFS tests remain 14B work. The numeric unified JSON-path sort
ordering limitation was resolved by Correction 02.

## Correction 02 — unified JSON-path ordering

**Base:** pushed Correction 01 head `3f87ea24e5e47517dd189f5a4b87f792cc40a4f8`.
**Correction commit:** `9fb90418f89cc0a67370124b78a6ad8306cc3bbd`.

### Production change

- `search/typed.rs`: `json_sort_value` visibility changed to `pub(crate)` only;
  algorithm, selector, typed errors and `ScanGuard` charging unchanged.
- `search/unified.rs`: in the existing per-hit `collect_mixed` loop, the tuple
  returned by `sort_tuple_for_doc` is now mutable. For each `json_path` sort
  field, the shared `typed::json_sort_value` is invoked through
  `TypedCharge`/`ScanGuard::shared`, and the completed tuple is installed before
  `SelectedHit`, heap comparison, continuation filtering and cursor creation.
- No comparator, PIT, cursor format, accounting formula, JSON decoder, storage,
  geo algorithm or public API changed.

### J01–J12 evidence

| ID | Test | Result |
|---|---|---|
| J01 | `j01_unified_json_path_numeric_ascending` | PASS — `k01,k03,k02,k06,k00,k05,k04` (old code produced key order) |
| J02 | `j02_json_path_descending_and_page_sizes` | PASS — descending and top_k 1/2/3/20 |
| J03 | `j03_second_field_json_sort_and_tie_key` | PASS — second JSON field plus key tie-break |
| J04 | `j04_json_missing_null_ascending_and_descending` | PASS — null before missing under missing-last |
| J05 | `j05_json_wildcard_min_max_and_selector_requirement` | PASS — Min/Max and missing-selector typed failure |
| J06 | `j06_mixed_lexical_json_sort_and_aggregation` | PASS — lexical+JSON predicate, stable aggregation |
| J07 | `t07_json_path_long_member_response_boundary` (public pinned top_k=1 pages) | PASS — no duplicate/omission, terminal cursor |
| J08 | `j08_json_pit_stable_across_mutation_and_compaction` | PASS — old PIT order stable; new PIT sees updated/deleted/inserted state |
| J09 | `j09_bad_json_sort_fails_typed` | PASS — invalid JSON sort field is a typed per-slot failure |
| J10 | `j10_json_work_limit_exact_and_one_under` | PASS — real total-work exact/one-under boundary |
| J11 | `j11_json_three_slot_failure_isolated` | PASS — three outcomes, middle expired cursor isolated |
| J12 | `j12_geo_distance_and_plain_column_sort_regression` | PASS — geo-distance order and columnar sort unchanged |

`pr14a_public_cursor` now has **26 passing tests**; `batch_cursor` unit tests
remain unchanged except Correction 01 accounting tests.

### Resource-bound assessment

`typed::JsonAccess::occurrences` is used unchanged. Indexed JSON paths are
bounded by existing `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT` (65,536),
`MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT` (8,000,000), path depth/member limits,
and `SearchLimits::max_typed_scan_docs`/typed work limits. The shared evaluator
charges each occurrence through `ScanGuard` against the existing
`MixedWorkMeter`. It still calls `occurrences(..., None)`, so the temporary
occurrence `Vec` is not added to `SlotMemoryScope`; this is the same pre-existing
typed-executor behavior, not a new unbounded path. It is a residual risk
(logical work is metered; temporary occurrence allocation is bounded by JSON
limits but not precisely RSS-accounted). No new meter or memory adapter was
introduced.

### Correction 02 final local gates

| Gate | Result |
|---|---|
| `cargo test -p quervant-core --all-features --test pr14a_public_cursor` | PASS — 26 tests |
| Workspace default tests | PASS — 2016 passed, 0 failed, 9 ignored |
| Workspace all-features tests | PASS — 2020 passed, 0 failed, 67 ignored |
| MSRV all-features tests | PASS — 2020 passed, 0 failed, 67 ignored |
| Stable/MSRV fmt and Clippy (`-D warnings`) | PASS |
| Coverage | PASS — **91.27% lines** (47599 lines, 4154 missed) |
| `pr14_storage_vertical` local (non-ignored) | PASS — 3 passed, 9 ignored |
| `cargo doc`, bench build, 33 script tests, `git diff --check` | PASS |

Ignored real-RustFS tests remain 14B work and are not claimed as executed.
