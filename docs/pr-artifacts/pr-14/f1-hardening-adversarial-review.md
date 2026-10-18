# PR 14 — F1 hardening adversarial review

| Claim | Evidence | Verdict |
|---|---|---|
| Mixed BM25 is bit-identical to PR 7 (not just delegated parity) | S01/S02/S03/S05 use `f64::to_bits()` against `LexicalSearcher` on the same snapshot | PASS |
| Negative-only leaves contribute no score | `pr14_unified_mixed::m04` now asserts `score.is_none()` | PASS |
| Typed-only matches do not acquire phantom lexical score | `pr14_unified_mixed::m02` (typed-only branch score 0.0 with positive lexical present) | PASS |
| Deletes cannot resurrect under NOT | `m07` | PASS |
| Duplicate positive leaves do not double score | `m08`, S03 | PASS |
| Sort validation precedes I/O and returns typed contract errors | V01–V05 | PASS |
| Mixed geo sort matches typed missing/descending semantics | G01–G03 | PASS |
| Projection uses the current physical version after upsert | P02 | PASS |
| Exact `total_hits` with K=1 | M02 | PASS |
| One cumulative lexical+typed work counter | NOT IMPLEMENTED (STOP H1) | **FAIL/OPEN** |
| Candidate memory is one query-wide budget | `CandidateBudget` global+segment combined; bounded heap | PASS (residual: duplicates not retained) |
| No public/codec/storage changes | diff limited to `search/*` + tests + docs | PASS |
| Pure typed/lexical results unchanged | PR 7/PR 10 & PR14 suites green; pure typed now `score: None` | PASS |

## Residual risks
1. **H1 not done.** A mixed request can consume up to the lexical and typed work ceilings
   independently; I01/I02 remain unmet. This is the primary open correctness gap.
2. Mixed candidate duplicate detection is bounded to retained candidates; non-retained duplicate
   live keys rely on the snapshot's effective-live uniqueness invariant.
3. `M01/M03/M04/M05/M06` and `G04/G05` are only partially covered (see traceability).
4. `total_hits`/top-K now run through the unified path for pure lexical/typed; parity is proven
   for the tested fixtures, but the full existing suites are the primary regression guard.
