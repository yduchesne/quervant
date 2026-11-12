# PR 15I-D3-A execution status

Status: `D3A_MEASUREMENT_BLOCKED`.

The A/A control failed twice under the frozen T0b tooling. Under DXA-17 the
first complete control may be retried exactly once; the second complete failure
is a HARD STOP. No paired campaign was run under T0b and no priority conclusion
is made.

## Identities

| Item | Value |
|---|---|
| BASE | `409fb0fdf370bb4d4dade5ea507c6fa4518b5220` |
| T0 (superseded) | `2576bbad088a7a16d1b84c4dc4a4b450e80b06e1` |
| T0b (current freeze) | `fd216580374cc0f30a9ca84b44f7b8a7cd760a08` |
| Derivative fingerprint | `62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60` |
| A binary | `31fa596e147b16e7aea87a66451b32902d152422490fc08c62c490a7af81a1cb` |
| Q/P binary | `22ca014125d1c404c782454616d4bf3fa6369ef78512d2092c03b8d0f6908101` |

## Blocking evidence

Both complete T0b controls preserved all 16 slots, 2,880 timed samples, 720
warmups and 32 clear contention probes. Both were classified
`D3A_CONTROL_NOT_QUALIFIED` by the independent verifier.

| Attempt | Failing gate | Lane | Block | Ratio | Bounds |
|---|---|---|---:|---:|---|
| 01 | `CONTROL_BLOCK_RATIO` | `pr15d_v1/10000/absent/k100` | 1 | 1.2963446475195823 | `[0.80, 1.25]` |
| 03 (single retry) | `CONTROL_BLOCK_RATIO` | `pr15d_v1/10000/rare/k100` | 3 | 1.3114080164439876 | `[0.80, 1.25]` |

In both attempts every other block/lane was inside the gate, the lower median
of four block ratios was inside `[0.85, 1.15]` (1.0495 and 1.0246), and no hard
outlier `[0.67, 1.50]` occurred. The failures are single-block outliers in the
low-hit 10K lanes. Attempt 02 aborted before any slot because a preserved build
directory caused an exclusive-write refusal; it contributed no measurements.

## Disposition

- No paired campaign was started under T0b (precondition: qualified control).
- The earlier T0 series (qualified control + one 24-slot campaign) is preserved
  under `target/pr15i-d3a/superseded/t0-2576bba/` and is **not** used for any
  conclusion. Its campaign was measured before the verifier stage-key repair.
- Failed controls are archived outside `target/` and indexed.
- `CI_PENDING`, `REVIEW_PENDING`, `PR_NOT_CREATED`.
- `RUSTFS_NOT_RUN_NOT_REQUIRED_FOR_D3A_ATTRIBUTION`.

## Smallest needed maintainer decision

Authorize either (a) an amended plan permitting a further complete A/A control
under a documented host-quiescence procedure, or (b) a new measurement design
for the low-hit 10K control lanes. Raising or reinterpreting the frozen
`[0.80, 1.25]` gate is not authorized by this plan and was not done.
