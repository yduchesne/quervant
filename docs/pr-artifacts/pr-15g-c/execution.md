# PR 15G-C execution record

**Status:** `IMPLEMENTATION_CORRECTNESS_PASS_PERFORMANCE_NOT_ACCEPTED`
**Shared branch:** `dev/pr15g-a-retained-column-geometry`
**GC_BASE_SHA:** `018fdd768d0898d6709baeb8661998ee1a82947c`
**B carryover commit:** `97d7ce1bc82c9903304371ce8b45074c3981adf5`
**C measured candidate:** `5ec886f3cbd8666d46b7d3c4a9761abd53e30d4e`
**Final HEAD:** documentation-only closure commit after measurement.
**Umbrella PR:** #86

## Changed paths

- `crates/quervant-core/src/search/execute.rs` — bounded stream visitor and
  test-only counters.
- `crates/quervant-core/src/search/unified.rs` — C eligibility, shared
  `admit_candidate`, C wiring, focused tests.
- `crates/quervant-core/src/segment/{reader,stored}.rs` — **test-only** B
  carryover corrections.
- `crates/quervant-core/tests/pr15g_c_stream.rs` and `pr15g_c_rustfs.rs`.
- `.github/workflows/ci.yml` — one additive C RustFS invocation.
- `benchmarks/pr15g_c/{README.md,run.py,test_run.py}`.
- `docs/pr-artifacts/pr-15g-c/*` and narrow status docs.

No protected format/writer/index/remote/public contract file changed.

## Implementation evidence

- B carryover: 5 lazy-budget tests and 2 K100 operation tests PASS.
- C eligibility: compiled-plan gate, one ascending ordinary sort, no cursor/
  aggregation; all other shapes remain legacy.
- C stage one: full postings decode, `charge_scanned`, live-document work,
  virtual 16/48/64 reservations, BM25 validation for every match, release and
  ledger finish before emission.
- C stage two: reopen immutable postings; no repeat work charging; feed every
  effective-live candidate to the shared admission routine.
- Shared admission: key, sort tuple, cursor (legacy), duplicate-key guard,
  candidate charge, heap preflight/commit/replace and late C score.
- No O(M) match/score vector is retained; the global heap remains K+1 bounded.
- Existing unified/phase4 candidate, batch, cursor, geo/JSON and cancellation
  tests pass unchanged.

## Local QA

| Gate | Result |
|---|---|
| Stable/MSRV fmt | PASS |
| Stable/MSRV Clippy default/all-features | PASS |
| Stable/MSRV workspace tests | **2303 passed, 10 ignored** |
| Stable/MSRV all-feature workspace tests | **2307 passed, 78 ignored** |
| Coverage | **92.69%** |
| `execute.rs` / `unified.rs` line coverage | 93.20% / 96.84% |
| Doc / bench build / scripts | PASS — 108 script checks |
| Python suites | PR15D 83, PR15F 54, A 16, B 18, C 18 PASS |
| C RustFS + A/B RustFS + proxy + K0 + 10× K05 | PASS locally |
| `git diff --check` | PASS |

Logs: `target/pr15g-c/qa/final/`, `target/pr15g-c/rustfs/`.

## Performance

The authorized C campaign was completed. It **failed the binding acceptance
gates**: both mandatory 100K common lanes were slower, and 100K absent/rare and
10K rare were classified `A_FASTER`. No lane was excluded or retimed. See
`performance-qualification.md`.

## Status

Correctness/integration/real-service evidence passes; performance is
**NOT ACCEPTED**. The C code remains on the shared branch for review and must not
be called accepted or merged.
