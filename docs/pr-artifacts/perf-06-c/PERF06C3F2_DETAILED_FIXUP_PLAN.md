# PERF-06-C3-F2 — Final test-only conformance and evidence delivery

**Repository:** `yduchesne/quervant`
**Branch:** `dev/perf06-c3`
**Existing PR:** [#132](https://github.com/yduchesne/quervant/pull/132)
**Plan date:** 2026-11-27 UTC
**Scope:** two existing test bodies and bounded acceptance evidence. No production changes, no new tests, no benchmarks, no C4 work.

## 0. Execution authority and pinned state

This is a continuation of C3-F1, not a fresh implementation of C3. The original C3 plan and F1 plan remain immutable historical contracts except for the explicitly stated F2 closeout/delivery decisions in this document. This document supplies the complete remaining design. The coding agent must execute it, not redesign it.

Once authorized, execute all prescribed stages and routine checkpoints continuously. Passing a checkpoint or encountering a listed AUTO-RESOLVE condition does not require additional approval. For DEFER AND CONTINUE, record the dependent gate as blocked and complete independent safe work. For HARD STOP, stop the affected work, preserve evidence and identify the exact smallest human decision needed. An unlisted condition is a HARD STOP; do not infer permission to improvise. No authority to merge, approve residual risk, waive a mandatory check, change readiness, create another PR or start C4 is granted.

### 0.1 Immutable identities

| Name | Full SHA / identity |
| --- | --- |
| B, current main (merged C2) | `6bc977e6a26c183609b7ca53eca51d3ab09ce337` |
| Original C3 RED | `0c295d1390869826c581a6c589d299cd13c4c99f` |
| Original C3 TESTED | `6ea6b7ce049d613a29864f1eae53dea5fd61e75f` |
| F1_START | `ee77917d303b060b0d38ab88e5d9ae73625f6676` |
| F1_TESTED | `8f82f8290f838547dfc7d490f44ba8c0c8798d24` |
| F1_TESTED tree | `d22e2da175cb627a5e81b88905290d2a13958c11` |
| START (F1_DOCS_FINAL and reviewed remote H) | `051104724125ba95d49a6d94b61500f974a3599f` |
| F1 hosted CI | `45941531494`, attempt 1, pull_request, success |
| F1 CI merge checkout | `45daca24bdd41ecec9d2bcc7e8edd2107380d658` |
| F1 RustFS job | `140316720459` |
| PR state when reviewed | open, draft=true, unmerged, base=main, head=dev/perf06-c3 |

Fresh main and PR metadata were read during F2 authoring. The F1_TESTED..START comparison contains only docs/evidence. START is the latest reviewed head. Stop if either branch advances or any pin changes; do not rebase, reset, cherry-pick, force-push or adapt the plan to a different base. A readiness-only change is covered by D04.

Reviewed source blobs at START:

| Path | Git blob |
| --- | --- |
| `crates/quervant-core/src/search/unified.rs` | `eb1d1f31d7554bb99d030858e99b3d3d2946c2f7` |
| `crates/quervant-core/src/search/score.rs` | `7c181a556dca5f69614c739a466478a7bee0b7da` |
| `crates/quervant-core/src/search/execute.rs` | `dbc863219716475db21cbb9739bf52557c2e61c3` |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | `76dc464a519dd5faf34653ab374a3033ffc43a0c` |

Read `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/TESTING.md`, `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md`, the original C3 plan, F1 plan and F1 report at START before edits. The repository quality gates take precedence over any illustrative command. All work is correctness-only: the warm performance qualification remains owned by C4. No host readiness campaign is needed for F2.

### 0.2 Frozen plans and reusable helpers

Set `D=docs/pr-artifacts/perf-06-c`, `E1=$D/evidence/c3-f1`, `E2=$D/evidence/c3-f2`, `B=6bc977e6a26c183609b7ca53eca51d3ab09ce337`, `F1_START=ee77917d303b060b0d38ab88e5d9ae73625f6676`, and `START=051104724125ba95d49a6d94b61500f974a3599f` as Bash variables before running the supplied commands. The following are the existing, reviewed files at START; hash bytes, not normalized text:

| Path (relative to repository) | SHA-256 |
| --- | --- |
| `$D/PERF06C3_DETAILED_IMPLEMENTATION_PLAN.md` | `69b1aeba951d13361936ef8ffed75f77ec88362d3c7a38727b4eedd684f9a755` |
| `$D/PERF06C3F1_DETAILED_FIXUP_PLAN.md` | `78a67331a496791c223ceb642180f9b7dd30da21530e231bc03bb01eb5d9408f` |
| `$E1/scripts/record.py` | `5bbb38e1b4b7538c56e80eacf1f694de19ccbd49528333f95553fde4bf80418d` |
| `$E1/scripts/verify_f1_receipts.py` | `f83e1ecc8e6c38cb86498e81e524d9a2ca1aab3cfa63fe8a425b507ba816a8e7` |
| `$E1/scripts/run_contract.py` | `42ba6fa6a9eacc1f698dfe7c0076228071b41fccb720b0daeb5b372ff0583c07` |
| `$E1/contracts/command-contract.json` | `1107c78e330559d8631882fc815a2d78dd0cc901e8517fcb32487c4663e545c4` |
| `$E1/verification.json` | `8cdb7f8b6d18ed1f9c9ac39d6a22774a42cef7cf03edecc2a9ab0abc5bce93c2` |
| `$E1/contracts/baseline-contract.json` | `f2da2e3bba4c188052fd48d42a46f0ce9392b58f9976189159baead2d664f05c` |

The original C3 evidence and all F1 evidence are immutable; do not edit them. Use the existing recorder and verifier byte-for-byte. The F1 freeze checker is designed for F1's documentation allowlist and is not a valid F2 checker when pointed at new F2 documentation. The F2 checker in Appendix A verifies the exact new two-test delta instead, which composes with the independently reviewed F1 freeze. Do not change F1's checker to accept F2.

## 1. Review disposition and bounded remaining delta

F1 executed its substantive repairs. Independent review of START compared all bytes outside seven authorized regions with F1_START; they match. All six focused receipts were inspected, including actual command names, single-test summaries, tested commit/tree, and case markers. The live PR metadata and five job results were read, and the real RustFS log established 32 successful result summaries with 65 passes, zero failed, zero ignored across invocations. No concrete production implementation defect was found. The reviewer did not locally compile Rust or rerun the tests.

| ID | Exact remaining finding | Required correction |
| --- | --- | --- |
| F2-01 | `c3_u09_logical_budget_edges` contains a newly added `#[allow(clippy::too_many_arguments)]` on the nested `recover_at` helper. F1 D08 explicitly forbids any new lint suppression. The report says there was no suppression. | Remove the nested helper and inline its complete recovery logic at its sole call site. Correct the historical report by append-only erratum. |
| F2-02 | `c3_u02_dispatch_and_count_matrix` compares the plain batch response to a forced Legacy response but omits the literal `aggregation.is_none()` requirement in F1 §5.3. Both routes could incorrectly return the same non-None aggregation and satisfy parity. | Add independent None assertions to the normal and reference batch responses, before completion of that row. Preserve all original assertions and counts. Correct the nearby erroneous comment (`avgdl=1`, not 24). |
| F2-03 | The final F1 ZIP and Markdown are named by the PR body with hashes, but the user handoff did not supply their bytes. The reviewer cannot verify the external archive merely from a path/name/digest. | Recover and deliver the actual F1 archive if available; record its availability honestly. Deliver a new complete terminal package for the final F2 head using the supported actual file-attachment mechanism. Never report a filename alone as delivery. |

The F1 U09 expectation generation is deterministic from the fixed shape constants, not from actual results; its 12 executed outcomes match the approved table. Accept this equivalent representation; do not rewrite the table or expand acceptance. All other F1 findings are preserved. No new production or performance issue is asserted by F2.

### 1.1 Preserve verified work

| Work item | Disposition |
| --- | --- |
| C3 certificate, decoder, accounting, eager fallback, heap representation, winner finalization | Frozen. No production edit authorized. |
| F1 S01, U04, U05 and I02; unchanged C3 cases | Executed and supported by reviewed source/receipts. Preserve exactly. |
| F1 U02 | Preserve 25-tuple matrix, split 10/12/12, six complete ineligible responses and 12 other ineligible shapes; add only literal batch absence assertions and correct comment. |
| F1 U09 | Preserve all 12 outcomes, seven recoveries, exact projection refusal 13056/13160 with 100 private scores; replace helper plumbing only. |
| Historical RED/green proof and F1 baseline receipts | Preserve and reference. Do not recreate a red production variant or rerun baseline commands. |
| F1 local QA and CI | Valid historical executed checks (Clippy passed with the suppression present); cannot establish F2 acceptance after test source changes. |
| F1 terminal attachment | Reported created and integrity-checked by executor; actual delivery not yet independently verified. |
| C4 and G10 | Unstarted and maintainer-owned, respectively. |

## 2. Exact scope and invariants

### 2.1 Executable allowlist

Only `crates/quervant-core/src/search/unified.rs`, specifically the bodies of `c3_u02_dispatch_and_count_matrix` and `c3_u09_logical_budget_edges`. The exact transformation is in §4 and Appendix A. All other bytes in that file, including the test attributes, function signatures, imports, every production function and other test, must be identical to START. Every other executable/build input is frozen. No new test registration, lint suppression, global helper, public or private production API, feature, dependency, benchmark script or workflow edit.

### 2.2 Documentation allowlist

New files only:

- `$D/PERF06C3F2_DETAILED_FIXUP_PLAN.md`: supplied plan verbatim, exact bytes.
- `$D/PERF06C3F2_EXECUTION_REPORT.md`: report specified in §8.
- `$E2/**`: precisely the new scripts, contract, 45 final receipts, verification, audits and summary evidence specified in §6–§8.

Append-only existing files:

- `$D/PERF06C3F1_EXECUTION_REPORT.md` (explicit erratum, not a rewrite).
- `docs/PERF_OPTIMIZATION_ROADMAP.md`.
- `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`.
- `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` (status note only; no normative architecture change).

All other docs, prior plans, reports and evidence are frozen. Do not place the F1 or F2 ZIP in the repository. Do not commit generated raw whitespace-bearing logs; receipts encode raw bytes. Do not add or modify `.gitignore` to hide evidence.

### 2.3 Correctness / impact matrix

| ID | Invariant | Positive / negative evidence | Owning step |
| --- | --- | --- | --- |
| F2-I01 | All normal-build source, APIs, codecs, accounting and existing production branches unchanged | Exact byte transformation of unified.rs; comparison rejects any extra change; all other paths frozen | P1, G2 |
| F2-I02 | No new lint suppression | Remove the single F1-added attribute and nested helper; source checker compares exact intended bytes; both compilers, four Clippy configurations with `-D warnings` | P1, G3/G7 |
| F2-I03 | A plain batch without aggregation has `None` independently of Legacy parity | Literal normal/reference `is_none()` before completion, full equality still required; existing separate aggregation row retains exact Some group | P1, G3 |
| F2-I04 | Recovery uses exactly the original snapshot, request, generous limits and reference, with all original assertions | U09 seven recoveries, literal twelve primary outcomes and score/identity counts; earlier failure checks and G row control retained | P1, G4 |
| F2-I05 | Unchanged semantic families and real integration remain tested | Existing complete C2/C3 and B1–B3, filesystem/PIT, reader, historical regression commands; five exact name sets | P2, G5/G6 |
| F2-I06 | Mandatory quality gates execute on immutable final test source | 45 final commands at F2_TESTED; two real Lines percentages >=85; no altered exclusions; final hosted run at actual remote head | P2/P3, G7/G8 |
| F2-I07 | Deliver actual inspectable evidence without rewriting history or commit/hash cycle | Frozen historical receipts, fresh receipt contract and verifier, external package, read-back of PR body, attachment bytes available | P3, G9 |

Impact on public search, batch/aggregation, PIT/cursors, projection, mutation, storage and remote adapters is **zero production delta**. U02 exercises the actual batch API, not a substitute mock; U09 retains actual search and resource failures; I02 retains real FsDirectory mutation/compaction/reopen and five paging phases. Hosted RustFS remains mandatory. The test-only change introduces no new performance hypothesis and does not authorize timing acquisition.

### 2.4 Pre-implementation worksheet (answer before applying)

Record the following seven answers with observed START anchors in the report. The expected answers are supplied; any contradiction stops the affected work.

1. Why did Clippy pass? The F1 nested `recover_at` takes ten parameters and is locally suppressed with `#[allow(clippy::too_many_arguments)]`; its only call is in U09's failing-row branch. Passing Clippy with that attribute does not prove no suppression was added. Inlining preserves all semantics and removes the lint target.
2. Why does full response parity not prove absence? `c3_assert_full_response` compares aggregation fields for equality, so two erroneous equal Some values can pass. Both batch responses must be literally None. The separate empty aggregation request still requires the existing Some result with one empty global group.
3. Which counters may change? None of the expected route, membership, numeric, callback, score, final-identity and recovery counts. Test-only assertions inspect already-produced data; they add no query, decoder or scorer operation. The U09 inline code invokes the same recovery exactly once per failing row.
4. Why is `avgdl=24` wrong? The common keyword fixture contains one `grp` token per document, `n=df=24`, average length=1. The existing scalar formula already uses 1. Only the comment changes.
5. Which QA is reusable? Historical evidence and the exact command contract are reusable; historical command outcomes cannot be relabelled as F2. All 45 final commands run again because test source changes. No historical baseline or RED reconstruction is required.
6. Why is the final ZIP external? Committing the final-head receipt would advance the head it refers to. Terminal evidence belongs outside the checkout, after the final documentation commit and CI observation. A file name/hash is not a file attachment.
7. What happens if a historical F1 ZIP was lost? It cannot be reconstructed as an original-time receipt. Qualify that historical delivery gap, preserve committed evidence and execute/deliver the complete new F2 terminal package. Current F2 delivery can close independently; no fictitious F1 recovery, no need to redo the historical acquisition or local QA.

## 3. P0 — Admission, source and evidence preflight

Run from the workspace root, use Bash with `set -euo pipefail` for orchestration, and explicitly capture expected/nonzero outcomes where specified. Create a task-owned external scratch directory using `mktemp -d "${TMPDIR:-/tmp}/quervant-c3-f2.XXXXXXXX"`; resolve it to an absolute path. Use `W` for this directory; it must not be within the repository. Save the supplied plan there as `PERF06C3F2_DETAILED_FIXUP_PLAN.md`, verify it against the user-supplied bytes and record its SHA-256. Do not create committed docs before the immutable test revision. Keep diagnostics and receipt outputs outside the checkout until document finalization.

1. Confirm correct repository (`git rev-parse --show-toplevel`, `git remote -v`), branch, `gh pr view 132 --repo yduchesne/quervant --json number,state,isDraft,mergedAt,headRefName,headRefOid,baseRefName,baseRefOid,url,body`. Do not expose credentials.
2. `git fetch origin main dev/perf06-c3`. Require origin/main=B and origin/dev/perf06-c3=START; require exact same PR head and base. Local tracked worktree/index must be clean. If local branch is strictly behind and can fast-forward to START without discarding anything, `git merge --ff-only origin/dev/perf06-c3` after confirming correct branch and no untracked collision. Otherwise stop. No destructive commands, stashing or resetting foreign work.
3. Record `git status --porcelain=v1 --untracked-files=all`, `git status --porcelain=v1 --untracked-files=no`, `git rev-parse HEAD HEAD^{tree}`, `git write-tree`, `git ls-remote --heads origin main dev/perf06-c3`. The known disjoint prior untracked file is `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt`. If present, hash it and leave untouched. A different disjoint pre-existing untracked documentation/evidence file may be preserved under D03. Inspect ignored or untracked build inputs/Cargo configuration for shadowing as F1 §8.1 required; any new/altered source/build-affecting input is a stop. Do not delete files to get clean output.
4. Verify immutable SHA ancestry `git merge-base --is-ancestor B START`, `git merge-base --is-ancestor F1_TESTED START`; verify F1_TESTED tree and `git diff --name-only F1_TESTED START --` all docs; verify source blobs via `git rev-parse START:path` against §0.1. Record `git config --show-origin --get-all core.whitespace` (exit 1/no value permitted), relevant `.gitattributes` and unchanged whitespace settings. No whitespace exception is granted or needed at this point.
5. Read the full listed repository authorities. Verify SHA-256 pins in §0.2 using `sha256sum`. Record `rustc +1.98.1 -vV`, `cargo +1.98.1 --version`, `rustc +1.85.0 -vV`, `cargo +1.85.0 --version`, `cargo +1.98.1 llvm-cov --version`, `python3 --version`, host triple and environment. Require the pinned toolchains, x86_64 Linux F1 geometry and existing coverage tool. Use the same source/feature configurations and unchanged workflow. Do not install alternative toolchains/dependencies, alter Cargo locks or lower lint/coverage thresholds.
6. Re-verify the existing F1 51 selected receipts read-only, using the frozen verifier and contract:

   ```sh
   python3 "$E1/scripts/verify_f1_receipts.py" \
       "$E1/contracts/command-contract.json" "$E1/receipts" \
       "$W/f1-historical-verification.json"
   ```

   This is analysis of stored receipts, not a test execution. Require PASS, 51 rows, six BASELINE rows at F1_START and 45 PASS rows at F1_TESTED. Compare decoded bytes/digests and checks with original verification (the verifier output should be byte-identical if invoked unchanged; at minimum exact JSON equality). Use `git rev-parse <receipt.expected_commit>^{tree}` to independently compare each receipt's `before.tree` / `after.tree` / `index_tree`. The verifier validates internal tree format and equality, not the actual Git tree object, so perform this extra linkage. A mismatch is a stop. Do not regenerate old test outputs.
7. Verify historical run 45941531494 metadata (PR head START, base B, success, five jobs, merge checkout), optionally obtain the same RustFS log bytes if needed for delivery; it is historical, not new F2 CI. Check the F1 terminal files in the executor's previous output location and any already-existing attachment. Limit search to the known task output directories and accessible existing artifact location; no broad host scan. Filenames and hashes are in §7.1. Record found/missing and verification, then continue independent work.
8. Extract Appendix A and B into `$W/apply_verify_f2.py` and `$W/build_f2_contract.py` verbatim. Record SHA-256 of both exact extracted files; keep them unchanged after extraction. Use only Python standard library and Git, no new dependencies. Record worksheet answers. Preflight passes only if all required pins and checks match.

## 4. P1 — Exact prescribed source edits

**Design decision:** inline the recovery block rather than invent a context struct, alternate helper signature, or new abstraction. It is called from exactly one place. This removes the sole new lint suppression and makes the exact assertions obvious. The production source and every accepted test except two named bodies remain frozen.

Appendix A is the authoritative byte transformation. Run `python3 "$W/apply_verify_f2.py" apply > "$W/f2-apply.json"` once at START after P0. The helper derives the raw exact patch from the pinned START blob and normalizes that generated source with `rustfmt +1.98.1 --edition 2024 --emit stdout` over stdin from the source directory. First require that formatting START reproduces every original byte; then require that formatting the prescribed patch preserves all bytes outside the two function regions. This is a deterministic mechanical normalization, not permission to alter the design. The raw and formatted patch hashes are recorded by the helper. No formatter writes another repository file. The source patch itself is described below for review. The script refuses if a required anchor is not unique within the authorized function or if worktree bytes differ from START. If the script fails, do not adapt its anchors or manually patch a different source shape. Record the actual failure and stop under D06/D07.

### 4.1 U02 (F2-02)

In `c3_u02_dispatch_and_count_matrix`, change the misleading two-line comment to read:

```rust
        // contracts. Every document has one `grp` token, so n = df = 24 and
        // avgdl = 1.
```

In the existing `// plain batch` block, immediately after `assert_ineligible_observation("batch");`, insert:

```rust
            assert!(response.aggregation.is_none(), "batch: no aggregation");
```

This must be on the actual `search_with_batch` return, before observations are reset for the forced Legacy call. After the forced Legacy call and its route assertion, immediately before complete parity, insert:

```rust
            assert!(reference.aggregation.is_none(), "batch reference: no aggregation");
```

Use exactly the supplied patch, normalized only by Appendix A's pinned rustfmt command. After existing `c3_assert_full_response(&response, &reference, "batch legacy parity");`, before `result_rows.push("batch");`, insert:

```rust
            eprintln!("C3 F2 U02 plain-batch aggregation=none normal+legacy");
```

Do not add another search. Keep the two meters, exact same AST/request, forced Legacy RAII guard, complete hit/key/field/score/cursor comparison and route checks. Keep the separate aggregation case's exact Some group, retained byte checks, counts and reference. No change to other ineligible rows, the 25-tuple matrix, split counts or original markers.

Acceptance: existing exact U02 test must select and pass one test; require the new F2 marker after both literal assertions and complete parity, and existing F1 marker `C3 F1 U02 matrix-rows=25 certified=5 legacy=20 split-c3=10 ineligible-result-rows=6`. The explicit None assertions are a negative oracle for an incorrect shared Some result. No deliberate production-red mutation is authorized.

### 4.2 U09 (F2-01)

Delete exactly the nested `recover_at` function and its two documentation-comment lines, suppression attribute and following blank line. Do not delete or alter `assert_literal_limit`, `Expect`, `limits`, shape table, primary-loop assertions, projection budget guard, error oracle or control. At its sole call site, replace the complete `recover_at(...)` invocation with:

```rust
                        // Same-snapshot recovery under the generous G-row limits.
                        c3_reset_all();
                        let recovered = run_with(
                            &fixture,
                            &request,
                            limits(peak_entries, generous_bytes),
                            config,
                        )
                        .expect("same-snapshot generous recovery");
                        c3_assert_certified(m, k, 1);
                        assert_eq!(recovered.total_hits, m as u64, "{id}: recovery total");
                        assert_eq!(
                            keys(&recovered),
                            expected_keys,
                            "{id}: recovery literal keys"
                        );
                        assert!(recovered.next_cursor.is_some(), "{id}: recovery cursor");
                        c3_assert_full_response(&recovered, &control, id);
```

Leave `recoveries += 1;` immediately following this block. These are exactly the same former helper's operations with its parameters replaced by the caller's existing local variables, no extra allocation/query or test registration. All original helper assertions remain; `label` becomes `id`. The local `fixture`, `request`, `expected_keys`, `control`, `m`, `k`, `peak_entries`, `generous_bytes`, and `config` are already in scope, with the same values previously passed. No lint attributes are allowed.

The original F1 U09 table is authoritative. The existing implementation uses fixed shape constants and derives the same literal tuples without reading actual outcomes. Keep that code. In particular, preserve these outcomes:

| Row | Entry cap / byte cap | Result | Score calls / identities | Callbacks |
| --- | --- | --- | --- | --- |
| U09-3-E | 8 / 384 | Limit(8,9) | 0/0 | 0 |
| U09-3-B | 9 / 383 | Limit(383,384) | 0/0 | 0 |
| U09-3-X | 9 / 384 | success total 3 | 1/1 | 3 |
| U09-3-G | 9 / 1536 | success total 3 | 1/1 | 3 |
| U09-12-E | 35 / 1536 | Limit(35,36) | 0/0 | 0 |
| U09-12-B | 36 / 1535 | Limit(1535,1536) | 0/0 | 0 |
| U09-12-X | 36 / 1536 | success total 12 | 10/10 | 12 |
| U09-12-G | 36 / 6144 | success total 12 | 10/10 | 12 |
| U09-102-E | 305 / 13056 | Limit(305,306) | 0/0 | 0 |
| U09-102-B | 306 / 13055 | Limit(13055,13056) | 0/0 | 0 |
| U09-102-X | 306 / 13056 | Limit(13056,13160) | 100/100 | 102 |
| U09-102-G | 306 / 52224 | success total 102 | 100/100 | 102 |

Seven failed rows each recover on the same snapshot at their M-specific generous G limits. Each recovery requires full response equality against the independent control plus literal count, ordered keys, cursor presence and certified route. U09-102-X remains a private finalization followed by projection refusal; no partial response and no change to the geometry guard. Retain the exact F1 marker `C3 F1 U09 rows=12 failed-rows=7 recoveries=7 fixed-projection-failure=13056/13160/100`.

### 4.3 Source freeze and tested commit

Immediately after apply, inspect `git diff -- crates/quervant-core/src/search/unified.rs` and execute the checker in worktree mode. Appendix A expects exactly the deterministic formatter-normalized result of the supplied substitutions. Run `cargo +1.98.1 fmt --all -- --check` as a precommit diagnostic; this is not the final receipt. Do not run unscoped automatic formatter on other files. Any rustfmt mismatch is a stop, not permission to rewrite the exact patch or insert attributes. No need for an extra historical test/red cycle.

```sh
python3 "$W/apply_verify_f2.py" verify WORKTREE > "$W/f2-worktree-freeze.json"
git diff --check "$START" --
git diff --check
git diff --cached --check
git add -- crates/quervant-core/src/search/unified.rs
git diff --cached --check
git diff --cached --name-only
git commit -m "PERF-06-C3-F2: remove test lint suppression and assert plain-batch absence"
F2_TESTED=$(git rev-parse HEAD)
F2_TREE=$(git rev-parse HEAD^{tree})
python3 "$W/apply_verify_f2.py" verify "$F2_TESTED" > "$W/f2-tested-freeze.json"
```

Set the shell variable `START` to the full pinned SHA in §0.1 before executing these commands. Require the staged name set exactly one file and no other tracked changes. F2_TESTED must be a direct child of START. Do not amend or rewrite it. Record its SHA/tree, exact diff and raw diff SHA-256. `git status --porcelain=v1 --untracked-files=no` must be empty, index tree equals F2_TREE. If commit fails, preserve worktree, no force or destructive reset. If the pinned transform is correct but Clippy/test/format fails later, use D10/D11; there is no open-ended mechanical repair authority in F2. This is an exact patch, not a redesign task.

## 5. P2 — Final verification contract

The repository requires fresh final local verification after test-source changes. The F1 plan already supplies a complete, reviewed 45-command final catalog. Reuse it without redesign. Do not rerun the six historical baseline commands or the original C3 red experiment. Do not run additional performance, profile, instrumentation, or benchmark acquisition commands. `cargo bench --workspace --no-run` compiles only; Criterion test-mode targets reached by `cargo test --all-targets` are smoke tests, not measurements.

### 5.1 Generate exactly 45 final commands

Appendix B builds the new contract directly from the immutable F1 contract. It verifies the frozen SHA-256, selects the 45 rows classified PASS, checks their exact label set, retains every argv, assertion, expected count and test-name set, and changes only:

- commit from F1_TESTED to F2_TESTED;
- label prefix from `f1_` to `f2_` and corresponding filename;
- the U02 required marker list, which gains `C3 F2 U02 plain-batch aggregation=none normal+legacy`.

No numerical coverage floor, expected test name, command, thread setting, feature set, test selection, or output predicate is otherwise changed. The original verifier accepts this schema regardless of the label prefix; do not modify it. This is a deterministic replay of the **command contract**, not replay of old results.

```sh
python3 "$W/build_f2_contract.py" "$E1/contracts/command-contract.json" \
    "$F2_TESTED" "$W/f2-command-contract.json"
mkdir -p "$W/receipts"
python3 "$E1/scripts/run_contract.py" "$W/f2-command-contract.json" \
    "$W/receipts" "$E1/scripts/record.py" PASS
python3 "$E1/scripts/verify_f1_receipts.py" "$W/f2-command-contract.json" \
    "$W/receipts" "$W/f2-verification.json"
```

Run from the same workspace root at immutable F2_TESTED. The recorder requires clean tracked/index identity and removes both `QUERVANT_PR15I_D3C_STRATEGY` and `QUERVANT_PR15I_D3C_PREFILTER_PROFILE`. Preserve all command exits and combined output bytes. Never replace a failed receipt, rerun-to-green, filter out a test, or adjust the parser/contract to match actual output. The supplied runner stops on first unexpected nonzero command. Preserve partial output and use the matrix. No authorization to continue to a final PASS exists after a required failure. Independent read-only diagnostics may proceed.

Before running the command contract, confirm that HEAD and index tree match F2_TESTED/F2_TREE and the source checker passes. After the 45 commands and verifier finish, independently require every receipt's `expected_commit`, `before.head`, `after.head`, `before.tree`, `after.tree`, `before.index_tree`, and `after.index_tree` to equal the actual recorded immutable commit/tree (HEAD fields to F2_TESTED, tree fields to F2_TREE). The verifier checks internal identity consistency; this independent Git linkage is also mandatory. Require empty tracked status and zero unexpected receipt files. Capture an exact post-test source-check result. No source modification is permitted after the final test commit.

### 5.2 Catalog and acceptance (authoritative argv inherited from F1)

The following is the full set of final labels, with the `f2_` prefix applied by Appendix B. The original F1 contract supplies the exact argument vectors, including toolchain, test threads, test filters, test mode and feature options. Do not reconstruct argv from this summary.

| Group | Labels after `f2_` | Count | Required result |
| --- | --- | ---: | --- |
| Focused acceptance | `fin_s01`, `fin_u02`, `fin_u04`, `fin_u05`, `fin_u09`, `fin_i02` | 6 | Exactly one test selected/passed per receipt, existing F1 marker(s), new U02 marker |
| Exact inventories | `fin_list_c2u`, `fin_list_c2p`, `fin_list_c2_broad`, `fin_list_c3`, `fin_list_integration` | 5 | Exact immutable F1 sets, 24/5/52/26/12 |
| C3 unit suite | `fin_suite_c3_t1`, `fin_suite_c3_t8`, `fin_suite_c3_msrv_af` | 3 | 26/0/0 each, prescribed 1/8 thread and MSRV/all-features |
| C2 unified | `fin_suite_c2u_t1`, `fin_suite_c2u_t8` | 2 | 24/0/0 each |
| C2 physical | `fin_suite_c2p_t1`, `fin_suite_c2p_t8` | 2 | 5/0/0 each |
| Real filesystem integration | `fin_suite_integration` | 1 | 12/0/0; real writer/commit/reopen/PIT/compaction and budget/cancellation checks |
| Score and reader modules | `fin_suite_score`, `fin_suite_reader` | 2 | 19/0/0 and 9/0/0 |
| B1–B3 unit regressions | `fin_suite_b1_lib`, `fin_suite_b2_lib`, `fin_suite_b3_lib` | 3 | 65/0/0, 31/0/0, 32/0/0 |
| B1–B3 real integration | `fin_suite_b1_int`, `fin_suite_b2_int`, `fin_suite_b3_int` | 3 | B1 9/0/2 parent; required child execution as frozen contract; B2/B3 8/0/0 each |
| Historical regressions | `fin_suite_pr15h_a`, `fin_suite_pr15h_a2` | 2 | 6/0/0 and 8/0/0 |
| Formatting | `qa_fmt_198`, `qa_fmt_185` | 2 | exit 0 and empty output |
| Clippy | `qa_clippy_198`, `qa_clippy_198_af`, `qa_clippy_185`, `qa_clippy_185_af` | 4 | all exit 0, warnings denied; no new suppressions |
| Workspace tests | `qa_test_198`, `qa_test_198_af`, `qa_test_185`, `qa_test_185_af` | 4 | both toolchains/default + all features; exact original scope-aware contract |
| Coverage | `qa_cov_198`, `qa_cov_198_af` | 2 | whole-workspace production Lines >=85% each |
| Documentation | `qa_doc_198`, `qa_doc_198_af` | 2 | both configurations, `--no-deps`, exit 0 |
| Bench compile and scripts | `qa_bench_norun`, `qa_bench_scripts` | 2 | compile only; scripts 108 passed, 0 failed |
| **Total** | | **45** | Every selected receipt verified |

The 16 workspace QA commands are exactly those in F1 §8.6. They include stable 1.98.1 and MSRV 1.85.0 formatting, Clippy and tests, default/all-features combinations, stable `llvm-cov --workspace --all-targets` with and without `--all-features` and `--fail-under-lines 85`, stable documentation both configurations, bench compile and script suite. Preserve all existing exclusions unchanged. Inspect the coverage output's changed source areas and report any unexpected production coverage drop or missing scope; do not infer correctness from the aggregate.

### 5.3 Verify semantic evidence rather than counts alone

After automated receipt verification, decode the six focused outputs and save concise case lines in `$W/case-output.txt` (derived summary, not the raw authoritative receipt). Check the following fixed acceptance witnesses. All are expected to remain equal to F1 except the new F2 U02 marker. Do not change expected values in response to execution.

| Test | Fixed post-assertion evidence |
| --- | --- |
| S01 | `C3 F1 S01 rows=24 isolated-df-rows=2`; present IDF, two isolated refusals, positive zero/missing-IDF precedence unchanged |
| U02 | 25 exact tuples in original F1 §5.1; five certified/20 Legacy; split 10/12/12; six completed ineligible rows; new F2 marker after two explicit None assertions and full reference parity |
| U04 | nine exact descriptor IDs including C29 with `posting=false`; same corrupted snapshot unarmed C3; `C3 F1 U04 rows=9 isolated-C29=true unarmed-synthetic-snapshot=C3` |
| U05 | cap 86/87/99 exact literal failures, cap100 success; four recovery lines; same fixed native segments, counts and score calls |
| U09 | 12 row IDs in order; seven failures and seven recoveries; exact `U09-102-X` 306/13056 → Limit(13056,13160), membership/numeric/callbacks 102, scores/identities 100; original F1 marker |
| I02 | five complete view phases, 40/39/40/39/40 hit checks (198), 14/13/14/13/14 pages in actual source execution order; old df/n/length 40/40/180, new 39/40/173; old/new wrapper parity and stale cursor rejection unchanged |

The new U02 assertion tests actual API absence, not an empty aggregation group or empty vector. The existing aggregation request must still return the precise Some group. U09 recovery logic must still assert the independent generous control; a count-only retry is not acceptable. Source proof from Appendix A establishes all those operations were preserved, not replaced by log statements. The other five authorized F1 regions are not re-edited; specifically the four other modified F1 tests and paging helper remain byte-identical.

F1's actual line metrics (93.53%, 93.13%) are historical only. Extract F2 coverage from the verifier's `lines` fields, not regions/functions/branches, and report totals, missed, covered and percent. Do not freeze the historical percentages as F2 targets. Scope-aware workspace test totals remain 2749/0/16 default and 2794/0/100 all-features at 146 Cargo launches (136 parent libtest, 10 Criterion smoke). Record child-process summaries separately and mark interleaved child output ambiguous when indicated by the unchanged verifier. No doctest claim. New output differing from a required frozen contract value is a stop, even if a broad command exits zero. Preserve the original proof of real RustFS for F1 separately from F2 CI.

## 6. P3a — Documentation and immutable evidence preparation

Only after G0–G7 local source/semantic/QA checks pass, assemble documentation. Do not manufacture a completed report for a blocked execution. If a blocker prevents completion, provide a bounded stop report externally and do not stage an inaccurate status.

### 6.1 Evidence contents and exact file map

Create the following files under `$E2/` (only new paths, no rewrites of prior evidence):

| Path | Content / origin |
| --- | --- |
| `scripts/apply_verify_f2.py` | Exact Appendix A, byte-for-byte |
| `scripts/build_f2_contract.py` | Exact Appendix B, byte-for-byte |
| `contracts/command-contract.json` | 45-row generated F2 contract |
| `receipts/final/*.json` | Exactly 45 new receipts named by the contract |
| `verification.json` | Actual output of unchanged F1 receipt verifier on the F2 contract |
| `historical-f1-verification.json` | Actual read-only re-verification of the original 51 receipts |
| `audits/preflight.json` | Pinned identities, blobs, plan/helper hashes, toolchains, config/attributes, preserved untracked paths + hashes, worksheet, no shadow inputs, and F1 terminal availability |
| `audits/worktree-freeze.json` | Actual Appendix A verify WORKTREE output |
| `audits/tested-freeze.json` | Actual Appendix A verify F2_TESTED output |
| `audits/post-local-qa-freeze.json` | Actual Appendix A output after final QA |
| `audits/tested-diff.json` | Exact `git diff --binary --full-index START F2_TESTED --` bytes encoded in Base64 with argv, exit, SHA-256 and size |
| `summaries/case-output.txt` | Actual extracted focused case lines; no raw whitespace-bearing log copy |
| `summaries/metrics.json` | Actual verified inventory, coverage, scope-aware test metrics, commit/tree, receipt/contract/helper SHA-256 values |

The final remote-head freeze, final ranges, remote identity, CI and terminal archive belong in the external package, not this commit. The existing F1 recorder, verifier and runner are reused by exact path and SHA-256; do not copy them into E2 or fork them. If producing a diagnostic receipt before freeze, keep it outside the selected receipt tree. Preserve any failure bytes without editing them. Do not manufacture a second verification output that says PASS. Derived summaries must point to actual immutable receipts.

`tested-diff.json` may be generated with standard Python `subprocess.run` + `base64.b64encode` + `hashlib.sha256`. Capture combined bytes and actual exit; include exactly `argv`, `exit_code`, `size`, `sha256`, `base64` keys. Use the same raw-byte encoding convention for terminal range receipts in §7. Write UTF-8 JSON with sorted keys, indent=2, terminating newline. No dependency, new general framework or permanent runner modification is authorized.

The E2 directory includes no raw ZIP, no final-head self-reference, and no extra acceptance files. Keep all START bytes under E1 and original C3 evidence unchanged. Verify source/report/evidence paths by Appendix A before staging and again at final head. Since Appendix A checks an exact source transformation and all tracked path classes, it is stricter than a function-mask-only check.

### 6.2 Append factual errata, not historical rewrites

Append a dated section to `$D/PERF06C3F1_EXECUTION_REPORT.md`, retaining the original as an exact byte prefix. The following is the prescribed correction (fill the actual UTC date and link, not fictitious status):

> **F2 independent-review erratum (YYYY-MM-DD UTC).** F1's assertion of no lint suppression was incorrect. The nested `recover_at` in U09 introduced `#[allow(clippy::too_many_arguments)]`, contrary to F1 D08; the recorded F1 Clippy commands did pass with that attribute present. U02's plain batch row also lacked a literal assertion that the response aggregation was None; its complete forced-Legacy parity was present but did not independently establish absence. F2 removes the nested suppression/helper, inlines its unchanged recovery operations, asserts None for normal and forced-Legacy plain batch responses, and corrects the nearby average-length comment (n=df=24, avgdl=1). All other test and production bytes are frozen. The F1 historical receipts are unchanged. The current acceptance record is [the F2 report](PERF06C3F2_EXECUTION_REPORT.md). F1 terminal artifact availability/delivery: [actual status per §7.1]. C4 performance and G10 remain outside executor acceptance.

Use an ordinary Markdown paragraph, not a blockquote if that matches the file's style. Do not report the historical F1 terminal as independently verified unless the actual archive bytes are supplied and validated. Do not relabel the historical F1 code or QA as failure in other respects; this is a conformance and acceptance assertion repair.

Append a short dated status note to the roadmap, series register and physical execution contract. State that F2 is **test-only conformance repair on the existing PR #132**; production source is unchanged; C3/F1 historical evidence is preserved; the F2 report records actual local execution; current final-head CI/terminal closeout is supplied in the live PR body and external handoff; G10 remains open; no performance or baseline promotion, C4 unstarted. Link to the new F2 report using the correct relative path. Do not mark DONE, change numerical performance targets, edit the normative C1/C3 design, or amend any unrelated series status. Do not alter the original C3 execution report; its existing F1 errata remain sufficient historical correction.

### 6.3 Commit and immutable source linkage

Copy the user-supplied F2 plan verbatim to `$D/PERF06C3F2_DETAILED_FIXUP_PLAN.md`, verify the byte hash against the supplied plan in W. Create the F2 report per §8.1 with **local gates only** and final CI/terminal pending observation. Do not claim final head before it exists. Copy the bounded evidence above into E2. Before staging, verify hashes and that all receipts belong to F2_TESTED. Check `git diff --check` for all relevant ranges; stage only the explicit allowlist using exact paths, never `git add .` or `git add -A`. Immediately after explicit staging, before committing, run Appendix A `verify WORKTREE --tested "$F2_TESTED"`, which requires the complete staged documentation allowlist, exact source change and four append-only prefixes. Verify the staged change set, all new files and append-only prefix rules. No untracked foreign file may be staged.

```sh
# Set D, E1, E2, START and F2_TESTED as already defined.
git add -- "$D/PERF06C3F2_DETAILED_FIXUP_PLAN.md" \
    "$D/PERF06C3F2_EXECUTION_REPORT.md" "$E2" \
    "$D/PERF06C3F1_EXECUTION_REPORT.md" \
    docs/PERF_OPTIMIZATION_ROADMAP.md \
    docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md \
    docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md
git diff --cached --check
git diff --cached --name-only
python3 "$W/apply_verify_f2.py" verify WORKTREE --tested "$F2_TESTED" \
    > "$W/f2-docs-staged-freeze.json"
git commit -m "PERF-06-C3-F2: record final test-only acceptance evidence"
F2_DOCS_FINAL=$(git rev-parse HEAD)
python3 "$W/apply_verify_f2.py" verify "$F2_DOCS_FINAL" --tested "$F2_TESTED" \
    > "$W/f2-final-freeze.json"
```

Require docs commit direct child of F2_TESTED, and all F2_TESTED..F2_DOCS_FINAL changed paths under the exact documentation allowlist. Verify every executable/build/test blob byte-identical between those two SHAs. No late test edits. If a documentation-only problem is discovered before push, correct only the permitted prose or evidence pointer, add an ordinary documentation commit, and recompute final docs SHA/checks. Do not amend history. If a source change would be necessary, stop. Never create a follow-up commit purely to embed the previous commit's terminal receipt hash.

## 7. P3b — Terminal delivery, CI, PR metadata

### 7.1 Recover the historical F1 package, without rerunning F1

The live PR body at START declares these exact F1 artifacts:

| File | SHA-256 |
| --- | --- |
| `PERF06C3F1_TERMINAL_051104724125ba95d49a6d94b61500f974a3599f.md` | `58f57299189c0ae99939ad4022c05fa1af57cbdcdbfff3daa8cd267341ef0c96` |
| `PERF06C3F1_TERMINAL_051104724125ba95d49a6d94b61500f974a3599f.zip` | `1774236f407c98b8042a9e4e9248d37ca4fde2e6377559b0c8b59e8bade36110` |

The executor claims 23 payload members plus member manifest. If the actual archive exists, check the archive SHA-256, `unzip -t` (or Python `ZipFile.testzip`), safe member paths, no duplicate member names, exact manifest coverage of every payload, every payload digest, terminal Markdown SHA-256, and the START/F1_TESTED identities. Deliver the original archive unchanged with the F2 handoff, and include the original Markdown if available. A ZIP containing the exact Markdown is sufficient for historical content inspection; do not invent an external Markdown copy with different bytes. Record path, size, hash, member count and result; preserve originals.

If the old archive is not recoverable, record `F1_TERMINAL_UNAVAILABLE_FOR_INDEPENDENT_REVIEW`. This is an explicit F2 plan-author decision: historical F1 external delivery remains qualified, but current F2 acceptance can close using the complete newly verified final-head package and committed historical F1 receipts. Do not fabricate old worktree status, timestamps, log bytes, or hashes. Do not run F1 or alter its old PR body/report retrospectively beyond the permitted erratum. If an archive exists but its identity/hash/member digest disagrees, preserve it and stop the delivery conclusion (D17); do not call it merely unavailable or silently substitute another archive.

### 7.2 Push once, verify final head and exact range checks

Reconfirm live main=B and remote branch=START, PR #132 open/unmerged, readiness unchanged from observed preflight. If another actor advanced a ref, stop. Push the existing branch once, without force:

```sh
git push origin HEAD:refs/heads/dev/perf06-c3
git ls-remote --heads origin main dev/perf06-c3
gh pr view 132 --repo yduchesne/quervant --json number,state,isDraft,mergedAt,headRefName,headRefOid,baseRefName,baseRefOid,url,body
```

Require local HEAD=F2_DOCS_FINAL=remote branch=PR headRefOid; main=B; record actual F2_REMOTE_H. Record full identities, tree, UTC time, remote output and PR metadata. Verify final exact checker at H with `--tested F2_TESTED`. Use real committed-range checks, not just worktree checks. The following six commands are mandatory, with actual argv, exit, raw bytes, size and SHA-256 captured outside checkout, including empty bytes and exit 0:

```sh
git diff --check "$B..$F2_REMOTE_H"
git diff --check "$F1_START..$F2_REMOTE_H"
git diff --check "$START..$F2_REMOTE_H"
git diff --check "$F2_TESTED..$F2_REMOTE_H"
git diff --check
git diff --cached --check
```

Also record `git diff --check "${B}...${F2_REMOTE_H}"` because PR range is the merge-base comparison (B is ancestor, so expected identical diagnostics). All seven must be exit 0 and empty. No inheritance of historical C2 whitespace exception; B already contains that history and is outside this PR's range. Preserve raw failures if any, stop G7. Do not run a destructive cleanup or change whitespace configuration. Verify final tracked status and untracked foreign file hashes; report any unaffected foreign paths explicitly. No worktree/staged-check pass substitutes for a committed range.

### 7.3 Observe ordinary hosted CI at the actual final head

Keep `.github/workflows/ci.yml` unchanged. It runs on pull_request and on push to main only. No new workflow dispatch, duplicate run, manual retry, cancellation, push trigger, or CI change is authorized. Discover the exact F2_REMOTE_H run using GitHub metadata (`gh run list --repo yduchesne/quervant --branch dev/perf06-c3 --event pull_request --commit "$F2_REMOTE_H" --json databaseId,headSha,event,status,conclusion,workflowName,url,createdAt`). Require actual workflow `Rust CI`, head exact H, base B, PR132, event pull_request. If no run is yet listed, observe within the same bounded polling window; if multiple matching runs make identity ambiguous, stop CI acceptance and report the metadata. Do not select by timestamp or success alone.

Poll at most 60 times at 30-second intervals (including discovery), stop immediately on terminal result. This is observing a running job, not retrying tests or waiting for host stability. If still pending or job logs unavailable, record G8 pending/blocked accurately and deliver independent completed work. Do not dispatch another run. On terminal success, retrieve actual run metadata, job IDs, step summaries and raw logs through `gh api` / `gh run view --log` for the existing run/jobs. Distinguish PR head metadata from synthetic merge checkout SHA and verify its lineage to B and H (the ordinary workflow is a merge-ref test, not a separate head-only workflow). Do not substitute F1's successful run for F2.

All five required jobs must be terminal success:

- `rust`
- `msrv`
- `rustfs`
- `benchmark-adapter-contract`
- `python-benchmark-framework`

For the real RustFS job, inspect the unchanged pinned healthy service setup and named actual tests, not just a successful job or echoed shell command. Require the exact workflow invocations and repetitions from F1 §10.3: `pr13_s3_rustfs`, `pr13_proxy_rustfs`, `pr13_remote`, `pr13_oracle`, `pr13_oracle_geo`, `pr15g_a_rustfs` through `pr15g_d_rustfs`, `perf06_b1_rustfs`, `m1_batches`, `pr15i_a_rustfs`, `pr15i_b_rustfs`, `m2_patches`, three `m3_delete_by_query` runs, three `m5_mutation_qualification` runs, `pr13_remote_proxy`, `pr13_crash_rustfs k0` and ten `pr13_crash_rustfs k05` runs. The workflow uses `--ignored --test-threads=1`. Require positive named tests and result summaries in the appropriate steps, no missing-service/early-return skips, zero failures, all repetitions. Report actual summary count, total passed/failed/ignored across invocations, and explicitly scope any unique-name or parent/child counts. The earlier 32/65 figures are historical observations, not automatically the F2 values. If required raw logs cannot be retrieved, G8 is not PASS, even if all badges are green.

### 7.4 Final PR description (one update, read back)

Preserve draft/readiness flag; do not request review, approve, comment, merge, create a new PR or alter title unless explicitly authorized separately. The PR body may be updated, with this structure, using actual values and no fabricated claims:

```
PERF-06-C3 — certified deferred BM25; F1 and F2 acceptance repairs

Production behavior frozen since C3's reviewed source. F2 only removes the
U09 test-local lint suppression by inlining the unchanged recovery logic,
adds explicit None assertions to U02 normal/Legacy plain batch responses,
and corrects the avgdl comment. No production/runtime/benchmark change.

Identities: B, original RED/TESTED, F1_START/F1_TESTED/START,
F2_TESTED (tree), F2_DOCS_FINAL, F2_REMOTE_H, actual PR base and readiness.
Plans/reports/evidence: original C3, F1, F2 paths and hashes; historical
receipt verification and F2 45-receipt contract/verification hashes.
Acceptance: unchanged F1 matrix outcomes and inventories; U02 F2 marker;
U09 seven full recoveries and exact projection refusal; no new suppression.
Local QA: actual toolchains, parent/child scope, line metrics from Lines,
all 45 final commands on F2_TESTED; exact immutable source/range checks.
Hosted CI: actual run ID, event, head/base, checkout, five job results,
real RustFS invocations/repetition evidence; no inference if pending.
Delivery: historical F1 archive verified/found/unavailable as actually
observed. Final F2 terminal Markdown and ZIP names containing actual H;
actual attachment supplied separately with hashes in final handoff.
Gate status: G0–G8 actual; G9 local artifacts/metadata complete or blocked,
terminal delivery requires actual file handoff; G10 OPEN, maintainer-owned.
Limits: F2 test-only, U09 geometry pinned, C4 unstarted, no measured
performance or baseline promotion, PR unmerged, observed readiness preserved.
```

The `G9` wording is deliberately conditional on attachment, not a premature PASS claim. Update with `gh pr edit 132 --repo yduchesne/quervant --body-file "$W/pr-body.md"`, fetch body back with `gh pr view ... --json body,...` and compare decoded body bytes with intended UTF-8 file. GitHub may normalize one final newline; do not silently accept other differences. If terminal newline only is normalized, record exact byte difference, normalize the intended representation to the actual API-returned body once, and verify equality without changing content. Do not loop to achieve a hash. Verify unchanged head/base/state/readiness after the edit. Preserve actual read-back and intended body separately in the terminal package. No ZIP hash inside the PR body is required; report package hashes in the external handoff, avoiding a self-referential package/body cycle. A body-update failure does not invalidate code execution but blocks G9. Do not create another repository commit solely to record a body update or final CI result.

### 7.5 External terminal package (mandatory actual delivery)

Create two new files outside the checkout, named with the exact final H:

- `PERF06C3F2_TERMINAL_<full-H>.md`
- `PERF06C3F2_TERMINAL_<full-H>.zip`

Use a new task-owned package directory inside W. A terminal ZIP is not a repo artifact. Include the following actual payloads (use the exact relative names below; JSON wrappers retain raw output Base64/exit/argv/hash/size where applicable):

| Member | Required content |
| --- | --- |
| `PERF06C3F2_TERMINAL_<full-H>.md` | terminal report per §8.2, final refs, gates, actual metrics, rule ledger, limitations and explicit attachment status |
| `f2-final-freeze.json` | actual Appendix A output for H and F2_TESTED |
| `git-tree-linkage.json` | actual START/F1_TESTED/F2_TESTED/H trees, source/evidence path identities, 45 new and 51 historical receipt tree checks; unchanged foreign file evidence |
| `whitespace-B-to-H.json` | exact first range command/exit/output |
| `whitespace-F1-start-to-H.json` | exact historical F1-start range |
| `whitespace-START-to-H.json` | F2 range |
| `whitespace-TESTED-to-H.json` | docs-only range |
| `whitespace-worktree.json` | exact worktree check |
| `whitespace-index.json` | exact staged check |
| `whitespace-main-merge-base-to-H.json` | exact triple-dot B range |
| `remote-heads.json` | actual remote ref check + local identity |
| `pr-meta.json` | actual final PR metadata after body update |
| `pr-body-intended.md` | intended body bytes |
| `pr-body-readback.md` | actual read-back body bytes |
| `ci-run.json` | actual exact-head run/attempt/checkout identity, status and base/PR linkage |
| `ci-jobs.json` | actual job metadata and required step conclusions |
| `ci-rustfs.log` | actual complete real RustFS job log bytes, not only selected lines |
| `ci-rustfs-summary.json` | derived executed target/repetition/result summary and raw log digest |
| `f2-verification.json` | actual committed new verifier output, 45 rows |
| `f2-command-contract.json` | actual committed contract |
| `f2-metrics.json` | actual committed metrics summary |
| `f1-historical-verification.json` | actual read-only re-verification of 51 receipts |
| `historical-f1-terminal-status.json` | available/verified/missing status, actual historical file identity if found, no fabrication |

For terminal CI pending/blocked cases, include actual metadata and available log bytes, and list unavailable members explicitly in terminal report; never create empty fake logs. Do not declare G9 fully closed while a required terminal member is missing. For a fully successful F2 package, all 23 above payload members are required. The old F1 ZIP, if recovered, is delivered separately; do not nest it in the new ZIP. Include `member-manifest.json` (24th member on full success) containing a sorted list of each payload relative filename, size and SHA-256, excluding the manifest itself. Write all payloads first, then the manifest, then the ZIP. No file hashes itself, and the ZIP does not include its own digest. Use standard Python `zipfile` and `hashlib`, no new dependencies. All member paths are plain basenames; reject absolute paths, separators, traversal and duplicate names. Verify actual archive integrity with `ZipFile.testzip() is None`, exact member set, no duplicates, each payload SHA-256 and length from manifest, and the terminal Markdown's equality to the external file. Record ZIP and Markdown size/hash outside the archive in the final handoff. Capture the actual final remote/PR identity immediately before final delivery; if it changed, stop and preserve the package as historical rather than claim current acceptance.

**Attachment rule:** attach the actual new ZIP through the coding environment's supported file handoff and provide a real accessible file/link. The ZIP contains the Markdown and all needed evidence; deliver standalone Markdown too if supported. If the environment cannot attach files, provide exact existing paths, names, sizes and hashes, say explicitly that the actual files still need upload, and mark G9 delivery BLOCKED. Do not say 'attached' or PASS merely because archive generation/verification succeeded. User can upload the archive; no code or test rerun is needed solely for upload. If F1 historical archive was recovered, attach it unchanged separately. If not recoverable, qualify it as stated in §7.1; current complete F2 package is the prospective evidence closure. This avoids repeating an entire implementation cycle for a file-transfer issue.

## 8. Reports, acceptance gates and stop semantics

### 8.1 Committed F2 execution report

Create `$D/PERF06C3F2_EXECUTION_REPORT.md` with the following sections, using actual data only:

1. **Scope and immutable identities:** B, RED, original TESTED, F1_START, F1_TESTED/tree, START, F2_TESTED/tree, plan SHA-256, source diff SHA-256, helper/contract/verification hashes, paths and exact test scope. Identify the final head as external/pending, not as a guessed self-referential SHA.
2. **Findings F2-01 through F2-03:** original offending attribute, exact missing oracle, prescribed repair and actual executed acceptance. The terminal archive availability at admission is a historical fact; final delivery is reported externally. State why earlier F1 QA still constitutes valid evidence of its actual source but not proof of absence of the suppression.
3. **Worksheet and invariants:** seven answers; F2-I01–I07 traceability and observed source/evidence checks; include explicit residual limitations.
4. **Source proof:** actual before/after blob and SHA-256, raw patch and formatter identity, exact changed path set, no outside-function change, no new lint attribute, no registration/inventory change; worktree and immutable tested checks; F1 and C3 frozen artifacts.
5. **Repaired acceptance:** actual U02 None marker, 25 tuples/5 certified/20 Legacy, split 10/12/12 and six ineligible rows; U09 12 outcomes, seven recoveries and exact projection refusal. Retain the other four focused receipts and 18 suite results. Do not equate the number of output markers to unique tests.
6. **Per-command QA:** actual outcome/exit and receipt path for every one of the 45 commands (group headings may organize the table, but do not omit commands). Five exact inventories, four workspace scopes, two actual Lines percentages/counts, 108 script checks, bench compile only, no doctests, child ambiguity disclosure when appropriate. Explain why all required local gates were rerun despite a test-only patch.
7. **CI and evidence:** historical F1 run at START and actual observed verification; F2 exact-head CI and final range checks are pending until the external terminal phase. State where the terminal package will be delivered and why it is external. Historical F1 archive verified/available/unavailable as actually established. Do not claim an attachment already delivered if it has not been.
8. **Rule ledger and limitations:** IDs applied and observable trigger/action/evidence; all failures or blockers; no unapproved exception, no production change, no benchmark/timing, C4 unstarted, G10 open. Record a stop honestly if not all stages passed.

### 8.2 Terminal report (external)

Use this exact outline and populate from actual observations, not copied predictions:

```text
REPO / BRANCH / PR / URL / OBSERVED DRAFT / MERGED
B / ORIGINAL_RED / ORIGINAL_TESTED / F1_START / F1_TESTED / START
F2_TESTED / F2_TREE / F2_DOCS_FINAL / F2_REMOTE_H
LOCAL_HEAD / REMOTE_BRANCH / PR_HEAD / MAIN_BASE
PLAN_SHA256 / PATCH_SHA256 / CHECKER_SHA256 / BUILDER_SHA256
CONTRACT_SHA256 / VERIFICATION_SHA256 / F1_HISTORICAL_VERIFICATION_SHA256
G0..G10: actual PASS/PARTIAL/PENDING/BLOCKED/FAIL/OPEN with evidence
F2-01: exact suppression removal, U09 12 rows / 7 recoveries
F2-02: exact U02 marker, 25 tuples / 5 certified / 20 Legacy, split 10/12/12
F2-03: historical F1 archive availability and actual current terminal delivery
SOURCE FREEZE: exact transformation, protected bytes, tested..H docs-only
RECEIPTS: 45 final F2 verified, 51 F1 historical reverified (not rerun)
INVENTORIES / WORKSPACE PARENT AND CHILD COUNTS / COVERAGE LINES
ALL REQUIRED QA COMMANDS: exit, source identity, receipt paths
WHITESPACE: seven checks, exact range, exit, output length and digest
CI: actual workflow/run/attempt/event/head/base/merge checkout/jobs/logs
RUSTFS: actual invocations, repetitions, real named result summaries
PR BODY: intended/read-back equality, actual head/base/status/readiness
APPLIED DECISIONS / FAILURES / EXCEPTIONS / RESIDUAL LIMITS
FINAL DISPOSITION
EXTERNAL PAYLOADS: actual filenames, member manifest, unresolved delivery status
G10 OPEN; C4 NOT STARTED; NO BENCHMARK OR PERFORMANCE CLAIM; NO MERGE
```

The final user-facing handoff (outside the ZIP) adds actual Markdown/ZIP SHA-256, size, member count, working attachment links or precise unavailable-delivery explanation, and the final G9 disposition. This handoff is the only place required to state that the file transfer actually succeeded. Do not claim G9 PASS in the archive based on a future upload. The committed report, terminal file and final message are separate layers of evidence, not contradictory timestamps.

### 8.3 Gate ledger

| Gate | PASS condition |
| --- | --- |
| G0 Admission | Correct pinned repo/branch/base/PR, exact source/helper/plan identities, clean tracked state, preserved foreign untracked inputs |
| G1 Preparation | Worksheet, invariant/impact mapping, historical 51 receipts independently reverified and actual tree linkage, explicit repair design |
| G2 Implementation and scope | Exact Appendix A transform with permitted formatter normalization only; only two existing test bodies; all other bytes and source/build paths frozen; historical artifacts unchanged |
| G3 Scoring and dispatch acceptance | Fresh S01/U02 focused receipts pass with exact existing matrix witnesses and F2 None marker; actual normal/reference assertions; no new suppression |
| G4 Adversarial/resource acceptance | Fresh U04/U05/U09; exact original fault/cap outcomes, U09 12 rows/seven complete same-snapshot recoveries and 13056/13160/100 checkpoint |
| G5 Public real-boundary acceptance | Fresh I02 198 every-hit checks across five actual filesystem/PIT phases, I01/I03 retained and run in integration suite |
| G6 Inventories and regressions | Exact 24/5/52/26/12 sets, all 18 regression/suite commands pass under original configurations |
| G7 Local QA and range checks | All 16 required commands pass on immutable F2_TESTED, actual Lines >=85% in both regimes; all 7 whitespace checks empty/exit0; no new lint suppression, no waived gates |
| G8 Hosted regression | Actual final-head pull_request run success, all five jobs, verified checkout lineage, actual healthy RustFS bodies/repetitions and raw logs |
| G9 Evidence and delivery | Frozen F1 and original artifacts; 45 current receipts verified; actual final identities/PR body read-back; complete current external terminal ZIP verified and actually delivered; historical F1 availability explicitly qualified if lost |
| G10 Independent acceptance | OPEN, maintainer/reviewer-owned; executor must never set it PASS |

Do not use the gate labels as a substitute for the underlying evidence. Implementation and correctness gates are distinct. A successful CI badge does not substitute for local coverage or actual RustFS evidence. A valid receipt proves only the command that produced it on its identified source, not a later revision.

Use one of these exact dispositions:

- `PERF06_C3_F2_ACCEPTANCE_COMPLETE_READY_FOR_INDEPENDENT_REVIEW`: G0–G9 all PASS and actual files delivered; G10 OPEN.
- `PERF06_C3_F2_LOCAL_ACCEPTANCE_PASS_CI_PENDING`: local evidence passes, required G8 terminal observation still pending under D20; G9 terminal conclusion accordingly incomplete, G10 OPEN.
- `PERF06_C3_F2_ACCEPTANCE_EXECUTED_DELIVERY_BLOCKED`: local and hosted acceptance pass, but actual package delivery or PR metadata closeout is blocked; report precise missing action, no new test cycle merely for a transfer.
- `PERF06_C3_F2_BLOCKED_EXTERNAL_DEPENDENCY`: a named required external dependency blocks applicable gates; completed independent work accurately recorded.
- `PERF06_C3_F2_STOPPED_PLAN_AMENDMENT_REQUIRED`: HARD STOP or unlisted condition; preserve exact evidence and identify smallest amendment. Never disguise a test failure as delivery-only blockage.

## 9. Preauthorized decision and exception-handling matrix

A = AUTO-RESOLVE; D = DEFER AND CONTINUE independent work; S = HARD STOP affected work. E = executor, M = maintainer/reviewer. The action column is the complete authorization. Successful work continues automatically; this matrix does not authorize skipped QA or source redesign. A condition matching more than one rule follows the stricter applicable action. When unsure whether a rule applies, use D25.

| ID | Observable trigger | Class | Authorized action | Prohibited action | Evidence / affected gate / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | Exact repo/PR/main/remote START pins, local branch exact or safely strictly behind with clean tracked state | A | Fetch; if behind, fast-forward only to pinned START; verify all refs; proceed | reset/rebase/force-push/new branch; work against a different SHA | before/after refs, status; G0; E |
| D02 | Wrong repo/branch, remote/main drift, PR closed/merged, unexpected local commits or tracked modifications | S | Preserve all state, report actual and required refs/status | discard/stash/overwrite foreign work or adapt plan | exact refs and diff; G0; M |
| D03 | Disjoint pre-existing untracked docs/evidence outside build inputs and F2 paths | A | Hash, leave untouched, confirm unchanged at end | stage/delete/rename or treat as task-owned | path + before/after digest; G0/G9; E |
| D04 | Observed readiness differs only from the earlier `draft=true`, all refs/state still exact | A | Record actual flag and preserve it | toggle readiness, approve or request review | metadata before/after; G0/G9; E |
| D05 | Any untracked/ignored build input shadows source/toolchain/Cargo config, or collides with F2 output | S | Preserve and report path/impact | delete or override config, modify ignore rules | source and config diagnostics; G0; M |
| D06 | Source/blob/helper/plan/contract hash mismatch, exact anchor missing/duplicated, F1 historical verifier or actual Git tree linkage disagrees | S | Preserve mismatch, identify exact input, stop dependent work | rewrite history/anchors/receipts/expected hash, substitute nearby revision | observed hashes/errors; G0/G1/G2/G9; M |
| D07 | Exact source transform would change a third region/path, registration, protected bytes, or introduce an attribute | S | Preserve diff outside checkout, stop | expand scope or loosen checker | failed checker and diff; G2; M |
| D08 | Prescribed raw patch is not exactly formatter-normalized | A | Use Appendix A's pinned rustfmt normalization only; require START formatter roundtrip and protected-byte equality; record actual bytes/hashes | manual Rust changes, arbitrary formatting elsewhere, adding suppression | exact transform/normalization receipts; G2; E |
| D09 | Exact patch/checker passes; all preflight obligations met | A | Commit only unified.rs; generate F2 final contract; execute all prescribed commands without interaction | add other source, run a new red experiment or historical baseline | commit/tree + command contract; G2–G7; E |
| D10 | Pinned toolchain/formatter unavailable, compiler/linter reports a problem, or either final formatter disagrees with exact generated source | S | Preserve actual diagnostic; if missing ordinary prerequisite, attempt only repository-documented non-destructive setup once, else stop | alter code beyond exact patch, suppress lint, change toolchain/dependency/exclusion | command receipt and error; G2/G7; M |
| D11 | Any focused semantic test, inventory, regression, expected outcome or mandatory QA fails; coverage below 85% | S | Preserve failed receipt; classify actual error; stop acceptance, no new production edit | rerun-to-green, relax oracle/cap/threading, filter, lower coverage floor | exact receipt + case; G3–G7; M |
| D12 | Final command outputs contain interleaved child summaries but unchanged verifier explicitly accepts scope-aware result | A | Report actual observed child summaries and ambiguity flag separately, preserve bytes | fabricate missing child counts, mix parent counts or claim doctests | raw receipt/verification; G7/G9; E |
| D13 | Verification parser fails, command/commit/count/marker mismatch or receipt set has extra/missing files | S | Preserve exact failure; report expected and observed row; stop | change verifier/regex, pick favorable summaries, regenerate old output | contract and raw receipt; G6/G7/G9; M |
| D14 | Successful 45-command final verification and exact tree linkage | A | Assemble only allowed docs/evidence and commit | report G8/G9 terminal before observation; modify frozen evidence | verifier, per-command statuses; G6/G7/G9; E |
| D15 | Need to correct own new prose/pointer before final push, no source/evidence mutation | A | Correct only allowed new prose/append note; verify exact scope and fresh final range checks; if already committed add normal docs-only commit | amend history, rewrite older prefix or alter source, fabricate receipt | diff, new docs head; G2/G7/G9; E |
| D16 | Historical F1 archive missing after bounded search | A | Record `F1_TERMINAL_UNAVAILABLE_FOR_INDEPENDENT_REVIEW`; preserve historical receipt evidence; continue current F2; qualify old delivery | backdate/reconstruct old package, rerun historical tests, claim old delivery | searched paths and status; historical G9 qualification/current G9; E |
| D17 | F1 archive found, exact SHA/member/identity matches, or found archive fails validation | A if matches; S if fails | If matches, deliver unchanged and record actual verification. If fails, preserve discrepancy and stop affected delivery conclusion | modify archive/member, silently call mismatch missing, substitute unrelated artifact | archive validation; G9; E/M |
| D18 | Any committed/worktree/staged whitespace diagnostic | S | Preserve actual raw output, identify range/path/diagnostic; stop gate | inherit old C2 exception, edit frozen artifact, hide whitespace via config | range/exit/raw bytes; G7/G9; M |
| D19 | All local gates pass, correct pins still current, docs-only post-test range verified | A | Push existing branch once; verify exact remote/PR head and observe ordinary CI | new PR, force-push, duplicate dispatch, alter workflow | remote metadata; G8/G9; E |
| D20 | Ordinary exact-head CI still pending within prescribed polling window, or logs temporarily unavailable | D | Observe bounded existing run, then deliver accurate PENDING/BLOCKED report and independent evidence; continue later read-only observation when available | start duplicate job or claim success from badge/old run | run status and log availability; G8/G9; E/M |
| D21 | Exact-head CI fails/cancelled, multiple ambiguous runs, missing expected job, real RustFS execution/repetitions not established | S | Preserve actual run/job/log evidence and classify failure; no acceptance | rerun job, change filters or substitute fake/old service evidence | exact CI diagnostics; G8; M |
| D22 | CI success, exact head/base/checkout verified, all five jobs and actual RustFS bodies pass | A | Update PR body once, read back, build and verify current terminal package | self-referential evidence commit, merge, ready-toggle, CI rerun | raw CI/job/metadata; G8/G9; E |
| D23 | PR body edit fails or read-back differs beyond one final-newline normalization | D | Preserve actual metadata and body, report G9 blocked; deliver independent current evidence, no further source tests | claim body updated, rewrite source or loop commits | intended/readback/API error; G9; E/M |
| D24 | Current terminal archive fully generated/validated but actual file transfer unsupported, or member retrieval incomplete | D | Provide exact paths/hashes and missing items; G9 remains blocked until actual bytes supplied; no rerun needed solely for delivery | claim attached/pass from filename/hash, fabricate missing payload | package/member verification and transfer status; G9; E/M |
| D25 | Any unforeseen condition, contradiction, unapproved source modification, unstable final ref or unclear required action | S | Stop affected work, preserve all evidence, state smallest amendment and independent completed work | improvise design, change test/threshold, silently waive gate, merge | precise trigger, actual evidence, affected gates; M |

## 10. Reviewer checklist and residual risks

The independent reviewer should be able to complete a focused review without another broad implementation cycle:

- Compare B, START, F2_TESTED and actual final H; verify exact Appendix A transformation, outside-region bytes and no other source change.
- Confirm the nested lint suppression is removed, the recovery block still performs exactly the same full-response assertions on the same snapshot, both U02 None checks are explicit and prior aggregation Some row is retained.
- Inspect new focused U02/U09 receipts and the retained S01/U04/U05/I02 receipts; verify actual selected single tests, marker placement, fixed cases and expected counts.
- Verify the generated F2 contract is exactly the frozen F1 final command subset with changed identity/labels and one new marker; check 45 final receipts and actual tree linkage. Verify the 51 historical F1 receipts without assuming they were rerun.
- Verify original receipt/plan/source freeze, correct Lines and parent/child counts; all 16 local quality commands and 18 suites; five CI jobs, actual exact-head and real RustFS; all seven whitespace checks; actual archive bytes, manifest, PR read-back and delivery status.
- Distinguish historical unavailability from current acceptance. Do not demand a fresh historical test campaign to reconstruct a missing old external ZIP. If F2 archive merely needs transfer, close that delivery issue by obtaining actual bytes, not another code cycle.
- Record maintainer acceptance separately, do not make a new claim of speedup; C4 remains owner of warm performance and layout/codegen assessment.

Residual limits inherited from C3/F1: the certificate is deliberately sufficient rather than necessary; TLS observations are thread-local; synthetic/pre-route corruption cases are labeled as such; U09 projection refusal is bound to observed x86_64 `FieldValues == 32` geometry. F2 does not change or independently requalify the production performance path. No new storage/wire/public API/CI contract, no benchmark or profiler acquisition, no performance gain claimed. G10 remains open pending independent acceptance; no merge authority.

### Source references and plan-author verification limits

- [Current reviewed PR #132](https://github.com/yduchesne/quervant/pull/132) and [F1 final CI](https://github.com/yduchesne/quervant/actions/runs/45941531494).
- [Pinned unified.rs](https://github.com/yduchesne/quervant/blob/051104724125ba95d49a6d94b61500f974a3599f/crates/quervant-core/src/search/unified.rs), U02 lines 15262–15904, U09 lines 17458–17764.
- [Pinned F1 plan](https://github.com/yduchesne/quervant/blob/051104724125ba95d49a6d94b61500f974a3599f/docs/pr-artifacts/perf-06-c/PERF06C3F1_DETAILED_FIXUP_PLAN.md), especially §5.3, §6.2, §10.4, D08, and mandatory local verification in [AGENTS.md](https://github.com/yduchesne/quervant/blob/6bc977e6a26c183609b7ca53eca51d3ab09ce337/AGENTS.md).
- [F1 report](https://github.com/yduchesne/quervant/blob/051104724125ba95d49a6d94b61500f974a3599f/docs/pr-artifacts/perf-06-c/PERF06C3F1_EXECUTION_REPORT.md), [F1 command contract](https://github.com/yduchesne/quervant/blob/051104724125ba95d49a6d94b61500f974a3599f/docs/pr-artifacts/perf-06-c/evidence/c3-f1/contracts/command-contract.json), and [F1 verification](https://github.com/yduchesne/quervant/blob/051104724125ba95d49a6d94b61500f974a3599f/docs/pr-artifacts/perf-06-c/evidence/c3-f1/verification.json).

Author verification is source/receipt/CI review and validation of the plan's deterministic Python helpers. No Rust execution or production performance acquisition was performed during plan authoring. Actual Rust formatting, compilation, lint and test acceptance must be established by the coding agent on the pinned toolchains. The historical terminal package itself was not available for independent byte inspection during the review. The explicit decision to allow current F2 evidence to supersede an unavailable historical F1 terminal attachment is limited to that historical delivery gap, not a waiver of the current package or any code/QA gate.

## Appendix A — Exact source application and verification helper

Extract the following complete Python block verbatim as `apply_verify_f2.py`, and execute using Python 3 from the repository root. It uses the original pinned Git bytes, verifies the entire source before applying, and allows only the deterministic output of the prescribed formatter. It does not derive expected source from the current worktree or from observed test outcomes. No hidden design step is delegated to the agent.

```python
#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

START = "051104724125ba95d49a6d94b61500f974a3599f"
SOURCE = "crates/quervant-core/src/search/unified.rs"
SOURCE_BLOB = "eb1d1f31d7554bb99d030858e99b3d3d2946c2f7"
D = "docs/pr-artifacts/perf-06-c"
E1 = D + "/evidence/c3-f1"
E2 = D + "/evidence/c3-f2"
CONTRACT_SHA = "1107c78e330559d8631882fc815a2d78dd0cc901e8517fcb32487c4663e545c4"
FUNCTIONS = ("c3_u02_dispatch_and_count_matrix", "c3_u09_logical_budget_edges")
APPEND = {
    D + "/PERF06C3F1_EXECUTION_REPORT.md",
    "docs/PERF_OPTIMIZATION_ROADMAP.md",
    "docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md",
    "docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md",
}
NEW_DOCS = {
    D + "/PERF06C3F2_DETAILED_FIXUP_PLAN.md",
    D + "/PERF06C3F2_EXECUTION_REPORT.md",
}
FIXED_EVIDENCE = {
    "scripts/apply_verify_f2.py", "scripts/build_f2_contract.py",
    "contracts/command-contract.json", "verification.json",
    "historical-f1-verification.json", "audits/preflight.json",
    "audits/worktree-freeze.json", "audits/tested-freeze.json",
    "audits/post-local-qa-freeze.json", "audits/tested-diff.json",
    "summaries/case-output.txt", "summaries/metrics.json",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.STDOUT)


def blob(ref, path):
    if ref == "WORKTREE":
        p = Path(path)
        require(p.is_file() and not p.is_symlink(), f"missing/unsafe file: {path}")
        return p.read_bytes()
    return git("show", f"{ref}:{path}")


def mode(ref, path):
    if ref == "WORKTREE":
        p = Path(path)
        require(p.is_file() and not p.is_symlink(), f"missing/unsafe file: {path}")
        return "100755" if p.stat().st_mode & 0o111 else "100644"
    entry = git("ls-tree", ref, "--", path).decode("utf-8").strip()
    require(entry and "\t" in entry, f"missing tree mode: {path}")
    return entry.split()[0]


def diff_names(base, current, only_deleted=False):
    args = ["diff", "--name-only", "-z", "--no-renames"]
    if only_deleted:
        args.append("--diff-filter=D")
    args.append(base)
    if current != "WORKTREE":
        args.append(current)
    args.append("--")
    return {p.decode("utf-8") for p in git(*args).split(b"\0") if p}


def region(data, name):
    lines = data.splitlines(keepends=True)
    prefix = b"    fn " + name.encode("ascii") + b"("
    positions = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    require(len(positions) == 1, f"missing/duplicate function: {name}")
    start = positions[0]
    end = next((i + 1 for i in range(start + 1, len(lines))
                if lines[i] == b"    }\n"), None)
    require(end is not None, f"function close missing: {name}")
    return b"".join(lines[start:end])


def mask(data):
    for name in FUNCTIONS:
        old = region(data, name)
        require(data.count(old) == 1, f"ambiguous region: {name}")
        data = data.replace(old, ("<F2:" + name + ">\n").encode("ascii"), 1)
    return data


def replace_once(data, old, new, label):
    require(data.count(old) == 1, f"anchor not unique: {label}")
    return data.replace(old, new, 1)


def prescribed_raw(start):
    u02 = region(start, FUNCTIONS[0])
    a = replace_once(
        u02,
        b"        // contracts. Every document has one `grp` token, so n = df = avgdl = 24.\n",
        b"        // contracts. Every document has one `grp` token, so n = df = 24 and\n"
        b"        // avgdl = 1.\n",
        "U02 comment",
    )
    a = replace_once(
        a,
        b'            assert_ineligible_observation("batch");\n',
        b'            assert_ineligible_observation("batch");\n'
        b'            assert!(response.aggregation.is_none(), "batch: no aggregation");\n',
        "U02 normal batch None",
    )
    a = replace_once(
        a,
        b'            assert_eq!(c2_observation::legacy_routes(), 1, "batch legacy route");\n'
        b'            c3_assert_full_response(&response, &reference, "batch legacy parity");\n'
        b'            result_rows.push("batch");\n',
        b'            assert_eq!(c2_observation::legacy_routes(), 1, "batch legacy route");\n'
        b'            assert!(reference.aggregation.is_none(), "batch reference: no aggregation");\n'
        b'            c3_assert_full_response(&response, &reference, "batch legacy parity");\n'
        b'            eprintln!("C3 F2 U02 plain-batch aggregation=none normal+legacy");\n'
        b'            result_rows.push("batch");\n',
        "U02 reference None and marker",
    )
    u09 = region(start, FUNCTIONS[1])
    helper = b'''        /// Same-snapshot recovery with the generous limits of the `-G` row for this
        /// `M`; the complete response must equal the independently executed control.
        #[allow(clippy::too_many_arguments)]
        fn recover_at(
            fixture: &Fixture,
            request: &UnifiedRequest,
            m: usize,
            k: usize,
            entries: u64,
            bytes: u64,
            control: &UnifiedResponse,
            expected_keys: &[String],
            config: TopKDuplicateConfig,
            label: &str,
        ) {
            c3_reset_all();
            let recovered = run_with(fixture, request, limits(entries, bytes), config)
                .expect("same-snapshot generous recovery");
            c3_assert_certified(m, k, 1);
            assert_eq!(recovered.total_hits, m as u64, "{label}: recovery total");
            assert_eq!(
                keys(&recovered),
                expected_keys,
                "{label}: recovery literal keys"
            );
            assert!(recovered.next_cursor.is_some(), "{label}: recovery cursor");
            c3_assert_full_response(&recovered, control, label);
        }

'''
    b = replace_once(u09, helper, b"", "U09 suppressed recovery helper")
    call = b'''                        recover_at(
                            &fixture,
                            &request,
                            m,
                            k,
                            peak_entries,
                            generous_bytes,
                            &control,
                            &expected_keys,
                            config,
                            id,
                        );
'''
    inline = b'''                        // Same-snapshot recovery under the generous G-row limits.
                        c3_reset_all();
                        let recovered = run_with(
                            &fixture,
                            &request,
                            limits(peak_entries, generous_bytes),
                            config,
                        )
                        .expect("same-snapshot generous recovery");
                        c3_assert_certified(m, k, 1);
                        assert_eq!(recovered.total_hits, m as u64, "{id}: recovery total");
                        assert_eq!(
                            keys(&recovered),
                            expected_keys,
                            "{id}: recovery literal keys"
                        );
                        assert!(recovered.next_cursor.is_some(), "{id}: recovery cursor");
                        c3_assert_full_response(&recovered, &control, id);
'''
    b = replace_once(b, call, inline, "U09 recovery call")
    require(b"recover_at(" not in b and b"#[allow(clippy::too_many_arguments)]" not in b,
            "U09 helper/suppression remains")
    result = replace_once(start, u02, a, "U02 region")
    result = replace_once(result, u09, b, "U09 region")
    require(mask(start) == mask(result), "raw transformation changed protected bytes")
    return result


def format_source(data):
    # unified.rs has no out-of-line module declarations at the pinned source.
    # stdin means rustfmt does not write a repository file. Preserve all diagnostics
    # on failure, and do not change config or use an alternate toolchain.
    result = subprocess.run(
        ["rustfmt", "+1.98.1", "--edition", "2024", "--emit", "stdout"],
        cwd=Path(SOURCE).resolve().parent,
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0 or result.stderr:
        sys.stderr.buffer.write(result.stderr)
        raise ValueError(f"pinned rustfmt failed or emitted diagnostics: {result.returncode}")
    require(result.stdout, "pinned rustfmt emitted no source")
    return result.stdout


def exact_expected():
    require(git("rev-parse", f"{START}:{SOURCE}").decode().strip() == SOURCE_BLOB,
            "START source Git blob mismatch")
    before = blob(START, SOURCE)
    raw = prescribed_raw(before)
    require(format_source(before) == before, "pinned START rustfmt roundtrip mismatch")
    expected = format_source(raw)
    require(mask(before) == mask(expected), "formatter changed protected bytes")
    for name in FUNCTIONS:
        original = region(before, name)
        updated = region(expected, name)
        require(original != updated, f"expected region unchanged: {name}")
        # No new lint attributes. Existing unrelated allow attributes, if any, in
        # either function must be a subset of START, not fabricated by formatter.
        old_attrs = re.findall(rb"#\s*\[\s*allow\s*\([^\]]*\)\s*\]", original)
        new_attrs = re.findall(rb"#\s*\[\s*allow\s*\([^\]]*\)\s*\]", updated)
        for attr in new_attrs:
            require(attr in old_attrs, f"new allow attribute in {name}")
            old_attrs.remove(attr)
    require(b"#[allow(clippy::too_many_arguments)]" not in region(expected, FUNCTIONS[1]),
            "U09 suppression survives")
    require(b"recover_at(" not in region(expected, FUNCTIONS[1]), "U09 helper survives")
    return before, raw, expected


def final_docs_paths():
    old_contract = blob(START, E1 + "/contracts/command-contract.json")
    require(sha(old_contract) == CONTRACT_SHA, "F1 contract changed")
    items = json.loads(old_contract)["receipts"]
    rows = [item for item in items if item["classification"] == "PASS"]
    require(len(rows) == 45, "wrong F1 final row count")
    receipts = set()
    for row in rows:
        label = row["label"]
        require(label.startswith("f1_") and row["path"] == f"final/{label}.json",
                "unexpected F1 receipt label/path")
        new_label = "f2_" + label[3:]
        receipts.add(E2 + "/receipts/final/" + new_label + ".json")
    require(len(receipts) == 45, "duplicate receipt labels")
    evidence = {E2 + "/" + p for p in FIXED_EVIDENCE} | receipts
    return APPEND | NEW_DOCS | evidence


def assert_sha(ref):
    require(re.fullmatch(r"[0-9a-f]{40}", ref) is not None,
            "immutable full SHA required")
    require(git("rev-parse", ref).decode().strip() == ref, "unresolved revision")


def verify(current, tested=None):
    if current != "WORKTREE":
        assert_sha(current)
    before, raw, expected = exact_expected()
    require(blob(current, SOURCE) == expected, "actual source differs from exact F2 design")
    require(mode(current, SOURCE) == mode(START, SOURCE) == "100644",
            "source file mode changed")
    paths = diff_names(START, current)
    require(not diff_names(START, current, only_deleted=True), "deleted tracked path")
    if tested is None:
        require(paths == {SOURCE}, f"source-only path set mismatch: {sorted(paths)}")
        if current != "WORKTREE":
            require(git("rev-parse", current + "^").decode().strip() == START,
                    "tested commit not direct child of START")
    else:
        assert_sha(tested)
        require(git("rev-parse", tested + "^").decode().strip() == START,
                "tested commit not direct child of START")
        require(diff_names(START, tested) == {SOURCE}, "tested source scope mismatch")
        require(blob(tested, SOURCE) == expected, "tested source differs from exact design")
        docs = final_docs_paths()
        require(paths == {SOURCE} | docs, f"final scope mismatch: {sorted(paths ^ ({SOURCE} | docs))}")
        require(diff_names(tested, current) == docs, "post-test path set mismatch")
        if current == "WORKTREE":
            # Call final-mode worktree verification only after explicit staging.
            require(git("rev-parse", "HEAD").decode().strip() == tested,
                    "staging HEAD not F2_TESTED")
            require(not git("diff", "--name-only", "-z", "--"),
                    "unstaged tracked modifications after explicit stage")
        else:
            git("merge-base", "--is-ancestor", tested, current)
        for path in sorted(docs):
            if path in APPEND:
                require(blob(current, path).startswith(blob(START, path)),
                        f"historical doc prefix changed: {path}")
                require(blob(current, path) != blob(START, path), f"missing erratum: {path}")
                require(mode(current, path) == mode(START, path), f"doc mode changed: {path}")
            else:
                require(not git("ls-tree", START, "--", path), f"new path already existed: {path}")
                require(mode(current, path) == "100644", f"new path must be regular 0644: {path}")
                require(blob(current, path), f"empty new artifact: {path}")
    return {
        "status": "PASS", "start": START, "current": current, "tested": tested,
        "changed_paths": sorted(paths), "source_blob_at_start": SOURCE_BLOB,
        "source_before_sha256": sha(before), "raw_prescribed_sha256": sha(raw),
        "formatted_prescribed_sha256": sha(expected),
        "actual_source_sha256": sha(blob(current, SOURCE)),
        "protected_bytes_sha256": sha(mask(before)),
        "authorized_functions": list(FUNCTIONS),
        "formatter_argv": ["rustfmt", "+1.98.1", "--edition", "2024", "--emit", "stdout"],
        "normal_build_source_equal": True, "all_other_test_bytes_equal": True,
        "no_new_lint_suppression": True,
        "tested_to_final_docs_only": bool(tested),
        "checker_sha256": sha(Path(__file__).read_bytes()),
    }


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("apply")
    check = sub.add_parser("verify")
    check.add_argument("current")
    check.add_argument("--tested")
    args = parser.parse_args()
    try:
        root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        require(Path.cwd().resolve() == root, "run from workspace root")
        if args.mode == "apply":
            require(git("rev-parse", "HEAD").decode().strip() == START, "HEAD is not START")
            require(not git("status", "--porcelain=v1", "--untracked-files=no"),
                    "tracked worktree/index not clean")
            before, raw, expected = exact_expected()
            require(blob("WORKTREE", SOURCE) == before, "worktree source not START")
            Path(SOURCE).write_bytes(expected)
            result = verify("WORKTREE")
        else:
            result = verify(args.current, args.tested)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "detail": str(exc)}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Appendix B — Exact F2 command-contract builder

Extract verbatim as `build_f2_contract.py`. This program does not run commands or alter source. It validates the original contract's bytes, all 45 labels, paths/classifications and source identities. The F1 receipt verifier and runner are reused, unmodified. The builder refuses a pre-existing output path. The F2 contract retains the existing schema ID intentionally because the schema and parser are unchanged.

```python
#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import re
import sys

PIN = "1107c78e330559d8631882fc815a2d78dd0cc901e8517fcb32487c4663e545c4"
F1_START = "ee77917d303b060b0d38ab88e5d9ae73625f6676"
F1_TESTED = "8f82f8290f838547dfc7d490f44ba8c0c8798d24"
SCHEMA = "quervant-perf06-c3-f1-receipt-contract-v1"
MARKER = "C3 F2 U02 plain-batch aggregation=none normal+legacy"
LABELS = set("""
fin_s01 fin_u02 fin_u04 fin_u05 fin_u09 fin_i02
fin_list_c2u fin_list_c2p fin_list_c2_broad fin_list_c3 fin_list_integration
fin_suite_c3_t1 fin_suite_c3_t8 fin_suite_c3_msrv_af
fin_suite_c2u_t1 fin_suite_c2u_t8 fin_suite_c2p_t1 fin_suite_c2p_t8
fin_suite_integration fin_suite_score fin_suite_reader
fin_suite_b1_lib fin_suite_b2_lib fin_suite_b3_lib
fin_suite_b1_int fin_suite_b2_int fin_suite_b3_int
fin_suite_pr15h_a fin_suite_pr15h_a2
qa_fmt_198 qa_fmt_185 qa_clippy_198 qa_clippy_198_af qa_clippy_185 qa_clippy_185_af
qa_test_198 qa_test_198_af qa_test_185 qa_test_185_af
qa_cov_198 qa_cov_198_af qa_doc_198 qa_doc_198_af qa_bench_norun qa_bench_scripts
""".split())
BASE_LABELS = {"base_s01", "base_u02", "base_u04", "base_u05", "base_u09", "base_i02"}


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(old_bytes, tested):
    require(sha(old_bytes) == PIN, "F1 command contract hash mismatch")
    require(re.fullmatch(r"[0-9a-f]{40}", tested) is not None, "bad F2_TESTED SHA")
    require(tested not in (F1_START, F1_TESTED), "historical revision cannot be F2_TESTED")
    require(len(LABELS) == 45, "bad embedded final label count")
    old = json.loads(old_bytes)
    require(set(old) == {"schema", "receipts"} and old["schema"] == SCHEMA,
            "unexpected F1 contract schema")
    require(len(old["receipts"]) == 51, "wrong F1 total row count")
    baseline, final = [], []
    for row in old["receipts"]:
        require(set(row) == {"path", "label", "argv", "commit", "classification", "check"},
                "unexpected row fields")
        label = row["label"]
        if row["classification"] == "BASELINE":
            require(label in BASE_LABELS and row["path"] == f"baseline/{label}.json"
                    and row["commit"] == F1_START, "bad historical baseline row")
            baseline.append(label)
            continue
        require(row["classification"] == "PASS" and row["commit"] == F1_TESTED,
                "bad historical final row")
        require(label.startswith("f1_") and row["path"] == f"final/{label}.json",
                "bad final label/path")
        require(label[3:] in LABELS, "unexpected final label")
        # The parsed row is newly allocated from the immutable input bytes.
        # Preserve every other field exactly as a JSON value.
        row["label"] = "f2_" + label[3:]
        row["path"] = f'final/{row["label"]}.json'
        row["commit"] = tested
        if label == "f1_fin_u02":
            required = row["check"]["required_text"]
            require(MARKER not in required, "F2 marker unexpectedly present in F1")
            required.append(MARKER)
        final.append(row)
    require(len(baseline) == 6 and set(baseline) == BASE_LABELS, "baseline inventory drift")
    require(len(final) == 45 and {r["label"][3:] for r in final} == LABELS,
            "final inventory drift")
    return {"schema": SCHEMA, "receipts": final}


def main():
    require(len(sys.argv) == 4, "usage: F1_CONTRACT F2_TESTED OUTPUT")
    src, tested, dst = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    require(not dst.exists(), "output exists")
    result = build(src.read_bytes(), tested)
    with dst.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": "PASS", "receipt_count": 45,
                      "sha256": sha(dst.read_bytes()), "tested": tested}, sort_keys=True))


if __name__ == "__main__":
    main()
```

End of plan. No discretionary extension of scope is authorized.
