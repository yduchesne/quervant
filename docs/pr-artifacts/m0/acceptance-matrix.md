# M0 — Acceptance matrix, test inventory and PR partitioning (M0-8)

**Status:** M0 audit artifact — *proposed* acceptance specifications, not tests.
**Baseline:** `main` @ `585a1eed033a9328c46872c505fe5aece9a735de`.
**M0 code impact:** none. This packet adds no test and changes no test.

This document is the deliverable of audit packet **M0-8** (`08_TEST_MATRIX`) and
the execution-plan §3/§6 traceability requirement. It contains:

1. what tests exist **and** whether they were actually executed for M0;
2. the invariant → future-test → owning-PR map;
3. the authoritative command and topology list;
4. the residual-risk register;
5. the failure-classification policy.

---

## 1. Execution evidence for M0 (this run)

M0 is documentation-only, so compilation/coverage/benchmark gates are **not**
M0 acceptance requirements (execution plan §8). A baseline run was still
performed to prove the audited source is not already broken.

| Command | Result | Notes |
|---|---|---|
| `cargo test --workspace --all-targets` | **PASS** — 1754 passed, 0 failed, 8 ignored across 101 test binaries | Default features; stable `rustc 1.98.1`; exit 0 |
| `cargo fmt --all -- --check` | **PASS** | exit 0 |
| `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** | exit 0 |
| `cargo test --workspace --all-targets --all-features` | **NOT RUN** | Not required for M0 |
| `cargo +1.85.0 test …` / `+1.85.0 clippy …` | **NOT RUN** | Not required for M0 |
| `cargo llvm-cov … --fail-under-lines 85` | **NOT RUN** | Documentation-only packet; M1–M5 must restore this gate |
| Real RustFS suites (`--ignored`) | **BLOCKED / NOT RUN** | No `QUERVANT_RUSTFS_*` env, no reachable RustFS service (see §4) |

**No failure to classify.** No baseline failure occurred, so the five-category
policy in §6 has no entries for this run. The 8 ignored tests are the
pre-existing real-service (`--ignored`) suites; they were not executed here and
must not be reported as passing.

---

## 2. Existing test inventory (mutation-relevant)

Counts are `#[test]` occurrences on `main`; names are the authoritative test
function identifiers.

### 2.1 PR 9 — stable-key mutation lifecycle (authoritative today)

| File | Tests | Coverage of the mutation contract |
|---|---:|---|
| `tests/pr09_mutations.rs` | 13 | `t01` insert/upsert/delete one winner; `t02` monotonic revisions, no reuse; `t03` absent-key tombstone then reinsert; `t04` same key across segments, one live pointer; `t05` duplicate live insert error; `t07` idempotent replay before/after commit; `t08` idempotency conflict; `t09` restart replay; `t10` refresh visibility vs commit durability; `t11` delete-only commit advances generation without a segment; `t14` old PIT sees previous version; `t15` old handle fixed / reopen sees latest; `t41` competing writer busy |
| `tests/pr09_visibility.rs` | 6 | `t16` term/phrase exclude deleted; `t17` multi-term operators and `Not` exclude dead docs; `t18` BM25 statistics after delete; `t19` negative-only has no ghost scores; `t27` corrupt state fails closed; `t37` v1 manifest readable and migrates |
| `tests/pr09_recovery.rs` | 4 | `t12` pre-`CURRENT` failure recoverable; `t13` failed refresh retains last view; `t34` resource bounds exact and +1; `t40` stale handle writer reloads `CURRENT` |
| `tests/pr09_reclamation.rs` | 5 | `t31` `CURRENT` objects never reclaimable; `t32` independent handles prevent deletion; `t33` orphan unknown; `t38` retention uses normal deletes; `t39` retention **preflight** validation |
| `tests/pr09_merge.rs` | 6 | `t20` indexed-not-stored phrase survives merge; `t21` columns and stored values survive merge; `t22` revisions/tombstones/replay survive merge; `t23` merge removes dead docs; `t24` merge scores equivalent; `t26` old PIT survives compact+close |
| `tests/pr09_properties.rs` | 1 | `t42` seeded stream matches an independent oracle |
| `src/index/amendment01.rs` (unit) | 25 | Revision overflow at `u64::MAX` (`a1_t01`–`a1_t04`); `CURRENT` write-then-fail poisoning on `MemoryDirectory` and real `FsDirectory` (`a1_t05`, `a1_t05b`, `a1_t06`, `a1_t07`); pre-publication failure retryable with one revision/token (`a1_t09`, `a1_t10`); cooperative compaction cancellation at every merge stage and post-final-check (`a1_t11`–`a1_t19`); lossless-merge oracle (`a1_t20`); compaction poison/retry (`a1_t15b`, `a1_t15c`); no wire-format change (`a1_t22`) |

### 2.2 PR 6 — lifecycle, refresh, PIT, fault injection

| File | Tests | Relevance |
|---|---:|---|
| `tests/pr06_lifecycle_unit.rs` | 18 | writer/flush/refresh/commit primitives |
| `tests/pr06_local_integration.rs` | 16 | real `MemoryDirectory`/`FsDirectory` lifecycle, restart |
| `tests/pr06_faults.rs` | 17 | deterministic fault injection around publication |
| `tests/pr06_amendment_01.rs` | 17 | lifecycle/recovery corrections |
| `tests/pr06_amendment_02.rs` | 15 | commit/reopen snapshot-budget parity |

### 2.3 Query execution, batches and projections

| File | Tests | Relevance to query-target mutation |
|---|---:|---|
| `tests/pr14_batch.rs` | 12 | ordered serial **query** batch, exactly-N outcomes |
| `tests/pr14_batch_governance.rs` | 7 | batch policy/capability admission |
| `tests/pr14_batch_memory.rs` | 31 | cumulative batch work/memory/response accounting |
| `tests/pr14_projection.rs` | 10 | five-state stored projection |
| `tests/pr14_unified_mixed.rs` | 14 | mixed lexical+typed `total_hits` and ordering |
| `tests/pr14_unified_cursor.rs` | 11 | cursor binding to snapshot identity |
| `tests/pr07_integration.rs` | 12 | lexical `total_hits`, top-K, BM25 |
| `tests/pr07_faults.rs` | 10 | lexical fault/budget paths |
| `tests/pr07_compatibility.rs` | 14 | segment/norms compatibility incl. legacy |

### 2.4 Codec, storage and remote

| File | Tests | Relevance |
|---|---:|---|
| `segment_codec.rs` | 24 | codec round-trip/corruption |
| `segment_golden.rs` | 3 | golden on-disk fixtures |
| `storage_conformance.rs` | 8 | `Directory` conformance |
| `storage_fs_integration.rs` | 8 | real filesystem |
| `storage_cache_integration.rs` | 16 | verified bounded cache |
| `cache_async_integration.rs` | 12 | async cache fill/eviction |
| `pr13_remote.rs` / `pr13_remote_proxy.rs` / `pr13_crash_rustfs.rs` / `pr13_oracle.rs` / `pr13_oracle_geo.rs` | 8 / 1 / 6 / 3 / 2 | **all `--ignored`**, real RustFS required |
| `quervant-objectstore/tests/pr13_s3_rustfs.rs`, `pr13_proxy_rustfs.rs` | `--ignored` | real RustFS `ObjectStore` |

### 2.5 Test inventory gaps that matter for M1–M5

| Gap | Why it blocks acceptance | Owning PR |
|---|---|---|
| No test injects a **mid-loop** failure into `delete_keys_for_retention` | `t39` proves only preflight atomicity; the loop at `index/writer.rs:1005-1007` is untested for partial admission | M1 |
| No test asserts zero revision/token consumption after a rejected batch | `INV-03` has no existing adversarial case | M1 |
| No test assembles a whole `Document` from a snapshot **by key** | `stored_doc`/`column_value` are exercised per physical doc (`pr09_merge.rs:100-110`, `pr11_json_mutations.rs:146`, `amendment01.rs:1132-1136`), and `index/merge.rs:300-327` merges STORED+COLUMNS inside compaction, but no key-addressed document API exists | M2 |
| No test asserts that an unstored-but-indexed field blocks a patch | the trap in `contract-proposals.md` D9 | M2 |
| No test enumerates *all* query matches | no exhaustive mode exists | M3 |
| No test asserts `max_matches` / limit+1 behaviour | bound does not exist | M3 |
| No batch-replay codec fixture, version, or mixed-version read test | replay encoding does not exist | M1/M5 |
| No test asserts a mutation replay survives reopen **with a query result set** | single-key replay only (`t09`) | M5 |
| No test asserts an old PIT is unchanged after a *batch* mutation | `t14`/`t26` cover single-key only | M3/M5 |

---

## 3. Invariant → future test → owner

Every invariant from execution-plan §3, with (a) positive case, (b) adversarial
counterexample, (c) producers/consumers, (d) future test ID, (e) what static
inspection cannot establish.

| ID | Invariant | Positive future test | Adversarial future test | Producers / consumers | Future test IDs | Owner | Not provable by inspection |
|---|---|---|---|---|---|---|---|
| **INV-01** | Single logical writer; immutable segments; `CURRENT` is durable authority | `M1-I01a`: batch admit → commit → reopen observes one generation | `M1-I01b`: second writer while lock held ⇒ `WriterBusy`; injected pre-`CURRENT` failure preserves old generation | `WriterLock`, `support::install_immutable`, `CurrentPointer` | `M1-I01a`, `M1-I01b`, `M5-I01c` | M1 | real fsync/crash ordering on real media |
| **INV-02** | `apply` volatile; `refresh`/`commit` have distinct visibility/durability | `M1-I02a`: after `apply_batch`, pre-refresh reader unchanged; post-refresh sees all | `M1-I02b`: failed `refresh` leaves prior view readable; restart before commit loses the batch | `journal`, `published`, `next_view`, `finish_commit` | `M1-I02a`, `M1-I02b`, `M5-I02c` | M1 | true power-loss durability |
| **INV-03** | Failed batch consumes no revision, token or admission | `M1-I03a`: valid batch admits exactly N revisions | `M1-I03b`: invalid **last** command / one-over-limit / cancellation / injected error ⇒ `journal`, `admitted`, `replay`, `pending`, `pending_bytes` all unchanged | `IndexWriter` fields (`writer.rs:179-187`) | `M1-I03a`…`M1-I03f` | M1 | nothing — must be measured, not inferred |
| **INV-04** | Query mutation selects **every** matching key, never a page | `M3-I04a`: 3 matches with `top_k=1` ⇒ 3 deletions | `M3-I04b`: exact `max_matches` passes; `+1` ⇒ typed error, zero deletions; `M3-I04c`: duplicate physical docs never cause double deletion; `M3-I04d`: corpus enumerated manually, not via the engine | planner, live masks, `CandidateBudget` | `M3-I04a`…`M3-I04d` | M3 | whether a bounded enumeration ever silently stops early |
| **INV-05** | Patch preserves every unspecified field without semantic loss | `M2-I05a`: patch one field of a document with all 10 `FieldType`s + all 5 `FieldValues` states | `M2-I05b`: document with `indexed=true,stored=false,columnar=false` field ⇒ patch rejected; `M2-I05c`: columnar-only field preserved through patch; `M2-I05d`: legacy v1 generation patch revision semantics | reconstruction seam, `STORED`+`COLUMNS` | `M2-I05a`…`M2-I05d` | M2 | byte-identical re-encoding of every historical generation |
| **INV-06** | Idempotent retry returns the original result; different request conflicts | `M1-I06a`: same token+request after commit returns identical response without re-query | `M1-I06b`: same token, different payload ⇒ conflict; `M5-I06c`: same token after reopen; `M5-I06d`: ledger at capacity ⇒ typed error | `ReplayRow`, `MutationStateV1` | `M1-I06a`, `M1-I06b`, `M5-I06c`, `M5-I06d` | M1 / M5 | durability across a real process restart with a query result set |
| **INV-07** | Limits apply; no silent truncation or unbounded buffering | `M1-I07a`: exact-limit batch succeeds | `M1-I07b`: limit+1 ⇒ typed error, zero admission; `M3-I07c`: cancellation during selection ⇒ no admission; `M5-I07d`: remote materialisation bounded | `IndexLimits`, `SearchWork`, `MixedWorkMeter`, `CandidateBudget` | `M1-I07a`, `M1-I07b`, `M3-I07c`, `M5-I07d` | M1 / M3 / M5 | peak RSS vs modelled bytes |
| **INV-08** | Historical readers/PITs unchanged after mutations | `M1-I08a`: old PIT sees pre-batch data; new reader sees post-batch | `M3-I08b`: PIT created before a query-delete still returns the deleted keys; `M5-I08c`: PIT surviving compact+close | `effective_live_docs`, masks | `M1-I08a`, `M3-I08b`, `M5-I08c` | M1 / M3 / M5 | cross-process PIT (there is none — PITs are process-local, `index/pit.rs:1-11`) |
| **INV-09** | Local and remote/RustFS share durability/recovery semantics | `M5-I09a`: same batch over `MemoryDirectory` and `FsDirectory` produces identical generations/results | `M5-I09b`: real RustFS cold-cache batch commit+reopen; `M5-I09c`: interrupted publication ⇒ `RecoveryRequired`/`RemoteConflict`, no partial generation | `Directory`, `ObjectStore`, `SegmentCache`, `publication::publish` | `M5-I09a`…`M5-I09c` | M5 | **everything real-service** — BLOCKED locally |
| **INV-10** | Existing single-key insert/upsert/delete/retention unchanged | `M1-I10a`: full regression of `pr09_*` after `apply_batch` lands | `M1-I10b`: `delete_keys_for_retention` behaviour byte-identical; `M1-I10c`: `MutationRequest`/`MutationResponse` unchanged | public contract, writer | `M1-I10a`…`M1-I10c` | M1 | nothing — these must be run |

**No invariant is marked runtime-verified by M0.** Static inspection established
the *paths*; only executed tests can establish behaviour.

---

## 4. Authoritative commands and topology

### 4.1 Local commands actually used by M0

```sh
cargo test --workspace --all-targets
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
```

### 4.2 Authoritative CI commands (from `.github/workflows/ci.yml`)

`rust` job — toolchain 1.98.1 (`.github/workflows/ci.yml:9-40`):

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --all-features --no-deps
cargo bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
git diff --check
```

`msrv` job — toolchain 1.85.0 (`.github/workflows/ci.yml:42-56`):

```sh
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
```

**Discrepancy recorded (not fixed here):** `AGENTS.md` documents
`cargo llvm-cov --workspace --all-targets --fail-under-lines 85`, while CI runs
the same with `--all-features`. CI is the superset. M1–M5 must report the
`--all-features` form.

### 4.3 Real RustFS topology

```sh
# service: rustfs/rustfs pinned by digest sha256:1803faef...
#   port 9000, health: curl -fsS http://localhost:9000/health
# env: QUERVANT_RUSTFS_ENDPOINT / _REGION / _BUCKET / _ACCESS_KEY / _SECRET_KEY

cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs     -- --ignored --test-threads=1
cargo test -p quervant-objectstore --features s3 --test pr13_proxy_rustfs -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_remote            -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_oracle            -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_oracle_geo        -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_remote_proxy      -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr13_crash_rustfs k0   -- --ignored --test-threads=1
# 10x repetition: pr13_crash_rustfs k05
```

Evidence source: `.github/workflows/ci.yml:58-99`.

**Local topology status: ENVIRONMENT BLOCKED.** `QUERVANT_RUSTFS_*` are unset;
no RustFS service is reachable; `docker` is absent and `podman` has no running
container. Starting one is outside a documentation-only packet (PA-18).

### 4.4 Required integration topology per PR

| PR | Minimum topology |
|---|---|
| M1 | `MemoryDirectory` unit + `FsDirectory` real-path integration + deterministic fault injection; no RustFS required |
| M2 | Real `SegmentBuilder` → `SegmentReader` round-trip over every `FieldType`/`FieldValues` combination; real `FsDirectory` restart; legacy v1 generation fixture |
| M3 | Real corpus with a **manually enumerated** expected key set (never a second call to the same engine); `MemoryDirectory` + `FsDirectory` |
| M4 | M3 topology plus query-upsert cardinality fixtures (0/1/2 matches) and fallback-key collision |
| M5 | Real RustFS cold bootstrap, interrupted publication, crash/reopen, and local↔remote equivalence; plus the full §4.2 command set |

---

## 5. Proposed adversarial boundary cases

Every row is a **future** test; none exists today.

| ID | Case | Expected | Owner |
|---|---|---|---|
| `B-01` | Empty batch (`commands: []`) | Rejected with a typed contract error (`InvalidBatchReason::Empty`); no admission | M1 |
| `B-02` | Single command | Admitted; one revision | M1 |
| `B-03` | Multiple distinct keys | All admitted or none | M1 |
| `B-04` | Duplicate keys within `MutationTarget::Keys` | Normalised by first occurrence, as `delete_keys_for_retention` does | M1 |
| `B-05` | Same key `Delete` → `Upsert` in one batch | Two revisions; final state live; deterministic ordering | M1 |
| `B-06` | Zero query hits | Successful no-op, `matched: 0`, no revision, no tombstone | M3 |
| `B-07` | Exactly one query hit | Deleted; PIT unchanged | M3 |
| `B-08` | Multiple query hits | All deleted; not just `top_k` | M3 |
| `B-09` | Exactly `max_matches` | Success | M3 |
| `B-10` | `max_matches + 1` | Typed error; zero deletions; no truncation | M3 |
| `B-11` | `max_matches` at `u64::MAX` / integer overflow in counts | Checked arithmetic ⇒ typed error | M3 |
| `B-12` | Patch `Set` with empty multi / explicit null | Exact five-state preservation | M2 |
| `B-13` | Patch on a document with an indexed-only field | `UnreconstructableDocument`; document unchanged | M2 |
| `B-14` | Patch on a legacy (v1 manifest) document | Defined revision semantics | M2 |
| `B-15` | Stale `expected_generation` | `StaleSelection`; zero mutation | M3 |
| `B-16` | Stale `ExpectedRevision` | `PreconditionFailed`; zero mutation | M1 |
| `B-17` | Replay after reopen (same token, same request) | Identical response, no re-query | M1/M5 |
| `B-18` | Replay with a different payload | `IdempotencyConflict`; no mutation | M1 |
| `B-19` | Replay-ledger at capacity | Typed resource error; no eviction | M5 |
| `B-20` | Interrupted query (cancellation mid-selection) | `IndexError::Cancelled`; no admission | M3 |
| `B-21` | Failed final staged command | Zero admission across the whole batch | M1 |
| `B-22` | Interrupted `commit` (injected pre-`CURRENT` failure) | Old generation authoritative; batch retryable | M5 |
| `B-23` | Cold RustFS cache batch reopen | Full logical state recovered | M5 |
| `B-24` | Ambiguous `CURRENT` publication | Preserve existing poison/terminal policy exactly | M5 |
| `B-25` | Duplicate token, different payload, concurrent | Conflict; no mutation | M1 |
| `B-26` | Crash after commit, reopen | Durable replay + consistent reader | M5 |
| `B-27` | `MustNotExist` against a tombstoned key | Per decision M0-D7 | M1 |
| `B-28` | `Replace(document)` over a multi-match selector | Rejected per decision M0-D6 | M4 |

---

## 6. Failure-classification policy

Any M1–M5 failure must be classified as exactly one of:

1. **Introduced regression** — the change caused it. Blocks completion.
2. **Feature defect** — the pre-existing feature is wrong and the new work
   exposed it. Record and open a scoped fix; do not silently absorb it into the
   mutation PR.
3. **Deterministic pre-existing** — reproducible on the baseline SHA with no
   mutation changes. Requires baseline reproduction at the same SHA.
4. **Flaky** — requires nondeterminism evidence (repetition counts, seeds,
   scheduling). A retry alone is **not** evidence.
5. **Environment/harness** — missing service, tool, or permission. Reported as
   **BLOCKED**, never PASS.

`docs/TESTING.md:227` mandates the same taxonomy ("introduced regression, feature
defect, verified pre-existing deterministic failure, evidenced
nondeterministic/flaky failure, or environment/harness failure"). Retries cannot
erase a failed required stability run, and no M0 finding may be re-labelled PASS
on the strength of CI alone.

---

## 7. Residual risk register

| ID | Residual risk | Why it is residual | Mitigation / owner |
|---|---|---|---|
| `RR-01` | Writer-visible query selection has no durable identity | `generation` is `None` for volatile views and `view_ordinal` restarts at 0 (`index/snapshot.rs:387-405`; `index/writer.rs:232`) | Decision M0-D1/M0-D2; default to committed selection; M1 |
| `RR-02` | Patching is impossible for schema-legal indexed-only fields | `FieldOptions::new(true,false,false)` is legal and its source value is discarded (`contract/schema.rs:20-40`; `segment/stored.rs:51`) | Decision required; reject such patches (PA-15); M2 |
| `RR-03` | `Projection::Source` silently omits unstored fields | `search/projection.rs:45-56` | Forbid projection as patch base (M0-D9); M2 |
| `RR-04` | Batch replay cannot be added compatibly without a version bump | version equality check + hard error on unknown section kinds (`index/mutation_state.rs:349-357`; `segment/format.rs:876-882`) | Decision M0-D11; M1/M5 |
| `RR-05` | A large query target set cannot be fully persisted within the 32 MiB mutation-state default | `index/limits.rs:32-52` | Decision M0-D10; bound + reject rather than truncate; M1 |
| `RR-06` | Remote writer has no retention helper and must gain `apply_batch` or remote mode cannot express the contract | `remote/mod.rs:357-482` | M1/M5 scope item |
| `RR-07` | Real RustFS behaviour is entirely unverified in this environment | no service, no env | `M5-I09b/c` remain mandatory; **BLOCKED**, not passed |
| `RR-08` | Public contract enums are not `#[non_exhaustive]`; additive variants break exhaustive downstream matches | `contract/document.rs:220`; `contract/error.rs:159`; `contract/budget.rs:9`; `contract/query.rs:503`; `contract/result.rs:179` | New types + `IndexError` (already `#[non_exhaustive]`, `index/error.rs:19`) where possible; document any break as a pre-1.0 contract note |
| `RR-09` | No `PitId` resolver exists, so any `pit`-based mutation selector is unimplementable today | `IndexError::PitNotFound` is never raised (`index/error.rs:107-110`) | Mutation selectors must not take a `PitId` in v0.1; M3 |
| `RR-10` | `delete_keys_for_retention` has no rollback if a mid-loop `apply` fails | `index/writer.rs:1005-1007` | Leave behaviour unchanged (PA-01); `apply_batch` must not reuse it |

---

## 8. M1–M5 scope reconciliation against verified `main`

Status vocabulary: **DONE + VERIFIED** / **DONE NOT VERIFIED** / **PARTIAL** /
**NOT STARTED** / **BLOCKED**.

| Phase | Roadmap claim | Reconciled against `main` @ `585a1ee` | Evidence |
|---|---|---|---|
| **M0** | "PLANNED — not started" | **PARTIAL** — audit performed; contracts proposed; **not frozen** | this directory |
| **M1** Atomic batches | PLANNED | **NOT STARTED** — no `apply_batch`; only single-key `apply` and the non-atomic retention loop | `capability-matrix.md` §1.3, §1.8 |
| **M2** Partial updates / reconstruction | PLANNED | **NOT STARTED** for patch; **PARTIAL** for raw material: `StoredRecord` + `ColumnReader::value` exist, but no key→document reconstruction and indexed-only fields are unrecoverable | `capability-matrix.md` §2 |
| **M3** Delete by query | PLANNED | **NOT STARTED**; **PARTIAL** reuse available: exact `total_hits`, full lexical `BTreeMap`, work meters, live masks | `capability-matrix.md` §3 |
| **M4** Query update/replace/upsert | PLANNED | **NOT STARTED** — depends on M2 + M3 | `capability-matrix.md` §3; `contract-proposals.md` D5/D6 |
| **M5** Qualification | PLANNED | **BLOCKED** — real RustFS unavailable locally | §4.3 |

No M1–M5 phase may be marked DONE on the strength of a design document.

---

## 9. Reviewer gate for this packet

* [x] Every invariant mapped to source, a future positive test, a future
      adversarial test, and an owning PR.
* [x] Commands copied from CI/`AGENTS.md`, not guessed.
* [x] Local vs. RustFS split stated explicitly; RustFS marked BLOCKED.
* [x] No test claimed as run when it was not.
* [x] No coverage number claimed for M0 (documentation-only).
* [x] Reference-oracle strategy stated: extend `contract/reference.rs`, and for
      query enumeration compare against a **manually enumerated** bounded corpus
      (never a second call to the paginated engine).
