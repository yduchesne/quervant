# M1 — Atomic explicit-key mutation batches: implementation evidence

**Status: ACCEPTED (locally qualified).** Implementation is complete and all
three qualification gates that were previously open have now **executed and
passed**:

| Gate | Result |
|---|---|
| `M1-V04` real RustFS | **PASS** — executed against the pinned RustFS image (same digest and credentials as CI), 3 consecutive successful runs |
| `M1-V05` baseline old-reader binary | **PASS** — a genuinely separate binary built from the pre-M1 commit rejects the upgraded index with `UnsupportedFeature { feature_id: 11, version: 1 }` (18/18 harness checks) |
| Performance, single-key `apply()` | **PASS (assessment complete)** — 2 independent campaigns × 3 runs × 2 configurations; no material regression detected; differences are statistically inconclusive on this shared host and no improvement is claimed |

No mandatory M1 gate remains blocked. The `.github/workflows/ci.yml` `rustfs` job
now also runs `M1-V04`, so CI re-confirms the remote gate on every push. M5
retains the broader release-level crash/RustFS qualification; nothing here
retroactively waives any gate.

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
| `crates/quervant-core/tests/m1_batches.rs` | **new** integration verticals incl. real-RustFS `M1-V04` |
| `crates/quervant-core/tests/m1_compat/probe.rs` | **new** two-revision compatibility probe (`M1-V05`) |
| `crates/quervant-core/tests/m1_compat/run.sh` | **new** `M1-V05` harness (builds a baseline binary) |
| `crates/quervant-core/benches/writer_mutation.rs` | **new** single-key `apply()` regression benchmark |
| `benchmarks/scripts/m1-single-key-apply.sh` | **new** two-revision performance harness |
| `.github/workflows/ci.yml` | runs `M1-V04` in the pinned RustFS job |

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
| M1-A10 | `baseline_v1_fixture_decodes_under_the_new_reader`, `v2_requires_the_new_feature_before_payload_decode`, `M1-V05` harness | **PASS** — new reader accepts v1; the real pre-M1 binary rejects v2 with a typed unsupported-feature error |
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
| M1-V04 (real RustFS) | `m1_v04_real_rustfs_batch_replay_and_generation_consistency` | **PASS** — see below |
| M1-V05 (mixed version) | `crates/quervant-core/tests/m1_compat/run.sh` | **PASS** — see below |

## M1-V04 — real RustFS qualification

Topology (identical to `.github/workflows/ci.yml`): the `rustfs` job's pinned
image `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
credentials `quervanttest`/`quervantsecret`, bucket `quervant-pr13-ci`, endpoint
`http://127.0.0.1:9000`, region `us-east-1`.

Docker was unavailable on this host, so the **same pinned image digest** was run
under Podman; no other object-store implementation was substituted and the image
version was not changed.

Command (exact):

```sh
QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
QUERVANT_RUSTFS_REGION=us-east-1 \
QUERVANT_RUSTFS_BUCKET=quervant-pr13-ci \
QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
cargo test -p quervant-core --all-features --test m1_batches -- --ignored --test-threads=1
```

Result: **1 test executed, 1 passed, 0 failed, 0 skipped**, repeated 3 times
(0.56 s / 0.50 s / 0.48 s). The service was independently confirmed reachable
(`GET /health` → 200) and the existing real-provider suite passed against the
same service in the same session:
`cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1`
→ 3 passed, 0 failed.

Assertions executed by `M1-V04` (all passed, against the real provider):

- batch admission performs no remote I/O — proven by opening a *fresh* remote
  reader after `apply_batch` but before `commit`: it still observes generation 1;
- `commit` publishes the complete batch atomically (generation 2, all three
  command outcomes present);
- a fresh remote reader observes the committed generation (`beta` → `a`,`b`;
  `seed` deleted);
- a cold reader with an **empty local cache** recovers from RustFS alone;
- reopening the remote index preserves the batch idempotency record
  (`REPLAYED=true`, per-key `replayed=true`, identical revisions);
- replay returns the original result without re-executing mutations;
- the same token with a different payload is rejected with
  `IndexError::IdempotencyConflict`, and the committed replay record still
  answers afterwards;
- the reader pinned at generation 1 keeps its original view.

CI wiring: `.github/workflows/ci.yml` step
`M1 atomic batch acceptance (real RustFS)` runs the same command. Local execution
is the evidence above; the CI job re-confirms it on PR #48.

## M1-V05 — genuine pre-M1 binary compatibility

Harness: `bash crates/quervant-core/tests/m1_compat/run.sh`
(result: **18 passed, 0 failed**).

It creates two detached worktrees, builds two **independent** probe binaries with
separate `CARGO_TARGET_DIR`s, and asserts :

| Revision | `CARGO_TARGET_DIR` | Probe sha256 |
|---|---|---|
| `cd3b9ac610e35628587faf38780fda778d53cd94` (pre-M1) | `…/target-baseline` | `bb809ed7…5ad9bac` |
| `9f16d2acfa2885098b24f33ceb8f4483fdab32ff` (M1) | `…/target-current` | `cecd756f…bebaf43` |

Source-level preconditions asserted before building:

- the baseline tree contains **no** `FEATURE_MUTATION_STATE_V2`;
- the baseline tree contains **no** `IndexWriter::apply_batch`;
- the baseline binary rejects the M1-only `mkbatch` mode with exit 64, proving the
  batch code paths are genuinely absent from it.

Results:

1. the baseline binary created and committed a **genuine v1 index** (`GENERATION=1`);
2. the current binary opened it, read live keys `a,b`, and rewrote **no files**
   (full per-file SHA-256 tree comparison before/after);
3. the current binary replayed the baseline's single-key idempotency token
   (`REPLAYED=true`, `REVISION=Some(1)`) and left the committed generation
   byte-identical;
4. the current binary applied + committed an idempotent batch (`GENERATION=2`),
   observing live keys `a,c` (`b` is a tombstone whose document is not yet
   compacted, so the physical key list is `a,b,c`);
5. the **baseline binary rejected the upgraded index**, exit 3, with the complete
   error chain:

   ```text
   ERROR_DEBUG=Segment(UnsupportedFeature { feature_id: 11, version: 1 })
   ERROR_DISPLAY=segment error: unsupported required feature 11 v1
   ERROR_CHAIN[0]=unsupported required feature 11 v1
   REJECTION=UnsupportedFeature
   ```

   `feature_id: 11` is `0x000B` = `FEATURE_MUTATION_STATE_V2`. It is **not** a
   corruption error and there is no silent v1 fallback. The rejecting binary
   modified **no index files** (tree comparison before/after);
6. the current binary still replays the durable batch exactly after the rejection
   (`REPLAYED=true`, per-key `replayed=true`, unchanged revisions).

No compiled binaries are committed; the harness removes its worktrees and
fixtures on exit (`KEEP_M1_COMPAT_ARTIFACTS=1` retains them for inspection).

## Performance — single-key `apply()` regression assessment

Benchmark: `crates/quervant-core/benches/writer_mutation.rs`; harness:
`bash benchmarks/scripts/m1-single-key-apply.sh`.

Methodology: the same benchmark source is compiled into two isolated worktrees
(`cd3b9ac…` baseline, `9f16d2a…` M1) with separate `CARGO_TARGET_DIR`s. Schema,
documents, requests and idempotency tokens are built in the **untimed** criterion
setup closure; the timed region is exactly 100 successful `IndexWriter::apply`
calls. An independent untimed oracle asserts the expected revision sequence and
pending counters before any measurement. Two configurations are measured so the
M1 token-namespace check is exercised: untokened, and with a distinct token per
mutation. Same machine, toolchain, release profile, corpus, limits and storage
mode (in-memory `Directory`) on both sides.

Environment: Linux 6.18.33.2-microsoft-standard-WSL2 (native `ext2/ext3` temp
filesystem, not `/mnt/c`), Intel Core i7-10750H (12 threads), rustc 1.98.1.
Load average was 1.1–4.4 during the campaigns, so this is a **shared development
host, not a qualified contention-free benchmark host**.

Campaign A (3 runs/config/revision):

| Configuration | Baseline median | M1 median | Change | Verdict |
|---|---:|---:|---:|---|
| `single_key_no_token` | 206.030 µs (2060.3 ns/op) | 195.740 µs (1957.4 ns/op) | −4.99 % | inconclusive (CIs overlap) |
| `single_key_with_token` | 249.060 µs (2490.6 ns/op) | 240.640 µs (2406.4 ns/op) | −3.38 % | inconclusive (CIs overlap) |

Campaign B (3 runs/config/revision, final benchmark source):

| Configuration | Baseline median | M1 median | Change | Verdict |
|---|---:|---:|---:|---|
| `single_key_no_token` | 196.150 µs (1961.5 ns/op) | 198.410 µs (1984.1 ns/op) | +1.15 % | inconclusive (CIs overlap) |
| `single_key_with_token` | 236.760 µs (2367.6 ns/op) | 237.060 µs (2370.6 ns/op) | +0.13 % | inconclusive (CIs overlap) |

Assessment: the measured differences are **not material**. Their sign flips
between campaigns (−5.0 %/−3.4 % then +1.2 %/+0.1 %) while the per-run spread on
the M1 side is 3.3–3.7 %, which places the effect entirely inside host noise. Per
`docs/BENCHMARKING.md` and the M1 plan §13, **no regression and no improvement is
claimed**; the gate is closed as "three qualified runs executed, regression
assessment complete, no material regression detected". A published qualified
baseline would additionally require an operator-confirmed contention-free host.

Regression formula used: `((M1_latency / baseline_latency) - 1) × 100`.

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
| `.github/workflows/ci.yml` RustFS job wiring | M1 step added; the same command executed locally against the pinned image (see `M1-V04`) |
| `cargo test -p quervant-core --all-features --test m1_batches -- --ignored --test-threads=1` | **PASS** — 1 executed, 1 passed, 0 skipped (3/3 runs) |
| `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1` | **PASS** — 3 passed (service sanity) |
| `bash crates/quervant-core/tests/m1_compat/run.sh` | **PASS** — 18 passed, 0 failed |
| `bash benchmarks/scripts/m1-single-key-apply.sh` | **PASS** — 2 campaigns × 3 runs × 2 configurations; no material regression |
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

## Gate closure summary

| Gate | Status | Evidence |
|---|---|---|
| M1-V01 memory vertical | PASS | `m1_v01_memory_vertical_slice` |
| M1-V02 filesystem vertical | PASS | `m1_v02_filesystem_restart_and_old_generation` |
| M1-V03 remote fake vertical | PASS | `m1_v03_*`, `m1_v03b_*` |
| M1-V04 real RustFS | **PASS** | pinned image + CI credentials, 3/3 runs |
| M1-V05 baseline old-reader binary | **PASS** | 18/18 harness checks, typed `UnsupportedFeature { feature_id: 11 }` |
| Performance (single-key `apply()`) | **PASS — assessment complete, no material regression** | 2 campaigns × 3 runs × 2 configurations |

All mandatory M1 gates are closed locally. M5 retains broader release-level
crash/fault/RustFS qualification and is unaffected by this status.
