# Reference catalog and two-family offline reader

## Catalog (`benchmarks/experiments/synthetic-cross-engine-reference/`)

Exactly eleven regular, non-symlink, canonical files (canonical JSON bytes plus one
trailing LF; the four BM-01 adjacent files are JSON documents with `.yaml` names, as
in BM-07):

```
experiment.yaml  workloads.yaml  protocol.yaml  adapter.yaml
analysis-profile.v1.json  policy-profile.v1.json
resource-observations.v1.json  synthetic-scenario.v1.json
semantic-comparability.v1.json  engine-source-bindings.v1.json
oracle-golden.v1.json
```

Frozen identifiers:

```
experiment_id         synthetic-cross-engine-reference
workload_id           cross-engine-synthetic-keyword
protocol_id           cross-engine-synthetic-paired
policy_id             cross-engine-synthetic-policy
analysis_id           cross-engine-synthetic-analysis
adapter_id            synthetic-execution
adapter.engine_id     synthetic
query_semantics_id    cross-engine-exact-keyword
oracle_id             synthetic-contract-oracle (v1)
arms                  quervant, tantivy, lucene (exact order)
baseline_arm_id       quervant
candidate_order       tantivy, lucene
```

The **one** adapter manifest is the BM-03 synthetic simulator; the three Quervant /
Tantivy / Lucene identities live in `engine-source-bindings.v1.json` outside it. No
v1 bundle ever tries to declare three executable adapters.

## Lane matrix

2 corpus sizes × 4 selectivity classes × 2 K values × warm only = **16 lanes**,
sorted lexicographically, named `n<6-digit N>-<class>-k<3-digit K>-warm`. Each lane
declares `operation=search`, `cache_regime=warm` and exactly the four
schema-permitted params `{corpus_size, top_k, selectivity_class, query_id}` with
`query_id` equal to the lane ID. The frozen `field`/`term` pair for each class is
carried by the reviewed `oracle-golden.v1.json` row for that lane (see the deviation
note in `design-and-contracts.md`).

## Schedule and logical execution

| Field | Value |
|---|---|
| arm multiplicity | 3 arms × `slots_per_block=2` |
| schedule | `seeded-balanced`, `blocks=6`, `slots_per_block=6`, `seed=42` |
| campaigns | `required_controls=1`, `required_treatments=2` |
| measurement | 2 warmups / 3 samples per lane slot, logical nanoseconds |
| statistics | `median-paired-ratios-v1`, `nearest-rank-percentile-v1`, 1000 resamples, seed `1592524801`, paired-block |
| exclusion | `within-arm-spread-v1`, symmetric, minimum 3 retained blocks, cap `1.5` per lane |
| recovery | 0 retries, `hard-stop` |
| control source | `quervant` |

Observed slice: 12 control slots + 72 treatment slots = **84 slots**, **1344 lane
envelopes**, **4032 synthetic samples**, 1 control campaign, 2 treatment campaigns.
Every arm/lane vector is `[990000, 1000000, 1010000]`, so every paired ratio is
exactly `1.000000000000` with a collapsed interval. Under the frozen policy (target
point `0.95`, CI `< 1.0`) no candidate is proven eligible: the decision is
`INCONCLUSIVE` with `selected_arm_id = null`. That is a **synthetic** decision and
chooses no real engine.

## Two-family offline reader

`migrations/offline.py` gained exactly one frozen literal map and explicit
`if/elif` branches on the validated experiment ID:

```python
FAMILY_LOADERS = {
    "synthetic-retained-key-reference": load_reference_bundle,
    "synthetic-cross-engine-reference": validate_cross_engine_reference,
}
```

There is no glob discovery, plugin registry or user-controlled resolver. The
unchanged order is: safe workspace → exact unique UUID directory → allowlisted
family → independent workspace trust anchors → selected BM-01 bundle (plus the
cross-engine companion/source check) → BM-06 `load_qualified_synthetic_run` → exact
second committed `load_bundle` with digest/receipt/directory comparison →
cross-engine companion recheck → existing stage/view document.

`validate`, `analyze`, `verify`, `accept`, `report` keep their BM-07 response and
error contracts; `run` remains exit 77 before any workspace access. A foreign third
family returns `BM_NOT_IMPLEMENTED`; a UUID present under two experiment directories
returns `BM_IDENTITY_INVALID` before either is opened; a ledger changed after the
first verification fails closed. The CLI never creates a workspace and never runs a
BM-03/BM-04/BM-05/BM-06 issuer.

## Catalog authorization and offline recheck (RF08-02)

Both `load_cross_engine_reference` and the post-BM-06 recheck verify the eleven
reviewed raw-byte pins and the frozen protocol content digest. The offline reader
compares the full `CrossEngineCompanionDigests` token (including
`catalog_members_digest`), the original vs revalidated protocol digest, and the frozen
protocol constant after `load_qualified_synthetic_run`. A mutation injected after
BM-06 verification — even one that can be made internally coherent — fails closed
with empty stdout and no workspace write. The retained-key family path is unchanged.
