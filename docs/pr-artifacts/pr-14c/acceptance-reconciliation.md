# PR 14C — acceptance reconciliation

**Status: `BLOCKED / NOT ACCEPTED`.** The human `R-14A-JSON-MEM` disposition is
`REQUIRE SEPARATE CORRECTION` (see
[resource-risk-disposition.md](resource-risk-disposition.md)). Under AD-14C-06 /
E18, PR 14 cannot be marked DONE in this PR. This document is the exhaustive
crosswalk required by plan §4: every historical obligation is either mapped to
executed/current evidence, recorded as an approved exception, or marked
`BLOCKED` — none is deleted or silently reclassified as optional.

Tested source SHA: `376023b53b557a30367097f29a41328c798188d4`. PR 14C adds
documentation only; no production, codec, manifest, API or distributed change
was made (`git diff --stat` at P5: `docs/pr-artifacts/pr-14c/*` and additive
supersession notes only).

Adjudications: `PASS`, `SUPERSEDED WITH EVIDENCE`, `NOT APPLICABLE (APPROVED)`,
`BLOCKED`, `FAIL`. A `PASS` requires an executed test in
[validation-report.md](validation-report.md) (or a named CI job, where CI is the
gate) with an independent oracle.

## 1. Sources reconciled

| Generation | Source | Date / SHA |
|---|---|---|
| Original PR 14 | `pr-14/preimplementation-correctness-gate.md`, `test-traceability.md`, `final-acceptance-gate.md` | `7ca1b2e` / `e0e1dcb` (2026-10-15) |
| P2B ownership/memory | `p2b-consolidated-final-acceptance.md`, `p2b-refactor-final-acceptance.md`, `p2b-memory-final-acceptance.md` | pre-P3 |
| Remaining / corrective / final design | `remaining-*`, `corrective-*`, `final-design-*`, `f1-hardening-*` | `dev/pagination` 2026-10-16…19 |
| P4 storage/benchmark | `p4-preimplementation-reconciliation.md`, `p4-rustfs-acceptance.md`, `p4-final-acceptance.md`, `p4-benchmark-report.md`, `p4-w08-stop.md` | tested `0d005ab`, bench `ab9b2d7` |
| PR 14A | `pr-14a/implementation-evidence.md`, `test-traceability.md`, `adversarial-review.md` | Corrections 01/02; merged `7a86059` |
| PR 14B | `pr-14b/implementation-evidence.md`, `fault-matrix.md`, `compatibility-evidence.md`, `resource-risk.md` | code `556621a`; merged `376023b` |

Where a later generation **re-used an ID prefix with different meaning**, this
document keeps the generations separate. The plan forbids number-matching by
accident; no such match is made below.

## 2. STOP conditions (original §3 gate)

| ID | Historical obligation | Current meaning | Evidence | Adjudication |
|---|---|---|---|---|
| S1 | Reusable lexical leaf/scorer seam; mixed lexical+typed execution | Mixed execution implemented through the PR 7 lexical seam and the shared typed evaluator; naked fail-closed negative is no longer the contract | `pr14_unified_mixed` 14 tests, `pr14a_public_cursor::j06`, `real::b02` (nested And/Or/Not over lexical+JSON+geo+IP) | **SUPERSEDED WITH EVIDENCE** |
| S2 | Public cursor cannot represent sorted search-after | `execute_batch_pinned(&PitHandle, …)` with full private tuple continuation; naked `execute_batch` stays fail-closed | `pr14a_public_cursor` 26 tests; `real::b06_b07` page sizes 1/2 | **SUPERSEDED WITH EVIDENCE** |
| S3 | JSON missing/null/mixed ordering | `SortValue` + canonical comparator; unchanged | `pr14_json::j09/j10/j11`, 14A `j01`–`j05` | PASS |
| S4 | Indexed-but-not-stored JSON operators | Inline JSON-path section, no format change | `pr14_json::j06`, `b18_b19` | PASS |
| S5 | PR 2 missing/null/multivalue semantics | Approved A09/A10 followed; prose discrepancy recorded | `pr14_typed_predicates` t01–t03, t10 | PASS |

## 3. Invariants I01–I16 (original preimplementation gate)

Source: `pr-14/preimplementation-correctness-gate.md` §"Invariant → intended
evidence mapping".

| ID | Requirement | Current evidence (executed) | Adjudication |
|---|---|---|---|
| I01 | Identical AST + snapshot ⇒ identical logical hit set | `pr14_unified_mixed` m01–m14; `real::b02`; 14A `t02`/`j07` pagination metamorphism | PASS |
| I02 | No deleted/obsolete documents | `pr14_typed_predicates::t11_delete_and_pit`, `pr14_projection::p06`, `real::r05` | PASS |
| I03 | BM25 only from positive lexical leaves; unchanged | `pr14_unified_mixed::m04/m08/m13` (bit-exact parity), `pr14_f1_hardening::s01/s02/s05` | PASS |
| I04 | Exact counts, gap-free pagination | 14A `t02`–`t05`, `j02`; `pr14_unified_cursor::p03`; `real::b06_b07` | PASS |
| I05 | Cursor binds snapshot/query/sort/tuple | 14A `t06/t07/t10`, `real::b06_b07` negatives (wrong handle, expiry, changed query/sort) | PASS |
| I06 | JSON scalar type and range boundaries | `pr14_json` j01–j05, j08; `real::b18` | PASS |
| I07 | JSON missing/null/multivalue sort deterministic | 14A `j04/j05`, `pr14_json::j09/j10`, `b03_local_...` | PASS |
| I08 | No unstored-field leak | `pr14_projection` p01–p06, 14A `t05` | PASS |
| I09 | IP/CIDR family and missing/null truth tables | `pr14_typed_predicates` t01–t10 | PASS |
| I10 | Exact aggregates share the predicate | `pr14_aggregation` a01–a05; `pr14_compound_aggregation` t05/t07/t12; `real::r02_r04_r06` | PASS |
| I11 | Batch cardinality and shared budgets | `pr14_batch` b01–b13; `pr14_batch_memory` b10a–b13j; `real::r10_r11`; 14A `t08/t11` | PASS |
| I12 | Bounded work/memory/output, cancellation | `pr14_batch_memory` b10f/b12d/b13d; `pr14_f1_hardening::w06`; 14A `t13` | PASS |
| I13 | Zero query-time remote GET | **No dedicated instrumentation exists**; 14B notes it as unimplemented | **BLOCKED** |
| I14 | Persisted formats unchanged | `b18_b19` frozen golden; PR 13 regressions; 14C diff is docs-only | PASS |
| I15 | Legacy segments correct or typed fail-closed | Historical PR 11 legacy suites; `b18_b19` corrupt/unsupported rejection | PASS |
| I16 | Unsupported capabilities fail before expensive work | `pr14_projection::p04`, `pr14_batch::b04/b10/b13`, `pr14_f1_hardening::v01`–`v05` | PASS |

I13 is retained as `BLOCKED`; no test was invented to cover it.

## 4. Original per-domain matrices (source `pr-14/test-traceability.md`)

### 4.1 Typed predicates T01–T12

| IDs | Current test | Adjudication |
|---|---|---|
| T01–T12 | `pr14_typed_predicates` t01–t12 (12 executed) | PASS |

### 4.2 JSON J01–J13

| IDs | Current test | Adjudication |
|---|---|---|
| J01–J13 | `pr14_json` j01–j13 (13 executed) | PASS |
| J14 | Old-segment JSON fallback | No dedicated PR 14 test; historical PR 11 fallback suites only | **BLOCKED** |
| J15 | Legacy segments | No dedicated PR 14 test; covered indirectly by PR 11 legacy suites | **BLOCKED** |

### 4.3 Projection P01–P10

| ID | Historical obligation | Current test | Adjudication |
|---|---|---|---|
| P01–P07 | Source projection, order, five states, invalid rejection, budget, delete exclusion, lexical delegation | `pr14_projection` p01–p07 | PASS |
| P08 | Mixed predicates **fail closed** (STOP S1 negative) | Current `p08_mixed_predicates_execute` proves mixed execution | **SUPERSEDED WITH EVIDENCE** |
| P09 | Lexical explicit sort **fails closed** | Current `p09_lexical_explicit_sort_supported` proves support | **SUPERSEDED WITH EVIDENCE** |
| P10 | Pure typed delegation | `p10_pure_typed_delegation` | PASS |

### 4.4 Aggregation A01–A05

| IDs | Current test | Adjudication |
|---|---|---|
| A01–A05 | `pr14_aggregation` a01–a05 | PASS |

### 4.5 Batch B01–B10

| ID | Historical obligation | Current test | Adjudication |
|---|---|---|---|
| B01–B04 | Single slot, ordered mixed outcomes, empty envelope, too many queries | `pr14_batch` b01–b04 | PASS |
| B05 | Conflicting PIT | `b05_conflicting_pit` + `real::b06_b07` wrong handle | PASS |
| B06 | Shared budget not reset | Current `b06_work_is_not_hit_count`; shared-meter resets covered by `pr14_batch_memory` b12e/b12f/b11a | **SUPERSEDED WITH EVIDENCE** |
| B07 | Cancellation preserves cardinality | `b07_cancellation_preserves_cardinality`, `b10f`, `b13d` | PASS |
| B08 | Aggregation slot isolated | `b08_aggregation_slot_isolated`, `real::r08_r09_r15` | PASS |
| B09 | Cursor slot fails closed | Naked-batch negative `b09_cursor_slot_fails_closed` still PASS; pinned public cursor is now supported by 14A | **SUPERSEDED WITH EVIDENCE** (support added; fail-closed negative preserved for the naked entry) |
| B10 | Invalid aggregate kind | `b10_invalid_aggregate_kind`, `real::r08_r09_r15` | PASS |

### 4.6 Original uncovered matrices U, G, R, X

The original report listed `U01–U06`, `G01–G14`, `R01–R07`, `X01–X13` only as
families with no per-ID definitions recorded in the repository. Later
generations re-used these prefixes for different matrices (for example `G01–G05`
are geo sorts in `f1-hardening-test-traceability.md`, while `G01–G12` are
budget/cancellation rows in `corrective-test-traceability.md`).

| Family | Historical intent | Adjudication |
|---|---|---|
| U01–U06 | Mixed execution / mixed live universe | **SUPERSEDED WITH EVIDENCE** at family level by `pr14_unified_mixed` + `real::b02`; per-ID mapping unrecoverable |
| G01–G14 | Dedicated budget/cancellation matrix | **SUPERSEDED WITH EVIDENCE** at family level by `pr14_batch_memory` (B10a–B13j), `pr14_f1_hardening` W-series, `pr14_compound_aggregation` t13–t26; per-ID mapping unrecoverable |
| R01–R07 | RustFS cold/warm/fault/golden | **SUPERSEDED WITH EVIDENCE** by the P4/14B provider suites (§6, §7); original per-ID definitions unrecoverable |
| X01–X13 | Independent local/FakeObjectStore/real-RustFS oracles | **BLOCKED** — no per-ID definitions recorded; local and real-provider oracles exist (§3, §7), but an exact ID mapping cannot be asserted without inventing one |

## 5. Later-generation gates

### 5.1 P2B checkpoints A–F

| ID | Requirement | Current evidence | Adjudication |
|---|---|---|---|
| A | Disjoint work/memory/response sub-meters | `search::batch_meter` unit tests (workspace run) | PASS |
| B | `MemoryCharge`/`SlotMemoryScope` checked reserve/release | `search::memory` unit tests | PASS |
| C1 | Candidate local preflight/commit primitives | `search::execute::budget_tests::c1*` (workspace run) | PASS |
| C2 | Segment candidate ledger ephemeral sink | `c2_*` unit tests; `pr14_batch_memory` b10i/b10j | PASS |
| C3 | K+1 heap batch binding | `c3_*` unit tests; `pr14_batch_memory` b10g/b10h | PASS |
| D | Typed/geo/JSON scratch accounting | `pr14_batch_memory` b11a–b11e | PASS |
| E | Projection/response handoff | `pr14_batch_memory` b12a–b12f | PASS |
| F | B10a–B13j acceptance | `pr14_batch_memory` 31 tests (B10a–B13j symbols) | PASS |

### 5.2 Remaining P01–P12 (unified cursor)

| IDs | Current test | Adjudication |
|---|---|---|
| P01–P08, P10–P12 | `pr14_unified_cursor` 11 executed | PASS |
| P09 | `search::unified::tests::cursor_tuple_length_and_class_are_validated` (unit, workspace run) | PASS |

### 5.3 Corrective matrix (source `corrective-test-traceability.md`)

Note: this generation reuses `I01–I16` with different meanings than §3.

| ID (corrective) | Requirement | Current evidence | Adjudication |
|---|---|---|---|
| I01 | Mixed Boolean equivalence | `pr14_unified_mixed` m01–m14; `real::b02` | PASS |
| I03 | BM25 under lexical extraction | `m04/m08/m13`, `pr14_f1_hardening::s01/s02/s03/s05` | PASS |
| I05 | Full-tuple cursor | `pr14a_public_cursor` 26 tests | PASS |
| I07 | Exact `HitRef` projection identity | Projection tests assert states/order, not a published physical hit identity; no direct assertion found | **BLOCKED** |
| I09 | Cumulative work/memory | `pr14_batch_memory` b10a/b12e/b13b; `real::r10_r11` exact/one-under | PASS |
| I11 | Mixed aggregation | `pr14_compound_aggregation` t01–t26; `real::b02`/`r08_r09_r15` | PASS |
| I12 | Zero-GET instrumentation | Not instrumented | **BLOCKED** |
| I14 | RustFS oracle equivalence | `real::r02_r04_r06`, `real::b02`, `real::r08_r09_r15` | PASS |
| I16 | Final-SHA CI | Not observed | **BLOCKED** |

### 5.4 Final-design I1–I14 (source `final-design-test-traceability.md`)

| ID | Requirement | Current evidence | Adjudication |
|---|---|---|---|
| I1 | Mixed Boolean membership | `pr14_unified_mixed` m01–m14 | PASS |
| I2 | Effective-live only / delete | `m07`, `real::r05` | PASS |
| I3 | BM25 unchanged / positive only | `m04/m08/m13`, `s01–s05` | PASS |
| I4 | Exact total before top-K | `m12`, 14A `t05`, `pr14_batch` b01 | PASS |
| I5 | Total sort / gap-free cursor | 14A `t02–t05`, `j02/j07`, `real::b06_b07` | PASS |
| I6 | Cursor binding/expiry | 14A `t06/t07/t10`, `real::b06_b07` | PASS |
| I7 | Five field states | `pr14_projection::p03`, `pr14_batch::b11` | PASS |
| I8 | Exact physical hit identity | Mixed-path identity internal only; no public assertion | **BLOCKED** |
| I9 | Work charged at scan sites | `pr14_f1_hardening` w04/w04b/w06; `search::work` unit tests | PASS |
| I10 | Shared budgets never reset | `pr14_batch_memory` b12e/b12f, `real::r10_r11` | PASS |
| I11 | Policy/capability admission | `pr14_batch` b10/b13; `pr14_projection::p04` | PASS |
| I12 | Aggregate sees every match once | `pr14_compound_aggregation` t05/t07/t12/t13 | PASS |
| I13 | No query-time remote GET | Not instrumented | **BLOCKED** |
| I14 | No persisted format change | Frozen golden + PR 13 suites; docs-only 14C diff | PASS |

### 5.5 F1 hardening W/S/V/G/M/P

| Family | Current evidence | Adjudication |
|---|---|---|
| W01–W06 | `search::work` unit tests (7), `pr14_f1_hardening` w04/w04b/w06, `search::execute::budget_tests` | PASS |
| S01–S05 | `pr14_f1_hardening` s01/s02/s03/s05; S04 = `pr14_unified_mixed::m07` | PASS |
| V01–V05 | `pr14_f1_hardening` v01–v05 | PASS |
| G01–G05 | `pr14_f1_hardening` g01–g05 | PASS |
| M01–M06 | `pr14_f1_hardening` m01/m02/m04/m05/m06; M03 = `search::execute::budget_tests::production_global_bytes…` | PASS |
| P01–P05 | `pr14_projection::p01/p03/p06`, `real::b03` | PASS |

## 6. Phases 14A–14G

| Phase | Historical status | Current evidence | Adjudication |
|---|---|---|---|
| 14A unified compiler + mixed execution | PARTIAL (S1 STOP) | `pr14_unified_mixed`, `real::b02`, `pr14_f1_hardening` parity | PASS (superseded) |
| 14B typed/IP/CIDR completeness | DONE | `pr14_typed_predicates` 12 | PASS |
| 14C JSON range/membership/sort | DONE (legacy PARTIAL) | `pr14_json` 13, 14A J01–J12, `real::b03/b18` | PASS (legacy fallback J14/J15 remain BLOCKED) |
| 14D projections | DONE | `pr14_projection` 10 | PASS |
| 14E aggregation + serial batch | DONE (mixed/agg-in-batch fail closed) | `pr14_aggregation` 5, `pr14_compound_aggregation` 24, `pr14_batch` 12 | PASS (superseded) |
| 14F real-boundary RustFS + faults + benchmarks | NOT EXECUTED / BLOCKED | Real verticals + faults PASS (§7); fresh benchmarks not run | **BLOCKED** (benchmark component) |
| 14G final gates, CI, docs | PARTIAL (no final-SHA CI) | Local gates PASS; CI not observed; docs delivered | **BLOCKED** (CI component) |

## 7. P4 matrices

### 7.1 V01–V14 (source `p4-preimplementation-reconciliation.md`)

| ID | Mapped requirement | Evidence | Adjudication |
|---|---|---|---|
| V01, V02, V03, V06 | R01–R07 | Real verticals + local oracle | PASS |
| V04, V05 | R08–R11 | `real::r08_r09_r15`, `real::r10_r11` | PASS |
| V06, V09 | R12–R14 | `real::r12`, `real::r13_r14` (V06 is listed twice in the source; reproduced as recorded) | PASS |
| V07, V08, V10 | F01–F10 | `pr14_storage_faults` 9 cases × 10 iterations | PASS |
| V11, V12 | B01–B04 | Benchmark oracle + three qualified trials not run in 14C; validator self-test PASS | **BLOCKED** |
| V13 | No codec/manifest/format changes | PR 13/PR 11 golden suites; docs-only 14C diff | PASS |
| V14 | R15 cursor + aggregation fail-closed | Naked-batch `b09`; pinned path `real::r08_r09_r15` | PASS |

### 7.2 R01–R15 (provider storage verticals)

| ID | Test | Evidence | Adjudication |
|---|---|---|---|
| R01 | Separate-process cold bootstrap | `real::r01` PASS | PASS |
| R02, R04, R06 | Cold compound equivalence + aggregation | `real::r02_r04_r06` PASS | PASS |
| R03 | Wrong generation not substituted | `real::r03` PASS | PASS |
| R05 | Mutation; old pin unchanged; new generation | `real::r05` PASS | PASS |
| R07 | Local missing/null/empty/multivalue + geo/tie ordering | `r07_local_states_and_tie_order` (local engine; the P4 note already classified R07 as local) | PASS (local) |
| R08, R09 | Ordered batch, aggregation, prior success retained | `real::r08_r09_r15` PASS | PASS |
| R10, R11 | Remote exact/one-over memory/response budgets | `real::r10_r11` PASS | PASS |
| R12 | Empty-cache cold bootstrap, no writer state | `real::r12` PASS | PASS |
| R13, R14 | Warm reuse; pinned bytes not evicted; fail-closed tiny cache | `real::r13_r14` PASS | PASS |
| R15 | Public cursor + aggregation | `real::r08_r09_r15`, 14A `t05/t11` | PASS |

### 7.3 F01–F10 (provider faults; 10 iterations each)

| ID | Case | Adjudication |
|---|---|---|
| F01 | `f01_segment_get_transient_failure` | PASS |
| F02 | `f02_truncated_segment_transfer` | PASS |
| F03 | `f03_corrupt_content_range_rejected` | PASS |
| F04 | `f04_manifest_read_interrupted` | PASS |
| F05 | `f05_concurrent_old_reader_and_new_commit` | PASS |
| F06 | `f06_cancellation_during_transfer_is_bounded` | PASS |
| F07 | `f07_retry_exhaustion_is_bounded_and_recoverable` | PASS |
| F08 | `f08_crash_at_download_checkpoint` | PASS |
| F09, F10 | `f09_f10_batch_after_fault_and_s_f_s` | PASS |

### 7.4 B01–B04 (benchmark qualification)

| ID | Requirement | Evidence | Adjudication |
|---|---|---|---|
| B01 | Correctness oracle passes before timing | Historical P4 trials only (`ab9b2d7`, 138 commits behind); no fresh trial | **BLOCKED** |
| B02 | Validator rejects invalid/unqualified reports | `validate-pr14-p4.py --self-test` PASS in P1 | PASS |
| B03 | Three independently qualified trials | Not run (acceptance blocked; no operator idle attestation) | **BLOCKED** |
| B04 | Dirty/contended/unknown rejection | Wrapper refuses dirty tree / missing `--idle-confirmed` / non-`clear` contention (source + self-test) | PASS |

### 7.5 W01–W09

| ID | Requirement | Evidence | Adjudication |
|---|---|---|---|
| W01–W07, W09 | Measured lanes with correctness oracle | Historical `ab9b2d7` trials only | **BLOCKED** (fresh measurement required) |
| W08 | Forced eviction/reload | Approved Option 2 v0.1 snapshot-lifetime pinning exception; exemption manifest present and required by the validator | **NOT APPLICABLE (APPROVED)** |

### 7.6 Final-SHA CI Q-gates

The historical CI gates were labelled `Q01–Q06` (remaining) and `Q01–Q09`
(corrective). Both require a pushed PR and CI on the exact head.

| Family | Evidence | Adjudication |
|---|---|---|
| Q01–Q06 / Q01–Q09 | No PR/CI run exists; `gh` token invalid | **BLOCKED** |

## 8. Preauthorized mappings (plan §4 items 1–7)

| Item | Mapping applied | Result |
|---|---|---|
| 1. S1 | `UnifiedSearcher` + `pr14_unified_mixed` + `real::b02` | **SUPERSEDED WITH EVIDENCE** — verified, not left active |
| 2. S2 | Merged 14A `execute_batch_pinned` + `real::b06_b07` | **SUPERSEDED WITH EVIDENCE** — naked entry stays fail-closed |
| 3. Legacy JSON/projection/aggregation/typed sorting | `pr14_json`/`pr14_projection`/`pr14_aggregation`/`pr14_typed_predicates` + 14B `b18` | PASS; compatibility scope limited to JSON wire **v1** |
| 4. R01–R15 / F01–F10 | 14B evidence re-executed in P1 (§7) | PASS locally, provider pinned |
| 5. W08 | Approved Option 2 exception, `p4-w08-stop.md` + exemption manifest | **NOT APPLICABLE (APPROVED)**; not measured |
| 6. Benchmarks | Old P4 reports are provenance only; fresh trials required | **BLOCKED** |
| 7. JSON temp memory | B20/B21 characterization; human decision `REQUIRE SEPARATE CORRECTION` | **BLOCKED** (risk not accepted) |

## 9. Summary

| Adjudication | Count (table rows; a row grouping several IDs counts once) |
|---|---:|
| PASS | 96 |
| SUPERSEDED WITH EVIDENCE | 11 |
| NOT APPLICABLE (APPROVED) | 2 |
| BLOCKED | 18 |
| FAIL | 0 |
| **Total classified rows** | **127** |

Blocking rows: I13, J14, J15, corrective I07/I12/I16, final-design I8/I13,
phase 14F, phase 14G, V11/V12, B01, B03, W01–W07/W09, Q01–Q06/Q01–Q09,
X01–X13, plus the `R-14A-JSON-MEM` gate.

**Consequence:** PR 14 remains **BLOCKED / NOT ACCEPTED**. Even if all remaining
execution gaps were closed, the human `REQUIRE SEPARATE CORRECTION` decision
prevents acceptance until the correction lands and is qualified.

## 10. Reviewer sign-off

| Item | State |
|---|---|
| Crosswalk reviewed against raw evidence | **PENDING** (P7) |
| No production/format diff in PR 14C | Verified by agent diff audit; independent review PENDING |
| Historical artifacts preserved (no retroactive rewrite) | YES — additive supersession notes only |
| Accountable reviewer | PENDING |

## 11. Successor note (2026-10-26, PR 14E) — historical record only

> **This section is additive.** Everything above describes PR 14C at tested
> source `376023b53b557a30367097f29a41328c798188d4` and merge `2cb91be`; it is
> not rewritten and remains the historical record for that PR.
>
> PR 14E (`docs/pr-artifacts/pr-14e/`) reconciled these 127 rows against merged
> `main` `dc506f6` (including merged PR 14D `6d18ebe`, reviewed head `635c7f4`).
> Successor outcomes, with evidence and scope, are in
> [../pr-14e/acceptance-crosswalk.md](../pr-14e/acceptance-crosswalk.md):
>
> - 127 historical rows preserved; `PR14C:<section>:<literal>` composite keys.
> - Current dispositions: `PASS 100 / SUPERSEDED 11 / N/A 2 / BLOCKED 14 / FAIL 0`.
> - `BLOCKED → PASS` for `J14`, `J15`, corrective `I16` and the `Q` CI family,
>   each with named executed or immutable CI evidence.
> - 14 rows remain `BLOCKED`: zero query-time remote GET (3 rows), exact physical
>   hit identity (2 rows), phase `14F`/`14G`, all P4 benchmark rows, `X01–X13`
>   and the `R-14A-JSON-MEM` risk-closure row.
> - PR 14 is **still not accepted**; this note does not convert any PR 14C
>   conclusion into acceptance.
