# PR 15I-0 — storage and mutation-sidecar byte attribution

**Measured source:** `48e7d3a0771f9ccd1cc0bf1d07eadac4b2b5f39f`
**Measurement contract:** `pr15i-0-measurement-contract-v1`
(`af828096ca3d4581a8cda50b9401b3d23df92311487acaa79966a8a0e2e0e6f8`)
**Derived data:**
`benchmarks/reports/pr15i-0/pr15i-0-summary.json`
(SHA-256 `7859f183fa8a971fc69adf4826b6b5207be5297975ee675dbdd0e67d4031d585`)

All numbers below are copied from the qualified PR 15F read-only inventory and
from the PR 15I-0 sidecar probe. Nothing is extrapolated from a historical report.

## 1. Committed index bytes (current baseline)

| Documents | Total | Segment file | Segment sections | Segment overhead | Manifest | `CURRENT` metadata | Mutation sidecar |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | 3,090,037 | 2,129,038 | 2,128,372 | 666 | 636 | 183 | 960,180 |
| 100,000 | 30,965,025 | 21,364,026 | 21,363,360 | 666 | 636 | 183 | 9,600,180 |

Reconciliation equalities verified by the PR 15F inventory and re-checked by
`verify.py` gate `I0-P07`:

```text
segment_file_bytes            = segment_sections + segment_nonsection_overhead
classified_file_bytes         = total_file_bytes
sum(file sizes)               = total_file_bytes
bytes_before_sha256           = bytes_after_sha256          (index not mutated)
content_sha256                = prepared-index inventory fingerprint
```

At 100K the committed index is **30,965,025 B**: 21,364,026 B of segment file,
9,600,180 B of mutation-state sidecar, 636 B manifest and 183 B `CURRENT`.
The sidecar is **31.00 %** of the committed index and the segment file is
**69.00 %**.

## 2. Segment sections (100K)

| Section | Bytes | Share of committed index |
|---|---:|---:|
| `Stored` | 9,662,513 | 31.2046 % |
| `Postings` | 3,983,573 | 12.8647 % |
| `Dictionary` | 3,500,207 | 11.3037 % |
| `Columns` | 2,004,364 | 6.4730 % |
| `DocKeys` | 1,100,010 | 3.5524 % |
| `VersionRefs` | 800,011 | 2.5836 % |
| `FieldNorms` | 300,074 | 0.9691 % |
| `LiveDocs` | 12,511 | 0.0404 % |
| `Schema` | 97 | 0.0003 % |
| segment non-section overhead | 666 | 0.0022 % |
| **segment file total** | **21,364,026** | **69.00 %** |

10K values: `Stored` 966,263; `Postings` 389,957; `Dictionary` 350,207;
`Columns` 200,492; `DocKeys` 110,010; `VersionRefs` 80,011; `FieldNorms` 30,074;
`LiveDocs` 1,261; `Schema` 97; segment overhead 666. The per-document shape is
therefore stable across the two sizes (for example `Stored` ≈ 96.63 B/doc and
`Postings` ≈ 39.84 B/doc at both sizes).

**Do not read section shares as compressibility.** A section's share of the file
says nothing about the achievable reduction of its payload; only a measured
codec experiment can establish that.

## 3. Mutation-state sidecar: exact byte decomposition

The authoritative active object was resolved only through the public
`CURRENT → Manifest → MutationStateRef` chain and cross-checked against the PR 15F
inventory (same relative key, same length, same SHA-256). Obsolete
`index/state/` objects from earlier generations were **not** attributed.

| Property | 10K | 100K |
|---|---:|---:|
| Payload version | 1 | 1 |
| Required features | `[(1,1), (8,1)]` | `[(1,1), (8,1)]` |
| Rows (live / deleted) | 10,000 / 0 | 100,000 / 0 |
| Replay rows | 0 | 0 |
| Payload bytes | 960,010 | 9,600,010 |
| Container envelope overhead | 170 | 170 |
| Sidecar file bytes | 960,180 | 9,600,180 |
| Bytes per document | 96.0180 | 96.0018 |

### Component shares (100K)

| Component | Bytes | Share of sidecar file |
|---|---:|---:|
| `live_pointer_id_bytes` (full segment ID per live row) | 6,600,000 | 68.7487 % |
| `row_key_bytes` | 900,000 | 9.3748 % |
| `row_revision_bytes` | 800,000 | 8.3332 % |
| `live_doc_id_bytes` | 800,000 | 8.3332 % |
| `row_key_prefix_bytes` | 200,000 | 2.0833 % |
| `live_pointer_prefix_bytes` | 200,000 | 2.0833 % |
| `row_status_bytes` | 100,000 | 1.0416 % |
| `state_header_bytes` (payload version + row count) | 6 | 0.0001 % |
| `replay_header_bytes` | 4 | 0.0000 % |
| `replay_*` components | 0 | 0.0000 % |
| `batch_replay_opaque_bytes` | 0 | 0.0000 % |
| container envelope overhead | 170 | 0.0018 % |

10K shares are the same to within 0.01 percentage points, so the shape is stable.

### Reconciliation equalities (asserted by the probe, re-asserted by `verify.py`)

```text
sum(component_bytes)                     = payload_bytes
payload_bytes + container_overhead_bytes = sidecar_file_bytes
sidecar_file_bytes                       = inventory mutation_state_file_bytes
sidecar_sha256                           = inventory file sha256
live_count + deleted_count               = row_count
payload_version 1  => batch_replay_opaque_bytes = 0        (no invented bytes)
payload_version 2  => batch_replay_opaque_bytes >= 4        (SEMANTIC_BATCH_DETAIL_NOT_VERIFIED)
```

Every subtraction in the probe uses `checked_sub`; every component total uses
`checked_add` on `u64`. A malformed, truncated, overlong, unsorted,
unsupported-version or unsafe-path input fails closed with a typed class and
writes no report.

## 4. Artifact disk bytes versus current-generation referenced bytes

Two different quantities are reported and must never be conflated:

- **Index artifact disk bytes** — what the prepared index currently occupies,
  including any obsolete `index/state/*.state` objects that are no longer
  referenced by the committed manifest.
- **Current generation referenced bytes** — the objects reachable from
  `index/CURRENT → manifest → {segments, mutation state}`.

The current prepared indexes contain exactly four files each (`CURRENT`,
one manifest, one segment, one state object), so in this campaign the two
quantities coincide. In a longer-lived index they will not.

**Deleting obsolete-generation files is not a safe compaction technique.** Remote
deletion requires committed-generation retention and reader-safety rules
(`docs/ARCHITECTURE.md`); a local cache is disposable, an authoritative object is
not. PR 15I-0 measures; it does not reclaim.

## 5. Baseline-to-historical table (isolated, never mixed)

| Item | Value | Label |
|---|---:|---|
| 100K committed index bytes | 30,965,025 | `2026 PR15F HISTORICAL` |
| 100K mutation sidecar bytes | 9,600,180 | `2026 PR15F HISTORICAL` |
| 100K STORED bytes | 9,662,513 | `2026 PR15F HISTORICAL` |
| 100K Dictionary bytes | 3,500,207 | `2026 PR15F HISTORICAL` |
| 100K Postings bytes | 3,983,573 | `2026 PR15F HISTORICAL` |
| 100K dictionary-v2 candidate | 1,618,170 | `2026 PR15H-E EXPERIMENTAL REJECTION` |

The 15H-E candidate is a **rejected experiment**, not a baseline: it was rolled
back (`8d722ad`) because the frozen whole-index storage gates failed, and it is
not measured in this campaign. The current measured values happen to equal the
historical ones because the 15H-E rollback restored v1 dictionary bytes exactly.

Current samples and historical samples are never combined into a single ratio.

## 6. Per-component physical-zero ceiling

`saved_bytes_upper_bound` in `benchmarks/reports/pr15i-0/pr15i-0-summary.json` is
labelled `PHYSICAL_ZERO_BYTE_CEILING_ONLY`.

It is the component's current byte count — the saving that would follow if that
component became literally zero bytes with no replacement cost. It is **not** an
achievable saving, **not** a compression-ratio claim and **not** a benefit
forecast. Actual feasible reduction depends on codec, entropy, durability and
mandatory metadata, and must be measured by the future workstream's own campaign.
