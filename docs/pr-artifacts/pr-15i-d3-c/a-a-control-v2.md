# PR 15I-D3-C — protocol v2 official A/A control

Status: **MEASUREMENT_BLOCKED**. No campaign was run and no policy was derived.

- T5 tooling commit: `1bdbef8984461de7ddc6c8fd30a1960e6accf140`
- Source: `3ad6c5184fbe9c011abb731415a007e3f19d21de`
- Protocol v2 SHA: `55255c687ccfa65f8cffe3169cca6f01880584f30e3c7f29843489bedc42a5c5`
- Evidence: `target/pr15i-d3-c/official-v2/d3c-v2-base-aa-01`
- Verifier: structural `PASS`; `measurement_status=MEASUREMENT_BLOCKED`
- Host: adapter CPU 0 / controller CPU 2, same package, distinct physical
  cores; readiness `READY`, no failure codes; 23,040 samples.
- Retries: `0`; no retry or campaign was attempted.

Six drift violations remain, with block 3 now dominant:

- A block 3 `100000/absent/k512` within 1.732 > 1.50
- A block 3 `100000/rare/k64` within 1.524 > 1.50
- A block 3 `100000/medium/k64` within 1.372 > 1.25
- A block 3 `100000/medium/k128` within 1.298 > 1.25
- A block 3 `100000/medium/k512` within 1.564 > 1.25
- A between-block `100000/medium/k512` 1.278 > 1.25

The 13-lane diagnostic had been stable on the same physical-core pair, so the
topology change alone does not stabilize the full 72-lane four-block run. The
v2 official series stops here under HS-08. The v1 control and T4 remain
immutable; v2 evidence is preserved and must not be published because its
status is not CONTROL_QUALIFIED.
