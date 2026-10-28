# PR 15B independent oracle and provenance

All expected values below are computed from `i` and `i % 8` over the frozen
PR15A template table. No expected value is obtained by calling `Index`,
`IndexWriter`, `UnifiedSearcher`, `TypedSearcher`, `execute_batch_pinned` or any
other production evaluator. The engine is only the system under test.

## Canonical provenance

| Item | Value |
|---|---|
| Canonical file | `benchmarks/datasets/pr15a_v1.json` |
| Frozen SHA-256 | `104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087` |
| Checked by | `unified_diag_common::assert_canonical_fixture_digest`, every benchmark run and validator |
| B-T01 witness | digest match; row-by-row constants; flipped-byte mismatch |
| B-T02 witness | row and corpus digests deterministic; `N` or `S` change changes the digest |

The eight-row fixture remains the semantic golden fixture. The 2K/10K/100K
corpora are synthetic scaling extensions with their own `rows_sha256` and
`corpus_sha256` values, emitted before timing in
`quervant-pr15b-fixture-v1` metadata.

## Exact formulas

With `t(i) = i % 8`, `TS_BASE = 1_000_000`:

| Predicate | Independent rule | Exact total |
|---|---|---|
| `title=alpha` | `t(i) ∈ {0,1,4,7}` | `N/2` |
| `title=gamma` | `t(i) ∈ {3,4,5}` | `3N/8` |
| absent sentinel | never | `0` |
| typed `n ∈ {0}` | `i == 0` | `1` |
| `alpha AND n >= N/2` | `t(i) ∈ {0,1,4,7} && i >= N/2` | `N/4` |
| IPv4 `/24` | `t(i) ∈ {0,1,7}` | `3N/8` |
| CIDR ∩ time | `t(i) ∈ {0,1,7} && N/4 <= i < N/2` | `N/8` (half-open) |
| `body.severity=2` | `t(i) ∈ {1,4}` | `N/4` |
| `host=h1` | `t(i) ∈ {0,2,4}` | `3N/8` |
| `host=h2` | `t(i) ∈ {1,5,7}` | `3N/8` |
| `host=h3` | `t(i) ∈ {3,6}` | `N/4` |
| `sum(n)` per host | direct loop over `i` | computed independently |
| global exact-distinct host | template host set size | `3` |

Ordering oracles:

- Explicit numeric `n` ascending: keys are `d00000000, d00000001, …`.
- Explicit `host` ascending: group order `h1,h2,h3`; inside each group, keys
  ascending (the contract's final logical-key tie-break).
- Typed default sort: logical key ascending. U02/U05/U06 compare the exact
  ordered sequence after truncation to `K=100`.
- Aggregation group order: canonical `Keyword` order `h1,h2,h3`.

## Independence limitations (explicit, not waived)

1. **Lexical top-K selection beyond eight rows.** Reimplementing BM25 would be a
   second scorer, not an independent oracle. U03/U04 therefore gate:
   exact total (`3N/8`, `N/4`), exact returned length `min(total, K)`, uniqueness
   and membership in the independently computed full match set. For `N <= 100000`
   the full match set is materialized untimed with a zero-field projection and
   compared exactly. The *ordering* of the top 100 is not independently scored;
   it is a `HYPOTHESIS`-grade ranking surface, not a correctness claim.
2. **Relevance scores.** No expected score bit pattern is asserted for the
   scaling corpus. The approved PR15A eight-row oracle remains the semantic
   ranking witness.
3. **U09 global distinct.** The public `Aggregation` contract's
   `ExactDistinct` is a per-group metric. Global exact-distinct host is the
   grouped response's cardinality, validated against the independent template
   set size `3` and reported separately from per-group count/sum.
4. **U13 geo provenance.** The fixed geometry corpus uses the PR12 schema/query
   contract but is not the `pr15b_v1` corpus. Its digest and physical topology are
   emitted as `geo_n8_s1`; it is labelled separately in every report.

## Failure behaviour

- Any mismatch calls `panic!` in the benchmark/test oracle gate. The benchmark
  process aborts before future timed regions and emits no qualifying timing for
  the mismatched lane.
- The validator refuses a trial with a missing lane, fewer than 20 samples, a
  bad digest, an oracle gate other than `PASS`, a dirty/contended/unknown
  environment, duplicate lanes or a source SHA mismatch.
- Negative self-tests for every rejection class live in
  `validate-pr15b.py self-test` and are invoked by `tests/pr15b_diagnostics.rs`
  B-T13.
