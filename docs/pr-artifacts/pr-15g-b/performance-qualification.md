# PR 15G-B performance qualification

**Status:** `PERFORMANCE_QUALIFIED` (GB-P01–P05 PASS)
**Measured arm A:** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c` (shared-branch pre-B)
**Measured arm B:** `4e7949ad12236a0feeee671c6221119b8a998cc7` (B implementation/tests)
**Campaign stage root:** `target/pr15g-b/qualified-pair-4e7949a-20261104T0648Z/`

## Provenance and qualification

- Operator instructed the agent to assume the host idle and authorized
  `--idle-confirmed`; this is recorded as `OPERATOR_ASSUMED_IDLE`, not as an
  independently proven idle measurement.
- Actual repository probes reported `clear` before, between and after the trials:
  initial CPU busy fraction `0.0092`, between-arm `0.0062`, zero competing
  processes, and every one of the six arm-trials reported `clear` before/after.
- Same host: WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, Intel i7-10750H,
  12 logical CPUs, native `ext4`, Rust/cargo 1.98.1, Python 3.12.3.
- Frozen corpus manifest SHA-256:
  `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.
- Both arms produced identical deterministic index digests:
  - 10K: `595b7783406d7bfbd9505e393ed355716c35b3cbee5d6d53c4ae1b8bfb062b77`
  - 100K: `fd60b53fcfa1191f7a9b96602cf0aae2c1ebc7986608ed74bc7533ac59369995`
- 5 warmups + 20 samples per lane/trial, 3 trials per arm, nine warm lanes.
- Exact oracle hit counts matched for every lane/arm; all six trials qualified.

## Results

| Lane | A median (ns) | B median (ns) | B/A | Improvement | Paired trial ratios | Verdict |
|---|---:|---:|---:|---:|---|---|
| 10K absent/K100 | 65,450 | 40,852 | 0.624 | +37.6% | 0.894, 0.692, 0.624 | B_FASTER |
| 10K rare/K100 | 2,413,854 | 50,447 | 0.021 | **+97.9%** | 0.023, 0.020, 0.022 | B_FASTER |
| 10K medium/K100 | 4,142,455 | 2,069,000 | 0.499 | +50.1% | 0.499, 0.511, 0.528 | B_FASTER |
| 10K common/K100 | 6,921,109 | 5,108,900 | 0.738 | +26.2% | 0.726, 0.715, 0.765 | B_FASTER |
| 100K absent/K100 | 394,167 | 245,600 | 0.623 | +37.7% | 0.659, 0.570, 0.644 | B_FASTER |
| 100K rare/K100 | 24,971,502 | 250,800 | 0.010 | **+99.0%** | 0.011, 0.010, 0.010 | B_FASTER |
| 100K medium/K100 | 44,362,603 | 21,237,364 | 0.479 | +52.1% | 0.470, 0.480, 0.463 | B_FASTER |
| 100K common/K100 | 77,830,598 | 54,841,216 | 0.705 | +29.5% | 0.717, 0.703, 0.698 | B_FASTER |
| 100K common/K10 | 65,892,180 | 41,844,385 | 0.635 | +36.5% | 0.575, 0.653, 0.643 | B_FASTER |

**Supplementary aggregate only:** geometric mean of the nine per-lane median
ratios = `0.265010`, equivalent to a `3.773×` A/B speedup or `73.50%` lower
median latency. This aggregate does not replace any GB-P gate.

## Binding gates

| Gate | Status | Evidence |
|---|---|---|
| GB-P01 100K rare/K100 B_FASTER | PASS | ratio 0.010, all paired ratios < 1.0 |
| GB-P02 10K rare/K100 B_FASTER | PASS | ratio 0.021, all paired ratios < 1.0 |
| GB-P03 zero other-lane A_FASTER | PASS | all nine lanes `B_FASTER` |
| GB-P04 oracle/count/index/host/trial qualification | PASS | exact hits, identical digests/fingerprint, six clear trials |
| GB-P05 full reporting | PASS | this table + sanitized artifacts |

## Artifacts

| Artifact | SHA-256 |
|---|---|
| `target/pr15g-b/qualified-pair-4e7949a-20261104T0648Z/comparison.json` | `bfda587999b6114686eb5433c0dcb6c132d6a24d99c9372849ab919892fb01ea` |
| `.../comparison.md` | `257ad15b15178613b08ca00cb68d178f000bbb16d8c4864493c0f33eb9114589` |
| `.../qualification-summary.json` | `f681f16883055b2f97ac9092975b46b4ea67101d1e0c11edb2e9e67323bfd63c` |
| Raw samples/contention/setup | `.../runs/{sha}/{run-id}/` |

## Interpretation and limits

- The two primary rare lanes improve by roughly 48× (10K) and 100× (100K),
  consistent with removing repeated full STORED/DOC_KEYS traversal.
- Medium/common/high-hit lanes improve by roughly 26–52% in this campaign.
- Absent lanes also improved consistently; they are guardrails, not the target
  mechanism, and the runner measures whole-query behavior rather than attributing
  that improvement to a specific code path.
- Cold first selective access still performs one full validation scan; this warm
  nine-lane protocol does not claim cold-query improvement, reopen speed,
  index-size reduction or Tantivy parity.
- One host, one campaign; no samples/lanes were excluded.
