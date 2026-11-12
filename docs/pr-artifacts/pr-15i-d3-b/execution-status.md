# PR 15I-D3-B — execution status

**Disposition: `D3B_MEASUREMENT_BLOCKED`.**

| Item | State |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` (`MAIN_PR97_BASE`) |
| Branch | `dev/pr15i-d3b-retained-key-prefilter` |
| Candidate production/tests | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Tooling freeze T0 | `155ebafafa29fb0e6b6cbf953f89445f4880fd2f` |
| Protocol SHA-256 | `8c113091507528450f9dd8f406fc3ac0a390c164b9a7a603583f48d752c6d1be` |
| A/A control | `d3b-base-aa-01` — `MEASUREMENT_BLOCKED` (structural binary mismatch), archived |
| Paired campaign 01 | NOT_RUN (`DBX-31`) |
| Paired campaign 02 | NOT_RUN |
| Production diff | Optimization retained on the unmerged measurement branch (not shipped, not rolled back) |
| Correctness | U01–U28 28/28, I01–I12 10/10 executable passed, I12 `RUSTFS_PENDING` |
| Coverage | 92.85% workspace lines (floor 85%) |
| RustFS | `RUSTFS_PENDING` (podman-compose cannot resolve the pinned image) |
| Hosted CI | `CI_PENDING` |
| Independent review | `REVIEW_PENDING` |
| PR | `PR_NOT_CREATED` |

## What was executed

1. **Preflight:** verified the pinned BASE, source anchors, clean branch, frozen
   PR15D inputs, native ext4 host, toolchains and the four-admission-call /
   three-check-site census. Wrote the design/correctness trace, preflight and
   test matrix before the production edit.
2. **Implementation:** added the request-local two-probe 1,024-bit monotonic
   prefilter, the exact-backed `check_retained_duplicate`, the boolean admission
   result and the three call-site integrations; 28 unit tests and 10 executable
   production-path integration tests (plus one ignored RustFS test) were added.
3. **QA:** formatting, stable and MSRV Clippy/format/tests/docs, workspace
   coverage, Python tooling tests, the PR15D harness tests and `git diff --check`
   all passed on the final code state.
4. **Measurement:** froze tooling at T0, ran preflight successfully and executed
   the mandatory A/A control. The control passed every numerical A/A ratio
   (0.9380–1.0969 medians), every soft/hard bound and all drift checks, but the
   two BASE worktrees produced different adapter binaries
   (`cdc434c8…` vs `d0847853…`), a structural identity failure. Per `DBX-31`
   the series stopped before any paired campaign; the control was independently
   verified (`PASS`, status `MEASUREMENT_BLOCKED`) and archived.
5. **Closeout:** recorded the blocker, published the sealed control evidence
   with a SHA-256 sidecar, and documented that no performance verdict exists.

## What is explicitly not claimed

- No speed-up or regression on any of the nine lanes.
- No K10 regression or K10 protection claim.
- No end-to-end conversion of the D3-A-F2 sampled-child shares.
- No correctness or performance rejection; the failure is measurement-only.

## Unresolved risks

- The A/A binary-identity requirement and the prescribed two-worktree design are
  mutually unsatisfiable in this environment without a reviewed build
  reproducibility decision. A future attempt needs a new authorized freeze.
- RustFS/S3 cold-bootstrap parity for this shared `unified.rs` path is unverified.
- The candidate stays on an unmerged branch; a human must decide whether to
  revise the control design, abandon D3-B, or authorize a new plan.
- Post-T0 review found two independent-verifier coverage gaps (frozen-input/
  adapter-lock re-hashing and affinity/native-filesystem re-derivation from
  sealed evidence). They are deferred to an authorized tooling fixup and do not
  affect the blocked outcome; see `qa.md` and `decision-register.md` (DBX-28).
