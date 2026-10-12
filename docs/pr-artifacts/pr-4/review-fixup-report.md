# PR 4 review fixup — final report

**Branch:** `dev/analyzer-contract`
**Base reviewed HEAD:** `5fcf4c4`
**Fixup commit:** `0c26149`
**Scope:** six independent-review findings on the PR 4 analyzer subsystem. No protected file
(`contract/**`, `storage/**`, object-store, distributed, PR 5/6/8, datasets/licenses) changed.
**Status:** all six findings addressed with executed negative tests and full CI-equivalent
evidence; ready for review. **Not merged.**

## 1. Findings and fixes

| ID | Severity | Change |
|---|---|---|
| R4-01 | HIGH | Replaced the hand-rolled `validate_regex`/`valid_repetition` with the parser-only `regex-syntax` AST. Malformed syntax and forbidden constructs (lookaround, backreferences, invalid ranges/repetitions, dangling escapes, unclosed groups/classes) are rejected typed before any execution; stacked quantifiers rejected explicitly. |
| R4-03 | HIGH | `prepare_regex` now normalizes **literal AST nodes only** with the same ordered `Normalize`/`CaseFold`/`AsciiFold` transforms as indexed terms. Inline flags, named captures, length-changing literal expansions and case-unstable classes under a case-transforming analyzer are rejected typed; the serialized pattern is re-parsed and re-validated. No regex is executed. |
| R4-04 | MEDIUM | Added `AnalyzerRegistry::resolve_fingerprint(name, version, fingerprint)` returning a typed `AnalyzerFingerprintMismatch`; documented `resolve_compatible` as version-only. This is the PR 5 persisted-identity seam. |
| R4-05 | MEDIUM | `psl()` is now fallible (`OnceLock<Result<PslData, AnalysisError>>` + `parse_psl`); a malformed embedded PSL is a typed `InvalidDataset` error instead of an empty-list success. |
| R4-06 | MEDIUM | Emitted-token ceiling is enforced **per value** (reset at each value), not call-wide; the work budget remains call-wide and position/offset/gap invariants are unchanged. |
| R4-02 | HIGH | Tokenizers are now lazy pull cursors (`SpanCursor` for keyword/whitespace/UAX #29 words); `AnalysisCursor` scans at most to the next retained token, retaining raw positions for stopword holes and the value gap, charging work incrementally with deterministic cancellation checkpoints. Opaque domain calls are charged/polled around (documented as uninterruptible). |

Added dependency: `regex-syntax = "0.8"` (resolved 0.8.11; `MIT OR Apache-2.0`; manifest MSRV
1.65; parser-only — no matching/automata).

## 2. Files changed

- `crates/trawler-core/src/analysis/{term,tokenizer,analyzer,work,domain,domain_data,registry,error,limits}.rs`
- `crates/trawler-core/tests/analysis_review_fixup.rs` (new, 19 tests)
- `crates/trawler-core/Cargo.toml`, `Cargo.lock`
- `docs/ARCHITECTURE.md` (implemented-API clarifications)
- `docs/pr-artifacts/pr-4/{review-fixup-preflight,review-fixup-work-budget,review-fixup-tests,review-fixup-report}.md`

## 3. Gate results (final run, workspace root)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — **370 passed; 0 failed; 1 ignored** |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — **370 passed; 0 failed; 1 ignored** |
| `cargo +1.85.0 check --workspace --all-targets` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **94.25% lines**, 91.32% functions, 93.84% regions |
| `cargo doc --workspace --no-deps` | PASS |

Targeted: `cargo +1.85.0 test -p trawler-core --lib analysis` = 62 passed;
`cargo +1.85.0 test -p trawler-core --test analysis_review_fixup` = 19 passed.
Toolchains: `rustc/cargo 1.99.0` (stable) and `cargo 1.85.0` (MSRV).

No failure required classification: the suite is green on both toolchains.

## 4. Deviations, limits and notes

- **Approved grammar reuse:** the regex subset and normalization policy are exactly the approved
  T03a/T08 direction; no unapproved extension was introduced. `a|` remains accepted because the
  approved subset does not forbid empty alternatives (documented and tested).
- **Conservative rejection:** case-unstable bracketed classes (`[A-Z]`), Unicode property classes
  under folding, inline flags and named captures are rejected rather than transformed. This
  favors explicit failure over silent false negatives, as the plan permits.
- **Opaque calls:** UTS #46/ToUnicode/PSL/UTS #39 cannot be interrupted mid-call; the 1 MiB
  per-value bound is enforced before them and they are charged/polled around.
- **PSL license:** embedded list remains MPL-2.0, included unmodified with notice (unchanged from
  prior acceptance).
- `docs/ROADMAP_V01.md` PR 4 remains **PLANNED** (not merged); no DONE marker added.
- No merge performed.
