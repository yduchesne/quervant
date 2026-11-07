# PR 15H-C — corrigendum: paired statistic and sealed-report labels

**This is documentation/label clarification only.** No C timing was rerun, no C
gate or threshold changed, and the rejected C candidate was not resurrected.

## Statistic

The frozen PR 15H-C contract explicitly prescribes the **nearest-rank lower
median of four paired deltas** (`sorted(d)[1]`) for gating. The controller and
all C gate outcomes are therefore unchanged.

| Lane | Four deltas (ms) | Lower median (gating) | Conventional median (informational) |
|---|---|---:|---:|
| P1 common/100K/K100 | −4.480, −4.273, 1.059, −1.642 | −4.273 | −2.9575 |
| P2 common/100K/K10 | −4.241, −0.954, 2.601, 1.644 | −0.954 | +0.3450 |
| P3 medium/100K/K100 | −5.891, −4.067, 5.397, 0.583 | −4.067 | −1.7420 |
| G1 common/10K/K100 | −0.947, −0.822, 0.281, −0.293 | −0.822 | −0.5575 |
| G2 rare/100K/K100 | −0.052, 0.001, 0.062, −0.037 | −0.037 | −0.0180 |
| G3 absent/100K/K100 | −0.037, −0.020, 0.035, −0.026 | −0.026 | −0.0230 |

The conventional median is **informational only**. Using it would not preserve
the frozen C contract, and it is not substituted into the C gate table. The
derived values above are reproducible from the four deltas in the nonsealed
`performance.md`; the raw sealed samples remain authoritative.

## Sealed sanitized label

The original sealed C sanitized Markdown (`target/pr15h-c/paired-01/sanitized/
performance.md`, SHA-256 `0bdae64ee30c4a8408b74dae0a6ea3dd6f61567780ec47049d1e6b2f6322d6fb`
for the JSON) and the baseline Markdown were mechanically copied from 15H-B and
retain the historical "PR 15H-B" title. **Their bytes are preserved unchanged**;
the source/tooling SHAs, six lanes and seals inside them are C-specific.

The corrected human-facing view is `docs/pr-artifacts/pr-15h-c/performance.md`
and `benchmark-baseline.md`, which label the work as PR 15H-C and distinguish the
lower from the conventional statistic. No sealed raw JSON/CSV/manifest was
modified.

## Controller test

`benchmarks/pr15h_c/test_run.py::CMedianClarificationTests::
test_hc_median_lower_vs_conventional` asserts both statistics for all six lanes,
including P2 where their signs differ.
