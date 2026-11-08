# PR 15I-B residual — preflight

- Branch: `dev/pr15i-b-stored-blocks` at `ba2a1dd9847ad438168f6b0b636603b629d47696`
  (the branch holding the archived direct-record report and rollback).
- Branch reconciliation: the older LZ4-only branch tip `7f5b1f7` was preserved
  under `dev/pr15i-b-legacy-lz4-direct`; `dev/pr15i-b-stored-blocks` was moved to
  the archive tip by branch rename, not by reset/rebase. All commits reachable.
- `P0_SHA`: `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb`; production/Cargo/CI at
  preflight were byte-identical to P0.
- Restored direct source: `67d75b58a17e2d99bb689adccbf9bdfd304bfb55`.
- Historical direct campaigns: `lz4-direct-01` (seal
  `4ba9404c…a51de`), `zstd-direct-01` (seal `23a41fb0…fe54`) — read-only.
- Frozen protocol SHA-256:
  `3a63d5b8f208ed15921c3200aaa00e940e7aa30697b1805cd7ce2fa0d86d523a`.
- `origin/main`: `691b6993d15f568617f9302cca0a4677bc50df3e` (unchanged relevant paths).

## Source map (restored direct code)

- `segment/stored_blocks.rs`: `validate_all_blocks`, `validate_offset_slice`,
  `decode_selected_with_offsets`, `decompress_block`.
- `segment/reader.rs`: `ValidatedStoredBlocks`,
  `ensure_stored_blocks_certificate`, `stored_selected_v2`.
- `segment/stored.rs`: `decode_stored_from_validated_offsets`, test observation.
- Frozen controller/verifier/protocol under `benchmarks/pr15i_b/` unchanged.

## Baseline checks executed before implementation

PR15I-A Python tests (87) and PR15I-B Python tests (10) passed; script tests
(108) passed; `cargo +1.85.0 test --locked -p quervant-core --lib segment::stored`
passed; fmt and `git diff --check` passed. Local historical raw campaigns were
present and read-only; their hardened verifier labels them historical negative
evidence.
