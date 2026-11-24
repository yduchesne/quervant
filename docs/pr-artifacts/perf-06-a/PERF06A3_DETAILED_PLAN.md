# PERF-06-A3 — Versioned Split Postings Streams and Block Directory

**Detailed coding-agent execution contract — DESIGN FROZEN; NOT EXECUTED**  
**Project:** `yduchesne/quervant` · `v0.1-perf` · **PERF-06-A3**  
**Planned implementation PR:** a **new, separately reviewable PR** titled `PERF-06-A3: Versioned split postings streams and block directory`  
**Prescribed branch:** `dev/perf06-a3-split-postings` from the accepted `origin/main` **after PERF-06-A2 is merged**; target `main`, not PR #119 or PR #121.  
**Reference for design:** PERF-06-A2 implementation PR [#121](https://github.com/yduchesne/quervant/pull/121), including its reviewed documentation-only correction, at head `4a7108a538c692faf87befb3ee6474c0ead6e3e3`. **Do not treat this as proof of merge.**  
**Source audit:** 2026-11-23; actual A2-branch Rust/source and actual current-`main` authoring guide inspected.  
**Planning authorities:** `docs/PERF_OPTIMIZATION_ROADMAP.md` (§ PERF-06-A3 and overarching execution approach); `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`; `docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md`; `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`; `AGENTS.md`; `docs/TESTING.md`.

> **IMPORTANT — user-specified assumption:** For **designing this document**, assume A2 has been accepted and merged. At inspection time PR #121 was still **open**. The implementation agent MUST verify GitHub's actual `MERGED` state and the accepted source before changing code. If A2 is not merged, report `PERF06_A3_DEPENDENCY_BLOCKED_A2_UNMERGED` and perform documentation/read-only audit only. Do **not** cherry-pick A2, implement on its unmerged branch, or infer merge from CI.

---

## 0. Operating authorization, non-goals, and exit

**Continuous execution authorization:** Once this plan is expressly approved for execution and its P0 dependency/source gate passes, execute **all prescribed stages** through tests, evidence, and draft PR publication without requesting routine confirmation. Automatically continue after a successful preflight, stage, approved AUTO-RESOLVE rule, or routine QA checkpoint. Classify exceptions using §13. STOP affected work only for a scoped HARD STOP, a missing substantive human decision, or an essential external dependency. Keep performing provably independent safe work during a DEFER/STOP in another path. Never treat a progress checkpoint as permission to ask for confirmation.

**Agent's job:** implement **the architecture specified in this file**, not choose an encoding, block size, migration strategy, skip policy, error contract, or test scope. Any unlisted choice that changes behavior, persisted layout, resource bounds, or error/validation timing is a HARD STOP. Section §13 contains all preauthorized alternatives and decisions. The agent may make bounded Rust syntax/borrow-checker repairs that do not change the frozen algorithms, contracts, or file allowlist; record them explicitly.

**A3 goal:** replace new segments' interleaved per-document postings blocks with **versioned split document-ID, frequency, and positional byte streams** and a validated **128-document directory**, while preserving the A2 lightweight/full readers, exact search semantics, old persisted index readability, corruption checks (including nonwinners), and other existing contracts. The compiler emits **new-format segments by default**. Older segments remain readable **only** to support mixed indexes and the checked-in legacy fixtures; there is no customer migration obligation. Rebuilding an index from documents is allowed.

**Not authorized:** any real query-performance acquisition (warm, cold, A/B, B/B), profiler, Criterion execution, Tantivy/Lucene comparison, new index/segment compression algorithm, WAND, SIMD, query executor rewrite, cache redesign, new `advance` skip jumps, changed BM25/A1 math, altered A2 corruption policy, new feature toggles/CLI settings, release/merge, or A4 qualification. `cargo bench --no-run` is allowed as a compile-only CI gate.

**Success disposition:** `PERF06_A3_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW` only when all specified source, local, real-boundary, mandatory CI, correctness, security/resource, and documentation gates have *actually executed and passed*. A draft PR may be published with `..._CI_PENDING` or `..._INTEGRATION_BLOCKED` but cannot be called ready. Do not merge or begin A4.

---

## 1. Actual repository facts and reconciliation

### 1.1 A2-head facts (verified, not guessed)

1. `crates/quervant-core/src/segment/postings.rs`: legacy `encode_postings_block`, `PostingsReader::new`, full `.next[_with]`/`.advance[_with]`, A2 `DocFreqPosting`, consuming `.into_doc_freq()`, and `DocFreqPostingsReader::next[_with]`. A2 uses **one shared `read_one_with`** for full/lean modes; every positional varint is still validated and the historical `check_alloc::<Occurrence>(freq)` preflight still applies even to lean readers.
2. `segment/build.rs::SegmentBuilder::build`: analyzes documents, constructs a `(field_id, term) -> Vec<Posting>` map, encodes each term via the **legacy** `encode_postings_block`, concatenates blocks in one `SectionKind::Postings` section; `DictionaryEntry` retains `(term, doc_freq, postings_offset, postings_length)`. Builder emits norms, STORED blocks and the rest of the established sections/features.
3. `segment/reader.rs::postings_for_entry`: bounds-checks dictionary extent, creates a legacy `PostingsReader::new`, rejects dictionary/posting count disagreement. `decode_metadata` validates required features and dictionary/postings section presence and extents, but intentionally does not eagerly decode each posting's occurrences.
4. `segment/format.rs`: container major/minor `1.0` (`FORMAT_MAJOR=1`, `FORMAT_MINOR=0`), existing required-feature registry IDs `0x0001`..`0x000D`; `FEATURE_STORED_BLOCKS=0x000D`. `SectionKind::Postings=0x0003`. Container digests already cover the immutable section; no need to invent a second checksum layer.
5. `segment/dictionary.rs`: dictionary payload **version 1**; its entries already provide exact per-term POSTINGS extents. Keep dictionary v1, fields, binary layout, and lookup API.
6. Search consumers: exactly four A2 doc/freq cursors—`execute.rs::build_leaf_data` Term/MultiTerm and `score.rs::compute_stats` partial-live and legacy-norms paths. `execute.rs::build_phrase` still consumes full positional `Posting.occurrences`. A1 prepared IDF and PERF-05 scoring/candidate ownership are already accepted inputs.
7. `tests/segment_golden.rs` pins an old **legacy** `golden.seg` and a separate **norms-bearing legacy** `golden_norms.seg`, with a fixed SHA-256; these must **NOT** be regenerated or silently repinned. Existing `pr15i_b_stored.rs` shows how to reconstruct a container while preserving unrelated sections, feature lists and digests for adversarial format tests.
8. CI `.github/workflows/ci.yml` runs default/all-features Rust and 85% coverage, Rust 1.85 MSRV, and a real pinned RustFS job. `crates/quervant-core/tests/pr13_remote.rs` already has an ignored RustFS module, a `real_index` helper, and is executed by that job.

### 1.2 Immutable preflight anchors

All listed Git **blob** SHAs were verified on the A2 branch at `4a7108a538c692faf87befb3ee6474c0ead6e3e3`. After the A2 merge, check the actual blobs at the new `origin/main`; a merge commit may differ, but **these source blobs must match** unless a human approves a revised plan. Comparison against *blob IDs* avoids guessing whether GitHub used a merge/squash strategy.

| Path | Required A2-source Git blob SHA |
|---|---|
| `crates/quervant-core/src/segment/postings.rs` | `3600a59e38171cc0737bf5f65c79769212b07d0e` |
| `crates/quervant-core/src/segment/build.rs` | `b6239f6fcff16b41fe6b9cc59e0ff231d6fad3cb` |
| `crates/quervant-core/src/segment/reader.rs` | `aa69f2bebb9746f44254a702438e91cea9a9b7a5` |
| `crates/quervant-core/src/segment/format.rs` | `6932edd210e3cc480342f11c4e4ca7ae5ec39e77` |
| `crates/quervant-core/src/segment/dictionary.rs` | `0e04d73b7b18c3f356b1c472790710e0d153ab81` |
| `crates/quervant-core/src/segment/limits.rs` | `bf222b67e0675aadf6137642748d6b7f4c781328` |
| `crates/quervant-core/src/segment/tests.rs` | `87c201b4280166992803d2765ea63cda37e4b60d` |
| `crates/quervant-core/src/search/execute.rs` | `0681bce3b49afc16ec01a0e4212b0ad9c42ec176` |
| `crates/quervant-core/src/search/score.rs` | `249122b50e2504593dc33056965dee366f31ab4b` |
| `crates/quervant-core/tests/segment_codec.rs` | `6b62abc10def4cbe3df7ee6f1b56e35eeac55a84` |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | `b39b024955898d842ea50d0cc6a8cb47e2a1c7ca` |
| `crates/quervant-core/tests/pr13_remote.rs` | `c0722dacfb7d94b05e2f48f011a352daec248363` |
| `crates/quervant-core/tests/segment_golden.rs` | `eca5a703d0f2f45aa79c7d4456238657655bf287` |
| `docs/ARCHITECTURE.md` | `bf20b49a8d07fcea7f2d015423f9ca211deaf517` |
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` |
| `.github/workflows/ci.yml` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` |

**Strict reconciliation:** the above table is a **reference for the assumed A2 merge**, not permission to begin from an unmerged head. Once PR #121 is shown MERGED, fetch/fast-forward `origin/main`, verify the merge's resulting source and capture its full SHA as `BASE_MAIN_SHA`. Any discrepancy to A2-relevant source blobs, missing A2 API, new posting consumer, or concurrently opened A3 implementation PR triggers **D03 HARD STOP**; no agent-designed adaptation. An unrelated documentation-only later `main` commit does not alter these blob requirements.

---

## 2. Architecture invariants and traceability

Each `INV` is **falsifiable**; code, tests and evidence must be linked in the execution report. “Coverage green” alone does not satisfy one.

| ID | Invariant and negative property | Implementation | Required evidence |
|---|---|---|---|
| **INV-01** | New segments carrying lexical postings use **only** the new split payload; required feature and section agree. No accidental mixed codec within a segment. | S1/S3/S4 | U01/U11; I01/I03 |
| **INV-02** | v2 decodes the **same ordered `(doc_id,freq,Occurrence...)`** as legacy for a logical posting sequence; every doc ID strictly increases across block boundaries; `freq_total` is exact in v2. | S2/S3 | U02/U03/U05/U10; I01 |
| **INV-03** | Both full and A2 lean v2 cursors validate **every positional varint and relationship** before returning its posting, even for dead/nonwinners; malformed data never becomes a successful hit. | S3 | U06/U07/U08; I03 |
| **INV-04** | v2 DocFreq mode has **zero positional `Vec::reserve` / occurrence pushes and zero full `Posting` clones**; full mode still caches the current posting for `.advance[_with]`. | S3 | U04; A2 witness tests |
| **INV-05** | `next`, `next_with`, `advance`, `advance_with`, `into_doc_freq`, EOF and cancellation remain compatible with the A2 public contract; no unvalidated skip/jump. | S3 | U04/U09; I02 |
| **INV-06** | `check_entries`, frequency limit, hypothetical `check_alloc::<Occurrence>(freq)`, and all existing search work/ledger checks remain; new block/directory lengths have **checked arithmetic and bounded/no allocations**. | S2/S3 | U07/U09/U10; I02; old B4 budget tests |
| **INV-07** | New feature + decoder version are explicit; old frozen interleaved segments remain independently readable next to split segments, and normal newly written multi-segment generations/snapshots remain consistent. No retrofit of old bytes. | S1/S3/S4 | U01/U11; I03/I04; golden + SC06/PIT suites |
| **INV-08** | Exact search `total_hits`, doc keys, order/ties, BM25 **bit pattern**, phrase positions, Boolean/multiterm expansion, live filtering, PIT/cursor, mutation/reopen remain unchanged. | S2–S5 | I02/I03/I04; existing SC/PR07/PR14/M tests |
| **INV-09** | Segment header/section/dictionary/manifest identities outside POSTINGS plus one required feature are unchanged; committed data are immutable, no new remote path or cache policy. | S1/S2/S4 | diff audit; I01/I04/I05 |
| **INV-10** | Directory entries and the stream boundaries are deterministic, canonical, nonoverlapping, exact-length, independently validated; malformed directory/table is rejected without unbounded allocation/panic. | S2/S3 | U03/U05/U06/U10 |
| **INV-11** | Changes to new-format segment size/indexing cost are **reported as structural descriptors only**; they do not masquerade as timed query improvements. | P5 | audit/report; no benchmark artifacts |
| **INV-12** | Every mandatory A3 local and applicable real RustFS gate actually executes and passes; failed attempts and unverified gates are recorded without positive relabeling. | P0–P7 | CI/logs, coverage and final report |

**Pre-implementation correctness gate:** before editing production Rust, map INV-01–INV-12 to the real source, U/I cases and likely failure boundaries; challenge: 0/1/127/128/129/256/257 docs, positional/doc-only, mixed fields, `tf>1`, 128→129 doc monotonicity, malformed last occurrence in a dead doc, zero/oversized frequency, short/extra streams, overlapping offsets, forged skip first ID, table count mismatch, invalid required feature, repeated EOF, cancel-before-EOF, PIT, deleted/upserted docs and fresh RustFS cold bootstrap. Record the challenge and apply §13. A mismatch requiring new semantics is HARD STOP, not an excuse to invent a codec.

---

## 3. Frozen physical design — DO NOT CHANGE

### 3.1 Versioning and feature agreement

**Do not modify** `FORMAT_MAJOR`/`FORMAT_MINOR`, the container magic, the dictionary version, dictionary entry format, section enum or `SectionKind::Postings` numeric ID.

1. In `segment/format.rs`, add **exactly** `pub const FEATURE_SPLIT_POSTINGS: u16 = 0x000E;` (the next free feature ID). Add `(FEATURE_SPLIT_POSTINGS, 1)` to `SUPPORTED_FEATURES`. Its meaning: every dictionary-referenced term in this segment has the **split postings v1** payload below. This is a *required* feature, not optional, on new nonempty-postings segments.
2. `SegmentBuilder::build` continues emitting `(FEATURE_POSITIONAL,1)` when it previously did. It additionally requires `(FEATURE_SPLIT_POSTINGS,1)` **iff** the segment has a DICTIONARY+POSTINGS pair. On empty/no-lexical-postings segments, neither the new feature nor the two sections appears. Do not add the feature to mutation-state sidecars, manifests globally, or preexisting fixture bytes; the normal index manifest already copies required features from actual segments.
3. `SegmentReader::decode_metadata` rejects `FEATURE_SPLIT_POSTINGS` without **both** DICTIONARY and POSTINGS using `SegmentError::Corrupt { context: "split postings", detail: "split postings feature requires dictionary and postings".to_owned() }` before publishing verified immutable state. Existing dictionary/postings pair validation remains intact.
4. `SegmentReader::postings_for_entry` continues slicing only the dictionary-advertised extent and verifying `posting_doc_count() == entry.doc_freq`. **Dispatch on the verified required-feature set:** `(FEATURE_SPLIT_POSTINGS,1)` present → `PostingsReader::new_split(slice, doc_count, limits)`; absent → existing `PostingsReader::new(slice, doc_count, limits)` (legacy). An unknown required feature still fails in `ensure_supported_features()`; no trial-decoding or byte sniffing fallback. A v2 marker under a featureless legacy segment fails closed as invalid occurrence kind. The feature-present v2 constructor rejects legacy markers, also without fallback.
5. `PostingsReader::new` remains the **public legacy block constructor** for existing direct raw-fixture tests. Add `pub(crate) fn new_split(...)` for the new format, used only by `SegmentReader`. Keep A2 `DocFreqPosting`, `DocFreqPostingsReader`, `.into_doc_freq()` and the full `.advance[_with]` API unmodified. Do not add another factory/cache in `SegmentReader`.

### 3.2 Per-term split-postings v1 exact byte contract

Every **dictionary entry's POSTINGS extent** contains exactly one whole term payload. All fixed integers below are **little-endian** using existing `ByteWriter`/`ByteReader`; every variable integer is canonical unsigned LEB128 via their existing `varint` methods.

**Header: exactly 56 bytes** (no alignment padding):

| Offset | Wire field | Required value / meaning |
|---:|---|---|
| 0 | `marker:u8` | `2` for doc-only; `3` for positional. Legacy markers `0`/`1` are forbidden with the new feature. |
| 1 | `payload_version:u8` | Exactly `1`. |
| 2 | `flags:u16` | Exactly `0`; any nonzero bits rejected (`UnknownFlags` with `context:"split postings"`). |
| 4 | `block_docs:u32` | **Exactly `128`**, fixed for A3. Not an option or tuning parameter. |
| 8 | `block_count:u32` | Exactly `ceil(posting_doc_count/128)` (checked arithmetic). |
| 12 | `reserved:u32` | Exactly `0`. |
| 16 | `posting_doc_count:u64` | `1..=min(segment_doc_count,max_postings_per_term)`; distinct from total segment doc count. |
| 24 | `freq_total:u64` | Exact checked sum of all posting frequencies; at least `posting_doc_count`. |
| 32 | `doc_stream_len:u64` | Length in bytes of the doc-ID stream. |
| 40 | `freq_stream_len:u64` | Length in bytes of the frequency stream. |
| 48 | `pos_stream_len:u64` | Length in bytes of the occurrence stream; exactly **0** for doc-only. |

**Physical bytes immediately after the 56-byte header, in this order:**

```
[doc IDs: doc_stream_len bytes]
[term frequencies: freq_stream_len bytes]
[positional occurrences: pos_stream_len bytes]
[skip-ready block directory: block_count * 40 bytes]
[EOF — no trailing padding/bytes]
```

The absolute end offset must be checked as `56 + doc_len + freq_len + pos_len + (block_count * 40) == extent.len()` using `checked_add`/`checked_mul` and `usize::try_from` before creating slices. No wrapping `as usize` from unchecked untrusted lengths; fail with typed `SegmentError::Corrupt` (`context:"split postings"`) for overflow or mismatch. `doc_stream_len >= posting_doc_count`, `freq_stream_len >= posting_doc_count` (one byte minimum per canonical varint); positional stream must contain at least `5 * freq_total` bytes (five minimum-byte fields per occurrence) when marker=3, checked for overflow. These are **new-v1-only structural requirements**, not changes to legacy error behavior.

**Document stream:** for each 128-document block, the first entry is the **absolute** physical `doc_id` varint. Remaining entries in the same block encode a **strictly positive delta** from the previous doc ID. At a block boundary the delta base resets, but the absolute first doc ID must still exceed the last doc ID of the preceding block; it must be `< segment_doc_count`. No reverse or duplicate doc IDs. First entry of the whole term may be doc ID 0. All 128-entry boundaries are based on *posting ordinals* within this term, not segment document IDs.

**Frequency stream:** one canonical `u64` frequency varint per posting, `freq >= 1` and `freq <= limits.max_decoded_entries()`. No per-block frequency compression. Check `freq_total` at new-format EOF; reject mismatch with `SegmentError::Corrupt {context:"split postings", detail:"frequency total mismatch".to_owned()}`. Never change legacy's historical lack of this end check.

**Position stream:** marker `3`: for every posting, write its `freq` occurrences consecutively, in the existing five-varint order:

```
(position_delta, position_length, value_index, start_offset, end_offset)
```

The first `position_delta` is the **absolute** position *within that posting*; subsequent deltas are positive from the preceding position. Validate exactly the old A2 rules: checked position addition/overflow; strictly increasing positions; nonzero `position_length`; nondecreasing `value_index`; `start_offset <= end_offset`; canonical/truncation checks from `ByteReader`. Reset position/value-index history at **each posting**, not at each 128-doc block. `freq` must equal occurrence count for positional source; reject encoding mismatches as the current legacy encoder does. Marker `2`: no positional stream, and `Posting.occurrences` is empty in full mode.

**Block-directory entry: exactly 40 bytes**, **appended after all three streams**, one per block in ordinal order. Fields:

| Entry offset | Field | Meaning |
|---:|---|---|
| 0 | `first_doc_id:u64` | Absolute first physical doc ID of the block. |
| 8 | `first_posting_ordinal:u64` | Exactly `block_index * 128`. |
| 16 | `doc_byte_offset:u64` | Exact offset into doc-ID stream **before** its first block varint. |
| 24 | `freq_byte_offset:u64` | Exact offset into frequency stream **before** its first block varint. |
| 32 | `pos_byte_offset:u64` | Exact offset into positions stream **before** the first occurrence of the block; **0 for all doc-only blocks**. |

**Directory geometry rules:** entry 0 has ordinal=0, doc/freq offsets=0 and pos offset=0. Every entry's ordinal is exactly `index*128`. `first_doc_id` is strictly ascending across entries and `<segment_doc_count`. Doc and frequency offsets are strictly ascending after entry 0 and each `<` its stream length; positional offsets are strictly ascending for positional blocks (positive frequency guarantees ≥1 occurrence) and each `<pos_stream_len`; doc-only offsets remain exactly zero. Reader constructor validates all directory entries using **borrowed slices and `ByteReader`**, *without constructing a `Vec<SkipEntry>`*, before returning; then decoder verifies each directory entry's doc ID and actual three stream offsets **at its block boundary**. The pair of checks catches forged/misaligned offsets as well as inconsistent stream contents.

**Important deliberately limited use of directory:** A3 creates and verifies **skip-ready** directory metadata, but **does NOT jump over postings**. Existing `.advance[_with]` continues linearly scanning/validating all intervening postings through `.next_with`, preserving corruption detection and cancellation on skipped/nonwinning candidates. Do **not** make a fast seek, skip corrupt blocks, or claim sublinear advance. A later separately approved design can exploit offsets if it formally addresses full validation obligations. This decision is frozen; it is not for the agent to revisit.

### 3.3 Encoder — exact work and validation

Add `pub fn encode_split_postings_block(segment_doc_count:u64, postings:&[Posting], limits:&SegmentLimits) -> SegmentResult<Vec<u8>>` in `segment/postings.rs`. **Do not change the existing `encode_postings_block` signature or legacy wire bytes.**

Implement with this exact sequence:

1. Extract the **existing** source-data validation rules from `encode_postings_block` into one *private* shared input validator used by **both** encoder functions. Preserve legacy errors: nonempty; term count ≤ `max_postings_per_term` and segment doc count; doc IDs ascending/in-range; frequencies nonzero and checked total; positional source if any occurrences nonempty; then *all* postings in positional mode must have `freq == occurrences.len()`; occurrence position length nonzero, offset order valid, value index nondecreasing, positions strictly increasing. Preserve the existing `encode_postings_block` output and old unit tests bit-for-bit. Do not introduce an algorithm to sort or repair invalid source data.
2. Create four local `ByteWriter`s: `doc_stream`, `freq_stream`, `pos_stream`, `directory`. Before each block's first doc, write the 5 fixed directory fields described above using current stream lengths, first doc ID and posting ordinal. No heap `Vec<SkipEntry>` and no per-posting metadata structs retained.
3. Iterate postings **in original order**. Start a new block when `posting_index % 128 == 0`. At that index write `doc_stream.varint(posting.doc_id)` (absolute). Otherwise write `postings[ordinal].doc_id - postings[ordinal-1].doc_id` using already-validated strict increase. Write each `freq` into `freq_stream`. Encode every positional occurrence in the identical old varint field order and per-posting delta policy into `pos_stream`; doc-only produces no position bytes.
4. Write exactly the 56-byte header (field order in §3.2) followed by `doc_stream`, `freq_stream`, `pos_stream`, then the fixed 40-byte directory. Never write an extra length prefix or per-block trailing sentinel. Check every size/count/offset addition and conversion before constructing/merging the output; use existing `SegmentLimits` and fallible/preflight allocation discipline. `block_count` must fit `u32`, and the resulting term blob must fit configured single-allocation/section safety ceilings; reject with typed `LimitExceeded`, never panic. Do not increase limits to make tests pass.
5. Retain the old encoder as the **legacy fixture generator** only. In `SegmentBuilder::build`, change **only** the per-term call from `encode_postings_block` to `encode_split_postings_block`. Dictionary offsets/lengths are still measured from `postings_body.len()` and **are exact**; don't add a second dictionary or separate segment section.
6. On a builder with zero indexed terms, no new feature/section is emitted. On a nonempty new segment, assert the required feature is present and all blocks use marker 2/3. The builder continues to emit identical non-postings logical values, norms, stored source and column data.

### 3.4 Reader and A2 API — exact state machine

In `segment/postings.rs` **extend the existing** `PostingsReader` with **one private source enum** and the split stream state, rather than adding a second public postings cursor or a new trait:

```rust
// Private implementation types; names are fixed to avoid an agent-chosen hierarchy.
enum PostingStreams<'a> {
    Legacy(ByteReader<'a>),
    Split(SplitStreams<'a>),
}
struct SplitStreams<'a> {
    docs: ByteReader<'a>,
    freqs: ByteReader<'a>,
    positions: ByteReader<'a>,
    block_directory: &'a [u8],
    block_count: u32,
    observed_freq_total: u64,
}
```

The existing `PostingsReader` retains `positional`, `posting_doc_count`, `freq_total`, `docs_read`, `previous_doc`, `segment_doc_count`, `limits`, `current`, `finished`; replace only its legacy `reader: ByteReader<'a>` member with `streams: PostingStreams<'a>`.

- `PostingsReader::new` parses the **old** header exactly as before, yields `PostingStreams::Legacy` and initializes all state identically. It must still reject occurrence-kind markers `2`/`3` when used directly.
- `PostingsReader::new_split` parses and validates the 56-byte v1 header, checked section slices and all block-directory entries as specified. It initializes three independent `ByteReader` streams with `PostingStreams::Split`, no copied payload/metadata, and all shared state identically. It must reject marker `0`/`1`, unknown versions, flags, reserved values, inconsistent counts, corrupt extents or invalid directory.
- Keep **one** A2 `read_one_with(&mut self, cancel, detail:DecodeDetail)` for both full and lean modes. Refactor only the source of varints, not scoring, work counters or ownership. After the existing **first** `cancel_result(cancel)?`, EOF and `limits.check_entries(docs_read + 1)`, obtain doc varint and frequency from the active source. Legacy uses its original single `ByteReader` and original delta policy. Split reads docs/freqs from separate streams; at each `docs_read % 128 == 0` compare current stream positions and the just-read absolute doc ID against the corresponding validated directory entry. Between boundaries decode strictly positive doc deltas; enforce cross-block global monotonicity as well.
- The **one common occurrence-validation loop** reads the five positional components through a small private helper that chooses `Legacy`'s reader or `Split`'s `positions` reader, with **unchanged** contexts (`"position delta"`, `"position length"`, `"value index"`, `"start offset"`, `"end offset"`). Keep the original A2 split between `DecodeDetail::Full` and `::DocFreq` **only** for positional-vector reserve/push and full `Posting` cache clone. Still call `limits.check_alloc::<Occurrence>(freq)` in both modes when positional. Do not pre-validate or discard unread occurrences, and do not add per-occurrence cancellation polls.
- Only after a posting fully decodes and validates may `docs_read` and `previous_doc` advance and, for Split, `observed_freq_total` checked-add `freq`. Existing callback work charging and live filtering are downstream and unchanged. No new resume-after-error behavior.
- At the first request **after** the declared final posting, after the usual `cancel_result`, legacy calls its original `expect_end("postings")`. Split calls `expect_end` on all three respective streams and verifies exact `observed_freq_total == freq_total`; typed new-format mismatch is `Corrupt {context:"split postings", detail:"frequency total mismatch"}`. Then mark `finished = true`, clear cached `current`, return `None`. Further `next` calls return `None` unless cancelled; cancellation **still wins** over EOF.
- `PostingsReader::next`, `.next_with`, `.advance`, `.advance_with`, `.into_doc_freq` and `DocFreqPostingsReader::next[_with]` remain **externally identical** to A2. `.advance[_with]` remains the **original sequential loop**, including reuse of current full posting. Neither public iterator learns block hopping.
- Keep errors from legacy decoding **exact** (variant/context/detail) and the old static/trailing-byte behavior. New split structural errors use `SegmentError::Corrupt {context:"split postings", detail:<fixed concise description>}` unless existing `Truncated`, `InvalidVarint`, `LimitExceeded`, `NonMonotoneDocId`, `NonMonotonePosition`, `ZeroFrequency` or `UnknownFlags` already expresses the failure more precisely. Define fixed split-specific detail literals in tests, not formatted input-derived strings.

**Rust implementation constraint:** `ByteReader`'s `position()` reports a `usize`; use checked conversion to `u64` before comparing to directory offsets. A private `SplitBlockEntry` **Copy value returned by parsing 40 bytes on demand** is permitted, but storing `Vec<SplitBlockEntry>` is **not** permitted. No `unsafe`, seek outside checked ranges, new synchronized cache, trait-object decoder, or global metadata cache.

### 3.5 Core index integration and compatibility

`SegmentReader::postings_for_entry` returns the **same** `PostingsReader<'_>` public type. New feature is checked against **retained verified metadata**, not guessed from byte marker. Container `parse_container`, `MetadataBudget`, `Directory`, `ObjectStore`, `SegmentCache`, manifest publication, mutation sidecars and index writer operation sequence are **reused without changes**. The existing `IndexWriter` calls `SegmentBuilder`, so real inserts, flushes, compactions, and reopened readers exercise split encoding automatically.

**Legacy acceptance:** checked-in `golden.seg` and `golden_norms.seg` still decode as old format and preserve their *exact existing bytes and pinned digest*. An index can contain legacy and split segments simultaneously; each `SegmentReader` dispatches independently. Existing snapshots retain old bytes through immutable reader state; new writer commits split segments. No in-place rewrite of old segments. Reindexing from original documents is allowed but not required for legacy reads.

**No skip acceleration:** the directory is structural and exposed only to the *private* split decoder; no API or runtime optimization uses it to jump in A3. Include a negative test proving a malformed earlier positional record cannot be skipped via `advance(target)` when the target is in a later block.

---

## 4. State, failure and cross-component matrices

### 4.1 State/ownership transitions

| State | Reader observation and ownership | Forbidden consequence |
|---|---|---|
| New constructor (`Legacy`) | Validate old header, hold borrowed old body, no occurrence allocation until `next` | Sniff/accept split marker without required feature |
| New constructor (`Split`) | Validate exact header, borrowed three streams and borrowed directory; no unbounded `Vec` of directory entries | Allocating from forged block count or accepting feature mismatch |
| Before each `next_with` | One cancellation poll; then finished/EOF/entry budget | Poll moving after EOF or into per-occurrence loop |
| At block start | Validate directory ordinal/offsets and first absolute doc; enforce global increase | Jump past earlier unchecked postings |
| During per-doc decode | Shared positional validator; lean materializes no occurrences | Return doc/freq before validating all positions |
| Validated doc | Update counts and previous ID; full caches one cloned `Posting` | Double emit or unbounded caching |
| Error mid-record | Typed error, never return partially verified record; old immutable bytes unchanged | Resume guarantee, partial generation publication |
| EOF attempt | End-check all streams and split frequency sum; then `finished` | Ignore trailing bytes or incomplete position stream |
| Fresh reader/reopen | Independent cursor over immutable source, correct feature dispatch | Reuse previous query cursor or mutate bytes |

### 4.2 Cross-component impact (no implicit editing permission)

| Component | Required change | Explicit nonchange / regression |
|---|---|---|
| `segment/format.rs` | New required feature ID and registry entry only | Container version, sections, checksums and byte reader stay unchanged |
| `segment/postings.rs` | New encoder/decoder/source enum; shared validation | A2 full/lean APIs, legacy parser errors, advance/cancel semantics |
| `segment/build.rs` | New per-term encoder call; new feature on nonempty postings | Analyzer, norms, stored/columns, doc remap, sorting, source identities |
| `segment/reader.rs` | Feature/section agreement and per-entry version dispatch | Dictionary payload, metadata budget/verified-state ownership, `postings` API |
| Search execution / BM25 | **No code edit** | A1 prepared weights and four A2 consumers continue to work; phrases full |
| Manifest / storage / remote | **No production code edit** | Segment required features propagate naturally; local/RustFS cold readers validated |
| Tests and architecture docs | New split/mixed/format/remote witnesses | Preserve legacy golden bytes and history |

### 4.3 Failure-mode contract

| Failure or boundary | Exact disposition / cleanup | Tests |
|---|---|---|
| No indexed terms | Omit feature/POSTINGS/DICTIONARY; other sections still valid | U01, I01 |
| Unknown/incorrect feature or v1/v2 marker mismatch | Typed `UnsupportedFeature` or `Corrupt`; never retry as another codec | U01/U06 |
| Empty/huge/negative-impossible count and forged `block_count` | Typed checked rejection before table allocation | U05/U06 |
| Length arithmetic overflow, short or trailing byte | Typed `Corrupt`/`Truncated`, no panic, no slice OOB | U05/U06 |
| Overlapping/descending/forged skip offsets and ID | Reject at constructor or block-boundary comparison | U05/U07 |
| Duplicate doc / 128→129 decreasing doc / out-of-range | Typed `NonMonotoneDocId` / `Corrupt` | U03/U07 |
| Zero/over-limit frequency or overflowed frequency sum | `ZeroFrequency` / `LimitExceeded` / `Corrupt` without acceptance | U03/U09 |
| Positional anomaly/truncation in any of five components | Same semantic checks in both full and lean; reject even unselected | U06/U07, I03 |
| Cancel before first/mid-term/on EOF | `SegmentError::Cancelled` at original posting boundary, no partial emitted posting | U08, I02 |
| Positional `check_alloc` exact/one-under | Same historical preflight in both modes | U09 |
| Local writer crash or incomplete commit | Existing atomic publication/recovery behavior; no new write boundary | existing `pr06_faults`, I04 |
| Remote download/timeout/eviction | Existing RustFS adapter/cache handles; never leak partial unverified segment | existing RustFS suites, I05 |
| Index rebuild/compaction with mixed formats | Old snapshots remain correct; new segments use new feature | I03/I04/I05 |
| Nonfinite score or scalar/IDF score drift | A1 tests must reject; do not weaken tolerance or rank | I02/SC suite |

**Independent oracles:** (1) for *valid* postings, frozen old encoder→legacy reader on the **same constructed `Vec<Posting>`**, hand-authored doc IDs/frequencies/positions, and new encoder→split reader all compare exactly; (2) for *malformed* new bytes, hand-written byte offsets/values and typed errors, never a decoder checking itself; (3) for user-visible search, hand-computed memberships and the existing scalar BM25/reference score-bit suite via real committed FsDirectory; (4) fixed byte/digest legacy fixtures are independently retained. Differential validation against legacy supplements but does not replace raw-byte negative testing.

---

## 5. Exact implementation sequence, tests and responsibilities

### P0 — Verify prerequisites and freeze starting source

1. `git fetch origin --prune` and `gh pr view 121 --json state,mergedAt,mergeCommit,headRefOid`. Require **MERGED**, non-null timestamp and a merge commit incorporating A2's reviewed production result. `git switch main && git pull --ff-only origin main`. Save `BASE_MAIN_SHA=$(git rev-parse HEAD)`. Do not assume it equals A2's historical branch-head SHA; check the actual resulting source blob table §1.2 with `git rev-parse HEAD:<path>` (replace `<path>` with each literal table row).
2. Require no tracked or untracked changes in working tree (ignored build output okay). Verify no existing local/remote `dev/perf06-a3-split-postings` branch and no existing A3 PR before creating. Never overwrite/reset/force-push a branch. Verify PR #121 is ancestor/source of accepted `main` via actual PR metadata and blob identities. If A2 not yet merged, **STOP** dependent implementation; document review findings only.
3. Read the actual `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `AGENTS.md`, `docs/TESTING.md`, architecture, and the unchanged series/roadmap. Reconcile §1.1–1.2 with actual `main`, and inventory all `PostingsReader::new` and `SegmentReader::postings(_for_entry)` production callers. Require the four A2 lean paths and one full phrase path unchanged. Any new consumer or authoritative policy drift: HARD STOP with exact source refs.
4. Run and record the **baseline**, before changes, at minimum:

```sh
cargo test -p quervant-core --lib a2_u
cargo test -p quervant-core --lib postings_round_trip_and_errors
cargo test -p quervant-core --test segment_codec
cargo test -p quervant-core --test segment_golden
cargo test -p quervant-core --test pr15i_d2a_scoring_contract
cargo test -p quervant-core --test pr07_properties
cargo test -p quervant-core --test pr13_remote
```

The default `pr13_remote` run does **not** execute ignored real-RustFS tests; this is baseline/local smoke only. Record baseline failures with §12 taxonomy rather than mislabeling them A3 failures. A1/A2 acceptance and their existing CI are baseline, not A3 acceptance.

### P1 — Write RED tests and exact format contract **before** production edits

1. Add new unit cases **A3-U01, U02, U05** (see §6) to `crates/quervant-core/src/segment/tests.rs` using specified split markers and API. Add direct hand-authored expected bytes of a 1-posting and a 129-posting split block. Verify at least U01/U02 fail to compile for the *missing new encoder/constructor/feature*, not due to unrelated test bugs. Capture exact RED output. Do not falsify RED through a failing existing regression.
2. Build a one-page source-to-invariant trace and adversarial challenge as required by §2. Write or complete the remaining prescribed U tests using only `ByteWriter`/`ByteReader`, explicit offsets and canonical varints; no production encoder should create malformed bytes.
3. No new format design questions remain open after this document. If Rust's type system needs mechanical helper placement, use the frozen private structs and `PostingStreams` enum; if it would change parser/error order or ownership, STOP and request amended design.

### P2 — Feature registration, encoder and builder

1. Add `FEATURE_SPLIT_POSTINGS=0x000E`, version 1 in format registry; do not renumber existing IDs. Use a proper doc comment and check `SUPPORTED_FEATURES` still accepts every existing ID/version.
2. In postings.rs implement the frozen constants, private input validator, `encode_split_postings_block`, stream writers and fixed directory, with checked arithmetic and no writer-side skip of invalid records. Keep the old encoder's exact bytes/validation.
3. Change only the builder call and additional required-feature declaration. The segment content is now split by default; no config toggle and no alternate `IndexWriter`. Run encoder-unit tests, existing golden **read-only** tests, and new format fixture cases. No regenerate ignored golden fixture.

### P3 — Reader source enum, feature dispatch and fail-closed metadata

1. Introduce `PostingStreams::{Legacy,Split}` and `SplitStreams` exactly as §3.4, retaining the A2 single full/lean validation loop. `PostingsReader::new` stays legacy; `new_split` validates the new header/directory/extent with borrowed slices. Implement directory entry access with checked `get` ranges and a local `ByteReader`; no borrowed table copies or cache.
2. Make `SegmentReader::postings_for_entry` dispatch from retained required feature. Update `decode_metadata` to reject the new feature without dictionary and postings. **Never sniff a marker and fall back** to a different version. Legacy and new-format segment parsing stay available side by side.
3. Complete U03–U10 and re-run A2-U01–U10. Reconfirm full `advance_with` is the same linear walk and that an invalid earlier posting cannot be jumped over. If any legacy error value or cancellation poll count changes, HARD STOP unless the existing contract can be restored by the specified minimal internal refactor.

### P4 — Production-path correctness and mixed formats

1. In `tests/segment_codec.rs`, extend the real `SegmentBuilder`/`SegmentReader` tests with **A3-I01** to verify feature presence, correct dictionary offset/length extents, split markers, and exact full/lean posting tuples across 127/128/129/257 cases. Include absent term and no-postings segment.
2. In `tests/pr15i_d2a_scoring_contract.rs`, add **A3-I02**: real `FsDirectory` writer→commit→fresh reopen→`UnifiedSearcher` on 257 deterministic documents. Term/prefix/`And([Term])`/phrase, K10/K100, explicit-string sort/relevance, all-live/partial-live, exact total hits, exact output score **bits**, and PIT/cursor assertions. Derive expected matches from fixture input, not from engine output. Existing A1/A2 and historical SC tests must stay green.
3. Add **A3-I03** to `tests/segment_codec.rs` (or if the existing module cannot form a valid container, stop and amend): construct old and new segments for the same hand-authored small corpus, compare decoded logical data, and hand-rebuild a new container with malformed positional bytes **and recomputed normal section digests** using existing `ContainerBuilder` so errors cannot be dismissed as only a whole-container SHA failure. Verify corruption in a later/unselected term's posting fails when consumed, both full and lean. A2's original malformed-block parity remains a required baseline.
4. Add **A3-I04** **only** in the existing `tests/segment_golden.rs` integration test file. Reuse its **actual** `schema()`, `doc()` and `golden_segment()` helpers: open the pinned legacy `golden_norms.seg` and the freshly built new-format `golden_segment()` with **two independent real `SegmentReader`s**, representing the *same two logical input documents*. Assert that the full `title` and `path` dictionary terms/doc frequencies, `title` and `path` field-norm lengths, all corresponding posting doc/freq/occurrence records, stored keys and physical remap are identical. Assert the new split feature is present only in the fresh segment; the pinned legacy fixture has no split feature and retains its recorded digest. This verifies cross-format per-segment readability without claiming that both segments were attached to one production manifest. **Do not** invent a raw-segment insertion API, invoke private `compute_stats` from an external integration test, or manipulate `CURRENT`/manifest bytes. Existing SC06, real multi-flush and PIT tests cover normal multi-segment index continuity; the independent readers exercise the two feature-dispatch branches. Record D22. If the two fixtures do not share the expected schema and documents, HARD STOP with exact evidence rather than generating a new reference corpus.
5. Exercise existing `pr07_integration`, `pr07_properties`, `pr14_unified_mixed`, `pr15i_d2a_scoring_contract`, `pr15i_b_stored`, `pr15i_d3_c`, `segment_golden`, `pr06_faults` and focused codec tests. Revalidate that only the new format's extra checks differ; no old fixture error suppression.

### P5 — Targeted **real RustFS correctness**, not a performance campaign

**Unlike A1/A2, A3 changes the *persisted format***. One real RustFS vertical is required to demonstrate it is portable through the existing remote writer and cold reader. No new service topology or benchmark. Reuse the **existing** `crates/quervant-core/tests/pr13_remote.rs` RustFS module/harness; do not create another test runner, `Cargo.toml` dependency or CI trigger.

Add one ignored feature-gated test `a3_r01_split_postings_rustfs_cold_reopen` in the already existing `#[cfg(feature="s3")]` real RustFS module, following its existing `rustfs_write_cold_open_query_and_restart` pattern:

1. `real_index("perf06-a3-split")` provides isolated remote prefix/credentials; insert at least 3 docs: `a: "alpha beta"`, `b: "alpha gamma"`, `c: "beta"`; commit once with the normal remote writer. Query term `alpha` => `{a,b}`, phrase `alpha beta` => `{a}` and term `beta` => `{a,c}` using the *actual* `LexicalSearcher`/query API; compare exact logical keys and counts (not HTTP timings).
2. Remove only the **disposable workspace root** through the existing harness method; open `RemoteIndex::open_existing` from RustFS with an empty cache, no writer-local state, and repeat term and phrase results. Leave durable remote objects intact until the harness's normal cleanup. Do not call an endpoint outside the CI-provided private RustFS service.
3. Test is ignored by default and must be **executed**, not merely compiled, by the existing CI `rustfs` job's command `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1`. No `.github/workflows/ci.yml` edit is necessary. Run the same exact test locally only when the documented pinned RustFS environment is already available; do not start new containers just for A3. If CI cannot exercise it, leave the remote gate `BLOCKED` and report.
4. Existing fake-objectstore tests continue to run as regression, but cannot substitute for this real-provider run. No RustFS performance, range-optimization or cold-start claim follows from this test.

**New structural size report:** In unit tests, record deterministic encoded byte sizes for a fixed 1/127/128/129/257-doc corpus using the legacy and split encoders, plus total built segment size for one fixed corpus. Record values, including increases, **without** a timing loop, tuning or a fabricated acceptance threshold. A4 owns the decision on warm-query speed and any size/performance tradeoff. A3 must still pass existing max-segment and memory safety limits.

### P6 — Full local QA on final code/test state

Run **after the last source/test/manifest-related edit**. Commands are not optional; record actual counts and exit codes on both stable and MSRV, with **no new exemptions**:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --fail-under-lines 85
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --no-deps
cargo doc --workspace --all-features --no-deps
cargo bench --workspace --no-run
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets -- -D warnings
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets
cargo +1.85.0 test --workspace --all-targets --all-features
git diff --check
```

The workspace 85%-line coverage gate applies to **all applicable production crates**, not a handpicked file. Note the actual CI Rust job uses pinned Rust 1.98.1 and MSRV 1.85.0; report exact observed local and CI toolchains. Run required relevant real local integration tests; do not count an ignored RustFS test unless the pinned service executed it. If required tooling unavailable, document the exact environment error and classify `ENVIRONMENT_HARNESS_FAILURE`, but do not claim READY. CI success on a different SHA is insufficient. Re-run affected mandatory checks after any final code/test edit.

### P7 — Documentation, evidence, and independent PR

1. Add a concise durable section in `docs/ARCHITECTURE.md` titled `PERF-06-A3 split postings v1 (implemented)` **only after** code/invariant gates pass: exact version/feature, 56-byte term header, 128-document grouping, three streams, 40-byte directory, old segment read behavior, no fast skipping, and resource/corruption contract. If code gates blocked, use `planned` instead and accurately mark unfinished items. **Do not** update `docs/PERF_OPTIMIZATION_ROADMAP.md` to DONE without full acceptance; don't edit `AGENTS.md`/`docs/BENCHMARKING.md`.
2. Commit an exact copy of **this** approved `PERF06_A3_DETAILED_PLAN.md` under `docs/pr-artifacts/perf-06-a/`, plus a new `PERF06A3_EXECUTION_REPORT.md`: source SHAs, branch/head/base, U/I/CI proofs, actual test counts, codec byte tables, malformed errors, remote topology and commands, applied decision rows, residual risks, and typed disposition. Plan file is *instructions*, not execution evidence.
3. Stage only §8 allowlist, run `git diff --cached --check` (handle existing intentional Markdown hard-break formatting only within its approved scope), commit `perf(a3): add versioned split postings streams`, push normally; verify local vs remote full SHA. Create **one new draft PR targeting `main`**. Never update PR #119 or #121, force-push, merge or start A4. If GitHub auth blocked, preserve the local commit/report and use typed `PR_CREATION_BLOCKED`.
4. Obtain hosted CI results for the **exact** final code-bearing PR head. Later docs-only report edits must identify which prior source SHA the passing CI tested, and check CI on updated head as applicable. `READY_FOR_INDEPENDENT_REVIEW` only after required hosted Rust/RustFS/MSRV/coverage and local checks are all green. Review is still independent.

---

## 6. Deterministic test matrix (do not substitute generic tests)

Unit tests **A3-U01–U12** belong in `crates/quervant-core/src/segment/tests.rs` alongside existing `postings_round_trip_and_errors` and A2-U01–U10. Use `ByteWriter` and existing `SegmentLimits`/`Occurrence`/`Posting` fixtures. Tests compare explicit values, typed error details and exact stream geometry, not just `is_err`.

| ID / prescribed name | Required stimulus and assertions |
|---|---|
| **U01 `a3_u01_feature_and_empty_segment_contract`** | `FEATURE_SPLIT_POSTINGS=0x000E` supported; no-postings builder omits new feature and pair; new nonempty segment requires the feature and has v2 markers. Header/section kinds and existing IDs unchanged; feature/no-sections mismatch rejected. |
| **U02 `a3_u02_exact_split_header_one_posting_bytes`** | One doc-only posting `(doc_id=0,freq=1)` in segment of 2 docs: exact 56 header fields, doc stream `[0]`, freq stream `[1]`, no positions, one 40-byte directory `(first_doc_id=0,ordinal=0,offsets=0)`, total **98 bytes** (`56+1+1+0+40`). Positional one-occurrence variant has 5 varints and **103 bytes**. Check both decode. |
| **U03 `a3_u03_block_boundaries_and_monotone_docs`** | Build 1, 127, 128, 129, 256, 257 postings with docs equal to physical ordinals, frequency 1 and positional occurrences; assert block counts `[1,1,1,2,2,3]`, exact `first_posting_ordinal` `[0,128,256]`, stream offsets and 128→129 absolute-ID reset; full and lean return exact ordered doc/freq sequence. Mutate boundary to duplicate/decrease and reject. |
| **U04 `a3_u04_full_lean_and_advance_parity`** | Construct 3-posting positional and doc-only v2 blocks; compare full `Occurrence` position lengths, value indexes, byte offsets with hand-authored input. A2 `decode_observation` witnesses: lean `(0,0)` reserves/clones, full >0. `next→advance(same)→advance(future)→EOF` exact; conversion after full read emits next unread only. |
| **U05 `a3_u05_split_directory_geometry_errors`** | Raw bytes: block_count off by 1, block_docs 127 or 0, first entry ordinal nonzero, 2nd ordinal ≠128, first doc offsets not zero, offset past stream, descending offsets/first doc ID, overlapping/truncated directory, forged last stream length, trailing byte, overflowed declared sizes. All fail with typed `Corrupt`/`Truncated`/`LimitExceeded`, no panic or allocation based on forged count. |
| **U06 `a3_u06_split_header_and_positional_corruption`** | Raw marker 0/1/9 with v2 constructor; version 0/2; nonzero flags/reserved; noncanonical varints, truncated position fifth field, zero length, duplicate position, decreasing value index, start>end, position overflow. Both full and lean reject the same malformed posting (exact typed variant/context), including corruption only on the second posting; no fallback. |
| **U07 `a3_u07_directory_offset_and_first_doc_must_match_streams`** | Structurally in-range but wrong directory first-doc ID or offset for block 1; constructor may accept bounded geometry, but first `.next_with` in that block must reject before returning its first posting. Verify earlier postings not omitted; also `advance(target_in_block_2)` sees error in block 1. |
| **U08 `a3_u08_cancellation_eof_and_unselected_corruption`** | Counting canceller: before first, after 1, exactly at EOF, after EOF; one poll per attempted posting. Valid first, corrupted later positional posting marked dead/nonwinner by test fixture: full and lean error, not accepted. With valid data, repeated EOF returns `None` and cancellation before repeated EOF wins. |
| **U09 `a3_u09_frequency_and_resource_limits`** | Doc count ≤ limit vs over; freq 0; freq over max entries; exact/one-under historical `check_alloc::<Occurrence>(freq)` in both modes; `freq_total` mismatch discovered at EOF only; checked sum overflow and no reader-allocation from skip count. Preserve old A2 U05. |
| **U10 `a3_u10_legacy_encoder_and_reader_unchanged`** | Legacy `encode_postings_block` bytes match fixed hand-authored old doc-only and positional specimens; legacy direct constructor rejects markers 2/3; new v2 constructor rejects 0/1; old noncanonical/trailing/limit errors retain exact categories and strings. Golden fixture SHA stays as pinned. |
| **U11 `a3_u11_feature_section_pair_and_dictionary_extents`** | Built v2 term entries point to exact nonoverlapping extents; dictionary `doc_freq` matches header. Mutate required feature missing/present, missing dictionary/POSTINGS section, incorrect `doc_freq`, bad per-term offset or length, and raw v2 data without feature; fail closed with typed errors. Test via valid container reconstruction with recomputed digests. |
| **U12 `a3_u12_determinism_and_structural_size_report`** | Same input, `Layout` and schema yield byte-identical new segments across two builds. Report exact legacy/split per-term byte sizes for 1/127/128/129/257 posts and one complete small segment, without timing or tuning. No hard improvement threshold. |

**Integration tests** must use the real production implementation and meaningful independent expected outputs:

| ID / existing test file | Required production path | Oracle / acceptance |
|---|---|---|
| **I01** `tests/segment_codec.rs` | `SegmentBuilder` → immutable POSTINGS/DICTIONARY → `SegmentReader`, for doc counts 0/127/128/129/257 and missing term | Feature/extent/marker/header/directory correctness; all decoded frequencies/positions; old golden unchanged |
| **I02** `tests/pr15i_d2a_scoring_contract.rs` | `FsDirectory` actual writer→commit→reopen→`UnifiedSearcher` on 257 docs, term/prefix/Boolean/phrase, K10/K100, sorted/relevance | Explicit key sets, exact totals, BM25 score bits vs frozen oracle, cursor/PIT/partial-live preservation |
| **I03** `tests/segment_codec.rs` | Two independently encoded payload versions; malformed v2 body in valid reconstructed outer envelope | Legacy/split logical parity, properly surfaced corrupt selected/unselected postings, no checksum-only false proof |
| **I04** `tests/segment_golden.rs` | Existing legacy `golden_norms.seg` + fresh `golden_segment()` from the **same two documents**, each through real `SegmentReader` | Exact logical terms/DF, norms, full postings/positions, stored keys/remap; new feature only on new segment; old fixture digest unchanged; no fictitious same-index mixed-format claim |
| **I05** `tests/pr13_remote.rs` (`a3_r01_split_postings_rustfs_cold_reopen`, ignored unless real RustFS) | Actual RemoteIndex write→commit→delete disposable workspace→fresh remote read | Exact `alpha`, `beta`, phrase `alpha beta` membership before/after cold reopen, no provider/format failure |

**Mandatory inherited regression suites:** A2-U01–U10; A1 scoring tests; `segment_codec`, `segment_golden`, `segment_corrective`, `pr07_integration`, `pr07_properties`, `pr14_unified_mixed`, `pr15i_d2a_scoring_contract`, `pr15i_b_stored`, `pr15i_d3_c`, `pr06_faults`, other workspace tests, plus existing CI RustFS. Do not regenerate `golden.seg` or `golden_norms.seg` and do not edit their pinned hashes.

---

## 7. Format diagrams, byte arithmetic and error examples

### 7.1 Layout overview

```text
DICTIONARY (unchanged v1)
  entry: [field][term][doc_freq][postings_offset][postings_length]
                                       |
                                       v
POSTINGS section, entry-selected v2 extent:
  0                 56
  +-----------------+----------------------+-------------------------+
  | 56-byte header  | doc stream           | frequency stream        |
  +-----------------+----------------------+-------------------------+
                    | positional stream    | 40B block entries x B   |
                    +----------------------+-------------------------+
                    A2 full/lean decoder validates ALL occurrences
                    while retaining occurrences ONLY in full mode.
```

### 7.2 Hand-computable bytes, used by U02

One **doc-only** posting doc `0`, freq `1`, term in 2-doc segment: header 56 bytes (`marker=2, version=1, flags=0, block_docs=128, blocks=1, reserved=0, count=1, freq_total=1, doc_len=1, freq_len=1, pos_len=0`); doc stream `00`, freq stream `01`, directory five `u64` zeros. **Total 98 bytes**.

One **positional** posting doc `0`, freq `1`, occurrence `{position:0, length:1, value_index:0, start_offset:0, end_offset:1}`: header differs only marker=3 and `pos_len=5`; doc `00`, freq `01`, pos `00 01 00 00 01`, directory five zeros. **Total 103 bytes**. The v2 parser must recover the original single occurrence, not infer position from frequency.

For 129 postings `doc_id=0..128`, `freq=1`, each with one position record, there are **two directory records** with ordinals 0 and 128. Document stream uses `absolute 0` at ordinal 0, positive deltas `1` at ordinals 1..127, then **absolute 128** as varint at ordinal 128; directory second entry holds `first_doc_id=128`, byte offsets equal to the three streams' positions before ordinal 128. No tuning based on these sizes.

### 7.3 Malformed data and precedence examples

- `marker=3`, 1 posting `freq=2`, but the position stream ends after the first occurrence's fourth field → final `ByteReader::varint("end offset")` yields **`Truncated`** before a posting is returned. This is true for both full and lean cursors.
- First block valid but block 2 first doc ID regresses below block 1's final ID → fail in the second block before its first posting return, even when the per-block delta itself is nonzero.
- `freq_total` declares 3 but two fully parsed postings have frequencies 1+1 → both return valid postings; the **next** call (EOF) raises `Corrupt("frequency total mismatch")` rather than returning `None`. No file mutation.
- A valid table entry describing byte offset `doc=3` where the actual reader position is `doc=2` → mismatch at block start; do not seek to offset 3 to “recover.”
- A valid earlier posting with malformed later (dead/unselected) occurrence must cause full/lean error upon traversing that later posting. Calling `advance(large_target)` must not skip the corrupt record.

---

## 8. Change allowlist and nonchanges

**Only these paths may be created/edited** (after preflight). Treat the list as an allowlist, not an invitation to touch every file:

| Path | Expected change |
|---|---|
| `crates/quervant-core/src/segment/format.rs` | Feature constant and supported-feature row |
| `crates/quervant-core/src/segment/postings.rs` | New encoder, byte layout/constants, private source enum/reader v2, A2 full/lean preservation |
| `crates/quervant-core/src/segment/build.rs` | Replace term encoder and declare feature when postings nonempty |
| `crates/quervant-core/src/segment/reader.rs` | Required-feature dispatch, feature/section pair validation |
| `crates/quervant-core/src/segment/tests.rs` | U01–U12 and malformed raw payload fixtures |
| `crates/quervant-core/tests/segment_codec.rs` | I01/I03 production segment and envelope validation |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | I02 real local search and score tests |
| `crates/quervant-core/tests/segment_golden.rs` | I04 cross-format, same-corpus golden fixture compatibility test **only** (do not change fixtures or digest) |
| `crates/quervant-core/tests/pr13_remote.rs` | New ignored A3-specific RustFS cold bootstrap test in existing harness |
| `docs/ARCHITECTURE.md` | Durable versioned format contract/status, accurate to observed implementation |
| `docs/pr-artifacts/perf-06-a/PERF06A3_DETAILED_PLAN.md` | Copy of this approved plan |
| `docs/pr-artifacts/perf-06-a/PERF06A3_EXECUTION_REPORT.md` | New evidence/commands/disposition |

**Protected, normally untouched:** `crates/quervant-core/src/search/{execute,score,unified,phrase}.rs`, `segment/{dictionary,limits,manifest,model,norms,stored,stored_blocks,column,remap}.rs`, index/writer, `Directory`/S3/RustFS adapter, any manifests/protocol schemas, `.github/workflows/*`, `Cargo.toml`/`Cargo.lock`, `AGENTS.md`, `docs/BENCHMARKING.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, benchmark harness/study configurations/results, historical PR artifacts and `tests/fixtures/segment/{golden.seg,golden_norms.seg}`. **A change required outside the allowlist is a HARD STOP** unless §13 explicitly allows a narrower equivalent action; do not slip it into the PR.

**Reuse:** existing `ByteReader`/`ByteWriter`, feature negotiation, SHA-256 container validation, dictionary extents, A2 decoding APIs, `SegmentBuilder` and `IndexWriter`, verified immutable state, real `FsDirectory` and `RemoteIndex` harnesses, `SegmentLimits`, `SearchWork`/candidate ledger, preserved A1 scorer, and existing CI. No parallel storage/query abstraction.

---

## 9. Resource, safety, persistence and portability contract

**Index identity:** The segment's content digest changes with new bytes (expected). The manifest's required features refer to the corresponding segment; do **not** fabricate a stable segment digest across formats. Old committed segment objects and snapshot handles are immutable. The index writer must construct and publish one **complete** new segment before updating `CURRENT`; A3 does not alter existing publication/rollback behavior.

**Ownership:** Encoder owns temporary byte writers only and returns one encoded term buffer; `SegmentBuilder` concatenates it under the existing byte-budget/commit path. Reader owns no new persistent allocations: `PostingsReader` holds borrowed byte slices for three streams and block directory, and A2 full/lean controls transient occurrence ownership. The immutable `VerifiedSegmentState` and `ReaderSnapshot` continue owning the segment bytes; cursors never outlive their segment. No global or cross-query cache.

**Resource accounting:** Validate counts/lengths before allocation; do not trust forged block_count or stream_len. Preserve `SegmentLimits` existing per-posting decoded and hypothetical occurrence limits *even in lean mode*. No new pre-return work charging in `SearchWork` or changes to candidate ledger peak/entry counts: those are still charged per validated posting `freq` by existing search loops. New read-only directory validation may be O(number of blocks), but it cannot allocate in proportion to an unverified count. Any legitimate new build allocation must be checked against the existing configured limits and handled as typed `LimitExceeded`, not OOM/panic.

**Corruption and failure order:** `SegmentReader::open` still verifies container hash/sections/features; `postings_for_entry` constructs the appropriate reader; per-posting validation remains lazy and occurs for every consumed posting. Even a posting which will be rejected after live filtering must be fully decoded/validated first. Only new v1 structural checks and final freq-total check are additional format-specific errors. Do not mask typed errors, ignore malformed unselected data, or alter the original legacy decoder's error strings.

**Remote:** Real RustFS object publication and cold reopen are covered by the existing transport; no new range fetching, retry or cache invalidation behavior. Existing writer and reader automatically operate on v2 segments because `SegmentBuilder` and `SegmentReader` are changed. Real adapter execution is required (§5 P5), not inferred from fake ObjectStore.

**Compatibility policy:** Old v1 postings blocks can remain in read-only archived and mixed indexes. New builder writes only split payloads. Quervant is not in production and has no customers, so no reindex/migration tooling, mixed-format write toggle, or compatibility guarantee beyond this explicit test contract is needed. Any proposal to delete old reader support or change feature IDs is a separate maintainer decision.

---

## 10. Reviewer and completion gates

A reviewer must verify **every** checkbox using actual source/test artifacts (not just the agent's narrative):

- [ ] A2 PR #121 genuinely MERGED; baseline main blobs match the table; no unreviewed A2 branch base.
- [ ] Single versioned format with exactly 56-byte header, three streams, 128-doc blocks, 40-byte directory; new required feature ID/version and legacy feature dispatch correct.
- [ ] Frozen legacy bytes/decoder unchanged; golden SHA and stored/norms/legacy tests remain green.
- [ ] Encoder validates all source invariants, writer emits new codec by default, dictionary extents exact.
- [ ] Reader validates all header/length/directory semantics with checked arithmetic, no unbounded skip table allocation, and no byte sniffing fallback.
- [ ] One common full/lean `read_one_with` still validates complete position data; A2 lean reserves/clones zero; full advance remains linear and cached-current semantics unchanged.
- [ ] New-format per-block and cross-block doc ordering, exact freq sum, mandatory invalid/truncated cases, cancellation and budget typed errors proven.
- [ ] Nonwinning/dead corrupted posting is rejected; skip metadata never bypasses required validation.
- [ ] Full corpus, real local writer/commit/reopen, multi-segment, PIT/cursor, phrase, score-bit and mutation integration tests pass.
- [ ] New A3 RustFS **ignored integration actually executed** against pinned real service; real cold reader works after workspace deletion, separate from fake-only tests.
- [ ] Default + all-features, stable + MSRV, workspace coverage >=85%, doc build, bench **compile-only**, existing CI green on final source; actual commands/counts recorded.
- [ ] Structural segment byte sizes recorded without a performance claim or benchmark acquisition.
- [ ] Diff limited to §8 files; source and history preserved; architectural documentation and full execution report accurate.
- [ ] Draft A3 PR pushed to `main` base, no merge/A4 work, independent review still pending.

**Failure classification for every mandatory gate:** `INTRODUCED_REGRESSION`; `FEATURE_IMPLEMENTATION_DEFECT`; `DETERMINISTIC_PREEXISTING_FAILURE` (only after reproducing against accepted `main`); `NONDETERMINISTIC_FLAKY_FAILURE` (only with reproducible nondeterminism); `ENVIRONMENT_HARNESS_FAILURE` (tool/service/permission). “Unrelated” is never sufficient. A test existing is not a test executed; CI passing on a different SHA is not final evidence. No automatic favorable reruns, threshold relaxation or skipped faults.

**Adversarial final self-review:** for each INV, write one concrete way an erroneous implementation could still pass a happy-path test, show which named negative fixture prevents it, and identify remaining unproven risks. Unknown integrity/corruption, read recovery, resource, or remote-persistence risks remain `STOP`, not self-approved as acceptable.

---

## 11. Suggested PR text and next dependency

```markdown
## PERF-06-A3 — Versioned split postings streams and block directory

Implements the approved split-postings v1 payload: a 56-byte per-term header,
independently addressable doc-ID / frequency / positional streams, and a
validated 128-document block directory. New segments declare required feature
`FEATURE_SPLIT_POSTINGS=0x000E`; legacy segments remain readable.

A2's full and doc/frequency-only readers and all original positional/error/
cancellation/resource contracts are retained. `advance` remains sequential;
this PR does NOT authorize jumping past unvalidated postings. Real
FsDirectory and pinned RustFS correctness paths, phrase and exact BM25 score
parity, malformed-byte tests, stable/MSRV QA and >=85% coverage are gates.

No query benchmark/profiling or cross-engine acquisition. PERF-06-A4 owns
consolidated warm-performance qualification. Independent review required.
```

**Dependencies:** A2 accepted merge → A3 implementation/review/merge → **PERF-06-A4** (one separately approved cumulative A-series correctness/warm-performance qualification). A3 must not predeclare the A4 historical baseline as automatically comparable: changed persistent format, index size and preparation can affect operational context. A4 independently chooses a legitimate measurement design; no fabricated B/A pairing.

---

## 12. Final execution report template and typed dispositions

Write `docs/pr-artifacts/perf-06-a/PERF06A3_EXECUTION_REPORT.md` with **all** of:

1. Exact repo/PR/base-main/branch/final/remote-verified SHA and A2 merge proof;
2. Current-main source blobs and any approved deviations (none expected);
3. Pre-implementation invariant challenge with INV→code→U/I mapping;
4. RED test evidence on baseline (correct missing API, no unrelated failure);
5. Versioned format byte table, directory geometry, checked arithmetic and example hex fixture;
6. Source/changed-files allowlist, ownership and legacy/new segment format dispatch;
7. Per-U unit tests and concrete byte-specific malformed/error results; per-I real production boundary results;
8. Full/lean position materialization witness, cancellation poll counts, ledger limits, old golden digest;
9. Real `FsDirectory`, mutation/PIT, actual ignored RustFS test invocation/topology/result;
10. Baseline vs v1 deterministic encoded sizes; clearly *not* query latency;
11. Stable/MSRV local commands, actual test counts, all-features coverage percentages and CI job status on exact head;
12. Every applied §13 rule, any deferred decision, all unresolved failures with five-class taxonomy;
13. Adversarial self-review and truthfully classified final disposition.

Allowed statuses:

- `PERF06_A3_DEPENDENCY_BLOCKED_A2_UNMERGED` — A2 not accepted; no A3 implementation.
- `PERF06_A3_HARD_STOP_DESIGN_DECISION_REQUIRED` — unforeseen/contradictory source or impossible-to-preserve invariant.
- `PERF06_A3_IMPLEMENTATION_BLOCKED` — implementation/gate fails, keep evidence; no READY.
- `PERF06_A3_REAL_RUSTFS_BLOCKED` — local implementation/tests may pass but mandatory real-provider gate did not execute/pass.
- `PERF06_A3_IMPLEMENTED_CI_PENDING` — all applicable local gates passed and draft PR pushed; hosted exact-head CI still running.
- `PERF06_A3_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW` — all local, source, real-RustFS, hosted CI, documentation and stop gates pass; still draft/unmerged.
- `PERF06_A3_PR_CREATION_BLOCKED` — GitHub auth/network prevents creating/pushing PR after local work; no fictional PR.

---

## 13. Preauthorized Architectural Decisions and Exception-Handling Matrix

**Mandatory semantics:** This table defines the **only** autonomous decisions. Match an **observable source condition**, apply the most restrictive applicable row. For `AUTO-RESOLVE`, act, record source/line and test proof, and continue. For `DEFER AND CONTINUE`, record an exact decision/dependency/gate, complete only provably independent authorized work, and do not assume a blocked dependency passed. For `HARD STOP`, stop the affected work, preserve evidence, and request the smallest maintainer decision; stop the whole PR if safe isolation is impossible. **An unforeseen condition not fitting a row is D45 HARD STOP**—never give the coding agent architectural discretion.

| ID | Observable trigger / source check | Category | Prescribed action/fallback | Prohibited action | Evidence, affected gate, owner |
|---|---|---|---|---|---|
| **D01** | PR #121 OPEN/DRAFT or CI green but not MERGED | **DEFER AND CONTINUE** | Source/document audit only; report dependency blocked. Resume P0 only after real merge. | Implement atop unmerged A2 or cherry-pick A2. | PR API status; P0; maintainer. |
| **D02** | PR #121 MERGED, source blobs equal §1.2, clean tree | **AUTO-RESOLVE** | Pin accepted `BASE_MAIN_SHA`; create prescribed A3 branch and continue. | Using A2 branch directly. | `gh`, blob and Git commands; agent. |
| **D03** | Any A3-relevant accepted `main` blob differs from §1.2 / missing A2 API | **HARD STOP** | Report exact path and expected/actual SHA; request updated plan. | Silent reinterpretation or fixups in A2. | P0; maintainer. |
| **D04** | `dev/perf06-a3-split-postings` exists locally or remotely, or A3 PR already exists | **HARD STOP** | Preserve and report branch/PR identity; request continuation strategy. | Reset, force push, second competing PR. | P0; maintainer. |
| **D05** | Next free known feature ID is `0x000E`, features up through `0x000D` | **AUTO-RESOLVE** | Add `FEATURE_SPLIT_POSTINGS=0x000E` version 1 only. | Renumbering/silently reusing ID or container version. | S1/U01; agent. |
| **D06** | New `SectionKind::Postings` and dictionary extents already exist | **AUTO-RESOLVE** | Reuse section and dictionary v1 unchanged. | Add a new section or dictionary format. | S1/S4; agent. |
| **D07** | `SegmentBuilder` contains exactly one `encode_postings_block` term call | **AUTO-RESOLVE** | Replace it with new encoder and add required feature iff postings nonempty. | Toggle or alternate builder. | S2/U01; agent. |
| **D08** | Existing legacy encoder validation duplicated into v2 | **AUTO-RESOLVE** | Extract shared private source validator, prove legacy output byte-identical. | Weaken old checks or start separate validation design. | S2/U10; agent. |
| **D09** | Exactly four A2 doc/freq consumers and full `build_phrase` still intact | **AUTO-RESOLVE** | Retain all five unchanged; version dispatch solely inside segment reader. | Change search pipeline or phrase calls. | INV08/diff; agent. |
| **D10** | Existing A2 `read_one_with` and `DecodeDetail` are in `postings.rs` | **AUTO-RESOLVE** | Extend one common full/lean parser with frozen `PostingStreams` source enum. | Duplicate two independent full/lean parsers. | S3/U04; agent. |
| **D11** | Rust cannot define an enum inside an `impl` | **AUTO-RESOLVE** | Place `PostingStreams` and `SplitStreams` as private module-level items adjacent to `PostingsReader`, exact contracts unchanged. | Adding a generic trait or different architecture. | S3/compile; agent. |
| **D12** | New skip table entry start is `b*40`, stream offsets are in-range | **AUTO-RESOLVE** | Parse borrowed 40-byte slice with `ByteReader`; compare at block boundary. | Allocating a Vec or seeking/jumping. | S3/U05/U07; agent. |
| **D13** | Existing `.advance_with` linear loop encounters blocks | **AUTO-RESOLVE** | Leave it exactly sequential; validate every record. | Using skip metadata to jump. | INV03/05; agent. |
| **D14** | Legacy `PostingsReader::new` sees markers 0/1; v2 new sees 2/3 | **AUTO-RESOLVE** | Feature dispatch determines constructor; each rejects other markers. | Guess version from marker when feature missing. | S3/U10/U11; agent. |
| **D15** | Empty builder has no dictionary/postings | **AUTO-RESOLVE** | Emit no split feature or split section for that segment. | Empty synthetic v2 term block. | S2/U01; agent. |
| **D16** | New split header differs from exact 56-byte field table | **HARD STOP** | Return raw bytes and offending source; request correction to prescribed bytes or plan amendment. | Guess a different version/layout. | INV01/10; maintainer. |
| **D17** | New format needs 127/128/129/257 block-count boundary | **AUTO-RESOLVE** | Use fixed 128 posts/block; encode first doc absolute at every block. | Configurable block size, compression, tuning. | U03; agent. |
| **D18** | Block directory offsets inconsistent with actual cursors | **HARD STOP** | Preserve exact bytes and reported offsets; correct only within §3 design upon reviewed defect. | Re-seek or ignore validation. | INV02/10; maintainer. |
| **D19** | A2 hypothetical `check_alloc::<Occurrence>(freq)` still exists | **AUTO-RESOLVE** | Preserve preflight for both split full and lean; use original error variants. | Remove to gain speed. | U09/INV06; agent. |
| **D20** | A proposed shortcut skips or defers corrupted positional bytes | **HARD STOP** | Halt shortcut; retain full validation before returning posting. | Accept corruption because not in Top-K/dead. | INV03; maintainer. |
| **D21** | Original golden fixture is versionless/legacy with SHA pinned | **AUTO-RESOLVE** | Preserve byte-for-byte; test dual-format reading, never regenerate. | Rewrite `golden_norms.seg` or digest. | U10/I03; agent. |
| **D22** | Existing `Index` API has no approved raw-legacy-segment insertion seam | **AUTO-RESOLVE** | Use §5 P4's **two-real-SegmentReader** same-corpus test in existing `tests/segment_golden.rs`, reusing its `schema`, `doc` and `golden_segment` helpers. Do not claim a production mixed-format index was created. | Invent manifest mutation/segment injection or access private `compute_stats` from integration tests. | I04; agent. |
| **D23** | New codec causes existing test to compare historical exact *new-builder* bytes | **DEFER AND CONTINUE** | Identify expectation and distinguish frozen legacy fixture from new-builder output; work on independent decoder tests. | Silently repin old hash or regenerate golden. | Test fixup; maintainer. |
| **D24** | `ByteWriter` assembled new block would exceed an existing configured allocation limit | **AUTO-RESOLVE** | Checked `LimitExceeded`; leave policy unchanged; test boundary. | Raise limit or unchecked reserve. | INV06/U09; agent. |
| **D25** | Malformed v2 header/directory/count/offset/input supplied | **AUTO-RESOLVE** | Reject with specified typed error and never allocate from forged count; add targeted counterexample. | Panic, `unwrap`, skip invalid bytes. | U05/U06/U11; agent. |
| **D26** | A2 full vs lean divergence on same valid split bytes | **HARD STOP** | Preserve fixture and stop until common parser contract restored. | Change score tolerance or hide occurrence. | INV02/03; maintainer. |
| **D27** | Legacy A2 error string, EOF, `advance`, cancellation or budget changes | **HARD STOP** | Record exact prior/current divergence, restore old behavior only under approved parser plan. | Claim improved error policy. | INV05–07; maintainer. |
| **D28** | New v2 freq_total does not match fully decoded frequencies at EOF | **AUTO-RESOLVE** | Return exact `Corrupt("frequency total mismatch")`; no partial successful EOF. | Ignore mismatch or test only header value. | U09; agent. |
| **D29** | Need to reconstruct a container for malformed-section test | **AUTO-RESOLVE** | Reuse existing `ContainerBuilder`/section-body and required-feature-copy idiom; recompute normal digest. | Disable checksum or patch envelope without repair. | I03/U11; agent. |
| **D30** | New A3 local feature tests fail RED only for missing API | **AUTO-RESOLVE** | Preserve RED log then implement prescribed API. | Present baseline bug as expected RED. | P1; agent. |
| **D31** | New code fails due to a narrow mechanical Rust compiler/borrow-check/lint issue | **AUTO-RESOLVE** | Make minimal behavior-preserving fix **within allowlist**, document exact reason, rerun tests. | Redesign enum, skip validation, waive tests. | P3/P6; agent. |
| **D32** | A new A3 negative/positive assertion fails due to incorrect implementation within specified codec | **AUTO-RESOLVE** | Fix only the named in-scope code path; rerun full affected tests. | Invent new format or weaken assertion. | U/I; agent. |
| **D33** | Formatting changes unrelated source files | **DEFER AND CONTINUE** | Restore only proven incidental formatting; run format again, report. | Broad `git reset --hard`, touch other PRs. | Diff; agent. |
| **D34** | Existing required baseline test fails before changes | **DEFER AND CONTINUE** | Reproduce against accepted main, classify; continue safe read-only analysis only for affected area. | Label unrelated/flaky without proof. | P0; maintainer. |
| **D35** | Workspace coverage <85% because new v2 error branch untested | **AUTO-RESOLVE** | Add in-scope deterministic adverse test for uncovered new behavior and rerun coverage. | Exclude module, lower threshold. | P6; agent. |
| **D36** | Mandatory integration/rustfs gate fails or not runnable in required service topology | **DEFER AND CONTINUE** | Complete independent tests/report; classify `ENVIRONMENT_HARNESS_FAILURE` or defect and mark `REAL_RUSTFS_BLOCKED`; do not claim READY. | Fabricate real-provider evidence from fake. | P5/P6; maintainer. |
| **D37** | Hosted CI still pending on exact A3 head | **DEFER AND CONTINUE** | Report CI pending and independent review can proceed; no READY/merge. | Poll indefinitely or mark green. | P7; maintainer. |
| **D38** | Hosted CI fails on A3 head | **HARD STOP** | Classify job, preserve failed logs and request narrow correction/approval. | Ignore failed job, broaden CI allowlist. | P7; maintainer. |
| **D39** | GitHub auth/remote unavailable after local work | **DEFER AND CONTINUE** | Preserve local commits/evidence, report `PR_CREATION_BLOCKED`; safe auth checks only. | Force push, invent PR/CI status. | P7; maintainer. |
| **D40** | Tests find old-format and new-format segment size differs | **AUTO-RESOLVE** | Record both exact bytes, do not set speed threshold or retune. | Reject solely due to size absent an existing safety limit; fabricate benchmark. | P5/U12; agent. |
| **D41** | A plan step would require touching forbidden search, writer, remote, manifest, CI, benchmark or fixture paths | **HARD STOP** | Explain need and request scope amendment. | Hidden related edit or broad refactor. | §8; maintainer. |
| **D42** | User/agent requests immediate performance benchmarks or profile | **HARD STOP** | Refer to PERF-06-A4 separately approved qualification. | Running even shortened timed acquisition. | A4 boundary; maintainer. |
| **D43** | Required feature is declared but DICTIONARY/POSTINGS pair missing | **AUTO-RESOLVE** | Reject `Corrupt("split postings feature requires dictionary and postings")`. | Treat as empty legacy segment or accept. | U01/U11; agent. |
| **D44** | Exact source/tests/CI complete and reviewed with no open gate | **AUTO-RESOLVE** | Push one draft PR, report READY_FOR_INDEPENDENT_REVIEW, then stop; no auto-merge. | Starting A4, merging PR. | P7; agent/maintainer. |
| **D45** | Any material condition, architectural choice or failure not covered by D01–D44 | **HARD STOP** | Preserve source/status, report precise facts and minimal approval question; continue only isolated safe work. | Guesswork, redesign, new permissions by inference. | Human maintainer. |

---

## 14. Last instructions to the coding agent

1. Verify A2's real merge and exact required blobs **first**; do not infer it from the user's planning assumption or CI.
2. Before touching production code, perform the invariant challenge, then write RED tests. Follow §§3–5 verbatim and use §13 for every foreseeable obstacle. **You do not own architectural decisions.**
3. Finish **all** approved implementation, QA, actual RustFS acceptance and PR steps under continuous authorization; do not pause at routine checkpoints. A scoped blocker is not permission to abandon unrelated safe tasks.
4. Do **not** modify any persistent format beyond split-postings v1, change original legacy fixture hashes, skip corruption checks, change query scoring, or run real performance measurements.
5. Report the exact final status and evidence. READY means all required real gates passed; CI pending/blocked means NOT READY. Do not merge the PR or start A4.

**Terminal desired result:** a small, source-verified and independently reviewable PERF-06-A3 PR that delivers a deterministic versioned split-postings codec, **not** a benchmark result or a new search engine architecture.
