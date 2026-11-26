## PERF-06-C2 — accepted test design, A2 verification closeout

The A1 amendment completed the native 34+6 segment boundary tests, all nine U12
corruption/precedence rows, actual B3 refusal coverage, and exact public
resource/retry comparisons. A2 preserves that C2 source and repairs the pre-existing
certificate test counter: test-only observation is thread-local, with a deterministic
real-reader sibling-thread regression and an exact no-rebuild assertion.

Plan: [`PERF06C2F1_A2_CLOSEOUT_PLAN.md`](https://github.com/yduchesne/quervant/blob/dev/perf06-c2/docs/pr-artifacts/perf-06-c/PERF06C2F1_A2_CLOSEOUT_PLAN.md).
Full evidence: [`PERF06C2F1_A2_EXECUTION_REPORT.md`](https://github.com/yduchesne/quervant/blob/dev/perf06-c2/docs/pr-artifacts/perf-06-c/PERF06C2F1_A2_EXECUTION_REPORT.md).
Historical reports are unchanged, with appended dated corrections.

### Verification

- **Counter regression.** Red first on the retired global mechanism (exit 101, one
  test, parent-isolation assertion `left: 1 / right: 0`), then green: the target test
  passes on stable, on MSRV and on MSRV + all features, and the nine-test reader module
  passes serial, with 8 threads and on MSRV + all features. Receipts:
  `evidence/c2-f1-a2-t01-red-attempt-01.json`, `c2-f1-a2-t02..t07-attempt-01.json`.
- **C2 inventories.** 24 unified, 5 physical, 9 integration, broad `--lib c2_` 39, and
  nine reader tests — name sets identical to the accepted A1 references; no function
  added, renamed or ignored. Focused cases re-executed: U17 (five B3 rows +
  structural), U21 (86/87/99/100 + three recoveries), U12 (nine rows, `completed=9`),
  P05 (six exact resource rows), I08 (exact resources + complete retry parity).
- **Local QA and coverage.** `fmt`, `clippy` (default + all features, stable + MSRV),
  `doc`, `bench --no-run` and 108 benchmark script tests pass. Workspace tests:
  2739 passed / 0 failed / 16 ignored (default), 2784 / 0 / 100 ignored (all features),
  2783 / 0 / 100 ignored (MSRV all features). Coverage: **93.33 %** lines default
  (74 398 total / 69 434 covered / 4 964 missed) and **92.91 %** all features
  (75 907 / 70 527 / 5 380).
- **Hosted regression.** Recorded in the A2 report; the five required jobs
  (`rust`, `msrv`, `python-benchmark-framework`, `benchmark-adapter-contract`,
  `rustfs`) are observed after the push, with the PR merge checkout, workflow head and
  delivered head reported separately.
- **Source.** A2_TESTED `919e5d7cd355edf5d4530997ef7ab5167ea0b4fc`; the supplied exact
  checker proves normal-build equality with A2_START in both regimes (only two
  `#[cfg(test)]` regions in `segment/reader.rs` and `segment/stored_blocks.rs` differ).
  Later documentation-only commits are linked by exact source equality.

### Outstanding acceptance

**G7 is blocked on one human decision.** The historical committed-range whitespace
check still fails with exactly **81 diagnostics across 41 unchanged frozen artifacts**
(Appendix A: 55 in 40 plan/receipt blobs plus 26 in the A1 self-quoting
`c2-f1-a1-whitespace-range.txt`). A2's own range introduces **0** diagnostics and the
worktree/staged checks are clean. The raw command remains reported as FAIL; no
exception has been granted, and approval of only the original 55 would not be enough.

No normal-build runtime change, benchmark execution or performance claim is included.
C3/C4 remain unstarted. The PR remains open and unmerged; observed readiness
(`ready for review`) was preserved. G10 independent review and maintainer acceptance
remain open.
