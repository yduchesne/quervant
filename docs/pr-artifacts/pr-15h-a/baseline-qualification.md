# PR 15H-A — pre-optimization baseline qualification

**Campaign directory:** `target/pr15h-a/baseline-01` (ignored raw evidence)
**Sealed raw files:** `authorization.json`, `manifest.json`,
`raw/trial-01.json`..`raw/trial-03.json`
**Seal file SHA-256:** `993c6822c12225519694bc90795606348fb7e2e29e8840f911f74f2714b27ada`
**Sanitized report SHA-256:** `c4d7f9181ce60a54ca95d951ad0465ad49ed249bc25256d3b4bed4bb9428eddf`

## Chronology (baseline strictly before production edits)

1. `HA-HARNESS` committed (`9958624…`).
2. Preflight/design docs committed (`f405ac0…`).
3. Baseline campaign executed against a clean detached worktree at
   `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078` and sealed.
4. `--verify-only` re-hashed the seal and reproduced the sanitized pair.
5. Only then was the production candidate committed (`dce8f024…`).

No Rust production file was modified before step 3 completed.

## Acquisition facts

| Fact | Value |
|---|---|
| Baseline source SHA | `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078` |
| Tooling SHA at acquisition | `f405ac008579eabbcf430f32e43302b884cea58e` |
| Frozen corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Trials | 3 (`raw/trial-01`..`03`) |
| Samples per lane per trial | 20 (nearest-rank `median`/`p95`/`p99`) |
| Warmups per lane | 5 |
| Contention probes | 3 trials x before/after = 6, all `clear` |
| Native filesystem | ext4 |

## Seven-lane baseline (median-of-three-trial medians)

| Lane | Trial medians (ns) | Median-of-medians (ns) |
|---|---:|---:|
| `pr15d_v1/100000/medium/k100` | 23357837, 22460742, 22105546 | 22460742 |
| `pr15d_v1/100000/common/k100` | 57370126, 56788263, 56298977 | 56788263 |
| `pr15d_v1/100000/common/k10` | 44495420, 43757112, 44251952 | 44251952 |
| `pr15d_v1/10000/common/k100` | 5124283, 5137995, 5111376 | 5124283 |
| `pr15d_v1/10000/rare/k100` | 53200, 49201, 51101 | 51101 |
| `pr15d_v1/100000/rare/k100` | 266104, 257704, 265704 | 265704 |
| `pr15d_v1/100000/absent/k100` | 303805, 262003, 256504 | 262003 |

## Qualification result

`BASELINE_QUALIFIED`. Corpus, index digests and source identity are sealed and
were reused read-only by the paired campaign.
