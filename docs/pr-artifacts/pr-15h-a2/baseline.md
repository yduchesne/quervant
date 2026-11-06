# PR 15H-A2 — pre-optimization baseline

**Campaign:** `target/pr15h-a2/baseline-01` (inside the immutable tooling
checkout; ignored raw evidence)
**Seal SHA-256:** `14836343626f35642e2eae472aac47af73b8b567f99811ea3d50d8e5ddebf2ec`
**Sanitized report SHA-256:** `dee2033b707ab046d9fc86e7b9c4e53ce70b90b568700f141bcbe5aa4e5947ae`

## Chronology

1. A2 harness-only commit `9aff92b` (`H_A2_TOOLING_SHA`).
2. Preflight/provenance docs `eb0a363`.
3. Detached tooling checkout at `9aff92b`; detached base worktree at `7a136f7`.
4. Baseline campaign executed from the tooling checkout and sealed.
5. `--verify-only` rehashed the seal and reproduced the sanitized pair.
6. Only then was the A2 candidate `569132d` committed and measured.

## Acquisition facts

| Fact | Value |
|---|---|
| Baseline source | `7a136f7f299c2f460401b9d92dcef37d219ea98c` |
| Tooling | `9aff92b6b1a12ee323ed7994a177f88949c736fd` |
| Frozen corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Trials / samples / warmups | 3 × 20 / 5 per lane |
| Baseline samples | 420 |
| Contention probes | 6, all `clear` |
| Native filesystem | ext4 |

## Seven-lane baseline (median-of-three trial medians)

| Lane | Trial medians (ns) | Median-of-medians (ns) |
|---|---:|---:|
| `pr15d_v1/100000/medium/k100` | 23250745, 22125636, 22101111 | 22125636 |
| `pr15d_v1/100000/common/k100` | 56793139, 57561670, 56209203 | 56793139 |
| `pr15d_v1/100000/common/k10` | 43941547, 44070163, 43900315 | 43941547 |
| `pr15d_v1/10000/common/k100` | 5066074, 5152877, 5074971 | 5074971 |
| `pr15d_v1/10000/rare/k100` | 47700, 49101, 53201 | 49101 |
| `pr15d_v1/100000/rare/k100` | 270604, 273904, 254703 | 270604 |
| `pr15d_v1/100000/absent/k100` | 284804, 262004, 250505 | 262004 |

Qualification: `BASELINE_QUALIFIED`.
