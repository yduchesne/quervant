# PR 12 — Validation report

## Tested state

- Base commit: `46ee2ad44db5562c53736cfbfea0ec6ac4e3e8b8` (fresh `main` after PR #33).
- Branch: `dev/geopoint-spatial-pr12`.
- Working tree: modified/new files listed by `git status` (see implementation
  report); no reverted or partial files. All mandatory checks were rerun after
  the final source/test change.
- Toolchains: stable `rustc 1.98.1 (48a229cea 2026-09-01)`, MSRV
  `cargo 1.85.0 (d73d2caf9 2024-12-31)`, `cargo-llvm-cov 0.9.1`.

## Gate results

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --lib` | PASS — 474 passed, 0 failed |
| `cargo test --workspace --all-targets` | PASS — 0 failures across all targets; `pr12_geo` 21 passed |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 0 failures across all targets |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — workspace line coverage **91.75%** |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench -p quervant-core --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |
| `git diff --check` | PASS |

### Coverage detail (line coverage)

| File | Lines | Missed | Coverage |
|---|---:|---:|---:|
| `search/geo.rs` | 332 | 5 | 98.49% |
| `segment/spatial.rs` | 924 | 89 | 90.37% |
| `search/typed.rs` | 2888 | 348 | 87.95% |
| `contract/value.rs` | 541 | 14 | 97.41% |
| `index/merge.rs` | 1549 | 262 | 83.09% |
| **TOTAL** | **50343** | **4152** | **91.75%** |

`index/merge.rs` is below 85% per file but the repository gate is the
workspace `--fail-under-lines 85`, which passes. New spatial paths there
(feature/section build, remap, legacy fallback) are exercised by `t12`; the
remaining uncovered merge lines are pre-existing failure/recovery branches.

## Integration topology

- Real `IndexWriter` → `ReaderSnapshot` → `TypedSearcher` over `MemoryDirectory`
  for T01–T17.
- Real `FsDirectory` create → commit → drop → reopen → query for T18.
- Real compaction (`IndexWriter::compact`) with delete+upsert for T12/T13.
- Real `SegmentReader::open` with digest-valid rebuilt containers for T09/T10.
- No mocks substitute for the writer/reader/searcher/compaction paths. RustFS
  integration belongs to PR 13 and is not required by PR 12.

## Oracle

300 seeded deterministic cases (SplitMix64 seed `0x5151_2024`, 0–1000 docs,
0–8 points/doc) plus 120 polygon points compare sorted hit keys against a
separately implemented circular bbox, haversine and ray-casting oracle. `t10b`
adds 35 digest-valid malformed spatial bodies that must all fail closed. Hand-verified zero distance, equatorial
quarter-circumference and ±180 alias are asserted directly.

## Benchmark

`geo_kd_candidates` performs 1,265 exact checks (vs 30,000 brute-force) and
measures ≈27–29 µs median vs ≈67–71 µs for the brute-force scan on the same
points; hit counts are asserted equal before timing. The benchmark makes no
fabricated speedup claim and discloses that broad shapes may scan all points.

## Unresolved failures and exceptions

None. No check was waived, skipped, or replaced by CI-only evidence. No
documented exception was required.
