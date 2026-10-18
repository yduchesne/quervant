# PR 14 — F1 hardening test traceability

State: `dev/pagination`, HEAD `83e1dcf` + uncommitted hardening edits.

| ID | Test symbol | Status |
|---|---|---|
| S01 | `pr14_f1_hardening::s01_term_parity` | PASS (bit-exact `f64::to_bits`) |
| S02 | `s02_phrase_parity` | PASS |
| S03 | `s03_duplicate_nested_parity` | PASS |
| S05 | `s05_two_segment_statistics_parity` | PASS |
| S04 | `pr14_unified_mixed::m07_not_cannot_resurrect_tombstones` | PASS |
| V01 | `v01_unknown_sort_field` | PASS |
| V02 | `v02_noncolumnar_sort_field` | PASS |
| V03 | `v03_multivalue_selector_required` | PASS |
| V04 | `v04_json_path_on_non_json_field` | PASS |
| V05 | `v05_invalid_geo_sort_field` | PASS |
| G01 | `g01_geo_ascending` | PASS |
| G02 | `g02_geo_descending` | PASS |
| G03 | `g03_geo_missing_first` | PASS |
| G04/G05 | multivalue-min / key-tie geo — not separately added; covered by shared PR 10 comparator | PARTIAL |
| M02 | `m02_top_k_total_hits` | PASS |
| M01/M03/M04/M05/M06 | exact/one-over bytes, full-sort oracle, long keyword, multi-segment+cancel — not all added | PARTIAL |
| P02 | `p02_projection_uses_current_version` | PASS |
| P01/P03/P04/P05 | covered by existing `pr14_projection` (p01/p03/p06) and mixed path | PARTIAL |
| W01–W06 | work/cancellation — blocked by STOP H1 | NOT IMPLEMENTED |
| R01 | PR 7 lexical suites + `m13` parity | PASS |
| R02 | PR 10 typed suites | PASS |
| R03 | `pr14_unified_mixed` (14), `pr14_projection` (10) | PASS |
| R04 | no codec/manifest/storage changes | PASS |

Every mixed-specific test (`m*`, `s*`, `g*`, `p02`) uses an AST containing both a lexical leaf
and a typed leaf (or a nonrestrictive `Exists(host)` for parity tests).
