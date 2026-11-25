# PERF-06-B4 — Detailed Integrated B-Series Warm Qualification Plan

**Repository:** `yduchesne/quervant`  
**Proposed branch/PR:** `dev/perf06-b4-qualification` → new draft PR against `main`  
**Plan status:** AUTHORING COMPLETE — not an execution or benchmark report  
**Experiment:** one new **paired, contemporaneous Quervant A/B** PERF-06 warm study of cumulative B1+B2+B3  
**Human authority:** maintainer reviews the result, chooses adoption/merge, and authorizes any new acquisition  
**Source examined:** accepted pre-B1 `480a77e78c6897e05cb7ceb76b01434974b82ec6`; current post-B2 `main` `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2`; B3 tested executable `52d7e69f40759f27be79434118c47171b06702b7`, PR #128 then at `b7753c5e6bccd443faf64b65c7b0f3d65fc2d083` (not merged at planning time). **The user explicitly instructs us to assume B3 is merged when this plan is executed.** The coding agent must discover and pin that actual merged `main` commit, not use the above PR head by guess.

> **Read first:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `AGENTS.md`, `docs/BENCHMARKING.md`, `docs/BENCHMARK_CONFIGURATION.md`, `docs/BENCHMARK_RESULT.md`, `benchmarks/BM10_README.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`. This plan is a subordinate, source-specific execution contract. If a new source fact makes a mandatory design invariant false, apply the decision matrix or STOP; do not redesign.

---

## 0. Explicit execution authorization and exceptions

**Continuous execution authorization:** Execute this approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, approved AUTO-RESOLVE decisions, and ordinary checks. Stop affected work only for an applicable HARD STOP, a genuinely missing maintainer decision, or an essential dependency. When the obstacle is isolated, record its scope and continue every independent safe authorized task. Informational checkpoints do not require approval.

### 0.1 User-specified overrides — binding

1. **Assume `main` stable after B3 merge.** Do **not** run any unit-test suite, integration-test suite, benchmark-framework test suite, `cargo test`, `pytest`, `cargo clippy`, `cargo fmt`, `cargo doc`, coverage, `bench --no-run`, pre-commit hooks or analogous broad QA. Do not create a CI gate requiring those checks. Historic accepted B1–B3 QA is not rerun in B4. Do not demand that the pre-existing CI jobs finish before performing B4. The benchmark runner's **actual independent oracle validation** and read-only configuration/result validators **are required**; they are acquisition integrity checks, not a test-suite rerun.
2. **Host assumed idle and available.** Do not ask for idle-host reconfirmation or run a separate host qualification campaign. Preserve Linux/WSL2, native filesystem, two distinct physical cores, `taskset`, pinned CPU roles, installed toolchain and executable availability as **technical prerequisites**. Do not disable CPU affinity, use a different host automatically or bypass an invalid filesystem.
3. **Host stability/readiness observations are informative, never blocking.** Observe the same CPU busy/steal values at the existing native checkpoints and store their *actual* `clear`, `busy`, or `unavailable` status. Busy/unavailable observations cannot prevent staging, controls, measurement, persistence, or numerical classification. Do not disguise a `busy` reading as `clear`, raise readiness ceilings, suppress raw observations, remove sampling or silently change host. The preexisting **A/A equivalent-executable statistical control stays blocking**, because it measures the statistical validity of the comparative study, not host-idle status. Incorrect answer/oracle, source, format or allocation checks remain blocking.
4. **Exactly one real timed acquisition** (`quervant-bench run`) is authorized for this configuration. `stage` is untimed preparatory work and may be called once; `analyze` and `report` only read the saved result. On failure or unfavorable result, never run again, overwrite, prune blocks, change a criterion, or generate a replacement configuration automatically.
5. **No new engine optimization.** No B1, B2, B3, index/reader/collector, codec, query, cursor, objectstore, S3/RustFS, adapter, compiler flag or dependency change. B4 introduces one narrow **benchmark-tool advisory host-readiness capability** plus versioned configuration/result/reporting; no engine changes.
6. **Human G10 remains open.** The agent may commit, push and open the draft PR, but cannot merge, issue an adoption approval, start PERF-06-C1, or claim a universal speedup.

### 0.2 Exact terminal status vocabulary

- `PERF06_B4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED`: new result structurally `COMPLETE`, all 16 A/A controls pass, oracle and source checks pass, and the separately frozen B4 4-primary/12-guard numerical policy passes.
- `PERF06_B4_QUALIFIED_TARGETS_NOT_MET_REVIEW_REQUIRED`: a sound, `COMPLETE` comparison, with at least one frozen B4 numerical gate not met. Preserve its unfavorable evidence; do **not** relabel it incomplete or automatically roll back merged B1–B3.
- `PERF06_B4_INCOMPLETE_VERIFICATION_BLOCKED`: missing/invalid source, build, index, oracle, control, output, uncomputable comparison, or one started campaign that did not complete. Preserve whatever result the native runner published; no second attempt.
- `PERF06_B4_PLAN_STOP_<RULE>`: source conflict/unforeseen architectural case, with task-local artifacts preserved and the exact rule/reason supplied. No benchmark-acquisition claim.

A native `COMPLETE` result is a structural measurement status, **not** automatic performance acceptance. A native `INCONCLUSIVE` lane does not erase a structurally complete campaign; the separate B4 policy handles it explicitly.

---

## 1. Goal, current source reconciliation, and reason for method

### 1.1 One dominant goal

Establish whether the combined, already accepted B-series architecture improves **end-to-end warm exact-keyword search and Top-K projection** relative to the **accepted source immediately before B1**. This is a cumulative A→B comparison; do not attribute the observed effect to B1, B2 or B3 independently.

| Component | Already delivered before B4 | B4 action |
|---|---|---|
| B1 | Persistent segment keyword dictionaries/ordinals, snapshot-wide numeric mapping, versioned COLUMNS and proven reader/codec failures | Preserve; validate independently built treatment index and observed correct answers |
| B2 | Global Top-K shared-rank sort, owned winner tuples, strict legacy fallback, K+1 and cursor/PIT semantics | Preserve; native warm workloads explicitly use lexically sorted `doc_id` strings |
| B3 | Retained, metered per-verified-segment key fingerprints, collision-exact duplicate detection, losing-candidate deferred ownership | Preserve; no policy change; report metadata tradeoff in untimed diagnostics |
| B4 | Not yet acquired on the merged B3 source | **One** qualifying A/A + paired A/B study, integrity reporting, independent maintainer decision |

The previously performance-rejected PR 15H-C and PR 15I-D1-F mechanisms remain historical negative evidence. B4 does not reopen, reinterpret or retry their campaigns.

### 1.2 Pinned source identities: no guessing

- **Arm A (pre-B1 accepted baseline; frozen):** `480a77e78c6897e05cb7ceb76b01434974b82ec6`. This is the actual PR #126 B1 base. Its ancestor `3bb232f868cb556ce9b4273d902164c65416af0f` was the A6 measured treatment source; their intervening changes were non-engine documentation/evidence. Prefer the *last accepted immediately-pre-B1* source `480a77...` for a **new paired** study rather than claiming historical 3bb data are a paired control.
- **Arm B (cumulative B1+B2+B3):** the actual new `origin/main` 40-hex SHA **after PR #128 merged**, assigned once to shell `B_SHA`. Do not substitute PR #128's pre-merge `b7753c5e6bccd443faf64b65c7b0f3d65fc2d083` unless that exact object is itself the accepted main revision—which would have to be demonstrated, not assumed. The B4 branch and report point to `B_SHA` even after later docs-only commits.
- **B1/B2/B3 provenance:** verify `480a77...` is ancestor of B_SHA, that PR #126/#127/#128 are merged and that B3's tested engine blobs are unchanged by their final evidence-only/merge commits. If new executable changes occurred after the reviewed B3 tested source, **STOP D05** rather than silently benchmarking something not accepted. Only docs/evidence changes are admissible.
- **Study implementation:** `benchmarks/quervant_bench/lean/{cli.py,configuration.py,runtime.py,preparation.py,statistics.py,artifacts.py}`. In the current harness, `perf-06/warm` already invokes the `perf-02` two-pinned-arm path: independent detached worktrees, `cargo build --release --locked`, separate source and indexes, A/A control, randomized blocks, per-sample exact oracle, and exclusive result JSON publication. Do not implement another scheduler.

### 1.3 Deliberate choice: contemporaneous A/B, not B-only historical

B1 introduced a persistent representation change; the nearest previously measured A6 source is not the exact pre-B1 Git source and was acquired in a separate session. Even if its logical PR15D workload matches, comparing those absolute medians would be **historical, unpaired, and context-sensitive**. The present plan **chooses one new paired A/B experiment** to avoid a weak historical comparability assumption. This is the existing supported PERF-06 path; it requires no Tantivy/Lucene, no synthetic control, no historical-median reconstruction, and no second timed campaign. **Do not switch to B-only** on an unfavorable result or to save time; that requires a new approved plan.

---

## 2. Exact permitted repository delta

**New task-owned files / edits:**

- `benchmarks/quervant_bench/lean/cli.py` — add a `prepare`-only boolean CLI switch `--readiness-advisory`, propagated to configuration creation.
- `benchmarks/quervant_bench/lean/configuration.py` — optional, validated `policy.readiness.mode="advisory"` **only** for `family="perf-06"`; no change to old configs or default behavior.
- `benchmarks/quervant_bench/lean/runtime.py` — a small shared readiness observation helper, advisory-vs-blocking decision on existing checkpoints in the paired path; no scheduler, oracle, sampler or statistics change.
- `benchmarks/quervant_bench/lean/preparation.py` — use the same helper for the existing pre-index observation; keep native host capability gates, content validation, stage caching and oracles unchanged.
- `docs/BENCHMARK_CONFIGURATION.md` and `benchmarks/BM10_README.md` — state the exact `perf-06` advisory-only option, observed true statuses and no change to A/A correctness/stability controls.
- `benchmarks/studies/perf-06/warm/configurations/quervant-perf06b4-paired-warm-<UTC-creation-date>.json` — **exactly one** new immutable config created using the sanctioned CLI.
- `benchmarks/studies/perf-06/warm/results/quervant-perf06b4-paired-warm-<UTC-creation-date>-<NNN>.json` — **exactly one** real native result (published exclusively by runner; sequence chosen by runner).
- `docs/pr-artifacts/perf-06-b/PERF06B4_DETAILED_PLAN.md` — verbatim approved plan copy.
- `docs/pr-artifacts/perf-06-b/PERF06B4_EXECUTION_REPORT.md` — source, oracle, policy/metric, observed host status, final decision report.
- `docs/pr-artifacts/perf-06-b/b4/` — small *text* run markers, command logs, SHA/identities, read-only analysis and verification output. No large corpora, binary, raw copied result or separate data acquisition.
- `docs/PERF_OPTIMIZATION_ROADMAP.md` and `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` — B4 status only **after** actual acquisition/acceptance; leave B3 status factual. Do not mark B-series performance-accepted without G10.

**Strictly protected:** all `crates/**`, `Cargo.toml`, `Cargo.lock`, `.github/**`, `benchmarks/pr15d/**`, `benchmarks/quervant_bench/lean/{statistics.py,artifacts.py,perf05.py,reporting.py}`, datasets/corpus/oracle sources, existing configuration/result JSON, existing evidence logs, `docs/BENCHMARKING.md` statistical methodology, and all historical tests. No test files are added or executed in B4. Any actual need to touch a protected path is **HARD STOP D32**. Scratch only under `target/perf06-b4/`, using the existing stage directory cache.

**Ownership:** runtime captures samples, oracles, and result; `artifacts.py` exclusively chooses result suffix and creates immutable JSON; B4 report interprets *stored* analysis; maintainer alone promotes/rejects the accepted B baseline.

---

## 3. Frozen contract — exact experiment configuration

| Dimension | Frozen value |
|---|---|
| Family, regime | `perf-06`, `warm` (supported by existing validator) |
| Name | `quervant-perf06b4-paired-warm` |
| Config filename | `quervant-perf06b4-paired-warm-<UTC creation date>.json`, generated by CLI |
| A revision | `480a77e78c6897e05cb7ceb76b01434974b82ec6` |
| B revision | post-B3 merged `B_SHA` recorded in preflight |
| Both arms | `engine=quervant`, `mode=by-top-k`, `source=pinned`, release/locked, no experimental strategy feature |
| Workload | `pr15d-exact-keyword-v1`; actual UTF-8 lexicographic ascending string sort of `doc_id`, exact term count and projected ordered IDs |
| Corpus sizes | `10000`, `100000` |
| Selectivity | `absent`, `rare`, `medium`, `common` |
| Top-K | `10`, `100` |
| Regime | warm, within adapter `engine_ns`, reader/index already opened; no startup/indexing in query timer |
| Lanes | 16; every combination of 2 sizes × 4 classes × 2 K |
| Controls | `AA`/`AA2`, baseline A executable/index only, native paired A/A stats and **blocking** gate |
| Treatment | A vs B, separately compiled release executables and independently built index files |
| Schedule | 12 randomized, position-balanced blocks; 2 slots **per arm** per block; seed `20261122` |
| Samples | 5 untimed warmups + 20 timed, strictly positive `engine_ns` values per lane/slot |
| Raw records | 768 controls + 768 treatment = 1536 records total; 15,360 + 15,360 = 30,720 positive timed samples |
| Statistical estimator | per-slot sample median; mean of 2 slot medians per arm/block; 12 blockwise B/A ratios; median of paired ratios; gain = `100 * (1 - ratio)` |
| Uncertainty | native 10,000 deterministic **whole paired block** bootstrap resamples; 95% percentile interval; no pooling of per-sample rows |
| Native policy | `min_gain_percent=0`, `max_regression_percent=0`, `max_aa_gain_percent=15`, `min_blocks=4`, `exclude_blocks={}` |
| Frozen B4 evaluation | §7.2 below; distinct from native `IMPROVED/REGRESSED/INCONCLUSIVE` labels |
| Readiness | observations 4 × 250ms, informational ceilings *unchanged* at busy 25%, steal 2%; `policy.readiness.mode="advisory"` |
| Real host prerequisites | Linux/WSL2, ext4/xfs/btrfs, ≥2 available physical cores, taskset, Rust toolchain and source/object availability |

### 3.1 Independent PR15D corpus/oracle (unchanged)

Existing `runtime.row_values(i)` for `i in [0,N)` writes `doc_id=d<i as 8 digits>`, `key=singleton` at i=0, otherwise `common` for even i and `other` for odd i, `group=medium` every eighth row else `different`, a deterministic body and payload. Existing independent `expected_answer` yields:

| Class | Exact predicate | Matching count | First retained IDs |
|---|---|---|---|
| absent | `key=never` | `0` | `[]` |
| rare | `key=singleton` | `1` | `[d00000000]` |
| medium | `group=medium` | `N/8` | `d00000000,d00000008,...` |
| common | `key=common` | `N/2 − 1` | `d00000002,d00000004,...` |

Each arm builds and reopens its own index; the indexes **are not expected to be byte-identical** because B1 changed encoding. The benchmark requires exact *logical* count and order for both versions. Any oracle mismatch is blocking, regardless of readiness observations. Do not replace real `doc_id` string sorting with numeric surrogate ordinals, time internal micro-operations, reduce projection, or change corpus distribution.

### 3.2 Untimed format/footprint/writer diagnostics

Reuse `stage_inputs()` → `runtime.build_index()` and capture existing `index_metrics[A|B]["10000"|"100000"]`:
`index_ns`, `commit_ns`, `reopen_ns`, `index_bytes`, and `segment_count`. `index_ns` is existing index build/indexing metric; `commit_ns` writer commit; `reopen_ns` reader reopening; `index_bytes` actual file-tree bytes cross-checked against adapter response. Report each arm/size absolute value, `B/A` descriptive ratio (not confidence interval), and byte delta. These are **fresh-build/reindex diagnostics**, *not* an isolated compaction benchmark, and must never be mixed into warm `engine_ns` or used as a primary selection gate. Do not run an extra timed writer/rebuild campaign. If an actual separate compaction-cost requirement is later raised, defer to another approved study; do not invent a compaction timer in B4.

No RSS claim: the benchmark framework does not currently record authoritative retained fingerprint RSS. Report source-level representation (`Vec<u64>` per segment, bounded metadata) and the committed B1–B3 structural evidence as context; **do not create a profiler or an unapproved RSS sampling regime**.

---

## 4. Exactly prescribed narrow benchmark-readiness implementation

Current source anchors (post-B2 main inspected):

- `lean/configuration.py::default_configuration` generates fixed 4×250ms readiness `25/2`, and `validate_configuration` checks shape and upper bounds; `prepare_configuration` calls default generator.
- `lean/cli.py::parser` defines `prepare/stage/run` and `main` forwards preparation kwargs.
- `lean/preparation.py::stage_inputs` runs `runtime.assess_readiness` before index build and **currently raises** for `busy`.
- `lean/runtime.py::run_benchmark` calls readiness before A/A, before treatment, and after treatment; it **currently raises** for `busy`. The `perf-05` path is separate and must not change.
- `runtime.host_context(scratch, check=True)` is the distinct mandatory structural host prerequisite. `pinned_controller` and `_run_pinned` preserve CPU affinity. These must remain exactly as before.

### 4.1 `configuration.py`: opt-in and bound validation

**Normative private signatures (add only named keyword and default):**

```python
def default_configuration(family, name, description, *,
                          timestamp=None, regime="warm",
                          baseline_revision=None, candidate_revision=None,
                          quervant_revision=None,
                          readiness_advisory=False):
    # Keep the original body except:
    if readiness_advisory and family != "perf-06":
        raise ArtifactError("advisory host readiness is supported only for perf-06")
    # AFTER original policy dict creation, BEFORE validate_configuration:
    if readiness_advisory:
        policy["readiness"]["mode"] = "advisory"
```

Add `readiness_advisory: bool=False` to `prepare_configuration(...)` and forward it to `default_configuration(...)`. Do not insert `mode` in other families or existing historical configurations. In `validate_configuration` after the original readiness percentage/budget validation:

```python
mode = readiness.get("mode", "blocking")
if mode not in ("blocking", "advisory"):
    raise ArtifactError("unsupported host readiness mode")
if mode == "advisory" and family != "perf-06":
    raise ArtifactError("advisory host readiness is supported only for perf-06")
```

The absence of `mode` is the **original blocking behavior**, including every old result. Do not accept arbitrary unknown readout strings as a bypass. Never relax the actual 25%/2% observation thresholds.

### 4.2 `cli.py`: creation-only switch

Add exactly:

```python
make.add_argument("--readiness-advisory", action="store_true",
                  help="perf-06 only: preserve actual host load observations without using them as an acquisition gate")
```

In `main` only the `prepare_configuration` invocation gains `readiness_advisory=args.readiness_advisory`. `stage` and `run` need **no runtime flag**: the mode is frozen in the immutable configuration, not an unrecorded command/environment override. Do not add `--force`, `--ignore-oracle`, `--skip-aa`, `--skip-affinity`, `--quick`, `--repeat`, or aliases.

### 4.3 `runtime.py`: one actual-observation helper, no false clear

Immediately after existing `assess_readiness(...)`, add exactly one small helper. Preserve `assess_readiness` unchanged:

```python
def observe_readiness(cpu: int, readiness: Mapping[str, Any], *, advisory: bool) -> dict[str, Any]:
    try:
        return assess_readiness(
            cpu, intervals=readiness["intervals"],
            interval_seconds=readiness["interval_ms"] / 1000,
            max_busy_percent=readiness["max_busy_percent"],
            max_steal_percent=readiness["max_steal_percent"])
    except MeasurementBlocked as error:
        if not advisory:
            raise
        return {"cpu": cpu, "observations": [],
                "max_busy_percent": readiness["max_busy_percent"],
                "max_steal_percent": readiness["max_steal_percent"],
                "status": "unavailable", "reason": str(error)[:500]}
```

In the **paired** `run_benchmark` (not `_run_benchmark_perf05`), after config validation derive:

```python
readiness_advisory = (
    config["family"] == "perf-06" and
    config["policy"]["readiness"].get("mode", "blocking") == "advisory")
```

Set `report["context"]["host_readiness_mode"] = "advisory" if readiness_advisory else "blocking"` **before** the `try` scope that may fail (so even an incomplete result records mode). Keep `host_context(..., check=check_host)` and all CPU selection unchanged. Replace only the body of the nested `observe()` by `return observe_readiness(adapter_cpu, readiness, advisory=readiness_advisory)`. For each existing `if result["status"] != "clear": raise MeasurementBlocked("host contention ...")` in the paired path (pre-index test seam, pre-A/A, pre-treatment, post-treatment, plus the cross-engine throughput checkpoints where present), change condition to `if ... != "clear" and not readiness_advisory:`. Because `readiness_advisory` is false outside `family="perf-06"`, every other family remains exact. The actual probe dictionary is always stored in the same `report["controls"]["readiness_..."]` key. Preserve `status="busy"` or `status="unavailable"` verbatim; **never rewrite to `clear`**.

Crucially, do **not** change the rejection after:

```python
if any(c.get("status") != "PASS" for lane in control_stats["lanes"].values()
       for c in lane["comparisons"].values()):
    raise MeasurementBlocked("A/A control is unstable; comparative acquisition is blocked")
```

No changes to block schedules, 10,000 bootstrap, raw samples, error propagation, result publication, corpus, or adapter. Do not call `run_benchmark(check_host=False)`; that would silently remove real CPU topology/affinity context and is not the user-authorized exception.

### 4.4 `preparation.py`: advisory stage observation only

Inside `stage_inputs` after loading the validated config derive the *same* `readiness_advisory` predicate. In the existing `if check_host:` index-pre observation:

```python
probe = runtime.observe_readiness(cpu, readiness, advisory=readiness_advisory)
prepare_host["readiness_index_pre"] = probe
if probe["status"] != "clear" and not readiness_advisory:
    raise runtime.MeasurementBlocked("host contention before indexing staged inputs")
```

For `perf-06` advisory mode, also persist `prepare_host["readiness_mode"]="advisory"` so result cache provenance is visible on stage HIT. Keep `host_context` technical-prerequisite check, all strict source/file/hash cache checks and `_verify_oracles` unchanged. Do not swallow malformed indexes or failed source verifications. Preserve the stage cache's normal identical-configuration key and non-overwriting manifest behavior. If source access/corruption failures occur, STOP; host observations alone are not a reason to stop.

### 4.5 Documentation / behavioral proof without a test suite

Update the two named doc files to say **only** PERF-06 configs explicitly created with `--readiness-advisory` have this mode; `clear/busy/unavailable` remains true in the result, host structural eligibility and A/A controls remain binding. Do **not** run benchmark-unit tests or quality checks; the user's stable-main assumption is explicit. Permitted non-test operational verification is `quervant-bench validate` on the real frozen configuration and inspection of the printed `context.host_readiness_mode` and observed control dictionaries from the published JSON. If any code change outside §4 is required, STOP D32.

---

## 5. Operational preflight and safe branch creation (not test suites)

From clean tracked source, on the original host and native filesystem:

```bash
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
git fetch origin main
# The authoring-time main was pre-B3; the execution-time main MUST include merged B3.
gh pr view 128 --repo yduchesne/quervant --json number,state,mergedAt,mergeCommit,baseRefName,headRefName,url
B_SHA="$(git rev-parse origin/main)"
A_SHA=480a77e78c6897e05cb7ceb76b01434974b82ec6
git cat-file -e "$A_SHA^{commit}"
git cat-file -e "$B_SHA^{commit}"
git merge-base --is-ancestor "$A_SHA" "$B_SHA"
# Read-only source and branch identity checks: never call test/QA commands.
git status --short
git diff --name-status "$A_SHA" "$B_SHA" -- crates/quervant-core/src/segment/format.rs crates/quervant-core/src/segment/reader.rs crates/quervant-core/src/search/unified.rs
git switch -c dev/perf06-b4-qualification "$B_SHA"
```

**Before executing `git switch -c`:** independently require `gh` reports PR #128 merged, `origin/main` equals or descends from that merge, B3's accepted source is present, and the tracked worktree is clean. Do not force checkout or destroy unrelated untracked evidence. The above commands are a recipe **conditional on checks**, not a license to ignore their output. For a preexisting task-owned B4 branch, apply D04 resume; never overwrite it. Ensure `A_SHA != B_SHA`, worktree and source pinned paths are real commits. No tests/clippy/CI are prerequisites. GitHub CI may run automatically on the B4 PR; record its state as informational and do not block the user's acquisition waiting for it.

Record immutable values in `docs/pr-artifacts/perf-06-b/b4/preflight.txt`: `A_SHA`, `B_SHA`, B3 merge SHA, parent commit, branch, current HEAD, source ancestry, original relevant Git tree blob IDs, source-matching diagnostics, Rust/cargo/python versions **by `--version` only**, native filesystem type, CPU candidate identifiers, free disk and config name. Don't run host contention measurements as an extra preliminary gate: the native stage and run already observe them. Do not modify governor, caches, or CPU affinity manually.

Use `target/perf06-b4/` for all compiled engines, indexes, and temporary corpus files. **Never** store them under `docs/` or commit them. Only the existing BM-10 runner owns prepped inputs; no custom cleanup or forced cache deletion.

---

## 6. Immutable acquisition lifecycle — exact commands

### 6.1 Before first stage: commit tooling, freeze source and config

Implement only §4, update docs, copy this plan verbatim to the designated repository artifact, and create the *one* B4 config using the modified CLI after committing the tooling so `preparation.source_identity` sees a clean committed benchmark source. Use `uv run` only if the project already has an authorized wrapper; default from repo root is the existing `quervant-bench` entrypoint installed as documented in `benchmarks/BM10_README.md`. The agent must use the currently installed, authenticated CLI, not download or install alternate harnesses. If it is not installed, the only authorized compatibility fallback is `PYTHONPATH=benchmarks python3 -m quervant_bench` (the existing module entrypoint); if neither resolves without new packages, STOP D13.

```bash
# The creation date is chosen and recorded by CLI in UTC; do not type a guessed date.
quervant-bench prepare \
  --family perf-06 --regime warm \
  --name quervant-perf06b4-paired-warm \
  --description 'PERF-06-B4 paired cumulative B1-B3 warm qualification against last accepted pre-B1 source; advisory-only CPU readiness, binding A/A control' \
  --baseline-revision "$A_SHA" --candidate-revision "$B_SHA" \
  --readiness-advisory
# CAPTURE CONFIG EXACTLY FROM CLI STDOUT. No glob selecting an older config.
CONFIG='<exact path printed by prepare>'
quervant-bench validate --config "$CONFIG"
```

The freshly created JSON must contain exactly A_SHA/B_SHA, `policy.readiness.mode="advisory"`, **original** `max_busy_percent=25`, `max_steal_percent=2`, 12/2/5/20/10000/20261122, no excluded blocks, one unique UUID, 16 lanes, the production `by-top-k` strategy and original `AA/AA2` control. A **single** immutable `created_utc` determines filename; the first `prepare` output is retained even if subsequent source/report commits occur. Never edit the JSON after creation. Source/tooling may be committed earlier than config; immediately commit the newly generated config as an **immutable** source input before stage. Do not re-run `prepare` if the config already exists—check and resume D04.

**Pre-stage source safety:** every new engine/source-code change is forbidden. The only committed runtime change is the advisory harness from §4. If `git status --short` shows an unresolved tracked/source change, STOP until provenance is reconciled; the normal cache refuses dirty benchmark sources. The agent may commit only task-owned documentation/evidence, never unrelated files.

### 6.2 Stage once, untimed, no historical A substitution

```bash
mkdir -p target/perf06-b4 docs/pr-artifacts/perf-06-b/b4
# One ordinary stage invocation; may be BUILT or a source-verified HIT.
quervant-bench stage --config "$CONFIG" --scratch-root target/perf06-b4 \
  2>&1 | tee docs/pr-artifacts/perf-06-b/b4/stage.log
```

Under `set -o pipefail`, log exit codes as well as stdout. Verify `PREPARATION=BUILT` or `HIT`, one preparation key and frozen A/B SHA in cached metadata; two independent Rust release binaries from pinned worktrees, two independent filesystem indexes per size, `documents_indexed==documents_verified==N`, `index_bytes` matches actual disk tree, and all **16 lanes × both arms** pass untimed oracle checks. These are *required engine-correctness oracles* integral to a benchmark; **not** broad unit/integration suites. The two indexes may legitimately differ in byte footprint/segment layout. Stage `readiness_index_pre` can be `busy` or `unavailable`: record it, label advisory, and **continue** if every mandatory source/oracle/build/host-capability check passed.

If stage returns error, classify; do not execute the timed campaign. A stage failure due only to actual busy CPU should be impossible with the mode installed; treat such a failure as a harness defect requiring STOP, not a reason to relax thresholds. An actual corrupt cache/digest/oracle mismatch is blocking even though the host was assumed ready.

### 6.3 Freeze exactly one real timed invocation

Before timing, create an **exclusive start marker** in `docs/pr-artifacts/perf-06-b/b4/` (with `noclobber` or Python `open(...,'x')`), containing `CONFIG`, UUID, A SHA, B SHA, acquisition UTC, tool SHA, stage preparation key and invocation command. The marker must be **durable before** spawning the command. If it exists, D21 forbids another run—even if a result is missing or a previous process was interrupted. Do not discard the marker, fabricate a run status or create a second config automatically.

```bash
# Make this exact command only ONCE after the start marker is durable.
quervant-bench run --config "$CONFIG" --scratch-root target/perf06-b4 \
  2>&1 | tee docs/pr-artifacts/perf-06-b/b4/run.log
# Record return code and exact RESULT_JSON path printed; rc=4 means INCOMPLETE.
```

Existing BM-10 `run` owns the whole schedule: stage-cache lookup/verified oracle → advisory host readings → real **blocking** 16-lane A/A control → real paired A/B acquisition if A/A passes → independent oracle for every warmup and sample → native analysis → immutable result JSON. Do not call individual `_phase`, `collect_slot`, `assess_readiness`, workload-specific scripts or a rerun. Do not launch other workload activity during acquisition; the user already guarantees host is ready. On high reported host busy/steal, **continue without intervention** and disclose it.

### 6.4 Read-only verification, policy decision and reporting

Once a result JSON exists, capture the exact original path returned by the CLI (not the most recent glob). The only permitted follow-ups are:

```bash
quervant-bench validate --config "$CONFIG"
quervant-bench analyze --result "$RESULT_JSON" \
  > docs/pr-artifacts/perf-06-b/b4/read-only-analysis.json
quervant-bench report --result "$RESULT_JSON" \
  > docs/pr-artifacts/perf-06-b/b4/rendered-report.md
```

`analyze` must recompute **exactly** the saved treatment analysis (compare JSON parsed values, not printed whitespace). `report` renders stored values only; it must not time or change the result. Capture one additional `docs/pr-artifacts/perf-06-b/b4/verification.json` from the precise §7 checks, and summarize in `PERF06B4_EXECUTION_REPORT.md`. Original config/result JSON are the only benchmark **data** artifacts; `b4/` is task-process/reporting evidence, not an invented statistical certification or second result.

On an unsuccessful run whose result exists, do read-only reporting of the `INCOMPLETE` artifact and STOP measurement; if no result exists after a started marker, report interruption and preserve the marker; no retry.

---

## 7. Evidence verification, performance gates and decision rule

### 7.1 Mechanical validity (must pass before interpreting gains)

From the native `benchmark-result-v1` JSON:

1. `schema`, `family`, `configuration_id`, `configuration_file`, embedded frozen `configuration`, `run_id`, `executed_utc` and original-result path are internally coherent and match the unique config. Result file is non-overwritten, non-symlinked and follows the `-NNN.json` suffix convention. `run_id` is a valid UUID distinct from the config UUID.
2. `context.build.arm_source_revisions` is exactly `{"A":A_SHA,"B":B_SHA}`; `context.host_readiness_mode == "advisory"` and preserved `controls.readiness_*` probes contain true `clear`, `busy` or `unavailable`. No declared host-stability reading can be used as a numerical gate.
3. `controls.analysis.lanes` has all **16** required lane IDs and each A/A comparison (`AA2`) has **`status="PASS"`** under original ±15% confidence/point limits. Failing A/A blocks comparative validity; host `busy` does not. The A/A control must not be replaced by synthetic/mock results.
4. `controls.raw_samples` has exactly **768** records and treatment `raw_samples` exactly **768** records, with the declared 12 blocks/2 arms/2 slots and all 16 lane IDs, no missing/duplicate slot records, `warmups==5`, exactly 20 positive integer `samples_ns` per record, and `oracle_ok is True`. **All 12 blocks per lane** must exist; no automatic pruning; `policy.exclude_blocks=={}`.
5. Verify `analysis.lanes` has each lane and treatment `comparisons.B` with a finite numeric `ratio_b_over_a`, `gain_percent`, exactly two ordered finite `gain_ci_95_percent` bounds, `status` in `IMPROVED/REGRESSED/INCONCLUSIVE`, and no `NON_COMPARABLE`, `NOT_COMPUTABLE`, `FAIL`, or missing retained-block data. The result `status` must be `COMPLETE`; an `INCOMPLETE` is not a qualified comparison, regardless of numerical partial samples. A structurally complete study may contain `INCONCLUSIVE` lanes; B4 policy applies below.
6. Compare `quervant-bench analyze` recomputation with saved `analysis` **without changing estimator**. No resampling schedule, altered lane set, cherry-picked trials, new exclusions or unpaired historical medians.
7. For both A and B and both corpus sizes, `index_metrics[arm][str(N)]` has positive `index_ns/commit_ns/reopen_ns/index_bytes`, valid `segment_count`, and independent index path/byte-count evidence from staged metadata. Do not divide by a missing or zero denominator. These are descriptive, not sampled warm-query timestamps.
8. The only non-blocking information comprises host busy/steal/readiness and optional writer-footprint comparison; incorrect count/order/score-visible output, stale source or unstable A/A remains blocking. No source or harness change between the released binaries, staging and timed acquisition; source-only edits after timing invalidate further performance claims and require a human-authorized *new* result (not an automatic rerun).

### 7.2 Frozen B4 warm selection policy (evaluate on original, unrounded numbers)

**Primary lanes (all four required):**

- `100000/common/k10/warm`
- `100000/common/k100/warm`
- `100000/medium/k10/warm`
- `100000/medium/k100/warm`

Each primary **PASSES** only if `native status == "IMPROVED"`, `gain_percent >= 5.0`, and `gain_ci_95_percent[0] > 0.0`. This retains the approved 5% primary target used in the A-series; it is **not** a post-hoc threshold chosen after observing B4 samples.

**Guard lanes (all remaining 12 required):** a guard **PASSES** iff `gain_percent >= -10.0` and `gain_ci_95_percent[0] >= -10.0`, while all data remain finite and structurally qualified. This defines an explicit 10% allowed bound (matching previous cumulative A-series guard policy); an `INCONCLUSIVE` native label may still pass a guard but must remain visible. No positive primary can compensate for one failed guard. All 4 primaries + all 12 guards ⇒ `TARGETS_MET`. Anything else with a valid complete run ⇒ `TARGETS_NOT_MET`. Missing/invalid/incomplete data ⇒ `INCOMPLETE_VERIFICATION_BLOCKED`, not an unfavorable-comparison verdict.

**Analysis treatment:** interpret signed gain as `100*(1−median paired B/A ratio)`, so **positive means B is faster**; ratio B/A above 1 means slower. The `gain_ci_95_percent` is the native percentile bootstrap interval for paired whole-block ratios. Do not derive confidence intervals by treating the 20 correlated per-slot samples as independent or by averaging unpaired medians.

**Boundaries:** All numeric targets are **selection recommendations**, not automatic merge/rollback permission. An `A/A` FAIL, oracle mismatch or incomplete campaign is a **validity stop**; a qualified 4-primary/12-guard miss is a **performance outcome**, preserved without retry. Host-stability readings are **always advisory**, even when the observed busy/steal crosses the original ceilings; disclose the values and possible interpretation limitation in the final report but do not change the qualified status solely for them.

### 7.3 Mechanical verification helper — exact reference implementation

Create `docs/pr-artifacts/perf-06-b/b4/support/verify_b4_result.py` with this bounded standard-library implementation. It is a **read-only result verifier**, not a unit-test suite and not a benchmark runner. It must not modify any config/result or produce extra samples. The helper receives **three arguments**: config JSON, result JSON and native read-only analysis JSON. Do not generalize the helper or add packages:

```python
#!/usr/bin/env python3
import json
import math
import sys
from collections import Counter
from pathlib import Path

CONFIG, RESULT, ANALYSIS = (Path(s) for s in sys.argv[1:4])
c = json.loads(CONFIG.read_text(encoding="utf-8"))
r = json.loads(RESULT.read_text(encoding="utf-8"))
a = json.loads(ANALYSIS.read_text(encoding="utf-8"))
assert a == r["analysis"], "native read-only reanalysis disagrees"
assert r["schema"] == "benchmark-result-v1"
assert r["family"] == c["family"] == "perf-06"
assert c["name"] == "quervant-perf06b4-paired-warm"
assert c["policy"]["readiness"]["mode"] == "advisory"
assert c["policy"]["readiness"]["max_busy_percent"] == 25
assert c["policy"]["readiness"]["max_steal_percent"] == 2
assert c["policy"]["blocks"] == 12 and c["policy"]["slots_per_arm"] == 2
assert c["policy"]["warmups"] == 5 and c["policy"]["samples"] == 20
assert c["policy"]["exclude_blocks"] == {}
assert r["configuration_id"] == c["configuration_id"]
assert r["configuration"] == c
assert r["context"]["host_readiness_mode"] == "advisory"
assert r["context"]["build"]["arm_source_revisions"] == {
    k: c["arms"][k]["revision"] for k in ("A", "B")}
assert r["configuration_file"] == CONFIG.name
classes = ("absent", "rare", "medium", "common")
lanes = {f"{n}/{cls}/k{k}/warm" for n in (10000, 100000)
         for cls in classes for k in (10, 100)}
assert {x["id"] for x in r["lanes"]} == lanes
assert set(r["analysis"]["lanes"]) == lanes
assert set(r["controls"]["analysis"]["lanes"]) == lanes
assert r["status"] == "COMPLETE", f"incomplete result: {r['status']}"

def check_records(rows, arms):
    assert len(rows) == 768, f"expected 768 raw records, got {len(rows)}"
    counts = Counter()
    for x in rows:
        key = (x["lane_id"], x["arm_id"], x["block"])
        assert x["lane_id"] in lanes and x["arm_id"] in arms
        assert type(x["block"]) is int and 1 <= x["block"] <= 12
        assert type(x["position"]) is int
        assert x["oracle_ok"] is True and x["warmups"] == 5
        assert len(x["samples_ns"]) == 20
        assert all(type(t) is int and t > 0 for t in x["samples_ns"])
        counts[key] += 1
    for lane in lanes:
        for arm in arms:
            for block in range(1, 13):
                assert counts[(lane, arm, block)] == 2, (lane, arm, block)

check_records(r["raw_samples"], {"A", "B"})
check_records(r["controls"]["raw_samples"], {"AA", "AA2"})
for lane in lanes:
    aa = r["controls"]["analysis"]["lanes"][lane]["comparisons"]["AA2"]
    assert aa["status"] == "PASS", (lane, aa)
for arm in ("A", "B"):
    for n in (10000, 100000):
        m = r["index_metrics"][arm][str(n)]
        assert all(type(m[key]) is int and m[key] > 0
                   for key in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"))
        assert type(m["segment_count"]) is int and m["segment_count"] > 0
primaries = {f"100000/{cls}/k{k}/warm"
             for cls in ("common", "medium") for k in (10, 100)}
out = {"result_status": r["status"], "host_readiness_mode": "advisory",
       "primary": {}, "guard": {}, "all_targets_met": True}
for lane in sorted(lanes):
    t = r["analysis"]["lanes"][lane]["comparisons"]["B"]
    assert t["status"] in ("IMPROVED", "REGRESSED", "INCONCLUSIVE")
    point = t["gain_percent"]
    ci = t["gain_ci_95_percent"]
    assert isinstance(point, (int, float)) and math.isfinite(point)
    assert len(ci) == 2 and all(isinstance(z, (int, float)) and math.isfinite(z) for z in ci)
    assert ci[0] <= ci[1]
    passed = (t["status"] == "IMPROVED" and point >= 5 and ci[0] > 0
              if lane in primaries else point >= -10 and ci[0] >= -10)
    dest = out["primary"] if lane in primaries else out["guard"]
    dest[lane] = {"passed": passed, "native_status": t["status"],
                  "gain_percent": point, "gain_ci_95_percent": ci}
    if not passed:
        out["all_targets_met"] = False
assert len(out["primary"]) == 4 and len(out["guard"]) == 12
print(json.dumps(out, indent=2, sort_keys=True, allow_nan=False))
```

If the result has `INCOMPLETE`, this helper deliberately raises at `status`: do not alter it to make the result look qualified. Instead label the incomplete status and preserve raw data. Because the helper is a read-only checker on actual acquired data, the user's blanket exclusion of unit/integration suites does not prohibit invoking it. Record the exact script SHA and output. Only a bounded compatibility correction to parse an actual documented BM-10 field is permissible under D39; a different estimator or weakened assertion is not.

Invoke after `analyze`:

```bash
python3 docs/pr-artifacts/perf-06-b/b4/support/verify_b4_result.py \
  "$CONFIG" "$RESULT_JSON" docs/pr-artifacts/perf-06-b/b4/read-only-analysis.json \
  > docs/pr-artifacts/perf-06-b/b4/verification.json
```

---

## 8. Invariants, negative cases, and explicit uncertainty

| ID | Required invariant | Positive check | Negative or STOP check |
|---|---|---|---|
| B4-I01 | A is last pre-B1 accepted revision; B is accepted post-B3 revision | Git ancestry, merge metadata, exact pinned 40-hex SHAs, compiled arm provenance | A/B same SHA, unmerged B3, unreviewed source mutation ⇒ STOP |
| B4-I02 | Real native string sort semantics, not numeric-surrogate field | `expected_answer` counts and ordered IDs for every arm/lane/warmup/sample | Any discrepancy ⇒ INCOMPLETE, no numerical verdict |
| B4-I03 | Independent A/B indexes and release binaries | staged source/build/index identities and separate corpus builds | reused index between arms or missing digest ⇒ STOP |
| B4-I04 | Readiness informative only, real observations preserved | config `mode=advisory`, report `busy/clear/unavailable` unchanged | `busy` abort, `clear` forgery or `check_host=False` ⇒ STOP |
| B4-I05 | Source/host capability and A/A control still binding | native two-core/taskset, all 16 AA2 PASS | unavailable toolchain, A/A FAIL ⇒ INCOMPLETE, no treatment claim |
| B4-I06 | Paired 12-block, 2-slot, 5+20, 16-lane acquisition | 768+768 records; reanalysis equality | missing sample/slot or bad estimator ⇒ INCOMPLETE |
| B4-I07 | Actual warm engine_ns excludes open/build | native `collect_slot`, independent build_index | conflating build/open/RSS with query latency ⇒ STOP |
| B4-I08 | Immutable permanent config/result naming | new UUID, exclusive result publication, exact run id | overwrite, source mutation after treatment, silent retry ⇒ STOP |
| B4-I09 | Resource impacts are separate diagnostics | writer/commit/reopen/bytes per size and arm | unsupported compaction/RSS claim ⇒ report limitation, not invention |
| B4-I10 | Historical rejection remains negative evidence | no mutation to old results/reports | relabel 15H-C, 15I-D1-F, old A6 ⇒ STOP |
| B4-I11 | New B4 policy frozen before timed run | 4 primaries/12 guards as §7.2 | favorable post-hoc threshold/selection ⇒ STOP |
| B4-I12 | Host idle is given; instability observation can affect interpretation, not qualification | record observed percentages + caveat | auto abort on busy, automatic host intervention ⇒ STOP |
| B4-I13 | No ordinary test/quality suites are run | command ledger has only source inspection, validate, stage, run, analyze/report/verification | `cargo test`, lint, pytest, CI-gate requirement ⇒ prohibit, do not run |
| B4-I14 | No automatic merge/promotion or next series | maintainer G10 open | B4 agent marks accepted or starts C1 ⇒ STOP |

**State/failure boundaries:** `UNCONFIGURED → CONFIG_CREATED → CONFIG_COMMITTED → STAGED → STARTED → RESULT_PUBLISHED → REANALYZED → REVIEW_READY`. A stage/cache failure cannot advance to STARTED; a STARTED marker is irreversible permission accounting; a published INCOMPLETE never becomes COMPLETE through manual editing. Advisory busy/unavailable is explicitly *not* a state transition or STOP. A/A and oracle failure are blocking. Canceled/interrupted processes preserve the marker and partial evidence. A process crash before result publication must be disclosed; do not fabricate a result or rerun automatically. Zero/one-hit/medium/common exercise different paths; the 16 native oracles supply those negative and positive cases; no separate test suite is required. No new storage or remote durability transitions exist in B4.

---

## 9. Preauthorized Architectural Decisions and Exception-Handling Matrix (52 binding rules)

**Categories:** `AUTO-RESOLVE` acts immediately within the exact source condition; `DEFER AND CONTINUE` records a blocked dependent gate while safely proceeding with unrelated authorized work; `HARD STOP` stops affected work and requests maintainer authorization, stopping the entire acquisition if isolation is impossible. For every applied rule record ID, observed condition, action, prohibited alternative, evidence path and affected gate in the report. Unmatched semantic/design decisions ⇒ **HARD STOP D52**, never agent improvisation.

| ID | Observable trigger / source check | Category | Exact authorized action | Forbidden action | Evidence / gate / owner |
|---|---|---|---|---|---|
| D01 | PR #128 actually merged, main has accepted B3 and 480a ancestor | AUTO-RESOLVE | Pin B_SHA once; use branch based on it | use unmerged PR head or older B | Git/PR identities G0 agent |
| D02 | B3 is not merged or pre-B1 baseline not ancestor | HARD STOP | Preserve plan; request maintainer B3 merge/lineage resolution | act on unmerged implementation | G0 maintainer |
| D03 | Post-B3 main differs from reviewed source only in docs/evidence | AUTO-RESOLVE | Record blob diff and use actual main SHA | substitute earlier tested commit silently | G0 agent |
| D04 | Task-owned B4 branch/config already exists and is compatible | AUTO-RESOLVE | Resume from existing immutable artifacts and markers, never create second | force reset or duplicate config | G0/G8 agent |
| D05 | Unreviewed production/adapter/config changes since accepted B3 | HARD STOP | Record exact changed paths/source blobs | treat branch as accepted | G0 maintainer |
| D06 | Foreign tracked/untracked changes block branch switch or clash with allowlist | HARD STOP | Preserve them and report paths | stash/delete/reset other person's work | G0 owner |
| D07 | Only task-owned clean new B4 branch needed | AUTO-RESOLVE | Create once from B_SHA; normal fast-forward push | amend B3 or create second PR | G0/G9 agent |
| D08 | A or B source object missing/ambiguous | HARD STOP | Obtain missing legitimate commit locally via standard `git fetch` once; if still missing halt | use branch name/short SHA guess | G0 agent/maintainer |
| D09 | Exact original benchmark tool exists as inspected | AUTO-RESOLVE | Reuse PERF-06 family paired flow | implement custom scheduler | G1 agent |
| D10 | Host-readiness `busy` at any native checkpoint | AUTO-RESOLVE | Record true readings, continue | reject samples, change ceiling, switch host | G3/G5 agent |
| D11 | Host readiness counter unavailable/observation throws `MeasurementBlocked` | AUTO-RESOLVE | Store `status=unavailable`, reason, continue | fabricate clear/missing reading | G3 agent |
| D12 | Linux/native filesystem/two-core/taskset or Rust toolchain unavailable | HARD STOP | Stop acquisition on technical host prerequisite | `check_host=False`, unpinned timing, WSL drive move | G3 operator |
| D13 | `quervant-bench` executable absent but canonical module resolves | AUTO-RESOLVE | Use `PYTHONPATH=benchmarks python3 -m quervant_bench` consistently | install new harness/deps or guess CLI args | G2 agent |
| D14 | Neither installed CLI nor canonical module available | HARD STOP | Report missing operator dependency | pip-install unknown versions | G2 operator |
| D15 | Existing native readiness thresholds are exactly 25/2 | AUTO-RESOLVE | Preserve numbers and add `mode=advisory` to new config only | set thresholds 100 or fake clear | G1 agent |
| D16 | Advisory mode requested for non-perf-06 family | HARD STOP | Validator rejects request | enable global readiness bypass | G1 maintainer |
| D17 | Unexpected mode value / malformed advisory config | HARD STOP | Reject configuration and report cause | silently coerce mode to advisory | G2 agent |
| D18 | Need to change scheduler, adapter, statistics or metadata codec to support advisory | HARD STOP | Stop and request new design | change protected files | G1 maintainer |
| D19 | Existing perf-06 paired control can use A/AA/AA2 | AUTO-RESOLVE | Preserve original A/A analysis and binding stop | move/skip A/A control | G5 agent |
| D20 | CLI creates one new UUID/date/name/path | AUTO-RESOLVE | Record exact config stdout, validate, commit once | glob select older config, rewrite UUID | G2 agent |
| D21 | Durable start marker exists | HARD STOP TIMING | Never invoke real `run` again; read existing result if any, otherwise report interrupted | remove marker/retry | G5 maintainer |
| D22 | Stage returns BUILT or cache HIT and all oracles pass | AUTO-RESOLVE | Proceed to single run after start marker | rebuild just for aesthetics | G3 agent |
| D23 | Stage cache reused, verified fingerprints/identities match | AUTO-RESOLVE | Keep cache HIT and actual provenance | delete cache and re-stage | G3 agent |
| D24 | Stage cache corrupt/inconsistent | HARD STOP | Record cache path/diagnostic; no timing | delete published cache while in use | G3 maintainer |
| D25 | Index A/B bytes differ due to B1 format | AUTO-RESOLVE | Preserve independent indexes, compare logical oracle + bytes descriptively | require equal digests | G3/G7 agent |
| D26 | Either corpus count/oracle mismatches on stage | HARD STOP | Stop before timing; preserve evidence | skip lane or change corpus | G3 agent |
| D27 | Writer/commit/reopen metrics valid but differ | AUTO-RESOLVE | Record separate diagnostics | treat as timed-query samples | G7 agent |
| D28 | Writer/commit/reopen metrics invalid/missing/zero | HARD STOP | Stop qualified report; preserve result if already started | invent values | G7 agent |
| D29 | Host busy across any timing block but oracles/A/A pass | AUTO-RESOLVE | Continue native schedule, annotate busy magnitude in report | prune/retime/switch host | G5/G7 agent |
| D30 | A/A control has one or more non-PASS lanes | HARD STOP FURTHER TIMING | Preserve runner's INCOMPLETE result; do not start treatment/retry | ignore invalid A/A | G5 agent/maintainer |
| D31 | A/A PASS, paired treatment runs | AUTO-RESOLVE | Complete all frozen 12 blocks, record every sample | manual early stop on expected unfavorable result | G5 agent |
| D32 | Requested essential code or file outside allowlist | HARD STOP | Stop affected task and seek new plan | broaden file edits autonomously | G1 maintainer |
| D33 | Treatment oracle failure or invalid engine_ns | HARD STOP FURTHER TIMING | Preserve INCOMPLETE native result, error | skip corrupt sample/lane | G5 agent |
| D34 | Result status INCOMPLETE | DEFER AND CONTINUE | Preserve immutable result and read-only diagnostics, report BLOCKED; no more acquisition | change status/retry | G6 maintainer |
| D35 | Result status COMPLETE, all native control/oracle checks good | AUTO-RESOLVE | Perform read-only B4 selection policy | claim automatic adoption | G6/G7 agent |
| D36 | A primary fails >=5% and >0 CI criterion | AUTO-RESOLVE | Mark TARGETS_NOT_MET, preserve all evidence | lower threshold to observed value | G7 agent |
| D37 | Any guard fails >=-10% point/lower-CI criterion | AUTO-RESOLVE | Mark TARGETS_NOT_MET, preserve all evidence | average failed guard away | G7 agent |
| D38 | All 4 primaries/12 guards meet frozen criteria | AUTO-RESOLVE | Mark TARGETS_MET_REVIEW_REQUIRED | merge or assert per-stage causality | G7 agent |
| D39 | Read-only verifier detects a genuine documented field-name mismatch | DEFER AND CONTINUE | Record exact schema and propose bounded parser-only correction, continue reporting other data; no changed gates | weaken predicates, invent fields | G7 maintainer |
| D40 | Recomputed `analysis` differs from stored analysis | HARD STOP | Report exact lane/value and preserve bytes | override stored statistics | G7 maintainer |
| D41 | Number of records, blocks, samples or warmups differs | HARD STOP | Mark validity incomplete and preserve | exclude blocks/alter declared schedule | G6 agent |
| D42 | Result has source SHAs not exactly frozen A/B | HARD STOP | Preserve and report source mismatch | substitute run source or rewrite result | G6 maintainer |
| D43 | Result directory name collision / old sequence occupied | AUTO-RESOLVE | Let native exclusive allocator choose next suffix once | overwrite/rename previous results | G6 agent |
| D44 | Source/test quality CI is pending or red for unrelated existing checks | DEFER AND CONTINUE | Record status informational only; user excluded suites/quality reruns | require CI before acquisition | G9 agent |
| D45 | `cargo test`, `pytest`, lint, coverage, format or integration QA requested by usual guidance | AUTO-RESOLVE | Skip suites and record user override | run them against stable main | G9 agent |
| D46 | Only docs/result/report commits since stage/build source | AUTO-RESOLVE | Verify protected source diff empty; reuse source evidence | regenerate samples | G9 agent |
| D47 | Actual executable/benchmark-tool change after time window | HARD STOP | Flag result source-inconsistent, preserve it | reinterpret as same treatment | G6 maintainer |
| D48 | An unplanned external timer, profiler or RSS source is requested | HARD STOP | Report out-of-scope diagnostic limitation | start extra sampling or benchmark | G7 maintainer |
| D49 | Historical A6/15H-C/15I-D1-F results differ from B4 | AUTO-RESOLVE | Keep historical outcomes intact; compare context narratively only | historical causal pairing or overwrite | G7 agent |
| D50 | Result valid but speedup unfavorable | AUTO-RESOLVE | Deliver `TARGETS_NOT_MET_REVIEW_REQUIRED`, no rollback or retime | cherry-pick better blocks | G7/G10 agent |
| D51 | Successful reporting and PR push, G10 still open | AUTO-RESOLVE | Leave draft PR review-ready; await maintainer merge decision | mark B complete and start C1 | G9/G10 maintainer |
| D52 | Any unforeseen source/host/schema/semantic condition not matched above | HARD STOP | Preserve state, show smallest evidence-backed maintainer decision; continue independent safe docs only | invent new architecture, work around STOP | relevant gate maintainer |

The above matrix deliberately treats **host CPU load** as informational but retains structural-host, actual oracle, A/A statistical, source and data-integrity conditions as binding. No row authorizes a second timed invocation.

---

## 10. Ordered autonomous phases and acceptance gates

| Phase / gate | Exact work | Acceptance and evidence | Failure |
|---|---|---|---|
| P0 / G0 | Verify merged B3/main/pre-B1 A, local branch/ownership, clean source, record exact Git/tree identities | `preflight.txt`, A/B SHA, diff/merge proof | HARD STOP identity conflict |
| P1 / G1 | Apply only advisory harness source edits and docs, freeze 4/12 policy before running | code source inspection, `mode=advisory` and untouched default/AA; **no test suites** | STOP unapproved behavioral edit |
| P2 / G2 | Commit tooling, create one CLI config and validate it; commit config | distinct UUID, generated UTC filename, fixed A/B/16 lanes, no old overwrite | STOP malformed config |
| P3 / G3 | `stage` once using exact config/scratch; observe host optionally busy, build both arms/indexes and native oracles | `stage.log`, cache identity, index metrics and all untimed oracles | stop if build/source/oracle invalid |
| P4 / G4 | Durable start marker (exclusive); freeze branch, source, config, stage key | one started marker with source/config/command | no timing if marker existed |
| P5 / G5 | Exactly one native paired `run` (A/A first, then A/B if controls PASS); host readiness advisory | immutable result path, complete raw records, native analysis; if error preserve `INCOMPLETE` | no retry |
| P6 / G6 | Read-only verify result schema/provenance/all samples/A/A/oracles and reanalysis | 768+768 records, controls all PASS, exact source, stored-vs-reanalyzed equality | result invalid ⇒ BLOCKED |
| P7 / G7 | Apply frozen 4-primary/12-guard thresholds; summarize writer/footprint separately | exact point/CI values, host actual observations, verdict and limitations | unfavorable is real evidence |
| P8 / G8 | Commit evidence only, verify `TESTED..FINAL` has no changes to `crates`, adapter, runner, config, sampling code | source identities and immutable two data artifact types preserved | STOP changed test/source post-acquisition |
| P9 / G9 | Open/push B4 draft PR with report, config/result; no suites/lint, no CI gate; user override visible | one PR link and exact source/report/result paths | block only if real repo action unavailable |
| P10 / G10 | Maintainer accepts/rejects B4 and decides whether B-series becomes PERF-06-C baseline | **MAINTAINER ONLY** | Agent never merges |

### Independent reviewer checklist

1. Is A precisely `480a77e78c6897e05cb7ceb76b01434974b82ec6` and B actually accepted post-B3 `main`? Does source testing provenance not introduce a hidden later engine change?
2. Did the new advisory config preserve actual CPU observations, leave two-core/taskset structural checks intact and **not** relax A/A statistical controls?
3. Did the agent avoid all broad unit/integration suites and quality checks per explicit user instruction, while still executing real **benchmark** oracles and validators?
4. Were independently pinned A and B built separately with `--release --locked`, no experimental feature? Are the indexes independent and logically identical despite differing bytes?
5. Are 16 lanes, 12×2 slots per arm, 5 warmups, 20 timed samples, randomized schedule and 10K whole-block bootstrap faithfully preserved?
6. Do oracle checks cover every warmup/sample, with exact ordered logical IDs and hit counts, real native UTF-8 sorting, and unchanged cursor/result semantics?
7. Is A/A good on **all 16 lanes** before treatment? Is host busy/unavailable **advisory only** without a fake `clear`?
8. Was real timed acquisition invoked exactly once, with a durable marker, and did the runner exclusively save one configuration-linked result? If incomplete, was it preserved without retry?
9. Does read-only analysis reproduce the stored analysis? Did the agent apply the original unrounded 4-primary/12-guard gates with no cherry-picking or changed thresholds?
10. Are `index_ns`, `commit_ns`, `reopen_ns`, `index_bytes` explicitly *untimed diagnostics* and not included in search latency, and is no unsupported RSS/compaction claim made?
11. Does the report distinguish COMPLETE structural validity, numerical targets, historical unpaired comparisons, host observations, source identities and G10 maintainer approval?
12. Did the agent refrain from automatically accepting, rolling back B1–B3 or starting C1?

### Required report outline (write all, not a status-only summary)

- Experiment hypothesis, why A/B (not B-only) was chosen, exact work, exclusions and user-authorized host/QA overrides.
- Post-B3 merge and source SHA identities; `A_SHA`, `B_SHA`, B4 branch, adapter build/source revisions, protected diffs.
- Configuration file, UUID, created UTC, policy and entire immutable 16-lane register.
- Host capabilities versus readiness observations; actual `clear/busy/unavailable` at every checkpoint; A/A PASS/FAIL separately.
- Stage corpus/build/commit/reopen/index-bytes per arm and N, independent oracle results, no extra writer experiment.
- Acquisition marker, one exact command, exit code, exact `run_id` and result path/status, number of slots and samples, exact source/tree and any errors.
- Per-lane table: A median block absolute ns, B median block absolute ns, paired B/A median ratio, gain percent, 95% gain CI, native status, frozen B4 primary/guard gate and reason.
- Summary of 4 primaries and 12 guards; `TARGETS_MET`/`TARGETS_NOT_MET`/`INCOMPLETE` qualification disposition; avoid universal performance or causal attribution.
- Exact read-only reanalysis agreement, result verifier evidence, immutable configuration/result names and any genuine STOP rules.
- Prior 15H-C and 15I-D1-F negative outcomes remain historical; B4 contributes *cumulative* B evidence only. Accepted main, PR draft status, G10 OPEN, no CI prerequisite and no B4 rerun.

**Final instruction:** run everything authorized in this plan without requesting routine approvals. If a new condition is not in D01–D52, STOP the affected work and report a concrete, minimal maintainer decision. Preserve every created artifact and original result. Never invent a source identity, sample, control, oracle, performance ratio, test pass, or human approval.
