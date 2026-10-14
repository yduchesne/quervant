# PR 7 Amendment 02 preflight — candidate reservation lifetimes

**Branch:** `dev/lexical-postings`
**Starting commit:** `161cf5ebce28c6425ae1b803384e876ac9254d78` (PR 7 Amendment 01)
**Base `main`:** `4f603ce1c0dafd994918bb5291d4b0584d9f001c` (unchanged from the PR 7 base)
**Working tree at preflight:** clean.
**Toolchains:** stable 1.98.1 and MSRV 1.85.0 (`rust-toolchain.toml` channel `stable`, `rust-version = 1.85`).

The branch HEAD matches the plan's inspected `161cf5e` contracts; no material
drift. No STOP condition is triggered.

## Baseline gate evidence (re-executed)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | 980 passed, 7 ignored, 0 failed |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | 91.90% line |

## Confirmed defects at `161cf5e`

1. **Phrase scratch never released.** `build_phrase` reserved `distinct` docs and
   occurrences but dropped `distinct` without releasing; later sibling phrase
   leaves and the segment peak were overcharged until `ledger.finish()`.
2. **Transfer gap.** `execute_segment` called `ledger.finish()` (bulk-releasing
   the still-live output vector) before the caller re-reserved the batch as
   global. The vector briefly existed with no live reservation.
3. **Implicit bulk release.** `live_set`, `leaf_data`, `matches` and `scored` were
   not explicitly released at their drop points; `finish()` released whatever
   remained, inflating the per-segment peak.

## Allocation ownership / charge / drop / transfer table

| Collection | Constructor | Charge site | Owner | Last use | Drop site | Release / transfer |
|---|---|---|---|---|---|---|
| `live_set: BTreeSet<u64>` | `execute_segment_inner` | `reserve(live_count, 48/entry)` | segment inner | `eval_node` | explicit `drop` after eval | `ledger.release(live)` |
| term posting `Vec<(u64,u64)>` | `build_leaf_data` | `reserve(1, 16)` per live posting | `leaf_data` | `score_segment` | with `leaf_data` | `ledger.release(leaf_charges)` |
| phrase scratch (`distinct` docs + occurrences) | `build_phrase` | `reserve` before append/insert | `build_phrase` local | `match_phrase` | explicit `drop(distinct)` | `ledger.release(scratch)` before returning |
| phrase match output | `build_phrase` | worst-case reserve, unused released | `leaf_data` | `score_segment` | with `leaf_data` | aggregated in `leaf_charges` |
| boolean `ReservedSet` (leaf/And/Or/Not) | `eval_node` | reserve upper bound before build; release unused | segment inner | `score_segment` (`matches`) | `ReservedSet::release` drops `set` first | `ledger.release(entries)` |
| scored `BTreeMap<u64,f64>` | `score_segment` | reserve before build | segment inner | doc-id→key loop | consumed by the loop | `ledger.release(scored_charges)` |
| output `Vec<(DocumentKey,f64)>` | `execute_segment_inner` | `reserve(1, 96+len)` per key before push | segment inner | `execute_segment` transfer | moved into `SegmentResults` | `ledger.transfer_to_global` |
| global result `BTreeMap<DocumentKey,f64>` | `execute_search` | none (batch already global-charged) | `execute_search` | top-K | end of request | request-scoped budget dropped |
| top-K heap | `execute_search` | `TopKSelector` own byte budget | `execute_search` | `finish` | dropped | n/a |

## Counterexamples

- **A2-02 (scratch):** one document `x y p q`; `OR(Phrase(x,y), Phrase(p,q))` with
  `max_segment_candidate_entries = 9`. Corrected peak retains only the two match
  reservations and succeeds; `161cf5e` retains both scratch sets and returns
  `ResourceLimit`.
- **A2-10 (implicit bulk release):** eight single-document segments, `MatchAll`,
  `max_segment_candidate_entries = 2`. Corrected per-segment peak is 2; `161cf5e`'s
  peak is 3 because the scored map coexists with the live set and match clone.
- **A2-01 (transfer gap):** the end-to-end acceptance boundary is dominated by the
  segment-charge checks (which are identical before and after), so a public-API
  test cannot distinguish the transient uncharged batch. Per the plan's
  feasibility rule, this is covered by the private `a2_01_*`/`a2_04_*` unit tests
  on `transfer_segment_to_global`, with the reasoning recorded in the review.

## Invariant → test mapping

| Invariant | Tests |
|---|---|
| INV-A2-01 batch always charged | `execute::budget_tests::a2_01_*`, `a2_05_*` |
| INV-A2-02 global+segment bound | `a2_03`, `a2_05`, `a2_10` |
| INV-A2-03 scratch released at death | `a2_02` (fails on base) |
| INV-A2-04 one charge per retained collection | `a2_08`, `a2_10` (fails on base) |
| INV-A2-05 rejected ops atomic | `a2_04`, `a2_09` |
| INV-A2-06 per-segment reset | `a2_10` |
| INV-A2-07 semantics unchanged | `a2_11`, `a2_12`, all existing suites |
| INV-A2-08 work/scanned/cancellation | `a2_09` |

## Scope confirmation

No public `SearchLimits`, codec/format, storage, writer/reader lifecycle,
analyzer/phrase-position, BM25 or positive-leaf change. No new dependencies or
unsafe code. The residual `match_phrase` internal scratch-vector risk remains.
