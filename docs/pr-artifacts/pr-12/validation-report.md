# PR 12 — Validation report (corrective pass)

## Tested state

- Branch: `dev/geopoint-spatial-pr12`.
- Base `main`: `46ee2ad44db5562c53736cfbfea0ec6ac4e3e8b8`; feature commit `1a44349`.
- Corrective changes are in the working tree on top of `1a44349`; all mandatory
  checks below were run on the final corrective code (documentation-only edits
  follow the code freeze).
- Toolchains: stable `rustc 1.98.1 (48a229cea 2026-09-01)`, MSRV
  `cargo 1.85.0 (d73d2caf9 2024-12-31)`, `cargo-llvm-cov 0.9.1`.
- New dependency: `robust` v1.2.0 (MIT OR Apache-2.0, GeoRust/Spade, edition
  2021), resolved by Cargo as Rust 1.85-compatible; API verified from the
  fetched crate source before use.

## Gate results

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --test pr12_geo` | PASS — 25 passed, 0 failed |
| `cargo test --workspace --all-targets` | PASS — 0 failures; `quervant-core --lib` 509 passed |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 0 failures |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — workspace line coverage **91.88%** |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |
| `git diff --check` | PASS |

### Coverage detail (line coverage)

| File | Lines | Missed | Coverage |
|---|---:|---:|---:|
| `search/geo.rs` | 851 | 9 | 98.94% |
| `search/typed.rs` | 3655 | 387 | 89.41% |
| `segment/spatial.rs` | 924 | 89 | 90.37% |
| `index/merge.rs` | 1549 | 259 | 83.28% |
| **TOTAL** | **51629** | **4190** | **91.88%** |

## Integration topology

- Real `IndexWriter` → `ReaderSnapshot` → `TypedSearcher` over `MemoryDirectory`
  for the functional and scratch-budget cases.
- Real `FsDirectory` create → commit → drop → reopen → query for T18.
- Real `FsDirectory` legacy-generation fixture: real writer commits, the
  manifest is rewritten to a v1 legacy generation and the segments have the
  `SpatialPoints` section/feature stripped, then the public `IndexWriter::compact`
  path is exercised and the generation is checked unchanged (L01–L04).
- Real `SegmentReader::open` with digest-valid rebuilt containers for T09/T10/T10b.
- `robust::orient2d` is the production polygon predicate; the test oracle uses an
  independent `i128` integer-grid reference and independent interval code.
- No mocks substitute for the KD, search, merge or FsDirectory paths.

## Benchmark (KD vs brute force)

`cargo bench -p quervant-core --bench geo` asserts equal hit counts before
reporting. Final run: points=30,000, hits=1,171, KD exact checks=1,265,
brute-force checks=30,000.

| Arm | Median latency |
|---|---|
| `geo_kd_candidates` | ≈34–38 µs |
| `geo_bruteforce_scan` | ≈66–69 µs |

No speed threshold is asserted; broad shapes may still scan all points.

## Unresolved failures and exceptions

None. No mandatory check was waived, skipped or replaced by CI-only evidence, and
no documented exception was required.
