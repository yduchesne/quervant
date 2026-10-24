# PR 14 — Final acceptance gate

> **Supersession note (2026-10-24, PR 14C):** the historical `NOT READY` text
> below is preserved unchanged. PR 14C reconciled every obligation and executed
> the local, real-RustFS and fault gates; PR 14 remains **BLOCKED / NOT
> ACCEPTED** because the human `R-14A-JSON-MEM` disposition is
> `REQUIRE SEPARATE CORRECTION` and qualified benchmarks / final-SHA CI are not
> available. See [../pr-14c/acceptance-reconciliation.md](../pr-14c/acceptance-reconciliation.md)
> and [../pr-14c/final-acceptance.md](../pr-14c/final-acceptance.md).

**Status: NOT READY.** Partial implementation delivered; the PR must not be marked DONE.

## Gate summary

| Gate | Status |
|---|---|
| §3 preimplementation correctness gate recorded | DONE (with S1/S2 unresolved) |
| 14A unified compiler + mixed execution | PARTIAL (pure delegation only; mixed STOP S1) |
| 14B typed/IP/CIDR completeness | DONE |
| 14C JSON range/membership/sort | DONE (legacy-segment dedicated tests PARTIAL) |
| 14D projections | DONE |
| 14E aggregation + serial batch | DONE (typed/neutral; mixed/aggregation-in-batch fail closed) |
| 14F real-boundary RustFS + faults + benchmarks | NOT EXECUTED / BLOCKED |
| 14G final gates, CI, docs | PARTIAL (local gates PASS; no final-SHA CI) |
| I01–I16 evidence | PARTIAL (I01/I13/I15 incomplete) |
| U/J/T/P/A/B/G/R/X matrix | PARTIAL (see traceability) |
| Coverage ≥ 85% (lines) | PASS — 91.25% |
| Stable + MSRV fmt/clippy/tests | PASS |
| Persisted formats unchanged | PASS |
| Real RustFS acceptance | BLOCKED |

## STOP conditions requiring a maintainer decision

1. **S1 — mixed lexical+typed execution.** A minimal extraction from `search/execute.rs`
   (`build_leaf_data`/`eval_node` with `SearchWork`/`SegmentCandidateLedger`/`Expansion`/
   `SnapshotStats`) plus a regression oracle is needed. The agent did not rewrite BM25 or copy
   the executor. Until approved, mixed queries fail closed.
2. **S2 — public sorted search-after cursor.** `contract::result::Cursor` lacks the full sort
   tuple. A compatibility amendment is required before exposing unified pagination.

## Resolved STOP conditions

- **S3** resolved by the existing `SortValue` + canonical comparator total order (tested).
- **S4** resolved without a format change via the indexed JSON-path section (tested, J06).
- **S5** resolved by following approved PR 2 A09/A10; the plan's “Exists = present non-null”
  prose discrepancy is documented in the preimplementation gate.

## READY criteria not yet met

- All I01–I16 have evidence (I01 mixed equivalence, I13 zero-GET instrumentation, I15 legacy
  JSON operators are incomplete).
- All U/J/T/P/A/B/G/R/X mandatory tests executed and passed (U, G, R, X incomplete).
- Real RustFS + final-SHA CI passed.

No “DONE” claim is made. A follow-up must implement/approve S1 and S2, add the 14F verticals
and benchmarks, and run the real-provider acceptance before this PR can be accepted.
