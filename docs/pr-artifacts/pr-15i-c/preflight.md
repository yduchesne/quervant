# PR 15I-C — Preflight and source reconciliation

Status: `PREFLIGHT_COMPLETE`
Recorded: 2026-11-08

## 1. Source identity

| Item | Value |
|---|---|
| `BASE_CONTENT_SHA` (assumed-merged PR 15I-B) | `f70cde62e709383d82693ad548a8c69c7f772bef` |
| `LAST_15IB_PRODUCTION_SHA` | `9da20614f58313259fcceb5ff8fa997e6afc7d7c` |
| `P0_15IA_SHA` | `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb` |
| Effective checked-out source (`dev/pr15i-c-postings`) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| Effective source tree SHA | `884f52278766d515c4f4f65d53ca23983ceab0c0` |
| `BASE_CONTENT_SHA` tree SHA | identical tree object (`git diff --quiet f70cde6 HEAD` empty) |

`6f6463cb` is the real merge commit of `dev/pr15i-b-stored-blocks` (PR #90). Its
complete content tree for every relevant production and benchmark path is
byte-identical to `f70cde62`, verified with:

```sh
git diff --name-status f70cde62e709383d82693ad548a8c69c7f772bef HEAD -- \
  crates/quervant-core/src crates/quervant-core/tests benchmarks/pr15d \
  benchmarks/pr15i_b docs/pr-artifacts/pr-15i-0
# empty
```

Decision-log entries: **C-D01** (current main includes identical relevant content
to complete 15I-B, so pin the real merge content SHA as BASE) and **C-D05**
(branch `dev/pr15i-c-postings` already exists with clean ancestry at exactly the
effective merged-15I-B base and no candidate work, so it is continued rather than
creating a second branch).

`EFFECTIVE_MAIN_ASSUMED_15IB` applies: this branch is based on the complete
15I-B content tree, never on the earlier PR 15I-A `main`.

## 2. Protected-path manifest

SHA-256 of the `git ls-tree -r` listing of all protected paths at
`BASE_CONTENT_SHA`:

```
a3768db375ff7d1e15a897abd0b6eca167ccec09fe8de7a914b81edf93d6e867
```

Scope: `crates/quervant-core/src`, `crates/quervant-core/tests`,
`benchmarks/pr15d`, `benchmarks/pr15i_b`, `docs/pr-artifacts/pr-15i-0`.

## 3. Working tree and toolchain

| Check | Result |
|---|---|
| `git status --porcelain=v1 --untracked-files=all` | clean |
| `git diff --check` | clean (`DIFFCHECK_OK`) |
| Native filesystem of worktree | `ext2/ext3` (WSL2 ext4 virtual disk on `/dev/sdd`) |
| `rustc --version` | `rustc 1.98.1 (48a229cea 2026-09-01)` |
| `cargo --version` | `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| `cargo +1.85.0 --version` | `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| `python3 --version` | `Python 3.12.3` |
| CPU count | 12 |
| Kernel | `Linux 6.18.33.2-microsoft-standard-WSL2 x86_64` |

## 4. Symbol and behavior checks against §1.1

All required symbols exist with the pinned signatures/semantics:

| Area | Symbol / contract | Verified |
|---|---|---|
| `search/unified.rs` | `UnifiedSearcher::collect_mixed`, `execute_unified`, `single_term_postings_eligible` | yes |
| `search/unified.rs` | `MixedEntry` bound `K+1`, `candidate_charge`, `heap_admit_candidate`, `consider_borrowed_keyword_candidate`, `keyword_sort_late_eligible` | yes |
| `search/execute.rs` | `build_leaf_data`, `evaluate_lexical_with`, `effective_live_examination_count`, `score_segment`, `SegmentCandidateLedger`, `CandidateBudget`, `TermPostings`, `LeafData` | yes |
| `search/execute.rs` | `SET_BYTES_PER_ENTRY = 48`, `SCORED_MAP_BYTES_PER_ENTRY = 64`, `TERM_POSTING_BYTES = 16`, `bytes_for_count` | yes |
| `search/unified_plan.rs` | `UnifiedPlan` root `UnifiedNode::Lexical(0)`, `CompiledLeaf::Term { terms }`, positive terms, typed leaves | yes |
| `search/score.rs` | `score::bm25(tf, df, n, dl, avgdl)`, `SnapshotStats::field`, `FieldStats::{length, doc_freq, n, avgdl}` | yes |
| `search/typed_compare.rs` | `ColumnAccess::open`, `keyword_sort_view`, `sort_tuple_for_doc`, `compare_candidates`, `compare_borrowed_keyword_to_owned` | yes |
| `search/work.rs` | `MixedWorkMeter` charges `1+freq` scanned occurrences, `charge_lexical`, `check_cancelled` | yes |
| `segment/postings.rs` | `PostingsReader::next_with` checked monotone decoding | yes |
| `benchmarks/pr15d/harness/run.py` | `measure_lane`, `lane_descriptors`, `prepare_corpus`, frozen 9 warm lanes (`benchmarks/pr15e_b1/run_targeted.py::stage_lanes`) | yes |

No material signature deviation was found, so matrix **C-D06** (reuse the accepted
`single_term_postings_eligible`) and **C-D07** (existing ledger API unchanged)
apply. There is no C-D03/C-D04/C-D07/C-D08 STOP trigger.

## 5. Baseline executable QA (pre-change, `BASE_CONTENT_SHA` content)

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo +1.85.0 check --locked -p quervant-core` | 0 | PASS |
| `cargo test --locked -p quervant-core --lib search::unified::phase4_tests` | 0 | 8 passed, 0 failed |
| `cargo test --locked -p quervant-core --lib search::unified::b_tests` | 0 | 6 passed, 0 failed |
| `cargo test --locked -p quervant-core --lib search::execute::budget_tests` | 0 | 40 passed, 0 failed |
| `python3 -m unittest discover -s benchmarks/pr15d/harness -p 'test_*.py'` | 0 | 139 tests OK |
| `python3 -m unittest discover -s benchmarks/pr15i_b -p 'test_*.py'` | 0 | 10 tests OK |
| `bash benchmarks/scripts/test-scripts.sh` | 0 | 108 passed, 0 failed |
| `git diff --check` | 0 | clean |

No pre-existing failures. The full workspace QA runs once at the final settled
candidate/rollback tree (§9.4), not at each micro-fix.

## 6. Qualified frozen benchmark fixture checks

- Frozen PR15D corpus schema: `pr15d-corpus-v1`.
- Frozen lanes come from `benchmarks/pr15e_b1/run_targeted.py::stage_lanes("final")`
  and are asserted equal to the nine-lane list in `benchmarks/pr15i_c/protocol.json`.
- Frozen PR15D adapter (`benchmarks/pr15d/adapters/quervant`) is used unmodified;
  its lockfile is `--locked --offline`.
- The 100K 15I-B LZ4 sentinel from the rejected/qualified 15I-B evidence
  (`15,747,551` committed bytes, `1,661,455` STORED bytes) is treated as a
  historical cross-check only. Fresh A/B index equality and source proof are
  authoritative for 15I-C.

## 7. Next authorized stage

C1 (correctness design gate) proceeds automatically per C-D47.
