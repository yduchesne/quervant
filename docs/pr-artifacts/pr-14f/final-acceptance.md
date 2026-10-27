# PR 14F — final acceptance gate

**Status: `BENCHMARK QUALIFIED — PASS`, but PR 14F is NOT ACCEPTED.**
Remaining gates: CI on the current binding head, independent review and merge
authorization. The durable raw archive is established (operator-attested
Google Drive upload). PR 14 remains **IN PROGRESS / NOT ACCEPTED**; v0.1 is
**NOT RELEASED**.

## 1. Distinct gates (none entails another)

| Gate | State | Basis |
|---|---|---|
| Harness corrections implemented and source-locked | **PASS** | `harness-corrections.md`; source `7df492023397…` |
| Local tests / fmt / clippy / docs / bench / scripts | **PASS** | `validation-report.md` |
| Coverage ≥ 85% lines | **PASS** | 91.84% |
| Native Linux filesystem | **PASS** | ext4 root in WSL2 |
| Real provider image digest + health | **PASS** | pinned `1803faef…6a3c`, health `1.0.1` |
| Operator authorization / idle attestation | **PASS (timing disclosed)** | `qualification-attempts.md` §1 |
| Three independent qualified trials | **PASS** | t1/t2/t3 at `7df4920…`; all `qualified=true` |
| Correctness oracle before timing | **PASS** | every trial |
| Live contention `clear` per trial | **PASS** | 0.003331 / 0.004990 / 0.003744; competing 0 |
| `validate-pr14-p4.py --w08-exemption` | **PASS** | 3 qualified trials |
| `audit-pr14f-trials.py` | **PASS** | `PASS PR14F audit` |
| W08 | **NOT APPLICABLE (APPROVED)** | never measured |
| Raw evidence local package | **VERIFIED** | deterministic `tar.gz`; `PACKAGE-SHA256SUMS` and `original-archive/SHA256SUMS` verify |
| Durable raw CSV archive | **PASS (operator-attested)** | Google Drive `1nt02UI8…`; declared SHA-256 matches local package |
| Baseline-head CI at `4c94ba8` (`rust`, `msrv`, `rustfs`) | **PASS** | PR #67, Rust CI run 40424504536 |
| Archival-head CI at `bd1fed7` (`rust`, `msrv`, `rustfs`) | **PASS** | PR #67, Rust CI run 40441448948 |
| Previous final-binding-head CI at `8887541` | **PASS** | PR #67, Rust CI run 40443185707 |
| Current binding-head CI | **PENDING** | this documentation commit advances the head |
| `INDEPENDENT REVIEW COMPLETE` | **NOT DONE** | agent self-review only |
| `PR MERGED` | **NO** | no merge authorization |
| `PR 14 ACCEPTED` | **NO** | other PR 14 obligations remain open |
| `v0.1 RELEASED` | **NO** | not a release PR |

## 2. CI evidence (immutable references)

PR #67: `https://github.com/yduchesne/quervant/pull/67`, state `open`, base
`main` `7b1b84be…`, head `4c94ba8823dac62d6397e65239db1094ce6dbfe1`.

Baseline head `4c94ba8`, workflow run **40424504536** (`Rust CI`, run 230):

| Check | Conclusion | Job |
|---|---|---|
| `rust` | success | `121926791174` |
| `msrv` | success | `121926791153` |
| `rustfs` | success | `121926790941` |

Archival head `bd1fed7`, workflow run **40441448948** (`Rust CI`, run 231):

| Check | Conclusion | Job |
|---|---|---|
| `rust` | success | `121982517900` |
| `msrv` | success | `121982518147` |
| `rustfs` | success | `121982518130` |

Previous final binding head `8887541`, workflow run **40443185707** (`Rust CI`,
run 233):

| Check | Conclusion | Job |
|---|---|---|
| `rust` | success | `121988108430` |
| `msrv` | success | `121988108673` |
| `rustfs` | success | `121988108696` |

These results are tied to those immutable SHAs. The current documentation commit
advances the head again and requires its own successful runs before any
final-head CI claim.

## 3. What is complete

- Deterministic qualified wrapper with absolute report/qualification paths,
  source-SHA capture, dirty-tree and provider-env gates, `env -u` removal of the
  inherited diagnostic variable, per-trial live contention with fail-closed
  `clear`, ignored `target/` report redirection, `create_new` no-overwrite, and
  the approved W08 exemption passed to the unchanged validator.
- Strict read-only trial auditor plus 25 unit tests, and 58 shell-harness tests.
- Three fresh qualified `pr14_p4_v1` trials at `7df4920…`, 20 samples × 14 lanes
  each, validator PASS and auditor PASS.
- Per-lane p50/p95/p99 and dispersion derived from raw CSV.
- Deterministic, self-verifying raw-evidence package
  `quervant-pr14f-p4-7df492023397-raw-evidence.tar.gz`, SHA-256
  `6cef9c713012c9040391b7a57c82027295781dcf2b42228f7912f2c5578fe66d`, 15,491
  bytes, 21 members; rebuild byte-identical.
- Durable Google Drive upload by the maintainer with a matching declared
  SHA-256; agent re-download blocked by Google authentication (operator-attested
  remote integrity).
- CI verified green at `4c94ba8`, `bd1fed7` and `8887541`.
- Disclosed and preserved campaign-1 failure.

## 4. What is explicitly not complete

- CI on the current binding head.
- Independent review and explicit maintainer merge authorization.
- PR 14 acceptance and v0.1 release.

## 5. Pending decisions / required human action

1. **Current-head CI.** After this evidence commit is pushed, observe `rust`,
   `msrv` and `rustfs` on the new head. Do not reuse earlier results.
2. **Review/merge.** Require independent human review and explicit maintainer
   merge authorization; no self-merge.
3. **Optional follow-ups (separate approval):** correct the corpus digest prose
   in `pr14_p4_v1.md`; review `QUERVANT_P4_IDLE_CONFIRMED` truthiness; add a
   manifest-hash invariant binding reports to CSVs; independently re-download
   the Google Drive object when credentials are available.

## 6. Evidence head vs source head

- Executable source: `7df492023397a512e400b03865a989020eff1430`.
- Measurement evidence head (CI-verified): `4c94ba8823dac62d6397e65239db1094ce6dbfe1`.
- Archival evidence head (CI-verified): `bd1fed714c21adc5d2aeb3936db1e0b49aea3eac`.
- Previous final binding head (CI-verified): `888754131add34cad914596c466503aa68a11325`.
- The executable diff between source and these evidence heads is empty. Current
  documentation binding commits may advance the branch head without changing
  measured inputs; they require their own CI run.

## 7. Signatures

No human acceptance signature, reviewer signature, merge authorization or
release authorization is recorded. This file is an agent-authored status
report, not an acceptance.

## 8. SR-14F-01 fixup status — 2026-10-27

| Item | State |
|---|---|
| SR-14F-01 source correction | **CORRECTED** — source lock `8cfd2fce436ea99d57d2699471ab49d2cd1a3446` |
| Preflight gates (stable/MSRV/tests/coverage/docs/scripts) | **PASS** — 91.84% lines |
| New qualified campaign | **BLOCKED — NEW OPERATOR ATTESTATION REQUIRED** |
| New reports/raw/package/durable archive | **NOT CREATED** |
| Final fixup-head CI | **PENDING** |
| Independent review / merge authorization | **NOT DONE / NOT GRANTED** |
| PR 14 overall | **IN PROGRESS / NOT ACCEPTED** |
| v0.1 | **NOT RELEASED** |

The previous campaign at `7df4920…` and its Google Drive archive remain
historical evidence only. They do not satisfy the SR-14F-01 campaign
requirement.

## 9. SR-14F-01 second source lock — 2026-10-27

| Item | State |
|---|---|
| SR-14F-01 source correction | **CORRECTED** — source lock `d12a97537a5131953c948c3a90065a73c3d24b40` |
| First corrected lock `8cfd2fc` | **SUPERSEDED** — t1 oracle snapshot failure, preserved unqualified |
| Preflight gates at `d12a975` | **PASS** — 2,044/2,048 tests, 91.84% lines |
| New qualified campaign | **BLOCKED — NEW OPERATOR ATTESTATION REQUIRED** |
| New reports/raw/package/durable archive | **NOT CREATED** |
| Final fixup-head CI | **PENDING** |
| Independent review / merge authorization | **NOT DONE / NOT GRANTED** |
| PR 14 overall | **IN PROGRESS / NOT ACCEPTED** |
| v0.1 | **NOT RELEASED** |

The `7df4920…` campaign and its Google Drive archive remain historical only. The
`8cfd2fc` t1 failure is preserved and is not acceptance evidence.
