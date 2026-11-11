# PR 15I-D3-A-F protocol

Status: T0c frozen at `0f07c29c318982afaf4ce6790ce5272e8754aa11`.

## Frozen properties

- Schema: `pr15i-d3a-candidate-attribution-fixup-v2`
- BASE: `409fb0fdf370bb4d4dade5ea507c6fa4518b5220`
- Control 01: `d3af-base-aa-01`
- Control retry: `d3af-base-aa-02` (not used; control 01 qualified)
- Paired runs: `d3af-unbatched-01` … `d3af-unbatched-05`
- `series_min_consistent_runs = 4`
- Exempt control lanes: `pr15d_v1/10000/absent/k100`,
  `pr15d_v1/10000/rare/k100`; at most one soft outlier each.
- `max_completed_control_attempts = 2`
- `run_mad_warning_relative = 0.25` (report-only)
- Seven reported areas: document key, duplicate detection, sort extraction,
  heap compare/update, candidate materialization, match-set construction,
  scored-map/vector.

The source derivative fingerprint is
`62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60`; the
25-stage/15-counter recorder, six-path insertion inventory, lane order,
sampling formulas, schedules, absolute/share/dominance thresholds and index
sentinels are unchanged. `protocol_v1.json` and `tooling_manifest.json` remain
bit-identical historical artifacts.
