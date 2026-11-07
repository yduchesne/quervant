# PR 15H-B — invariant traceability

| ID | Invariant | Evidence | Status |
|---|---|---|---|
| B-I01 | Only the precise eligible shape uses B | `b_u01_u08_u36_counts_order_and_materialization`; `b_u04_u05_u11_u16_ineligible_shapes`; integration `b_i01` | PASS |
| B-I02 | Other shapes/API siblings untouched | `b_u04_u05…`; `b_i08_multi_and_typed_fallback`; source diff | PASS |
| B-I03 | Exact `total_hits`, no stop at K | `b_u01…` (50K), `b_i01` | PASS |
| B-I04 | BM25 score bits unchanged | `b_u01…`, `b_u12_two_segment_score_bits`, `b_i01` | PASS |
| B-I05 | Raw UTF-8 byte order; ASC/DESC values only | `b_u07_utf8_ordering`, `b_comparator_tests::b_u06_u10…` | PASS |
| B-I06 | Missing/null/empty/present ordering | `b_u06_u09_u10_missing_null_tie_ordering`; column `b_u06_u16…` | PASS |
| B-I07 | Logical key ascending tie-break | `b_u06_u09_u10…`; `b_i02_two_segment_key_tie` | PASS |
| B-I08 | Key resolved before sort decode; first-error order | source order; `b_i05` corruption; existing key tests | PASS |
| B-I09 | Malformed losing values still fail | `b_u14_invalid_utf8_rejected`, `b_u18_decode_budget_rejected`, `b_u17_out_of_range_rejected` | PASS |
| B-I10 | Legacy-decoding state never reinterpreted | `b_u06_u16…` (`LegacyDecode`), source fallback | PASS |
| B-I11 | Retained entries own their tuples | `materialize_keyword_entry`; `b_u01…` heap path | PASS |
| B-I12 | Identical modeled charge/overflow order | `borrowed_keyword_candidate_charge`; test assert in `materialize_keyword_entry` | PASS |
| B-I13 | Duplicate retained key checked before competitiveness | fast-path duplicate check; existing duplicate tests | PASS |
| B-I14 | Heap preflight/overlap/atomicity unchanged | extracted `heap_admit_candidate`; existing heap budget tests | PASS |
| B-I15 | Cancellation/work counters unchanged | unchanged `execute.rs`/meter; existing cancellation tests | PASS |
| B-I16 | PIT/cursor/projection/aggregation/typed unchanged | `b_i03_pit…`, `b_i04_cursor…`, `b_i08…`; existing suites | PASS |
| B-I17 | Wire/format/manifest/DOC_KEYS unchanged | production diff excludes those; equal index digests | PASS |
| B-I18 | No borrowed reference escapes | `ColumnKeywordView<'_>` tied to `&self`; compile-time | PASS |
| B-I19 | No new I/O/tracing/shared state in hot path | source diff; no imports added | PASS |
| B-I20 | Quervant-only, same host/inputs/index | sealed `paired-01` manifest | PASS |
| B-I21 | Absolute-millisecond gates | `test_run.py` gate tests; `performance.md` | PASS |
| B-I22 | Rejection restores source | not applicable: accepted | N/A |
| B-I23 | QA/MSRV/coverage/RustFS separate | `qa-and-ci.md` | PASS |
| B-I24 | Unanticipated cases hard-stop | no hard stop encountered | PASS |

## Fixup subsection (B-R01/B-R02/B-R03)

Appended after the original traceability table; original PASS claims are unchanged.

| ID | Fixup evidence | Status |
|---|---|---|
| BF-I01 | `require_same_tooling` + `BF-T01/T02/T03/T07` | PASS |
| BF-I02 | `BF-T04/T05/T06` | PASS |
| BF-I03 | `verify_campaign` guard + historical `--verify-only` | PASS |
| BF-I04 | original baseline/paired seals verified with original tooling | PASS |
| BF-I05 | `BF-T08/T09` | PASS |
| BF-I06 | `BF-T10/T11/T12` | PASS |
| BF-I07 | `BF-U01` intact losing candidate: zero owned materializations | PASS |
| BF-I08 | `BF-U02` exact `SegmentError::InvalidUtf8 { context: "keyword" }` | PASS |
| BF-I09 | `BF-U02` heap/charge/counters unchanged | PASS |
| BF-I10 | `BF-U03` owned `sort_tuple_for_doc` same typed error | PASS |
| BF-I11 | `#[cfg(test)]` constructor only; release build green | PASS |
| BF-I12 | blob audit: `column.rs`/scorer/format/reader/Cargo/CI identical | PASS |
| BF-I13 | no historical evidence overwritten | PASS |
| BF-I14 | `BF-T06/T13`; benchmark constants unchanged | PASS |
| BF-I15 | stable/MSRV/coverage/RustFS matrix | PASS |
| BF-I16 | `CI_PENDING` | PENDING |
| BF-I17 | test-only fixes; no production behavior change | PASS |
| BF-I18 | additive commit on the same branch | PASS |
