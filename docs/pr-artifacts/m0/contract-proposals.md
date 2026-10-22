# M0 — Contract decision proposals (M0-7)

**Status:** **PROPOSED — NOT IMPLEMENTED.** Nothing in this document exists on
`main`. Every Rust snippet is a compile-plausible *proposal* written against
types that **were** verified at `main` @ `585a1eed033a9328c46872c505fe5aece9a735de`.
No production file, manifest, or codec byte was changed by M0.

Types marked *(verified)* are cited to source. Types marked *(proposed)* do not
exist and must not be referred to as facts.

| Verified type | Source |
|---|---|
| `contract::document::{Document, DocumentKey, FieldValues, IdempotencyKey, MutationIntent, MutationRequest, MutationResponse}` | `crates/quervant-core/src/contract/document.rs:16-311` |
| `contract::value::{FieldType, FieldValue}` | `contract/value.rs:284-296` |
| `contract::query::Query` | `contract/query.rs:503-...` |
| `contract::result::{TopK, Projection, PitId, Sort}` | `contract/result.rs:179-260` |
| `contract::budget::{Budgets, BudgetKind}` | `contract/budget.rs:8-100` |
| `contract::error::QueryError` | `contract/error.rs:159-204` |
| `index::{IndexWriter, IndexLimits, IndexError, ReaderSnapshot}` | `index/mod.rs:32-45` |
| `index::PitHandle` | `index/pit.rs:118-155` |
| `analysis::Cancellation` | `analysis/cancellation.rs:10-13` |

---

## 1. Module placement (naming hazard)

`contract::batch` **already exists and means a batch of *queries***:
`BatchQueryRequest` / `BatchQueryResponse` / `PerQueryOutcome`
(`contract/batch.rs:20-260`; exported at `contract/mod.rs:22-25`). QMA-001's
proposed `MutationBatch` must **not** be added to that module.

**Proposal:** a new module `contract::mutation` for the target/action/patch/
precondition/batch contract, and a new `index::mutation` (or `index::batch`)
planner module. `contract::batch` is left untouched.

---

## 2. Proposed shapes *(PROPOSED — NOT IMPLEMENTED)*

### 2.1 Target, action, precondition

```rust
// crates/quervant-core/src/contract/mutation.rs  (PROPOSED — NEW FILE)

use crate::contract::document::{Document, DocumentKey, FieldValues, IdempotencyKey, MutationIntent};
use crate::contract::query::Query;

/// Which logical documents a command applies to.
#[derive(Debug, Clone, PartialEq)]
pub enum MutationTarget {
    Key(DocumentKey),
    /// Explicit key set. Order is preserved; duplicates are normalised by first
    /// occurrence (matching `IndexWriter::delete_keys_for_retention`).
    Keys(Vec<DocumentKey>),
    Query(QueryMutationSelector),
}

/// A bounded, snapshot-bound query selector.
#[derive(Debug, Clone, PartialEq)]
pub struct QueryMutationSelector {
    pub query: Query,
    /// Hard ceiling on matched keys. Exceeding it is an error, never a truncation.
    pub max_matches: u64,
    /// Durable precondition: the selection must observe exactly this generation.
    pub expected_generation: Option<u64>,
    /// Optional writer-visible selection token (see decision D2).
    pub selection: Option<SelectionToken>,
}

/// Which mutation to perform.
#[derive(Debug, Clone, PartialEq)]
pub enum MutationAction {
    Insert(Document),
    /// Full-document replacement or insertion; preserved current semantics.
    Upsert(Document),
    /// Full-document replacement of an existing key; the key is retained.
    Replace(Document),
    /// Partial update: only the listed fields change.
    Update(DocumentPatch),
    Delete,
}

/// A patch: ordered `Set`/`Unset` operations only.
#[derive(Debug, Clone, PartialEq)]
pub struct DocumentPatch {
    pub operations: Vec<PatchOperation>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum PatchOperation {
    /// Replace the whole five-state value of `field`.
    Set { field: String, values: FieldValues },
    /// Remove `field` entirely (equivalent to `FieldValues::Absent`).
    Unset { field: String },
}

/// Per-target existence/revision precondition.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MutationPrecondition {
    None,
    MustExist,
    MustNotExist,
    ExpectedRevision(u64),
}

/// One ordered command.
#[derive(Debug, Clone, PartialEq)]
pub struct MutationCommand {
    pub target: MutationTarget,
    pub action: MutationAction,
    pub precondition: MutationPrecondition,
}

/// An all-or-nothing batch. There is deliberately no `atomic` field (D3).
#[derive(Debug, Clone, PartialEq)]
pub struct MutationBatch {
    pub commands: Vec<MutationCommand>,
    pub idempotency_key: Option<IdempotencyKey>,
}
```

`DocumentPatch` is a struct wrapping an ordered `Vec` rather than a bare
`Map` because "repeated operations on the same field" must be well defined; see
D7.

### 2.2 Response and error taxonomy

```rust
// PROPOSED — NOT IMPLEMENTED

/// Result for one logical key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationKeyOutcome {
    pub key: DocumentKey,
    pub intent: MutationIntent,
    pub revision: Option<u64>,
    pub replayed: bool,
}

/// Result for one command, in request order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationCommandOutcome {
    pub command_index: u32,
    /// Number of keys the command resolved to (0 for a zero-match selector).
    pub matched: u64,
    /// Per-key outcomes in ascending `DocumentKey` order.
    pub keys: Vec<MutationKeyOutcome>,
}

/// Deterministic, positional batch result.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationBatchResponse {
    pub outcomes: Vec<MutationCommandOutcome>,
    /// True when the whole batch was served from the replay ledger.
    pub replayed: bool,
}
```

Error family — added to `index::IndexError` as **one** new variant so that the
existing `#[non_exhaustive]`-free enum does not grow many arms at once:

```rust
// PROPOSED — NOT IMPLEMENTED

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MutationRejection {
    /// A per-key precondition did not hold.
    PreconditionFailed {
        key: DocumentKey,
        expected: MutationPrecondition,
    },
    /// The selection snapshot is no longer the requested one.
    StaleSelection {
        expected_generation: Option<u64>,
        observed_generation: Option<u64>,
    },
    /// A query upsert matched more than one key.
    AmbiguousQueryUpsert { matched: u64 },
    /// A query selector exceeded its `max_matches` bound.
    MatchLimitExceeded { limit: u64, matched: u64 },
    /// The document cannot be losslessly reconstructed (indexed-only field).
    UnreconstructableDocument { key: DocumentKey, field: String },
    /// The target/action pairing is not permitted.
    UnsupportedTargetAction {
        target: &'static str,
        action: &'static str,
    },
}

// in `index::error::IndexError`
// MutationRejected { rejection: MutationRejection },
```

### 2.3 Entry points *(PROPOSED — NOT IMPLEMENTED)*

```rust
// PROPOSED — NOT IMPLEMENTED
impl IndexWriter {
    /// Validate, select, materialise, meter and stage every command, then admit
    /// the whole batch as one logical unit. Either all commands are admitted or
    /// none are; no revision, token or writer mutation survives a failure.
    pub fn apply_batch(
        &mut self,
        batch: &MutationBatch,
        cancel: &dyn crate::analysis::Cancellation,
    ) -> IndexResult<MutationBatchResponse>;

    /// Convenience delegate to `apply_batch` with a single query-targeted delete.
    pub fn delete_by_query(
        &mut self,
        selector: QueryMutationSelector,
        cancel: &dyn crate::analysis::Cancellation,
    ) -> IndexResult<MutationBatchResponse>;
}

// The remote writer must offer the same contract or remote mode cannot express it.
impl<S: quervant_objectstore::ObjectStore + 'static> RemoteIndexWriter<S> {
    pub fn apply_batch(
        &mut self,
        batch: &MutationBatch,
        cancel: &dyn crate::analysis::Cancellation,
    ) -> IndexResult<MutationBatchResponse>;
}
```

**Do not** add `update_by_query` / `upsert_by_query` as independent engines:
QMA-001 requires them to delegate to the same planner
(`docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md:42`).

### 2.4 Bounds *(PROPOSED — NOT IMPLEMENTED)*

```rust
// PROPOSED — NOT IMPLEMENTED
impl IndexLimits {
    /// Maximum logical keys a single query selector may resolve to.
    pub const fn max_query_matches(&self) -> u64;                 // default: 10_000
    pub const fn with_max_query_matches(self, value: u64) -> Self; // clamped to a ceiling

    /// Maximum commands in one batch.
    pub const fn max_batch_commands(&self) -> u64;                 // default: 1_024
    pub const fn with_max_batch_commands(self, value: u64) -> Self;

    /// Maximum keys persisted per batch replay record.
    pub const fn max_batch_replay_keys(&self) -> u64;              // default: 1_024
    pub const fn with_max_batch_replay_keys(self, value: u64) -> Self;
}
```

Rationale for `IndexLimits` rather than `BudgetKind`: `BudgetKind`
(`contract/budget.rs:8-9`) is a public, non-`#[non_exhaustive]` enum already
coupled to the *query* budget contract; `IndexLimits` (`index/limits.rs:13-30`)
is the operational writer policy and is the documented home of
`max_pending_docs`/`max_replay_entries`-style bounds (G6-1).

---

## 3. Decision table

Legend: **Approval** — `PREAUTHORIZED` means Section 7A of the execution plan
governs and no new human approval is needed for the *proposal*;
`DECISION REQUIRED` means a human must choose before contracts freeze.

### D1 — Query selection snapshot: committed vs writer-visible

**Question:** does a query mutation selector read the last durable generation,
or the writer's volatile refresh view?

**Source evidence (verified):**

* `ReaderSnapshot::generation()` is `Option<u64>` and is `None` for a volatile
  refresh view (`index/snapshot.rs:387-390`; the writer passes
  `self.committed.as_ref().map(|state| state.generation)` at
  `index/writer.rs:434-437`).
* `ReaderSnapshot::view_ordinal()` is process-local and restarts at `0` for
  every `IndexWriter::open` (`index/writer.rs:232`) — so it is **not** a
  cross-call identifier (`index/snapshot.rs:393-395`).
* `ReaderSnapshot::binding_id()` *is* process-wide unique and monotonic
  (`index/snapshot.rs:41-57`, `403-405`) but is never persisted and never leaves
  the process; it is already used to bind typed/unified cursors
  (`search/unified_cursor.rs`).
* `IndexWriter::reader()` returns the published view, falling back to committed
  (`index/writer.rs:457-462`). Capturing it once at plan start is consistent for
  the whole call.

**Options**

| Option | Meaning | Consequence |
|---|---|---|
| **A** | Committed-snapshot selection: selector reads the committed generation only; `expected_generation` is the durable precondition | Simple, portable, durable, testable; a writer-visible change made by an earlier command in the same batch is *not* visible to a later query selector; matches PA-04's "query selectors see one batch-initial selection snapshot" if that snapshot is the committed one |
| **B** | Writer-visible selection: selector reads `writer.reader()` at batch start | Matches the intuitive "delete what I just inserted"; but the resulting view has no durable identity, so a *caller-supplied* precondition can only be `expected_generation` (which may match while the view differs, or be `None` while a generation exists). Requires an opaque writer-minted `SelectionToken` that is meaningful only within one writer handle |

**Analysis for PA-13:** the source **does** prove that a writer-visible snapshot
can be *captured consistently for the duration of one `apply_batch` call* (a
single `Arc<ReaderSnapshot>` clone; `refresh` replaces the published `Arc` and
never mutates the previous one — `index/writer.rs:449-451`). It does **not** prove
that such a snapshot has a stable identifier usable as a caller-supplied
precondition. PA-13 is therefore **conditional and not satisfied for
caller-supplied identification**.

**Compatibility impact:** option A needs no new type beyond `Option<u64>`.
Option B additionally requires `SelectionToken` (opaque, process-local,
non-durable) and must document that a token from a different writer handle or a
different process is rejected, not reinterpreted.

**Recommendation (not approval):** ship **A as the default** and expose **B as an
opt-in mode** selected by supplying `selection: Some(token)` from the same writer.
Document that `expected_generation` alone never identifies a volatile view.

**Approval: DECISION REQUIRED.**

### D2 — Does volatile selection need an identity beyond `expected_generation`?

**Question:** is `expected_generation: Option<u64>` sufficient?

**Source evidence:** as D1. `generation` is `None` for a volatile view; two
distinct volatile views of the same committed generation are indistinguishable
by generation alone. `binding_id` distinguishes them but is process-local.

**Options:** (A) `expected_generation` only, and writer-visible selection is
*not* expressible as a caller precondition (it is only available inside
`apply_batch`); (B) add an opaque `SelectionToken` minted by the writer, valid
only for that writer handle.

**Impact:** (A) is strictly smaller and cannot be misused across processes. (B)
enables optimistic concurrency over volatile views but adds a non-durable public
token whose misuse mode (stale token from an earlier writer) must be a typed
error.

**Recommendation (not approval):** (A) for v0.1. Do not mint a public token
until a writer-visible-selection requirement is demonstrated. **PA-14 →
DEFER-AND-CONTINUE.** **Approval: DECISION REQUIRED.**

### D3 — Batch semantics: atomic-only, no `atomic` flag

**Source evidence:** PA-03 preauthorizes all-or-nothing for v0.1; QMA-001
requires rejecting `atomic=false` if a flag is ever exposed
(`docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md:44`).

**Options:** (A) omit the field entirely (`MutationBatch { commands,
idempotency_key }`); (B) include `atomic: bool` and reject `false`.

**Impact:** (A) makes partial success unrepresentable, which is stronger than
rejecting it at runtime. (B) is a larger public surface with a permanently
failing value.

**Recommendation (not approval):** **(A) — omit `atomic`.** PA-03 satisfied.
**Approval: PREAUTHORIZED (PA-03).**

### D4 — Same-key ordering and repeated keys

**Source evidence:** PA-04; `apply` already supports repeated keys because
`candidate_state_for` overlays `admitted` over committed
(`index/writer.rs:723-736`) and `candidate_rows` overlays the whole journal
(`index/writer.rs:797-846`). `flush` rewrites one `AcceptedOp.location` per
journal row (`index/writer.rs:398-405`), so two ops on one key produce two
journal rows and one winning `KeyRow`.

**Proposal:** preserve command order; each command sees the staged state of all
preceding commands; no coalescing; each admitted command consumes its own
revision. Query selectors always use the batch-initial selection snapshot.

**Impact:** deterministic and consistent with existing revision semantics.
**Approval: PREAUTHORIZED (PA-04).**

### D5 — Query upsert cardinality

**Source evidence:** PA-06. `QueryError` already has `Conflict { key }` and
`IdempotencyConflict { key }` (`contract/error.rs:180-185`) but nothing that
expresses "matched N > 1".

**Proposal:** exactly 1 match ⇒ act on that key; 0 matches ⇒ require an explicit
fallback document whose key is stable; > 1 ⇒ `MutationRejection::AmbiguousQueryUpsert`;
fallback key exists but was not selected ⇒ `MutationRejection::PreconditionFailed`.
The fallback document's key must equal the command's declared fallback key
else `QueryError::InvalidDocument(DocumentError::TypeMismatch{ field: "document.key" })`
(reusing `MutationRequest::validate`'s existing check,
`contract/document.rs:279-283`).

**Approval: PREAUTHORIZED (PA-06).**

### D6 — Multi-match full-document replacement

**Source evidence:** PA-08. A `Document` carries exactly one `DocumentKey`
(`contract/document.rs:141-150`); `MutationRequest::validate` rejects a document
whose key differs from the request key (`contract/document.rs:279-283`). There is
no key-preserving replacement template.

**Proposal:** **reject** `MutationAction::Replace(document)` /
`MutationAction::Upsert(document)` when the target is `Keys` with more than one
key or `Query`. `MutationAction::Update(patch)` may fan out (it preserves keys
by construction). `MutationAction::Delete` may fan out.

**Impact:** a documented v0.1 restriction, not a public-API regression (no such
API exists today). **Approval: PREAUTHORIZED (PA-08) as a safe restriction;
DEFER the key-preserving template design.**

### D7 — Preconditions

**Source evidence:** `KeyStatus::{Live,Deleted}` exists
(`index/mutation_state.rs:37-56`) and `candidate_state_for` returns
`(revision, Option<KeyStatus>)` (`index/writer.rs:723-736`); "absent" is
`None`, "tombstoned" is `Some(Deleted)`, "live" is `Some(Live)`. This means
`MustExist` / `MustNotExist` are **ambiguous by themselves**:
`MustNotExist` could mean "absent" or "absent or tombstoned", and `Insert`
already treats a tombstoned key as insertable (`index/writer.rs:309-313`).
**Proposal:** define explicitly:

| Precondition | Absent | Tombstoned | Live |
|---|---|---|---|
| `None` | allowed | allowed | allowed |
| `MustExist` | reject | reject | allowed |
| `MustNotExist` | allowed | **allowed** (matches current insert semantics) | reject |
| `ExpectedRevision(n)` | reject | require `revision == n` | require `revision == n` |

**Approval: DECISION REQUIRED** — specifically on `MustNotExist` vs tombstone.

### D8 — Patch semantics

**Source evidence:** PA-07. `FieldValues` already distinguishes absent/null/
empty/single/multi (`contract/document.rs:16-95`); `Document::insert` with
`Absent` removes the field (`contract/document.rs:155-161`).

**Proposal:**

* `PatchOperation::Set { field, values }` maps exactly onto
  `Document::insert(field, values)`, so `Set{.., FieldValues::Absent}` ≡
  `Unset{..}` (both remove) — this equivalence must be documented or `Set` must
  reject `Absent`.
* `PatchOperation::Unset { field }` ≡ `FieldValues::Absent`.
* Repeated operations on the same field are applied in list order; the last
  operation wins. This is well defined *because* `DocumentPatch` keeps a `Vec`.
* Identity fields (`document.key`) are not fields, so they cannot be patched;
  attempting `Set{field: <key-like name>}` is just an ordinary schema lookup and
  fails with `DocumentError::UnknownField` unless the schema declares it.
* The patch is validated by constructing the merged `Document` and running
  `Schema::validate_document` (`contract/schema.rs:186-212`) — never by
  validating operations in isolation, because analyzer/index validation is a
  whole-document property for JSON depth and duplicate members
  (`contract/schema.rs:265-301`).
* The patch base must be reconstructed from `STORED` **and** `COLUMNS`
  (R2-1/R2-4); a field with `indexed=true, stored=false, columnar=false`
  ⇒ `MutationRejection::UnreconstructableDocument`.

**Approval: PREAUTHORIZED (PA-07, PA-15) for the rule; DECISION REQUIRED on
whether `Set{values: Absent}` is legal or rejected.**

### D9 — Patch base and the projection trap

**Source evidence:** `Projection::Source` returns only `stored` fields and
silently reports an unstored field as `Absent`
(`search/projection.rs:45-56`, `122-139`). `ProjectionPlan::compile` rejects an
explicitly requested unstored field (`search/projection.rs:90-98`), but the
`Source` variant has no such guard because it filters by `stored` up front.

**Proposal:** the patch engine must **not** use `ProjectionPlan` as its
reconstruction path. It needs a dedicated internal reconstruction that reads
`SegmentReader::stored_doc` (`segment/reader.rs:314-327`) plus
`SegmentReader::open_columns` / `ColumnReader::value`
(`segment/reader.rs:430-436`, `segment/column.rs:638-731`), and it must fail
closed if any schema field is neither stored nor columnar.

**Approval: PREAUTHORIZED (PA-15) as a safe design rule.**
Residual note for M2: consider adding a `Projection::Source` diagnostic so this
trap cannot silently reappear at a public boundary — but that is a public
behaviour change and is **out of M0 scope**.

### D10 — Response determinism and zero-match

* `delete_keys_for_retention` returns `deleted: Vec<DocumentKey>` populated in
  request order after dedupe (`index/writer.rs:1041-1044` is the accessor region;
  the doc contract is `index/writer.rs:968-976`). Query executors already produce
deterministic order: lexical sorts by `DocumentKey` via `BTreeMap`
(`search/execute.rs:1028`), typed/unified sort by explicit total order.

**Proposal:** per-command outcomes in **request order**; per-key outcomes in
**ascending `DocumentKey` order**; a zero-match selector yields
`MutationCommandOutcome { matched: 0, keys: [] }` and is a successful no-op
(PA-05) that consumes no revision. Response size is bounded by
`max_matches` × `max_batch_commands`, which must itself be bounded (D11).

**Approval: PREAUTHORIZED (PA-05) for zero-match; DECISION REQUIRED for the
response-size product bound.**

### D11 — Bounded response and replay

**Source evidence:** the batch *query* response already carries explicit
cumulative byte budgets (`BudgetKind::BatchResponseBytes`,
`contract/budget.rs:26`) and a `BatchExecutionMeter` charging
policy-derived ceilings (`search/batch.rs:48-105`). Nothing equivalent exists for
mutations.

**Proposal:** reuse the *pattern* (not the module): a `MutationResponseLedger`
charging `projected_hit_bytes`-style per-key costs
(`search/projection.rs:218-235`) against a new
`IndexLimits::max_batch_response_bytes`, and a persisted replay record limited
to `max_batch_replay_keys` keys plus a count and a digest. Overflow is an error,
never truncation.

**Approval: DECISION REQUIRED** (this is the concrete form of PA-17/G4-1).

### D12 — Error taxonomy mapping

**Source evidence:** two existing families must be reconciled.
`IndexError` (`index/error.rs:18-116`) owns writer-lifecycle failures;
`QueryError` (`contract/error.rs:159-204`) owns contract failures and already has
`Conflict`, `IdempotencyConflict`, `BudgetExceeded`, `ExpiredCursor`,
`Cancelled{reason}`.

**Proposal:** keep the split and make the boundary explicit:

| Failure class | Error | Rationale |
|---|---|---|
| Malformed request (empty batch, zero commands, missing document, bad patch field) | `QueryError::{InvalidDocument, InvalidQuery, InvalidBatch}` wrapped as `IndexError::Contract` | Existing contract family; `InvalidBatchReason` already exists (`contract/error.rs:140-148`) |
| Precondition/conflict (revision, existence, ambiguous upsert, stale selection) | `IndexError::MutationRejected(MutationRejection)` *(proposed)* | New writer-semantics failures; must not reuse `QueryError::Conflict { key: String }`, which carries only a key |
| Budget/limit | `IndexError::ResourceLimit` (writer bounds) or `MutationRejection::MatchLimitExceeded` (selector bound) | Existing `ResourceLimit` shape is `{limit, requested}` and is already used by `delete_keys_for_retention` |
| Cancellation | `IndexError::Cancelled` before admission | `index/error.rs:52-54` already exists and is used by `compact_with_cancel` |
| Persistence ambiguity | `IndexError::RecoveryRequired` / `RemoteConflict` | Existing, unchanged (`index/writer.rs:684-710`; `remote/mod.rs:261-274`) |
| Corruption | `IndexError::CorruptCommittedState` / `Segment(SegmentError)` | Existing, unchanged |

**Approval: DECISION REQUIRED** on whether adding a variant to `IndexError` is
acceptable given `IndexError` is `#[non_exhaustive]` (`index/error.rs:19`) —
it is, and no downstream breakage results. `QueryError` is **not**
`#[non_exhaustive]`, so it must **not** gain variants; hence the new
`MutationRejection` family lives on `IndexError`.

### D13 — Storage, publication and codec

**Source evidence:** §4–§5 of [`capability-matrix.md`](capability-matrix.md).

**Proposal:** `apply_batch` performs no I/O. All durability remains
`IndexWriter::commit` / `RemoteIndexWriter::commit`. The only on-disk change in
M1–M5 is the replay-record extension, which needs a payload version bump
(`MUTATION_STATE_VERSION` 1 → 2) plus a required-feature version bump because
unknown section kinds are hard errors (`segment/format.rs:876-882`) and the
version field is compared for equality (`index/mutation_state.rs:349-357`).

**Approval: DECISION REQUIRED** (cross-version policy does not exist).

---

## 4. Decision register

Required format from execution-plan §7.

```text
DECISION ID: M0-D1
Question: Is the default query-selection snapshot committed or writer-visible?
Existing code evidence: index/snapshot.rs:387-390 (generation Option, None for volatile);
  index/writer.rs:232 (view_ordinal restarts at 0); index/snapshot.rs:41-57,403-405
  (binding_id process-local); index/writer.rs:457-462 (reader()).
Options (A/B) and trade-offs: A committed-snapshot default — durable, portable,
  testable, no new type. B writer-visible default — intuitive, but the view has no
  durable identity, so a caller premise can only be expected_generation.
Recommended option (not approval): A as default, B as opt-in only if D2 is approved.
Affected invariants and future PRs: INV-04, INV-06, INV-08; M1, M3, M4.
Human approval required: YES
Status: OPEN
```

```text
DECISION ID: M0-D2
Question: Does a volatile (writer-visible) selection need an identity beyond expected_generation?
Existing code evidence: index/snapshot.rs:387-405; index/writer.rs:232;
  search/unified_cursor.rs (binding_id is the existing snapshot-identity mechanism).
Options (A/B) and trade-offs: A expected_generation only, volatile selection not
  caller-expressible. B add an opaque writer-minted SelectionToken (non-durable,
  handle-scoped) plus a typed cross-handle rejection.
Recommended option (not approval): A for v0.1.
Affected invariants and future PRs: INV-04, INV-08; M3, M4.
Human approval required: YES
Status: OPEN
```

```text
DECISION ID: M0-D3
Question: Expose an `atomic` flag on MutationBatch?
Existing code evidence: docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md:44;
  index/writer.rs:977-1039 (existing loop-based helper is not atomic).
Options (A/B) and trade-offs: A omit the field — partial success unrepresentable.
  B include and always reject `false`.
Recommended option (not approval): A.
Affected invariants and future PRs: INV-03; M1.
Human approval required: NO (preauthorized PA-03)
Status: APPROVED (preauthorized)
```

```text
DECISION ID: M0-D4
Question: How are repeated keys and cross-command ordering handled?
Existing code evidence: index/writer.rs:723-736, 797-846, 398-405.
Options (A/B) and trade-offs: A preserve order, no coalescing, one revision per
  command, query selectors bound to the batch-initial snapshot. B coalesce to one
  net effect per key.
Recommended option (not approval): A.
Affected invariants and future PRs: INV-03, INV-04, INV-10; M1.
Human approval required: NO (preauthorized PA-04)
Status: APPROVED (preauthorized)
```

```text
DECISION ID: M0-D5
Question: Query-upsert match cardinality and fallback rules.
Existing code evidence: index/writer.rs:309-313 (insert vs tombstone);
  contract/document.rs:283-289 (document.key must equal the request key).
Options (A/B) and trade-offs: A <=1 match, explicit fallback key on zero matches,
  reject fallback collision not in the selection. B allow ambiguous match (rejected
  by PA-06).
Recommended option (not approval): A.
Affected invariants and future PRs: INV-04; M4.
Human approval required: NO (preauthorized PA-06)
Status: APPROVED (preauthorized)
```

```text
DECISION ID: M0-D6
Question: May Replace/Upsert(document) fan out over multiple matched keys?
Existing code evidence: contract/document.rs:141-150 (one key per Document);
  contract/document.rs:283-289 (mismatched key rejected).
Options (A/B) and trade-offs: A reject multi-match full-document replacement in
  v0.1, allow patch fan-out. B broadcast one keyed document to many keys (would
  violate the identity contract).
Recommended option (not approval): A.
Affected invariants and future PRs: INV-04, INV-05, INV-06; M2, M4.
Human approval required: NO for A (preauthorized PA-08); YES if B is ever wanted.
Status: APPROVED (preauthorized, restriction only)
```

```text
DECISION ID: M0-D7
Question: What does MustNotExist mean for a tombstoned key?
Existing code evidence: index/mutation_state.rs:37-56 (Live/Deleted);
  index/writer.rs:309-313 (Insert permits a tombstoned key);
  index/writer.rs:723-736 (absent = None, tombstoned = Some(Deleted)).
Options (A/B) and trade-offs: A MustNotExist == "not live" (absent or tombstoned),
  consistent with current insert semantics. B MustNotExist == "no row at all",
  which makes re-insert after delete impossible without an extra precondition.
Recommended option (not approval): A.
Affected invariants and future PRs: INV-10; M1, M2.
Human approval required: YES
Status: OPEN
```

```text
DECISION ID: M0-D8
Question: Is `Set { field, values: FieldValues::Absent }` legal, and does it equal Unset?
Existing code evidence: contract/document.rs:160-172 (Absent removes the field);
  contract/document.rs:16-95 (five states).
Options (A/B) and trade-offs: A treat Set(Absent) as Unset (one code path, but two
  spellings of one operation). B reject Set(Absent) and require Unset (single
  spelling, one extra typed error).
Recommended option (not approval): B — reject, so the request unambiguously states
  intent and replay fingerprints cannot collide across two spellings.
Affected invariants and future PRs: INV-05, INV-06; M2.
Human approval required: YES
Status: OPEN
```

```text
DECISION ID: M0-D9
Question: May the patch base come from Projection::Source?
Existing code evidence: search/projection.rs:45-56,122-139 (Source silently omits
  unstored fields and reports them as Absent).
Options (A/B) and trade-offs: A forbids it; add an internal STORED+COLUMNS
  reconstruction and fail closed on indexed-only fields. B reuse Projection::Source
  (silently drops columnar-only fields).
Recommended option (not approval): A.
Affected invariants and future PRs: INV-05; M2.
Human approval required: NO (preauthorized PA-15)
Status: APPROVED (preauthorized)
```

```text
DECISION ID: M0-D10
Question: What bounds the batch response and the persisted replay record?
Existing code evidence: contract/budget.rs:26 (BatchResponseBytes pattern);
  search/batch.rs:48-105 (cumulative response charging);
  index/limits.rs:32-52 (replay/mutation-state budgets); index/mutation_state.rs:217-224.
Options (A/B) and trade-offs: A persist count + request digest + up to
  max_batch_replay_keys keys and reject larger batches. B persist the complete key
  set (unbounded durable growth; would exceed the 32 MiB mutation-state default).
Recommended option (not approval): A.
Affected invariants and future PRs: INV-06, INV-07; M1, M5.
Human approval required: YES
Status: OPEN
```

```text
DECISION ID: M0-D11
Question: How is batch replay persisted on disk?
Existing code evidence: index/mutation_state.rs:34,349-357 (version equality check);
  segment/format.rs:876-882 (unknown section kind = Corrupt);
  segment/format.rs:722-724 (unknown required feature fails closed);
  index/limits.rs:32-52 (budgets/ceilings).
Options (A/B) and trade-offs: A bump MUTATION_STATE_VERSION to 2 with a batch replay
  tail. B same bytes plus a required-feature version bump so old readers fail with a
  typed "unsupported feature" instead of Corrupt. C separate content-addressed
  sidecar referenced by a new manifest field (manifest v3). D no persisted batch
  results (cannot satisfy PA-11 "no re-query").
Recommended option (not approval): B; reject A (worse failure mode) and D (does not
  satisfy PA-11); defer C unless a cross-version policy is adopted.
Affected invariants and future PRs: INV-06, INV-09; M1, M5.
Human approval required: YES
Status: OPEN
```

```text
DECISION ID: M0-D12
Question: Where does the new error/target/action contract live, and how are errors classified?
Existing code evidence: contract/batch.rs (module name already means *query* batch);
  index/error.rs:19 (#[non_exhaustive]); contract/error.rs:159 (QueryError is not).
Options (A/B) and trade-offs: A new contract::mutation module + one new
  IndexError::MutationRejected(MutationRejection) variant; QueryError unchanged.
  B extend QueryError and contract::batch in place.
Recommended option (not approval): A.
Affected invariants and future PRs: INV-03, INV-06; M1–M4.
Human approval required: NO for placement (preauthorized PA-02); YES for the
  `MustNotExist`/`Set(Absent)` sub-questions covered by M0-D7/M0-D8.
Status: OPEN (placement preauthorized)
```

---

## 5. What is explicitly *not* proposed

* No new WAL, journal-on-disk, or second publication protocol (PA-10).
* No change to `CURRENT` bytes, manifest v2, segment codecs, `SegmentCache`, or
  `ObjectStore` contracts.
* No `atomic=false` / partial-success mode (PA-03).
* No distributed coordination, shard routing, vector/ANN, or hybrid retrieval
  (PA-21) — all remain outside M1–M5.
* No change to the existing public single-key `apply`/`insert`/upsert/delete
  semantics or to `delete_keys_for_retention` behaviour (PA-01).
* No new `dyn` dispatch on the admission hot path: the planner is generic over
  `&dyn Cancellation` only, matching the existing executors
  (`analysis/cancellation.rs:10-13`).
