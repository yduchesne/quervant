# PR 15E-B1 — decision log

Entries record the decision-matrix IDs that actually triggered, the observation, the
action taken and its owner. Nothing here is retroactive; no condition was reinterpreted
to avoid escalation.

## D01 / D02 — G11 gate

| Field | Value |
|---|---|
| Observation | `docs/pr-artifacts/pr-15e-a/fixup-review-handoff.md` still states `G11 = PENDING_REVIEW` and `PR15E_B_AUTHORIZED = NO`; no named reviewer verdict exists anywhere in the tree |
| Plan classification | `HARD STOP` (D02) |
| Action (first pass) | Reported `BLOCKED_G11` with evidence; performed source reconnaissance only; made no changes |
| Human decision | The repository maintainer **explicitly waived G11 as a prerequisite** for PR 15E-B1 implementation by direct authorization, citing the existing profiling report and audit receipt (25/25 checks) as sufficient evidence, and instructed that no formal G11 PASS be claimed |
| Action (second pass) | Proceeded with P0–P9 under that documented exception; PR 15E-A dossier, private evidence and the `PENDING_REVIEW` status are unchanged |
| Owner | Maintainer (waiver), coding agent (implementation) |
| Residual risk | B1 rests on PR15E-A evidence that has **not** been independently reviewed. The waiver covers authorization to implement, not the truth of the profiling conclusions; the targeted B1 measurements were designed to be independently interpretable |

## D03 — source seams match the reviewed design

| Field | Value |
|---|---|
| Observation | On `c3083d8`, `visit_lexical_membership_with` and `evaluate_lexical_with` still build `live_count`/`live_bytes`, `reserve_with_memory`, `BTreeSet<u64>`, `for doc_id in &live_set`, `drop`, `release_with_memory`; `LeafData::matches` still linear-scans; `execute_segment_inner` keeps its own charged `live_set`; `Phrase` arm unchanged; `unified.rs::select_keys`/`collect_mixed` and `work.rs` unchanged |
| Classification | `AUTO-RESOLVE` |
| Action | Branched `dev/pr15e-b1-live-bitmap-postings-membership` from fresh `main`; recorded SHA and frozen-artefact hashes |

## D05 — temporary live-set reservations only backed the removed collection

| Field | Value |
|---|---|
| Observation | In both functions the paired `reserve_with_memory(live_count, live_bytes, …)` covered exactly the `BTreeSet<u64>` built immediately after it and released immediately after `drop(live_set)`; the set was never returned, scored, observed by a callback or used for any cap decision |
| Classification | `AUTO-RESOLVE` |
| Action | Removed only the paired reserve/release and the now-unused locals in those two functions; kept every other charge site |
| Why not D06 | The reservation had no independent normative role: it tracked a collection that no longer exists, and `live_count` was not used for any other budget decision |

## D07 — decoded postings are strictly ascending

| Field | Value |
|---|---|
| Observation | `PostingsReader::next_with` computes `doc_id = previous + delta` and rejects `delta == 0` (`NonMonotoneDocId`), plus out-of-range ids and zero frequencies; both production `TermPostings` constructors push in decoded order; `build_leaf_data` only filters by `live` |
| Classification | `AUTO-RESOLVE` |
| Action | `binary_search_by_key` in the `Term` arm only; documented the invariant on `TermPostings`; added `S::decoder_rejects_nonmonotone_doc_id_deltas` |
| Why not D08 | The only other constructor is the `#[cfg(test)]` `term_leaf` helper, which takes caller-supplied ids; it is documented and used with ascending ids. No production path can build an unsorted vector |

## D09 — formerly rejected queries now succeed

| Field | Value |
|---|---|
| Observation | `min_total_candidate_bytes` for a 1000-live-doc index with one match moved from `48016` (baseline, = 48×1000 + 16) to the same value as a 10-doc index; queries whose only constraint was the transient charge are now admitted |
| Classification | `AUTO-RESOLVE` |
| Action | Documented as an intentional admissibility improvement; asserted that real retained peaks still reject at `peak - 1` and that high-match requests still scale with retained hits |

## Variance — test-only addition outside the listed test locations

| Field | Value |
|---|---|
| Observation | The plan allowed new tests in `execute.rs`'s `#[cfg(test)]` module, `unified.rs`'s test module and/or `tests/pr15e_b1.rs`. The decoder-side ordering invariant B1b depends on (rejecting a zero doc-id delta on read) had no existing assertion; `encode_postings_block`/`PostingsReader` are not reachable from an integration test |
| Action | Added one test to `crates/quervant-core/src/segment/tests.rs`, which is `#[cfg(test)] mod tests;` — compiled only for unit tests, never shipped |
| Classification | Test-only; no production code, API, format or dependency change |
| Owner | Coding agent, explicitly disclosed here for reviewer awareness |

## D11 — operator idle confirmation unavailable

| Field | Value |
|---|---|
| Observation | No real operator attestation was available to the agent; the runner refuses to time without `--idle-confirmed` and the agent must not synthesize it |
| Classification | `DEFER AND CONTINUE` |
| Action | Completed implementation, tests, docs and the full mandatory QA matrix; classified performance as `PERF_BLOCKED_OPERATOR`; validated the entire untimed pipeline (build, corpus, index, metadata, per-lane oracle) so the operator run is de-risked |
| Not done | No timing, no ratios, no `MEASURED` state, no performance claim |

## D13 — regression/ambiguity policy (pre-registered, not yet triggered)

| Field | Value |
|---|---|
| Rule in force | Any lane whose paired trial ratios disagree in sign is `INCONCLUSIVE`; a consistently slower lane is `A_FASTER` and must be escalated for human accept/revert rather than hidden or backed out |

## D17 — do not broaden the experiment

| Field | Value |
|---|---|
| Observation | B1 changes unified per-live traversal and per-term membership only |
| Action | Did not run Lucene/Tantivy, the full PR15D matrix, or a new `perf`/Heaptrack campaign; no profiling window was requested |

## Environment notes (transparency)

| Field | Value |
|---|---|
| Real RustFS gate | Executed locally with **podman** (Docker absent) using the exact CI image digest `rustfs/rustfs@sha256:1803faef…`, the exact CI env vars and the exact CI commands; all 26 invocations passed |
| `perf`/Heaptrack | Not installed; not required for B1 and not used |
| Coverage tool | `cargo llvm-cov` (installed) |
| Host | WSL2, `ext4`; the targeted benchmark host fingerprint is recorded by the runner at run time |
