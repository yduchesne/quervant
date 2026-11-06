# PR 15H-A — integration qualification

## Local production-path suite

`crates/quervant-core/tests/pr15h_a_candidate_materialization.rs` runs against
the public index/writer/reader/search boundary and does not depend on the
rejected crate-private helper.

| ID | Test | Coverage |
|---|---|---|
| HA-I01 | `h_a_i01_local_commit_reopen_term_query` | Real `FsDirectory`, 2,048 docs, commit, fresh reopen, K10/K100, Term vs And parity and projection |
| HA-I02 | `h_a_i02_two_segment_differential` | Two committed segments, sparse/medium/common terms, doc-id/score parity |
| HA-I03 | `h_a_i03_mixed_fallback_shapes` | MatchAll, Or, Not, And and Phrase against an independent document-set oracle |
| HA-I04 | `h_a_i04_pit_refresh_delete_upsert` | Old snapshot preserved; new snapshot reflects delete/upsert/commit |
| HA-I05 | `h_a_i05_limits_and_cancellation` | Tight candidate bytes typed `ResourceLimit`; clean retry; cancelled flag typed `Cancelled` |
| HA-I06 | `h_a_i06_corruption_injection` | Corrupted committed segment rejected with a typed error, never a panic |

Result at candidate SHA: **6 passed**.
Result after the production rollback: **6 passed** (the baseline postings branch
and the fallback satisfy the same observable contract).

## RustFS / remote

HA-I07 and HA-I08 use the existing real-RustFS suites rather than a fake:
`pr15g_b_rustfs`, `pr13_remote_proxy`, `pr13_crash_rustfs` (k0 and k05 10/10).
PR 15H-A modifies no format, reader, cache, writer or remote path, so these are
regression gates only. Their execution status is recorded in `qa-ci.md`; a
missing container/credentials is reported as `PENDING`, never replaced by a fake.
