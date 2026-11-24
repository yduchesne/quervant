# PERF-06-A5 — Execution report

**Stage:** PERF-06-A5 — compact small postings while retaining split long lists
**Plan of record:** [PERF06A5_DETAILED_PLAN.md](PERF06A5_DETAILED_PLAN.md) (approved planning deliverable)
**Status:** `READY_FOR_INDEPENDENT_REVIEW` — G0–G8 pass, including real hosted
RustFS evidence for R01. Not `DONE`, not `ACCEPTED`, and no A6 performance
qualification is claimed.
**Milestone:** `v0.1-perf`
**Authoring time:** 2026-11-23/24

---

## 1. Disposition

| Gate | Evidence | Result |
| --- | --- | --- |
| **G0 — Source/preflight** | §2; clean worktree at the pinned base, empty frozen-input drift diff, producer/feature scan, protected hashes captured before edits | **PASS** |
| **G1 — Pre-implementation correctness** | §4 (INV trace, §9 challenge ledger, decision register) | **PASS** |
| **G2 — Implementation and cost structure** | §5, §6 (exactly five production files; both producers; one-buffer/shared-decoder source audit) | **PASS (agent audit; independent confirmation is G9)** |
| **G3 — Unit/codec** | §7 (`a5_u01`…`a5_u16`, 16/16 pass; retained A2/A3 suites pass) | **PASS** |
| **G4 — Local boundaries** | §8 (I01–I06 + S01 on real `FsDirectory`, real compaction, real subprocess) | **PASS** |
| **G5 — Real remote boundary** | §9 — R01 executed and passed on the pinned real RustFS topology in the hosted `rustfs` job; local service/credentials were absent (`D29`) and no fake provider was used | **PASS (hosted real provider)** |
| **G6 — Local QA** | §11 (all §14.3 commands pass; coverage 92.74% default / 92.31% all-features) | **PASS** |
| **G7 — CI** | §11 — all five required jobs passed on head `9283344` (run 45333872681, conclusion `success`) | **PASS** |
| **G8 — Evidence/docs/audit** | §12–§14 (report, adversarial review, protected evidence unchanged, bounded residuals, A6 handoff) | **PASS** |
| **G9 — Independent acceptance** | Maintainer/reviewer — not performed by the executing agent | **OPEN** |

**Implementation status:** complete for the A5 design scope.
**Correctness status:** all prescribed local correctness/adversarial/boundary
gates executed and passing.
**Remote status:** R01 passed against the pinned real RustFS service in the
hosted `rustfs` job (log: `test real::a5_r01_adaptive_postings_rustfs_cold_reopen ... ok`).
**A6:** `PLANNED — SEPARATE DESIGN/ACQUISITION REQUIRED`. **B1:** still blocked.
**A4:** disposition untouched (`PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`).

---

## 2. Authority and source

| Item | Value |
| --- | --- |
| Approved plan | this repository copy of `PERF06A5_DETAILED_PLAN.md` (copied without redesign) |
| Planning base | `main@5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d` (merge of A4 PR #123) |
| Verified `origin/main` at start | `5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d` (identical; base is an ancestor) |
| Frozen-input drift diff (§13 P0 step 4) | empty (`git diff --exit-code <base> origin/main -- crates Cargo.toml Cargo.lock rust-toolchain.toml .github/workflows tests benchmarks/quervant_bench benchmarks/pr15d AGENTS.md docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md docs/TESTING.md docs/ARCHITECTURE.md docs/PERF_OPTIMIZATION_ROADMAP.md docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md` → exit 0) |
| Working branch | `dev/perf06-a5-adaptive-postings` (created from the verified base; branch had no prior A5 work — `D04` classification **NOT STARTED**) |
| Toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1`; MSRV job toolchain `1.85.0` |
| Host | Linux x86_64 (`x86_64-unknown-linux-gnu`), no container runtime services started |
| Known pinned documentation defect | `docs/TESTING.md` already contains committed conflict-marker text at the base; left untouched per §13 P0, and no `git ls-files -u` entries existed |

Producer/feature scan at the base (`rg -n 'encode_(split_)?postings_block|FEATURE_SPLIT_POSTINGS|FEATURE_ADAPTIVE_POSTINGS' crates benchmarks --glob '*.rs'`):
the only production consumers of the old encoders were `segment/build.rs`
(`encode_split_postings_block`) and `index/merge.rs` (`encode_postings_block`);
every other match was an encoder definition or a test. `FEATURE_ADAPTIVE_POSTINGS`
did not exist. No `D08` condition occurred.

Baseline health (§14.1) was executed on the unmodified source and passed:
`--lib a2_` 22/22, `--lib a3_` 54/54, `segment_codec` 27/27, `segment_golden`
3/3 (+1 ignored), `pr07_compatibility` 14/14, `pr09_merge` 6/6,
`pr15i_d2a_scoring_contract` 18/18.

---

## 3. Reconciliation of prior stages

* **A1** (query-local BM25 preparation) and **A2** (consuming doc/frequency-only
  cursor) remain merged and unchanged; their suites pass unchanged.
* **A3** separated/versioned split streams remain implemented. The A3 *writer
  default* is replaced by A5 (see `docs/ARCHITECTURE.md` amendment); the A3
  payload remains the long-list representation and its encoder/reader/API are
  untouched and still tested directly.
* **A4** PR #123 is merged. Its complete second paired campaign met two of four
  primary targets with all 16/16 A/A controls and 12/12 guards passing; the
  measured disposition `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`
  is preserved verbatim and is **not** reinterpreted by this report. Two existing
  `benchmarks/studies/perf-06/warm/results/*.json` acquisitions were read only;
  their hashes are unchanged (§14).
* A producer inconsistency recorded in the plan was confirmed and closed:
  `SegmentBuilder` emitted A3 split payloads while `index/merge.rs` compaction
  still used the legacy interleaved encoder. Both now use the adaptive encoder.
* No prior A5 work existed on the branch.

---

## 4. Pre-implementation and adversarial gate

### 4.1 Invariant ledger (INV → implementation → executed evidence)

| ID | Contract | Evidence actually executed |
| --- | --- | --- |
| INV01 | F/1 only with a real dictionary/postings pair; neither family for no indexed terms; compaction follows the same rule | `a5_u01`, `a5_u12`, `a5_i01` (count 0 and stored-only schema), `a5_i05_stored_only_compaction_has_no_postings`, `a5_i06` |
| INV02 | Featureless legacy and E/1 A3 payloads keep original bytes/counts/errors; F mode is df1 / 2–128 / 129+ | `a5_u02`–`a5_u04`, `a5_u12`, `a5_u13`, `a5_u14`, `a5_i04_feature_marker_combinations`, `a5_i06` |
| INV03 | Full decoding returns exact IDs/frequencies/occurrences; lean returns the ID/frequency projection | `a5_u02`–`a5_u04`, `a5_u07`, `a5_u14`, `a5_i01`–`a5_i04`, `a5_r01` (implemented) |
| INV04 | Canonical, bounded, exhaustive compact framing; no count ambiguity, ignored tail, extent escape or silent fallback | `a5_u06`, `a5_u11`, `a5_u12`, `a5_i01` |
| INV05 | Invalid source is never sorted/repaired; semantic error precedence preserved | `a5_u05` (12 invalid sources, adaptive vs legacy vs split error identity, doubly invalid ordering) |
| INV06 | Shared lazy per-posting validation, decoded-resource charging and cancellation retained; no eager pre-decode | `a5_u07`–`a5_u11`, inherited A2 suites |
| INV07 | One admitted output buffer; validation/measurement fused; no growth or scratch streams | `a5_u15` (counts/capacities), `a5_u16`, source audit §6 |
| INV08 | Long-list encoding delegates once to A3 with zero compact work; bytes identical | `a5_u04`, `a5_u15` (long-path counters all zero), `a5_u13` (129/257 identity) |
| INV09 | Valid compact cursor construction borrows bytes with no heap allocation; lean allocates no occurrence vector | `a5_u10` (decode witnesses 0/0 for lean), `a5_u15` (no buffer at construction; construction is not instrumented because it allocates nothing by construction — source review, §6) |
| INV10 | Scores, totals, ordering, phrase semantics, cursors, deletes/upserts and PIT visibility unchanged | `a5_i02`, `a5_i03` (subprocess), `a5_i05_*`, `a5_i06`, inherited SC01–SC16 |
| INV11 | Publication/recovery/cache/immutable-object behavior unchanged; no in-place rewrite | `a5_i03`, `a5_i05_compaction_limit_failure_preserves_generation` (CURRENT byte-identical), `a5_i06` (original objects byte-identical), inherited PR9 suites |
| INV12 | Sizes deterministic and equal to independent arithmetic; long bytes equal A3; no performance claim | `a5_u13`, `a5_u16`, §10 |
| INV13 | A4 negative evidence, configurations and results immutable; statuses follow passed gates | §14 protected-file hash/diff check |

### 4.2 §9 challenge ledger (expected result vs actual discriminator)

| Challenge | Actual discriminator in this implementation |
| --- | --- |
| Singleton frequency alias | `a5_u11` builds header `freq_total=5` with body frequency `1`; the returned record keeps `freq=1` and EOF fails `"frequency total mismatch"`. |
| Lean positions skipped | `a5_u07` corrupts occurrences and asserts identical full/lean typed errors; `a5_u10` proves lean reserves/clones zero. |
| Cheap constructor decodes everything | `a5_u07` clean-first/corrupt-second payload opens, first read succeeds, second fails; `a5_u09` `max_decoded_entries=1` on df2 fails only on the second posting. |
| Mode selector by encoded size or only on ordinary builds | `a5_u13` exact 128/129 crossing; `a5_i05_compaction_boundary_128_stays_short` (128 short) and `a5_i05_compaction_reclassifies_adaptive_terms` (129 long) plus `a5_i05_compaction_after_delete_crosses_down` (129→128 short). |
| Feature fallback/sniffing | `a5_u12`: F removed → legacy `"occurrence kind"` error (no adaptive fallback); optional F does not activate adaptive parsing; E+F conflict rejected. |
| Dictionary binding trusted | `a5_u12` patches dictionary `doc_freq` → `"dictionary doc_freq does not match posting count"`; `a5_i01` asserts header count equals dictionary `df`. |
| EOF short-circuit | `a5_u11` per-stream trailing-byte errors in order, then `a5_u08` cancellation-before-EOF and post-EOF cancellation. |
| Eager error allocation on success paths | The five prescribed `ok_or` → `ok_or_else` conversions exist; the separate A3 split document branch was left unchanged; new code uses `adaptive_corrupt` only on error paths (§6). |
| One-buffer illusion | `a5_u15` asserts exactly one compact output buffer, `initial_capacity >= len`, `initial_capacity == final_capacity`, and zero compact work on the long path; source review confirms header/streams are written into the single writer. |
| Double validation / long delegation | `a5_u15` long path: `validation_calls=1`, `compact_validation_calls=0`, `width_calls=0`, `compact_output_buffers=0`. |
| Historical tests rewritten to F | A3 assertions were migrated to *explicit A3 reconstruction* (`D09`) and remain active; pinned goldens/digests unchanged (`49f813a6…` still asserted). |
| Corruption fixture rejected only by checksum | I01/U06 fixtures rebuild a valid envelope (recomputed digests/lengths) and assert the intended inner typed error. |
| Ad-hoc committed-index rewriting | `a5_i06` uses the complete legacy fixture plus the public writer/commit/compact/reopen lifecycle only. |
| Exact score oracle from the code under test | Expectations come from `frozen_scalar_bm25` and input-derived statistics (`a5_i02`, `a5_i03`, `a5_i05_*`, `a5_i06`, `a5_r01`). |
| Misleading evidence | Projections are labelled **NOT MEASURED**; CI state is reported as observed (§11). |

### 4.3 Decision register

| # | Rule | Observed trigger | Action taken | Prohibited workaround avoided |
| --- | --- | --- | --- | --- |
| 1 | `D04` | Branch existed at the verified base with no commits | Classified `NOT STARTED`, renamed to the suggested A5 branch name, executed the full plan | Reimplementing/overwriting unseen work |
| 2 | `D09` | `a3_u01`, `a3_u11`, `a3_u12`, `segment_codec::a3_i01`, `segment_codec::a3_i03`, `segment_golden::a3_i04` failed only because the writer now emits F | Added an explicit A3 reconstruction helper (read built container → re-encode every term with the retained A3 encoder → rebuild Dictionary extents → replace F with E) and kept every A3 assertion; added separate A5 tests | Replacing E assertions with F, or accepting "either family" |
| 3 | `D10` | `pr08_integration::p8_t42_golden_bytes_features_unchanged` failed its closed feature allowlist | Added F to the known list; asserted F present and E absent for current output while E stays supported | Loosening the allowlist to "all ids" |
| 4 | `D11` | Reconstruction helper copied the constructor's baseline tuple twice (+4 bytes) | Skip exactly one matching `(FEATURE_BASELINE,1)` tuple, preserve the remaining multiplicity and every other section | Global feature de-duplication |
| 5 | `D13` | Test-authoring defects: wrong expected marker for a df2 term; header truncation range off by one; incorrect positional-corruption fixture sizing; header parse omitted the `P` field; wrong assumption that segment order follows commit order; OR-key expectation included non-matching documents; asserted a creating `Index` handle's generation before reopen | Fixed the tests; the production contracts were not changed | Changing the expected contract to match a wrong test |
| 6 | `D19` | I05 limit fixture | Compaction returned exactly `LimitExceeded { limit: 65_536, requested: 114_059 }` and left generation 2 intact on the first attempt | Raising the limit, falling back to legacy, or calling the rejection a regression |
| 7 | `D26` | — | No production/test edit outside §3 was needed | — |
| 8 | `D29` | No pinned RustFS service on `127.0.0.1:9000`, no `QUERVANT_RUSTFS_*` credentials, no running container | Completed all local work; R01 is implemented and runnable; G5 marked pending on hosted `rustfs` evidence | Starting an unapproved service/provider, faking the boundary, or reporting PASS |
| 9 | `D31` | Report-only commit follows the tested source | Tested SHA recorded; report commit presumed docs-only (scoped diff verified before closeout) | Claiming CI ran on the report commit |
| 10 | `D32` | One production fix after the first QA pass (reverting a well-intentioned lazy-error conversion in the *A3 split* document branch that §6.4 excludes) | Full mandatory QA rerun afterwards (§11) | Carrying stale PASS forward |
| 11 | `D39` | No genuine complete E (A3) committed index fixture exists | Accepted the bounded gate: real legacy+F lifecycle (`a5_i06`) plus explicit E container/decoder coverage (U04/U12/I04); A6 must design and execute a genuine E+F lifecycle | Fabricating a fixture or rewriting state pointers |

No `D03`, `D05`, `D07`, `D08`, `D14`, `D17`, `D20`, `D27`, `D33`, `D37` or `D40`
trigger occurred.

---

## 5. Implementation

Production changes are exactly the five authorized files.

| File | Change |
| --- | --- |
| `crates/quervant-core/src/segment/format.rs` | `FEATURE_ADAPTIVE_POSTINGS = 0x000F` + `(F,1)` in `SUPPORTED_FEATURES`; `ByteWriter::try_with_capacity`; `#[cfg(test)] ByteWriter::capacity_for_test`. |
| `crates/quervant-core/src/segment/postings.rs` | Compact constants and `adaptive_corrupt`; `CompactLengths`/`PostingsSource::compact_lengths`; `compact_varint_len`, `compact_total_len`, `accumulate_width`; `validate_source_postings<const MEASURE_COMPACT: bool>`; `encode_adaptive_postings_block`; `PostingStreams::Compact`/`CompactStreams`; `PostingsReader::new_adaptive`; shared document-delta match; compact frequency/position/sum/finish arms; three prescribed lazy error factories; `#[cfg(test)] encode_observation`. |
| `crates/quervant-core/src/segment/build.rs` | Per-term `encode_adaptive_postings_block`; `FEATURE_ADAPTIVE_POSTINGS` instead of `FEATURE_SPLIT_POSTINGS` at the existing pair-guarded emission site. |
| `crates/quervant-core/src/segment/reader.rs` | One feature-driven dispatch (`F → new_adaptive`, else `E → new_split`, else `new`); E/F conflict rejection; F pair-absence rejection; two prescribed lazy extent-error factories. |
| `crates/quervant-core/src/index/merge.rs` | Per-term `encode_adaptive_postings_block`; `FEATURE_ADAPTIVE_POSTINGS` inside the existing `has_positional` guard. |

Public API: only `encode_adaptive_postings_block` and the feature constant are
new; `new_adaptive` and all compact state stay crate-internal. `Cargo.toml`,
`Cargo.lock`, `rust-toolchain.toml`, crate layout, schema, manifest layout,
`SectionKind` values and workflow files are unchanged.

Intentional behavioural tightening: compaction now goes through the adaptive/A3
encoded-block admission, so a pathologically large merged term block can return
`IndexError::Segment(SegmentError::LimitExceeded { .. })` where the legacy
compaction encoder would not have. There is no fallback to the legacy encoder.
No broader equivalence is claimed for over-limit legacy compactions.

---

## 6. Performance-structure evidence (structural, not timing)

* **Validation once.** The shared validator is instantiated `::<false>` by the
  legacy and split encoders and `::<true>` only by the compact path. The long
  path returns before any compact validation, sizing or allocation.
* **Fused measurement.** Width accounting runs inside the existing per-posting
  and per-occurrence loops after the original checks for that element; the
  measured `width_calls` equal `2n + 5m + 4` (singleton) / `2n + 5m + 5` (short),
  which is exactly the minimum (no extra occurrence traversal).
* **One buffer.** `a5_u15` observes `compact_output_buffers = 1`,
  `initial_capacity >= encoded_len`, `initial_capacity == final_capacity` for
  singleton doc-only, short positional and is zero for the long path and for a
  rejected admission. `debug_assert_eq!` in the encoder additionally pins
  header end, each stream endpoint and the final length to the measured values.
* **Lazy errors.** The five prescribed sites are lazy; the compact-specific
  helpers construct owned strings only on error paths.
* **Borrowed reader.** `CompactStreams` holds three `ByteReader` borrows and one
  `u64` sum. `a5_u09` constructs a compact cursor under
  `max_single_allocation = 39` (below one decoded occurrence) without error, so
  construction performs no decoded/allocation charge; decoded charges happen
  incrementally per posting.
* **No lean regression.** `a5_u10` observes `(0, 0)` positional-vector reserves
  and cached-posting clones for a full lean traversal, and `(2, 2)` for a full
  positional traversal of the same payload.
* **Uninstrumented properties confirmed by source review:** the compact encoder
  creates no `ByteWriter` other than the final output, does not clone source
  postings, does not collect offsets and does not shrink-to-fit;
  `new_adaptive` performs only bounded header parsing and checked slicing.

**These are structural witnesses, not measurements.** A5 makes no latency,
writer-CPU, RSS or index-size claim.

---

## 7. Unit and compatibility results

Executed with `cargo +1.98.1 test -p quervant-core --lib segment::tests::a5_`
→ **16 passed, 0 failed**.

| ID | Test | Focus |
| --- | --- | --- |
| U01 | `a5_u01_feature_and_empty_segment_contract` | F id/version/support, E retained, current builder emits F only, empty + stored-only emit neither, unknown F/2 rejected, `SectionKind::MutationState = 0x000F` not renumbered |
| U02 | `a5_u02_literal_wire_fixtures_and_absolute_ids` | The four literal byte arrays decode to the input records (8/13/11/21 bytes); singleton frequency > 1; absolute ids 0/127/128/16383/16384 with widths 1/1/2/2/3 |
| U03 | `a5_u03_short_forms_and_stream_length_boundaries` | df 2/127/128 sparse+varied; marker selection by count+positional only; value-index resets; stream lengths crossing 127/128; P exactly 16_380 / 16_383 / 16_384 |
| U04 | `a5_u04_long_delegation_and_old_parser_compatibility` | adaptive == A3 for df 129/256/257 (both modes); `new_split` accepts small A3; adaptive rejects it only after the A3 parser succeeds; truncated A3 keeps its own error |
| U05 | `a5_u05_source_validation_order_is_preserved` | 12 invalid source shapes produce identical adaptive/legacy/split errors; doubly invalid input keeps the first rule |
| U06 | `a5_u06_compact_framing_is_canonical_and_bounded` | marker/version, header truncation, overlong/>u64 varints, counts 0/1/129, count>docs, `freq_total<count`, short D/F, doc-only P, positional P minimum and overflow, extent overflow/short/long |
| U07 | `a5_u07_lazy_full_and_lean_parity` | doc delta 0, doc-add overflow, range, zero/invalid frequency, repeated/overflowing position, zero length, decreasing value index, reversed offsets, truncated/non-canonical occurrence varints, clean-then-corrupt second posting |
| U08 | `a5_u08_cancellation_advance_and_conversion` | cancellation before first/next/final/after EOF, stable repeated EOF, `advance` across postings, cached-target advance with a cancelled flag, conversion then lean next |
| U09 | `a5_u09_resource_limits_and_incremental_charging` | encoded total at/one-below the allocation limit, `max_decoded_entries=1` on df2, frequency at/over the decoded limit, occurrence allocation at/one-below the bound in both modes, forged A3 `u64::MAX` count still enforces `max_postings_per_term` |
| U10 | `a5_u10_decode_and_conversion_witnesses` | full/lean reserve+clone witnesses, conversion after a full read continues at the next posting |
| U11 | `a5_u11_frequency_totals_and_stream_tails` | header/body frequency disagreement fails at EOF, ordered doc/frequency/position trailing-byte errors, bounded observed-sum overflow with `max_decoded_entries=u64::MAX`, legacy EOF unchanged |
| U12 | `a5_u12_required_feature_matrix_and_extent_errors` | required/optional matrix, E+F conflict only per segment, pair absence vs single-section `MissingSection`, dictionary `df` mismatch, extent errors, separate E and F readers |
| U13 | `a5_u13_structural_size_table_and_determinism` | exact six-row size table, determinism, record preservation, compact strictly smaller at `df<=128`, long identity |
| U14 | `a5_u14_generated_differential_across_all_families` | 64 deterministic LCG cases: counts `[1,2,3,127,128,129,256,257]` × doc-only/positional × bases `[0,127,128,16384]`; all three families encode/decode full+lean against the generator's records |
| U15 | `a5_u15_encoder_cost_witnesses` | validator/width/buffer counts and capacity invariants; zero compact work on the long path; no buffer for a rejected admission |
| U16 | `a5_u16_varint_width_and_checked_arithmetic` | width 0/1/127/128/16383/16384/`u64::MAX` → 1/1/1/2/2/3/10, checked total arithmetic near `u64::MAX`, header-width accounting on a real payload |

Retained codec suites: `--lib a2_` 22/22, `--lib a3_` 54/54,
`--test segment_codec` 28/28, `--test segment_golden` 4/4 (+1 ignored),
`--test pr07_compatibility` 15/15.

Literal wire fixtures (asserted byte-for-byte, produced by the real encoder and
compared to hand-authored arrays):

```
singleton doc-only:      04 01 01 01 01 00 00 01
singleton positional:    05 01 01 01 01 05 00 01 00 01 00 00 01
two-document doc-only:   06 01 02 02 02 02 00 00 01 01 01
two-document positional: 07 01 02 02 02 02 0a 00 01 01 01 00 01 00 00 01 00 01 00 00 01
```

---

## 8. Local vertical slices (real FsDirectory / real compaction)

All executed with `cargo +1.98.1 test -p quervant-core`.

| ID | Test(s) | Result |
| --- | --- | --- |
| I01 | `segment_codec::a5_i01_adaptive_segment_extents_and_corruption` | PASS — counts `[0,1,2,127,128,129,257]`; F present / E absent; singleton tag terms marker 5, dense terms 5/7/3, every extent contiguous and covering the body exactly; both public lookups and full/lean traversal match input-derived records and the `(0,1,0,0,5)` alpha occurrence; df2 position-length corruption in a digest-valid envelope yields `"zero position length"` while an unrelated tag stays readable. |
| I02 | `pr15i_d2a_scoring_contract::a5_i02_adaptive_fs_search_contract` | PASS — 259 docs, one segment requiring F; markers 5/7/3 for df 1/128/130; group key sets exactly the input ranges; alpha total 259 with independent statistics (646/516/1162); prefix and `And([alpha])` identical maps; phrase 194 and zeta 207 input-derived; absent term 0; K10/K100 explicit + relevance prefixes with exact bits; 3 cursor pages concatenate to the full 259-key result. |
| I03 | `pr15i_d2a_scoring_contract::a5_i03_fresh_process_reopens_adaptive` (parent) + `a5_i03_child_reopen_adaptive` (ignored child) | PASS — parent builds 64+65, compacts to generation 3, drops every handle, then spawns `current_exe()` with `QUERVANT_PERF06_A5_REOPEN_ROOT`; the child reopens, asserts generation 3, one F/no-E segment, markers 3/5/7, the full alpha key set and the exact frozen-formula score map, and exits successfully. |
| I04 | `segment_golden::a5_i04_adaptive_legacy_and_split_parity`, `segment_codec::a5_i04_feature_marker_combinations` | PASS — legacy golden vs explicit A3 vs adaptive agree on dictionary terms/df, full records, lean projection, stored values, norms and remap, with input-derived `hello`/`world` expectations; wrong feature/marker combinations behave as specified (compact-under-E rejected, long-under-E still valid, A3-singleton-under-F rejected). |
| I05 | `pr15i_d2a_scoring_contract::a5_i05_compaction_reclassifies_adaptive_terms`, `…boundary_128_stays_short`, `…after_delete_crosses_down`, `…stored_only_compaction_has_no_postings`, `…repeated_compaction_is_a_no_op`, `…compaction_limit_failure_preserves_generation` | PASS — see §8.1. |
| I06 | `pr07_compatibility::a5_i06_legacy_adaptive_commit_reopen_and_compact` | PASS — staged fixture hashes verified; generation 1 = 8 docs/2 legacy pre-norms segments with title:rust 4 and body:rust 6; generation 2 = 10 docs/3 segments (2 legacy + 1 F with norms), new segment title:rust df2 marker 7 and title:async df1 marker 5, totals 6/8 plus the OR oracle; one compaction → generation 3, 10 docs, 3 merged, one F/no-E segment with norms; held generation-1/2 pins reproduce their exact bits; the original manifest and both original segments stay byte-identical. |
| S01 | Structural sizes (§10) | PASS — recorded from `a5_u13` and the I01/I04 fixtures; no timing. |

### 8.1 I05 detail

* Generation 2: two compact input segments with alpha/common `df` 64 and 65
  (markers 7), zeta 51/52, unique `doc_id` singletons (marker 5).
* One public `writer.compact()` publishes generation 3 itself: `no_op=false`,
  `documents=129`, `segments_merged=2`. The writer's live reader immediately
  shows generation 3 with one segment.
* Fresh reopen: alpha and `grp:common` are long positional lists under F
  (markers 3, df 129); unique `doc_id` stays marker 5; zeta stays short
  (marker 7, df 103). Alpha total 129 / phrase 96 / zeta 103; exact frozen bits
  `frozen_scalar_bm25(tf,129,129,dl,577/129)` for every returned key, plus
  K10/K100 explicit and relevance ordering and the generic `And` fallback.
* The held generation-2 PIT repeats alpha/phrase/zeta bit-for-bit.
* 128-document sibling stays short after compaction; deleting `k00128` (129→128)
  keeps the survivors short with exactly the input set minus that key and an
  immutable pre-delete PIT; stored-only segments compact with no
  Dictionary/Postings/F/E sections; a second compaction on the clean compacted
  segment is a typed no-op and does not publish a generation.

### 8.2 I05 limit failure (`a5_i05_compaction_limit_failure_preserves_generation`)

Fixture: one indexed-**not-stored** `Text` field, 16 documents × 1,024 `alpha`
tokens, committed as 8+8. Input terms: `df 8`, `freq_total 8192`, `D 8`, `F 16`,
`P 57_000`, compact length **57_034** bytes; one posting's occurrence allocation
is `1_024 × 40 = 40_960` bytes. Reopening with
`SegmentLimits::default().with_max_single_allocation(65_536)` still opens the
index, creates a writer and serves a search (total 16, exact input keys, exact
frozen bits). Public compaction then returns exactly
`IndexError::Segment(SegmentError::LimitExceeded { limit: 65_536, requested: 114_059 })`
(merged term: `df 16`, `freq_total 16_384`, `D 16`, `F 32`, `P 114_000`,
11-byte header). `CURRENT` bytes are unchanged, the writer's live reader and the
held PIT still expose generation 2 / two segments / 16 matches with identical
bits, and a fresh default-limit reopen still sees generation 2.

---

## 9. Remote results (R01)

**Test:** `pr13_remote::real::a5_r01_adaptive_postings_rustfs_cold_reopen`
(`#[ignore]`, existing real-service pattern). Fixture: 259 documents
`a5-000..a5-258`, title `"<singleton|short|long> alpha beta"` when `i%4 != 0`
else `"… alpha gamma"`. Commit → drop the writer and the creating handle → fresh
`RemoteIndex::open_existing` (generation 1, one F/no-E segment, markers 5/7/3) →
delete only this configuration's disposable `workspace_root` → open again from
the authoritative remote store and assert the same feature/mode classes, group
membership (`a5-000`, `a5-001..a5-128`, `a5-129..a5-258`), alpha 259, beta 194,
gamma 65, absent 0, and phrase `alpha beta` = exactly the 194 input-derived keys,
using a local `TopK300` helper for full-set equality.

**Environment.** The local host had no `QUERVANT_RUSTFS_*` environment, no
service on `127.0.0.1:9000` and no running container, so no local service was
started (`D29` forbids starting an unapproved provider). The prescribed local
command was executed and failed at the harness gate, not at the codec:

```
cargo +1.98.1 test -p quervant-core --all-features --test pr13_remote \
  real::a5_r01_adaptive_postings_rustfs_cold_reopen -- --ignored --exact --test-threads=1
→ panicked: QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance: NotPresent
```

That failure is preserved as a diagnostic; it is not acceptance evidence.

**Hosted real-provider acceptance (actual).** The repository's authoritative
`rustfs` CI job starts the pinned RustFS image
(`rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
`http://127.0.0.1:9000`, region `us-east-1`, disposable bucket, production
`S3ObjectStore`) and runs the encompassing ignored suite:

```
cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1
```

Observed job log for head `9283344` (run
[45333872681](https://github.com/yduchesne/quervant/actions/runs/45333872681),
job `rustfs`):

```
test real::a5_r01_adaptive_postings_rustfs_cold_reopen ... ok
test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out
```

The job also completed the rest of the pinned remote topology (Oracle/fault-proxy,
crash/recovery and mutation/race suites) with no failures; the `rustfs` job
conclusion is `success`. No fake ObjectStore was substituted, no topology,
credential or retry policy was changed, and no additional container was started
by this task.

---

## 10. Structural sizes (measured fixtures, untimed)

Term payload lengths asserted in `a5_u13` (bytes):

| n | legacy doc-only | A3 doc-only | **A5 doc-only** | legacy positional | A3 positional | **A5 positional** |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 19 | 98 | **8** | 24 | 103 | **13** |
| 2 | 21 | 100 | **11** | 31 | 110 | **21** |
| 127 | 271 | 350 | **261** | 906 | 985 | **897** |
| 128 | 273 | 352 | **267** | 913 | 992 | **908** |
| 129 | 275 | 395 | **395** | 920 | 1040 | **1040** |
| 257 | 531 | 692 | **692** | 1816 | 1977 | **1977** |

Complete adaptive containers from `a5_i01` (real `SegmentBuilder`,
`test_schema`: body text, unique keyword tag, multi-keyword tags plus stored
fields):

| docs | segment bytes | Dictionary bytes | Postings bytes |
| ---: | ---: | ---: | ---: |
| 1 | 2_808 | 165 | 52 |
| 2 | 3_111 | 203 | 89 |
| 127 | 40_571 | 4_953 | 4_342 |
| 128 | 40_882 | 4_991 | 4_388 |
| 129 | 41_736 | 5_029 | 4_798 |
| 257 | 80_113 | 9_893 | 9_401 |

Complete containers for the same two-document golden logical content
(`a5_i04`): pinned legacy-norms fixture **1_810** bytes, current adaptive
**1_799** bytes, explicit A3 reconstruction **2_248** bytes. The adaptive
container is smaller than the explicit A3 container for identical logical
content.

**Full-corpus projection — NOT MEASURED — A6 verification pending.** From the
A4-recorded A3 index bytes and the frozen 10K/100K corpus's `N+1` singleton
terms, the source model predicts:

| Corpus | Recorded A3 index bytes | Projected A5 bytes | Projected reduction |
| --- | ---: | ---: | ---: |
| 10,000 documents | 2_356_869 | 1_456_779 | 900_090 bytes (≈38.19%) |
| 100,000 documents | 23_713_222 | 14_713_132 | 9_000_090 bytes (≈37.95%) |

These are arithmetic projections under the stated corpus/schema/one-segment
assumptions. **No A5 benchmark-corpus index was built, and no size, latency, RSS
or writer-cost measurement is claimed.** A6 owns real index sizes and warm
qualification.

---

## 11. Final QA

All commands were run from the repository root after the last source/test change.

| Command | Result |
| --- | --- |
| `cargo +1.98.1 fmt --all -- --check` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.98.1 test --workspace --all-targets` | PASS — 2576 passed, 0 failed, 14 ignored |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | PASS — 2621 passed, 0 failed, 97 ignored |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **92.74% lines** (regions 87.56%, functions 93.26%) |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.31% lines** (regions 87.47%, functions 92.94%) |
| `cargo +1.98.1 doc --workspace --no-deps` | PASS (no warnings) |
| `cargo +1.98.1 doc --workspace --all-features --no-deps` | PASS (no warnings) |
| `cargo +1.98.1 bench --workspace --no-run` | PASS (compile only; no measurement) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2621 passed, 0 failed, 97 ignored |
| `git diff --check` | PASS |

Coverage scope is workspace production Rust with the repository's existing
exclusions only; no new exclusions, suppressions or floors were introduced. The
touched codec files measure (all-features): `segment/postings.rs` 90.03% lines,
`segment/reader.rs` 92.51%, `segment/build.rs` 91.06%,
`segment/format.rs` 92.95%, `index/merge.rs` 86.66%. The ignored tests are the
real-service suites plus the A5 child helper, which is executed by its parent.

**CI (as actually observed) on tested head `9283344`** — draft PR
[#124](https://github.com/yduchesne/quervant/pull/124), run
[45333872681](https://github.com/yduchesne/quervant/actions/runs/45333872681),
conclusion `success`:

| Job | Conclusion | Duration | Job URL |
| --- | --- | --- | --- |
| `rust` | pass | 21m30s | <https://github.com/yduchesne/quervant/actions/runs/45333872681/job/138241255851> |
| `msrv` | pass | 7m30s | <https://github.com/yduchesne/quervant/actions/runs/45333872681/job/138241255549> |
| `rustfs` | pass | 2m33s | <https://github.com/yduchesne/quervant/actions/runs/45333872681/job/138241255969> |
| `benchmark-adapter-contract` | pass | 1m38s | <https://github.com/yduchesne/quervant/actions/runs/45333872681/job/138241256022> |
| `python-benchmark-framework` | pass | 3m16s | <https://github.com/yduchesne/quervant/actions/runs/45333872681/job/138241256001> |

A report-only documentation commit follows this tested head (`D31`); the scoped
diff between the tested SHA and the final head is docs-only, so the local QA
above and the CI run above remain the source-test evidence for this PR. Final-head
CI state for the documentation-only delta is reported in the PR rather than
implied here.

---

## 12. Failures, diagnostics and classifications

| Item | Classification | Outcome |
| --- | --- | --- |
| `a3_u01`, `a3_u11`, `segment_codec::a3_i01`, `segment_codec::a3_i03`, `segment_golden::a3_i04` failing after the producer switch | Expected consequence of the prescribed writer change (`D09`) | Migrated to explicit A3 reconstruction; all pass; A3 coverage retained |
| `pr08_integration::p8_t42_golden_bytes_features_unchanged` | Expected closed allowlist (`D10`) | Added F to the known list and asserted F-present/E-absent; passes |
| A5 unit/integration authoring defects (wrong marker expectation for df2, header truncation range, positional fixture sizing, missing `P` parse, segment-order assumption, OR-key set, creating-handle generation) | Feature-implementation defect **in tests** (`D13`) | Tests corrected against the frozen contract; no contract change |
| Clippy `collapsible_if`, `field_reassign_with_default`, `bool_assert_comparison`, `identity_op`, `assertions_on_constants` | Lint defects (`D06`/`D13`) | Fixed within the approved files; clippy clean on stable and MSRV |
| One over-broad lazy-error conversion in the A3 split document branch | Prescribed-contract deviation (`D32`) | Reverted to the original `ok_or`; full QA rerun afterwards |
| R01 local run | Environment/harness failure (`D29`) | No local service/credentials; preserved as a diagnostic. G5 was closed by the hosted `rustfs` job, which executed the same test against the pinned real provider. |
| Nothing else | — | No deterministic preexisting failure and no nondeterminism observed |

No test was deleted, ignored, retried to green, relaxed or excluded to close a
gate.

---

## 13. Final adversarial review and residual risks

Plausible remaining violation paths and why they are excluded:

* **A compact term silently accepted under the wrong family.** Excluded: the
  family comes only from required features; U12/I04 prove compact-under-E,
  optional-F and E+F combinations fail closed, and there is no marker sniffing.
* **A tail or count accepted after the last posting.** Excluded: U11 asserts the
  ordered doc/frequency/position trailing errors after a successful read and the
  frequency-sum mismatch, and U06 forces extent/geometry failures at
  construction.
* **Decoded budgets charged eagerly by construction.** Excluded: U09 constructs
  under a 39-byte allocation budget and fails only at the second posting with
  `max_decoded_entries=1`.
* **Lean decoding skipping positional validation.** Excluded: U07 (identical
  full/lean errors) and U10 (zero occurrences/clones).
* **Compaction keeping its old encoder or an old feature tuple.** Excluded:
  `index/merge.rs` is the only compaction encoder call site and I05/I06 observe
  markers/features on the published output.
* **One-buffer claim satisfied by reserving then copying.** Excluded by the
  single-writer emission structure plus U15 capacity/count witnesses; the plan's
  outer caller copy into the segment body is explicitly unchanged and out of
  scope.
* **Historical evidence rewritten.** Excluded: §14 hash verification.

Approved residual risks (unchanged from the plan):

| Risk | Severity | Disposition / owner |
| --- | --- | --- |
| Warm-query latency and writer CPU/RSS | Material | Deferred to A6; A5 claims none |
| Actual 10K/100K complete-index sizes | Model-only | A6 measures and reconciles; A5 labels projections |
| Genuine complete **E** index appended/compacted by A5 | Bounded integration gap (`D39`) | A5 gate is real legacy+F lifecycle + explicit E coverage; **A6 must design and execute a genuine E+F lifecycle** |
| Old executable rejecting F | Source-derived only | Not executed; no old-binary claim |
| Real allocator exhaustion after a bounded reservation | Not deterministically reproducible | Fallible reservation and arithmetic/admission tested; no OOM injection |
| 32-bit host behaviour | CI hosts are 64-bit | Checked `usize` conversions plus bounded arithmetic tests; disclosed |
| Faults in unchanged publication protocols | No new mechanism | Existing local/remote failure suites remain mandatory |

No new self-approved waiver was introduced beyond the plan's `D39` bounded
acceptance.

---

## 14. Publication and integrity

* Tested source: `9283344712cafab6367efeea084dc7a7ca4a0c23`
  (`PERF-06-A5: compact small postings while retaining split long lists`).
* Branch: `dev/perf06-a5-adaptive-postings`; remote pushed without force.
* Draft PR: <https://github.com/yduchesne/quervant/pull/124> (separate from the
  merged A4 PR #123).
* CI for the tested source: run
  [45333872681](https://github.com/yduchesne/quervant/actions/runs/45333872681)
  — `rust`, `msrv`, `rustfs`, `benchmark-adapter-contract` and
  `python-benchmark-framework` all `pass`; conclusion `success`.
* This report is a documentation-only commit after the tested source (`D31`);
  the scoped diff between the tested SHA and the final head is docs-only and is
  verified before closeout.
* Protected evidence verified byte-identical after the work: both
  `benchmarks/studies/perf-06/warm/results/*.json` acquisitions, all A1–A4
  detailed plans/reports, all checked-in study configurations, every
  `tests/fixtures/**` file (including `golden.seg`, `golden_norms.seg` with
  SHA-256 `49f813a6…`, `json_paths_golden.seg`, the complete
  `pr07_pre_norms_v1` index and `m1/mutation_state_v1.bin`). Only the two
  authorized register files changed, by appending the current-status amendment.
* No merge, release, deployment, benchmark acquisition or messaging was
  performed.

---

## 15. Handoff to PERF-06-A6

Source accepted candidate for A6: `9283344712cafab6367efeea084dc7a7ca4a0c23`
(pending independent review; A6 must pin whatever head is actually accepted).

A6 owns these unanswered questions and must define its own protocol, source
pins, corpus/schema, result identity, acceptance criteria and acquisition count:

1. Does the frozen 10K/100K benchmark corpus produce the projected A5 index
   bytes at the accepted source?
2. What are the actual commit/reopen diagnostics and memory costs under a
   separately defined measurement?
3. Does cumulative A1–A3+A5 retain warm-query improvements and guardrails
   relative to an explicitly selected, comparable source?
4. Does a **genuine A3-produced complete E index**, appended and compacted by A5,
   pass native and required remote reopen/PIT/state-pointer correctness? (A5
   could not: no genuine E fixture exists in the inspected fixture set — `D39`.)
5. What is the maintainer's baseline/adoption decision before B1?

A6 must **not** retune A4's declared 5% target, reuse the A4 study UUID, or treat
this report's projections as measurements. B1 (persistent keyword ordinals)
remains blocked pending A6 evidence and maintainer disposition.
