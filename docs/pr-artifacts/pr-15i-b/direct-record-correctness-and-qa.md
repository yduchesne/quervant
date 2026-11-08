# PR 15I-B direct-record — correctness and final QA

## Direct-record correctness evidence

Executed before the campaigns and again at the common source:

- `segment/stored_blocks.rs::direct_offsets_tests` (5 tests): flat `N+B`
  geometry for N=0/1/127/128/129/255/256/257, cross-block mapping at block 1
  (`flat index 128+1`), forged offset rejection (first boundary, duplicate,
  terminal, truncated), malformed selection, and hot counters
  (`direct_records`, `hot_block_lookups`, empty-selection zero work).
- `segment/reader::stored_blocks_reader_tests` (9 tests): certificate built once,
  all blocks validated first, `record_ends.len()==N+B`, certified hot path
  inflates only touched blocks, one direct parse per selected record, empty
  selection does no work, zero/no budget uses full validation, metadata cap
  fallback, unselected corruption blocks the certificate, distinct states do not
  share certificates, concurrent first access publishes one certificate,
  initializer panic/poison fails closed.
- `crates/quervant-core/tests/pr15i_b_stored.rs` (20 tests): v2 geometry,
  features, v1/v2 parity, corruption, mixed/compaction/PIT/replay and query
  oracle behavior (restored from the rejected candidate and passing before
  rollback).
- The v2 RustFS suite was restored and compiled; because both codecs were
  rejected at the performance gate, the rollback removed it and it is **not**
  claimed as executed v2 acceptance. PR 15I-A real-RustFS evidence remains valid
  for the restored production.

## Final QA at rollback `7b423fc`

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS (0 failures) |
| `cargo +1.85.0 clippy/test --all-features` | PASS |
| `cargo llvm-cov … --fail-under-lines 85` | PASS, **92.74%** lines |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| PR 15I-A Python tests | PASS (87) |
| PR 15I-B Python tests | PASS (10) |
| `verify.py` on both new campaigns | PASS, both ineligible |
| PR 15I-A P0 campaign verifier | PASS |
| `git diff --check` | PASS |

Production diff from P0 for core/Cargo/CI is empty.

## External status

`HOSTED_CI_PENDING`, `INDEPENDENT_REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`.
