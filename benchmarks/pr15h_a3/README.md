# PR 15H-A3 — four-lane diagnostic controller

**Diagnostic only.** This controller measures and compares source variants to
investigate the sparse-query regression observed in rejected PR 15H-A2. It never
retains a production optimization and never emits a performance-acceptance
verdict.

## Lineage

| Item | Value |
|---|---|
| A3 base / accepted source | `7a136f7f299c2f460401b9d92dcef37d219ea98c` (`ddcbe778` search) |
| Rejected A2 candidate B | `569132dace8d92c103dfdebd5d24167d65c0c0c0` |
| A2 final branch HEAD | `d398af5e2dc354f19b209ce53df62f78d12e26f8` |
| Original 15H-A candidate (context) | `dce8f02405e6541d478c2072a0332af192ed2945` |
| A2 historical tooling | `9aff92b6b1a12ee323ed7994a177f88949c736fd` |

## Frozen four lanes (fixed order)

| ID | Lane | Role |
|---|---|---|
| S1 | `pr15d_v1/100000/absent/k100` | zero postings |
| S2 | `pr15d_v1/100000/rare/k100` | one posting |
| S3 | `pr15d_v1/10000/rare/k100` | short-index one posting |
| C1 | `pr15d_v1/100000/common/k100` | high-cardinality control |

All are warm, 5 warmups + 20 timed samples per lane. No other lane is timed.

## Subcommands

```sh
python3 benchmarks/pr15h_a3/run.py aa \
  --checkout-root /ABS/A3_TOOLING --source-tree /ABS/A3_BASE \
  --out /ABS/A3_TOOLING/target/pr15h-a3/aa-01 --idle-authorized

python3 benchmarks/pr15h_a3/run.py ab \
  --checkout-root /ABS/A3_TOOLING --base-tree /ABS/A3_BASE \
  --candidate-tree /ABS/A3_CANDIDATE \
  --out /ABS/A3_TOOLING/target/pr15h-a3/ab-01 --idle-authorized

python3 benchmarks/pr15h_a3/run.py bv2 \
  --checkout-root /ABS/A3_TOOLING --candidate-tree /ABS/A3_CANDIDATE \
  --variant-tree /ABS/A3_V2 \
  --out /ABS/A3_TOOLING/target/pr15h-a3/bv2-01 --idle-authorized

python3 benchmarks/pr15h_a3/run.py bv3 \
  --checkout-root /ABS/A3_TOOLING --candidate-tree /ABS/A3_CANDIDATE \
  --variant-tree /ABS/A3_V3 \
  --out /ABS/A3_TOOLING/target/pr15h-a3/bv3-01 --idle-authorized

python3 benchmarks/pr15h_a3/run.py verify \
  --checkout-root /ABS/A3_TOOLING --campaign /ABS/A3_TOOLING/target/pr15h-a3/aa-01
```

- `aa`: two independent builds of the same accepted source, two mirrored blocks
  `(A,A_PRIME)`, `(A_PRIME,A)` — 4 slots. A/A qualifies only when both block
  ratios are `<= 1.15` (100K) or `<= 1.20` (10K).
- `ab`: accepted A vs rejected B, four mirrored blocks — 8 slots. Reproduction is
  `REPRODUCED` only when S1/S2/S3 are `B_SLOWER` and C1 is `B_FASTER` on all
  four ratios.
- `bv2`: B vs the single-line `H_A2_MIN_POSTINGS = usize::MAX` diagnostic, two
  mirrored blocks. The controller verifies the variant diff is exactly one line.
- `bv3`: B vs B with exactly one `#[inline(never)]` on
  `evaluate_single_term_linear`, two mirrored blocks.
- `verify`: rehash the seal and recompute the sanitized report byte-for-byte.

All outputs live strictly beneath `<checkout-root>/target/pr15h-a3/`. Raw slots
and the seal are immutable; `--out` must not pre-exist.

## Verdicts

| Stage | Output |
|---|---|
| AA | `qualified.json` / `blocked.json` only |
| AB | four B/A ratios per lane + `REPRODUCED` / `REPRODUCTION_INCONCLUSIVE` |
| BV2/BV3 | V/B ratios + `V*_EFFECT_PRESENT` / `V*_EFFECT_NOT_ESTABLISHED`, `SUPPORTING_ONLY` |

No stage emits `PERFORMANCE_ACCEPTED` or `OPTIMIZATION_RETAINED`; the controller
actively rejects such a claim.

## Tests

```sh
python3 -m py_compile benchmarks/pr15h_a3/run.py benchmarks/pr15h_a3/test_run.py
python3 -m unittest discover -s benchmarks/pr15h_a3 -p 'test_*.py' -v
```

The 28 tests cover lane/order refusal, process-cold rejection, AA/AB/variant
schedules, sample/summary/oracle validation, index/host identity, AA and drift
cap boundaries, reproduced/inconclusive verdicts, seal/report tamper, duplicate
JSON keys, symlink/traversal refusal, report-pair conflicts and acceptance-claim
suppression. They never run live timing.
