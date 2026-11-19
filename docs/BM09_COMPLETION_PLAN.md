# BM-09 completion — current baselines, relative effects and durable results

**Continuation:** `BM09-CURRENT-BASELINE-1`

**Repository / PR / branch:** `yduchesne/quervant` / `110` / `dev/bm09-real-qualification`

**Date:** 19 November 2026

**Inspected branch baseline:** `560a0af320534aaec3c6e3169e9c17b3b50f3aa5`

**Fresh main / merge base:** `a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b`

## 1. Execution contract and continuity

**Pull the latest branch before starting.** The commit delivering this plan also contains the Linux/WSL2 correction. Do not reset to the authoring baseline or an earlier chat SHA.

Implement the bounded design below, then execute the current benchmarks on the coding host. Assume that host is idle and ready; verify the existing readiness conditions without asking the user to reconfirm idleness. The assistant author does not run benchmarks. The coding agent owns the implementation, tests, real acquisition, preservation and replay stages.

**Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

This continues existing PR #110. Preserve RF09-11 through RF09-19, the E2 assertion work, migration adapters and C-F01/C-F02/C-F03. The maintainer's latest decision explicitly supersedes the proposed mandatory fresh legacy-versus-new experiment. **There is no legacy-reference acquisition stage in this plan.** The current runs become the new baseline. Use authentic historical evidence when available or faithfully recoverable; otherwise disclose its absence and proceed.

The normative contract is [BENCHMARK_MIGRATION_ACCEPTANCE.md](BENCHMARK_MIGRATION_ACCEPTANCE.md). Follow [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md), [TESTING.md](TESTING.md) and repository `AGENTS.md`. Unknown cases require the matrix's scoped STOP; they do not authorize architectural improvisation. No executable attachment, external patch bundle or ZIP handoff is required.

### 1.1 Required outcome

- One complete current run through the migrated cross-engine backend, including its current A/A control.
- One complete current retained-key series through the migrated acquisition implementation: control followed by the two treatment campaigns.
- Current-run correctness, provenance, controls, raw statistics and proportional results independently verified.
- Historical/current comparisons expressed only as differences in within-run proportional effects, when compatible historical evidence exists.
- Complete raw and derived evidence automatically preserved and committed under `benchmark-results/baselines/<baseline-uuid>/`.
- Successful offline rederivation from a separate clean checkout with producer paths unavailable.
- Current-source local/hosted QA and independent review, with historical absence and unevaluated optimization policy disclosed rather than represented as successful evaluation.

Do not merge PR #110 under this plan. Do not delete frozen legacy readers/entrypoints or change historical archive hashes. Baseline acceptance does not adopt an optimization or resolve the separate RF09 ExactSet comparative-performance limitation.

### 1.2 State at handoff

| Area | State | Action |
| --- | --- | --- |
| Earlier provenance fixes, ExactSet repair and E2 assertions | Delivered | Preserve and regress on final source. |
| Official public workflow and migrated acquisition loops | Implemented | Reuse. No second runner or engine abstraction. |
| Native Linux/WSL2 support | Implemented with this plan; focused local tests passed | Preserve actual environment identity and all other host checks. |
| Existing v1 historical/full-policy acceptance | Implemented, intentionally strict | Preserve behavior and identity serialization. |
| `current-baseline-v2` profile and current retained runtime freeze | NOT IMPLEMENTED | Implement §§4–6 before timing. |
| Complete proportional-history report and committable replay | NOT IMPLEMENTED | Implement §§3 and 7. |
| Current real family runs under this profile | NOT EXECUTED | Execute after concrete source-bound QA/G0. |
| Original T6/micro/corrected PR15D observations | Missing in previous bounded search | Do not make recovery a prerequisite or fabricate them. |
| Three retained historical archives | Previously found/hash-verified | Reopen available evidence; use supported portions only. |
| F1 source receipt | Deterministically recoverable | Recover if useful from exact pinned Git bytes; it is not a measurement receipt. |

### 1.3 Current source facts and measured variants

Fresh main already contains core/objectstore/distributed crates, Directory/SegmentStore/ObjectStore contracts, segment/manifest codecs, recovery/fault tests, analyzers/postings, unified query execution and benchmark infrastructure. This PR supplies the official BM-09 workflow. Reuse those boundaries. No Rust search/storage/cache API, segment format, manifest publication, analyzer, feature or telemetry redesign belongs here.

The cross-engine run measures Quervant at the final execution source C against the currently pinned Tantivy/Lucene adapters. Retained-key still intentionally measures BASE `39dbd9f571a58bea8cc03d5a406533298e809bfe` against experiment `3ad6c5184fbe9c011abb731415a007e3f19d21de`. Its new baseline is fresh measurement of those declared variants through the current framework, **not** a measurement of current HEAD's retained-key optimizer. Keep these identities visible. Updating scientific source selections is outside this plan; never silently relabel the pinned experiment as current HEAD.

### 1.4 Observable invariants and evidence trace

| ID | Always true / forbidden counterexample | Owning implementation / checks | Completion evidence |
| --- | --- | --- | --- |
| I01 | Every effect uses one run’s explicit baseline/treatment and declared estimator; no across-run absolute effect is inferred. | §3 relative_effects; T01–T04 | Bound relative rows and proportional-history report. |
| I02 | Version/profile selection remains consistent through all reopeners; v1 never inherits a weaker v2 claim. | §4/§6 dispatch, contracts and anchors; T05–T07/T15 | Version-cross-product negatives plus public lifecycle. |
| I03 | Current runtime authority binds actual C, full source roster, host, prepared bytes and owned roots before effects. | §5 factory/outer/worker/invoke; T08–T11 | Fresh source-bound freeze and independent G0; no historical impersonation. |
| I04 | Positive current statistics verification is independent; absent memory policy cannot select a strategy. | §6 analysis/reference/verifier; T12–T16 | Raw-slot recomputation, explicit policy scope and exact check registry. |
| I05 | Every completed/partial acquisition is preserved before downstream failure; sealed members never change. | §7 exporter and workflow; T17–T20 | Immutable checkpoints, stopped status where applicable, terminal inventory. |
| I06 | Offline replay needs neither producer paths nor timing/build/service execution and cannot mint original authority. | §7 transport/offline; T21–T24 | Separate Git checkout and REPLAY_VERIFIED receipt. |
| I07 | Missing or invalid historical candidates are disclosed, never substituted for measurements or used to conceal a current defect. | §3 history/§6 acceptance; T04/T15/T25 | Authentic/as-reported/unavailable rows and excluded-input reasons. |
| I08 | Completion derives from both current family results, QA, durability and review, not test counts alone. | §10/§12; T25 | Source/result/replay/CI identities and independent acceptance. |

Residual limits: cross-environment effect changes cannot establish code-only causality; descriptive PR15D statistics do not establish significance; retained source pins do not measure current-HEAD optimizer code; absent memory inputs do not establish optimizer adoption; deterministic host tests do not substitute for the actual acquisition host’s readiness. These are disclosed scope limits, not permission to omit current-run correctness. A new defect outside these specified limits triggers M25.

## 2. Start safely, pull latest and establish the execution host

1. Inspect branch, remote, HEAD, tracking state and `git status --porcelain=v1`. Preserve unrelated edits. Fetch main and the PR branch; use a fast-forward-only update of `dev/bm09-real-qualification`.
2. Record the full pulled SHA, fresh main and merge base. Require the pulled history to contain the inspected baseline and the commit carrying this plan/host fixes. Audit intervening production changes under M03; do not reset or force-push.
3. Read the current guide, active benchmark docs and this plan. Classify already delivered work before edits. Search for existing symbols listed here; modify those owners rather than adding parallel infrastructure.
4. Observe installed Rust stable, MSRV 1.85.0, Python/console paths, cargo, Java/Gradle and container-runtime availability. Use the toolchain required by checked-in CI. Record the resolved stable version; prior 1.98.1 results are historical evidence, not proof for a different installed version.
5. Probe Unix socket creation in an owned temporary directory and run `test_evidence_paths.PathValidationTests.test_path_04_fifo_directory_and_socket_are_rejected` using the repository's supported test import path. The assistant workspace denied AF_UNIX with `PermissionError: [Errno 1] Operation not permitted`; that was an environment limit, not a WSL2 rejection. On a capable coding host the test must run normally. Do not delete, skip, mock away or weaken the socket case. If prohibited, mark local acceptance BLOCKED, continue independent work and obtain execution on a socket-capable host.
6. Native Linux and WSL2 are supported when all required capabilities are present. Keep supported Linux filesystems, allowed CPU affinity, distinct physical cores, native-path checks and readiness windows. WSL2 storage under `/mnt/c` is not an automatic substitute for an allowed Linux filesystem. Native Windows collection is outside this implementation; historical Windows-derived relative effects may still be reported.

The coding agent should communicate meaningful progress at stage boundaries and while long gates run. A passing preflight is not a reason to hand the task back.

## 3. Performance and history contract

### 3.1 Within-run effects; across-run proportional changes

A/B identify baseline/treatment within one experiment. They do not identify the old/new framework. Preserve the existing paired/interleaved schedules; do not interpret “A then B” as permission to run all A observations first.

Let `r` be the declared estimator's treatment/baseline ratio. For lower-is-better metrics, `gain_percent = 100 × (1 − r)`; for higher-is-better, `gain_percent = 100 × (r − 1)`. Positive means a treatment advantage. Label latency reduction as latency reduction; do not confuse it with reciprocal speedup. Preserve estimator precision and round only its presentation. A paired-block estimator is not a quotient of unrelated pooled medians.

Across comparable runs, show both gains and `effect_change_percentage_points = current_gain − historical_gain`. A previous 20% latency reduction and current 10% reduction means a ten-percentage-point narrowing. It does not establish that either current A or current B is slower in absolute terms. Never compute historical/current A ratios, historical/current B ratios, absolute A-minus-B changes across runs or legacy/new runner latency ratios as performance conclusions.

Within a run, host/configuration must remain fixed. Across runs, platform differences do not automatically reject proportional comparison. Record environment/source/config changes as context. Ratios reduce environmental dependence but do not eliminate it; an observed effect change across environments is not automatically a code-only regression.

### 3.2 Pure relative-effects projection

Add `official/relative_effects.py`, a pure projection over validated results, not a new estimator. Each normalized row has exactly:

`study_id`, `run_id`, `campaign_id`, `lane_id`, `metric`, `unit`, `regime`, `direction`, `baseline`, `treatment`, `method_id`, `ratio`, `gain_percent`, `uncertainty`, `decision`, `evidence_level`, `source_commit`, `host_environment`, `host_identity`, `input_digest`.

Direction is `lower` or `higher`; evidence level is `RECOMPUTED` or `AS_REPORTED`. Ratios/gains are canonical decimal strings. Uncertainty is null or the existing interval with exact `low`, `high`, `method`; do not invent CIs/significance for PR15D. Unknown historical source/host fields are null with disclosure. Raw absolute measurements remain preserved for rederivation, but relative effects lead the report.

Cross-run rows contain exactly `historical_row_digest`, `current_row_digest`, `comparability`, `context_changes`, `effect_change_percentage_points`. Comparability is `COMPARABLE`, `CONTEXT_CHANGED` or `NOT_COMPARABLE`. Numeric comparison requires matching workload coordinates, metric/unit/direction, arm roles and estimator. Source revisions and environment may differ and are recorded. Unknown orientation, changed semantics/K/N/class, missing estimator or unsupported conversion yields `NOT_COMPARABLE` and null change; no fuzzy name matching or silent inversion.

Keep the actual numerator/denominator orientation of frozen fields. Test it from known values, not labels. An A/B speedup of 1.20 is about 16.67% lower B latency, not 20%; a B/A throughput ratio of 1.20 is 20% higher throughput. An ambiguous historical “20% faster” is not a normalizable measurement.

For retained-key v2, publish the existing complete paired raw-slot statistics from `retained_policy.derive_slot_statistics`, checked independently by `policy_reference.reference_slot_statistics`: all six L/A, P/A, H/A, P/L, H/L, H/P ratios, their CIs/seeds, filtered/unfiltered latencies and filter sensitivity. Neither function needs micro/F1. The literal field mapping is R_L_A/CI_L_A→baseline A,treatment L; R_P_A/CI_P_A→A/P; R_H_A/CI_H_A→A/H; R_P_L/CI_P_L→L/P; R_H_L/CI_H_L→L/H; R_H_P/CI_H_P→P/H. All are lower-is-better latency ratios. Emit 72 lanes × 2 campaigns × 6 comparisons =864 current retained rows, with the actual campaign name and warm regime; never pool campaigns. The decision field is DESCRIPTIVE_EFFECT_ONLY when optimization policy is unevaluated; do not infer selection from a CI. Cross-engine emits 32 warm effect rows (16 lanes × 2 comparators), baseline=quervant and treatment=the lucene/tantivy comparator (the existing ratio is comparator/Quervant), with campaign_id=three-trial-backend and the existing descriptive INCONCLUSIVE decision. Preserve cold/build/throughput data as existing descriptive observations, without inventing a new estimator. The uniqueness key is study/run/campaign/lane/metric/unit/regime/baseline/treatment/method. Do not mix the paired-slot symmetric exclusion/median conventions with the separate existing descriptive block table; preserve that table with its own method identity. Cross-engine keeps its present three-trial estimator and rounding. Do not implement the superseded legacy-compatible rounding change.

### 3.3 Bounded historical use

Add `official/history.py`. Its input is a closed location inventory, not a PASS list. The inventory contains exactly `kind`, `schema_version`, `candidates`; each candidate contains `family`, `input_role`, `path`, `source_identity`, `expected_digest` (null permitted only when no independent digest exists). The exact input_role enum is retained-archive, retained-micro, retained-f1-receipt, retained-t6-receipt, pr15d-archive, pr15d-aggregate, retained-analysis, retained-policy. Inventory kind is official-baseline-history-inputs, schema_version1; family is retained-key or cross-engine. Each role has one fixed owning existing reader/normalized-field mapping; do not accept arbitrary schemas or a configurable parser. Use existing strict readers where they apply. A path or declared digest is not its own authentication.

Search once in: paths already recorded in the preceding BM-09 evidence; checked-in `benchmark-results` and PR artifacts; the original documented benchmark archive directories; and additional exact paths explicitly supplied by the user. Do not scan the entire machine or keep requesting absent archives. Recover deterministic receipts/derived results only from authentic inputs with their original algorithm and pinned identity. Re-running timing cannot reproduce lost historical observations.

Available authentic raw data may be reanalyzed. Authentic original explicit ratios without raw inputs may be shown `AS_REPORTED`, with their original source/digest/precision and no claim of recomputed parity. Missing is `UNAVAILABLE`; present malformed is `INVALID`; insufficient authentication is `UNVERIFIED`; incompatible semantics is `NOT_COMPARABLE`. Exclude invalid/unauthenticated candidates from numeric comparison. Their presence does not invalidate an independently verified current baseline unless it exposes a defect affecting current calculations/provenance. Keep historical statuses in the final report; never manufacture historical PASS.

The history report is bound into acceptance as a disclosure. It cannot mint `VerifiedHistoricalParity`, certify current data, or require a replacement legacy run. Existing strict historical openers remain available and unchanged.

## 4. Explicit current-baseline v2; preserve v1

### 4.1 Versions and configuration

Keep workload IDs `cross-engine-keyword-real-v1` and `retained-key-topk-real-v1`. Add `benchmarks/official-protocols/cross-engine-keyword-v2.json` and `retained-key-topk-v2.json`, registered by `(study_id, version)`. Add keyword-only `version=1` to `template_path`, retaining v1 default for old callers.

Only config1/template1/G0-1/operation1 → existing v1, and config2/template2/G0-2/operation2 → `current-baseline-v2`, are valid. Reject mixed/unknown/bool versions before directories, processes or timing. Do not globally change shared schema constants. Preserve v1 serialized freeze identities and digests; add v2 identity fields only in the v2 branch. Synthetic config stays version1.

V2 config retains the current exact top-level key set except `historical_parity`, replacing it with `acceptance_profile` and `baseline`. Profile is literal `current-baseline-v2`. `baseline` has exactly `baseline_id`, `evidence_root`, `history_inventory`, `runtime_freeze_path`. Baseline ID is a UUID4 shared by both family operations; each family has its own distinct run UUID. Evidence root is exactly the ordinary branch checkout's `benchmark-results/baselines/<baseline_id>`. Runtime freeze path is required for retained-key, null for cross-engine, checked in workflow validation before effects. Cross-engine must reject non-null retained policy inputs. Retain `policy_inputs`: null is explicitly allowed in v2; a non-null supplied input must pass the existing authenticated reader and cannot silently become null on a validation error.

Use existing normalized absolute/no-symlink path validation. Config locates data; it cannot supply commands, thresholds, retries, approval booleans, success states or trusted observed digests.

V2 templates copy existing workload/source pins/host requirements/schedules/controls/timing limits/oracle/QA rosters unchanged. Add `acceptance_profile="current-baseline-v2"` and a closed `baseline` object with `history="optional-authentic-v1"`, `performance="within-run-effects-v1"`, `preservation="committable-baseline-v1"`, `optimization_selection_required=false`. Retained predecessors replace the historical-receipt requirement with `runtime_freeze_kind="official-current-runtime-freeze"`, retaining control-first, publish-between-campaigns and exact campaign order. Do not alter the frozen backend protocol.

V2 G0 retains v1 fields and adds `acceptance_profile`, `baseline_id`, `preservation_root_identity`, `runtime_freeze_digest` (null for cross-engine). Derive them from actual observations. Validate each field by its type: literal profile, UUID4 baseline ID, normalized absolute preservation-root identity, and family-dependent nullable digest. Do not append these fields to the old digest-only observation loop. Bind the freshly generated freeze, prepared binaries, source, host, corpus, QA and output paths. Permitted campaign sequences remain the existing cross-engine control/treatment and retained three-campaign lists. No legacy stage or extra micro stage is authorized by this plan.

### 4.2 Hidden dispatch sites that must all change

| Owner | Required change |
| --- | --- |
| `execution/operator.py::read_operation_document` | Accept official schema2 only; preserve synthetic1 and reject mixed versions. |
| `official/operation_config.py` | Select exact V1/V2 key sets before closed validation. |
| `official/protocols.py` | Versioned template registry, validator and freeze serialization; campaign order checked with selected profile. |
| `official/workflow.py::_template`, `_operation_record`, later-stage reopening | Persist and recheck version/profile/design; never silently reopen v2 with v1. |
| `official/cross_engine_backend.py::_template` | Replace hardcoded v1 filename with selection from verified freeze version and design digest. |
| `official/retained_acquisition.py`, outer and worker | Reopen the retained template and current runtime freeze for v2 before effects. |
| `official/acquisition.py` | v1 retains historical precondition; v2 requires the current runtime capability. |
| `official/authorization.py`, `operation_identity.py` | Re-observe v2 fields; preserve exact-type/sentinel/reverification controls. |
| `analysis.py`, `verification.py`, `contracts.py` | Complete v2 raw-slot effect payload and explicit baseline verification scope. |
| `coordinator.py`, `receipts.py`, `publication.py` | Versioned Gate D inputs/anchors/reopen checks; no historical-PASS placeholder. |
| `report.py` | Current-baseline closeout, relative/history reporting and policy limitations. |
| `migrations/offline.py`, new `official/transport.py` | Separate real-baseline transport/replay route; synthetic viewer unchanged. |

The existing CLI `prepare` and `run` already accept `--protocol`/`--config`. Use them after implementing v2 dispatch. Do not invent `inspect --profile`, `--prebuilt`, `--skip-build`, `--control-only` or unsupported diagnostic commands. `inspect` remains the current v1 declaration view; v2 preparation returns its actual template/version/digest.

## 5. Current retained runtime freeze, without historical forgery

Implement `official/runtime_freeze.py`. It establishes a fresh execution freeze of the current approved source and inputs. It is not restoration of the missing historical T6. No separate legacy measurement route is added.

Use a clean owned detached execution checkout at C. The frozen retained helper uses `target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json`; that path must be absent in the new checkout. Create a narrowly defined backend-compatible fresh receipt there exclusively, with the exact keys:

`schema`, `protocol_sha256`, `control_name`, `campaign_names`, `t6_commit`, `tooling_manifest_sha256`, `protected_files`, `receipt_origin`.

Values: schema `pr15i-d3c-freeze-v1`; protocol raw digest `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`; control `d3c-v3r3-base-aa-01`; campaigns `d3c-v3r3-strategies-01`, `d3c-v3r3-strategies-02`; `t6_commit=C` (truthfully this new freeze's source); observed tooling-manifest raw digest; `receipt_origin="current-baseline-v2"`.

`protected_files` is the sorted union of `qualification.identity.source_roster(execution_checkout)` after requiring clean HEAD=C, and these exact paths: `benchmarks/pr15i_d3_c/{run.py,verify.py,protocol_v3r3.json,host_topology.py,tooling_manifest.json}`, `benchmarks/pr15d/harness/run.py`, `benchmarks/pr15d/corpus/{generate.py,oracle.py}`, `benchmarks/scripts/check-pr07-contention.py`, and the registered retained-v2 template. Hash each actual Git blob at C and require the working bytes to match. Compatibility `protocol_sha256`, `tooling_manifest_sha256` and protected-file digests are unprefixed lowercase64-hex, as required by the original helper. Validate exact roster equality; empty/subset/extra rosters fail. The original helper's permissive subset loop is not sufficient validation. Pin the BASE/experiment commits and prepared binary identities separately; this Python roster does not replace those bindings.

Write the separate v2 envelope at `runtime_freeze_path` with exactly:

`kind`, `schema_version`, `origin`, `baseline_id`, `study_id`, `source_commit`, `source_tree_sha`, `source_file_set_digest`, `design_digest`, `backend_protocol_digest`, `backend_receipt_digest`, `prepared_manifest_digest`, `binary_manifest_digest`, `corpus_manifest_digest`, `host_preflight_digest`, `adapter_cpu`, `controller_cpu`, `control_schedule_digest`, `treatment_schedule_digest`, `approved_output_root_identity`.

Kind is `official-current-runtime-freeze`, version2, origin `current`. Envelope digest fields use sha256: prefixes. backend_receipt_digest and prepared_manifest_digest hash the complete actual file bytes, including any trailing newline; design/schedule/host/content fields retain the owning existing content_digest convention (canonical payload without newline). source_tree_sha retains the existing operation_identity.git_identity tree-document digest convention; do not replace it with a bare Git tree SHA. Every identity is observed, not copied from a candidate approval. The envelope has no self-digest. G0 independently binds its digest. Preparation may produce these candidates but cannot approve them. This avoids a source/approval cycle. In v2 prepare: complete/reopen prepared binaries/corpus; write/revalidate preparation-inputs.json; create/reopen runtime receipt/envelope; then call _preparation_qa_observations and emit authorization inputs. Runtime creation uses only the explicitly listed QA-independent source/prepared/host/schedule/root observations, never the full observe_identities function (which reads QA and will itself need the runtime digest). Source C and prepared inputs exist first; freeze second; source-bound QA/G0 bind them before timing.

Only a factory-issued `VerifiedCurrentRuntimeFreeze` may open v2 retained acquisition. Reopen both envelope and compatibility receipt, recompute full roster/source/prepared/host/root bindings, require exact type/private sentinel and canonical equality on revalidation. Preserve original helper checks by still calling `runner.require_freeze` after this stronger validation. The original readiness and publish helpers can therefore be reused unchanged; their `t6_commit` now truthfully names the new freeze, not an alleged historic approval.

V1 preconditions must reject `receipt_origin="current-baseline-v2"` before effects. This prevents fresh compatibility data from being accepted as an original historical prerequisite. Never overwrite an existing receipt; use a fresh owned checkout. Never change frozen helpers, their protocol, historical archive hashes or a historical receipt. Revalidate at workflow open, invocation construction, outer acquisition, worker start, readiness and publication. Name the barriers explicitly: workflow._invoke revalidates immediately before each retained readiness/publish child; retained_acquisition._worker receives the runtime-envelope path, expected digest and selected profile from the verified outer authorization and reopens them before _execute_campaign or deliberate CPU pinning. The direct acquire_retained_campaign v1 entry must also reject the fresh receipt marker; relying only on workflow preconditions misses that public boundary. Propagate selected version/binding into the worker. No empty receipt, monkeypatch or bypass flag is allowed.

Use existing `_execute_campaign`, `_build_bound_inputs`, `_require_built_binary`, original `verified` predecessor checks and publisher. Fresh predecessor archives are produced during this run in its private HOME; they are not missing historical archives. Preserve control-first and publication between campaigns.

## 6. Current-run analysis and baseline acceptance

### 6.1 Required complete workloads

| Family | Complete current acquisition |
| --- | --- |
| Cross-engine | Three engines × three trials; N10K/100K, four classes, K10/100, cold/warm: nine manifests, 288 latency lanes, 5,760 samples; 18 build observations; 18 serial throughput windows of 100 requests with five warmups. Preserve trial engine order. |
| Cross-engine control | Existing 12×4 A/A slots, 16 warm lanes each, 20 samples each: 15,360 samples, plus existing warmups/windows. |
| Retained-key | Control48 slots, campaign1 96, campaign2 96; 72 lanes/slot; five warmups and20 samples: 345,600 samples total. N10K/100K, four classes and K1/10/32/64/100/128/256/512/1024. |

Keep backend query/oracle semantics, all supported cold/descriptive fields and disclosures. Process-cold is not OS-cache-cold. Do not shrink workloads, select successful lanes, invent repetitions or retry a failed timed campaign. Current source/binaries/host/config must remain stable. Different historical/current effects do not by themselves fail a current benchmark.

### 6.2 Baseline verification is a positive, narrower contract

V1 remains unchanged. V2 retained analysis calls `lanes, authenticated_slots = derive_slot_statistics(admitted)` and adds `retained_slot_statistics` to a new closed version2 analysis envelope. That field has exactly method_id=`retained-key-paired-slot-effects-v1` and lanes=the complete first return mapping. The tuple-key authenticated_slots mapping stays internal/recomputed; do not serialize the function return tuple. This new wrapper names the existing unchanged paired-slot computation, not new arithmetic. Preserve the old descriptive table and its identity separately. The independent Gate C path uses the complete first return from `reference_slot_statistics` on freshly re-admitted disk slots and the same literal wrapper identity, never importing the production derivation. Compare all coordinates, retained IDs/counts, six ratios, CIs/seeds, filtered/unfiltered latencies and filter sensitivity exactly; no tolerance that conceals a decision or sample difference.

Document versions are independent: v2 execution with absent inputs retains existing policy schema1/POLICY_NOT_DERIVABLE; complete authenticated retained policy retains existing policy schema2 with its mandatory nine-K payload; extended retained analysis, baseline verification and acceptance use their newly specified version2; generic receipt transport stays version1. Do not mechanically bump every document because the execution profile is v2.

When `policy_inputs` is null, do not run a fresh microbenchmark merely to recover old policy inputs. Allow the v2 workflow to analyze current raw slots. Emit no selected strategy and `performance_claim_allowed=false` for optimization adoption; mark policy `POLICY_NOT_DERIVABLE` and explain the unavailable memory/F1 inputs. Descriptive measured gain/loss is still reportable with its uncertainty. Do not invent zero memory, fallback strategy, P/H eligibility or nine-K selection rows.

Add verification schema2 with `verification_scope="current-baseline-v2"`, status `VERIFIED_CURRENT_BASELINE`, `policy_verification_status` and `not_evaluated_checks`. Its required checks are the existing RV01–RV10 registry excluding only `RV-08-POLICY` when policy inputs are absent. In that case `not_evaluated_checks` is exactly `["RV-08-POLICY"]`, policy status `NOT_EVALUATED`, claims exclude `policy-decision`, and the verifier positively checks selected arm is null/adoption false/the disclosed reason matches absent inputs. If authenticated policy inputs are supplied, evaluate RV08 normally and require all ten checks; invalid supplied policy evidence is an error, not an absence exemption. Cross-engine retains its existing descriptive INCONCLUSIVE policy and all applicable checks.

Never treat an arbitrary old `BLOCKED` assessment as PASS, and never label the nine-check baseline result `VERIFIED_REAL` under the ten-check v1 contract. Current sample/correctness/provenance/control/calculation failures always block current baseline qualification. Both paired-slot functions raise when fewer than four symmetric blocks remain. For that exact condition, preserve the complete acquisition and diagnostics, emit a typed insufficient-data BLOCKED analysis/acceptance outcome, and produce no invented/null ratio schema or timed retry. Partial per-lane acceptance is not designed here.

### 6.3 Gate D, receipt inputs and publication

Add an explicitly selected v2 acceptance contract with `decision_scope="real-current-baseline-v2"`. It requires current admission, current baseline verification, QA, controls and real authorization. Replace mandatory `historical_parity_status=PASS` with a `history_report_digest` and actual historical availability statuses. Keep policy disposition visible. Remove mandatory fresh-comparison proof entirely.

V2 acceptance summary retains the current identity/gate/control/QA/admission fields, changes schema to2 and replaces `historical_parity_status` with `history_report_digest`, `baseline_id`, `baseline_verification_status`, `policy_verification_status`. Its receipt input roster replaces `historical-parity` with `history-report` and adds `relative-effects`; all other existing inputs remain. The generic receipt transport envelope stays version1. Add keyword-only profile_version=1 through official_validator_identity, receipt build/verify and gate-graph verification; choose2 only from refreshed v2 authorization. Register its validator identity/rosters explicitly; keep v1 identity/version/inputs unchanged. The exact v2 acceptance input set is admission-index, analysis, authorization, control-assessment, framework-qa-evidence, history-report, policy, relative-effects, source-qa-evidence, source-set, verification-assessment. Do not infer version from the receipt under validation or broaden global v1 input rosters.

Use separate exact-type OfficialBaselineAnchors. Its fields are subject, approved_design_digest, authorization_digest, backend_protocol_digest, source_set_digest, binary_manifest_digest, corpus_manifest_digest, host_preflight_digest, original_verifier_digest, policy_digest, qa_roster_digest, control_assessment_digest, acceptance_profile, baseline_id, history_report_digest, relative_effects_digest. Validate profile/UUID separately from digests. publication._require_anchors, bundle loading and _expected_inputs must all dispatch using the refreshed authorization version.

Write bound disclosure files at the fixed operation-directory paths history-report.json and relative-effects.json, exclusively or byte-identical read-only reuse. Both payloads have a closed identity envelope: kind, schema_version=1, baseline_id, study_id, source_commit, current_raw_digest, and respectively entries or rows. Kinds are official-baseline-history and official-baseline-relative-effects. History entries retain input_role, source_identity, input_digest, status, reason, normalized_rows; normalized rows follow §3.2. Define history.open_verified_baseline_disclosures to reopen/validate these two files from the authorized operation root, bind source/run/raw identities, independently reconstruct current effect rows from the verified analysis and return an exact-type private-sentinel capability holding the two observed digests and private source paths. Pass that capability as required keyword-only baseline_context to v2 bundle publication/loading; v1 keeps null. Reopen it at publication barriers and compare its digests to anchors. Include the actual two payloads in transport reports/history, not only their hashes.

Publication reopening must independently recompute the required input map, revalidate current raw/analysis/control evidence and verify the bound disclosure. A caller-supplied PASS/history map cannot satisfy it. Preserve the 15-member derived bundle layout where the versioned member payloads permit it; raw preservation is a separate complete baseline evidence tree.

V2 closeout requires L1/L2, both independently authorized current family runs, controls, positive current-baseline verification, genuine source QA, original attestation reopen, final CI, complete result preservation, clean-checkout replay and independent review. It does not require historical PASS or an optimization selection. Keep v1 `CloseoutInputs` behavior intact; add a distinct `CurrentBaselineCloseoutInputs`. Historical limitations remain visible even when v2 baseline acceptance passes.

## 7. Automatic preservation and clean-checkout replay

### 7.1 Destination and lifecycle

A baseline UUID groups the two family run UUIDs. Validate the ordinary branch checkout and the exact destination `benchmark-results/baselines/<baseline-uuid>/` before acquisition, including `git check-ignore`; it must be committable. The executing checkout remains clean at C. Evidence commits belong to the separate ordinary checkout and never change the measured source identity.

Add `official/transport.py` with `preserve_baseline_checkpoint`, `finalize_baseline_evidence`, `open_verified_baseline_evidence` and `replay_baseline_evidence`. These are planned APIs, not commands that already exist. Reuse current exclusive writers, safe-member/path helpers, canonical JSON and SHA-256 code. No generic uploader, ZIP executor, remote artifact dependency or new plugin mechanism.

After each completed acquisition unit, publish its logical evidence subtree and an immutable checkpoint before proceeding. Units are cross-engine control, cross-engine treatment, and each retained campaign. Also preserve stopped partial units after owned-process cleanup. The original failure stays primary if preservation itself fails. Existing checkpoint/member bytes cannot be overwritten. Read-only reopening or reuse of an exactly byte-identical completed checkpoint is permitted; no timed resume.

Use this fixed layout beneath the baseline root:

- `studies/cross-engine-keyword-real-v1/<run-uuid>/raw/` for new control and treatment measurements.
- `studies/retained-key-topk-real-v1/<run-uuid>/raw/` for the three current campaigns and their seals.
- Each study/run also owns `provenance/`, `authorization/`, `qa/`, `analysis/`, `verification/`, `qualification/`, `policy-inputs/` and `checkpoints/`.
- `history/` for the location/status inventory and authenticated original historical inputs actually used; no fabricated placeholder inputs.
- `reports/` for current relative effects, historical/current proportional comparisons and limitations.
- `baseline-manifest.json` published once after all expected members/checkpoints are terminal.

Create only applicable subdirectories; the terminal inventory declares absent optional policy inputs and incomplete/failed acquisitions explicitly. It cannot call a partial series COMPLETE. Preserve genuine backend-created archive/sidecar evidence needed by the current run; an archive is data, not an executable handoff to the user.

### 7.2 Exact logical content

Preserve all nonregenerable inputs/results: every measured sample and slot/trial manifest; control/readiness observations; original seals/inventories and verifier results; current G0/profile/freeze/preparation documents; source/build/toolchain/binary inventories; complete executed-QA summaries/check records/logs actually used; analysis/policy/independent assessments; the unchanged original derived qualification bundle; history disclosures; and every optional input actually consumed. Do not export only medians, final policy rows or fifteen derived files.

Do not commit binaries, JARs, virtualenvs, indexes, build trees, caches or private HOME contents. Store runtime inventories/hashes. Preserve the deterministic corpus recipe, frozen generator identity, manifest and expected file hashes; regenerate it untimed during replay. If a used corpus cannot be reconstructed from that closed recipe, STOP publication rather than omit necessary evidence.

The terminal manifest has exactly `kind`, `schema_version`, `baseline_id`, `profile`, `source_commit`, `source_file_set_digest`, `design_digests`, `study_runs`, `members`, `checkpoints`, `corpus`, `relocations`, `status`. Kind is `official-baseline-evidence`, version1, profile `current-baseline-v2`; status is `COMPLETE` or `STOPPED`. `study_runs` maps the two literal study IDs to their run IDs/status/qualification-manifest digests. Design digests map the same IDs to approved templates. Each member entry is `path`, `size_bytes`, `sha256`, `role`, sorted by path. Allowed roles are raw/control/readiness/provenance/authorization/qa/policy-input/analysis/verification/history/report/qualification/checkpoint. The manifest does not inventory itself; its digest is external. Reject absolute/dot-dot/non-normalized paths, links/special files, duplicate/case-colliding names, undeclared members and inconsistent lengths/hashes.

Allocate public-safe output paths before execution. Never dump an environment or export credentials. Preserve original sealed measurement bytes unchanged. Redact bounded execution logs before their public version is sealed, using existing explicit credential-field handling. If a mandatory already sealed member contains a secret that cannot be preserved safely, STOP publication and identify the field; do not silently redact sealed data or claim a complete export.

### 7.3 Replay capability and fixed relocation rules

`VerifiedBaselineEvidence` proves the exported content and its link to the original run; it is not a new G0 or a factory for original production capabilities. Original authorization/attestation bytes remain checked against their original digests. Replay produces `REPLAY_VERIFIED` in a separate record and never rewrites an original attestation.

Extend the existing `verify --run <uuid> --offline` route to recognize exactly `benchmark-results/baselines/<uuid>/baseline-manifest.json` with the above kind. Keep the synthetic offline loader unchanged. Reject ambiguous synthetic/baseline UUID matches. Preserve the existing prohibition on combining `--offline` and `--config`. No new public flags are needed. `report --run <uuid> --offline` renders the preserved baseline/history report with its replay status; it does not acquire data.

Replay uses an owned scratch directory under the replay checkout's `target/pr15i-d3-c/` when the retained verifier requires that namespace. First verify all original bytes/seals/archives and source bindings. Materialize regular-file working copies; keep the committed originals untouched. Regenerate and hash-check the corpus with the pinned Python generator. Run only bounded Python verification/analysis and pure current analyzers; never build adapters, call cargo/Gradle, start services, collect timing or use credentials/network.

The relocation allowlist is deliberately small:

- Cross-engine working `run.json`: change only `/corpus_dir` to the verified replay corpus path.
- Retained working `raw/build-provenance.json`: change only `/canonical_source_path` and each `/events/<index>/canonical_source` to that replay campaign's `compile-source` location.
- For those retained working-copy edits only, recompute `/build_provenance_sha256` in working `manifest.json`, then recompute the corresponding provenance/manifest entries in working `raw/seal.json`'s `files` map. No other semantic field or digest is rewritten.

Record each original digest, working-copy digest, exact JSON pointer and old/new value in the replay relocation receipt. The derived working seals are explicitly transport projections, not original acquisition seals. Verify the original seals before any projection. Run the unchanged original validators on these confined working views, and the current independent statistics/effects functions on the authenticated logical samples. Check every permitted edit and require all measured/source/arm/schedule/metric fields to remain identical. Do not modify frozen validators or broaden the allowlist after seeing an error. An unanticipated path dependency is M25.

Fresh-checkout acceptance: commit the baseline directory on the ordinary branch; create a separate checkout from that Git commit at a different absolute root; deny access to producer target/HOME/raw/corpus paths and deny timing/build/network/service seams; then run the implemented offline verification route. Require complete semantic/statistical/report equality and `REPLAY_VERIFIED`. Mutated or missing members must fail.

Avoid a manifest/replay self-digest cycle. The terminal baseline manifest is immutable before replay. Save the separate replay receipt at `benchmark-results/replays/<baseline-uuid>/<replay-uuid>.json`, binding the baseline-manifest digest, measured source C, evidence commit and replay checkout identity. Commit that receipt afterward. Closeout requires this verified receipt; the original baseline manifest does not need to contain its own future replay evidence.

## 8. Exact implementation scope and reuse

### 8.1 Allowed production paths

All names below are relative to `benchmarks/quervant_bench/` unless stated otherwise:

- Existing: `execution/operator.py`; `official/{protocols,operation_config,operation_identity,operation_store,authorization,acquisition,retained_acquisition,cross_engine_backend,workflow,analysis,verification,contracts,coordinator,receipts,publication,report,policy_inputs}.py`; `migrations/offline.py`.
- New: `official/{runtime_freeze,relative_effects,history,transport}.py`.
- New templates: `benchmarks/official-protocols/{cross-engine-keyword-v2,retained-key-topk-v2}.json`.
- `qualification/identity.py` only if a new non-Python contract requires explicit source-roster registration; do not change the existing tracked-Python roster algorithm to avoid untracked-file rejection.
- `official/{retained_policy,policy_reference}.py` only for extracting/reusing their existing statistics shape or annotations; no mathematical change. Prefer calling their existing public functions.

Keep current v1 templates and their Linux/WSL2 behavior. Do not modify frozen `benchmarks/pr15d/**`, `benchmarks/pr15i_d3_c/**`, T7/F2 sources, historical archive/mapping bytes, BM-01 whitelist/inventory, Rust source/benches, Cargo manifests/lockfiles, CI trigger/identity steps, or generic synthetic contracts. No unsupported diagnostic harness changes are needed.

### 8.2 Tests, fixtures, docs and results

Extend the corresponding existing `test_operator.py`, `test_official_{protocols,operation_identity,workflow,admission,verification,analysis,coordinator,publication,report,qa_evidence,retained_acquisition,cross_engine_backend,policy_inputs}.py`, and existing CLI/offline tests. Add `test_official_{runtime_freeze,current_baseline,relative_effects,history,transport}.py`. Preserve independent expected values; do not import the implementation under test as its oracle.

Source-dependent fixtures may be refreshed once after final Python edits, limited to the existing twelve controlled qualification JSON files and independent test template pins. Keep their synthetic scope. Stage new Python modules before computing the source roster. Reopen both QA fixture chains, verify profile unchanged unless deliberately versioned for the new profile, and verify the post-freeze digest remains stable. Test fixture refresh is not real SOURCE_QA.

Update these active docs: this plan, `BENCHMARK_MIGRATION_ACCEPTANCE.md`, `BENCHMARK_WORKFLOW.md`, `BENCHMARKING.md`, `benchmarking/BENCHMARKING_MIGRATION.md`, `benchmarking/BENCHMARKING_ROADMAP.md`. Append evidence to the existing BM-09 design/contracts, review-fixup evidence, verification report and QA/attestation files; do not rewrite old records. Add only generated verified baseline/replay data beneath the two result namespaces in §7.

Any needed production/test path outside this list requires M25. Do not broaden the allowlist by editing this plan while executing it.

## 9. Acceptance test matrix

Write/execute focused tests for concrete new behavior and high-risk boundaries, not tests that merely repeat assignment statements. Use real filesystem/Git/public CLI boundaries where affected; fake only host/process external boundaries in unit tests. No unit fixture may claim real execution.

| ID | Positive and adversarial requirement |
| --- | --- |
| T01 | Lower/higher metric examples, reciprocal speedup versus latency reduction, zero-denominator/nonfinite/bool rejection. |
| T02 | Historical20%/current10% produces −10 percentage points; same A/B scale change preserves effect; no cross-run absolute-time field is produced. |
| T03 | Different platform yields contextual comparison, not rejection or causal-code claim; changed metric/estimator/arm meaning is NOT_COMPARABLE. |
| T04 | Authentic summary without raw is AS_REPORTED; unavailable/invalid/ambiguous history cannot mint numeric/recomputed PASS; current baseline still proceeds. |
| T05 | Every mixed config/template/G0/operation version rejects before filesystem/process effects; bool/unknown versions reject. |
| T06 | v1 freeze identity bytes/digests and strict historical/full-policy behavior are unchanged. Later verbs cannot reopen v2 using v1. |
| T07 | Both families use selected template through host/readiness/backend paths; preserve Linux and WSL2 positives and literal-selector negatives. |
| T08 | Current runtime receipt uses actual C and full exact roster. Empty/subset/extra/changed roster, changed Git blob or working bytes rejects. |
| T09 | Fresh receipt cannot pass v1 historical preconditions; existing receipt is never overwritten; source/host/binary/root change rejects before worker/query. |
| T10 | Runtime envelope/capability mutation, dataclasses.replace, numeric alias, missing source root and false origin reject on reopen. |
| T11 | Exact existing retained predecessor/control/publish sequence; all outer/worker/readiness/publish gates revalidate; no legacy/micro acquisition is called. |
| T12 | Retained v2 with no micro/F1 still derives complete slot ratios/CIs from real-shaped raw fixtures; independent reference matches exactly. |
| T13 | Mutated median, symmetric retained set, seed/CI endpoint, ratio orientation or one sample is detected by the independent verifier. |
| T14 | Missing policy emits selected=null/adoption=false and explicit RV08 NOT_EVALUATED; no VERIFIED_REAL/full-policy claim. Invalid supplied policy cannot downgrade to absent. |
| T15 | v2 acceptance/publication require exact profile/positive baseline verification/history-effects digests; v1 requires old historical parity. Caller PASS, wrong family or tampered anchors fail. |
| T16 | Existing current cross-engine workload/rounding and retained scientific pins remain unchanged; full coverage including cold/index/throughput disclosures. |
| T17 | Failure after completed acquisition but before policy/acceptance leaves a complete immutable raw checkpoint in the committable path. |
| T18 | Interrupted acquisition preserves partial non-passing evidence and owned cleanup; no timed retry/resume; original error retained if export also fails. |
| T19 | Exclusive checkpoint/terminal publication, byte-identical reuse, conflicting bytes, symlink/FIFO/socket/hardlink and path traversal cases. |
| T20 | Terminal COMPLETE cannot omit one family, one required raw record, QA/provenance, consumed policy input or original qualification record. |
| T21 | Fresh checkout replays with producer paths inaccessible and timing/build/network/services disabled; real filesystem/public offline CLI exercised. |
| T22 | Mutated/extra/missing transport member, incorrect digest/length, wrong profile/source or ambiguous UUID rejects. |
| T23 | Allowed path projections recorded; attempting a sample/source/metric edit or unlisted JSON pointer rejects even if a working seal is recomputed. |
| T24 | Original attestation remains distinguishable from REPLAY_VERIFIED; no replay can mint current G0 or historical PASS. |
| T25 | Both family completeness/current QA/replay/review gate closeout; absent history or disclosed optimization-policy absence does not alone block v2. |

Before modifying production, record the old behavior for T05 and T12/T14 using the actual public boundaries: v2 rejects and v1 retained-without-policy blocks. These are intentional old contracts, not assertions that historical v1 is defective. Add the new behavior only under v2. Preserve regression negatives from F3/F4/E2 rather than recreating arithmetic replicas.

Final adversarial review must answer: could false history certify current data; could v2 silently select v1; could missing policy become strategy selection; could both statistics paths share the same erroneous helper; could an unpreserved raw unit disappear after failure; could replay rely on producer paths; could resealing a relocated working copy hide an altered measurement? Cite the named tests and real evidence or mark the remaining issue blocked.

## 10. Ordered execution and repository gates

1. **Pull/reconcile:** complete §2, classify existing work and apply the matrix. Preserve completed RF09 work. Record sockets/toolchains/host and scope.
2. **Contracts first:** implement v2 schemas/dispatch and runtime freeze with before-effect negatives. Implement complete raw-slot effects and independent baseline verification. Keep v1 tests green.
3. **Reporting/preservation:** implement historical proportional projection, immediate checkpoints, terminal manifest and offline replay. Run the full focused matrix and public filesystem/CLI integration before any real timing.
4. **Freeze candidate C:** finish source/tests, controlled fixture refresh and docs needed to execute. Commit ordinary changes; verify tree clean, source digest and protected-source inventory. Push normally. No benchmark runs on dirty source.
5. **Local QA on C:** execute the repository commands below serially where CPU/load measurements could be affected. Record exact argv/toolchain/count/exit and ignored/skipped details. Do not use an empty test filter as PASS.
6. **Real service/adapter QA:** run owned RustFS integration and complete comparative adapter correctness, collect actual source-bound raw logs. Prepare untimed corpus/binaries before final QA sealing if their identity is needed. Do not omit current-source checks because previous heads were green.
7. **Hosted CI/source QA/G0:** observe exact C push and PR merge runs, all four jobs and identity logs. Seal real executed-QA evidence for C/prepared binaries. Finalize the same prepared inputs without rebuilding. Generate concrete current-runtime/G0 candidates and use an existing valid independent approval if it already matches. Otherwise defer only timing pending reviewer approval; finish every independent safe task first.
8. **Acquire current data:** use a clean detached execution checkout at C and owned roots. Run one full cross-engine study and one full retained series, serially, through v2. Preserve checkpoints automatically. No replacement legacy series or mandatory fresh micro run. Stop/reap on real failure; no timed rerun.
9. **Analyze/verify/accept/report:** current statistics and controls first; historical input handling stays nonblocking unless it reveals a current defect. Reopen original qualification. No comparison against historical absolute A/B.
10. **Commit results and replay:** finalize/commit complete baseline data on the ordinary branch, verify a separate checkout offline, commit the separate replay receipt and append final evidence. Record measured source C separately from results/docs commit D. Confirm final remote head/CI; leave merge to the maintainer.

### 10.1 Supported local commands

Run these from the repository root using its installed Python/console. Do not add `-t benchmarks` to unittest discovery: some existing test modules use flat sibling imports; use the checked-in CI command.

```text
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v
python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py
python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de --check docs/pr-artifacts/bm-01/legacy-inventory.json
PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json
quervant-bench inspect --experiment synthetic-contract-smoke --format json
bash benchmarks/scripts/test-scripts.sh
```

Rust: execute `cargo +<stable> fmt --all -- --check`; `cargo +<toolchain> clippy --workspace --all-targets -- -D warnings` and the `--all-features` variant; `cargo +<toolchain> test --workspace` and `--all-features`, for stable and1.85.0; `cargo +<stable> doc --workspace --no-deps`; `cargo +<stable> bench --workspace --no-run`; `cargo +<stable> llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`. Resolve `<stable>` once from current CI/toolchain policy and record its concrete version. No Rust production edits are prescribed, but applicable whole-workspace coverage remains ≥85%; no selective-file substitution. Report ignored real-service tests separately and execute the named service acceptance below.

Use the exact U43 function u43_replacement_witness_all_variants in crates/quervant-core/src/search/unified.rs, not the unrelated mutation-state U43. Resolve its fully qualified module path from the test binary listing once; require exactly one selected test. Execute it in ten fresh processes on each toolchain with --exact --test-threads=1. Run the existing rf09_14_tests module (the delivered19 selectors) without dropping any restored E2 case; verify the listing count and named results. Re-run only to fulfil this gate or resolve a concrete risk, not to search for a green outcome.

RustFS topology: use the checked-in compose/service settings and pinned image. Prefer available Docker; if unavailable use observed Podman/compose as previously demonstrated. Own a unique project name and explicit container-name override, bind loopback/free ports, record health, then run the named real tests in `pr13_oracle`, `pr13_oracle_geo`, `m1_batches` with the CI feature/environment configuration. Require their named real tests actually executed, not a filtered zero-test exit. Redact credentials from logs. `down -v` only that project; verify zero owned containers/volumes/networks. Never global-prune unrelated resources. The checked-in CI service/job configuration is the exact supported command authority, not an improvised runtime invocation.

Do not run QA builds/services concurrently with timed acquisition. Stop only task-owned resources after QA. Current code/CLI itself, not prose or an unsupported shell flag, must select the new profile.

### 10.2 Public lifecycle after implementation

The existing supported command shapes are:

```text
quervant-bench prepare --experiment <study-id> --protocol <registered-v2-template> --out <fresh-build-root> --config <operation-v2.json>
quervant-bench run --experiment <study-id> --protocol <registered-v2-template> --out <approved-new-run-root> --config <operation-v2.json>
quervant-bench validate --run <run-uuid> --config <operation-v2.json>
quervant-bench analyze --run <run-uuid> --config <operation-v2.json>
quervant-bench verify --run <run-uuid> --config <operation-v2.json>
quervant-bench accept --run <run-uuid> --config <operation-v2.json>
quervant-bench report --run <run-uuid> --config <operation-v2.json>
quervant-bench verify --run <baseline-uuid> --offline
```

These become v2-capable only after this implementation and its dispatch tests. Placeholders are generated/observed identities from the concrete approved config, not text to paste literally. The agent creates these files from the prescribed closed schemas; the user need not supply code, patches or archives. Preparation can preserve completed builds while source QA is pending; repeating that untimed finalization must rehash, not rebuild. A failed timed run never follows this reuse rule.

## 11. Preauthorized decision matrix

Apply the first matching specific row. Record ID, observed condition, action, evidence and affected gate. AUTO resolves only the exact stated case. DEFER means continue independent work. Every unlisted semantic/architectural condition is M25.

| ID / observable trigger | Category | Authorized action; prohibited action | Evidence / affected gate / owner |
| --- | --- | --- | --- |
| M01 Clean branch behind its remote, ordinary fast-forward | AUTO | Fetch and ff-only update; never reset/force. | Start/remote SHAs; all stages; agent. |
| M02 Dirty/unpushed work belongs to another task, branch diverged or remote wrong | HARD STOP affected checkout | Preserve it; isolate only when identity is demonstrable. Never discard or merge blindly. | Status/ref/diff; source; maintainer. |
| M03 Later descendant contains unexpected production changes | HARD STOP affected design | Identify changed symbols/invariants; no silent plan retarget. Independent read-only inventory may continue. | Range diff; implementation; maintainer. |
| M04 Already delivered fix/test matches plan | AUTO | Preserve and regress; do not reimplement. | Source/test mapping; implementation; agent. |
| M05 Native Linux or WSL2 with complete required capabilities | AUTO | Use actual environment identity and approved CPUs/filesystem. | Capability/readiness record; host; agent. |
| M06 Socket creation denied, mandatory capability absent or unsupported collection platform | DEFER | Block affected local acceptance/acquisition; continue code/docs/read-only work. No skip or fabricated native label. | Exact error/host; host gate; host owner. |
| M07 Rust/Java/Gradle/profiler prerequisite missing | DEFER | Use supported project installation mechanism if already authorized/available; otherwise record blocked gates. Never claim partial scripts/coverage PASS. | Probe/exit/argv; QA; host owner. |
| M08 Old historical data absent after fixed search | AUTO | UNAVAILABLE; current baseline proceeds. No replacement legacy timing or prolonged search. | Bounded inventory; history disclosure; agent. |
| M09 Deterministic old receipt/derived output recoverable from authentic bytes | AUTO | Reproduce exact pinned bytes and verify; never invent past samples/approval. | Inputs/generator/digests; history; agent. |
| M10 Authentic summary with known ratio/method but raw absent | AUTO | AS_REPORTED effect; no rederived uncertainty/parity claim. | Source/digest/field mapping; report; agent. |
| M11 Historical artifact invalid/unverified or method incompatible | AUTO | Exclude numeric history, show status; continue valid current work. If a current defect is exposed, apply M22. | Validation error/context; history; agent/reviewer. |
| M12 Different environments across historical/current runs | AUTO | Compare compatible proportional effects with CONTEXT_CHANGED; no code-only attribution or absolute comparison. | Per-run identities; report; agent. |
| M13 Original T6 absent, explicit v2 current freeze fully validated | AUTO | Create fresh owned compatibility receipt/envelope per §5 and obtain bound G0. Never claim historical recovery/overwrite. | Exact roster/currentC/G0; acquisition; agent/reviewer. |
| M14 Existing T6/freeze/output path or mismatched current freeze | HARD STOP that run | Preserve; allocate a new owned checkout/identity only before timing under the same prescribed design. No overwrite or repair in place. | Paths/hashes; acquisition; agent. |
| M15 Micro/F1 unavailable and config policy_inputs=null | AUTO | Verify current slot effects; explicit policy NOT_EVALUATED, no selected strategy. No mandatory new micro run. | Missing inputs/positive baseline checks; baseline; agent. |
| M16 Supplied policy input invalid or mismatched | HARD STOP affected acceptance | Preserve and report; cannot silently treat as absent. Other family may proceed if isolated. | Reader/error/digests; policy/current integrity; reviewer. |
| M17 Current-source CI/log credentials unavailable (401/403) | DEFER | Use available authorized connector/REST read access; collect actual tested-source logs. Block SOURCE_QA/G0 if essential logs remain unavailable. No token printing or copied prior-head PASS. | Run/attempt/head/job/log status; QA; CI owner. |
| M18 Only PR merge M passed; C push evidence differs | AUTO / DEFER | Record PR head and tested merge separately; use exact C push proof where source QA requires C. Never relabel M as C. | Identity step/logs; CI/QA; CI owner if missing. |
| M19 Real G0 absent or stale after complete candidate preparation | DEFER | Finish independent work; request approval of concrete C/binaries/host/profile/roots. No self-approval or timing. | Candidate digests/needed reviewer action; acquisition; independent reviewer. |
| M20 Readiness/control/correctness/timed process fails | HARD STOP that run | Reap owned processes; preserve stopped evidence; no retries, thresholds changes or lane selection. | Raw/checkpoint/exit; current run; reviewer. |
| M21 Fewer than four symmetric retained blocks for a required lane | HARD STOP affected baseline acceptance | Preserve raw/diagnostics and typed insufficient-data BLOCKED; no invented partial-ratio schema or timed rerun. Other family may finish independently. | Retained counts/reference error; result/review; reviewer. |
| M22 Current calculation/provenance/test regression | HARD STOP affected qualification | Diagnose/fix within allowlist, rerun meaningful gates; a source change after C requires new C/QA/G0 before timing. | Red proof/root cause; correctness; agent/reviewer. |
| M23 Exactly identical completed preparation/checkpoint reopens | AUTO | Read-only verify/reuse. Never timed resume or overwrite a different payload. | Byte/digest identity; preparation/preservation; agent. |
| M24 Export unavailable/ignored/conflicting/secret-bearing or replay depends on producer path | HARD STOP publication | Preserve measurements; fix specified exporter before new timing if needed. No omitted member, secret commit or manual ZIP substitution. | Exact member/path; durability; agent/reviewer. |
| M25 Unlisted case, extra production path, protocol/method/source-pin change or broader relocation needed | HARD STOP affected work | Report file/symbol/observation/invariant and smallest required decision. Continue only demonstrably independent safe work. No improvisation/plan self-amendment. | Decision register; relevant gate; maintainer. |
| M26 Gates pass and only routine stage/commit checkpoint remains | AUTO | Continue automatically; normal commits/push and evidence collection. No renewed permission request. | Gate receipt/SHAs; all stages; agent. |

Classify failures as REGRESSION, PRE_EXISTING (with same-command baseline evidence), ENVIRONMENT_BLOCKED, FLAKY (with actual evidence) or UNCLASSIFIED. A green subset or retry is not a root-cause classification. Report unresolved failures explicitly.

## 12. Completion report and reviewer checklist

Report five separate outcomes: implementation, semantic correctness, local QA, hosted/source QA and real-baseline acceptance. Attach the invariant/test ledger and exact source/result/replay identities. State plainly:

1. Were both current benchmark families executed through the new framework? Give actual run IDs/statuses.
2. What within-run A/B proportional effects were observed, with applicable uncertainty/limitations?
3. Which authentic historical effects could be compared, which were AS_REPORTED, and which were unavailable/incompatible?
4. Are complete results committed and replayed from a clean checkout? Give Git path, manifest digest, evidence commit and replay receipt.
5. Is optimization policy evaluated or explicitly unevaluated? Do not confuse baseline validity with adoption.
6. Is BM-09 accepted under current-baseline-v2, or which actual required gate remains blocked?

Record pulled start, C, final remote head, main/merge base, runtime/profile/design/source/QA digests, exact CI run/attempt/PR-head/tested-commit mappings, applied matrix rows, limitations, owned-resource cleanup and `MERGED=NO`. Preserve separate native/WSL metadata. No process or owned service should be left running.

Only after all required current-baseline gates and independent review pass may active roadmap status change. Historical absence alone is not a reason to leave the new baseline blocked. The final instruction to the next agent is simply: **pull the latest PR branch, read this plan, and execute its remaining stages under the decision matrix.**
