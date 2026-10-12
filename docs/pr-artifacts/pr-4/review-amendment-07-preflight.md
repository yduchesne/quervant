# PR 4 review amendment 07 — preflight and reproductions

**Branch:** `dev/analyzer-contract`
**Starting HEAD / `origin/dev/analyzer-contract`:** `6b5ace2` (Amendment 06)
**`origin/main` / merge base:** `040b6a945e9e02c26bbf13660744ddceed177797` (PR 4 analysis is feature-only)
**Working tree at preflight:** clean. Toolchains: stable rustc 1.99.0, MSRV cargo 1.85.0.
**`regex-syntax`:** 0.8.11 (unchanged; no new dependency).

## 1. Findings and classification

| Finding | Classification | Evidence |
|---|---|---|
| R4-11 prefix/glob input, work and output limits | PARTIAL → fixed | Source inspection: `prepare_prefix`/`prepare_glob` had no input-byte preflight, no per-scalar work charge for no-op pipelines/operators/escapes, no per-segment `max_term_bytes` check, and no total serialized-glob bound. |
| R4-12 normalization across wildcard boundaries | PARTIAL → fixed | `prepare_glob` normalized each literal run independently; a literal beginning with a combining scalar after `*`/`?` could compose in the indexed term (`e*\u{0301}` vs indexed `é`). |
| Amendments 01–06 analyzer/domain/registry/regex | DONE (source/tests present; rerun here) | Prior agent-reported 584 tests / 94.27% — reported evidence only. |
| PR 5 persistence / PR 8 execution | Out of scope | Not implemented in this fixup. |

Baseline workspace: `cargo +1.85.0 test --workspace --all-targets` = 584 passed; 0 failed;
1 ignored.

## 2. Source API facts (`crates/trawler-core/src/analysis/term.rs`)

- `prepare_prefix()` and `prepare_glob()` reused `normalize_literal()`/`flush_literal()` with a
  `WorkBudget` but no input preflight, cancellation check at entry, per-scalar work charge, or
  output checks. `PatternScanner` yielded scalars without charging.
- `GlobSegment::{Literal(String), AnySequence, AnyChar}` and
  `PreparedGlob::{segments, normalized, metadata}` are public and preserved unchanged.
- `AnalysisLimits::{max_input_bytes, max_term_bytes, max_work_units}` (defaults 1 MiB, 4 KiB,
  8,000,000) and the typed `AnalysisError::{InputTooLarge, TermTooLarge, WorkBudgetExceeded,
  Cancelled, UnsupportedPattern, EmptyTerm}` variants are reused; no new variants/API.
- `normalize_literal()` charges `1 + term.len()` per configured transform filter; a pipeline with
  an empty filter list charged nothing, which is why an independent per-scalar charge is needed.

## 3. R4-12 wildcard safety policy (decision note)

Glob matching is defined over **scalars of the indexed term** (`*` = zero or more scalars,
`?` = exactly one scalar). The user's pattern is normalized through the same ordered
`Normalize`/`CaseFold`/`AsciiFold` filters as the index; stop-words and stemming are never applied.

Accepted/rejected matrix under a **composing normalization** (`NFC`/`NFKC`):

| Case | Decision |
|---|---|
| Adjacent literals (single run) | Normalize together (e.g. `e\u0301` → `é`). |
| Literal beginning with a combining scalar that is the **first** segment | Accept (no preceding starter). |
| Literal beginning with a combining scalar **after** `*`/`?` or an earlier segment | **Reject** (`e*\u0301`, `*\u0301`, `e?\u0301`, `e**\u0301`): `*` may match zero scalars, exposing composition. |
| Escaped `\*`, `\?`, `\\` | Literals, never operators. |
| `?` scalar semantics | One scalar of the indexed term; case-fold expansion (`ß`→`ss`) is documented indexed-term behavior, not a rewrite of the operator. |
| Literal removed entirely by a transform (AsciiFold dropping a mark) | **Reject** rather than silently dropping it. |
| Under `NFD`/`NFKD`/no normalization | No composition; prior acceptance preserved. |

This is a deliberate conservative policy: rejection is preferred over a false-negative match. No
automaton or match execution is added (PR 8).

## 4. Baseline red reproduction

The A7 suite was authored with the production change and then re-run against the reverted
production file (`git stash push -- term.rs`) to obtain genuine baseline evidence:
**25 passed / 30 failed** at baseline, **55 / 0** after. Representative baseline failures:
`a7_t01`/`a7_t03`/`a7_t05` (no input preflight), `a7_t06`–`a7_t09` (no per-scalar work charge),
`a7_t12`/`a7_t14`/`a7_t16` (no term/output bounds), `a7_t10`/`a7_t11` (no entry cancellation),
`a7_t21`–`a7_t33` (glob composition accepted), `a7_i01`/`a7_i03`/`a7_i05`/`a7_i06`/`a7_i07`
(public-path variants). The 25 baseline passes are grammar/regression cases preserved unchanged.

## 5. Resource model (R4-11)

- **Input:** raw UTF-8 byte length checked against `max_input_bytes` before scanning/copying.
- **Work:** `prepare_prefix` charges one unit per raw input scalar; `prepare_glob` charges one
  unit per scanned scalar plus one for each escaped scalar. This is independent of configured
  filters, so a no-op pipeline is still bounded; `normalize_literal` additionally charges per
  filter.
- **Per-term:** the normalized prefix and each normalized glob literal segment are checked against
  `max_term_bytes`.
- **Total glob:** the serialized UTF-8 byte length is accumulated with checked/saturating
  arithmetic **before** allocating the string and checked against `max_input_bytes`; escaping and
  case-fold expansion are counted.
- Input preflight precedes work charging; cancellation is checked at entry and at deterministic
  points.
