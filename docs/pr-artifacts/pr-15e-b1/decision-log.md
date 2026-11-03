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
| Action (first pass) | Completed implementation, tests, docs and the full mandatory QA matrix; classified performance as `PERF_BLOCKED_OPERATOR`; validated the entire untimed pipeline (build, corpus, index, metadata, per-lane oracle) so the operator run was de-risked |
| Action (second pass) | The operator confirmed the host was idle; the six prepared invocations were executed with `--idle-confirmed`. All stages qualified with 3 trials per commit, 20 samples per lane and 36/36 `clear` contention probes. See `qualification.md` |
| Not claimed | Any generalisation beyond a single host, synthetic exact-term `FsDirectory` lanes and wall-clock `engine_ns` |

## D12-adjacent — runner defect found by the first measurement attempt

| Field | Value |
|---|---|
| Observation | The first `b1a` invocation aborted fail-closed with `X34_CONTENTION: trial 1 before: contention state 'unknown' (reasons ['probe_failed'])`. The frozen probe writes its JSON to `--out` and does not create parent directories, so the fresh run directory's `contention/` folder was missing |
| Classification | Fail-closed behaviour was correct; the cause was a tooling defect, classified as "stop and fix", not "treat unknown as clear" |
| Action | Fixed in `ed7bf06` by creating the probe's parent directory inside `contention_for`, with a regression test; committed **before** any timing so every run records a clean tooling SHA. No samples from the aborted attempt were used |
| Prohibited alternative (not taken) | Accepting an `unknown` probe, using `--allow-contended`, or re-running to fabricate a clean trial |

## D13 — regression/ambiguity policy (triggered by the qualified results)

| Field | Value |
|---|---|
| Observation | `b1b` and `final`: the `absent`/`rare` lanes are sign-inconsistent (paired ratios straddle 1.0); `rare` is also sign-inconsistent in `final` |
| Classification | `AUTO-RESOLVE` (D19 wording: report `INCONCLUSIVE`) |
| Action | Reported as `INCONCLUSIVE`; **no** lane is `A_FASTER`, so no accept/revert escalation was required |

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

## PR 15E Phase 4 — triggered rules

| Rule | Trigger (observed) | Class | Action |
|---|---|---|---|
| D01 | Branch = PR #83; `b7a9def` ancestor; clean tree; no prior Phase 4 code | AR | Implemented P0–P9 on the same branch; recorded SHAs |
| D03 | Compiled plan satisfies every P4-AD-01 clause, including the frozen adapter's `doc_id ASC` sort | AR | Eligibility TRUE, proven by an in-crate replica of the adapter schema/query |
| D04/D05 | Any clause false; a Term that analyzes to ≥2 terms | AR | Eligibility FALSE → byte-identical legacy scan (matrix + fallback tests) |
| D07 | Eligible query with zero postings | AR | Full effective-live charge with zero candidate visits (witness 0) |
| D09 | Work-cap accounting | AR | One bulk `charge_lexical(live_count)`; parity with the ineligible twin proven by exact/one-below search |
| D10 | Work cap one below / batch limits | AR | Existing `ResourceLimit`, unchanged |
| D11 | Frozen adapter must exercise the optimized path | AR | Proven eligible and single-candidate by the adapter-shaped in-crate test; all nine lanes therefore exercise it |
| D13 | Cancellation during counting/candidates | AR | `Cancelled` propagates; the same snapshot succeeds afterwards |
| D19 | `python -m unittest benchmarks.pr15e_b1.test_run_targeted` unsupported | AR | Used `python3 benchmarks/pr15e_b1/test_run_targeted.py`; test content unchanged |
| D20 | Architecture/roadmap "done" markers | DC | Not updated; deferred until performance acceptance |
| D25 | No fresh idle confirmation requested | AR | Used the maintainer's Phase 4 instruction as authorization for `--idle-confirmed`; recorded provenance; real before/after probes mandatory (54/54 `clear`) |
| D26/D27/D28 | Primary/control verdicts | AR | Primary `B_FASTER`, no `A_FASTER`, four INCONCLUSIVE controls disclosed → `P4_PERF_MEASURED`; stopped before Phase 5 |
| D29 | GitHub credentials invalid | DC | `CI_BLOCKED_CREDENTIALS`; local commits kept; no CI PASS claim |
| D30 | Real RustFS local substitution | AR | Podman + pinned image digest + exact CI env/commands; 26/26 PASS; disclosed |
| D32 | In-crate test placement outside the literal ledger list | DC | Disclosed as a recorded variance in `phase4-design-and-decisions.md`; test-only, no production/benchmark surface |

## PR 15E Phase 5 — triggered rules

| Rule | Trigger | Class | Action |
|---|---|---|---|
| S01 | HEAD = anchor `784c1af`; no unrelated edits | AR | Worked on PR #83; recorded ancestry |
| S03 | DOC_KEYS is one key per ascending physical doc | AR | Premise proven from the writer/decoder/accessor; proceeded |
| S05/S06/S07/S08 | Range, framing/count/limit, unselected key validity, post-selection scan | AR | Existing typed errors, validation without ownership, full scan to `expect_end` (tested) |
| S09/S29 | Full key cache already populated | AR | Clone selected key from the cache; cache untouched |
| S10 | Cold selective path | AR | Exactly one owned key, cache left empty (test-only witness) |
| S11 | Need for test-only instrumentation | AR | `#[cfg(test)]` witnesses only |
| S12/S13 | Threshold/singleton predicates per site | AR | Exact predicates; sites decided independently; multi-hit keeps the legacy path |
| S15 | Allocation-only admissibility change | AR | Declared bounds preserved; no cap changed |
| S18 | Local RustFS substitution | AR | Podman + pinned image digest + exact CI env/commands; 26/26 PASS; disclosed |
| S19 | Phase 5 timing under the maintainer's assume-idle instruction | AR | `--idle-confirmed` with recorded provenance; real probes mandatory (54/54 `clear`) |
| S22 | Primary `B_FASTER` (0.770), no `A_FASTER`, gates PASS | AR | Published `P5_PERF_MEASURED_REVIEW_PENDING`; stopped before Phase 6 |
| S25 | GitHub credentials invalid | DC | `CI_BLOCKED_CREDENTIALS`; no CI PASS claim |
| S30 | Selected-key construction failure | AR | Typed error, cache left empty |
| S31 | Docs/tooling commits after the code SHA | AR | Rust tree proven identical before treating QA as valid |

## PR 15E Phase 6 — triggered rules

| Rule | Trigger | Class | Action |
|---|---|---|---|
| D01 | HEAD exactly `e448469`; clean tree; Phase 5 tail touched no Rust/frozen/profiler path | AR | Recorded SHAs, tool hashes and prepared a fresh private run |
| D04 | Contract signatures present, behaviour unchanged | AR | Recorded verified symbols; proceeded |
| D05 | First fixed run destination free | AR | Used `target/pr15e/phase6-e448469d-01`; nothing deleted, reused or symlinked |
| D18 | Driver selected the installed versioned `perf` fallback | AR | Used it and disclosed `origin=versioned`, `fallback=true`, version 6.8.12 |
| D17 | No genuine, current operator attestation (first attempt) | DC | No timed capture; recorded the fail-closed refusal (exit 3, no capture dir) and the exact operator action required |
| D02 | After the operator supplied a host and 25-minute window, HEAD (docs tip) differed from the fixed anchor | HS | Driver refused `X24_SOURCE_CHANGED`; captures were executed with the working tree at exactly `e448469` and the branch tip restored afterwards (no Rust difference) |
| D19/D20/D22/D24 | Four valid focused captures; attribution thresholds | AR | Focused gate 4/4 PASS with the legacy verifier `PARTIAL` 4/20; `LIKELY, INCLUSIVE_ONLY` for `G05_STORED_PROJECTION` (82.39 % inclusive, largest named exclusive 10.58 %); allocation probe not triggered; implementation not authorized |
| D26 | End of authorized Phase 6 work | HS | Stopped before Phase 7; no merge |

## PR 15E Phase 6F — triggered rules

| Rule | Trigger | Class | Action |
|---|---|---|---|
| D01/D02 | Correct branch, anchor ancestor, no post-anchor protected diff, clean tree; `origin/main` differs from the plan's recorded value | AR | Proceeded on the docs tip; recorded the actual main SHA without rebasing |
| D08 | Original P6 private run and raw inputs present | AR | Validated prepare/capture/verifier/published manifests and all artifact digests |
| D14 | Hashed text reports expose named frames | AR | Extracted self and inclusive evidence; cross-checked per-sample |
| D16 | Offline re-reading yields 121,296 samples vs the recorded 121,000 | AR | Used one denominator for all shares, disclosed the `121K` display rounding, never mixed the two |
| D18/D19 | Shared `from_utf8`/`ByteReader`/`DecodeBudget`/drop frames with ambiguous text caller trees | AR | Text-tree partitions failed the arithmetic check (parent/shared overflow), so attribution was re-derived from per-sample call chains instead of heuristics |
| D22 | Nested G05 ancestry | AR | Kept the 82.39 % inclusive context separate from the disjoint exclusive buckets |
| D27 | No eligible bucket reaches 10 % with a 5 pp lead and all buckets are mandatory validation | AR | Selected `C06_NO_SAFE_LOCAL_CHANGE`; no implementation authorized |
| D30 | Legacy campaign still `PARTIAL` 4/20 | AR | Labelled P6F as an offline follow-up; no 20/20 claim |

## PR 15E closeout — triggered rules

| Rule | Trigger | Class | Action |
|---|---|---|---|
| D01/D02 | Branch at the exact P6F head, clean, ancestry verified | AR | Entered closeout audit |
| D04 | `origin/main` exactly `506beb0` | AR | Applied the six-path predicate |
| D08 | Six-path/no-conflict merge succeeded | AR | Merge `40ca10b`; proved zero protected-path delta and byte-identical docs |
| D14/D15 | `final` stage has exactly nine lanes; label is legacy | AR | Reused it unchanged; disclosed the real arm B SHA |
| D17 | No genuine current idle attestation for this campaign | DC | `PERF_BLOCKED_OPERATOR`; no `--idle-confirmed`, no timing, no cumulative JSON |
| D23/D25 | No timing data exists | DC | Performance reported as blocked, never reconstructed from other sessions |
| D28 | Stable/MSRV QA, coverage, docs, scripts PASS | AR | Recorded exact commands, counts and SHA |
| D30 | RustFS available via pinned podman image | AR | Ran the 25 exact CI invocations, itemised, disclosed runtime |
| D34 | G11 pending, no reviewer verdict | DC | G11 kept `PENDING_REVIEW`; reviewer handoff prepared |
| D38 | GitHub credentials invalid | DC | `CI_BLOCKED_CREDENTIALS`; local evidence preserved |
| D41 | Closeout commit is documentation-only | AR | Prior code QA applies to the identical Rust tree; docs checks rerun |
