# PR 15I-D3-A-F2 independent review closure

Status: **P1 evidence gap closed; P2 hardening confirmed and deferred.**
Reviewer source-review disposition was `REVIEW_CHANGES_REQUESTED`; the diagnostic
finding remains provisionally supported. No T0d tooling or official evidence was
changed.

## Scope

- Frozen tooling: T0d `2c74e40d87f319c548c1f485d9b0267208311743`
- Official branch tip under review: `40fd6b92fe646f7bebe4e3076adfac9c8877696f`
- Harness: `benchmarks/pr15i_d3a_review/replay_matrix.py` (outside the frozen
  manifest-covered directory)
- Official evidence was copied into `target/pr15i-d3a/review/cases/`; originals
  were not mutated.

## Command and result

```sh
python3 benchmarks/pr15i_d3a_review/replay_matrix.py \
  --out target/pr15i-d3a/review/replay-matrix.json
# exit 0
```

## Adversarial replay matrix

| Case | Result | Verifier outcome |
|---|---|---|
| Valid five-run aggregate with run 03 lane-scoped | PASS | `D3AF2_ATTRIBUTION_QUALIFIED`, `D3A_CANDIDATE_HOTSPOT_LOCALIZED` |
| Wrong oracle doc IDs in the excluded 10K rare lane | REJECTED | `V_ORACLE` (global block) |
| Malformed P counter in the excluded lane | REJECTED | `V_SAMPLE_TYPE` (global block) |
| Swapped Q/P binary digest | REJECTED | `V_BINARY` (global block) |
| Missing sealed member | REJECTED | `V_SEAL` |
| Extra unlisted member | REJECTED | `V_SEAL` |
| Altered v3 tooling hash | REJECTED | `V_SOURCES` |
| Altered v3 protocol hash | **ACCEPTED** | `PASS` (P2 gap, see below) |
| Duplicate manifest entry | **ACCEPTED** | `PASS` (P2 gap, see below) |
| 4/5 same-run shared `candidate_duplicate` | PASS | localized |
| 3/5 same-run shared `candidate_duplicate` | NOT LOCALIZED | `D3A_CANDIDATE_STAGE_UNRESOLVED` |

The P1 requirement is met: timing-only failure in one low-hit lane is scoped,
while oracle, malformed-shape, binary, seal and tooling-integrity failures block
globally. No verifier defect was found in the selected `candidate_duplicate`
result.

## Finding 2 — dispersion warnings

The frozen verifier does not emit `HIGH_DISPERSION` or a `max/min` ratio. The
review-only postprocessor computes them from the sealed aggregate. No primary
lane exceeds the `0.25` MAD/median warning:

| Lane | candidate MAD/median | candidate max/min |
|---|---:|---:|
| 100K medium/K100 | 0.00839 | 1.0369 |
| 100K common/K100 | 0.00402 | 1.0216 |
| 100K common/K10 | 0.01359 | 1.0361 |

The full report is in `target/pr15i-d3a/review/replay-matrix.json` under
`dispersion`. Future verifier revisions should emit the flag natively; no T0d
change was made.

## Finding 3 / additional P2 — manifest and protocol identity hardening

- A duplicated `raw/manifest.json` entry is accepted because the verifier
  compares membership as a set. Actual F2 manifests have **no** duplicate paths
  (checked for control and all five runs).
- An altered `raw/authorization.json`/`raw/sources.json` `protocol_sha256` is
  accepted. Actual F2 artifacts have the correct v3 protocol hash
  `6a5eaaf8dd5ba1f9ed986a44201d742432e4f8a07b2e703949a55afba836163b` in every
  run; all archive sidecars match their archives.

Both are non-result-changing hardening items. Proposed future fixes (under a new
freeze, not T0d): reject duplicate manifest paths explicitly; require
`authorization["protocol_sha256"] == sha256(protocol_v3.json)`; add negative
tests for both. They do not invalidate the official F2 result or archives.

## Conclusion

- P1 review gap: **closed** by an independent read-only replay matrix.
- P2 hardening: **confirmed, deferred** to a future tooling revision.
- Official F2 evidence and T0d remain immutable.
- Diagnostic verdict remains provisionally supported; merge acceptance is a
  human decision. No optimization is authorized.
