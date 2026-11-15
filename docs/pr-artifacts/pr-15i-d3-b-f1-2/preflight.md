# PR 15I-D3-B-F1.2 — preflight

Verified before any F1.2 edit; no protected source or historical tooling changed.

| Check | Result |
|---|---|
| Branch | `dev/pr15i-d3b-retained-key-prefilter` |
| HEAD at start | `66cd833ef044a57cb786a7f0b1c398f6f53bf52c` |
| `main` / `origin/main` | `39dbd9f571a58bea8cc03d5a406533298e809bfe` (both) |
| Candidate commit | `48d9abf3eeefbccb480d89eac95f6e6911e078d5`; `unified.rs` blob `493f9382…` |
| BASE `unified.rs` | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| Historical T0 / T1 / T2 | `155ebafa…` / `ac45c23f…` / `63b30a0b…`; all three `git diff --exit-code` empty |
| F1.1 protocol / manifest | `ae1b7d8d…` / `f9134926…` (unchanged) |
| F1.1 archives | control `f58ef556…` (61 members), blocked paired `69c45bc4…` (63 members) |
| Working tree | only the pre-existing user modification `disk-cleanup.sh`; preserved untouched |
| Host | WSL2 `6.18.33.2-microsoft-standard-WSL2`, x86_64, 12 CPUs, Intel i7-10750H, native ext4 |
| Tools | rustc/cargo 1.98.1, cargo 1.85.0, Python 3.12.3, cargo-llvm-cov 0.9.1, git 2.43, findmnt 2.39.3 |

## F1.2 identities (computed from actual bytes)

| Item | Value |
|---|---|
| F1.2 tooling freeze T3 | `c86c3b1554cadbc11deaedf4de4f4d7247e1467c` |
| Protocol SHA-256 | `3946c1caec27127c7f53c3d10db9a9e9769f2d8f812a8bb1f4fb9551949c3a95` |
| Tooling manifest SHA-256 | `35f797515565934ff6d191bdb3c9b9fd586d9a4e161ab2b3ca13e12ce443716e` |
| Controller / verifier SHA-256 | `326ae047…` / `17f5a914…` |
| Protocol delta vs F1.1 | exactly nine top-level entries: `schema`, `study_type`, `comparisons` (key rename), `tooling_directory`, `target_subroot`, `evidence_root_relative`, `campaign_suffixes`, `host_readiness`, `paired_structural_replacement` |

## Confirmed source facts

- `benchmarks/pr15i_d3_b_f1_1/` is the T2-frozen F1.1 controller/verifier with the
  canonical single-path build, provenance, host attestation and per-slot affinity.
- F1.1's only paired campaign was structurally blocked by a 10K-rare within-block
  drift of `1.503057781526782 > 1.50`; its per-lane numbers are diagnostic only.
- The F1.1 A/A control is archived and immutable and is **not** reused as F1.2
  authorization.
- No production source, Cargo file, corpus, oracle, index format or threshold was
  changed by F1.2.
