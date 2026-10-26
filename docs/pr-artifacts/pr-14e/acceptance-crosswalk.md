# PR 14E — acceptance crosswalk (lossless 127-row reconciliation)

**Status: `RECONCILED — PR 14 NOT ACCEPTED`.** This document re-adjudicates the
historical PR 14 acceptance crosswalk against merged `main`
`dc506f6ee28014e64fbc9070db6925b73063d9ba` (including merged PR 14D
`6d18ebe` / reviewed head `635c7f4`). It is additive: the historical PR 14C
conclusions are **not** rewritten (see the dated successor note in
`docs/pr-artifacts/pr-14c/acceptance-reconciliation.md`).

PR 14 remains **IN PROGRESS / NOT ACCEPTED**, no original obligation is deleted,
no ID is renumbered, and no `BLOCKED` row is converted into a success by
inference.

## 1. Method and row unit

- **Historical source:** `docs/pr-artifacts/pr-14c/acceptance-reconciliation.md`
  at merge `2cb91be` (content produced against tested source `376023b`). That
  file is the canonical historical record; its generation identifiers are
  preserved verbatim below.
- **Row unit:** exactly the historical *published table row*, not the individual
  IDs inside a grouped row. `U01–U06`, `X01–X13`, `V11, V12`, `P01–P08,
  P10–P12`, `W01–W07, W09`, `Q01–Q06 / Q01–Q09` and the repeated `I01…I16` /
  `I1…I14` / `P01…P12` / `G01…G14` namespaces stay grouped exactly as published.
  Expanding a range would fabricate rows; decision X05 applies.
- **Composite key:** `{historical document, section, generation, literal ID}`.
  The same literal `I07`, `I13`, `I8`, `P01–P05`, `G01–G05`, `R01–R07`,
  `V01…V14`, `B01…B10`, `Q01–Q09` labels occur in different generations with
  different meanings (EAD-03/EAD-07, decision X06). Rows are keyed as
  `PR14C:<section>:<literal>` and are never joined by ID alone.
- **Count verification:** re-extraction produced **127** adjudicated rows with
  historical totals `PASS 96 / SUPERSEDED 11 / N/A 2 / BLOCKED 18 / FAIL 0`
  (decision X04 not triggered). Parsing note: the historical `§6` row
  "14C JSON range/membership/sort" carries the composite cell
  `PASS (legacy fallback J14/J15 remain BLOCKED)`; it counts as one `PASS` row
  (its trailing clause is an obligation note, not a second row). Without that
  rule a naive parser reports 95/19 — the published 96/18 is correct.
- **Execution vocabulary (`exec`):**
  - `RUN-14E` — the cited local test(s) were executed in this PR's validation
    run at current head `dc506f6` (see `validation-report.md`).
  - `REUSE-14D` — immutable real-RustFS evidence recorded by merged PR 14D at
    reviewed head `635c7f4`; **cited, not re-executed** in PR 14E (no provider
    was started).
  - `INSPECT-14E` — source/CI/artifact inspection performed in this PR.
  - `REUSE-14C` — immutable real-RustFS evidence recorded by PR 14C at
    `376023b`; cited, not re-executed.
  - `NONE` — no executed evidence; row remains `BLOCKED`.
- **Evidence SHA** is the immutable commit at which the cited evidence was
  produced. `dc506f6` = current reconciliation head; `635c7f4` = PR 14D
  reviewed/final head in `main`; `376023b` = PR 14C tested source.

## 2. Historical `§2` STOP conditions (5 rows)

Key prefix `PR14C:§2`.

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 001 | `S1` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Reusable lexical leaf/scorer seam; mixed lexical+typed execution | `pr14_unified_mixed` m01–m14 (14), `pr14a_public_cursor::j06`, `real::b02` | RUN-14E (+REUSE-14D for `real::b02`) | evidence complete |
| 002 | `S2` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Public cursor cannot represent sorted search-after | `acquire_batch_pinned`/`execute_batch_pinned` + `pr14a_public_cursor` (26), `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 003 | `S3` | PASS | **PASS** | JSON missing/null/mixed ordering deterministic | `pr14_json` j09/j10/j11, `pr14a_public_cursor` j01–j05 | RUN-14E | evidence complete |
| 004 | `S4` | PASS | **PASS** | Indexed-but-not-stored JSON operators (no format change) | `pr14_json::j06`, `b18_b19` | RUN-14E | evidence complete |
| 005 | `S5` | PASS | **PASS** | PR 2 missing/null/multivalue semantics | `pr14_typed_predicates` t01–t03, t10 | RUN-14E | evidence complete |

## 3. Original invariants `I01–I16` (16 rows, `pr-14/preimplementation-correctness-gate.md`)

Key prefix `PR14C:§3`. These are **not** the `§5.3` / `§5.4` invariant families.

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 006 | `I01` | PASS | **PASS** | Identical AST + snapshot ⇒ identical logical hit set | `pr14_unified_mixed` m01–m14; `real::b02`; 14A t02/j07 | RUN-14E (+REUSE-14D) | evidence complete |
| 007 | `I02` | PASS | **PASS** | No deleted/obsolete documents | `pr14_typed_predicates::t11_delete_and_pit`, `pr14_projection::p06`, `real::r05` | RUN-14E (+REUSE-14D) | evidence complete |
| 008 | `I03` | PASS | **PASS** | BM25 only from positive lexical leaves | `pr14_unified_mixed::m04/m08/m13`, `pr14_f1_hardening::s01/s02/s05` | RUN-14E | evidence complete |
| 009 | `I04` | PASS | **PASS** | Exact counts, gap-free pagination | 14A t02–t05/j02, `pr14_unified_cursor::p03`, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 010 | `I05` | PASS | **PASS** | Cursor binds snapshot/query/sort/tuple | 14A t06/t07/t10, `real::b06_b07` negatives | RUN-14E (+REUSE-14D) | evidence complete |
| 011 | `I06` | PASS | **PASS** | JSON scalar type and range boundaries | `pr14_json` j01–j05, j08; `real::b18` | RUN-14E (+REUSE-14D) | evidence complete |
| 012 | `I07` | PASS | **PASS** | JSON missing/null/multivalue sort deterministic | 14A j04/j05, `pr14_json::j09/j10`, `b03` | RUN-14E | evidence complete |
| 013 | `I08` | PASS | **PASS** | No unstored-field leak | `pr14_projection` p01–p06, 14A t05 | RUN-14E | evidence complete |
| 014 | `I09` | PASS | **PASS** | IP/CIDR family and missing/null truth tables | `pr14_typed_predicates` t01–t10 | RUN-14E | evidence complete |
| 015 | `I10` | PASS | **PASS** | Exact aggregates share the predicate | `pr14_aggregation` a01–a05, `pr14_compound_aggregation` t05/t07/t12, `real::r02_r04_r06` | RUN-14E (+REUSE-14D) | evidence complete |
| 016 | `I11` | PASS | **PASS** | Batch cardinality and shared budgets | `pr14_batch` b01–b13, `pr14_batch_memory` b10a–b13j, `real::r10_r11` | RUN-14E (+REUSE-14D) | evidence complete |
| 017 | `I12` | PASS | **PASS** | Bounded work/memory/output, cancellation | `pr14_batch_memory` b10f/b12d/b13d, `pr14_f1_hardening::w06`, 14A t13 | RUN-14E | evidence complete |
| 018 | `I13` | BLOCKED | **BLOCKED** | **Zero query-time remote GET** | Instrumentation exists (`TransferStats`, `FakeObjectStore::get_calls`); assertions exist only for the lexical query path (`pr13_remote::v01…`, `pr13_oracle::o07…O09`). No executed assertion at the PR 14 typed/mixed/batch/pinned boundary. | RUN-14E (partial) / NONE (gate) | separate instrumentation+test approval → dossier D-01 |
| 019 | `I14` | PASS | **PASS** | Persisted formats unchanged | `b18_b19` frozen golden; PR 13 regressions; docs-only PR 14E diff | RUN-14E | evidence complete |
| 020 | `I15` | PASS | **PASS** | Legacy segments correct or typed fail-closed | `pr11_json_corruption::t14…`, `legacy_json_tests`, `b18_b19` | RUN-14E | evidence complete |
| 021 | `I16` | PASS | **PASS** | Unsupported capabilities fail before expensive work | `pr14_projection::p04`, `pr14_batch::b04/b10/b13`, `pr14_f1_hardening::v01–v05` | RUN-14E | evidence complete |

## 4. Per-domain matrices `§4` (20 rows)

### 4.1 Typed predicates `T01–T12` (1 row, key `PR14C:§4.1`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 022 | `T01–T12` | PASS | **PASS** | Typed IPv4/IPv6/CIDR predicates and truth tables | `pr14_typed_predicates` t01–t12 (12) | RUN-14E | evidence complete |

### 4.2 JSON `J01–J13`, `J14`, `J15` (3 rows, key `PR14C:§4.2`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 023 | `J01–J13` | PASS | **PASS** | JSON range/membership/sort/table semantics | `pr14_json` j01–j13 (13) | RUN-14E | evidence complete |
| 024 | `J14` | BLOCKED | **PASS** | Old-segment JSON fallback: a segment without the JSON-path section must evaluate by bounded, exact stored source, and fail typed when the field is not stored | `search::typed::legacy_json_tests::legacy_source_fallback_and_unstored_error` (section-stripped segment; `access.paths.is_none()`; matching and non-matching source fallback; `SearchError::UnsupportedOperator` for indexed-not-stored), `…::b1_legacy_source_fallback_wide_field` (2,000-member fallback) | RUN-14E | evidence complete; scope: unit-level production accessor, not an end-to-end `UnifiedSearcher` legacy query — see dossier D-02 |
| 025 | `J15` | BLOCKED | **PASS** | Legacy JSON segments: genuine historical artifact still decodes, reproduces byte-identically, and corrupt/unsupported bytes are rejected typed | `pr14_storage_vertical::b18_b19_historical_json_segment_compatibility` (frozen PR 11 artifact `65f7440`, SHA-256 `0528a62c…a02f`, writer reproduces byte-identical segment, corruption → `Err`, major 2 → `UnsupportedFormatVersion`), `pr11_json_corruption::t14_negotiation_and_corruption_fail_closed` (legacy neither-feature-nor-section opens cleanly), `pr14d_json_sort_memory::d07_historical_fixture_digest_and_corruption` | RUN-14E | evidence complete; see dossier D-03 |

### 4.3 Projection `P01–P10` (4 rows, key `PR14C:§4.3`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 026 | `P01–P07` | PASS | **PASS** | Source projection, order, five states, invalid rejection, budget, delete exclusion, lexical delegation | `pr14_projection` p01–p07 | RUN-14E | evidence complete |
| 027 | `P08` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Historical fail-closed negative superseded by mixed execution | `pr14_projection::p08_mixed_predicates_execute` | RUN-14E | evidence complete |
| 028 | `P09` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Historical lexical explicit-sort fail-closed superseded by support | `pr14_projection::p09_lexical_explicit_sort_supported` | RUN-14E | evidence complete |
| 029 | `P10` | PASS | **PASS** | Pure typed delegation | `pr14_projection::p10_pure_typed_delegation` | RUN-14E | evidence complete |

### 4.4 Aggregation `A01–A05` (1 row, key `PR14C:§4.4`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 030 | `A01–A05` | PASS | **PASS** | Exact aggregation over matched live set | `pr14_aggregation` a01–a05 | RUN-14E | evidence complete |

### 4.5 Batch `B01–B10` (7 rows, key `PR14C:§4.5`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 031 | `B01–B04` | PASS | **PASS** | Single slot, ordered mixed outcomes, empty envelope, too many queries | `pr14_batch` b01–b04 | RUN-14E | evidence complete |
| 032 | `B05` | PASS | **PASS** | Conflicting PIT | `pr14_batch::b05_conflicting_pit`, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 033 | `B06` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Shared budget not reset | `pr14_batch::b06_work_is_not_hit_count`, `pr14_batch_memory` b12e/b12f/b11a | RUN-14E | evidence complete |
| 034 | `B07` | PASS | **PASS** | Cancellation preserves cardinality | `b07_cancellation_preserves_cardinality`, b10f, b13d | RUN-14E | evidence complete |
| 035 | `B08` | PASS | **PASS** | Aggregation slot isolated | `b08_aggregation_slot_isolated`, `real::r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |
| 036 | `B09` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Cursor slot fails closed on the naked entry; pinned path supported by 14A | `b09_cursor_slot_fails_closed`, `pr14a_public_cursor` (26) | RUN-14E | evidence complete |
| 037 | `B10` | PASS | **PASS** | Invalid aggregate kind | `b10_invalid_aggregate_kind`, `real::r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |

### 4.6 Original uncovered matrices `U/G/R/X` (4 rows, key `PR14C:§4.6`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 038 | `U01–U06` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Mixed execution / mixed live universe (family level; per-ID definitions unavailable) | `pr14_unified_mixed` (14), `real::b02` | RUN-14E (+REUSE-14D) | evidence complete |
| 039 | `G01–G14` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Dedicated budget/cancellation matrix (family level) | `pr14_batch_memory` (31), `pr14_f1_hardening` W-series, `pr14_compound_aggregation` t13–t26 | RUN-14E | evidence complete |
| 040 | `R01–R07` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | RustFS cold/warm/fault/golden (family level) | §7.2 provider verticals, PR 14D vertical/fault suites | REUSE-14D | evidence complete |
| 041 | `X01–X13` | BLOCKED | **BLOCKED** | Independent local/FakeObjectStore/real-RustFS oracles per-ID | Repository search found no per-ID definitions: `pr-14/test-traceability.md:63` records only the family sentence; `corrective-test-traceability.md` reuses `X01` under corrective `I01` and `X01–X10` under corrective `I14`; git history (`fa82db7`, `d0c445a`, `e0e1dcb`) contains no definition table | INSPECT-14E | maintainer decision → dossier D-16 |

## 5. Later-generation gates `§5` (39 rows)

### 5.1 P2B checkpoints A–F (8 rows, key `PR14C:§5.1`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 042 | `A` | PASS | **PASS** | Disjoint work/memory/response sub-meters | `search::batch_meter` unit tests | RUN-14E | evidence complete |
| 043 | `B` | PASS | **PASS** | `MemoryCharge`/`SlotMemoryScope` checked reserve/release | `search::memory` unit tests | RUN-14E | evidence complete |
| 044 | `C1` | PASS | **PASS** | Candidate local preflight/commit primitives | `search::execute::budget_tests::c1*` | RUN-14E | evidence complete |
| 045 | `C2` | PASS | **PASS** | Segment candidate ledger ephemeral sink | `c2_*` units, `pr14_batch_memory` b10i/b10j | RUN-14E | evidence complete |
| 046 | `C3` | PASS | **PASS** | K+1 heap batch binding | `c3_*` units, `pr14_batch_memory` b10g/b10h | RUN-14E | evidence complete |
| 047 | `D` | PASS | **PASS** | Typed/geo/JSON scratch accounting | `pr14_batch_memory` b11a–b11e | RUN-14E | evidence complete |
| 048 | `E` | PASS | **PASS** | Projection/response handoff | `pr14_batch_memory` b12a–b12f | RUN-14E | evidence complete |
| 049 | `F` | PASS | **PASS** | B10a–B13j acceptance | `pr14_batch_memory` (31) | RUN-14E | evidence complete |

### 5.2 Remaining unified cursor `P01–P12` (2 rows, key `PR14C:§5.2`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 050 | `P01–P08, P10–P12` | PASS | **PASS** | Unified cursor tuple/resume semantics | `pr14_unified_cursor` (11) | RUN-14E | evidence complete |
| 051 | `P09` | PASS | **PASS** | Cursor tuple length/class validation | `search::unified::tests::cursor_tuple_length_and_class_are_validated` | RUN-14E | evidence complete |

### 5.3 Corrective matrix (9 rows, key `PR14C:§5.3`)

Note: this generation reuses `I01–I16` with **different meanings** than §3.

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 052 | `I01` | PASS | **PASS** | Mixed Boolean equivalence | `pr14_unified_mixed` m01–m14, `real::b02` | RUN-14E (+REUSE-14D) | evidence complete |
| 053 | `I03` | PASS | **PASS** | BM25 under lexical extraction | m04/m08/m13, `pr14_f1_hardening` s01/s02/s03/s05 | RUN-14E | evidence complete |
| 054 | `I05` | PASS | **PASS** | Full-tuple public cursor | `pr14a_public_cursor` (26) | RUN-14E | evidence complete |
| 055 | `I07` | BLOCKED | **BLOCKED** | **Exact `HitRef` projection identity** | Implementation now projects by physical `(segment_index, doc_id)` and guards key mismatch (`search/unified.rs`, `project_selected_hits`); no executed test asserts selected-physical → projected identity. `pr14_f1_hardening::p02_projection_uses_current_version` proves current-version output only. | INSPECT-14E / NONE (gate) | separate test-only approval → dossier D-04 |
| 056 | `I09` | PASS | **PASS** | Cumulative work/memory | `pr14_batch_memory` b10a/b12e/b13b, `real::r10_r11` | RUN-14E (+REUSE-14D) | evidence complete |
| 057 | `I11` | PASS | **PASS** | Mixed aggregation | `pr14_compound_aggregation` t01–t26, `real::b02`/`r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |
| 058 | `I12` | BLOCKED | **BLOCKED** | **Zero-GET instrumentation** | Same boundary gap as CW-018/CW-064; counters exist, PR 14 query paths never asserted | RUN-14E (partial) / NONE (gate) | separate instrumentation+test approval → dossier D-05 |
| 059 | `I14` | PASS | **PASS** | RustFS oracle equivalence | `real::r02_r04_r06`, `real::b02`, `real::r08_r09_r15` | REUSE-14D | evidence complete |
| 060 | `I16` | BLOCKED | **PASS** | Final-SHA CI | Exact-head check runs green at every pushed PR of the PR 14 line: `a61f0b8` (PR #62 head), `635c7f4` (PR #64 head), `dc506f6` (main head) — `rust`, `msrv`, `rustfs` all `completed/success`. The never-pushed local corrective commits (`e0e1dcb`, `d0c445a`) have **0** check runs and are **not** claimed. | INSPECT-14E | evidence complete; scope in dossier D-06 |

### 5.4 Final-design matrix `I1–I14` (14 rows, key `PR14C:§5.4`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 061 | `I1` | PASS | **PASS** | Mixed Boolean membership | `pr14_unified_mixed` m01–m14 | RUN-14E | evidence complete |
| 062 | `I2` | PASS | **PASS** | Effective-live only / delete | m07, `real::r05` | RUN-14E (+REUSE-14D) | evidence complete |
| 063 | `I3` | PASS | **PASS** | BM25 unchanged / positive only | m04/m08/m13, s01–s05 | RUN-14E | evidence complete |
| 064 | `I4` | PASS | **PASS** | Exact total before top-K | m12, 14A t05, `pr14_batch::b01` | RUN-14E | evidence complete |
| 065 | `I5` | PASS | **PASS** | Total sort / gap-free cursor | 14A t02–t05, j02/j07, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 066 | `I6` | PASS | **PASS** | Cursor binding/expiry | 14A t06/t07/t10, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 067 | `I7` | PASS | **PASS** | Five field states | `pr14_projection::p03`, `pr14_batch::b11` | RUN-14E | evidence complete |
| 068 | `I8` | BLOCKED | **BLOCKED** | **Exact physical hit identity** | Internal physical identity only (`SelectedHit{segment_index,doc_id}` + `project_selected_hits`); no assertion ties the selected physical hit to the projected fields across duplicate keys/upsert/PIT. No public `HitRef` exists. | INSPECT-14E / NONE (gate) | separate test-only approval → dossier D-07 |
| 069 | `I9` | PASS | **PASS** | Work charged at scan sites | `pr14_f1_hardening` w04/w04b/w06, `search::work` units | RUN-14E | evidence complete |
| 070 | `I10` | PASS | **PASS** | Shared budgets never reset | `pr14_batch_memory` b12e/b12f, `real::r10_r11` | RUN-14E (+REUSE-14D) | evidence complete |
| 071 | `I11` | PASS | **PASS** | Policy/capability admission | `pr14_batch` b10/b13, `pr14_projection::p04` | RUN-14E | evidence complete |
| 072 | `I12` | PASS | **PASS** | Aggregate sees every match once | `pr14_compound_aggregation` t05/t07/t12/t13 | RUN-14E | evidence complete |
| 073 | `I13` | BLOCKED | **BLOCKED** | **No query-time remote GET** | Same boundary gap as CW-018/CW-058 | RUN-14E (partial) / NONE (gate) | separate instrumentation+test approval → dossier D-08 |
| 074 | `I14` | PASS | **PASS** | No persisted format change | frozen golden + PR 13 suites; docs-only PR 14E diff | RUN-14E | evidence complete |

### 5.5 F1 hardening `W/S/V/G/M/P` (6 rows, key `PR14C:§5.5`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 075 | `W01–W06` | PASS | **PASS** | Work accounting at scan/rejected-charge sites | `search::work` units (7), `pr14_f1_hardening` w04/w04b/w06, `budget_tests` | RUN-14E | evidence complete |
| 076 | `S01–S05` | PASS | **PASS** | Scorer/stat parity under extraction | `pr14_f1_hardening` s01/s02/s03/s05; S04 = `pr14_unified_mixed::m07` | RUN-14E | evidence complete |
| 077 | `V01–V05` | PASS | **PASS** | Validation/fail-closed cases | `pr14_f1_hardening` v01–v05 | RUN-14E | evidence complete |
| 078 | `G01–G05` | PASS | **PASS** | Geo sort family (this generation) | `pr14_f1_hardening` g01–g05 | RUN-14E | evidence complete |
| 079 | `M01–M06` | PASS | **PASS** | Memory-bound family | `pr14_f1_hardening` m01/m02/m04/m05/m06; M03 = `budget_tests::production_global_bytes…` | RUN-14E | evidence complete |
| 080 | `P01–P05` | PASS | **PASS** | Projection family | `pr14_projection` p01/p03/p06, `real::b03` | RUN-14E (+REUSE-14D) | evidence complete |

## 6. Phases `14A–14G` (7 rows, key `PR14C:§6`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 081 | `14A unified compiler + mixed execution` | PASS | **PASS** | Mixed execution and unified compiler | `pr14_unified_mixed`, `real::b02`, F1 parity | RUN-14E (+REUSE-14D) | evidence complete |
| 082 | `14B typed/IP/CIDR completeness` | PASS | **PASS** | Typed predicate completeness | `pr14_typed_predicates` (12) | RUN-14E | evidence complete |
| 083 | `14C JSON range/membership/sort` | PASS (note: legacy fallback J14/J15 remain BLOCKED) | **PASS** | JSON query surface; historical row counted as one PASS row | `pr14_json` (13), 14A J01–J12, `real::b03/b18` | RUN-14E (+REUSE-14D) | evidence complete; the J14/J15 note is now closed by CW-024/CW-025 |
| 084 | `14D projections` | PASS | **PASS** | Stored projections | `pr14_projection` (10) | RUN-14E | evidence complete |
| 085 | `14E aggregation + serial batch` | PASS | **PASS** | Aggregation and serial batch | `pr14_aggregation` (5), `pr14_compound_aggregation` (24), `pr14_batch` (12) | RUN-14E | evidence complete |
| 086 | `14F real-boundary RustFS + faults + benchmarks` | BLOCKED | **BLOCKED** | Real boundary + faults + **benchmarks** | Verticals/faults exist as immutable evidence (`REUSE-14D`); three qualified trials absent | INSPECT-14E / NONE (benchmarks) | PR 14F → dossier D-09 |
| 087 | `14G final gates, CI, docs` | BLOCKED | **BLOCKED** | Final gates + CI + docs | CI component now verified (CW-060); benchmarks (CW-086/D-09…D-14), risk signoff (D-18) and PR 14 acceptance remain open | INSPECT-14E | PR 14F + maintainer → dossier D-10 |

## 7. P4 matrices `§7` (33 rows)

### 7.1 `V01–V14` (7 rows, key `PR14C:§7.1`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 088 | `V01, V02, V03, V06` | PASS | **PASS** | R01–R07 provider verticals | `real::r01…`, `real::r02_r04_r06…`, cold-bootstrap suite | REUSE-14D | evidence complete |
| 089 | `V04, V05` | PASS | **PASS** | R08–R11 batch/budget verticals | `real::r08_r09_r15`, `real::r10_r11` | REUSE-14D | evidence complete |
| 090 | `V06, V09` | PASS | **PASS** | R12–R14 cold-cache/pin/eviction (the source lists V06 twice; reproduced as recorded) | `real::r12`, `real::r13_r14` | REUSE-14D | evidence complete |
| 091 | `V07, V08, V10` | PASS | **PASS** | F01–F10 provider faults | `pr14_storage_faults` 9 cases × 10 iterations | REUSE-14D | evidence complete |
| 092 | `V11, V12` | BLOCKED | **BLOCKED** | Benchmark oracle + three qualified trials | 0 of 3 qualified trials; historical `ab9b2d7` is provenance only | NONE | PR 14F → dossier D-11 |
| 093 | `V13` | PASS | **PASS** | No codec/manifest/format changes | PR 13/PR 11 golden suites; docs-only PR 14E diff | RUN-14E | evidence complete |
| 094 | `V14` | PASS | **PASS** | R15 cursor + aggregation fail-closed | naked-batch `b09`; pinned `real::r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |

### 7.2 `R01–R15` provider storage verticals (10 rows, key `PR14C:§7.2`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 095 | `R01` | PASS | **PASS** | Separate-process cold bootstrap | `real::r01` | REUSE-14D | evidence complete |
| 096 | `R02, R04, R06` | PASS | **PASS** | Cold compound equivalence + aggregation | `real::r02_r04_r06` | REUSE-14D | evidence complete |
| 097 | `R03` | PASS | **PASS** | Wrong generation not substituted | `real::r03` | REUSE-14D | evidence complete |
| 098 | `R05` | PASS | **PASS** | Mutation; old pin unchanged; new generation | `real::r05` | REUSE-14D | evidence complete |
| 099 | `R07` | PASS | **PASS** | Local missing/null/empty/multivalue + geo/tie ordering | `r07_local_states_and_tie_order` (local engine, as classified in P4) | RUN-14E | evidence complete |
| 100 | `R08, R09` | PASS | **PASS** | Ordered batch, aggregation, prior success retained | `real::r08_r09_r15` | REUSE-14D | evidence complete |
| 101 | `R10, R11` | PASS | **PASS** | Remote exact/one-over memory/response budgets | `real::r10_r11` | REUSE-14D | evidence complete |
| 102 | `R12` | PASS | **PASS** | Empty-cache cold bootstrap, no writer state | `real::r12` | REUSE-14D | evidence complete |
| 103 | `R13, R14` | PASS | **PASS** | Warm reuse; pinned bytes not evicted; fail-closed tiny cache | `real::r13_r14` | REUSE-14D | evidence complete |
| 104 | `R15` | PASS | **PASS** | Public cursor + aggregation | `real::r08_r09_r15`, 14A t05/t11 | REUSE-14D | evidence complete |

### 7.3 `F01–F10` provider faults (9 rows, key `PR14C:§7.3`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 105 | `F01` | PASS | **PASS** | Segment GET transient failure | `f01_segment_get_transient_failure` ×10 | REUSE-14D | evidence complete |
| 106 | `F02` | PASS | **PASS** | Truncated segment transfer | `f02_truncated_segment_transfer` ×10 | REUSE-14D | evidence complete |
| 107 | `F03` | PASS | **PASS** | Corrupt content-range rejected | `f03_corrupt_content_range_rejected` ×10 | REUSE-14D | evidence complete |
| 108 | `F04` | PASS | **PASS** | Manifest read interrupted | `f04_manifest_read_interrupted` ×10 | REUSE-14D | evidence complete |
| 109 | `F05` | PASS | **PASS** | Concurrent old reader + new commit | `f05_concurrent_old_reader_and_new_commit` ×10 | REUSE-14D | evidence complete |
| 110 | `F06` | PASS | **PASS** | Cancellation during transfer bounded | `f06_cancellation_during_transfer_is_bounded` ×10 | REUSE-14D | evidence complete |
| 111 | `F07` | PASS | **PASS** | Retry exhaustion bounded and recoverable | `f07_retry_exhaustion_is_bounded_and_recoverable` ×10 | REUSE-14D | evidence complete |
| 112 | `F08` | PASS | **PASS** | Crash at download checkpoint | `f08_crash_at_download_checkpoint` ×10 (SIGKILL child) | REUSE-14D | evidence complete |
| 113 | `F09, F10` | PASS | **PASS** | Batch after fault and S/F/S | `f09_f10_batch_after_fault_and_s_f_s` ×10 | REUSE-14D | evidence complete |

### 7.4 Benchmark qualification `B01–B04` (4 rows, key `PR14C:§7.4`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 114 | `B01` | BLOCKED | **BLOCKED** | Correctness oracle passes before timing | No fresh trial; historical `ab9b2d7` trials are provenance only | NONE | PR 14F → dossier D-12 |
| 115 | `B02` | PASS | **PASS** | Validator rejects invalid/unqualified reports | `validate-pr14-p4.py --self-test` | RUN-14E | evidence complete |
| 116 | `B03` | BLOCKED | **BLOCKED** | Three independently qualified trials | 0 of 3; no operator idle attestation | NONE | PR 14F → dossier D-13 |
| 117 | `B04` | PASS | **PASS** | Dirty/contended/unknown rejection | wrapper source + validator self-test | RUN-14E | evidence complete |

### 7.5 `W01–W09` workload lanes (2 rows, key `PR14C:§7.5`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 118 | `W01–W07, W09` | BLOCKED | **BLOCKED** | Measured lanes with correctness oracle | Historical `ab9b2d7` trials only; no fresh measurement | NONE | PR 14F → dossier D-14 |
| 119 | `W08` | N/A (APPROVED) | **NOT APPLICABLE (APPROVED)** | Forced eviction/reload lane | Approved Option 2 v0.1 snapshot-lifetime pinning exception: `docs/pr-artifacts/pr-14/p4-w08-stop.md`, `benchmarks/reports/pr14-p4-w08-exemption.json`, required by the validator | RUN-14E | evidence complete — **never measured** |

### 7.6 Final-SHA CI `Q`-gates (1 row, key `PR14C:§7.6`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 120 | `Q01–Q06 / Q01–Q09` | BLOCKED | **PASS** | Pushed PR + CI on the exact head (family-level CI gate) | Exact-head check runs, all `completed/success` for `rust`, `msrv`, `rustfs`: `6cb6d47` (#61), `a61f0b8` (#62), `4097a02` (#63), `635c7f4` (#64), `b66f817` (#65), merge/main heads `2cb91be`, `6d18ebe`, `dc506f6`. Per-ID `Q` check definitions are not recorded in the repository; adjudicated at family level exactly as the historical row was recorded. | INSPECT-14E | evidence complete; scope in dossier D-15 |

## 8. Preauthorized mapping table `§8` (7 rows, key `PR14C:§8`)

| CW | literal_id | hist | cur | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|
| 121 | `1. S1` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Mapping 1 verifies mixed execution | `pr14_unified_mixed`, `real::b02` | RUN-14E (+REUSE-14D) | evidence complete |
| 122 | `2. S2` | SUPERSEDED | **SUPERSEDED WITH EVIDENCE** | Mapping 2 verifies pinned cursor support; naked entry fails closed | `pr14a_public_cursor`, `real::b06_b07`, `b09` | RUN-14E (+REUSE-14D) | evidence complete |
| 123 | `3. Legacy JSON/projection/aggregation/typed sorting` | PASS | **PASS** | Legacy JSON/projection/aggregation/typed sorting compatibility (JSON wire v1) | `pr14_json`/`pr14_projection`/`pr14_aggregation`/`pr14_typed_predicates`, `real::b18` | RUN-14E (+REUSE-14D) | evidence complete |
| 124 | `4. R01–R15 / F01–F10` | PASS | **PASS** | Provider verticals and faults | PR 14B evidence re-executed in PR 14C; re-cited (not re-executed) in 14E | REUSE-14D | evidence complete |
| 125 | `5. W08` | N/A (APPROVED) | **NOT APPLICABLE (APPROVED)** | Approved W08 exception | exemption manifest + validator | RUN-14E | evidence complete — never measured |
| 126 | `6. Benchmarks` | BLOCKED | **BLOCKED** | Fresh trials required; old reports provenance only | 0 of 3 | NONE | PR 14F → dossier D-17 |
| 127 | `7. JSON temp memory` | BLOCKED | **BLOCKED** | `R-14A-JSON-MEM`: correction **and** human risk closure | Correction implemented `d0e1bbb`, merged via #64 (`6d18ebe`), reviewed head `635c7f4` CI-verified; B20/B21 re-characterized (387 / 45,726 / 1,462,302 B); **human risk-closure acceptance not recorded** | REUSE-14D / INSPECT-14E | maintainer risk signoff → dossier D-18 |

## 9. Recomputed totals and transition matrix

| New adjudication | Count |
|---|---:|
| PASS | 100 |
| SUPERSEDED WITH EVIDENCE | 11 |
| NOT APPLICABLE (APPROVED) | 2 |
| BLOCKED | 14 |
| FAIL | 0 |
| **Total** | **127** |

Transition matrix (historical × current):

| Historical ↓ / Current → | PASS | SUPERSEDED | N/A | BLOCKED | FAIL | Total |
|---|---:|---:|---:|---:|---:|---:|
| PASS | 96 | 0 | 0 | 0 | 0 | 96 |
| SUPERSEDED | 0 | 11 | 0 | 0 | 0 | 11 |
| N/A (APPROVED) | 0 | 0 | 2 | 0 | 0 | 2 |
| BLOCKED | 4 | 0 | 0 | 14 | 0 | 18 |
| FAIL | 0 | 0 | 0 | 0 | 0 | 0 |
| **Total** | **100** | **11** | **2** | **14** | **0** | **127** |

`BLOCKED → PASS` transitions (all require named executed/immutable proof):

| CW | literal_id | proof |
|---|---|---|
| 024 | `J14` | `legacy_source_fallback_and_unstored_error`, `b1_legacy_source_fallback_wide_field` (RUN-14E) |
| 025 | `J15` | `b18_b19_historical_json_segment_compatibility`, `pr11_json_corruption::t14…`, `d07_historical_fixture_digest_and_corruption` (RUN-14E) |
| 060 | `I16` (corrective) | Exact-head CI `a61f0b8`/`635c7f4`/`dc506f6`, all 3 jobs success (INSPECT-14E) |
| 120 | `Q01–Q06 / Q01–Q09` | Exact-head CI on 5 pushed PR heads + 3 merge/main heads (INSPECT-14E) |

No row moved to `NOT APPLICABLE` in PR 14E (decision X20 not triggered; the only
two N/A rows are the pre-existing approved `W08` exception).

## 10. Remaining blockers by owner

| Owner | Blocked rows |
|---|---|
| PR 14F (fresh qualified benchmarks) | CW-086, CW-087 (benchmark component), CW-092, CW-114, CW-116, CW-118, CW-126 |
| Separate instrumentation/test approval (zero-GET) | CW-018, CW-058, CW-073 |
| Separate test-only approval (physical hit identity) | CW-055, CW-068 |
| Maintainer decision (historical per-ID `X` definitions) | CW-041 |
| Maintainer risk-closure acceptance (`R-14A-JSON-MEM`) | CW-127 |
| PR 14 acceptance (all of the above + review) | all remaining `BLOCKED` rows |

## 11. What this crosswalk does not claim

- It does **not** mark PR 14 DONE, accepted, or v0.1 released.
- It does **not** claim a zero-GET property for PR 14 query paths, or a physical
  hit-identity guarantee.
- It does **not** claim fresh real-RustFS execution in PR 14E, or fresh
  benchmarks; `REUSE-14D` rows carry PR 14D's immutable evidence only.
- It does **not** invent per-ID definitions for `X01–X13`.
- It does **not** rewrite any historical PR 14C conclusion.

## 12. Row-schema mapping (plan §11 fields)

Every row above carries the required minimum fields; the compact table layout
maps them as follows so each row stays machine-checkable without a custom parser.

| Required field | Representation in this document |
|---|---|
| `historical_source` | `docs/pr-artifacts/pr-14c/acceptance-reconciliation.md` at merge `2cb91be19652379b435c49a5fa4aea2ed7502de5` (produced against tested source `376023b`) |
| `generation` | The `Key prefix` / section header of each table (`§2`, `§3`, `§4.1`…`§8`); the literal generation is the section, because the ID namespaces are reused |
| `section` | Same as `generation` for the published crosswalk; original upstream section names are quoted in each table heading |
| `literal_id` | Column 2 (`literal_id`), preserved verbatim (`U01–U06`, `V11, V12`, `P01–P08, P10–P12`, `Q01–Q06 / Q01–Q09`) |
| `historical_disposition` | Column 3 (`hist`), verbatim including the composite `§6` cell |
| `current_disposition` | Column 4 (`cur`), one of the five permitted adjudications |
| `invariant` | Column 5 (`obligation`) |
| `current_head_sha` | `dc506f6ee28014e64fbc9070db6925b73063d9ba` for all rows (single reconciliation head; stated in the header) |
| `evidence_ref` | Column 6 (`evidence_ref`) |
| `evidence_sha` | Derived from column 7 (`exec`) by the table below, or the exact SHA named in the evidence cell |
| `test_or_inspection` | Column 6 names the test symbol, suite, CI record or inspection |
| `execution_status` | Column 7 (`exec`) |
| `rationale` | For changed rows: §9 transition table + the dossier named in column 8. For unchanged rows: the historical rationale stands and the evidence was re-executed or re-cited |
| `owner` | Column 8 (`owner → next gate`) |
| `next_gate` | Column 8, after the arrow |

`exec` → `evidence_sha`:

| `exec` | `evidence_sha` |
|---|---|
| `RUN-14E` | `dc506f6ee28014e64fbc9070db6925b73063d9ba` (this PR's execution) |
| `REUSE-14D` | `635c7f4a89c5e2e9478da23c2a533e8dc1f80e09` (PR 14D reviewed head; merged as `6d18ebe`) |
| `REUSE-14C` | `376023b53b557a30367097f29a41328c798188d4` (PR 14C tested source) |
| `INSPECT-14E` | `dc506f6` for repository state; the immutable CI SHA named in the evidence cell for check records |
