# PR 15I-B — final execution status

**Status:** `15IB_CODEC_REJECTED_SAFE_ROLLBACK`

P0 and P1 passed. P2 implemented two source-locked STORED v2 candidates (LZ4 and
Zstd level 1) with a full validation certificate; both P3 campaigns were
independently verified and both are **ineligible** because the frozen
rare/medium warm-lane gate (`B-P06`) fails despite large storage savings.
Production was restored exactly to P0 (merged PR 15I-A code) in
`c5180a7012e678d6fa938c747b18990201621d11`.

| Phase | Status | Evidence |
|---|---|---|
| P0 PR 15I-A verifier requalification | PASS | `p0-15ia-qualification.md`; receipt `verification-15ib-p0-01.json`; seal unchanged `af7f6c1a…b2f`; 87 tests |
| P1 historical attribution | PASS (H-E3) | `historical-15g-e-attribution.md`; `target/pr15i-b/diagnose/run-01` |
| P1 codec pre-study | PASS (both eligible offline) | `codec-pre-study.md`; codec lab JSON |
| P2 STORED v2 + certificate | IMPLEMENTED, REJECTED | `format-v2.md`; candidate commits `bfdb9b0` / `b3fbde5` ancestry |
| P3 paired campaigns | COMPLETE, BOTH INELIGIBLE | `codec-selection.md`; seals `9adec5f3…` / `245fad6e…` |
| P4 correctness/RustFS acceptance | NOT REACHED (candidate rejected first) | rollback removed v2 tests; no claim |
| P5 final QA at rollback | PASS | `qa-and-review.md`; 92.74% coverage |
| Safe rollback | PASS | production diff vs P0 empty |

## Identities

| Item | Value |
|---|---|
| BASE | `691b6993d15f568617f9302cca0a4677bc50df3e` |
| P0_SHA | `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb` |
| P1_SHA | `178c000b7e0bbc44b9f4e439755a36aadbb7ec7f` |
| B_LZ4 (tooling tip) | `bfdb9b0d95de171c72be1de26e4501fc701df988` |
| B_ZSTD (tooling tip) | `b3fbde55596615e44d4aa4b11a0e0bbf4f107e5b` |
| Rollback / final code HEAD | `c5180a7012e678d6fa938c747b18990201621d11` |
| B_FINAL_SHA | none (rejected) |

## External status

`HOSTED_CI_PENDING`, `INDEPENDENT_REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`.
