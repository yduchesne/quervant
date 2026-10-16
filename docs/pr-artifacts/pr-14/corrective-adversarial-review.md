# PR 14 — Corrective adversarial review

| Claim | Evidence | Verdict |
|---|---|---|
| Batch preserves explicit-null/empty-multi states | `pr14_batch::b11_lossless_field_states` | demonstrated |
| Cancellation maps to `Cancelled`, not invalid syntax | `search::batch::tests::error_mapping_preserves_contract_errors` | demonstrated |
| Resource exhaustion maps to `BudgetExceeded` | same unit test | demonstrated (mapping only; see limitation) |
| Corruption maps to a typed failure | same unit test | demonstrated |
| Existing PR 3–13 + PR14 behavior preserved | full workspace suites | demonstrated |
| Mixed queries not mis-scored | `pr14_projection::p08_mixed_predicates_fail_closed` | demonstrated (still fails closed) |
| OR/NOT never resurrects tombstones | `pr14_typed_predicates::t11_delete_and_pit`, `pr14_projection::p06_deleted_documents_excluded` | demonstrated for typed path |
| BM25 unchanged under extraction | not applicable — extraction not performed | **OPEN** |
| Mixed typed-only matches do not acquire phantom lexical scores | not applicable — mixed unsupported | **OPEN** |
| Full sort tuple survives pagination | only typed path (`pr10_cursor`) | **PARTIAL** |
| Legacy cursor cannot resume arbitrary sorted query | no unified cursor exists | **OPEN** |
| Projection of upserted key returns new record | key-based rescan; not proven obsolete-safe | **OPEN** |
| Zero-hit scan consumes work | not implementable without C3 seam | **OPEN** |
| Batch work/memory cannot reset | response-byte/hit meter only | **PARTIAL** |
| RustFS performs no GET during query | not executed | **OPEN** |
| RustFS acceptance actually executed | not executed | **BLOCKED** |

## Residual risk statement

The core corrective objective — a genuinely unified mixed executor with full-tuple pagination
and cumulative governance — is **not delivered**. Mixed queries fail closed (safe), but the PR
cannot be accepted as complete. The two delivered corrections (lossless batch states, typed
failure taxonomy) are independently tested and reduce two of the nine blockers.
