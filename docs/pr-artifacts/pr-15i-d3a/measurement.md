# PR 15I-D3-A measurement

Status: `D3A_MEASUREMENT_BLOCKED`.

## Executed attempts

| Attempt | Kind | Slots | Timed samples | Warmups | Clear probes | Index builds | Result |
|---|---|---:|---:|---:|---:|---:|---|
| `d3a-base-aa-01` attempt 01 | A/A control | 16 | 2,880 | 720 | 32 | 2 | `NOT_QUALIFIED` |
| `d3a-base-aa-01` attempt 02 | A/A control | 0 | 0 | 0 | 0 | 0 | aborted (exclusive write) |
| `d3a-base-aa-01` attempt 03 | A/A control (single retry) | 16 | 2,880 | 720 | 32 | 2 | `NOT_QUALIFIED` |

No paired campaign is qualified under the current T0b freeze. The prior T0
series is preserved but excluded.

## Why no priority conclusion

DXA-17 permits one fresh complete A/A control after a single documented
transient. The retry also failed the same frozen per-block gate (on a different
low-hit lane). That is the HARD STOP condition: a second complete failure.
Without a qualified control, P02–P04 cannot be established and no candidate or
intermediate-materialization conclusion is valid.

The raw control slots remain available for a future authorized re-analysis, but
they are not a qualified attribution campaign.
