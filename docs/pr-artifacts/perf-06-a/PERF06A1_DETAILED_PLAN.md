# PERF-06-A1 — Query-Local BM25 Term-Weight Preparation

**Detailed implementation and independent-review contract — NOT YET EXECUTED**  
**Repository:** `yduchesne/quervant`  
**Milestone / series:** `v0.1-perf` / PERF-06-A (scoring and postings efficiency)  
**Planned individual PR:** PERF-06-A1 (create a **new PR**, not the PERF-06-A charter PR #119)  
**Proposed branch:** `dev/perf06-a1-precomputed-bm25`  
**Required baseline:** `origin/main` at `2a74017958c8ac61948f931e8745bf8134827025`, the merged PERF-06 planning baseline, including PERF-05-B1–B5  
**Related PRs:** PERF-05 #117 MERGED; PERF-06 planning #118 MERGED; PERF-06-A series charter #119 OPEN/DRAFT at authoring time  
**Authority:** `docs/PERF_OPTIMIZATION_ROADMAP.md` § “PERF-06-A”; `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`; `docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md` on its separate charter branch; `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`; `AGENTS.md`; `docs/TESTING.md`.  
**Source inspection:** Author inspected actual `main@2a74017958c8ac61948f931e8745bf8134827025` on 2026-11-23; the code/blob anchors in §3 are from that commit.  
**Authorization boundary:** User approval to **execute this plan** authorizes the bounded implementation, tests, documentation, branch/PR preparation and source push described below. It does **not** authorize production benchmark acquisition, profiling, altering scores, weakening tests, accepting residual correctness failures, merging, or starting A2.

---

## 0. Mandatory execution contract — read before any code

> **Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

1. Execute exactly the design in this file; **do not design** a different scoring cache, change score algebra, add a new benchmark family, introduce a storage format, or select additional optimizations.
2. Apply the **most restrictive matching decision** from the §12 matrix on every exception. Use only an AUTO-RESOLVE action whose source and trigger conditions are proven. For unforeseen conditions, **HARD STOP the affected work** and continue only provably independent, safe, previously authorized work.
3. Make an **independent PERF-06-A1 implementation PR** based on merged `main`. **Do not put A1 implementation code on the planning/charter branch `dev/perf06-a-scoring-postings-series` or PR #119**. A1 is one PR, not an accumulation of A1–A4.
4. This is a **correctness-first implementation**, not a performance-acquisition PR. No `quervant-bench run`, real timed A/B or B-only campaign, profiler, `perf record`, Criterion run, Tantivy/Lucene benchmark, RustFS/container start, process-cold testing or benchmark configuration/result mutation. Real local `FsDirectory` correctness tests **are** mandatory.
5. Never change the benchmark results or approved warm criteria to make an optimization pass. A4 owns the separately authorized **consolidated warm qualification** after A1–A3.
6. Before creating a commit, report all files changed, explain every deviation, run the applicable required local checks, and include exact failures. Branch push/PR creation is a routine authorized step if credentials work; **do not merge** or mark the overall PERF-06-A series complete.

## 1. Purpose, narrow optimization, and why A1 exists

**Single dominant architectural concern:** The same BM25 inverse-document-frequency (**IDF**) expression is computed repeatedly for each matched document, even though it depends only on the query's `(field_id, term)`, snapshot-wide live count `n`, and term document frequency `df`.

In the merged PERF-05 code, `crates/quervant-core/src/search/score.rs::bm25()` executes:

```rust
let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
```

for every scored hit. `crates/quervant-core/src/search/execute.rs` calls `bm25()` from **three** production scoring sites: the generic term loop, generic phrase loop, and PERF-05 strict one-term candidate loop. The already existing `compute_stats()` calculates immutable `n`, `df`, `avgdl` and per-segment lengths before those loops.

**A1 will prepare IDF once per eligible `(field_id, term)` in that query-local `FieldStats` and reuse it for every matching document across all segments and both scorer paths**. It will reuse the current `FieldStats.df` hash-map allocation, *not* add a second cache, persistent index data or new score representation. Repeated per-document `tf`, `dl`, BM25 denominator and result materialization remain as today.

**Required outcome:** identical `f64::to_bits()` scores and identical error/limit/cancellation/sort/total-hit behavior on the same committed index, while structurally eliminating per-hit IDF logarithms for prepared terms. **Do not claim a wall-clock performance improvement in A1**; A4 measures the cumulative A-series impact.

## 2. Mandatory invariant/acceptance traceability

| ID | Required invariant (observable) | Explicit counterexample / negative case | Tests / evidence |
| --- | --- | --- | --- |
| INV-01 | Every finite BM25 score has **identical IEEE-754 bits** to the pre-A1 formula for the same `tf,df,n,dl,avgdl`. Preserve formula **parenthesization**, conversions and floating-point operation order. | Associative rewrite of `tf*(k1+1)/denominator` or factoring `BM25_B / avgdl` changes rounding; `n>2^53`, `tf>2^53`, fractional avgdl. | A1-U01, U02, U03, U08; A1-I01; existing SC02–SC06 and P03. |
| INV-02 | IDF is evaluated at most **once per present, valid query `(field_id,term)`**, across all matching docs and segments. No per-hit `ln` on prepared paths. | One logarithm in each loop iteration; an `idf` cache created afresh for each segment; a second map lookup per hit. | A1-U04/U05; code inspection of all three scoring sites. |
| INV-03 | `tf==0`, `n==0`, or `avgdl<=0.0` returns `+0.0` **before** invalid-`df` checks, as before. An invalid `df>n` is surfaced **only if positive scoring actually reaches it**. | Eager `InvalidScore` from preparation on a no-hit or zero-score request. | A1-U02/U06, A1-I02; existing `bm25_boundaries_and_invalid`, B4 U06. |
| INV-04 | `df==0` or an absent term does **not** force an unnecessary IDF computation during preparation; if a synthetic scoring input unexpectedly requests a missing/zero-df term, the scorer retains the old `bm25(tf,0,n,dl,avgdl)` behavior. | Empty/absent warm query slowed by avoidable log; unrecognized positive term throws a new error. | A1-U03/U04/U06; SC01. |
| INV-05 | Generic owner-deduplicated term/phrase scoring and strict single-term scoring use the **same prepared term accessor**, keeping addition order, positive/negative leaf policy and `+0.0` score initialization unchanged. | Repeated term in OR/Prefix scored twice; negative/typed-only leaf acquires a score; strict path differs from generic. | A1-U07; A1-I01/I03; SC09–SC11; `pr14_unified_mixed` M08/M13. |
| INV-06 | Existing `compute_stats` counts, live/tombstone handling, work/byte and cancellation charges, and scoring ledger reservations remain unchanged. | Recount live bitmap; extra postings pass; new charged or uncharged full-doc collection; early error before required decoding. | A1-U05/U09; A1-I02; existing PERF-05 B2/B4 tests and SC12/SC13. |
| INV-07 | Scores, keys, order, `total_hits`, cursor/PIT, and reopening the same durable local index are unaffected. | Changed K10/K100 ordering or pagination; different score bits after commit/reopen or under snapshots. | A1-I01/I02/I03; SC03–SC15; `pr07_properties` P03/P05. |
| INV-08 | A1 has **no persistent-format, API, storage, index-write, or distributed side effects**. The prepared term weight lives only in the current query's `SnapshotStats`. | `SegmentReader` shared cache, new serialized field, writer change, remote request, global/static production cache. | Explicit changed-path audit and `git diff`; A1-U04 (request-local behavior). |

**Pre-implementation correctness gate:** Before source edits, map every INV ID above to its tests, check the old early-return/error ordering and both scoring paths, and inspect the existing B4 test injecting invalid `df` (see §3). If you find a contradiction, use §12; do not silently choose a replacement contract.

## 3. Verified current-main facts and source anchors

**These line numbers refer to `main@2a74017958c8ac61948f931e8745bf8134827025`. Verify symbols and Git object SHAs before editing; STOP if semantically different.**

| Path / blob SHA | Source anchor and pre-A1 behavior | A1 relevance |
| --- | --- | --- |
| `crates/quervant-core/src/search/score.rs` / `a843ddc52f8951b286c6ed69a33aa5d7d694c9fa` | lines 20–50: `BM25_K1=1.2`, `BM25_B=0.75`; `bm25` checks `tf==0 \|\| n==0 \|\| avgdl<=0`, then `df>n`, then calculates IDF, denominator, score, and finite/nonnegative check. | Frozen scalar reference and extraction point. |
| Same file | lines 63–100: `FieldStats { n, avgdl, df: HashMap<String,u64>, lengths }`; `doc_freq()` returns `0` if absent. | Replace value type with in-place prepared term data; preserve `doc_freq` API. |
| Same file | lines 235–460: `compute_stats()` creates `FieldStats`, accumulates `df` through (1) all-live persisted norms/dictionary, (2) partially-live postings, (3) legacy reconstruction, then computes `avgdl` and inserts `FieldStats`. | Prepare IDF **after** all df/live processing, not while `df` is partial. |
| Same file | lines 468–~838: scalar golden/boundary tests, legacy/norms/live-count/multisegment tests; `field_stats_lookup_defaults` directly constructs `FieldStats`. | Extend tests; no new test infrastructure required. |
| `crates/quervant-core/src/search/execute.rs` / `497c683a3553d30b8cd877652e4961eb300eda76` | lines ~1680–1775: `score_segment` generic, owner-deduplicated term and phrase score loops; calls `score::bm25` for each owned term/phrase match. | Two call-site substitutions only; preserve ownership and accumulation. |
| Same file | lines ~1783–1820: `score_single_term_candidates` (PERF-05-B4), uses `FieldStats`, `doc_freq`, and per-hit `bm25`. | Third call-site substitution; keep scored-vector and ledger unchanged. |
| Same file | lines ~3680–4135: PERF-05-B4 exact-bit tests, empty/subset behavior, 48M+64M reservation, invalid-df injection at ~4040, `tf>2^53`, fallback. | Extend existing tests; **adjust only the invalid-df test's direct internal map mutation** for the new value type. |
| `crates/quervant-core/src/search/unified.rs` / `89419f6404ce248c5912be0565d8ed9e9eb7aedf` | `collect_mixed` calls `compute_stats` and `execute::evaluate_lexical_with` for generic and eligible strict term; real response returns scores and sort. | **No A1 code modification**; run integration regressions. |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` / `dca43449e911343db24d14d350c01ca3cf8a2fb4` | existing SC01–SC15 use real `FsDirectory` + public Index/commit/reopen + `UnifiedSearcher`, assert exact score bits across sort, K, multi-segment, PIT/cursor, invalid and repeated paths. | Reuse and add A1-specific independent formula/shape verification; no mock scorer. |
| `crates/quervant-core/tests/pr07_properties.rs` / `07cc25e96ba2afc997012dab66dc036ceda181dc` | P03 independent BM25 reference; P05 partitioning/score properties. | Run unchanged; don't duplicate the independent oracle. |
| `crates/quervant-core/tests/pr14_unified_mixed.rs` / `427ca96881e5dd329ce5294f86c1926a5c2c0026` | M08 duplicate positive leaves, M13 generic lexical parity. | Run unchanged as generic-path regression. |
| `AGENTS.md` / `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` | mandatory **local** stable/MSRV fmt, clippy, tests, workspace coverage ≥85%, doc and final reruns; CI does not replace local checks. | Follow exactly; do not waive mandatory gates because A4 owns performance. |
| `.github/workflows/ci.yml` / `df63adc43f9f27e1e84e539d00bb2d78361c5c03` | `pull_request` and `push: main`, Rust stable/MSRV, all-features, adapter tests, coverage and RustFS jobs. | **Do not edit CI**, duplicate triggers, or manually start services for this code change. |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` / `d7b3e9934bf5f9abdeb6bccc42a2dfde734593b8` | PERF-06-A1 explicitly says “Precompute query-constant BM25 term weights… exact externally returned scores”; A2/A3/A4 separate. | Keep scope A1 only; no roadmap status update before review/acceptance. |

**Source status reconciliation:** At authoring, A1 is **NOT STARTED**. PERF-05 implementation is **DONE + MERGED**. PR #119 is **a separate series-charter PR, not A1 implementation**. No evidence from A1 may be claimed until agent executes the actual commands in the required environment.

## 4. Final architecture (frozen; no alternate design delegation)

### 4.1 Query-local ownership and type layout

Keep `FieldStats<'a>` and its current `df` hash map, **changing only the hash-map value** from `u64` to a private, copyable term-stat record. Use these exact names unless the existing code now contains a collision (collision ⇒ D02 HARD STOP):

```rust
#[derive(Debug, Clone, Copy)]
struct PreparedTermStat {
    doc_freq: u64,
    idf: Option<f64>,
}

pub(crate) struct FieldStats<'a> {
    pub(crate) n: u64,
    pub(crate) avgdl: f64,
    pub(crate) df: HashMap<String, PreparedTermStat>,
    lengths: Vec<SegmentLengths<'a>>,
}
```

- **Visibility is frozen:** `FieldStats.df` remains `pub(crate)` as in current source, with value type `PreparedTermStat` that is also `pub(crate)` and has `pub(crate) doc_freq`; `idf` remains private to `score.rs`. This permits the existing B4 invalid-df test in `execute.rs` to mutate **only** `stat.doc_freq` and retain its error assertions. No public API is added. Do not introduce a test-only production method or a global cache.
- The term keys remain cloned **once at statistics creation**, as they already are; do not create another keyed `HashMap`, rehash strings, intern terms, or allocate a sidecar `Vec` per query/segment.
- Each record belongs exclusively to one invocation of `compute_stats`; `SnapshotStats` owns it as before. Its `idf` is **immutable after preparation** and reused by all segment scorers for the query. No `RefCell`/`OnceCell`/mutex, global counter/cache, lifetime extension, unsafe code, or persisted format.
- Keep `FieldStats::doc_freq(term) -> u64`, returning `0` when absent; change its implementation to access `.map(|stat| stat.doc_freq).unwrap_or(0)`.
- `FieldStats::length()` and `SnapshotStats::field()`/`verified_segment_live_count()` remain byte-for-byte unchanged except unavoidable formatting.

### 4.2 Pure IDF preparation function

Add a **private** helper named `prepare_idf(doc_freq: u64, n: u64) -> Option<f64>` in `score.rs`. Algorithm is **exactly**:

```rust
fn prepare_idf(doc_freq: u64, n: u64) -> Option<f64> {
    if doc_freq == 0 || n == 0 || doc_freq > n {
        return None;
    }
    let df = doc_freq as f64;
    let n = n as f64;
    Some((1.0 + (n - df + 0.5) / (df + 0.5)).ln())
}
```

**Why those guards:** `df==0` should consume **no log** in absent/zero-hit queries; if an anomalous synthetic scorer later needs a `df==0` term it must fall back to the old scalar function. `n==0` must still yield `+0.0` on score without raising errors. `df>n` must **not** fail during preparation: the previous error occurs only inside BM25 if scoring actually reaches the invalid term. Guarding it records `idf=None` and defers the exact old typed error.

Do not precompute the BM25 denominator or a rearranged numerator/slope: these depend on `tf` and/or `dl`, and factoring floats is not proven bitwise equivalent. Keep constants `BM25_K1=1.2` and `BM25_B=0.75`, conversions, and their original expression grouping.

### 4.3 Preparation when statistics are complete

At `compute_stats()` initialization, change only the `df` map element type:

```rust
stats.df.insert(term.clone(), PreparedTermStat { doc_freq: 0, idf: None });
```

For all **three** existing df accumulation branches, change `get_mut` uses to mutate `stat.doc_freq` with the **same** `checked_add` and **same** `SearchError::ResourceLimit` limits and requested values. Do not change dictionary lookup, live-bitmaps, count loops, charge order, cancellation polls, `stats.avgdl`, or error types.

**Only after** all segments' df accumulation and after the existing `stats.avgdl` assignment, prepare each already-collected term exactly once:

```rust
for stat in stats.df.values_mut() {
    stat.idf = prepare_idf(stat.doc_freq, stats.n);
}
```

Do not use `?` here, change the method's error behavior, skip negative/present terms, or allocate new objects. `compute_stats` must return the same `SnapshotStats` shape and remain read-only w.r.t. segments.

### 4.4 Preserve legacy scalar BM25 as fallback and independent comparison seam

Retain `pub(crate) fn bm25(tf,df,n,dl,avgdl) -> SearchResult<f64>` and **all existing return/error semantics**:

```rust
if tf == 0 || n == 0 || avgdl <= 0.0 { return Ok(0.0); }
if df > n { return Err(SearchError::InvalidScore {
    detail: "document frequency exceeds the live-document count",
}); }
```

After the guards, compute IDF using exactly the original expression (or a single shared private helper with the **identical expression and float conversions**). Keep the existing finite/nonnegative result check and its original string `"BM25 produced a non-finite or negative score"`.

Extract **one** private arithmetic helper `bm25_with_idf(tf: u64, dl: u64, avgdl: f64, idf: f64) -> SearchResult<f64>` containing **only the old post-IDF arithmetic**, with the exact operation order:

```rust
let tf = tf as f64;
let dl = dl as f64;
let denominator = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * dl / avgdl);
let score = idf * (tf * (BM25_K1 + 1.0)) / denominator;
if score.is_finite() && score >= 0.0 {
    Ok(score)
} else {
    Err(SearchError::InvalidScore {
        detail: "BM25 produced a non-finite or negative score",
    })
}
```

Do not multiply by a reciprocal, reorder additions, reassociate the denominator, rewrite BM25 constants as approximations, turn score into `f32`, use SIMD/`mul_add`, change the error description, or remove the legacy scalar helper.

### 4.5 One prepared scoring API, including exact fallback/invalid precedence

Add **exactly one** crate-local method on `FieldStats`:

```rust
pub(crate) fn bm25_score(&self, term: &str, tf: u64, dl: u64) -> SearchResult<f64>
```

Its exact decision tree:

1. Look up the query term **once**: `let Some(stat) = self.df.get(term) else { return bm25(tf, 0, self.n, dl, self.avgdl); };`. Missing term reproduces the existing `doc_freq` default of zero, including `df==0` scoring on malformed/synthetic inputs.
2. Before validating `stat.doc_freq`, if `tf==0 || self.n==0 || self.avgdl<=0.0`, return `Ok(0.0)` as the legacy function does.
3. If `stat.doc_freq>self.n`, return `Err(SearchError::InvalidScore { detail: "document frequency exceeds the live-document count" })` **at the scoring site**.
4. If `stat.doc_freq==0`, call `bm25(tf,0,self.n,dl,self.avgdl)`; this anomalous case has no cached IDF and must preserve the old arithmetic.
5. Otherwise, obtain `stat.idf`. Its absence is an **internal impossible state** on valid, finalized `compute_stats`: return a typed `SearchError::CorruptIndex { detail: "prepared BM25 IDF missing for valid term".to_owned() }` rather than using an invented value, silently recomputing it on the hot path, or panicking. This defensive branch does not trigger for valid submitted data; test it with an injected test-only `PreparedTermStat`.
6. Return `bm25_with_idf(tf, dl, self.avgdl, idf)`; do not alter the `+0.0` initialization or contribution-addition order in the caller.

**Important semantic edge:** The original `bm25` returns `Ok(0.0)` when `avgdl` is `-0.0`, `-Infinity`, or zero; when `avgdl` is `NaN`, the early guard is **false**, and its denominator produces an invalid score. Preserve this exact behavior. Do not normalize NaN/Infinity or replace `avgdl<=0.0` with `!(avgdl>0.0)`.

### 4.6 Exactly three call-site substitutions in `execute.rs`

Change only the arguments used to obtain each BM25 contribution:

- **Generic term leaf:** Replace the existing block `let df = field_stats.doc_freq(&term.term);` + inner-loop `super::score::bm25(*freq,df,field_stats.n,dl,field_stats.avgdl)?` with `field_stats.bm25_score(&term.term, *freq, dl)?`. Remove the now-unused local `df`; leave owner checks, posting loop, `scores.get_mut`, `dl` retrieval and `*current += contribution` unchanged.
- **Generic phrase leaf:** Replace `super::score::bm25(*freq,field_stats.doc_freq(term),field_stats.n,dl,field_stats.avgdl)?` with `field_stats.bm25_score(term, *freq, dl)?`. Leave phrase-match iteration order, deduplication/owner rules, `dl` and addition unchanged.
- **Strict one-term scorer:** Remove the now-unused line that resolves `df` before the candidate loop; replace `super::score::bm25(freq,df,field.n,dl,field.avgdl)?` with `field.bm25_score(term, freq, dl)?`. Leave `score=0.0_f64`, `score += contribution`, positive-leaf guard, the loop over exact `(doc_id,freq)` pairs, and all ledger reserve/release behavior unchanged.

**Do not** modify `UnifiedSearcher`, `score_segment`'s owner algorithm, Top-K, heap, retained duplicate prefilter, raw postings, segment format, query compilation, generic/strict selection eligibility, score aggregation order, resource meters, or public APIs. No `idf` computation is permitted inside any prepared candidate loop.

### 4.7 What is and is not prepared

| Term/field state after `compute_stats` | IDF stored | Scoring behavior | Error timing |
| --- | --- | --- | --- |
| `n>0`, `1<=df<=n` | `Some(original IDF)` | Same IDF for every hit and segment; old denominator per hit | Same as old score validation |
| `n>0`, `df==0` | `None` | No result on normal absent term; synthetic score request calls original `bm25` | No eager error |
| `n==0` | `None` | `Ok(+0.0)` first | No eager error even if malformed `df>n` |
| `df>n` | `None` | `Ok(+0.0)` if `tf==0`/`n==0`/`avgdl<=0`; otherwise old typed `InvalidScore` | Only when scoring reaches this term |
| Field exists, query term not in map | No record | Original `bm25(tf,df=0,...)` fallback | Same as before |
| `avgdl=NaN`, positive `tf` | IDF present if valid n/df | Same non-finite denominator rejection | Typed `InvalidScore` when scoring |
| `avgdl<=0` | Irrelevant | `Ok(+0.0)` first | No new eager errors |
| No positive lexical owner / typed-only / negative-only | Unused | Existing no-score or `+0.0` behavior | No scoring-related new error |

**Validation at PR review:** A1 must prove every row of this table with direct tests or inherited full-path acceptance. A design introducing an eager error, caching scores across queries, or changing floating-point grouping **fails** the contract.

## 5. Cross-component impact, ownership, persistence, and failure matrix

| Component / consumer | Action | Mandatory observation |
| --- | --- | --- |
| `score.rs` `compute_stats` and `FieldStats` | Change map value and add query-local preparation/accessor | Existing live/df/avgdl/lengths and typed failures stay identical. No second map or shared state. |
| `execute.rs` `score_segment` term + phrase | Use prepared accessor | Exact score bits, single owner per `(field,term)`, original addition order. |
| `execute.rs` `score_single_term_candidates` | Use same accessor | Strict single-term bit parity and original 48M+64M modeled ledger behavior. |
| `unified.rs` and public `UnifiedSearcher` | **No code changes** | Real vertical tests verify same hits, scores, pagination and mixed queries. |
| `IndexWriter` / `SegmentReader` / postings/norms codec | **No code changes** | Real local committed index/reopen through existing SC suite; no schema/format change. |
| Legacy vs new norms segments | **No code changes** | Existing `compute_stats` mixed-segment and `pr07_properties` regression passes. |
| Batch/mutation/aggregation/typed/geo branches | **No code changes** | Existing suites pass through normal CI; no new score for filter-only paths. |
| RustFS/S3/remote directory/distributed | **No code changes**, **no new RustFS startup** | A1 changes pure scorer; repository-required hosted CI remains authoritative where configured. |
| Benchmark framework/config/results | **No changes**, **no acquisition** | `git diff` shows no modified benchmark artifacts or new perf observations. |

**Failure behavior:** Existing `SearchError::InvalidScore`, `SearchError::ResourceLimit`, `SearchError::Cancelled`, `SearchError::CorruptIndex`, cursor/query validation errors remain typed and ordered at their prior boundaries. This PR does not add I/O, transactions or persistent state; commit/restart/cleanup are unchanged. A memory-allocation failure in the existing query-term hash map remains governed by its preexisting behavior; do not add an extra allocation structure. Any changed query error, even if earlier detection seems “safer”, requires **HARD STOP**, not a self-authorized semantic change.

**Idempotency:** Scoring the same immutable snapshot twice constructs fresh `SnapshotStats` and prepared weights; no cross-request reuse or mutable global state. No durable write, retry, cache invalidation or cleanup path is created.

**Out of scope:** PERF-06-A2 document/frequency decoder; PERF-06-A3 codec/writer/skip layout; A4 benchmark; PERF-06-B ordinal sort; PERF-06-C winner-only deferred scoring; `BM25_K1`/`BM25_B` changes; WAND/block-max; changed scores or removal of scoring on noncompetitive candidates; heap/duplicate-key redesign; new tracing, timing, profile, config/CI/RustFS modifications.

## 6. Precise tests — write failing tests before production changes

**Oracle rule:** Testing only that strict and generic scorers agree is insufficient because both use the new accessor. Compare new results to a **frozen pre-A1 scalar implementation** in a `#[cfg(test)]` function using the exact original five scalar arguments, conversions and math, or to real persisted baseline score bits. The existing `pr07_properties::bm25_reference` is independent and must stay unchanged. Never generate “expected bits” by calling the new helper under test.

### Unit test table (new stable IDs)

| ID | Exact fixture/action | Expected result |
| --- | --- | --- |
| **A1-U01** | In `score.rs` test, include frozen original BM25 scalar formula. For valid cases `(tf,df,n,dl,avgdl)` including `(1,1,3,2,2.0)`, `(3,2,5,10,4.5)`, `u64` inputs above `2^53`, and a fixed LCG seed `0xa106_a106_2026_1123` generating **256** tuples with `1<=df<=n<=10^6`, `1<=tf<=10^6`, `0<=dl<=10^6`, finite positive `avgdl` formed from `1..10000` over 4. | `FieldStats::bm25_score` equals frozen scalar `to_bits()` for **every** tuple. On scalar `Err`, compare the same error category; no tolerance or epsilon. |
| **A1-U02** | Exhaustive early guards for `tf=0`, `n=0`, `avgdl=+0`, `-0`, `-1`, `-Infinity` combined with both valid df and `df>n`; `avgdl=NaN` and `+Infinity` with positive `tf`. | Same `Ok(+0.0)` bits or `InvalidScore` as frozen scalar; `df>n` errors only after early guards; no eager error from preparation. |
| **A1-U03** | A missing term and an existing zero-df term; `tf=0` and synthetic `tf>0`, `n>0`. | No IDF precomputation for absent/zero-df; missing/df0 fallback reproduces frozen scalar `df=0` bits/errors. |
| **A1-U04** | Test-only thread-local `Cell<u64>` counter in **one private IDF calculation helper only**; after `compute_stats` with a real `golden_norms.seg` and one positive term, record counter; call strict & generic scorer repeatedly and in two segment contexts using the same `SnapshotStats`. | Counter increases **once per nonzero valid `(field,term)` on preparation**, not with hits/segments; independent extra query gets a fresh preparation; absent/zero-df adds zero. Counters exist only in `#[cfg(test)]`, never in production. |
| **A1-U05** | Real `golden_norms.seg`, `golden.seg`, all-live/partially-live/fully-dead and two-segment `compute_stats`; verify exact `n`, `df`, avgdl and lengths plus prepared IDF. | Existing field-length/live summary tests pass; correct per-query IDF for valid df; no new document scans or work/cancel calls. |
| **A1-U06** | Synthetic `PreparedTermStat` with `df=n+1` in `FieldStats` after preparation; test both `tf=0` and `tf>0`; synthetic valid `df>0` with `idf=None`. | Early `+0.0` precedes invalid df; then exact `InvalidScore` string; impossible prepared-missing case gives precisely `CorruptIndex("prepared BM25 IDF missing for valid term")`, never panic or silent fallback. |
| **A1-U07** | Execute generic `Term`, `Phrase`, duplicated `Term/Prefix`, negative-only, typed-only; strict eligible single-term. Compare actual score bits against frozen scalar per occurrence/owner, not just generic vs strict. | Correct positive owner attribution, no double score, no score for typed/negative, same initialized `+0.0`, same `total_hits` and order. |
| **A1-U08** | Two or more contributions to the same doc, mixed term frequencies and lengths, including values above `2^53` and variable-length terms; compare the **exact ordered sum** of frozen scalar contributions. | Identical final `f64::to_bits()`. No rearranged term addition, no altered `score +=` or sort ranking. |
| **A1-U09** | B4 exact/one-below modeled scored reservation, cancellation and invalid df, after changing internal df map type. | Same `ResourceLimit` limit/requested values and release, unchanged cancellation classification and exact score-bit tests. |
| **A1-U10** | No input terms, missing scoring field, all-negative and all-zero live snapshot. | Correct empty stats/positive count/no scores; no unwarranted IDF; no new allocations outside old query-term map. |

**Test-only instrumentation placement:** In `score.rs` create `#[cfg(test)] thread_local!` `PREPARED_IDF_EVALS: Cell<u64>` and increment **inside** the function evaluating the IDF logarithm (which both prepared and scalar fallback may call). Reset/read within a single thread in A1-U04; do not write a production metric, tracing label, global synchronization primitive or per-hit clock. If the compiled `#[cfg(test)]` counter causes a test-only difference in performance, that is irrelevant to A4's future uninstrumented benchmark and must not be used as timing evidence.

**Red-first requirement:** Preserve baseline test PASS evidence, then add U01/U04/U06 and at least one new real-path acceptance test *before* implementing the new scoring method; require the expected RED failure to be **missing new API/type/counter**, not an unexpected environment problem or false oracle. Implement §4 exactly and turn RED to GREEN without weakening tests.

### Real production-path acceptance / integration table

| ID | Harness (real code and storage) | Required assertion |
| --- | --- | --- |
| **A1-I01** | Extend `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` with one `a1_i01_prepared_scoring_matches_formula_and_generic` test using existing `build`, `request`, `search_ok`, real `FsDirectory`, 9 docs with distinct term frequencies and lengths, both explicit ascending sort and relevance sort. | Independently derive `n`, `df`, `dl`, `avgdl` from fixture docs; evaluate old scalar BM25 formula **in the test**, compare each returned `Some(score).to_bits()` exactly. Include `Query::And(vec![term()])` forcing generic fallback, K10 and K100, and exact total count and keys. No fake executor. |
| **A1-I02** | Run all existing SC01–SC15 in that file, including multi-segment commit/reopen, delete/upsert/PIT, cursors, invalid/cancel/resource, real FS reopen and repeated queries; run `pr07_properties` P03/P05. | Exact score bits and error boundaries preserved in real public Index / UnifiedSearcher and legacy LexicalSearcher paths. |
| **A1-I03** | Run `pr14_unified_mixed` including M08 repeated leaves, M13 lexical parity; run `pr15h_b_sort_materialization` including eligible vs fallback and PIT/cursor; relevant B4 unit tests. | Generic/strict/typed/batch-adjacent behavior intact, no altered sort/score contracts. |

**Required focused commands from repository root** (actual integration uses local FS and in-memory fixtures, no external services):

```bash
cargo test -p quervant-core --lib bm25
cargo test -p quervant-core --lib a1_
cargo test -p quervant-core --lib b4_u0
cargo test -p quervant-core --test pr15i_d2a_scoring_contract
cargo test -p quervant-core --test pr07_properties
cargo test -p quervant-core --test pr14_unified_mixed
cargo test -p quervant-core --test pr15h_b_sort_materialization
```

If some filters yield **zero tests**, that is **not a PASS** for the intended gate: correct the filter once by inspecting the exact compiled test list (`cargo test -p quervant-core --lib -- --list`) and rerun matching tests. This is an allowed **command/filter-only** correction, not license to modify implementation or test assertions. Record test counts.

### No-real-benchmark gate

There is **no A1 performance acquisition**. The following are prohibited during A1: `quervant-bench run`, `cargo bench` **execution** (compile-only CI checks remain permitted), `perf record`, Criterion runtime, direct timed query loops for qualification, pinned A/B or B-only campaigns, and any editing of `benchmarks/studies/**` config/result JSONs. A1 qualification is **correctness and implementation**, not wall-time speedup.

## 7. Baseline, branch, source, and PR operations — exact steps

1. From a clean local checkout, run `git fetch origin` and `git status --short`; inspect `git rev-parse origin/main`, `git rev-parse HEAD`, and `git branch --show-current`. **Do not stash, reset, force-clean, or overwrite unknown work**. The intended `origin/main` is `2a74017958c8ac61948f931e8745bf8134827025`. If it has changed, D02 applies; no auto-rebase or silent source substitution.
2. Verify the content SHA/behavior of `score.rs`, `execute.rs`, `AGENTS.md`, and the PERF-06 roadmap against §3. Verify that the code still has the three exact `bm25` production call sites and that `FieldStats.df` is `HashMap<String,u64>`. Any substantive divergence ⇒ D02/HARD STOP before implementing dependent edits.
3. Check the charter context: PR #119 is a **series planning PR**. Do not check out its head for A1 implementation. Branch **from `origin/main`**:

```bash
git fetch origin
git switch -c dev/perf06-a1-precomputed-bm25 origin/main
# Verify starting commit *before* editing:
git rev-parse HEAD
# Required: 2a74017958c8ac61948f931e8745bf8134827025
```

4. Before source changes, run the baseline focused scoring suite (A1-I02). Record count and result; this is **baseline evidence**, not A1 feature proof. If a failure occurs, classify via §11 and §12; do not call it pre-existing without reproducing on baseline.
5. Create/port the approved plan text verbatim as `docs/pr-artifacts/perf-06-a/PERF06A1_DETAILED_PLAN.md` (do not edit it to conceal deviations). Create `PERF06A1_EXECUTION_REPORT.md` only as work progresses; include observed commands, gates, exceptions and final status.
6. Add RED tests; implement §4 in the authorized files only; run GREEN tests and required regression gates. Use normal commits; no forced pushes. New branch push and PR creation are authorized after the code is reviewable; do not start A2 or merge.
7. **PR identity:** title `PERF-06-A1: Prepare query-local BM25 term weights`; target **`main`**; draft state while gates are pending; link to PERF-06-A charter PR #119 and merged PERF-06 roadmap PR #118. Keep the A1 PR separate from #119. If `gh` auth is unavailable after pushing, record **PR_CREATION_BLOCKED**, do not invent a PR URL, and continue safe reporting.

## 8. Implementation sequence (do not reorder semantic work)

| Phase | Action | Required result / gate |
| --- | --- | --- |
| **P0** | Source SHAs, branch/clean tree and mandatory baseline tests; verify §2 invariant-to-test mapping and §4 decision table. | Source/roadmap consistent; baseline tests classified. No code edits on unexpected tree. |
| **P1** | Add U01, U04, U06 and I01 tests first. Run focused RED. | RED due solely to missing prepared scorer/type or expected new behavior; freeze tests before implementation. |
| **P2** | Add `PreparedTermStat`, `prepare_idf`, `bm25_with_idf`, `FieldStats::bm25_score` and update df initialization/three checked-add branches + final preparation in `score.rs`. | No new map/cache or modified score order/error behavior; all §4 rows supported. |
| **P3** | Make the **three exact** `execute.rs` call-site changes; update B4 invalid-df test for changed internal map value type. | No unrelated executor/owner/heap/score algorithm edits; strict+generic use same accessor. |
| **P4** | GREEN unit/real-FS integration, boundary/negative tests and remaining targeted regression. | All INV-01–08 traces pass. No withheld failures. |
| **P5** | Mandatory Rust workspace local QA + MSRV (see §9), final `git diff --check`, scope/semantic audit and independent self-review. | Every applicable local gate PASS or accurately BLOCKED; coverage ≥85%. |
| **P6** | Commit allowed paths, push branch, open draft A1 PR, verify remote SHA/diff; record CI status. | A1 isolated PR, complete execution report, no merge or performance claim. |

**Progress checkpoints are informational, never a request for permission.** Continue from phase to phase automatically under §0 except when a §12 blocker applies.

## 9. Authoritative QA, coverage, and evidence

**Follow `AGENTS.md` and `docs/TESTING.md`; mandatory local QA cannot be waived by a hosted green check.** The repository's CI also runs all-features checks, benchmark-adapter build tests and integration jobs; do not add new triggers or manually duplicate remote workflow runs. In local shell, run the following after the **last code/test change** (use project rustup toolchains; don't modify global toolchain settings):

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo llvm-cov --workspace --all-targets --fail-under-lines 85
cargo doc --workspace --no-deps
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets -- -D warnings
cargo +1.85.0 test --workspace --all-targets
```

The current `.github/workflows/ci.yml` also has **all-features Rust checks**. To identify feature-only defects before CI, run locally if available without reconfiguring the host:

```bash
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets --all-features
```

Coverage is the **workspace-wide production Rust line coverage**, not an A1-only percentage. Require ≥85% and inspect new code branches (`df==0`, `n==0`, invalid df, missing term, valid prepared idf, nonfinite). If `cargo llvm-cov` or MSRV is absent, make **one normal installation attempt** using the existing toolchain/package workflow (no privileged system modifications), then mark that gate **BLOCKED** if still unavailable. Don't claim A1 ready for review until the mandatory local gate passes or an explicit maintainer exception is recorded.

**Test topology:** ordinary Rust unit tests plus existing real `FsDirectory` writer→commit→reader→UnifiedSearcher tests. These exercise no external service. No local RustFS container is necessary: the altered code has no remote/storage boundary, but GitHub's existing CI `rustfs` job may run automatically on the PR; report its actual status honestly, do not proactively start a service. No cache/benchmark/CI modifications required.

**Failure classification** for every mandatory failed command: introduced regression, feature implementation defect, deterministic pre-existing failure (proved on baseline), nondeterministic/flaky failure (with reproducible evidence), or environment/harness failure. A single green retry is **not** proof that a failure was unrelated. Preserve logs, tested SHA, commands and counts. If an essential correctness/coverage gate fails, stop source promotion; continue independent documentation/report tasks only.

**Final rerun:** If any source/test/manifest changes after gate execution, rerun affected mandatory checks **including workspace coverage**. If only the execution report changes later, verify text/links/`git diff --check` and do not rerun Rust merely for a doc-only adjustment.

## 10. Expected changes, files protected, and documentation

**Only these source/test files may change** (first two required; third recommended for real-path independent acceptance):

- `crates/quervant-core/src/search/score.rs` — prepared IDF term stats, existing df accumulation, scalar arithmetic, unit tests.
- `crates/quervant-core/src/search/execute.rs` — **three exact BM25 call sites** and existing B4 direct-map test seam; extend scorer-specific unit tests if needed.
- `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` — add A1-I01 independent real `FsDirectory` scoring acceptance; preserve SC01–SC15.

**Only these documentation files may be added**:

- `docs/pr-artifacts/perf-06-a/PERF06A1_DETAILED_PLAN.md` — this approved plan.
- `docs/pr-artifacts/perf-06-a/PERF06A1_EXECUTION_REPORT.md` — exact evidence, matrix IDs, status and no benchmark run.

**Protected / unchanged:** `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/ROADMAP.md`, `docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md`, PR #119 branch and files, `AGENTS.md`, `Cargo.toml` and `Cargo.lock`, `.github/workflows/**`, public contracts, other `crates/**`, every `segment/**` codec/writer, `UnifiedSearcher`/plan/Top-K/duplicate code, all RustFS/S3/distributed/vector modules, and every benchmark configuration/result. No unreviewed unrelated formatting. If an essential edit outside the allowlist is required, D21 HARD STOP that affected change and request a plan amendment.

**Status documentation:** A1 is **PLANNED/IN REVIEW** until independent review and gate acceptance. Do not update `docs/PERF_OPTIMIZATION_ROADMAP.md` to DONE in this implementation PR. The merged PERF-06 series roadmap remains the authority; subsequent accepted-status reconciliation is a maintainer-controlled documentation step. Do not update PERF-06-A2/A3/A4 descriptions or change performance-acceptance thresholds.

## 11. Evidence, acceptance, independent reviewer checklist, and next PR

### Implementation gate

- [ ] New A1 branch begins from exact source baseline and changes only allowed paths.
- [ ] `FieldStats.df` retains the **same map** with a `PreparedTermStat` value; each valid positive query term prepares IDF **once**, no extra map or per-segment cache.
- [ ] No IDF computation inside either generic or strict per-hit loop for prepared terms; all three sites use `bm25_score`.
- [ ] `bm25` scalar and score denominator arithmetic preserve float operation order, early errors and exact error strings; no public API, index format or ledger changes.
- [ ] Unit and real-FS integration tests added with actual independent bitwise oracle, RED evidence and GREEN evidence.

### Correctness gate

- [ ] INV-01–INV-08 traced to actual named passing tests, with counters for IDF-once and distinct no-hit behavior.
- [ ] Exact bit equality on positive/zero/large/degenerate inputs and both generic and strict scorers.
- [ ] Existing SC01–SC15, P03/P05, mixed/phrase/positive-owner/cursor/PIT and B4 resource/cancellation cases passed.
- [ ] Native local writer/commit/reopen real-boundary tests passed, not mocks.
- [ ] Unresolved residual risk is listed and either explicitly authorized or **BLOCKED**; 85% coverage alone does not override a semantic failure.

### Mandatory QA and PR gate

- [ ] Stable + MSRV fmt/clippy/tests, workspace line coverage ≥85%, cargo doc, applicable all-features and hosted CI actually passed (or each explicitly BLOCKED).
- [ ] `git diff --check`, allowed-file audit, no benchmark timing or service startup.
- [ ] New A1 PR targets main, not series charter #119; pushed HEAD equals remote; no force push; no merge.
- [ ] Final report records starting/main SHA, final/remote SHA, changed paths, PR URL if actually created, each test command count/outcome, coverage %, host/toolchain, accepted exceptions, errors, and **A1_IMPLEMENTED_CORRECTNESS_READY_FOR_INDEPENDENT_REVIEW** only after all mandatory gates pass.

### Required final disposition strings

- `PERF06_A1_IMPLEMENTED_CORRECTNESS_READY_FOR_INDEPENDENT_REVIEW` — all mandatory local + applicable CI gates green, PR open and unmerged; **not a performance claim**.
- `PERF06_A1_IMPLEMENTED_CI_PENDING` — local gates green; hosted required CI not complete; review/merge gate remains pending.
- `PERF06_A1_IMPLEMENTED_UNVERIFIED_<GATE>` — source code exists but a mandatory gate remains blocked/failing; do not claim ready.
- `PERF06_A1_HARD_STOP_<CAUSE>` — correctness/source/architecture requires new decision. Record precise affected work and independent work completed.

**Next-stage boundary:** After **independent review and human acceptance of A1**, the planned PERF-06-A2 detailed plan can be authored separately. A2 handles doc/frequency-only postings decoding; A1 never implements it, and A4 (not A1) runs the consolidated warm campaign.

### Suggested PR description (only after actual implementation)

> **PERF-06-A1 — Query-local BM25 IDF preparation.** Prepare each valid positive `(field,term)` weight once in existing query-local `FieldStats`, reuse it in generic term/phrase and strict one-term scoring while retaining identical IEEE score bits and typed error precedence. Reuse PERF-05 executor/ledger and public real-FS scoring tests. No segment-format changes, postponement of scores, benchmark acquisition, RustFS, or additional caches. Include RED/GREEN and local/hosted QA evidence. Dependent stage: PERF-06-A2; performance qualification: A4.

## 12. Preauthorized Architectural Decisions and Exception-Handling Matrix

**This matrix is binding.** Classify before pausing. Select the most restrictive matching rule; unknown conditions affecting implementation ⇒ **HARD STOP**. `DEFER AND CONTINUE` applies only to tasks demonstrably independent of the blocked gate; it is not authority to invent an algorithm. Every row requires log evidence (file/function/command, observed state, action, affected gate, owner). “Auto” **never** means modify unrelated scope, skip a mandatory test, or retry a benchmark.

| ID | Observable trigger / source check | Category | Exactly authorized action | Prohibited action | Evidence / affected gate / approval owner |
| --- | --- | --- | --- | --- | --- |
| **D01** | `origin/main` exactly `2a740179…` and expected score/execute blobs and call sites match | AUTO-RESOLVE | Branch from exact main and execute P0 onward | Branch from PR #119 or old PERF-05 | Record SHAs, clean tree; source gate |
| **D02** | Main/source/roadmap or one of three call sites differs substantively from §3 | HARD STOP | Record actual SHA/diff/symbol, stop source-dependent A1 edits | Auto rebase, guess rename, cherry-pick into charter | Maintainer to amend source contract |
| **D03** | Clean tree; only known ignored `target/`/build output exists | AUTO-RESOLVE | Leave ignored output alone; proceed | `git clean`, reset/stash other changes | Scope safety |
| **D04** | Unknown tracked/untracked source or staged changes on starting branch | HARD STOP | Preserve state; report paths and stop checkout/edit | Reset, overwrite, stash, force-clean | Repository safety / maintainer |
| **D05** | `FieldStats.df` is still existing query-local `HashMap<String,u64>` | AUTO-RESOLVE | Change **value only** to prescribed `PreparedTermStat` | Add global map, second hash table, persistent cache | Implementation gate; diff |
| **D06** | `compute_stats` has exactly three known checked-add df branches and final avgdl | AUTO-RESOLVE | Update all three accumulation values, preserve `checked_add` errors and compute idf after stats complete | Precompute with incomplete df, recalc live bitmap | INV-03/06; tests |
| **D07** | Expected three `bm25` call sites in generic term, phrase and strict scorer | AUTO-RESOLVE | Replace with `FieldStats::bm25_score` exactly per §4.6 | Widen eligibility, modify Top-K or scorer ownership | INV-01/05; diff and tests |
| **D08** | Additional real BM25 production call site found | HARD STOP | Record path and call context; stop dependent code pending amendment | Leave it silently unoptimized or invent a new pathway | Full scorer coverage / maintainer |
| **D09** | Existing B4 invalid-df test inserts raw `u64` into map | AUTO-RESOLVE | Change **that test only** to mutate `PreparedTermStat.doc_freq`, keep `idf` private and old error assertions | Delete test, ignore invalid-df case | B4 regression |
| **D10** | `df==0`, `n==0`, `df>n`, or `tf==0` observed in preparation/scoring | AUTO-RESOLVE | Follow §4.7 matrix exactly, preserve error timing | Eager invalid score, create dummy idf, divide by zero | INV-03/04 |
| **D11** | Prepared term `df>0`, `df<=n`, `n>0`; valid finalized stats | AUTO-RESOLVE | One IDF per map entry; score through frozen arithmetic | Per-hit `ln`, algebraic reassociation | INV-01/02 |
| **D12** | Valid positive term has `idf=None` (injected or invariant violation) | AUTO-RESOLVE | Emit exact specified `CorruptIndex` error; cover in unit test | Panic or silently use `0.0`, recompute on every hit | INV-01/03 internal fail-closed |
| **D13** | Synthetic scoring term missing from stats or existing zero-df | AUTO-RESOLVE | Preserve fallback `bm25(tf,0,n,dl,avgdl)` | New error or eager log on absent query | INV-04 |
| **D14** | Frozen scalar reference and new score differ by even one `f64` bit on valid case | HARD STOP | Record inputs/bits and stop score edits; leave RED evidence | Epsilon tolerance, change canonical BM25 expression | INV-01; architecture owner |
| **D15** | Scalar and prepared paths disagree on error type/detail, or early error time | HARD STOP | Preserve exact counterexample; stop affected implementation | Convert errors or change precedence | INV-03; maintainer |
| **D16** | Deterministic test needs stronger oracle but fits §6 fixtures and allowlist | AUTO-RESOLVE | Add a *test-only* seeded case using frozen formula, no new dependencies | Re-implement scorer architecture, weaken assertions | A1 tests; report seed |
| **D17** | New test-only IDF counter interferes with parallel tests | AUTO-RESOLVE | Use **thread-local** `Cell`, reset within test thread; no production instrumentation | Global shared counter or serialize whole suite | A1-U04; source diff |
| **D18** | RED fails solely because prepared method/type/counter absent | AUTO-RESOLVE | Record expected failure and proceed to P2 | Treat unrelated env failure as feature RED | Red-first gate |
| **D19** | RED fails for unrelated baseline assertion or fixture error | HARD STOP | Preserve log and stop dependent implementation; report exact failing input and request corrected test contract | Weaken oracle, silently fix semantic fixture, or declare expected RED | Testing/maintainer |
| **D20** | Formatting/import/lint-only defect in allowlisted A1 files | AUTO-RESOLVE | Fix bounded syntax/format; rerun affected tests | Broaden architecture, ignore Clippy warning | QA evidence |
| **D21** | Necessary file/API/format change outside allowlist, altered public score contract or new dependency | HARD STOP | Record source/constraint and seek amended plan | Quietly modify codecs/CI/roadmap or cargo flags | Scope/maintainer |
| **D22** | Positive-owner/phrase/strict results, score bits, or ledger accounting regress | HARD STOP | Preserve failed test/inputs; no automatic design alternatives | Relax limits, skip test, switch collector | Correctness owner |
| **D23** | Baseline-targeted tests pass, new feature tests and real-FS integration pass | AUTO-RESOLVE | Proceed with mandatory QA P5 and diff audit | Skip mandatory gates because targeted suite green | Regression/correctness evidence |
| **D24** | Required local stable/MSRV toolchain, `cargo llvm-cov` unavailable | DEFER AND CONTINUE | Make one normal nonprivileged setup attempt, document blocker; continue independent docs/review | Claim PASS from hosted CI, privileged system changes | Mandatory QA BLOCKED; human exception |
| **D25** | A mandatory suite/coverage fails (not proven baseline), or test flaky without evidence | HARD STOP for promotion | Classify with baseline proof and evidence; retain code, continue independent report only | Unbounded reruns, exclusion, lower 85% | QA gate / maintainer |
| **D26** | All local source and coverage gates pass, hosted CI still pending | DEFER AND CONTINUE | Push/open draft PR, report `CI_PENDING`, finish docs; do not declare ready | Claim hosted success or merge | CI gate / reviewer |
| **D27** | Exact CI for final pushed commit succeeds with appropriate QA, local gates pass | AUTO-RESOLVE | Report READY FOR INDEPENDENT REVIEW; leave PR open | Merge or start A2 | Acceptance owner |
| **D28** | PR #119 charter remains draft/open or is later merged | AUTO-RESOLVE | Keep A1 PR separate and based on `main`; refer to charter | Commit implementation on charter branch | PR topology |
| **D29** | Existing host has no RustFS, Docker, Tantivy/Lucene or profiler | AUTO-RESOLVE | Ignore entirely for A1; no service is required | Install/start services, switch scope to benchmarks | Nonapplicable external work |
| **D30** | Branch push succeeds but `gh pr create` credentials fail | DEFER AND CONTINUE | Preserve pushed branch SHA and report `PR_CREATION_BLOCKED`; finish review artifact | Invent PR URL, force-push, edit PR #119 | PR operation / maintainer |
| **D31** | Documentation/status change after final code QA only | AUTO-RESOLVE | Revalidate docs, scope and `git diff --check`; no unnecessary Rust rerun | Claim changed code was tested if code changed later | Final reporting |
| **D32** | Unforeseen condition not explicitly covered and dependent work cannot be proven safe | HARD STOP | Stop affected work, preserve all evidence, report smallest required human decision | Design by analogy or guess | Architecture / maintainer |

**Precedence and escalation:** HARD STOP > DEFER AND CONTINUE > AUTO-RESOLVE. A hard stop is scoped; if source scoring work is blocked, independent test-evidence and documentation may continue **without** claiming implementation completion. No row authorizes circumventing the source safety, correctness, coverage or PR/merge boundaries.

## 13. Coding-agent terminal report format

Use this exact outline (fill with **actual** values, not planned assertions):

```text
REPO / BRANCH / PR:
MAIN_BASE_SHA:
START_SHA:
FINAL_SHA:
REMOTE_VERIFIED_SHA:
SOURCE_FILE_BLOBS_VERIFIED:
CHANGED_PATHS:

INVARIANT_TRACE:
  INV-01: <tests + actual pass/fail evidence>
  ...
  INV-08: <tests + actual pass/fail evidence>

RED_EVIDENCE: <command, expected compilation/behavioral failure>
GREEN_EVIDENCE: <commands, test counts>
REAL_FS_ACCEPTANCE: <tests with actual FsDirectory and reopen>
SCORING_BIT_PARITY: <number of cases, any mismatches, seed>
IDF_PREPARATION_COUNT: <term/field count, across-segment verification>
RESOURCE/CANCELLATION/CORRUPTION: <tests and actual results>

MANDATORY_QA:
  stable fmt/clippy/test/coverage/doc: PASS/FAIL/BLOCKED with counts/percentage
  msrv fmt/clippy/test: PASS/FAIL/BLOCKED
  all-features: PASS/FAIL/BLOCKED
  hosted CI: PASS/FAIL/PENDING with run IDs
  git diff --check and allowlist: PASS/FAIL

EXCEPTION_ROWS_APPLIED: <IDs + trigger/action/evidence>
UNRESOLVED_FAILURES_AND_CLASSIFICATION:
NO_REAL_PERFORMANCE_ACQUISITION: TRUE/FALSE
NO_RUSTFS_START: TRUE/FALSE
NO_FORMAT_CHANGE: TRUE/FALSE
NO_PR_119_IMPLEMENTATION_CHANGES: TRUE/FALSE
PR_OPEN_AND_UNMERGED: TRUE/FALSE

DISPOSITION: <one exact §11 disposition>
NEXT: independent review of A1; no A2 or A4 execution yet.
```

**End of plan.**
