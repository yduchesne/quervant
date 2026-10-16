# PR 14 — Final design adversarial review

| Claim | Evidence | Verdict |
|---|---|---|
| OR/NOT never resurrects tombstones | `pr14_unified_mixed::m07_not_cannot_resurrect_tombstones` | demonstrated |
| BM25 unchanged under extraction | `m13_pure_lexical_parity` (bit-exact key/score parity with `LexicalSearcher`) | demonstrated |
| Mixed typed-only matches get no phantom lexical score | `m02_term_or_ip` asserts `d3` score `Some(0.0)` | demonstrated |
| Duplicate positive leaves do not double score | `m08_duplicate_leaves_do_not_double_score` | demonstrated |
| Nested AND/OR/NOT membership is exact | `m01`, `m03`, `m05`, `m06` | demonstrated |
| Phrase/regex/multi-term reuse the PR 7/8 pipeline | `m10`, `m11` | demonstrated |
| Deleted docs excluded | `m07`, `pr14_projection::p06` | demonstrated |
| Lossless batch field states | `pr14_batch::b11_lossless_field_states` | demonstrated |
| Capability rejection is per-slot, before scan | `pr14_batch::b13_capability_rejection_is_isolated` | demonstrated |
| Every sort tuple/key tie survives pagination | only partial (`m14` single page); no unified cursor | **PARTIAL** |
| Legacy cursor cannot resume arbitrary sorted query | no unified cursor exists | **OPEN** |
| Projection of upserted key returns new record | mixed path uses exact `(segment,doc_id)`; not yet covered by a dedicated stale-record test | **PARTIAL** |
| Zero-hit scan consumes work | not implemented (no ExecutionMeter) | **OPEN** |
| Batch work/memory cannot reset | response/hit meter only | **PARTIAL** |
| Mixed aggregation matches oracle | not implemented | **OPEN** |
| RustFS performs no GET during query | not executed | **OPEN** |
| Real RustFS acceptance executed | not executed | **BLOCKED** |

## Residual risk

F1 (mixed execution) is complete and independently tested with bit-exact BM25 parity. F2/F3/F4/F5
remain incomplete: unified pagination, shared work governance, compound aggregation and
real-provider acceptance are not delivered. No degraded substitute was introduced for these.
