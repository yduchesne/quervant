# PR 15I-B residual — decision log

| Rule | Trigger | Action |
|---|---|---|
| RES-D01/D02 | Archive tip `ba2a1dd` reachable; required branch renamed to it without rewriting commits | Continued on `dev/pr15i-b-stored-blocks` |
| RES-D07 | Production equals P0 | Restored only the exact direct-source allowlist |
| RES-D13 | Restored diff within allowlist; MSRV compiles | Proceeded |
| RES-D16/D22 | Only one private certified caller; unselected interior checked at certification | Implemented O(k) selected boundary checks |
| RES-D25/D26 | Singleton group | Stack `[u64;1]`; multi uses reused fallible scratch |
| RES-D28/D29 | One-block vs multi-block selection | Direct decoder vector vs single outer vector |
| RES-D33 | Wire format unchanged | Kept 22/40/128 and feature `0x000D` |
| RES-D41/D43 | Old campaigns readable | Extracted ABBA/BAAB association (LZ4 gap 0.153) |
| RES-D49 | Structural counters pass | Froze common LZ4 source, created matched Zstd |
| RES-D51 | Zstd differs only in Cargo files | Ran both campaigns |
| RES-D58 | Zstd 10K rare median 1.1923 > 1.10 | Zstd ineligible; LZ4 continued |
| RES-D59 | Only LZ4 eligible | Selected LZ4, kept exact measured production |
| RES-D64 | Real RustFS v2 executed | 6/6 passed before CI line added |
| RES-D65 | Final QA passes; source identical to measured production | Marked local review-ready pending CI/review |
| RES-D70/D71 | CI/review pending; no push permission | Reported statuses; no push/merge |
