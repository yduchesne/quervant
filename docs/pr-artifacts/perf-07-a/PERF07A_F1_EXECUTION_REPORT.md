# PERF-07-A-F1 execution report

**Disposition:** `PERF07_A_F1_LOCAL_ACCEPTANCE_PASS_CI_PENDING`
**Repository:** `yduchesne/quervant`
**Branch:** `dev/perf-07-a`
**Existing PR:** [#135](https://github.com/yduchesne/quervant/pull/135) — open, unmerged, ready (not draft) at admission
**Correctness only.** No production code change, no benchmark, no timing acquisition, no merge, no stage advance.

## 1. Identities and admission

| Item | Value |
|---|---|
| BASE / current `origin/main` | `c9ca7975ab6f29fc4fe1fac65951cede3799cb8c` (tree `0ead7efb356d66751c801b12a27147e281ae2a5e`) |
| Original RED | `06898baf9a796cddf5a03033652df4d2a53e150a` (tree `9ca4f8ed5cf311dbca24f9e50848c24e69c74a5a`) |
| Original TESTED | `29fe4a2d596b3df43cd29f18722983098d664a47` (tree `5828846d3dfcc3a4742848099c873e185fb9a7aa`) |
| F1_START / reviewed PR head | `f7437954c87e070ffc5df15bbc4d80c826ace3e7` (tree `aecc07cc6a1bbd6de7b73a557f2a86b9297feeee`) |
| F1_TESTED | `1f9940844f6219cf31586ebfd6e470abcca74599` (tree `3dd9d651fdde22f4babe56aced78f0d1293994e1`) |
| F1 plan SHA-256 (committed readable copy) | `55d41d7030da935217e5f251d7ac458572129b201086e9b11641857fe0e934d9` |
| F1 plan verbatim supplied bytes | `fe757b491f1220c3643437132904655c05fcd84d9196420658e9a1b21d070225` (82,383 bytes; lossless base64 in evidence) |
| Original plan SHA-256 | `5a66c42cb00ed8fde2118ef3e55145603b44a4a3ca13de9a6a1f65b0670ed7b1` (blob `bac21b375bb93deb34cccb29423369125cae46e9`) |
| Prior CI on F1_START | run `46102649763`, `pull_request`, `success`, all five jobs success |
| Local clean state | tracked tree clean at admission and at F1_TESTED |
| Preserved untracked | `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` (never staged) |

Ancestry and scope were verified: BASE ancestor of RED, RED ancestor of A_TESTED, A_TESTED ancestor of F1_START; `BASE..A_TESTED` is exactly the four executable paths; `A_TESTED..F1_START` is docs-only. All seven F1_START source anchors matched. The original evidence manifest validated 18/18 entries. The supplied F1 plan text is stored at [PERF07A_F1_DETAILED_FIXUP_PLAN.md](PERF07A_F1_DETAILED_FIXUP_PLAN.md) with exactly one formatting normalization: five header lines had Markdown hard-break trailing double-spaces stripped so the required `git diff --check` stays clean. No substantive text changed. The exact supplied bytes are preserved losslessly at [PERF07A_F1_DETAILED_FIXUP_PLAN.md.verbatim.b64](evidence/f1/PERF07A_F1_DETAILED_FIXUP_PLAN.md.verbatim.b64), with SHA-256 `fe757b49…` and 82,383 bytes.

## 2. Source scope and reconciliation

**Production code changed: NO.** Only five existing test-function bodies changed: `perf07a_r05_post_scan_finalize_refusal_no_rescan`, `perf07a_r07_selection_order_and_singleton_boundary`, `perf07a_u02_projection_first_use_and_zero_metadata`, `perf07a_u03_projection_selected_order_and_parity`, and `perf07a_rf01_real_rustfs_multi_hit_cold_and_warm_projection`.

`git diff --name-only F1_START..F1_TESTED` is exactly:
- `crates/quervant-core/src/segment/reader.rs`
- `crates/quervant-core/src/search/unified.rs`
- `crates/quervant-core/tests/pr15g_b_rustfs.rs`

`crates/quervant-core/tests/perf06_c2_physical.rs` is unchanged. The source-freeze checker masked the five allowed function bodies and reported:

```
PASS outside permitted function bodies: crates/quervant-core/src/segment/reader.rs
PASS outside permitted function bodies: crates/quervant-core/src/search/unified.rs
PASS outside permitted function bodies: crates/quervant-core/tests/pr15g_b_rustfs.rs
PASS exact test-only path scope
```

`git diff --check F1_START..F1_TESTED` and `git diff --check BASE..F1_TESTED -- crates/` both pass. Each diff hunk was manually inspected and corresponds only to the literal prescribed test changes.

Correctness worksheet mapping (all confirmed against pinned source):
- R05 detects a cached false comparison after optional-directory refusal with a corrected retry on the same sticky-`None` owner.
- R07 requires the large invalid singleton to return range without scanning rows, while N=1023 and the late-corrupt rows stay `InvalidUtf8`.
- U03 both permutations decide mismatch vs range before any dedup/skip, and prepared failures prove parity precedes STORED and ledger admission.
- U03 recovery on the same snapshot and same ledger proves no poisoned request-local state or charged ledger survives a failure.
- RF01 full `UnifiedResponse` equality proves cursor/generation/view identity as well as key order.

## 3. Historical corrections and immutable RED replay

- Original RED command: HEAD `c9ca7975…`, HEAD tree `0ead7efb…`, 2026-11-28T02:28:33Z–02:28:50Z, exit 101.
- RED commit created 2026-11-28T02:28:55Z (`06898baf…`).
- **Provenance limitation:** no contemporaneous precommit dirty/staged tree identity was recorded in the original scratch; equivalence to the later RED commit cannot be established retrospectively. The historical failure itself is real (named U01 full-owned assertion, 1100 vs 0, `full_decodes=1`).
- **Immutable replay (separate evidence, not a historical receipt replacement):** detached worktree at RED, clean tracked tree. `cargo +1.98.1 test -p quervant-core --lib perf07a_u01_projection_prepared_offsets_no_full_keys -- --nocapture` exited 101: exactly one selected test, `0 passed; 1 failed`, named `PERF07-A U01 full owned keys (K10-a)`, left 1100/right 0, witnessed `full_decodes=1`. Raw log: [f1-red-replay.log](evidence/f1/f1-red-replay.log). The worktree was removed without force; RED was not modified.
- **Historical count recovered:** original `qa-test-198` log (SHA-256 `5c62b31f5ec7a10819bfdcc59cb6287e2f7ebfd4992ce1331b30496977e42aba`) shows the `quervant-core` library harness `running 1234 tests` and `test result: ok. 1233 passed; 0 failed; 1 ignored`. The original table’s `1234 passed` was a reporting error. Details: [historical-count-excerpt.txt.b64](evidence/f1/historical-count-excerpt.txt.b64); RED attribution: [historical-red-attribution.txt.b64](evidence/f1/historical-red-attribution.txt.b64).

## 4. Repaired row evidence (F1_TESTED)

### R05 — corrected recovery on the same unavailable owner (4 calls)

| Case | Injected parity | Corrected retry | Counts | Owned | Cell | Ledger/charge |
|---|---|---|---|---|---|---|
| match | true | true | scans 1, rows 4, selection rows 3, all else 0, stored 0 | 0 | `Some(false)`, pointer none | budget unchanged |
| mismatch | false | true | scans 1, rows 4, selection rows 3, all else 0, stored 0 | 0 | `Some(false)`, pointer none | budget unchanged |

`rows_done == 4`; `budget.used() == 0` after dropping owners. Marker: `PERF07-A F1 R05 case=… corrected_parity=true scan_rows=4/4 sticky_none=true rows=2`; the `INJECTED_POST_SCAN_MEASUREMENT` label is retained and is not a real allocator incident.

### R07 — exclusive singleton boundary (35 total calls; 8 boundary rows)

| N | Case | Mode | Outcome | scans | scan_rows | selection rows | Cell |
|---:|---|---|---|---:|---:|---:|---|
| 1023 | invalid-id | unmetered | `InvalidUtf8{"doc key"}` | 1 | 1022 | 0 | none |
| 1023 | invalid-id | admitted | `InvalidUtf8{"doc key"}` | 1 | 1022 | 0 | `None` |
| 1023 | late-corrupt | unmetered | `InvalidUtf8{"doc key"}` | 1 | 1022 | 1 | none |
| 1023 | late-corrupt | admitted | `InvalidUtf8{"doc key"}` | 1 | 1022 | 1 | `Some(false)` |
| 1024 | invalid-id | unmetered | `Corrupt{"doc keys","doc id out of range"}` | 1 | 0 | 0 | none |
| 1024 | invalid-id | admitted | `Corrupt{"doc keys","doc id out of range"}` | 1 | 0 | 0 | `None` |
| 1024 | late-corrupt | unmetered | `InvalidUtf8{"doc key"}` | 1 | 1023 | 1 | none |
| 1024 | late-corrupt | admitted | `InvalidUtf8{"doc key"}` | 1 | 1023 | 1 | `Some(false)` |

All unspecified counters zero, `selected_keys_owned()==0`, no full cache, no offset pointer; admitted metadata unchanged; budgets released to zero. The S0–S7 table (24 calls), empty segment (2), and corrupt empty selection (1) are unchanged.

### U02 — five actual projector calls

Labels: `first-use`, `warm-use`, `zero-a`, `zero-b`, `empty-selection`. `completed == 5`; marker `PERF07-A U02 rows=5`. All original count/field/guard/metadata assertions retained.

### U03 — 19 completed calls (3 controls + 8 failures + 8 recoveries)

| Case | Route | Literal error | selection rows / offset reads | Owned | Ledger | STORED |
|---|---|---|---:|---:|---:|---:|
| wrong-first | unmetered | mismatch | 3 | 0 | 0 | 0 |
| wrong-later | unmetered | mismatch | 3 | 0 | 0 | 0 |
| mismatch-then-invalid | unmetered | mismatch | 1 | 0 | 0 | 0 |
| invalid-then-mismatch | unmetered | range | 1 | 0 | 0 | 0 |
| wrong-first | prepared | mismatch | 1 | 1 | 0 | 0 |
| wrong-later | prepared | mismatch | 3 | 3 | 0 | 0 |
| mismatch-then-invalid | prepared | mismatch | 1 | 1 | 0 | 0 |
| invalid-then-mismatch | prepared | range | 0 | 0 | 0 | 0 |

Mismatch is exactly `SearchError::CorruptIndex{detail:"selected hit key does not match its physical document"}`; range is exactly `SearchError::Segment(SegmentError::Corrupt{context:"doc keys", detail:"doc id out of range"})`. Every failure leaves `reader_copy_used()==0`, `ledger.used()==0`, zero STORED calls, unchanged metadata; every recovery runs on the same snapshot and same ledger variable and re-checks the repeated positions. `completed == 19`, `failures == 8`, `recoveries == 8`. The historical U03 matrix had eight calls (three successes + four failures + one separate success); F1's 19 is a new, stronger matrix, not a retroactive recount.

### RF01 — complete cold/warm parity on real RustFS

Four complete `UnifiedResponse` pairs (`Asc K=10`, `Asc K=100`, `Desc K=10`, `Desc K=100`) compared with `PartialEq`; `checks == 440`, `requests == 8`, `parity_pairs == 4`; provider requests before = 1 and after = 1 (unchanged). Generation and view ordinal are checked on every response; all literal key/field/score-`None`/cursor assertions retained. GB-R01 remains byte-identical and passed.

### Unchanged targeted regressions

`column_geometry_tests` 34 pass, `b3_key_identity_tests` 12, `phase3_projection` 2, `phase5_i07` 1, `g_b0` 5, `e_projection` 4, `c2_tests` 42, `c2_physical_tests` 6, and the `perf06_c2_physical` target 14 pass (including unchanged I01 16 page executions and I02 20 pages / 200 checks).

## 5. Real RustFS topology

Podman (Docker unavailable) ran the pinned image `rustfs/rustfs@sha256:1803faef…` as task-owned `quervant-perf07a-f1-1291098` on `127.0.0.1:19007`, disposable credentials, bucket `quervant-perf07a-f1-1291098`, region `us-east-1`; health succeeded on the first bounded poll. On F1_TESTED:
- `pr15g_b_rustfs --ignored --test-threads=1 --nocapture`: 2 passed / 0 failed / 0 ignored (`gb_r01…` and `perf07a_rf01…`), four parity pairs and 440 hit checks.
- `perf06_b1_rustfs --ignored --test-threads=1 --nocapture`: `b1_r01_cold_shared_ordinals_and_pit` passed (1/0/0).

Only the task-owned container and disposable workspace were removed; shared bucket/objects were not deleted. Receipts: [rustfs-topology.txt](evidence/f1/rustfs-topology.txt), [rustfs-health.txt](evidence/f1/rustfs-health.txt), [f1-rustfs-gb-rf01.log.b64](evidence/f1/f1-rustfs-gb-rf01.log.b64), [f1-rustfs-b1.log.b64](evidence/f1/f1-rustfs-b1.log.b64).

## 6. Final local QA on F1_TESTED

Toolchains: stable `rustc/cargo 1.98.1`, MSRV `rustc/cargo 1.85.0`, `cargo-llvm-cov 0.9.1`, `git 2.43.0`, `python3 3.12.3`.

| Command | Result |
|---|---|
| `cargo +1.98.1 fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| stable Clippy `--all-targets` | PASS |
| stable Clippy `--all-targets --all-features` | PASS |
| MSRV Clippy `--all-targets` | PASS |
| MSRV Clippy `--all-targets --all-features` | PASS |
| stable tests default | PASS |
| stable tests all-features | PASS |
| MSRV tests default | PASS |
| MSRV tests all-features | PASS |
| stable coverage default | PASS |
| stable coverage all-features | PASS |
| `cargo doc --no-deps` | PASS |
| `cargo doc --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compilation only) |
| adapter contract (`benchmarks/pr15d/adapters/quervant`) | PASS, 6/6 |
| `benchmarks/scripts/test-scripts.sh` | PASS, 108/108 |

Test counts (all four workspace runs: 146 top-level harness summaries each, zero failed):
- Library harness default: `running 1234 tests` → `1233 passed; 0 failed; 1 ignored` (both toolchains).
- Library harness all-features: `running 1276 tests` → `1274 passed; 0 failed; 2 ignored` (both toolchains).
- Aggregate across harnesses (including zero-test targets): default `2776 passed / 0 failed / 16 ignored`; all-features `2821 passed / 0 failed / 101 ignored`.

Coverage (named Line columns):

| Regime | Lines total | Covered | Missed | Cover% |
|---|---:|---:|---:|---:|
| default | 79623 | 74448 | 5046 | **93.66%** |
| all-features | 81133 | 75673 | 5460 | **93.27%** |

Inventory parity: `f1-lib-list` equals the original 1234-name set; `f1-c2-list` equals 14; `f1-rustfs-list` equals 2. `cargo doc` is a docs build, not a doctest run; `bench --no-run` compiles only. Full raw per-command logs remain under `target/perf07-a-f1-evidence/`; selected logs are committed under `evidence/f1/` (raw bytes preserved as base64 where needed).

## 7. Residual risks, decision rules, gates

Applied rules: F01 (branch clean at F1_START), F05 (new scratch directory), F07 (expected RED replay), F08 (mechanical rustfmt/import/type corrections within the permitted bodies), F12 (lossless base64 for raw logs with whitespace diagnostics), F13 narrowly scoped to the new plan copy (readable copy normalized only by stripping five trailing-space hard breaks; exact supplied bytes preserved in base64 and disclosed above), F15 (CI pending at report time), F16 (historical provenance and count limitation recorded). No other rule was triggered.

Residuals remain those accepted for A: cold first use validates N keys and may retain an N+1 `u64` directory; refused/unmetered directory still scans once per projection group; optional metadata admission order can vary; physical allocation/OOM timing is not identical; cancellation sites are unchanged. F1 introduces no new production behavior. Actual warm performance remains unmeasured until PERF-07-I.

Local gates: PASS. Source freeze: PASS. Hosted CI on F1_FINAL and independent review G7: pending at documentation closeout; the agent does not mark G7 PASS and does not merge.

## 8. Evidence index

All committed evidence is under `evidence/f1/` with [SHA256SUMS](evidence/f1/SHA256SUMS) and [RAW-B64-MANIFEST.txt](evidence/f1/RAW-B64-MANIFEST.txt). Raw files that would introduce a new `git diff --check` whitespace diagnostic are committed losslessly as `.b64`; each entry records the original SHA-256 and byte length, and decoded equality was verified. Original `evidence/` files and their manifest remain byte-identical (18/18 `sha256sum -c` OK).

Selected files: [f1-red-replay.log](evidence/f1/f1-red-replay.log), [f1-u01.log.b64](evidence/f1/f1-u01.log.b64), [f1-r-group.log.b64](evidence/f1/f1-r-group.log.b64), [f1-u-group.log.b64](evidence/f1/f1-u-group.log.b64), [f1-perf06-c2.log.b64](evidence/f1/f1-perf06-c2.log.b64), [f1-rustfs-gb-rf01.log.b64](evidence/f1/f1-rustfs-gb-rf01.log.b64), [f1-rustfs-b1.log.b64](evidence/f1/f1-rustfs-b1.log.b64), [f1-lib-list.log](evidence/f1/f1-lib-list.log), [f1-c2-list.log](evidence/f1/f1-c2-list.log), [f1-rustfs-list.log](evidence/f1/f1-rustfs-list.log), [coverage-default-total.txt](evidence/f1/coverage-default-total.txt), [coverage-allfeatures-total.txt](evidence/f1/coverage-allfeatures-total.txt), [source-freeze.txt](evidence/f1/source-freeze.txt), [historical-red-attribution.txt.b64](evidence/f1/historical-red-attribution.txt.b64), [historical-count-excerpt.txt.b64](evidence/f1/historical-count-excerpt.txt.b64), [commands.tsv.b64](evidence/f1/commands.tsv.b64), [PERF07A_F1_DETAILED_FIXUP_PLAN.md.verbatim.b64](evidence/f1/PERF07A_F1_DETAILED_FIXUP_PLAN.md.verbatim.b64).
