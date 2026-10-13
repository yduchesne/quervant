# Amendment 01 cross-decision consistency matrix

> **Status:** PLANNED/CONSISTENCY REVIEW — no code executed. This matrix satisfies
> Amendment 01 §4: trace each cross-cutting invariant end to end across the
> revised F sections, record at least two concrete counterexamples per row, and
> confirm the revised format rejects them or preserves the required semantics.
> References use the revised headings in
> `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`.

## 1. Audit table

| # | Cross-cutting invariant | Must agree across | Resolution in revised proposal | Ex. 1 (rejected/preserved?) | Ex. 2 (rejected/preserved?) |
|---|---|---|---|---|---|
| C1 | Section offsets and lengths | F01, F02, F07, F10, F11 | Sections contiguous from `header_len` to `footer_offset`; `body_offset+body_length` checked; column block offsets are relative and validated non-decreasing with sentinel == value length | A directory overlap (two sections share bytes) is rejected by exact tiling (F02.4). | A column offset table ending short of the value area is rejected (F07). |
| C2 | Footer/trailer integrity | F02, F10, F12 | Fixed 64-byte trailer; `footer_offset+footer_len == trailer_offset`; footer exactly consumed; `envelope_digest` covers `[0, trailer_offset)` | A forged `footer_len` not equal to `trailer_offset-footer_offset` fails closed. | Padding after the footer before the trailer leaves undeclared bytes and fails the exact-consumption check. |
| C3 | Trusted digest identity | F01, F02, F10, PR 3 `ContentDescriptor` | Full verification compares `envelope_digest` to a trusted PR 3 `ContentDescriptor`; manifest stores per-segment `(algorithm, length, digest)`; these are distinct roles (F02.1, F10) | Comparing a section digest to the same untrusted footer is explicitly not authentication. | A manifest repeating its own envelope digest in-payload is prohibited (F10). |
| C4 | Physical doc-ID order | F04, F05, F06, F07, F08, F09 | Dense `0..doc_count`; postings doc ids ascending; stored/columns/bounds emitted in physical order; F09 remap applied before column layout | Remap applied to postings but not columns is caught by cross-structure agreement tests (INV08). | Bounds computed over original order while postings use physical order is rejected by P5-A20. |
| C5 | Analyzer position/value-index semantics | F03, F05, PR 4 | Position strictly increasing per `(term, doc)`; first absolute then positive deltas; `value_index` non-decreasing; `position_length` stored; offsets stored from analyzer | Equal positions are impossible (PR 4 `increment > 0`); storing a zero delta is rejected. | Re-deriving offsets from normalized term length is forbidden; offsets are stored (F05). |
| C6 | Field states and typed values | F03, F06, F07, PR 2 | One five-state vocabulary (`0x00..0x04`); `MULTI` count `>= 1`; integer width/family tags preserved; group keys carry MISSING/NULL/VALUE | Collapsing `EMPTY_MULTI` into `ABSENT` fails round-trip (P5-A08). | `MULTI` count 0 rejected; count 1 vs `SINGLE` remain distinct tags. |
| C7 | Bounded random access | F01, F05, F07, F11 | Column doc N touches one block via O(1) directory arithmetic; postings `advance` is bounded sequential; read/allocation budgets enforced | A "block" without stored offsets degenerates to a prefix scan and fails P5-A06. | `advance` materializing the whole term list fails the bounded-read budget (P5-A02). |
| C8 | Partial-field pruning | F07, F08, F09, future query predicates | Presence states + applicability truth table; unknown disables pruning; positive pruning safe under `SOME`; negation requires `ALL` | Pruning a negated range from present values while a doc lacks a value produces a false negative and fails P5-A14. | Treating `SOME` as `ALL` for `IS NULL` wrongly prunes and fails P5-A13. |
| C9 | Wire feature/version policy | F02, F05, F07, F10, F12 | Unknown required feature/section/flag fails closed; unknown optional ignored; major mismatch fails; minor conservatively rejected | Ignoring an unknown required section is rejected by F02.4. | Adding a skip section without `F_SKIP_BLOCKS` fails feature negotiation. |
| C10 | Format vs operational limits | F02, F05, F07, F11 | Wire widths vs decoder safety budgets vs operational policy separated; 256 MiB is a preferred encoder target, not a wire ceiling | Treating the preferred 256 MiB as a hard reader rejection is rejected by F11 (accepted-size policy). | A `u64` count cast to `usize` without a checked conversion is rejected by F11/INV12. |

## 2. Adversarial self-review (new counterexamples)

Per Amendment 01 §7 correctness gate, two additional attempts to break the
revised invariants beyond restating the amendment:

1. **Trailer/`envelope_digest` circularity.** A writer could try to place
   `envelope_digest` before `footer_offset` so the digest covers itself. The
   revised trailer fixes `envelope_digest` as the final 32 bytes and covers
   `[0, trailer_offset)`; a self-covering layout cannot satisfy the byte table and
   fails P5-A11/P5-A12. If a future trailer reorders fields, the covered range
   must be re-specified and re-approved.
2. **Column block directory remap drift.** A writer could build block directories
   in original doc order and then apply F09 remap to postings only. Cross-
   structure agreement (P5-A20) plus the requirement that columns are written in
   physical order (F07) reject this; a remap that is not applied uniformly fails
   F09's single-entry-point rule.
3. **`SOME`-presence positive pruning with explicit null.** Presence metadata
   counts "has an applicable value"; an explicit-null-only field has
   `present_count = 0`, so positive range pruning is safe and no value-less doc
   can match. This is consistent because positive predicates do not match
   absent/null (PR 2 A09/A10). A future predicate that *does* match null must not
   reuse this rule (truth table says unlisted predicates never prune).

## 3. Residual ambiguity and dispositions

| Item | Disposition |
|---|---|
| Selective-range authentication | **Deferred** — reserved; requires a separate human decision on a Merkle/authenticated structure. v1 labels such reads structurally checked only. |
| Skip index performance | **Deferred** — reserved `F_SKIP_BLOCKS`; v1 `advance` is sequential by design. |
| Column state packing | **Deferred** — one byte/doc in v1; 2-bit packing is a later compatible optimization. |
| `FIXED_SINGLE` vs `VARIABLE_MULTI` split for future types | **Open** — new fixed-width types must declare a layout kind; unknown layout fails closed. |
| Reserved lifecycle fields | **Open for human choice** — omit (recommended) vs reserved-zero. |
| Minor-version compatibility | **Open for human choice** — conservative rejection recommended. |

No contradiction remains that requires a STOP; the open items are explicitly
presented for human decision rather than decided by the agent.
