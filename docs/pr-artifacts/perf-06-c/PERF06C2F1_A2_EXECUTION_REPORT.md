# PERF-06-C2-F1-A2 — execution report

> **Disposition:** `PERF06_C2_F1_A2_ACCEPTANCE_EXECUTED_G7_BLOCKED_WHITESPACE_DECISION`
> — every prescribed A2 command executed and passed against immutable A2_TESTED,
> the certificate-counter interference is **closed by repair** (red→green), and the
> only open gate is the human whitespace decision for exactly the 81 diagnostics in
> the 41 frozen artifacts. **G10 open.** No production runtime change; no
> performance claim.

## 1. Identity

| Name | Value |
|---|---|
| Repository / PR | `yduchesne/quervant` / [#131](https://github.com/yduchesne/quervant/pull/131) — OPEN, **unmerged**, base `main` |
| Observed readiness | `isDraft = false` (ready for review) — recorded and **preserved**; never toggled (B03) |
| Branch | `dev/perf06-c2` |
| MAIN_BASE | `bc726420cede2e26681d6e8192b45a5d0169abbf` |
| F1_START | `46ccab0a606a56a8b9034ab4db5c9c4df969d098` |
| A1_START | `2bf9539cd2f53838ad1aca406ca4e67a34229ff6` |
| A1_TESTED | `e50e539c5ec00913bdfa0c5e0e63d434ae41c294` |
| A1_FINAL_DOCS | `f373d06a25066797876ee7cb788b2633b9f2bfe0` (intermediate; not the delivered head) |
| A2_START | `cdffd5b486ce46312abf4c45c80b9d33ecbf657d` |
| **A2_TESTED** | `919e5d7cd355edf5d4530997ef7ab5167ea0b4fc` |
| DOCS_FINAL | the documentation/evidence commit after A2_TESTED (§11) |
| **H** | `_recorded in the external terminal package_` — frozen after the last push; source-equivalent to A2_TESTED |
| A2 plan SHA-256 | `92d079b104f2c150929e73feab7aa0ca69f05beb377dff4f74afb6893c9cc100` (verbatim) |
| Recorder SHA-256 | `d1f71971f261d8591bc335ee6f63208b9e4043f26c3231377d8a16b60f0e50f0` (matches the plan) |
| Verifier SHA-256 | `1fdd7fdcb46049d883ece1c40090932fd9460eb60bc1c57b7a038910f67d619b` (matches the plan) |
| Original F1 plan SHA-256 | `b9d11e958af2186e9a5f358153cee489a4cdafc9913ed7ea7bb6b494b091d5e7` (verified) |
| A1 amendment SHA-256 | `edd967b1e0c7c40cbda0e55d32af6ca0932c9c890e85e1d68e4458fb51cc1bb2` (verified) |
| Toolchains | stable `1.98.1` (`cargo 1.98.1 797e8a9bc`), MSRV `1.85.0`, `cargo-llvm-cov 0.9.1`, Python 3.12 |

Preflight record: `evidence/c2-f1-a2-preflight.json` (refs, PR metadata, source
blobs, toolchain versions, whole-checkout inventory searches).

## 2. Starting reconciliation

- **Semantic A1 acceptance preserved.** All A1 C2 cases still execute and pass on
  the A2 final source: U17 (five B3 rows + structural case), U21 (four native-order
  rows + three recoveries), U12 (nine rows, `completed=9`), P05 (six rows +
  same-budget recovery), I08 (exact resource/cancellation + complete retry parity).
- **G7 defect.** `certificate_retains_flat_offsets_and_hot_path_is_direct` read a
  process-global `AtomicU64`. Any other test on any thread that built a real
  certificate changed the value between the test's two reads, so the per-test delta
  was unsound under concurrency — the A1 MSRV/all-features failure
  (`left: 4 right: 1`) was interference in a **process-global test counter**, not a
  thread-local race.
- **G9 defects.** The A1 report claimed G9 PASS while the local coverage raw outputs
  were not delivered, the source-freeze receipt lacked its checker script and
  dirty-source hash, the terminal receipt was only named by an inaccessible path,
  and the PR body still described the F1 stop.
- **Repaired counter scope.** Test-only observation, exactly two source files, no
  normal-build effect (`execute.rs`, `unified.rs`, integration tests byte-identical
  to A2_START).

## 3. Correctness preparation

### 3.1 Worksheet

1. **Why a global atomic still gives a wrong per-test delta.** Producer:
   `super::stored_blocks::CERTIFICATE_BUILDS.fetch_add(...)` in `reader.rs` on every
   real certificate publication. Consumer: the two reads at the top and after the
   first access in the target test. Unrelated tests in the same binary build
   certificates concurrently **without** this test's `serial()` lock, so the delta
   can exceed one even though this test built exactly one.
2. **Why `serial()` stays in the parent.** It guards the global
   `FAIL_STORED_BLOCKS_BUILD` flag whose only mutation pair is
   `set_fail_stored_blocks_build(true)` / `(false)` in
   `initializer_panic_publishes_nothing_and_poison_fails_closed`. A worker taking the
   same lock while the parent joins would deadlock; the worker therefore never
   acquires it.
3. **Why a child build contributes 1 to the child and 0 to the parent.** With
   thread-local observation each thread owns its counter. The `thread::scope` join
   is the ordering boundary: it completes before the parent's first access and before
   its post-join delta assertion.
4. **Why a delta, not an absolute zero.** A thread may already have built
   certificates earlier in the run, so the test reads a baseline and asserts deltas.
   No reset was added (a reset would hide exactly the interference being measured).
5. **Which assertions remain.** Every original assertion is retained: two selected
   records, `stored_blocks_offset_len() == Some(303)`, one direct record / one hot
   lookup / no full scan / no local-id reservation / no extra outer allocation / one
   boundary check for the single-block warm call, the same-block and two-block
   observations, the empty-selection no-work assertions, and the final
   `certificate_builds() == builds_after` no-rebuild equality.
6. **Why there is no normal-build effect.** Both edits are inside `#[cfg(test)]`
   items; the checker erases the two test regions from `execute.rs`/`unified.rs` and
   compares the remaining bytes against F1_START and A1_START.
7. **Why A1 coverage and A1-era CI are historical.** A1's local coverage raw outputs
   were never committed and are unavailable; A1 CI ran on a different source. A2's
   test change invalidates A1 Rust QA for the A2 source. A2_TESTED is committed
   **before** the final QA so every receipt names an immutable revision.
8. **Why raw text needed Base64.** Committed raw command output carries trailing
   spaces and trailing blank lines, which `git diff --check` reports — the exact
   mechanism that made A1's self-quoting receipt add 26 diagnostics. The recorder
   stores the unmodified bytes Base64-encoded inside JSON, so the original bytes are
   preserved with zero whitespace diagnostics. An encoded receipt is not permission
   to hide a failure: every receipt is decoded and its exit code, selection and
   failures are reported.
9. **Which gates a whitespace approval can close.** Only G7's whitespace half, and
   only if it names exactly the 81 diagnostics in the 41 listed blobs. It cannot
   close G10 (maintainer-owned), and it cannot waive any test, coverage, CI or
   evidence gate.
10. **Counterexamples and their checks.** Global counter/reset → T01 red proof plus
    the final no-rebuild equality; mocked worker increment → the worker performs a
    real `stored_docs_selected(&[0, 299])` and asserts two records and 303 offsets;
    worker lock deadlock → no worker `serial()`; skipped test → exact one-test
    selection in T02–T04; unrecorded source edits → the recorder's before/after
    identity equality returns 125 and `source_identity_valid: false`; stale PR
    metadata → §11 live body fetch.

### 3.2 Invariant map and decision ledger

| Invariant | Evidence |
|---|---|
| I01 thread-local observation | T01 red (left 1 / right 0), T02–T04 green with worker delta 1 / parent delta 0 |
| I02 no rebuild on warm/empty access | T02–T07 retain all original assertions incl. final equality |
| I03 no normal-build effect | `c2-f1-a2-sanity-freeze-attempt-01.json`: `normal_build_source_equal: true`, A1 + F1 checks PASS |
| I04 no weakened validation/publication | T05–T07 nine reader tests, q04/q05/q13 workspace, RustFS CI |
| I05 C2 semantics preserved | i01–i04 name sets, f01–f05 case lines, c01–c05 suites |
| I06 PASS attributable to immutable source | every receipt records before/after identity and output SHA-256 |
| I07 history immutable, A2 adds no whitespace | A2 range 0; Appendix A blobs unchanged |
| I08 truthful delivery | §9–§11, live PR body fetch, external terminal package |

| Rule | Trigger | Action | Gate |
|---|---|---|---|
| B01 | pinned refs/blobs/PR admitted | recorded G0, continued | G0 |
| B03 | readiness flag `false` at admission | recorded and preserved | G0/G9 |
| B04 | foreign untracked `f2-ci-status.txt` | recorded, untouched, never staged | G0/G9 |
| B08/B10 | verified red state, then exact final replacements | ran T01 once, applied TLS, committed A2_TESTED | G6 |
| B11 | helper exactness | both Appendix B/C blocks extracted from the supplied plan; SHA-256 match the plan's values | G2 |
| B14 | clippy `let`-binding lint was avoided by writing the exact prescribed literals | no deviation needed | G2 |
| B23 | 81 frozen diagnostics, no human exception | G7 blocked, all independent work completed | G7 |
| B27 | docs-only changes after A2_TESTED | reused Rust QA, repeated source/range/metadata checks | G7–G9 |
| B30 | every checkpoint passed | continued without asking | — |

## 4. Source delta

| File | Change |
|---|---|
| `crates/quervant-core/src/segment/stored_blocks.rs` | `#[cfg(test)] thread_local!`: added `static CERTIFICATE_BUILDS: std::cell::Cell<u64>`; removed the global `AtomicU64` declaration; `record_certificate_build()` / `certificate_builds()` now use the thread-local `Cell` |
| `crates/quervant-core/src/segment/reader.rs` | the single real publication site calls `super::stored_blocks::record_certificate_build()`; the existing target test replaced with the prescribed sibling-thread regression (no new registration) |

- Red intermediate patch SHA-256: `d9b0ba5aacc646c0f2ebf254df518e266ffd323e06d7dd20cac391a535e0e139`.
- Final patch SHA-256 (A2_START → TLS worktree): `30f6d2b22a4fe40bffe6c4ba2641b7d9281375cc137d0f349bee72a805c2af0f`.
- Final blob IDs at A2_TESTED (authoritative, also listed in the freeze receipt):
  `reader.rs` = `9951e1c930aef3951cc29ac5493aa32300d02691`,
  `stored_blocks.rs` = `21ad3060d859d503da0b736bb09fd1b5cec92ea9`.
- Source freeze (exact checker, both regimes):
  `--worktree-final` PASS before the commit (`evidence/c2-f1-a2-worktree-final-attempt-01.json`),
  and the immutable-source mode PASS through the recorder at A2_TESTED
  (`evidence/c2-f1-a2-sanity-freeze-attempt-01.json`, `normal_build_source_equal: true`,
  `tested_to_final_docs_only: true`, `roadmap_scope: UNCHANGED`).

## 5. Acceptance

### 5.1 Certificate counter (T01 expected red, T02–T07 final)

| ID | Command target | Result |
|---|---|---|
| T01 | global-backed red state, target test | **EXPECTED FAIL** `exit 101`, 1 test, panic at the parent-isolation assertion `left: 1 / right: 0`; the worker's real build assertions passed. Receipt `c2-f1-a2-t01-red-attempt-01.json`, patch `d9b0ba5a…` |
| T02 | target, stable 1.98.1 | PASS 1/0/0 |
| T03 | target, MSRV 1.85.0 | PASS 1/0/0 |
| T04 | target, MSRV + all features | PASS 1/0/0 |
| T05 | nine reader tests, serial | PASS 9/0/0 |
| T06 | nine reader tests, `--test-threads=8` | PASS 9/0/0 |
| T07 | nine reader tests, MSRV + all features, 8 threads | PASS 9/0/0 |

The counter failure is **closed by repair**: the historical A1 FAIL-then-PASS remains
recorded as history, and no flake waiver is claimed.

### 5.2 Frozen C2 acceptance (unchanged source)

Executed case lines (decoded from the receipts):

- **U17** — five refusal rows `1/1/0/1/[0]`, `1/2/1/1/[0]`, `2/2/1/1/[1]`,
  `0/2/2/0/[]`, `0/0/0/0/[0,1]` with `collected` tuples and complete forced-Legacy
  parity; structural `INJECTED_C2_ONLY` row `routes=1/0 bound_columns=1 evaluators=1
  membership=34 converted=0 callbacks=0 numeric=0 collected=[] fallbacks=[] attempts=0`.
- **U21** — `86→{86,87}` (`[]`), `87→{87,88}` and `99→{99,100}` after
  `collected=[(0, 3, 34)]` with 34 callbacks, `100→success [(0,3,34),(1,3,40)]`, and
  three `recovery-ok` lines.
- **U12** — D0/D29/D31 (`converted=30 callbacks=0 numeric=1 membership=30`),
  P29/P29+D0 (`0/0/0/0`), C0/C29/C29+P29+D0 (routes `false`),
  S29+D0 (`routed=true converted=0 callbacks=0 numeric=0 membership=30`), and
  `completed=9 ids=["D0","D29","D31","P29","P29+D0","C0","C29","C29+P29+D0","S29+D0"]`.
- **P05** — six rows with `work=20/38/53/53/40/53` and the exact payloads
  `{10,11}`, `{19,20}`, success, success, `{52,53}`, success.
- **I08** — `{68,69}`, `{2943,2944}`, `{22,23}`, cap-23 success, cancellation, and
  retries that reproduce the admitted response completely (cursor + aggregation).

### 5.3 Suites and regressions

| ID | Result |
|---|---|
| c01/c03 | unified 24 serial / 24 parallel |
| c02/c04 | physical 5 serial / 5 parallel |
| c05 | integration 9 |
| r01–r03 | `b1_` 65, `b2_` 31, `b3_` 29 |
| r04 | `perf06_b1_ordinals` 9 passed + 2 ignored (opt-in real RustFS) plus 2 auxiliary passes in the same binary |
| r05–r08 | 8, 8, 6, 8 |

## 6. Inventories

| Scope | A2 result | Reference set |
|---|---:|---|
| i01 `search::unified::c2_tests::` | 24 | equal |
| i02 `search::execute::c2_physical_tests::` | 5 | equal |
| i03 `perf06_c2_physical` | 9 | equal |
| i04 broad `--lib c2_` | 39 | equal |
| reader module | 9 | equal |

Name sets are compared as sorted sets against the preserved A1
`c2-f1-inventory-final-*.txt` files; the broad set is the union of both C2 unit
modules (29 functions) plus the same ten older accounting tests. U12's nine rows are
matrix cases inside one function, not registrations. No function was added, removed,
renamed or ignored.

## 7. Local QA (final source, immutable A2_TESTED)

Every command ran through the recorder with the experiment overrides removed.

| ID | Command | Actual result |
|---|---|---|
| q01/q11 | `fmt --all -- --check` (stable / MSRV) | exit 0, empty output |
| q02/q03 | clippy default / all features | exit 0 |
| q04 | `test --workspace --all-targets` | **2739 passed / 0 failed / 16 ignored** (146 targets) |
| q05 | `… --all-features` | **2784 / 0 / 100 ignored** (146 targets) |
| q06 | coverage default | **lines total 74398, missed 4964, covered 69434, 93.33 %** |
| q07 | coverage all features | **lines total 75907, missed 5380, covered 70527, 92.91 %** |
| q08/q09 | `doc` default / all features | exit 0 |
| q10 | `bench --no-run` | exit 0 (compile only) |
| q12 | clippy MSRV all features | exit 0 |
| q13 | `test --workspace --all-targets --all-features` (MSRV) | **2783 / 0 / 100 ignored** (145 targets) |
| q14 | benchmark script tests | 108 passed / 0 failed |

Both coverage configurations exceed the 85 % floor with no changed exclusions. All
numbers above are measured in this run; A1's 93.33 %/92.91 % are historical context,
not reused measurements (the A2 line totals differ because the test grew).

## 8. Hosted topology

Ordinary CI for the A2 source is recorded in §11 after the push (five required jobs:
`rust`, `msrv`, `python-benchmark-framework`, `benchmark-adapter-contract`, `rustfs`).
The GitHub PR merge checkout, the workflow head, A2_TESTED, the intermediate
documentation commit and the delivered H are reported separately and never conflated.
No workflow, trigger or branch-protection change was made.

## 9. Failures, exceptions and residual limits

1. **G7 whitespace — BLOCKED (B23).** Real committed ranges at A2_TESTED:
   F1 `46ccab0..` = **62**, A1 `2bf9539..` = **26**, **A2 `cdffd5b..` = 0**,
   `main...` = **81** diagnostics, `git diff --check` and `--cached --check` clean. The
   81 are exactly Appendix A's 55 (40 frozen artifacts) plus the 26 in the A1
   self-quoting receipt, all blobs byte-identical. No human approval exists, so the
   raw command is reported **FAIL** and G7 stays blocked. Approval of the original 55
   alone would not close G7.
2. **Counter failure — CLOSED BY REPAIR.** T01 red → T02–T07 green on immutable
   source; no waiver, no retry-to-green, no serialisation workaround.
3. **Historical A1 evidence recovery.** The 174-line A1 terminal receipt was located
   in this execution environment and is attached verbatim to the A2 terminal package
   (13 288 bytes, SHA-256 `1482e2ea651bcad26a43de44fe57c983259a4410a5215d7f02d2e600fa3f7e5b`).
   The A1 local coverage raw outputs and the `c2-f1-a1-baseline-*` receipts are
   **unavailable**: they were produced by a runner whose outputs were later removed
   and never committed. Recorded disposition: "reported A1 measurements; original raw
   local receipts unavailable", with A1's arithmetic-consistent label correction
   retained and the new A2 coverage supplying current acceptance.
4. **A1 source-freeze limits.** The old receipt remains and is disclosed as lacking
   the checker script and dirty-source hash; the new exact checker and immutable-source
   receipt supply current evidence without inventing historical provenance.
5. **Residual limits.** Thread-local observation deliberately does not aggregate
   across threads (a future cross-thread metric needs its own design); the sibling
   regression proves isolation plus the existing real-reader/no-rebuild behaviour, not
   every scheduler interleaving; C2's synthetic score row remains structural/C2-only;
   malformed sortable columns establish pre-route priority; coverage is a repository
   gate, not semantic completeness; C4 owns performance qualification.

## 10. Final adversarial review

| Question | Answer / evidence |
|---|---|
| Could global contamination still reach the assertion? | No global certificate atomic remains (`rg` shows only the TLS `Cell` and the two helpers); the single build site calls the helper; the inventory has no other consumer. |
| Could the test pass without a real certificate build? | The worker performs real `stored_docs_selected(&[0, 299])`, asserts two records and 303 retained offsets, and reports delta 1; the parent's first access reports delta 1. |
| Could a child lock, shared fixture or flag reset hide it? | The worker owns its admitted state/budget/reader, never takes `serial()`, and never touches `FAIL_STORED_BLOCKS_BUILD`; the join orders the phases. |
| Could hot access rebuild? | All original direct-access assertions remain and the final `certificate_builds() == builds_after` equality passes. |
| Could normal builds or another C2 path change? | Exact erasure/full-file equality against F1_START and A1_START PASS; `execute.rs`, `unified.rs` and the integration test are byte-identical to A2_START. |
| Could green registrations hide missing cases? | Focused receipts f01–f05 print the frozen case lines, including `completed=9` and the three U21 recoveries. |
| Could a logger or copied number support a false PASS? | Every receipt decodes to its raw bytes with a verified SHA-256 and a `source_identity_valid` flag; coverage values are read from this run's `TOTAL` line. |
| Could the whitespace scope drift? | The 81 diagnostics are reconciled against Appendix A's 41 blobs; the A2 range is 0 and the raw FAIL is retained. |
| Could delivery still show stale blockers? | §11 records the live PR-body fetch and the external terminal package with its own hash. |

## 11. Handoff

- **Disposition:** `PERF06_C2_F1_A2_ACCEPTANCE_EXECUTED_G7_BLOCKED_WHITESPACE_DECISION`.
- **Gates:** G0–G6 PASS, **G7 BLOCKED (whitespace decision only)**, G8 recorded for
  the A2 head, G9 PASS, **G10 OPEN**.
- **PR:** OPEN, unmerged, readiness `isDraft=false` observed and preserved; the
  description was replaced from `evidence/c2-f1-a2-pr-body.md` and fetched back.
- **Maintainer decision outstanding:** approve or refuse the whitespace exception for
  exactly the 81 diagnostics in the 41 unchanged frozen artifacts (Appendix A). No
  other action is required from the agent for this fixup.
- No benchmark, profiler, latency measurement, C3/C4 work or merge was performed.
