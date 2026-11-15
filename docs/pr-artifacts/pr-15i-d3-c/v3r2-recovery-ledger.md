# PR 15I-D3-C — v3-R2 recovery ledger

Status: **SCOPED HARD STOP — campaign 01 independent verification failed.**

- T6-R2 commit: `8d070ec1e46c13bbb857dc6b4e9d26bf682b7162`
- Receipt SHA-256: `321f372f11b9e50769c52499e8ec21044cf3b7eb9cb70951003a84467ac47e94`
- Protocol v3-R2 SHA-256: `1623cd8081d67a911776105c9a4bf1c9b8506903a737a01b7bccf4e3e1fd3715`
- Readiness-only: `READY` (CPU0/CPU2).
- Control `d3c-v3r2-base-aa-01`: 69,120 samples; verification PASS;
  `ACQUIRED_VERIFIED`; archive
  `3419007a74688abe3379599eba4e7e015728a7603e892c88a3d6f4f84d9a8bb6`, published.
- Campaign 01 `d3c-v3r2-strategies-01`: 138,240 samples; controller
  `ACQUIRED_VERIFIED`; independent verifier `FAIL: V_SUMMARY`.
- Campaign 02 and policy: not run.

## Root cause

The controller's `summary_campaign` omits the `timing_observation` key while
the independent verifier's `summary_campaign` includes it. The verifier's
canonical summary comparison therefore fails on a non-measurement diagnostic
field. The per-corpus index structural defect was fixed and campaign 01 now
reaches `ACQUIRED_VERIFIED`; this remaining summary-contract mismatch is a
frozen T6-R2 tooling defect.

No raw samples, archives, or existing evidence may be edited to bridge the
difference. The campaign cannot be retried or published under this freeze.

## Decision required

Authorize a T6-R3 correction aligning the controller/verifier summary schema
and a fresh replacement series, or accept the stop. No campaign 02, series
verification, nine-K policy, or study completion is claimed.
