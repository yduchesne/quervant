# PR 14F — final acceptance gate

**Status: `BENCHMARK QUALIFIED — PASS`, but PR 14F is NOT ACCEPTED.**
Remaining gates: durable raw archive (**BLOCKED — DURABLE ARCHIVE DESTINATION
REQUIRED**), CI on the new archival head, independent review and merge
authorization. PR 14 remains **IN PROGRESS / NOT ACCEPTED**; v0.1 is **NOT
RELEASED**.

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
| Durable raw CSV archive | **BLOCKED** | no operator-designated external destination |
| Baseline-head CI at `4c94ba8` (`rust`, `msrv`, `rustfs`) | **PASS** | PR #67, Rust CI run 40424504536 |
| Archival-head CI at `bd1fed7` (`rust`, `msrv`, `rustfs`) | **PASS** | PR #67, Rust CI run 40441448948 |
| Final binding-head CI | **PENDING** | this documentation commit advances the head |
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

These results are tied to those immutable SHAs. The final binding commit in this
pass advances the head again and requires its own successful runs before any
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
- Baseline-head CI verified green at `4c94ba8`.
- Disclosed and preserved campaign-1 failure.

## 4. What is explicitly not complete

- A durable, operator-designated external archive destination for the package.
  **This is the remaining benchmark-evidence blocker.**
- CI on the new archival head.
- Independent review and explicit maintainer merge authorization.
- PR 14 acceptance and v0.1 release.

## 5. Pending decisions / required human action

1. **Durable archive destination.** Provide an approved path/URI and authorized
   upload mechanism for
   `target/pr14-p4/package/quervant-pr14f-p4-7df492023397-raw-evidence.tar.gz`.
   Do not create a bucket, cloud account, retention policy or credentials.
2. **New-head CI.** After this evidence commit is pushed, observe `rust`, `msrv`
   and `rustfs` on the new head. Do not reuse the `4c94ba8` result as final-head
   evidence.
3. **Review/merge.** Require independent human review and explicit maintainer
   merge authorization; no self-merge.
4. **Optional follow-ups (separate approval):** correct the corpus digest prose
   in `pr14_p4_v1.md`; review `QUERVANT_P4_IDLE_CONFIRMED` truthiness; add a
   manifest-hash invariant binding reports to CSVs.

## 6. Evidence head vs source head

- Executable source: `7df492023397a512e400b03865a989020eff1430`.
- Measurement evidence head (CI-verified): `4c94ba8823dac62d6397e65239db1094ce6dbfe1`.
- Archival evidence head (CI-verified): `bd1fed714c21adc5d2aeb3936db1e0b49aea3eac`.
- The executable diff between source and both evidence heads is empty. Final
  documentation binding commits may advance the branch head without changing
  measured inputs; they require their own CI run.

## 7. Signatures

No human acceptance signature, reviewer signature, merge authorization or
release authorization is recorded. This file is an agent-authored status
report, not an acceptance.
