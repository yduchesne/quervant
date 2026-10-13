# PR 5 corrective adversarial self-review

For each corrective invariant, a plausible *still-incorrect* implementation is
named with the test that would catch it. This supplements the C5 test matrix.

| INV | Plausible surviving incorrect implementation | Catching test |
|---|---|---|
| C5-INV01 | Preflight only `max_decoded_entries` (count) and not `count × size_of`/retained bytes, so a huge count within the entry budget still allocates | `c5_u02_dictionary_field_count_is_preflighted`, `c5_stored_budget_exceeded_is_typed`, `c5_u39_schema_field_count_is_preflighted` |
| C5-INV02 | Decode valid dictionaries but reject an at-limit dictionary by off-by-one | `c5_u01_dictionary_valid_at_limit_still_decodes` |
| C5-INV03 | Validate only `first_doc`/`rows` and not per-block state/value extents, allowing a block to alias the next column | `c5_u07`, `c5_u09`, `c5_u10`, `c5_u11`, `c5_column_geometry_branch_coverage`, `c5_reader_rejects_forged_columns_and_coherence` |
| C5-INV04 | Recompute `data_base` per value incorrectly (double-count `dir_len`) so doc N reads the wrong block | `c5_i01_valid_columns_still_read_all_docs`, `p5_a23` (`blocks_read == 12`) |
| C5-INV05 | Negotiate container features but skip per-segment `required_features` | `c5_u20_manifest_unknown_required_segment_feature_fails_closed`, `c5_u19` |
| C5-INV06 | Reserve `segment_count` before bounds check; or keep O(n²) duplicate-key scan | `c5_u16`, `manifest_feature_order_and_schema_length_errors` (duplicate ids) |
| C5-INV07 | Keep state-before-type order or omit the type tag for missing/null | `p5_g01_group_key_wire_bytes_match_approved_f07`, `p5_u27_group_keys_do_not_collide` |
| C5-INV08 | Bound entry count but not the `Rc<Vec<StoredRecord>>` allocation / retained strings | `c5_u31`, `c5_u32` |
| C5-INV09 | Add preflights to dictionary alone, leaving `schema`/`stored`/`remap`/`geo`/`json` unbounded | `c5_u37`, `c5_u38`, `c5_u39`, `c5_u41`, `c5_stored_truncation_and_count_mismatch` |
| C5-INV10 | Validate geometry but panic on truncated block directory or overflow arithmetic | `c5_p03_truncation_never_panics_and_fails_typed`, mutation battery |
| C5-INV11 | "Fix" a decoder by changing an encoded byte / golden fixture | Golden SHA `ebb078…dae979` unchanged; `p5_g02` |
| C5-INV12 | Add eager validation that re-reads remote objects or changes `Directory` usage | `p5_i01`, `p5_i06`, `c5_reader_rejects_forged_columns_and_coherence` |

## Residual risks (disclosed)

| Risk | Severity | Disposition |
|---|---|---|
| `check_alloc` is a conservative upper bound, not exact allocator accounting | Low | Accepted; prevents amplification, does not claim exactness |
| Coverage margin 85.16% | Low | Accepted; floor met, future changes should add tests |
| Whole-file read bounded by `accepted_segment_bytes` (1 GiB default) rather than `max_single_allocation` | Low | Accepted and documented; full envelope verification requires all bytes |
| Dictionary `doc_freq` vs posting count checked lazily at `postings()` | Low | Accepted; extents checked eagerly at open |
| Group-key API conformance correction | Low | Isolated to `column.rs` + tests; no persisted-byte impact; flagged for review |
| No authenticated selective range reads | Medium | Deferred; separate human decision (unchanged from approved F02) |
| Stored retrieval is not O(1) on first access | Low | Documented; bounded eager decode |

No new STOP condition arose. No unresolved correctness failure.
