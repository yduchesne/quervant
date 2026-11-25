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

The executable/test source `237ae6dcc01d1c179f292b05cf843df76c9f6ad4` was pushed
on `dev/perf06-b2`; the draft B2 PR (#127, base `main`) ran the existing,
unchanged `.github/workflows/ci.yml` (`pull_request`, run `45557000136`) on the
then-tip `e396177eb0a29a087228cf841bde18ddecf49947`, whose diff from `TESTED` is
empty under `crates/`, `.github/`, `benchmarks/` and `Cargo.*`. **All five required
jobs are terminal success**: `rust` 21m58s, `msrv` 10m2s, `rustfs` 2m21s,
`benchmark-adapter-contract` 1m33s, `python-benchmark-framework` 4m49s. The real
RustFS job actually executed
`cargo test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored`
and `b1_r01_cold_shared_ordinals_and_pit ... ok`
(`evidence/b2-ci-status.txt`, `evidence/b2-ci-rustfs-extract.txt`). Later commits
on the branch are evidence/report text only; the agent records the actual branch
tip in its final response. Nothing was dispatched, cancelled or re-run manually.

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

# F1 independent-review correction

This section is additive and supersedes **only** the overbroad G3/G4/G5 claims of
the B2 report above where they concern (a) hidden mixed-heap detection ordering
and (b) the I07 losing-candidate fixture. Earlier negative evidence and the
original QA log remain historical record and are not retroactively rewritten.

F1 plan: [PERF06B2_F1_DETAILED_FIXUP_PLAN.md](PERF06B2_F1_DETAILED_FIXUP_PLAN.md)
(SHA-256 `bf3de7919361c1a8a20bf187a356200c1b41cc46ee53d87a47ea16b8ee737815`,
git blob `c64ca43aee059cac4b64f797722c21c0d5824074`, verbatim).

## F1 pre-implementation invariant worksheet (gate G1)

Starting head `ca573ef624529418fd1a6e4bdaa978b4e75f6b2a`; reviewed executable
source `237ae6dcc01d1c179f292b05cf843df76c9f6ad4`; accepted `main`
`3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc`. The diff
`TESTED..HEAD` contains documentation/evidence only (D02).

| INV | Current symbol / behavior | Positive proof | Counterexample / negative proof | Test |
|---|---|---|---|---|
| F1-INV01 | `consider_ordinal_keyword_candidate` compares `heap.peek()` before `ensure_ordinal_heap` at ~L2341/L2370 | Audit before first numeric comparison; every admitted entry `Some` by construction | Numeric worst + hidden legacy `None`; a losing candidate must still error, not return `Ok` | `b2_f1_u01_hidden_mixed_heap_rejected_even_for_loser` (red first) |
| F1-INV02 | `ensure_ordinal_heap` is a full O(K) scan called per competitive candidate | One `OrdinalHeapAudit { checked }` per Ready request; O(1) afterwards | 1,000 competitive admissions must not rescan | `b2_f1_u02_one_time_audit_and_numeric_only_admissions` |
| F1-INV03 | `MixedEntry::cmp`, `heap_admit_candidate`, `d3c::State::admit`, K+1 cursor | Unchanged ordering/count/score/charge/cursor | Lost/duplicate hit, wrong tie, skipped duplicate check | existing B2 U03–U18/U22, I01/I02 |
| F1-INV04 | I07 has only two matching rows while K+1=2 | Three rows `a`,`b`,`z×80`; third lexically loses after two admissions | Two-doc fixture cannot fill K+1; page omission is not rejection | strengthened I07 + `b2_f1_u03_long_loser_after_k_plus_one` |
| F1-INV05 | segment limits fixed at snapshot open; container open needs >80 bytes | `U07` bound accessor exactly `LimitExceeded{79,80}`; public I07 permissive | Do not lower limits or claim public 79-byte rejection | existing B2-U07 / I07 |
| F1-INV06 | I07 rebuilds a valid outer container with corrupt unselected term | exact `InvalidUtf8{context:"keyword"}`; original bytes/map intact | Raw edit without envelope is invalid | I07 second half; B2-U17 |
| F1-INV07 | allowlist: only `search/unified.rs` + the B2 integration file | protected-path diff empty; no format/cursor/d3c/benchmark change | changed B1 codec, `d3c`, limits, CI or benchmark | G0/G7/G9 inventory |

State boundaries: `NotAvailable`/ineligible = legacy (no audit); `Ready` = numeric
only; audit `Unchecked → Verified` once per request after a successful scan; error
leaves `checked=false`, heap and accounting untouched; empty heap/zero candidates
need no scan. Candidate order stays row read/Single budget → translation →
logical charge/MultiOne decode → duplicate check → audit → numeric compare →
owned string only on admission. No durable/remote state is introduced.

## F1 source identity and production delta

| Item | Value |
|---|---|
| PR / branch / base | #127 / `dev/perf06-b2` / `main` (draft, open) |
| F1 starting head | `ca573ef624529418fd1a6e4bdaa978b4e75f6b2a` |
| Reviewed B2 executable source | `237ae6dcc01d1c179f292b05cf843df76c9f6ad4` |
| TESTED (F1 source+tests) | `7218d5e57c0ce1734a94ed0db93f94a3a7ecf477` |
| Accepted post-B1 `main` | `3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc` |
| F1 plan | SHA-256 `bf3de7919361c1a8a20bf187a356200c1b41cc46ee53d87a47ea16b8ee737815`, blob `c64ca43aee059cac4b64f797722c21c0d5824074` |

The only production mutation is in `crates/quervant-core/src/search/unified.rs`:
one request-local `OrdinalHeapAudit { checked: bool }`, created when the request
has a B1 `Ready` map, passed into `consider_ordinal_keyword_candidate`, and
invoked as `audit.verify_once(heap)?` immediately after the existing duplicate
check and **before** any numeric comparison. The former
`ensure_ordinal_heap(heap)?` immediately before materialization was removed. The
one existing test-only `Cell` observation (`b2_observation::full_heap_audits`) is
`#[cfg(test)]` and compiled out of normal builds. The integration file gained the
third I07 source row and exact assertions. No B1 codec/map, `typed_compare`,
`segment/column`, `d3c`, heap charge, cursor, format, storage, remote, CI or
benchmark file changed.

### Preservation argument (F1-INV01/02)

The request heap starts empty. `verify_once` scans every existing entry before the
first numeric competitiveness decision; with healthy production data that first
scan sees the empty heap. For the rest of that same `Ready` request the only
insertions/replacements are `MixedEntry` values built by the numeric handler with
`ordinal_sort: Some(key)` and moved through the unchanged
`d3c::State::admit` → `heap_admit_candidate` path; eviction only removes entries,
and the legacy branch never executes while `ordinal_binding` exists
(`continue`). Therefore every retained entry stays `Some` inductively. Source
inspection of every `heap.push`/`heap.pop` under default and
`pr15i-d3c-experiment` confirms no other insertion path exists in that request.
Full scan at most once per eligible request; O(1) thereafter. No benchmark was
run (D32).

## F1 adversarial results

### F1-U01 (F1-01) — hidden legacy entry with numeric worst

Initial RED witness on the reviewed source (scratch detached worktree at
`ca573ef`, test-only addition, no production edit; `evidence/b2-f1-red-u01.log`):
the production handler returned `Ok(())` for the numeric-losing `k2="z"`
candidate while a hidden `ordinal_sort=None` entry remained in the `K+1=2`
heap — the exact reviewed defect.

After the fix (`b2_f1_u01_hidden_mixed_heap_rejected_even_for_loser`): real B1
v2 segment `k0="a"`, `k1="b"`, `k2="z"`; real translated ranks; synthetic heap
`k0` legacy `None` + `k1` numeric `Some(rank_b)`; `peek()` asserted to be `k1`
numeric; a fresh unchecked audit; real handler call for doc 2. Exact
`Err(CorruptIndex { detail: "mixed ordinal and legacy sort entries" })`,
`numeric_compares()==0`, `owned_single_strings()==0`,
`full_heap_audits()==1`, heap keys/ranks/charges/scores/length unchanged.
Positive arm: both entries `Some`, fresh audit, same losing `z` returns `Ok`,
`numeric_compares()==1`, `owned_single_strings()==0`, one audit, no mutation.

### F1-U02 (F1-INV02) — one audit under maximum competition

`b2_f1_u02_one_time_audit_and_numeric_only_admissions` reuses the 1,000-document
descending-input fixture where every candidate is competitive: `total_hits=1000`,
ordered keys, `owned_single_strings()=1000`, `numeric_compares()=999`, and
`full_heap_audits()==1`. A second eligible request on the same cached map audits
exactly once again. An ineligible `Query::And([Term])` request prepares no map and
audits zero times. U16 remains unchanged and passes.

### F1-U03 / strengthened I07 (F1-02) — genuine third-candidate loser

Fixture: one real `FsDirectory` v2 segment, physical/doc-id order `k0="a"`,
`k1="b"`, `k2="z"×80`, all `body=common`, `K=1` (`K+1=2`). Exact results:

| TopK | total_hits | keys | next_cursor Kth value |
|---:|---:|---|---|
| 1 | 3 | `["k0"]` | `Some`, `Keyword("a")` |
| 2 | 3 | `["k0","k1"]` | `Some`, `Keyword("b")` |
| 3 | 3 | `["k0","k1","k2"]` | `None` |

`b2_f1_u03_long_loser_after_k_plus_one` proves the third candidate is the loser
rather than page truncation: `numeric_candidates=3`, `numeric_compares=1`,
`owned_single_strings=2`, `single_rejected_without_copy=1`,
`full_heap_audits=1`, `total_hits=3`, keys `["k0"]`, with
`Query::And([Term])` parity for keys, count, score bits and projected fields.
I07 also asserts the real `doc_keys` order `k0,k1,k2`, the
`FEATURE_KEYWORD_ORDINALS` requirement, the existing `city` ordinal column, the
complete six-field projected values per row (literal input constructor), and
legacy parity for K=1/K=2. The old two-row topology (K+1 not filled) is no longer
used as proof.

The corrupt-unselected half is preserved: a valid outer `ContainerBuilder`
envelope around a mutated `Seattle` dictionary term still fails with exactly
`SegmentError::InvalidUtf8 { context: "keyword" }`, and the original immutable
segment bytes plus snapshot-map readiness remain intact.

**79/80 statement (F1-INV05, D22):** the exact
`LimitExceeded { limit:79, requested:80 }` remains established by the existing
bound-accessor unit test on real v2 bytes. The public I07 snapshot cannot reach
that per-value threshold because its container-open admission itself requires
more than 80 bytes. No limit was lowered and no public 79-byte failure is
claimed.

## F1 local gate results (G0–G6, G9)

| Gate | Evidence | Result |
|---|---|---|
| G0 preflight | `evidence/b2-f1-preflight.txt` | PASS — pinned PR/branch/base, only docs since TESTED, harmless untracked B1 `f2-ci-status.txt` preserved (D04a) |
| G1 worksheet | section above | PASS — F1-INV01..07 mapped |
| G2 implementation | source diff | PASS — one request-local bool audit, scan before compare, late scan removed |
| G3 unit | `evidence/b2-f1-focused-tests.log`, `b2-f1-red-u01.log` | PASS — F1-U01/U02/U03 + U08/U14/U16 aliases; red witness retained |
| G4 integration | `b2-f1-focused-tests.log` | PASS — I07 exact K=1/2/3, corruption half, all I01–I08 |
| G5 regression | same log | PASS — B2 lib 29, B1 lib 64, B1 integration 9+2 ignored, PR15H `b_u` 12 |
| G6 final QA | `b2-f1-qa-*.log`, `b2-f1-coverage-*.log` | PASS — see table below |

Final QA on TESTED `7218d5e...`:

| Command | Result |
|---|---|
| `cargo +1.98.1 fmt --all -- --check` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets [--all-features] -- -D warnings` | PASS (both) |
| `cargo +1.98.1 test --workspace --all-targets` | PASS — 2669 passed, 0 failed, 16 ignored |
| `… --all-features` | PASS — 2714 passed, 0 failed, 100 ignored |
| `cargo +1.98.1 llvm-cov … --fail-under-lines 85` | PASS — 93.03% (64176/68986) |
| `… --all-features` | PASS — 92.62% (65291/70494) |
| `cargo +1.98.1 doc … [--all-features]` | PASS |
| `cargo +1.98.1 bench --workspace --no-run` (compile only) | PASS |
| adapter `query_session_constructs_exactly_one_snapshot_for_the_whole_session` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108/108 |
| `cargo +1.85.0 fmt/clippy --all-features/test --all-features` | PASS — 2714 passed, 0 failed, 100 ignored |
| `git diff --check` | PASS |

No benchmark acquisition, profiler, cross-engine run or RustFS service was
started (D32).

## F1 decision ledger

| Rule | Applied action |
|---|---|
| D01 | PR #127 open/draft, `dev/perf06-b2 → main`, pinned head; fast-forward only; no force ops |
| D02 | Head differed from reviewed executable source only by docs/evidence; executable/test blobs compared |
| D04a | Untracked B1 `evidence/f2-ci-status.txt` recorded, left byte-identical and uncommitted |
| D06/D07 | One audit per Ready request; handler and the two U08 test call sites updated mechanically (one shared audit) |
| D08/D09/D10 | Full scan once on first numeric candidate, before comparison; exact `CorruptIndex` on any `None`; O(1) afterwards |
| D11/D12 | Existing `d3c`/heap admission reused; source inspection found no `None` insertion path in a Ready request |
| D16 | Hidden-legacy fixture explicitly asserts numeric `peek()` and a deeper `None` |
| D19/D20/D21 | Three real rows `a`,`b`,`z×80`; third loses with exact counters instead of page-only inference |
| D22 | Bound-accessor 79/80 evidence retained; no public 79-byte claim |
| D24/D27 | Narrow test-source corrections only (F1 tests and I07); invalidated gates rerun |
| D30 | Only `#[cfg(test)]` `Cell` observation; release source inspected |
| D32 | No timing; structural complexity documented and deferred to B4 |
| D33 | Docs/evidence committed after TESTED with protected-path diff proof |

No HARD STOP row applied.

## F1 residual risks

Unchanged from B2: B1 map optional unavailability, legacy/mixed segment limits,
MultiOne full decoding, competitive-entry string materialization, no stable
cross-snapshot rank identities, no B3 identity change, A6 remote-compaction
publication unqualified, and no warm/RSS/footprint claim. The audit is a
one-time proof plus inductive construction invariant; it is not a
memory-corruption detector for arbitrary post-proof mutation outside the approved
query code.

## F1 hosted CI (G7/G8)

Run `45662385666` (`pull_request`, head `cd4abd061a10f89e522fb0cf93849925c28099f1`)
is terminal **success** with exactly the five existing jobs: `rust` 22m16s,
`msrv` 10m40s, `rustfs` 2m45s, `benchmark-adapter-contract` 1m42s,
`python-benchmark-framework` 3m25s. The hosted real-RustFS job actually executed
`cargo test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored`
and `b1_r01_cold_shared_ordinals_and_pit ... ok`
(`evidence/b2-f1-ci-status.txt`, `evidence/b2-f1-ci-rustfs-extract.txt`).
`TESTED (7218d5e)..cd4abd0` is empty for `crates/`, `.github/`, `benchmarks/`
and `Cargo.*`; the only delta is the F1 plan/report/evidence. No workflow edit,
manual dispatch, cancellation or rerun occurred. A later evidence-only commit
keeps the same executable/test tree; the agent records the actual final branch
tip and its CI run in its final response.

**F1 disposition:** `PERF06_B2_F1_READY_FOR_INDEPENDENT_REVIEW` once the
docs-only final-head CI is terminal green; G10 remains maintainer-owned. No B3/B4
work was started and no performance claim is made.
