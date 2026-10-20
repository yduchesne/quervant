# QMA-001 — Unified v0.1 mutation architecture

Status: **Approved architectural direction; M0 verification gates remain open**.
Baseline: `main` at `f1efd5f377353561191b0d8a3a10ae6c86226e8d` (2026-10-20).
Scope: single-index/single-writer v0.1, no distributed transaction or new WAL.

## Verified implementation baseline

- `contract/document.rs`: `MutationIntent::{Insert,Upsert,Delete}`, `MutationRequest` and `MutationResponse`; stable `DocumentKey`; `FieldValues` distinguishes absent, explicit null and empty multi.
- `index/writer.rs`: `IndexWriter::apply` accepts one mutation, validates schema, fingerprints idempotency, checks duplicate insert, allocates checked per-key revision, preflights pending documents/bytes and records journal/replay. `insert` is a wrapper. No public `apply_batch`, query-target mutation or patch method in this writer API.
- `index/mutation_state.rs`: versioned mutation-state sidecar, ordered key/replay rows, revisions, live/deleted status and replay capacity modeling.
- `index/snapshot.rs`: immutable reader snapshots with generation-specific visibility and guarded reader byte reservations.
- `index/writer.rs`: `flush` builds immutable segments, `refresh` publishes volatile snapshot, `commit` installs durable generation through `CURRENT`; writer lock is exclusive for writer lifetime; apply acknowledgement is **not durable**.
- `index/limits.rs`: existing limits include pending docs/bytes, segments per commit, snapshot/mutation-state bytes, replay entries/bytes.
- `tests/pr09_mutations.rs`: key-level revision, tombstone, idempotency, refresh and durability regression coverage.

These observations do not prove repository-wide absence of additional helpers. M0 must inspect search executors, projections, storage codecs, query batching, all writer tests, remote persistence and failure paths before implementing missing pieces.

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

- [ ] Confirm full-fidelity document reconstruction for every indexed/stored type (lexical, typed, JSON, geospatial), including old generations and null/empty states; identify unsupported field schemas.
- [ ] Inspect query planner/executor, batch APIs and pagination for complete key enumeration, compound predicates, snapshot binding, work meters, cancellation and duplicate-hit handling.
- [ ] Inspect `commit`, `candidate_state`, refresh, merge, retention and writer poisoning under all fault paths; define precise atomic staging boundary.
- [ ] Inspect mutation sidecar codec and replay fingerprint/versioning; design backward-compatible batch replay encoding and bounded result retention.
- [ ] Inspect local/remote ObjectStore, RustFS, cache and `CURRENT` recovery; ensure no new publication path.
- [ ] Inventory all relevant existing tests and identify exact new regression/fault-injection cases; retain >=85% production Rust line coverage gate.
- [ ] Resolve whether committed versus writer-visible query selection should be the default, and how expected generation/revision preconditions are represented.
- [ ] Confirm no undocumented capability is being reimplemented; update API examples to actual repository types.

## Implementation PR sequence

- **M1 Atomic batches:** staged journal, key-state/revision/idempotency ledger, admission rollback and limits. Acceptance: no prefix admission or revision leaks; single-key compatibility.
- **M2 Partial updates:** full-document reconstruction, set/unset patches, type validation and reindexing. Acceptance: exact preservation of untouched fields and JSON/geo/typed/lexical behavior.
- **M3 Delete by query:** bounded snapshot target resolution, cardinality/overflow detection, dedupe, revision checks and atomic tombstones. Acceptance: zero-match no-op, full target deletion, unchanged PITs.
- **M4 Update/replace/upsert by query:** reuse planner, enforce <=1 match for query upsert, explicit fallback key and conflicts. Acceptance: no ambiguous insertion or silent overwrite.
- **M5 Qualification:** local/memory/RustFS equivalence, crash/fault injection, idempotency replay after reopen, budget/cancellation, old generation/PIT isolation, >=85% coverage.

No implementation PR should be started before M0 verification gates are closed and contracts are frozen. Estimates: M0 0.5–1 day; M1–M5 6–10 days total with coding agent, contingent on reconstruction and replay compatibility findings.
