# PERF-06-A3 execution report — versioned split postings streams

**Plan:** [`PERF06A3_DETAILED_PLAN.md`](PERF06A3_DETAILED_PLAN.md) (verbatim copy of the approved
execution contract, `sha256 fa46e783a20106762c20f81e4e5d414a949ed576baf4da0fb6d6e6f211cfa666`)
**Branch:** `dev/perf06-a3-split-postings` → `main`
**Source commit under test (code + unit/integration tests + `ARCHITECTURE.md`):**
`f076739f7aa5a1456d8ec978ec6ddbfe75491f7f`
**Status:** `PERF06_A3_IMPLEMENTED_CI_PENDING` at the time this report was written; hosted CI
status, the exact tested head and the RustFS job outcome are appended by the follow-up
evidence commit (§11, §12) — this report never claims a pass it did not observe.

---

## 1. Repository, PR and base identity

| Item | Value |
|---|---|
| Repository | `yduchesne/quervant` |
| Dependency PR | [#121 `PERF-06-A2: Validated document/frequency-only postings decoding`](https://github.com/yduchesne/quervant/pull/121) |
| A2 API state (`gh pr view 121 --json state,mergedAt,mergeCommit,headRefOid`) | `state: MERGED`, `mergedAt: 2026-11-23T21:30:53Z`, `mergeCommit.oid: 668a58372a514cef4896ea595b0d96d1a3cecb85`, `headRefOid: 4a7108a538c692faf87befb3ee6474c0ead6e3e3` |
| `BASE_MAIN_SHA` (fast-forwarded `origin/main`) | `668a58372a514cef4896ea595b0d96d1a3cecb85` (`Merge pull request #121 …`) |
| A3 branch | `dev/perf06-a3-split-postings`, created at `BASE_MAIN_SHA` |
| Local `dev/perf06-a3` | Pre-existing pointer to the same merge commit; no A3 work was based on it, nothing was reset or force-pushed |
| Pre-existing A3 branch/PR | None (`git branch -a --list '*perf06-a3*'`, `gh pr list --search perf06-a3`): D04/D01 not triggered |
| Working tree before changes | Clean (no tracked or untracked changes) |

`gh` reported `MERGED` with a non-null timestamp and a merge commit, so P0 proceeded. The merge
commit is the A2-reviewed source: every blob in §2 matches.

## 2. Accepted-`main` source blobs

`git rev-parse HEAD:<path>` at `BASE_MAIN_SHA`; all 16 rows match the plan table exactly.

| Path | Expected (A2) = actual |
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

**No deviations, no D03.** Consumer inventory confirmed exactly the accepted shape: four A2
lean consumers (`search/execute.rs::build_leaf_data` Term + MultiTerm;
`search/score.rs::compute_stats` persisted-norms partially-live + legacy no-norms) and full
positional consumers (`search/execute.rs::build_phrase`, `index/merge.rs` ×2,
`index/snapshot.rs` test, `tests/pr15c_a_segment_state.rs`). No new consumer needed a change:
the split codec lives entirely inside `PostingsReader`.

### P0 baseline (before any edit)

All green: `cargo test -p quervant-core --lib a2_u` (10), `--lib postings_round_trip_and_errors`
(1), `--test segment_codec` (25), `--test segment_golden` (2 + 1 ignored), `--test
pr15i_d2a_scoring_contract` (17), `--test pr07_properties` (4), `--test pr13_remote` (5,
real-RustFS tests ignored). No `DETERMINISTIC_PREEXISTING_FAILURE` at baseline.

## 3. Pre-implementation invariant challenge and code mapping

Each invariant was challenged against real source before editing; failure boundaries considered:
0/1/127/128/129/256/257 postings, positional vs doc-only, mixed fields, `tf>1`, 128→129
monotonicity with an absolute reset, malformed last occurrence of a dead document, zero/oversized
frequency, short/extra streams, overlapping offsets, forged first doc id, table count mismatch,
invalid required feature, repeated EOF, cancel-before-EOF, PIT, deleted/upserted docs and a fresh
RustFS cold bootstrap.

| INV | Implementation | Evidence |
|---|---|---|
| INV-01 | `format.rs` `FEATURE_SPLIT_POSTINGS`; builder requires it iff the DICTIONARY/POSTINGS pair exists; reader dispatches on retained required features only | U01, U11, I01, I03 |
| INV-02 | Encoder absolute-at-block-start + deltas; decoder cross-block monotonicity; exact `freq_total` check at EOF | U02, U03, U05, U10, I01 |
| INV-03 | One `read_one_with` validates every positional field in both modes; later/dead postings still validated | U04, U06, U07, U08, I03 |
| INV-04 | Lean mode never reserves occurrences nor clones `Posting` | U04 (`decode_observation` witnesses) |
| INV-05 | `next`, `next_with`, `advance`, `advance_with`, `into_doc_freq`, EOF, cancellation unchanged; `advance` strictly sequential | U04, U08, U09, I02 |
| INV-06 | `check_entries`, `max_decoded_entries`, `check_alloc::<Occurrence>` kept; checked arithmetic; no allocation from forged counts | U05, U07, U09, U10 |
| INV-07 | Feature + payload version explicit; legacy and split payloads reject each other's markers; old bytes immutable | U01, U03, U10, I03, I04 |
| INV-08 | Exact search semantics through the real writer/reopen path | I02, I04 + all inherited suites |
| INV-09 | Only one required feature + internal postings bytes change; no new section/remote/cache path | §6 diff audit, I01, I05 |
| INV-10 | Canonical, ascending, exact-length directory; borrowed parsing; boundary re-check | U03, U05, U06, U07 |
| INV-11 | Structural byte counts only; no timing loop, no threshold, no profiler | U12 + I03 print |
| INV-12 | Every locally runnable gate executed; RustFS gate reported separately | §11, §12 |

## 4. RED evidence before production edits

A3-U01/U02/U05 were added first. `cargo test -p quervant-core --lib a3_u` produced exactly the
expected missing-API failures and nothing else:

```text
error[E0432]: unresolved import `super::format::FEATURE_SPLIT_POSTINGS`
error[E0432]: unresolved import `super::postings::encode_split_postings_block`
error[E0599]: no associated function or constant named `new_split` found for struct `PostingsReader<'a>` (3×)
error: could not compile `quervant-core` (lib test) due to 5 previous errors
```

No pre-existing regression was used as RED. Remaining U cases were then written against the
frozen layout using hand-authored `ByteWriter` fixtures (`A3RawSplit`), not encoder output.

## 5. Format byte table, directory geometry and worked hex fixture

Header (56 bytes, little-endian, no padding):

| Off | Field | Value |
|---:|---|---|
| 0 | `marker:u8` | 2 doc-only / 3 positional |
| 1 | `payload_version:u8` | 1 |
| 2 | `flags:u16` | 0 |
| 4 | `block_docs:u32` | 128 (fixed) |
| 8 | `block_count:u32` | `ceil(posting_doc_count/128)` |
| 12 | `reserved:u32` | 0 |
| 16 | `posting_doc_count:u64` | `1..=min(segment_doc_count,max_postings_per_term)` |
| 24 | `freq_total:u64` | exact checked sum, `>= posting_doc_count` |
| 32 | `doc_stream_len:u64` | bytes |
| 40 | `freq_stream_len:u64` | bytes |
| 48 | `pos_stream_len:u64` | bytes, `0` for doc-only, otherwise `>= 5*freq_total` |

Order: header, doc stream, frequency stream, positional stream, `block_count × 40` directory
entries, EOF. Entry = `first_doc_id`, `first_posting_ordinal`, `doc_byte_offset`,
`freq_byte_offset`, `pos_byte_offset` (five `u64`). Entry 0 is canonical (ordinal 0, three zero
offsets); ordinals are `index*128`; doc/frequency and (positional) position offsets strictly
ascend and stay inside their streams; doc-only entries keep a zero position offset.

Checked arithmetic: `56 + doc_len + freq_len + pos_len + block_count*40 == extent.len()` with
`checked_add`/`checked_mul` and `usize::try_from` on every stream length before slicing.
`block_count` is validated against `ceil(posting_doc_count/128)` and `posting_doc_count` against
`max_postings_per_term`/`segment_doc_count` **before** any directory byte is touched, so a forged
count cannot drive an allocation.

Hand-computable fixture (A3-U02): one doc-only posting `doc=0,freq=1` in a 2-doc segment →
`56+1+1+0+40 = 98` bytes:

```text
02 01 0000 80000000 01000000 00000000
0100000000000000 0100000000000000 0100000000000000 0100000000000000 0000000000000000
00 01
00*40
```

Positional variant (one occurrence `position=0,length=1,value_index=0,start=0,end=1`) is 103
bytes with marker `03`, `pos_stream_len=5` and positional bytes `00 01 00 00 01`.

## 6. Allowlisted changes, ownership and dispatch

| Path | Change |
|---|---|
| `segment/format.rs` | `FEATURE_SPLIT_POSTINGS = 0x000E` + supported-feature row (7 lines) |
| `segment/postings.rs` | shared source validator, `encode_split_postings_block`, header/stream/directory constants, `PostingStreams`/`SplitStreams`/`SplitBlockEntry`, `new_split`, stream-aware `read_one_with`, `read_doc_id`, `read_frequency`, `position_varint`, `finish` |
| `segment/build.rs` | single per-term encoder call replaced; required feature declared for non-empty postings |
| `segment/reader.rs` | new feature/section-pair validation; feature-driven constructor dispatch |
| `segment/tests.rs` | A3-U01…U12 + hand-authored wire fixtures |
| `tests/segment_codec.rs` | A3-I01, A3-I03 (+ structural size line) |
| `tests/pr15i_d2a_scoring_contract.rs` | A3-I02 |
| `tests/segment_golden.rs` | A3-I04 |
| `tests/pr13_remote.rs` | A3-R01 (ignored, existing RustFS harness) + phrase helper |
| `docs/ARCHITECTURE.md` | "PERF-06-A3 split postings v1 (implemented)" |
| `docs/pr-artifacts/perf-06-a/PERF06A3_DETAILED_PLAN.md` | verbatim approved plan |

**Declared allowlist exception (maintainer attention):**
`crates/quervant-core/tests/pr08_integration.rs` — its PR-8 guard `p8_t42_golden_bytes_features_unchanged`
asserts a *closed* list of required features for newly built segments. §3.1 of the frozen design
mandates a new required feature, so the assertion necessarily conflicts. The change is the
precedent already used by PR 15I-B in the same list: add `FEATURE_SPLIT_POSTINGS` to `known` and a
positive assertion with an explicit comment. No fixture, digest or frozen-byte expectation was
touched. This is the only edit outside the allowlist; it is reported here rather than silently
absorbed (D23 / D41 note).

Ownership: the encoder owns only temporary byte writers and returns one term buffer;
`SegmentBuilder` concatenates under the existing budget/commit path. The reader holds borrowed
slices for three streams plus the directory, parses 40-byte entries on demand and retains no
`Vec` of entries. `VerifiedSegmentState`/`ReaderSnapshot` keep owning the bytes.

## 7. Unit evidence (A3-U01…U12)

`cargo test -p quervant-core --lib a3_u` → **12 passed**.

| Case | Result highlights |
|---|---|
| U01 | `0x000E/1` supported; empty segment omits feature + both sections; non-empty segment has feature and markers 2/3; featureless split bytes fail as `Corrupt{context:"occurrence kind"}`; feature without pair → `Corrupt("split postings feature requires dictionary and postings")` |
| U02 | exact 98-byte doc-only and 103-byte positional payloads, header fields, single zeroed entry, decode round-trip |
| U03 | block counts 1/1/1/2/2/3 for 1/127/128/129/256/257; ordinals 0/128/256; doc-stream widths 127/128/129/130/257/259; absolute `0x80 0x01` at ordinal 128; duplicate → `NonMonotoneDocId{4,4}`; 128→129 regression → `NonMonotoneDocId{127,127}` in both modes |
| U04 | occurrences equal to hand-authored input; full reserves/clones > 0, lean exactly `(0,0)`; cached `advance(1)/advance(0)`; conversion after a full read emits only the next unread posting; doc-only vectors empty |
| U05 | 30+ geometry mutations: block_count off-by-one, `block_docs` 0/127/129, ordinal/offset/first-doc canonicality+ordering+range, positional offset ordering/range, doc-only non-zero position offset, forged/truncated declared lengths, `u64::MAX` overflow, trailing byte, forged posting count → `LimitExceeded` with no directory use |
| U06 | markers 0/1/9, version 0/2, flags (`UnknownFlags{"split postings",1}`), reserved, noncanonical doc varint, truncated `end offset`, zero position length, duplicate position, decreasing value index, start>end, position overflow — identical full/lean errors; corruption on the second posting surfaces only when traversed |
| U07 | forged in-range first doc id/offset accepted by constructor, rejected at block boundary after 128 valid postings; `advance(129)` cannot skip it; `advance(200)` cannot skip a malformed earlier positional record |
| U08 | one poll per attempted posting (1/2/4); cancellation wins over EOF; repeated EOF `None`; cancelled-after-EOF `Cancelled`; later dead posting's corruption still fatal |
| U09 | forged count 2^40 → `LimitExceeded(2^32)`; count > segment docs; `ZeroFrequency`; `max_decoded_entries`; `check_alloc::<Occurrence>` exact/one-under in both modes; `freq_total` mismatch only at EOF (`"frequency total mismatch"`); checked sum overflow (`"frequency total overflow"`); forged block count rejected before use |
| U10 | legacy 19-byte doc-only and 24-byte positional specimens byte-exact; legacy constructor rejects markers 2/3; split constructor rejects 0/1; legacy trailing (`"1 trailing bytes"`), noncanonical (`InvalidVarint{context:"doc id delta"}`) and limit categories unchanged; `golden_norms.seg` digest still `49f813a6…5c39b` |
| U11 | contiguous, exact dictionary extents, header `doc_freq` agreement; single missing section keeps `MissingSection`; whole pair absent → split-feature corruption; wrong `doc_freq` → `Corrupt{"postings","dictionary doc_freq does not match posting count"}`; overflowing/out-of-range extents → `Corrupt{"dictionary",…}` via rebuilt containers with recomputed digests |
| U12 | two identical builds → byte-identical segments; structural size table (below); no threshold |

**Error-context policy (documented, not silent):** split-*structural* failures use
`Corrupt{context:"split postings", …}` with fixed literals. Semantic corruptions shared with the
legacy decoder (`zero position length`, `value index decreased`, `start offset exceeds end offset`,
`position overflow`, `doc id out of range`, `dictionary doc_freq does not match posting count`)
keep their historical `"postings"`/`"dictionary"` contexts so legacy error values stay exact; the
single-missing-section case keeps `MissingSection` (existing pair validation intact) and the
whole-pair case uses the mandated split corruption.

## 8. Full/lean witness, cancellation, limits, golden digest

* Full mode: `positional_vector_reserves > 0`, `cached_posting_clones > 0`; lean mode: exactly
  `(0, 0)` before and after conversion, including after a prior full read.
* Cancellation poll counts observed: `1` before the first posting, `2` at the second, `4` after
  the third plus EOF attempt — one poll per attempted posting, no per-occurrence polls.
* `check_alloc::<Occurrence>(freq)` still applies in both modes: exact bound passes, `exact-1`
  fails with `LimitExceeded{limit:exact-1, requested:exact}` in both.
* `golden.seg` and `golden_norms.seg` are unmodified; `golden_norms.seg` SHA-256 remains
  `49f813a68a4adedf8b69c8a965159a840bc993ca252f81efb1887daa95b5c39b`.

## 9. Production-boundary evidence

| ID | Path exercised | Result |
|---|---|---|
| I01 `tests/segment_codec.rs` | `SegmentBuilder` → POSTINGS/DICTIONARY → `SegmentReader` for 0/127/128/129/257 docs, absent term | feature presence/absence, exact contiguous extents, markers, header counts and block counts, exact full/lean doc sequences (0..n) |
| I02 `tests/pr15i_d2a_scoring_contract.rs` | `FsDirectory` real writer → commit → fresh reopen → `UnifiedSearcher`, 257 docs | exact key sets from fixture input, totals 257, K10/K100 pages, score-bit equality vs full reference, relevance vs explicit-sort bit equality, prefix/`And([Term])` parity, phrase membership (`ordinal%4!=0` → 192 hits), cursor pages, delete+reopen (254 hits) with immutable PIT |
| I03 `tests/segment_codec.rs` | split segment + rebuilt legacy-equivalent container; malformed split body inside a valid reconstructed outer envelope | per-term logical parity; corrupted position-length fails both cursors with `Corrupt{"postings","zero position length"}`; an unselected clean term still decodes |
| I04 `tests/segment_golden.rs` | pinned `golden_norms.seg` + fresh `golden_segment()` (same two docs), two independent readers | identical stored keys/values, remap, norm lengths, dictionary terms/DF and every posting record; split feature only on the fresh segment; digest unchanged. No same-manifest mixed-format claim |
| I05 `tests/pr13_remote.rs` `a3_r01_split_postings_rustfs_cold_reopen` | real `RemoteIndex` write → commit → delete disposable workspace → `open_existing` from RustFS | **executed only by the hosted RustFS job** (see §11/§12); locally `BLOCKED` because no pinned RustFS service is running (D36) |

Inherited suites re-run and green: `pr07_integration` (12), `pr07_properties` (4),
`pr14_unified_mixed` (14), `pr15i_d2a_scoring_contract` (18 incl. A3-I02), `pr15i_b_stored` (20),
`pr15i_d3_c` (20), `segment_golden` (3 + 1 ignored), `pr06_faults` (17), `segment_corrective` (24),
`pr15c_a_segment_state` (5), plus the whole workspace (§11).

## 10. Structural size report (bytes; not latency)

Deterministic encoder sizes (1 occurrence per posting; doc-only / positional):

| postings | legacy doc-only | split doc-only | legacy positional | split positional |
|---:|---:|---:|---:|---:|
| 1 | 19 | 98 | 24 | 103 |
| 127 | 271 | 350 | 906 | 985 |
| 128 | 273 | 352 | 913 | 992 |
| 129 | 275 | 395 | 920 | 1040 |
| 257 | 531 | 692 | 1816 | 1977 |

Closed forms: split positional `56 + 7n + 40*ceil(n/128)` (doc-stream length grows by one byte per
extra block because absolute ids ≥ 128 need two varint bytes); legacy positional `17 + 7n`.
Complete segment, same 3-document logical corpus (A3-I03): split **3924** bytes vs legacy
**3450** bytes; a 2-document segment via the real builder is 1327 bytes. These are structural
descriptors only — **no timing, no profiler, no benchmark, no acceptance threshold**. A4 owns any
warm-performance decision.

## 11. Local QA on the final source state (`f076739`)

Toolchain: stable `rustc/cargo 1.98.1 (48a229cea 2026-09-01)`, MSRV `cargo 1.85.0
(d73d2caf9 2024-12-31)`, `cargo-llvm-cov 0.9.1`. Commands run from the workspace root after the
final source/test edit.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 138 targets, **2547 passed**, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 138 targets, **2592 passed**, 0 failed, 95 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 2547 passed, 0 failed, 13 ignored |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2592 passed, 0 failed, 95 ignored |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **93.23 % lines** (61839 lines, 92.72 % regions, 87.68 % branches) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.91 % lines** (63346 lines, 92.29 % regions, 87.58 % branches) |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only; nothing timed) |
| `git diff --check` | PASS (`git diff --cached --check` additionally reports only the intentional Markdown hard-break trailing spaces of the verbatim plan copy — same as the accepted A2 plan artifact) |

New-code coverage on the touched modules (default features): `segment/postings.rs` 88.66 % lines,
`segment/build.rs` 91.06 %, `segment/reader.rs` 92.59 %, `segment/format.rs` 92.96 %. No module
was excluded and no threshold was lowered.

### One unreproduced flake (five-class taxonomy: `NONDETERMINISTIC_FLAKY_FAILURE`)

During the **first** default-feature `cargo llvm-cov` invocation,
`segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct`
failed once at `reader.rs:2109` — `assert_eq!(builds_after - builds_before, 1)` observed `2`. This
is a **pre-existing** lib test on a path A3 does not modify: it asserts a delta of a *process-global*
`stored_blocks::CERTIFICATE_BUILDS` atomic, so any other concurrently running lib test that builds
a STORED v2 certificate can inflate the delta. It was not reproduced in the 4 subsequent full
workspace runs, the second/third coverage runs, 30 non-instrumented parallel lib runs, or 35
instrumented parallel lib runs (16 and 64 test threads). The mandatory coverage gate then passed
on the final state (93.23 %). Not silently relabeled: the flaky assertion remains a residual risk
for hosted CI and belongs to a separate, protected test file that this PR must not change.

## 12. Applied preauthorized decisions, deferrals, failures

| Rule | Applied action |
|---|---|
| D02 | A2 merged + blobs match → pinned `BASE_MAIN_SHA`, created the prescribed branch |
| D05 | `FEATURE_SPLIT_POSTINGS = 0x000E/1`, no renumbering |
| D06 | Reused `SectionKind::Postings` and dictionary v1 unchanged |
| D07 | Replaced the single `encode_postings_block` builder call; no toggle/alternate builder |
| D08 | Extracted one private source validator; legacy bytes proven byte-exact (U10) |
| D09 | No search/score/phrase code change; version dispatch only in `SegmentReader` |
| D10/D11 | One `read_one_with`; `PostingStreams`/`SplitStreams` are private module-level items |
| D12 | 40-byte entries parsed on demand from borrowed bytes; no `Vec`, no seek |
| D13 | `advance_with` left exactly sequential |
| D14 | Feature-set dispatch; each constructor rejects the other marker set |
| D15 | Empty builder emits no split feature/section |
| D17 | Fixed 128-posting blocks, absolute id at each block start |
| D19 | Historical `check_alloc::<Occurrence>(freq)` kept in both modes |
| D21 | Golden fixtures untouched; dual-format read proven (I04) |
| D22 | Two independent real readers over the same corpus (I04); no manifest injection |
| D24 | Checked `LimitExceeded` on encoder output size; no limit raised |
| D25 | Typed rejection, no panic/`unwrap` on malformed input; counterexamples U05/U06/U11 |
| D28 | `Corrupt("frequency total mismatch")` at EOF, no partial success |
| D29 | `ContainerBuilder` + copied features for every malformed-container test |
| D30 | RED captured with missing-API compile errors only |
| D31 | One MSRV lint fix (`impl SplitStreams<'_>`) inside the allowlist |
| D32 | In-scope assertion/index corrections in the new tests only |
| D35 | Added two extra directory-branch counterexamples (positional offset ordering, doc-only position offset) |
| D40 | Recorded both codec sizes; no threshold, no retune |
| D43 | Declared feature without the section pair → mandated `Corrupt`; single missing section keeps `MissingSection` |
| D23 / D41 | **Exception:** updated the PR-8 closed feature-list guard (see §6). Needs maintainer sign-off |
| D36 | Local real-RustFS gate `BLOCKED` (no pinned service; plan forbids starting one) → not claimed as executed locally |
| D37 | Hosted CI on the exact head pending at report-writing time → `..._CI_PENDING`, not READY |
| D42 | No benchmark, profiler or timed acquisition was run; only `cargo bench --no-run` |

No unresolved implementation failures. No threshold relaxation, no test deletion, no skipped
failure.

## 13. Adversarial self-review

| INV | How an incorrect implementation could still pass happy-path tests | Negative fixture that prevents it | Residual risk |
|---|---|---|---|
| 01 | Reading the marker to pick a codec | featureless split bytes (U01/U11), marker 0/1 under the split constructor (U06/U10) | none known |
| 02 | Per-block deltas without cross-block check | 128→129 regression (U03), directory vs stream first doc (U07) | absolute ids ≥ 2^56 widen beyond 9 bytes only at absurd term lengths, bounded by extent equality |
| 03 | Skipping unread occurrences in lean mode | truncated/zero-length/decreasing fields in both modes (U06), dead later posting (U08), advance over malformed record (U07) | none known |
| 04 | Lean path reserving without observable effect | `decode_observation` reserve/clone witnesses (U04) | counters are test-only `cfg(test)` thread-locals |
| 05 | A fast seek on the directory | U07's `advance` cases; `advance_with` unchanged | none: no seek code exists |
| 06 | Allocating from `block_count` before validation | forged 2^40 count (U05/U09), block-count mismatch before extent math | encoder-side stream writers grow with validated input only |
| 07 | Silent rewrite/repin of old fixtures | pinned digest + legacy 19/24-byte specimens (U10), I04 digest assertion | none known |
| 08 | Score drift masked by loose tolerance | exact `to_bits()` comparisons (I02) and inherited SC suite | phrase scoring is compared by membership only, matching the plan |
| 09 | New section/feature leakage into manifests | diff audit; builder-only required feature; I01 empty-segment case | pre-existing `pr08` guard updated explicitly |
| 10 | Overlapping/forged offsets accepted | 30+ geometry mutations (U05), boundary mismatches (U07) | directory offsets > 2^63 are impossible to express in an accepted extent |
| 11 | A timing claim hiding in test output | U12/I03 print sizes only; no `Instant`, no Criterion | none |
| 12 | Claiming unexecuted gates | §11/§12 tables; RustFS status reported as BLOCKED/pending | hosted CI evidence is appended, not assumed |

Remaining unproven locally: the real RustFS cold-reopen path (I05) and hosted CI on the exact
head. Both are tracked in §12 (D36/D37) and neither is reported as passed.

## 14. Disposition

`PERF06_A3_IMPLEMENTED_CI_PENDING` — implementation, unit tests, real local production-path
integration tests, stable/MSRV lint+test, ≥85 % coverage and documentation all passed locally on
`f076739f7aa5a1456d8ec978ec6ddbfe75491f7f`. The real-RustFS gate did not execute locally and
hosted CI on the exact head had not yet completed, so READY is not claimed here; see the follow-up
evidence commit for CI results. Independent review remains required, and no merge or A4 work is
started.
