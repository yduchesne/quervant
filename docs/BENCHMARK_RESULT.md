# Benchmark result JSON — format reference

**Status:** Current implemented `benchmark-result-v1` result contract on the BM-10 implementation branch (PR #113). This permanent reference documents **actual serialized fields and present validation**, including incomplete runs. It does not claim that a real performance run has been executed or accepted.

**Related references:** [Benchmark configuration JSON](BENCHMARK_CONFIGURATION.md) · [Benchmarking methodology and naming](BENCHMARKING.md) · [BM-10 CLI guide](../benchmarks/BM10_README.md).

**Implementation authority:** `benchmarks/quervant_bench/lean/runtime.py` (`run_benchmark`, `collect_slot`, `collect_throughput`), `lean/artifacts.py` (`publish_result`, `load_result`), `lean/statistics.py` (`analyze`, `compare_historical`), `lean/reporting.py` (`render_report`), and `lean/cli.py` (`analyze`, `compare`, `report`/`replay`). There is currently **no separately enforced JSON Schema** for this new result format. Python producer/consumer code is authoritative.

## 1. What is a result?

A **result** represents a **single execution attempt** of a saved configuration. It is distinct from the immutable experiment specification: it records the run identity, execution date, the configuration it used, per-slot observations, control/readiness outcomes, build and host context, statistical analysis, metrics, errors, and final execution disposition.

A result is a **single Git-trackable JSON file** stored beside its source study's `configurations/` directory under:

```text
benchmarks/studies/<family>/<regime>/results/<configuration-name>-<execution-yyyy-mm-dd>-<NNN>.json
```

`<NNN>` is a **three-digit sequence from 001 to 999**, allocated monotonically **per configuration across all dates**. It does not reset at midnight. Publication is exclusive/atomic and must not replace an existing file. The execution timestamp is in UTC and is set at the **start of the run**. Saving locally requires **no manual approval**; Git commit/push is a separate task.

A result does **not** require a stored `configuration_path`: its parent is `studies/<family>/<regime>/results/`, and the configuration lives in the sibling `configurations/` directory under the exact `configuration_file` basename. The three supported studies are `retained-key/warm`, `cross-engine/warm`, and `cross-engine/cold-start`. **No `retained-key/cold-start` folder exists** because the retained-key experiment is a warm-only historical duplicate-strategy comparison. The directory enforces this supported-regime distinction during creation/publication, while portable copied results remain readable with their embedded configuration snapshot. Each study has its own results and each configuration has its own cross-date numbering.

The result's final analysis is stored directly in `analysis`. `report`/`replay` only render that stored value as Markdown, normally to stdout; there is no third durable benchmark artifact, seal, receipt, approval file, attestation, or separate evidence bundle. `analyze` is a **different**, explicit operation that recalculates from the stored raw samples and prints its output without replacing the saved result.

## 2. How a result relates to its configuration

**This is the central referential contract.** A configuration is a reusable, immutable **one-to-many parent**; each execution gets a separate result **child**.

| Configuration side | Result side | Meaning |
| --- | --- | --- |
| `configuration_id` | `configuration_id` | **Same canonical lowercase UUID.** This is the stable logical link to the experiment specification. |
| `name` | `configuration_name` | Same name; result names and filenames use the configuration's name exactly. |
| Filename `<name>-<creation-date>.json` | `configuration_file` | Exact original **basename**, including the creation date; the result's study folder identifies its sibling `configurations/` directory. No absolute path is stored. |
| `created_utc` | `executed_utc` | **Different events.** The configuration was created once; each result records its own run start timestamp. |
| Configuration object | `configuration` | Runner embeds the effective configuration JSON **snapshot** in each result so standalone reanalysis can read the configuration without fetching the original file. |
| (No run identity) | `run_id` | New canonical UUID for this execution attempt; not reused as `configuration_id`. |
| (No result sequence) | `sequence` | Automatically allocated monotonically across dates for the same configuration, reflected by `NNN` in the result filename. |

### Illustrative relationship (filenames only; NOT real measured results)

```text
benchmarks/studies/retained-key/warm/
  configurations/
    retained-key-prefilter-2026-11-22.json
      name             = retained-key-prefilter
      configuration_id = c5800fb9-ae02-4ee1-a726-491a44ab9857

  results/
    retained-key-prefilter-2026-11-24-001.json   (illustrative first run)
    retained-key-prefilter-2026-11-25-002.json   (illustrative second run)
    retained-key-prefilter-2026-11-25-003.json   (illustrative third run)
```

Every illustrative result would carry that exact `configuration_id` and `configuration_file: "retained-key-prefilter-2026-11-22.json"`, plus a **different** `run_id` and an execution date matching its own filename. The directory is derived from the source configuration's supported family/regime, not from its filename alone. The result `sequence` would be `1`, `2`, and `3`, respectively. The dates do **not** require a new configuration. These sample filenames **do not assert that real result files exist**.

### Creation, loading, immutability and what is actually checked

1. The runner reads and validates the source configuration and derives lanes from it, then records an embedded `configuration` snapshot.
2. The result publisher reopens the source configuration, checks the **global study registry** for the name/`configuration_id` pairing, checks the result's `configuration_id`, and **generates** `configuration_name`, `configuration_file`, `sequence` and destination filename **inside the sibling `results/` directory**, rejecting cross-study output routing. It does not take those identity fields from arbitrary caller-provided values.
3. When loading a result, the reader checks its own filename/name/date/sequence consistency, canonical IDs, and that `raw_samples` is an array and `analysis` is an object. Existing results are considered when allocating future suffixes.
4. **Important present limitation:** the result loader does **not** independently reopen its configuration file or verify that the embedded `configuration` snapshot is byte-for-byte equal to that file. There is no hash/digest or seal binding. The system relies on the configuration's intended **immutability** and normal Git version control. Editing the referenced file after a result is saved can create an unreconciled inconsistency: **do not edit it**.
5. `analyze` uses the **embedded** `result.configuration` (arms, baseline, policy) together with `result.raw_samples` and `result.lanes`. It does **not** run adapters, require the original configuration file, or silently update the stored analysis. `report`/`replay` use only the saved analysis and do **not** recalculate statistics.

A `run_id` is freshly generated for each execution by the runner; the loader validates its UUID shape, but does not scan every other result to prove global `run_id` uniqueness. The one-to-one configuration-name/ID registry is enforced **across all studies** at configuration creation.

## 3. Top-level result field dictionary

The normal producer emits the following fields; the publisher adds the three identity/sequence fields indicated below. A run aborted during acquisition may have empty, partial, or absent optional metric objects.

| Field | Type | Source | Meaning |
| --- | --- | --- | --- |
| `schema` | string | runner | Currently `benchmark-result-v1`. |
| `family` | string | runner | `retained-key` or `cross-engine`, copied from configuration. |
| `configuration_id` | UUID string | runner, checked by publisher | Must identify the referenced configuration. |
| `configuration_name` | string | **publisher** | Exact referenced configuration `name`. |
| `configuration_file` | string | **publisher** | Exact original configuration filename, including **creation date**. |
| `configuration` | object | runner | Effective embedded configuration snapshot, with its own `schema`, `name`, `configuration_id`, `workload`, `arms`, `baseline`, `control`, `build`, `policy`. |
| `run_id` | UUID string | runner | Distinct execution attempt identifier; canonical lowercase UUID. |
| `executed_utc` | UTC timestamp string | runner | Run **start** timestamp, required to match result filename's UTC execution date. |
| `sequence` | integer | **publisher** | 1–999, monotonic across execution dates for a configuration; filename suffix is 3-digit padded form. |
| `status` | string | runner | Top-level execution disposition: see §4. |
| `lanes` | array of objects | runner | Effective lane matrix (workload, metric, direction, cache regime); see §5. |
| `raw_samples` | array of objects | runner | Measured treatment slot/lane records; empty/partial on failure; see §6. |
| `analysis` | object | runner/statistics | Finalized paired analysis when available, otherwise `{}`; see §8. |
| `controls` | object | runner | A/A raw observations, derived A/A decisions and host readiness diagnostics; see §7. |
| `index_metrics` | object | runner | Per-arm/per-corpus index build, commit, reopen and size; see §9. |
| `throughput_metrics` | object | runner (conditional) | Cross-engine serial throughput results where that phase was reached; may be **absent**. |
| `context` | object | runner | Host, source revision, build settings, pinned CPU choices and diagnostics; see §10. |
| `errors` | string array | runner | Diagnostic failures; generally nonempty for `INCOMPLETE`. |
| `notes` | string | runner | Current generated note: no historical performance comparison implied. |

**Reader validation is deliberately narrower than this full semantic dictionary.** Some fields are required by the producer and downstream analysis but are not independently schema-checked in `load_result`. Do **not** claim that a JSON file was statistically validated merely because it passed simple result loading. `schema` is the producer's format discriminator; the present loader does not enforce its exact value.

## 4. Top-level run status versus per-comparison status

| `status` | Meaning in current runner |
| --- | --- |
| `INCOMPLETE` | Acquisition/validation/host/process interruption or error. Collected measurements are preserved; do **not** present as accepted comparative performance. `analysis` may be `{}` or may already exist if failure came after analysis. |
| `COMPLETE` | The runner finished mandatory stages without fatal measurement failure, and no per-lane status in the configured aggregate-ineligibility set forced `INCONCLUSIVE`. **This does not mean the candidate improved**. A measured slowdown (`REGRESSED`) or a per-lane `INCONCLUSIVE` may still be a valid completed result. |
| `INCONCLUSIVE` | A completed run with no eligible comparisons or relevant structural/metric non-comparability or non-computability. Do not invent an overall winner. |

**Within-run analysis comparison statuses:** `IMPROVED`, `REGRESSED`, `INCONCLUSIVE`, `NON_COMPARABLE`, `NOT_COMPUTABLE`; A/A comparisons use `PASS`/`FAIL`. Numeric comparisons retain point estimates and confidence intervals; non-comparable or non-computable comparisons may contain only a status and reason.

**Across-run `compare` output statuses (a separate view, not saved back to either result):** `COMPARABLE`, `CONTEXT_CHANGED`, `NOT_COMPARABLE`, `UNAVAILABLE`. Comparison is computed only from compatible **within-run** gains, never unmatched absolute old/current latencies. It refuses numeric effects from incomplete runs, non-passing A/A controls, invalid readiness or missing/incorrect lane samples. Missing history is nonfatal.

## 5. `lanes[]`: effective workload matrix

Each normal lane descriptor has:

| Key | Type | Meaning |
| --- | --- | --- |
| `id` | string | `<n>/<class>/k<k>/<regime>`, e.g. `10000/medium/k100/warm`. |
| `workload_id` | string | Configuration's `workload.id`. |
| `n` | integer | Corpus size (10,000 or 100,000). |
| `class` | string | `absent`, `rare`, `medium`, `common`. |
| `field`, `term` | strings | Independently expected exact field/term query. |
| `k` | integer | Top-K value. |
| `cache_regime` | string | `warm` or `process-cold`. |
| `query_semantics` | string | Declared exact-keyword/ordered-IDs search semantics. |
| `timed_operation` | string | Warm: `exact-term-search-plus-topk-projection`; cold-start: `process-launch-to-first-jsonl-response` (different operation/metric, do not compare as identical latency). |
| `metric` | string | Warm: `search_latency`; cold-start: `cold_start_first_response_latency`. |
| `unit` | string | Current default `ns`. |
| `direction` | string | Current default `lower` (lower is better). |
| `comparability` | string | Currently generated `COMPARABLE`; an analysis lane can instead be `NON_COMPARABLE` with a `reason` when equivalent work is not demonstrated. |

A lane represents one shared comparison scenario; arms are implementations, not lanes. The current generated metadata alone does **not** prove real cross-engine semantic equivalence; actual adapter correctness and timing-boundary checks must still pass.

## 6. `raw_samples[]`: treatment measurements

For each completed timed lane within a scheduled slot, the real runner appends a record:

| Key | Type | Meaning |
| --- | --- | --- |
| `block` | integer | 1-based randomized paired block number. |
| `position` | integer | 1-based position of that slot within its block. |
| `arm_id` | string | Implementation arm (e.g. `P`, `Q`). |
| `lane_id` | string | References one `lanes[].id`. |
| `warmups` | integer | Untimed warmup count: normally policy `warmups` for warm lanes; zero for process-cold slots. |
| `samples_ns` | positive-integer array | For warm: engine-reported search nanoseconds; for process-cold: **wall-clock process launch to first complete JSONL reply**, of length `policy.samples` per complete lane/slot. The analyzer uses these values for each study's declared metric. |
| `oracle_ok` | boolean | Must be `true` for analysis, after independently verifying exact hit count and ordered IDs. |
| `strategy_marker` | string or null | Expected experimental strategy marker only for **retained-key** L/P/H diagnostic variants; `null` for production-default Quervant Q and for non-overridden engines. The Quervant default dispatch is defined in production Rust code, not confirmed by an experimental marker. |
| `engine_samples_ns` | positive-integer array; cold only | Query-only `engine_ns` values returned by the adapter, validated against the same correctness oracle. These are retained **separately** from wall-clock cold-start measurements. |
| `index_open_samples_ns` | positive-integer array; cold only | Adapter-reported `index_open_ns` for each first-query process, measured around index opening, reader creation and initialization. It **does not include** query execution. |
| `other_overhead_samples_ns` | nonnegative-integer array; cold only | Per-observation `samples_ns − index_open_samples_ns − engine_samples_ns`. Includes process/JVM startup, scheduling and JSONL handling/transport, but **not** the independently timed index opening or query work. This is a combined residual, **not a pure OS process-startup metric**. |
| `timing_scope` | string; cold only | Explicitly `process launch through first complete JSONL reply`. |
| `analysis.lanes[].component_absolute` | nested object; analyzed cold only | Per-arm descriptive index-open, query and other-overhead block medians and individual block values, computed during analysis from the component arrays. |

For a complete run, `statistics.analyze` verifies complete block/lane/slot coverage, per-block arm multiplicities, and exact seeded schedule assignments. An invalid, duplicate, missing, or incorrectly answered sample prevents valid analysis.

A cold-start observation invokes a fresh adapter process and sends **one** query; its first complete reply stops the wall timer **before process shutdown**. Every Quervant, Tantivy and Lucene adapter times its own index/reader open independently, reporting `index_open_ns` on the **first successful query response after opening the index**. That duration excludes the separately timed `engine_ns` query/search/Top-K projection. Subsequent queries using the same open reader omit `index_open_ns`. The cold-start runner rejects missing, boolean, nonpositive or inconsistent open times and verifies exact hits/ordered IDs before recording the observation.

For each cold observation, `samples_ns = index_open_samples_ns + engine_samples_ns + other_overhead_samples_ns`. Read-only `analyze` validates this equality and the length/types of all three component arrays; incomplete or inconsistent observations are **not** eligible for a valid performance decision. The final analysis stores a `component_absolute` map by arm with descriptive per-block absolute values and median block value for `index_open_ns`, `engine_ns` and `other_overhead_ns`. The Markdown renderer presents them without recomputing. Individual component medians are not additive, even though **every raw observation** reconciles exactly. The component summaries are descriptive rather than independently CI-gated optimization outcomes.

The response is verified against expected hit count/ordered IDs before its duration can be recorded. Warm and cold-start results use different `timed_operation` and `metric` values; they must not be combined or interpreted as the same quantity. Each study has a **separate saved configuration, UUID, result JSON and run lifecycle**.

**Raw data are not discarded** when an error occurs. The array may stop mid-campaign; an incomplete sequence is preserved with top-level `INCOMPLETE`, not relabeled as a valid comparison. A/A samples live separately under `controls.raw_samples`, so `raw_samples` at the top level is specifically the **treatment** phase.

## 7. `controls`: readiness and equivalent-baseline A/A

`controls` is populated incrementally. Possible keys:

| Key | When present | Meaning |
| --- | --- | --- |
| `readiness_index_pre` | Checked real host before indexing | Host contention immediately before timed index metrics. |
| `readiness_pre` | Checked real host before A/A | Pre-control contention. |
| `raw_samples` | A/A acquisition began | A/A arm/slot/lane samples, with `AA` and `AA2` roles; same general record structure as §6. |
| `analysis` | A/A analysis succeeded | Normal `bm10-analysis-v1` object, with `kind: "A/A"` and per-lane `PASS`/`FAIL`. |
| `readiness_treatment` | Checked real host before treatment | Contention before timed treatment slots. |
| `readiness_post` | Checked real host after treatment | A failure invalidates the run while retaining raw samples/analysis. |
| `readiness_throughput_pre` | Checked cross-engine real host before throughput | Contention before separately timed serial throughput. |
| `readiness_throughput_post` | Checked cross-engine real host after throughput | A failure invalidates the run while retaining collected measurements. |

Readiness observations normally contain `cpu` (integer), `observations` (array of `{busy_percent, steal_percent}` numbers), `max_busy_percent`, `max_steal_percent` and `status` (`clear` or `busy`). Under deterministic test injections (`check_host=False`) these keys may be absent; such an injected test is **not** real-host qualification.

An unstable A/A control blocks further comparative acquisition. The presence of an `analysis` object alone is **not** proof of valid readiness, correctness or complete acquisition; evaluate `status` and `controls`.

## 8. `analysis`: computed per-lane statistics and decisions

The analysis object is present even on incomplete runs, but may be empty (`{}`). A completed analysis has:

| Key | Type | Meaning |
| --- | --- | --- |
| `schema` | string | `bm10-analysis-v1`. |
| `estimator` | string | `median-paired-ratios-v1`. |
| `bootstrap_method` | string | `paired-whole-block-percentile-v1`. |
| `lanes` | object | Map from lane ID to its derived analysis row. |

For each `analysis.lanes["<lane-id>"]`:

| Field | Meaning |
| --- | --- |
| `metric`, `unit`, `direction` | Measurement identity, units, and improvement orientation. |
| `raw_blocks` | Number of acquired scheduled blocks in this lane. |
| `excluded_blocks` | Sorted explicit block numbers excluded symmetrically for every arm; raw data preserved. |
| `retained_blocks` | Eligible paired blocks after exclusions. |
| `arm_absolute` | Map of arms to `median_block_value` and per-block `block_values` (absolute values, ns for latency). |
| `comparisons` | Map of treatment arms to comparison outcomes against the declared baseline. |

The cold-start `analysis.lanes["<lane-id>"].component_absolute` object additionally contains per-arm `index_open_ns`, `engine_ns` and `other_overhead_ns` with `median_block_value` and `block_values`. These descriptive summaries use the same slot-median/block-mean process but are **not** separate paired comparison decisions; total first-response latency remains the primary statistically evaluated cold-start metric.

For a numerical `comparisons["<treatment-arm>"]`:

| Field | Type | Meaning |
| --- | --- | --- |
| `kind` | string | `treatment` or `A/A`. |
| `status` | string | Individual comparison verdict (see §4). |
| `baseline_arm`, `treatment_arm` | strings | Explicit comparison orientation. |
| `ratio_b_over_a` | number | **Median of retained paired block ratios**, treatment/baseline. |
| `ratio_ci_95` | two-number array | 95% paired whole-block bootstrap interval for the ratio. |
| `gain_percent` | number | Signed improvement: lower-is-better `100 × (1 − B/A)`; higher-is-better `100 × (B/A − 1)`. |
| `gain_ci_95_percent` | two-number array | Direction-aware uncertainty interval for signed gain, ordered low-to-high. |
| `retained_paired_ratios` | number array | Per-retained-block treatment/baseline ratios; no unpaired pooling. |
| `bootstrap_resamples` | integer | Number of resamples actually used. |

For `NON_COMPARABLE`, `INCONCLUSIVE` (too few blocks), or `NOT_COMPUTABLE` (e.g. zero baseline), the comparison may contain only `status` and `reason`—**do not assume numerical fields exist**.

Interpretation: `B/A` always means **treatment divided by baseline**. For latency, `B/A < 1` favors the treatment; a measured `REGRESSED` outcome is still a valid observation. For throughput the direction is reversed. Confidence intervals resample whole blocks, preserving pairing. Historical *cross-run* comparisons must use differences of compatible **within-run gains in percentage points**, not differences or ratios of unmatched absolute durations.

## 9. `index_metrics` and `throughput_metrics`

**`index_metrics`** maps **arm ID → corpus-size string → metric object**. These index **write/build** metrics are collected independently of cold-start query-session `index_open_ns`, which measures an actual fresh reader opening for a query process:

| Inner key | Type | Meaning |
| --- | --- | --- |
| `index_ns` | positive integer | Adapter-measured document insertion duration. |
| `commit_ns` | positive integer | Index commit duration. |
| `reopen_ns` | positive integer | Reader/index reopen duration. |
| `index_bytes` | positive integer | On-disk index size in bytes, checked against actual stored files. |
| `segment_count` | integer | Adapter-reported segment count. |

These are separately measured build/index values, **not** search latency. Partial metrics may survive an interrupted run. The current producer collects these for **both benchmark families**.

**`throughput_metrics`** is emitted only for **cross-engine warm** runs that reach the serial-throughput stage. It maps each engine arm to:

| Inner key | Type | Meaning |
| --- | --- | --- |
| `lane_id` | string | The selected warm medium-cardinality Top-K 10 lane for 10K documents. |
| `requests` | integer | Number of serial timed requests (currently 100). |
| `warmups` | integer | Untimed warmup requests before the window. |
| `wall_ns` | positive integer | Total wall-clock duration of sequential query/request-response window. |
| `serial_ops_per_second` | number | `requests × 1e9 / wall_ns`, rounded. |
| `status` | string | `MEASURED` when valid. |
| `timing_scope` | string | Explicit serial JSONL-session timing boundary; process startup excluded, protocol overhead included. |

Throughput is **not** inferred from per-query `engine_ns`, and it is **not** parallel QPS. It is absent from cold-start and retained-key runs, and may be absent from incomplete warm runs.

## 10. `context`, `errors` and `notes`

`context` normally includes:

- `host`: Linux/WSL2 platform information (`system`, `kernel`, `architecture`, `cpu`, `physical_core_candidates`, `filesystem`, `wsl`, `toolchains`).
- `source_revision`: actual `git rev-parse HEAD` for a real runner, or `MOCKED` for explicitly injected test programs.
- `build`: descriptive build metadata such as `source_revision`, `compiler_options`, and `quervant_strategy_feature_enabled` (**false** for cross-engine production-default Quervant, **true** for retained-key diagnostics); retained-key also records `baseline_ref`. Under injection it may instead state `mode: INJECTED_TEST`.
- `controller_cpu`, `adapter_cpu`: CPUs used for isolation where available.

These are **descriptive context**, not approvals or digest-based identity gates. An incomplete run may lack some of them.

`errors` lists bounded diagnostic messages on failures; `notes` is a human-readable qualification note. Both are included **inside the same result JSON**, never in a separate receipt or report artifact.

## 11. Safe CLI operations and persistence boundaries

```bash
# Presentation only: does not invoke analysis or any benchmark adapter.
quervant-bench report --result benchmarks/studies/<family>/<regime>/results/<name>-<execution-date>-001.json
quervant-bench replay --result benchmarks/studies/<family>/<regime>/results/<name>-<execution-date>-001.json

# Optional read-only computation: recalculates from the EMBEDDED configuration,
# stored raw_samples and lanes. Does not modify the saved result JSON.
quervant-bench analyze --result benchmarks/studies/<family>/<regime>/results/<name>-<execution-date>-001.json

# Relative within-run gain comparison across two existing, compatible results.
quervant-bench compare \
  --current benchmarks/studies/<family>/<regime>/results/<current-result>.json \
  --historical benchmarks/studies/<family>/<regime>/results/<historical-result>.json \
  --lane 10000/medium/k100/warm --arm P
```

The path placeholders above are **not existing results** and these commands are not real benchmark executions. `quervant-bench run` is the only CLI verb that initiates acquisition; it is intentionally **outside** documentation/implementation-only QA.

**Do not edit or overwrite saved results.** A result can be `INCOMPLETE` and still worth preserving. A Markdown rendering is an ephemeral view, not evidence independent of its JSON. Result allocation never reuses a suffix across dates.

## 12. Version and compatibility boundaries

- `benchmark-result-v1` is the current producer's schema identifier, not a general schema for arbitrary metric types or distributed campaigns.
- Configuration and result schemas are **separately versioned**. Results reference a particular saved `configuration_id` and embed the effective configuration; future incompatible fields or semantics should receive a new documented schema/version rather than silently changing old results.
- The current Python loader performs basic shape and filename checks, **not** full statistical recertification or formal JSON Schema validation.
- The existing fixed workload matrix and adapter protocol (`pr15d-adapter-v1`) remain specialized to exact-keyword search. Future workloads may require new or extended adapters and new versioned format rules; do not misrepresent an unimplemented generalization as present.
- **No real BM-10 results** are supplied by this documentation. The milestone cannot be marked complete from schema/docs/unit-test success alone.

See [Benchmark configuration JSON](BENCHMARK_CONFIGURATION.md) for all configuration fields, allowed values, defaults, and the immutable parent identity.
