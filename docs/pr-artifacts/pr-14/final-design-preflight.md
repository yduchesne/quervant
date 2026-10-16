# PR 14 — Final design preflight

- Branch `dev/pagination`; base `main` @ `7ca1b2ec59fec648602e0e4a52e8f903a596f106`.
- Preflight HEAD: `e0e1dcb` (superseded by the final-design edits below).
- Confirmed present from earlier passes: lossless `FieldValues` batch hits and `QueryError::ExecutionFailure`.
- Toolchains: stable `1.98.1`, MSRV `1.85.0`, `cargo-llvm-cov 0.9.1`.

## Seams implemented (D1)

- `search/plan.rs::compile_lexical_leaf` — compiles exactly one lexical leaf with a
  caller-supplied `CodecSchema` + `SchemaAnalyzerBindings`, reusing the existing PR 7
  `Compiler` (no second analyzer/automaton pipeline).
- `search/execute.rs::evaluate_lexical_with` — crate-private per-segment lexical seam. It
  builds existing `LeafData` via `build_leaf_data`, evaluates a caller predicate per
  effective-live doc, and scores the matched set with the existing `score_segment` BM25
  implementation. `CandidateBudget`, `SearchWork`, `LeafData` (with `matches`) are crate-private.
- `search/typed.rs` — `TypedPlan`, `CompiledQuery`, `Compiled`, `compile_query`,
  `evaluate_query`, `JsonAccess`, `GeoMembership`, `GeoScratchBudget`,
  `build_geo_membership` are now `pub(crate)` for reuse; no typed semantics changed.
- `search/unified_plan.rs` — compiles `Query` into a `UnifiedNode` tree of
  `MatchAll`/`Lexical`/`Typed`/`And`/`Or`/`Not`, interns equivalent leaves, and computes the
  positive-lexical parity set and scoring field ids.

## PIT resolver finding (D2)

No authoritative `PitId` → `ReaderSnapshot` resolver exists at the batch boundary; a PIT string
cannot prove snapshot binding. Per D2 the snapshot-bound runtime cursor path is the required
fallback. Unified pagination is **not** implemented in this pass; batch cursor slots remain
fail-closed. No public `contract::result::Cursor` shape was changed.

## Budget observability (D3/D5)

`SearchError::ResourceLimit` still carries only `limit`/`requested`; existing `SearchWork` and
`ScanGuard` bound work locally. A shared `ExecutionMeter` was **not** threaded through the hot
paths in this pass. The batch ledger continues to meter response bytes and hit counts only; this
is not claimed to be work-accurate.
