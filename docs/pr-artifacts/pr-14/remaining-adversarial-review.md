# PR 14 — Remaining adversarial review

| Invariant | Evidence | Verdict |
|---|---|---|
| I01 complete tuple/key continuation, no gaps/duplicates | P01 (all page sizes vs full order), P05 (relevance bit-exact) | PASS |
| I02 cursor bound to snapshot + query/sort fingerprint | P06 (binding), P07 (query/sort) | PASS |
| I03 total_hits independent of page | P03, P01 | PASS |
| I04 no token without a further candidate; K+1 | P02, P04 | PASS |
| I11 no partial response on cancellation | P11 | PASS |
| I12 public PIT cursor fail-closed | P12 | PASS |
| P09 malformed tuple length/class | `cursor_tuple_length_and_class_are_validated` | PASS |
| I05/I06 batch work monotonic + ceilings | NOT IMPLEMENTED | OPEN |
| I07 memory/response accounting | NOT IMPLEMENTED | OPEN |
| I08/I09 aggregation over every match, exactness | NOT IMPLEMENTED | OPEN |
| I10 typed per-slot isolation | existing batch tests only | PARTIAL |
| I13/I14 RustFS/CI | BLOCKED | OPEN |

## Residual risks
1. P2/P3 are not implemented, so batch work governance and compound aggregation remain
   unverified.
2. The cursor fingerprint encodes the contract `Query`/`Sort`/`CodecSchema`; a future analyzer
   semantic change without a schema-identity change would not alter the fingerprint, but the
   snapshot binding plus the identical-schema reader check bounds this risk.
3. P04 "empty page after the final hit" cannot be produced through the public API because a
   cursor is only emitted when a further candidate exists; the search-after filter handles it,
   and P09 covers malformed tokens.
