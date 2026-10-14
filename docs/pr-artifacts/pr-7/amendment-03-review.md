# PR 7 Amendment 03 review

**Scope:** transactional candidate-ledger transitions and bounded phrase scratch.
**Branch:** `dev/lexical-postings`; starting commit `66b512b` (Amendment 02).
**Disposition:** amend the existing PR 7 branch; not a separate roadmap PR.

## Corrections delivered

| Item | Defect | Fix | Files |
|---|---|---|---|
| 1 | Ledger mutated the budget before validating ledger-local counters | `LedgerState` + pure `checked_{reserve,release,transfer}` + single `commit`; consistency preflight | `search/execute.rs` |
| 2 | `release_segment` subtracted entries before validating bytes | Validate both subtractions into locals, then assign | `search/execute.rs` |
| 3 | `match_phrase` internal vectors were uncharged | `PhraseScratch` scoped owner; fixed-capacity reserves for `distinct`, `candidates`, intersection, `token_occurrences`, `phrase_chains::{current,advanced}` | `search/{execute,phrase}.rs` |

## Invariant evidence

- **T01–T04:** fail on `66b512b` (recorded before the fix), pass after.
- **T05–T08:** overflow boundary, valid sequence, 300-op seeded tuple model,
  Drop/injected-inconsistency; pass.
- **P01:** `p01_chain_reference_scratch_is_charged` fails on `66b512b` in a
  detached worktree and passes after (internal chain references now charged).
- **P02–P12:** intersection peak, long repeated chain, sibling release, combined
  global+segment+scratch bound, error/cancellation cleanup, multi-value oracle,
  memory/Fs parity, 200-case seeded membership+score oracle (`0xA303`), degenerate
  phrases, long terms; pass.
- **Scratch residue:** `phrase::tests::phrase_scratch_returns_to_zero` asserts
  zero outstanding scratch after success, no-match and empty phrases.
- **R01:** all existing PR 7 / Amendment 01 / Amendment 02 suites remain green
  (only the Amendment 02 sibling boundary test was updated for the new internal
  scratch charges).

## Red-test evidence

Detached worktree at `66b512b`:

```text
T01 t01_direct_release_is_atomic_on_mixed_underflow ... FAILED
T02 t02_ledger_release_preflights_before_budget_mutation ... FAILED
T03 t03_transfer_preflights_ledger_state ... FAILED
T04 t04_reserve_preflights_ledger_state ... FAILED
T07 t07_seeded_transactions_match_tuple_model ... FAILED
T08 t08_drop_cleanup_and_injected_inconsistency ... FAILED

p01_chain_reference_scratch_is_charged ... FAILED
(11 other pr07_amendment03 tests ok)
```

After the fix, all T01–T08 and P01–P12 pass on both toolchains.

## Execution evidence

- `cargo test --workspace --all-targets`: 1012 passed, 7 ignored, 0 failed on
  Rust 1.98.1 and Rust 1.85.0.
- `cargo fmt`, `cargo clippy --all-features -D warnings`, `cargo doc`: clean on
  both toolchains.
- `cargo llvm-cov --workspace --all-features --fail-under-lines 85`: 92.04% line.
- `cargo run --release ... pr07_bench`: correctness oracle passes; latencies
  within noise of Amendment 02.

## Reviewer checklist status

- [x] Every ledger transition preflights budget and ledger state, then commits once.
- [x] Direct budget release atomic under mixed-validity subtraction.
- [x] Injected failures preserve counters; seeded model test passes.
- [x] Phrase scratch charged before every bounded vector allocation and released
      only after drop.
- [x] Intersection and chain transitions account for simultaneous old/new buffers.
- [x] Returned matches/term frequencies charged exactly once via outer reservation.
- [x] Cancellation/resource errors clean up scratch and preserve typed errors.
- [x] Independent phrase oracle and memory/Fs parity pass.
- [x] Existing Amendments 01/02 and all PR 7 suites remain green.
- [x] Stable/MSRV gates, ≥85% coverage, correctness-gated benchmark executed.
- [x] No public API, format, storage, query semantics, or roadmap scope changes.
- [ ] Independent review before PR 7 merge (pending).

## Residual risks

Scratch/byte units are conservative logical estimates, not allocator-exact RSS;
field-length recomputation remains O(indexed postings); no RustFS/WAND/streaming.
The prior Amendment 02 residual risk that `match_phrase` scratch was uncharged is
now resolved. No new on-disk format.
