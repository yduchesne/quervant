# PR 14G — final acceptance state

**Status: `NOT ACCEPTED`. PR 14 remains `IN PROGRESS`; v0.1 is `NOT RELEASED`.**

This document records the exact state at the end of PR 14G. The two maintainer
decisions are recorded as an attributed transcription of PR #70 comment
`6458408816`; no merge authorization, independent review or PR 14 acceptance has
been supplied, and none is claimed.

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
| CW-041 (`X01–X13`) | **SUPERSEDED WITH EVIDENCE** | maintainer option **X-B** (family-level supersession), PR #70 comment `6458408816`, decision date `2026-10-27`; verbatim transcription in `maintainer-decisions.md` §0 |
| CW-127 (`R-14A-JSON-MEM`) | **PASS** | maintainer **`ACCEPT RESIDUAL RISK FOR PR14 ONLY`**, same comment/date; bounded scope, limits and mitigations transcribed in `maintainer-decisions.md` §0/§2.0 |
| CW-087 (final gates, CI, docs, acceptance) | **BLOCKED** | explicitly excluded from the decision authorization: needs current-head CI, independent acceptance review and explicit maintainer PR 14/merge authorization |
| Exact-head GitHub CI | **VERIFIED PER HEAD** | PR #70 is open, so pushes trigger CI; `rust`/`msrv`/`rustfs` are observed on the new exact head after each push (`validation-report.md` §6). No still-running or earlier-head job is claimed as a pass |
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
| Closed by the recorded decision | 1 (127) | `PASS` |
| Total `PASS` | **112** | |
| `SUPERSEDED WITH EVIDENCE` | **12** (includes `041` under X-B) | |
| `NOT APPLICABLE (APPROVED)` | 2 | unchanged (`W08` exception; never measured) |
| `BLOCKED` | **1** (`087`) | final gates, CI, independent review, acceptance/merge |
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
2. That `X01–X13` per-ID obligations are satisfied — the row is closed only at
   family level under X-B, and no per-ID definition or test exists.
3. That the JSON memory risk is eliminated — it is **accepted for PR 14 only**
   within the stated limits; the meter is not RSS or a physical cap.
4. That CI passes at any head by inference; only completed check-runs at the exact
   head count.
5. That independent review occurred.

## 4. Required human actions (in order)

1. ~~CW-041 / CW-127 decisions~~ — **done**: recorded from PR #70 comment
   `6458408816` (see `maintainer-decisions.md` §0).
2. **Observe CI at the exact PR #70 head**: `rust`, `msrv`, `rustfs` must be
   `completed/success` on that head. Any later docs-only commit requires
   re-verification.
3. **Independent review** of the changed files, negative tests and evidence (the
   agent's `adversarial-review.md` is not independent review).
4. **Maintainer acceptance** of PR 14 and, separately, merge authorization for
   PR 14G. PR 15 and v0.1 stay on hold until PR 14 is explicitly accepted.

## 5. Signatures

| Role | Name | Date (UTC) | Decision |
|---|---|---|---|
| Implementing agent | _automated execution_ | 2026-10-28 | completed A/B and prepared C evidence; no acceptance authority |
| Maintainer — CW-041 | `yduchesne` (attributed) | `2026-10-27` | option **X-B**; `SUPERSEDED WITH EVIDENCE` |
| Maintainer — CW-127 | `yduchesne` (attributed) | `2026-10-27` | **`ACCEPT RESIDUAL RISK FOR PR14 ONLY`**; `PASS` |
| Independent reviewer | **absent** | — | `PENDING` |
| CW-087 final acceptance | **absent** | — | `BLOCKED` |
| Merge authorization | **absent** | — | `NOT GRANTED` |
