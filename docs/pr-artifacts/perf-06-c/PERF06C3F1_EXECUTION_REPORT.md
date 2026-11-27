# PERF-06-C3-F1 execution report — acceptance repair and evidence closeout

**Status:** acceptance repair complete; local gates executed on one immutable
`F1_TESTED`. **No production change, no performance measurement, no benchmark,
no profiler, no C4 work, no merge, no baseline promotion.** G10 remains
maintainer-owned and open. The original C3 plan, report and the entire
`evidence/c3/**` directory are frozen; corrections are dated errata.

## 1. Identities and hashes

| Fact | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| PR | [#132](https://github.com/yduchesne/quervant/pull/132), `OPEN`, observed `isDraft=true`, `mergedAt=null` |
| Branch | `dev/perf06-c3` |
| `B` (main) | `6bc977e6a26c183609b7ca53eca51d3ab09ce337` |
| `START` | `ee77917d303b060b0d38ab88e5d9ae73625f6676` |
| `START` tree | `38b892beffb81dccbc651b5923bf1fa311fdb454` |
| Original `RED` | `0c295d1390869826c581a6c589d299cd13c4c99f` |
| Original `TESTED` | `6ea6b7ce049d613a29864f1eae53dea5fd61e75f` |
| `F1_TESTED` | `8f82f8290f838547dfc7d490f44ba8c0c8798d24` |
| `F1_TESTED` tree | `d22e2da175cb627a5e81b88905290d2a13958c11` |
| `F1_DOCS_FINAL` / `F1_REMOTE_H` | recorded in the terminal handoff; no file in the repository claims its own enclosing commit |
| Original plan SHA-256 | `69b1aeba951d13361936ef8ffed75f77ec88362d3c7a38727b4eedd684f9a755` |
| F1 plan SHA-256 | `78a67331a496791c223ceb642180f9b7dd30da21530e231bc03bb01eb5d9408f` |
| Original recorder SHA-256 | `5bbb38e1b4b7538c56e80eacf1f694de19ccbd49528333f95553fde4bf80418d` |
| Freeze checker SHA-256 | `85012631836e96d62181f5ade033f59e4eaff2a8bf8256634b41ab5f67ca225b` |
| Receipt verifier SHA-256 | `f83e1ecc8e6c38cb86498e81e524d9a2ca1aab3cfa63fe8a425b507ba816a8e7` |
| Contract builder SHA-256 | `62af39cca1c0dba47ac0c58ab580cdfe8473cdeeaac05ca93b44abdf9922d2ad` |
| Command contract SHA-256 | `1107c78e330559d8631882fc815a2d78dd0cc901e8517fcb32487c4663e545c4` |
| Verification SHA-256 | `8cdb7f8b6d18ed1f9c9ac39d6a22774a42cef7cf03edecc2a9ab0abc5bce93c2` |
| Baseline verification SHA-256 | `3236369ab9c57847ae6d17715f54a98dfc3b06bb335105dca98cedaab785f5db` |
| Receipts | 6 baseline + 45 final = 51, all verified `PASS` |

Toolchains: `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1`,
`rustc 1.85.0 (4d91de4e4 2025-02-17)`, `cargo 1.85.0`, Python 3.12.3,
host `x86_64-unknown-linux-gnu`.


## 2. Review findings and their dispositions

| ID | Disposition | Source change | Acceptance evidence |
| --- | --- | --- | --- |
| F1-01 | **FIXED** — S01 df rows now retain the valid base prepared IDF and assert its presence, bounds and exact bits before requiring refusal; S01-06 keeps the missing-IDF case separate with its eager precedence checks. | `score.rs::c3_s01_certificate_matrix` only | `f1_fin_s01` → `C3 F1 S01 rows=24 isolated-df-rows=2` |
| F1-02 | **FIXED** — U02 now executes the literal 25 ordered tuples `M ∈ {0,1,K,K+1,K+2}`, validates the tuple list, captures every normal-run witness before references, asserts the split certified/eager/Legacy counts from captured values, and asserts the six previously discarded ineligible-result responses in full. | `unified.rs::c3_u02_dispatch_and_count_matrix` only | `f1_fin_u02` → `C3 F1 U02 matrix-rows=25 certified=5 legacy=20 split-c3=10 ineligible-result-rows=6` |
| F1-03 | **FIXED** — U04 validates the nine literal fault descriptors before execution, makes `C29` a column-only mutation, and adds the same-snapshot unarmed certified C3 check for the injected+corrupt-key descriptor. | `unified.rs::c3_u04_corruption_precedence` only | `f1_fin_u04` → `C3 F1 U04 rows=9 isolated-C29=true unarmed-synthetic-snapshot=C3` |
| F1-04 | **FIXED** — U09 asserts the twelve literal resource outcomes (no outcome-dependent expectation), guards the `FieldValues`/projected-charge geometry, runs seven same-snapshot recoveries against an independently executed generous control, and binds normal/eager/Legacy errors to the same literal tuple. U05 also binds its three failing caps' normal/eager/Legacy errors literally. | `unified.rs::c3_u09_logical_budget_edges`, `c3_u05_native_later_segment_boundary` | `f1_fin_u09` → `C3 F1 U09 rows=12 failed-rows=7 recoveries=7 fixed-projection-failure=13056/13160/100`; `f1_fin_u05` → `C3 F1 U05 rows=4 recoveries=4 literal-reference-errors=3` |
| F1-05 | **FIXED** — I02 now verifies every paged hit of all five view phases against the immutable input index, complete projection and scalar bits, and adds the previously missing old-view wrapper Legacy comparison. | `perf06_c2_physical.rs::collect_pages` and `c3_i02_real_pit_update_merge_and_paging` only | `f1_fin_i02` → `C3 F1 I02 phases=5 checked-hits=198 old-pages=14 new-pages=13` |
| F1-06 | **FIXED (reporting)** — dated errata correct the region-vs-line coverage label, the U02 split diagnostic, the C29 descriptor, the I02 later-page scope, the S01 guard independence, the U09 expectation, the U04 execution classes, the parent/child test-count scopes and the `c3_` 26-vs-17 inventory. | Documentation only (append-only) | §7 and the appended errata in the original report |
| F1-07 | **CLOSED** — the earlier pending observation is preserved; the original run is recorded as completed with its merge checkout distinguished from the PR head, and the F1 head observes its own ordinary CI. | Documentation and evidence only | §8 |

## 3. Worksheet answers (G1)

1. **Which earlier predicate masks S01's df rows?** `FieldStats::certify_deferred`
   requires `let idf = stat.idf?;` **before** it evaluates `df == 0` /
   `df > n`. The old rows passed `idf = None`, so the absent-IDF `?` refused them
   regardless of the df guard. The IDF must be the *valid base* value rather than
   recomputed from the invalid df because `prepare_idf(0, 30)` and
   `prepare_idf(31, 30)` both return `None` (df == 0 or df > n), which would
   re-introduce exactly the masking condition. The base `prepare_idf(30, 30)` is
   the value a coherent snapshot would hold for the same n.
2. **The 25 U02 tuples** are `K ∈ {1,10,31,32,100}` × row index `0..4` with
   `M = [0, 1, K, K+1, K+2]`. The five eligible rows are the index-4 rows
   (`M = K+2`) because the certificate additionally requires `df > K+1`. At
   `K = 1` both index 1 and index 2 give `M = 1`; they are two distinct inputs
   with the same value and must both execute.
3. **Which reset contaminates the split diagnostic?** The old code printed
   `crate::search::score::c3_score_observation::calls()` *after* running the
   eager and Legacy references, so the printed `12` belonged to the Legacy run
   while the certified assertion correctly read `10`. The certified, eager and
   Legacy counts must each be captured into locals immediately after their own
   run and printed from those saved values.
4. **The nine U04 descriptors** (ID, doc-key record, final posting, sort column,
   injected score) are `D0(Some(0),false,None,None)`, `D29(Some(29),false,None,None)`,
   `D31(Some(31),false,None,None)`, `P29(None,true,None,None)`,
   `P29+D0(Some(0),true,None,None)`, `C0(None,false,Some(0),None)`,
   `C29(None,false,Some(29),None)`, `C29+P29+D0(Some(0),true,Some(29),None)`,
   `S29+D0(Some(0),false,None,Some(29))`. The three `C*` rows fail **before**
   route dispatch (eager column validation), so they are pre-route cases;
   `S29+D0` is the only `INJECTED_C2_ONLY` row; the remaining eight are real
   byte-only corruption.
5. **U09 collection → finalization → projection.** `collect_mixed` runs the
   strict collector (leaf `16m` bytes, matched admission `48m` bytes/`m` entries,
   scored admission `64m` bytes/`m` entries → peak `3m` entries and `128m` bytes),
   releases the segment reservations, then `finalize_deferred_entries` scores the
   first `K`. Only afterwards does `project_selected_hits` charge the projection
   ledger. For the `doc_id`-only projection each hit costs
   `24 + 9 = 33` for key plus `32 + 6 + 32 + 24 + (9 + 4) = 107` for the field,
   i.e. **140 bytes**. After 93 projections the ledger has used `93 × 140 =
   13020`; the 94th needs `13020 + 140 = 13160`, exceeding the `13056` cap by
   exactly `104`. The `104` is the excess over the cap, **not** a new charge.
6. **I02 new statistics.** Deleting index 2 removes `dl(2) = 1+2+2 = 5`;
   rewriting index 6 from `1+2+1 = 4` to the single token `gamma` removes `3` and
   adds `1`; inserting index 40 adds `dl(40) = 1`. New total length
   `180 − 5 − 4 + 1 + 1 = 173`; live `n = 40` (39 original + 1 insert);
   alpha `df = 39` (indices 0..=40 except 2 and 6). The updated document is not a
   match but still contributes its one length unit.
7. **Why input-derived indices?** Parsing the returned key would make the test
   agree with whatever the engine returned, including a wrong-but-well-formed
   page, and would not prove the page boundary. The expected index comes from the
   immutable input sequence, so identity, projection and score all reference
   independent data.
8. **Coverage/26-vs-17/merge-SHA.** The historical percentages were read from the
   region column; the `Lines` columns give `93.50 %` and `93.09 %`. The broad
   `--lib c3_` filter selects 26 tests because the base tree already contained 9
   unrelated `c3_*` accounting tests; 17 are the new PERF-06-C3 registrations.
   GitHub's `pull_request` runs check out a synthetic merge commit, so the
   workflow metadata names the PR head while the job checkout names the merge
   SHA.

## 4. Invariant → test mapping

| Invariant | Evidence |
| --- | --- |
| F-I01 production freeze | `audits/worktree-freeze.json`, `audits/tested-freeze.json` (`normal_build_source_equal=true`, `unapproved_test_bytes_equal=true`), plus the unchanged original `source_audit.py` (36 PASS / 0 FAIL / 1 INFO) |
| F-I02 independent S01 guards | `f1_fin_s01` |
| F-I03 exact U02 domain | `f1_fin_u02` (literal 25-tuple comparison, 5 certified / 20 Legacy) |
| F-I04 same-operation observation | U02/U05/U09 captured witnesses before references |
| F-I05 fault exclusivity | `f1_fin_u04` descriptor table + `isolated-C29=true` |
| F-I06 literal failure oracle | `f1_fin_u04`, `f1_fin_u05`, `f1_fin_u09` (`assert_literal_limit`, per-route) |
| F-I07 failure phase and atomicity | `f1_fin_u09` `fixed-projection-failure=13056/13160/100`, seven recoveries |
| F-I08 every-hit snapshot oracle | `f1_fin_i02` 5 phases / 198 checks / 14+13 pages |
| F-I09 evidence identity | 51 verified receipts, tree linkage against `START`/`F1_TESTED` trees |
| F-I10 accurate status | §7 (Lines coverage, scoped counts) and §8 (CI) |

## 5. Exact changed-function audit

`freeze_f1.py` masks exactly the seven authorized regions and byte-compares
everything else. Result at `WORKTREE` and at `F1_TESTED`: **PASS**.

| File | Authorized functions | Changed |
| --- | --- | --- |
| `crates/quervant-core/src/search/score.rs` | `c3_s01_certificate_matrix` | yes |
| `crates/quervant-core/src/search/unified.rs` | `c3_u02_dispatch_and_count_matrix`, `c3_u04_corruption_precedence`, `c3_u05_native_later_segment_boundary`, `c3_u09_logical_budget_edges` | yes |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | `collect_pages`, `c3_i02_real_pit_update_merge_and_paging` | yes |

`crates/quervant-core/src/search/execute.rs` and every other executable file are
byte-identical to `START`. No test was added, removed, renamed, ignored or
filtered. Only mechanical clippy repairs were needed (local `type` aliases inside
the two authorized functions, no lint suppression).

## 6. Repaired case outcomes (actual emitted markers)

```
f1_fin_s01: C3 F1 S01 rows=24 isolated-df-rows=2
f1_fin_u02: C3 F1 U02 matrix-rows=25 certified=5 legacy=20 split-c3=10 ineligible-result-rows=6
f1_fin_u04: C3 F1 U04 rows=9 isolated-C29=true unarmed-synthetic-snapshot=C3
f1_fin_u05: C3 F1 U05 rows=4 recoveries=4 literal-reference-errors=3
f1_fin_u09: C3 F1 U09 rows=12 failed-rows=7 recoveries=7 fixed-projection-failure=13056/13160/100
f1_fin_i02: C3 F1 I02 phases=5 checked-hits=198 old-pages=14 new-pages=13
```

Row-level detail (U02 25 tuples, U04 nine descriptors, U09 twelve outcomes, I02
five phases) is in `evidence/c3-f1/summaries/case-output.txt` and in each
receipt's Base64 output.

Selected concrete observations:

- U02: certified rows print `scores=K`; Legacy rows print `scores=M`; the split
  line prints `c3_calls=10 eager_calls=12 legacy_calls=12`.
- U04: `C29 descriptor=(doc_key=None,posting=false,sort_column=Some(29),injected=None)`;
  `S29+D0 unarmed-synthetic-snapshot=C3 route=(1, 0, 1, 1, 0) membership=30 numeric=1 bm25=0`.
- U09: `U09-102-X ... outcome=Limit(13056, 13160) membership=102 numeric=102 callbacks=102 scores=100 identities=100`;
  one-under rows show `callbacks=0 scores=0`.
- I02: `I02-OLD-BEFORE df=40 n=40 total_length=180 pages=14 checked_hits=40`;
  `I02-NEW df=39 n=40 total_length=173 pages=13 checked_hits=39`;
  `I02-OLD-AFTER-COMPACTION` repeats the old statistics.

## 7. Inventories, regressions and measured gates

| Selection | Count | Names |
| --- | ---: | --- |
| `--lib search::unified::c2_tests::c2_u` | 24 | identical to `START` |
| `--lib search::execute::c2_physical_tests::c2_p` | 5 | identical to `START` |
| `--lib c2_` | 52 | identical to `START` |
| `--lib c3_` | 26 | 9 pre-existing accounting + 17 PERF-06-C3, identical to `START` |
| `--test perf06_c2_physical` | 12 | identical to `START` |

All eighteen suite commands executed with their required toolchain/thread
settings (C3 26/0/0 serial, 8-thread and MSRV+all-features; C2 24/0/0 and 5/0/0
serial and 8-thread; integration 12/0/0; score 19/0/0; reader 9/0/0; `b1_` 65/0/0;
`b2_` 31/0/0; `b3_` 32/0/0; `perf06_b1_ordinals` 9/0/2 ignored;
`perf06_b2_ordinals` 8/0/0; `perf06_b3_keys` 8/0/0; `pr15h_a` 6/0/0;
`pr15h_a2` 8/0/0).

Sixteen repository QA commands on `F1_TESTED`:

| Gate | Result |
| --- | --- |
| `cargo +1.98.1 fmt --all -- --check` | PASS (exit 0, empty output) |
| `cargo +1.85.0 fmt --all -- --check` | PASS (empty) |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.98.1 clippy ... --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy ... --all-features -- -D warnings` | PASS |
| `cargo +1.98.1 test --workspace --all-targets` | PASS |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS |
| `cargo +1.98.1 llvm-cov ... --all-features --fail-under-lines 85` | PASS |
| `cargo +1.98.1 doc --workspace --no-deps` | PASS |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS |
| `cargo +1.98.1 bench --workspace --no-run` | PASS (compile only) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108 script tests) |

### Measured line coverage (F1, from the `Lines` column)

| Receipt | Total | Missed | Covered | Percent |
| --- | ---: | ---: | ---: | ---: |
| `f1_qa_cov_198` | 77689 | 5026 | 72663 | 93.53% |
| `f1_qa_cov_198_af` | 79199 | 5442 | 73757 | 93.13% |

Regions, functions and branches are separate columns in the receipts and are not
conflated with line coverage.

### Workspace test scopes

`--all-targets` launches 146 Cargo targets: 136 parent libtest targets plus 10
Criterion test-mode targets (bench smoke, not measurements). Parent totals are
`2749 passed / 0 failed / 16 ignored` (default) and `2794 / 0 / 100` (all
features) on both toolchains. Child-process summaries are recorded separately
(10 observed in three receipts, 9 observed with `child_output_ambiguous=true` in
`f1_qa_test_198_af`); they are **not** unique parent tests. No doctest target
appeared in these `--all-targets` commands, so no doctest claim is made.

## 8. Hosted CI

- **Original run, now closed:** 45925006538 (`pull_request`, attempt 1, head
  `START`) completed `success`; all five jobs succeeded. Its `rustfs` job
  (140264172087) log contains 32 `test result: ok` summaries summing to
  **65 passed / 0 failed / 0 ignored** across repeated invocations, 37 unique
  named real-service tests and 53 top-level `test … ok` lines; the workflow
  metadata identifies the PR head, the checkout the merge commit
  `592241ec0ad408f30cbe1a0ab6cc0b7968aa56b6`. Metadata is preserved in
  `evidence/c3-f1/ci/`.
- **F1 head:** not yet observed at the time this report was committed. This is a
  deliberate layered evidence boundary: the final-head CI run, remote/PR identity
  and committed-range whitespace receipts are delivered in the external terminal
  package and the live PR description, rather than in a commit that would itself
  create a new head needing another run.

## 9. Applied decisions, failures and residual limits

- Applied rules: D01 (admission matched the pins), D03 (the pre-existing
  `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` was left untouched and
  its hash unchanged), D05 (draft flag observed and preserved), D08 (mechanical
  local `type` aliases and comment restoration only, no suppression, new
  `F1_TESTED` and full final rerun), D09/D10/D13/D15/D17/D18/D22/D24/D26/D27.
- No required gate failed. The only intermediate failure was the freeze checker
  flagging my own change to the `collect_pages` **doc comment** (outside the
  authorized function region); it was reverted to the exact `START` text and the
  new prose moved inside the body, then the audit passed. Both audits (`FAIL`
  then `PASS`) are retained in the external diagnostics directory.
- Residual limits: the certificate is sufficient rather than necessary; TLS
  observations do not aggregate other threads; U13 is structural; `S29+D0` is
  injected; the three U04 column rows fail before route dispatch; the U09
  `{13056,13160}` tuple is tied to the verified 64-bit `FieldValues == 32`
  geometry and is not an ABI-independent claim; C4 owns performance and
  layout/codegen qualification.

---

# F2 independent-review erratum (2026-11-27 UTC)

F1's assertion of no lint suppression was incorrect. The nested `recover_at`
helper in `c3_u09_logical_budget_edges` introduced
`#[allow(clippy::too_many_arguments)]`, contrary to F1 D08; the recorded F1
Clippy commands did pass with that attribute present, so those green runs never
demonstrated its absence. U02's plain-batch row also lacked a literal assertion
that the response aggregation was `None`; its complete forced-Legacy parity was
present but did not independently establish absence.

F2 removes the nested suppression and helper and inlines its unchanged recovery
operations, asserts `is_none()` for both the normal and forced-Legacy plain-batch
responses, and corrects the nearby average-length comment (`n = df = 24`,
`avgdl = 1`). All other test and production bytes are frozen: `F2_TESTED`
`e4816c51f0063383596e8ee8a644b38d7a39a400` is a direct child of
`051104724125ba95d49a6d94b61500f974a3599f` and changes only
`crates/quervant-core/src/search/unified.rs` inside those two test bodies. The F1
historical receipts are unchanged and were re-verified read-only (51 rows,
`PASS`, identical JSON, tree linkage confirmed).

The current acceptance record is
[PERF06C3F2_EXECUTION_REPORT.md](PERF06C3F2_EXECUTION_REPORT.md).

F1 external artifact delivery: The historical archive was recovered and fully validated (archive SHA-256, Markdown SHA-256, archive integrity, 23 payload members plus manifest, every member digest and the embedded Markdown all verified, with the START/F1_TESTED identities present) and is delivered unchanged with this handoff.

C4 performance work and G10 maintainer acceptance remain outside executor
acceptance.
