# PR 3 Stage 3B — Amendment #5 report

**NO MERGE.** Branch `dev/storage-abstraction`; do not open or merge a PR.

## SHAs

- Starting (reviewed) HEAD: `e0404a2d72c20b33a8e8d11c098c23b9709ad6cf`
- Implementation commit: `308531a`
- Documentation commit: `e96e6ba`
- Branch HEAD after this report: the commit that contains it (see the push record)
  on `dev/storage-abstraction`.

## Changed files

- `crates/trawler-core/src/storage/cache.rs` — crash-temp classification,
  measure-before-delete reconciliation, tri-state failed-write probe,
  `uncertain_bytes` accounting, stale-comment fix.
- `crates/trawler-core/src/storage/a3_io.rs` — A5-01..12 and fault-injection
  doubles (`FaultDirectory`, `RenameFailDirectory`).
- `docs/decisions/PR03_CRASH_TEMP_RECOVERY.md` (new),
  `docs/decisions/PR03_PHYSICAL_CACHE_ACCOUNTING.md`,
  `docs/decisions/PR03_FS_OFFLOAD_DESIGN.md`, `docs/ARCHITECTURE.md`,
  `docs/TESTING.md`.
- `docs/pr-artifacts/pr-3/amendment-05-report.md` (this report).

## Design decisions

- **Temporary grammar (F1):** exactly
  `.trawler-tmp-<decimal pid>-<decimal counter>`; lookalikes are unknown files
  and fail reconciliation closed. `cache-v1-*` (content), `tmp-v1-*` (legacy
  cache temp) and `.trawler-tmp-*` (filesystem temp) are distinct classes.
- **Recovery order:** list → measure every regular file (fail closed on any
  metadata/scan error) → charge recognized files → delete recognized
  temporaries. A failed temp delete keeps the charge (`delete_failed`,
  `delete_failures`) and is retried at most once per admission.
- **Tri-state probe (F2):** `Present(len)` / `Absent` / `Indeterminate`.
  Determinate residual files are charged and the reservation released;
  `Indeterminate` retains the reservation as `uncertain_bytes`, re-arms
  reconciliation, and blocks admission until a full scan succeeds.
- **Exclusivity:** a dedicated, exclusively owned cache root is assumed; PID is
  not a staleness proof. Concurrent instances on one root remain unsupported
  (would require a public lock API — not added).
- **No API/format change:** only internal helpers and `CacheStats` fields (from
  A4) are involved; no manifest, no constructor change, no new dependency.

## Test results

A5 suite (`cargo test -p trawler-core --lib a5_`), all **PASS**:

| ID | Scenario | Result |
|---|---|---|
| A5-01 | Real `.trawler-tmp-*` recognized, charged, cleaned on reopen | PASS |
| A5-02 | Partial temp charged at actual size | PASS |
| A5-03 | Temp delete fails: charge retained, bounded retry, no over-admission | PASS |
| A5-04 | Successful cleanup restores capacity exactly once | PASS |
| A5-05 | Unknown file and malformed temp names fail closed | PASS |
| A5-06 | Symlink to outside never followed or deleted | PASS |
| A5-07 | Indeterminate destination probe retains charge; repairs clear it | PASS |
| A5-08 | Verified `NotFound` releases only after temp inventory | PASS |
| A5-09 | Post-rename failure charges destination, never publishes | PASS |
| A5-10 | Cancellation during a real write reconciles without leak | PASS |
| A5-11 | Concurrent fills + crash-temp cleanup preserve the bound | PASS |
| A5-12 | Scan failure refuses admission; repaired root recovers | PASS |

Retained suites (all PASS): D-KEY01–08, D-API01–08, F-01–08, O-01–12, C-01–14,
A2-ASYNC-01–12, A3-IO-01–14, A4-01–16.

## QA commands and results

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` (GNU) | **263 passed, 0 failed** |
| `cargo test --workspace --all-targets --target x86_64-unknown-linux-musl` | **263 passed, 0 failed** |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` (GNU) | **PASS — 94.51% lines** |
| musl coverage | **PASS — 94.51% lines** |
| `cargo doc --workspace --no-deps` | PASS |
| `git diff --check` | PASS |

## Invariant proof sketch

`physical_bytes = known_bytes + reserved_bytes + uncertain_bytes <= max_cache_bytes`
where every cache-owned regular file is represented by at most one ledger
entry.

- Admission requires the sum to fit; eviction only removes charged unpinned
  files and only a successful delete releases the charge.
- A failed write charges the measured residual (destination and/or internal
  temporaries) before releasing the reservation; if any measurement is
  indeterminate, the reservation becomes `uncertain_bytes` and reconciliation
  re-arms, so no fill can be admitted while the on-disk state is unknown.
- Reconciliation (offloaded, before admission) measures all files before any
  deletion and charges everything that remains; a successful full scan clears
  `uncertain_bytes`.
- Temp/destination overlap is covered because the existing destination is
  already charged and the reservation covers the new temp growth.

## Limitations

- Logical content-length bound only; not device blocks, metadata, sparse
  allocation, or unrelated writers.
- Exclusive single-instance ownership of the cache root is required and
  documented; multi-instance coordination is out of scope.
- A permanent delete failure keeps bytes charged until a later bounded retry or
  restart.
- RustFS production adapter remains PR 13 (SKIP, not PASS).

## Dependencies / licensing / MSRV

No dependency changes. `trawler-core -> trawler-objectstore -> sha2`; `futures`
dev-only; **no Tokio**; all resolved packages MSRV <= 1.85 and permissive
licenses; `#![forbid(unsafe_code)]`; no unsafe.

## STOP gates

None triggered: no breaking public API/format/coordination change; verified
absence is distinguished from indeterminate state; crash artifacts are charged
before admission; temp cleanup never deletes unrelated or live files (dedicated
root assumption); no hang/spin/leak; tests pass and coverage is 94.51% >= 85%.

**NO MERGE.**
