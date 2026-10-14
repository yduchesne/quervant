# PR 10 Amendment 02 — Validation Report

**Amendment:** bound transient aggregation memory (acceptance finding A1).
**Branch:** `dev/temporal-retrieval`.
**Parent baseline HEAD:** `a132325fef9df49b05bff7f0ed0bb086fcf72ee5`.
**Merge-base against `main`:** `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7`.
**Toolchains:** stable (1.98.1), MSRV `1.85.0`, and the exact CI compiler `1.98.1`.
**Tree:** clean at Phase 0; all amendment edits applied before the commands below.

The amendment commit is created on `dev/temporal-retrieval` after these commands;
its SHA is reported in the handoff message. All results below were produced on the
final amendment working tree.

## Command matrix

| Command | Toolchain | Result | Evidence |
|---|---|---|---|
| `cargo fmt --all -- --check` | stable | **PASS** | no diff |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | **PASS** | no diagnostics |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | **PASS** | no diagnostics |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | 1.98.1 | **PASS** | exact CI command |
| `cargo test -p quervant-core --lib` | stable | **PASS** | 441 passed, 0 failed |
| `cargo test -p quervant-core --test pr10_groups` | stable | **PASS** | 5 passed |
| `cargo test -p quervant-core --test pr10_distinct` | stable | **PASS** | 5 passed |
| `cargo test -p quervant-core --test pr10_frequency` | stable | **PASS** | 6 passed |
| `cargo test -p quervant-core --test pr10_metrics` | stable | **PASS** | 5 passed |
| `cargo test -p quervant-core --test pr10_properties` | stable | **PASS** | 9 passed |
| `cargo test -p quervant-core --test pr10_integration` | stable | **PASS** | 11 passed |
| `cargo test -p quervant-core --test pr10_cursor` | stable | **PASS** | 4 passed |
| `cargo test -p quervant-core --test pr10_aggregate_memory` | stable | **PASS** | 7 passed |
| `cargo test --workspace --all-targets` | stable | **PASS** | 1341 passed, 0 failed, 7 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | **PASS** | 1341 passed, 0 failed, 7 ignored |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | **PASS** | **91.70% line**, 87.69% function, 91.47% region |
| `cargo doc --workspace --no-deps` | stable | **PASS** | generated |
| `cargo bench -p quervant-core --no-run` | stable | **PASS** | all bench targets build |
| `bash benchmarks/scripts/test-scripts.sh` | shell | **PASS** | 33 passed, 0 failed |

All required test targets exist with the names used by the plan; no mapping was
needed. No failure required classification.

## A2 test traceability

Test states: **written**, **executed**, **passed**. All tests were written and
executed in this change.

| ID | Test | Location | Assertion |
|---|---|---|---|
| A2-I01 | `a2_t01_memory_ledger_exact_and_one_over` | `search/analytics.rs` unit | exact limit succeeds; one-over fails atomically |
| A2-I02 | `a2_t02_memory_ledger_checked_arithmetic` | `search/analytics.rs` unit | near-`u64::MAX` is typed, never wraps/clamps |
| A2-I03 | `a2_t03_large_keyword_admission_rejected` | `tests/pr10_aggregate_memory.rs` | 10 KB keyword rejected at a 256-byte budget |
| A2-I04 | `a2_t04_repeated_metrics_reuse_and_exactness` | `tests/pr10_aggregate_memory.rs` | Sum/Avg/Min/Max/Distinct on one field match a hand table |
| A2-I05 | `a2_t05_frequency_dedup_per_document`, `a2_t05_charged_expansion_one_over` | integration + unit | duplicates count once; expansion one-over fails before allocating |
| A2-I06 | `a2_t06_expansion_memory_bound` | `tests/pr10_aggregate_memory.rs` | 2-field Cartesian staging rejected at 512 bytes, exact (9 groups) with a generous budget |
| A2-I07 | `a2_t07_retained_and_transient_share_one_limit` | `search/analytics.rs` unit | each side fits alone; the combined peak fails |
| A2-I08 | `a2_t08_add_document_error_releases_transient`, `a2_t08_cancellation_mid_scan` | unit + integration | error releases transient; mid-scan cancel returns `Cancelled`, snapshot reusable |
| A2-I09 | `a2_t09_finish_peak_fails_without_partial_response` | `search/analytics.rs` unit | finalization peak rejected, no output returned |
| A2-I10 | `a2_t10_semantics_table` + existing PR 10 suites | integration | exact group/metric/frequency values and ordering |
| A2-I11 | `a2_t11_deterministic_success_or_error` | `tests/pr10_aggregate_memory.rs` | identical inputs yield identical success or typed error |
| A2-I12 | diff audit + workspace/MSRV gates | this report | no public API/codec/lexical/snapshot changes |

## Independent oracle

Expected counts, sums, averages, min/max, distinct counts, frequency ties and
group combinations in `a2_t10_semantics_table`, `a2_t04`, `a2_t05` and `a2_t06`
are hand-calculated literal tables. No expected value is computed by
`AggregationEngine`. Budget tests assert acceptance/rejection at independently
chosen conservative bounds, not against a second implementation of the ledger.

## Budget scope statement

The enforced bound is a **conservative logical memory-admission budget** for owned
aggregation allocations introduced by the PR 10 paths (`visit_aggregate` decode
cache and group staging; `AggregationEngine` expansion stack, emitted key set,
frequency dedup staging, retained group/metric/frequency state and response
finalization). It is not a hard bound on allocator metadata, `Vec` capacity
slack, decoded column buffers outside the listed paths, storage-cache
allocations, or total process RSS. Over-estimation is intentional; no listed
owned value is omitted.

## Diff audit (A2-T12)

Changed production files:

- `crates/quervant-core/src/search/analytics.rs` — shared `AggregateMemory`
  ledger (replaces `state_bytes`), budget-aware expansion, internal and
  finalization admission.
- `crates/quervant-core/src/search/typed.rs` — decode-once cache + borrowed metric
  and frequency inputs + pre-admitted group staging.
- `crates/quervant-core/src/search/typed_compare.rs` — `pub(crate)`
  `decoded_value_bound` seam.
- `crates/quervant-core/src/segment/column.rs` — read-only `pub(crate)`
  `encoded_value_shape` seam; `value` refactored onto a shared span helper with
  identical behavior.

Unchanged: `search/limits.rs`, `index/snapshot.rs`, `search/execute.rs`,
`search/plan.rs`, contract modules, `.github/`, codec wire versions, `CURRENT`,
manifest and merge code. No new public API item was added (verified with a
`git diff` audit for `pub fn/struct/enum/trait/const/type` additions).

## Coverage (amended files)

| File | Line coverage |
|---|---|
| `search/analytics.rs` | 90.69% |
| `search/typed.rs` | 87.60% |
| `search/typed_compare.rs` | 91.55% |
| `segment/column.rs` | 89.63% |
| **Workspace total** | **91.70%** |

No coverage exclusion was added or changed.

## Residual risks

- **Allocator RSS vs logical budget:** accepted PR 10 limitation. Broader
  allocation instrumentation is future work requiring a separate decision.
- **Conservative over-estimation:** a request with a very large multi-value
  fan-out or very large single values can be rejected slightly earlier than a
  byte-exact accounting would; this is fail-closed and deterministic.
- **Column decoder bound:** the read-only span seam is a trustworthy
  pre-allocation bound for all supported aggregation scalar types; unsupported
  types are rejected at validation before decode.

## Unresolved failures

None. No STOP condition was triggered. No gate is reported as PASS without having
been executed on the final amendment tree.
