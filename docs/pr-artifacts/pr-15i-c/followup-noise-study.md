# PR 15I-C follow-up — A/A and A/G measurement-noise study

Status: **`15IC_NOISE_DIAGNOSTIC_BLOCKED`** — the source-neutral A/A criterion
failed, so the A/G diagnostic could not be interpreted and no operator was
restored.
Protocol: `benchmarks/pr15i_c/noise_protocol_v2.json` (`pr15i-c-noise-v2`),
authored and committed **before** the first v2 sample.

## 1. What was measured

| Item | Value |
|---|---|
| Study type | `AA_IDENTICAL_EXECUTABLE` (4 campaigns) and `AG_OUT_OF_LINE_GENERIC` (4 campaigns) |
| Baseline A | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` (merged PR 15I-B) |
| Generic control G | `50b56e9fe7b22bb266ca7b0d9e209500dfc785ff` (historical F0 control, one `#[inline(never)]`) |
| Lanes | the seven frozen PR15D warm lanes in the fixed order |
| Schedule | 8 paired blocks `ABBA BAAB BAAB ABBA BAAB ABBA ABBA BAAB`, 32 slots per campaign |
| Per lane per slot | 5 warmups + 10 measured samples |
| Per campaign | 2 240 measured samples, 1 120 warmups, 12 freshly rebuilt index directories |
| Series | fixed interleaved order `aa-01, ag-01, aa-02, ag-02, aa-03, ag-03, aa-04, ag-04` |
| Totals | 17 920 measured samples, 8 960 warmups, 96 remeasured rebuilds |
| Contention | `clear` before and after all 256 slots (independently enforced) |
| Host/toolchain | one host fingerprint and one `rustc 1.98.1` for all eight campaigns |

A/A semantics: both logical arms executed the **same release adapter file**
(`executed_binary.A.path == executed_binary.B.path`, identical SHA-256, verified
before and after each campaign; 12 rebuild directories still produced). A/G
semantics: two immutable release adapters, A and G.

## 2. Per-campaign lane medians (independently re-derived from sealed raw)

### A/A (identical executable)

| Lane | aa-01 | aa-02 | aa-03 | aa-04 | Aggregate | In band [0.90,1.10] |
|---|---|---|---|---|---|---|
| 10K absent/k100 | **0.8496** | 0.9677 | 0.9987 | 1.0007 | 0.9832 | **NO** |
| 10K rare/k100 | 1.0262 | 0.9811 | 1.0235 | 0.9541 | 1.0023 | yes |
| 10K common/k100 | 1.0055 | 1.0119 | 0.9932 | 0.9962 | 1.0008 | yes |
| 100K absent/k100 | 1.0044 | 1.0028 | 0.9909 | 1.0010 | 1.0019 | yes |
| 100K rare/k100 | 0.9983 | 0.9978 | 0.9755 | 1.0087 | 0.9981 | yes |
| 100K common/k100 | 0.9926 | 1.0022 | 1.0012 | 0.9885 | 0.9969 | yes |
| 100K common/k10 | 1.0074 | 1.0004 | 0.9998 | 1.0046 | 1.0025 | yes |

### A/G (historical out-of-line generic boundary)

| Lane | ag-01 | ag-02 | ag-03 | ag-04 | Aggregate | Runs ≤1.05 |
|---|---|---|---|---|---|---|
| 10K absent/k100 | 1.0202 | 0.9602 | 0.9606 | 0.9589 | 0.9604 | 4/4 |
| 10K rare/k100 | 0.9855 | 0.9885 | 0.9725 | 1.0366 | 0.9870 | 4/4 |
| 10K common/k100 | 0.9885 | 0.9807 | 0.9755 | 0.9837 | 0.9822 | 4/4 |
| 100K absent/k100 | 0.9796 | 0.9651 | 0.9967 | 1.0077 | 0.9882 | 4/4 |
| 100K rare/k100 | 0.9981 | 0.9729 | 0.9895 | 1.0156 | 0.9938 | 4/4 |
| 100K common/k100 | 0.9868 | 0.9881 | 0.9865 | 0.9877 | 0.9873 | 4/4 |
| 100K common/k10 | 1.0008 | 0.9977 | 0.9992 | 0.9952 | 0.9984 | 4/4 |

Per-block ratios above 1.15 occurred in the diagnostic (e.g. aa-01 10K absent
1.176, aa-03 10K absent 1.220 and 10K rare 1.212, ag-01 10K absent 1.184,
ag-02 10K absent 1.211, ag-03 10K rare 1.175, aa-04 10K rare 1.179). Under this
study they are recorded as observations only, exactly as predeclared; the
historical F0 decision under its own stricter rule is untouched.

## 3. Predeclared criteria and outcome

| Criterion | Requirement | Observed | Result |
|---|---|---|---|
| A/A aggregate median | `0.95 ≤ AGG ≤ 1.05` for every lane | 0.9832 … 1.0025 | PASS |
| A/A every campaign median | `0.90 ≤ M ≤ 1.10` for every lane | 10K absent aa-01 = **0.8496** | **FAIL** |
| A/G aggregate median | `AGG ≤ 1.05` for every lane | 0.9604 … 0.9984 | pass |
| A/G every campaign median | `M ≤ 1.10` for every lane | max 1.0366 | pass |
| A/G runs at/below 1.05 | ≥ 3 of 4 per lane | 4/4 on every lane | pass |
| A/A must hold on the same host/toolchain | required precondition for interpreting A/G | false | **blocked** |

**Decision: `15IC_NOISE_DIAGNOSTIC_BLOCKED`.** A/A is the environment-stability
control. One of four A/A campaigns measured the *same executable bytes* as 15%
faster in the B-labelled arm on the 10K absent lane (block ratios 0.77–1.18),
so the environment is not sufficiently stable for the A/G numbers to be
interpreted as a layout effect. No operator restoration, no performance claim
and no threshold change followed (`NC-D34`).

## 4. Honest reading of the A/G numbers

The A/G aggregates are systematically at or slightly below 1.0 with 4/4 runs
≤1.05 on every lane. That is *consistent* with the out-of-line generic boundary
being neutral-to-slightly-favourable, and it is the opposite of the historical
low-match regression. It is **not** reported as a pass: the predeclared rule
requires a stable A/A baseline first, and a 15% same-binary swing in one A/A
campaign shows the 10K absent lane cannot support that inference at this sample
size.

## 5. Cross-references to the frozen acceptance contract

Nothing here waives `benchmarks/pr15i_c/protocol.json`
(SHA-256 `5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e`,
unchanged). `C-P06..C-P09` and their per-block `1.15` ceilings remain exactly as
frozen; this study is diagnostic-only and `final_feature_acceptance` is `false`
in every receipt.

## 6. Artefacts

| Artefact | Location |
|---|---|
| Sealed campaigns (8) | `target/pr15i-c/noise-diagnostics-v2/{aa,ag}-0N` |
| Individual receipts (8) | `target/pr15i-c/reviews/noise-v2-{aa,ag}-0N.json` |
| Aggregate receipt | `target/pr15i-c/reviews/noise-v2-series-aggregate.json` |
| Invalidated v1 attempt | `target/pr15i-c/noise-diagnostics/aa-01` (untouched) |
| Invalidated v2 attempt-1 campaigns | `target/pr15i-c/noise-diagnostics-v2-attempt1/` (untouched) |
| Protocol | `benchmarks/pr15i_c/noise_protocol_v2.json` |
| Tooling | `benchmarks/pr15i_c/{noise_diag,verify_noise_diag,source_proof}.py` + 60 tests |

Component seal digests (first 12 hex, full values in the aggregate receipt):
`aa-01 d02912591fee`, `ag-01 2dd15cbe6409`, `aa-02 113b7d0c8eaf`,
`ag-02 9068be834d77`, `aa-03 a6e1b8014650`, `ag-03 a8a37afacabd`,
`aa-04 85116065c799`, `ag-04 e13743bdf1db`.
