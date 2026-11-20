# Frozen official protocol templates

Two closed, versioned design templates live outside the reviewed source roster so
that a reviewer can pin them without any circular hash:

| Study | File | Template content digest |
| --- | --- | --- |
| `retained-key-topk-real-v1` | `benchmarks/official-protocols/retained-key-topk-v1.json` | `sha256:bf6fd040819b86b2bee317c83eb286e1e5f50400f8e19cb8490d8171d1197f44` |
| `cross-engine-keyword-real-v1` | `benchmarks/official-protocols/cross-engine-keyword-v1.json` | `sha256:86ac2996777ced1995969e3a8f9271aa8de324b41006456c3fd9e64568211815` |

The on-disk (canonical bytes plus trailing newline) SHA-256 for the same files is
`e37cadc3…a9368` and `37364e7f…afb7` respectively. The **approved digest** used by
`official.protocols.read_approved_template` is the canonical *payload* digest of the
table above; a candidate file can never supply its own trust root.

## Retained-key mapping (`diagnostic_only` disclosure)

`benchmarks/pr15i_d3_c/protocol_v3r3.json` is unchanged, still carries
`diagnostic_only=true`, and its raw SHA-256 is pinned in the template as
`sha256:c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`. The
template records explicit review facts:

```json
"backend_diagnostic_flag": true,
"outer_protocol_mapping": {
  "reviewed": true, "diagnostic_only_disclosed": true,
  "new_execution_required": true, "historical_protocol_unmodified": true
}
```

Relabelling `backend_diagnostic_flag` to `false` is rejected. The template also
copies the frozen 12-block control and both 12-block treatment orders, the schedule
seeds, the A/A numeric windows, the 100K committed-index sentinel
(`15747551`), the within-arm exclusion caps (`1.50`, and `1.25` for 100K
medium/common), the 4-block retention minimum and the P2 prefilter profile.
`official.protocols.verify_backend_protocol` re-hashes the legacy protocol and
requires every one of those values to match the frozen bytes; a mismatch is an
identity failure, never a re-pin.

The nine-K policy chain is recorded as `t7-f2-nine-k-v1` with
`not_derivable_status: POLICY_NOT_DERIVABLE` and `claim_on_tie:
TIE_PREFERENCE_NOT_PROVEN_FASTER`.

## Cross-engine mapping

`benchmarks/pr15d/spec/pr15d_v1.json` is pinned by raw SHA-256
`sha256:ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466`. The
template fixes `tantivy =0.22.1`, `lucene 9.12.3`, the three trial rotations, 32
lanes (16 warm, 16 process-cold descriptive only), 5 warmups, 20 samples, 100
serial throughput requests per window, and a mandatory *separate* 12-block × 4-slot
Quervant/Quervant A/A that the legacy runner does not perform.

The A/A numeric windows are explicitly recorded as a **newly reviewed transfer** of
the D3-C windows (`0.85..1.15` median, `0.80..1.25` non-exception blocks, one soft
outlier for 10K absent/rare with hard bounds `0.67..1.50`). A reviewer may reject
the transfer; the agent may not change it.

The v1 official decision is frozen to `INCONCLUSIVE` with no selected arm and
`performance_claim_allowed=false`. Descriptive per-lane warm ratios are still
reported.

## Review status

Both templates are implemented and self-consistent, and their digests above are the
candidate digests an independent reviewer must approve out of band. **No approval
record exists yet**, so no real control may run.
