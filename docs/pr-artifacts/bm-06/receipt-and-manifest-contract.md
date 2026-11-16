# BM-06 — Receipt and manifest contract

## 1. Encoding and digest rules

- Every persisted internal document is strict JSON with a closed field set and
  `schema_version: 1`, UTF-8 without BOM, no duplicate keys / `NaN` / `Infinity`,
  at most 1 048 576 bytes.
- Persisted canonical bytes are `canonical_document_bytes(document)` (sorted keys,
  no whitespace) **plus exactly one trailing newline**.
- `content_digest(document)` is `sha256:<hex>` over the canonical payload bytes
  **without** the newline.
- The BM-03 seal is bound by a **raw** `sha256:` digest of the actual `seal.json`
  file bytes (`seal_raw_digest`), never by a canonical JSON digest. The raw digest
  therefore covers the trailing newline; the replay's canonical `seal_digest` is a
  second, distinct identity that admission also cross-checks.
- No document carries its own digest. The external `manifest_digest` is
  `content_digest(manifest.json)`; the attestation receipt ID is
  `content_digest(attestation payload without receipt_id)`.

## 2. Seven receipt-v1 gates

All seven gate receipts reuse the frozen BM-01 `receipt.v1` schema
(`config.contracts.validate_receipt`) unchanged. BM-06 adds a semantic verifier;
it does not add a schema, a status value, an error code or a gate name.

| Gate | Validator ID (version 1) | Dependencies (sorted) | Outputs | Inputs |
| --- | --- | --- | --- | --- |
| `admission` | `synthetic-admission` | — | `admission-index` | `protocol`, `qualification-profile`, `scenario`, `seal`, `source-set`, `workload` |
| `analysis` | `synthetic-analysis` | `admission` | `analysis`, `policy` | `admission-index`, `analysis-profile`, `policy-profile`, `resource-observations`, `source-set` |
| `verification` | `synthetic-verification` | `admission`, `analysis` | `verification-assessment` | `analysis`, `policy`, `source-seal`, `source-set` |
| `framework-qa` | `synthetic-framework-qa` | — | `framework-qa-evidence` | `framework-qa-evidence`, `qa-toolchain`, `qualification-profile`, `source-set` |
| `source-qa` | `synthetic-source-qa` | — | `source-qa-evidence` | `qa-toolchain`, `qualification-profile`, `source-qa-evidence`, `source-set` |
| `acceptance` | `synthetic-acceptance` | `admission`, `analysis`, `framework-qa`, `source-qa`, `verification` | `acceptance-summary` | `admission-index`, `analysis`, `framework-qa-evidence`, `policy`, `qualification-profile`, `source-qa-evidence`, `source-set`, `verification-assessment` |
| `attestation` | `synthetic-attestation` | `acceptance`, `admission`, `analysis`, `framework-qa`, `source-qa`, `verification` | `freeze-snapshot` | `freeze-snapshot`, `qualification-profile`, `source-set` |

Every receipt:

- has `status='pass'`, `evidence_origin='synthetic'`, `qualification_scope='simulated'`;
- carries the exact BM-01 subject `{experiment_id, run_id, protocol_digest,
  workload_digest}` of the qualified run;
- has validator `source_digest` equal to the independently pinned source-set digest;
- lists `inputs`/`outputs` as sorted `{name, digest}` entries and `dependencies` as
  sorted `{name, digest, gate, receipt_id}` entries, where `name == gate` and
  `receipt_id`/`digest` are the referenced receipt's recomputed ID and canonical
  document digest (two distinct values; the digest includes the referenced
  `receipt_id`);
- sets `qa_roster_digest` (the qualification profile digest) only on
  `framework-qa`, `source-qa`, `acceptance`, `attestation`;
- sets `policy_digest` (the frozen policy document digest) only on `analysis`,
  `verification`, `acceptance`, `attestation`.

A receipt whose self-hash is valid but whose dependency edges point at a different
run, a different gate or an extra/missing receipt is rejected (`REC-02…09`).

## 3. Durable 15-file inventory

Creation order (completion marker last):

```text
 1 admission-index.json        synthetic-sealed-admission-index
 2 admission.json              receipt: admission
 3 analysis.json               BM-04 analysis document (unchanged)
 4 policy.json                 BM-04 policy document (unchanged)
 5 analysis-receipt.json       receipt: analysis
 6 verification-assessment.json synthetic-verification-assessment
 7 verification.json           receipt: verification
 8 framework-qa-evidence.json  canonical copy of the pinned QA input
 9 framework-qa.json           receipt: framework-qa
10 source-qa-evidence.json     canonical copy of the pinned source QA input
11 source-qa.json              receipt: source-qa
12 acceptance-summary.json     synthetic-acceptance-summary
13 acceptance.json             receipt: acceptance
14 attestation.json            receipt: attestation
15 manifest.json               simulated-qualification-manifest (marker)
```

No logs, metadata, temp JSON, nested directories or additional members are allowed.
Publication creates `<experiment>` and `<run>` exclusively, writes files 1–14 with
`O_CREAT|O_EXCL|O_NOFOLLOW`, fsyncs each file, fsyncs the directory, writes a
canonical `manifest.pending` exclusively and fsyncs it, hard-links pending to
`manifest.json` (no replace), fsyncs the directory, unlinks pending and fsyncs
again. A pending file, a missing marker or any unexpected name means **incomplete**.
Publication never repairs, overwrites, cleans up or falls back to rename/copy; a
platform without no-follow/link/directory-fsync semantics fails with
`BM_NOT_IMPLEMENTED`.

## 4. Freeze snapshot and acyclic manifest

`freeze-snapshot` (in memory only) contains
`kind, schema_version, subject, evidence_origin, qualification_scope,
profile_digest, source_set_digest, members` where `members` are the **first 13**
durable documents in lexicographic path order:

```text
acceptance-summary.json, acceptance.json, admission-index.json, admission.json,
analysis-receipt.json, analysis.json, framework-qa-evidence.json,
framework-qa.json, policy.json, source-qa-evidence.json, source-qa.json,
verification-assessment.json, verification.json
```

The `attestation` receipt depends on all six upstream gates and outputs exactly
`[{name: 'freeze-snapshot', digest: content_digest(snapshot)}]`. It **never** refers
to `manifest.json` or its digest.

The final manifest contains
`kind='simulated-qualification-manifest', schema_version, subject, evidence_origin,
qualification_scope, profile_digest, source_set_digest, freeze_snapshot,
attestation_digest, members`, where `members` lists all **14** published documents
(including `attestation.json`) in sorted path order. It has no self-hash field and
no `manifest.json` entry. `attestation_digest == content_digest(attestation.json)`
and the attestation member digest must equal it.

The loader independently reconstructs the snapshot from the actual first 13
canonical files, checks the attestation output digest, rehashes all 14 members,
requires exactly the 15 committed names (no pending, no symlinks, no hardlink
surprises) and then re-verifies every receipt edge against current anchors. A forged
but internally consistent bundle with a stale source/QA/seal is still rejected.

## 5. Internal records

- **Admission index**: `subject, evidence_origin, qualification_scope,
  seal_raw_digest, freeze_digest, scenario_digest, protocol_digest, profile_digest,
  source_set_digest, counts{controls_completed,treatments_completed,
  slots_completed,lane_envelopes,synthetic_samples}, files[{path,byte_length,
  raw_digest}]`; files are exactly the sealed `seal.files` list, sorted, with raw
  file digests and no absolute paths.
- **Verification assessment**: the BM-05 `VerificationAssessment` fields plus
  `kind`/`schema_version`; `check_ids` must equal the frozen nine-entry registry.
- **Acceptance summary**: subject, profile/source digests, the five upstream
  `gate_receipt_ids` (`admission, analysis, verification, framework-qa, source-qa`),
  both QA evidence digests and the **exact** policy `decision_status` copied from the
  independently verified policy document.
