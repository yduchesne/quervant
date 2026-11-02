# PR 15E Phase 6 — focused CPU profiling qualification

**Status: `P6_PROFILED_FOCUSED_ACCEPTANCE_READY` — disposition `LIKELY, INCLUSIVE_ONLY`
(`G05_STORED_PROJECTION`). No implementation is authorized.**

Four 100K/K100 `perf` captures were collected from the exact Phase 5 evidence anchor, fully
verified by the unchanged PR 15E-A per-capture checks, with zero oracle errors, zero lost
samples and clear contention before and after each run. The original 20-capture campaign
remains `PARTIAL` (4/20) and is **not** claimed as complete.

## 1. Identity and validity

| Item | Value |
|---|---|
| Measured source | `e448469d6c98d9ef4b4a827ad9567363a888a185` (working tree checked out at exactly this commit during capture) |
| Tool | driver-selected installed versioned fallback, `perf version 6.8.12` (`fallback=true`) |
| Corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` (frozen 100K lane) |
| Contention | `clear` before **and** after all four captures (8/8) |
| Oracle | every profiled reply equal to the independent frozen oracle; zero errors |
| Original verifier | exit `3`, `status=PARTIAL`, `head_matches_measured=true`, `prepare_violations=[]`, counts `{required:20, passed:4, blocked:16, missing:16, failed:0}` |
| Focused gate | `P6_FOCUSED_4_OF_4_VERIFIED` |

| Capture | Samples | Lost | Queries in window |
|---|---:|---:|---:|
| `rare/k100` (primary) | 121,000 | 0 | 1,183 |
| `absent/k100` | 117,000 | 0 | 21,681 |
| `medium/k100` | 122,000 | 0 | 684 |
| `common/k100` | 242,000 | 0 | 782 |

## 2. Primary lane (`rare`, 121,000 samples) — exclusive frames

| Frame | Self % | ≈ samples |
|---|---:|---:|
| `core::str::from_utf8` | 20.88 | 25,265 |
| `core::ptr::drop_glue` (monomorphized) | 11.41 | 13,806 |
| `segment::value::skip_scalar_budgeted` | 10.58 | 12,802 |
| `core::ptr::drop_glue` (second instance) | 7.74 | 9,365 |
| `segment::stored::decode_stored_selected` | 7.74 | 9,365 |
| `segment::value::skip_field_values_budgeted` | 7.24 | 8,760 |
| `segment::format::ByteReader::u32` | 6.32 | 7,647 |
| `segment::DecodeBudget::reserve_string` | 6.32 | 7,647 |

Caller attribution inside the `from_utf8` self share: 16.75 pp flows through
`run_utf8_validation`, of which **10.79 pp** arrives via `skip_scalar_budgeted` (STORED skip)
and **3.87 pp** via `decode_doc_key_selected` (document keys, split 1.95 projection / 1.93
collection); a further **2.08 pp** arrives directly from `decode_stored_selected`. A second
`from_utf8` instance contributes 4.04 pp (3.06 stored skip, 0.65 document keys). These are
caller splits of one exclusive figure and are not added together with it.

## 3. Inclusive chains (perf call tree, nested and never summed)

| Group | Rare | Absent | Medium | Common |
|---|---:|---:|---:|---:|
| `G05_STORED_PROJECTION` (`stored_docs_selected` → `decode_stored_selected`) | **82.39 %** | not observed | 47.84 % | 27.98 % |
| `G06_QUERY_SCORING` (`evaluate_lexical_with`, `build_leaf_data`, postings, `score_segment`) | 0.99 % | 19.78 % | 9.80 % | 23.07 % |
| `G04_KEYS` (`doc_key_selected` / legacy `decode_doc_keys`) | 9.47 % | not observed | 14.68 % (legacy full decode) | 8.55 % (legacy full decode) |
| `G03_COLUMNS` (`ColumnAccess::open` → `ColumnReader::open`) | 3.01 % | **60.00 %** | 2.84 % | 6.99 % |
| `G02_STATS` (`compute_stats`) | < 0.5 % | 4.01 % | < 0.5 % | < 0.5 % |
| `G01_STAGING` (`open_segment_reader`) | 0.60 % | 0.70 % | 0.60 % | < 0.5 % |

Primary-lane chain: `execute_unified` → `project_selected_hits` → `stored_docs_selected` →
`decode_stored_selected` → `skip_field_values_budgeted` → `skip_scalar_budgeted`.

## 4. Control lanes (exclusive highlights)

* **absent** (117,000 samples): `column::read_u64_at` 24.28 %, `ColumnReader::open_with_doc_count`
  19.35 %, `SegmentReader::live_docs` 10.33 %, `effective_live_examination_count` 9.70 %,
  `compute_stats` below 4 %. Column setup dominates a query that returns no hits.
* **medium** (122,000): `from_utf8` 12.25 %, `skip_scalar_budgeted` 6.26 %,
  `DecodeBudget::reserve_string` 4.58 %, `skip_field_values_budgeted` 4.21 %,
  `decode_stored_selected` 4.20 %; legacy `decode_doc_keys` appears at 14.68 % inclusive
  because 12,500 hits keep the full-key path.
* **common** (242,000): `from_utf8` 7.76 %, `MixedEntry` iterator 4.71 %, `score_segment`
  3.16 %, `evaluate_unified` 3.05 %; `build_leaf_data` 10.11 % and postings decoding 7.82 %
  inclusive, `sort_tuple_for_doc` 10.23 % — scoring and ranking become comparable to storage.

## 5. Disposition (preapproved §10 algorithm)

1. **Strong candidate: no.** The largest named Quervant *exclusive* frame is
   `skip_scalar_budgeted` at 10.58 %, below the 20.0 % threshold and without a 5.0 pp lead.
2. **Likely candidate: yes — `G05_STORED_PROJECTION`, `LIKELY, INCLUSIVE_ONLY`.** One
   unambiguous named inclusive chain reaches **82.39 %** on the primary lane with a clear
   owned child path, and no competing disjoint chain reaches 35.0 % (next: 9.47 %).
3. **Recommendation:** confirm with narrower profiling before implementation. The candidate
   area is the remaining **full-section skip/validation** cost of the selective STORED path
   (`decode_stored_selected` validates all records to project one). This is a scope proposal
   only: `implementation_authorized: false`, and a Phase 7 plan requires maintainer approval.
4. **Overturned hypothesis:** the earlier `compute_stats` suggestion is not supported (≤ 4.01 %
   inclusive anywhere, < 0.5 % on the primary lane).
5. **Conditional allocation probe: not triggered.** The D22 condition requires ≥ 20 %
   exclusive allocator/runtime CPU with **no attributable caller**; the leading runtime frame
   (`from_utf8`, 20.88 % self) has specific attributable Quervant callers, so no heaptrack
   capture was run.

## 6. Unresolved alternatives

* The **absent** lane is dominated by `G03_COLUMNS` (60.00 % inclusive) — a larger relative
  cost for zero-hit queries than anything in the primary lane's runner-up groups. The
  rare-primary rule does not select it, but it is the strongest unselected signal and a
  candidate for a future investigation.
* The **common** lane blends storage (27.98 %) and scoring (23.07 %); no single chain clears
  the thresholds there.
* `drop_glue` self shares (11.41 % + 7.74 %) are generic destruction frames; their call chains
  resolve into the same stored/key decoding paths, but they are reported as runtime frames and
  were not assigned a subsystem share of their own.

## 7. Limits

Process-wide CPU samples include startup, the five warmups and JSONL transport; they are not
per-query stage durations and cannot be converted into microseconds, speedups or savings.
One host, one session, synthetic frozen exact-term corpus. No allocation totals (no heaptrack),
no cross-host, remote-latency or concurrent-writer evidence. Symbolization succeeded for the
cited frames (0 lost samples); unresolved addresses are excluded rather than distributed.
