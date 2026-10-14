# PR 9 validation report

**Base:** `17fd2b674365bb656ce5f3ea22de5a52cd4bf80f` (`main` after PR #26).
**Tested tree:** `dev/stable-key-mutations`, 31 changed/new paths, uncommitted.
**Toolchains:** Rust `1.98.1` (active stable) and Rust `1.85.0` (workspace MSRV,
`rust-version`).

This report records commands actually executed on the final tree. A green remote
CI status is not claimed and would not replace these commands.

## Gate results

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (1.98.1) | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` (1.98.1) | PASS — 1207 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — no failures |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **91.32%** workspace line coverage |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench -p quervant-core --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |

PR 9 test suites (each executed individually and also as part of the workspace
run):

| Suite | Result |
|---|---|
| `cargo test -p quervant-core --test pr09_mutations` | PASS — 13 passed |
| `cargo test -p quervant-core --test pr09_visibility` | PASS — 6 passed |
| `cargo test -p quervant-core --test pr09_recovery` | PASS — 4 passed |
| `cargo test -p quervant-core --test pr09_merge` | PASS — 6 passed |
| `cargo test -p quervant-core --test pr09_reclamation` | PASS — 5 passed |
| `cargo test -p quervant-core --test pr09_properties` | PASS — 1 passed |

Coverage detail for the new PR 9 modules:

| Module | Line coverage |
|---|---|
| `index/mutation_state.rs` | ≥ 90% (workspace aggregate 91.32%) |
| `index/visibility.rs` | ≥ 90% |
| `index/merge.rs` | ≥ 90% |
| `index/reclaim.rs` | ≥ 90% |
| `index/writer.rs` | 90.03% |

Exact per-file figures are in the `cargo llvm-cov` output; the aggregate line
coverage is **91.32%**, above the mandatory 85% floor, with no exclusions.

## Benchmark results (actual)

`crates/quervant-core/benches/merge.rs`, criterion
`--sample-size 10 --measurement-time 3 --warm-up-time 1`, synthetic documents
with one `indexed+stored` text field, one document per key and every other key
tombstoned before commit.

| Size | `compact` median | Compact throughput | Search before median | Search after median |
|---|---|---|---|---|
| 2 000 | 1.22 ms | 1.64 Melem/s | 3.33 ms | 1.79 ms |
| 10 000 | 6.01 ms | 1.66 Melem/s | 3.33 ms (2 000-doc corpus) | 1.79 ms |
| 100 000 | 61.85 ms | 1.62 Melem/s | 171.6 ms | 114.4 ms |

These are machine- and dataset-specific; they are not claims of universal
throughput. Correctness was verified by T24 (before/after merge hit set and BM25
score equivalence) before timing.

## Failure classification

- No introduced regressions: the full workspace suite (including all PR 5–8
  frozen fixtures) passes on both toolchains.
- No reproducible pre-existing failures encountered.
- **Not covered (feature gaps, not regressions):**
  - T06 revision-overflow injection (the `checked_add`/`RevisionOverflow` path
    exists but is not dynamically injected).
  - T30 indeterminate post-`CURRENT` poisoning (the pre-`CURRENT` barrier is
    covered by T12/T36; the post-replacement path is not injected).
  - T35 cooperative cancellation during merge/state decode (not implemented).
- No waived gates. All mandatory local gates above were executed on the final
  tree.

## Environment / topology

- Local-only `MemoryDirectory` and temporary real `FsDirectory`; no RustFS,
  network or distributed services are required or used by PR 9.
- Stable and MSRV Clippy/format/test were run from the workspace root.
