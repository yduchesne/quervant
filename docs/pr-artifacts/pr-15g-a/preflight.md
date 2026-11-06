# PR 15G-A preflight

**Status:** PASS — executed before any source edit.
**Branch:** `dev/pr15g-a-retained-column-geometry`
**Pinned base:** `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc` (merge PR #85 / PR 15F)
**Working tree at preflight:** clean; local `main` equals `origin/main` at the pinned SHA.

## Identity and required evidence

| Check | Result |
|---|---|
| `git rev-parse HEAD` on `main` | `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc` |
| `git status --porcelain` | empty |
| `docs/pr-artifacts/pr-15f/p0-review-fixup.md` | present |
| `benchmarks/reports/pr15f/p0-profile-summary.json` | present |
| SHA-256 of `p0-profile-summary.json` | `384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096` (matches plan) |

## Environment

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.5 LTS under WSL2 |
| Kernel | `6.18.33.2-microsoft-standard-WSL2` |
| Filesystem | `ext4` on `/dev/sdd` (native Linux filesystem, not `/mnt/c`) |
| CPUs | 12 |
| Memory | 31 GiB |
| Stable toolchain | `rustc 1.98.1`, `cargo 1.98.1` |
| MSRV toolchain | `cargo 1.85.0` (installed) |
| Python | 3.12.3 |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Docker / RustFS service | not installed / unavailable locally |

## Source-shape verification

`rg` confirmed the plan's assumed shape before editing:

- `crates/quervant-core/src/segment/column.rs`: `ColumnMeta` has exactly the
  eight primitive fields (`field_id`, `type_tag`, `layout`, `doc_count`,
  `block_count`, `block_docs`, `dir_offset`, `data_base`); `ColumnReader` owned
  `Vec<ColumnMeta>` plus query-local `Cell<u64> blocks_read`; parser entry points
  `open`, `open_with_doc_count`, `try_reserve_exact`, and all structural checks
  are present.
- `crates/quervant-core/src/segment/reader.rs`: `VerifiedSegmentState` and
  `DecodedMetadata` fields, `decode_allowance`, `measured_charge`,
  `decode_metadata`; eager `ColumnReader::open_with_doc_count` validation
  discarded its reader; `open_columns` and `column_value` re-parsed each call.
- `crates/quervant-core/src/index/snapshot.rs`: `SlotState::{Empty,Building,
  Ready}`, per-segment mutex/condvar, `MetadataBudget`/`MetadataMeter`, and
  `build_cached` candidate/fallback lifecycle are unchanged.
- `crates/quervant-core/src/search/typed_compare.rs`: `ColumnAccess::open` uses
  `SegmentReader::open_columns`; no comparator change was needed.

Raw command output: `target/pr15g-a/qa/preflight-source.log`.

## Baseline test evidence (before edits)

| Command | Result | Log |
|---|---|---|
| `cargo test -p quervant-core --lib segment::column` | PASS, 0 tests (no column unit module existed) | `target/pr15g-a/qa/baseline-column-lib.log` |
| `cargo test -p quervant-core --lib index::snapshot` | PASS, 51 passed | `target/pr15g-a/qa/baseline-snapshot-lib.log` |
| `cargo test -p quervant-core --lib segment::reader` | PASS, 2 passed | `target/pr15g-a/qa/baseline-reader-lib.log` |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | PASS, 5 passed | `target/pr15g-a/qa/baseline-pr15c-a.log` |

No PR 15F source drift, frozen report rewrite, report edit or format change was
made. The branch was created only after these checks.
