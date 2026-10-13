# PR 7 implementation report

## Summary

Adds a standalone, snapshot-bound lexical search executor to `quervant-core`:
exact lexical `Term` (Text/Keyword), positional `Phrase` on Text, arbitrarily
nested `And`/`Or`/`Not`, `MatchAll`, deterministic BM25 top-K and exact hit
counts. It reads PR 5 immutable postings through PR 6 `ReaderSnapshot`s and does
not change the segment format, manifest, writer, commit path or lifecycle.

## Public API (`quervant_core::search`)

- `SearchHit { key: DocumentKey, score: f64 }`
- `SearchResponse { hits, total_hits, generation, view_ordinal }`
- `LexicalSearcher<'a>::new(&ReaderSnapshot, &Schema, &AnalyzerRegistry, SearchLimits)`
  with `with_analysis_limits`, `limits`, and
  `search(&Query, TopK, &Budgets, &dyn Cancellation) -> Result<SearchResponse, SearchError>`.
- `SearchError` (wraps `QueryError`, `AnalysisError`, `SegmentError`, `IndexError`,
  plus `UnsupportedOperator`, `ResourceLimit`, `Cancelled`, `CorruptIndex`,
  `InvalidScore`).
- `SearchLimits` with ten explicit, hard-ceilinged bounds.

## Module layout

`search/{mod,error,limits,plan,execute,phrase,score,topk}.rs` as prescribed.

- `plan.rs` — fail-closed compilation: unsupported operators rejected before any
  segment read; field ids from `CodecSchema`; search-pipeline analysis; duplicate
  clause interning; compiled-node and unique-term bounds.
- `execute.rs` — two-phase execution: snapshot statistics first, then bounded
  per-segment doc-id/score maps; boolean evaluation over PR 6 live flags; key
  resolution; duplicate-key detection; top-K; RAII guarded readers.
- `phrase.rs` — positional chain verification across `position_length`,
  `position_length`-aware gaps and identical `value_index`.
- `score.rs` — `bm25(k1=1.2, b=0.75)` and snapshot-wide field-length/document
  frequency preparation with checked arithmetic and work/entry bounds.
- `topk.rs` — bounded binary heap, score descending then key ascending.

## Semantics decisions (within D07-01..D07-06)

- **Term**: Text is analyzed with the field's search pipeline; zero terms match
  nothing; multiple terms are an OR with one scoring contribution per distinct
  term. Keyword requires exactly one normalized term. Unsupported field types are
  `UnsupportedOperator`.
- **Phrase**: ordered components are concatenated with a single tokenization
  boundary and analyzed once, which preserves analyzer position holes; matching
  requires an ordered occurrence chain in the same `value_index` and respects
  `position_length`. Doc-only postings are a typed corruption failure.
  Phrase on non-Text fields is unsupported.
- **Boolean**: `And` intersection, `Or` union/dedup, `Not` live-universe
  complement. `Not(Not(X)) == X`; repeated clauses share one compiled leaf so
  scores cannot inflate; negation contributes zero.
- **Ranking**: `idf = ln(1 + (N - df + 0.5)/(df + 0.5))`,
  `score = idf * (tf * 2.2) / (tf + 1.2 * (1 - 0.75 + 0.75 * dl/avgdl))`.
  `dl` is rebuilt from dictionary/posting frequencies (no on-disk norms). `N`,
  `df` and `dl` use live documents only. Non-finite/negative scores fail typed.
- **Top-K**: exact `total_hits` independent of `K`; deterministic ties.

## Read-only seam additions (no encoding change)

`SegmentReader::{doc_keys, doc_key, live_docs, is_live, postings_for_entry}` and
`PostingsReader::is_positional`. These decode existing `DOC_KEYS`/`LIVE_DOCS`
sections and reuse existing postings extents. No segment-format, writer, manifest,
`CURRENT`, storage or distributed code was modified.

## Known limitations / residual risks

- Field lengths are recomputed for every searched field per query (O(indexed
  postings)); this is the approved v1 reference behaviour. A future separately
  approved format extension may add norms.
- The executor materializes per-segment candidate maps and a global key map
  (bounded); it does not claim streaming, WAND or block skipping.
- Duplicate live keys across segments are detected while merging matches, not
  eagerly before matching.
- Phrase concatenation uses a single ASCII-space boundary; this is documented as
  the v1 positional semantics and does not change PR 4 contracts.
