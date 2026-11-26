# PERF-06-C2-F1-A1 — execution report

> **Disposition:** `PERF06_C2_F1_A1_ACCEPTANCE_EXECUTED_G7_BLOCKED_WHITESPACE_DECISION`
> — every prescribed A1 case executes and passes; **G7 remains blocked** by two
> maintainer-owned decisions (committed-range whitespace in frozen artifacts, and the
> known pre-existing `stored_blocks_reader_tests` certificate-counter flake).
> **G10 open.** No production change; no performance claim.

## 1. Identity

| Item | Value |
|---|---|
| Repository / PR | `yduchesne/quervant` / [#131](https://github.com/yduchesne/quervant/pull/131) — OPEN, **unmerged**, base `main` |
| PR readiness flag (fresh observation) | `isDraft = false` (ready for review) — recorded and **preserved** (A31); never toggled |
| Branch | `dev/perf06-c2` |
| MAIN_BASE | `bc726420cede2e26681d6e8192b45a5d0169abbf` (accepted C1) |
| F1_START | `46ccab0a606a56a8b9034ab4db5c9c4df969d098` |
| A1_START | `2bf9539cd2f53838ad1aca406ca4e67a34229ff6` |
| Historical F1 tested source | `564fd7853d41adc77c84c766f59e29bae113d7b0` |
| A1_TESTED | `e50e539c5ec00913bdfa0c5e0e63d434ae41c294` (source, tests, verbatim amendment) |
| A1_FINAL | the documentation/evidence commit after A1_TESTED (see §11) |
| REMOTE_VERIFIED | frozen in the terminal handoff receipt `perf06-c2-f1-a1-terminal-<H>.txt` |
| Original F1 plan SHA-256 | `b9d11e958af2186e9a5f358153cee489a4cdafc9913ed7ea7bb6b494b091d5e7` (verified) |
| A1 amendment SHA-256 | `edd967b1e0c7c40cbda0e55d32af6ca0932c9c890e85e1d68e4458fb51cc1bb2` (verified) |
| Toolchains | stable `1.98.1`, MSRV `1.85.0` |

Identity meanings (no historical label is reinterpreted): `BASE` here means
`MAIN_BASE`; `START` here means `A1_START`.

### 1.1 Source admission (executed)

```
$ git fetch origin main dev/perf06-c2
$ git rev-parse HEAD origin/dev/perf06-c2 origin/main
2bf9539cd2f53838ad1aca406ca4e67a34229ff6
2bf9539cd2f53838ad1aca406ca4e67a34229ff6
bc726420cede2e26681d6e8192b45a5d0169abbf
$ git merge-base --is-ancestor bc726420… HEAD   -> ANCESTOR_OK
$ gh pr view 131 --json state,isDraft,headRefName,headRefOid,baseRefName
{"state":"OPEN","isDraft":false,"headRefName":"dev/perf06-c2",
 "headRefOid":"2bf9539cd2f53838ad1aca406ca4e67a34229ff6","baseRefName":"main"}
$ sha256sum docs/pr-artifacts/perf-06-c/PERF06C2F1_DETAILED_FIXUP_PLAN.md
b9d11e958af2186e9a5f358153cee489a4cdafc9913ed7ea7bb6b494b091d5e7
```

A01 applied. A31 applied for the readiness flag (only the `draft` boolean differs
from the earlier observation; refs, base and open/unmerged state are unchanged).
A05 applied: the foreign untracked
`docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` was recorded, never staged.

### 1.2 Baseline (before any A1 edit)

Registered functions: unified 24, physical 5, integration 9, broad `--lib c2_` 39 —
all pass. These are regression baselines, **not** evidence for the A1 rows: U21 still
ran its old `saw_failure` sweep and U12 still called only six of nine rows.
Receipts: `evidence/c2-f1-a1-baseline-*.txt`, `evidence/c2-f1-inventory-*.txt`.

## 2. Starting defects and reconciliation

| ID | Defect at A1 start | A1 outcome |
|---|---|---|
| F1-01 | actual B3 refusal unarmed | preserved and strengthened — five exact refusal rows now compared with the complete-response helper |
| F1-02 | U21 table never implemented; U17 structural case absent | **CLOSED** — four native-order U21 rows plus three recoveries, and the U17 `INJECTED_C2_ONLY` no-eager-binding case |
| F1-03 | U12 executed six of nine rows | **CLOSED** — all nine rows execute with the exact ordered completion array |
| F1-04 | P05/I08 resource negatives | P05 untouched (frozen); I08 comparison strengthened to complete cursor + aggregation |
| F1-05 | inventory/identity/evidence attribution | **CLOSED** — corrected counts, errata, this report |

Root cause of the two earlier D14 stops is confirmed and now resolved by design
(not by fixture change): query segment order is the manifest order sorted by the
content-addressed `s-{sha256}` id, and `grp/common` is encoded compact-short
**positional**.

## 3. Correctness worksheet and rule ledger

| Worksheet item (amendment §3.6) | Answer |
|---|---|
| Why segment 0 has 34 documents | `IndexWriter::commit` sorts manifest refs by `segment_id`, and `support::meta_from_bytes` sets `segment_id = "s-{sha256(bytes)}"`; `s-920b6e02…` (34 docs) sorts before `s-f915efbf…` (6 docs). |
| Why the scanned total is 87 + 13 | Global document `i` has alpha frequency `1 + i % 4`; 6..39 sums to 87 and 0..5 sums to 13, total 100. |
| Why cap 87 fails requesting 88 | Segment 0 charges exactly 87 scanned occurrences and completes; the first posting of segment 1 then requests `87 + 1 = 88`. |
| Why doc 33 is the last first-segment score | Segment 0 holds global 6..39, so local doc ids 0..33; local 33 is the last row scored. |
| Why frequency byte 67 precedes unchanged positional bytes | Header `[0,8)`, document deltas `[8,38)`, frequencies `[38,68)`, positions `[68,218)`; the final frequency is at 67 and bytes 68..218 are preserved verbatim. |
| Why the combined column error must prevent deeper probes | Native v2 keyword dictionaries are validated eagerly at reader open, so `SegmentReader::open` cannot succeed on those bytes. |
| Why exact cursor equality is legitimate | Every comparison is the same snapshot, same request, same sort and same limits; the cursor is a deterministic value with `PartialEq`. |
| Why a worktree-only diff cannot prove a committed range clean | `git diff --check` skips untracked files, so it cannot see newly added plan/evidence files that were not yet committed. |

| Rule | Trigger | Action | Gate |
|---|---|---|---|
| A01 | refs/PR match pinned identities | admitted A1_START | G0 |
| A05 | foreign untracked file | recorded, untouched, never staged | G0/G9 |
| A06 | clippy `let`-binding lint in new U21 code | corrected only the local expression; reran focused + full QA | G2–G7 |
| A07 | prescribed assertions/rows had to be added verbatim | restored the amendment's exact design | G3/G4 |
| A13 | score arm must follow resets | resets precede `arm(33)`; `run_with` called directly; `strict()` never used inside the arm | G3 |
| A24 | committed-range whitespace diagnostics without a human exception | preserved the FAIL, prepared the exact scope reconciliation, G7 BLOCKED | G7 |
| A23 | known certificate-counter flake reproduced | first failure preserved, one identical repeat (green), two isolated BASE runs; gate still blocked | G7 |
| A26 | new A1 prose/exports whitespace | verified zero diagnostics from every A1 path (`A1_START..HEAD` = 0) | G7/G9 |
| A29 | checkpoints | continued automatically through all stages | — |
| A31 | readiness flag differs | recorded `isDraft=false`, preserved, G10 open | G0/G9 |

## 4. Complete-response comparisons and source delta

Added `assert_c2_f1_full_response` (projected hits, explicit `to_bits` score bits,
total, generation, view ordinal, **complete cursor**, aggregation) and used it for
U17 refusal parity, U12 pristine/recovery parity and every U21 success/recovery. I08's
`assert_same_response` now compares the complete cursor and aggregation too. Literal
expected keys/totals and separate cursor-present assertions are retained, so two
identically wrong routes cannot be the only oracle.

Files changed relative to A1_START:

| Path | Delta |
|---|---|
| `search/unified.rs` | `c2_tests` only: `assert_c2_f1_full_response`, `assert_native_boundary_fixture`, rewritten U21, U17 structural case, U12 nine-row completion + corrected proof/probe/guard, plus the two prescribed comment corrections |
| `tests/perf06_c2_physical.rs` | I08's local `assert_same_response` helper and its doc comment only (3 diff hunks inside `c2_i08_resource_cancellation_atomicity`) |
| docs | amendment, this report, errata, evidence, status links |

`execute.rs` is byte-identical to A1_START, including P05.

**Source-freeze receipt** (`evidence/c2-f1-a1-source-freeze.txt`):

```
execute.rs byte-identical to A1 START (frozen, incl. P05): PASS
unified trailing content after C2_TESTS_CLOSE_MARKER is whitespace only: PASS
A1 START contains the old observer comment exactly once: PASS
candidate contains the prescribed A1 comment exactly once: PASS
unified.rs non-test regions equal to A1 START (observer comments excluded): PASS
execute.rs normal-build equality vs F1 START: PASS
candidate contains F1 Site A exactly once: PASS
candidate contains F1 Site B exactly once: PASS
unified.rs normal-build equality vs F1 START (both sites removed): PASS
RESULT: PASS
```

## 5. Per-case acceptance

Every row resets `reset_witnesses()`, `b2_observation::reset()`,
`b3_observation::reset()` (and `reset_b3_counters()` where used) before its measured
query, and captures observations before any reference/retry call.

### 5.1 U17 — five actual B3 refusal rows + native structural case

| Case | fired | attempts | directories | refusals | fallbacks | collected |
|---|---:|---:|---:|---:|---|---|
| single refusal | 1 | 1 | 0 | 1 | `[0]` | `[(0,4,40)]` |
| first of two | 1 | 2 | 1 | 1 | `[0]` | `[(0,4,20),(1,4,40)]` |
| second of two | 2 | 2 | 1 | 1 | `[1]` | `[(0,4,20),(1,4,40)]` |
| all ready | 0 | 2 | 2 | 0 | `[]` | `[(0,4,20),(1,4,40)]` |
| ExactSet | 0 | 0 | 0 | 0 | `[0,1]` | `[(0,4,20),(1,4,40)]` |

Each row also asserts route 1/0, evaluator calls = segments, converted 40, callbacks
40, numeric 40, bound columns = segments, total 40, literal keys, cursor present, and
**complete** forced-Legacy parity.

`INJECTED_C2_ONLY — no-eager-binding structural evidence`, observed:

```
routes=1/0 bound_columns=1 evaluators=1 membership=34 converted=0 callbacks=0
numeric=0 collected=[] fallbacks=[] attempts=0
error=InvalidScore("injected C2 score failure")
```

Unarmed recovery: total 40, literal keys `doc000000/doc000001`, cursor present,
bound columns 2, evaluators 2, membership/converted/callbacks/numeric 40, collected
`[(0,3,34),(1,3,40)]`, complete forced-Legacy parity.

Receipt: `evidence/c2-f1-a1-u17.txt`.

### 5.2 U21 — exact native-order boundary table

| Row | Cap | Result | Evaluators | Membership | Converted | Callbacks | Numeric | Bound | Collected |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| U21-A86 | 86 | `ResourceLimit {86,87}` | 1 | 0 | 0 | 0 | 0 | 1 | `[]` |
| U21-A87 | 87 | `ResourceLimit {87,88}` | 2 | 34 | 34 | 34 | 34 | 2 | `[(0,3,34)]` |
| U21-A99 | 99 | `ResourceLimit {99,100}` | 2 | 34 | 34 | 34 | 34 | 2 | `[(0,3,34)]` |
| U21-A100 | 100 | success, total 40 | 2 | 40 | 40 | 40 | 40 | 2 | `[(0,3,34),(1,3,40)]` |

Every row asserts strict route 1 / Legacy route 0, the identical forced-Legacy
`ResourceLimit` payload for failures, and an independent same-snapshot recovery at
cap 100 with the full counter vector, literal keys, cursor, snapshot generation/view
and complete response parity (`evidence/c2-f1-a1-u21.txt`). `assert_native_boundary_fixture`
guards the 34+6 topology by exact segment ids, doc counts, keys, live masks and
persisted body norms before any measured query.

### 5.3 U12 — all nine rows

| ID | Exact error | routes | eval | conv | cb | numeric | membership |
|---|---|---|---:|---:|---:|---:|---:|
| D0 | `Segment(InvalidUtf8{"doc key"})` | 1/0 | 1 | 30 | 0 | 1 | 30 |
| D29 | same | 1/0 | 1 | 30 | 0 | 1 | 30 |
| D31 | same | 1/0 | 1 | 30 | 0 | 1 | 30 |
| P29 | `Segment(ZeroFrequency{doc_id:29})` | 1/0 | 1 | 0 | 0 | 0 | 0 |
| P29+D0 | same | 1/0 | 1 | 0 | 0 | 0 | 0 |
| C0 | `Index(Segment(InvalidUtf8{"keyword"}))` | 0/0 | 0 | 0 | 0 | 0 | 0 |
| C29 | same | 0/0 | 0 | 0 | 0 | 0 | 0 |
| C29+P29+D0 | same | 0/0 | 0 | 0 | 0 | 0 | 0 |
| S29+D0 | `InvalidScore("injected C2 score failure")` | 1/0 | 1 | 0 | 0 | 0 | 30 |

Final line: `C2-F1-A1 U12 completed=9 ids=["D0","D29","D31","P29","P29+D0","C0","C29","C29+P29+D0","S29+D0"]`.
The posting recipe asserts the 218-byte positional layout, patches exactly one byte
(relative 67), verifies the position bytes are unchanged, and the direct probe sees
docs 0..28 with `freq == 1` then `ZeroFrequency { doc_id: 29 }`. Column-present
combined rows run only the eager column probe. Every row also repeats the real fault
on the same immutable snapshot, compares the identical typed Legacy error, proves the
original committed bytes unchanged and compares the pristine recovery completely.
Receipt: `evidence/c2-f1-a1-u12.txt`.

### 5.4 P05 (unchanged) and I08 (strengthened)

P05's six rows remain exactly as verified (`total_used` 20/38/53/53/40/53, exact
payloads, zero ledgers, same-budget recovery) —
`evidence/c2-f1-a1-p05.txt`. I08 keeps its exact peak/one-under/scanned-22/scanned-23
cases and now compares the **complete cursor and aggregation** on every retry —
`evidence/c2-f1-a1-i08.txt`.

## 6. Inventories

| Scope | A1_START | A1_FINAL |
|---|---:|---:|
| `search::unified::c2_tests::` | 24 | **24** |
| `search::execute::c2_physical_tests::` | 5 | **5** |
| New C2 unit functions | 29 | 29 |
| `perf06_c2_physical` | 9 | **9** |
| Broad `--lib c2_` | 39 | **39** |

No name added, removed, renamed or ignored. U12 remains one function with nine fault
rows plus its pristine/control/retry cases.

## 7. QA (final source state)

All commands ran with
`env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE`;
receipts carry `BEGIN/END RAW OUTPUT`, real exit codes, timestamps and source identity.

| Command | Result |
|---|---|
| `cargo +1.98.1 fmt --all -- --check` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.98.1 test --workspace --all-targets` | PASS — 2739 passed / 0 failed / 16 ignored (146 targets) |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS — 2784 / 0 / 100 ignored |
| `cargo +1.98.1 llvm-cov … --fail-under-lines 85` | PASS — lines total 74368, missed 4964, covered **69404**, **93.33 %** |
| `… --all-features` coverage | PASS — lines total 75877, missed 5383, covered **70494**, **92.91 %** |
| `cargo +1.98.1 doc` (default + all features) | PASS |
| `cargo +1.98.1 bench --workspace --no-run` | PASS (compile-only) |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | **FAIL then PASS** — see §9.1 |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script tests |

Changed-module coverage: `search/unified.rs` 95.64 % lines, `search/execute.rs`
96.73 % lines. No exclusion added. Feature suites: unified 24 serial and 24 parallel;
physical 5 and 5; integration 9. Retained regressions: `b1_` 65, `b2_` 31, `b3_` 29,
`perf06_b1_ordinals` 9 (+2 ignored, opt-in real RustFS), `perf06_b2_ordinals` 8,
`perf06_b3_keys` 8, `pr15h_a_candidate_materialization` 6, `pr15h_a2_dispatch` 8.

## 8. CI and topology

Local acceptance uses the real path in every case: schema → analyzer → writer →
committed `MemoryDirectory`/`FsDirectory` bytes → snapshot → `UnifiedSearcher` → real
collectors; `ReaderSnapshot::for_test` only supplies ownership/identity for the
copied-and-rebuilt U12 containers. No mock decoder, scorer or directory substitutes
for it.

Ordinary CI on the A1 head: run
[45881618721](https://github.com/yduchesne/quervant/actions/runs/45881618721) at
`f373d06a25066797876ee7cb788b2633b9f2bfe0` — all five required jobs (`rust`, `msrv`,
`python-benchmark-framework`, `benchmark-adapter-contract`, `rustfs`) `pass`,
`conclusion: success`; the `rustfs` job executed 32 real-service test bodies with 0
failures. GitHub checked out the PR merge ref `8c3a9cb` (merge of the head into
`bc726420…`), which is recorded separately from the PR-head identity. Receipt:
`evidence/c2-f1-a1-ci-status.txt`. No workflow, trigger or branch filter changed.
Runs 45828518258 and 45825576316 are pre-A1 regression baselines only.

## 9. Failures, diagnostics and open gates

### 9.1 Known pre-existing certificate-counter flake (G7 blocker)

`segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct`
failed once in the MSRV all-features workspace run (`left: 4 right: 1`), then passed
on an identical repeat; two isolated `MAIN_BASE` runs also passed. The archived
receipt `evidence/c2-baseline-flake-pre-existing.txt` reproduces the same assertion
on pristine `bc726420` with no C2 code. Bounded diagnostics per policy:
`evidence/c2-f1-a1-flake-classification.txt`.

Classification: nondeterministic, pre-existing, in a protected module. **The gate
remains BLOCKED**; the later green result does not waive it (A23). No source, thread
count, filter or retry-to-green change was made.

### 9.2 Committed-range whitespace (G7 blocker)

`evidence/c2-f1-a1-whitespace-range.txt` records the real commands and failures:

| Range | Diagnostics |
|---|---:|
| `F1_START..HEAD` | 23 (frozen F1 artifacts only) |
| `A1_START..HEAD` | **0** |
| `MAIN_BASE...HEAD` | **55 across exactly the 40 Appendix A artifacts** |
| `git diff --check` (worktree) / `--cached` | 0 / 0 |

Reconciliation is exact: Appendix A declares 55 diagnostics across 40 artifacts, all
40 git blobs are byte-identical at HEAD (0 mismatches), and the measured set has 0
extra and 0 missing. The earlier F1 claim that "all 25 errors pre-existed and the F1
delta is clean" was **wrong** and is corrected in the errata; the old receipt is
preserved unchanged.

**G7 is BLOCKED** (A24): no explicit human exception exists. Appendix A is a
*proposal*; this report does not treat it as granted and does not report the command
as passing. Approving exactly that scope would change the row to *FAIL — authorized
exception* with G7 *satisfied with explicit exception*.

## 10. Final adversarial self-review

| Item | Answer |
|---|---|
| Native query order stayed 34+6; no fixture reorder/alternate corpus | YES — `assert_native_boundary_fixture` with exact ids/counts/keys |
| U21 has exactly four fixed rows and three same-snapshot recoveries; 87/99 prove prior `(0,3,34)` | YES — §5.2 |
| U17's five B3 rows remain; `arm(33)` after resets; exactly one column binding | YES — §5.1 |
| U12 final frequency is at relative 67, positions preserved, each decoded posting `freq == 1`, final error doc 29 `ZeroFrequency` | YES — §5.3 |
| Column-present combined bytes run only the eager column probe | YES — §5.3 |
| U12 prints `completed=9` only after the ordered completion array and all recoveries | YES — §5.3 |
| Same-snapshot comparisons include real cursor and aggregation values plus explicit score bits | YES — §4 |
| P05 and all runtime/protected paths unchanged; no new seam/registration/ignore | YES — freeze receipt |
| Local QA/coverage/case receipts/CI identify the final source; FAIL is not relabelled PASS | YES — §7, §9 |
| Reports preserve history, correct overclaims, distinguish functions/rows/CI | YES — errata §12 |
| G7 actually satisfied or explicitly excepted; G10 open | NO — G7 BLOCKED by two maintainer decisions; G10 OPEN |

Residual limits unchanged: score injections are structural C2-only evidence;
malformed columns establish the shared pre-route boundary; these fixtures do not
prove all formats/corpora; no new end-to-end B1 `NotAvailable` fixture; copied corrupt
segments never mutate durable storage; source isolation/correctness/coverage do not
prove performance (C4 owns it). C3/C4 unstarted.

## 11. Handoff

- **Disposition:** `PERF06_C2_F1_A1_ACCEPTANCE_EXECUTED_G7_BLOCKED_WHITESPACE_DECISION`.
- **Gates:** G0 PASS, G1 PASS, G2 PASS, G3 PASS, G4 PASS, G5 PASS, G6 PASS,
  **G7 BLOCKED** (whitespace decision + pre-existing flake), G8 recorded for the A1
  head, G9 PASS, **G10 OPEN**.
- **Closed:** F1-01, F1-02 (U21 + U17 structural), F1-03 (nine rows), F1-04, F1-05.
- **PR state:** OPEN, unmerged, readiness flag observed as `isDraft=false` and
  preserved; no approval, merge, review message or readiness toggle was performed.
- **Maintainer actions outstanding:** (1) grant or refuse the Appendix A whitespace
  exception for exactly those 55 diagnostics in those 40 frozen artifacts; (2) dispose
  of the pre-existing `stored_blocks_reader_tests` counter flake; (3) independent
  review and merge (G10).
- No benchmark, profiler, latency measurement or C3/C4 work was executed.

## PERF-06-C2-F1-A2 correction and superseding status (2026-11-26)

This section is append-only; every preceding byte of this report is preserved. It
supersedes the A1 statements listed below. The current record is the
[A2 report](PERF06C2F1_A2_EXECUTION_REPORT.md).

1. **The delivered A1 implementation does complete the previously blocked cases.**
   U17 (five B3 rows + structural row), U21 (caps 86/87/99/100 with three
   recoveries) and U12 (nine rows, `completed=9`) all execute and pass on the A1 and
   A2 sources; no D14 fixture amendment remains open.
2. **Whitespace arithmetic corrected.** At the historical receipt SHA the first
   range count was **36**, not 23 (the report's summary said 23). At A2_START the
   three old ranges measure **62 / 26 / 81**, where the 81 is Appendix A's 55 frozen
   diagnostics in 40 artifacts plus the 26 in this series' self-quoting
   `c2-f1-a1-whitespace-range.txt`. Those 26 are a **separate frozen scope**:
   approval of the original 55 alone does not close G7. A2's own range is **0**.
3. **A1 coverage receipts.** The reported A1 totals were arithmetic-consistent but
   their raw local receipts were never delivered and are now unavailable. Current
   acceptance comes from the fresh A2 measurement (lines 74398 total / 69434 covered
   / 4964 missed / 93.33 % default; 75907 / 70527 / 5380 / 92.91 % all features),
   which is a new measurement, not a reconstruction of A1.
4. **Source-freeze limits.** The A1 freeze receipt lacked its exact checker script
   and a dirty-source hash. The new `c2-f1-a2-source-freeze.py` supplies both
   regimes now; this does not invent the missing historical provenance.
5. **G9 was partial, not PASS.** Until the report corrections, the delivered local
   receipts, the live PR-body update and the outside-checkout terminal package were
   corrected, G9 was partial/blocked. The A1 report's `G9 PASS` therefore overstated
   delivery; §11 of the A2 report records the actual delivery evidence.
6. **Terminal and baseline recovery.** The A1 terminal receipt was recovered from the
   execution environment and is attached to the A2 terminal package (13 288 bytes,
   SHA-256 `1482e2ea651bcad26a43de44fe57c983259a4410a5215d7f02d2e600fa3f7e5b`) with
   its original generation timestamp; it was not regenerated. The A1
   `c2-f1-a1-baseline-*` receipts are unavailable and are qualified rather than
   backdated.
7. **Counter flake reclassified.** The failure was interference in a **process-global
   test counter** (`crt::segment::stored_blocks::CERTIFICATE_BUILDS`), not a
   thread-local counter race. A2 repairs it (thread-local observation, deterministic
   sibling-thread regression) and proves the retired mechanism's failure red-first;
   the historical FAIL-then-PASS remains recorded and is not retroactively waived.
8. **U12 wording.** The identical-Legacy-error claim applies to the real-byte rows
   (D0/D29/D31/P29/P29+D0/C0/C29/C29+P29+D0). `S29+D0` is the synthetic
   `INJECTED_C2_ONLY` row with unarmed shared-fault controls; it claims no equivalent
   Legacy score injection. U21's three required post-failure recoveries are distinct
   from its additional benign success follow-up call.
9. **Readiness.** The PR's observed readiness is `draft=false`; earlier text implying a
   draft state is historical. Workflow head, merge checkout, tested source,
   intermediate documentation commits and the delivered H are separate identities.
