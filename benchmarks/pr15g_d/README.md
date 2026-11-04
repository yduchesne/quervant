# PR 15G-D — compiled exact-term specialization benchmark

Quervant-only nine-lane A/B runner for the D experiments.

- Arm A is pinned to D_BASE `ca065a212987284144d8901aa5c54de093d6dbfc`.
- `--experiment d1` gates on 100K absent/K100 `B_FASTER` and no other lane
  `A_FASTER` (verified dictionary-miss segment bypass).
- `--experiment d2` gates on 100K medium/K100 or common/K100 `B_FASTER`, with
  no other lane `A_FASTER` (direct positive-membership predicate).
- Nine frozen PR15D lanes, 3 trials/arm, 5 warmups + 20 samples, exact oracle,
  identical corpus/index digests and clear contention probes are required.
- Verdicts use strict sign consistency only; no percentage threshold or
  aggregate substitution.

## Authorization

The operator has instructed the agent to assume the benchmark host is idle and
authorized `--idle-confirmed` without further permission. Actual runner probes
still decide qualification; `busy`/`unknown` invalidates the campaign.

```sh
python3 benchmarks/pr15g_d/run.py \
  --experiment d1 \
  --source-tree /ABS/CLEAN/WORKTREE \
  --out /ABS/CHECKOUT/target/pr15g-d/d1-... \
  --idle-confirmed
```

`--out` must be strictly below `<checkout>/target/pr15g-d/`; each run directory
is exclusive and immutable. Raw evidence stays ignored; tracked comparisons are
sanitized.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15g_d -p 'test_*.py' -v
```

## Status

Evidence is under `docs/pr-artifacts/pr-15g-d/`. C remains rejected; D1 and D2
have independent performance gates.
