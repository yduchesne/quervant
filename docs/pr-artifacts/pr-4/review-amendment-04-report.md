# PR 4 review amendment 04 — final report

**Branch:** `dev/analyzer-contract`
**Starting HEAD:** `1de1fe01828097c2d7c139ce37c96d1365a12601`
**Fixup commit:** `<recorded after commit>`
**Disposition:** narrow parser-only fixup; **not merged**; roadmap PR 4 remains PLANNED.

## 1. Finding addressed (R4-08 HIGH)

Amendment 03's boundary check inspected only the first child of a concatenation and treated
character classes as safe, so nullable prefixes and accepted classes could hide a combining
scalar that composes with a preceding matched character during indexed-term normalization,
producing a prepared regex that silently misses the normalized index.

**Fix (`crates/trawler-core/src/analysis/term.rs`, no public API change):**
- Replaced the first-child-only `starts_with_combining` with a nullable-aware
  `LeadingInfo { nullable, may_start_with_combining }` computed for every AST node:
  - `Empty`/assertions: nullable, not combining; literals: leading class from the configured
    transforms; `Dot`: may start with combining; Perl/Unicode classes: may start with combining;
    bracketed classes: bounded proof over the class set.
  - Concatenation ORs `may_start_with_combining` over children reachable after nullable
    prefixes; alternation ORs over branches; repetition derives `(nullable, can_repeat)` from
    `RepetitionKind`/`RepetitionRange` (`?`, `*`, `+`, `{0}`, `{0,n}`, `{1,n}`, `{n}`, `{n,m}`).
  - Bracketed classes: a range is proven safe only when every scalar in the bounded (≤4096)
    interior is transform-stable with combining class zero; literal members are checked the same
    way; `BinaryOp` (intersection/difference) and Unicode/Perl classes are conservatively unsafe;
    POSIX ASCII classes are safe.
- `process_concat` now consults `LeadingInfo` for every non-first child and still rejects
  preceded literal runs whose transformed first scalar is combining.
- Work budget/cancellation/nesting limits are preserved; the new traversal polls cancellation
  and reuses `apply_pattern_transforms` for charging. No regex is compiled or executed.

No STOP condition applied: no grammar/fingerprint/MSRV/dependency change, and the narrowed
acceptance (`.`/`\w`/`\p{...}` after a preceding expression) is the plan's explicitly approved
conservative policy with demonstrated unsafe boundaries.

## 2. Files changed

- `crates/trawler-core/src/analysis/term.rs`
- `crates/trawler-core/tests/analysis_review_amendment_04.rs` (new, 45 tests)
- `docs/ARCHITECTURE.md` (nullable-aware/class/`.`/Perl boundary policy)
- `docs/pr-artifacts/pr-4/review-amendment-04-{preflight,tests,report}.md`

Amendment 01–03 artifacts are unchanged.

## 3. Gate results (final run)

| Command | Result |
|---|---|
| `cargo +1.85.0 check --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **473 passed; 0 failed; 1 ignored** |
| `cargo test -p trawler-core --test analysis_review_amendment_04` | PASS — 45 |
| `cargo test -p trawler-core --test analysis_review_amendment_03` | PASS — 27 |
| `cargo test -p trawler-core --test analysis_review_amendment_02` | PASS — 30 |
| `cargo test --workspace --all-targets` | PASS — **473 passed; 0 failed; 1 ignored** |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **94.14% lines**, 91.34% functions, 93.80% regions |
| `cargo doc --workspace --no-deps` | PASS |

Red-before / green-after: the A4 matrix was **39 passed / 6 failed** at baseline `1de1fe0` and
**45 / 0** after the fix. No failure remains; none required classification beyond the
reproduced bypasses. Toolchains: stable 1.99.0, MSRV cargo 1.85.0.

## 4. Integration topology

In-process public path only: real `AnalyzerRegistry`/`AnalyzerDefinition` →
`collect_tokens(AnalyzerRole::Index, …)` and public `prepare_regex` with matching analyzer
fingerprint. PR 4 has no persisted index or regex executor; PR 5 (segments) and PR 8 (matching)
are not implemented and no end-to-end search is claimed. No RustFS/network topology applies.

## 5. Conservative behavior changes (documented, approved by the plan)

Under composing normalization (`NFC`/`NFKC`), the following now reject typed because they can
match a combining scalar after a starter: `e.`, `e.*`, `e\w` (and equally `e\d`, `e\s`,
`e\p{...}`). Standalone/leading forms and safe classes/ranges (`e[0-9]`, `e[a-z]`, `e(?:xy)`,
`e(?:x?y)`) remain accepted. Decomposition-only and no-normalization pipelines are unchanged.
No prior test asserted these patterns; no earlier test was modified.

## 6. Residual limitations

- Class intersection/difference/symmetric-difference and Unicode/Perl shorthand membership are
  treated conservatively (rejected when trailing a preceding expression) rather than proven.
- A single UAX #29 word segment remains atomic (Amendment 02 note).
- Regex matching/execution is PR 8; analyzer-identity persistence is PR 5.
