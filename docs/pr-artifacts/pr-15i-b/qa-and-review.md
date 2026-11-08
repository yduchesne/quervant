# PR 15I-B — QA and review status

**Final code state:** rollback commit `c5180a7012e678d6fa938c747b18990201621d11`
on `dev/pr15i-b-stored-blocks`; production is byte-identical to P0
(`git diff 0cf7dec..HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml Cargo.lock .github/workflows/ci.yml` is empty).

## Local QA at the final rollback state

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS (0 failures) |
| `cargo +1.85.0 clippy …` / `cargo +1.85.0 test …` | PASS |
| `cargo llvm-cov … --fail-under-lines 85` | PASS, **92.74%** lines |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| `git diff --check` | PASS |
| PR 15I-A Python verifier tests | PASS (87) |
| PR 15I-B controller/verifier tests | PASS (10) |
| Sealed campaign verification (`lz4-05`, `zstd-01`) | PASS, both `B_CANDIDATE_INELIGIBLE` |

## Real boundaries

- PR 15I-A real-RustFS evidence (`pr15i_a_rustfs`) was executed and passed before
  this PR; production is now identical to that state.
- PR 15I-B v2 RustFS tests (`pr15i_b_rustfs.rs`) were implemented and compiled but
  were removed by the prescribed safe rollback; they were **not** used as
  acceptance evidence because both codec candidates were rejected at the
  performance gate before P4 acceptance. No v2 real-RustFS pass is claimed.
- P0/P1 diagnostics used the pinned historical sources and frozen corpus; no
  remote service was needed.

## External gates

- **Hosted CI: `HOSTED_CI_PENDING`** — branch has no upstream and was not pushed.
- **Independent review: `INDEPENDENT_REVIEW_PENDING`.**
- **NOT_PUSHED, NOT_MERGED.**

## Applied matrix rules

P0: IB-D01, IB-D06, IB-D09, IB-D10, IB-D12. P1: IB-D16, IB-D20, IB-D24.
P3: IB-D50–D55 (neither candidate eligible → safe rollback), IB-D56 (no
contention observed), IB-D58 (seal verified). P5: IB-D62 (local QA), IB-D68
(hosted CI pending). No HARD STOP from a technical defect.
