# M0 — Capability inventory, reuse findings and source-level gates

**Status:** M0 audit artifact — *proposed contracts*, not frozen contracts.
**Baseline:** `main` @ `585a1eed033a9328c46872c505fe5aece9a735de` (verified at execution time).
**Scope:** read-only source inspection. No production code was modified in this packet.

This document carries the deliverables of audit packets **M0-1** (`01_CAPABILITY_MATRIX`),
**M0-2** (`02_RECONSTRUCTION`), **M0-3** (`03_QUERY_SELECTION`), **M0-4** (`04_ATOMICITY`),
**M0-5** (`05_REPLAY_COMPATIBILITY`) and **M0-6** (`06_STORAGE_AND_BUDGETS`).
The packet-specific names are kept as section headings so traceability to the
execution plan is explicit; see the naming reconciliation note in
[`verification-report.md`](verification-report.md).

Classification vocabulary: **EXISTS** / **PARTIAL** / **ABSENT** / **UNVERIFIED**.
Every `ABSENT` claim below carries the search scope that was used.

---

## 1. M0-1 — Complete capability inventory

### 1.1 Document and field contracts — EXISTS

| Capability | Symbol | Evidence | Notes |
|---|---|---|---|
| Stable document key | `contract::document::DocumentKey` | `crates/quervant-core/src/contract/document.rs:102-139` | Validated nonempty, `MAX_BYTES = 1024`, byte-exact `Ord`. |
| Five-state field vocabulary | `FieldValues::{Absent,ExplicitNull,Empty,Single,Multi}` | `contract/document.rs:16-95` | Absent/null/empty/single/multi are distinct and preserved. |
| Single-valued field type set | `FieldValue` (10 variants) | `contract/value.rs:284-296` | Text, Keyword, Bool, I64, U64, F64, Timestamp, Json, GeoPoint, Ip, Cidr. |
| Mutable document | `Document` (`BTreeMap<String, FieldValues>`) | `contract/document.rs:141-196` | `BTreeMap` ⇒ deterministic field order in every fingerprint/encode path. |
| Mutation intent | `MutationIntent::{Insert,Upsert,Delete}` | `contract/document.rs:219-224` | No `Replace`/`Update`/patch variant. |
| Mutation request/response | `MutationRequest`, `MutationResponse` | `contract/document.rs:226-311` | Request carries `key`, `intent`, optional `Document`, optional `IdempotencyKey`; response is `key`/`intent`/`revision`/`replayed`. |
| Opaque idempotency token | `IdempotencyKey` | `contract/document.rs:198-214` | Nonempty; **no length bound** (see §5.4 gap G4-3). |
| Schema closure | `Schema::validate_document` | `contract/schema.rs:186-212` | Every document field must be a declared schema field (`self.require(name)?` at line 208). The reconstructable field universe is therefore closed and finite. |

### 1.2 Writer, flush, refresh, commit — EXISTS

| Capability | Symbol | Evidence |
|---|---|---|
| Single-mutation admission | `IndexWriter::apply` | `index/writer.rs:279-377` |
| Insert convenience wrapper | `IndexWriter::insert` | `index/writer.rs:270-272` |
| Volatile immutable segment build | `IndexWriter::flush` | `index/writer.rs:379-416` |
| Volatile reader publication | `IndexWriter::refresh` | `index/writer.rs:420-454` |
| Current reader view | `IndexWriter::reader` | `index/writer.rs:457-462` |
| PIT pin | `IndexWriter::pin` | `index/writer.rs:465-467` |
| Durable commit | `IndexWriter::commit` | `index/writer.rs:474-634` |
| Commit finalisation | `finish_commit` | `index/writer.rs:636-682` |
| `CURRENT` failure reconciliation / poisoning | `reconcile_current_failure`, `ensure_writable` | `index/writer.rs:684-721` |
| Lossless compaction | `compact`, `compact_with_cancel` | `index/writer.rs:945-975`; `index/merge.rs` |
| Writer lock | `WriterLock` on `index/WRITER_LOCK` | `index/writer.rs:110-166`; `index/current.rs:30` |
| Remote writer parity | `RemoteIndexWriter::{insert,apply,flush,refresh,reader,pin,compact,commit}` | `remote/mod.rs:357-482` |

Explicitly **not** present on `RemoteIndexWriter`: `delete_keys_for_retention`
(see `remote/mod.rs:357-482` for the complete method list). `RemoteIndexWriter`
does carry `IndexLimits` (`remote/mod.rs:251-258`).

### 1.3 Retention deletion — PARTIAL (a maintenance helper, not an atomic batch)

`IndexWriter::delete_keys_for_retention` (`index/writer.rs:977-1039`) already
implements multi-key deletion. It was inspected closely because QMA-001 must not
assert that all batch deletion is absent.

Observed behaviour, in order:

1. `ensure_writable()` (line 978) — refuses a poisoned writer.
2. Rejects an empty/whitespace `reason` (lines 979-983) with
   `IndexError::InvalidRetention`.
3. Deduplicates keys by first occurrence using `BTreeSet<&DocumentKey>`
   (lines 984-991).
4. Rejects `unique.len() > limits.max_pending_docs()` (lines 992-997) with
   `IndexError::ResourceLimit`.
5. Preflights `revision == u64::MAX` for **every** key before admitting any
   (lines 999-1004) — `IndexError::RevisionOverflow`.
6. **Loops over `self.apply(MutationRequest::delete(key))`** (lines 1005-1007),
   propagating the first error with `?`.

Consequences (this is the important finding):

* The helper is **not** all-or-nothing. Steps 1–5 make the *common* failure modes
  preflight-only, but step 6 has no rollback: if the `n`-th `apply` fails, the
  first `n-1` deletes remain in `journal`/`admitted`/`replay`. QMA-001 §
  "Atomicity, isolation and persistence invariants" #1 explicitly forbids
  "loop over existing `apply`" for atomic batches.
* The only in-loop failure sources that remain after the preflight are
  writer poisoning (already excluded by step 1), `mutation_fingerprint` encode
  failure (`index/mutation_state.rs:515-540`), and `request.validate()` on a
  delete (cannot fail: `contract/document.rs:288-296`). So the practical risk is
  narrow, but the guarantee is structural only for the preflighted cases.
* The existing regression `tests/pr09_reclamation.rs:117-141` (`t38`) exercises
  the happy path; `tests/pr09_reclamation.rs:143-174` (`t39`, "retention
  validation is atomic") proves only the **preflight** cases (empty reason,
  one-over-limit, duplicate normalisation). Neither test injects a mid-loop
  failure. `t39`'s name overstates what it verifies.

**Reuse instruction (PA-01, PA-02):** `delete_keys_for_retention` is the correct
model for *validation order* (dedupe → bound → revision preflight → admit) and
must be preserved with unchanged public behaviour. It is **not** the seam for
`apply_batch`, and `apply_batch` must not be implemented by delegating to it.

### 1.4 Writer-owned mutable state — EXISTS (complete inventory)

`IndexWriter` fields (`index/writer.rs:171-188`):

| Field | Line | Mutated by `apply` | Mutated by `flush` | Mutated by `refresh` | Mutated by `commit` |
|---|---|---|---|---|---|
| `directory` | 172 | — | — | — | writes objects |
| `schema`, `registry`, `limits`, `pins`, `lock` | 173-177 | read | read | read | read |
| `committed: Option<CommittedState>` | 178 | read | read | read | replaced (`finish_commit:636-682`) |
| `journal: Vec<AcceptedOp>` | 179 | **push** (`358-362`) | location rewrite (`398-405`) | read | cleared (`669`) |
| `admitted: BTreeMap<DocumentKey,(u64,KeyStatus)>` | 180 | **insert** (`355-357`) | — | read | cleared (`670`) |
| `replay: BTreeMap<IdempotencyKey,ReplayRow>` | 181 | **insert** (`363-373`) | — | read | cleared (`671`) |
| `pending: Vec<SegmentDocument>` | 182 | **push** (`351`) | cleared (`410`) | read (build-only) | cleared (`672`) |
| `pending_bytes: u64` | 183 | **set** (`352`) | reset (`411`) | read | reset (`673`) |
| `flushed: Vec<PendingSegment>` | 184 | — | **push** (`406`) | read | cleared (`674`) |
| `published: Option<Arc<ReaderSnapshot>>` | 185 | — | — | **set** (`450`) | set (`680`) |
| `next_view: u64` | 186 | — | — | **increment** (`449`) | — |
| `poisoned: bool` | 187 | read | read | read | cleared (`678`) |
| *(lock guard)* | 177 | — | — | — | — |

`AcceptedOp { key, revision, location }` at `index/writer.rs:88-92`;
`MutationLocation::{Pending,Flushed}` at `index/writer.rs:79-86`.

### 1.5 Mutation-state codec and replay ledger — EXISTS (version 1)

| Capability | Symbol | Evidence |
|---|---|---|
| Payload version constant | `MUTATION_STATE_VERSION: u16 = 1` | `index/mutation_state.rs:34` |
| Canonical encoder | `MutationStateV1::encode` | `index/mutation_state.rs:249-331` |
| Strict decoder | `MutationStateV1::decode` | `index/mutation_state.rs:333-481` |
| Key row | `KeyRow { key, revision, status, segment_id, doc_id }` | `index/mutation_state.rs:59-109` |
| Replay row | `ReplayRow { token, fingerprint[32], key, intent, revision }` | `index/mutation_state.rs:113-124` |
| Request fingerprint | `mutation_fingerprint` | `index/mutation_state.rs:515-540` |
| Replay byte model | `replay_bytes` | `index/mutation_state.rs:217-224` |
| Retained byte model | `retained_bytes` | `index/mutation_state.rs:231-245` |
| Sidecar reference in manifest | `Manifest::mutation_state: Option<MutationStateRef>` | `segment/manifest.rs`; writer builds it at `index/writer.rs:541-546` |
| Required feature | `(FEATURE_MUTATION_STATE, 1)` | `segment/format.rs:49`; writer at `index/writer.rs:567-574` |
| Legacy v1 manifest synthesis | `synthesize_legacy_state` | `index/mod.rs:434-458` |

### 1.6 Snapshot, live masks and PIT — EXISTS / PARTIAL

| Capability | Symbol | Evidence |
|---|---|---|
| Immutable reader snapshot | `ReaderSnapshot` | `index/snapshot.rs:270-296` |
| Generation echo | `ReaderSnapshot::generation` | `index/snapshot.rs:387-390` |
| Process-local view ordinal | `ReaderSnapshot::view_ordinal` | `index/snapshot.rs:393-395` |
| Process-wide snapshot identity | `ReaderSnapshot::binding_id` (`NEXT_SNAPSHOT_BINDING`) | `index/snapshot.rs:41-57`, `403-405` |
| Generation-specific live masks | `visibility::build_masks{,_from_readers,_from_readers_cancellable}` | `index/visibility.rs:32-160` |
| Live-mask construction is pointer-validated | key/segment/doc-id/duplicate checks | `index/visibility.rs:87-124` |
| Pinned handle | `PitHandle` | `index/pit.rs:118-155` |
| PIT count bound | `PinCounter` | `index/pit.rs:26-116` |
| PIT **resolver** (`PitId → snapshot`) | — | **ABSENT**; `IndexError::PitNotFound` is declared (`index/error.rs:107-110`) but never constructed outside its own display/`Debug` test (`index/error.rs:282`). Repo-wide `rg -n 'PitNotFound' crates --type rust -g '!tests'` returns only `index/error.rs`. |

### 1.7 Query execution and complete key enumeration — PARTIAL

| Capability | Symbol | Evidence |
|---|---|---|
| Typed query AST (30+ variants) | `contract::query::Query` | `contract/query.rs:503-...` |
| Pure lexical executor | `search::LexicalSearcher::search` → `execute::execute_search` | `search/mod.rs:150-176`; `search/execute.rs:973-1077` |
| Mixed lexical+typed executor | `UnifiedSearcher::search` | `search/unified.rs:134-...`; `collect_mixed` at `318` |
| Pure typed executor | `TypedSearcher::search` | `search/typed.rs:463-...` |
| Ordered serial **query** batch | `search::execute_batch`, `BatchQueryRequest` | `search/batch.rs:34-...`; `contract/batch.rs:125-...` |
| Exact match count | `total_hits` | `search/execute.rs:1062`; `search/unified.rs:519-524`; `search/typed.rs:523-527` |
| Exhaustive key materialisation (lexical only) | `let mut global: BTreeMap<DocumentKey, f64>` | `search/execute.rs:1028-1062` |
| Stored projections | `ProjectionPlan`, `ProjectionLedger` | `search/projection.rs:36-235` |
| Work meters | `SearchWork`, `MixedWorkMeter`, `ScanGuard`, `BatchWorkMeter`, `BatchExecutionMeter` | `search/execute.rs:158-...`; `search/work.rs:24-...`; `search/typed.rs`; `search/batch_meter.rs` |
| Cooperative cancellation | `analysis::Cancellation`, `NeverCancel`, `CancellationFlag` | `analysis/cancellation.rs:1-71` |

### 1.8 Types required by QMA-001 — ABSENT

Search scope: `rg -n '<symbol>' . -g '!target'` over the whole repository
(workspace members, tests, benches, examples, docs, scripts). Only the QMA-001
prose itself matched.

| Symbol | Result | Only match |
|---|---|---|
| `apply_batch` | ABSENT | `docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md:10,42` |
| `MutationBatch` | ABSENT | `QMA-001:39` |
| `MutationTarget` | ABSENT | `QMA-001:34` |
| `MutationAction` | ABSENT | `QMA-001:35` |
| `MutationCommand` | ABSENT | `QMA-001:38` |
| `MutationPrecondition` | ABSENT | `QMA-001:37` |
| `QueryMutationSelector` | ABSENT | `QMA-001:36` |
| `DocumentPatch` / `UpdatePatch` | ABSENT | `QMA-001:21,35` |
| `delete_by_query` / `update_by_query` / `upsert_by_query` | ABSENT | `QMA-001:42` |
| `expected_generation` | ABSENT | `QMA-001:36` |
| `ExpectedRevision` | ABSENT | `QMA-001:37` |
| `max_matches` | ABSENT | `QMA-001:36` |

Also absent, with the same scope:

* No mutation-specific `BudgetKind` variants (`contract/budget.rs:9-28` lists all
  18 variants; none names matched keys, staged mutations, or patch bytes).
* No `IndexError` variant for a stale snapshot, failed precondition, or
  revision conflict (`index/error.rs:18-116` is the complete list).
* No `#[non_exhaustive]` on the contract enums that a batch API would extend:
  `MutationIntent` (`contract/document.rs:220`), `QueryError`
  (`contract/error.rs:159`), `BudgetKind` (`contract/budget.rs:9`), `Query`
  (`contract/query.rs:503`), `Projection` (`contract/result.rs:179`).

### 1.9 Test-only reference oracles — EXISTS (reusable pattern)

`contract/reference.rs` is a `#[cfg(test)]` module of deliberately naive
re-implementations (`exists`, `missing`, `is_null`, `in_matches`, …) used by
contract conformance tests. It is the established pattern for the independent
state-machine oracle that M1–M4 acceptance requires, and it must be extended
rather than duplicated.

---

## 2. M0-2 — Lossless document reconstruction (gate 1 / INV-05)

### 2.1 Trace: original document → stored representation → reconstruction

```text
Document (BTreeMap<String, FieldValues>)
  -> Schema::validate_document            (closed field universe)
  -> SegmentDocument                      (index/writer.rs:1064-1071)
  -> SegmentBuilder:
       STORED   section  <- only fields with FieldOptions::stored     (segment/stored.rs:36-73)
       COLUMNS  section  <- only fields with FieldOptions::columnar   (segment/column.rs:122-...)
       POSTINGS/JSON_PATHS/SPATIAL_POINTS <- derived, lossy for source purposes
  -> SegmentReader:
       stored_doc(doc_id) -> StoredRecord{key, BTreeMap<field_id, FieldValues>}  (segment/reader.rs:314-327)
       column_value(field_id, doc_id) -> Option<FieldValues>                     (segment/reader.rs:382-393)
```

### 2.2 Per-field-type matrix

`stored = true` ⇒ the exact `FieldValues` five-state value is recoverable from
`STORED`. `columnar = true` ⇒ the exact five-state value is recoverable from
`COLUMNS` (`ColumnReader::value` returns `Absent`/`ExplicitNull`/`Empty`/
`Single`/`Multi` — `segment/column.rs:638-731`; `LAYOUT_FIXED_SINGLE` and the
variable layout both carry an explicit state byte per document).

| Field state / type | `stored` | `columnar` (not stored) | neither | Evidence |
|---|---|---|---|---|
| Scalar `Text`, `Keyword`, `Bool`, `I64`, `U64`, `F64`, `Timestamp`, `Ip`, `Cidr` | lossless | lossless | **unrecoverable** | `stored.rs:36-73`; `column.rs:638-731` |
| `Multi` (ordered) | lossless (order preserved) | lossless | **unrecoverable** | `stored.rs:66-71`; `column.rs:686-717` |
| `ExplicitNull` | lossless | lossless | **unrecoverable** | presence bitmap + state byte |
| `Empty` (zero-element multi) | lossless | lossless | **unrecoverable** | `column.rs:658-663` |
| `Absent` (field not set) | lossless by omission | lossless (`STATE_ABSENT`) | indistinguishable from unset | presence bitmap |
| `Json` (nested/scalar arrays, `JsonNumber`) | lossless verbatim | **schema-forbidden** (`SchemaError::ColumnarTypeUnsupported`, `contract/schema.rs:112-117`) | unrecoverable | `stored.rs:66-71` |
| `GeoPoint` / GeoJSON Point | lossless source value; derived KD-tree is separate | lossless | unrecoverable | `segment/spatial.rs` is a derived index only |
| Indexed-only field (`indexed=true, stored=false, columnar=false`) | **not applicable** | **not applicable** | **unrecoverable** | `FieldOptions::new(true,false,false)` is schema-legal (`contract/schema.rs:20-40`); only the FST/postings survive |

Non-obvious verification details:

* Schema closure (`contract/schema.rs:208`) means an undeclared field can never
  enter a segment, so the matrix above is exhaustive over document content.
* `F64` non-finite values are rejected at `Document::insert`
  (`contract/document.rs:143-158` via `FieldValues::validate`) and re-validated
  by `FieldValue::validate` (`contract/value.rs:318-...`), so stored `F64` is
  always finite and byte-round-trippable.
* Indexed `Json` rejects duplicate object members at validation
  (`contract/schema.rs:288-296`); stored-only `Json` may legally contain
  duplicates and is preserved verbatim. A patch on a stored-only JSON field must
  therefore not "canonicalise" it.
* Compaction does **not** reconstruct documents: `index/merge.rs:1-13` states it
  remaps decoded structures specifically so that "indexed-but-not-stored fields"
  survive. This is the proof that postings are *not* a reconstruction source.
* Legacy (manifest v1, no mutation state) generations reconstruct their **stored
  bytes** identically; only the *revision* is synthesised as `1`
  (`index/mod.rs:434-458`). A patch against a legacy generation therefore cannot
  honour a caller-supplied `ExpectedRevision` matching the original write order.
* `Projection::Source` returns only `stored` fields and silently reports an
  unstored-but-columnar field as `Absent` (`search/projection.rs:45-56`,
  `122-139`). Using a projection as a patch base would therefore silently drop
  columnar-only fields. **This is the single most dangerous reuse trap in M0.**

### 2.3 Existing STORED+COLUMNS merge primitive (important reuse finding)

`index/merge.rs:300-327` already performs exactly the reconstruction M2 needs: for
each surviving physical document it builds a `SegmentDocument` from
`reader.doc_key` + `reader.stored_doc(...).fields` (resolved to field names), then
fills in every `columnar` field still absent via `reader.column_value(field.id, doc)`
and skips `Absent` column values. It is cancellation-aware (`cancel.step(1)`) and
is validated by `a1_t20_lossless_merge_against_document_oracle`
(`src/index/amendment01.rs:1098-1145`).

Why merge can do this without a fail-closed indexed-only check: compaction
**remaps** postings, JSON-path occurrences, field norms and spatial points
structurally rather than re-deriving them from the document
(`index/merge.rs:1-13`), so it never needs the source value of an indexed-only
field. A patch engine does, which is precisely why M2 must add that check.

**Reuse instruction:** M2 should extract/reuse this STORED+COLUMNS merge rather
than write a second reconstruction, and add (a) a `DocumentKey → (segment, doc_id)`
resolution step against the generation state, and (b) the fail-closed
indexed-only-field rule.

### 2.4 Blockers to lossless patching

| ID | Blocker | Evidence | Consequence |
|---|---|---|---|
| R2-1 | A schema-legal field with `indexed=true, stored=false, columnar=false` has no recoverable source | `contract/schema.rs:20-40`; `segment/stored.rs:51`; `segment/column.rs:135-140` | Patch MUST be rejected for any document owning such a field, or the schema must be tightened. |
| R2-2 | No key → `(segment, doc_id)` resolver is exposed to a patch engine | `mutation_state.rs:249-...` rows are private (`mod mutation_state;` in `index/mod.rs:23`); `IndexWriter::committed_state_arc` is `pub(crate)` (`index/writer.rs:901-906`); `ReaderSnapshot` stores masks only, not rows (`index/snapshot.rs:270-296`) | A new read seam is required. It must not become a second publication path. |
| R2-3 | `ReaderSnapshot::stored_keys` / `contains_key` are not liveness checks and are unbounded | `index/snapshot.rs:490-522` iterates every stored record without consulting `effective_live_docs`; `stored_keys` reserves `document_count` entries | `contains_key(deleted_key)` returns `true`. Must not be reused for patch existence checks. |
| R2-4 | Reconstruction from `STORED` alone is lossy for columnar-only fields | `search/projection.rs:45-56` | Patch base must merge `STORED` **and** `COLUMNS`. |
| R2-5 | Legacy generation revisions are synthesised as `1` | `index/mod.rs:434-458` | `ExpectedRevision` semantics must be defined for legacy generations. |

### 2.5 M0-2 conclusion

**Lossless patch is achievable only for documents whose every schema field is
`stored` or `columnar`, and only with a new key→physical-pointer seam plus a
`STORED`+`COLUMNS` merge.** Full-fidelity patching of arbitrary documents would
require a new stored-source format or a schema migration; that is **not**
approved by QMA-001. Classified **PA-15 → DEFER-AND-CONTINUE**: contracts
proposed, format change not started.

---

## 3. M0-3 — Exhaustive query-target selection (gate 2 / INV-04)

### 3.1 Count is exact; key materialisation is not exposed

| Executor | `total_hits` source | Retains all keys? | Evidence |
|---|---|---|---|
| Pure lexical | `global.len()` after building the full `BTreeMap<DocumentKey, f64>` | **Yes**, transiently and privately | `search/execute.rs:1028-1062` |
| Mixed lexical+typed | `checked_add(1)` per matched live doc; only a `top_k + 1` heap is kept | **No** | `search/unified.rs:419-420`, `519-524`, `669-679` |
| Pure typed | `Accumulator::total_hits`; only `top_k + 1` heap entries | **No** | `search/typed.rs:493-498`, `2544-2560`, `2583` |

So: `INV-04`'s "count is exact" half is **already satisfied**; the "select every
matching key" half needs a retention mode, not a new executor.

### 3.2 Duplicate keys are treated as corruption, not deduplicated

Both executors fail closed if one logical key appears twice among live
documents: `search/execute.rs:1048-1059` and `search/unified.rs:584-589` return
`SearchError::CorruptIndex`. Deduplication is therefore a *structural invariant*
of the mutation-state live mask (exactly one `LIVE` winner per key, enforced in
`index/visibility.rs:87-124`), not an algorithm in the executors.

**Consequence for M3/M4:** the "deterministic dedup and sort by stable key"
requirement is already guaranteed if and only if selection reads the
generation-specific live mask through `ReaderSnapshot::effective_live_docs`. A
mutation planner that re-derives liveness (e.g. via `stored_keys`) would break
it. M3 must test the invariant adversarially rather than assume it.

### 3.3 Pagination and top-K hazards

* `next_cursor` is produced only when more rows exist than were returned
  (`search/unified.rs:657-679`), so a page is always a strict prefix.
* `execute_batch` rejects a caller cursor outright (`search/batch.rs:...`, the
  `query.cursor.is_some()` guard returning
  `SearchError::UnsupportedOperator{operator: "batch_cursor_stop_s2"}`), and
  there is no authoritative `PitId → snapshot` resolver (§1.6). This matches the
  PR 14 STOP S2 already recorded in `docs/ROADMAP_V01.md`.
* `TopK::new` rejects `0` (`contract/result.rs:212-222`), so "unbounded" cannot
  be expressed as `top_k = 0`.
* Therefore a query-mutation selector must **not** be implemented as repeated
  pagination. It must be a distinct "enumerate all matches, bounded by an
  explicit `max_matches`, error on overflow" mode.

### 3.4 Snapshot binding available to a selector

| Identity | Durable? | Unique across writer reopens? | Evidence |
|---|---|---|---|
| `generation: Option<u64>` | Yes (durable `CURRENT`) | Yes | `index/snapshot.rs:387-390` |
| `view_ordinal: u64` | No | **No** — `next_view` starts at `0` for every `IndexWriter::open` (`index/writer.rs:232`) | `index/snapshot.rs:393-395` |
| `binding_id: u64` | No | Yes, process-wide monotonic (`NEXT_SNAPSHOT_BINDING`) | `index/snapshot.rs:41-57`, `403-405` |

`generation` is `None` for a volatile refresh view, so `expected_generation`
alone **cannot** identify a writer-visible selection snapshot. PA-13/PA-14 are
therefore **conditional and unresolved**: see `contract-proposals.md` §D1/D2.

### 3.5 Work and cancellation seams reusable by a mutation planner

* `SearchWork::new(limit, cancel)` + `with_scanned_limit` — `search/execute.rs:158-215`.
* `MixedWorkMeter::new(total, typed, scanned, cancel)` with atomic
  preflight→commit against an optional `BatchWorkMeter` sink — `search/work.rs:57-120`.
* `ScanGuard::shared(&mut WorkCharge)` — typed-scan charges.
* Cancellation poll interval `256` work units (`search/work.rs:19`), plus a
  per-document poll in `evaluate_lexical_with` (`search/execute.rs:1797-1800`).
* `analysis::Cancellation` is the single cancellation trait (`analysis/cancellation.rs:10-13`).

### 3.6 M0-3 conclusion

Classification **PA-16 → DEFER-AND-CONTINUE**. A bounded exhaustive enumeration
mode is the M3 prerequisite. It can reuse `evaluate_lexical_with`
(`search/execute.rs:1743-1760`, which already yields every matched
`(doc_id, score)`), `reader.doc_key(doc_id)`, the live masks, `CandidateBudget`,
and the work meters. No new query engine contract is required — so M0-3 is
**not** a STOP.

---

## 4. M0-4 — Writer state, atomic staging and lifecycle (gate 3 / INV-02, INV-03)

### 4.1 `apply` control flow (the exact staging boundary)

`IndexWriter::apply` (`index/writer.rs:279-377`):

| Step | Lines | Mutates writer state? |
|---|---|---|
| `ensure_writable()` (poison check) | 280 | no |
| `request.validate()` | 281 | no |
| `schema.validate_document(...)` | 282-286 | no |
| `mutation_fingerprint(...)` | 287-288 | no |
| replay lookup → replay return / `IdempotencyConflict` | 290-306 | no |
| `check_replay_capacity()` | 307 | no |
| `candidate_state_for(key)` (committed ⊕ admitted) | 308 | no |
| `DuplicateDocument` check | 309-313 | no |
| `revision = previous.checked_add(1)` | 314-316 | no |
| pending count/bytes preflight | 320-340 | no |
| **`self.pending.push(...)`** | **351** | **YES — first mutation** |
| `self.pending_bytes = new_bytes` | 352 | YES |
| `self.admitted.insert(...)` | 355-357 | YES |
| `self.journal.push(...)` | 358-362 | YES |
| `self.replay.insert(...)` | 363-373 | YES |

**Last safe pre-admission point: after line 316 (revision computation), before
line 351.** A batch planner must not begin mutating writer state before it has
completed every command's validation, selection, materialisation, fingerprinting
and metering — i.e. the atomic seam sits exactly where PA-03 requires.

### 4.2 State-transition map

```text
                    apply(command)  [preflight fails] --> unchanged (no admission, no revision)
                    apply(command)  [preflight ok]    --> journal+1, admitted[key], pending(+1 doc), replay(+1)
flush()             pending --> flushed[+1]; journal[*].location rewritten to Flushed
refresh()           committed ∪ flushed ∪ pending(built) --> candidate state
                    -> build_masks (pointer-validated) -> ReaderSnapshot
                    -> published = new, next_view += 1        (failure: published unchanged)
commit()  (success) segments -> mutation-state -> manifest -> atomic CURRENT
                    -> finish_commit: committed replaced, journal/admitted/replay/pending/flushed
                       cleared, poisoned = false, published = new committed snapshot
commit()  (pre-CURRENT failure)  CURRENT still at previous generation
                    -> Err(Storage); writer stays retryable; state NOT cleared
commit()  (ambiguous publication: CURRENT == attempted generation, durability
           unacknowledged, or indeterminate) -> poisoned = true
                    -> Err(RecoveryRequired); every later entry point is refused
compact() (success) install_compacted: committed replaced, poisoned = false,
                    published = new committed snapshot
```

Evidence: `index/writer.rs:379-416` (flush), `420-455` (refresh),
`474-634` (commit), `636-682` (finish), `684-710` (reconciliation),
`712-721` (poison gate), `1018-1040` (install_compacted).

Note that `commit` refuses to run on an empty journal *only* when
`committed.is_some()` (`index/writer.rs:476-486`); the first commit of an empty
index falls through and publishes generation 1.

### 4.3 Rollback requirements for a batch

A batch admission must restore, on any failure: `journal` length, `admitted`
entries, `replay` entries, `pending` length, `pending_bytes`, and must not have
advanced `next_view` or touched `published`. `poisoned` and `committed` are
untouched by any admission path. No fsync, no `CURRENT` write and no segment
build occurs during admission, so an admission rollback is pure in-memory.

### 4.4 Candidate atomicity boundaries, compared

| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| **A. Batch overlay + single swap** | Build a `StagedMutation` holding *delta* vectors/maps; on success extend `journal`/`admitted`/`replay`/`pending` once, in one non-failing pass | Exactly mirrors the existing `candidate_rows` overlay (`index/writer.rs:797-846`); no cloning of committed state; trivially testable rollback (drop the delta); no new durability concept | Requires every command's preflight to be complete before the swap, so the planner must compute final pending count/bytes incrementally |
| **B. Staged immutable plan + checked commit** | Build a fully materialised `MutationPlan` (all `SegmentDocument`s, all `KeyRow`s, all `ReplayRow`s), validate, then apply | Strongest separation of "plan" and "commit"; plan is directly inspectable/replayable | Duplicates `candidate_rows`; doubles peak memory for documents (plan + pending); risks divergence from `flush`/`commit` state derivation |
| **C. Loop `apply` (as `delete_keys_for_retention` does)** | Sequential admission | No new code | **Forbidden by QMA-001 §Atomicity #1**; no rollback; partial prefix visible |

**Recommendation (not approval):** option **A**, with the batch's *last*
validation step being a single checked `preflight_batch_admission` that computes
total pending docs/bytes and replay entries against `IndexLimits`, followed by
one infallible swap. This adds no WAL, no new publication path, and no change to
`CURRENT`/poisoning semantics.

### 4.5 Unresolved atomicity questions

1. Must a batch containing a `Delete` for a key that a *later* command in the
   same batch re-inserts keep both journal entries (two revisions), or is it
   coalesced? PA-04 says "preserve command order; preconditions and revisions see
   preceding staged commands", which implies two revisions and two journal
   entries. Recommendation: **no coalescing**, atomicity applies to visibility
   only. This needs confirmation because `flush` maps `AcceptedOp.location`
   per-op, and two ops on one key produce two journal rows but one winning
   `KeyRow` (`index/writer.rs:797-846`).
2. Does a batch that is a **no-op** (e.g. zero commands, or a query selector
   matching nothing) consume no generation on `commit`? `commit` already treats
   an empty journal as `no_op` when committed state exists
   (`index/writer.rs:476-486`), so the answer should be inherited.
3. Batch cancellation: `apply` has no cancellation parameter. A planner needs
   one before admission; PA-12 requires bounded work, so `&dyn Cancellation`
   should be threaded through the planner only (not stored in writer state).

---

## 5. M0-5 — Replay, fingerprint and codec compatibility (gate 4 / INV-06)

### 5.1 Current on-disk shape (exact)

`MutationStateV1::encode` (`index/mutation_state.rs:249-331`):

```text
container(ContainerKind::MutationState)
  required_features = [(FEATURE_MUTATION_STATE = 0x0008, 1)]
  section(SectionKind::MutationState = 0x000F, aux = 0)
    payload:
      u16  MUTATION_STATE_VERSION (= 1)
      u32  row_count
      row*: len_prefixed_u16(key) u64(revision) u8(status)
            [status==LIVE: len_prefixed_u16(segment_id) u64(doc_id)]
      u32  replay_count
      replay*: len_prefixed_u16(token) [u8;32](fingerprint)
               len_prefixed_u16(key) u8(intent) u64(revision)
```

`fingerprint` covers `intent`, key length+bytes, a `1` marker plus field count
for documents, and for each field `varint(len)+name` then a state byte and typed
scalar encoding (`index/mutation_state.rs:515-560`). It never uses `Debug`,
randomised hashing, or map order (fields come from a `BTreeMap`).

### 5.2 Compatibility constraints that bind any batch-replay design

| Constraint | Evidence | Impact |
|---|---|---|
| `MUTATION_STATE_VERSION` is compared for equality | `index/mutation_state.rs:349-357` | Any new payload field requires a version bump; old readers reject version 2 outright. |
| Unknown **section kinds** are a hard `Corrupt` error | `segment/format.rs:876-882` (`SectionKind::from_raw(...).ok_or(Corrupt)`) | Adding a new section to the mutation-state container makes every older reader reject the whole sidecar. Option "new section" is therefore **not** backward compatible. |
| Unknown **required features** fail closed | `segment/format.rs:722-724`; `index/mutation_state.rs:340` | A new required feature is a clean, explicit version gate — but old readers cannot read the generation at all. |
| Unknown **optional features** are ignored | `format.rs` required/optional split; `parse_container` reads both | An optional-feature addition keeps old readers working. |
| Sections must be strictly ascending by kind and contiguous | `segment/format.rs:880-905` | Ordering is fixed by `SectionKind` discriminants. |
| `ReplayRow` is single-key / single-intent / single-revision | `index/mutation_state.rs:113-124` | Cannot represent a multi-command batch result. |
| Replay capacity is enforced three ways | `index/writer.rs:522-540`; `index/mod.rs:399-414`; `index/limits.rs:32-52` | `max_replay_entries` 100 000 / `max_replay_bytes` 16 MiB / `max_mutation_state_bytes` 32 MiB, with absolute ceilings. |
| Legacy manifests synthesise revisions as `1` | `index/mod.rs:434-458` | Replay rows only exist in v2+ manifests. |

### 5.3 Options for durable batch replay

| Option | On-disk impact | Old-reader behaviour | Verdict |
|---|---|---|---|
| **A. Bump `MUTATION_STATE_VERSION` to 2**, append `batch_count` + batch replay rows (batch token, request digest, per-command result summary) | New payload tail; same section kind; required feature stays `(0x0008, 1)` | Old readers hit the version check and fail with `Corrupt` ⇒ the whole generation becomes unreadable | Requires an explicit cross-version policy that does not exist ⇒ **DECISION REQUIRED** |
| **B. New payload version + new required feature `(0x0008, 2)`** | Same bytes as A but honest feature gate | Old readers fail with a typed "unsupported required feature", which is a *cleaner* failure than `Corrupt` | Preferred shape **if** a version bump is approved |
| **C. Separate content-addressed batch-replay sidecar**, referenced by a new `Manifest` field (`manifest` v3) | New object class + manifest change | Old readers ignore the unknown manifest field only if the manifest decoder tolerates it — it does **not** currently (manifest is versioned and strictly decoded) | Largest blast radius; also creates a second durable artefact |
| **D. Do not persist batch results; persist only the batch token + request digest** and reconstruct the response from the per-key replay rows | None (reuse `ReplayRow`, token = per-command derived token) | Fully compatible | Only works when the response is derivable; the **target key set** of a query selector is not derivable without re-running the query, which PA-11 forbids |

**Recommendation (not approval):** option **B** — bump the payload version and
add a *required* feature version so old readers fail with a precise typed error
rather than `Corrupt`, **and** bound the persisted result set (see G4-1).
Option **A** is the same bytes with a worse failure mode and is rejected.
Option **D** is insufficient because it cannot satisfy PA-11's "no re-evaluation
on replay" for query selectors.

### 5.4 Replay gaps

| ID | Gap | Evidence | Impact |
|---|---|---|---|
| G4-1 | A batch whose query target set is large cannot store per-key results inside the 32 MiB default mutation-state budget | `index/limits.rs:32-52`, `149-196`; `index/mutation_state.rs:217-224` | Need an explicit bound (e.g. persist count + digest + a truncated, clearly-flagged key prefix, or reject batches whose result set exceeds a new `max_replay_result_keys`). PA-11 requires bounded retention; silently dropping keys is forbidden. |
| G4-2 | `MutationIntent` has no ordering/priority for a batch, and `intent_tag` is a `u8` triple | `index/mutation_state.rs:490-508` | Any batch-intent encoding must not reuse `intent_tag` values implicitly. |
| G4-3 | `IdempotencyKey` has no length bound | `contract/document.rs:198-214` | A batch token is persisted in the ledger; an unbounded token is an unbounded durable write. Needs a bound (`DocumentKey::MAX_BYTES`-style) before batch persistence. |
| G4-4 | Replay lookup is `BTreeMap` in memory and binary search on disk | `index/writer.rs:738-746`; `index/mutation_state.rs:181-187` | O(log n) is fine; no gap beyond capacity. |
| G4-5 | No replay-ledger eviction exists | `index/limits.rs:149-196` | Exhaustion is a typed error, never silent eviction — consistent with PA-12, but M1 must state it. |

### 5.5 M0-5 conclusion

**PA-17 → DEFER-AND-CONTINUE / DECISION REQUIRED.** Replay encoding is
compatible-by-extension only through a payload version bump; the container
format forbids "just add a section". No `MutationStateV1` byte was modified in
M0.

---

## 6. M0-6 — Local/remote recovery, storage and budgets

### 6.1 Storage seams (all exists; all reusable; none needs a second path)

| Seam | Evidence | Reuse for batch mutation |
|---|---|---|
| `Directory` (`create`, `open_read`, `exists`, `delete`, `atomic_write`, `sync`, `create_dir_all`, `list`, `file_len`) | `storage/directory.rs:38-100` | Unchanged. A batch adds **no** directory operations. |
| `ObjectStore` (`put`, `get`, `head`, `delete`, capabilities, preconditions) | `quervant-objectstore/src/contract.rs:17-59` | Unchanged. |
| Local commit ordering | `index/writer.rs:589-628` (segments → state → manifest → `CURRENT`, steps 3–6) | Must be reused verbatim. |
| Remote publication ordering | `remote/publication.rs:240-285` (upload immutables → verify references → CAS `CURRENT`) | Must be reused verbatim. |
| Ambiguous remote `CURRENT` | `remote/publication.rs:287-330` | Reused verbatim; writer becomes terminal (`remote/mod.rs:261-274`). |
| Ambiguous local `CURRENT` | `index/writer.rs:684-710` | Reused verbatim; writer poisoned. |
| Verified bounded cache | `storage/cache.rs` | Unchanged. |
| Reclamation | `index/reclaim.rs:1-40`, dry-run only | Unchanged; a batch adds no new deletable object class. |

**No second publication path is required or proposed.** `PA-10` satisfied.

### 6.2 Resource-charge map for a proposed batch

| Batch step | Existing charger | Exact-at-limit behaviour | Evidence |
|---|---|---|---|
| Query selection scan (lexical) | `SearchWork` / `MixedWorkMeter::charge_lexical` | `checked_add`, `> limit` ⇒ `ResourceLimit`; counter not advanced | `search/execute.rs:214-247`; `search/work.rs:120-152` |
| Query selection scan (typed/geo) | `ScanGuard` via `MixedWorkMeter::charge_typed` | Same | `search/work.rs:154-196` |
| Posting occurrences scanned | `charge_scanned` = `1 + freq` | Separate `max_scanned_posting_occurrences` ceiling | `search/work.rs:198-232` |
| Candidate rows retained | `CandidateBudget` (`max_segment_candidate_entries`, `max_total_candidate_bytes`) | Preflight/commit split, overlap-conservative replacement | `search/execute.rs:281-460` |
| **Matched-key count (mutation target set)** | **none** | n/a | Gap **G6-1** |
| Decoded stored-source bytes | `DecodeBudget` + `SegmentLimits` | `LimitExceeded` | `segment/decode_budget.rs`; `segment/limits.rs` |
| **Patch bytes applied** | **none** (document bytes only, at admission) | n/a | Gap **G6-2** |
| Staged documents | `max_pending_docs` | `ResourceLimit` before push | `index/writer.rs:326-333` |
| Staged bytes | `max_pending_bytes` (saturating add, then `>`) | `ResourceLimit` before push | `index/writer.rs:334-345` |
| Document-level contract budgets | `Budgets` (`Fields`, `DocumentBytes`, `ArrayElements`, `JsonDepth`) | typed error | `contract/schema.rs:191-205`; `index/limits.rs:56-70` |
| Replay entries/bytes | `max_replay_entries`, `max_replay_bytes`, `max_mutation_state_bytes` | `ResourceLimit` | `index/writer.rs:522-540`, `748-770` |
| Segments per commit | `max_segments_per_commit` | `ResourceLimit` | `index/writer.rs:384-392`, `487-493` |
| Snapshot resident bytes | `max_snapshot_bytes` | `ResourceLimit` | `index/writer.rs:441-446`; `index/mod.rs:328-376` |
| Pinned PITs | `max_pinned_pits` | `PitLimitExceeded` | `index/pit.rs:52-58` |
| Remote transfers | `TransferLimits`, `RemoteTransferConfig` | typed error | `quervant-objectstore/src/transfer.rs`; `remote/config.rs:105-261` |

Two distinct meters exist and must **not** be conflated: the *query* meter
(`SearchWork`/`MixedWorkMeter`, CPU/work units) and the *writer admission* meter
(`IndexLimits`, bytes/entries). A batch touches both, in that order, before
admission.

### 6.3 Budget gaps

| ID | Gap | Required decision |
|---|---|---|
| G6-1 | No bound expresses "maximum matched keys accepted by a mutation selector" | Add to `IndexLimits` (operational, non-wire — recommended) rather than to the public `BudgetKind` enum, which is not `#[non_exhaustive]` (`contract/budget.rs:8-9`) |
| G6-2 | No bound expresses "patch bytes" before the merged document is validated | Charge the merged `Document::approx_size()` against `Budgets::DocumentBytes` + `max_pending_bytes`; state it explicitly rather than inventing a new metric |
| G6-3 | `delete_keys_for_retention` reuses `max_pending_docs` as a key-count bound (`index/writer.rs:992-997`) | Keep for compatibility; a batch should use the new `max_matches`/command-count bound instead |
| G6-4 | No frozen-at-mid-loop rollback for charges | Charges are held by RAII ledgers (`ReservedSet`, `ProjectionLedger`, `ReaderReservation`); a batch planner must drop its ledgers on every failure path |

### 6.4 Local vs remote / RustFS topology

| Aspect | Local | Remote |
|---|---|---|
| Authoritative commit selector | `index/CURRENT` via `Directory::atomic_write` | `CURRENT` object via conditional `put` (`IfMatch`/`IfAbsent`) |
| Recovery record | `CURRENT` only (`index/mod.rs:50-57`) | Remote `CURRENT` + local writer workspace |
| Poisoning | `poisoned = true` (`index/writer.rs:684-710`) | `TerminalState::{Conflict,Recovery}` (`remote/mod.rs:262-274`) |
| Retention helper | `delete_keys_for_retention` exists | **absent** on `RemoteIndexWriter` |

A batch API must be added to **both** writers (or the remote one must delegate),
otherwise remote mode cannot express the same mutation contract. This is an M1/M5
scope item.

### 6.5 Real-RustFS runtime evidence — NOT RUN / ENVIRONMENT BLOCKED

* `QUERVANT_RUSTFS_*` environment variables are **not set** in this environment.
* No `docker` on `PATH`; `podman` is present but no RustFS service/container is
  running, and starting one is outside a documentation-only M0.
* CI defines the authoritative topology (.github/workflows/ci.yml:58-99): a
  `rustfs/rustfs` service container pinned by digest, then `--ignored` test
  binaries (`pr13_s3_rustfs`, `pr13_proxy_rustfs`, `pr13_remote`, `pr13_oracle`,
  `pr13_oracle_geo`, `pr13_remote_proxy`, `pr13_crash_rustfs k0`, plus ten
  repetitions of `k05`).

Classification **PA-18 → DEFER-AND-CONTINUE**: static audit complete; M5
real-RustFS qualification remains mandatory and is **NOT** satisfied by this
packet.

### 6.6 M0-6 conclusion

Gate **G5 PASS at audit level** (every publication, cache and recovery path is
identified and no batch proposal needs a new one), with a permanent runtime
caveat: real-RustFS behaviour is unverified locally.
