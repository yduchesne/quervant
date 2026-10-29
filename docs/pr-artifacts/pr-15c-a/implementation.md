# PR 15C-A implementation record

Branch `dev/pr15c-a-immutable-segment`, base `main` `42b1944…`.

## Change list

### S1 — norms storage normalization (`b807ce6`)

`crates/quervant-core/src/segment/norms.rs`

- `FieldNormsReader.fields` changed from `BTreeMap<u32, FieldNorms>` to a
  strictly ascending `Vec<(u32, FieldNorms)>`.
- `field()` uses `binary_search_by_key`; `field_ids()` iterates the vector;
  missing-required-scoring-field detection uses a binary search.
- Strictly-increasing field-id validation, duplicate rejection, declared-vs-decoded
  total cross-checks, `DecodeBudget` accounting and every public accessor are
  unchanged. The outer field vector is now explicitly budgeted and
  `try_reserve_exact`-allocated.
- New tests: `sorted_vec_lookup_matches_former_map_semantics`,
  `empty_and_singleton_field_sets_are_supported` (plus the retained A5-T13/14/15
  adversarial cases).

### S2–S4 — immutable state, accounting, snapshot cache (`9fe9470`)

`crates/quervant-core/src/segment/reader.rs`

- New crate-private `VerifiedSegmentState` with exactly the 14 prescribed fields
  plus an `Option<MetadataReservation>` accounting owner. `SegmentReader` now
  holds `shared: Arc<VerifiedSegmentState>` and the three query-local
  `RefCell<Option<Rc<Vec<…>>>>` caches; all existing accessors delegate and keep
  their names, arguments and return types.
- `SegmentReader::open(Vec<u8>, SegmentLimits)` and `open_directory` still perform
  the full validation (byte-length limit, `parse_container` envelope + section
  digests + structure, feature/section agreement, dictionary↔postings extents,
  column geometry, stored header, every metadata decoder). They now produce the
  shared state directly (`VerifiedSegmentState::validate`) with no meter.
- `VerifiedSegmentState::build_cached` runs the *same* parser and decoders against
  the snapshot's `Arc<Vec<u8>>` (no byte copy), reserving a candidate allowance
  first, charging each retained allocation before it is made, reconciling the
  measured capacities, and attaching the final reservation to the state.
- `parser_allowance` bounds the parser-side retained vectors by
  `max_sections`/`max_features` plus the state `Arc` payload. `decode_allowance`
  bounds each decoded metadata class from the validated section lengths and the
  document format's proven minimum encoded widths (schema 13, dictionary field 12
  / term 26, norms `20 + doc_count` per field and ≥1 byte per length, JSON-path
  occurrence 10 with `capacity < 2·len + 4` for push growth, spatial field 20 /
  node 77, geo bounds 55, remap `2·doc_count·8`). All arithmetic is checked.
- `#[cfg(test)]`-only `candidate_allowance_for_test` exposes that bound so the
  exact/one-over admission boundary is tested rather than estimated.

`crates/quervant-core/src/segment/metadata.rs` (new)

- `MetadataBudget` (`Arc<AtomicU64>` used + exact `u64` limit, checked CAS
  reserve, RAII release), `MetadataReservation` (owned by the immutable state so
  it releases on the last `Arc` drop, including when a guard outlives its
  snapshot), and `MetadataMeter` (candidate allowance, `extend`, per-allocation
  `charge`/`charge_vec`/`charge_str`/`charge_arc`, and `finalize(measured)` which
  releases the unused allowance and refuses a measured charge above the
  allowance). Checked helpers `element_bytes`, `capacity_bytes`, `accumulate`,
  `count_bound`.

`crates/quervant-core/src/index/snapshot.rs`

- `metadata_budget: Arc<MetadataBudget>` with `limit = reader_copy_limit` exactly
  (the existing constructor argument; no call site and no `IndexLimits` field
  changed), and `slots: Vec<SegmentCacheSlot>` in canonical segment order.
- `SegmentCacheSlot { state: Mutex<SlotState>, ready: Condvar }` with
  `SlotState = Empty | Building | Ready(Arc<VerifiedSegmentState>)`.
- `open_segment_reader` keeps the existing full encoded-length admission charge
  **before** acquisition (a hit never reduces it). `acquire_reader` returns a
  fresh query-local reader from `Ready`, waits on the `Condvar` while `Building`
  (rechecking the predicate), or transitions `Empty → Building` and builds outside
  the lock. `Ok(None)` (optional capacity/allocation failure) releases everything,
  resets the slot, notifies and runs the original verified uncached reader; true
  corruption propagates its typed error.
- `SlotBuildGuard` restores `Building → Empty` and notifies on error or unwind,
  recovering a poisoned guard only for that cleanup. `acquire_reader` fails closed
  with `IndexError::CorruptCommittedState` on a poisoned mutex.
- Test-only: `for_test` (independent admission/metadata caps), `metadata_used`,
  `metadata_budget_handle`, `verification_count`, `set_build_fault`,
  `slot_is_ready`, `slot_is_unlocked`, `poison_slot`.

`crates/quervant-core/src/segment/{schema,remap,dictionary,norms,spatial,json_paths}.rs`

- Public decoders keep their exact signatures and delegate to new crate-private
  `*_metered` variants that charge every retained allocation before allocating.
- Each type exposes a crate-private `metadata_charge()` computing its measured
  retained charge from actual capacities.
- `JsonPathDirectory` handling moved from `Rc` to `Arc` (reader field,
  `JsonPathsReader::new`, `open_json_paths`); `JsonDocOffset` is now
  `pub(crate)`. The non-metered `decode_directory` remains as a test-only helper.

### S5 — production-path integration witness (`d54e220`)

`crates/quervant-core/tests/pr15c_a_segment_state.rs` (new) — five tests covering
repeated-query oracle parity, PIT parity, old-snapshot isolation after a commit,
real native-filesystem commit/restart/reopen parity, and key-accessor parity,
each also comparing the cached reader with an independent
`SegmentReader::open` over the same bytes.

## Invariant → test summary

| Invariant | Witness |
|---|---|
| VSR-I01 exact bytes | `g1_01`, `g1_02`, `g3_01`, `g3_06`, `pr15c_a_t01` |
| VSR-I02 fail closed | `g3_02`–`g3_05`, `g3_04b`, `g4_04`, `g4_05` |
| VSR-I03 snapshot isolation | `g3_07`, `pr15c_a_t02`, `pr15c_a_t03` |
| VSR-I04 thread safety | `g1_01`, `g4_01` (2/8/32 threads) |
| VSR-I05 bounded memory | `g2_01`, `g2_02`, `g2_04`–`g2_12`, `metadata::tests` |
| VSR-I06 no execution lock | `g4_09` |
| VSR-I07 compatibility | `g1_03`, `g1_04`, `pr15b_diagnostics`, `pr15c_a_t01…t05` |
| VSR-I08 provider parity | **BLOCKED — ENVIRONMENT** (no live RustFS); local filesystem covered by `pr15c_a_t04` |
| VSR-I09 safe cleanup | `g2_10`, `g4_06`, `g4_07`, `g4_08` |
| VSR-I10 fallback valid | `g2_01`, `g2_02`, `g2_04`, `g2_12`, `g4_05`, `g1_05` |

## Baseline / feature / regression status

- Baseline (`42b1944`): all suites green; recorded in `preflight.md`.
- Post-change: 2145 workspace tests pass on stable and on MSRV 1.85; the frozen
  PR 15B oracle suite (16 tests) and the PR 15A regression/oracle suites are
  unchanged and green; no fixture, dataset or benchmark manifest was modified.
- Regression: none observed. No pre-existing failure was found beyond the
  `docs/TESTING.md` conflict-marker document defect (F3, untouched).
- Coverage: 91.66% workspace lines (floor 85%), gate executed exactly as CI does.

## Residual risk and deferred work

1. **Cache occupancy on large dictionaries.** The candidate allowance is derived
   from section lengths and minimum encoded widths, so it over-estimates retained
   memory for term-dense segments (roughly 3× for a dictionary with ~10-byte
   terms). A segment whose allowance exceeds `reader_copy_limit` therefore uses the
   verified uncached path. This is specified behaviour ("may conservatively reject
   caching") but means the optimisation is not guaranteed for very large
   dictionaries. A tighter exact pre-scan allocation bound would be an
   architecture amendment, not a coding decision.
2. **Poison is permanent for a slot.** After a panic inside a slot critical
   section, that slot fails closed for the remainder of the snapshot's life. This
   is deliberate (fail closed, no negative cache removal), and the critical
   sections contain no panicking operations in practice.
3. **Aggregate metadata residency** is `concurrently retained snapshots ×
   reader_copy_limit`; no global LRU or cross-snapshot eviction was introduced
   (VSR-AD-009).
4. **Performance qualification is out of scope.** PR 15C-B owns the same-host,
   3-trial Criterion before/after campaign. This PR only proves, deterministically,
   that repeated opens no longer re-verify (exactly one verification per snapshot
   slot, no byte clone on hits) and that no oracle result changed. No timing win is
   claimed here.
5. **Architecture document status** (`docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md`)
   intentionally still says "not yet implemented on `main`" until a reviewer
   accepts the implementation.

## C15A-01 fixup (`aca8ed1`)

`crates/quervant-core/src/segment/reader.rs::decode_allowance` now charges the two
retained doc-id remap `Vec<u64>` allocations unconditionally instead of only when
a `SortedRemap` section is present, because `decode_metadata` retains both vectors
for the explicit decoder and `DocRemap::identity`. Checked arithmetic, the typed
overflow error and every other section allowance are unchanged; no other
production file, format, limit, admission or metering code changed. Regression and
production-path witnesses are recorded in
[`fixup-c15a01.md`](./fixup-c15a01.md).

## C15A-02 / C15A-03 fixup (`6cdbf93`)

* `segment/json_paths.rs`: `JsonPathsReader::decode_directory_metered` now appends
  retained offset groups through the private `push_doc_offset` helper, which
  charges the exact capacity delta before `try_reserve_exact` and charges any
  allocator excess before the insert; `DecodeBudget` accounting and unmetered
  callers are unchanged.
* `segment/remap.rs`: new private `DocRemap::identity_fallible` (both arrays
  reserved fallibly before filling) and `pub(crate) identity_metered` (charges the
  two arrays once, then reconciles allocator excess); `decode_metered` state `0`
  uses it.
* `segment/reader.rs`: the absent-`SortedRemap` branch uses `identity_metered`;
  the C15A-01 unconditional allowance is untouched.
* No change to `segment/metadata.rs`, the snapshot state machine, formats, limits,
  public APIs or telemetry. The scoped allocation audit recorded six further
  infallible-but-precharged sites (F1–F6) for a separate fixup decision.

## F1–F6 fallible-allocation fixup (`b3c72b9`)

`segment/format.rs` (new crate-private `reserve_exact_vec`, used by the parser's
section directory and feature lists), `segment/reader.rs` (`copy_slice_fallible` for
the retained section/feature copies, fallible geo-bounds reservation),
`segment/schema.rs` (`pub(crate) copy_str_fallible` for field names and binding
id/version), `segment/dictionary.rs` (terns via the same helper) and
`segment/remap.rs` (`reserve_pair`/`reserve_pair_with` used by `identity_fallible`
and the explicit `SortedRemap` state-1 decoder). All named retained allocations now
reserve fallibly before allocating and keep their existing precharges, allowance
reconciliation, typed errors and fallback classification.

F4 (the two accounted `Arc` payloads) is a preauthorized HARD STOP: `Arc::try_new`
is unstable on the workspace MSRV 1.85.0 and on stable 1.98.1 (E0658, issue
#32838), and unsafe/custom-allocator workarounds are forbidden. PR acceptance
therefore remains blocked pending an F4 architecture decision.
