# PR 14 — Validation report

Tested state: uncommitted working tree on `main` @ `7ca1b2ec59fec648602e0e4a52e8f903a596f106`.
New integration suites executed: `pr14_typed_predicates` (12), `pr14_json` (13), `pr14_projection` (10), `pr14_aggregation` (5), `pr14_batch` (10) = **50 tests**, all passing, plus new in-crate unit tests in `search/{unified,projection,batch}.rs` and the `AggregateRequest::from_contract` mapping.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --all-features` (all binaries) | PASS, 0 failed |
| `cargo test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo test --workspace --no-fail-fast` (default features) | PASS, 0 failed |
| `cargo +1.85.0 test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo test -p quervant-core --all-features --doc` | PASS (0 doctests) |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compiles) |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS |
| New PR 14 real-RustFS targets (`--ignored --test-threads=1`) | NOT EXECUTED |
| PR 13 real-RustFS regression targets | NOT EXECUTED (no RustFS endpoint in this environment) |

## Coverage

`cargo llvm-cov --workspace --all-targets --fail-under-lines 85`:

- **Lines: 36,614 covered / 3,204 missed = 91.25%** (floor 85% PASS)
- Regions 91.62%, Functions 87.50%
- No exclusions added. New/changed modules: `search/unified.rs` 93.47% lines, `search/batch.rs` 93.98%, `search/projection.rs` 95.18%, `search/typed.rs` 90.63%, `segment/json_paths.rs` 88.33%, `contract/query.rs` 90.36%, `contract/result.rs` 91.53%.

## Regression classification

- `pr10_integration.rs::t59_unsupported_fails_closed` initially failed because PR 14 intentionally makes `Query::Exists` executable. Reclassified as an **intentional feature change**; the test was updated to keep using genuinely unsupported operators (`Term`, `Prefix`).
- `pr11_json_corruption.rs::t23_unrelated_operators_still_unsupported` initially failed for the same reason; updated to use `In` on a JSON field, which the typed engine still rejects.
- All other suites (PR 3–13) pass unchanged. No introduced regressions remain.

## BLOCKED / not verified

- Real RustFS cold/warm/fault acceptance and the new 14F verticals: **BLOCKED** (no `QUERVANT_RUSTFS_*` endpoint in this environment).
- 14F benchmark qualification: **NOT EXECUTED**.
- Final-SHA GitHub Actions observation: **NOT EXECUTED** (work is uncommitted; not pushed).
