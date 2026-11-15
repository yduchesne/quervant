# PR 15I-D3-B-F1.1 — decision register

| ID | Observation | Action |
|---|---|---|
| F11-01 | Branch `dev/pr15i-d3b-retained-key-prefilter`, HEAD `b1c72a24…`, only documented D3-B/F1 commits | Continued without rebase/reset |
| F11-04 | Candidate `unified.rs` Git blob SHA-256 `493f9382…` | Reused; no production edit |
| F11-06 | Original F1 control present with valid 59-member seal | Read-only inventory, then copied sealed members |
| F11-08/09/10/11/12 | Root `compile-source` handling | Root-only exclusion; file/symlink/sealed/interior cases rejected with exact codes |
| F11-13/14/15/16 | Fingerprint contracts | Preflight kept `allowed_cpus`; campaign uses sealed `allowed_cpus_before_pin` under canonical `allowed_cpus` key; strict shape; controller/verifier parity proven |
| F11-17/18 | Protocol delta | Exactly the six prescribed top-level changes; recursive equality elsewhere |
| F11-19/20 | Inherited F1 tests | All 95 retained and passing; fixes limited to the two approved defects |
| F11-22/23/24/25 | Synthetic copy transformation | Only prescribed identity/attestation/path fields changed; sample/oracle payload byte-identical |
| F11-26/27 | Positive rehearsal | Full external verifier PASS (`SYNTHETIC_REHEARSAL_VERIFIER_PASS`) |
| F11-28/29/30 | Negative matrix | 15/15 exact expected outcomes; R16 invariance confirmed |
| F11-31 | Rehearsal publish attempt | Refused with `D3B_REHEARSAL_PUBLISH_FORBIDDEN`; no receipt/archive |
| F11-33/36 | Two pre-T2 harness defects (R02 missing reseal; R09 exclusive overwrite) | Corrected within harness scope; new candidate commits T_PRE2/T_PRE3; full tests and rehearsal matrix re-run; failed rounds preserved |
| F11-35 | Rehearsal green with unchanged tooling | T2 = T_PRE3 = `63b30a0be451357a5edaf8399ad2e4d336e6c45b` |
| F11-37 | T2 inventory/hash checks | `git diff --exit-code T2 -- benchmarks/pr15i_d3_b_f1_1` empty |
| F11-39 | Detached clean identity worktrees | Created under the new target root; never compile paths |
| F11-40 | Canonical A/A builds byte-identical | Proceeded to official slots |
| F11-42 | Canonical A/B builds distinct | Campaign 01 executed |
| F11-45 | Independent control fully qualified | Archived immediately, then ran paired 01 automatically |
| F11-48 | Native FS, pinned affinity, 32 clear probes | Continued |
| F11-49 | Campaign 01 drift violation (arm A block 2 `10K rare` 1.503058 > 1.50) | HARD STOP: `D3BF11_MEASUREMENT_BLOCKED`; no lane retime, no campaign 02 |
| F11-56 | Paired 01 structurally blocked | No performance decision; evidence archived as blocked; candidate retained |
| F11-59 | No campaign 02 | Series verdict `MEASUREMENT_BLOCKED`, `d3b_p08=FAIL` |
| F11-64/65/66 | Archives | Exclusive new paths, sidecars, extraction rehash; no overwrite |
| F11-67 | RustFS pinned image cannot start | `RUSTFS_PENDING`; no unpinned image, no fake PASS |
| F11-68 | `gh` token invalid (unchanged environment) | Push via SSH; `PR_NOT_CREATED` |
| F11-71 | QA/coverage | PASS (2,496 Rust tests, 92.85% lines, MSRV clean) |
| F11-72 | No unforeseen condition outside the matrix | None |

## Incidental working-tree state

A pre-existing user modification to `disk-cleanup.sh` (Podman image guard) was
present before the F1.1 tooling commit. It is outside the plan's paths and was
preserved untouched; it was not staged, reverted or included in any F1.1 commit.

## Human decision required

The optimization is **not** rejected — the first paired campaign was
structurally blocked by a within-block drift violation, so no performance
verdict is authorized. A future attempt needs a separately authorized plan/fresh
campaign names (the official names are consumed) and should consider a
host-noise/drift strategy that does not relax the frozen caps. The measured P01
and P02 wins and the P03 miss (below the frozen floor by 40,643 ns) remain
diagnostic only.
