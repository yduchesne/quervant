# PERF-06-C2-F1-A2 — Isolate the certificate test counter and finish verifiable delivery

**Document type:** Detailed execution contract for a low-reasoning coding agent.

**Repository / branch / existing PR:** `yduchesne/quervant` / `dev/perf06-c2` / [#131](https://github.com/yduchesne/quervant/pull/131).

**Prepared:** 2026-11-26. **Scope:** a test-only counter repair and the remaining A1 evidence/delivery corrections. **Performance work:** C3/C4 remain unstarted.

## 0. Binding execution contract

Execute this document when the user authorizes its execution. Do not implement it merely because it was supplied for review. Once execution is authorized, that authorization covers the complete prescribed implementation, local verification, evidence commits, normal push to the existing branch, and update of the existing PR description. It does not approve a whitespace exception, waive a failing test, merge the PR, change its readiness flag, or authorize new architecture.

> **Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

The coding agent implements a fixed design. The agent may fill factual report fields with observations, execute named commands, apply the exact decision matrix, and make formatting-only adjustments permitted by that matrix. It may not choose a different counter mechanism, redesign C2 acceptance, replace real reader operations with mocked increments, weaken assertions, expand mutation regions, or infer approval from silence. Any case outside the matrix stops the affected work under B32.

**The remaining human decision is concrete:** whether to accept exactly the 81 whitespace diagnostics in the 41 unchanged historical artifact blobs listed in Appendix A. This plan proposes that bounded exception; it does not grant it. Complete every independent code, verification, evidence, and delivery task before asking for that decision. A refusal does not authorize editing the frozen artifacts: return for a separately designed historical-document policy.

Preserve the observed PR readiness value, currently `draft=false`, in either direction if a maintainer changes it. Keep the PR open and unmerged. No reviewer message, comment, review approval, merge, force push, rebase, benchmark execution, profiler, latency measurement, performance claim, workflow change, or new dependency is authorized. `cargo bench --no-run` is required compile-only QA.

## 1. Reviewed identities, primary sources, and actual starting state

### 1.1 Immutable identity record

| Name | Exact value | Meaning |
|---|---|---|
| MAIN_BASE | `bc726420cede2e26681d6e8192b45a5d0169abbf` | Fresh reviewed `main`; do not substitute the old F1 base |
| F1_START | `46ccab0a606a56a8b9034ab4db5c9c4df969d098` | Original F1 comparison identity |
| A1_START | `2bf9539cd2f53838ad1aca406ca4e67a34229ff6` | Previous amendment starting head |
| A1_TESTED | `e50e539c5ec00913bdfa0c5e0e63d434ae41c294` | Reported A1 tested source; later changes are documentation/evidence only |
| A1_FINAL_DOCS | `f373d06a25066797876ee7cb788b2633b9f2bfe0` | Intermediate A1 documentation commit, not the delivered head |
| A2_START | `cdffd5b486ce46312abf4c45c80b9d33ecbf657d` | Reviewed remote head and the only automatically admitted A2 starting source |
| A2_TESTED | To be recorded after the final prescribed source is committed | Immutable source used by all final A2 local verification |
| H | To be recorded after the last authorized repository commit and normal push | Final remote-verified delivery head; must be source-equivalent to A2_TESTED |

Original F1 plan SHA-256: `b9d11e958af2186e9a5f358153cee489a4cdafc9913ed7ea7bb6b494b091d5e7`.

A1 amendment SHA-256: `edd967b1e0c7c40cbda0e55d32af6ca0932c9c890e85e1d68e4458fb51cc1bb2`.

Record the supplied A2 file's actual SHA-256 before copying it into the checkout. Commit it verbatim at `docs/pr-artifacts/perf-06-c/PERF06C2F1_A2_CLOSEOUT_PLAN.md`. Do not replace historical plan files.

### 1.2 Primary-source basis and author verification boundary

The author reviewed fresh PR metadata, the A1 comparison and source-equivalent documentation tail, all 41 changed A1 documentation/evidence blobs, exact frozen whitespace blobs, relevant current-main source, the source tests, and the current workflow. The author did not run Rust tests: the review environment has no `cargo`. Prospective red/green outcomes below are required acceptance, not claimed executions.

| Source | Stable reference / fact used |
|---|---|
| Authoring guide | [Pinned guide](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md): correctness contract, matrix, continuous execution, real execution evidence, scoped failure classification |
| Repository instructions | [Pinned AGENTS](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/AGENTS.md) and [TESTING](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/docs/TESTING.md): local QA, coverage, real-boundary acceptance |
| A1 implementation | [unified.rs](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/crates/quervant-core/src/search/unified.rs), [integration tests](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/crates/quervant-core/tests/perf06_c2_physical.rs), and [A1 report](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/docs/pr-artifacts/perf-06-c/PERF06C2F1_A1_EXECUTION_REPORT.md) |
| Counter producer and consumer | [reader.rs](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/crates/quervant-core/src/segment/reader.rs), blob `37af8cc4091b9eef7d963c6ae4e154ad6d93e8ea`; [stored_blocks.rs](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/crates/quervant-core/src/segment/stored_blocks.rs), blob `fd2cd436217106ef91ca8e28c210153a30a0a49b`; both identical on reviewed main |
| Existing flake evidence | [A1 classification receipt](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/docs/pr-artifacts/perf-06-c/evidence/c2-f1-a1-flake-classification.txt): failure preserved, identical repeat passed, prior main failure referenced |
| Self-quoting whitespace receipt | [Exact receipt](https://github.com/yduchesne/quervant/blob/cdffd5b486ce46312abf4c45c80b9d33ecbf657d/docs/pr-artifacts/perf-06-c/evidence/c2-f1-a1-whitespace-range.txt), blob `6e30b575929d22652335f184c8fa7e3379dc52cd` |
| Current hosted regression | [Run 45884330648](https://github.com/yduchesne/quervant/actions/runs/45884330648), all five required jobs successful; current RustFS log contains 32 actual successful test summaries and zero failed summaries |

Current CI is valid A1 regression evidence. It does not replace missing A1 local coverage receipts and will be historical after the A2 test source changes. The current CI checkout is merge revision `925c8679f3566db8721ef74012cea384122cf0a7`; the older committed receipt's `8c3a9cb…` belongs to its older run. Keep these identities separate.

### 1.3 Reconciled capabilities and gates

| Capability | Starting classification | A2 treatment |
|---|---|---|
| U17 actual B3 rows and native no-eager-binding structural row | DONE + VERIFIED by source and focused A1 evidence | Freeze source; retain feature/regression execution |
| U21 four native 34+6 segment boundaries | DONE + VERIFIED | Freeze caps 86/87/99/100 and all prescribed recovery comparisons |
| U12 nine-row corruption/precedence matrix | DONE + VERIFIED | Freeze all nine rows, byte 67 mutation, guards and complete-response helpers |
| P05 six exact resource rows and I08 public failure/retry parity | DONE + VERIFIED | Freeze source and exact expectations |
| Normal-build C2 source isolation | Independently verified; required A1 reproducibility receipt PARTIAL | Supply new exact checker, immutable-source linkage, and receipt |
| Certificate test observation | PARTIAL: global counter allows cross-test interference | Implement the one prescribed TLS observation repair and regression |
| A1 local coverage percentages | Reported, delivered raw outputs missing | Recover old outputs if retained; qualify history if not; measure fresh A2 final source |
| G7 local acceptance | BLOCKED | Fix and verify the counter; keep raw whitespace failure distinct from any approved exception |
| G8 A1 hosted regression | PASS for A1 source | Require ordinary hosted regression for final A2 source |
| G9 A1 evidence and delivery | PARTIAL / BLOCKED, despite report's PASS | Correct reports, receipts, PR body and terminal-file delivery |
| G10 independent acceptance | OPEN | Maintainer-owned; never close in an execution report |

No new C2 test design is needed. A1's focused receipts now execute the formerly blocked cases. The small test-only repair here addresses a separate pre-existing QA failure whose mechanism is visible in current main. It neither changes C2 execution semantics nor turns a flaky mandatory run into a retrospective PASS.

## 2. Exact supersession, scope, reuse, and protected files

This amendment overrides A1's protected-source rule **only** for the exact counter observation and one existing regression test listed below. It replaces A1's raw-text format for **new A2 receipts** with Appendix B's lossless JSON envelope. It supersedes the assertion that G9 is already complete, the inference that only 55 whitespace diagnostics remain, and the final-source identity procedure: A2 final source is committed **before** final QA. All other inherited behavioral contracts remain binding.

### 2.1 Closed change allowlist relative to A2_START

| Path | Exact permitted change |
|---|---|
| `crates/quervant-core/src/segment/stored_blocks.rs` | Add one `Cell<u64>` in the existing `#[cfg(test)] thread_local!` block; remove the old test-only global `CERTIFICATE_BUILDS` declaration and insert the two exact helpers after the existing `decompressed_blocks()` getter, as prescribed in §6 |
| `crates/quervant-core/src/segment/reader.rs` | Replace one existing `#[cfg(test)]` increment statement; strengthen only `stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct` as prescribed |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_A2_CLOSEOUT_PLAN.md` | New file, verbatim supplied plan |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_A2_EXECUTION_REPORT.md` | New factual report with §12's fixed structure |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_A1_EXECUTION_REPORT.md` | Append one consolidated dated correction; original bytes remain exact prefix |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_EXECUTION_REPORT.md` | Append dated correction and pointer to A2; original bytes remain exact prefix |
| `docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md` | Append only a short superseding-status pointer; original bytes remain exact prefix |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | Append an A2 entry/link and gate-derived status; preserve existing bytes |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | Update only the existing C2 status note and report link; no DONE/accepted marker and no other roadmap change |
| `docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-*` | New bounded receipts, two exact helper scripts from appendices, named inventories, source comparisons, decision ledger and prepared PR body; no overwrite of any existing path |

The existing PR description may be replaced from the prepared, reviewed body under execution authorization. Updating its description is the complete metadata task; no comment, reviewer notification, readiness toggle or merge is part of it.

Everything else is frozen. In particular, all C2 source in `search/execute.rs`, `search/unified.rs`, and `tests/perf06_c2_physical.rs` stays byte-identical to A2_START. Freeze all normal-build reader/stored-block source, other segment/index/storage files, score/work/memory/plan/typed/topk/cursor/limits/error code, B1–B3 fixtures and contracts, ObjectStore/distributed code, manifests, lockfile, `.cargo`/toolchain/build configuration, `.github`, benchmarks, architecture, C1 contract, guide, AGENTS, TESTING and all historical plans/evidence. No new registered Rust test function, ignore, filter, dependency, feature or file format is permitted.

Reuse the existing `SegmentReader`, `admitted_state`, `v2_bytes(300)`, real `stored_docs_selected`, per-state certificate, `serial()` guard, and existing thread-local `DECOMPRESSED_BLOCKS`/stored-observation pattern. Do not introduce a new test framework, fake certificate builder, alternate reader, counter registry, shared global reset protocol, or extra lock.

## 3. Correctness contract, states, failure modes, and oracle

### 3.1 Invariants and positive/negative traceability

| ID | Falsifiable invariant | Positive acceptance | Negative/counterexample | Implementation / evidence |
|---|---|---|---|---|
| I01 | A thread observes only certificate builds performed synchronously on that thread | Parent first access changes its counter by exactly 1; worker independently changes its own by exactly 1 | A real worker build between the parent's reads changes parent delta by 0; the old global backend must fail this assertion | §6; T01–T04; red/green receipts |
| I02 | A certified reader does not rebuild on warm or empty selected access | Existing direct-record/block/scan/allocation assertions remain exact; final counter equals first-build counter | Extra build on any warm/empty call fails final equality | Same existing test; T02–T04 |
| I03 | The repair has no normal-build effect and changes only approved test observation | Exact byte erasure checks for two source files; all other source unchanged | Any outside-region byte change or added consumer fails G2 | Appendix C checker; before/after source blobs |
| I04 | Test observation does not weaken certificate publication, corruption validation, resource handling or fail-closed behavior | All nine existing reader tests, final workspace QA and real integration regressions pass | Do not skip the panic/concurrent/corrupt/resource siblings or replace their readers | T05–T08; G6–G8 |
| I05 | Accepted C2 semantic cases and registered names are preserved | 24 unified / 5 physical / 9 integration / broad 39; exact source equality; full focused receipts | A removed row, renamed/ignored function, changed cap/error/offset or zero-test selection fails | G3–G6; inherited matrices summarized in §8 |
| I06 | Every new PASS is attributable to actual command execution against immutable admitted source | Recorder captures full command, output bytes, exit and same source before/after | Logger success, code existence, old CI or an unrecorded dirty worktree cannot substitute | Appendix B; all command receipts |
| I07 | Historical evidence remains immutable and every new A2 artifact adds zero whitespace diagnostics | Appendix A blob equality; A2_START..H check clean; encoded raw output preserves original bytes | Trimmed history, new unapproved diagnostic or silently accepted failed check leaves G7/G9 blocked | §10; exact committed-range terminal evidence |
| I08 | Delivery truthfully reflects current gates, identities, metadata and available files | Corrected reports; verified updated PR body; attached terminal receipt; literal H verified remotely | Path-only delivery, dangling receipt link, stale F1-stop body, copied coverage totals or inferred exception fails G9 | §11–§13 |

### 3.2 State and boundary table

| State / transition | Required behavior |
|---|---|
| Counter on a fresh thread | Starts at 0 through `Cell` initialization; no shared reset required |
| Thread has prior builds | Read a baseline and assert deltas; do not assume an absolute parent count of 0 |
| Parent holds `serial()`, worker starts | Worker owns a separate real reader/state/budget; worker must not acquire `serial()` |
| Worker builds and joins before parent access | Worker delta exactly 1; parent delta exactly 0; join provides deterministic ordering |
| Parent performs first selected access | Two records, retained offset length `Some(303)`, parent build delta exactly 1 |
| Parent performs all existing warm selections and empty selection | Existing exact observations retained; no further certificate build |
| Worker panics, reader fails, or join fails | Test fails normally; no ignored error, sleep/retry, global flag reset or fallback |
| Test returns / worker exits | Thread-local observation lifetime ends naturally; existing reader/budget drops remain unchanged |
| Counter integer boundary | `u64` is test-only, incremented once per real build; no practical overflow test is required. Do not add saturation/wrapping policy or an externally settable counter. Unexpected overflow is a failing check and STOP |
| Actual source changes after final QA begins | Prior final-source receipts cannot be attributed to the new source; apply B15 before any completion claim |

### 3.3 Failure-mode and cross-component analysis

| Failure / affected component | Expected result and unchanged boundary | Required check / disposition |
|---|---|---|
| Parallel unrelated certificate initialization | Does not affect this thread's observation; real certificate state remains per-reader/per-admitted state | Deterministic sibling build in existing test, not scheduling luck |
| Global `FAIL_STORED_BLOCKS_BUILD` injection | Existing parent `serial()` guard prevents the known panic-injection test from toggling it during this test | Whole-checkout setter/lock inventory; preserve panic test and lock code |
| Worker tries the parent's serial lock | Would deadlock while parent joins | Explicitly prohibited; exact test body contains no worker lock |
| Corrupt/unselected stored bytes, malformed selection, zero metadata cap | Existing reader errors/fallback/certificate absence and resource cleanup remain unchanged | All nine `stored_blocks_reader_tests`; no production mutation |
| Concurrent first access to one shared state | Existing one-published-certificate contract remains unchanged | Existing concurrent test; do not reinterpret TLS values as a cross-thread total |
| Query limits, cancellation, selected/unselected corruption, response materialization | Existing C2 typed errors, priority, atomicity and retry semantics unchanged | U12/P05/I08 and retained unit/integration suites |
| Local filesystem / RustFS I/O, retry or publication error | No I/O algorithm is changed; existing real-boundary suites retain their error and cleanup contracts | Existing FsDirectory tests and hosted RustFS job; no new fake storage acceptance |
| Missing credentials/toolchain/CI access/receipt delivery facility | Relevant gate BLOCKED, not PASS | Continue independent authorized work; B19/B22/B29 |
| New API, codec, manifest, durability, writer, cache, remote, distributed or vector design | Inapplicable to this repair; all bytes protected | No new public API/version/migration or alternate architecture; B07/B32 |

The independent oracle for I01 is execution on two actual OS threads with an explicit join: a build on a different thread must not change the parent's observation. The red stage keeps the old global backend and therefore deterministically violates I01. The test uses real certificate initialization, so a helper that merely returns a canned value or an unused TLS counter cannot pass both worker and parent exact-one-build checks. The final warm assertion rejects a repair that counts every access instead of real initialization. Full byte comparison protects normal builds. Property/fuzz generation is unnecessary for this two-thread observation contract; do not add a dependency or stress campaign to substitute for its deterministic regression.

## 4. G0 source admission and G1 correctness preparation

Fetch `origin/main` and `origin/dev/perf06-c2` normally. Do not merge, reset, rebase, cherry-pick, clean, stash, or overwrite foreign work. Use an isolated checkout only if necessary to leave unrelated work untouched; the admitted source remains the exact pinned A2_START.

Record these actual read-only commands/results before editing:

~~~sh
git remote -v
git branch --show-current
git status --short
git rev-parse HEAD origin/main origin/dev/perf06-c2
git merge-base origin/main HEAD
git log -1 --format=fuller
git rev-parse HEAD:crates/quervant-core/src/segment/reader.rs
git rev-parse HEAD:crates/quervant-core/src/segment/stored_blocks.rs
git diff --name-status e50e539c5ec00913bdfa0c5e0e63d434ae41c294 cdffd5b486ce46312abf4c45c80b9d33ecbf657d
rg -n --glob '*.rs' 'CERTIFICATE_BUILDS|record_certificate_build|certificate_builds' crates
rg -n --glob '*.rs' 'FAIL_STORED_BLOCKS_BUILD|set_fail_stored_blocks_build|COUNTER_LOCK|test_serial' crates
rustup toolchain list
cargo +1.98.1 --version
rustc +1.98.1 --version --verbose
cargo +1.85.0 --version
rustc +1.85.0 --version --verbose
cargo +1.98.1 llvm-cov --version
python3 --version
~~~

Fresh PR metadata must identify repository/branch/#131, open/unmerged, base main at MAIN_BASE, and head A2_START. Record the readiness flag and preserve it. Check original F1/A1 plan file hashes. The reader/stored-block blob IDs must match §1.2, including on MAIN_BASE. Require tracked source/configuration clean before the red stage. Record and leave the known foreign untracked `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` untouched if present. A foreign item that might influence source, build configuration or command behavior is a source-admission blocker; do not silently exclude it.

The counter search must show exactly the old declaration, the one `reader.rs` increment, and the two reads in the target test: four old identifier occurrences, with no existing new helper name. Whole-checkout search is required; indexed remote search is not proof of absence. Inspect the actual failure-flag setter and every call. The only mutation pair must be the known panic-injection test's true/reset-false pair under the same serial guard. An extra consumer, another unguarded setter, cross-thread aggregate assertion, ambiguous lock owner, or changed source spelling triggers B06 before implementation. Record actual output; never manufacture a count.

Complete this worksheet in the report before modifying source:

1. Why a globally atomic counter can still give a wrong per-test delta. Name its producer, the two reads, and unrelated tests' ability to build without this test's lock.
2. Why `serial()` stays in the parent and must not be acquired in the child. Name the global fault flag and the protected setter pair.
3. Why a child build must contribute 1 to the child and 0 to the parent, independent of scheduling. Identify the join boundary.
4. Why the parent uses a delta rather than assuming an absolute zero and why no counter reset is added.
5. Which exact old assertions and warm selections remain, and why the final no-rebuild assertion matters.
6. Why the repair has no normal-build effect and how the byte comparator rejects out-of-scope changes.
7. Why old A1 coverage and source-bound current CI are historical after this test change; how A2_TESTED is made immutable before final QA.
8. Why raw diagnostic text can introduce new whitespace when committed, how Base64 preserves its bytes, and why an encoded receipt is not permission to hide a failed check.
9. Which gates a possible 81-diagnostic whitespace approval can close, and which it cannot. Name G10's owner.
10. Challenge the proposed design with global counter/reset, mocked worker increment, worker-lock deadlock, skipped test, unrecorded source edits and stale PR metadata counterexamples. Map each to a named invariant/check. Apply §14 for any new contradiction.

## 5. Evidence capture contract before the red stage

Copy Appendix B verbatim to `docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-record.py` and Appendix C verbatim to `docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-source-freeze.py`. Record their SHA-256 values and include their actual invocation in receipts. Use Python without `-O` or `-OO`; the scripts refuse optimized mode. No third-party Python package is required.

The recorder takes `OUTPUT.json MODE EXPECTED_COMMIT -- COMMAND ARGUMENTS...`; use `red` only for the specified temporary source state, otherwise `pinned`. In pinned mode it requires immutable HEAD and clean relevant source/configuration before and after the child command. In red mode it records the exact source patch as bytes and a SHA-256, and the red-state checks must also pass. It removes exactly three keys from the child environment: `QUERVANT_PR15I_D3C_STRATEGY`, `QUERVANT_PR15I_D3C_PREFILTER_PROFILE`, and `RUST_TEST_THREADS`. The first two preserve the accepted experiment configuration; removing the third prevents an inherited `RUST_TEST_THREADS=1` from silently serializing mandatory full-workspace tests. Explicit targeted `--test-threads` arguments remain as prescribed. It captures stdout and stderr together as unmodified bytes, records the actual return code, and encodes those bytes in Base64. This avoids trailing-space diagnostics in newly authored JSON while retaining every original byte, including blank lines and trailing spaces. No persistent environment or other environment key is changed.

Use distinct attempt-01 names for first executions. Never overwrite a receipt. Read and decode every required result; a Base64 blob without a factual report is not an acceptable handoff. To inspect a receipt without changing it:

~~~python
import base64, hashlib, json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    receipt = json.load(stream)
raw = base64.b64decode(receipt["combined_output_base64"], validate=True)
assert hashlib.sha256(raw).hexdigest() == receipt["combined_output_sha256"]
sys.stdout.buffer.write(raw)
~~~

The command's exit code, complete output, selected names/counts, failures/ignores and applicable case lines must be checked. A successful logger, empty output, test compilation, `--list`, exit-0 zero-test command or green related test does not establish a passing acceptance test. `source_identity_valid=false`, a launch error, missing output hash match or wrong selected set invalidates the receipt. Keep failed receipts and classify them; do not relabel them after a retry.

Create `evidence/c2-f1-a2-manifest.json` before the evidence commit. It must enumerate the 36 Appendix E command receipts, the six final counter receipts T02–T07, the separate expected-red receipt T01, and all required source/identity/decision artifacts. Each row contains the stable command/check ID, exact file path, SHA-256, actual source revision, command exit, result classification, and selected count or coverage totals where applicable. Verify every path exists, its stored hash matches, its output decodes, and its source/command matches the prescribed check. Explicitly verify that both q06/q07 coverage files are staged and appear in the committed tree. Hash the manifest in the report; do not try to put the manifest's own hash inside itself. A wildcard citation or a local file that was never delivered cannot close G9.

For preflight metadata and human decisions, write a bounded factual JSON/Markdown record with exact commands/observations and available timestamps. Do not dump all environment variables, credentials or unrelated logs. No unrecorded historical metadata may be reconstructed as if observed. Missing A1 receipts are handled by §11, not backdated wrappers.

## 6. Fixed implementation design and deterministic red/green proof

### 6.1 Temporary red state: retain the old global backend

Leave the old `#[cfg(test)]` atomic `CERTIFICATE_BUILDS` declaration in place. Immediately after the existing `decompressed_blocks()` getter and its following blank line, before `FAIL_STORED_BLOCKS_BUILD`, add these exact temporary helpers, both test-only:

~~~rust
#[cfg(test)]
pub(crate) fn record_certificate_build() {
    CERTIFICATE_BUILDS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
}

#[cfg(test)]
pub(crate) fn certificate_builds() -> u64 {
    CERTIFICATE_BUILDS.load(std::sync::atomic::Ordering::SeqCst)
}
~~~

Replace only the existing counter statement in `reader.rs`:

~~~rust
        #[cfg(test)]
        super::stored_blocks::record_certificate_build();
~~~

Replace only the body of the existing test `certificate_retains_flat_offsets_and_hot_path_is_direct` with Appendix D's complete prescribed function. Preserve its name/registration. Create the existing 300-document fixture once; the parent uses a clone of its bytes and moves the independent owned bytes into the worker. The worker constructs its own admitted state, budget and reader, calls real `stored_docs_selected(&[0, 299])`, asserts two records and 303 retained offsets, and returns its exact build delta. The parent holds its existing serial guard throughout and joins the worker before any parent first access. No worker `serial()`, sleep, retry, fake increment, changed global fault flag or mutation of original source fixtures is allowed.

Validate the red state with the exact red-state check in Appendix C; save its receipt and binary patch. Run exactly once:

~~~sh
python3 docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-record.py docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-counter-red-attempt-01.json red cdffd5b486ce46312abf4c45c80b9d33ecbf657d -- cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct -- --exact --nocapture --test-threads=1
~~~

Expected: one test selected; `command_exit_code == 101` and `source_identity_valid == true`; the target fails specifically at the assertion that a different thread's real certificate build must not change this thread's count, observed left 1 / right 0. The worker's real reader/build assertions must have passed. A wrapper exit125, launch exit127, signal or compilation error does not satisfy this result. This expected red failure is feature-acceptance evidence for the old mechanism, not a final QA failure or a reason to retry the old flaky campaign. A different failure, unexpected pass, zero selection or uncertain intermediate source triggers B09. Do not run full QA on this temporary state and do not commit it as the repair.

### 6.2 Final state: thread-local observation only

In the existing `#[cfg(test)] thread_local!` block in `stored_blocks.rs`, alongside `DECOMPRESSED_BLOCKS`, add exactly:

~~~rust
    static CERTIFICATE_BUILDS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
~~~

Remove the old `#[cfg(test)]` global atomic certificate-counter declaration. Replace the temporary helpers with:

~~~rust
#[cfg(test)]
pub(crate) fn record_certificate_build() {
    CERTIFICATE_BUILDS.with(|value| value.set(value.get() + 1));
}

#[cfg(test)]
pub(crate) fn certificate_builds() -> u64 {
    CERTIFICATE_BUILDS.with(std::cell::Cell::get)
}
~~~

Keep the one replaced reader increment and exact Appendix D regression. Do not reset the TLS counter: deltas correctly handle any previous work on the same thread. Do not touch the remaining `AtomicBool`, existing locks, certificate data, initialization/validation order, codec, budget, publication, mutex, stored observation or normal-build logic. `Cell` is appropriate because only the calling thread accesses its value. These helpers are observation utilities for tests, not a cross-thread metric or public API.

Review the exact allowed source diff. Run the pinned toolchain formatter only to format these prescribed edits; preserve all other bytes. Validate source erasures before committing. Commit the final two-file source change together with the verbatim A2 plan and its exact helper scripts; explicit-path staging only. Record the resulting full SHA as A2_TESTED. The red receipt remains a record of the temporary patch; it must not be relabeled A2_TESTED.

**All final test/QA commands now run against committed A2_TESTED with source clean before and after.** Do not amend this commit, alter source during QA, or allow later documentation commits to obscure its identity. If a prescribed mechanical fix is necessary, use B14/B15 and a new immutable source commit; preserve superseded results.

## 7. Counter repair acceptance matrix and regression scope

Use Appendix B's recorder in pinned mode with the literal A2_TESTED SHA substituted. For each command below, select exactly the expected tests, retain complete output and actual exits, and decode it for the report.

| ID | Command after recorder `--` | Required result |
|---|---|---|
| T01 | §6.1 exact command on the verified global-backed red state | One deliberate failure at parent isolation, left 1 / right 0; all worker preconditions passed |
| T02 | `cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct -- --exact --nocapture --test-threads=1` | Exactly one PASS on final TLS source; parent/worker deltas 0/1/1 and final no-rebuild assertions executed |
| T03 | `cargo +1.85.0 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct -- --exact --nocapture --test-threads=1` | Exactly one PASS on MSRV |
| T04 | `cargo +1.85.0 test -p quervant-core --lib --all-features segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct -- --exact --nocapture --test-threads=1` | Exactly one PASS in the former failing feature/toolchain configuration |
| T05 | `cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests:: -- --test-threads=1` | Nine existing tests PASS; no new registration/ignore |
| T06 | `cargo +1.98.1 test -p quervant-core --lib segment::reader::stored_blocks_reader_tests:: -- --test-threads=8` | Same nine PASS under module concurrency |
| T07 | `cargo +1.85.0 test -p quervant-core --lib --all-features segment::reader::stored_blocks_reader_tests:: -- --test-threads=8` | Same nine PASS under MSRV/all-features concurrency |
| T08 | Full final workspace and required integration/CI commands in §8–§9 | PASS under normal suite concurrency; no global serialization workaround |

The nine frozen module names are `certificate_validates_all_once_then_selected_blocks_only`, `plain_reader_without_access_budget_revalidates_each_call`, `zero_metadata_cap_uses_full_validation_fallback`, `malformed_selection_is_rejected_before_certificate`, `certificate_retains_flat_offsets_and_hot_path_is_direct`, `unselected_corruption_blocks_certificate`, `distinct_states_never_share_a_certificate`, `concurrent_first_access_publishes_one_certificate`, and `initializer_panic_publishes_nothing_and_poison_fails_closed`.

No new probabilistic stress campaign is required. A new failure in the target after the TLS repair is not automatically the historical flake: classify and stop the affected acceptance under B16. The old bounded A1 diagnostic repeat budget is exhausted and is not restarted here. Do not run more unchanged-baseline flake trials merely to obtain a green line.

## 8. Preserve and execute C2 feature acceptance and retained regressions

All C2 source and expectations remain byte-identical to A2_START. Final source equality is required even when all tests pass. The following observations are the retained contract, not numbers to print without checking the executed tests:

| Case | Frozen acceptance |
|---|---|
| U17 B3 | Five actual refusal/ready/ExactSet rows; real probes/counters, fallback segments, 40 callbacks, route 1/0, completed tuples and full forced-Legacy response equality |
| U17 structural | Native segment 0 has 34 docs; injected local doc 33 score fault; one bound/evaluated segment, membership 34, zero conversion completion/callbacks/numeric, empty collected list; unarmed 40-hit recovery and tuples `(0,3,34)`, `(1,3,40)` |
| U21 | Caps 86→`{86,87}` before first completed segment; 87→`{87,88}` and 99→`{99,100}` after `(0,3,34)`/34 callbacks; cap100 success with both tuples; three required post-failure same-snapshot recoveries |
| U12 | All nine IDs: D0, D29, D31, P29, P29+D0, C0, C29, C29+P29+D0, S29+D0; exact expected errors, probes/counters, pristine guards, complete response comparison and `completed=9`; no skipped branch |
| P05 | Six exact total-used results 20/38/53/53/40/53; exact resource payloads, zero ledgers and same-budget recovery |
| I08 | Exact failures `{68,69}`, `{2943,2944}`, `{22,23}`, cap23 success and cancellation; full cursor and aggregation retry parity |

U12 real-byte rows compare their corresponding Legacy results. S29+D0 is explicitly synthetic `INJECTED_C2_ONLY` and uses its specified unarmed shared-fault controls; do not claim an equivalent Legacy score injection. The current U21 code also performs a fourth follow-up success call after the successful cap100 row. That benign additional call may remain; report three required failure recoveries separately rather than changing source for prose consistency.

Appendix E provides the complete command catalog, with fixed receipt suffixes. Run all of it against A2_TESTED after the source commit. Use the recorder's child environment so `QUERVANT_PR15I_D3C_STRATEGY` and `QUERVANT_PR15I_D3C_PREFILTER_PROFILE` are absent. Do not execute a bare `env` prefix as an environment dump. No concurrent Cargo processes against the same target directory.

Inventory requirements: selected name sets remain unified24, physical5, integration9, and broad `--lib c2_`39. The broad set remains the union of both C2 modules plus the same ten older accounting tests. Compare sets, not source substring counts or a sum of repeated executions. Reader-module count remains nine. Matrix rows are cases inside functions; do not add them to registered test totals.

Use the four preserved `evidence/c2-f1-inventory-final-unified.txt`, `evidence/c2-f1-inventory-final-physical.txt`, `evidence/c2-f1-inventory-final-integration.txt`, and `evidence/c2-f1-inventory-final-broad.txt` files under `docs/pr-artifacts/perf-06-c/` as exact historical name-set references. They contain 24/5/9/39 registrations and remain unchanged through A1. Parse only full lines ending `: test`, remove that suffix, reject duplicate names, sort, and compare with the identically parsed new i01–i04 outputs. Ignore surrounding historical compiler chatter for this name-set comparison only; do not relabel those old receipts as new QA. Do not use the older `inventory-baseline-*` files, which predate U12 and have 23/5/9/38. The reader-module reference is the nine exact names in §7. No old-source inventory rerun is required.

Unit acceptance uses real writer/reader/collector execution over existing MemoryDirectory fixtures. U12 uses precisely rebuilt private test bytes through real codec/reader/query paths. I08 and dedicated integration use real local FsDirectory create/commit/reopen/query and the same immutable snapshot for retries. Hosted RustFS is the existing real S3 integration topology for unchanged storage behavior; its job must execute real bodies. No fake decoder, mocked search, extra local RustFS deployment or new harness is required.

## 9. Final local QA, hosted regression, and failure classification

All commands in Appendix E's final QA table are mandatory on the same immutable A2_TESTED source. Both line-coverage runs must cover the applicable production Rust workspace at at least 85%, with no changed exclusion, threshold, crate/module selection or dependency. Record actual total, missed, covered and percentage values from each new output. The reported A1 93.33%/92.91% and A1 CI measurements are historical context, not new A2 measurements. A per-file percentage cannot satisfy the workspace gate.

Use normal full-workspace test concurrency; do not add `--test-threads=1`, ignored-test filters, retries or environment overrides to hide the counter problem. The targeted commands' explicitly selected concurrency is intentional acceptance. Existing externally gated ignored tests remain disclosed. All required local commands must run successfully after final source edits; CI cannot replace them.

Classify every unexpected mandatory failure as introduced regression, feature implementation defect, deterministic pre-existing failure, nondeterministic/flaky failure, or environment/harness failure. Calling something pre-existing requires relevant baseline evidence; calling it flaky requires evidence of nondeterminism. The historical A1 MSRV failure stays recorded as FAIL then PASS, not retroactive PASS. A new A2 failure receives its own classification and cannot inherit an exception from the old one.

After the normal push, observe the existing ordinary PR workflow. Require terminal success of `rust`, `msrv`, `python-benchmark-framework`, `benchmark-adapter-contract`, and `rustfs`. Capture run URL/ID, head SHA, event, merge checkout if used, all job IDs/statuses, and evidence that required RustFS bodies executed rather than skipped/ignored registration. Do not launch duplicate equivalent workflows, change triggers, edit branch protection or invent a head-only workflow. If CI is pending or inaccessible, continue evidence/documentation work and leave G8 pending/blocked.

Later documentation-only commits may reuse this A2_TESTED QA/CI only after an exact source/configuration equality check. A newly triggered ordinary run must still be reported honestly; do not claim a run is on H when it used an earlier source-equivalent commit. Final source drift requires B15, not selective relabeling of old receipts.

## 10. Whitespace: frozen scope, exact commands, and no implicit exception

### 10.1 Correct historical and current arithmetic

The A1 raw range receipt measured historical head `80ccc5c75f244c2c89b295732a229423ad86438f` before that receipt itself was committed. Its actual diagnostic counts were **36 / 0 / 55** for F1_START / A1_START / MAIN_BASE ranges. Its summary and the committed report incorrectly used 23 for the first count. Committing the raw self-quoting log added 26 trailing-whitespace diagnostics in that log. At reviewed A2_START, the resulting counts are **62 / 26 / 81**, with the 81 consisting exactly of Appendix A's 55 original diagnostics plus the 26 new log diagnostics. All original 40 blobs are unchanged.

The user's `42c…` shorthand is not the prescribed F1_START. Always run the literal `46ccab0…` comparison below. An unavailable terminal receipt cannot establish what that shorthand meant; do not invent a source defect or silently change identity definitions.

### 10.2 Required final committed-range checks

Substitute literal final H into each command. Capture complete output and actual exits outside the checkout in the final terminal package; a precommit/worktree-only check is not equivalent.

~~~sh
git diff --check 46ccab0a606a56a8b9034ab4db5c9c4df969d098..H
git diff --check 2bf9539cd2f53838ad1aca406ca4e67a34229ff6..H
git diff --check cdffd5b486ce46312abf4c45c80b9d33ecbf657d..H
git diff --check bc726420cede2e26681d6e8192b45a5d0169abbf...H
git diff --check
git diff --cached --check
~~~

Expected if only this plan's clean additions occur: F1 range62 diagnostics, A1 range26, A2 range0, main range81, and worktree/cached checks clean. Still inspect actual output, types, paths, lines and exact blobs. Counts alone cannot approve a changed scope. Run equivalent committed-range checks before the last evidence commit as well; record that earlier measured revision distinctly.

Appendix A is the complete reviewable proposed scope. Preserve every listed file byte-for-byte, and also preserve every other historical evidence artifact. For each applicable human approval, record the actual approving instruction/reference, exact scope and gate effect. A statement approving only the original55 does not cover the additional26. Authorization to execute this plan is not whitespace approval. The raw `git diff --check` command continues to be reported FAIL if it exits nonzero; an approved gate becomes `PASS WITH EXPLICIT WHITESPACE EXCEPTION`, with the failing raw result retained.

New A2 source/prose/scripts/JSON must introduce zero diagnostics. Before committing, use named staging and `git diff --cached --check` so new files are actually checked. Fix only newly authored A2 formatting under B18. Do not trim old logs, reserialize old reports, change Git whitespace configuration, ignore paths or insert `.gitattributes` exceptions. New lossless JSON records prevent the particular self-quoting whitespace recurrence without changing the recorded diagnostic bytes.

## 11. Resolve A1 evidence gaps honestly

Do the following during independent work; no old mandatory run becomes PASS merely because this plan exists.

1. **Coverage:** look for the actual retained outputs of the two claimed A1 local coverage runs. If they exist, preserve exact bytes in new A2 recovery receipts with known original provenance and an honest new collection timestamp; do not invent missing command/exit/source/time metadata. If lost, state “reported A1 measurements; original raw local receipts unavailable.” The fresh final A2 coverage runs supply current acceptance; they are not reconstructions of A1. Do not rerun old source simply to reproduce the old percentages.
2. **Source-freeze receipt:** preserve the old 23-line A1 receipt and state that it lacks the required exact script and dirty-source linkage. Run and deliver the exact new checker against immutable source. If an original tested-diff hash is unavailable, disclose that; current equality and source-bound CI do not retroactively recreate it.
3. **Terminal file:** try to retrieve the actual existing 174-line A1 receipt from the execution environment if still available. Attach its actual bytes if recovered. If unavailable, say so; regenerate cheap final checks for A2 under new timestamps. A path on another machine is not a delivered artifact. Never fabricate the old receipt or commit a terminal raw log.
4. **Baseline attachments:** recover real `c2-f1-a1-baseline-*.txt` and isolated-main diagnostic outputs if retained. Otherwise remove the dangling current claim by append-only qualification and distinguish reused historical inventories from newly delivered A1 executions. The prior preserved pristine-main assertion failure still supports pre-existence; missing new success logs do not require more diagnostic flake runs.
5. **Consolidated report corrections:** use §12. Do not independently rewrite each old receipt or silently replace historical statuses.
6. **PR description:** replace the stale current F1-stop description using §13's prepared body. Fetch it afterward and compare the complete relevant body plus observed head/state/readiness. Saving a local body file alone does not complete the update.

Historical A1 evidence recoveries are useful but need not remain an indefinite execution blocker when they cannot be recovered: accurately disclose the loss, retain available historical facts, and satisfy every current A2 acceptance requirement with actual immutable-source receipts. An invented old PASS, unsupported percentage, unresolved source identity or unavailable current terminal delivery still blocks G9.

## 12. Required report, append-only corrections, and objective gates

Create the new A2 report using these eleven sections:

1. **Identity:** repository/PR/branch, all §1 revisions, A2 plan and helper hashes, A2_TESTED, intermediate docs revisions, literal H or an explicit pointer to the external terminal receipt, toolchains and tested-source cleanliness.
2. **Starting reconciliation:** semantic A1 acceptance preserved; exact G7/G9 defects; repaired counter scope; historical versus current evidence.
3. **Correctness preparation:** completed §4 worksheet, invariant/test map, every applied B-rule with trigger/evidence/action/gate/owner.
4. **Source delta:** exact two files/test-only regions, red intermediate patch hash, final blob IDs and complete source-freeze script/receipt.
5. **Acceptance:** T01–T08 and preserved U17/U21/U12/P05/I08 cases with executed results and receipt links. Distinguish expected red failure from final QA.
6. **Inventories:** actual baseline/final name sets; unchanged24/5/9/broad39 and reader9; cases versus functions.
7. **Local QA:** each exact command, all attempts/exits, actual totals/ignored names and both complete final coverage summaries.
8. **Hosted topology:** current run/head/merge/jobs and real RustFS body evidence; identify any source-equivalent later delivery commit.
9. **Failures and exceptions:** all old/new relevant failures, taxonomy, exact whitespace scope/decision or absence, missing-history qualifications and open gates.
10. **Final adversarial review:** §15 checklist with concrete evidence/residual dispositions.
11. **Handoff:** gate-derived disposition, current metadata, exact terminal attachment name/hash, remote equality, G10 open, C3/C4 unstarted and precise remaining human decision.

Append one dated A2 correction to the A1 report and F1 report. Preserve original bytes as exact prefixes. Correct all of these points together:

- The delivered A1 implementation completes the previously blocked U17/U21/U12 cases, as established by its focused receipts; no current D14 fixture amendment remains.
- At the historical whitespace-receipt SHA, the first count is36 rather than23; at A2_START the three old ranges are62/26/81. The additional26 are a separate frozen scope. Approval of original55 alone does not close G7.
- A1's reported local coverage totals are arithmetic-consistent but originally lacked delivered raw receipts; state recovery outcome and separate new A2 measurement.
- The old source-freeze receipt omitted its script/dirty-source hash; current exact checking does not invent missing historical provenance.
- G9 was partial/blocked until delivery/report/PR-body defects were corrected. State terminal and baseline recovery outcome, not fictional links.
- Actual B3 refusal was already fixed by F1; the A1-start refinement was full response parity. Label the earlier “unarmed” defect as historical rather than an A1-start fact.
- U12 identical Legacy-error wording applies to real-byte rows; qualify the synthetic score row. Distinguish U21's three required failure recoveries from its additional benign success follow-up.
- Describe the flake as interference in a process-global test counter, not a thread-local counter race. Record the exact test-only repair and its red/green evidence without erasing the historical FAIL then PASS.
- Use actual current readiness; do not claim draft when false. Separate workflow head, merge checkout, tested source, intermediate documentation and delivered H.

Append only a pointer to the original C2 report, append an A2 series-register entry, and change only the current C2 roadmap note. Do not mark the roadmap DONE or PR accepted while G10 is open.

| Gate | A2 closure condition |
|---|---|
| G0 | Exact source/PR/toolchain admission, known foreign work untouched, original plans verified |
| G1 | Completed worksheet, invariants and decision ledger, no unresolved design contradiction |
| G2 | Only allowed changes; exact final/old source-freeze checks; historical bytes preserved |
| G3 | Frozen U17/U21 acceptance executed successfully on final source |
| G4 | Frozen all-nine U12 acceptance executed successfully on final source |
| G5 | Frozen P05/I08 acceptance and complete retry parity executed successfully |
| G6 | T01–T07 decisive counter proof, exact inventories, required feature/module/retained regressions passed |
| G7 | All mandatory final local QA passed; current source/prose adds zero whitespace; the exact frozen historical whitespace diagnostics have §10's explicit human disposition. The counter failure is CLOSED BY REPAIR only after T01–T07 and all final QA pass; no flake waiver is required or granted |
| G8 | Ordinary final-source hosted regression, all five jobs and required real bodies passed |
| G9 | Accurate report/append-only corrections, complete current receipts, exact source linkage, actually updated PR body and delivered outside-checkout terminal package |
| G10 | Independent review and maintainer acceptance; remains OPEN in the coding-agent handoff |

Use `PERF06_C2_F1_A2_EXECUTED_PENDING_INDEPENDENT_REVIEW` only if G0–G9 are satisfied, identifying an approved whitespace exception separately. If only the exact whitespace decision remains, use `PERF06_C2_F1_A2_ACCEPTANCE_EXECUTED_G7_BLOCKED_WHITESPACE_DECISION`. If any other verification/delivery gate remains open, use `PERF06_C2_F1_A2_IMPLEMENTED_VERIFICATION_BLOCKED` and enumerate it. A design/source mismatch uses `PERF06_C2_F1_A2_STOPPED_AMENDMENT_REQUIRED`. Never derive readiness from a single green command, coverage percentage or PR draft flag.

## 13. Ordered delivery, immutable final identity, and prepared PR body

1. Finish the exact red proof, final source, source commit A2_TESTED, all final local verification and new evidence. Append factual corrections and prepare the PR body. Complete every independent task even if the human whitespace decision is absent.
2. Run the source-freeze checker and named staging checks. Commit only authorized docs/evidence. Prove A2_TESTED to that commit differs only in authorized documentation/evidence; all source/configuration/build inputs must be unchanged. Normal push only.
3. Observe the ordinary CI run and record it. If recording CI requires one later docs-only evidence commit, preserve the earlier run's exact source identity and prove source equivalence. Do not rerun unrelated local Rust suites for a docs-only commit, create duplicate workflows, or chase a self-referential “report contains its own SHA” loop.
4. Replace the existing PR body from the prepared file using the supported structured update tool or `gh pr edit 131 --repo yduchesne/quervant --body-file <prepared-file>`. Do not interpolate a multiline description into shell arguments. Fetch the body/metadata back; compare and preserve the readiness flag. No notification/comment is required.
5. After the last repository commit and normal push, fetch normally and freeze the actual remote head as literal H. Verify remote branch and PR head equal H and PR remains open/unmerged. Do not substitute A2_TESTED or an intermediate docs commit for H.
6. Outside the checkout, create `perf06-c2-f1-a2-terminal-<H>.md` and its raw lossless JSON command receipts. Include full identities, actual commands/times/exits, all §10.2 committed-range outputs, Appendix A blob checks, final source-freeze result, A2_TESTED→H equality, final remote/PR metadata, CI linkage, helper/plan/terminal receipt hashes and exception status. The Markdown terminal file may quote the diagnostics because it will not be committed. Use a small ZIP if necessary to deliver the Markdown plus lossless receipt files together; list each member's SHA-256 in the terminal Markdown. Do not recursively hash the terminal Markdown inside itself; put its hash in the final handoff.
7. Verify remote equality again immediately before handoff. Attach the actual terminal file/package and give a working download link; if attachments are unavailable, paste the complete terminal Markdown and complete required raw outputs. Merely naming an inaccessible `/tmp` path leaves G9 BLOCKED. Do not commit the terminal package or create another docs commit solely to refer to it. If the remote moved, apply B02/B28 rather than claim old H is current.

### Prepared PR description template

Replace bracketed observations only with measured values and actual links; remove no unresolved blocker. Keep this body concise and accurate. Store the rendered body at `evidence/c2-f1-a2-pr-body.md` before the update.

~~~markdown
## PERF-06-C2 — accepted test design, A2 verification closeout

The A1 amendment completed the native 34+6 segment boundary tests, all nine U12 corruption/precedence rows, actual B3 refusal coverage, and exact public resource/retry comparisons. A2 preserves that C2 source and repairs the pre-existing certificate test counter: test-only observation is thread-local, with a deterministic real-reader sibling-thread regression and an exact no-rebuild assertion.

Plan: [A2 plan link]. Full evidence: [A2 report link]. Historical reports remain unchanged with appended corrections.

### Verification

- Counter regression: [red/green and MSRV result, receipt links].
- C2 inventories: 24 unified, 5 physical, 9 integration, broad 39; reader module9; [actual execution status].
- Local QA and coverage: [actual statuses and new default/all-features line totals/percentages].
- Hosted regression: [actual run URL, tested head/merge distinction, five job statuses and real RustFS execution].
- Source: [A2_TESTED]; report evidence revision [actual revision]; later documentation-only delivery is linked by exact source equality and the terminal handoff.

### Outstanding acceptance

[Exact G7 status: historical raw range failure81 across41 unchanged artifact blobs; explicit approval reference if granted, otherwise decision required. Include every other unresolved gate.]

No normal-build runtime change, benchmark execution or performance claim is included. C3/C4 remain unstarted. The PR remains open and unmerged; observed readiness is [actual value, preserved]. G10 independent review and maintainer acceptance remain open.
~~~

## 14. Preauthorized decisions and exception-handling matrix

Categories are **AUTO-RESOLVE**, **DEFER AND CONTINUE**, and **HARD STOP**. Apply a rule only when every listed observable precondition holds. The evidence column is mandatory in the decision ledger. “Agent” means permission to perform only the specified action; “Maintainer” means the agent cannot supply the approval. A STOP is scoped to the affected dependency unless source admission or ownership makes isolation impossible. For the one T01 red invocation, B09 takes precedence over B14/B17/B19 after that invocation is attempted: a verified literal red state that fails compilation or otherwise misses the required assertion needs a plan/environment decision before another red attempt. Correct source transcription before invoking T01; B14 does not authorize repeating it. Other unresolved rule conflicts use B32.

| ID | Observable trigger / source check | Category | Exact authorized action | Prohibited action | Evidence / gates / owner |
|---|---|---|---|---|---|
| B01 | Exact pinned refs, source blobs, clean relevant source and open/unmerged PR admitted | AUTO-RESOLVE | Record G0 and continue immediately | Asking to continue after successful admission | Commands, blob/PR identities; G0; Agent |
| B02 | At initial G0 admission HEAD/remote differs from A2_START; at any time main differs from MAIN_BASE, PR is merged/closed, repository/branch is wrong, or later source drift is unexplained | HARD STOP | Stop affected implementation/delivery; report exact difference and request updated admission/design. Authorized A2_TESTED/docs commits are expected progress, checked against their recorded identity and equality rules | Rebase, merge, reset, reinterpret foreign source as approved, or stop merely because a prescribed commit advanced HEAD | Full refs/status and minimal diff; G0/G2; Maintainer |
| B03 | Readiness flag differs from prior report while source/PR admission still holds | AUTO-RESOLVE | Record and preserve observed flag; continue | Toggle draft/ready or infer acceptance/identity of changer | Metadata before/after; G0/G9; Agent |
| B04 | Known foreign untracked evidence file is outside build inputs | AUTO-RESOLVE | Record and leave untouched; stage named owned files only | Broad add, cleanup, stash or deletion | Exact path and independence; G0/G9; Agent |
| B05 | At admission relevant source/configuration is dirty, or later unapproved/foreign source/configuration can affect execution; ownership is uncertain | HARD STOP | Isolate only if possible without altering foreign work; otherwise report blocker. The exact verified red worktree is authorized only for T01 | Overwrite, exclude meaningful inputs or claim clean final source from the red state | Status/config paths; G0/G6/G7; Maintainer |
| B06 | Counter/setter/lock inventory differs from the four-read/producer/declaration and sole guarded setter-pair design | HARD STOP | Stop counter work; record symbols and dependency | Convert consumers to TLS by guess, add locks or drop checks | Whole-checkout search and relevant code; G1/G2/G6; Plan author |
| B07 | Any proposed change falls outside §2 allowlist or approved exact regions | HARD STOP | Preserve branch; report smallest required scope amendment | New architecture, new public API or expanded erasure | Exact diff/invariant; G2; Maintainer/plan author |
| B08 | Exact global-backed red state passes its source checks | AUTO-RESOLVE | Run T01 once and retain patch/receipt | Commit red as final, run repeated flake diagnostics | Red checker, patch hash; G6; Agent |
| B09 | Red command selects other than one test, unexpectedly passes, or fails anywhere except exact parent-isolation assertion | HARD STOP | Retain output and intermediate source; stop dependent repair acceptance | Accept another panic, weaken oracle, retry until desired failure | Actual selection/exit/panic and patch; G6; Plan author |
| B10 | Expected red failure observed and exact final TLS replacements applied | AUTO-RESOLVE | Run source comparison, commit prescribed final source, continue all final commands | Routine reconfirmation or global counter reset alternative | Red receipt/final diff/source commit; G2/G6; Agent |
| B11 | Formatting/transcription can be corrected to the exact supplied literals and that exact code passes pinned rustfmt | AUTO-RESOLVE | Restore the prescribed literal code; rerun format/source checks. If rustfmt requires different fixed bytes, apply B32 | Editing approved templates/checker, broader normalization or whole-file drift | Exact diff and format receipt; G2/G7; Agent |
| B12 | Source comparator fails solely from identified agent-owned accidental drift outside an allowed region, with exact START bytes known | AUTO-RESOLVE | Restore only that accidental drift and rerun comparison once | Broader exclusions, normalization, foreign restoration | Owned delta/restoration and comparison; G2; Agent |
| B13 | Comparator fails for unknown cause or after B12's bounded restoration | HARD STOP | Preserve failure and exact inputs; request plan correction | Claim “test-only” from reasoning or expand markers | Script/hash/outputs/blobs; G2; Plan author |
| B14 | Compiler error is a literal transcription/formatting error in prescribed new code, with correction unambiguously matching this plan | AUTO-RESOLVE | Correct only to exact prescribed code, preserve failed receipt, create new tested commit if needed | New design/API/workaround, altering exact assertions | Diagnostic plus exact before/after; G2/G6/G7; Agent |
| B15 | Any allowed source/test edit occurs after final QA starts | AUTO-RESOLVE | Preserve old receipts as superseded; commit new immutable A2_TESTED; rerun affected acceptance and all mandatory final QA once on final source | Mix source identities or relabel old runs | Source delta/new SHA/full final receipts; G2–G8; Agent |
| B16 | Final TLS target/module/workspace exposes an unexpected semantic failure or the counter assertion fails again | HARD STOP | Classify with evidence; stop affected acceptance and continue only independent documentation work | Automatic “known flake” label, retry-to-green, serial suite or weaker assertion | Failure/source/selected case; G6/G7; Plan author |
| B17 | Any other final command fails | DEFER AND CONTINUE | Preserve and classify; continue commands independent of the failing dependency; report affected gate | Treat related green run/CI as replacement or self-waive | Actual receipt/taxonomy; affected G6–G8; Maintainer if disposition needed |
| B18 | New A2-owned formatting causes a whitespace diagnostic; raw data are still available losslessly | AUTO-RESOLVE | Fix only new prose/script formatting or exact JSON envelope; preserve raw output bytes; recheck new staged/range diff | Trim historical logs/raw data, suppress Git rules | New-path diagnostic and clean delta; G7/G9; Agent |
| B19 | Required toolchain, coverage component, execution topology or access is unavailable | DEFER AND CONTINUE | Use only existing supported installation/setup procedure if authorized; otherwise mark gate blocked, finish independent work | Substitute toolchain, skip required topology, change threshold/workflow | Exact missing dependency/error; relevant gate; environment owner |
| B20 | Old A1 receipts actually retained with known provenance | AUTO-RESOLVE | Preserve exact bytes in new recovery artifact and state what metadata is known | Backdate collection or fabricate missing metadata | Hashes/original file/context; G9; Agent |
| B21 | Old A1 receipt is unavailable after bounded local recovery search | AUTO-RESOLVE | Qualify historical claim/dangling link; rely on new actual final-source acceptance for current gates | Recreate historical output or rerun old flake to make paper trail | Searched named locations and explicit loss; G9; Agent |
| B22 | New A2 final receipt is missing, corrupt, zero-test or not bound to admitted source | HARD STOP | Stop that gate's closure; capture a genuinely missing command once on final source if safe and prescribed | Infer pass from report/coverage/test existence or overwrite failure | Missing/invalid field and new numbered receipt; relevant gate; Agent within command scope, otherwise plan author |
| B23 | Exact Appendix A81 remain; no explicit applicable human exception | DEFER AND CONTINUE | Keep G7 blocked; complete every independent code/evidence/CI/delivery task | Self-approve, assume previous55 approval or modify frozen blobs | Exact diagnostic/blob set; G7; Maintainer |
| B24 | Human explicitly approves only the original55, or only the new26 | AUTO-RESOLVE | Record only that exact scope as approved; keep remainder blocked | Expand approval to all81 or tests/coverage | Exact approving instruction/scope; G7; Maintainer approval, Agent recording |
| B25 | Human explicitly approves all81 unchanged listed diagnostics and every other G7 requirement passed | AUTO-RESOLVE | Mark gate PASS WITH EXPLICIT WHITESPACE EXCEPTION; retain raw command FAIL | Report command exit0 or waive another gate | Approval + exact set/blob comparison + other QA; G7; Agent recording |
| B26 | Human refuses an exception or diagnostic set exceeds approved scope | DEFER AND CONTINUE | Keep G7 blocked; preserve history; finish independent tasks and request narrow policy amendment | Rewrite old plans/logs, quietly broaden exception or normalize bytes | Exact refused/extra scope; G7; Maintainer/plan author |
| B27 | All later changes are permitted documentation/evidence with exact source equality | AUTO-RESOLVE | Reuse A2_TESTED Rust QA; repeat cheap final source/range/metadata checks | Optional full Rust reruns or source identity ambiguity | Complete equality result; G7–G9; Agent |
| B28 | Remote or PR head changes during final handoff | HARD STOP | Stop current-state claim; record new refs and source difference; retain completed work | Push over others, force, call old H current | Fresh remote/PR metadata; G0/G8/G9; Maintainer |
| B29 | CI pending/inaccessible, PR-body update denied/unavailable, or attachment delivery unavailable | DEFER AND CONTINUE | Preserve exact status/error; finish independent tasks; paste complete terminal contents if attachment fallback is available | Claim G8/G9 passed from a local body/file path | Run/error/body/file facts; G8/G9; service/user owner |
| B30 | Preflight and a stage/checkpoint pass without an applicable blocking rule | AUTO-RESOLVE | Execute the next prescribed work without asking again | Treat progress update as approval boundary | Next step recorded; all gates; Agent |
| B31 | All G0–G9 conditions satisfied, including any exact human whitespace decision | AUTO-RESOLVE | Deliver full final report/terminal package and leave G10 open | Merge, approve, change readiness or start C3/C4 | Gate table and remote identity; G9/G10; Maintainer owns G10 |
| B32 | An unlisted condition, conflicting contract, unverified assumption or multiple plausible fixes would change behavior/scope/acceptance | HARD STOP | Stop affected work; state exact observation, invariant, blocked dependency and smallest decision; continue demonstrably independent work | Improvise, extrapolate a rule, lower expected results or invent evidence | File/symbol/command and concrete decision; affected gates; Plan author/maintainer |

## 15. Final adversarial review, residual limits, and reviewer checklist

Before reporting acceptance, answer these with concrete receipt/source references:

- Could global contamination still reach the target assertion? Confirm no global certificate atomic remains, all real builds call the one helper, and every counter consumer was inventoried.
- Could the new test pass without building a real certificate? Confirm actual reader calls, retained offsets, worker delta1, parent delta1 and old-backend red delta1→expected0.
- Could a child lock, shared mutable fixture or failure-flag reset conceal the failure? Confirm child owns its reader/budget, parent alone holds serial, no injected flag mutation and join ordering.
- Could hot access rebuild? Confirm all original direct-access assertions and the final unchanged build count execute.
- Could normal builds or another C2 path change? Cite exact erasure/full-file equality, protected-config/contract checks and inventories.
- Could green test registration hide missing cases? Cite focused U17/U21/U12/P05/I08 bodies and receipts, completed nine U12 rows, exact selections and full retries.
- Could a logger, copied percentage or later commit falsely support PASS? Decode raw receipts, verify actual exits/hashes/source, compare A2_TESTED→H and distinguish CI merge/head.
- Could whitespace approval accidentally cover new defects? Compare exact Appendix A paths/lines/types/blobs, require A2 range0, retain command FAIL and exact human decision.
- Could delivery still show stale blockers or omit a file? Fetch updated PR body, resolve current links, attach terminal package, verify actual H remotely and report unresolved gates explicitly.

Residual limits: TLS observations deliberately do not aggregate work across threads; future cross-thread metric consumers need a separate design. The deterministic regression proves counter isolation and the existing test's real-reader/no-rebuild behavior, not every possible scheduler interleaving. Existing concurrent certificate tests cover publication separately. Stored corruption, resource, fault-injection and remote regressions are retained rather than redesigned. C2's synthetic score rows remain structural/C2-only, malformed sortable columns establish pre-route priority, and C4 owns performance qualification. Coverage is a repository gate, not proof of semantic completeness. Missing original A1 metadata cannot be recreated; accurate disclosure and new final-source evidence are the required disposition. None of these limits authorizes weakening an acceptance gate.

Reviewer acceptance checklist:

- [ ] Exact starting refs and current main inspected; provided plans/hashes preserved.
- [ ] Only prescribed two-file test observation and one existing test changed; normal builds identical.
- [ ] Expected deterministic global-backed red failure retained; stable/MSRV/all-features final target and nine-reader suite passed.
- [ ] Every original hot-path assertion retained; real worker build, parent isolation, parent first build and warm no-rebuild assertions present.
- [ ] C2 source frozen; all focused cases, inventories, serial/8-thread feature suites and named regressions passed.
- [ ] All final local QA and both workspace coverage gates passed on immutable A2_TESTED, with complete actual receipts.
- [ ] Ordinary hosted five-job regression passed and real RustFS bodies verified; head/merge/source-equivalent docs identities accurate.
- [ ] All historical bytes preserved; A2 range clean; exact human whitespace disposition recorded or G7 openly blocked.
- [ ] Reports/roadmap note/series register accurate, append-only requirements met, missing-history limits disclosed.
- [ ] Live PR body actually updated; observed readiness preserved; real terminal file/package delivered and H remotely verified.
- [ ] G10 remains open; no merge, C3/C4, benchmark or performance claim.

## 16. Final coding-agent handoff format

Report the following after all independent authorized work is finished. Fill only observed facts; include download links to the new report and outside-checkout terminal package.

~~~text
REPO / BRANCH / PR
  yduchesne/quervant / dev/perf06-c2 / #131 OPEN UNMERGED
  observed readiness = <actual, preserved>

MAIN_BASE / F1_START / A1_START / A2_START / A2_TESTED / DOCS_FINAL / REMOTE_H
  <full actual values, meanings preserved>
  final source/configuration equality A2_TESTED..H = <actual>

PLAN / HELPER / TERMINAL HASHES
  <actual SHA-256 values and delivered filenames>

DISPOSITION
  <gate-derived A2 disposition>

G0..G10
  <each actual status, receipt, remaining owner>

COUNTER T01..T08 / C2 ACCEPTANCE / INVENTORIES
  <expected red distinguished from final pass; actual selected sets and cases>

LOCAL QA / COVERAGE / CI
  <all attempts, exits, measured totals and run/head/merge/jobs>

WHITESPACE
  <actual F1/A1/A2/main range results, exact81 scope, approval or none>

HISTORICAL EVIDENCE RECOVERY / CORRECTIONS / PR BODY
  <delivered / unavailable / qualified; live update verification>

FAILURES / RULE LEDGER / RESIDUAL LIMITS
  <every unresolved item and exact scope>

DELIVERY
  <actual downloadable terminal package and SHA-256; final remote equality>
  G10 OPEN; C3/C4 UNSTARTED; no benchmark or performance claim.
~~~

Do not end at a successful preflight, stage boundary, local body draft, CI observation, or an inaccessible path. Execute all prescribed independent work. Only the exact scoped decision matrix authorizes stopping; it never authorizes invention.

## Appendix A. Proposed frozen-whitespace exception — 81 diagnostics in 41 artifacts

**PROPOSED ONLY. This section grants no approval.** The old A1 Appendix A contains 55 diagnostics in 40 artifacts. The self-quoting A1 receipt adds 26 diagnostics in one additional exact blob. A human may explicitly approve this combined scope after reviewing it; execution authorization does not imply approval.

Every artifact below must remain byte-identical. A current range receipt and exact blob checks are prerequisites to applying any approval. Preserve raw command FAIL results. The proposal excludes Rust/test changes, build/configuration/CI changes, new A2 prose, every newly introduced raw artifact diagnostic, missing tests/coverage/receipts, inaccurate reports, the counter regression, and G10 acceptance. Any approved scope must be recorded exactly; no automatic extension is allowed.

Paths are relative to `docs/pr-artifacts/perf-06-c/`. Diagnostic line numbers refer to the listed complete Git blobs. “Trailing” means trailing whitespace; “EOF” means a new blank line at end of file.

| Artifact | Cohort | Exact diagnostics | Git blob |
|---|---|---|---|
| `PERF06C2F1_DETAILED_FIXUP_PLAN.md` | F1 | 3 trailing, 4 trailing, 5 trailing, 6 trailing, 7 trailing, 8 trailing, 9 trailing, 378 trailing, 853 trailing, 854 trailing, 1005 EOF | `5852dcf8952b9114f7e078c57b73075f977810e7` |
| `PERF06C2_DETAILED_PLAN.md` | original C2 | 3 trailing, 4 trailing, 5 trailing, 6 trailing | `b6f44a92a441305fa98993657a1688150c3e03e1` |
| `evidence/c2-coverage-all-features.txt` | original C2 | 11 EOF | `7e7bf4fc677874207223b3500ecb18f1a73d8fd6` |
| `evidence/c2-coverage.txt` | original C2 | 11 EOF | `4a0747e95a1cdc3f8e10bddd459f016b3c2ccb0e` |
| `evidence/c2-f1-baseline-integration.txt` | F1 | 16 EOF | `610ad72fadea70b12f66e8e629c052ce62198d92` |
| `evidence/c2-f1-baseline-physical.txt` | F1 | 12 EOF | `eb52df0bd9a644859fac638f9d79c66b49f2804c` |
| `evidence/c2-f1-baseline-unified.txt` | F1 | 30 EOF | `9c77c1e0f987c0ede769028122daeaffa756208f` |
| `evidence/c2-f1-i08-attempt-01.txt` | F1 | 8 EOF | `b27ba3ac34f7fe1fcce4ca581bbf731a262b7493` |
| `evidence/c2-f1-i08-attempt-02.txt` | F1 | 9 EOF | `e5ee7b573cac456f0e08d41f57492cd2e69a3c09` |
| `evidence/c2-f1-integration.txt` | F1 | 16 EOF | `05d3aad261b4affdc979c8cf3de11a0228f826fc` |
| `evidence/c2-f1-p05-attempt-01.txt` | F1 | 42 EOF | `6d985f6e1b8b035c67e80d7a3918f21a3325d257` |
| `evidence/c2-f1-p05-attempt-02.txt` | F1 | 14 EOF | `c68e1a83dc52a72665e038003b066dcce6a8f6b9` |
| `evidence/c2-f1-physical-parallel.txt` | F1 | 12 EOF | `7fe53722b331f4b8cda23353cd08c89f4a6b472e` |
| `evidence/c2-f1-physical-serial.txt` | F1 | 12 EOF | `0cef1307cf7aa829688ac30ab9446bce893c063c` |
| `evidence/c2-f1-regression-15h-a.txt` | F1 | 14 EOF | `39e20d1c28cbcaacdc911ec84b252ac9db10c990` |
| `evidence/c2-f1-regression-15h-a2.txt` | F1 | 16 EOF | `6a200df084e452526e6b5314f3e67bf27ec617d5` |
| `evidence/c2-f1-regression-b1-ordinals.txt` | F1 | 31 EOF | `814ea60dcccb5a0c7c5905f0166b6824b6118560` |
| `evidence/c2-f1-regression-b1-unit.txt` | F1 | 100 EOF | `4adabcfa7854df453d4790f45e93fbe13721b32b` |
| `evidence/c2-f1-regression-b2-ordinals.txt` | F1 | 16 EOF | `245ad7bd91bc73dc01430f360973cb399f7db7f7` |
| `evidence/c2-f1-regression-b2-unit.txt` | F1 | 66 EOF | `79d25512ca224a756f9a5bf6f620265e445fd493` |
| `evidence/c2-f1-regression-b3-keys.txt` | F1 | 16 EOF | `73b789710506ae6ec145a8a219d12bacd0537cdc` |
| `evidence/c2-f1-regression-b3-unit.txt` | F1 | 64 EOF | `626305dbafb0437eba35ef526397881379e8f56a` |
| `evidence/c2-f1-u12-attempt-01.txt` | F1 | 42 EOF | `8a2135f8795d57991aa73efb2606aa7c531884d0` |
| `evidence/c2-f1-u12-attempt-02.txt` | F1 | 14 EOF | `6ae93996129c05c73a880ec49b90ffce5f68897a` |
| `evidence/c2-f1-u17-attempt-01.txt` | F1 | 41 EOF | `05523fbb75edfc1ec6b8aba8ea04ec87ac2007e0` |
| `evidence/c2-f1-u17-attempt-02.txt` | F1 | 14 EOF | `09e2d8c388fc3a25624c188fdd6272c4a10a290e` |
| `evidence/c2-f1-u21-attempt-01.txt` | F1 | 36 EOF | `f0b8a58deeea22e270b96559b3b7038eec54983f` |
| `evidence/c2-f1-unified-parallel.txt` | F1 | 31 EOF | `5b44d04fa057c422bbdc50b04e8b36b6043f1106` |
| `evidence/c2-f1-unified-serial.txt` | F1 | 31 EOF | `376c0d1864f545face6ac4803540ba0b6d377c06` |
| `evidence/c2-integration.txt` | original C2 | 16 EOF | `d4554464f9ee0dc051bb3cded24b491b205d3a73` |
| `evidence/c2-regression-15h-a.txt` | original C2 | 13 EOF | `5eb35d63791af2007e05c3486cf7aff6c58c71bc` |
| `evidence/c2-regression-15h-a2.txt` | original C2 | 15 EOF | `2056815f513429b5cc0efdffa529c6862b18e721` |
| `evidence/c2-regression-b1-ordinals.txt` | original C2 | 7 trailing, 16 trailing, 30 EOF | `72ac7ab7ce3bfcf293697b241124cf08b1f9895f` |
| `evidence/c2-regression-b1-unit.txt` | original C2 | 72 EOF | `2049a5da7ce5b63800723d52e45729472bd5ec15` |
| `evidence/c2-regression-b2-ordinals.txt` | original C2 | 15 EOF | `8c96634b20af4fc2faab7cdb1a9a2293922cdfd0` |
| `evidence/c2-regression-b2-unit.txt` | original C2 | 38 EOF | `d5b08836d2c549ac340c0b6940ab645c5c00ea61` |
| `evidence/c2-regression-b3-keys.txt` | original C2 | 15 EOF | `10f987566e41ccf82bed394ccd029f4f3b6dc691` |
| `evidence/c2-regression-b3-unit.txt` | original C2 | 36 EOF | `6f930e6fdead63ef38a6072ccf3fa7ee521085b9` |
| `evidence/c2-unit-c2-parallel.txt` | original C2 | 45 EOF | `025af9004a402d1e995f70873f7b5e5b0bddaccd` |
| `evidence/c2-unit-c2-serial.txt` | original C2 | 45 EOF | `a756d55e3c62b05e23558c103bbb24752f1ebcd9` |
| `evidence/c2-f1-a1-whitespace-range.txt` | A1 new raw receipt | 11 trailing, 13 trailing, 15 trailing, 17 trailing, 19 trailing, 21 trailing, 23 trailing, 25 trailing, 27 trailing, 29 trailing, 61 trailing, 63 trailing, 65 trailing, 67 trailing, 69 trailing, 71 trailing, 73 trailing, 75 trailing, 77 trailing, 79 trailing, 82 trailing, 84 trailing, 86 trailing, 88 trailing, 120 trailing, 122 trailing | `6e30b575929d22652335f184c8fa7e3379dc52cd` |

## Appendix B. Exact lossless command-recorder script

Copy the following block, without the Markdown fence, to `docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-record.py`. Keep Appendix C's script beside it. Its exact UTF-8 file SHA-256 is `d1f71971f261d8591bc335ee6f63208b9e4043f26c3231377d8a16b60f0e50f0` (one final newline). The recorder imports the sibling verifier to validate the exact red source. For pinned final QA both helper files must already be committed and unchanged. An internal output must be a new authorized A2 evidence path; a terminal output may be a new path outside the checkout.

No `tee`, shell pipeline or environment dump is needed. The child command's real return code is returned. For T01, inspect and retain the expected nonzero result; do not let a blanket shell `set -e` discard its analysis or classify it as an unexpected gate failure. Source-identity failure returns a distinct failure status. If a destination already exists, use the next authorized attempt number; never overwrite it. An unapproved retry remains prohibited even when a new filename is available.

~~~python
#!/usr/bin/env python3
"""One-task lossless receipt: OUT.json MODE EXPECTED_HEAD -- command argv."""
import base64
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if not __debug__:
    raise SystemExit("Do not run this recorder with -O or PYTHONOPTIMIZE.")

# Import the supplied sibling verifier without generating an untracked .pyc file.
sys.dont_write_bytecode = True
HELPER_PATH = Path(__file__).resolve().with_name("c2-f1-a2-source-freeze.py")
spec = importlib.util.spec_from_file_location("c2_f1_a2_source_freeze", HELPER_PATH)
assert spec is not None and spec.loader is not None
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)
ALLOWED_RED = {freeze.READER, freeze.STORED}


def git(*args):
    return freeze.git(*args)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    out, mode, expected, delimiter, *command = sys.argv[1:]
    assert delimiter == "--" and command
    assert mode in {"red", "pinned"}
    assert re.fullmatch(r"[0-9a-f]{40}", expected)
    root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    assert Path.cwd().resolve() == root
    if mode == "red":
        assert expected == freeze.A2_START, "RED is pinned to the reviewed A2 START"
    destination = Path(out).resolve()
    assert destination.suffix == ".json"
    try:
        relative_output = destination.relative_to(root).as_posix()
    except ValueError:
        assert mode == "pinned", "only pinned terminal receipts may be written outside the checkout"
        receipt_location = "outside-checkout"
    else:
        assert relative_output.startswith(freeze.EVIDENCE_PREFIX)
        receipt_location = "repository-evidence"
    assert not destination.exists(), "never overwrite a receipt"
    destination.parent.mkdir(parents=True, exist_ok=True)

    def identity():
        actual = git("rev-parse", "HEAD").decode().strip()
        assert actual == expected, (actual, expected)
        untracked = freeze.paths(git("ls-files", "--others", "--exclude-standard", "-z"))
        assert all(path.startswith("docs/") for path in untracked), ("untracked source/build input", untracked)
        assert all(freeze.allowed_document(path) or path == freeze.FOREIGN_DOC for path in untracked), ("unapproved untracked document", untracked)
        # Cargo reads these files even when local ignore rules hide them from Git.
        for config in [".cargo/config", ".cargo/config.toml"]:
            if os.path.lexists(root / config):
                tracked = freeze.paths(git("ls-files", "-z", "--", config))
                assert tracked == {config}, ("untracked Cargo configuration, including ignored files", config)
        changed_docs = freeze.paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", expected, "--", "docs/"))
        assert all(freeze.allowed_document(path) for path in changed_docs), ("unapproved document change", changed_docs)
        patch = git("diff", "--no-ext-diff", "--no-textconv", "--binary", expected, "--", *freeze.SOURCE_PATHS)
        changed = freeze.paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", expected, "--", *freeze.SOURCE_PATHS))
        if mode == "pinned":
            assert not patch and not changed, "final QA requires committed, clean source/build inputs"
        else:
            assert changed == ALLOWED_RED, changed
            freeze.compare_red(
                freeze.blob(expected, freeze.READER),
                (root / freeze.READER).read_bytes().decode("utf-8"),
                freeze.blob(expected, freeze.STORED),
                (root / freeze.STORED).read_bytes().decode("utf-8"),
            )
        helper_hashes = {}
        for helper in [Path(__file__).resolve(), HELPER_PATH]:
            path = helper.relative_to(root).as_posix()
            assert path.startswith(freeze.EVIDENCE_PREFIX), ("helper outside prescribed artifacts", path)
            raw = helper.read_bytes()
            if mode == "pinned":
                assert freeze.blob_bytes(expected, path) == raw, ("uncommitted helper change", path)
            helper_hashes[path] = hashlib.sha256(raw).hexdigest()
        foreign = root / freeze.FOREIGN_DOC
        assert not foreign.is_symlink(), "unexpected symlink at the known foreign artifact"
        foreign_hash = hashlib.sha256(foreign.read_bytes()).hexdigest() if foreign.exists() else None
        return {"head": actual, "patch": patch, "helper_hashes": helper_hashes, "foreign_hash": foreign_hash}

    before = identity()
    env = os.environ.copy()
    removed = ["QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE", "RUST_TEST_THREADS"]
    for name in removed:
        env.pop(name, None)
    started = stamp()
    launch_error = None
    try:
        run = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        raw, command_exit = run.stdout, run.returncode
    except OSError as error:
        raw, command_exit, launch_error = b"", 127, str(error)
    ended = stamp()
    after = None
    identity_error = None
    try:
        after = identity()
        valid = after == before
        if not valid:
            identity_error = "source, helper or known foreign artifact changed during command"
    except (AssertionError, OSError, ValueError, subprocess.CalledProcessError) as error:
        valid, identity_error = False, str(error)
    payload = {
        "schema": "quervant-perf06-c2-f1-a2-receipt-v1",
        "mode": mode,
        "receipt_location": receipt_location,
        "command": command,
        "cwd": str(root),
        "source_commit": before["head"],
        "source_commit_after": after["head"] if after is not None else None,
        "source_patch_sha256": hashlib.sha256(before["patch"]).hexdigest(),
        "source_patch_base64": base64.b64encode(before["patch"]).decode("ascii"),
        "helper_scripts_sha256": before["helper_hashes"],
        "known_foreign_artifact_sha256_before": before["foreign_hash"],
        "known_foreign_artifact_sha256_after": after["foreign_hash"] if after is not None else None,
        "environment_keys_removed": removed,
        "started_utc": started,
        "ended_utc": ended,
        "command_exit_code": command_exit,
        "launch_error": launch_error,
        "source_identity_valid": valid,
        "source_identity_error": identity_error,
        "combined_output_encoding": "base64",
        "combined_output_sha256": hashlib.sha256(raw).hexdigest(),
        "combined_output_base64": base64.b64encode(raw).decode("ascii"),
    }
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
    print(json.dumps({"receipt": str(destination), "command_exit_code": command_exit, "source_identity_valid": valid}))
    sys.exit(command_exit if valid else 125)


if __name__ == "__main__":
    main()
~~~

## Appendix C. Exact source-freeze and red-state verifier

Copy this block verbatim to `docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-source-freeze.py`. Its exact UTF-8 file SHA-256 is `1fdd7fdcb46049d883ece1c40090932fd9460eb60bc1c57b7a038910f67d619b` (one final newline). This includes the full approved test region, so an early return, removed assertion, moved increment, alternate backend or broad “test module” exclusion cannot satisfy the source check.

The recorder calls the verifier's exact red-state check before and after T01. Before the final source commit, run the verifier's prescribed working-tree mode against literal A2_START. After committing final source, run its committed mode against A2_START and literal A2_TESTED. For the final terminal package, add literal H as the optional third revision. Capture each real invocation/result; do not print a fictional “PASS” line or replace a failed comparison with a hand inspection.

~~~sh
python3 docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-source-freeze.py --worktree-final cdffd5b486ce46312abf4c45c80b9d33ecbf657d
python3 docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-source-freeze.py cdffd5b486ce46312abf4c45c80b9d33ecbf657d A2_TESTED
python3 docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-source-freeze.py cdffd5b486ce46312abf4c45c80b9d33ecbf657d A2_TESTED H
~~~

`A2_TESTED` and `H` in these command templates are substitution markers for the recorded full SHA values, not Git ref names to invent. The second command runs through the recorder in pinned mode at A2_TESTED; the third runs through it at H with an outside-checkout output. The precommit working-tree check is an implementation check, not a substitute for the later immutable-source receipts. Preserve its actual output and invocation in the new source-scope record.

The complete changed-path allowlist protects all non-document source/build inputs, including `.cargo`, root tests and scripts. Historical evidence is compared as bytes, old reports/register as exact prefixes, and the original F1/A1 source comparisons remain active. Roadmap scope still requires the explicit manual C2-note-only diff review in §2. Do not change constants, templates, exclusions or assertions to accommodate a failure.

~~~python
#!/usr/bin/env python3
"""Exact A2 checks: START TESTED [FINAL_HEAD], or --worktree-final START."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if not __debug__:
    raise SystemExit("Do not run this verifier with -O or PYTHONOPTIMIZE.")

READER = "crates/quervant-core/src/segment/reader.rs"
STORED = "crates/quervant-core/src/segment/stored_blocks.rs"
UNIFIED = "crates/quervant-core/src/search/unified.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
F1_START = "46ccab0a606a56a8b9034ab4db5c9c4df969d098"
A1_START = "2bf9539cd2f53838ad1aca406ca4e67a34229ff6"
OLD_DECL = "#[cfg(test)]\npub(crate) static CERTIFICATE_BUILDS: std::sync::atomic::AtomicU64 =\n    std::sync::atomic::AtomicU64::new(0);\n\n"
TLS_LINE = "    static CERTIFICATE_BUILDS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };\n"
HELPERS = """#[cfg(test)]
pub(crate) fn record_certificate_build() {
    CERTIFICATE_BUILDS.with(|value| value.set(value.get() + 1));
}

#[cfg(test)]
pub(crate) fn certificate_builds() -> u64 {
    CERTIFICATE_BUILDS.with(std::cell::Cell::get)
}

"""
OLD_SITE = "        #[cfg(test)]\n        super::stored_blocks::CERTIFICATE_BUILDS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);\n"
NEW_SITE = "        #[cfg(test)]\n        super::stored_blocks::record_certificate_build();\n"
OLD_COMMENT = "    /// PERF-06-C2-F1: this segment's only key-identity attempt was refused, so the\n    /// accepted owned B2 key handler ran for it.\n"
NEW_COMMENT = "    /// PERF-06-C2-F1-A1: record selection of the accepted owned B2 key handler.\n    /// Refusal and ExactSet bypass are distinguished by config and B3 counters.\n"
SITE_A = "                    #[cfg(test)]\n                    if matches!(key_binder, KeyBinder::Fallback) {\n                        c2_observation::record_owned_key_fallback_segment(segment_index);\n                    }\n"
SITE_B = "        #[cfg(test)]\n        c2_observation::record_collected_segment(segment_index, heap.len(), *total_hits);\n"


A2_START = "cdffd5b486ce46312abf4c45c80b9d33ecbf657d"
SOURCE_PATHS = [".", ":(top,exclude)docs/**"]
DOC_ROOT = "docs/pr-artifacts/perf-06-c/"
A2_PLAN = DOC_ROOT + "PERF06C2F1_A2_CLOSEOUT_PLAN.md"
A2_REPORT = DOC_ROOT + "PERF06C2F1_A2_EXECUTION_REPORT.md"
EVIDENCE_ROOT = DOC_ROOT + "evidence/"
EVIDENCE_PREFIX = EVIDENCE_ROOT + "c2-f1-a2-"
OLD_REPORTS = [
    DOC_ROOT + "PERF06C2_EXECUTION_REPORT.md",
    DOC_ROOT + "PERF06C2F1_EXECUTION_REPORT.md",
    DOC_ROOT + "PERF06C2F1_A1_EXECUTION_REPORT.md",
]
SERIES = "docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md"
ROADMAP = "docs/PERF_OPTIMIZATION_ROADMAP.md"
APPEND_ONLY = [*OLD_REPORTS, SERIES]
EDITABLE_DOCS = {A2_PLAN, A2_REPORT, *APPEND_ONLY, ROADMAP}
FOREIGN_DOC = "docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt"
TEST_FIRST = "    #[test]\n    fn certificate_retains_flat_offsets_and_hot_path_is_direct() {"
TEST_FOLLOWING = "    #[test]\n    fn unselected_corruption_blocks_certificate() {"
DECOMPRESSED_TLS = "    static DECOMPRESSED_BLOCKS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };\n"
DECOMPRESSED_GETTER = "#[cfg(test)]\npub(crate) fn decompressed_blocks() -> u64 {\n    DECOMPRESSED_BLOCKS.with(std::cell::Cell::get)\n}\n\n"
RED_HELPERS = """#[cfg(test)]
pub(crate) fn record_certificate_build() {
    CERTIFICATE_BUILDS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
}

#[cfg(test)]
pub(crate) fn certificate_builds() -> u64 {
    CERTIFICATE_BUILDS.load(std::sync::atomic::Ordering::SeqCst)
}

"""

APPROVED_TEST = '    #[test]\n    fn certificate_retains_flat_offsets_and_hot_path_is_direct() {\n        use crate::segment::stored::test_observation;\n        use crate::segment::stored_blocks::certificate_builds;\n        let _serial = serial();\n        let bytes = v2_bytes(300);\n        let (state, _budget) = admitted_state(bytes.clone());\n        let reader = SegmentReader::from_shared(Arc::clone(&state));\n        test_observation::reset();\n        let builds_before = certificate_builds();\n\n        let sibling_delta = std::thread::scope(|scope| {\n            scope\n                .spawn(move || {\n                    // The parent holds serial(); the worker must not acquire it.\n                    let (sibling_state, _sibling_budget) = admitted_state(bytes);\n                    let sibling_reader = SegmentReader::from_shared(Arc::clone(&sibling_state));\n                    let sibling_before = certificate_builds();\n                    let selected = sibling_reader\n                        .stored_docs_selected(&[0, 299])\n                        .expect("sibling first access");\n                    assert_eq!(selected.len(), 2);\n                    assert_eq!(sibling_state.stored_blocks_offset_len(), Some(300 + 3));\n                    let sibling_after = certificate_builds();\n                    assert_eq!(sibling_after - sibling_before, 1);\n                    sibling_after - sibling_before\n                })\n                .join()\n                .expect("sibling certificate build")\n        });\n        assert_eq!(sibling_delta, 1);\n        assert_eq!(\n            certificate_builds() - builds_before,\n            0,\n            "a different thread\'s real certificate build must not change this thread\'s count"\n        );\n\n        let first = reader.stored_docs_selected(&[0, 299]).expect("first");\n        assert_eq!(first.len(), 2);\n        assert_eq!(state.stored_blocks_offset_len(), Some(300 + 3));\n        let builds_after = certificate_builds();\n        assert_eq!(builds_after - builds_before, 1);\n        // Warm direct access: one touched block, one selected record, no full scan.\n        test_observation::reset();\n        reader.stored_docs_selected(&[0]).expect("one");\n        assert_eq!(test_observation::direct_records(), 1);\n        assert_eq!(test_observation::hot_block_lookups(), 1);\n        assert_eq!(test_observation::full_scan_records(), 0);\n        assert_eq!(test_observation::local_id_reservations(), 0);\n        assert_eq!(test_observation::extra_outer_allocations(), 0);\n        assert_eq!(test_observation::selected_boundary_checks(), 1);\n        assert_eq!(test_observation::full_offset_pair_checks(), 0);\n        // Same block: one inflation, two direct records, one lookup.\n        test_observation::reset();\n        reader.stored_docs_selected(&[1, 2]).expect("same block");\n        assert_eq!(test_observation::direct_records(), 2);\n        assert_eq!(test_observation::hot_block_lookups(), 1);\n        assert_eq!(test_observation::local_id_reservations(), 1);\n        assert_eq!(test_observation::extra_outer_allocations(), 0);\n        assert_eq!(test_observation::selected_boundary_checks(), 2);\n        // Two blocks: two direct records, two lookups.\n        test_observation::reset();\n        reader.stored_docs_selected(&[0, 200]).expect("two blocks");\n        assert_eq!(test_observation::direct_records(), 2);\n        assert_eq!(test_observation::hot_block_lookups(), 2);\n        assert_eq!(test_observation::extra_outer_allocations(), 1);\n        assert_eq!(test_observation::local_id_reservations(), 0);\n        assert_eq!(test_observation::selected_boundary_checks(), 2);\n        // Empty selection after certification does no work.\n        test_observation::reset();\n        assert!(reader.stored_docs_selected(&[]).expect("empty").is_empty());\n        assert_eq!(test_observation::direct_records(), 0);\n        assert_eq!(test_observation::hot_block_lookups(), 0);\n        assert_eq!(test_observation::full_scan_records(), 0);\n        assert_eq!(\n            certificate_builds(),\n            builds_after,\n            "warm selected access must reuse the existing certificate"\n        );\n    }\n\n'


def git(*args):
    return subprocess.check_output(["git", "--no-pager", "-c", "color.ui=false", *args])


def paths(raw):
    return {item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item}


def blob_bytes(rev, path):
    return git("show", f"{rev}:{path}")


def blob(rev, path):
    return blob_bytes(rev, path).decode("utf-8")


def replace_once(text, token, replacement):
    assert text.count(token) == 1, ("unique literal required", token)
    return text.replace(token, replacement, 1)


def remove_once(text, token):
    return replace_once(text, token, "")


def region(text, first, following):
    assert text.count(first) == text.count(following) == 1
    a, b = text.index(first), text.index(following)
    assert a < b
    return a, b


def remove_region(text, first, following):
    a, b = region(text, first, following)
    return text[:a] + text[b:]


def without_c2_tail(text):
    first, last = "#[cfg(test)]\nmod c2_tests {", "// C2_TESTS_CLOSE_MARKER"
    assert text.count(first) == text.count(last) == 1
    a, b = text.index(first), text.index(last) + len(last)
    assert a < b and not text[b:].strip()
    return text[:a]


def compare_reader(old, new):
    a, b = region(old, TEST_FIRST, TEST_FOLLOWING)
    expected = old[:a] + APPROVED_TEST + old[b:]
    expected = replace_once(expected, OLD_SITE, NEW_SITE)
    assert new == expected, "reader must contain exactly the approved test and original-site helper substitution"


def expected_stored(old, red):
    assert old.count(OLD_DECL) == 1
    if red:
        return replace_once(old, DECOMPRESSED_GETTER, DECOMPRESSED_GETTER + RED_HELPERS)
    expected = remove_once(old, OLD_DECL)
    expected = replace_once(expected, DECOMPRESSED_TLS, DECOMPRESSED_TLS + TLS_LINE)
    return replace_once(expected, DECOMPRESSED_GETTER, DECOMPRESSED_GETTER + HELPERS)


def compare_stored(old, new):
    assert new == expected_stored(old, False), "stored_blocks must contain the exact TLS replacement at the prescribed anchors"


def compare_red(old_reader, red_reader, old_stored, red_stored):
    compare_reader(old_reader, red_reader)
    assert red_stored == expected_stored(old_stored, True), "RED must retain the global AtomicU64 and use exactly its prescribed helpers"


def normal_execute(text):
    return remove_region(text, "#[cfg(test)]\nmod c2_physical_tests {", "#[cfg(test)]\nmod budget_tests {")


def normal_unified(text, remove_sites):
    text = without_c2_tail(text)
    text = remove_region(text, "#[cfg(test)]\npub(crate) mod c2_observation {", "#[cfg(test)]\n#[allow(clippy::needless_option_as_deref)]\nmod tests {")
    if remove_sites:
        text = remove_once(remove_once(text, SITE_A), SITE_B)
    return text


def allowed_document(path):
    return path in EDITABLE_DOCS or path.startswith(EVIDENCE_PREFIX)


def changed_paths(start, end, *pathspec):
    return paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", start, end, "--", *pathspec))


def tree_paths(rev):
    return paths(git("ls-tree", "-r", "--name-only", "-z", rev))


def check_range(start, end, require_source):
    changed = changed_paths(start, end)
    outside_docs = {path for path in changed if not path.startswith("docs/")}
    expected_source = {READER, STORED} if require_source else set()
    assert outside_docs == expected_source, ("unapproved source/build-input change", outside_docs)
    assert all(path in expected_source or allowed_document(path) for path in changed), ("path outside the closed allowlist", changed)
    old_paths, new_paths = tree_paths(start), tree_paths(end)
    assert not (old_paths - new_paths), ("file deletion is not authorized", old_paths - new_paths)
    for path in old_paths:
        if path.startswith(EVIDENCE_ROOT):
            assert blob_bytes(start, path) == blob_bytes(end, path), ("historical evidence bytes changed", path)
    for path in APPEND_ONLY:
        assert blob_bytes(end, path).startswith(blob_bytes(start, path)), ("append-only document prefix changed", path)
    if A2_PLAN in old_paths:
        assert blob_bytes(start, A2_PLAN) == blob_bytes(end, A2_PLAN), "the supplied A2 plan changed"
    for path in new_paths - old_paths:
        assert path in {A2_PLAN, A2_REPORT} or path.startswith(EVIDENCE_PREFIX), ("new file outside A2 artifacts", path)
    return changed


def check_inherited(unified, execute):
    assert blob_bytes(A1_START, EXECUTE) == execute
    old_u = remove_once(without_c2_tail(blob(A1_START, UNIFIED)), OLD_COMMENT)
    new_u = remove_once(without_c2_tail(unified), NEW_COMMENT)
    assert old_u == new_u
    assert normal_execute(blob(F1_START, EXECUTE)) == normal_execute(execute.decode("utf-8"))
    assert normal_unified(blob(F1_START, UNIFIED), False) == normal_unified(unified, True)


def worktree_final(start):
    assert start == A2_START, ("unexpected A2 START", start)
    root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    assert Path.cwd().resolve() == root
    head = git("rev-parse", "HEAD").decode().strip()
    git("merge-base", "--is-ancestor", start, head)
    untracked = paths(git("ls-files", "--others", "--exclude-standard", "-z"))
    assert all(allowed_document(path) or path == FOREIGN_DOC for path in untracked), ("unapproved untracked path", untracked)
    for config in [".cargo/config", ".cargo/config.toml"]:
        if os.path.lexists(root / config):
            assert paths(git("ls-files", "-z", "--", config)) == {config}, ("untracked Cargo configuration, including ignored files", config)
    changed = paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", start))
    changed |= untracked - {FOREIGN_DOC}
    outside_docs = {path for path in changed if not path.startswith("docs/")}
    assert outside_docs == {READER, STORED}, ("unapproved source/build-input change", outside_docs)
    assert all(path in {READER, STORED} or allowed_document(path) for path in changed), ("path outside the closed allowlist", changed)
    old_paths = tree_paths(start)
    for path in old_paths:
        assert (root / path).exists(), ("file deletion is not authorized", path)
        if path.startswith(EVIDENCE_ROOT):
            assert blob_bytes(start, path) == (root / path).read_bytes(), ("historical evidence bytes changed", path)
    for path in APPEND_ONLY:
        assert (root / path).read_bytes().startswith(blob_bytes(start, path)), ("append-only document prefix changed", path)
    compare_reader(blob(start, READER), (root / READER).read_bytes().decode("utf-8"))
    compare_stored(blob(start, STORED), (root / STORED).read_bytes().decode("utf-8"))
    check_inherited((root / UNIFIED).read_bytes().decode("utf-8"), (root / EXECUTE).read_bytes())
    patch = git("diff", "--no-ext-diff", "--no-textconv", "--binary", start, "--", *SOURCE_PATHS)
    import base64
    print(json.dumps({"result": "PASS", "mode": "worktree-final", "A2_START": start,
        "worktree_HEAD": head, "normal_build_source_equal": True,
        "other_source_build_inputs_and_old_evidence_unchanged": True,
        "A1_and_original_F1_checks": "PASS", "changed_paths": sorted(changed),
        "source_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "source_patch_base64": base64.b64encode(patch).decode("ascii"),
        "roadmap_scope": "MANUAL_C2_NOTE_REVIEW_REQUIRED" if ROADMAP in changed else "UNCHANGED"}, indent=2))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worktree-final":
        worktree_final(sys.argv[2])
        return
    assert len(sys.argv) in {3, 4}, "usage: script A2_START A2_TESTED [FINAL_HEAD]"
    start, tested = sys.argv[1:3]
    final = sys.argv[3] if len(sys.argv) == 4 else tested
    assert all(re.fullmatch(r"[0-9a-f]{40}", rev) for rev in [start, tested, final])
    assert start == A2_START, ("unexpected A2 START", start)
    git("merge-base", "--is-ancestor", start, tested)
    git("merge-base", "--is-ancestor", tested, final)
    changed_tested = check_range(start, tested, True)
    compare_reader(blob(start, READER), blob(tested, READER))
    compare_stored(blob(start, STORED), blob(tested, STORED))
    check_inherited(blob(tested, UNIFIED), blob_bytes(tested, EXECUTE))
    changed_final = check_range(tested, final, False)
    check_range(start, final, True)
    identities = []
    for rev in dict.fromkeys([start, tested, final]):
        for path in [READER, STORED, UNIFIED, EXECUTE]:
            raw = blob_bytes(rev, path)
            identities.append({"revision": rev, "path": path,
                "git_blob": git("rev-parse", f"{rev}:{path}").decode().strip(),
                "sha256": hashlib.sha256(raw).hexdigest()})
    roadmap_changed = ROADMAP in changed_tested | changed_final
    print(json.dumps({"result": "PASS", "A2_START": start, "A2_TESTED": tested,
        "FINAL_HEAD": final, "normal_build_source_equal": True,
        "other_source_build_inputs_and_old_evidence_unchanged": True,
        "tested_to_final_docs_only": True, "A1_and_original_F1_checks": "PASS",
        "roadmap_scope": "MANUAL_C2_NOTE_REVIEW_REQUIRED" if roadmap_changed else "UNCHANGED",
        "changed_at_tested": sorted(changed_tested), "changed_after_tested": sorted(changed_final),
        "identities": identities}, indent=2))


if __name__ == "__main__":
    main()
~~~

## Appendix D. Exact complete existing-test replacement

Use this identical region in the temporary red state and final TLS state. It replaces the existing `#[test]` and target function through the blank line before `unselected_corruption_blocks_certificate`. Do not add a second registration. The verifier embeds this exact region. The worker receives owned fixture bytes; no reader or query-local interior state is transferred between threads.

~~~rust
    #[test]
    fn certificate_retains_flat_offsets_and_hot_path_is_direct() {
        use crate::segment::stored::test_observation;
        use crate::segment::stored_blocks::certificate_builds;
        let _serial = serial();
        let bytes = v2_bytes(300);
        let (state, _budget) = admitted_state(bytes.clone());
        let reader = SegmentReader::from_shared(Arc::clone(&state));
        test_observation::reset();
        let builds_before = certificate_builds();

        let sibling_delta = std::thread::scope(|scope| {
            scope
                .spawn(move || {
                    // The parent holds serial(); the worker must not acquire it.
                    let (sibling_state, _sibling_budget) = admitted_state(bytes);
                    let sibling_reader = SegmentReader::from_shared(Arc::clone(&sibling_state));
                    let sibling_before = certificate_builds();
                    let selected = sibling_reader
                        .stored_docs_selected(&[0, 299])
                        .expect("sibling first access");
                    assert_eq!(selected.len(), 2);
                    assert_eq!(sibling_state.stored_blocks_offset_len(), Some(300 + 3));
                    let sibling_after = certificate_builds();
                    assert_eq!(sibling_after - sibling_before, 1);
                    sibling_after - sibling_before
                })
                .join()
                .expect("sibling certificate build")
        });
        assert_eq!(sibling_delta, 1);
        assert_eq!(
            certificate_builds() - builds_before,
            0,
            "a different thread's real certificate build must not change this thread's count"
        );

        let first = reader.stored_docs_selected(&[0, 299]).expect("first");
        assert_eq!(first.len(), 2);
        assert_eq!(state.stored_blocks_offset_len(), Some(300 + 3));
        let builds_after = certificate_builds();
        assert_eq!(builds_after - builds_before, 1);
        // Warm direct access: one touched block, one selected record, no full scan.
        test_observation::reset();
        reader.stored_docs_selected(&[0]).expect("one");
        assert_eq!(test_observation::direct_records(), 1);
        assert_eq!(test_observation::hot_block_lookups(), 1);
        assert_eq!(test_observation::full_scan_records(), 0);
        assert_eq!(test_observation::local_id_reservations(), 0);
        assert_eq!(test_observation::extra_outer_allocations(), 0);
        assert_eq!(test_observation::selected_boundary_checks(), 1);
        assert_eq!(test_observation::full_offset_pair_checks(), 0);
        // Same block: one inflation, two direct records, one lookup.
        test_observation::reset();
        reader.stored_docs_selected(&[1, 2]).expect("same block");
        assert_eq!(test_observation::direct_records(), 2);
        assert_eq!(test_observation::hot_block_lookups(), 1);
        assert_eq!(test_observation::local_id_reservations(), 1);
        assert_eq!(test_observation::extra_outer_allocations(), 0);
        assert_eq!(test_observation::selected_boundary_checks(), 2);
        // Two blocks: two direct records, two lookups.
        test_observation::reset();
        reader.stored_docs_selected(&[0, 200]).expect("two blocks");
        assert_eq!(test_observation::direct_records(), 2);
        assert_eq!(test_observation::hot_block_lookups(), 2);
        assert_eq!(test_observation::extra_outer_allocations(), 1);
        assert_eq!(test_observation::local_id_reservations(), 0);
        assert_eq!(test_observation::selected_boundary_checks(), 2);
        // Empty selection after certification does no work.
        test_observation::reset();
        assert!(reader.stored_docs_selected(&[]).expect("empty").is_empty());
        assert_eq!(test_observation::direct_records(), 0);
        assert_eq!(test_observation::hot_block_lookups(), 0);
        assert_eq!(test_observation::full_scan_records(), 0);
        assert_eq!(
            certificate_builds(),
            builds_after,
            "warm selected access must reuse the existing certificate"
        );
    }

~~~

## Appendix E. Complete inherited final command catalog

These are 36 mandatory final invocations: four inventories, five focused C2 commands, five C2 suites, eight retained regressions and fourteen local QA commands. Together with §7's six final counter commands T02–T07 they make 42 final commands; the one expected-red T01 is separate. Do not also execute another optional counter catalog. Each command runs through Appendix B's recorder at the literal A2_TESTED SHA, from the repository root. The recorder removes both inherited experiment overrides from the child environment. Run sequentially against the same Cargo target directory.

For table ID `i01`, the exact invocation form is:

~~~sh
python3 docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-record.py docs/pr-artifacts/perf-06-c/evidence/c2-f1-a2-i01-attempt-01.json pinned A2_TESTED -- cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests:: -- --list --format terse
~~~

Substitute the recorded full A2_TESTED SHA. Apply the same wrapper with each table's exact child argv and its own lowercase ID; use `c2-f1-a2-t02-attempt-01.json` through `c2-f1-a2-t07-attempt-01.json` for §7's counter checks. Do not copy `A2_TESTED` literally as a SHA or change a child command's flags. Each selected set/count and case receipt must actually be checked. Inventory listing is separate from executing tests.

### E.1 Inventories — four commands

| ID | Child command after recorder `--` | Required registrations |
|---|---|---:|
| i01 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests:: -- --list --format terse` | 24 |
| i02 | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests:: -- --list --format terse` | 5 |
| i03 | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list --format terse` | 9 |
| i04 | `cargo +1.98.1 test -p quervant-core --lib c2_ -- --list --format terse` | 39 |

Parse only complete lines ending `: test`; remove that exact suffix, reject duplicates/empty sets, sort names, and retain the actual name sets. A2 adds no C2 function: unified/physical/integration sets must match the accepted A1 sets. The broad set is 29 C2 unit functions plus the same ten older accounting tests. Dedicated integration remains nine functions; U12's nine matrix rows are not nine registered functions. Do not apply the original F1 “one new U12 function” set-difference rule to A2, because U12 already exists at A2 START.

### E.2 Focused C2 cases — five commands

Each command must select exactly one function, with zero failures or ignores. Exit zero with no selected test is a failed verification command.

| ID | Child command after recorder `--` |
|---|---|
| f01 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u17_ordinal_unavailable_and_b3_refusal -- --exact --nocapture --test-threads=1` |
| f02 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u21_work_budget_exhaustion_after_prior_segment -- --exact --nocapture --test-threads=1` |
| f03 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u12_corrupt_selected_unselected_and_multi_fault -- --exact --nocapture --test-threads=1` |
| f04 | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p05_n_examination_and_scanned_frequency -- --exact --nocapture --test-threads=1` |
| f05 | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical c2_i08_resource_cancellation_atomicity -- --exact --nocapture --test-threads=1` |

Retain exact case evidence: U17 five B3/control rows plus the structural failure/recovery; U21 four caps 86/87/99/100 and its required three failure recoveries; U12 all nine ordered IDs and `completed=9`; P05 six exact resource rows and same-budget recovery; I08 exact resource/cancellation outcomes and complete retry parity. A successful function registration does not replace those assertions.

### E.3 C2 serial/parallel and real integration — five commands

| ID | Child command after recorder `--` | Required passed / ignored |
|---|---|---:|
| c01 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests:: -- --test-threads=1` | 24 / 0 |
| c02 | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests:: -- --test-threads=1` | 5 / 0 |
| c03 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests:: -- --test-threads=8` | 24 / 0 |
| c04 | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests:: -- --test-threads=8` | 5 / 0 |
| c05 | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --test-threads=1` | 9 / 0 |

The existing inherited all-features requirement is in the workspace commands below; the original F1 catalog has no separate all-features C2 module command. Do not invent extra variants through a vague “all applicable permutations” instruction.

### E.4 Retained regressions — eight commands

| ID | Child command after recorder `--` | Reviewed reference result |
|---|---|---|
| r01 | `cargo +1.98.1 test -p quervant-core --lib b1_` | 65 passed |
| r02 | `cargo +1.98.1 test -p quervant-core --lib b2_` | 31 passed |
| r03 | `cargo +1.98.1 test -p quervant-core --lib b3_` | 29 passed |
| r04 | `cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals` | 9 passed; 2 existing opt-in RustFS tests ignored |
| r05 | `cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals` | 8 passed |
| r06 | `cargo +1.98.1 test -p quervant-core --test perf06_b3_keys` | 8 passed |
| r07 | `cargo +1.98.1 test -p quervant-core --test pr15h_a_candidate_materialization` | 6 passed |
| r08 | `cargo +1.98.1 test -p quervant-core --test pr15h_a2_dispatch` | 8 passed |

Record actual selections/counts/ignored names. Reference counts are not copied results. Zero selection or an unexpected name-set/count change is a source/command discrepancy to resolve through an exact applicable matrix rule, otherwise STOP affected verification. Do not change filters, add ignores, or count ignored real-service registrations as executions.

### E.5 Complete local repository QA — fourteen commands

| ID | Child command after recorder `--` | Required evidence |
|---|---|---|
| q01 | `cargo +1.98.1 fmt --all -- --check` | Real exit status, including when output is empty |
| q02 | `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | Exit zero, no warnings |
| q03 | `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | Exit zero, no warnings |
| q04 | `cargo +1.98.1 test --workspace --all-targets` | Every target result, actual aggregate counts/ignores |
| q05 | `cargo +1.98.1 test --workspace --all-targets --all-features` | Every target result, actual aggregate counts/ignores |
| q06 | `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | Complete local coverage summary; total/covered/missed lines and actual percentage |
| q07 | `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | Complete all-features local coverage summary and actual percentage |
| q08 | `cargo +1.98.1 doc --workspace --no-deps` | Actual exit and relevant documentation output |
| q09 | `cargo +1.98.1 doc --workspace --all-features --no-deps` | Actual exit and relevant documentation output |
| q10 | `cargo +1.98.1 bench --workspace --no-run` | Compile only; no benchmark execution |
| q11 | `cargo +1.85.0 fmt --all -- --check` | Real exit status |
| q12 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | Exit zero, no warnings |
| q13 | `cargo +1.85.0 test --workspace --all-targets --all-features` | Every target result, actual counts, no repeated-to-green workaround |
| q14 | `bash benchmarks/scripts/test-scripts.sh` | Actual script output; reviewed reference is 108 passed script tests |

Both local coverage configurations must measure all applicable production Rust workspace code and be at least 85% lines, with no changed exclusions. Compute covered lines as total minus missed. Do not equate LLVM's total-line column with covered lines. A high percentage does not close correctness gates. Current CI coverage is separate evidence, not a substitute for these local receipts.

Prior A1 workspace totals (2739 default / 2784 all-features) and percentages are historical context. Report actual new results, not copied numbers. Ordinary workspace concurrency stays unchanged.
