# PR 15I-D3-A-F2 lane qualification

Status: four runs fully qualified; run 03 is lane-scoped.

| Run | Global status | Ineligible lanes |
|---|---|---|
| `d3af2-unbatched-01` | `D3A_ATTRIBUTION_LOW_INTRUSION` | none |
| `d3af2-unbatched-02` | `D3A_ATTRIBUTION_LOW_INTRUSION` | none |
| `d3af2-unbatched-03` | `D3A_ATTRIBUTION_LANE_SCOPED` | `pr15d_v1/10000/rare/k100` — `DIAGNOSTIC_PERTURBED`, Q/A median `1.1838453145406709` > `1.15` |
| `d3af2-unbatched-04` | `D3A_ATTRIBUTION_LOW_INTRUSION` | none |
| `d3af2-unbatched-05` | `D3A_ATTRIBUTION_LOW_INTRUSION` | none |

All three primary lanes have `n=5` eligible runs. The 10K rare lane has `n=4`;
the excluded run is `d3af2-unbatched-03`, and its complete raw evidence remains
archived. No global source, oracle, index, binary, host or partition failure
occurred. The 10K rare lane is explicitly **not** a safe low-hit regression
guard for any future optimization.
