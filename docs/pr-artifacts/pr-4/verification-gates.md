# PR 4 — verification gates V1–V5 and dependency/license evidence

**Branch:** `dev/analyzer-contract` **Implementation commit:** `1baff06` (not pushed, not merged).
**Authority:** `docs/decisions/PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md` (HUMAN APPROVED
WITH CHANGES, 2026-10-12).
**Predecessor preflight:** `docs/pr-artifacts/pr-4/stop-report.md` (preserved; PR 2 #6 and
PR 3 #13 verified merged with green CI).

## V1 — library behavior and MSRV

**Dependency MSRV verification (PASS).** The exact crate/feature set was built and exercised on
Rust 1.85.0 in an isolated scratch crate pinned to the same transitive ICU4X versions as the
workspace lock (`icu_locale_core =2.1.1`, `icu_provider =2.1.1`; 2.3.x require Rust 1.88):

```text
cargo +1.85.0 build   # Finished dev profile
cargo +1.85.0 test --lib   # 1 passed; 0 failed
```

The scratch test asserted full Unicode case folding (`Straße` -> `strasse`), NFC composition,
UAX #29 word segmentation, Snowball English stemming, UTS #46 IDNA (`BÜCHER.example` ->
`xn--bcher-kva.example`), PSL API usage, UTS #39 skeleton, and RustCrypto `sha2`.

**Workspace MSRV verification (BLOCKED — pre-existing).** `cargo +1.85.0 test -p trawler-core`
fails to compile **existing PR 2 contract code** that uses `if let … && …` let-chains
(stabilized in Rust 1.88, edition 2024), despite the workspace declaring
`rust-version = "1.85"`. Confirmed 10 occurrences across
`contract/{schema,query,batch,aggregation,result}.rs`. The new `analysis` module is
let-chain-free. This is a pre-existing repository/MSRV inconsistency, not introduced by PR 4;
fixing it would require changing PR 2 code or raising MSRV, which is outside PR 4's authority.
See the final report's BLOCKED entry and required human decision.

**Runtime/library behavior (PASS):** all pinned crate APIs were verified against the installed
crate sources (`icu_casemap` `CaseMapper::fold_string`, `unicode_security::skeleton` +
`UNICODE_VERSION`, `idna::uts46::Uts46::to_ascii`, `publicsuffix::{List,IcannList}` +
`psl_types::List` trait, `rust_stemmers::Stemmer`, `unicode_segmentation::UnicodeSegmentation`).
No speculative method names are used.

## V2 — datasets (PASS)

| Dataset | Source | Pinned identity | SHA-256 | License |
|---|---|---|---|---|
| Public Suffix List | `https://publicsuffix.org/list/public_suffix_list.dat`, retrieved 2026-10-12 | `2026-10-07_07-28-19_UTC`, commit `3929462652695bad04f0a27afb600974014a3c8b` | `ba7d836c0ea57a8bcf9f1fcb868066a7554bed029b441ecc6204ad8494a32612` | MPL-2.0 (file-level; included unmodified with notice) |
| Snowball English stopwords | `https://snowballstem.org/algorithms/english/stop.txt`, retrieved 2026-10-12 | `snowball-english-stop.txt@2026-10-12` | `06b8b14bbe6f6e0b64c0830813819416d96a71bec1655668d83b3e602a651db6` | BSD-3-Clause (Snowball) |

Files: `crates/trawler-core/src/analysis/data/{public_suffix_list.dat,english_stopwords.txt}`,
provenance in `.../data/PROVENANCE.md`. The stopword parser strips comments and sorts into a
`BTreeSet`, so behavior is independent of file ordering. Unit tests recompute both SHA-256
digests and assert the PSL header version/commit, so accidental edits fail the build.
No dataset is fetched at runtime.

## V3 — term-pattern correctness (PASS)

`prepare_glob` parses patterns into `Literal`/`AnySequence`/`AnyChar` segments; only literal
runs pass through `Normalize`/`CaseFold`/`AsciiFold`, while `*`, `?` and `\` escaping are
preserved and re-serialized. Stop-word and stemmer filters are never applied to patterns.
`prepare_regex` validates the bounded subset (balanced groups/brackets, no `(?` extensions,
no `\1` backreferences, no stacked quantifiers, valid `{m}`/`{m,n}`/`{m,}`), rejects unsupported
constructs with `UnsupportedPattern`, applies only canonical normalization, and never
case-folds or stems. Tests: `a4_13_prefix_glob_regex_contract`,
`term::tests::{glob_preserves_operators_and_escapes,regex_is_not_case_folded_or_stemmed,
regex_validator_rejects_lookaround_backreference_and_unbalanced}`.

## V4 — work and cancellation budgets (PASS)

Design recorded **before** implementation in
`docs/pr-artifacts/pr-4/v4-work-cancellation-budget-design.md`: 1 work unit per input scalar,
per raw token, per stopword lookup, and `1 + term.len()` bytes per length-changing filter;
`u64::checked_add` only; cancellation polled deterministically every 1024 work units and at
value boundaries. Tests: `work::tests::{charges_and_enforces_limit,overflow_is_checked,
polls_cancellation_at_boundaries,explicit_check_polls_cancellation}`,
`a4_08_exact_limit_succeeds_and_one_over_fails`, `a4_09_cancellation_at_start_and_mid_analysis`,
`i4_04_cancellation_and_resource_bounds_through_public_api`.

## V5 — compatibility (PASS)

The analyzer fingerprint is a self-contained canonical encoding of analyzer configuration and
pinned data identities. It has no dependency on any PR 5 format, and no segment codec, manifest,
writer, reader or postings type is introduced. `docs/ARCHITECTURE.md` documents the PR 5/6/8
boundary.

## D-GATE evidence

| Gate | Decision | Evidence |
|---|---|---|
| D-GATE-1 | `icu_casemap =2.0.1` for full folding; keep MSRV 1.85; no 2.3.0 | V1 dependency build/test on 1.85.0; workspace let-chain blocker reported separately |
| D-GATE-2 | `publicsuffix =2.3.0` + committed pinned `public_suffix_list.dat`; no runtime fetch | V2 table; `domain_data::psl()` parses embedded list; `DomainDatasetIdentity::matches_embedded` |
| D-GATE-3 | Record actual data versions; include in fingerprint | Table below; encoded in `AnalyzerDefinition::fingerprint` |
| D-GATE-4 | Inspect shipped license texts and compatibility | Table below; `LICENSES/{MPL-2.0,Unicode-3.0,BSD-3-Clause-Snowball}.txt` added |

### Exact data versions (D-GATE-3)

| Library | Version | Data identity (verified source) |
|---|---|---|
| `unicode-normalization` | 0.1.25 | `UNICODE_VERSION = (17, 0, 0)` |
| `unicode-segmentation` | 1.13.3 | `UNICODE_VERSION = (17, 0, 0)` |
| `icu_casemap` / `idna` backend | 2.0.1 / 1.1.0 | ICU4X 2.0 data: "generated with CLDR version 47.0.0, ICU version icu4x/2025-05-01/77.x" (`icu_casemap_data` 2.0.0 README) |
| `unicode-security` (UTS #39) | 0.1.2 | `UNICODE_VERSION = (16, 0, 0)` |
| `publicsuffix` | 2.3.0 | PSL `2026-10-07_07-28-19_UTC` commit `39294626…` |
| `rust-stemmers` | 1.2.0 | Snowball English algorithm |
| `sha2` | 0.11.0 | RustCrypto (no custom crypto) |

### Shipped license review (D-GATE-4)

| Crate/data | Manifest license | Shipped file | Assessment |
|---|---|---|---|
| `unicode-normalization`, `unicode-segmentation`, `unicode-security`, `idna`, `sha2` | MIT OR Apache-2.0 | `LICENSE-APACHE` + `LICENSE-MIT` | Compatible with Apache-2.0 core |
| `icu_casemap` (+ `icu_*_data`) | Unicode-3.0 | `LICENSE` = "UNICODE LICENSE V3" | Permissive/OSI-approved; added `LICENSES/Unicode-3.0.txt` |
| `rust-stemmers` | MIT/BSD-3-Clause | `LICENSE` (MIT) | Permissive; compatible |
| `publicsuffix`, `psl-types` (code) | MIT/Apache-2.0 | `LICENSE` (MIT) + `LICENSE-APACHE` | Compatible |
| Public Suffix List (data) | MPL-2.0 | header notice retained | File-level copyleft; included **unmodified** with the MPL notice, `LICENSES/MPL-2.0.txt` added. `trawler-core` source remains Apache-2.0. Flagged for legal review before commercial distribution; no modification of MPL data. |
| Snowball stopwords (data) | BSD-3-Clause | text preserved | Permissive; `LICENSES/BSD-3-Clause-Snowball.txt` added |

No hand-written Unicode, IDNA, UTS #39 or cryptographic algorithm is implemented.
