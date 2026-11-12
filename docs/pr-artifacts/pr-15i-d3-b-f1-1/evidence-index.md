# PR 15I-D3-B-F1.1 — evidence index

## Published archives

Root: `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1-1/`

| Archive | SHA-256 | Members | Verified status |
|---|---|---:|---|
| `d3bf11-base-aa-01.tar.gz` | `f58ef556a50ea08ac8feb1b5c724276e8eb7f0626113c7a543d28c762de8c060` | 61 | `CONTROL_QUALIFIED` |
| `d3bf11-base-01.tar.gz` | `69c45bc40534af30161179147cfa957909c20a1113362a671ece3b940836fcc5` | 63 | `MEASUREMENT_BLOCKED` (drift; preserved, not a verdict) |

Both have exclusive `.sha256` sidecars written by `publish`; archives exclude
`build/`, `indexes/`, `corpus/` and `compile-source/`, and each was extracted and
fully re-hashed before the sidecar was written. No synthetic rehearsal archive
exists.

## Local scratch (`SAME_DISK_ONLY`, not archives)

| Path | Contents |
|---|---|
| `target/pr15i-d3-b/fixup-f1-1/preflight-01.json` | source/host/corpus identity, changed-path allowlist, protocol/tooling digests |
| `target/pr15i-d3-b/fixup-f1-1/sources/{base,control-base,candidate}` | detached identity worktrees (never compile paths) |
| `target/pr15i-d3-b/fixup-f1-1/rehearsal/round-01` | failed rehearsal attempt (harness R02 reseal bug), partial, preserved |
| `target/pr15i-d3-b/fixup-f1-1/rehearsal/round-02` | failed rehearsal attempt (harness R09 overwrite bug), partial, preserved |
| `target/pr15i-d3-b/fixup-f1-1/rehearsal/round-03` | successful `SYNTHETIC_REHEARSAL_VERIFIER_PASS`, `replay-report.json` |
| `target/pr15i-d3-b/fixup-f1-1/d3bf11-base-aa-01` | complete sealed control with `compile-source`, builds, indexes, raw evidence and sanitized summary |
| `target/pr15i-d3-b/fixup-f1-1/d3bf11-base-01` | complete sealed paired campaign (structurally blocked) |
| `target/pr15i-d3-b/fixup-f1-1/d3bf11-base-02` | does not exist (not authorized) |

## Key digests

| Artifact | SHA-256 |
|---|---|
| F1.1 protocol | `ae1b7d8d9ab638e70cddb1e52d0b9dd063ccdffae74826ab67728db42a095b4c` |
| F1.1 tooling manifest | `f9134926cbe372b628f6248aa7f846a52455ebaedaa6b2a741f402796295e250` |
| Control build provenance | `3696f404619bee80970adc7741ea5a509c08b56e80597e81c0e345699d924485` |
| Control host attestation | `efda5a3f2e21b9e937fda4372bc513509de01fdacfc0f1f2fa6760d31318266d` |
| Paired-01 build provenance | `46b90dbd10377b5e9180d918343fcc5f74c7d1d6b0fcbd1d50216b6747827160` |
| Paired-01 host attestation | `18ecc9b9b0457a9b5019e4b67e1ade37ce69a089542d1d8c8b016a2c532ad94b` |
| Rehearsal original inventory | `d5511aec2f2d2546e83a728a08872ea6103e8c7c37db6105361eed406e86ff88` |

## Historical evidence (unchanged)

- D3-B v1 archive `563a5cf0…` (59 members) and its sidecar untouched.
- Original F1 blocked control untouched; no receipt, archive or reclassification
  was added to it.
- Rehearsal copies are labelled `rehearsal_only` and cannot be published.
