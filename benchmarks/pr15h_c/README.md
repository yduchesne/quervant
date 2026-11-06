# PR 15H-C — six-lane Quervant-only performance controller

Controller for the PR 15H-C borrowed-document-key late-ownership optimization.
It is a mechanical adaptation of the verified PR15H-B controller; the frozen
PR15D/PR15E-B1 adapter, corpus, oracle, statistics and sealing helpers are
unchanged.

## Lineage / source pins

| Item | Value |
|---|---|
| Comparison baseline A | `e8744d3fe16ee858c7d587aaf3b10d393059b809` |
| Stage / phase | `15h-c` / `borrowed-document-key-late-ownership` |
| Tooling | recorded as `HC_TOOLING_SHA` in `docs/pr-artifacts/pr-15h-c/preflight.md` |

## Frozen six lanes (fixed order)

P1 `pr15d_v1/100000/common/k100`, P2 `100000/common/k10`,
P3 `100000/medium/k100`, G1 `10000/common/k100`,
G2 `100000/rare/k100`, G3 `100000/absent/k100`.

## Commands

```sh
ROOT=$(pwd -P)
python3 benchmarks/pr15h_c/run.py baseline \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-c/source-a" \
  --out "$ROOT/target/pr15h-c/baseline-01" --idle-confirmed
python3 benchmarks/pr15h_c/run.py baseline \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-c/source-a" \
  --out "$ROOT/target/pr15h-c/baseline-01" --verify-only

python3 benchmarks/pr15h_c/run.py paired \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-c/source-a" \
  --candidate-tree "$ROOT/target/pr15h-c/source-b" \
  --baseline "$ROOT/target/pr15h-c/baseline-01" \
  --out "$ROOT/target/pr15h-c/paired-01" --idle-confirmed
python3 benchmarks/pr15h_c/run.py paired \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-c/source-a" \
  --candidate-tree "$ROOT/target/pr15h-c/source-b" \
  --baseline "$ROOT/target/pr15h-c/baseline-01" \
  --out "$ROOT/target/pr15h-c/paired-01" --verify-only
```

## Frozen absolute gates (nanoseconds internally, ms in reports)

`d = A_median − B_median` (positive = C faster); median of four is the
nearest-rank lower median (`sorted(diffs)[1]`).

| Gate | Condition |
|---|---|
| HC-P01/P02 | median ≥ 2.000 ms, ≥3/4 blocks ≥ 1.000 ms, no block < −1.000 ms |
| HC-P03 | median > −2.000 ms, fewer than 3/4 blocks < −2.000 ms |
| HC-P04 | G1 median > −2.000 ms |
| HC-P05 | G2 and G3 each median > −1.000 ms |

`HC-P00` requires complete qualification (source/host/corpus/index/oracle/
schedule/probes/seals); `HC-P06` correctness; `HC-P07` sanitized reproducibility.

## Tests

```sh
python3 -m py_compile benchmarks/pr15h_c/run.py benchmarks/pr15h_c/test_run.py
python3 -m unittest discover -s benchmarks/pr15h_c -p 'test_*.py' -v
```

The suite covers the six-lane identity, mirrored schedule, samples/warmups,
tooling identity (including pre-output blocking), corpus/index/host/oracle,
contention, all C absolute gate boundaries, the actual `pr-15h-c` source-scope
prefix and forbidden paths, seal/report tamper and read-only `--verify-only`.
