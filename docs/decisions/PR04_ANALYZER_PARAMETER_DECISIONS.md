# PR 4 — Analyzer parameter decisions (HUMAN APPROVED — with binding addendum)

**Status:** **APPROVED WITH CHANGES (2026-10-12)**. The human approved the recommendations and refinements recorded in [`PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md`](PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md). That amendment is authoritative where this draft's proposed choices, placeholders, or STOP language differ. PR 4 implementation is authorized on the feature branch, subject to its dependency, licensing, and test gates; merging is not authorized.

**Plan:** `~/Downloads/TRAWLER_PR04_DETAILED_IMPLEMENTATION_PLAN.md` (PR 4).
**Parent approval:** [`docs/decisions/PR04_PR05_DESIGN_GATE_APPROVAL.md`](PR04_PR05_DESIGN_GATE_APPROVAL.md)
(2026-10-12) — T01–T08 approved **in principle only**; the concrete parameters below are
the open items the parent document explicitly left unresolved.

**Prepared:** Phase 0 preflight, `dev/analyzer-contract`, base SHA
`040b6a945e9e02c26bbf13660744ddceed177797`.

## How to use this document

- The proposed A choices are **approved with the binding clarifications in the approval amendment**; they are no longer open questions.
- The term **proposed** in historical tables denotes the approved A choice **as modified by the amendment**; do not treat historical wording as an unresolved gate.
- Alternatives, version/compatibility effects and the tests that will pin each choice are
  listed so approval is informed.
- Each row's approval is recorded globally in the human-approved amendment; historical blank row fields are superseded. STOP only for the explicit remaining verification gates in the amendment.

## Dependency-verification gate (required before selecting T03/T06)

Verified against the crates.io API on 2026-10-12. Licenses are the crate manifest strings and
**must still be confirmed against the shipped LICENSE files**. Workspace MSRV is **Rust 1.85**
(`Cargo.toml`, `rust-version = "1.85"`, edition 2024); `#![forbid(unsafe_code)]` applies.

| Capability | Candidate crate | Latest | Declared MSRV | License | Maintenance signal | Notes |
|---|---|---|---|---|---|---|
| Unicode normalization (NFC/NFD/NFKC/NFKD) | `unicode-normalization` | 0.1.25 | 1.36 | MIT OR Apache-2.0 | Active (2025-10-30) | Embeds a fixed Unicode data version; must be recorded in the fingerprint. |
| Unicode case mapping/folding | `icu_casemap` | 2.3.0 | **1.88 (exceeds 1.85)** | Unicode-3.0 | Active | **2.0.1 declares Rust 1.82** and is MSRV-compatible; 2.3.0 is not. |
| Unicode case folding (legacy) | `unicode-casefold` | 0.2.0 | none | MIT/Apache-2.0 | Abandoned (2016) | Not recommended without explicit risk acceptance. |
| Unicode word/grapheme segmentation | `unicode-segmentation` | 1.13.3 | 1.85.0 | MIT OR Apache-2.0 | Active (2026-06-01) | Exactly at MSRV. |
| Snowball stemming | `rust-stemmers` | 1.2.0 | none declared | MIT/BSD-3-Clause | Last published 2019 | Algorithm implementations are stable but low-maintenance; pin algorithm + crate. |
| Stopwords | `stop-words` | 0.10.1 | none declared | MIT OR Apache-2.0 | Active (2026-09-19) | Bundled multilingual lists; list origin/version must be pinned. |
| IDNA / UTS #46 | `idna` | 1.1.0 | 1.57 | MIT OR Apache-2.0 | Active (2025-08-21) | Presents UTS #46 profiles; profile/transitional flag is a T06 choice. |
| PSL decomposition (pinned list supplied by us) | `publicsuffix` | 2.3.0 | ~1.56.1 | MIT/Apache-2.0 | Active enough (2024-11-14) | **Does not download the list**; caller commits a pinned `public_suffix_list.dat`. Best fit for "no runtime fetch + pinned dataset". |
| PSL decomposition (embedded static list) | `psl` | 2.1.241 | none declared | MIT/Apache-2.0 | Very active (2026-10-08) | Embeds the list; list version is tied to the crate version, must be recorded. |
| UTS #39 mixed-script/confusable skeleton | `unicode-security` | 0.1.2 | none declared | MIT/Apache-2.0 | Last published 2024-09-12 | Implements UTS #39; embedded Unicode version must be recorded. |

Unresolved dependency questions that are part of this gate:

- **D-GATE-1 (MSRV):** approve `icu_casemap` 2.0.1 (MSRV 1.82, Unicode-3.0, Unicode 16 data)
  for case folding, or defer case folding. Using `icu_*` 2.3.0 requires raising MSRV to 1.88
  and is **not** approved by the current `rust-version = "1.85"`.
- **D-GATE-2 (PSL):** choose embedded `psl` (version-coupled list) vs `publicsuffix` +
  committed, reviewed pinned list file. The plan requires a pinned dataset and no runtime
  fetch; both satisfy "no runtime fetch".
- **D-GATE-3 (data versions):** record the exact embedded Unicode/UTS/PSL data versions for
  whichever crates are chosen, and make them part of the analyzer fingerprint (T05).
- **D-GATE-4 (license):** confirm each shipped LICENSE text permits Apache-2.0 linkage
  (Unicode-3.0 must be recorded, not assumed). No custom Unicode/IDNA/confusable/crypto
  implementation is permitted.

## T01 — Term byte representation

**Decision:** Must emitted term bytes be valid UTF-8, or may they be arbitrary bytes?

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | Terms are UTF-8 `String`/`Box<str>` for all built-in analyzers. | Simpler term dictionaries/FSTs (PR 5/8); lossless `&str`; no escaping ambiguity. Binary terms need a later, separately versioned extension. | A4-01, A4-02, A4-03, A4-20 |
| B | Arbitrary `Vec<u8>`/`Box<[u8]>` terms. | More general; forces byte escaping/identity rules into PR 5 format and every term-query surface. | A4-01, A4-02, A4-20 |

**Proposed rationale (A):** the initial built-ins produce text; deferring binary terms avoids
freezing an ambiguous byte contract into PR 5.

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## T02 — Multi-value position and offset gaps

**Decision:** exact position gap between field values, and the offset model for multiple values.

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | Position gap **100** between values; offsets returned as `(value_index, byte_range)` into the original source value; no fabricated bytes; a flat logical offset (`1`) only if a caller explicitly requests it. | 100 is the widely used convention and leaves room for same-value phrase expansion; `(value_index, byte_range)` is unambiguous and keeps original-offset integrity. | A4-05, A4-06, A4-07 |
| B | Position gap 1; globally concatenated logical offsets with a synthetic 1-unit separator. | Denser positions; requires fabricating a separator offset not present in source and risks accidental cross-value phrase matches. | A4-05, A4-06 |
| C | Configurable gap, default 100. | More knobs; config becomes part of the analyzer fingerprint. | A4-05, A4-06, A4-11 |

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## T03a — Default normalization and case folding

**Decision:** default Unicode normalization form; case-folding policy; whether keyword
normalizers and multi-term patterns are normalized the same way.

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | `Text`: **NFC** by default; Unicode **case folding is opt-in** (not implicit coercion); `Keyword` normalizer default NFC with an explicit no-op option; multi-term patterns normalized with the field's search analyzer/normalizer, never stemmed. | Freezing NFC as the default is a long-lived term-compatibility decision; changing it later is a reindex event. | A4-03, A4-12, A4-13, A4-18, A4-19 |
| B | NFKC default (compatibility normalization). | Stronger folding (full-width, ligatures) but changes meaning for some text; needs explicit acceptance. | A4-03, A4-18 |
| C | No default normalization; fully explicit per field. | Maximum control; more configuration and easier mismatch. | A4-03, A4-19 |

**Case-folding sub-choice:** simple vs full folding (e.g. `ß`), and whether lowercasing is
used instead. This is gated by D-GATE-1.

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## T03b — Stopwords and stemming

**Decision:** exact English stopword list and Snowball stemmer algorithm, with pinned
dataset/algorithm versions.

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | Pinned English stopword list committed as a reviewed fixture with a named version (origin recorded), and Snowball `english` via `rust-stemmers` pinned at `=1.2.0`. Stemming is opt-in per field and never applied to keyword identity or glob/regex patterns. | List/algorithm version becomes part of the analyzer fingerprint; any change is a reindex event. | A4-04, A4-12 |
| B | Use the `stop-words` crate list. | Convenient but ties term compatibility to that crate's list revisions unless the exact list is snapshotted into our fixtures. | A4-04, A4-12 |
| C | No built-in stopwords/stemmer in PR 4; ship only the filter extension point. | Narrowest scope; defers accepted roadmap capability. | A4-04 |

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## T04 — Offset correction for length-changing character filters

**Decision:** implement original-offset correction maps now, or reject/defer length-changing
character filters.

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | **Defer** length-changing character filters; reject them at configuration time with a typed error. Length-preserving character filters and all token filters must preserve original offsets. | Never emits incorrect offsets; can be added later behind a capability/fingerprint bump. | A4-03, A4-08, A4-20 |
| B | Implement a correction map (transformed byte -> original byte spans) in PR 4. | More capable; larger surface and more tests before PR 5. | A4-02, A4-03 |

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## T05 — Analyzer identity, canonical fingerprint, compatibility and reindex policy

**Decision:** representation of analyzer identity and what happens on version mismatch.

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | Stable explicit analyzer ID + semantic version + canonical fingerprint (SHA-256 via the already-present `sha2` RustCrypto crate) over: filter/tokenizer config, filter order, normalization form, stopword list ID/version, stemmer algorithm/crate version, and domain dataset versions. Unknown/incompatible version returns a typed error; consumers may surface a `reindex_required` result. | Frozen into PR 5 per-field/segment metadata; no silent reinterpretation of committed postings. | A4-10, A4-11, A4-17, A4-19 |
| B | Opaque version string only. | Simpler but does not detect semantic drift; higher risk of silent mismatch. | A4-10, A4-11 |

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## T06 — IDNA profile, PSL source/version/private-suffix policy, UTS #39 data/version

**Decision:** which IDNA profile and transitional behavior; PSL source and private-suffix
policy; UTS #39 implementation/data. All data pinned; **no runtime network fetch**.

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | `idna` UTS #46 (record transitional vs non-transitional explicitly), case-fold + NFC canonical form, trailing root dot handled as a labeled representation; `publicsuffix` with a committed, reviewed `public_suffix_list.dat` and its date recorded; explicit private-suffix policy (included vs ICANN-only); `unicode-security` UTS #39 skeleton. Identity (IDNA canonical) is a **different** field from skeleton. | Dataset versions become part of the fingerprint; invalid domains fail typed; skeleton match never equals identity. | A4-14, A4-15, A4-16, A4-17 |
| B | `psl` embedded list (version coupled to crate). | Simpler dependency; list updates require a crate bump. | A4-15, A4-17 |
| C | Defer D1–D4 entirely and split to a later PR. | Requires explicit human split/deferral decision per plan §6D STOP. | — |

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## T07 — Concrete resource limits, cancellation and typed errors

**Decision:** exact configurable defaults and hard ceilings.

| Limit | Proposed starting value (for consideration) | Notes |
|---|---|---|
| Max input bytes per value | 1 MiB | Typed budget error beyond; checked before analysis. |
| Max emitted tokens per value | 100 000 | Bounds materialization and PR 14 cursor work. |
| Max term bytes | 4 KiB | Prevents pathological single terms. |
| Max work / expansion units | implementation-defined, finite, checked | Strict checked arithmetic; no saturating positions. |
| Timeout / cancellation check interval | bounded token/filter interval | Typed `Cancelled`; never a complete partial stream. |

All defaults are proposed placeholders; the human must set or confirm the numbers. The
`A2` API-shape sub-decision (batch results vs pull/streaming sink, ownership/lifetime) must
also be recorded here before Part A2 is implemented.

| Option | Description | Tests |
|---|---|---|
| A (proposed) | Finite, configurable limits with documented hard ceilings and a typed error per limit kind. | A4-07, A4-08, A4-09, A4-20, A4-21 |
| B | Single aggregate budget only. | Weaker diagnostics; harder to prove bounds. |

**API-shape sub-decision:** bounded pull iterator, borrowed input and owned emitted terms; optional budgeted Vec collection. **APPROVED** — see binding approval amendment.

**Approval (limits):** APPROVED WITH CHANGES — see binding approval amendment.

## T08 — Prefix/glob/regex grammar and normalized-term boundary

**Decision:** exact grammar, escaping and normalized whole-term boundary; confirm no stemming
of patterns and no automata execution in PR 4.

| Option | Description | Version/compatibility effect | Tests |
|---|---|---|---|
| A (proposed) | Adopt the `docs/ARCHITECTURE.md` grammar: `*` = zero-or-more Unicode scalar values, `?` = one scalar value, backslash escaping; regex = bounded subset (classes, alternation, grouping, bounded quantifiers, Unicode classes), excluding lookarounds/backreferences/PCRE extensions. Patterns are normalized via the field's search analyzer and matched against whole indexed terms; **never** stemmed. PR 4 defines parse/normalize contracts only; PR 8 executes automata. | Frozen pattern semantics; PR 8 must not silently change them. | A4-13 |
| B | Delegate grammar to a third-party regex crate in PR 4. | Out of PR 4 scope and would prejudge PR 8's bounded automaton design. | A4-13 |

**Approval:** APPROVED WITH CHANGES — 2026-10-12; see binding approval amendment.

## Traceability to the PR 4 test matrix

T01 -> A4-01/02/03/20; T02 -> A4-05/06/07; T03a -> A4-03/12/13/18/19; T03b -> A4-04/12;
T04 -> A4-02/03/08/20; T05 -> A4-10/11/17/19; T06 -> A4-14/15/16/17; T07 -> A4-07/08/09/20/21;
T08 -> A4-13.

## Approval block (human decision)

- **Reviewer / owner:** Trawler project owner (approval in ChatGPT conversation)
- **Date:** 2026-10-12
- **Reference:** User message: “yes. Provide any amendment for the coding agent, if necessary”, approving the immediately preceding T01–T08 and D-GATE-1…4 recommendations and refinements.
- **Overall disposition:** **APPROVED WITH CHANGES**, as specified by [`PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md`](PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md).
- **Implementation authorization:** Resume PR 4 Phases 1–6 on `dev/analyzer-contract`, only after verification-only STOP gates in the amendment are satisfied. **No merge authorization.**
