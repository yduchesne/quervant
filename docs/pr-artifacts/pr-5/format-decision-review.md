# PR 5 format-decision review artifact

> **Status: AWAITING HUMAN REVIEW — no production codec authorized.
> Amendment 01 (R5-01–R5-08) applied.**
>
> Companion to `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`. This artifact
> exists so a human reviewer can approve or amend the F01–F12 binary-format
> decisions before any durable format is implemented, per
> `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md` §2 and §8, and the PR 5 Format
> Decision Amendment 01.

## 1. Why this gate exists

`docs/ROADMAP_V01.md` specifies PR 5 *capabilities* but deliberately does not fix
a byte-level durable format. `PR04_PR05_DESIGN_GATE_APPROVAL.md` states F01–F12
are approved **in principle** and that the concrete binary layout, size
envelopes and postings encoding remain open, to be resolved by a human-reviewed
addendum. That record explicitly says: **"STOP if a coding agent is asked to
decide any of the unresolved architecture or format choices."**

This review is that addendum's input. The agent may propose; it may not approve.

## 2. What was verified before proposing

- Fresh `main` = `a23cf25798e52fc181e93ac84505a07412f37463`; PR 4 merged
  (`9bc042d`); branch `dev/segment-codecs` includes amendment baseline `98762ed`.
  See `docs/pr-artifacts/pr-5/preflight.md` and
  `docs/pr-artifacts/pr-5/amendment-01-preflight.md`.
- Reusable seams confirmed: `contract::{schema,document,value,budget,capability}`,
  `analysis::{Token,AnalyzerFingerprint,AnalyzerRegistry::resolve_fingerprint}`,
  `storage::{Directory,ReadHandle,WriteHandle,SegmentId,SegmentDescriptor,
  SegmentCache}`, `trawler_objectstore::digest::{ContentDescriptor,ContentDigest}`.
- PR 4 positional semantics independently checked: `Token::new` rejects
  `position_increment == 0`; the analyzer computes increments with
  `checked_sub(previous).filter(|i| *i > 0)`; `POSITION_GAP = 100`. Equal positions
  for the same term in one document are impossible.
- Baseline QA: **639 passed / 0 failed / 1 ignored**; fmt/Clippy/docs pass;
  **87.74% workspace line coverage**; MSRV `rustc 1.85.0`.
- Integrity primitive: RustCrypto `sha2 = 0.11.0`; no custom cryptography.

## 3. Revised recommendation at a glance (post-Amendment 01)

| Area | Recommendation | Strongest alternative |
|---|---|---|
| F01 container | One sectioned container file; section-addressable, contiguous | Multi-file components + manifest |
| F02 envelope | `TRWSEG01`, LE, **fixed 64-byte EOF trailer** (no magic scan), SHA-256 `envelope_digest`, required/optional features | Backward scan; CRC-32C |
| F02.1 trust | Full verification against trusted PR 3 `ContentDescriptor`; selective reads reserved and **not** independently authenticated | Merkle-authenticated ranges (separate decision) |
| F03 schema | Canonical name-sorted dense `field_id`; PR 4 fingerprint stored | Name-keyed everywhere |
| F04 identity | Dense physical ids; byte-exact keys; revision/live refs only | Revisions only |
| F05 dictionary/postings | UTF-8-sorted per-field dictionary; varint delta postings; strict positive position deltas; **sequential `advance`**, no v1 skips | Fixed-width postings; v1 skip index |
| F06 stored source | Five-state vocabulary; per-doc presence bitmap; semantic typed preservation | Byte-for-byte request JSON |
| F07 columns | **Block-addressable** columns (`block_docs` uniform); O(1) directory arithmetic; fixed/variable layouts; family-tagged IP; tagged group keys | Column-major; byte-per-doc states |
| F08 bounds | Presence-aware `NO_VALUES`/`SOME`/`ALL`/`UNKNOWN` + pruning applicability truth table | Always-Unknown (safe but no pruning) |
| F09 remap | Timestamp asc then `DocumentKey` asc; stored bidirectional permutation | Doc-id tie-break |
| F10 manifest | Codec + validation only; **three distinct digest roles**; lifecycle fields omitted (or reserved-zero) | Publish manifest now |
| F11 caps | **Wire representability / safety budgets / operational policy** separated; 256 MiB is a preferred target | Single hard 256 MiB ceiling |
| F12 evolution | Major fail-closed; conservative minor rejection; committed goldens | Assume minor compatibility |

## 4. What Amendment 01 changed (R5-01–R5-08)

1. **R5-01 (F05):** added a binding `next`/`advance` behavioral contract, made
   the absence of v1 skips an explicit performance tradeoff, required
   lazy/bounded decode and cancellation, and validated strict positive position
   deltas against actual PR 4 code.
2. **R5-02 (F07):** replaced unindexed per-doc records with a uniform block
   directory and fixed/variable layouts, guaranteeing doc-N access touches at
   most its own block (no prefix scan).
3. **R5-03 (F01/F02/F07/F12):** split full verification (trusted
   `ContentDescriptor`) from selective access (structurally checked, not
   independently authenticated); clarified SHA-256 authenticity requires a
   trusted reference; reserved an authenticated-range scheme as a separate
   decision.
4. **R5-04 (F02):** replaced backward magic scanning with a fixed 64-byte EOF
   trailer and checked offsets.
5. **R5-05 (F06/F07):** one shared five-state vocabulary
   (`ABSENT`/`EXPLICIT_NULL`/`EMPTY_MULTI`/`SINGLE`/`MULTI`) with a presence
   bitmap for stored source and consistent column/group-key mapping.
6. **R5-06 (F08):** presence metadata and a conservative pruning applicability
   truth table covering positive, negated, disjunctive and missing/null
   predicates.
7. **R5-07 (F11):** separated wire representability, decoder safety budgets and
   operational policy; 256 MiB is no longer a hard format ceiling.
8. **R5-08 (F10):** named three distinct digest roles and removed ambiguous
   duplication; lifecycle fields omitted (recommended) or reserved-zero.

## 5. Tradeoffs worth human attention

1. **F01 one-file vs multi-file.** One file preserves the PR 3 one-object
   `SegmentDescriptor` and PR 13 whole-file materialization. Multi-file would
   re-open the PR 3 descriptor seam and PR 13 bootstrap.
2. **F05 varint vs fixed-width.** Varints are compact but add canonical-encoding
   checks; fixed-width is simpler/safer but larger. No v1 skips means `advance`
   is sequential.
3. **F06 semantic vs byte-for-byte.** The PR 2 contract has no raw-source
   capture; byte-for-byte would be a new contract requirement (STOP).
4. **F02.1 selective trust.** v1 has no authenticated range mechanism; selective
   reads are structurally checked only. A Merkle scheme is a separate decision.
5. **F10 lifecycle fields.** Omit vs reserved-zero is a genuine choice; omission
   avoids accidentally freezing PR 6 semantics.
6. **F11 operational target.** 256 MiB is an encoder target, not a wire ceiling;
   readers accept larger compliant files under policy.
7. **F12 minor policy.** Conservative rejection is safest but may impede additive
   evolution until a compatibility policy is approved.

## 6. Open questions for the human decision

Defaults in parentheses:

1. **F01** — one sectioned container file? *(yes)*
2. **F02** — fixed 64-byte trailer, SHA-256 envelope digest, full-vs-selective
   trust model? *(yes)*
3. **F05** — varint delta postings with strict canonical form, or fixed-width v1?
   *(varint; fixed-width fallback)*; confirm sequential `advance` without v1 skips.
4. **F06** — semantic preservation with a five-state vocabulary? *(yes)*
5. **F07** — block-addressable columns with `block_docs = 1,024` policy? *(yes)*
6. **F08** — the proposed pruning applicability truth table? *(yes; conservative)*
7. **F10** — omit lifecycle fields, or retain reserved-zero fields? *(omit)*
8. **F11** — confirm the safety-budget defaults and that 256 MiB is policy, not
   format? *(yes)*
9. **F12** — conservative rejection of unknown minor versions? *(yes)*

## 7. Reviewer checklist

- [ ] F01–F12 each marked APPROVED / APPROVED WITH CHANGES / REJECTED.
- [ ] R5-01: bounded `next`/`advance`; PR 4 position semantics verified.
- [ ] R5-02: per-doc column access avoids prefix scan; block/offset layout precise.
- [ ] R5-03: full vs selective integrity trust is unambiguous.
- [ ] R5-04: fixed EOF trailer; no backward magic scan.
- [ ] R5-05: absent/null/empty states consistent across source, columns, group keys.
- [ ] R5-06: partial-presence bounds and predicate applicability conservative.
- [ ] R5-07: wire/safety/operational limits separated and numerically consistent.
- [ ] R5-08: manifest digest roles distinct; lifecycle fields reserved only.
- [ ] No decision conflicts with PR 2–4 contracts.
- [ ] No custom cryptography; SHA-256 via vetted `sha2`.
- [ ] No PR 6/13/distributed/vector scope in PR 5.
- [ ] `correctness-matrix.md` traceability (INV01–INV12 + P5-A01–A20) accepted.
- [ ] Approved commit SHA recorded in the decision document.
- [ ] Approval table remains pending; no merge or roadmap DONE.

## 8. Consequence of approval

After approval (and only after), implementation proceeds per the plan's Phases
A–E, followed by the full mandatory local validation and both implementation and
correctness gates.

## 9. Consequence of rejection or requested changes

The agent updates `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`, re-runs the
pre-implementation correctness gate, and returns for approval. **No production
codec code is written before approval.**
