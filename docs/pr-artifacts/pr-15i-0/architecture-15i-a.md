# 15I-A — Mutation-Sidecar Segment-ID Interning and Compact Live Pointers (DESIGN CONTRACT)

**Status: `DESIGN_PROPOSAL_ONLY` — source-dependent details require independent
approval; NOT IMPLEMENTED.**

This document is a *contract input* for a future, separately authorised
implementation PR. PR 15I-0 changes no production code, no on-disk format and no
public API. Nothing below is implemented, accepted or scheduled by the
measurement work that produced it.

## Owner and goal

15I-A owns the **authoritative generation mutation-state sidecar physical
encoding**, not segment files, manifest publication, key/revision semantics or
replay behaviour.

Its first experiment is to eliminate repeated full segment-ID strings across live
key rows by storing them once in an immutable per-sidecar segment-ID dictionary.

It SHALL NOT attempt, in the first experiment:

- dictionary-FST conversion,
- zstd or any other general-purpose compression,
- prefix compression of logical keys,
- replay-ledger truncation.

Those are separate experiments with separate contracts.

## Proposed future physical format (requires an independent implementation PR before shipping)

```text
V3 mutation-state payload:
  payload_version: u16 = 3
  segment_id_count: u32
  segment_ids[segment_id_count]: (u16 byte_length, UTF-8 exact segment-id bytes)
  key_row_count: u32
  key_rows[key_row_count] in strict key-byte order:
    (u16 key_bytes_length, key_bytes,
     u64 revision, u8 status,
     LIVE -> canonical_unsigned_varint segment_ordinal,
             canonical_unsigned_varint physical_doc_id;
     DELETED -> no pointer)
  replay_count: u32
  replay_rows: byte-for-byte existing v2 structure
  batch_replay: byte-for-byte existing v2 structure, including count and full response
```

Rules:

- The `segment_ids` table MUST contain **only** identifiers referenced by live
  rows, be unique, and be ascending in byte-lexical order.
- A live row refers to the zero-based ordinal `< segment_id_count`. Deleted rows
  carry no segment pointer.
- Each segment ID is subject to exactly the same validity requirements as
  existing sidecar live pointers. **No new normalisation may be invented.**
- `revision` stays a full `u64` initially. Changing its representation is a
  separate later experiment.
- Logical key bytes and idempotency-token bytes remain exact.
- Replay fingerprints and payload domain separation remain exact.
- **The v3 write format must contain all v2 batch-replay semantics** and must
  never downgrade a previously upgraded sidecar.
- No loss of tombstones, revisions, replays or pointer validity is permitted.

## Version and feature rule

Define a **distinct** required mutation-state V3 feature in the shared container
`SUPPORTED_FEATURES`. Never reuse or renumber the V2 feature.

On the PR 15I-0 measured base (`48e7d3a`), `0x0001`–`0x000B` are occupied
(`FEATURE_MUTATION_STATE_V2 = 0x000B`), so the suggested next ID `0x000C` is
currently free. If it is occupied on the actual implementation base, **HARD STOP**
the dependent future implementation until an explicit ID decision is made.

Existing v1/v2 readers remain supported; older binaries observing v3 must fail
closed as unsupported. Payload V3 is **not** the same thing as segment dictionary
v2 and must not share its feature gate.

## Producer / consumer matrix

| Producer / consumer | Responsibility under V3 |
|---|---|
| `MutationStateV1::{encode,encode_with_mode,decode}` | Encode/decode V3; keep v1/v2 decode |
| Index writer publish/commit | Publish a new content-addressed sidecar object |
| Reader open/reconstruct | Accept v1/v2/v3; fail closed on unknown required feature |
| Compaction remap | Rewrite live pointers into a newly encoded V3 table |
| Replay and batch replay | Semantics unchanged, bytes preserved |
| Migration/open/recovery | No silent downgrade, no cross-generation in-place rewrite |
| Local `FsDirectory` and RustFS remote bootstrap | New bytes → new digest → new object key |
| Persistent descriptor digest | Content identity follows the new bytes |
| Immutable segment identities | Unchanged; segment ids remain immutable |

**No new public index API.** No changes to `CURRENT`/manifest atomic publication.
The sidecar's new bytes naturally produce a new content digest and object key, and
only a committed generation may refer to it. Old PIT readers retain earlier
immutable objects.

## Mandatory negative cases for the future PR

Repeated/live/deleted keys; two different segments; all rows deleted; zero-live
sidecar; high ordinals > 127 requiring multibyte canonical varint; out-of-range
ordinals; duplicate/unreferenced/unsorted segment table; invalid UTF-8; wrong
feature/version; revision zero/overflow; stale `CURRENT`; interrupted sidecar
write; withheld remote object; idempotency replay across restart; batch query
selector fingerprint; compaction pointer rewrite; concurrent PIT + refresh;
corruption in an unselected table entry; exact/one-over decode-memory budgets.

## Acceptance policy for the future detailed plan

- **Primary goal:** `mutation_sidecar_bytes` and `total_committed_index_bytes`.
- **Independent guardrails:** reopen, commit, remote cold bootstrap,
  heap/memory, replay correctness.
- Use the 10K/100K PR 15D frozen corpus **plus mandatory** multi-segment,
  deletes/upserts and replay-heavy fixtures so success is not limited to
  single-segment clean indexes.
- Predeclare **relative** size objectives after the 15I-0 measured breakdown: the
  first candidate must save **≥ 25 % of sidecar bytes at 100K** and **≥ 5 % of
  total committed-index bytes at 100K**, with **≤ 10 % median reopen
  regression** and zero correctness regressions. If the measured baseline makes
  either impossible under the segment-ID repetition ceiling, the separate
  implementation plan must explicitly seek maintainer review of new targets
  **before any candidate is written** — not silently retune them.

## STOP principles

No cross-generation in-place rewrite. No dropping replay rows or duplicate
corruption checks. No unmetered allocation. No weaker old-reader handling. No new
opaque digest algorithm. No assumption of S3 CAS. No merging this workstream with
STORED compression.

## Measured evidence (PR 15I-0, source `48e7d3a`, not a forecast)

Exact byte attribution of the active mutation-state sidecar, reconstructed from
the original envelope-verified bytes:

| Component (100K) | Bytes | Share of sidecar |
|---|---:|---:|
| `live_pointer_id_bytes` (repeated full segment IDs) | 6,600,000 | 68.7487 % |
| `row_key_bytes` | 900,000 | 9.3748 % |
| `row_revision_bytes` | 800,000 | 8.3332 % |
| `live_doc_id_bytes` | 800,000 | 8.3332 % |
| `row_key_prefix_bytes` | 200,000 | 2.0833 % |
| `live_pointer_prefix_bytes` | 200,000 | 2.0833 % |
| `row_status_bytes` | 100,000 | 1.0416 % |
| `state_header_bytes` | 6 | 0.0001 % |
| `replay_header_bytes` | 4 | 0.0000 % |
| container envelope overhead | 170 | — |
| replay / batch components | 0 | 0 % |
| **sidecar file total** | **9,600,180** | **100 %** |

Interpretation constraints for the future PR:

- The measured corpus is a single-segment, all-live, zero-replay fixture. The
  repetition factor observed here (66 bytes of segment ID per live row) is an
  upper bound for *this* corpus shape, not a general claim.
- The `saved_bytes_upper_bound` values in
  `benchmarks/reports/pr15i-0/pr15i-0-summary.json` are labelled
  `PHYSICAL_ZERO_BYTE_CEILING_ONLY`. They are **not** achievable savings.
- Full details, denominators and reconciliation equalities are in
  [`storage-attribution.md`](storage-attribution.md).

## Open questions / decision required before implementation

1. Varint ordinal width policy and its interaction with the segment table size
   budget (single- vs multi-segment indexes).
2. Whether the batch-replay block is re-encoded or kept byte-identical in the
   first V3 candidate (the contract requires semantic equality; byte equality is
   cheaper to prove).
3. Exact decoded-memory accounting for the new segment table.
