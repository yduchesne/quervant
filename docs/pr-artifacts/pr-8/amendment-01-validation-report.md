# PR 8 Amendment 01 validation report

**Tested working tree:** `64edd5f2bf0919a9836472481c069bc7428172bf` plus the
amendment-01 code/test/doc changes (pre-commit); all commands below were executed
from the workspace root after the final source/test change.
**Branch:** `dev/advanced-lexical`
**Toolchains:** stable Rust 1.98.1; MSRV Rust 1.85.0.

## Gate results

| Command | Stable | MSRV 1.85.0 |
|---|---|---|
| `cargo fmt --all -- --check` | PASS | PASS (toolchain-independent) |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS | PASS |
| `cargo test --workspace --all-targets` | PASS — **1167 passed, 0 failed, 7 ignored** | PASS — **1167 passed, 0 failed, 7 ignored** |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | PASS — **91.91% lines** | not required |
| `cargo doc --workspace --no-deps` | PASS | not required |
| `cargo bench -p quervant-core --no-run` | PASS | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed | not required |

### Amendment-focused suites

| Suite | Result |
|---|---|
| `cargo test -p quervant-core --lib` | 379 passed, 0 failed (was 360; +19 intern/FST/budget module tests) |
| `cargo test -p quervant-core --test pr08_amendment01` | 15 passed, 0 failed |
| `cargo test -p quervant-core --test pr08_unit` | 21 passed |
| `cargo test -p quervant-core --test pr08_properties` | 8 passed |
| `cargo test -p quervant-core --test pr08_faults` | 5 passed |
| `cargo test -p quervant-core --test pr08_integration` | 8 passed |
| `cargo test -p quervant-core --test pr08_domain` | 4 passed |
| all `pr07_*` suites | PASS (no assertion changed) |

## Coverage

Workspace total **91.91% lines** (floor 85%; previous branch 91.86%). Changed
modules:

| Module | Lines |
|---|---:|
| `search/term_fst.rs` | 93.35% |
| `search/expand.rs` | 92.32% |
| `search/execute.rs` | 94.77% |
| `search/limits.rs` | 96.01% |

No production crate/module was excluded. Coverage is necessary but not
sufficient; exact-limit, cancellation, amplification and oracle tests pass
independently.

## Diagnostic benchmark disclosure

`cargo run --release -p quervant-core --example pr08_bench -- <vocab>` on the same
identity-keyword workload. Latency includes the per-request derived-FST build.

| Vocab | `Term` p50 | prefix-selective p50 | fuzzy-1 p50 | phrase p50 | broad prefix |
|---:|---:|---:|---:|---:|---|
| 2,000 | 5.99 ms | 6.22 ms | 6.20 ms | 9.58 ms | ResourceLimit |
| 10,000 | 28.78 ms | 29.80 ms | 28.97 ms | 53.06 ms | ResourceLimit |

The amendment's added charged preflight walk is within run-to-run noise of the
pre-amendment numbers (pre-amendment 2K prefix 5.6 ms, 10K prefix 27.9 ms); the
dominant cost remains the existing per-request segment open/dictionary decode.
No cross-engine speedup is claimed and PR 7 Amendment #5 qualified benchmarks were
not rerun (no scoring/codec change).

## Integration topology

Local only: `MemoryDirectory` and real `FsDirectory`; no RustFS, network or
distributed service. Real production path:
`IndexWriter -> commit -> Index::open_existing -> ReaderSnapshot/PIT ->
LexicalSearcher`. Frozen `pr07_pre_norms_v1` fixture bytes are asserted unchanged.

## Failure classification

- No introduced regressions, feature defects, flaky tests or environment
  failures.
- No pre-existing failures observed on the amendment tree.
- No gate was BLOCKED or waived; no exceptions were requested.

## Unresolved / residual

- `fst::Set::from_iter` does not expose fallible allocation; an allocator OOM
  during build cannot be mapped to `ResourceLimit`. The builder is streaming and
  bounded by the output size plus the longest key; this is disclosed as a residual
  risk, not concealed. See `amendment-01-adversarial-review.md`.
- CI/merge status is **not** claimed. `docs/ROADMAP_V01.md` PR 8 remains
  `PLANNED` until merge/CI evidence exists.
