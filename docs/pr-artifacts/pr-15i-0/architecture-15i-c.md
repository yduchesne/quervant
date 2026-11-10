# 15I-C — Postings-Driven Exact-Count/Top-K Physical Execution (DESIGN CONTRACT)

> **Historical design only; execution line retired (2026-11-09).** The
> subsequently implemented PR 15I-C experiments failed their frozen performance
> guardrails and were safely rolled back. This specification records the
> original **unimplemented** design intent; it is **not** authority to resume
> implementation, change acceptance thresholds or mark PR 15I-C delivered.
> See [final PR 15I-C closeout](../pr-15i-c/closeout.md).

**Status: `DESIGN_PROPOSAL_ONLY` — no query code modified; detailed
implementation approval required.**

PR 15I-0 changes no production code and no query executor. Everything below is a
fixed design direction for a future, separately authorised implementation PR.

## Owner and goal

Search execution only. **No format change in the first C experiment.**

Targets: high matched-set allocation, unnecessary scoring for explicit sort,
sort-tuple construction, and separate intermediate containers.

Preserve **all** existing searchable operators, typed/JSON/geo predicates and
aggregation by **falling back** to the current generic pipeline whenever the
specialised operator cannot prove exact equivalence.

## Mandatory shape for the first physical operator

Eligible only when the compiled root is a single positive exact `Term` with:

- precisely one analysed term,
- no negation, no phrase/pattern/fuzzy, no typed clauses,
- no aggregation,
- no cursor (`after`),
- an explicit ascending `doc_id` sort **only** when the field is proven
  equivalent to byte-exact lexical order by the current schema/codec.

It must yield exact `total_hits` by **exhausting the matched candidates even
after K winners are found**. There is **no early-exit shortcut for counting**.

Use a postings iterator over effective-live docs, exact old work/budget/
cancellation charges, bounded K top-hit records, and deferred scoring only where
returned score bits and sort semantics are provably unchanged. Duplicated logical
keys, superseded/deleted documents and per-segment visibility must be checked
exactly as before.

## Fast-path fallback

Any semantic ambiguity, unsupported sort field, multi-token analysis, unproven
work/error ordering, cursor/PIT/batch interaction or extension of the feature
surface routes immediately to the existing general execution.

"Safe fallback" is **not** permission to bypass corrupted-data detection or
budget rejections. First-error precedence, duplicate detection, missing/explicit
null handling, tie order, score bit equality, sort tuples and projection values
must remain exact.

## Architectural module ownership

`search/unified.rs`, `search/unified_plan.rs`, `search/execute.rs`,
`search/score.rs`, `search/typed_compare.rs` and `segment/reader.rs`.

No additional public `UnifiedSearcher` entry point.

The approved PR 15G/15H candidates that failed their performance gates do **not**
count as validated building blocks; their evidence is retained as **negative
historical controls**.

## Future measurement requirements

- Stage-level instrumented candidate enumeration, scoring, sorting and selected
  projection via strictly query-local benchmark-only/probe instrumentation where
  possible.
- If existing public APIs cannot expose a stage without changing production, the
  future separate detailed plan must authorise narrowly scoped build-time
  instrumentation with no release overhead.
- Require: the nine frozen PR 15D lanes, explicit-sort controls, an adversarial
  query shape/fallback matrix, exact output/oracle/score-bit parity, allocation
  counts and per-lane median/tail latency, source/execution fingerprints and real
  clear contention probes.
- **Reject performance** if the primary `common`/K100 and `common`/K10 medians
  each fail to improve by **≥ 10 %** on the same host, or if any non-primary lane
  regresses **> 5 %**, absent a separately approved new gate decided before
  coding.
- Do not overfit to the `doc_id` name or fixed PR 15D corpus values: eligibility
  must be schema-verified, not a string check.

## Postings compression

A subsequent, separate 15I-C subphase may evaluate block-compressed postings/skip
data and SIMD after the format-preserving operator is qualified. Its codec/feature
compatibility requires a different detailed plan and must never be combined
silently with this first execution experiment.

## Measured evidence (PR 15I-0, source `48e7d3a`, not a forecast)

Same-session warm medians (ns) from the qualified three-engine campaign, exact
match + exact count + explicit ascending `doc_id` sort:

| Lane | Quervant | Tantivy | Lucene |
|---|---:|---:|---:|
| 10K absent K100 | see `measurements.md` | | |
| 10K rare K100 | see `measurements.md` | | |
| 10K medium K100 | see `measurements.md` | | |
| 10K common K100 | see `measurements.md` | | |
| 100K absent K100 | see `measurements.md` | | |
| 100K rare K100 | see `measurements.md` | | |
| 100K medium K100 | see `measurements.md` | | |
| 100K common K100 | see `measurements.md` | | |
| 100K common K10 | see `measurements.md` | | |

The authoritative table is
[`measurements.md`](measurements.md); it is not duplicated here to avoid stale
numbers. The physical sort encodings differ (Quervant `Keyword` column, Tantivy
numeric ordinal, Lucene `SortedDocValues`), so these are *logical-result*
comparisons, not operator-parity proofs.

Sampled CPU attribution (PR 15F) is deliberately **not** converted into
milliseconds. The exclusive/inclusive partitions and the unclassified bucket are
in [`performance-attribution.md`](performance-attribution.md). In this campaign
the unclassified exclusive share is 14.55 %–88.56 % per lane, which means the
sampled evidence does **not** by itself justify a specific execution rewrite; the
future PR must add stage-level measurement first.

## Open questions / decision required before implementation

1. Whether `doc_id` ordering can be proven byte-exact-lexical for every schema
   that uses it, or only for the frozen corpus shape.
2. The precise budget-charge equivalence between the fast path and the generic
   planner for rejected/cancelled queries.
3. Where stage-level instrumentation may live without violating the no-release-
   overhead rule.
