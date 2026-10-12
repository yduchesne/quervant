# PR 4 review amendment 06 — final report

**Branch:** `dev/analyzer-contract`
**Starting HEAD:** `c8f3e8f` (Amendment 05)
**Fixup commit:** `<recorded after commit>`
**Disposition:** narrow parser-only fixup; **not merged**; roadmap PR 4 remains PLANNED.

## 1. Finding addressed (R4-10 HIGH)

`class_set_is_transform_stable()` proved only explicit-member stability and ignored
`ClassBracketed.negated` / `ClassAscii.negated`. A negated class matches the complement, which is
not membership-stable under full Unicode case folding: `[^a]` matches source `A`, but the folded
indexed term `a` is excluded. Under a `CaseFold` analyzer the class was accepted, silently
missing the indexed term.

**Fix (`crates/trawler-core/src/analysis/term.rs`, parser-only, no public API change):**
- Added a private `PatternPolicy.case_folding` flag, set only by `TokenFilter::CaseFold`
  (`AsciiFold` does not change case and does not set it). Existing flags are unchanged.
- `validate_and_collect` rejects `Ast::ClassBracketed { negated: true }` under case folding.
- `class_item_is_transform_stable` returns unstable for `ClassAscii { negated: true }` and for a
  nested `ClassSetItem::Bracketed(inner { negated: true })` under case folding.
- Positive classes/ranges/POSIX classes, `Perl`/`Unicode`, set operators and the
  `MAX_CLASS_RANGE_SCAN = 4096` proof keep their behavior; non-case-folding `NFC`/`NFD`/`NFKD`
  and no-transform pipelines are unchanged; `leading_info` (Amendments 03–05) still rejects
  negated classes at unsafe composing boundaries. Work budget, cancellation, input/nesting limits
  and typed errors are preserved. No STOP condition applied.

The two properties are now distinct and documented: **leading-combining safety** (never begin a
match with a mark that composes with a preceding character) versus **negated-complement
membership stability** (a complement must not change under the configured transforms).

## 2. Files changed

- `crates/trawler-core/src/analysis/term.rs`
- `crates/trawler-core/tests/analysis_review_amendment_06.rs` (new, 55 tests)
- `docs/ARCHITECTURE.md` (separates the two stability properties)
- `docs/pr-artifacts/pr-4/review-amendment-06-{preflight,tests,report}.md`

Amendments 01–05 artifacts are unchanged. No protected/file-map deviations.

## 3. Gate results (final run)

| Command | Result |
|---|---|
| `cargo +1.85.0 check --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **584 passed; 0 failed; 1 ignored** |
| `cargo test -p trawler-core --test analysis_review_amendment_06` | PASS — 55 |
| `cargo test -p trawler-core --test analysis_review_amendment_05` | PASS — 56 |
| `cargo test -p trawler-core --test analysis_review_amendment_04` | PASS — 45 |
| `cargo test -p trawler-core --test analysis_review_amendment_03` | PASS — 27 |
| `cargo test -p trawler-core --test analysis_review_amendment_02` | PASS — 30 |
| `cargo test --workspace --all-targets` | PASS — **584 passed; 0 failed; 1 ignored** |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **94.27% lines**, 91.34% functions, 94.03% regions |
| `cargo doc --workspace --no-deps` | PASS |

Red-before / green-after: the A6 matrix was **28 passed / 27 failed** at baseline `c8f3e8f` and
**55 / 0** after. No failing gate remained. Toolchains: stable 1.99.0, MSRV cargo 1.85.0. The one
ignored test is pre-existing and unrelated.

## 4. Integration topology

In-process public path only: real `AnalyzerRegistry`/`AnalyzerDefinition` →
`collect_tokens(AnalyzerRole::Index, …)` and public `prepare_regex` with matching analyzer
fingerprint. PR 4 has no persisted index or regex executor; PR 5 (segments) and PR 8 (matching)
are not implemented and no end-to-end search or regex-matching claim is made. No RustFS/network
topology applies; storage/retry/recovery boundaries are **not applicable**.

## 5. Conservative behavior changes (approved)

Under a `CaseFold` search pipeline, negated bracketed/POSIX/ASCII classes and nested negated
brackets now reject typed (`UnsupportedPattern`), independently of any preceding node. Positive
classes (`[0-9]`, `[a-z]`, `[[:digit:]]`, `[[:lower:]]`), non-negated patterns, and
non-case-folding pipelines are unchanged. No existing test asserted these negated patterns; no
earlier test was edited.

## 6. Residual limitations

- The rule is conservative: it rejects all negated classes under case folding, including
  complements that happen to be stable (e.g. `[^0-9]`), because closure is not proven.
- Case folding is the only trigger; `AsciiFold` (NFKD + strip marks, no case change) does not
  set the flag, so `AsciiFold`-only complement behavior is unchanged.
- Regex matching/execution is PR 8; analyzer-identity persistence is PR 5. Roadmap PR 4 remains
  PLANNED and the branch is unmerged pending human review.
