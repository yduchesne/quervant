# PR 15I-C-F — correctness and QA

Working tree tested: `45dd538a14faf1696e971efdaa09a8ff6bde7a38` (rollback +
verifier aggregate fix + result documents); production `crates/` is
byte-identical to `6f6463cb26bcf28340cc9d4afd4dfeb040281898`.

## 1. Production equivalence

| Check | Result |
| --- | --- |
| `git diff 6f6463cb… -- crates/` | empty (0 lines) |
| `git diff 6f6463cb… -- Cargo.toml Cargo.lock .github/` | empty |
| `crates/quervant-core/tests/pr15i_c_physical.rs` | removed (absent in `BASE_A`) |
| `benchmarks/pr15i_c/protocol.json` SHA-256 | `5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e` (unchanged) |
| Frozen acceptance criteria | untouched and unmet; nothing in this experiment claims them |

## 2. Mandatory local gates

| Command | Result |
| --- | --- |
| `cargo fmt --all -- --check` (stable) | PASS |
| `cargo +1.85.0 fmt --all -- --check` (MSRV) | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable) | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` (MSRV) | PASS |
| `cargo test --workspace --all-targets` | PASS — 135 test binaries, 0 failures |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **92.62 % lines** (58 727 lines, 4 334 missed), 88.05 % functions, 93.18 % regions |
| `cargo doc --workspace --no-deps` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script tests |

Toolchain used: `rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1
(797e8a9bc 2026-08-05)` stable, plus `cargo +1.85.0` for the MSRV lint/format
gate.

## 3. Benchmark-tooling suites

| Suite | Result |
| --- | --- |
| `python3 -m unittest discover -s benchmarks/pr15i_c -p 'test_*.py'` | PASS — 499 tests (382 pre-existing + 117 new F tooling tests: 35 controller, 69 verifier, 13 source proof) |
| `python3 -m unittest discover -s benchmarks/pr15d/harness -p 'test_*.py'` | PASS — 139 tests |
| `python3 -m unittest discover -s benchmarks/pr15i_b -p 'test_*.py'` | PASS — 10 tests |
| `python3 -m unittest discover -s benchmarks/pr15i_a -p 'test_*.py'` | 1 failure + 3 errors, **pre-existing** (the PR 15I-A real-campaign/read-only tree expectations that depend on that study's on-disk campaign; unchanged by this experiment and identical on the preflight tree) |

## 4. Evidence integrity

- Four sealed campaigns, each with 15 raw files, 32 slot files, a SHA-256 seal
  and an independent verification receipt
  (`target/pr15i-c/reviews/f-final-{unbatched-01,batched-01,unbatched-02,batched-02}.json`)
  plus the series receipt `f-final-series.json`.
- Aborted attempts 01, 02 (no samples) and 03 (32 slots / 5 760 samples, no
  seal, no receipt) are preserved outside the series with `INVALID.json` and are
  excluded from every statistic.
- The verifier recomputes medians, block means, block ratios, drift and the
  classifier from raw data; it re-runs the source proof, checks seal/inventory
  and binary digests, and rejects any recorded receipt that disagrees.
- No raw file, receipt or protocol was modified after measurement; no campaign
  was retried for a favourable result.

## 5. Outstanding external gates

| Gate | Status |
| --- | --- |
| Real RustFS integration | `REAL_RUSTFS_BLOCKED` — no verified `rustfs/rustfs@sha256:1803faef…` runtime (`docker` absent; `podman` cannot pull the pinned image). No fake store substituted, no ignored test counted. |
| Hardware counters | `PERF_UNAVAILABLE` — no cycle/cache claims made |
| Hosted CI | `HOSTED_CI_PENDING` |
| Independent review | `INDEPENDENT_REVIEW_PENDING` |
| Publication | `NOT_PUSHED`, `NOT_MERGED` — none authorized |
