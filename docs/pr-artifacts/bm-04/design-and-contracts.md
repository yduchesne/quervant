# BM-04 — Design, contracts and invariant-to-code/test map

Status: **implementation in progress**. This document is the mandatory
pre-implementation correctness gate required by the BM-04 plan (§3). It records
the closed input/output contracts, the identity/digest flow, the numeric and I/O
budgets, and a falsifiable map from every architectural invariant to the code and
the test that proves it.

Scope reminder: BM-04 produces **pure primary statistics and policy documents in
memory**. It issues no Gate A–E receipt, writes nothing into a BM-03 sealed run,
adds no CLI verb, performs no real timed measurement and makes no performance
verdict. Output is synthetic/simulated framework evidence only.

## 1. Change map

| Path | Change | Why |
| --- | --- | --- |
| `benchmarks/quervant_bench/analysis/*` | **new** package | BM-04 logic, fixed file ownership per plan §2 |
| `benchmarks/experiments/synthetic-analysis-smoke/*` | **new** experiment + 4 canonical companion JSON documents | Independent fixture; BM-03 fixture untouched |
| `benchmarks/quervant_bench/tests/test_analysis_*.py`, `tests/fixtures/analysis/*` | **new** tests and goldens | Adversarial and mathematical acceptance |
| `docs/pr-artifacts/bm-04/*` | **new** documentation | Required artifacts |
| `benchmarks/README.md` | one pointer paragraph | Discoverability |
| `docs/benchmarking/BENCHMARKING_ROADMAP.md` | one factual implementation-status sentence, added only after gates pass | Status honesty |

Explicitly **unchanged**: `config/` and the six v1 schemas, `evidence/`, `host/`,
`execution/`, `protocol/`, `benchmarks/pr15*`, `target/`, `crates/`,
`Cargo.toml`, `Cargo.lock`, `.github/workflows/ci.yml`, `quervant_bench/cli.py`.

## 2. Module ownership

| Module | Owns | Never does |
| --- | --- | --- |
| `analysis/contracts.py` | frozen dataclasses, decimal-literal parsing/formatting, closed-field validators, `validate_analysis_result`, `validate_policy_decision` | recompute statistics (that is BM-05's independent job) |
| `analysis/profiles.py` | closed analysis-profile contract and bounded no-follow reader | invent defaults, mutate the profile |
| `analysis/arithmetic.py` | slot median, arm/block mean, direction-aware ratios, the two estimators, geometric mean, 12dp quantisation | any I/O, any RNG, any policy decision |
| `analysis/pruning.py` | `within-arm-spread-v1` symmetric lane×block exclusion ledger | prune one arm, mutate raw evidence |
| `analysis/bootstrap.py` | `sha256-rejection-paired-block-v1` interval + isolated `legacy-python-randrange-v1` helper | global RNG, OS entropy, interpolation, BCa |
| `analysis/aggregation.py` | read-only reconstruction of slot medians from BM-03 schedule + lane envelopes | write, repair, or import the A/A campaign |
| `analysis/policy.py` | closed policy-profile contract, resource observations, eligibility precedence, selection | recompute estimates, emit Gate B receipts |
| `analysis/derive.py` | sole high-level entry point `analyze_synthetic_run` in the mandated §11 order | write to disk, start a process, read wall time |
| `analysis/history.py` | read-only historical D3-C/T7 normalisation and arithmetic comparison | run a historical benchmark, mutate historical evidence, define universal thresholds |

## 3. Identity and digest flow

```text
experiment.yaml --analysis.analysis_id/version/digest-->  analysis-profile.v1.json
                                                          |  (content_digest)
protocol.statistics.method_id/interval_id/resamples/seed -+  must agree
protocol.exclusion.ruleset_id/minimum_retained_blocks -----+
schedule.blocks in [1,256], resamples in [100,20000] ------+

experiment.yaml --policy.policy_id/version/digest--->  policy-profile.v1.json
protocol.yaml   --policy.policy_id/version/digest--->  |  (content_digest)
                                                       both bindings must agree
adapter.measurement_envelope.direction -------------->  policy.metric_direction

resource-observations.v1.json --content_digest--> policy output
                                `resource_observations_digest`

seal.json raw SHA-256 ----------------------------> analysis.source_seal_digest
seal.freeze_digest ------------------------------> analysis.freeze_digest
bundle.protocol_digest ---------------------------> analysis.protocol_digest
analysis-profile content_digest ------------------> analysis.analysis_profile_digest
bootstrap domain-key SHA-256 ---------------------> per-candidate bootstrap_stream_digest
canonical analysis output content_digest ---------> policy.analysis_digest
```

`source_seal_digest` is the SHA-256 of the raw `seal.json` bytes (§11.4 "remember
its raw SHA256"); every other digest is a BM-01 `content_digest` over canonical
payload bytes (`sha256:` + 64 lower-case hex). Neither is an authenticity token:
BM-05/BM-06 own independent verification and attestation.

## 4. Closed input contracts

### 4.1 `analysis-profile.v1.json` (internal BM-04 v1, not a seventh BM-01 schema)

```text
kind, schema_version, analysis_id, analysis_version, evidence_origin,
qualification_scope, slot_aggregator, block_aggregator, estimator_id,
bootstrap{algorithm_id, interval_id, confidence_basis_points, resamples, seed},
exclusion{ruleset_id, symmetric_by_lane_and_block, minimum_retained_blocks,
          per_lane_caps[{lane_id, max_within_arm_ratio}]},
output_precision_decimal_places
```

Fixed by v1: `slot_aggregator=median-v1`, `block_aggregator=mean-of-slot-medians-v1`,
`estimator_id ∈ {median-paired-ratios-v1, ratio-of-arm-medians-v1}`,
`bootstrap.algorithm_id=sha256-rejection-paired-block-v1`,
`bootstrap.interval_id` matched to the protocol, `confidence_basis_points=9500`,
`output_precision_decimal_places=12`, `exclusion.ruleset_id=within-arm-spread-v1`,
`symmetric_by_lane_and_block=true`.

Every decimal is a JSON **string** matching
`^(0|[1-9][0-9]*)(\.[0-9]{1,12})?$`; no sign, exponent, boolean, float, NaN,
infinity or whitespace. Caps are `>= 1.000000000000` and `<= 100.000000000000`.
`per_lane_caps` covers every workload lane exactly once, in ascending lane order.

### 4.2 `policy-profile.v1.json`

```text
kind, schema_version, policy_id, policy_version, evidence_origin,
qualification_scope, baseline_arm_id, candidate_order[], metric_direction,
targets[{lane_id, point_upper, ci_upper, ci_operator}],
guardrails[{lane_id, point_upper, ci_upper, ci_operator}],
resource_rules[{arm_id, resource_id, max_bytes}],
selection{ranking_lanes[], tie_relative_delta, tie_preference[],
          fallback_arm_id, filter_sensitivity_action}
```

`candidate_order` keeps its **declared order** (selection precedence), must be
unique and non-empty, and every entry must be a declared arm distinct from the
baseline. `ci_operator ∈ {lt, le}`. `tie_preference` must be a permutation of
`candidate_order`. Resource rules are sorted-unique by `(arm_id, resource_id)`.
Policy ID/version/digest must match **both** the experiment and protocol policy
bindings, including the exact content digest. `metric_direction` must equal
`bundle.adapter.measurement_envelope.direction`. There is no alias or fallback.

### 4.3 `resource-observations.v1.json`

```text
kind='synthetic-resource-observations', schema_version=1, experiment_id,
evidence_origin='synthetic', qualification_scope='simulated',
records[{arm_id, resource_id, value_bytes}]
```

Records are sorted-unique by `(arm_id, resource_id)`, integers only,
non-boolean, `0 <= value_bytes <= 2**63-1`. A validated record is synthetic data,
never an authenticated production measurement.

## 5. Closed output contracts

### 5.1 `analysis.json` (`kind='synthetic-analysis-result'`)

Top level exactly: `kind, schema_version, experiment_id, run_id,
evidence_origin, qualification_scope, status, source_seal_digest, freeze_digest,
protocol_digest, analysis_profile_digest, analysis_id, analysis_version,
estimator_id, algorithm_id, confidence_basis_points, resamples, seed,
baseline_arm_id, candidate_ids, lane_ids, campaigns`.

Per campaign: `campaign_index, lanes`. Per lane row: `lane_id, blocks_total,
retained_blocks, excluded_blocks, exclusion_ledger, candidates`. Per ledger row:
`block, status, reason, trigger_arms, arm_spreads[{arm_id, spread}]`. Per
candidate row: `candidate_arm_id, comparison_direction, raw_point_effect,
retained_point_effect, ci_low, ci_high, bootstrap_stream_digest, status,
raw_block_effects, retained_block_effects`. Per block effect: `block,
normalized_effect, raw_candidate_over_baseline`.

`status ∈ {analyzed, inconclusive-insufficient-blocks}`. `ci_low`, `ci_high`,
`retained_point_effect`, `bootstrap_stream_digest` are `null` **only** for a
valid insufficient-retained-block lane. `raw_point_effect` is always present on
structurally valid evidence. No raw samples are duplicated; no source path
outside the run is embedded; no policy selection appears anywhere.

### 5.2 `policy.json` (`kind='synthetic-policy-decision'`)

Top level exactly: `kind, schema_version, experiment_id, run_id,
evidence_origin, qualification_scope, status, analysis_digest,
policy_profile_digest, resource_observations_digest, policy_id, policy_version,
baseline_arm_id, candidate_results, selected_arm_id, decision_status, reasons,
ranking`.

Per candidate: `arm_id, status, worst_campaign_gm, campaign_results`. Per
campaign result: `campaign_index, status, lanes`. Per lane result: `lane_id,
kind ∈ {target, guardrail}, point_effect, ci_low, ci_high, point_limit,
ci_limit, ci_operator, retained_blocks, status, reasons`.

`decision_status ∈ {SELECTED_ELIGIBLE_SYNTHETIC,
TIE_PREFERENCE_NOT_PROVEN_FASTER, BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE,
INCONCLUSIVE}`; a `null` `selected_arm_id` **must** carry `INCONCLUSIVE`.
Reasons are closed `{candidate_arm_id, campaign_index, lane_id, code}` with a
literal `null` campaign/lane for global/resource decisions, sorted by
`(campaign_index, lane_id, code)`. No field named `approved`, `release`,
`real_qualification`, `winner_proven`, `pass` or `attestation` exists.

## 6. Numeric contract

* `Decimal` only, inside `localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN))`.
  The ambient global context is never read or mutated.
* `slot_median`: odd count → middle value; even count → exact Decimal average of
  the two middle values (never `// 2`).
* `block_value(arm)`: arithmetic mean of that arm's **all declared slot medians**
  in the block. Samples are never pooled across slots.
* normalised effect: `candidate/baseline` when `lower-is-better`, else
  `baseline/candidate`. Smaller is always better. Candidate identity is never
  swapped to invert a direction.
* `median-paired-ratios-v1`: median of the per-block normalised effects.
* `ratio-of-arm-medians-v1`: `median(candidate block values) /
  median(baseline block values)` over the **same** selected blocks, reversed for
  higher-is-better. Not equivalent to the median of per-block ratios.
* geometric mean: `exp(sum(ln(r_i))/N)` at precision 50 over the policy's
  `ranking_lanes`, using the canonical 12dp retained effects.
* every ratio/GM/CI is quantised to exactly 12 fractional digits and serialised
  with `format(value, 'f')`. Policy comparisons use those quantised values only.
  No float epsilon, no approximate equality, no silent clipping.
* memory: exact integer comparison `observed <= max_bytes`.
* spread cap: excluded iff `spread > cap`; equality is retained.

## 7. Invariant → code → test map

| Invariant | Code | Positive test | Negative test |
| --- | --- | --- | --- |
| AN-01 synthetic-only, no mutation | `derive.py::_require_synthetic_scope` | `AN-INT-01` | `AN-INT-02`, `AN-SCOPE-02` |
| AN-02 dual digest bindings | `profiles.py`, `policy.py` | `AN-BIND-01/02` | `AN-BIND-03/04/05` |
| AN-03 every slot once, controls excluded | `aggregation.py` | `AN-ING-01/02` | `AN-ING-03/04/05` |
| AN-04 exact slot/block arithmetic | `arithmetic.py` | `AN-MATH-01/02/03` | `AN-MATH-05/06` |
| AN-05 symmetric lane×block exclusion | `pruning.py` | `AN-PRUNE-01/04` | `AN-PRUNE-02/03/05/07/08/09` |
| AN-06 paired-block bootstrap | `bootstrap.py` | `AN-BOOT-01/02/03/04` | `AN-BOOT-06/08/09` |
| AN-07 direction-aware ratios | `arithmetic.py` | `AN-DIR-01/02/03/04` | `AN-DIR-05/06` |
| AN-08 inconclusive ≠ winner | `pruning.py`, `policy.py` | `AN-PRUNE-06` | `AN-INT-03`, `AN-POL-14` |
| AN-09 exact operator/resource boundaries | `policy.py` | `AN-POL-02/05/09` | `AN-POL-03/06/10/11/12` |
| AN-10 frozen selection precedence | `policy.py` | `AN-SEL-01/02/05/08` | `AN-SEL-03/04/06/07/09/10` |
| AN-11 canonical, stable, finite | `contracts.py`, `derive.py` | `AN-CAN-01/05/06` | `AN-CAN-02/03/04/07/08` |
| AN-12 historical separation | `history.py` | `AN-HIST-01/02` | `AN-HIST-03/04/05/06` |
| AN-13 no measurement/verdict/receipt | `derive.py`, untouched `cli.py` | `AN-SCOPE-01/03/04` | `AN-SCOPE-02/05/06` |
| AN-14 bounded, no-follow I/O | `profiles.py`, `derive.py` | `AN-LIMIT-01/02` | `AN-LIMIT-03…09` |

## 8. Mandated counterexamples

For each of the following, a **plausible wrong implementation that passes the
happy path** is named together with the assertion that kills it.

| Case | Wrong implementation that passes happy path | Killing assertion |
| --- | --- | --- |
| `AN-MATH-04` | ratio-of-arm-medians masquerading as `median-paired-ratios-v1` (identical when all block ratios are equal) | blocks `A=[10,20,100]`, `B=[10,50,50]` must give `1.000000000000` for median-of-ratios and `2.500000000000` for ratio-of-medians; asserting **both** distinguishes them |
| `AN-PRUNE-02` | pruning only the offending arm (the favorable one) | `A=[10,16]`, `B=[10,10]`, cap 1.5 must exclude the **pair**: both arms absent from `retained_blocks`, both named in `trigger_arms` when both offend |
| `AN-BOOT-06` | resampling baseline and candidate independently | every replicate's drawn block identity must come from one shared index list; a two-arm independent draw changes the constant-ratio CI away from `0.800000000000` and is rejected by the stream/index golden plus an exact paired-row equality probe |
| `AN-POL-03` | using `<=` for a `lt` CI bound (float-style tolerance) | `ci_high = 1.000000000000` with `ci_operator=lt` must be `TARGET_UNPROVEN`/inconclusive, while `0.999999999999` passes |
| `AN-POL-09` | treating a missing resource observation as `0` (implicitly eligible) | a resource rule without a matching observation must be `INCONCLUSIVE`/`MISSING_RESOURCE`, never eligible |
| `AN-SEL-06` | `<=` tie comparison | a relative delta of exactly `0.030000000000` is **not** a tie and must choose the smaller worst GM |
| `AN-INT-04` | reading the seal once and trusting it | mutating a lane envelope between the first and second read must raise `BM_IDENTITY_INVALID` and return no outputs |

## 9. I/O and resource budgets

| Budget | Value | Enforced by |
| --- | --- | --- |
| profile / resource document bytes | `1 MiB + 1` read cap, reject above `1 MiB` | `profiles.py::read_analysis_profile`, `policy.py::read_resource_observations` |
| canonical output bytes per document | `1 MiB` | `derive.py` |
| `resamples` | `[100, 20000]` | `profiles.py` |
| `schedule.blocks` | `[1, 256]` | `profiles.py` |
| candidate arms | `<= 8` | `profiles.py` |
| lanes | `<= 64` | `profiles.py` |
| treatment campaigns | `<= 8` | `profiles.py` |
| `max_total_draws` | `2_000_000` for one derivation | `profiles.py::require_draw_budget` |
| `max_analysis_records` | `10_000` | `derive.py` |
| retained blocks needed for a CI | `max(protocol.minimum_retained_blocks, 2)` | `pruning.py`, `policy.py` |
| bootstrap counter ceiling | `2**64-1`, typed failure, never wrap | `bootstrap.py` |

All reads go through the BM-02 no-follow helpers (`open_regular_beneath`,
`require_safe_root`); no new reader is introduced.

## 10. Why sealed evidence stays immutable

BM-04 only ever opens the sealed run through `open_regular_beneath` in read mode,
never calls `ExecutionStore`, `mkdir`, `open(..., 'w')`, `fsync` or
`commit_seal`, and re-verifies the complete seal + replayer after building its
in-memory documents. Adding `analysis.json`/`policy.json` inside a sealed run
would invalidate the closed file inventory checked by
`replay_sealed_synthetic`, so published payloads are returned as canonical
**bytes** for BM-06 to persist elsewhere.

The double read is a deterministic ordinary-change detector: it catches an
accidental or concurrent mutation between the first and last read. It is **not**
an authentication boundary against an adversary who races and restores bytes;
that is BM-06/BM-09 work.
