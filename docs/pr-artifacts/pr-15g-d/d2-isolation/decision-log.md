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
