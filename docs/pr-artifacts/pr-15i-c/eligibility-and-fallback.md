# PR 15I-C — Eligibility and fallback

Status: implemented, tested, then **rolled back** with the rejected candidate
(`15IC_PERFORMANCE_REJECTED_SAFE_ROLLBACK`). This document records the contract as
implemented and executed; it is not a claim about the current tree.

## 1. `C-EXACT-ONE` predicate

Implemented as `UnifiedSearcher::exact_term_physical_eligible`, an additional,
strictly narrower gate on top of the accepted PR 15E
`single_term_postings_eligible`. It returns `true` only when **all** of:

1. The call is standalone (`BatchExecutionMeter` absent) and `retain == false`.
2. `snapshot.segment_count() == 1`.
3. `single_term_postings_eligible(plan, request, aggregation)` holds: compiled
   root `UnifiedNode::Lexical(0)`, exactly one `CompiledLeaf::Term` with exactly
   one analyzed term, exactly one positive lexical leaf, no typed leaves, no
   aggregation and `request.after == None`.
4. Exactly one sort field, `SortDirection::Asc`, with no `json_path`, no
   `distance_from` and no `multi` selector.
5. The schema definition exists with `FieldType::Keyword`,
   `Cardinality::Single`, `options.columnar == true`.

There is deliberately **no** assertion that the sort field is named `doc_id`, that
its values equal the logical key, or that any metadata proves key equivalence. The
fast operator always runs the canonical `ColumnKeywordView` decoder and
`compare_borrowed_keyword_to_owned` / `compare_candidates` comparator.

## 2. Eligibility / fallback truth table (as tested)

| Shape | Eligible | Test |
|---|---|---|
| One positive exact `Term(Keyword)`, one segment, standalone, `Keyword Single columnar ASC` | FAST | C-U01/C-U36 |
| One positive `Term(Text)` analyzing to exactly one term, same conditions | FAST | C-U02 |
| Term analyzing to zero or 2+ terms | FALLBACK | C-U02 |
| No sort (relevance) | FALLBACK | C-U03 |
| `doc_id ASC` whose column differs from the logical key | FAST, canonical column order | C-U10/C-U32, C-I04 |
| `doc_id DESC`, two sorts, numeric sort, missing/Null/Unicode values | DESC/two-sorts/numeric FALLBACK; value states FAST | C-U03, C-U11 |
| Keyword ASC field named `label` (not `doc_id`) | FAST | C-U12 |
| Pure term + aggregation / cursor / batch slot / `retain=true` | FALLBACK | C-U03, C-U26, C-I12 |
| `And`/`Or`/`Not`, `MatchAll`, phrase, prefix | FALLBACK | C-U03 |
| Two or more committed segments (incl. mixed codecs and PIT) | FALLBACK | C-U03, C-I06/I07 |
| One segment with deleted/superseded docs | FAST when shape holds | C-U07, C-I08 |
| One segment with no postings for the term | FAST, 0 hits, per-live work charged | C-U13, C-U05 |
| Corrupt bytes/invalid sort value/work cap after admission | **ERROR, never fallback** | C-U18, C-F01..F06 |

## 3. Rejected shortcut

A schema field named `doc_id` is not, by name or `Keyword` type, guaranteed equal
to the immutable logical `DocumentKey`. No key-order or column-equivalence
shortcut was taken, and the on-disk schema does not contain a proof of equality.
