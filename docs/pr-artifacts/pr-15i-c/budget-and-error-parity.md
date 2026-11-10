# PR 15I-C — Budget and first-error parity

Status: executed; the production change was subsequently rolled back after a
performance rejection. Evidence below is from the tested candidate.

## 1. Work and scanned-occurrence accounting

| Charge | Position | Evidence |
|---|---|---|
| `1 + freq` per decoded posting | unchanged `build_leaf_data` | C-U16 (identical `max_scanned_posting_occurrences` boundary) |
| One examination per effective-live document | `effective_live_examination_count` + single `charge_lexical(live_count)` | C-U13, C-U14, C-I21 |
| Per-candidate cancellation poll | once per posting, as the PR 15E eligible path | C-U18, C-F05/F06 |
| No extra work units during scoring | score pass has no charge or poll | by construction; C-U19 measures that all `M` scores precede the first callback |

Exact/one-below parity was measured by binary-searching the minimum admitted limit
on the fast shape and on the forced-generic shape over the same snapshot:
`C-U14` (work), `C-U16` (scanned occurrences), `C-I21` (work, public API).

## 2. Candidate budget model

The fast path performs the legacy reservations in the legacy order:

```
build_leaf_data           -> 16 bytes per live posting
matched (virtual)         -> 48 bytes per matched document
scored map (virtual)      -> 64 bytes per matched document
scores Vec<f64>           -> 8 bytes per matched document (caller-owned transient)
release matched, leaf, scored; ledger.finish() must observe zero
```

Measured boundary equality (`C-U15`, `C-U17`, `C-U21`, `C-U22`):

* minimum `max_segment_candidate_entries` for the fast and generic paths is equal;
* minimum `max_total_candidate_bytes` is equal;
* at the exact ceilings both paths succeed and return identical output;
* one below, both fail with the same `SearchError` variant and no partial response.

`C-U40` asserts inside the callback that `segment_entries == 0` and
`segment_bytes == 0`, i.e. the ledger owns nothing before the first heap
admission.

## 3. First-error ordering

Implemented order: query/sort/projection/cursor validation (before plan compile) →
metadata/schema binding → posting decode and scanned work → per-live work and
cancellation → virtual matched admission → virtual scored admission → **complete**
BM25 pass → key decode → sort/heap → projection.

Evidence:

* `C-U31`/`C-I14`: contract validation fails before plan compilation and before
  admission (fast-path counter stays zero).
* `C-U18`: cancellation before the first callback; no callbacks emitted.
* `C-U19`/`C-U38`: even when the callback fails on the first candidate, all `M`
  scalar scores were already produced, which is the structural precondition that
  keeps a late `InvalidScore` ahead of key/sort errors.
* `C-U20`: absent `FieldStats` yields exactly `0.0` bit-identical to legacy.
* `C-U06`: a non-single-term leaf shape is a typed `CorruptIndex`, never a partial
  enumeration.

## 4. Known evidence gap (declared, not waived)

`C-U19` cannot inject a synthetic `df > n` `FieldStats`: constructing one requires
a test-only constructor inside the protected `search/score.rs`, which the plan's
source allowlist forbids. The ordering property is therefore evidenced by the
score-before-callback observation above plus a source-order review, not by a
synthetic `InvalidScore` fixture. This is recorded as a limitation of the
qualification evidence.
