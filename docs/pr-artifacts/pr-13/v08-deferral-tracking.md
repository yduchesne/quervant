# PR 13 — V08 query-scoped pruning deferral

**Status: DEFERRED — PENDING MAINTAINER APPROVAL. Not PASS, not implemented.**

Query-scoped pre-materialization pruning (V08) is not implemented. It was
already deferred in the PR 13 plan because it requires a planner/manifest
metadata contract change. This is a **separate tracked follow-up**, not part of
PR 13.

## Proposed follow-up scope

- Define a query-aware safe-pruning contract over manifest-level temporal and
  spatial bounds without changing the persisted segment/manifest/`CURRENT`
  formats.
- Prove safety for Boolean composition: `AND`/`OR`/`NOT`, unknown or absent
  bounds, legacy segments and unknown semantics must default to **download**,
  never skip.
- Guarantee no false negatives: a skipped segment must be provably unable to
  contain a matching live document.
- Provide an independent correctness oracle comparing pruned versus unpruned
  results, and measure actual remote GET bytes.
- Benchmark the pruning decision against the unpruned path on representative
  selective and non-selective queries.

## Disposition

- PR 13 does **not** implement V08 and does **not** mark it PASS.
- PR 13 must not be marked DONE until a maintainer explicitly approves this
  deferral and links a tracking issue/PR for the follow-up.
- Until then, this remains **DEFERRED — PENDING APPROVAL**.
