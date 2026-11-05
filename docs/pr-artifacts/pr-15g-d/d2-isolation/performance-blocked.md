# D2-only isolation performance — measurement blocked

**Status:** `MEASUREMENT_BLOCKED_REVIEW_REQUIRED`
**Campaign:** opaque `d2-only-first-qualified`
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**X:** `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6`

No performance verdict is claimed. The complete campaign failed the fixed drift
gate, so all timing ratios are retained as blocked evidence only.

## Acquisition

| Item | Result |
|---|---|
| Slots | 16/16 |
| Arms | 8 A, 8 X; 2 per arm per block |
| Lane records | 144 |
| Measured samples | 2,880 |
| Warmups | 720 |
| Oracle checks | 144 pass |
| Contention probes | 32/32 clear |
| Sources/binaries/indexes | immutable during campaign |

## Drift blocker

Arm A, `pr15d_v1/100000/rare/k100`:

| Block | Slot medians (ns) | Block median (ns) |
|---|---|---|
| 1 | 251604, 279105 | 265354.5 |
| 2 | 251104, 253904 | 252504.0 |
| 3 | 358005, 298204 | 328104.5 |
| 4 | 275604, 327105 | 301354.5 |

- Cross-block drift: `328104.5 / 252504.0 = 1.299403...`
- Fixed limit: `1.25`
- Result: `BLOCKED_DRIFT`

The same lane in X:

| Block | Block median (ns) |
|---|---|
| 1 | 253053.5 |
| 2 | 247004.0 |
| 3 | 261954.0 |
| 4 | 273804.0 |

- Cross-block drift: `1.108500...` (within limit)

## Non-blocking observations

All other arm/lane drift combinations were within their 1.25 (100K) or 1.50
(10K) caps. That does not cure the single failed gate.

## Decision

Per the predeclared protocol, a drift failure is not converted into
`X_FASTER`, `A_FASTER` or `INCONCLUSIVE`. Shared production source was left
unchanged. A fresh campaign is not authorized by this plan.
