# D2 isolation harness fixup — design verification

## Implementation seams

| Seam | Change |
|---|---|
| `isolate_d2.py` source proof | `_git_bytes`, `_diff_edits`, `_assert_exact_d2_edits`; explicit two-state diff parser; per-file counts 15/0 and 43/1 |
| `validate_source_identity` | A pin, single parent, two-file allowlist, exact edit streams, no D1 symbols, D2 branch/counter witnesses |
| `prepare` | fixed `START_HEAD=317d60d`; strict allowed-path set; clean checkout; production diff exit status checked explicitly |
| `validate_raw` | 20 positive non-bool samples; frozen `summarize` exact six-field match; manifest/slot identity; descriptor, warmup and oracle checks |
| Acquisition | existing 4x4 loop unchanged; final source proof then raw validation then seal |
| Seal | v2 schema, exactly two metadata files plus 16 slots, hashes from on-disk bytes, exclusive create |
| Drift | `compute_drift_diagnostics` returns diagnostics and ordered violations without raising; `drift_report` remains the raising helper |
| Blocked output | `blocked.json` / `blocked.md`, no performance table or gate result |
| Qualified output | existing `confirmation.json` / `performance.md` |
| Verify-only | strict seal schema/keys, hash every sealed file, recompute validation and drift, byte-compare the correct report pair |

## Frozen summary semantics

For 20 samples sorted 1..20, frozen nearest-rank output is:

```json
{"count": 20, "median": 10, "p95": 19, "p99": 20, "min": 1, "max": 20}
```

The arithmetic median `10.5` is deliberately rejected. Block medians still
combine two slot medians with `(m1 + m2) / 2.0`.

## Report ownership

- Drift violation: only blocked pair; no `X_FASTER`, `A_FASTER`,
  `INCONCLUSIVE`, `DX-P01` or `DX-P02`.
- No drift violation: only qualified pair; gates retain original meanings.
- Verify-only never writes.

## Test coverage added

- Literal schedule and 16-slot balance.
- Sample count/type, nearest-rank summary, tampered median/p95/missing field.
- Manifest identity and warmup checks.
- Block median arithmetic, four-ratio verdicts, drift boundaries and violations.
- Gate acceptance/rejection and guardrail blocking.
- Blocked report shape, sanitizer and canonical rendering.
- Real-filesystem sealed blocked/qualified verify-only, tampered slot/report,
  legacy unsealed refusal.
- Real local A/X exact-edit proof and per-file edit counts.
