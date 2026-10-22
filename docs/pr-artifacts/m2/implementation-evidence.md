# M2 — Lossless explicit-key partial updates: implementation evidence

**Status: M2 + M2-F01 IMPLEMENTED — local and real-RustFS qualification PASS;
pending commit/CI/merge.** M2 is not marked DONE, and `docs/ROADMAP_V01.md`
does not mark it DONE.

- Working branch: `dev/m2-document-patch`
- Current `origin/main`: `ba5c51250e7624c9de9193d44e2e8b74c67594e9`
  (merge of PR #48 / M1 into `main`)
- M2 head before M2-F01: `9138db305bd231af7cd9df6e231e9711bf9e40ab`
- M1 implementation head: `3df332490cd93b34e741854d2963af17c1b7a734`
- Historical pre-M1-merge ref: `85f8d4386b1badf3fae3075c4ba2fa160dfe8383`
  (`refs/pull/48/merge`). M2 originally branched from it while `main` still
  pointed at `cd3b9ac`; `main` now contains M1 at `ba5c512`, and the branch is
  based on that merged baseline.
- M2-F01 fixup production commit: recorded in the final status section after
  commit. All gates below were rerun on the M2-F01 tree.
- Host: Linux x86-64; `rustc 1.98.1` (stable) and `1.85.0` (MSRV)
- Plan revision: `QUERVANT_M2_DETAILED_IMPLEMENTATION_PLAN.md`

## P0 — Baseline and correctness gate

### Merge-base verification (§0)

Current `origin/main` is `ba5c51250e7624c9de9193d44e2e8b74c67594e9`, the
merge of PR #48 / M1. The M2 branch head before this fixup
(`9138db305bd231af7cd9df6e231e9711bf9e40ab`) is a descendant of that merge.
The earlier M2 evidence recorded that `main` still pointed at `cd3b9ac` and
that M2 was based on the clean PR #48 merge ref `85f8d43`; that was accurate at
the time but is **historical and no longer current**. PR #48 is now merged, so
no separate M1 merge action remains before M2.

### Baseline facts

| Item | Actual |
|---|---|
| `git status --short` before work | clean |
| `git rev-parse HEAD` at branch creation | `85f8d4386b1badf3fae3075c4ba2fa160dfe8383` |
| M1 commit `3df3324` ancestor of branch head | YES |
| `cargo test -p quervant-core --lib` before edits | **PASS** — 676 passed, 0 failed, 1 ignored |
| `IndexWriter::apply_batch` | present, `index/writer.rs` |
| `MutationAction::Update(DocumentPatch)` | present but rejected |
| `BatchDelta` / `batch_raw_key_preflight` | present |
| `FEATURE_MUTATION_STATE_V2` | present |
| `RemoteIndexWriter::apply_batch` | present, synchronous delegation |
| Existing M1 suites | `tests/m1_batches.rs`, `tests/m1_compat/run.sh` present |

### M2-F01 fixup — projected patch-result budgeting

**Defect.** `apply_document_patch` used `precheck_patch_admission`, which started
at `base.approx_size()` and added every patch field name/value without
subtracting replaced or removed values. Valid exact-limit `Unset`, smaller and
equal replacements could therefore fail with `ResourceLimit`. A temporary
focused reproduction on the pre-fix tree failed as:

```text
exact-limit shrink must succeed, got Err(ResourceLimit { limit: 16, requested: 29 })
```

That reproduction was removed after recording it; it is baseline defect
evidence, not fix acceptance evidence.

**EX-02 resolution (human-approved).** Verified source:
`FieldValues::Absent.approx_size() == 1`, but `Document::insert(Absent)` removes
the field and `Document::approx_size()` sums only present fields. The approved
document-relative contribution for an absent field is therefore **zero**.
`FieldValues::approx_size()`, `Document::approx_size()`, `Document::insert()`
and public budget semantics are unchanged.

**Implementation.** The cumulative preflight was removed. A private
`check_projected_patch_document_bytes` now computes, before each ordered
insert/clone:

```text
projected = current.approx_size()
          - current_field_document_contribution   // absent = 0
          + new_field_contribution                // Unset = 0
```

using checked `u64` conversions and checked subtraction/addition. It does not
charge field-name bytes, clone the current/set values, or allocate a candidate
document. It is called before `Document::insert`; the existing post-operation
`Fields`/`DocumentBytes` guard, ordered last-write-wins semantics and final
`schema.validate_document` remain authoritative. No public API, budget kind,
format, fingerprint, replay or writer-installation boundary changed.

**Tests added.** Unit tests `m2f01_t01`–`m2f01_t10`, `m2f01_t16` and
`m2f01_ex02_t01`–`m2f01_ex02_t08` cover exact-limit `Unset`/shrink/equal
replacement, +1 rejection, intermediate oversize, shrink-then-grow, repeated
sets, five-state preservation, absent-field set/unset, null/empty contributions,
no configured byte limit and the reachable overflow/over-limit boundary.
Integration tests `m2_f01_t11`–`m2_f01_t14` cover atomic late-batch rejection
with retry, exact-limit commit/reopen/query, replay after reopen/conflict, and
pending/flushed/committed source equivalence. A writer unit test exercises
`Set` of a previously absent field at the exact budget followed by `Unset` of a
present and an absent field.

**Failure classification note.** The previously observed MSRV failure of
`search::term_fst::tests::preflight_work_limit_prevents_build` is a
test-isolation flake: `BUILD_INVOCATIONS` is a process-global counter reset by
two concurrently scheduled tests and incremented by `TermFst::build`. A
temporary two-thread race harness demonstrated the assertion failing with
`build_invocations() == 1`; it was removed after recording the evidence. The
actual two-test and module stress runs passed (500 + 100 repetitions). No M2
production code is involved.

### Source inventory verified for M2

| Symbol | Actual source fact used by M2 |
|---|---|
| `Schema::get` / `Schema::require` | field lookup returns `Option<&FieldDefinition>` / typed `UnknownField`; `Schema::fields()` iterates ascending name order |
| `Schema::validate_document` | validates whole document: field count, document bytes, unknown fields, cardinality, type, JSON depth/duplicates |
| `Document::insert` | `Absent` removes the field; other states are retained exactly |
| `FieldValues::approx_size` | private; made `pub(crate)` for the patch admission bound (PA-M2-07) |
| `MutationLocation` | private writer enum `Pending(usize)` / `Flushed { segment, doc_id }`; no second persistent pointer type added |
| `KeyRow` | committed winner has `status`, `segment_id`, `doc_id`; tombstones have no pointer |
| `CommittedState` | `segments: Vec<SegmentSnapshot>` plus `state: Arc<MutationStateV1>`; winning row lookup is sorted/bounded |
| `SegmentSnapshot::open_reader` | crate-private reader constructor over cloned immutable bytes |
| `SegmentReader::schema` | verified `CodecSchema` |
| `SegmentReader::doc_key` / `stored_doc` | decode `DOC_KEYS` / `STORED`; stored records are cached per reader |
| `SegmentReader::open_columns` / `ColumnReader::value` | columnar value is authoritative and returns `Some(Absent/ExplicitNull/Empty/Single/Multi)` or `None` when the column is absent |
| `SegmentReader::stored_doc` | calls `stored()`, which decodes/caches all stored records for the segment; the whole encoded segment is precharged |
| `IndexLimits::max_snapshot_bytes` | reused as the per-batch aggregate physical-source-byte ceiling |
| `Budgets` / `IndexLimits::budgets` | reused for reconstructed/patched document, field, array and JSON budgets |

No source-level semantic contradiction was found. Schema-legal
`indexed=true, stored=false, columnar=false` fields are confirmed to have no
lossless source; M2 rejects those physical-source documents conservatively.

### Pre-implementation adversarial challenges

1. **Indexed-only field.** A committed document has a legal indexed-only field
   whose value cannot be read from stored/columnar source. Reconstructing only
   stored fields would silently drop it; the patch is rejected schema-wide even
   when the patch overwrites that field.
2. **Same-key repeated Update.** Two `Update` commands in one batch must read the
   first command's patched document, not the committed source. Reading the
   committed source twice would lose the first patch and produce a wrong revision
   chain.
3. **Stale refresh view.** `self.reader()` may lag the writer journal. A Delete
   followed by Insert in the journal must use the latest journal winner; reading
   the refresh snapshot could resurrect an older physical document.
4. **Prior Delete.** Updating a key whose latest winning journal/committed row is
   a tombstone must be `ActionNotApplicable`, never a reconstruction from an older
   segment that still contains the key.
5. **Replay after Delete.** A matching batch idempotency token must replay the
   original durable response even after the key was superseded/deleted and its
   source is no longer reconstructable. Reconstruction happens after replay.
6. **Source mismatch.** A mutation-state pointer whose physical doc id belongs to
   a different logical key, or a stored record key/schema that differs, must fail
   closed with no fallback to another segment.
7. **Late failure.** A failing command after earlier accepted Updates in the same
   batch must leave pending, journal, admitted, replay, refresh and `CURRENT`
   byte-identical.
8. **Budget bypass through reconstruction.** A large committed segment must be
   rejected before decode when the aggregate physical-source-byte ceiling is
   exceeded, and a patch cannot allocate outside the document budget.

## Implemented surface

| File | Change |
|---|---|
| `crates/quervant-core/src/contract/mutation.rs` | Activate single-key `Update`; document ordered patch semantics; add `ReconstructionFailure` and `MutationRejection::ReconstructionUnavailable` with Display/Error coverage. Public target/patch/fingerprint shapes unchanged. |
| `contract/mod.rs` | Export `ReconstructionFailure`. |
| `contract/document.rs` | `FieldValues::approx_size` made `pub(crate)` for checked patch admission. No public API change. |
| `index/reconstruct.rs` (**new, private**) | `SourceMeter`, `validate_patch_shape`, `apply_document_patch`, physical and in-memory lossless reconstruction, checked budget helpers, unit tests. |
| `index/mod.rs` | Private `mod reconstruct;` registration. |
| `index/writer.rs` | `BatchDelta::prospective_documents` (planning-only), Phase A patch-shape validation, Phase B source resolver, pending/flushed/committed reconstruction wrappers, physical-source meter, Update admission/staging, unit tests. No change to `install_batch` boundary or single-key `apply()`. |
| `tests/m1_batches.rs` | Updated only the two M1 assertions that expected `Update` to be unsupported; all other M1 behavior unchanged. |
| `tests/m2_patches.rs` (**new**) | Local memory/filesystem, typed-error/atomicity, fake-remote and real-RustFS verticals. |
| `.github/workflows/ci.yml` | RustFS job runs the ignored M2 real-provider test. |
| `docs/ARCHITECTURE.md`, `docs/ROADMAP_V01.md`, `docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md` | Accurate M2 scope/status; no claim of DONE or merge. |

### Source-of-truth resolver

`IndexWriter::resolve_live_document` follows the prescribed order:

1. the batch's planning-only `prospective_documents` entry for the key;
2. the latest matching operation in `self.journal` (reverse scan), including
   `Pending` and `Flushed` locations;
3. the committed `MutationStateV1` winning `KeyRow` and exactly one matching
   committed segment snapshot.

`self.reader()` is never consulted. A tombstoned/absent winner is
`ActionNotApplicable`. A live in-batch override without a staged complete
document fails closed as `MissingSource` rather than falling through to older
state.

### Reconstruction and patch rules

- Physical source reconstructs every codec schema field in ascending field-id
  order. Stored records are authoritative; columnar values are the fallback.
  A field that is neither stored nor columnar rejects the whole update with
  `UnrecoverableField`, even when the patch overwrites it.
- Missing/invalid column representation is `MissingSource`; key/schema
  mismatches are `SourceMismatch`; corrupt codecs remain `IndexError::Segment`.
- In-memory `SegmentDocument` sources convert their original field map directly,
  without stored-record decoding, so indexed-only fields remain patchable while
  still pending.
- Patches are nonempty, ordered, last-write-wins. `Set(Absent)` is rejected;
  `Unset` is the removal operation and a no-op `Unset` still creates a revision.
  The complete final document is schema-validated and budget-checked.
- Patch admission is conservatively bounded before cloning: source
  `approx_size` plus every `Set` field-name/value and `Unset` field-name size,
  checked against `BudgetKind::DocumentBytes`.

### Budget and cancellation

- `SourceMeter` charges each distinct physical segment's encoded length once,
  before any reader is opened, against `IndexLimits::max_snapshot_bytes` with
  checked addition.
- Patch admission and per-operation document growth are checked against existing
  `Budgets`; the final schema validation is authoritative.
- Cancellation is polled in phases A/B before each command/key and before any
  installation; replay and source reconstruction remain after the replay lookup.
- `install_batch` is unchanged: all reconstruction/patching/validation/staging
  completes before the single non-fallible installation boundary.

## Correctness invariant traceability

| ID | Falsifiable invariant | Evidence | Result |
|---|---|---|---|
| M2-I01 | Update retains every untouched recoverable field/value state | `m2_v01_local_lossless_update_refresh_pit_commit_reopen`, `reconstruct_from_segment_round_trips_stored_and_columnar_values`, `patch_applies_ordered_set_and_unset_with_five_state_fidelity` | PASS |
| M2-I02 | Indexed-only nonstored/noncolumnar physical source never yields a partial replacement | `reconstruct_rejects_indexed_only_physical_field_schema_wide`, `m2_indexed_only_physical_source_is_reconstructed_only_while_in_memory`, `m2_v02_indexed_only_physical_source_is_rejected_schema_wide` | PASS |
| M2-I03 | Source winner respects staged order, journal and committed state | `m2_same_batch_updates_use_staged_documents_and_successive_revisions`, `m2_delete_insert_update_and_replace_update_sequencing`, `m2_update_reads_pending_flushed_and_committed_sources`, `m2_update_delete_sequence_and_tombstone_applicability` | PASS |
| M2-I04 | Ordered exact Set/Unset with five-state fidelity | `patch_applies_ordered_set_and_unset_with_five_state_fidelity`, `m2_unset_of_absent_field_is_an_accepted_new_revision`, `patch_shape_rejections_are_typed_and_bounded` | PASS |
| M2-I05 | Complete document is validated and reindexed | `m2_v01_local_lossless_update_refresh_pit_commit_reopen` (lexical/typed/JSON/geo), `patch_rejects_invalid_final_document_and_budget_overflow` | PASS |
| M2-I06 | Errors/cancellation/resource overflow change no state | `m2_late_failure_leaves_every_writer_field_unchanged`, `m2_v02_public_errors_are_typed_and_atomic`, `m2_revision_overflow_and_cancellation_precede_reconstruction` | PASS |
| M2-I07 | Precondition/revision semantics match M1 | `m2_update_target_matrix_and_precondition_order`, `m2_update_delete_sequence_and_tombstone_applicability`, `m2_revision_overflow_and_cancellation_precede_reconstruction`, M1 `u05`/`a03` | PASS |
| M2-I08 | Durable replay is exact and never reconstructs | `m2_replay_after_delete_and_reopen_does_not_reconstruct`, real RustFS `m2_v04_real_rustfs_patch_reopen_replay` | PASS |
| M2-I09 | Committed/PIT/refresh snapshots are immutable and atomic | `m2_v01_local_lossless_update_refresh_pit_commit_reopen`, `m2_v02_filesystem_restart_preserves_untouched_fields` | PASS |
| M2-I10 | Local and RustFS results agree without admission-time remote I/O | real RustFS `m2_v04_real_rustfs_patch_reopen_replay`; `m2_v03_remote_fake_update_makes_no_admission_io_and_reopens` | PASS |
| M2-I11 | All source/patch work is bounded before installation | `m2_source_byte_meter_rejects_flushed_segment_before_decode`, `m2_v02_source_byte_budget_rejects_before_decode`, patch budget unit test, M1 raw-key ceiling tests | PASS |
| M2-I12 | No on-disk format change; M1/single-key behavior survives | M1 suite (`m1_batches`, `m1_compat/run.sh`), full workspace suite; diff touches no segment/manifest/CURRENT codec | PASS |

### M2-T matrix

| Test ID | Exercise | Where |
|---|---|---|
| T01 | mixed text/typed/JSON/geo update and query | `m2_v01...` |
| T02 | null/empty/multi/absent preservation | `m2_v01...`, `reconstruct_from_segment...`, `patch_applies...` |
| T03 | committed indexed-only rejection | `m2_v02_indexed_only...`, unit indexed-only |
| T04 | indexed-only field not targeted by patch still rejects | `reconstruct_rejects_indexed_only_physical_field_schema_wide` |
| T05 | Insert→Update | `m2_same_batch_updates...` |
| T06 | Update→Update | `m2_same_batch_updates...` |
| T07 | flushed/committed source | `m2_update_reads_pending_flushed_and_committed_sources`, `m2_v02_filesystem_restart...` |
| T08 | Delete→Insert→Update | `m2_delete_insert_update_and_replace_update_sequencing` |
| T09 | repeated fields / left-to-right order | `patch_applies_ordered_set_and_unset_with_five_state_fidelity` |
| T10 | Set(Absent) rejected | `patch_shape_rejections...`, `m2_v02_public_errors...` |
| T11 | Unset missing field | `m2_unset_of_absent_field_is_an_accepted_new_revision` |
| T12 | query before/after lexical/typed/JSON/geo | `m2_v01...` |
| T13 | invalid final type/cardinality | `patch_rejects_invalid_final_document_and_budget_overflow`, `m2_v02_public_errors...` |
| T14 | late failure after earlier planned update | `m2_late_failure...`, `m2_v02_public_errors...` |
| T15 | cancellation | `m2_revision_overflow_and_cancellation_precede_reconstruction`, `m2_v02_public_errors...` |
| T16 | exact/+1 source and patch budgets | `m2_source_byte_meter_accepts_exact_and_rejects_one_over`, `m2_source_byte_meter...`, `m2_v02_source_byte_budget...`, `patch_rejects_invalid_final_document_and_budget_overflow` |
| T17 | expected revision / precondition ordering | `m2_update_target_matrix_and_precondition_order`, M1 `u05` |
| T18 | absent/tombstone target | M1 `u08`, `m2_update_delete_sequence_and_tombstone_applicability` |
| T19 | revision overflow | `m2_revision_overflow_and_cancellation_precede_reconstruction` |
| T20 | replay after delete/reopen | `m2_replay_after_delete_and_reopen_does_not_reconstruct`, real RustFS |
| T21 | token conflict | `m2_replay_after_delete...`, real RustFS |
| T22 | pinned PIT before update | `m2_v01...` |
| T23 | refresh and commit boundaries | `m2_v01...`, filesystem restart |
| T24 | real RustFS update/reopen/replay | `m2_v04_real_rustfs_patch_reopen_replay` |
| T25 | fake-store admission I/O counter | `m2_v03_remote_fake_update_makes_no_admission_io_and_reopens` |
| T26 | oversized source segment rejected before decode | `m2_source_byte_meter...`, `m2_v02_source_byte_budget...` |
| T27 | raw explicit-key budget still enforced for Update | M1 `m1_raw_ceiling_*`, writer raw-preflight unit tests updated for M2 |
| T28 | source key/schema mismatch | `reconstruct_rejects_key_and_schema_mismatch`; existing codec corruption suites |
| T29 | M1 regression | full M1 unit/integration suite |
| T30 | v1/v2 compatibility harness | `crates/quervant-core/tests/m1_compat/run.sh` |

## Mandatory qualification commands (final working tree)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | **PASS** |
| `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `cargo test --workspace --all-targets` | **PASS** — 1843 passed, 0 failed, 9 ignored |
| `cargo test --workspace --all-targets --all-features` | **PASS** — 1847 passed, 0 failed, 64 ignored |
| `cargo test -p quervant-core --all-features --test m2_patches` | **PASS** — 6 passed, 1 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** — **90.65% line coverage** (45096 covered / 49314 lines, 4218 missed); 91.20% region coverage |
| `cargo doc --workspace --all-features --no-deps` | **PASS** |
| `cargo bench --workspace --no-run` | **PASS** |
| `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 33 passed, 0 failed |
| `git diff --check` | **PASS** |
| `cargo +1.85.0 fmt --all -- --check` | **PASS** |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** on rerun — all test binaries, 0 failed |
| `bash crates/quervant-core/tests/m1_compat/run.sh` | **PASS** — 18/18 checks on `91be5e0`; current probe SHA-256 `735353ca…53607`; production code identical to `6556ac6` |
| `bash benchmarks/scripts/m1-single-key-apply.sh cd3b9ac 6556ac6 3` | **PASS (assessment)** — no material single-key `apply()` regression; both configurations inconclusive with overlapping intervals |

### MSRV transient note

The first MSRV all-features run reported one failure in the pre-existing
`search::term_fst::tests::preflight_work_limit_prevents_build` test. The exact
test passed when rerun alone, and the complete MSRV suite passed on rerun. The
test uses a process-global build-invocation counter and resets it while other
tests may run in parallel; this is a pre-existing test-isolation race, not an M2
code path. No M2 test failed.

## Real RustFS qualification (M2-V04)

Topology: the CI-pinned image
`docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
under rootless Podman (Docker unavailable on this host), ephemeral container,
credentials `quervanttest`/`quervantsecret`, bucket `quervant-pr13-ci`, endpoint
`http://127.0.0.1:9000`, region `us-east-1`. `GET /health` returned 200 before
the runs.

```sh
QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
QUERVANT_RUSTFS_REGION=us-east-1 \
QUERVANT_RUSTFS_BUCKET=quervant-pr13-ci \
QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
cargo test -p quervant-core --all-features --test m2_patches -- --ignored --test-threads=1
```

Result: **1 executed, 1 passed, 0 failed, 0 skipped**, repeated **3/3** times
(0.64 s / 0.53 s / 0.54 s). The test asserts: admission performs no remote I/O;
commit publishes the updated generation; a cold empty-cache reader recovers the
updated and untouched stored fields; durable replay after a cold reopen returns
the original revision; a token conflict is rejected; replay still succeeds after
the key is deleted and the delete is committed.

M1/RustFS regression against the same service in the same session:

| Command | Result |
|---|---|
| `cargo test -p quervant-core --all-features --test m1_batches -- --ignored --test-threads=1` | **PASS** — 1 passed |
| `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1` | **PASS** — 3 passed |

The container was removed after the runs. CI must independently rerun the M2
RustFS step before merge; local Podman evidence does not waive that gate.

## Adversarial self-review

| Attack/counterexample | Passing evidence |
|---|---|
| Stale source pointer / stale refresh view | `resolve_live_document` never uses `self.reader()`; `m2_update_reads_pending_flushed_and_committed_sources`; `m2_replay_after_delete...` |
| Same-key staged operation order | `m2_same_batch_updates_use_staged_documents_and_successive_revisions`; `m2_delete_insert_update_and_replace_update_sequencing` |
| Indexed-only field loss | `m2_indexed_only...`; `reconstruct_rejects_indexed_only...`; schema-wide rejection before patching |
| Field-state conflation (absent/null/empty/single/multi) | `reconstruct_from_segment_round_trips_stored_and_columnar_values`; `patch_applies_ordered_set_and_unset_with_five_state_fidelity`; integration five-state projection |
| Patch order / repeated fields | `patch_applies_ordered_set_and_unset_with_five_state_fidelity` |
| Replay after source deletion | `m2_replay_after_delete_and_reopen_does_not_reconstruct`; real RustFS M2 |
| Segment budget overrun | `m2_source_byte_meter...`; `m2_v02_source_byte_budget...` |
| Partial state on late failure | `m2_late_failure...`; `m2_v02_public_errors...` |
| Pinned-reader isolation | `m2_v01...` |
| Real RustFS reopen | `m2_v04_real_rustfs_patch_reopen_replay` (3/3) |

Both entry points are covered: `IndexWriter::apply_batch` through the local
suites and `RemoteIndexWriter::apply_batch` through the fake-remote and real
RustFS suites. A local-only test is not treated as remote evidence.

## Exception matrix usage

| ID | Trigger observed | Action | Evidence |
|---|---|---|---|
| PA-M2-01 | `origin/main` did not contain PR #48 | Verified PR #48 merge ref is clean (zero diff from M1 head), branched from it, recorded deviation | §P0; remote `main` still must merge `85f8d43` before this branch |
| PA-M2-02 | Schema accessor is `get`/`require`, not a named `field` | Used existing accessors | `validate_patch_shape`, tests |
| PA-M2-03 | `MutationLocation` is private and named exactly `Pending`/`Flushed` | Matched existing variants; no new pointer type | `resolve_live_document` |
| PA-M2-04 | Schema-legal indexed-only physical field | Reject whole update as `UnrecoverableField` | indexed-only tests |
| PA-M2-06 | Missing/mismatched physical source | Fail closed with `MissingSource`/`SourceMismatch`/corruption; no fallback | reconstruction mismatch tests |
| PA-M2-07 | `FieldValues::approx_size` private | Made `pub(crate)` only | contract/document.rs |
| PA-M2-08 | Segment decode would exceed source budget | Reject before reader open | source meter tests |
| PA-M2-10 | Matching replay after source deletion | Replay lookup remains before reconstruction | replay tests, RustFS |
| PA-M2-12 | Docker unavailable locally | Used the same pinned image under rootless Podman; CI rerun remains required | RustFS section |
| PA-M2-17 | Conservative patch admission bound may reject replace-heavy patches | Preserved checked conservative bound; tested a budget rejection | patch budget unit test |
| PA-M2-18 | Two M1 tests asserted `Update` unsupported | Updated only those assertions to M2 semantics; all other M1 tests unchanged | `tests/m1_batches.rs`, writer unit tests |

No HARD STOP row was triggered. No persistent format, manifest, `CURRENT`,
mutation-state wire encoding, fingerprint or v2 replay payload changed.

## Residual risks (accepted within M2 scope)

- Physical reconstruction uses `SegmentReader::stored()`, which decodes the
  bounded whole stored section rather than a single record. The encoded segment
  is charged before opening and existing `SegmentLimits` bound the decode; no
  per-document O(1) claim is made.
- The schema-wide conservative rule makes any document with an indexed-only,
  nonstored/noncolumnar field unpatchable after flush/commit, even if that field
  was absent at indexing time. This is intentional because absence cannot be
  proved from the physical source.
- Query-targeted mutation (M3/M4) and the full M5 crash/fault matrix remain out
  of scope. No field-value loss or partial admission is an accepted risk.

## Performance assessment (single-key `apply()` smoke)

Command: `bash benchmarks/scripts/m1-single-key-apply.sh cd3b9ac 6556ac6 3`.
Three runs per revision, identical benchmark source, aggressive Criterion mode
on a shared WSL2 host (load average 2.89–4.66 during the runs).

| Configuration | Baseline median | Current (M2) median | Change | Verdict |
|---|---|---|---|---|
| `single_key_no_token` | 182.080 µs (1820.8 ns/op) | 188.360 µs (1883.6 ns/op) | +3.45% | INCONCLUSIVE — intervals overlap |
| `single_key_with_token` | 222.700 µs (2227.0 ns/op) | 225.340 µs (2253.4 ns/op) | +1.19% | INCONCLUSIVE — intervals overlap |

Script verdict: `M1-PERF: no material regression detected on the single-key
apply() path`. No improvement is claimed. M2 does not modify the single-key
`apply()` path; the batch planner is the only changed writer path, and its
large-segment protections are exercised by the M2 tests. A full new benchmark
campaign is not required by the plan because no measured threshold was exceeded
and the existing hot path was not changed.

## M2-F01 qualification results

Final production/test commit for this fixup:
`2b22bb2d940647199f502f96dba26c0e69eed75f`
(`fix(m2): project patch result size instead of summing inputs`).

| Gate | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| Clippy default + all-features, `-D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 1866 passed, 0 failed, 9 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 1870 passed, 0 failed, 64 ignored |
| `cargo test -p quervant-core --all-features --test m2_patches` | PASS — 10 passed, 1 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **90.75% line coverage** (45513 covered / 49725 lines, 4212 missed) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 passed, 0 failed |
| `git diff --check` | PASS |
| Rust 1.85.0 fmt/Clippy/tests | PASS — 1870 passed, 0 failed, 64 ignored |
| `bash crates/quervant-core/tests/m1_compat/run.sh` | PASS — 18/18; current probe SHA-256 `fdd764dd…a3c` |
| Real RustFS M2 test | PASS — **3/3** runs against the pinned provider |
| M1 RustFS + PR13 remote regression | PASS — 1/1 and 3/3 |

Real RustFS topology: CI-pinned
`docker.io/rustfs/rustfs@sha256:1803faef…b6a3c` under rootless Podman,
credentials/bucket/endpoint identical to the CI `rustfs` job, `GET /health` 200.
The container was removed after the runs. Exact M2 command:

```sh
QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 QUERVANT_RUSTFS_REGION=us-east-1 QUERVANT_RUSTFS_BUCKET=quervant-pr13-ci QUERVANT_RUSTFS_ACCESS_KEY=quervanttest QUERVANT_RUSTFS_SECRET_KEY=quervantsecret cargo test -p quervant-core --all-features --test m2_patches -- --ignored --test-threads=1
```

No new performance benchmark was run: the fixup is confined to patch
admission/size projection and does not change the single-key `apply()` path.
The previously recorded single-key performance smoke remains historical M2
evidence, not a new M2-F01 claim.

## Failure classifications

- **MSRV `term_fst` failure:** classified **test-isolation flake**, not M2.
  `BUILD_INVOCATIONS` is a process-global test-only counter reset by two
  concurrently scheduled tests and incremented by `TermFst::build`. A temporary
  two-thread harness demonstrated the assertion failing with
  `build_invocations() == 1`; the harness was removed after recording the
  evidence. The two-test/module stress runs and the final full MSRV suite passed.
- No introduced regression, feature defect, or environment failure remains in
  the required local gates.

## Final report status

- PR: **#50**, `https://github.com/yduchesne/quervant/pull/50`, open, base
  `ba5c51250e7624c9de9193d44e2e8b74c67594e9`.
- Branch: `dev/m2-document-patch`.
- M2-F01 final production/test commit:
  `2b22bb2d940647199f502f96dba26c0e69eed75f`.
- M2-F01 files changed: `crates/quervant-core/src/index/reconstruct.rs`
  (production fix + tests), `crates/quervant-core/src/index/writer.rs`
  (narrow writer-path regression test only), `crates/quervant-core/tests/m2_patches.rs`
  (integration regressions), this evidence document. No public API, budget enum,
  segment/manifest/CURRENT/mutation-state wire format, remote protocol or
  feature flag changed.
- M2-F01 EX-02 resolution: absent field contributes **zero** to the projected
  document size; `ExplicitNull`/`Empty` retain their existing contribution of
  one. This is recorded in the M2-F01 section above.
- T01–T10/T16 and EX02-T01–T08 unit tests pass; T11–T14 integration tests pass.
  T15 is covered by the unchanged M1 compatibility harness and segment codec
  suite. T12 also covers commit/reopen/query; T13 covers replay/conflict.
- CI: pending the push/final workflow run for this commit. The PR exists, so the
  push triggers the repository workflow; CI is not claimed as PASS until the run
  completes.
- Residual risks: cumulative patch CPU work still has no independent public
  limit (operation count and M1 batch bounds remain the existing governance);
  `Document::approx_size` remains an approximation; physical reconstruction
  still decodes a bounded whole stored section; indexed-only physical fields
  remain conservatively unpatchable. M3–M5 remain out of scope.
- **PR #50 remains open and unmerged; final merge requires explicit human
  authorization.**
