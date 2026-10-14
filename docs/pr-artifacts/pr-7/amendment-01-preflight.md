# PR 7 Amendment 01 preflight — Boolean scoring correctness and resource accounting

**Branch:** `dev/lexical-postings`
**Starting commit:** `0568cce6f3505ba94158af990e4b834772d25e21` ("PR 7 Phase 0", parent `4f603ce1c0dafd994918bb5291d4b0584d9f001c`)
**Current `main`:** `4f603ce1c0dafd994918bb5291d4b0584d9f001c` (`origin/main`), unchanged from the PR 7 base.
**Working tree at preflight:** clean (`git status --short` empty).
**Toolchains:** stable 1.98.1 and MSRV 1.85.0.

The pinned amendment delta is the current branch HEAD. `main` has not moved
beyond the PR 7 base, and no intervening PR changed scoring, resource, segment
or lifecycle semantics. No STOP condition is triggered.

## Baseline gate evidence (re-executed on `0568cce`, not inferred)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | 948 passed, 7 ignored, 0 failed |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | 91.73% line / 92.05% region |

## Verified defects (source inspection at `0568cce`)

- **A1 — `execute.rs::score_segment`**: iterates every `LeafData` regardless of
  Boolean polarity. Negated-only leaves therefore contribute BM25 whenever their
  term is present in a matching document, contradicting `search/mod.rs`'s
  "negation contributes zero" promise.
- **A2 — `execute.rs::SearchWork::charge_candidates`**: accumulates
  `SearchWork::candidates` across the whole request while enforcing
  `SearchLimits::max_segment_candidate_entries`, which is documented as a
  per-segment bound. Completed segments keep charging the same counter.
- **A3 — `score.rs`**: uses `segment_lengths.entry(doc_id).or_insert(0)` and
  `if *slot == 0` to detect a new field-length entry. A legitimate zero-valued
  entry (from a zero-frequency path) is miscounted as new on the next posting.
- **A4 — resource safety**: `max_total_candidate_bytes` only covers the global
  key map; concurrently live segment temporaries are unaccounted.
  `max_scanned_posting_occurrences` is declared but never enforced independently
  of `max_total_work_units`. `TopKSelector::push` checks bytes on initial
  insertion but not on a replacement that grows `self.bytes`.

## Counterexamples (pre-amendment behaviour)

1. **Negative scoring.** Corpus `{alpha, beta, neither}`; query
   `NOT(AND(Term(alpha), Term(beta)))`. `{alpha}` and `{beta}` match; the `alpha`
   leaf is negative-only (odd polarity) yet `score_segment` adds its BM25 to the
   `{alpha}` hit, producing a positive score where the contract requires zero.
2. **Two-segment false limit.** Two segments each with N live documents and
   `max_segment_candidate_entries = N`: each segment individually fits the
   per-segment bound, but the cumulative `charge_candidates` reaches `2N` and
   rejects the search.
3. **Heap replacement growth.** `K = 2` with the heap at `max_topk_heap_bytes`;
   offering a better-scoring document with a much longer key evicts a short key
   and pushes a larger one without rechecking `self.bytes`, silently exceeding
   the heap bound.

## Invariant → test mapping (planned)

| Invariant | Planned tests |
|---|---|
| INV-01 odd-NOT leaf contributes zero | S01, S02, S06 |
| INV-02 even-NOT leaf scores only on positive match | S03, S04 |
| INV-03 duplicate eligible leaf not multiplied | S05, S07 |
| INV-04 per-segment peak candidate entries | B01–B05 |
| INV-05 cumulative work/scanned + typed failure | B06, F01–F03 |
| INV-06 independent byte budgets, checked before growth | B07–B11 |
| INV-07 field-length entry counted once regardless of value | L01–L03 |
| INV-08 membership/phrase/order/snapshot/format unchanged | R01–R07 |

## Scope confirmation

Phrase position arithmetic in `phrase.rs` is **not** changed (the withdrawn
reviewer concern). No segment/manifest/index/storage/encoding change is planned.
No distributed, object-store or vector work is touched.
