# PR 7 Amendment 04 workload specification `pr07_amendment04_v1`

**Status:** pre-optimization baseline for PR 7. No production behavior changes.

## Fixture

- Fixed seed `0xA404_2026_0000_0001`; document keys `d{index:08}`.
- Single `title` field, `FieldType::Text`, single-valued, indexed and stored, bound
  to the built-in `whitespace` analyzer.
- Eight whitespace tokens per document. Background vocabulary `w0000..w0511`,
  selected by SplitMix64 over `(seed, doc_index, token_slot)`.
- Special tokens occupy disjoint slots so expected counts are exact:
  - slot 0 = `mtoken` for `doc_index % 100 == 0` (medium);
  - slot 1 = `ctoken` for even `doc_index` (common);
  - slot 2 = `rare_sentinel_zzz` for `doc_index == 0` only;
  - slots 3..5 = `alpha beta gamma` for `doc_index % 250 == 0`;
  - slots 6..7 = `reptok reptok` for `doc_index % 125 == 0`.
- `absent_sentinel_zzz` is never indexed.

## Corpora

| ID | documents | segments | notes |
|---|---:|---:|---|
| small | 2,000 | 1 and 4 | mandatory |
| medium | 10,000 | 4 | mandatory |
| large | 100,000 | 4 | mandatory |
| extended | 1,000,000 | 4 | optional, explicitly labeled; not run by default |

Tombstones: 0% (insert-only PR 7). A 25% tombstone lane is **not measured** and is
NOT APPLICABLE until PR 9 adds mutation/tombstone support; the reader's live
bitmap is asserted all-true instead.

## Query IDs

`term-rare`, `term-medium`, `term-common`, `term-absent`, `and-common-medium`,
`or-common-rare`, `phrase-present`, `phrase-absent`, `phrase-repeated`,
`match-all`, `pure-negative`. Top-K `10` (and `100` for one common-term case).

## Correctness gate

Before any timing the fixture is validated against an independent in-memory oracle
(token lists; no production executor, postings codec or phrase verifier) for every
case's exact hit set, `total_hits`, and finite nonnegative scores. Boolean set
algebra, phrase adjacency, selectivity counts, top-K truncation/ranking and single-
vs four-segment equivalence are asserted by `tests/pr07_amendment04.rs`.

## Dataset fingerprint

SHA-256 over: seed, document count, segment count, segment boundaries, each
document key and token list, and the ordered query IDs. The digest is axis-
sensitive (seed, document count and segment partition change it) and stable across
fresh builds.

## Report schema `quervant-bench-v1`

`run_id`, `timestamp_utc`, `git_sha`, `dirty`, `toolchain`, `os_kernel`, `wsl2`,
`cpu_model`, `filesystem_type`, `fixture_version`, `seed`, `dataset_sha256`,
`workload_id`, `doc_count`, `segments`, `query_type`, `selectivity`, `actual_hits`,
`top_k`, `reader_lifecycle`, `cache_state`, `criterion_version`, `sample_count`,
`estimate_ns`, `ci_lower_ns`, `ci_upper_ns`, `correctness_passed`, `status`,
`profiler_status`, `notes`.

## Correction 01 — semantic metadata and qualification

- **Schema v2:** corrected reports use `quervant-bench-v2` with mandatory
  `hit_count_applicable`, nullable `actual_hits`/`selectivity_ratio`, per-row
  `workload_key`/`dataset_sha256`, and an `environment_qualification` object.
  Legacy `quervant-bench-v1` is accepted only via `validate-report.py
  --historical` as `historical_unqualified`.
- **Source of truth:** `pr07_report_metadata` (a benchmark-only example) emits
  `quervant-fixture-metadata-v1` from the independent fixture oracle. Search and
  phrase rows carry the oracle match count; `bm25`/`dictionary`/`postings` rows
  carry `actual_hits: null` and `hit_count_applicable: false` (authoritative
  `posting_doc_count`/`dictionary_doc_freq` are separate). `validate-report.py
  --fixture-metadata` cross-checks every row; missing/duplicate/extra rows fail.
- **Assembly:** `build-pr07-report.py` reads real Criterion
  `new/{estimates.json,sample.json}` (slope, falling back to median/mean when
  Criterion writes `null`) and writes atomically. It fails closed on missing,
  duplicate or unexpected workload keys.
- **Dictionary unit:** one timed iteration = one lookup
  (`Throughput::Elements(1)`, unit `lookups`). The present term sorts early while
  the absent term scans the whole dictionary; neither is a randomized workload.
- **Contention:** `check-pr07-contention.py` samples `/proc` (or synthetic
  snapshots for tests) and reports `clear`/`suspected`/`unknown` with sanitized
  counters. The runner fails closed on non-clear unless `--allow-contended`
  (diagnostic only). Qualification additionally requires `--idle-confirmed` and a
  clean tree, and is never claimed from a single run.
- **Qualified baseline:** `aggregate-pr07-baseline.py` produces a
  `quervant-bench-v2-qualified` aggregate only from ≥3 independently qualified
  trials (median/min/max across trials).
