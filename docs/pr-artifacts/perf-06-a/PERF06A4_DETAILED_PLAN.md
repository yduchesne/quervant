# PERF-06-A4 — Consolidated A-Series Correctness and Qualified Warm-Query Comparison

**Prescriptive coding-agent execution plan — for maintainer approval before execution**

- **Repository:** `yduchesne/quervant`
- **Milestone:** `v0.1-perf`
- **Series:** PERF-06-A, stages A1 → A2 → A3 → **A4**
- **Planned separate draft PR:** `PERF-06-A4: Consolidated correctness and paired warm qualification`
- **Planned branch:** `dev/perf06-a4-warm-qualification`
- **Source inspected:** merged `main@b70f624fffe0329def62701b61e997c4e303e167` on 2026-11-23 UTC/Pacific-local November 23
- **Protected source identities:** A (pre-A1 accepted PERF-05 baseline) `2a74017958c8ac61948f931e8745bf8134827025`; B (merged A1+A2+A3) `b70f624fffe0329def62701b61e997c4e303e167`
- **Preceding merges:** A1 PR #120 → `20134359c9a2c4257488357eb52e02f5317627d0`; A2 PR #121 → `668a58372a514cef4896ea595b0d96d1a3cecb85`; A3 PR #122 → `b70f624fffe0329def62701b61e997c4e303e167`
- **Source authority:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md`, `docs/BENCHMARKING.md`, `docs/BENCHMARK_CONFIGURATION.md`, `docs/BENCHMARK_RESULT.md`, `benchmarks/BM10_README.md`, `AGENTS.md`, `docs/TESTING.md`
- **A4 nature:** Qualification, evidence and a *bounded study-family registration*; **no new engine optimization**. **No automatic merge or B1 start**.

---

## 0. Executive execution contract and explicit study authorization

> **Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

**Important study-method approval.** The permanent PERF-06 roadmap prefers *B-only against a qualified, immutable historical A* **only when comparability has actually been proven**. That is **not pre-established here**: the historical PERF-05-C B result measured `ee18ed63bbeeb54b544393ee0f676987ff9987d1`, not the chosen accepted pre-A1 A SHA, and A3 intentionally changed the persisted postings representation. A historical ratio would be **between sessions, unpaired**, and cannot qualify a new causal result with paired confidence intervals. Instead, **this plan explicitly selects and prescribes one separately authorized same-session, two-revision A/B comparison**, using BM-10's existing prospective paired machinery. **Human approval of this complete A4 plan is the explicit additional methodology/acquisition authorization** required by the PERF-06 roadmap; without approval, do only read-only planning and STOP **before coding or acquisition**. Do not silently switch to a B-only campaign.

**One-authorization limit:** Upon approval, perform **one** actual A/A-control + A/B-treatment `run` only, after all source and host gates pass. A failed or inconclusive run is preserved and **does not authorize a second run**. `stage` is *untimed preparation*, not a second acquisition; normal pre-acquisition cache verification is permitted. No clock-based query experiments, profiling, Criterion, RustFS startup, Lucene, Tantivy, process-cold series, throughput study, OS-cache flushing, host swapping, threshold tuning, source retargeting, or unapproved rerun.

**Do not redesign:** Code must be restricted to a small `perf-06` study-family registration that delegates to the already implemented `perf-02` two-pinned-arm paired A/B path. Do not copy/fork a runner or change the statistics algorithm, adapter protocol, workload generator, production engine, source revision or disk codec.

**Exit:** Preserve every result including `INCOMPLETE`, give a scientifically honest qualification outcome, push one independently reviewable A4 PR, then STOP. A successful numerical outcome is **not** an automatic adoption/merge. A4 must not call the already merged A3 a completed *qualified performance win* until this campaign's correctness and qualified effect meet the stated gates and a human accepts it.

## 1. Current-main facts and in-progress reconciliation

### 1.1 Actual source state (not inferred from roadmap labels)

| Item | Actual verified source fact | A4 treatment |
|---|---|---|
| A1 | Merged query-local BM25 IDF preparation; exact scalar score bits were tested | Reuse; no scorer modifications |
| A2 | Merged consuming doc/frequency-only reader; full positional fields still validated | Reuse; no decoder API redesign |
| A3 | Merged `FEATURE_SPLIT_POSTINGS=0x000E/1`, split doc/freq/position streams, 128-doc block directory; legacy golden retained | Reuse; no format changes or skip-ahead logic |
| A3 CI | Final source head `86816673fd50b8a7560d9f3dac9042aec6c1f105` passed GitHub Rust CI run **#543**; PR #122 merged | Reuse as prior implementation acceptance, not proof of A4 benchmark |
| A3 review exception | Added feature assertion to `crates/quervant-core/tests/pr08_integration.rs`; maintainer explicitly authorized | Preserve; no new approval needed for that existing edit |
| Existing prospective study | `benchmarks/quervant_bench/lean/configuration.py` recognizes `perf-02` A/B; two independent pinned Quervant release builds, default P2, warm 16 lanes, A/A controls | Reuse behavior unchanged for `perf-06` |
| Existing B-only study | `perf-05` uses B/B aliases + historical descriptive, not paired A/B | Historical reference only; do not select it |
| Persisted study families | `artifacts.STUDY_REGIMES` contains `retained-key`, `cross-engine`, `perf-02`, `perf-05` | Add `perf-06: ("warm",)` — nothing else |
| Analyzer | `statistics.schedule` randomized, position-balanced; `statistics.analyze` paired block-ratio median and 10,000 whole-block bootstrap draws | Call unchanged; do not implement another estimator |
| Runner | `runtime.run_benchmark` stages, controls, treatment and publishes immutable result automatically; special-case only `perf-05` | Generic normal path applies to `perf-06` |
| Prepared inputs | `preparation.stage_inputs` builds, commits and reopens **two separate indexes** for A/B, verifies 16 untimed oracles, fingerprints source/toolchain/index | Reuse unchanged |
| All A1–A3 accepted | `main` == A3 merge SHA when plan authored | Verify again immediately before branch creation |

**In-progress classification:** A1, A2, A3 = **DONE + independently reviewed/merged**, A3 actual CI = **PASS**. A4 has **NOT STARTED**: new family registration, new immutable config, new real campaign and new result. Historical PERF-05 measurement = DONE but **NOT an A4 acceptance artifact**. Do not repeat or rewrite any earlier work.

### 1.2 Mandatory source identity table

The agent must `git fetch origin main`, inspect GitHub PR merges (not branch labels), require clean worktree, and compare `git rev-parse HEAD:<path>` at accepted main against this expected table **before implementation**. An unexpected change is **D03 HARD STOP**, not an invitation to infer an equivalent design.

| Source path | Git blob SHA1 at authoring baseline |
|---|---|
| `benchmarks/quervant_bench/lean/artifacts.py` | `d0b284063c07f1ae145b49688b47d5601d4e4d86` |
| `benchmarks/quervant_bench/lean/configuration.py` | `e6f6be187a3de49d11645e4245249df48b2f1efc` |
| `benchmarks/quervant_bench/lean/cli.py` | `d044413e7b3773b7284afe0f8082c25a0d5d0580` |
| `benchmarks/quervant_bench/lean/runtime.py` | `d1f3d5bc831533c81098321a970e3505c489c52d` |
| `benchmarks/quervant_bench/lean/preparation.py` | `67c53b180cfacc7188cbb0b4498261be09590cb8` |
| `benchmarks/quervant_bench/lean/statistics.py` | `7854fb8035128e425d00e6f4ad192f20d7a6c718` |
| `benchmarks/quervant_bench/lean/tests/test_perf02.py` | `05b65822b7f3816614e953c469bfb48051716dc7` |
| `benchmarks/quervant_bench/lean/tests/test_study_layout.py` | `613ce7697760e078dc91e3f07bf1fe41797c9228` |
| `benchmarks/quervant_bench/lean/tests/test_preparation.py` | `70d8bc45cd7ac7e8833b96f64cfb58f6d390851e` |
| `docs/BENCHMARKING.md` | `d695a47e23ccbfabeb4b39a69aacd831eac62b08` |
| `docs/BENCHMARK_CONFIGURATION.md` | `9ebe6e90fd873297fae0bb4e1bd0e65a9dd3df60` |
| `docs/BENCHMARK_RESULT.md` | `1b4e44e700bc3f0760f4089ba170122d04026e2f` |
| `benchmarks/BM10_README.md` | `b53dd4837df1da63c0e24a8f40127fdfdba782d9` |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | `d7b3e9934bf5f9abdeb6bccc42a2dfde734593b8` |
| `.github/workflows/ci.yml` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` |

The approved benchmark comparison pins two *source commits*, not the A4 framework code commit: **arm A** `2a74017958c8ac61948f931e8745bf8134827025` (all PERF-05 engineering merged, before any A1–A3) and **arm B** `b70f624fffe0329def62701b61e997c4e303e167` (all A1–A3 merged). Verify both are reachable commit objects, that A is an ancestor of B, and no Rust source/disk-format changes are introduced on the A4 branch. **Do not substitute latest HEAD** or old PERF-05-C `ee18…` as an arm.

## 2. Frozen qualification architecture and physical workload

### 2.1 Why paired A/B, and what it can establish

- A3's new disk layout is a **deliberate treatment characteristic**. Each independently pinned executable builds and reads its own index with the **same deterministic logical corpus**. Index-byte differences are expected and are recorded **separately**, never inserted into warm latency.
- A and B must match **query semantics**, actual result order, total hits, response materialization, schema, P2 production strategy, warm timed boundary and oracle; they need **not** share an on-disk format or physical index digest. Do not force the B reader to open A's index or invent a cross-version write migration.
- This is a **within-session, two-implementation treatment comparison** with A/A controls and paired block bootstrap CI; it is stronger for A4 than a cross-day unmatched historical ratio. The combined difference can include A1, A2 and A3, compiler-optimized consequences and changed physical layouts. It does **not** attribute latency to one of A1/A2/A3 individually; do not claim an isolated speedup for any stage.
- Do not compare treatment data to the older 2026-11-22 cross-engine Q result or the 2026-11-23 PERF-05 B-only result as if matched/paired. Those are retained contextual history only. A/B treatment baseline is A's **newly acquired same-session** observations.
- **Study family:** register one new **`perf-06/warm`** family, reuse `perf-02` operational behavior via case inclusion, not a new runner. Do not store an A4 result in the misleading `perf-02/warm` directory. The family is available for future B4/C4 work **only after separately approved plans**; A4 creates no future configurations.

### 2.2 Exact immutable configuration contract

Use the existing `prepare` CLI to create **one** canonical configuration:

```text
benchmarks/studies/perf-06/warm/configurations/
  quervant-perf06a-paired-warm-<UTC-CREATION-DATE>.json
```

**Fixed identity fields** (normal creator supplies `schema`, fresh UUID `configuration_id`, `created_utc` and canonical filename; DO NOT hand-author IDs):

```json
{
  "family": "perf-06",
  "name": "quervant-perf06a-paired-warm",
  "baseline": "A",
  "arms": {
    "A": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": "2a74017958c8ac61948f931e8745bf8134827025"},
    "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": "b70f624fffe0329def62701b61e997c4e303e167"}
  },
  "control": {"enabled": true, "baseline": "AA", "equivalent": "AA2"},
  "build": {"release": true, "locked": true, "baseline_ref": null, "prefilter_profile": "P2", "quervant_feature": null},
  "workload": {
    "id": "pr15d-exact-keyword-v1",
    "sizes": [10000, 100000],
    "classes": ["absent", "rare", "medium", "common"],
    "top_k": [10, 100],
    "regimes": ["warm"],
    "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
    "timed_operation": "exact-term-search-plus-topk-projection"
  },
  "policy": {
    "blocks": 12,
    "slots_per_arm": 2,
    "warmups": 5,
    "samples": 20,
    "bootstrap_resamples": 10000,
    "seed": 20261122,
    "min_blocks": 4,
    "min_gain_percent": 0,
    "max_regression_percent": 0,
    "max_aa_gain_percent": 15,
    "exclude_blocks": {},
    "control_arms": [],
    "readiness": {"intervals": 4, "interval_ms": 250, "max_busy_percent": 25, "max_steal_percent": 2}
  }
}
```

The CLI's generated `description` must be exactly:
`PERF-06-A4 cumulative A1-A3 paired warm qualification against accepted pre-A1 PERF-05 source; independent indexes, query-only timing`.

**Do not edit** any generated configuration after the first result has been published. If a code-independent human-readable correction would materially change the experiment, STOP and request a newly named configuration/approval; do not overwrite or reuse the UUID. All file dates use UTC, not local Pacific calendar dates.

### 2.3 Schedule, controls and sample arithmetic

- **16 lanes:** both sizes × absent/rare/medium/common × K10/K100, all warm, every lane measured in both arms. The exact classes/terms come from `configuration.CLASSES`, not agent-generated terms.
- **Two independent release binaries** and **two independently built, committed, reopened index directories per size**. A and B must have distinct executable, index and source-worktree paths. Build **without** `quervant-core/pr15i-d3c-experiment` or any other experimental feature. Both use production-default P2 prefilter behavior.
- **Control:** 12 balanced blocks × 2 labels (`AA`, `AA2`) × 2 slots per label = **48 control slots** × 16 lanes = **768 control slot/lane records**. Both aliases point to **A's exact executable and existing A index**, not to B. 5 warmups + 20 measured observations per lane and slot.
- **Treatment:** 12 balanced blocks × 2 arms (`A`, `B`) × 2 slots per arm = **48 treatment slots** × 16 lanes = **768 treatment slot/lane records**. Same warmups and samples.
- **Total:** 1,536 slot/lane records; **7,680 untimed warmup requests** plus **30,720 timed requests**, always using the query adapter's reported `engine_ns`. This excludes separate untimed stage oracles and readiness checks. Do not shorten or augment the schedule because timing is slow.
- Existing `statistics.schedule` supplies exact randomized cyclic/position balance. No manual pairing of samples, missing-block pruning, unfavorable-block exclusions or manual reruns.
- **Control pass:** each of the 16 `controls.analysis.lanes[id].comparisons.AA2.status` must be `PASS` under the frozen ±15% signed-gain *and confidence-interval* test. If any fails: `INCOMPLETE`, preserve result and **STOP; no treatment attempt/retry**.
- **Treatment estimator:** for each arm/block, mean of two slot medians; 12 paired B/A block ratios; median ratio; deterministic 10,000-resample whole-block bootstrap, `gain_percent=100*(1-B/A)` and signed 95% CI. Do not implement another estimator. A/A and A/B are different phases, never pooled.
- Every warmup/sample response is independently checked for exact `total_hits` and ordered logical document IDs. Engine timing excludes adapter reader opening, index build/commit, process startup and JSONL transport, but includes query and mandatory Top-K/projection work.

### 2.4 Frozen lane-by-lane decision contract

Declare **before** any timed acquisition:

| Lane category | IDs | Decision gate |
|---|---|---|
| **PRIMARY** (4) | `100000/medium/k10/warm`, `100000/medium/k100/warm`, `100000/common/k10/warm`, `100000/common/k100/warm` | Each requires treatment `comparisons.B.status == "IMPROVED"`, median gain **>=5.0%**, and bootstrap 95% gain CI **lower bound >0.0%** |
| **GUARD** (12) | All other lanes: every 10K lane plus 100K absent/rare K10/K100 | Each requires median gain **>=-10.0%** and 95% gain CI **lower bound >=-10.0%**. An unqualified/uncomputed comparison never passes by default |

**Quality prerequisites before interpreting any lane:** exact A/B source identities; matching workload/query semantics; two real independently built indexes/size; full 16-lane untimed oracles; 16/16 A/A `PASS`; readiness checks all `clear`; 16×12 unpruned paired blocks; every raw sample finite/positive and oracle-verified; result `status == "COMPLETE"`; 16 analyzable B comparisons with neither `NON_COMPARABLE` nor `NOT_COMPUTABLE`; complete provenance and no source edit after timed acquisition.

Classify outcomes, not just Python exit code:

1. `PERF06_A4_PAIRED_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED` **only** when all prerequisites, all 4 primary and all 12 guard lane rules pass. Not a merge authorization.
2. `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED` when the run is statistically/structurally valid and `COMPLETE`, but one or more thresholds fail. Preserve all lanes, identify them, do not rerun or automatically revert already merged A3. Ask maintainer whether to adopt/iterate/replan; **do not mark A accepted**.
3. `PERF06_A4_PAIRED_INCONCLUSIVE_REVIEW_REQUIRED` when run is structurally `COMPLETE` but at least one mandatory comparison is inconclusive/uncomputable or required uncertainty cannot be interpreted. Retain full source and CI evidence; no adoption.
4. `PERF06_A4_INCOMPLETE_STOP` for any failed control/readiness/oracle, misidentified source/build/index, interrupted or truncated sample series, invalid result publication, or missing mandatory integration/QA. Preserve partial result and **do not rerun**.
5. `PERF06_A4_NOT_ACQUIRED_DEPENDENCY_BLOCKED` when source, framework or host preflight fails **before** any timed run; no fabricated result or acquisition claim.

**A4 does not assert that any primary lane improves.** Pre-declaring a threshold does not predict a favorable observation. Structural index byte-size increases are expected and must be included as separate descriptive index metrics, not treated as warm latency or silently hidden.

## 3. Correctness contract and evidence matrix

### 3.1 Falsifiable invariants with named witnesses

| ID | Invariant | Required proof and negative/counterexample |
|---|---|---|
| A4-INV01 | A1–A3 accepted baseline matches pinned `main`; A source predates A1 and B includes all three | PR #120/#121/#122 merge verification + Git object-tree/ancestor proof; stop on mismatch |
| A4-INV02 | A4 changes no production Rust engine, persisted format or reader/searcher behavior | `git diff --name-only` and exact Rust blob checks; stop if any `crates/**` production file changes |
| A4-INV03 | Study `perf-06` is a **new family name only**, delegating to existing `perf-02` pinned A/B semantics | U01/U02 configuration equivalence vs PERF-02 except family; U03 wrong-family/path/revision rejection |
| A4-INV04 | A and B are separately compiled pinned sources with feature disabled and distinct physical indexes | U04 mock build/worktree behavior + real `stage` provenance/fingerprint/index checks; reject same binary/source unexpectedly |
| A4-INV05 | Query materialization/order and all 16 independent hit oracles agree in both arms | `stage` preflight; existing A3 I02, A2 I02, A1 bit-parity suites; U05 simulated bad oracle fails before timing |
| A4-INV06 | Legacy and split postings remain readable; phrase and error/cancellation/position validation are not weakened | existing `segment_golden`, `segment_codec`, A3 U01–U12, A2 U01–U10, `pr07_properties`, `pr13_remote` accepted A3 gate |
| A4-INV07 | Warm index build, commit and reader open are excluded from engine time | Existing `stage` + `runtime.collect_slot` source boundary; U06 verifies stage has no timed `run`/result |
| A4-INV08 | Control is an A/A comparison of **identical A**, never A/B | U07 mock alias paths/schedule and control rejection; exact 768 control records, 16 PASS required |
| A4-INV09 | Treatment is balanced and paired, with correct 12-block CI and no pruning | U08 complete/mock and missing/duplicated/biased block negative; exact 768 treatment records |
| A4-INV10 | Source/result files are immutable, dated, unique, non-overwriting and correctly routed | U09 family paths, collision/misroute, `_publish_exclusive`; real generated UTC config/result path and IDs |
| A4-INV11 | All adverse / incomplete attempts remain visible; no automatic retry, altered thresholds or selective block deletion | U10 mock incomplete publication, test timeout/cancel; manual actual run count exactly one |
| A4-INV12 | Result `COMPLETE` is not equivalent to an accepted speedup | U11 pure decision table for PRIMARY/GUARD cases; review report rechecks all 16 without rewriting raw result |
| A4-INV13 | No false causal attribution across A1/A2/A3; no historical-unpaired result misrepresented as paired | Report includes chosen A/B source, format differences, paired CI, and explicit exclusions |
| A4-INV14 | A4 local Rust/Python gates and CI are independently evidenced; no conflation with A3 success | Exact command log, measured coverage, CI on A4 framework source; A3 CI #543 separately labeled |

### 3.2 Pre-implementation adversarial challenge (mandatory before edits)

Before modifying the benchmark framework, the agent must write the matrix above and attempt to falsify it using these specific counterexamples: two arms with same source (smoke only); B SHA not a commit; source A or B absent locally; `perf-06/process-cold`; a `perf-06` result in `perf-02/results`; uncommitted benchmark source; stale/tampered staged binary or index; new split segment different index byte size; A/A single lane unstable; B missing one block; B wrong ordered doc IDs; same lane omitted from only one arm; all-fast B but missing full-source provenance; a valid `COMPLETE` result with negative guard; incomplete result with apparently good primary medians; UTC date boundary; collision of result suffix; no host/affinity readiness. Apply §10 matrix, do **not** invent alternative requirements.

### 3.3 Cross-component impact, ownership and failure table

| Boundary | Change permitted? | Required behavior / error consequence |
|---|---|---|
| Rust BM25, positional decoder, builder, writer, index, mutation, PIT, source adapters | **NO** | Exact A1–A3 bits/identity maintained; source diff violation HARD STOP |
| Python `artifacts.py` | **YES: one family entry** | `perf-06` only `warm`; no rerouting/misrouting; collision and exclusive publication unchanged |
| Python `configuration.py` | **YES: include `perf-06` in pinned A/B checks** | Exactly 2 pinned Quervant arms; cold/revision/feature errors typed as `ArtifactError` |
| Python `cli.py` | **YES: family choice/help text** | Existing prepare/validate/stage/run/report verbs; no new acquisition command |
| Python `preparation.py` | **YES: pinned revision source-identity branch** | Verify exact A/B commit types and separate artifacts; stage once and fingerprint |
| Python `runtime.py` | **YES: one condition group** | Reuse `perf-02` detached worktrees/independent builds; no change to `_phase`, `collect_slot`, `statistics` |
| Python `statistics.py`, `perf05.py`, `reporting.py` | **NO** | Existing estimator and B-only history remain unchanged |
| Config/result JSON | **NEW FILES ONLY** | Unique UUIDs, UTC names, no overwrite; results survive failure |
| RustFS/ObjectStore | **NO A4 implementation change** | A3 accepted real RustFS CI evidence reused; no new service needed for benchmark |
| CPU host readiness | **Existing** | Failure means no qualified run; preserve measured data if acquisition already began |
| Git commit/push | **New A4 branch only** | Normal pushes, no force, no existing PR rewrite |

**Failure precedence:** source/Git identity → configuration/schema/policy → stage compilation+commit+reopen → untimed oracle in both arms → host readiness → A/A acquisition+analysis+16 PASS → treatment readiness → treatment acquisition+analysis → post-readiness → exclusive result save → outcome classification. A late failure must not erase earlier legitimate raw results. Any candidate `SearchError`/corruption/incorrect ordered keys is a correctness failure, not a slow sample. A/A instability is **NOT** an authorization to retry, prune or change CPU.

**State, durability and concurrency:** Inputs and outputs are immutable committed snapshots and local scratch indexes. Each independent source build owns its detached worktree/target; `preparation` owns disposable caches under `target/bm10/prepared`. The result publisher exclusively creates a new JSON file in its canonical Git-trackable directory, with atomic/non-overwriting sequence allocation. No change to production `CURRENT`, manifests, live snapshots, RustFS objects, locking, or read caches; no durable data migration. Existing staging locks and fingerprints remain authoritative. A controlled test should prove a damaged cache fails closed. Unexpected pre-existing concurrent benchmark acquisition means fail readiness/lock and STOP; don't kill unrelated processes.

## 4. Exact bounded implementation design — framework registration only

**All changes below are *narrow, mechanical* additions using the already implemented PERF-02 implementation. No design option is delegated.** Match the anchors in §1.2 first.

### S1 — `benchmarks/quervant_bench/lean/artifacts.py`

At the module-level `STUDY_REGIMES` mapping add exactly `"perf-06": ("warm",)` alongside existing families. Do not modify the generated config/result filename regex, collision handler, `_lock`, `_publish_exclusive`, schema version or any storage code. This provides the permanent `studies/perf-06/warm/{configurations,results}` route.

### S2 — `benchmarks/quervant_bench/lean/configuration.py`

Treat `perf-06` as a **two-arm pinned production-default** sibling of `perf-02` (not PERF-05) at every existing branch:

1. Expand valid family list and corresponding error-message text to include `perf-06`.
2. `baseline_revision`/`candidate_revision` allowed **only** when `family in ("perf-02", "perf-06")`. Correct the old guard that currently loosely mentions `perf-05` in that set; keep the specialized `perf-05` one-arm `quervant_revision` path unchanged. If a revision flag is passed for `retained-key`, `cross-engine` or `perf-05`, reject in the existing way.
3. Arm construction `elif family == "perf-02":` → `elif family in ("perf-02", "perf-06"):`; make the same two pinned Quervant `A/B` arm records and `top_k=list(K_CROSS)`.
4. Baseline `A`, control aliases `AA`/`AA2`, release/locked, `baseline_ref=None`, `prefilter_profile="P2"`, `quervant_feature=None` — unchanged existing default A/B policy. No new parameter, custom source mode or fallback to `HEAD`.
5. Validation: `expected_arms={A,B}`, engines Quervant, mode `by-top-k`, `source="pinned"`, full lowercase 40-hex Git revisions and `warm` only; include `perf-06` wherever current `perf-02` has these branches. Update the `baseline_ref`-null rule as well. Existing cold study remains cross-engine-only. Keep all 16 warm lanes and original policy validation.
6. Preserve `family == "perf-05"` historical reference and B/B schedule **byte-for-byte in effect**; do not remove any current family or relax a policy check.

**Expected result:** `default_configuration("perf-06", ..., baseline_revision=A_SHA, candidate_revision=B_SHA)` has the same mathematical/query/build/control shape as `perf-02` except the family and newly allocated UUID/name/description/timestamp. Its validator rejects a bare branch name or a missing pinned SHA. Never introduce `perf-06`-specific statistics functions.

### S3 — `benchmarks/quervant_bench/lean/cli.py`

Add `"perf-06"` to `prepare --family` choices; update the two revision-argument help strings from “for perf-02” to “for perf-02/perf-06”; update regime help to include perf-06 warm only. `prepare` still delegates to `configuration.prepare_configuration`; other verbs unchanged. No CLI `--benchmark-now`, `--retry`, `--ignore-control`, `--skip-readiness`, historical-reference flag or new root override.

### S4 — `benchmarks/quervant_bench/lean/preparation.py`

In `source_identity`, use `if config["family"] in ("perf-02", "perf-05", "perf-06"):` with `arm_ids=("A","B")` when family is `perf-02` **or** `perf-06`, else `("B",)` for PERF-05. Keep `git cat-file -t` commit validation, `SOURCE_PATHS` tree identity, toolchain/environment fingerprint, worktree-clean and cache verification unchanged. Never special-case A3's larger index size as a cache validity failure: compare each index to **its own** preserved fingerprint, not A to B.

### S5 — `benchmarks/quervant_bench/lean/runtime.py`

In `build_programs` only, modify `if family == "perf-02":` → `if family in ("perf-02", "perf-06"):`. Reuse *the same exact* `for arm_id, revision` loop, detached `source-a`/`source-b` Git worktrees, distinct release targets `build/quervant-a`, `build/quervant-b`, `--release --locked` compile, feature `False`, cleanup in `finally`, and return `arm_source_revisions={"A": A_SHA,"B": B_SHA}`. Do **not** edit `run_benchmark`, `_control_config`, `_phase`, `collect_slot`, `statistics.analyze`, `create_corpus`, `build_index`, adapter JSONL, clock, CPU-affinity or slot scheduler: all generic behavior already applies to the new family.

**Do not** change how the explicit `perf-05` B-only acquisition works. It must continue to take its fixed historical A source and one B release binary; no `perf-06` branch in `_run_benchmark_perf05`.

### S6 — Bounded deterministic/mock Python tests (write RED first)

Create **one** new `benchmarks/quervant_bench/lean/tests/test_perf06a.py` (no dependencies) by borrowing only the established fixtures and test strategies from `test_perf02.py`, `test_preparation.py`, and `test_study_layout.py` (do not copy the whole test suite). Use synthetic 40-character lowercase hashes `"a"*40`, `"b"*40`, synthetic `tmp_path`, `monkeypatch`, and `CompletedProcess`; **never execute production adapters in tests**.

| ID | Required test name | Exact assertions (RED against missing family, GREEN after S1–S5) |
|---|---|---|
| U01 | `test_a4_u01_perf06_config_is_exact_paired_pinned_warm` | `default_configuration` supports family, A/B revisions, 16 warm lanes, profile P2 and no experiment feature; only family differs from paired PERF-02 source shape |
| U02 | `test_a4_u02_validator_rejects_unpinned_and_wrong_regime` | Missing A/B, 39-char SHA, uppercase, branch name, `source=current`, wrong engine, `mode=prefilter`, extra arm, `process-cold`, incorrect control and feature all reject |
| U03 | `test_a4_u03_study_path_identity_and_nonoverwriting_results` | Config path `perf-06/warm/configurations`; result sibling `perf-06/warm/results`; wrong study path rejects; duplicate configuration name/UUID collision and result sequence 001/002 never overwrite |
| U04 | `test_a4_u04_two_isolated_pinned_release_builds` | Monkeypatch `_run`, `_build_rust`, `_git`; two separate detached worktrees/build directories; both feature=False; proper worktree removal even if B compile fails |
| U05 | `test_a4_u05_stage_oracles_cover_both_real_roles` | Fake builders/corpus and oracle outputs; both A and B required for 10K and 100K and all 16 lanes; a deliberately wrong ordered key in B is rejected before any timed phase |
| U06 | `test_a4_u06_stage_no_timing_then_cache_hit_and_tamper_stop` | Stage run builds two indexes and no result JSON/slot calls; reuse HIT with fingerprints/oracles; changed B binary/index fails validation without timing |
| U07 | `test_a4_u07_aa_control_aliases_use_only_a` | `_control_config` emits AA/AA2 from A, fixed seed/slots; mock captures same binary/index for both aliases; 16 stable A/A comparisons PASS; noise beyond frozen bound blocks treatment |
| U08 | `test_a4_u08_paired_treatment_and_invalid_schedule` | Mocked 12×2×2×16 rows / samples, lane B change; paired stats produce expected outcomes/CI, wrong block/missing sample/misassigned position rejected; no pair formed from historical A JSON |
| U09 | `test_a4_u09_incomplete_control_publishes_unmodified_result` | Inject deterministic A/A fail; `run_benchmark` publishes one INCOMPLETE JSON with control raw data, no treatment data and no auto retry |
| U10 | `test_a4_u10_good_complete_result_is_not_approval` | Pure test-only helper in **test file**, not production, implements §2.4 classification (all primary >=5 and CI>0; all guards <=10); `COMPLETE` with one guard -10.01 or weak primary classifies NOT_MET; malformed/missing CI INCONCLUSIVE |
| U11 | `test_a4_u11_existing_perf02_and_perf05_behavior_unchanged` | Validate existing unchanged `perf-02` pinned A/B, `perf-05` B-only immutable historic and unsupported cross-engine revision behavior; no mixed family identity |
| U12 | `test_a4_u12_cli_prepare_validation_and_date` | CLI `prepare --family perf-06 --baseline-revision ... --candidate-revision ...` creates exactly one valid file at generated UTC date, `validate` says VALID; invalid flags don't create artifacts |

For pure decision classification U10: implement an isolated **test-only** helper from the frozen §2.4 table; the real report may use identical field checks against saved JSON, not a new production analysis module. Ensure tests prove `status=COMPLETE` with `REGRESSED` guard **does not** mean targets met.

**No modifications to** `statistics.py`, `reporting.py`, `perf05.py` or `test_perf02.py` are authorized. If a mechanical test-discovery/fixture issue arises, apply D19/D22; if a new framework algorithm is required, HARD STOP.

### S7 — Permanent reference documentation (bounded)

Update exactly these documentation files, without changing unrelated historical verdicts:

- `docs/BENCHMARKING.md`: supported study hierarchy adds `perf-06/warm` as Quervant paired cumulative architectural qualification; clarify PERF-05 historical B-only remains historical, and A4's paired A/B is specifically preapproved because A3 changes format/baseline provenance; preserve UTC naming, timing and controls.
- `docs/BENCHMARK_CONFIGURATION.md`: update supported-family lists/tables and CLI semantics for two pinned revisions and `perf-06` 16-lane warm only, with profile P2/no experimental feature.
- `docs/BENCHMARK_RESULT.md`: add `perf-06/warm` allowed result route and clarify it uses existing `bm10-analysis-v1` paired bootstrap; no new result schema; retain immutability and no false historical pairing.
- `benchmarks/BM10_README.md`: add **operator** commands for `perf-06` prepare/validate/stage/run/report and explicit distinction between stage-only and one authorized real run. Reference this detailed plan, do not hardcode future UTC filenames.
- `docs/pr-artifacts/perf-06-a/PERF06A4_DETAILED_PLAN.md`: copy the entire approved plan, unchanged.
- `docs/pr-artifacts/perf-06-a/PERF06A4_EXECUTION_REPORT.md`: new, cumulative correctness matrix, framework/host evidence, gates, source identity, actual result path/status, measurement interpretation, human decision required.

Do **not** update `docs/PERF_OPTIMIZATION_ROADMAP.md` to mark A complete until campaign and independent acceptance are actually complete. Do not mark B1 ready before A4 has been reviewed and accepted.

## 5. Exact execution phases, no coding-agent choice

### P0 — Verify and capture accepted baseline, STOP on divergence

From an idle development checkout on the intended benchmark host (no need to start RustFS):

```bash
set -euo pipefail
git fetch origin main
git switch main
git pull --ff-only origin main
test "$(git rev-parse HEAD)" = "b70f624fffe0329def62701b61e997c4e303e167"
git status --porcelain=v1 --untracked-files=all
# Require no untracked/source modifications. Ignored target/ artifacts may remain.
git cat-file -t 2a74017958c8ac61948f931e8745bf8134827025
git cat-file -t b70f624fffe0329def62701b61e997c4e303e167
git merge-base --is-ancestor 2a74017958c8ac61948f931e8745bf8134827025 b70f624fffe0329def62701b61e997c4e303e167
```

`git status` output must be empty unless there is a specifically isolated, already ignored build directory. Verify PR #120, #121, #122 all `MERGED`, exact merger SHAs, and A3 successful CI #543; compare source blob table. Check no existing `dev/perf06-a4-warm-qualification` local/remote branch and no other open PERF-06-A4 PR before `git switch -c ...`; if one exists, **D04 HARD STOP** rather than resetting it. Record main/base SHA, toolchain IDs, host platform, compiler/toolchain, source/workload tree hashes and accepted existing A3 CI proof.

### P1 — Test-first family registration (untimed)

1. Create A4 branch at exact accepted `main`.
2. Implement test file U01/U02/U03/U04/U07 first and run `PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests/test_perf06a.py`; expected RED solely from unsupported `perf-06` family. Capture errors in execution report. A pre-existing unexpected error is not RED evidence.
3. Add remaining U05–U12. Apply S1–S5 exactly, one file at a time; make tests pass. Run existing `test_perf02.py`, `test_perf05.py`, `test_study_layout.py`, `test_preparation.py` as regression.
4. Implement S7 docs. Run Python QA and full Rust QA for this **code-bearing** A4 framework change as prescribed below. No timed query or host benchmark while source or tests are changing.

### P2 — Full correctness, QA, and source review before any acquisition

**Run from workspace root, on final framework source and tests**:

```bash
PYTHONPATH=benchmarks python -m compileall -q benchmarks/quervant_bench
PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests
PYTHONPATH=benchmarks python -m coverage run --branch --source=quervant_bench.lean -m pytest -q benchmarks/quervant_bench/lean/tests
PYTHONPATH=benchmarks python -m coverage report --fail-under=85
bash benchmarks/scripts/test-scripts.sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --fail-under-lines 85
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --no-deps
cargo doc --workspace --all-features --no-deps
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
git diff --check
```

Install Python benchmark dependencies only if missing, using project's **existing** `benchmarks/pyproject.toml` (`python -m pip install -e ./benchmarks pytest coverage`), record versions; do not change manifests or install service packages. The repository's exact Rust coverage 85% floor is mandatory even though the engine is unmodified. Relevant existing integration/negative suites must be identified and executed as part of the workspace run: A1 exact BM25 parity, A2 lean/full errors/charges, A3 split/legacy codec U01–U12, real FsDirectory writer→commit→reopen, `pr07_properties`, `segment_golden`, `pr15i_d2a_scoring_contract`, `pr13_remote` fake remote and prior accepted real RustFS CI proof. Do **not** run ignored RustFS tests without the actual pinned service topology, and do not substitute fake remote for real A3 acceptance. No test results may be fabricated from source inspection.

**Mandatory report:** command; real PASS/FAIL/BLOCKED; actual test count; actual Rust workspace line coverage and Python branch coverage; toolchain versions; affected-file coverage; ignored counts; host integration topology; any unresolved errors. Do not modify thresholds, ignore tests or artificially exclude code to make gates pass. After any test/source change, rerun every affected mandatory local gate and coverage. Existing accepted A3 RustFS CI #543 is evidence of prior feature acceptance, **not** new A4 source CI.

### P3 — Commit/push framework and obtain CI (no timing)

Create `docs/pr-artifacts/perf-06-a/PERF06A4_EXECUTION_REPORT.md` with initial sections and `NOT_ACQUIRED` status. Commit **only** S1–S7 implementation/test/docs files, push this new branch normally, and open one **draft** PR targeting `main`. Verify remote SHA equals local HEAD and diff contains only the allowed files. Inspect actual hosted `python-benchmark-framework`, `rust`, `msrv`, `rustfs`, and `benchmark-adapter-contract` statuses for this exact code head. CI must be green before real acquisition; if unavailable, preserve code and STOP the timed part with a clear external-blocker state (you may continue read-only documentation/reporting). Do not modify source after this gate without a new full QA and new code-head CI pass.

### P4 — Freeze the one unique configuration and stage untimed inputs

**Only after P3 green on exact code source:** create a unique config with the existing CLI, from workspace root (the CLI chooses the UTC dated filename):

```bash
export PYTHONPATH=benchmarks
python -m quervant_bench prepare --family perf-06 --regime warm \
  --name quervant-perf06a-paired-warm \
  --description 'PERF-06-A4 cumulative A1-A3 paired warm qualification against accepted pre-A1 PERF-05 source; independent indexes, query-only timing' \
  --baseline-revision 2a74017958c8ac61948f931e8745bf8134827025 \
  --candidate-revision b70f624fffe0329def62701b61e997c4e303e167
# Capture the ONE exact path printed by prepare; do not use a glob.
export CONFIG='<EXACT-PRINTED-CONFIG-PATH>'
python -m quervant_bench validate --config "$CONFIG"
```

Read JSON and compare every field to §2.2, then commit **that single immutable new config** and push A4 branch. Wait for exact-source CI to be green (if configuration-only commit, CI's configuration validator is required; no need to repeat unchanged Rust QA). The config's UUID/date are generated normally; record them; do not hand-edit.

Now stage **once**:

```bash
python -m quervant_bench stage --config "$CONFIG"
```

`stage` must build both exact pinned release executables in isolated worktrees/targets, generate one deterministic corpus for each of 10K/100K, separately build/commit/reopen A and B indexes, prove independent oracle for **all 16 lanes in both arms**, fingerprint binaries and index files and print one cache key. Record `index_metrics` for A/B 10K/100K: `index_ns`, `commit_ns`, `reopen_ns`, `index_bytes`, source binary and SHA, compiler, host, cache status and verification. Index sizes **should differ** because A3 changed physical representation; compare logical correctness and per-arm self-fingerprints, not cross-arm byte equality. Staging may reuse an existing matching verified cache and is not a timed `run`. If staging fails due to a real source/index/oracle defect, STOP: no timed acquisition. Never weaken the oracle or switch baseline to make stage pass.

**Host:** require the benchmark runner's existing Linux/x86_64/native supported filesystem, physical-core/CPU-affinity and readiness checks; don't disable them or call `run_benchmark(..., check_host=False)` outside unit tests. Assume nothing about idleness except observed readiness. No repeated manual idle wait, no host/process killing, no auto-retry on failure. Do not start RustFS or use a network index.

### P5 — Exactly one A/A + A/B warm acquisition (approved plan only)

**Only after full P4 success and explicit human approval of this A4 plan**:

```bash
python -m quervant_bench run --config "$CONFIG"
```

The CLI automatically consumes the matching staged preparation after verifying it, checks readiness, performs complete A/A control, and (only if control PASS) complete A/B treatment; it writes a result JSON **even on INCOMPLETE** using the exclusive dated suffix. `RESULT_JSON=<path>` is the authority; capture the **actual printed path**. If CLI exit is 4, expect an `INCOMPLETE` result and stop any further acquisition. If process dies before result publication, preserve logs/scratch and report an unsaved blocked acquisition; never assert a result exists and never rerun without new human approval.

**Do not** call `run` twice, run `analyze` to override the published analysis, or add a second "confirmation" session. No pass based on an unpaired historical ratio or partial lane subset.

### P6 — Read-only result validation, classification and publication

Read saved JSON with `artifacts.load_result` and verify `configuration_id`, UUID, filename, sequence, UTC timestamp and embedded config. Require exact source provenance in `context.build.arm_source_revisions`, actual compiled options, feature disabled and correct A/B index metrics. Validate `controls.readiness_index_pre` (from stage), `readiness_pre`, `readiness_treatment`, `readiness_post` are all `clear` where applicable; do not interpret missing as clear. Require `controls.analysis` contains exactly 16 A/A PASS; `controls.raw_samples` exactly 768 and treatment `raw_samples` exactly 768 rows, with 20 positive ns samples and 5 warmups in every row, every `oracle_ok=True`, full declared seeded schedule, 16 result lanes, `excluded_blocks=[]`, `retained_blocks=12`, 12 paired ratios and 10,000 resamples per lane. Use `statistics.analyze` **only for read-only independent recomputation** if verification is warranted; never overwrite `analysis`, change policy or write another result.

Classify with §2.4 using the **published per-lane `comparisons.B`**. Exact reviewed decision code for the *report script only*, after confirming type/field presence (no new production module):

```python
primary = {
    "100000/medium/k10/warm", "100000/medium/k100/warm",
    "100000/common/k10/warm", "100000/common/k100/warm",
}
# For each of exactly 16 results, comp = result["analysis"]["lanes"][lane]["comparisons"]["B"]
# Require comp["kind"] == "treatment"; comp["gain_ci_95_percent"] is two finite numbers.
# primary passes iff comp["status"] == "IMPROVED", comp["gain_percent"] >= 5.0,
#                    and comp["gain_ci_95_percent"][0] > 0.0.
# guard passes iff comp["gain_percent"] >= -10.0
#                  and comp["gain_ci_95_percent"][0] >= -10.0,
#                  and comp["status"] is an actually computed treatment status.
# A missing/malformed field never defaults to zero or PASS.
```

Report every lane in a human-readable table: 12 paired block ratios, center B/A, 95% ratio CI, gain, 95% gain CI, analyzer status, PRIMARY/GUARD classification and pass/fail reason. Include A/B index sizes, ratio of index bytes and build/commit/reopen metrics as **descriptive writer-side diagnostics** (never mix with `engine_ns` warm performance). State that A1 vs A2 vs A3 contribution is not independently identified. State what was actually acquired, whether A/A and readiness passed, and whether final `COMPLETE` implies TARGETS_MET (it does not).

Run `python -m quervant_bench report --result "$RESULT_JSON"` for **read-only rendering**; no new statistics, no new timed query. Commit only the one new result JSON plus the evidence report (and optionally a human-readable `.md` report **under `docs/pr-artifacts/perf-06-a`**, not a third benchmark JSON artifact). Preserve the config/result identities and all original negative evidence. Use an ordinary push to the open draft A4 PR. Docs/result-only commits do not require rebuilding source or repeating Rust QA, but configuration validation, JSON parse, `git diff --check`, and exact artifact consistency remain mandatory. If any new source edit is needed, STOP and seek a separate bounded fixup before claiming measurements.

### P7 — Reviewer handoff / release boundary

The agent stops and reports one of §2.4 typed dispositions, source and branch/remote SHAs, actual CI on code head, stage input identities, unique config/result paths, A/A + primary/guard result tables, coverage, baseline differences, blocked gates and applied decision-matrix rules. PR stays **draft** until independent review. **Do not merge**, update milestone DONE, launch B1, delete failed artifacts, rerun the campaign or reconfigure the framework. A human reviews whether A qualifies as the accepted B1 source; A3 code is already merged and cannot be automatically reverted on an unfavorable A4 result.

## 6. Testing/integration and evidence specifics

| Gate ID | Test/topology | Evidence vs inherited work |
|---|---|---|
| T01 | A4 U01–U12 pure Python, mocked real CLI semantics | NEW feature-family gate; no production timings |
| T02 | Existing `test_perf02.py`, `test_perf05.py`, `test_study_layout.py`, `test_preparation.py` | Regression protects A/B, historical B-only, cache and naming |
| T03 | Python compileall, test suite, 85% branch coverage | NEW Python framework-source gate |
| T04 | All Rust stable/MSRV commands, 85% workspace line coverage | Inherited production QA; A4 modifies no Rust but repository gate remains binding |
| T05 | `pr07_properties`, `segment_codec`, `segment_golden`, `pr15i_d2a_scoring_contract`, A1–A3 unit tests, `pr13_remote` fake | Existing deterministic/adversarial production path with actual codecs |
| T06 | Accepted A3 RustFS real cold-reopen run #543; new A4 PR hosted RustFS CI status | A3 prior real provider proof, A4 integration unaffected, must not present a fake as real |
| T07 | Actual stage A/B source/build/index/corpus oracles on authorized host | Real source-specific preparation; not benchmark timing |
| T08 | Actual A/A + A/B one warm run on authorized idle-enough host | NEW performance gate; real supported host and immutable result |
| T09 | Result verification and independent replay + classification | Source/object identity and all 16 lane outcomes; no selective comparison |

**No new Rust engine test harness** is warranted: A3 was already reviewed and merged with its codec and real remote acceptance. If these existing suites reveal a new semantic failure in A4 preflight, STOP and request an independent engine fixup rather than modify optimized code inside A4.

### Exact failure categories

Every failure must be classified with evidence as one of: `INTRODUCED_REGRESSION`, `FEATURE_IMPLEMENTATION_DEFECT`, `DETERMINISTIC_PREEXISTING_FAILURE` (requires proof at accepted baseline), `NONDETERMINISTIC_FLAKY_FAILURE` (requires proof of nondeterminism) or `ENVIRONMENT_HARNESS_FAILURE`. Don't label a failed run "noisy" or "unrelated" without evidence. A failing control is a **failed control**, not necessarily evidence of a coder bug; it still blocks qualification. A stage-cache corruption is integrity failure, not permission to delete the cache. A performance regression is valid unfavorable evidence, not an implementation test failure.

## 7. Exact file allowlist and prohibited changes

### Code/test changes allowed

```text
benchmarks/quervant_bench/lean/artifacts.py
benchmarks/quervant_bench/lean/configuration.py
benchmarks/quervant_bench/lean/cli.py
benchmarks/quervant_bench/lean/preparation.py
benchmarks/quervant_bench/lean/runtime.py
benchmarks/quervant_bench/lean/tests/test_perf06a.py       [NEW]
```

### Documentation and new measured artifacts allowed

```text
docs/BENCHMARKING.md
docs/BENCHMARK_CONFIGURATION.md
docs/BENCHMARK_RESULT.md
benchmarks/BM10_README.md
docs/pr-artifacts/perf-06-a/PERF06A4_DETAILED_PLAN.md          [NEW, verbatim]
docs/pr-artifacts/perf-06-a/PERF06A4_EXECUTION_REPORT.md       [NEW]
benchmarks/studies/perf-06/warm/configurations/quervant-perf06a-paired-warm-<UTC-DATE>.json [ONE NEW]
benchmarks/studies/perf-06/warm/results/quervant-perf06a-paired-warm-<UTC-DATE>-001.json   [ONE NEW if run publishes, actual suffix allocated by CLI]
```

**Prohibited:** `crates/**` production Rust code or adapters, `Cargo.toml`/`Cargo.lock`, `benchmarks/pr15d/**`, `benchmarks/quervant_bench/lean/statistics.py`, `perf05.py`, `reporting.py`, `tests/test_perf02.py`, `tests/test_perf05.py`, `.github/workflows/**`, `docs/PERF_OPTIMIZATION_ROADMAP.md` completion flag, historical result/config JSON, existing checked-in golden segments, Cargo features, RustFS and objectstore code, any other `studies` family, benchmark thresholds/host readiness policy, B1 source. All actual dated/suffixed filenames are generated by the repository tool; the above `-001` is **expected only if none exists**, never hand-author or overwrite it.

**No third benchmark artifact format.** A human-readable Markdown summary belongs in the execution report. Raw scratch lives ignored under `target/` and is never committed.

## 8. Reviewer acceptance checklist

- [ ] A1–A3 actually merged; A source SHA correct (post-PERF05/pre-A1), B source SHA correct (merged A3), A ancestor of B; actual A3 CI #543 PASS.
- [ ] New `perf-06/warm` family correctly registered in all source/validation paths with exact A/B semantics and no copied runner/estimator.
- [ ] U01–U12, PERF-02 and PERF-05 regressions, Python coverage 85%, Rust stable/MSRV and workspace 85% gates pass on tested source, with exact command/count records.
- [ ] Independent user-approved paired-study method recorded; older historical B-only result is never used as A in the paired analyzer.
- [ ] One unique UTC config/UUID prepared with fixed source SHAs, workload and policy; fully validated and committed before any timing.
- [ ] `stage` verified both source objects/builds, separate indexes and 16 exact oracles; all output index metrics captured separately from warm query timings.
- [ ] Host checks genuinely executed and passed; no fake or disabled readiness; A/A 16/16 PASS.
- [ ] Exactly one timed campaign, 768 control and 768 treatment slot/lane records, no exclusions, all 16 lanes and 12 paired blocks, no missing or unverified responses.
- [ ] Every primary and guard outcome classified by fixed predeclared §2.4 thresholds; no success claim from status alone.
- [ ] Every `INCOMPLETE`/unfavorable result preserved; no unapproved retry, retuning or discarded slots.
- [ ] New config/result follow correct UTC, UUID, sibling `results`, unique suffix and Git provenance; report is reproducible read-only.
- [ ] Code/PR diff strictly matches allowlist; A3 and RustFS proofs stay unchanged; no format, scorer, benchmark engine or legacy evidence mutation.
- [ ] A4 PR remains draft and unmerged; decision to adopt A series and start B1 remains human-owned.

## 9. Suggested pull-request description (agent must populate actual evidence)

```markdown
## PERF-06-A4 — Cumulative A-series warm qualification

Separately verifies accepted A1–A3 correctness and registers the new `perf-06/warm`
study family by reusing BM-10's existing, fully pinned two-arm Quervant A/B runner.
Arm A: accepted pre-A1 PERF-05 source `2a74017958c8...`.
Arm B: merged PERF-06-A3 source `b70f624fffe0...`.

The A3 persisted postings-format change is intentionally represented by separately
built, committed, validated indexes; index bytes/build/commit/reopen are reported
separately from **warm query-only** `engine_ns`. The previously saved PERF-05
B-only study remains historical/unpaired and is not treated as this A4 baseline.

One approved 12-block randomized/position-balanced A/A + A/B run, 16 lanes,
exact independent oracles, 10K/100K absent/rare/medium/common and K10/K100,
5 warmups + 20 samples per slot, paired bootstrap CIs. No extra real benchmark,
RustFS setup, profiler, cold study or cross-engine comparison.

Result: <actual path/status, controls, all primary and guard outcomes>.
Correctness+CI: <actual command counts and coverage>.
Independent review and maintainer adoption decision REQUIRED; do not merge/start B1.
```

## 10. Preauthorized Architectural Decisions and Exception-Handling Matrix

**Rules:** Check observable triggers *before acting*. `AUTO-RESOLVE` means apply the **exact** prescribed response and continue, recording evidence. `DEFER AND CONTINUE` means preserve the blocked dependent gate while completing **only safe, independent** tasks; no implicit waiver. `HARD STOP` means halt affected work immediately, and the entire plan if it cannot be isolated. When several rules match, most restrictive prevails. **Any material condition not covered by this table is D48 HARD STOP**, not coding-agent improvisation.

| ID | Observable trigger / check | Category | Prescribed action | Prohibited action | Evidence / gate / owner |
|---|---|---|---|---|---|
| D01 | A1/A2/A3 PR not merged, source branch dirty or A3 final CI unverified | **HARD STOP** | Preserve IDs/CI and request dependency resolution | Treat pushed/green but unmerged as accepted | P0 / maintainer |
| D02 | Three PRs MERGED; `main==b70f624f…`; Git objects/ancestor valid; blobs exact | **AUTO-RESOLVE** | Pin A/B SHAs, create A4 branch from main and continue | Use newer arbitrary HEAD or PERF05 B-only B as A | P0 / agent |
| D03 | Any inspected implementation/framework source blob differs from §1.2, or main advanced | **HARD STOP** | Report actual SHA and diff; request amended source-anchored plan | Silently adapt, reset main or invent changed API | P0 / maintainer |
| D04 | Target branch or existing A4 PR already present | **HARD STOP** | Preserve identity; request explicit continuation plan | Reuse/reset/force-push without approval | P0 / maintainer |
| D05 | Previous PERF-05-C B result exists with different pinned SHA and a split-format candidate | **AUTO-RESOLVE** | Use **approved paired A/B** from §2; no historical A injected | Select a convenient historical B-only ratio | P4–P6 / agent |
| D06 | New family `perf-06` absent in `STUDY_REGIMES` | **AUTO-RESOLVE** | Add warm-only mapping; retain original family routes | Put results in perf-02 or create cold dir | S1/U03 / agent |
| D07 | `configuration.py` has sibling `perf-02` two-pinned arms | **AUTO-RESOLVE** | Include `perf-06` in exact same construction/validation branches | Copy a new config parser or allow non-pinned A | S2/U01–U02 / agent |
| D08 | Existing `perf-05` B-only historical branch observed | **AUTO-RESOLVE** | Leave unchanged, preserve historical tests/results | Convert PERF05 into paired study | S2/U11 / agent |
| D09 | CLI has supported `prepare`/`validate`/`stage`/`run` verbs | **AUTO-RESOLVE** | Add family choice/help only | Add a new CLI command or override safety flags | S3/U12 / agent |
| D10 | Preparation source identity has `perf-02` A/B and `perf-05` B logic | **AUTO-RESOLVE** | Extend A/B arm-id selection for `perf-06` | Skip Git commit type/source checks | S4/U04–U06 / agent |
| D11 | `build_programs` has two detached pinned worktrees for PERF02 | **AUTO-RESOLVE** | Route PERF06 through identical code loop | In-process source swap/shared target/compiler option changes | S5/U04 / agent |
| D12 | Generic `_control_config`, `_phase`, `analyze` already support two arms | **AUTO-RESOLVE** | Reuse exactly without editing | New paired estimator, extra controls, slot pruning | S5/U07–U08 / agent |
| D13 | A/B current build/index bytes legitimately differ due to A3 feature 0x000E | **AUTO-RESOLVE** | Record separate sizes and exact oracles; no byte equality requirement | Reject based solely on new-vs-old index size or normalize timers | P4 / agent |
| D14 | Corpus, query semantics, adapter mode or mandatory oracle differs between arms | **HARD STOP** | Capture exact response and source; no timed run | Change query or sort contract to create parity | P4 / maintainer |
| D15 | Git SHA missing/unavailable/not commit, or source compilation changes source selection | **HARD STOP** | Capture Git failure and fix dependency only with authorization | Fetch/clone arbitrary replacement or substitute SHA | P0/P4 / maintainer |
| D16 | Pinned worktree checkout/build fails, cleanup unavailable | **DEFER AND CONTINUE** | Record error, preserve source; complete independent reporting/tests; block stage/acquisition | Force-clear worktree or substitute binary | P4 / maintainer |
| D17 | Existing prepared cache matches all fingerprints and passes oracles | **AUTO-RESOLVE** | Reuse cached A/B source-built inputs, record HIT | Rebuild solely to get newer timing | P4 / agent |
| D18 | Existing completed cache digest/mapping/size fails | **HARD STOP** | Preserve bad cache + evidence; no acquisition | Delete/reuse stale cache, disable checksum | P4 / maintainer |
| D19 | Python test RED due solely to missing `perf-06` support | **AUTO-RESOLVE** | Record expected RED; implement S1–S5 | Count unrelated failures as RED | P1 / agent |
| D20 | New test/code fails due to narrow mechanical typo/typing/lint within allowlist | **AUTO-RESOLVE** | Minimal behavior-preserving correction; rerun relevant gates | New architecture or broad suppressions | P1–P2 / agent |
| D21 | Implemented Python feature requires modifying statistics/runner protocol/production Rust | **HARD STOP** | Report missing contract and request plan revision | Modify forbidden files or weaken tests | S1–S5 / maintainer |
| D22 | New deterministic Python assertion fails due to intended feature bug | **AUTO-RESOLVE** | Fix specified in-scope branch, retain assertion, rerun affected QA | Relax oracle or thresholds | P1–P2 / agent |
| D23 | Stable/MSRV, workspace coverage or Python 85% gate fails | **DEFER AND CONTINUE** | Preserve exact logs, classify; fix only in-scope defect per D20/D22; block acquisition | Waive/ignore, lower 85%, report GREEN | P2 / maintainer |
| D24 | Preexisting baseline test failure is claimed | **DEFER AND CONTINUE** | Reproduce on accepted baseline (or equivalent evidence) and classify | Assert "unrelated" without proof | P2 / maintainer |
| D25 | New format/score/reader/corruption/PIT regression found in inherited suite | **HARD STOP** | Document failure, request separate source fixup | Patch engine code in A4 | P2 / maintainer |
| D26 | Python CLI `prepare` attempts duplicate name or UUID / wrong family path | **HARD STOP** | Preserve existing config and ask for distinct name authorization | Overwrite, move existing config, force UUID | P4 / maintainer |
| D27 | UTC creation date differs from Pacific-local date | **AUTO-RESOLVE** | Use CLI-generated UTC date unchanged | Manually rename based on local clock | P4 / agent |
| D28 | CLI creates correct config; exact two pinned SHAs and default 16 lanes | **AUTO-RESOLVE** | Validate, commit immutably and continue to stage | Hand-edit UUID/config after result | P4 / agent |
| D29 | Host lacks supported Linux/x86_64 native FS/2 distinct physical cores/affinity | **DEFER AND CONTINUE** | Block timed study, finish safe source/docs work | Disable checks, change host quietly, fake readiness | P4 / maintainer |
| D30 | Mandatory host readiness returns busy/steal/unclear | **HARD STOP** | Preserve observation; no timed run/new run | Sleep/kill workload, auto-retry or adjust limits | P4/P5 / maintainer |
| D31 | Untimed stage oracle fails for any declared lane in A or B | **HARD STOP** | Capture arm/lane/expected/actual, stop timing | Remove bad lane, adjust expected or skip error | P4 / maintainer |
| D32 | Stage validates all indexes/oracles, sources, builds and config | **AUTO-RESOLVE** | Record exact evidence, proceed to one run | Rebuild again for arbitrary freshness | P4 / agent |
| D33 | A/A stage produces non-PASS on any of 16 controls | **HARD STOP** | Preserve `INCOMPLETE` result/control samples; no treatment/retry | Loosen ±15% or prune blocks | P5 / maintainer |
| D34 | A/A PASS but readiness before treatment fails | **HARD STOP** | Preserve `INCOMPLETE`, do not time treatment | Force treatment despite unstable host | P5 / maintainer |
| D35 | Oracle mismatch, missing slot, truncated series, invalid timing during treatment | **HARD STOP** | Preserve sampled data and `INCOMPLETE`; report first failure | Drop lane, retest only missing samples, call COMPLETE | P5 / maintainer |
| D36 | Readiness post-treatment fails or job interrupted | **HARD STOP** | Preserve raw result `INCOMPLETE`, no inferred qualification | Auto rerun or relabel clear | P5 / maintainer |
| D37 | `run` returned exit 4 and a saved INCOMPLETE result | **AUTO-RESOLVE** | Record precise path/reason and stop acquisition; safe reporting may continue | Retry, overwrite or relabel | P5–P6 / agent |
| D38 | A valid COMPLETE result includes B comparison `INCONCLUSIVE` | **AUTO-RESOLVE** | Classify paired INCONCLUSIVE, record CI/blocks; no adoption | Change significance threshold or rerun | P6 / agent |
| D39 | COMPLETE, four PRIMARY meet 5%+CI>0 and all GUARDS meet >=-10% point/CI | **AUTO-RESOLVE** | Report TARGETS_MET_REVIEW_REQUIRED, not merge | Declare code-only causal stages or start B1 | P6 / agent |
| D40 | COMPLETE but primary/guard condition fails | **AUTO-RESOLVE** | Report TARGETS_NOT_MET with all failed lanes, stop | Favorable subset, rebenchmark/rollback A3 | P6 / agent |
| D41 | Index/write-side bytes or build durations differ materially | **AUTO-RESOLVE** | Report values as separate diagnostics and potential tradeoff | Add write measurements to warm samples | P6 / agent |
| D42 | Saved result JSON cannot be parsed, validated or has broken UUID/name/sequence | **HARD STOP** | Preserve invalid file/raw evidence and seek publisher fixup | Write synthetic result or overwrite | P6 / maintainer |
| D43 | Result file already exists with expected `-001` suffix | **AUTO-RESOLVE** | Let publisher allocate next available *non-overwriting* sequence; verify ownership | Manually choose/overwrite old suffix | P5/P6 / agent |
| D44 | CI pending/unavailable after code commit | **DEFER AND CONTINUE** | Keep PR draft, continue documentation/read-only proofs only; no real run | Claim CI PASS or run before required gates | P3 / maintainer |
| D45 | Hosted CI fails on exact code head | **HARD STOP** | Classify job, request narrow fixup and rerun mandatory gates | Ignore CI or run timed acquisition | P3 / maintainer |
| D46 | Results/docs-only commit after successful source/CI qualification | **AUTO-RESOLVE** | Push only result/report; validate JSON; reuse source QA | Rebuild/benchmark solely because docs SHA changed | P6 / agent |
| D47 | User asks for RustFS/profiling/cross-engine/cold runs or more timed trials | **HARD STOP** | Refer to separately authorized future work | Fold into A4 without new plan/approval | Scope / maintainer |
| D48 | Any material new condition not matched by D01–D47 | **HARD STOP** | Preserve state, exact source/logs, smallest question; continue only provably independent work | Invent solution/design, bypass authorization | Human maintainer |

## 11. Final report schema and status requirements

The agent's `PERF06A4_EXECUTION_REPORT.md` **must** provide these headings in this order:

1. `REPOSITORY / BRANCH / PR / BASE_MAIN_SHA / A_SHA / B_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA`
2. `A1–A3 MERGED DEPENDENCY PROOF AND A3 CI #543`
3. `PERF-05 HISTORICAL COMPARABILITY DECISION — PAIRED ALTERNATIVE APPROVED`
4. `BENCHMARK FAMILY REGISTRATION — EXACT FILE DIFF AND TESTS`
5. `PRE-IMPLEMENTATION ADVERSARIAL CHALLENGE AND INV-TO-TEST TRACE`
6. `RED / GREEN AND BASELINE REGRESSION EVIDENCE`
7. `LOCAL RUST+PYTHON COVERAGE AND STABLE/MSRV COMMAND TABLE`
8. `HOSTED CI HEAD, JOB IDS, STATUS, REAL RUSTFS REUSE`
9. `IMMUTABLE CONFIG FILE / UUID / UTC DATE / A/B COMMIT IDENTITIES`
10. `STAGE / CACHE FINGERPRINT / COMPILERS / TWO INDEX BUILD-COMMIT-REOPEN ORACLES`
11. `BENCHMARK HOST READINESS, CPU AFFINITY, TIMED BOUNDARY`
12. `ONE REAL RUN, RESULT FILE / UUID / UTC / SUFFIX / RAW COUNT AND CONTROLS`
13. `16-LANE PRIMARY/GUARD PAIRED CI TABLE AND DETERMINISTIC DECISION`
14. `INDEX-BYTE / BUILD-COMMIT-REOPEN DESCRIPTIVE TRADEOFFS`
15. `NEGATIVE EVIDENCE, FAILURE CLASSIFICATION, UNRESOLVED RISKS`
16. `APPLIED DECISION MATRIX ROWS AND HARD STOPS`
17. `NO_UNAPPROVED_RERUN / NO_PROFILING / NO_CROSS_ENGINE / NO_MERGE`
18. `B_DISPOSITION / NEXT HUMAN DECISION / B1 BLOCKED UNTIL ACCEPTED`

**Terminal scope:** one **draft, unmerged** PR plus one immutable configuration and at most one newly measured result. If a relevant gate fails, partial artifact/evidence remains visible; completion is BLOCKED/INCONCLUSIVE rather than a favorable claim. **The coding agent does not decide whether Quervant should retain A1–A3 in the performance roadmap; the independent maintainer does.**
