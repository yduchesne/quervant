# PR 14 — F1 hardening test traceability

State: `dev/pagination`, base `69d47ba` + uncommitted H1 edits.

| ID | Test symbol | Status |
|---|---|---|
| W02/W03 | `search::work::tests::aggregate_exhaustion_blocks_typed_after_lexical` | PASS |
| W03 | `search::work::tests::rejected_typed_charge_does_not_mutate_counters` | PASS |
| W06 | `search::work::tests::scanned_charges_add_one_plus_freq` | PASS |
| W04 | `pr14_f1_hardening::w04_zero_match_scan_charges_work` | PASS |
| W06 | `pr14_f1_hardening::w06_mixed_cancellation` | PASS |
| W01/W05 | repeated queries / standalone budgets → existing PR 7/PR 10 suites + S01–S05 | PASS |
| I01/I02 | shared meter unit tests + W04/W06 | PASS |
| S01 | `s01_term_parity` (bit-exact) | PASS |
| S02 | `s02_phrase_parity` | PASS |
| S03 | `s03_duplicate_nested_parity` | PASS |
| S04 | `pr14_unified_mixed::m07_not_cannot_resurrect_tombstones` | PASS |
| S05 | `s05_two_segment_statistics_parity` | PASS |
| V01–V05 | `v01`–`v05` | PASS |
| G01–G03 | `g01`–`g03` | PASS |
| G04/G05 | multivalue-min / key-tie geo | PARTIAL (shared PR 10 comparator) |
| M02 | `m02_top_k_total_hits` | PASS |
| M01/M03–M06 | exact/one-over bytes, full-sort oracle, long keyword, multi-segment+cancel | PARTIAL |
| P02 | `p02_projection_uses_current_version` | PASS |
| P01/P03–P05 | existing `pr14_projection` + mixed path | PARTIAL |
| R01–R04 | PR 7/10/14 suites; no codec/storage diff | PASS |

New total: `pr14_f1_hardening` 16, `pr14_unified_mixed` 14, `pr14_projection` 10, `pr14_batch` 12.
