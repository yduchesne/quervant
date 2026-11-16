# BM-07 — retained-key synthetic reference and offline qualification views

BM-07 adds one **synthetic-only** retained-key reference study and makes the five
reserved read-only stage verbs useful against a previously committed BM-06
qualification. It does not add a benchmark controller, statistics engine, policy
evaluator, reference oracle, attestation publisher or Rust benchmark target.

## What was added

- `benchmarks/experiments/synthetic-retained-key-reference/` — a declarative
  eight-file BM-01 catalog with four scenario labels (`baseline`, `linear`,
  `prefilter`, `exact-set`) and eight simulated query-class lanes.
- `benchmarks/quervant_bench/migrations/` — a thin retained-key locator, a bounded
  offline workspace resolver/stage renderer, and a read-only historical evidence
  assessor.
- `quervant-bench validate|analyze|verify|accept|report --run <uuid> --offline` —
  read-only views over one fully revalidated BM-06 committed bundle.
- BM-07 tests for catalog binding, the real BM-03→BM-06 synthetic chain, policy
  boundaries, forged outputs, offline resolution, replay/reuse rejection and the
  historical non-equivalence ledger.
- One reviewed BM-06 source-roster entry:
  `"benchmarks/quervant_bench/migrations"`, followed by the controlled synthetic
  QA anchor re-freeze.

## Scope and semantic limitations

- Every duration is a declared integer logical nanosecond from the checked-in
  scenario. Nothing is measured on a host, engine, profiler or wall clock.
- The four labels are scenario names, not four built or running engine modes. The
  historical mapping `A/L/P/H → baseline/linear/prefilter/exact-set` is for human
  orientation only and authorises no data conversion.
- The new study is **not** a replay of D3-C/T7/T7-F2 and is not comparable to the
  historical 12-block trials.
- The offline CLI never acquires, derives, verifies from scratch, publishes,
  repairs or relabels evidence. It opens an already committed bundle only after
  full BM-06 revalidation against independently supplied local anchors.
- Local anchors are operator-provisioned trust roots, not cryptographic
  signatures. The QA fixtures are simulated L2 assertions, not CI attestations.
- `quervant-bench run` remains unconditionally prohibited with exit 77. BM-09 owns
  the first real timed campaign.

## Safe usage

```sh
# Declared synthetic contract only.
PYTHONPATH=benchmarks python -m quervant_bench inspect \
    --experiment synthetic-retained-key-reference --format json

# Read-only stage views over an operator-provisioned workspace.
export QUERVANT_BENCH_OFFLINE_WORKSPACE=/absolute/path/to/offline-workspace
quervant-bench validate --run 00000000-0000-4000-8000-000000000001 --offline
quervant-bench analyze  --run 00000000-0000-4000-8000-000000000001 --offline
quervant-bench verify   --run 00000000-0000-4000-8000-000000000001 --offline
quervant-bench accept   --run 00000000-0000-4000-8000-000000000001 --offline
quervant-bench report   --run 00000000-0000-4000-8000-000000000001 --offline

# Still prohibited before BM-09.
quervant-bench run --experiment synthetic-retained-key-reference \
    --protocol protocol.yaml --out /tmp/forbidden   # exit 77
```

## Historical status

The external D3-C archive is an empty stub in the execution environment, so:

```text
HISTORICAL_EVIDENCE_STATUS=EVIDENCE_UNAVAILABLE
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
LEGACY_PATHS_RETIRED=NO
HISTORICAL_ACCEPTANCE_GATE=BLOCKED (scoped, not waived)
```

Historical D3-C/T7/T7-F2 sources, protocols and reports remain byte-identical and
read-only. The frozen historical `median4` convention is the lower-middle value of
four values, which is not the BM-04 paired estimator; no tolerance is invented to
hide that difference. See [legacy-equivalence-matrix.md](legacy-equivalence-matrix.md).

## Artifact map

- [design-and-contracts.md](design-and-contracts.md) — pre-implementation gate,
  R01–R20, false-PASS counterexamples.
- [reference-catalog-and-cli.md](reference-catalog-and-cli.md) — frozen fixture,
  CLI topology and exact stage views.
- [legacy-equivalence-matrix.md](legacy-equivalence-matrix.md) — H01–H08.
- [verification-report.md](verification-report.md) — executed commands, digests,
  coverage, CI status and residual risks.
- [review-fixup-evidence.md](review-fixup-evidence.md) — RF07-01/RF07-02
  red-first evidence, `PRESENT_UNVERIFIED` contract and the follow-up synthetic
  re-freeze.
