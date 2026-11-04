# PR 15G-A decision log

Only rules from the approved matrix are recorded. No unrecognized condition was
resolved by inventing behavior.

| Rule | Trigger observed | Action taken | Verification / remaining gate |
|---|---|---|---|
| GA-D01 | clean `main` at `f44d7f4...`; source shape matched §3 | created `dev/pr15g-a-retained-column-geometry` and executed phases 0–5 | preflight identity; A00 PASS |
| GA-D04 | `ColumnMeta` primitive-only; existing parser uses `try_reserve_exact` | implemented owned/borrowed `ColumnGeometry` without cloning on hit | GA-U01/U02/U07/U12; A01 PASS locally |
| GA-D05 | `ColumnReader` callers unchanged | preserved public signatures; routed both parser entry points through one private body | workspace tests; A01/A03 PASS locally |
| GA-D06 | `meter` already present in `decode_metadata` | retained geometry only on the metered candidate; added allowance and measured capacity charge | GA-U08/U09/U10, `g5_01`; A02 PASS locally |
| GA-D07 | absent COLUMNS vs present zero-column section | preserved `None` vs `Some(empty geometry)` | GA-U04; A01/A03 PASS locally |
| GA-D08 | zero cap / candidate reservation failure | unchanged fully validating uncached fallback; no shared retention | GA-U08/U09 and `g5_01`; A02 PASS locally |
| GA-D09 | corrupt state tag/truncation/type mismatch | propagated the original typed validator error | GA-U05/U06/U14; A03 PASS locally |
| GA-D10 | metering/limits can reject before an underlying corruption is reached | fallback re-discovers the authoritative typed error; no admission error is reported as corruption | GA-U11 and snapshot fallback tests; A03 PASS locally |
| GA-D14 | borrow source is the same-state `Arc<VerifiedSegmentState>` | borrowed `&shared.column_geometry` and the same COLUMNS body slice into a query-local reader | GA-U12/U13 and `g5_01`; A01/A03 PASS locally |
| GA-D17 | no deterministic pre-existing baseline failures | no baseline failure was waived or reclassified | baseline logs in `target/pr15g-a/qa/baseline-*.log` |
| GA-D18 | two new tests failed only after implementation | fixed inside the approved model (expected block counter; rebuild container with valid envelope digest) and reran affected suites | column/reader/integration tests PASS |
| GA-D19 | no fix required a third production file | scope stayed within the two authorized production files plus snapshot test-only coverage | staged diff |
| GA-D20 | no explicit operator idle authorization | skipped timed comparison; recorded `PERF_BLOCKED_OPERATOR`; ran only the negative authorization test | P01–P04 BLOCKED; A07 BLOCKED |
| GA-D24 | hosted CI status not available from this session | no green CI claim; exact-head hosted acceptance remains blocked until pushed/observed | A09 BLOCKED / NOT OBSERVED |
| GA-D25 | RustFS service/image unavailable | kept local implementation and tests; did not substitute a fake for GA-I07/I08 | A06 real-RustFS portion BLOCKED |
| GA-D28 | all locally executable gates passed; no unclassified finding | prepared evidence and branch for independent review; did not self-approve or merge | status `QA_PASS_PERF_BLOCKED_OPERATOR`; A10 NOT STARTED |
| GA-D30 | routine phase completion | continued through implementation, tests, runner and documentation without gratuitous approval requests | phase log above |

## Scope and guardrail confirmations

- No `unsafe`, new dependency, lockfile change, public API change, segment
  format change, manifest change, storage-provider change or query-semantic
  change was introduced.
- `index/snapshot.rs` production logic, `segment/metadata.rs` semantics,
  `search/{unified,execute,typed_compare}.rs`, PR 15D/15E/15F benchmarks and
  reports were not modified.
- The only snapshot change is an additive test module covering the new
  geometry admission/fallback lifecycle.
