# PR 10 Amendment 01 — Validation Report

**Amendment:** snapshot binding exhaustion correctness closure.
**Branch:** `dev/temporal-retrieval`.
**Amendment commit:** `bd3e16b1377014b6565bede5dcc0595a1d98cc5d` (`fix(core): prevent snapshot cursor binding identifier wraparound`), pushed to `origin/dev/temporal-retrieval`.
**Parent baseline HEAD:** `05c8d89ac6f364ff4132bb4ac33788cf8fc38042` (PR 10 implementation).
**Merge-base against `main`:** `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7`.
**Toolchains:** stable (1.98.1) and MSRV `1.85.0`, both installed.
**Tree:** all amendment edits applied; production change confined to
`crates/quervant-core/src/index/snapshot.rs`.

The amendment commit is `bd3e16b1377014b6565bede5dcc0595a1d98cc5d`; the command
results below were all run on the final amendment working tree whose committed
content is exactly that commit.

## Command matrix

| Command | Toolchain | Result | Evidence |
|---|---|---|---|
| `cargo fmt --all -- --check` | stable | **PASS** | no diff |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | **PASS** | no diagnostics |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | **PASS** | no diagnostics |
| `cargo test -p quervant-core --lib snapshot_binding` | stable | **PASS** | 8 passed, 0 failed |
| `cargo test -p quervant-core --test pr10_cursor` | stable | **PASS** | 4 passed, 0 failed |
| `cargo test -p quervant-core --test pr10_integration` | stable | **PASS** | 11 passed, 0 failed |
| `cargo test -p quervant-core --test pr10_properties` | stable | **PASS** | 9 passed, 0 failed |
| `cargo test --workspace --all-targets` | stable | **PASS** | 1328 passed, 0 failed, 7 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | **PASS** | 1328 passed, 0 failed, 7 ignored |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | **PASS** | **91.66% line**, 87.50% function, 91.31% region |
| `cargo doc --workspace --no-deps` | stable | **PASS** | generated |
| `cargo bench -p quervant-core --no-run` | stable | **PASS** | all bench targets build |
| `bash benchmarks/scripts/test-scripts.sh` | shell | **PASS** | 33 passed, 0 failed |

Workspace passed count increased from 1320 (pre-amendment) to 1328 (+8 allocator
tests). Both toolchains now agree at 1328; the earlier stable/MSRV one-test
discrepancy is no longer present.

## A1 test traceability

Test states: **written**, **executed**, **passed**. All amendment tests were
written and executed in this change; no result is carried over from the original
PR 10 validation report.

| Test | Location | Assertion | State |
|---|---|---|---|
| A1-T01 `snapshot_binding_allocates_monotonically` | `index/snapshot.rs` unit | `1,2,3`, counter `4` | written / executed / passed |
| A1-T02 `snapshot_binding_near_exhaustion` | `index/snapshot.rs` unit | `MAX-2, MAX-1`, counter `MAX` | written / executed / passed |
| A1-T03 `snapshot_binding_exhaustion_after_last_success` | `index/snapshot.rs` unit | last success then exact panic, sentinel unchanged | written / executed / passed |
| A1-T04 `snapshot_binding_rejects_reserved_and_exhausted` | `index/snapshot.rs` unit | `0` and `MAX` panic, unchanged | written / executed / passed |
| A1-T05 `snapshot_binding_concurrent_uniqueness` | `index/snapshot.rs` unit | 8×1000 unique IDs `1..=8000`, counter `8001` | written / executed / passed |
| A1-T05b `snapshot_binding_concurrent_near_exhaustion` | `index/snapshot.rs` unit | 4 successes `MAX-4..MAX-1`, 4 exact panics, counter `MAX` | written / executed / passed |
| A1-T06 `snapshot_binding_distinct_snapshot_identity` | `index/snapshot.rs` unit | nonzero unequal IDs, equal generation/view | written / executed / passed |
| A1-T07 `snapshot_binding_arc_clone_identity` | `index/snapshot.rs` unit | shared ID, global counter unchanged by clone | written / executed / passed |
| A1-T08 `typed_cursor_origin_snapshot_regression` | `tests/pr10_cursor.rs::t19_full_pagination_no_gaps` (reused) | continuation on same snapshot, no gaps/dupes | existing / executed / passed |
| A1-T09 `typed_cursor_different_snapshot_regression` | `tests/pr10_cursor.rs::t23_distinct_snapshot_same_generation_rejected` (reused) | `CursorPitMismatch` for distinct snapshot, same generation/view | existing / executed / passed |
| A1-T10 `snapshot_construction_regression` | `index/snapshot.rs` existing reader-budget/out-of-range/decoder tests; PR 9/10 suites | masks/generation/counts unchanged | existing / executed / passed |

## Independent oracle used

- Sequential IDs compared against the literal range `1..=8000`, not another
  allocator call.
- Boundary assertions use the §3 transition table and explicit sentinel checks;
  the `0`/`MAX` cases use fresh local `AtomicU64` instances.
- Concurrent tests sort and deduplicate returned IDs, check exact length and
  endpoints, and inspect the final atomic value.
- Panic assertions inspect the payload `&str`/`String` and require the exact
  message `snapshot binding identifier space exhausted`.
- No test mutates the global `NEXT_SNAPSHOT_BINDING`; A1-T07 only reads it.

## Topology

- Allocator tests are pure deterministic unit tests on local atomics; threads are
  joined on every path, including panic paths.
- Cursor/snapshot regression ran through the existing PR 10 integration harness
  with real `MemoryDirectory`, real writer commit/reopen and immutable snapshots.
- No fake `ReaderSnapshot` or test-only cursor implementation was used.
- No RustFS/distributed topology is required; this amendment does not touch I/O.

## Coverage (amended files)

| File | Line coverage |
|---|---|
| `index/snapshot.rs` | 89.71% |
| **Workspace total** | **91.66%** |

No coverage exclusion was added or changed.

## Unresolved failures

None. No gate failed; no STOP condition was triggered. No command is reported as
PASS without having been executed on the final amendment tree.
