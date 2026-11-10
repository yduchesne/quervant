# PR 15I-D0 attribution report

**Status: `D0_PAIRED_CAMPAIGNS_BLOCKED_SOURCE_LOCK`.**
**Attribution: `NO_ATTRIBUTION_MEASUREMENT`.**
**Quantitative ranking: `RANKING_NOT_QUALIFIED` (no valid P samples).**

No A/Q/P ratio, stage share, or hypothesis rank is reported. The diagnostic
source derivative is proven and its recorder compiles in a disposable smoke
build, but the prescribed paired campaigns require the frozen PR 15D Quervant
adapter to build with `--locked`, which it cannot at BASE.

## 1. Diagnostic architecture (implemented, source-proven)

- **A** — pristine BASE adapter, `op=query`, no timers.
- **Q** — one diagnostic binary, `op=query`, recorder never activated.
- **P** — the *same* diagnostic binary, `op=query_probe`, recorder activated
  before the public query call and exported after `engine_ns` has stopped.

The committed repository contains only the deterministic materializer
(`patch_instrumented_source.py`), the independent proof (`source_proof.py`), the
controller (`run.py`) and the verifier (`verify.py`). The production `crates/`
tree and the frozen `benchmarks/pr15d` adapter are unchanged.

The materialized derivative changes exactly six scratch paths:

```text
crates/quervant-core/Cargo.toml                         + pr15id0-probe = [] (non-default)
crates/quervant-core/src/search/mod.rs                  + cfg-gated `pub mod d0_probe;`
crates/quervant-core/src/search/d0_probe.rs             + new recorder (scratch only)
crates/quervant-core/src/search/unified.rs              + scoped timers/counters
crates/quervant-core/src/search/execute.rs              + scoped timers/counters
benchmarks/pr15d/adapters/quervant/src/main.rs          + one query_probe arm
```

Independent proof: rebuilding BASE + the approved insertions + the recorded
`rustfmt` pass is byte-identical to the scratch tree, and deleting only the
inserted bytes restores BASE exactly. The derivative fingerprint is

```text
09d7b8cda7229223ea123d45eec12f2d5f7c8c64afeb0043fc1ac0511ee275d6
```

The one non-literal addition is a mechanical Rust name-resolution import
(`use super::d0_probe;` in two files), recorded in the decision log.

Recorder vocabulary is closed: ten stage labels and three counters, exactly as
the protocol. There is no per-document `Instant::now`, no async sampler, no
logging, no file I/O and no allocation inside the timed region.

## 2. Why the campaigns did not run

The prescribed build sequence is:

```text
cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml \
  --target-dir target/pr15i-d0/build/A
```

for arm A, and the same with `--features quervant-core/pr15id0-probe` for Q/P.
Both fail closed because the adapter's frozen `Cargo.lock` lacks `lz4_flex` and
`twox-hash`. Updating that lock is explicitly prohibited by the plan, and no
substitute binary, source tree or fake sample was used.

A disposable compile smoke (lock updated only inside the smoke worktree) proved
that the instrumented derivative compiles and that the feature is wired
correctly. That smoke produced no timing and is not used in any table.

## 3. Nine-lane ratio matrix

Not available. The required two campaigns × 24 slots × 9 lanes × 20 samples
(8,640 timed observations, 2,160 warmups, 96 contention probes, eight index
builds) were not executed. Every lane is therefore:

```text
pr15d_v1/10000/absent/k100     NO_DATA
pr15d_v1/10000/rare/k100       NO_DATA
pr15d_v1/10000/medium/k100     NO_DATA
pr15d_v1/10000/common/k100     NO_DATA
pr15d_v1/100000/absent/k100    NO_DATA
pr15d_v1/100000/rare/k100      NO_DATA
pr15d_v1/100000/medium/k100    NO_DATA
pr15d_v1/100000/common/k100    NO_DATA
pr15d_v1/100000/common/k10     NO_DATA
```

No A/A drift, Q/A, P/Q or P/A value exists. No stage median, share, residual or
`OTHER` value exists. No counter parity was observed from a real query.

## 4. Stage decomposition contract (for a future qualified run)

For every P sample the verifier requires, in integer nanoseconds:

```text
EVAL_RESIDUAL = evaluate_ns - leaf_decode_ns - membership_ns - score_vector_ns
OTHER         = engine_ns - (plan_ns + reader_live_ns + expand_ns + stats_ns
                             + evaluate_ns + candidate_ns + projection_ns)
```

Both must be `>= 0`; no clamp, no reassignment of a negative residual and no
sum-of-medians partition is permitted. The exclusive per-sample categories are
`plan`, `reader_live`, `expand`, `stats`, `leaf_decode`, `membership`,
`score_vector`, `eval_residual`, `candidate`, `projection`, `other` and must sum
exactly to `engine_ns`. `evaluate_ns` is a parent; its children are not
double-counted.

For this exact-term, all-live PR15D workload the verifier also requires
`matched_docs == scored_docs == candidate_docs == total_hits`, including the
absent zero-hit lane. That is a structural witness for this workload only, not a
general engine assumption.

Per-category medians are reported separately from the median total; **the sum of
category medians is not the median total** and must not be presented as one.

## 5. Closed hypothesis register (not measured)

| ID | Region | Current-source mechanism under measurement | Status |
|---|---|---|---|
| `H-CANDIDATE` | `candidate_ns` | per-hit doc-key/keyword-sort ownership, bounded heap, comparisons in `collect_mixed` | NOT MEASURED |
| `H-LEAF` | `leaf_decode_ns` | postings/leaf-data expansion and creation in `build_leaf_data` | NOT MEASURED |
| `H-MEMBERSHIP` | `membership_ns` | `BTreeSet` match population and per-document predicate/accounting | NOT MEASURED |
| `H-SCORE` | `score_vector_ns` | scored `BTreeMap` construction, contribution and vector conversion | NOT MEASURED |
| `H-LIVE` | `reader_live_ns` | reader acquisition plus effective-live bitmap work | NOT MEASURED |
| `H-STATS` | `stats_ns` | snapshot live counts, dictionary lookups and field stats | NOT MEASURED |
| `H-PLAN` | `plan_ns` | schema bindings, codec, fingerprint, compiler | NOT MEASURED |
| `H-PROJECTION` | `projection_ns` | selected-result projection and validation | NOT MEASURED |
| `H-OTHER` | `other_ns` + `eval_residual_ns` | unclassified work | NOT MEASURED; mandatory further attribution if it tops a future ranking |

No new hypothesis name is introduced. No `possible_scope` / `WORTH_REVIEW` label
is claimed without P data. If a future qualified ranking is topped by `H-OTHER`,
the next decision is **more attribution**, not an implementation.

## 6. Requirements-equivalence matrix (documentation only)

| Requirement | Quervant | Tantivy 0.22.1 | Lucene 9.12.3 |
|---|---|---|---|
| Exact keyword membership | yes (`Keyword` term) | yes (`TermQuery`, Basic) | yes (`TermQuery`) |
| Exact total hits | yes | yes (`Count`) | yes (`TotalHitCountCollector`/`count`) |
| Ascending `doc_id` order | `Keyword` column sort | numeric `ordinal` fast-field sort | sorted doc values |
| Scoring in timed lane | positive-term BM25 execution present | none (`Count` + numeric sort) | none for count/sorted collection |
| Projection of `doc_id` | yes | yes | yes |
| Oracle comparable? | logical count/order only | logical count/order only | logical count/order only |
| Physical cost comparable? | **no** | **no** | **no** |

This matrix exists to prevent any future report from presenting logical parity as
physical parity.

## 7. What a future qualified run must produce

If the frozen lock decision is made and a fresh two-campaign series is run with
this tooling, the report must include:

- all nine A/A, Q/A, P/Q and P/A values per campaign, not only primaries;
- per-sample exclusive arithmetic and counter parity;
- median share per category with p95 and raw distribution;
- `H-OTHER` as an explicit observed residual, never as “optimization headroom”;
- the fixed non-causal shortlist sorted by 100K common/K100 median exclusive ns,
  with exact ties broken by the table order;
- `RANKING_NOT_QUALIFIED` whenever intrusion, partition, stability or canonical
  parity fails.

Nothing in this document authorizes PR 15I-D1 or an optimization.
