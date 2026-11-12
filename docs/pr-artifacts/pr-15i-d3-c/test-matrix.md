# PR 15I-D3-C — test matrix (executed subset)

All commands were run on the implementation tree. No D3-C benchmark tooling
exists yet, so V/M/P/RH suites and I01–I12 are **NOT RUN**.

| Suite | State |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,464 tests |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,492 tests |
| `cargo test -p quervant-core --features pr15i-d3c-experiment d3c_tests` | PASS — 24/24 |
| D3-C V01–V60 / M01–M16 / P01–P22 / RH-01–RH-16 | NOT RUN (tooling not implemented) |
| D3-C I01–I12 real `FsDirectory` integration | NOT RUN |
| Python D3-C suites | NOT RUN |
| Coverage, docs, bench, MSRV, RustFS, CI, review | NOT RUN for D3-C final state |

Implemented U-IDs: U01–U20 (except U21–U25/U27), U26, U28, U29, U31, U32,
U39. Missing U-IDs are listed in `design-and-invariants.md`.
