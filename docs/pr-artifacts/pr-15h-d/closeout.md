# PR 15H-D — closeout

**D status:** `PERFORMANCE_REJECTED_SAFE_ROLLBACK` (verified). Production
`search/unified.rs` and `search/unified_plan.rs` are byte-identical to
`D_TOOLING_SHA c802f96` (which equals the accepted C rollback).

## Why the experiment is closed without retry

The duplicate binding/codec resolution was real but saved only ~0.30 ms (100K
common K100), ~0.30 ms (K10) and ~0.87 ms (medium) conventional medians — far
below the predeclared +2 ms keep gate and within ordinary single-host noise.
A retry, threshold change or second candidate is not authorized; statistics
caching/other planner work requires a separate approved plan.

## Evidence and environment

Sealed baseline `72c8d17d…`, paired `902d8432…`; host
`4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f`;
corpus `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`;
49 controller tests PASS; stable/MSRV/RustFS local suites previously PASS.

## Status fields

- D source: exact rollback, verified.
- D hosted CI at the exact closeout checkpoint: **pending** — see the E
  predecessor lock/blocker record.
- Independent human review: requested/pending; no self-approval.
- Residual risks: one WSL2 host, six frozen lanes; rounded display tables are not
  gating; no cross-engine claim.
