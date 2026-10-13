# PR 5 Amendment 04 adversarial review

## Plausible still-broken implementations and catching tests

| INV | Still-broken implementation | Catching test / audit |
|---|---|---|
| A4-01 | Allocate then charge (or charge only after parsing the whole entry) | Per-family exact/one-below tests U05/U06/U08/U09/U11/U12/U16/U22/U23; line-referenced audit |
| A4-02 | Mutate the budget before a failed `check_*`, leaving state dirty | `decode_budget::tests::failed_reservation_leaves_budget_unchanged`, `byte_addition_overflow_is_typed_and_unchanged` |
| A4-03 | Rely only on `max_single_allocation` and skip cumulative (or vice versa) | `vector_cumulative_and_single_allocation_limits` (per-vector cap + cumulative), U02 |
| A4-04 | Keep `previous_term: Option<String>` (duplicate copy); or accept nonascending terms | `a4_u07_dictionary_order_utf8_duplicate_truncation`; audit `:199`→`:201` |
| A4-05 | Charge the field vector but not names; or not charge binding strings | `a4_u08_u09_schema_vector_and_name_boundary` (binding variant charges id+version) |
| A4-06 | Create a fresh stored budget per record (siblings no longer share) | `a4_u11_u12_stored_shared_budget` (one-below full fails) |
| A4-07 | Reset the JSON budget per child array/object | `a4_u16_u17_nested_json_array_shared_budget` |
| A4-08 | Change public signatures while adding `*_budgeted` | `a4_u19_u20_public_wrappers_and_ordering`; existing column wrapper tests |
| A4-09 | Call `from_order` after reading both arrays (third allocation) | Remap audit `:152`/`:153` before `:154`/`:158`; `a4_u23` boundary |
| A4-10 | Panic on malformed/truncated input | U07, U10, U18, U26, U27 |
| A4-11 | Regenerate golden to hide an encoder drift | Golden SHA unchanged; `segment_golden` |
| A4-12 | Claim coverage without final-SHA execution | This report + §1 commands |

## Allocation-order evidence

No custom allocator (forbidden by the amendment's STOP rules). Each charged
allocation is preceded by its cumulative reservation, verified by a
line-referenced audit (implementation report §3) plus per-family exact/one-below
boundary tests. The shared-budget tests (U12, U16) detect accidental resets.

## Independent oracle

Expected charges are computed from fixture lengths/`size_of`, never by calling
production budget code; `retained()` is asserted only in unit tests.

## Residual risks

| Risk | Severity | Disposition |
|---|---|---|
| Modeled charge ≠ allocator/RSS | Medium if misrepresented | Documented explicitly |
| `BTreeMap` overhead estimate | Low | Accepted under model |
| `FieldBinding` strings charged (plan premise inaccurate) | Low | Resolved by charging; documented deviation |
| Manifest budget not migrated | Medium for total-container budgeting | Deferred; explicitly out of amendment |
| Each logical decode has its own budget (no whole-segment aggregate) | Medium | Documented; deferred |
| Whole-segment buffering | Existing PR 5 limitation | Out of scope |

No new STOP condition. No unresolved correctness failure.
