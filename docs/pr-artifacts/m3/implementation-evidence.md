# M3 — Atomic delete by query: implementation evidence

**Status: HARD STOP — `M3-AD09` (query selector is not covered by the durable
batch fingerprint). No M3 production implementation was attempted. This is a
blocked/not-verified report, not implementation evidence.**

- Branch: `dev/m3-delete-by-query`
- Baseline/current `HEAD`: `bea042fea2ed106ae014c13fca0773fe49436fc7`
- `origin/main` and local `main`: the same `bea042f` commit
- Required M2 ancestry: PR #50 merge `874ac40b9e2b2948306be03c102f034e2275bc56`
  is an ancestor of `HEAD` (`git merge-base --is-ancestor 874ac40 HEAD` PASS)
- Working tree at branch creation: clean
- Host: Linux x86-64; stable `rustc 1.98.1`, MSRV `rustc 1.85.0`
- Plan: `QUERVANT_M3_DETAILED_IMPLEMENTATION_PLAN.md`

No source, test, manifest, CI, or roadmap file was modified. The only artifact
is this report.

## 1. P0 baseline (read-only gate)

| Item | Actual |
|---|---|
| `git fetch origin` | PASS |
| `git rev-parse HEAD` | `bea042fea2ed106ae014c13fca0773fe49436fc7` |
| `git rev-parse origin/main` | `bea042fea2ed106ae014c13fca0773fe49436fc7` |
| `git merge-base --is-ancestor 874ac40 HEAD` | PASS (0) |
| `git status --short` before work | clean |
| Branch created from verified `HEAD` | `dev/m3-delete-by-query` |
| Stable toolchain | `rustc 1.98.1`, `cargo 1.98.1` |
| MSRV toolchain | `rustc/cargo 1.85.0` available |
| Baseline `cargo test -p quervant-core --lib` | **PASS** — 715 passed, 0 failed, 1 ignored |
| Baseline stable default Clippy | **PASS** — `cargo clippy -p quervant-core --all-targets -- -D warnings` |
| Baseline stable all-feature Clippy | **PASS** — `cargo clippy -p quervant-core --all-targets --all-features -- -D warnings` |
| Baseline MSRV all-feature Clippy | **PASS** — `cargo +1.85.0 clippy -p quervant-core --all-targets --all-features -- -D warnings` |
| Formatting | **PASS** — `cargo fmt --all -- --check` |
| Whitespace | **PASS** — `git diff --check` |

## 2. Source inventory reconciled against the plan

| Planned component | Current source fact |
|---|---|
| `contract/mutation.rs` | `MutationTarget::{Key,Keys,Query}`, `QueryMutationSelector { query, max_matches, expected_generation }`, `MutationAction::Delete`, `MutationRejection::{MatchLimitExceeded,StaleSelection}` all present (`contract/mutation.rs:31`, `:40`, `:265`, `:277`). |
| `index/writer.rs` | `apply_batch` → `plan_batch` → `install_batch` present (`:446`, `:459`, `:1000`); `BatchDelta`, prospective simulation and single installation present. |
| `index/writer.rs` selection prerequisites | `candidate_state_for` (`:1396`), `committed_snapshot` (`:1589`), `committed_segments` (`:1443`), replay lookup (`:1470`, `:1491`) present. |
| `index/limits.rs` | Batch limits present; **no** `max_query_matches` present, as expected. |
| `search/unified.rs` | `UnifiedSearcher`, `UnifiedRequest` and `collect_mixed` present. `collect_mixed` evaluates every effective-live document and computes exact `total_hits`, but only retains top-K (`:318`–`:674`). |
| `search/execute.rs` | `evaluate_lexical_with` performs the complete per-document membership loop (`:1743`). |
| `index/mutation_state.rs` | `BatchReplayRow` stores a single `fingerprint: [u8; 32]` (`:145`) and `MutationStateV1::encode_with_mode` is the durable replay encoding. |
| `remote/mod.rs` | `RemoteIndexWriter::apply_batch` delegates to the local writer; no admission-time remote I/O was found in the local path. |
| M1/M2 suites | `crates/quervant-core/tests/m1_batches.rs`, `m2_patches.rs` and `m1_compat/` present. |

## 3. Feasibility probe (§2.1): enumeration is feasible; replay binding is not

### 3.1 Committed selection view

`IndexWriter::committed_snapshot()` (`index/writer.rs:1589`) builds a
`ReaderSnapshot` from `committed_segments()` and the committed masks only. It
does not read `self.pending`, `self.flushed`, `self.journal` or `writer.reader()`,
so a selection snapshot can exclude uncommitted/flushed/volatile changes and can
be held for the full selection phase. `ReaderSnapshot::effective_live_docs`
(`index/snapshot.rs:464`) intersects the segment live bitmap with the committed
generation mask. A missing committed generation yields an empty committed view.

**Result: PASS.** No STOP here.

### 3.2 Complete membership

`collect_mixed` (`search/unified.rs:318`) opens every segment, computes the
effective live set, expands the compiled query, calls
`evaluate_lexical_with` for every live document, evaluates typed/JSON/geo leaves
through the shared `evaluate_unified` predicate, and accumulates exact
`total_hits`. It then retains only a bounded top-K heap.

A private complete-key visitor can therefore be implemented **without forking
query semantics** by compiling the same `UnifiedPlan` and reusing
`evaluate_lexical_with` plus `evaluate_unified`, replacing only the top-K
retention with a bounded, deduplicated key vector. This is the executor
extension explicitly pre-authorized by §2.1.

**Result: PASS — a private visitor is feasible.** `TopK(max_matches)`,
`total_hits` alone and repeated fresh snapshots are not required.

### 3.3 Query errors

`SearchError` already distinguishes query/analysis/segment/index, resource,
cancel, corruption and invalid-score failures (`search/error.rs`). These map to
existing `IndexError` variants (`Contract`, `Analysis`, `Segment`, `ResourceLimit`,
`Cancelled`, `CorruptCommittedState`) without treating a failure as a partial or
empty selection. No new public error variant is required for this conversion.

**Result: PASS.** No STOP here.

### 3.4 Durable idempotency fingerprint — **STOP**

The whole-batch fingerprint is the sole durable binding between an idempotency
token and the original request:

- `batch_fingerprint` hashes the domain tag plus each command
  (`index/mutation_state.rs:982`–`:995`).
- `encode_fingerprint_target` for `MutationTarget::Query` writes **only**
  `max_matches` and `expected_generation`
  (`index/mutation_state.rs:1017`–`:1028`). It does **not** encode
  `selector.query`.
- `plan_batch` compares only `existing.fingerprint == fingerprint`
  (`index/writer.rs:536`–`:551`) and stores that same fingerprint in the durable
  `BatchReplayRow` (`:750`–`:770`).
- The existing unit test `query_targets_are_fingerprinted_deterministically`
  proves determinism and `max_matches` sensitivity, but not query sensitivity
  (`index/mutation_state.rs:1689` onward).

#### Reproduction (transient probe, reverted)

A temporary unit test was inserted into `index/mutation_state.rs`, run, and then
the file was restored byte-for-byte. It built two query-delete batches with
identical `max_matches = 7` and `expected_generation = Some(3)` but different
selectors (`Query::MatchAll` vs a `Query::Term`) and asserted the two
fingerprints are equal:

```text
test index::mutation_state::m1_rejection_tests::m3_fingerprint_gap_probe ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 716 filtered out
```

`git status --short` and `git diff --check` were clean after the probe was
reverted.

#### Consequence

With the current fingerprint, a durable query-delete token can be replayed
against a **different query** that shares the same `max_matches` and
`expected_generation`, returning the original response without re-executing the
selector. This violates M3 frozen semantics S08 (whole-batch fingerprint must
bind the complete request) and invariant M3-I10 / tests T21–T22.

This is exactly pre-authorized decision **M3-AD09**:

> Query fingerprint lacks selector fields → **HARD STOP**: cannot change replay
> semantics ad hoc.

No implementation was attempted after this finding.

## 4. Minimal alternatives requiring explicit human approval

The plan forbids changing fingerprint bytes/replay wire format without approval.
The smallest credible options are:

1. **Versioned batch fingerprint that includes the query selector.**
   Add canonical, domain-separated encoding of `Query` to the query-target
   fingerprint. Because explicit-key batches must retain replay compatibility,
   the safest shape is a new domain/version used **only** for batches containing
   a query target, leaving all existing explicit-key/M1/M2 fingerprints
   byte-identical. New durable replay rows for query batches would use the new
   domain. This still changes replay semantics for a previously rejected request
   shape and therefore needs explicit approval.
2. **A second durable binding field on `BatchReplayRow`.**
   Store an independent query-selector fingerprint alongside the existing
   fingerprint and require both to match. This changes the durable mutation-state
   encoding (`MutationStateV1`/`FEATURE_MUTATION_STATE_V2`) and therefore needs
   explicit approval and a format-version decision.
3. **Reject idempotency tokens for query-target batches.**
   This avoids the unsafe binding but removes a required M3 capability
   (S08/T19/T21/T22), so it is not an acceptable M3 implementation.

Option 1 is the least invasive and preserves existing explicit-key replay
bytes. It is **not implemented here** because M3-AD09 requires a human decision
before changing replay semantics.

## 5. Checks not executed because the feature is blocked

- No `crates/quervant-core/tests/m3_delete_by_query.rs` was created.
- No M3 unit/integration tests, independent oracle, seed sequences, RustFS
  vertical, real-boundary I/O spy, coverage run or benchmark comparison was run.
- No `.github/workflows/ci.yml` change was made.
- No `docs/ROADMAP_V01.md` change was made; M3 remains `PLANNED`.
- No production line-coverage or full workspace gate is claimed for M3.

## 6. Required decision

Request human authorization for one of the alternatives in §4, preferably a
versioned query-inclusive batch fingerprint that leaves existing explicit-key
replay bytes unchanged. Until then, M3 is **BLOCKED / NOT VERIFIED** under
`M3-AD09`, not implemented, not DONE, and not ready for merge.
