# M4 — Query-targeted update, replace and restricted upsert: P0 evidence

**Status: BLOCKED at the pre-implementation contradiction gate (§2.1 / EX-02 /
EX-18). No production code changed. Not DONE, not implemented, not qualified.**

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
| EX-02 | **Triggered** — HARD STOP; alternatives in §3.3 |
| EX-03 / EX-04 | Seam exists and is verified (§3.1); no action needed |
| EX-05 / EX-06 / EX-07 / EX-08 / EX-09 | Reachable through existing helpers (`candidate_state_for`, `prospective_state_for`, Insert staging, `admitted_overrides`); documented, unexercised |
| EX-10 / EX-11 / EX-13 | Not reached (no code edits) |
| EX-12 | Would be needed for alternatives D/E; **not** used |
| EX-14 | Not triggered: M3 merged unchanged at `0af6759` |
| EX-15 | RustFS gate not attempted: no M4 code exists to qualify; no fake evidence offered |
| EX-16 | Baseline focused suites green (§1.2); workspace baseline green (§1.3) |
| EX-17 | No unspecified precedence needed for the gate |
| EX-18 | **Triggered** — HARD STOP; no response-semantic workaround applied |
| EX-19 / EX-20 | No public `Upsert(Document)` change; no M1–M3 defect found in the inspected paths |

## 7. Observations outside M4 scope (not modified)

- `docs/TESTING.md` on `main` contains four leftover merge-conflict markers
  (`<<<<<<< HEAD` etc., lines 56–59; introduced by `0568cce "PR 7 Phase 0"`).
  Pre-existing documentation defect, unrelated to M4 and not fixed here
  (EX-20: no opportunistic changes).

## 8. Next step

1. Human authorization for §3.3 Option A (or a different disposition).
2. On authorization, resume the plan at P1 and carry the codec change as an
   explicitly approved amendment with:
   - canonical-shape validation in the v2 response encoder/decoder,
   - a new regression for `matched=0` + one fallback outcome,
   - the existing `matched > keys.len()` corruption case retained,
   - the mutation-state format notes in `docs/decisions/` updated to state that
     `matched` is selector cardinality, not key-outcome count.
3. Re-run every P0 baseline gate after the final M4 patch (P5), including
   coverage, MSRV and three real-RustFS runs.
