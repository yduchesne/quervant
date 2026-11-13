# PR 15I-D3-C — session correctness closure ledger

- Starting HEAD: `6078cd28dbe32ee9e7eadc4f4811185e34dbf7c4`
- Experimental source commit: `3ad6c5184fbe9c011abb731415a007e3f19d21de`
- Tooling commit: `b57a5e05ee3129bf1043d9e7af88e27f87b638a6`
- BASE/main: `39dbd9f571a58bea8cc03d5a406533298e809bfe`
- Historical tooling diffs: empty for `pr15i_d3_b`, `_f1`, `_f1_1`, `_f1_2`.

## Executed correctness

- Integration: 12 passing tests in `pr15i_d3_c.rs` (I01, I02, I03, I04,
  I04 extension, I05, I06, I07 ×2, I08, I09, I10, I12 ×2 — one of these is the
  no-feature child, the other the parent; I11 is separate).
- I11: real RustFS m1/m2 each `1 passed; 0 failed; 0 ignored`.
- Unit: `d3c_tests` 37 passed, 1 ignored. Added U22, U24, U25, U34, U40, U42;
  retained U43.
- U23: existing `b_fixup_...` codec precedence test PASS; I08 real-FsDirectory
  malformed-sort precedence PASS.
- U35: no-feature child/parent pair PASS with invalid experiment env and zero
  `PR15I_D3C_MODE=` markers.
- U38: `run.py adapter-compare` sends three post-marker queries per arm and
  rejects a second stderr marker.
- I09 note: the unified lexical path does not consult
  `max_topk_heap_bytes`; the resource-rejection subcase therefore uses the
  enforced `max_total_candidate_bytes(1)` bound. This pre-existing gap was not
  changed and is a residual risk for any future heap-byte accounting work.

## Explicit residual gaps (not PASS)

- U24/U25 now exercise legacy and borrowed duplicate guards with real encoded
  columns. The owned-general inline guard has no separate standalone U witness;
  its shared check is covered by state tests and `g_b04`.
- U40 now proves score-bit and two-page cursor parity across separate
  linear/P2/exact_set processes.
- PM11 and PM12 now execute. PM12 uses explicitly synthetic two-campaign data.

## Memory

- Fresh 900-record micro at source `8f6e353...`, P2 selected.
- K1024 exact-set estimate `1,120,256` bytes (capacity 1792 × 40 + 1,048,576).
- `policy.py` now validates all 900 combinations, recomputes the nine-K map,
  requires source/protocol identity, and applies the inclusive 2,097,152-byte
  guard per K. It no longer excludes H unconditionally.
- PM01–PM10 pass; PM11/PM12 not run.

## QA evidence

- `cargo test --workspace --all-targets`: 2,478 passed, 0 failed.
- `cargo test --workspace --all-targets --all-features`: 2,514 passed, 0 failed.
- `cargo llvm-cov --workspace --all-targets --fail-under-lines 85`: PASS,
  93.17% region / 92.62% line coverage.
- `cargo doc --workspace --no-deps`: PASS.
- Python: 15 tests PASS (PM01–PM11 plus harness tests).

## Status

`D3C_IN_PROGRESS`: source correctness and policy memory tests are complete for
the implemented scope; T4 is not frozen because the full V/M/P/RH and missing
controller/verifier test files are incomplete. No official control/campaign has
been run. Exploratory data remains `EXPLORATORY_ONLY`.
