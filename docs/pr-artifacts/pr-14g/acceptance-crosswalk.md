# PR 14G — 127-row acceptance crosswalk (additive post-14F successor)

**Status: `RECONCILED — PR 14 NOT ACCEPTED`.** This document is an **additive**
successor to `docs/pr-artifacts/pr-14e/acceptance-crosswalk.md` (baseline
`dc506f6ee28014e64fbc9070db6925b73063d9ba`) and incorporates the merged PR 14F
qualification (PR #67, merge `054ca55d143e89a092cc6519231b820fecfa42dc`) plus the
executed PR 14G Phase A and Phase B evidence.

It **rewrites no earlier crosswalk**: every historical PR 14C/14E literal ID, row
unit and row count is preserved verbatim; the 14E column is carried unchanged and a
separate `14G` column records only the rows whose disposition advanced with new,
named evidence. PR 14 remains **IN PROGRESS / NOT ACCEPTED**; v0.1 is **NOT
RELEASED**.

## 1. Baselines, row unit and composite keys

| Item | Value |
|---|---|
| Historical source | `docs/pr-artifacts/pr-14c/acceptance-reconciliation.md` at merge `2cb91be` |
| 14E reconciliation | `docs/pr-artifacts/pr-14e/acceptance-crosswalk.md`, head `dc506f6…` |
| PR 14F qualification | merged PR #67: source `d12a97537a5131953c948c3a90065a73c3d24b40`, evidence head `cc8153e593bc403d169da291a95a5ad18c6b0293`, merge `054ca55d143e89a092cc6519231b820fecfa42dc` |
| PR 14G Phase A | commit `e4d7237` (CW-018, CW-058, CW-073) |
| PR 14G Phase B | commit `d1ee42b` (CW-055, CW-068) |
| PR #69 | **unmerged** at execution (`origin/docs/pr14-post-14f-reconciliation` tip `75fc489`, not an ancestor of `origin/main`); cited only as an unmerged corroborating proposal |

**Row unit:** exactly the historical *published table row*, never the individual IDs
inside a grouped row. `U01–U06`, `X01–X13`, `V11, V12`, `P01–P08, P10–P12`,
`W01–W07, W09`, `Q01–Q06 / Q01–Q09` and the reused `I01…I16` / `I1…I14` /
`P01…P12` / `G01…G14` namespaces stay grouped exactly as published. No row is added,
split, removed or renumbered.

**Composite key:** `PR14C:<section>:<literal_id>` (section = historical generation).
The same literal label occurs in different generations with different meanings, so
rows are never joined by literal ID alone.

## 2. Mechanical count verification

The 14E tables were re-parsed mechanically (this exact script was executed from the
repository root):

```python
import re
from collections import Counter
src = open("docs/pr-artifacts/pr-14e/acceptance-crosswalk.md").read().splitlines()
key, rows = None, []
for line in src:
    m = re.search(r"[Kk]ey (?:prefix )?`(PR14C:§[0-9.]+)`", line)
    if m:
        key = m.group(1)
        continue
    if not line.startswith("|"):
        continue
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    if len(parts) == 8 and parts[0].isdigit():
        rows.append((key, int(parts[0]), parts[1], parts[3]))
assert len(rows) == 127
assert len(set((k, literal) for k, _, literal, _ in rows)) == 127
assert sorted(cw for _, cw, _, _ in rows) == list(range(1, 128))
print(Counter(disposition.replace("**", "") for *_, disposition in rows))
```

Observed output at execution:

```text
127 rows parsed; 127 unique composite keys; CW numbers exactly 1..127
Counter({"PASS": 100, "BLOCKED": 14,
         "SUPERSEDED WITH EVIDENCE": 11,
         "NOT APPLICABLE (APPROVED)": 2})
```

This reproduces the 14E published totals exactly (`100 PASS / 11 SUPERSEDED / 2 N/A /
14 BLOCKED`). The 14G successor then applies only the documented transitions in §4.

## 3. Successor crosswalk (127 rows)

Columns: `CW` = historical row number; `literal_id` = historical literal ID verbatim;
`hist` = historical disposition; `14E` = PR 14E adjudication; `14G` = PR 14G
adjudication; `evidence_ref` is the current binding evidence; `exec` is the execution
class. `RUN-14G` means executed in this PR; `INSPECT-14G reuse …` means immutable
evidence produced by a merged predecessor and inspected, **not re-executed** here.

### §2 historical STOP conditions (5 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 1 | `S1` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Reusable lexical leaf/scorer seam; mixed lexical+typed execution | `pr14_unified_mixed` m01–m14 (14), `pr14a_public_cursor::j06`, `real::b02` | RUN-14E (+REUSE-14D for `real::b02`) | evidence complete |
| 2 | `S2` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Public cursor cannot represent sorted search-after | `acquire_batch_pinned`/`execute_batch_pinned` + `pr14a_public_cursor` (26), `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 3 | `S3` | PASS | PASS | PASS | JSON missing/null/mixed ordering deterministic | `pr14_json` j09/j10/j11, `pr14a_public_cursor` j01–j05 | RUN-14E | evidence complete |
| 4 | `S4` | PASS | PASS | PASS | Indexed-but-not-stored JSON operators (no format change) | `pr14_json::j06`, `b18_b19` | RUN-14E | evidence complete |
| 5 | `S5` | PASS | PASS | PASS | PR 2 missing/null/multivalue semantics | `pr14_typed_predicates` t01–t03, t10 | RUN-14E | evidence complete |

### §3 original invariants `I01–I16` (16 rows; `pr-14/preimplementation-correctness-gate.md`)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 6 | `I01` | PASS | PASS | PASS | Identical AST + snapshot ⇒ identical logical hit set | `pr14_unified_mixed` m01–m14; `real::b02`; 14A t02/j07 | RUN-14E (+REUSE-14D) | evidence complete |
| 7 | `I02` | PASS | PASS | PASS | No deleted/obsolete documents | `pr14_typed_predicates::t11_delete_and_pit`, `pr14_projection::p06`, `real::r05` | RUN-14E (+REUSE-14D) | evidence complete |
| 8 | `I03` | PASS | PASS | PASS | BM25 only from positive lexical leaves | `pr14_unified_mixed::m04/m08/m13`, `pr14_f1_hardening::s01/s02/s05` | RUN-14E | evidence complete |
| 9 | `I04` | PASS | PASS | PASS | Exact counts, gap-free pagination | 14A t02–t05/j02, `pr14_unified_cursor::p03`, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 10 | `I05` | PASS | PASS | PASS | Cursor binds snapshot/query/sort/tuple | 14A t06/t07/t10, `real::b06_b07` negatives | RUN-14E (+REUSE-14D) | evidence complete |
| 11 | `I06` | PASS | PASS | PASS | JSON scalar type and range boundaries | `pr14_json` j01–j05, j08; `real::b18` | RUN-14E (+REUSE-14D) | evidence complete |
| 12 | `I07` | PASS | PASS | PASS | JSON missing/null/multivalue sort deterministic | 14A j04/j05, `pr14_json::j09/j10`, `b03` | RUN-14E | evidence complete |
| 13 | `I08` | PASS | PASS | PASS | No unstored-field leak | `pr14_projection` p01–p06, 14A t05 | RUN-14E | evidence complete |
| 14 | `I09` | PASS | PASS | PASS | IP/CIDR family and missing/null truth tables | `pr14_typed_predicates` t01–t10 | RUN-14E | evidence complete |
| 15 | `I10` | PASS | PASS | PASS | Exact aggregates share the predicate | `pr14_aggregation` a01–a05, `pr14_compound_aggregation` t05/t07/t12, `real::r02_r04_r06` | RUN-14E (+REUSE-14D) | evidence complete |
| 16 | `I11` | PASS | PASS | PASS | Batch cardinality and shared budgets | `pr14_batch` b01–b13, `pr14_batch_memory` b10a–b13j, `real::r10_r11` | RUN-14E (+REUSE-14D) | evidence complete |
| 17 | `I12` | PASS | PASS | PASS | Bounded work/memory/output, cancellation | `pr14_batch_memory` b10f/b12d/b13d, `pr14_f1_hardening::w06`, 14A t13 | RUN-14E | evidence complete |
| 18 | `I13` | BLOCKED | BLOCKED | PASS | **Zero query-time remote GET** | PR 14G Phase A `pr14g_remote_zero_get::a01` (FakeObjectStore exact `get_calls`) + `a02` (real pinned RustFS, GET-only `TransferStats::requests`), plus `a03`/`a04`/`a05`/`a06`; `+0` GETs for typed-only, mixed, serial batch and pinned page 1->2 after warmup; local Index oracle parity | RUN-14G (Phase A commit `e4d7237`) | evidence complete |
| 19 | `I14` | PASS | PASS | PASS | Persisted formats unchanged | `b18_b19` frozen golden; PR 13 regressions; docs-only PR 14E diff | RUN-14E | evidence complete |
| 20 | `I15` | PASS | PASS | PASS | Legacy segments correct or typed fail-closed | `pr11_json_corruption::t14…`, `legacy_json_tests`, `b18_b19` | RUN-14E | evidence complete |
| 21 | `I16` | PASS | PASS | PASS | Unsupported capabilities fail before expensive work | `pr14_projection::p04`, `pr14_batch::b04/b10/b13`, `pr14_f1_hardening::v01–v05` | RUN-14E | evidence complete |

### §4.1 typed predicates `T01–T12` (1 row)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 22 | `T01–T12` | PASS | PASS | PASS | Typed IPv4/IPv6/CIDR predicates and truth tables | `pr14_typed_predicates` t01–t12 (12) | RUN-14E | evidence complete |

### §4.2 JSON `J01–J13`, `J14`, `J15` (3 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 23 | `J01–J13` | PASS | PASS | PASS | JSON range/membership/sort/table semantics | `pr14_json` j01–j13 (13) | RUN-14E | evidence complete |
| 24 | `J14` | BLOCKED | PASS | PASS | Old-segment JSON fallback: a segment without the JSON-path section must evaluate by bounded, exact stored source, and fail typed when the field is not stored | `search::typed::legacy_json_tests::legacy_source_fallback_and_unstored_error` (section-stripped segment; `access.paths.is_none()`; matching and non-matching source fallback; `SearchError::UnsupportedOperator` for indexed-not-stored), `…::b1_legacy_source_fallback_wide_field` (2,000-member fallback) | RUN-14E | evidence complete; scope: unit-level production accessor, not an end-to-end `UnifiedSearcher` legacy query — see dossier D-02 |
| 25 | `J15` | BLOCKED | PASS | PASS | Legacy JSON segments: genuine historical artifact still decodes, reproduces byte-identically, and corrupt/unsupported bytes are rejected typed | `pr14_storage_vertical::b18_b19_historical_json_segment_compatibility` (frozen PR 11 artifact `65f7440`, SHA-256 `0528a62c…a02f`, writer reproduces byte-identical segment, corruption → `Err`, major 2 → `UnsupportedFormatVersion`), `pr11_json_corruption::t14_negotiation_and_corruption_fail_closed` (legacy neither-feature-nor-section opens cleanly), `pr14d_json_sort_memory::d07_historical_fixture_digest_and_corruption` | RUN-14E | evidence complete; see dossier D-03 |

### §4.3 projection `P01–P10` (4 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 26 | `P01–P07` | PASS | PASS | PASS | Source projection, order, five states, invalid rejection, budget, delete exclusion, lexical delegation | `pr14_projection` p01–p07 | RUN-14E | evidence complete |
| 27 | `P08` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Historical fail-closed negative superseded by mixed execution | `pr14_projection::p08_mixed_predicates_execute` | RUN-14E | evidence complete |
| 28 | `P09` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Historical lexical explicit-sort fail-closed superseded by support | `pr14_projection::p09_lexical_explicit_sort_supported` | RUN-14E | evidence complete |
| 29 | `P10` | PASS | PASS | PASS | Pure typed delegation | `pr14_projection::p10_pure_typed_delegation` | RUN-14E | evidence complete |

### §4.4 aggregation `A01–A05` (1 row)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 30 | `A01–A05` | PASS | PASS | PASS | Exact aggregation over matched live set | `pr14_aggregation` a01–a05 | RUN-14E | evidence complete |

### §4.5 batch `B01–B10` (7 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 31 | `B01–B04` | PASS | PASS | PASS | Single slot, ordered mixed outcomes, empty envelope, too many queries | `pr14_batch` b01–b04 | RUN-14E | evidence complete |
| 32 | `B05` | PASS | PASS | PASS | Conflicting PIT | `pr14_batch::b05_conflicting_pit`, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 33 | `B06` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Shared budget not reset | `pr14_batch::b06_work_is_not_hit_count`, `pr14_batch_memory` b12e/b12f/b11a | RUN-14E | evidence complete |
| 34 | `B07` | PASS | PASS | PASS | Cancellation preserves cardinality | `b07_cancellation_preserves_cardinality`, b10f, b13d | RUN-14E | evidence complete |
| 35 | `B08` | PASS | PASS | PASS | Aggregation slot isolated | `b08_aggregation_slot_isolated`, `real::r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |
| 36 | `B09` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Cursor slot fails closed on the naked entry; pinned path supported by 14A | `b09_cursor_slot_fails_closed`, `pr14a_public_cursor` (26) | RUN-14E | evidence complete |
| 37 | `B10` | PASS | PASS | PASS | Invalid aggregate kind | `b10_invalid_aggregate_kind`, `real::r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |

### §4.6 original uncovered matrices `U/G/R/X` (4 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 38 | `U01–U06` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Mixed execution / mixed live universe (family level; per-ID definitions unavailable) | `pr14_unified_mixed` (14), `real::b02` | RUN-14E (+REUSE-14D) | evidence complete |
| 39 | `G01–G14` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Dedicated budget/cancellation matrix (family level) | `pr14_batch_memory` (31), `pr14_f1_hardening` W-series, `pr14_compound_aggregation` t13–t26 | RUN-14E | evidence complete |
| 40 | `R01–R07` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | RustFS cold/warm/fault/golden (family level) | §7.2 provider verticals, PR 14D vertical/fault suites | REUSE-14D | evidence complete |
| 41 | `X01–X13` | BLOCKED | BLOCKED | BLOCKED | Independent local/FakeObjectStore/real-RustFS oracles per-ID | Repository search found no per-ID definitions: `pr-14/test-traceability.md:63` records only the family sentence; `corrective-test-traceability.md` reuses `X01` under corrective `I01` and `X01–X10` under corrective `I14`; git history (`fa82db7`, `d0c445a`, `e0e1dcb`) contains no definition table | INSPECT-14E | maintainer decision → dossier D-16 |

### §5.1 P2B checkpoints A–F (8 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 42 | `A` | PASS | PASS | PASS | Disjoint work/memory/response sub-meters | `search::batch_meter` unit tests | RUN-14E | evidence complete |
| 43 | `B` | PASS | PASS | PASS | `MemoryCharge`/`SlotMemoryScope` checked reserve/release | `search::memory` unit tests | RUN-14E | evidence complete |
| 44 | `C1` | PASS | PASS | PASS | Candidate local preflight/commit primitives | `search::execute::budget_tests::c1*` | RUN-14E | evidence complete |
| 45 | `C2` | PASS | PASS | PASS | Segment candidate ledger ephemeral sink | `c2_*` units, `pr14_batch_memory` b10i/b10j | RUN-14E | evidence complete |
| 46 | `C3` | PASS | PASS | PASS | K+1 heap batch binding | `c3_*` units, `pr14_batch_memory` b10g/b10h | RUN-14E | evidence complete |
| 47 | `D` | PASS | PASS | PASS | Typed/geo/JSON scratch accounting | `pr14_batch_memory` b11a–b11e | RUN-14E | evidence complete |
| 48 | `E` | PASS | PASS | PASS | Projection/response handoff | `pr14_batch_memory` b12a–b12f | RUN-14E | evidence complete |
| 49 | `F` | PASS | PASS | PASS | B10a–B13j acceptance | `pr14_batch_memory` (31) | RUN-14E | evidence complete |

### §5.2 remaining unified cursor `P01–P12` (2 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 50 | `P01–P08, P10–P12` | PASS | PASS | PASS | Unified cursor tuple/resume semantics | `pr14_unified_cursor` (11) | RUN-14E | evidence complete |
| 51 | `P09` | PASS | PASS | PASS | Cursor tuple length/class validation | `search::unified::tests::cursor_tuple_length_and_class_are_validated` | RUN-14E | evidence complete |

### §5.3 corrective matrix (9 rows; reuses `I01–I16` with different meanings)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 52 | `I01` | PASS | PASS | PASS | Mixed Boolean equivalence | `pr14_unified_mixed` m01–m14, `real::b02` | RUN-14E (+REUSE-14D) | evidence complete |
| 53 | `I03` | PASS | PASS | PASS | BM25 under lexical extraction | m04/m08/m13, `pr14_f1_hardening` s01/s02/s03/s05 | RUN-14E | evidence complete |
| 54 | `I05` | PASS | PASS | PASS | Full-tuple public cursor | `pr14a_public_cursor` (26) | RUN-14E | evidence complete |
| 55 | `I07` | BLOCKED | BLOCKED | PASS | **Exact `HitRef` projection identity** | PR 14G Phase B `search::unified::tests::g_b01/g_b03/g_b04/g_b05`: projection equals the exact physical `(segment_index, doc_id)` oracle in selected order, mismatched key yields `SearchError::CorruptIndex`, key-latest shortcut demonstrably differs | RUN-14G (Phase B commit `d1ee42b`) | evidence complete |
| 56 | `I09` | PASS | PASS | PASS | Cumulative work/memory | `pr14_batch_memory` b10a/b12e/b13b, `real::r10_r11` | RUN-14E (+REUSE-14D) | evidence complete |
| 57 | `I11` | PASS | PASS | PASS | Mixed aggregation | `pr14_compound_aggregation` t01–t26, `real::b02`/`r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |
| 58 | `I12` | BLOCKED | BLOCKED | PASS | **Zero-GET instrumentation** | PR 14G Phase A `a01`/`a05` three-slot serial batch (typed, mixed, aggregation) with exact local slot parity and `+0` GETs on the fake and real-provider boundaries | RUN-14G (Phase A commit `e4d7237`) | evidence complete |
| 59 | `I14` | PASS | PASS | PASS | RustFS oracle equivalence | `real::r02_r04_r06`, `real::b02`, `real::r08_r09_r15` | REUSE-14D | evidence complete |
| 60 | `I16` | BLOCKED | PASS | PASS | Final-SHA CI | Exact-head check runs green at every pushed PR of the PR 14 line: `a61f0b8` (PR #62 head), `635c7f4` (PR #64 head), `dc506f6` (main head) — `rust`, `msrv`, `rustfs` all `completed/success`. The never-pushed local corrective commits (`e0e1dcb`, `d0c445a`) have **0** check runs and are **not** claimed. | INSPECT-14E | evidence complete; scope in dossier D-06 |

### §5.4 final-design matrix `I1–I14` (14 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 61 | `I1` | PASS | PASS | PASS | Mixed Boolean membership | `pr14_unified_mixed` m01–m14 | RUN-14E | evidence complete |
| 62 | `I2` | PASS | PASS | PASS | Effective-live only / delete | m07, `real::r05` | RUN-14E (+REUSE-14D) | evidence complete |
| 63 | `I3` | PASS | PASS | PASS | BM25 unchanged / positive only | m04/m08/m13, s01–s05 | RUN-14E | evidence complete |
| 64 | `I4` | PASS | PASS | PASS | Exact total before top-K | m12, 14A t05, `pr14_batch::b01` | RUN-14E | evidence complete |
| 65 | `I5` | PASS | PASS | PASS | Total sort / gap-free cursor | 14A t02–t05, j02/j07, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 66 | `I6` | PASS | PASS | PASS | Cursor binding/expiry | 14A t06/t07/t10, `real::b06_b07` | RUN-14E (+REUSE-14D) | evidence complete |
| 67 | `I7` | PASS | PASS | PASS | Five field states | `pr14_projection::p03`, `pr14_batch::b11` | RUN-14E | evidence complete |
| 68 | `I8` | BLOCKED | BLOCKED | PASS | **Exact physical hit identity** | PR 14G Phase B `g_b02` old/new PIT physical identity across a real upsert (`(1,0)` before vs `(2,0)` after), `g_b03` deleted-key/old-pin stability and deterministic ties, `g_b05` key-rescan discriminator | RUN-14G (Phase B commit `d1ee42b`) | evidence complete |
| 69 | `I9` | PASS | PASS | PASS | Work charged at scan sites | `pr14_f1_hardening` w04/w04b/w06, `search::work` units | RUN-14E | evidence complete |
| 70 | `I10` | PASS | PASS | PASS | Shared budgets never reset | `pr14_batch_memory` b12e/b12f, `real::r10_r11` | RUN-14E (+REUSE-14D) | evidence complete |
| 71 | `I11` | PASS | PASS | PASS | Policy/capability admission | `pr14_batch` b10/b13, `pr14_projection::p04` | RUN-14E | evidence complete |
| 72 | `I12` | PASS | PASS | PASS | Aggregate sees every match once | `pr14_compound_aggregation` t05/t07/t12/t13 | RUN-14E | evidence complete |
| 73 | `I13` | BLOCKED | BLOCKED | PASS | **No query-time remote GET** | PR 14G Phase A `a01`/`a05`/`a02` pinned page 1->2 chains on one frozen generation (page sizes 1/2/3/4), non-overlapping and exact, with `+0` GETs; `a06` old/new generation guard | RUN-14G (Phase A commit `e4d7237`) | evidence complete |
| 74 | `I14` | PASS | PASS | PASS | No persisted format change | frozen golden + PR 13 suites; docs-only PR 14E diff | RUN-14E | evidence complete |

### §5.5 F1 hardening `W/S/V/G/M/P` (6 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 75 | `W01–W06` | PASS | PASS | PASS | Work accounting at scan/rejected-charge sites | `search::work` units (7), `pr14_f1_hardening` w04/w04b/w06, `budget_tests` | RUN-14E | evidence complete |
| 76 | `S01–S05` | PASS | PASS | PASS | Scorer/stat parity under extraction | `pr14_f1_hardening` s01/s02/s03/s05; S04 = `pr14_unified_mixed::m07` | RUN-14E | evidence complete |
| 77 | `V01–V05` | PASS | PASS | PASS | Validation/fail-closed cases | `pr14_f1_hardening` v01–v05 | RUN-14E | evidence complete |
| 78 | `G01–G05` | PASS | PASS | PASS | Geo sort family (this generation) | `pr14_f1_hardening` g01–g05 | RUN-14E | evidence complete |
| 79 | `M01–M06` | PASS | PASS | PASS | Memory-bound family | `pr14_f1_hardening` m01/m02/m04/m05/m06; M03 = `budget_tests::production_global_bytes…` | RUN-14E | evidence complete |
| 80 | `P01–P05` | PASS | PASS | PASS | Projection family | `pr14_projection` p01/p03/p06, `real::b03` | RUN-14E (+REUSE-14D) | evidence complete |

### §6 phases `14A–14G` (7 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 81 | `14A unified compiler + mixed execution` | PASS | PASS | PASS | Mixed execution and unified compiler | `pr14_unified_mixed`, `real::b02`, F1 parity | RUN-14E (+REUSE-14D) | evidence complete |
| 82 | `14B typed/IP/CIDR completeness` | PASS | PASS | PASS | Typed predicate completeness | `pr14_typed_predicates` (12) | RUN-14E | evidence complete |
| 83 | `14C JSON range/membership/sort` | PASS (note: legacy fallback J14/J15 remain BLOCKED) | PASS | PASS | JSON query surface; historical row counted as one PASS row | `pr14_json` (13), 14A J01–J12, `real::b03/b18` | RUN-14E (+REUSE-14D) | evidence complete; the J14/J15 note is now closed by CW-024/CW-025 |
| 84 | `14D projections` | PASS | PASS | PASS | Stored projections | `pr14_projection` (10) | RUN-14E | evidence complete |
| 85 | `14E aggregation + serial batch` | PASS | PASS | PASS | Aggregation and serial batch | `pr14_aggregation` (5), `pr14_compound_aggregation` (24), `pr14_batch` (12) | RUN-14E | evidence complete |
| 86 | `14F real-boundary RustFS + faults + benchmarks` | BLOCKED | BLOCKED | PASS | Real boundary + faults + **benchmarks** | merged PR #67 (merge `054ca55d143e89a092cc6519231b820fecfa42dc`); three fresh qualified `pr14_p4_v1` trials at source `d12a97537a5131953c948c3a90065a73c3d24b40`, evidence head `cc8153e593bc403d169da291a95a5ad18c6b0293`; validator PASS, strict auditor `PASS PR14F audit`, W08 `NOT APPLICABLE (APPROVED)`; deterministic package SHA-256 `373d3b756598b1a70f1501530167e7399a47d9172799b0bf05a40ee6ada181e2`, durable archive file id `18VqahZSMlRRnijXppRlJCVcUzTi9Zp4z` (operator-attested); `docs/pr-artifacts/pr-14f/sr14f01-fixup.md` | INSPECT-14G reuse of immutable merged PR #67 evidence | evidence complete (PR 14F qualified) |
| 87 | `14G final gates, CI, docs` | BLOCKED | BLOCKED | BLOCKED | Final gates + CI + docs | CI component now verified (CW-060); benchmarks (CW-086/D-09…D-14), risk signoff (D-18) and PR 14 acceptance remain open | INSPECT-14E | PR 14F + maintainer → dossier D-10 |

### §7.1 `V01–V14` (7 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 88 | `V01, V02, V03, V06` | PASS | PASS | PASS | R01–R07 provider verticals | `real::r01…`, `real::r02_r04_r06…`, cold-bootstrap suite | REUSE-14D | evidence complete |
| 89 | `V04, V05` | PASS | PASS | PASS | R08–R11 batch/budget verticals | `real::r08_r09_r15`, `real::r10_r11` | REUSE-14D | evidence complete |
| 90 | `V06, V09` | PASS | PASS | PASS | R12–R14 cold-cache/pin/eviction (the source lists V06 twice; reproduced as recorded) | `real::r12`, `real::r13_r14` | REUSE-14D | evidence complete |
| 91 | `V07, V08, V10` | PASS | PASS | PASS | F01–F10 provider faults | `pr14_storage_faults` 9 cases × 10 iterations | REUSE-14D | evidence complete |
| 92 | `V11, V12` | BLOCKED | BLOCKED | PASS | Benchmark oracle + three qualified trials | merged PR #67 (merge `054ca55d143e89a092cc6519231b820fecfa42dc`); three fresh qualified `pr14_p4_v1` trials at source `d12a97537a5131953c948c3a90065a73c3d24b40`, evidence head `cc8153e593bc403d169da291a95a5ad18c6b0293`; validator PASS, strict auditor `PASS PR14F audit`, W08 `NOT APPLICABLE (APPROVED)`; deterministic package SHA-256 `373d3b756598b1a70f1501530167e7399a47d9172799b0bf05a40ee6ada181e2`, durable archive file id `18VqahZSMlRRnijXppRlJCVcUzTi9Zp4z` (operator-attested); latency tables `benchmarks/reports/pr14f-p4-d12a97537a51-t{1,2,3}.json` (`docs/pr-artifacts/pr-14f/benchmark-report.md` §10) | INSPECT-14G reuse of immutable merged PR #67 evidence | evidence complete (PR 14F qualified) |
| 93 | `V13` | PASS | PASS | PASS | No codec/manifest/format changes | PR 13/PR 11 golden suites; docs-only PR 14E diff | RUN-14E | evidence complete |
| 94 | `V14` | PASS | PASS | PASS | R15 cursor + aggregation fail-closed | naked-batch `b09`; pinned `real::r08_r09_r15` | RUN-14E (+REUSE-14D) | evidence complete |

### §7.2 `R01–R15` provider storage verticals (10 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 95 | `R01` | PASS | PASS | PASS | Separate-process cold bootstrap | `real::r01` | REUSE-14D | evidence complete |
| 96 | `R02, R04, R06` | PASS | PASS | PASS | Cold compound equivalence + aggregation | `real::r02_r04_r06` | REUSE-14D | evidence complete |
| 97 | `R03` | PASS | PASS | PASS | Wrong generation not substituted | `real::r03` | REUSE-14D | evidence complete |
| 98 | `R05` | PASS | PASS | PASS | Mutation; old pin unchanged; new generation | `real::r05` | REUSE-14D | evidence complete |
| 99 | `R07` | PASS | PASS | PASS | Local missing/null/empty/multivalue + geo/tie ordering | `r07_local_states_and_tie_order` (local engine, as classified in P4) | RUN-14E | evidence complete |
| 100 | `R08, R09` | PASS | PASS | PASS | Ordered batch, aggregation, prior success retained | `real::r08_r09_r15` | REUSE-14D | evidence complete |
| 101 | `R10, R11` | PASS | PASS | PASS | Remote exact/one-over memory/response budgets | `real::r10_r11` | REUSE-14D | evidence complete |
| 102 | `R12` | PASS | PASS | PASS | Empty-cache cold bootstrap, no writer state | `real::r12` | REUSE-14D | evidence complete |
| 103 | `R13, R14` | PASS | PASS | PASS | Warm reuse; pinned bytes not evicted; fail-closed tiny cache | `real::r13_r14` | REUSE-14D | evidence complete |
| 104 | `R15` | PASS | PASS | PASS | Public cursor + aggregation | `real::r08_r09_r15`, 14A t05/t11 | REUSE-14D | evidence complete |

### §7.3 `F01–F10` provider faults (9 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 105 | `F01` | PASS | PASS | PASS | Segment GET transient failure | `f01_segment_get_transient_failure` ×10 | REUSE-14D | evidence complete |
| 106 | `F02` | PASS | PASS | PASS | Truncated segment transfer | `f02_truncated_segment_transfer` ×10 | REUSE-14D | evidence complete |
| 107 | `F03` | PASS | PASS | PASS | Corrupt content-range rejected | `f03_corrupt_content_range_rejected` ×10 | REUSE-14D | evidence complete |
| 108 | `F04` | PASS | PASS | PASS | Manifest read interrupted | `f04_manifest_read_interrupted` ×10 | REUSE-14D | evidence complete |
| 109 | `F05` | PASS | PASS | PASS | Concurrent old reader + new commit | `f05_concurrent_old_reader_and_new_commit` ×10 | REUSE-14D | evidence complete |
| 110 | `F06` | PASS | PASS | PASS | Cancellation during transfer bounded | `f06_cancellation_during_transfer_is_bounded` ×10 | REUSE-14D | evidence complete |
| 111 | `F07` | PASS | PASS | PASS | Retry exhaustion bounded and recoverable | `f07_retry_exhaustion_is_bounded_and_recoverable` ×10 | REUSE-14D | evidence complete |
| 112 | `F08` | PASS | PASS | PASS | Crash at download checkpoint | `f08_crash_at_download_checkpoint` ×10 (SIGKILL child) | REUSE-14D | evidence complete |
| 113 | `F09, F10` | PASS | PASS | PASS | Batch after fault and S/F/S | `f09_f10_batch_after_fault_and_s_f_s` ×10 | REUSE-14D | evidence complete |

### §7.4 benchmark qualification `B01–B04` (4 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 114 | `B01` | BLOCKED | BLOCKED | PASS | Correctness oracle passes before timing | every trial asserted the full remote oracle before the first cold stopwatch; marker `PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS` present in all three run logs (source `d12a975…`); `docs/pr-artifacts/pr-14f/sr14f01-fixup.md` §3–§4 | INSPECT-14G reuse of immutable merged PR #67 evidence | evidence complete (PR 14F qualified) |
| 115 | `B02` | PASS | PASS | PASS | Validator rejects invalid/unqualified reports | `validate-pr14-p4.py --self-test` | RUN-14E | evidence complete |
| 116 | `B03` | BLOCKED | BLOCKED | PASS | Three independently qualified trials | three independently qualified trials `t1/t2/t3` at `d12a975…`: `qualified=true`, `idle_confirmed=true`, per-trial contention `clear`, 20 samples x 14 lanes each; validator `PASS: 3 qualified pr14_p4_v1 trials`; auditor `PASS PR14F audit` | INSPECT-14G reuse of immutable merged PR #67 evidence | evidence complete (PR 14F qualified) |
| 117 | `B04` | PASS | PASS | PASS | Dirty/contended/unknown rejection | wrapper source + validator self-test | RUN-14E | evidence complete |

### §7.5 `W01–W09` workload lanes (2 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 118 | `W01–W07, W09` | BLOCKED | BLOCKED | PASS | Measured lanes with correctness oracle | all measured lanes executed in the three qualified trials at `d12a975…` (14 lanes x 20 samples per trial, raw CSV archived); W08 remains `NOT APPLICABLE (APPROVED)` and was never measured | INSPECT-14G reuse of immutable merged PR #67 evidence | evidence complete (PR 14F qualified) |
| 119 | `W08` | N/A (APPROVED) | NOT APPLICABLE (APPROVED) | NOT APPLICABLE (APPROVED) | Forced eviction/reload lane | Approved Option 2 v0.1 snapshot-lifetime pinning exception: `docs/pr-artifacts/pr-14/p4-w08-stop.md`, `benchmarks/reports/pr14-p4-w08-exemption.json`, required by the validator | RUN-14E | evidence complete — **never measured** |

### §7.6 final-SHA CI `Q` gates (1 row)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 120 | `Q01–Q06 / Q01–Q09` | BLOCKED | PASS | PASS | Pushed PR + CI on the exact head (family-level CI gate) | Exact-head check runs, all `completed/success` for `rust`, `msrv`, `rustfs`: `6cb6d47` (#61), `a61f0b8` (#62), `4097a02` (#63), `635c7f4` (#64), `b66f817` (#65), merge/main heads `2cb91be`, `6d18ebe`, `dc506f6`. Per-ID `Q` check definitions are not recorded in the repository; adjudicated at family level exactly as the historical row was recorded. | INSPECT-14E | evidence complete; scope in dossier D-15 |

### §8 preauthorized mapping table (7 rows)

| CW | literal_id | hist | 14E | 14G | obligation | evidence_ref | exec | owner → next gate |
|---|---|---|---|---|---|---|---|---|
| 121 | `1. S1` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Mapping 1 verifies mixed execution | `pr14_unified_mixed`, `real::b02` | RUN-14E (+REUSE-14D) | evidence complete |
| 122 | `2. S2` | SUPERSEDED | SUPERSEDED WITH EVIDENCE | SUPERSEDED WITH EVIDENCE | Mapping 2 verifies pinned cursor support; naked entry fails closed | `pr14a_public_cursor`, `real::b06_b07`, `b09` | RUN-14E (+REUSE-14D) | evidence complete |
| 123 | `3. Legacy JSON/projection/aggregation/typed sorting` | PASS | PASS | PASS | Legacy JSON/projection/aggregation/typed sorting compatibility (JSON wire v1) | `pr14_json`/`pr14_projection`/`pr14_aggregation`/`pr14_typed_predicates`, `real::b18` | RUN-14E (+REUSE-14D) | evidence complete |
| 124 | `4. R01–R15 / F01–F10` | PASS | PASS | PASS | Provider verticals and faults | PR 14B evidence re-executed in PR 14C; re-cited (not re-executed) in 14E | REUSE-14D | evidence complete |
| 125 | `5. W08` | N/A (APPROVED) | NOT APPLICABLE (APPROVED) | NOT APPLICABLE (APPROVED) | Approved W08 exception | exemption manifest + validator | RUN-14E | evidence complete — never measured |
| 126 | `6. Benchmarks` | BLOCKED | BLOCKED | PASS | Fresh trials required; old reports provenance only | superseded by the three freshly qualified PR 14F trials at `d12a975…`; the historical `ab9b2d7` reports remain provenance-only and are not reused as current benchmark evidence | INSPECT-14G reuse of immutable merged PR #67 evidence | evidence complete (PR 14F qualified) |
| 127 | `7. JSON temp memory` | BLOCKED | BLOCKED | BLOCKED | `R-14A-JSON-MEM`: correction **and** human risk closure | Correction implemented `d0e1bbb`, merged via #64 (`6d18ebe`), reviewed head `635c7f4` CI-verified; B20/B21 re-characterized (387 / 45,726 / 1,462,302 B); **human risk-closure acceptance not recorded** | REUSE-14D / INSPECT-14E | maintainer risk signoff → dossier D-18 |

## 4. Transition record (no implied transitions)

### 4.1 PR 14F: six historical `BLOCKED → PASS` transitions

Justified only by merged PR #67 immutable evidence. No benchmark was re-run in PR
14G (X25: no production query, remote-cache or workload behaviour changed in the PR
14G diff, so the PR 14F qualification remains valid).

| CW | literal_id | proof |
|---|---|---|
| 086 | `14F real-boundary RustFS + faults + benchmarks` | three qualified trials at `d12a975…`; validator + auditor PASS; Drive archive `18Vqah…` (operator-attested) |
| 092 | `V11, V12` | benchmark oracle + three qualified trials; per-trial reports `pr14f-p4-d12a97537a51-t{1,2,3}.json` |
| 114 | `B01` | remote oracle marker `PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS` before every timed cold lane |
| 116 | `B03` | `t1/t2/t3` qualified, idle-confirmed, contention `clear` |
| 118 | `W01–W07, W09` | all measured lanes executed; W08 remains approved N/A and unmeasured |
| 126 | `6. Benchmarks` | fresh qualified trials supersede the provenance-only `ab9b2d7` reports |

### 4.2 PR 14G Phase A: three `BLOCKED → PASS` transitions

Both the deterministic FakeObjectStore test (non-ignored) and the gated real-RustFS
test (executed explicitly against the pinned provider) produced the mandated counter
positive control and exactly zero additional GETs after warmup, with independent local
oracle parity. Evidence: `docs/pr-artifacts/pr-14g/phase-a-zero-get.md`.

| CW | literal_id | proof |
|---|---|---|
| 018 | `I13` (§3) | `a01` fake `get_calls` `+0` after warmup; `a02` real GET-only `requests` `+0`; local/remote typed, mixed, batch, pinned parity |
| 058 | `I12` (§5.3) | three-slot serial batch (typed/mixed/aggregation) with exact slot parity and `+0` GETs on both boundaries |
| 073 | `I13` (§5.4) | pinned page 1->2 chains (page sizes 1/2/3/4) on one frozen generation, `+0` GETs; `a06` old/new generation guard |

### 4.3 PR 14G Phase B: two `BLOCKED → PASS` transitions

The physical-tuple proofs and the negative key-latest discriminator both executed and
passed. Evidence: `docs/pr-artifacts/pr-14g/phase-b-physical-identity.md`.

| CW | literal_id | proof |
|---|---|---|
| 055 | `I07` (§5.3) | `g_b01` exact `(segment,doc,key,host)` projection oracle; `g_b03` deletion/tie ordering; `g_b04` mismatched key → `CorruptIndex`; `g_b05` key-latest differs |
| 068 | `I8` (§5.4) | `g_b02` `(1,0)`→`(2,0)` old/new PIT identity; `g_b03` old-pin stability; `g_b05` shortcut regression |

### 4.4 Rows that did **not** transition

| CW | literal_id | 14G state | reason |
|---|---|---|---|
| 041 | `X01–X13` (§4.6) | `BLOCKED` | no authoritative per-ID definitions exist; requires one of the three recorded maintainer options (`maintainer-decisions.md` §1). No per-ID test was fabricated. |
| 127 | `7. JSON temp memory` (§8) | `BLOCKED` | `R-14A-JSON-MEM` correction is merged (`d0e1bbb`, `3f82284`, `635c7f4`, merge `6d18ebe`), but the dated human risk closure is absent (`maintainer-decisions.md` §2). |
| 087 | `14G final gates, CI, docs` (§6) | `BLOCKED` | depends on CW-041/CW-127 decisions, exact-head CI and independent review; none is satisfied or claimable by the agent. |

No other row changed disposition. `FAIL` remains `0`.

## 5. Recomputed totals

| Adjudication | 14E | 14F delta | 14G delta | **14G total** |
|---|---:|---:|---:|---:|
| PASS | 100 | +6 | +5 | **111** |
| SUPERSEDED WITH EVIDENCE | 11 | 0 | 0 | **11** |
| NOT APPLICABLE (APPROVED) | 2 | 0 | 0 | **2** |
| BLOCKED | 14 | −6 | −5 | **3** |
| FAIL | 0 | 0 | 0 | **0** |
| **Total** | **127** | 0 | 0 | **127** |

The `FAIL` count of `0` is valid because no executed PR 14G gate failed: all five new
tests, both provider boundaries, both toolchains and both feature sets passed (see
`validation-report.md`).

Remaining `BLOCKED` rows and their owners:

| CW | literal_id | owner | next gate |
|---|---|---|---|
| 041 | `X01–X13` | maintainer | select X-A / X-B / X-C with a dated, named decision |
| 127 | `7. JSON temp memory` | maintainer | dated ACCEPT-or-REJECT residual-risk decision |
| 087 | `14G final gates, CI, docs` | maintainer + independent reviewer | the two decisions above, exact-head CI and independent review |

## 6. What this crosswalk does not claim

- It does **not** mark PR 14 accepted, merged, or v0.1 released.
- It does **not** convert CW-041 or CW-127; no risk closure or per-ID definition is
  invented, and no human signature is written by an agent.
- It does **not** claim CI success at any head. Exact-head CI for PR 14G is recorded
  as `PENDING`/unverifiable in `validation-report.md` because the GitHub API token in
  the execution environment was invalid.
- It does **not** re-run or re-qualify the PR 14F benchmarks.
- It does **not** rewrite or supersede the historical PR 14C/14E artefacts, which
  remain immutable evidence.

