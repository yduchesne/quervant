# PR 15I-D2-A — qualified scoring attribution

## Verification status

| Campaign | Kind | Structural | Oracle | Contention | A/A or intrusion | Stage partition | Priority gate |
|---|---|---|---|---|---|---|---|
| `d2a-base-aa-01` | A1/A2 control | PASS | PASS | PASS | `D2A_CONTROL_QUALIFIED` | n/a | n/a |
| `d2a-unbatched-01` | A/Q/P | PASS | PASS | PASS | `D2A_ATTRIBUTION_LOW_INTRUSION` | `QUALIFIED`, 0/1440 violations | **FAIL** (1/3 lanes) |
| `d2a-unbatched-02` | A/Q/P | PASS | PASS | PASS | `D2A_ATTRIBUTION_LOW_INTRUSION` | `QUALIFIED`, 0/1440 violations | **FAIL** (1/3 lanes) |

Aggregate independent verdict: **`D2A_SCORE_COST_LOW_PRIORITY`**.

Counts actually executed: 64 slots, 11,520 timed samples, 2,880 warmups,
128 clear contention probes and 10 index builds (plus superseded attempts that
were never accepted). The 100K A/QP committed index digests are byte-identical.

## A/A control (final T0)

The qualified retry has a lower-median `A1/A2` ratio of 0.9399–1.0429 across the
nine lanes, inside `[0.85, 1.15]`; every block ratio is inside `[0.80, 1.25]`.
The first attempt (one 10K absent block at 1.269948) is preserved and excluded.

## Intrusion checks (Q/A and P/Q medians)

| Campaign | Lane group | Q/A ceiling | max observed | P/Q ceiling | max observed |
|---|---|---|---|---|---|
| 01 | absent/rare | 1.15 | 1.0197 | 1.25 | 1.0166 |
| 01 | medium/common | 1.10 | 1.0220 | 1.15 | 1.0038 |
| 02 | absent/rare | 1.15 | 1.0153 | 1.25 | 1.0214 |
| 02 | medium/common | 1.10 | 1.0214 | 1.15 | 1.0102 |

All are below the frozen ceilings; no low-hit probe intrusion invalidates the
attribution.

## Primary-lane score cost

Values are per-lane nearest-rank medians of sample-level ratios from P; they are
instrumentation-inclusive and are not accepted-build latency.

| Campaign | Lane | `score_accumulate` median ns | engine share | `score_vector` median ns | `bm25_calls / returned` | Gate |
|---|---|---|---|---|---|---|
| 01 | 100K medium/K100 | 655,600 | 0.0402 | 794,841 | 125.0 | FAIL (share < 0.08) |
| 01 | 100K common/K100 | 2,649,899 | 0.0657 | 3,246,556 | 499.99 | FAIL (share < 0.08) |
| 01 | 100K common/K10 | 2,632,115 | 0.0872 | 3,220,432 | 4,999.9 | PASS |
| 02 | 100K medium/K100 | 661,192 | 0.0404 | 804,833 | 125.0 | FAIL (share < 0.08) |
| 02 | 100K common/K100 | 2,630,741 | 0.0648 | 3,218,966 | 499.99 | FAIL (share < 0.08) |
| 02 | 100K common/K10 | 2,633,308 | 0.0866 | 3,232,165 | 4,999.9 | PASS |

The §11 gate requires at least **two of three** primary lanes to meet both
`median >= 2,000,000 ns` and `share >= 0.08`. Both campaigns qualify exactly
one lane (common/K10). The result is stable across campaigns and is not a
threshold-tuning opportunity.

### Optimistic arithmetic-only upper bound

Using same-campaign sample medians, `engine_ns / (engine_ns -
score_accumulate_ns)` gives:

| Lane | Campaign 01 | Campaign 02 |
|---|---|---|
| 100K medium/K100 | ≈1.042 | ≈1.042 |
| 100K common/K100 | ≈1.070 | ≈1.069 |
| 100K common/K10 | ≈1.095 | ≈1.095 |

These are **optimistic diagnostic upper bounds**, not predicted speedups and not
evidence that all accumulation time is removable. They assume no mapping,
owner, projection, error, budget or cancellation cost and no mapper-selected
implementation.

## Non-primary lanes

The 10K lanes and 100K absent/rare lanes show much smaller accumulation cost
(e.g. 10K common/K100 ≈237 µs, 5.9–6.0%; 100K rare ≈0.46 µs, <0.2%). The absent
lanes correctly report 0 ns and zero counters. This is consistent with the
D0 attribution that candidate processing, not the removable scoring arithmetic,
dominates the high-hit path.

## Interpretation

D2-A is a measurement gate, not a performance change. The measured absolute
scoring-accumulation cost is approximately 0.66 ms on medium and 2.63 ms on the
two common 100K lanes. Only common/K10 crosses both frozen priority thresholds.
Because both independent campaigns agree, the closed-form verdict is
`D2A_SCORE_COST_LOW_PRIORITY`; no immediate D2-B implementation is recommended,
and the semantic contract risks in `correctness-trace.md` independently prevent
D2-A from authorizing one.

## Residual limits

- Warm-lane attribution only; `process_cold` means a fresh adapter process, not
  an OS page-cache cold start.
- Quervant and Tantivy/Lucene use non-equivalent physical operators; no BM25
  cost parity is claimed.
- Stage values are nested/instrumented observations; parent and children are
  never added together.
- Archives are same-disk unless an operator supplies off-host storage.
