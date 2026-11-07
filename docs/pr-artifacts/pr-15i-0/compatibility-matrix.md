# PR 15I-0 — cross-workstream compatibility matrix

**Status: contract matrix for future work. No item here is implemented by
PR 15I-0.**

| Consumer/producer | A mutation state | B STORED | C execution | Contract |
|---|---|---|---|---|
| Writer + atomic publish | Future A only | Future B producer only | No change | Publish only fully verified immutable objects |
| Reader open/reconstruct | Future v3 read + v1/v2 legacy | Future new STORED + v1 legacy | No change | Snapshot identity/digests/budgets |
| Replay/batch mutation | Preserve byte and semantic equality | No change | Existing execution fallback | No replay drift or fingerprint mismatch |
| Compaction | Rewrite live pointers to newly encoded v3 table | Build compressed STORED blocks | No change | Key/revision/winner invariants |
| Search | No new surface | Random-access selected materialization after verified admission | Narrow operator and fallback | Exact keys/count/order/score/first errors |
| FsDirectory | Content-addressed sidecar read | New segment bytes | Unchanged | Atomic durable generation |
| RustFS + SegmentCache | New sidecar verified from authoritative store | New segment complete-object bootstrap | No new remote I/O | Read-only cache disposable |
| PIT/refresh | Preserve old generations | Preserve old sections | Preserve old cursor/sort semantics | No in-place mutation |
| Previous codec | Read legacy v1/v2 sidecars | Read legacy v1 STORED | Generic plan remains | No migration silently required |
| Segment Dictionary E-v2 | Rejected and rolled back | No coupling | No coupling | Historical candidate only |

## Reading the matrix

- **No row allows a shared feature gate.** Mutation-state payload V3, the future
  STORED_BLOCKS feature and any postings-compression feature are independent
  required-feature ids.
- **No row permits in-place mutation.** Every accepted change creates new
  immutable content-addressed bytes; the previous generation stays readable for
  existing PIT readers.
- **No row permits remote I/O on the search hot path.** RustFS remains the
  authoritative whole-object store; `SegmentCache` stays disposable and bounded.
- **No row weakens corruption detection.** 15I-B may not trade
  corruption-observability for speed, and 15I-C may not trade first-error
  precedence for a smaller matched set.

## Ordering and isolation rules for the next series

1. 15I-A and 15I-B are **format** changes; 15I-C is an **execution** change.
2. Each workstream is qualified against a **separately accepted baseline**; a
   combined A+B+C candidate is never qualified as one performance experiment.
3. Where a factorial experiment is desired, it must be separately approved and
   clearly isolated.
4. Rejection evidence is retained with the same discipline as acceptance
   evidence, and thresholds are fixed **before** a candidate is written.
