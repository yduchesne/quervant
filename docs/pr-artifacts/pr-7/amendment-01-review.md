# PR 7 Amendment 01 review

**Scope:** Boolean scoring correctness and search resource accounting.
**Branch:** `dev/lexical-postings`; starting commit `0568cce6f3505ba94158af990e4b834772d25e21`.
**Disposition:** amend the existing PR 7 branch; no separate roadmap PR.

## Corrections delivered

| Item | Defect | Fix | Files |
|---|---|---|---|
| A1 | Negated leaves contributed BM25 to results | Scoring filtered to even-`Not`-parity leaves; negative-only fields excluded from stats | `plan.rs`, `execute.rs`, `mod.rs` |
| A2 | `max_segment_candidate_entries` charged cumulatively across segments | Per-segment peak-entry ledger, reset between segments | `execute.rs` |
| A3 | Field-length entry occupancy inferred from a zero value | Explicit `HashMap::Entry` state; bounds checked before insertion | `score.rs` |
| A4 | Segment temporaries unaccounted; scanned-occurrence limit ignored; top-K replacement unchecked | `CandidateBudget` (segment+global bytes), cumulative scanned counter, replacement precheck | `execute.rs`, `topk.rs` |

## Invariant evidence

- **INV-01/02:** `s01`–`s04`, `s06`, and the 200-case seeded oracle `s07` show
  that odd-`Not` leaves score zero, even-`Not` leaves score only on positive
  match, and mixed-polarity leaves score once.
- **INV-03:** `s05`, `s07`.
- **INV-04:** `b01`–`b05` plus `budget_tests` reserve/release/reset tests prove
  per-segment peaks, not lifetime sums.
- **INV-05:** `b06`, `f01`, `f03`, and overflow/rejection unit tests.
- **INV-06:** `b07`, `global_plus_segment_byte_sum_is_enforced`,
  `global_byte_boundary_is_exact`, `h01`, `h02`.
- **INV-07:** `l01`, `l02`, and the `l03` occupied-zero unit tests.
- **INV-08:** all original PR 7 suites and the correctness-gated benchmark remain
  green; no encoding, snapshot, phrase-arithmetic or comparator change.

## Execution evidence

- `cargo test --workspace --all-targets`: 980 passed, 7 ignored, 0 failed on both
  Rust 1.98.1 and Rust 1.85.0.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: clean on
  both toolchains; `cargo fmt --all -- --check`: clean on both.
- `cargo llvm-cov --workspace --all-features --fail-under-lines 85`: 91.90% line
  coverage (up from the 91.73% baseline).
- `cargo run --release -p quervant-core --example pr07_bench`: correctness-gated
  against the naive oracle; pure-negative p50 dropped from 8.9 ms to 4.1 ms
  because negative-only fields are no longer scanned.

## Reviewer checklist status

- [x] Pinned branch/base reconciled; preflight recorded (`amendment-01-preflight.md`).
- [x] Odd/even/mixed NOT polarity and duplicate leaves covered by an independent
      oracle that never calls production scoring/traversal.
- [x] Positive-only fields/terms determine statistics scans; counts and
      membership unchanged.
- [x] Candidate entries reset per segment and account for concurrent temporaries.
- [x] Global bytes plus current segment bytes checked before growth; overflow and
      cleanup tested.
- [x] Scanned-occurrence limit independent; cancellation/no-partial-result
      contracts preserved.
- [x] Field-length occupancy and top-K replacement fixed.
- [x] All original suites, local real-path integration, MSRV, coverage, lint,
      docs and benchmark gates executed and recorded.
- [x] No segment/manifest encoding or distributed dependency changes.
- [x] Residual risks and failure classifications documented; roadmap remains
      PLANNED pending independent review/merge.
- [ ] Commit/push and independent review before merge (pending).

## Known residual risks

Logical accounting estimates are not exact RSS; `match_phrase` scratch vectors
are not separately charged; O(indexed postings) field-length work remains; no
RustFS/WAND/streaming scope. No new on-disk format.
