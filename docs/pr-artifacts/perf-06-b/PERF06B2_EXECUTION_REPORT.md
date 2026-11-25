# PERF-06-B2 — Snapshot-wide ordinal keyword sorting in the global Top-K collector

**Execution report.** Plan: [PERF06B2_DETAILED_PLAN.md](PERF06B2_DETAILED_PLAN.md)
(SHA-256 `871bd0116bf87a3c8e056a89ffc96adccaa0e57ad1aeb22a401f3e4db69ff70f`,
verbatim copy of the maintainer-supplied revision 1). Branch: `dev/perf06-b2`.

## 1. Identity

| Item | Value |
|---|---|
| Repository | `yduchesne/quervant` |
| B2 branch | `dev/perf06-b2` |
| Post-B1 `origin/main` | `3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc` (merge of PR #126) |
| B1 reviewed executable source | `ad66e5e833616bafaaa97e15d89cdc511d715868` |
| PR #126 state | `MERGED`, `mergedAt 2026-11-25T04:32:41Z`, base `main`, head `ad66e5e…` |
| B1 ancestry | `git merge-base --is-ancestor ad66e5e origin/main` → YES |
| B2 implementation/test commit | see `evidence/b2-delivery.txt` (`TESTED`) |
| B2 docs/evidence commit | see `evidence/b2-delivery.txt` (`FINAL`) |
| Draft PR | see `evidence/b2-delivery.txt` (URL/number) |

All ten B1-critical paths are **byte-identical** blobs between `ad66e5e…` and
`origin/main` (recorded in `evidence/b2-p0-preflight.txt`). `origin/main`
contained no B2 collector symbol before this work (X02 clear).

## 2. Scope and files

Changed production/test files (only these):

| Path | Change |
|---|---|
| `crates/quervant-core/src/search/typed_compare.rs` | crate-private `OrdinalSortKey` + `ordinal_sort_key_cmp`; `ColumnAccess::bind_keyword_sort_ordinal` forwarding; focused tests |
| `crates/quervant-core/src/search/unified.rs` | `MixedEntry.ordinal_sort`; B2 eligibility; one request-wide B1 preparation; one per-segment bind; `consider_ordinal_keyword_candidate`; `candidate_charge_parts`; `b2_observation`; focused tests |
| `crates/quervant-core/src/segment/column.rs` | crate-private `KeywordSortOrdinalColumn` (`read_sort_row` applies the existing logical Single string budget) + `ColumnReader::bind_keyword_sort_ordinal`; focused tests. No encoder/parser/wire change. |
| `crates/quervant-core/tests/perf06_b2_ordinals.rs` (new) | I01–I08 real `FsDirectory`/Index/PIT/compaction/historical-fixture lifecycle |

No change to: `Cargo.toml`/`Cargo.lock`/toolchain, `index/**`, `segment/format.rs`,
`reader.rs`, `build.rs`, `metadata.rs`, `search/execute.rs`, `search/typed.rs`,
`unified_cursor.rs`, `contract/**`, `storage/**`, `remote/**`,
`quervant-objectstore`, distributed/vector code, `.github/workflows/**`,
`benchmarks/**`, B1 plans/reports/fixtures, `AGENTS.md`, `TESTING.md` or the
plan-authoring guide. Evidence: `evidence/b2-protected-blobs.txt` (empty diff for
every protected path) and `evidence/b2-diff-inventory.txt`.

`segment/column.rs` diff consists only of the new private wrapper (2 hunks near
`KeywordOrdinalColumn`/`ColumnReader`) and an appended `#[cfg(test)]` module; the
B1 v1/v2 encoder and parser are untouched.

## 3. Algorithm as implemented

1. **Eligibility (once per request).** `keyword_ordinal_eligible` = the existing
   `keyword_sort_late_eligible` (standalone, strict root single analyzed Term,
   no typed leaves, no aggregation, no `after`, exactly one sort field, no JSON
   path/geo distance, contract `Keyword` + `Single` + columnar) **plus**
   `sort.fields[0].multi.is_none()`, a non-empty snapshot and a canonical
   `CodecSchema` field id. No config/flag/threshold.
2. **One map preparation.** After expansion/stats and before the segment loop:
   `ReaderSnapshot::prepare_keyword_ordinals(field_id, &guards, cancel)` once.
   `Ready` → numeric mode for the whole request; `NotAvailable(..)` → whole-request
   legacy mode (no retry); `IndexError::Cancelled` → `SearchError::Cancelled`;
   other `IndexError` → typed `SearchError::Index`. `NotAvailable` classification
   is isolated in `ordinal_ready_from_preparation` for direct unit proof.
3. **One bind per segment.** After `ColumnAccess::open`, bind the numeric accessor
   and `map.bind_segment(&guards[i])` exactly once. A `Ready` map without a
   matching segment column is `CorruptIndex("ready keyword ordinal map has no
   matching segment column")`.
4. **Per matched candidate** (`consider_ordinal_keyword_candidate`), after the
   existing total-hit/key/score work:
   `read_sort_row` (one `doc_ordinal`; for `Single` also the frozen
   `DecodeBudget::reserve_string`) → `OrdinalSortKey` via translator →
   legacy-equivalent logical charge → existing `experiment.check` duplicate check
   → numeric comparison against the retained worst (`ordinal_sort_key_cmp`, then
   ascending raw key bytes) → full mixed-heap rejection before mutation → owned
   one-component string tuple (`owned_keyword_sort_value`) only for a competitive
   candidate → existing `experiment.admit`. `MultiOne` decodes the complete
   legacy tuple (entry/vector/string admission and errors) before the reject
   decision and keeps its shape; its shared rank is still valid.
5. **Output/cursor.** Same global heap, same `into_sorted_vec`, same K+1
   truncation, same owned `SortValue` cursor tuple and projection.

`MixedEntry::cmp` uses the numeric comparator only when both entries carry
`Some(rank)`; otherwise it keeps `compare_candidates`. No `SortValue`/cursor
variant was added. `candidate_charge` formula is unchanged and factored into
`candidate_charge_parts` so a `MultiOne` tuple is charged without cloning the key.

## 4. INV-B2 worksheet and traceability

| INV | Implementation | Executed evidence |
|---|---|---|
| INV-B2-01 shared rank | `SegmentOrdinalMap::translate` in handler | U03 (local 0 = different terms; same term different local), I01 (Seattle in batches A/B) |
| INV-B2-02 canonical order | `ordinal_sort_key_cmp`, `ordinal_candidate_order` | U01, U02, U05, I01 |
| INV-B2-03 validate/charge all losers | step order in handler; `read_sort_row` budget; `experiment.check` before compare | U07 (accessor exact 79/80), U08, U16, U17 |
| INV-B2-04 whole-request fallback | `ordinal_ready_from_preparation`, mode `Option` | U10/U11 (classifier), I03 (genuine v1 g3/g4) |
| INV-B2-05 errors not hidden | `ordinal_preparation_error`; `?` propagation | U12, U17, I07 |
| INV-B2-06 counts/scores/projection/duplicates | unchanged `total_hits`, scoring, key, `d3c` | U04, U06, U13, I01, I02, I06 |
| INV-B2-07 one ordering, owned cursor tuple | numeric `Ord`, K+1 cursor | U04, U12, I02 |
| INV-B2-08 no cross-snapshot comparison | request/snapshot-scoped map; per-segment bind | U19, I04 |
| INV-B2-09 no per-candidate name/string | bound field id/accessor/translation | U15/U21 counters; U16 owned-string bound |
| INV-B2-10 bounded resources | existing `CandidateBudget`/`d3c` preflight | U08 (exact 209/210, heap unchanged), U16 |
| INV-B2-11 MultiOne legacy path | handler `MultiOne` branch | U06, U07, I05 |
| INV-B2-12 ineligible shapes unchanged | eligibility predicate; cursor before prepare | U09, U23, U24, I06 |
| INV-B2-13 scope/provenance | file allowlist; no benchmark edit | protected-diff proof; no B4 run |

Negative-case challenge list: missing, null, empty term, Unicode composed/
decomposed/emoji, ASCII case, NUL, prefix pairs, MultiOne, same-string/different-
local-rank, many segments, no segment, K=1/K+1, legacy v1, resource bound, corrupt
container, cancellation, stale/foreign/wrong-sort cursor.

## 5. Resources, cancellation, ownership

- The B2 candidacy adds only the inline `Option<OrdinalSortKey>` (a fixed-size
  scalar); no new heap allocation, cache, map or persistent bytes. The B1 map's
  retained charge stays owned by `MetadataBudget` through its `Arc`.
- A retained candidate keeps the **logical** owned-string charge (base + key + 32
  (+ `len+4` for `Single`) ), identical to `candidate_charge`; the handler asserts
  equality in `cfg(test)`.
- Every matched `Single`/`Missing`/`Null` candidate performs the old logical
  string budget check; `MultiOne` performs the full legacy decode (entry, vector,
  string) on every candidate. `experiment.check` runs before any reject.
- Heap preflight/commit/release and `d3c::State` are unchanged; a preflight
  failure leaves heap/duplicate state untouched (U08).
- Cancellation from B1 mapping is `SearchError::Cancelled`; B1 publication
  semantics and last-`Arc` ownership are untouched. No `Index::snapshot()` call
  was added.

## 6. Tests executed on the final source

Commands and logs in `evidence/b2-focused-tests.log`,
`evidence/b2-test_1.98.1_default.log`,
`evidence/b2-test_1.98.1_all-features.log`,
`evidence/b2-test_1.85.0_all-features.log`.

| Group | Result |
|---|---|
| New B2 lib tests (`b2_` filter) | 26 passed (20 new: U01/U02; U03–U20; U21; U07 accessor; plus pre-existing `b2_u0*` execute/score tests) |
| New B2 integration (`perf06_b2_ordinals`) | 8 passed (I01–I08) |
| B1 lib regression (`b1_` filter) | 64 passed |
| B1 integration (`perf06_b1_ordinals`) | 9 passed, 2 ignored (child-only helper executed by its parent) |
| PR 15H-B regression (`b_` filter) | 62 passed |
| Adapter contract | `query_session_constructs_exactly_one_snapshot_for_the_whole_session` passed |
| Workspace default | 2666 passed, 0 failed, 16 ignored |
| Workspace all-features | 2711 passed, 0 failed, 100 ignored |
| Workspace MSRV 1.85 all-features | 2711 passed, 0 failed, 100 ignored |

The 64-case generated differential (U13) uses seed
`0xB2_06_20_26_00_00_0001`, 1–5 segments, up to 24 docs/segment, K ∈ {1,2,5,10,20},
all four direction/placement combinations, an independent `Vec`-sort oracle and
the ineligible `Query::And` reference path.

Adjusted PR 15H-B instrumentation assertion: `b_u01_u08_u36_counts_order_and_materialization`
now expects the B2 numeric path (`b2_observation`) and asserts zero legacy
borrowed/owned-tuple counters. All of its semantic assertions (exact count, key
order, K+1 own-string bound, fallback equality, score bits) are retained. No
result/error assertion was removed elsewhere.

### Known test-topology limitation (U07 / I07)

`SegmentLimits` are fixed when the snapshot's segment readers open. For these
fixtures the container-open path itself needs more than 80 decode bytes
(`max_section_decode_bytes(79)` is refused with `requested: 600`;
`max_single_allocation(79)` with `requested: 104`), so a public snapshot cannot
reach the per-candidate 79-byte rejection. The exact `limit: 79, requested: 80`
error is therefore proven on real v2 bytes through the crate-private bound
accessor (`b2_u07_decode_budget_79_rejects_the_80_byte_single_before_discard`,
which parses geometry permissively and then applies the strict limits), and I07
proves the losing long value is fully validated under permissive limits plus the
container-wrapped corruption refusal. No limit was lowered after a failure to
obtain a green result.

## 7. Final local QA ledger (G7)

| Command | Result | Log |
|---|---|---|
| `cargo +1.98.1 fmt --all -- --check` | PASS | `b2-fmt_1.98.1.log` |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS | `b2-clippy_1.98.1_default.log` |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | `b2-clippy_1.98.1_all-features.log` |
| `cargo +1.98.1 test --workspace --all-targets` | PASS | `b2-test_1.98.1_default.log` |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS | `b2-test_1.98.1_all-features.log` |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — 93.00% lines (63885/68691) | `b2-coverage-default.log` |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 92.59% lines (65000/70199) | `b2-coverage-all-features.log` |
| `cargo +1.98.1 doc --workspace --no-deps` | PASS | `b2-doc_default.log` |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS | `b2-doc_all-features.log` |
| `cargo +1.98.1 bench --workspace --no-run` (compile only) | PASS | `b2-bench_no-run.log` |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108/108 | `b2-benchmark_scripts.log` |
| `cargo +1.85.0 fmt --all -- --check` | PASS | `b2-fmt_1.85.0.log` |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | `b2-clippy_1.85.0_all-features.log` |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS | `b2-test_1.85.0_all-features.log` |
| `git diff --check` | PASS | `b2-git_diff_--check.log` |

No baseline suites were run, no BM-10 timing, no profiler, no cross-engine
acquisition, no local RustFS startup and no `perf` study.

## 8. CI (G8)

The final executable/test source is pushed on `dev/perf06-b2` and the draft B2 PR
is opened against the accepted `main` with the existing, unchanged
`.github/workflows/ci.yml`. CI run/job status is recorded in
`evidence/b2-ci-status.txt` and `evidence/b2-delivery.txt`. A pending or
unavailable run is reported as `IMPLEMENTED_VERIFICATION_BLOCKED`, never PASS.

## 9. Decision-matrix ledger

| Row | Trigger | Action taken |
|---|---|---|
| X03 | B1 merged by merge commit; exact critical blobs match | Recorded blob/ancestry proof; proceeded from `origin/main` |
| X05 | Untracked `evidence/f2-ci-status.txt` existed before B2 (B1 F2 leftover) | Left untouched and uncommitted; no stash/reset/clean |
| X06/X08/X17–X21/X23 | Eligible request, identity map, missing/null/single/MultiOne, Desc, equal ranks, noncompetitive | Implemented frozen numeric key/branches; U01–U05, U16, U20 |
| X07 | Zero segments | No preparation; old empty result (U20/I05) |
| X09–X12 | Four `NotAvailable` reasons | Whole-request fallback classifier; real `LegacySegment` in I03 |
| X13/X14 | Cancellation / other B1 errors | `SearchError::Cancelled` / typed `Index` (U12) |
| X15 | Ready map, missing column | Exact `CorruptIndex` detail |
| X22/X27 | Cursor/batch/aggregate/JSON/geo/multi-shape | No preparation; first-page cursor keeps owned string tuple (U09/U23/U24, I02/I06) |
| X24/X25/X45 | Allocation failure / mixed heap / charge mismatch | Error before mutation; mixed heap rejected; charge asserted (U08/U14/U22) |
| X33 | Test-harness directory-name collision under parallel all-features run; MSRV `useless_vec` lint | Narrow fixes: local `B2TempDir` helper in the new test file (frozen B1 helper untouched) and array literal; all invalidated gates rerun |
| X34 | Per-candidate 79-byte rejection unreachable through a public snapshot (container open needs more) | Not a semantic change: accessor-level exact evidence retained; limitation documented in §6, no limits lowered after failure |
| X39 | Docs/evidence changed after final tested source | Docs committed separately after `TESTED`; protected diff `TESTED..FINAL` empty |
| X41 | No timing acquired | B4 handoff only |

## 10. Residual risks

- The B1 map can be unavailable (legacy/mixed segments, resource budget,
  allocation, unsupported field); B2 then uses the legacy string/typed path.
- Old PITs keep their own ranks; ranks are not durable identities and may
  renumber on a new snapshot/compaction.
- `MultiOne` pays the legacy decode on every matched candidate.
- Strings are still materialized for *competitive* heap entries (not only final
  winners).
- Reader cache/open costs and the A6 remote-compaction publication residual are
  unchanged and not qualified by B2.
- No latency, whole-index footprint or RSS claim is made. B4 owns warm
  qualification; B3 owns document-key identity.

## 11. Next dependency

B3 (document-key/duplicate identity) and B4 (cumulative correctness plus a
separately approved warm qualification) are not started. G10 (maintainer
acceptance/merge) remains open; the coding agent does not merge or approve.
