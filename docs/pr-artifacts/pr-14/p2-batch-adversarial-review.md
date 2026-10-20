# PR 14 — P2 batch governance adversarial review

| Invariant | Evidence | Disposition |
|---|---|---|
| I01 cumulative actual work (not hits) | `b01`, `b06`, batch meter unit tests | PASS |
| I02 local+batch preflight atomic | `work_exact_limit_then_one_over_is_atomic`; all charges preflight then commit | PASS |
| I03 no query-class bypass | per-document examination charge in `evaluate_lexical_with`; `b01`, `b06`, `b21` | PASS |
| I04 peak memory | response outcomes reserved; candidate/heap memory still query-local | **PARTIAL** |
| I05 cleanup on error/cancel | query-local ledgers release on drop; batch response memory retained until meter drop | **PARTIAL** |
| I06 response cumulative/once | `b14`, `b16`, `response_bytes_are_cumulative_and_checked` | PASS |
| I07 failed response not committed | reserve→charge ordering, release on charge failure | PASS |
| I08 exact budget origin | `b17`, `error_mapping_preserves_contract_errors` | PASS |
| I09 envelope policy before I/O | `b19`, `b10` | PASS |
| I10 F1/P1 unchanged | full suites, bit-exact score tests | PASS |
| I11 checked arithmetic | `overflow_is_typed_not_wrapped` | PASS |
| I12 no remote GET / persistence change | no storage code changed; B24 blocked | PARTIAL/BLOCKED |

## Residual risks
1. Batch `BatchMemoryBytes` currently bounds retained response bytes, not the peak of
   simultaneously live query scratch (candidate heap, sort tuples, projection temporaries).
   Query-local `CandidateBudget`/`ProjectionLedger` still bound those, so the batch peak is
   under-counted.
2. Query-local `ResourceLimit` now maps to `ExecutionFailure { query_resource_limit }`; this is
   intentional per D06 but loses the specific local budget kind (no verified contract kind).
3. `BatchAggregate` now meters work; any existing caller assuming it was a hit cap will see
   different behavior. The only in-repo callers are tests, updated.
