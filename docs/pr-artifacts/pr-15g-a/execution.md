# PR 15G-A execution record

**Status:** `IMPLEMENTED_NOT_ACCEPTED` — code, tests and local QA pass; performance
and real-RustFS acceptance are blocked (see `qualification.md`).
**Implementation commit:** `73cbc78441ae9e97f58942a72ccdc4276db4590d`
**Branch:** `dev/pr15g-a-retained-column-geometry`

## What changed

Only the two authorized production files changed, plus tests/tooling/docs:

| Path | Change |
|---|---|
| `crates/quervant-core/src/segment/column.rs` | `ColumnGeometry`, owned/borrowed `GeometrySource`, one shared parser body, metered parser entry point, `into_geometry`, `from_validated_geometry`, `metadata_charge`, `column_geometry_allowance` |
| `crates/quervant-core/src/segment/reader.rs` | retained `column_geometry` in `DecodedMetadata`/`VerifiedSegmentState`, allowance + measured charge, metered eager validation, borrowed dispatch for `open_columns`/`column_value` |
| `crates/quervant-core/src/index/snapshot.rs` | one test-only regression covering admission/zero-cap/one-under fallback; production slot logic untouched |
| `crates/quervant-core/tests/pr15g_a_column_geometry.rs` | real `Index`/writer/`FsDirectory`/snapshot/PIT/concurrency integration |
| `benchmarks/pr15g_a/{run.py,test_run.py,README.md}` | PR 15G-A Quervant-only A/B runner and deterministic unit tests |

No segment format, manifest, schema, query semantics, budget semantics, cache
policy, dependency or public API changed.

## GA-AD contract implementation

- **GA-AD-001.** One `Option<ColumnGeometry>` lives in `VerifiedSegmentState` and
  in `DecodedMetadata`; `from_decoded` moves it without cloning. It is populated
  only on the metered `try_build_cached` path via `into_geometry()`. Unmetered
  `validate`, standalone `SegmentReader::open` and the snapshot fallback still
  parse and discard geometry (`None`). An absent COLUMNS section remains `None`;
  a present zero-column section retains `Some(ColumnGeometry { columns: [] })`.
- **GA-AD-002.** `ColumnReader` keeps its public type/methods but stores one
  `GeometrySource::{Owned,Borrowed}`. `open`/`open_with_doc_count` return owned
  geometry; `open_with_doc_count_metered` charges the actual column count before
  `try_reserve_exact`; `from_validated_geometry` performs no parsing/allocation;
  `into_geometry` moves the owned vector and hard-stops on a borrowed source.
  `blocks_read` remains a query-local `Cell` initialized to zero.
- **GA-AD-003.** `column_geometry_allowance(section_len)` returns `0` below the
  6-byte prefix and otherwise `((len - 6) / 46) * size_of::<ColumnMeta>()` via
  checked `element_bytes`. `decode_allowance` adds it only when COLUMNS exists.
  `ColumnGeometry::metadata_charge()` measures actual `Vec` capacity. Metering,
  capacity, cap and finalization failures release the candidate and take the
  fully validating uncached path; genuine corruption propagates unchanged.
- **GA-AD-004.** `decode_metadata` uses the metered parser when a meter exists
  and the unchanged unmetered parser otherwise. `open_columns` borrows the
  retained table when present, else calls the original parser. `column_value`
  is routed through `open_columns`, so direct and unified query access share the
  same dispatch. Return types and lifetimes are unchanged.
- **GA-AD-005.** Eager whole-geometry validation still runs on first verified
  state construction. Slot CAS, mutex/condvar, failure reset, poison handling,
  RAII guards, metadata release, PIT masks and snapshot isolation are untouched.

## Test-to-requirement mapping

Unit tests (all PASS):

- `segment::column::tests::u01` … `u12` — owned/borrowed value and shape parity,
  multi/block behavior, field order, zero-column section, corrupt state tag,
  truncation/type/doc-count errors, move/borrow identity, allowance vs actual
  charge, overflow/allocation bounds, repeated borrow identity and independent
  counters.
- `segment::reader::column_geometry_tests::u08,u09,u12,u13,u14,u15` — zero-cap,
  exact/one-under allowance, repeated `open_columns`, direct/standalone/reader
  parity, corrupt-container propagation, `Send + Sync`.
- `index::snapshot::verified_state_cache::g5_01` — real snapshot admission,
  zero-cap and one-under fallback with cached/uncached column value parity.

Integration tests (all PASS):

- `ga_i01` memory index/writer/snapshot; term, absent, range, explicit column
  sort; column parity against a fresh `SegmentReader::open`.
- `ga_i02` real `FsDirectory` commit, handle drop, cold reopen and
  byte-identical committed segments.
- `ga_i03` pinned old snapshot vs delete/insert/commit/new snapshot.
- `ga_i04` four concurrent query threads over one multi-segment snapshot.
- `ga_i05` small metadata cap repeated fallback and guard drop.
- `ga_i06` corrupt rebuilt COLUMNS geometry with valid envelope digests fails
  closed with the typed `FieldTypeMismatch`.

Runner tests (all PASS): `GA-B01..B14` in `benchmarks/pr15g_a/test_run.py`
(16 tests; B01–B14 plus valid-pair/sanitizer shape coverage).

## Local QA evidence

All commands were run from the workspace root at implementation commit
`73cbc78` on the environment in `preflight.md`. Logs are under the git-ignored
`target/pr15g-a/qa/`.

| Gate | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 118 suites, 2251 passed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 118 suites, 2255 passed, 75 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 118 suites, 2251 passed, 10 ignored |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 118 suites, 2255 passed, 75 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 92.62% line coverage (all workspace production code) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `python3 -m unittest discover -s benchmarks/pr15g_a -p 'test_*.py' -v` | PASS — 16 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests |
| `python3 -m unittest discover -s benchmarks/pr15f -p 'test_*.py' -v` | PASS — 54 tests |
| `cargo test -p quervant-core --test pr06_local_integration` | PASS — 13 passed, 3 ignored |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | PASS — 5 passed |
| `cargo test -p quervant-core --test pr15e_b1` | PASS — 17 passed |
| `cargo test -p quervant-core --test pr15g_a_column_geometry` | PASS — 6 passed |
| `git diff --check` | PASS |

Coverage detail: `segment/column.rs` 94.37% lines, `segment/reader.rs` 89.89%
lines. The ignored workspace tests are the pre-existing real-RustFS suites that
require a running service.

## Deviations and stops

- None of the production scope matrix escalated: no third production file, no
  new dependency, no lockfile change, no format/API change.
- Two tests initially failed during development and were fixed **inside the
  approved model** (GA-D18): an incorrect expected `blocks_read` count in two
  column tests, and an integration corruption test that initially tripped the
  envelope digest; it now rebuilds the container with valid digests so the
  column validator is exercised.
- `into_geometry` deliberately panics on a borrowed source; a `#[should_panic]`
  test records that call-site invariant.

## Acceptance fixup (F15G-A-01/02/03)

**Original reviewed SHA:** `b120f9f8d63901cd4bdc9bb83fb4462a5b11d6ad`
**Scope:** tests, one CI invocation and evidence only. No production statement in
`segment/column.rs`, `segment/reader.rs` (outside `#[cfg(test)]`) or
`index/snapshot.rs` (outside `#[cfg(test)]`) changed.

### F15G-A-01 — explicit limit and observable fallback

- `ga_i05_reduced_limit_survives_public_reopen_and_queries` now reopens with
  `Index::open_with_limits(..., limits.clone())`, preserving the 64-KiB
  `max_snapshot_bytes` value, and adds exact `n` range and `n ASC` query parity.
  It is labelled as public limit-propagation/correctness evidence, not as a
  private cache-miss witness.
- `g5_02_private_zero_exact_and_one_under_observable_fallback` proves zero,
  exact and one-under candidate allowances with four repeated one-under rounds,
  `slot_is_ready`, `verification_count`, `metadata_used`, retained geometry
  identity, independent `blocks_read` counters, value parity and final charge
  release.
- `g5_03_reopened_index_with_exact_resident_cap_uses_fallback` drives the real
  public path: `Index::create_with_limits` → writer insert → commit → reopen with
  `max_snapshot_bytes == encoded resident bytes` → four observed fallback reads
  with no retained geometry, no charge, no Ready slot and no verification.

### F15G-A-02 — digest-valid malformed COLUMNS through both constructors

- `u18_valid_envelope_bad_columns_rejected_by_metered_candidate` rebuilds the
  segment with `ContainerBuilder`, preserving every required/optional feature
  (including the original duplicate baseline pair by skipping exactly one
  builder-supplied occurrence), all section flags/aux values and every
  non-COLUMNS body. It corrupts only COLUMNS byte 10 (the first type tag) and
  re-parses the container first to prove all digests are valid.
- Standalone `SegmentReader::open` and metered `VerifiedSegmentState::build_cached`
  both return `FieldTypeMismatch`; `Ok(None)`/`Ok(Some(_))` are explicit failures.
  `budget.used()==0` after the error, and the same budget handle admits the
  pristine bytes, retains geometry, then releases on drop.
- The existing real-boundary `ga_i06_corrupt_column_geometry_fails_closed` test
  remains and passes separately.

### F15G-A-03 — real RustFS GA-I07

- Added `crates/quervant-core/tests/pr15g_a_rustfs.rs`, an ignored S3-feature
  test using the existing `S3ObjectStore`, `RemoteIndex`, `RemoteKeyPrefix` and
  `UnifiedSearcher` APIs.
- Fixture: `a=(alpha,30)`, `b=(beta,10)`, `c=(alpha,20)`. After committing
  generation 1 it deletes the disposable local workspace and cold-reopens.
  Assertions: exact sort `["b","c","a"]`, range `["c","a"]`, direct column map
  `{a:30,b:10,c:20}`, and no additional provider requests on warm reread.
- Added exactly one invocation to the existing `rustfs` workflow job.
- The test compiled with `--all-features --no-run` and was **actually executed
  locally against the pinned RustFS image digest**
  `sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
  (local container, CI-equivalent test credentials). Hosted exact-head execution
  remains pending.

### GA-I08 execution

Using the same local pinned RustFS service, the existing real-boundary tests
were executed:

- `pr13_remote_proxy` — 7 passed (including H06, H07, H09).
- `pr13_crash_rustfs k0` — 5 passed (K01–K05, including K05).
- `pr13_crash_rustfs k05` — 10/10 repeated runs passed, matching the CI repetition.

### Fixup local QA

| Gate | Result |
|---|---|
| Focused reader/snapshot/integration suites | PASS — 7 / 41 / 6 tests |
| `pr15c_a_segment_state` / `pr15e_b1` / `pr06_local_integration` | PASS — 5 / 17 / 13 (3 ignored) |
| `pr15g_a_rustfs --no-run` | PASS (BUILDABLE; execution recorded separately) |
| Stable + MSRV fmt/clippy (default/all-features) | PASS |
| `cargo test --workspace --all-targets` stable/MSRV | PASS — 2254 passed, 10 ignored, 119 suites |
| All-features workspace tests stable/MSRV | PASS — 2258 passed, 76 ignored, 119 suites |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 92.65% |
| `cargo doc` / `cargo bench --workspace --no-run` | PASS |
| Script / PR 15D / PR 15F Python suites | PASS — 108 / 83 / 54 |
| `git diff --check`, PR 15F report JSON and SHA-256 | PASS — hash unchanged |
| GA-I07 / GA-I08 local real RustFS execution | PASS (hosted exact-head pending) |
| Performance P01–P04 | BLOCKED_OPERATOR — no timed run |

Logs: `target/pr15g-a/fixup/` and `target/pr15g-a/fixup/qa/`.
