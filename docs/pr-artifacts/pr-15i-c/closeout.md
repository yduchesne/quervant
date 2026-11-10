# PR 15I-C — Final closeout (performance rejected)

**Disposition:** `REJECTED — PERFORMANCE`; original final experiment:
`F_GENERIC_BOUNDARY_REJECTED`. **Production:** safely restored to merged
PR 15I-B baseline `6f6463cb26bcf28340cc9d4afd4dfeb040281898`.
**Delivery:** no PR 15I-C optimization merged, released or accepted.

## Scope and closure decision

PR 15I-C investigated a postings-driven, single positive exact-term physical
executor intended to improve exact count and top-K under explicit ascending
Keyword sorting. Candidate implementations and layout experiments improved
common-match workloads but repeatedly violated absent/rare-query guardrails.
The final approved experiment failed the generic-path neutrality gate before
constructing a release candidate. This optimization direction is **retired**;
new implementation work requires a separate human-approved plan.

## Final evidence

| Low-match lane | F diagnostic G/A aggregate | Status |
|---|---:|---|
| 10K absent/K100 | 1.4382 | REJECT |
| 10K rare/K100 | 1.3568 | REJECT |
| 100K absent/K100 | 1.7737 | REJECT |
| 100K rare/K100 | 1.7310 | REJECT |

The G/A neutrality contract required each unbatched campaign to remain at or
below 1.10 and each two-campaign aggregate at or below 1.05 across the nine
lanes. All four low-match lanes failed. The three common-query P/A aggregates
(0.8652, 0.8383, 0.8026) are experimental gains **not delivered in production**.

The final diagnostic used four valid campaigns (two unbatched, two batched),
128 slots, 17,280 timed observations and 256 clear contention probes. The
batched campaigns were observational; the rejection uses the unbatched gate.

## Interpretation limits

Arm G had an out-of-line generic collector and a compiled but runtime-disabled
physical collector. The physical operator's **execution** was unnecessary for
the low-match regression in this build. The experiment does **not** isolate
`#[inline(never)]` as the sole cause or establish a particular LLVM, branch,
cache or machine-code mechanism. Hardware `perf` counters were unavailable.

## Production and qualification state

The experimental branch's final production paths match accepted baseline
`6f6463cb…`; the physical operator and diagnostic runtime feature do not remain
in the final production tree. The original frozen nine-lane contract is
unchanged. `F_RELEASE` was not built, and the final frozen 16-slot campaign did
not run. Real RustFS, hosted CI and independent review were not reported as
complete for the rejected experiment. This **documentation-only closeout** does
not imply any missing feature acceptance has passed.

## Evidence provenance and retention

The authoritative historical files are on experimental commit
`6175b9681ff3b82c0b92a9306773f3d4d7e906ba` (branch
`dev/pr15i-c-postings`):

- [f-final-performance-decision.md](https://github.com/yduchesne/quervant/blob/6175b9681ff3b82c0b92a9306773f3d4d7e906ba/docs/pr-artifacts/pr-15i-c/f-final-performance-decision.md)
- [f-final-diagnostic-results.md](https://github.com/yduchesne/quervant/blob/6175b9681ff3b82c0b92a9306773f3d4d7e906ba/docs/pr-artifacts/pr-15i-c/f-final-diagnostic-results.md)
- [f-final-source-and-codegen.md](https://github.com/yduchesne/quervant/blob/6175b9681ff3b82c0b92a9306773f3d4d7e906ba/docs/pr-artifacts/pr-15i-c/f-final-source-and-codegen.md)
- [f-final-execution-status.md](https://github.com/yduchesne/quervant/blob/6175b9681ff3b82c0b92a9306773f3d4d7e906ba/docs/pr-artifacts/pr-15i-c/f-final-execution-status.md)

Experimental protocols, verification tooling and committed reports remain on
the experimental branch. Raw/receipt files under `target/pr15i-c/` are
*local-only unless independently archived*; their repository presence must not
be asserted. The original nine-lane acceptance protocol SHA-256 is
`5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e`.

## Reopening policy

No PR 15I-C continuation, threshold change, code-placement rewrite, codec
change or performance claim is authorized. A new experiment requires a new
human-approved design, explicit immutable gates and genuinely new diagnostic
evidence. Separate future reader/field-norm work is not part of this closeout.
