# PR 15I-D3-C — preflight

Executed before any edit. No protected path changed.

| Check | Result |
|---|---|
| Branch | `dev/pr15i-d3b-retained-key-prefilter` |
| HEAD | `99652d75bca3ac674b1ad6a32176b413a8144574` |
| `main` / `origin/main` | `39dbd9f571a58bea8cc03d5a406533298e809bfe` (both) |
| BASE / rejected / rollback / T3 objects | `39dbd9f5…`, `48d9abf3…`, `5d3bf1f7…`, `c86c3b15…` all present |
| `unified.rs` at BASE and HEAD | `b2978021…` — byte-identical; BASE linear behavior |
| T0/T1/T2/T3 tooling diffs vs HEAD | all empty |
| Working tree | only the pre-existing user `disk-cleanup.sh` edit; untouched |
| Duplicate-check census | three sites (owned, legacy keyword, borrowed keyword) |
| Heap admission calls | four (owned, legacy, borrowed fill, borrowed replace) |
| Rust / MSRV / Python | stable 1.98.1, `cargo +1.85.0` 1.85.0, Python 3.12.3, cargo-llvm-cov 0.9.1 |

No D3-C namespace existed before this run.
