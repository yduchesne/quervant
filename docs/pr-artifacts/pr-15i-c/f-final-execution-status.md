# PR 15I-C-F — execution status

**Status: COMPLETE (diagnostic negative), production rolled back.**
Disposition: `F_GENERIC_BOUNDARY_REJECTED`.

## 1. What was executed

| Stage | Outcome |
| --- | --- |
| §2 preflight | PASS — clean tree, protected paths identical, `fmt`/`check` green, 382 `pr15i_c` tests, frozen protocol unchanged |
| §3 invariant traceability | `f-final-invariant-traceability.md` |
| §4 `F_DIAG` | commit `5f74bb691420673bde1181603d0a19a8a4114ec8` — `CAUSAL_PARENT` + one `#[inline(never)]` + prescribed `n_u34` update |
| §6 correctness at `F_DIAG` | 16 unified-module tests and 12 `pr15i_c_physical` tests passed on the diagnostic source |
| §8.2–8.5 tooling | protocol + controller + verifier + source proof + 117 tests, re-frozen after two pre-sampling and one post-sampling tooling defect (attempts preserved as `INVALID`) |
| §8.6 campaigns | all four run in the frozen order; 128 slots, 17 280 timed observations, 276 480 executed queries, 72 fresh builds, 256 clear contention probes |
| §8.5 gates | A/A stable; C reproduced on all eight low-match cells; **G neutrality failed on four of nine lanes in both unbatched campaigns** |
| §5 `F_RELEASE` | not built (gate failed) |
| §7 frozen campaign | not run (gate failed) |
| §11 rollback | production byte-identical to `6f6463cb…`; physical test file removed |

## 2. Frozen references

| Item | Value |
| --- | --- |
| Frozen PR 15I-C protocol | `benchmarks/pr15i_c/protocol.json` → SHA-256 `5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e` (unmodified) |
| F diagnostic protocol | `benchmarks/pr15i_c/f_final_protocol_v1.json` → SHA-256 `5ca968c2e8f6cbfbca88357651d66a1cacace3b45def3ad25fefc1d0228a7dba` |
| Baseline | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| Historical candidate | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` |
| F diagnostic | `5f74bb691420673bde1181603d0a19a8a4114ec8` |
| Tooling (final) | `89244ece550618ae562a06fbb4b6747b5d1f2743` campaign run; `45dd538a14faf1696e971efdaa09a8ff6bde7a38` rollback + documentation |
| Campaign schedule | `ACGPPGCA / PGCAACGP / GCPAPACG / CPAGGACP` (balanced, unchanged) |
| Corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |

## 3. Key numbers

Aggregate over the two unbatched campaigns (mean of campaign medians), frozen
ceilings `≤ 1.05` aggregate / `≤ 1.10` per campaign:

| Lane | C/A | G/A | P/A | P/G |
| --- | --- | --- | --- | --- |
| `10000/absent` | 1.5204 | **1.4382** | 1.4212 | 0.9941 |
| `10000/rare` | 1.5015 | **1.3568** | 1.4291 | 1.0435 |
| `100000/absent` | 1.7926 | **1.7737** | 1.7291 | 0.9679 |
| `100000/rare` | 1.7334 | **1.7310** | 1.6970 | 0.9930 |
| `10000/common` | 0.9812 | 1.0057 | 0.8652 | 0.8575 |
| `100000/common` | 1.0159 | 0.9982 | 0.8383 | 0.8459 |
| `100000/common/k10` | 1.0403 | 1.0264 | 0.8026 | 0.7731 |

A/A drift medians stayed within 0.9455–1.0587 with at most one outlier block per
lane, so the evidence is valid and the failure is a genuine numerical result,
not noise.

## 4. Interpretation boundary

The generic boundary alone reproduces the low-match regression; the physical
operator is not required for it and does not recover those lanes. No
instruction-level, cache or cycle attribution is claimed (`PERF_UNAVAILABLE`).
The frozen PR 15I-C acceptance criteria remain unmet, and this experiment does
not authorize another attempt on this axis.

## 5. External status

`REAL_RUSTFS_BLOCKED` (no pinned RustFS runtime reachable),
`HOSTED_CI_PENDING`, `INDEPENDENT_REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`,
`PERF_UNAVAILABLE`.
