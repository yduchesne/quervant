# PR 15G-D execution record

**Status:** `D1_D2_PERFORMANCE_QUALIFIED_REVIEW_PENDING`
**D_BASE:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**D1 candidate:** `1d2a6b0f08bf68994699e1f3e37f163347492cd1`
**D2 candidate / active source:** `dae598758a433ecdc0d9af37e15194e948bbc788`

## D1

- Compiled exact-term eligibility computed once from the plan.
- Per-segment dictionary lookup before `ColumnAccess::open`; proven miss calls
  `charge_absent_exact_term_segment`, which uses the existing ledger, cancellation
  polls and `effective_live_examination_count`/`charge_lexical`.
- Present entries, including all-dead postings, keep original decode validation.
- No geo/JSON sort miss bypass.

## D2

- Existing P4 `evaluate_lexical_with` postings path remains.
- `is_match` returns `true` only when the P4 gate holds; the executor runtime
  guard and one-term postings decode remain.
- Matched set, score map, BM25, total_hits, heap, cursor and projection unchanged.
- Test-only term-membership counter proves zero redundant binary searches on the
  direct path and positive searches on the legacy `And([Term])` control.

## Tests and QA

- D1 unit tests: miss/present/compound, exact/one-below absent work.
- D2 unit test: 1,000 matches, K10, membership search counter and score/key/field
  bits parity with legacy.
- Integration `pr15g_d_specialization`: 5 tests — memory, cross-segment,
  FsDirectory, PIT, concurrency.
- Real pinned RustFS `pr15g_d_rustfs`: 1 PASS.
- Stable/MSRV all-feature workspace tests: 2313 passed / 79 ignored each.
- Coverage: 92.73%; `execute.rs`/`unified.rs` 94.31%/96.85%.
- B carryover tests and C integration/regression tests remain green.
