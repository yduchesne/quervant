# PR 14G — final acceptance state

**Status: `NOT ACCEPTED`. PR 14 remains `IN PROGRESS`; v0.1 is `NOT RELEASED`.**

This document records the exact state at the end of PR 14G. No signature, approval
or merge authorization is claimed, and none has been supplied.

## 1. Gate states

| Gate | State | Basis |
|---|---|---|
| Phase A — CW-018, CW-058, CW-073 (remote query-time zero-GET) | **PASS** | `phase-a-zero-get.md`; fake (all GETs) and real pinned RustFS (budgeted GETs) positive controls + zero deltas + local-oracle parity; commit `e4d7237` |
| Phase B — CW-055, CW-068 (exact selected physical hit) | **PASS** | `phase-b-physical-identity.md`; physical-tuple oracle, old/new PIT witness, deleted/tie witness, `CorruptIndex` negative, key-latest discriminator; commit `d1ee42b` |
| 127-row crosswalk reconciliation | **RECONCILED** | `acceptance-crosswalk.md`; mechanical re-parse: 127 rows, 127 unique composite keys, CW `1..127`; totals `111 PASS / 11 SUPERSEDED / 2 N/A / 3 BLOCKED / 0 FAIL` |
| Workspace tests (stable + MSRV, default + all features) | **PASS** | `validation-report.md`; 2054 / 2058 passed, 0 failed |
| Coverage ≥ 85 % lines | **PASS** | `cargo llvm-cov … --fail-under-lines 85` → **91.37 %** |
| Formatting, Clippy (4 combinations), docs, benches, scripts, `git diff --check` | **PASS** | `validation-report.md` §2 |
| Real RustFS Phase A test | **PASS** | `real::a02_real_rustfs_zero_get_after_warmup`, digest `sha256:1803faef…b6a3c`, version `1.0.1` |
| Real PR 14 vertical/fault regression suites | **PASS** | 14 + 10 tests at this head |
| CW-041 (`X01–X13`) | **BLOCKED** | human decision required; `maintainer-decisions.md` §1 |
| CW-127 (`R-14A-JSON-MEM`) | **BLOCKED** | human risk closure required; `maintainer-decisions.md` §2 |
| CW-087 (final gates, CI, docs, acceptance) | **BLOCKED** | depends on both decisions, exact-head CI and independent review |
| Exact-head GitHub CI | **PENDING / BLOCKED** | no check run exists at the pushed head; `ci.yml` triggers only on `pull_request`/`push: main`, and PR creation requires valid credentials that are unavailable here |
| Independent review | **PENDING** | agent self-review is not independent review |
| PR 14F benchmark reuse | **VALID (X25)** | immutable merged PR #67 evidence; PR 14G changes no measured path and did not re-run trials |
| Maintainer acceptance / merge of PR 14G | **NOT GRANTED** | no authorization supplied; agent did not self-merge |

## 2. Row-level state (source of truth)

| Scope | Rows | State |
|---|---|---|
| Historical rows closed before PR 14G | 106 | `PASS` |
| Historical rows closed by PR 14F (immutable evidence) | 6 | `PASS` |
| Closed by PR 14G Phase A | 3 (018, 058, 073) | `PASS` |
| Closed by PR 14G Phase B | 2 (055, 068) | `PASS` |
| Total `PASS` | **111** | |
| `SUPERSEDED WITH EVIDENCE` | 11 | unchanged |
| `NOT APPLICABLE (APPROVED)` | 2 | unchanged (`W08` exception; never measured) |
| `BLOCKED` | **3** (`041`, `127`, `087`) | awaiting human decisions / final gates |
| `FAIL` | **0** | no executed gate failed |
| **Total** | **127** | |

## 3. What the implementer asserts (and what it does not)

**Asserted, with executed or immutable evidence:**

1. After a remote committed snapshot is opened and warmed, typed-only, mixed
   lexical+typed, three-slot serial batch (typed/mixed/aggregation) and pinned
   batch page 1→2 execution issue **zero additional remote GETs**, proven on a
   deterministic fake (all GETs) and a real pinned RustFS provider (budgeted
   GETs), with independent local-oracle parity for keys, ordering, fields,
   scores, aggregations and cursor pages.
2. Projection of a unified result uses the **selected physical**
   `(segment_index, doc_id)` and its own snapshot, not a logical-key rescan: the
   exact physical oracle matches, old/new PIT versions of one key are physically
   distinct with correct per-snapshot values, deletions do not leak, and a
   key/PHYSICAL mismatch raises `CorruptIndex`.
3. The 127-row crosswalk is preserved exactly, with only the transitions listed
   in `acceptance-crosswalk.md` §4 applied, each backed by named evidence.

**Not asserted:**

1. That PR 14 is accepted, merged or released; that v0.1 may start.
2. That `X01–X13` per-ID obligations are satisfied — they remain undefined and
   `BLOCKED`.
3. That the JSON memory risk is accepted — the correction is merged and
   characterized, but the human risk closure is absent.
4. That CI passes at the PR head; no check run exists and none is inferred from
   earlier heads.
5. That independent review occurred.

## 4. Required human actions (in order)

1. **One combined decision** (see `maintainer-decisions.md` §3):
   CW-041 → X-A / X-B / X-C; CW-127 → `ACCEPT RESIDUAL RISK FOR PR14 ONLY`
   (with the six required elements) or `REJECT / REQUIRE MORE CORRECTION`.
2. **Open the PR** `test/pr14g-final-acceptance` → `main` with a valid GitHub
   credential and observe `rust`, `msrv`, `rustfs` at the exact head. A docs-only
   commit after that observation requires re-verification.
3. **Independent review** of the changed files, negative tests and evidence.
4. **Maintainer acceptance** of PR 14 and, separately, merge authorization for
   PR 14G. PR 15 and v0.1 stay on hold until PR 14 is explicitly accepted.

## 5. Signatures

| Role | Name | Date (UTC) | Decision |
|---|---|---|---|
| Implementing agent | _automated execution_ | 2026-10-28 | completed A/B and prepared C evidence; no acceptance authority |
| Maintainer — CW-041 | **absent** | — | `BLOCKED` |
| Maintainer — CW-127 | **absent** | — | `BLOCKED` |
| Independent reviewer | **absent** | — | `PENDING` |
| Merge authorization | **absent** | — | `NOT GRANTED` |
