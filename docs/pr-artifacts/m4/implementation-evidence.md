# M4 — Query-targeted update, replace and restricted upsert: implementation evidence

**Status: IMPLEMENTED — LOCALLY QUALIFIED (stable 1.98.1 + MSRV 1.85.0, coverage
91.15% lines) — real RustFS PASS 3/3 — NOT PUSHED/CI PENDING at the time this
section was written (see §12). Not DONE; not ready to merge without explicit
human authorization.**

## 0. M4-AD16 — approved codec cardinality amendment (recorded before code edits)

**Decision authority:** `QUERVANT_M4_AD16_AGENT_INSTRUCTIONS.md` (human
architectural authorization), supplementing the M4 plan §§2.1, 3.3, EX-02 and
EX-18.

- The P0 stop recorded in §3.2 of this document is **resolved by explicit human
authorization of Option A**; it was a true positive against the frozen plan, not
a false alarm.
- **Approved semantics:** the durable `MutationCommandOutcome.matched` counts
  query-selected documents; `keys.len()` counts per-key mutation outcomes. They
  normally agree. The single permitted exception is the zero-match query-upsert
  fallback:
  `matched = 0`, `keys.len() = 1`, `keys[0].intent = Insert`,
  `keys[0].key = fallback.key()`, `keys[0].revision` = allocated fallback revision.
- **Accepted validator shapes (exactly):**
  `matched == keys.len() as u64` **or**
  (`matched == 0 && keys.len() == 1 && keys[0].intent == MutationIntent::Insert`).
- **Boundary:** the codec cannot prove an exceptional record came from
  `QueryUpsert` (the durable response stores no action or query). The M4 planner
  is the sole producer of this shape and must enforce query cardinality,
  fallback eligibility, stable-key identity, revision, staged overlap,
  preconditions, caps and atomicity. No action tag, version, feature bit or
  layout change; no other validation is weakened.
- **Scope:** this approval covers only AD16 (and the original M4 plan). Any
  further architectural contradiction follows the original STOP matrix.
- Resolution of the P0 alternatives: **Option A** (§3.3) — a shared private
  cardinality predicate used by the v2 encoder and the v2 decoder, with the
  decoder's cardinality check moved to *after* the command's key outcomes are
  decoded (intent is not known earlier).
- P0 evidence below is preserved unchanged; the baseline was not re-run because
  the base is unchanged (`origin/main` = `4e64acb` = branch start).

**Starting state for this amendment:** branch `dev/m4-query-mutations`,
`HEAD = 1c59e2c7c6b09077f7c2b8aad2e2ba5899a27d75` (P0 evidence commit),
base `4e64acb`, clean worktree, `origin/main` unchanged at `4e64acb`.

## P0 evidence (recorded at `4e64acb`; unchanged)

**P0 status was: BLOCKED at the pre-implementation contradiction gate (§2.1 /
EX-02 / EX-18). No production code changed at P0. Resolved by M4-AD16 (§0).**

- Plan: `QUERVANT_M4_DETAILED_IMPLEMENTATION_PLAN.md`
- Branch: `dev/m4-query-mutations`, created from `origin/main`
  `4e64acb0e7baa3d0cdb6261d1b7379143a3cfa63`
  (`Merge pull request #53 from yduchesne/dev/m3-delete-by-query`)
- Base/M3 acceptance: `git merge-base --is-ancestor 0af67599 HEAD` exits 0
  (verified); see §1.1
- Worktree at gate: clean before and after the gate (`git status --short`
  empty; only this evidence file is added)
- Host: Linux x86-64; stable `rustc 1.98.1`; MSRV `rustc 1.85.0` (workspace
  `rust-version = "1.85"`, `.github/workflows/ci.yml` matrix unchanged)

## 1. P0 baseline

### 1.1 Base identification

| Item | Value |
|---|---|
| `origin/main` | `4e64acb0e7baa3d0cdb6261d1b7379143a3cfa63` |
| PR #53 merge | `4e64acb0e7baa3d0cdb6261d1b7379143a3cfa63` (same commit) |
| M3 head referenced by the plan | `0af6759938f24e6c876f5f5aea200b3b1b42bfcf` (ancestor; `git merge-base --is-ancestor 0af67599 HEAD` exits 0) |
| M4 branch start | `4e64acb` |
| CI workflow | `.github/workflows/ci.yml` → `Rust CI` (`rust-stable`, `rust-msrv`, `rustfs`) |

The plan's prerequisite is satisfied: M3 is merged into `main` with the exact
head the plan was authored against (`0af6759`). `git log --oneline
0af6759..origin/main` contains only the merge commit `4e64acb` itself, so no
post-M3 semantic change exists in the inspected mutation paths.

### 1.2 Focused baseline suites

Command:

```sh
cargo test -p quervant-core --all-features --test m1_batches \
  --test m2_patches --test m3_delete_by_query
```

| Suite | Result |
|---|---|
| `m1_batches` | 14 passed, 0 failed, 1 ignored (real RustFS) |
| `m2_patches` | 10 passed, 0 failed, 1 ignored (real RustFS) |
| `m3_delete_by_query` | 29 passed, 0 failed, 1 ignored (real RustFS) |

Ignored tests are the real-RustFS acceptance tests; per `docs/TESTING.md` and
`AGENTS.md`, an ignored test is **not** executed RustFS acceptance.

### 1.3 Workspace baseline gate (all PASS)

Command set (repo-prescribed, `.github/workflows/ci.yml` + `AGENTS.md`), run on
`4e64acb` before any M4 edit:

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (stable 1.98.1) | PASS (rc=0) |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS (rc=0) |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS (rc=0) |
| `cargo test --workspace --all-targets` | PASS — 1903 passed, 0 failed, 9 ignored (104 suites) |
| `cargo test --workspace --all-targets --all-features` | PASS — 1907 passed, 0 failed, 65 ignored (104 suites) |
| `cargo doc --workspace --all-features --no-deps` | PASS (rc=0) |
| `cargo bench --workspace --no-run` | PASS (rc=0) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (rc=0) |
| `git diff --check` | PASS (rc=0) |
| `cargo +1.85.0 fmt --all -- --check` (MSRV) | PASS (rc=0) |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` (MSRV) | PASS (rc=0) |
| `cargo +1.85.0 test --workspace --all-targets --all-features` (MSRV) | PASS — 1907 passed, 0 failed, 65 ignored (104 suites) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.04% lines** (46441 lines, 4159 missed); regions 91.66%; functions 86.96% |

No baseline failure was observed, so EX-16 needs no pre-existing-failure
classification. Ignored tests are the real-service (RustFS/S3) suites; they are
not executed acceptance and are not claimed as such.

## 2. P0 source map (verified at `4e64acb`)

| Path | Verified contract | M4 relevance |
|---|---|---|
| `crates/quervant-core/src/contract/mutation.rs` | `MutationTarget::{Key,Keys,Query}`, `MutationAction::{Insert,Upsert,Replace,Update,Delete}`, `QueryMutationSelector{query,max_matches,expected_generation}`, `DocumentPatch`, `MutationPrecondition`, `MutationBatch`, `MutationRejection::{UnsupportedTargetAction,MatchLimitExceeded,AmbiguousQueryUpsert,StaleSelection,ReconstructionUnavailable,…}`; `MutationCommandOutcome{command_index,matched,keys}`; `MutationBatchResponse::encoded_len` | AD-03/AD-04/AD-05/AD-09/AD-12 |
| `crates/quervant-core/src/index/writer.rs` | `apply_batch` → `plan_batch` Phases A/A2/B/C → `install_batch`; `BatchDelta`; `delete_by_query`; `prospective_state_for`; `resolve_live_document`; `stage_pending`; `candidate_state_for`; `check_precondition`; `action_intent`; `action_document`; `batch_raw_key_preflight`; `resolve_batch_target` | AD-01/AD-02/AD-06/AD-07/AD-08 |
| `crates/quervant-core/src/index/query_selection.rs` | `select_query_keys(…, effective_limit, cancel) -> SelectionOutcome::{Complete(Vec<SelectedKey>), LimitExceeded{limit,matched}}` | AD-01/AD-05/AD-06 |
| `crates/quervant-core/src/search/unified.rs` | `UnifiedSearcher::select_keys(query, limit, budgets, cancel)`; membership-only visitor returns `LimitExceeded{limit, matched: limit+1}` on the first distinct over-limit key | AD-05/AD-06/AD-14 |
| `crates/quervant-core/src/index/mutation_state.rs` | `MutationStateV1`, `BatchReplayRow{token,fingerprint,response}`, `batch_fingerprint`, `encode_fingerprint_action` (tags 0..4), `MUTATION_STATE_VERSION=1`, `MUTATION_STATE_VERSION_BATCH=2`, `FEATURE_MUTATION_STATE_V2`, `encode_batch_response`/`decode` batch-response codec | **Gate §2.1**; AD-09/AD-10/AD-13 |
| `crates/quervant-core/src/index/reconstruct.rs` | `validate_patch_shape`, `apply_document_patch`, `reconstruct_from_segment`, `reconstruct_from_document`, `SourceMeter` | AD-07 |
| `crates/quervant-core/src/index/limits.rs` | `max_query_matches`, `max_batch_keys`, `max_batch_commands`, `max_batch_response_bytes`, `max_batch_replay_keys`, `max_replay_entries/bytes`, `max_pending_*`, `max_snapshot_bytes` | AD-10 |
| `crates/quervant-core/src/remote/mod.rs` | `RemoteIndexWriter::{apply_batch,delete_by_query,…}` synchronous delegation to the local writer; no admission-time remote I/O | AD-12/I-16 |

### 2.1 Relevant exact expressions

```rust
// crates/quervant-core/src/index/writer.rs:640-653 (Phase A2, M3 effective bound)
let effective_limit = selector
    .max_matches
    .min(self.limits.max_query_matches())
    .min(self.limits.max_batch_keys());
```

```rust
// crates/quervant-core/src/search/unified.rs:323-330 (first over-limit key)
if selected.len() as u64 >= limit {
    let matched = limit.checked_add(1)...;
    limit_exceeded = Some(CompleteKeySelection::LimitExceeded { limit, matched });
    return Ok(VisitControl::Stop);
}
```

```rust
// crates/quervant-core/src/index/writer.rs:946-947 (Phase C durable preflight)
let version_2 = self.version_2_active() || prospective_state.has_batch_replay();
let encoded = prospective_state.encode_with_mode(version_2)?;
```

## 3. Pre-implementation contradiction gate (§2.1)

### 3.1 AD-05 / AD-06 (query-upsert limit routing) — **PASS, implementable**

`select_query_keys` already takes a caller-computed `effective_limit` and
returns `SelectionOutcome::LimitExceeded { limit, matched }`, where `matched` is
always `limit + 1` for the first distinct over-limit key
(`search/unified.rs:323-330`). Therefore a private, M4-local mapping is
possible exactly as AD-05 requires:

1. compute `ordinary_bound = min(selector.max_matches, max_query_matches, max_batch_keys)`;
2. call selection with `min(ordinary_bound, 1)`;
3. if `ordinary_bound >= 2` and the outcome is `LimitExceeded{1,2}` → map to
   `MutationRejection::AmbiguousQueryUpsert { matched: 2 }`;
4. if `ordinary_bound <= 1`, keep `MatchLimitExceeded { limit: ordinary_bound,
   matched: ordinary_bound + 1 }` (no ambiguity precedence override);
5. search budget, work-memory, cancellation and corruption failures propagate
   unchanged and are never converted into ambiguity.

No change to the public M3 limit semantics, the visitor, or scoring is needed
(EX-03/EX-04 have a seam). Nothing in this gate blocks implementation.

### 3.2 `MutationBatchResponse` / replay codec representability — **FAIL → HARD STOP**

The required zero-match `QueryUpsert` outcome is:

- `matched = 0` (query cardinality, §1: "`matched` means query cardinality, not
  mutation count");
- exactly one key outcome for the inserted fallback (`intent = Insert`).

The in-memory contract can hold that shape
(`contract/mutation.rs:180-225`: `matched: u64` is independent of `keys`, and
`encoded_len()` has no equality rule). The **durable v2 batch-replay codec**
rejects it in both directions:

```text
crates/quervant-core/src/index/mutation_state.rs:692-697  (encoder)
    if command.matched != command.keys.len() as u64 {
        return Err(SegmentError::Corrupt {
            context: "mutation-state batch replay",
            detail: "command matched count does not match its key list".to_owned(),
        });
    }

crates/quervant-core/src/index/mutation_state.rs:824-830  (decoder)
    if u64::from(key_count) != matched {
        return Err(SegmentError::Corrupt {
            context: "mutation-state batch replay",
            detail: "command matched count does not match its key list".to_owned(),
        });
    }
```

The invariant is pinned by an existing negative test
(`crates/quervant-core/src/index/mutation_state.rs:1511`, malformed v2 case
`"matched mismatch"`). Phase C encodes the prospective mutation state for **any**
tokenized batch (`writer.rs:946-947`), so a tokenized zero-match `QueryUpsert`
cannot be admitted, committed, reopened or replayed without changing this
validation.

#### Minimal reproducer (executed, then reverted to keep the tree clean)

Temporary `#[cfg(test)]` module appended to `index/mutation_state.rs`:

```rust
let response = MutationBatchResponse {
    outcomes: vec![MutationCommandOutcome {
        command_index: 0,
        matched: 0,
        keys: vec![MutationKeyOutcome {
            key: DocumentKey::new("fallback").unwrap(),
            intent: MutationIntent::Insert,
            revision: Some(1),
            replayed: false,
        }],
    }],
    replayed: false,
};
let state = MutationStateV1::from_parts(BTreeMap::new(), BTreeMap::new())
    .with_batch_replay(BTreeMap::from([(token, BatchReplayRow {
        token, fingerprint: [7u8; 32], response,
    })]));
state.encode().expect_err("zero-match fallback must not encode");
```

Observed:

```text
encode error: corrupt mutation-state batch replay: command matched count does not match its key list
test index::mutation_state::m4_gate_reproducer::... ... ok (asserts the typed Corrupt error)
```

This is exactly EX-02 / EX-18. Per the plan ("**HARD STOP**; report the exact
invariant/codec check and two alternatives, do not change format"), production
changes stop here.

### 3.3 Alternatives for the codec blocker (human decision required)

| Option | Change | Compatibility impact | Assessment |
|---|---|---|---|
| **A. Relax the v2 response record predicate** (recommended) | Encoder and decoder accept exactly two canonical shapes instead of equality: `matched == keys.len()`, or `matched == 0 && keys.len() == 1 && intent == Insert` (the zero-match fallback; the record itself carries `intent`, so no action metadata is needed). Keep the `u64 matched` + `u32 key count` layout, payload version 2, v2 feature bit and every existing byte unchanged | Old v2 records always satisfied equality → still decode identically; no byte/version change. Old **readers** reject v2 containers with typed `UnsupportedFeature` before payload decode (proved by `v2_requires_the_new_feature_before_payload_decode`), so no old reader ever sees the new shape. Existing malformed cases (`matched=9` with one key, `matched=2` with duplicate keys) stay rejected | Smallest change that satisfies §1/AD-10/T20 while keeping corruption detection tight. Requires explicit human approval because it amends a persisted-record **validation** rule, even though no bytes/version change is needed |
| B. Keep the strict codec, reject tokens with zero-match `QueryUpsert` | No codec change | — | Violates required durable replay (T08/T20), AD-09, AD-10; not viable |
| C. Redefine `matched` as mutation count (fallback → `matched = 1`) | Response semantics change | Alters persisted meaning; contradicts §1 and §2.1 ("do not silently redefine `matched`"); replay would no longer report query cardinality | Not viable |
| D. Persist a separate fallback outcome/section outside `outcomes` | New persisted section/record | Format change; `command_index == ordinal` validation and `encoded_len`/caps would change | HARD STOP under EX-12; not viable |
| E. Persist `matched = 1` and rewrite to `0` only on live responses | Replay would return `matched = 1` | Violates byte-identical replay (T20) and I-09 | Not viable |

**Recommended disposition:** authorize Option A (documented in the mutation-state
format notes and the M4 evidence, with a canonical-shape validation test, a new
`matched=0` + one `Insert` fallback round-trip regression, and a regression that
the old `matched > keys.len()` corruption cases are still rejected). Without
authorization, M4 remains BLOCKED and no production change is made.

## 4. Counterexample expectations (P0 item 5)

These are the §1–§2 expected outcomes derived from the current code paths and
private seams. They are recorded now, before implementation, so the acceptance
tests cannot be shaped after the fact. **None is executed yet** (blocked).

| # | Scenario | Expected outcome | Code path |
|---|---|---|---|
| a | Query selects committed key `k@r`, writer has a pending newer `k@r+1` | `PreconditionFailed{key:k, expected:ExpectedRevision(r)}`, no changes | `writer.rs:730-746` (`candidate_state_for` vs `selected_revisions`) |
| b | Zero-match upsert, fallback key live in pending but not committed | `DuplicateDocument{key}`, no changes (EX-06) | `candidate_state_for` → `admitted`; Insert path `writer.rs:764-770` |
| c | Two query commands select an overlapping key | Whole batch rejects `PreconditionFailed{ExpectedRevision}` on the second command (overlap), no changes | `delta.admitted_overrides` check `writer.rs:749-757` |
| d | Earlier explicit delete, later query replace of the same key | Whole batch rejects `PreconditionFailed{ExpectedRevision}` (writer state Deleted / overlap), no changes | `writer.rs:730-757` |
| e | Fallback key tombstoned at revision `N` | Insert at same key with revision `N+1`, `intent=Insert`, `matched=0` (EX-07) | `prospective_state_for` → `candidate_state_for` |
| f | Query-upsert, ordinary bound `1`, two distinct matches | `MatchLimitExceeded{limit:1, matched:2}`, not ambiguity (EX-04/T16) | AD-05 mapping over `LimitExceeded{1,2}` |
| g | Query-upsert, ordinary bound `2`, two distinct matches | `AmbiguousQueryUpsert{matched:2}`, no staging (AD-05/T07) | same seam, ambiguity branch |
| h | Replay after the committed generation (and match set) changed | Original response, `replayed=true`, no reselection, no generation assertion (I-09/T19) | `plan_batch` replay lookup precedes Phase A2 |
| i | Patch touches an indexed-only field with no stored/columnar source | `ReconstructionUnavailable{field, reason:UnrecoverableField}`, atomic rollback (T17) | `resolve_live_document` → `reconstruct_from_segment` |
| j | Replace template key `other`, selected key `k` | `k` preserved; template fields installed; template key never persisted (AD-04/T04) | new `rebase_template_document` (planned) |

Additional derived expectations already provable from M1/M3 contracts:
zero-match Update/Replace is a success no-op with no revision/journal change
(T02); malformed template/patch is rejected before replay lookup and selection
(T34, AD-11); fallback counts as one logical operation against
`max_batch_keys`/pending/replay caps (AD-10/T35).

## 5. AD → code / invariant → test traceability (planned, not implemented)

| ID | Planned implementation site | Planned tests | Status |
|---|---|---|---|
| AD-01 | reuse `committed_snapshot()` + `select_query_keys`; no new executor | T01,T14,T19 | BLOCKED |
| AD-02 | extend `plan_batch` routing; single `install_batch` | T12,T13,T24,T38 | BLOCKED |
| AD-03 | `MutationAction::QueryUpsert{replacement,fallback}` | T06,T07,T08,T33 | BLOCKED (codec) |
| AD-04 | `rebase_template_document` | T04,T05,T06 | BLOCKED |
| AD-05 | QueryUpsert bound/ambiguity routing | T07,T16,T28 | seam verified (§3.1) |
| AD-06 | ordinary M3 bound for Update/Replace | T15 | seam verified (§3.1) |
| AD-07 | `resolve_live_document` + `apply_document_patch` | T01,T03,T17 | BLOCKED |
| AD-08 | `stage_pending` + `prospective_documents` | T04,T06,T25 | BLOCKED |
| AD-09 | fingerprint tag `5` (replacement then fallback) | T21,T22,T32 | BLOCKED |
| AD-10 | logical-op/cap accounting incl. fallback | T08,T35,T36 | BLOCKED (codec) |
| AD-11 | Phase A template/patch validation before replay | T34 | BLOCKED |
| AD-12 | `update_by_query`/`replace_by_query`/`upsert_by_query` + remote delegations | T27 | BLOCKED |
| AD-13 | byte-preserved old discriminants/domains | T21,T22 | BLOCKED |
| AD-14 | no stats/visitor/scoring change | T37 | n/a until implementation |
| AD-15 | no idempotency/partial/multi-match additions | T33 | n/a |

| Invariant | Planned tests | Status |
|---|---|---|
| I-01..I-16 | T01..T38 as mapped in the plan §3 | Blocked: T01–T37 not implemented |

## 6. Exception dispositions

| ID | Disposition |
|---|---|
| EX-01 | **Blocked by §3.2** — the existing codec cannot encode `matched=0` with one fallback outcome |
| EX-02 | **Triggered at P0, then resolved** by human M4-AD16 authorisation of Option A (§0/§9); no format change |
| EX-03 / EX-04 | Seam exists and is verified (§3.1); no action needed |
| EX-05 / EX-06 / EX-07 / EX-08 / EX-09 | Reachable through existing helpers (`candidate_state_for`, `prospective_state_for`, Insert staging, `admitted_overrides`); documented, unexercised |
| EX-10 / EX-11 / EX-13 | Not reached (no code edits) |
| EX-12 | Would be needed for alternatives D/E; **not** used |
| EX-14 | Not triggered: M3 merged unchanged at `0af6759` |
| EX-15 | RustFS gate not attempted: no M4 code exists to qualify; no fake evidence offered |
| EX-16 | Baseline focused suites green (§1.2); workspace baseline green (§1.3) |
| EX-17 | No unspecified precedence needed for the gate |
| EX-18 | **Triggered at P0, then resolved** by M4-AD16: the response keeps `matched` as selector cardinality and the codec validates the exact two shapes (§9) |
| EX-19 / EX-20 | No public `Upsert(Document)` change; no M1–M3 defect found in the inspected paths |

## 7. Observations outside M4 scope (not modified)

- `docs/TESTING.md` on `main` contains four leftover merge-conflict markers
  (`<<<<<<< HEAD` etc., lines 56–59; introduced by `0568cce "PR 7 Phase 0"`).
  Pre-existing documentation defect, unrelated to M4 and not fixed here
  (EX-20: no opportunistic changes).

## 8. Next step (P0)

P0's requested authorization was granted as **M4-AD16** (see §0). Implementation
resumed at P1 and the full plan P1–P5 work is recorded in Part II (§9–§12).

---

# Part II — M4 implementation evidence

Base: `4e64acb` (M3 merged). P0 evidence commit: `1c59e2c`. Implementation and
qualification working tree is described in §12 (final SHA recorded there).

## 9. M4-AD16 implementation (approved Option A)

### 9.1 Shared private predicate

`crates/quervant-core/src/index/mutation_state.rs`:

```rust
fn batch_outcome_cardinality_is_valid(matched: u64, keys: &[MutationKeyOutcome]) -> bool {
    if u64::try_from(keys.len()).ok() == Some(matched) {
        return true;
    }
    matched == 0 && keys.len() == 1 && keys[0].intent == MutationIntent::Insert
}
```

It is private, has no new enum variant, no new persisted field and no alternate
decoder. Rejections keep `SegmentError::Corrupt` with context
`mutation-state batch replay` and the existing detail string.

### 9.2 Encoder and decoder anchors

| Site | Change |
|---|---|
| `mutation_state.rs::encode_batch_response` | the direct `command.matched != command.keys.len() as u64` rejection is replaced by `batch_outcome_cardinality_is_valid`; ordinal, replay-flag, ascending-key, intent/revision, length-prefix, encoding-order and allocation checks are untouched |
| `mutation_state.rs::decode_batch_response` | the premature equality rejection right after `matched`/`key_count` is removed; `check_entries` and `check_alloc` still run **before** allocation; the shared predicate runs immediately after the command's outcomes are decoded; ordinal, key order, intent, revision, replay-flag, trailing-byte and container validations are unchanged |

### 9.3 Compatibility and format

- No payload version, `FEATURE_MUTATION_STATE_V2` bit, section, layout or field
  order changed. `u64 matched` + `u32 key count` were already independent fields.
- Previously valid v2 records always satisfied equality and still decode with
  identical bytes (verified by the existing round-trip and malformed-v2 suites
  and the pre-M4 fingerprint goldens in §10).
- Old readers reject v2 containers with typed `UnsupportedFeature` before any
  payload decode (`v2_requires_the_new_feature_before_payload_decode`), so no
  old reader observes the new shape; this claim is limited to the existing
  compatibility contract.
- Malformed shapes remain rejected: `matched=9` with one key, `matched=1` with
  two keys, `matched=0` with an `Upsert`/`Delete` outcome, `matched=0` with two
  `Insert` outcomes (encoder + hand-built decoder fixtures: `AD16-T01..T10`).

## 10. M4 functional implementation

| Area | Implementation |
|---|---|
| Contract | additive `MutationAction::QueryUpsert { replacement, fallback }`; rustdoc for query-only scope, template rebasing, fallback and ambiguity; `MutationAction::Upsert(Document)` unchanged |
| Matrix | `Query + Delete/Update/Replace/QueryUpsert` admitted; `Query + Insert`, `Query + Upsert`, `Key`/`Keys + QueryUpsert` typed `UnsupportedTargetAction` (preflight, before replay/allocation) |
| Selection | one committed batch-initial snapshot, M3 `select_query_keys`, M3 effective bound; no new executor, no pagination, no volatile token |
| QueryUpsert bound | `ordinary = min(selector.max_matches, max_query_matches, max_batch_keys)`; visitor bound `min(ordinary, 1)`; `LimitExceeded{1,2}` → `AmbiguousQueryUpsert{2}` only when `ordinary >= 2`, else `MatchLimitExceeded` |
| Update by query | per-key selected-revision/overlap checks, M2 `resolve_live_document` + `apply_document_patch`, one revision per key |
| Replace by query | `rebase_template_document` (new private writer helper) → schema validation → `stage_pending` |
| QueryUpsert 1 match | rebase `replacement` onto the selected key; `intent = Upsert`; fallback validated but not inserted |
| QueryUpsert 0 matches | fallback eligibility frozen at batch-initial writer state: live → `DuplicateDocument`; earlier in-batch touch → `PreconditionFailed`; tombstone → insert at `previous + 1`; fallback staged unaltered at its own key; response `matched=0` + one explicit `Insert` outcome; one logical operation against every cap |
| Fingerprint | additive action tag `5`; encodes `replacement` then `fallback` with the existing document encoder; old tags `0..4`, v1 explicit domain and M3 v2 query domain unchanged; pre-M4 goldens hardcoded in `m4_fingerprint_tests` |
| Remote | `RemoteIndexWriter::{update_by_query, replace_by_query, upsert_by_query}` synchronous delegations; no admission-time remote I/O (`m4_t27`) |

## 11. Traceability

### 11.1 AD16 tests

| ID | Test | Result |
|---|---|---|
| AD16-T01 | `index::mutation_state::ad16_tests::ad16_t01_equality_shapes_round_trip` | PASS |
| AD16-T02 | `…::ad16_t02_zero_match_empty_outcomes_round_trip` | PASS |
| AD16-T03 | `…::ad16_t03_zero_match_single_insert_fallback_round_trips` | PASS |
| AD16-T04 | `…::ad16_t04_zero_match_single_upsert_is_rejected` | PASS (encoder + crafted decode) |
| AD16-T05 | `…::ad16_t05_zero_match_single_delete_is_rejected` | PASS (encoder + crafted decode) |
| AD16-T06 | `…::ad16_t06_zero_match_two_inserts_are_rejected` | PASS (encoder + crafted decode) |
| AD16-T07 | `…::ad16_t07_one_match_two_outcomes_is_rejected` | PASS (encoder + crafted decode) |
| AD16-T08 | `…::ad16_t08_two_matches_one_outcome_is_rejected` | PASS (encoder + crafted decode) |
| AD16-T09 | `…::ad16_t09_large_matched_mismatch_is_still_rejected`; existing `u14_malformed_v2_records_are_typed_rejections` `"matched mismatch"` | PASS |
| AD16-T10 | `…::ad16_t10_decoder_keeps_independent_validation`; existing v2 malformed suite | PASS |
| AD16-T11 | `m4_query_mutations::m4_t20_tokenized_zero_match_fallback_commit_reopen_and_replay` | PASS |
| AD16-T12 | `m4_query_mutations::m4_t32_replacement_and_fallback_each_change_the_idempotency_fingerprint` | PASS |
| AD16-T13 | `m4_query_mutations::m4_t09_zero_match_fallback_live_in_committed_state_rejects` (plus `m4_t10` pending) | PASS |
| AD16-T14 | `m4_query_mutations::m4_t29_tombstoned_fallback_inserts_at_the_next_revision`, `m4_t30_earlier_command_touching_the_fallback_key_rejects_the_batch` | PASS |
| AD16-T15 | `m4_query_mutations::m4_t18_cancellation_leaves_no_partial_admission`, `m4_t35_query_resource_caps_fail_closed_without_state_change`, `m4_t24_mixed_batch_late_failure_leaves_no_prefix` | PASS |
| AD16-T16 | `m4_query_mutations::m4_t26_real_rustfs_query_mutations_reopen_and_replay` (ignored, 3/3 real runs — §12.3) | PASS |

The adversarial non-Insert decoder check required by §4 of the AD16
instructions is `ad16_t04`/`ad16_t05`/`ad16_t06`: hand-built v2 payloads (not
produced by the production encoder) with `matched=0, key_count=1` and
`Upsert`/`Delete` intent, plus the two-`Insert` variant, all rejected as
`Corrupt`.

### 11.2 Original M4 acceptance tests

| Test | Name | Result |
|---|---|---|
| T01 | `m4_t01_query_update_patches_every_selected_key_only` | PASS |
| T02 | `m4_t02_zero_match_update_is_a_noop_without_revisions` | PASS |
| T03 | `m4_t03_query_update_preserves_every_untouched_field_state` | PASS |
| T04 | `m4_t04_query_replace_uses_template_fields_and_keeps_selected_keys` | PASS |
| T05 | `m4_t05_query_replace_removes_fields_omitted_by_the_template` | PASS |
| T06 | `m4_t06_query_upsert_one_match_replaces_selected_key_and_ignores_fallback` | PASS |
| T07 | `m4_t07_query_upsert_two_matches_is_ambiguous_and_atomic` | PASS |
| T08 | `m4_t08_query_upsert_zero_matches_inserts_fallback_with_matched_zero` | PASS |
| T09 | `m4_t09_zero_match_fallback_live_in_committed_state_rejects` | PASS |
| T10 | `m4_t10_zero_match_fallback_live_only_in_pending_state_rejects` | PASS |
| T11 | `m4_t11_selected_key_with_pending_newer_revision_rejects` | PASS |
| T12 | `m4_t12_earlier_explicit_command_overlapping_a_selected_key_rejects`; `m4_t12b_convenience_delegations_build_one_typed_command_each` | PASS |
| T13 | `m4_t13_two_query_commands_selecting_the_same_key_reject` | PASS |
| T14 | `m4_t14_query_does_not_select_a_key_inserted_earlier_in_the_batch` | PASS |
| T15 | `m4_t15_query_bounds_fail_closed_without_truncation` | PASS |
| T16 | `m4_t16_query_upsert_bound_one_two_matches_is_a_limit_not_ambiguity` | PASS |
| T17 | `m4_t17_query_update_rejects_an_unreconstructable_source` | PASS |
| T18 | `m4_t18_cancellation_leaves_no_partial_admission` | PASS |
| T19 | `m4_t19_replay_does_not_rerun_selection_after_the_match_set_changes` | PASS |
| T20 | `m4_t20_tokenized_zero_match_fallback_commit_reopen_and_replay` | PASS |
| T21 | `index::mutation_state::m4_fingerprint_tests::m4_t21_t22_pre_m4_fingerprints_are_byte_compatible` (goldens generated from base `4e64acb`) | PASS |
| T22 | same test (M3 query-delete golden) | PASS |
| T23 | `m4_t23_pit_pinned_before_query_mutation_stays_immutable` | PASS |
| T24 | `m4_t24_mixed_batch_late_failure_leaves_no_prefix` | PASS |
| T25 | `m4_t25_filesystem_commit_and_reopen_for_each_m4_action` | PASS |
| T26 | `m4_t26_real_rustfs_query_mutations_reopen_and_replay` (real RustFS, 3 independent runs) | PASS |
| T27 | `m4_t27_remote_admission_performs_no_remote_io_and_replays` | PASS |
| T28 | `m4_t28_upsert_with_batch_key_limit_one_reports_the_limit_not_ambiguity` | PASS |
| T29 | `m4_t29_tombstoned_fallback_inserts_at_the_next_revision` | PASS |
| T30 | `m4_t30_earlier_command_touching_the_fallback_key_rejects_the_batch` | PASS |
| T31 | `m4_t31_preconditions_apply_to_selected_and_fallback_cases` | PASS |
| T32 | `m4_t32_replacement_and_fallback_each_change_the_idempotency_fingerprint`; unit `m4_t32_query_upsert_fingerprint_is_deterministic_and_covers_both_documents` | PASS |
| T33 | `m4_t33_unsupported_target_action_pairs_are_typed` | PASS |
| T34 | `m4_t34_validation_precedes_replay_lookup` | PASS |
| T35 | `m4_t35_query_resource_caps_fail_closed_without_state_change` | PASS |
| T36 | Revision-overflow half: existing `index::writer::batch_tests::a03_revision_overflow_rejects_the_whole_batch` (full writer-state equality). Response-size arithmetic half: the `encoded_len` checked-arithmetic branch is unreachable with a bounded in-memory response; the cap path that consumes it is covered by T35 (`ResourceLimit`). | PARTIAL — documented disposition; no fabricated test |
| T37 | `m4_t37_scored_search_and_delete_by_query_are_unaffected`; full M3 suite re-run | PASS |
| T38 | Optional seeded reference-model differential test | NOT IMPLEMENTED — plan §5 permits omission when no existing deterministic seeded harness exists; determinism is covered by fixed fixtures and exact-state assertions |

Additional writer-granularity tests (full `state_snapshot()` equality on every
rejection path): `index::writer::batch_tests::m4_u01_zero_match_fallback_conflicts_are_atomic_and_tombstones_revive`,
`m4_u02_query_templates_are_rebased_onto_selected_keys`.

## 12. Qualification

### 12.1 Commands and results (final working tree)

| Gate | Command | Result |
|---|---|---|
| Stable fmt | `cargo fmt --all -- --check` | PASS |
| Stable Clippy (default) | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| Stable Clippy (all features) | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Workspace tests (default) | `cargo test --workspace --all-targets` | PASS — 1951 passed, 0 failed, 9 ignored (105 suites) |
| Workspace tests (all features) | `cargo test --workspace --all-targets --all-features` | PASS — 1955 passed, 0 failed, 66 ignored (105 suites) |
| M1 focused | `cargo test -p quervant-core --all-features --test m1_batches` | PASS — 14 passed, 1 ignored |
| M2 focused | `… --test m2_patches` | PASS — 10 passed, 1 ignored |
| M3 focused | `… --test m3_delete_by_query` | PASS — 29 passed, 1 ignored |
| M4 focused | `… --test m4_query_mutations` | PASS — 34 passed, 1 ignored |
| MSRV fmt | `cargo +1.85.0 fmt --all -- --check` | PASS |
| MSRV Clippy (all features) | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| MSRV tests (all features) | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 1955 passed, 0 failed, 66 ignored (105 suites) |
| Documentation | `cargo doc --workspace --all-features --no-deps` | PASS |
| Benchmark build | `cargo bench --workspace --no-run` | PASS |
| Benchmark scripts | `bash benchmarks/scripts/test-scripts.sh` | PASS |
| Whitespace | `git diff --check` | PASS |
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.15% lines** (47145 lines, 4171 missed); regions 91.76%; functions 87.04% |

### 12.2 Failures encountered during implementation and classification

| Failure | Classification | Resolution |
|---|---|---|
| `m1_raw_ceiling_keeps_existing_typed_rejections`, `m2_v02_public_errors_are_typed_and_atomic`, `m3_t01_query_delete_only` asserted pre-M4 `Query+Update → UnsupportedTargetAction` | **Intended behaviour change** (M4 activates the action) | Assertions updated to keep the still-unsupported `Query+Insert` / `Query+Upsert` / `Key+QueryUpsert` cases and the invalid-patch rejection; no test deleted or renamed |
| `raw_key_preflight_preserves_typed_error_precedence` asserted the same pre-M4 restriction | **Intended behaviour change** | Split into "query update contributes zero raw keys" and "query insert is unsupported" |
| New tests initially used PR 14's indexed-only `raw` field and the wrong JSON `body` type | **Test fixture defect (new code)** | Dedicated all-stored/columnar M4 schema; PR 14 schema retained only for the reconstruction-failure test where appropriate |
| `clippy::format_collect` on the golden hex helper (MSRV Clippy only) | **Introduced regression (lint)** | Rewritten with `std::fmt::Write`; both toolchains re-run clean |
| `HEAD`-worktree golden generation used a different document payload | **Test-authoring defect** | Golden test uses the exact payload the base commit hashed |

No pre-existing baseline failure and no unresolved flake remain.

### 12.3 Real RustFS qualification

- Runtime: `podman` (Docker unavailable on the host); pinned image
  `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
  (same digest as `.github/workflows/ci.yml`), container `quervant-m4-rustfs`,
  endpoint `http://127.0.0.1:9000`, health `/health` → 200.
- Credentials/bucket per CI contract (`QUERVANT_RUSTFS_*`, bucket
  `quervant-m4-local`); every M4 run uses a unique
  `m4/m4-t26-<pid>-<nanos>` prefix and a fresh local workspace, so the three
  runs are independent clean namespaces. The ignored test also creates the
  bucket if absent.
- Three independent M4 runs: **3/3 PASS** (each `1 passed, 0 failed`, real S3
  I/O through the production adapter with a cold remote reopen and durable
  replay of the zero-match fallback).
- Regression runs on the same service: M1 `1 passed`, M2 `1 passed`, M3 `3/3`
  runs `1 passed` each, `pr13_remote` 3 passed, `pr13_oracle` 1 passed,
  `pr13_oracle_geo` 1 passed, `pr13_s3_rustfs` 8 passed, `pr13_proxy_rustfs`
  5 passed. All `rc=0`.

### 12.4 Residual risks

| Risk | Evidence/disposition |
|---|---|
| Durable response cardinality is shape-validated, not action-proven | Accepted and documented by M4-AD16; the planner is the only producer and all eligibility/revision/overlap/precondition/cap checks are enforced there and tested (T07–T11, T28–T31, T35) |
| Zero-match fallback commit crash windows | Reuses the unchanged M1/M2 commit/CURRENT protocol; no new durable artefact; M5 owns broader crash matrices |
| Memory peaks during multi-match update/replace | Reconstruction is bounded by `max_snapshot_bytes` per distinct segment and patch/pending caps; T35 exercises caps; no full-match materialization beyond bounded key vectors |
| Cancellation granularity | Checkpoints are unchanged: phase A, per command, per selected key, and inside the search visitor; cancellation cannot occur mid-installation. T18 calibrates the final pre-staging checkpoint |
| Source reconstruction coverage | The schema-wide conservative rule still rejects any document with an indexed-only field (T17); M4 adds no new reconstruction path |
| `docs/TESTING.md` merge-conflict markers | Pre-existing on `main` (`0568cce`); reported, not edited (M4-AD16 §5.7) |

## 13. Status and handoff

- **IMPLEMENTED:** yes (contract, planner, codec amendment, delegations, docs).
- **LOCALLY QUALIFIED:** yes — stable 1.98.1 and MSRV 1.85.0 fmt/Clippy/tests,
  workspace default/all-features, focused M1–M4, coverage 91.15%, docs, benches,
  scripts, whitespace.
- **REAL RUSTFS QUALIFIED:** yes — M4 3/3 independent runs plus M1/M2/M3 and
  PR13 remote-oracle regressions (§12.3).
- **PUSHED / CI:** recorded in the agent's final report for the commit
  containing this document. `DONE` is not claimed; final-SHA CI is required and
  merging requires explicit human authorization.
