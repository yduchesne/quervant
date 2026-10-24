# PR 14D — P0 baseline inventory

**Status: P0 COMPLETE — no production change made.** This inventory records the
verified baseline, signatures/call sites, toolchains, fixture identities and the
pre-fix B20/B21 probe required by plan §2. It contains no acceptance claim. All
line numbers refer to the P0 baseline SHA and will shift once P1–P4 edits land.

## 1. Preflight record

| Step | Result |
|---|---|
| `git fetch origin --prune` | exit 0 |
| `git switch main; git pull --ff-only origin main` | up to date |
| `git status --short` | empty (clean) |
| `git rev-parse HEAD` | `2cb91be19652379b435c49a5fa4aea2ed7502de5` |
| `git merge-base --is-ancestor 376023b5… HEAD` | **YES** (PR 14B merge is an ancestor) |
| PR #62 merge | `2cb91be Merge pull request #62 from yduchesne/dev/pr14c-acceptance-closeout` — **ancestor of main** |
| Work branch | `dev/pr14d-json-sort-memory-governance`, created from `main` |
| Host | WSL2, `Linux 6.18.33.2-microsoft-standard-WSL2`, x86-64 |
| Repository filesystem | ext4 (`/dev/sdd` → `/`), not `/mnt/c` |

E01 satisfied: PR #62 is in main ancestry. No signer/branch conflict (E02).

## 2. Toolchains

| Tool | Version |
|---|---|
| `rustc` / `cargo` (stable) | 1.98.1 (`48a229cea 2026-09-01` / `797e8a9bc 2026-08-05`) |
| MSRV | `cargo +1.85.0` → 1.85.0 (`d73d2caf9 2024-12-31`) |
| Coverage | `cargo-llvm-cov 0.9.1` |
| Python (scripts) | 3.12.3 |
| Container runtime | `podman 4.9.3` (rootless) |

Real provider (for later phases): `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
(`rustfs:1.0.1`), health `1.0.1`, disposable `QUERVANT_RUSTFS_*` credentials.
Not started during P0.

## 3. Defect path — signatures and call sites (baseline)

### 3.1 Memory primitives (`search/memory.rs`, `search/batch_meter.rs`)

| Symbol | Location | Signature / behavior |
|---|---|---|
| `MemoryCharge` | `memory.rs:16` | `preflight`, `commit`, `preflight_release`, `release` over logical `u64` bytes; `BatchMeterError` maps to `QueryError::BudgetExceeded { kind }` |
| `SlotMemoryScope<'m>` | `memory.rs:27` | Owns `&'m mut BatchMemoryMeter`; tracks `temporary_bytes`; `reserve`/`release`; `finish_success(retained)`, `finish_failure`; non-panicking `Drop` fallback |
| `BatchExecutionMeter` | `batch_meter.rs:33` | `{ work: BatchWorkMeter, memory: BatchMemoryMeter, response: BatchResponseMeter }` |
| `BatchMemoryMeter` | `batch_meter.rs:100` | `preflight_reserve`, `commit_reserve`, `release_memory`, peak/current (test accessors) |
| `BudgetKind::BatchMemoryBytes` | `contract/budget.rs:25` | Exact typed failure kind for batch memory |
| `BatchMeterError::to_search_error` | `batch_meter.rs:27` | `SearchError::Query(QueryError::BudgetExceeded { kind })` |

### 3.2 JSON occurrence access (`search/typed.rs`, `segment/json_paths.rs`)

| Symbol | Location | Baseline behavior |
|---|---|---|
| `JsonAccess::occurrences` | `typed.rs:1218` | Builds `Vec<JsonOccurrence>`; charges **after** materializing, via `charge_occurrence_buffer` (`typed.rs:1178`), which uses `out.capacity() * size_of::<JsonOccurrence>()`; returns `(Vec<JsonOccurrence>, u64 bytes)` |
| Indexed path | `typed.rs:1225–1231` | `paths.doc_occurrences(field_id, doc_id)?` then `while let Some(o) = cursor.next_occurrence()? { guard.charge(1)?; out.push(o) }` |
| Legacy path | `typed.rs:1238–1254` | Requires stored field (else typed `UnsupportedOperator("json_path_legacy_unstored")`); `out = extract_field_paths(doc_id, &values, &self.limits)?` — **bulk allocation before any charge**; then charges `guard` per occurrence |
| `release_occurrence_buffer` | `typed.rs:1197` | `preflight_release` + `release` |
| Existing predicate callers | `typed.rs:1263,1287,1316,1341` | `match_exists`, `match_equals`, `match_range`, `match_array_contains` pass `Option<&mut dyn MemoryCharge>` and release after |
| `DocOccurrences::next_occurrence` | `json_paths.rs:1037` | Streams one occurrence at a time; allocates `path: Vec<JsonPathComponent>` and decodes `node` per item |
| `JsonPathsReader::doc_occurrences` | `json_paths.rs:996` | Returns a per-`(field, doc)` cursor from the directory run |
| `JsonOccurrence` | `json_paths.rs:71` | `{ doc_id: u64, path: Vec<JsonPathComponent>, node: JsonNode }` |
| `extract_field_paths` | `json_paths.rs:347` | Builds the full `Vec`, sorts by `(doc_id, concrete_path)`, rejects duplicate paths, enforces per-document occurrence limit — all before returning |

### 3.3 Sort path and call graph

| Symbol | Location | Baseline behavior |
|---|---|---|
| `json_sort_value` | `typed.rs:2465` | Calls `json.occurrences(field_id, doc_id, guard, None)`; materializes `values: Vec<FieldValue>`; clones `values[0]` and every replacement winner; returns `SortValue::{Value,Null,Missing}` |
| Typed caller | `typed.rs:2571` (`SearchAccumulator::accept`, `typed.rs:2555`) | No `MemoryCharge` parameter anywhere in the standalone typed path |
| Unified caller | `unified.rs:726` (inside `collect_mixed`, `unified.rs:503`) | Calls `typed::json_sort_value(&json, reader.schema(), field, doc_id, &mut guard)` — memory is `None` even when a batch meter exists |
| Batch scope creation | `unified.rs:601` | `let mut scope = memory.map(SlotMemoryScope::new);` where `memory` comes from `batch: Option<&mut BatchExecutionMeter>` (`unified.rs:508`) |
| Existing sink pattern in same loop | `unified.rs:618–665` | `scope.as_mut().map(|s| s as &mut dyn MemoryCharge)` already used for geo membership, geo sort distances and `evaluate_lexical_with`; the JSON sort call at line 726 does **not** use it |
| Batch entry | `search/batch.rs:150` | Batch uses `UnifiedSearcher`, not `TypedSearcher`; `BatchExecutionMeter` created at `batch.rs:149` |
| Typed standalone entry | `typed.rs:463` (`TypedSearcher::search`) | Uses query-local `max_heap_bytes` / heap accounting only; **no batch memory sink exists** |

### 3.4 Reusable precedent for reservation-before-growth

`GeoScratchBudget::reserve_exact_with_memory` (`typed.rs:1065`) already implements
the required pattern: checked `bytes_for::<T>(additional)` → `reserve_with_memory`
(preflight+commit) → `try_reserve_exact` → reconcile actual capacity upward or
release the difference → release on allocation failure. AD-05 can mirror this
logic in a JSON-specific scratch owner without inventing a new meter.

## 4. Standalone (non-batch) typed path distinction

- `TypedSearcher::search` has **no** batch memory sink and no `SlotMemoryScope`;
  it is governed by query-local limits (`max_topk_heap_bytes`,
  `max_total_candidate_bytes`) and `ScanGuard` work limits.
- Batch and pinned batch execute through `UnifiedSearcher` with
  `BatchExecutionMeter`.
- Therefore the P3 threading must accept `Option<&mut dyn MemoryCharge>` and pass
  `None` only on the standalone typed path (AD-04/E09). No batch path may pass
  `None`; `collect_mixed` must pass the existing `scope` whenever `batch` is
  present.
- No new public budget policy or meter is introduced.

## 5. Pre-fix B20/B21 baseline output

Command:

```sh
cargo test -p quervant-core --all-features --test pr14b_json_memory \
  -- --nocapture --test-threads=1
```

Result: `1 passed; 0 failed; 1 ignored` (child entrypoint), baseline `2cb91be`.

```text
B20/B21 occurrences=1 logical_BatchMemoryBytes=112 tracked_peak_exact=33675 tracked_peak_one_under=33104 tracked_peak_cancelled=7397
B20/B21 occurrences=128 logical_BatchMemoryBytes=112 tracked_peak_exact=110392 tracked_peak_one_under=41233 tracked_peak_cancelled=7397
B20/B21 occurrences=4096 logical_BatchMemoryBytes=112 tracked_peak_exact=2518968 tracked_peak_one_under=303121 tracked_peak_cancelled=7397
```

This is an allocator-window observation, **not RSS** and not a physical cap. It
is a defect baseline; the `112 B` logical value must not be hardcoded as a
post-fix pass criterion (plan rule 4 / E14).

Test inventory for the suite: `b20_b21_json_occurrence_memory_characterization`
(parent, executed) and `b20_child_json_memory_probe` (child, `#[ignore]`, spawned
by the parent — must not be run standalone, E08).

## 6. Dry-run feasibility observations (for P2, not decisions)

Recorded so P2 can apply E04/E05/E06 without re-deriving:

| Observation | Consequence |
|---|---|
| Indexed occurrence cursor (`doc_occurrences`/`next_occurrence`) already streams | E04 likely AUTO-RESOLVE: a sort visitor can consume one occurrence at a time and avoid the full `Vec` |
| Each decoded `JsonOccurrence` allocates an owned `path` vec and member strings, and possibly owned node data, during `decode_path`/`decode_node` | AD-07 requires charging owned path/member/node bytes; decoder-side preflight may need a narrow hook, otherwise E06 HARD STOP |
| Legacy path calls bulk `extract_field_paths`, which materializes, sorts and duplicate-checks the whole occurrence set | Batch sort must not use it unmetered (AD-06). An incremental visitor must preserve sorting/duplicate-rejection semantics or E05 HARD STOP |
| `JsonAccess::occurrences` charges with `out.capacity()` **after** growth | AD-05 requires preflight before capacity growth; post-hoc charging is explicitly insufficient |
| `json_sort_value` builds `Vec<FieldValue>` and clones winners | AD-08 requires single-pass winner selection with reservation before clone/replace |

No production code, format, API, cursor, dependency or CI change has been made in
P0.

## 7. Frozen fixtures relevant to compatibility (D13)

| Fixture | Size | SHA-256 |
|---|---:|---|
| `tests/fixtures/segment/json_paths_golden.seg` | 1186 | `0528a62cdb02fcd08754d5776f23bd16de787f788597ade93d5dfbc65c30a02f` |
| `tests/fixtures/segment/golden.seg` | 1688 | `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979` |
| `tests/fixtures/segment/golden_norms.seg` | 1810 | `49f813a68a4adedf8b69c8a965159a840bc993ca252f81efb1887daa95b5c39b` |
| `tests/fixtures/m1/mutation_state_v1.bin` | 307 | `753094d07734fbbebf5b535d585af83107d241c917e7e731462d2af972efc469` |
| `tests/fixtures/index/pr07_pre_norms_v1/index/CURRENT` | — | `56067c79491360ac0db145387aa15dc6156bac3217c5261507e34954bcebea88` |
| `…/manifests/g-0000000000000001.manifest` | — | `276d8025485f0e2ce9fe02a4f9eb7536a433cd28b2ae911a0b5a382b160f91d1` |
| `…/segments/050868…b4e.seg` | — | `0508682861380e974057c33f1f702713f0d38643ebd55eee12edeeedb3b94b4e` |
| `…/segments/da391e…558.seg` | — | `da391e76a490450b371d3ea963dd06e4a58d269974d52d1460b26c0083faf558` |

`json_paths_golden.seg` is the PR 11 v1 frozen JSON wire object used by B18/B19;
it must remain byte-identical (E26: no golden regeneration).

## 8. P0 exit checklist

| Item | State |
|---|---|
| Fresh main and PR #62 ancestry verified | DONE |
| Branch created | DONE |
| Memory/sort signatures and call sites captured | DONE |
| Standalone typed path sink question resolved | DONE — none; non-batch `None` only |
| Pre-fix B20/B21 probe executed and recorded | DONE |
| Fixture identities recorded | DONE |
| Production/format/API changes | NONE |

Next phase: **P1** — add the private sort scratch owner with reservation
lifecycle tests, without touching the defect path yet beyond additive helpers.
