# PERF-06-C4 — Integrated C-series paired warm-performance qualification

**Repository:** `yduchesne/quervant`  
**Work item:** PERF-06-C4 (measurement and documentation only)  
**New branch:** `dev/perf06-c4`  
**PR:** create one new draft PR against `main`; discover its actual number after creation, never assume #133.  
**Plan date:** 2026-11-27 UTC  
**Acquisition budget:** exactly one invocation of the existing BM-10 `perf-06/warm` runner; one built-in A/A phase and, only if A/A passes, one paired A/B treatment phase. No additional timing campaign.

## 0. Authority, explicit user overrides, and continuous execution

Execute this document as a closed design. The coding agent is an executor, not the experiment designer. The purpose is to measure the integrated C2+C3 effect on top of accepted A+B, not implement another optimization or modify the measurement framework.

**Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval. Anything outside the decision matrix in §11 is a HARD STOP; do not invent a decision.

### 0.1 Task-scoped maintainer instructions (override general plan defaults)

| Instruction | Exact operational consequence |
| --- | --- |
| Assume merged `main` stable. | Reuse C2/C3 independent review and executed correctness/CI evidence. No new implementation, no baseline QA rerun. |
| No unit/integration suites or quality checks. | Do **not** execute `cargo test`, `pytest`, `cargo clippy`, `cargo fmt`, `cargo llvm-cov`, `cargo doc`, `cargo bench --no-run`, `test-scripts.sh`, adapter unit tests, RustFS test harnesses, coverage or other general QA. No new tests. Mark these `NOT RUN — USER-AUTHORIZED C4 WAIVER`, not PASS. |
| Assume the host is idle, available, and ready. | No separate idle check, qualification run, quiet-period wait, load-probe loop, manual authorization, service shutdown, or confirmation request. |
| Host stability check informative only. | Use the already implemented `prepare --readiness-advisory` for `perf-06`. Preserve actual readiness observations including `busy` and `unavailable`; neither status blocks, prunes, changes the result classification, nor triggers another run. |
| Do not redesign. | No production, test, adapter, framework, Cargo, workflow, compiler optimization, workload or statistical-code changes. Any actual defect needing changes stops this plan. |

The waiver is specific to C4 and does not change permanent repository testing policy. Benchmark configuration validation, real release adapter compilation, index creation/reopen, independent per-lane and per-query oracles, built-in A/A, and read-only analysis of the actual acquisition **remain required**. These are the work of the benchmark itself, not separate unit/integration/quality suites. Do not disable them.

**Important distinction:** host readiness observations are advisory. The paired **A/A experimental equivalence control** is not a host-load gate; it remains binding under the existing runner and the B4 precedent. A/A FAIL means the runner cannot establish its required measurement-system control; preserve its `INCOMPLETE` result and do not run treatment. Do not implement a bypass. Structural prerequisites (supported Linux host/filesystem, usable compiler and two available distinct physical cores with `taskset`) remain necessary for the executable to run. Do not treat an actual operational failure as an advisory load observation.

The agent is authorized to create the branch, configuration, run the one acquisition, analyze and report the saved result, commit the bounded artifacts and open a draft PR. No additional human checkpoints before/during this work. No automatic merge, ready-for-review transition, rollback, baseline promotion, or changes to `main` are authorized. Routine hosted CI may run automatically on opening the draft PR; do not initiate, duplicate, wait for, rerun, cancel or gate this acquisition/delivery on hosted CI. Report its actual status if visible, not an invented pass. Leave workflows unchanged.

## 1. Current-main reconciliation and pinned identities

Fresh GitHub verification during authoring established the following. PR #132 (C3 including F1/F2) is **merged**, not merely ready for review. Old status notes in historical documents predate the merge; use the actual Git identities and append dated status facts, not retroactive edits.

| Role | Immutable full commit SHA |
| --- | --- |
| **Arm A** — merged PERF-06-B4, accepted A+B, pre-C baseline, PR #129 | `8c9f51f311afa5b327f70432e32c0f6f5c205eab` |
| C1 merged architectural contract (doc-only) | `bc726420cede2e26681d6e8192b45a5d0169abbf` |
| C2 merged, PR #131 | `6bc977e6a26c183609b7ca53eca51d3ab09ce337` |
| C3/F2 tested source | `e4816c51f0063383596e8ee8a644b38d7a39a400` |
| C3 final reviewed PR head | `c7ba5c5f899626e1de654e3a47ebc9a059f7292a` |
| **Arm B** — merged C3/F1/F2, PR #132, fresh `main`; also **START / runner checkout** | `f169fbba93e10d174cad8ab3bca55cdb7ae6aa03` |
| B Git tree | `be6f2a3f000ebbcab80e2985a34316401524c614` |

PR #132 merged at 2026-11-27T21:39:34Z according to GitHub. Its final-head ordinary CI run 46066729122 passed all five jobs; actual RustFS log had 32 successful result summaries totaling 65 passes across invocations. F2 local acceptance used 45 verified commands and reported line coverage 93.53% / 93.13%, both above 85%. Historical evidence is not a claim that C4 reran those checks. The two reviewed F2 edits were test-only. The C2-A2 counter repair is test-only. See the source and evidence links in §13.

The verified B4 result was measured against the **pre-B1** arm, not the C-series baseline: historical arm A=`480a77e78c6897e05cb7ceb76b01434974b82ec6`; historical arm B=`d660ca9f487d5c54363d790a240abb7da30af245` (post-B3 merged source). B4's merge added the advisory-readiness framework capability, documentation and benchmark artifacts; no new engine work. The B4 merge SHA is the canonical accepted source for C4 A. Do not substitute the old B4 arm A or a pre-PERF-05 baseline, nor the merged C2 alone, for C4 A.

### 1.1 Reuse decision (fixed, not delegated)

C1 §7 calls for one separately approved 16-lane warm experiment against merged A+B. B4 used a two-revision paired run. This plan specifies the same native two-pinned-arm `perf-06/warm` path with **A=B4 merge** and **B=C3 merge**. The historical B4 candidate is useful context (B3 and B4 engine bytes agree), but its saved absolute times are from another session and its pinned source is not the exact B4 merge object. A B-only reuse would be descriptive/unpaired and would not provide the prescribed same-session incremental confidence interval. Also `perf-05` is the existing specialized B-only family with its own hardwired historical reference; `perf-06` does not expose a generic B-only mode. Do not add one or misuse `perf-05`. This is a deliberate plan-author choice of **one** paired experiment, not a second campaign after B-only, and not a cross-engine run.

### 1.2 What has already been delivered

| Area | State before C4 | Action |
| --- | --- | --- |
| PERF-06-A/B accepted primitives | MERGED; B4 qualified and accepted | Preserve exactly. |
| C1 strict physical-family contract | MERGED | Preserve normative contract. |
| C2 exact-count/Top-K execution | MERGED; independently correctness-reviewed | No edits, no repeat acceptance campaign. |
| C3 guarded deferred BM25 | MERGED; independently correctness-reviewed with F1/F2 | No edits, no repeat acceptance campaign. |
| `perf-06/warm` two-pinned-arm runner and advisory readiness | Implemented and previously used by B4 | Reuse unchanged. |
| C4 configuration/result | Not created at authoring | Create only the new configuration and its one result. |
| C-series performance acceptance | Not yet measured | Decide from this run; maintainer owns adoption. |

### 1.3 Actual code and existing framework inspected

The following anchors are at START unless stated otherwise. Verify these Git blobs locally (ordinary provenance, not a new receipt/attestation system):

| Path | Git blob |
| --- | --- |
| `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |
| `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` | `d66876b7ba43674f04d210207df43f8857f5fe00` |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | `fc50b800550d6f523859992c0e0c97504e9e874b` |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | `3c9fba8f5a62ef8ac543c6c7f1b24494369def78` |
| `benchmarks/quervant_bench/lean/cli.py` | `4367ec988e4386ffb7ddf5f588b77ddb7f049bb0` |
| `benchmarks/quervant_bench/lean/artifacts.py` | `dc5b52b70795967e5785254c9b0964a3dad04120` |
| `benchmarks/quervant_bench/lean/configuration.py` | `52b677f531a578352cfdc6ba6b953324825222a6` |
| `benchmarks/quervant_bench/lean/runtime.py` | `0edc0a536e697fb0b5e18709d23032ae4cd94dd1` |
| `benchmarks/quervant_bench/lean/preparation.py` | `486444318e9de8c3f4f45ba86badb4b28088f95d` |
| `benchmarks/quervant_bench/lean/statistics.py` | `7854fb8035128e425d00e6f4ad192f20d7a6c718` |
| `benchmarks/pr15d/adapters/quervant/src/main.rs` | `9e333e7d9be23d08802ae850b39bd3ffd2dfbf48` |
| `crates/quervant-core/src/search/unified.rs` (merged reviewed F2) | `cd2072960fa15ffd078335ca56264559d22ad018` |
| `crates/quervant-core/src/search/execute.rs` | `dbc863219716475db21cbb9739bf52557c2e61c3` |
| `crates/quervant-core/src/search/score.rs` | `7c181a556dca5f69614c739a466478a7bee0b7da` |
| B4 configuration (path in §13) | `87b8b33063ccfba1dc1e6ce9095c52aed2786643` |
| B4 result (path in §8) | `930e9a09887ecb0cf7de576a2de3670df71c482f` |
| A6 cumulative result (path in §8) | `f65afc6911fcc6b4fcf5c2c6f2999c439feb1bf2` |

Source facts:

- `configuration.py::default_configuration` already generates `perf-06` with pinned A/B, `by-top-k`, 12 balanced blocks, 2 slots per arm, 5 warmups, 20 samples, seed 20261122, 10,000 bootstrap resamples, and optional advisory readiness. CLI `prepare --readiness-advisory` is implemented; no runtime patch is needed.
- `runtime.py::build_programs` builds two independent Quervant release binaries from two detached worktrees, separate target dirs, `cargo build --release --locked`, no `pr15i-d3c-experiment` feature. Both arm revisions are recorded. Java is not required by the `perf-06` path. `runtime._strategy` removes both experimental strategy variables; default duplicate dispatch is linear at K10 and P2 prefilter at K100.
- `preparation.py::stage_inputs` uses committed build-source identity, automatic reuse, independent filesystem indexes, full-build count/reopen/byte validation and an untimed oracle for all 16 lanes in each arm. It admits `busy`/`unavailable` in advisory mode. `run` invokes this stage automatically. No separate `stage` command needed for a fresh run.
- `runtime.py::run_benchmark` reads actual host capabilities, uses two distinct available physical cores (`host_context`, `pinned_controller`, `taskset`), runs A/A aliases of A, validates each warmup/sample using `expected_answer`, then runs paired treatment. It preserves partial completed-slot records on a handled failure and publishes one `INCOMPLETE` result. `artifacts.py::publish_result` chooses dated sequential names and exclusively writes the immutable result. No authorization/integrity-approval machinery.
- `statistics.py::schedule` generates seeded position-balanced slots; `analyze` validates exact schedule, records, pairing, oracle status, computes native decimal median/ratios/bootstrap. `cli analyze` is read-only reanalysis; `report` only renders saved values.
- `benchmarks/pr15d/adapters/quervant/src/main.rs::search` invokes actual public `UnifiedSearcher::search` with one `Query::Term`, actual `doc_id` Keyword column ascending, `Projection::Fields(["doc_id"])`, `after=None`, default search limits. Timer covers search and building the owned returned IDs, excludes request/searcher setup, reader open, correctness comparison and JSON serialization. ReaderSnapshot is reused within each process/corpus group. The adapter checks each projected ID equals the logical key and IDs are strictly increasing. It does **not** export score bits or cursor values. Those contracts rely on merged C2/C3 correctness evidence; do not claim the benchmark proves them afresh or add an adapter feature to observe them.
- The C path selects only strict term/ordinal sort with M>K+1 after shared validation; `DeferredBm25` uses the already reviewed request-wide proof. A match is never skipped to stop at K. Absent/one-hit requests are expected to remain Legacy, medium/common eligible. The proof does not imply measured speedup. The C3 `MixedEntry` size grew 136→144 bytes in the tested 64-bit layout; C4 captures any whole-query effects with both sparse and dense lanes, not by adding a layout/profiling test.

## 2. Scope, invariants and ownership

### 2.1 Exact write allowlist

New files:

1. `docs/pr-artifacts/perf-06-c/PERF06C4_DETAILED_QUALIFICATION_PLAN.md` — this exact supplied plan.
2. One CLI-generated `benchmarks/studies/perf-06/warm/configurations/quervant-perf06c4-paired-warm-<creation-UTC-date>.json`.
3. At most one runner-published `benchmarks/studies/perf-06/warm/results/quervant-perf06c4-paired-warm-<execution-UTC-date>-001.json` (COMPLETE or INCOMPLETE; never fabricate a result if no file was published).
4. `docs/pr-artifacts/perf-06-c/PERF06C4_EXECUTION_REPORT.md` — compact, self-contained report per §10, including exact commands/status and tables. This is a PR explanation; the native configuration and result remain the two persisted benchmark artifact types. No third custom result schema or evidence bundle.

Append-only existing files (only dated C4 status notes after execution, no old text changed):

- `docs/PERF_OPTIMIZATION_ROADMAP.md`;
- `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`;
- `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` (status note only; no semantic-rule changes).

**Protected:** every other path, especially all `crates/**`, test sources, adapter trees and lockfiles, `benchmarks/quervant_bench/**`, benchmark scripts, existing config/result files, `.github/**`, `Cargo.*`, `.cargo`, Rust toolchains, `.gitignore`, prior C2/C3/F1/F2 evidence, all older negative evidence. No new persistent verification tool. A/B use identical accepted benchmark adapter and dependency source, different engine source. Use Appendix A as an ephemeral read-only report helper under task scratch, not a repository framework change. No ZIP, evidence manifest, seal, token, signed receipt or G0-approval cycle; BM-10 remains the direct runner.

### 2.2 Cross-component invariants and acceptance mapping

| ID | Invariant / failure counterexample | Required evidence | Stage |
| --- | --- | --- | --- |
| I01 | A and B are exact pinned immutable commits; no altered compiler profile, test seam, feature, forced route, adapter or query shape. A historical result or current code substituted for either arm invalidates the experiment. | Git identities, pinned configuration, native result build provenance; path comparison | P0/P1/P3 |
| I02 | Identical logical input corpus/queries, actual local real writers and readers. Wrong count, wrong projected key, wrong order/duplicate, malformed reply or missing index must fail. | Native stage: two corpora, four independent indexes, 32 real untimed lane/arm oracles; every warmup/sample checked | P2 |
| I03 | Complete immutable exact query count and ordered projection under identical `engine_ns` boundary; reader open/indexing excluded. | Inspected adapter, native reply/metric fields, result lanes | P0/P2 |
| I04 | Advisory host load is never a validity condition. No BUSY/UNAVAILABLE→clear rewrite, no policy change, no pause until clear. Structural execution prerequisites still required. | `policy.readiness.mode`, actual context + raw readiness entries; existing runner | P1/P2/P3 |
| I05 | A/A equivalence control uses A alone, exact same index/binary; 16 controls must pass before treatment. | Built-in control, 768 control records, complete native `controls.analysis` | P2/P3 |
| I06 | Treatment uses exact 12 blocks / 2 slots per arm / 16 lanes / 5+20; no omissions, duplicate slots, post-hoc pruning or selective samples. | Native schedule + `analyze`, exact raw shape and all 12 retained blocks | P2/P3 |
| I07 | C4 selection is incremental warm-only and uses predeclared point + interval policy on all lanes. A complete unfavorable run is not incomplete. | §5 numeric rules, Appendix A output, all 16 lane rows | P3/P4 |
| I08 | No production/API/format/codec/reader/mutation/cursor/score/accounting changes; those properties rely on accepted C2/C3. | Scope check vs B; accepted prior evidence; QA waiver explicitly labelled | P0/P4 |
| I09 | One acquisition only, immutable result, correct source/status, no performance promotion or merge by executor. | Single native `run`, saved result, explicit disposition, draft PR | P2/P4 |

**Ownership / lifecycle:** GitHub source A/B is read-only. Native runtime owns ephemeral detached worktrees, build dirs, generated TSV and four local committed indexes, one session snapshot per adapter process/corpus. Native preparation owns cache and validation. Native `publish_result` owns exclusive result naming/publication. Neither engine writes to the other arm's index; no durable application data or remote services. No format, mutation, distributed or object-store feature is touched. No new external dependencies, no mock programs/injected index builders or invoke_phase seam. The only independent oracle is the existing formula over the input rows and the public response IDs/count; the offline report helper checks stored observations and native statistics, not a second independent engine. Empty/singleton cases and high-hit cases are present; first-page only. Other query shapes, score errors, cancellation budgets, PIT updates, RustFS failure paths are covered by merged prior tests, not measured in C4. New unit/integration/fault-injection matrices and quality gates are explicitly waived for this measurement-only task.

### 2.3 State and failure boundaries

`PINNED_SOURCE → CONFIG_CREATED_VALID → PREPARATION → CONTROL → TREATMENT → RESULT_SAVED → ANALYZED → REPORTED → DRAFT_PR`.

- Preparation may fail before any timed sample; report actual failure and runner `INCOMPLETE` if written. If a native run has begun, it consumes the one authorized invocation even if no sample was captured. No automatic stage/run retry.
- A/A may fail: native runner saves completed control records and no treatment; no A/B gain. If failure occurs mid-slot, native runner preserves already completed slots, not necessarily every partially consumed response; do not invent missing samples.
- Treatment may fail or be interrupted: `INCOMPLETE` or no published JSON (e.g. abrupt kill/disk failure); preserve native result and logs if present, report incomplete, no retry, no manually constructed result JSON. Do not fabricate a `COMPLETE` acquisition from partial samples.
- COMPLETE can have `IMPROVED`, `REGRESSED`, `INCONCLUSIVE` native lane decisions. It is still COMPLETE when thresholds miss. Source stays unchanged. Unsupported/non-comparable/invalid observations are validity failures; do not treat them as measured performance losses.
- Remote push/PR failure after result publication does not change local measured result. Retain local artifacts, report exact blocker. No replacement acquisition. If a PR exists already for this task but no run is proven, do not create another one or restart; apply D02.

## 3. P0 — Admission and fixed pre-acquisition worksheet

### 3.1 Source and environment setup

Run from the repository root on the user's existing Linux/WSL2 host. Use the existing installed Python and Rust tools. No installer, dependency update, `cargo update`, unlocked build or modified flags. Use `PYTHONPATH` for the checked-out CLI, rather than an installed stale entrypoint.

```bash
set -euo pipefail
A=8c9f51f311afa5b327f70432e32c0f6f5c205eab
B=f169fbba93e10d174cad8ab3bca55cdb7ae6aa03
BRANCH=dev/perf06-c4
NAME=quervant-perf06c4-paired-warm
D=docs/pr-artifacts/perf-06-c
STUDY=benchmarks/studies/perf-06/warm
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
# Use a native Linux filesystem; target is repository-local ignored scratch.
mkdir -p target
W=$(mktemp -d "$ROOT/target/perf06-c4.XXXXXXXX")
export W A B ROOT NAME STUDY
export PYTHONPATH="$ROOT/benchmarks"
export RUSTUP_TOOLCHAIN=1.98.1
unset QUERVANT_PR15I_D3C_STRATEGY QUERVANT_PR15I_D3C_PREFILTER_PROFILE
```

Do not set optimization or CPU-specific flags. Verify no non-default build/profile/compiler wrapper, `RUSTFLAGS`, `CARGO_ENCODED_RUSTFLAGS`, `CARGO_PROFILE_*`, alternative compiler/linker or shadow Cargo config would cause asymmetric or instrumented builds. Do not expose environment secrets. Stop if an unexpected override is present; do not delete user environment settings or rewrite Cargo configuration. Pin Rust 1.98.1 for both arms (the B4/merged-C3 toolchain) via the one exported `RUSTUP_TOOLCHAIN`. `python3 --version`, `rustc --version`, `cargo --version`, `git --version`, `findmnt -T "$W" -n -o FSTYPE` are operational provenance, not quality checks. No `cargo test` or pre-commit quality hook invocation. The native runner performs the required structural host checks. No custom busy polling.

Fetch refs: `git fetch origin main`. Confirm repo/remote identity without exposing credentials, `origin/main == B` and `git cat-file -t "$A"`/`"$B"` both `commit`. Confirm `git merge-base --is-ancestor "$A" "$B"`. Verify PR #129 and #132 are merged at A and B respectively (e.g. `gh pr view 129 --repo yduchesne/quervant --json state,mergedAt,mergeCommit` and same for 132). If GitHub metadata inaccessible but already available matching Git parents and immutable refs, record actual missing metadata under D21 and continue only the local work whose source identity is established; do not guess merge status or claim remote delivery. If refs differ, stop (D01).

Check `git status --porcelain=v1 --untracked-files=all` and tracked cleanliness. Preserve the known disjoint untracked `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` if present; do not stage, delete, stash or overwrite it. Untracked/ignored inputs that shadow `crates`, `benchmarks/pr15d`, `benchmarks/quervant_bench`, `benchmarks/pyproject.toml`, `.cargo`, toolchain or build settings are stops. Ordinary ignored build scratch is allowed; no cleanup of unrelated work. Verify §1.3 anchor blobs with `git rev-parse "$B:$path"` and historical result paths. Verify the actual A..B non-doc delta locally (the GitHub compare API may truncate long artifact path lists):

```bash
git diff --name-status "$A" "$B" -- . ':(exclude)docs/**' > "$W/a-to-b-source.txt"
git diff --name-status "$A" "$B" -- benchmarks Cargo.toml Cargo.lock .cargo rust-toolchain.toml .github > "$W/a-to-b-tooling.txt"
```

Expected A..B non-doc delta is confined to:

```
crates/quervant-core/src/search/execute.rs
crates/quervant-core/src/search/score.rs
crates/quervant-core/src/search/unified.rs
crates/quervant-core/src/segment/reader.rs
crates/quervant-core/src/segment/stored_blocks.rs
crates/quervant-core/tests/perf06_c2_physical.rs
```

The last three listed include C2-A2 test-only repair and C3 tests; not a new persisted format. Require the tooling diff empty. Any additional path or unexpected normative change is D01/D05. The agent need not inspect every test body again. Verify `git diff --name-only e4816c51f0063383596e8ee8a644b38d7a39a400 "$B" --` is docs-only. Check `git rev-parse "$B^{tree}"` exact pin.

Branch admission: if `dev/perf06-c4` does not exist locally/remotely and no existing PR/acquisition/result/configuration for NAME, create `git switch -c "$BRANCH" "$B"` from a clean tree; if it exists, only D02 applies. Do not force-create or rebase. Main need not be switched or modified. Check exact HEAD=B and tracked clean. Copy the supplied plan verbatim into `$D/PERF06C4_DETAILED_QUALIFICATION_PLAN.md`, only if absent. This records thresholds before acquisition. It is not necessary to commit a config/plan separately before `run`; the native source check excludes `docs/**` and `benchmarks/studies/**`, and HEAD remains pinned B. Do not edit the plan after timing. Store ordinary provenance and outputs in the report, not elaborate receipts. The scratch log can be discarded after complete publication and handoff, but retain on any failure.

### 3.2 Worksheet (record the seven answers in execution report; mismatch → STOP)

1. What do A and B mean? A is merged B4 A+B, B is merged C3 after C2/F1/F2. No pre-B1 or C2-only baseline. One paired A/B measures integrated C, not individual C2/C3 attribution.
2. Why no historical B-only? Historical B4 candidate is pre-B4 merge and different session; no same-session interval. Native `perf-06` provides precisely the two pinned arms; `perf-05` is not a generic alternative.
3. Why are low-hit lanes necessary? Historical PR 15I-C had low-hit codegen/layout regressions despite favorable common queries. M=0/1≤K+1 uses Legacy and must retain acceptable warm latency. C3 entry growth/compiled code can affect other paths even when deferred branch not selected.
4. Which counts are independent? N, exact corpus key/group formula, M, lexicographically ordered fixed-width doc IDs and min(M,K). Do not derive expected keys from result. Warmups and samples use same oracle.
5. What is measured? Actual search + owned Top-K projected doc IDs; no index construction/open or external oracle/JSON serialization. No throughput, no RSS, no cold-start, no compaction performance claim.
6. Which checks are non-blocking? CPU-readiness `clear`/`busy`/`unavailable`. A/A remains binding; compiler/build/index/oracle/schema/sample errors remain real failures, not host-load advisories.
7. Which policy applies? Four primary lanes (100K medium/common × K10/100), twelve guards, §5. All 12 paired blocks per lane, no pruning. Native COMPLETE versus threshold verdict distinct. Historical comparisons separately labelled, no multiplication of gains. No test/quality reruns, no approval loop, no additional acquisition.

## 4. P1 — Exact configuration and workload

### 4.1 Create exactly one configuration via existing CLI

Use the following **single** `prepare` call (do not hand-generate UUID/time or edit output):

```bash
CONFIG=$(python3 -m quervant_bench prepare \
  --family perf-06 --regime warm \
  --name "$NAME" \
  --description 'PERF-06-C4 paired incremental C2+C3 warm qualification against merged accepted A+B (B4); advisory host readiness, binding A/A control' \
  --baseline-revision "$A" \
  --candidate-revision "$B" \
  --readiness-advisory)
export CONFIG
printf '%s\n' "$CONFIG" > "$W/config-path.txt"
python3 -m quervant_bench validate --config "$CONFIG"
```

Require `VALID`, a single regular JSON under `$STUDY/configurations/`, with name `quervant-perf06c4-paired-warm-<created_utc date>.json`, a newly generated UUID, no existing result with this name/UUID. Do not hardcode Nov 27 into filename if actual UTC date changes. The CLI creates the file exclusively. No editing existing config or repurposing an old config. Validate exact values using Appendix A `config` mode **before** the run; the immutable file and plan fix all policy before timing.

Exact expected configuration (only `configuration_id` and `created_utc` generated by CLI; JSON member ordering immaterial):

```json
{
  "schema": "benchmark-configuration-v1",
  "name": "quervant-perf06c4-paired-warm",
  "description": "PERF-06-C4 paired incremental C2+C3 warm qualification against merged accepted A+B (B4); advisory host readiness, binding A/A control",
  "configuration_id": "<generated UUID>",
  "created_utc": "<generated UTC timestamp>",
  "family": "perf-06",
  "workload": {
    "id": "pr15d-exact-keyword-v1",
    "sizes": [10000, 100000],
    "classes": ["absent", "rare", "medium", "common"],
    "top_k": [10, 100],
    "regimes": ["warm"],
    "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
    "timed_operation": "exact-term-search-plus-topk-projection"
  },
  "arms": {
    "A": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": "8c9f51f311afa5b327f70432e32c0f6f5c205eab"},
    "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": "f169fbba93e10d174cad8ab3bca55cdb7ae6aa03"}
  },
  "baseline": "A",
  "control": {"enabled": true, "baseline": "AA", "equivalent": "AA2"},
  "build": {"release": true, "locked": true, "baseline_ref": null, "prefilter_profile": "P2", "quervant_feature": null},
  "policy": {
    "blocks": 12, "slots_per_arm": 2, "warmups": 5, "samples": 20,
    "bootstrap_resamples": 10000, "seed": 20261122, "min_blocks": 4,
    "min_gain_percent": 0, "max_regression_percent": 0, "max_aa_gain_percent": 15,
    "exclude_blocks": {}, "control_arms": [],
    "readiness": {"intervals": 4, "interval_ms": 250, "max_busy_percent": 25, "max_steal_percent": 2, "mode": "advisory"}
  }
}
```

The placeholders above are explanatory only. They must never be persisted as values. Native `min_blocks=4` does not authorize omitting eight blocks; this plan requires complete 12/12 and no exclusions. Native 0/0 treatment thresholds determine native labels; C4 adoption recommendation uses the separate fixed policy in §5.

### 4.2 Frozen lane matrix and independent oracle

Existing corpus generator `runtime.row_values(i)` for `i=0..N-1` creates `doc_id=f"d{i:08d}"`, key `singleton` for i=0 else `common` at positive even i, else `other`; group `medium` for i divisible by 8 else `different`; stored body/payload follow existing formula. Actual `key`/`group` are indexed Keyword; `doc_id` is indexed, stored and columnar Keyword/Single. No numeric surrogate sort. Ascending fixed-width UTF-8 key order. Every normal request has exact lexical score production and selected projection even though adapter output carries IDs/count only.

| N | Class | Field / term | Exact M | K=10 expected route / hits / gate | K=100 expected route / hits / gate |
| ---: | --- | --- | ---: | --- | --- |
| 10,000 | absent | key / never | 0 | Legacy / 0 / guard | Legacy / 0 / guard |
| 10,000 | rare | key / singleton | 1 | Legacy / 1 / guard | Legacy / 1 / guard |
| 10,000 | medium | group / medium | 1,250 | C eligible / 10 / guard | C eligible / 100 / guard |
| 10,000 | common | key / common | 4,999 | C eligible / 10 / guard | C eligible / 100 / guard |
| 100,000 | absent | key / never | 0 | Legacy / 0 / guard | Legacy / 0 / guard |
| 100,000 | rare | key / singleton | 1 | Legacy / 1 / guard | Legacy / 1 / guard |
| 100,000 | medium | group / medium | 12,500 | C eligible / 10 / primary | C eligible / 100 / primary |
| 100,000 | common | key / common | 49,999 | C eligible / 10 / primary | C eligible / 100 / primary |

Route column is a source-derived expectation for B, not measured per-request telemetry. A uses the accepted B-series path for all lanes. M is actual count of generated matching live docs (one segment typical; never assume a physical segment count that adapter did not report). Oracle IDs: absent `[]`; rare `[d00000000]`; medium `i=0,8,...,8(K-1)`; common `i=2,4,...,2K`; format eight decimal digits after `d`. For K=10 medium last ID `d00000072`, common `d00000020`; K=100 medium `d00000792`, common `d00000200`. The native runner calls `expected_answer` for every query. Do not replace it with comparing A to B, hardcoded measured result or an oracle from the actual engine. Do not edit adapter/corpus/oracle.

### 4.3 Topology, schedule and counts

- One sequential local-only process controller; same available adapter core for both arms, distinct controller core, no simultaneous independent runs. Native `host_context` chooses physical cores; do not require historic CPU indices if host topology differs. Do not override taskset or affinity, frequency governor or kernel settings. Use the same installed toolchain for both.
- `run` automatically compiles independently and stages once, indexes both N values for both arms (four actual indexes), commit/reopen/count/byte validation and all 32 untimed lane/arm queries. Unique new scratch and new configuration ensure fresh preparation; `BUILT` is expected. No separate explicit `stage` invocation or redundant rebuild. Source/format unchanged between A and B for persisted schema; index byte totals are separately reported and any unexpected difference disclosed, not a new size-qualification criterion.
- Warm query sessions: one real adapter process for a corpus/strategy group per slot; same snapshot across its queries, not OS-cache-cold. First index open excluded from query timer. For each lane five untimed warmups, then 20 timed samples. No throughput phase in `perf-06`.
- A/A: `AA`, `AA2` aliases of **A's same executable and indexes**. 12 blocks × 4 slots = 48 slots. Treatment only after control PASS. Treatment A/B: same 12 × 4 = 48 slots. Native schedule is seeded position-balanced cyclic shuffle; don't manually alternate or recreate schedule.
- Per phase: 16 lanes × 48 slots = 768 raw lane/slot records; 3,840 warmup queries + 15,360 timed queries. Both phases: **1,536 raw records, 7,680 warmups, 30,720 timed samples**. Each lane has 12 × 2 × 20 = 480 timed samples per role per phase; 12 paired block values. With 32 preparation-oracle queries, planned query calls total 38,432 on a normal complete fresh run. Index build/reopen operations are not query samples. A/A failure reduces actual counts; record actual, never fill missing values.

## 5. Prospective performance decision policy (fixed before acquisition)

Use the existing B4 acceptance thresholds to avoid post-hoc retuning. This is a plan-author choice, not a prediction of outcome. It makes "low-hit neutrality" operational as **no material regression beyond the predeclared 10% bound**, not literal equality or a guarantee of statistical non-regression. In particular, a small statistically significant regression inside that tolerance must remain visible.

### 5.1 Native estimator (unchanged)

Slot median of its 20 `engine_ns` values; arithmetic mean of an arm's two slot medians within block; paired ratio `R_i = B_i/A_i` for each of 12 blocks; point ratio median of all 12 ratios. Signed gain `g=100*(1-R)`: positive means faster, negative means slower. Native deterministic 10,000-resample percentile 95% interval uses **whole paired blocks**, not individual correlated query samples. No reweighting, no outlier exclusion, no pooled medians, no alternative percent calculation. Report native point and interval unrounded for decisions, use readable rounded display only. Native treatment status `IMPROVED` iff CI lower >0, `REGRESSED` iff CI upper <0, otherwise `INCONCLUSIVE` with valid finite data. A/A requires native PASS on each lane: abs(point)≤15, CI lower≥−15 and upper≤15. A/A is binding; host CPU readings are not.

### 5.2 C4 recommendation policy

| Class | Exact pass predicate | Counts |
| --- | --- | ---: |
| Primary: all `100000/{medium,common}/k{10,100}/warm` | native status `IMPROVED` AND gain ≥ 5.0% AND CI lower > 0.0% | 4 |
| Guard: all other lanes | finite native point/CI, retained blocks=12 AND gain ≥ −10.0% AND CI lower ≥ −10.0% | 12 |
| All eight absent/rare lanes | Same guard rule; report separate low-hit subset tally (8/8 required) | subset of 12 |

Exact boundary: gain=+5.0 and lower>0 passes primary; lower=0 fails. Guard point or lower=−10.0 passes exactly; any below fails. Guard native `INCONCLUSIVE` or `REGRESSED` may pass within tolerance; never relabel native result. No averaging or compensating with another lane. All four primary and all twelve guards must pass; no aggregate geometric mean can override one failing lane. No per-optimization effect or CPU/RSS attribution inferred.

| Actual state | Terminal disposition / authorized recommendation |
| --- | --- |
| Native `COMPLETE`, all oracles/control/schedule/provenance valid, 4/4 and 12/12 pass | `PERF06_C4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED`. Recommend maintainer accept the integrated C-series warm performance and promote after review. |
| Native `COMPLETE`, valid data, any primary/guard misses | `PERF06_C4_QUALIFIED_TARGETS_NOT_MET_REVIEW_REQUIRED`. Report exact misses; recommend **not** promote C on this evidence. No automatic rollback of already merged C, no retuning/retry, no cherry-pick/revert. Further work is a separately approved design. |
| `INCOMPLETE`, native run-level `INCONCLUSIVE`, missing result, failed A/A/oracle/build or invalid shape/metadata | `PERF06_C4_INCOMPLETE_VERIFICATION_BLOCKED`. Report actual failure, no accepted performance conclusion. |
| Source/plan contradiction before execution or outside decision matrix | `PERF06_C4_STOPPED_PLAN_AMENDMENT_REQUIRED`. No timed invocation. Preserve any config and diagnostics if created. |
| Essential external dependency blocks before execution/delivery | `PERF06_C4_BLOCKED_EXTERNAL_DEPENDENCY`. State exact blocker; if acquisition valid locally and only push blocked, retain measured verdict separately and report delivery blocked. No new run. |

Neither a successful execution nor a favorable verdict constitutes maintainer acceptance. `main` already contains correctness-qualified C. Do not treat this as an automatic performance baseline promotion; report pending maintainer selection. C4 concludes PERF-06's planned engineering series, but do not mark milestone DONE or start another PR on the agent's authority.

## 6. P2 — Execute the existing native runner exactly once

Prerequisites: §3 pins and worksheet, generated config validate + Appendix A `config` mode, no existing result for NAME, actual source still B. No approval/receipt gate. The host is assumed ready; do not run `assess_readiness` manually. The runner collects all four informative readiness entries at its normal points. Native `host_context` structural failure is an operational stop; no host-load refusal if CPU observation says busy/unavailable. There are no further user interactions during acquisition. No profiling, no monitoring/sampling loop, no background competing jobs, no another shell running tests.

Use one foreground command with the already selected config and isolated scratch. Execute from root; log stdout/stderr to a task-owned file. The native CLI `run` builds/stages/indexes automatically, does A/A, treatment, analysis and local result save. **Do not run `stage` first.**

```bash
# Appendix A is extracted verbatim into "$W/verify_c4.py" before this command.
python3 "$W/verify_c4.py" config "$CONFIG" > "$W/config-check.json"
# No native run for this name has been started previously; no rerun or resume.
# Do not set a shell trap that repeats the run. Preserve its real exit code.
set +e
python3 -m quervant_bench run \
  --config "$CONFIG" \
  --scratch-root "$W/scratch" > "$W/run.log" 2>&1
RUN_RC=$?
set -e
printf '%s\n' "$RUN_RC" > "$W/run-exit.txt"
cat "$W/run.log"
```

The exit file is a simple operational log, not a new authorization marker or evidence protocol. A native `INCOMPLETE` result generally returns 4; a `BM10_ERROR` returns 2; native run-level `INCONCLUSIVE` may return 0, so inspect saved status, not just exit. On any nonzero exit, do not rerun. Preserve actual result if published. `RESULT_JSON=<path>` is printed by existing CLI; use that path only after checking it is a single regular file under `$STUDY/results/` and matches config identity. If runner didn't print it but exactly one file under that name exists, D13 allows reading its native identities. Do not select the latest file by timestamp or guess a path. If no file exists, report no published result; no synthesized JSON. Native sequence must be 001 (new name and UUID), actual UTC date from `executed_utc`. Native result saves before Markdown rendering; a renderer error is not permission to repeat timing.

The native runner can time build/index/reopen separately; never add them to warm `engine_ns`. The actual adapter's `index_open_ns` is emitted on first query but warm `raw_samples` retain `engine_ns` only. Do not infer warm reader open duration from query samples. Report available `index_ns`, `commit_ns`, `reopen_ns`, `index_bytes`, `segment_count` for each arm and size as descriptive. No extra indexing campaign, disk scan/RSS measurement, cold-start measurement, `cargo bench`, Criterion, `perf`, profiler, RustFS or cross-engine operation.

## 7. P3 — Read-only result validation and fixed report generation

Only after the one native run has ended, resolve `RESULT` from CLI or D13, and keep configuration/result bytes unchanged. Read the actual native result. For COMPLETE, run exactly:

```bash
python3 -m quervant_bench analyze --result "$RESULT" > "$W/native-analysis.json"
python3 "$W/verify_c4.py" result "$CONFIG" "$RESULT" "$W/native-analysis.json" > "$W/c4-verdict.json"
python3 -m quervant_bench report --result "$RESULT" > "$W/native-report.md"
```

These are ordinary read-only result interpretation, not a test suite, authorization gate, or additional measurement. Reanalysis uses existing native estimator and must match stored treatment analysis. Appendix A also reanalyzes control from saved data using native `analyze` with `control_arms=["AA2"]`, not a new statistical implementation. Require exact lane catalog, build/source and config identity, 768 records per phase, no duplicates, exact seeded schedule, positive samples, all warmups/oracles, native control PASS, 12 retained blocks, no exclusions, point/CI finiteness, each readiness status preserved and advisory, all four index metadata entries. No file content attestation ceremony; data completeness and declared method are the validity criteria. If native analysis or helper fails, preserve raw result and report validity blocked (D15); do not fix estimator/config or loosen assertions. If result incomplete, **do not** run the complete-result helper/analyzer against missing observations; inspect the actual status/errors and render native `report` if possible. Report completed control/treatment record counts and sums of `samples_ns` lengths from actual rows, no favorable subset analysis.

The full native Markdown may be referenced or supplied to reviewer but do not create a third persistent benchmark-result type. Only the config/result JSON are canonical. The execution report is a concise decision record and PR summary, derived from `c4-verdict.json` plus result, not a replacement for it. Do not modify raw results, including unsuccessful ones. Readiness statuses `busy`/`unavailable` are recorded in report without changing verdict; if an observation is unexpectedly missing in a native COMPLETE run, report missing advisory observation and disclose (do not turn a host observation into an admission gate). Structural context and A/A still required. Appendix A outputs missing advisory observations explicitly.

## 8. P4 — Historical context and cumulative-series reporting (no further acquisition)

C4 answers **incremental C over accepted A+B**. Report the cumulative PERF-06 history as a separate table of already measured within-run effects; do not imply a direct contemporaneous A0→C effect exists. Preserve old conclusions, even when thresholds were missed. In particular, do not sum gains, multiply ratios, compose confidence intervals, or compare old absolute A/B medians as if contemporaneous. The actual cumulative comparison from pre-A1 PERF-05 through integrated C is **NOT MEASURED by this plan**. A direct paired pre-A1 versus final C experiment would require a separately authorized new study and is out of scope. No historical benchmark reruns.

Use these exact committed result files (immutable reference, not current A's measured samples):

| Study | Path under `benchmarks/studies/perf-06/warm/results/` | Measured A → B | Role |
| --- | --- | --- | --- |
| A6 cumulative | `quervant-perf06a6-cumulative-warm-2026-11-24-001.json` | `2a74017958c8ac61948f931e8745bf8134827025` → `3bb232f868cb556ce9b4273d902164c65416af0f` | Historical A-series effect vs pre-A1 PERF-05 |
| B4 paired | `quervant-perf06b4-paired-warm-2026-11-25-001.json` | `480a77e78c6897e05cb7ceb76b01434974b82ec6` → `d660ca9f487d5c54363d790a240abb7da30af245` | Historical B-series effect; 4/4 primary, 12/12 guard PASS |
| C4 paired | Actual new result path | A (merged B4) → B (merged C3) | Incremental integrated C decision only |

Historical primary effects verified at authoring (display rounded, do not use as C4 data):

| Lane (100K) | A6 cumulative gain / 95% CI | B4 gain / 95% CI |
| --- | --- | --- |
| medium K10 | +3.129% [2.732,3.425] | +35.819% [35.411,36.430] |
| medium K100 | +3.365% [2.421,3.995] | +35.409% [35.041,36.505] |
| common K10 | +6.235% [5.427,6.708] | +25.363% [24.843,26.167] |
| common K100 | +5.428% [4.984,6.143] | +24.873% [24.414,25.243] |

Read the saved `analysis.lanes[lane_id].comparisons.B` for historical values as needed (not `analyze` for old data). A6 cumulative did not meet all four 5% primaries; never re-label it. Report A6/B4 source identities and actual published decisions separately from C4. No need to calculate any across-run change in percentage points because these studies represent different treatments; if historical file unavailable, record historical context unavailable, do not invent a composite or block current comparison solely for the optional history table. Preserve all earlier result files.

## 9. P5 — Bounded documentation, commit and delivery

Before commit, compare the exact changed paths with §2.1. `git diff --name-only "$B" --` and `git status --porcelain=v1 --untracked-files=all` (source scope/ownership, not an additional quality suite). Require source/build paths unchanged and existing notes append-only. No routine lint/coverage/format/test/whitespace QA runs are authorized. Do not rewrite preexisting historical whitespace. The source/config/result association is ordinary provenance; no new integrity gates. Use exact-path `git add -- "$CONFIG" "$RESULT" ...` (omit RESULT if none published, omit nonexisting files); never `git add -A`, do not stage untracked foreign notes. Do not stage scratch logs, binaries, indexes, raw TSV or helper. Confirm staged list matches allowlist. If a local hook is verified to perform only the explicitly waived QA, use a **per-command** `git -c core.hooksPath=/dev/null commit ...` for this task only; do not persist configuration or change hook scripts. If hooks include mandatory security/other unwaived checks, do not bypass them; follow D25 if a hook cannot be reconciled with this waiver. No security/remote policy bypass.

Required updates:

1. New `PERF06C4_EXECUTION_REPORT.md` per §10, no self-referential final-commit value. Explicit current code revision B (C3 merged); local current measurement verdict and open maintainer decision. Report filenames, actual IDs and known source; record PR number/URL in live handoff if not created yet. This report and plan are the only new documents; no terminal ZIP or attachment dependency.
2. Append dated C4 status to the three named docs. Preserve original historical text. Wording: "C2 and C3 merged at [actual B]; C4 executed [actual native status] using A=[A] and B=[B] with advisory readiness, exact result/config links. [actual target verdict or blocked]. Unit/integration/quality checks not rerun by explicit maintainer instruction; native benchmark correctness and control [actual]. Independent acceptance/promotion pending. No automatic rollback or performance claim beyond the measured lanes." If execution never reached timing, explicitly say unstarted/blocked. Don't mark DONE or baseline promoted.
3. Commit bounded changes (`git commit -m "PERF-06-C4: record integrated C-series warm qualification"`; add the per-command `-c core.hooksPath=/dev/null` before `commit` only under the verified QA-only hook rule above). This is a data/doc-only change. If admission stops before branch/config, preserve scratch report and no repository write; if acquisition ran, publish the immutable result even if unfavorable/incomplete (safe to commit bounded evidence with exact status). No dummy result.
4. Verify local HEAD and commit diff from B is allowed. Fetch/check `origin/main` remains B before push. If main advanced, preserve branch and results; no rebase, no source repin, no new acquisition, report D19; do not claim candidate still equals current main. If remote branch absent and correct, `git push -u origin dev/perf06-c4` (no force). If push fails, retain local commit and report precise failure. For successful push verify `git ls-remote --heads origin dev/perf06-c4` equals local HEAD. Create one new draft PR (`gh pr create --repo yduchesne/quervant --base main --head dev/perf06-c4 --draft --title "PERF-06-C4: qualify integrated C-series warm query execution" --body-file "$W/pr-body.md"`). Do not request reviews or mark ready. If a PR for branch already exists due to a successful prior attempt, verify it, do not create another. Use `gh pr view ... --json number,url,state,isDraft,mergedAt,headRefOid,baseRefOid` to report actual identity. No subsequent commit merely to record its own SHA/PR/CI status. No tests or CI waiting.
5. Record the returned actual PR URL, HEAD/remote/base, disposition and user-readable result/report links in final handoff. The native result is persisted in repository immediately by runner regardless of remote credentials; no extra approval required. No auto merge, no revert, no next performance task.

## 10. Required execution report and gates

One report with these sections (not 45 receipts / self-hashing packages):

1. **Identity/scope:** pins A/B, merged C3 provenance, plan path, branch, actual config filename/UUID/creation, actual result filename/run_id/execution/sequence or absent; runner/adapter build, toolchains, host, core IDs and filesystem. Worksheet §3.2 answers and any scope exceptions (none preauthorized other than user overrides).
2. **Waivers:** explicit no unit/integration/quality checks, no hosted CI gate, prior C3 evidence referenced as historical. Host readiness mode and each actual observation (busy/steal/status/reason; absent observation disclosed), no additional probes. A/A status separately binding.
3. **Execution:** native prepare/validate/run/analysis/report command outcomes and actual recorded exit; if run failed note point and complete/partial observation counts; no retry. One invocation, prep cache status, actual index/build/provenance. No imaginary measurements. If no native result, preserve log in scratch and paste concise exact error in report.
4. **16-lane result table** on valid complete data (read from Appendix A): lane, N, class, K, A and B median block `engine_ns` (ns or explicitly labelled ms), B/A, gain %, lower/upper 95% gain CI, native status, A/A point+CI/status, primary/guard classification and PASS/FAIL with reason. Include four-primary and twelve-guard tally, low-hit 8-lane tally; worst guard point/lower interval (actual). `INCOMPLETE` report only completed observation counts and errors; no partially selected verdict. Show `INCONCLUSIVE` native status as-is.
5. **Untimed descriptive metrics:** index/commit/reopen durations, actual index bytes, segment count (each arm/size), B/A size ratio and absolute delta. Clarify no isolated compaction, RSS, throughput, index-opening or cold-start qualification. Phase durations from `phase_durations_ns` separate from measured query latency. No unmeasured performance estimates.
6. **Historical series context:** §8 separate effects and limitation, no cumulative end-to-end claim. Report historical A6 and B4 primary results and identities; no new A0 campaign.
7. **Disposition:** exact §5.2 status, specific failed lanes or blocker, independent review and maintainer decision pending. Applied decision-rule IDs and actual trigger/action. Report no source/test/framework change, no retry, no C4 promotion/merge. If delivery blocked, state local file paths and which Git action failed.

| Gate | Exact required state |
| --- | --- |
| C4-P0 source & scope | Pinned exact A/B, ancestor, adapter/runner and allowed files, worksheet complete. No redesign. |
| C4-P1 config | Native `prepare`/`validate`, exact prospective values; no preexisting C4 acquisition or result. |
| C4-P2 benchmark correctness | Native release builds, index commit/reopen/size checks, all 32 untimed oracles and every scheduled warmup/sample validated. Failures recorded; no suite reruns. |
| C4-P3 measurement validity | Complete native result, A/A 16/16 PASS, seeded all-lane records, no pruning; native reanalysis matches, exactly one run. Advisory readiness never blocks. |
| C4-P4 performance decision | All actual lane-level native statuses and prescribed threshold verdict; pass or miss is a valid result if C4-P3 valid. |
| C4-P5 publication | Actual config/result (if published), dated status report and scope-preserved commit, actual draft PR/remote identity if available. No test/CI gate. |
| Maintainer review | OPEN; executor cannot set accepted/merged/baseline promoted. |
| General Rust/Python QA and real-service regression suites | NOT RUN — USER-AUTHORIZED C4 WAIVER. Existing C2/C3 evidence remains historical. |

Reviewer checklist: verify exact A/B and unchanged engine/framework; new config with advisory mode; one result / exact run ID; native output/control/coverage of 16 lanes, no excluded blocks; numeric gates applied before considering result; no retuned guard, no rerun, no other acquisition; all negative evidence preserved; current and historical comparisons separate; exact raw result linked; old docs unchanged except dated appended notes; truthful skipped QA and limitations; PR unmerged, maintainer decision still open. If any item cannot be verified, report actual limitation, don't manufacture another protocol.

Suggested PR body:

```
PERF-06-C4 — integrated incremental warm qualification
A=<merged B4 full SHA>, B=<merged C3 full SHA>.
Config <path, UUID>; result <actual path, run_id, native status>.
One native perf-06/warm run: A/A <actual>, treatment <actual>.
4 primary <actual passed/4>; 12 guards <actual passed/12>; low-hit <actual/8>.
Disposition <exact value>; failed lanes/limitations <actual>.
Host readiness advisory (actual states); A/A binding. No extra run.
No source/adapter/framework/test changes. General QA not run by maintainer instruction.
Historical A/B-series effects are separate; no direct cumulative A0→C claim.
Plan/report <relative links>. Draft PR; independent acceptance/promotion pending.
```

Final handoff: repository, branch, actual PR URL/state, pinned A/B, local and remote commit IDs, config/result names and IDs, native status, actual observation totals, control tally, all primary/guard pass counts and failed lanes, exact disposition, informative host observations, command failures/waivers, no extra measurements, maintainer next action. No inaccessible /tmp package requirement; all essential data are the committed config/result and report. If push/PR unavailable, identify the actual files and local commit and do not claim remote availability.

## 11. Preauthorized decision and exception-handling matrix

Read observable conditions literally. E = coding executor; M = maintainer/plan author. Every unlisted case is D25. "STOP" always prohibits a second native run. If a failure is isolated, preserve safe independent documentation/evidence work; never force an unknown architecture or classification. A classified measurement miss is not a reason to stop reporting.

| ID | Observable trigger | Category | Prescribed action | Prohibited | Evidence / gate / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | `origin/main` not B at admission, A/B missing/not commit/ancestry wrong, PR merge/source anchor contradiction or unexpected A..B diff | HARD STOP | Record actual SHAs/path and exact discrepancy; no config/run | repin/rebase/cherry-pick/change baseline | Git output; P0; M |
| D02 | C4 branch, config, same-name result or previous run exists before admission | HARD STOP for acquisition | Preserve and inspect only actual existing artifacts; if a complete result exists report its identity to maintainer; no new acquisition | reuse old result as new, delete marker, overwrite, create alternate name, rerun | refs/files/status; P0/P1/P2; M |
| D03 | Clean pinned source; task branch absent; known unrelated untracked note present | AUTO-RESOLVE | Preserve file, record path, create branch exactly at B; stage exact paths only | delete/stash foreign data or add-all | status; P0/P5; E |
| D04 | Untracked/ignored shadow build input, dirty tracked file, external build/profile flag, incompatible toolchain, symlink scratch or unsafe environment | HARD STOP | Record specific non-secret input and affected stage | clean/reset, unset arbitrary user config, upgrade/unlock, bypass source check | diagnostic; P0; M |
| D05 | Existing native CLI supports `perf-06` advisory and fixed configuration/runner | AUTO-RESOLVE | Reuse untouched, Python module via PYTHONPATH and exact command | alter code, unsupported perf05 B-only substitution | inspected source/validate; P0/P1; E |
| D06 | Native Linux/filesystem/cores/taskset/toolchain or native build prerequisites not available | DEFER AND CONTINUE (if before run); otherwise validity stop | Report external blocker, no alternative topology. If inside run preserve native incomplete result and stop timing | check_host=False, mock, change host, install alternate compiler | actual error; P0/P2; M |
| D07 | CPU-load probe clear, busy, unavailable, or thresholds exceeded in advisory mode | AUTO-RESOLVE | Preserve real status/reason/observations; continue normal runner; disclose no stability exclusion | idle wait, rerun, rewrite clear, change thresholds, prune or block solely for load | readiness; P2/P4; E |
| D08 | Generated config exactly matches §4.1; actual timestamp/UUID/path chosen by CLI, validates | AUTO-RESOLVE | Use same immutable generated config; date follows UTC | hand-edit UUID, force date, retune policy or controls | validate, config; P1; E |
| D09 | CLI prepare/validate/helper config mismatch, duplicate name/UUID or invalid config | HARD STOP | Preserve actual generated file and diagnostic, no run | manual JSON correction/rename/overwrite/retry prepare | actual config and error; P1; M |
| D10 | Fresh `run` automatic preparation valid; build/index/oracle success | AUTO-RESOLVE | Runner continues to A/A without interaction | separately stage/rebuild, additional oracle acquisition/quality suite | native result context; P2; E |
| D11 | Release build/lockfile/index/reopen/cache/oracle/strategy marker error, real I/O failure or cache corruption | HARD STOP | Native runner records INCOMPLETE where possible; retain evidence, no treatment/rerun; classify failure as environment/harness or actual observed defect, not assumed pre-existing | modify lock/codec/oracle/limits/cache, retry run, replace arm | actual error/result; P2; M |
| D12 | Any native A/A lane FAIL or A/A invalid/incomplete | HARD STOP for treatment | Native runner stops; preserve controls and INCOMPLETE; classify measurement validity blocked | bypass A/A, change 15% bound, B/B substitute, run treatment separately | result/control; P2/P3; M |
| D13 | Native `run` returns, result path printed or exactly one uniquely matching native file exists (renderer/log output issue) | AUTO-RESOLVE | Read actual saved JSON/identity and exit; determine real native status; no new run | choose newest unrelated file, synthesize missing result, rename | run log/result; P3; E |
| D14 | Native run incomplete, interrupted, timeout, missing result or run-level INCONCLUSIVE | HARD STOP for acquisition | Preserve all native data/logs, actual completed row/sample counts, no accepted effect; report bounded safe status | retry/resume/prune or analyze partial subset as valid | actual state/diagnostic; P3; M |
| D15 | COMPLETE result but native analysis/Appendix A/provenance/slot/metric mismatch | HARD STOP for decision | Preserve original result, report verification blocked; no edit/helper weakening or repeat | fabricate counts, change estimator, re-run acquisition | exact mismatch; P3; M |
| D16 | COMPLETE valid 4/4 primary and 12/12 guard | AUTO-RESOLVE | Report TARGETS_MET, recommend acceptance subject to maintainer | auto-promote/merge | full table; P4; E/M |
| D17 | COMPLETE valid any primary or guard miss, including inconclusive primary or low-hit regression | AUTO-RESOLVE | Report TARGETS_NOT_MET, exact failed lanes and interval; no rollback, recommend not promote on this evidence | retune, choose subset, retry, implement fix or automatic revert | full table; P4; E/M |
| D18 | Historical A6/B4 context missing or different host/source | DEFER AND CONTINUE | Label context unavailable/changed; no cumulative composite; current paired result independent | historical absolute ratio or composed gain/CI | history limitations; P4; E |
| D19 | Main advances after measurement starts | DEFER AND CONTINUE | Keep immutable original pins/result; finish accurate local report, do not rebase or repin; defer PR delivery/current-main acceptance | discard result, rerun against new main, claim latest candidate | refs and local evidence; P5; M |
| D20 | Only allowed docs/config/result created; source unchanged; valid or incomplete result | AUTO-RESOLVE | Commit precise paths and push draft branch, with actual status | rewrite previous evidence, stage foreign files or scratch | Git scope; P5; E |
| D21 | Push/auth/PR creation or GitHub metadata unavailable | DEFER AND CONTINUE | Keep local files/commit, report exact error and delivery state; no additional measurement | fabricate URL/remote SHA, force-push, open duplicate PR | local path/commit/error; P5; M |
| D22 | Automatic ordinary CI starts on draft PR | AUTO-RESOLVE | Do not wait or intervene. State user waiver and actual CI status if known | trigger tests, dispatch/re-run/cancel, edit workflow | PR status; P5; E |
| D23 | Current local/remote/PR IDs match; draft/unmerged | AUTO-RESOLVE | Final handoff, independent review open | ready toggle, approve, merge, promote, start later work | live PR identity; P5; M |
| D24 | User instruction excludes QA and host idle confirmation; no code/test/framework changes | AUTO-RESOLVE | Record not run by user authorization; execute only native benchmark operations and saved-data analysis | substitute quality suite, mark waived checks PASS, make load a gate | report; all; E |
| D25 | Any condition not explicitly covered, including required source/tooling change or ambiguous output | HARD STOP | Preserve facts, classify introduced regression/feature defect/pre-existing only with evidence/flaky only with evidence/environment-harness or unclassified, identify smallest maintainer decision. Continue only safe independent reporting | invent fixture, policy, architecture, retries or result | observed evidence and blocked stage; M |

## 12. Critical rules for the coding agent

1. One new `perf-06/warm` configuration, one native run, no separate stage call, no repeat even on failure. No interactions while benchmark executes. No automatic performance adoption.
2. Pin A=B4 and B=C3 merged. Use the native runner, native independent oracle, native statistical analyzer, actual adapter and actual index. No new code anywhere in engine/framework/adapter/tests. `main` stable by instruction; no QA suites/quality checks. Native ordinary prerequisites and oracles remain.
3. Host observations advisory via existing implemented flag. A/A binding and source/metric validity not waived. Preserve all unfavorable and incomplete evidence. Never interpret a `COMPLETE` miss as a reason to run again.
4. Report all sixteen lanes and exact guard decisions; distinguish query metric, writer diagnostics, historical series and unmeasured cumulative effect. Do not overstate score or PIT correctness from benchmark projection.
5. Use only exact permitted file paths, one draft PR, no merge/promotion. Unforeseen condition → stop, not improvise. No terminal ZIP/receipt bureaucracy or additional approval gates.

## 13. Repository sources / author-verification limits

Read at immutable B: `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/TESTING.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/BENCHMARKING.md`, `docs/BENCHMARK_CONFIGURATION.md`, `docs/BENCHMARK_RESULT.md`, `benchmarks/BM10_README.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`, and `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md`. The C4 architecture, current merge identities, prior B4 config and complete result, A6 cumulative result, B4 detailed plan/report, CLI, config, runner, preparation, statistical and adapter source were inspected in authoring. Recursive Git trees for A and B were compared without API truncation: exactly the six non-document paths in §3 differ; the runner/adapter/tooling paths are identical. The user waiver and advisory-mode precedent are explicitly applied only to this task.

Reference URLs:

- B4 merge: https://github.com/yduchesne/quervant/pull/129
- C2 merge: https://github.com/yduchesne/quervant/pull/131
- C3 merge: https://github.com/yduchesne/quervant/pull/132
- C3/F2 final-head CI: https://github.com/yduchesne/quervant/actions/runs/46066729122
- B4 configuration: `benchmarks/studies/perf-06/warm/configurations/quervant-perf06b4-paired-warm-2026-11-25.json`
- B4 report: `docs/pr-artifacts/perf-06-b/PERF06B4_EXECUTION_REPORT.md`
- Original C3 and F2 reports: `docs/pr-artifacts/perf-06-c/PERF06C3_EXECUTION_REPORT.md`, `docs/pr-artifacts/perf-06-c/PERF06C3F2_EXECUTION_REPORT.md`

No real acquisition, test run or release build was executed by the plan author. Historical outcomes are read from actual saved results/CI, not predictions for C4. No new optimization or performance target was inferred from a future result. The authoring decisions are the paired comparison, reuse of B4's 5% primary / 10% guard policy, one automatic native preparation+run, and no direct cumulative A0→C campaign; all fixed before the executor observes timing.

## Appendix A — Exact ephemeral saved-result reader and decision evaluator

Save the following Python code verbatim as `$W/verify_c4.py` (not a committed script). Python standard library plus imports from the **existing** checked-out BM-10 analyzer/config loader; no new package, estimator or runner. The `config` command confirms the requested prospective experiment, `result` consumes only a saved COMPLETE result and the native treatment analysis. It never times a query, starts a process, mutates a result, changes status, runs a test suite or performs authorization. Any error invokes D09 or D15; do not repair the helper on the fly. stdout contains ordinary JSON derived verdict for report. `python3` normal mode, never `-O`.

```python
#!/usr/bin/env python3
import json
import math
import sys
from collections import Counter
from pathlib import Path
from uuid import UUID
from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean.configuration import validate_configuration, lanes_for
from quervant_bench.lean.statistics import analyze, schedule

A = "8c9f51f311afa5b327f70432e32c0f6f5c205eab"
B = "f169fbba93e10d174cad8ab3bca55cdb7ae6aa03"
NAME = "quervant-perf06c4-paired-warm"
DESC = ("PERF-06-C4 paired incremental C2+C3 warm qualification against "
        "merged accepted A+B (B4); advisory host readiness, binding A/A control")
CLASSES = {"absent": ("key", "never"), "rare": ("key", "singleton"),
           "medium": ("group", "medium"), "common": ("key", "common")}
NS = (10000, 100000)
KS = (10, 100)
POLICY = {
    "blocks": 12, "slots_per_arm": 2, "warmups": 5, "samples": 20,
    "bootstrap_resamples": 10000, "seed": 20261122, "min_blocks": 4,
    "min_gain_percent": 0, "max_regression_percent": 0,
    "max_aa_gain_percent": 15, "exclude_blocks": {}, "control_arms": [],
    "readiness": {"intervals": 4, "interval_ms": 250,
                  "max_busy_percent": 25, "max_steal_percent": 2,
                  "mode": "advisory"},
}
WORKLOAD = {
    "id": "pr15d-exact-keyword-v1", "sizes": list(NS),
    "classes": list(CLASSES), "top_k": list(KS), "regimes": ["warm"],
    "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
    "timed_operation": "exact-term-search-plus-topk-projection",
}
ARMS = {role: {"engine": "quervant", "mode": "by-top-k", "source": "pinned",
               "revision": rev} for role, rev in (("A", A), ("B", B))}
BUILD = {"release": True, "locked": True, "baseline_ref": None,
         "prefilter_profile": "P2", "quervant_feature": None}


def require(ok, label):
    if not ok:
        raise ValueError(label)


def positive(value):
    return type(value) is int and value > 0


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def lane_id(n, cls, k):
    return f"{n}/{cls}/k{k}/warm"


def config_check(path):
    c = load_configuration(path)
    validate_configuration(c)
    expected = {"schema": "benchmark-configuration-v1", "name": NAME,
                "description": DESC, "family": "perf-06", "workload": WORKLOAD,
                "arms": ARMS, "baseline": "A", "build": BUILD, "policy": POLICY,
                "control": {"enabled": True, "baseline": "AA", "equivalent": "AA2"}}
    require(set(c) == set(expected) | {"configuration_id", "created_utc"}, "config keys")
    require({k: c[k] for k in expected} == expected, "frozen config mismatch")
    require(str(UUID(c["configuration_id"])) == c["configuration_id"], "invalid config UUID")
    require(c["created_utc"].endswith("Z"), "creation time not UTC")
    require(path.name == f"{NAME}-{c['created_utc'][:10]}.json", "config date/name")
    require(path.parent.name == "configurations" and path.parent.parent.name == "warm"
            and path.parent.parent.parent.name == "perf-06"
            and path.parent.parent.parent.parent.name == "studies", "config path")
    return c


def expected_lanes():
    out = []
    for n in NS:
        for cls, (field, term) in CLASSES.items():
            for k in KS:
                out.append({"id": lane_id(n, cls, k), "workload_id": WORKLOAD["id"],
                            "n": n, "class": cls, "field": field, "term": term,
                            "k": k, "cache_regime": "warm",
                            "query_semantics": WORKLOAD["query_semantics"],
                            "timed_operation": WORKLOAD["timed_operation"],
                            "metric": "search_latency", "unit": "ns",
                            "direction": "lower", "comparability": "COMPARABLE"})
    return out


def check_records(rows, roles, lanes):
    require(isinstance(rows, list) and len(rows) == 768, "expected 768 slot/lane records")
    slots = schedule(roles, blocks=12, slots_per_arm=2, seed=20261122)
    expected = {(s["block"], s["position"], s["arm_id"], lane)
                for s in slots for lane in lanes}
    actual = Counter()
    timed = warmups = 0
    for row in rows:
        require(type(row["block"]) is int and type(row["position"]) is int, "slot coordinate")
        require(row["oracle_ok"] is True, "unverified oracle")
        require(row["strategy_marker"] is None, "strategy override marker")
        require(type(row["warmups"]) is int and row["warmups"] == 5, "warmup count")
        values = row["samples_ns"]
        require(isinstance(values, list) and len(values) == 20
                and all(positive(v) for v in values), "timed samples")
        actual[(row["block"], row["position"], row["arm_id"], row["lane_id"])] += 1
        timed += len(values)
        warmups += row["warmups"]
    require(set(actual) == expected and all(v == 1 for v in actual.values()), "seeded slot/lane inventory")
    require((timed, warmups) == (15360, 3840), "phase sample totals")
    return {"records": len(rows), "timed_samples": timed, "warmup_queries": warmups}


def comparison(stat, lane, role, baseline, allowed):
    require(stat["metric"] == "search_latency" and stat["direction"] == "lower"
            and stat["unit"] == "ns", f"{lane} metric")
    require(stat["raw_blocks"] == stat["retained_blocks"] == 12
            and stat["excluded_blocks"] == [], f"{lane} block inventory")
    t = stat["comparisons"][role]
    require(t["status"] in allowed and t["baseline_arm"] == baseline
            and t["treatment_arm"] == role, f"{lane} comparison identity/status")
    require(t["bootstrap_resamples"] == 10000, f"{lane} bootstrap")
    p, ci, ratio, rci = (t["gain_percent"], t["gain_ci_95_percent"],
                         t["ratio_b_over_a"], t["ratio_ci_95"])
    require(finite(p) and isinstance(ci, list) and len(ci) == 2
            and all(finite(v) for v in ci) and ci[0] <= ci[1], f"{lane} gain/CI")
    require(finite(ratio) and ratio > 0 and isinstance(rci, list) and len(rci) == 2
            and all(finite(v) and v > 0 for v in rci) and rci[0] <= rci[1], f"{lane} ratio/CI")
    require(len(t["retained_paired_ratios"]) == 12
            and all(finite(v) and v > 0 for v in t["retained_paired_ratios"]), f"{lane} paired ratios")
    for arm in (baseline, role):
        a = stat["arm_absolute"][arm]
        require(finite(a["median_block_value"]) and a["median_block_value"] > 0
                and len(a["block_values"]) == 12
                and all(finite(v) and v > 0 for v in a["block_values"]), f"{lane} absolute metrics")
    return t


def result_check(config_path, result_path, analysis_path):
    c = config_check(config_path)
    r = load_result(result_path)
    require(r["schema"] == "benchmark-result-v1" and r["family"] == "perf-06", "result schema/family")
    require(r["status"] == "COMPLETE" and r["errors"] == [], "not a complete valid result")
    require(r["configuration"] == c and r["configuration_id"] == c["configuration_id"]
            and r["configuration_file"] == config_path.name and r["configuration_name"] == NAME,
            "result config linkage")
    require(r["run_id"] != c["configuration_id"] and r["sequence"] == 1, "new run identity/sequence")
    require(result_path.resolve().parent == config_path.resolve().parent.parent / "results"
            and result_path.name == f"{NAME}-{r['executed_utc'][:10]}-001.json", "result path/date")
    lanes = expected_lanes()
    require(lanes_for(c) == lanes and r["lanes"] == lanes, "exact lane catalog")
    ids = [x["id"] for x in lanes]
    ctx = r["context"]
    require(ctx["host_readiness_mode"] == "advisory", "wrong readiness mode")
    require(ctx["source_revision"] == B, "runner checkout revision")
    build = ctx["build"]
    require(build["arm_source_revisions"] == {"A": A, "B": B}
            and build["compiler_options"] == "cargo --release --locked"
            and build["quervant_strategy_feature_enabled"] is False
            and build["source_revision"] == B, "build provenance")
    prep = ctx["preparation"]
    require(prep["verified_oracles"] is True and prep["cache_status"] == "BUILT", "fresh preparation/oracles")
    host = ctx["host"]
    require(host["system"] == "Linux" and host["filesystem"] in ("ext4", "xfs", "btrfs"), "host capabilities")
    require(ctx["controller_cpu"] != ctx["adapter_cpu"] and ctx["controller_cpu"] is not None
            and ctx["adapter_cpu"] is not None, "distinct CPU roles")
    require(host["toolchains"]["rustc"].startswith("rustc 1.98.1 ")
            and host["toolchains"]["cargo"].startswith("cargo 1.98.1 "), "pinned Rust tools")
    ctr = r["controls"]
    control_counts = check_records(ctr["raw_samples"], ["AA", "AA2"], ids)
    treatment_counts = check_records(r["raw_samples"], ["A", "B"], ids)
    native = json.loads(analysis_path.read_text(encoding="utf-8"))
    require(native == r["analysis"], "native treatment reanalysis mismatch")
    ca = analyze(ctr["raw_samples"], arms=["AA", "AA2"], baseline="AA", lanes=lanes,
                 policy=dict(c["policy"], control_arms=["AA2"]))
    require(ca == ctr["analysis"], "native control reanalysis mismatch")
    require(set(native["lanes"]) == set(ca["lanes"]) == set(ids), "analysis lane set")
    require(set(r["index_metrics"]) == {"A", "B"}, "index arms")
    index_rows = []
    for n in NS:
        out = {"n": n}
        for arm in ("A", "B"):
            require(set(r["index_metrics"][arm]) == {str(s) for s in NS}, "index corpus set")
            m = r["index_metrics"][arm][str(n)]
            require(all(positive(m[key]) for key in ("index_ns", "commit_ns", "reopen_ns",
                                                     "index_bytes", "segment_count")), "index metric")
            out[arm] = m
        out["byte_delta_B_minus_A"] = out["B"]["index_bytes"] - out["A"]["index_bytes"]
        out["size_ratio_B_over_A"] = out["B"]["index_bytes"] / out["A"]["index_bytes"]
        index_rows.append(out)
    require("throughput_metrics" not in r, "unexpected throughput phase")
    rows = []
    for lane in lanes:
        lid = lane["id"]
        aa = comparison(ca["lanes"][lid], lid, "AA2", "AA", {"PASS"})
        require(abs(aa["gain_percent"]) <= 15 and aa["gain_ci_95_percent"][0] >= -15
                and aa["gain_ci_95_percent"][1] <= 15, f"{lid} A/A bound")
        stat = native["lanes"][lid]
        t = comparison(stat, lid, "B", "A", {"IMPROVED", "REGRESSED", "INCONCLUSIVE"})
        p, low, high = t["gain_percent"], *t["gain_ci_95_percent"]
        primary = lane["n"] == 100000 and lane["class"] in ("medium", "common")
        failures = []
        if primary:
            if t["status"] != "IMPROVED": failures.append("native status not IMPROVED")
            if p < 5: failures.append("gain below +5%")
            if low <= 0: failures.append("CI lower not above zero")
        else:
            if p < -10: failures.append("gain below -10%")
            if low < -10: failures.append("CI lower below -10%")
        rows.append({"lane": lid, "n": lane["n"], "class": lane["class"], "k": lane["k"],
                     "policy": "primary" if primary else "guard", "pass": not failures,
                     "failure_reasons": failures,
                     "a_median_block_ns": stat["arm_absolute"]["A"]["median_block_value"],
                     "b_median_block_ns": stat["arm_absolute"]["B"]["median_block_value"],
                     "ratio_b_over_a": t["ratio_b_over_a"], "gain_percent": p,
                     "gain_ci_95_percent": [low, high], "native_status": t["status"],
                     "aa_gain_percent": aa["gain_percent"],
                     "aa_gain_ci_95_percent": aa["gain_ci_95_percent"], "aa_status": aa["status"]})
    primary = [x for x in rows if x["policy"] == "primary"]
    guard = [x for x in rows if x["policy"] == "guard"]
    low_hit = [x for x in guard if x["class"] in ("absent", "rare")]
    require((len(primary), len(guard), len(low_hit)) == (4, 12, 8), "policy lane inventory")
    passed = all(x["pass"] for x in rows)
    readiness = {k: ctr.get(k, {"status": "not_recorded", "advisory_only": True})
                 for k in ("readiness_index_pre", "readiness_pre", "readiness_treatment", "readiness_post")}
    # Deliberately do not require readiness.status==clear, or use busy/steal
    # values as a selection criterion. Missing advisory observations are
    # disclosed by the report, never used to invalidate an otherwise valid run.
    return {"disposition": ("PERF06_C4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED" if passed
                            else "PERF06_C4_QUALIFIED_TARGETS_NOT_MET_REVIEW_REQUIRED"),
            "native_result_status": r["status"], "configuration_id": c["configuration_id"],
            "run_id": r["run_id"], "configuration_file": config_path.name,
            "result_file": result_path.name, "executed_utc": r["executed_utc"],
            "a": A, "b": B, "aa_passed": 16,
            "primary_passed": sum(x["pass"] for x in primary),
            "guard_passed": sum(x["pass"] for x in guard),
            "low_hit_passed": sum(x["pass"] for x in low_hit),
            "all_targets_met": passed,
            "worst_guard_gain": min(x["gain_percent"] for x in guard),
            "worst_guard_ci_lower": min(x["gain_ci_95_percent"][0] for x in guard),
            "control_counts": control_counts, "treatment_counts": treatment_counts,
            "readiness_advisory_only": readiness, "index_metrics_descriptive": index_rows,
            "phase_durations_ns": r["phase_durations_ns"], "lanes": rows}


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "config":
        c = config_check(Path(args[1]))
        result = {"status": "VALID", "configuration_id": c["configuration_id"],
                  "a": A, "b": B, "readiness": "advisory", "lane_count": 16,
                  "primaries": 4, "guards": 12}
    elif len(args) == 4 and args[0] == "result":
        result = result_check(*(Path(x) for x in args[1:]))
    else:
        raise SystemExit("usage: verify_c4.py config CONFIG | result CONFIG RESULT ANALYSIS")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
```

**End of plan.** Execute as written. No new optimization; no QA suites; host-load advisory; one paired warm study; no subsequent measurement or merge without new maintainer authorization.
