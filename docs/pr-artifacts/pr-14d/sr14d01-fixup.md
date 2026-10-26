# SR-14D-01 — admission-before-winner-materialization fixup

**Status:** corrected and locally verified; PR #64 remains unmerged and PR 14
remains **IN PROGRESS / NOT ACCEPTED**. Final-SHA CI and independent review are
still required.

| Item | Value |
|---|---|
| Baseline (PR #64 head before fixup) | `9f9371c2e6e8923eecfedee39de2f4430e52d15f` |
| Fixup commits | implementation + evidence commits on `dev/pr14d-json-sort-memory-governance` |
| Ancestry | `2cb91be` (PR #62 merge) is an ancestor |
| Provider | pinned `rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`, health-checked |

## 1. Defect and correction

`json_sort_value` called `node_to_field_value(&occurrence.node)` for **every**
matching candidate before any winner reservation. `node_to_field_value` maps
`JsonNode::String(text)` to `FieldValue::Keyword(text.clone())`, so an owned
string allocation could occur before `BatchMemoryBytes` admission — and losing
string candidates were cloned too.

Correction (A01–A12):

- Added private `json_sort_scalar_rank`, `json_sort_scalar_cmp` and
  `json_sort_node_owned_bytes`; candidates are compared as **borrowed**
  `&JsonNode` values with canonical ranks
  (Bool 0, I64 1, U64 2, F64 3, String 5), `f64::total_cmp`, and UTF-8 byte
  ordering.
- Winner selection keeps `Option<&JsonNode>`; strict `<`/`>` preserves
  first-winner ties.
- `materialize_json_sort_winner` reserves `JsonSortBuffer::Winner` bytes first,
  then calls `node_to_field_value` exactly once. A test-only counter
  (`winner_probe`, `#[cfg(test)]`) increments only after admission.
- The occurrence buffer remains charged and alive during selection; the
  occurrence reservation is released only after the buffer is dropped, and the
  original typed error is preserved on cleanup paths.
- Caller handoff (`sort_scratch.finish()`) is unchanged; no second charge, no
  new meter, no public API/format change.

Code locations: `crates/quervant-core/src/search/typed.rs`
(`json_sort_value`, comparator/bytes helpers, `materialize_json_sort_winner`);
`crates/quervant-core/src/segment/mod.rs` now re-exports the already crate-private
`JsonNode` for the comparator.

## 2. F01–F16 evidence

| ID | Evidence | Result |
|---|---|---|
| F01 | unit `json_sort_winner_tests::f01_f03_borrowed_comparator_matches_canonical` — all 16×16 node pairs, both orders, parity with `canonical_scalar_cmp`; `f01_non_scalar_nodes_are_not_comparable` | PASS |
| F02 | same unit test includes `-0.0` vs `0.0` and ±finite f64 via `total_cmp` parity | PASS |
| F03 | same unit test includes empty, prefix (`a`/`ab`), Unicode (`é`) and 64-byte strings | PASS |
| F04 | `pr14d_json_sort_memory::d03_mixed_scalar_min_max_order`, `d08_multivalue_min_max_and_shape_handling` | PASS |
| F05 | `f05_f06_string_winner_exact_and_one_under` — 128-string winner at runtime-binary-searched exact limit (unified + pinned) | PASS |
| F06 | same test — exact−1 → typed `BudgetExceeded(BatchMemoryBytes)` (unified + pinned) | PASS |
| F07 | unit `f07_winner_conversion_runs_only_after_admission` — counter 0 on rejected reservation, exactly 1 after admitted conversion | PASS |
| F08 | `f08_large_losing_string_is_not_the_min_winner` — Min picks numeric 1 over a 4 KiB string; Max picks the string and the threshold is ≥4,096 B higher | PASS |
| F09 | `f09_replacement_sequence_keeps_strict_winner` — `ccc/aaa/bbb` Min/Max winners and tie order | PASS |
| F10 | `f10_two_json_sort_fields_and_sibling_isolation` — two JSON sort fields, S/F/S at a shared cumulative budget | PASS |
| F11 | `f11_cancellation_mid_scan_releases_meter` — cancellation after 3 polls is typed; retry succeeds | PASS |
| F12 | unit `t09_legacy_extraction_rejects_before_retained_growth`; legacy fallback semantics unchanged in PR 11 legacy suites (D16). No dedicated legacy-sort integration test exists; recorded as a coverage limitation | PASS (unit) / limitation noted |
| F13 | `d04_typed_unified_and_pinned_parity` now resumes the pinned page-2 cursor (`c`, terminal) | PASS |
| F14 | `pr14b_json_memory` post-fix: thresholds 387 / 45,726 / 1,462,302; peaks 33,547 / 110,392 / 2,518,968; cancel 7,397 — unchanged by this fixup, not RSS | PASS |
| F15 | `d07_historical_fixture_digest_and_corruption` + `b18_b19` regression | PASS |
| F16 | unit `t02`, `t05`, `t08`, `t09`; failure-path cleanup in `json_sort_value` and full-suite regression | PASS |

## 3. Validation (fixup head)

| Gate | Result |
|---|---|
| `cargo fmt --all -- --check` / MSRV fmt | PASS |
| Clippy default/all-features, stable + MSRV | PASS |
| `cargo test -p quervant-core --lib --all-features` | 759 passed, 1 ignored |
| `cargo test -p quervant-core --all-features --test pr14d_json_sort_memory` | 13 passed |
| `cargo test -p quervant-core --all-features --test pr14b_json_memory` | 1 passed, 1 ignored |
| Workspace default tests (stable + MSRV) | 2044 passed, 0 failed, 10 ignored |
| Workspace all-features tests (stable + MSRV) | 2048 passed, 0 failed, 73 ignored |
| Coverage | **91.29 % lines** (48,236 lines, 4,200 missed); regions 91.84 %; functions 87.36 % |
| `cargo doc`, `cargo bench --no-run`, 33 script tests, validator self-test | PASS |
| `git diff --check` | PASS |

## 4. Real-provider re-run (pinned RustFS 1.0.1)

- 13 `pr14_storage_vertical` real symbols (11 pre-existing + D11 + D12): PASS.
- `pr14_storage_faults` F01–F09/F10, 10 unique-prefix iterations each: PASS.
- `pr13_remote_proxy` h06–h12: 7 PASS.
- `pr13_crash_rustfs` k01–k05: 5 PASS.
- `quervant-objectstore` `pr13_s3_rustfs` 8 and `pr13_proxy_rustfs` 5: PASS.
- `pr13_remote` real 3, `pr13_oracle` real 1, `pr13_oracle_geo` real 1: PASS.

No fake substituted for a real-boundary case; credentials were not logged; the
provider was stopped after the run.

## 5. Failure classification

| Item | Classification |
|---|---|
| Original defect (pre-reservation clone) | Feature/admission defect in PR #64; corrected here |
| Original PR 14D test-expectation issues (D04 tie order, D05 cumulative retained bytes, D12 `insert` vs upsert) | Test-harness/expectation errors, corrected before this fixup; not product defects |
| New failures introduced by this fixup | None observed |
| Flaky results | None observed |
| Environment/harness failures | None in the fixup run |

## 6. Residual risk and limits

- The logical meter is a reservation ledger, not RSS; B20/B21 remains an
  allocator-window observation.
- One decoded indexed occurrence and the legacy walker's path/stack remain
  bounded pre-admission transients (unchanged, documented).
- F12 has unit-level legacy evidence and existing PR 11 legacy suites, not a
  dedicated legacy JSON-sort integration fixture; this is a coverage limitation,
  not a new exception.
- PR 14 still has other blocked reconciliation rows and the qualified P4
  benchmark obligation; this fixup does not address them.

## 7. CI

`gh` authentication remains invalid in this environment, so PR #64 checks cannot
be read and no new CI run was observed. Status: **CI NOT VERIFIED**; no merge is
authorized.
