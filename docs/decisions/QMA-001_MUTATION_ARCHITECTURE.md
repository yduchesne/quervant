# QMA-001 — Unified v0.1 mutation architecture

Status: **Approved architectural direction; M0 audit complete, contracts NOT frozen**.
Baseline: `main` at `585a1eed033a9328c46872c505fe5aece9a735de` (M0 re-verification, 2026-10-21; the original approval baseline was `f1efd5f377353561191b0d8a3a10ae6c86226e8d`).
Scope: single-index/single-writer v0.1, no distributed transaction or new WAL.

M0 verification evidence: [`pr-artifacts/m0/verification-report.md`](../pr-artifacts/m0/verification-report.md),
[`capability-matrix.md`](../pr-artifacts/m0/capability-matrix.md),
[`contract-proposals.md`](../pr-artifacts/m0/contract-proposals.md),
[`acceptance-matrix.md`](../pr-artifacts/m0/acceptance-matrix.md).
That audit is **not** a contract freeze: `M0-D1`, `M0-D2`, `M0-D7`, `M0-D8`,
`M0-D10` and `M0-D11` still require human approval. The API block below remains
provisional and must not be treated as a public contract until those decisions
are accepted.

## Verified implementation baseline

- `contract/document.rs`: `MutationIntent::{Insert,Upsert,Delete}`, `MutationRequest` and `MutationResponse`; stable `DocumentKey`; `FieldValues` distinguishes absent, explicit null and empty multi.
- `index/writer.rs`: `IndexWriter::apply` accepts one mutation, validates schema, fingerprints idempotency, checks duplicate insert, allocates checked per-key revision, preflights pending documents/bytes and records journal/replay. `insert` is a wrapper. No public `apply_batch`, query-target mutation or patch method in this writer API.
- `index/mutation_state.rs`: versioned mutation-state sidecar, ordered key/replay rows, revisions, live/deleted status and replay capacity modeling.
- `index/snapshot.rs`: immutable reader snapshots with generation-specific visibility and guarded reader byte reservations.
- `index/writer.rs`: `flush` builds immutable segments, `refresh` publishes volatile snapshot, `commit` installs durable generation through `CURRENT`; writer lock is exclusive for writer lifetime; apply acknowledgement is **not durable**.
- `index/limits.rs`: existing limits include pending docs/bytes, segments per commit, snapshot/mutation-state bytes, replay entries/bytes.
- `tests/pr09_mutations.rs`: key-level revision, tombstone, idempotency, refresh and durability regression coverage.

These observations do not prove repository-wide absence of additional helpers. M0 must inspect search executors, projections, storage codecs, query batching, all writer tests, remote persistence and failure paths before implementing missing pieces.

## M0 source-verified corrections

Re-verified against `main` @ `585a1eed033a9328c46872c505fe5aece9a735de`. Only
facts that the source **disproved or refined** are recorded here; unapproved
design choices are untouched and remain provisional.

1. **`delete_keys_for_retention` exists and is *not* an atomic batch.** It
deduplicates, bounds and preflights revisions up front, then loops over
`apply` with no rollback (`crates/quervant-core/src/index/writer.rs:977-1039`).
The regression test named "retention validation is atomic" covers only the
preflight cases (`crates/quervant-core/tests/pr09_reclamation.rs:143-174`).
`apply_batch` must not be implemented this way.
2. **Exact match counting already exists.** `SearchResponse::total_hits` /
`TypedSearchResponse::total_hits` / `UnifiedResponse::total_hits` are exact in
all three executors (`search/execute.rs:1062`, `search/typed.rs:523`,
`search/unified.rs:519`). The pure lexical executor already materialises the
complete matching key set internally (`search/execute.rs:1028-1062`).
3. **Duplicate logical keys are a corruption error, not a dedupe case.** Live
uniqueness is guaranteed by the generation live mask
(`index/visibility.rs:87-124`); executors fail closed on a duplicate
(`search/execute.rs:1048-1059`, `search/unified.rs:584-589`).
4. **A volatile refresh view has no durable identity.** `generation` is `None`
for a volatile view and `view_ordinal` restarts at `0` per writer handle
(`index/snapshot.rs:387-405`, `index/writer.rs:232`), so `expected_generation`
alone cannot identify a writer-visible selection snapshot.
5. **There is no PIT resolver.** `IndexError::PitNotFound` is declared but never
raised; PITs are process-local and unaddressable by id. A mutation selector
must not accept a `PitId` in v0.1.
6. **Lossless reconstruction is conditional on the schema.** Stored-source
fields and columnar fields round-trip all five `FieldValues` states; a
schema-legal `indexed=true, stored=false, columnar=false` field has no
recoverable source, and `Projection::Source` silently reports such a field as
`Absent` (`search/projection.rs:45-56`). Patch must fail closed for those
documents.
7. **Batch replay requires a payload version bump.** `MUTATION_STATE_VERSION` is
compared for equality and unknown container section kinds are hard errors
(`index/mutation_state.rs:349-357`, `segment/format.rs:876-882`). No
cross-version compatibility policy exists yet.
8. **`contract::batch` already means a batch of *queries*.** A mutation batch
contract must not be added to that module.

## Approved semantic model

Separate **target** (`Key`, `Keys`, `Query`) from **action** (`Insert`, `Delete`, `Replace`, `UpdatePatch`, `Upsert`). Retain current `MutationRequest` and existing upsert-as-complete-document behavior. New contracts must be additive and validate target/action compatibility.

- Delete by key: preserve current absent-key tombstone semantics. Delete by query: only keys actually matched; zero matches is no-op.
- Replace: complete document replacement; omitted fields disappear; key is retained. Update: patch specified fields only, retaining all others.
- Upsert by key: preserve current replacement-or-insertion behavior.
- Upsert by query: at most one matching target; an explicit stable-key fallback document is required for no-match insertion. Reject ambiguous multi-match selection. If fallback key exists but was not selected, reject rather than silently overwrite it.
- Query-based target selection uses one immutable, explicit writer-visible or committed snapshot; enumerate **all** matches within limits, deduplicate and sort by stable key. Never infer complete target cardinality from a paginated top-K result. Query selection is fixed at the batch's initial selection snapshot; explicit-key commands evaluate against ordered staged state.
- Validate per-key expected revision, existence, schema and reconstructed document before admission. Do not overwrite a newer revision than selected.
- For patch: `Set(FieldValues)` and `Unset` initially; distinguish absent/null/empty/multi; validate field type and analyzer/index semantics. Reject any update that cannot reconstruct a complete original document losslessly.

## API design (provisional until M0 verification)

```rust
enum MutationTarget { Key(DocumentKey), Keys(Vec<DocumentKey>), Query(QueryMutationSelector) }
enum MutationAction { Insert(Document), Delete, Replace(Document), Update(DocumentPatch), Upsert(Document) }
struct QueryMutationSelector { query: Query, max_matches: u64, expected_generation: Option<u64> }
enum MutationPrecondition { None, MustExist, MustNotExist, ExpectedRevision(u64) }
struct MutationCommand { target: MutationTarget, action: MutationAction, precondition: MutationPrecondition, idempotency_key: Option<IdempotencyKey> }
struct MutationBatch { commands: Vec<MutationCommand>, atomic: bool, idempotency_key: Option<IdempotencyKey> }
```

`IndexWriter::apply_batch` is the authoritative new entry point; convenience `delete_by_query`, `update_by_query` and `upsert_by_query` delegate to the same planner. Exact Rust types, query API and batch response are subject to compatibility audit. The initial v0.1 contract guarantees atomic batches; `atomic=false` must be rejected until partial-success semantics are separately approved.

## Atomicity, isolation and persistence invariants

1. Plan, select, materialize, validate, meter and stage *all* operations before mutating live writer state. Do not loop over existing `apply` for atomic batches.
2. A failed batch (validation, budget, cancellation, conflict, overflow) admits zero mutations and consumes zero revisions/idempotency tokens.
3. A successful batch admits as one logical unit to volatile writer state; no intermediate refresh may expose a prefix. Deterministic command ordering and revision allocation.
4. `refresh` exposes all accepted batch changes or none; earlier snapshots and PITs remain unchanged.
5. Durable commit remains the existing immutable segment + mutation-state + manifest + authoritative `CURRENT` publication protocol. No new WAL, no in-place segment modification, no automatic stale writer-lock stealing.
6. Pre-`CURRENT` failure must preserve previous durable generation; ambiguous publication and writer-poisoning behavior must match existing writer implementation, not be weakened.
7. Replaying a committed batch idempotency token must return original result without rerunning its query against newer data. Different canonical request under same token conflicts. Durable replay records must remain bounded and version-compatible.
8. A batch may contain ordered commands against the same key; conflicts and preconditions are evaluated against staged state. Query selectors always refer to the batch's initial selection snapshot.

## Resource governance

Reuse existing query and batch work-meter infrastructure where supported. Enforce max matches, scanned candidates, total query work, materialized document bytes, patch bytes, logical operation count, staged bytes, deadline/cancellation and existing `IndexLimits` (pending docs/bytes, segments, replay ledger, mutation state, snapshot and storage). Overflow is an **error**, not a truncated successful mutation. Check arithmetic, reserve before allocation, release on all failure paths. Bound remote object materialization and respect existing storage/cache constraints.

## M0 mandatory source-level verification gates

M0 audit status per gate (evidence in
[`pr-artifacts/m0/verification-report.md`](../pr-artifacts/m0/verification-report.md) §3).
These boxes stay **unchecked** until the dependent human decisions are accepted;
an audited gate is not a frozen gate.

| Gate | Audit status | Blocks on |
|---|---|---|
| Reconstruction | GAP | M0-D9 (patch base), M2 scope |
| Query selection | PASS (audit) | M0-D1, M0-D2 |
| Writer atomicity | PASS (audit) | — |
| Batch replay | DECISION REQUIRED | M0-D10, M0-D11 |
| Storage/recovery | PASS (audit); runtime BLOCKED | real RustFS in M5 |
| Tests | PASS (audit) | — |
| Visibility semantics | DECISION REQUIRED | M0-D1, M0-D2 |
| Capability reuse | PASS (audit) | — |
- [ ] Confirm full-fidelity document reconstruction for every indexed/stored type (lexical, typed, JSON, geospatial), including old generations and null/empty states; identify unsupported field schemas.
- [ ] Inspect query planner/executor, batch APIs and pagination for complete key enumeration, compound predicates, snapshot binding, work meters, cancellation and duplicate-hit handling.
- [ ] Inspect `commit`, `candidate_state`, refresh, merge, retention and writer poisoning under all fault paths; define precise atomic staging boundary.
- [ ] Inspect mutation sidecar codec and replay fingerprint/versioning; design backward-compatible batch replay encoding and bounded result retention.
- [ ] Inspect local/remote ObjectStore, RustFS, cache and `CURRENT` recovery; ensure no new publication path.
- [ ] Inventory all relevant existing tests and identify exact new regression/fault-injection cases; retain >=85% production Rust line coverage gate.
- [ ] Resolve whether committed versus writer-visible query selection should be the default, and how expected generation/revision preconditions are represented.
- [ ] Confirm no undocumented capability is being reimplemented; update API examples to actual repository types.

## M0 decision approvals — 2026-10-22

Approved: D1 committed-snapshot selection; D2 no public volatile selection tokens; D7 MustNotExist accepts absent/tombstoned; D8 reject Set(Absent), use Unset; D10 bounded atomic response/replay rejection. D11 durable replay compatibility and upgrade policy is approved: new readers accept v1; old readers fail with a typed unsupported-feature error on upgraded v2; the first durable batch-replay commit publishes v2 payload plus required-feature metadata atomically through the existing commit/CURRENT protocol, without rewriting on open. Cross-version, crash, and real-RustFS qualification remain implementation gates. See the complete policy in `docs/pr-artifacts/m0/contract-proposals.md` D13. M0 architectural decisions are resolved; no M1 implementation is included in this PR.

## Implementation PR sequence

- **M1 Atomic batches:** staged journal, key-state/revision/idempotency ledger, admission rollback and limits. Acceptance: no prefix admission or revision leaks; single-key compatibility.
- **M2 Partial updates:** full-document reconstruction, set/unset patches, type validation and reindexing. Acceptance: exact preservation of untouched fields and JSON/geo/typed/lexical behavior.
- **M3 Delete by query:** bounded snapshot target resolution, cardinality/overflow detection, dedupe, revision checks and atomic tombstones. Acceptance: zero-match no-op, full target deletion, unchanged PITs.
- **M4 Update/replace/upsert by query:** reuse planner, enforce <=1 match for query upsert, explicit fallback key and conflicts. Acceptance: no ambiguous insertion or silent overwrite.
- **M5 Qualification:** local/memory/RustFS equivalence, crash/fault injection, idempotency replay after reopen, budget/cancellation, old generation/PIT isolation, >=85% coverage.

No implementation PR should be started before M0 verification gates are closed and contracts are frozen. Estimates: M0 0.5–1 day; M1–M5 6–10 days total with coding agent, contingent on reconstruction and replay compatibility findings.

## M1 implementation status — 2026-10-22 (branch `dev/atomic-mutation-batch`, PR #48)

**DONE — implemented and locally qualified. All M1 acceptance gates PASS.**

M1 is implemented on `dev/atomic-mutation-batch` on top of base
`cd3b9ac610e35628587faf38780fda778d53cd94` (M0 PR #47 merged). Evidence and the
per-command results are in
[`pr-artifacts/m1/implementation-evidence.md`](../pr-artifacts/m1/implementation-evidence.md).

Implemented (see the evidence file for exact files and tests):

- `contract::mutation`: `MutationTarget` (`Key`/`Keys`/reserved `Query`),
  `MutationAction` (`Insert`/`Upsert`/`Replace`/reserved `Update`/`Delete`),
  `MutationPrecondition`, `MutationBatch`, deterministic bounded
  `MutationBatchResponse` and typed `MutationRejection`. No `atomic` flag and no
  public selection token.
- `IndexWriter::apply_batch` with a **prospective delta** and exactly one
  non-fallible installation point. No loop over `apply()`; no writer mutation
  before full preflight.
- Bounded writer-policy limits (`max_batch_commands`, `max_batch_keys`,
  `max_batch_replay_keys`, `max_batch_response_bytes`) in `IndexLimits` only —
  `BudgetKind` and `QueryError` enum shapes are unchanged.
- Durable, bounded batch idempotency replay in a v2 mutation-state payload with
  the `FEATURE_MUTATION_STATE_V2` required feature. Readers accept v1; the first
  durable batch-replay commit upgrades to v2 through the existing
  commit/`CURRENT` protocol and is never downgraded. Compaction preserves batch
  replay records.
- `RemoteIndexWriter::apply_batch` as synchronous delegation; remote publication
  remains `commit`-only.

Correctness evidence (executed locally, both `1.98.1` and `1.85.0`):
`cargo fmt`, Clippy (default and `--all-features`, warnings denied), full
workspace test suite (1809 passed / 0 failed with `--all-features`), 91.14%
workspace production line coverage, `cargo doc`, bench compile, benchmark
scripts and `git diff --check` all PASS.

Qualification gates (all executed, all PASS):

1. `M1-V04` real RustFS — executed against the pinned RustFS image with the CI
   credentials (`M1 atomic batch acceptance (real RustFS)`, now also a CI step);
   3/3 runs passed: no remote I/O during admission, atomic commit, cold
   bootstrap, durable replay, token conflict rejection, pinned-generation
   isolation.
2. `M1-V05` baseline old-reader binary — a separate binary built from pre-M1
   `cd3b9ac` rejects the upgraded index with
   `UnsupportedFeature { feature_id: 11, version: 1 }` (`0x000B` =
   `FEATURE_MUTATION_STATE_V2`), modifies no files, and the current reader still
   replays exactly. The new decoder was never used to simulate the old reader.
3. Performance — two campaigns of three runs each on baseline vs M1 for
   single-key `apply()`: differences are inside host noise (sign flips between
   campaigns; overlapping confidence intervals). No regression and no
   improvement is claimed.

M2–M5 remain PLANNED and are unaffected by this status.

## M2 implementation status — 2026-10-22 (branch `dev/m2-document-patch`)

**IMPLEMENTED — local and real-RustFS qualification PASS; pending review, CI and merge.**

M2 is implemented on top of the verified PR #48 merge ref
`85f8d4386b1badf3fae3075c4ba2fa160dfe8383` (M1 content `3df3324`; zero diff
between the M1 head and the merge ref). Implemented surface:

- `contract::mutation`: `MutationAction::Update(DocumentPatch)` is active for
  exactly one unique explicit key; the query selector remains reserved.
  `MutationRejection::ReconstructionUnavailable { key, field, reason }` and the
  public `Copy + Eq` `ReconstructionFailure` enum are added. No fingerprint or
  v2 replay payload shape changed.
- `index/reconstruct.rs` (**private**): patch-shape validation before
  fingerprint/replay, ordered `Set`/`Unset` with five-state fidelity, checked
  patch admission/work bounds, complete in-memory source conversion, and
  physical source reconstruction over the verified stored/columnar codecs.
  A schema field with `indexed=true, stored=false, columnar=false` rejects the
  whole physical-source update even when the patch does not target it.
- `index/writer.rs`: `BatchDelta::prospective_documents` is a planning-only
  full-document cache for live keys touched by the batch; it is never persisted.
  `resolve_live_document` follows batch-local staged document → reverse journal
  (latest pending/flushed winner) → committed `KeyRow`; `self.reader()` is never
  used. Physical segments are charged against `max_snapshot_bytes` before a
  reader is opened. All reconstruction, patching and validation happen before
  the unchanged M1 non-fallible installation boundary.
- `RemoteIndexWriter::apply_batch` remains synchronous delegation with no
  admission-time remote I/O.
- `tests/m2_patches.rs` adds local memory/filesystem, typed-failure, fake-remote
  and ignored real-RustFS verticals. Unit tests cover same-batch sequencing,
  pending/flushed/committed sources, all five states, all supported field types,
  indexed-only rejection, source mismatch, budget/cancellation and replay after
  delete/reopen.

Known residual risks accepted within M2 scope: physical reconstruction calls
`stored()` (a bounded whole-segment stored decode rather than one record), and
the schema-wide conservative rule makes documents with any indexed-only field
unpatchable after flush/commit. Query-targeted mutation and the M5-wide crash
matrix remain out of scope. Any field-value loss or partial admission is not an
accepted risk.

Evidence: [`pr-artifacts/m2/implementation-evidence.md`](../pr-artifacts/m2/implementation-evidence.md).

## M4 implementation status — 2026-10 (branch `dev/m4-query-mutations`)

**IMPLEMENTED and locally qualified; real-RustFS and final-SHA CI status are
recorded in the M4 evidence document. Not DONE.**

M4 composes the M3 committed-snapshot selection with the M2 patch/replacement
path and adds the narrow query upsert required by the M0 decision approved on
2026-10-22 ("Upsert by query: at most one matching target; an explicit
stable-key fallback document is required for no-match insertion. Reject
ambiguous multi-match selection. If fallback key exists but was not selected,
reject rather than silently overwrite it.").

- **Target/action matrix.** `Query` admits `Delete`, `Update(DocumentPatch)`,
  `Replace(Document)` and the additive
  `MutationAction::QueryUpsert { replacement, fallback }`. `Query + Insert`,
  `Query + Upsert(Document)` and `Key`/`Keys + QueryUpsert` are typed
  `UnsupportedTargetAction`. `MutationAction::Upsert(Document)` is unchanged.
- **Selection.** One committed batch-initial snapshot, the M3
  `select_query_keys` seam and the non-scoring membership visitor are reused.
  Query update/replace apply to the complete selected set; zero matches is a
  successful no-op with no revisions. Query upsert is bounded to one selected
  key: when the effective ordinary bound permits two matches, the second match
  is `AmbiguousQueryUpsert { matched: 2 }`; a configured bound of zero or one
  keeps `MatchLimitExceeded` precedence.
- **Templates and keys.** Query `Replace` and `QueryUpsert.replacement` are field
  templates rebased onto the selected key; the template's own key is inert and
  never persisted for a matched document. `fallback` is inserted unaltered at
  its own key. No key change is ever inferred from query matching.
- **Fallback eligibility and conflicts.** The fallback key must not be live in
  the batch-initial writer-effective state and must not be touched by an earlier
  command in the same batch; both reject atomically. A tombstoned fallback is
  inserted at `previous revision + 1`. The command precondition applies to the
  fallback key, and the fallback is one logical operation for every cap.
- **M4-AD16 (approved response-cardinality amendment).** `matched` is selector
  cardinality and `keys` is the per-key outcome list. The durable v2
  batch-response codec now accepts exactly `matched == keys.len()` or the
  zero-match fallback shape (`matched == 0`, one `Insert` outcome). No payload
  version, feature bit, layout, field order or previously valid byte changed; a
  shared private predicate is used by the encoder and by the decoder after the
  command's outcomes are decoded. Because the durable response does not store
  the action or query, the writer planner is the sole producer of the
  exceptional shape and remains responsible for cardinality, fallback
  eligibility, revision, overlap, preconditions, caps and atomicity.
- **Fingerprints and replay.** Query batches keep the M3 v2 query domain. The
  new action uses additive action discriminant `5` encoding `replacement` then
  `fallback`; discriminants `0..4` and all pre-M4 explicit-key and M3
  query-delete fingerprints are byte-identical (golden-tested). Durable replay
  returns the original response without re-running selection, including the
  zero-match fallback record.
- **Remote parity.** `RemoteIndexWriter::{update_by_query, replace_by_query,
  upsert_by_query}` delegate synchronously to the local planner with no
  admission-time remote I/O.

Evidence: [`pr-artifacts/m4/implementation-evidence.md`](../pr-artifacts/m4/implementation-evidence.md).
