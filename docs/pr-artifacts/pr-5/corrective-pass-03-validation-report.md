# PR 5 corrective pass 03 validation report

> Final tree (pre-commit working state; committed SHA recorded in the branch
> log). `cargo +1.85.0` (`rustc 1.85.0 (4d91de4e4 2025-02-17)`) and stable
> `1.99.0`. No merge.

## 1. Mandatory commands

| Gate | Exact command | Exit | Result |
|---|---|---|---|
| Check | `cargo +1.85.0 check --workspace --all-targets` | 0 | PASS |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS — **749 passed / 0 failed / 2 ignored** |
| Tests (stable) | `cargo test --workspace --all-targets` | 0 | PASS — **749 passed / 0 failed / 2 ignored** |
| Format | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| Lint (MSRV) | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Lint (stable) | `cargo clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | 0 | PASS |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS — **85.18% line / 89.53% function / 92.53% region** |
| Whitespace | `git diff --check` | 0 | clean |

Both toolchains are reported per `AGENTS.md` (CI uses stable; a clean MSRV
Clippy does not guarantee clean stable Clippy).

The 2 ignored tests are the pre-existing RustFS SKIP and the golden regeneration
helper; no new ignored tests.

## 2. C7 test execution

`cargo +1.85.0 test -p trawler-core --test segment_corrective_pass03` →
**11 passed / 0 failed**.

| Test ID | Rust test | Result |
|---|---|---|
| C7-INV01 / U01 | `c7_u01_empty_manifest_zero_segment_charge` | PASS |
| C7-INV02 / U03–U07 | `c7_stage_prefixes_reserve_before_allocating` (ID, key, index prefixes) | PASS |
| C7-INV03 / U08–U11 | `c7_stage_prefixes_reserve_before_allocating` (per-segment features) | PASS |
| C7-INV04 / U12–U14 | `c7_stage_prefixes_reserve_before_allocating` (manifest features) | PASS |
| C7-INV05 / U02 | `c7_u02_exact_full_model_and_one_below` | PASS |
| C7-INV06 / U15–U16 | `c7_u15_nonadjacent_duplicate_keys_rejected`, `c7_u16_unordered_ids_rejected` | PASS |
| C7-INV07 / U17 | `c7_u17_independent_oracle_and_round_trip` | PASS |
| C7-INV08 / U18–U21 | `c7_u18_invalid_utf8_rejected`, `c7_u19_truncated_rejected`, `c7_u20_unknown_required_and_unsorted_features`, `c7_u21_large_count_rejected_before_alloc` | PASS |
| C7-INV09 / I04, G01–G02 | pass-02 `c6_i01`/`c6_i02`; golden `p5_g02`; unchanged golden SHA | PASS |
| C7-INV10 / I05 | `c7_i05_failed_then_valid_decode_is_independent` | PASS |
| C7-INV11 / U22 | `retained_bytes` documentation audit | PASS (documentation) |
| C7-INV12 / Q01–Q07 | mandatory commands above | PASS |

The stage-prefix test asserts that a budget one below each cumulative prefix
fails with `LimitExceeded.requested == that prefix`, exercising every charged
reservation stage. Allocation ordering itself is evidenced by the source-level
audit (custom allocator forbidden by the plan's STOP rules).

## 3. Independent oracle

`charge_components`/`oracle_charge` compute the expected charge from fixture
inputs (lengths, `size_of`), **not** from production `retained_bytes()`;
`retained_bytes()` is asserted only as a second check (`c7_u17`,
`c7_i04`). The `debug_assert_eq!` in `decode` cross-checks budget vs
`retained_bytes()` on every successful decode.

## 4. Golden fixture

`crates/trawler-core/tests/fixtures/segment/golden.seg`
`sha256 = ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`
— **unchanged**; not regenerated.

## 5. Failure classification

No mandatory gate failed. No introduced regression, feature defect, flaky
failure, or environment/harness failure. Pre-existing `docs/TESTING.md` markers
and the RustFS SKIP remain out of scope.

## 6. Limitations

- Charge is a deterministic model, not heap/RSS/allocator capacity.
- No allocation-count red (custom allocator prohibited); source audit provided.
- Schema and manifest budgets remain independent.
