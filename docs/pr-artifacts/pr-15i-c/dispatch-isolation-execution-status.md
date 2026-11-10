# PR 15I-C dispatch-isolation — final status

**Disposition: `15IC_DISPATCH_DIAG_MIXED_SAFE_ROLLBACK_VERIFIED`**

The historical low-match regression reproduces exactly with the unchanged causal
candidate (C) and is removed when its physical dispatch is compile-time-disabled
(D) or replaced by a minimal no-operator scaffold on the merged baseline (E).
Because D is not uniformly neutral (two of eight cells land at 1.0807 and 1.0863,
just above the predeclared 1.08 ceiling), the frozen table does not award a single
row and the study reports **MIXED**.

## Identities

| Role | SHA |
|---|---|
| `BASE_A` (merged PR 15I-B) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| Branch start | `c9216304dc3317735397961a8974396d32e82dfd` |
| C (causal candidate, unchanged) | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` |
| D (C + literal-false dispatch) | `9c710e5432aa17cdcd717ce40ad6f9a8167914f1` |
| E (A + predicate/gate/trampoline) | `d97889d2debc14f1e4ea3c821089cd453ba1daab` |
| Dispatch tooling | `9b35df64e4dca1afcd8594475e586b71f6308684` (+ `e4c3c80`, verifier/codegen fixes) |
| Final primary tip | this commit |

## Protected-state proof

```
git diff --quiet 6f6463cb… HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml \
  Cargo.lock .github/workflows/ci.yml benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b  -> empty
```

D and E exist only as local diagnostic branches/worktrees
(`dev/pr15i-c-dispatch-d`, `dev/pr15i-c-dispatch-e`) and are preserved for review.
No production revert commit was needed because the primary branch never carried
the experimental source. Every earlier protocol hash is unchanged.

## Evidence

| Artefact | Location |
|---|---|
| Four sealed campaigns (2 unbatched, 2 batched) | `target/pr15i-c/dispatch-isolation-v1/{unbatched,batched}-0{1,2}` |
| Preserved pre-sampling attempt | `.../unbatched-01-attempt-01` (with `INVALID.json`) |
| Five independent receipts | `target/pr15i-c/reviews/dispatch-*` |
| Codegen captures (controller-era and verifier re-capture) | `target/pr15i-c/dispatch-codegen-v1/` |

## External statuses

`REAL_RUSTFS_BLOCKED` (no verified pinned runtime), `HOSTED_CI_PENDING`,
`INDEPENDENT_REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`.
No PR 15I-C capability is delivered, no roadmap item is marked done, and the
frozen `C-P06..C-P09` acceptance gates were not run (this study never executes a
16-slot acceptance campaign).

## Single bounded fact and next decision

Within one candidate source, the low-match regression disappears when the physical
dispatch is compiled away and does not appear in a minimal no-operator scaffold,
while it is fully present with the runtime gate intact. That points at the
candidate-only compilation/dispatch context rather than at the operator's runtime
work — but the predeclared strictness yields MIXED, so **no single architecture is
recommended**. The next decision belongs to a human: either authorize a follow-up
that isolates the remaining D/A ≈ 1.08–1.09 cells with more samples per slot, or
stop the PR 15I-C line entirely.
