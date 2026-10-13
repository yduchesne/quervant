# PR 5 implementation preflight

> **Status:** PRE-IMPLEMENTATION GATE PASSED except where noted. F01–F12 approved
> and frozen at `111e464`; implementation authorized. No merge.

## 1. Approval verification

| Item | Value |
|---|---|
| Approved source revision | `111e464a74b0664c005c5f2adc2b0cd66ffb28b6` |
| Approval-record commit | `84ed70ba775836be98831f5442e4e6a3ddd97b75` |
| Local `HEAD` after fetch/ff | `84ed70ba775836be98831f5442e4e6a3ddd97b75` |
| `origin/dev/segment-codecs` | `84ed70ba775836be98831f5442e4e6a3ddd97b75` |
| `origin/main` | `a23cf25798e52fc181e93ac84505a07412f37463` |
| Fast-forward relationship | `525404e` (agent amendment) → `189b2c1` → `73fbcc9` → `111e464` → `de402b4` → `84ed70b`; local fast-forwarded, no divergence, no reset/rebase |
| Format approval record | `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md` status **APPROVED — FORMAT FROZEN**; F01–F12 table complete; approved SHA recorded |

The approved decision document, the five clarification/approval commits, and the
previously authored amendment artifacts were all present and preserved.

## 2. Contract reconciliation (PR 2–4)

| Dependency | Status | Notes |
|---|---|---|
| PR 2 contracts | present | `contract::{schema,document,value,budget,capability,error}` match the approved spec |
| PR 3 storage | present | `Directory`, `ReadHandle::read_at`/`len`, `WriteHandle::write_all`/`sync_all`, `StorageKey`, `SegmentId`, `SegmentDescriptor`; `trawler_objectstore::digest::ContentDescriptor` `(length, digest)` |
| PR 4 analysis | present | `Token` (term, `value_index`, `position`, `position_increment`, `position_length`, `start/end_offset`), `AnalyzerRegistry`, `SchemaAnalyzerBindings`, `AnalyzerDefinition::collect_tokens`, `AnalyzerFingerprint` |
| PR 4 merge ancestry | present | `9bc042d` ancestor of `HEAD` |
| Existing PR 5 code | **none** | no `crates/trawler-core/src/segment/` directory; nothing to duplicate |

No contract contradiction with the frozen format was found.

## 3. Approved format clarifications incorporated

The five post-amendment commits clarified: (a) PR 3 whole-file `ContentDescriptor`
digest covers the trailer while the F02 `envelope_digest` excludes it, and the two
must never be compared; (b) `posting_doc_count` is distinct from segment
`doc_count`; (c) column `block_docs` is persisted and validated, not a runtime
default; (d) v1 dictionary lookup is sequential/work-budgeted with no
binary-search claim; (e) P5-A21–P5-A23 added. All are reflected in this
implementation.

## 4. Baseline QA (fresh runs on approved HEAD `84ed70b`)

Toolchain `rustc 1.85.0 (4d91de4e4 2025-02-17)`, workspace root.

| Gate | Command | Exit | Result |
|---|---|---|---|
| Check | `cargo +1.85.0 check --workspace --all-targets` | 0 | PASS |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS — 639 passed / 0 failed / 1 ignored |
| Format | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| Lint | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | 0 | PASS |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS — TOTAL 87.74% line / 91.19% function / 94.63% region |

## 5. Correctness-matrix ownership

`docs/pr-artifacts/pr-5/correctness-matrix.md` maps INV01–INV14 and the complete
P5-U / P5-I / P5-G / P5-P / P5-A01–A23 suites to source paths, plan steps, positive
and adversarial tests, and evidence status. All new cases are explicitly
**PLANNED** until executed. The pre-existing `docs/TESTING.md` conflict markers
(lines 56–59) remain unfixed and out of PR 5 scope.

## 6. Phase oracle check

| Phase | Positive oracle | Negative oracle |
|---|---|---|
| A | container decode of independently known bytes; digest/version checks | corrupt magic/footer/trailer/digest/overlap/truncation |
| B | five-state + typed round-trip vs hand-authored table | duplicate ids, invalid type/cardinality, fingerprint mismatch, oversized counts |
| C | postings vs independent sorted-doc oracle; `next`/`advance` monotonicity | non-monotone/duplicate/out-of-range doc ids, malformed varints |
| D | bijective remap vs oracle; conservative bounds vs predicate table | non-bijective remap, dateline/partial-presence false-negative attempts |
| E | real `MemoryDirectory`/fresh `FsDirectory` reopen; committed golden decode | tamper/truncate/partial-write/sync-failure/orphan |

## 7. Gate outcome

**PASS.** No STOP condition is present. Proceeding to Phases A–E in the detailed
plan order, with all mandatory local checks re-run on the final SHA.
