# PR 4 review amendment 06 — preflight and reproductions

**Branch:** `dev/analyzer-contract`
**Starting HEAD / `origin/dev/analyzer-contract`:** `c8f3e8f` (Amendment 05)
**`origin/main` / merge base:** `040b6a945e9e02c26bbf13660744ddceed177797` (PR 4 analysis is feature-only)
**Working tree at preflight:** clean. Toolchains: stable rustc 1.99.0, MSRV cargo 1.85.0.
**`regex-syntax`:** 0.8.11 (unchanged; no new dependency).

## 1. Baseline

| Command | Result |
|---|---|
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 529 passed; 0 failed; 1 ignored |
| `cargo test --workspace --all-targets` | PASS — 529 passed; 0 failed; 1 ignored |

Amendments 01–05 artifacts/results are preserved.

## 2. Pinned AST and code facts

- `ClassBracketed { negated: bool, kind: ClassSet }`; `ClassAscii { kind, negated }`;
  nested `ClassSetItem::Bracketed(Box<ClassBracketed>)`; `ClassPerl { negated }`;
  `ClassUnicode { negated }`; `ClassSet::BinaryOp` for intersection/difference/symmetric
  difference. Verified in the installed `regex-syntax 0.8.11` source.
- `class_set_is_transform_stable()` / `class_item_is_transform_stable()` proved only **explicit
  member** stability; they did not consult `ClassBracketed.negated` or `ClassAscii.negated`.
  `PatternPolicy` had no case-folding flag (only `transforms_terms`, `composing_normalization`,
  `compatibility_normalization`), so the complement problem was unaddressed.
- The separate `leading_info` (Amendments 04–05) already rejects negated classes that could
  compose with a preceding character at a composing boundary; that is a different property from
  complement membership stability.

## 3. Phase-zero red reproduction (A6 tests against unmodified `c8f3e8f`)

`crates/trawler-core/tests/analysis_review_amendment_06.rs` was added and run first:
**28 passed; 27 failed**. Failures are the R4-10 complement bypass.

| Representative failing test | Observed at baseline |
|---|---|
| `a6_t01_negated_class_casefold_only` | `[^a]` accepted under `CaseFold` only. |
| `a6_t02`/`a6_t03` | accepted with NFC+CaseFold and CaseFold+NFC. |
| `a6_t07`–`a6_t13` | negated class in groups/alternations/repetitions accepted. |
| `a6_t14`–`a6_t19` | negated POSIX/ASCII classes, unions and nested negated brackets accepted. |
| `a6_t31`/`a6_t32` | `[^a]` accepted with NFD/NFKD + CaseFold. |
| `a6_t43`, `a6_t44`, `a6_t46`, `a6_i01`, `a6_i02`, `a6_i06`, `a6_i08` | public-path variants accepted. |

**Already safe (retained as regressions, not new-bug evidence):** `[^A]`, `[^ß]`, `[^Σ]`
(T04–T06) were already rejected because the excluded literal is itself case-unstable;
`e[^x]`/`e[[:^digit:]]` without case folding (T33/T34) already reject via Amendment 05.

**Semantic witness (independent of preparation):** the case-folding pipeline maps source `A` to
the indexed term `a`, which `[^a]` excludes — asserted in
`a6_i_semantic_witness_casefold_membership_changes` via `collect_tokens`, not via regex matching.

## 4. Classification

| Capability | Classification |
|---|---|
| Analyzer pipeline/tokenization/domain/registry (Amendments 01–02) | DONE (source/tests present; rerun here) |
| Leading-combining boundary safety (Amendments 03–05) | DONE (source/tests present; rerun here) |
| Negation-aware **complement-stability** under case folding | PARTIAL → fixed here |
| A6 regression matrix | NOT STARTED → implemented here |
| Prior agent-reported 529 tests/94.24% | DONE NOT INDEPENDENTLY VERIFIED (rerun on final SHA) |
| Regex execution / persistence | Out of scope (PR 8 / PR 5) |

## 5. Fix and preserved policy

- `PatternPolicy` gains a private `case_folding` flag set only by `TokenFilter::CaseFold`
  (`AsciiFold` does not change case and does not set it).
- `validate_and_collect` rejects `ClassBracketed.negated` under case folding; 
  `class_item_is_transform_stable` returns unstable for `ClassAscii.negated` and nested
  `Bracketed.negated` under case folding.
- Positive classes, class ranges, `Perl`/`Unicode`, set operators and the existing
  `MAX_CLASS_RANGE_SCAN = 4096` proof keep their behavior. Non-case-folding `NFC`/`NFD`/`NFKD`/
  no-transform pipelines are unchanged. Class-stability, `leading_info`, work budget,
  cancellation, input and nesting limits and typed errors are all preserved. No STOP condition
  applied.
