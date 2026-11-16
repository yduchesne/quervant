# BM-04 — Primary statistical analysis and frozen policy engine

Status: **implemented; see `verification-report.md` for the measured gate results.**
Output is **synthetic/simulated framework evidence only** — never a performance
verdict, a Gate A–E receipt, an approval or a deployment permission.

## What BM-04 is

`benchmarks/quervant_bench/analysis/` is an internal, deterministic primary
analysis layer over BM-03's read-only, replay-verified **synthetic** evidence. It
evaluates an independently digest-bound analysis profile, a frozen policy profile
and a synthetic resource record set, and returns two canonical in-memory
documents: the `analysis.json` payload and the `policy.json` payload.

It is importable Python. It adds **no CLI verb**, writes **nothing** to disk, and
never starts a process, reads a wall clock, opens a socket or invokes an adapter.
`quervant-bench run` still fails closed with `BM_ACQUISITION_PROHIBITED` (exit 77).

## Pipeline

```text
read-only inputs                pure computation                 in-memory outputs
───────────────                 ────────────────                 ─────────────────
BM-03 sealed synthetic run  ─┐
scenario fixture             │  structural replay (first gate)
analysis-profile.v1.json     ├─▶ slot medians → arm/block values
policy-profile.v1.json       │   → raw paired effect
resource-observations.v1.json│   → symmetric lane×block exclusion ledger
                             │   → retained paired effect + bootstrap interval
                             │   → per-campaign GM → frozen policy decision
                             └─▶ re-read + replay again (TOCTOU defence)
                                                              → (analysis, policy)
```

## Key contracts

| Concern | Frozen decision |
| --- | --- |
| slot aggregate | statistical median of the recorded samples; never warmups |
| block aggregate | arithmetic mean of that arm's **all** declared slot medians |
| default estimator | `median-paired-ratios-v1` (median of per-block effects) |
| alternative estimator | `ratio-of-arm-medians-v1` (pure comparison calculator, not the default) |
| exclusion | `within-arm-spread-v1`: whole lane × block × **all arms**, only when an arm spread is *strictly greater* than the lane cap |
| interval | `sha256-rejection-paired-block-v1`, nearest-rank percentiles, 95% |
| resampling unit | the **paired block**; both arms always come from the same draw |
| direction | `candidate/baseline` for lower-is-better, `baseline/candidate` for higher-is-better; a smaller effect is always better |
| precision | `Decimal` at precision 50, quantised to exactly 12 fractional digits, compared exactly |
| memory | exact integer `observed <= max_bytes` |
| selection | frozen candidate order → tie rule → declared baseline fallback |

## Modules

| Module | Responsibility |
| --- | --- |
| `contracts.py` | closed records, decimal grammar, analysis/policy output validators |
| `profiles.py` | closed analysis profile + bounded no-follow reader |
| `arithmetic.py` | medians, block values, direction-aware ratios, both estimators, GM |
| `pruning.py` | symmetric exclusion ledger |
| `bootstrap.py` | deterministic SHA-256 rejection bootstrap + isolated legacy helper |
| `aggregation.py` | read-only reconstruction of BM-03 treatment samples |
| `policy.py` | closed policy profile, resources, eligibility precedence, selection |
| `derive.py` | the single entry point `analyze_synthetic_run(...)` |
| `history.py` | read-only D3-C/T7 compatibility and archive inventory |

## Fixture

`benchmarks/experiments/synthetic-analysis-smoke/` is a **new** experiment. It
reuses the BM-03 schedule, arms, lanes, adapter and simulated sample values, and
adds the canonical `analysis-profile.v1.json`, `policy-profile.v1.json`,
`resource-observations.v1.json` and `synthetic-scenario.v1.json`. Its sealed run
replays to exactly **24 slots, 48 lane envelopes, 16 warmups × 6 = 96 warmups and
144 samples**, and derives:

```text
rare-query    baseline 1 000 000 ns, candidate 800 000 ns -> 0.800000000000
common-query  baseline 1 200 000 ns, candidate 1 000 000 ns -> 0.833333333333
all four blocks retained in both campaigns; both CI endpoints equal the point ratio
policy: candidate eligible -> SELECTED_ELIGIBLE_SYNTHETIC (worst campaign GM 0.816496580928)
```

## Boundaries owned elsewhere

- **BM-05** owns independent recomputation and mutation/adversarial verification.
- **BM-06** owns durable Gate B publication, gate coordination and attestation.
- **BM-07/BM-09** own historical migration and the first real timed qualification.

## Further reading

- [`design-and-contracts.md`](design-and-contracts.md) — contracts, digests, budgets
- [`mathematical-oracles.md`](mathematical-oracles.md) — goldens and the fixed stream
- [`policy-matrix.md`](policy-matrix.md) — operators, precedence, tie boundaries
- [`historical-parity.md`](historical-parity.md) — D3-C/T7 status
- [`verification-report.md`](verification-report.md) — commands, counts, coverage
