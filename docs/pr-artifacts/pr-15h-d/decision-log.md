# PR 15H-D — decision log

| ID | Trigger | Action | Evidence |
|---|---|---|---|
| C-03 | Frozen C contract explicitly prescribes lower median | Kept C gates; relabeled docs; added informational conventional medians | C corrigendum |
| C-07/C-08 | Copied “PR 15H-B” title | Preserved sealed bytes; added corrigendum/derived view | CORRIGENDUM |
| C-11 | C-only correction validated | Committed C separately before D | `d4b10c1` |
| D-01 | `main` unchanged | Continued on the C base | preflight |
| D-02 | C runner protocol inspected | Mechanical D port with literal mapping | D tooling |
| D-04 | D tooling tests pass; A source = C rollback | Committed D tooling; sealed baseline | `c802f96` |
| D-05 | Host idle, probes clear | Ran full campaigns | baseline/paired |
| D-10 | Exact duplicate resolution present; pure reuse viable | Implemented `compile_with_resolved` delegation | source |
| D-15 | Correctness passed; controller ready | Ran paired campaign | performance |
| D-17 | Qualified campaign missed D-P01 | Source-only rollback; preserved evidence | `2ac85c7` |
| D-18 | Rollback byte-identical to A | Verified with `git diff --quiet` | rollback-or-keep |
| D-22 | No push/PR | `CI_PENDING` | qa-and-ci |

No HARD STOP, invalid campaign, or gate change occurred.
