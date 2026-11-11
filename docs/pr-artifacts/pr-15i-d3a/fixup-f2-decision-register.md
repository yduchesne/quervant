# PR 15I-D3-A-F2 decision register

Status: `D3AF2_ATTRIBUTION_QUALIFIED`; priority
`D3A_CANDIDATE_HOTSPOT_LOCALIZED`.

| ID | Trigger | Action |
|---|---|---|
| F2D-01 | Branch/BASE clean and exact | Continued on existing branch |
| F2D-04 | T0c historical runs 01–03 exist | Preserved as context only |
| F2D-05 | T0c run04 unstable, run05 absent | Preserved; not relabeled |
| F2D-06 | v2 protocol fields exist | Copied with fixed v3 overrides |
| F2D-12 | Control 01 qualified | Archived; no control 02 |
| F2D-16/17 | Run 03 10K rare Q/A median 1.1838 | Marked only that lane `DIAGNOSTIC_PERTURBED`; continued series |
| F2D-27 | Run 03 global integrity valid | Sealed/verified/archived; continued |
| F2D-33 | Two primary lanes share `candidate_duplicate` in all five runs | `D3A_CANDIDATE_HOTSPOT_LOCALIZED` |
| F2D-38 | 10K rare lane not estimable/eligible in run 03 | Excluded from attribution; not zero |
| F2D-42 | Archives on WSL disk | `SAME_DISK_ONLY` |
| F2D-43 | RustFS unavailable | Not required for this local measurement |
| F2D-44 | GitHub CLI token invalid | Branch push via SSH; no fabricated PR |

No threshold was changed after T0d. No run was replaced, dropped or re-sealed.
The localized component is diagnostic only; no optimization is authorized.
