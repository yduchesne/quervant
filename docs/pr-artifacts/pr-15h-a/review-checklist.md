# PR 15H-A — reviewer acceptance checklist

- [x] Fresh `main` SHA recorded; `main` unchanged at
      `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`.
- [x] Branch `dev/pr15h-a-linear-term-candidates` created from that exact SHA.
- [x] Benchmark-only `HA-HARNESS` commit made before any production Rust edit.
- [x] Pre-optimization baseline (3 trials, 7 lanes) executed, sealed and
      `--verify-only` reproduced before production implementation.
- [x] Changed-file audit: benchmark tool + integration test + PR artifacts, then
      an exact revert of `execute.rs` / `unified.rs`.
- [x] All 20 HA-I invariants mapped to named executed tests
      (`design-verification.md`, `adversarial-test-traceability.md`).
- [x] No `collect_mixed`, heap, sort, cursor, projection or `score.rs` change in
      the candidate; no format/storage change at any point.
- [x] Decoded posting order, `is_match` callbacks, cancellation and work charges
      preserved in the candidate.
- [x] Both 48-byte matched and 64-byte scored virtual charges preserved in
      sequence; double-fault precedence tested.
- [x] Bitwise score parity and zero-score cases tested against `And([Term])`.
- [x] `And([Term])` fallback verified genuinely ineligible.
- [x] Unit matrix and local integration matrix executed with evidence.
- [x] Exactly seven frozen warm lanes; no three-engine timing; no extra lanes.
- [x] Four mirrored paired blocks, 8 slots, 56 lane records, 1,120 samples,
      280 warmups, 16 clear probes, 56 oracle validations.
- [x] Frozen nearest-rank summaries and drift caps applied without tuning.
- [x] Qualified verdict is `PERFORMANCE_REJECTED` (HA-P04 guard regression).
- [x] Additive revert restores byte-identical production search to baseline.
- [x] Benchmark controller, its 21 tests and sealed raw evidence preserved.
- [x] Stable and MSRV fmt/clippy/tests, ≥85 % coverage, docs and real RustFS
      executed locally; hosted CI remains PENDING.
- [ ] Hosted `rust` / `msrv` / `rustfs` jobs on the final pushed HEAD.
- [ ] Independent human review.

**Status:** `PERFORMANCE_REJECTED_SAFE_ROLLBACK`, review pending. Not merged.
