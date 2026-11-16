# BM-07 reference catalog and offline CLI contract

## 1. Catalog

Path: `benchmarks/experiments/synthetic-retained-key-reference/`

Exactly eight BM-01 files:

```text
experiment.yaml
workloads.yaml
protocol.yaml
adapter.yaml
analysis-profile.v1.json
policy-profile.v1.json
resource-observations.v1.json
synthetic-scenario.v1.json
```

### Arms and lanes

Semantic arm order: `baseline`, `linear`, `prefilter`, `exact-set`. All four use
the existing `synthetic-execution` adapter with `variant` equal to the arm ID.

Eight simulated lanes, in canonical order:

```text
large-absent  large-common  large-medium  large-rare
small-absent  small-common  small-medium small-rare
```

These are simulated query-class labels, not D3-C `pr15d_v1/n/class/k`
identifiers and not measurements at a particular `k`.

### Frozen schedule and samples

| Field | Value |
|---|---|
| Blocks | 4 |
| Treatment slots/block | 8 |
| Appearances of each treatment arm/block | 2 |
| Treatment campaigns | 2 |
| Control campaigns | 1 (`baseline` source arm) |
| Samples per lane/slot | 3 |
| Warmups per lane/slot | 2 |
| Seed | `42` |

Every slot of an arm/lane replays the same declared vector:

| Arm | Samples (ns) | Slot median |
|---|---|---|
| `baseline` | `990000, 1000000, 1010000` | 1,000,000 |
| `linear` | `930000, 940000, 950000` | 940,000 |
| `prefilter` | `780000, 790000, 800000` | 790,000 |
| `exact-set` | `805000, 815000, 825000` | 815,000 |

The literal ledger is
`benchmarks/quervant_bench/tests/fixtures/retained-key/reference-expectations.v1.json`.
It is an independent source of truth: tests compare literal integer arithmetic
against the expected strings and never import BM-04 to compute the golden.

Expected per-lane normalized effects (lower-is-better):

```text
linear    0.940000000000
prefilter 0.790000000000
exact-set 0.815000000000
```

With identical block ratios the paired confidence intervals collapse to the same
values. The frozen policy selects `prefilter` on merit
(`DECISION_STATUS=SELECTED_ELIGIBLE_SYNTHETIC`): `prefilter` (0.79) beats
`exact-set` (0.815) by more than the 3% tie window. The result remains
`evidence_origin=synthetic`, `qualification_scope=simulated`.

### Policy and resources

- Target: `large-medium`, point ≤ 0.95, CI upper < 1.0 (`lt`).
- Guardrail: `large-common`, point and CI upper ≤ 1.1 (`le`).
- Ranking lanes: `large-common`, `large-medium`.
- Tie relative delta: `0.030000000000`.
- Tie preference: `prefilter`, `exact-set`, `linear`.
- Resource `aux-memory-bytes`, maximum 2,097,152 bytes per candidate.
- Simulated observations: `linear=1048576`, `prefilter=1048576`,
  `exact-set=2097152`.

## 2. Offline workspace

The workspace is externally supplied, never inferred from a manifest:

```text
QUERVANT_BENCH_OFFLINE_WORKSPACE=/absolute/safe/directory
```

If unset, the only fallback is `<repository>/benchmark-results`. The CLI never
creates the workspace.

Accepted topology:

```text
<workspace>/
  qualification-anchors.v1.json
  qa/                                     # BM-06 simulated QA tree
  scenarios/<experiment-id>/<run-uuid>/synthetic-scenario.v1.json
  runs/<experiment-id>/<run-uuid>/...      # sealed BM-03 input
  qualified/<experiment-id>/<run-uuid>/    # 15-file BM-06 bundle
```

`qualification-anchors.v1.json` is an independent caller trust root with exactly:

```json
{
  "kind": "simulated-qualification-trust-anchors",
  "schema_version": 1,
  "profile_digest": "sha256:...",
  "framework_qa_digest": "sha256:...",
  "source_qa_digest": "sha256:...",
  "source_set_digest": "sha256:..."
}
```

It is never derived from the candidate bundle and is never repaired by the CLI.

### Resolution rules

- Only immediate children of `<workspace>/qualified` are scanned.
- Maximum 128 semantic-ID experiment directories.
- The requested run ID must be canonical lower-case UUIDv4.
- Exactly one match is required: zero ⇒ `BM_EVIDENCE_UNAVAILABLE`,
  two or more ⇒ `BM_IDENTITY_INVALID`.
- More than 128 directories, illegal names, symlinks or non-directory entries ⇒
  `BM_UNSAFE_INPUT`.
- A matched experiment outside `synthetic-retained-key-reference` ⇒
  `BM_NOT_IMPLEMENTED`.

## 3. Stage views

Without `--offline`, all five verbs remain `BM_NOT_IMPLEMENTED`. With
`--offline`, the CLI:

1. resolves the workspace and run;
2. reads the independent anchors;
3. calls `load_qualified_synthetic_run` (full BM-06 revalidation);
4. re-reads the committed bundle and compares manifest digest, attestation
   receipt ID and output directory;
5. writes exactly one canonical JSON document to stdout and nothing to stderr.

| Verb | Success body |
|---|---|
| `validate` | Existing `admission-index.json` |
| `analyze` | `{kind:"simulated-offline-analysis-view",schema_version:1,evidence_origin:"synthetic",qualification_scope:"simulated",subject,manifest_digest,analysis,policy}` |
| `verify` | Existing `verification-assessment.json` |
| `accept` | Existing `acceptance-summary.json` |
| `report` | `{kind:"simulated-offline-report",schema_version:1,evidence_origin:"synthetic",qualification_scope:"simulated",subject,manifest_digest,attestation_receipt_id,policy}` |

Both internal views use an exact closed key set, a validated subject, a
`sha256:` manifest digest, existing BM-04 documents (no recomputation) and a
1 MiB canonical budget. They are deliberately **not** `outcome.v1` success
documents; `outcome.v1` success remains restricted to `inspect`.

Errors keep the existing BM-01 `outcome.v1` error envelope, empty stdout and the
existing exit code. `run` remains exit 77 before any workspace or scenario access.
