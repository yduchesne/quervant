# PR 4 review amendment 05 — preflight and reproductions

**Branch:** `dev/analyzer-contract`
**Starting HEAD / `origin/dev/analyzer-contract`:** `29636c8` (Amendment 04)
**`origin/main` / merge base:** `040b6a945e9e02c26bbf13660744ddceed177797` (PR 4 analysis is feature-only)
**Working tree at preflight:** clean. Toolchains: stable rustc 1.99.0, MSRV cargo 1.85.0.
**`regex-syntax`:** 0.8.11 (unchanged; no new dependency).

## 1. Baseline

| Command | Result |
|---|---|
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 473 passed; 0 failed; 1 ignored |
| `cargo test --workspace --all-targets` | PASS — 473 passed; 0 failed; 1 ignored |

Amendments 01–04 artifacts/results are preserved.

## 2. Pinned AST contract for negation (verified in installed 0.8.11 source)

| Form | AST representation |
|---|---|
| `[^x]` | `Ast::ClassBracketed { negated: true, kind: ... }` |
| `[[:^digit:]]` | `ClassBracketed { negated: false, kind: Item(Ascii(ClassAscii { kind: Digit, negated: true })) }` |
| `[\D]` | `ClassBracketed { negated: false, kind: Item(Perl(ClassPerl { kind: Digit, negated: true })) }` |
| `\D` | `Ast::ClassPerl(ClassPerl { negated: true, ... })` |
| `\P{Greek}` | `Ast::ClassUnicode(ClassUnicode { negated: true, ... })` |
| `[[^a]]` | `ClassBracketed { negated: false, kind: Item(Bracketed(ClassBracketed { negated: true, ... })) }` |
| `[\^x]` | `ClassBracketed { negated: false, kind: Item(Union([Literal(Meta, '^'), Literal(Verbatim, 'x')])) }` — `^` is a literal |
| `[^]` | parser error: `unclosed character class` |
| `[^\u{0301}]` | `ClassBracketed { negated: true, kind: Item(Literal(HexBrace(U+0301))) }` |

`ClassUnicode.negated`, `ClassPerl.negated` and nested `ClassBracketed.negated` are therefore all
reachable. Perl/Unicode were already conservatively `true`; the fix needed is for
`ClassBracketed.negated` and `ClassAscii.negated` (and nested `Bracketed.negated`).

## 3. Phase-zero red reproduction (A5 tests against unmodified `29636c8`)

`crates/trawler-core/tests/analysis_review_amendment_05.rs` was added and run first:
**31 passed; 25 failed**. All failures are the negation bypass; none was already rejected for an
unrelated reason except `a5_t13` (see below).

| Representative failing test | Observed at baseline |
|---|---|
| `a5_t01_outer_negated_class_nfc` | `e[^x]` accepted although `[^x]` can match U+0301. |
| `a5_t11_negated_posix_class` | `e[[:^digit:]]` accepted (`ClassAscii.negated` ignored). |
| `a5_t33_negated_caret_class_rejected` | `e[^^]` accepted. |
| `a5_t35_negated_posix_in_union` | `e[[:^digit:]a]` accepted. |
| `a5_t14`/`a5_t15`/`a5_t17`/`a5_t18` | negated ranges/quantifiers accepted. |
| `a5_t36`/`a5_t37` | nullable/quantified wrappers permit the bypass. |
| `a5_t38`, `a5_i01`, `a5_i02`, `a5_i05` | public-path variants accepted. |

**Already safe (retained as regression, not new-bug evidence):** `a5_t13 e[^\u{0301}]` was already
rejected (the excluded literal is itself a combining mark), and `a5_t34 e[^]` is a parser error.

## 4. Classification

| Capability | Classification |
|---|---|
| Analyzer pipeline, tokenization, domain, registry (Amendments 01–02) | DONE (source/tests present; rerun here) |
| Literal-run/group/nullable/class leading-mark safety (Amendments 03–04) | DONE (source/tests present; rerun here) |
| Negation-aware leading-mark classification | PARTIAL → fixed here |
| A5 regression matrix | NOT STARTED → implemented here |
| Prior agent-reported 473 tests/94.14% | DONE NOT INDEPENDENTLY VERIFIED (rerun on final SHA) |
| Regex execution / persistence | Out of scope (PR 8 / PR 5) |

## 5. Fix and preserved policy

- `leading_info` for `Ast::ClassBracketed` now treats `class.negated` as possibly combining.
- `class_item_may_start_with_combining` treats `ClassAscii { negated: true }` as possibly
  combining and propagates nested `ClassBracketed.negated`.
- Positive bracketed classes, positive ASCII/POSIX classes, literals/ranges, Perl/Unicode and
  set operators keep their existing (conservative) behavior; class-stability,
  `MAX_CLASS_RANGE_SCAN = 4096`, work budget/cancellation, 1 MiB input limit, nest limit and typed
  errors are unchanged.
- Rejection only occurs at a composing-normalization concatenation boundary; standalone/leading
  negated classes (`[^x]`, `[^x]e`) remain accepted, as do `NFD`/`NFKD`/no-normalization
  pipelines. No STOP condition applied.
