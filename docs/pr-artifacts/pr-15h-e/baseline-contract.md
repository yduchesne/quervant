# PR 15H-E — baseline and campaign contract

- A = `E_TOOLING_SHA` (v1 writer/reader), clean detached worktree.
- E = `E_CANDIDATE_SHA` (v2), clean detached descendant.
- Frozen PR15D 10K/100K corpus, adapter, schema, oracle and nine lanes.
- Size: Dictionary section bytes, immutable segment bytes and committed index
  bytes, from validated committed `FsDirectory` files.
- Low-vocabulary control: 2,048 docs, one `Keyword` field `term`, all
  `common`, keys `e-low-{i:08}`.
- Warm: 16 balanced slots, 9 lanes, 5 warmups + 20 samples.
- Cold/open and build+commit: 4 balanced blocks × 2 samples per arm.
- Gating statistic: conventional even-n median of four E/A block ratios.
- All E-P00–E-P12 gates frozen before measurements; a valid miss is a rejection
  with exact source rollback; invalid evidence is `E_MEASUREMENT_INVALID`.
