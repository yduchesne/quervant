# PR 15I-D3-C — official A/A control result

Status: **MEASUREMENT_BLOCKED**. No campaign was run and no policy was derived.

- T4 tooling commit: `cb3f3c8313831bef0b49aa30ffea5f2e21c2b714`
- Source: `3ad6c5184fbe9c011abb731415a007e3f19d21de`
- Protocol: `c7a062f85ffc2b356612ea0b47e062cb7f59c23444164c438fd2a3d9f0404002`
- Control evidence: `target/pr15i-d3-c/official/d3c-base-aa-01`
- Verifier: `verification=PASS`, `measurement_status=MEASUREMENT_BLOCKED`
- Host readiness: `READY`, no failure codes
- Samples: 23,040 (16 slots × 72 lanes × 20)

The protocol sets `official_measurement_retries=0`. The single valid official
attempt was blocked by A/A drift and lane failures, so it must not be retried or
published:

- 17 drift violations; examples:
  - A block 2 `10000/absent/k1` within-block ratio 1.527 > 1.50
  - A block 2 `10000/rare/k100` 1.555 > 1.50
  - A block 2 `10000/medium/k256` 1.756 > 1.50
  - A block 2 `10000/medium/k512` 1.592 > 1.50
  - A block 2 `10000/medium/k1024` 1.712 > 1.50
  - A block 2 `100000/absent/k128` 1.503 > 1.50
- Failing A/A lanes include `10000/absent/k100` (0.799),
  `10000/rare/k1024` (0.839), and several `10000/medium` lanes.

The earlier control invocation that used an uncommitted mode-env fix is invalid
and is not counted as an official attempt. T4 remains frozen; acquisition is
stopped on a real stability failure rather than relaxing the frozen caps.
