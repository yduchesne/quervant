# PR 13 — review fixup correctness gate

**Inspected HEAD:** `fecb95ae6670ad4f2c1098026aeea637eddf25f8` on `dev/rust-fs`
(`main` base `653b412e0e7df8efe18602479b661629427fab57`). Clean worktree.

## Verified implementation boundaries (from source, not memory)

- `crates/quervant-core/src/search/typed.rs::compile_query_inner` implements
  `JsonPathExists`, `JsonPathEquals`, `GeoBoundingBox`, `GeoRadius` and
  `GeoPolygon`; `distance_from` GeoPoint sort is implemented
  (`build_distance_table`, sort field validation). `LexicalSearcher` rejects
  these; `TypedSearcher` is the correct executor.
- `JsonPathExpr::parse` accepts `$`, `.member`, `[index]`, `[*]`; `is_concrete`
  gates equality. `JsonScalar::from_field_value` accepts Bool/I64/U64/F64/
  Text/Keyword and returns `None` for others (e.g. explicit null → typed
  `unsupported("jsonpath_equals_type")`).
- `GeoBoundingBox::new(west,south,east,north)` allows `west > east`
  (antimeridian). `GeoRadius::new(center, meters)` rejects zero/negative/
  non-finite. `GeoPolygon::new(outer, holes)` validates ring size.
- `TypedSearchRequest { query, sort, top_k, after, primary_time_field }`;
  `TypedSearchResponse { hits, total_hits, next_cursor, … }`. `SortField {
  field, direction, missing, multi, distance_from }`.
- K05 is currently absent from `pr13_crash_rustfs.rs`; H02/H09 are in-process
  regression evidence only.
- Real-provider tests use `let Some(env) = env() else { return; };`, i.e. they
  silently pass when explicitly invoked without RustFS.
- `remote/transfer.rs` uses `TokioSleeper` (real elapsed time) only under the
  `s3` feature; the non-`s3` `ImmediateSleeper` only yields.

## Invariant to test map

| ID | Invariant | Positive | Negative |
|---|---|---|---|
| I01 | JSON typed queries exact after cold remote reopen | O04A–O04D | wildcard equality typed error; type mismatch empty |
| I02 | Geo predicates exact with documented boundaries | O05A–O05F | antimeridian, hole, invalid shape |
| I03 | GeoDistance sort/search-after identical across backends | O06A–O06C | ties key-break, pagination no gaps |
| I04 | PIT immutable through commits and reopen | O07A–O07C | delete/upsert no leak |
| I05 | Kill during partial ranged fill exposes no verified entry | K05A–K05C | orphan reconciliation, fresh recovery |
| I06 | Explicit real-RustFS acceptance fails closed | E01–E05 | unset/empty/unreachable/bad creds |
| I07 | Real elapsed-time retry for every supported production build | T07–T10 | cancel during sleep; non-transient no sleep |
| I08 | CI status on final SHA runs real boundary tests | CI01–CI05 | skipped suite / wrong SHA |
| I09 | Large-segment resource ceilings | P05–P07 | 16/64 MiB stress |
| I10 | Deferrals explicit, never PASS | D01–D03 | V08 not DONE |

## Scope decisions

- **O04/O05 are mandatory**: both operator families are implemented and tested
  here; they are not PR 14 deferrals.
- **O06 is supported** (`distance_from`); tested where the existing API can
  express it. If a specific variant (e.g. search-after interaction) cannot be
  expressed, it is dispositioned explicitly rather than marked PASS.
- **K05** requires a genuine child-process crash after at least one staged
  chunk is written. If the post-stage-write boundary cannot be observed without
  a production storage API change, STOP.
- **Retry timer**: a real elapsed-time sleeper must exist for non-`s3`
  production builds without an unconditional Tokio runtime, or the runtime
  contract must be explicitly constrained. Falls back to a STOP decision if no
  MSRV-1.85-compatible runtime-neutral timer exists.
- **CI**: this environment cannot push or observe GitHub Actions; reported
  BLOCKED rather than PASS.

## Counterexample challenges

| Transition | Counterexample asserted |
|---|---|
| JSON path equality with wildcard | typed `UnsupportedOperator`, no silent scan |
| JSON null vs missing | null exists; missing does not |
| Geo antimeridian bbox | wraps east/west; origin excluded |
| Geo polygon hole | point inside hole excluded |
| Kill mid-fill | final cache key absent; CURRENT unchanged |
| Missing RustFS env on explicit `--ignored` | nonzero failure, no silent skip |
| Transient twice | real elapsed ≥ 100 ms; 3 attempts |
| Non-transient | 1 attempt, no sleep |
| V08 | DEFERRED, not PASS |
