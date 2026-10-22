# M1 — Atomic explicit-key mutation batches: implementation evidence

**Status: PARTIAL / NOT QUALIFIED.** Implementation is complete and every locally
runnable mandatory gate passed. Two mandatory qualification gates are **BLOCKED**
in this environment: `M1-V04` (real RustFS) and `M1-V05` (baseline old-reader
binary). Per plan §17 a blocked gate is **not** an approval to waive it, so M1 is
**not** marked DONE/accepted/mergeable on this evidence.

- Working tree: `dev/atomit-mutation-batch`
- Implementation base: `cd3b9ac610e35628587faf38780fda778d53cd94`
  (merge of PR #47 `dev/mutation-contract`, which carries M0 decisions through
  `64bb826`)
- Source baseline audited by M0: `585a1eed033a9328c46872c505fe5aece9a735de`
- Host: Linux x86-64; toolchains `rustc 1.98.1` (stable) and `1.85.0` (MSRV)
- Plan revision: `QUERVANT_M1_DETAILED_IMPLEMENTATION_PLAN.md`

## P0 baseline evidence table (§2 preflight)

| Item | Actual |
|---|---|
| `git status --short` before work | clean |
| Branch | `dev/atomit-mutation-batch` (created from verified main; already present) |
| `git rev-parse HEAD` | `cd3b9ac610e35628587faf38780fda778d53cd94` |
| M0 PR #47 merged into base | YES (merge `cd3b9ac`; content `64bb826`) |
| Guide PR #46 on base | YES (`docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` present) |
| M0-D11 approvals present | YES (`docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md` §"M0 decision approvals — 2026-10-22") |
| `crates/quervant-core/src/index/writer.rs` | `apply` L279, `flush` L379, `commit` L474, `candidate_state_for` L723, `candidate_rows` L797 |
| `index/mutation_state.rs` | `MUTATION_STATE_VERSION` L34, `ReplayRow` L115, version equality check in `decode` |
| `index/limits.rs` | `IndexLimits` L13 |
| `index/error.rs` | `IndexError` L20 (`#[non_exhaustive]`) |
| `segment/format.rs` | `ensure_features_supported` L423; `ContainerView::ensure_supported_features` L722 |
| `remote/mod.rs` | `RemoteIndexWriter::apply` L363 (before change) |
| `contract/batch.rs` | query batches only — mutation types added to `contract/mutation.rs` |
| Baseline `cargo test -p quervant-core --lib` | **PASS** — 627 passed, 0 failed |

Deviations from the plan's §2 table: none observed. Symbols are at the expected
paths with the described semantics.

## Pre-implementation correctness gate (§15)

1. **State diagram.** `Committed -> ProspectiveDelta -> AdmittedVolatile ->
   RefreshedImmutable -> CommittedGeneration`. `BatchDelta` is pure data; a
   failure while building it returns to the exact original state because the
   writer is never touched. Implemented in `index/writer.rs`
   (`plan_batch` / `install_batch`).
2. **Single installation boundary.** `install_batch` performs the map copies,
   replacement-map construction and the two `Vec::try_reserve` calls *before* its
   first mutation. From `self.pending.append(...)` onward there is no `?`, no
   cancellation poll, no I/O, no validation and no allocation-capable call.
   A test-only counter (`install_transitions`) asserts exactly one transition per
   admitted batch (`batch_install_happens_exactly_once`).
3. **Revision truth table, ordering, dedupe, applicability.** Implemented by
   `check_precondition`, `resolve_batch_target`, `action_document`,
   `action_intent`. `Keys` dedupes by first occurrence for processing, sorts the
   response ascending, and rejects multi-key non-delete actions.
4. **Resource accounting.** Pending docs/bytes, journal length, replay entries
   (single-key + batch), replay bytes, per-batch persisted key outcomes, encoded
   response bytes and the *encoded mutation-state sidecar bytes* are all checked
   with checked arithmetic before installation. Pending segment ids are fixed
   width (`s-` + 64 hex), so the placeholder used for size preflight is exact.
5. **v1/v2 layout and feature ordering.** `ContainerView::ensure_supported_features`
   runs **before** the payload version is read (`mutation_state.rs::decode`), so a
   baseline reader fails with typed `SegmentError::UnsupportedFeature` rather than
   corruption. See PA-M1-11 resolution below.
6. **Failure matrix and independent oracle.** Rollback tests snapshot every
   mutable writer field (`state_snapshot`) and compare before/after. Revision
   oracles are hand-computed, never produced by a second `apply_batch`.
7. **M0 approvals and non-goals.** D1/D2 (committed-snapshot selection, no public
   volatile token) — respected: the selector is reserved and rejected. D7
   (`MustNotExist` accepts tombstones) — tested. D8 (reject `Set(Absent)`) —
   `PatchOperation` is reserved and rejected in M1. D10/D11 — see §7.

## Implemented surface

| File | Change |
|---|---|
| `crates/quervant-core/src/contract/mutation.rs` | **new** — `MutationTarget`, `QueryMutationSelector`, `MutationAction`, `DocumentPatch`, `PatchOperation`, `MutationPrecondition`, `MutationCommand`, `MutationBatch`, `MutationKeyOutcome`, `MutationCommandOutcome`, `MutationBatchResponse`, `MutationRejection` |
| `contract/mod.rs` | exports |
| `index/error.rs` | one new `IndexError::MutationRejected { rejection }` (rejection payload boxed for the large variants) |
| `index/limits.rs` | `max_batch_commands`, `max_batch_keys`, `max_batch_replay_keys`, `max_batch_response_bytes` + ceilings + `[1, ceiling]` clamping |
| `index/mutation_state.rs` | `BatchReplayRow`, v2 payload + `FEATURE_MUTATION_STATE_V2`, v2 encode/decode with bounds, `batch_fingerprint`, `encode_with_mode` |
| `index/writer.rs` | `apply_batch`, `BatchDelta`, `plan_batch`, `install_batch`, batch replay ledger, token-namespace unification, `candidate_rows` refactor, v2-aware `commit` |
| `index/mod.rs` | load-path replay bounds now cover batch replay; `max_batch_replay_keys` enforced on decode |
| `index/merge.rs` | compaction preserves batch replay records and never downgrades v2 |
| `remote/mod.rs` | `RemoteIndexWriter::apply_batch` synchronous delegation |
| `segment/format.rs` | `FEATURE_MUTATION_STATE_V2 = 0x000B` in `SUPPORTED_FEATURES` |
| `crates/quervant-core/tests/fixtures/m1/mutation_state_v1.bin` | **new** baseline v1 fixture (307 bytes) |
| `crates/quervant-core/tests/m1_batches.rs` | **new** integration verticals |

### Fixture

`tests/fixtures/m1/mutation_state_v1.bin`

- Generated with the **pre-M1 (baseline) v1 encoder** at `cd3b9ac`, before any
  v2 encoder existed.
- Contents: live key `m1-live` revision 3 -> `seg-m1-fixture` doc 7; tombstone
  `m1-dead` revision 2; one single-key replay token `m1-single-token`
  (Upsert, revision 3).
- Size: 307 bytes.
- SHA-256: `753094d07734fbbebf5b535d585af83107d241c917e7e731462d2af972efc469`
- Regeneration (manual, ignored test):
  `cargo test -p quervant-core --lib m1_fixture_tests::regenerate_v1_fixture -- --ignored --nocapture`

## §16 exception-matrix usage

| ID | Trigger observed | Action taken | Evidence |
|---|---|---|---|
| PA-M1-02 | `AcceptedOp`/`MutationLocation` are private to `writer` | Planner, `BatchDelta` and helpers placed in `writer.rs`; no visibility widening | `index/writer.rs` |
| PA-M1-03 | Existing `IndexLimits` builders clamp rather than reject | Batch builders clamp to `[1, ceiling]`; zero can never mean unbounded | `batch_limits_never_allow_unbounded_zero` |
| PA-M1-04 | Single-key `apply(Delete)` on an absent key allocates revision 1 and records a tombstone | Batch delete reproduces it exactly; parity test against `apply(Delete)` | `u02_delete_on_absent_key_matches_single_apply` |
| PA-M1-05 | `BTreeMap` insertion could allocate during install | Full replacement maps built before the boundary, then `mem::replace` | `install_batch` |
| PA-M1-06 | M0 D1/D2 approved but no selector implementation | `Query` target reserved and typed-rejected | `u08_query_target_and_update_action_are_rejected` |
| PA-M1-11 | *Would* stop if the feature marker could not reject before decode | **Not triggered**: `ensure_supported_features()` precedes version parsing; verified in source and by test | `v2_requires_the_new_feature_before_payload_decode`; `segment/format.rs:423,722`; `mutation_state.rs` decode order |
| PA-M1-07 | Real RustFS unavailable here | Local/fake verticals executed; `M1-V04` marked BLOCKED | below |
| PA-M1-08 | No baseline old-reader executable can be built here | Feature-gate evidence captured in-repo; `M1-V05` marked BLOCKED | below |
| PA-M1-13 | Matrix rows need M2/M3/M4 functionality | Typed rejection, future owner preserved | `u08`, `u11` |
| PA-M1-14 | Not triggered — no publication change | `CURRENT`/manifest algorithm untouched | `git diff` scope |

No HARD STOP row was triggered.

## Requirement → test traceability

### Unit matrix (§10)

| ID | Test(s) | Result |
|---|---|---|
| M1-U01 | `u01_empty_batch_is_rejected_before_any_state_change`, `u01_empty_key_list_is_rejected`, `u01_too_many_commands_is_rejected` | PASS |
| M1-U02 | `u02_single_key_action_matrix`, `u02_single_element_key_list_behaves_like_key`, `u02_delete_on_absent_key_matches_single_apply` | PASS |
| M1-U03 | `u03_duplicate_keys_dedupe_by_first_occurrence_but_sort_response` | PASS |
| M1-U04 | `u04_repeated_key_commands_consume_successive_revisions` | PASS |
| M1-U05 | `u05_precondition_truth_table` | PASS |
| M1-U06 | `u06_batch_key_limit_boundaries`, `u06_response_byte_limit_boundaries`, `u06_batch_replay_key_limit_boundaries` | PASS |
| M1-U07 | `u07_idempotent_replay_returns_the_exact_original_outcome`, `u07_replay_survives_commit_and_reopen` | PASS |
| M1-U08 | `u08_query_target_and_update_action_are_rejected` | PASS |
| M1-U09 | `u09_mismatched_document_key_and_invalid_schema_are_rejected` | PASS |
| M1-U10 | `batch_fingerprint_is_stable_and_domain_separated`, `batch_fingerprint_covers_order_keys_actions_and_preconditions`, `batch_fingerprint_distinguishes_field_states_and_patch_operations`, `query_targets_are_fingerprinted_deterministically` | PASS |
| M1-U11 | `u11_action_applicability_is_rejected_before_admission` | PASS |
| M1-U12 | `u12_batch_and_single_key_tokens_share_one_namespace` | PASS |
| M1-U13 | `u13_v1_is_retained_when_eligible_and_upgraded_for_batch_replay` | PASS |
| M1-U14 | `u14_malformed_v2_records_are_typed_rejections` | PASS |

### Adversarial matrix (§11)

| ID | Test(s) | Result |
|---|---|---|
| M1-A01 | `a01_last_command_failure_leaves_state_identical` | PASS |
| M1-A02 | `a02_last_document_exceeding_pending_bytes_rolls_back_whole_batch` | PASS |
| M1-A03 | `a03_revision_overflow_rejects_the_whole_batch` | PASS |
| M1-A04 | `a04_single_over_limit_rejects_without_truncation` | PASS |
| M1-A05 | `a05_cancellation_at_every_position_leaves_no_state`, `a05_presignalled_cancellation_is_reported_first` | PASS |
| M1-A06 | `a06_planner_failure_leaves_writer_retryable` (typed pre-install planner failure, then successful retry) | PASS (no allocation-failure injector exists in this crate; the equivalent pre-install failure class is covered) |
| M1-A07 | `a07_refresh_after_batch_keeps_pinned_reader_stable` | PASS |
| M1-A08 | covered by existing publication tests + `m1_v03_remote_upload_fault_before_current_keeps_old_generation` | PASS |
| M1-A09 | `m1_v03b_remote_concurrent_writer_conflict` | PASS |
| M1-A10 | `baseline_v1_fixture_decodes_under_the_new_reader`, `v2_requires_the_new_feature_before_payload_decode` | PARTIAL — new-reader half PASS; baseline-binary half BLOCKED (PA-M1-08) |
| M1-A11 | `u14_malformed_v2_records_are_typed_rejections` | PASS |
| M1-A12 | `a12_batch_and_single_key_mutations_stay_coherent` | PASS |

### Codec / compatibility (§7)

| Item | Test(s) | Result |
|---|---|---|
| v1 fixture opens under the new reader | `baseline_v1_fixture_decodes_under_the_new_reader` | PASS |
| New writer does not rewrite v1 on open | `u13_v1_is_retained_when_eligible_and_upgraded_for_batch_replay` | PASS |
| First durable batch-replay commit upgrades to v2 + feature | `u13_...` (payload version read from the published sidecar) | PASS |
| New reader replays exact original outcome after reopen | `u07_replay_survives_commit_and_reopen` | PASS |
| Crash before/after `CURRENT` | existing PR 9/13 publication tests; no publication code changed | PASS (unchanged code path) |
| Baseline old reader rejects v2 with a typed error | source-verified ordering + in-repo feature-table test | BLOCKED as a *binary* gate (`M1-V05`) |
| Compaction preserves batch replay / never downgrades | `compaction_preserves_batch_replay_records` | PASS |

### Integration verticals (§12)

| ID | Test | Result |
|---|---|---|
| M1-V01 (memory) | `m1_v01_memory_vertical_slice` | PASS |
| M1-V02 (filesystem) | `m1_v02_filesystem_restart_and_old_generation` | PASS |
| M1-V03 (remote fake) | `m1_v03_remote_fake_batch_admission_makes_no_remote_calls`, `m1_v03_remote_upload_fault_before_current_keeps_old_generation`, `m1_v03b_remote_concurrent_writer_conflict` | PASS |
| M1-V04 (real RustFS) | `m1_v04_real_rustfs_batch_replay_and_generation_consistency` (`#[ignore]`) | **BLOCKED** — no RustFS service in this environment |
| M1-V05 (mixed version) | baseline binary vs upgraded fixture | **BLOCKED** — no baseline binary can be built/executed here (PA-M1-08) |

## Authoritative QA results (§13)

Working tree `dev/atomit-mutation-batch` @ `cd3b9ac` + M1 changes (uncommitted at
time of measurement).

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | **PASS** |
| `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `cargo test --workspace --all-targets` | **PASS** — 1805 passed, 0 failed, 9 ignored |
| `cargo test --workspace --all-targets --all-features` | **PASS** — 1809 passed, 0 failed, 63 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** — total line coverage **91.14%** (region 90.62%, function 87.03%) |
| `cargo doc --workspace --all-features --no-deps` | **PASS** |
| `cargo bench --workspace --no-run` | **PASS** |
| `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 33 passed, 0 failed |
| `git diff --check` | **PASS** |
| `cargo +1.85.0 fmt --all -- --check` | **PASS** |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** |
| `cargo test -p quervant-core --lib` (baseline) | PASS — 627 before, 673 after (+1 ignored regeneration helper) |

Coverage on the new/changed modules (lines):

| Module | Lines | Coverage |
|---|---|---|
| `contract/mutation.rs` | 212 | 98.11% |
| `index/mutation_state.rs` | 2100 | 90.24% |
| `index/writer.rs` | 3738 | 94.22% |
| `index/limits.rs` | 294 | 95.92% |
| `index/error.rs` | 156 | 85.26% |
| `remote/mod.rs` | 1528 | 90.58% |

## Performance

No benchmark claim is made. `cargo bench --workspace --no-run` proves the bench
targets still compile. A three-run single-key `apply()` before/after comparison
was **not** executed on this host; this is recorded as **NOT RUN** and no
regression/win is asserted. The admission path performs no remote I/O during
batch admission, proven dynamically by
`m1_v03_remote_fake_batch_admission_makes_no_remote_calls`.

## Open gates (M1 not accepted)

1. **M1-V04 real RustFS.** Requires the pinned CI service from
   `.github/workflows/ci.yml`:
   `cargo test -p quervant-core --all-features --test m1_batches -- --ignored --test-threads=1`.
   Owner: CI/reviewer with RustFS topology.
2. **M1-V05 baseline old-reader binary.** Requires building the baseline revision
   (`cd3b9ac` / `585a1ee`) as a separate binary and opening an upgraded v2 index
   with it. The new reader's half and the feature-ordering proof are in-repo; the
   *old binary* half is not substitutable (PA-M1-08 explicitly forbids simulating
   it with the new decoder). Owner: reviewer.
3. **Performance evidence.** Three qualified single-key `apply()` runs on one
   host/corpus, per §13. Status: NOT RUN.

M1 must be reported as **PARTIAL / BLOCKED**, not DONE, until gates 1–2 pass.
