# PR 15I-0 — performance and CPU attribution

**Measured source:** `48e7d3a0771f9ccd1cc0bf1d07eadac4b2b5f39f`
**Campaigns (private, sealed under `target/`):** PR 15D `pr15d-current-01`;
PR 15F `pr15i0-run-48e7d3a0-04` with prepared index
`pr15i0-prepared-48e7d3a0-01`.
**Derived data:** `benchmarks/reports/pr15i-0/pr15i-0-summary.json`.

Every number here comes from the current qualified campaign. Historical PR 15D/
15E/15F numbers appear only in the explicitly labelled historical section and are
never mixed into a current ratio.

## 1. Three-engine baseline (same host, same corpus, three trials per engine)

Corpus manifest SHA-256 `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`
(identical between the PR 15D and PR 15F campaigns). Filesystem `ext4`, native.
All 54 contention probes reported `clear`; the PR 15D validator returned
`QUALIFIED` with zero errors; every lane matched the independent PR 15D oracle.

The lane is **exact keyword match + exact `total_hits` + explicit ascending
`doc_id` sort**. It is **not** a BM25 relevance comparison and no score
comparability is claimed anywhere.

### Index size (median of three trials, integer bytes)

| Documents | Quervant | Tantivy | Lucene | Q/Tantivy | Q/Lucene |
|---:|---:|---:|---:|---:|---:|
| 10,000 | 3,090,037 | 296,787 | 186,052 | 10.412 | 16.608 |
| 100,000 | 30,965,025 | 2,901,172 | 1,858,642 | 10.673 | 16.660 |

**Comparability caveat:** these compare whole committed index bytes. The segment
and schema layouts are physically different; no equivalence of physical
structures is implied.

### Ingest / commit / reopen (medians, ns)

| Documents | Engine | Ingest | Commit | Reopen | Segments |
|---:|---|---:|---:|---:|---:|
| 10,000 | quervant | 20,379,222 | 169,069,933 | 41,745,650 | 1 |
| 10,000 | tantivy | 689,810 | 108,352,322 | 423,206 | 4 |
| 10,000 | lucene | 139,763,442 | 130,500,499 | 30,503,567 | 1 |
| 100,000 | quervant | 219,390,954 | 1,630,187,839 | 418,244,572 | 1 |
| 100,000 | tantivy | 1,405,095,056 | 64,999,030 | 466,008 | 4 |
| 100,000 | lucene | 459,518,626 | 304,838,259 | 26,862,690 | 1 |

Reopen ratio Quervant/Tantivy: **98.641×** at 10K and **897.505×** at 100K.
Quervant's reopen cost dominates its whole index-open path (see §4).

### Warm query medians (ns)

| Documents | Class | K | Quervant | Tantivy | Lucene | Q/T |
|---:|---|---:|---:|---:|---:|---:|
| 10,000 | absent | 10 | 43,701 | 10,700 | 352,906 | 4.084 |
| 10,000 | absent | 100 | 43,400 | 11,100 | 299,105 | 3.910 |
| 10,000 | rare | 10 | 45,201 | 13,001 | 675,111 | 3.477 |
| 10,000 | rare | 100 | 48,900 | 13,801 | 675,411 | 3.543 |
| 10,000 | medium | 10 | 1,609,025 | 38,000 | 1,370,921 | 42.343 |
| 10,000 | medium | 100 | 1,958,830 | 90,802 | 4,482,970 | 21.573 |
| 10,000 | common | 10 | 3,401,354 | 75,301 | 1,491,923 | 45.170 |
| 10,000 | common | 100 | 4,545,572 | 133,102 | 3,002,847 | 34.151 |
| 100,000 | absent | 10 | 251,604 | 15,300 | 329,705 | 16.445 |
| 100,000 | absent | 100 | 251,305 | 15,500 | 329,405 | 16.213 |
| 100,000 | rare | 10 | 251,604 | 17,900 | 663,311 | 14.056 |
| 100,000 | rare | 100 | 254,804 | 18,600 | 665,310 | 13.699 |
| 100,000 | medium | 10 | 16,214,770 | 167,002 | 1,257,919 | 97.093 |
| 100,000 | medium | 100 | 19,021,490 | 239,504 | 4,891,975 | 79.420 |
| 100,000 | common | 10 | 35,689,628 | 647,911 | 1,579,425 | 55.084 |
| 100,000 | common | 100 | 47,918,853 | 662,910 | 3,043,451 | 72.286 |

**Physical sort disclosure.** Quervant sorts on a `Keyword` column, Tantivy on a
numeric ordinal and Lucene on `SortedDocValues`. The ordering is logically
equivalent; the physical representation is not. No low-level operator parity is
claimed, and every ratio above must be read with that caveat.

Process-cold medians (fresh adapter process per sample — **not** OS-cache-cold)
are in [`measurements.md`](measurements.md); all 16 process-cold lanes are
reported there, none dropped, and their cross-engine ratios are deliberately
`NOT_COMPARABLE` because a process-cold lane measures process start-up.

## 2. Quervant CPU attribution (nine warm lanes, `perf`, `--call-graph dwarf`)

Perf resolved through PR 15F's documented `versioned` fallback
(`perf version 6.8.12`) because the WSL2 `perf` wrapper exits 2 for this kernel.
All nine lanes captured with **zero lost samples**, 76,000–242,000 samples per
lane, five warmups and `clear` contention before and after.

Exclusive shares partition to 100 % **including** the `G08` unclassified bucket;
inclusive shares overlap by construction and are never summed.

| Lane | Samples | Unknown (G08) excl. % | G01 staging | G02 planning/stats | G03 columns | G04 key decode | G05 STORED proj. | G06A postings | G06B BM25 | G06C sort/heap | Rank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10K absent K100 | 76,000 | 53.91 | 23.99 | 22.10 | 0 | 0 | 0 | 0 | 0 | 0 | `UNRESOLVED` |
| 10K rare K100 | 76,000 | 59.92 | 21.75 | 18.33 | 0 | 0 | 0 | 0 | 0 | 0 | `UNRESOLVED` |
| 10K medium K100 | 77,000 | 88.56 | 0.65 | 0.57 | 1.40 | 0 | 0 | 5.96 | 2.86 | 0 | `UNRESOLVED` |
| 10K common K100 | 78,000 | 80.16 | 0 | 0.72 | 3.14 | 0 | 0 | 10.83 | 5.15 | 0 | `LIKELY_INCLUSIVE_CANDIDATE` (G06A, inclusive 37.47) |
| 100K absent K100 | 118,000 | 14.55 | 49.16 | 36.29 | 0 | 0 | 0 | 0 | 0 | 0 | `LIKELY_INCLUSIVE_CANDIDATE` (G01, inclusive 49.50) |
| 100K rare K100 | 118,000 | 16.91 | 47.94 | 35.15 | 0 | 0 | 0 | 0 | 0 | 0 | `LIKELY_INCLUSIVE_CANDIDATE` (G01, inclusive 48.26) |
| 100K medium K100 | 121,000 | 88.02 | 0.65 | 0 | 1.83 | 0 | 0 | 6.18 | 3.32 | 0 | `UNRESOLVED` |
| 100K common K100 | 242,000 | 79.66 | 0 | 0.67 | 3.16 | 0 | 0 | 10.91 | 5.60 | 0 | `LIKELY_INCLUSIVE_CANDIDATE` (G06A, inclusive 37.44) |
| 100K common K10 | 241,000 | 79.84 | 0 | 0.81 | 4.18 | 0.60 | 0 | 5.74 | 7.33 | 1.50 | `UNRESOLVED` |

Reading rules (frozen by PR 15F, not reinterpreted here):

- `STRONG_EXCLUSIVE_CANDIDATE` needs ≥ 20 % top exclusive, ≥ 5 pp lead and
  unknown ≤ 10 %. **No lane met it.**
- `LIKELY_INCLUSIVE_CANDIDATE` is *inclusive-only* and is **not** an estimated
  improvement.
- The unclassified exclusive share is 14.55 %–88.56 % per lane. Shared digest and
  demangled-symbol frames that cannot be uniquely owned stay in the unknown
  bucket; they are never spread across named stages.

**Consequence:** this attribution does **not** by itself justify any specific
execution rewrite. Stage-level measurement is required by 15I-C before coding.

## 3. Optional allocation capture

`heaptrack 1.5.0` captured both prescribed lanes
(`100K/rare/K100`, `100K/common/K100`). This is a supplementary capture, never a
substitute for the CPU matrix, and no allocation-reduction claim is made.

## 4. Reopen: timing and attribution

Fresh-process single-shot probe (`FsDirectory::open` → `Index::open_with_limits`
→ `Index::snapshot`), 21 independent processes per corpus size (42 total),
`clear` contention in every block:

| Documents | Samples | Reopen total median ns | Reopen core median ns |
|---:|---:|---:|---:|
| 10,000 | 21 | 42,791,382 | 42,778,582 |
| 100,000 | 21 | 427,513,918 | 427,473,118 |

`reopen_total − reopen_core` is ≈ 1.3 µs–41 µs, i.e. the cost is inside
`Index::open_with_limits`, not in directory opening or snapshot acquisition.

The CPU-sampled reopen loop (128 iterations at 10K, 64 at 100K) reported
**zero lost samples** at both sizes and `perf_origin = versioned`.

Reopen frame attribution (inclusive, % of samples):

| Frames | 10K inclusive | 100K inclusive | Exclusive |
|---|---:|---:|---|
| `R01` directory open | 0.00 | 0.00 | 0.00 |
| `R02` CURRENT/manifest/descriptor verification | 0.00 | 0.00 | 0.00 |
| `R03` immutable segment read + digest | 40.55 | 40.39 | 0.00 |
| `R04` segment container parse + metadata | 43.63 | 43.41 | 0.00 |
| `R05` mutation-state decode | 21.13 | 21.03 | 0.00 |
| `R06` revision visibility masks | 1.43 | 3.71 | 0.00 |
| `R07` snapshot creation | 0.00 | 0.00 | 0.00 |
| `R08` runtime/allocator/unknown | 99.92 | 99.95 | **100.00** |

Inclusive values sum to well over 100 % because they overlap. The **exclusive**
partition is 100 % `R08`: shared digest/allocator frames cannot be uniquely
owned, so no stage can be credited with a removable share. `R03`/`R04`/`R05`
remain *inclusive* possibilities only.

A fresh process is **not** an OS-cache-cold measurement. Nothing here measures a
cold page cache.

## 5. Hypothesis registry (non-causal)

| ID | Hypothesis | Status | Supporting evidence | What a future experiment must prove |
|---|---|---|---|---|
| `H-A` | Repeated full segment IDs and mutation-state decode cost dominate sidecar bytes and reopen | **MEASURED** (bytes) / **INDIRECT_SUPPORT** (CPU) | sidecar probe: `live_pointer_id_bytes` = 6,600,000 of 9,600,180 B (68.75 %) at 100K; reopen `R05` inclusive 21.03 % | A V3 candidate's real reopen median, plus cold-bootstrap and memory gates |
| `H-B` | Selected STORED validation/access dominates selective retrieval | **INDIRECT_SUPPORT** | `Stored` = 9,662,513 B (31.20 % of index); `G05` inclusive reaches 3.0 % at 10K medium but 0 % exclusive everywhere | A block-compressed candidate's selected-document retrieval time and corruption-observability proof |
| `H-C` | Candidate enumeration, scoring, sort tuple and projection overhead dominate `common` lanes | **INDIRECT_SUPPORT** | `G06A` inclusive 37.47 % (10K common) and 37.44 % (100K common); exclusive 10.83 %/10.91 %; unknown 80.16 %/79.66 % | Stage-level instrumented enumeration/scoring/sort timings with exact score-bit parity |
| `H-D` | FST/postings/typed sort physical representation drives the warm gap to Tantivy | **UNRESOLVED** | Q/T warm ratios 13.7×–97.1×; physical sort encodings differ; G06A/G06B exclusive are single-digit | A format-preserving execution experiment, then a separately approved postings-format proposal |

No proportional extrapolation from an inclusive percentage to milliseconds is
permitted. Stage-level latency is `NOT_MEASURED` in PR 15I-0 because no production
timing hook was added.

## 6. Historical context (isolated)

PR 15F's historical P0 campaign reported a 100K sidecar of 9,600,180 B and a
100K committed index of 30,965,025 B on measured source `447ac648…`. Those values
match today's measured baseline because the 15H-E dictionary experiment was
rolled back byte-for-byte. Historical **latency** ratios from other sessions are
**not** today's verdict and are deliberately excluded from every ratio above.

## 7. Evidence quality notes

- Three PR 15F `query-perf` campaigns were rejected before this one:
  `…-01` (24 and 156 lost samples), `…-02` (10 and 490) and `…-03` (490).
  The root cause is a single lost perf ring chunk during the ~1.9 GB write-out of
  the 60-second 100K lanes on this WSL2 host; `perf` reported
  `lost 1 chunks` and the harness classified `X19_PERF_LOST_SAMPLES`. Those
  campaigns are preserved unchanged and are **not** used for any number here.
  Campaign `…-04` captured all nine lanes with zero lost samples and is the only
  one sealed `QUALIFIED` and verified.
