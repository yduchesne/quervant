# PR 15G-C fixup execution record

**Status:** `FIXUP_PERFORMANCE_REJECTED_SAFE_ROLLBACK`
**Base/fixup candidate:** `0a55119b1d47ab4bbd7d9205ad1d84a636d96c2f`
**Historical failed C:** `5ec886f3cbd8666d46b7d3c4a9761abd53e30d4e`
**Final source state:** C production search restored to B source `97d7ce1`.

## Implemented two-pass design (historical candidate)

- Replaced four full postings decodes with two for nonempty eligible terms; an
  absent term performs one lookup and no second decode.
- Pass 1 validates all postings, charges scanned/live work, admits 16/48/64
  virtual resources and releases the ledger before pass 2.
- Pass 2 scores every live posting exactly once with `Posting.freq: u64`, then
  feeds the validated `f64` into the shared candidate admission.
- Removed the `u32` frequency cast and winner rescore.
- Deferred the first candidate-admission error until all later scores in the
  segment were checked; later `InvalidScore` outranks it.
- Added mandatory tests: postings opens, absent term, invalid nonwinner,
  deferred-error priority, u64 frequency, exact/one-under candidate entry/bytes,
  and pass-count mismatch.
- No format/writer/public API/benchmark input change.

## Verification before rollback

- Focused search and C integration: PASS.
- Full stable/MSRV QA: PASS.
- Coverage: 92.73%; `execute.rs`/`unified.rs` line coverage 93.85%/96.83%.
- C/A/B RustFS + proxy + K0 + 10× K05: PASS locally.
- Authorized fixup A/B campaign: **FAIL** (GF-P01 and GF-P04). See
  `performance-qualification.md`.

## Rollback

After the qualified performance failure, `execute.rs` and `unified.rs` were
restored additively from `97d7ce1`. B carryover tests and C correctness tests
remain. Post-rollback QA is in `rollback.md`.
