# PR 15D workload `pr15d_v1`

**Status:** FROZEN. This file and `pr15d_v1.json` define the engine-neutral
comparative lane. Changing either requires a new workload version.

The machine-readable authority is `pr15d_v1.json`. This document explains the
semantics and the deliberately narrow comparability claim.

## What is compared

The mandatory lane is **exact, unanalyzed `Keyword` membership** over a
deterministic TSV corpus. That is the only lane for which full three-engine
equivalence is provable with the pinned adapters:

| Field | Indexed as | Stored | Searched | Sorted |
|---|---|---|---|---|
| `doc_id` | exact `Keyword` | yes | no | yes (ascending) |
| `key` | exact `Keyword` | yes | yes | no |
| `group` | exact `Keyword` | yes | yes | no |
| `body` | not indexed | yes | no | no |
| `payload` | not indexed | yes | no | no |

No stemming, stop-word filtering, Unicode normalization, relevance scoring,
boost, wildcard, phrase, or engine-specific query rewriting is allowed. Every
term input is lowercase ASCII. Results are ordered by `doc_id` ascending
(lexical), never by engine score.

Because the mandatory queries return a constant-score membership set, the
**primary score comparison is explicitly `NOT_APPLICABLE`**. Exact-term results
must never be described as scored lexical performance.

## Corpus formula

For `i` in `[0, N)`:

```text
doc_id  = 'd' + format(i, '08d')
key     = 'singleton' if i == 0 else ('common' if i % 2 == 0 else 'other')
group   = 'medium' if i % 8 == 0 else 'different'
body    = 'alpha beta' if i % 2 == 0 else 'gamma delta'
payload = 'payload-' + format(i, '08d')
```

`N` is fixed at `10000` and `100000`. The TSV is UTF-8 with `\n` line endings,
one header line, and no timestamps, randomness or locale-dependent formatting.

## Query classes

| Class | Field | Term | Exact matches |
|---|---|---|---|
| `absent` | `key` | `never` | 0 |
| `rare` | `key` | `singleton` | 1 (`d00000000`) |
| `medium` | `group` | `medium` | `N/8` |
| `common` | `key` | `common` | `N/2 - 1` |

Each `(N, class, K)` pair with `K` in `{10, 100}` is one mandatory lane, id
`pr15d_v1/<N>/<class>/k<K>`; 16 lanes per engine per trial. Every lane is
measured in two explicitly labelled regimes:

- `process_cold`: a fresh adapter process and a fresh index reader per sample.
  This is **not** an OS page-cache-cold claim.
- `warm`: one process and one open reader, five untimed warmups, then 20
  measured samples.

## Oracle

`corpus/oracle.py` enumerates matching rows directly from the raw TSV bytes,
counts them exactly and takes the first `K` lexically sorted `doc_id` values. It
imports no adapter. The generator re-verifies the bytes it just wrote, and the
harness validator re-verifies again before any timing is certified.

## Secondary scored lexical lane

A BM25 (`k1=1.2`, `b=0.75`) lane over `body` was considered but is **not
published**: an identical score, document-statistics, length-normalization and
tie contract cannot currently be proven across all three engines with public
APIs. Until that proof exists the lane is
`SEMANTICALLY_NONCOMPARABLE`, contributes no cross-engine ratios and never
changes the mandatory exact-term claim.
