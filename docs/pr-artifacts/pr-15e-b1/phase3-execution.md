# PR 15E Phase 3 — execution record

**Optimization:** selective stored-document materialization (one optimization, same
PR/branch, no new PR). **Implementation head:** `2470b00` (single implementation
commit); **runner stage:** `4330cc9`. Phase entry was
`5553c3bba268b9b268b51117e54eb256772ec19c` on
`dev/pr15e-b1-live-bitmap-postings-membership`, on top of `main`/PR #82 merge
`c3083d83ab88fd53f30d34d34c4860d29aa6493e`.

**Status: `PHASE3_PERF_MEASURED`** — implementation, the full mandatory QA matrix and the
targeted seven-lane performance matrix are complete. Main results: primary
`100K/rare/k100` 78.65 ms → 32.17 ms (ratio 0.409, all three paired trial ratios < 1);
6 of 7 lanes `B_FASTER`, the no-projection `absent` control `INCONCLUSIVE`, 0 `A_FASTER`.
See `phase3-qualification.md`; independent phase review is pending and no Phase 4 work has
started.

## 1. P0 preflight (observed, read-only)

| Check | Observation |
|---|---|
| Branch | `dev/pr15e-b1-live-bitmap-postings-membership` |
| HEAD at phase entry | `5553c3bba268b9b268b51117e54eb256772ec19c` — matches the plan's fixed predecessor |
| Tracked tree | clean (0 entries from `git status --porcelain=v1`) |
| `origin/main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (PR #82 merge) |
| Prior B1 commits | `601765f` (B1a), `7921818` (B1b), `e0b1562`/`ed7bf06`/`5553c3b` (tooling/evidence) |
| B1 acceptance evidence | `docs/pr-artifacts/pr-15e-b1/qualification.md`, `benchmarks/reports/pr15e-b1/targeted-comparison.json` present and untouched |
| Unknown Phase 3 work | none — no prior Phase 3 code existed on the branch |

### Signatures inspected on the phase-start branch

| Location | Observed contract |
|---|---|
| `segment/reader.rs` | `pub fn stored(&self) -> SegmentResult<Rc<Vec<StoredRecord>>>` (query-local `RefCell<Option<Rc<...>>>` cache); `pub fn stored_doc(&self, doc_id: u64)`; `fn body(&self, kind)`; `SegmentReader::from_shared` never mutates shared state |
| `segment/stored.rs` | `pub fn encode_stored(schema, docs, limits)`; `pub fn decode_stored(schema, bytes, limits)` — sequential v1 records, one cumulative `DecodeBudget`, `expect_end`; no offset table |
| `segment/value.rs` | `pub(crate) fn decode_field_values_budgeted(reader, field_type, limits, budget)`; private `decode_scalar_budgeted` / `decode_json_budgeted`; `check_len` / `check_count`; `STATE_*` tags |
| `segment/decode_budget.rs` | `reserve_bytes` / `reserve_vec<T>` / `reserve_string` / `reserve_btree_entry<K,V>`, cumulative and atomic |
| `search/unified.rs` | `fn project_selected_hits(snapshot, plan, ledger, hits, memory)` — groups by segment, opens a guarded reader, verifies `reader.doc_key(doc_id) == hit.key`, then `stored_doc` + `plan.project` + `ledger.reserve_with_memory` |
| `search/projection.rs` | `ProjectionPlan::compile/project`, `projected_hit_bytes`, `ProjectionLedger` (unchanged) |
| `benchmarks/pr15e_b1/run_targeted.py` | stage table, `stage_lanes`, `compare_summaries`, `execute`, `--idle-confirmed` gate |

## 2. Implementation as applied

### P1 — `value.rs`: allocation-free validated consumption

Added `skip_field_values_budgeted`, private `skip_scalar_budgeted`, private
`skip_json_budgeted`. They consume exactly the bytes the accepted decoders consume,
run the same checks in the same order, return the same typed errors, and issue the
same modeled `DecodeBudget` reservations, while allocating nothing for the value.

Pinned semantic decisions:

* **Raw `F64` field and JSON `f64`**: the accepted decoders do **not** reject
  non-finite payloads on read (only the encoders do). The skip path therefore does not
  reject them either — differential parity with the accepted decoder is the governing
  contract, and adding a new rejection would have changed the decode-admissibility
  surface (D11). `GeoPoint` still validates through `GeoPoint::new`, exactly as before.
* `Mutable`/`MULTI` zero count, `check_entries`, `max_array_elements`,
  `max_single_allocation` and JSON depth bounds are enforced identically.

### P2 — `stored.rs`: `decode_stored_selected`

`pub(crate) fn decode_stored_selected(schema, bytes, limits, selected_doc_ids)`:

* validates strictly increasing, duplicate-free ids (context `stored selection`) and
  range (`count`; context `stored`, detail `doc id out of range`);
* repeats the header/version/count/`check_entries`/`count_min_bytes` checks in the same
  order as `decode_stored`;
* reserves the **full-decode** modeled budget (`reserve_vec::<StoredRecord>(count)` plus
  every key, present-field entry and nested value) while allocating only
  `selected_doc_ids.len()` result slots via `try_reserve_exact`;
* scans every record in `0..count`, validating key UTF-8 and the constructor's exact key
  rules (non-empty, `<= DocumentKey::MAX_BYTES`) without building an owned key for
  unselected records, the presence bitmap, each set bit's stored-ness, the exact field
  id, and then either the normal decoder (selected) or the skip path (unselected);
* calls `expect_end("stored")` and fails if any requested id was not materialized.

`encode_stored` and `decode_stored` are unchanged.

### P3 — `reader.rs`: `stored_docs_selected`

`pub(crate) fn stored_docs_selected(&self, ascending_unique_ids)` clones only the
requested records when a full decode already exists in this reader's query-local cache,
otherwise performs the single selective scan through `decode_stored_selected`. It never
installs `stored_cache` and never writes shared verified state; `stored()`/`stored_doc()`
are byte-identical to before (a test-only `stored_cache_is_populated()` witness was added
behind `#[cfg(test)]`).

### P4 — `unified.rs`: batched projection

`project_selected_hits` now performs, per segment group: (1) physical key parity for
**every** selected hit before any stored work (same error as before), (2) build, sort and
dedup the per-segment physical id list (bounded by selected hits, not document count),
(3) exactly one `stored_docs_selected` call, (4) projection in the original output order
via `binary_search_by_key` on the returned tuples. `ProjectionPlan`, `ProjectionLedger`,
batch memory, response bytes, cursor, ranking and totals are untouched.

## 3. Invariant traceability (actual tests executed)

All tests below were executed and passed on the final head; names are exact.

| ID | Tests | Result |
|---|---|---|
| P3-I01 | `segment::tests::phase3::phase3_u01_u02_selection_boundaries`, `phase3_u13_generated_fixtures_match_full_decode`, `pr14_projection::phase3_i01_i02_projection_matches_full_decode_for_every_type` | PASS |
| P3-I02 | `segment::value::phase3_tests::phase3_skip_matches_decode_on_malformed_inputs`, `segment::tests::phase3::phase3_u04_u05_u06_u14_unselected_corruption_is_rejected`, `phase3_u08_invalid_keys_are_rejected` | PASS |
| P3-I03 | `segment::value::phase3_tests::phase3_skip_matches_decode_under_tight_budgets`, `segment::tests::phase3::phase3_u07_u10_budget_parity_exact_and_one_below` (exact byte-equal ceiling and one-below rejection for both paths) | PASS |
| P3-I04 | `pr14_projection::phase3_i01_i02_*`, `phase3_i04_generations_and_pit_project_only_live_records`, `phase3_i05_i07_interleaved_segments_sort_and_cursor` | PASS |
| P3-I05 | `phase3_i04_*` (delete + upsert + pinned PIT), existing `pr09_*`, `pr06_local_integration`, real RustFS suites | PASS |
| P3-I06 | `segment::tests::phase3::phase3_u11_u12_reader_selected_accessor_and_cache_order` (both cache orders, no cache installed by the selective path) | PASS |
| P3-I07 | `unified::tests::phase3_projection_ledger_is_exact_and_one_below_is_rejected`, `phase3_projection_preserves_positions_and_duplicate_physical_ids`, `phase3_zero_hits_opens_no_reader`, `pr14_projection::phase3_i03_batch_and_standalone_projection_parity` | PASS |
| P3-I08 | diff audit: `git diff --name-only 5553c3b..HEAD` touches only the five allowed source/test files plus the runner and docs; `format.rs`, `decode_budget.rs`, `limits.rs`, `schema.rs`, `projection.rs`, `execute.rs`, `work.rs`, `.github/**`, `Cargo.toml`/`Cargo.lock`, `AGENTS.md`, frozen PR15D/PR15E-A paths: **0 changes** | PASS |
| P3-I09 | runner `p3` stage pinned to `5553c3b` + descendant, 7 fixed lanes, `--idle-confirmed`, three trials, oracle/contention checks | PASS — 3 trials/arm, 42/42 `clear` probes, oracle per lane and per sample |

| Plan ID | Test | Result |
|---|---|---|
| U01/U02 | `phase3_u01_u02_selection_boundaries` | PASS |
| U03 | `phase3_skip_matches_decode_for_every_state_and_type` (all 11 field types × 5 states, incl. nested JSON) | PASS |
| U04/U05/U06 | `phase3_u04_u05_u06_u14_unselected_corruption_is_rejected` (invalid bool, invalid UTF-8 keyword, unknown JSON tag, invalid geo, invalid CIDR, truncated, trailing, bad version, misaligned field id, non-stored presence bit) | PASS |
| U07 | `phase3_skip_matches_decode_on_malformed_inputs` (zero multi, unknown state, oversized text/array, JSON depth overflow, overlong varint, truncated payloads) | PASS |
| U08 | `phase3_u08_invalid_keys_are_rejected` (empty and oversized keys in unselected records) | PASS |
| U09 | `phase3_skip_matches_decode_for_every_state_and_type` (cursor + modeled budget equality) | PASS |
| U10 | `phase3_u07_u10_budget_parity_exact_and_one_below`, `phase3_skip_matches_decode_under_tight_budgets` | PASS |
| U11/U12 | `phase3_u11_u12_reader_selected_accessor_and_cache_order` | PASS |
| U13 | `phase3_u13_generated_fixtures_match_full_decode` (200 deterministic seeds, LCG constant in test) | PASS |
| U14 | `phase3_u04_u05_u06_u14_*` (corruption after the last selected record) | PASS |
| U15 | `unified::tests::phase3_projection_ledger_*` | PASS |
| I01/I02 | `pr14_projection::phase3_i01_i02_*` (production writer→snapshot→search, all stored types/states, Source vs Fields parity, no unstored leakage) | PASS |
| I03 | `pr14_projection::phase3_i03_batch_and_standalone_projection_parity`; batch memory exact/one-below already covered by `pr14_batch_memory` (31) and `unified::tests::c3_path_batch_parity_and_memory_reject` | PASS |
| I04 | `phase3_i04_*` | PASS |
| I05/I07 | `phase3_i05_i07_*` (32 hits across 4 segments, cursor paging, no duplicate/omitted hit) | PASS |
| I06 | local `FsDirectory` suites: `pr07_integration`, `storage_fs_integration`, `storage_conformance`, `cache_async_integration`, `pr06_local_integration` | PASS |
| I08 | real RustFS gate (26 invocations, see §4) | PASS |

## 4. Mandatory QA — actual results on head `4330cc9`

Toolchains: stable `cargo 1.98.1`, MSRV `cargo 1.85.0`. Logs are private under
`target/pr15e-b1-qa/` (gitignored).

| Gate | Result |
|---|---|
| `cargo fmt --all -- --check` (stable + 1.85.0) | PASS (exit 0) |
| `cargo clippy --workspace --all-targets -- -D warnings` (stable + MSRV) | PASS (0) |
| `… --all-features` (stable + MSRV) | PASS (0) |
| `cargo test --workspace --all-targets` (stable) | PASS — 2200 passed, 0 failed, 10 ignored (117 binaries) |
| `… --all-features` (stable) | PASS — 2204 passed, 0 failed, 75 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 2200/0/10 |
| `cargo +1.85.0 test … --all-features` | PASS — 2204/0/75 |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **lines 92.42%** (84575 lines, 6414 missed), functions 87.98%, regions 91.90% |
| `cargo doc --workspace --all-features --no-deps` | PASS (0) |
| `cargo bench --workspace --no-run` | PASS (0, compile only) |
| `cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` (stable + MSRV) | PASS — 5 tests each |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS (0) |
| `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py' -v` | PASS (0) |
| `python3 -m unittest discover -s benchmarks/pr15e_b1 -p 'test_*.py' -v` | PASS (0) — 51 tests |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (0) — 108/108 |
| `git diff --check` | PASS (0) |
| PR15E real-adapter integration (`PR15E_RUN_REAL_INTEGRATION=1`) | PASS — recorded `source_sha=4330cc9…` |
| Real RustFS suite (26 invocations: s3 8, proxy 5, remote 3, oracle 1, oracle_geo 1, m1 1, m2 1, m3 1×3, m5 1×3, crash proxy 7, k0 5, k05 1×10) | PASS |
| Exact-head GitHub CI (`rust`, `msrv`, `rustfs`) | **BLOCKED (credentials)** — `gh` token invalid, branch not pushed; no CI claim is made |
| Phase 3 targeted performance (`p3`) | **PASS** — operator-attested, 3 trials/arm, 7 lanes; see `phase3-qualification.md` |

RustFS ran under **podman** (Docker absent) using the exact CI image digest
`rustfs/rustfs@sha256:1803faef…`, the exact CI env vars and the exact CI commands; the
container was removed afterwards. CI must still run the authoritative `rustfs` job.

## 5. Triggered decision-matrix entries

| ID | Trigger (observed) | Category | Action / prohibited alternative |
|---|---|---|---|
| D01 | Branch at `5553c3b`, clean, signatures as reviewed | AUTO-RESOLVE | Implemented P1–P4 on the same branch; no new PR |
| D02 | G11 dossier still `PENDING_REVIEW`; waiver recorded in the B1 decision log | AUTO-RESOLVE | Waiver treated as implementation authorization only; dossier untouched; no G11 PASS claimed |
| D04 | Selected ids sorted/unique/in range at the call site | AUTO-RESOLVE | One monotone full-section scan; checked result capacity |
| D05 | Caller (executor) may hold duplicate/unordered hits | AUTO-RESOLVE | Sort+dedup only the per-segment temporary id list, decode once, restore output order |
| D06 | Reader may already hold a full query-local decode | AUTO-RESOLVE | Clone only requested records; cache preserved |
| D07 | Sequential STORED v1, no offsets | AUTO-RESOLVE | Strict one-pass validation of **all** records; no early exit; no persisted offsets |
| D08 | Unselected text/keyword/JSON values | AUTO-RESOLVE | UTF-8 + canonical count/tag/limit validation and mirrored budget charge; no owned value |
| D09 | Unselected IP/CIDR/Geo/bool/numbers | AUTO-RESOLVE | Existing validated primitives invoked, results discarded |
| D11 | Full-decode budget parity | Verified, not triggered | Differential tests show equal `retained()` and equal exact/one-below behaviour; no cap was relaxed |
| D12 | Selected record with MULTI/JSON states | AUTO-RESOLVE | Existing `decode_field_values_budgeted` used for the **entire** selected record |
| D15 | `try_reserve_exact` failure paths | AUTO-RESOLVE | Typed `LimitExceeded`; no panicking `with_capacity` on hostile counts |
| D16 | Runner extensible behind `p3` | AUTO-RESOLVE | Added only the `p3` stage; B1 stage matrices/labels/report shape preserved (regression-tested) |
| D18 | No fresh idle confirmation at first | DEFER AND CONTINUE | Code/tests/QA/docs completed first; after the operator explicitly confirmed idleness for `5553c3b`→`df9b856`, the two invocations ran with `--idle-confirmed` |
| D20 | Verdict rule for the p3 comparison | AUTO-RESOLVE | Sign-consistency only (`B_FASTER`/`A_FASTER`/`INCONCLUSIVE`); no invented threshold |
| D22 | Local Podman matches the pinned RustFS image and CI topology | AUTO-RESOLVE | Real-service tests executed and Podman disclosed |
| D23 | Invalid `gh` credentials | DEFER AND CONTINUE | `CI_BLOCKED_CREDENTIALS`; all local work completed; no merge |
| D99 | None triggered | — | — |

## 6. Residual risks and limits

* The selectivity benefit only materializes when few records are projected relative to
  the segment size; high-match lanes still project many records (bounded by selected
  hits, not by document count).
* Modeled `DecodeBudget` charges are deliberately **unchanged** (full-decode parity), so
  a query that was rejected before is still rejected; only physical allocation differs.
* Query-local only: no cross-query cache, no persisted offset table, no format change.
* F64 non-finite payloads remain accepted on read exactly as before (parity); this is a
  pre-existing decoder property, not introduced here.
* Upstream evidence: the PR15E-A attribution is a hypothesis; Phase 3 timing is the test.
  The 786 lost samples and unresolved Heaptrack buckets remain disclosed.
* Exact-head CI and PR publication remain external gates.

## 7. Head inventory

| Item | SHA |
|---|---|
| Phase entry / B1 accepted | `5553c3bba268b9b268b51117e54eb256772ec19c` |
| Phase 3 implementation | `2470b0070af3a15da45dbaa25f7c5adba297986b` |
| Phase 3 runner stage | `4330cc94bfd5bd9484b963d42c1d3a015d2e7d0d` |
| Phase 3 measured head | `df9b8565a4e47c5c66a7edeb566333643672e3fa` |
| Phase 3 evidence | `phase3-qualification.md`, `benchmarks/reports/pr15e-b1/phase3-targeted-comparison.json` |
