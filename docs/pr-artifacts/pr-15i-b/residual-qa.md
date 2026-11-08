# PR 15I-B residual — QA

Final code SHA `9da20614f58313259fcceb5ff8fa997e6afc7d7c` (production identical
to measured LZ4 `5703a3d`). Zstd measured `6bbdd73`, ineligible.

| Check | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| stable `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS |
| MSRV 1.85 clippy + `--all-features` tests | PASS |
| `cargo llvm-cov … --fail-under-lines 85` | PASS, **92.67%** lines |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| PR 15I-B Python tests | PASS (10) |
| PR 15I-B residual tests | PASS (2) |
| PR 15I-A historical verifier tests at P0 worktree | PASS (87) |
| Real RustFS v2 suite (`pr15i_b_rustfs -- --ignored`) | PASS 6/6 |
| Real RustFS PR15I-A suite | PASS 4/4 |
| Real RustFS PR13 fault proxy | PASS 7/7 |
| New campaign verifiers (LZ4/Zstd) | PASS; LZ4 qualified, Zstd ineligible |
| `git diff --check` | PASS |

## Historical-test applicability

The four PR15I-A `RealCampaignTests` are source-bound to the PR15I-A measured
candidate and intentionally reject the v2 winner branch. They were executed and
passed at the P0 worktree (87/87); on the v2 branch they are `NOT_APPLICABLE`
historical evidence checks, not a v2 regression.

## External status

`HOSTED_CI_PENDING`, `INDEPENDENT_REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`.
