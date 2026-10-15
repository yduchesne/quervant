# PR 12 — Adversarial review

## Attempted counterexamples and outcomes

1. **First-point-only retrieval.** A multi-valued document whose only matching
   point is not the first must match. `t02` stores two points and matches via
   either; `t12` matches after compaction; the KD tree indexes every occurrence,
   not a document-level summary.
2. **Exclusive edges.** Points on the west/east/south/north edges must match an
   inclusive box. `t04` asserts all four edge documents match and a point
   `1e-4` outside does not.
3. **Wrong meridian alias.** A point at `+180` must match a box that reaches
   down to `-180` and vice versa. `t04` asserts both `±180` documents match all
   three alias variants, and `search::geo::bbox_envelope_pruning_never_false_prunes_alias`
   proves the envelope test cannot prune the aliased node.
4. **False pruning.** The KD envelope test is conservative: it never prunes a
   node whose point could satisfy the predicate. The 300-case seeded oracle
   compares full sorted hit sets against an independent implementation; a single
   false prune would surface as a missing key.
5. **Stale doc id after compaction.** `t12` deletes half the documents, compacts,
   and then asserts the exact survivor coordinates resolve. The compaction path
   reads persisted spatial occurrences and remaps `old_doc → new_doc`; it never
   reuses a source physical id.
6. **NOT-complement errors.** `t15` composes `Not` with geo, time and JSON
   predicates. Membership is precomputed positively per leaf and negated
   per-document, so `Not(geo)` is the exact complement over effective-live docs.
7. **Digest-valid corruption.** `t09`/`t10`/`t10b` rebuild containers with
   recomputed digests after tampering with the spatial body, so the parser's
   structural and digest checks pass and only the spatial validator can reject.
   `t10b` alone exercises 35 distinct malformed bodies (30 field-level mutations
   across three nodes plus duplicate `(doc_id, ordinal)`, wrong version, wrong
   root, truncation and a trailing byte). Feature/section mismatch, wrong axis,
   out-of-range doc id, non-WGS84 latitude, NaN longitude and a truncated node
   all fail closed.
8. **Legacy state.** `legacy_column_fallback_and_unrecoverable` opens a segment
   with the spatial section stripped: a columnar field falls back to an exact
   bounded column scan, while an indexed-not-stored/non-columnar field returns a
   typed `geo_legacy_unrecoverable` error rather than zero hits.
9. **Distance ties and missing.** `t14` includes a document whose minimum
   distance comes from its second point, a missing-point document, and a
   search-after continuation; ordering and pagination are deterministic.

## Findings

- **Eager full-tree decode.** Opening a feature-bearing segment decodes and
  validates the entire KD tree into memory. This is required to verify cycles,
  extrema and split ordering, and is bounded by `SegmentLimits`
  (`max_decoded_entries`, `max_section_decode_bytes`, `max_single_allocation`).
  A field with more than roughly 760k points can exceed the default 64 MiB
  single-allocation ceiling and fail to open. This is a deliberate fail-closed
  behavior, not a silent partial read, but it is a scale limit to disclose.
- **Broad-query cost.** A bounding box covering most of the world prunes almost
  nothing, and the typed scan still visits every effective-live document to
  evaluate Boolean membership. The plan permits this ("broad queries may still
  scan all points"); the benchmark reports it honestly rather than claiming a
  uniform speedup.
- **Merge-unrecoverable branch.** `t12b` commits an indexed-not-stored,
  non-columnar GeoPoint field through the real writer, deletes half the
  documents, compacts and re-queries: the persisted spatial occurrences survive
  and no stored/columnar fallback is needed. The `IndexError::CorruptCommittedState`
  branch is only reachable for a *legacy* generation (no spatial section) that
  also lacks a stored/columnar copy, which the public writer cannot construct;
  the equivalent read-time branch is tested directly by
  `legacy_column_fallback_and_unrecoverable`. This is the main coverage gap in
  `index/merge.rs`.
- **Polygon holes are not validated against the outer ring.** The existing
  `GeoPolygon` contract validates each ring independently but does not require a
  hole to be strictly inside the outer ring. The PR 12 evaluator keeps the
  contract's semantics: outer boundary wins, otherwise any hole boundary or hole
  interior excludes. This is consistent with the approved contract and is not a
  new ambiguity.

## Residual risks disclosed

- Spherical (haversine) distances, not ellipsoidal.
- Planar, non-geodesic polygons; antimeridian-crossing polygons remain rejected.
- Full-scan cost for broad shapes and process RSS beyond logical decode budgets.

No unresolved correctness counterexample was found. No acceptance item was
silently deferred.
