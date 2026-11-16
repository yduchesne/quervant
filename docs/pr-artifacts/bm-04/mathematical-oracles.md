# BM-04 — Mathematical oracles

Every expected value in this document is **hand-authored**. No test generates an
expected value by calling the function it is testing, and the frozen SHA-256 stream
golden is independently reproducible without importing `quervant_bench`.

## 1. Frozen numeric conventions

```text
precision            Context(prec=50, rounding=ROUND_HALF_EVEN), local only
final quantisation   Decimal('0.000000000001')  (exactly 12 fractional digits)
serialisation        format(quantized, 'f')
policy comparison    exact Decimal operators on the quantized values; no epsilon
decimal literal      ^(0|[1-9][0-9]*)(\.[0-9]{1,12})?$   (JSON strings only)
```

An ambient global decimal context is never read and never mutated: every
arithmetic entry point opens its own `localcontext`.

## 2. Slot and block aggregation

| ID | Input | Expected |
| --- | --- | --- |
| AN-MATH-01 | samples `[1, 3, 7]` | `3` |
| AN-MATH-01 | samples `[1, 3, 7, 9]` | `5` (exact Decimal average of the middle two) |
| AN-MATH-05 | samples `[1, 2]` | `1.5` |
| AN-MATH-02 | baseline slot medians `[10, 14]`, candidate `[8, 10]` | block values `12` and `9`; lower-better effect `0.750000000000` |
| AN-MATH-03 | baseline slots `[10,10,10]` and `[10,1000,1000]` | block value `505`; pooling all six samples would give `10` |

AN-MATH-03 is the anti-pooling proof: with the two slot medians `10` and `1000`,
the block value is their mean `505`, while the median of all six raw samples is
`10`. An implementation that pooled samples across slots would hide the slow slot
entirely and still pass every single-slot happy-path test.

## 3. Estimator distinction (AN-MATH-04)

Blocks `(baseline, candidate)` = `(10, 10)`, `(20, 50)`, `(100, 50)`.

```text
per-block effects            1.0, 2.5, 0.5
median-paired-ratios-v1      median(0.5, 1.0, 2.5)          = 1.000000000000
ratio-of-arm-medians-v1      median(10, 20, 100) = 20
                             median(10, 50, 50)  = 50
                             candidate/baseline  = 50/20     = 2.500000000000
```

The two estimators agree on every constant-ratio dataset, which is exactly why a
constant-ratio-only test cannot detect a substitution. The test asserts **both**
values on this dataset, so either substitution fails.

## 4. Geometric mean (AN-MATH-07)

| Input | Expected |
| --- | --- |
| `[0.8, 1.25]` | `1.000000000000` |
| `[0.25, 0.25, 4, 4]` | `1.000000000000` |

`worst_campaign_gm = max(GM_campaign)` because a lower normalised effect always
favours improvement.

## 5. Metric direction (AN-DIR-01…06)

| Direction | Values | Normalised effect |
| --- | --- | --- |
| lower-is-better | baseline 100, candidate 80 | `candidate/baseline` = `0.800000000000` |
| higher-is-better | baseline 100, candidate 125 | `baseline/candidate` = `0.800000000000` |
| higher-is-better | baseline 100, candidate 80 | `1.250000000000` |

A smaller normalised effect is always better. Candidate identity is never swapped
to invert a direction: `normalized_effect(100, 80, lower-is-better)` is
`1.250000000000`, and multiplying the two orientations yields exactly `1`.

## 6. Rounding boundary (AN-MATH-05)

| Value | 12-place round-half-even |
| --- | --- |
| `0.8333333333335` | `0.8333333333334`-class tie → `0.833333333334` |
| `0.8333333333325` | `0.833333333332` |
| `0.8000000000005` | `0.800000000000` |

## 7. Bootstrap percentile indexes (AN-BOOT-04)

```text
tail = (10000 - 9500) / 2 = 250
low  = ceil( 250 * R / 10000) - 1
high = ceil(9750 * R / 10000) - 1      (integer-only ceil: (n + d - 1) // d)

R = 1000  -> (24, 974)
R = 10000 -> (249, 9749)
```

No interpolation, normal approximation, BCa correction or hidden standard error.

## 8. Frozen SHA-256 bootstrap stream (AN-BOOT-03 / plan §19)

Binding payload (canonical bytes via `config.codec.canonical_payload_bytes`, sorted
keys, no spaces, no trailing newline):

```json
{"baseline_id":"baseline","campaign_index":0,"candidate_id":"candidate","estimator_id":"median-paired-ratios-v1","lane_id":"rare-query","protocol_digest":"sha256:0000000000000000000000000000000000000000000000000000000000000000","seed":42}
```

Algorithm:

```text
domain_key = SHA256(b"quervant-bench/paired-bootstrap/v1\x00" || payload).digest()
limit      = (2**64 // nblocks) * nblocks
counter    = 0
u          = int.from_bytes(SHA256(domain_key || counter.to_bytes(8,'big')).digest()[:8],'big')
counter   += 1
if u >= limit: reject and retry with the next counter
else:          accept u % nblocks
```

The counter increments **once per attempted draw** (accepted or rejected).

```text
domain_key (lower-case hex)
e721deeafcc410ebb65aef7944bc4dc3d5a6ec0b23e34ed99f4948bba4af12a8

first 16 accepted zero-based block indexes (nblocks = 3)
[0, 2, 0, 2, 1, 2, 1, 0, 0, 0, 0, 1, 0, 2, 2, 0]
```

Source: `benchmarks/quervant_bench/tests/fixtures/analysis/bootstrap-index-reference.py`
(a standalone 15-line script that **does not import `quervant_bench`**).

Golden file: `benchmarks/quervant_bench/tests/fixtures/analysis/bootstrap-index-golden.v1.json`
(canonical payload bytes, 482 bytes, `sha256:7f86e7fb10aa15b970cbaffdfba12ebb5503f234aae4f03d351d9948fcd999ee`).

Reproduce:

```sh
python3 benchmarks/quervant_bench/tests/fixtures/analysis/bootstrap-index-reference.py
python3 -c "import hashlib;print('sha256:'+hashlib.sha256(open('benchmarks/quervant_bench/tests/fixtures/analysis/bootstrap-index-golden.v1.json','rb').read()).hexdigest())"
```

## 9. Constant-ratio and paired-draw oracles (AN-BOOT-01/02/06)

* **AN-BOOT-01** — blocks `(10,8)`, `(20,16)`, `(30,24)`, `(40,32)`. Every block has
  the ratio `0.8`, so every replicate and **both** endpoints are exactly
  `0.800000000000` for every seed. The distinct block *magnitudes* matter: an
  implementation that drew the two arms independently would mix blocks and produce a
  spread instead of a degenerate interval.
* **AN-BOOT-02** — blocks `(10,10)`, `(20,20)`, `(30,30)`, `(40,40)` ⇒ both
  endpoints `1.000000000000`.
* **AN-BOOT-06** — the test additionally builds a *test-local independent-draw
  oracle* that pairs a candidate value from one drawn block with a baseline value
  from a different drawn block. Its replicate set contains more than one value while
  the production paired estimator's replicate set is exactly `{0.8}`.

## 10. Exclusion goldens (AN-PRUNE-01…09)

Cap for both lanes is `1.500000000000`.

| Slot medians | Spread | Result |
| --- | --- | --- |
| `A=[10,15]`, `B=[10,10]` | `1.5` | **retain** (equality is not exclusion) |
| `A=[10,16]`, `B=[10,10]` | `1.6` | **exclude the pair**, trigger `baseline` |
| `A=[10,10]`, `B=[10,16]` | `1.6` | **exclude the pair**, trigger `candidate` |
| `A=[10,15.000000000001]`, `B=[10,10]` | `1.5 + 1e-12` | **exclude** |
| single slot per arm | `1` | **retain** |

Four blocks with two excluded and a minimum of three retained blocks is a
**valid inconclusive** result: the raw point estimate and the full ledger are kept,
the retained effect / CI / stream digest are JSON `null`, and no candidate can be
selected.

## 11. Test coverage map

| Test ID | Module |
| --- | --- |
| AN-MATH-01…07, AN-DIR-01…06 | `test_analysis_arithmetic.py` |
| AN-PRUNE-01…09 | `test_analysis_pruning.py` |
| AN-BOOT-01…11 | `test_analysis_bootstrap.py` |
| AN-BIND-01…05, AN-CAN-01…06, AN-CAN-08 | `test_analysis_contracts.py` |
| AN-POL-01…18, AN-SEL-01…10 | `test_analysis_policy.py` |
| AN-ING-01…05, AN-INT-01…05, AN-LIMIT-01…09, AN-SCOPE-01…06, AN-CAN-07 | `test_analysis_vertical_slice.py` |
| AN-HIST-01…06 | `test_analysis_history.py` |

### Mandated counterexamples and the assertion that kills each

| Case | Plausible wrong implementation | Killing assertion |
| --- | --- | --- |
| AN-MATH-04 | ratio-of-arm-medians used as the default estimator | both point values asserted on the same dataset (`1.000000000000` vs `2.500000000000`) |
| AN-PRUNE-02 | pruning only the offending arm | both arms vanish from `retained_blocks`; `trigger_arms` names the offender only |
| AN-BOOT-06 | independent per-arm resampling | constant-ratio dataset with distinct magnitudes stays degenerate at `0.800000000000`, and the test-local independent-draw oracle demonstrably spreads |
| AN-POL-03 | `<=` used for a `lt` CI bound | `1.000000000000` is unproven, `0.999999999999` passes |
| AN-POL-09 | missing resource treated as `0` | `MISSING_RESOURCE` + inconclusive, never eligible |
| AN-SEL-06 | `<=` tie comparison | a `0.030000000000` relative delta is not a tie and selects the smaller GM |
| AN-INT-04 | reading the seal once and trusting it | mid-derivation lane mutation raises a typed error, returns no outputs and writes no files |
