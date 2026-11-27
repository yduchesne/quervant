# PERF-06-C3-F1 — Acceptance repair and evidence closeout for PR #132

**Plan date:** 2026-11-26, America/Los_Angeles.

**Repository / branch / PR:** `yduchesne/quervant` / `dev/perf06-c3` / [#132](https://github.com/yduchesne/quervant/pull/132).

**Deliverable:** this implementation contract; it is not evidence that its fixes have run.

**Intended executor:** a coding agent following predetermined decisions.

**Dominant invariant:** each claimed acceptance row must exercise its named inputs and independently assert its required result, while the reviewed C3 production implementation remains byte-identical.

## 0. Execution contract and authority

Read this plan, the preserved C3 plan, `AGENTS.md`, `docs/TESTING.md`, and `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` before editing. This plan applies the guide's current-main inspection, in-progress reconciliation, correctness-first planning, continuous-execution rule, evidence taxonomy, and exception matrix. It narrows the remaining work under the C3 plan; it does not reopen its architecture.

**Continuous execution authorization:** Once assigned to execute this plan, continue from admission through implementation, prescribed checks, evidence, ordinary push to the existing branch, CI observation, PR-description reconciliation, and handoff without asking for routine reconfirmation. Successful preflight, passing checks, an AUTO-RESOLVE decision, or a phase transition are not permission checkpoints. Apply the exact matrix in §12 before an exception. Stop dependent work for a HARD STOP or essential missing dependency, and continue only the independent work explicitly identified there. Any unlisted condition is a HARD STOP for affected work; the coding agent may not invent a fallback, adjust an oracle, waive a gate, or redesign the implementation.

Preserve the observed PR readiness. Do not mark ready, convert to draft, merge, enable auto-merge, approve a review, request reviewers, or post conversation/review comments. Updating the existing PR description and pushing the prescribed commits are delivery actions when this plan is assigned for execution. Do not force-push or rewrite history.

### 0.1 Immutable identities

| Name | Exact value / role |
| --- | --- |
| `B` | `6bc977e6a26c183609b7ca53eca51d3ab09ce337` — fresh observed main, merge of C2 PR #131 |
| `START` | `ee77917d303b060b0d38ab88e5d9ae73625f6676` — reviewed C3 PR head; required F1 starting commit |
| Original `RED` | `0c295d1390869826c581a6c589d299cd13c4c99f` |
| Original `TESTED` | `6ea6b7ce049d613a29864f1eae53dea5fd61e75f` |
| Original tested tree | `ee12c6b576ebd877e46e56512d4e786ef76a41af` |
| Original plan SHA-256 | `69b1aeba951d13361936ef8ffed75f77ec88362d3c7a38727b4eedd684f9a755` |
| Original recorder SHA-256 | `5bbb38e1b4b7538c56e80eacf1f694de19ccbd49528333f95553fde4bf80418d` |
| Original manifest SHA-256 | `2f7478a2dc72fe955a8d245bade407b28194429aad33709166573bcc45b264ac` |
| Reviewed hosted run | `45925006538`, attempt 1, event `pull_request`, workflow head `START` |
| Hosted merge checkout | `592241ec0ad408f30cbe1a0ab6cc0b7968aa56b6` — merge checkout, not PR-head identity |

Use new names `F1_TESTED`, `F1_DOCS_FINAL`, and `F1_REMOTE_H` for this execution. Never overwrite the historical identities in prose or receipts. Commit IDs cannot be known before execution; derive them with Git, never substitute a branch name in an evidence identity.

### 0.2 Reviewed source anchors at START

| File | Git blob |
| --- | --- |
| `crates/quervant-core/src/search/score.rs` | `43a1c4f79a60c1255148571f96b6e5a0c93726f2` |
| `crates/quervant-core/src/search/execute.rs` | `dbc863219716475db21cbb9739bf52557c2e61c3` |
| `crates/quervant-core/src/search/unified.rs` | `541f3fda5b52d40ae7d9fde86ee68af890a89fd6` |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | `d4cd5293a56cc812829042458d6359c6babc233d` |
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` |
| `docs/TESTING.md` | `91c8643eaa041b0cb475949bcefa7c074ae27fe3` |
| `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |
| Original C3 execution report | `e9d3e03fd95ddd4c07581a8624791cf2ed89d1a3` |

The original plan/report are under `docs/pr-artifacts/perf-06-c/`; its evidence is under `docs/pr-artifacts/perf-06-c/evidence/c3/`. The latter entire directory is frozen during F1.

## 1. Review outcome, remaining delta, and evidence limits

The review inspected fresh main and immutable START, the four source/test deltas, all 75 selected receipts, the plan/recorder/manifest hashes, actual hosted status and RustFS logs, and protected production functions. It found no concrete production correctness defect. This does not claim an independent local Rust rerun by the reviewer.

Fresh main remains B. C3 changes four source/test files from B; the original TESTED-to-START range changes 156 documentation/evidence paths only. The existing implementation reuses prepared BM25, the validated posting allocation, existing candidate ledgers, the K+1 ordinal heap, B1/B2/B3, cursor finalization and selected projection. Those mechanisms stay frozen.

### 1.1 Required fix-ups

| ID | Observed defect / gap | Required delta | Classification |
| --- | --- | --- | --- |
| F1-01 | S01 df=0 and df>n rows also remove prepared IDF. They can pass through the missing-IDF refusal even with their advertised df guard broken. | Isolate each guard by retaining the valid base IDF; preserve the 24-row table and eager precedence checks. | Test-oracle defect |
| F1-02 | U02 executes M=[K−1,K,K+1,K+2,K+3], not the required [0,1,K,K+1,K+2]; several ineligible subcases discard results; the split logger reads a counter after Legacy reset. | Exact 25 tuples, complete existing ineligible/batch/aggregation assertions, captured C3 split count=10. | Acceptance and evidence defect |
| F1-03 | U04's named C29 also corrupts posting29; the S29+D0 unarmed check omits normal C3 on that same snapshot. | Exact nine mutation descriptors, isolated C29, explicit same-snapshot unarmed C3 check. | Fixture and recovery-acceptance defect |
| F1-04 | U09 permits observed success/failure and 0-or-K scores; U05/U09 reference errors can agree with each other without matching the literal C3 payload. | Freeze the twelve outcomes in §6, bind all three routes to literal errors/full responses, and accept the specifically documented projection checkpoint. | Test-oracle defect plus explicit plan-author correction |
| F1-05 | I02 paging retains keys but discards later-page scores/fields; only the new snapshot gets first-page wrapper comparison. | Every-hit input-derived oracle across all five view phases; full old/new wrapper parity except query fingerprint. | Integration-acceptance gap |
| F1-06 | Region coverage is labelled line coverage; all U04 rows are called real-byte-only; workspace prose incorrectly includes doctests. | Dated corrections, correctly parsed new coverage, accurate topology and test scope. | Reporting defect |
| F1-07 | Original delivery stopped while CI was running. CI has since succeeded, including real RustFS bodies. | Preserve the historical observation and add current evidence; verify ordinary CI again for the F1 delivery head. | Closeout work |

### 1.2 Preserve verified work

| Capability / evidence | Status at START | F1 treatment |
| --- | --- | --- |
| C3 certificate, deferred executor, frequency transport, finalizer and production fallback | DONE + VERIFIED by source review and recorded acceptance; no runtime defect identified | Byte-freeze; no redesign |
| Original 40→3 expected-red/green proof | DONE + VERIFIED | Reuse immutable RED receipt; do not recreate a production regression |
| S02/P01, U01/U03/U06/U07/U08/U10/U11/U12/U13/U14, I01/I03 | DONE + VERIFIED within their stated evidence classes | Preserve bodies; rerun through prescribed suites |
| S01/U02/U04/U05/U09/I02 | PARTIAL against the exact acceptance contract | Repair only named functions/helper |
| All 75 original selected receipts, original manifest and recorder | DONE + VERIFIED as historical execution evidence | Keep bytes unchanged; do not relabel old runs as fixed |
| Original local workspace QA | DONE + VERIFIED; actual line gates pass | New test changes require fresh QA at F1_TESTED |
| Hosted run 45925006538 | DONE + VERIFIED after the prior report | Historical supporting evidence; new head needs new ordinary CI |
| Current report/roadmap/register accuracy | PARTIAL | Append errata and new closeout report |
| Independent acceptance / merge | OPEN, maintainer-owned | Do not close G10 |
| C4 performance work | NOT STARTED | Remains out of scope |

An executed test with a wrong fixture is evidence that that written test ran, not that the planned row ran. Passing coverage is not proof of semantic completeness.

### 1.3 Current verified CI and historical metric correction

All five jobs of run 45925006538 now succeeded: `python-benchmark-framework`, `benchmark-adapter-contract`, `rustfs`, `rust`, `msrv`. The RustFS job is 140264172087; its log shows a healthy real service and actual named S3/remote/PIT/mutation/restart/proxy/crash tests. It contains 32 successful test-result summaries, summing to 65 passed, 0 failed and 0 ignored across repeated invocations. Do not describe that as 32 unique test bodies. The workflow metadata identifies START; the checkout identifies the separate merge commit above.

| Original coverage receipt | Total lines | Missed lines | Covered lines | Actual line coverage | Region coverage previously mislabelled |
| --- | ---: | ---: | ---: | ---: | ---: |
| `qa_cov_198.json` | 77,232 | 5,023 | 72,209 | 93.50% | 93.85% |
| `qa_cov_198_af.json` | 78,742 | 5,438 | 73,304 | 93.09% | 93.54% |

Both actual historical line percentages exceed 85%; do not call this a coverage failure. Each of the four workspace receipts has 146 Cargo target launches: 136 top-level libtest targets plus 10 Criterion test-mode bench targets. Top-level libtest totals are 2749/0/16 ignored for default and 2794/0/100 ignored for all-features, on both toolchains. Ten additional child-process summaries each report one passing test; summing every visible summary produces the previously reported 2759/2804. The bench targets contain 74 test-mode Testing/Success pairs, and no doctest target appears. Preserve all scopes separately; do not describe all-visible sums as unique top-level tests or benchmark measurements. F1 must derive its own metrics, not force these numbers.

## 2. Scope, ownership, and protected surfaces

### 2.1 Exact executable-edit allowlist

Only the following existing function bodies/signatures may differ from START. Keep registration names, `#[test]` attributes, module boundaries, test seams, imports, and all other bytes unchanged. Put any tiny assertion helper inside the authorized test function; do not add global helpers.

| File | Authorized functions |
| --- | --- |
| `crates/quervant-core/src/search/score.rs` | `c3_s01_certificate_matrix` only |
| `crates/quervant-core/src/search/unified.rs` | `c3_u02_dispatch_and_count_matrix`, `c3_u04_corruption_precedence`, `c3_u05_native_later_segment_boundary`, `c3_u09_logical_budget_edges` only, within `c2_tests` |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | `collect_pages` and `c3_i02_real_pit_update_merge_and_paging` only |

Six existing registered tests change; no test is added, removed, renamed, ignored, or filtered out. The helper remains specific to I02. Use qualified names inside authorized functions if an import is needed.

### 2.2 Documentation allowlist

New files:

- `docs/pr-artifacts/perf-06-c/PERF06C3F1_DETAILED_FIXUP_PLAN.md` — this supplied file verbatim.
- `docs/pr-artifacts/perf-06-c/PERF06C3F1_EXECUTION_REPORT.md`.
- `docs/pr-artifacts/perf-06-c/evidence/c3-f1/**` — bounded receipts, exact scripts, command contract, hashes and audits described below.

Append-only existing files:

- `docs/pr-artifacts/perf-06-c/PERF06C3_EXECUTION_REPORT.md`.
- `docs/PERF_OPTIMIZATION_ROADMAP.md`.
- `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`.
- `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` — dated acceptance-status note only; no normative-rule edit.

Keep each START document as an exact byte prefix. Historical statements are corrected by explicit dated errata, never silently rewritten. Preserve the original C3 implementation plan and the entire original `evidence/c3/**`.

### 2.3 Explicit non-goals

No change to normal-build Rust, `execute.rs`, scoring/proof bounds, decoder layout, candidate charges, resource limits, projection order, cancellation polls, duplicate policy, B1/B2/B3, cursor/PIT semantics, storage/segment format, indexing/compaction, objectstore/distributed crates, dependency/manifests/toolchains/workflows, build configuration, benchmark source/configuration, public API, or runtime observability. No benchmark execution, profiler, timing acquisition, C4, merge, baseline promotion, or historical whitespace exception.

There is no new durability transaction, index format, remote protocol, or cache ownership. The tests continue using existing real immutable snapshots and existing FsDirectory publication/reopen/compaction. Fault copies remain disposable test inputs; original committed segment bytes must remain unchanged.

## 3. Correctness contract and pre-implementation worksheet

| Invariant | Falsifiable requirement | Implementation / acceptance |
| --- | --- | --- |
| F-I01 Production freeze | Every byte outside the seven authorized function regions and allowlisted documentation is unchanged from START. | §2, §9 freeze audit; G2 |
| F-I02 Independent guards | S01 df rows contain a valid prepared IDF; each named df guard alone excludes the row. | §4; 24 ordered S01 rows; G3 |
| F-I03 Exact dispatch domain | U02 executes the fixed 25 ordered tuples, including duplicate M=1 at K=1; exactly five select C3. | §5.1; G3 |
| F-I04 Same-operation observation | Every printed counter was captured from the operation labelled, before any reference/reset. | §5.2 and all changed diagnostics; G3/G4 |
| F-I05 Fault exclusivity | C29 corrupts only column29; each of nine descriptors equals the literal table. | §5.4; G4 |
| F-I06 Literal failure oracle | C3, eager and Legacy independently match the prescribed error tuple; success uses complete response comparison. | §6; G4 |
| F-I07 Failure phase and atomicity | U09's specific projection failure after score finalization computes exactly 100 private scores then returns Err; no response is exposed. Earlier failures score zero. | §6 table and same-snapshot recovery; G4 |
| F-I08 Every-hit snapshot oracle | Every paged hit has the expected input identity, full projection and scalar score bits for its own snapshot, before and after mutation/compaction. | §7; G5 |
| F-I09 Evidence identity | Fresh command results name one immutable F1_TESTED, are losslessly hashed, and cannot be replaced by stale/zero-test/skipped results. | §8–§10; G6–G9 |
| F-I10 Accurate status | Coverage is read from Lines; synthetic/pre-route cases are labelled; pending, passed and maintainer acceptance remain distinct. | §10–§13; G7–G10 |

Before editing, answer these in the new report or an external worksheet later committed with it:

1. Which earlier predicate masks S01's df rows, and why must the IDF be retained from the valid base rather than recomputed for the invalid df?
2. List all 25 U02 tuples and the five eligible rows. Explain the two separate M=1 inputs for K=1.
3. Which reset contaminates the existing split diagnostic? Which values must be captured first?
4. Give the exact nine U04 mutation descriptors; identify which cases are pre-route and which is injected.
5. Trace U09 collection → finalization → projection. Derive 140 bytes per projected hit and requested 13160 at the 94th attempt. Explain why 104 is an excess, not a new charge.
6. Derive new I02 n=40, df=39 and total length=173, including the nonmatching updated document's length.
7. Explain why every expected I02 index must come from the input sequence, not by parsing only the returned key.
8. Explain the coverage column correction, 26-versus-17 C3 inventory, and why CI merge SHA differs from PR head.

Map each answer to source and planned assertions. Missing or contradictory safety-critical facts invoke the matrix; do not fill gaps with assumptions.

### Boundary and cross-component analysis

| Boundary / risk | Required treatment |
| --- | --- |
| Empty, singleton, K, K+1, K+2 | Literal U02 matrix at all five K values |
| Isolated versus competing corruption | U04 descriptor table, unchanged guarded byte mutators, same-snapshot recovery |
| One-under / exact / generous resources | Literal twelve-row U09 table; unchanged four U05 scanned caps |
| Early failure versus later projection failure | Exact phase-specific scores and typed errors; never broaden to 0-or-K |
| Old/new/compacted snapshot | Separate input-derived stats; actual cursor continuation; stale old cursor rejected on new snapshot |
| Concurrency / TLS | Existing serial and eight-thread suites; no new process-global observer or changed retry policy |
| Retry / interruption | Same-snapshot unarmed/generous recoveries, existing cancellation sweep and I03 retained |
| Partial I/O / crash / remote protocol | No implementation delta; existing hosted real RustFS regression remains required, not replaced by fakes |
| Unknown layout, fixture or source drift | Stop affected work; no recalculated cap/offset or alternate acceptance |
| Extra physical word / code generation | Existing accepted C4 measurement risk, not a measured performance result |

Residual limits: the certificate is sufficient rather than necessary; TLS observations do not aggregate other threads; U13 is structural; S29+D0 is injected; column failures precede dispatch; runtime performance remains unmeasured and owned by C4.

## 4. P1 — repair S01 guard isolation (F1-01)

**File/function:** `score.rs::tests::c3_s01_certificate_matrix`. No changes to `cert_stats`, `cert_base`, `certify_deferred`, the scorer, S02, or any production/test seam.

1. Preserve all 24 IDs, their order, lengths `[0,1,u64::MAX]`, base n=30/avgdl=2, and every other existing assertion.
2. In S01-03, construct n=30, avgdl=2, term alpha, df=0, **the valid base prepared IDF `prepare_idf(30,30)`**, unchanged lengths.
3. In S01-04, use the same base inputs except df=31. Again retain `prepare_idf(30,30)`.
4. Do **not** call `prepare_idf(0,30)` or `prepare_idf(31,30)` for those rows; that would produce the masking None again. Do not substitute a different arbitrary IDF.
5. Before checking refusal, assert the term exists, its df equals the literal row value, its IDF is Some, finite and in [0,64], and its IDF bits equal the base prepared IDF. Assert n=30 and avgdl bits=2.0. Then require `certify_deferred("alpha").is_none()`.
6. Retain S01-06 as the separate missing-IDF case. Add the directly specified eager check on the existing valid-df/missing-IDF object: `bm25_score("alpha",0,3)` returns positive-zero bits; its positive-tf call retains the exact missing-IDF error already tested. Do not change error text.
7. Preserve the 24-element completion list. Emit a short post-assertion line identifying df=0/31, IDF-present=true and both refusals, then the existing completed=24 line.

The test now distinguishes a missing df guard from the independent missing-IDF refusal. This is a test-input correction; no production-red experiment or guard removal is authorized.

## 5. P2 — exact dispatch and corruption acceptance (F1-02/F1-03)

### 5.1 U02: replace the matrix with these exact rows

**Function:** `unified.rs::c2_tests::c3_u02_dispatch_and_count_matrix`.

Iterate K in [1,10,31,32,100]. For each K iterate the literal array `[0usize,1,top_k,top_k+1,top_k+2]` with a row index 0..4. Do not derive M using a delta around K+1. Do not deduplicate.

Use the existing M=0 fixture of eight documents plus absent term; all other rows use `documents(M)` and common term. Preserve request construction, fresh fixtures, limits, duplicate configuration, full same-query forced-eager/Legacy comparisons and literal key/count/cursor assertions.

| Row ID | K | Row index | M | Required normal route | Returned hits | Cursor |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| U02-K1-R0 | 1 | 0 | 0 | Legacy | 0 | absent |
| U02-K1-R1 | 1 | 1 | 1 | Legacy | 1 | absent |
| U02-K1-R2 | 1 | 2 | 1 | Legacy | 1 | absent |
| U02-K1-R3 | 1 | 3 | 2 | Legacy | 1 | present |
| U02-K1-R4 | 1 | 4 | 3 | C3 | 1 | present |
| U02-K10-R0 | 10 | 0 | 0 | Legacy | 0 | absent |
| U02-K10-R1 | 10 | 1 | 1 | Legacy | 1 | absent |
| U02-K10-R2 | 10 | 2 | 10 | Legacy | 10 | absent |
| U02-K10-R3 | 10 | 3 | 11 | Legacy | 10 | present |
| U02-K10-R4 | 10 | 4 | 12 | C3 | 10 | present |
| U02-K31-R0 | 31 | 0 | 0 | Legacy | 0 | absent |
| U02-K31-R1 | 31 | 1 | 1 | Legacy | 1 | absent |
| U02-K31-R2 | 31 | 2 | 31 | Legacy | 31 | absent |
| U02-K31-R3 | 31 | 3 | 32 | Legacy | 31 | present |
| U02-K31-R4 | 31 | 4 | 33 | C3 | 31 | present |
| U02-K32-R0 | 32 | 0 | 0 | Legacy | 0 | absent |
| U02-K32-R1 | 32 | 1 | 1 | Legacy | 1 | absent |
| U02-K32-R2 | 32 | 2 | 32 | Legacy | 32 | absent |
| U02-K32-R3 | 32 | 3 | 33 | Legacy | 32 | present |
| U02-K32-R4 | 32 | 4 | 34 | C3 | 32 | present |
| U02-K100-R0 | 100 | 0 | 0 | Legacy | 0 | absent |
| U02-K100-R1 | 100 | 1 | 1 | Legacy | 1 | absent |
| U02-K100-R2 | 100 | 2 | 100 | Legacy | 100 | absent |
| U02-K100-R3 | 100 | 3 | 101 | Legacy | 100 | present |
| U02-K100-R4 | 100 | 4 | 102 | C3 | 100 | present |

Capture the normal-run witnesses before calling either reference. Certified rows use the existing `c3_assert_certified(M,K,1)`; normal BM25 calls equal K. Legacy rows require strict=0, Legacy=1, certificate attempts=0, deferred=0, eager-strict=0, no final identities, zero strict evaluator/membership/callback/converted witnesses, and actual BM25 calls=M. All rows require total=M and the existing literal first min(M,K) keys.

Collect ordered `(K,row_index,M)` tuples and compare with a separately written literal 25-tuple list matching the table; check completed=25, C3 rows=5, Legacy rows=20. A count alone is insufficient. Print each row only after its normal assertions and full reference comparisons. Include the captured normal route and score count.

### 5.2 U02: split observation and original ineligible cases

For the existing split fixture (3 nonmatches, 1 match, 11 matches), preserve the native constructors and K=10. Verify three physical segment counts form the multiset [1,3,11]; do not assume hash-sorted manifest order equals insertion order. Existing certified witnesses remain: three evaluator calls, twelve memberships/callbacks, ten final scores/identities, total12, first ten keys and cursor.

Immediately after the normal run, store `split_c3_calls` and require 10. Store eager and Legacy counts immediately after their respective runs and require 12 each. Print `c3_calls=10 eager_calls=12 legacy_calls=12` from these saved values after full comparisons. Never read the final live TLS counter as though it belonged to the first run.

Keep all twelve existing ineligible query shapes and their inputs, the actual after-cursor case, malformed sort and non-columnar failures. Preserve existing complete reference checks. For the six successful sort/batch/aggregation subcases that currently discard results, implement §5.3; do not replace the original request projection or API to make assertions easier.

### 5.3 U02: existing sort, batch and aggregation response contracts

The six rows are relevance, two sort fields, doc_id with Min, multi-valued tag with Min, plain batch, and empty aggregation. All use the existing 24-document common-term fixture and K=5. Their independently required logical result is:

- total_hits=24, exactly five hits with keys `doc000000` through `doc000004`;
- a cursor whose last key is `doc000004`;
- every hit has Some finite/nonnegative score with the exact scalar bits below;
- normal observation tuple (strict, Legacy, attempts, deferred, eager-strict)=(0,1,0,0,0), empty final identities, zero strict physical observations, and actual scorer calls=24.

The scalar oracle is fixed by input tf=1, dl=1, n=df=24, avgdl=1:

~~~rust
let idf = (1.0_f64 + (24.0_f64 - 24.0 + 0.5) / (24.0 + 0.5)).ln();
let expected_score = 0.0_f64
    + (idf * (1.0_f64 * (1.2 + 1.0))
        / (1.0_f64 + 1.2 * (1.0 - 0.75 + 0.75 * 1.0_f64 / 1.0_f64)));
~~~

Retain expression grouping and compare `.to_bits()`. For each hit use its literal expected position i=0..4 to construct field expectations from `document(i)`, not from the returned key.

| Existing row | Projection to preserve | Exact field order / values | Cursor sort values | Cursor score |
| --- | --- | --- | --- | --- |
| relevance | Fields(doc_id) | doc_id from input i | [] | Some(expected_score), compare bits |
| two_fields | Source | body, doc_id, js, loc, n, each from input i | Keyword(doc000004), I64(4) | None |
| doc_id Min | Source | same five stored fields | Keyword(doc000004) | None |
| tag Min | Source | same five stored fields | Keyword(t) | None |
| batch | Fields(doc_id) | doc_id from input i | Keyword(doc000004) | None |
| aggregation | Fields(doc_id) | doc_id from input i | Keyword(doc000004) | None |

`Document::get(name)` returns the field value suitable for the expected projection. Preserve the fixed field order. For ordinary sort rows, use the same request for `c3_run_legacy`, default limits and the same default duplicate configuration; require `c3_assert_full_response`, including complete cursor equality.

For plain batch, bind the returned `UnifiedResponse` from `search_with_batch`; use the existing real meter with all three limits 1,000,000. For its reference, reset observations, create a fresh identical meter, hold the existing RAII `ForceLegacy` guard, and invoke that **same batch method and same AST**. Assert the normal witnesses before reference reset, then complete response equality. Aggregation must be None.

For aggregation, keep `Aggregation::new()`, `search_with_batch_aggregation_retained`, default configuration and the fresh 1,000,000,000-per-dimension meter. This method returns `(UnifiedResponse,u64)`; destructure it, do not invent an accessor. The response has exactly one empty global group:

~~~rust
Some(crate::contract::aggregation::AggregationResult {
    groups: vec![crate::contract::aggregation::AggregationGroupResult {
        key: vec![0],
        components: Vec::new(),
        metrics: Vec::new(),
        frequencies: None,
    }],
})
~~~

Do not invent a Count metric; 24 is `response.total_hits`. Compare the full aggregation response against a same-method, same-AST ForceLegacy run with a fresh identical meter. Require retained bytes >0 and equal to that reference, without inventing a fixed byte total. Keep normal counters separate from reference counters. Print six completed row IDs and assert the fixed ordered ID list. No new top-level helper or test registration is needed.

### 5.4 U04: exact fault descriptors and same-snapshot recovery

**Function:** `c3_u04_corruption_precedence`. Preserve `CopiedSegment`, all existing guarded byte mutators/probes, the 32-document fixture, native snapshots, checksum/container rebuilding, error helper and pristine recovery.

Before executing rows, compare the row descriptor list with this literal ordered list. The tuple order is (ID, doc-key record, final-posting mutation, sort-column record, injected-score doc).

| ID | Doc key | Final posting | Sort column | Injected score |
| --- | ---: | --- | ---: | ---: |
| D0 | Some(0) | false | None | None |
| D29 | Some(29) | false | None | None |
| D31 | Some(31) | false | None | None |
| P29 | None | true | None | None |
| P29+D0 | Some(0) | true | None | None |
| C0 | None | false | Some(0) | None |
| C29 | None | false | Some(29) | None |
| C29+P29+D0 | Some(0) | true | Some(29) | None |
| S29+D0 | Some(0) | false | None | Some(29) |

Set `column_row.final_posting` to false unconditionally. Keep the explicitly combined row true. Build the descriptor array first, validate it, then execute each row once and retain the exact completed-ID comparison.

Do not modify the actual compact-short positional posting fixture: 218-byte payload, marker7, last frequency at offset+67. Unexpected layout or physical DOC_KEYS order is a HARD STOP. Retain the current combined-column probe ordering. Do not retune any mutator.

| Cases | Required error | Strict / deferred / eager | Membership / numeric / callbacks | Actual BM25 |
| --- | --- | --- | --- | ---: |
| D0,D29,D31 | exact nested InvalidUtf8, context doc key | 1/1/0 | 30/1/0 | 0 |
| P29,P29+D0 | exact ZeroFrequency, doc_id29 | 1/1/0 | 0/0/0 | 0 |
| C0,C29,C29+P29+D0 | exact Index→Segment→InvalidUtf8, context keyword | 0/0/0 | 0/0/0 | 0 |
| S29+D0, arm active | existing exact injected InvalidScore | 1/0/1 | 30/0/0 | 29 |

Every row retains Legacy-route=0 during its normal failing execution, certificate attempts=strict, converted=0 and no final identities. Byte-only rows retain repeated same-snapshot failure plus exact eager/Legacy error checks. All rows retain byte-equal pristine source and full pristine successful response recovery.

After dropping S29+D0's arm, add a **normal unarmed C3 run on that same corrupted snapshot** before or alongside its existing unarmed eager/Legacy checks. Reset all witnesses first. Require exactly D0's error, (strict,Legacy,attempts,deferred,eager)=(1,0,1,1,0), membership30, numeric1, callbacks0, converted0, actual BM25=0 and empty final identities. Do not replace it with the separate D0 row or a pristine recovery.

Classify the final nine as eight byte-only corruption cases plus one real key-byte fault combined with INJECTED_C2_ONLY. Three column cases fail before route dispatch; do not count them as C3 candidate execution. Completion evidence must print descriptor identity as well as observed result/counters.

## 6. P3 — deterministic resource oracles (F1-04)

### 6.1 Explicit amendment to the original U09 expectation

The original plan's requirement that any exact-peak failure have no final scores was too broad for the prescribed real request. This plan corrects that author assumption only for the literal row below. It does not authorize an executor-selected alternative or move production work.

The existing order is collection/heap finalization, then projection. On the reviewed 64-bit layout, `FieldValues` occupies 32 bytes. For the U09 doc_id-only projection, each returned hit charges 140 bytes: key/base 24+9=33, plus the projected field 32+6+32+24+(9+4)=107. After 93 projections the ledger has used 13020; the 94th requests 13160, exceeding 13056 by 104. The 104 is **not** a newly introduced charge.

Before running U09 rows, assert `std::mem::size_of::<crate::contract::document::FieldValues>() == 32`. Build `DocumentKey::new(bounded_key(0)).expect("key")` and the vector `[("doc_id".to_owned(), FieldValues::Single(FieldValue::Keyword(bounded_key(0))))]`; require the key string to have nine bytes and `projected_hit_bytes(&key, &fields) == 140`. That existing helper is already in scope through `super::*`; do not add an import or copy/alter its implementation. Unexpected geometry invokes D11; do not change the caps, charge function or expected error.

Require the pinned 1.98.1 and 1.85.0 toolchains, and record their full target metadata. The numeric expectation is tied to the verified layout; it is not a claim of an ABI-independent Rust enum size.

### 6.2 U09: exact twelve rows

Keep the existing `Fixture::new(&[body_documents(M)])`, `request_asc(term_body(),K)`, default duplicate configuration, and limit setters. Use this literal table; do not select an expected outcome by inspecting the result.

| ID | M | K | Entry cap | Byte cap | Required result | C3 calls / final identities | Callbacks |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| U09-3-E | 3 | 1 | 8 | 384 | ResourceLimit {8,9} | 0 / 0 | 0 |
| U09-3-B | 3 | 1 | 9 | 383 | ResourceLimit {383,384} | 0 / 0 | 0 |
| U09-3-X | 3 | 1 | 9 | 384 | success, total3, first1 key | 1 / 1 | 3 |
| U09-3-G | 3 | 1 | 9 | 1536 | success, total3, first1 key | 1 / 1 | 3 |
| U09-12-E | 12 | 10 | 35 | 1536 | ResourceLimit {35,36} | 0 / 0 | 0 |
| U09-12-B | 12 | 10 | 36 | 1535 | ResourceLimit {1535,1536} | 0 / 0 | 0 |
| U09-12-X | 12 | 10 | 36 | 1536 | success, total12, first10 keys | 10 / 10 | 12 |
| U09-12-G | 12 | 10 | 36 | 6144 | success, total12, first10 keys | 10 / 10 | 12 |
| U09-102-E | 102 | 100 | 305 | 13056 | ResourceLimit {305,306} | 0 / 0 | 0 |
| U09-102-B | 102 | 100 | 306 | 13055 | ResourceLimit {13055,13056} | 0 / 0 | 0 |
| U09-102-X | 102 | 100 | 306 | 13056 | ResourceLimit {13056,13160}, projection after finalization | 100 / 100 | 102 |
| U09-102-G | 102 | 100 | 306 | 52224 | success, total102, first100 keys | 100 / 100 | 102 |

For every normal row, capture witnesses before references. Require strict=1, Legacy=0, certificate attempts=1, deferred=1, eager-strict=0 and converted=0. Existing one-under tests retain zero callbacks/scores; exact and generous rows require all M membership events. On success, require the literal keys from `expected_ascending_keys(M,K)`, total=M, cursor present, K actual calls and K final identities. Compare **complete responses** against both same-query eager and Legacy references using `c3_assert_full_response`. Do not use `verdict()` as a success oracle; it checks too little.

On each failure, independently match exact `SearchError::ResourceLimit { limit, requested }` for the normal, eager and Legacy results against the table. Two references agreeing is insufficient. For U09-102-X also require 102 numeric candidates, 102 callbacks, 100 actual scores and 100 recorded identities before references; forced eager has 102 score calls. The public result is Err, so no partial page is available.

Remove the open-ended `actual.is_ok()`-selected expectation and `scores == 0 || scores == K` allowance from U09. The different, explicitly authorized cancellation rule in U10 remains unchanged.

After **each of the seven failing rows**, run the same snapshot unarmed with its G-row generous limits. Require the complete response to equal the independently executed G-row response for that M, literal count/keys/cursor, and `c3_assert_certified(M,K,1)`. A retry that checks only total_hits is insufficient. Keep twelve primary rows; record seven recoveries separately. It is permitted to obtain each M's generous control before its four rows; reset witnesses before each operation. Do not count the control/recovery as additional primary rows.

Implement a small nested assertion function if useful, with exactly this behavior: consume `SearchResult<UnifiedResponse>`, reject Ok, reject every error variant other than ResourceLimit, and compare (limit,requested) to the literal tuple. This function must not derive expected values from an actual result or a reference.

Preserve all actual budget release behavior. F1 does not insert a new ledger observer, allocation, accounting operation, or cancellation poll.

### 6.3 U05: bind references to the literal scanned errors

Keep all existing fixture ordering assertions, 34+6 physical documents, 87+13 posting occurrences, four row descriptors, native boundaries and captured normal witnesses.

| Cap | Required normal/eager/Legacy result | Normal C3 scores | Normal completed callbacks | Collected segments |
| ---: | --- | ---: | ---: | --- |
| 86 | ResourceLimit {86,87} | 0 | 0 | [] |
| 87 | ResourceLimit {87,88} | 0 | 34 | [(0,3,34)] |
| 99 | ResourceLimit {99,100} | 0 | 34 | [(0,3,34)] |
| 100 | success, total40, first2 keys, complete response parity | 2 | 40 | [(0,3,34),(1,3,40)] |

After the existing normal literal check, apply the same literal error assertion separately to the eager and Legacy results. Keep existing route checks and all four successful cap100 recovery/repeat comparisons. No source change, cap change, fixture rebuild, segment-order workaround or relaxed counter is authorized.

## 7. P4 — every-page I02 oracle (F1-05)

### 7.1 Fixed fixture, snapshots and expected statistics

Keep the real `FsDirectory` corpus, two committed slices 0..6 and 6..40, close/reopen, pinned snapshot, real mutation writer, commit/refresh, real compact/commit/reopen, K=3, ascending doc_id, body alpha and existing projection.

| Phase ID | Actual view and time | Expected input indices | df / n / total field length | Required pages / scored hits checked |
| --- | --- | --- | --- | --- |
| I02-OLD-BEFORE | pinned old, before mutation | 0..39 | 40 / 40 / 180 | 14 / 40 |
| I02-NEW | new snapshot after mutation | 0..40 excluding2,6 | 39 / 40 / 173 | 13 / 39 |
| I02-OLD-AFTER-MUTATION | same pinned old, after mutation | 0..39 | 40 / 40 / 180 | 14 / 40 |
| I02-COMPACTED | freshly reopened after compaction | 0..40 excluding2,6 | 39 / 40 / 173 | 13 / 39 |
| I02-OLD-AFTER-COMPACTION | same pinned old after compact/reopen | 0..39 | 40 / 40 / 180 | 14 / 40 |

The added old-after-mutation full paging invocation makes the pinned-view guarantee explicit at the publication boundary. All five use the same bounded helper. This is 198 per-hit oracle checks, distinct from extra first-page/reference searches.

First pages exercise the eligible normal search; cursor continuations retain the existing Legacy route. The 198 checks cover the complete public paging operation, not 198 deferred-score events. Do not claim otherwise.

Reuse `scoring_tf(i)=1+i%4`, `scoring_dl(i)=1+i%4+i%5`, `scoring_body`, `scoring_doc_key` and the existing independent `scoring_oracle` unchanged.

- Initial n=df=40, total180.
- Delete index2: tf3, dl5.
- Upsert index6 to exactly gamma: old tf3/dl4; new alpha tf0/dl1.
- Insert index40: tf1/dl1.
- New live-document n=40, alpha df=39, total180−5−4+1+1=173.
- Index6 contributes one length unit although it is excluded from matching results.

Do not compute the oracle from production `SnapshotStats`, prepared IDF, returned score, or decoded result identity. The immutable input table is the independent oracle.

### 7.2 Exact helper design

Change only the existing helper's signature/body to:

~~~rust
fn collect_pages(
    searcher: &UnifiedSearcher<'_>,
    base: &UnifiedRequest,
    expected_indices: &[usize],
    stats: (u64, u64, u64), // df, n, total field length
    label: &str,
) -> Vec<String>
~~~

Keep the existing function name and returned concatenated keys. The helper is specific to these K=3 phases; use a fixed hard cap of 20 pages inside it. No new public type or generalized paging framework.

Algorithm, in this order:

1. Destructure (df,n,total_length). Assert `expected_indices.len() as u64 == df`. Set collected keys empty, cursor=None, pages=0, checked_hits=0.
2. Before each search assert pages<20, so a twenty-first query is never executed. Clone base; set `after` to the current actual cursor; execute the existing search with a fresh `Budgets::new()` and `NeverCancel`.
3. Assert total_hits=df. Let offset be the number already collected; assert offset<=expected_indices.len(). Expected page length is min(3, expected_indices.len()−offset). Assert actual length equals it. Do not accept an empty intermediate page.
4. For each hit at rank r, obtain i from `expected_indices[offset+r]`. Require key=`scoring_doc_key(i)`. Require exactly the ordered projection [(doc_id, Single Keyword(scoring_doc_key(i))), (body, Single Text(scoring_body(i)))]. Compare the entire field vector, not just presence.
5. Require score Some, finite and nonnegative. Compare its bits to `scoring_oracle(scoring_tf(i),scoring_dl(i),df,n,total_length).to_bits()`. Increment checked_hits only after all assertions.
6. Append those verified keys. Increment pages and assert <=20. Require cursor presence iff collected count is still less than expected_indices.len(). On Some, continue using that returned cursor; on None, break. Keep the current searcher for the whole phase.
7. Assert concatenated keys equal the literal input-derived expected sequence, no duplicates, checked_hits=df and pages=14 for df40 or 13 for df39. Reject any other df in this helper. Print phase, df,n,total_length,pages,checked_hits only now.
8. Return the keys, preserving the caller's explicit sequence checks.

No manual cursor construction, stale-cursor suppression, key parsing as the sole oracle, score recomputation through production scoring, or cross-snapshot cursor equality is allowed.

### 7.3 I02 caller changes and reference parity

Use the table's exact expected index vectors and stats for all five invocations. Retain the current first-page exact scalar checks as useful direct first-page assertions; do not remove a strong existing assertion because the helper also covers it.

For both old and new first pages, execute the existing same-snapshot `legacy_text_query("body","alpha")` wrapper with K3, ascending doc_id and the same projection. Use existing `assert_response_except_cursor_fingerprint` for complete response/field/score/snapshot/cursor comparison. The wrapper changes AST fingerprint legitimately. Do not compare its entire cursor for equality or weaken other cursor fields. Add the missing old-view reference; strengthen the existing new-view comparison.

Retain:

- exact `CursorPitMismatch` for an old cursor used on the new snapshot;
- complete pinned first-page equality before/after publication and compaction;
- fresh reopened compacted view, exact new logical result, first-page score equality;
- old and new immutable views simultaneously alive;
- actual native commit/reopen topology.

Compaction may change physical segment identity and snapshot cursor binding. Compare logical input identity, fields and scalar bits across views; only compare full response/cursor identity within the same snapshot. There is no new durability, crash or remote test requirement beyond the existing regression gates.

## 8. Ordered execution and authoritative commands

### 8.1 Admission and baseline

Run from the existing repository root. Use task-specific variables such as `C3F1_START`, `C3F1_TESTED`, `C3F1_DIR`; never repurpose HOME or other system variables.

1. Fetch origin without changing the working tree. Verify repository URL, branch and commit identities, actual main=B and remote C3=START. Read PR #132 through `gh pr view 132 --repo yduchesne/quervant --json number,url,state,isDraft,mergedAt,baseRefName,headRefName,headRefOid`. Require open, unmerged, base main, correct head branch/SHA. Record observed draft flag and preserve it.
2. Require clean tracked worktree and index. Record all untracked paths. The known disjoint `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` must remain untouched; hash it before/after if present. Apply D03 for other untracked files. Do not stash/reset/delete someone else's work.
3. Verify §0 anchors and original plan/manifest/recorder SHA-256 from immutable Git objects. Record full `rustc +1.98.1 -vV`, `rustc +1.85.0 -vV`, cargo versions, Python version and active target. Do not silently substitute another Rust version.
4. Create one private evidence working directory **outside** the checkout, with `receipts/baseline/`, `receipts/final/`, `diagnostics/`, `audits/` and `ci/`. Copy the original `evidence/c3/record.py` there unchanged and verify its hash. Extract the three exact Appendix scripts into that same external directory and verify their listed hashes. Scripts may be copied into new F1 evidence only during delivery.
5. Run `build_f1_contract.py BASELINE <new-external-baseline-contract.json>`. It reads only immutable original evidence and emits the six baseline commands. Execute those six once with the original recorder, expected commit START. The command contract's path is relative to the external `receipts/` root. Use the contract label and exact argv.
6. Verify the baseline contract and six receipts with `verify_f1_receipts.py`. A baseline PASS means the currently written tests pass; it does not erase the review's missing assertions. No production-red experiment is required or authorized.
7. Complete §3's worksheet. Then implement P1–P4 continuously, applying only the matrix's permitted mechanical repairs. No additional architecture decision remains for the coding agent.

The recorder invocation is:

~~~text
python3 <external-record.py> <absolute-new-receipt.json> <immutable-expected-commit> <contract-label> <exact-command-argv...>
~~~

Pass argv as an array through a subprocess/tool interface. Do not reconstruct a shell command by joining untrusted text. Recorder outputs must be new files; preserve failures/diagnostics separately. It removes both `QUERVANT_PR15I_D3C_STRATEGY` and `QUERVANT_PR15I_D3C_PREFILTER_PROFILE` in the child.

### 8.2 Worktree preparation and immutable F1_TESTED

After the prescribed edits:

1. Format only changed authorized function regions as needed. Running repository fmt is permitted, but revert only your own unintended formatting outside the allowlist; do not normalize historical code.
2. Run Appendix A's freeze checker on `WORKTREE`, writing its output outside the checkout. All three test files must differ; all bytes outside the seven authorized function regions must compare exactly. The original `execute.rs` and all other executable files remain unchanged.
3. Review exact diff and staged name list. Stage only the three test-bearing paths from §2.1, run staged whitespace check, and commit with a message identifying C3-F1 acceptance repair. Do not include generated evidence in this test commit.
4. Set the shell variable `C3F1_TESTED=$(git rev-parse HEAD)` and record `git rev-parse HEAD^{tree}`. Its report role is named F1_TESTED throughout this plan. Require clean tracked status and index tree equal to HEAD tree.
5. Generate a new final command contract using `build_f1_contract.py "$C3F1_TESTED" <new-external-command-contract.json>`. This contract contains **51 receipts: six baseline +45 final**. The builder's BASELINE mode is only for baseline execution; never use its START identity for final verification.
6. Execute all 45 final commands below on that same immutable commit. If a mechanical repair changes a test after a check, create a new F1_TESTED and regenerate/re-execute all 45 final commands. Preserve superseded receipts in a sibling directory; never overwrite or select a green subset.
7. No further source/test/build/CI change is allowed after F1_TESTED. Documentation and evidence may follow under §10.

### 8.3 Six focused cases

The Appendix C builder supplies exact argv; this table provides human-readable mapping. All focused commands use Rust 1.98.1 and `-- --exact --nocapture --test-threads=1`. Each must announce exactly one test, execute its exact registered name, exit0, report one passed/zero failed/zero ignored, and emit the final F1 completion line after all row assertions.

| Original command ID reused for argv | Target / exact registered name | Baseline label | Final label |
| --- | --- | --- | --- |
| fin_s01 | `--lib search::score::tests::c3_s01_certificate_matrix` | base_s01 | f1_fin_s01 |
| fin_u02 | `--lib search::unified::c2_tests::c3_u02_dispatch_and_count_matrix` | base_u02 | f1_fin_u02 |
| fin_u04 | `--lib search::unified::c2_tests::c3_u04_corruption_precedence` | base_u04 | f1_fin_u04 |
| fin_u05 | `--lib search::unified::c2_tests::c3_u05_native_later_segment_boundary` | base_u05 | f1_fin_u05 |
| fin_u09 | `--lib search::unified::c2_tests::c3_u09_logical_budget_edges` | base_u09 | f1_fin_u09 |
| fin_i02 | `--test perf06_c2_physical c3_i02_real_pit_update_merge_and_paging` | base_i02 | f1_fin_i02 |

Emit these exact final lines **only after verifying actual completion counters and the fixed ID lists**. Keep the more detailed per-row observations prescribed earlier. Do not print a completion marker before the assertions it certifies.

~~~text
C3 F1 S01 rows=24 isolated-df-rows=2
C3 F1 U02 matrix-rows=25 certified=5 legacy=20 split-c3=10 ineligible-result-rows=6
C3 F1 U04 rows=9 isolated-C29=true unarmed-synthetic-snapshot=C3
C3 F1 U05 rows=4 recoveries=4 literal-reference-errors=3
C3 F1 U09 rows=12 failed-rows=7 recoveries=7 fixed-projection-failure=13056/13160/100
C3 F1 I02 phases=5 checked-hits=198 old-pages=14 new-pages=13
~~~

Use the U02 six-result ID list `["relevance","two_fields","doc_id_min","tag_min","batch","aggregation"]` in that order. For I02 sum actual checked hits from the five invocations before printing198; the helper can return only keys because each appended key has passed all per-hit assertions, and its returned length equals verified-hit count.

### 8.4 Five exact inventories

Use `cargo +1.98.1 test -p quervant-core` plus each suffix below. Compare the entire sorted name set with the corresponding immutable START receipt, never with a set derived from the new final output. Appendix C performs that extraction and freezes it in the final contract.

| Original ID | Command suffix | Expected names |
| --- | --- | ---: |
| fin_list_c2u | `--lib search::unified::c2_tests::c2_u -- --list --format terse` | 24 |
| fin_list_c2p | `--lib search::execute::c2_physical_tests::c2_p -- --list --format terse` | 5 |
| fin_list_c2_broad | `--lib c2_ -- --list --format terse` | 52 |
| fin_list_c3 | `--lib c3_ -- --list --format terse` | 26 |
| fin_list_integration | `--test perf06_c2_physical -- --list --format terse` | 12 |

Final labels are `f1_` plus the original ID. The broad C3 set contains nine pre-existing accounting tests and seventeen C3 tests; the implementation-plan count17 for that broad filter was an author mistake. Preserve all names, including collisions. No inventory growth is expected from these repairs.

### 8.5 Eighteen regression/suite commands

Use the exact argv frozen in Appendix C. Suffixes below are relative to `cargo +1.98.1 test -p quervant-core` except the explicitly pinned MSRV row.

| Original ID | Command suffix / difference | Required top-level result |
| --- | --- | --- |
| fin_suite_c3_t1 | `--lib c3_ -- --test-threads=1` | 26/0/0 |
| fin_suite_c3_t8 | `--lib c3_ -- --test-threads=8` | 26/0/0 |
| fin_suite_c3_msrv_af | use +1.85.0; `--lib --all-features c3_ -- --test-threads=8` | 26/0/0 |
| fin_suite_c2u_t1 | `--lib search::unified::c2_tests::c2_u -- --test-threads=1` | 24/0/0 |
| fin_suite_c2u_t8 | same filter, threads8 | 24/0/0 |
| fin_suite_c2p_t1 | `--lib search::execute::c2_physical_tests::c2_p -- --test-threads=1` | 5/0/0 |
| fin_suite_c2p_t8 | same filter, threads8 | 5/0/0 |
| fin_suite_integration | `--test perf06_c2_physical -- --test-threads=1` | 12/0/0 |
| fin_suite_score | `--lib search::score::tests:: -- --test-threads=1` | 19/0/0 |
| fin_suite_reader | `--lib segment::reader::stored_blocks_reader_tests:: -- --test-threads=8` | 9/0/0 |
| fin_suite_b1_lib | `--lib b1_` | 65/0/0 |
| fin_suite_b1_int | `--test perf06_b1_ordinals` | parent9/0/2 ignored; child output separate |
| fin_suite_b2_lib | `--lib b2_` | 31/0/0 |
| fin_suite_b2_int | `--test perf06_b2_ordinals` | 8/0/0 |
| fin_suite_b3_lib | `--lib b3_` | 32/0/0 |
| fin_suite_b3_int | `--test perf06_b3_keys` | 8/0/0 |
| fin_suite_pr15h_a | `--test pr15h_a_candidate_materialization` | 6/0/0 |
| fin_suite_pr15h_a2 | `--test pr15h_a2_dispatch` | 8/0/0 |

These execute all unchanged C3/C2 bodies and required sibling regressions. Separate repeated focused runs of unchanged tests are not required: their original focused evidence, exact body freeze and these executed suites remain traceable. Do not replace required suite execution with a statement that a broader test ought to cover it.

### 8.6 Sixteen full local QA commands

All execute after the final test change, from clean F1_TESTED. These are repository-required gates for a test-bearing change, even though production source is frozen.

| Original IDs | Exact command(s) | Acceptance |
| --- | --- | --- |
| qa_fmt_198 / qa_fmt_185 | `cargo +1.98.1 fmt --all -- --check`; same +1.85.0 | both exit0, empty output |
| qa_clippy_198 / qa_clippy_198_af | `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings`; add `--all-features` before `--` | both exit0 |
| qa_clippy_185 / qa_clippy_185_af | same two commands with +1.85.0 | both exit0 |
| qa_test_198 / qa_test_198_af | `cargo +1.98.1 test --workspace --all-targets`; add `--all-features` for second | both exit0, full scope parsed |
| qa_test_185 / qa_test_185_af | same two commands with +1.85.0 | both exit0, full scope parsed |
| qa_cov_198 | `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | exit0, actual Lines >=85% |
| qa_cov_198_af | same with `--all-features` before floor option | exit0, actual Lines >=85% |
| qa_doc_198 / qa_doc_198_af | `cargo +1.98.1 doc --workspace --no-deps`; second uses `--workspace --all-features --no-deps` | both exit0 |
| qa_bench_norun | `cargo +1.98.1 bench --workspace --no-run` | compile only, exit0 |
| qa_bench_scripts | `bash benchmarks/scripts/test-scripts.sh` | exit0, 108 passed/0 failed |

The two fmt, four clippy, four workspace-test, two coverage, two doc, one compile-only bench and one script command total sixteen. Do not accidentally omit a feature regime or count a command twice.

Workspace parsing requirements:

- 146 Cargo target launches, of which136 have parent libtest summaries and10 are the named Criterion test-mode targets frozen in Appendix C.
- Parent default totals2749/0/16 ignored; parent all-features2794/0/100 ignored. No new registered tests are added, so a changed top-level name/count requires investigation/STOP, not automatic acceptance.
- Child-process summaries are recorded separately. Future contracts deliberately omit the optional fixed child-total assertion: interleaved child output is reported as observed, with ambiguity flagged; do not invent a pass or infer a unique-test total.
- Unknown parent-summary scope, a failed target, or an unknown Criterion target is a STOP. Criterion test-mode smoke output is not performance measurement.
- No doctest claim is made for these all-targets commands. Documentation build is recorded separately.

Coverage must retain the real output header and TOTAL. Use Appendix B's parser; report its `lines` object with total/missed/covered/percentage. Regions, functions and branches remain separately labelled. Do not reuse historical percentages for F1, change exclusions, drop production modules, lower85, or accept a single selected-file percentage as workspace coverage.

## 9. Scope verification, receipts and immutable linkage

### 9.1 Exact checker use

Appendix A `freeze_f1.py` has SHA-256 `85012631836e96d62181f5ade033f59e4eaff2a8bf8256634b41ab5f67ca225b`. It permits only the seven named function regions and the documentation allowlist. It is not a broad whitespace-insensitive comparison.

Run it in these regimes, each with a new external output path:

~~~text
python3 <external>/freeze_f1.py WORKTREE <external>/audits/worktree-freeze.json
python3 <external>/freeze_f1.py F1_TESTED <external>/audits/tested-freeze.json
python3 <external>/freeze_f1.py F1_DOCS_FINAL <external>/audits/final-freeze.json --tested F1_TESTED
~~~

Replace symbolic SHAs with their actual immutable values. If a source anchor/terminator is missing or ambiguous, do not change the checker to fit a different scope. Stop under D12. Preserve all checker inputs, script bytes, output and hashes.

Also rerun the unchanged original `evidence/c3/source_audit.py` against B and F1_TESTED with an external output path. Require its protected comparisons still pass; keep its informational callback row labelled INFO, not PASS. The stronger F1 whole-file mask check establishes that no production or unrelated-test region changed after the independently reviewed START.

Verify every receipt's claimed tree against `git rev-parse <expected_commit>^{tree}`: baseline against START, final against F1_TESTED. Appendix B checks internal identity consistency; it does not replace this actual Git-object linkage. Record the two real trees and the per-class comparison.

### 9.2 Command contract and verifier

Appendix C `build_f1_contract.py` has SHA-256 `62af39cca1c0dba47ac0c58ab580cdfe8473cdeeaac05ca93b44abdf9922d2ad`. It never executes commands. It freezes argv from the reviewed original receipts and checks their identity against the original manifest. It produces six baseline entries or all51 final-contract entries, with exact test names/counts/inventory sets and the F1 markers.

Appendix B `verify_f1_receipts.py` has SHA-256 `f83e1ecc8e6c38cb86498e81e524d9a2ca1aab3cfa63fe8a425b507ba816a8e7`. Invoke:

~~~text
python3 <external>/verify_f1_receipts.py <external>/command-contract.json <external>/receipts <external>/verification.json
~~~

The contract, scripts, verification output, diagnostics and CI metadata must be **outside the receipts root being verified**. That root contains exactly the declared baseline/final receipt files. Never include the verifier's own receipt in the set it is currently consuming; that creates a self-reference cycle. Audits and verifier invocation receipts belong in a sibling directory.

The verifier checks exact argv, labels, source commits, before/after equality, clean tracked status, index-tree equality, removed environment names, exit code, strict Base64, raw size/SHA-256, exact test execution, inventory names, separate target scopes and actual line metrics. It also emits complete receipt hashes. No test is executed by this verifier, and its PASS must not be called a Rust-test rerun.

The author validated the helper against the preserved75 receipts and rejected six adversarial controls: unknown coverage header, region-as-line expectation, duplicate TOTAL, wrong17-name inventory, changed source identity, and undeclared acceptance file. The scope checker was checked against every allowed function marker and rejects an outside-region delta. Preserve these supplied scripts; parser ambiguity requires a plan amendment rather than an improvised regex.

### 9.3 Lossless artifacts and whitespace

Reuse the original recorder unchanged. JSON carries raw command bytes as Base64, including failure diagnostics. Do not paste raw whitespace diagnostics, patches, or recursive self-quoting logs into tracked Markdown.

Record exact output/exit for:

~~~text
git diff --check B...F1_DOCS_FINAL
git diff --check START..F1_DOCS_FINAL
git diff --check F1_TESTED..F1_DOCS_FINAL
git diff --check
git diff --cached --check
~~~

All must exit0 with empty output. A clean worktree does not prove a committed range is clean. No historical C2 exception applies to the new B range. Preserve failing outputs and stop; do not label a failed raw command PASS.

Produce path lists for B..F1_TESTED, START..F1_TESTED and F1_TESTED..F1_DOCS_FINAL. The F1 test delta has exactly three source/test files, all within their permitted functions. The last range contains documentation/evidence only. Record the exact diff SHA-256; encode the patch if it is included.

The source freeze outputs and local QA are not evidence that the remote head equals a local name. Remote linkage is checked separately in §10.

## 10. Documentation, hosted CI and delivery without a commit cycle

### 10.1 Required prose corrections and new report

Create the new F1 report with these sections: identities/hashes; review findings; worksheet; invariant-to-test mapping; exact changed-function audit; six repaired case outcomes and actual row descriptors; retained inventories/regressions; per-command QA and correctly scoped coverage/counts; real local topology; hosted CI status; applied decisions/failures/residual limits; delivery links/identities.

Append dated errata to the original C3 report, roadmap and series register. Provide these historical corrections explicitly:

1. Historical line coverage was93.50% and93.09%, with §1.3's total/missed/covered counts. The earlier93.85%/93.54% values were region coverage.
2. U02's earlier25 loops exercised a different matrix; the earlier split log's final-calls12 belonged to Legacy, while the certified run's assertion correctly observed10. Do not imply the corrected empty/singleton matrix had already run.
3. C29 previously also mutated P29; the isolated column29 case was not then established under that name.
4. I02 previously validated later-page keys/counts, but score/field oracles covered first pages only.
5. S01's two df rows had an additional missing-IDF condition; the old PASS did not independently prove those guards.
6. The original U09 expectation was overbroad; document this plan's specific projection-after-finalization amendment and exact {13056,13160}/100 result. Do not describe the generic 0-or-K allowance as previously authorized.
7. U04 has eight byte-only rows plus an injected/key combination; three column rows fail before route dispatch. No assertion that all nine execute C3 candidate handling.
8. The all-visible2759/2804 sums include ten child-process passes; parent totals2749/2794, Criterion targets and ignored tests are separate. No doctests occurred in those commands.
9. Original run45925006538 later completed successfully; distinguish its head and merge checkout and actual RustFS bodies from the truthful earlier pending observation.
10. Broad C3 inventory26 contains17 new and9 old names; no test registration change is needed.

Keep old text as history and explicitly name the superseded statements. Record new F1 values separately after measurement. Do not overwrite the original plan, raw logs, manifest, recorder or superseded attempts.

Append a short acceptance-status note to the physical execution contract. It records preserved production semantics, repaired acceptance, the exact projection checkpoint clarification and open G10/C4; it does not change C1/C3 normative ownership, scoring, accounting or projection order.

### 10.2 One documentation finalization, then external terminal evidence

Avoid a self-referential sequence in which committing CI evidence creates a new head needing another CI run.

1. After all local gates pass, copy this plan verbatim, the new report, appendix scripts,51 selected receipts, contract, verification JSON, case/inventory summaries and immutable-source audits into the new F1 paths. Include captured historical START CI evidence. Put old attempts only in a clearly named diagnostic/superseded sibling directory; they are not selected PASS evidence.
2. The committed F1 report identifies F1_TESTED and all local results. At this point it records F1 hosted CI as not yet observed, and explains that final-head CI/remote/whitespace receipts will be in the terminal package and live PR description. This is a deliberate layered evidence boundary, not a fabricated PASS.
3. Run working/staged whitespace and exact scope checks. Commit the allowlisted documentation/evidence once local artifacts are internally consistent. Capture the resulting SHA as F1_DOCS_FINAL.
4. Generate final range/region/identity audits **outside the checkout** against that exact immutable SHA. Do not commit a file claiming to contain its own enclosing commit SHA.
5. Push the existing branch normally. Require local HEAD, `git ls-remote --heads origin dev/perf06-c3`, and PR headRefOid all equal F1_DOCS_FINAL. Set F1_REMOTE_H to that value. Preserve observed readiness.
6. Observe the ordinary pull_request CI for that head and complete the external terminal package below. Update and read back the existing PR description with the actual final evidence. Do not create another evidence commit merely to record the same head's terminal CI.
7. If any actual documentation error requires a new commit before handoff, it becomes a new DOCS_FINAL; repeat final committed-range/remote/hosted verification for that new head. Local Rust QA may be reused only if the immutable source/test diff from F1_TESTED remains empty. Do not repeat Rust QA for a purely external receipt or PR-body wording correction.

### 10.3 Hosted acceptance for F1_REMOTE_H

Keep `.github/workflows/ci.yml` byte-identical. It uses pull_request for PR updates and push only on main. Do not dispatch, add a push trigger, rerun failed jobs, cancel required validations, or change workflow concurrency/filters.

Discover the actual Rust CI run for PR132, event pull_request and exact F1_REMOTE_H. Record run ID, URL, attempt, event, head SHA, base SHA, status/conclusion, job IDs and actual checkout SHA. Distinguish head metadata from merge checkout and verify its lineage. Never substitute an earlier identical-source run without the explicit matrix rule.

Observe up to60 times at30-second intervals, stopping immediately on a terminal conclusion. Each wait is at most30seconds, with a progress update at least once per minute. This is observation of one existing run, not retrying tests. No duplicate run is dispatched.

Required jobs: `python-benchmark-framework`, `benchmark-adapter-contract`, `rustfs`, `rust`, `msrv`; all must finish success. Retrieve job steps and raw logs after completion. A success job badge alone does not prove ignored real-service bodies executed.

For RustFS, verify the unchanged workflow's healthy pinned service and actual executed command bodies:

- objectstore `pr13_s3_rustfs` and `pr13_proxy_rustfs`;
- core `pr13_remote`, `pr13_oracle`, `pr13_oracle_geo`, `pr15g_a_rustfs` through `pr15g_d_rustfs`, and `perf06_b1_rustfs`;
- `m1_batches`, `pr15i_a_rustfs`, `pr15i_b_rustfs`, `m2_patches`;
- `m3_delete_by_query` three runs, `m5_mutation_qualification` three runs;
- `pr13_remote_proxy`, `pr13_crash_rustfs k0`, and `pr13_crash_rustfs k05` ten runs.

These are the current workflow's existing `--ignored --test-threads=1` real-service invocations. Require positive named tests/results in the appropriate step, no missing-service early-return/skip, and all required repetitions. Report summary count, passed invocation count and unique-name scope separately. Do not copy historical32/65 numbers if new output differs; reconcile actual target bodies and repetitions without inventing a count.

If the run is still pending after the window or logs are temporarily unavailable, complete all independent local/evidence work and deliver the accurately pending/blocked handoff. Do not mark G8 PASS, G9 fully closed or G10 accepted. A terminal failure is classified under §11 and the decision matrix.

### 10.4 Exact terminal package

Create it outside the checkout only after the final remote observation. Use a filename containing the actual head:

`PERF06C3F1_TERMINAL_<full-head>.md` and `.zip`.

Include:

- terminal Markdown with identities, all G0–G10 statuses, seven finding dispositions, actual row counts, local command/metric summary, current CI/real RustFS evidence, applied rules and residual limits;
- final source-freeze JSON and actual Git tree linkage for baseline/final receipts;
- final range/worktree/staged whitespace outputs, with exact argv/exit/bytes encoded;
- current PR/remote/workflow/job metadata and required job-log bytes (Base64 or raw archive members with independent hashes);
- selected-receipt verification JSON and hashes/paths linking to committed F1 evidence;
- a member manifest listing SHA-256 for every payload member except the member manifest itself.

Write all payload members first, then the member manifest, then the ZIP. Record Markdown and ZIP hashes **outside the ZIP in the final handoff**; do not put a ZIP's own hash inside itself or a file's own hash inside that file. Test the archive, verify every listed member digest, and ensure the named files exist and are readable.

Attach actual files using the environment's supported delivery mechanism. Do not say an artifact is attached merely because a /tmp path was printed. If attachment is unavailable, state the exact accessible paths and delivery limitation; preserve the artifacts and mark the delivery portion of G9 accordingly.

### 10.5 Ready-to-use PR-description structure

Replace the current description with this structure after the actual values are known; substitute verified observations only. Preserve the original C3 purpose and its no-performance limitation.

~~~text
PERF-06-C3: certified deferred BM25, with F1 acceptance repair

C3 retains validated posting/ledger/key/cursor behavior and scores only the
returned K hits when the immutable statistics certificate applies.

F1 preserves every production byte from START. It repairs independent certificate
guard inputs, the exact dispatch/fault matrices, fixed resource oracles and
every-page PIT score/field assertions. It also corrects historical coverage and
count labels. No new test names, API, storage, dependency or CI change.

Identities:
  B / START / F1_TESTED / tested tree / F1_DOCS_FINAL / remote head
Artifacts:
  original plan hash; F1 plan/report; c3-f1 evidence; terminal handoff
Acceptance:
  exact repaired rows; unchanged inventories; local QA; actual Lines coverage;
  current-head CI run/jobs and verified real RustFS bodies
Status:
  G0–G9 [actual statuses]; G10 OPEN; observed draft state preserved
Limits:
  synthetic/pre-route classifications, layout-bound resource oracle,
  conservative certificate; C4 owns performance and layout/codegen qualification
~~~

Do not include sandbox paths as GitHub links. Link repository artifacts and CI using their real provider URLs; refer to the terminal package supplied with the handoff. Read the PR body back and compare to the exact intended bytes.

## 11. Failure classification and residual-risk decisions

Every required-gate failure must be preserved and classified as introduced regression, feature/test implementation defect, deterministic pre-existing failure, nondeterministic failure, or environment/harness failure.

- A new assertion failing is not permission to change its fixture, expected payload, row count, statistic or oracle. Stop affected work and record the actual result.
- Compilation/format/lint failures caused solely by mechanical implementation details may be repaired under D08 within the same seven function regions. They require a new tested identity and fresh final checks.
- To label a failure pre-existing, perform at most one equivalent reproduction on immutable START in an isolated clean worktree, keeping all original failure evidence. Do not modify the active checkout, filters, concurrency or environment to obtain green.
- A passing repeat does not erase a failing required run. No retry-to-green or nondeterminism waiver is authorized.
- An unavailable tool/service/log blocks only its dependent gate. Setup using ordinary installed tooling and already-authorized repository infrastructure is permitted; do not weaken network/storage policy or introduce new infrastructure.
- A new production defect, proof-bound contradiction or unexpected normal-build diff is a scoped HARD STOP for a new author decision.

The remaining performance/layout/codegen risks belong to C4. The current fixed resource tuple depends on verified representation geometry; unexpected layout needs an amendment. Evidence helpers are bounded review artifacts, not new production frameworks. No failure classification can silently waive acceptance or close G10.

## 12. Preauthorized decisions and exception-handling matrix

**Owners:** E=executor may apply the exact AUTO-RESOLVE rule; A=plan author/maintainer must decide amendments; M=maintainer owns PR acceptance. The Evidence column is mandatory for every applied row. If several apply, choose the most restrictive. Every unlisted condition invokes D30.

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Evidence / dependent gate / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | repo, B, START, PR branch/head and anchors equal §0 | AUTO-RESOLVE | Record admission and continue all stages | ask routine permission; silently change pins | refs/blob/hash receipts; G0; E |
| D02 | fetched main or PR head differs from pin; PR closed/merged | HARD STOP | Stop edits/push; retain read-only diagnosis | rebase/reset/cherry-pick/adopt an unseen head | exact old/new refs and PR state; G0; A/M |
| D03 | disjoint untracked evidence/document outside build inputs and allowlist | AUTO-RESOLVE | Hash/preserve it; continue without staging | delete/stash/rename/claim ownership | before/after path+hash; G0/G9; E |
| D04 | tracked dirty work, untracked source/build shadow, or conflicting allowed path | HARD STOP | Preserve state and identify affected path | clean/reset/stash or compile through a shadow input | status/path/hash; G0; A |
| D05 | PR readiness differs from earlier report but PR/head otherwise match | AUTO-RESOLVE | Record observed true/false and preserve | toggle readiness | PR metadata; G0/G9; E |
| D06 | required known tool missing, ordinary installation available | AUTO-RESOLVE | Install prescribed tool/version without source/policy changes | substitute version or alter workspace/toolchain files | exact setup/version outputs; G0/G7; E |
| D07 | essential tool, credential or service cannot be obtained | DEFER AND CONTINUE | Mark dependent gate BLOCKED; finish independent admitted work | invent pass or weaken topology | failed setup/access evidence and task map; dependent gate; A |
| D08 | compile/fmt/clippy issue limited to seven permitted function regions | AUTO-RESOLVE | Fix borrow/type/qualification/format mechanics; retain every input/oracle/assertion; new F1_TESTED and full final rerun | alter production, remove assertion, change expected values, add any new lint suppression | exact diff and fresh receipts; G2/G7; E |
| D09 | S01 old missing-IDF masking or U02 wrong delta loop matches reviewed source | AUTO-RESOLVE | Apply §§4–5 exactly | recompute invalid-df IDF, deduplicate rows, keep old M set | literals/completed tuples; G3; E |
| D10 | U04 C29 has extra posting mutation and native guards match | AUTO-RESOLVE | Use fixed descriptor table and existing mutators | change offsets/codecs/fixture or omit a row | descriptor/probe/row receipts; G4; E |
| D11 | FieldValues size !=32, projected charge !=140, unexpected physical layout | HARD STOP | Record target/version/size/charge and stop resource-dependent acceptance | recompute caps/choose alternate error/move finalization | exact measured guard output; G4; A |
| D12 | function anchor ambiguous or any protected byte/path changed | HARD STOP | Preserve diff; remove only your own accidental out-of-scope edit if mechanically identifiable, then rerun exact audit; otherwise await amendment | widen checker mask, normalize all whitespace, edit protected source | checker failure+diff; G2; A |
| D13 | U09 exact102/K100 returns prescribed {13056,13160} after100 scores | AUTO-RESOLVE | Apply the author-approved exact projection case and seven recoveries | change production order or permit arbitrary0-or-K | fixed table, geometry, all-route errors; G4; E |
| D14 | any U05/U09 route returns a different error/outcome/counter | HARD STOP | Capture normal and reference results, exact row and source | retune fixture/limit/expected value; fall back to parity-only | failing receipt/row; G4; A |
| D15 | broad c3_ selects26=9 old+17 C3 and exact name set matches | AUTO-RESOLVE | Record actual scope and continue | rename/remove/ignore tests to produce17 | sorted names vs START; G6; E |
| D16 | inventory changed, zero selected test, wrong exact name or skipped required row | HARD STOP | Correct only an invocation transcription that differs from frozen argv; otherwise stop | accept count-only/compile-only proof or change inventory oracle | contract/actual argv/names; G3–G6; A |
| D17 | wrapper query fingerprint differs on same snapshot | AUTO-RESOLVE | Existing full helper compares all fields except fingerprint | relax key/score/generation/sort/binding or compare only cursor presence | complete helper assertions; G5; E |
| D18 | old/new/compacted snapshot identities legitimately differ | AUTO-RESOLVE | Use exact input oracle per phase; preserve within-snapshot identity checks | require cross-snapshot cursor equality or weaken stale-cursor error | phase stats/hits/cursors; G5; E |
| D19 | hosted CI running or logs unavailable within60×30s window | DEFER AND CONTINUE | Observe boundedly; finish independent evidence; report current PENDING/BLOCKED | dispatch duplicate, claim real bodies without logs, close G8 | timed run/job observations; G8; A |
| D20 | multiple ambiguous runs/head lineage, terminal failure or cancelled required job | HARD STOP | Preserve all run metadata; classify; continue only independent local report work | pick only a green run, rerun automatically or alter workflow | run/attempt/head/checkout logs; G8; A |
| D21 | all five current-head jobs pass and actual RustFS invocations/repetitions verified | AUTO-RESOLVE | Record terminal G8 PASS and proceed to delivery | call an earlier head current; infer execution from badge alone | metadata plus raw job logs; G8; E |
| D22 | child-process output interleaves but parent results/targets are unambiguous and pass | AUTO-RESOLVE | Use supplied parser, report observed child totals/ambiguity separately | count children as unique parent tests or invent omitted passes | parsed parent/child/bench scopes; G7; E |
| D23 | unknown parent scope, coverage header, duplicateTOTAL or parser error | HARD STOP | Preserve raw bytes and parser error; request exact amendment | hand-pick another column, change regex or type check to green | raw/decoded hashes and error; G7/G9; A |
| D24 | actual Lines >=85 and all command checks pass | AUTO-RESOLVE | Report measured line totals/percent; retain other metrics separately | reuse old percent, lower floor/exclude code | coverage header+TOTAL+verifier JSON; G7; E |
| D25 | substantive assertion/runtime/QA failure outside D08's verified mechanical case and D16's exact invocation-transcription case | HARD STOP | Classify under §11; at most one exact baseline reproduction if needed | retry-to-green, loosen assertion, filter/concurrency change | all failing and baseline receipts; affected gate; A |
| D26 | docs-only correction after F1_TESTED, exact source/test diff empty | AUTO-RESOLVE | Keep local QA; make new docs head if needed; repeat final range/remote/CI linkage | claim old head's CI as new head's run | immutable diff/source hashes; G2/G8/G9; E |
| D27 | terminal metadata needs own head/ZIP hash | AUTO-RESOLVE | Use external terminal package and manifest ordering in §10.4 | self-referential commits or self-hashing archive members | actual files/member hashes; G9; E |
| D28 | any new-range whitespace diagnostic | HARD STOP | Preserve raw output; fix only own authorized prose whitespace and repeat | inherit C2 exception or edit frozen historical artifacts | range/exit/bytes; G7/G9; A |
| D29 | push succeeded; local,remote,PR head equal; PR body read-back matches | AUTO-RESOLVE | Deliver actual files and complete handoff with G10 OPEN | merge, approve, post comments or start C4 | remote/PR/body/file hashes; G9; E/M |
| D30 | condition absent from this matrix, competing instructions, or production fix appears necessary | HARD STOP | Stop affected work; state exact observation, invariant, affected tasks and smallest requested amendment; finish only listed independent evidence | improvise, generalize an approval, invent a waiver/design | source/receipt and decision request; affected gate; A |

For D12, restoring an accidental edit is allowed only when it restores the exact START bytes outside the approved regions and touches no user change. That is recovery of your own scope violation, not permission to repair production. Record it even when resolved.

No rule changes a required expected error, test data row, source scope, output parser, proof bound or acceptance gate except the specific U09 amendment and broad-inventory clarification written by this plan.

## 13. Acceptance gates and final report format

### 13.1 Gate ledger

| Gate | PASS condition / owner |
| --- | --- |
| G0 Source admission | exact repository/refs/PR/anchors, toolchains, clean tracked state, preserved foreign files |
| G1 Correctness preparation | eight worksheet answers, fixed tuple/descriptor/stat tables and rule ledger completed before edits |
| G2 Scope and implementation | only six existing test functions plus I02 helper changed; exact protected-byte checks pass; execute.rs and all normal-build behavior unchanged |
| G3 Score/dispatch acceptance | isolated S01 rows;24 S01 IDs; exact25 U02 tuples;5 C3/20 Legacy;split10; six complete ineligible-result rows; unchanged scoring proofs execute |
| G4 Adversarial/resource acceptance | nine exact U04 descriptors and unarmed recovery; four U05 caps/recoveries; twelve U09 fixed results/seven recoveries; all literal reference errors; existing sibling/cancellation/duplicate tests pass |
| G5 Public-boundary acceptance | real FsDirectory I02 five phases/198 per-hit oracles with correct14/13 page counts, exact stats and stale-cursor error; old/new full wrapper comparisons; I01/I03 retained and executed |
| G6 Inventory/regression | exact24/5/52/26/12 name sets; all eighteen named suites execute with required thread/toolchain settings |
| G7 Local QA | all sixteen commands pass at immutable F1_TESTED; actual Lines>=85 twice; counts correctly scoped; all required committed/worktree/staged whitespace checks pass |
| G8 Hosted regression | ordinary run for exact F1_REMOTE_H, all five jobs success, checkout lineage and actual real RustFS bodies/repetitions verified |
| G9 Evidence/delivery | verbatim plan/hash,51 selected verified receipts plus audits, append-only corrections, docs-only post-test range, current remote/body read-back and real terminal files |
| G10 Independent acceptance | OPEN until maintainer/independent reviewer accepts; executor cannot mark it PASS |

Implementation completion and correctness completion are separate. All repaired assertions existing/compiling is not G3–G5 PASS; they must run. Old green receipts do not establish repaired rows. A live CI badge is not local QA, and local QA is not real RustFS execution.

Disposition is exactly one of:

- `PERF06_C3_F1_ACCEPTANCE_COMPLETE_READY_FOR_INDEPENDENT_REVIEW`: G0–G9 all PASS; G10 OPEN.
- `PERF06_C3_F1_LOCAL_ACCEPTANCE_PASS_CI_PENDING`: local gates PASS, G8 pending under D19, terminal handoff accurately qualified.
- `PERF06_C3_F1_BLOCKED_EXTERNAL_DEPENDENCY`: named essential external dependency blocks its gate; independently completed work recorded.
- `PERF06_C3_F1_STOPPED_PLAN_AMENDMENT_REQUIRED`: applicable HARD STOP or unlisted condition; exact reason/evidence and smallest amendment stated.

Do not call the original PR fully complete or mark a roadmap DONE merely because local acceptance is green. C4 remains unstarted and G10 remains open.

### 13.2 Final handoff template

~~~text
REPO / BRANCH / ACTUAL PR / URL / STATE / DRAFT / MERGED

B / START / ORIGINAL_RED / ORIGINAL_TESTED
F1_TESTED / F1_TESTED_TREE / F1_DOCS_FINAL / F1_REMOTE_H
Actual source/test equality F1_TESTED..F1_REMOTE_H
Actual scope/function audit START..F1_TESTED

ORIGINAL_PLAN_HASH / F1_PLAN_HASH / RECORDER_HASH
FREEZE_CHECKER_HASH / RECEIPT_VERIFIER_HASH / CONTRACT_BUILDER_HASH
COMMAND_CONTRACT_HASH / VERIFICATION_HASH / SOURCE_DIFF_HASH
BASELINE_RECEIPTS=6 / FINAL_RECEIPTS=45 / SELECTED_TOTAL=51

DISPOSITION
G0..G10 with PASS / PARTIAL / PENDING / BLOCKED / FAIL and evidence

F1-01..F1-07 outcome, source change and actual acceptance evidence
S01 24 IDs, two isolated df guards
U02 exact25 tuples, five C3/twenty Legacy, split10, six result rows
U04 exactnine descriptors, C29-only, same-snapshot unarmed C3
U05 four caps/four recoveries/three literal-reference errors
U09 exacttwelve rows/seven failures/seven recoveries/projection tuple
I02 five phases, 198 checked hits, explicit per-phase pages/df/n/length

Inventory name sets: 24 / 5 / 52 / 26 / 12, no registrations changed
Per-command PASS/FAIL/BLOCKED/NOT-APPLICABLE with immutable source
Workspace parent / child / Criterion / ignored / doctest scopes
Measured coverage: Lines totals/missed/covered/percent; Regions separate

CI run/attempt/event/head/base/merge checkout/URL
All five job statuses; actual real RustFS invocation/repetition evidence
Every failure, diagnostic attempt, applied D-rule and unresolved gate
No unauthorized exception; no performance/benchmark acquisition/C4/merge

Protected source and historical evidence equality
PR readiness preserved, PR-body exact read-back, remote equality
Actual terminal Markdown and ZIP attachment links, sizes and hashes
G10 OPEN, next action owned by independent reviewer/maintainer
~~~

The report must stand on its own. State what was actually run, what remains historical, and what is blocked. If the terminal files are not attached, say so explicitly instead of asserting delivery.

### 13.3 Reviewer checklist

- [ ] Source/PR identities match the plan; fresh main and implementation source were inspected.
- [ ] Normal-build source and all unrelated test bytes are unchanged.
- [ ] Two S01 df inputs retain the valid base IDF; missing-IDF remains separate.
- [ ] Exact U02 rows include all absent/singleton boundaries and intentional duplicate input.
- [ ] Split counters were captured before references; existing sort/batch/aggregation responses are asserted.
- [ ] C29 has no posting mutation; all U04 descriptors, error classes and recovery scopes are accurate.
- [ ] U09 uses literal results rather than outcome-dependent expectations; projection geometry is guarded.
- [ ] Every failure's eager/Legacy payload is tied to the same independent literal.
- [ ] I02 checks every hit from every required view against input indices, fields and scalar bits.
- [ ] Retained tests and real local/remote boundaries were executed in their required topology.
- [ ] Coverage comes from Lines; parent/child/bench test counts have explicit scopes.
- [ ] Plan/old evidence are frozen, errata append-only, selected receipts verified, final remote and CI linked.
- [ ] G10 and C4 remain outside executor authority.

## 14. Source references and author-verification limits

All review claims refer to immutable START unless a live status URL is specified:

- [PR132](https://github.com/yduchesne/quervant/pull/132) and [completed original run45925006538](https://github.com/yduchesne/quervant/actions/runs/45925006538).
- [Plan authoring guide](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md), particularly §§3A–3F,27,37–40.
- [Original C3 plan](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/docs/pr-artifacts/perf-06-c/PERF06C3_DETAILED_IMPLEMENTATION_PLAN.md) and [execution report](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/docs/pr-artifacts/perf-06-c/PERF06C3_EXECUTION_REPORT.md).
- [score.rs](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/crates/quervant-core/src/search/score.rs): certificate373ff; S01 df rows1553–1561.
- [unified.rs](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/crates/quervant-core/src/search/unified.rs): U02 matrix15264ff, split diagnostic15377ff, U04 column constructor16277ff, U05 error references16484ff, U09 exact-result allowance17158ff, projection call3760ff.
- [projection.rs](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/crates/quervant-core/src/search/projection.rs): ledger177ff, projected byte formulas218ff.
- [perf06_c2_physical.rs](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/crates/quervant-core/tests/perf06_c2_physical.rs): collect_pages1413ff and I02 following it.
- [Original evidence](https://github.com/yduchesne/quervant/tree/ee77917d303b060b0d38ab88e5d9ae73625f6676/docs/pr-artifacts/perf-06-c/evidence/c3), especially manifest, fin_u09, qa_cov_198/qa_cov_198_af and the four workspace-test receipts.
- [Current-main CI](https://github.com/yduchesne/quervant/blob/6bc977e6a26c183609b7ca53eca51d3ab09ce337/.github/workflows/ci.yml), [workspace manifest](https://github.com/yduchesne/quervant/blob/6bc977e6a26c183609b7ca53eca51d3ab09ce337/Cargo.toml), [architecture](https://github.com/yduchesne/quervant/blob/6bc977e6a26c183609b7ca53eca51d3ab09ce337/docs/ARCHITECTURE.md), and [testing policy](https://github.com/yduchesne/quervant/blob/ee77917d303b060b0d38ab88e5d9ae73625f6676/docs/TESTING.md).

Line numbers are navigation aids, not edit authorization; exact function anchors and immutable blobs control. The workspace has quervant-core, quervant-objectstore and quervant-distributed, edition2024/MSRV1.85. Existing CI pins1.98.1 and1.85.0. This fix-up changes none of those boundaries.

The plan author performed source/receipt/CI review and helper validation, not a fresh local Rust build or benchmark. Passing historical evidence remains tied to its original tested commit. New acceptance and new measured coverage are future executor work.

## Appendix A — exact source-freeze helper

Save the following block as `freeze_f1.py` with one final newline. SHA-256: `85012631836e96d62181f5ade033f59e4eaff2a8bf8256634b41ab5f67ca225b`. Do not modify it to admit an unexpected diff.

~~~python
#!/usr/bin/env python3
"""Verify C3-F1's function-only delta and immutable post-test source."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

START = "ee77917d303b060b0d38ab88e5d9ae73625f6676"
FUNCTIONS = {
    "crates/quervant-core/src/search/score.rs": [
        ("c3_s01_certificate_matrix", 4)],
    "crates/quervant-core/src/search/unified.rs": [
        ("c3_u02_dispatch_and_count_matrix", 4),
        ("c3_u04_corruption_precedence", 4),
        ("c3_u05_native_later_segment_boundary", 4),
        ("c3_u09_logical_budget_edges", 4)],
    "crates/quervant-core/tests/perf06_c2_physical.rs": [
        ("collect_pages", 0), ("c3_i02_real_pit_update_merge_and_paging", 0)],
}
APPEND = {
    "docs/pr-artifacts/perf-06-c/PERF06C3_EXECUTION_REPORT.md",
    "docs/PERF_OPTIMIZATION_ROADMAP.md",
    "docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md",
    "docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md",
}
NEW_DOCS = {
    "docs/pr-artifacts/perf-06-c/PERF06C3F1_DETAILED_FIXUP_PLAN.md",
    "docs/pr-artifacts/perf-06-c/PERF06C3F1_EXECUTION_REPORT.md",
}
EVIDENCE = "docs/pr-artifacts/perf-06-c/evidence/c3-f1/"


def require(ok, detail):
    if not ok:
        raise ValueError(detail)


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.STDOUT)


def blob(ref, path):
    if ref == "WORKTREE":
        return Path(path).read_bytes()
    return git("show", f"{ref}:{path}")


def changed(base, current):
    args = ["diff", "--name-only", "-z", base]
    if current != "WORKTREE":
        args.append(current)
    args.append("--")
    return [p.decode("utf-8") for p in git(*args).split(b"\0") if p]


def mask(data, declarations):
    lines = data.splitlines(keepends=True)
    spans = []
    for name, indent in declarations:
        pattern = re.compile(rb"^" + b" " * indent + rb"fn " +
                             re.escape(name.encode()) + rb"[(<]")
        positions = [i for i, line in enumerate(lines) if pattern.match(line)]
        require(len(positions) == 1, f"ambiguous/missing function {name}")
        start = positions[0]
        end = next((i + 1 for i in range(start + 1, len(lines))
                    if lines[i].rstrip(b"\r\n") == b" " * indent + b"}"), None)
        require(end is not None, f"missing function terminator {name}")
        spans.append((start, end, name))
    spans.sort()
    require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])),
            "overlapping function regions")
    for start, end, name in reversed(spans):
        lines[start:end] = [f"<C3-F1:{name}>\n".encode()]
    return b"".join(lines)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect(current, tested):
    paths = changed(START, current)
    require(set(FUNCTIONS) <= set(paths), "all three prescribed test files must change")
    source_rows = []
    for path, declarations in FUNCTIONS.items():
        before, after = blob(START, path), blob(current, path)
        a, b = mask(before, declarations), mask(after, declarations)
        require(a == b, f"protected bytes changed in {path}")
        source_rows.append(dict(path=path, before_sha256=digest(before),
                                after_sha256=digest(after), protected_sha256=digest(a),
                                authorized_functions=[n for n, _ in declarations]))
    for path in paths:
        if path in FUNCTIONS:
            continue
        if path in APPEND:
            require(blob(current, path).startswith(blob(START, path)),
                    f"historical document was rewritten: {path}")
            continue
        if path in NEW_DOCS or path.startswith(EVIDENCE):
            require(git("ls-tree", START, "--", path) == b"",
                    f"new-artifact path existed at START: {path}")
            continue
        raise ValueError(f"path outside F1 allowlist: {path}")
    post_test_paths = None
    if tested:
        require(re.fullmatch(r"[0-9a-f]{40}", tested), "tested must be immutable SHA")
        post_test_paths = changed(tested, current)
        require(all(p.startswith("docs/") for p in post_test_paths),
                "non-document change after F1_TESTED")
        for path in FUNCTIONS:
            require(blob(tested, path) == blob(current, path),
                    f"test source changed after F1_TESTED: {path}")
    return dict(status="PASS", start=START, current=current, tested=tested,
                changed_paths=paths, source_regions=source_rows,
                post_test_paths=post_test_paths,
                normal_build_source_equal=True,
                unapproved_test_bytes_equal=True,
                tested_to_final_docs_only=bool(tested))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("current")
    parser.add_argument("output")
    parser.add_argument("--tested")
    args = parser.parse_args()
    require(args.current == "WORKTREE" or
            re.fullmatch(r"[0-9a-f]{40}", args.current), "current must be SHA or WORKTREE")
    output = Path(args.output).resolve()
    repo = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    require(repo not in output.parents, "write audit output outside checkout")
    require(not output.exists(), "audit output must be new")
    try:
        result = inspect(args.current, args.tested)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        result = dict(status="FAIL", detail=str(error))
    result["checker_sha256"] = digest(Path(__file__).read_bytes())
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
~~~

## Appendix B — exact receipt verifier

Save this block as `verify_f1_receipts.py` with one final newline. SHA-256: `f83e1ecc8e6c38cb86498e81e524d9a2ca1aab3cfa63fe8a425b507ba816a8e7`. It validates receipts; it never executes recorded commands. Its explicit schema is generated by Appendix C.

~~~python
#!/usr/bin/env python3
"""Validate frozen receipt contracts; never execute recorded commands.

Usage: python3 verify_f1_receipts.py SPEC.json RECEIPTS_ROOT OUTPUT.json
SPEC and new OUTPUT must be outside RECEIPTS_ROOT. Diagnostics belong elsewhere.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from decimal import Decimal
CURRENT = "contract"

def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def keys(value, allowed, required):
    require(isinstance(value, dict), "expected JSON object")
    require(set(value) <= set(allowed) and set(required) <= set(value), "unknown/missing keys")


def summaries(text):
    rows = re.findall(r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; \d+ measured; (\d+) filtered out;.*$", text, re.M)
    return [dict(status=s, passed=int(p), failed=int(f), ignored=int(i), filtered=int(z)) for s, p, f, i, z in rows]


def summary_equal(row, expected):
    keys(expected, ("passed", "failed", "ignored"), ("passed", "failed", "ignored"))
    require(all(type(v) is int and v >= 0 for v in expected.values()), "invalid expected totals")
    require({k: row[k] for k in expected} == expected, "test summary mismatch")
    require(row["status"] == ("FAILED" if expected["failed"] else "ok"), "test status mismatch")


def coverage(text):
    headers = re.findall(r"^Filename\s+.*$", text, re.M)
    totals = re.findall(r"^TOTAL\s+.*$", text, re.M)
    require(len(headers) == len(totals) == 1, "need exactly one coverage header and TOTAL")
    pattern = r"Filename|Missed Regions|Missed Functions|Missed Lines|Missed Branches|Regions|Functions|Executed|Lines|Branches|Cover"
    matches = list(re.finditer(pattern, headers[0]))
    require(not re.sub(pattern, "", headers[0]).strip(), "unknown coverage header")
    labels = [m.group() for m in matches]
    require(labels[0] == "Filename", "unknown coverage leading column")
    groups = [labels[i:i + 3] for i in range(1, len(labels), 3)]
    known = [["Regions", "Missed Regions", "Cover"], ["Functions", "Missed Functions", "Executed"],
             ["Lines", "Missed Lines", "Cover"], ["Branches", "Missed Branches", "Cover"]]
    require(len(groups) == 4 and sorted(groups) == sorted(known), "unsupported coverage columns")
    cells = totals[0].split()
    require(len(cells) == len(labels) and cells[0] == "TOTAL", "coverage column count mismatch")
    result = {}
    for label in ("Regions", "Functions", "Lines", "Branches"):
        index = labels.index(label)
        require(cells[index].isdigit() and cells[index + 1].isdigit(), "invalid coverage counts")
        total, missed = int(cells[index]), int(cells[index + 1])
        require(0 <= missed <= total, "invalid missed count")
        value = cells[index + 2]
        if total == 0:
            require(value == "-", "unexpected zero-total percentage")
        else:
            require(re.fullmatch(r"\d{1,3}\.\d{2}%", value), "unknown percentage format")
            actual = Decimal(100) * (total - missed) / total
            require(abs(Decimal(value[:-1]) - actual) <= Decimal("0.005"), "coverage arithmetic mismatch")
        result[label.lower()] = dict(total=total, missed=missed, covered=total - missed, percent=value)
    require(result["lines"]["total"] > 0, "empty line coverage")
    require(100 * result["lines"]["covered"] >= 85 * result["lines"]["total"], "line coverage below 85%")
    return result


def check_output(text, check, argv):
    kind = check.get("kind")
    fields = {"plain": ["empty"], "exact": ["name", "expected"], "summary": ["expected"],
              "inventory": ["names"], "workspace": ["targets", "expected", "bench_smoke", "expected_children"], "coverage": ["expected_lines"]}
    require(kind in fields, "unknown output check kind")
    keys(check, ["kind", "required_text", "forbidden_text"] + fields[kind], ["kind"])
    for needle in check.get("required_text", []):
        require(isinstance(needle, str) and needle in text, "required output text missing")
    for needle in check.get("forbidden_text", []):
        require(isinstance(needle, str) and needle not in text, "forbidden output text present")
    if kind == "plain":
        require(not check.get("empty", False) or text == "", "expected empty output")
        return {"kind": kind}
    if kind == "coverage":
        result = coverage(text)
        if "expected_lines" in check:
            require(result["lines"] == check["expected_lines"], "historical line coverage mismatch")
        return result
    if kind == "inventory":
        names = re.findall(r"^([^\r\n]+): test$", text, re.M)
        expected = check["names"]
        require(isinstance(expected, list) and all(isinstance(n, str) for n in expected), "invalid inventory contract")
        require(len(names) == len(set(names)) and len(expected) == len(set(expected)), "duplicate inventory name")
        require(sorted(names) == sorted(expected) and len(names) > 0, "inventory name-set mismatch")
        return {"count": len(names), "names": sorted(names)}
    if kind == "workspace":
        launches = list(re.finditer(r"^\s+Running ([^\r\n]+)$", text, re.M))
        require(not re.search(r"^\s*Doc-tests\b", text, re.M), "unexpected doctest scope")
        require(len(launches) == check["targets"], "workspace target count mismatch")
        require(not summaries(text[:launches[0].start()]), "summary outside Cargo target")
        result, children, benches, ambiguous = [], [], {}, False
        for i, launch in enumerate(launches):
            end = launches[i + 1].start() if i + 1 < len(launches) else len(text)
            block = text[launch.end():end]
            rows = summaries(block)
            announced = re.findall(r"^running (\d+) tests?$", block, re.M)
            target = launch.group(1).split(" (")[0]
            if target.startswith("benches/"):
                pairs = len(re.findall(r"^Testing .+$", block, re.M))
                require(not rows and not announced and pairs > 0 and pairs == len(re.findall(r"^Success$", block, re.M)), "unknown benchmark test-mode output")
                require(target not in benches, "duplicate benchmark target")
                benches[target] = pairs
                continue
            require(rows and announced and rows[-1]["filtered"] == 0, "missing/ambiguous parent summary")
            require(sum(rows[-1][k] for k in ("passed", "failed", "ignored")) == int(announced[0]), "parent target count mismatch")
            require(all(r["status"] == "ok" and r["failed"] == 0 for r in rows), "failed workspace test")
            require(all(r["filtered"] > 0 for r in rows[:-1]), "unknown child summary scope")
            ambiguous |= len(rows) != len(announced) or len(rows) != block.count("test result:")
            children.extend(rows[:-1])
            result.append(dict(target=launch.group(1), **rows[-1]))
        total = {k: sum(r[k] for r in result) for k in ("passed", "failed", "ignored")}
        child_total = {k: sum(r[k] for r in children) for k in ("passed", "failed", "ignored")}
        summary_equal(dict(status="ok", **total), check["expected"])
        require(benches == check["bench_smoke"], "benchmark test-mode target/count mismatch")
        if "expected_children" in check:
            require(not ambiguous, "historical child output unexpectedly ambiguous")
            summary_equal(dict(status="ok", **child_total), check["expected_children"])
        return dict(scope="parent libtest targets; child observations and benchmark test-mode results separate; no doctests",
                    targets=result, totals=total, child_summaries=children, observed_child_totals=child_total,
                    child_output_ambiguous=ambiguous, bench_test_mode=benches)
    rows = summaries(text)
    require(len(rows) == 1, "expected one test result summary")
    summary_equal(rows[0], check["expected"])
    if kind == "exact":
        name = check["name"]
        require("--exact" in argv and name in argv, "exact test argv mismatch")
        require(re.search(r"^running 1 test$", text, re.M), "exact test did not select one")
        require(re.search(r"^test " + re.escape(name) + r" \.\.\.", text, re.M), "exact test name absent")
    return rows[0]


def verify(spec_path, root):
    global CURRENT
    spec_bytes = spec_path.read_bytes()
    spec = json.loads(spec_bytes)
    keys(spec, ("schema", "receipts"), ("schema", "receipts"))
    require(spec["schema"] == "quervant-perf06-c3-f1-receipt-contract-v1", "unknown contract schema")
    require(isinstance(spec["receipts"], list) and spec["receipts"], "empty receipt contract")
    planned, labels, results = set(), set(), []
    for item in spec["receipts"]:
        CURRENT = item.get("label", "invalid contract row") if isinstance(item, dict) else "invalid contract row"
        keys(item, ("path", "label", "argv", "commit", "classification", "check"), ("path", "label", "argv", "commit", "classification", "check"))
        require(isinstance(item["argv"], list) and item["argv"] and all(isinstance(a, str) for a in item["argv"]), "invalid argv contract")
        path = root / item["path"]
        require(not Path(item["path"]).is_absolute() and ".." not in Path(item["path"]).parts, "unsafe receipt path")
        require(path.is_file() and not path.is_symlink() and root in path.resolve().parents, "missing/unsafe receipt")
        require(item["path"] not in planned and item["label"] not in labels, "duplicate contract path/label")
        planned.add(item["path"]); labels.add(item["label"])
        receipt_bytes = path.read_bytes()
        receipt = json.loads(receipt_bytes)
        require(receipt["schema"] == "quervant-perf06-c3-receipt-v1", "unknown recorder schema")
        require(receipt["label"] == item["label"] and receipt["argv"] == item["argv"], "receipt command/label mismatch")
        require(re.fullmatch(r"[0-9a-f]{40}", item["commit"]), "expected immutable commit")
        require(receipt["expected_commit"] == item["commit"], "receipt commit mismatch")
        before, after = receipt["before"], receipt["after"]
        require(receipt["source_identity_valid"] is True and before == after, "source identity changed")
        require(before["head"] == item["commit"] and before["tracked_status_b64"] == "", "unclean/wrong source")
        require(re.fullmatch(r"[0-9a-f]{40}", before["tree"]) and before["tree"] == before["index_tree"], "index/tree mismatch")
        require(receipt["removed_env_names"] == ["QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE"], "environment removal mismatch")
        require(item["classification"] in ("BASELINE", "PASS", "EXPECTED_RED"), "unknown classification")
        expected_exit = 101 if item["classification"] == "EXPECTED_RED" else 0
        require(receipt["command_exit_code"] == expected_exit, "unexpected command exit")
        raw = base64.b64decode(receipt["combined_output_base64"], validate=True)
        require(len(raw) == receipt["combined_output_size"] and sha(raw) == receipt["combined_output_sha256"], "raw output hash/length mismatch")
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw.decode("utf-8"))
        checked = check_output(text, item["check"], item["argv"])
        results.append(dict(label=item["label"], path=item["path"], argv=item["argv"], commit=item["commit"],
                            classification=item["classification"], receipt_sha256=sha(receipt_bytes),
                            output_sha256=sha(raw), output_size=len(raw), check=checked))
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    require(actual == planned, "missing/undeclared acceptance files; keep diagnostics in sibling directory")
    return dict(status="PASS", schema="quervant-perf06-c3-f1-verification-v1", contract_sha256=sha(spec_bytes),
                verifier_sha256=sha(Path(__file__).read_bytes()), receipt_count=len(results), receipts=results)


if __name__ == "__main__":
    require(len(sys.argv) == 4, "usage: SPEC.json RECEIPTS_ROOT OUTPUT.json")
    spec_path, root, output = [Path(p).resolve() for p in sys.argv[1:]]
    require(root.is_dir() and root not in spec_path.parents and root not in output.parents, "spec/output must be outside receipt root")
    require(not output.exists(), "output must be a new file")
    try:
        result = verify(spec_path, root)
    except (ValueError, KeyError, TypeError, OSError) as error:
        result = dict(status="FAIL", context=CURRENT, error=str(error))
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "receipts"}, sort_keys=True))
    sys.exit(0 if result["status"] == "PASS" else 1)
~~~

## Appendix C — exact command-contract builder

Save this block as `build_f1_contract.py` with one final newline. SHA-256: `62af39cca1c0dba47ac0c58ab580cdfe8473cdeeaac05ca93b44abdf9922d2ad`. Run from the repository root. Use `BASELINE` before edits to generate six baseline entries, or the actual immutable F1_TESTED SHA after the test commit to generate all51 entries. The output path must be new and outside the checkout. It reads immutable START evidence and never executes commands.

~~~python
#!/usr/bin/env python3
"""Build the author-frozen F1 receipt contract; never execute its commands."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

START = "ee77917d303b060b0d38ab88e5d9ae73625f6676"
OLD = "docs/pr-artifacts/perf-06-c/evidence/c3/"
MANIFEST_SHA = "2f7478a2dc72fe955a8d245bade407b28194429aad33709166573bcc45b264ac"
ARGV = {
    'fin_s01': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::score::tests::c3_s01_certificate_matrix', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u02': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u02_dispatch_and_count_matrix', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u04': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u04_corruption_precedence', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u05': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u05_native_later_segment_boundary', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_u09': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c3_u09_logical_budget_edges', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_i02': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_c2_physical', 'c3_i02_real_pit_update_merge_and_paging', '--', '--exact', '--nocapture', '--test-threads=1'],
    'fin_list_c2u': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c2_u', '--', '--list', '--format', 'terse'],
    'fin_list_c2p': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::execute::c2_physical_tests::c2_p', '--', '--list', '--format', 'terse'],
    'fin_list_c2_broad': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c2_', '--', '--list', '--format', 'terse'],
    'fin_list_c3': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c3_', '--', '--list', '--format', 'terse'],
    'fin_list_integration': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_c2_physical', '--', '--list', '--format', 'terse'],
    'fin_suite_b1_int': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_b1_ordinals'],
    'fin_suite_b1_lib': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'b1_'],
    'fin_suite_b2_int': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_b2_ordinals'],
    'fin_suite_b2_lib': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'b2_'],
    'fin_suite_b3_int': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_b3_keys'],
    'fin_suite_b3_lib': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'b3_'],
    'fin_suite_c2p_t1': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::execute::c2_physical_tests::c2_p', '--', '--test-threads=1'],
    'fin_suite_c2p_t8': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::execute::c2_physical_tests::c2_p', '--', '--test-threads=8'],
    'fin_suite_c2u_t1': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c2_u', '--', '--test-threads=1'],
    'fin_suite_c2u_t8': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::unified::c2_tests::c2_u', '--', '--test-threads=8'],
    'fin_suite_c3_msrv_af': ['cargo', '+1.85.0', 'test', '-p', 'quervant-core', '--lib', '--all-features', 'c3_', '--', '--test-threads=8'],
    'fin_suite_c3_t1': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c3_', '--', '--test-threads=1'],
    'fin_suite_c3_t8': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'c3_', '--', '--test-threads=8'],
    'fin_suite_integration': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'perf06_c2_physical', '--', '--test-threads=1'],
    'fin_suite_pr15h_a': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'pr15h_a_candidate_materialization'],
    'fin_suite_pr15h_a2': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--test', 'pr15h_a2_dispatch'],
    'fin_suite_reader': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'segment::reader::stored_blocks_reader_tests::', '--', '--test-threads=8'],
    'fin_suite_score': ['cargo', '+1.98.1', 'test', '-p', 'quervant-core', '--lib', 'search::score::tests::', '--', '--test-threads=1'],
    'qa_bench_norun': ['cargo', '+1.98.1', 'bench', '--workspace', '--no-run'],
    'qa_bench_scripts': ['bash', 'benchmarks/scripts/test-scripts.sh'],
    'qa_clippy_185': ['cargo', '+1.85.0', 'clippy', '--workspace', '--all-targets', '--', '-D', 'warnings'],
    'qa_clippy_185_af': ['cargo', '+1.85.0', 'clippy', '--workspace', '--all-targets', '--all-features', '--', '-D', 'warnings'],
    'qa_clippy_198': ['cargo', '+1.98.1', 'clippy', '--workspace', '--all-targets', '--', '-D', 'warnings'],
    'qa_clippy_198_af': ['cargo', '+1.98.1', 'clippy', '--workspace', '--all-targets', '--all-features', '--', '-D', 'warnings'],
    'qa_cov_198': ['cargo', '+1.98.1', 'llvm-cov', '--workspace', '--all-targets', '--fail-under-lines', '85'],
    'qa_cov_198_af': ['cargo', '+1.98.1', 'llvm-cov', '--workspace', '--all-targets', '--all-features', '--fail-under-lines', '85'],
    'qa_doc_198': ['cargo', '+1.98.1', 'doc', '--workspace', '--no-deps'],
    'qa_doc_198_af': ['cargo', '+1.98.1', 'doc', '--workspace', '--all-features', '--no-deps'],
    'qa_fmt_185': ['cargo', '+1.85.0', 'fmt', '--all', '--', '--check'],
    'qa_fmt_198': ['cargo', '+1.98.1', 'fmt', '--all', '--', '--check'],
    'qa_test_185': ['cargo', '+1.85.0', 'test', '--workspace', '--all-targets'],
    'qa_test_185_af': ['cargo', '+1.85.0', 'test', '--workspace', '--all-targets', '--all-features'],
    'qa_test_198': ['cargo', '+1.98.1', 'test', '--workspace', '--all-targets'],
    'qa_test_198_af': ['cargo', '+1.98.1', 'test', '--workspace', '--all-targets', '--all-features'],
}
FOCUSED = ['fin_s01', 'fin_u02', 'fin_u04', 'fin_u05', 'fin_u09', 'fin_i02']
INVENTORIES = {'fin_list_c2u': 24, 'fin_list_c2p': 5, 'fin_list_c2_broad': 52, 'fin_list_c3': 26, 'fin_list_integration': 12}
COUNTS = {'fin_suite_b1_lib': 65, 'fin_suite_b2_lib': 31, 'fin_suite_b2_int': 8, 'fin_suite_b3_lib': 32, 'fin_suite_b3_int': 8, 'fin_suite_c2p_t1': 5, 'fin_suite_c2p_t8': 5, 'fin_suite_c2u_t1': 24, 'fin_suite_c2u_t8': 24, 'fin_suite_c3_msrv_af': 26, 'fin_suite_c3_t1': 26, 'fin_suite_c3_t8': 26, 'fin_suite_integration': 12, 'fin_suite_pr15h_a': 6, 'fin_suite_pr15h_a2': 8, 'fin_suite_reader': 9, 'fin_suite_score': 19}
MARKERS = {'fin_s01': 'C3 F1 S01 rows=24 isolated-df-rows=2', 'fin_u02': 'C3 F1 U02 matrix-rows=25 certified=5 legacy=20 split-c3=10 ineligible-result-rows=6', 'fin_u04': 'C3 F1 U04 rows=9 isolated-C29=true unarmed-synthetic-snapshot=C3', 'fin_u05': 'C3 F1 U05 rows=4 recoveries=4 literal-reference-errors=3', 'fin_u09': 'C3 F1 U09 rows=12 failed-rows=7 recoveries=7 fixed-projection-failure=13056/13160/100', 'fin_i02': 'C3 F1 I02 phases=5 checked-hits=198 old-pages=14 new-pages=13'}
BENCH_SMOKE = {'benches/bm25.rs': 1, 'benches/dictionary.rs': 6, 'benches/geo.rs': 2, 'benches/merge.rs': 3, 'benches/phrase.rs': 6, 'benches/postings.rs': 3, 'benches/search.rs': 18, 'benches/typed_analytics.rs': 3, 'benches/unified_diagnostics.rs': 30, 'benches/writer_mutation.rs': 2}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_git(path):
    return subprocess.check_output(["git", "show", f"{START}:{path}"], stderr=subprocess.STDOUT)


def expected(passed, ignored=0):
    return dict(passed=passed, failed=0, ignored=ignored)


def make(mode):
    require(mode == "BASELINE" or re.fullmatch(r"[0-9a-f]{40}", mode), "mode must be BASELINE or F1_TESTED SHA")
    raw = read_git(OLD + "manifest.json")
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, "original manifest mismatch")
    manifest = json.loads(raw)
    old_rows = {row["label"]: row for row in manifest["receipts"]}
    original = {}
    for label, argv in ARGV.items():
        row = old_rows[label]
        path = OLD + "receipts/" + label + ".json"
        require(row["path"] == path and row["argv"] == argv and row["classification"] == "PASS", "original command contract mismatch")
        receipt = json.loads(read_git(path))
        out = base64.b64decode(receipt["combined_output_base64"], validate=True)
        require(receipt["argv"] == argv and receipt["command_exit_code"] == 0, "original command/exit mismatch")
        require(hashlib.sha256(out).hexdigest() == receipt["combined_output_sha256"] == row["output_sha256"], "original raw hash mismatch")
        require(len(out) == receipt["combined_output_size"] == row["output_size"], "original raw size mismatch")
        original[label] = out.decode("utf-8")
    rows = []
    for label in FOCUSED:
        name = ARGV[label][ARGV[label].index("--") - 1]
        new_label = "base_" + label.removeprefix("fin_")
        rows.append(dict(path="baseline/" + new_label + ".json", label=new_label,
                         argv=ARGV[label], commit=START, classification="BASELINE",
                         check=dict(kind="exact", name=name, expected=expected(1))))
    if mode == "BASELINE":
        require(len(rows) == 6, "baseline cardinality")
        return dict(schema="quervant-perf06-c3-f1-receipt-contract-v1", receipts=rows)
    for label, argv in ARGV.items():
        if label in FOCUSED:
            check = dict(kind="exact", name=argv[argv.index("--") - 1], expected=expected(1), required_text=[MARKERS[label]])
        elif label in INVENTORIES:
            names = sorted(re.findall(r"^([^\r\n]+): test$", original[label], re.M))
            require(len(names) == len(set(names)) == INVENTORIES[label], "original inventory cardinality")
            check = dict(kind="inventory", names=names)
        elif label in COUNTS:
            check = dict(kind="summary", expected=expected(COUNTS[label]))
        elif label == "fin_suite_b1_int":
            check = dict(kind="workspace", targets=1, expected=expected(9, 2), bench_smoke={})
        elif label.startswith("qa_test_"):
            af = label.endswith("_af")
            check = dict(kind="workspace", targets=146,
                         expected=expected(2794 if af else 2749, 100 if af else 16),
                         bench_smoke=BENCH_SMOKE)
        elif label.startswith("qa_cov_"):
            check = dict(kind="coverage")
        elif label.startswith("qa_fmt_"):
            check = dict(kind="plain", empty=True)
        elif label == "qa_bench_scripts":
            check = dict(kind="plain", required_text=["script tests: 108 passed, 0 failed"])
        else:
            require(label.startswith(("qa_clippy_", "qa_doc_")) or label == "qa_bench_norun", "unknown command class")
            check = dict(kind="plain")
        new_label = "f1_" + label
        rows.append(dict(path="final/" + new_label + ".json", label=new_label,
                         argv=argv, commit=mode, classification="PASS", check=check))
    require(len(rows) == 51, "final cardinality")
    return dict(schema="quervant-perf06-c3-f1-receipt-contract-v1", receipts=rows)


if __name__ == "__main__":
    require(len(sys.argv) == 3, "usage: BASELINE_OR_F1_TESTED_SHA NEW_OUTPUT.json")
    result = make(sys.argv[1])
    output = Path(sys.argv[2]).resolve()
    require(not output.exists(), "contract output must be new")
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(dict(receipts=len(result["receipts"]), output=str(output)), sort_keys=True))
~~~

## Appendix D — execution of a generated command list

Use the original recorder and the exact argv arrays; do not join them into a shell string. The following is the complete sequential driver design, with supplied absolute paths. For baseline use classification BASELINE and the baseline contract; for final use classification PASS and the final contract. Stop immediately on a nonzero recorder exit and retain that receipt. Do not continue to a later gate or retry until the matrix permits it.

~~~python
import json
from pathlib import Path
import subprocess
import sys

# Usage: run_contract.py CONTRACT RECEIPTS_ROOT RECORDER CLASSIFICATION
contract_path, receipts_root, recorder, classification = sys.argv[1:]
assert classification in {"BASELINE", "PASS"}
root = Path(receipts_root).resolve()
assert root.is_absolute()
contract = json.loads(Path(contract_path).read_text())
for item in contract["receipts"]:
    if item["classification"] != classification:
        continue
    destination = root / item["path"]
    assert not destination.exists(), str(destination)
    command = [sys.executable, str(Path(recorder).resolve()),
               str(destination), item["commit"], item["label"], *item["argv"]]
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
~~~

The driver is optional mechanical orchestration; invoking each exact command through the recorder is equally authorized. It does not expand the selected command set, authorize retry, or bypass the per-phase matrix. Keep it outside the checkout while tests run; if used, commit its exact bytes/hash with the other bounded F1 evidence.

**Final executor rule:** preserve the implemented design, execute the specified remaining work continuously, and stop on an uncovered condition. The task is to fulfill this design and prove the named cases, not to design a different fix.
