# PR 14B — implementation evidence

**Status vocabulary:** `TESTS IMPLEMENTED` ≠ `LOCALLY EXECUTED` ≠
`REAL-RUSTFS QUALIFIED` ≠ `CI VERIFIED` ≠ `HUMAN ACCEPTED`.

| Status | Value |
|---|---|
| TESTS IMPLEMENTED | YES |
| LOCALLY EXECUTED | YES (stable 1.98.1 and MSRV 1.85.0) |
| REAL-RUSTFS QUALIFIED | YES on the pinned RustFS 1.0.1 digest recorded in [environment-and-commands.md](environment-and-commands.md) |
| CI VERIFIED | **NO — not run** (no PR/CI run was created for this branch) |
| HUMAN ACCEPTED | **NO** — PR 14 acceptance belongs to 14C |

The mandatory real-provider cases were executed, not merely compiled. No
required provider case was left ignored-and-unrun, skipped, or substituted with
a fake.

## Base and scope

| Item | Value |
|---|---|
| Fresh `main` base | `7a860590fe5ba4fde3cfeee235e8a33751019522` (PR #60 / PR 14A merged) |
| Branch | `dev/pr14b-real-rustfs-qualification` |
| Code/test commit qualified by all gates | `556621a5414673d3355e57fb2b2f4fb09135c54b` |
| Evidence commit | final docs-only commit on `dev/pr14b-real-rustfs-qualification` (see `git log -1`); it adds only `docs/pr-artifacts/pr-14b/*.md` |
| Scope | Qualification tests and evidence only; no production source, API, codec, manifest, prefix, cache, PIT or protocol change |

Files changed by the qualified code commit (`556621a`):

- `crates/quervant-core/tests/pr14_storage_vertical.rs` (extended)
- `crates/quervant-core/tests/pr14b_json_memory.rs` (new test-only suite)

This evidence commit adds only `docs/pr-artifacts/pr-14b/*.md`. No production
source was changed in either commit.

## Baseline (Phase P0) and the one baseline failure

Before any change, the non-ignored local vertical passed (3 passed, 9 ignored).
Each of the eight pre-existing ignored real-provider cases was then run
individually against the pinned service.

| Case | Initial result |
|---|---|
| `real::r02_r04_r06_real_cold_compound_equivalence` | PASS |
| `real::r08_r09_r15_real_batch_aggregation_and_cursor` | **FAIL** |
| `real::r05_real_mutation_old_and_new_snapshot` | PASS |
| `real::r10_r11_real_remote_budget_exact_and_one_over` | PASS |
| `real::r12_empty_cache_no_writer_state` | PASS |
| `real::r01_separate_process_cold_bootstrap` | PASS |
| `real::r03_wrong_generation_is_not_substituted` | PASS |
| `real::r13_r14_warm_evict_and_pinned_reader` | PASS |

### Classification of the baseline failure

- **Test/command:** `real::r08_r09_r15_real_batch_aggregation_and_cursor`
  (`pr14_storage_vertical.rs`, the historical naked-snapshot cursor block).
- **Observed:** `execute_batch(...).unwrap()` panicked with
  `Query(InvalidBatch(PinnedContextRequired))`.
- **Classification:** *deterministic pre-existing test defect*, not an
  introduced regression and not a feature defect. PR 14A deliberately changed
  the naked `execute_batch` entry to reject the whole PIT/cursor-bearing
  envelope before any slot executes (`crates/quervant-core/src/search/batch.rs`).
  The real-provider test predates that contract and still expected a per-slot
  `PerQueryOutcome::Failure`; because it is `#[ignore]`d, ordinary CI never
  observed the mismatch.
- **Resolution (test-only):** the negative regression now asserts the actual
  typed envelope error `InvalidBatch(PinnedContextRequired)`. The fail-closed
  intent is preserved; the positive pinned path is a *separate* new test
  (`b06_b07_real_pinned_batch_search_after`). No production behaviour changed.
- **Acceptance scope:** this removes a stale assertion only; it does not
  weaken the fail-closed regression. Re-run after the change: PASS.

No other baseline failure occurred. No test was excluded, retried-until-green,
or re-labeled.

## What was added

| Area | Test / assertion |
|---|---|
| B01 cross-provider oracle | `real::r02_r04_r06_real_cold_compound_equivalence` now also asserts an explicit `n`-ascending key table `["d0","d1","d3","d5"]`, `total_hits = 4`, host aggregation `[("h1",3,90),("h2",1,40)]`, and five-state projections on both providers |
| B02 mixed Boolean + ranking | `real::b02_real_mixed_boolean_and_relevance_order` — nested `And/Or/Not` over lexical + JSON path range + geo bbox + IPv4 CIDR; the only two survivors rank `["zfew","aonce"]` while key order is `["aonce","zfew"]`, proving the score contract is not key sorting |
| B03 JSON sort + five states | `b03_local_json_path_sort_and_projection_table` — `$.k` descending yields `["d5","d4","d3","d2","d1","d0"]` with ExplicitNull/Multi/Empty/Absent projections |
| B06/B07 public PIT pagination | `real::b06_b07_real_pinned_batch_search_after` — a live `RemoteIndex::pin()` handle, `execute_batch_pinned`, page sizes 1 and 2, exact sequence `d0..d5`, aggregation parity on every page, middle-slot typed failure isolated, terminal `None`, and expired/wrong-handle/query/sort negatives |
| B08/B09 mutation and pins | `real::r05_real_mutation_old_and_new_snapshot` — retains a `PitHandle` across upsert+delete+commit, proves the old ordered snapshot is unchanged, cold-reopens remote, and pins the new generation which excludes `d2` |
| B12/B13 budgets + cancellation | `real::r10_r11_real_remote_budget_exact_and_one_over` — exact/one-under for `BatchMemoryBytes`, `BatchResponseBytes`, `BatchAggregate` on both the plain and pinned-cursor paths, plus cancellation after a prior success with ordered sibling failures |
| B18/B19 historical JSON | `b18_b19_historical_json_segment_compatibility` (local) and `real::b18_real_historical_json_remote` (real provider) — see [compatibility-evidence.md](compatibility-evidence.md) |
| B20/B21 risk characterization | `pr14b_json_memory.rs` — child-process tracking allocator measurement; see [resource-risk.md](resource-risk.md) |

## Gate results (code commit `556621a`)

| Gate | Command | Result |
|---|---|---|
| Formatting | `cargo fmt --all -- --check` | **PASS** |
| Clippy (default) | `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** |
| Clippy (all features) | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| MSRV formatting | `cargo +1.85.0 fmt --all -- --check` | **PASS** |
| MSRV Clippy (all features) | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| Tests (default) | `cargo test --workspace --all-targets` | **PASS — 2019 passed, 0 failed, 10 ignored** |
| Tests (all features) | `cargo test --workspace --all-targets --all-features` | **PASS — 2023 passed, 0 failed, 71 ignored** |
| Tests (MSRV all features) | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS — 2023 passed, 0 failed, 71 ignored** |
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS — 91.27% lines** (47599 lines, 4155 missed; regions 91.83%, functions 87.24%) |
| Documentation | `cargo doc --workspace --all-features --no-deps` | **PASS** |
| Benchmark build | `cargo bench --workspace --no-run` | **PASS** |
| Benchmark scripts | `bash benchmarks/scripts/test-scripts.sh` | **PASS — 33 passed, 0 failed** |
| Whitespace | `git diff --check` | **PASS** |
| CI (final SHA) | GitHub Actions | **NOT RUN — open gate** |

Ignored counts increased only because the new real-provider cases and the
memory-probe child entrypoint are intentionally `#[ignore]`d; each required
real-provider case was executed explicitly with `--ignored --exact`.

## Real-provider execution totals

| Suite | Executions | Result |
|---|---|---|
| `pr14_storage_vertical` provider cases (individually) | 11 cases + 1 parent-spawned child | **PASS** |
| `pr14_storage_faults` (each case runs 10 unique-prefix iterations; child only via parent) | 9 cases | **PASS** |
| `pr13_remote_proxy` | 7 cases (+3 repeat cycles for h10/h11) | **PASS** |
| `pr13_crash_rustfs` | 5 cases (+3 repeat cycles for k03/k04) | **PASS** |
| `quervant-objectstore` `pr13_s3_rustfs` | 8 cases | **PASS** |
| `quervant-objectstore` `pr13_proxy_rustfs` | 5 cases | **PASS** |
| `pr13_remote` / `pr13_oracle` / `pr13_oracle_geo` | 3 / 1 / 1 | **PASS** |

Critical fault/recovery cases (`k03`, `k04`, `h10`, `h11`) were repeated three
times end-to-end with unique prefixes; all repetitions passed. The
`pr14_storage_faults` cases already perform ten independent unique-prefix
iterations each, exceeding the three-repetition floor.

## Exception and decision record

| ID | Trigger | Disposition | Gate state |
|---|---|---|---|
| E01 | Existing ignored RustFS cases | Preserved and executed explicitly | Closed for executed cases |
| E02 | `p4_child_bootstrap` / `p4_fault_child_open` | Filtered by `--exact` parent; children only invoked by parents | Closed |
| E03 | PR 14A merged on `main` | Branched from verified `origin/main` | Closed |
| E04 | Unique prefixes/workspaces | Reused `config(tag)` isolation | Closed |
| E05 | Test names | Resolved with `--list`; actual symbols recorded | Closed |
| E06 | Harness variables | Used the fixed `QUERVANT_RUSTFS_*` contract | Closed |
| E07 | Minor doc discrepancies (PR 14A references) | New dated evidence set; original artifacts untouched | Deferred to review |
| E08 | Historical PR 14 logs unavailable | Not cited; current reproducible runs used | Not applicable |
| E09 | RustFS service/digest | Pinned image started and verified (`1.0.1`) | Closed |
| E10 | Historical JSON fixture | Genuine frozen PR 11 golden found; see [compatibility-evidence.md](compatibility-evidence.md) | Closed, with the version caveat documented |
| E11 | Fault injection boundary | Existing real-provider HTTP fault proxy and crash checkpoints used | Closed |
| E12 | Local/remote oracle mismatch | None observed | Not triggered |
| E13 | Corrupt/partial visibility | None observed; corruption rejected typed | Not triggered |
| E14 | Unmetered JSON occurrence memory | Measured and characterized; **not** silently accepted. See [resource-risk.md](resource-risk.md) | **Open for 14C human disposition** |
| E15 | Production change required | None; all changes are tests/evidence | Not triggered |
| E16 | Coverage/lint/tests | Coverage 91.27%; stable/MSRV pass | Closed locally; CI open |
| E17 | Flaky real-provider tests | No flakiness observed across repeats | Not triggered |
| E18 | Historical format limitation | Documented; compatibility claimed only for the supported JSON v1 wire | Open for 14C acknowledgement |

## Independent PR #61 source-review qualifications

- **Q1 — Allocator-probe interpretability:** the tracked heap figures describe allocations observed within isolated test measurement windows, not RSS, physical peak-process usage, allocator capacity or a guaranteed global cap. See [resource-risk.md](resource-risk.md#independent-source-review-qualifications-pr-61).
- **Q2 — Formal risk disposition:** `R-14A-JSON-MEM` remains **OPEN** even if PR 14B is merged. PR 14B acceptance addresses qualification evidence only; PR 14C requires explicit human acceptance with limitations, a separately designed fix, or a release block. See [resource-risk.md](resource-risk.md#independent-source-review-qualifications-pr-61).

## Residual risks / open gates

- **`R-14A-JSON-MEM` remains open.** The measurements confirm the documented
  gap; 14B measures it and does not fix the accounting architecture. 14C must
  accept or reject the residual risk explicitly (or authorize a separate
  design-reviewed fix).
- **CI not run.** Final-SHA CI (`rust`, `msrv`, `rustfs` jobs) is a required
  gate and is unverified in this run. Absent a CI run that logs the pinned
  provider and the executed cases, 14B cannot be called `CI VERIFIED`.
- **Human review/approval not performed.** 14B is not `HUMAN ACCEPTED`.
- Cursor continuations remain process-local and invalid after process exit or
  when the issuing `PitHandle` is dropped (unchanged PR 14A contract).
- The historical JSON qualification proves frozen-byte compatibility for the
  only supported JSON wire version; it does **not** claim a cross-version
  migration because no older supported JSON version exists in repository
  history.
