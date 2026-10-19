# PR 14 — P2B Phase A validation

Base HEAD `dd27c9a` + uncommitted Phase A changes. Stable `1.98.1`, MSRV `1.85.0`.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --lib search::batch_meter` | PASS — 5 (`a01`, `a02`, memory exact/release, response exact, overflow) |
| `cargo test -p quervant-core --test pr14_batch` | PASS — 12 |
| `cargo test -p quervant-core --test pr14_batch_governance` | PASS — 6 |
| `cargo test -p quervant-core --test pr14_unified_cursor` | PASS — 11 |
| `cargo test -p quervant-core --test pr14_f1_hardening` | PASS — 23 |
| `cargo test --workspace --all-features` | PASS — 0 failed |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-features` | PASS on rerun |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — 90.85% lines (regions 91.13%, functions 87.30%) |

## Failure classification
One intermittent MSRV full-suite failure was observed:
`search::term_fst::tests::preflight_work_limit_prevents_build` failed once during the first full
`cargo +1.85.0 test --workspace` run. It passes in isolation on stable and 1.85.0, and the full
MSRV workspace suite passed on rerun. `term_fst` is not on the Phase A changed path (only the
batch meter/work borrows changed). Classification: **demonstrated non-deterministic (flaky)
failure**, cause not yet identified; not an introduced Phase A regression, but recorded as an
open observation rather than erased.

## Phase A acceptance
Disjoint borrows proven; no query semantics or current partial memory behavior changed; gates
green. **P2B remains NOT ACCEPTED.** Phases B–F (scoped memory API, candidate/heap, geo/JSON,
projection handoff, full B10–B13 acceptance) are not implemented.
