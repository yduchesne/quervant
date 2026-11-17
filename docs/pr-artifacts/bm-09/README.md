# BM-09 — real qualification facade: implementation evidence

Scope: `dev/bm09-real-qualification`, branched from verified `main` at
`a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b` (the BM-08 PR #109 merge).

## Disposition

**`BM09_IMPLEMENTATION_L1_L2_PASS_REAL_BLOCKED`.**

The official qualification facade is implemented, its deterministic and adversarial
test suites pass locally, and the pre-existing synthetic L1/L2 behaviour is
unchanged. **No real timed measurement was taken.** There is no independent G0
authorization, the historical D3-C T6 freeze receipt is absent on this host, and no
reviewer has approved an official outer mapping or parity matrix. Those gaps are
external, human-owned evidence; fabricating them is forbidden by the plan.

## What is implemented

| Module | Responsibility |
| --- | --- |
| `official/contracts.py` | Closed official-v1 records, scope predicates, exact gate/input/output/dependency sets, decision vocabulary |
| `official/protocols.py` | Two reviewed design templates outside the source roster; strict loader requiring an *independent* approved digest; G0 authorization validation and freeze construction; frozen-backend re-hash and schedule cross-check |
| `official/acquisition.py` | Typed invocation plan for the unmodified legacy backends (explicit argv, `shell=False`, sanitized env, template-approved timeout, no `--allow-contended`), lifecycle transitions, isolated-`HOME` probe, non-reuse of output paths |
| `official/controls.py` | Real `/proc/stat` readiness sampling over the existing capability provider and pure evaluator; exact-rational A/A window assessment for the 12x4 cross-engine control and the D3-C control |
| `official/admission.py` | Gate A: complete raw-series inventory before/after read, corpus/answer oracle checks, build/throughput/contention checks, original verifier invocation, original-verifier digest pin, series/admission index |
| `official/analysis.py` | Gate B: frozen per-family arithmetic (lower-middle medians, nearest-rank percentiles, exact ratios, dispersion/overlap), retained-key block retention with the frozen caps, official policy decisions |
| `official/verification.py` | Gate C: independent recomputation with its own primitives and oracle rebuild, RV-01…RV-10 registry, typed block when the required policy is underivable |
| `official/receipts.py` | Real/official `receipt.v1` builder, exact dependency-edge verification, 13-member snapshot / 14-member manifest algebra |
| `official/publication.py` | Gate E: official semantic validator on the shared exclusive publisher, post-publication re-open with externally pinned anchors, `REUSED_VERIFIED` |
| `official/coordinator.py` | G0 → A → B → C → D → E orchestration with no premature pass |
| `official/historical.py` | Read-only legacy byte-identity manifest, bounded archive audits, parity assessment that cannot pass without authentic archives and an independent reviewer |
| `official/report.py` | Sanitized report and the exact `v0.1-bench COMPLETE` predicate set |

Existing code changed in three places only: `SOURCE_DIRECTORIES` gained
`benchmarks/quervant_bench/official`, `qualification/publication.py` gained the
shared private byte-level publisher helper (public synthetic API unchanged), and the
controlled synthetic QA fixture chain was re-frozen once after the final Python
edit.

## Files

- `design-and-contracts.md` — preimplementation invariants O01–O22 and false-pass
  counterexamples.
- `frozen-protocols.md` — the two design templates and their approved digests.
- `acquisition-ledger.md` — decision-matrix rules applied and blockers found.
- `verification-report.md` — final report block, QA evidence and command results.
- `historical-equivalence-matrix.md` — required parity rows and their blocked state.
- `legacy-retirement-ledger.md` — per-path disposition (`retain_live`).
- `qa-and-attestation.md` — QA roster, coverage, RustFS and CI status.
