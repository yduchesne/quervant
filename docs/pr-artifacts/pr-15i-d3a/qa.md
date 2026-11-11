# PR 15I-D3-A QA

Status: pre-measurement QA pending. The final gate table is regenerated after
the last source/test/tooling change.

## Required commands

```sh
python3 -m py_compile benchmarks/pr15i_d3a/*.py
python3 -m unittest discover -s benchmarks/pr15i_d3a -p 'test_*.py' -v
python3 benchmarks/pr15d/harness/test_pr15d.py
python3 -m unittest discover -s benchmarks/pr15i_d2a -p 'test_*.py' -v
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --no-deps
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
cargo +1.85.0 doc --workspace --no-deps
git diff --check
git diff --exit-code "$BASE_SHA" HEAD -- crates/ Cargo.toml Cargo.lock .github/ AGENTS.md benchmarks/pr15d/ benchmarks/pr15i_d2a/
```

RustFS: `RUSTFS_NOT_RUN_NOT_REQUIRED_FOR_D3A_ATTRIBUTION` locally; no local
RustFS result is reported as PASS.
