# PR 7 Amendment 03 preflight — transactional ledger and bounded phrase scratch

**Branch:** `dev/lexical-postings`
**Inspected/starting commit:** `66b512bd737af5dfb25cbf258be22c999a3eb76c` (Amendment 02)
**Base `main`:** `4f603ce1c0dafd994918bb5291d4b0584d9f001c` (unchanged)
**Working tree at preflight:** clean.
**Environment:** Linux 6.18.33.2-microsoft-standard-WSL2 x86_64, Intel(R)
Core(TM) i7-10750H @ 2.60GHz, 12 logical CPUs; stable Rust 1.98.1 and MSRV Rust
1.85.0; `cargo-llvm-cov 0.9.1`. Date: 2026-10-14.

The branch HEAD matches the plan's inspected `66b512b` contracts; no material
drift. No STOP condition triggered.

## Baseline gates (re-executed on `66b512b`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | 991 passed, 7 ignored, 0 failed |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | 91.97% line |

## Confirmed defects at `66b512b`

1. **Budget-first ledger mutation.** `SegmentCandidateLedger::{reserve,release,
   transfer_to_global}` mutated `CandidateBudget` first, then performed checked
   arithmetic on the ledger-local counters. A rejected second stage left the
   budget mutated.
2. **Non-atomic direct release.** `CandidateBudget::release_segment` subtracted
   `segment_entries` before validating the `segment_bytes` subtraction.
3. **Uncharged phrase-verification scratch.** `phrase.rs::match_phrase` allocated
   `distinct`, `candidates`, `token_occurrences`, and `phrase_chains::{current,
   advanced}` without charging their peak against the candidate budget. Only
   `build_phrase`'s outer postings/match reservations were charged.

## Allocation charge/drop ownership matrix (post-Amendment 03)

| Collection | Constructor | Charge site | Owner | Drop site | Release / transfer |
|---|---|---|---|---|---|
| `live_set` | `execute_segment_inner` | `ledger.reserve` | segment inner | after `eval_node` | `ledger.release` |
| term postings | `build_leaf_data` | `ledger.reserve` per posting | `leaf_data` | with `leaf_data` | `leaf_charges` release |
| outer phrase postings scratch | `build_phrase` | `ledger.reserve` | `build_phrase` | `drop(distinct)` | `ledger.release(scratch)` |
| phrase-match output (`matches`, `term_freqs`) | `build_phrase`/`match_phrase` | caller worst-case `ledger.reserve` | `leaf_data` | with `leaf_data` | `leaf_charges` (not charged again) |
| `distinct`, `candidates`, `intersect` result | `match_phrase` | `PhraseScratch::reserve` | `PhraseScratch` | explicit `drop` | `scratch.release` |
| `token_occurrences` | `match_phrase` | `PhraseScratch::reserve` | `PhraseScratch` | explicit `drop` | `scratch.release` |
| `phrase_chains::{current,advanced}` | `phrase_chains` | `PhraseScratch::reserve` | `PhraseScratch` | explicit `drop` | `scratch.release` |
| boolean `ReservedSet` | `eval_node` | `ledger.reserve` | segment inner | `ReservedSet::release` | `ledger.release` |
| scored map | `score_segment` | `ledger.reserve` | segment inner | consumed | `scored_charges` release |
| output batch | `execute_segment_inner` | `ledger.reserve` | segment inner | `SegmentResults` | `transfer_to_global` |
| global results | `execute_search` | batch already global | `execute_search` | end of request | request-scoped |

All scratch charges are **logical units**, not RSS or `Vec` capacity.

## Red-test evidence

- **Transactional:** T01–T04 (and T07/T08) were added to `execute.rs::budget_tests`
  before the fix and failed on `66b512b`; T05/T06 already passed. After the fix,
  all T01–T08 pass.
- **Phrase scratch:** `p01_chain_reference_scratch_is_charged` (in
  `tests/pr07_amendment03.rs`, public API only) fails on `66b512b` in a detached
  worktree and passes after. P02–P12 pass on both (guards / new-contract tests).

## Invariant → test mapping

| Invariant | Tests |
|---|---|
| T01–T04 atomic transitions | `budget_tests::t01`–`t04` |
| T05 overflow, T06 boundary, T07 model, T08 Drop | `budget_tests::t05`–`t08` |
| P01 chain refs charged | `pr07_amendment03::p01` (red on base) |
| P02 intersection peak, P03 long repeated | `p02`, `p03` |
| P04 sibling release, P11 degenerate | `p04`, `p11` |
| P05 combined global+segment+scratch | `p05` |
| P06 error cleanup, P07 cancellation | `p06`, `p07` |
| P08 semantics oracle, P09 memory/Fs parity | `p08`, `p09` |
| P10 seeded membership+scores, P12 long terms | `p10`, `p12` |
| Scratch residue zero | `phrase::tests::phrase_scratch_returns_to_zero` |

## Scope confirmation

No public API, `SearchLimits`, `SearchError` variant, codec/format, storage,
phrase position semantics, BM25, positive-leaf policy, top-K ordering or
dependency changes. No `unsafe`. Local-only topology.
