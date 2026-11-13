# PR 15I-D3-C v3 — execution status

Status: **SCOPED HARD STOP — official series invalid/stopped.**

- v3 protocol: `ccf6d6419090570bcfafae0cd36f72dfb179bd045d8aa87dd1dd6fda980a18cf`
- v3 code was not frozen as T6 before the official control was invoked (HS-07).
- A v3 control was nevertheless acquired with 69,120 samples, structurally
  verified (`ACQUIRED_VERIFIED`) and published to the v3 evidence root
  (`bb5cd3d0...`). It cannot be treated as a T6-frozen official result.
- Campaign 01 aborted before sample collection at readiness:
  `HOST_NOT_READY ['BUSY_EXCEEDED']`. Per the plan this is not a free retry;
  the official series stops. No campaign 02 and no policy were produced.
- Partial campaign-01 build/index/readiness evidence is preserved under
  `target/pr15i-d3-c/official-v3/d3c-v3-strategies-01`.
- v1/v2 evidence and T4/T5 remain untouched.

The v3 protocol/schedule generator and controller/verifier changes are
committed as work-in-progress but are **not** a frozen T6 and must not be used
for another official run until the freeze/QA sequence is completed.
