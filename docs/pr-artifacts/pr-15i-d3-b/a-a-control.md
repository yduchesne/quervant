# PR 15I-D3-B — A/A control `d3b-base-aa-01`

**Result: `MEASUREMENT_BLOCKED` (structural A/A binary-identity failure).**
The numerical A/A stability policy passed for all nine lanes and the drift
policy passed, but the two BASE arms produced **different adapter binaries**.
Per plan §9.3 and decision rule `DBX-31`, a control with a structural identity
failure blocks measurement: no paired campaign was run and no performance
verdict is claimed.

## Attempt identity

| Item | Value |
|---|---|
| Campaign | `d3b-base-aa-01` |
| Kind | control (same-source A/A) |
| BASE / both arms | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Tooling freeze (T0) | `155ebafafa29fb0e6b6cbf953f89445f4880fd2f` |
| Protocol SHA-256 | `8c113091507528450f9dd8f406fc3ac0a390c164b9a7a603583f48d752c6d1be` |
| Tooling manifest SHA-256 | `d1dd3decbe3f96c18190cf48d28c28b8aab926baea1b9d77d1b2a18c7722dd10` |
| Host fingerprint | `c8524a7281e0cff89adf8271995fd4c7597a9d9b9a0a90c0fcf85a5b1d221f44` |
| Started / ended (UTC) | `2026-11-12T03:20:15Z` / `2026-11-12T03:22:35Z` |
| Slots / lane records | 16 / 144 |
| Timed samples / warmups | 2,880 / 720 |
| Contention probes | 32, all `clear` |
| Drift | `PASS`, zero violations |
| Numerical A/A | `passes = true` for all nine lanes |

## Structural failure

| Arm | Source | Binary SHA-256 | Bytes |
|---|---|---|---|
| A (`sources/base`) | `39dbd9f5…` | `cdc434c8ba2691a0636c7dbb03018f8a8e2a4f31d85ce102359c806cff44634c` | 4,478,176 |
| B (`sources/control-base`) | `39dbd9f5…` | `d0847853c0bbe62060a4fcd4b3e7a2350f9130f86ae9e18fb9d720ccb693a089` | 4,478,656 |

The manifest records the disclosed `control_binary_mismatch`; the independent
verifier accepts the campaign as verifiable but recomputes
`MEASUREMENT_BLOCKED`.

### Diagnosis (non-timed, not evidence for a performance verdict)

The two arms were built from **different Git worktree paths**
(`.../sources/base` and `.../sources/control-base`) with otherwise identical
source, lock file and toolchain. A dry rebuild of the same source path into two
different target directories produced byte-identical binaries
(`cdc434c8…`, 4,478,176 bytes), while the second worktree path produced
`d0847853…` (4,478,656 bytes; `.text` 1,170,288 vs 1,170,032 bytes). The
difference is therefore the absolute source path embedded by the Rust build,
not a source, dependency or feature difference: Cargo's per-package metadata
hash depends on the path package source id.

The plan prescribes two isolated BASE worktrees for the A/A control and
simultaneously requires identical binary digests. This environment cannot
satisfy both; no build-flag remapping or tooling change is authorized
(`DBX-28`, `DBX-48`). A second control attempt is not permitted because the
failure is structural, not numerical (`DBX-30`), and `DBX-31` stops the series.

### Index identity (structural checks that did pass)

| Corpus | Committed bytes | STORED bytes | Digest (both arms) |
|---|---:|---:|---|
| 10K | 1,560,111 | 166,369 | `3840f8ba8e44717e…` |
| 100K | **15,747,551** | **1,661,455** | `5734ae60591f7563…` |

Both arms share byte-identical index digests and the frozen 100K sentinels; the
corpus manifest is the frozen
`69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.

## Numerical A/A ratios (diagnostic only; never a performance claim)

Block value = floor of the two slot medians; ratio = B/A; lower median of four
blocks.

| Lane | Main | Block ratios | Median | Pass |
|---|---|---|---|---|
| `pr15d_v1/10000/absent/k100` | 0.9936 | 1.0164, 0.8747, 0.9936, 1.1643 | 0.9936 | yes |
| `pr15d_v1/10000/rare/k100` | 1.0969 | 1.2436, 0.8289, 1.1015, 1.0969 | 1.0969 | yes |
| `pr15d_v1/10000/medium/k100` | 0.9897 | 0.9897, 1.0192, 0.9689, 1.0239 | 0.9897 | yes |
| `pr15d_v1/10000/common/k100` | 0.9831 | 0.9926, 0.9576, 0.9831, 1.0082 | 0.9831 | yes |
| `pr15d_v1/100000/absent/k100` | 0.9380 | 0.9541, 1.0063, 0.9116, 0.9380 | 0.9380 | yes |
| `pr15d_v1/100000/rare/k100` | 0.9790 | 1.0317, 0.9462, 0.9790, 1.0509 | 0.9790 | yes |
| `pr15d_v1/100000/medium/k100` | 0.9814 | 1.0144, 0.9781, 1.0251, 0.9814 | 0.9814 | yes |
| `pr15d_v1/100000/common/k100` | 0.9932 | 0.9967, 0.9932, 0.9919, 0.9934 | 0.9932 | yes |
| `pr15d_v1/100000/common/k10` | 0.9915 | 0.9813, 0.9951, 0.9924, 0.9915 | 0.9915 | yes |

## Evidence

- Sealed campaign: `target/pr15i-d3-b/d3b-base-aa-01/` (57 sealed members plus
  `verification.json`).
- Independent verification: `PASS`, `campaign_status = MEASUREMENT_BLOCKED`,
  `a_a_passes = true`, `member_count = 57`.
- Archive: `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b/d3b-base-aa-01.tar.gz`,
  SHA-256 `563a5cf02674dacd71286796dcffcb0760098a0adec8db5434edbd60b3d973fc`,
  59 members, exclusive create, extraction and full re-hash round-trip
  (0 mismatches), sidecar `d3b-base-aa-01.tar.gz.sha256`.
