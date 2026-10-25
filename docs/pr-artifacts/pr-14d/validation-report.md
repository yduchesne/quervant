# PR 14D — validation report

**Status: implementation locally verified; PR 14 IN PROGRESS / NOT ACCEPTED.**
Final-SHA CI and independent review remain open. No v0.1 release claim.

| Item | Value |
|---|---|
| Baseline | `2cb91be19652379b435c49a5fa4aea2ed7502de5` (PR #62 merged) |
| Implementation commit | `d0e1bbbd841feff6615d7824dd3261a2418511f7` |
| Evidence commit | docs-only commit on `dev/pr14d-json-sort-memory-governance` |
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV toolchain | `cargo +1.85.0` → 1.85.0 |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Host | WSL2 Linux x86-64; repository on ext4 (`/dev/sdd`) |
| Provider | `docker.io/rustfs/rustfs@sha256:1803faef…6a3c` (`1.0.1`), health-verified, disposable credentials (not logged) |

## 1. Workspace gates

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — **2036 passed, 0 failed, 10 ignored** |
| `cargo test --workspace --all-targets --all-features` | PASS — **2040 passed, 0 failed, 73 ignored** |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **2036 passed, 0 failed, 10 ignored** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — **2040 passed, 0 failed, 73 ignored** |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.27 % lines** (48,123 lines, 4,199 missed); regions 91.82 %; functions 87.33 % |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |
| `git diff --check` | PASS |

Coverage is measured across all workspace production crates with no exclusions
added by this PR.

## 2. PR 14D suites

| Suite | Result |
|---|---|
| `pr14d_json_sort_memory` | **8 passed** (D01/D09, D02, D03, D04, D05/D10, D06, D07, D08) |
| `pr14b_json_memory` | 1 passed, 1 ignored (child) — post-fix characterization |
| `search::typed::json_sort_scratch_tests` (unit) | **9 passed** (reservation lifecycle, overflow/underflow, drop cleanup, sibling budget, concurrent buffers, `push_occurrence` rejection, legacy rejection) |

## 3. Real-provider execution (pinned RustFS 1.0.1)

Each required case was invoked individually with
`--ignored --exact --test-threads=1`.

| Suite / case class | Executed | Result |
|---|---:|---|
| `pr14_storage_vertical` real symbols (11 pre-existing + D11 + D12) | 13 | PASS |
| `pr14_storage_faults` F01–F09/F10 (10 unique-prefix iterations each) | 9 (90 iterations) | PASS |
| `pr13_remote_proxy` h06–h12 | 7 | PASS |
| `pr13_crash_rustfs` k01–k05 | 5 | PASS |
| `quervant-objectstore` `pr13_s3_rustfs` | 8 | PASS |
| `quervant-objectstore` `pr13_proxy_rustfs` | 5 | PASS |
| `pr13_remote` real | 3 | PASS |
| `pr13_oracle` real | 1 | PASS |
| `pr13_oracle_geo` real | 1 | PASS |

D11 and D12 are the new provider cases:

- `real::d11_real_json_sort_memory_exact_and_one_under` — cold remote reopen,
  exact/one-under JSON sort memory, hand-authored local oracle.
- `real::d12_real_json_sort_mixed_sibling_cancellation_and_pit` — mixed lexical +
  JSON sort S/F/S, typed cancellation, and old/new PIT visibility after upsert.

The provider was stopped after the run.

## 4. Ignored-test reconciliation

All-features workspace reports **73** ignored tests: the previous 71 plus the two
new provider cases (D11/D12). Classification is unchanged from PR 14C:

| Class | Count |
|---|---:|
| PR 14 owned real verticals/faults/child entrypoints/benchmark (now incl. D11/D12) | 26 |
| PR 13 provider/objectstore suites | 31 |
| Pre-existing PR 06–12 / M-series / fixture generators / unrelated benchmarks | 16 |

Every required PR 14D provider case was executed; child entrypoints only through
their parents. No required case was skipped or replaced by a fake.

## 5. Local vs CI

| Flag | State |
|---|---|
| IMPLEMENTED | YES (`d0e1bbb`) |
| LOCALLY EXECUTED | YES |
| REAL-RUSTFS QUALIFIED (local) | YES |
| BENCHMARK QUALIFIED | N/A for 14D (PR 14 P4 unchanged; not re-run) |
| STABLE/MSRV VERIFIED | YES |
| COVERAGE VERIFIED | YES — 91.27 % lines |
| FINAL-SHA CI VERIFIED | **NO — pending PR #63 head checks** |
| INDEPENDENT SOURCE REVIEW | **PENDING** |
| PR 14 DONE | **NO — IN PROGRESS** |
| V0.1 RELEASED | **NO** |

Logs were retained locally under `/tmp/pr14d-logs/` (not committed).
