# PR 4 review amendment 05 — final report

**Branch:** `dev/analyzer-contract`
**Starting HEAD:** `29636c8` (Amendment 04)
**Fixup commit:** `<recorded after commit>`
**Disposition:** narrow parser-only fixup; **not merged**; roadmap PR 4 remains PLANNED.

## 1. Finding addressed (R4-09 HIGH)

Amendment 04's nullable-aware `LeadingInfo` ignored class negation. `LeadingInfo` for
`Ast::ClassBracketed` inspected `class.kind` only, and `class_item_may_start_with_combining`
treated every POSIX/ASCII class as safe. A negated class is not safe merely because its excluded
members are: `e[^x]` and `e[[:^digit:]]` can match U+0301, while the NFC-indexed term for
`e\u{0301}` is `é` — a silent false negative.

**Fix (`crates/trawler-core/src/analysis/term.rs`, parser-only, no public API change):**
- `leading_info` treats `ClassBracketed.negated` as `may_start_with_combining = true`.
- `class_item_may_start_with_combining` treats `ClassAscii { negated: true }` as possibly
  combining and propagates a nested `ClassBracketed.negated`.
- Positive bracketed/ASCII/POSIX classes, literals/ranges, set operators and Perl/Unicode classes
  keep their existing (conservative) behavior. Class-stability, `MAX_CLASS_RANGE_SCAN = 4096`,
  work budget/cancellation, the 1 MiB input ceiling, parser nesting and typed errors are
  unchanged.
- Rejection happens only at a composing-normalization concatenation boundary. Standalone/leading
  negated classes (`[^x]`, `[^x]e`) and `NFD`/`NFKD`/no-normalization pipelines remain accepted.

No STOP condition applied: no grammar/fingerprint/dependency/MSRV/public-contract change; the
narrowing is the approved conservative negation policy.

## 2. Files changed

- `crates/trawler-core/src/analysis/term.rs`
- `crates/trawler-core/tests/analysis_review_amendment_05.rs` (new, 56 tests)
- `docs/ARCHITECTURE.md` (negated-class boundary note)
- `docs/pr-artifacts/pr-4/review-amendment-05-{preflight,tests,report}.md`

Amendments 01–04 artifacts are unchanged. No protected/file-map deviations.

## 3. Gate results (final run)

| Command | Result |
|---|---|
| `cargo +1.85.0 check --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **529 passed; 0 failed; 1 ignored** |
| `cargo test -p trawler-core --test analysis_review_amendment_05` | PASS — 56 |
| `cargo test -p trawler-core --test analysis_review_amendment_04` | PASS — 45 |
| `cargo test -p trawler-core --test analysis_review_amendment_03` | PASS — 27 |
| `cargo test -p trawler-core --test analysis_review_amendment_02` | PASS — 30 |
| `cargo test --workspace --all-targets` | PASS — **529 passed; 0 failed; 1 ignored** |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **94.24% lines**, 91.34% functions, 93.92% regions |
| `cargo doc --workspace --no-deps` | PASS |

Red-before / green-after: the A5 matrix was **31 passed / 25 failed** at baseline `29636c8` and
**56 / 0** after. No failing gate remained; no failure required classification beyond the
reproduced bypasses. Toolchains: stable 1.99.0, MSRV cargo 1.85.0. The 1 ignored test is
pre-existing (unrelated).

## 4. Integration topology

In-process public path only: real `AnalyzerRegistry`/`AnalyzerDefinition` →
`collect_tokens(AnalyzerRole::Index, …)` and public `prepare_regex` with matching analyzer
fingerprint. PR 4 has no persisted index or regex executor; PR 5 (segments) and PR 8 (matching)
are not implemented and no end-to-end search is claimed. No RustFS/network topology applies.

## 5. Residual limitations

- Case-stability of negated classes under case folding is a separate property (not in this
  amendment's scope); class negation is handled for leading-combining safety only.
- Class set operators (intersection/difference/symmetric difference) and Unicode/Perl shorthand
  membership remain conservatively unsafe at a boundary rather than proven.
- Regex execution is PR 8; analyzer-identity persistence is PR 5. Roadmap PR 4 remains PLANNED.
