# PR 4 review amendment 07 — final report

**Branch:** `dev/analyzer-contract`
**Starting HEAD:** `6b5ace2` (Amendment 06)
**Fixup commit:** `e237e19`
**Disposition:** narrow parser-only fixup; **not merged**; roadmap PR 4 remains PLANNED.

## 1. Findings addressed

**R4-11 (HIGH) — incomplete prefix/glob limits.** `prepare_prefix`/`prepare_glob` lacked an
input-byte preflight, an entry cancellation check, a per-scalar work charge independent of
configured filters, per-segment `max_term_bytes` checks, and a total serialized-glob bound.

**R4-12 (HIGH) — normalization across wildcard boundaries.** `prepare_glob` normalized each
literal run independently; a literal beginning with a combining scalar after `*`/`?` could
compose in the indexed term (`e*\u0301` vs indexed `é`), silently losing matches.

**Fix (`crates/trawler-core/src/analysis/term.rs` only, no public API change):**
- `prepare_prefix`: entry cancellation, raw-byte `InputTooLarge` preflight, one work unit per
  input scalar (independent of filters), `EmptyTerm`, and `TermTooLarge` when the normalized
  prefix exceeds `max_term_bytes`.
- `prepare_glob`: entry cancellation, raw-byte `InputTooLarge` preflight, one work unit per
  scanned scalar plus one per escaped scalar, per-segment `TermTooLarge` in `flush_literal`, a
  transform-removed literal is rejected rather than dropped, and the serialized UTF-8 length is
  accumulated with checked/saturating arithmetic and checked against `max_input_bytes` **before**
  allocating the string.
- `validate_glob_boundary_safety`: under composing normalization (`NFC`/`NFKC`), a glob literal
  that begins with a combining scalar and is not the first segment is rejected typed; `*`/`?` are
  documented as scalars of the indexed term.
- Preserved: `GlobSegment`/`PreparedGlob` contracts, operator/escape serialization, canonical `*`
  collapse, metadata/fingerprint, exact-at-limit/one-over behavior, `prepare_term`/`prepare_regex`
  behavior, class/regex policies from Amendments 02–06, and resource ceilings.

No STOP condition applied: no grammar/public-contract/dependency/MSRV change; no previously
approved test was weakened.

## 2. Files changed

- `crates/trawler-core/src/analysis/term.rs`
- `crates/trawler-core/tests/analysis_review_amendment_07.rs` (new, 55 tests)
- `docs/ARCHITECTURE.md` (prefix/glob limits and wildcard-indexed-scalar semantics)
- `docs/pr-artifacts/pr-4/review-amendment-07-{preflight,tests,report}.md`

Amendments 01–06 artifacts are unchanged. No protected/file-map deviations.

## 3. Gate results (final run)

| Command | Result |
|---|---|
| `cargo +1.85.0 check --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **639 passed; 0 failed; 1 ignored** |
| `cargo test -p trawler-core --test analysis_review_amendment_07` | PASS — 55 |
| `cargo test -p trawler-core --test analysis_review_amendment_06` | PASS — 55 |
| `cargo test -p trawler-core --test analysis_review_amendment_05` | PASS — 56 |
| `cargo test -p trawler-core --test analysis_review_amendment_04` | PASS — 45 |
| `cargo test -p trawler-core --test analysis_review_amendment_03` | PASS — 27 |
| `cargo test -p trawler-core --test analysis_review_amendment_02` | PASS — 30 |
| `cargo test --workspace --all-targets` | PASS — **639 passed; 0 failed; 1 ignored** |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **94.52% lines**, 91.64% functions, 94.27% regions |
| `cargo doc --workspace --no-deps` | PASS |

Red-before / green-after: with `term.rs` reverted to baseline, the A7 matrix was
**25 passed / 30 failed**; after the fix **55 / 0**. No failing gate remained. Toolchains:
stable 1.99.0, MSRV cargo 1.85.0. The one ignored test is pre-existing and unrelated.

## 4. Integration topology

In-process public path only: real `AnalyzerRegistry`/`AnalyzerDefinition` →
`collect_tokens(AnalyzerRole::Index, …)` and public `prepare_prefix`/`prepare_glob`/
`prepare_regex` with matching analyzer fingerprint. PR 4 has no persisted index or wildcard
automaton; PR 5 (segments) and PR 8 (matching) are not implemented and no end-to-end search or
wildcard-matching claim is made. No RustFS/network topology applies; storage/retry/recovery are
**not applicable**.

## 5. Conservative behavior changes (approved)

Under composing normalization, glob literals beginning with a combining scalar after a wildcard
(`e*\u0301`, `*\u0301`, `e?\u0301`) are rejected typed. A glob literal that a configured transform
removes entirely (e.g. AsciiFold dropping a mark) is rejected rather than dropped. `*`/`?` keep
their indexed-scalar semantics (documented), and decomposition/no-normalization pipelines are
unchanged. No existing test asserted these forms; no earlier test was edited.

## 6. Residual limitations

- The wildcard boundary rule is conservative and composition-focused; whole-pattern equivalence
  between raw-text and indexed-term glob semantics (especially `?` scalar counts under
  length-changing folds) is documented as indexed-term semantics, not proven raw-text equivalence.
- Class set operators and Unicode/Perl membership remain conservatively handled per Amendments
  04–06.
- Regex/wildcard matching execution is PR 8; analyzer-identity persistence is PR 5. Roadmap PR 4
  remains PLANNED and the branch is unmerged pending human review.
