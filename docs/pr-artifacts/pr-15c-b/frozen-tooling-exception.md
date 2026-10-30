# Frozen-tooling exception — PR 15C-B A-R2 profiler-evidence correction

Status: **approved exception, narrowly scoped.** Authorised by the human-issued
directive `QUERVANT_PR15C_B_A_R2_PROFILER_EVIDENCE_FIXUP_PLAN.md`
(decision **A-R2**, which resolved `STOP-15CB-02`). Append-only: this document
records what is exempt from the PR 15B benchmark-tooling freeze and what is not.

## 1. Why an exception is needed

`docs/pr-artifacts/pr-15c-b/decisions.md` → `STOP-15CB-01` / `STOP-15CB-02`
established, with code evidence, that the frozen PR 15B trial validator and runner
cannot emit a *qualified* trial on a host that has a profiling tool on `PATH`:

- `validate-pr15b.py::validate_trial` requires a non-empty `profiler_evidence`
  whenever `profiler_status` is `AVAILABLE` (unchanged rule);
- `validate-pr15b.py::build_trial` hardcoded `"profiler_evidence": None`;
- the `trial` subcommand exposed no input for it.

No change confined to `run-pr15b.sh` can satisfy that rule without suppressing
profiler discovery or forking the manifest builder — both forbidden. A-R2
therefore authorises exactly one additive input plus one manifest assignment.

## 2. Exactly what is exempt

| File | Exempt change | Everything else frozen |
|---|---|---|
| `benchmarks/scripts/validate-pr15b.py` | `trial` gains an optional `--profiler-evidence` argument (`default=None`), and `build_trial` assigns `args.profiler_evidence or None` to the existing `profiler_evidence` key | The `AVAILABLE ⇒ non-empty evidence` rule, the `UNAVAILABLE` branch, profiler **discovery**, every other field, every other rejection rule, the manifest schema, the lane list, the aggregation rules and the self-test are unchanged |
| `benchmarks/scripts/run-pr15b.sh` | The per-trial profiler-evidence capture → record → verify → CLI wiring described in §3 | The `cargo bench -p quervant-core --bench unified_diagnostics` command, the `CRITERION_HOME` isolation, the three-trial default, the contention gates, the `--idle-confirmed` gate, the aggregate step, the exit codes and the fixture-digest check are unchanged |
| `benchmarks/scripts/pr15cb-profiler-evidence.py` | New helper that writes/re-verifies the evidence record | It never mints a trial manifest and never contacts the validator |
| `benchmarks/scripts/test-scripts.sh` | New AR2 regression section | No existing assertion relaxed or removed |
| `.gitignore` | Ignores `__pycache__/` and `*.pyc` | — |
| `benchmarks/reports/.gitignore` | Adds `!*/` so the existing `!*.md` / `!*.json` negations apply inside `benchmarks/reports/<subdir>/` (a directory excluded by `*` is never traversed, so the plan's `benchmarks/reports/pr15c-b/` layout was otherwise untrackable). Raw artifacts, profiler binaries and Criterion trees remain ignored | — |

## 3. Not exempt (explicitly unchanged)

- The validator's acceptance rule and profiler-discovery logic.
- `benchmarks/workloads/pr15b_v1.md`, the 30 mandatory lane identifiers and the
  `pr15a_v1` corpus (`sha256 104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087`).
- Criterion settings: `sample_size(20)`, 3 s warm-up, 5 s measurement,
  `Throughput::Elements(1)`; every timed region.
- `benchmarks/scripts/profile-pr15b.sh` (byte-identical to `origin/main`, asserted
  by AR2-T08).
- `benchmarks/scripts/capture-pr07-env.sh`, `check-pr07-contention.py`.
- `benchmarks/reports/pr15b-*` (the source-locked PR 15B evidence).
- The CI coverage floor, production `quervant-core` code, dependencies, and the
  causal engine SHAs.

## 4. Proof the validator rule was not modified

The test suite reconstructs the pre-patch validator by inverting *only* the two
approved hunks and asserts that re-applying them round-trips to the current file
byte-for-byte (AR2 counterexample gate in `benchmarks/scripts/test-scripts.sh`).
Any future third change to `validate-pr15b.py` therefore fails that assertion.
The acceptance rule text is additionally diffed between the reconstructed and
current file and must be identical.

Behavioural proof (same suite):

| Case | Pre-patch validator | Patched validator |
|---|---|---|
| `AVAILABLE` + `--profiler-evidence <path>` | exit 2, `unrecognized arguments` | exit 0, qualified, evidence serialised verbatim |
| `AVAILABLE`, no flag | exit 3, `AVAILABLE profiler status requires captured evidence` | exit 3, identical text |
| `AVAILABLE` + `--profiler-evidence ""` | exit 2, `unrecognized arguments` | exit 3, normalised to `null`, identical text |
| `UNAVAILABLE`, no flag | accepted | accepted, `evidence = null` |

## 5. Where the evidence comes from

Only a genuinely captured artifact is accepted. Per trial, strictly **after**
`cargo bench` exits and **after** the final contention sample:

1. `perf` via the unmodified `profile-pr15b.sh --mode perf --workload absent`;
   if that is unavailable or fails, `heaptrack` via the same wrapper.
2. The primary artifact must be a regular, non-symlink, non-empty file
   (`profiler/perf.data` **and** `profiler/perf-report.txt` for perf; the
   `profiler/heaptrack*` data file for heaptrack).
3. `pr15cb-profiler-evidence.py write` measures `st_size` and SHA-256 from the
   bytes on disk and atomically writes `profiler/evidence.json`.
4. `pr15cb-profiler-evidence.py verify` re-opens the record, re-stats and
   re-hashes the artifact, and rejects anything absent, symlinked, empty,
   mis-sized, mis-digested, malformed, or living outside that trial's own
   `profiler/` directory.
5. Only after (4) succeeds is `--profiler-evidence <evidence.json>` passed.

If no candidate profiler produces a valid artifact the flag is omitted, the
capture stderr is logged, and the **unchanged** validator rule decides the
outcome. `profiler_status` is never forced, never suppressed, and no PATH, kernel,
service or package state is modified.

## 6. Applicability to both measured sources

The same patch is committed as a tooling-only commit on top of each measured
source (`42b1944…` before, `b4682d0…` after) so both worktrees remain clean (the
runner refuses a dirty tree) and carry byte-identical benchmark tooling. The
causal identifiers remain the engine SHAs; tooling commits are recorded separately
and are compared by SHA-256 before any qualified trial.

## 7. Prohibited extensions

A third validator change, new CLI semantics, a different evidence representation,
relaxed validation, a runner-minted trial manifest, or any further optimisation
under this exception requires a new, separately approved amendment.
