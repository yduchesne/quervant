# PR 15H-A2 targeted benchmark controller

Quervant-only measurement controller for PR 15H-A2 (cardinality-gated linear
single-term candidate staging). It is a byte-derived copy of the proven
`benchmarks/pr15h_a` controller with only stage identity and source-allowlist
changes. All corpus, adapter, oracle, lane, schedule, statistical, sealing and
privacy semantics are inherited unchanged.

## Lineage

| Item | Value |
|---|---|
| Copied from | `benchmarks/pr15h_a/{run.py,test_run.py}` at `7a136f7` |
| A2 base source | `7a136f7f299c2f460401b9d92dcef37d219ea98c` (accepted search == `ddcbe778`) |
| Stage identity | `15h-a2` |
| Phase | `cardinality-gated-linear-single-term-candidates` |
| Frozen dispatch threshold | `H_A2_MIN_POSTINGS = 8_192` (defined in production source) |

The controller deliberately does **not** hardcode a baseline SHA; the sealed
baseline manifest records the A2 base source, and `paired` requires the supplied
`--base-tree` to equal it.

## Frozen lanes (fixed order)

| Role | Lane |
|---|---|
| P1 | `pr15d_v1/100000/medium/k100` |
| P2 | `pr15d_v1/100000/common/k100` |
| P3 | `pr15d_v1/100000/common/k10` |
| G1 | `pr15d_v1/10000/common/k100` |
| G2 | `pr15d_v1/10000/rare/k100` |
| G3 | `pr15d_v1/100000/rare/k100` |
| G4 | `pr15d_v1/100000/absent/k100` |

No lane may be added, dropped or reordered. No process-cold lane and no
Tantivy/Lucene timing is part of this controller.

## Baseline (must precede production Rust edits)

```sh
cd /ABS/A2_TOOLING_CHECKOUT
python3 benchmarks/pr15h_a2/run.py baseline \
  --checkout-root /ABS/A2_TOOLING_CHECKOUT \
  --base-tree /ABS/A2_BASE_WORKTREE \
  --out /ABS/A2_TOOLING_CHECKOUT/target/pr15h-a2/baseline-01 \
  --idle-confirmed

python3 benchmarks/pr15h_a2/run.py baseline \
  --checkout-root /ABS/A2_TOOLING_CHECKOUT \
  --base-tree /ABS/A2_BASE_WORKTREE \
  --out /ABS/A2_TOOLING_CHECKOUT/target/pr15h-a2/baseline-01 \
  --verify-only
```

3 trials x 5 warmups + 20 timed samples x 7 lanes = 420 samples, 105 warmups and
6 real clear before/after contention probes. The campaign is sealed before any
production edit.

## Paired (after a committed, correctness-passing candidate)

```sh
cd /ABS/A2_TOOLING_CHECKOUT
python3 benchmarks/pr15h_a2/run.py paired \
  --checkout-root /ABS/A2_TOOLING_CHECKOUT \
  --base-tree /ABS/A2_BASE_WORKTREE \
  --candidate-tree /ABS/A2_CANDIDATE_WORKTREE \
  --baseline /ABS/A2_TOOLING_CHECKOUT/target/pr15h-a2/baseline-01 \
  --out /ABS/A2_TOOLING_CHECKOUT/target/pr15h-a2/paired-01 \
  --idle-confirmed

python3 benchmarks/pr15h_a2/run.py paired \
  --checkout-root /ABS/A2_TOOLING_CHECKOUT \
  --base-tree /ABS/A2_BASE_WORKTREE \
  --candidate-tree /ABS/A2_CANDIDATE_WORKTREE \
  --baseline /ABS/A2_TOOLING_CHECKOUT/target/pr15h-a2/baseline-01 \
  --out /ABS/A2_TOOLING_CHECKOUT/target/pr15h-a2/paired-01 \
  --verify-only
```

Four mirrored blocks `A,B | B,A | B,A | A,B` = 8 slots, 56 lane records, 1,120
timed samples, 280 warmups, 16 clear probes and 56 oracle validations.

## Frozen decision

- `B_FASTER` iff all four `B/A` ratios `< 1.0`; `A_FASTER` iff all four `> 1.0`;
  otherwise `INCONCLUSIVE` (equality included).
- `HA2-P01`/`HA2-P02`: 100K common K100/K10 must be `B_FASTER`.
- `HA2-P03`: 100K medium K100 must not be `A_FASTER`.
- `HA2-P04`: no guard G1–G4 may be `A_FASTER`.
- Drift caps: `max/min <= 1.25` for 100K and `<= 1.50` for 10K, both
  cross-session and within-arm. Exactly at the cap passes; above blocks.
- `HA2-P00`/`HA2-P05`/`HA2-P06` gate completeness, oracle/index identity and
  source scope/sanitization/verify-only.

## Source allowlist

Only `benchmarks/pr15h_a2/`, `docs/pr-artifacts/pr-15h-a2/`,
`crates/quervant-core/src/search/{execute,unified}.rs`,
`crates/quervant-core/tests/pr15h_a2_dispatch.rs`, `docs/BENCHMARKING.md` and
`docs/PERF_OPTIMIZATION_PLAN.md` are new-modifiable paths. The historical
`benchmarks/pr15h_a/`, `docs/pr-artifacts/pr-15h-a/` and
`crates/quervant-core/tests/pr15h_a_candidate_materialization.rs` are already in
the baseline and must not be edited.

## Tests

```sh
python3 -m py_compile benchmarks/pr15h_a2/run.py benchmarks/pr15h_a2/test_run.py
python3 -m unittest discover -s benchmarks/pr15h_a2 -p 'test*.py' -v
```

The suite covers the seven-lane identity, idle gating, source/ancestry and
dirty-tree refusals, seal/tamper/duplicate-key/symlink refusal, sample and
summary validation, mirrored-schedule refusal, drift-cap boundaries, sign
verdicts, accepted/rejected/blocked decisions, verify-only read-only
recomputation, source allowlist enforcement and historical-artifact
preservation.
