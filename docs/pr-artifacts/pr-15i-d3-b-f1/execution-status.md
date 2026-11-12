# PR 15I-D3-B-F1 — execution status

**Disposition: `D3BF1_MEASUREMENT_BLOCKED`.**

| Item | State |
|---|---|
| Branch | `dev/pr15i-d3b-retained-key-prefilter` |
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate source | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Historical D3-B T0 | `155ebafafa29fb0e6b6cbf953f89445f4880fd2f` (untouched) |
| F1 T1 tooling freeze | `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82` |
| F1 protocol SHA-256 | `4d55ea0577f2779a48f007c4e14adf56538c8ded4a86d8ca3e4d8194215657cd` |
| F1 tooling manifest SHA-256 | `6ac5f26743a3cf58880db2090839d6d25befee0724859265a5ff57d8367ad7e0` |
| Canonical AA dry proof | PASS (`4994d273…` == `4994d273…`) |
| Canonical AB dry proof | PASS (`81bacb88…` != `3b2f17fc…`) |
| Control 01 | `MEASUREMENT_BLOCKED` — controller `CONTROL_QUALIFIED`, independent verifier FAIL (`V_INVENTORY` then `V_HOST`), both from frozen F1 tooling defects |
| Control 02 | NOT_RUN (retry not authorized for tooling/structural failure) |
| Paired 01 / 02 | NOT_RUN (no independently qualified control) |
| Independent verifier | FAIL on the sealed control; no `PASS` receipt exists |
| Production diff | Optimization retained on the unmerged measurement branch; no rollback |
| Historical evidence | Unchanged (old v1 tooling diff empty; old archive/sidecar intact) |
| Rust QA / coverage | PASS — 2,496 tests, 92.85% lines (both stable and MSRV 1.85) |
| Python QA | PASS — 95 F1 tests, 61 historical v1 tests, 83 PR15D harness tests |
| RustFS | `RUSTFS_PENDING` |
| Hosted CI | `CI_PENDING` |
| Independent review | `REVIEW_PENDING` |
| PR | `PR_NOT_CREATED` |
| Final HEAD before closeout docs | `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82` |

## What was executed

1. Reconciled the pinned BASE, candidate and historical tooling/evidence;
   confirmed the source census (three duplicate checks, four admission routes,
   `SearchResult<bool>` admission helper, zero rejected design symbols).
2. Wrote the preflight, correctness trace and test matrix before touching
   tooling; copied the D3-B tooling into an isolated F1 directory and
   implemented the canonical-path build architecture, sealed build/host/affinity
   provenance, independent Git-blob frozen-input verification, A/A/A-B binary
   identity rules, control-succession history, and the T01–T56 adversarial
   suite.
3. Ran the non-timed canonical reproducibility proof: two real BASE builds from
   one path produced byte-identical binaries; a BASE/candidate pair on one path
   produced distinct binaries.
4. Froze the F1 tooling at T1, passed preflight, and executed the mandatory
   16-slot canonical A/A control. The canonical build fix worked: 2,880 timed
   samples, 720 warmups, 32 clear contention probes, zero drift violations, all
   nine A/A medians inside bounds, and byte-identical A/B arm binaries and
   100K indexes.
5. The frozen independent verifier then failed the sealed control on two
   post-T1 tooling defects: the inventory walk does not exempt the mandated
   `compile-source/` worktree (`V_INVENTORY`), and the controller's sealed host
   fingerprint omits `allowed_cpus_before_pin` while the verifier recomputes it
   (`V_HOST`). Per §4/FDX-41/44/56 the series stopped before any paired
   campaign; no archive was published.

## What is not claimed

- No performance verdict, speed-up, regression or K10 result.
- No acceptance of the controller's `CONTROL_QUALIFIED`.
- No repair, requalification or archive of the blocked control.
- No rollback (this is a measurement block, not a qualified rejection).

## Required human decision

Authorize an F1.1 tooling freeze that (a) excludes `compile-source/` from the
verifier inventory walk and (b) unifies the host-fingerprint input key
(`allowed_cpus_before_pin`) between controller and verifier. Then run a fresh
control and, only if it independently verifies and qualifies, the two paired
campaigns. No threshold change, evidence reuse or alternative algorithm is
authorized.
