# M0 — Source-level verification report (QMA-001)

**Title:** M0 mutation verification and final contract proposals
**PR type:** documentation / audit only
**Status:** **M0 IN PROGRESS — audit complete, contracts NOT frozen.**
Open decisions remain (see §6). M1 is **not** authorized.

**Companion documents**

| Document | Content | Packets |
|---|---|---|
| [`capability-matrix.md`](capability-matrix.md) | Capability inventory, reconstruction matrix, query-selection trace, atomicity map, replay/codec compatibility, storage & budgets | M0-1, M0-2, M0-3, M0-4, M0-5, M0-6 |
| [`contract-proposals.md`](contract-proposals.md) | Proposed Rust contract, decision table, decision register | M0-7 |
| [`acceptance-matrix.md`](acceptance-matrix.md) | Test inventory, invariant→test→owner map, topology, bounds cases, residual risks | M0-8 |

**Naming note (M0-9 reconciliation).** The execution plan names per-packet
deliverables (`00_BASELINE`, `01_CAPABILITY_MATRIX`, …, `08_TEST_MATRIX`) *and*
four canonical PR-artifact files. Repository practice is one directory per PR
under `docs/pr-artifacts/<pr>/`; the four canonical names are therefore used, and
each carries the packet ID as a section heading. No content was dropped.

---

## 1. Baseline frozen for this audit (M0-0)

| Item | Value |
|---|---|
| Reference `main` in the plan | `585a1eed033a9328c46872c505fe5aece9a735de` |
| `origin/main` observed at execution | `585a1eed033a9328c46872c505fe5aece9a735de` — **identical**, no drift |
| Local branch at audit start | `dev/mutation-contract`, **0 commits ahead / 0 behind** `origin/main`; working tree clean |
| Existing M0 branch / artifacts | none (`docs/pr-artifacts/m0/` did not exist) |
| `rustc` | `1.98.1 (48a229cea 2026-09-01)` (stable) |
| `cargo` | `1.98.1 (797e8a9bc 2026-08-05)`; MSRV toolchain `1.85.0 (d73d2caf9 2024-12-31)` available |
| `cargo-llvm-cov` | `0.9.1` installed |
| Workspace | `resolver = "3"`, `edition = "2024"`, `rust-version = "1.85"`; members `quervant-core`, `quervant-objectstore`, `quervant-distributed` |
| Feature flags | `quervant-core/s3 = ["quervant-objectstore/s3"]`; default build is local-only |
| CI | `.github/workflows/ci.yml` — three jobs: `rust` (1.98.1), `msrv` (1.85.0), `rustfs` (real service container pinned by digest) |
| RustFS harness locally | **unavailable**: `QUERVANT_RUSTFS_*` unset, no reachable service, no `docker`, `podman` idle |
| PR #44 / #45 docs on `main` | confirmed: `docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md`, and the M0–M5 table in `docs/ROADMAP_V01.md` |

### 1.1 Source of truth identified

`AGENTS.md` > `docs/ARCHITECTURE.md` > `docs/ROADMAP_V01.md` /
`docs/TESTING.md` > `docs/decisions/QMA-001_MUTATION_ARCHITECTURE.md` >
this audit. Where QMA-001's *provisional* types conflicted with verified code,
the code wins and the conflict is recorded (§6).

### 1.2 Stale claims observed (not rewritten)

| Claim | Location | Observation |
|---|---|---|
| `IndexError::UnsupportedMutation` says "only insert mutations are supported in this release" | `index/error.rs:186-188` | Stale: upsert and delete are implemented (`index/writer.rs:279-377`). Documentation-only defect; not fixed in M0 (no production edits). |
| `docs/ROADMAP_V01.md` header: "PRs 1–6 and 8–12 DONE … PR 13 DONE; PRs 14–15 PLANNED" | `docs/ROADMAP_V01.md:3` | The PR register below it marks PR 14 **IN PROGRESS**, and PR 7 **PLANNED**. Header/register disagreement, pre-existing. |
| `AGENTS.md` coverage command omits `--all-features`; CI includes it | `AGENTS.md` vs `.github/workflows/ci.yml:31-32` | CI is the superset; M1–M5 must report the `--all-features` form. |
| QMA-001 "Verified implementation baseline" says `insert` wrapper accepts one mutation etc. | `QMA-001:9-17` | **Verified accurate** on this SHA (see §4). |

No unrelated roadmap status was changed.

---

## 2. Executive summary

1. **QMA-001's baseline assertions all re-verified.** Every claimed existing
   capability (`MutationIntent`, `DocumentKey`, `FieldValues`, `IndexWriter::apply`,
   journal/admitted/replay state, `mutation_state.rs`, snapshots, `limits.rs`,
   `pr09_mutations.rs`) exists as described. Nothing claimed absent is present.
2. **`delete_keys_for_retention` is real multi-key deletion but is not an atomic
   batch.** It dedupes, bounds, and preflights revisions up front, then *loops
   over `apply`* with no rollback (`index/writer.rs:977-1039`). The existing test
   named "retention validation is atomic" proves only the preflight cases
   (`tests/pr09_reclamation.rs:143-174`). QMA-001 explicitly forbids this pattern
   for atomic batches.
3. **The atomic seam is precisely located.** `IndexWriter::apply` performs all
   validation, fingerprinting and preflight before its first mutation at
   `index/writer.rs:351`; the last safe pre-admission point is line 316. A batch
   can stage entirely off-state and swap once. Recommended shape (not approval):
   a delta overlay reusing the existing `candidate_rows` pattern.
4. **Exhaustive query-key selection is achievable without a new engine.** All
   three executors already compute an **exact** `total_hits`; the pure lexical
   executor already materialises the complete `BTreeMap<DocumentKey, f64>`
   (`search/execute.rs:1028-1062`), and `evaluate_lexical_with` yields every
   matched `(doc_id, score)`. Only a bounded *retention* mode plus a
   key→`doc_id` seam are missing.
5. **Duplicate-key dedup is an invariant, not an algorithm.** All executors treat
   a duplicate live logical key as `CorruptIndex`; uniqueness comes from the
   validated live mask (`index/visibility.rs:87-124`). A mutation planner must
   read liveness through `ReaderSnapshot::effective_live_docs` and must never use
   `ReaderSnapshot::contains_key` (which ignores liveness and returns `true` for
   a deleted key — `index/snapshot.rs:490-522`).
6. **Lossless patching is conditional.** Patch fidelity holds iff every schema
   field is `stored` or `columnar`. A schema-legal `indexed=true, stored=false,
   columnar=false` field has no recoverable source, and `Projection::Source`
   silently reports such fields as `Absent`. Patch must fail closed for those
   documents.
7. **Batch replay cannot be added without a payload version bump.** The mutation
   state payload compares `MUTATION_STATE_VERSION` for equality
   (`index/mutation_state.rs:349-357`) and the container rejects unknown section
   kinds outright (`segment/format.rs:876-882`). No cross-version policy exists.
8. **No new publication path, WAL, or storage contract is needed.** Every batch
   step maps onto existing `Directory`/`ObjectStore`/`commit`/`CURRENT`
   machinery, and every resource charge maps onto an existing meter except
   "matched keys" and "patch bytes".
9. **Two new public bindings are unavoidable but small:** a
   `contract::mutation` module (never `contract::batch`, which already means a
   batch of *queries*) and one `IndexError::MutationRejected` variant
   (`IndexError` is already `#[non_exhaustive]`).

---

## 3. The eight-gate report

`PASS` means **the audit question is answered with evidence**, not that the
future functionality exists. A documented implementation gap coexists with PASS.

### G1 — Reconstruction

| Field | Content |
|---|---|
| **Status** | **GAP** |
| **Source evidence** | `contract/schema.rs:186-212` (closed field universe); `segment/stored.rs:36-73` (only `stored` fields encoded); `segment/column.rs:122-283`, `638-731` (five-state column round-trip); `index/merge.rs:1-13` (compaction remaps decoded structures *because* indexed-only fields cannot be re-derived); `search/projection.rs:45-56` (Source omits unstored fields) |
| **Finding** | Byte-exact five-state reconstruction exists for `stored` and `columnar` fields, including legacy generations. It does **not** exist for `indexed=true, stored=false, columnar=false` fields, and no public key→document API exists. |
| **Gap** | (a) indexed-only fields are unrecoverable; (b) no key→`(segment, doc_id)` resolver outside `index`; (c) `Projection::Source` is a lossy patch base; (d) legacy revisions synthesise as `1`. |
| **Recommendation** | M2 reconstructs from `STORED` + `COLUMNS` only, fails closed with `UnreconstructableDocument`, and adds an internal pointer resolver that reuses `MutationStateV1::row` rather than a new index. |
| **Follow-up owner** | M2 |
| **Human approval** | **YES** — whether to reject such patches or tighten the schema/migrate |

### G2 — Query selection

| Field | Content |
|---|---|
| **Status** | **PASS (audit) / GAP (capability)** |
| **Source evidence** | `search/execute.rs:1028-1062` (full `BTreeMap`, exact count); `search/unified.rs:419-420, 519-524` (`top_k+1` heap, exact count); `search/typed.rs:493-498, 2544-2560`; `search/execute.rs:1048-1059` + `search/unified.rs:584-589` (duplicate key = `CorruptIndex`); `search/work.rs:24-232` (meters); `analysis/cancellation.rs` |
| **Finding** | Exact match counting already exists in all three executors. Complete *key materialisation* exists only privately in the lexical path. Pagination is a strict prefix and there is no PIT resolver, so pagination-based selection is unsafe. |
| **Gap** | No bounded exhaustive enumeration mode; no `max_matches`; no `PitId` resolver (`IndexError::PitNotFound` never raised). |
| **Recommendation** | M3 adds a retention mode over the existing per-document scan and candidate budget; `max_matches` on `IndexLimits`; never expose `PitId` on a mutation selector in v0.1. |
| **Follow-up owner** | M3 / M4 |
| **Human approval** | **YES** — D1/D2 snapshot identity |

### G3 — Writer atomicity

| Field | Content |
|---|---|
| **Status** | **PASS (audit)** |
| **Source evidence** | Full control-flow table in `capability-matrix.md` §4.1; first mutation at `index/writer.rs:351`; complete state inventory at `index/writer.rs:171-188`; poisoning at `684-721`; `finish_commit` at `636-682` |
| **Finding** | Every writer-owned mutable structure touched by a command is enumerated, and the last safe pre-admission point is unambiguous. Admission performs no I/O, so rollback is pure in-memory. |
| **Gap** | No staging structure; `apply` has no cancellation parameter; `delete_keys_for_retention` loops without rollback. |
| **Recommendation** | Delta-overlay staging + one swap (option A). No new WAL. Thread `&dyn Cancellation` into the planner only. |
| **Follow-up owner** | M1 |
| **Human approval** | **NO** for the staging approach (PA-03/PA-04/PA-09 apply) |

### G4 — Batch replay

| Field | Content |
|---|---|
| **Status** | **DECISION REQUIRED** |
| **Source evidence** | `capability-matrix.md` §5.1–§5.4; `index/mutation_state.rs:34, 249-331, 333-513`; `segment/format.rs:722-724, 876-882`; `index/limits.rs:32-52` |
| **Finding** | Replay is exact for single-key mutations and already versioned and bounded. `ReplayRow` cannot represent a batch, and the container forbids additive sections. A batch target set cannot fit the 32 MiB default budget. |
| **Gap** | Payload version bump needed; result-set retention bound needed; `IdempotencyKey` is unbounded. |
| **Recommendation** | Bump payload version **and** required-feature version, add a bounded batch replay record (count + digest + up to `max_batch_replay_keys`), bound `IdempotencyKey`. |
| **Follow-up owner** | M1 / M5 |
| **Human approval** | **YES** — cross-version policy (M0-D11) and result bound (M0-D10) |

### G5 — Storage and recovery

| Field | Content |
|---|---|
| **Status** | **PASS (audit) / BLOCKED (runtime)** |
| **Source evidence** | `capability-matrix.md` §6; `storage/directory.rs:38-100`; `quervant-objectstore/src/contract.rs:17-59`; `index/writer.rs:589-628`; `remote/publication.rs:240-330`; `index/reclaim.rs:1-40`; .github/workflows/ci.yml:58-99 |
| **Finding** | Both publication paths were traced end to end and neither needs a second path. Cache, reclamation and `CURRENT` recovery are unchanged by a batch. |
| **Gap** | Real RustFS execution unavailable locally; `RemoteIndexWriter` has no retention helper and must gain `apply_batch`. |
| **Recommendation** | M5 must run the `--ignored` RustFS suites on the pinned image; treat this as BLOCKED, never PASS. |
| **Follow-up owner** | M1 / M5 |
| **Human approval** | **NO** (PA-10 satisfied); runtime qualification remains mandatory |

### G6 — Tests

| Field | Content |
|---|---|
| **Status** | **PASS (audit) / GAP (coverage of new behaviour)** |
| **Source evidence** | `acceptance-matrix.md` §2–§7 |
| **Finding** | 1754 default-feature tests pass on the audited SHA with 0 failures (8 `--ignored` real-service tests not run). Mutation regression coverage is strong for single-key behaviour, including revision overflow, poisoning and cancellation. |
| **Gap** | No mid-loop failure test; no exhaustive-selection test; no reconstruction test; no batch replay fixture; no RustFS run. |
| **Recommendation** | Adopt the 28 proposed adversarial cases (`B-01`…`B-28`) and the `INV-*` test IDs, each owned by a phase. |
| **Follow-up owner** | M1–M5 |
| **Human approval** | **NO** |

### G7 — Visibility semantics

| Field | Content |
|---|---|
| **Status** | **DECISION REQUIRED** |
| **Source evidence** | `index/snapshot.rs:387-405`; `index/writer.rs:232, 434-437, 457-462`; `search/unified_cursor.rs` |
| **Finding** | A writer-visible snapshot is consistently *capturable* for one `apply_batch` call, but has **no durable identifier**: `generation` is `None` for volatile views and `view_ordinal` restarts at 0 per writer handle. PA-13 is conditional and its source-evidence test **fails** for caller-supplied identification. |
| **Gap** | No `SelectionToken`; no stale-selection error variant. |
| **Recommendation** | Committed-snapshot selection as the default; `expected_generation` as the only durable precondition; defer an opaque token. |
| **Follow-up owner** | M1 / M3 / M4 |
| **Human approval** | **YES** — M0-D1, M0-D2 |

### G8 — Capability reuse

| Field | Content |
|---|---|
| **Status** | **PASS (audit)** |
| **Source evidence** | `capability-matrix.md` §1 (repo-wide `rg`, results quoted) |
| **Finding** | No undocumented duplicate writer, planner, meter or storage abstraction is needed. Retention deletion, the query work meter (including `MixedWorkMeter` with an atomic pre-audit batch sink), the stored/columnar reconstruction primitives and the `contract/reference.rs` oracle pattern are all reusable. |
| **Gap** | `contract::batch` name collision; `BudgetKind`/`QueryError` are not `#[non_exhaustive]`. |
| **Recommendation** | New `contract::mutation` module; extend `IndexLimits` rather than `BudgetKind`; add one `IndexError` variant. |
| **Follow-up owner** | M1–M4 |
| **Human approval** | **NO** for placement (PA-02) |

### 3.1 Gate summary

| Gate | Status | Owner | Approval needed |
|---|---|---|---|
| G1 Reconstruction | GAP | M2 | YES |
| G2 Query selection | PASS (audit) | M3/M4 | YES |
| G3 Writer atomicity | PASS (audit) | M1 | NO |
| G4 Batch replay | DECISION REQUIRED | M1/M5 | YES |
| G5 Storage/recovery | PASS (audit) / BLOCKED (runtime) | M1/M5 | NO |
| G6 Tests | PASS (audit) | M1–M5 | NO |
| G7 Visibility | DECISION REQUIRED | M1/M3/M4 | YES |
| G8 Capability reuse | PASS (audit) | M1–M4 | NO |

**Six of eight gates are audited to a defensible conclusion; G4 and G7 cannot be
frozen without human decisions.** G5 carries a permanent runtime caveat.

---

## 4. Reuse findings (the four the plan asked for)

1. **Retention deletion.** `delete_keys_for_retention` (`index/writer.rs:977-1039`)
   is the closest existing relative of `apply_batch`. Reuse its **validation
   order** (dedupe → bound → revision preflight → admit) and its
   `RetentionOutcome { reason, deleted }` shape. Do **not** reuse its
   loop-over-`apply` execution: that is the exact anti-pattern QMA-001 forbids.
   Preserve it unchanged (PA-01).
2. **Query work meter.** Three reusable meters already exist and one is
   purpose-built for this shape: `MixedWorkMeter` charges a *single* authoritative
   total with atomic preflight→commit against an optional cumulative
   `BatchWorkMeter` sink (`search/work.rs:57-232`), with a separate typed ceiling
   and a separate scanned-postings ceiling. `BatchExecutionMeter` already
   demonstrates cumulative work + memory + response-byte budgets across a serial
   batch (`search/batch_meter.rs`, used at `search/batch.rs:48-105`). A mutation
   planner should charge `MixedWorkMeter` during selection and a
   response-byte ledger during response construction — not invent a meter.
3. **Existing stored-source support.** Reconstruction primitives exist and are
   five-state exact: `SegmentReader::stored_doc` (`segment/reader.rs:314-327`)
   and `ColumnReader::value` (`segment/column.rs:638-731`). Better still,
   `index/merge.rs:300-327` **already implements the STORED+COLUMNS merge**
   (stored values first, then columnar fields still absent, skipping `Absent`
   column values) into a `SegmentDocument`, and is validated by
   `a1_t20_lossless_merge_against_document_oracle`
   (`src/index/amendment01.rs:1098-1145`). M2 should extract that rather than
   write a second reconstruction. What does not exist is the *assembly entry
   point* (key → pointer → document) and the *coverage rule* (indexed-only
   fields). `Projection::Source` must not be used as the base.
4. **Exact hit counts.** `total_hits` is exact in all three executors and
   duplicate live keys are already a hard corruption error, so "never select only
   a page" is a *bounded-retention* problem, not a *correctness* problem.

---

## 5. Evidence ledger

| # | Claim | Evidence |
|---|---|---|
| E1 | Baseline untampered | `git rev-parse HEAD` = `585a1ee…`; `origin/main` identical; `git status --short` empty |
| E2 | No prior M0 work to reconcile | `find . -iname '*m0*'` → nothing outside `target/`; `docs/pr-artifacts/` had no `m0/` |
| E3 | Baseline suite green | `cargo test --workspace --all-targets` → 1754 passed / 0 failed / 8 ignored, 101 binaries, exit 0 |
| E4 | Formatting and lints clean | `cargo fmt --check` exit 0; `cargo clippy … -D warnings` exit 0 |
| E5 | All QMA-001 baseline symbols exist | `capability-matrix.md` §1.1–§1.6 |
| E6 | All QMA-001 proposed symbols are absent | `capability-matrix.md` §1.8 (repo-wide `rg -g '!target'`, only QMA-001 prose matched) |
| E7 | Retention deletion is non-atomic | `index/writer.rs:1005-1007`; `tests/pr09_reclamation.rs:143-174` |
| E8 | Atomic seam location | `index/writer.rs:279-377` (first mutation at 351; last safe point at 316) |
| E9 | Exact `total_hits`, three executors | `search/execute.rs:1062`; `search/unified.rs:519`; `search/typed.rs:523` |
| E10 | Lexical exhaustive map | `search/execute.rs:1028-1062` |
| E11 | Duplicate key = corruption, not dedupe | `search/execute.rs:1048-1059`; `search/unified.rs:584-589` |
| E12 | Liveness comes from the live mask | `index/visibility.rs:87-124`; `index/snapshot.rs:464-484` |
| E13 | `contains_key` ignores liveness | `index/snapshot.rs:490-522` |
| E14 | `STORED` carries only `stored` fields | `segment/stored.rs:36-73` |
| E15 | `COLUMNS` carries five-state values | `segment/column.rs:122-283, 638-731` |
| E16 | Indexed-only fields are legal and unrecoverable | `contract/schema.rs:20-40`; `index/merge.rs:1-13` |
| E17 | `Projection::Source` silently omits unstored fields | `search/projection.rs:45-56` |
| E18 | Replay version is equality-checked | `index/mutation_state.rs:349-357` |
| E19 | Unknown section kinds are hard errors | `segment/format.rs:876-882` |
| E20 | Unknown required features fail closed | `segment/format.rs:722-724` |
| E21 | Replay budgets and ceilings | `index/limits.rs:32-52, 147-196`; `index/writer.rs:522-540`; `index/mod.rs:399-414` |
| E22 | Volatile view has no durable identity | `index/snapshot.rs:387-405`; `index/writer.rs:232` |
| E23 | No PIT resolver | `index/error.rs:107-110`; repo-wide `rg PitNotFound` outside tests |
| E24 | Local and remote publication paths, unchanged | `index/writer.rs:589-628`; `remote/publication.rs:240-330` |
| E25 | RustFS topology is CI-only and unset locally | .github/workflows/ci.yml:58-99; `env | grep QUERVANT_RUSTFS` → empty |
| E26 | `delete_keys_for_retention` absent on the remote writer | `remote/mod.rs:357-482` |
| E27 | `contract::batch` already means a *query* batch | `contract/batch.rs:20-260`; `contract/mod.rs:22-25` |
| E28 | Public contract enums are not `#[non_exhaustive]` | `contract/document.rs:220`; `contract/error.rs:159`; `contract/budget.rs:9`; `contract/query.rs:503`; `contract/result.rs:179`; `index/error.rs:19` (is) |
| E29 | A STORED+COLUMNS reconstruction already exists inside compaction | `index/merge.rs:300-327`; tested by `src/index/amendment01.rs:1098-1145` |

---

## 6. Decision register and STOPs

Full register with options and trade-offs: [`contract-proposals.md`](contract-proposals.md) §4.

| ID | Question | PA-ID | Recommendation (not approval) | Human approval |
|---|---|---|---|---|
| **M0-D1** | Default selection snapshot: committed or writer-visible? | PA-13 (conditional — **not** satisfied) | Committed default; writer-visible opt-in | **YES** |
| **M0-D2** | Does volatile selection need an identity beyond `expected_generation`? | PA-14 | No for v0.1; defer a public `SelectionToken` | **YES** |
| **M0-D3** | Expose an `atomic` flag? | PA-03 | **Omit** the field entirely | NO — preauthorized |
| **M0-D4** | Repeated keys / ordering | PA-04 | Preserve order, no coalescing, one revision per command | NO — preauthorized |
| **M0-D5** | Query-upsert cardinality | PA-06 | ≤1 match; explicit fallback key on zero; reject collisions | NO — preauthorized |
| **M0-D6** | Multi-match `Replace`/`Upsert(document)` | PA-08 | **Reject**; patch may fan out | NO — preauthorized (restriction) |
| **M0-D7** | `MustNotExist` vs a tombstoned key | PA-20 | "not live" (absent **or** tombstoned), matching current insert | **YES** |
| **M0-D8** | `Set { values: Absent }` vs `Unset` | PA-20 | **Reject** `Set(Absent)`; require `Unset` | **YES** |
| **M0-D9** | May the patch base be `Projection::Source`? | PA-15 | **No** — internal STORED+COLUMNS, fail closed | NO — preauthorized |
| **M0-D10** | Bounds for response and persisted replay record | PA-17 | Bound by `max_batch_replay_keys`; reject, never truncate | **YES** |
| **M0-D11** | Batch replay on-disk encoding | PA-17 | Payload **and** required-feature version bump | **YES** |
| **M0-D12** | Placement and error classification | PA-02 | New `contract::mutation` + one `IndexError` variant | NO — preauthorized (placement) |

### 6.1 STOP reports

```text
STOP — M0-5 / G4 Batch replay
Observed behavior and exact source evidence:
  `MutationStateV1::decode` compares MUTATION_STATE_VERSION for equality
  (index/mutation_state.rs:349-357); `parse_container` rejects any unknown
  section kind as `Corrupt` (segment/format.rs:876-882); unknown *required*
  features fail closed (segment/format.rs:722-724). `ReplayRow` holds exactly one
  key/intent/revision (index/mutation_state.rs:113-124). Replay budgets are
  100 000 entries / 16 MiB / 32 MiB state (index/limits.rs:32-52).
Approved invariant at risk:
  INV-06 (durable, bounded, idempotent replay) and INV-09 (a committed
  generation must remain readable across generations).
Why the plan cannot safely proceed:
  A batch replay record cannot be added without changing the mutation-state
  payload version, and there is no cross-version compatibility policy in the
  repository (AGENTS.md requires an explicit policy before asserting
  compatibility). Choosing an encoding is an architectural decision, not an
  audit finding.
Smallest decision needed (options + recommendation):
  (A) payload version 2 only — old readers fail with `Corrupt`;
  (B) payload version 2 + required-feature version bump — old readers fail with a
      typed "unsupported feature";
  (C) separate content-addressed sidecar + manifest v3 — largest blast radius;
  (D) no persisted batch results — violates PA-11 "no re-evaluation".
  Recommendation: (B), with `max_batch_replay_keys` bounding the result set.
What audit work remains safely possible:
  Completed: gates G1, G2, G3, G6, G8; storage and budget maps (G5); the full
  write-path, query-path and codec inventories. Only contract *freezing* waits.
No production code modified.
```

```text
STOP — M0-7 / G7 Visibility semantics
Observed behavior and exact source evidence:
  `ReaderSnapshot::generation()` is `Option<u64>` and is `None` for a volatile
  refresh view (index/snapshot.rs:387-390; writer passes the committed
  generation at index/writer.rs:434-437). `view_ordinal` is process-local and
  restarts at 0 for every `IndexWriter::open` (index/writer.rs:232;
  index/snapshot.rs:393-395). `binding_id` is process-wide unique but never
  persisted (index/snapshot.rs:41-57, 403-405).
Approved invariant at risk:
  INV-04 (select every matching key exactly once) and INV-08 (historical views
  never change).
Why the plan cannot safely proceed:
  PA-13 is conditional: writer-visible selection is only acceptable if it can be
  captured consistently *and* identified. Capture is proven; identification is
  not — `expected_generation` alone cannot distinguish two volatile views of the
  same generation, and `view_ordinal` is not comparable across writer handles.
  The plan forbids silently switching the contract.
Smallest decision needed (options + recommendation):
  (A) committed-snapshot selection as the default, `expected_generation` as the
      only durable precondition;
  (B) additionally mint an opaque, process-local, non-durable `SelectionToken`
      and reject a token from another handle with a typed error.
  Recommendation: (A) for v0.1; revisit (B) only with a demonstrated need.
What audit work remains safely possible:
  Everything except freezing the selector contract: query-plan, mask, meter and
  pagination analysis is complete (capability-matrix.md §3).
No production code modified.
```

---

## 7. Residual risks

See [`acceptance-matrix.md`](acceptance-matrix.md) §7 for the full `RR-01`…`RR-10`
register. The three that most affect a naive implementation:

| ID | Risk | Guard |
|---|---|---|
| `RR-01` | Writer-visible selection has no durable identity | Commit to committed-snapshot selection (M0-D1) |
| `RR-03` | `Projection::Source` silently drops unstored fields | Forbid it as a patch base (M0-D9) |
| `RR-04` | Batch replay needs a version bump | Decide before any codec edit (M0-D11) |

Additional residual risk that is **not** a defect: real RustFS behaviour is
`NOT RUN / ENVIRONMENT BLOCKED`. M0's static audit is complete; M5's
real-RustFS qualification remains mandatory and is not satisfied here.

---

## 8. Commands actually executed

| Command | Environment | Exit | Result |
|---|---|---:|---|
| `git fetch origin main` | local | 0 | `origin/main` = `585a1ee…`, no drift |
| `git rev-parse HEAD` / `git status --short` | local | 0 | `585a1ee…`; clean tree |
| `git rev-list --left-right --count origin/main...HEAD` | local | 0 | `0 0` |
| `find crates -maxdepth 3 -type f` | local | 0 | inventory recorded |
| `rg -n '<symbol>' . -g '!target'` (12 symbols, twice) | local | 0 / 1 | absence proven; only QMA-001 prose matched |
| `cargo test --workspace --all-targets` | stable 1.98.1 | 0 | **1754 passed, 0 failed, 8 ignored, 101 binaries** |
| `cargo fmt --all -- --check` | stable 1.98.1 | 0 | clean |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable 1.98.1 | 0 | clean |
| `env \| grep -iE 'QUERVANT_RUSTFS\|AWS_\|S3_'` | local | 1 | empty — RustFS unavailable |
| `which docker podman` | local | 0 | `podman` present, idle; no `docker` |

**Not executed, and not claimed:** `--all-features` builds/tests, MSRV
(`+1.85.0`) fmt/clippy/test, `cargo llvm-cov`, `cargo doc`, `cargo bench
--no-run`, benchmark scripts, and every `--ignored` real-RustFS suite. M0 is
documentation-only and §8 of the execution plan does not require them; M1–M5
must run the full `ci.yml` set.

---

## 9. Reviewer checklist

* [x] Latest `main` SHA, workspace, policies and test harnesses recorded (§1).
* [x] Every QMA-001 baseline assertion reverified; nothing assumed absent (§4, E5).
* [x] All eight audit gates have evidence and a defensible status (§3).
* [x] All ten invariants mapped to source, future positive/negative tests and owners (`acceptance-matrix.md` §3).
* [x] Full-document reconstruction risks and version compatibility documented (`capability-matrix.md` §2, §5).
* [x] Query result completeness and snapshot identity risks documented (§3 G2/G7; `capability-matrix.md` §3).
* [x] All writer mutation state and atomic staging boundaries identified (`capability-matrix.md` §4).
* [x] Durable replay format and idempotency semantics documented, migration decisions flagged (M0-D10/M0-D11).
* [x] Local/remote/RustFS recovery and resource governance inventoried (`capability-matrix.md` §6).
* [x] Query upsert and multi-match replacement resolved or marked DECISION REQUIRED (M0-D5, M0-D6, M0-D7).
* [x] M1–M5 scopes reconciled with the implementation; no duplicate architecture proposed (`acceptance-matrix.md` §8).
* [x] All unproven runtime properties recorded as residual risks; no false PASS.
* [x] Documentation-only diff; no production code, CI, dependency or codec change.
* [ ] Documentation PR opened — **pending** (see §10).
* [ ] M0 marked DONE — **NOT done**; remains IN PROGRESS until M0-D1/D2/D7/D8/D10/D11 are accepted.

---

## 10. Status and next action

**M0 is IN PROGRESS.** This document is a completed *audit packet with proposed
contracts*, not a frozen contract set.

Six decisions require human approval before contracts can freeze:

1. `M0-D1` / `M0-D2` — query-selection snapshot and its identity.
2. `M0-D7` — `MustNotExist` semantics against a tombstone.
3. `M0-D8` — `Set(Absent)` vs `Unset`.
4. `M0-D10` — response and replay-record bounds.
5. `M0-D11` — batch-replay on-disk encoding and cross-version policy.

**M1 is not authorized.** No production code was changed and no
`MutationStateV1`/manifest/segment byte was altered by this audit.
