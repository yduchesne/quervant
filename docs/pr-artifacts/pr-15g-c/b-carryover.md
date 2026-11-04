# PR 15G-C deferred B test corrections

**Scope:** test-only; no B production or benchmark change.
**Base:** `018fdd768d0898d6709baeb8661998ee1a82947c`

## GC-BR01 — lazy offset remaining-budget boundaries

New tests in `segment::reader::column_geometry_tests`:

- `gc_br01a_stored_exact_lazy_directory_budget`
- `gc_br01b_stored_one_under_lazy_directory_falls_back`
- `gc_br01c_keys_exact_lazy_directory_budget`
- `gc_br01d_keys_one_under_lazy_directory_falls_back`
- `gc_br01e_stored_and_key_directories_coexist_and_release`

Method: admit a cached state first, then hold a separate `MetadataMeter`
pressure reservation so the *remaining* budget is exactly the lazy directory
allowance (or one byte under). This distinguishes lazy-directory admission from
initial verified-state admission. Exact cases assert `Some(true)`, exact retained
charge and repeat parity; one-under cases assert `Some(false)`, no extra charge,
no full-cache publication and repeated fallback parity. Coexistence asserts both
directories can be charged and all reservations release on final state drop.

Result: **5/5 PASS** locally (`target/pr15g-c/preflight/br01.log`).

## GC-BR02 — K=100 direct-operation witness

New tests in `segment::stored::pr15g_b_tests`:

- `gc_br02a_k100_from_128_visits_only_selected`
- `gc_br02b_k100_strided_from_1024_visits_only_selected`
- Existing `gbu15_direct_reads_visit_only_selected_records` remains K=1/K=3.

Results: **2/2 PASS**; exact values, `direct_records()==100`,
`full_scan_records()==0` for both dense-prefix and strided selections.

Logs are under `target/pr15g-c/preflight/`.
