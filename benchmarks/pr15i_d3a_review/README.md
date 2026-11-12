# PR 15I-D3-A-F2 independent-review replay harness

This directory is **review-only**. It is outside the frozen
`benchmarks/pr15i_d3a/` tooling directory and does not change the T0d manifest or
any official evidence.

The harness copies selected F2 campaigns into `target/pr15i-d3a/review/cases/`,
applies controlled tampering, reseals the copy, and invokes the frozen
independent verifier. It also recomputes the F2 dispersion flags and the
3/5-vs-4/5 shared-run decision from sealed summaries.

```sh
python3 benchmarks/pr15i_d3a_review/replay_matrix.py \
  --out target/pr15i-d3a/review/replay-matrix.json
```

The command exits 0 after writing the matrix. Each case records `PASS`,
`REJECTED` or `ACCEPTED` with the verifier status/error. Official archives and
the frozen tooling are never modified.
