# PR 15C-B decision log

Every exercised row of the plan's preauthorised decision/exception matrix, plus
the one condition that no row covers (recorded as `STOP-15CB-01`, rule X99).

## Exercised rows

| Rule | Condition observed | Classification | Action taken | Evidence |
|---|---|---|---|---|
| **X03** | Clean worktree, `origin/main` = `0a0f912…`, target branch absent | AUTO-RESOLVE | created `dev/pr15c-b-performance-qualification` from `origin/main` | `preflight.md` §1 |
| **X05** | Exactly two synchronous test consumers of `BUILD_INVOCATIONS` (lines 605/614, 619/627) and no other caller | AUTO-RESOLVE | replaced the process-global `AtomicU64` with the prescribed `#[cfg(test)] thread_local! Cell<u64>`; kept both tests and both `assert_eq!(build_invocations(), 0)` assertions unchanged | `preflight.md` §2, `gates.md` §4 |
| **X07** | Not needed | not triggered | `const { Cell::new(0) }` compiles on `cargo +1.85.0 test -p quervant-core --lib --no-run` | `gates.md` rows 5/6/8 |
| **X09** | Coverage command passes with the isolated counter | AUTO-RESOLVE | continued the full suite (3 independent coverage runs, all 91.81 % lines) | `gates.md` rows 15–17 |
| **X11** | Pre-15C-A SHA proven from PR 15C-A parent/merge history, not from the shortened `e8ca1b0` filename | AUTO-RESOLVE | pinned the full SHA `42b19445dd79a90d8701b4306e305c6e4e44cd57` | `preflight.md` §4 |
| **X13** | Before and after compile the byte-identical frozen harness | AUTO-RESOLVE | executed both clean worktrees with the unmodified `run-pr15b.sh` | `preflight.md` §4, `gates.md` §5 |
| **X15** | Native Linux `ext4` on one host for all three trees | AUTO-RESOLVE | ran the controlled A→B series (order fixed before measurement) | `gates.md` §5 |
| **X19** | Contention state `clear` in every pre/post/final sample | AUTO-RESOLVE | accepted the trials as non-contended; no environment repair needed | `gates.md` §5, `trials/` |
| **X20** | All trials structurally unqualified | DEFER AND CONTINUE | kept every raw log, trial dir, contention file, Criterion tree and profiler record; produced a diagnostic comparison instead of dropping trials | `gates.md` §5–6 |
| **X25** | Same-host paired medians show no regression | AUTO-RESOLVE | reported all 30 lane-level rows plus dispersion; **no hot-path optimisation performed** | `comparison.md` |
| **X26** | `/usr/bin/perf` wrapper unusable on the WSL kernel | DEFER AND CONTINUE | recorded the failure verbatim; used only the already-installed version-mismatched `6.8.12` binary via a `PATH` symlink; no `sudo`, no kernel/sysctl change, no installation, no fabricated counts | `diagnostics.md` §3 |
| **X27** | Test-only cache counters exist with clear semantics | AUTO-RESOLVE | reused `verification_count` as a labelled deterministic witness; explicitly **not** described as a total SHA-invocation count | `diagnostics.md` §1 |
| **X28** | Head SHA changes after the measured executable tree | AUTO-RESOLVE | recorded executable-tree identity (`eb49bd4c…`, `crates/` `ad1a756c…`, `benchmarks/` `56eaf9cf…`); CI still required at the final head | `gates.md` §1 |
| **X29** | No local RustFS endpoint/credentials | DEFER AND CONTINUE | marked real-RustFS `BLOCKED-ENVIRONMENT` locally; relies on the GitHub `rustfs` job (pending) | `gates.md` rows 27 |
| **X33** | Historical PR 15B report is same CPU/kernel but a different, earlier qualification run | AUTO-RESOLVE | cited only as historical context; **no** causal or matched-latency claim uses it | `comparison.md`, `acceptance.md` §5 |
| **X34** | Timings available, profiling partially available | AUTO-RESOLVE | published only measured timing and measured attribution; missing attribution explicitly `NOT MEASURED` | `diagnostics.md` §5 |
| **X36** | No gate failed, so baseline re-verification is not needed | not triggered | — | `gates.md` §6 |

## STOP-15CB-01 (rule X99) — frozen validator cannot emit a qualified trial on a host with profiling tools

**Stage:** S3 (qualified before/after measurement) and the `QUALIFIED` half of S4.

**Exact code:**

- `benchmarks/scripts/capture-pr07-env.sh` records `perf_path`,
  `cargo-flamegraph_path`, `heaptrack_path` (and `hyperfine_path`) from
  `command -v`.
- `benchmarks/scripts/validate-pr15b.py::build_trial` (lines ~393–401) derives
  `profiler_status = "UNAVAILABLE" if all(p == "UNAVAILABLE" …) else "AVAILABLE"`
  and then always writes `"profiler_evidence": None`.
- `benchmarks/scripts/validate-pr15b.py::validate_trial` (lines ~226–233) requires
  a non-empty `profiler_evidence` whenever `profiler_status == "AVAILABLE"`.

**Observed input/error:**

```text
derived profiler_status = AVAILABLE
REJECTED: AVAILABLE profiler status requires captured evidence
```

and, on a real trial manifest with the idle attestation supplied:

```text
STILL REJECTED after supplying idle attestation: AVAILABLE profiler status requires captured evidence
profiler_status: AVAILABLE evidence: None
```

**Invariant violated:** B-I04/B-I05 — a `QUALIFIED` aggregate is unobtainable, so
no qualified before/after comparison can be produced on this host. The frozen
runner exits 3 and never writes `pr15b-qualified.json`.

**Why it did not fire in PR 15B:** the PR 15B qualification host had no profilers
installed (`target/pr15b/20261028T161528Z-e8ca1b0…/trial-1/env.txt` records all
three as `UNAVAILABLE`). They were installed later, during the PR 15B profiling
follow-up (`docs/pr-artifacts/pr-15b/profile-attempts.md`). Nothing in the
workload, lane set, oracle, digest or timing region changed — **X31 does not
apply**, and the frozen files were not modified (§S4 "do not edit that
validator", §S6 "all frozen PR15B files … must not be changed").

**Impact:** before/after timing exists, is same-host, uses the byte-identical
harness and 30/30 lanes, and is reported as `UNQUALIFIED`/`DIAGNOSTIC` with no
published speedup claim.

**Independent safe work continued:** S1 FST correction, S2 gate set, S4 strict
comparator + self-test, S5 untimed diagnostics, S6 documentation.

**Options considered and rejected without approval:**

1. Edit `validate-pr15b.py`/`run-pr15b.sh` to record or relax
   `profiler_evidence` — forbidden (frozen PR15B files) and would break
   apples-to-apples with the baseline.
2. Apply the same patch to both measured worktrees — §S3 requires the
   *unmodified* runner; a baseline harness patch is X14 (HARD STOP).
3. Hide `perf`/`cargo-flamegraph`/`heaptrack` from `PATH` so the runner records
   `UNAVAILABLE` — technically feasible, but it manufactures the qualification
   label by suppressing a true environment fact. Rejected as covert policy
   change (X31 forbidden improvisation: "Change policy silently").
4. Remove the installed tools — requires system modification; forbidden.

**One smallest decision needed:** authorise exactly one of

- **(A)** a narrowly scoped amendment permitting `run-pr15b.sh`/`validate-pr15b.py`
  to record a real `profiler_evidence` value (e.g. the profiling artifact paths
  produced by `profile-pr15b.sh`) — the honest fix, but it edits a frozen file and
  must then be proven not to change timing semantics; or
- **(B)** an amendment stating that `profiler_status` describes only the
  *tool-availability probe* and that trials on a profiler-equipped host may be
  qualified with `profiler_evidence` recorded out-of-band in
  `docs/pr-artifacts/…/diagnostics.md`; or
- **(C)** accept that PR 15C-B stays `DIAGNOSTIC/UNQUALIFIED` on this host and
  that qualified measurement is deferred to a profiler-free environment.

Option (C) is what this PR currently does; (A)/(B) would allow a `QUALIFIED`
label in a follow-up.

## Additional decision: no idle attestation was invented

The plan requires an actual human operator to confirm that no competing benchmark
workload was running before passing `--idle-confirmed` (X17/X18). No such
confirmation was obtained, so the flag was **not** passed and the runner recorded
`operator_idle_confirmation = absent`. The contention detector independently
reported `clear` in all 18 samples (6 trials × pre/post/final), which is recorded
but is explicitly **not** a substitute for the operator attestation.

## Additional decision: no production counter or metric added

S5.3 allows a separate untimed cache-hit-ratio scenario only if it is
source-grounded. Providing an engine-wide hit ratio would need production
instrumentation (forbidden by the plan and by AGENTS.md hot-path rules), so it is
reported as `NOT MEASURED` rather than approximated.

---

# STOP-15CB-02 (rule X99) — OPTION A cannot be implemented runner-only

Status: **HARD STOP on the corrected-tooling stage.** No frozen file has been
modified. Everything else in the authorised Option A remains ready to execute.

## Authorisation received

> "AUTHORIZE OPTION A — STOP-15CB-01 tooling correction." with constraints:
> (1) do not modify the frozen validator, production implementation, benchmark
> workloads or qualification thresholds; (2) record genuine evidence, never
> fabricate or suppress profiler discovery; (3) keep profiling outside timed
> measurements; (4) add focused regression tests; (5) document the frozen-tooling
> exception; (6) do not reclassify existing diagnostic trials; (7) requalify both
> sources with identical corrected tooling and an independently supplied operator
> idle attestation; (8) stop if the correction requires changing validator
> semantics, timing regions, source comparability or other frozen contracts.

## Exact code evidence

1. `benchmarks/scripts/validate-pr15b.py:399` — inside `build_trial`, the trial
   manifest builder **hardcodes** the field the validator then requires:

   ```python
   "profiler_status": profiler_status,
   "profiler_evidence": None,
   ```

2. `benchmarks/scripts/validate-pr15b.py:362–368` — `profiler_status` is derived
   from `capture-pr07-env.sh`'s `perf_path` / `cargo-flamegraph_path` /
   `heaptrack_path`. This half already works and must not be suppressed.

3. `benchmarks/scripts/validate-pr15b.py:310–315` — the acceptance rule:

   ```python
   profiler_status = qualification.get("profiler_status")
   require(profiler_status in {"AVAILABLE", "UNAVAILABLE"}, "invalid profiler_status")
   if profiler_status == "AVAILABLE":
       evidence = qualification.get("profiler_evidence")
       require(isinstance(evidence, str) and evidence,
               "AVAILABLE profiler status requires captured evidence")
   ```

4. The `trial` subcommand CLI surface has **no** argument for evidence:
   `--criterion-dir --fixture-metadata --env-file --out --run-id --source-sha
   --contention-state --source-dirty --idle-confirmed --correctness-passed`.

5. Empirical proof that the runner cannot supply it:

   ```text
   $ python3 benchmarks/scripts/validate-pr15b.py trial … --profiler-evidence "/some/artifact"
   usage: validate-pr15b.py [-h] {trial,aggregate,self-test} ...
   validate-pr15b.py: error: unrecognized arguments: --profiler-evidence /some/artifact
   exit code = 2
   ```

6. Empirical proof that the *rule itself* already accepts evidence (so the defect
   is the missing input, not the rule):

   ```text
   hand-patched manifest with evidence: ACCEPTED by the frozen check
   manifest without evidence: REJECTED -> AVAILABLE profiler status requires captured evidence
   ```

7. `aggregate` re-runs `validate_trial` on every supplied trial, so a manifest
   amended after `build_trial` would be re-checked under the same rule — there is
   no passive escape route.

## The contradiction

Constraint (1) says "do not modify the frozen validator". Because of (1), (4) and
(7) above, **no change confined to `run-pr15b.sh` can ever satisfy the validator's
evidence rule while the validator's profiler discovery stays truthful.** The only
run-pr15b-only alternatives are exactly the ones forbidden by constraint (2):

- suppress profiler discovery (hide `perf`/`cargo-flamegraph`/`heaptrack` from
  `PATH`) so the status becomes `UNAVAILABLE` — fabricates a qualification label
  by suppressing a true environment fact; explicitly forbidden;
- have the runner author the trial manifest itself and call only
  `validate-pr15b.py aggregate`, duplicating the frozen manifest builder — a much
  larger silent schema fork; not an Option A correction.

This is precisely rule X99 ("unforeseen condition or contradictory
requirements"), and the plan instructs: report it and **do not design a workaround
independently**.

Note that the plan's own Option A description anticipates editing the validator:
"a narrowly scoped amendment permitting `run-pr15b.sh`/`validate-pr15b.py` to
record a real `profiler_evidence` value … the honest fix, but it edits a frozen
file and must then be proven not to change timing semantics". Constraint (8) is
consistent with that (it stops only on a change of validator *semantics*).
Constraint (1) as literally worded is not. **Only the human can say which governs.**

## Proposed amendment (ready to apply on approval — smallest possible)

`benchmarks/scripts/validate-pr15b.py`, two hunks, 7 added lines, 1 changed line:

```diff
@@ trial subparser (after --correctness-passed)
     trial.add_argument("--correctness-passed", action="store_true")
+    trial.add_argument(
+        "--profiler-evidence",
+        default=None,
+        help="non-empty record of genuinely captured profiler evidence; required by "
+        "validation whenever profiler_status is AVAILABLE",
+    )
@@ build_trial manifest
             "profiler_status": profiler_status,
-            "profiler_evidence": None,
+            "profiler_evidence": args.profiler_evidence or None,
```

Why this does **not** change validator semantics, thresholds or timing:

- Lines 310–315 (the acceptance rule) are untouched: `AVAILABLE` still requires a
  non-empty string, `UNAVAILABLE` still ignores the field.
- Lines 362–368 (profiler discovery) are untouched, so a present-but-unusable
  profiler still yields `AVAILABLE` and therefore still forces evidence.
- The new argument is optional with `default=None`, so every existing invocation
  (including `self-test` and the CI harness) behaves **byte-identically**. An
  empty string is normalised to `None`, so the rule cannot be satisfied by `""`.
- No lane, corpus, oracle, digest, sample count, warm-up/measurement time,
  tolerance or coverage threshold is touched. The timed region is not touched.

## Runner amendment (authorised; applies only together with the above)

`benchmarks/scripts/run-pr15b.sh`, strictly **after** `cargo bench` exits and after
the post-trial contention sample, i.e. outside every timed region:

1. Pre-build the profiling driver once per series (builds are allowed outside timed
   regions); the profiling profile is separate from the `bench` profile.
2. Per trial, attempt one bounded capture in a fixed documented order by reusing
   the unmodified `profile-pr15b.sh`: `--mode perf --workload absent`, then
   `--mode heaptrack --workload absent` if perf produced no artifact.
3. On success, write `$OUT_ABS/profiler-evidence/evidence.json` containing the
   tool, the tool path and version, the workload, the artifact path, the artifact
   byte size and the artifact `sha256`, and pass a non-empty
   `--profiler-evidence` string to the validator.
4. If every attempt fails while a profiler is on `PATH`, pass **no** flag (the
   trial then correctly stays unqualified), print the captured stderr, and never
   substitute `UNAVAILABLE`. Profiler discovery is never modified.
5. If `capture-pr07-env.sh` reported all profilers `UNAVAILABLE`, pass no flag —
   exactly today's behaviour.

## Identical tooling on both source states (constraint 7, comparability)

The runner refuses a dirty tree, so the corrected harness cannot simply be copied
into a worktree. Plan: commit the **identical** `benchmarks/scripts/*` patch as a
tooling-only commit on top of each measured source (`42b1944 + T` and
`b4682d0 + T'`), verify with
`git diff <before> <after> -- benchmarks/ crates/quervant-core/benches crates/quervant-core/examples Cargo.lock`
being empty, and keep the base SHAs as the causal "before"/"after" identifiers.
This preserves source comparability and leaves the timed region untouched.

## Regression tests (constraint 4) — planned

In `benchmarks/scripts/test-scripts.sh` (existing Python/script test pattern), with
a synthetic Criterion tree, a synthetic fixture-metadata file and a synthetic
`env.txt`:

- evidence supplied ⇒ `validate-pr15b.py trial --profiler-evidence <path>` returns 0
  and the manifest carries that string with `profiler_status = AVAILABLE`;
- evidence omitted ⇒ exit 3, `qualified = false`, reason
  `AVAILABLE profiler status requires captured evidence`;
- empty/whitespace evidence ⇒ rejected (normalised to `None`);
- profiler reported `UNAVAILABLE` ⇒ accepted with no evidence required;
- runner with a fake profiler present and a successful fake capture ⇒ the
  validator is invoked with a non-empty `--profiler-evidence` value and the trial
  directory contains `profiler-evidence/evidence.json` whose recorded `sha256`
  matches the artifact;
- runner with a fake profiler present and a failing capture ⇒ the evidence flag is
  absent, the trial is unqualified, and the captured stderr is logged.

## Requalification requirement (constraint 7) — still open

Requalification additionally requires an **independently supplied operator idle
attestation** at the moment of the run. That attestation has not been given and
will not be self-supplied.

## Impact

- Existing diagnostic trials (`docs/pr-artifacts/pr-15c-b/trials/`, committed at
  `b4682d0`) are **not** reclassified; they stay `UNQUALIFIED` and are the record
  of the pre-correction tooling.
- No source, workload, threshold or timing region has changed in this stop.
- Only this decision record was added.

## One smallest decision needed

Choose exactly one:

- **(A-R2 — recommended)** Confirm that constraint (1) means "do not change the
  validator's *semantics/rules*", and approve the 7-line additive
  `--profiler-evidence` input shown above. Then the runner correction, tests,
  frozen-tooling exception document and two-sided requalification proceed as
  planned (requalification still needs your idle attestation at run time).
- **(A-R1)** Confirm that `validate-pr15b.py` must not be touched at all. Then
  Option A is unreachable and PR 15C-B stays `DIAGNOSTIC/UNQUALIFIED` (previous
  Option C), because every remaining route requires fabricating or suppressing a
  profiler fact.
- **(A-i)** Authorise a larger correction: a new runner that mints the trial
  manifest itself against the frozen schema and calls only `aggregate`. Not
  recommended — it forks schema knowledge out of the validator.

---

# STOP-15CB-02 → A-R2 APPROVED (resolves the STOP)

- **Date:** 2026-10-29
- **Authorising provenance:** human decision **A-R2**, delivered as
  `QUERVANT_PR15C_B_A_R2_PROFILER_EVIDENCE_FIXUP_PLAN.md`
  ("Decision: AUTHORIZE OPTION A — STOP-15CB-01 tooling correction", refined by
  A-R2). It resolves the option set recorded immediately above and **replaces**
  it; the `STOP-15CB-02` record and the `STOP-15CB-01` record are retained
  unedited as required by append-only history.
- **Ruling:** constraint (1) ("do not modify the frozen validator") is interpreted
  as **do not change the validator's semantics, rules, discovery or thresholds**.
  An additive, optional CLI *input* that leaves the acceptance rule byte-identical
  is inside the approved scope. The plan's own Option A description anticipated
  editing both `run-pr15b.sh` and `validate-pr15b.py`.

## Exact validator diff (the only two authorised hunks)

```diff
@@ -396,7 +396,7 @@ def build_trial(args):
             "contention_state": args.contention_state,
             "correctness_passed": bool(args.correctness_passed),
             "profiler_status": profiler_status,
-            "profiler_evidence": None,
+            "profiler_evidence": args.profiler_evidence or None,
         },
         "fixture": fixture,
         "lanes": lanes,
@@ -762,6 +762,12 @@ def main():
     trial.add_argument("--source-dirty", action="store_true")
     trial.add_argument("--idle-confirmed", action="store_true")
     trial.add_argument("--correctness-passed", action="store_true")
+    trial.add_argument(
+        "--profiler-evidence",
+        default=None,
+        help="non-empty record of genuinely captured profiler evidence; required by "
+        "validation whenever profiler_status is AVAILABLE",
+    )

     aggregate = subparsers.add_parser("aggregate", help="aggregate qualified trials")
     aggregate.add_argument("--trial", action="append", required=True)
```

`7 insertions(+), 1 deletion(-)` in `benchmarks/scripts/validate-pr15b.py`. The
second `"profiler_evidence": None,` (the `synthetic_trial` self-test fixture) is
deliberately untouched; only one assignment was eligible.

## Proof the acceptance rule was not modified

1. `validate_trial` lines 310–315 have **no diff lines**. AR2 asserts that the
   `profiler_status = qualification.get(...)` … `environment = manifest.get(...)`
   region is byte-identical between the reconstructed pre-patch validator and the
   patched one.
2. The pre-patch validator is reconstructed by inverting only the two hunks, and
   re-applying them must round-trip to the patched file **byte-for-byte**
   (AR2 counterexample gate). Any third change fails the suite.
3. Behavioural contrast (AR2-T02/T03 plus the counterexample gate):

   | Case | pre-patch | patched |
   |---|---|---|
   | `AVAILABLE` + evidence flag | exit 2 `unrecognized arguments` | exit 0, qualified, evidence serialised verbatim |
   | `AVAILABLE`, no flag | exit 3 `AVAILABLE profiler status requires captured evidence` | exit 3, identical text |
   | `AVAILABLE` + `""` | exit 2 `unrecognized arguments` | exit 3, normalised to `null`, identical text |
   | `UNAVAILABLE`, no flag | accepted | accepted, `evidence = null` |

4. Profiler **discovery** (`profiler_paths` / `profiler_status`) has no diff
   lines, so a present-but-unusable profiler still yields `AVAILABLE` and still
   forces evidence.

## Frozen-tooling exception

Recorded in `docs/pr-artifacts/pr-15c-b/frozen-tooling-exception.md`: only the
optional CLI argument, the single manifest assignment, the runner evidence
plumbing, a new evidence helper, the AR2 test section and a `.gitignore` entry for
Python bytecode are exempt. Workload, lanes, corpus/oracle digests, Criterion
settings, timing regions, `profile-pr15b.sh`, `capture-pr07-env.sh`,
`check-pr07-contention.py`, the PR 15B reports, the CI coverage floor, production
code and dependencies remain frozen.

## Repository-hygiene correction (self-inflicted, disclosed)

Commit `a9af8de` accidentally tracked
`benchmarks/scripts/__pycache__/validate-pr15b.cpython-312.pyc` (a Python bytecode
artifact created while importing the validator to inspect it). It was absent on
`origin/main`, so it was introduced by this branch. It is removed from tracking
(`git rm --cached`, file deleted) and `.gitignore` now ignores `__pycache__/` and
`*.pyc`. No source, report or evidence file was affected.

## Consequence for qualification

The validator can now accept genuine evidence, so `STOP-15CB-01` is resolved
**technically**. Qualified measurement remains blocked only by the operator idle
attestation (rule X20) and, for merge acceptance, by exact-head CI and real
RustFS. The six previously published diagnostic trials stay `UNQUALIFIED` and are
**not** reclassified; requalification will be a new, separate series.
