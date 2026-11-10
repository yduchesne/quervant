# PR 15I-C — Applied decision-matrix rules

Every entry records the observable trigger, the chosen response and the evidence.
No rule was used to change a format, threshold, budget semantic, scoring rounding,
public API or benchmark schedule.

| Rule | Trigger (observed) | Response | Evidence |
|---|---|---|---|
| `C-D01` | Checked-out branch was exactly the real merge commit `6f6463cb` of PR 15I-B, byte-identical to `f70cde6` | Pinned the effective merged content as `BASE_CONTENT_SHA` and recorded both SHAs | `preflight.md` §1 |
| `C-D05` | `dev/pr15i-c-postings` already existed with clean ancestry at exactly the effective base and no candidate work | Continued that branch instead of creating a second one | `preflight.md` §1 |
| `C-D06` | Accepted `single_term_postings_eligible` present and matching the pinned source facts | Reused it unchanged; the new predicate is strictly narrower | `unified.rs`, `C-U03` |
| `C-D07` | `build_leaf_data` / `SegmentCandidateLedger` APIs matched the pinned source | Reused them; no new ledger or charging scheme | `execute.rs`, `C-U15…C-U22` |
| `C-D08` | `bm25` and `SnapshotStats` matched the pinned formula | Reused the exact function and field stats | `C-U09`, `C-U34` |
| `C-D09` | Frozen PR15D adapter has an ascending single columnar `Keyword` `doc_id` sort | Asserted eligibility from the compiled schema in a source test | `C-U01`, `C-U36` |
| `C-D11` | `C-U12` exercises a `label` sort field instead of `doc_id` | Kept it eligible; no literal field-name requirement | `C-U12` |
| `C-D12` | Sort column deliberately unequal to the logical key (`C-U10`, `C-I04`) | Kept the canonical borrowed-Keyword comparator; no value/key substitution | `C-U10`, `C-U32`, `C-I04` |
| `C-D13`/`C-D14` | Descending/numeric/two-field sorts, relevance, cursor, aggregation, batch, multi-segment | Generic path only; no eligibility widening and no compaction on read | `C-U03`, `C-U26`, `C-I06`, `C-I07` |
| `C-D15` | One segment with retention deletes | Fast path when the shape held; original effective-live filtered postings | `C-U07`, `C-I08` |
| `C-D18` | Zero postings (`C-U13`) | Modelled zero matched/scored charges, charged per-live work, zero hits | `C-U13` |
| `C-D19` | Postings already decoded, monotone and live-filtered | Used the vector in place: no copy, sort, re-decode or second reader | `C-U04`, `C-U29` |
| `C-D23`/`C-D24` | Physical trees removed | Kept the virtual legacy matched/64-byte scored reservations before any key/heap work | `C-U15`, `C-U21`, `C-U22` |
| `C-D26` | `FieldStats` absent (`C-U20`) | Emitted exactly `0.0` | `C-U20` |
| `C-D29` | Complete score pass produced for all `M` | Released temporaries, then visited all candidates; no early stop after K | `C-U05`, `C-U19`, `C-U40` |
| `C-D32`/`C-D33` | `M == 1 && doc_count >= 1024` vs otherwise | Kept the legacy `doc_key_selected` / `doc_key` split keyed off the real match count | `C-I01`…`C-I03` |
| `C-D34`/`C-D35` | `LegacyDecode` view and corrupt losing values | Called the unchanged owned-tuple fallback; validation stays before rejection | pre-existing `b_fixup_…` test, `C-U24` |
| `C-D39` | The plan asks for an *external* probe binary but says to keep the accessor private to `search` | Made `search::probe` `#[doc(hidden)] pub` **only** behind the non-default `pr15ic-probe` feature, and registered it with a one-line `pub use` in `search/mod.rs`; default builds contain no probe symbol | `strings … \| grep -c open_and_live_ns` → 0 |
| `C-D42` | Stage profile showed matched/scored structures were a large share of `100K` common | Reported the measured attribution without inventing new optimizations | `diagnostic-stage-profile.md` |
| `C-D43` | Protocol fixed before measurement | `protocol.json` written and committed before the campaign; SHA pinned in the manifest | `source-and-binary-proof.md` |
| `C-D47` | Changes confined to the allowlist and MSRV-clean | Ran unit, differential, budget and integration tests without asking for stage permissions | `correctness-and-qa.md` |
| `C-D48` | A/B fresh index layouts and segment digests were identical | Continued the same-format trial | `raw/sizes.json`, verifier §4 |
| `C-D52` | All required local correctness gates passed | Ran the full 16-slot campaign autonomously on the assumed-idle host | `raw/slots/*` |
| `C-D57` | Frozen PR15D adapter lockfile cannot be used with `--locked` at the pinned base | Built the arm adapters with `cargo build --release --offline` exactly as the accepted PR15I-B controller does, and recorded binary + source hashes | `source-and-binary-proof.md` §4 |
| `C-D58` | Controller and verifier initially disagreed on gate key names | Fixed the verifier to compare only the four frozen `C-Pxx` keys and to keep per-lane verdicts independent; both then agreed | `verify.py`, `test_verify.py` |
| `C-D59`/`C-D61` | Primary medians below 0.90 and blocks below 1.15 | Recorded PASS; no threshold change | `performance-decision.md` |
| `C-D62` | Four non-primary medians above 1.05 | Recorded `C-P09` FAIL; candidate ineligible; refused to average or drop lanes | `performance-decision.md` |
| `C-D63` | Performance failure but no correctness failure | Did **not** waive correctness; preserved every passing correctness artefact | `correctness-and-qa.md` |
| `C-D65` | Valid performance failure with valid correctness/source/provenance | Prescribed additive rollback to A production, preserved negative raw, ran final QA | `execution-status.md` |
| `C-D69` | No container runtime on the host (`docker` absent) | Marked `C-P13` **BLOCKED**; did not substitute a fake ObjectStore | `correctness-and-qa.md` §4 |
| `C-D73` | No push/PR/merge authorization | Committed locally only; no push, no PR, no merge | final report |
| `C-D74` | Hosted CI not run | Reported `HOSTED_CI_PENDING` separately from local results | final report |
