# PERF-07-A execution report

**Status:** `PERF07_A_LOCAL_ACCEPTANCE_PASS_CI_PENDING`
**Branch:** `dev/perf-07-a`
**Plan:** [PERF07A_DETAILED_IMPLEMENTATION_PLAN.md](PERF07A_DETAILED_IMPLEMENTATION_PLAN.md) (SHA-256 `5a66c42cb00ed8fde2118ef3e55145603b44a4a3ca13de9a6a1f65b0670ed7b1`)
**Correctness scope only.** No timed acquisition, profiler campaign, new benchmark, cross-engine run, or measured speedup claim. PERF-07-I owns warm qualification.

## Revisions and admission

| Item | Value |
|---|---|
| BASE (`origin/main`) | `c9ca7975ab6f29fc4fe1fac65951cede3799cb8c` |
| BASE complete tree | `0ead7efb356d66751c801b12a27147e281ae2a5e` |
| Roadmap PR #134 | merged `2026-11-28T02:24:12Z`, merge commit `c9ca7975…`, reviewed head `e7bc4cab3c433f7e6c1894e8128b0bd6e618bf5b` |
| Reviewed head tree | `0ead7efb356d66751c801b12a27147e281ae2a5e` (equals `origin/main` complete tree) |
| PERF-06-C4 ancestor | `44caa511f6e147836c446b970845f03de45eb515` is an ancestor of BASE |
| RED commit | `06898baf9a796cddf5a03033652df4d2a53e150a`, tree `9ca4f8ed5cf311dbca24f9e50848c24e69c74a5a` |
| TESTED commit | `29fe4a2d596b3df43cd29f18722983098d664a47`, tree `5828846d3dfcc3a4742848099c873e185fb9a7aa` |
| Branch admission | `dev/perf-07-a` existed locally at exactly BASE with no remote branch and no prior PR; reused under D03 |
| Preserved untracked input | `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` (disjoint, never staged) |

All §2 source-anchor blobs were verified with `git rev-parse "$BASE:$path"`; all 19 matched the reviewed values (recorded in the execution transcript).

## Pre-implementation correctness worksheet

| Challenge | Resolution used |
|---|---|
| Why not call `doc_key_selected` K times? | A refused directory would rescan N keys K times. One scan with K sorted borrowed rows is required. |
| Why not skip parity because B3 already selected the key? | Projection physical identity is authoritative, including tampered private `SelectedHit` and retained PITs. |
| Why not return mismatch as soon as a key differs in the fallback scan? | A late corrupt unselected key or trailing data used to win before the selected lookup. The failure is recorded privately and full validation completes. |
| Why not sort selected IDs and report the first sorted error? | Historical selected order decides mismatch vs out-of-range after validation; original ordinals are retained. |
| Can optional directory build scan then refuse? | Yes. Measured finalization can fail after a completed scan; the private parity result is reused with no rescan. |
| Can the initializer cache the comparison? | No. The comparison is request-local; only the immutable offset certificate enters the shared cell. |
| Does `None` mean valid bytes? | No. It means the optional directory is unavailable; every access validates. |
| Does checksum validation establish all keys valid? | No. Full UTF-8/length/framing/terminal validation still runs before publication. |
| Can one snapshot's certificate verify another segment's bytes? | No. Ownership is bound to the exact immutable bytes/limits; R04 uses independent owners. |
| Can projection reserve fewer output bytes? | No. The output ledger and optional batch sink are unchanged. |
| Is a new public storage abstraction needed? | No. The existing reader, state, offset builder and cache are reused. |
| Does the first preparation claim O(K) total memory? | No. The retained directory is N+1 `u64`; only request scratch/owned keys change. |

## Implementation

Only the four authorized executable/test paths changed.

- `crates/quervant-core/src/segment/reader.rs`: the existing `scan_doc_keys` body moved to `scan_doc_keys_with` (original body byte-equivalent after the prescribed `cfg(test)` observations, visitor call, `early_range` binding and signature changes); new request-local `KeyParity`, `scan_selected_key_parity` (bounded O(K) borrowed scratch, original-ordinal first failure after complete validation), `verify_keys_at_offsets`, and `SegmentReader::verify_selected_doc_keys`; `cfg(test)` `perf07a_observation` counters and deterministic directory fault seam.
- `crates/quervant-core/src/search/unified.rs`: the `project_selected_hits` key-check block now routes every projection group through the verifier. The `selected_ids` reservation/sort/dedup, `stored_docs_selected`, binary search, plan projection, ledger charge and `out[index]` ordering are unchanged.
- `crates/quervant-core/tests/perf06_c2_physical.rs`: I01/I02.
- `crates/quervant-core/tests/pr15g_b_rustfs.rs`: RF01.

No wire format, public API, persistent/global cache, new dependency, `unsafe`, lint suppression, production flag, benchmark policy, CI trigger or storage lifecycle changed. Existing scalar `doc_key_selected`, `bind_key_identity`, full key decoder behavior, `VerifiedSegmentState`, `ValidatedOffsets`, `MetadataMeter` and the STORED projection body are unchanged.

### Error precedence retained

- Ordinary `doc_key`/full-body route: a non-representable first ID fails before body access; otherwise the complete body is validated before the first selected lookup returns, and later bad IDs/mismatches follow original selection order.
- Large singleton (`K == 1 && N >= 1024`): the historical header/count/limits/minimum-byte-then-range behavior is retained through `early_range`.
- Unselected invalid UTF-8, empty, oversized, truncated or trailing data still wins over a selected mismatch.
- A completed valid directory may publish even when the expected key mismatches; the private mismatch result is returned after validation.

## Red-first and green evidence

- RED: `06898baf…` with only the observation seam and U01 added. Command:
  `cargo +1.98.1 test -p quervant-core --lib perf07a_u01_projection_prepared_offsets_no_full_keys -- --nocapture`
  exited 101 with exactly one selected test, all preceding semantic assertions passed, and the named assertion failed with `full_owned=1100`, expected `0`, `full_decodes=1`. Raw log: [`evidence/red-u01.log`](evidence/red-u01.log).
- GREEN on TESTED: U01 completes four rows (K=10 twice, K=100 twice) with `full_owned=0`, `full_decodes=0`, `scans=0`, `scan_rows=0`, `offset_reads=K`, `selection_rows=0`, `selected_keys_owned=K`, `stored_calls=1`. Raw log: [`evidence/green-u01.log`](evidence/green-u01.log).

## Unit acceptance (15 new registrations)

Reader tests in `segment::reader::column_geometry_tests` (R01–R09) and projection tests in `search::unified::c2_tests` (U01–U06) all pass.

| Test | Rows / key evidence |
|---|---|
| R01 prepared reordered/duplicate UTF-8 | 3 rows; direct reads 6, no full key construction; full-cache control `cache_compares=6`, directory untouched |
| R02 first use + warm reuse | 4 calls; cold `scans=1/4`, scratch 3, +40 bytes; warm `offset_reads=3`; mismatch publishes directory and later direct call succeeds |
| R03 unmetered + real one-under refusal | 4 calls; unmetered one scan each; 39-free-byte refusal one scan, sticky `None`, no delta |
| R04 exact metadata + independent owners | 3 calls, 2 states; exact 40-byte admission, distinct pointers, accounting inherited and released |
| R05 injected post-scan finalize refusal | 4 calls; `INJECTED_POST_SCAN_MEASUREMENT`, one scan, no rescan, sticky `None`, no delta |
| R06 corrupt unselected matrix | 20 acceptance calls (C1–C8 × unmetered/admitted, C1 mismatch ×2, sticky repeat, direct count-limit); exact typed errors, full-decoder oracle agreement, `scan_rows` 3/0/4 per row |
| R07 selected-order and singleton boundary | 35 calls; S0–S7 × unmetered/admitted-empty/prepared (direct reads 0/3/2/1/0/1/2/0), N=1023/1024 boundaries, real empty segment, corrupt empty selection |
| R08 concurrent initialization | 2 workers; sum `scans=1`, `scan_rows=4`, `full_owned=0`; one worker scans, the other direct-reads exactly 1 or 3 depending on the winner; one shared pointer and one 40-byte charge |
| R09 initializer unwind + recovery | 3 calls; injected panic after scan, cell `None`, budget restored, retry publishes `Some(true)` and +40, next wrapper direct-reads |

Additional matrix facts: prepared routes constructed exactly K selected keys (`selected_keys_owned=K`); scan routes constructed zero; every failed projection group admitted zero bytes and performed zero STORED calls; a mismatch is not allowed to suppress later body corruption; a started scan is never restarted.

## Projection-path unit acceptance (6 new registrations)

| Test | Evidence |
|---|---|
| U01 | RED 1100 owned keys vs 0; GREEN 4 rows with exact direct/scan counts |
| U02 | N=1100 first use `scans=1`, `scan_rows=1100`, `selection_rows=4`, `stored_calls=1`; warm `offset_reads=4`; zero-metadata snapshot scans each call; empty selection zero work |
| U03 | selection order `[3,0,3,1]`, duplicates, exact mismatch/range errors, zero ledger/STORED on failures, cold scan 1 / warm scan 0 |
| U04 | real copied-container lazy `InvalidUtf8` on unselected record 3 wins through the projector on admitted and zero-metadata snapshots; `stored_calls=0`, no ledger admission; pristine control succeeds |
| U05 | two real committed segments; input `[7,0,5,2,7]`; cold `scans=2`, `scan_rows=8`, `selection_rows=5`, `stored_calls=2`; warm `offset_reads=5`; segment-1 mismatch leaves `stored_calls=1` and exactly `33 * first_group_positions` charged |
| U06 | 33-byte empty-field hit; standalone 66 success / 65 `ResourceLimit{65,66}` with 33 retained; exact batch 66, batch 65 `BudgetExceeded{BatchMemoryBytes}` with 33 temporary, local 65 batch 66 `ResourceLimit`; scope release returns the meter to zero |

## Integration acceptance

- I01 `perf07a_i01_real_fs_multi_hit_scores_and_projection`: two real `FsDirectory` segments (counts 100/1000), total field length 4950; K=1/10/100 × Asc/Desc each executed twice plus four continuations = 16 page executions; exact keys, fields, score bits, totals, cursors.
- I02 `perf07a_i02_real_fs_pit_upsert_delete_compact_projection`: delete `s0002`, keep `s0006` matching with a new body (tf=4, dl=6), insert `s0040`; df=n=40, total length 178; five phases × four pages = 20 page calls / 200 per-hit checks; old pinned responses exactly unchanged, stale cursor rejected with `CursorPitMismatch`, compacted single segment matches partial-parity fields/scores, old pinned view survives.
- RF01 `perf07a_rf01_real_rustfs_multi_hit_cold_and_warm_projection`: real pinned RustFS service, 1100 documents, one committed segment; four cases (Asc/Desc × K=10/100) executed twice = 440 returned-hit checks; exact keys/fields, `score=None`, cursors; second pass added zero provider requests.

## Real-service topology

Podman (Docker unavailable) ran the pinned image `rustfs/rustfs@sha256:1803faef…` as task-owned `quervant-perf07a-1152180` on `127.0.0.1:19007`, disposable credentials and bucket `quervant-perf07a-1152180`, region `us-east-1`; health succeeded on the first of at most 30 bounded polls. `pr15g_b_rustfs --ignored --test-threads=1` passed both `gb_r01…` and `perf07a_rf01…` (2 passed, 0 failed, 0 ignored); `perf06_b1_rustfs --ignored --test-threads=1` passed `b1_r01…`. Only the task-owned container and disposable workspace were removed; the shared bucket was not deleted.

## Final quality gates on TESTED (`29fe4a2d…`)

Both feature regimes and both toolchains were executed in the prescribed order. Full logs remain under the task-owned untracked `target/perf07-a-evidence/`; focused logs are committed.

| Gate | Result |
|---|---|
| `cargo +1.98.1 fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| stable Clippy `--all-targets` | PASS |
| stable Clippy `--all-targets --all-features` | PASS |
| MSRV Clippy `--all-targets` | PASS |
| MSRV Clippy `--all-targets --all-features` | PASS |
| stable tests default | PASS (top-level `1234 passed, 0 failed, 1 ignored`) |
| stable tests all-features | PASS |
| MSRV tests default | PASS |
| MSRV tests all-features | PASS |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS |
| `cargo +1.98.1 doc --workspace --no-deps` | PASS |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS |
| `cargo +1.98.1 bench --workspace --no-run` | PASS (compilation only) |
| adapter contract test (`benchmarks/pr15d/adapters/quervant`) | PASS (6 tests) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108 script tests) |

Coverage (named line columns; Regions/Functions also reported by llvm-cov):

| Regime | Lines total | Covered | Missed | Cover% |
|---|---:|---:|---:|---:|
| default | 79494 | 74448 | 5046 | **93.65%** |
| all-features | 81004 | 75543 | 5461 | **93.26%** |

Inventory: baseline lib inventory 1219 tests; TESTED lib inventory 1234 tests (1 ignored). `perf06_c2_physical` 12 → 14 tests. `pr15g_b_rustfs` 1 → 2 ignored tests. No prior test renamed, removed or weakened. Criterion harnesses were compiled by `bench --no-run` only; no measurement was acquired. `cargo doc` is a documentation build, not a doctest run.

## Source freeze and whitespace

`git diff --name-only BASE..TESTED` equals exactly the four authorized paths. `.github/` is unchanged. `git diff --check BASE..TESTED` and `git diff --check` pass. Details: [`evidence/source-scope.txt`](evidence/source-scope.txt).

## Applied decision-matrix rules

D01 (predecessor merged and anchors exact), D03 (clean branch reused), D06 (expected RED accepted), D08 (mechanical Clippy/format corrections only: `field_reassign_with_default` struct literals, `needless_range_loop` iterator form, `type_complexity` alias, block-return simplification), D09/D10/D11/D12/D13 (runtime table paths verified by R/U tests), D17 (expected typed refusals recorded as PASS), D23 (all local mandatory checks passed).

## Residual risks and open gates

- Actual elapsed savings are unmeasured until PERF-07-I.
- Cold first use still validates N keys and may retain an N+1 `u64` directory.
- A refused/unmetered directory still scans the section once per projection group; not an O(K)-latency promise.
- Existing STORED certification and candidate collection retain their own costs.
- Projection can consume part of the shared optional metadata budget earlier, potentially changing which later optional accelerators are admitted; semantic limits are unchanged.
- Real allocator failure timing changed with the physical allocation footprint; no identical-OOM claim.
- Existing cancellation checks are preserved, not redesigned.
- Hosted final-head CI status is not asserted here; it is recorded in the draft PR and terminal handoff. G7 (independent review) remains open. No merge or baseline promotion.
