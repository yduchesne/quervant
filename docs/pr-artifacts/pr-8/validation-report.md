# PR 8 validation report

**Tested working tree:** `cbfb5ec774f77e03c7d48b3baf8a47c407bed7f4` (all code and
tests) plus the documentation-only follow-up commit containing this report.
**Branch:** `dev/advanced-lexical`
**Machine:** local Linux dev workstation (x86_64).
**Toolchains:** stable Rust 1.98.1; MSRV Rust 1.85.0 (`workspace rust-version = 1.85`).

All commands were executed from the workspace root after the final source/test
change. No gate was waived and no command was retried to hide a failure.

## Gate results

| Command | Stable | MSRV 1.85.0 |
|---|---|---|
| `cargo fmt --all -- --check` | PASS | PASS (formatting is toolchain-independent) |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS | PASS |
| `cargo test --workspace --all-targets` | PASS — 1133 passed, 0 failed, 7 ignored | PASS — 1133 passed, 0 failed, 7 ignored |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | PASS — 91.86% lines | not required |
| `cargo doc --workspace --no-deps` | PASS | not required |
| `cargo bench -p quervant-core --no-run` | PASS | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed | not required |

### Focused PR 8 suites

| Suite | Result |
|---|---|
| `cargo test -p quervant-core --lib` | 372 passed, 0 failed |
| `cargo test -p quervant-core --test pr08_unit` | 21 passed |
| `cargo test -p quervant-core --test pr08_properties` | 8 passed |
| `cargo test -p quervant-core --test pr08_faults` | 5 passed |
| `cargo test -p quervant-core --test pr08_integration` | 8 passed |
| `cargo test -p quervant-core --test pr08_domain` | 4 passed |
| all existing `pr07_*` suites | PASS (one obsolete PR 7 "prefix unsupported" assertion updated to `Exists`; see below) |

## Coverage

`cargo llvm-cov` workspace total: **91.86% lines** (floor 85%). New modules:

| Module | Lines |
|---|---:|
| `search/automaton.rs` | 85.61% |
| `search/term_fst.rs` | 91.76% |
| `search/expand.rs` | 91.43% |
| `search/plan.rs` | 89.83% |
| `search/execute.rs` | 94.76% |

Uncovered lines in the new modules are typed-error/overflow branches and
platform-conditional paths; the acceptance behaviours are covered by T01–T44.
No production crate or module was excluded from the measurement.

## Diagnostic benchmark (PR 8 plan §7)

`cargo run --release -p quervant-core --example pr08_bench -- <vocab>` on an
identity-keyword synthetic vocabulary (one segment per 10,000 docs). Latency
includes the per-request derived FST build; broad patterns exceeding the default
1,024 expanded-term budget fail closed with `ResourceLimit`.

| Vocab | `Term` | prefix-selective | glob-selective | regex-selective | fuzzy-1 | phrase (all) | prefix-broad |
|---:|---:|---:|---:|---:|---:|---:|---|
| 2,000 | 5.9 ms | 5.6 ms | 5.6 ms | 5.8 ms | 5.8 ms | 8.9 ms | ResourceLimit |
| 10,000 | 26.1 ms | 27.9 ms | 27.6 ms | 27.6 ms | 27.2 ms | 45.9 ms | ResourceLimit |
| 100,000 | 270.8 ms | 294.6 ms | 286.0 ms | 291.1 ms | 291.0 ms | 467.6 ms | ResourceLimit |

Observation: the derived-FST increment over the matching `Term` control is
≈1–2 ms per 10,000 terms; the dominant cost is the existing per-request segment
open/dictionary decode (PR 7 architecture), not PR 8 expansion. No cross-engine
speedup is claimed; full Quervant/Tantivy/Lucene qualification belongs to PR 15.

## Integration topology

- Local only: `MemoryDirectory` and real `FsDirectory`; no RustFS, no network, no
  distributed service, no vector dependency.
- Real production path exercised: `IndexWriter -> commit/refresh ->
  Index::open_existing -> ReaderSnapshot/PIT -> LexicalSearcher`.
- Frozen legacy fixture `tests/fixtures/index/pr07_pre_norms_v1` reused without
  regeneration; its hashes are checked by the PR 7 compatibility suite.

## Pre-existing regression handling

`tests/pr07_faults.rs::f01_unsupported_nested_operator` previously asserted that
`Query::Prefix` is unsupported. PR 8 makes prefix executable by design, so the
test now asserts the same invariant with the still-unsupported `Query::Exists`.
This is the only changed PR 7 assertion; all other PR 7 suites pass unchanged.

## Unresolved failures / exceptions

- None. Every mandatory gate above passed on the final tree.
- No local gate was BLOCKED and no exception was requested.
- CI status and merge are **not** claimed by this report; the roadmap PR 8 entry
  remains `PLANNED` until merge/CI evidence exists.
