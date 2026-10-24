# PR 14A — invariant/test traceability

| Invariant | Evidence |
|---|---|
| I01 same live pinned snapshot issues/resumes a cursor | T01, T06, T09 |
| I02 pages form an exact duplicate-free union | T02–T05 |
| I03 full tuple plus key tie-break | T02, T03, T12 |
| I04 relevance score bits and tie behavior | T04, T12 (`b01`, `b02`) |
| I05 query/sort/schema fingerprint and tuple mismatch fail typed | T07, T12 |
| I06 wrong/legacy/expired PIT cursor never falls back | T01, T06, T10 |
| I07 mutation/refresh/commit/compaction preserve retained PIT | T09 |
| I08 legacy cursor/naked PIT fail closed; plain batches unchanged | T01, `pr14_batch::b09` |
| I09 exactly N outcomes in order; cursor failure is slot-local | T08, T13 |
| I10 cursor payload charged exactly once; exact/one-over boundaries | T11 |
| I11 no format/remote/distributed changes; QA gates pass | diff scope + evidence QA table |
| I12 expiry never increases along a continuation chain | T10 |

Known observation limitation: public `Cursor` exposes PIT/sort/last-key/expiry
but not the private continuation tuple. Tests therefore compare resumed page
membership/order and reject internal mismatches through the public API; T12
unit tests exercise tuple/scalar round-trips directly inside `quervant-core`.

## Correction 01 traceability

| Invariant | Source function | Test | Observed |
|---|---|---|---|
| I01 root charges 24 | `json_path_logical_bytes` | T01 | PASS |
| I02 member bytes add exactly N | `json_path_logical_bytes` / `cursor_logical_bytes` | T02, T06 | PASS |
| I03 every segment costs 24 | `checked_path_components` | T04 | PASS |
| I04 UTF-8 bytes not scalar count | `member.len()` | T03 | PASS |
| I05 overflow returns `None` | `checked_path_components` | T05 | PASS |
| I06 long path increases public cursor charge | `cursor_logical_bytes` | T06, T07 | PASS for accounting |
| I07 exact passes / one-under fails; siblings preserved | shared batch meters | T07, T08 | PASS |
| I08 non-JSON/PIT/expiry/query regressions unchanged | existing cursors | T09 | PASS |
| I09 no unrelated production change | diff audit | G01 | PASS for batch_cursor.rs only |

Numeric JSON-path ordering is not traced as PASS; it is blocked by the
pre-existing `UnifiedSearcher` gap documented in the evidence.
