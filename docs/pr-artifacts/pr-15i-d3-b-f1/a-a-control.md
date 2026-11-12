# PR 15I-D3-B-F1 — A/A control `d3bf1-base-aa-01`

**Status: `MEASUREMENT_BLOCKED` at independent verification. The controller
reported `CONTROL_QUALIFIED`; the frozen independent verifier rejects the sealed
evidence because of two post-T1 tooling defects.** No paired campaign was run.

## Execution facts

| Item | Value |
|---|---|
| Campaign | `d3bf1-base-aa-01` |
| Kind | same-source A/A control, both arms BASE `39dbd9f5…` |
| Canonical compile path | `…/fixup-f1/d3bf1-base-aa-01/compile-source` |
| T1 tooling freeze | `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82` |
| Protocol SHA-256 | `4d55ea0577f2779a48f007c4e14adf56538c8ded4a86d8ca3e4d8194215657cd` |
| Tooling manifest SHA-256 | `6ac5f26743a3cf58880db2090839d6d25befee0724859265a5ff57d8367ad7e0` |
| Controller SHA-256 / verifier SHA-256 | `85e81352…` / `b7dfce92…` |
| Build A window | `04:08:08`–`04:08:30` UTC |
| Build B window | `04:08:31`–`04:08:54` UTC |
| Arm A binary | `2e28d89b19e973bacedd61aee09dae83c1af0f19c8437429cda4684a2a338313`, 4,479,080 bytes |
| Arm B binary | `2e28d89b19e973bacedd61aee09dae83c1af0f19c8437429cda4684a2a338313`, 4,479,080 bytes |
| Slots / lane records | 16 / 144 |
| Timed samples / warmups | 2,880 / 720 |
| Contention probes | 32, all `clear` |
| Drift | `PASS`, zero violations |
| Index bytes / STORED (100K) | 15,747,551 / 1,661,455 (identical digests `5734ae60591f7563…`) |
| Controller summary status | `CONTROL_QUALIFIED`, structural all `PASS`, A/A `passes = true` |

The canonical-path design worked: two real, sequential `cargo build` executions
from **one** path into **two** target directories produced byte-identical
binaries, exactly as the dry proof predicted. The numerical A/A medians all sit
inside `[0.85, 1.15]` (0.9323–1.0019) with no soft-outlier exception used.

## Independent verification failure

`python3 benchmarks/pr15i_d3_b_f1/verify.py --campaign-dir …/d3bf1-base-aa-01`
returns exit code 3:

```json
{"reasons":[{"code":"V_INVENTORY","detail":"unlisted campaign member: compile-source/.git"}],"schema":"pr15i-d3bf1-verification-v1","verification":"FAIL"}
```

After exempting `compile-source/` from that inventory walk **in memory only**
(diagnostic, no file or evidence change), the next failure is:

```text
V_HOST [{"code":"V_HOST","detail":"host fingerprint does not recompute"}]
```

Root causes (both in the frozen T1 tooling, not in the evidence):

1. `verify_inventory` exempts only `build/`, `indexes/` and `corpus/`. Plan
   §3.2 mandates `<campaign>/compile-source` and §11 lists it as excluded from
   the archive; it is therefore an unsealed, non-evidence directory that the
   inventory check must skip.
2. The controller writes `allowed_cpus_before_pin` in
   `raw/host-attestation.json`, but its shared `host_fingerprint` function reads
   `environment.get("allowed_cpus")`. The sealed fingerprint
   `45024a19…` therefore omits the allowed CPU set, while the verifier
   independently recomputes `aa136252…` from
   `allowed_cpus_before_pin`. Controller and verifier disagree (FDX-56).

The sealed control is internally consistent (`verify_seal_hashes` passes, 59
members; controller summary/manifest agree), but it cannot be requalified
without regenerating it under corrected tooling. The archive is **not**
published: `publish` correctly refuses because independent verification fails,
and hand-crafting an archive would bypass the mandatory verifier gate.

## Disposition and rule application

- `FDX-41` / plan §4: a tooling defect discovered after the first official
  acquisition is a HARD STOP; no hot patch, no paired campaign.
- `FDX-44`: no control retry and no measurement continuation.
- `FDX-56`: controller/verifier disagreement blocks the result.
- `FDX-64`: the unmerged candidate is left intact; no rollback for a structural
  measurement block.

Preserved locally at
`target/pr15i-d3-b/fixup-f1/d3bf1-base-aa-01/` (`SAME_DISK_ONLY`), including
`compile-source`, both builds, indexes, sealed raw evidence and sanitized
summary. Not archived, not evidence for any performance claim.

## Required human decision

Authorize a new freeze (F1.1) that (a) excludes `compile-source/` from the
verifier inventory walk and (b) defines one canonical host-fingerprint input
set (`allowed_cpus_before_pin`) used identically by controller and verifier.
Then execute a **fresh** control and paired campaigns; this control cannot be
reclassified or repaired.
