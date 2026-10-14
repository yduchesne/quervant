# PR 11 — Local validation report

**State validated:** `dev/json-indexing` at `81b8a31713f79a0855210f89d8857c2e5cbb3802` plus the
PR 11 working-tree changes (branch has no PR 11 commit yet at report time).
**Toolchains:** stable `rustc 1.98.1 (48a229cea 2026-09-01)`; MSRV `rustc 1.85.0`.
**Topology required:** none beyond a local filesystem-free build; integration tests use
`MemoryDirectory` and the real `IndexWriter`/`ReaderSnapshot`/`TypedSearcher` path. No RustFS,
container, network or distributed services were required or exercised.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable 1.98.1) | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --test pr11_json_paths` | PASS (9) |
| `cargo test -p quervant-core --test pr11_json_mutations` | PASS (6) |
| `cargo test -p quervant-core --test pr11_json_corruption` | PASS (7 passing; 1 ignored fixture generator) |
| `cargo test -p quervant-core --test pr11_json_properties` | PASS (4) |
| `cargo test --workspace --all-targets` (stable) | PASS (all suites) |
| `cargo +1.85.0 test --workspace --all-targets` | PASS (all suites) |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — TOTAL **91.69% line**, 87.79% branch, 91.27% function |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench -p quervant-core --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |

## Feature evidence

- Codec round-trip, exact concrete paths, multi-root virtual index, duplicate rejection: `segment/json_paths.rs` unit tests + `pr11_json_paths`.
- Feature/section negotiation, corruption fail-closed, decode/accepted-size bounds, and the byte-frozen checked-in `tests/fixtures/segment/json_paths_golden.seg` (SHA-256 asserted): `pr11_json_corruption`.
- Work-budget exhaustion and cancellation terminality: `pr11_json_corruption::t16`.
- Refresh/commit/PIT/delete/upsert/compact/reopen: `pr11_json_mutations`.
- Legacy stored-source fallback and unstored typed error: `search::typed::legacy_json_tests`.
- Deterministic independent oracle: `pr11_json_properties::t_oracle_matches_exactly`.
- Existing lexical/temporal/analytics/mutation suites unaffected: full workspace run.

## Skipped / blocked gates

None. No gate was waived. `cargo llvm-cov` was available and executed.

## Unresolved failures

None.

## Residual risks

- Logical memory budgets are not a hard process-RSS cap.
- The immutable path/leaf-value section is an occurrence scan per matched segment, not an inverted
  `(path, scalar)` dictionary; it is exact and bounded but may be slower on very large segments.
  No performance claim is made.
