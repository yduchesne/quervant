# PR 5 format-decision review artifact

> **Status: AWAITING HUMAN REVIEW — no production codec authorized.**
>
> Companion to `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`. This artifact
> exists so a human reviewer can approve or amend the F01–F12 binary-format
> decisions before any durable format is implemented, per
> `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md` §2 and §8.

## 1. Why this gate exists

`docs/ROADMAP_V01.md` specifies PR 5 *capabilities* (immutable segment/manifest
schemas, typed columns, positional postings, bounds, remap) but deliberately does
not fix a byte-level durable format. `PR04_PR05_DESIGN_GATE_APPROVAL.md` states
F01–F12 are approved **in principle** and that the concrete binary layout, size
envelopes and postings encoding are still open, to be resolved by a human-reviewed
addendum. The design-gate record explicitly says: **"STOP if a coding agent is
asked to decide any of the unresolved architecture or format choices."**

This review is that addendum's input. The agent may propose; it may not approve.

## 2. What was verified before proposing

- Fresh `main` = `a23cf25798e52fc181e93ac84505a07412f37463`; clean tree;
  `dev/segment-codecs == main`; no PR 5 code exists. See
  `docs/pr-artifacts/pr-5/preflight.md`.
- PR 4 is **merged** (merge `9bc042d`, PR #16) despite the stale roadmap status.
- Reusable seams confirmed: `contract::{schema,document,value,budget,capability}`,
  `analysis::{Token,AnalyzerFingerprint,AnalyzerRegistry::resolve_fingerprint,
  AnalysisLimits}`, `storage::{Directory,ReadHandle,WriteHandle,SegmentId,
  SegmentDescriptor,SegmentStore,SegmentCache}`.
- Baseline QA on the inspected SHA: **639 passed / 0 failed / 1 ignored**;
  fmt, Clippy (`-D warnings`), docs pass; **87.74% workspace line coverage**.
- Integrity primitive: RustCrypto `sha2 = 0.11.0` already present; **no custom
  cryptography proposed**.

## 3. Recommendation at a glance

| Area | Recommendation | Strongest alternative |
|---|---|---|
| F01 container | One sectioned container file per `SegmentId` | Multi-file components + manifest |
| F02 envelope | `TRWSEG01`, LE, header + footer directory, SHA-256 prefix digest, required/optional feature ids | CRC-32C; fixed-width only |
| F03 schema | Canonical name-sorted dense `field_id`; PR 4 fingerprint stored | Name-keyed everywhere |
| F04 identity | Dense physical ids; byte-exact keys; revision/live refs only, no delete execution | Store revisions only |
| F05 dictionary/postings | Per-field UTF-8-sorted dictionary; varint delta postings with positions, offsets, `value_index`; skips reserved | Fixed-width postings |
| F06 stored source | Semantic lossless typed document; nested JSON order preserved | Byte-for-byte original JSON |
| F07 columns | Doc-major typed columns; family-tagged IP/CIDR; tagged group keys | Column-major blocks |
| F08 bounds | Known/Unknown; Unknown disables pruning; antimeridian-aware envelopes | Mandatory bounds |
| F09 remap | Timestamp asc, then `DocumentKey` asc; stored bidirectional permutation | Doc-id tie-break |
| F10 manifest | Codec + validation only; generation/epoch fields reserved; no CURRENT | Publish manifest now |
| F11 caps | Explicit hard ceilings; checked arithmetic; cancellation checkpoints | Unbounded decode |
| F12 evolution | Major fail-closed, conservative minor; checked-in goldens with oracle | Assume minor compatibility |

## 4. Tradeoffs worth human attention

1. **F01 one-file vs multi-file.** One file preserves the PR 3
   one-object `SegmentDescriptor` and PR 13 whole-file materialization, at the
   cost of not selectively materializing components. Section addressability keeps
   `ReadHandle::read_at` selective reads available. Multi-file would require
   re-opening the PR 3 descriptor seam and PR 13 bootstrap; that is a larger
   change than PR 5.
2. **F05 varint vs fixed-width.** Varints are compact but introduce
   canonical-encoding requirements (overlong rejection) and more decoder surface
   for a low-reasoning agent. Fixed-width is simpler and safer but larger. This is
   a genuine risk/space tradeoff and should be decided explicitly; the format must
   choose one.
3. **F06 byte-for-byte vs semantic.** The PR 2 contract has no raw source
   capture; semantic preservation is the only lossless option within contract.
   Byte-for-byte would be a new contract requirement and is out of scope.
4. **F02 minor-version policy.** The proposal is conservative (reject unknown
   minor). This is safest but may impede future additive evolution until a
   compatibility policy is approved. Alternative: allow unknown minor if all
   required features are known — more forward-compatible, requires stronger
   feature discipline.
5. **F11 numeric ceilings.** The proposed ceilings are conservative defaults.
   They are decoder policy, not wire format, and can be adjusted without changing
   bytes; still, they must be approved because they bound real resource use.

## 5. Compatibility and scope implications

- **PR 2 contracts:** no change. Field types, null/missing/empty, IP family,
  timestamp units, sorting/ties and budgets are reused as approved.
- **PR 3 storage:** no change. `Directory`, handles, `SegmentId`,
  `SegmentDescriptor`, `SegmentCache` are reused; no new remote runtime.
- **PR 4 analysis:** no change. The canonical `AnalyzerFingerprint` is stored
  verbatim and resolved through `resolve_fingerprint`; PR 5 does not reimplement
  analysis or fingerprinting.
- **PR 6+:** PR 5 exposes codecs and reference schemas. It does **not** publish
  `CURRENT`, allocate generations, refresh, recover, merge, delete, or execute
  queries. Generation/epoch fields are reserved placeholders.
- **PR 13:** remote RustFS cold bootstrap remains PR 13. PR 5 exercises only the
  real local `MemoryDirectory`/`FsDirectory` paths.
- **No distributed, vector, or ObjectStore-adapter scope** is introduced.

## 6. Open questions for the human decision

Please answer explicitly (defaults shown in parentheses):

1. **F01** — one sectioned container file? *(recommended: yes)*
2. **F02** — SHA-256 prefix digest and required/optional feature ids? *(recommended: yes)*
3. **F05** — varint delta postings with strict canonical form, or fixed-width
   v1 postings? *(recommended: varint; fixed-width is the conservative fallback)*
4. **F06** — semantic typed preservation rather than byte-for-byte? *(recommended: semantic)*
5. **F11** — confirm or change the numeric ceilings (segment 256 MiB, fields
   4,096, term 4 KiB, etc.)?
6. **F12** — confirm conservative rejection of unknown minor versions, or allow
   unknown-minor-when-required-features-are-known?

## 7. Reviewer checklist

- [ ] F01–F12 each marked APPROVED / APPROVED WITH CHANGES / REJECTED.
- [ ] No decision conflicts with PR 2–4 contracts (A01–A25, storage S01–S16,
      analyzer T01–T08/parameter amendment).
- [ ] No custom cryptography; SHA-256 via vetted `sha2`.
- [ ] No PR 6/13/distributed/vector scope leaked into PR 5.
- [ ] Resource caps and checked arithmetic acceptable.
- [ ] Golden-fixture policy acceptable (committed bytes + independent oracle).
- [ ] Approved commit SHA recorded in
      `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`.
- [ ] `docs/pr-artifacts/pr-5/correctness-matrix.md` traceability accepted.

## 8. Consequence of approval

After approval (and only after), implementation proceeds per the plan's Phases
A–E: `segment/` module, typed codec errors, checked primitives, schema/stored/
columns, dictionary/postings, remap/bounds/manifest, then real `Directory`
write/read/reopen and checked-in golden fixtures — followed by the full mandatory
local validation and both implementation and correctness gates.

## 9. Consequence of rejection or requested changes

The agent updates
`docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`, re-runs the pre-implementation
correctness gate, and returns for approval. **No production codec code is written
before approval.**
