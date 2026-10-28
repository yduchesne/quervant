# PR 15B CPU and allocation profiling evidence

## Status

| Stage | Status |
|---|---|
| Original PR 15B attempt | **UNAVAILABLE** (tools not installed) |
| PR 15B profiling amendment | **MEASURED** CPU and allocation evidence collected |
| Executable source measured | `e8ca1b03420e1ffe8cb19fafac06b2fe8082866b` |
| Profiling session base | `5668d6ef285fdff72b01072327f46a449ed104f2` (adds only `install.sh`) |
| Raw artifacts | ignored `target/pr15b/profiles/` |

The original unavailability findings are preserved below. They are superseded
only for the tools that now produce usable data; no unavailable measurement is
represented as successful.

## Original attempt (preserved)

**Original result: CPU/ALLOCATION ATTRIBUTION UNAVAILABLE.** No profiler was
installed on the qualification host. The wrapper was executed for every approved
mode and returned an explicit nonzero `UNAVAILABLE` status. No sudo, package
installation, sysctl change, kernel change or alternative sampling agent was
used.

| Mode | Original command | Exit | Original output |
|---|---|---:|---|
| perf | `bash benchmarks/scripts/profile-pr15b.sh --mode perf --workload absent --out target/pr15b-profile-perf` | 2 | `UNAVAILABLE: perf is not installed.` |
| flamegraph | `bash benchmarks/scripts/profile-pr15b.sh --mode flamegraph --workload absent --out target/pr15b-profile-flamegraph` | 2 | `UNAVAILABLE: cargo-flamegraph is not installed.` |
| heaptrack | `bash benchmarks/scripts/profile-pr15b.sh --mode heaptrack --workload absent --out target/pr15b-profile-heaptrack` | 2 | `UNAVAILABLE: heaptrack is not installed.` |

The release driver was executed separately for every accepted workload and
verified the oracle/iteration wiring; those runs are not profiling results.

## Amendment environment

| Item | Value |
|---|---|
| OS / kernel | Linux `6.18.33.2-microsoft-standard-WSL2` |
| CPU | Intel Core i7-10750H @ 2.60 GHz, 12 logical CPUs |
| Memory | 32,774,780 kB |
| Filesystem | `ext4` |
| Rust | `rustc 1.98.1` / `cargo 1.98.1` |
| `perf` (working binary) | `perf version 6.8.12` |
| `cargo-flamegraph` | `flamegraph-flamegraph 0.6.14` |
| `heaptrack` | `1.5.0` |
| `heaptrack_print` | available |

### `perf` wrapper condition and exact handling

The distro wrapper `/usr/bin/perf` is installed but cannot find tools for the
running WSL kernel:

```text
$ perf --version
WARNING: perf not found for kernel 6.18.33.2-microsoft
...
$ echo $?
2
```

The installed version-specific binary is usable:

```text
$ /usr/lib/linux-tools/6.8.0-147-generic/perf --version
perf version 6.8.12
```

A smoke test with that binary collected real samples:

```text
$ /usr/lib/linux-tools/6.8.0-147-generic/perf record -g \
    -o /tmp/quervant-pr15b-perf-smoke.data -- sleep 2
[ perf record: Captured and wrote 0.002 MB ... (5 samples) ]
$ /usr/lib/linux-tools/6.8.0-147-generic/perf report --stdio \
    -i /tmp/quervant-pr15b-perf-smoke.data
# Samples: 5  of event 'cycles:Pu'
```

The approved profiling script was then run with a PATH shim:

```text
target/pr15b/perf-bin/perf -> /usr/lib/linux-tools/6.8.0-147-generic/perf
PATH="$PWD/target/pr15b/perf-bin:$PATH" bash benchmarks/scripts/profile-pr15b.sh ...
```

No kernel setting, kernel module, WSL configuration, privilege escalation or
package installation was performed. **Caveat:** the working perf binary (6.8.12)
does not match the running 6.18 WSL kernel. The samples are usable, but this
version mismatch is a reproducibility limitation and is recorded in the dossier.

### Flamegraph script correction (P4-X11)

The existing flamegraph mode had two unambiguous, semantics-preserving defects:
it did not export `CARGO_PROFILE_RELEASE_DEBUG=1` to the `cargo flamegraph`
subprocess (producing "profiling without debuginfo"), and it ran in the repository
root, leaving a multi-hundred-MB `perf.data` there.

Both were corrected without changing workload semantics, search execution or
APIs: the flamegraph command now runs in a private `$OUT/.flamegraph-work`
directory with an absolute SVG output path and
`CARGO_PROFILE_RELEASE_DEBUG=1`. The work directory (including `perf.data`) is
removed after capture. The corrected script was used for every retained
flamegraph artifact. This is documented under P4-X11 in `decisions.md`.

## Workload coverage

The approved profiling driver supports the workload identifiers `absent`, `rare`,
`mixed`, `json`, `sort`, `aggregation`, `batch`, and always builds the 10K/4
corpus. It has no 100K workload and no `medium`/`common` lexical identifier.

| Priority behavior | Approved ID | Status |
|---|---|---|
| Absent lexical term | `absent` | **PROFILED** |
| Rare typed predicate | `rare` | **PROFILED** |
| Common lexical query (U03 gamma, 100K) | none | **NOT PROFILED — NO APPROVED ENTRYPOINT** |
| Mixed lexical/typed | `mixed` | **PROFILED** |
| Top-K sorting | `sort` (K=100) | **PROFILED** (K=1000 is not a separate approved ID) |
| Aggregation | `aggregation` | **PROFILED** |
| JSON scalar | `json` | NOT PROFILED — not in the priority table |
| Serial batch | `batch` | NOT PROFILED — not in the priority table |

All profiled workloads use **10K documents / 4 segments**. The 100K Criterion
lanes were not profiled because no approved profiling entrypoint accepts a
100K corpus or a Criterion lane. This does not change the original Criterion
baseline.

## Exact commands

For each profiled workload `W ∈ {absent, rare, mixed, sort, aggregation}`:

```sh
PATH="$PWD/target/pr15b/perf-bin:$PATH" \
  bash benchmarks/scripts/profile-pr15b.sh --mode perf \
    --workload "$W" --out "target/pr15b/profiles/$W-perf"

target/pr15b/perf-bin/perf report \
  -i "target/pr15b/profiles/$W-perf/perf.data" --stdio \
  --no-children --sort dso,symbol --percent-limit 0.5 \
  > "target/pr15b/profiles/$W-perf/perf-self.txt"

PATH="$PWD/target/pr15b/perf-bin:$PATH" \
  bash benchmarks/scripts/profile-pr15b.sh --mode flamegraph \
    --workload "$W" --out "target/pr15b/profiles/$W-flamegraph"

PATH="$PWD/target/pr15b/perf-bin:$PATH" \
  bash benchmarks/scripts/profile-pr15b.sh --mode heaptrack \
    --workload "$W" --out "target/pr15b/profiles/$W-heaptrack"

heaptrack_print \
  -f "target/pr15b/profiles/$W-heaptrack/heaptrack.gz" \
  -p -a -T \
  -H "target/pr15b/profiles/$W-heaptrack/histogram.txt" \
  -F "target/pr15b/profiles/$W-heaptrack/folded.txt" \
  > "target/pr15b/profiles/$W-heaptrack/heaptrack-report.txt"
```

The wrapper's perf mode uses `perf record -g --call-graph dwarf ... --seconds 20`;
the heaptrack mode uses the same 20-second bounded loop. `absent` was profiled
twice with perf under the same configuration (P4-X09); SHA-256 self cost was
82.75% and 82.83%, confirming stability.

## CPU results (perf, 10K/4)

Self CPU percentages from `perf report --no-children`:

| Workload | SHA-256 envelope | ByteReader::varint | JSON path decode | Query-specific self cost | Other |
|---|---:|---:|---:|---:|---:|
| `absent` | **82.75%** | 2.36% | 1.56% + 0.87% directory | — | SegmentError drop glue 1.96%, malloc/cfree 1.58%, from_utf8 0.89% |
| `rare` | **74.30%** | 2.41% | 1.42% + 0.86% directory | — | SegmentError drop glue 2.55%, malloc/cfree 1.92%, from_utf8 1.22% |
| `mixed` | **64.73%** | 2.68% | 1.24% + 0.73% directory | `evaluate_unified` **8.53%** | SegmentError drop glue 2.30%, malloc/cfree 1.97%, from_utf8 1.11% |
| `sort` | **64.92%** | 2.13% | 1.16% + 0.71% directory | `MixedEntry` heap **1.84%**, `sort_tuple_for_doc` **0.75%**, BTreeMap 0.85% | SegmentError drop glue 2.29%, malloc/cfree 2.26%, from_utf8 1.21% |
| `aggregation` | **55.53%** | 1.78% + 1.20% u64 | 1.00% + 0.62% directory | `visit_aggregate` **1.95%**, `ColumnReader::span_of` **1.30%**, `ColumnReader::value` **0.62%** | SegmentError drop glue 2.79%, malloc/cfree 3.98%, from_utf8 1.25% |

Inclusive path (representative branch from the default call-tree report):

| Workload | `open_segment_reader` | `SegmentReader::open` | `parse_container` | envelope `sha256` | JSON path directory |
|---|---:|---:|---:|---:|---:|
| `absent` | 96.37% | 95.34% | 81.93% | 81.87% | 11.57% |
| `rare` | 69.28% | 68.56% | 58.70% | 58.64% | 8.47% |
| `mixed` | 59.95% | 59.32% | 50.96% | 50.92% | 7.23% |
| `sort` | 60.52% | 59.81% | 51.22% | 51.15% | 7.36% |
| `aggregation` | 50.97% | ~50% | 43.84% | 43.78% | 6.22% |

The inclusive percentages vary by branch/segment; the no-children self table is
the primary quantity. The consistent finding is that **every query re-opens each
segment and re-computes the whole-segment envelope SHA-256**. The direct source
path is:

```text
ReaderSnapshot::open_segment_reader  (index/snapshot.rs:455)
  -> SegmentReader::open             (segment/reader.rs:54/61)
     -> parse_container              (segment/format.rs:734)
        -> sha256(&bytes[..trailer_offset])  (segment/format.rs:842)
```

`open_segment_reader` also clones the full segment byte vector before parsing
(`segment.bytes.as_ref().clone()` at `index/snapshot.rs:455`). The profile
therefore explains why zero-hit and one-hit queries scale with corpus size.

## Allocation results (heaptrack, 10K/4)

| Workload | Iterations in 20s | Total allocations | Temporary allocations | Total allocated bytes* | Peak live heap | Peak RSS | Leaked |
|---|---:|---:|---:|---:|---:|---:|---:|
| `absent` | 399 | 21,728,612 | 10,111,909 | 2,168,488,983 (~2.07 GiB) | 16.03 MiB | 29.82 MiB | 544 B |
| `rare` | 252 | 23,787,507 | 8,098,161 | 2,139,795,753 (~2.04 GiB) | 16.03 MiB | 29.86 MiB | 544 B |
| `mixed` | 208 | 25,634,579 | 9,497,813 | 2,213,497,622 (~2.11 GiB) | 16.03 MiB | 29.82 MiB | 544 B |
| `sort` | 192 | 26,861,922 | 8,272,137 | 2,038,866,063 (~1.94 GiB) | 16.03 MiB | 29.88 MiB | 544 B |
| `aggregation` | 97 | 26,588,172 | 4,458,931 | 1,966,027,475 (~1.87 GiB) | 16.03 MiB | 29.95 MiB | 544 B |

\* Total allocated bytes are the sum of `size × count` from the heaptrack
histogram. This is **cumulative allocation traffic, not retained memory**. Peak
live heap is constant at 16.03 MiB across all workloads and is dominated by the
resident immutable corpus/index, not by query temporaries. The single leaked
allocation is 544 B and is not on the search path.

### Dominant allocation call sites

Counts are over the whole 20s process (including one fixture build and the untimed
oracle); the repeated query loop dominates. Per-iteration values are approximate
and are shown only to relate the counts to the query path.

| Workload | Allocation site | Count | Approx/query | Peak | Interpretation |
|---|---|---:|---:|---:|---|
| `absent` | `segment/json_paths.rs:1099` (`decode_path` in `decode_directory`) | 9,476,250 | ~23,750 | 0 B | JSON-path directory rebuilt on every segment open |
| `absent` | `segment/reader.rs:163` (same `decode_directory` call) | 9,476,250 | ~23,750 | 0 B | same call site, alternate stack merge |
| `absent` | `search/execute.rs:1899` (live `BTreeSet` collect) | 331,968 | ~832 | 0 B | per-segment live-set materialization |
| `absent` | `segment/format.rs:885` (`format!` in `ok_or`) | 15,960 | ~40 | 0 B | eager error string on every section iteration |
| `rare` | `segment/reader.rs:163` + `json_paths.rs:1099` | 5,985,000 + 1,496,376 | ~29,700 | 0 B | same per-query segment open |
| `rare` | `segment/value.rs:395` | 1,102,500 | ~4,375 | 0 B | typed document value decoding |
| `mixed` | `segment/reader.rs:163` + `json_paths.rs:1099` | 4,940,000 + 1,235,104 | ~29,700 | 0 B | per-query segment open |
| `mixed` | `segment/reader.rs:626` (`DocumentKey::new`) | 1,040,000 | ~5,000 | 0 B | key materialization |
| `mixed` | `search/projection.rs:130` (field clone) | 104,000 | ~500 | 0 B | projection of selected hits |
| `sort` | `json_paths.rs:1099` / `reader.rs:163` | 4,560,000 each | ~23,750 | 0 B | per-query segment open |
| `sort` | `search/unified.rs:710/714` (doc key + sort tuple) | 1,920,000 each | ~10,000 | 0 B | sorting materialization |
| `sort` | `reader.rs:626` (`DocumentKey::new`) | 1,920,000 | ~10,000 | 0 B | key materialization |
| `aggregation` | `json_paths.rs:1099` / `reader.rs:163` | 2,303,750 each | ~23,750 | 0 B | per-query segment open |
| `aggregation` | `search/typed.rs:2393/2476`, `analytics.rs:885`, `contract/document.rs:100` | ~970,000 each | ~10,000 | 0 B | group/metric staging per document |
| `aggregation` | `segment/format.rs:255` / `contract/value.rs:286` | 970,000 each | ~10,000 | 0 B | typed value decoding |

The common `SegmentReader::open` / `JsonPathsReader::decode_directory` allocation
path is the largest repeated allocation source in every workload, including the
zero-hit query. The per-query total allocation count is therefore dominated by
segment re-open/re-decode, not by candidate scoring alone.

## Flamegraph artifacts

| Workload | Artifact | Size | Notes |
|---|---|---:|---|
| `absent` | `target/pr15b/profiles/absent-flamegraph/flamegraph.svg` | ~308 KB | retained after debuginfo/P4-X11 fix |
| `rare` | `target/pr15b/profiles/rare-flamegraph/flamegraph.svg` | ~482 KB | perf lost chunks reported; 20,294 samples |
| `mixed` | `target/pr15b/profiles/mixed-flamegraph/flamegraph.svg` | ~603 KB | perf lost chunks reported; 20,243 samples |
| `sort` | `target/pr15b/profiles/sort-flamegraph/flamegraph.svg` | ~609 KB | perf lost chunks reported; 20,210 samples |
| `aggregation` | `target/pr15b/profiles/aggregation-flamegraph/flamegraph.svg` | ~780 KB | perf lost chunks reported; 20,225 samples |

The `perf` flat reports completed with no lost samples. Cargo-flamegraph reported
small lost-chunk counts ("Check IO/CPU overload") but produced usable 20K-sample
graphs; this is recorded as a measurement limitation, not a failed capture.

## What remains unavailable

- No CPU profile exists for the U03 `title=gamma` **100K** lane or the 100K
  absent/rare/mixed lanes: no approved profiling entrypoint builds 100K.
- No separate K=1000 profiling lane exists; `sort` profiles K=100 only.
- No `json` or `batch` profiling lanes were run because they are outside the
  priority table.
- The generic perf binary does not match the WSL kernel version; results are
  usable but carry that reproducibility caveat.
- Heaptrack measures cumulative allocation traffic and peak live heap; it does
  not justify total-allocated-bytes-equals-retained-memory or an RSS cap.
