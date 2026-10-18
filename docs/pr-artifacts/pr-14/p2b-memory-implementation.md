# PR 14 — P2B batch peak-memory implementation

**Status: NOT IMPLEMENTED.** No production code was changed in this pass.

The safe implementation design is recorded in `p2b-memory-preflight.md`:
split `BatchExecutionMeter` into disjoint `work`/`memory`/`response` sub-meters so a slot can
lend `&mut work` to `MixedWorkMeter` and `&mut memory` to a slot-scoped reservation bound to
`CandidateBudget`/`ProjectionLedger` without aliasing. Then thread an optional slot memory
context through candidate scratch, typed/geo/JSON scratch, projection, and the response
retention transfer.

This requires lifetime changes to `CandidateBudget`/`SegmentCandidateLedger`, a checked
`ProjectionLedger::release`, `SlotMemoryScope`/`finish_success`, and call-site rewrites in
`execute.rs`, `unified.rs`, `typed.rs`, `projection.rs`, `batch.rs`, `batch_meter.rs`. It was not
started because it cannot be completed and validated within this pass; shipping it partially
would violate the plan's no-degraded-accounting rule.

Existing P2 work/response/error behavior is unchanged and remains tested.
