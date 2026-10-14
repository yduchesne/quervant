# PR 7 preflight — lexical postings, Boolean/phrase and ranked search

**Branch:** `dev/lexical-postings` (implementation branch; plan suggested `dev/pr07-lexical-search`)
**Base:** `main` @ `4f603ce1c0dafd994918bb5291d4b0584d9f001c` (PRs 1–6 merged)
**Toolchain:** stable Rust 1.98.1; MSRV check with Rust 1.85.0 (`rust-toolchain.toml` channel `stable`, workspace `rust-version = 1.85`).

This document records the verified source seams and the pre-implementation
compatibility checks required by PR 7 Step 5. Every item below was inspected on
the base commit before production code was written.

## Verified source APIs

- `contract::query::Query` and `Query::validate(&Schema, &Budgets)`; `Phrase { field, terms: Vec<String> }`.
- `contract::result::TopK { pub limit: usize }`; `TopK::new(limit)` rejects `0`; `TopK::validate(&Budgets)` enforces `BudgetKind::ResultWindow`. `TopK` is `Copy`.
- `analysis::registry::AnalyzerRegistry::resolve_fingerprint`, `SchemaAnalyzerBindings::resolve`, `FieldAnalyzerBinding { index, search }`.
- `analysis::analyzer::AnalyzerDefinition::collect_tokens(AnalyzerRole, &[&str], &AnalysisLimits, &dyn Cancellation)`; `Token { term, value_index, position, position_increment, position_length, start_offset, end_offset }`; `POSITION_GAP = 100`.
- `analysis::cancellation::{Cancellation, NeverCancel, CancellationFlag}`; `analysis::limits::{AnalysisLimits, CANCELLATION_POLL_INTERVAL}`.
- `segment::reader::SegmentReader::postings(field_id, term)`, `dictionary()`, `stored_doc(doc_id)`, `stored()`, `schema() -> &CodecSchema`, `doc_count()`.
- `segment::postings::{Posting { doc_id, freq, occurrences }, Occurrence { position, position_length, value_index, start_offset, end_offset }, PostingsReader::next_with/advance_with}`.
- `segment::dictionary::{DictionaryEntry, DictionaryReader::fields/field/lookup}`; v1 lookup is sequential and there is no random-access offset table.
- `index::snapshot::{ReaderSnapshot, SegmentSnapshot, GuardedSegmentReader}`; `ReaderSnapshot::open_segment_reader(index)` is the budgeted, RAII-guarded path. Managed reader-copy accounting bounds cloned encoded bytes only.
- `index::{Index, IndexWriter, PitHandle}`; `Index::snapshot`, `IndexWriter::refresh`, `IndexWriter::pin`, `IndexWriter::reader`, `PitHandle::snapshot`.

## Field-ID mapping and analyzer-resolution seam

`CodecSchema::from_contract(&Schema, &SchemaAnalyzerBindings)` assigns dense field
ids in ascending UTF-8 byte order of field name and persists the analyzer/normalizer
`{id, version, fingerprint}`. Search resolves the 1:1 mapping via the same
`CodecSchema::from_contract`, and verifies each opened segment's `CodecSchema`
equals the compiled one **before** reading postings; a mismatch is a typed
`SearchError::CorruptIndex`. Analyzer definitions are re-resolved with
`AnalyzerRegistry::resolve_fingerprint(id, version, fingerprint)` so the same id
and version with a different configuration cannot be silently reinterpreted.

## Posting / occurrence producer semantics

`segment::build::SegmentBuilder::analyze_document` analyzes each indexed Text/Keyword
value, groups occurrences by term, and emits one `Posting { doc_id, freq = occurrences.len(), occurrences }`
per `(physical doc, term)`. Occurrences are sorted by strictly increasing
`position`; `value_index` is non-decreasing. Multi-valued fields are analyzed as
separate `values` in one `AnalysisCursor`, so positions advance by `POSITION_GAP`
between values while `value_index` changes. A term whose block contains any
occurrence is positional; PR 5 always encodes positional blocks for real
builder output. `PostingsReader::is_positional()` was added as a read-only
accessor to reject doc-only blocks in phrase execution.

## Live-document accessor, dictionary iteration and doc keys

On the base commit the `LIVE_DOCS`, `DOC_KEYS` and posting-extent bytes existed
but the reader did not expose liveness or keys. Because PR 7 must honor live
flags and resolve logical keys without loading every stored document, these
read-only accessors were added to `SegmentReader` (no encoding change):

- `doc_keys() -> Rc<Vec<DocumentKey>>`, `doc_key(doc_id)` (decodes the existing `DOC_KEYS` section).
- `live_docs() -> Rc<Vec<bool>>`, `is_live(doc_id)` (decodes the existing `LIVE_DOCS` section).
- `postings_for_entry(&DictionaryEntry)` (avoids a redundant sequential dictionary lookup when iterating `dictionary().field(field_id)` for BM25 statistics).
- `PostingsReader::is_positional()`.

`DictionaryReader::field(field_id)` returns the sorted `&[DictionaryEntry]` for a
field; `lookup` remains the point-query path.

## Cancellation / budget types

Search uses a checked `SearchWork` (deterministic work ceiling + candidate-entry
ceiling + cooperative cancellation polling at `CANCELLATION_POLL_INTERVAL`) and a
validated, hard-ceilinged `SearchLimits` (`search/limits.rs`). Contract-level
`Budgets` (`QueryDepth`, `ResultWindow`) are honored by `Query::validate` and
`TopK::validate` before compilation.

## Paper counterexamples and resolutions

| # | Case | Resolution |
|---|---|---|
| a | Repeated query clause score inflation | Identical clauses intern to one `CompiledLeaf`; each distinct leaf is scored once. |
| b | Multi-valued phrase false positive | Phrase chains require an identical `value_index` for every occurrence. |
| c | Stopword position hole | Phrase components are concatenated with one tokenization boundary and analyzed once, preserving analyzer positions (e.g. `quick the fox` -> positions 0 and 2). |
| d | OR with a negative subtree | `Or` unions positive matches and `Not` complements against the live universe; negation contributes zero score. |
| e | Same term in two different fields | Scoring identity is `(field_id, term)`, so distinct fields are distinct contributions. |
| f | Duplicate keys in two segments | Merging fails closed with `SearchError::CorruptIndex` when a live key is seen twice. |
| g | Zero `avgdl` | `bm25` returns `0.0` without division. |
| h | Budget exhausted after partial results | No partial response is returned; the error propagates and RAII releases guarded readers. |
| i | Cancellation during field-length scan | `SearchWork` polls cancellation during dictionary/posting traversal. |
| j | Snapshot refresh during search | The searcher borrows a captured `ReaderSnapshot`; refresh/commit cannot mutate it. |

## Mandatory compatibility checks

1. **Phrase/analyzer positional semantics** — representable without contract change. PR 4 emits strictly increasing positions and `position_length`; PR 7 derives query positions by analyzing the concatenated phrase components. No PR 2/4 contract change.
2. **Live-document membership / key lookup** — not previously exposed; added **read-only** accessors, no new encoding.
3. **Text field without analyzer** — index-time `SegmentBuilder::analyze_document` falls back to `exact_tokens` (whole value, 1..=4096 bytes). Search mirrors this exactly (`exact_terms`).
4. **Document length derivation** — `dl` is the checked sum of posting frequencies for every distinct term of the field (equivalently the retained-token count, including derived/stemmed tokens and all multi-values). No on-disk norms added; `docs/ARCHITECTURE.md` is updated accordingly.
5. **PR 2 `Term`/Boolean scoring** — PR 2 defines shapes only, not execution. D07-02's "OR of analyzed terms" and D07-04's dedup-by-leaf policy are therefore the first execution semantics and do not contradict a frozen contract.

No STOP condition was triggered.
