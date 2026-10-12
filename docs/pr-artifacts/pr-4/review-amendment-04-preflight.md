# PR 4 review amendment 04 — preflight and reproductions

**Branch:** `dev/analyzer-contract`
**Starting HEAD / `origin/dev/analyzer-contract`:** `1de1fe01828097c2d7c139ce37c96d1365a12601` (Amendment 03)
**`origin/main` / merge base:** `040b6a945e9e02c26bbf13660744ddceed177797` (PR 4 analysis is feature-only)
**Working tree at preflight:** clean. Toolchains: stable 1.99.0, MSRV cargo 1.85.0.
**`regex-syntax`:** 0.8.11 (`RepetitionKind::{ZeroOrOne,ZeroOrMore,OneOrMore,Range}`, `RepetitionRange::{Exactly,AtLeast,Bounded}`; `{0}` parses as `Exactly(0)`).

## 1. Baseline

| Command | Result |
|---|---|
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 428 passed; 0 failed; 1 ignored |
| `cargo test --workspace --all-targets` | PASS — 428 passed; 0 failed; 1 ignored |

Amendment 01–03 artifacts/results are preserved; this amendment adds to them.

## 2. Reproduction evidence (A4 tests against unmodified `1de1fe0`)

`crates/trawler-core/tests/analysis_review_amendment_04.rs` was added and run first:
**39 passed; 6 failed**. Every failure is a real bypass; no stated defect was disproven.

| Failing test | Observed at baseline | Why it is unsafe |
|---|---|---|
| `a4_t08_explicit_stable_combining_class` | `e[\u{0301}]` accepted | class is transform-stable but matches a combining scalar; NFC index stores `é`. |
| `a4_t09_combining_range` | `e[\u{0300}-\u{0302}]` accepted | range of combining scalars. |
| `a4_t10_class_inside_alternative` | `e(?:[\u{0301}]\|x)` accepted | class branch reachable after `e`. |
| `a4_t11_dot_after_literal_is_rejected` | `e.` / `e.*` accepted | `.` can match a combining scalar. |
| `a4_t12_perl_word_class_after_literal_is_rejected` | `e\w` accepted | `\w` includes combining marks (Mn). |
| `a4_t35_deep_nesting_does_not_panic` | nested group starting with a mark accepted | nested expression reachable after `e`. |

### Baseline already safe (assert continued rejection; not new-bug evidence)

`a4_t01`–`a4_t07` (nullable-prefix literal cases) already fail closed on `1de1fe0` because the
inner concatenation's preceded-literal check rejects the mark. `a4_t13` (NFKC) and
`a4_t28`/`a4_t39` already reject. These are retained as regression tests, not as evidence of the
new defect.

## 3. Verified status reconciliation

| Capability | Classification |
|---|---|
| Analyzer pipeline, tokenization, domain, registry (Amendments 01–02) | DONE (prior source/tests; rerun here) |
| Literal-run and group-boundary composition safety (Amendment 03) | DONE (prior source/tests; rerun here) |
| Nullable-aware leading-mark analysis | PARTIAL → completed here |
| Character-class / `.` / Perl leading-mark exclusion | NOT STARTED → implemented here |
| A4 regression matrix | NOT STARTED → implemented here |
| Prior agent's 428-test/94.23% report | DONE, NOT INDEPENDENTLY VERIFIED (rerun on final SHA) |
| Real regex execution | Out of PR 4 scope (PR 8) |

## 4. Policy and conservative narrowing

- `LeadingInfo { nullable, may_start_with_combining }` is computed for every AST node with a
  bounded, cancellation-aware traversal. `nullable` handles empties/assertions/optional
  repetitions; `may_start_with_combining` ORs over concatenation children reachable after
  nullable prefixes and over alternation branches.
- Bracketed classes use a bounded proof: a range is safe only when every (≤4096) scalar is
  transform-stable with combining class zero; `BinaryOp` (intersection/difference) and
  Unicode/Perl classes are treated as possibly combining.
- **Narrowed acceptance (documented correctness restrictions):** under composing normalization,
  `e.` (and `e.*`), `e\w`/`e\d`/`e\s`, and `e\p{...}` after a preceding expression are now
  rejected. `.`, `\w` and `\p{...}` can match combining scalars, so these are genuine
  false-negative risks; standalone/leading forms and safe classes (`e[0-9]`, `e[a-z]`) remain
  accepted. No STOP is required because the plan explicitly approves this conservative policy
  (A4-T11/T12) and each rejected case demonstrates an unsafe boundary.
- Decomposition-only (`NFD`/`NFKD`) and no-normalization pipelines are unchanged because no
  cross-boundary composition occurs.
