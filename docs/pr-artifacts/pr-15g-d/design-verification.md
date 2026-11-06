# PR 15G-D design verification

## D1 — dictionary-miss segment bypass

- Eligibility derives once from the compiled plan and `single_term_postings_eligible`.
- Additional D1 restriction: no geo-distance or JSON-path sort.
- Per segment, before `ColumnAccess::open`, a missing dictionary entry triggers
  `charge_absent_exact_term_segment`: existing ledger begin/finish, cancellation,
  and `effective_live_examination_count` + `charge_lexical`.
- A present dictionary entry, including all-dead postings, takes the original
  decode/validation path.
- No `charge_scanned` or virtual 16/48/64 reservations are fabricated for a miss.
- Upstream validation, schema, stats, cursor and reader-state checks remain.

## D2 — direct positive membership

- Only the P4-eligible `is_match` closure returns `true`; executor's runtime
  guard and existing postings decode remain.
- Matched set, score map, vector, key/sort/heap, BM25, total_hits, projection and
  cursor are unchanged.
- Test-only `Term` membership-search counter proves the redundant binary search
  is absent on the direct path and present on the legacy `And([Term])` control.

## Invariants

| Invariant | Witness |
|---|---|
| GD-I01 compiled proof | eligibility tests; `single_term_postings_eligible` unchanged |
| GD-I02 miss is proven | D1 miss vs present/all-dead tests |
| GD-I03 validation precedence | invalid sort/cursor/query tests |
| GD-I04 work charge | absent work-cap exact/one-below test |
| GD-I05 ledger/batch | existing ledger/RAII + batch tests |
| GD-I06 direct true | D2 membership-search counter |
| GD-I07 no scoring change | C? replaced; legacy differential score bits |
| GD-I08 fallback | Boolean/typed/heo/JSON/cursor regressions |
| GD-I09 corruption | existing corrupt posting tests |
| GD-I10 PIT | integration old/new generation |
| GD-I11 sort/projection | differential parity |
| GD-I12 cancellation | existing cancellation tests |
| GD-I13 format | no protected changes |
| GD-I14 real boundaries | FsDirectory + pinned RustFS |
| GD-I15 performance | D1/D2 frozen campaigns |
| GD-I16 B preservation | B carryover rerun |

## Rejected alternatives

No C streaming revival, no second postings pass, no new collector, no BM25
change, no eligibility broadening, no skipped live work.
