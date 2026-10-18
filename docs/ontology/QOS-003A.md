# QOS-003A — Relationship mutation encoding

**Version 1.0-design · D01–D22 approved · Post-v0.1**

## Identity and operations (D01–D05)

**D01:** Canonical key `K=(relationship type, subject incarnation, object incarnation)`; reversed symmetric triples remain distinct assertions. **D02:** Set semantics; duplicates not separate occurrences. **D03:** Ordered atomic batch operations `Assert(K)`, `Retract(K)`, `DeleteInstance(I)`, `ReplaceInstanceClasses(I,C)`. **D04:** Logical no-ops do not emit redundant delta records. **D05:** Derived-only roles reject direct assertion.

## Ordering and idempotency (D06–D08)

**D06:** State-changing transactions have monotonically increasing total logical sequence; operation ordinal disambiguates order; multiple mutations per key collapse to final state before encoding. **D07:** Optional expected logical revision precondition; distinguish never-present and previously retracted when necessary. **D08:** Optional caller idempotency key binds canonical request digest and outcome, committed atomically; conflicting replay fails; retention bounds replay guarantees.

## Physical encoding (D09–D11)

**D09:** Immutable delta records include relationship ID, subject/object IDs, transaction sequence, `Assert|Retract`; persistent codec must be versioned, deterministic, bounded and checksummed. **D10:** Forward `(relationship,subject,object,sequence)` and reverse `(relationship,object,subject,sequence)` indexes point to the same authoritative mutation record. **D11:** Generation-scoped compact latest-mutation resolution, without rewriting every key on commit: `R_G={K | latest_visible_G(K)=Assert}`.

## Visibility and deletion (D12–D16)

**D12:** Reader pins generation. **D13:** Refresh exposes non-durable state to new readers; commit durably publishes documents, relationships and ontology together; PIT remains isolated. **D14:** Ontology semantics pinned. **D15:** Deletion completely enumerates and retracts incoming/outgoing asserted edges, deduplicates self-loops, fails atomically on budget exhaustion. **D16:** Only live incarnation IDs can be endpoints; deleted external key recreated as a distinct incarnation.

## Compaction, recovery (D17–D22)

**D17:** Compaction preserves all retained snapshots. **D18:** Tombstone reclamation only after no retained snapshot, older assertion or recovery reference needs it and replacement is durable. **D19:** PIT pins prevent premature local/remote GC. **D20:** Validate private candidate, write/verify immutable artifacts, publish generation atomically with required fencing. **D21:** Missing/corrupt authoritative segments, bad ordering, invalid dictionary or dangling IDs fail closed. **D22:** Inferred caches disposable; reuse only with matching snapshot and semantic fingerprints.

**Chosen model:** hybrid immutable segment deltas plus generation-aware latest-mutation lookup, not a separate mutable graph database. Conformance must test reassert/retract, mixed batches, delete/recreate, pinned PIT, compaction, crash boundaries, remote recovery, revisions, idempotency, budgets and corruption.
