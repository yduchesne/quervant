# PR 9 adversarial review

Each entry names the invariant, a concrete counterexample considered, and the
implementation response. `[NOT COVERED]` marks a residual gap.

## P9-I01 — one live winner per logical key, physical ids not identity

- **Counterexample:** insert `k`, flush, upsert `k`, flush, commit. Both physical
  documents remain in immutable segments.
  **Response:** the generation sidecar stores exactly one `LIVE` row per key.
  `visibility::build_masks_from_readers` marks only the winner's
  `(segment_id, doc_id)`; `execute_search` intersects that mask with the
  segment bitmap. Search returns one hit. (T01, T04, T14, T23)
- **Counterexample:** two live rows pointing at the same physical document.
  **Response:** rejected as `CorruptCommittedState` before publication. (T29)

## P9-I02 — revisions strictly increase; replay preserves

- **Counterexample:** delete a key then reinsert; a naive implementation might
  restart at revision 1. **Response:** revision = candidate revision + 1, where
  deleted rows retain their revision. (T02, T03)
- **Counterexample:** revision `u64::MAX` then a new mutation. **Response:**
  `checked_add` maps to `RevisionOverflow` with no state change. *Not
  dynamically injected through the public API.* `[NOT COVERED — code path only]`

## P9-I03 — deterministic idempotency across restart

- **Counterexample:** reuse a token with a changed multi-value order.
  **Response:** the fingerprint length-delimits field states and every typed
  value; `Multi` ordering is encoded positionally. Reuse yields
  `IdempotencyConflict`. (T08)
- **Counterexample:** crash after accepting a replay entry but before commit.
  **Response:** only the committed ledger is authoritative after restart;
  uncommitted entries are lost. (T09)
- **Counterexample:** a full replay ledger silently evicts an old entry.
  **Response:** a new idempotency request is rejected with `ResourceLimit`
  before admission. (T34)

## P9-I04 — refresh volatile, commit atomic

- **Counterexample:** insert then reopen before commit. **Response:** reopen
  reads only `CURRENT`; the uncommitted document is gone. (T10)
- **Counterexample:** delete-only commit creates an empty segment.
  **Response:** state changes and `CURRENT` advances with `segments_added = 0`.
  (T11)
- **Counterexample:** failure after installing segments/state/manifest but
  before `CURRENT`. **Response:** old `CURRENT` remains authoritative and the
  writer is retryable; orphan objects are retained. (T12)
- **Counterexample:** `CURRENT` replaced but durability unacknowledged.
  **Response:** writer is poisoned with `RecoveryRequired`; reopen reconciles
  from `CURRENT`. *Indeterminate-post-replacement path not dynamically injected.*
  `[PARTIAL — T36 covers the pre-CURRENT barrier only]`

## P9-I05 — old snapshot/PIT immutability

- **Counterexample:** a PIT created before an upsert/delete sees the new
  version. **Response:** masks are immutable per snapshot. (T14, T15)
- **Counterexample:** compaction mutates a segment object a PIT holds.
  **Response:** compaction writes a new segment object; old snapshots keep the
  old bytes and masks. (T26)

## P9-I06 — all query paths and BM25 use the effective mask

- **Counterexample:** a `NOT` clause resurrects a deleted document.
  **Response:** the live set in `execute_segment` is the effective mask, so
  negative-only evaluation cannot produce a dead doc. (T17, T19)
- **Counterexample:** deleted documents inflate `doc_freq`/`avgdl`.
  **Response:** `compute_stats` filters by the effective mask for both persisted
  and legacy paths. (T18)
- **Counterexample:** prefix/glob/regex/fuzzy use a stale live bitmap.
  **Response:** all expansion paths share the same `live` slice. (T17)

## P9-I07 — lossless compaction

- **Counterexample:** an indexed-but-not-stored field is lost because merge
  rebuilds from stored records. **Response:** merge re-encodes decoded postings
  (with positions) directly and never re-analyzes. (T20)
- **Counterexample:** merge drops columns, nulls, stored values or revisions.
  **Response:** stored/columns are remapped from decoded values; revisions come
  from the authoritative state; tombstones/replay are copied. (T21, T22)
- **Counterexample:** merge changes BM25 scores. **Response:** surviving docs
  and stats are identical. (T24)

## P9-I08 — corrupt/missing state fails closed

- **Counterexample:** a missing sidecar falls back to all-live. **Response:**
  `read_verified` fails with a typed error before any fallback. (T27)
- **Counterexample:** unsorted/duplicate/unknown-status rows decode
  successfully. **Response:** the decoder rejects them. (T28)

## P9-I09 — reclamation cannot remove reachable objects

- **Counterexample:** a single `PinCounter` is treated as proof of no readers.
  **Response:** no online deletion exists; `has_deletable_objects()` is always
  false. (T31, T32)
- **Counterexample:** an orphan from a crash is deleted automatically.
  **Response:** unreferenced objects are `UNKNOWN`. (T33)

## P9-I10 — bounds/cancellation fail atomically

- **Counterexample:** a state over the byte budget is partially published.
  **Response:** the state is encoded and size-checked before any install. (T34)
- **Counterexample:** merge cancellation leaves a partial `CURRENT`.
  **Response:** merge builds all bytes before installing and publishes
  `CURRENT` last. *Cooperative cancellation inside merge is not implemented.*
  `[NOT COVERED]`

## P9-I11 — legacy readability

- **Counterexample:** a v1 manifest is rejected because the decoder assumes a
  state reference. **Response:** versions 1 and 2 are both accepted; v1
  synthesizes state in memory. (T25, T37)

## P9-I12 — explicit retention

- **Counterexample:** a clock-driven TTL deletes documents on restart.
  **Response:** the only hook takes explicit keys and a reason; no clock is
  read. (T38, T39)

## P9-I13 — writer reloads `CURRENT` under lock

- **Counterexample:** a stale `Index` handle's writer trusts its cached
  generation. **Response:** `IndexWriter::open` reads `CURRENT` after acquiring
  the lock. (T40)
- **Counterexample:** two writers both succeed. **Response:** the second gets
  `WriterBusy`. (T41)

## P9-I14 — no remote/distributed/vector behavior

- **Counterexample:** PR 9 imports a RustFS/S3 or distributed type.
  **Response:** no such dependency or import was added; `Cargo.toml` is
  unchanged except for the new benchmark target. (T42)
