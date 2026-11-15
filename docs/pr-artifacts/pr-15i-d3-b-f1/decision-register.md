# PR 15I-D3-B-F1 — decision register

| ID | Observation | Action |
|---|---|---|
| FDX-01 | `main`/`origin/main` == `39dbd9f5…`; branch clean at `80bffa8…` | Pinned BASE; continued on `dev/pr15i-d3b-retained-key-prefilter` |
| FDX-03 | Candidate commit `48d9abf3…`, `unified.rs` SHA-256 `493f9382…` | Preserved candidate bytes; no production edit |
| FDX-05 | Branch advanced only in documentation after the candidate | Continued without rebase/cherry-pick |
| FDX-07 | Old v1 manifest/protocol/archive verified | Left untouched; not re-used |
| FDX-09 | `benchmarks/pr15i_d3_b_f1` absent | Copied v1 tooling and applied only the F1 deltas |
| FDX-12 | v1 functions/shape matched the plan anchors | Applied §5–6 transformations |
| FDX-14/16/18 | Fresh F1 output paths; canonical worktree added exclusively; BASE detached and clean | Created and proved |
| FDX-21/23/24 | A/A built B from the unchanged BASE checkout; binaries identical | Dry proof and control both equal |
| FDX-25 | A/B dry proof produced distinct binaries and correct source SHAs | Proceeded to freeze |
| FDX-28 | Non-timed AA and AB dry proofs passed | Proceeded to T1 |
| FDX-30 | Verifier independently rehashes frozen Git blobs | Implemented and tested (T14/T15/V01) |
| FDX-32/34 | Native ext4 for all seven roles, `findmnt` agrees, observed controller/adapter CPUs match | Controller sealed host evidence and continued |
| FDX-38 | 32/32 contention probes clear; drift PASS | Continued |
| FDX-40 | Protocol/manifest literal and exact inventory matched T1 before the control | Started the official control |
| FDX-41 | Post-T1 tooling defects found during first verification (`V_INVENTORY` compile-source exclusion; `V_HOST` fingerprint field mismatch) | **HARD STOP**: no hot patch, no paired campaign, no retry; evidence preserved; new freeze required |
| FDX-42/43 | Control cannot be accepted because independent verification fails | No paired campaign; no control 02 |
| FDX-44 | Control verification failure is structural (seal/verifier), not numerical | Series stopped; `D3BF1_MEASUREMENT_BLOCKED` |
| FDX-56 | Controller summary says `CONTROL_QUALIFIED`; verifier recomputation disagrees | Blocked the result; controller status not used |
| FDX-57/58 | `publish` requires verifier `PASS`; verification failed | No archive, no sidecar, no overwrite; evidence preserved locally |
| FDX-59 | RustFS pinned image cannot start | `RUSTFS_PENDING`; no fake pass |
| FDX-60 | Hosted CI unavailable in this session | `CI_PENDING`; SSH push only, no PR claim |
| FDX-64 | Structural measurement block only | Unmerged candidate left intact; no rollback |
| FDX-65 | Independent documentation/QA remained | Completed trace/docs and QA |
| FDX-66 | Defects are material to acceptance and were not enumerated as fixable post-T1 | Stopped affected work and recorded the exact human decision required |

## Required human decision

Authorize a new tooling freeze (F1.1) that:

1. excludes the mandated `<campaign>/compile-source` worktree from
   `verify_inventory`'s evidence walk (it is never sealed or archived), and
2. uses one canonical host-fingerprint input set — `allowed_cpus_before_pin` —
   identically in the controller and the independent verifier.

Then execute a fresh control and, only if it verifies and qualifies, the two
paired campaigns. The current `d3bf1-base-aa-01` evidence must not be
reclassified, repaired or archived as official evidence.
