# PR 14C — validation report

**Status: IN PROGRESS — no acceptance claimed.** Local, real-RustFS and
fault/regression evidence is recorded below. Qualified P4 benchmarks (C-T10),
final-SHA CI (C-T14) and the human `R-14A-JSON-MEM` disposition (C-T16) are
still open, so C09/C10/C16 cannot be marked PASS.

Baseline: `376023b53b557a30367097f29a41328c798188d4` (clean tree before P1;
14C documentation commits only). All commands below were run from the repository
root on that baseline plus documentation-only commits.

## 1. Environment

| Item | Value |
|---|---|
| Host | WSL2, `Linux 6.18.33.2-microsoft-standard-WSL2`, x86-64 |
| Repository filesystem | ext4 (`/dev/sdd` → `/`), not `/mnt/c` |
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV toolchain | `rustc/cargo 1.85.0` (`cargo +1.85.0`) |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Container runtime | `podman 4.9.3` (rootless) |
| RustFS image | `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`, local image ID `f6b22807f10d` (digest verified via `podman image inspect`) |
| RustFS container | `quervant-pr14b-rustfs`, started for this run, `--security-opt no-new-privileges:true`, ports `127.0.0.1:9000-9001` |
| Health | `{"status":"ok","service":"rustfs-endpoint","version":"1.0.1"}` (ready after 2 s) |
| Provider env | `QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000`, `REGION=us-east-1`, `BUCKET=quervant-pr14b`; disposable test credentials supplied per-command and not written to any log or committed file |
| Python | 3.12.3 |
| GitHub CLI | `gh` token invalid — CI job IDs cannot be read with the CLI (open item) |

Every provider command used a disposable bucket/prefix scope; no production
bucket or credential was touched.

## 2. Local PR 14 suites (C-T01, C-T03, C-T06, C-T07)

Command pattern: `cargo test -p quervant-core --all-features --test <suite> -- --test-threads=1`.

| Suite | Result |
|---|---|
| `pr14a_public_cursor` | PASS — 26 passed, 0 failed |
| `pr14_batch` | PASS — 12 |
| `pr14_batch_governance` | PASS — 7 |
| `pr14_batch_memory` | PASS — 31 |
| `pr14_unified_cursor` | PASS — 11 |
| `pr14_unified_mixed` | PASS — 14 |
| `pr14_compound_aggregation` | PASS — 24 |
| `pr14_aggregation` | PASS — 5 |
| `pr14_json` | PASS — 13 |
| `pr14_projection` | PASS — 10 |
| `pr14_typed_predicates` | PASS — 12 |
| `pr14_f1_hardening` | PASS — 23 |
| **Subtotal** | **188 passed, 0 failed** |
| `pr14_storage_vertical` (local, non-ignored) | PASS — 5 passed, 12 ignored |
| `pr14b_json_memory` (B20/B21 parent) | PASS — 1 passed, 1 ignored (child) |

B20/B21 output reproduced the PR 14B characterization exactly:

```text
occurrences=1    logical_BatchMemoryBytes=112 tracked_peak_exact=33675    tracked_peak_one_under=33104  tracked_peak_cancelled=7397
occurrences=128  logical_BatchMemoryBytes=112 tracked_peak_exact=110392   tracked_peak_one_under=41233  tracked_peak_cancelled=7397
occurrences=4096 logical_BatchMemoryBytes=112 tracked_peak_exact=2518968  tracked_peak_one_under=303121 tracked_peak_cancelled=7397
```

These remain **characterization**, not compliance with a physical memory cap; the
risk is open in [resource-risk-disposition.md](resource-risk-disposition.md).

Historical JSON golden (C-T06) ran inside `pr14_storage_vertical`:
`b18_b19_historical_json_segment_compatibility` PASS (frozen SHA-256
`0528a62c…a02f`, corruption rejected, major version 2 → typed rejection).

## 3. Real RustFS qualification (C-T02, C-T04, C-T05)

Provider: pinned digest above, health-verified `1.0.1`.

### 3.1 Vertical provider cases (each `--ignored --exact --test-threads=1`)

| Symbol | Result |
|---|---|
| `real::r02_r04_r06_real_cold_compound_equivalence` | PASS |
| `real::r05_real_mutation_old_and_new_snapshot` | PASS |
| `real::r12_empty_cache_no_writer_state` | PASS |
| `real::r03_wrong_generation_is_not_substituted` | PASS |
| `real::r01_separate_process_cold_bootstrap` | PASS (parent-spawned child) |
| `real::r08_r09_r15_real_batch_aggregation_and_cursor` | PASS |
| `real::r10_r11_real_remote_budget_exact_and_one_over` | PASS |
| `real::r13_r14_warm_evict_and_pinned_reader` | PASS |
| `real::b02_real_mixed_boolean_and_relevance_order` | PASS |
| `real::b06_b07_real_pinned_batch_search_after` | PASS |
| `real::b18_real_historical_json_remote` | PASS |

**11/11 PASS.** `p4_child_bootstrap` was not invoked standalone (E08).

The historical 14B baseline failure in
`real::r08_r09_r15_real_batch_aggregation_and_cursor` (stale naked-snapshot
cursor assertion) is **not** reproduced: the test-only correction merged in
PR #61 is present and the case passes.

### 3.2 `pr14_storage_faults` (10 unique-prefix iterations per case)

| Case | Result |
|---|---|
| `f01_segment_get_transient_failure` | PASS |
| `f02_truncated_segment_transfer` | PASS |
| `f03_corrupt_content_range_rejected` | PASS |
| `f04_manifest_read_interrupted` | PASS |
| `f05_concurrent_old_reader_and_new_commit` | PASS |
| `f06_cancellation_during_transfer_is_bounded` | PASS |
| `f07_retry_exhaustion_is_bounded_and_recoverable` | PASS |
| `f08_crash_at_download_checkpoint` | PASS (separate process, SIGKILL) |
| `f09_f10_batch_after_fault_and_s_f_s` | PASS |

**9/9 PASS × 10 iterations = 90 fault iterations.** `p4_fault_child_open` only
via its parent (E08).

### 3.3 PR 13 regression suites (C-T05)

| Suite | Executed | Result |
|---|---|---|
| `pr13_remote_proxy` (`h06`–`h12`, individually) | 7 | PASS |
| `pr13_crash_rustfs` (`k01`–`k05`, individually) | 5 | PASS |
| `pr13_remote` (local 5 + `real::*` 3) | 8 | PASS |
| `pr13_oracle` (local 2 + `real::*` 1) | 3 | PASS |
| `pr13_oracle_geo` (local 1 + `real::*` 1) | 2 | PASS |
| `quervant-objectstore` `pr13_s3_rustfs` | 8 | PASS |
| `quervant-objectstore` `pr13_proxy_rustfs` | 5 | PASS |

Provider-backed executions in this section: 7 (proxy) + 5 (crash) + 3 + 1 + 1 + 8 + 5 = **30**.

### 3.4 Totals

| Class | Count |
|---|---:|
| Real-provider executions (11 verticals + 9 fault cases + 30 PR 13 provider/objectstore cases) | 50 cases (90 fault iterations inside the 9) |
| Local PR 14 suite executions | 194 (188 + 5 vertical local + 1 memory parent) |
| PR 13 local/fake executions | 8 |

No required provider case was left ignored-and-unrun; no fake was substituted
for a real-boundary assertion.

## 4. Workspace quality gates (C-T12, C-T13)

All commands below produced exit 0; logs under `/tmp/pr14c-logs/gates/`.

| Gate | Command | Result |
|---|---|---|
| Formatting | `cargo fmt --all -- --check` | PASS |
| Formatting (MSRV) | `cargo +1.85.0 fmt --all -- --check` | PASS |
| Clippy default | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| Clippy all features | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Clippy default (MSRV) | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| Clippy all features (MSRV) | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Tests default | `cargo test --workspace --all-targets` | PASS — **2019 passed, 0 failed, 10 ignored** |
| Tests all features | `cargo test --workspace --all-targets --all-features` | PASS — **2023 passed, 0 failed, 71 ignored** |
| Tests default (MSRV) | `cargo +1.85.0 test --workspace --all-targets` | PASS — **2019 passed, 0 failed, 10 ignored** |
| Tests all features (MSRV) | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — **2023 passed, 0 failed, 71 ignored** |
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.27 % lines** (47,599 lines, 4,155 missed); regions 91.83 %; functions 87.24 % |
| Documentation | `cargo doc --workspace --all-features --no-deps` | PASS |
| Bench build | `cargo bench --workspace --no-run` | PASS |
| Script tests | `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |
| Whitespace | `git diff --check` | PASS |
| Validator self-test | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | PASS (C-T09) |

Coverage is measured over all workspace production code with no exclusions
added by 14C.

## 5. Ignored/skipped reconciliation (G03 / reviewer checklist)

`cargo test --workspace --all-targets --all-features -- --ignored --list`
reports **71** ignored tests. Classification:

| Class | Count | Executed in PR 14C |
|---|---:|---|
| PR 14 owned: 11 real verticals, 9 fault cases, 3 child entrypoints (`p4_child_bootstrap`, `p4_fault_child_open`, `b20_child_json_memory_probe`), 1 benchmark | 24 | Yes — parents executed, children only via parents |
| PR 13 provider/objectstore: `h06`–`h12` (7), `k01`–`k05` + `child_entrypoint` (6), `pr13_remote` real (3), `pr13_oracle` real (1), `pr13_oracle_geo` real (1), objectstore `s*` (8) + `h0*` (5) | 31 | Yes (children only via parents) |
| Pre-existing PR 06–12 / M-series / fixture-regenerator / unrelated benchmark entrypoints (`c07_child_reopen`, `f02_child_writer`, `i03`–`i05`, `generate_json_paths_golden`, `regenerate_v1_fixture`, `regenerate_golden_norms`, `m4_t26`, `m5_t43`, `real_rustfs::m1/m2/m3`, `p01_p04`, `p05_p07`, `t02_child_commits_gen2`) | 16 | Not re-run — not PR 14 acceptance obligations |

No ignored test required by PR 14C was left unexecuted. The 16 unrelated entries
are pre-existing provider/generator/child suites owned by earlier PRs and are
outside this closeout's required matrix; they are listed here so the count is
fully explained.

## 6. Local vs CI

| Flag | State |
|---|---|
| IMPLEMENTED (PR 14 surface) | Historical merges (PR #41, #60, #61) |
| LOCALLY EXECUTED | YES — this report |
| REAL-RUSTFS QUALIFIED (local run) | YES — pinned digest, per-case symbols |
| BENCHMARK QUALIFIED | **NO — pending C-T10** |
| STABLE/MSRV VERIFIED (local) | YES — §4 |
| COVERAGE VERIFIED (local) | YES — 91.27 % lines |
| FINAL-SHA CI VERIFIED | **NO** — no PR exists; `gh` token invalid |
| INDEPENDENT SOURCE REVIEW | Pending (P7) |
| RISK DECISION | **PENDING — BLOCKED** (`R-14A-JSON-MEM`) |
| HUMAN ACCEPTED | NO |
| PR14 DONE | NO |

## 7. Open items

1. **C-T10/C-T11:** three qualified P4 trials require an idle-host attestation
   (`--idle-confirmed`) and a clean tracked tree; W08 must be validated only via
   the approved exemption manifest.
2. **C-T14:** open a PR and observe `rust`, `msrv`, `rustfs` on the final head;
   restore `gh` authentication or capture job evidence another way.
3. **C-T16:** human `R-14A-JSON-MEM` disposition.
4. **C-T08:** no test-harness change was made in P1, so no re-run of boundary
   tests was required; if a harness change is later authorized, the affected
   local and provider cases must be re-executed.

No acceptance is claimed by this report.
