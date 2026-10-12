# PR 4 review amendment 02 — Phase 0 preflight and reproductions

**Branch:** `dev/analyzer-contract`
**Reviewed/starting HEAD:** `591474524eee574c8d7e67b2b9ca5704ca4a5bd7` (matches `origin/dev/analyzer-contract`)
**`origin/main`:** `040b6a945e9e02c26bbf13660744ddceed177797` (no PR 4 analyzer APIs; feature-only)
**Working tree at preflight:** clean. `regex-syntax` resolved 0.8.11. Toolchains: stable 1.99.0, MSRV cargo 1.85.0.

## 1. Baseline before edits

| Command | Result |
|---|---|
| `cargo test --workspace --all-targets` | PASS — 370 passed; 0 failed; 1 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 370 passed; 0 failed; 1 ignored |

Prior PR 4 fixup evidence (R4-01/03/04/05/06) is preserved and regression-tested; nothing erased.

## 2. Reproduction evidence (targeted tests run against unmodified code)

New test file `crates/trawler-core/tests/analysis_review_amendment_02.rs` was added first and run
against `5914745`. Result: **19 passed; 11 failed**, confirming every alleged defect that this
amendment targets. No alleged defect was disproven, so no STOP was required.

| Finding | Failing reproduction | Observed |
|---|---|---|
| A2-01 | `a2_t01_nfc_literal_run_composes_across_scalars` | prepared literal `"e\u{301}"` (decomposed) instead of `"é"`; indexed NFC term is `"é"` → silent mismatch. |
| A2-01 | `a2_t03_nfd_decomposes_composed_literal` | NFD analyzer rejected `"é"` (`UnsupportedPattern`) instead of decomposing it. |
| A2-01 | `a2_t05_quantified_combining_mark_is_rejected` | `e\u{301}+` was accepted unchanged (composition across quantifier boundary not handled). |
| A2-01 | `a2_t08_expansion_policy_is_safe` | unquantified `Straße`/`Straße+` rejected although run expansion is safely representable. |
| A2-01 | `a2_i01_nfc_indexing_and_literal_preparation_agree` | prepared pattern ≠ indexed term. |
| A2-03 | `a2_t11_stable_endpoints_unsafe_interior_is_rejected` | `[@-a]` accepted: endpoints `@`/`a` are stable but interior `A`–`Z` is not, so folded terms silently fail. |
| A2-03 | `a2_i02_folded_analyzer_rejects_unsafe_class` | `[@-a]` accepted under `english`. |
| A2-04 | `a2_t22_terminal_error_is_latched` | after `TooManyTokens`, subsequent `next_token()` calls did not return the latched error. |
| A2-04 | `a2_t23_cancellation_after_token_is_terminal` | post-error calls were not proven terminal. |
| A2-02 | `a2_t16_keyword_charges_incrementally` | keyword tokenizer charged the whole value at once (polls = 4 instead of ≥5), i.e. no checkpoint during the scan. |
| A2-02 | `a2_t18_uax29_single_word_exact_segmentation` | (initial test sizing) — corrected to stay within the 4 KiB term limit; retained as a segmentation regression. |

After the code fixes, all A2 tests pass (see `review-amendment-02-tests.md`).

## 3. Pinned dependency facts

- `regex-syntax 0.8.11` AST: `Ast::{Literal, Concat, Alternation, Group, Repetition, ClassUnicode, ClassPerl, ClassBracketed, Dot, Assertion, Empty, Flags}`; `Literal { span, kind, c }`; spans are byte offsets (`Span.start.offset`). The parser already rejects lookaround/backreferences/malformed syntax.
- Adjacent literal scalars are distinct `Ast::Literal` nodes inside `Ast::Concat` (e.g. `RUN` =
  3 literals); a quantified literal is wrapped in `Ast::Repetition`, so literal-run grouping only
  applies to consecutive bare `Ast::Literal` children.
- `unicode_normalization::char::canonical_combining_class` is available for combining-mark detection.
- `unicode_segmentation::UnicodeWordIndices::next()` scans one UAX #29 segment atomically; it is
  not preemptible. This is documented as an uninterruptible-segment limitation, bounded by the
  1 MiB per-value ceiling. `char_indices()` (whitespace) is per-scalar and interruptible.

## 4. Compatibility assessment (no STOP)

- The `[@-a]` fix uses a **full interior scalar scan** for ranges (capped at 4096 scalars), not
  endpoint-only reasoning. This preserves the existing acceptance of `[0-9]` and `[a-z]` under
  case-folding while rejecting ranges with an unstable interior, so `f4_07_approved_subset_is_accepted`
  and T08 do **not** need to change. No class rejection beyond genuine unsoundness is introduced.
- Literal-run grouping preserves the approved conservative-failure policy: quantified expansions
  and quantifier-crossing composition are rejected typed; unquantified runs are re-escaped.
- No new dependency, public-contract, MSRV, parser/automaton, or out-of-scope change is required.
