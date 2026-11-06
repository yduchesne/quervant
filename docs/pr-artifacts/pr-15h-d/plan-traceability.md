# PR 15H-D — plan traceability (pre-implementation)

**C correction predecessor:** `d4b10c18a0a906f9f22f169c6437e3f82e796401`
**A production source:** equals `e8744d3` (C rollback); A identity is `D_TOOLING_SHA`.

## Source call graph (verified before edits)

- `search/unified.rs::search_impl` validates query/sort/top-K/projection, then
  calls `execute_unified`.
- `execute_unified` resolves `SchemaAnalyzerBindings` + `CodecSchema`, computes
  the cursor fingerprint, validates `request.after`, then calls
  `unified_plan::compile`.
- `unified_plan::compile` resolves the same bindings + codec again, builds the
  typed plan/`Compiler`, and returns `UnifiedPlan`.
- `UnifiedSearcher::select_keys` calls `unified_plan::compile` directly and must
  keep the original API.
- `score::compute_stats` is unchanged and is measured separately, not optimized.

The D change will add `unified_plan::compile_with_resolved(...)` and make the
existing `compile` delegate to it; `execute_unified` passes its already-resolved
owned values. No `resolve`/`from_contract` call is added to the normal path.

## D-K → tests

| Invariant | Tests |
|---|---|
| D-K01 validation ordering | D-U01, D-I01 |
| D-K02 cursor/fingerprint precedence | D-U02, D-I02 |
| D-K03 identical plan | D-U03/U04 |
| D-K04 single resolution | D-U05 + call-graph review |
| D-K05 sibling callers unchanged | D-U06, D-I03 |
| D-K06 score/order/projection/totals | D-U07–U10, D-I04 |
| D-K07 error/resource semantics | D-U11–U16, D-I05 |
| D-K08 snapshot/PIT/mutation | D-I06/I07 |
| D-K09 no resource/format expansion | source diff, D-I08 |
| D-K10 rollback exactness | D-T19/T20 |
| D-K11 batch/aggregation | D-I09/I10 |
| D-K12 measurement integrity | D-T01–T20 |

## Pre-implementation no-go checks

1. Cursor/fingerprint validation must remain before compilation; the resolved
   values are computed before cursor validation exactly as at A.
2. `SchemaAnalyzerBindings::resolve`/`CodecSchema::from_contract` are pure
   constructors with no observable side effects; reuse is ownership-only.
3. Both resolved values are owned/immutable and can be moved into the compiler;
   one codec clone is used only because the fingerprint needs the value.
4. Any borrow/ownership conflict that would move validation or segment access is
   a HARD STOP, not a refactor.
5. `select_keys` and lexical callers stay on the original API.
6. No statistics cache, planner, shared state, format or public API change.

## Controller test IDs

D-T01–D-T20 are implemented in `benchmarks/pr15h_d/test_run.py`:
lanes/order, mirrored schedule, samples/warmups, tooling identity (including
pre-output blocking), corpus/index/host/oracle/probe, D primary/guard boundaries,
source-scope allowlist, seal/report tamper and read-only verify.
