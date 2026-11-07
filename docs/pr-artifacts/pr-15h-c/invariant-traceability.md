# PR 15H-C — invariant traceability

The C candidate was implemented and fully tested at `fee4edb`, then
performance-rejected and rolled back to `e8744d3`. The table records the
executed evidence and the final source state.

| ID | Invariant | Evidence | Candidate | Final source |
|---|---|---|---|---|
| HC-I01 | Eligibility exactly `keyword_sort_late_eligible` | B eligibility tests unchanged | PASS | restored |
| HC-I02 | `total_hits` once per match before key lookup | loop keeps checked increment; `c_u01/u04` | PASS | restored |
| HC-I03 | Borrow from same full-key decoder | `cached_doc_key_ref` over `reader.doc_keys()`; `c_u09` | PASS | restored |
| HC-I04 | Zero/singleton preservation | `c_u01_u02_u03_zero_and_singleton_routing` | PASS | restored |
| HC-I05 | Key error before sort decode | loop order; `c_u09/u10` | PASS | restored |
| HC-I06 | Exact out-of-range error | `c_u09_u10_u11_cached_key_boundaries` | PASS | restored |
| HC-I07 | No per-loser ownership | `c_u04/u05` owned admission <= K+1 | PASS | restored |
| HC-I08 | One clone on fallback | `c_u16_legacy_decode_fallback_owns_one_key` | PASS | restored |
| HC-I09 | Byte-exact key equality/order | B/C ordering and tie tests | PASS | restored |
| HC-I10 | Missing/null/empty semantics | `c_u06_u07_u08_u18...` | PASS | restored |
| HC-I11 | Exact counts/cursor | `c_u04/u05`, `c_u18`, B integration | PASS | restored |
| HC-I12 | Score bits unchanged | `c_u04/u05/u06` vs `And([Term])` | PASS | restored |
| HC-I13 | Duplicate check on losers | `c_u15_duplicate_retained_key_before_competitiveness` | PASS | restored |
| HC-I14 | Typed corruption precedence | B fixup malformed loser + column tests | PASS | restored |
| HC-I15 | Charges/heap ordering unchanged | unchanged `heap_admit_candidate`; B/phase4 tests | PASS | restored |
| HC-I16 | Budgets/cancellation unchanged | unchanged meter/collect loop; existing tests | PASS | restored |
| HC-I17 | No borrowed reference escapes | `&DocumentKey` synchronous; Rust borrow checker | PASS | restored |
| HC-I18 | Ineligible shapes legacy | B `b_u04/u05`, `c_u06` cursor fallback | PASS | restored |
| HC-I19 | PIT/live filtering unchanged | B `b_i03`; C changes no snapshot state | PASS | restored |
| HC-I20 | No new cache/global state | only segment-local `Rc` borrow | PASS | restored |
| HC-I21 | No wire/index/Cargo/CI change | protected blobs identical; equal index digests | PASS | PASS |
| HC-I22 | B evidence immutable | B files and `target/pr15h-b` untouched | PASS | PASS |
| HC-I23 | Same host/corpus/index/oracle | sealed C manifest; equal index digests | PASS | n/a |
| HC-I24 | Absolute-ms acceptance | C gates 2/1/−1/−2 ms | PASS | n/a |
| HC-I25 | Rejection restores exact A | `git diff --quiet e8744d3 HEAD -- unified.rs` | n/a | PASS |
| HC-I26 | 15G-C history untouched | no reference/implementation resurrected | PASS | PASS |

## Correctness matrix (executed at candidate)

| ID | Test | Result |
|---|---|---|
| HC-U01–U03 | `c_u01_u02_u03_zero_and_singleton_routing` | PASS |
| HC-U04/U05/U12/U13 | `c_u04_u05_u12_u13_large_k_bounds_and_parity` (50K, K10/K100) | PASS |
| HC-U06–U08/U18 | `c_u06_u07_u08_u18_ordering_and_cursor` | PASS |
| HC-U09–U11 | `c_u09_u10_u11_cached_key_boundaries` | PASS |
| HC-U15 | `c_u15_duplicate_retained_key_before_competitiveness` | PASS |
| HC-U16 | `c_u16_legacy_decode_fallback_owns_one_key` | PASS |
| HC-U14 | B fixup malformed losing UTF-8 test | PASS |
| HC-U17 | B comparator incompatible-retained fallback | PASS |
| HC-U19 | B integration PIT/two-segment | PASS |
| HC-U20 | B ineligible-shape unit tests | PASS |
| HC-U21 | Existing corruption/container tests | PASS |
| HC-U22 | Existing budget/cancellation suites | PASS |

These C-only tests were removed mechanically by restoring the baseline
`unified.rs`; their evidence is preserved here.
