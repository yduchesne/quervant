# PR 14E — benchmark dependency ledger (PR 14F)

**Status: `BLOCKED — PR 14F`. Zero fresh trials were executed by PR 14E.**
This document carries the P4 benchmark obligation forward with its exact
dependency. It does not measure, qualify, re-label or reinterpret anything.

## 1. Historical vs current — the distinction that must not be blurred

| Item | Historical | Current (PR 14E) |
|---|---|---|
| Source SHA of the only trials of record | `ab9b2d7da066ec80190dcee70a8cebfd81481b80` (2026-10-19) | — none — |
| Distance from current `main` | 138+ commits behind PR 14C baseline `376023b`; current head is `dc506f6` | n/a |
| Trials | `t1`, `t2`, `t3` (`qualified=true`, `idle_confirmed=true`, `contention=clear`, `dirty=false`) | **0 of 3** |
| Sanitized reports | `benchmarks/reports/pr14-p4-t{1,2,3}.json` | unchanged, **not** regenerated |
| Status in PR 14E | **PROVENANCE ONLY** | **BLOCKED** |

The `ab9b2d7` numbers are never presented as current-branch measurements, are
never re-validated as if fresh, and are not the basis of any acceptance claim in
PR 14E. They exist to show the workload and validator were executable at some
point, not that the current tree is qualified.

## 2. Obligation ledger

| ID (historical) | Obligation | State | Exact dependency |
|---|---|---|---|
| `V11, V12` (§7.1) | Benchmark oracle (`B01–B04`) and three qualified trials | **BLOCKED** | PR 14F |
| `B01` (§7.4) | Correctness oracle asserted before timing | **BLOCKED** | PR 14F: first qualified trial |
| `B03` (§7.4) | Three independently qualified trials | **BLOCKED** | PR 14F: 3 × qualified |
| `W01–W07, W09` (§7.5) | Measured lanes with correctness oracle | **BLOCKED** | PR 14F: all lanes measured |
| `W08` (§7.5) | Forced eviction/reload lane | **NOT APPLICABLE (APPROVED)** | approved exemption — never measured |
| `§8` item 6 | Fresh benchmarks; old reports provenance only | **BLOCKED** | PR 14F |
| phase `14F` (§6) | Real boundary + faults + benchmarks | **BLOCKED** (benchmark component only) | PR 14F |
| `B02` (§7.4) | Validator rejects invalid/unqualified reports | **PASS** | re-executed `--self-test` in PR 14E |
| `B04` (§7.4) | Dirty/contended/unknown rejection | **PASS** | wrapper source + self-test |

## 3. What a qualified trial must satisfy (unchanged contract)

Source of truth: `benchmarks/workloads/pr14_p4_v1.md`,
`benchmarks/scripts/run-pr14-p4.sh`, `benchmarks/scripts/validate-pr14-p4.py`.

| Requirement | Detail |
|---|---|
| Workload | `pr14_p4_v1`, 20,000 deterministic documents, 3 immutable segments, seed `0x14F4_2026`, corpus digest `80ef5615…f8768` |
| Correctness oracle | Lanes W01–W07/W09 asserted **before** timing (10,000 / 10,000 / 2,000 / 6,000 / 2,500 / 4×5,000 / S-F-S / 10,000) |
| Trials | 3 independent qualified trials |
| Operator attestation | `--idle-confirmed` (explicit operator statement) |
| Environment | native Linux filesystem, pinned real RustFS (`rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`), contention result `clear` (`check-pr07-contention.py`) |
| Tree state | clean tracked tree at the recorded SHA |
| Sampling | ≥3 warmups and ≥20 measured samples per configuration |
| Artifacts | raw CSV under `target/pr14-p4/`, sanitized report JSON under `benchmarks/reports/`, all metrics present |
| Exemptions | W08 exemption manifest `benchmarks/reports/pr14-p4-w08-exemption.json` (approved Option 2) |
| Validation | `python3 benchmarks/scripts/validate-pr14-p4.py` → `PASS: 3 qualified pr14_p4_v1 trials` |
| Prohibitions | no pooling of cold/warm or local/remote; no cross-engine (Tantivy/Lucene) claim in PR 14; no p99 SLO claim |

## 4. W08 waiver (approved, not measured)

| Item | Value |
|---|---|
| Status | `NOT APPLICABLE (APPROVED)` — decision "Option 2", `approved: true` |
| Decision record | `docs/pr-artifacts/pr-14/p4-w08-stop.md` |
| Manifest | `benchmarks/reports/pr14-p4-w08-exemption.json` (`workload: pr14_p4_v1`, `w08.status: not_applicable`) |
| Rationale (verbatim gist) | `RemoteIndex` pins every verified committed segment for the snapshot lifetime; releasing it would violate the immutable snapshot contract, and manual unpin/external cache deletion/new production APIs are out of scope for v0.1 |
| Validator enforcement | `validate_w08_exemption()` requires the manifest, `workload == pr14_p4_v1`, `status == not_applicable`, and an approval flag |
| PR 14E check | Manifest present and structurally valid; validator self-test requires it; W08 is **never** reported as measured or PASS |

PR 14E did not run an eviction/reload measurement, does not claim one, and does
not convert this waiver into a performance result.

## 5. Why PR 14E did not run a trial

1. The plan (§3, §6 C7, §8) assigns fresh trials to **PR 14F**; PR 14E is
   docs/evidence only (EAD-01, EAD-12; decision X18).
2. Qualified mode requires an explicit operator `--idle-confirmed` attestation
   on an idle native-Linux host; the maintainer has not supplied one for this
   session.
3. A diagnostic run cannot qualify and would not change any gate, so it was not
   performed (same reasoning recorded in PR 14C).

## 6. Handoff to PR 14F

PR 14F must, at minimum:

1. Confirm a clean tree at its own recorded SHA and start the pinned provider.
2. Obtain and record the operator idle attestation and a `clear` contention
   result.
3. Execute three independent qualified trials with the pre-timing oracle.
4. Archive raw CSVs + sanitized reports and run the validator to `PASS`.
5. Publish a report that keeps cold/warm and local/remote separate, labels W08
   as the approved waiver, and makes no cross-engine claim.
6. Bind the resulting evidence to its own immutable head SHA and CI run.

Until 1–6 exist, `V11/V12`, `B01`, `B03`, `W01–W07/W09`, `§8` item 6, phase `14F`
and PR 14 acceptance remain `BLOCKED`.

## 7. 2026-10-26 successor note — PR 14F status (does not erase §1–§6)

PR 14F (`bench/pr14f-p4-qualification`, source lock
`162cbfea509d5f03df4bedb89a09d9be4cafb75e`) prepared and tested the qualified
harness, prequalified the pinned provider, and ran trial `t1` successfully. The
campaign then **aborted after t1** on a report-directory path defect; `t2`/`t3`
were never started. There are **0 of 3 publishable trials**.

Exact new evidence:

- `docs/pr-artifacts/pr-14f/harness-corrections.md` — deterministic wrapper
  parser, removal of an inherited `QUERVANT_P4_DIAGNOSTIC`, ignored
  `QUERVANT_P4_REPORT_DIR`, per-trial live contention, W08-exemption wiring,
  strict read-only auditor.
- `docs/pr-artifacts/pr-14f/environment-and-provider.md` — ext4 WSL2 host and
  pinned `docker.io/rustfs/rustfs@sha256:1803faef…6a3c` health `1.0.1`.
- `docs/pr-artifacts/pr-14f/qualification-attempts.md` — **1 of 3** trials
  executed (`t1`, runner PASS, clear contention), **0 publishable**;
  `BLOCKED — CAMPAIGN ABORTED AFTER T1 (HARNESS REPORT-PATH DEFECT)`.
- `docs/pr-artifacts/pr-14f/validation-report.md` — local stable/MSRV gates pass,
  91.84% line coverage; benchmark gate blocked.
- `docs/pr-artifacts/pr-14f/qualification-manifest.json` — machine-readable
  blocked gate with the preserved `t1` artifact hashes (no fabricated trials).

Therefore every row above that depends on fresh trials (`V11/V12`, `B01`,
`B03`, `W01–W07/W09`, `§8` item 6, phase `14F`) remains **BLOCKED**. `W08`
remains **NOT APPLICABLE (APPROVED)** and was not measured. PR 14 overall
remains **IN PROGRESS / NOT ACCEPTED**; v0.1 is **NOT RELEASED**.
