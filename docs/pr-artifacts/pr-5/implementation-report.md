# PR 5 implementation report

> **Branch:** `dev/segment-codecs`
> **Baseline HEAD:** `84ed70ba775836be98831f5442e4e6a3ddd97b75` (approved format)
> **Status:** implementation complete for the approved PR 5 scope; awaiting
> review. **No merge performed.**

## 1. Authorization and approval

- F01–F12 approved at `111e464a74b0664c005c5f2adc2b0cd66ffb28b6` and recorded in
  `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md` (status **APPROVED — FORMAT
  FROZEN**), approval-record commit `84ed70ba775836be98831f5442e4e6a3ddd97b75`.
- The approved format was implemented exactly; no F01–F12 semantics were
  reinterpreted. Byte-level clarifications folded in: PR 3 whole-file
  `ContentDescriptor` digest vs F02 envelope digest domains; persisted column
  `block_docs`; `posting_doc_count` vs segment `doc_count`; sequential v1
  dictionary lookup with no binary-search claim.

## 2. Files changed

New production module `crates/trawler-core/src/segment/`:

| File | Responsibility |
|---|---|
| `mod.rs` | Public API and exports |
| `error.rs` | Typed `SegmentError` (no panic, no content leakage) |
| `limits.rs` | F11 wire/safety/operational budgets |
| `format.rs` | LE primitives, canonical varints, header/footer/trailer, SHA-256 integrity, container builder/parser |
| `schema.rs` | Canonical name-sorted `field_id`, analyzer/normalizer fingerprint bindings |
| `value.rs` | Five-state vocabulary, typed scalar encodings, recursive JSON |
| `stored.rs` | Stored source with presence bitmap |
| `column.rs` | Block-addressable typed columns, persisted `block_docs`, group keys |
| `dictionary.rs` | UTF-8 sorted term dictionary, sequential lookup |
| `postings.rs` | Positional postings + lazy bounded `next`/`advance` + cancellation |
| `bounds.rs` | Presence-aware time/geo bounds and pruning applicability |
| `remap.rs` | Total bijective doc-id permutation |
| `manifest.rs` | Manifest codec + reference validation (no publication) |
| `model.rs` | Immutable fixture input model |
| `build.rs` | Deterministic fixture builder composing all sections |
| `reader.rs` | Bounded reader over the real `Directory` seam |
| `tests.rs` | Unit tests for error paths, primitives, bounds, values |

Also: `crates/trawler-core/src/lib.rs` (`pub mod segment;`), integration tests
`crates/trawler-core/tests/segment_codec.rs` and `segment_golden.rs`, and the
checked-in golden fixture `crates/trawler-core/tests/fixtures/segment/golden.seg`.

Documentation artifacts: `docs/pr-artifacts/pr-5/implementation-preflight.md`,
`correctness-matrix.md` (executed evidence), `implementation-report.md`,
`validation-report.md`.

No changes to PR 2 contracts, PR 3 storage, PR 4 analysis, `trawler-objectstore`,
`trawler-distributed`, Cargo manifests, or the lockfile.

## 3. Completed steps against the detailed plan

- **Phase A:** typed codec errors; checked LE/varint primitives; header/footer/
  fixed 64-byte trailer validation; envelope + whole-file digest separation;
  bounded reads and allocations; immutable fixture builder. ✅
- **Phase B:** canonical schema with analyzer fingerprints; stored source with
  the five logical states and nested JSON; fixed/variable typed column blocks;
  typed group keys; persisted block geometry. ✅
- **Phase C:** UTF-8 sorted deterministic dictionary; positional postings with
  monotone doc ids, frequencies, positions, `position_length`, `value_index` and
  original offsets; bounded lazy `next`/`advance` with cancellation; live/version
  references (no mutation execution). ✅
- **Phase D:** total validated doc-id remap; presence-aware conservative temporal
  and geospatial bounds (antimeridian aware); manifest encode/decode/reference
  validation with **no** publishing. ✅
- **Phase E:** immutable persistence and reopen through `MemoryDirectory` and a
  fresh `FsDirectory` instance; independently specified checked-in golden
  fixture; adversarial corruption/truncation/geometry tests. ✅

## 4. Scope boundaries enforced

No production `IndexWriter`, commit/CURRENT publication, generation/fencing,
refresh, recovery, PIT, reader generations, query execution, BM25, merge/delete
execution, automata/FST, remote ObjectStore/RustFS adapter, cold bootstrap,
distributed runtime, or vector/ANN functionality was implemented. The manifest
carries no generation/parent/epoch fields.

## 5. Explicit approved-architecture decisions reflected

- One immutable section-addressable container per segment; `SegmentId`/
  `SegmentDescriptor` identity retained (F01).
- LE header + fixed EOF trailer; `envelope_digest` excludes the trailer, PR 3
  `ContentDescriptor` covers the whole file; the two are never compared (F02).
- Canonical schema IDs and persisted analyzer fingerprints (F03); dense physical
  ids and byte-exact keys (F04).
- Sequential v1 dictionary lookup; `posting_doc_count` distinct from
  `doc_count`; no v1 skips (F05).
- Semantic stored-source fidelity with `ABSENT`/`EXPLICIT_NULL`/`EMPTY_MULTI`/
  `SINGLE`/`MULTI` (F06).
- Persisted `block_docs`, bounded doc-N column access, family-aware IP/CIDR,
  collision-free typed group keys (F07).
- Conservative bounds plus an explicit pruning-applicability table (F08).
- Deterministic timestamp-then-key remap applied to every doc-addressed section
  (F09).
- Manifest codec only (F10).
- Wire/safety/operational limit separation; 256 MiB is an encoder target (F11).
- Fail-closed major/minor/required features; committed golden fixtures (F12).

## 6. Unresolved risks and limitations

- **v1 dictionary lookup is O(terms) sequential** by design; no binary-search or
  skip-index claim. A future optional block/FST index is required for sublinear
  lookup.
- **Postings `advance` is sequential** without v1 skip metadata.
- **Selective range reads are not content-authenticated** in v1; a Merkle-style
  authenticated range scheme remains a separate human decision.
- **Boundary UTF-8 validation of stored offsets** against the original source is
  a higher-layer check; the codec records the analyzer-produced offsets and
  validates ordering/bounds, not source boundary membership.
- **Exact term fallback**: indexed `Text`/`Keyword` fields without a bound
  analyzer index exact value bytes (keyword-style). This default is documented in
  code; a schema requiring analyzer semantics should bind one.
- **Golden fixture regeneration** is an `#[ignore]`d test; fixture updates must be
  reviewed.
- Coverage headroom is modest (**85.26%** workspace line); the workspace floor is
  met but a future large change should add tests.

## 7. Validation summary

Exact commands and results are in `docs/pr-artifacts/pr-5/validation-report.md`.
All mandatory gates pass on the final working tree. No merge was performed.
