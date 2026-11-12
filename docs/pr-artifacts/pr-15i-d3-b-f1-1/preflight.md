# PR 15I-D3-B-F1.1 — preflight

Executed before creating the F1.1 tooling copy. No source or tooling changed.

## Preflight commands and results

| Command | Result |
|---|---|
| `git status --short` | empty (clean) |
| `git branch --show-current` | `dev/pr15i-d3b-retained-key-prefilter` |
| `git rev-parse HEAD` | `b1c72a2498d7330be714926753ef045b7f8e7117` |
| `git rev-parse main` / `origin/main` | `39dbd9f571a58bea8cc03d5a406533298e809bfe` / same |
| `git cat-file -t 39dbd9f5…`, `48d9abf3…`, `ac45c23f…`, `155ebafa…` | `commit` for each |
| `git merge-base --is-ancestor 39dbd9f5… 48d9abf3…` | exit 0 |
| `git diff --exit-code 155ebafa… -- benchmarks/pr15i_d3_b` | empty |
| `git diff --exit-code ac45c23f… -- benchmarks/pr15i_d3_b_f1` | empty |
| `git show 48d9abf3…:crates/…/unified.rs \| sha256sum` | `493f93825e77581833a26c6436c5ea35aed26fc453eb2cbcec80733710ec183c` |
| `sha256sum benchmarks/pr15i_d3_b_f1/protocol_v1.json` | `4d55ea0577f2779a48f007c4e14adf56538c8ded4a86d8ca3e4d8194215657cd` |
| `sha256sum benchmarks/pr15i_d3_b_f1/tooling_manifest.json` | `6ac5f26743a3cf58880db2090839d6d25befee0724859265a5ff57d8367ad7e0` |

`main`/`origin/main` still equal the fixed BASE; the branch HEAD equals the
plan's authoring HEAD; the two historical tooling directories diff empty.

## Source identities

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` (`MAIN_PR97_BASE`) |
| Candidate | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Candidate `unified.rs` SHA-256 | `493f9382…` (Git blob at the candidate commit) |
| BASE `unified.rs` SHA-256 | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| Historical D3-B T0 | `155ebafafa29fb0e6b6cbf953f89445f4880fd2f` |
| Historical F1 T1 | `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82` |
| F1 control | `target/pr15i-d3-b/fixup-f1/d3bf1-base-aa-01`, `CONTROL_QUALIFIED` (controller only), 59 sealed members, `compile-source/` present, no `verification.json` |
| Historical D3-B archive | `d3b-base-aa-01.tar.gz`, SHA-256 `563a5cf02674dacd71286796dcffcb0760098a0adec8db5434edbd60b3d973fc` |

## Source census (candidate)

Three retained-duplicate checks, four admission routes, `heap_admit_candidate`
returning `SearchResult<bool>`, and zero rejected D1-C1/C2 design symbols, as
recorded and re-verified in `docs/pr-artifacts/pr-15i-d3-b/` and the F1
documents. No production source, test, Cargo file, corpus or adapter change is
authorized by F1.1.

## Confirmed F1 defects (read-only inspection)

| Defect | Location | Observation |
|---|---|---|
| F11-R1 | `benchmarks/pr15i_d3_b_f1/verify.py::verify_inventory` | Only `build`, `indexes`, `corpus` are excluded; the mandated top-level `compile-source/` is reported as an unlisted member (`V_INVENTORY`). |
| F11-R2 | `benchmarks/pr15i_d3_b_f1/run.py::host_fingerprint` vs `collect_host_attestation` | The attestation writes `allowed_cpus_before_pin`, but the shared fingerprint reads `allowed_cpus`; the sealed digest silently omits the allowed CPU set and disagrees with the verifier. |

The frozen F1 files were not modified to demonstrate either defect.

## Host and toolchains

WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64, 12 CPUs, Intel
i7-10750H, native ext4. `rustc 1.98.1 (48a229cea 2026-09-01)`,
`cargo 1.98.1`, `cargo +1.85.0` 1.85.0, Python 3.12.3, cargo-llvm-cov 0.9.1,
git 2.43.0, util-linux `findmnt` 2.39.3. Host assumed idle; real contention
probes and affinity observations remain mandatory.

## Applied rules

`F11-01` (branch/HEAD as documented), `F11-04` (candidate blob matches),
`F11-06` (historical control present with the original seal), `F11-07` not
triggered (all originals present).
