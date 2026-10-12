# PR 4 review fixup — Phase 0 preflight

**Branch:** `dev/analyzer-contract`
**Reviewed HEAD:** `5fcf4c4` (matches `origin/dev/analyzer-contract`)
**`origin/main`:** `040b6a945e9e02c26bbf13660744ddceed177797` (PR 2/3 contracts + storage; no PR 4)
**Working tree:** clean at preflight; no uncommitted work discarded.
**Authority:** `docs/decisions/PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md`, `docs/ARCHITECTURE.md`,
`docs/TESTING.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`; approved decisions take precedence
over the fixup plan on conflict.

## 1. Baseline (before any fixup change)

Toolchains: `rustc/cargo 1.99.0` (stable), `cargo 1.85.0` (MSRV).

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 342 passed; 0 failed; 1 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 342 passed; 0 failed; 1 ignored |

CI (`.github/workflows/ci.yml`) remains authoritative: fmt, clippy, tests,
`cargo llvm-cov --workspace --all-targets --fail-under-lines 85`, doc.

## 2. Finding classification

Six independent-review findings confirmed as **feature defects / partial implementations** in the
existing PR 4 code; the subsystem otherwise works. This fixup targets only those six, plus the
mandatory regression matrix. No protected files (`contract/**`, `storage/**`, object-store,
distributed, PR 5/6/8) will change.

## 3. G-RX — approved regex subset and parser (RESOLVED)

`docs/ARCHITECTURE.md` defines the subset: character classes/ranges, grouping, alternation,
`*`/`+`/`?`, bounded repetitions (`{2,4}`), Unicode character classes where bounded cost permits;
**no** backreferences, lookaround, or arbitrary PCRE extensions. The amendment T08 adds: whole
indexed-term matching, parse/normalize contracts only, reject unsupported constructs explicitly.

Selected parser: **`regex-syntax = 0.8` (resolved 0.8.11)**, license `MIT OR Apache-2.0`, manifest
MSRV **1.65**, maintained by the `rust-lang/regex` project. Verified to build on Rust 1.85.0 and
to expose a parser-only API (`regex_syntax::ast::parse::{Parser, ParserBuilder}`, `regex_syntax::ast::Ast`,
`regex_syntax::is_meta_character`). No regex compilation, DFA/NFA, or matching is used.

Verified behavior on 0.8.11 (installed source + executed probe):

| Pattern | Parser result |
|---|---|
| `^ab(c\|d)[0-9]{2,4}$` | OK (accepted) |
| `a{3,2}` | **error**: start must be <= end |
| `*abc` | **error**: repetition operator missing expression |
| `[z-a]` | **error**: class range start must be <= end |
| `(ab`, `a\`, `[a` | **error**: unclosed group / incomplete escape |
| `(a)\1` | **error**: backreferences are not supported |
| `a(?=b)` | **error**: look-around not supported |
| `a\|` | OK: alternation with an `Empty` branch |
| `(?i)abc` | OK: parsed as `Ast::Flags` (we reject) |
| `(?<name>a)` | OK: `GroupKind::CaptureName` (we reject) |
| `(?:ab)+` | OK: non-capturing group |
| `\p{Greek}`, `\p{Lu}` | OK: `ClassUnicode` |
| `\d` | OK: `ClassPerl` |
| `[A-Z]` | OK: `ClassBracketed` with a cased range |

`ParserBuilder::nest_limit(u32)` bounds recursion (default 250); we set a tighter constant bound.
`Parser` is single-use, so each validation builds a fresh parser.

## 4. G-NORM — regex literal normalization policy (RESOLVED)

The prior `prepare_regex` normalized the whole pattern string with NFC only and never case-folded,
which is inconsistent with case-folded indexed terms. Resolved with the plan's **preferred
policy**: syntax-aware normalization of AST **literal nodes only**, using the same ordered
`Normalize`/`CaseFold`/`AsciiFold` transforms as index-time analysis (stopwords and stemming are
never applied to patterns; consistent with T03a/T08).

Rules:
- A literal whose transform yields exactly one scalar value is replaced (syntax re-escaped if it
  becomes a metacharacter).
- A literal whose transform yields zero or multiple scalar values (e.g. `Straße` → `strasse`,
  NFKD ligature expansion) is **rejected** with `UnsupportedPattern` (quantifier scope cannot be
  preserved without grouping semantics we do not need to invent).
- Inline flags (`(?i)…`), named captures, and — when the search pipeline applies case folding or
  ASCII folding — `ClassUnicode`/`ClassBracketed` nodes are **rejected**; `ClassPerl` (`\d`, `\w`,
  `\s`), anchors, `Dot`, groups, repetition and alternation are preserved.
- The normalized output is re-parsed and re-validated.

This is consistent with the approved decisions, so no STOP is required. It never rewrites
operators/escaping/grouping/ranges/quantifiers.

## 5. G-STREAM — lazy tokenization (RESOLVED)

- Keyword: single whole-value span (bounded by the 1 MiB/value ceiling).
- Whitespace: lazy state machine over `str::char_indices()`.
- Unicode-word: lazy `unicode_segmentation::UnicodeSegmentation::unicode_word_indices()`
  (`UnicodeWordIndices<'a>`), yielding `(offset, &str)` without materializing the value.
- `AnalysisCursor` will hold the active value's lazy cursor and process one raw span at a time,
  retaining raw positions for dropped stopwords and the 100-position value gap.

All are safe Rust 1.85 with no self-referential structs or unsafe.

## 6. Protected-scope confirmation

No change is planned to `crates/trawler-core/src/contract/**`, `storage/**`,
`crates/trawler-objectstore/**`, `crates/trawler-distributed/**`, datasets/licenses, or any
PR 5/6/8 component. Only `analysis/**`, targeted integration tests, the core manifest/lock for the
verified parser, and reports under `docs/pr-artifacts/pr-4/` will change.
