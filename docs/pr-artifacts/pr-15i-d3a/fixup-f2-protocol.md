# PR 15I-D3-A-F2 protocol

Status: T0d frozen at `2c74e40d87f319c548c1f485d9b0267208311743`.

- Schema: `pr15i-d3a-candidate-attribution-lane-scoped-v3`
- Measurement family: `D3AF2_FIVE_PAIRED_LANE_SCOPED`
- Control: `d3af2-base-aa-01`; retry `d3af2-base-aa-02` (not used)
- Paired runs: `d3af2-unbatched-01` … `d3af2-unbatched-05`
- Lane-scoped statistics: minimum 4 eligible runs, lower median/MAD,
  whole-lane-run exclusion, global non-timing failures still block the campaign.
- Numeric gates, 25 stages, 15 counters, FIRST/STEADY sampling, derivative
  fingerprint `62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60`
  and all historical v1/v2/T0c artifacts are unchanged.

The v3 diff from v2 is exactly 13 keys, mechanically tested by
`test_v3_diff_is_exactly_thirteen_keys`.
