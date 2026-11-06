# PR 15H-B — preflight

**Branch:** `dev/pr15h-a-linear-term-candidates` (required literal, continued in place)
**Baseline HEAD / source pin:** `6e47eed3f35a5fad8db6dab24c66f386567e95c0`
**Accepted search:** identical to `7a136f7` / `ddcbe778`
**Tooling-only commit (`HB_TOOLING_SHA`):** `79593314aa0525a1bb7d5f30c900a70e890e728a`
**Candidate SHA:** `ae7e416a7d4d8a0ce179b64a15cafc2cb104f85e`

## 1. Branch and source gate

| Check | Result |
|---|---|
| `git branch --show-current` | `dev/pr15h-a-linear-term-candidates` |
| `git rev-parse HEAD` at preflight | `6e47eed3…` |
| `git status --porcelain` | empty |
| `git diff --quiet 7a136f7… 6e47eed… -- crates/quervant-core/src/search` | exit 0 |
| Ancestry | baseline descends from accepted `7a136f7` |

No new feature branch was created (HB-D01). Historical A/A2/A3 evidence was
preserved and not executed (HB-D04). No existing B-like fast path was found
(HB-D05).

## 2. Toolchain / environment

| Fact | Value |
|---|---|
| `rustc` | `1.98.1 (48a229cea 2026-09-01)` |
| `cargo` | `1.98.1 (797e8a9bc 2026-08-05)` |
| MSRV | `1.85.0 (d73d2caf9 2024-12-31)` |
| OS / kernel | WSL2 `6.18.33.2-microsoft-standard-WSL2` |
| Measurement filesystem | native ext4 under the WSL distribution |
| `perf` | not required (the plan does not require perf counters) |

## 3. Frozen experiment (recorded before baseline)

| Item | Value |
|---|---|
| Lanes | P1 common/100K/K100, P2 common/100K/K10, P3 medium/100K/K100, G1 common/10K/K100, G2 rare/100K/K100, G3 absent/100K/K100 |
| Baseline | 3 trials × 5 warmups + 20 samples |
| Paired | 4 mirrored blocks `A,B / B,A / B,A / A,B` = 8 slots |
| Primary gate | median `A−B` ≥ 5.000 ms, ≥3/4 blocks ≥ 2.000 ms, no block < −3.000 ms |
| P3 | median > −3.000 ms, fewer than 3/4 blocks < −3.000 ms |
| G1 | median > −2.000 ms |
| G2/G3 | each median > −1.000 ms |
| Confirmation | one bounded extra campaign only under the literal §9.3 shape (unreachable under the nearest-rank lower median; encoded and tested) |

## 4. Pre-implementation counterexamples

| Counterexample | Mapping |
|---|---|
| Invalid UTF-8 on a losing keyword | `segment::column::b_keyword_view_tests::b_u14_invalid_utf8_rejected` |
| Missing vs explicit null vs empty multi | `b_u06_u16_missing_null_value_and_multi_fallback`; unified `b_u06_u09_u10_missing_null_tie_ordering` |
| Equal keyword, different keys, ASC and DESC | unified `b_u06_u09_u10_missing_null_tie_ordering` |
| Decode budget rejection | `b_keyword_view_tests::b_u18_decode_budget_rejected` |
| `STATE_MULTI` / non-single cardinality | `b_u06_u16_…` returns `LegacyDecode` |
| Duplicate retained key on a loser | `hip_admit` duplicate check; integration duplicate-key corruption path |
| Replacement old+new peak | existing `heap_preflight_*` tests + extracted `heap_admit_candidate` |
| `top_k=1` heap limit 2 and cursor replay | unified `b_u04_u05…` cursor case; integration `b_i04_cursor_followup` |
| Key decode error before column error | fast path resolves key before `keyword_sort_view`; integration corruption |
| Batch/retained/aggregation/multi/typed | unified `b_u04_u05_u11_u16_ineligible_shapes` |
| Multi selector Min/Max | integration `b_i08_multi_and_typed_fallback` |

## 5. Source scope

Allowed modified production files: `segment/column.rs`, `search/typed_compare.rs`,
`search/unified.rs`; new integration test `tests/pr15h_b_sort_materialization.rs`;
new `benchmarks/pr15h_b/`; B evidence docs. No scorer, `execute.rs`, codec format,
manifest, Cargo, CI, storage or public API change (HB-D68).
