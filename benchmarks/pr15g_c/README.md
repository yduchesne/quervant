# PR 15G-C — fused sorted single-term stream benchmark

Quervant-only nine-lane A/B runner for the C fused sorted single-term path. It
measures the frozen PR15D adapter over the same nine warm lanes as prior phases:

| N | classes | K |
|---|---|---|
| 10K | absent, rare, medium, common | 100 |
| 100K | absent, rare, medium, common | 100 |
| 100K | common | 10 |

## Provenance

- Arm A is pinned to the shared-branch pre-C tip
  `018fdd768d0898d6709baeb8661998ee1a82947c`.
- Arm B must be a distinct committed descendant on the same shared branch.
- Frozen PR15D corpus/adapter/oracle and the B runner mechanics are reused.
- Three trials per arm, 5 warmups + 20 samples per lane/trial, exact oracle and
  identical corpus/index digests are required.
- GB/GC gates: both 100K common lanes (`K100`, `K10`) must be `B_FASTER`;
  100K medium must not be `A_FASTER`; the other six lanes must not be
  `A_FASTER`. Sign consistency only; no invented percentage threshold.

## Authorization

The operator instructed the agent to assume the host idle and authorized
`--idle-confirmed` for this campaign. Actual runner contention probes still
decide qualification; `busy`/`unknown` invalidates the affected trial/campaign.

```sh
python3 benchmarks/pr15g_c/run.py \
  --source-tree /ABS/CLEAN/WORKTREE \
  --out /ABS/CHECKOUT/target/pr15g-c/qualified-pair-01 \
  --idle-confirmed
```

`--out` must be strictly beneath `<checkout>/target/pr15g-c/`. Each invocation
creates an exclusive `runs/<source-sha>/<UTC-microsecond>/` directory and never
overwrites evidence. Raw samples/contention/setup stay under ignored
`target/pr15g-c/`; tracked summaries are sanitized.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15g_c -p 'test_*.py' -v
```

## Status

Implementation and correctness evidence is in `docs/pr-artifacts/pr-15g-c/`.
Performance and hosted-CI status are recorded only after actual execution.
