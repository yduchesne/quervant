# PR 4 — Approved analyzer parameters: binding implementation amendment

**Status:** HUMAN APPROVED WITH CHANGES — 2026-10-12. **Scope:** PR 4 only.
**Authority:** Trawler owner explicitly approved the assistant's T01–T08 and D-GATE-1…4 recommendations and refinements in the planning conversation on 2026-10-12.
**Precedence:** This amendment supersedes inconsistent draft/proposed language in `PR04_ANALYZER_PARAMETER_DECISIONS.md` and the downloadable PR 4 detailed plan. The original plan's acceptance, evidence, artifact and STOP rules otherwise remain binding.
**Authorization:** Coding agent may resume PR 4 Phases 1–6 on `dev/analyzer-contract` after completing verification gates below. **Do not merge.** No PR 5 format freeze is authorized.

## Approved selections and implementation rules

| ID | Approved decision | Binding detail |
|---|---|---|
| T01 | A — UTF-8 term representation | Built-in terms are valid UTF-8; no arbitrary binary term API in PR 4. Reject invalid/oversize output; preserve exact emitted bytes. |
| T02 | A — position gap 100 | Each multi-value token carries `value_index` and source-value-relative UTF-8 byte range. Position increment between last token of previous value and first token of next must preserve a gap of **at least 100 positions** (test empty/stopword-only values); no synthetic concatenated source offsets. Any optional flat offset view must not be used for source highlighting. |
| T03a | A — NFC default, case folding opt-in | Text and Keyword default to NFC; explicit no-op supported. Opt-in **full Unicode case folding**, not simple lowercasing. Normalize terms at token-filter stage while preserving offsets in original input. A length-changing normalization of the term does **not** change the source offsets. Multi-term normalization preserves pattern metacharacters and escaping, and never stems patterns. |
| T03b | A — opt-in English stopwords and stemming | Use a reviewed, committed English stopword list with explicit provenance/version and deterministic ordering; pin `rust-stemmers =1.2.0` for opt-in Snowball English. Never stem keyword identities or wildcard/regex patterns. List contents and origin must be reviewed before shipping. |
| T04 | A — defer length-changing character filters | Reject unsupported character filters at config validation with typed error. Do not transform the whole source and falsely report transformed byte offsets as original. Token filters may change term length but must retain original source spans. |
| T05 | A — stable identity + canonical fingerprint | Explicit analyzer ID and semantic version; SHA-256 from a vetted library over a **version-tagged, length-delimited canonical byte encoding** with fixed field order, UTF-8 and unambiguous collection lengths. Include tokenizer/filter order, normalized config, dataset IDs and exact data versions, case-map/normalization/stemmer versions, and policy flags. No Debug strings, randomized hash maps or unspecified JSON encoding. Mismatch is typed incompatible/reindex-required; no silent reinterpretation. Do not implement SHA-256. |
| T06 | A — domain analysis | UTS #46 **nontransitional** IDNA; canonical DNS identity is distinct from reversed labels, PSL decomposition and UTS #39 confusable skeleton. Root dot representation is explicit; reject malformed labels. PSL includes both ICANN and private rules, with **explicit configurable policy** included in fingerprint. No runtime dataset download. |
| T07 | A — bounded analysis | Defaults: **1 MiB input bytes/value; 100,000 emitted tokens/value; 4 KiB term bytes**. These are enforceable limits (not unlimited hints); user may lower limits. Reject configurations exceeding these ceilings pending separately approved extension. All counters use checked arithmetic and typed errors. CPU/work limits and cancellation checkpoint details must be specified and tested before coding the corresponding execution path; see verification gate V4. |
| T08 | A — grammar contract only | `*` matches zero or more Unicode scalars; `?` matches one scalar; backslash escapes literal metacharacters. Regex bounded subset per `docs/ARCHITECTURE.md`, no lookaround/backreferences. Whole indexed term matching, not tokenized phrase matching. Parse/normalize contracts in PR 4; automata execution PR 8. Reject unsupported constructs explicitly. |

## Dependency gates: approved selection, mandatory verification

- **D-GATE-1:** Preserve workspace MSRV **Rust 1.85**. Select **`icu_casemap =2.0.1`** for full Unicode case folding; **do not** use 2.3.0 or raise MSRV. Verify the exact crate API, feature flags and transitive dependency resolution against a Rust 1.85 build before relying on it. If it cannot be made compatible, STOP; do not silently replace the dependency or drop folding.
- **D-GATE-2:** Select **`publicsuffix =2.3.0`** with a committed, reviewed, pinned `public_suffix_list.dat`. Record dataset source, retrieval date, hash (computed using vetted tooling/library), and license; do not fetch at runtime. Verify ICANN/private rule behavior with fixtures.
- **D-GATE-3:** Record **actual exact** Unicode normalization, case mapping, segmentation, IDNA, UTS #39 and PSL data versions from chosen dependencies and the committed dataset. Do not guess these from crate versions. Include exact versions and policy flags in fingerprint. If a library does not expose its data version, document and pin its exact crate version and embedded dataset identity from verified source; STOP if deterministic identity cannot be established.
- **D-GATE-4:** Inspect **shipped license texts** and transitive license compatibility, including Unicode-3.0 and the PSL dataset. The draft's manifest strings are **not** sufficient evidence. If incompatible/unclear, STOP and request a decision. No hand-written Unicode, IDNA, UTS #39 or cryptographic algorithms.

## Implementation interface clarification

The primary analyzer interface is a **bounded pull-based synchronous token iterator** (or equivalent fallible pull cursor), accepting borrowed input for its lifetime and emitting **owned term text**. A token retains `value_index`, absolute position, position increment, position length, and original-source UTF-8 byte offsets. Use typed errors for invalid configuration, budget exhaustion, incompatible analyzer, and cancellation. A convenience `collect` API may return `Vec<Token>` only with the same bounded budgets. No Tokio dependency or asynchronous executor is required for tokenization. Do not implement query result streaming in PR 4.

## Remaining verification-only STOP gates (not new architectural choices)

**V1 — library behavior:** verify exact pinned crate APIs/Unicode behavior on Rust 1.85 and record evidence in `docs/pr-artifacts/pr-4/`. No speculative method names.
**V2 — datasets:** select and check in the exact English stopword file and PSL snapshot with provenance and license; document data versions. If source selection creates materially different semantics, STOP for human review.
**V3 — term-pattern correctness:** ensure pattern normalization cannot rewrite wildcard operators, escaping or regex syntax. If the proposed API cannot guarantee this without implementing PR 8 automata, STOP and propose a narrow grammar-only alternative; do not implement unapproved pattern semantics.
**V4 — work and cancellation budgets:** before implementing the analyzer iterator, write a short design note in `docs/pr-artifacts/pr-4/` proposing concrete finite work-unit accounting and cancellation polling interval, with tests for exact capacity, overflow and cancellation. This is an **implementation parameter verification gate**, not license to introduce unlimited or implementation-defined work. If unable to define enforceable deterministic bounds, STOP and request human approval.
**V5 — compatibility:** keep analyzer config/fingerprint independent of the future PR 5 physical format; do not create a segment codec or publish manifests in PR 4.

## Instructions to coding agent

1. Rebase/reconcile with current `main`; preserve the already-written Phase 0 report and baseline evidence. Verify predecessor merges/CI as already documented; rerun tests if base changed.
2. Treat T01–T08 and D-GATE-1…4 as **approved with these modifications**; do **not** stop merely because historical draft rows contain the word `proposed`.
3. Satisfy V1–V5; if blocked, report exact dependency/file, reproducible evidence, and smallest required decision. Do not improvise architecture.
4. Execute original PR 4 plan Phases 1–6; map unit and integration tests to the original A4 test IDs. Exercise real production analyzer/term-query preparation path, not only fakes.
5. Run required CI commands from `.github/workflows/ci.yml`: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace --all-targets`, `cargo llvm-cov --workspace --all-targets --fail-under-lines 85`, `cargo doc --workspace --no-deps`. Explicitly test compatibility with Rust 1.85. Record commands, exit codes, coverage, topology and negative tests.
6. Put **every coding-agent report** under `docs/pr-artifacts/pr-4/` (lowercase, hyphenated), including design verification, test transcripts/summaries and final report. Do not mark PR 4 DONE until acceptance actually passes. Do not merge without user authorization.

## Completion criteria

A PR 4 implementation is eligible for review only when approved semantics, MSRV/license/dataset verification, required test matrix, integration slices, >=85% production Rust workspace line coverage and repository CI all pass with recorded evidence. PR 5 format decisions remain separate.
