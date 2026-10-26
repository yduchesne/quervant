# PR 14E — adversarial review

**Status: `EVIDENCE REVIEW — PR 14 NOT ACCEPTED`.** This file records the
falsification attempts made while reconciling the historical crosswalk, the
counterexamples that actually block a conclusion, the credibility limits of the
evidence chain, and the decisions PR 14E deliberately did **not** make. It makes
no acceptance claim.

## 1. Challenge checklist (each one exercised, not assumed)

| # | Challenge | How it could falsify | Observed / disposition |
|---:|---|---|---|
| 1 | Row count is wrong | Re-extraction shows ≠127 rows or ≠96/11/2/18/0 | 127 rows reproduced; naive parse gives 95/19 because one `§6` row has a composite cell `PASS (…remain BLOCKED)`. Counted by its leading token → 96/18. Documented in the crosswalk §1 so the discrepancy is reproducible, not hidden |
| 2 | A range was expanded into invented rows | `U01–U06` etc. counted as six rows | Every grouped row is one historical row; no ID inside a group got its own row (decision X05) |
| 3 | Reused ID prefixes were joined by number | `I07`/`I13`/`I8`/`P01–P05`/`G01–G05`/`R01–R07`/`B01–B04`/`Q01–Q09` mean different things per generation | Composite keys `PR14C:<section>:<literal>`; repeated literals kept in separate rows (CW-012 vs CW-055/CW-068; CW-018 vs CW-058/CW-073; CW-039 vs CW-078; CW-040 vs CW-095…104; CW-031 vs CW-114…117; CW-042…049 vs CW-075…080) |
| 4 | Zero-GET was inferred from "the query worked" | Reading success as "no remote read" | Rejected. Success is not a counter assertion; the three zero-GET rows stay `BLOCKED` (D-01/D-05/D-08) |
| 5 | The existing zero-GET assertion is a false positive | A reset placed *before* open would count open GETs as query GETs; a reset placed after a warm cache proves nothing about a cold path | `pr13_remote::v01` resets after the workspace/snapshot is open and then runs lexical queries only ⇒ it is a valid assertion **for the lexical path**, and it is not transferable to typed/mixed/batch/pinned. The proposed follow-up (D-01 step 4) additionally demands a positive control that the cold window *does* increment the counter |
| 6 | Zero-GET could pass because the counter is broken | A counter that never increments trivially satisfies "unchanged" | Noted as a required positive control in D-01; no such assertion exists for PR 14 paths today, which is part of why the rows stay blocked |
| 7 | Physical hit identity was inferred from matching output | `p02_projection_uses_current_version` passes even for a key-based rescan against the same snapshot | Therefore CW-055/CW-068 remain `BLOCKED`; only a direct physical-identity assertion would close them (D-04/D-07) |
| 8 | The key/identity guard in `project_selected_hits` is treated as proof | The guard is a defensive invariant (`doc_key(doc_id) != key` → `CorruptIndex`) that cannot fire for a consistent snapshot | Treating it as a test would be inference from code presence (EAD-06); it is cited as *implementation* evidence only |
| 9 | Upsert could leave two live physical docs with the same key, so identity matters | Upsert tombstones the prior physical document; only one live physical doc per key exists in a snapshot | Confirmed; this is exactly why the missing assertion must bind the **selected** `(segment_index, doc_id)`, not compare output values. Recorded in D-07 |
| 10 | "Legacy JSON" evidence is fake legacy | A synthesised segment is not a historical artifact | Both are used and labelled: `J14` uses a section-stripped container built with production builders (fallback + typed fail-closed asserted); `J15` uses the genuine frozen PR 11 artifact `65f7440` with byte-identical reproduction and typed corruption/version rejection. `J14`'s end-to-end limitation is written down, not glossed over |
| 11 | The legacy fixture was silently regenerated | Digest differs from the historical record | Digest `0528a62c…a02f` re-asserted by two independent tests (`b18_b19`, `d07`); corruption must fail at open |
| 12 | B20/B21 numbers were quoted as RSS or a cap | Treating allocator-window peaks as memory limits | Rejected everywhere; `resource-risk-reconciliation.md` states the limits verbatim and never uses "RSS-bounded", "cap" or "resolved" |
| 13 | Post-fix B20/B21 numbers were invented | Thresholds differ from what the test prints | Re-executed `pr14b_json_memory` at current head; the printed thresholds are compared to 387 / 45,726 / 1,462,302 B in `validation-report.md` |
| 14 | PR 14D provider evidence went stale | Code changed after the provider run | `git diff --stat 3f82284..dc506f6 -- crates/ Cargo.toml Cargo.lock benchmarks/ .github/` is empty; only docs changed. `REUSE-14D` rows are therefore code-current but **not** re-executed, and are labelled as such |
| 15 | A newer CI run was retroactively attributed to an old SHA | Claiming `e0e1dcb` or `ab9b2d7` was green | API shows `total_count: 0` for both. They are explicitly excluded in D-06/D-15; the PASS claims name the exact green SHAs only |
| 16 | "CI verified" hides which CI | Collapsing historical #64 CI, `main` CI and PR 14E CI into one flag | Three separate states: historical PR-line CI **verified**; `main` CI **verified**; PR 14E head CI **pending** (`final-acceptance.md` flags table) |
| 17 | Historical benchmark numbers are presented as current | Freshness implied by context | `ab9b2d7` is 138+ commits behind and labelled provenance only in the crosswalk, dossiers and benchmark ledger; no lane value is restated as a PR 14E measurement |
| 18 | W08 is smuggled in as measured | A "measured" label or a PASS without the waiver | W08 stays `NOT APPLICABLE (APPROVED)` (CW-119, CW-125); the validator requires the exemption manifest and PR 14E re-ran its self-test |
| 19 | `X01–X13` were reconstructed from related families | Inventing definitions from `pr-14/test-traceability.md`'s one-line family description or from the contradictory corrective reuse | Not done. Searched `docs/`, three commits (`fa82db7`, `d0c445a`, `e0e1dcb`) and the whole history; no definition table. Row stays `BLOCKED` with three explicit maintainer options (D-16) |
| 20 | Ignored provider tests were counted as executed | Default `cargo test` does not run `#[ignore]` cases | Only `RUN-14E` local suites are claimed as executed; provider rows are `REUSE-14D`; the ignored counts are reported per run in `validation-report.md` |
| 21 | Coverage was copied from the historical run | Reusing 91.29 % | Coverage was re-measured in this run (value in `validation-report.md`), not copied |
| 22 | Historical files were rewritten to make the past look better | Edits inside PR 14C/14D conclusions | Only two **dated additive** successor notes were added to PR 14C documents; PR 14D evidence was not edited; `docs/ROADMAP_V01.md` is unchanged |
| 23 | Scope crept into production/test code | Any `crates/**` diff | `git diff --stat` for this branch touches only `docs/pr-artifacts/pr-14e/*` plus the two additive notes; verified before commit and re-verified in `final-acceptance.md` |
| 24 | The Q-family CI PASS over-claims per-ID checks | Implying Q01…Q09 were individually verified | Explicitly family-level only; per-ID definitions are absent from the repository and the limitation is recorded (D-15) |
| 25 | The corrective `I16` CI PASS over-claims | Implying CI ran on `e0e1dcb` | Scope statement in D-06: PASS is bound to the merged/reviewed heads; never-pushed local commits are excluded |
| 26 | The risk was closed by an agent | Treating "correction merged" as "risk accepted" | CW-127 stays `BLOCKED`; closure requires a named human decision (D-18) |
| 27 | PR 14 status was accidentally advanced | Any text implying DONE/accepted/released | Contradiction scan below; all documents state `NOT ACCEPTED` |
| 28 | A test failure was hidden or a test edited to pass | No source/test edits at all; all failures would be reported | No failures occurred in the executed matrix; nothing was skipped, ignored, retried to green or edited |

## 2. Contradiction scan

Searched all new PR 14E files (and the two successor notes) for claims that
would contradict the status:

| Forbidden claim | Occurrences |
|---|---|
| PR 14 DONE / ACCEPTED / COMPLETE | 0 |
| v0.1 released / PR 15 unblocked | 0 |
| benchmark qualified / measured lanes PASS | 0 |
| W08 measured | 0 |
| zero-GET proven for PR 14 query paths | 0 |
| physical hit identity proven | 0 |
| `X` IDs mapped | 0 |
| RSS / physical memory cap | 0 |

## 3. Credibility limits of this evidence chain

| Limit | Impact |
|---|---|
| PR 14E ran **no** real provider | Provider rows rest on PR 14D's immutable record, not on a fresh run; the no-code-drift check is the only bridge, and it is stated |
| `REUSE-14D` evidence is recorded in PR 14D prose, not as machine-verifiable artifacts in this PR | A reviewer must trust the merged PR 14D record for per-case PASS; PR 14E independently verified its CI SHA, ancestry, and the absence of code drift |
| `J14` is unit-level | The stored-source fallback is asserted through the production accessor, not through `UnifiedSearcher` on a legacy segment |
| `J15` is JSON wire v1 only | No older supported wire version exists to migrate; nothing is claimed about a hypothetical v0 elsewhere |
| B20/B21 is one host/profile | Absolute bytes are indicative; only the threshold-growth and typed-rejection relations are material |
| CI is read-only through the public API | Job logs were not downloaded; conclusions rest on `status`/`conclusion` per check run |
| PR 14E head CI | Not observable until the branch is pushed and checks complete; recorded as pending |

## 4. Unresolved decisions (explicitly not made by the agent)

| ID | Decision needed | Owner |
|---|---|---|
| UD-1 | Recover or formally retire `X01–X13` per-ID definitions (three options in D-16) | maintainer |
| UD-2 | Approve a test-only change that proves zero query-time remote GET on the PR 14 query paths (D-01) | maintainer / separate fixup PR |
| UD-3 | Approve a test-only change that proves exact physical hit identity, or approve a public `HitRef` contract (D-04/D-07) | maintainer / separate design review |
| UD-4 | Record risk closure for `R-14A-JSON-MEM` with the preserved allocator-window limitation (D-18) | maintainer |
| UD-5 | Whether the family-level `Q` CI PASS is acceptable without per-ID definitions (D-15) | maintainer |
| UD-6 | Run the three qualified P4 trials (PR 14F) | operator + maintainer |
| UD-7 | Independent review and acceptance of PR 14E and then PR 14 | reviewer / maintainer |

## 5. Reviewer prompts (suggested falsification)

1. Re-parse the 127 rows independently and confirm the `§6` composite-cell rule
   is the *only* reason a naive count reports 95/19.
2. Open the CI URLs and confirm `rust`/`msrv`/`rustfs` conclusions for
   `a61f0b8`, `635c7f4`, `dc506f6` — and confirm `e0e1dcb`/`ab9b2d7` have no
   runs at all.
3. Read `legacy_json_tests` and decide whether the section-stripped container
   plus production accessor meets the historical `J14` bar, or whether a
   pre-PR-11 artifact is required.
4. Read `project_selected_hits` and decide whether implementation-level physical
   identity is sufficient without an assertion (PR 14E says it is not).
5. Confirm `git diff --stat 3f82284..dc506f6 -- crates/ Cargo.toml Cargo.lock
   benchmarks/ .github/` is empty before accepting `REUSE-14D`.
6. Confirm no new file claims PR 14 acceptance, benchmark qualification, W08
   measurement, RSS bounding or release.

No acceptance is claimed by this review.
