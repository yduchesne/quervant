# PR 15F P0 — Reviewer fixup and QA provenance addendum

**Status:** `FIXUP_IMPLEMENTED_LOCAL_QA_PASS_CI_BLOCKED`. This is not merge
approval. The historic performance evidence was **not** regenerated, recaptured or
rewritten.

## 1. Reviewer findings addressed

| Finding | Disposition |
|---|---|
| **F15F-01** — `verify.py` unconditionally wrote C10/C11 as `PASS` although it does not execute or consume authenticated test results | Fixed: future evaluator calls now record C10/C11 as `NOT_MEASURED` with an explicit "not executed or independently attested by this verifier" detail. No new attestation schema, importer, runner or bypass flag was added. |
| **F15F-02** — documents described the earlier push SHA as the current branch head | Corrected: the original author push was `3594a9f338d82e85ca826b047a690814ca7df567`; the independently inspected review head as of 2026-11-03 was `94529467e7934ab8462b5bee7a8f2e36283b834c`. The eventual fixup HEAD is recorded in the PR/final agent report, never hardcoded into a file that would then require another commit. |
| **C12** — no exact-head hosted CI | Still blocked. See §6. |
| **C14** — independent reviewer acceptance | Still pending and human-owned. See §6. |

## 2. Provenance ladder

These are four different facts and must not be conflated:

| Level | Meaning here | Current state |
|---|---|---|
| **Campaign-qualified** | Profiling captures passed oracle, sampling, contention, source-bound and layout-reconciliation rules | `P0_QUALIFIED_REVIEW_READY` for the historic `run-02` campaign |
| **External-QA-attested** | A trusted verifier executed and machine-attested the local test/QA suites | **Not claimed.** The verifier never did this and now says `NOT_MEASURED` |
| **Hosted-CI-green** | Required `rust`/`msrv`/`rustfs` jobs passed on the exact final head | **Not achieved** (`BLOCKED_CREDENTIALS`/no PR-triggered run) |
| **Reviewer-approved** | An independent human accepted source and evidence and authorized merge | **Pending** |

`P0_QUALIFIED_REVIEW_READY` therefore means "the profiling evidence is reviewable",
not "tests were independently attested", "CI is green", or "merge is approved".

## 3. Historical report remains immutable

`benchmarks/reports/pr15f/p0-profile-summary.json` is preserved byte-for-byte:

- SHA-256: `384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096`
- Its historical `C10: PASS` and `C11: PASS` entries were emitted by the **old**
  unconditional verifier semantics. They must be read as author-reported external
  QA, not as machine attestations.
- The historic report was **not** republished through the modified verifier.
  Changing `verify.py`/`test_verify.py` after capture places them outside the
  measured-source post-capture allowlist, so the strict `C01` source gate must
  continue to reject republishing that campaign. No allowlist was widened.
- `verify.py --publish-sanitized`/`--publish-partial` was **not** run against
  `target/pr15f/run-02/` after this fixup.

The full metrics, ranking, layout and source identities in the historic report are
unchanged. This document does not restate or replace them.

## 4. Verifier gate semantics: before and after

| Gate | Historical verifier (produced the report) | Fixed verifier (future evaluations) |
|---|---|---|
| C09 Evidence integrity/privacy | `PASS` (raw evidence under `target/`, sanitizer) | Unchanged `PASS` |
| C10 Tests | Unconditional `PASS` — **not** an execution attestation | `NOT_MEASURED`: "External test execution is documented in p0-execution.md; not executed or independently attested by this verifier" |
| C11 Repository QA | Unconditional `PASS` — **not** an execution attestation | `NOT_MEASURED`: "External repository QA is documented in p0-execution.md; not executed or independently attested by this verifier" |
| C12 CI | `BLOCKED` | Unchanged `BLOCKED` |
| C14 Reviewer | `BLOCKED` | Unchanged `BLOCKED` |

`build_summary()`'s profiling-status calculation is unchanged: it still uses
C01–C08 plus allocation availability. A `NOT_MEASURED` C10/C11 does not downgrade
campaign evidence readiness, and a qualified campaign does not imply external QA
or merge approval.

## 5. What the author reported and what this fixup executed

The historic `p0-execution.md` QA table is an **author report** of commands that
were run before that document was committed. The reviewer did not independently
replay them, and the historic verifier did not attest them.

For this fixup, the agent executed the targeted and full recorded gates again on
the fixup tree. Result: all required local commands passed; workspace
all-features line coverage remeasured at **92.52%**. Evidence logs are under the
ignored `target/pr15f/fixup/` directory. This remains agent-executed QA, not an
independent reviewer replay and not hosted CI.

| Check | Result |
|---|---|
| PR 15F Python tests (including new F15F tests) | PASS — 54 tests |
| PR 15D harness tests | PASS — 83 tests |
| PR 15E tests | PASS — 90 tests, 1 skipped |
| PR 15E-B1 tests | PASS — 64 tests |
| Stable + MSRV fmt / clippy (default and all features) | PASS |
| Stable + MSRV workspace tests | PASS — 2,227 default / 2,231 all-features each |
| Coverage (`cargo llvm-cov … --fail-under-lines 85`) | PASS — 92.52% lines |
| Docs, `cargo bench --no-run`, script tests | PASS — 108 script tests |
| Probe tests (stable + MSRV) | PASS — 11 tests each |
| `git diff --check`, report JSON validation | PASS |

## 6. Branch identity and external gates

| Item | SHA / state |
|---|---|
| Original author push | `3594a9f338d82e85ca826b047a690814ca7df567` |
| Independent review head (2026-11-03) | `94529467e7934ab8462b5bee7a8f2e36283b834c` |
| Fixup commit / final remote head | Recorded in the PR and final agent report; not hardcoded here |

- **C12 — `BLOCKED_CREDENTIALS`.** SSH push is available, but the local `gh`
  credential is invalid (`HTTP 401: Bad credentials`) and no other GitHub API
  credential is configured. `.github/workflows/ci.yml` triggers only on `main`
  pushes and pull requests, so no exact-head `rust`, `msrv` or `rustfs` job has run
  for the fixup. Local QA does not substitute for hosted CI.
- **C14 — pending.** The author does not self-approve or merge. A human reviewer
  must accept the source, evidence and this provenance correction.

## 7. Tests added for this fixup

| Test | Assertion |
|---|---|
| T-F01 | Real `evaluate()` records C10/C11 as `NOT_MEASURED`, with "not executed or independently attested"; a documented `p0-execution.md` is not consumed as evidence |
| T-F02 | C09 remains `PASS`, C12/C14 remain `BLOCKED`, C08 remains `NOT_MEASURED` without analysis |
| T-F03 | Real `build_summary()` still yields profiling readiness with C01–C08 PASS and C10/C11 `NOT_MEASURED`; C12/C14 remain blocked |
| T-F04 | A post-measurement diff containing `verify.py` or `test_verify.py` fails C01; a docs-only diff preserves C01/C02 |
| T-F05 | The historic report path still resolves to the unchanged historical SHA-256 |
| Existing tests | Sanitizer/publication/source/ranking tests remain in place; publication tests use temporary destinations |

## 8. Explicitly not done

- No perf, heaptrack, reopen or inventory recapture; no metric, percentage,
  ranking, source-lock, summary or frozen-input change.
- No `crates/` or other production change; no ObjectStore/RustFS work.
- No C01 allowlist widening, no re-publication of the historic campaign, no edit
  of the historic JSON report.
- No P1–P5 optimization, format change or architecture authorization.
- **NO_OPTIMIZATION_IMPLEMENTED; NOT_MERGED.**
