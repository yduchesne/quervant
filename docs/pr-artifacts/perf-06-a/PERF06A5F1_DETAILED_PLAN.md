# PERF-06-A5-F1 — Complete the required acceptance assertions

| Item | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Existing PR | [#124](https://github.com/yduchesne/quervant/pull/124), draft and unmerged at planning |
| Branch | `dev/perf06-a5-adaptive-postings` |
| Milestone | `v0.1-perf` |
| Planning date | 2026-11-24, America/Los_Angeles |
| Plan status | complete correction design; no correction implementation or new acceptance run is claimed by this document |
| Execution baseline | `bb0d6c17523eab38a61d4d1976469124688f42a9` |
| Repository destination for this exact approved file | `docs/pr-artifacts/perf-06-a/PERF06A5F1_DETAILED_PLAN.md` |

## 0. Execution contract and continuous authorization

Implement the exact test and evidence corrections in this document on the existing A5 PR. The dominant problem is incomplete acceptance assertions: existing tests pass but do not establish every invariant required by the approved A5 design. No production defect was established by the independent review.

**Production code is immutable in A5-F1.** The permitted executable delta is confined to three existing test files. The selected codec, threshold, feature declarations, error order, cancellation semantics, buffer strategy, search behavior, compaction behavior, and publication protocol remain the approved A5 contracts. The coding agent must not design an alternative oracle, fixture, representation, algorithm, threshold, or acceptance policy.

This is a correction plan under §37 of `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`. It supplements the original `PERF06A5_DETAILED_PLAN.md`; do not rewrite that document. For this correction, the five-file allowlist and exception matrix below narrow the original plan's implementation authority. In particular, original A5 D13 does not authorize a production edit during F1. A newly exposed production counterexample requires a scoped stop and an amendment.

**Continuous execution authorization:** Once the user authorizes execution of this plan, execute all prescribed stages without routine reconfirmation. Continue after a successful preflight, stage, test gate, or AUTO-RESOLVE decision. The authorization includes local commits, ordinary non-force push to the existing branch, and updating the existing draft PR body with truthful evidence. Stop affected work only for an applicable HARD STOP, an essential unavailable dependency, or a missing substantive decision. When safe work is independent, record the blocker and continue that work. A progress update is not an approval request.

Creating this planning deliverable does not itself execute it. This plan does not authorize a merge, release, benchmark acquisition, A4 rerun, A6 work, or B1 work. Do not create a second implementation PR.

An unlisted condition is a **HARD STOP for affected work** under F1-D28. Do not broaden a nearby AUTO-RESOLVE row by analogy. The stop report must identify the exact source/input, invariant, affected gates, independent work completed, and smallest required decision.

## 1. Purpose and reconciliation of the existing work

### 1.1 Observed review findings

The independent review inspected source at the baseline above, the frozen A5 plan, and actual GitHub Actions evidence. It found these bounded omissions:

| Finding | Original requirement | Observed omission | Fixed scope |
| --- | --- | --- | --- |
| F1-R01 / P2 | A5 §11.5 I05 | Post-compaction K10/K100 checks do not assert hit count, selected members, or order. Phrase/zeta checks assert totals but not independent membership. Equivalent pre-compaction checks are incomplete. | One shared, input-derived I05 search-contract helper used before and after compaction and by the existing child reopen. |
| F1-R02 / P2 | A5 §11.6 I06 | Complete MatchAll membership is checked on generation 1 only, not after append or mixed-format compaction. Rust-term queries omit legacy keys d3 and d8. | Exact eight-/ten-key vectors across original, appended, compacted, and held snapshots. |
| F1-R03 / P2 | A5 §10.1 U08/U10 | No compact corrupt-intervening advance assertion; no conversion after the final data record while EOF verification is pending. U08 representation coverage is incomplete. | Exact compact/long seek corruption fixtures, singleton/short/long state matrix, six final-record conversion cases. |
| F1-R04a / P3 | A5 §10.1 U05 | Only zero-frequency source also has an out-of-range ID; range fails first. | Independent exact ZeroFrequency assertion for an in-range source across all three encoders. |
| F1-R04b / P3 | A5 §10.1 U15 | Cost witnesses cover singleton doc-only and short positional only. | Fixed four-row cost table covering all compact modes. |
| F1-R05 / reporting consequence | A5 G3/G4/G8 | The execution report describes all prescribed checks as complete and claims I05 ordering coverage. | Current-status correction plus an appended F1 evidence section; historical executed results remain intact. |

The optional I03 child-filter/sentinel hardening note is **not** in scope. The reviewed CI logs show the actual child executed. Strengthen the shared query assertions that its existing child already invokes; preserve the launcher, environment variable, test name, ignored annotation, and parent/child protocol.

### 1.2 Capability classification

| Capability | Classification at planning | Required treatment |
| --- | --- | --- |
| Adaptive encoder, borrowed decoder, feature dispatch, ordinary/compaction producers | DONE + VERIFIED for source conformance and prior CI; independent acceptance remains open | Preserve production bytes and regression coverage. |
| U05/U08/U10/U15 required assertions | PARTIAL | Implement only §7's missing acceptance cases. |
| I05/I06 independent lifecycle oracles | PARTIAL | Implement only §8's helper/assertion changes. |
| Existing tests, local QA results, and hosted runs at the recorded old SHAs | DONE + VERIFIED as historical evidence | Preserve; do not treat them as execution of the new assertions. |
| G3/G4 completeness and corresponding G8 report | PARTIAL, superseded by review | Complete new checks and correct the current report. |
| G9 independent acceptance | OPEN | Remains maintainer/reviewer-owned after F1. |
| Actual full-corpus sizes, warm latency, writer costs/RSS, genuine complete E+F lifecycle | Deferred to A6 | No F1 acquisition or fixture substitution. |
| B1 | Blocked pending A6 and maintainer disposition | No status promotion. |

A test existing, running, and passing in the required topology are separate facts. Existing CI was green; do not reclassify old command exits as failures. The issue is missing assertions, not false CI results.

**Do not manufacture a production red run.** The new assertions should pass unchanged A5 production. Record the original omissions, the concrete counterexamples in §9, and the executed strengthened tests. The corrupt input and invalid-source cases provide genuine negative behavior checks. No mutation-testing framework, fake response factory, copied production algorithm, or temporary runtime bug is authorized.

## 2. Source facts, pins, and current-main context

### 2.1 Verified revision identities

| Item | Verified value |
| --- | --- |
| Fresh `origin/main` / PR base | `5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d` |
| Original tested A5 source | `9283344712cafab6367efeea084dc7a7ca4a0c23` |
| Reviewed A5 / F1 baseline | `bb0d6c17523eab38a61d4d1976469124688f42a9` |
| Difference from tested A5 to reviewed A5 | Only addition of `PERF06A5_EXECUTION_REPORT.md` |
| Original tested-source workflow | `45333872681`; five required jobs succeeded |
| Reviewed-head workflow | `45336474554`; five required jobs succeeded |
| Original approved A5 plan Git blob | `2c8833e610c259e145687a3cded10f5c2b4fad35` |
| Authoring-guide Git blob | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |
| `AGENTS.md` Git blob | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` |
| `docs/TESTING.md` Git blob | `91c8643eaa041b0cb475949bcefa7c074ae27fe3` |
| `.github/workflows/ci.yml` Git blob | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` |

Fresh main was checked and remains the A4 merge base. A5 lives on the existing PR branch; do not begin F1 from main or reimplement A5. The Rust workspace contains `quervant-core`, `quervant-objectstore`, and `quervant-distributed`, edition 2024, MSRV 1.85. The inspected CI explicitly uses Rust 1.98.1 for ordinary jobs and 1.85.0 for MSRV. Use those exact versions in this plan, rather than guessing from generic references to floating stable.

The original A5 plan file matches the approved planning deliverable by Git blob identity. Keep it immutable. Main's actual storage/query contracts and the preceding A5 implementation remain the foundation; this is a test-evidence delta, not a new codec phase.

### 2.2 Test and production blob identities at the execution baseline

These are Git object IDs, not SHA-256 file digests. Verify with `git rev-parse <ref>:<path>`.

| Path | Git blob |
| --- | --- |
| `crates/quervant-core/src/segment/tests.rs` | `61bd8b056b5720af38451a106b081b74fbbf65b1` |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | `ea9289f86f12b2c96c12e709f0f353ba5bbaab03` |
| `crates/quervant-core/tests/pr07_compatibility.rs` | `9c83b7ff4b88e61aa9f9ecee1b736b18ff0203a0` |
| `crates/quervant-core/src/segment/postings.rs` | `4a3abeeb921cb5ca8ecbbd93a2b71c49c4f3f538` |
| `crates/quervant-core/src/segment/format.rs` | `55ca2885def34d6563ab91b9fd81c761f19a3203` |
| `crates/quervant-core/src/segment/build.rs` | `7cf05a09e9453a254febcb7ea10bd957e175b587` |
| `crates/quervant-core/src/segment/reader.rs` | `951f08086a8a0225b7fb31195c4db359bd7fda82` |
| `crates/quervant-core/src/index/merge.rs` | `14754c16254064902fe17753f809565b0c01ec9b` |
| `docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md` | `c9873b30c6e6d11eb494c09db59240c6dd476ed5` |

### 2.3 Existing architecture and exact reuse

- Unit tests call real `encode_postings_block`, `encode_split_postings_block`, `encode_adaptive_postings_block` and `PostingsReader::new_adaptive`. Reuse `A5RawCompact`, `A3RawSplit`, `a3_postings`, `A2CountingCancel`, `a3_assert_corrupt_with`, and existing thread-local observation counters. Do not change those implementations.
- I05 uses the actual `FsDirectory → Index/writer → commit → ReaderSnapshot → UnifiedSearcher` path, existing four-field schema, `batch`, `request`, `ascend`, `keys`, `bits_by_key`, frozen scalar BM25, and `a5_relevance_prefix`.
- I06 uses the genuine pinned pre-norms fixture, `stage_fixture`, `append_and_reopen`, `open_fixture`, actual `LexicalSearcher`, literal `LEGACY_DOCS`/`APPENDED_DOCS`, and existing independent score oracles.
- I03 is an actual separate process. Its child calls `a5_assert_compacted_generation`, so correcting that helper strengthens the existing process boundary without another fixture or launcher.
- R01 already exercises the production S3 adapter and real pinned RustFS, with disposable local cache removal and cold reopen. No remote code/test change is needed; current CI reruns it for the revised candidate.

No new external framework contract or dependency is introduced. All code snippets below use inspected existing APIs. If an API or required fixture differs, apply the matrix before modifying anything.

## 3. Exact file allowlist and protected scope

Only these five tracked paths may differ from the F1 baseline:

| Path | Authorized change |
| --- | --- |
| `crates/quervant-core/src/segment/tests.rs` | Extend the existing U05/U08/U10/U15 functions exactly as §7; local imports/type annotations only as needed. |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | Add the selected private I05 helper and replace its two weak query blocks; preserve all other lifecycle and test behavior. |
| `crates/quervant-core/tests/pr07_compatibility.rs` | Add the selected private MatchAll helper and specified generation/PIT calls. |
| `docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md` | Current-status correction and appended §16 F1 evidence under §12. |
| `docs/pr-artifacts/perf-06-a/PERF06A5F1_DETAILED_PLAN.md` | Add this exact approved document without redesign. |

Every other tracked path is protected. This includes **all production code**, existing test helpers outside those bounded edits, all other tests, fixtures/goldens, Cargo files, toolchain files, workflows, benchmark code/configuration/results/caches, original A1–A5 plans and historical reports, architecture, roadmaps, and series registers. The original report is the sole authorized existing report exception.

Do not add a standalone new test module, test harness, dependency, allocator hook, benchmark, mutation framework, global observation, runtime feature flag, CI trigger, or production abstraction. Temporary command logs may live outside tracked source; do not add them as extra repository files. The consolidated report records reproducible evidence.

Performance requirements are preserved by production immutability and the four exact cost witnesses. In the test changes, also avoid waste: reuse existing indexes, execute each full query once per helper call, compute the frozen alpha map once, compute the relevance prefix of length100 once for both K values, and return captured maps for PIT checks. Do not rebuild an index or requery merely to capture a result already available.

## 4. Observable invariants and traceability

| ID | Falsifiable invariant | Inherited/new coverage | Implementation | Acceptance |
| --- | --- | --- | --- | --- |
| F1-INV01 | Every runtime/support file outside the five-file allowlist is byte-identical to the reviewed A5 baseline. | Scope constraint | §§3,6,10 | C0/C5/C6 scope guard and production blob check |
| F1-INV02 | I05 generation2 and fresh generation3 return the exact input-defined full alpha/phrase/zeta vectors; limited explicit/relevance results have exact count, prefix and alpha bits. | Completes I05 | §8.1–§8.3 | F1-I05; real scoring suite; C3 |
| F1-INV03 | Generic single-term And returns the complete independent alpha map/order on both I05 generations. | Completes I05 | §8 | F1-I05; C3 |
| F1-INV04 | I06 MatchAll returns all expected logical keys with multiplicity preserved on generations1/2/3 and held1/2. | Completes I06 | §8.4 | F1-I06; real compatibility suite; C3 |
| F1-INV05 | Full advance cannot skip invalid intervening occurrences in compact or F-selected long data. | Completes U08 | §7.3 | F1-U08 corruption cases; C2 |
| F1-INV06 | Full→lean conversion after the final data record preserves pending D/F/P-tail and frequency-sum verification. | Completes U10 | §7.4 | Six F1-U10 cases; C2 |
| F1-INV07 | In-range zero frequency raises the exact typed source error from each encoder. | Completes U05 | §7.2 | F1-U05; C2 |
| F1-INV08 | Each compact mode has one validation/measurement and one admitted output buffer, exact widths, and no capacity growth; long delegation retains zero compact work. | Completes U15 | §7.5 | Four F1-U15 rows and retained long/rejection cases; C2 |
| F1-INV09 | Cancellation precedes first/subsequent/final/post-EOF reads; cached full advance preserves its no-poll exception across singleton/short/long routes. | Completes U08 family coverage | §7.3 | Fixed family/state matrix; C2 |
| F1-INV10 | Real filesystem publication, remapping and held snapshot visibility remain exercised through existing public paths; child execution is real. | Preserved/strengthened | §§8,11 | Named local suites and child log; C3 |
| F1-INV11 | Old command successes remain historical; revised completeness claims are supported by current source, executed assertions, local QA and actual CI. | Reporting correction | §§11–13 | C4/C5/C6 |
| F1-INV12 | A4 evidence, A6 ownership, D39 limitation and B1 dependency are unchanged. | Preserved | §§3,12,16 | Protected diff and report; C6 |

C0–C7 gates are defined in §13. Each new assertion must be mapped to its actual enclosing test function in the report. The number of Rust test functions may remain unchanged; new subcases do not justify invented test counts.

## 5. State, identity, ownership, and boundary analysis

### 5.1 Relevant states

| State/transition | Expected behavior | Explicit check |
| --- | --- | --- |
| Cursor constructed, no record read | Bounded header validation; cancellation can stop the first attempted read. | U08 boundaries0 |
| One or more records read | Source-derived next record; cancellation before a subsequent read. | U08 boundaries1 for short/long |
| All records read, EOF not yet requested | Final verification remains pending; conversion preserves that state. | U10 six cases |
| Successfully verified EOF | Repeated uncancelled reads return None; cancelled attempted reads return Cancelled. | U08 full/lean all three families |
| Cached full advance target | Cached result returns without cancellation poll; a larger target attempts a read. | U08 all three families |
| Advance through bad middle occurrence | Exact occurrence error before returning target. | U08 count3 and count129 |
| Generation2 before compaction | Two adaptive inputs; exact independent 129-document search contract. | I05 |
| Generation3 after compaction/drop/reopen | One adaptive output; same logical results despite possible physical-ID remapping. | I05 and I03 |
| Legacy generation1→mixed generation2→adaptive generation3 | Eight→ten→ten literal keys, complete membership preserved. | I06 |
| Old PIT queried after new publication | Its own generation's keys and saved score bits remain visible. | I05/I06 |

### 5.2 Identities and owners

Logical `DocumentKey` values are the result identities. Physical document IDs may change during compaction and must never define expected result order. Segment IDs are immutable content identities; manifest generation identifies a published view. The test's temporary filesystem root is disposable, while checked-in fixtures and historical benchmark artifacts are protected.

Existing `IndexWriter` owns commit/compaction publication. The tests call the public method once at the existing point; do not add another commit after compact. Existing `ReaderSnapshot` owns a held view. Existing `TempDir` owns test-root cleanup. Existing remote harness owns RustFS topology and disposable cache cleanup. F1 creates no alternate persistence, recovery, cache, or ownership path.

### 5.3 Cross-component impact

| Path/component | Change | Required evidence |
| --- | --- | --- |
| Legacy/split/adaptive source encoders | None | U05 exact error; retained A2/A3/default/all-features suites |
| Compact/split shared full/lean reader | None | U08/U10 and retained validation/resource suites |
| Normal SegmentBuilder | None | Existing A5 I01/I02 and full regression |
| Compaction producer/publication | None | Stronger I05/I06 plus retained 128/129/delete/no-op/limit checks |
| Unified sorted/relevance/phrase/generic query paths | Assertions only | Exact vectors/maps before/after and actual child reopen |
| Lexical MatchAll on legacy/adaptive state | Assertions only | Exact eight-/ten-key vectors |
| Real filesystem storage boundary | No mechanism change | Existing real FsDirectory lifecycle and subprocess |
| Remote S3/RustFS boundary | No code or test change | All current hosted rustfs gates, including named R01 |
| A5 reporting | Current-status correction | Old evidence preserved, new evidence source-qualified |

New timeout, I/O retry, crash-recovery, concurrency, remote consistency and durability mechanisms are **not introduced**. Do not invent new stress campaigns for those categories. Their existing applicable suites remain mandatory regression evidence. The directly affected boundaries are cursor state, logical results across compaction, held-PIT visibility, and evidence provenance.

## 6. Preflight and pre-implementation correctness gate

### 6.1 Synchronize without overwriting work

Run from the existing repository through its established authenticated Git workflow:

~~~bash
git remote -v
git branch --show-current
git status --short
git ls-files -u
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
git rev-parse origin/dev/perf06-a5-adaptive-postings
~~~

Read PR124's current state/head/base and record them. Require the correct repository, open draft PR and verified named target branch. The initial clean checkout may be on another branch; selecting the verified target is explicitly authorized by F1-D02. Require the working branch to be the named target before test edits. Verify the reviewed baseline is an ancestor of the remote target:

~~~bash
git merge-base --is-ancestor bb0d6c17523eab38a61d4d1976469124688f42a9 origin/dev/perf06-a5-adaptive-postings
~~~

If on another clean branch, select the verified existing local target with `git switch dev/perf06-a5-adaptive-postings`. If only its verified remote-tracking branch exists locally, create its matching local tracking branch with `git switch --track -c dev/perf06-a5-adaptive-postings origin/dev/perf06-a5-adaptive-postings`; this is the same PR branch, not a new implementation branch. If the target is held by another active worktree, do not override that lock or disturb its owner; stop affected synchronization under D04 while read-only work continues. If the selected clean local branch is only behind its verified remote, fast-forward it with `git merge --ff-only origin/dev/perf06-a5-adaptive-postings`, then repeat the source checks. Do not reset, stash, clean, rebase, or force-push. Apply F1-D02/D03/D04 for synchronization or partial prior F1 work.

Fresh main remains recorded separately. If it advanced, use F1-D05/D06; this plan does not authorize rebasing A5. Known committed conflict-marker text in `docs/TESTING.md` is not an unmerged Git index when its pinned blob matches and `git ls-files -u` is empty. Record and preserve that known documentation defect under F1-D07.

### 6.2 Source inventory and protected-state proof

Read the current guide, AGENTS, TESTING, original A5 plan, this F1 plan, the report, and the named functions in the three test files. Check the blob pins above at the baseline; inspect actual branch differences before deciding what remains.

At initial start, the branch may equal the reviewed baseline. On resume, classify each step as DONE+VERIFIED / DONE NOT VERIFIED / PARTIAL / NOT STARTED / BLOCKED. Preserve conforming work. Prior evidence is reusable only for unchanged relevant tested inputs, exact commands and required topology. Do not overwrite a different F1 plan file.

Use this read-only guard before edits, before commit, and at closeout. It compares the working tree with the reviewed baseline, includes tracked staged/unstaged changes and nonignored untracked paths, and disables rename detection so an old protected path cannot disappear behind a rename:

~~~bash
python3 - <<'PY'
from pathlib import Path
import subprocess

base = "bb0d6c17523eab38a61d4d1976469124688f42a9"
allowed = {
    "crates/quervant-core/src/segment/tests.rs",
    "crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs",
    "crates/quervant-core/tests/pr07_compatibility.rs",
    "docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md",
    "docs/pr-artifacts/perf-06-a/PERF06A5F1_DETAILED_PLAN.md",
}
def paths(argv):
    raw = subprocess.check_output(argv)
    return {p.decode("utf-8") for p in raw.split(b"\0") if p}
changed = paths(["git", "diff", "--no-renames", "--name-only", "-z", base, "--"])
staged = paths(["git", "diff", "--cached", "--no-renames", "--name-only", "-z", base, "--"])
untracked = paths(["git", "ls-files", "--others", "--exclude-standard", "-z"])
unexpected = sorted((changed | staged | untracked) - allowed)
required_existing = allowed - {"docs/pr-artifacts/perf-06-a/PERF06A5F1_DETAILED_PLAN.md"}
missing = sorted(p for p in required_existing if not Path(p).is_file())
if unexpected or missing:
    raise SystemExit(f"STOP: unexpected paths={unexpected}; missing required files={missing}")
print("PASS: incremental path allowlist")
PY
~~~

This guard is evidence of file scope, not evidence that every edit inside an allowed file is authorized. Inspect the diff within all three test files. Preserve unrelated tests/helpers verbatim; only §7/§8 changes are permitted.

Copy this approved file to its named repository destination. Compare its bytes/hash with the supplied deliverable before commit. Preserve the original A5 plan blob and all non-allowlisted tracked contents. No protected historical result requires regeneration.

### 6.3 Pre-implementation correctness challenge

Before changing tests, record a compact ledger mapping F1-INV01–12 to the selected cases and actual functions. Challenge at least these counterexamples:

- K10 has total129 but zero hits, wrong ten members, or reversed order.
- Phrase/zeta totals are correct but membership is wrong.
- A map hides duplicate logical keys.
- d3 or d8 is lost/substituted while rust query results remain correct.
- Advance bypasses the bad middle occurrence.
- Conversion marks the cursor finished before its pending frequency/tail checks.
- Three shared validators all accept zero frequency.
- Only one compact mode grows its output buffer or performs duplicate measurement.

The exact discriminators are specified below. Do not add an alternative oracle or design a framework. If a specification contradiction appears, use F1-D12/D28 and continue only independent work.

### 6.4 Baseline health

Before test edits, execute §11.1's three baseline commands. Record existing function counts, actual child execution, source identity, toolchains and failures. Do not duplicate the full final QA matrix at baseline. Missing infrastructure or a failing baseline is handled by the matrix; no silent PASS or whole-task abandonment.

## 7. Exact unit-test corrections

Every case in this section is required. Extend the four existing named groups; do not add a new production path or reinterpret an expected result. The valid U08 family matrix and long corruption counterpart complete the original U08 family coverage; they are fixed bounded cases.

### 7.1 Exact edit scope and reuse

Only `crates/quervant-core/src/segment/tests.rs` changes for these corrections. Extend the existing four named test functions; retain all their existing guarantees and the other twelve A5 groups. Do not edit `postings.rs`, `format.rs`, observation counters, raw fixture builders, or public APIs.

Existing APIs verified:

```rust
fn a3_postings(docs: &[u64], freqs: &[u64], positional: bool) -> Vec<Posting>;
fn a5_encode_with(segment_doc_count: u64, postings: &[Posting], limits: &SegmentLimits) -> Vec<u8>;
fn a3_assert_corrupt_with(error: &SegmentError, context: &str, detail: &str);
A5RawCompact::new(marker: u8, freq_total: u64)
    .df(count: u64) // short only
    .streams(docs: &[u8], freqs: &[u8], positions: &[u8])
    .encode() -> Vec<u8>;
PostingsReader::new_adaptive(bytes, segment_doc_count, &limits)
PostingsReader::{next, next_with, advance, advance_with, into_doc_freq}
DocFreqPostingsReader::{next, next_with} // no advance API
```

`A2CountingCancel { polls: Cell<u64>, cancel_after: u64 }` increments polls and cancels on poll `cancel_after + 1`. It is already in this same test module. `a3_postings` creates each positional occurrence as `(position=i, position_length=1, value_index=0, start_offset=2*i, end_offset=2*i+1)`.

### 7.2 F1-U05 — independent ZeroFrequency assertion

Retain all twelve existing comparison-table cases, especially `(doc_id=9, freq=0, segment_doc_count=4)`, whose expected first rejection is document range. Add a separate in-range source after that table:

```rust
let zero = [Posting {
    doc_id: 0,
    freq: 0,
    occurrences: Vec::new(),
}];
for result in [
    encode_postings_block(4, &zero, &limits),
    encode_split_postings_block(4, &zero, &limits),
    encode_adaptive_postings_block(4, &zero, &limits),
] {
    let error = result.expect_err("an in-range zero frequency must fail");
    assert!(matches!(error, SegmentError::ZeroFrequency { doc_id: 0 }));
}
```

This adds one logical invalid-source case, exercised through three encoders. Do not merely add it to the cross-encoder comparison table: every encoder shares the modified validator, so equality alone does not pin the expected error independently. Do not duplicate this scenario in both places. The original 12-case table remains unchanged; the report may describe 13 source cases overall.

### 7.3 F1-U08 — complete the already-required family/state matrix

Retain the function name `a5_u08_cancellation_advance_and_conversion`. Generalize its existing valid positional fixture to fixed counts `[1usize, 3, 129]`, documents `0..count`, all frequencies `1`, `segment_doc_count=count`. Use `a3_postings(..., true)` and `a5_encode_with`. Assert the first marker is respectively `5`, `7`, `3`. All readers in this new matrix must open through `new_adaptive`, including the long fixture.

This is three tiny fixed fixtures, not an unbounded Cartesian test generator. It supplies singleton/short/long representation coverage explicitly required by original U08. Keep positional=true for this cancellation matrix; all four compact mode combinations are separately covered by bytes/decoder tests and by the corrected U15 below.

#### Paired full/lean cancellation checks

For singleton use cancellation boundaries `[0, 1]`; for counts 3 and 129 use `[0, 1, count]`. Avoid running singleton boundary 1 twice.

For each boundary create **fresh** full and lean cursors plus separate `A2CountingCancel` values. Use bounded loops: for each cursor, call `next_with` exactly `cancel_after` times, require each call to return the input-defined `(doc_id, freq) = (ordinal, 1)`, then call once more and require cancellation. Do not use an unbounded drive loop. Require:

- Both errors are exactly `SegmentError::Cancelled`.
- Each successful full and lean record equals the **input-defined** `(ordinal, 1)` for `ordinal` in `0..cancel_after`; comparing only full against lean is insufficient.
- Both poll counters equal `cancel_after + 1`.

The boundary equal to count proves cancellation occurs before the final exhaustion verification; boundary 0 proves first-read cancellation. Boundary 1 on short/long proves cancellation before a subsequent data record. Singleton has no subsequent data record, so its boundary 1 is the final-verification case.

Use separate bounded full and lean loops; do not add a generic cursor trait, enum wrapper, boxing, production instrumentation, or new dependency just to reduce a few lines of test code.

#### EOF and full advance checks for each count

Create fresh full and lean cursors, read exactly `count` input-defined records from each, require the next call to return the first successful `None`, and require two additional uncancelled `next()` calls to return `None`. Then use a freshly cancelled `CancellationFlag` and require each cursor's `next_with` to return `Cancelled`, even after successful EOF. This is an immutable cursor attempt; no promise about recovery after arbitrary decode errors is introduced.

For full advance, open a fresh cursor, call `advance(count-1)`, and require document `count-1` with frequency1. Create a cancelled flag. `advance_with(count-1, &flag)` must return that cached posting successfully; `advance_with(count, &flag)` must return `Cancelled` because it attempts a read. Never add a lean advance API or an expectation that a cached full advance polls cancellation.

For consuming conversion, open a fresh full cursor and read document0; convert. For short/long, the next lean record must be document1/frequency1. For singleton, the next lean result must be `None`. The stronger pending-final-validation corruptions belong to U10 below.

#### Corrupt intervening compact posting (mandatory counterexample)

Use this literal raw fixture; construction is independent of the encoder:

```rust
let corrupt = A5RawCompact::new(A5_COMPACT_SHORT_POSITIONAL, 3)
    .df(3)
    .streams(
        &[0, 1, 1],
        &[1, 1, 1],
        &[0,1,0,0,1, 0,0,0,0,1, 0,1,0,0,1],
    )
    .encode();
```

Exact full bytes are:

```text
07 01 03 03 03 03 0f
00 01 01
01 01 01
00 01 00 00 01  00 00 00 00 01  00 01 00 00 01
```

The constructor succeeds: df3, frequency total3, D3/F3/P15, exact extent. Document0 has a valid occurrence. Document1's position_length is zero. Document2 is valid but must never be returned by a seek that encounters document1.

Open with `new_adaptive(&corrupt, 3, &limits)`; require first `next()` to return doc0/freq1 and occurrence `(0,1,0,0,1)`. Require `advance(2)` to fail, and use `a3_assert_corrupt_with(&error, "postings", "zero position length")`. The context is **postings**, not **adaptive postings**: it is the retained shared occurrence semantic error.

Repeat with a fresh cursor and first-record read, then `advance_with(2, &CancellationFlag::new())`; require the same exact error. A cancelled flag would test cancellation precedence rather than the corrupt intervening posting and is therefore not a substitute.

#### Corrupt intervening long list (bounded retained-family check)

Original U08 asks for family coverage as applicable. A singleton has no intervening posting; record N/A for that case. The long case can reuse `A3RawSplit::valid` without creating a new wire builder:

1. Build docs `0..129` and 129 unit frequencies, positional=true.
2. `let mut raw = A3RawSplit::valid(&docs, &freqs, true);`
3. Assert `raw.positions.len() == 645` and `raw.positions[6] == 1`.
4. Set `raw.positions[6] = 0`; retain every stream length/directory value and call `raw.encode()`.
5. Open through **new_adaptive** with segment count129; first doc0 succeeds.
6. Require `advance(2)` to fail with `Corrupt { context: "postings", detail: "zero position length" }`; use a fresh reader for the `advance_with` equivalent.

Index6 is the position_length of the second 5-byte unit occurrence. This is a bounded tiny raw corruption in the existing A3 grammar selected under F. It does not mutate a historical golden or production code. The retained A3 corruption tests stay unchanged.

### 7.4 F1-U10 — conversion after all records, before EOF validation

Retain the existing full/lean allocation witnesses and midstream conversion assertions verbatim. Append the following six single-posting cases. All use segment_doc_count1 and default limits. Construct with `A5RawCompact`; do not set `.df` for singleton markers.

| Case | Marker / freq_total | D / F / P raw bytes | Exact expected next lean result after full record + conversion |
| --- | --- | --- | --- |
| Valid doc-only | 4 / 1 | `[0]` / `[1]` / `[]` | `None`, then repeated `None` |
| Valid positional | 5 / 1 | `[0]` / `[1]` / `[0,1,0,0,1]` | `None`, then repeated `None` |
| Header sum mismatch | 4 / 2 | `[0]` / `[1]` / `[]` | adaptive `frequency total mismatch` |
| Document tail | 4 / 1 | `[0,0]` / `[1]` / `[]` | adaptive `doc stream trailing bytes` |
| Frequency tail | 4 / 1 | `[0]` / `[1,1]` / `[]` | adaptive `frequency stream trailing bytes` |
| Position tail | 5 / 1 | `[0]` / `[1]` / `[0,1,0,0,1,0]` | adaptive `position stream trailing bytes` |

Exact byte arrays, useful for plan transcription checks:

```text
valid doc:  04 01 01 01 01 00 00 01
valid pos:  05 01 01 01 01 05 00 01 00 01 00 00 01
sum:        04 01 02 01 01 00 00 01
doc tail:   04 01 01 02 01 00 00 00 01
freq tail:  04 01 01 01 02 00 00 01 01
pos tail:   05 01 01 01 01 06 00 01 00 01 00 00 01 00
```

Per case:

1. Construct and require success.
2. Call full `next()` **exactly once**; require doc0/freq1 and the expected empty/one-element occurrences.
3. Do not request full EOF. Immediately consume via `into_doc_freq()`.
4. On negative cases require `lean.next().expect_err(...)`, then `a3_assert_corrupt_with(&error, A5_ADAPTIVE_CONTEXT, exact_detail)`.
5. On the two valid cases require `None`, then repeated `None`.
6. Drop each failed cursor; introduce no retry/rollback semantics after corruption.

A fixed table `(label, bytes, positional, Option<&str>)` is sufficient. No helper needs production visibility. Checking the full record's actual frequency1 also detects a header-frequency alias instead of legitimate pending sum validation.

### 7.5 F1-U15 — all four cost combinations with literal counts

Replace only the two repeated compact witness blocks with the following fixed four-row table and the same assertions. Keep existing long-list and rejected-admission blocks unchanged.

| Label | docs | freqs | positional | segment docs | marker | actual occurrence count m | exact width calls | encoded bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| singleton doc-only | `[3]` | `[2]` | false | 4 | 4 | 0 | 6 | 8 |
| singleton positional | `[3]` | `[2]` | true | 4 | 5 | 2 | 16 | 18 |
| short doc-only | `[1,4,9]` | `[2,1,3]` | false | 10 | 6 | 0 | 11 | 13 |
| short positional | `[1,4,9]` | `[2,1,3]` | true | 10 | 7 | 6 | 41 | 43 |

Use `a3_postings`. Explicit `&[u64]` slice coercions in table rows avoid Rust array-length type mismatch. For each row create the input, call `encode_observation::reset()` **immediately before the one encode**, encode exactly once, and read counters immediately afterwards. Assert:

```text
validation_calls == 1
compact_validation_calls == 1
width_calls == the literal table value
compact_output_buffers == 1
initial_capacity >= bytes.len()
initial_capacity == final_capacity
bytes[0] == table marker
bytes.len() == table encoded length
```

The independent formula is `2*n + 5*m + 4` for singleton, `2*n + 5*m + 5` for short. Crucially, doc-only `m=0` even when the sum of frequencies is nonzero: count actual `occurrences.len()` if checking the formula, not sum(freq). Literal expected widths protect against a shared arithmetic mistake in the test and production measurement formula. No capacity==length assertion: the allocator may over-reserve.

The retained long case df129 remains one validation, zero compact validation, zero width calls, zero compact output buffers. Retained failed admission remains zero output allocations/capacities. Every test iteration resets observations, so normal parallel test execution remains valid with the existing thread-local counters.

## 8. Exact local integration corrections

Use the following source-checked helper bodies and insertion points. No new index corpus or top-level test is needed. Preserve all existing public lifecycle, feature/marker, immutable-object and held-PIT assertions.

### 8.1 F1-I05 — selected shared helper

Add exactly this private helper in the A5 section of `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs`, after `a5_zeta_request` and before `a5_assert_compacted_generation`:

```rust
fn a5_assert_i05_search_contract(
    snapshot: &ReaderSnapshot,
    specs: &[DocSpec],
) -> [BTreeMap<String, u64>; 3]
```

Return order is fixed: `[alpha_bits, phrase_bits, zeta_bits]`. The fixed array avoids a new test data structure and lets I05 keep its existing PIT comparisons without rerunning the three full queries just to capture their results. Each distinct request combination is executed once; the full alpha, phrase, and zeta results are each queried once per helper invocation. The helper computes the independent alpha score map once per invocation, outside all top-K loops.

The helper is specific to the existing 129-document I03/I05 corpus. Do not route the 128-document sibling or delete case through it. The existing general `a5_compacted_alpha_scores` helper must remain unchanged because the 128-document sibling uses it.

### 8.2 Exact I05 helper body

This body uses only names and APIs already present in the inspected file. Rustfmt may format it; the predicates, counts, oracles, sorting semantics, and return order are fixed.

```rust
fn a5_assert_i05_search_contract(
    snapshot: &ReaderSnapshot,
    specs: &[DocSpec],
) -> [BTreeMap<String, u64>; 3] {
    assert_eq!(specs.len(), 129, "I03/I05 uses the frozen 129-document corpus");
    let alpha_frequency: usize = specs.iter().map(|spec| spec.alpha).sum();
    let filler_frequency: usize = specs.iter().map(|spec| spec.filler).sum();
    assert_eq!((alpha_frequency, filler_frequency), (321, 256));
    assert_eq!(alpha_frequency + filler_frequency, 577);

    let ascending_keys: Vec<String> = specs
        .iter()
        .map(|spec| format!("k{:05}", spec.ordinal))
        .collect();
    let expected_phrase: Vec<String> = specs
        .iter()
        .filter(|spec| spec.ordinal % 4 != 0)
        .map(|spec| format!("k{:05}", spec.ordinal))
        .collect();
    let expected_zeta: Vec<String> = specs
        .iter()
        .filter(|spec| spec.ordinal % 5 != 0)
        .map(|spec| format!("k{:05}", spec.ordinal))
        .collect();
    assert_eq!(expected_phrase.len(), 96);
    assert_eq!(expected_zeta.len(), 103);
    let expected_alpha = a5_compacted_alpha_scores(specs);
    assert_eq!(expected_alpha.len(), 129);

    let alpha = search_ok(snapshot, &request(term(), 300, ascend()));
    assert_eq!(alpha.total_hits, 129);
    assert_eq!(alpha.hits.len(), 129);
    assert_eq!(keys(&alpha), ascending_keys, "full alpha keys and order");
    let alpha_bits = bits_by_key(&alpha);
    assert_eq!(alpha_bits, expected_alpha, "full alpha frozen score bits");

    let phrase = search_ok(snapshot, &a5_phrase_request());
    assert_eq!(phrase.total_hits, 96);
    assert_eq!(phrase.hits.len(), 96);
    assert_eq!(keys(&phrase), expected_phrase, "input-derived phrase members");
    let phrase_bits = bits_by_key(&phrase);

    let zeta = search_ok(snapshot, &a5_zeta_request());
    assert_eq!(zeta.total_hits, 103);
    assert_eq!(zeta.hits.len(), 103);
    assert_eq!(keys(&zeta), expected_zeta, "input-derived zeta members");
    let zeta_bits = bits_by_key(&zeta);

    let expected_relevance = a5_relevance_prefix(&expected_alpha, 100);
    assert_eq!(expected_relevance.len(), 100);
    for top_k in [10usize, 100] {
        let explicit = search_ok(snapshot, &request(term(), top_k, ascend()));
        assert_eq!(explicit.total_hits, 129);
        assert_eq!(explicit.hits.len(), top_k);
        assert_eq!(
            keys(&explicit),
            ascending_keys[..top_k].to_vec(),
            "k{top_k} explicit prefix"
        );
        let observed = bits_by_key(&explicit);
        for key in &ascending_keys[..top_k] {
            assert_eq!(observed[key], expected_alpha[key], "k{top_k} explicit bits {key}");
        }

        let relevance = search_ok(snapshot, &request(term(), top_k, Sort::default()));
        assert_eq!(relevance.total_hits, 129);
        assert_eq!(relevance.hits.len(), top_k);
        assert_eq!(
            keys(&relevance),
            expected_relevance[..top_k].to_vec(),
            "k{top_k} relevance prefix"
        );
        let observed = bits_by_key(&relevance);
        for key in &expected_relevance[..top_k] {
            assert_eq!(observed[key], expected_alpha[key], "k{top_k} relevance bits {key}");
        }
    }

    let conjunction = search_ok(
        snapshot,
        &request(Query::And(vec![term()]), 300, ascend()),
    );
    assert_eq!(conjunction.total_hits, 129);
    assert_eq!(conjunction.hits.len(), 129);
    assert_eq!(keys(&conjunction), ascending_keys, "generic fallback keys and order");
    assert_eq!(
        bits_by_key(&conjunction),
        expected_alpha,
        "generic fallback frozen score bits"
    );

    [alpha_bits, phrase_bits, zeta_bits]
}
```

The expected ascending order follows the literal input ordinals 0–128 and the stored `doc_id` strings `d00000`–`d00128`, which are bytewise ascending in the same order as the corresponding `k` keys. Do not sort or otherwise repair the observed response before explicit/relevance/phrase/zeta assertions: their order is part of the search contract.

The relevance oracle remains the existing `a5_relevance_prefix`: descending `f64::from_bits(score_bits)` using `total_cmp`, then ascending logical `DocumentKey` bytes. Compute its 100-key result once before the K loop, then use `[..top_k]` for K10/K100; do not sort the same expected map twice. Never use physical document IDs or the order returned by a reference production query. All fixture alpha scores are finite; the frozen helper's exact floating-point operation order stays unchanged.

The assertions borrow their expressions through `assert_eq!`; they do not consume the expected vectors/maps. The final array moves the three observed maps once. `BTreeMap` indexes with `&String` are already used throughout this source. No new imports are needed.

### 8.3 Exact I05 call-site replacements

#### 8.3.1 Fresh generation 3 (shared with I03 and repeated-compaction check)

Inside `a5_assert_compacted_generation`, preserve the existing open/generation/segment/features/marker checks through `drop(guard)`. Replace its whole current query-only block, from `let specs = batch(129, ...)` through the final generic fallback assertion, with:

```rust
let specs = batch(129, |ordinal| ordinal % 4 + 1);
let _ = a5_assert_i05_search_contract(&snapshot, &specs);
```

This removes the unconditional `matches!(sort, Sort { .. })` branch and all weak/redundant assertions that the new shared helper supersedes. Existing I03 invokes this function after its true process reopen; I05 calls it after compaction and drop; the no-op sibling calls it after its fresh reopen. Preserve those existing invocation sites.

#### 8.3.2 Generation 2 before compaction

Inside `a5_i05_compaction_reclassifies_adaptive_terms`, preserve all input-segment checks and the sorted `alpha_dfs` / `zeta_dfs` assertions. Replace the existing query block beginning `let specs = batch(129, ...)` and ending the capture of `gen2_zeta_bits` with:

```rust
let specs = batch(129, |ordinal| ordinal % 4 + 1);
let [gen2_alpha_bits, gen2_phrase_bits, gen2_zeta_bits] =
    a5_assert_i05_search_contract(&snapshot2, &specs);
```

Preserve the single public compaction, writer live-reader assertions, index/directory drops, the three existing held-PIT map comparisons, and `a5_assert_compacted_generation(&temp.path)`.

Resulting evidence is three distinct things: the generation-2 queries match an independent input oracle; the new compacted generation-3 queries match the same independent oracle; the held generation-2 PIT reproduces its saved maps exactly. No cross-generation reference query is used as the correctness oracle.

### 8.4 F1-I06 — selected helper and insertions

In `crates/quervant-core/tests/pr07_compatibility.rs`, add this private helper after `a5_keys` and before the I06 test:

```rust
fn a5_assert_match_all_keys(snapshot: &ReaderSnapshot, expected: &[String]) {
    let response = search(snapshot, &Query::MatchAll);
    assert_eq!(response.total_hits, expected.len() as u64, "MatchAll total");
    assert_eq!(response.hits.len(), expected.len(), "MatchAll returned length");
    let mut observed = a5_keys(&response);
    observed.sort_unstable();
    assert_eq!(observed.as_slice(), expected, "complete logical key membership");
}
```

Unlike I05 sorted search, I06's requirement is complete membership, so sorting the `MatchAll` result before comparison is intentional. Preserve duplicates; never use a set or `dedup`, because duplicate or missing keys must fail. The expected vector is sorted before the helper is called. The existing `search` uses real `LexicalSearcher`, the fixture's actual schema/registry, fresh budget, `NeverCancel`, and `TopK100`, which already exceeds both corpus sizes. Do not change those helpers.

Apply these exact insertions/replacements:

1. In generation 1, replace the current inline `all_keys` query/comparison with:

   ```rust
   let mut expected_legacy_keys: Vec<String> = LEGACY_DOCS
       .iter()
       .map(|(key, _, _)| (*key).to_owned())
       .collect();
   expected_legacy_keys.sort_unstable();
   assert_eq!(expected_legacy_keys.len(), 8);
   a5_assert_match_all_keys(&gen1, &expected_legacy_keys);
   ```

   Preserve the immediately following generation-1 title/body bit captures.

2. Immediately after the existing concatenated `corpus: Vec<DocSpec>` is built on generation 2, add:

   ```rust
   let mut expected_all_keys: Vec<String> = corpus
       .iter()
       .map(|(key, _, _)| (*key).to_owned())
       .collect();
   expected_all_keys.sort_unstable();
   assert_eq!(expected_all_keys.len(), 10);
   a5_assert_match_all_keys(&gen2, &expected_all_keys);
   ```

   Preserve all title/body/OR independent score and membership assertions and bit captures. The exact expected keys are d1,d2,d3,d4,d5,d6,d7,d8,n1,n2. d3 and d8 are deliberately included although the rust queries do not match them.

3. In generation 3, immediately after its reader guard is dropped, call:

   ```rust
   a5_assert_match_all_keys(&gen3, &expected_all_keys);
   ```

   Preserve the following independent title/body/OR query assertions.

4. In the held-PIT section after the generation-3 assertions, add:

   ```rust
   a5_assert_match_all_keys(&gen1, &expected_legacy_keys);
   a5_assert_match_all_keys(&gen2, &expected_all_keys);
   ```

   Preserve every saved title/body/OR bit comparison and original immutable-object byte comparison. Do not compare generation-1 scores with generation-2/3 scores, because corpus statistics differ.

## 9. Adversarial strategy and failure behavior

### 9.1 Why these assertions distinguish correct behavior

| Plausible incorrect behavior | Required discriminator | Evidence class |
| --- | --- | --- |
| Limited result reports total129 and returns zero hits | Exact hit count and full expected prefix | I05 new acceptance |
| Valid scores accompany reversed or wrong top-K keys | Ordered expected vector before per-key score comparison | I05 new acceptance |
| Phrase96 or zeta103 substitutes a nonmatching key | Complete vectors derived from input ordinal predicates | I05 new acceptance |
| Generic query duplicates one key and omits another while a map hides it | Exact returned length and ordered vector before map equality | I05 new acceptance |
| Mixed lifecycle loses/substitutes d3 or d8 | MatchAll vector includes every literal input key; no set/dedup | I06 new acceptance |
| Old generation1 PIT exposes newly appended keys | Exact original eight-key vector after compaction | I06 new acceptance |
| Advance jumps over an invalid intervening occurrence | Exact shared occurrence error for the raw count3/count129 fixture | U08 negative acceptance |
| Conversion publishes finished early or loses pending state | Sum/tail error after final-record conversion; valid EOF companion | U10 negative/positive acceptance |
| Conversion replays cached final record | Next lean result must be None or the exact final error, never Some | U10 acceptance |
| Shared validator accepts zero frequency consistently | Independent typed ZeroFrequency assertion for all three encoders | U05 negative acceptance |
| A single compact mode performs excess work or grows capacity | Literal counters/capacity checks for all four marker classes | U15 structural acceptance |
| Cancellation is checked after EOF or on cached advance | Exact family/state outcomes and poll counts | U08 acceptance |
| An ignored declaration or zero-match filter is mistaken for execution | Named executed tests, positive selected counts, actual child/R01 logs | Execution evidence |

This is an adversarial argument tied to actual new assertions. Do not claim hypothetical faulty implementations were executed. Do not introduce `catch_unwind` tests of copied assertions, synthetic search-response builders, a global allocator, production mutation, fuzz infrastructure, or additional dependencies.

### 9.2 Failure-mode matrix

| Condition | Expected observable result | State/cleanup rule | Acceptance impact |
| --- | --- | --- | --- |
| In-range zero-frequency source | `SegmentError::ZeroFrequency { doc_id: 0 }` | No successful encoded result | U05 must assert exact variant |
| Invalid middle occurrence during full advance | `Corrupt` with context `postings` and detail `zero position length` | Drop failed cursor; do not infer retry/rollback behavior | U08 must reject before target |
| Pending compact stream tail after conversion | Exact adaptive D/F/P trailing-byte error | Drop failed cursor | U10 must preserve final verification |
| Pending compact header/body frequency mismatch | Exact adaptive `frequency total mismatch` | Actual returned posting frequency remains1; drop failed cursor | U10 must preserve observed sum |
| Cancelled attempted read, including final or post-EOF | `SegmentError::Cancelled` | Each test uses its own fresh cursor/flag | U08 checks required boundaries |
| Cached full advance with cancelled flag | Cached posting returned | No new read or poll | Preserve historical exception |
| Valid final-record conversion | None, then repeated None | Exhausted cursor remains valid | Positive U10 companion |
| Wrong integration key/order/score under fixed input | Assertion fails with generation/query/expected/observed diagnostics | Existing temporary-root RAII remains; preserve sufficient counterexample | Stop affected F1 acceptance if not proven transcription error |
| Existing I05 over-limit merge | Exact `LimitExceeded { limit: 65_536, requested: 114_059 }` and unchanged generation2 | Retained existing production-path test | Regression, not a new F1 scenario |
| Missing tool/service/CI access | Explicit BLOCKED/NOT VERIFIED | Continue independent authorized work | No PASS by inference |
| New timeout/retry/concurrency/crash mechanism | Not applicable: F1 adds none | Existing applicable regression suites retained | No new stress campaign |

Use the guide's failure taxonomy: introduced regression; feature implementation defect (including test-authoring error); deterministic pre-existing failure demonstrated on the relevant baseline; evidenced nondeterminism/flakiness; environment/harness failure. “Unrelated” is not a classification. Preserve every unresolved failure; a later green retry does not erase it.

## 10. Ordered implementation sequence

Execute the sequence continuously after authorization. No stage boundary requires routine approval.

| Stage | Exact work | Completion evidence |
| --- | --- | --- |
| P0 — Verify and resume | §6 preflight, source classification, protected-state check, baseline health, invariant/counterexample ledger | Correct source/branch; existing work classified; C0/C1 evidence |
| P1 — U05 and U15 | Add independent in-range zero-frequency case; replace two compact cost blocks with the four-row table; retain long/rejection blocks | §7.2/§7.5 assertions pass |
| P2 — U08 and U10 | Complete fixed family/state matrix, raw corrupt-intervening cases, and six final-record conversion cases | §7.3/§7.4 assertions pass |
| P3 — I05 | Add exact helper; replace generation2 and fresh-generation3 query blocks; retain lifecycle and saved PIT checks | Before/after independent oracles and child assertions pass |
| P4 — I06 | Add MatchAll helper and five specified generation/PIT calls; preserve rust oracles and immutable objects | Exact eight-/ten-key membership across lifecycle |
| P5 — Audit assertions and draft report | Check every finding-to-assertion mapping, source scope and counterexample discriminator; insert current-status notice and append F1 draft | C2/C3 source coverage complete; report says IN_PROGRESS until evidence exists |
| P6 — Final local QA | Run §11.3 after the final test change; preserve real failures and actual values | C4 |
| P7 — Commit, ordinary push, CI | Commit approved test/docs changes, push existing branch, keep/update draft PR, verify normal five-job CI and named child/R01 execution | C5; true source/merge provenance |
| P8 — Evidence closeout | Finalize §16 report, protected diff, final identities and current PR body; apply documentation-only evidence rule if needed | C6; READY only if all non-maintainer gates pass |

Targeted commands during P1–P4 diagnose the newly changed contract. Once a final full suite covers unchanged tests, do not rerun the same targeted command solely for a second green log. Do not add optional optimization/stress work after the prescribed contracts are established.

Do not edit other A5 unit groups, historical A2/A3 tests, fixture reconstruction helpers, I02, the I03 launcher, 128/delete/stored-only/no-op/limit siblings, or remote tests. The existing shared post-compaction helper intentionally strengthens its existing callers; preserve their fixture construction and call sequence.

## 11. Required execution and validation

### 11.1 Baseline: three touched suites

Run from the repository root before test edits:

~~~bash
cargo +1.98.1 test -p quervant-core --lib segment::tests::a5_ -- --nocapture
cargo +1.98.1 test -p quervant-core --test pr15i_d2a_scoring_contract
cargo +1.98.1 test -p quervant-core --test pr07_compatibility
~~~

The first filter selects the existing sixteen segment A5 unit groups. The other two run their complete test binaries. Require actual positive selected counts and named test success. The scoring parent must execute its child; preserve the nested child success output. Do not launch the ignored child directly without the fixture root supplied by its parent.

Baseline success establishes environment health, not completion of the assertions that do not yet exist. Record exact command output counts; do not copy old totals as new evidence.

### 11.2 Focused acceptance during edits

Use these exact filters as needed for the changed step:

~~~bash
cargo +1.98.1 test -p quervant-core --lib segment::tests::a5_u05_ -- --nocapture
cargo +1.98.1 test -p quervant-core --lib segment::tests::a5_u08_ -- --nocapture
cargo +1.98.1 test -p quervant-core --lib segment::tests::a5_u10_ -- --nocapture
cargo +1.98.1 test -p quervant-core --lib segment::tests::a5_u15_ -- --nocapture
cargo +1.98.1 test -p quervant-core --test pr15i_d2a_scoring_contract a5_ -- --nocapture
cargo +1.98.1 test -p quervant-core --test pr07_compatibility a5_i06_legacy_adaptive_commit_reopen_and_compact -- --exact --nocapture
~~~

Unit prefixes are substring filters, not exact full names; do not add `--exact` to them. The I06 name is the existing top-level exact name. If an invocation selects zero tests, mark that invocation invalid and correct it using the actual `-- --list` output under F1-D09. Do not rename tests or drop `--ignored` requirements to manufacture success.

The existing A2/A3, codec/golden, PR7 compatibility/properties, PR8, merge/mutation/visibility/recovery/property, remote deterministic and other workspace suites remain mandatory regression coverage through §11.3. No separate repetition of each is needed once the full final workspace runs contain them.

### 11.3 Mandatory final local QA after the last test change

This is a code-bearing task even though production files are unchanged. `AGENTS.md` requires local verification; CI is additional evidence. Retain the approved A5 final matrix:

~~~bash
cargo +1.98.1 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
git diff --check
~~~

Capture real exit statuses; if logging through a pipe, enable `pipefail` or separately preserve the command's status. Record actual Rust/Cargo versions, source/test tree identity, command, PASS/FAIL/BLOCKED, actual counts, coverage percentages, and log location. Keep transient logs outside the tracked file allowlist.

Run Cargo commands sequentially when they share build directories. Do not overlap coverage instrumentation and ordinary builds. Require **at least 85% production Rust workspace line coverage in both coverage invocations**, with only existing reviewed scope/exclusions. No lowered floor, new exclusion, ignored test, lint suppression, score tolerance, or selective per-file substitute is permitted.

The benchmark command is compile-only. Inherited normal test-mode targets may run as part of the prescribed workspace commands; no Criterion measurement, benchmark stage/prepare/run, profiling, full benchmark corpus build, new configuration, or result acquisition is authorized.

Run this matrix once on the final test source. At its start, record the three Git blob hashes below in this path order; rerun this command after QA and before committing, and require equality with the recorded tested values:

~~~bash
git hash-object crates/quervant-core/src/segment/tests.rs \
  crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs \
  crates/quervant-core/tests/pr07_compatibility.rs
~~~

Stage only the five permitted paths after the approved edits are ready, then require the staged test bytes to match the working-tree bytes that actually passed:

~~~bash
git add -- crates/quervant-core/src/segment/tests.rs \
  crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs \
  crates/quervant-core/tests/pr07_compatibility.rs \
  docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md \
  docs/pr-artifacts/perf-06-a/PERF06A5F1_DETAILED_PLAN.md
git diff --exit-code -- crates/quervant-core/src/segment/tests.rs \
  crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs \
  crates/quervant-core/tests/pr07_compatibility.rs
git diff --cached --check
~~~

After the ordinary source/test commit, require these committed blob IDs to equal the recorded tested values in the same order:

~~~bash
git rev-parse HEAD:crates/quervant-core/src/segment/tests.rs \
  HEAD:crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs \
  HEAD:crates/quervant-core/tests/pr07_compatibility.rs
~~~

This binds local execution to the committed tests; a path-scope check alone is insufficient. The protected-file guard must also pass for both working tree and index. A mismatch uses F1-D20 and is never repaired by substituting the new hash into an old PASS record.

A subsequent test edit invalidates affected evidence, including workspace coverage, and requires the appropriate final rerun. A report-only change follows §11.6. Do not rerun unaffected checks for presentation alone.

### 11.4 Real local and remote topology

**Local integration:** use existing real `FsDirectory` temporary roots and actual public writer/commit/compact/open/search paths. I03 launches `current_exe()` through the existing parent; its environment variable remains `QUERVANT_PERF06_A5_REOPEN_ROOT`. No fake scorer, reader, Directory or production-response oracle replaces these tests.

**Remote regression:** the existing hosted `rustfs` job owns the pinned service:

| Item | Fixed value |
| --- | --- |
| Image | `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Endpoint | `http://127.0.0.1:9000` |
| Region | `us-east-1` |
| Disposable CI bucket | `quervant-pr13-ci` |
| Adapter | Existing production `S3ObjectStore` |
| Test concurrency | Existing `--test-threads=1` |
| Prefixes/credentials | Existing harness-generated unique prefixes and environment inputs; no secrets in report |
| Repetitions | Existing CI rules, including its already prescribed mutation/race repeats; no new sampling campaign |

If that authorized pinned local service is already available, the existing R01 targeted invocation remains:

~~~bash
cargo +1.98.1 test -p quervant-core --all-features --test pr13_remote \
  real::a5_r01_adaptive_postings_rustfs_cold_reopen \
  -- --ignored --exact --test-threads=1
~~~

If it is absent, record local remote execution as unavailable and continue local work. The original approved A5 boundary allows actual hosted execution to satisfy this provider gate. Do not start another service, proxy, container or cloud bucket just to fill the checklist. Do not invoke a guaranteed-to-fail missing-credential command merely to produce another failure log.

The existing hosted suite is:

~~~bash
cargo test -p quervant-core --all-features --test pr13_remote \
  -- --ignored --test-threads=1
~~~

Verify the named `real::a5_r01_adaptive_postings_rustfs_cold_reopen ... ok` line for revised source, not only a green generic workspace run. An ordinary output line marking the ignored child/R01 declaration as ignored is expected in non-owning test runs and is not acceptance; retain the separate actual execution evidence.

### 11.5 CI and checked-source provenance

All five existing jobs must succeed on a candidate that contains the final corrected tests:

- `rust`
- `msrv`
- `rustfs`
- `benchmark-adapter-contract`
- `python-benchmark-framework`

No workflow/trigger change is allowed. Normal PR push triggers the current CI. Do not add a branch push trigger, invoke duplicate equivalent workflows, or rerun until green. Existing adapter/framework jobs are synthetic/unit/compile/config checks and remain required.

For every run, record workflow run ID/URL, PR head SHA, actual checkout SHA (GitHub may test its PR merge ref), merge parents/base where relevant, job URLs and conclusions. Verify the actual checked test/production blobs contain the corrected source. Do not describe a PR merge checkout as a literal checkout of the head commit. Unexplained merge/source drift uses F1-D06.

Verify actual revised-source execution of the I03 child and R01. Historic run45336474554 proves the original child and remote tests ran; it does not prove the new assertions ran.

If CI is pending, cancelled or inaccessible, complete independent local work/report/ordinary draft delivery. Keep C5 blocked and use the correct final status. Observe normal CI while useful work remains; do not busy-poll indefinitely or repeatedly trigger equivalent runs.

### 11.6 Evidence commits without circular reruns

Prefer one source/test commit followed by a report-only evidence commit if needed. Record the exact tested source commit and final report head separately. The report can name its evidence parent; the PR body/final handoff can name the final report commit, avoiding a self-referential commit-SHA loop.

Before reusing local QA for a later documentation-only commit, require an empty diff over every tested input. Because this fixup's allowlist is exact, a strong sufficient proof is that the full commit-to-commit filename delta contains only:

- `docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md`
- `docs/pr-artifacts/perf-06-a/PERF06A5F1_DETAILED_PLAN.md`, only if adding the identical approved plan copy

There must be no test/source/Cargo/toolchain/workflow/support/benchmark-input delta. Verify this with `git diff --name-status <tested-sha> <final-sha> --` and the scoped source checks. Run document/whitespace and scope checks; full local Rust QA does not need repetition solely to embed its evidence.

Record final-head CI as actually observed. An earlier source-identical run remains identified as that earlier run, never relabelled as final-head execution. While mandatory CI on the final report head is pending, the current overall disposition in the PR body and handoff is `PERF06_A5_F1_VERIFICATION_BLOCKED`, even when the tested source's gates have passed. After final-head checks succeed, update the PR body/handoff to the ready disposition without another repository commit solely to restate that result.

The committed report is a dated evidence snapshot for its explicitly named tested source; it must state that its own later final-head CI/delivery observation is recorded in the PR body. Label any source-qualified readiness accordingly. It must not assert a future final-head PASS. This separates the immutable evidence record from the current delivery status and prevents a self-referential report-commit loop.

## 12. Exact documentation correction

### 12.1 Preserve the historical record

Update the existing `PERF06A5_EXECUTION_REPORT.md` only. Keep its original source identities, command outcomes/counts, coverage values, CI URLs, R01 evidence, structural size table, projected full-corpus sizes, failure history, protected-file statements and A6 limitations as historical evidence at their recorded revisions.

At the top:

1. Replace the unqualified current `READY_FOR_INDEPENDENT_REVIEW — G0–G8 pass` status paragraph with the current F1 status and a link to §16.
2. Add this substance explicitly:

> The original execution evidence below is retained at its recorded source revisions. Independent review found omitted required U05/U08/U10/U15 and I05/I06 assertions. The original G3/G4 completeness claims and corresponding G8 reporting claim are superseded by the F1 gate ledger in §16; the original command PASS results remain historical successes.

3. Rename `## 1. Disposition` to `## 1. Original execution disposition — superseded by the F1 correction ledger`.
4. Preserve the remainder of original §§1–15 verbatim. The new notice makes their former present-tense completeness claims historical; do not silently rewrite evidence.

Do not alter the original A5 plan, architecture, roadmap or registers. Their pending-independent-review state remains appropriate. No DONE, ACCEPTED, A6-qualified or B1-unblocked marker is authorized.

### 12.2 Append exactly one current F1 section

Append:

~~~markdown
## 16. PERF-06-A5-F1 — Independent-review corrections
~~~

Use these fixed subsections and contents:

| Subsection | Required content |
| --- | --- |
| 16.1 Current disposition | C0–C7 table, original G3/G4/G8 mapping, current status, G9 still maintainer-owned |
| 16.2 Authorization and source | Reviewed baseline, START_SHA, fresh main, branch, tested source, final head/remote identity when available, plan identity |
| 16.3 Finding-to-assertion trace | F1-R01…R05 to actual existing test functions and the added assertions |
| 16.4 Unit acceptance | U05 exact error; U08 counts/markers/boundaries/corrupt fixtures; U10 six outcomes; U15 four literal count/capacity rows and retained long/rejection results |
| 16.5 Local integration acceptance | I05 before/after and actual child execution; independent prefixes/membership/maps; I06 five snapshot checks; preserved PIT/immutable-object evidence |
| 16.6 QA and real-provider evidence | Every required local command with real counts/coverage/exit status; toolchains; actual topology; current CI head/merge/run/job identity; named R01 result |
| 16.7 Adversarial and failure ledger | Counterexamples excluded by each assertion; actual failures and classifications; no fabricated production-red claim |
| 16.8 Decision register | Applied matrix IDs, triggers, actions, verification, deferred gates and owners |
| 16.9 Scope and evidence integrity | Five-file incremental diff; zero production delta; original plan/fixtures/A4/benchmark artifacts unchanged; tested-to-final delta proof |
| 16.10 Residuals and handoff | G9 open; D39 genuine E+F deferred to A6; size/performance unmeasured; B1 remains dependent |

State that the old I05 limited-result loop checked only per-returned-key bits, and the corrected test now asserts actual selected prefixes/order. This prevents the retained historical wording from being read as current completeness evidence.

Do not infer newly executed subcase counts from the number of top-level tests. The same sixteen unit groups and existing integration names can contain more assertions without a changed function count. Report actual command totals separately from this plan's subcase inventory.

## 13. Acceptance gates and status derivation

| Gate | Required evidence | Owner / closure |
| --- | --- | --- |
| C0 — Source and authority | Verified repo/branch/base/head, compatible source/policy pins, protected-state guard, conforming resume classification | Agent |
| C1 — Correctness preparation | Invariant/counterexample matrix, exact APIs/fixtures, three baseline commands with classified outcomes | Agent; an unresolved mandatory baseline failure prevents ready status |
| C2 — Unit correction | Every §7 case actually passes on final tests; U05/U08/U10/U15 and retained relevant suites | Agent; compilation or source inspection alone is insufficient |
| C3 — Local integration correction | Exact I05/I06 generation oracles, actual child reopen, preserved lifecycle/limit/PIT/fixture checks pass | Agent; real FsDirectory/public path |
| C4 — Final local QA | All §11.3 commands passed after final test change; both coverage forms ≥85%; exact source evidence | Agent |
| C5 — Hosted regression and provider | Five existing jobs succeeded on corrected source, checked checkout provenance, actual R01 and child evidence | Agent; pending/inaccessible is BLOCKED |
| C6 — Reporting and delivery | Accurate report/PR body, complete finding trace, no protected delta, ordinary push/local-remote identity, final CI truthfully stated | Agent |
| C7 — Independent acceptance | Independent reviewer/maintainer verifies the F1 correction and resolves A5 G9 | Maintainer; executing agent cannot close |

Original A5 G3 requires C2; G4 requires C3; G8 requires C6 together with the complete current evidence. Other original implementation/regression evidence remains historical and is corroborated by the revised candidate's checks. Do not turn the existence of this plan into gate completion.

| Condition | Permitted status |
| --- | --- |
| Authorized correction in progress | `PERF06_A5_F1_IN_PROGRESS` |
| Implementation assertions completed but required local/CI/provider evidence missing | `PERF06_A5_F1_VERIFICATION_BLOCKED` |
| Source/contract conflict or unexpected production counterexample prevents affected work | `PERF06_A5_F1_STOP_DECISION_REQUIRED` |
| C0–C6 pass; C7/A5 G9 remains open | `PERF06_A5_F1_READY_FOR_INDEPENDENT_REVIEW` |
| Maintainer later accepts | Maintainer records acceptance; agent does not self-promote |

If a blocker affects only one part, report that scope and finish every independent task. A stopped case cannot be marked PASS because unrelated gates are green.

## 14. Preauthorized decisions and exception handling

All rows require observable evidence. “AUTO” means AUTO-RESOLVE and continue. “DEFER” means DEFER AND CONTINUE with affected gates open. “STOP” means HARD STOP for affected work. If multiple rows apply, use the most restrictive. The owner column names who may resolve an outstanding decision; it is not a request to seek permission for an AUTO action.

| ID | Observable trigger / source check | Category | Exact action | Prohibited response | Required evidence | Affected work/gate; owner |
| --- | --- | --- | --- | --- | --- | --- |
| F1-D01 | Correct clean branch at reviewed source; pins and PR state agree | AUTO | Execute P0→P8 continuously | Ask at each successful checkpoint | Refs/status/pins | All; agent |
| F1-D02 | Clean checkout is on another branch and the named A5 target is verified/available, or the selected clean target is only behind its verified remote; reviewed baseline is ancestor | AUTO | Select the existing local target or create its matching local tracking branch as §6.1 specifies; fast-forward only if behind; repeat source/scope checks | Choose another implementation branch/PR, override another active worktree, merge commit, rebase, reset or force push | Clean status, target/PR identity, before/after SHAs and ancestry | P0/C0; agent |
| F1-D03 | Existing identifiable F1 work is confined to five paths and matches this plan | AUTO | Classify each step, preserve conforming work, implement/verify only remainder | Overwrite work or trust a status without source/evidence | Diff, per-step state, evidence identity | P0–P8; agent |
| F1-D04 | Wrong repository or unavailable/unverified target branch; target held by another active worktree; unrelated dirty changes; branch divergence; PR closed/merged/non-draft | STOP synchronization/publication and affected writes | Preserve work, report exact state; independent read-only review may continue; a clean other-branch checkout alone is D02, not this trigger | Reset/stash/clean user edits, override worktree ownership, choose another PR/branch or merge | Status/refs/worktree/PR observation | C0/C6; maintainer |
| F1-D05 | Main advanced only in unrelated documentation: old main is ancestor and all changed paths are outside crates/tests/benchmarks/Cargo/toolchain/workflows/AGENTS and all authoritative docs/plans listed here | AUTO | Record exact changed paths; continue same A5 branch without rebase | Treat unknown code/policy drift as harmless | Compare metadata and path/blob proof; relevant CI checkout still matches | C0/C5; agent |
| F1-D06 | Production/test/support/policy/authoritative-plan drift outside conforming F1 edits, or unexplained merge checkout differs in relevant tested inputs | STOP affected implementation/acceptance | Preserve source evidence; request bounded reconciliation | Rebase, reinterpret contract, transplant snippets onto unknown APIs | Exact path/blob/merge-parent diff | C0/C5; maintainer |
| F1-D07 | TESTING.md has known committed marker text with blob `91c8643…` and no unmerged index entries | AUTO | Record known preexisting doc defect and continue unchanged | Repair unrelated documentation or call it an active merge conflict | Blob and `git ls-files -u` | P0/C0; agent |
| F1-D08 | Compile/borrow/import/format/lint failure is confined to prescribed test code and an equivalent repair preserves all inputs/oracles/assertions | AUTO | Correct syntax, type annotation, imports or formatting; rerun affected checks | New API/abstraction, lint suppression, changed expected behavior | Diagnostic and bounded diff | C2–C4; agent |
| F1-D09 | Filter selects zero tests or child helper is invoked without the parent fixture | AUTO | Mark invocation invalid; use actual listed known test name or prescribed parent; require positive execution | Count zero-run exit0 or ignored declaration as PASS; rename tests to fit filter | Command/list/output/actual names | C1–C5; agent |
| F1-D10 | Correctly transcribed new assertion fails against unchanged production and no proven test transcription error explains it | STOP affected correction/acceptance | Preserve exact fixture/query/generation/expected/observed/error and source; finish unrelated tests/docs | Production edit under old D13, relaxed error/bits/order, changed corpus or skipped test | Concrete counterexample and scope | C2/C3; maintainer amendment |
| F1-D11 | A needed edit is outside the five paths or outside the bounded changes inside a permitted file | STOP that edit | Report file/symbol and necessity; continue independent authorized work | Add helper module/dependency/production hook or widen scope silently | Proposed delta and dependency | Applicable gate; maintainer |
| F1-D12 | Plan literals, source API, original semantic contract or fixed statistics contradict each other | STOP affected test | Report exact contradiction and smallest amendment | Retune expected values, choose another fixture/grammar or approximate bits | Source/input/formula proof | C1–C3; maintainer |
| F1-D13 | A mandatory baseline test fails | DEFER dependent acceptance | Preserve first failure, classify with baseline/environment proof; implement independent known corrections if safe | Call it unrelated/preexisting without proof or erase failure by retry | Baseline SHA/command/output/classification | C1 plus dependent gates; agent/maintainer |
| F1-D14 | An unexplained pass/fail alternation or intermittent error occurs | DEFER affected gate | Preserve all outcomes; run only bounded diagnostics that distinguish a concrete cause; otherwise report nondeterminism unqualified | Retry until green or label flaky from one failure | Reproduction/environment/outcomes | C1–C5; maintainer if unresolved |
| F1-D15 | Prescribed toolchain/component/tool unavailable | DEFER dependent execution | Use established supported installation workflow without source/dependency changes; if unavailable, record exact blocker and finish other work | Substitute toolchain/version, change Cargo/toolchain files, fabricate output | Tool/version/setup result | C1–C4; environment owner |
| F1-D16 | Authorized local pinned RustFS topology absent | DEFER local remote invocation | Continue local work and use normal hosted pinned rustfs execution for provider evidence, as original A5 permits | Fake provider, new service/cloud bucket, local PASS claim | Availability observation and actual hosted R01 | C5; hosted harness owner |
| F1-D17 | Required CI pending/cancelled/inaccessible | DEFER hosted gate | Complete local work and accurate draft delivery; observe normally while useful work remains | Invent PASS, busy-poll indefinitely, duplicate equivalent runs | Run/job status or access error | C5/C6; CI/environment owner |
| F1-D18 | Required CI job fails | DEFER/STOP according to cause | Apply failure taxonomy; fix only proven allowed test transcription defects; unexplained runtime failure uses D10 | Skip job, weaken workflow or carry old CI as current | Failing step/log/source | C5; agent or maintainer |
| F1-D19 | Coverage below85% or required correction case unexecuted | STOP acceptance; allowed missing-case work may continue | Add only omitted prescribed cases or fix their invocation; rerun affected coverage; otherwise report blocker | New exclusions/floor, arbitrary unrelated test expansion, percentage-only waiver | Actual scope/percentage/case trace | C2–C5; maintainer if unresolved |
| F1-D20 | Any test/source input changes after final QA | AUTO | Invalidate affected evidence; rerun required checks including workspace coverage for test changes | Keep stale PASS or reuse an old tested SHA | Delta and new command ledger | C2–C5; agent |
| F1-D21 | Later delta is report/identical-plan only and all tested inputs are unchanged | AUTO | Reuse local QA with both identities; run doc/diff/scope checks; describe final CI truthfully | Claim old run executed new head; full QA solely for a self-referential report SHA | Full filename delta and tested-input proof | C4–C6; agent |
| F1-D22 | Push or PR update access fails | DEFER external delivery | Finish reviewable local commits/report and exact PR text; record access failure | New remote, force push, claim remote identity not observed | Local SHA, attempted action, error | C6; repository owner |
| F1-D23 | Protected path changed accidentally by this agent, with exact provenance and no preexisting user edit | AUTO for restoration only | Preserve diagnostic diff; restore only proven unintended bytes from the pinned baseline; verify full guard again | Silent evidence rewrite, whole-tree reset, restoration of uncertain edits | Causative diff, before/after blob proof | C0/C6; agent; uncertainty→STOP |
| F1-D24 | Disk usage≥60% and broad cleanup could remove protected/unknown state | DEFER housekeeping under original A5 D35 | Record usage; use normal cleanup only for verified task-owned disposable roots; keep evidence/caches; report any remaining resource block | Blind target purge, container reset, benchmark cache/result or user-data deletion | Usage/ownership/scope | Housekeeping; C4 if exhausted; environment owner |
| F1-D25 | All prescribed non-maintainer gates complete with no concrete remaining risk | AUTO | Stop optional testing; finalize evidence, ordinary push and existing draft PR update | Open-ended stress/optimization or additional acquisition | Complete C0–C6 ledger | P8/C6; agent |
| F1-D26 | Proposed timing/profiling/full-corpus build, A4 rerun, A6/B1 work, merge/release, new fixture policy or production redesign | STOP proposed action | Keep F1 scope; record deferred owner/action if relevant | Infer authority from bench --no-run or previous implementation permission | Proposed action and scope conflict | Out-of-scope work; maintainer |
| F1-D27 | Actual unmerged index entries, unexpected conflict markers, or unknown changed fixture/plan identity | STOP affected writes/publication | Preserve state and report exact conflict/provenance | Auto-resolve source conflict or regenerate fixture | Index/blob/diff evidence | C0/C6; maintainer |
| F1-D28 | Any unlisted situation, contradictory instructions, new material residual risk, or uncertainty not precisely covered above | STOP affected work | Freeze that action/gate, report concrete evidence and smallest required amendment; continue only provably independent tasks | Improvise, generalize AUTO, silently waive a requirement | Counterexample/dependency map/decision request | All affected gates; maintainer |

For F1-D05, authoritative documents include `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/TESTING.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/BENCHMARKING*.md` and both PERF-06 series registers/plans/reports. If the changed main paths cannot be proven irrelevant under this explicit boundary, use D06/D28.

## 15. PR publication and ready-to-use description

Use the existing branch and draft PR124. No new PR, title redesign, milestone change, review comment, merge, or external message is required. Update the PR body after the actual gate status is known. Write multiline body text to a file and use the repository's structured tool or `gh pr edit 124 --body-file <path>`; do not put multiline Markdown or shell substitutions into an interpolated command string.

The following is a template. Replace bracketed evidence fields with observed values; do not leave placeholders in the submitted body:

~~~markdown
## Why

Independent review of PERF-06-A5 found missing required assertions in the unit
cursor/cost tests and the real compaction/legacy compatibility tests. The existing
commands passed, but those assertions did not fully establish the original plan's
G3/G4 contracts.

## Changes

- Complete U05's in-range zero-frequency error check.
- Complete U08's singleton/short/long cursor-state checks and corrupt-intervening
  advance assertions.
- Complete U10's conversion-after-final-record verification cases.
- Cover all four compact encoder modes with exact work/capacity witnesses.
- Check I05's input-derived full membership, K10/K100 prefixes and exact alpha
  score bits before/after compaction and through the existing process reopen.
- Check I06's full legacy/adaptive key sets across append, compaction and held PITs.
- Correct the current execution-report status and append the F1 evidence ledger.

Production files are unchanged from bb0d6c17523eab38a61d4d1976469124688f42a9.

## Validation

Status: [actual F1 disposition]; A5 G9 remains open.
Tested source: [full SHA].
Final head: [full SHA, stated separately if report-only].
Local QA: [actual command-summary/counts and both coverage values].
CI: [run URLs, head/checkout identity and actual five-job status].
Real boundaries: [actual FsDirectory/child/RustFS R01 evidence].
Unresolved failures or blocked gates: [explicit list, or none if true].

Plan: docs/pr-artifacts/perf-06-a/PERF06A5F1_DETAILED_PLAN.md
Report: docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md, §16.

A4's historical targets-not-met disposition remains unchanged. Full-corpus size,
latency, writer cost/RSS and genuine complete E+F lifecycle qualification remain
A6 responsibilities. B1 remains dependent on A6 and maintainer disposition.
~~~

Before final delivery, verify local HEAD equals the observed remote branch head, the intended worktree is clean, the incremental allowlist still passes, and PR124 is still draft/unmerged. If delivery is blocked, preserve the concrete local result and report that state; do not ask permission for ordinary already-authorized publication.

## 16. Residual risks and next-stage ownership

| Property not newly proven by F1 | Disposition |
| --- | --- |
| Actual 10K/100K index bytes | A5's arithmetic projections remain explicitly NOT MEASURED; A6 measures real index footprint. |
| Warm query gain, writer CPU/cost, RSS, reopen improvement | No new timing/memory acquisition; A6 defines and executes its qualification. Smaller bytes do not themselves establish latency gains. |
| Genuine A3-produced complete E index appended/compacted by A5 | Original D39 bounded gap remains; A6 must design and execute genuine E+F lifecycle compatibility. Do not fabricate a fixture or rewrite state pointers. |
| Old executable rejecting F | Existing source-derived conclusion only; no new old-binary claim. |
| Real allocator exhaustion | Existing fallible reservation/admission and arithmetic tests; no OOM injection. |
| 32-bit execution | Existing checked conversions; ordinary hosted evidence is 64-bit. No new platform claim. |
| Future test-launcher drift | Optional I03 sentinel/filter robustness remains outside F1; current and revised actual child execution are verified from logs. |
| Production defect exposed by a stronger assertion | Not an accepted residual. Stop affected F1 acceptance and seek a bounded amendment. |

Retain A1–A3 and the selected A5 design. After F1 passes and the maintainer resolves G9, A6 owns consolidated compatibility, actual size and performance qualification. F1 does not promote B1 or reinterpret A4's recorded primary targets.

## 17. Reviewer checklist

- [ ] Current branch/head/base and source-policy identities agree with the execution record.
- [ ] Exactly the three bounded test files, original report and new F1 plan changed incrementally.
- [ ] Every production file and protected original plan/fixture/benchmark artifact is unchanged.
- [ ] U05 reaches an in-range zero-frequency error and asserts its exact variant independently.
- [ ] U08 covers the fixed singleton/short/long read/cancellation/EOF/cached-advance states through new_adaptive.
- [ ] Compact and long corrupt-intervening advance cases fail on the shared occurrence error before target.
- [ ] U10 converts after the final data record and before EOF, with valid companions and all specified pending-error cases.
- [ ] U15 covers four compact modes with literal widths6/16/11/41, lengths8/18/13/43, one buffer and unchanged capacity.
- [ ] I05 computes expectations from input/frozen oracle, checks full vectors and both K prefixes before and after compaction, and retains exact PIT maps.
- [ ] I05 does not sort observed ordered results or use physical IDs as an oracle.
- [ ] I06 checks complete eight-/ten-key vectors on all five specified snapshots, retaining multiplicity.
- [ ] No duplicate index build, reference production query oracle, temporary runtime bug or new framework was introduced.
- [ ] The real child executed the strengthened shared assertions; an ignored declaration/zero-test run was not counted.
- [ ] Final local QA, both ≥85% coverage results and all five actual CI jobs qualify corrected source.
- [ ] Real pinned RustFS R01 executed; local absence, if any, is disclosed accurately.
- [ ] Original evidence is preserved and original completeness claims explicitly superseded.
- [ ] Current report/PR identities, final CI state, unresolved failures and decision register are truthful.
- [ ] C7/A5 G9 remains independent; A6/D39/B1 boundaries and A4 evidence are unchanged.
- [ ] Optional testing ended once required risks and gates were resolved.

## 18. Authoring basis and source references

This plan follows the repository authoring guide's in-progress classification (§3A), execution-evidence discipline (§3B–3D), invariant/adversarial/state analysis (§3E), continuous authorization (§3F), mandatory decision matrix (§27), narrow-fixup rule (§37), and reviewer/acceptance checklist. The complete original A5 design remains the semantic authority; this file supplies the precise missing-test delta and stricter F1 edit boundary.

Planning checked the fresh main/PR metadata and immutable source files, the guide/policy/workflow blobs, the existing helper APIs, the actual reviewed execution report and the prior review's CI evidence. Separate reviews checked the unit design, integration design and guide/QA/decision rules.

Authoring validation checked Markdown fence balance, all28 decision rows and all12 invariant rows, six U10 framing literals, I05's fixed statistics and all four U15 arithmetic rows. The actual scope-guard snippet was executed in a disposable local Git fixture: clean and allowed edits passed; staged protected edits and unapproved untracked files were rejected; the separate index/working-tree check rejected staged test bytes that differed from the tested working tree. No repository production source was modified for these checks.

The plan's Rust snippets were source-reviewed. The planning environment has no Rust toolchain; no compilation or execution of the proposed Rust correction is claimed. The authoring checks validate this document, and do not close correction gates. The executing agent must produce §11's actual evidence.

Primary repository references:

1. [PR124](https://github.com/yduchesne/quervant/pull/124) and [current main base](https://github.com/yduchesne/quervant/tree/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d).
2. [Detailed PR Plan Authoring Guide at the inspected revision](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md).
3. [AGENTS.md](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/AGENTS.md), [TESTING.md](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/docs/TESTING.md), and [CI workflow](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/.github/workflows/ci.yml).
4. [Original approved A5 plan](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/docs/pr-artifacts/perf-06-a/PERF06A5_DETAILED_PLAN.md).
5. [Reviewed execution report](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md).
6. [Unit tests and raw fixture helpers](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/crates/quervant-core/src/segment/tests.rs).
7. [I03/I05 scoring integration source](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs).
8. [I06 legacy compatibility source](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/crates/quervant-core/tests/pr07_compatibility.rs).
9. [Production postings implementation being preserved](https://github.com/yduchesne/quervant/blob/bb0d6c17523eab38a61d4d1976469124688f42a9/crates/quervant-core/src/segment/postings.rs).
10. [Original tested-source CI](https://github.com/yduchesne/quervant/actions/runs/45333872681), [reviewed-head CI](https://github.com/yduchesne/quervant/actions/runs/45336474554), [actual reviewed RustFS job](https://github.com/yduchesne/quervant/actions/runs/45336474554/job/138249633376), and [actual reviewed Rust job](https://github.com/yduchesne/quervant/actions/runs/45336474554/job/138249633261).

## 19. Final coding-agent instruction

Execute this approved correction continuously on the existing draft PR. Add the exact assertions, reuse the verified fixtures/helpers, preserve production bytes and historical evidence, run the prescribed local and hosted gates, and deliver the corrected report with precise source identities.

A successful checkpoint means continue. A missing external dependency means record its gate and complete independent work. A correctly transcribed unexpected production result, scope conflict or unlisted condition means stop the affected work and provide the concrete counterexample and smallest required amendment. Never improvise an oracle, alter a semantic expectation, weaken a gate, or self-approve A5 acceptance.
