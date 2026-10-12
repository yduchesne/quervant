# PR 4 / PR 5 — Human-approved architecture direction and unresolved design gates

**Human approval:** 2026-10-12, in the Trawler planning conversation, of the proposal titled *Trawler — PR 4 / PR 5 design-gate proposal*.

**Status:** T01–T08 and F01–F12 **APPROVED IN PRINCIPLE**, subject to the explicitly open choices and prerequisite gates below. This record is not an approval of a concrete binary layout, an on-disk format freeze, or coding-agent implementation authorization. It does not authorize merging any PR.

## Approved PR 4 directions (T01–T08)

- **T01:** token term, UTF-8 source byte offsets, absolute position, position increment and position length; validate boundaries and overflow.
- **T02:** stopword positional holes and multi-valued field position/offset separation.
- **T03:** composable character filters, tokenizers and ordered token filters; independently configured versioned index/search analyzers.
- **T04:** original-input byte offsets with correct correction mapping for length-changing transformations.
- **T05:** analyzer identity/version compatibility; no silent reinterpretation of old postings.
- **T06:** optional IDNA, reversed-label, PSL and UTS #39 derived domain fields, keeping canonical identity separate from similarity.
- **T07:** bounded analysis work with typed failures and cancellation.
- **T08:** explicit whole-term prefix/glob/regex grammar and normalization boundary; execution deferred to PR 8.

## Approved PR 5 directions (F01–F12)

- **F01:** versioned immutable, section-addressable segment container and integrity validation.
- **F02:** byte-exact logical document identity distinct from dense segment-local doc IDs; revisions assigned later by writer.
- **F03:** sorted term dictionary and lossless positional postings, subject to approved PR 4 token semantics.
- **F04:** bounded offset-addressable stored source and selective field projection.
- **F05:** typed DocValues-like per-document columns with explicit missing/null/empty/multivalue distinctions and family-aware IP/CIDR.
- **F06:** JSON ancestry preservation and conservative temporal/spatial metadata.
- **F07:** correct doc-ID remapping for physically sorted segments and merge-ready references.
- **F08:** PR 5 defines schemas/serialization; PR 6 owns publication, CURRENT, refresh, recovery and PIT lifecycle.
- **F09:** reuse PR 3 Directory/ReadHandle/WriteHandle and SegmentStore/SegmentCache boundaries; no new remote runtime dependency.
- **F10:** bounded segment-local iterators and selective reads for later streaming execution; PR 14 owns core result cursor.
- **F11:** golden fixtures, deterministic serialization, compatibility/corruption validation and fail-closed decoding.
- **F12:** explicit resource limits and typed exhaustion errors.

## Still open: human-selectable or evidence-based design details

The approval does **not** resolve questions that the approved proposal itself labeled open. A subsequent decision addendum must choose and document these **before the affected implementation or format freeze**:

1. **T01:** UTF-8-only term bytes versus arbitrary term bytes.
2. **T02:** exact multi-value position gap (100 proposed) and offset-gap semantics (logical 1 proposed).
3. **T03:** NFC/default normalization, Unicode case-fold policy, stopword/stemmer dataset and pinned versions.
4. **T04:** offset-correction implementation in PR 4 versus explicit deferral of length-changing char filters.
5. **T05:** analyzer fingerprint representation and upgrade/reindex policy.
6. **T06:** IDNA profile, pinned IDNA/PSL/UTS #39 dataset versions and private-suffix policy.
7. **T07:** concrete configurable resource defaults and typed-error mapping.
8. **F01:** exact header/section schema, checksum algorithm, one-file size envelope and multi-file strategy.
9. **F03:** postings block/skip encoding selected against explicit correctness/measurement criteria.
10. **F04:** initial compression choice and bounded block size.
11. **F12:** exact maximum segment size, documents, terms, postings, stored/decompressed block bytes and read budgets.

The F02/F05/F06/F07/F08/F09/F10/F11 constraints remain binding; none may be weakened to simplify implementation.

## Verified repository context and prerequisites

- PR 2 contract decision record `docs/decisions/PR02_CONTRACT_DECISIONS.md` says A01–A25 approved on 2026-10-11; approval is **contract-only**. Final PR 2 merge/CI evidence still requires explicit reconciliation.
- PR 3 storage implementation exists on `main` and is user-reported CI-passed/merged.
- `docs/STREAMING_SEARCH.md` is present on `main`.
- The roadmap currently lists PR 4 planned and PR 5 dependent on PRs 2–4.
- `G-DEDUP-MIN` and `G-CANON` remain open pre-PR 6.

## Execution order and STOP gates

1. Reconcile PR 2 merge and CI evidence against the actual GitHub PR; do not infer it from the ADR approval or code presence.
2. Finalize the T01–T08 open selections in an explicit, human-reviewed PR 4 decision addendum.
3. Prepare and review a detailed PR 4 coding-agent implementation plan based on current `main`; use `docs/pr-artifacts/pr-4` for reports.
4. Implement and validate PR 4 before PR 5, unless the human expressly changes the dependency.
5. Reconcile the PR 5 proposals with merged PR 4 code, resolve F01/F03/F04/F12 details in a human-reviewed addendum and then prepare the PR 5 detailed coding-agent plan; use `docs/pr-artifacts/pr-5`.
6. **STOP** if a coding agent is asked to decide any of the unresolved architecture or format choices, if a required predecessor is unmerged, or if the format would be frozen without the required decisions. No merge authorization is implied.

**Important:** This approval record deliberately distinguishes acceptance of design direction from approval of all specific parameters; it must not be presented as a fully specified codec implementation contract.
