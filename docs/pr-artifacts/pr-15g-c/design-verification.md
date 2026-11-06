# PR 15G-C design verification

**Status:** implementation complete; performance acceptance **FAILED** (see
`performance-qualification.md`). No ad hoc retuning was performed.

## Locked architecture

- `single_term_stream_eligible` is narrower than the existing P4 predicate:
  compiled root single `Term`, one analyzed term, one ordinary ascending sort
  field, no cursor/aggregation/typed leaf/geo/JSON/multi-sort.
- `visit_single_term_sorted_stream_with` performs bounded immutable postings
  passes: full decode/scanned/work/virtual 16/48/64 admission and BM25 validation
  for every effective-live match; then releases all segment charges and emits
  every effective-live candidate into the existing bounded heap admission.
- `admit_candidate` is the single shared candidate-key/tuple/heap/duplicate/
  K+1/cursor admission routine for both legacy scored items and C stream items.
- C late-computes the returned BM25 value only after a candidate qualifies for
  insertion/replacement; first-stage validation still checks every match.
- No format, writer, public API, score formula, dependency or frozen benchmark
  input changed.

## Invariant map

| ID | Witness |
|---|---|
| GC-I01 eligibility | `gc_u01_u02_u03_u05_eligibility_gate`, cursor/ineligible integration |
| GC-I02 validation order | existing unified validation/cursor tests; C gate runs after compile |
| GC-I03 exact counts | `gc_u11_u13_u22_stream_matches_legacy_and_counts_all_matches` |
| GC-I04 score/key/tuple parity | `gc_u11_u13_u22…`, `gc_i01`/`gc_i02` |
| GC-I05 work/bytes parity | existing `phase4_u10_u11_u12_work_charge_parity`; C uses same constants |
| GC-I06 bounded winners | test-only stream counters + K=1/10/100 checks |
| GC-I07 nonwinner score validation | stage one scores every match before emission |
| GC-I08 fallback shapes | eligibility test + `gc_i03_i04_fallback_and_cursor_pages` |
| GC-I09 cancellation/cleanup | existing `phase4_u14_cancellation_unwinds_cleanly` now exercises C, plus RustFS/fault suites |
| GC-I10 duplicate guard | shared admission duplicate check |
| GC-I11 PIT isolation | `gc_i07_old_pit_isolated_from_new_generation` |
| GC-I12 no wire change | identical index/corpus digests in benchmark |
| GC-I13/14 B carryover | `gc_br01a–e`, `gc_br02a–c` |
| GC-I15 performance provenance | C runner and artifacts |
| GC-I16 charge release | segment ledger finish before second pass; cancellation tests |

## Residual risk

The C path is functionally correct but measured slower than the B baseline on
this host/campaign. No causal profiling was performed, and no tuning was made
after qualification. Performance acceptance is the reviewer's decision.
