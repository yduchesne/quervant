# PR 15E-A — profiling report (measured)

- **Status:** `PROFILED_EVIDENCE_COMPLETE` — 20/20 authorized captures executed,
  `verify.py` → `EVIDENCE_COMPLETE`, `analysis_valid: true`, sanitized manifest
  published.
- **Acceptance:** `PENDING_REVIEW`; `MERGED = NO`; `PR15E_B_AUTHORIZED = NO`.
- **Source:** implementation commit `19ae3d7`, documentation/preparation commit
  `0f0091c` (measured HEAD), run `target/pr15e/20261031T164645Z-0f0091c`.
- **Evidence:** `verification.json` `52ec0465…`, `analysis.json` (81 entries),
  published manifest `benchmarks/reports/pr15e-a/profile-manifest.json`
  SHA-256 `adfe7eadc2d948ab335e11de78edb4e86691590e464c2660e60eb37e611b4bb7`.

Measured state is `CAPTURED_RAW` → `VERIFIED` → `REPORTED` for all 20 lanes. No
value in this report is inferred, modelled or copied from PR 15D-B.

## 1. Campaign window and topology

| Item | Value |
|---|---|
| Operator attestation | `<run>/attestation.json`, host `MSI`, window `2026-10-31T17:24:40Z … 2026-10-31T20:24:40Z` |
| Operator reply recorded verbatim | `now + 2h / now + 3h` (3 h envelope recorded) |
| First profiled request | `2026-10-31T17:24:45Z` |
| Last profiled request | `2026-10-31T17:44:53Z` (20 min 08 s total campaign) |
| Topology | one adapter process per capture (`QuerySession`, one `ReaderSnapshot`), 5 untimed warmups, then the timed loop; profiler wraps the adapter |
| Host | WSL2, kernel `6.18.33.2-microsoft-standard-WSL2`, `ext4`, Intel i7-10750H, host fingerprint `f450d284…` |
| Tools | `perf version 6.8.12` (X12 versioned fallback), `heaptrack 1.5.0`, `heaptrack_print 1.5.0` |
| Contention probe | `clear` before and after all 20 captures (40/40) |
| Oracle | every reply in every capture matched `oracle.expected()`; one mismatch aborts |

Interpretation limits fixed in advance: `perf` figures are **samples** (self +
nested inclusive), never stage durations; heaptrack counts are **allocation
traffic** for the whole profiled process (index open + 5 warmups + the timed
loop), not RSS, not peak logical memory, and not per-query rates.

## 2. Capture matrix (all 20, fixed order)

| # | Lane | Tool | Profiled queries | Samples | Lost | Allocations |
|---:|---|---|---:|---:|---:|---:|
| 1 | `n10000/absent/k100` | perf | 42 765 | 76 000 | 0 | — |
| 2 | `n10000/absent/k100` | heaptrack | 20 458 | — | — | 23 429 803 |
| 3 | `n10000/rare/k100` | perf | 2 452 | 64 000 | 0 | — |
| 4 | `n10000/rare/k100` | heaptrack | 379 | — | — | 35 117 791 |
| 5 | `n10000/medium/k100` | perf | 1 467 | 53 000 | 0 | — |
| 6 | `n10000/medium/k100` | heaptrack | 244 | — | — | 25 750 726 |
| 7 | `n10000/common/k100` | perf | 525 | 54 000 | 0 | — |
| 8 | `n10000/common/k100` | heaptrack | 166 | — | — | 23 010 511 |
| 9 | `n100000/absent/k100` | perf | 7 033 | 81 000 | 0 | — |
| 10 | `n100000/absent/k100` | heaptrack | 3 641 | — | — | 35 015 933 |
| 11 | `n100000/rare/k100` | perf | 308 | 84 000 | 0 | — |
| 12 | `n100000/rare/k100` | heaptrack | 49 | — | — | 50 123 071 |
| 13 | `n100000/medium/k100` | perf | 42 | 94 000 | 0 | — |
| 14 | `n100000/medium/k100` | heaptrack | 22 | — | — | 28 397 521 |
| 15 | `n100000/common/k100` | perf | 28 | 201 000 | **786** | — |
| 16 | `n100000/common/k100` | heaptrack | 23 | — | — | 38 081 899 |
| 17 | `n100000/absent/k10` | perf | 8 724 | 82 000 | 0 | — |
| 18 | `n100000/rare/k10` | perf | 363 | 84 000 | 0 | — |
| 19 | `n100000/medium/k10` | perf | 48 | 92 000 | 0 | — |
| 20 | `n100000/common/k10` | perf | 31 | 192 000 | 0 | — |

Capture 15 is labelled `SAMPLED_WITH_LOSS` (786 lost samples, decision X21); it
still yields 201 000 samples, so it qualifies, but no exact-share assertion is made
for that lane. The 11 other `perf` captures report 0 lost samples.

Reproduction (argv is stored verbatim, with absolute paths, in each private
`capture.json`; sanitized form):

```sh
perf record -g --call-graph dwarf -o <capture>/perf.data -- <run>/build/release/pr15d-quervant-adapter --index-dir <run>/indexes/n<N>
perf report --stdio --no-children --sort dso,symbol --percent-limit 0.5 -i <capture>/perf.data   > <capture>/perf-self.txt
perf report --stdio -i <capture>/perf.data                                                     > <capture>/perf-calltree.txt
heaptrack -o <capture>/heaptrack <run>/build/release/pr15d-quervant-adapter --index-dir <run>/indexes/n<N>
heaptrack_print -f <capture>/heaptrack.gz -p -a -T                                             > <capture>/heaptrack-report.txt
```

Symbols are recorded mangled (Rust v0); demangled names below are for reading
only (`c++filt -s rust`), and every `analysis.json` entry cites the exact mangled
spelling from the raw line.

## 3. Primary lanes — N=100 000, K=100

### 3.1 `absent` (`key:never`, 0 hits) — perf 81 000 samples, heaptrack 35 015 933 allocations

| Kind | Value | Category | Path (demangled) |
|---|---:|---|---|
| self CPU | 17.71 % | `live_doc_and_stats` | `execute::evaluate_lexical_with::<collect_mixed::{closure#5}>` |
| inclusive | 65.86 % | `live_doc_and_stats` | `execute::evaluate_lexical_with::<…>` (live-set build + per-live-doc loop) |
| inclusive | 23.92 % | `snapshot_and_reader` | `search::typed_compare::ColumnAccess::open` → `SegmentReader::open_columns` (23.92 %) → `ColumnReader::open` (23.92 %) |
| inclusive | 3.82 % | `postings_and_candidate_membership` | `slice::Iter<TermPostings>::any::<LeafData::matches::{closure}>` |

| Allocations | Category | Recorded innermost Quervant frame |
|---:|---|---|
| 34 232 993 | `live_doc_and_stats` | `BTreeSet<u64>::from_iter::<FilterMap<Enumerate<Iter<bool>>, …>>` |
| 651 658 | `query_validation_and_plan` | `segment::schema::copy_str_fallible` |
| 100 005 | `query_validation_and_plan` | `segment::schema::copy_str_fallible` |

Raw: `captures/n100000/absent/k100/perf/perf-self.txt` SHA-256
`8d05d204bd505acc2d6f60d8b4876e0685f8ee74f4fa7e70ac3d4f264007ad0c`;
`…/heaptrack/heaptrack-report.txt` SHA-256
`6460c5505114d9672363e97021fe7e80e45bb63c1a99afe946caba7cc48f7e7e`.
The `BTreeSet<u64>` symbol reproduces `execute.rs:1895` (`live_set` built from the
live flags) exactly: **34.2 M of 35.0 M allocations in this capture are the
per-query live-document set construction** (≈ 9 400 allocations per query).

### 3.2 `rare` (`key:singleton`, 1 hit) — perf 84 000 samples, heaptrack 50 123 071 allocations

| Kind | Value | Category | Path (demangled) |
|---|---:|---|---|
| self CPU | 9.55 % | `allocator_or_runtime` | `core::str::converts::from_utf8` |
| inclusive | 87.83 % | `projection_and_materialization` | `search::unified::project_selected_hits` |
| inclusive | 59.30 % | `projection_and_materialization` | `SegmentReader::stored_doc` (→ `SegmentReader::stored` 59.29 %) |
| inclusive | 29.53 % *(chain)* | `projection_and_materialization` | `segment::value::decode_scalar_budgeted` |

| Allocations | Category | Interpretation | Recorded innermost frame |
|---:|---|---|---|
| 49 716 535 | `allocator_or_runtime` | **UNRESOLVED** | `alloc::alloc::alloc` (stack truncated before any Quervant frame) |
| 27 000 000 | `projection_and_materialization` | MEASURED | `segment::value::decode_scalar_budgeted` |
| 5 400 000 | `projection_and_materialization` | MEASURED | `segment::reader::decode_doc_keys` |

Raw: `perf-self.txt` `a9c6d91911680aac3d4ae08db18982f1be58bbd963bc662b963b057505c38a64`;
`heaptrack-report.txt` `5a7fc33ba9735de1094955989fe7865539e1d30eb1d0dca9edd6e8a08f6f8d64`.
The single-hit lane is **projection-bound, not scan-bound**: 87.83 % of samples
are in hit projection, 59 % in stored-doc decoding, and 22–24 % in
`Rc<Vec<StoredRecord>>`/`GuardedSegmentReader` drop glue (visible in the call
tree) — i.e. materialising one hit is the dominant cost of this query.

### 3.3 `medium` (`group:medium`, 12 500 hits) — perf 94 000 samples, heaptrack 28 397 521 allocations

| Kind | Value | Category | Path (demangled) |
|---|---:|---|---|
| self CPU | 83.41 % | `live_doc_and_stats` | `search::unified::evaluate_unified` |
| inclusive | 84.72 % | `live_doc_and_stats` | `execute::evaluate_lexical_with::<…>` |
| inclusive | 83.41 % | `live_doc_and_stats` | `search::unified::evaluate_unified` |
| inclusive | 83.23 % | `live_doc_and_stats` | `Option<&LeafData>::is_some_and::<evaluate_unified::{closure#0}>` |
| inclusive | 83.21 % | `postings_and_candidate_membership` | `slice::Iter<TermPostings>::any::<LeafData::matches::{closure}>` (83.11 % at `LeafData::matches::{closure#0}`) |

| Allocations | Category | Interpretation | Recorded innermost frame |
|---:|---|---|---|
| 27 291 874 | `allocator_or_runtime` | **UNRESOLVED** | `alloc::alloc::alloc` (stack truncated) |
| 13 500 000 | `projection_and_materialization` | MEASURED | `segment::value::decode_scalar_budgeted` |
| 2 700 000 | `projection_and_materialization` | MEASURED | `segment::stored::decode_stored` |

Raw: `perf-self.txt` `d1e6b4fcf3c78fd70fa8198cc2c667921f77d5a28b8d3bb87353637b5fe1ca5a`;
`heaptrack-report.txt` `4983d5a903683738f697f943ce3f13ed13f5fffb84595b94b12e5d75c578e8cf`.

### 3.4 `common` (`key:common`, 49 999 hits) — perf 201 000 samples (`SAMPLED_WITH_LOSS` 786), heaptrack 38 081 899 allocations

| Kind | Value | Category | Path (demangled) |
|---|---:|---|---|
| self CPU | 92.38 % | `live_doc_and_stats` | `search::unified::evaluate_unified` |
| inclusive | 93.73 % | `live_doc_and_stats` | `execute::evaluate_lexical_with::<…>` |
| inclusive | 92.39 % | `live_doc_and_stats` | `search::unified::evaluate_unified` |
| inclusive | 92.25 % | `live_doc_and_stats` | `Option<&LeafData>::is_some_and::<evaluate_unified::{closure#0}>` |
| inclusive | 92.23 % | `postings_and_candidate_membership` | `slice::Iter<TermPostings>::any::<LeafData::matches::{closure}>` (92.16 % at `LeafData::matches::{closure#0}`) |

| Allocations | Category | Interpretation | Recorded innermost frame |
|---:|---|---|---|
| 34 850 121 | `allocator_or_runtime` | **UNRESOLVED** | `alloc::alloc::alloc` (stack truncated; `BTreeMap<String, Value>` node insert frames) |
| 14 000 000 | `projection_and_materialization` | MEASURED | `segment::value::decode_scalar_budgeted` |
| 3 230 016 | `projection_and_materialization` | MEASURED | `contract::document::DocumentKey::clone` |

Raw: `perf-self.txt` `bc1cbb9c01032c18281536622d3b164ff9beff949694f0516871413daeae3aba`;
`heaptrack-report.txt` `69df9a2d0718f65d696fe4300df7a313d4860b60e7eae2f439074281a1d16181`.

## 4. Reference lanes

### 4.1 N=10 000 (K=100), one per class

| Lane | Top self | Top inclusive paths | Largest attributed allocation bucket |
|---|---|---|---|
| `absent` | `evaluate_lexical_with` closure 16.75 % | `evaluate_lexical_with` 58.63 %; `ColumnAccess::open` 22.00 % (chain 21.98 %) | `BTreeSet<u64>::from_iter` 21 302 467 |
| `rare` | `from_utf8` 9.95 % | `project_selected_hits` 86.43 %; `stored_doc` 58.29 % / `stored` 58.27 % | `decode_scalar_budgeted` 19 200 000; `decode_stored` 3 840 000; (`alloc::alloc` 35 033 137 UNRESOLVED) |
| `medium` | `evaluate_unified` 31.38 % | `project_selected_hits` 53.61 %; `stored_doc` 36.34 %; `TermPostings::any` 30.86 % | `decode_scalar_budgeted` 12 450 000; `decode_doc_keys` 2 490 000; (`alloc::alloc` 24 807 991 UNRESOLVED) |
| `common` | `evaluate_unified` 56.53 % | `evaluate_lexical_with` 62.94 %; `evaluate_unified` 56.53 %; `TermPostings::any` 56.14 % | `decode_scalar_budgeted` 8 550 000; `DocumentKey::clone` 1 932 883; (`alloc::alloc` 21 068 026 UNRESOLVED) |

The 10 K shape reproduces the 100 K shape: at small N the per-query live-set build
is cheaper, so projection and scan shares move, but the same three code paths
dominate. No scaling law is claimed from two sizes.

### 4.2 N=100 000, K=10 control (perf only)

| Lane | Self | Inclusive paths |
|---|---|---|
| `absent` | 18.65 % | `evaluate_lexical_with` 66.13 %; `ColumnAccess::open` 24.28 % (chain 24.28 %) |
| `rare` | 9.89 % | `project_selected_hits` 88.12 %; `stored_doc` 58.67 % / `stored` 58.66 % |
| `medium` | 84.04 % | `evaluate_lexical_with` 85.30 %; `evaluate_unified` 84.04 %; `TermPostings::any` 83.83 % |
| `common` | 93.22 % | `evaluate_lexical_with` 94.48 %; `evaluate_unified` 93.23 %; `TermPostings::any` 93.10 % |

K changes the returned top-K size but not the bottleneck: the cost tracks matched /
live documents, not the number of returned ids (medium 84.04 %/83.83 % at K=10 vs
83.41 %/83.21 % at K=100; common 93.22 %/93.10 % vs 92.38 %/92.23 %).

## 5. Ranked bottlenecks (MEASURED)

1. **`live_doc_and_stats` — per-query all-live-document loop.** `perf` exclusive
   share inside `evaluate_unified` / the `evaluate_lexical_with` closure is
   83.41 % (medium) and 92.38 % (common) of samples, and the loop frame is 58.63 %
   even for the zero-hit `absent` lane. The loop is `for doc_id in &live_set`
   (`execute.rs:1920`), which also builds `live_set: BTreeSet<u64>` per query
   (`execute.rs:1895`): **34 232 993 of 35 015 933 allocations** in the 100 K
   `absent` capture.
2. **`postings_and_candidate_membership` — per-document linear postings scan.**
   `LeafData::matches` performs `term.postings.iter().any(|(doc, _)| *doc == doc_id)`
   (`execute.rs:915-920`); the nested `TermPostings` `any` frame carries 83.21 %
   (medium) / 92.23 % (common) of samples (inside the loop above, not additive).
3. **`projection_and_materialization` — stored-field decoding per projected hit.**
   `project_selected_hits` is 87.83 % (100 K rare) / 86.43 % (10 K rare) of samples
   with `stored_doc` ≈ 59 %; allocation buckets at `decode_scalar_budgeted` are
   27.0 M (100 K rare) and 8.55–19.2 M on the other lanes, plus 3.23 M
   `DocumentKey::clone` on common. One hit costs ≈ 88 % of a rare query.
4. **`snapshot_and_reader` — per-query column-reader opening.** `ColumnAccess::open`
   → `SegmentReader::open_columns` → `ColumnReader::open` is 23.92 % (100 K absent,
   K=100) and 24.28 % (K=10) of samples.

**Measured but not dominant in this workload (for completeness, not ranked):**

| Category | Evidence | Reading |
|---|---|---|
| `bm25_scoring` | `search::score::compute_stats` self 1.48 % (100 K absent); `execute::score_segment` self 0.72 % (10 K common); absent from the 100 K medium/common reports | present, small |
| `sort_and_top_k` | `binary_heap<MixedEntry>` self 1.13 % (10 K common); inclusive `MixedEntry` frames 0.55–0.69 % (100 K common) | small |
| `adapter_protocol` | no `serde_json` frame appears in any `perf-self.txt` (below the 0.5 % cut or inlined into its caller) | not observed as a CPU cost |
| `allocator_or_runtime` (CPU) | top self std/allocator frame is `core::str::from_utf8` 9.55 % (100 K rare), inside hit projection | contributes to rank 3, not a separate bottleneck |

**Unknowns kept explicit.**
- The largest heaptrack bucket on 100 K `rare`/`medium`/`common` (49.7 M / 27.3 M /
  34.9 M) is `UNRESOLVED`: heaptrack's recorded stack is truncated before any
  Quervant frame (`alloc::alloc` / `BTreeMap` node internals), so responsibility is
  **not** assigned.
- `perf` reports `# Total Lost Samples: 786` for 100 K `common`; shares for that
  lane are `SAMPLED_WITH_LOSS`.
- `perf` self percentages for `absent`/`rare` are spread over many small symbols
  (top self 17.71 % / 9.55 %), so the ranking there rests on the inclusive call
  tree, not on one self symbol.
- Indirect/unknown address buckets (`0x…`) are present in the call trees; they are
  not attributed to code.

## 6. Provisional PR 15E-B direction (not authorized)

Ordered by measured support, cheapest-to-falsify first. None of these is approved,
implemented or promised, and each needs the separately reviewed PR 15E-B plan plus
the same 20-lane evidence for a before/after claim.

1. **Postings-driven candidate enumeration** replacing the `live_set` scan plus
   per-document linear postings membership. Support: rank 1 + 2. Missing proof:
   an implementation must be measured with the identical matrix and must not
   change `total_hits`/ordering; the current result says the scan dominates, not
   which substitution is cheapest.
2. **Reuse the effective-live-document set across queries of one committed
   generation** instead of rebuilding `BTreeSet<u64>` per query. Support: 34.2 M
   of 35.0 M allocations in the 100 K absent capture. Missing proof: allocation
   savings attributed to CPU (allocation time is not separately visible at 0.5 %
   granularity here), and correctness under delete/update generations.
3. **Project only the requested fields and avoid full stored-record
   materialisation per hit.** Support: rank 3 (87.83 % of samples, 27 M+ allocations
   on rare). Missing proof: whether the frozen lane's `Projection::Fields(["doc_id"])`
   already narrows decoding; the measured `decode_stored` cost suggests it does not.
4. **Cache or reuse column readers per snapshot** instead of opening them per query.
   Support: rank 4 (23.9 % on absent). Missing proof: memory/ownership contract and
   whether the open cost moves elsewhere.

If the scan work cannot be reduced without changing results, the honest outcome for
PR 15E-B is "no change with evidence", not a speedup claim.

## 7. Residual risks and limitations

- `perf` samples include adapter start-up, JSONL protocol and the 5 warmups; the
  shares are process-sample shares, not per-query stage timings.
- `perf` 6.8.12 runs on a 6.18 WSL2 kernel; symbolization is partial, Rust symbols
  are mangled, and `0x…` frames are unattributed.
- heaptrack counters are cumulative allocation traffic for the process; they are
  not bytes-allocated-per-site (the mandated report exposes call counts and peak
  consumption, not per-site cumulative bytes), not RSS, and not peak logical
  memory. No bytes figure is claimed.
- 786 lost samples in one lane; 0 elsewhere.
- The corpus is a fixed synthetic exact-term workload with `doc_id`-ascending
  membership and constant-score semantics; it is not BM25 ranking and does not
  represent mixed queries.
- Two sizes and one host; no statistical significance test is performed and no
  comparison with the uninstrumented PR 15D-B latencies is made.
- Nothing here covers RustFS-backed indexes, distributed fan-out, vector search or
  the production `Directory` variants other than `FsDirectory`.
