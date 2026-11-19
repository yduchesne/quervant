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

## One operator surface

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

1. Continue from the migration commit on PR #110. Preserve the RF09/E2 engine
   repairs, historical protocol bytes and frozen source identities. Inspect the
   real experiment with the normal CLI and read its registered protocol.
2. Locate current executed QA summaries and their real external evidence root.
   Recover the authentic retained T6 receipt and historical inputs from the
   existing host/repository evidence locations. Missing generated corpus or
   adapter binaries are preparation work; use `prepare` to create them. The
   configured QA paths may still be missing at this preparation step; they are
   mandatory before authorization inputs can be finalized or acquisition starts.
3. Choose task-owned paths and the actual allowed CPU pair in the operation
   configuration. `prepare` uses existing locked Cargo/Gradle sources and the
   deterministic corpus generator. Cross-engine preparation runs the established
   two-size untimed correctness smoke. It writes the completed prepared manifest
   and source-bound `preparation-inputs.json`. If QA is unavailable, preserve that
   preparation, obtain the required genuine QA records and logs, and repeat the
   same command to finalize without rebuilding. Finalization writes
   `authorization-inputs.json` containing independently observed source, binary,
   corpus, protocol, schedule, host and QA identities. A partial preparation never
   takes this continuation path.
4. Complete the existing G0 review using those concrete identities. An
   authorization candidate must include the real run UUID, permitted campaign
   order, zero measurement retries and genuine operator/reviewer metadata.
   The separate approval record must approve that exact candidate digest.
   Preparation and inspection never manufacture this approval.
5. Execute `run` for each required family through the configured CLI. The user's
   idle-host instruction establishes operator intent; live readiness and the
   frozen A/A control still run. Every failed attempt remains preserved. Do not
   retry a failing campaign under the same identity or relax its protocol.
6. Invoke `validate`, `analyze` and `verify` for each sealed run. Supply the
   authentic retained-key policy inputs before its positive verification gate.
   A valid inconclusive or baseline policy is a result; no favorable performance
   outcome is required or invented.
7. Complete the authentic historical comparisons under independently approved
   mappings, then `accept` and `report`. Each stage reopens the raw bytes and
   reconstructs its authority; report additionally compares the reopened
   publication with the freshly derived manifest.
8. Complete independent performance disposition, required final-head CI and
   reviewer acceptance. Only then apply the existing itemized legacy-disposition
   and BM-09 closeout gates. Merge remains a separate repository action.

This continuation uses repository commands and local inputs. It requires no
downloaded chat code, execution ZIP, externally supplied helper or parallel
implementation plan.

## Fixed decisions and stop conditions

| Observed condition | Required behavior |
| --- | --- |
| Missing generated corpus or adapter build | Run untimed `prepare` in a fresh owned directory |
| Unsupported host, dirty checkout, protocol mismatch or unsafe preparation path | Fail before building or measuring; correct the concrete input and start preparation in a valid location |
| Successful preparation but QA summary/check record missing, incomplete or stale | Preserve completed inputs, emit no authorization inputs; obtain genuine current-source QA and repeat the same `prepare` to rehash/finalize without rebuilding |
| Existing valid completed preparation | Rehash fixed manifest and verify source/protocol/corpus/path bindings; only identical authorization-input bytes may be reused |
| Existing partial preparation or any existing acquisition output | Preserve it; do not overwrite, rebuild or resume; use a fresh path/approved run identity as applicable |
| Missing independent G0 approval or authentic retained T6 receipt | No acquisition; report the exact missing record |
| Prepared source, binary, runtime jar or corpus changed | Refuse acquisition; regenerate/review affected identities before a new approved attempt |
| Live readiness or A/A control fails | Stop this attempt, preserve partial evidence and diagnostics; no treatment |
| Actual rebuilt retained executable differs from the G0-prepared bytes | Stop before any index/query primitive; preserve the build evidence |
| Adapter/worker exits, times out or is interrupted | Terminate only owned descendants, record terminal failure, and stop; no hidden retry |
| Raw samples, control, policy inputs or stage output changes after sealing | Reject the stale result; never edit the old receipt to make it pass |
| Authentic retained-key policy inputs are absent | Keep acquisition/validation available; fail analysis and later stages before writing derived records. Supply the inputs and continue the same sealed run |
| Historical input or mapping approval is absent | Preserve current-run progress; historical acceptance/publication/closeout remain blocked |
| An independent exact comparison differs | Stop the affected acceptance path; retain both values for review |
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


## Current status (18 November 2026)

The three pre-execution corrections are implemented and verified at checkpoint
`b2eb2878` (C-F01 QA roster, C-F02 exact campaign order, C-F03 exact-source CI).
Local and hosted gates are green at that checkpoint. Real acquisition remains
blocked: the benchmark host is WSL2 (rejected by the official host contract), the
authentic retained T6/micro/F1 inputs and the corrected PR15D archive are absent,
hosted job logs are not readable without repository admin rights, and no
independent G0 approval exists. `closeout_status` therefore returns `BLOCKED` with
ten unmet predicates; see the BM-09 verification report for the full matrix.
