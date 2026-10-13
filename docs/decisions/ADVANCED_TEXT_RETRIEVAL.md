# Advanced text retrieval — planned capability contracts

**Status:** Proposed design target; documentation only. No implementation, release commitment, or change to approved PR 5 bytes. This document distinguishes matching semantics from acceleration and does not silently enlarge PR 7/8 scope.

## Terminology and semantics

| Capability | Semantics | Candidate strategy | Verification |
| --- | --- | --- | --- |
| Term substring | Literal contiguous substring of an indexed, normalized term | Existing bounded glob/regex enumeration initially; optional gram postings later | Exact term comparison |
| Field-value substring | Literal contiguous substring of a normalized full field value, including whitespace/token boundaries | Optional schema-configured gram postings on the full normalized value | Exact normalized full-value comparison |
| Prefix | Beginning of an indexed term | FST/automaton intersection as planned for PR 8 | Term-prefix check |
| Autocomplete | Ranked, deduplicated suggestions for a prefix in a specified field | Bounded prefix enumeration and postings statistics | Suggestion identity and eligibility |
| Search-as-you-type | Retrieve documents matching completed analyzed tokens and a final incomplete token prefix | Boolean/phrase-capable postings plus bounded prefix expansion | Full query semantics and scoring |

**Normalization:** Index and query must use a matching, versioned field-specific normalizer. Define Unicode normalization, case folding, byte/codepoint interpretation, analyzer versions, and offset mapping before implementing field-value substring retrieval. Do not promise raw-byte matches when only normalized text is indexed. Empty patterns and invalid Unicode inputs must have explicit errors or documented bounded behavior.

**Term versus field-value:** A token-substring query does not implicitly search across whitespace or token boundaries. A field-value substring query requires an independently indexed full normalized value; a tokenized TEXT field alone is insufficient. Multivalued fields match within each value, never across distinct values. Missing, null, and empty values are distinct. Nested JSON string values must follow their configured field/value boundaries; no implicit recursive JSONPath.

## Substring acceleration

Plan optional, **per-field**, versioned gram/trigram postings, with exact verification against the appropriate normalized source. Gram postings generate a superset of candidate documents; false positives must never escape verification. For patterns of fewer than three normalized units, use a documented bounded fallback or a deliberate query rejection; never silently return incomplete results. For larger patterns, intersect selected grams with cost-aware bounded expansion. Consider adversarial high-frequency grams, Unicode combining sequences, high-cardinality JSON/log strings, and large values. Indexing, storage, merge, and query cost must be measured against the no-gram baseline.

Do not conflate edge n-grams (prefix-oriented) with full n-grams (substring-oriented). A suffix-only index is not a general substring solution. An FST alone does not guarantee efficient leading-wildcard or contains queries.

## Autocomplete

Use PR 8's planned FST-like prefix traversal and bounded term enumeration; do not add a parallel trie by default. Suggestion contracts must specify field, normalization, optional context/filtering, maximum suggestions, traversal/expansion/time budgets, deterministic tie-breaking, ranking (initially a documented frequency-based policy), deduplication across immutable segments, and deletion visibility. Term suggestions and full-value suggestions are distinct APIs/field configurations. Empty and too-short prefixes require a bounded policy. Fuzzy suggestion support is optional and must reuse bounded fuzzy matching where available; do not equate fuzzy term matching with a delivered autocomplete API.

## Search-as-you-type

Analyze complete tokens with the field's search analyzer and interpret only the unfinished final token as a prefix; trailing whitespace means no unfinished token. Define exact behavior for punctuation, stopword gaps, Unicode, multiple values, and analyzer mismatch. Initial query execution can combine Boolean/BM25 and bounded prefix expansion; phrase-order matching is a separate explicit mode, not an implicit guarantee. Rank document results, not term suggestions. Apply normal filters/deletes and segment aggregation, with stable deterministic top-K tie-breaking and bounded resource use.

## Segment and FST compatibility gate

PR 5's approved dictionary wire representation is sequential and must not be silently replaced. Before PR 8 adds FST intersection, choose and approve either (a) an auxiliary/versioned optional FST structure with explicit compatibility and feature negotiation, or (b) a separately versioned codec extension. A runtime-only derived FST is possible but its memory and startup costs must be measured. The decision must preserve reading existing golden fixtures, unknown required-feature rejection, and independent `trawler-core` operation. **STOP** before changing PR 5 wire bytes or required-feature semantics without explicit approval.

## Future implementation boundaries

1. PR 8 retains its existing bounded multi-term search scope. Efficient arbitrary substring indexing, ranked autocomplete, and search-as-you-type are **not** retroactively PR 8 acceptance requirements.
2. A future FST/format-compatibility decision gates prefix-index implementation choices.
3. Subsequent, separately scoped implementation PRs: (i) ranked autocomplete; (ii) search-as-you-type; (iii) optional gram-backed substring acceleration. Ordering is indicative and requires dedicated plans.
4. No v0.1 or v0.2 delivery commitment is made here.

## Future acceptance tests and benchmarks

- Independent brute-force oracle for literal substring matching over normalized per-value strings, including token-boundary cases and short patterns; verify candidate+exact-filter equals oracle.
- Unicode normalization, combining marks, case-fold expansion, empty/missing/null, multivalue, JSON nesting, analyzer-version mismatch, deletion, merge/reopen, and cross-segment equivalence.
- Prefix/autocomplete reference enumeration with ranking/deduplication/tie-breaking oracle, candidate/timeout budgets, and pathological common-prefix cases.
- Search-as-you-type completed-token/trailing-whitespace/stopword/phrase-mode fixtures; deterministic document top-K and query cancellation.
- Compare index size, ingest throughput, memory, p50/p95/p99 latency, and cold/warm performance on logs, identifiers, JSON strings, and general text, against bounded glob and non-gram baseline. Correctness is a prerequisite for performance claims.
- Real Directory reopen and persistence tests where codec/index structures are introduced; use repository-prescribed topology, QA and coverage gates. Do not substitute mocks for integration acceptance.
