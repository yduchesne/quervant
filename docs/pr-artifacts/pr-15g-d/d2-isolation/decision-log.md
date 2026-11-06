# D2-only decision log

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| DX-D01 | Shared HEAD exactly `f0039e1`, clean | Proceeded | preflight |
| DX-D03 | `main` is an included ancestor | Reused shared baseline | `git merge-base` |
| DX-D04 | A/D1/D2 available locally | No fetch needed | git rev-parse |
| DX-D05 | Historical D2 touches only two files | Extracted delta | file allowlist |
| DX-D07 | Worktree paths absent under ignored target | Created detached A/X | worktree logs |
| DX-D10 | Helper anchors and original D2 test verified | Constructed X | X `53e41df` |
| DX-D11 | Stable patch hashes differ despite identical added lines | **HARD STOP** | source-proof |
| DX-D16 | Original D2 differential test passes at X | Diagnostic only | 1 passed |
| DX-D53 | Qualification gate failed before timing | Kept shared source unchanged; no performance decision | this log |
| DX-D69 | No merge authorization | PR #86 left open | PR state |

## Human decision required

The plan's mandated helper cannot satisfy the plan's patch-ID gate because the
gate hashes hunk context and the historical test followed a D1-only test absent
from A. A maintainer must either:

1. authorize source identity by exact added-line equality and immediate
   parent/file/no-D1 proofs, allowing the test-context relocation; or
2. supply a revised candidate-construction/source-proof procedure.

Until then, no campaign or disposition is authorized.

## Amendment continuation

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| DX-D01 override | Shared HEAD was exactly `9968690`; diff from `f0039e1` was the five authorized docs | Accepted continuation | amendment record |
| DX-D11 superseded | Original patch-ID gate withdrawn by maintainer | Replaced with exact edit-sequence proof; no manual patch | `source-proof-amended.md` |
| DX-D12 | All exact-edit checks passed | Froze X `53e41df`, committed harness `e2009d2`, proceeded | `DX-SOURCE-ID: PASS` |
| DX-D34 | Literal schedule/lanes verified | Ran all 16 slots | raw manifest |
| DX-D38/40 | All probes clear, samples/oracle valid | Admitted slots | raw validation |
| DX-D46/47 | A 100K rare cross-block drift 1.2994 > 1.25 | **HARD STOP: BLOCKED_DRIFT**; no retry | performance-blocked |
| DX-D53 | Qualification gate failed | Kept shared D1+D2 source unchanged | diff audit |
| DX-D70 | 16-slot campaign cannot yield performance verdict | Reported blocked, no alternative design | this record |
