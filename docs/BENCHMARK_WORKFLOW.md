# Benchmark framework: supported workflow and migration handoff

## Implementation boundary

The common `quervant-bench` operator surface now connects the two required
BM-09 real families to preparation, authorization, acquisition, raw admission,
analysis, independent verification, acceptance, publication and reopening.
The two synthetic references use the same closed stage executor with their
existing logical simulator and simulated qualification coordinator.

This is a source migration. It does not assert that a real campaign, authentic
historical replay, independent performance acceptance or v0.1-bench closeout
has occurred. The implementation task explicitly stops before benchmarking;
the execution agent owns those runs after this handoff.

The approved remaining acceptance contract is
[Benchmark migration acceptance](BENCHMARK_MIGRATION_ACCEPTANCE.md); the coding
agent's instructions are in [BM09_COMPLETION_PLAN.md](BM09_COMPLETION_PLAN.md).
Native Linux and WSL2 capability support, the explicit `current-baseline-v2`
execution path, current retained runtime freeze, complete result preservation
and offline replay are implemented. The execution agent must verify this source
on its full-capability host before obtaining G0 approval and measuring anything.
The existing v1 commands retain their T6, policy-input and historical-parity
requirements. Selecting v2 is explicit; a missing v1 input never selects it.

| Family | Supported experiment ID | Measurement implementation |
| --- | --- | --- |
| Retained-key / Top-K | `retained-key-topk-real-v1` | Frozen D3-C v3r3 primitives, two pinned source revisions, A/A plus both complete treatment campaigns |
| Cross-engine exact keyword | `cross-engine-keyword-real-v1` | Frozen PR15D Quervant/Tantivy/Lucene primitives, separate Quervant/Quervant A/A, all three trials and both cache regimes |
| Simulated retained-key reference | `synthetic-retained-key-reference` | Existing logical BM-03 simulator and BM-06 gate graph |
| Simulated cross-engine reference | `synthetic-cross-engine-reference` | Existing logical simulator, independent exact-answer contract and BM-06 gate graph |

Native Criterion targets remain native. Earlier diagnostic/profiling families,
immutable archives and original verifiers remain available through their
documented compatibility interfaces. BM-09's migration contract selects the two
representative families above; it does not require relocating or deleting every
historical directory. No legacy retirement is authorized by implementation alone.

## Approved current baseline and host support

For each required real family, execute one complete current run through the new
framework and preserve the results as a new baseline. Current-run correctness,
controls, provenance, independently verified calculations and QA remain required.
A second legacy acquisition and old/new analyzer equivalence are not required
acceptance gates. Use authentic or faithfully recoverable historical results
when available; otherwise record the gap and continue with current results.

Fresh measurements do not imply current-HEAD engine code. The retained method
still measures pinned BASE `39dbd9f571a58bea8cc03d5a406533298e809bfe` and experiment
`3ad6c5184fbe9c011abb731415a007e3f19d21de`. Report those source identities and the
actual cross-engine sources/binaries separately from the framework checkpoint.

Missing micro/F1 inputs do not prevent v2 measurement or baseline validity. They
leave the optimizer-selection policy `NOT_EVALUATED`, with no selected arm or
adoption claim. No fresh micro loop is required to establish this baseline.
The narrower baseline verification must not be labelled the existing full
`VERIFIED_REAL` policy result.

A and B name the experiment's baseline and treatment, not the legacy and new
runners. Performance results compare B with A within the same run, using its
frozen estimator, controls and balanced schedule. Across runs, discuss those
relative effects and their qualification; never compute old-A/current-A,
old-B/current-B, absolute old-A-minus-B/current-A-minus-B comparisons or
old-runner/new-runner latency ratios. Independently acquired absolute timings and
decisions need not match.

Comparison with a previous run's proportional A/B effect is supported and
used wherever comparable authenticated historical effects are available.
For a lower-is-better latency metric, a previous 20% reduction and a current 10%
reduction mean the treatment's relative advantage narrowed by ten percentage
points; neither implementation is thereby shown to have become slower in
absolute time. Match metric direction, baseline/treatment orientation, workload
and analysis method before comparing effects. Display both runs' actual host
environments and their own uncertainty/qualification. Missing comparable
historical effects are reported unavailable, not invented.

Relative effects reduce environmental variation but do not eliminate it: a host
or platform change may affect A and B differently. Keep the host/configuration
constant within each A/B run. Historical and current runs may use different
hosts or platforms; that difference does not by itself prohibit comparing their
proportional effects, but it must be visible and prevents attributing the change
to code alone. There is no mandatory legacy/new execution pair.

Both host classes must expose complete capabilities, allowed affinity on distinct
physical cores, approved Linux filesystems and passing live readiness. The actual
environment remains `native-linux` or `wsl2` in the observed G0 identity; the union
selector is not an observation and does not permit switching hosts after G0.
Readiness limits, filesystem restrictions, workloads and timing boundaries are
unchanged.

Native Windows collection is not implemented. Comparable historical effects
measured on Windows may be displayed when their provenance is valid, retaining
their Windows metadata. This reporting allowance does not authorize native
Windows acquisition or relabelling Windows evidence as Linux/WSL2.

The exporter preserves the complete baseline automatically under
`benchmark-results/baselines/<baseline-uuid>/`. One baseline UUID groups the two
family run UUIDs. Preserve raw observations, provenance, controls, analysis,
independent verification, every policy input actually used and the historical
availability ledger. Completion requires replay from a separate clean
checkout without the producer's ignored workspace. The existing fifteen-member
derived qualification bundle does not by itself satisfy that preservation test.

## Existing v1 operator surface

Install the package from this checkout using the repository's existing editable
installation. The module entrypoint is `python -m quervant_bench`; the installed
entrypoint is `quervant-bench`. Their command handling is identical.

New official inspection/preparation/results and configured synthetic results use
the version 2 `outcome` envelope. Its closed schema is shipped separately in
`config/operator_schemas/outcome.v2.schema.json`. Ordinary synthetic inspection
and CLI errors retain version 1. The frozen BM-01 v1 schema bytes and registry
remain unchanged; consumers must not relabel a new operator result as v1.

| Command | Required arguments | Behavior |
| --- | --- | --- |
| `inspect` | `--experiment`, optional `--format json` | Validate and describe a supported declaration; official output says `INDEPENDENT_G0_REQUIRED` |
| `prepare` | `--experiment --protocol --out --config` | Build adapters/corpus once, perform untimed correctness preparation, then finalize actual authorization inputs when current-source QA is available; no timing or approval |
| `run` | `--experiment --protocol --out --config` | Execute exactly one new authorized full series and seal admitted raw evidence |
| `validate` | `--run --config` | Re-open authorization and re-admit the sealed raw bytes |
| `analyze` | `--run --config` | Re-admit and derive the frozen analysis/policy |
| `verify` | `--run --config` | Re-admit, rederive and independently verify the analysis/policy |
| `accept` | `--run --config` | Execute the existing full A–E coordinator, require executed QA and independently approved parity, publish and reopen the exact bundle |
| `report` | `--run --config` | Recompute the acceptance inputs and verify the existing publication without creating a publication |

`--protocol` must have the same canonical content as the registered template in
this checkout. A copy is allowed; an edited protocol requires a separately
reviewed source/design change. For official runs, `--out` is exactly
`workspace/<G0-approved-run-uuid>`. Reusing an acquisition directory is refused,
including after interruption or a failed attempt. Stage commands can reuse only
byte-identical rederived output.

Preparation has one explicit continuation: if adapter/corpus preparation completed
but genuine QA is still missing or incomplete, the command reports
`BM_EVIDENCE_UNAVAILABLE` and preserves the prepared manifest and
`preparation-inputs.json`. It creates no `authorization-inputs.json`. After
collecting the required QA, repeat `prepare` with the same arguments. It rehashes
the completed inputs and checks their source, protocol, corpus and path identities;
it does not rebuild. An existing directory without both completion records is
partial evidence and cannot be reused. Once authorization inputs exist, only
byte-identical finalization is reusable.

Unconfigured `run` continues to refuse acquisition before opening inputs.
The established `--offline` synthetic reader remains available and cannot be
combined with `--config`. No command accepts a shell command, callable, plugin,
fixture-mode flag, retry count, skipped control or supplied PASS decision.

## Official operation configuration

Use a regular local JSON file with `kind` equal to
`official-operation-config` and integer `schema_version` equal to `1`.
Whitespace is allowed in configuration. All paths are normalized absolute paths;
links in the path are refused. The object is closed: include exactly these
fields, with `null` for the two optional input groups when not yet available.
Retained-key acquisition and `validate` may precede `policy_inputs`. Its
`analyze`, `verify`, `accept` and `report` commands require those authentic inputs
before writing derived records. A missing-input failure preserves the sealed raw
run; supply the inputs and invoke the stage again on that same run.

| Field | Meaning |
| --- | --- |
| `source_root` | The clean checkout executing the installed package |
| `workspace` | Owned parent of the raw operation directories |
| `output_base` | Separate approved publication base; never an ancestor/descendant of the raw workspace |
| `authorization_path` | Candidate authorization file that the existing independent G0 approval record approves |
| `approval_source_root` | Independent approval-record directory outside the repository, candidate directory and generated output roots |
| `approval_source_identity` | The approved semantic identity used to locate `<identity>.approval.json` |
| `prepared_manifest` | `prepared-cross-engine.json` or `prepared-retained-key.json` in the owned preparation directory |
| `corpus_dir` | Complete deterministic PR15D 10K/100K corpus; verify existing bytes or generate once during preparation |
| `framework_qa` | Current canonical official framework QA summary |
| `source_qa` | Current canonical official source QA summary |
| `qa_evidence_root` | Actual external executed-QA root required by the existing 66-member verifier; synthetic fixtures are not an official QA root |
| `adapter_cpu` | Nonnegative integer CPU ID |
| `controller_cpu` | Different CPU on a distinct physical core |
| `policy_inputs` | `null`, or the retained-key input object described below |
| `historical_parity` | `null`, or the historical input object described below |

The QA paths locate source-qualification evidence produced independently of the
pending campaign. Their records must match the actual source commit and source
set. The framework roster is exactly the 15 source-regression checks, including
`official-authorization-boundary` and `official-control-boundary`, which are
executed `hosted-ci`/`python-contracts` regression coverage of the authorization
and measured-control boundaries. They report that the source implements those
boundaries; they do not attest that a particular pending run is approved or that
its A/A control passed. Those remain runtime gates: the real independent G0
approval must open the run, and a failed readiness/control check stops the series
before any treatment campaign. This removes the first-run cycle in which QA asked
for the very approval and A/A measurement it was meant to precede.

QA records cannot be invented by copying the pending run's status or relabelling
the checked-in synthetic fixtures. Preparation checks summary/check identity
bindings; the production opener and acceptance coordinator additionally verify the
full 66-member evidence root and raw logs against the independently approved G0
pins.

Every official authorization names exactly one reviewed campaign sequence:
`cross-engine-keyword-real-v1` permits `["control", "treatment"]`, and
`retained-key-topk-real-v1` permits
`["d3c-v3r3-base-aa-01", "d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02"]`.
A control-only, treatment-only, reordered, duplicated, extended or other-family
list is rejected with `BM_IDENTITY_INVALID`/`permitted_campaign_order` while the
authorization is validated, before any output directory, readiness check, control
campaign or treatment campaign exists.

For retained-key, the frozen backend confines its artifacts to
`source_root/target/pr15i-d3-c`. Put both its preparation and raw workspace beneath
that namespace. The configured CPU pair must equal the frozen backend's
deterministic topology selection. The official publication still belongs under
`benchmark-results` or an approved external directory. For cross-engine, owned
preparation belongs under `target` or outside the repository, and the raw
workspace belongs under `benchmark-results` or outside the repository.

`policy_inputs` has exactly `micro_json`, `expected_micro_sha256` and
`f1_receipt`. The paths identify authentic input files, and the expected micro
digest is a `sha256:` digest of the actual input file. The reader requires the
complete 900-cell P2 table, the original pinned F1 receipt/source identities and
the same re-admitted series. It does not accept a precomputed selected strategy.

`historical_parity` has exactly `archive_root`, `mapping_path`,
`approval_source_root` and `approval_source_identity`. The independent mapping
approval record supplies the approved mapping digest. The cross-engine v1
mapping retains the full 1,440-row comparison. The retained-key v2 mapping
declares historical input paths relative to its archive root, three authentic
archive digests, raw/statistics/policy-input digests and all nine expected K rows.
Historical inputs are reconstructed separately from the newly measured series.
They cannot be promoted to official current-run inputs.

For D3-C historical replay, stage an intact copy of the authentic archives,
sidecars and verified loose series under an owned
`target/pr15i-d3-c/historical-replay` root. The original verifier retains its
target-path confinement. Neither the framework nor this migration fabricates
old T6/F1 receipts, raw measurements or historical mapping approvals.

## Execution agent's continuation sequence

The source implementation for Steps 2 through 6 is delivered together. The
execution agent's remaining work is full-host verification, genuine QA and G0
inputs, acquisition and replay. Do not reimplement the delivered modules or start
another partial v2 design. The detailed plan's scientific contracts and stop
decisions still apply. The following sequence is the continuation from this
source, not a request to repeat Step 1.

1. Fetch and pull the latest PR #110 branch changes using the detailed plan's
   clean-tree and fast-forward checks. Preserve the RF09/E2 repairs and frozen
   historical files. Do this before selecting the final execution checkpoint;
   never pull or modify the approved execution worktree during measurements.
2. Run the complete local acceptance gates below on the pulled source and review
   any unexpected failure before proceeding. A new retained runtime freeze has a
   fresh identity; its explicitly marked compatibility receipt uses the original
   helper's locator only in the new owned checkout and explicit v2 path. Never
   overwrite an existing receipt or describe this as recovery of the old T6.
3. Prepare the locked adapters and deterministic corpus, complete current-source
   local/hosted QA, and observe the actual native-Linux or WSL2 capabilities.
   Missing generated inputs are preparation work. Preserve completed preparation
   when QA is pending and use only the supported finalization continuation.
4. Obtain independent G0 approval of the concrete source, binaries, workload,
   host, roots and full execution sequence. The idle-host instruction establishes
   operator intent; live readiness and the frozen A/A controls still apply.
5. Execute one complete current run per required family through the new framework. Preserve
   successful and stopped raw results automatically. No sample copying, shortened
   campaigns, hidden retries or outcome-driven protocol changes are allowed.
6. Reopen and independently verify each current raw run and its calculations.
   Report the within-run treatment
   effects. An inconclusive or baseline decision is a valid result, not a reason
   to rerun until a favorable decision appears.
   Missing micro/F1 policy inputs produce `NOT_EVALUATED` and no adoption claim;
   they do not require extra acquisition or prevent a valid v2 baseline.
7. Use available or faithfully recoverable historical results, retaining their
   provenance and comparison limits. Mark absent history `UNAVAILABLE`, original
   ratios without raw rederivation `AS_REPORTED`, and incompatible effects
   `NOT_COMPARABLE`. Complete the versioned acceptance and the
   clean-checkout replay test for
   `benchmark-results/baselines/<baseline-uuid>/`. Do not substitute the
   current derived-only publication for the complete result set.
8. Finish independent review, final-source CI and the amended closeout predicates.
   Preserve unresolved limitations and the original legacy readers. Destructive
   legacy retirement and merge are separate actions.

This continuation uses repository commands and local inputs. It requires no
downloaded chat code, execution ZIP, externally supplied helper or parallel
implementation plan.

### Full-host verification handoff for Steps 2–6

The authoring environment can execute Python and filesystem integration tests.
It cannot create AF_UNIX sockets or provide the Rust, Java, adapter and service
environment needed for final local acceptance. These are execution gates for the
coding agent. Do not infer a full-host PASS from the authoring test count or from
an earlier commit's CI. The implementation evidence records the exact checks
actually run here. Authoring discovery was intentionally interrupted with exit
130 and remains incomplete; it is not a full-suite PASS. Final full-host
verification remains assigned to the coding agent.

1. In the ordinary PR branch checkout, require a clean tree, fetch `origin`, and
   pull `dev/bm09-real-qualification` with `--ff-only`. Record the complete local
   and remote SHAs, fresh main and merge base. If local work or divergence exists,
   preserve it and stop synchronization; do not reset, stash, rebase or force-push
   to manufacture a clean starting point.
2. Install this checkout's package in an owned environment with
   `python -m pip install -e ./benchmarks`. Record the interpreter and resolved
   console path. Run one complete Python discovery on the final source using the
   command below. Do not first run all focused official modules: that would
   duplicate the slow integration cases. Use the already listed bounded selectors
   only for targeted triage or rechecks; preserve the separately required genuine
   QA commands and repository gates.

   The retained selector
   `test_official_transport.TransportEndToEndTests.test_retained_checkpoint_finalization_and_complete_study_replay`
   contains 19 complete retained-verification passes. Observed passes took about
   3.5 minutes each on this authoring host, giving an estimated 60–70 minutes for
   this one case here. Its actual target-host duration has not been measured.
   Allow for that cost in the single discovery run; do not remove, skip or weaken
   the test or change CI to conceal it. This scheduling note assigns no additional
   code changes.
3. Probe an AF_UNIX socket in an owned temporary directory, clean it up, then run
   the existing named socket test unchanged. `EPERM` on the authoring host is a
   sandbox capability limit, not a WSL2 defect. If the execution host also denies
   it, record `ENVIRONMENT_BLOCKED` and obtain a capable host; do not mock, skip or
   weaken the case.
4. Execute current-source Rust and owned-service acceptance below. Record exact
   toolchain, argv, count, exit and ignored/skipped tests. Do not replace complete
   workspace coverage with coverage of selected files. Do not infer executed
   RustFS acceptance from ignored tests.
5. Pin `C` to the complete SHA of the clean, freshly pulled and pushed source
   actually being verified and executed. If the author published an implementation
   commit followed by an evidence/docs commit, use the pulled final head, not an
   unpushed intermediate implementation checkpoint. Source equivalence does not
   turn another commit's CI into exact-head QA. Any necessary reviewed source
   correction must be committed, pushed and pulled before choosing the new `C`,
   with the required acceptance gates rerun on that source.
   Complete exact-`C` push CI and PR merge CI; preserve their different tested
   identities. Require `python-contracts`, `rust`, `msrv` and `rustfs`, including
   each job's `Record tested source identity` step, to succeed for both events.
   Dispatch the full comparative check below while the remote branch still names
   `C`. Do not request logs for an intermediate commit with no run.
6. Create a separate detached execution worktree at `C`, install its package in
   its own environment, and establish the fixed v2 directory layout below. Keep
   an ordinary branch checkout descended from `C` for committable evidence. Its
   only subsequent changes may be documentation and `benchmark-results/`.
   Do not pull, switch or edit the detached checkout during preparation, G0,
   acquisition or stage reopening; only owned ignored build/raw files may grow.
7. Run untimed `prepare` for both families at `C` before completing their local
   QA observations. If QA is unavailable, preserve the completed manifests and
   `preparation-inputs.json`. Then assemble all 33 genuine executed-QA records and
   33 logs for `C`, including `host-capability-readiness` and
   `source-binary-digests` from this host and both actual prepared manifests.
   CI metadata without downloadable logs cannot become sealed executed QA.
   Missing credentials are an input/access blocker, not permission to invent
   transcripts. Keep summaries outside the exact 66-member evidence root.
8. Repeat the same `prepare` commands only to finalize the unchanged inputs after
   QA is complete. Review the resulting actual identities with the independent
   G0 reviewer, obtain the real approval records, and only then execute the two
   families serially. The host is assumed idle and ready; live readiness and A/A
   control checks still run before treatment. Finish all QA before timing starts.

The supported Python gates are:

```sh
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v
python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py
python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de --check docs/pr-artifacts/bm-01/legacy-inventory.json
PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json
quervant-bench inspect --experiment synthetic-contract-smoke --format json
PYTHONPATH=benchmarks python -m unittest quervant_bench.tests.test_evidence_paths.PathValidationTests.test_path_04_fifo_directory_and_socket_are_rejected -v
bash benchmarks/scripts/test-scripts.sh
```

Do not add `-t benchmarks` to discovery; existing test modules use their supported
flat sibling imports. Resolve the stable Rust version from the checked-in CI
policy and record it; the preceding verified host used 1.98.1. Also use the
declared MSRV, 1.85.0. On both toolchains run `fmt --all -- --check`, workspace
clippy with all targets and `-D warnings`, and workspace tests, with default and
all features. On stable also run all-feature workspace rustdoc, `bench --no-run`
and `llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`.
Keep the 19 delivered RF09-14 tests and the existing U43 ten-fresh-process checks
per toolchain. Run the three named real RustFS suites (`pr13_oracle`,
`pr13_oracle_geo`, `m1_batches`) with the existing owned Docker/Podman topology,
pinned image and cleanup rules; preserve the named real-test results.

The comparative QA requires the `comparative-full-correctness` job, not the smoke
job. With the authenticated CI account and the remote branch still exactly at
`C`, use the existing workflow's explicit boolean input:

```sh
gh workflow run comparative-adapters.yml --repo yduchesne/quervant --ref dev/bm09-real-qualification -f full_correctness=true
```

Record the resulting run ID, `workflow_dispatch` event, complete head SHA `C`,
successful `comparative-full-correctness` job and its genuine downloadable logs.
The default `full_correctness=false` runs smoke only. A labelled-PR run is merge
integration evidence and is not a substitute for exact-`C` QA; the workflow's PR
path filter can also prevent a label event from creating a run. If dispatch,
exact-head selection or log access is unavailable, retain the prepared inputs
and report the CI-owner gate. Do not reset a branch, make a dummy source edit or
relabel another head's evidence. Do not run QA and timing concurrently or change
toolchain policy to hide an adapter build failure.

### V2 configuration and preparation

Use one baseline UUID4 shared by the two families and a distinct run UUID4 for
each family's G0 authorization. Keep the experiment IDs unchanged:

| Experiment | Registered v2 protocol |
| --- | --- |
| `cross-engine-keyword-real-v1` | `benchmarks/official-protocols/cross-engine-keyword-v2.json` |
| `retained-key-topk-real-v1` | `benchmarks/official-protocols/retained-key-topk-v2.json` |

The v2 configuration has all the v1 fields listed above except
`historical_parity`, sets integer `schema_version` to `2`, and adds exactly:

| Field | Required value |
| --- | --- |
| `acceptance_profile` | `"current-baseline-v2"` |
| `baseline.baseline_id` | The shared canonical UUID4 |
| `baseline.evidence_root` | Absolute path to the ordinary evidence checkout's `benchmark-results/baselines/<baseline-uuid>` |
| `baseline.history_inventory` | Absolute path to the closed historical location inventory; an empty candidate list is valid when no sources are available |
| `baseline.runtime_freeze_path` | `null` for cross-engine; an owned absolute JSON path for retained-key, produced by `prepare` |

`baseline` contains exactly those four keys. It is not an approval or a list of
expected PASS results. Historical candidates are authenticated by the fixed
catalog; a declared digest cannot authenticate itself. A shared inventory may
list both families; each study's disclosure includes only its own candidates.
Do not manufacture missing historical input files. A missing or invalid historical
candidate is disclosed and excluded from numeric history without blocking a valid
current baseline.

Keep `policy_inputs=null` when authentic retained micro/F1 inputs are unavailable;
the baseline will explicitly report `NOT_EVALUATED`. Cross-engine requires both
`policy_inputs` and `baseline.runtime_freeze_path` to be null. The existing v1
configuration remains strict and does not accept these v2 fields.

Use this single layout for v2. `C_CHECKOUT` is the detached execution worktree at
`C`; `EVIDENCE_CHECKOUT` is the separate ordinary branch checkout descended from
`C`. `TASK` is the new owned absolute directory
`/var/tmp/quervant-bm09-<baseline-uuid>`, outside both checkouts. Every path must
be normalized, free of symlinks and on an approved Linux filesystem. Select the
existing deterministic CPU pair on distinct physical cores. On native Linux or
WSL2, a Windows-mounted path is not an equivalent Linux path.

| Input or output | Prescribed absolute location |
| --- | --- |
| Both configs | `TASK/config/cross-engine-v2.json` and `TASK/config/retained-key-v2.json` |
| QA evidence root for both configs | `TASK/qa/evidence` |
| Framework/source QA summaries | `TASK/qa/framework-qa-evidence.json` and `TASK/qa/source-qa-evidence.json` |
| Candidate authorizations | `TASK/g0/candidates/cross-engine.json` and `TASK/g0/candidates/retained-key.json` |
| Independent approval root | `TASK/g0/approvals` (a sibling of the candidate directory) |
| Shared corpus | `TASK/corpus`; leave absent for generation or supply the complete verified existing corpus |
| Cross-engine `prepare --out` | `C_CHECKOUT/target/bm09/<baseline-uuid>/prepared/cross-engine` |
| Cross-engine `prepared_manifest` | The preceding directory's `prepared-cross-engine.json` |
| Cross-engine `workspace` | `TASK/runs/cross-engine` |
| Cross-engine `output_base` | `TASK/qualified/cross-engine` |
| Retained-key `prepare --out` | `C_CHECKOUT/target/pr15i-d3-c/current-baseline/<baseline-uuid>/prepared` |
| Retained-key `prepared_manifest` | The preceding directory's `prepared-retained-key.json` |
| Retained-key `workspace` | `C_CHECKOUT/target/pr15i-d3-c/current-baseline/<baseline-uuid>/runs` |
| Retained-key `output_base` | `TASK/qualified/retained-key` |
| Retained-key runtime envelope | `TASK/runtime/retained-key-current-freeze.json` |
| Historical location inventory | `TASK/history/inventory.json` |
| Both configs' `baseline.evidence_root` | `EVIDENCE_CHECKOUT/benchmark-results/baselines/<baseline-uuid>` |
| Execution/replay Python environments | `TASK/venv-execution` and `TASK/venv-replay`, each installed from its own checkout |

The QA evidence directory contains exactly the registered 33 record files at
`<gate>/<check-id>.json` and 33 log files at `logs/<gate>/<check-id>.log`; summaries
and other task records belong outside it. The production QA opener rejects a QA
root anywhere under `C_CHECKOUT`, including ignored `target`. Cross-engine raw
files and both publication outputs stay outside `C_CHECKOUT` because creating
them under its unignored `benchmark-results` would invalidate its clean-source
check. Only retained raw/build files use the frozen backend's required ignored
`target/pr15i-d3-c` namespace. The ordinary evidence checkout's baseline directory
must be committable and unignored. Preserve the sibling locations shown for QA,
G0, raw and qualified outputs; the earlier v1 location choices do not replace
this v2 layout.

Invoke the existing `prepare` command once per family, using the table's exact
build root and matching config. Paths below are placeholders for those absolute
locations, not additional command options:

```text
quervant-bench prepare --experiment cross-engine-keyword-real-v1 --protocol <C_CHECKOUT>/benchmarks/official-protocols/cross-engine-keyword-v2.json --out <C_CHECKOUT>/target/bm09/<baseline-uuid>/prepared/cross-engine --config <TASK>/config/cross-engine-v2.json
quervant-bench prepare --experiment retained-key-topk-real-v1 --protocol <C_CHECKOUT>/benchmarks/official-protocols/retained-key-topk-v2.json --out <C_CHECKOUT>/target/pr15i-d3-c/current-baseline/<baseline-uuid>/prepared --config <TASK>/config/retained-key-v2.json
```

These commands build and verify inputs without timing. Do not pre-create their
`--out` directories: an existing incomplete preparation directory is refused.
Retained preparation writes a new marked current runtime receipt and the bound
runtime envelope; it does not recover the old T6. Its protected source roster,
prepared binaries, corpus, host and schedules are rechecked at later worker
barriers. If QA is not yet complete, preserve the successful preparation and
repeat exactly the same `prepare` only to finalize its identities after genuine
QA arrives. Do not rebuild completed preparation or repair a partial receipt pair.

Review the resulting twenty actual observations and source/binary/host identities
with the independent G0 reviewer. The candidate uses the v2 authorization contract;
the independent approval record keeps its existing schema 1 envelope. Acquisition
opens that real record through the existing approval factory. The operator must
not approve its own candidate, substitute a test capability or copy approved
observations from a different run. Source, CPU, host, roots or prepared-byte
changes require a new concrete review before any new attempt.

### Execute, preserve and replay the current results

Use only the existing public lifecycle with each approved run identity:

```text
quervant-bench run --experiment <study-id> --protocol <registered-v2-template> --out <workspace/run-uuid> --config <operation-v2.json>
quervant-bench validate --run <run-uuid> --config <operation-v2.json>
quervant-bench analyze --run <run-uuid> --config <operation-v2.json>
quervant-bench verify --run <run-uuid> --config <operation-v2.json>
quervant-bench accept --run <run-uuid> --config <operation-v2.json>
quervant-bench report --run <run-uuid> --config <operation-v2.json>
```

There is no `inspect --profile`, `--skip-build`, control-only command, shorter
timing profile or manual PASS option. Run the two families serially. The complete
control/treatment workloads and engine revision pins are unchanged. Retained
`NOT_EVALUATED`, a descriptive cross-engine `INCONCLUSIVE`, an unfavorable effect
or insufficient symmetric retained blocks never authorizes a timed retry. Preserve
the result and report the exact applicable gate.

The implementation copies immutable raw evidence immediately after control,
cross-engine treatment and each retained campaign. It writes stopped checkpoints
on acquisition failure and preserves the primary error if export also fails.
Successful qualification adds the provenance, genuine QA, original qualification
records, disclosures and used policy inputs. The second family qualification
finalizes the complete baseline manifest. `PRESERVED` means the inventory was
sealed; it is not a clean-checkout replay result. Build trees, binaries, indexes
and corpus payloads are excluded. Their source pins, recipes and expected hashes
are retained, as are the task-owned published retained archives. Credentials
cannot enter preserved records; a sealed secret-bearing input must be corrected
at its proper owner, not silently redacted during transport.

Commit the preserved directory in the ordinary evidence checkout, producing `D`
descended from measured source `C`. Create a separate clean checkout at `D`,
install its package in `TASK/venv-replay`, and invoke the console from that
environment, not the environment installed from `C`. Clear any inherited offline
workspace override so the default is this checkout's own `benchmark-results`:

```sh
unset QUERVANT_BENCH_OFFLINE_WORKSPACE
```

Make the original producer workspace, private HOME and corpus unavailable to that
replay process. The reader regenerates only deterministic corpus data, creates
confined temporary working views, runs the unchanged original
validators and independently rederives statistics/effects. It does not build
adapters, start services, read producer absolute paths or perform measurements.

```text
quervant-bench verify --run <baseline-uuid> --offline
```

This writes a separate replay receipt below `benchmark-results/replays/` only
after both family replays pass. The clean checkout is consequently dirty by that
new receipt. Commit the receipt before invoking the offline report or another
offline verification; do not weaken the clean-checkout predicate or delete the
receipt to satisfy it. Preserve the receipt's actual evidence-commit identity.

The terminal manifest is
`benchmark-results/baselines/<baseline-uuid>/baseline-manifest.json`; the separate
replay receipt is
`benchmark-results/replays/<baseline-uuid>/<replay-uuid>.json`. Use the actual IDs
and paths printed by the CLI. Commit only the exact owned baseline subtree and
the exact owned replay receipt path; do not infer a filename or include another
baseline's results.

```text
quervant-bench report --run <baseline-uuid> --offline
```

The original baseline manifest, measured identities and attestations remain
unchanged. Report within-run A/B proportional effects and cross-run percentage
point changes only. Finally obtain CI at the final evidence head and independent
review. Steps 4–6 are not complete merely because their implementation exists;
their actual executed gates, G0 approval, two current runs and replay receipt are
the completion evidence. Step 7 reconciliation and merge remain separate actions.

## Fixed decisions and stop conditions

| Observed condition | Required behavior |
| --- | --- |
| Missing generated corpus or adapter build | Run untimed `prepare` in a fresh owned directory |
| Unsupported host, dirty checkout, protocol mismatch or unsafe preparation path | Fail before building or measuring; correct the concrete input and start preparation in a valid location |
| Successful preparation but QA summary/check record missing, incomplete or stale | Preserve completed inputs, emit no authorization inputs; obtain genuine current-source QA and repeat the same `prepare` to rehash/finalize without rebuilding |
| Existing valid completed preparation | Rehash fixed manifest and verify source/protocol/corpus/path bindings; only identical authorization-input bytes may be reused |
| Existing partial preparation or any existing acquisition output | Preserve it; do not overwrite, rebuild or resume; use a fresh path/approved run identity as applicable |
| Missing independent G0 approval | No acquisition; report the exact missing record |
| Original retained T6 receipt is absent | Existing v1 remains strict. V2 uses its own verified current runtime freeze and explicitly marked backend compatibility receipt in a new owned checkout; never overwrite or claim recovery of the original |
| Prepared source, binary, runtime jar or corpus changed | Refuse acquisition; regenerate/review affected identities before a new approved attempt |
| Live readiness or A/A control fails | Stop this attempt, preserve partial evidence and diagnostics; no treatment |
| Actual rebuilt retained executable differs from the G0-prepared bytes | Stop before any index/query primitive; preserve the build evidence |
| Adapter/worker exits, times out or is interrupted | Terminate only owned descendants, record terminal failure, and stop; no hidden retry |
| Raw samples, control, policy inputs or stage output changes after sealing | Reject the stale result; never edit the old receipt to make it pass |
| Required retained-key policy inputs are absent | Current v1 remains strict. V2 can verify current baseline observations with policy `NOT_EVALUATED`, no selected arm and no adoption claim; no mandatory new micro run |
| Historical input or mapping approval is absent | Current v1 remains strict. For current-baseline-v2, record the unavailable history and continue; do not claim historical PASS |
| Historical candidate is invalid, unverified or not comparable | Preserve its status and exclude it from quantitative history. Investigate any defect affecting current calculations; only such a current correctness issue blocks current acceptance |
| Complete committable result cannot be replayed from a clean checkout | Do not claim migration completion; preserve partial output and report the missing member or dependency |
| Independent verification of current calculations differs | Stop current acceptance; retain both values for review |
| Proposed exception is outside these contracts | Stop the affected path and obtain a reviewed decision; do not invent a fallback |

## Source identity of hosted QA and executions

Hosted CI retains its ordinary pull-request integration behaviour: the checkout is
the tested merge commit `M`, and the PR head `C` is recorded separately. Official
executed-QA records are bound to `C`, so the workflow also runs on a push to
`dev/bm09-real-qualification`. Each job's first step after `actions/checkout@v4`
is `Record tested source identity`, which logs `event`, `event_sha`, the PR head
(when present), the actual checkout commit and the actual checkout tree, then
fails if the checkout commit differs from the event SHA. A push run of `C`
therefore proves the exact source; a pull-request run remains integration evidence
and is never relabelled as an execution of `C`.

Real acquisition uses one immutable execution checkpoint `C` in its own detached
worktree and its own environment. After that checkpoint is approved for
execution, the execution worktree is never pulled, switched, committed or
rebased; documentation continues in the ordinary branch checkout.

## Internal ownership and preserved semantics

`execution/operator.py` owns closed, ordered stage execution. `official/workflow.py`
owns real operation configuration, persisted progression and stage reopening.
`official/acquisition.py`, `cross_engine_backend.py`, `retained_backend.py` and
`retained_acquisition.py` bridge the existing measurement implementations.
The original timing primitives, deterministic workload generators, engine pins,
lane matrices and legacy verifiers remain the measurement/compatibility basis.

Production authorization still comes only from `VerifiedOfficialAuthorization`;
admission comes only from the production admission factories. Gate C retains the
RF09 exact-family guard, canonical control comparison, full-record equality and
fresh re-admission. New operator observations are computed from actual files and
the executing host, never copied from the candidate authorization.

The retained-key policy is versioned separately from the existing descriptive
analysis. It reconstructs the old T7/F2 symmetric within-block exclusions, floor
pair means, ordinary retained-block medians, exact bootstrap seeds/draws and
nine-K decision chain. `policy_reference.py` independently recomputes the same
result without importing the primary analysis implementation. Mixed per-K
decisions are represented explicitly; they are not collapsed into a global
winner. Ties and baseline-only decisions do not acquire a speedup claim.

The historical readiness reader understands the unchanged seven-snapshot D3-C
format and recomputes its settling, interval, busy/steal and lower-median checks.
Raw admission accepts the actual legacy count/median summary shape and verifies
optional extrema if present. Build/index working trees are excluded at every
inventory depth; admitted evidence, prepared executables and source identities
retain their separate byte bindings.

## Validation boundary

The migration is verified with deterministic unit/integration tests, logical
synthetic execution, real filesystem reads/writes, parser/record compatibility,
independent policy/reference agreement and controlled failure injection.
Acquisition-boundary tests substitute adapter execution; they do not claim real
engine performance or authentic historical parity. The implementation report
records exact executed checks. Timed benchmarks, service qualification and final
real-performance acceptance are the continuation agent's work.

Reverting the migration operator changes restores the previous direct legacy
entrypoints. Existing historical bytes and previously published evidence remain
unchanged and interpretable. Keep new operation/evidence directories for audit;
rollback never deletes a failed or completed run.


## Earlier checkpoint record (18 November 2026)

The following records the pre-amendment checkpoint, not the current host-support
or historical-availability acceptance rule.

The three pre-execution corrections are implemented and verified at checkpoint
`b2eb2878` (C-F01 QA roster, C-F02 exact campaign order, C-F03 exact-source CI).
Local and hosted gates are green at that checkpoint. Real acquisition remains
blocked: the benchmark host is WSL2 (rejected by the official host contract), the
authentic retained T6/micro/F1 inputs and the corrected PR15D archive are absent,
hosted job logs are not readable without repository admin rights, and no
independent G0 approval exists. `closeout_status` therefore returns `BLOCKED` with
ten unmet predicates; see the BM-09 verification report for the full matrix.

## Current continuation status (19 November 2026)

Native Linux and WSL2 capability support is implemented locally, with the actual
host identity bound to G0 and unchanged readiness/filesystem requirements. WSL2
classification alone is no longer a rejection reason. The `current-baseline-v2`
runtime, baseline acceptance and complete committed-result exporter are now
implemented under [BM09_COMPLETION_PLAN.md](BM09_COMPLETION_PLAN.md). Full-host
verification, real G0 approval, both current acquisitions and clean-checkout
replay of their preserved results remain execution work. Source tests do not
establish those results or BM-09 closeout.


## Proportional effects and bounded history (19 November 2026)

`quervant_bench/official/relative_effects.py` projects validated results into
normalized effect rows instead of comparing absolute times across runs. It is a
projection, not an estimator: retained-key rows come from the existing paired-slot
statistics and cross-engine rows from the existing descriptive comparison table.
Each row carries the study/run/campaign/lane/metric/unit/regime, the arm roles, the
method identity, the canonical ratio, the signed `gain_percent`, the existing interval when
one exists, the decision and evidence level, source/host identities and the input
digest.

For lower-is-better latency, the ratio is treatment divided by baseline. A ratio of
1.2 means 20% higher latency and `gain_percent = -20`. Across runs, compare the
current gain with the historical gain by subtraction in percentage points; do not
compare historical and current absolute timings.

Cross-run comparisons bind only rows with matching workload coordinates, metric,
unit, direction, arm roles and estimator, and report
`effect_change_percentage_points = current_gain - historical_gain`. A platform or
source difference makes the pair `CONTEXT_CHANGED`, not a rejection and not a
code-only regression; changed semantics, estimator or arm roles make it
`NOT_COMPARABLE` with a null change. No row or comparison carries an absolute
time, so absolute A-minus-B differences across runs cannot be read off the report.

`quervant_bench/official/history.py` turns historical evidence into a bounded
disclosure. Its input is a closed location inventory (never a PASS list); each
candidate is authenticated against the fixed supported-source catalog and recorded
as `FOUND`, `UNAVAILABLE`, `INVALID`, `UNVERIFIED` or `NOT_COMPARABLE` with a reason.
An input's declared digest is an assertion to check, never its own authority.
Frozen retained archive digests are enforced, so byte-mismatched archives are
rejected rather than used. Derived documents with an independent digest are shown
`AS_REPORTED`; they never become a recomputed comparison, and no historical PASS
can be minted. `open_verified_baseline_disclosures` reopens
`history-report.json` and `relative-effects.json` from the operation root and
binds them to the baseline, study, source commit and current raw digest.

The v2 disclosure factory now independently reopens authorization, raw admission
and baseline verification before constructing its capability. A reader cannot
promote a caller-provided row or a correctly shaped JSON file into verified
current evidence. The transport reader uses authenticated original records and
fixed working-copy relocations; it does not mint production authorization or
admission capabilities during offline replay.
