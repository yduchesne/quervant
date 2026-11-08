# PR 15I-B direct-record — preflight

- Branch: `dev/pr15i-b-stored-blocks`
- `CONTINUATION_BASE_SHA`: `3c2ff89dd2a0a19347a54475c34f678ff583c4a0`
- `P0_SHA`: `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb`
- `P1_SHA`: `178c000b7e0bbc44b9f4e439755a36aadbb7ec7f`
- Old rejected LZ4 source: `bfdb9b0d95de171c72be1de26e4501fc701df988`
- `origin/main`: `691b6993d15f568617f9302cca0a4677bc50df3e` (unchanged)
- Frozen protocol: `benchmarks/pr15i_b/protocol.json`,
  SHA-256 `3a63d5b8f208ed15921c3200aaa00e940e7aa30697b1805cd7ce2fa0d86d523a`
- Restoration diff: exactly the §3.1 allowlist (13 tracked paths plus the three
  files absent after rollback: `stored_blocks.rs`, `pr15i_b_stored.rs`,
  `pr15i_b_rustfs.rs`).
- MSRV compatibility: two `let`-chains in the restored `reader.rs` were rewritten
  as nested `if let` for Rust 1.85; behavior is identical. `cargo +1.85.0 check
  --locked -p quervant-core` passes.
- `git diff P0..HEAD -- core/Cargo/CI` was empty before restoration.
- Historical campaigns `lz4-05`/`zstd-01` remain untouched and are negative
  evidence only.

Baseline checks before implementation: PR15I-A and PR15I-B Python suites pass,
`benchmarks/scripts/test-scripts.sh` passes (108), `cargo fmt` and
`git diff --check` pass.
