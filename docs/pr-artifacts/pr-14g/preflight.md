# PR 14G — Phase A preflight (source, provider and counter boundaries)

**Status:** preflight complete. No production source changed by PR 14G.

Executed on `2026-10-28` (host clock) from the repository root
`/home/yduchesne/Dev/Github/yduchesne/quervant`.

## 1. Baseline and branch

| Item | Verified value |
|---|---|
| `origin/main` at execution | `054ca55d143e89a092cc6519231b820fecfa42dc` |
| Local `main` at execution | `054ca55d143e89a092cc6519231b820fecfa42dc` |
| Merged PR #67 head | `054ca55` (`Merge pull request #67 from yduchesne/bench/pr14f-p4-qualification`) |
| PR #67 executable SHA / evidence SHA | `d12a97537a5131953c948c3a90065a73c3d24b40` / `cc8153e593bc403d169da291a95a5ad18c6b0293` |
| Working tree before branching | clean (`git status --porcelain` empty); existing local branch `dev/pr14g-finalization` was at `054ca55` with **zero** commits ahead of `origin/main` and no remote counterpart |
| PR 14G branch created | `test/pr14g-final-acceptance`, from `origin/main` |
| PR #69 state | **unmerged.** `origin/docs/pr14-post-14f-reconciliation` = `75fc489 docs(pr14): reconcile 127 acceptance rows after merged PR14F`; `git merge-base --is-ancestor` of that tip against `origin/main` is false, i.e. `main` does not contain it |
| GitHub API | `gh auth status` reports the stored token is invalid (`HTTP 401: Bad credentials`), so authenticated writes (PR creation) are unavailable. The repository is public, so **read-only** endpoints work unauthenticated: `GET /pulls/69` returns `number 69, state open, merged false, head docs/pr14-post-14f-reconciliation @ 75fc4893dcbe9bfc188c4c13438cfbddcacf7a9b`, agreeing with the git-ref finding |

PR #69 is therefore cited as an **unmerged corroborating proposal**; the PR 14G
crosswalk is independently reconciled from verified 14E plus the merged PR 14F
evidence (X03).

## 2. Source anchors revalidated at `054ca55`

Small line drift from the plan's authoring snapshot with identical signatures is
preauthorized (X06). No anchor changed materially (no X07/X99 trigger).

### 2.1 Fake object store (GET-only, exact)

`crates/quervant-objectstore/src/fake.rs`

| Anchor | Line | Signature / behavior |
|---|---|---|
| `FakeObjectStore::get_calls` | 163 | `pub fn get_calls(&self) -> u64` — incremented at line 321 inside `ObjectStore::get`, **before** fault/`NotFound` handling, so every fake GET attempt is counted |
| `FakeObjectStore::put_calls` | 169 | `pub fn put_calls(&self) -> u64` |
| `FakeObjectStore::delete_calls` | 175 | `pub fn delete_calls(&self) -> u64` |
| `FakeObjectStore::reset_counters` | 180 | `pub fn reset_counters(&self)` — **not used inside any measured query** in PR 14G |

GET is the only operation that touches `get_calls`; `put`/`head`/`delete` have
separate counters, so `get_calls` is an exact GET-only oracle for the fake.

### 2.2 Remote open, snapshot and transfer counters

`crates/quervant-core/src/remote/mod.rs`

| Anchor | Line | Signature |
|---|---|---|
| `RemoteIndex::open_existing` | 147 | `pub async fn open_existing(store: Arc<S>, config: RemoteConfig, schema: Schema, registry: AnalyzerRegistry, limits: IndexLimits) -> IndexResult<Self>` |
| `RemoteIndex::snapshot` | 198 | `pub fn snapshot(&self) -> Arc<ReaderSnapshot>` |
| `RemoteIndex::pin` | 203 | `pub fn pin(&self) -> IndexResult<PitHandle>` |
| `RemoteIndex::generation` | 209 | `pub fn generation(&self) -> Option<u64>` |
| `RemoteIndex::transfer_stats` | 215 | `pub fn transfer_stats(&self) -> Arc<TransferStats>` |
| `hydrate` | 622 | hydrates committed state; the `CURRENT` probe at line 636 is a **direct** `store.get` (not budgeted) |
| `fetch_verified` | 584 | direct `store.get` for small metadata objects (manifest, mutation-state sidecar); **not budgeted** |
| `prepare_workspace` | 569 | deletes and recreates the disposable reader workspace on every open |

`crates/quervant-core/src/remote/transfer.rs`

| Anchor | Line | Signature / behavior |
|---|---|---|
| `TransferStats::requests` | 211 | `pub fn requests(&self) -> u64` — documented as *"Total HTTP GET requests issued (including retries)"* |
| `requests` increment | 513 | exactly one increment per `store.get(...)` attempt inside `get_with_retry` (line 500); retries re-enter the same path |
| `whole_requests` increment | 437 | once per whole-object `fetch_to_stage` |
| `range_requests` increment | 465 | once per ranged chunk `fetch_to_stage` |

**GET-only verdict (feeds A-03).** `TransferStats::requests` is incremented
**only** immediately before `ObjectStore::get` and is never touched by PUT, HEAD
or LIST, so it isolates GET. Its coverage is narrower than "all GETs": the
metadata GETs issued through `fetch_verified`/the `CURRENT` probe bypass the
transfer budget and are not counted. Consequence, recorded honestly:

- Fake (`get_calls`): proves **zero** GETs of any kind after warmup (strongest).
- Real (`requests`): proves **zero segment (re)materialization GETs** after
  warmup; metadata is never re-read at query time because `ReaderSnapshot`
  holds resident segment bytes.

No production instrumentation was added and no proxy/tracing tap was invented
(X15 does not trigger: a genuine GET-only counter exists).

### 2.3 Private selected-hit seam (Phase B precondition, recorded for completeness)

`crates/quervant-core/src/search/unified.rs`

| Anchor | Line | Signature |
|---|---|---|
| `SelectedHit` | 906 | private `struct SelectedHit { segment_index: usize, doc_id: u64, key: DocumentKey, score: Option<f64>, sort_tuple: Vec<SortValue> }` |
| `UnifiedSearcher::collect_mixed` | 503 | private method returning `(Vec<SelectedHit>, u64, Option<UnifiedCursor>, Option<AggregationResult>)` |
| `project_selected_hits` | 1280 | private `fn project_selected_hits(snapshot: &ReaderSnapshot, plan: &ProjectionPlan, ledger: &mut ProjectionLedger, hits: &[SelectedHit], memory: Option<&mut (dyn MemoryCharge + '_)>) -> SearchResult<Vec<Vec<(String, FieldValues)>>>`; opens `snapshot.open_segment_reader(hit.segment_index)`, checks `reader.doc_key(hit.doc_id)? == hit.key` (`SearchError::CorruptIndex` on mismatch) and projects `reader.stored_doc(hit.doc_id)?` |
| existing `#[cfg(test)] mod tests` | 1323 | sibling test module with private access to all of the above |

### 2.4 Reused PR 13/PR 14 fixtures (unchanged)

| Anchor | File:line |
|---|---|
| `remote_fake()` | `crates/quervant-core/tests/pr13_remote.rs:97` |
| `v01_lexical_results_match_local_oracle` (fake-store remote open + zero-GET baseline) | `crates/quervant-core/tests/pr13_remote.rs:163` |
| `r01_cold_open_from_remote_after_workspace_delete` | `crates/quervant-core/tests/pr13_remote.rs:209` |
| `fixture()` / `mixed_query()` / `aggregation()` / `policy()` / `batch_requests()` | `crates/quervant-core/tests/pr14_storage_vertical.rs:84/267/293/365/383` |
| `pinned_run` / `b06_b07_real_pinned_batch_search_after` | `crates/quervant-core/tests/pr14_storage_vertical.rs:1157/1184` |
| `r05_real_mutation_old_and_new_snapshot` | `crates/quervant-core/tests/pr14_storage_vertical.rs:1405` |
| `execute_batch` / `execute_batch_pinned` | `crates/quervant-core/src/search/batch.rs:42/75` |

The new Phase A file reuses `pr14_common` for the schema/registry/document
helpers and copies only the minimum fixture declarations (`fixture`,
`typed_query`, `mixed_query`, `aggregation`, `batch_policy`, `batch_requests`,
`pinned_run`) from `pr14_storage_vertical.rs`, with the source reference in the
file header and identical semantics. No search algorithm is duplicated.

## 3. Real provider preflight (X13)

| Item | Observed value |
|---|---|
| Container | `quervant-pr14f-rustfs`, `running` (rootless podman) |
| Image reference | `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Image ID | `f6b22807f10db2aee80b8a9ed1e36bd12c2fba25ac2d98dc3b0332a23f1a5c4d` |
| Version / health | `{"status":"ok","service":"rustfs-endpoint","version":"1.0.1"}` at `http://127.0.0.1:9000/health` |
| Endpoint | `http://127.0.0.1:9000` (loopback, disposable harness credentials; not recorded) |
| Filesystem | native ext4 under WSL2 (permitted by `docs/BENCHMARKING.md`) |

The pinned digest and version agree with the PR 14B/14D/14F committed evidence.
No image-tag substitution or mock provider was used (X16 does not trigger). The
real Phase A test therefore ran explicitly rather than being deferred (X14 does
not trigger).

## 4. Toolchains

| Item | Value |
|---|---|
| Stable | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV | `cargo +1.85.0` → `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| Coverage | `cargo-llvm-cov 0.9.1` |
| `rust-toolchain.toml` | `channel = "stable"`, components `rustfmt`, `clippy` |

## 4a. Addendum — PR #70 and CI binding (after Phase C evidence)

| Item | Observed state |
|---|---|
| PR 14G | maintainer opened **PR #70** `test(pr14g): zero-GET and physical hit identity final acceptance`, base `main` `054ca55`, head `test/pr14g-final-acceptance`, created `2026-10-28T01:42:29Z` |
| CI trigger | with PR #70 open, every branch push triggers the `pull_request` workflow (`rust`, `msrv`, `rustfs`); earlier pushes had zero check runs because only `push: main` and `pull_request` are configured |
| Maintainer decisions | PR #70 comment `6458408816` (`OWNER`, created `2026-10-28T01:43:43Z`, decision date `2026-10-27`): CW-041 = X-B, CW-127 = `ACCEPT RESIDUAL RISK FOR PR14 ONLY`; transcribed in `maintainer-decisions.md` §0 |

## 5. Scope fence confirmation

| Check | Result |
|---|---|
| Production `#[cfg(not(test))]` changes | none |
| `SelectedHit` visibility / `HitRef` API | unchanged |
| Persisted formats, codecs, manifests | unchanged |
| `Cargo.toml` / `Cargo.lock` | unchanged |
| `.github` workflows | unchanged |
| Historical 14C/14D/14E/14F artifacts | unchanged |
| Benchmarks / PR 14F source-lock corpus | unchanged |
