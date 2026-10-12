# PR 4 — implementation report

**Title:** Versioned analyzers and deterministic token contracts
**Branch:** `dev/analyzer-contract`
**Base commit:** `6fa5692` (`docs(pr4): add binding coding-agent amendment for approved analyzer parameters`)
**Implementation commit:** `773fdb3` (feature branch `dev/analyzer-contract`; not pushed, not merged).
**Authority:** `docs/decisions/PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md` (HUMAN APPROVED
WITH CHANGES) and the original PR 4 detailed plan (which remains authoritative except where the
amendment supersedes it).
**Status:** implementation and local gates **PASS**; one **BLOCKED** sub-gate (workspace build
on Rust 1.85 — pre-existing) requiring a human decision. **Not marked DONE. No merge.**

## 1. Summary

Implemented the complete PR 4 analyzer subsystem in `trawler-core::analysis`: token model,
tokenizers, ordered filters, bounded pull cursor, deterministic analyzer registry and
fingerprints, schema bindings, term-query preparation, and optional pinned domain analysis.
Reused the existing `contract::Schema`/`FieldDefinition` bindings and did not touch PR 3
storage, PR 5 codecs, PR 6 lifecycle, or PR 8 automata.

All mandatory local checks pass on the CI toolchain (stable 1.99.0). Line coverage is
**94.04%** (floor 85%). The only blocker is the pre-existing workspace MSRV inconsistency
described in §6.

## 2. Deliverables

- `crates/trawler-core/src/analysis/` — `mod, error, limits, token, cancellation, work, config,
  tokenizer, filters, analyzer, registry, term, domain, domain_data`.
- `crates/trawler-core/src/analysis/data/` — pinned `public_suffix_list.dat`, `english_stopwords.txt`,
  `PROVENANCE.md`.
- `crates/trawler-core/tests/analysis_contract.rs`, `tests/domain_analysis.rs`,
  `tests/fixtures/analysis/golden.tsv`.
- Dependency additions in `crates/trawler-core/Cargo.toml` + regenerated `Cargo.lock`.
- `LICENSES/{MPL-2.0,Unicode-3.0,BSD-3-Clause-Snowball}.txt`.
- `docs/ARCHITECTURE.md` updated with the implemented analyzer API and PR 5/6/8 boundary.
- Phase 0 evidence preserved: `docs/pr-artifacts/pr-4/stop-report.md`.
- `docs/pr-artifacts/pr-4/v4-work-cancellation-budget-design.md`,
  `docs/pr-artifacts/pr-4/verification-gates.md`, this report.
- `docs/ROADMAP_V01.md` — PR 2/PR 3 status reconciled (previous task); PR 4 status note added
  without marking DONE.

## 3. Test matrix coverage

A4-01…A4-22 and I4-01…I4-04 are implemented as named tests and executed; A4-22 also relies on
the full workspace regression suite. Key mapping:

| ID | Where |
|---|---|
| A4-01/02/03/04/05/06/07/08/09/10/11/12/13/18/19/20/21/22 | `tests/analysis_contract.rs` (named `a4_*`) |
| A4-07 position-overflow path | `analysis::analyzer::tests::position_overflow_is_checked` |
| A4-14/15/16/17 | `tests/domain_analysis.rs` (named `a4_*`) |
| I4-01 | `tests/analysis_contract.rs::i4_01_*` |
| I4-02 | `tests/domain_analysis.rs::i4_02_*` |
| I4-03 | `tests/analysis_contract.rs::i4_03_*` |
| I4-04 | `tests/analysis_contract.rs::i4_04_*` |

## 4. Command results (final run, CI toolchain)

Working directory: workspace root. Toolchain: `rustc 1.99.0`, `cargo 1.99.0`, `cargo-llvm-cov 0.9.1`.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | **PASS** |
| `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** |
| `cargo test --workspace --all-targets` | **PASS — 342 passed; 0 failed; 1 ignored** |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | **PASS — 94.04% lines, 90.87% functions, 93.93% regions** |
| `cargo doc --workspace --no-deps` | **PASS** |
| `cargo +1.85.0 build/test` (dependency isolation, V1) | **PASS** (see `verification-gates.md`) |
| `cargo +1.85.0 test -p trawler-core` (whole workspace) | **BLOCKED — pre-existing let-chains** (§6) |

New-module coverage (lines): analyzer 92.21%, cancellation 100%, config 94.12%, domain 88.89%,
domain_data 96.67%, error 100%, filters 97.62%, limits 88.66%, registry 88.59%, term 87.02%,
token 100%, tokenizer 100%, work 100%.

## 5. Behavioral verification highlights

- Deterministic token equality across runs and parallel threads (A4-11, A4-21).
- Original-input offsets preserved through length-changing normalization/case folding (A4-03).
- Stopword position holes and the 100-position multi-value gap, including empty values (A4-04, A4-05).
- Exact-at-limit succeeds / one-over fails for input and token budgets (A4-08); typed
  cancellation at start and mid-analysis (A4-09); typed overflow (A4-07).
- Fail-closed registry/version binding (A4-10, I4-03); schema type restrictions preserved
  (A4-18); analyzer-free schema valid (A4-19).
- Real Schema -> registry -> multi-value tokenization -> term preparation (I4-01).
- Domain: UTS #46 nontransitional canonical identity, root dot, reversed labels, PSL private
  policy, identity-vs-skeleton separation, verifiable pinned dataset identity (A4-14…17, I4-02).

## 6. BLOCKED sub-gate and required human decision

**Gate:** V1 / D-GATE-1 "verify on a Rust 1.85 build".

The new dependency set is verified MSRV-compatible on Rust 1.85.0 in isolation. However the
**existing workspace cannot compile on Rust 1.85** because PR 2 contract files use
`if let … && …` let-chains (stable only in Rust 1.88, edition 2024):
`contract/{schema,query,batch,aggregation,result}.rs` (10 occurrences), while
`Cargo.toml` declares `rust-version = "1.85"`. The `analysis` module itself contains no
let-chains.

This is a **pre-existing** condition (CI uses `dtolnay/rust-toolchain@stable`, currently 1.99),
not a PR 4 regression, and fixing it means either editing PR 2 code or raising MSRV — outside
PR 4's authorized scope. **Smallest human decision needed:** either (a) authorize a
behavior-preserving let-chain refactor of the PR 2 contract files, or (b) raise the workspace
`rust-version` to `1.88`. Until then, the workspace-wide Rust 1.85 gate is **BLOCKED / NOT
VERIFIED**; the dependency-level MSRV gate is satisfied.

## 7. Unresolved items / notes

- **PSL license:** the embedded Public Suffix List is MPL-2.0 (file-level). It is included
  unmodified with its notice and `LICENSES/MPL-2.0.txt`. Flagged for legal review before
  commercial distribution; no modification of MPL-licensed data.
- No performance parity claims are made; no benchmark harness was added (not required by PR 4).
- RustFS integration is not applicable to PR 4.
- `docs/ROADMAP_V01.md` PR 4 is **not** marked DONE pending the blocked MSRV sub-gate.

## 8. Scope confirmation

No segment codec, writer, commit/manifest, reader/PIT, postings/term dictionary, FST/automata,
query executor, streaming transport, remote ObjectStore change, distributed or vector code was
introduced. `trawler-core` remains standalone and `#![forbid(unsafe_code)]`. **PR not merged.**
