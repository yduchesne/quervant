# PR 4 review amendment 03 — final report

**Branch:** `dev/analyzer-contract`
**Starting HEAD:** `66cfb5fb8182fa40d408c6609e6ff38d0d827304`
**Fixup commit:** `fb56c97`
**Disposition:** narrow fixup only; **not merged**; roadmap PR 4 remains PLANNED.

## 1. Finding addressed

**A3 (HIGH):** regex preparation normalized each nested AST group independently, so a combining
mark at the start of a nested group (or a group/alternation/repetition that can begin with one)
could compose with the character matched by a preceding sibling during indexed-term normalization,
producing a prepared pattern that silently matches nothing against the normalized index. Example:
`e(?:\u0301)` was accepted although the NFC-indexed term for the same source is `é`.

**Fix (in `crates/trawler-core/src/analysis/term.rs`, no public API change):**
- `PatternPolicy` now tracks `composing_normalization` (`NFC`/`NFKC`).
- In a concatenation, every non-first node that can begin with a combining mark after the
  configured transforms is rejected typed (groups, alternations, repetitions, and preceded
  literal runs). The check uses the **transformed** first scalar's combining class, so literals
  that normalize into a leading combining mark are caught too, not just source marks.
- A first/standalone node (no preceding sibling) remains accepted, and self-contained runs
  (`(?:e\u0301)` → `(?:é)`) still normalize internally.
- Under `NFD`/`NFKD`/no normalization, no cross-boundary composition occurs, so those patterns
  remain accepted (`e(?:\u0301)` accepted).
- Class ranges and existing rejections are unchanged; work budget, cancellation and parser
  nesting limits are preserved (`starts_with_combining` polls cancellation and reuses
  `apply_pattern_transforms` for charging).

No STOP condition applied: no grammar/fingerprint/MSRV/dependency change, and no previously
accepted safe pattern is rejected.

## 2. Files changed

- `crates/trawler-core/src/analysis/term.rs` (boundary analysis + unit behaviour)
- `crates/trawler-core/tests/analysis_review_amendment_03.rs` (new, 27 tests)
- `docs/ARCHITECTURE.md` (documented composing-normalization boundary policy)
- `docs/pr-artifacts/pr-4/review-amendment-03-{preflight,tests,report}.md`

Amendment 01/02 artifacts were left intact.

## 3. Gate results (final run)

| Command | Result |
|---|---|
| `cargo +1.85.0 check --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **428 passed; 0 failed; 1 ignored** |
| `cargo test --workspace --all-targets` | PASS — **428 passed; 0 failed; 1 ignored** |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **94.23% lines**, 91.39% functions, 93.87% regions |

Targeted `cargo +1.85.0 test -p trawler-core --test analysis_review_amendment_03` = 27 passed.
Baseline reproduction: the same matrix was **20 passed / 7 failed** at `66cfb5f` before the fix.
Toolchains: stable 1.99.0, MSRV cargo 1.85.0. No tests skipped or ignored to hide failures.

## 4. Residual limitations

- The boundary analysis covers literal runs and group/alternation/repetition/concat structure.
  Character classes are governed by the separate class-stability policy and are conservatively
  treated as not starting with a combining mark; a class such as `[\u0301]` after a starter is a
  known limitation, not claimed safe. Broadening this would require bounded class-set analysis.
- This is parser-only preparation; PR 8 owns regex automaton execution and matching.
- PR 5 owns persisting analyzer identity/fingerprints; no fingerprint/version semantics changed.
