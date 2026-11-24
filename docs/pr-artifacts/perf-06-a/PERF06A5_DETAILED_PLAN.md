# PERF-06-A5 — Adaptive postings without short-list metadata waste
## Detailed implementation and execution contract

**Repository:** [yduchesne/quervant](https://github.com/yduchesne/quervant)  
**Source inspected:** main at `5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d`, the merge of A4 PR #123  
**Plan status:** complete proposed design; implementation and acceptance have not been performed by this planning document  
**Suggested implementation branch:** `dev/perf06-a5-adaptive-postings`  
**Repository copy of this plan:** `docs/pr-artifacts/perf-06-a/PERF06A5_DETAILED_PLAN.md`  
**Execution report:** `docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md`  
**Minimum authoring authority:** [DETAILED_PR_PLAN_AUTHORING_GUIDE.md at the inspected revision](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md)

**Navigation:** [Execution contract](#0-instructions-to-the-executing-coding-agent) · [Scope and files](#3-scope-and-file-allowlist) · [Frozen format](#5-frozen-format-and-compatibility-design) · [Encoder cost contract](#6-encoder-algorithm-and-explicit-cost-contract) · [Reader semantics](#7-reader-parsing-errors-and-state-transitions) · [Tests](#10-unit-tests-and-independent-byte-oracles) · [Integration](#11-real-integration-and-structural-size-acceptance) · [Execution sequence](#13-ordered-execution-sequence) · [Commands/gates](#14-authoritative-commands-topology-and-gates) · [Decision matrix](#15-preauthorized-architectural-decisions-and-exception-handling-matrix) · [Acceptance](#18-objective-acceptance-reviewer-checklist-and-pr-description)

## 0. Instructions to the executing coding agent

Implement the design in this document. Do not select another representation, threshold, compatibility policy, validation policy, allocation strategy, benchmark methodology, or algorithm. The decision matrix in §15 is the complete exception authority. An unlisted condition is a **HARD STOP for affected work**; record it and obtain an amendment before proceeding with that work.

**Continuous execution authorization:** Once the maintainer directs you to execute this plan, execute it from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. An informational checkpoint is not an approval request.

This document is a planning deliverable. Its creation does not itself launch implementation. Subsequent authorization to execute this complete plan covers the prescribed source edits, tests, documentation, local commits, ordinary branch push, and creation/update of a separate **draft implementation PR**. Do not ask for permission again at those routine delivery steps. Do not merge, release, deploy, send Slack/email messages, or start a performance acquisition. If remote access prevents delivery, finish the reviewable local change and exact PR text, record the external blocker, and continue every independent gate.

**Performance sensitivity is a binding requirement.** Compact encoding uses one final output allocation, shared validation with fused size accounting, and no scratch stream buffers. Compact reading borrows existing bytes and preserves A2's occurrence-allocation avoidance. Long-list encoding delegates directly to the existing A3 encoder before compact-only work. Structural witnesses and source review verify those properties; A6 will assess latency and writer cost. Do not replace performance-sensitive implementation with an easy but wasteful implementation and call it equivalent.

## 1. Purpose, evidence, and roadmap disposition

### 1.1 The specific problem

A3 emits a 56-byte per-term header plus a 40-byte directory entry for every block of up to 128 postings. Even a singleton therefore carries 96 bytes of structural metadata. The A4 benchmark corpus indexes unique `doc_id` values: most lists contain one document and cannot benefit from a block directory. The increased footprint is principally fixed metadata per tiny list, not larger document content or BM25 state.

A5 has one architectural concern: **choose a compact, independently framed postings representation for lists of 1–128 documents while retaining A3's split representation for longer lists**. Preserve A1 scoring, A2 lean decoding, the logical posting data, and all publication/search correctness contracts.

A source review also found an existing producer difference: `SegmentBuilder` emits A3 split postings, but `index/merge.rs` compaction still calls the legacy interleaved encoder. A5 must wire the same adaptive encoder into both producers. This is a narrow codec integration change; the compaction algorithm and publication protocol remain intact.

### 1.2 What has and has not been accepted

| Work | Source/status at planning | Treatment in A5 |
| --- | --- | --- |
| A1: query-local BM25 preparation | Merged; already implemented | Preserve; run score-contract regression tests. |
| A2: consuming document/frequency-only cursor | Merged; already implemented | Preserve shared validation, ownership, cancellation and limits. |
| A3: versioned separated streams | Merged; implemented in ordinary segment building | Retain old codec and long-list bytes. Add compact small-list representations and cover compaction producer. |
| A4 first acquisition | Historical unfavorable/incomplete evidence exists | Preserve its result and report verbatim. Do not reclassify it. |
| A4 second acquisition | COMPLETE; 16/16 A/A controls and 12/12 guards passed; 2/4 primary lanes met the ≥5% target | Preserve `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED` as the measured disposition. |
| A4 merge | User states merged; inspected main includes PR #123 | Record maintainer decision to retain A1–A3 and merge A4. Merge is not proof that all original performance targets passed. |
| A5 | NOT STARTED at inspected main | This implementation/correctness/structural-size PR. |
| A6 | Planned follow-up, no acquisition authorized here | Consolidated storage and warm-query preservation qualification, with its own detailed plan and acquisition authorization. |
| PERF-06-B1 | Next architectural series after A follow-up acceptance | Remains blocked pending A6 evidence and maintainer disposition; do not start B1 in A5. |

The updated dependency is **A1 → A2 → A3 → A4 (merged, targets not all met) → A5 → A6 → B1 → B2 → B3 → B4 → C1 → C2 → C3 → C4**. B1 remains persistent keyword ordinals; A5 does not absorb that design.

A4 compared pre-A1 Quervant `2a74017958c8ac61948f931e8745bf8134827025` with cumulative A1–A3 source `b70f624fffe0329def62701b61e997c4e303e167`. Its measurements do not isolate the contribution of individual A stages. The second campaign's primary gains were +6.7170%, +5.6911%, +3.3231%, and +2.1053%. These are historical cumulative results, not predicted A5 performance.

### 1.3 Footprint model and evidence boundary

For the frozen 10K/100K corpus, `runtime.py::row_values` yields `N+1` singleton terms: N unique `doc_id` terms and one `key=singleton` term. The other four indexed lists are long. The current builder creates positional occurrences for Keyword as well as Text fields; do not infer doc-only encoding from field type. Each of these singleton positional lists retains the same data bytes but replaces 96 metadata bytes with a six-byte compact header, saving **90 bytes**. Replacing E/1 with F/1 does not change feature-tuple length.

| Corpus | Recorded A3 index bytes from A4 | Predicted A5 bytes | Predicted reduction from A3 |
| --- | ---: | ---: | ---: |
| 10,000 documents | 2,356,869 | 1,456,779 | 900,090 bytes, about 38.19% |
| 100,000 documents | 23,713,222 | 14,713,132 | 9,000,090 bytes, about 37.95% |

Formula: `predicted_A5_bytes = recorded_A3_bytes - 90 * (N + 1)`, conditional on the identical corpus, schema, one-segment build shape, and unchanged remaining files.

These are **source-derived projections**, not measured A5 indexes. A5 verifies exact small-fixture sizes and structural arithmetic. It does not build/timestamp full benchmark indexes or create benchmark results. A6 owns actual benchmark-corpus index sizes, writer diagnostics, and warm latency qualification. Do not claim a speedup, unchanged latency, RSS reduction, or reduced build time from the size model.

## 2. Source basis, ownership, and verified reuse

### 2.1 Pinned source anchors

All paths in this plan are repository-relative unless expressly called local report paths. Symbol names are navigation anchors; line numbers can shift. Use the pinned source when resolving meaning, then apply §15 for drift.

| Path | Verified Git blob at inspected main | Relevant symbols / obligation |
| --- | --- | --- |
| `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` | `c871d370dc050fad9457bfa81a8421dbb846fbf2` | Correctness-first plan, continuous execution, evidence separation, decision matrix. |
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` | Repository architecture, testing and coverage gates. |
| `docs/TESTING.md` | `91c8643eaa041b0cb475949bcefa7c074ae27fe3` | Real algorithm tests, real filesystem/RustFS boundaries, 85% floor. |
| `crates/quervant-core/src/segment/postings.rs` | `c5d4d46d7cf5a3fa2ed8b9ce4211ecf8b8317945` | Shared source validator; legacy/split encoders; full/lean shared cursor. |
| `crates/quervant-core/src/segment/format.rs` | `000b56a5d3d89bf064f03bbc9ede1e9f2d182b27` | Feature constants, ByteReader/ByteWriter, canonical varints, required-feature support. |
| `crates/quervant-core/src/segment/build.rs` | `a05bae5056a64314fa4e0141f4f5e50d32bda85e` | Per-term encoder call and segment feature emission. |
| `crates/quervant-core/src/segment/reader.rs` | `a1da7a30e10e2c85c5dccbd6725af89c297eb373` | `postings_for_entry`, metadata verification and format dispatch. |
| `crates/quervant-core/src/index/merge.rs` | `0443c600cd3c362f41fa2057883265d659adfaa2` | Per-term compaction encoding; `build_merged_segment` feature/section pair. |
| `crates/quervant-core/src/segment/limits.rs` | `bf222b67e0675aadf6137642748d6b7f4c781328` | Existing encoded/decoded/allocation limits; no new knobs. |
| `crates/quervant-core/src/segment/manifest.rs` | `a67eb89c02a4c8c98cacb910308ca2f74b4a6c16` | Per-segment required features; layout unchanged. |
| `crates/quervant-core/src/index/writer.rs` | `20f0dc29fa00ce40663ee4b492424bf640cffea4` | Publication, immutable generations, state pointer handling; unchanged. |
| `crates/quervant-core/src/index/support.rs` | `d9342fbe60688683b5e0d8c56b7ccf6ca51ff58b` | Segment metadata propagation; unchanged. |
| `crates/quervant-core/tests/pr07_compatibility.rs` | `40a2fde5102379e935bc6bc6d895ea55f82c2107` | Complete legacy index fixture and actual append/reopen compatibility. |
| `.github/workflows/ci.yml` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` | Current mandatory CI and pinned RustFS topology. |
| `Cargo.toml` / `Cargo.lock` | `40bd37bd5314009eeb7b81f201f5ae0180be26f7` / `a230eb28d692c543fd541e7a9eaa0980e678e40e` | Rust workspace, MSRV and dependencies unchanged. |
| `rust-toolchain.toml` | `73cb934de4706a914c15e8db2a3c037ce75699d9` | Requests stable; CI pins 1.98.1, MSRV job pins 1.85.0. |
| `benchmarks/quervant_bench/lean/runtime.py` | `0081b0d4600bc33f974960a0a9a700c7342dd50e` | Corpus source used only for footprint arithmetic. |

Source links: [postings](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/segment/postings.rs), [segment builder](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/segment/build.rs), [reader](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/segment/reader.rs), [compaction](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/index/merge.rs), [CI](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/.github/workflows/ci.yml).

### 2.2 Existing architecture to reuse

| Component / boundary | Existing contract | A5 action |
| --- | --- | --- |
| Workspace | `quervant-core`, `quervant-objectstore`, `quervant-distributed`; Rust 2024 | Production edits limited to core codec integration. No dependencies, crate/features or toolchain edits. |
| `SegmentBuilder` | Analyzes inputs, maps logical records to physical IDs, builds dictionary/postings and immutable segment | Change only encoder selection and required postings feature. |
| `IndexWriter::compact` / `index::merge` | Decodes and remaps live posting structures; preserves indexed-but-not-stored fields; publishes through existing lifecycle | Change only output posting encoder/feature. Never reanalyze stored documents. |
| `SegmentReader` | Verified immutable bytes, dictionary lookup, lazy term cursor | Select codec from required segment features; borrow exact term extent. |
| `PostingsReader` / `DocFreqPostingsReader` | One owning cursor; shared per-posting semantic validation; consuming conversion | Add a compact stream source to the existing decoder. No second decoder. |
| `ByteReader::varint` | Canonical unsigned u64 LEB128; rejects overflow/noncanonical/truncated data | Reuse for every compact header and body varint. |
| `ByteWriter::varint` | Existing canonical emitter | Reuse; add only fallible capacity construction and a test-only capacity accessor. |
| `SegmentLimits` | Encoded allocation limits and incremental decoded entries/occurrences checks | Reuse exactly; do not add setters or weaken charges. |
| `Directory` / `FsDirectory` | Immutable local files; explicit synchronization and atomic pointer replacement | Real test boundary; no trait or lifecycle changes. |
| `SegmentStore` / `SegmentCache` | Authoritative descriptor lookup versus local materialization | Reuse unchanged. Do not add a codec cache or new store abstraction. |
| `ObjectStore` / production S3 adapter | Immutable object put, exact range get, caller-owned retry policy | Existing RustFS integration only; no remote I/O inside posting loops. |
| Manifest and mutation state | Per-segment content descriptors/features; immutable state references and generation publication | Let existing metadata propagation carry F. No global-manifest feature or pointer rewrite. |
| Search/scoring/phrase/sort | Existing exact result, score, count, cursor, cancellation and duplicate contracts | No production changes. Exercise full and lean callers with new bytes. |

Logical document keys, segment-local physical document IDs, content-addressed segment IDs, manifest generations, and remote object keys remain distinct. Compact encoding changes bytes and therefore normal content digests/segment names. It does not reuse an old digest for new bytes or modify an immutable segment in place.

## 3. Scope and file allowlist

### 3.1 Production changes — exactly five files

1. `crates/quervant-core/src/segment/format.rs`: F feature/support tuple, `ByteWriter::try_with_capacity`, `#[cfg(test)]` capacity accessor.
2. `crates/quervant-core/src/segment/postings.rs`: compact wire constants/encoder/reader source, shared-validator size accounting, fixed lazy error factories, test-only witnesses.
3. `crates/quervant-core/src/segment/build.rs`: adaptive per-term encoder and F feature instead of E.
4. `crates/quervant-core/src/segment/reader.rs`: F/E feature consistency/dispatch and the two specified lazy extent-error factories.
5. `crates/quervant-core/src/index/merge.rs`: adaptive per-term encoder and F inside the existing dictionary/postings emission guard.

No other production file edit is preauthorized. Mechanical imports/docs in these five files are permitted. Do not widen public APIs beyond the new encoder; the new cursor constructor remains crate-internal.

### 3.2 Test changes

| File | Permitted edits |
| --- | --- |
| `crates/quervant-core/src/segment/tests.rs` | A5 codec tests, adversarial fixtures, exact sizes and structural witnesses; narrow A3 fixture migration. |
| `crates/quervant-core/tests/segment_codec.rs` | Current-builder adaptive integration and valid-envelope corruption; preserve explicit A3 tests. |
| `crates/quervant-core/tests/segment_golden.rs` | Add adaptive parity; preserve pinned legacy fixture bytes and A3 coverage. |
| `crates/quervant-core/tests/pr08_integration.rs` | Only the closed known-feature list/current-builder feature assertions in `p8_t42_golden_bytes_features_unchanged`. |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | A5 real FsDirectory search, actual child-process restart, compaction boundary tests, and local test-only helpers. |
| `crates/quervant-core/tests/pr07_compatibility.rs` | A5 legacy-plus-adaptive append/reopen/compaction test using the existing complete fixture. |
| `crates/quervant-core/tests/pr13_remote.rs` | Named A5 real-RustFS cold-reopen test and narrowly shared test helpers. |

Read and execute other relevant existing tests unchanged. No fixture binaries, golden digests, production test toggle, test-dependency additions or new test framework are authorized. If a test outside the allowlist needs changing, apply D26; do not broaden the list yourself.

### 3.3 Documentation changes

Create this plan's repository copy and the A5 execution report. Update only the relevant codec/status sections in:

- `docs/ARCHITECTURE.md`;
- `docs/PERF_OPTIMIZATION_ROADMAP.md`;
- `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`;
- `docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md`.

Keep the original series-opening history identifiable as historical. Add a current-status amendment and A5/A6 rows; do not rewrite prior authorization as if it already included A5. Apply the exact status discipline in §17.

### 3.4 Explicit exclusions

No BM25 arithmetic changes; A1/A2/A3 rollback; skip/seek acceleration; winner-only validation; ordinal/key/sort/executor design; compression library; bit packing; general varint replacement; per-field tuning; new cache; runtime feature flag; new SectionKind; global container-version bump; manifest format change; analyzer/schema/corpus changes; remote lifecycle changes; distributed/vector work; unsafe encoding; dynamic-dispatch hot-loop abstraction; new production logging or counters.

No benchmark `stage`/`prepare`/`run`, adapter build measurement, real timing campaign, Criterion run, `perf`/profiler, RSS experiment, new study configuration/result, or cross-engine acquisition. Repository-prescribed correctness tests and `cargo bench --no-run` are required QA, not authorization to run a benchmark campaign.

**Protected evidence:** both existing `benchmarks/studies/perf-06/warm/results/*.json` acquisitions, all checked-in study configurations, A1–A4 detailed plans/reports, and prior PERF artifacts. Read them; do not edit, replace, prune, regenerate or delete them.

## 4. Observable invariants and traceability

Every row must have its actual test result and command/log reference in the execution report. “Implemented” or “covered by inspection” cannot substitute for the named executed check.

| ID | Falsifiable contract | Implementation steps | Positive / negative acceptance |
| --- | --- | --- | --- |
| INV01 | A5 emits F/1 only for segments with an actual dictionary/postings pair; neither E nor F for no indexed terms. Compaction follows the same rule. | P2, P5 | U01, U12, I01, I05, I06. |
| INV02 | Featureless legacy and E/1 A3 payloads retain original bytes, accepted counts and errors. F's mode is df1 / df2–128 / df≥129. | P2–P5 | U02–U04, U12–U14, I04, I06. |
| INV03 | Full decoding returns input-defined IDs, frequencies and every occurrence exactly; lean returns their ID/frequency projection. | P3–P4 | U02–U04, U07, U14; I01–I04, R01. |
| INV04 | Compact framing is canonical, bounded and exhaustive: no count ambiguity, ignored stream tail, extent escape, alternate grammar or silent fallback. | P3–P5 | U06, U11, U12, I01. |
| INV05 | Invalid source records are not sorted/repaired; preexisting semantic-error precedence remains exact. | P3 | U05, U14, retained A2/A3 tests. |
| INV06 | Shared lazy per-posting validation, decoded-resource charging and cancellation remain; compact construction does not predecode postings or charge decoded entries eagerly. | P4 | U07–U11; I02 and inherited cancellation/resource suites. |
| INV07 | Compact encoding validates once, measures during that walk, reserves one final output buffer, and never grows it or creates three transient stream buffers. | P3 | U15, U16, source ownership checklist. |
| INV08 | Adaptive long-list encoding calls A3 once with zero compact sizing/reservations; bytes are identical. Existing A3 directory validation remains. | P3–P4 | U04, U13, U15; retained A3 tests. |
| INV09 | Valid compact cursor construction borrows bytes with no heap allocation; lean mode allocates no occurrence vector and clones no cached full posting. | P4–P5 | U10, U15, source ownership checklist. |
| INV10 | Actual returned scores, total counts, ordering, phrase semantics, cursors, deletes/upserts and PIT visibility remain correct. | P5–P6 | I02, I03, I05, I06; SC01–SC16 and inherited mutation tests. |
| INV11 | Existing publication/recovery/cache/immutable object behavior remains; no segment or sidecar is rewritten in place. | P5–P6 | I03, I05, I06, R01; mandatory local/remote regression suites. |
| INV12 | Sizes are deterministic for exact input; compact size fixtures equal independent byte arithmetic, long bytes equal A3; no performance claims from structural tests. | P3, P6–P7 | U13, U16, S01, report labels. |
| INV13 | A4 negative evidence and all configurations/results remain immutable; A5 statuses follow passed gates. | P0, P7–P8 | Protected-file diff/hash check, evidence/status review. |

## 5. Frozen format and compatibility design

### 5.1 Feature and representation table

Add `pub const FEATURE_ADAPTIVE_POSTINGS: u16 = 0x000F;` in `segment/format.rs` and add `(FEATURE_ADAPTIVE_POSTINGS, 1)` to `SUPPORTED_FEATURES`. The inspected required-feature namespace has no F entry. `SectionKind::MutationState` also uses numeric 0x000F in a different namespace; that is not a collision and must not be renumbered.

Retain `FEATURE_SPLIT_POSTINGS = 0x000E` and E/1 support. F is the complete adaptive-family selector, not an optional extension to E.

| Required postings feature for one segment | Allowed term representation | Constructor |
| --- | --- | --- |
| Neither E nor F | Existing legacy marker 0/1 | Existing `PostingsReader::new` unchanged. |
| E/1 only | Existing A3 marker 2/3, version1, at every previously valid df including1 | Existing `new_split` unchanged. |
| F/1 only; df1 | Marker4 doc-only / marker5 positional | New `new_adaptive` compact branch. |
| F/1 only; df2..128 | Marker6 doc-only / marker7 positional | New `new_adaptive` compact branch. |
| F/1 only; df≥129 | Existing A3 marker2/3, version1, byte-for-byte unchanged | `new_adaptive` delegates to `new_split` once. |
| Both E/1 and F/1 required in the same segment | Invalid | Reject before publishing verified segment metadata. |
| F optional only | Does not select adaptive parsing | Required-feature dispatch remains authoritative. |
| Unknown required feature/version | Unsupported | Existing `UnsupportedFeature` path. |

Different segments in the same index may have different families. E in one segment and F in another is valid; never enforce the E/F exclusion at index-wide manifest scope. No global manifest F feature is added. Existing manifest references carry the segment's actual required features normally.

An older **container reader** without F support rejects an F-required segment via feature negotiation. A raw old `new_split` can still decode byte-identical long 2/3 payloads; it has no container-feature context. Do not claim otherwise. Old-binary rejection is a source-derived compatibility property unless an old executable is actually run; current unknown-version tests are not old-binary evidence.

### 5.2 Compact wire layout

All `v` fields are canonical unsigned u64 LEB128.

| Order | Field | Singleton (markers4/5) | Short (markers6/7) |
| --- | --- | --- | --- |
| 1 | `marker:u8` | 4 doc-only; 5 positional | 6 doc-only; 7 positional |
| 2 | `payload_version:u8` | Exactly1 | Exactly1 |
| 3 | `posting_doc_count:v` | Omitted; implicit1 | Explicit, exactly2..128 |
| 4 | `freq_total:v` | Sum of real per-posting frequencies | Same |
| 5 | `doc_stream_len:v` | Length D in bytes | Same |
| 6 | `freq_stream_len:v` | Length F in bytes | Same |
| 7 | `pos_stream_len:v` | Length P in bytes; zero for doc-only | Same |
| 8 | Document stream | First document ID absolute | First absolute; subsequent positive deltas |
| 9 | Frequency stream | One real frequency varint | One real frequency varint per posting |
| 10 | Position stream | Existing occurrence fields if positional | Same, history resets per posting |
| 11 | End | Exact end of term extent | Exact end of term extent |

There are no flags, reserved fields, padding, directory, secondary format wrapper, field-specific variants, or inline singleton frequency shortcut.

The occurrence encoding is unchanged: position delta, position length, value index, start offset, end offset; each is a varint. First position is absolute; later deltas are positive. Value-index monotonicity resets for each posting, and offsets retain their existing rules. Frequencies/positions are not omitted because a caller wants lean output.

Let `V(x)` denote canonical varint width:

- Singleton size: `2 + V(freq_total) + V(D) + V(F) + V(P) + D + F + P`.
- Short size: the singleton expression plus `V(df)`.
- The minimum headers are6 and7 bytes, respectively; headers are not fixed-size when values grow.
- At df≤128 the compact header is at most44 bytes; A3's header+one-directory-entry is96 bytes. The underlying three streams for that single block encode the same values. Compact is strictly smaller for every valid short input, without a dynamic size-selection heuristic.

### 5.3 API and private state

Retain existing public legacy and A3 encoder signatures. Add:

```rust
pub fn encode_adaptive_postings_block(
    segment_doc_count: u64,
    postings: &[Posting],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>>;
```

Add inside the existing `impl<'a> PostingsReader<'a>`:

```rust
pub(crate) fn new_adaptive(
    bytes: &'a [u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> SegmentResult<Self>;
```

Extend existing `PostingStreams<'a>` with `Compact(CompactStreams<'a>)`. The private compact state has exactly:

```rust
struct CompactStreams<'a> {
    docs: ByteReader<'a>,
    freqs: ByteReader<'a>,
    positions: ByteReader<'a>,
    observed_freq_total: u64,
}
```

Implement a bounded `Debug` arm/implementation consistent with the existing Split variant. Do not print payloads. Retain all other `PostingsReader` cursor fields, `DecodeDetail`, `DocFreqPostingsReader` and public methods. The lean reader currently exposes `next` and `next_with`; **do not invent a lean advance API**.

For the shared encoder validator, use:

```rust
#[derive(Clone, Copy, Default)]
struct CompactLengths {
    docs: u64,
    freqs: u64,
    positions: u64,
}

struct PostingsSource {
    positional: bool,
    posting_doc_count: u64,
    freq_total: u64,
    compact_lengths: Option<CompactLengths>,
}

fn validate_source_postings<const MEASURE_COMPACT: bool>(
    segment_doc_count: u64,
    postings: &[Posting],
    limits: &SegmentLimits,
) -> SegmentResult<PostingsSource>;
```

`None` means measurement disabled when the const parameter is false; during enabled validation it can also remember length overflow. Only after all original semantic validations succeed may enabled measurement failure return adaptive `"length overflow"`. A successful enabled call returns `Some`. No new public result type, dynamic visitor, trait, callback framework, or allocation is needed.

## 6. Encoder algorithm and explicit cost contract

### 6.1 Dispatch first; validate once

The first branch in `encode_adaptive_postings_block` is:

```rust
if postings.len() > 128 {
    return encode_split_postings_block(segment_doc_count, postings, limits);
}
```

It precedes compact validation, size accounting, allocation and temporary construction. The existing A3 encoder calls `validate_source_postings::<false>` once; the legacy encoder does likewise. The compact path calls `::<true>` once. Empty input follows the existing shared source error.

Do not prevalidate the adaptive long path and then call an encoder that validates it again. Do not add compact size arithmetic to the false specialization.

### 6.2 Preserve original validation order; fuse measurement

The existing order is authoritative:

1. Determine whether any source posting has occurrences.
2. Check posting count against `max_postings_per_term`; reject empty; reject count greater than segment document count.
3. Checked sum of source frequencies; reject frequency-total overflow.
4. In source order: document range, nonzero frequency, strict document monotonicity, positional frequency/occurrence-count equality, then each occurrence's position length, offsets, value-index monotonicity, and strict position monotonicity.

Preserve that order and all existing typed errors/details. Do not combine preliminary frequency summation with the later validation walk: that would change which error wins.

For enabled compact measurement, count document/frequency widths during the existing per-posting loop, and five occurrence widths during the existing occurrence loop, after the relevant source values have passed their original checks. Use previous document/position values before updating them. No additional occurrence traversal solely for sizing is allowed.

Use the private pure width helper:

```rust
fn compact_varint_len(value: u64) -> u64 {
    u64::from((u64::BITS - (value | 1).leading_zeros()).div_ceil(7))
}
```

The OR with1 gives zero the correct width1. The helper calculates size only; `ByteWriter::varint` remains the sole production emitter. Perform every length addition with checked arithmetic. If measurement overflows, keep validating all original semantic rules and report the new overflow only after those succeed. Do not allocate enormous inputs to exercise arithmetic failure; use bounded arithmetic helper tests.

The false const specialization has no width calls or compact measurement loops. Preliminary `any` and frequency summation are retained existing passes, not newly introduced duplication.

### 6.3 Admit and allocate one output

After successful source validation, calculate header length from the fixed grammar. Add the private `fn compact_total_len(header_len: u64, lengths: CompactLengths) -> SegmentResult<u64>` helper: start at header_len, checked-add docs, freqs and positions in that order, returning adaptive `"length overflow"` on failure. Use it for the encoder total and, after parsing, compact constructor geometry. U16 directly tests tiny synthetic numeric arguments such as header_len1/docs=u64::MAX; no enormous source allocation is implied. Check `max_single_allocation` and conversion to `usize` before reserving memory in the encoder. The reader checks exact extent, without charging a new encoded allocation for borrowed bytes.

Add this minimal method to the existing `ByteWriter`:

```rust
pub(crate) fn try_with_capacity(
    capacity: usize,
) -> Result<Self, std::collections::TryReserveError> {
    let mut buf = Vec::new();
    buf.try_reserve_exact(capacity)?;
    Ok(Self { buf })
}
```

Existing `new`/`with_capacity` and unrelated callers remain unchanged. Map compact reservation failure to the existing `SegmentError::LimitExceeded { limit: limits.max_single_allocation(), requested: total }` convention. Total arithmetic overflow is adaptive corruption `"length overflow"`. An over-limit total or failed usize admission is the corresponding existing LimitExceeded form.

Allocate one final ByteWriter, emit the compact header, then D, F and P directly into it:

1. One bounded pass over ≤128 postings writes document IDs/deltas.
2. One bounded pass over the same postings writes frequencies.
3. If positional, one pass writes each occurrence once with the existing varint emitter and per-posting reset.

The occurrence data is visited once for validation/measurement and once for final encoding. Do not create D/F/P ByteWriters, concatenate three vectors, copy complete streams, clone source postings, collect offsets, or build a directory. No reserve-and-shift header placeholder, unsafe uninitialized buffer, backpatching scheme or shrink-to-fit pass.

Debug assertions and U15/U16 check header and each stream endpoint, final length and unchanged capacity after the initial reservation. `try_reserve_exact` may receive a larger allocation from the allocator; assert `final_capacity == initial_capacity` and `capacity >= total`, not `capacity == total`.

The one-buffer contract applies **inside the per-term compact encoder**. Existing callers copy the returned term bytes once into the segment's aggregate postings body. Removing that existing caller copy or redesigning the whole segment builder is outside A5.

### 6.4 Lazy error construction at the affected successful paths

Use lazy error factories in new code. Make exactly these existing String-bearing `ok_or(...)` conversions to `ok_or_else(|| ...)`, retaining identical error values and ordering:

| File / site | Fixed error detail |
| --- | --- |
| `postings.rs::validate_source_postings` frequency sum | `frequency total overflow` |
| `postings.rs::read_one_with` checked position addition | `position overflow` |
| `postings.rs::read_doc_id` legacy branch shared with Compact | `doc id overflow` |
| `reader.rs::postings_for_entry` checked extent addition | `posting extent overflow` |
| `reader.rs::postings_for_entry` slice lookup | `posting extent out of range` |

This avoids constructing and dropping error Strings on valid operations. Do not sweep unrelated code or change the separate A3 split document branch. Cheap typed errors without owned Strings need no conversion for this contract. Error construction may allocate when an error is actually returned.

### 6.5 Structural witnesses; no production instrumentation

Add `#[cfg(test)] pub(crate) mod encode_observation` beside the existing decode witness. Use thread-local `Cell` state, reset/read helpers and this fixed count record:

```rust
#[derive(Clone, Copy, Default, Debug, PartialEq, Eq)]
pub(crate) struct Counts {
    pub validation_calls: u64,
    pub compact_validation_calls: u64,
    pub width_calls: u64,
    pub compact_output_buffers: u64,
    pub initial_capacity: usize,
    pub final_capacity: usize,
}
```

Record validator entry, enabled-validator entry, private width-helper calls, successful compact writer allocation and capacity at allocation/finish. Add only `#[cfg(test)] pub(crate) fn capacity_for_test(&self) -> usize` to ByteWriter. No production counters, allocator replacement, logging or tracing.

The unit tests live in sibling `segment/tests.rs`, so they cannot call postings-private helpers directly. Keep those production helpers/types private and add these two **test-only** wrappers inside encode_observation:

```rust
pub(crate) fn test_varint_len(value: u64) -> u64 {
    super::compact_varint_len(value)
}

pub(crate) fn test_total_len(
    header: u64,
    docs: u64,
    freqs: u64,
    positions: u64,
) -> super::SegmentResult<u64> {
    super::compact_total_len(
        header,
        super::CompactLengths { docs, freqs, positions },
    )
}
```

U16 uses those wrappers. Reset observations after direct width-helper tests and before U15 encoding assertions; do not widen production visibility for test access.

For valid compact input with n postings and m occurrences, expected width calls are `2*n + 5*m + 4` for singleton, or `2*n + 5*m + 5` for short; the final4/5 are header field widths. No extra measurement call is needed for marker/version. Counts are1 validator,1 compact validator,1 compact output buffer, and unchanged capacity. For adaptive long input:1 validator,0 compact validators,0 width calls,0 compact buffers. Produce the A3 oracle before resetting counters.

These witnesses prove named control-flow/allocation sites together with source review. Do not call them a whole-process heap profiler or a measurement of total allocator activity. Compact valid-constructor allocation freedom is additionally a structural review of borrowed fields and code paths, not an invented global allocation counter.

### 6.6 Complexity and auxiliary-memory bounds

Here n is posting document count and m is total positional occurrence count. These are structural algorithm bounds, not measured runtime claims.

| Operation | Required work bound | Auxiliary memory beyond input/required output |
| --- | --- | --- |
| Compact validation plus fused measurement | O(n+m), with original preliminary passes retained and no additional occurrence sizing pass | O(1) scalar state; no heap allocation on valid input. |
| Compact final emission | O(n+m); separate D/F scans are bounded by n≤128, occurrences emitted once | One admitted output Vec plus O(1) state; no scratch stream copies. |
| Valid compact cursor construction | O(1) bounded header parsing and checked slicing; no body scan | Borrowed readers and scalar cursor state; no heap allocation. |
| Long adaptive encoding/reading route | O(1) selector work plus the existing A3 algorithm | No added compact buffers/measurements; A3's existing costs remain. |
| Lean compact posting consumption | O(freq) when positional because all occurrences must be validated | O(1) extra state; no occurrence vector/cache clone. |
| Full compact posting consumption | O(freq) including required occurrence materialization | Existing full-mode O(freq) result/cache behavior retained. |

No new sorting, quadratic rescanning, per-posting dictionary lookup, per-term eager body scan, or per-query format conversion is permitted. Do not remove necessary validation merely to obtain a smaller asymptotic or allocation claim.

## 7. Reader parsing, errors, and state transitions

### 7.1 Required-feature dispatch and metadata precedence

In `reader.rs` preserve the existing sequence through `ensure_supported_features`, schema/norms/remap/dictionary parsing and dictionary/postings pair/extent checks. Then:

1. If both E/1 and F/1 are required in this segment, return adaptive corruption `"conflicting postings features"`.
2. If F/1 is required but the entire dictionary/postings pair is absent, return adaptive corruption `"adaptive postings feature requires dictionary and postings"`.
3. Keep the existing E whole-pair-absence check and its error unchanged.

A single missing section must retain the earlier `MissingSection` error even if the feature set is also conflicting. Existing preceding schema/norm/dictionary errors also retain precedence. Do not reorder all metadata validation for this feature.

In `postings_for_entry`, after the existing checked extent extraction, choose F → `new_adaptive`, else E → `new_split`, else `new`. Keep the existing dictionary `doc_freq` versus parsed count comparison/error after construction. Both `postings(field, term)` and `postings_for_entry` must use this one path.

### 7.2 Compact constructor — exact ordered checks

Use private `ADAPTIVE_CONTEXT = "adaptive postings"` and `adaptive_corrupt(detail: &'static str)` producing the existing Corrupt variant with a fixed bounded detail.

For a marker2/3 input, delegate to `new_split` once, with the original complete byte slice. Only after it succeeds, reject `posting_doc_count <= 128` with adaptive `"noncanonical split posting count"`. Return the existing Split cursor otherwise. Do not preparse the A3 header or directory, validate it twice, or change its errors. One leading-byte mode inspection and the canonical-count check are the only new adaptive routing work.

For compact markers, process in this exact order:

| Order | Check | Required error |
| --- | --- | --- |
| 1 | Read marker; accept4/5/6/7 in compact branch | Existing Truncated with `"adaptive occurrence marker"`, or adaptive `"invalid occurrence marker"`. |
| 2 | Read version; require1 | Truncated with `"adaptive payload version"`, or adaptive `"unsupported payload version"`. |
| 3 | Singleton count implicit1; short reads canonical count and requires2..128 | Varint errors use `"adaptive posting doc count"`; out-of-mode count uses `"noncanonical compact posting count"`. |
| 4 | Count ≤max_postings_per_term, then ≤segment_doc_count | Existing LimitExceeded; then adaptive `"posting count exceeds segment doc count"`. |
| 5 | Read freq_total; require ≥count | Varint errors use `"adaptive freq total"`; adaptive `"frequency total below posting count"`. |
| 6 | Read D, F, P in order; retain header end | Varint contexts `"adaptive doc stream length"`, `"adaptive frequency stream length"`, `"adaptive position stream length"`. |
| 7 | If positional, checked `5*freq_total` ≤P; if doc-only P==0 | Multiplication overflow: `"length overflow"`; too short: `"position stream too short"`; nonzero doc-only P: `"doc-only positional bytes"`. |
| 8 | D≥count, then F≥count | `"doc stream too short"`, then `"frequency stream too short"`. |
| 9 | Checked `header_end + D + F + P` equals exactly the term slice length | Overflow/conversion: `"length overflow"`; unequal extent: `"extent length mismatch"`. |
| 10 | Take the three validated borrowed slices, initialize cursor fields | No heap, payload predecode, directory or cache. |

Require canonical varints via existing ByteReader. Check lengths in u64 before checked conversion/slicing. Do not add an upper-bound heuristic on stream lengths; semantic parsing and final exhaustive consumption detect padding or malformed data.

The constructor does **not** call `check_entries(df)` or `check_alloc::<Occurrence>(freq_total)`, and does not reject a sum merely because it exceeds one posting's decoded-entry limit. Decoded budgets remain incremental. A valid df2 payload with `max_decoded_entries=1` must construct successfully, yield the first posting, then fail on the second attempted posting.

### 7.3 Extend the shared decoder only

Use a shared match alternative for the identical Legacy and Compact document-delta logic:

```rust
PostingStreams::Legacy(reader)
| PostingStreams::Compact(CompactStreams { docs: reader, .. }) => {
    // Existing legacy absolute-first/positive-delta logic, unchanged errors.
}
```

Use the existing `"doc id delta"` varint context, NonMonotoneDocId and `"postings"/"doc id overflow"` error. Leave the Split directory/boundary logic intact.

Add Compact arms to `read_frequency` and `position_varint` using its respective borrowed readers. Keep `read_one_with` as the single semantic decoder, in its original order:

- cancellation before any attempted next, including already-finished EOF;
- incremental posting entry limit;
- document decode/range;
- frequency decode/nonzero/per-posting decoded-entry limit;
- hypothetical occurrence-allocation charge for positional data, even in lean mode;
- each occurrence's complete semantic validation;
- cursor count/previous-document update;
- checked observed frequency sum for Split and Compact.

For Compact sum overflow use adaptive `"frequency total overflow"`; retain Split's original context and legacy behavior. Do not add an EOF frequency-sum check to the old legacy format.

Compact `finish` checks, in order: document stream empty; frequency stream empty; position stream empty; observed sum equals header freq_total. Exact adaptive details are `"doc stream trailing bytes"`, `"frequency stream trailing bytes"`, `"position stream trailing bytes"`, `"frequency total mismatch"`. Publish `finished=true` and clear current only after success.

### 7.4 Cursor-state and failure contract

| State / operation | Result and remaining state |
| --- | --- |
| Constructed, no reads | Headers/geometry checked; body semantics still lazy; docs_read0; currentNone. |
| Full `next[_with]` succeeds | Existing full posting, cache and clone behavior retained. |
| Lean `next[_with]` succeeds | Same validated ID/frequency; no occurrence reserve or cached-posting clone. |
| Convert full cursor with `into_doc_freq` | Consume ownership, discard cached full posting, continue at next unread posting with all stream offsets/sums intact. Never restart. |
| Full `advance(target<=current.doc_id)` | Existing cached-return behavior; no cancellation poll on this no-read path. Preserve this exception. |
| Full `advance` needs another posting | Sequential shared next calls; no seek, no bypass of corrupt intervening data or budgets. |
| Cancellation before attempted next | Cancelled wins before EOF/body work; no byte consumption by that attempt. |
| Normal end | Final stream and sum checks, then stable None on later uncancelled next calls. |
| Cancelled next after normal end | Cancelled, as before; do not move EOF ahead of cancellation. |
| Corruption or resource error during decoding | Return typed error. Some bytes/state may have advanced; caller discards cursor. No new rollback/resume guarantee. |
| Reopen immutable bytes | Independent fresh cursor; no mutable shared decoder cache. |

## 8. Producer integration and publication

### 8.1 Ordinary segment building

In `segment/build.rs` replace the per-term `encode_split_postings_block` call with `encode_adaptive_postings_block` and replace E/1 with F/1 at the existing postings feature emission site. Preserve dictionary offsets/lengths from actual returned bytes and all other features/sections, including positional metadata.

Empty segments and schemas with no indexed terms keep no dictionary/postings pair and neither postings-family feature. Do not emit empty term payloads; an absent term remains a dictionary absence.

### 8.2 Compaction output

In `index/merge.rs`:

1. Replace the imported/called `encode_postings_block` with `encode_adaptive_postings_block` at the existing loop over remapped per-term postings.
2. Import F.
3. In `build_merged_segment`, add F/1 inside the existing `if has_positional` branch beside `FEATURE_POSITIONAL`. In this function that boolean is computed as `!dictionary_fields.is_empty()` and also guards emission of the dictionary/postings pair; retain its existing name/meaning.
4. Make no changes to collected postings, term ordering, document remapping, visibility filtering, cancellation cadence, revisions/tombstones/replay ledger, stored fields, norms, columns, JSON/spatial rebuild, publication or recovery.
5. No indexed terms means the existing guard emits neither pair nor F. A compaction no-op remains a no-op; it must not rewrite a single segment merely to migrate format.

New output count determines representation: compacting64+64 distinct live documents containing a term, with one posting per document, produces short128;64+65 produces long129. Occurrence frequency does not select the mode. Filtering dead documents can cross the boundary in the other direction. Test both directions through public compaction.

### 8.3 Durability and compatibility boundary

Encoder failure returns before a newly encoded candidate can be published; existing writer/merge error handling owns cleanup and retention of the previous committed generation. No retry policy changes.

Existing immutable legacy/E segments remain readable; subsequent normal writes produce F. Normal compaction produces F for its output. No eager migration, in-place feature-bit flip, manifest-side format override or forced reindex is authorized.

Never rewrite only a segment and its manifest in a live index to simulate compatibility: mutation-state sidecars can refer to content-addressed segment IDs. Use the existing complete legacy fixture and public append/compact lifecycle (§11), and standalone explicitly constructed A3 containers for A3 codec tests.

## 9. Correctness gate before production edits

Complete P0/P1 and record this gate before editing any production file. Read the current guide, AGENTS, TESTING, relevant architecture and this entire plan. Build the INV→step→test ledger. The following concrete challenges are mandatory; supply expected results, not only a checklist tick.

| Challenge | Plausible wrong implementation | Required discriminator |
| --- | --- | --- |
| Singleton frequency | Reuse header freq_total as the posting's frequency | Header/body mismatch still constructs where geometry permits, returns the real body frequency, and fails final sum check at EOF. |
| Lean positions | Skip positional parsing to save CPU | A corrupt later occurrence returns the same semantic error in full and lean modes; lean allocation witnesses remain zero. |
| Cheap constructor | Decode all short postings at open | Valid first posting followed by malformed second posting opens; first read succeeds; later read fails. Entry-limit1 test fails only on second read. |
| Mode selector | Choose compact by encoded byte size or only on ordinary builds | Exact df boundaries and real compaction crossing128→129 and129→128. |
| Feature fallback | Sniff an alternate family after a parser error | Wrong required feature/marker pair fails; optional F does not activate adaptive parsing. |
| Dictionary binding | Trust singleton implied count despite dictionary df2 | Existing dictionary-count mismatch error. |
| EOF shortcut | Return None before checking tails/sum or cancellation | Trailing stream/sum errors and cancellation-before-EOF cases. |
| Eager error allocations | Use `ok_or` with an owned String on successful paths | Source audit of the five named factories plus new compact code. |
| One-buffer illusion | Reserve final output but still construct three temporary streams | Ownership/source audit plus U15 counts and capacity/endpoint checks. |
| Double validation | Validate then delegate long lists to A3 | Long-path validation_calls1, compact_calls0 and width_calls0. |
| Historical tests | Rewrite every A3 assertion to F and lose old-format coverage | Explicit A3 reconstruction tests remain and direct historical bytes/digests stay pinned. |
| Corruption fixture | Corrupt bytes but fail only an outer checksum | Recompute valid envelope checksums; assert the intended inner typed error. |
| Mixed compatibility | Rewrite only manifest/segment bytes and ignore state pointers | Use complete fixture/public writer; no ad hoc committed-index rewriting. |
| Exact score oracle | Compare two query paths sharing the same regression | Frozen scalar formula and input-derived expected membership/key sets. |
| Misleading evidence | Label projected sizes or queued CI as measured/PASS | Separate actual measurements, projections, execution and passed gates. |

Use the prescribed cases to write the first tests before the corresponding production implementation. A new symbol may initially cause a compile failure; record that accurately as an interface-not-yet-implemented failure, not a behavioral red test. Current-writer F assertions should fail behaviorally against the baseline. Do not claim all adversarial tests were executed on old source if they cannot compile there.

If the audit finds a contradiction or an uncovered semantic decision, apply §15. Do not repair the design silently. Safe independent fixture preparation/documentation can continue after a scoped STOP.

## 10. Unit tests and independent byte oracles

Place the new unit groups in `src/segment/tests.rs` with the exact prefixes below. Multiple concrete `#[test]` functions per group may use a suffix. Record actual test names and passed counts so a filter matching zero tests cannot pass a gate.

### 10.1 Required unit matrix

| ID / prefix | Required cases and assertions |
| --- | --- |
| U01 / `a5_u01_` | F id/version support, E support retained; current builder emits F only; completely empty and nonempty stored-only schemas emit neither family and no pair; unknown F/version rejected; no SectionKind changes. |
| U02 / `a5_u02_` | Exact four hand-authored singleton/two-document byte arrays below; full records equal literal input; lean equals projection; positional and doc-only singleton frequencies1 and>1; absolute IDs0,127,128,16383,16384. |
| U03 / `a5_u03_` | Short df2,127,128; sparse IDs; varied frequencies; repeated field values with valid position/value-index resets; stream-length varints crossing127/128, and P-length specifically crossing16383/16384. Doc IDs, per-posting frequencies and header frequency totals exercise wider value varints separately. D/F lengths cannot reach16384 for df≤128 (each≤1280 bytes); do not invent such a valid fixture. Marker6/7 determined solely by df and positional data. |
| U04 / `a5_u04_` | Adaptive df129,256,257 output equals old A3 encoder exactly for doc-only and positional inputs; F accepts it; E still accepts old df1/2/128 A3 payloads; F rejects canonical split mode at df≤128 only after old parser succeeds. Malformed A3 error precedence preserved. |
| U05 / `a5_u05_` | Empty source; count>segment count; duplicate/decreasing/out-of-range IDs; zero frequency; frequency/occurrence mismatch; frequency sum overflow; bad position length, decreasing position/value index, reversed offsets. Compare legacy/A3/adaptive source-error variants, contexts and details for common inputs, including doubly invalid source order. Do not allocate billions of records to exceed max_postings_per_term. |
| U06 / `a5_u06_` | Invalid marker/version; each compact header field truncated; overlong and >u64 varints; short counts0,1,129; count>segment docs; freq_total<count; D/F too small; doc-only P>0; positional P<5*freq_total and multiplication overflow; checked extent overflow; both shorter and longer extent; header/body division boundaries. Assert the first error from §7.2. |
| U07 / `a5_u07_` | Lazy full/lean parity for doc delta0, doc-add overflow, doc range, frequency0, invalid frequency varint, repeated/overflowing positions, zero length, decreasing value index, start>end, truncated/noncanonical occurrence fields. At least one clean first posting then corrupt second posting: construction and first read succeed; both APIs fail at second with identical error. |
| U08 / `a5_u08_` | Cancellation before first and subsequent attempted reads, before final exhaustion check, and after successful EOF; repeated uncancelled EOF; full advance across clean/corrupt intervening postings; cached-target full advance exception; conversion then lean next. Cover singleton/short/long as applicable. No lean advance API. |
| U09 / `a5_u09_` | Compact encoded output total at allocation limit and one byte over; max_decoded_entries=1 on df2 (incremental); frequency equal to and one over decoded limit; occurrence allocation exact bound and one below, equally charged full/lean. Oversized forged A3 headers cover max_postings_per_term at the existing parser seam; compact's canonical df≤128 means a default max-postings violation is unreachable without changing limits, so do not add a setter for it. |
| U10 / `a5_u10_` | Reset existing decode_observation: full positional traversal has reserve/clone events; lean traversal has neither. Full one-record read then consuming conversion returns the second record next, retains sums/offsets, drops cached full result. Conversion after all data records preserves subsequent final verification. |
| U11 / `a5_u11_` | Independent singleton/short header frequency versus body frequency; mismatch detected at EOF, not substituted into a returned record. Each stream trailing-byte case reaches the corresponding ordered finish error. For checked observed-sum overflow use bounded doc-only raw bytes with two huge frequencies and a test-local decoded-entry limit of u64::MAX; no huge vector/allocation. Legacy EOF behavior remains unchanged. |
| U12 / `a5_u12_` | Required/optional feature matrix; E+F conflict only within one segment; pair absence and single-section MissingSection precedence; dictionary df mismatch; checked offsets/extents; missing/incorrect format declaration with compact bytes; retain original legacy/E errors. Manifest references may describe separate E and F segments; no index-wide family exclusion is introduced. |
| U13 / `a5_u13_` | Exact six-row size table below, deterministic repeated bytes, all source records preserved, compact strictly smaller than A3 at df≤128, long identity. No timing assertion. |
| U14 / `a5_u14_` | Deterministic generated differential cases specified in §10.3; source input is oracle. Compare full outputs and lean projection across legacy/A3/adaptive; no production decode result used to construct expected logical records. |
| U15 / `a5_u15_` | Exact validation/measurement/output-buffer counts and capacity invariants from §6.5; singleton/short doc-only and positional; zero compact work on long path; clean constructor fields borrow slices and introduce no heap-owning state. Audit uninstrumented allocations/passes explicitly. |
| U16 / `a5_u16_` | Varint-width helper at0,1,127,128,16383,16384,u64::MAX gives1,1,1,2,2,3,10; checked-length arithmetic near u64::MAX with tiny synthetic numeric inputs; output endpoint/header-width cases and compact admission before allocation. Compare width with literal expectations, not just another copy of the formula. |

Use the existing SegmentError variants; do not add a testing-only public error. Resource/corruption tests must use bounded bytes or small source vectors. An unreachable allocation-failure branch is a disclosed residual; do not install a global allocator hook or force host OOM to cover it.

For U03's exact P-length boundary, use two positional postings at IDs0/1 with1,638 occurrences each. In each posting positions are0..1637, position_length1, value_index0, start0/end1. The ordinary P length is16,380 bytes. Set position_length128 for the first three occurrences of the first posting to obtain P16,383, and for its first four to obtain P16,384. All other values stay fixed; the length increase is one extra varint byte per changed value. Both inputs satisfy the existing semantic checks and need only bounded test memory.

### 10.2 Literal wire fixtures and exact lengths

These fixtures use doc IDs0..n−1, frequency1. Positional fixtures use exactly one occurrence per document: `(position=0, length=1, value_index=0, start=0, end=1)`.

| n | Legacy doc-only | A3 doc-only | A5 doc-only | Legacy positional | A3 positional | A5 positional |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 19 | 98 | **8** | 24 | 103 | **13** |
| 2 | 21 | 100 | **11** | 31 | 110 | **21** |
| 127 | 271 | 350 | **261** | 906 | 985 | **897** |
| 128 | 273 | 352 | **267** | 913 | 992 | **908** |
| 129 | 275 | 395 | **395** | 920 | 1040 | **1040** |
| 257 | 531 | 692 | **692** | 1816 | 1977 | **1977** |

Literal bytes:

```text
singleton doc-only:
04 01 01 01 01 00 00 01

singleton positional:
05 01 01 01 01 05 00 01 00 01 00 00 01

two-document doc-only:
06 01 02 02 02 02 00 00 01 01 01

two-document positional:
07 01 02 02 02 02 0a 00 01 01 01 00 01 00 00 01 00 01 00 00 01
```

The test must compare the encoder with these literal arrays and independently decode them into expected records. Do not generate the “expected” arrays using the production encoder. Old literal fixtures remain unchanged.

### 10.3 Deterministic generated differential cases

Use a test-local u64 linear-congruential fixture generator, following the repository's deterministic case-generation pattern. This is not a cryptographic primitive, production randomness, dependency or production abstraction:

```text
initial state = 0x504552460006A505
next: state = state.wrapping_mul(6364136223846793005)
                   .wrapping_add(1442695040888963407)
```

Generate exactly64 cases: counts `[1,2,3,127,128,129,256,257]` × doc-only/positional × first-doc bases `[0,127,128,16384]`, in that order. Carry generator state deterministically across cases. First ID is the chosen base; each following ID adds `1 + next()%17`. Each frequency is `1 + next()%4`.

For positional cases, emit exactly freq occurrences. First position0, then add `1 + next()%3`; position length `1 + next()%2`; value index `occurrence_index/2`; start offset `3*occurrence_index`; end offset `start+1`. These are valid multi-value examples under the existing semantic contract. Doc-only cases keep empty occurrence vectors. Set segment_doc_count to last ID+1. Encode all three families, decode to exhaustion with full and lean APIs, and compare with the original generated records/projection.

Failure messages include seed, case ordinal, count, positional mode and base. Retain the failing case. A smaller reproduction may remove a suffix or reduce values while retaining the same failed invariant; that is test diagnosis, not authorization to change the contract.

### 10.4 Historical-test migration is narrow and explicit

Do not globally rename A3 tests as A5. The current default builder changes, so tests that need A3 must explicitly construct A3 bytes:

| Existing test/helper | Prescribed treatment |
| --- | --- |
| Unit `a3_build_segment`, `a3_u01`, `a3_u11` | Use explicit A3 reconstruction for historical assertions. Add separate current-builder A5 tests. |
| Direct `a3_u02` through `a3_u10` and legacy/A2 codec tests | Preserve old byte/error expectations; no adaptive weakening. |
| `a3_u12_determinism_and_structural_size_report` | Preserve old legacy/A3 size table; add A5 evidence separately. |
| `segment_codec::a3_i01_real_segment_split_postings_extents` | Preserve split geometry using explicit A3 container; update descriptive wording if necessary. |
| `segment_codec::a3_i03_legacy_split_parity_and_malformed_body` | Start with explicit A3, preserve valid-envelope inner corruption and legacy parity. |
| `segment_golden::a3_i04_legacy_and_split_segments_share_logical_content` | Preserve explicit A3 parity, add adaptive reader comparison separately. |
| `pr08_integration::p8_t42_golden_bytes_features_unchanged` | Add F to known supported features; current builder positively requires F and negatively E. E stays supported. |
| Existing A3 real-search / remote tests without raw feature assumptions | Preserve semantic bodies as regression; named A5 tests prove new feature classes. |

Test-only A3 reconstruction: read a small valid built container, traverse every term, collect fully validated records, reencode with retained `encode_split_postings_block`, rebuild Dictionary offsets/lengths, replace Postings, replace F with E, preserve every other section body/flags/aux and optional feature. This reconstructed fixture is supplementary differential/old-parser coverage; literal source-input oracles remain primary.

`ContainerBuilder::new` adds a baseline feature. To preserve byte accounting, skip **exactly one** matching baseline tuple when copying the original required feature list, then copy all remaining tuples with their original multiplicity. Replace only the selected postings-family tuple. Do not globally deduplicate features or repair production feature multiplicity. Rebuild outer integrity normally. For no-postings inputs, add neither E nor F.

Never regenerate `golden.seg`, `golden_norms.seg` or the complete historical index fixture. Preserve the existing pinned digest assertions, including the norms golden SHA-256 `49f813a68a4adedf8b69c8a965159a840bc993ca252f81efb1887daa95b5c39b`.

## 11. Real integration and structural-size acceptance

### 11.1 I01 — Actual current SegmentBuilder and dispatch

**File/name:** `tests/segment_codec.rs::a5_i01_adaptive_segment_extents_and_corruption`.

Reuse the file's actual `build`/`document` helpers and `test_schema`. For counts `[0,1,2,127,128,129,257]` build insertion-order documents with unique keys and body `"alpha"`. For each returned SegmentDocument, replace its `fields["tag"]` with `FieldValues::Single(FieldValue::Keyword(format!("unique-{i:05}")))`. Do not change schema: the existing tag is indexed, whereas the helper's original constant `"Alpha"` is not unique. Leave multi-keyword tags x/y as dense positional terms. SegmentBuilder emits occurrences for indexed keywords as well as text; doc-only codec support is tested through explicit Posting fixtures, without changing production field semantics.

Assert F/no-E and exact expected body/dense-keyword positional marker5/7/3 by count, singleton marker5 for each unique tag, and no pair/feature at count0. Compare body records against input-defined IDs/frequency1/occurrence `(0,1,0,0,5)` for the literal alpha token. Check every dictionary extent is valid and contiguous in emitted term order and the last end equals Postings length.

Open through production `SegmentReader`, call both public term lookup and entry lookup, then full/lean traversal. A missing term returns None. For the df2 positional compact term, replace its second posting's position length with0 and rebuild valid outer digests and exact lengths. Container open and the first record succeed; selected traversal returns the inner semantic error; an unrelated clean tag remains readable. Do not report a checksum failure as decoder acceptance.

### 11.2 I02 — FsDirectory search across all three representations

**File/name:** `tests/pr15i_d2a_scoring_contract.rs::a5_i02_adaptive_fs_search_contract`.

Reuse `spec`, `schema`, `registry`, `build`, `request`, `ascend`, `search_ok`, `keys`, `bits_by_key` and `frozen_scalar_bm25`. Create exactly259 DocSpecs:

```text
ordinal i = 0..258
alpha = i % 4 + 1
filler = i % 5
grp = "singleton" when i==0,
      "short" when 1<=i<=128,
      "long" when 129<=i<=258
```

Existing helpers generate logical keys `k00000`..`k00258`, unique indexed `doc_id=d00000`..`d00258`, numeric `n=i%7`, and the body consisting of alpha repeats followed by zeta repeats. Do not introduce an alternate schema or change existing helper behavior.

Commit once and reopen with fresh FsDirectory/Index. Verify the one segment requires F, not E; group markers are5/7/3 for df1/128/130; all unique doc_id terms are marker5; body alpha is positional long marker3. The keyword fields retain their existing occurrences.

Independent expectations:

- Group key sets are exactly their input ordinal ranges.
- Alpha total259; prefix `alph` and `And([alpha])` have the same members and per-key scores.
- Phrase `alpha alpha` matches exactly the194 ordinals where `i%4!=0`.
- Zeta matches exactly207 ordinals where `i%5!=0`.
- Absent term has zero hits and no scores.
- For alpha, n=df259, total alpha frequency646, total filler516, total field length1162. Exact expected score bits are `frozen_scalar_bm25(i%4+1, 259, 259, i%4+1+i%5, 1162.0/259.0).to_bits()`, with integer arguments converted to u64.

Run alpha with explicit ascending sort, relevance sort, K10, K100 and K300. Totals remain259. Full-result key/score map equals the independent map. Each limited result has the expected sorted prefix and exact per-returned-key bits; determine relevance ordering from the independent score map with the existing documented tie rule, not from a new-code reference query alone. Exercise cursor pages using existing SC08 request pattern and verify concatenated exact keys/scores against the independent complete set.

Existing SC07 delete/upsert/PIT, SC12 cancellation/invalid cursor, SC13 candidate limits and SC16 score-boundary tests remain mandatory regressions. A5 need not duplicate those entire scenarios.

### 11.3 I03 — A real new process opens adaptive committed data

**Parent:** `a5_i03_fresh_process_reopens_adaptive`.  
**Child:** `a5_i03_child_reopen_adaptive`, marked ignored with an explanatory reason.  
**File:** same scoring-contract integration file.  
**Environment key:** `QUERVANT_PERF06_A5_REOPEN_ROOT`.

Use the exact129-document fixture from I05 below:64+65 commits, compact once to generation3, then drop all parent writer/index/snapshot/directory handles. Follow the existing subprocess pattern in `pr15i_a_v3.rs::run_child`:

```text
current_exe()
  --ignored --exact a5_i03_child_reopen_adaptive --nocapture
environment: QUERVANT_PERF06_A5_REOPEN_ROOT=<this test's temporary directory>
```

Use `Command::env`; do not mutate process-global environment. The child only opens existing data through new FsDirectory/Index, asserts generation3, one F/no-E segment, and verifies I05's fixed counts, mode classes, full alpha key set and exact frozen-formula score map. It must not create, repair, rewrite or compact. Missing environment in a directly invoked child is a clear failure, not silently skipped success. Require successful child exit and evidence that this exact child ran. No Cargo invocation, external service, golden expected-results file or workflow edit is needed.

The normal parent runs in workspace tests and invokes exactly this ignored child. SC15's same-process reopen remains regression evidence and must not be relabeled as a new-process test.

### 11.4 I04 — Legacy, A3 and adaptive container compatibility

**Files:** `segment_golden.rs` and `segment_codec.rs`; names prefixed `a5_i04_`.

Keep the historical golden files unchanged. For the existing logical golden/schema/input fixture, compare legacy, explicit A3 and current adaptive readers. Assert dictionary term/df, stored values, norms where present, remap, full posting records and lean projection. Compare against original fixture data first; decoded/reencoded differential comparison is supplementary.

Test wrong feature/marker combinations using rebuilt valid envelopes. An F long payload happens to be the same A3 payload; therefore changing F to E on that particular term is not inherently invalid. Use compact markers for the F→E rejection test, and old A3 singleton under F for canonical-selector rejection. No false assertion that every E/F tag swap must fail.

### 11.5 I05 — Real compaction recalculates mode, retains PIT and reopens

**File/name:** `pr15i_d2a_scoring_contract.rs::a5_i05_compaction_reclassifies_adaptive_terms`.

Use `batch(129, |i| i%4+1)`. The existing batch helper fixes filler=i%5 and group=common. Build/commit the first64, commit the remaining65, then reopen generation2 with two F segments.

| Term / behavior | Generation2 | Compacted generation3 |
| --- | --- | --- |
| body alpha | Positional short df64 and65, marker7 | Positional long df129, marker3 under F |
| grp common | Positional short df64 and65, marker7 | Positional long df129, marker3 under F |
| Unique doc_id | Positional singleton marker5 | Positional singleton marker5 |
| body zeta | Short within each input | Short df103, marker7 |
| Alpha matches |129|129|
| Phrase alpha alpha |96|96|
| Zeta matches |103|103|

Keep a generation2 PIT. Call public `writer.compact()` once; it publishes generation3 itself, so do not require another commit. Assert no_op=false, documents129, segments_merged2 and one F output. Drop writer and reopen. Expected alpha scores use n=df129, alpha frequency sum321, filler sum256, total field length577; each key's expected bits are:

```text
frozen_scalar_bm25(i%4+1, 129, 129, i%4+1+i%5, 577.0/129.0).to_bits()
```

Check full map, K10/K100, explicit/relevance sorting, single-term generic fallback and input-defined phrase/zeta members before and after compaction. Repeat the held PIT's saved results bit-for-bit. Do not assert physical document IDs are unchanged; compaction's ordering uses content-addressed segment IDs.

Add bounded sibling cases in the same test group:

- `batch(128, ...)` committed64+64 compacts to short df128, not long.
- In a fresh129 fixture, delete exactly logical key `k00128` through the existing public mutation API used in SC07, commit and compact. Remaining128 alpha/common postings are short; expected membership is the input set minus that key. Preserve a pre-delete PIT and use its old results for immutability.
- Two stored-only segments compact without Dictionary/Postings/E/F. Use a test-local schema with only single I64 field n and `FieldOptions::new(false, true, false)`, keys s0/s1 with values0/1; no analysis or alternate production path.
- Repeating compact on an already compacted clean single segment preserves the existing typed no-op and generation.
- Run existing merge/mutation/visibility/recovery/property suites; do not replace them with A5 happy paths.

**Explicit resource consequence:** the old compactor used a legacy encoder without the adaptive/A3 final encoded-block allocation admission. New compaction can return `IndexError::Segment(SegmentError::LimitExceeded { .. })` when its selected encoded block exceeds max_single_allocation. That tightening is prescribed; do not raise limits or fall back to legacy. Actual host reservation exhaustion is not injected. No broader acceptance equivalence is claimed for pathological over-limit legacy compactions.

Add `a5_i05_compaction_limit_failure_preserves_generation` in this same file, with this exact bounded production-path fixture:

1. A test-local schema has exactly one single Text field body, standard_folded, `FieldOptions::new(true, false, false)` (indexed, **not stored**, not columnar). Insert keys p00000..p00015, each with 1,024 alpha tokens joined by one ASCII space. Commit two segments of eight documents under default limits.
2. Verify generation2, two F segments, alpha total16. Each input term has df8, frequency total8,192, D8/F16/P57,000, compact length57,034. Each decoded posting's occurrence allocation is40,960 bytes (1,024 × size_of::<Occurrence>() at the verified layout), below65,536.
3. Drop the default writer/index; reopen through `Index::open_with_limits` on the same FsDirectory with `IndexLimits::default().with_segment_limits(SegmentLimits::default().with_max_single_allocation(65_536))`. Assert limited open, writer creation and a normal search each succeed separately, with generation2 and total16. Keep a snapshot and copy CURRENT bytes before compact.
4. The merged term has df16, frequency total16,384, D16/F32/P114,000 and11 header bytes: exact encoded length114,059. Call public compact and require `IndexError::Segment(SegmentError::LimitExceeded { limit: 65_536, requested: 114_059 })`. An earlier unrelated limit error is a failed test, not equivalent success.
5. CURRENT bytes remain identical; writer.reader and held snapshot still expose generation2/two segments/16 matches and the same per-key score bits. Drop writer/index, reopen with defaults and confirm the same committed state. No generation3 is published.

The field must remain indexed-but-not-stored: storing the repeated body could trip a different stored-block limit before the intended encoder seam. Positions occupy7,125 bytes per document under the existing token offsets; test that input-derived arithmetic, rather than accepting whatever requested value the production error returns.

For this one-field fixture, do not reuse the scoring file's `search_ok`/`request` helpers: they bind its normal four-field schema and doc_id/n projection. Add a test-local helper using `LexicalSearcher::new(snapshot, &limit_schema, &registry, SearchLimits::default())` with `Query::Term { field: "body".to_owned(), value: FieldValue::Text("alpha".to_owned()) }`, TopK16, fresh Budgets and CancellationFlag. Require total16, exact input keys, and each returned score's bits equal `frozen_scalar_bm25(1024, 16, 16, 1024, 1024.0).to_bits()`. Use this same schema-specific helper before/after failure; leave original scoring helpers unchanged.

### 11.6 I06 — Genuine legacy-plus-adaptive committed generations

**File/name:** `tests/pr07_compatibility.rs::a5_i06_legacy_adaptive_commit_reopen_and_compact`.

Reuse its actual `stage_fixture`, `open_fixture`, `append_and_reopen`, `LEGACY_DOCS`, `APPENDED_DOCS`, `FIXTURE_OBJECTS`, `expected_rust_scores`, OR oracle and search helpers.

1. Stage `fixtures/index/pr07_pre_norms_v1/index/` in an isolated temporary directory. Verify its four existing pinned objects/lengths/digests. Never regenerate them.
2. Open generation1: eight documents, two legacy segments with neither E nor F and no field norms. Pin it. Assert title:rust total4, body:rust total6, and MatchAll d1..d8 against the existing independent oracles. Save exact repeat-query score bits for this snapshot.
3. Call existing `append_and_reopen`, which inserts exactly APPENDED_DOCS and publishes generation2. Assert ten documents/three segments; classify by feature sets, not segment order: two legacy and one F/no-E with norms.
4. In the new F segment verify title:rust df2 marker7 and title:async df1 marker5. Check title:rust total6, body:rust total8, OR oracle, and all keys d1..d8,n1,n2 against the concatenated literal corpus. Existing TopK100 is sufficient. Pin generation2.
5. Capture hashes of the original generation1 manifest and both original segments. CURRENT is mutable and is excluded from the post-write immutability assertion.
6. Call public compact once. Assert generation3, documents10, segments_merged3, no_op=false. Fresh open sees one F/no-E segment with norms. Repeat independent corpus queries.
7. Query generation1 and2 pins again: each retains its own saved keys and exact bits. Do not compare scores across different corpus generations because their statistics differ.
8. Original immutable manifest/segments remain byte-identical in the temporary index. The checked-in fixture remains unchanged.

The existing compatibility oracle's tolerance is <1e-10; retain it for its cross-layout formula checks. Repeated same-snapshot checks use exact bits. The all-current I02/I03/I05 use the stronger frozen exact-bit oracle. Do not quietly weaken either policy.

### 11.7 R01 — Real RustFS, cold reader, no writer-local state

**File/name:** `tests/pr13_remote.rs::real::a5_r01_adaptive_postings_rustfs_cold_reopen`. Use the existing `#[test]` and ignored-real-service pattern.

Reuse `real_index`, unique test-prefix remote configuration, production RemoteIndex/S3ObjectStore and existing schema/document helpers. That schema has one indexed/stored Text title with standard_folded. Insert259 documents with keys `a5-000`..`a5-258`. Title for i is `"<group> alpha beta"` when i%4!=0, otherwise `"<group> alpha gamma"`; group is singleton/short/long with the same1/128/130 partition as I02. Do not change schema.

Commit, then drop the writer and the original RemoteIndex. That original handle's snapshot is the generation observed at creation; do not inspect it as if commit refreshed it. Open a fresh `RemoteIndex::open_existing(Arc::clone(&store), config.clone(), schema(), registry(), IndexLimits::default()).await`, verify generation1/one F/no-E segment and expected positional group markers5/7/3, then drop this handle and all its readers. Delete only this disposable test configuration's local workspace_root, then open_existing again from the real remote store. Inspect the cold fresh segment readers and require the same feature/mode classes. Assert:

- singleton exactly key a5-000; short keys a5-001..a5-128; long keys a5-129..a5-258;
- alpha total259; beta194; gamma65; absent0;
- phrase alpha beta exactly194 input-defined keys.

Add one local test helper using the existing LexicalSearcher search invocation with **TopK300**, fresh Budgets/cancellation, then sort returned keys for set equality. Use it for the term/phrase full sets and assert total_hits separately. Do not change global query/phrase_query helpers, whose TopK20 cannot prove full130/194-key sets.

No fake ObjectStore is substituted for this acceptance. No topology/credentials/retry-policy changes. Existing CI's rustfs job runs all ignored `pr13_remote` tests, so no workflow edit is necessary. If local pinned RustFS is unavailable, mark R01 pending and complete all independent work; final A5 acceptance still needs actual R01 execution in the pinned topology on the relevant A5 source.

### 11.8 S01 — Untimed structural report

Record actual small-fixture term payload lengths from U13 and actual complete-container section lengths from I01/I04. For like-for-like container comparisons preserve exact feature multiplicity and every non-postings section; distinguish Postings bytes, Dictionary bytes, complete segment bytes, and full index bytes. Never count target directories, executables, caches or unrelated files as index footprint.

Record the source-derived full-corpus projection in §1.3 separately, labeled **NOT MEASURED — A6 verification pending**. A deterministic arithmetic check may enumerate the logical N+1 singleton count for N10K/100K without building an index. No A5 build of the full benchmark corpus or adapter invocation is authorized. If observed small-fixture sizes disagree with the grammar, fix a proven implementation/test arithmetic defect within this design; if the grammar itself must change, STOP.

## 12. Boundaries, failure modes, cross-component impact and residual risk

### 12.1 Failure and state matrix

| Boundary / failure | Required behavior | State / cleanup / evidence |
| --- | --- | --- |
| Invalid source Posting | Original typed source error in original order | No compact output allocation before validation. U05/U15. |
| Corrupt compact framing | Typed adaptive/varint error at construction | No cursor returned, no proportional allocation. U06/U12. |
| Corrupt later posting | Same full/lean semantic error on attempted traversal | Earlier valid posting remains observable; discard failed cursor. U07. |
| Malformed final tails/sum | Ordered finish error | Do not mark finished before checks. U11. |
| Unknown required feature | UnsupportedFeature through normal container validation | No fallback; original immutable object untouched. U01/U12. |
| Missing pair/extent mismatch | Existing section/extent precedence, then adaptive agreement | No verified metadata published. U12/I01. |
| Decoded limit | Existing incremental LimitExceeded; lean charged equally | No bypass/limit increase. U09. |
| Encoded output/reservation limit | Checked typed error before or at single reservation | Normal caller propagation; no legacy fallback. U09/I05 disclosure. |
| Cancellation | Existing posting/merge boundary polling | No compact eager body work; no cursor rollback beyond original contract. U08, existing merge cancellation tests. |
| Partial I/O, timeout, remote conflict | Existing Directory/ObjectStore/writer behavior | No new retry or publication branch; inherited real/fault suites plus R01. |
| Crash during publication | Existing previous/new complete generation semantics | Lifecycle unchanged; existing recovery and RustFS crash suites mandatory. |
| Concurrent reader / held PIT | Old immutable generation remains readable | I05/I06, existing visibility suites. No new concurrency mechanism. |
| Repeated compact / retry | Existing no-op and durable-generation semantics | I05; no custom automatic retry loop. |
| A5 source changes after tests | Relevant evidence invalidated | Reexecute affected mandatory gates; record source identity. |
| Service/credential absence | Environment/harness blocker | Defer dependent remote gate; continue safe local work; never report PASS. |

No new network timeout, authentication, retry, encryption, distributed placement or vector behavior is introduced; designing those failure mechanisms is inapplicable to A5. Existing remote lifecycle tests remain relevant regression obligations because these new bytes are persisted remotely.

### 12.2 Cross-component and sibling-API matrix

| Producer / consumer | Change or preserved obligation | Evidence |
| --- | --- | --- |
| Direct legacy encoder/new | Original bytes/error contract | U05/U14, A2/A3 direct tests, I04. |
| Direct A3 encoder/new_split | Original wire/directory/errors including tiny lists | U04/U05/U14, retained A3 suite. |
| Adaptive compact encoder/new_adaptive | Frozen framing, one buffer, lazy borrowed decoding | U01–U16. |
| SegmentBuilder | F and selector for each real term | I01/I02. |
| Compactor | Same F encoder selected by live output df | I05/I06, merge/mutation/visibility/recovery regressions. |
| SegmentReader postings lookup / entry lookup | One feature-driven dispatch, same df check | U12/I01. |
| Full next/next_with/advance/advance_with | Same semantics including cached advance exception | U07/U08 and retained A3 tests. |
| Consuming into_doc_freq + lean next/next_with | Preserve ownership/progress/validation, avoid occurrence materialization | U07–U11, I02. |
| Term/prefix/generic Boolean/phrase search | Real inherited contracts, no decoder bypass | I02/I03/I05/R01, existing lexical/property tests. |
| Explicit/relevance sort, returned scores, cursors | Exact independent results and scores | I02/I03/I05, SC suite. |
| Local Index publication / mutation pointers | No format-specific bypass | I03/I05/I06, existing PR9 and mutation suites. |
| RustFS remote cold reopen | New bytes independent of writer-local cache | R01 and full hosted rustfs regression job. |
| Manifest feature propagation | Per-segment features remain independent | I05/I06 plus source review; no global F required feature. |
| Benchmark adapter/framework | No code/config/method change; compiles/tests with current core | Mandatory adapter/framework CI. No real acquisition. |

### 12.3 Residual risks and approved disposition

| Risk / property not fully established by A5 | Severity / why | Disposition and owner |
| --- | --- | --- |
| Warm-query latency and writer CPU/RSS | Material; fewer bytes and fewer temporary buffers do not establish end-to-end performance | Deferred to A6's separate design/acquisition, maintainer-owned. A5 cannot claim preservation or speedup. |
| Actual 10K/100K complete-index sizes | Model is exact only under stated corpus/build assumptions | A6 measures and reconciles real index bytes; A5 labels projections. |
| Complete committed generation containing both E and F segments | Bounded integration gap: no genuine complete E fixture exists in inspected fixture set; ad hoc replacement risks state-pointer inconsistency | A5 accepts real legacy+F lifecycle plus explicit E container/decoder coverage as its bounded implementation gate. **A6 must explicitly design and execute genuine E+F append/reopen/compaction compatibility before A-series qualification is accepted.** Do not claim it executed here. |
| Old executable rejecting F | Source-derived feature-negotiation behavior; current tests cannot simulate an old binary merely by asserting current support | Report as source-derived; no old-binary run claimed. Unknown-version tests remain mandatory. |
| Real allocator exhaustion after bounded reservation | Not safely reproducible as a deterministic normal test | Review fallible reservation/error mapping; test arithmetic/admission; no OOM injection. Accepted limited test gap. |
| 32-bit host behavior | Current CI hosts are64-bit | Checked usize conversions plus bounded arithmetic tests; no new cross-platform CI. Disclose. |
| Faults in unchanged publication protocols | No new crash mechanism is designed | Existing local and hosted remote failure/recovery suites remain mandatory; no claim that codec unit coverage proves durability. |

Any additional material residual risk is not preaccepted: use D40 and STOP affected acceptance. The executing agent cannot approve its own residual-risk waiver.

## 13. Ordered execution sequence

Stages are checkpoints for evidence, not repeated permission boundaries. Use §15 at every exception and continue automatically after successful checks.

### P0 — Establish source, worktree, protections and baseline evidence

1. Inspect repository origin, branch, HEAD, worktree status and unmerged index entries before any write. Do not reset, stash, clean or discard user work. The pinned docs/TESTING.md already contains committed conflict-marker text near its beginning; record this known documentation defect and continue without editing it when its blob matches §2.1. It is not an unmerged Git index. Actual `git ls-files -u` entries still trigger D05; unexpected new marker text is not covered by this exception.
2. Fetch origin using the existing authenticated repository workflow. Verify inspected base `5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d` exists as a commit and is an ancestor of current origin/main. Verify A4 merge history. If the source has diverged, use D02/D03.
3. Start a clean dedicated branch `dev/perf06-a5-adaptive-postings` from the verified latest main. Fast-forward only if needed; use an isolated worktree when main is in use. If this branch already exists, inspect and classify its work rather than overwriting/reimplementing it (D04).
4. Verify the code anchors and source-sensitive inputs against the planning base. The following diff must be empty for the doc-only drift rule:

```bash
git diff --exit-code 5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d origin/main -- \
  crates Cargo.toml Cargo.lock rust-toolchain.toml .github/workflows tests \
  benchmarks/quervant_bench benchmarks/pr15d AGENTS.md \
  docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md docs/TESTING.md \
  docs/ARCHITECTURE.md docs/PERF_OPTIMIZATION_ROADMAP.md \
  docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md \
  docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md
```

5. Repeat the bounded producer/feature audit:

```bash
rg -n 'encode_(split_)?postings_block|FEATURE_SPLIT_POSTINGS|FEATURE_ADAPTIVE_POSTINGS' \
  crates benchmarks --glob '*.rs'
git ls-files -u
git status --short
git rev-parse HEAD
git rev-parse origin/main
rustc -Vv
cargo -V
```

Expected production consumers of the old encoders are only segment/build.rs and index/merge.rs. Tests and encoder definitions are expected matches. An additional production producer is D08, not an invitation to wire it speculatively.

6. Record hashes/list of all protected benchmark results/configurations and A1–A4 artifacts. Record the legacy fixture/golden Git blob identities. These must remain unchanged throughout A5.
7. Create the new A5 report with status `IN_PROGRESS`, base SHA, environment/toolchain, planned gate ledger and empty decision register. Copy this approved plan into its repository artifact path without redesign.
8. Execute the targeted baseline commands in §14.1 once on the unmodified source; capture outputs/counts/exit codes. Do not run the full QA matrix twice simply because this is a new stage. Classify failures using §16 before calling them preexisting. A baseline feature test that cannot yet compile is not baseline health evidence.

### P1 — Complete the adversarial pre-implementation gate

Map INV01–INV13 to actual named tests. Evaluate every challenge in §9 and record expected error/phase/state. Freeze the source-facing interfaces, wire values, file list, resource consequence and residual-risk dispositions exactly as written. Add the initial red tests and independent literals.

If source facts disagree with the plan, stop affected implementation and record the smallest amendment needed. Do not treat this gate as permission to design an alternative.

### P2 — Format constants and primitive support

Add F/1 support, fixed compact constants and bounded error context in the specified files. Preserve all old IDs. Add fallible ByteWriter construction, its test-only capacity accessor, CompactLengths/PostingsSource extension and the compact-total helper. Make no producer switch until encoder and reader support exist.

Add U01/U02/U16 interfaces/fixtures. Keep changes compiling as the corresponding code lands; no separate merged format-only PR or partially supported shipped format.

### P3 — Shared source validation and adaptive encoder

Apply the const specialization, fused width accounting, original validation ordering, lazy source error factory and one-buffer algorithm in §6. Update existing legacy/A3 calls to false, compact to true, and the first long branch exactly as prescribed.

Add test-only observations. Run U02–U05/U09/U13–U16 and old A3/legacy encoder tests. Inspect successful compact source for all forbidden allocations/copies/traversals. Record actual buffer/width/validator counts and exact sizes.

Do not continue to claim encoder complete if only round trips pass but byte literals or capacity witnesses fail.

### P4 — Borrowed compact reader in the existing decoder

Add Compact state, new_adaptive, required ordered geometry checks, shared delta match, frequency/position arms, compact frequency-sum/final checks and lazy semantic error factories. Preserve full/lean public API and old Split/Legacy behavior.

Execute U04/U06–U12/U14 and A2/A3 full suites. Specifically check incremental entry limits, first-valid/second-corrupt behavior, cancellation versus EOF, consuming conversion and old cached-advance exception. No separate lean decoder is allowed.

### P5 — Wire both producers and one feature-driven reader dispatch

Update SegmentBuilder, compaction's two exact sites, and SegmentReader dispatch/feature validation. Apply the two lazy extent-error factories. Run real-container tests and narrowly migrate builder-dependent historical tests per §10.4.

Audit the complete diff: only five allowed production files; both producers use the new encoder; no E added to new output; no F in the global manifest; old encoders remain callable for fixtures. New valid bytes must flow through existing publication and query APIs without special cases.

### P6 — Execute local and remote vertical slices

Implement/run I01–I06 and S01, including the separate-process child, real compact limit failure and previous-generation availability. Run applicable existing scoring, compatibility, merge, mutation, visibility, recovery and property regressions.

Implement R01 and execute it against an already available authorized pinned RustFS test topology, or obtain its execution from normal hosted PR CI. An unavailable external service does not stop local work; G5 remains blocked until real evidence exists.

Do not invent a complete E+F fixture, start A6 acquisition, or use a fake provider to close R01.

### P7 — Final QA, evidence and adversarial review

Run the final repository gates in §14 after the last source/test edit. Resolve implementation defects within this design. Record all failures and exact evidence of fixes. Once sufficiently verified, do not add optional stress/benchmark campaigns.

Perform an adversarial self-review against INV01–INV13: state one plausible wrong implementation for each high-risk invariant and the actual evidence excluding it. Review source for uninstrumented waste, eager errors, false green test filters, changed validation timing and historical evidence edits. Fill the residual-risk table without new self-approved waivers.

Reconcile docs/status only with actual gate outcomes. Commit source/tests separately from the final evidence-only closeout when useful for clean provenance; no artificial requirement for one commit per phase.

### P8 — Deliver the separate draft PR and precise status

Push normally to the designated A5 branch; no force push or main rewrite. Create/update a separate draft PR using §18's text. Use a body file for multiline CLI descriptions. Record head/source/tree identity, remote verification, CI run URLs/check states, tested-source identity and every open gate.

Do not poll CI in an unbounded loop or rerun acquisitions. Continue normal CI observation while there is useful authorized work; if infrastructure remains pending/unavailable, provide the complete reviewable draft with `VERIFICATION_BLOCKED` and exact next evidence needed. No routine reconfirmation is required for the draft push/PR described in §0.

Check disk usage and follow D35 for safe cleanup. Finish with an evidence-based status report. Independent reviewer/maintainer acceptance is G9 and does not authorize automatic merge or A6 timing.

## 14. Authoritative commands, topology and gates

Run each command from the repository root, capture real exit status, and record the active toolchain. For ordinary local gates use Rust1.98.1 to match the inspected rust CI job; the explicit `+1.98.1` commands below avoid floating stable ambiguity. The MSRV remains1.85.0. Install missing prescribed components/tools only through the existing repository/environment workflow; never change Cargo dependencies or toolchain files to work around failures.

### 14.1 Targeted baseline commands

Run these before source edits. They cover the touched codec and compaction seams without duplicating full final QA:

```bash
cargo +1.98.1 test -p quervant-core --lib a2_
cargo +1.98.1 test -p quervant-core --lib a3_
cargo +1.98.1 test -p quervant-core --test segment_codec
cargo +1.98.1 test -p quervant-core --test segment_golden
cargo +1.98.1 test -p quervant-core --test pr07_compatibility
cargo +1.98.1 test -p quervant-core --test pr09_merge
cargo +1.98.1 test -p quervant-core --test pr15i_d2a_scoring_contract
```

A passing whole later suite can cover a targeted regression once source identity is established; do not rerun the same targeted suite solely to create a second green log. Targeted red/green runs are still needed where they resolve a specific changed contract.

### 14.2 Feature and adjacent regression execution

```bash
cargo +1.98.1 test -p quervant-core --lib a5_ -- --nocapture
cargo +1.98.1 test -p quervant-core --test segment_codec
cargo +1.98.1 test -p quervant-core --test segment_golden
cargo +1.98.1 test -p quervant-core --test pr07_compatibility
cargo +1.98.1 test -p quervant-core --test pr07_properties
cargo +1.98.1 test -p quervant-core --test pr08_integration
cargo +1.98.1 test -p quervant-core --test pr09_merge
cargo +1.98.1 test -p quervant-core --test pr09_mutations
cargo +1.98.1 test -p quervant-core --test pr09_visibility
cargo +1.98.1 test -p quervant-core --test pr09_recovery
cargo +1.98.1 test -p quervant-core --test pr09_properties
cargo +1.98.1 test -p quervant-core --test pr15i_d2a_scoring_contract
cargo +1.98.1 test -p quervant-core --test pr13_remote
```

The default pr13_remote command exercises its ordinary deterministic/regression tests; ignored real tests require §14.4. The scoring suite's normal parent invokes the exact ignored child itself. A skipped test is not acceptance.

### 14.3 Mandatory final local repository QA

These are mandatory local commands; CI success does not replace them. Do not run simultaneous Cargo gates that contend for the same target directory or mix coverage instrumentation with ordinary builds.

```bash
cargo +1.98.1 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
git diff --check
```

Coverage scope is workspace production Rust with the repository's existing exclusions only; require ≥85% lines in both prescribed default and all-feature invocations. Tests must exercise real production code. No excluding new codec branches, raising tolerances, disabling tests, altering lints or reducing the floor.

The benchmark command is compile-only. Inherited repository test invocations may execute their normal test-mode targets; this is not permission to invoke full Criterion measurements or claim performance results.

### 14.4 Real RustFS topology and invocation

Use the existing authoritative RustFS CI topology:

| Item | Inspected configuration |
| --- | --- |
| Service image | `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Endpoint | `http://127.0.0.1:9000` |
| Region | `us-east-1` |
| Disposable CI bucket | `quervant-pr13-ci` |
| Prefixes | Existing test helper generates per-run unique prefixes. |
| Adapter | Production S3ObjectStore with core's existing s3 feature. |
| Credentials | Existing fixture/environment inputs; do not copy secrets into reports. |
| Concurrency | Existing real suite runs with one test thread. |
| Repetitions | R01 once per verified candidate; inherited CI retains its existing3x/10x mutation/race checks. No added sampling campaign. |

When the authorized local topology is already available, the exact targeted command is:

```bash
cargo +1.98.1 test -p quervant-core --all-features --test pr13_remote \
  real::a5_r01_adaptive_postings_rustfs_cold_reopen \
  -- --ignored --exact --test-threads=1
```

The hosted job runs this encompassing target:

```bash
cargo test -p quervant-core --all-features --test pr13_remote \
  -- --ignored --test-threads=1
```

Normal hosted CI owns its pinned service startup and broader existing remote conformance, oracle, fault-proxy/crash and mutation suites. Do not independently start another container, proxy, service or cloud bucket just to fill a checklist. If an already authorized local service is absent, D29 defers its local execution; actual hosted execution can satisfy the real-provider gate. Absence of local service is not an A5 design failure.

### 14.5 CI and source identity

All five current required CI jobs must pass on source that actually contains the final implementation/tests:

- `rust`;
- `msrv`;
- `rustfs`;
- `benchmark-adapter-contract`;
- `python-benchmark-framework`.

Retain their current workflow. Adapter/framework jobs perform their existing synthetic/unit/compile/configuration checks; no real benchmark is needed.

Record actual workflow run ID, checked head/merge SHA, corresponding PR head, conclusion and URL for each. A4's green or pending jobs do not qualify A5. A queued job, a cancelled job or an ignored new test is not PASS.

A later report-only commit can reuse local source-test evidence **only** after an empty diff proves no changes under crates, Cargo manifests/lock, toolchain, workflows, tests, benchmark sources/adapters or other tested inputs. Record both tested SHA and final report SHA. Report final CI as actually observed; do not relabel an earlier run as a run on the new head. No full local QA rerun is required solely to embed its own evidence report.

### 14.6 Gate ledger

| Gate | Evidence required | Owner / closing rule |
| --- | --- | --- |
| G0 — Source/preflight | Verified base/drift, clean isolated branch, producer/feature scan, protected hashes, baseline outcomes | Agent; no unresolved source mismatch. |
| G1 — Pre-implementation correctness | INV trace, all §9 challenges, no unapproved architectural ambiguity | Agent; matrix decisions recorded before production edits. |
| G2 — Implementation and cost structure | Exact wire/API, five-file production scope, both producers, one-buffer/shared-decoder source audit | Agent completes audit; independent confirmation belongs to G9. No forbidden extra work or allocations. |
| G3 — Unit/codec | U01–U16 and preserved old codec tests actually pass | Agent; real names/counts/output recorded. |
| G4 — Local boundaries | I01–I06, S01 and adjacent regression suites pass, including child process and real compact limit failure | Agent; real FsDirectory/public paths. |
| G5 — Real remote boundary | R01 executes and passes on pinned actual RustFS with the final relevant source | Local authorized topology or hosted rustfs evidence. |
| G6 — Local QA | Every §14.3 command passes; coverage ≥85% both forms | Agent; no CI substitution. |
| G7 — CI | All five jobs pass with exact relevant provenance | Hosted CI; no queued-as-pass. |
| G8 — Evidence/docs/audit | Complete truthful report, final adversarial review, protected evidence unchanged, bounded residuals and A6 handoff | Agent; no new self-approved waiver. |
| G9 — Independent acceptance | Independent code/design-conformance review and maintainer decision | Human maintainer/reviewer; agent cannot self-approve or merge. |

G0–G8 PASS permits **READY_FOR_INDEPENDENT_REVIEW**. A missing mandatory gate means **VERIFICATION_BLOCKED** or **IMPLEMENTATION_BLOCKED**, not DONE. G9 is required for **ACCEPTED — IMPLEMENTATION**. None of these statuses means A6 performance qualification has passed.

## 15. Preauthorized Architectural Decisions and Exception-Handling Matrix

### 15.1 How to use this matrix

**AUTO-RESOLVE:** verify the exact preconditions, perform only the listed action, record proof, continue.  
**DEFER AND CONTINUE:** retain the blocker and dependent gates; complete all independent authorized work without assuming a missing result or architecture.  
**HARD STOP:** stop affected work immediately. Continue only demonstrably independent safe tasks. An unlisted condition is D40, regardless of how reasonable a proposed workaround appears.

If multiple rows apply, the most restrictive governs. An AUTO-RESOLVE row never overrides an invariant, permits an unlisted file edit, waives QA, authorizes a benchmark or changes a threshold. A maintainer must approve a written plan amendment for an architectural deviation; the executing agent cannot approve it.

Every decision-register entry includes rule ID, timestamp, source SHA/path/symbol, observed trigger, category, action, prohibited workaround avoided, evidence path/command, affected tasks/gates, owner and resolution. Do not stop merely to announce a passing checkpoint.

### 15.2 Source, branch and producer decisions

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Required evidence | Affected work/gates | Escalation owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | Clean isolated checkout; local base is an ancestor of verified origin/main; frozen-input diff empty | AUTO-RESOLVE | Fast-forward or create dedicated worktree/branch at origin/main; record base; continue | Reset/rebase main, force push, discard user work | Status, ancestry, exact SHAs and empty protected diff | P0 / G0 | Agent; maintainer only if conditions fail |
| D02 | New main commits change only paths outside §13's frozen inputs and protected evidence; no conflicting A5 work | AUTO-RESOLVE | Use latest main; retain planning-base reference and prove relevant identity | Ignore a nonempty frozen-input diff or assume code equivalence | Diff path list, exact base, hash checks | P0 / G0 | Agent |
| D03 | Code/API/guide/architecture/roadmap frozen input changed, pinned ancestor missing or A4 merge unverified | HARD STOP | Preserve checkout; produce exact delta and required plan amendment; continue read-only independent audit | Rebase design by intuition; edit old source to match plan | Diff, symbol, invariant and impact | Dependent P1–P8 / G0 onward | Maintainer |
| D04 | A5 branch already contains work | AUTO-RESOLVE only if every edit conforms to this plan and baseline is verified | Classify DONE+VERIFIED / DONE NOT VERIFIED / PARTIAL / NOT STARTED / BLOCKED; preserve verified work; execute remaining steps | Overwrite/reimplement completed work; adopt unreviewed deviations | Branch diff, source/test evidence and per-step status | P0–P8 / applicable gates | Agent; deviation becomes D03/D40 |
| D05 | Dirty user work or actual `git ls-files -u` entries; the known committed TESTING.md text markers from P0 are not this trigger | HARD STOP affected checkout | Leave it intact; use an independent clean worktree only if no conflicting branch/state is touched. Record/continue past the pinned documentation markers without editing them | Stash/reset/clean, resolve unknown user's merge, opportunistically repair pinned policy text | Status/index listing, pinned blob and isolation proof | P0 / G0 | Maintainer for conflicting work |
| D06 | Compile/rustfmt/clippy issue confined to prescribed code with unchanged contract | AUTO-RESOLVE | Correct syntax, imports, lifetimes, local names, formatting or equivalent safe borrow form; rerun affected gate | New API/layout/trait, suppression, unsafe, behavior or error-order change | Diagnostic and bounded diff, passing check | P2–P7 / G2,G3,G6 | Agent |
| D07 | F ID/version already occupied, module API differs, or grammar conflicts with actual source | HARD STOP | Report collision/interface evidence; request amendment | Choose next free ID/version or another wire grammar | Exact source and contract conflict | P2–P5 / G0–G4 | Maintainer |
| D08 | Producer scan finds a production encoder caller beyond build.rs and merge.rs | HARD STOP affected integration | Identify caller/data flow and required scope decision; continue independent codec tests | Wire it automatically or leave an undocumented producer inconsistency | rg output and source call site | P5 / G2,G4 | Maintainer |

### 15.3 Implementation, performance and compatibility decisions

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Required evidence | Affected work/gates | Escalation owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D09 | Named builder-dependent A3 test fails solely because current writer now uses F | AUTO-RESOLVE | Apply exact historical fixture migration in §10.4; add A5 counterpart | Replace all E assertions with F; accept either family vacuously | Old/new fixture provenance, retained A3 assertions and passing tests | P5 / G3,G4 | Agent |
| D10 | Only `p8_t42` closed feature allowlist/current-builder assertion needs F | AUTO-RESOLVE | Add F support entry; assert F present/E absent for current output; keep old E recognized | Change other PR8 semantics/goldens or loosen list to all IDs | Focused diff and full pr08_integration result | P5 / G4 | Agent |
| D11 | Rebuilt test container is four bytes larger because baseline feature was copied twice | AUTO-RESOLVE | Skip exactly one constructor-supplied baseline tuple; preserve remaining multiplicity | Deduplicate all tuples or fix production unrelated feature multiplicity | Before/after tuple lists, section/total byte accounting | Test helpers / G3,G4,S01 | Agent |
| D12 | Corruption test returns digest error before intended inner decoder error | AUTO-RESOLVE | Rebuild outer checksums/lengths using existing ContainerBuilder while retaining intended inner defect | Disable digest checks or accept wrong error as sufficient | Valid envelope proof and exact inner-error assertion | U06/U07/U12,I01 / G3,G4 | Agent |
| D13 | Newly implemented code returns wrong prescribed error/order, skips validation or changes cancellation | AUTO-RESOLVE if defect is confined to approved algorithm | Fix code within frozen contract and allowlist; add/retain the exact counterexample | Change expected contract, defer required validation, skip positions | Reproduction, bounded fix and failed/passed logs | P3–P7 / G2–G4 | Agent; contract contradiction → D14 |
| D14 | Correctness requires changing the approved wire, lazy timing, error precedence, budget, public API or recovery contract | HARD STOP | Document contradiction and smallest amendment | Pick a “reasonable” semantics or weaken tests | Exact source/input/error sequence and violated invariant | Dependent implementation/acceptance | Maintainer |
| D15 | Compact witness shows duplicate validation, extra width traversal, extra stream buffers or capacity growth | AUTO-RESOLVE within prescribed one-buffer design | Remove the implementation defect; keep exact allocation/width/endpoints contract | Accept waste, add profiling first, remove witness or change threshold | Counts, ownership audit, fixed tests | P3–P7 / G2,G3 | Agent |
| D16 | Long adaptive output differs from direct A3, or compact counters are nonzero | AUTO-RESOLVE within direct delegation rule | Restore first-branch delegation and false validation specialization | New long format, altered directory, second validation, byte-equivalent reimplementation | Byte comparison and exact counter values | P3/P4 / G2,G3 | Agent |
| D17 | Proposed optimization needs size-based selection, other cutoff, block skipping, bit packing, fewer validations, or runtime switch | HARD STOP | Record separately as future idea; stop that edit | Benchmark alternatives or choose a variant in A5 | Proposed delta and affected invariants | Affected P2–P6 / G2 | Maintainer |
| D18 | Small-fixture size differs from §10.2 or endpoint arithmetic | AUTO-RESOLVE only for a proven implementation/test transcription defect against the unchanged grammar and literals | Correct the defect and verify all independent literals/formulas | Change frozen expected table/grammar to match output; tune corpus/schema | Independent field-by-field arithmetic and diff | P3/P6 / G3,S01 | Agent; plan contradiction → D40 |
| D19 | Exact I05 over-limit compaction returns prescribed114,059-byte request and leaves generation2 intact | AUTO-RESOLVE | Record expected admission failure as passing negative test; continue | Raise limit, fallback to legacy or call expected rejection a regression | Exact error, unchanged CURRENT/old generation/results | I05 / G4 | Agent |
| D20 | I05 resource fixture fails before intended encoder seam or publishes after error | HARD STOP for that acceptance pending diagnosis | Preserve reproduction; determine proven code defect versus source/design mismatch; unrelated tests continue | Accept any LimitExceeded, retune fixture/limit until it passes | First failing stage, actual error/state, source-level explanation | I05 / G4,G8 | Maintainer for amendment; approved-code defect uses D13 |
| D21 | Compact constructor contains owned buffers, body predecode, eager error strings or eager decoded-entry charging | AUTO-RESOLVE under §6/§7 | Remove those implementation defects using borrowed state/lazy factories/incremental checks | Cache predecoded postings; bypass original budgets or cancellation | Source diff, U07/U09/U10/U15 | P4/P5 / G2,G3 | Agent |
| D22 | Mandatory new or existing test fails after a source change | AUTO-RESOLVE diagnosis only | Preserve failure; apply §16 classification; fix a proven in-scope defect and rerun affected gates | Declare “unrelated” without evidence or delete/ignore test | Full log, failing input/source, classification proof | P3–P7 / affected gates | Agent; out-of-scope defect D26 |

### 15.4 Evidence, environment and delivery decisions

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Required evidence | Affected work/gates | Escalation owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D23 | Same deterministic required-gate failure reproduced on relevant base with same command/toolchain/topology | DEFER AND CONTINUE | Mark preexisting failure, keep gate blocked, finish independent work and report narrow remediation owner | Waive gate, hide baseline failure or broaden production scope | Baseline/current logs and identity/environment match | Relevant G3–G7 remains blocked | Maintainer / owner of existing defect |
| D24 | Preserved identical-input runs demonstrate nondeterminism | DEFER AND CONTINUE | Record failed and successful attempts, quarantine only the decision, investigate boundedly; gate unresolved | Retry until green, suppress test, label flaky without evidence | All attempts and unchanged input/source proof | Relevant gate remains blocked | Maintainer |
| D25 | Coverage below85% or an allowed new error branch untested | AUTO-RESOLVE | Add meaningful positive/negative tests within allowlist; rerun coverage and affected QA | Exclusions, lowered floor, artificial test-only production branch | Coverage report, invariant traced test and result | P7 / G3,G6 | Agent |
| D26 | Needed production/test edit outside §3 allowlist | HARD STOP affected fix | Prepare smallest justified amendment with source/test evidence | Silent file-list expansion, unrelated refactor or broad cleanup | Proposed file/symbol and reason no allowed solution suffices | Affected gate | Maintainer |
| D27 | Required pinned toolchain/tool, network dependency or local harness unavailable | DEFER AND CONTINUE | Use established installation workflow for specified tool; if blocked, finish independent work and report exact missing dependency | Dependency/version changes, fabricated output, skip-as-pass | Command/error/environment and blocked gate | G3–G7 as applicable | Environment owner / maintainer |
| D28 | Pinned disposable RustFS test topology already authorized and healthy | AUTO-RESOLVE | Execute exact R01 command once and normal required suites | Change credentials/bucket/retry/topology or treat fake as provider | Image/topology/source and test log | P6 / G5 | Agent |
| D29 | Local pinned RustFS absent/unhealthy or credentials unavailable | DEFER AND CONTINUE | Complete test/code/local QA; use normal hosted rustfs evidence when available; mark G5 pending | Start an unapproved new service/provider or abandon all local work | Environment observation and hosted run status | P6 / G5 | Environment owner / maintainer |
| D30 | Remote push/PR access or CI observation unavailable; CI pending/cancelled/failing | DEFER AND CONTINUE | Retain complete local commits/PR text/evidence, finish independent gates, report actual status | Invent remote SHA/check PASS, repeatedly trigger runs to obtain green | Local head, attempted operation, actual CI/run state | P8 / G5,G7,delivery | Repository/environment owner |
| D31 | Only docs/report changed since tested source; protected tested-input diff is empty | AUTO-RESOLVE | Reuse local QA with both SHAs and identity proof; run doc/diff checks; describe actual final CI separately | Claim old CI ran on final head or rerun all QA solely for self-referential report SHA | Empty scoped diff, tested/final SHAs | P7/P8 / G6–G8 | Agent |
| D32 | Any source/test/Cargo/workflow change after final QA | AUTO-RESOLVE | Invalidate affected evidence and rerun mandatory relevant local/CI gates; production codec changes require full final Rust QA again | Carry stale PASS forward or skip coverage after code change | Exact delta, revised gate ledger/logs | P7/P8 / G2–G8 | Agent |
| D33 | Protected A4 result/config/report or golden fixture changed unexpectedly | HARD STOP affected write/publication | Preserve diagnostic diff, restore only proven agent-created unintended edit from pinned bytes, investigate; rerun integrity checks | Overwrite evidence silently, delete unfavorable attempt, reset unrelated user work | Before/after hashes, causative diff, restoration proof | G0,G8 and delivery | Maintainer if provenance uncertain |
| D34 | Old registers still say “no implementation” or A4 all-target pass is inferred from merge | AUTO-RESOLVE | Append current-status amendment per §17; record user retention/merge separately from original measured disposition | Rewrite A4 target result, claim per-stage attribution or change historical authorizations | Links to merge/evidence and new bounded status text | P7 / G8 | Agent |
| D35 | Disk usage≥60% and AGENTS cleanup would require broad root-target purge/container reset with protected state not proven safe | DEFER AND CONTINUE housekeeping | Record usage; remove only this task's verified disposable test directories through their normal cleanup; preserve evidence/caches; report remaining cleanup requirement | Blind global purge, Podman reset, removal of benchmark caches/results/user data | Usage and exact ownership/scope proof | Housekeeping; resource-blocked QA if disk exhausted | Environment owner / maintainer |
| D36 | Approved plan executed, branch clean/verified, ordinary push and separate draft PR possible | AUTO-RESOLVE | Commit/push normally and create/update A5 draft with complete evidence; continue CI observation | Force push, merge, deploy, promote B1 or send unrelated messages | Local/remote SHAs, PR URL and draft state | P8 / delivery | Agent; merge remains maintainer |
| D37 | Request/temptation to run timing, profiling, new benchmark config/result or full-corpus build in A5 | HARD STOP affected action | Preserve A5 scope; prepare A6 handoff only | Reuse A4 UUID/results, rerun qualification, infer permission from cargo bench --no-run | Proposed action and explicit scope boundary | A6-dependent work only | Maintainer through separate A6 plan/authorization |
| D38 | Optional optimization or additional stress experiment has no remaining concrete acceptance risk | AUTO-RESOLVE | Stop optional work and complete evidence/delivery | Expand tests/profiling indefinitely or keep optimizing after prescribed gates pass | Gate ledger and no unresolved concrete question | P7/P8 | Agent |
| D39 | Complete E+F committed fixture is absent exactly as documented; legacy+F and explicit E gates pass | AUTO-RESOLVE bounded acceptance only | Record §12.3 limitation and mandatory A6 compatibility action; continue A5 review | Fabricate fixture, rewrite state pointers, claim E+F lifecycle was tested | Actual fixture inventory, passed separate gates, explicit handoff | G8; A6 acceptance dependency | Agent records; A6 maintainer owns follow-up |
| D40 | Any unexpected case not precisely covered, conflicting plan clauses, or new material residual risk | HARD STOP affected work | Freeze affected action/acceptance; report concrete source/input, invariant, options and smallest requested amendment; continue only provably independent work | Improvise architecture, broaden an AUTO rule, silently waive a gate | Reproduction, dependency map, unresolved decision | All affected steps/gates | Maintainer |

## 16. Failure classification and execution report

### 16.1 Classify before declaring a failure unrelated

| Classification | Minimum proof | Required disposition |
| --- | --- | --- |
| Introduced regression | Previously passing behavior fails on changed source with a relevant causal diff/reproduction | Fix within approved scope and rerun required gate; otherwise STOP affected work. |
| Feature implementation defect | New behavior violates a frozen invariant/literal/boundary | Correct implementation; retain regression case. |
| Deterministic preexisting failure | Same failure on relevant baseline under same command, toolchain and topology, or equivalent immutable evidence | Keep failing gate blocked; report owner; continue independent work. |
| Nondeterministic/flaky failure | Unchanged source/input/environment produces both outcomes, with all attempts retained | Do not treat latest pass as resolution; report open gate and investigate within scope. |
| Environment/harness failure | Concrete missing service/tool/resource/credential or harness failure precedes meaningful test execution | Fix an authorized environment issue or defer gate; never claim test passed. |

For a failed gate, first preserve command, source identity, stdout/stderr, exit code and first failing assertion. A single bounded diagnostic repeat of the exact command, and a same-command baseline reproduction in an isolated checkout, are permitted when necessary to classify it. They are diagnostic attempts and all outcomes remain in the report. This is not an automatic retry-to-green policy. A code fix authorizes rerunning the affected gate normally.

Do not run destructive repository cleanup to reproduce a baseline. Use an isolated baseline worktree/target path with no user edits or benchmark-artifact modification.

### 16.2 Required report contents

The execution report is the complete review record, organized as follows:

1. **Disposition:** implementation status, G0–G9 table, independent-review state, A6 pending, B1 blocked; no unsupported DONE.
2. **Authority and source:** approved plan identity, planning base, actual execution base, branch/head, protected source differences, toolchain and host.
3. **Reconciliation:** A1–A4 retained/merged facts, A4 targets-not-met evidence, existing A5 work classification if resuming.
4. **Preflight and adversarial gate:** producer scan, feature namespace, INV trace, concrete counterexamples and matrix decisions.
5. **Implementation:** exact five production files, format/API summary, compaction integration and intentional admission tightening.
6. **Performance structure:** validator/width/output counts, capacity endpoints, no scratch buffers, shared decoding, lazy error factories, constructor ownership audit. Label structural evidence, not latency measurement.
7. **Unit and compatibility results:** actual test names/counts, all hand bytes/lengths, malformed inputs/errors, limits/cancellation/full/lean, historical fixtures.
8. **Local vertical slices:** real source-input key/score expectations, fresh-process child result, compact boundary and limit-failure state, legacy+F generations and PIT.
9. **Remote results:** exact R01 environment/source/command/result and hosted regression provenance or explicit BLOCKED.
10. **Structural sizes:** exact measured fixture bytes and accounting, then separately labeled full-corpus projections.
11. **Final QA:** each command/source/environment/exit/result, default/all-feature coverage percentages and reports, CI run/checked source details.
12. **Failures and decisions:** every failed/diagnostic attempt, classification proof, applied matrix rule, outstanding owner/gate.
13. **Final adversarial review:** plausible remaining violations and evidence; residual-risk dispositions including unexecuted genuine E+F lifecycle.
14. **Publication and integrity:** local/remote SHAs, draft PR URL, protected-file hash/diff proof, docs-only identity proof if applicable.
15. **A6 handoff:** exact new accepted candidate source when known, required E+F lifecycle test, expected size model, unchanged A4 evidence, performance questions still unmeasured.

Keep logs in the task's existing execution log location and reference durable CI links where available. Record essential outputs/results in the report itself so it remains reviewable when local transient logs disappear. Do not commit large build logs, raw index directories, credentials, generated benchmark files or unrelated artifacts.

### 16.3 Evidence categories must remain distinct

- **Baseline evidence** establishes initial health on the actual base.
- **Regression evidence** establishes retained behavior on final relevant source.
- **Feature acceptance evidence** executes the new cases and intended production boundary.
- **Structural evidence** proves byte/cost/ownership properties, not timing.
- **Source-derived inference** includes projected full-index sizes and old-binary feature rejection unless actually executed.
- **Unexecuted/pending evidence** remains visibly pending.

An integration test's existence or compilation is not execution. A zero-match test filter is not execution. A whole suite passing without running ignored R01 is not real-provider evidence.

## 17. Documentation and status updates

### 17.1 Exact architecture documentation delta

In the existing segment/postings format discussion of `docs/ARCHITECTURE.md`, document:

- F/1 adaptive family, singleton4/5, short6/7, existing long2/3 and cutoff128;
- canonical varint header grammar and exact stream boundaries;
- new segments and ordinary compaction emit F; legacy and E remain readable;
- Keyword postings retain occurrences, exactly as current production input creates them;
- feature-based selection, E/F exclusion within one segment, mixed per-segment family support;
- borrowed lazy shared full/lean decoder and preserved validation/budget/cancellation;
- one-buffer compact encoding and strict allocation admission;
- no skipping, runtime tuning, migration rewrite, or measured speed claim.

Keep the documentation about the broader storage architecture unchanged. Link this plan/report for detailed evidence instead of copying every test into architecture prose.

### 17.2 Roadmap/register amendment text and boundaries

In the relevant PERF-06 sections, add a current-status amendment that states:

> A1–A3 remain retained. A4 PR #123 is merged; its complete second paired campaign met two of four primary targets and all guards, with no lane classified as regressed. The measured targets-not-met disposition remains historical evidence. A5 addresses short-list postings metadata and correctness/structural footprint. A6 is a separately planned consolidated compatibility/storage/warm-performance qualification before B1. No A6 acquisition is authorized by A5.

Add A5/A6 rows and update the dependency arrow exactly as §1.2. Preserve original opening documents' history by labeling it historical; do not silently rewrite “four original stages” as if six had always been authorized.

Status vocabulary:

| Actual condition | Permitted label | Forbidden implication |
| --- | --- | --- |
| Work started, gates incomplete | `IN_PROGRESS` | Tests/CI passed or accepted. |
| Implementation done, required gate unavailable/failing | `IMPLEMENTED — VERIFICATION_BLOCKED` | DONE because code compiles. |
| G0–G8 pass, independent review pending | `READY_FOR_INDEPENDENT_REVIEW` | Merged, accepted, or performance qualified. |
| G9 maintainer acceptance recorded | `ACCEPTED — IMPLEMENTATION`; DONE only for A5's implementation scope | A6 passed or B1 unblocked automatically. |
| A6 future work | `PLANNED — SEPARATE DESIGN/ACQUISITION REQUIRED` | An acquisition is authorized or has occurred. |

No edits to `PERF06A4_EXECUTION_REPORT.md`, A4 plans, acquisition JSON, result statuses, original thresholds, recorded confidence intervals, or earlier rejected experiment dispositions.

### 17.3 Exact A6 handoff; no design delegated to the A5 coder

The A5 report must hand off these unanswered questions without deciding their measurement protocol:

1. Does the actual frozen benchmark corpus produce the predicted bytes at the accepted A5 source?
2. What are actual commit/reopen diagnostics and memory costs under a separately defined measurement?
3. Does cumulative A1–A3+A5 retain warm-query improvements and guardrails relative to an explicitly selected, comparable source?
4. Does a **genuine A3-produced complete E index**, appended/compacted by A5, pass native and required remote reopen/PIT/state-pointer correctness?
5. What is the maintainer's resulting baseline/adoption decision before B1?

A6's author must inspect then-current main and define source pins, corpus/schema, result identity, performance acceptance criteria, stability/oracles, comparison methodology and acquisition count before running anything. A5's coding agent must not pick those details, retune the5% A4 target, or repurpose the A4 study UUID.

## 18. Objective acceptance, reviewer checklist and PR description

### 18.1 Implementation and correctness acceptance are separate

**Implementation acceptance:** the precise format and five-file integration exist, compile, retain legacy/A3 APIs and pass the prescribed cost/byte/limit gates.

**Correctness acceptance:** INV trace is complete; adversarial, negative, boundary, full/lean, real local/remote, compaction failure/PIT and actual process-restart checks have executed and passed; all mandatory QA/coverage/CI has passed; protected historical evidence is unchanged; residual risks are exactly the approved bounded set.

Both are required for G0–G8 completion. Independent acceptance G9 remains a reviewer/maintainer decision. Do not use overall line coverage, a small green test subset or a favorable projection as a substitute.

### 18.2 Reviewer checklist

- [ ] Source pins, latest-main reconciliation and all producer call sites match the plan.
- [ ] F id/version is free, old E support intact, no SectionKind/global-format/manifest-layout change.
- [ ] Compact grammar matches literal bytes; no optional field, padding, implicit body-frequency alias or tuned threshold.
- [ ] Positional Keyword semantics are retained; real tests assert5/7/3, while raw doc-only tests cover4/6/2.
- [ ] Shared source validation order and old error values are preserved; width accounting is fused and false specialization does no compact work.
- [ ] Compact encoder reserves one final buffer after admission; no temporary complete streams, cloning, extra sizing walk or capacity growth.
- [ ] Long encoder delegates once to original A3 before compact work and emits identical bytes.
- [ ] Five named lazy factories eliminate successful-path owned error construction without changing error values/order.
- [ ] Compact construction is bounded/borrowed; no eager posting decode, decoded-entry charge or retained heap cache.
- [ ] Full and lean decode use one semantic path; lean retains all corruption/limit checks and no occurrence reserve/cache clone.
- [ ] EOF, cached advance, cancellation, conversion, frequency totals and stream tails follow the frozen contract.
- [ ] Both ordinary builder and compactor emit adaptive output only with a real section pair; count-based selection uses live output df.
- [ ] Real compaction crossing128/129 and the114,059-byte limit rejection preserve correct generations/PIT.
- [ ] Real FsDirectory, actual subprocess and pinned RustFS cold reader passed on the actual candidate.
- [ ] Legacy golden and actual legacy+F index tests remain intact; unexecuted E+F complete-index combination is explicitly assigned to A6.
- [ ] Scores/counts/keys/phrases/sorts/cursors use independent input/formula oracles.
- [ ] Required tests ran, filter counts are nonzero, coverage ≥85%, local QA and all five CI jobs passed with accurate provenance.
- [ ] No unauthorized code files, feature flags, dependencies, benchmark acquisition, schema changes, retries-to-green or historical evidence edits.
- [ ] Architecture/roadmap/register/report describe actual implementation and blocked future qualification accurately.
- [ ] A5 is independently reviewable; no A6/B/C work or automatic merge slipped into the diff.

### 18.3 Suggested draft PR title and body

**Title:** `PERF-06-A5: compact small postings while retaining split long lists`

Use the following body, filling only factual execution fields from the report. Do not replace a missing result with optimistic wording.

```markdown
## Problem

A3's split postings pay a 56-byte header and a 40-byte block-directory entry
even for a singleton. Unique indexed terms make this fixed cost dominate the
A4 corpus footprint. The ordinary builder and compaction also used different
postings encoders.

## Changes

- Add required adaptive-postings feature F/1.
- Use compact framed streams for df1 and df2–128; retain byte-identical A3
  split payloads for df129+.
- Write compact terms into one admitted output buffer, with size accounting
  fused into the shared validator.
- Reuse the existing lazy full/lean decoder and its validation, cancellation
  and resource semantics.
- Wire both SegmentBuilder and normal compaction to the same adaptive encoder.
- Retain legacy/E readers and immutable historical evidence.

## Validation and evidence

Execution report: docs/pr-artifacts/perf-06-a/PERF06A5_EXECUTION_REPORT.md

Tested source: <actual SHA>
Final head: <actual SHA>
Unit/structural/local integration: <actual result>
Real RustFS: <actual result and source/run>
Default/all-feature line coverage: <actual percentages>
Local mandatory QA: <actual result>
CI: <actual run URLs and conclusions>
Independent review: <actual state>

## Scope and limitations

A1–A3 remain retained. A4's original targets-not-met evidence is unchanged.
Full-corpus index sizes in this report are source-model projections until A6.
A5 does not claim warm-latency or writer-cost preservation. Genuine complete
E+F committed-index qualification is explicitly handed to A6.
No performance acquisition, A4 rerun, merge, or B1 implementation is included.
```

Store exact multiline text in a temporary body file when using `gh pr create/edit --body-file`. Preserve actual newlines and literal code text. Keep PR draft and separate from merged A4; ordinary pushes only.

## 19. Final instructions to the coding agent

Execute all authorized stages continuously. A passing preflight, completed stage or AUTO-RESOLVE decision means **continue**, not request permission. When blocked, preserve the concrete evidence, stop only affected work, and finish every demonstrably independent authorized task.

Implement the selected design; do not improvise a better one. Keep source-validation, byte-format, cancellation, resource, score and publication contracts fixed. Performance sensitivity is verified by the prescribed structure and tests, and later measured by A6.

Before your final response, ensure the report and draft PR distinguish what was implemented, what actually ran, what passed, what remains blocked, and who owns each next action. State exact local/remote/tested revisions. Do not claim A5 DONE before independent acceptance, A6 qualified, B1 unblocked, or A4 targets met.

If an unforeseen condition prevents conformance, use D40: report the exact file/symbol/input, the invariant at risk, the affected steps/gates, the work safely completed, and the smallest maintainer decision required. **Stop that work rather than inventing a solution.**

## Appendix A. Planning-source references

The design was checked against current source and the repository guide, rather than inferred only from roadmap titles.

- [Authoring guide](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md)
- [AGENTS](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/AGENTS.md) and [TESTING](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/TESTING.md)
- [Architecture](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/ARCHITECTURE.md), [roadmap](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/ROADMAP.md), and [benchmark policy](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/BENCHMARKING.md)
- [PERF roadmap](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/PERF_OPTIMIZATION_ROADMAP.md), [PERF-06 register](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md), [A register](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md)
- [A4 execution report](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/docs/pr-artifacts/perf-06-a/PERF06A4_EXECUTION_REPORT.md) and [merged PR #123](https://github.com/yduchesne/quervant/pull/123)
- [Source postings](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/segment/postings.rs), [format primitives](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/segment/format.rs), [builder](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/segment/build.rs), [reader](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/segment/reader.rs), [compaction](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/src/index/merge.rs)
- [Scoring integration oracle](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs), [complete legacy compatibility fixture/tests](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/tests/pr07_compatibility.rs), [real remote tests](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/crates/quervant-core/tests/pr13_remote.rs)
- [Frozen corpus generator source](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/benchmarks/quervant_bench/lean/runtime.py) and [CI topology/gates](https://github.com/yduchesne/quervant/blob/5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d/.github/workflows/ci.yml)

**Planning validation:** byte-table/fixture arithmetic and plan consistency are checked as part of authoring. No implementation, real benchmark acquisition, code push or PR publication is claimed by this document.





