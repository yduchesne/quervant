# PR 15H-D — six-lane unified binding-resolution controller

Controller for the PR 15H-D experiment: share the already resolved
schema/analyzer bindings and `CodecSchema` between cursor/fingerprint validation
and `unified_plan` compilation in the normal unified search path. Only
`search/unified.rs` and `search/unified_plan.rs` may change in production.

It is a mechanical port of the frozen PR15H-C controller. The six PR15D warm
lanes, corpus, adapter, oracle, warmups, samples, mirrored schedule and sealing
semantics are unchanged.

## Source identity

The measured A identity is the **D tooling commit itself** (`D_TOOLING_SHA`),
whose production `search/` files equal `C_CORRECTION_SHA` (the accepted C
rollback). The controller refuses a tooling commit that contains non-tooling
paths. Run it from a clean detached worktree at `D_TOOLING_SHA`.

## Frozen lanes (fixed order)

`pr15d_v1/100000/common/k100`, `100000/common/k10`, `100000/medium/k100`,
`10000/common/k100`, `100000/rare/k100`, `100000/absent/k100`.

## Statistic

For four paired deltas `d = A_median − B_median` (positive = D faster):

- **gating:** conventional even-n arithmetic median `0.5*(sorted(d)[1]+sorted(d)[2])`;
- **supplementary only:** lower median `sorted(d)[1]`.

## Frozen D gates

- At least two of D-P1/D-P2/D-P3 have conventional median `>= +2.000 ms` and at
  least 3/4 individual deltas `> 0`.
- Every remaining primary has conventional median `>= -0.750 ms` and no single
  delta `< -2.000 ms`.
- D-G1 conventional median `>= -0.750 ms`; D-G2/D-G3 `>= -0.250 ms`; no guard
  single delta `< -1.000 ms`.
- Any invalid oracle/corpus/index/host/provenance/contention makes the campaign
  invalid, never a pass or fail.

## Commands

```sh
ROOT=$(pwd -P)
python3 <pinned-tooling>/benchmarks/pr15h_d/run.py baseline \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-d/source-a" \
  --out "$ROOT/target/pr15h-d/baseline-01" --idle-confirmed
python3 <pinned-tooling>/benchmarks/pr15h_d/run.py baseline \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-d/source-a" \
  --out "$ROOT/target/pr15h-d/baseline-01" --verify-only

python3 <pinned-tooling>/benchmarks/pr15h_d/run.py paired \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-d/source-a" \
  --candidate-tree "$ROOT/target/pr15h-d/source-b" \
  --baseline "$ROOT/target/pr15h-d/baseline-01" \
  --out "$ROOT/target/pr15h-d/paired-01" --idle-confirmed
python3 <pinned-tooling>/benchmarks/pr15h_d/run.py paired \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-d/source-a" \
  --candidate-tree "$ROOT/target/pr15h-d/source-b" \
  --baseline "$ROOT/target/pr15h-d/baseline-01" \
  --out "$ROOT/target/pr15h-d/paired-01" --verify-only
```

## Tests

```sh
python3 -m py_compile benchmarks/pr15h_d/{run.py,test_run.py}
python3 -m unittest discover -s benchmarks/pr15h_d -p 'test_*.py' -v
```

The deterministic suite covers source/tooling identity (including pre-output
blocking), lane/schedule/sample validation, corpus/index/host/oracle/probe
identity, the D conventional-median and lower-median boundary cases, the
`pr-15h-d` source-scope allowlist, seal/report tamper and read-only
`--verify-only`.
