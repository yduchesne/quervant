# PR 11 — Pre-implementation correctness gate

**Status:** PRE-CODE GATE (recorded before production changes)
**Plan:** `QUERVANT_PR11_DETAILED_IMPLEMENTATION_PLAN.md`
**Baseline HEAD:** `81b8a31713f79a0855210f89d8857c2e5cbb3802`
(`Merge pull request #30 …docs/pr10-roadmap-closure`; `main` and `dev/json-indexing` are identical.)
**Toolchain:** stable `rustc 1.98.1 (48a229cea 2026-09-01)`, MSRV `1.85.0` installed.
**Baseline result:** `cargo check -p quervant-core --all-targets` → PASS.
`git status --short` → clean.

## (a) Invariant → step → test traceability

| Invariant | Contract | Steps | Tests |
|---|---|---|---|
| J11-I01 | Stored JSON round-trips exactly | 4,8 | J11-T01, T02 |
| J11-I02 | One exact concrete path per node, no duplicates/omissions | 3,4 | T03, T04, T05 |
| J11-I03 | Missing/null/empty/JSON-null/containers distinct | 2,5 | T06, T07 |
| J11-I04 | Type-exact non-normalizing equality | 2,5 | T08, T09 |
| J11-I05 | Unsupported path / wildcard equality fail pre-I/O | 2,5 | T10 |
| J11-I06 | Document-level Boolean, no array correlation | 5 | T11 |
| J11-I07 | Feature/section/version fail closed; legacy opens | 4,6 | T12, T13, T14 |
| J11-I08 | Bounded counts/decode/work/cancel, no partial answers | 3,4,5 | T15, T16, T17 |
| J11-I09 | Physical ids/live masks/PIT/refresh/compact/reopen | 4–7 | T18, T19, T20 |
| J11-I10 | `stored=false` hides source; `indexed=false` not queryable | 2,5,7 | T21 |
| J11-I11 | Deterministic encoding/query across input order | 3,4 | T22 |
| J11-I12 | Existing lexical/numeric/temporal/analytics unaffected | 5–8 | T23, T24 |

## (b) Concrete counterexamples the implementation must reject or handle

1. `$.events[*].ip = "a"` — wildcard equality must be rejected at query validation (`UnsupportedOperator`), not executed.
2. `$.events[0].t = 2 AND $.events[1].t = 2` must **not** be inferred from `$.events[*].t = 2`; no ancestor binding exists.
3. `I64(1)` vs `U64(1)` vs `F64(1.0)` must never compare equal even though they print the same.
4. `-0.0` and `0.0` F64 must compare equal (sign of zero is not identity).
5. `"é"` (NFC) vs `"e\u0301"` (NFD) strings must be distinct; equality is byte-exact.
6. `$.a` and `$["a"]` must resolve to the same concrete member identity.
7. Duplicate object member `{"a":1,"a":2}` in an **indexed** JSON field must be a typed document error; stored-only keeps duplicates.
8. `FieldValues::Absent` (`$` absent), `FieldValues::ExplicitNull` (`$` exists as null), `FieldValues::Empty` (no root), and `FieldValue::Json(Null)` (root null node) are four distinct behaviours.
9. Multi-root JSON `[{"x":1},{"x":2}]` must index `$[0].x` and `$[1].x`, never collapse them.
10. A JSON null, empty array or empty object node **exists**; a missing member does not.
11. A new segment that declares `FEATURE_JSON_PATHS` but omits the section (or vice versa) must fail on open, never fall back.
12. A legacy segment (no JSON feature/section) queried on an indexed JSON field must use the bounded stored-source fallback, and must fail typed when the field is `stored=false`.
13. `[*]` over a scalar produces no match; `[*]` over an array of nulls produces a match.
14. `Not(JsonPathExists)` must still include live documents that have no matching path and must exclude tombstoned physical docs.

## (c) Code path map (reused seams)

| Concern | Location |
|---|---|
| JSON value/AST/path parser | `contract/value.rs`, `contract/query.rs` (`JsonPathExpr`, `ConcreteJsonPath`) |
| Document validation | `contract/schema.rs::validate_document`, `contract/document.rs` |
| Stored JSON codec | `segment/value.rs`, `segment/stored.rs` |
| Segment format/features | `segment/format.rs` |
| Segment composition | `segment/build.rs` |
| Compaction | `index/merge.rs::build_merged_segment` |
| Reader lifecycle | `segment/reader.rs`, `index/snapshot.rs` |
| Search validation/execution | `search/typed.rs` (`validate_query`, `evaluate_query`, `scan`) |
| Bounds/budgets | `search/limits.rs`, `segment/limits.rs`, `segment/decode_budget.rs` |

## (d) Baseline SHA / results

- HEAD `81b8a31713f79a0855210f89d8857c2e5cbb3802`.
- Workspace builds; `quervant-core` checks clean with all targets.
- PR 7 lexical, PR 9 mutation/merge, PR 10 typed/cursor/analytics suites present and green on baseline.
- PR 5 legacy golden fixture present under `crates/quervant-core/tests/fixtures/segment`.

## (e) Open contract contradictions

None found: A11/A12 define `JsonPathExpr`/`ConcreteJsonPath` and `JsonPathEquals`/`JsonPathExists`,
`Query::validate` already rejects wildcard equality and JSON-typed RHS, and `FieldType::Json` is
stored-capable but non-columnar. The multi-root virtual outer index and duplicate-member rejection are
narrow additions consistent with those contracts. No STOP condition is triggered.
