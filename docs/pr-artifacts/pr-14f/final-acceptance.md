# PR 14F — final acceptance gate

**Status: `QUALIFIED BENCHMARK — PASS`, but PR 14F is NOT ACCEPTED.**
Remaining gates: durable raw archive (**RAW ARCHIVE BLOCKED**), final-head CI,
independent review and merge authorization. PR 14 remains **IN PROGRESS / NOT
ACCEPTED**; v0.1 is **NOT RELEASED**.

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
| Durable raw CSV archive | **BLOCKED** | staged under ignored `target/`; no external archive |
| `FINAL-SHA CI PASS` (`rust`, `msrv`, `rustfs`) | **NOT RUN** | no PR; invalid `gh` token |
| `INDEPENDENT REVIEW COMPLETE` | **NOT DONE** | no reviewer |
| `PR MERGED` | **NO** | no merge authorization |
| `PR 14 ACCEPTED` | **NO** | other PR 14 obligations remain open |
| `v0.1 RELEASED` | **NO** | not a release PR |

## 2. What is complete in this PR

- Deterministic qualified wrapper with absolute report/qualification paths,
  source-SHA capture, dirty-tree and provider-env gates, `env -u` removal of the
  inherited diagnostic variable, per-trial live contention with fail-closed
  `clear`, ignored `target/` report redirection, `create_new` no-overwrite, and
  the approved W08 exemption passed to the unchanged validator.
- Strict read-only trial auditor plus 25 negative/positive unit tests, and 58
  shell-harness tests including absolute-path assertions.
- Three fresh qualified `pr14_p4_v1` trials at `7df4920…`, 20 samples × 14 lane
  pairs each, with validator PASS and auditor PASS.
- Per-lane p50/p95/p99 and dispersion derived directly from raw CSV in
  `benchmark-report.md`.
- Preserved/hashed raw staging and disclosed campaign-1 failure.

## 3. What is explicitly not complete

- A durable, operator-designated external archive of the raw CSVs. **This is the
  remaining benchmark-evidence blocker.**
- Final-head CI on the immutable PR head.
- Independent review and explicit maintainer merge authorization.
- PR 14 acceptance and v0.1 release.

## 4. Pending decisions / required human action

1. **Durable archive.** Designate an external archive path/URI for
   `target/pr14-p4/archive/7df492023397…/` and record its locator plus hashes.
   Until then, no fully reproducible acceptance claim.
2. **PR/CI.** Re-authenticate `gh` or create the PR manually; observe `rust`,
   `msrv` and `rustfs` on the exact immutable head.
3. **Review/merge.** Require independent review and explicit maintainer merge
   authorization; no self-merge.
4. **Optional follow-ups (separate approval):** correct the corpus digest prose
   in `pr14_p4_v1.md`; review the `QUERVANT_P4_IDLE_CONFIRMED` truthiness; add a
   manifest-hash invariant check binding reports to CSVs.

## 5. Evidence head vs source head

- Executable source: `7df492023397a512e400b03865a989020eff1430`.
- Evidence head: the publication commit(s) after source lock. The executable
  diff between source and evidence heads is verified empty; documentation and
  the tracked sanitized reports may advance the head without changing measured
  inputs.

## 6. Signatures

No human acceptance signature, reviewer signature, merge authorization or
release authorization is recorded. This file is an agent-authored status
report, not an acceptance.
