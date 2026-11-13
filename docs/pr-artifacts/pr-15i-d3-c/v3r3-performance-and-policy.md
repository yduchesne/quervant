# PR 15I-D3-C v3-R3 — official acquisition and provisional performance

Status: **three official campaigns acquired, independently verified and
published; full series structurally verified. Formal nine-K policy is
BLOCKED by incomplete CI/policy tooling.**

- Protocol SHA-256: `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`
- T6-R3 commit: `44ccd9e027071cf12777610abae5e6ab5f03177f`
- Receipt SHA-256: `05c7a677fbb7e3e808efd098670e561cb9be41cc72af668572f21d23a7144e93`
- Source BASE/experiment: `39dbd9f…` / `3ad6c51…`

| Campaign | Samples | Verifier | Archive SHA-256 |
|---|---:|---|---|
| `d3c-v3r3-base-aa-01` | 69,120 | PASS / ACQUIRED_VERIFIED | `e02ff5661ecb12d76cddedfd701decdbc4004a7e6c16a40ae09a53733a409ba6` |
| `d3c-v3r3-strategies-01` | 138,240 | PASS / ACQUIRED_VERIFIED | `721e1f543e2a8f0b9b13e2894c22676e7e400ea2568e4a2de7976c28daa2f87e` |
| `d3c-v3r3-strategies-02` | 138,240 | PASS / ACQUIRED_VERIFIED | `72391496dd1d458ba39fb0e347f0446048878ae4180d4cb087f41e788efa3444` |

Full series verification: `verification=PASS`, `full_series=true`,
`provenance_consistent=true`.

## Provisional point estimates (median of lane P/A and H/A ratios)

All 72 lanes retained at least four blocks in both campaigns. Values below are
medians over the eight lanes for each K; they are **not** the formal
CI-gated policy.

| K | P/A camp01 | P/A camp02 | H/A camp01 | H/A camp02 |
|---:|---:|---:|---:|---:|
| 1 | 1.0104 | 1.0154 | 1.0151 | 1.0140 |
| 10 | 1.0031 | 1.0021 | 1.0019 | 1.0069 |
| 32 | 0.9800 | 0.9751 | 0.9763 | 0.9751 |
| 64 | 0.9511 | 0.9366 | 0.9586 | 0.9455 |
| 100 | 0.9143 | 0.9128 | 0.9174 | 0.9331 |
| 128 | 0.9011 | 0.9018 | 0.9048 | 0.9218 |
| 256 | 0.8217 | 0.8454 | 0.8422 | 0.8476 |
| 512 | 0.7998 | 0.7977 | 0.8060 | 0.8001 |
| 1024 | 0.7715 | 0.7603 | 0.7768 | 0.7694 |

Provisional interpretation only: K=1/10 show no meaningful gain; K=32 is at the
3% primary boundary; K>=64 shows consistent P/H gains, with P marginally ahead
of H. Exact selection requires the paired-block CIs and the v3 policy evaluator.

## Blocker

`analysis_v3.py` emits retained/filtered point estimates but does not emit the
required paired 10,000-draw CIs, and `policy.py` still contains v2/4-block
decision logic. Under the frozen T6-R3 inventory these cannot be corrected
without a new freeze. No formal nine-K policy or production recommendation is
claimed.
