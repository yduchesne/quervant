# PR 15I-B direct-record — decision log

| Rule | Trigger | Action | Gate |
|---|---|---|---|
| DR-D01 | Correct branch, clean, P0 descendant | Pinned continuation and proceeded | S0 |
| DR-D07 | Old LZ4 source reachable and symbols matched | Restored exact allowlist | S1 |
| DR-D19 | Restored source builds with LZ4 and Rust 1.85 after nested-if fix | Proceeded | S1 |
| DR-D21 | v1 payload bytes and wire format unchanged | Captured offsets only in memory | S2 |
| DR-D25 | N+B flat boundaries captured and validated | Retained `Vec<u64>` certificate | S2 |
| DR-D29 | First STORED access full semantic scan | Captured offsets and published once | S3 |
| DR-D31 | Metadata budget optional capacity | `Ok(false)` full-validation fallback | S3 |
| DR-D35 | Valid certificate, selected ID | One block lookup/inflate/direct parse | S3 |
| DR-D49/D50 | Verifier raw/source hardening | Exact inventory/provenance before gates | S4 |
| DR-D57 | Absolute RSS cap | Independently checked <=16 MiB | S4 |
| DR-D59 | LZ4/Zstd non-Cargo source identical | Ran both source-locked campaigns | S7 |
| DR-D68 | Both fail B-P06 with valid evidence | Marked both ineligible, preserved blocks | S7 |
| DR-D72 | Neither codec eligible | Additive rollback to P0, kept evidence | S8 |
| DR-D77 | Final local QA passes at rollback | Reported pending CI/review only | S9 |
