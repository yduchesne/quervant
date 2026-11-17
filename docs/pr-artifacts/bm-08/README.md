# BM-08 — cross-engine synthetic reference, semantic comparability and shared offline qualification

BM-08 proves that a *second* benchmark family — the PR15D-style
Quervant/Tantivy/Lucene exact-keyword comparative question — can reuse the
**same** frozen BM-01 declarations, BM-03 logical-clock simulator and recorder,
BM-04 analysis/policy, BM-05 independent verifier, BM-06 A–E receipts/attestation
and BM-07 read-only result reader **without changing any of those algorithms and
without enabling live timing**.

## What was added

- `benchmarks/experiments/synthetic-cross-engine-reference/` — one closed,
  eleven-file catalog: eight BM-01 declaration files plus three cross-engine
  companions (`oracle-golden.v1.json`, `engine-source-bindings.v1.json`,
  `semantic-comparability.v1.json`).
- `benchmarks/quervant_bench/migrations/cross_engine.py` — a thin read-only
  reference loader plus the mandatory `qualify_cross_engine_synthetic` wrapper that
  calls the unchanged BM-03 controller and BM-06 coordinator.
- `benchmarks/quervant_bench/migrations/cross_engine_contract.py` — the pure
  exact-term corpus oracle, the closed semantic-comparability ledger validator, the
  source-only engine identity validator and the untimed wire-projection contract.
- `benchmarks/quervant_bench/migrations/offline.py` — the **only** changed runtime
  file: a frozen two-entry literal family map
  (`synthetic-retained-key-reference`, `synthetic-cross-engine-reference`).
- Five new test modules (`test_cross_engine_{catalog,semantics,synthetic,offline,
  historical}.py`) plus two closed fixtures.
- One controlled BM-06 source/QA trust-anchor re-freeze.

## Scope and limitations (must not be overstated)

| Capability | Disposition when the local gates pass | Does **not** establish |
|---|---|---|
| Pure exact-keyword oracle + 48 *projected* reply fixtures | `UNTIMED_SEMANTIC_CONTRACT_PASS` | Running Quervant/Tantivy/Lucene |
| Pinned original adapter source files and version literals | `SOURCE_CONTRACT_INSPECTED` | Compiled binary identity or runtime correctness |
| BM-03→BM-06 cross-engine-labelled logical-clock campaign | `SIMULATED_CROSS_ENGINE_A_TO_E_PASS` | Real engine speed, cache behaviour or throughput |
| Two-family offline CLI reads | `TWO_FAMILY_OFFLINE_REVALIDATION_PASS` | Live acquisition or historical equivalence |
| Historical PR15D inspection | `HISTORICAL_SEMANTIC_BOUNDARY_DOCUMENTED` | Numerical/decision parity or an authentic archive |

- `quervant`, `tantivy` and `lucene` are **declared logical sample-stream labels**
  bound to the single BM-03 `synthetic-execution` simulator. No adapter is built,
  launched or queried.
- Every duration is a declared integer logical nanosecond
  (`[990000, 1000000, 1010000]` for every arm and lane). Identical vectors mean no
  synthetic simulation can select a real-engine winner.
- Scored BM25, process-cold and indexing-throughput classes are excluded in the
  semantic ledger. A logical warm simulation is **not** evidence of a physically
  warm engine cache.
- No real timed acquisition was performed, and none may be inferred from these
  artifacts.

## Files

- `design-and-contracts.md` — module boundaries, validation order, invariants.
- `semantic-comparability-and-source.md` — oracle formula, ledger and source
  bindings.
- `reference-catalog-and-offline.md` — catalog layout, schedule/slot arithmetic,
  two-family routing.
- `legacy-equivalence-matrix.md` — the X01–X08 non-equivalence boundary.
- `verification-report.md` — executed commands, observed counts, digests,
  deviations and residual risk.
