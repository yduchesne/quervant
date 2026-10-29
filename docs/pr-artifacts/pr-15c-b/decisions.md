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
