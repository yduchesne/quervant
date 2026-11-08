# PR 15I-B direct-record — execution and disposition

**Final status:** `15IB_DIRECT_RECORD_REJECTED_SAFE_ROLLBACK`

| Stage | Result |
|---|---|
| S0 preflight | PASS — branch/HEAD/P0/protocol verified |
| S1 restore rejected v2 source | PASS — exact allowlist; MSRV let-chains fixed |
| S2 flat offset capture + direct decoder | IMPLEMENTED |
| S3 correctness | PASS — DR-U/reader/integration tests, structural counters |
| S4 verifier hardening | IMPLEMENTED — provenance (12 rebuilds/8 binaries), absolute RSS, selected doc_keys/oracle, safe inventory |
| S5 candidates | LZ4 `7f5b1f7`; Zstd `71d92f9` (Cargo-only diff) |
| S6 correctness topology | Local PASS; v2 RustFS compiled, not executed before rejection |
| S7 campaigns | Both complete and independently verified; both `B_CANDIDATE_INELIGIBLE` |
| S8 | Safe additive rollback `7b423fc`; production identical to P0 |
| S9 | Docs, final QA, report |

## Why rejected

Direct intra-block access removed most of the original rare-query regression,
but both codecs still exceed the frozen 10K rare `B-P06` median (1.152 / 1.158
vs 1.10). All other gates pass, including 100K rare (~1.04–1.07), storage, RSS,
reopen, build/commit, RustFS cold, and selected retrieval. The threshold was not
relaxed and no third architecture was attempted.

## Statuses

`HOSTED_CI_PENDING`, `INDEPENDENT_REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`.
