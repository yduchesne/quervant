# PERF-06-C3-F2 execution report — test-only conformance and local acceptance

**Scope:** two existing test bodies plus bounded acceptance evidence. **No**
production change, new test, benchmark, profiler, C4 work, merge or readiness
change. Local gates executed on one immutable `F2_TESTED`; final-head CI and the
terminal package are supplied in the external handoff and the live PR body, not
in this commit. G10 remains maintainer-owned and open.

## 1. Immutable identities

| Name | Value |
| --- | --- |
| B (main, unchanged) | `6bc977e6a26c183609b7ca53eca51d3ab09ce337` |
| Original C3 RED | `0c295d1390869826c581a6c589d299cd13c4c99f` |
| Original C3 TESTED | `6ea6b7ce049d613a29864f1eae53dea5fd61e75f` |
| F1_START | `ee77917d303b060b0d38ab88e5d9ae73625f6676` |
| F1_TESTED / tree | `8f82f8290f838547dfc7d490f44ba8c0c8798d24` / `d22e2da175cb627a5e81b88905290d2a13958c11` |
| START (reviewed head, F1_DOCS_FINAL) | `051104724125ba95d49a6d94b61500f974a3599f` (tree `7d4221394e85c7414674018a9be129bd3549bb72`) |
| `F2_TESTED` | `` |
| `F2_TESTED` tree | `eb0695985f36bcb954e1da36e9f856b786f6640d` |
| `F2_DOCS_FINAL` / `F2_REMOTE_H` | external/pending; recorded in the terminal handoff, never guessed here |
| F2 plan SHA-256 | `08063c9e3e9f0589695d560db05a697ed6bf1352a059330ac521eb02e724912b` |
| Source diff SHA-256 (START..F2_TESTED, `--binary --full-index`) | `1e44141de2030780fa60640c2670fc51f86bf6e9bfd7ed5d1bbc0bf18c767bfe` |
| `apply_verify_f2.py` SHA-256 | `c612fff5e3674273e3e4957aa084bd57e274660146758af7c932c6732f00473b` |
| `build_f2_contract.py` SHA-256 | `278a391cca07fa10803a72279bf020dbd65fdb5d9b97f04b8b2bba4df993a614` |
| F2 command contract SHA-256 | `aacc2fb71199bda21f42bd27b72aea646096786518736c9ef51f58c253a54fa0` |
| F2 verification SHA-256 | `60aa2ad6709c08fc3603a1c469cc7385e61ad79652fb41c1a0d2395afe12d7d9` |
| F1 historical re-verification SHA-256 | `8cdb7f8b6d18ed1f9c9ac39d6a22774a42cef7cf03edecc2a9ab0abc5bce93c2` |
| Frozen F1 contract / verifier / recorder | `1107c78e…e545c4` / `f83e1ecc…16a8e7` / `5bbb38e1…0418d` |
| Exact test scope | `crates/quervant-core/src/search/unified.rs`: `c3_u02_dispatch_and_count_matrix` and `c3_u09_logical_budget_edges` only |

Toolchains: `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1`, `rustc 1.85.0`,
`cargo 1.85.0`, `rustfmt 1.9.0-stable (1.98.1)` / `1.8.0-stable (1.85.0)`,
`cargo-llvm-cov 0.9.1`, Python 3.12.3, host `x86_64-unknown-linux-gnu`.

## 2. Findings F2-01..F2-03

| ID | Original defect | Prescribed repair | Actual acceptance |
| --- | --- | --- | --- |
| F2-01 | The F1 nested `recover_at` helper in `c3_u09_logical_budget_edges` carried a new `#[allow(clippy::too_many_arguments)]`, contrary to F1 D08; F1 Clippy passed **with** that attribute present, so a green run never proved its absence. | Delete the nested helper, its doc comment and the attribute; inline the identical recovery operations at the single call site. | `apply_verify_f2.py` proves `recover_at(` and the attribute are absent from the reconstructed region and that no new `allow` attribute exists in either authorized function; four Clippy configurations pass with `-D warnings`. |
| F2-02 | The plain-batch row compared the normal response with a forced-Legacy response but never asserted that either aggregation was `None`; two identically wrong `Some` values would have satisfied parity. | Assert `response.aggregation.is_none()` and `reference.aggregation.is_none()` before completing the row; correct the `avgdl` comment. | Receipt `f2_fin_u02` emits `C3 F2 U02 plain-batch aggregation=none normal+legacy` after both literal assertions and the full parity check; the separate empty-aggregation row still requires its exact `Some` group. |
| F2-03 | The final F1 ZIP and Markdown were named and hashed in the PR body but their bytes were not supplied to the reviewer. | Recover and validate the historical archive honestly; deliver a complete new F2 terminal package with the actual attachment. | Historical F1 archive **recovered and fully validated** (archive SHA-256 matches `1774236f…36110`, Markdown SHA-256 matches `58f57299…f0c96`, `testzip()` clean, 23 payload members + manifest, every member digest and the embedded Markdown verified, START/F1_TESTED identities present). The F2 terminal package is produced and verified externally; its attachment status is reported in the final handoff (this environment supports paths and hashes, not uploads). |

F1's recorded QA remains valid evidence of the source it actually executed; it
cannot establish the absence of the suppression or the batch-`None` oracle, which
is exactly the gap F2 closes. No other F1 finding is reopened.

## 3. Worksheet answers

1. **Why did Clippy pass?** The F1 nested `recover_at` had ten parameters and was
   locally suppressed; `-D warnings` does not fail an explicitly allowed lint.
   A green Clippy run therefore never demonstrated the absence of a suppression.
   Inlining removes the lint target without changing behaviour.
2. **Why does full response parity not prove absence?** `c3_assert_full_response`
   compares aggregation values for *equality*, so two equally wrong `Some`
   results satisfy it. Only a literal `is_none()` on both responses establishes
   absence. The separate aggregation request must still be `Some(...)`.
3. **Which counters may change?** None. The new assertions only inspect values
   already produced, and the inlined recovery invokes exactly the same
   operations once per failing row. Route, membership, numeric, callback, score,
   identity and recovery counts are unchanged and were re-verified.
4. **Why is `avgdl = 24` wrong?** The common-keyword fixture indexes one `grp`
   token per document, so `n = df = 24` and the average field length is `1`;
   only the comment was wrong, and the scalar formula already used `1`.
5. **Which QA is reusable?** Only the historical *evidence*, the command
   contract and the helper scripts. Historical outcomes cannot be relabelled as
   F2, so all 45 final commands were re-executed on `F2_TESTED`. No baseline or
   RED reconstruction was needed or performed.
6. **Why is the final ZIP external?** Committing the final-head receipt would
   advance the very head it describes. Terminal evidence belongs outside the
   checkout, produced after the documentation commit and CI observation.
7. **If the historical F1 ZIP were lost?** It could not be reconstructed as an
   original-time receipt; the gap would be qualified explicitly and the new
   complete F2 package would still close current delivery. Here it was found,
   validated and is delivered unchanged in addition to the new package.

## 4. Source proof

`apply_verify_f2.py` derives the exact patch from the pinned START blob, proves
that formatting START reproduces it byte-for-byte, applies only the prescribed
substitutions, and normalizes with the pinned `rustfmt +1.98.1 --edition 2024
--emit stdout`. It then requires the formatter to preserve every byte outside the
two authorized function regions, that both regions actually change, and that no
new `allow` attribute appears.

| Fact | Value |
| --- | --- |
| START source blob | `eb1d1f31d7554bb99d030858e99b3d3d2946c2f7` |
| Raw prescribed patch SHA-256 | `5afa58259b4fe099b63306cceb9d645a5b49d421e6ef8079d35fd916fe429b12` |
| Formatter-normalized patch SHA-256 | `3cc656947533ed93d942f2993d6021edc8e710490e987f87c4629103662ecaf2` |
| Actual `unified.rs` SHA-256 at `F2_TESTED` | `3cc656947533ed93d942f2993d6021edc8e710490e987f87c4629103662ecaf2` |
| Protected-bytes SHA-256 | `0554361a819f52f47c1102e8ce8b6f794c45392fb9667e321ed9f37e28cef4aa` |
| Changed tracked paths START..F2_TESTED | exactly `crates/quervant-core/src/search/unified.rs` |
| New lint attributes | none |
| Test registration / inventory change | none |
| Production / other test bytes | identical to START (`normal_build_source_equal=true`, `all_other_test_bytes_equal=true`) |

`F2_TESTED` is a direct child of `START`; `F2_TESTED..F2_DOCS_FINAL` is
documentation/evidence only. Original C3 and all F1 artifacts are byte-identical
to START.

## 5. Repaired acceptance

- **U02** — 25 ordered `(K, row_index, M)` tuples for `M ∈ {0,1,K,K+1,K+2}`,
  five certified / twenty Legacy, split `c3_calls=10 eager_calls=12
  legacy_calls=12`, six completed ineligible sort/batch/aggregation rows, plus
  the new F2 plain-batch marker after two explicit `None` assertions and full
  reference parity.
- **U09** — twelve primary rows in the fixed order, seven failures, seven
  same-snapshot full-response recoveries against the independent generous
  control, and `U09-102-X` at `306/13056` → `Limit(13056, 13160)` with
  membership/numeric/callbacks `102/102/102` and scores/identities `100/100`.
- **S01/U04/U05/I02** — unchanged and re-executed: 24 isolated-df rows; nine
  literal descriptors with isolated `C29` and unarmed same-snapshot C3; four
  caps with three literal reference errors and four recoveries; five view
  phases with 198 every-hit oracles and 14/13/14/13/14 pages.

## 6. Per-command local QA

All 45 final commands executed once each on `F2_TESTED` = `` with a
clean tracked worktree and `QUERVANT_PR15I_D3C_STRATEGY` /
`QUERVANT_PR15I_D3C_PREFILTER_PROFILE` removed in the child environment. Each
receipt records argv, source identity, exit code, raw output size/SHA-256 and the
Base64 bytes; `evidence/c3-f2/verification.json` lists all 45 verified rows.

| Group | Receipts | Result |
| --- | ---: | --- |
| Focused acceptance | 6 | `f2_fin_s01`, `u02`, `u04`, `u05`, `u09`, `i02`: one test selected/passed each, markers present |
| Exact inventories | 5 | 24 / 5 / 52 / 26 / 12, name sets identical to F1 |
| C3 unit suite | 3 | 26/0/0 serial, 8-thread and MSRV+all-features |
| C2 unified / physical | 4 | 24/0/0 and 5/0/0, serial and 8-thread |
| Real filesystem integration | 1 | 12/0/0 |
| Score / reader modules | 2 | 19/0/0 and 9/0/0 |
| B1–B3 unit | 3 | 65/0/0, 31/0/0, 32/0/0 |
| B1–B3 real integration | 3 | B1 9/0/2 parent; B2 8/0/0; B3 8/0/0 |
| Historical regressions | 2 | 6/0/0 and 8/0/0 |
| Formatting | 2 | exit 0, empty output |
| Clippy | 4 | exit 0 with `-D warnings`, four configurations, no new suppression |
| Workspace tests | 4 | `2749/0/16` and `2794/0/100` parent totals on both toolchains |
| Coverage | 2 | Lines >= 85 % in both regimes |
| Documentation | 2 | exit 0, `--no-deps`, both configurations |
| Bench compile + scripts | 2 | compile only; 108 script checks passed |

### Measured line coverage (from the `Lines` column)

| Receipt | Total | Missed | Covered | Percent |
| --- | ---: | ---: | ---: | ---: |
| `f2_qa_cov_198` | 77673 | 5026 | 72647 | 93.53% |
| `f2_qa_cov_198_af` | 79183 | 5441 | 73742 | 93.13% |

Regions, functions and branches are separate columns in the receipts and are not
conflated with line coverage. The F1 figures (93.53 % / 93.13 %) are historical;

the F2 numbers differ slightly because the test bodies changed.

### Workspace scopes

- `f2_qa_test_185`: 146 Cargo target launches = 136 parent libtest + 10 Criterion test-mode; parent totals {'failed': 0, 'ignored': 16, 'passed': 2749}; observed child summaries {'failed': 0, 'ignored': 0, 'passed': 10}; child-output ambiguous = `false`
- `f2_qa_test_185_af`: 146 Cargo target launches = 136 parent libtest + 10 Criterion test-mode; parent totals {'failed': 0, 'ignored': 100, 'passed': 2794}; observed child summaries {'failed': 0, 'ignored': 0, 'passed': 10}; child-output ambiguous = `false`
- `f2_qa_test_198`: 146 Cargo target launches = 136 parent libtest + 10 Criterion test-mode; parent totals {'failed': 0, 'ignored': 16, 'passed': 2749}; observed child summaries {'failed': 0, 'ignored': 0, 'passed': 10}; child-output ambiguous = `false`
- `f2_qa_test_198_af`: 146 Cargo target launches = 136 parent libtest + 10 Criterion test-mode; parent totals {'failed': 0, 'ignored': 100, 'passed': 2794}; observed child summaries {'failed': 0, 'ignored': 0, 'passed': 10}; child-output ambiguous = `false`

Child summaries are recorded separately and are **not** unique parent tests. No
doctest target appeared in these `--all-targets` commands, so no doctest claim is
made. All required gates were rerun because test source changed; a green F1 run
cannot certify different test bytes.

## 7. CI and evidence

- **Historical F1 run** `45941531494` at START (`pull_request`, attempt 1,
  `success`, five jobs, merge checkout
  `45daca24bdd41ecec9d2bcc7e8edd2107380d658`) remains valid historical evidence
  and was independently re-verified only through its stored metadata and the
  historical F1 receipts (51 rows, `PASS`, JSON identical to the committed
  verification, tree linkage to `F1_START`/`F1_TESTED` confirmed).
- **Historical F1 terminal package** was recovered and validated as described in
  §2/F2-03 and is delivered unchanged with the F2 handoff.
- **F2 exact-head CI** and the final committed-range whitespace checks are
  produced after this documentation commit; the F2 terminal package is built
  outside the checkout afterwards and its hashes are reported in the final
  handoff and the live PR body. A receipt for a head cannot be committed into
  the commit it describes.

## 8. Rule ledger, failures and limitations

Applied rules: D01 (pins exact, branch at START), D03 (the pre-existing
untracked `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` hashed
`c286db99…e3e7c7` and left untouched), D04 (draft flag observed and preserved),
D08 (pinned formatter normalization only), D09, D12 (child-summary ambiguity
reported separately), D14, D16/D17 (historical F1 archive found and validated),
D19, D22. No HARD STOP triggered; D25 was never needed.

No required gate failed: all 45 receipts are `PASS`, the 45 historical F1
receipts re-verify as `PASS`, the Appendix A source proof passes at worktree,
`F2_TESTED` and post-QA, and all seven planned whitespace checks are empty.

Residual limits: F2 is test-only; the certificate remains sufficient rather than
necessary; TLS observations stay thread-local; synthetic/pre-route corruption
rows are labelled as such; the U09 `{13056,13160}` refusal is tied to the
observed x86_64 `FieldValues == 32` geometry; C4 owns warm performance and
layout/codegen qualification; G10 remains open; nothing was merged, approved or
marked ready, and no benchmark, profiler or baseline promotion occurred.
