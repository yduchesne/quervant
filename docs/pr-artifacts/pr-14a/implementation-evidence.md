# PR 14A — Public PIT-bound batch search-after: implementation evidence

**Status:** IMPLEMENTED — local and workspace qualification PASS; real-RustFS
14B qualification, final-SHA CI and human review pending. **Not accepted/DONE.**
The implementation commit above passed every local gate; CI could not be started
because the local GitHub CLI token is invalid and the branch has no PR.

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
