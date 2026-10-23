# M5 — Mutation qualification implementation evidence

**Status: IMPLEMENTED — LOCAL AND REAL-RUSTFS QUALIFICATION PASS — FINAL-SHA CI
AND HUMAN MERGE APPROVAL PENDING. NOT DONE.** No production mutation code,
persisted format, feature bit, WAL or storage abstraction changed.

## 0. Baseline, scope and changed files

| Item | Value |
|---|---|
| Branch | `dev/m5-mutation-qualification` |
| Base / `origin/main` | `fed516164e765a0c74479f0f49db1344ed9d27e6` (`Merge pull request #54 from yduchesne/dev/m4-query-mutations`) |
| M4 head | `8889bbbff2d64ce07a86ede6f6d4cb79d7d0099e` |
| M4 ancestry check | `git merge-base --is-ancestor 8889bbb origin/main` exited 0 |
| Tested working tree | M5 test file + evidence/docs/CI edits on base `fed5161` (not yet committed) |
| Host | Linux x86-64; stable `rustc 1.98.1`; MSRV `rustc 1.85.0`; `cargo-llvm-cov 0.9.1`; `podman 4.9.3` |
| RustFS | `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`, endpoint `http://127.0.0.1:9000`, local disposable credentials |

Changed/added files:

- `crates/quervant-core/tests/m5_mutation_qualification.rs` (new qualification suite)
- `.github/workflows/ci.yml` (M5 real-RustFS step, three runs)
- `docs/ARCHITECTURE.md`, `docs/ROADMAP_V01.md`,
  `docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md` (verified qualification
  status only)
- `docs/pr-artifacts/m5/implementation-evidence.md` (this file)

**No production file changed.** The only executable code added is test code.

### 0.1 P0 baseline (recorded before M5 edits)

All commands run on `fed5161`:

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS — 1955 passed, 0 failed, 66 ignored, 105 suites |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 1955 passed, 0 failed, 66 ignored, 105 suites |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 91.15% lines |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed |
| `git diff --check` | PASS |

### 0.2 P0 source audit

| Path | Verified contract used by M5 |
|---|---|
| `contract/mutation.rs` | Public targets/actions/preconditions/batch/response/rejection and M4-AD16 shape |
| `index/writer.rs` | `apply_batch` → `plan_batch` Phases A/A2/B/C → one `install_batch`; flush, refresh, pin, commit, compact, poisoning/reconciliation, candidate state |
| `index/query_selection.rs`, `search/unified.rs` | Committed-snapshot bounded selection and first-over-limit stop |
| `index/mutation_state.rs` | v1/v2 state, replay ledger, fingerprints, AD16 predicate, compaction retention |
| `index/reconstruct.rs` | Five-state patch application and physical source reconstruction |
| `index/limits.rs` | Pending/batch/query/response/replay/state/snapshot caps |
| `remote/mod.rs` | Synchronous admission delegation; remote publication only on commit |
| `storage/{fs,memory}.rs` | Real filesystem and memory directories |
| `quervant-objectstore/tests/support/mod.rs` | Deterministic HTTP fault proxy with real upstream forwarding/checkpoints |
| `tests/pr13_crash_rustfs.rs` | Separate-process SIGKILL crash harness K01–K05 |
| `tests/m1_compat/run.sh` | Genuine pre-M1 binary compatibility harness |

### 0.3 Publication boundary classification

Local and remote publication use the same order: immutable segments →
mutation-state sidecar → manifest → `CURRENT` replacement → reader/state
installation. Failures before `CURRENT` preserve the previous authoritative
generation. Failure at/around `CURRENT` is reconciled by reading it: old pointer
keeps the writer usable with the old state; attempted pointer yields
`RecoveryRequired` and poisons the writer; anything else is indeterminate and
poisoned. No test assumes automatic rollback after an ambiguous `CURRENT`.

### 0.4 Pre-existing documentation defect

`docs/TESTING.md` contains four leftover `<<<<<<< HEAD` conflict markers from
before M4. Per plan EX18 this is reported, not edited.

## 1. Independent oracle and deterministic fixtures

`tests/m5_mutation_qualification.rs` contains a small `BTreeMap` state machine:

- key → `(revision, live/tombstone, field map)`;
- explicit insert/upsert/delete/replace/patch transitions;
- expected live keys and all five `FieldValues` states.

It never calls `plan_batch`, `select_query_keys`, the writer planner, or
production search to compute expected matches. Query scripts enumerate the
expected target keys by hand; the production query executor is only the system
under test. Fixtures are fixed (no property-testing dependency, no sleeps) and
use isolated `MemoryDirectory`, real temporary `FsDirectory` roots, or unique
RustFS prefixes/caches.

Test-only fault injection wraps the **real** `FsDirectory` (manifest-create
failure, pre-`CURRENT` failure, post-`CURRENT` failure, and barriers around the
`CURRENT` atomic write). Remote faults use the existing deterministic proxy.

## 2. Test traceability (T01–T44)

All listed results were executed on the final working tree described in §0.

| Test | Test name(s) | Topology | Result |
|---|---|---|---|
| T01 | `m5_t01_mixed_batch_is_atomic_and_visible_after_refresh_memory_and_fs` | Memory + FS | PASS |
| T02 | `m5_t02_late_invalid_patch_rejects_whole_batch_without_token_consumption_memory_and_fs` | Memory + FS | PASS |
| T03 | `m5_t03_late_conflict_after_query_mutation_rejects_entire_batch_memory_and_fs` | Memory + FS | PASS |
| T04 | `m5_t04_ordered_explicit_commands_allocate_exact_revisions` | Memory | PASS |
| T05 | `m5_t05_stale_expected_revision_fails_without_mutation_memory_and_fs` | Memory + FS | PASS |
| T06 | `index::writer::batch_tests::a03_revision_overflow_rejects_the_whole_batch` | Unit/state harness | PASS (1) |
| T07 | `m5_t07_query_selection_is_fixed_to_the_batch_initial_committed_snapshot` | Memory + FS | PASS |
| T08 | `m5_t08_earlier_staged_insert_is_not_selected_by_a_query` | Memory | PASS |
| T09 | `m5_t09_selected_key_with_a_newer_pending_revision_fails_closed` | Memory | PASS |
| T10 | `m5_t10_exactly_at_the_query_match_limit_mutates_every_match` | Memory | PASS |
| T11 | `m5_t11_one_over_the_query_match_limit_is_a_typed_failure_without_truncation` | Memory | PASS |
| T12 | `m5_t12_patch_preserves_all_five_states_and_typed_json_geo_memory_and_fs` | Memory + FS | PASS |
| T13 | `m5_t13_indexed_only_source_is_rejected_on_real_filesystem` | FS | PASS |
| T14 | `m5_t14_query_replace_retains_keys_and_drops_omitted_fields` | Memory | PASS |
| T15 | `m5_t15_query_upsert_zero_one_and_two_matches_memory_and_fs` | Memory + FS | PASS |
| T16 | `m5_t16_live_pending_fallback_collisions_and_staged_overlap_reject` | Memory | PASS |
| T17 | `m5_t17_zero_match_fallback_is_durable_and_replays_after_reopen_memory_and_fs` | Memory + FS | PASS |
| T18 | `ad16_t01..t10` (10 tests) + `u14_malformed_v2_records_are_typed_rejections` | Codec unit | PASS (10 + 1) |
| T19 | `m5_t19_replay_after_reopen_never_reselects_changed_query_matches_fs`; real `full_script` replay inside `m5_t43_real_rustfs_mutation_qualification` | FS + RustFS | PASS |
| T20 | `m5_t20_changed_token_payloads_conflict_without_admission_fs` | FS | PASS |
| T21 | `m5_t21_replay_survives_compaction_and_respects_replay_bounds_fs`; existing `compaction_preserves_batch_replay_records` | FS + unit | PASS |
| T22 | `m5_t22_successful_mixed_batch_cold_reopens_completely_fs` | FS | PASS |
| T23 | `m5_t23_pre_current_failure_preserves_the_old_generation_fs`; real `interrupted_upload_preserves_generation` in `m5_t43` | FS + RustFS | PASS |
| T24 | Real `interrupted_upload_preserves_generation` (state upload 503) + existing K01–K03 pre-`CURRENT` crash checkpoints | RustFS fault harness | PASS |
| T25 | `pr13_crash_rustfs::{k01,k02,k03,k04}` (K04 = after CAS, before ack) | RustFS crash harness | PASS (4) |
| T26 | `m5_t26_ambiguous_current_poisoning_and_reopen_follow_the_protocol_fs` | FS | PASS |
| T27 | `m5_t27_pinned_reader_and_pit_remain_immutable_across_refresh_commit_and_merge` | Memory + FS | PASS |
| T28 | `m5_t28_barrier_controlled_readers_never_observe_a_prefix_fs` | FS + barriers | PASS |
| T29 | `m5_t29_same_logical_script_is_equivalent_on_memory_and_filesystem`; real `full_script` | Memory + FS + RustFS | PASS |
| T30 | Real `full_script` cold reopen with an empty cache | RustFS | PASS |
| T31 | Real `full_script`: local cache removed, then cold reopen | RustFS | PASS |
| T32 | Real `admission_without_remote_io` (proxy request count unchanged across admission, increases on commit) | RustFS + proxy | PASS |
| T33 | `m5_t33_cancellation_before_and_within_selection_admits_nothing` | Memory | PASS |
| T34 | `m5_t34_exact_and_one_over_batch_and_query_limits_fail_closed` + T10/T11 + existing `u06_batch_key_limit_boundaries`, `u06_response_byte_limit_boundaries`, `u06_batch_replay_key_limit_boundaries`, `m2_v02_source_byte_budget_rejects_before_decode` | Memory/unit/FS | PASS |
| T35 | `m5_t35_budget_and_cancellation_failures_consume_no_revision_or_token_memory_and_fs` | Memory + FS | PASS |
| T36 | `baseline_v1_fixture_decodes_under_the_new_reader`, `v2_round_trip_preserves_batch_replay`, `u14_malformed_v2_records_are_typed_rejections`, genuine pre-M1 harness | Codec + FS | PASS |
| T37 | `m4_t21_t22_pre_m4_fingerprints_are_byte_compatible`; `ad16_t*` tag-5/fingerprint coverage | Codec unit | PASS |
| T38 | `bash crates/quervant-core/tests/m1_compat/run.sh` — separate pre-M1 binary from `cd3b9ac` typed-rejects v2 without writes | Two binaries + FS | PASS — 18/18 checks |
| T39 | FS: `m5_t23`, `m5_t26`, `m5_t28`; RustFS: K01–K05 crash checkpoints | FS + RustFS | PASS |
| T40 | `pr13_crash_rustfs k05` executed 10 independent runs | RustFS | PASS — 10/10 |
| T41 | Focused `m1_batches`/`m2_patches`/`m3_delete_by_query`/`m4_query_mutations`/`m5_mutation_qualification` non-ignored = 116 passed, 5 ignored; full workspace suite | Workspace | PASS |
| T42 | `m5_t42_scored_search_still_observes_only_live_documents` + full workspace suite | Workspace | PASS |
| T43 | `m5_t43_real_rustfs_mutation_qualification` executed 3 independent runs with unique prefixes/caches | RustFS | PASS — 3/3 |
| T44 | Final local gates below | CI + local | **LOCAL PASS / CI PENDING — NOT DONE** |

Ignored tests were executed separately in their authoritative topology; they
are never counted as default-suite passes.

## 3. Final local qualification commands

Run after all source/test/doc/CI edits, on the working tree in §0.

| Gate | Command | Result |
|---|---|---|
| Stable fmt | `cargo fmt --all -- --check` | PASS |
| Stable Clippy (default) | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| Stable Clippy (all features) | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Workspace tests (default) | `cargo test --workspace --all-targets` | PASS — 1980 passed, 0 failed, 9 ignored, 106 suites |
| Workspace tests (all features) | `cargo test --workspace --all-targets --all-features` | PASS — 1984 passed, 0 failed, 67 ignored, 106 suites |
| MSRV fmt | `cargo +1.85.0 fmt --all -- --check` | PASS |
| MSRV Clippy (all features) | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| MSRV tests (all features) | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 1984 passed, 0 failed, 67 ignored, 106 suites |
| Documentation | `cargo doc --workspace --all-features --no-deps` | PASS |
| Benchmark build | `cargo bench --workspace --no-run` | PASS |
| Benchmark scripts | `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |
| Whitespace | `git diff --check` | PASS |
| Focused mutation suites | `cargo test -p quervant-core --all-features --test m1_batches --test m2_patches --test m3_delete_by_query --test m4_query_mutations --test m5_mutation_qualification` | PASS — 116 passed, 0 failed, 5 ignored |
| M5 non-ignored | `cargo test -p quervant-core --all-features --test m5_mutation_qualification -- --test-threads=1` | PASS — 29 passed, 0 failed, 1 ignored |
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.16% lines** (47145 lines, 4167 missed); regions 91.77%; functions 87.04% |

Coverage is reported from the workspace command; no crate/module exclusion was
added. It is not offered as proof of semantic correctness.

## 4. Real RustFS and crash evidence

### 4.1 M5 real-service acceptance (T43)

Command per run:

```sh
QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
QUERVANT_RUSTFS_REGION=us-east-1 \
QUERVANT_RUSTFS_BUCKET=quervant-m5-local \
QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
cargo test -p quervant-core --all-features \
  --test m5_mutation_qualification -- --ignored --test-threads=1
```

| Run | Result | Duration | Namespace/cache |
|---|---|---|---|
| 1 | PASS — 1 passed, 0 failed | 2.33 s | unique `m5/full`, `m5/admission`, `m5/interrupt` prefix + fresh cache per scenario |
| 2 | PASS — 1 passed, 0 failed | 2.29 s | unique prefixes/caches |
| 3 | PASS — 1 passed, 0 failed | 2.34 s | unique prefixes/caches |

The scenario performed real S3 I/O through the production `S3ObjectStore` and
`RemoteIndexWriter`; no fake or SKIP was used. It covered mixed batches, query
delete/replace/upsert, cold bootstrap with an empty cache, cache removal, durable
replay without reselection, zero remote I/O during admission, and interrupted
state upload preserving generation G. The local container used the exact pinned
digest from `tests/rustfs/README.md` and `.github/workflows/ci.yml`.

### 4.2 M1–M4 and PR13 regression on real RustFS

| Suite | Result |
|---|---|
| `m1_batches --ignored` | PASS — 1 passed |
| `m2_patches --ignored` | PASS — 1 passed |
| `m3_delete_by_query --ignored` (3 independent runs) | PASS — 1/1 each |
| `m4_query_mutations --ignored` | PASS — 1 passed |
| `pr13_s3_rustfs --ignored` | PASS — 8 passed |
| `pr13_proxy_rustfs --ignored` | PASS — 5 passed |
| `pr13_remote --ignored` | PASS — 3 passed |
| `pr13_oracle --ignored` | PASS — 1 passed |
| `pr13_oracle_geo --ignored` | PASS — 1 passed |
| `pr13_remote_proxy --ignored` | PASS — 7 passed |

### 4.3 Crash/race injection points

| Harness | Injection point | Observed outcome | Runs |
|---|---|---|---|
| K01 | after segment upload, before mutation state | no committed `CURRENT`; cold reopen `NotInitialized` | 1 |
| K02 | after state upload, before manifest | no committed `CURRENT` | 1 |
| K03 | after manifest, before `CURRENT` | previous/no generation authoritative | 1 |
| K04 | after `CURRENT` CAS, before acknowledgment | new whole generation opens (`Some(1)`) | 1 |
| K05 | mid ranged segment download with staged partial bytes | no final segment visible; cache reconciles; fresh cache opens complete G1 | 10/10 |
| M5 FS | manifest create failure; `CURRENT` pre-write failure | old G authoritative after cold reopen | 1 test (2 cases) |
| M5 FS | `CURRENT` write succeeds then error | writer poisoned; cold reopen sees whole G+1 | 1 |
| M5 FS | barrier immediately before `CURRENT` | pre-publication reader sees complete old G; post-publication reader sees complete new G | 1 |
| M5 RustFS | state upload returns 503 | commit fails; cold reopen sees whole old G | 1 per run |

No test observed a mixed/partial generation. No sleep is used to prove a race;
the filesystem concurrency case is barrier-controlled.

### 4.4 Genuine pre-M1 binary (T38)

`bash crates/quervant-core/tests/m1_compat/run.sh` built two independent
binaries: baseline `cd3b9ac` and current `fed5161`. Result: **18 passed, 0
failed**. The baseline reader rejected the upgraded v2 index with
`UnsupportedFeature { feature_id: 11, version: 1 }`, modified no index files,
and the current reader still replays the durable batch exactly. The new decoder
was never used to simulate the old reader.

## 5. Failure classification and residual risks

No mandatory gate failed. No pre-existing baseline failure was observed. The
only development failures were test-authoring/test-implementation defects
(fixed before final runs):

| Failure | Classification | Resolution |
|---|---|---|
| T01 initially cold-reopened without committing the volatile batch | M5 test defect | Removed the cold-reopen assertion from T01; T22 owns committed cold reopen |
| T28 initially armed the `CURRENT` barrier during seed commit, deadlocking | M5 test defect | Seed G1 through the plain filesystem, then arm the barrier only for G2 |
| T28 post-publication read raced the writer after the release barrier | M5 test defect | Added a third barrier so the reader opens only after commit acknowledgment |
| T29 query-delete selected from the prior committed generation while batch mutations were pending | M5 test defect | Commit the mixed batch before the query action, as the script intends |
| `clippy::unnecessary_cast` in a test fixture | M5 test defect | Removed the redundant cast; stable and MSRV Clippy clean |

Residual limitations (disclosed, not waivers):

- **T44 is not complete:** final-SHA GitHub `rust`, `msrv` and `rustfs` CI has
  not run; human review and merge approval are outstanding. M5 is not DONE.
- The real RustFS interrupted-upload case fails the mutation-state PUT (no
  incomplete object is published) and relies on existing K01–K03/K05 for
  process-kill and mid-download interruption. The test proxy does not truncate
  an HTTP request body upstream; no such fault is claimed.
- The source-byte exact/+1 boundary is covered by the existing M2
  `m2_v02_source_byte_budget_rejects_before_decode` test rather than duplicated
  in M5.
- Revision overflow uses the existing safe near-`u64::MAX` fixture; it is not
  reachable through public input alone.
- OS power-loss beyond the existing `FsDirectory` sync protocol and network
  partitions beyond the existing proxy matrix remain outside this suite.
- Indexed-only sources remain unreconstructable by contract; multiwriter
  fencing, distributed behavior and vectors are out of scope.
- `docs/TESTING.md` merge-conflict markers are pre-existing and untouched.
- Coverage does not prove semantic correctness; the independent model and
  adversarial assertions are separate evidence.

## 6. Status

- **P0:** PASS, no production changes.
- **P1–P4:** implemented and executed; local/Memory/FS/RustFS gates PASS.
- **P5 local qualification:** PASS (commands in §3, service evidence in §4).
- **Pushed / draft PR:** pending.
- **Final-SHA CI:** pending.
- **Independent review / human merge authorization:** pending.
- **DONE:** **not claimed.**
