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

---

# Corrective adversarial review

## Counterexamples re-tested after the fixes

1. **Adjacent-ULP bbox miss / near-full-world halo.** `b02` proves a point one
   ULP past a `1e-15`-wide east edge is excluded and a point one ULP below the
   west edge is excluded; `b07` proves a span one ULP under 360° does not become
   full-world (the only value left in that gap is the `+180`/`-180` seam, which
   is correctly included through the alias). `b04`/`b08` prove degenerate and
   signed-zero boxes match only exactly. The old `+ 1e-12` and
   `>= 360 - 1e-12` code fails these; the exact interval code passes.
2. **Point just outside a hole.** `p06` and `p10` place a point one ULP outside a
   hole edge and require inclusion. The old tolerance treated it as a hole
   boundary (excluded); the robust `orient2d` predicate returns nonzero
   orientation and the ray cast includes it. `p04`/`p05` keep hole edges and
   interiors excluded.
3. **Combined scratch allocations.** `m04` (two leaves), `m10` (two distance
   tables) and `m11` (membership + sort) each fit individually but fail together;
   `m06`/`m09` prove the exact per-table byte limit and the one-byte-short
   failure; `m12` proves the physical-doc table stays bounded; `m13` proves
   checked-arithmetic overflow fails typed. `m05` proves the DFS stack itself is
   charged. `m01`–`m03` prove the pre-dedup candidate-entry cap including
   duplicate occurrences.
4. **Legacy unrecoverable compaction.** `l01_l04` builds a real `FsDirectory`
   legacy v1 generation whose two segments were stripped of the `SpatialPoints`
   section and feature but retain an indexed-not-stored/non-columnar GeoPoint
   field, then calls the public compaction path. It returns
   `IndexError::CorruptCommittedState`, and `CURRENT`, the manifest set and a
   held snapshot are unchanged on both the first attempt and a retry.

## Oracle independence

`oracle_bbox_contains` uses its own canonical interval splitter, and
`integer_polygon_contains` uses checked `i128` orientation with integer parity.
Neither calls `search::geo`, the KD tree, the codec or any production predicate.
`o03` demonstrates that a regression to a `+ 1e-12` predicate would be flagged
by the exact oracle. The 300 seeded cases remain supplemental differential
coverage; boundary expectations come from the exact interval / integer-grid
reference. `t17_oracle_polygon` now generates exactly dyadic coordinates.

## Residual risks and limitations

- Spherical haversine (not ellipsoidal); planar non-antimeridian polygons;
  broad bbox/radius shapes may still traverse all points.
- The scratch budget is a **logical** per-segment capacity bound, not process
  RSS and not a combined global budget; the top-K heap budget remains separate.
- `index/merge.rs` line coverage is 83.28% (workspace total 91.88%); the
  unrecoverable-merge branch is now exercised by `l01_l04`, and the remaining
  uncovered merge lines are pre-existing recovery/failure branches.
- Indexed Polygon/MultiPolygon and MultiPolygon query remain deferred.

No unresolved correctness counterexample remains. No acceptance item was
silently deferred and no codec bytes, PIT semantics or publication behavior
changed.
