# PR 15H-B — six-lane Quervant-only performance controller

Controller for the PR 15H-B borrowed-keyword late-sort-materialization
optimization. It measures only the six frozen warm PR15D lanes, reuses the
frozen PR15D/PR15E-B1 adapter, corpus, oracle and statistics, and applies the
frozen **absolute millisecond** acceptance gates.

## Lineage and source pins

| Item | Value |
|---|---|
| Baseline source (A) | `6e47eed3f35a5fad8db6dab24c66f386567e95c0` (accepted `ddcbe778` search) |
| Stage / phase | `15h-b` / `borrowed-keyword-late-sort-materialization` |
| Tooling commit | recorded as `HB_TOOLING_SHA` in `docs/pr-artifacts/pr-15h-b/preflight.md` |

## Frozen six lanes (fixed order)

| Role | Lane |
|---|---|
| P1 | `pr15d_v1/100000/common/k100` |
| P2 | `pr15d_v1/100000/common/k10` |
| P3 | `pr15d_v1/100000/medium/k100` |
| G1 | `pr15d_v1/10000/common/k100` |
| G2 | `pr15d_v1/100000/rare/k100` |
| G3 | `pr15d_v1/100000/absent/k100` |

## Commands

```sh
ROOT=$(pwd -P)
python3 benchmarks/pr15h_b/run.py baseline \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-b/source-a" \
  --out "$ROOT/target/pr15h-b/baseline-01" --idle-confirmed
python3 benchmarks/pr15h_b/run.py baseline \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-b/source-a" \
  --out "$ROOT/target/pr15h-b/baseline-01" --verify-only

python3 benchmarks/pr15h_b/run.py paired \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-b/source-a" \
  --candidate-tree "$ROOT/target/pr15h-b/source-b" \
  --baseline "$ROOT/target/pr15h-b/baseline-01" \
  --out "$ROOT/target/pr15h-b/paired-01" --idle-confirmed
python3 benchmarks/pr15h_b/run.py paired \
  --checkout-root "$ROOT" --base-tree "$ROOT/target/pr15h-b/source-a" \
  --candidate-tree "$ROOT/target/pr15h-b/source-b" \
  --baseline "$ROOT/target/pr15h-b/baseline-01" \
  --out "$ROOT/target/pr15h-b/paired-01" --verify-only
```

The one-time confirmation exception is expressed with
`--confirmation-of <prior paired campaign>` on a fresh `paired` output
directory; it is used only when the first campaign reports
`CONFIRMATION_REQUIRED`.

## Frozen gates (absolute, integer nanoseconds internally)

For each lane and block, `d = A_median − B_median` (positive = B faster). The
median of four is the nearest-rank lower median (rank 2 of sorted 4).

| Gate | Condition |
|---|---|
| P1/P2 | median ≥ 5.000 ms, at least 3/4 `d ≥ 2.000 ms`, no `d < −3.000 ms` |
| P3 | median > −3.000 ms and fewer than 3/4 blocks `< −3.000 ms` |
| G1 | median > −2.000 ms |
| G2/G3 | each median > −1.000 ms |

`HB-P00` requires the complete 8-slot, 960-sample campaign with clear probes,
matching host/corpus/index and oracle. `HB-P06` requires correct oracle results
and byte-identical query-only indexes; `HB-P07` requires sanitized reports.
A blocked campaign never produces an acceptance verdict.

## Tests

```sh
python3 -m py_compile benchmarks/pr15h_b/run.py benchmarks/pr15h_b/test_run.py
python3 -m unittest discover -s benchmarks/pr15h_b -p 'test_*.py' -v
```

The deterministic suite covers lane identity/order, path/native-filesystem
confinement, schedule integrity, sample/summary/oracle validation, all absolute
gate boundaries, blocked-vs-accepted behavior, seal/report tamper and
verify-only, source allowlist and sanitization. No live timing is performed.
