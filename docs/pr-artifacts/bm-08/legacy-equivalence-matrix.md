# BM-08 legacy equivalence matrix

This is an explicit *boundary* record, not a claim of observed parity with historical
PR15D results. Machine-readable counterpart:
`benchmarks/quervant_bench/tests/fixtures/cross-engine/legacy-equivalence.v1.json`.

## Historical status (frozen)

```
HISTORICAL_NUMERIC_PARITY   = NOT_EXECUTED
HISTORICAL_DECISION_PARITY  = NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE  = BLOCKED
LEGACY_PATHS_RETIRED        = NO
```

No original PR15D source, spec, harness or adapter file was modified; the recorded
raw-byte digests are asserted by `HIST-01`. The original `run.py`, `smoke.py`,
adapter `query` operations, Criterion targets and D3-C/T7 files were not executed.

## Rows

| ID | Class | Legacy component | New component | Required input | Expected comparison | Missing disposition |
|---|---|---|---|---|---|---|
| X01 | `SEMANTIC` | exact `key`/`group` membership | `compute_oracle_row` | frozen row formula | identical `total_hits` and identical ascending `doc_id` list | `blocked-synthetic-oracle-missing` |
| X02 | `SEMANTIC` | `doc_id` ascending + top-K truncation | `compute_oracle_row` | `K ∈ {10,100}` | first `min(K,total_hits)` entries, element-wise | `blocked-synthetic-oracle-missing` |
| X03 | `NON_EQUIVALENT_CONTRACT` | `process_cold` restart regime | warm-only logical campaign | real restart and physical cache state | not comparable; `DEFERRED` | `excluded-deferred` |
| X04 | `NON_EQUIVALENT_CONTRACT` | BM25 scored lane | exact-membership lane | identical scoring and tie contract | not comparable; `NONCOMPARABLE` | `excluded-noncomparable` |
| X05 | `SEMANTIC` | source/build/corpus identity intent | raw-byte source bindings | original regular source files and pins | identical length and SHA-256 | `blocked-source-identity` |
| X06 | `NON_EQUIVALENT_CONTRACT` | 3 trials × 20 samples | 6 blocks × 3 logical samples | real acquisition campaign | not comparable; orchestration slice only | `deferred-real-acquisition` |
| X07 | `SEMANTIC` | adapter wire response | untimed six-field projection | one record per (engine,lane) | identical `total_hits` and ordered `doc_ids`; timing rejected | `blocked-wire-contract` |
| X08 | `EVIDENCE_UNAVAILABLE` | archived numeric/decision/QA evidence | synthetic receipts | authentic archive + approved verifier | not executed; historical gate `BLOCKED` | `historical-gate-blocked` |

## Why the non-equivalent rows are non-equivalent

- **X03**: a logical warm simulation cannot model a fresh process and an unverified
  physical page cache. The ledger records `process-cold` as `DEFERRED`; the measured
  matrix is warm-only.
- **X04**: the frozen spec still declares
  `scored_lane.status = SEMANTICALLY_NONCOMPARABLE_UNTIL_PROVEN`, requiring identical
  `k1=1.2`, `b=0.75`, length normalisation, document statistics and tie behaviour
  across all three engines.
- **X06**: the frozen balanced scheduler cannot represent the plan's prescribed
  4-block/6-slot layout (tile size 3), so the observed 6-block slice is recorded
  explicitly rather than papered over.
- **X08**: no authentic full historical archive is available locally. No historical
  published number was used to set synthetic sample values or to extrapolate
  competitive latency.

## Retained-key regression

The BM-07 retained-key family, catalog, fixtures and offline views are unchanged and
are re-exercised by `REG-01`–`REG-04`.
