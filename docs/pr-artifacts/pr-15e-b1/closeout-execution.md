# PR 15E — Final qualification and closeout: execution record

**Status: `CLOSEOUT_EVIDENCE_READY`** with two external blockers: cumulative performance is
`PERF_BLOCKED_OPERATOR` (no genuine idle attestation for this campaign) and exact-head CI is
`CI_BLOCKED_CREDENTIALS`. G11 remains `PENDING_REVIEW`. **PR #83 was not merged.**

## 1. P0 preflight (observed)

| Item | Value |
|---|---|
| Branch | `dev/pr15e-b1-live-bitmap-postings-membership` |
| HEAD before closeout | `6f9a2017b44e9138bbe9742ada636f5ae56df0f1` (exact P6F head, clean tree) |
| Original benchmark base (arm A) | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` |
| Phase 5 production code | `9881789b6c00a14bed995a5bc7e38ae18536d125` (ancestor; `crates/` byte-identical to HEAD) |
| `origin/main` after `git fetch` | `506beb038e070aee780dacfda1b5dbb9da30b642` |
| merge-base(HEAD, origin/main) | `c3083d8…` = original base |
| P5-tail protected diff (`66b266f..HEAD`) | **0 files** (crats/frozen/profiler/tooling untouched by docs) |
| Frozen runner tests before mutation | 64 tests PASS |

## 2. P2 one permitted reconciliation (succeeded)

All predicates held: `origin/main` exactly `506beb0`; merge-base equals the original base; the
main delta is exactly the six documentation paths; no overlap with the branch's changed paths;
merge-tree check clean; branch clean at the audited head.

`git merge --no-ff --no-edit 506beb0…` →

| Item | Value |
|---|---|
| Merge commit (`OPT_SHA`) | `40ca10bae46f2d7df7804a0a129a99a4daf35ef0` |
| Parents | `6f9a201…` (PR tip) and `506beb0…` (main) |
| Tree after merge | clean |
| Protected delta vs pre-merge tip (`crates/ benchmarks/ Cargo.toml Cargo.lock .github/`) | **0 files** |
| Six integrated docs identical to `main` | `README.md`, `docs/INTEGRATION_ROADMAP.md`, `docs/ROADMAP.md`, `docs/integrations/iceberg/{FEDERATION,README,SYNC}.md` — all **SAME** |
| `crates/` identical to Phase 5 code SHA | 0 files differ |

## 3. P1 source audit

Production files changed by the whole PR (vs the original base): `search/execute.rs`,
`search/unified.rs`, `segment/{value,stored,reader}.rs` plus test-only files
(`segment/tests.rs`, `tests/pr14_projection.rs`, `tests/pr15e_b1.rs`). No changes to
`segment/format.rs`, `search/{work,score,projection}.rs`, `index/`, objectstore, distributed,
`Cargo.toml`/`Cargo.lock`, `.github/`, `AGENTS.md`, frozen PR15D or PR15E tooling (0 files).

Full PR #83 file inventory (36 paths at the pre-merge tip) is the five implementation files,
their test files, the runner/tooling and benchmark stages (`benchmarks/pr15e_b1/*`), the
sanitized comparison reports, and the phase evidence documents. No production commit exists
after the Phase 5 code SHA; everything later is tooling, evidence or documentation.

G11: `docs/pr-artifacts/pr-15e-a/fixup-review-handoff.md` still records `G11 = PENDING_REVIEW`;
no independent reviewer verdict and **no merge-specific waiver** exists anywhere in the tree.

## 4. P3 benchmark preparation (untimed) and timing status

Two clean worktrees were created under `target/pr15e-b1/closeout-worktrees/`:

| Arm | Path | SHA | State |
|---|---|---|---|
| A — original base | `…/baseline` | `c3083d8…` | clean, frozen hashes verified |
| B — cumulative optimized | `…/optimized` | `40ca10b…` | clean, frozen hashes verified |

`run_targeted.py --stage final` was inspected and has exactly the nine F01–F09 lanes with
3 trials × (5 warmups + 20 samples). The stage's historical `B1 final` label is a legacy
runner label only; the measured arm identity is `40ca10b…` (B1 + Phase 3 + Phase 4 + Phase 5
cumulative head).

**Timing: `PERF_BLOCKED_OPERATOR`.** This campaign requires a genuine, contemporaneous operator
assertion that the host is idle. The earlier B1/Phase 3/Phase 5/Phase 6 authorizations are
historical and their windows are expired; no current attestation was given for this final
campaign, and the agent may not fabricate one. No `--idle-confirmed` invocation was made, neither
arm was timed, and therefore **no cumulative benchmark claim or JSON is published**.

## 5. P4 QA on the reconciled head (`40ca10b`)

Toolchains: stable `cargo 1.98.1` (CI-pinned), MSRV `cargo 1.85.0`. Logs under
`target/pr15e-b1/closeout-qa/` (gitignored).

| # | Command | Result |
|---|---|---|
| 01 | `cargo fmt --all -- --check` | PASS (0) |
| 02 | `cargo +1.85.0 fmt --all -- --check` | PASS (0) |
| 03–06 | clippy `--workspace --all-targets` ± `--all-features`, stable + MSRV | PASS (4/4) |
| 07 | `git diff --check` | PASS |
| 08 | `bash benchmarks/scripts/test-scripts.sh` | PASS (108/108) |
| 09 | `python3 -m unittest discover -s benchmarks/pr15e_b1` | PASS — 64 tests |
| 10 | `python3 -m unittest discover -s benchmarks/pr15e` | PASS (1 skipped) |
| 11 | `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS |
| 12 | `cargo test --workspace --all-targets` | PASS — 2227 passed, 0 failed, 10 ignored |
| 13 | `… --all-features` | PASS — 2231 passed, 0 failed, 75 ignored |
| 14 | `cargo +1.85.0 test --workspace --all-targets` | PASS — 2227 / 0 / 10 |
| 15 | `… --all-features` | PASS — 2231 / 0 / 75 |
| 16–17 | frozen PR15D adapter tests (stable + MSRV, `--locked`) | PASS — 5 each |
| 18 | `cargo bench --workspace --no-run` | PASS (compile only) |
| 19 | `cargo doc --workspace --all-features --no-deps` | PASS |
| 20 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **lines 92.52 %** (85,694 lines, 6,410 missed), functions 88.08 %, regions 92.00 % |
| 21 | PR15E real-adapter integration (`PR15E_RUN_REAL_INTEGRATION=1`) | PASS — recorded `source_sha = 40ca10b…` |
| 22 | Real RustFS acceptance (25 invocations, §6) | PASS — 25/25 |

## 6. Real RustFS acceptance (local podman, pinned image, exact CI commands)

Service: `rustfs/rustfs@sha256:1803faef…` (the pinned CI digest), CI credentials and bucket,
endpoint `http://127.0.0.1:9000`, region `us-east-1`, health check green before the first test.
Docker is not installed in this environment; **podman** was used with the identical image digest,
environment and command lines, and this is disclosed as a **local substitution, not hosted CI**.

**25 invocations, all exit 0**: `pr13_s3_rustfs` (8 tests), `pr13_proxy_rustfs` (5),
`pr13_remote` (3), `pr13_oracle` (1), `pr13_oracle_geo` (1), `m1_batches` (1), `m2_patches` (1),
`m3_delete_by_query` ×3 (1 each), `m5_mutation_qualification` ×3 (1 each),
`pr13_remote_proxy` (7), `pr13_crash_rustfs k0` (5), `pr13_crash_rustfs k05` ×10 (1 each).
The container started by this task was removed afterwards; no other container was touched.

**Reporting erratum (25 vs 26):** historical Phase 3/4/5 reports describe “26 invocations”. The
checked-in CI command list contains **25** `cargo test` process invocations (7 individual +
M3×3 + M5×3 + proxy×1 + k0×1 + k05×10). This closeout used exactly the checked-in CI list and
itemsed all 25; the earlier “26” is a counting error in the older reports, which are left
byte-identical. No 26th invocation was invented.

## 7. Blocked gates and exact next actions

| Gate | State | Needed to close |
|---|---|---|
| C06 cumulative performance | `PERF_BLOCKED_OPERATOR` | A genuine, current operator idle assertion for this campaign; then run the two `--stage final` commands on the prepared worktrees |
| C09 exact-head CI | `CI_BLOCKED_CREDENTIALS` | Working GitHub credentials; push the final closeout commit and require `rust`/`msrv`/`rustfs` green on that exact SHA |
| C10 G11 | `PENDING_REVIEW` | Independent named reviewer verdict per RV-01–RV-08, **or** an explicit merge-specific maintainer waiver naming G11 and its risks |
| C12 maintainer signoff | `MERGE_PENDING_MAINTAINER` | Maintainer review of this evidence |

## 8. Failure log

No deterministic QA failure occurred. The only failed/blocked attempts are the two external
dependencies above (no idle attestation; no GitHub credentials). No test was skipped, weakened
or retried to green; the RustFS service substitution and the 25-vs-26 count are disclosed rather
than smoothed over.
