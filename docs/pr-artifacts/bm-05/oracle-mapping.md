# BM-05 — Oracle provenance, independence audit and vector mapping

## 1. Principle

A primary engine and an oracle that call the same implementation are not
independent. BM-05 therefore re-derives every material number and decision from
the sealed source records. BM-04 code is reused only for **input admission**
(canonical codecs, safe path opening, structural replay, envelope/seal validation,
frozen profile readers, closed output validators) and never as a calculator,
selector or expected-value source.

## 2. Source → independent source map

| Concern | Primary source (reused?) | Independent BM-05 source | Shared dependency exception |
| --- | --- | --- | --- |
| Slot median | `analysis.arithmetic.slot_median` — **not called** | `verification.reference_math.slot_median` | none |
| Arm block value | `analysis.arithmetic.arm_block_value` — **not called** | `reference_math.mean_of` | none |
| Normalised/raw effect | `analysis.arithmetic.{normalized_effect,raw_ratio}` — **not called** | `reference_math.{normalized_effect,raw_ratio}` | none |
| Estimators | `analysis.arithmetic.compute_paired_effect` — **not called** | `reference_math.compute_estimator` | none |
| Symmetric pruning | `analysis.pruning.apply_lane_block_exclusions` — **not called** | `reference_math.compute_statistics` ledger | none |
| 12dp quantisation/format | `analysis.contracts.{quantize_effect,format_effect}` — **not called** | `reference_math.{quantize_12,format_12}` | none |
| Bootstrap stream/CI | `analysis.bootstrap.bootstrap_interval` — **not called** | `reference_bootstrap.compute_interval` | canonical JSON bytes from `config.codec`; stdlib `hashlib.sha256` |
| Policy truth table/selection | `analysis.policy.{evaluate_policy,_select}` — **not called** | `reference_policy.evaluate_reference_policy` | policy/resource **readers only**; closed structural validator only |
| Sample traversal | `analysis.aggregation.read_treatment_samples` — **not called** | `reference_input.collect_reference_evidence` | BM-03 `lane_relative_path`, envelope/seal validators, BM-02 no-follow open |
| Structural admission | `analysis.derive` — **not called from verification** | `execution.replay.replay_sealed_synthetic` | reused as the frozen BM-03 admission gate (not a statistical oracle) |
| Output comparison | `analysis.contracts.validate_*` — **first-line structural checks only** | full source-derived document reconstruction + deterministic first-difference | validators never recompute statistics |

No wrapper, dynamic import or indirect route reaches a forbidden function. The AST
audit and runtime poison probe in `test_verification_independence.py` prove this.

## 3. Formulas

All arithmetic uses a fresh `Context(prec=50, rounding=ROUND_HALF_EVEN)`; an
ambient context is never read. The final rendering is
`Decimal('0.000000000001')` quantisation then `format(value, 'f')`.

```text
slot median            odd: middle sample; even: exact mean of middle two
block value            arithmetic mean of that arm's declared slot medians
within-arm spread      max(slot medians) / min(slot medians)
exclusion              any arm's spread > lane cap => exclude whole block for all arms
raw block ratio        candidate / baseline
normalised effect      lower-is-better: candidate/baseline
                       higher-is-better: baseline/candidate
median-paired-ratios   median(normalised per-block effects)
ratio-of-arm-medians   normalised(median(candidate block values),
                                  median(baseline block values)) on the same blocks
GM                     exp(sum(ln(r_i)) / N); worst campaign GM = max(GMs)
tie                    delta = |a-b| / min(a,b); tie iff exact equality or delta < frozen delta
```

## 4. Bootstrap provenance and frozen vector

`sha256-rejection-paired-block-v1`:

```text
key     = SHA256(b"quervant-bench/paired-bootstrap/v1\x00" || canonical(binding))
binding = {baseline_id, campaign_index, candidate_id, estimator_id, lane_id,
           protocol_digest, seed}   (exact closed key set)
draw    = SHA256(key || counter.to_bytes(8,"big"))[:8] as big-endian u64
limit   = (2**64 // nblocks) * nblocks
reject  if value >= limit, increment counter and retry
accept  value % nblocks
replicate: nblocks paired draws with replacement, same estimator both arms
bounds  low = ceil(250*R/10000)-1, high = ceil(9750*R/10000)-1
```

The prescribed non-degenerate vector (seed 7, 4 blocks) was independently
reproduced with a standalone standard-library script that imports no
`quervant_bench` module. It produced exactly the plan §6 literals:

```text
domain key          9b77d5e532d4404ea88f3248da6681d0486313cd45dda2d0cb78920d0f7a4b25
first 16 indexes    [2,1,0,2, 0,3,1,0, 3,0,2,0, 3,1,0,0]
first 12 medians    1.000000000000, 0.900000000000, 0.900000000000, 0.900000000000,
                    0.750000000000, 0.750000000000, 0.750000000000, 0.825000000000,
                    1.000000000000, 0.750000000000, 0.925000000000, 1.100000000000
nearest-rank        (2, 97)
CI                  [0.750000000000, 1.100000000000]
accepted draws      400; rejected counters 0
```

The published seed-42 three-block golden
(`tests/fixtures/analysis/bootstrap-index-golden.v1.json`, key
`e721deea…`, first indexes `[0,2,0,2,1,2,1,0,0,0,0,1,0,2,2,0]`) is also checked
against its standalone reproducer. `reference-vectors.v1.json` additionally
records a modulo-bound case (`value=2**64-1` rejected for 3 blocks, `2**64-2`
accepted as index 2) and the percentile goldens `(24,974)`/`(249,9749)`.

## 5. Reference vectors

`tests/fixtures/verification/reference-vectors.v1.json` is canonical JSON and
contains hand-reviewed literals for:

* even/odd mode medians (`[10,20,100,200] -> 60`, `[1,2] -> 1.5`);
* the estimator counterexample (`1.000000000000` vs `2.500000000000`) that kills a
  silent estimator substitution;
* lower/higher direction (`0.800000000000` vs `1.250000000000`, raw unchanged);
* pruning equality, strict exclusion, and trigger-arm cases;
* the published and small bootstrap vectors above;
* policy thresholds, resource cap and tie boundaries.

No expected value in these tests is generated by calling the primary engine. For
vertical slices the primary engine is invoked **in test setup only** to produce a
proposed document under test; expected literals remain frozen independently.

## 6. Historical T7-F2 mapping (read-only, semantic reference only)

Inventory from `find benchmarks/pr15i_d3_c -type f` (source hashes are SHA-256):

| Path | SHA-256 | Original responsibility | BM-05 semantic counterpart |
| --- | --- | --- | --- |
| `benchmarks/pr15i_d3_c/verify.py` | `54e91d999ac923cf9e33289207d5a567786a7b318dbc46c5f24ed276f07fa2cd` | independent historical verifier: inventory, schedule, oracle, status/reason/CI/memory/election checks, no controller import | `reference_input` (inventory/traversal), `reference_math`, `reference_policy`, `verify` |
| `benchmarks/pr15i_d3_c/analysis_v3.py` | `a028de728c44f553924faf8ab78b1f73da50d11e7bcc88ce9254c8c87d0d9603` | historical analysis/statistics | `reference_math` semantics only; not copied |
| `benchmarks/pr15i_d3_c/policy.py` | `79674459d14ea41f6dcc9a9e3dec995bcab6cf8588d94b73b7e4212c331ed4bc` | historical policy | `reference_policy` semantics only; not copied |
| `benchmarks/pr15i_d3_c/replay.py` | `367d16016fc40d6bbe7e979440ac00e2061136eabfb39c7643c609601afde9fe` | historical replay | BM-03 replay gate reused for the new synthetic format |
| `benchmarks/pr15i_d3_c/test_verify.py` | `59a3265dd8fab591c39c9c3edefeb740f470465340e4a5e5fa801d5f486254b0` | historical verifier tests | semantic reference for independent checking |

The historical T7 estimator (`legacy-python-randrange-v1`, ratio of arm medians)
and the new BM-04 default (`sha256-rejection-paired-block-v1`,
median-paired-ratios-v1) are **not interchangeable** and are never conflated.
No historical script, evidence or verdict was modified or executed; no legacy
path was retired. See `historical-parity.md`.


## 7. RF05 review-fixup oracle clarification

* **Parity vs order.** `reference_math.sign_of` remains an individual
  effect/parity comparator against `1`, and its docstring now states that it must
  not compare candidates. Pair ordering uses the separately coded
  `reference_math.compare_candidate_order(first, second)`, which compares relative
  magnitude (difference relative to `0`). The primary fix uses its own
  `analysis.policy._relative_order`; the reference never imports it.
* **Zero policy bounds.** `reference_math.format_policy_limit_12` is a separate,
  explicitly nonnegative formatter used only for `point_limit` and `ci_limit`
  display. Generic `format_12`, `quantize_12`, `require_decimal`, samples,
  denominators and effects remain strict-positive.
* **Negative control.** `F05-IND-01` builds a hand-authored two-campaign policy
  fixture, asserts literal reference reasons/status/selection, compares the
  corrected primary document with the reference, then poisons only the primary
  `_filter_sensitive_lanes` to return an empty set. The poisoned primary produces
  a plausible `SELECTED_ELIGIBLE_SYNTHETIC` document that the independent
  reference rejects; expected values are never computed from the primary.
