# PR 15G-D decision log

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| GD-D01 | Shared HEAD `ca065a2`, clean | Pinned D_BASE | `preflight.md` |
| GD-D05 | Umbrella PR #86 exists | Same branch/PR; no new branch | PR #86 |
| GD-D06 | C production files equal `97d7ce1` | Treated accepted B as baseline | `git diff --quiet` |
| GD-D09/D10 | P4 eligibility and one-term compiled leaf verified | Reused compiled proof | eligibility tests |
| GD-D15 | Dictionary lookup `None` on eligible segment | Charged existing empty-term work; skipped only that segment | D1 tests |
| GD-D16 | Entry exists but all postings dead | Normal decode path, no bypass | D1 tests |
| GD-D19 | Prior segment heap bytes | Existing ledger begin/finish | D1 budget tests |
| GD-D24 | P4 runtime guard exactly one term | D2 closure returns true for decoded live posting | D2 tests |
| GD-D28 | Test-only membership witness needed | `#[cfg(test)]` thread-local counter | D2 test |
| GD-D41 | Assume-idle authorization | Benchmark may pass `--idle-confirmed`; probes still required | performance reports |
