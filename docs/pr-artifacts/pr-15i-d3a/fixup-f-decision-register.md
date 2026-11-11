# PR 15I-D3-A-F decision register

Status: `D3A_MEASUREMENT_BLOCKED`.

| ID | Trigger | Action |
|---|---|---|
| FDX-01 | Correct branch, clean start | Continued on same branch |
| FDX-02 | HEAD is a docs-only descendant of BASE | Recorded and continued |
| FDX-04 | T0/T0b evidence exists | Preserved; v2 names only |
| FDX-06 | Exempt 10K absent one soft outlier | Tolerated and recorded |
| FDX-10 | Control 01 qualified | Archived; no control 02 |
| FDX-14 | Derivative fingerprint unchanged | Reused derivative |
| FDX-18 | Runs 01–03 independently `LOW_INTRUSION` | Archived and continued |
| FDX-19 | Run 04 paired A/A drift unqualified | HARD STOP; `D3A_MEASUREMENT_BLOCKED`; no run 05 |
| FDX-30 | Archives on WSL disk | `SAME_DISK_ONLY` |
| FDX-31 | RustFS unavailable | Not required for this local measurement |
| FDX-32 | GitHub auth invalid | Commit/push if SSH permits; no fabricated PR |

No threshold was changed after T0c. No failed run was discarded or re-sealed.
