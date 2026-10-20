# PR 14 — P2B batch peak-memory preflight

- Branch: `dev/pagination`
- `main`: `7ca1b2ec59fec648602e0e4a52e8f903a596f106`
- Branch HEAD: `dd27c9a0f862b00ae7bd4942f1a07ecc311bfeaf` (P2 work/response slice committed); no P2B production edits.
- Toolchains: stable `1.98.1`, MSRV `1.85.0`.
- Baseline targeted suites (executed): `pr14_batch` 12, `pr14_batch_governance` 6,
  `pr14_f1_hardening` 23, `pr14_unified_cursor` 11 — all pass.

## Call graph

`execute_batch` owns `BatchExecutionMeter`
→ `execute_slot(searcher, query, cancel, &mut meter)`
→ `UnifiedSearcher::search_with_batch(..., &mut meter)`
→ `search_impl` validates and builds `ProjectionPlan`
→ `execute_unified` → `collect_mixed`:
  - `CandidateBudget::new(&limits)` (local only)
  - `MixedWorkMeter::with_batch(..., &mut meter)` (holds the batch meter)
  - `evaluate_lexical_with` (segment scratch via `SegmentCandidateLedger`)
  - `project_selected_hits` → `ProjectionLedger` (local only)
→ returns `UnifiedResponse`; `execute_slot` converts to `SearchResponse`; `execute_batch` then
  `meter.reserve_memory(response_bytes)` + `meter.charge_response`.

## Live memory owners

| Owner | Reservation | Release | Batch-bound? |
|---|---|---|---|
| `SegmentCandidateLedger`/`CandidateBudget` segment scratch | `reserve`/`release_segment` | segment end/Drop | no |
| `CandidateBudget` global K+1 heap | `reserve_global_bytes` | eviction/end | no |
| `GeoScratchBudget` (geo membership/sort) | `reserve_exact` | segment end | no |
| typed decoded-value bound | `decoded_value_bound` admission | per value | no |
| `ProjectionLedger` | `reserve` | saturating `release` | no |
| retained successful `SearchResponse` | `reserve_memory(response_bytes)` | never until meter drop | yes |

## Borrow-graph finding (why the prescribed binding is not a small change)

In batch mode `MixedWorkMeter` holds `&mut BatchExecutionMeter` for the whole slot
(`with_batch`). `CandidateBudget` and `ProjectionLedger` would each need simultaneous mutable
access to the **same** meter's memory counters during `collect_mixed`/`project_selected_hits`.
That is two live `&mut` to one object and does not compile without `RefCell`/unsafe/globals,
which the plan forbids (S2). The safe design is to give `BatchExecutionMeter` **disjoint
sub-meters**:

```text
BatchExecutionMeter { work: BatchWorkMeter, memory: BatchMemoryMeter, response: BatchResponseMeter }
```

Then `execute_batch` can destructure the fields once and lend:
- `&mut work` to `MixedWorkMeter` (unchanged capacity semantics),
- `&mut memory` to a `SlotMemoryScope` bound to `CandidateBudget` and `ProjectionLedger`,
- `&mut response` for cumulative response admission.
Distinct field borrows are legal; no interior mutability, no duplicate counters.

## Ripple (not executed in this pass)

- `CandidateBudget` → `CandidateBudget<'m>` with `Option<&'m mut BatchMemoryMeter>`, and
  `SegmentCandidateLedger<'a>` gains the memory lifetime; every `execute_search`/mixed call site.
- `ProjectionLedger` gains an optional memory binding and a checked `release` (`SearchResult`).
- `MixedWorkMeter`/`with_batch` switch from `BatchExecutionMeter` to `BatchWorkMeter`.
- `batch.rs` destructures the meter; `execute_slot`/`search_with_batch` accept work+memory refs;
  `SlotMemoryScope` RAII + explicit `finish_success(retained_bytes)`.
- Typed/geo/JSON scratch binding and `response_bytes` transfer.

This touches `execute.rs`, `unified.rs`, `typed.rs`, `projection.rs`, `batch.rs`,
`batch_meter.rs` and their tests. It is a coherent but large mechanical change and was **not**
attempted here to avoid an unvalidated partial accounting implementation.

## Three adversarial counterexamples (to cover when implemented)
1. Slot 2's candidate heap peak must be checked against `retained(slot1) + slot2 scratch`; a
   post-slot-only reservation undercounts this.
2. A heap replacement must release the evicted reservation before admitting the incoming one, or
   the peak is over-counted; both must be atomic on rejection.
3. A failed projection/decoding must release slot scratch and not advance response bytes; a later
   slot must still observe the retained prior outcomes.

## Disposition

No production edits were made. This is an execution-scope stop (large refactor, not a semantic
contradiction): the safe disjoint-field design is specified above but cannot be completed and
verified within this pass. P2B is **NOT IMPLEMENTED**; PR 14 remains NOT READY.
