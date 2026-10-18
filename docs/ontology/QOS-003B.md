# QOS-003B — Cross-segment adjacency

**Version 1.0-design · D01–D25 approved · Post-v0.1**

## Identity and dictionary (D01–D05)

**D01:** Never-reused 128-bit incarnation IDs. **D02:** UUIDv4-compatible random allocation with collision detection, no segment/shard encoding. **D03:** Generation-scoped `external key → incarnation → live document version` mapping; old edges never attach to recreated keys. **D04:** Versioned ontology dictionary maps canonical relationship URNs to compact physical numeric IDs. **D05:** Mixed dictionary versions resolve to canonical URNs through verified mappings or reject; bounded snapshot-local interning.

## Segment encoding (D06–D09)

**D06:** Forward `(relationship,subject,object) → mutation`. **D07:** Reverse `(relationship,object,subject) → same authoritative mutation`. **D08:** Sorted seekable bounded blocks with offsets, checksums and optional compression. **D09:** Conservative counts, key bounds, index offsets/lengths, dictionary fingerprint, codec version and digest; pruning must never yield false negatives.

## Streaming merge (D10–D13)

**D10:** Snapshot-scoped k-way cursor merge seeks relevant segments, groups by canonical triple and resolves latest visible mutation. **D11:** Outgoing ordered by canonical object ID; incoming by canonical subject ID. **D12:** Winner maximizes `(transaction sequence, operation ordinal)`; only `Assert` emits. **D13:** Deduplicate during grouping, without loading the graph into memory.

## Snapshot and incident lookup (D14–D18)

**D14:** Pin generation, manifest, incarnation mapping, dictionary, ontology and operator fingerprints. **D15:** Refresh may expose non-durable segments only to newly opened readers. **D16:** PIT unaffected by writes, compaction or definition changes. **D17:** Additional immutable `(subject,relationship,object)` and `(object,relationship,subject)` access paths support incident enumeration across all relationship types. **D18:** Incident merge resolves retractions and self-edges; enumeration must complete before deletion.

## Remote access, API, limits (D19–D25)

**D19:** Conservative pruning considers tombstones. **D20:** ObjectStore authoritative; bounded verified cache materialization, no unrelated fetch when provably prunable. **D21:** No whole-graph materialization on open. **D22:** Asserted-only `contains_asserted`, `outgoing`, `incoming`, `incident` with cancellable, error-aware cursors. **D23:** Inference lives above the physical asserted reader. **D24:** Bound open cursors, block bytes, merge heap, dictionary, records visited, results, remote bytes, deadline/cancellation; never silently truncate. **D25:** Bounded hierarchical merge/spill for high fan-in, preserving global latest mutation; otherwise explicit failure.

**Proof obligations:** `Outgoing_G(R,S)={O|(R,S,O)∈R_G}`; `Incoming_G(R,O)={S|(R,S,O)∈R_G}`. Differential tests include mixed dictionary versions, retractions, self-loops, delete/recreate, PIT, compaction, remote reload, corruption and budgets.
