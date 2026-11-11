# PR 15I-D3-A decision register

Status: pre-measurement. The closed decision from §6.4 is applied only after a
qualified A/A control and two qualified paired campaigns.

## Pre-authorized decisions applied

| DXA | Trigger observed | Action | Evidence |
|---|---|---|---|
| DXA-01 | D2-A evidence commit is an ancestor of `origin/main`; `D2A_SCORE_COST_LOW_PRIORITY` present | Proceed | preflight |
| DXA-04 | Expected search-source blob SHAs and D2-A merge verified | Pin `409fb0f…` as BASE | preflight |
| DXA-06 | D2-A probe/tooling exists | Copy infrastructure into a new `pr15i_d3a` namespace only | source proof |
| DXA-11 | Absent/rare lanes have fewer than 512 candidates | Keep coarse timers, suppress candidate micro-timers | VT-11/VT-12 |
| DXA-19 | A/A control qualifies | Continue to paired campaign 01 without reconfirmation | pending |
| DXA-21 | Campaign 01 fully qualifies | Run campaign 02 without re-freezing | pending |
| DXA-23 | Named dominant candidate component qualifies in both campaigns | Record `LOCALIZED`/`INTERMEDIATE`; design review only | pending |
| DXA-28 | Evidence archive is on the same WSL virtual disk | Record `SAME_DISK_ONLY` | pending |

No HARD STOP condition has been observed. No threshold was changed after the
protocol was written. No failed or superseded attempt is hidden.

## Final decision

Pending measurement. The independent verifier writes the aggregate verdict; the
agent does not reinterpret it. Any outcome remains diagnostic and does not
authorize a D3-B implementation.
