# PR 15I-D3-B-F1 — performance qualification

**Status: `NOT_RUN` for both paired campaigns. Overall `D3BF1_MEASUREMENT_BLOCKED`.**

No paired campaign (`d3bf1-base-01`, `d3bf1-base-02`) was executed. The
mandatory A/A control was executed once but could not be independently verified
because of the two post-T1 tooling defects documented in `a-a-control.md`; per
plan §4/§11 and FDX-41/44 the series stopped before any A/B timing.

- No gate (`D3B-P01`–`D3B-P06`) was evaluated.
- No speed-up, regression, K10 or low-hit claim exists.
- The D3-A-F2 sampled-child shares remain diagnostic and are not converted into
  an end-to-end claim.
- The controller's `CONTROL_QUALIFIED` is **not** an accepted result; the
  independent verifier is the authority and it did not return `PASS`.

## What the control did show (diagnostic only)

The numerical A/A ratios (0.9323–1.0019 medians) and drift were inside the
frozen bounds; the two BASE binaries were byte-identical; the 100K indexes were
byte-identical and matched the sentinels. This supports the canonical build
design but is **not** performance evidence and cannot be promoted.

## What is required for a future attempt

A separately authorized F1.1 tooling freeze fixing the two defects, followed by
a fresh `d3bf1-base-aa-01` control and, only if it independently verifies and
qualifies, the two paired campaigns. No threshold may be relaxed, no evidence
may be reused, and no alternative algorithm may be introduced.

## Preserved evidence

- Local sealed campaign `target/pr15i-d3-b/fixup-f1/d3bf1-base-aa-01/`
  (`SAME_DISK_ONLY`), including the non-timed dry proof and both build events.
- Independent verifier failure receipts (reproduced in `a-a-control.md`).
- No archive exists because `publish` requires independent verification `PASS`.
