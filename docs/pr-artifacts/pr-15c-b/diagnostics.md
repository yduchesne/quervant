# PR 15C-B untimed causal diagnostics

Status: **S5 evidence record.** All measurements in this file are *instrumented*
and **untimed**. They are never substituted for the uninstrumented Criterion
numbers in `comparison.md`, and none of them is a speedup claim.

Sources compared: before `42b19445dd79a90d8701b4306e305c6e4e44cd57`,
after `b4682d0fdebaa691b55bb29b32f3499781a8fc04`.

## 1. Per-snapshot reuse witnesses (test-only, deterministic)

Command: `cargo test -p quervant-core --lib index::snapshot::verified_state_cache::`
— **38 passed, 0 failed**.

Representative authoritative witnesses for the reuse contract (B-I07):

| Witness | Contract proved |
|---|---|
| `g3_01_repeated_reads_reuse_same_verified_state` | repeated acquisitions return the same published `Arc<VerifiedSegmentState>` |
| `g3_05_descriptor_verification_unchanged` | explicit descriptor verification is not bypassed |
| `g2_05_single_state_is_charged_once_under_a_large_cap` | metadata charge counted once, `Arc` clones not re-charged |
| `g2_10_reservation_releases_on_last_arc_after_snapshot_drop` | charge released on last owner even if a guard outlives the snapshot |
| `g2_11_cache_hits_keep_full_admission_charge` | a cache hit keeps its admission charge |
| `g4_01_racing_first_opens_verify_once` | racing first opens verify exactly once |
| `g4_09_no_lock_held_across_query` | no slot lock held across query work |
| `c15a01_t05_absent_remap_segment_is_cached_and_reused` | implicit-identity remap segments are cached and reused |

The `index::snapshot::tests::` module (13 tests) covers the active-reader byte
budget, guard-drop release and reserved/exhausted binding rejection. Its
test-only `verification_count` is used by the cache witness module to assert
"exactly one verification, no second verification".

**No global production cache-hit ratio is inferred from these unit tests.** They
are scenario-specific, deterministic witnesses. `verification_count` counts
*successful published verifications*; it is **not** a universal SHA-invocation
counter and is not reported as one.

## 2. Fallback witnesses (inherited, not modified)

All from the same 38-test run: `g2_01_zero_metadata_cap_uses_uncached_reader`,
`g2_02_exact_allowance_admits_and_one_byte_over_falls_back`,
`g2_04_repeated_failed_candidates_do_not_leak`,
`g2_06_to_09_nested_classes_are_accounted`,
`g2_12_over_limit_input_reports_authoritative_error`,
`g3_02`/`g3_03`/`g3_04`/`g3_04b` (envelope, section, metadata and JSON-path
corruption fail closed), `g3_06_same_ids_different_bytes_are_never_trusted`
(no key/digest-only caching), `g4_04_failed_validation_wakes_waiters`,
`g4_05_artificial_build_failure_recovers`, `g4_06_poisoned_slot_fails_closed`,
`g4_07_panic_during_build_restores_slot`, `g4_08_guard_outlives_snapshot`,
`g4_10_out_of_range_index_is_typed`, `g4_11_cache_hit_still_obeys_admission_budget`,
`c15a01_t06_absent_remap_falls_back_one_under_allowance`,
`c15a01_t09_absent_remap_corruption_still_fails_closed`.
`cargo test -p quervant-core --test pr15c_a_segment_state` adds 5 passing
end-to-end witnesses including a real-filesystem restart oracle.

## 3. CPU attribution (`perf`)

Command per side/workload:
`bash benchmarks/scripts/profile-pr15b.sh --mode perf --workload <absent|rare|mixed> --out <side>/target/pr15c-b/profiles/<wl>-perf`

`perf` availability: `/usr/bin/perf` is the distro wrapper and **fails on this
WSL kernel** (`WARNING: perf not found for kernel 6.18.33.2-microsoft`, exit 2).
The version-mismatched but working binary already installed for the PR 15B
profiling follow-up (`/usr/lib/linux-tools/6.8.0-147-generic/perf`, `perf version
6.8.12`) was placed on `PATH` via a symlink directory. Nothing was installed,
`sudo` was not used, `perf_event_paranoid` (2) and kernel settings were not
changed. **Caveat retained from PR 15B: the user-space binary version does not
match the running kernel.**

Driver: `target/release/examples/pr15b_profile --workload <wl> --seconds 20`,
untimed oracle first, then a bounded production-entrypoint loop.

### 3.1 Before — whole-segment re-verification dominates

Child (inclusive) percentages from `perf report --stdio` on the *before* records:

| workload | `ReaderSnapshot::open_segment_reader` | `SegmentReader::open` | `parse_container` | `sha2::soft::unroll::compress` (self) |
|---|---:|---:|---:|---:|
| `absent` | 96.37 % | 95.28 % | 81.91 % | **82.65 %** |
| `rare` | 69.66 % | 68.84 % | 59.24 % | 14.76 % |
| `mixed` | 60.18 % | 59.49 % | 51.09 % | (below report cut) |

Dominant call chain in the before `absent` profile:

```text
UnifiedSearcher::search 98.44%
  UnifiedSearcher::collect_mixed 98.19%
    ReaderSnapshot::open_segment_reader 96.37%
      SegmentReader::open 95.28%
        format::parse_container 81.91%
          sha2::soft::unroll::compress  (82.65 % of self time)
```

### 3.2 After — the re-verification path is gone

Flat self-time leaders in the after `absent` record:

| symbol | self % | interpretation |
|---|---:|---|
| `segment::column::read_u64_at` | 13.34 % | residual per-query column reads |
| `execute::evaluate_lexical_with` | 13.02 % | residual query evaluation |
| `segment::column::ColumnReader::open_with_doc_count` | 12.61 % | residual per-query column open |
| `search::unified::evaluate_unified` | 9.90 % | residual query evaluation |
| `alloc::collections::btree::map::…dying_next` | 7.42 % | live-doc `BTreeSet` teardown |
| `sha2::soft::unroll::compress` | 4.79 % | **see §3.3 — not segment verification** |

`open_segment_reader`, `SegmentReader::open` and `parse_container` **do not appear
at all** in the after profile reports for `absent`, `rare` or `mixed`
— they fall below the report cut-off — versus 60–96 % inclusive before.

### 3.3 The residual SHA-256 is analyzer fingerprinting, not verification

In the after profile the remaining `sha2` samples sit under

```text
search::unified_plan::compile
  analysis::registry::AnalyzerDefinition::fingerprint
    digest::Digest<Sha256>::digest
      sha2::soft::unroll::compress
```

and the same subtree under `analysis::registry::SchemaAnalyzerBindings::resolve`.
That is per-request analyzer-definition fingerprint hashing, **not** whole-segment
verification. It is recorded as a residual observation and a candidate for a
future PR (see `acceptance.md`); **nothing was optimized in this PR**.

Instrumented loop iterations observed in the same 20 s (perf runs, before →
after): `absent` 817 → 41 673, `rare` 592 → 5 208, `mixed` 515 → 2 169. These are
instrumented iteration counts, **not** Criterion latency and **not** QPS claims.

## 4. Allocation traffic and retained memory (`heaptrack`)

Command per side/workload:
`bash benchmarks/scripts/profile-pr15b.sh --mode heaptrack --workload <absent|rare|mixed> --out <side>/target/pr15c-b/profiles/<wl>-heaptrack`
then `heaptrack --analyze <…>/heaptrack.gz`.

Because the profile driver runs a fixed 20-second loop, the after build completes
far more iterations, so **absolute** totals are not comparable. The table below
therefore divides by the iteration count printed by the driver.

| side | workload | iterations | allocation calls | calls / query | temporary allocations | temporaries / query | peak heap | peak RSS |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| before | `absent` | 435 | 23 492 720 | 54 006 | 10 974 721 | 25 229 | 16.03 M | 29.82 M |
| after | `absent` | 19 309 | 25 444 994 | **1 318** | 2 344 813 | **121** | 15.88 M | 30.04 M |
| before | `rare` | 275 | 25 756 606 | 93 660 | 8 786 620 | 31 951 | 16.03 M | 29.88 M |
| after | `rare` | 1 260 | 34 827 052 | **27 641** | 662 476 | **526** | 15.88 M | 30.09 M |
| before | `mixed` | 224 | 27 419 891 | 122 410 | 10 180 245 | 45 448 | 16.03 M | 29.82 M |
| after | `mixed` | 630 | 35 035 254 | **55 612** | 8 654 087 | **13 737** | 15.88 M | 29.83 M |

Per-query change (descriptive, instrumented, scenario-specific):

| workload | allocation calls / query | temporary allocations / query |
|---|---|---|
| `absent` | −97.6 % | −99.5 % |
| `rare` | −70.5 % | −98.4 % |
| `mixed` | −54.6 % | −69.8 % |

**Retained memory does not grow.** Peak heap is 16.03 M before and 15.88 M after
for every workload; the pre-existing 544 B leak is unchanged and is not on the
search path. This is consistent with the VSR-G2 accounting contract (charge
release on last owner) and with the 38 cache/fallback witnesses, but it is a
**measured process snapshot**, not a proof of an allocator-independent RSS bound.

`heaptrack --analyze` reports cumulative allocation traffic, not retained memory.
The per-query normalisation above is the only defensible use of the counts; the
raw totals are preserved in the ignored `target/` trees.

## 5. What was not measured

| Metric | Status | Reason |
|---|---|---|
| Production cache-hit ratio (engine-wide) | **NOT MEASURED** | would require production instrumentation, forbidden in this PR |
| Separate SHA-256 / decode invocation counts per query | **NOT MEASURED** | `verification_count` counts published verifications only; adding universal counters would instrument production code (plan §S5.3 forbids it) |
| Allocations for `json`, `sort`, `aggregation`, `batch` profiling lanes | **NOT MEASURED** | outside the prioritised `absent`/`rare`/`mixed` set |
| Flamegraph SVGs | **NOT RUN** | `perf` flat/self attribution plus heaptrack already answer the SHA-reuse question; recorded as unnecessary rather than failed |
| RustFS throughput / cold-bootstrap cost | **NOT MEASURED** | PR 15C-A only optimises post-load reader-state reuse; no remote claim is made |
| Peak RSS under a fixed query count | **NOT MEASURED** | would need a different driver contract (fixed iterations vs fixed seconds) |
| A cold-snapshot (first-acquisition) cost lane | **NOT MEASURED** | no existing timed lane controls cold acquisition; warm Criterion lanes must not be described as cold verification cost |

## 6. Preservation and provenance

| Artifact | Location |
|---|---|
| Criterion raw data (6 trials) | `<worktree>/target/pr15b/<stamp>-<sha>/trial-N/criterion/` |
| Trial manifests + `env.txt` + contention snapshots | `<worktree>/target/pr15b/<stamp>-<sha>/trial-N/` |
| Compact copies of the six trial manifests, `env.txt` and pre-trial contention snapshots | `docs/pr-artifacts/pr-15c-b/trials/` (trailing whitespace normalised for the CI whitespace gate; no value changed) |
| perf records and reports (6 × ~700 MB) | `<worktree>/target/pr15c-b/profiles/<wl>-perf/` (**untracked**) |
| heaptrack records (6) | `<worktree>/target/pr15c-b/profiles/<wl>-heaptrack/` (**untracked**) |

No large profiler binary is committed. Nothing under `benchmarks/reports/` was
overwritten.
