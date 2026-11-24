# PERF-06-A6 — Consolidated compatibility, storage and warm-performance qualification

**Document type:** frozen, source-specific execution contract for a low-reasoning coding agent.  
**Planning date:** 2026-11-24 (Pacific date; benchmark artifact dates remain UTC).  
**Repository:** https://github.com/yduchesne/quervant  
**Planning main / accepted A5 merge:** 3bb232f868cb556ce9b4273d902164c65416af0f.  
**Proposed branch:** dev/perf06-a6-qualification.  
**Proposed PR title:** PERF-06-A6: qualify adaptive postings and the consolidated A series.  
**Status of this document:** PLAN ONLY. No A6 acquisition or compatibility execution is claimed.

## 0. Execution authority, user override and fixed boundaries

### 0.1 Explicit user instructions control this plan

The user states that A5 is merged, deliberately declined the preceding report-only corrections to avoid lengthy CI, directs the agent to assume stable main, and says that unit/integration test suites and quality checks such as Clippy need not run. The user also directs the agent to assume that the host is idle and ready for performance benchmarking.

Those instructions supersede the ordinary QA requirements in AGENTS.md and docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md for this task. The exception comes from the user, not from an agent-created waiver.

| Activity | Required disposition in A6 |
| --- | --- |
| Baseline and regression unit/integration suites, including existing RustFS suites | NOT RUN — USER-AUTHORIZED STABLE-MAIN EXCEPTION |
| Stable/MSRV formatting, Clippy, coverage, cargo doc, bench --no-run, benchmark-framework/script test suites | Same exception; do not invoke them |
| Re-establishing A5/F1 test totals, old report corrections or independent-review bookkeeping | Not an A6 prerequisite; preserve the merged historical documents |
| Requiring green CI before preparing, measuring or delivering A6 | Not an A6 gate under the user exception |
| Ordinary release compilation needed to execute the frozen adapters and qualification driver | Required operational preparation; no test runner |
| Source/pin/configuration checks, actual benchmark oracles, A6-specific compatibility operations, result reanalysis and measured-byte checks | Required A6 acceptance work |
| Automatically triggered CI on a final PR | Leave the workflow unchanged; no manual dispatch, retry, cancellation, waiting loop or success claim without evidence |

Do not run cargo test, cargo clippy, cargo fmt, cargo llvm-cov, cargo doc, cargo bench, Rust/MSRV test matrices, Python test suites, shell test suites, or a substitute general QA battery. Do not classify the absence of waived checks as BLOCKED. Record the exception explicitly.

The bounded compatibility executable in this plan is a new A6 qualification workload through real public writer/reader APIs. It does not invoke or rerun an existing integration suite. Benchmark correctness oracles likewise remain part of measurement admission.

### 0.2 Continuous execution authorization

Once this plan is authorized, execute every prescribed unblocked stage through final evidence delivery without routine reconfirmation. A successful source check, compilation, compatibility phase, configuration validation or AUTO-RESOLVE decision means continue.

Stop affected work only for an applicable HARD STOP, a missing essential dependency, or an unforeseen condition that needs a plan amendment. Complete independent safe work when the decision matrix explicitly permits it. The agent must not invent architecture, alter measurement contracts or weaken assertions to continue.

This plan authorizes, in a later execution turn:

- Exactly two distinct paired warm run invocations, each at most once.
- Two pinned compatibility executable builds, one at E and one at F.
- Three native and three real-RustFS compatibility process invocations.
- Four separate build-process resource observations, using already-built benchmark adapters.
- Read-only artifact verification and the narrowly listed documentation/evidence changes.
- One ordinary branch delivery and draft PR, when repository publication is part of the execution instruction.

It does not authorize executing this plan merely because the plan file was generated. It never authorizes a merge, release, B1 implementation, engine/framework correction, additional acquisition, target relaxation, or retroactive rewriting of A4/A5 evidence.

### 0.3 Host assumption

Start from the user's assumption that the host is idle and ready. Do not ask for an idle-host confirmation, run a separate host qualification campaign, change governors, pin CPUs by guess, drop OS caches, or repeatedly wait for a quieter host.

Keep the existing harness's native fail-closed readiness observations and CPU selection. The CLI already performs them as part of its run. A reported readiness failure is evidence; preserve it and apply the stop matrix. Never pass check_host=False or fabricate a clear observation.

### 0.4 Frozen study decisions

| Decision | Fixed selection |
| --- | --- |
| Production implementation | Accepted A5 unchanged |
| Warm method | Two separate prospective, contemporaneous paired A/B studies |
| Campaign R | A3/E versus A5/F: isolate A5's incremental effect |
| Campaign C | Pre-A1/A0 versus A5/F: measure the complete A1–A3+A5 result |
| Acquisitions | One run invocation per campaign; no rerun authority |
| Corpus/lane matrix | Existing perf-06 exact-keyword 10K/100K, four classes, K10/K100; 16 warm lanes |
| Controls/statistics | Existing A/A aliases, schedule, estimator and bootstrap unchanged |
| Real sizes | Fresh one-commit whole-index logical file bytes at A0, E and F |
| Resource observations | E/F × 10K/100K, one process per cell; descriptive CPU/RSS and build timers |
| Native compatibility | Genuine E creation → F append → E+F → native F compaction → new-process reopen |
| Remote compatibility | Genuine remote E creation → F append → E+F cold/new-process reopen and held PITs |
| Remote compaction publication | Explicitly NOT QUALIFIED; bounded maintainer-owned residual, no workaround |
| Overall promotion | Maintainer decision after evidence; B1 never starts automatically |

The two campaigns answer different questions. Do not derive a cumulative effect by multiplying gains from different runs or infer A5's effect from a historical A4 median. The current two-arm framework needs two declared campaigns to estimate both effects. Its cache key includes the complete configuration and arm pair, so it may compile/build F once per campaign; do not redesign caching to deduplicate that work.

## 1. Purpose and reconciliation with merged main

A1 prepared query-constant BM25 work. A2 added consuming document/frequency-only traversal. A3 separated posting streams but increased short-list framing. A4 measured the cumulative A1–A3 candidate and preserved a targets-not-met outcome. A5 introduced compact framing for lists of 1–128 documents while retaining the A3 representation for longer lists. A5/F1 is now merged through PR #124.

A6's dominant concern is to obtain a reviewable qualification of that accepted implementation: genuine format coexistence, actual footprint, bounded writer-resource evidence, incremental warm cost and cumulative warm benefit.

| Capability/evidence | State at planning | A6 treatment |
| --- | --- | --- |
| A1–A3 implementation | Merged and retained | No changes |
| A4 second campaign | COMPLETE; 16/16 A/A and 12/12 guards; 2/4 primary targets met | Immutable historical evidence |
| A5 adaptive codec and its F1 assertions | Merged by maintainer | Stable-main assumption; no suite reruns |
| Historical F1 report discrepancies | Not corrected before merge by user choice | Preserve; do not make them A6 prerequisites |
| Full-corpus A5 sizes | Model projections, not measured | Measure directly |
| A5 writer CPU/peak RSS | Not measured | Four bounded fresh-build observations |
| Genuine complete E+F lifecycle | Missing combination under A5 D39 | Execute the fixed native and remote qualification |
| Current cumulative A0→F warm outcome | Not measured | Campaign C |
| Current isolated E→F warm outcome | Not measured | Campaign R |
| B1 | Dependent on A6 and maintainer disposition | Remains blocked from automatic execution |

Do not re-label A4's unfavorable result after observing A6. A6 creates new evidence with new names and UUIDs.

## 2. Pinned identities and source contract

### 2.1 Immutable revisions

| Symbol | Role | Full Git revision |
| --- | --- | --- |
| A0 | Accepted pre-A1 PERF-05 source | 2a74017958c8ac61948f931e8745bf8134827025 |
| E | Cumulative A1–A3 source; genuine A3/E writer | b70f624fffe0329def62701b61e997c4e303e167 |
| F | Merged A5/F1 source; adaptive F writer/reader | 3bb232f868cb556ce9b4273d902164c65416af0f |
| Reviewed A5 PR head | Historical F1 final head included in F | be5e4b21843cc77e22845588ec9185b5b8b4db31 |
| Expected immediate pre-A5 main | Historical merge parent | 5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d |

A0 must be an ancestor of E and E an ancestor of F. Every arm revision must resolve to a commit object. If an exact object is missing locally, one fetch of the three frozen SHAs is authorized; then repeat only the object/ancestry reads:

~~~bash
git fetch origin 2a74017958c8ac61948f931e8745bf8134827025 b70f624fffe0329def62701b61e997c4e303e167 3bb232f868cb556ce9b4273d902164c65416af0f
~~~

A fetch/ancestry failure blocks measurement; never substitute a branch tip. Use these pinned arm revisions even if a later documentation-only main commit is used for the A6 branch.

### 2.2 Verified source objects

| Path | Git object at planning main |
| --- | --- |
| docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md | c871d370dc050fad9457bfa81a8421dbb846fbf2 |
| AGENTS.md | 08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c |
| docs/BENCHMARKING.md | 9cdb1c816482d4de42a800419a39c62f1ab6dde9 |
| docs/PERF_OPTIMIZATION_ROADMAP.md | db2a4271692905f03142c638566bd276ec16dc75 |
| benchmarks/quervant_bench/lean/runtime.py | 0081b0d4600bc33f974960a0a9a700c7342dd50e |
| benchmarks/quervant_bench/lean/preparation.py | ef8e5c8b21db7a5c38c58f5105584a1dacdbe8bc |
| benchmarks/quervant_bench/lean/configuration.py | 6103a0cb1ac7cd8d8029d3d92c63761dce429c61 |
| benchmarks/quervant_bench/lean/statistics.py | 7854fb8035128e425d00e6f4ad192f20d7a6c718 |
| benchmarks/pr15d/adapters/quervant/src/main.rs | 9e333e7d9be23d08802ae850b39bd3ffd2dfbf48 |
| crates/quervant-core/src/segment/postings.rs | 4a3abeeb921cb5ca8ecbbd93a2b71c49c4f3f538 |
| crates/quervant-core/src/segment/format.rs | 55ca2885def34d6563ab91b9fd81c761f19a3203 |
| crates/quervant-core/src/segment/build.rs | 7cf05a09e9453a254febcb7ea10bd957e175b587 |
| crates/quervant-core/src/segment/reader.rs | 951f08086a8a0225b7fb31195c4db359bd7fda82 |
| crates/quervant-core/src/index/merge.rs | 14754c16254064902fe17753f809565b0c01ec9b |
| crates/quervant-core/src/remote/mod.rs | 4ff26d85d5b7fe5651a5cca44d0606332466d6de |
| Cargo.toml | 40bd37bd5314009eeb7b81f201f5ae0180be26f7 |
| Cargo.lock | a230eb28d692c543fd541e7a9eaa0980e678e40e |
| rust-toolchain.toml | 73cb934de4706a914c15e8db2a3c037ce75699d9 |
| .github/workflows/ci.yml | df63adc43f9f27e1e84e539d00bb2d78361c5c03 |

Use Git's existing hash/object functions and Python hashlib/RustCrypto sha2; never implement a digest primitive.

### 2.3 Fresh-main and branch rule

Fetch origin/main once and inspect it before creating the A6 branch. The normal path is a clean worktree at F. If origin/main is ahead, continue only if all these conditions hold:

1. F remains an ancestor.
2. The diff from F changes documentation and/or existing tests only.
3. Every executable measurement input remains identical, including whole source trees covered by the preparation source closure. A test change under crates changes that tree and therefore is NOT automatically allowed for controller execution despite stable-main assumptions.
4. No changed policy alters an A6 contract.
5. The arm pins remain A0/E/F.

A simple sufficient AUTO-RESOLVE case is a docs-only descendant with no policy conflict. Any production, adapter, harness, manifest, lockfile, toolchain, workflow or relevant policy drift stops affected measurement pending an amended plan. Do not silently choose a newer F.

For a clean main checkout, the exact branch sequence is:

~~~bash
git fetch origin main
git switch main
git pull --ff-only origin main
git switch -c dev/perf06-a6-qualification
~~~

Before switching, require clean tracked/staged state and no untracked collision with the allowlist. If the A6 branch already exists, use the resume rules in §15; do not reset, rebase, force-push, delete user work or create another similarly named branch. A foreign checkout with unrelated edits is a stop for checkout mutation; do not stash it automatically.

Record START_SHA, F, actual RUNNER_SHA (= the committed controller HEAD before acquisition), current origin/main, guide/plan identities and tool versions.

### 2.4 Toolchain and environment

Use already-installed Rust 1.98.1 for all arm builds and both qualification drivers:

~~~bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
RUNNER_SHA="$(git rev-parse HEAD)"
export RUSTUP_TOOLCHAIN=1.98.1
export PYTHONPATH="$REPO_ROOT/benchmarks"
export LC_ALL=C
~~~

Do not overwrite RUNNER_SHA on resume after a prior acquisition; recover its recorded value from the started marker/report and require the current controller source contract still matches. Record rustc --version, cargo --version and Python version; Python must meet the existing >=3.11 requirement. Do not update stable, run rustup update, change Cargo.lock, install optional QA tools or select another compiler. Missing operational tools block only the work that needs them.

Do not set experiment overrides or enable pr15i-d3c-experiment. If QUERVANT_PR15I_D3C_STRATEGY or QUERVANT_PR15I_D3C_PREFILTER_PROFILE is inherited, stop measurement and report the environment conflict; do not silently benchmark it. Do not introduce RUSTFLAGS/profile/LTO changes. Capture existing build-relevant environment via the harness's digest without printing secrets.

Use task-specific variables only. Never repurpose HOME, home or CODEX_HOME.

## 3. Scope, files and ownership

### 3.1 Exact repository write allowlist

Existing files whose current-status sections may be updated:

- docs/PERF_OPTIMIZATION_ROADMAP.md
- docs/BENCHMARKING.md
- docs/pr-artifacts/perf-06-a/PERF06A_SERIES_REGISTER.md
- docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md

New files:

- docs/pr-artifacts/perf-06-a/PERF06A6_DETAILED_PLAN.md — exact approved copy.
- docs/pr-artifacts/perf-06-a/PERF06A6_EXECUTION_REPORT.md.
- docs/pr-artifacts/perf-06-a/a6/support/a6_compatibility.rs.
- docs/pr-artifacts/perf-06-a/a6/support/verify_a6_results.py.
- docs/pr-artifacts/perf-06-a/a6/support/measure_a6_writer.py.
- docs/pr-artifacts/perf-06-a/a6/support/run_a6_once.py.
- docs/pr-artifacts/perf-06-a/a6/invocation-uuid.txt — one retained task identity.
- docs/pr-artifacts/perf-06-a/a6/acquisition/ — exactly one started marker and one run log per authorized campaign, plus a result-reference text file if published; the outer guard transcript records pre-C verification.
- docs/pr-artifacts/perf-06-a/a6/compatibility/ — exactly six stdout JSONL/stderr log pairs and six exit.txt records for the prescribed modes, plus source/binary/inventory evidence.
- docs/pr-artifacts/perf-06-a/a6/writer/ — the bounded diagnostic output inventory specified in §10.
- docs/pr-artifacts/perf-06-a/a6/verification/ — read-only verification output, source/byte ledgers and no copied large indexes.
- benchmarks/studies/perf-06/warm/configurations/quervant-perf06a6-adaptive-warm-<creation-UTC-date>.json.
- benchmarks/studies/perf-06/warm/configurations/quervant-perf06a6-cumulative-warm-<creation-UTC-date>.json.
- Corresponding sibling results/<same-name>-<execution-UTC-date>-001.json files, only when the native publisher creates them.

Angle-bracket values are mechanically returned timestamps, never chosen to conceal an attempt. Sequence 001 is expected because each new configuration receives one run invocation. A different suffix for these new names is a stop for additional acquisition.

Support files are fixed content supplied in this plan, not a new framework. Keep them local to the A6 artifact directory. Do not add them to production packages, test discovery, entry points, CI, library APIs or dependency manifests.

### 3.2 Protected files

Everything outside the allowlist remains unchanged, especially:

- crates/** in the A6 controller branch.
- benchmarks/quervant_bench/** and benchmarks/pr15d/**.
- Cargo files, .cargo/**, rust-toolchain.toml, .github/**.
- Every existing test, fixture and golden file.
- All A1–A5 and F1 plans/reports and both A4 result JSON files.
- Existing benchmark configurations/results, other study families and archived controllers.
- docs/ARCHITECTURE.md, docs/ROADMAP.md, AGENTS.md, docs/TESTING.md and the authoring guide.

The temporary qualification worktrees have one explicit exception: install the identical supplied Rust example at crates/quervant-core/examples/perf06_a6_compatibility.rs. This is an uncommitted, task-owned example in those dedicated worktrees only; it must never be installed in the controller or prepared benchmark cache worktrees.

### 3.3 Ownership and identities

The public Index/IndexWriter or RemoteIndex writer owns generation publication. FsDirectory and the existing production S3ObjectStore own their actual I/O. The qualification program observes; it never manufactures manifests, CURRENT, mutation-state objects, segment bytes or successful provider responses.

Logical keys remain k00000…; projected doc_id field values remain d00000…. Physical segment IDs may change on compaction. Generation1 has 129 logical documents, generation2/3 has130. A held PIT retains its own generation. Index-byte measurements use separate fresh benchmark directories and are never taken from these multi-generation compatibility directories.

## 4. Invariants and acceptance trace

| ID | Falsifiable invariant | Evidence owner/check |
| --- | --- | --- |
| I01 | Engine, adapter and harness production sources remain pinned and unchanged | Source ledger; native preparation identity; final allowlist |
| I02 | Both configurations are new and frozen before timing; each run is invoked at most once | Config bytes/UUIDs; exclusive started markers; result inventory |
| I03 | Every accepted warm sample has correct exact total_hits and ordered document IDs | Native oracle on preparation and every sample; replay verifier |
| I04 | A/A passes on all 16 lanes and all 12 blocks are retained | Native controls + exact control replay |
| I05 | Treatment estimates use only same-campaign paired blocks | Existing statistics.analyze; no pooled historical values |
| I06 | E is a genuine old-writer complete index, never a rewritten fixture | E process at pinned revision; actual required feature and state/generation checks |
| I07 | F reads E, appends F, and native compaction produces one F segment while preserving old PITs | Native create-e/advance-f/verify-f |
| I08 | Remote E and mixed E+F open from empty workspaces using authoritative remote CURRENT | Three real-provider modes; no local-state copying |
| I09 | Old E and F immutable files survive native compaction byte-identically; remote E objects survive append | Generation1+2 inventories and sha2 checks; remote byte comparisons |
| I10 | Whole-index size is the sum of regular-file lengths in a fresh one-commit index | Adapter count, native independent count, cache fingerprints and diagnostic repeat |
| I11 | Resource observations exclude compilation and query windows | Exactly four already-built adapter processes under GNU time |
| I12 | Report distinguishes valid unfavorable results, incomplete runs, model deviations and unmeasured properties | Gate/disposition tables and immutable raw artifacts |
| I13 | No waived QA or CI gate is reintroduced | Command ledger; explicit NOT RUN exception |
| I14 | Unknown conditions cannot authorize repairs or more measurements | §15 decision matrix; preserved failed evidence |

### 4.1 Cross-component impact

| Component/path | A6 action | Prohibited change |
| --- | --- | --- |
| Adaptive encoder, split encoder, reader dispatch, full/lean cursor | Execute existing production through workloads | Codec/algorithm/refactor change |
| Normal builder and native compactor | Genuine E/F inputs, one prescribed native compact | Alternate producer or hand-built containers |
| Manifest/CURRENT/mutation state | Observe generations, hashes and real reopen | Direct edit/upload to force success |
| Local FS / remote S3 | Real public boundaries | Fake Directory/ObjectStore or result |
| Benchmark adapter | Existing release executable, unchanged JSONL protocol | Instrumentation or extra timed operations |
| Lean controller/statistics | Existing perf-06 CLI and exact reanalysis | New study family, estimator, cache redesign or injected seam |
| General test/QA infrastructure | User exception | Running suites to fill a checklist |
| Roadmap/registers | Current-status amendment after observations | Rewriting historical verdicts |

### 4.2 State and adversarial coverage

The bounded qualification explicitly covers old E-only, mixed E+F, native F-only, held old PITs, dropped owner handles, empty remote workspaces and a genuinely new reader process.

| Plausible incorrect behavior | Fixed discriminator |
| --- | --- |
| An alleged E fixture was created by F | Required E/1 and no F/1 in generation1; markers3 including singleton |
| Append silently rewrites all old segments | Generation2 must contain one E and one F segment; original objects unchanged |
| Compaction preserves the wrong family or misses short/long reclassification | Generation3 requires only F/1; markers3 for df130,7 for df104,5 for singleton |
| Search returns correct totals but wrong/empty/duplicate/reversed hits | Exact hit lengths and ordered key vectors, no deduplication |
| Returned scores are compared only to the engine itself | Frozen pre-A1 scalar BM25 bits for alpha, plus generic path and K prefixes |
| Phrase/zeta count is right but membership is wrong | Independent ordinal-derived membership vectors |
| New state leaks into an old PIT | Separate129/130 key and bit-map expectations |
| Resident reader hides rewritten old bytes | Hash both generation1 and generation2 objects before compaction; read disk again afterward |
| Remote reopen accidentally uses writer-local files | New nonexistent workspace roots and separate process |
| A cached old preparation is described as a fresh writer observation | Preserve prepared_utc/cache_status; separate four fresh resource builds |
| Zero-crossing CI is misreported as failure to compute | Keep analyzer INCONCLUSIVE; evaluate fixed numerical guard/retention rules |
| A failed/incomplete run disappears on restart | Started marker consumes the invocation before process launch; never delete it |

Malformed-codec, allocation-failure, cancellation, crash-injection, remote races, MSRV and broad regression coverage are not re-executed. They remain part of the accepted main implementation under the user's exception. Their omission does not turn A6 into a new codec-verification campaign.

## 5. Fixed workloads and timing semantics

### 5.1 Benchmark corpus and lanes

Reuse runtime.create_corpus, runtime.row_values and runtime.expected_answer. Do not generate a different corpus.

For input ordinal i in [0,N):

- doc_id = d followed by i as eight decimal digits.
- key = singleton when i=0; otherwise common for even i and other for odd i.
- group = medium when i mod8=0, otherwise different.
- body = alpha beta for even i, gamma delta for odd i.
- payload = payload- followed by the eight-digit ordinal.

The exact TSV header is doc_id, key, group, body, payload separated by tabs. The native builder owns schema/analyzer settings. The independent oracle expects absent0, rare1, medium N/8, common N/2−1, with the first K logical IDs in ascending keyword order.

| Dimension | Frozen values |
| --- | --- |
| N | 10,000 and 100,000 |
| Class | absent, rare, medium, common |
| K | 10 and 100 |
| Regime | warm |
| Lane count | 16 |
| Baseline/treatment | A/B, both real pinned Quervant |
| Controls | AA/AA2 aliases of that campaign's A |
| Blocks | 12 |
| Slots per arm per block | 2 |
| Warmups per slot/lane | 5 |
| Positive timed samples per record | 20 |
| Bootstrap resamples | 10,000 |
| Seed | 20261122 |
| A/A bound | Signed gain and entire 95% confidence interval inside ±15% |
| Exclusions | Empty mapping; no block pruning |
| Raw records per phase | 768 =16×12×2arms×2slots |
| Raw records per campaign | 1,536 across controls+treatment |
| Recorded timed samples per campaign | 30,720 |
| Both campaigns combined | 3,072 records /61,440 timed samples, if COMPLETE |

Do not count warmups as samples. Do not add a candidate B/B campaign, a startup, throughput, cross-engine or profiling acquisition.

### 5.2 Estimator and timing boundary

Use the unchanged native paired whole-block estimator and seeded bootstrap in statistics.analyze: take each slot's sample median, average the two slot medians for each arm/block, form 12 paired B/A block ratios, and take their median. Gain is 100 ×(1−ratio); the bootstrap resamples whole paired blocks. Report its gain_percent and gain_ci_95_percent without re-rounding before gate evaluation. Preserve its IMPROVED/REGRESSED/INCONCLUSIVE status independently of the A6 policy decision.

Warm timings measure the existing exact-term search plus top-K projection. Builds, process startup, index open, corpus parsing, compatibility operations, GNU-time diagnostics and read-only analysis are outside the query timing window.

No external profiler, tracing subscriber, allocation counter, GNU-time wrapper or resource sampler may wrap the warm run/adapter query process.

### 5.3 Fixed warm acceptance policy

These policy gates are evaluated after native validity and replay pass. Do not modify native configuration thresholds to encode them; configuration min_gain_percent and max_regression_percent remain 0.

| Campaign / category | Required decision |
| --- | --- |
| R: every one of 16 lanes | gain_percent >=−2.0 AND lower95%CI >=−5.0 |
| C: each of 4 primary lanes | native status IMPROVED AND gain_percent >=5.0 AND lower95%CI >0.0 |
| C: each of 12 guard lanes | gain_percent >=−10.0 AND lower95%CI >=−10.0 |

Campaign C primary lanes are exactly100000/common/k10/warm,100000/common/k100/warm,100000/medium/k10/warm,100000/medium/k100/warm. All other lanes are guards.

R's bounds are a newly frozen A6 retention budget: at most 2% observed slowdown, with the confidence interval excluding losses worse than 5%. They are not proof of exact equivalence or zero regression. A small statistically significant REGRESSED result can satisfy this numerical budget; report both facts.

C preserves A4's 5% primary target and guard limits. A computable zero-crossing interval can pass a guard or R budget. An uncomputable, missing or invalid estimate never passes. All lane decisions are mandatory; do not average a failed lane away.

A valid numerical failure is unfavorable evidence, not an excuse to repeat acquisition. Continue the second preauthorized campaign after a valid unfavorable first result. A host/readiness/oracle/source/control validity failure stops remaining timing as specified in §15.

## 6. Preparation, freeze and exact run commands

### 6.1 Task layout

From the verified controller checkout, set:

~~~bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
A6_SCRATCH="$REPO_ROOT/target/perf06-a6"
A6_ARTIFACTS="$REPO_ROOT/docs/pr-artifacts/perf-06-a/a6"
A6_SUPPORT="$A6_ARTIFACTS/support"
~~~

Use one new A6 invocation UUID, recorded once in the report and used for the remote prefix. Persist it with the exact recipe below; on resume reuse its validated bytes. Create scratch, support, acquisition and compatibility evidence directories without deleting prior contents. A preexisting completed or partially started A6 directory follows resume rules, not a fresh-start assumption.

Keep large builds, corpora, native/remote reader workspaces and temporary diagnostic indexes under A6_SCRATCH. RustFS uses only the task-owned container storage described in §8, not an invented host mount. They are not committed. Exact plan/support files and bounded evidence remain in A6_ARTIFACTS.

### 6.1a Explicit task identity and executable bindings

Run this after the verified branch/layout setup and before any A6 operation. The persisted UUID file is authoritative across resume; a valid existing UUID is reused, never replaced.

~~~bash
mkdir -p "$A6_SCRATCH" "$A6_SUPPORT" "$A6_ARTIFACTS/acquisition" \
  "$A6_ARTIFACTS/compatibility" "$A6_ARTIFACTS/verification"
A6_UUID="$(python3 - "$A6_ARTIFACTS/invocation-uuid.txt" <<'PY'
from pathlib import Path
import os, sys, uuid
p = Path(sys.argv[1])
if p.exists():
    value = p.read_text(encoding="ascii").strip()
    if str(uuid.UUID(value)) != value:
        raise SystemExit("STOP: invalid retained invocation UUID")
else:
    value = str(uuid.uuid4())
    with p.open("x", encoding="ascii") as f:
        f.write(value + "\n")
        f.flush()
        os.fsync(f.fileno())
print(value)
PY
)"
A6_REMOTE_PREFIX="perf06-a6/$A6_UUID"
A6_CONTAINER_NAME="quervant-perf06-a6-$(printf '%.8s' "$A6_UUID")"
A6_IMAGE="rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c"
E_DRIVER="$A6_SCRATCH/compat-target/E/release/examples/perf06_a6_compatibility"
F_DRIVER="$A6_SCRATCH/compat-target/F/release/examples/perf06_a6_compatibility"
NATIVE_ROOT="$A6_SCRATCH/compatibility/native-index"
~~~

RUNNER_SHA was assigned in §2.4. Preserve that original value on resume by reading the started marker/report; do not overwrite an old measured source with the current HEAD. If there is no prior acquisition, it must equal the current committed controller HEAD.

Appendix E extracts the four supplied support files. Set A6_PLAN to the actual local path of this approved downloaded plan before extraction; never substitute an earlier A5/F1 plan.

### 6.1b Exact compatibility log capture

Use this fixed shell function for the six ordinary compatibility processes. Its log files are exclusive. A completed or partially launched mode is never retried by calling it again. The driver itself emits terminal PASS only after its assertions; the function also requires a zero exit and checks that the final JSONL line has the exact mode and PASS.

~~~bash
a6_compat_once() {
  local label="$1"
  local driver="$2"
  local mode="$3"
  local root="$4"
  local log_root="$A6_ARTIFACTS/compatibility"
  shift 4
  if test -e "$log_root/$label.stdout.jsonl" || test -e "$log_root/$label.stderr.log" || test -e "$log_root/$label.exit.txt"; then
    printf 'STOP: compatibility invocation history exists: %s\n' "$label" >&2
    return 90
  fi
  local code=0
  (set -o noclobber; "$driver" "$mode" "$root" "$@" >"$log_root/$label.stdout.jsonl" 2>"$log_root/$label.stderr.log") || code=$?
  (set -o noclobber; printf '%s\n' "$code" >"$log_root/$label.exit.txt") || return 91
  if test "$code" -ne 0; then
    printf 'STOP: compatibility mode failed: %s exit=%s\n' "$mode" "$code" >&2
    return "$code"
  fi
  python3 - "$log_root/$label.stdout.jsonl" "$mode" <<'PY'
import json, sys
from pathlib import Path
lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
if not lines:
    raise SystemExit("STOP: empty compatibility evidence")
for line in lines:
    row = json.loads(line)
    if row.get("schema") != "perf06-a6-compatibility-v1":
        raise SystemExit("STOP: unexpected compatibility output schema")
if json.loads(lines[-1]) != {"schema": "perf06-a6-compatibility-v1", "mode": sys.argv[2], "status": "PASS"}:
    raise SystemExit("STOP: missing terminal compatibility PASS")
PY
}
~~~

Call each next mode only if the preceding call returns0. A nonzero return applies the matrix; do not continue the dependent lifecycle. This function is a frozen shell recipe, not an additional repository support file.


### 6.2 Freeze both configurations before any acquisition

Ensure neither new campaign name/UUID already exists anywhere under benchmarks/studies. Use the native prepare command exactly once per new campaign and capture the returned path.

~~~bash
python3 -m quervant_bench prepare --family perf-06 --regime warm \
  --name quervant-perf06a6-adaptive-warm \
  --description "PERF-06-A6 isolated adaptive-postings E-to-F paired warm qualification; fixed retention policy in approved A6 plan" \
  --baseline-revision b70f624fffe0329def62701b61e997c4e303e167 \
  --candidate-revision 3bb232f868cb556ce9b4273d902164c65416af0f

python3 -m quervant_bench prepare --family perf-06 --regime warm \
  --name quervant-perf06a6-cumulative-warm \
  --description "PERF-06-A6 cumulative A1-A3 plus A5 A0-to-F paired warm qualification; original 5 percent primary target" \
  --baseline-revision 2a74017958c8ac61948f931e8745bf8134827025 \
  --candidate-revision 3bb232f868cb556ce9b4273d902164c65416af0f
~~~

Set R_CONFIG and C_CONFIG to those actual returned paths, not guessed dates. Validate both:

~~~bash
python3 -m quervant_bench validate --config "$R_CONFIG"
python3 -m quervant_bench validate --config "$C_CONFIG"
~~~

Require VALID and exact equality with the frozen workload/policy/build/arm maps in the supplied verifier. Record each path, UUID, creation timestamp and SHA-256. The two UUIDs must differ from each other and from all historical configurations. Never mutate the JSON after preparation.

Configuration validation is operational admission, not a waived unit-test suite.

### 6.3 No redundant standalone staging

Do not run the standalone stage command. The production run path already calls stage_inputs, builds/reuses the release adapters and indexes, and executes all 32 untimed lane/arm oracles before controls.

Actual sizes are outcomes, not a precondition that requires another stage invocation. Avoiding stage→run also avoids the otherwise duplicated32 oracle checks. Reuse an existing valid cache only through the native mechanism; never copy or rewrite prepared.json, override programs, inject index_builder/invoke_phase, bypass fingerprints or modify a timed index.

### 6.4 Exclusive single-invocation guard

Use the exact run_a6_once.py supplied in Appendix D. It records an exclusive started marker before launching the ordinary CLI. A started marker consumes that campaign's invocation even if the process is interrupted before publishing a result. It is not an approval token or a replacement benchmark framework; it prevents accidental repeat execution.

Run R first:

~~~bash
python3 "$A6_SUPPORT/run_a6_once.py" "$REPO_ROOT" "$A6_SCRATCH" \
  "$A6_ARTIFACTS/acquisition" "$R_CONFIG"
~~~

After R publishes its actual result reference, invoke the C guard only under §15's continuation rule. The supplied guard performs the exact R-only verify_one()/classify() call BEFORE creating C's started marker or launching C. It requires COMPLETE, native validity and both analysis replays; a numerical NOT_MET result does not block C. No verifier design is delegated to the agent. Then:

~~~bash
python3 "$A6_SUPPORT/run_a6_once.py" "$REPO_ROOT" "$A6_SCRATCH" \
  "$A6_ARTIFACTS/acquisition" "$C_CONFIG"
~~~

The final combined verifier deliberately rechecks R read-only after C to establish final artifact integrity and cross-campaign agreement. This small data-only repeat executes no query, build or acquisition.

The inner command is exactly python3 -m quervant_bench run --config <frozen config> --scratch-root <A6 scratch>. No standalone A/A rerun or alternate phase entry point is allowed.

Record exit code and the actual RESULT_JSON path. Native exit0 only means the CLI did not return its INCOMPLETE exit code; it can also accompany native INCONCLUSIVE. Require the actual saved status COMPLETE and the prescribed validity checks. Native exit4 means INCOMPLETE. Preserve other errors, partial logs and any result that exists.

## 7. Genuine E/F compatibility design

### 7.1 Fixed executable and source provenance

Appendix A supplies the complete executable source. The agent must copy it without redesign into the A6 support path, then into exactly one untracked example path in each of two dedicated detached worktrees:

~~~bash
git worktree add --detach "$A6_SCRATCH/compat-worktrees/E" b70f624fffe0329def62701b61e997c4e303e167
git worktree add --detach "$A6_SCRATCH/compat-worktrees/F" 3bb232f868cb556ce9b4273d902164c65416af0f
~~~

Both temporary worktrees must be absent initially or match the exact resume identity. Refuse a collision. Copy the same approved file to crates/quervant-core/examples/perf06_a6_compatibility.rs in each, creating the examples directory if absent.

Require no tracked source delta in either worktree and exactly that one allowed untracked example. Record the example digest and each worktree's HEAD. Do not add a feature constant to E or rewrite its writer to emulate old output.

Build the two examples once with the existing s3 feature so the same qualification executable can run both native and remote modes:

~~~bash
cargo +1.98.1 build --release --locked -p quervant-core \
  --features s3 --example perf06_a6_compatibility \
  --manifest-path "$A6_SCRATCH/compat-worktrees/E/Cargo.toml" \
  --target-dir "$A6_SCRATCH/compat-target/E"

cargo +1.98.1 build --release --locked -p quervant-core \
  --features s3 --example perf06_a6_compatibility \
  --manifest-path "$A6_SCRATCH/compat-worktrees/F/Cargo.toml" \
  --target-dir "$A6_SCRATCH/compat-target/F"
~~~

Use E_DRIVER and F_DRIVER as explicitly bound in §6.1; they point to the corresponding release/examples/perf06_a6_compatibility executables. Record their SHA-256 and compiler version. This build enables no experiment feature and does not execute a suite. The measured benchmark adapters remain separate native builds with their existing feature selection.

The supplied Rust source was checked against both revisions' APIs during planning but was not compiled in this planning environment. A compilation failure is a scoped driver-preparation blocker: preserve exact diagnostics and stop compatibility work for amendment. Do not alter imports, APIs, dependencies, assertions, formulas or lifetimes by guess. Independent warm/storage work may continue because it uses unchanged accepted executables.

### 7.2 Fixed compatibility corpus

The complete code uses the existing A5 I05 schema: grp Keyword indexed/stored; doc_id Keyword indexed/stored/columnar; n I64 stored/columnar; body Text indexed/stored with standard_folded.

For ordinal i:

- Logical key k followed by five digits; doc_id field d followed by five digits.
- grp is common; n is i mod7.
- body contains (i mod4)+1 copies of alpha, then i mod5 copies of zeta separated by spaces.
- E writes ordinals0…128 in one commit.
- F appends ordinal129 in one commit.

| Observation | Generation1 | Generation2/3 |
| --- | ---: | ---: |
| Documents | 129 | 130 |
| Alpha frequency sum | 321 | 323 |
| Zeta frequency sum | 256 | 260 |
| Total body length | 577 | 583 |
| alpha-alpha phrase members | 96 | 97 |
| Zeta members | 103 | 104 |

All complete queries use TopK300. K10/K100 are additionally checked for explicit doc_id ascending and relevance sorting. Relevance ordering comes from the independent scalar score map with key-ascending ties.

The source asserts every expected total, hit length and ordered logical-key vector; alpha score bits use the fixed pre-A1 formula. It verifies generic And([alpha]), phrase/zeta membership, and held-PIT bit maps. No expected set is derived from engine output.

### 7.3 Native execution: exactly three processes

Use the NATIVE_ROOT binding in §6.1 and require that path not to exist before create-e. Each command gets separate stdout JSONL and stderr logs; use exclusive log creation and record exit status.

~~~bash
a6_compat_once native-create-e "$E_DRIVER" create-e "$NATIVE_ROOT" &&
a6_compat_once native-advance-f "$F_DRIVER" advance-f "$NATIVE_ROOT" &&
a6_compat_once native-verify-f "$F_DRIVER" verify-f "$NATIVE_ROOT"
~~~

The second command depends on success of the first; the third depends on the second. Do not parallelize them.

| Phase | Required observations |
| --- | --- |
| E create/commit/close/reopen | Generation1; one E/1 segment, no F/1; alpha marker3 df129, zeta marker3 df103, doc_id singleton marker3 |
| F open and append | Actual generation1 PIT; public append of ordinal129; generation2; one E plus one F segment; appended F singleton marker5 |
| F native compact | Exactly one compact; generation3, documents130, segments_merged2, no_op=false; one F segment |
| Compacted format | alpha/common marker3 df130; zeta marker7 df104; old/new doc_id singleton marker5 |
| Reader/PIT evidence | Fresh reopen; generation3 maps equal generation2; held PIT1 still129, PIT2 still130 with their saved maps |
| Immutable objects | Every captured generation1 AND generation2 immutable file retains length and SHA-256 after compaction |
| New-process verification | Third executable invocation opens generation3 and repeats the full frozen search/format contract |

The driver excludes only mutable index/CURRENT and index/WRITER_LOCK from immutable-file inventory. It does not delete generations or run garbage collection.

### 7.4 Remote execution: exactly three processes

Run remote work after both warm campaigns and resource observations, so an owned service cannot contend with query measurements. Use the fixed pinned real RustFS topology in §8.

~~~bash
(
  export QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:19000
  export QUERVANT_RUSTFS_REGION=us-east-1
  export QUERVANT_RUSTFS_BUCKET=quervant-perf06-a6
  export QUERVANT_RUSTFS_ACCESS_KEY=quervanttest
  export QUERVANT_RUSTFS_SECRET_KEY=quervantsecret
  a6_compat_once remote-create-e "$E_DRIVER" remote-create-e "$A6_SCRATCH/compatibility/remote-e" "$A6_REMOTE_PREFIX" &&
  a6_compat_once remote-append-f "$F_DRIVER" remote-append-f "$A6_SCRATCH/compatibility/remote-f" "$A6_REMOTE_PREFIX" &&
  a6_compat_once remote-verify-f "$F_DRIVER" remote-verify-f "$A6_SCRATCH/compatibility/remote-reader" "$A6_REMOTE_PREFIX"
)
~~~

Each root must be new. The driver also creates distinct empty internal workspaces for every cold reopen.

The first process creates the task-local bucket if absent, then uses the genuine E RemoteIndex writer. It awaits durable generation1 publication, closes the writer, reads authoritative remote CURRENT, and cold-opens E.

The second F process cold-opens E, pins generation1, captures the original remote manifest/segment/mutation-state bytes, appends ordinal129 and awaits generation2 publication. It reads remote CURRENT2, cold-opens mixed E+F, pins generation2, drops the owning index handle, verifies both held PITs and rereads the original immutable remote objects.

The third fresh process reads remote CURRENT2 and cold-opens mixed E+F from another empty workspace. Its terminal PASS requires the complete query/format contract.

No workspace is copied from the writer. No local cache, manifest or state pointer is transplanted. No fake provider, direct object upload or manual CURRENT modification is permitted.

### 7.5 Explicit remote-compaction residual

This plan does not qualify remote compaction publication. Inspected unchanged source shows RemoteIndexWriter::compact delegates to native compaction, while remote commit returns early for a no-op underlying commit before publication. That source observation is not a claimed runtime failure and is not authority to fix or work around the path.

A6 establishes native E→E+F→F compaction plus remote E→E+F append/cold-reopen/PIT/state-pointer behavior. Record remote compaction publication as NOT QUALIFIED — MAINTAINER-OWNED FOLLOW-UP. Do not claim universal remote lifecycle qualification or automatically unblock B1. The maintainer must explicitly dispose of this bounded residual when deciding promotion.

## 8. Real RustFS topology without running integration suites

### 8.1 Fixed service

| Property | Value |
| --- | --- |
| Image | rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c |
| Host binding | 127.0.0.1:19000 → container9000 |
| Endpoint | http://127.0.0.1:19000 |
| Region | us-east-1 |
| Bucket | quervant-perf06-a6 |
| Prefix | perf06-a6/<one recorded A6 invocation UUID> |
| Credentials | Dedicated local fixture credentials quervanttest / quervantsecret, as used by the pinned CI fixture; never real account credentials |
| Container | One task-owned quervant-perf06-a6-<first8 UUID characters> |
| Storage | Task-owned container writable layer and any image-declared anonymous volumes; no existing host data mount |
| Provider | Existing production S3ObjectStore, actual RustFS |
| Concurrency | One writer and prescribed sequential operations; no races/repeat campaigns |
| Cleanup | Stop/remove only the container and anonymous volumes created by this task, after evidence capture |

Use an already available functioning podman command; otherwise use already available functioning docker. A missing/broken runtime is a scoped remote-environment blocker. Do not install a runtime, change daemon configuration or request elevated repair. If both are available, choose podman deterministically.

Check the exact image locally; if absent, one pull of this exact digest is authorized. A pull failure blocks remote qualification. Do not substitute latest or another tag.

Do not reuse a foreign listener/container on19000 or repurpose a service on9000. A binding/name collision blocks remote work; no alternate port or endpoint is authorized. The qualification driver enforces the fixed endpoint and bucket.

### 8.2 Launch and readiness

Perform these steps only in P5, after all warm acquisitions and resource observations. Select the engine first:

~~~bash
A6_CONTAINER_ENGINE=
if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
  A6_CONTAINER_ENGINE=podman
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  A6_CONTAINER_ENGINE=docker
else
  printf 'BLOCKED: no functioning authorized local container runtime\n' >&2
fi
~~~

If the value is empty, apply D25 and skip remote launch; continue reporting. Do not run a command with an empty executable.

Inspect the exact image using the selected engine:

~~~bash
"$A6_CONTAINER_ENGINE" image inspect "$A6_IMAGE"
~~~

If that image is absent, one exact pull is authorized:

~~~bash
"$A6_CONTAINER_ENGINE" pull "$A6_IMAGE"
~~~

A pull failure blocks remote work. Do not try another tag, runtime, service or registry. Confirm the task's container name is absent using the selected engine's inspect command; an existing container requires ownership/resume reconciliation, never replacement. The port binding below must succeed; it may not be changed on collision.

Launch exactly once, capturing the returned container ID in A6_CONTAINER_ID:

~~~bash
A6_CONTAINER_ID="$("$A6_CONTAINER_ENGINE" run --detach --name "$A6_CONTAINER_NAME" \
  --publish 127.0.0.1:19000:9000 \
  --env RUSTFS_ACCESS_KEY=quervanttest \
  --env RUSTFS_SECRET_KEY=quervantsecret \
  --health-cmd "curl -fsS http://localhost:9000/health || exit 1" \
  --health-interval 5s --health-timeout 5s --health-retries 30 \
  "$A6_IMAGE")"
~~~

Require launch exit0 and a nonempty returned ID before any dependent step. Record that ID and the image digest in the report and an exclusive verification/rustfs-container-id.txt file. Use the recorded ID for all subsequent inspect/log/stop/remove operations. Never infer ownership merely from a matching name.

Use the image's own default entry point/command, as the pinned CI service does. Do not supply an invented RustFS subcommand, host directory mount or permission workaround. Record actual storage from the engine's inspect output; only task-owned writable-layer data and any image-declared anonymous volumes are allowed.

Wait for the fixed endpoint with this bounded readiness recipe; it prints each observation so the agent can continue progress reporting:

~~~bash
python3 - <<'PY'
import time
import urllib.error
import urllib.request
endpoint = "http://127.0.0.1:19000/health"
deadline = time.monotonic() + 150.0
for attempt in range(1, 31):
    try:
        with urllib.request.urlopen(endpoint, timeout=2.0) as response:
            if response.status == 200:
                print(f"RUSTFS_HEALTH=PASS observation={attempt}", flush=True)
                break
    except (OSError, urllib.error.URLError):
        pass
    print(f"RUSTFS_HEALTH=PENDING observation={attempt}", flush=True)
    remaining = deadline - time.monotonic()
    if attempt == 30 or remaining <= 0:
        raise SystemExit("BLOCKED: pinned task-owned RustFS did not become healthy")
    time.sleep(min(5.0, remaining))
PY
~~~

This is service startup only. It does not authorize a host-readiness retry or new benchmark invocation. On failure preserve bounded container logs/inspect metadata, apply D25 and complete independent handoff.

After health succeeds, execute the complete §7.4 block. It exports fixed QUERVANT_RUSTFS_* settings inside a subshell containing all three remote invocations. Do not export them in the parent shell: preparation.source_identity hashes QUERVANT_* variables, and a changed environment would invalidate later cache verification even when files are identical.

Do not run cargo test or the pr13 harness to bootstrap the bucket or prove provider health. The supplied remote-create-e mode owns bucket creation and real production-path qualification.

After capturing actual outcomes, stop/remove only the recorded task-owned container:

~~~bash
"$A6_CONTAINER_ENGINE" stop "$A6_CONTAINER_ID"
"$A6_CONTAINER_ENGINE" rm --volumes "$A6_CONTAINER_ID"
~~~

These commands must use the ID recorded from this task's successful launch, not a guessed/foreign ID. No global prune/reset or named-volume deletion is authorized.

If remote work cannot run, mark G3 BLOCKED and finish all independent evidence/reporting. Never substitute prior A5 RustFS CI for this new E+F qualification.


## 9. Whole-index size qualification

### 9.1 Reuse existing measurement outputs

Use Campaign R index_metrics A as E and B as F. Use Campaign C index_metrics A as A0 and B as a second independently built F observation. Each result includes two sizes and native validation against disk.

Require:

- One segment per fresh benchmark index.
- Positive integer index_bytes, index_ns, commit_ns and reopen_ns.
- All candidate F sizes agree across the two campaigns.
- Diagnostic fresh E/F build sizes in §10 equal the corresponding R stage sizes.
- Cache fingerprints and result/manifest metric agreement pass read-only verification.

Do not rerun a build solely to obtain another size number. Do not measure a compatibility directory containing old generations, use du allocated blocks, or silently exclude manifest/state/CURRENT bytes.

### 9.2 New prospective A6 byte gates

At EACH N=10,000 and 100,000, require both:

~~~text
F_bytes / E_bytes <= 0.70
F_bytes / A0_bytes <= 1.00
~~~

Use exact integer comparisons:

~~~text
100 * F_bytes <= 70 * E_bytes
F_bytes <= A0_bytes
~~~

These are new predeclared A6 criteria: remove at least 30% of E's whole-index footprint while returning to no more than the pre-A1 footprint. They are not preexisting A4/A5 thresholds.

### 9.3 Projection versus measured explanation

The historical model predicts:

~~~text
E_bytes − F_bytes = 90 * (N + 1)
~~~

It accounts for N indexed doc_id singleton lists plus one singleton-key list, each saving 90 bytes. Its conditional assumptions are identical corpus/schema, one-segment shape and unchanged other file lengths.

Historical reference values, not new A6 measurements:

| N | A0 historical bytes | E historical bytes | F projected bytes |
| ---: | ---: | ---: | ---: |
| 10,000 | 1,560,111 | 2,356,869 | 1,456,779 |
| 100,000 | 15,747,551 | 23,713,222 | 14,713,132 |

Report actual A6 totals, E−F, percent reduction, both ratios, model-predicted difference and actual-minus-predicted difference.

Exact model equality closes MODEL_CONFIRMED. A mismatch does not authorize changing the formula or production. Perform only the exact read-only whole-file fingerprint inventory below; state the observed file-level difference and retain MODEL_NOT_CONFIRMED if not fully explained. Do not decode segment sections or design an inspector. Do not design a new profiler/parser or a new build. A size target can be met while the model remains unconfirmed; keep those dispositions separate and require maintainer review of the residual.

The only additional inspection authorized for a size-model mismatch is this exact fingerprint inventory, after native read-only cache verification. It writes a new auxiliary TSV and executes no query/build/parser:

~~~bash
python3 - "$R_RESULT" "$A6_SCRATCH" "$A6_ARTIFACTS/verification/model-file-inventory.tsv" <<'PY'
import csv, json, sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
key = result["context"]["preparation"]["cache_key"]
cache = Path(sys.argv[2]) / "prepared" / key
manifest = json.loads((cache / "prepared.json").read_text(encoding="utf-8"))
fingerprints = manifest["file_fingerprints"]
out = Path(sys.argv[3])
with out.open("x", encoding="utf-8", newline="") as stream:
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(["source", "documents", "relative_file", "bytes", "sha256"])
    for arm, source in [("A", "E"), ("B", "F")]:
        for n in [10000, 100000]:
            prefix = f"indexes/{arm}/n{n}/"
            selected = [(name, item) for name, item in sorted(fingerprints.items()) if name.startswith(prefix)]
            if not selected:
                raise SystemExit("STOP: missing verified index inventory")
            if sum(item["bytes"] for _, item in selected) != result["index_metrics"][arm][str(n)]["index_bytes"]:
                raise SystemExit("STOP: inventory sum differs from measured index bytes")
            for name, item in selected:
                writer.writerow([source, n, name.removeprefix(prefix), item["bytes"], item["sha256"]])
PY
~~~

A preexisting inventory is inspected/reused if its exact provenance is intact; do not overwrite it or use another filename to conceal a mismatch.


## 10. Four descriptive build-process resource observations

### 10.1 Why a separate observation is necessary

Native preparation records insertion, commit, reopen wall time, whole-index bytes and segment count. It does not record CPU time or RSS and offers no production callback for attaching that measurement.

Wrap the already-built adapter process, not the full stage/controller/compiler, using GNU /usr/bin/time. This requires four fresh indexes but no new adapter compilation, corpus generation, query campaign or framework change.

Use Appendix C's exact measure_a6_writer.py. It calls the existing runtime.build_index, preserving its count/protocol/positive-timer/on-disk-byte checks.

### 10.2 Fixed cases and order

| Order | Source | N |
| ---: | --- | ---: |
| 1 | E | 10,000 |
| 2 | F | 10,000 |
| 3 | F | 100,000 |
| 4 | E | 100,000 |

Use Campaign R's verified programs/corpora and its recorded adapter CPU. Do not measure A0 CPU/RSS or F twice across campaigns. There is one observation per cell, no repetitions, medians or confidence intervals for these diagnostics.

Invoke the helper once with a nonexistent scratch diagnostic root:

~~~bash
mkdir -p "$A6_ARTIFACTS/writer"
(
  set -o noclobber
  python3 "$A6_SUPPORT/measure_a6_writer.py" \
    "$R_CONFIG" "$R_RESULT" "$A6_SCRATCH" "$A6_SCRATCH/writer-diagnostics" \
    >"$A6_ARTIFACTS/writer/driver.log" 2>&1
)
~~~

The helper verifies the cache without restaging, runs the four fixed builds, preserves resource outputs, and verifies the cache again. If a case fails, preserve completed rows/partial files and stop the remaining resource work; no automatic retry.

### 10.3 Exact semantics

GNU-time fields are user CPU seconds, system CPU seconds, elapsed wall seconds, exit status and maximum resident KiB. Convert KiB to bytes with1024. CPU total is user+system.

They cover the entire adapter lifetime: startup, TSV parsing, index creation, insertion, commit, writer close, verification reopen and byte walk. They are NOT isolated encoder CPU, insert-only memory, compaction memory, query RSS, allocation counts or OS-cache memory.

Keep the adapter's internal index_ns, commit_ns and reopen_ns separately. They have narrower boundaries. All four rows must use the same GNU-time format/locale and successful exit.

Report F/E ratios for insertion, commit, reopen, user CPU, system CPU, total CPU, elapsed process time and peak RSS at each N, with one-observation/descriptive labeling. If the E denominator is zero because GNU time rounded a component to0.00, show NOT_COMPUTABLE with both raw values; never add epsilon, divide by zero or invent a ratio. Do not ratio exit status. There is no automatic numerical writer-performance acceptance threshold and no statistical preservation claim. The maintainer evaluates the observed tradeoff alongside size and warm results; the coding agent must not invent a favorable threshold afterward.

### 10.4 Durable evidence inventory

Copy exactly these seven existing files from the scratch diagnostic root into A6_ARTIFACTS/writer, preserving relative paths and bytes:

~~~text
writer.tsv
raw-times.txt
scope.txt
01-E-n10000/resources.txt
02-F-n10000/resources.txt
03-F-n100000/resources.txt
04-E-n100000/resources.txt
~~~

Also preserve the outer helper stdout/stderr transcript as writer/driver.log. On failure copy only files actually produced; do not manufacture the missing rows/files. Exclude fresh index directories and compiled binaries. Record file hashes.

These are auxiliary diagnostic records, not benchmark-result-v1. Do not place custom resource JSON in benchmarks/studies/perf-06/warm/results or create an unsupported writer/cold study family.

## 11. Read-only verification and integrity

Run Appendix B's exact verify_a6_results.py after both COMPLETE results exist, in the same operational environment and controller checkout:

~~~bash
python3 "$A6_SUPPORT/verify_a6_results.py" "$RUNNER_SHA" "$A6_SCRATCH" \
  "$R_CONFIG" "$R_RESULT" "$C_CONFIG" "$C_RESULT"
~~~

It performs no build, query, suite or artifact rewrite. It verifies the frozen configurations, full arm/source/CPU identities,16 lanes,768 records per phase,5 warmups/20 positive samples, all 12 unpruned blocks, native readiness, actual default strategy and source/cache fingerprints. It independently replays BOTH A/A and treatment analyses and requires exact equality with saved analyses. It then applies the fixed R/C numerical policies.

The native analyze CLI replays treatment only. Do not substitute it for the supplied two-phase verification. Do not use the generic compare command to derive cumulative or incremental effects from historical runs.

For an INCOMPLETE result, do not pass it to the COMPLETE verifier and reinterpret its rejection as an extra failure. Preserve it, read its errors/readiness/available samples, classify the original obstacle, and report which phases never executed.

Before and after read-only analysis, record config/result SHA-256. Keep original JSON immutable. Verify original A4 result Git objects remain c7d49358fdaf0a6f4591f7a70d3ad2d5eba2cb40 and dbbd5116ccbfe06a0fc8099ab2fbeee4967ccc12, and every protected path has zero task delta.

Whole-index nondeterminism (same source/corpus but different total bytes), provenance mismatch, corrupted cache, result tampering or replay mismatch stops the affected acceptance claim. Do not edit the artifact to make a verifier pass.

## 12. Performance sensitivity and bounded work

- Reuse the existing lean controller, adapter protocol, corpus/oracle and statistics.
- Invoke run directly; no duplicate stage/oracle cycle.
- Reuse each campaign's native cache as designed; do not introduce cross-config cache sharing.
- Run the two campaigns sequentially. No parallel builds, resource observations or RustFS activity during query timing.
- Compile the compatibility driver once per revision with the existing s3 feature; use those binaries for all its modes.
- Reuse built benchmark adapters and staged TSVs for the four resource observations.
- Keep all auxiliary code outside production hot paths and outside benchmark source injection.
- No cold-cache manipulation, perf/flamegraph/profiler, background telemetry, new allocator, dependency upgrade or retained-key tuning.
- Compatibility uses129/130 documents, not the full benchmark corpus.
- Resource observations are four fixed builds, not a statistically repeated write benchmark.
- Read-only reanalysis may be repeated for report accuracy; no repeated acquisition is thereby authorized.
- Stop optional investigation once prescribed evidence is complete.

## 13. Ordered execution sequence

| Phase | Required work | Continue condition |
| --- | --- | --- |
| P0 | Fetch/reconcile source, record user exception, exact pins, source closure, operational tool versions, ownership/resume state | G0 |
| P1 | Copy approved plan/support; freeze both new configs; create dedicated E/F qualification worktrees and compile examples | G1; compatibility build blocker may be isolated |
| P2 | Three native compatibility processes and exact output/immutability checks | G2, or scoped driver-environment block under D08; actual semantic failure stops dependent measurement |
| P3 | Run R once, classify native validity; run C once when permitted | G4/G5 validity separately from numerical outcome |
| P4 | Read-only replay; measured size table; four resource observations | G6/G7/G8 as applicable |
| P5 | Start owned pinned RustFS, three remote compatibility processes, capture evidence, remove owned service | G3; missing service is isolated from completed warm work |
| P6 | Write report, current-status amendments, residuals, gate table and command ledger | G9 |
| P7 | Verify allowlist/protected hashes; one ordinary evidence commit/push and draft PR if authorized; no CI wait | Delivery completed or accurately blocked |
| P8 | Final handoff with actual source/head/remote identities, outcomes and maintainer next decision | G10 remains maintainer-owned |

Do not turn passing phase boundaries into permission prompts. If an isolated gate is blocked, execute every independent row allowed by §15 before the final handoff.

## 14. Failure taxonomy, statuses and acceptance gates

### 14.1 Classify from evidence

| Class | Evidence needed | A6 response |
| --- | --- | --- |
| Qualification-driver preparation defect | Concrete compile/launch error in supplied auxiliary executable; production unchanged | Stop compatibility for amendment; do not repair by guess |
| Observed semantic/correctness failure | Exact failing invariant, source, input, stderr and available state | Stop affected compatibility and dependent new timing; no production fix |
| Environment/harness failure | Specific missing tool/service, readiness/affinity/filesystem problem, protocol/launch failure | Scoped block; preserve attempts and continue independent work |
| Valid unfavorable measurement | COMPLETE, controls/oracles/replay valid, numerical gate not met | Preserve and finish remaining authorized independent work; no rerun |
| Model mismatch | Valid size measurement differs from fixed projection | Separate model disposition; read-only inventory only |
| Pre-existing/flaky assertion | Requires actual supporting evidence; stable-main assumption alone is insufficient | Do not invent classification or run unapproved diagnostic repeats |
| Unknown | Cannot map precisely to matrix | Stop affected work and request plan amendment after completing independent safe work |

There is no general production-fix authority and no diagnostic retry allowance for acquired campaigns. A framework/engine issue becomes a separate planned correction.

### 14.2 Gate ledger

| Gate | Required evidence | Owner |
| --- | --- | --- |
| G0 — Source/authority | Pins, source closure, merged A5, user QA/CI exception, clean applicable paths | Agent |
| G1 — Frozen protocol | Exact plan/support/config identities, new UUIDs, run budget and exclusive markers | Agent |
| G2 — Native compatibility | Three actual successful processes; E→E+F→F, exact oracles/PIT/immutability | Agent |
| G3 — Remote compatibility | Three actual successful real-RustFS processes on fixed topology; cold E/E+F, CURRENT/PIT/immutability | Agent |
| G4 — R evidence validity | One COMPLETE run; native controls/oracles/readiness; exact replay/source identity | Agent |
| G5 — C evidence validity | Same for C | Agent |
| G6 — Storage | Actual whole-index bytes, agreement checks, both per-size gates; distinct model disposition | Agent |
| G7 — Resources | Four actual successful build-process observations and accurate scope/ratios | Agent |
| G8 — Warm numerical disposition | All16 R retention gates and4 C primary +12 C guard decisions, with original analyzer statuses | Agent |
| G9 — Evidence/report integrity | Accurate report, full unfavorable evidence, protected scope, explicit residuals and delivery state | Agent |
| G10 — Acceptance/promotion | Independent maintainer review, writer-tradeoff assessment, remote-compaction residual disposition, B1 decision | Maintainer |

General suites/quality checks/CI waiting are deliberately absent from G0–G10 under the user instruction. Do not add them back.

### 14.3 Deterministic status derivation

| Condition | Report status |
| --- | --- |
| Work remains and no terminal blocker | PERF06_A6_IN_PROGRESS |
| Required operation could not execute, validity failed, or source/result cannot be verified | PERF06_A6_VERIFICATION_BLOCKED |
| Valid complete evidence exists, but any byte/R/C numerical gate is NOT_MET | PERF06_A6_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED |
| Prescribed execution/validity/byte/numerical gates pass; resources reported; known residual explicit; maintainer pending | PERF06_A6_QUALIFIED_READY_FOR_INDEPENDENT_REVIEW |
| Maintainer accepts the documented tradeoffs/residual and promotes | Maintainer records acceptance; executing agent cannot self-assign |

If some valid unfavorable evidence exists alongside a blocked gate, use VERIFICATION_BLOCKED as overall status and separately retain the unfavorable numeric decisions. A model mismatch is a separately disclosed unresolved residual; do not report MODEL_CONFIRMED. If it is unexplained, G9/overall favorable readiness remains blocked pending review.

G8 is a decision-producing gate, not a requirement that every result be favorable before reporting the work. An honest complete targets-not-met report is a completed measurement disposition, not an implementation failure.

## 15. Preauthorized decision and exception matrix

Most restrictive applicable rule wins. Every applied row goes in the report with trigger, evidence, action, affected gate and owner. AUTO-RESOLVE never authorizes a new algorithm or estimator. HARD STOP is scoped unless explicitly global.

| ID | Observable condition | Class | Exact authorized action | Prohibited action | Evidence / affected gate / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | Clean F checkout; all pins/contracts match | AUTO-RESOLVE | Execute P0→P8 continuously | Ask routine permission at phase boundaries | Source ledger; all; agent |
| D02 | Main is docs-only descendant of F, source closure unchanged and no policy conflict | AUTO-RESOLVE | Branch from current main; keep A0/E/F pins; record RUNNER_SHA | Re-pin F to latest without amendment | Diff/tree identities; G0; agent |
| D03 | Production/harness/build/toolchain/workflow/policy drift or non-ancestor source | HARD STOP measurement | Preserve source observations; request amended source contract | Rebase/adapt source or infer comparability | Exact paths/SHAs; G0; maintainer |
| D04 | Dirty tracked/staged work or untracked collision | HARD STOP checkout mutation | Preserve user work; report collision | Stash/reset/clean/delete automatically | Status/path list; G0; user |
| D05 | Old F1 report discrepancies remain after A5 merge | AUTO-RESOLVE | Record merged baseline; leave historical files untouched | Reopen old report-correction prerequisite or CI gate | Merge SHA/user instruction; G0/G9; agent |
| D06 | Required unit/QA/CI gate suggested by generic guide | AUTO-RESOLVE | Apply explicit user exception; continue operational qualification | Run suites or mark waived activity PASS/BLOCKED | Exception table; G0/G9; agent |
| D07 | Missing operational Rust1.98.1/Python/taskset/native filesystem capability | DEFER AND CONTINUE independent work | Block affected execution; preserve read-only source/docs work | Upgrade toolchain, use another compiler or bypass host contract | Exact tool/error; affected gates; maintainer |
| D08 | Supplied driver fails to compile/launch before semantic execution | DEFER AND CONTINUE | Preserve diagnostics; block compatibility; perform independent unchanged-adapter warm/storage work | Edit driver semantics/dependencies or production; pretend compile is acceptance | Error and driver hash; G1–G3; plan author |
| D09 | Native semantic assertion fails on genuine E/F data | HARD STOP dependent timing | Preserve dirs/logs; stop native continuation and any not-yet-run warm acquisition | Change oracle, rewrite fixture, fix production, retry | First assertion/source/state; G2/G4/G5; maintainer |
| D10 | New config names absent; prepare returns VALID frozen maps | AUTO-RESOLVE | Record new UUID/digest and proceed | Edit config after freeze | Exact JSON/hash; G1; agent |
| D11 | Existing identical config, no started marker/result, trustworthy prior ledger proves no invocation | AUTO-RESOLVE resume | Reuse exact config; continue unfinished pre-acquisition step | Create replacement UUID or duplicate config | Files/history; G1; agent |
| D12 | Existing result or started marker for a campaign | AUTO-RESOLVE read-only resume | Never invoke it again; verify/report existing evidence; continue unstarted independent campaign only if prior validity permits | Delete marker/result, bump sequence, rerun | Marker/log/result; G1/G4/G5; agent |
| D13 | Invocation history uncertain after lost workspace/logs | HARD STOP that acquisition | Record uncertainty; request explicit new authority | Assume no result means no prior run | Available durable evidence; G1; maintainer |
| D14 | Native cache HIT validates or clean cache miss is built automatically | AUTO-RESOLVE | Accept native behavior and retain cache provenance | Manual cache sharing/copying or redundant stage | Native context/prepared.json; G4/G5; agent |
| D15 | Published cache fails fingerprint/identity checks | HARD STOP affected measurement | Preserve cache and error | Delete/rebuild/patch it and retry under same authority | Cache key/error; G4/G5; maintainer |
| D16 | R COMPLETE with valid controls/oracles/replay but retention gate NOT_MET | AUTO-RESOLVE | Preserve failure and execute preauthorized C once; finish other work | Rerun R, drop lane or retune bound | R artifact/decision; G8; agent |
| D17 | Any source/oracle/readiness/affinity/A/A validity failure or INCOMPLETE during timing | HARD STOP all remaining warm timing | Preserve result/log; no same-campaign or other warm run until new authority; finish safe read-only/report work and unrelated compatibility if isolated | Retry-to-green, host change, pruning, check_host=False | Error/partial data; G4/G5; maintainer |
| D18 | C COMPLETE but primary/guard or size target fails | AUTO-RESOLVE unfavorable closeout | Finish resources/remote/report; derive targets-not-met status | Mark targets passed or automatically revert/adopt | Actual table; G6/G8; maintainer |
| D19 | Analyzer INCONCLUSIVE with finite valid estimates | AUTO-RESOLVE | Apply fixed numerical R/guard rule; retain INCONCLUSIVE label; primary cannot pass unless IMPROVED | Treat as uncomputable or manufacture significance | Exact point/CI/status; G8; agent |
| D20 | Replay mismatch, missing records, pruning or mutated result/config | HARD STOP affected acceptance | Preserve hashes and discrepancy; report blocked validity | Recompute and overwrite saved analysis/rows | Before/after hashes; G4/G5/G9; maintainer |
| D21 | Correct measured sizes differ from projection | DEFER AND CONTINUE | Exact supplied whole-file fingerprint inventory only; keep model unconfirmed; finish independent evidence | Change prediction, rebuild until matching, invent cause | Byte table; G6/G9; maintainer |
| D22 | Same F/corpus produces different total bytes across campaign builds, or diagnostic/stage bytes differ | HARD STOP size acceptance | Preserve all copies; no extra build; report nondeterminism/mismatch | Select favorable copy or normalize files | All byte/fingerprint identities; G6; maintainer |
| D23 | GNU /usr/bin/time absent/non-GNU or invalid resource output | DEFER AND CONTINUE | Block resource observation; finish unrelated evidence | Approximate RSS from index bytes or wrap compiler/stage | Tool/error/partial row; G7; maintainer |
| D24 | Any of four resource cases fails/interrupted | HARD STOP remaining resource observations | Preserve completed/partial cases; no repeat | Restart helper into fresh dir to obtain clean four rows | Case/logs/exit; G7; maintainer |
| D25 | Real local RustFS runtime/image/port/health unavailable | DEFER AND CONTINUE | Block G3; preserve cause and finish warm/storage/report work | Use fake/foreign provider, alternate image/port or cloud service | Container/runtime evidence; G3; maintainer |
| D26 | Real remote semantic assertion or publication fails | HARD STOP remote continuation | Preserve task container/workspaces/logs long enough to report; safe owned-service cleanup afterward | Direct CURRENT/object edits, extra mutation, provider redesign or retry | Assertion/remote generation; G3; maintainer |
| D27 | Remote compaction would be needed for broader claim | HARD STOP that expansion | Retain explicit NOT_QUALIFIED residual; maintainer chooses separate follow-up | Call compact→commit workaround, change production or imply tested | Source boundary; G10; maintainer |
| D28 | Automatic CI pending/not observed after one evidence delivery | AUTO-RESOLVE | Report actual state or NOT_OBSERVED; finish handoff without waiting | Poll/dispatch/rerun/cancel or claim success | PR/current observation; G9; agent |
| D29 | A later actual CI failure is observed | DEFER AND CONTINUE reporting | Disclose exact job/source; do not claim green; maintainer assesses outside waived execution gate | Hide failure or start unapproved code fix/suite | CI URL/state; G9/G10; maintainer |
| D30 | Only allowlisted docs/artifacts changed after measurements | AUTO-RESOLVE | Preserve exact tested/source pins and hashes; one final evidence commit; no local QA rerun | Relabel new commit as a newly measured executable | Full filename diff; G9; agent |
| D31 | Unexpected tracked source/test/workflow change | HARD STOP publication/claim | Preserve diff; request direction | Expand allowlist or quietly undo user edits | Diff; G0/G9; maintainer |
| D32 | Existing task-owned service needs cleanup | AUTO-RESOLVE | Stop/remove exact recorded task container and its anonymous volumes after evidence | Global prune/reset or touching another container | Recorded container ID; G9; agent |
| D33 | A prescribed operation reports ENOSPC/insufficient capacity, or proposed cleanup would threaten protected/unrelated data | DEFER AND CONTINUE handoff | Preserve evidence and report capacity; no acquisition under exhausted disk | Global destructive cleanup or deletion of raw outcomes | Capacity/paths; affected operation; user |
| D34 | All prescribed gates complete but maintainer acceptance absent | AUTO-RESOLVE delivery | Report appropriate review-ready/targets-not-met disposition; leave G10 open | Merge, declare B1 authorized or mark whole roadmap DONE | Gate ledger; G10; maintainer |
| D35 | A frozen commit object is absent locally | AUTO-RESOLVE bounded fetch | Fetch only the three exact pins once and repeat object/ancestry reads; block if still unavailable | Substitute another revision or fetch/rewrite until a different source fits | Exact object/fetch outcome; G0; agent |
| D36 | Any unlisted condition, contradiction, material risk or requested algorithmic choice | HARD STOP affected work | Report exact input/symbol/error/invariant and smallest needed amendment; continue only demonstrably independent authorized work | Improvise, generalize an AUTO rule, invent measurements | Evidence/dependency map; affected gates; plan author |

## 16. Report, documentation and publication

### 16.1 Required report structure

Write PERF06A6_EXECUTION_REPORT.md with:

1. Current disposition and G0–G10 ledger, including unfavorable/blocked states.
2. User's stable-main/no-suite/no-QA/no-CI-wait exception and unchanged host-readiness contract.
3. Source identities: planning main, fetched main, controller RUNNER_SHA, A0/E/F, compiler and support-file digests.
4. Protocol/config identities, names, UUIDs, creation/execution UTC timestamps and exact invocation budget.
5. Native compatibility commands, actual exits, all states/counts/feature markers, independent query/PIT/immutable checks.
6. Remote topology and actual commands/exits/state pointers/cold reopen/PIT/immutability, or precise block.
7. R result identity, all 16 A/A outcomes and all 16 A/B rows: A/B absolute latency, gain, CI, analyzer status, A6 budget result.
8. C equivalent full tables with4 primary and12 guard classifications.
9. Whole-index byte table A0/E/F for each N, agreement checks, two size gates and model comparison.
10. Four descriptive resource rows, boundaries, F/E ratios, rounding limitations and no statistical writer claim.
11. Read-only verification outputs, protected evidence identities and zero production delta.
12. All actual failures, interruptions and applied decision-matrix rows; no retry-to-green omission.
13. Residuals: remote compaction publication unqualified; one-observation resources; warm-only/local benchmark scope; no attribution within A1–A3.
14. Publication state, final head/remote identities in handoff, actual optional CI observation, and maintainer/B1 next decision.

Do not copy historical test counts/coverage as newly executed evidence. Do not fill an unexecuted operation with expected values. Keep planned inventory separate from observed output.

### 16.2 Current-status amendments

Update only the four allowlisted existing documents:

- PERF roadmap and both series registers: A5 merged at F by maintainer; A6 exact current outcome; B1 still awaits acceptance; preserve opening charters and A4's recorded targets-not-met status.
- BENCHMARKING.md: add an A6 study amendment describing the two explicitly authorized perf-06/warm comparisons, source pins, query timing boundary, fixed acquisition count, descriptive resource scope and stable-main exception specific to this task. Do not turn the one-task QA exception into permanent policy.

No architecture change is delivered. Do not update architecture docs, global test policy or CI configuration.

### 16.3 Efficient delivery

Prefer one final commit after all possible evidence is collected. Do not make an interim source commit solely to trigger CI: controller/engine inputs are unchanged and pinned, and new configs/support outside the source closure may remain uncommitted during execution.

Before committing, inspect the complete tracked, staged and nonignored-untracked path list against §3. Verify exact approved plan/support copies, original result hashes, and that no raw indexes/binaries/container data/secrets are staged. This is evidence/scope review, not a formatter/linter test gate.

Use an ordinary commit and push, no force. Create or update only the intended A6 draft PR, with a body file preserving actual newlines. Do not post comments/messages elsewhere.

Existing CI may start automatically. Do not alter workflow triggers, use skip directives, cancel checks, wait for green or push another commit solely to restate a CI observation. The report identifies the measurement source and protocol; final head/remote identity and the latest observed CI state belong in the handoff/PR body, avoiding a self-referential commit loop.

Suggested PR body:

~~~markdown
## Purpose

Qualify merged adaptive postings and the consolidated PERF-06-A implementation
using fixed genuine E/F compatibility operations, actual index bytes, bounded
build-process diagnostics and two prospective paired warm studies.

## Evidence

- Engine pins: A0 <full>, E <full>, F <full>; controller <full>.
- Native/remote compatibility: <actual results or blockers>.
- R isolated A5 retention: <all16 decisions>.
- C cumulative A-series: <4primary/12guard decisions>.
- Whole-index sizes and model: <actual table and disposition>.
- Four resource observations: <actual result; descriptive only>.
- Read-only replay/integrity: <actual result>.
- Overall: <derived status>; maintainer acceptance remains open.

## Execution exception and limits

Main is treated as stable by explicit user direction. Unit/integration suites,
formatting/lint/coverage/general QA and waiting for CI were not required or run.
Native benchmark oracles and the prescribed A6 qualification operations remain
mandatory. No production or benchmark-framework change is included.

Remote compaction publication is not qualified. Resource observations are
single-run diagnostics. A4 history is unchanged; B1 does not start automatically.
~~~

## 17. Reviewer checklist and residuals

- [ ] User QA/CI exception is explicit; no hidden suite or CI wait appears.
- [ ] A0/E/F and runner/source closure are recorded and match the fixed contract.
- [ ] Exactly two new configs and at most one invocation for each; all attempts preserved.
- [ ] Genuine E producer, complete committed state and real F reader/append/compaction are demonstrated.
- [ ] Native generation1+2 immutable objects and both PITs survive compaction.
- [ ] Real remote cold/new-process E+F reopen and authoritative CURRENT are demonstrated, or blocked accurately.
- [ ] No remote compaction claim/workaround slipped into scope.
- [ ] Oracles, A/A, readiness,16lanes,12blocks,5+20samples and both exact replays pass where COMPLETE is claimed.
- [ ] Numerical targets are evaluated as frozen, including inclusive R/guard lower bounds and strict primary CI>0.
- [ ] Actual whole-index sizes, model projection and allocated-disk usage are not conflated.
- [ ] Four resource observations reuse the E/F adapters/corpora and exclude compilation/query timing.
- [ ] Unfavorable evidence remains immutable; no rerun, pruning, target change or outcome-driven selection.
- [ ] All production/framework/tests/dependencies/workflows and historical artifacts are unchanged.
- [ ] General QA is NOT RUN under authorization, never falsely PASS.
- [ ] Maintainer explicitly assesses writer tradeoffs and the remote-compaction residual before promotion.
- [ ] No merge, automatic B1 start or broader v0.1-perf DONE claim.

Remaining scientific limits even after favorable A6:

- Paired warm effects apply to these sources, corpus, explicit sort/K lanes, compiler and host.
- The R result isolates the complete A5 change; it does not isolate compact framing from the other A5 implementation changes.
- C measures the consolidated A1–A3+A5 change; it cannot attribute gain to each stage.
- Smaller indexes do not by themselves prove lower query latency, lower query RSS, faster startup or lower writer CPU.
- Resource observations are descriptive process-level samples, not statistically qualified write benchmarking.
- Remote qualification is real correctness evidence for its stated path, not a RustFS latency/storage-performance campaign.
- Remote compaction publication requires an explicit future disposition.

## 18. Final coding-agent instruction

Execute this design exactly and continuously. Reuse accepted production code and existing benchmark machinery. Treat a negative result as evidence to preserve. Do not respond to an unexpected condition by designing a fix, changing an oracle, running another acquisition, introducing QA delays or broadening the claim.

When work is blocked, identify the exact matrix row and affected gate, preserve what happened, finish independent authorized tasks, and provide the smallest requested amendment. When the prescribed work is complete, deliver the report and draft PR with the maintainer's acceptance still open.

## 19. Authoring-guide applicability record

This plan implements the guide's fresh-main inspection, scope reconciliation, source-grounded APIs, explicit invariants, boundary/state analysis, real production-path qualification, independent oracles, ownership/immutability, failure taxonomy, continuous-execution rule, exact commands, file scope, decision matrix, acceptance ledger, reviewer checklist and PR description.

Normal guide sections17/18/19/28/40 requirements for baseline/regression suites, workspace coverage and broad QA are overridden only to the extent explicitly directed by the user. They are represented as NOT RUN — USER-AUTHORIZED STABLE-MAIN EXCEPTION. A6 feature-specific measurements/compatibility/oracles are separately specified and are not replaced by reasoning or historical CI.

No new distributed/vector feature, codec, storage provider, publication protocol, framework architecture or dependency is designed by this plan.

## 20. Source references

All links pin planning main unless they intentionally identify historical sources.

- [Authoring guide](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md)
- [Merged A5 PR124](https://github.com/yduchesne/quervant/pull/124)
- [PERF roadmap](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/docs/PERF_OPTIMIZATION_ROADMAP.md)
- [A5 plan, including D39 and §17.3 handoff](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/docs/pr-artifacts/perf-06-a/PERF06A5_DETAILED_PLAN.md)
- [A4 report](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/docs/pr-artifacts/perf-06-a/PERF06A4_EXECUTION_REPORT.md)
- [Permanent benchmarking contract](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/docs/BENCHMARKING.md)
- [Native configuration/CLI](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/benchmarks/quervant_bench/lean/cli.py)
- [Preparation/cache/source identity](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/benchmarks/quervant_bench/lean/preparation.py)
- [Acquisition/corpus/oracle/resource boundaries](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/benchmarks/quervant_bench/lean/runtime.py)
- [Statistical analysis](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/benchmarks/quervant_bench/lean/statistics.py)
- [Real adapter build/query protocol](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/benchmarks/pr15d/adapters/quervant/src/main.rs)
- [Native index API](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/crates/quervant-core/src/index/mod.rs)
- [Remote writer/publication API](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/crates/quervant-core/src/remote/mod.rs)
- [Frozen scalar/formula and I05 schema/oracles](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs)
- [Existing real-provider topology](https://github.com/yduchesne/quervant/blob/3bb232f868cb556ce9b4273d902164c65416af0f/.github/workflows/ci.yml)

## 21. Extracting the fixed support files

Appendices A–D are authoritative source, not illustrative pseudocode. Copy each fenced file body exactly to its stated support path. The extraction recipe after the appendices writes only those four paths, refuses differing existing contents and prints digests for the source ledger. The coding agent must not redesign the helpers.


## Appendix source identities

These hashes bind the supplied source bodies; execution must preserve them.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| a6_compatibility.rs | 22,842 | 927c4d09759c5f29cd35005e8079f77b25028bcd349ea66744b1054130e3b5fc |
| verify_a6_results.py | 12,025 | 8564a68d1a46e99df3b008a69e0dadcadc053993f67751d1a118d2d2ae5964b0 |
| measure_a6_writer.py | 9,944 | 32aabfcdb9b485307a96e056e934d31d523652458a9ee9072e01286a0ce41194 |
| run_a6_once.py | 8,445 | 4fe15fcc3e79dd5329af36f8038bae549e38bd9eb1f65d86667301dee253110c |

## Appendix A — Fixed compatibility qualification source

Destination: docs/pr-artifacts/perf-06-a/a6/support/a6_compatibility.rs.

<!-- A6-FILE: a6_compatibility.rs -->
~~~rust
//! Fixed PERF-06-A6 compatibility qualification workload, not a test-suite target.
//! Compile this identical example against the pinned E and F revisions.
//! No timing result emitted here is used for performance acceptance.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory};
use sha2::{Digest, Sha256};

const E: u16 = 0x000E;
const F: u16 = 0x000F;
type Scores = BTreeMap<String, u64>;
type Maps = [Scores; 3];

fn schema() -> Schema {
    let keyword = |name: &str, columnar| FieldDefinition::new(
        name, FieldType::Keyword, Cardinality::Single,
        FieldOptions::new(true, true, columnar),
    );
    Schema::new(vec![
        keyword("grp", false),
        keyword("doc_id", true),
        FieldDefinition::new("n", FieldType::I64, Cardinality::Single,
            FieldOptions::new(false, true, true)),
        FieldDefinition::new("body", FieldType::Text, Cardinality::Single,
            FieldOptions::indexed_stored()).with_analyzer("standard_folded"),
    ], None).expect("fixed schema")
}

fn registry() -> AnalyzerRegistry { AnalyzerRegistry::builtin() }
fn key(i: usize) -> String { format!("k{i:05}") }
fn doc_id(i: usize) -> String { format!("d{i:05}") }

fn document(i: usize) -> Document {
    assert!(i < 130);
    let alpha = i % 4 + 1;
    let filler = i % 5;
    let body = std::iter::repeat_n("alpha", alpha)
        .chain(std::iter::repeat_n("zeta", filler)).collect::<Vec<_>>().join(" ");
    let mut d = Document::new(DocumentKey::new(key(i)).expect("key"));
    for (name, value) in [
        ("grp", FieldValue::Keyword("common".to_owned())),
        ("doc_id", FieldValue::Keyword(doc_id(i))),
        ("n", FieldValue::I64((i % 7) as i64)),
        ("body", FieldValue::Text(body)),
    ] {
        d.insert(name, FieldValues::Single(value)).expect("field");
    }
    d
}

fn term(value: &str) -> Query {
    Query::Term { field: "body".to_owned(), value: FieldValue::Text(value.to_owned()) }
}
fn ascending() -> Sort {
    Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)])
}
fn search(snapshot: &ReaderSnapshot, query: Query, k: usize, sort: Sort) -> UnifiedResponse {
    let mut request = UnifiedRequest::new(query, TopK::new(k).expect("top k"));
    request.sort = sort;
    request.projection = Projection::Fields(vec!["doc_id".to_owned(), "n".to_owned()]);
    let s = schema();
    let r = registry();
    UnifiedSearcher::new(snapshot, &s, &r, SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new()).expect("search")
}
fn keys(response: &UnifiedResponse) -> Vec<String> {
    response.hits.iter().map(|h| h.key.as_str().to_owned()).collect()
}
fn bits(response: &UnifiedResponse) -> Scores {
    response.hits.iter().map(|h| {
        (h.key.as_str().to_owned(), h.score.expect("scored lexical hit").to_bits())
    }).collect()
}

// Verbatim scalar operation order from the frozen pre-A1 score oracle.
fn scalar(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> f64 {
    let tf = tf as f64;
    let df = df as f64;
    let n = n as f64;
    let dl = dl as f64;
    let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
    let denominator = tf + 1.2 * (1.0 - 0.75 + 0.75 * dl / avgdl);
    idf * (tf * (1.2 + 1.0)) / denominator
}

fn emit_query(label: &str, name: &str, response: &UnifiedResponse) {
    // Labels/names and keys are fixed ASCII generated by this program.
    let score_bits: Vec<Option<u64>> = response.hits.iter()
        .map(|h| h.score.map(f64::to_bits)).collect();
    let values: Vec<String> = score_bits.into_iter()
        .map(|v| v.map_or_else(|| "null".to_owned(), |v| v.to_string())).collect();
    println!("{{\"schema\":\"perf06-a6-compatibility-v1\",\"state\":\"{label}\",\"query\":\"{name}\",\"total_hits\":{},\"keys\":{:?},\"score_bits\":[{}]}}",
        response.total_hits, keys(response), values.join(","));
}

fn verify_queries(snapshot: &ReaderSnapshot, n: usize, label: &str) -> Maps {
    assert!(n == 129 || n == 130);
    assert_eq!(snapshot.document_count(), n as u64);
    let all: Vec<String> = (0..n).map(key).collect();
    let phrase_keys: Vec<String> = (0..n).filter(|i| i % 4 != 0).map(key).collect();
    let zeta_keys: Vec<String> = (0..n).filter(|i| i % 5 != 0).map(key).collect();
    let alpha_total: usize = (0..n).map(|i| i % 4 + 1).sum();
    let filler_total: usize = (0..n).map(|i| i % 5).sum();
    let expected_stats = if n == 129 { (321, 256, 96, 103) } else { (323, 260, 97, 104) };
    assert_eq!((alpha_total, filler_total, phrase_keys.len(), zeta_keys.len()), expected_stats);
    let avgdl = (alpha_total + filler_total) as f64 / n as f64;
    let expected: Scores = (0..n).map(|i| {
        let tf = (i % 4 + 1) as u64;
        let dl = tf + (i % 5) as u64;
        (key(i), scalar(tf, n as u64, n as u64, dl, avgdl).to_bits())
    }).collect();
    let mut relevance: Vec<String> = expected.keys().cloned().collect();
    relevance.sort_by(|a, b| f64::from_bits(expected[b]).total_cmp(&f64::from_bits(expected[a]))
        .then_with(|| a.cmp(b)));

    let check = |name: &str, response: &UnifiedResponse, wanted: &[String], total: usize| {
        assert_eq!(response.total_hits, total as u64, "{label}/{name} total");
        assert_eq!(response.hits.len(), wanted.len(), "{label}/{name} count");
        assert_eq!(keys(response), wanted, "{label}/{name} keys/order/multiplicity");
        emit_query(label, name, response);
    };
    let match_all = search(snapshot, Query::MatchAll, 300, ascending());
    check("match_all", &match_all, &all, n);
    let alpha = search(snapshot, term("alpha"), 300, ascending());
    check("alpha_full", &alpha, &all, n);
    assert_eq!(bits(&alpha), expected);
    let phrase = search(snapshot, Query::Phrase {
        field: "body".to_owned(), terms: vec!["alpha".to_owned(), "alpha".to_owned()],
    }, 300, ascending());
    check("phrase", &phrase, &phrase_keys, phrase_keys.len());
    let zeta = search(snapshot, term("zeta"), 300, ascending());
    check("zeta", &zeta, &zeta_keys, zeta_keys.len());
    let generic = search(snapshot, Query::And(vec![term("alpha")]), 300, ascending());
    check("generic_alpha", &generic, &all, n);
    assert_eq!(bits(&generic), expected);
    for k in [10usize, 100] {
        for (sort, wanted, name) in [
            (ascending(), &all[..k], format!("alpha_ascending_k{k}")),
            (Sort::default(), &relevance[..k], format!("alpha_relevance_k{k}")),
        ] {
            let page = search(snapshot, term("alpha"), k, sort);
            check(&name, &page, wanted, n);
            let observed = bits(&page);
            for key in wanted { assert_eq!(observed[key], expected[key]); }
        }
    }
    [bits(&alpha), bits(&phrase), bits(&zeta)]
}

fn marker(reader: &quervant_core::segment::SegmentReader, field: &str, term: &str) -> (u8, u64) {
    use quervant_core::segment::{SectionKind, SegmentLimits, parse_container};
    let field_id = reader.schema().field_id(field).expect("field");
    let entry = reader.dictionary().expect("dictionary").lookup(field_id, term).expect("term");
    let container = parse_container(reader.bytes(), &SegmentLimits::default()).expect("container");
    let body = container.body(SectionKind::Postings).expect("postings");
    (body[entry.postings_offset as usize], entry.doc_freq)
}

fn verify_format(snapshot: &ReaderSnapshot, generation: u64, label: &str) {
    assert_eq!(snapshot.generation(), Some(generation));
    assert_eq!(snapshot.segment_count(), if generation == 2 { 2 } else { 1 });
    let mut families = (0, 0);
    for i in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(i).expect("segment");
        let reader = guard.reader();
        let required = reader.required_features();
        let e = required.contains(&(E, 1));
        let f = required.contains(&(F, 1));
        assert!(e ^ f, "exactly one required postings family");
        assert!(reader.field_norms().is_some());
        if e {
            families.0 += 1;
            assert!(generation == 1 || generation == 2);
            assert_eq!(marker(reader, "body", "alpha"), (3, 129));
            assert_eq!(marker(reader, "body", "zeta"), (3, 103));
            assert_eq!(marker(reader, "doc_id", "d00000"), (3, 1));
        } else {
            families.1 += 1;
            if generation == 2 {
                assert_eq!(marker(reader, "body", "alpha"), (5, 1));
                assert_eq!(marker(reader, "body", "zeta"), (5, 1));
                assert_eq!(marker(reader, "grp", "common"), (5, 1));
                assert_eq!(marker(reader, "doc_id", "d00129"), (5, 1));
            } else {
                assert_eq!(generation, 3);
                assert_eq!(marker(reader, "body", "alpha"), (3, 130));
                assert_eq!(marker(reader, "grp", "common"), (3, 130));
                assert_eq!(marker(reader, "body", "zeta"), (7, 104));
                assert_eq!(marker(reader, "doc_id", "d00000"), (5, 1));
                assert_eq!(marker(reader, "doc_id", "d00129"), (5, 1));
            }
        }
    }
    assert_eq!(families, match generation { 1 => (1, 0), 2 => (1, 1), 3 => (0, 1), _ => panic!("generation") });
    println!("{{\"schema\":\"perf06-a6-compatibility-v1\",\"state\":\"{label}\",\"generation\":{generation},\"documents\":{},\"segments\":{},\"e_segments\":{},\"f_segments\":{}}}",
        snapshot.document_count(), snapshot.segment_count(), families.0, families.1);
}

fn fresh_directory(path: &Path) {
    assert!(!path.exists(), "qualification output must not exist: {}", path.display());
    fs::create_dir_all(path).expect("create qualification directory");
}
fn open_native(path: &Path) -> Index {
    let dir: Arc<dyn Directory> = Arc::new(FsDirectory::open(path).expect("fs directory"));
    Index::open_existing(dir, schema(), registry()).expect("native reopen")
}
fn digest(bytes: &[u8]) -> String { format!("{:x}", Sha256::digest(bytes)) }
fn immutable_files(root: &Path) -> BTreeMap<PathBuf, (u64, String)> {
    fn walk(root: &Path, dir: &Path, found: &mut BTreeMap<PathBuf, (u64, String)>) {
        for entry in fs::read_dir(dir).expect("inventory") {
            let entry = entry.expect("entry");
            let path = entry.path();
            let kind = entry.file_type().expect("file type");
            assert!(!kind.is_symlink(), "no qualification symlinks");
            if kind.is_dir() { walk(root, &path, found); }
            else if kind.is_file() {
                let rel = path.strip_prefix(root).expect("relative").to_path_buf();
                if rel == Path::new("index/CURRENT") || rel == Path::new("index/WRITER_LOCK") { continue; }
                let bytes = fs::read(&path).expect("immutable object");
                found.insert(rel, (bytes.len() as u64, digest(&bytes)));
            }
        }
    }
    let mut result = BTreeMap::new();
    walk(root, root, &mut result);
    assert!(!result.is_empty());
    result
}
fn verify_immutable(root: &Path, before: &BTreeMap<PathBuf, (u64, String)>) {
    for (rel, expected) in before {
        let bytes = fs::read(root.join(rel)).expect("old immutable object retained");
        assert_eq!(&(bytes.len() as u64, digest(&bytes)), expected);
    }
}

fn create_e(root: &Path) {
    fresh_directory(root);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(root).expect("fs directory"));
    let index = Index::create(directory, schema(), registry()).expect("create E");
    let mut writer = index.writer().expect("E writer");
    for i in 0..129 { writer.insert(document(i)).expect("E insert"); }
    let outcome = writer.commit().expect("E commit");
    assert_eq!(outcome.generation, 1);
    assert!(!outcome.no_op);
    writer.close().expect("close E");
    drop(index);
    let reopened = open_native(root);
    let snapshot = reopened.snapshot();
    verify_format(&snapshot, 1, "native_e_g1");
    verify_queries(&snapshot, 129, "native_e_g1");
}

fn advance_f(root: &Path) {
    let index1 = open_native(root);
    let pit1 = index1.pin().expect("pin generation 1");
    verify_format(pit1.snapshot(), 1, "native_f_reads_e_g1");
    let g1 = verify_queries(pit1.snapshot(), 129, "native_f_reads_e_g1");
    let original = immutable_files(root);
    let mut writer = index1.writer().expect("F append writer");
    writer.insert(document(129)).expect("F insert");
    let outcome = writer.commit().expect("F append commit");
    assert_eq!(outcome.generation, 2);
    assert!(!outcome.no_op);
    writer.close().expect("close append writer");
    drop(index1);
    let index2 = open_native(root);
    let pit2 = index2.pin().expect("pin generation 2");
    verify_format(pit2.snapshot(), 2, "native_mixed_g2");
    let g2 = verify_queries(pit2.snapshot(), 130, "native_mixed_g2");
    let mixed = immutable_files(root);
    let mut writer = index2.writer().expect("F compaction writer");
    let outcome = writer.compact().expect("native compact");
    assert_eq!(outcome.generation, 3);
    assert_eq!(outcome.documents, 130);
    assert_eq!(outcome.segments_merged, 2);
    assert!(!outcome.no_op);
    writer.close().expect("close compaction writer");
    drop(index2);
    let index3 = open_native(root);
    let snapshot3 = index3.snapshot();
    verify_format(&snapshot3, 3, "native_compacted_g3");
    assert_eq!(verify_queries(&snapshot3, 130, "native_compacted_g3"), g2);
    assert_eq!(verify_queries(pit1.snapshot(), 129, "native_held_g1"), g1);
    assert_eq!(verify_queries(pit2.snapshot(), 130, "native_held_g2"), g2);
    verify_immutable(root, &original);
    verify_immutable(root, &mixed);
}

fn verify_f(root: &Path) {
    let index = open_native(root);
    let snapshot = index.snapshot();
    verify_format(&snapshot, 3, "native_fresh_process_g3");
    verify_queries(&snapshot, 130, "native_fresh_process_g3");
}

#[cfg(feature = "s3")]
mod remote {
    use super::*;
    use quervant_core::index::{CURRENT_KEY, CURRENT_MAX_BYTES, CurrentPointer, IndexLimits};
    use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix};
    use quervant_objectstore::{ObjectStore, S3Config, S3ObjectStore, TransferLimits};

    fn store() -> Arc<S3ObjectStore> {
        let required = |name: &str| {
            let v = std::env::var(name).expect("required existing RustFS environment");
            assert!(!v.trim().is_empty(), "nonempty environment required");
            v
        };
        let endpoint = required("QUERVANT_RUSTFS_ENDPOINT");
        assert_eq!(endpoint, "http://127.0.0.1:19000", "frozen task-local endpoint");
        let region = required("QUERVANT_RUSTFS_REGION");
        assert_eq!(region, "us-east-1");
        let bucket = required("QUERVANT_RUSTFS_BUCKET");
        assert_eq!(bucket, "quervant-perf06-a6");
        Arc::new(S3ObjectStore::new(S3Config::rustfs(endpoint, region,
            bucket, required("QUERVANT_RUSTFS_ACCESS_KEY"),
            required("QUERVANT_RUSTFS_SECRET_KEY"))).expect("real S3 adapter"))
    }
    fn config(root: &Path, prefix: &str, phase: &str) -> RemoteConfig {
        let workspace = root.join(phase);
        fresh_directory(&workspace);
        RemoteConfig::new(RemoteKeyPrefix::parse(prefix).expect("prefix"), workspace)
    }
    async fn fetch(store: &S3ObjectStore, prefix: &RemoteKeyPrefix, logical: &str, limit: u64) -> Vec<u8> {
        store.get(&prefix.object_key(logical).expect("object key"), None,
            &TransferLimits::new(limit)).await.expect("real remote read")
    }
    async fn pointer(store: &S3ObjectStore, prefix: &RemoteKeyPrefix, generation: u64) -> CurrentPointer {
        let bytes = fetch(store, prefix, CURRENT_KEY, CURRENT_MAX_BYTES as u64).await;
        let pointer = CurrentPointer::parse(&bytes).expect("remote CURRENT");
        assert_eq!(pointer.generation(), generation);
        pointer
    }
    pub async fn run(mode: &str, root: &Path, prefix_str: &str) {
        fresh_directory(root);
        let store = store();
        let prefix = RemoteKeyPrefix::parse(prefix_str).expect("prefix");
        if mode == "remote-create-e" {
            store.create_bucket_if_absent().await.expect("create task-local qualification bucket");
            let cfg = config(root, prefix_str, "create");
            let index = RemoteIndex::create(Arc::clone(&store), cfg, schema(), registry(), IndexLimits::default())
                .await.expect("create genuine remote E");
            let mut writer = index.writer().await.expect("remote E writer");
            for i in 0..129 { writer.insert(document(i)).expect("remote E insert"); }
            let outcome = writer.commit().await.expect("remote E durable commit");
            assert_eq!(outcome.generation, 1);
            assert!(!outcome.no_op);
            writer.close().expect("remote E close");
            drop(index);
            pointer(&store, &prefix, 1).await;
            let reopened = RemoteIndex::open_existing(Arc::clone(&store), config(root, prefix_str, "cold-g1"),
                schema(), registry(), IndexLimits::default()).await.expect("cold remote E open");
            let snapshot = reopened.snapshot();
            verify_format(&snapshot, 1, "remote_e_g1");
            verify_queries(&snapshot, 129, "remote_e_g1");
        } else if mode == "remote-append-f" {
            let index1 = RemoteIndex::open_existing(Arc::clone(&store), config(root, prefix_str, "cold-g1"),
                schema(), registry(), IndexLimits::default()).await.expect("F cold reads remote E");
            let pit1 = index1.pin().expect("remote generation-1 PIT");
            verify_format(pit1.snapshot(), 1, "remote_f_reads_e_g1");
            let g1 = verify_queries(pit1.snapshot(), 129, "remote_f_reads_e_g1");
            let p1 = pointer(&store, &prefix, 1).await;
            let manifest_key = p1.manifest_key().as_str().to_owned();
            let old_manifest = fetch(&store, &prefix, &manifest_key, p1.manifest_length()).await;
            let decoded = quervant_core::segment::Manifest::decode(
                &old_manifest, &quervant_core::segment::SegmentLimits::default()).expect("E manifest");
            let old_state = decoded.mutation_state.as_ref().expect("E mutation state");
            let state_key = old_state.object_key.clone();
            let state_length = old_state.content_length;
            let old_state_bytes = fetch(&store, &prefix, &state_key, state_length).await;
            let old_segment = pit1.snapshot().segments()[0].meta();
            let old_key = old_segment.object_key().to_owned();
            let old_length = old_segment.descriptor().length;
            let old_bytes = fetch(&store, &prefix, &old_key, old_length).await;
            let mut writer = index1.writer().await.expect("remote F append writer");
            writer.insert(document(129)).expect("remote F insert");
            let outcome = writer.commit().await.expect("remote F durable append");
            assert_eq!(outcome.generation, 2);
            assert!(!outcome.no_op);
            writer.close().expect("remote F close");
            drop(index1);
            pointer(&store, &prefix, 2).await;
            let index2 = RemoteIndex::open_existing(Arc::clone(&store), config(root, prefix_str, "cold-g2"),
                schema(), registry(), IndexLimits::default()).await.expect("cold mixed remote generation");
            let pit2 = index2.pin().expect("remote generation-2 PIT");
            verify_format(pit2.snapshot(), 2, "remote_mixed_g2");
            let g2 = verify_queries(pit2.snapshot(), 130, "remote_mixed_g2");
            // Both PITs must outlive their owning RemoteIndex handles. The final
            // remote-verify-f invocation owns the separate-process cold reopen.
            drop(index2);
            assert_eq!(verify_queries(pit1.snapshot(), 129, "remote_held_g1"), g1);
            assert_eq!(verify_queries(pit2.snapshot(), 130, "remote_held_g2"), g2);
            assert_eq!(fetch(&store, &prefix, &manifest_key, p1.manifest_length()).await, old_manifest);
            assert_eq!(fetch(&store, &prefix, &old_key, old_length).await, old_bytes);
            assert_eq!(fetch(&store, &prefix, &state_key, state_length).await, old_state_bytes);
        } else {
            assert_eq!(mode, "remote-verify-f");
            pointer(&store, &prefix, 2).await;
            let index = RemoteIndex::open_existing(store, config(root, prefix_str, "cold-g2"),
                schema(), registry(), IndexLimits::default()).await.expect("fresh-process cold mixed open");
            let snapshot = index.snapshot();
            verify_format(&snapshot, 2, "remote_fresh_process_g2");
            verify_queries(&snapshot, 130, "remote_fresh_process_g2");
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    assert!(args.len() == 2 || args.len() == 3, "MODE ROOT [REMOTE_PREFIX]");
    let mode = args[0].as_str();
    let root = Path::new(&args[1]);
    match mode {
        "create-e" => { assert_eq!(args.len(), 2); create_e(root); }
        "advance-f" => { assert_eq!(args.len(), 2); advance_f(root); }
        "verify-f" => { assert_eq!(args.len(), 2); verify_f(root); }
        "remote-create-e" | "remote-append-f" | "remote-verify-f" => {
            assert_eq!(args.len(), 3);
            #[cfg(feature = "s3")]
            {
                let owned = args.clone();
                std::thread::Builder::new().name("perf06-a6-remote".to_owned())
                    .stack_size(32 * 1024 * 1024).spawn(move || {
                        let runtime = tokio::runtime::Builder::new_current_thread()
                            .enable_all().build().expect("runtime");
                        runtime.block_on(remote::run(&owned[0], Path::new(&owned[1]), &owned[2]));
                    }).expect("remote thread").join().expect("remote qualification");
            }
            #[cfg(not(feature = "s3"))]
            panic!("remote mode requires the explicit s3 qualification build");
        }
        _ => panic!("unknown mode"),
    }
    println!("{{\"schema\":\"perf06-a6-compatibility-v1\",\"mode\":\"{mode}\",\"status\":\"PASS\"}}");
}
~~~
<!-- END A6-FILE -->

## Appendix B — Fixed read-only result verifier

Destination: docs/pr-artifacts/perf-06-a/a6/support/verify_a6_results.py.

<!-- A6-FILE: verify_a6_results.py -->
~~~python
#!/usr/bin/env python3
"""A6 read-only artifact verification; no query, build, test, or artifact writes.

Run from repository root with the same environment as acquisition:
PYTHONPATH=benchmarks python /path/to/verify_a6_results.py \
  RUNNER_SHA SCRATCH_ROOT RETENTION_CONFIG RETENTION_RESULT \
  CUMULATIVE_CONFIG CUMULATIVE_RESULT

Only pass COMPLETE results here. An incomplete result is retained and reported
without attempting to manufacture a complete analysis.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean.configuration import lanes_for, validate_configuration
from quervant_bench.lean.statistics import analyze
from quervant_bench.lean import preparation

A0 = "2a74017958c8ac61948f931e8745bf8134827025"
E = "b70f624fffe0329def62701b61e997c4e303e167"
F = "3bb232f868cb556ce9b4273d902164c65416af0f"
POLICY = {
    "blocks": 12, "slots_per_arm": 2, "warmups": 5, "samples": 20,
    "bootstrap_resamples": 10000, "seed": 20261122, "min_blocks": 4,
    "min_gain_percent": 0, "max_regression_percent": 0,
    "max_aa_gain_percent": 15, "exclude_blocks": {}, "control_arms": [],
    "readiness": {
        "intervals": 4, "interval_ms": 250,
        "max_busy_percent": 25, "max_steal_percent": 2,
    },
}
PRIMARY = {
    "100000/medium/k10/warm", "100000/medium/k100/warm",
    "100000/common/k10/warm", "100000/common/k100/warm",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def verify_one(
    config_path: Path,
    result_path: Path,
    *,
    baseline: str,
    name: str,
    runner_sha: str,
    scratch_root: Path,
) -> dict:
    config_before = hashlib.sha256(config_path.read_bytes()).hexdigest()
    result_before = hashlib.sha256(result_path.read_bytes()).hexdigest()
    config = load_configuration(config_path)
    validate_configuration(config)
    result = load_result(result_path)
    require(config["family"] == "perf-06", "wrong family")
    require(config["name"] == name, "wrong campaign name")
    require(config["workload"] == {
        "id": "pr15d-exact-keyword-v1", "sizes": [10000, 100000],
        "classes": ["absent", "rare", "medium", "common"],
        "top_k": [10, 100], "regimes": ["warm"],
        "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
        "timed_operation": "exact-term-search-plus-topk-projection",
    }, "frozen workload changed")
    require(config["policy"] == POLICY, "frozen policy changed")
    require(config["arms"] == {
        "A": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": baseline},
        "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": F},
    }, "arm sources or modes changed")
    require(config["build"] == {
        "release": True, "locked": True, "baseline_ref": None,
        "prefilter_profile": "P2", "quervant_feature": None,
    }, "build settings changed")
    require(config["baseline"] == "A", "wrong baseline")
    require(config["control"] == {
        "enabled": True, "baseline": "AA", "equivalent": "AA2",
    }, "control roles changed")
    expected_lanes = lanes_for(config)
    require(len(expected_lanes) == 16, "wrong lane count")
    require(result["schema"] == "benchmark-result-v1", "wrong result schema")
    require(result["family"] == "perf-06", "wrong result family")
    require(result["configuration"] == config, "embedded configuration changed")
    require(result["configuration_id"] == config["configuration_id"], "wrong configuration UUID")
    require(result["configuration_file"] == config_path.name, "wrong configuration filename")
    require(result["configuration_name"] == name, "wrong result campaign")
    require(result_path.parent.resolve() == (config_path.parent.parent / "results").resolve(),
            "result outside canonical sibling directory")
    require(result["sequence"] == 1, "unexpected additional acquisition sequence")
    require(result["status"] == "COMPLETE", "result is not COMPLETE")
    require(result["errors"] == [], "result has errors")
    require(result["lanes"] == expected_lanes, "lane descriptors changed")
    context = result["context"]
    require(context["source_revision"] == runner_sha, "unexpected runner source")
    require(context["build"]["arm_source_revisions"] == {"A": baseline, "B": F},
            "wrong compiled arm sources")
    require(context["build"]["compiler_options"] == "cargo --release --locked",
            "wrong compiler options")
    require(context["build"]["quervant_strategy_feature_enabled"] is False,
            "experiment feature unexpectedly enabled")
    require(context["controller_cpu"] != context["adapter_cpu"], "CPU affinity collided")
    for cpu_key in ("controller_cpu", "adapter_cpu"):
        cpu = context[cpu_key]
        require(isinstance(cpu, int) and not isinstance(cpu, bool) and cpu >= 0,
                "missing CPU affinity identity")
    prep = context["preparation"]
    require(prep["verified_oracles"] is True, "preparation oracles unverified")
    require(prep["cache_status"] in ("BUILT", "HIT"), "unknown preparation state")
    require(prep["index_metrics_provenance"] == "preparation stage (not the current query window)",
            "index metric timing scope changed")
    require(re.fullmatch(r"[0-9a-f]{64}", prep["cache_key"]) is not None, "invalid cache key")
    controls = result["controls"]
    for key in ("readiness_index_pre", "readiness_pre", "readiness_treatment", "readiness_post"):
        require(controls[key]["status"] == "clear", f"{key} did not pass")
        require(controls[key]["cpu"] == context["adapter_cpu"], f"{key} CPU differs")
    require(controls["readiness_index_source"] == "preparation stage",
            "index readiness provenance changed")
    lane_ids = {lane["id"] for lane in expected_lanes}
    for label, rows, arms in (
        ("control", controls["raw_samples"], {"AA", "AA2"}),
        ("treatment", result["raw_samples"], {"A", "B"}),
    ):
        require(len(rows) == 768, f"{label}: wrong record count")
        require(Counter(row["lane_id"] for row in rows) == Counter({lane: 48 for lane in lane_ids}),
                f"{label}: wrong per-lane record count")
        require(Counter(row["arm_id"] for row in rows) == Counter({arm: 384 for arm in arms}),
                f"{label}: wrong arm record count")
        for row in rows:
            require(row["warmups"] == 5 and row["oracle_ok"] is True,
                    f"{label}: invalid warmups or oracle")
            require(row["strategy_marker"] is None, f"{label}: unexpected strategy override")
            require(len(row["samples_ns"]) == 20 and
                    all(positive_integer(x) for x in row["samples_ns"]),
                    f"{label}: missing or invalid timed samples")
    aa_policy = dict(config["policy"], control_arms=["AA2"])
    control_replay = analyze(
        controls["raw_samples"], arms=["AA", "AA2"], baseline="AA",
        lanes=result["lanes"], policy=aa_policy,
    )
    treatment_replay = analyze(
        result["raw_samples"], arms=["A", "B"], baseline="A",
        lanes=result["lanes"], policy=config["policy"],
    )
    require(control_replay == controls["analysis"], "A/A analysis differs on replay")
    require(treatment_replay == result["analysis"], "A/B analysis differs on replay")
    for lane in lane_ids:
        require(control_replay["lanes"][lane]["comparisons"]["AA2"]["status"] == "PASS",
                "A/A lane did not pass")
        for phase in (control_replay, treatment_replay):
            row = phase["lanes"][lane]
            require(row["raw_blocks"] == 12 and row["retained_blocks"] == 12
                    and row["excluded_blocks"] == [], "missing/pruned blocks")
        comp = treatment_replay["lanes"][lane]["comparisons"]["B"]
        require(comp["status"] in ("IMPROVED", "REGRESSED", "INCONCLUSIVE"),
                "uncomputable comparison")
        require(comp["bootstrap_resamples"] == 10000 and
                len(comp["retained_paired_ratios"]) == 12, "wrong bootstrap inputs")
    cache_dir = scratch_root.resolve() / "prepared" / prep["cache_key"]
    # Read-only native cache verification; no stage(), queries, or rebuilds.
    identity = preparation.source_identity(Path.cwd(), config)
    cached = preparation._load_cache(cache_dir, identity, config)
    require(cached is not None, "prepared input identity/fingerprint no longer verifies")
    require(cached["index_metrics"] == result["index_metrics"], "index metrics differ")
    require(cached["build_info"] == context["build"], "cached build identity differs")
    require(cached["prepared_utc"] == prep["prepared_utc"], "preparation timestamp differs")
    for arm in ("A", "B"):
        for n in ("10000", "100000"):
            metrics = result["index_metrics"][arm][n]
            for key in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"):
                require(positive_integer(metrics[key]), "invalid index metric")
            require(metrics["segment_count"] == 1, "unexpected benchmark segment count")
    require(hashlib.sha256(config_path.read_bytes()).hexdigest() == config_before,
            "configuration changed during verification")
    require(hashlib.sha256(result_path.read_bytes()).hexdigest() == result_before,
            "result changed during verification")
    return result


def classify(result: dict, *, retention: bool) -> list[dict]:
    decisions = []
    for lane, row in result["analysis"]["lanes"].items():
        comp = row["comparisons"]["B"]
        gain = comp["gain_percent"]
        lower, upper = comp["gain_ci_95_percent"]
        if retention:
            category = "A5_RETENTION"
            passed = gain >= -2.0 and lower >= -5.0
        elif lane in PRIMARY:
            category = "CUMULATIVE_PRIMARY"
            passed = comp["status"] == "IMPROVED" and gain >= 5.0 and lower > 0.0
        else:
            category = "CUMULATIVE_GUARD"
            passed = gain >= -10.0 and lower >= -10.0
        decisions.append({
            "lane": lane, "category": category, "gain_percent": gain,
            "gain_ci_95_percent": [lower, upper], "analyzer_status": comp["status"],
            "gate": "MET" if passed else "NOT_MET",
        })
    return decisions


if __name__ == "__main__":
    require(len(sys.argv) == 7, "expected runner SHA, scratch root, and two config/result pairs")
    runner, scratch, rcfg, rres, ccfg, cres = sys.argv[1:]
    require(re.fullmatch(r"[0-9a-f]{40}", runner) is not None, "invalid runner SHA")
    r = verify_one(
        Path(rcfg), Path(rres), baseline=E,
        name="quervant-perf06a6-adaptive-warm", runner_sha=runner, scratch_root=Path(scratch),
    )
    c = verify_one(
        Path(ccfg), Path(cres), baseline=A0,
        name="quervant-perf06a6-cumulative-warm", runner_sha=runner, scratch_root=Path(scratch),
    )
    require(r["configuration_id"] != c["configuration_id"], "campaign UUID reused")
    require(r["run_id"] != c["run_id"], "run UUID reused")
    require(r["context"]["controller_cpu"] == c["context"]["controller_cpu"] and
            r["context"]["adapter_cpu"] == c["context"]["adapter_cpu"], "campaign CPUs differ")
    # Both current-F builds must produce the same complete-index bytes at each size.
    for n in ("10000", "100000"):
        require(r["index_metrics"]["B"][n]["index_bytes"] ==
                c["index_metrics"]["B"][n]["index_bytes"],
                "independently built F index sizes disagree")
    print(json.dumps({
        "verification": "PASS",
        "retention": classify(r, retention=True),
        "cumulative": classify(c, retention=False),
    }, indent=2, sort_keys=True, allow_nan=False))

~~~
<!-- END A6-FILE -->

## Appendix C — Fixed four-case writer-resource collector

Destination: docs/pr-artifacts/perf-06-a/a6/support/measure_a6_writer.py.

<!-- A6-FILE: measure_a6_writer.py -->
~~~python
#!/usr/bin/env python3
"""Four fixed E/F index-build resource observations; no query timing or QA.

Run from repository root, after both paired acquisitions, with the same frozen
environment and LC_ALL=C:
PYTHONPATH=benchmarks python /path/to/measure_a6_writer.py \
  RETENTION_CONFIG RETENTION_RESULT SCRATCH_ROOT NEW_DIAGNOSTIC_DIRECTORY

This program creates four fresh indexes. It reuses the measured E/F release
executables and frozen corpora. It never changes or rebuilds a prepared cache.
Each case executes once. An exception stops the remaining cases and preserves
every file already written. Do not rerun against another output directory.
"""
from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean import preparation, runtime

E = "b70f624fffe0329def62701b61e997c4e303e167"
F = "3bb232f868cb556ce9b4273d902164c65416af0f"
GNU_TIME = Path("/usr/bin/time")
TIME_FORMAT = (
    "user_seconds=%U\nsystem_seconds=%S\nmax_rss_kib=%M\n"
    "elapsed_seconds=%e\nexit_status=%x"
)
CASES = (
    (1, "E", "A", 10000),
    (2, "F", "B", 10000),
    (3, "F", "B", 100000),
    (4, "E", "A", 100000),
)
FIELDS = (
    "order", "label", "source_revision", "documents", "adapter_cpu",
    "adapter_sha256", "index_ns", "commit_ns", "reopen_ns", "index_bytes",
    "segment_count", "user_seconds", "system_seconds", "cpu_seconds",
    "max_rss_kib", "elapsed_seconds", "exit_status", "resource_file",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_resources(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    rows = [line.split("=", 1) for line in text.splitlines()]
    require(len(rows) == 5 and all(len(row) == 2 for row in rows),
            "unexpected GNU time output")
    fields = dict(rows)
    require(len(fields) == 5 and set(fields) == {
        "user_seconds", "system_seconds", "max_rss_kib",
        "elapsed_seconds", "exit_status",
    }, "missing or duplicate resource fields")
    for field in ("user_seconds", "system_seconds", "elapsed_seconds"):
        require(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", fields[field]) is not None,
                "invalid resource duration")
    for field in ("max_rss_kib", "exit_status"):
        require(re.fullmatch(r"[0-9]+", fields[field]) is not None,
                "invalid resource integer")
    user = Decimal(fields["user_seconds"])
    system = Decimal(fields["system_seconds"])
    elapsed = Decimal(fields["elapsed_seconds"])
    rss = int(fields["max_rss_kib"])
    status = int(fields["exit_status"])
    require(user >= 0 and system >= 0 and user + system > 0,
            "CPU observation unavailable or rounded to zero")
    require(elapsed > 0 and rss > 0 and status == 0,
            "invalid resource values or unsuccessful adapter")
    return {
        "user_seconds": str(user), "system_seconds": str(system),
        "cpu_seconds": str(user + system), "max_rss_kib": rss,
        "elapsed_seconds": str(elapsed), "exit_status": status,
    }


def main() -> None:
    require(len(sys.argv) == 5,
            "expected retention config, retention result, scratch root, and new output directory")
    config_path, result_path, scratch_root, output_root = map(Path, sys.argv[1:])
    require(os.environ.get("LC_ALL") == "C", "run with frozen LC_ALL=C")
    require(GNU_TIME.is_file() and os.access(GNU_TIME, os.X_OK),
            "/usr/bin/time unavailable; no substitute is authorized")
    time_identity = subprocess.run(
        [str(GNU_TIME), "--version"], check=True, capture_output=True,
        text=True, timeout=15,
    ).stdout
    require("gnu" in time_identity.lower(), "GNU time identity not established")
    require(not output_root.exists() and not output_root.is_symlink(),
            "diagnostic output already exists; do not repeat resource acquisition")
    require(not scratch_root.is_symlink(), "scratch root must not be a symlink")
    require(not output_root.resolve().is_relative_to(scratch_root.resolve() / "prepared"),
            "resource output must remain outside all prepared caches")
    config_before, result_before = digest(config_path), digest(result_path)
    config = load_configuration(config_path)
    result = load_result(result_path)
    require(config["name"] == "quervant-perf06a6-adaptive-warm"
            and config["family"] == "perf-06", "wrong source campaign")
    require(result["status"] == "COMPLETE" and result["errors"] == [],
            "resource acquisition requires the complete retained campaign")
    require(result["configuration"] == config, "configuration mismatch")
    require(config["arms"]["A"]["revision"] == E
            and config["arms"]["B"]["revision"] == F, "wrong E/F source pins")
    require(result["context"]["build"]["arm_source_revisions"] == {"A": E, "B": F},
            "wrong compiled sources")
    cpu = result["context"]["adapter_cpu"]
    require(isinstance(cpu, int) and not isinstance(cpu, bool) and cpu >= 0,
            "adapter CPU unavailable")
    key = result["context"]["preparation"]["cache_key"]
    require(re.fullmatch(r"[0-9a-f]{64}", key) is not None, "invalid cache key")
    cache_dir = scratch_root.resolve() / "prepared" / key
    identity = preparation.source_identity(Path.cwd(), config)
    cached = preparation._load_cache(cache_dir, identity, config)
    require(cached is not None, "prepared cache identity or fingerprints failed")
    require(cached["index_metrics"] == result["index_metrics"],
            "prepared metrics no longer match acquisition")
    programs, _indexes = preparation._existing_inputs(cache_dir, config)
    for arm in ("A", "B"):
        require(len(programs[arm]) == 1, "unexpected adapter command shape")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(exist_ok=False)
    metadata = {
        "scope": "whole index-build adapter process; includes corpus parse, insert, commit, close, reopen and size enumeration",
        "interpretation": "single descriptive observation per source and corpus; no confidence interval or performance acceptance gate",
        "retention_configuration_id": config["configuration_id"],
        "retention_run_id": result["run_id"],
        "configuration_sha256": config_before,
        "result_sha256": result_before,
        "cache_key": key,
        "gnu_time_identity": time_identity.strip(),
        "adapter_cpu": cpu,
        "cases": [{"order": order, "label": label, "arm": arm, "documents": n}
                  for order, label, arm, n in CASES],
    }
    (output_root / "scope.txt").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    with (output_root / "writer.tsv").open("x", encoding="utf-8", newline="") as table, \
         (output_root / "raw-times.txt").open("x", encoding="utf-8") as raw:
        writer = csv.DictWriter(table, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        table.flush()
        os.fsync(table.fileno())
        for order, label, arm, n in CASES:
            case_dir = output_root / f"{order:02d}-{label}-n{n}"
            case_dir.mkdir(exist_ok=False)
            resource_path = case_dir / "resources.txt"
            adapter = Path(programs[arm][0])
            adapter_hash = digest(adapter)
            corpus = cache_dir / "corpus" / f"keyword-n{n}.tsv"
            wrapped = [
                str(GNU_TIME), "-o", str(resource_path),
                "-f", TIME_FORMAT, *programs[arm],
            ]
            # The native helper supplies taskset, JSONL build request, timeout,
            # expected document counts, positive timing checks and disk-size check.
            metrics = runtime.build_index(
                wrapped, engine="quervant", corpus_path=corpus,
                target=case_dir / "index", n=n, cpu=cpu,
            )
            resources = parse_resources(resource_path)
            require(metrics["segment_count"] == 1, "unexpected segment count")
            require(metrics["index_bytes"] == result["index_metrics"][arm][str(n)]["index_bytes"],
                    "fresh diagnostic index size differs from the same source's staged index")
            require(digest(adapter) == adapter_hash, "adapter changed during observation")
            row = {
                "order": order, "label": label,
                "source_revision": E if arm == "A" else F,
                "documents": n, "adapter_cpu": cpu, "adapter_sha256": adapter_hash,
                **metrics, **resources,
                "resource_file": str(resource_path.relative_to(output_root)),
            }
            writer.writerow(row)
            table.flush()
            os.fsync(table.fileno())
            raw.write(f"[{order:02d} {label} n={n}]\n")
            raw.write(resource_path.read_text(encoding="utf-8"))
            raw.write("\n")
            raw.flush()
            os.fsync(raw.fileno())
            print(json.dumps({"case": order, "label": label, "documents": n,
                              "status": "RECORDED"}, sort_keys=True), flush=True)
    require(digest(config_path) == config_before and digest(result_path) == result_before,
            "protected campaign artifact changed")
    after = preparation._load_cache(cache_dir, identity, config)
    require(after is not None and after == cached,
            "prepared cache changed during resource observations")
    print("A6_WRITER_DIAGNOSTICS_RECORDED=4", flush=True)


if __name__ == "__main__":
    main()

~~~
<!-- END A6-FILE -->

## Appendix D — Fixed single-invocation guard

Destination: docs/pr-artifacts/perf-06-a/a6/support/run_a6_once.py.

<!-- A6-FILE: run_a6_once.py -->
~~~python
#!/usr/bin/env python3
"""Invoke one frozen A6 campaign at most once, using the unmodified native CLI.

This is an invocation guard and log capture only. It does not measure queries,
change the native framework, retry a run, or replace native result publication.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean.configuration import validate_configuration
from verify_a6_results import A0, E, F, POLICY, classify, require, verify_one

RETENTION = "quervant-perf06a6-adaptive-warm"
CUMULATIVE = "quervant-perf06a6-cumulative-warm"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_exclusive(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    require(len(sys.argv) == 5, "expected repository, scratch, acquisition evidence, configuration")
    repo, scratch, evidence, config_path = map(lambda x: Path(x).resolve(), sys.argv[1:])
    require(Path.cwd().resolve() == repo, "run from the verified controller repository root")
    require(scratch == repo / "target" / "perf06-a6", "unexpected scratch root")
    require(evidence == repo / "docs/pr-artifacts/perf-06-a/a6/acquisition",
            "unexpected acquisition evidence root")
    require(config_path.parent == repo / "benchmarks/studies/perf-06/warm/configurations",
            "configuration outside the approved study")
    require(os.environ.get("RUSTUP_TOOLCHAIN") == "1.98.1", "toolchain not frozen")
    require(os.environ.get("LC_ALL") == "C", "locale not frozen")
    for name in ("QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE"):
        require(name not in os.environ, "forbidden experiment override")
    config = load_configuration(config_path)
    validate_configuration(config)
    name = config["name"]
    require(name in (RETENTION, CUMULATIVE), "unapproved acquisition name")
    baseline = E if name == RETENTION else A0
    require(config["policy"] == POLICY, "frozen policy changed")
    require(config["workload"] == {
        "id": "pr15d-exact-keyword-v1", "sizes": [10000, 100000],
        "classes": ["absent", "rare", "medium", "common"],
        "top_k": [10, 100], "regimes": ["warm"],
        "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
        "timed_operation": "exact-term-search-plus-topk-projection",
    }, "frozen workload changed")
    require(config["arms"] == {
        "A": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": baseline},
        "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned", "revision": F},
    }, "frozen arm sources changed")
    require(config["build"] == {
        "release": True, "locked": True, "baseline_ref": None,
        "prefilter_profile": "P2", "quervant_feature": None,
    }, "frozen build settings changed")
    require(config["baseline"] == "A" and config["control"] == {
        "enabled": True, "baseline": "AA", "equivalent": "AA2",
    }, "frozen arm/control roles changed")
    evidence.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    runner = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    with (scratch / "acquisition.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = evidence / (name + ".started.txt")
        log_path = evidence / (name + ".run.log")
        reference = evidence / (name + ".result-reference.txt")
        require(not marker.exists() and not log_path.exists() and not reference.exists(),
                "campaign evidence already exists; invocation is not repeatable")
        result_dir = config_path.parent.parent / "results"
        require(not list(result_dir.glob(name + "-*.json")), "a result already exists")
        if name == RETENTION:
            require(not (evidence / (CUMULATIVE + ".started.txt")).exists(),
                    "C already has invocation history; do not start R")
        prior_verification = None
        if name == CUMULATIVE:
            prior_marker = evidence / (RETENTION + ".started.txt")
            prior_reference = evidence / (RETENTION + ".result-reference.txt")
            require(prior_marker.is_file() and prior_reference.is_file(),
                    "R has no complete prior invocation record")
            prior = json.loads(prior_marker.read_text(encoding="utf-8"))
            r_config = Path(prior["configuration_path"])
            r_result = Path(prior_reference.read_text(encoding="utf-8").strip())
            require(prior["runner_sha"] == runner, "controller changed between campaigns")
            require(sha(r_config) == prior["configuration_sha256"], "R configuration changed")
            # Mandatory R-only validity/replay before consuming C's invocation.
            # A valid numerical NOT_MET outcome does not stop C.
            r = verify_one(r_config, r_result, baseline=E, name=RETENTION,
                           runner_sha=runner, scratch_root=scratch)
            prior_verification = {
                "result_path": str(r_result), "result_sha256": sha(r_result),
                "configuration_sha256": sha(r_config), "status": "PASS",
                "retention": classify(r, retention=True),
            }
            print(json.dumps({"pre_c_r_verification": "PASS",
                              "retention": classify(r, retention=True)},
                             sort_keys=True, allow_nan=False), flush=True)
        payload = {
            "campaign": name,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "runner_sha": runner,
            "configuration_path": str(config_path),
            "configuration_id": config["configuration_id"],
            "configuration_sha256": sha(config_path),
            "invocation_budget_consumed": True,
            "pre_c_r_verification": prior_verification,
        }
        # Marker is durable before any native acquisition process can start.
        write_exclusive(marker, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        argv = [sys.executable, "-m", "quervant_bench", "run",
                "--config", str(config_path), "--scratch-root", str(scratch)]
        with log_path.open("x", encoding="utf-8") as log:
            log.write("NATIVE_ARGV=" + json.dumps(argv) + "\n")
            log.flush()
            os.fsync(log.fileno())
            done = subprocess.run(argv, cwd=repo, stdout=log, stderr=subprocess.STDOUT,
                                  check=False)
            log.write("\nNATIVE_EXIT=" + str(done.returncode) + "\n")
            log.flush()
            os.fsync(log.fileno())
        require(sha(config_path) == payload["configuration_sha256"],
                "configuration changed during acquisition")
        lines = log_path.read_text(encoding="utf-8").splitlines()
        paths = [line.removeprefix("RESULT_JSON=") for line in lines
                 if line.startswith("RESULT_JSON=")]
        require(len(paths) <= 1, "unexpected multiple result publications")
        if paths:
            result_path = Path(paths[0]).resolve()
            require(result_path.parent == result_dir, "published result outside approved directory")
            result = load_result(result_path)
            require(result["configuration_id"] == config["configuration_id"],
                    "published result has wrong configuration")
            write_exclusive(reference, str(result_path) + "\n")
            print("RESULT_JSON=" + str(result_path), flush=True)
            print("NATIVE_RESULT_STATUS=" + str(result["status"]), flush=True)
        else:
            print("NO_RESULT_REFERENCE_PUBLISHED; started marker remains consumed", flush=True)
        print("NATIVE_EXIT=" + str(done.returncode), flush=True)
        return done.returncode if done.returncode >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
~~~
<!-- END A6-FILE -->

## Appendix E — Exact extraction recipe

Set A6_PLAN to the actual path of this approved Markdown file and run from the
verified repository checkout. The recipe extracts only the four supplied source
bodies, verifies their frozen hashes, and refuses to overwrite differing files.
An identical existing source file is reused on resume.

~~~bash
python3 - "$A6_PLAN" "$A6_SUPPORT" <<'PY'
from pathlib import Path
import hashlib, sys
plan = Path(sys.argv[1]).read_text(encoding="utf-8")
destination = Path(sys.argv[2])
expected = {'a6_compatibility.rs': '927c4d09759c5f29cd35005e8079f77b25028bcd349ea66744b1054130e3b5fc', 'verify_a6_results.py': '8564a68d1a46e99df3b008a69e0dadcadc053993f67751d1a118d2d2ae5964b0', 'measure_a6_writer.py': '32aabfcdb9b485307a96e056e934d31d523652458a9ee9072e01286a0ce41194', 'run_a6_once.py': '4fe15fcc3e79dd5329af36f8038bae549e38bd9eb1f65d86667301dee253110c'}
languages = {
    "a6_compatibility.rs": "rust",
    "verify_a6_results.py": "python",
    "measure_a6_writer.py": "python",
    "run_a6_once.py": "python",
}
destination.mkdir(parents=True, exist_ok=True)
for name, wanted in expected.items():
    marker = f"<!-- A6-FILE: {name} -->\n~~~{languages[name]}\n"
    if plan.count(marker) != 1:
        raise SystemExit(f"STOP: missing/duplicate source block {name}")
    tail = plan.split(marker, 1)[1]
    source = (tail.split("\n~~~\n<!-- END A6-FILE -->", 1)[0] + "\n").encode("utf-8")
    observed = hashlib.sha256(source).hexdigest()
    if observed != wanted:
        raise SystemExit(f"STOP: source body hash differs for {name}")
    target = destination / name
    if target.exists():
        if target.is_symlink() or target.read_bytes() != source:
            raise SystemExit(f"STOP: differing existing support file {target}")
    else:
        with target.open("xb") as stream:
            stream.write(source)
    print(name, len(source), observed)
PY
~~~

Copy this complete approved plan to
docs/pr-artifacts/perf-06-a/PERF06A6_DETAILED_PLAN.md without editing its body.
Record its independently computed hash in the execution report; the plan does
not attempt to include its own self-referential digest.

## Planning validation and limits

The plan was grounded in merged main, the authoring guide, current native
benchmark/config/cache/statistics code, historical A4 evidence and actual
native/remote public APIs. Separate reviews covered benchmark contracts,
compatibility source and guide/storage/exception handling.

Authoring verification checks the embedded file identities, extraction recipe,
Python syntax, shell-command syntax and document consistency. No Rust build,
unit/integration suite, quality gate, benchmark acquisition, writer observation,
container startup, source push or PR publication was performed while authoring.
The Rust qualification driver remains subject to its prescribed release build
during execution; a compilation or semantic discrepancy follows the stop matrix.
