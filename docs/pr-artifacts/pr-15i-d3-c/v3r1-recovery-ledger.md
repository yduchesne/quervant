# PR 15I-D3-C — v3-R1 recovery ledger

Status: **SCOPED HARD STOP — campaign 01 structural verification failed.**

- Pulled branch to `e633728` (owner BENCHMARKING doc), then implemented v3-R1.
- Frozen tooling commit T6-R1: `d499cb4a1c634eab9dce337c8fcd388574cf96e5`
- Receipt: `target/pr15i-d3-c/v3r1-freeze/freeze-receipt.json`
  SHA-256 `861f273c0813fe5c26afc5222603d6b80c4b09bf68c7023cc13645ceeb35318e`
- Protocol v3-R1 SHA-256:
  `ad83bcf3ac11370b7c5ea2afc162c2818287d7460f7abf6aa87afec346410c65`
- v3-R1 readiness-only: `READY`.
- Control `d3c-v3r1-base-aa-01`: 69,120 samples, verifier PASS,
  `ACQUIRED_VERIFIED`, archive
  `f6c54e1c2ecc5d856168ea12edd81ba3eb5751532fea494e1aff053cc6ed6567`,
  published.
- Campaign 01 `d3c-v3r1-strategies-01`: 138,240 samples collected, but the
  controller emitted `ACQUISITION_INCOMPLETE`; independent verifier returns
  `V_SUMMARY: summary mismatch`.
- Campaign 02 and policy: not run.

## Root cause

The frozen controller computes:

```python
structural_ok = ready["readiness_status"]=="READY" and len(set(layouts.values()))==1
```

`layouts` is keyed by corpus size (`10000`, `100000`), so it always contains
two different digest values even when all four arms share identical indexes.
The condition is never true for a campaign with two corpus sizes. Control is
unaffected because it does not set `structural_ok` this way.

Campaign evidence itself is complete, but the official status is wrong and the
independent verifier rejects the summary. This is an implementation defect in
frozen T6-R1, not timing noise. Per the freeze rules, it cannot be repaired
under the same T6 and the campaign cannot be retried or relabeled.

## Decision required

Authorize a T6-R2 tooling correction (per-corpus-size index consistency across
arms) and a new replacement v3-R1 series with fresh identities, or accept the
scoped stop. No campaign 02, series verification, nine-K policy, or closeout is
claimed.
