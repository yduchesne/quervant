# PR 4 review amendment 02 — final report

**Branch:** `dev/analyzer-contract`
**Starting HEAD:** `591474524eee574c8d7e67b2b9ca5704ca4a5bd7`
**Fixup commit:** `<recorded after commit>`
**Disposition:** fixup only; **not merged**; roadmap PR 4 remains PLANNED.

## 1. Findings addressed

| ID | Severity | Fix |
|---|---|---|
| A2-01 | HIGH | `prepare_regex` now groups **decoded literal runs** (adjacent literal AST nodes in a concatenation) and normalizes the whole run, so cross-scalar NFC composition (`e`+U+0301 → `é`) and safe case expansion (`Straße` → `strasse`) are preserved. Quantified scalars that expand, combining marks that could compose across a quantifier/operator boundary, and empty run results are rejected typed; operators, groups, anchors and quantifiers are never rewritten. |
| A2-02 | HIGH | Keyword tokenizer charges **one unit per scalar** (was one whole-value `chars().count()` charge), so cancellation is polled during the scan. `UnicodeWordIndices::next()` is documented as **atomic per UAX #29 segment**; cancellation is polled before each segment and the segment is bounded by the 1 MiB per-value ceiling. Whitespace remains per-scalar. No inaccurate sub-1,024 guarantee is claimed for a single word segment. |
| A2-03 | MEDIUM | Class ranges are now proven stable over their **whole interior** (bounded to ≤4096 scalars), not just endpoints. `[@-a]` is rejected because its interior contains `A`–`Z`; `[0-9]`/`[a-z]` remain accepted. `ClassUnicode` is rejected under any term transform, `ClassPerl`/POSIX classes are accepted for NFC/NFD/case-fold with a documented closure argument and rejected under compatibility normalization; `[[:upper:]]` remains rejected. |
| A2-04 | MEDIUM | `AnalysisCursor` latches the first terminal error (`Option<AnalysisError>`). After an error, `next_token` returns the same error without scanning, emitting a token or charging work; `Ok(None)` (EOF) is idempotent. `collect_tokens` therefore never returns partial success. |

No STOP condition applied: the range-interior proof keeps `[0-9]` under `english` accepted, so no
conflict with T08 and no dependency/MSRV/public-contract change.

## 2. Files changed

- `crates/trawler-core/src/analysis/term.rs` (literal runs, `PatternPolicy`, range/interior class proof)
- `crates/trawler-core/src/analysis/tokenizer.rs` (keyword per-scalar charging, word-segment checkpoint)
- `crates/trawler-core/src/analysis/analyzer.rs` (terminal latch, overflow-latch unit test)
- `crates/trawler-core/tests/analysis_review_amendment_02.rs` (new, 30 tests)
- `crates/trawler-core/tests/analysis_review_fixup.rs` (authorized F4-09 update)
- `docs/ARCHITECTURE.md` (actual regex subset, class policy, honest cancellation boundaries)
- `docs/pr-artifacts/pr-4/review-amendment-02-{preflight,tests,report}.md`,
  `review-fixup-tests.md`, `review-fixup-work-budget.md` (amendment note; prior evidence preserved)

No new dependency; `regex-syntax 0.8.11` reused. No protected file (`contract/**`, storage,
object-store, distributed, PR 5/6/8) changed.

## 3. Gate results (final run)

| Command | Result |
|---|---|
| `cargo +1.85.0 check --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **401 passed; 0 failed; 1 ignored** |
| `cargo test --workspace --all-targets` | PASS — **401 passed; 0 failed; 1 ignored** |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **94.13% lines**, 91.29% functions, 93.79% regions |

Targeted `cargo +1.85.0 test -p trawler-core --test analysis_review_amendment_02` = 30 passed.
Toolchains: stable 1.99.0, MSRV cargo 1.85.0. No ignored/skipped tests were added.

## 4. Conservative behavior changes (authorized)

- `Straße` (unquantified) is now normalized to `strasse` rather than rejected; `Straße+` to
  `strasse+`. `ß+` (quantified expansion) is rejected. Pre-existing F4-09/unit tests were updated
  accordingly (see `review-amendment-02-tests.md`); prior evidence was not erased.
- Character classes under a term-transforming analyzer are now accepted only with a proof of
  stability. `[A-Z]`, `[@-a]`, `[[:upper:]]`, `\p{Lu}` are rejected (the first two previously
  `[A-Z]` rejected / `[@-a]` wrongly accepted). `[0-9]`, `[a-z]`, `\d`, `\w`, `\s`, `[[:lower:]]`,
  `[[:alpha:]]` remain accepted.

## 5. Residual limitations

- One UAX #29 word segment scanned by the pinned `unicode_segmentation` iterator is
  uninterruptible; cancellation latency is bounded by one segment (≤1 MiB value). Documented in
  `ARCHITECTURE.md` and the work-budget note. This is a verified library limitation, not a STOP
  (the plan permits documenting it when preserving exact UAX #29 segmentation).
- Compatibility (`NFKC`/`NFKD`) analyzers reject Perl/POSIX classes conservatively; no built-in
  analyzer uses compatibility normalization.
- PR 8 still owns regex automaton execution; PR 5 owns analyzer-identity serialization.
