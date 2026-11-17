# Semantic comparability and source identity

## Independent exact-term oracle

`migrations/cross_engine_contract.py::compute_oracle_row` is a small pure arithmetic
formula. It never imports a historical PR15D module and never invokes an engine.
Document IDs are `d%08d` for `i = 0..N-1`; the exact-keyword matches are:

| Class | Field | Term | Total hits | Ascending IDs |
|---|---|---|---|---|
| absent | `key` | `never` | `0` | empty |
| rare | `key` | `singleton` | `1` | `d00000000` |
| medium | `group` | `medium` | `N//8` | `d00000000`, `d00000008`, ... |
| common | `key` | `common` | `N//2-1` | `d00000002`, `d00000004`, ... |

For `N ∈ {10000, 100000}` this yields totals `[0, 1, 1250, 4999]` and
`[0, 1, 12500, 49999]`, each truncated to the first `min(K, total_hits)` IDs for
`K ∈ {10, 100}`. There are no BM25 scores, native engine order, tokenisation,
fuzzy matching or tolerances.

`oracle-golden.v1.json` is a closed checked-in corpus of 16 sorted rows with keys
`{lane_id, corpus_size, selectivity_class, field, term, top_k, total_hits, doc_ids}`.
Tests independently rederive every row twice: from a local restatement of the
formula, and from the *read-only* historical module
`benchmarks/pr15d/corpus/oracle.py` loaded with `importlib` in the test only. A
count-only match is never accepted.

## Semantic comparability ledger

`semantic-comparability.v1.json` is a closed document:

```
kind, schema_version, evidence_origin, qualification_scope,
reference_spec_digest, oracle_golden_digest, engine_source_bindings_digest,
comparable_lane_ids, excluded_classes
```

`comparable_lane_ids` is exactly the 16 lexicographically sorted warm
keyword-exact lane IDs in `workloads.yaml`. `excluded_classes` is exactly:

| class_id | status | reason |
|---|---|---|
| `index-throughput` | `DEFERRED` | `no-untimed-performance-contract` |
| `process-cold` | `DEFERRED` | `real-process-cache-state-unverified` |
| `scored-bm25` | `NONCOMPARABLE` | `ranking-and-scoring-not-equivalent` |

Any other row set, status or reason is a typed `BM_IDENTITY_INVALID`. Promoting an
excluded class — even with a fully coherent digest rehash — is rejected, and no
excluded class appears in measured lanes, analysis, targets, guardrails or ranking.

## Binding chain

`content_digest(semantic-comparability)` equals
`workload.dataset.digest`; the ledger in turn binds the oracle-golden digest, the
source-bindings digest and the canonical digest of the frozen
`benchmarks/pr15d/spec/pr15d_v1.json`. `protocol.workload_digest` equals the
canonical workload digest. Mutating one companion without rehashing its parents
fails, and a coherently rehashed but semantically altered companion fails the
independent exact-value validator.

## Source-only engine identity

`engine-source-bindings.v1.json` binds raw file bytes, never binaries. Engines are
ordered `lucene`, `quervant`, `tantivy`; every entry declares
`adapter_schema=pr15d-adapter-v1`, `analyzer=keyword-exact`,
`source_qualification=SOURCE_ONLY_NOT_BUILT` and the frozen version literal:

| Engine | Version literal |
|---|---|
| lucene | `Apache Lucene 9.12.3` |
| quervant | `quervant-core 0.1.0` |
| tantivy | `tantivy 0.22.1` |

The allowlist is exact (3 Quervant files, 3 Tantivy files, 8 Lucene files) and every
file is streamed through `open_regular_beneath` with a bounded read; byte length and
SHA-256 must match. Literal pins are re-asserted inside the original bytes
(`tantivy = "=0.22.1"`, `JavaLanguageVersion.of(21)`, the three `ENGINE_VERSION`
constants). A mutated file, a changed pin, an extra engine, an escaped path or a
symlinked source fails closed. No compiled binary identity is claimed.

## Untimed wire projection

A reply projection is a closed six-field record
`{schema, engine, request_id, status, total_hits, doc_ids}` with
`schema=pr15d-adapter-v1`, `engine ∈ {quervant, tantivy, lucene}`,
`request_id="query-"+lane_id`, `status="ok"`, an exact non-negative integer
`total_hits` and the exact expected ordered `doc_ids`. Any `engine_ns`, `wall_ns`,
`duration`, `benchmark_result`, scoring field or binary-identity claim is rejected,
as is a count-only match.

**Why no live query is ever issued:** the original Quervant and Tantivy adapters use
`std::time::Instant` inside their `query` path and the original Lucene adapter uses
`System.nanoTime()`. A direct `op=query` is therefore a timed acquisition even when
a downstream validator ignores `engine_ns`. The 48 projections are generated in
tests from reviewed oracle goldens only.

## Untrusted caller rows (RF08-01)

`validate_keyword_reply_projection` treats the supplied oracle row as untrusted input.
It recomputes the reviewed row from the validated lane via `oracle_row_for_lane`,
requires the exact closed eight-key row with strict primitive types (booleans are
never accepted as integers), and compares the reply against the **recomputed** row
only. A coherently forged row/reply pair, a wrong singleton ID, a forged
`field`/`term`, or a count-only match can therefore never validate itself.
