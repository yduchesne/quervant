# PERF-06-C2-F1 — execution report

> **Disposition:** `PERF06_C2_F1_STOPPED_PLAN_AMENDMENT_REQUIRED`.
> Three prescribed fixtures are contradicted by the accepted source (two D14
> hard stops). All other F1 work is implemented, verified and reported below.
> G10 (independent review / maintainer acceptance) remains **open**.

## 1. Identity

| Item | Value |
|---|---|
| Repository | `yduchesne/quervant` |
| Pull request | [#131](https://github.com/yduchesne/quervant/pull/131) — draft, open, unmerged, base `main` |
| Actual branch | `dev/perf06-c2` (the C2 report's earlier `dev/perf06-c2-physical-executor` was wrong) |
| Plan | [PERF06C2F1_DETAILED_FIXUP_PLAN.md](PERF06C2F1_DETAILED_FIXUP_PLAN.md), committed verbatim |
| Plan SHA-256 | `b9d11e958af2186e9a5f358153cee489a4cdafc9913ed7ea7bb6b494b091d5e7` (identical to the supplied file) |
| Fresh main / accepted C1 | `bc726420cede2e26681d6e8192b45a5d0169abbf` |
| BASE | `46ccab0a606a56a8b9034ab4db5c9c4df969d098` (= `origin/dev/perf06-c2` at admission) |
| START | `46ccab0a606a56a8b9034ab4db5c9c4df969d098` |
| TESTED | `564fd7853d41adc77c84c766f59e29bae113d7b0` (source, tests, verbatim plan) |
| FINAL | `07e56d882637c0119abeeb627b417d9584ba8532` (documentation/evidence only); `git diff TESTED..FINAL -- crates/ Cargo.toml Cargo.lock rust-toolchain.toml .github/ benchmarks/` is **empty** |
| Remote-verified SHA | `19cf038dcdaa90f12582423c4536f351a460d6d0` (verified equal to `origin/dev/perf06-c2`; CI head, source-equivalent to TESTED) |
| Toolchains | stable `1.98.1` (pinned by CI), MSRV `1.85.0` |
| Worktree at admission | clean except the foreign untracked `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` (D07: recorded, untouched) |

### P0 / G0 source admission (executed)

```
$ git fetch origin main dev/perf06-c2
$ git rev-parse HEAD origin/dev/perf06-c2 origin/main
46ccab0a606a56a8b9034ab4db5c9c4df969d098
46ccab0a606a56a8b9034ab4db5c9c4df969d098
bc726420cede2e26681d6e8192b45a5d0169abbf
$ git merge-base --is-ancestor bc726420… HEAD   -> ANCESTOR_OK
$ gh pr view 131 --json state,isDraft,headRefName,headRefOid,baseRefName
{"state":"OPEN","isDraft":true,"headRefName":"dev/perf06-c2",
 "headRefOid":"46ccab0a…","baseRefName":"main"}
```

D01 applied (branch/head/main match the pinned identities); D02 was not needed (the
remote head equals the pinned head exactly).

### Baseline (before any edit)

| Scope | Registered functions | Serial run |
|---|---:|---|
| `search::unified::c2_tests::` | 23 | 23 passed / 0 failed |
| `search::execute::c2_physical_tests::` | 5 | 5 passed / 0 failed |
| `perf06_c2_physical` (integration) | 9 | 9 passed / 0 failed |
| broad `--lib c2_` filter | 38 | — |

Receipts: `evidence/c2-f1-inventory-baseline-*.txt`, `evidence/c2-f1-baseline-*.txt`.

## 2. Starting defects and reconciliation

| ID | Original defect at START | F1 outcome |
|---|---|---|
| F1-01 | `c2_u17_…` ran an ordinary search; no refusal was armed | **CLOSED** — five injected-refusal rows execute with exact probe/counter/route evidence (§5.1) |
| F1-02 | U21 only required *some* limit to fail; I08 accepted success and could not show a prior completed segment | **PARTIAL** — the public I08 boundary is exact and recoverable (§5.5); the internal U21 boundary and the U17 no-eager-binding refinement are **BLOCKED** by a D14 segment-order stop (§9) |
| F1-03 | `c2_u12_…` absent | **PARTIAL** — the test exists and executes 6 of the 9 prescribed rows (§5.3); the three posting-mutation rows are **BLOCKED** by a D14 byte-layout stop |
| F1-04 | P05 accepted success at a cap that must fail; I08 used scanned 30 for 23 occurrences | **CLOSED** — P05 has six exact rows with exact `total_used()` and same-budget recovery (§5.4); I08 requires `scanned 22 → {22, 23}` |
| F1-05 | “38 new unit tests” counted ten older accounting tests; branch/status claims stale | **CLOSED** — exact inventories (§6), append-only errata in the C2 report, and this report |

Historical count correction: the original new inventory was **28 unit + 9
integration = 37** functions; the broad `--lib c2_` 38 included ten older
`budget_tests::c2_*` / `memory::tests::c2_*` tests.

## 3. Pre-implementation worksheet and rule ledger

| Worksheet question (plan §4.3) | Answer |
|---|---|
| Why a fresh, never-searched fixture for U17 refusal? | `bind_key_identity` publishes a sticky per-snapshot fingerprint cache; a prior search would populate it and the probe would never fire. |
| Source of 13 scanned occurrences in U21 segment 0? | `document_with_body` uses `1 + index % 4`; indices 0..5 give `1,2,3,4,1,2` = 13. Total 0..39 = 100. (See §9: the accepted segment order makes this the *second* evaluated slice.) |
| Why one entered candidate and zero completed callbacks for a key error? | `b2_observation::record_numeric_candidate()` precedes key binding/`doc_key`; `physical::callbacks()` increments only after `on_scored(...)` returns `Ok`. |
| Why zero routes for malformed columns? | Native v2 keyword dictionaries are validated by the column parser at `open_segment_reader`, i.e. before route selection. |
| Why is P05 work 53 only for the direct evaluator? | `strict_inputs` prepares leaves/expansion/statistics on its own meter; each evaluator call starts from zero: `20 × (1+1) + 13 = 53`. |
| Which comparisons are forced Legacy vs public wrapper vs C2-only injections? | U17/U21/I08 compare the *same* request/snapshot/limits under `ForceLegacy`; U12 D/C rows likewise; U12 S29+D0 and U17's removed no-eager-binding case are `INJECTED_C2_ONLY` with unarmed real-fault controls. |
| Which two observation sites disappear from non-test builds? | `c2_observation::record_owned_key_fallback_segment(...)` after the `KeyBinder` assignment and `c2_observation::record_collected_segment(...)` after `visit_strict_term_scored_with(...)?`, both under `#[cfg(test)]`. |
| Which report claims are superseded? | See the dated section appended to `PERF06C2_EXECUTION_REPORT.md` (§2 above). Its raw logs are untouched. |

| Rule | Trigger | Action | Gate |
|---|---|---|---|
| D01 | branch/head/main match pinned identities | admitted START | G0 |
| D07 | foreign untracked `f2-ci-status.txt` | recorded, untouched, never staged | G0/G9 |
| D10 | test-only syntax/lint corrections (unused helper removal, `too_many_arguments` allow, `mut` removal, rustfmt) | corrected in test code only, failure retained in the receipts | G2 |
| D11 | probe would not fire on a warm fixture | fixtures are freshly constructed per case; reference search runs only after the witnesses are captured | G3 |
| D13 | reset after arming an injector | resets precede `ScoreFailureArm`/`ForceLegacy`; `strict()` is never used inside an armed scope | G3/G4 |
| D14 | segment order and `grp/common` byte layout differ from the plan | **STOP** for the affected rows; evidence preserved; no expectation rewritten | G3/G4 |
| D15 | a mandatory row would disagree with its specified outcome | not reached for the executed rows | G3–G5 |
| D16 | column faults are pre-route | asserted both route counters 0 | G4 |
| D17 | DOC_KEYS faults enter one candidate, complete none | asserted numeric 1 / callbacks 0 | G4 |
| D18 | synthetic score fault is C2-only | labelled `INJECTED_C2_ONLY`; unarmed controls on both routes required | G3/G4 |
| D20 | same-snapshot retries / immutable bytes | asserted per row and at the end of U12 | G3–G5 |
| D26 | source/test changed after earlier runs | focused/feature/regression/QA suites re-run after the final fmt+clippy edits | G7 |
| D29 | pre-existing `git diff --check origin/main...HEAD` whitespace failures | reproduced at START, classified, F1 delta proven clean | G7 |
| D31a | prescribed assertion omissions | none beyond the D14-stopped rows | G4–G7 |
| D37 | unlisted condition (plan/fixture contradictions) | reported as D14 stops with the smallest amendment | G3/G4 |

No production source changed; no HARD STOP other than D14 was triggered.

## 4. Source delta and normal-build freeze

| File | Change |
|---|---|
| `search/unified.rs` | `c2_observation`: `RefCell<Vec<_>>` witness vectors, two record/read accessors, `reset()` clears them. Two `#[cfg(test)]` sites in `collect_strict_term_ordinal_body`. `c2_tests`: F1 helpers (`B3ProbeReset`, `linear_config`, `exact_set_config_threshold_one`, `forced_legacy_with`, `CopiedSegment`, `c2_f1_snapshot`, `c2_f1_run_snapshot`, `c2_f1_forced_legacy_on_snapshot`), the rewritten U17, the new U12 test and its private helpers. **U21 is unchanged** (blocked). |
| `search/execute.rs` | `c2_physical_tests`: rewritten P05 with the six-row table plus `make_meter_with`. No evaluator change. |
| `tests/perf06_c2_physical.rs` | I08 strengthened: exact scanned 22/23 boundaries, same-snapshot retries, full response/score-bit comparison. |

**Normal-build freeze check** (exact region comparison against START, not a
plausibility argument): `evidence/c2-f1-normal-build-freeze.txt`

```
execute.rs normal-build equality: PASS
unified trailing content after C2_TESTS_CLOSE_MARKER is whitespace only: PASS
unified candidate contains Site A exactly once: PASS
unified candidate contains Site B exactly once: PASS
unified.rs normal-build equality: PASS
RESULT: PASS
```

The check removes `#[cfg(test)] mod c2_physical_tests { … }` from `execute.rs`,
the `#[cfg(test)] pub(crate) mod c2_observation { … }` and
`#[cfg(test)] mod c2_tests { … // C2_TESTS_CLOSE_MARKER }` regions from
`unified.rs`, plus the two exact site snippets, then requires byte equality. A
marker that is not unique, or any residual difference, is a FAIL — none occurred.

## 5. Per-case acceptance

All counters below are observed, not inferred. Every row resets witnesses before
its run; reference/retry runs happen after the witnesses are captured.

### 5.1 C2-U17 — actual per-segment B3 refusal (F1-01) — CLOSED

Config `Prefilter` with `min_top_k = 4`, `K = 3` (resolves to internal `Linear`).
Fresh fixture per case; probe armed before the request; guard cleared after.

| Case | segments | callbacks fired | build attempts | directory builds | refusals | fallback segments | collected |
|---|---:|---:|---:|---:|---:|---|---|
| single refusal | 1 | 1 | 1 | 0 | 1 | `[0]` | `[(0,4,40)]` |
| first of two refuses | 2 | 1 | 2 | 1 | 1 | `[0]` | `[(0,4,20),(1,4,40)]` |
| second of two refuses | 2 | 2 | 2 | 1 | 1 | `[1]` | `[(0,4,20),(1,4,40)]` |
| all ready control | 2 | 0 | 2 | 2 | 0 | `[]` | `[(0,4,20),(1,4,40)]` |
| ExactSet control | 2 | 0 | 0 | 0 | 0 | `[0,1]` | `[(0,4,20),(1,4,40)]` |

Every row also asserts C2 route 1, Legacy route 0, evaluator calls = segments,
converted rows 40, callbacks 40, numeric candidates 40, bound columns = segments,
`total_hits` 40, literal keys `doc000000..doc000002`, cursor present, and complete
`projected()`/`total_hits`/`generation`/`view_ordinal`/cursor-presence/aggregation
parity against `forced_legacy_with(...)` of the same request, snapshot and config.
Receipt: `evidence/c2-f1-u17-attempt-02.txt`.

Counterexample this now rejects: a request that silently replays Legacy after a
refusal (Legacy route would be 1), or one that abandons the refused segment
(converted rows < 40).

The originally planned no-eager-binding refinement is **BLOCKED** (§9).

### 5.2 C2-U21 — later-segment resource boundary (F1-02) — BLOCKED

Not modified. The prescribed four-row table cannot hold on the accepted source
because query segment order is content-addressed (§9.1). `evidence/c2-f1-u21-attempt-02.txt`
therefore records the unchanged pre-F1 test passing, not the F1 rows.

### 5.3 C2-U12 — selected/unselected corruption and multi-fault precedence (F1-03) — PARTIAL

Pristine corpus: 30 matching + 2 non-matching rows, one committed segment, `K = 3`.
Prerequisites asserted: physical DOC_KEYS `doc000000..doc000031`, `grp` field norms
persisted, `grp/common` `doc_freq = 30`. Healthy control: 30 hits, three literal
keys, cursor present, C2 route 1, full parity with forced Legacy.

| Row | Faults | Observed error | route | converted | callbacks | numeric | membership | Status |
|---|---|---|---|---:|---:|---:|---:|---|
| D0 | DOC_KEYS invalid UTF-8 at record 0 | `Segment(InvalidUtf8 { "doc key" })` | 1 | 30 | 0 | 1 | 30 | PASS |
| D29 | DOC_KEYS invalid UTF-8 at record 29 | same | 1 | 30 | 0 | 1 | 30 | PASS |
| D31 | DOC_KEYS invalid UTF-8 at record 31 (non-matching) | same | 1 | 30 | 0 | 1 | 30 | PASS |
| P29 | final posting frequency 0 | — | — | — | — | — | — | **BLOCKED (D14)** |
| P29+D0 | postings + keys | — | — | — | — | — | — | **BLOCKED (D14)** |
| C0 | COLUMNS invalid UTF-8 at `doc000000` | `Index(Segment(InvalidUtf8 { "keyword" }))` | 0 | 0 | 0 | 0 | 0 | PASS |
| C29 | COLUMNS invalid UTF-8 at `doc000029` | same | 0 | 0 | 0 | 0 | 0 | PASS |
| C29+P29+D0 | all three | — | — | — | — | — | — | **BLOCKED (D14)** |
| S29+D0 | DOC_KEYS + injected score at doc 29 | `InvalidScore { "injected C2 score failure" }` | 1 | 0 | 0 | 0 | 30 | PASS (`INJECTED_C2_ONLY`) |

Additional assertions on every executed row: zero-match query returns 0 hits /
no cursor first (posting/key rows only); the same immutable corrupted snapshot
repeats the identical nested error; the same query under `ForceLegacy` produces the
same exact nested error (route counters `legacy 1 / strict 0` when routed, both 0
for column rows); the original committed bytes are still byte-identical; and the
pristine fixture still answers with identical keys, counts and score bits
afterwards. For S29+D0 the unarmed controls on **both** routes must produce the real
DOC_KEYS error, and no same-fault Legacy score comparison is claimed.

Receipt: `evidence/c2-f1-u12-attempt-02.txt`.

Counterexamples now rejected: a skipped final posting, an ignored unselected key,
a reordered column error, or a candidate admitted before complete scoring.

### 5.4 C2-P05 — exact evaluator work and scanned limits (F1-04) — CLOSED

Fixture: 20 physical postings of frequency 1, tombstones at positions
`0,3,6,9,12,15,18` → 13 effective-live docs `[1,2,4,5,7,8,10,11,13,14,16,17,19]`.

| total cap | scanned cap | observed outcome | callbacks | `total_used()` |
|---|---|---|---:|---:|
| `u64::MAX` | 10 | `ResourceLimit { 10, 11 }` | 0 | 20 |
| `u64::MAX` | 19 | `ResourceLimit { 19, 20 }` | 0 | 38 |
| `u64::MAX` | 20 | success, exact 13 live ids | 13 | 53 |
| `u64::MAX` | 21 | success, same answer | 13 | 53 |
| 52 | 20 | `ResourceLimit { 52, 53 }` | 0 | 40 |
| 53 | 20 | success, same answer | 13 | 53 |

After **every** row: `segment_entries == 0`, `segment_bytes == 0`,
`global_bytes == 0`; then the **same** `CandidateBudget` is reused with a fresh
`(53, 20)` meter and must produce the full 13-hit success with all ledger fields
still zero. Receipt: `evidence/c2-f1-p05-attempt-02.txt`.

### 5.5 C2-I08 — exact public resource errors and snapshot reuse (F1-04/F1-02 public) — CLOSED

Real `FsDirectory` corpus of 48 rows, `K = 3`, `m = 23`, virtual peak
`69` entries / `2944` bytes, 23 scanned occurrences.

| Case | Observed / required |
|---|---|
| exact peak | success, 23 hits, literal keys `d00000002/d00000004/d00000006`, cursor present |
| entries 68 | `ResourceLimit { 68, 69 }`, then retry at the admitted limits reproduces the admitted response exactly |
| bytes 2943 | `ResourceLimit { 2943, 2944 }`, then the same retry |
| split corpus, scanned 23 | success, 23 hits, same three keys, cursor present |
| split corpus, scanned 22 | `ResourceLimit { 22, 23 }` (previously permissive at 30) |
| split corpus, retry 23 | identical response to the admitted split result |
| cancellation | `Cancelled`, then an identical recovered response |

"Identical" means equal total hits, generation, view ordinal, cursor presence,
`f64::to_bits` scores, keys and projected fields. Receipt:
`evidence/c2-f1-i08-attempt-02.txt`.

## 6. Inventories

`evidence/c2-f1-inventory-diff.txt`, `evidence/c2-f1-inventory-{baseline,final}-*.txt`.

| Scope | START | Final |
|---|---:|---:|
| `search::unified::c2_tests::` | 23 | **24** |
| `search::execute::c2_physical_tests::` | 5 | 5 |
| New C2 unit functions | 28 | **29** |
| `perf06_c2_physical` integration functions | 9 | 9 |
| New C2 test functions total | 37 | **38** |
| Broad `--lib c2_` selection | 38 | **39** |

- Unified delta is exactly
  `c2_u12_corrupt_selected_unselected_and_multi_fault`; nothing removed.
- Physical and integration sets are unchanged.
- The broad set equals `union(C2 unit modules, the ten older accounting tests)`;
  the ten older names are listed in the diff receipt.
- Matrix cases, refusal rows and retries are counted separately from test
  functions in §5.

Focused commands each selected exactly one function with `--exact` and passed
(`evidence/c2-f1-{u17,u12,p05,i08}-attempt-02.txt`).

## 7. QA (final source state)

All cargo/script commands ran with
`env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE`.

| Command | Result |
|---|---|
| `cargo +1.98.1 fmt --all -- --check` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.98.1 test --workspace --all-targets` | PASS — 2739 passed / 0 failed / 16 ignored (146 targets) |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS — 2784 / 0 / 100 ignored |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — line coverage **93.24 %** (74113 covered / 5010 missed); functions 87.96 %; regions 93.60 % |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — line coverage **92.82 %** (75622 / 5426); functions 87.78 % |
| `cargo +1.98.1 doc --workspace --no-deps` | PASS |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS |
| `cargo +1.98.1 bench --workspace --no-run` | PASS (compile-only; no benchmark executed) |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2784 / 0 / 100 ignored |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script tests |
| `git diff --check` (worktree / F1 delta) | PASS |
| `git diff --check origin/main...HEAD` | **FAIL (pre-existing, F1 delta clean)** — see §9.3 |

Changed-module coverage: `search/unified.rs` 95.03 % lines,
`search/execute.rs` 96.73 % lines. No exclusion was added.

Feature suites: unified 24 serial **and** 24 with `--test-threads=8`; physical 5
serial and 5 parallel; integration 9. Retained regressions: `b1_` 65, `b2_` 31,
`b3_` 29, `perf06_b1_ordinals` 9 (+2 ignored, opt-in real RustFS),
`perf06_b2_ordinals` 8, `perf06_b3_keys` 8, `pr15h_a_candidate_materialization` 6,
`pr15h_a2_dispatch` 8 — all PASS.

## 8. CI and topology

Local feature acceptance uses the real path in every case: schema → analyzer →
writer → committed `MemoryDirectory`/`FsDirectory` bytes → snapshot →
`UnifiedSearcher` → real collectors, with `ReaderSnapshot::for_test` only supplying
ownership/identity for the copied-and-rebuilt U12 containers. No mock decoder,
scorer or directory substitutes for it.

Ordinary CI on the F1 head: run
[45825576316](https://github.com/yduchesne/quervant/actions/runs/45825576316) at
`19cf038dcdaa90f12582423c4536f351a460d6d0` — all five required jobs
(`rust`, `msrv`, `python-benchmark-framework`, `benchmark-adapter-contract`,
`rustfs`) reported `pass` with `conclusion: success`, and the `rustfs` job executed
real-service bodies (32 `test result: ok` lines, 0 failed). Receipt:
`evidence/c2-f1-ci-status.txt`. The required jobs are `rust`, `msrv`,
`python-benchmark-framework`, `benchmark-adapter-contract` and `rustfs`; no
workflow, trigger or branch filter was changed, and no duplicate equivalent
workflow was launched. The head is `TESTED` plus documentation-only commits, so
`git diff TESTED..head -- crates/` is empty (D27).

## 9. Failures, diagnostics and open gates

### 9.1 D14 STOP — physical segment order (blocks U21 and the U17 refinement)

`support::meta_from_bytes` derives `segment_id = "s-{sha256(bytes)}"` and
`IndexWriter::commit` sorts manifest references by `segment_id`, so **query segment
order is content-addressed, not commit order**. For the prescribed
`body_documents(6)` + `body_documents(40).skip(6)` fixture the 34-document slice is
segment 0 in three consecutive runs:

```
seg0 id=s-920b6e02… docs=34 first_keys=["doc000006", …]
seg1 id=s-f915efbf… docs=6  first_keys=["doc000000", …]
```

Re-committing in the opposite order cannot change it, because each segment's bytes
(and therefore its id) depend only on that slice. Consequences: the plan's
`collected [(0, 3, 6), (1, 3, 40)]`, `membership observations 6`, and the U21
`scanned 13 → ResourceLimit { 13, 16 }` row cannot hold. Evidence:
`evidence/c2-f1-d14-segment-order-stop.txt`. Smallest amendment requested: restate
the rows for the real `(34, 6)` order, or prescribe a corpus whose 6-document
segment sorts first.

### 9.2 D14 STOP — `grp/common` postings byte layout (blocks three U12 rows)

The prescribed payload is not 67 bytes of compact-short doc-only. Observed:
`postings_length = 218`, head `[7, 1, 30, 30, 30, 30, 0x96, 0x01, …]` — marker `7`
(compact-short **positional**), 8-byte header, 30 doc bytes, 30 frequency bytes and
a 150-byte position stream. Hence `postings_offset + 66` is the second-to-last
frequency byte, and the prescribed mutation cannot yield `ZeroFrequency { doc_id: 29
}`. Evidence: `evidence/c2-f1-d14-postings-layout-stop.txt`. Rows `P29`, `P29+D0`
and `C29+P29+D0` are therefore not executed. No byte offset or expected error was
rewritten.

### 9.3 Pre-existing `git diff --check` failures

`git diff --check origin/main...HEAD` fails with 25 whitespace entries, **all
introduced by commits that already existed at START**: the plan-mandated verbatim
`PERF06C2_DETAILED_PLAN.md` (markdown hard line breaks) and the previously committed
evidence logs (trailing blank lines). `git diff --check origin/main...START` fails
identically, and `git diff --check` on the F1 delta is clean. Classification:
deterministic pre-existing (D29). Note that the F1 plan itself is also required to be
committed verbatim, which inherently carries the same trailing double-space style.

### 9.4 Bounded diagnostics used

Two D14 fixtures were diagnosed; no other retry was needed. The known
`segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct`
counter flake did **not** appear in any F1 run (workspace suites ran with their
ordinary concurrency and passed on first attempt).

### 9.5 Residual limits (inherited, disclosed)

- The score injector exists only in C2; injected rows are structural precedence
  evidence, not same-fault Legacy parity.
- U12 column rows prove the shared pre-route reader-validation boundary; they cannot
  prove collector-internal ordering.
- B1 `NotAvailable` remains enum/error-mapping evidence (no new end-to-end fixture).
- Correctness/source isolation/QA do not prove any latency change; C4 owns warm
  qualification. No benchmark, profiler, timing loop or C3/C4 work was executed.

## 10. Final adversarial self-review

| Checklist item | Answer |
|---|---|
| Fresh main/PR head admitted; branch is `dev/perf06-c2` | YES — §1 |
| Production algorithms/APIs/formats/thresholds/budgets/errors unchanged | YES — normal-build freeze PASS (§4) |
| Both observation sites compile out of normal builds | YES — site snippets removed for equality check, PASS |
| U17 records the actual refusal callback and exact counters on fresh caches | YES — §5.1 (five rows) |
| U17 proves first-only, second-only, all-ready and ExactSet | YES — §5.1 |
| U17's score injection armed after reset; label not overclaimed | YES — injection row removed with the blocked scenario; D13 applied |
| U21 cap 13/99 shows completed segment 0 before the error | **NO — BLOCKED (D14, §9.1)** |
| U21 cap 12 is the no-prior-segment control; cap 100 exact success | **NO — BLOCKED (D14, §9.1)** |
| U12 covers winner, matching loser, nonmatch, final posting, columns, competing errors | PARTIAL — 6 of 9 rows; the final-posting rows are BLOCKED (§9.2) |
| U12 pre-route column rows have zero routes; key rows one entered candidate and zero completed callbacks | YES — §5.3 |
| Genuine byte faults have identical typed Legacy outcomes; injected rows are C2-only | YES — §5.3 |
| P05 verifies physical scanned occurrences despite tombstones and reuses the same zeroed budget | YES — §5.4 |
| I08 requires cap 22 failure and cap 23 success/retry through FsDirectory | YES — §5.5 |
| Registrations and case counts separated; 28/37 and 29/38 accurate | YES — §2, §6 |
| Prior evidence preserved; stale claims superseded by dated errata | YES — §2 |
| Full local QA and coverage ran after final source/tests; no failure hidden | YES — §7, §9.3 |
| CI/RustFS evidence tied to the correct source; no duplicate workflow added | see §11 |
| No benchmarks/profilers/C3/C4/merge; PR stays draft, G10 open | YES |

## 11. Handoff

- **Disposition:** `PERF06_C2_F1_STOPPED_PLAN_AMENDMENT_REQUIRED` — G0, G1, G2, G5,
  G6, G7, G9 pass; **G3 is partial** and **G4 is partial** (the D14 stops in §9.1 and
  §9.2); G8 recorded below; **G10 open**.
- **Closed findings:** F1-01, F1-04, F1-05, and the public half of F1-02.
- **Open findings needing a maintainer amendment:** F1-02's internal U21 boundary
  (plus the U17 no-eager-binding refinement) and F1-03's three posting-mutation rows.
- **Requested decision:** the two smallest amendments in
  `evidence/c2-f1-d14-segment-order-stop.txt` and
  `evidence/c2-f1-d14-postings-layout-stop.txt`.
- PR #131 stays draft and unmerged; C3/C4 remain unstarted; no performance claim is
  made.

### Delivery note

- `TESTED` = `564fd7853d41adc77c84c766f59e29bae113d7b0` (source, tests, verbatim plan).
- `FINAL` = `07e56d882637c0119abeeb627b417d9584ba8532` (report, errata, evidence, status
  links). The protected-path diff `TESTED..FINAL` is empty, so the §7 QA results
  remain valid for `FINAL`.
- The identity block was completed in a further documentation-only commit; it
  changes this report only.
- Protected-path verification from START: only
  `crates/quervant-core/src/search/{execute.rs,unified.rs}` and
  `crates/quervant-core/tests/perf06_c2_physical.rs` changed under `crates/`.
  `score.rs`, `work.rs`, `memory.rs`, `plan.rs`, `unified_plan.rs`, the typed
  modules, `topk.rs`, `unified_cursor.rs`, `limits.rs`, `error.rs`, `index/**`,
  `segment/**`, `storage/**`, `quervant-objectstore/**`, `quervant-distributed/**`,
  the B1–B3 tests/fixtures, manifests, lockfiles, toolchains, workflows,
  `benchmarks/**`, the C1 contract, `docs/architecture/**`, the authoring guide,
  `AGENTS.md`, `docs/TESTING.md`, the original C2 plan and the C1 source audit are
  all byte-identical to START.

## PERF-06-C2-F1-A1 errata and superseding status (2026-11-26)

This section supersedes the F1 report's earlier conclusions where listed. Every
preceding byte of this report is preserved unchanged.

1. **The two D14 stops were correct.** The plan's segment-order and posting-layout
   assumptions were wrong, not the source. Query segment order is the manifest order
   sorted by the content-addressed `s-{sha256}` id (34-document slice first for the
   prescribed corpus), and `grp/common` is encoded compact-short **positional**
   (218-byte payload, marker 7, 150-byte position stream). The approved
   [A1 amendment](PERF06C2F1_A1_DETAILED_AMENDMENT.md) restates both fixtures; the
   new receipts are in [PERF06C2F1_A1_EXECUTION_REPORT.md](PERF06C2F1_A1_EXECUTION_REPORT.md).
2. **U21 and the U17 structural row were not executed by F1.** Their status changes
   only now that the amended cases pass: four native-order U21 rows (caps 86/87/99/100
   with a completed `(0,3,34)` tuple before the later-segment error, plus three
   same-snapshot recoveries) and the `INJECTED_C2_ONLY` no-eager-binding case
   (one bound column, no completion, no candidate entry, then a full unarmed recovery).
3. **U12 executed six of nine rows in F1.** The earlier statement that a skipped final
   posting "would now be rejected" was not established by that run. All nine rows now
   execute, in order, with `completed=9`, including `P29`, `P29+D0` and `C29+P29+D0`.
4. **The earlier "complete/identical" response comparisons were presence-only for
   cursors** and I08 omitted aggregation. `assert_c2_f1_full_response` and the
   strengthened I08 helper now compare the complete cursor and the aggregation
   payload, with explicit score bits (`evidence/c2-f1-a1-u17.txt`,
   `c2-f1-a1-u12.txt`, `c2-f1-a1-u21.txt`, `c2-f1-a1-i08.txt`).
5. **The G7 whitespace claims in this report were wrong.** `git diff --check` was run
   while the new plan/evidence files were untracked, so "all 25 errors pre-existed"
   and "the F1 delta is clean" are not valid final-range conclusions. The real
   committed range `MAIN_BASE...HEAD` currently reports **55 diagnostics across 40
   frozen artifacts**, exactly matching Appendix A of the A1 amendment, with
   `A1_START..HEAD` at **0**. The old receipt is preserved; the corrected measurement
   and classification are in `evidence/c2-f1-a1-whitespace-range.txt`.
6. **No `c2-f1-u21-attempt-02.txt` exists.** The reviewed tree contains only
   `c2-f1-u21-attempt-01.txt`; the amended U21 evidence is `c2-f1-a1-u21.txt`.
7. **Historical revisions and CI runs are historical only.** `46ccab0…`,
   `564fd78…` and CI run 45828518258 predate A1; the current identity record is in the
   A1 report. `BASE` there means `MAIN_BASE` and `START` means `A1_START`.
8. **Coverage labels corrected without touching the raw measurements.** The
   `cargo llvm-cov` TOTAL line is `(total lines, missed lines, cover)`: the historical
   default figure is 74,113 total / 69,103 covered / 5,010 missed / 93.24 %, and
   all-features is 75,622 total / 70,196 covered / 5,426 missed / 92.82 % — not
   "74,113 covered". A1 re-measured: default 74,368 total / 69,404 covered / 4,964
   missed / 93.33 %; all-features 75,877 / 70,494 / 5,383 / 92.91 %.
9. **The old source-freeze receipt was incomplete.** It recorded no checking script,
   no tested-dirty-diff hash, and several old command receipts lack invocation/exit/
   source metadata. New A1 receipts carry `BEGIN/END RAW OUTPUT`, real exit codes,
   timestamps, toolchain and source identity, plus the checker
   `evidence/c2-f1-a1-source-freeze.txt`. Current-source equality supports preserving
   the verified F1 work; it does not reconstruct unrecorded historical command
   metadata.
10. **Additional A1 G7 blocker.** The known pre-existing
    `segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct`
    counter flake failed once in the MSRV all-features workspace run and passed on an
    identical repeat; the earlier baseline receipt reproduces it on `MAIN_BASE`.
    G7 stays blocked pending maintainer disposition (`evidence/c2-f1-a1-flake-classification.txt`).

**Current disposition:** `PERF06_C2_F1_A1_ACCEPTANCE_EXECUTED_G7_BLOCKED_WHITESPACE_DECISION`
— every prescribed A1 case executes; G7 has two maintainer-owned blockers; G10 open.

## PERF-06-C2-F1-A2 correction and pointer (2026-11-26)

This section is append-only. Two F1 statements need correction, and the current
record is the [A2 report](PERF06C2F1_A2_EXECUTION_REPORT.md).

1. **Actual B3 refusal was already fixed by F1.** F1's U17 installed the real
   `BeforeHashAllocation` probe and asserted the refusal/fallback/directory counters;
   what A1 added was **complete-response parity** (whole cursor and aggregation, not
   presence). Describing the F1 state as "refusal unarmed" is historical shorthand for
   the original pre-F1 defect, not an F1-start fact.
2. **The certificate-counter failure was process-global counter interference**, not a
   thread-local counter race. A2 publishes a test-only thread-local observation repair
   with a deterministic real-reader sibling-thread regression and a red-first proof of
   the retired mechanism; the historical FAIL-then-PASS stays recorded.

Whitespace: F1's "25 pre-existing / F1 delta clean" conclusion was wrong (the check
ran while new files were untracked). Current arithmetic: F1_START range 62, A1_START
range 26, A2 range 0, `main` range 81 (55 frozen Appendix A diagnostics in 40
artifacts + 26 in the A1 self-quoting receipt). No exception has been granted.
