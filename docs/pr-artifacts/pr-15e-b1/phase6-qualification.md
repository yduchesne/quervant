# PR 15E Phase 6 — focused profiling qualification

**Status: `P6_PROFILE_BLOCKED_OPERATOR` — no profiling data exists; nothing is qualified.**

The four required CPU captures were not executed because the PR 15E-A profiler requires a
genuine, current operator-written attestation, and the coding agent may not create one. The
capture attempt failed closed (`BLOCKED_ATTESTATION`, exit 3) before any profiled query ran.

## 1. Why there is no measurement here

| Gate | State |
|---|---|
| Source lock (`e448469`, clean, frozen tools untouched) | PASS |
| Adapter/corpus/index preparation (real `FsDirectory`, frozen oracle) | PASS |
| `perf` tool availability | PASS via the driver's versioned fallback (`perf 6.8.12`), disclosed |
| Operator attestation | **BLOCKED** — no operator-written `attestation.json` for this run |
| Four required captures (`rare`, `absent`, `medium`, `common`) | NOT RUN |
| Contention probes | NOT RUN (8 expected) |
| PR 15E-A full-campaign verifier | NOT RUN (would be `PARTIAL` by design) |
| Focused 4/4 subset gate | NOT RUN |
| CPU attribution | NO DATA |
| Disposition (§10 thresholds) | NOT APPLICABLE |

## 2. What will be published when unblocked

Once the operator supplies the attestation described in `phase6-execution.md` §5 and the four
captures succeed, this document will be replaced with:

* per-capture SHA-256, sample counts and lost samples for `perf-self.txt`,
  `perf-calltree.txt` and `capture.json`;
* the original verifier's `PARTIAL` status (4/20, exit 3) and the focused 4/4 subset result,
  explicitly **not** `EVIDENCE_COMPLETE`;
* for each lane, the top exclusive frames and the top inclusive chains with the fixed
  `P6-G01…G08` group labels, `self` and `inclusive` clearly distinguished and never summed;
* the §10 disposition (`strong` / `likely, inclusive only` / `unresolved`) with the exact
  threshold comparison, or an explicit `P6_PROFILE_UNRESOLVED` with
  `NO_PHASE7_OPTIMIZATION_AUTHORIZED`;
* and a sanitized `benchmarks/reports/pr15e-b1/phase6-focused-profile.json`.

## 3. Limits that will apply to any future result

Perf sample shares cover the whole profiled process (startup, five warmups, JSONL transport)
and are not per-query stage durations; they cannot be converted into microseconds or savings.
The workload is the synthetic frozen exact-term `FsDirectory` corpus. WSL2 symbolization and
lost samples may leave a material share unresolved. No allocation attribution exists without
the optional heaptrack probe, and no cross-host, remote-latency or concurrent-writer behaviour
is measured by this phase.

## 4. What this phase does **not** claim

No dominant function, no bottleneck ranking, no optimization recommendation, no speedup, and
no revision of the Phase 5 measurements. The prior `compute_stats` suggestion remains an
untested hypothesis.
