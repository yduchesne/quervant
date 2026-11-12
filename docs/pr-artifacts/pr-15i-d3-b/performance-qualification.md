# PR 15I-D3-B — performance qualification

**Status: `NOT_RUN` for both paired campaigns; overall `D3B_MEASUREMENT_BLOCKED`.**

No paired campaign (`d3b-base-01`, `d3b-base-02`) was executed. The mandatory
A/A control (`d3b-base-aa-01`) was structurally invalid because its two BASE
arms produced different adapter binaries from two different worktree paths, even
though every numerical A/A ratio and every drift check passed. Plan decision
rule `DBX-31` stops the series on a control structural failure, and `DBX-30`
permits a retry only for a purely numerical A/A failure. Therefore:

- No A/B timing exists, and no gate (`D3B-P01`–`D3B-P06`) can be evaluated.
- No speed-up or regression is claimed for any lane, including K10 and the
  10K/100K absent and rare lanes.
- The D3-A-F2 sampled `candidate_duplicate` shares remain a diagnostic
  hypothesis only; they are not converted into an end-to-end claim.
- The D1-C1 and D1-F C2 rejections are unaffected and were not re-used.

## What would be required for a future, separately authorized attempt

A control that produces identical BASE binaries from two isolated build
namespaces while preserving the frozen source-locked protocol. That needs an
explicitly reviewed build-reproducibility decision (for example a
`--remap-path-prefix` or same-path build policy) and a new protocol/tooling
freeze; neither is authorized by this plan. No threshold may be relaxed and no
alternative algorithm may be introduced.

## Evidence preserved

- `d3b-base-aa-01` sealed campaign and independent verifier receipt.
- Archived evidence with SHA-256 sidecar (see `evidence-index.md`).
- The blocker diagnosis in `a-a-control.md`.
