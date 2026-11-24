# Benchmark configuration JSON — format reference

**Status:** Implemented `benchmark-configuration-v1` contract merged into `main` by **BM-10 DONE — PR #113**. This reference describes **what the code supports today**, not a proposed generalized benchmark system. It is a permanent format reference, independent of the BM milestone identifier.

**Related references:** [Benchmark result JSON](BENCHMARK_RESULT.md) · [Benchmarking methodology and permanent naming rules](BENCHMARKING.md) · [BM-10 command-line guide](../benchmarks/BM10_README.md).

**Implementation authority:** `benchmarks/quervant_bench/lean/configuration.py` (`default_configuration`, `validate_configuration`, `lanes_for`); `lean/artifacts.py` (`configuration_filename`, `create_configuration`, `load_configuration`); `lean/runtime.py` for actual execution and adapter interpretation. There is currently **no separately enforced JSON Schema** for these two new artifact formats; the Python validators and runner are authoritative. This document must be updated if those contracts change.

## 1. Purpose, lifecycle, and relationship to results

A **configuration** identifies one immutable experiment specification: workload, arms, baseline, control, build requirements, and measurement/statistical policy. Under the [baseline-promotion rule](BENCHMARKING.md#within-run-comparisons-treatment-versus-baseline), an accepted optimization is part of subsequent **production-default** comparisons. The retained-key family documents an older experimental reference for retrospective comparison, not the current Quervant reference. It is **not a run**, a result, a measurement, an approval, or an integrity certificate.

1. Save a configuration under `benchmarks/studies/<family>/<regime>/configurations/<name>-<yyyy-mm-dd>.json`. The CLI selects the family/regime directory automatically. The filename's date is the **UTC creation date** (`created_utc`), *not* the date measurements are taken.
2. Assign one canonical lowercase UUID to `configuration_id`. The `name` and `configuration_id` must each be unique across **all configurations under `benchmarks/studies/`** and retain a **one-to-one** mapping; an existing name cannot be reused for another ID, nor an existing ID assigned a different name.
3. Run the same configuration repeatedly, producing **separate result JSON files**. Each result copies the configuration's `configuration_id`, records its exact `configuration_file` filename, embeds a `configuration` snapshot for read-only reanalysis, and owns a separate `run_id`, execution timestamp and cross-date sequence. Details and examples: [result reference §2](BENCHMARK_RESULT.md#2-how-a-result-relates-to-its-configuration).
4. A material change to workload, arms, source strategy, schedule, statistical policy, or other measured behavior requires **a new configuration, new UUID, and new distinct name** (e.g. `retained-key-prefilter-v2`). Do not silently edit a previously referenced configuration. A saved result does not mutate its source configuration.

**Current validation boundary:** `publish_result` checks the source configuration file, its name/ID registry, and the new result's matching `configuration_id`. It derives the result's `configuration_file`, `configuration_name` and `sequence` from the source file and allocator. It **does not cryptographically bind or verify** the embedded configuration snapshot against the file or revalidate its content at every read. Preserve configuration immutability by normal repository discipline; do not imply there is a hash/seal/receipt system.

**Study hierarchy is part of the configuration contract.** Supported paths are `retained-key/warm`, `cross-engine/warm`, `cross-engine/cold-start`, `perf-02/warm`, `perf-05/warm`, and `perf-06/warm`, each containing sibling `configurations/` and `results/`. The `workload.regimes` value `["process-cold"]` maps to the human-readable directory name `cold-start`; `["warm"]` maps to `warm`. A configuration under the wrong family/regime is rejected. **There is intentionally no `retained-key/cold-start`, `perf-02/cold-start` or `perf-06/cold-start` study**: these families test warmed query execution and do not measure process startup. The absent studies must not be created as empty placeholders. Future additional regimes require a reviewed experiment and validator change.

The global registry checks names and IDs across **all** study directories, not merely one `configurations/`. Result output always belongs to the sibling `results/` of the source configuration and cannot be redirected to another study; `configuration_file` within a result remains the original **basename**, not a path. See [permanent layout methodology](BENCHMARKING.md#permanent-study-directory-hierarchy).

The [permanent three-step query benchmark execution sequence](BENCHMARKING.md#query-benchmark-execution-sequence-permanent-methodology) governs the configured workload: build/commit/validate the index outside query acquisition; open the existing index/reader separately; then time only the declared query operation (or the explicitly distinct cold first-response wall window). Index construction is never part of query latency, and the build-phase `reopen_ns` is distinct from cold adapter `index_open_ns`.

The immutable configuration also identifies a reusable **local input preparation**. `quervant-bench stage --config <path>` (or an automatic `run` cache miss) compiles/builds the correct source and indexes, then verifies the corpus/index/oracles before real acquisition. The ignored `target/bm10/prepared/<cache-key>/` directory contains disposable builds/indexes and cache metadata; it is **not** a third Git-tracked benchmark artifact, evidence seal or historical result. Reuse requires matching full configuration content, the Git object IDs of build-relevant committed source trees/files (not merely the HEAD commit SHA), toolchains, build environment and host and passing ordinary local file checks plus all declared-lane correctness oracles. See the [permanent preparation method](BENCHMARKING.md#reusable-preparation-versus-timed-query-acquisition-permanent-rule). Cache hits never modify this configuration.

No extra benchmark artifact is needed: only **configuration JSON** and **result JSON** are persisted. Markdown is a presentation of a result, not a third persisted benchmark artifact.

## 2. Top-level field dictionary

| JSON key | Type | Required for supported runs | Meaning / constraint |
| --- | --- | --- | --- |
| `schema` | string | Yes | Exactly `benchmark-configuration-v1`. |
| `configuration_id` | string | Yes | Canonical lowercase UUID; stable per configuration and unique across the full studies-tree registry. |
| `name` | string | Yes | Lowercase hyphenated slug matching `[a-z][a-z0-9]*(?:-[a-z0-9]+)*`, 1–80 characters, unique across configurations. |
| `description` | string | Yes | Nonempty human-readable description. |
| `created_utc` | string | Yes | ISO 8601 UTC timestamp ending `Z`; calendar date determines configuration filename. |
| `family` | string | Yes | Exactly `retained-key`, `cross-engine`, `perf-02`, `perf-05`, or `perf-06`. |
| `workload` | object | Yes | Query/corpus matrix and exact timed operation; see §3. |
| `arms` | object | Yes | Fixed arm identities and their engine/strategy; see §4. |
| `baseline` | string | Yes | `A` for retained-key, perf-02 and perf-06; `B` for the single-arm perf-05; `Q` for cross-engine. |
| `control` | object | Yes | Separate A/A design; see §5. |
| `build` | object | Yes | Required build mode, source ref and strategy feature; see §6. |
| `policy` | object | Yes | Schedule, samples, bootstrap, decision thresholds and readiness; see §7. |

These fields are the **supported** current configuration surface. The Python validator does not reject every possible unknown JSON key; an unrecognized key is **not** a supported extension point and may be ignored. Do not infer configurable behavior from an extra field.

### Filename and ID example

```text
benchmarks/studies/retained-key/warm/configurations/retained-key-prefilter-2026-11-22.json
```

The example contains `"name": "retained-key-prefilter"`, a stable `configuration_id`, and `created_utc` on 2026-11-22 UTC. The ID, name, and date are distinct concepts. See [the committed retained-key configuration](../benchmarks/studies/retained-key/warm/configurations/retained-key-prefilter-2026-11-22.json).

## 3. `workload` object

| Key | Type | Current semantics |
| --- | --- | --- |
| `id` | string | Generated value `pr15d-exact-keyword-v1`. Identifies the exact-keyword workload; not an arbitrary adapter selector. |
| `sizes` | integer array | All **warm** families: `[10000,100000]`; cross-engine **cold-start**: `[10000]` only. |
| `classes` | string array | Warm: `["absent","rare","medium","common"]`; cold-start: `["medium"]` only. |
| `top_k` | integer array | Retained-key warm: `[1,10,32,64,100,128,256,512,1024]`; cross-engine, perf-02, perf-05 and perf-06 warm: `[10,100]`; cold-start: `[100]`. |
| `regimes` | string array | Exactly **one** of `["warm"]` or `["process-cold"]` per configuration. Retained-key, perf-02, perf-05 and perf-06 support warm only; cross-engine has separate warm and cold-start configurations. |
| `query_semantics` | string | Exactly `exact-keyword-total-hits-and-ordered-doc-ids`. Expected total hit count and ordered IDs are checked against an independent corpus formula. |
| `timed_operation` | string | Warm: `exact-term-search-plus-topk-projection` (adapter `engine_ns`); cold-start: `process-launch-to-first-jsonl-response` (wall clock from pre-spawn to first complete response, including process, adapter independently timed `index_open_ns` for reader initialization, query-only `engine_ns`, and remaining transport/startup overhead). |

The runner derives a **lane** from each combination of size, class, Top-K, and cache regime. Its ID is `<size>/<class>/k<top-k>/<regime>`, for example `10000/medium/k100/warm`. The same lane must be measured in all arms of the family.

`process-cold` starts a new adapter process for **each timed observation**, and times launch-to-first-JSONL-response. It does **not** guarantee a cold OS page cache. The cold-start study uses **one lane: `10000/medium/k100/process-cold`**, distinct from the full 16-lane warm study. Each has its own `name`, `configuration_id`, result sequence, and result file; the workload, timed operation, and metrics are **not** interchangeable. The runner validates these specific supported matrices; this is **not** a general workload-description language.

## 4. `arms` and `baseline`

Each arm is a JSON object with three standard fields; perf-02, perf-05 and perf-06 also require `revision`:

| Field | Type | Meaning |
| --- | --- | --- |
| `engine` | string | `quervant`, `tantivy`, or `lucene` (family/arm-specific). |
| `mode` | string | Current strategy selector, fixed per arm below. |
| `source` | string | Generated descriptive source role: `baseline` or `current` in legacy families; exactly `pinned` for perf-02, perf-05 and perf-06. Other families do not accept arbitrary source selectors. |

**Retained-key:** baseline `A`; arm set **exactly** `A, L, P, H`.

| Arm | Engine | Mode | Generated source |
| --- | --- | --- | --- |
| `A` | quervant | `BASE` | `baseline` (pinned Git baseline `build.baseline_ref`) |
| `L` | quervant | `linear` | `current` |
| `P` | quervant | `prefilter` (P2) | `current` |
| `H` | quervant | `exact_set` | `current` |

**Cross-engine:** baseline `Q`; arm set **exactly** `Q, T, J`.

| Arm | Engine | Mode |
| --- | --- | --- |
| `Q` | quervant | `by-top-k`: **unmodified production default**, linear below K=32 and P2 prefilter at K≥32 (therefore linear at K=10 and P2 at K=100). No experimental environment override. |
| `T` | tantivy | `default` |
| `J` | lucene | `default` |

**PERF-02:** baseline `A`, treatment `B`. Both must have `engine: quervant`, `mode: by-top-k`, `source: pinned`, and an explicitly declared lowercase **40-hex `revision` Git commit SHA**. Both builds retain the production default (linear below K32, P2 prefilter from K32). The same revision is permitted for *stage-only A=A host sanity checking* (validate/build/index/untimed oracles), not a real timed campaign or performance-gain claim. Actual candidate comparisons require separate revisions and a fresh versioned configuration. The build root checks each pinned object is an available Git commit before staging.

The engine and mode are validated against these exact mappings. The adapter implementation supports the current exact-term `build` and `query` operations; arbitrary new arms, other metrics and query families cannot be enabled by JSON alone.

**Subtle but important:** the scheduler consumes arm IDs in the iteration order of the **loaded configuration object**, not an independent order field. The current artifact writer serializes JSON with alphabetically sorted object keys. Changing or manually reordering the arm object can therefore change the seed-derived slot assignment. Treat that as a material configuration change; preserve the generated file unchanged.

## 5. `control` object

| Key | Type | Current supported value / meaning |
| --- | --- | --- |
| `enabled` | boolean | Must be `true`. |
| `baseline` | string | Exactly `AA`. |
| `equivalent` | string | Exactly `AA2`. |

A/A is a **separate** equivalent-baseline control phase with two arm labels. It checks measurement stability; it does not add two treatment arms or constitute an approval/receipt gate. The runner constructs the control configuration using the actual baseline arm. An unstable A/A control blocks the treatment phase and is recorded in the result.

## 6. `build` object

| Key | Type | Current supported behavior |
| --- | --- | --- |
| `release` | boolean | Must be `true`: release build. |
| `locked` | boolean | Must be `true`: locked dependency resolution. |
| `baseline_ref` | string or null | Retained-key requires a lowercase 40-hex Git SHA (currently `39dbd9f571a58bea8cc03d5a406533298e809bfe`); cross-engine default is `null`. |
| `prefilter_profile` | string | Must be `P2`. |
| `quervant_feature` | string or null | Retained-key requires `quervant-core/pr15i-d3c-experiment` to exercise its **historical diagnostic variants**. Cross-engine requires `null`: the Quervant reference is the uninstrumented **production default**. |
| `sort_contract` | string or absent | New cross-engine measurements require `doc_id:keyword:utf8-lex-asc:v1`: all engines sort the actual keyword/string `doc_id` ascending, never numeric `ordinal`. Absent in pre-correction historical configs; they remain read-only but are barred from staging/running. |
| `tantivy_version` | string or absent | For the new string-sort contract, exactly `0.25.0`. Earlier, absence (or `0.22.1`) identifies the frozen numeric-sort contract only; it does not authorize new measurements. |

The retained-key runner constructs a **pinned historical pre-optimization** source worktree and uses a current Quervant build with the historical experiment feature for L/P/H diagnostic arms. For cross-engine, **Quervant is built without that feature and without forced strategy/profile variables**. Its accepted production dispatch is owned by `TopKDuplicateConfig::default()` (K<32 linear; K≥32 P2). The independent Tantivy adapter is pinned to **0.25.0** for native ascending `doc_id` string FAST-field sorting; its prior numeric `ordinal` surrogate is removed. Lucene continues to sort the `doc_id` string. Result build context records whether Quervant experimental instrumentation was enabled; this is **descriptive**, not a binary-hash certification protocol. After an optimization is accepted into production it becomes the baseline for *future* work; the retained-key retrospective baseline A does not override that policy.

## 7. `policy` object

| Key | Type | Generated default | Semantics and enforced bounds |
| --- | --- | ---: | --- |
| `blocks` | positive integer | 12 | Number of balanced randomized treatment blocks; divisible by the treatment arm count and by 2 for control balance. |
| `slots_per_arm` | positive integer | 2 | Slots for each arm **per block**, not number of raw timed samples. |
| `warmups` | positive integer | 5 | Untimed warmups per warm lane/slot; process-cold query samples use zero per-slot warmups. |
| `samples` | positive integer | 20 | Timed observations per lane **per slot**. |
| `bootstrap_resamples` | positive integer | 10,000 | Whole-block bootstrap iterations; at most 100,000. |
| `seed` | integer | 20261122 | Unsigned 64-bit deterministic scheduling and bootstrap seed. |
| `min_blocks` | positive integer | 4 | Minimum retained blocks required for a conclusive comparison; cannot exceed `blocks`. |
| `min_gain_percent` | finite nonnegative number | 0 | Treatment improvement threshold applied to the lower bound of gain CI. |
| `max_regression_percent` | finite nonnegative number | 0 | Treatment regression threshold applied to the upper bound of gain CI. |
| `max_aa_gain_percent` | finite nonnegative number | 15 | Maximum absolute signed gain and CI bound for equivalent-baseline A/A PASS. |
| `exclude_blocks` | object | `{}` | Map of declared lane IDs to lists of **unique block numbers** in `[1,blocks]`; exclusions are symmetric across arms. |
| `control_arms` | array | `[]` | Must be empty in the normal configuration. A/A analysis separately uses `["AA2"]`. |
| `readiness` | object | See §8 | Predeclared host observation settings. |

Example of an exclusion declaration (illustrative syntax **only**, not an authorized exclusion policy):

```json
{
  "exclude_blocks": {
    "10000/medium/k100/warm": [3, 8]
  }
}
```

Exclusions must be declared before measurement. The analyzer retains raw samples, removes **whole block/lane comparisons** symmetrically, reports excluded IDs, and labels comparisons with too few retained blocks `INCONCLUSIVE`. The current system does **not** automatically infer or tune exclusion thresholds from observed performance.

**Statistical semantics:** a slot's value is the median of its measured query latencies; an arm's block value is the mean of its slot medians; each block supplies a paired treatment/baseline `B/A` ratio. The point effect is the median of eligible block ratios. The bootstrap resamples **whole blocks**, not individual query samples. Positive signed gain means improvement for the declared direction.

## 8. `policy.readiness` object

| Key | Type | Default | Constraint / role |
| --- | --- | ---: | --- |
| `intervals` | positive integer | 4 | Number of CPU observations, maximum 20. |
| `interval_ms` | positive integer | 250 | Duration of each observation, maximum 5,000 ms. |
| `max_busy_percent` | integer | 25 | Maximum CPU busy fraction as a percent, 1–100. |
| `max_steal_percent` | integer | 2 | Maximum CPU steal fraction as a percent, 1–100. |

The Linux/WSL2 runner checks physical-core availability, usable filesystem/toolchains and contention around timed phases. Readiness results live in the **result's** `controls` object, not in configuration. These checks prevent invalid comparisons; they are not manual approval or cryptographic attestation.

## 9. Current limitations, validation and versioning

**Automatic CI validation:** The single existing `python-benchmark-framework` job discovers all `benchmarks/studies/**/configurations/*.json` files and passes each through `load_configuration` and `validate_configuration`. It fails closed on an empty configuration set, invalid JSON, inconsistent names/dates/directories or unsupported semantic fields. There is **no per-study CI job or hard-coded configuration list**. Adding a configuration does not require changing the workflow. The CI validation is untimed and cannot replace real-host A/A or A/B qualification.

- **Five supported families and their fixed matrices.** A different corpus size, Top-K list, arm set, query semantics, cache regime or operation cannot be introduced by editing JSON alone. New workload adapters and a generalized configuration contract would be separate future development.
- The code checks important semantic fields but does **not** currently close every nested object against unknown keys, enforce `workload.id`/`arms.*.source` as strict enums, or provide a standalone JSON Schema. Do not treat an ignored extra key as supported behavior.
- `quervant-bench prepare --family cross-engine --regime warm|process-cold --name ... --description ...` creates a standalone warm or cold-start configuration (default `warm`). The `perf-02` and `perf-06` families require `--baseline-revision <40-hex>` and `--candidate-revision <40-hex>`; `perf-05` requires `--quervant-revision <40-hex>` and accepts no A/B revision flags. Retained-key, perf-02, perf-05 and perf-06 permit only `warm`. `--studies-root` can change the containing root while preserving this required relative layout. The deprecated `--config-dir` path override is not supported. `quervant-bench validate --config <path>` checks filename and semantics without measuring.
- A generated configuration should be saved in Git, but **Git commit/push is not part of benchmark execution**. New material revisions get a new name and UUID; there is no destructive in-place update.
- `schema` is the on-disk format discriminator. A future incompatible contract should introduce a **new schema/version**, document migration/compatibility, and not silently reinterpret historical configurations.
- A configuration does **not** contain `run_id`, `sequence`, `executed_utc`, raw samples, analysis, performance verdicts, or host observations. Those belong in the [result JSON](BENCHMARK_RESULT.md).

## 10. Examples and commands (no measurements)

Full, version-controlled examples:

- [PERF-02-A pinned Quervant A=A warm readiness configuration](../benchmarks/studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json)
- [Retained-key configuration](../benchmarks/studies/retained-key/warm/configurations/retained-key-prefilter-2026-11-22.json)
- [Current string-sort cross-engine warm configuration (16 lanes)](../benchmarks/studies/cross-engine/warm/configurations/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22.json)
- [Current string-sort cold-start configuration (one lane)](../benchmarks/studies/cross-engine/cold-start/configurations/quervant-tantivy-lucene-lexical-sort-cold-start-2026-11-22.json)
- [Historical numeric-sort warm configuration (do not rerun)](../benchmarks/studies/cross-engine/warm/configurations/quervant-tantivy-lucene-warm-2026-11-22.json)
- [Historical numeric-sort cold-start configuration (unexecuted; do not use)](../benchmarks/studies/cross-engine/cold-start/configurations/quervant-tantivy-lucene-cold-start-2026-11-22.json)

```bash
# Safe: checks only the saved configuration (no real benchmark).
quervant-bench validate --config benchmarks/studies/retained-key/warm/configurations/retained-key-prefilter-2026-11-22.json

# Creates a distinct configuration; never overwrites an existing name or UUID.
quervant-bench prepare --family retained-key \
  --name retained-key-prefilter-v2 \
  --description "Newly specified experiment"
```

**Warm and process-cold are independent experiments.** The earlier combined, unexecuted cross-engine draft has been replaced by two separately named/identified configurations, never silently mutated. The process-cold schedule still retains A/A controls, 12 balanced blocks, 2 slots per arm and 20 process launches per slot, for **2,400 planned launches** across three treatments and two A/A roles. **No real benchmark has been run merely by adding this documentation.** See [Benchmark result JSON](BENCHMARK_RESULT.md) for exact result-to-configuration linkage, field definitions, incomplete runs and reanalysis.

## PERF-05 B-only warm family

`perf-05/warm` is a **B-only** study family added for PERF-05-C. It measures one pinned Quervant revision and compares its **absolute** warm medians descriptively against a frozen historical reference. It is **not** a paired A/B family and must not be interpreted as one.

- `family` is exactly `perf-05`; only `warm` is supported; one declared arm `B` with `{"engine":"quervant","mode":"by-top-k","source":"pinned","revision":"<40-hex commit>"}` is required.
- The CLI accepts the revision only via `quervant-bench prepare --family perf-05 … --quervant-revision <40-hex commit>`. `--baseline-revision`, `--candidate-revision`, ref names and uppercase/partial revisions are rejected.
- `control` is `{"enabled":true,"baseline":"BB","equivalent":"BB2"}`. These are temporary aliases of the **same** B executable and indexes used only for within-session B/B stability; neither is A.
- `historical_reference` is fixed and validator-enforced: `/benchmarks/studies/cross-engine/warm/results/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json`, Git blob `a809f0362553e4e5c93ac1593ef478e8eef6a865`, configuration `c4083f1e-4ce2-4477-b282-04c4d40b187f`, run `f2df1d40-2eee-4fcb-9593-ba8433e08c4a`, arm `Q`, measured source `256501f0e700ed199f316e79d128389375177530`, mode `historical-absolute-unpaired`.
- Workload is the existing 16-lane warm exact-keyword matrix: sizes `[10000,100000]`, classes `absent,rare,medium,common`, `top_k [10,100]`, `timed_operation exact-term-search-plus-topk-projection`.
- Frozen policy: 12 blocks, **1** slot per arm, 5 warmups, 20 samples, seed `20261122`, 4 minimum retained blocks, B/B stability bound 15%. Staging builds exactly one B release executable from a detached worktree of the pinned commit and indexes 10K/100K locally. No A, Tantivy, Lucene, RustFS or profiler work occurs.

The measured historical A source is `256501f0…`, **not** the later pre-PERF-05 `main` base `9775bfca…`; both identities are distinct and must not be conflated.

## PERF-06 A-series paired warm family

`perf-06/warm` is the **paired** cumulative A-series qualification family added by PERF-06-A4. It reuses the accepted `perf-02` two-pinned-arm operational shape and adds no new configuration field, workload, estimator or CLI verb.

- `family` is exactly `perf-06`; only `warm` is supported. Exactly two arms are required: `A` and `B`, each `{"engine":"quervant","mode":"by-top-k","source":"pinned","revision":"<40-hex commit>"}`.
- The CLI accepts revisions only via `quervant-bench prepare --family perf-06 … --baseline-revision <40-hex> --candidate-revision <40-hex>`. A missing revision, a branch name, an uppercase or partial SHA, a `current` source, a non-Quervant engine, a non-`by-top-k` mode or `--quervant-revision` is rejected. `baseline` is `A`; `control` is `{"enabled":true,"baseline":"AA","equivalent":"AA2"}`; `build` is release/locked with `baseline_ref` null, `prefilter_profile` `P2` and `quervant_feature` null.
- Workload and policy are the existing 16-lane warm matrix: sizes `[10000,100000]`, classes `absent,rare,medium,common`, `top_k [10,100]`, `timed_operation exact-term-search-plus-topk-projection`, 12 blocks, **2** slots per arm, 5 warmups, 20 samples, `bootstrap_resamples` 10000, seed `20261122`, 4 minimum retained blocks, A/A stability bound 15%, empty `exclude_blocks` and empty `control_arms` in the saved configuration.
- Each arm is built and indexed independently from its own pinned commit; index bytes and index/commit/reopen durations differ legitimately between arms and are descriptive writer-side metrics, never warm query timings.
- The saved `perf-06` configuration pins the *source* commits under `arms.A.revision`/`arms.B.revision`; the A4 framework commit that registers the family is not an arm. Do not substitute `HEAD` or a historical unpaired study for either arm.
- Decision thresholds for a PERF-06-A4 campaign live in the approved plan and review report, not in `policy`. `policy.min_gain_percent`/`max_regression_percent` remain the framework defaults; the four primary and twelve guard lanes are classified during read-only review of a saved result. A `COMPLETE` status is never an adoption decision.
