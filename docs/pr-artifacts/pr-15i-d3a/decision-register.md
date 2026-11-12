# PR 15I-D3-A decision register

Final status: `D3A_MEASUREMENT_BLOCKED`.

## Applied decisions

| DXA | Trigger observed | Action | Evidence |
|---|---|---|---|
| DXA-01 | D2-A evidence ancestor and `D2A_SCORE_COST_LOW_PRIORITY` present | Proceed | preflight |
| DXA-04 | Expected search-source blobs and D2-A merge verified | Pin `409fb0f…` as BASE | preflight |
| DXA-06 | D2-A probe/tooling exists | New `pr15i_d3a` namespace only | source proof |
| DXA-11 | Absent/rare lanes have fewer than 512 candidates | Suppress candidate micro-timers | VT-11/VT-12 |
| DXA-16 | Verifier stage-key defect found before any qualified paired campaign | Verifier-only repair, new T0b freeze, full series restarted | T0b `fd21658…` |
| DXA-17 | First complete T0b control failed one per-block ratio; one fresh control allowed | Ran exactly one new complete control (attempt 03) | attempts 01/03 |
| DXA-17 | The single retry also failed one per-block ratio | HARD STOP; `D3A_MEASUREMENT_BLOCKED`; no campaign 01/02 | attempts 01/03 |
| DXA-20 | No qualified paired campaign attempt exists | Preserve evidence; no alternate threshold | archives |
| DXA-28 | Archive on WSL virtual disk | `SAME_DISK_ONLY` | sidecars |

## Not applied / not authorized

- No threshold was changed, reinterpreted or relaxed.
- No paired campaign was run without a qualified control.
- No attempt was dropped, repaired or re-sealed.
- The superseded T0 campaign was not used to bypass the T0b control failure.

## Final verdict

`D3A_MEASUREMENT_BLOCKED`. There is no candidate-hotspot or
intermediate-materialization priority conclusion. The smallest needed
maintainer decision is an amended host-quiescence/control procedure or a new
measurement design for the low-hit 10K control lanes.
