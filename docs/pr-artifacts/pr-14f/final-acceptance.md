# PR 14F — final acceptance gate

**Status: `BLOCKED — OPERATOR ATTESTATION REQUIRED`. PR 14F is NOT ACCEPTED.
PR 14 remains `IN PROGRESS / NOT ACCEPTED`. v0.1 is NOT RELEASED.**

## 1. Distinct gates (none entails another)

| Gate | State | Basis |
|---|---|---|
| Harness corrections implemented and source-locked | **PASS** | `162cbfea…`; `harness-corrections.md` |
| Local tests / fmt / clippy / docs / bench / scripts | **PASS** | `validation-report.md` §1 |
| Coverage ≥ 85% lines | **PASS** | 91.84% |
| Native Linux filesystem | **PASS** | ext4 root in WSL2 |
| Real provider image digest + health | **PASS (prequalification only)** | pinned digest `1803faef…6a3c`, health `1.0.1` |
| Operator idle attestation | **ABSENT** | not supplied by a human |
| `QUALIFIED BENCHMARK` (3 fresh trials) | **BLOCKED** | 0 of 3 |
| Validator PASS on fresh reports | **BLOCKED** | no reports |
| Strict auditor PASS on fresh reports | **BLOCKED** | no reports |
| Raw CSV durable archive | **BLOCKED** | no CSV |
| `FINAL-SHA CI PASS` (`rust`, `msrv`, `rustfs`) | **NOT RUN** | no PR; invalid `gh` token |
| `INDEPENDENT REVIEW COMPLETE` | **NOT DONE** | no reviewer |
| `PR MERGED` | **NO** | no PR, no merge authorization |
| `PR 14 ACCEPTED` | **NO** | benchmark and other PR 14 obligations remain open |
| `v0.1 RELEASED` | **NO** | not a release PR |

## 2. What is complete in this PR

- A source-locked, tested wrapper that consumes arguments deterministically,
  removes an inherited diagnostic variable from qualified child environments,
  records the source SHA, rejects dirty trees and missing provider env, runs a
  fresh live contention check per trial, fails closed on non-`clear`, writes
  reports under ignored `target/`, and passes the approved W08 exemption to the
  unchanged validator.
- A test-only `QUERVANT_P4_REPORT_DIR` destination that refuses to overwrite
  previous attempts, with no change to queries, timing or report shape.
- A standalone strict read-only auditor plus 25 negative/positive unit tests,
  and 15 appended wrapper-contract assertions in the existing shell harness.
- Baseline inventory, environment/provider prequalification and this evidence
  set.

## 3. What is explicitly not complete

- Three fresh qualified `pr14_p4_v1` trials, raw CSVs, per-lane p50/p95/p99,
  dispersion, trial/CSV/contention hashes and a durable raw archive.
- Validator and audit PASS on fresh data.
- Copies to `benchmarks/reports/pr14f-p4-<sha-prefix>-t{1,2,3}.json`.
- PR-head CI on the exact immutable SHA.
- Independent review and maintainer merge authorization.

## 4. Pending decisions / required human action

1. **Operator idle attestation.** A human must state that competing benchmark
   workloads are stopped and the host is sufficiently idle, then authorize
   `bash benchmarks/scripts/run-pr14-p4.sh --trials=3 --idle-confirmed`.
2. **Provider env.** Export the non-secret endpoint/region/bucket and disposable
   credentials locally (not committed).
3. **Corpus digest prose.** Approve or reject a future documentation correction
   that makes `pr14_p4_v1.md` match the implemented hasher. No change was made.
4. **Idle-confirmed truthiness.** Decide whether to schedule a separate,
   reviewed runner fix for `var(...).is_ok()` (not authorized in PR 14F).
5. **Raw archive location.** Name a durable external archive for the future CSV
   evidence.
6. **PR/CI.** Re-authenticate `gh` (or create the PR manually) and observe
   `rust`, `msrv` and `rustfs` on the exact immutable head SHA.
7. **Review/merge.** Require independent review and explicit maintainer merge
   authorization; no self-merge.

## 5. Evidence head vs source head

- Executable source: `162cbfea509d5f03df4bedb89a09d9be4cafb75e`.
- Evidence head: `76612ded952623b1b4dffc5fdace67780d2b4b17` (first documentation
  evidence commit). The executable diff between source and evidence heads is
  verified empty; later documentation-only commits may advance the PR head
  without changing measured inputs.

## 6. Signatures

No human acceptance signature, no reviewer signature, no merge authorization and
no release authorization are recorded. This file is an agent-authored status
report, not an acceptance.
