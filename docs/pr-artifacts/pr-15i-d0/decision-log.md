# PR 15I-D0 decision log

Every entry is an immutable record of an applied rule, the observed trigger, the
authorized action, the prohibited action that was **not** taken, the affected
gate and the owner of any unresolved decision. Raw evidence paths are local and
relative to the repository root.

## D0-X83 — docs-only advance of `origin/main`

| Field | Value |
|---|---|
| Rule | `D0-X83` (AUTO-RESOLVE) |
| Stage | P0 |
| Trigger | `origin/main = 4606f92e…`; BASE `7237bce…` is an ancestor; the complete intervening diff is exactly `docs/BENCHMARKING.md`, `docs/ROADMAP.md`, `docs/pr-artifacts/pr-15i-0/architecture-15i-c.md`, `docs/pr-artifacts/pr-15i-c/closeout.md`; protected paths identical |
| Source identity | `7237bce325834d6cc1c73735697be29bc60ef16b` |
| Evidence | `git diff --name-only 7237bce… origin/main`; `target/pr15i-d0/preflight-01.json` |
| Authorized action | Continue measuring pinned BASE; record docs-only advance |
| Prohibited action not taken | Re-basing or repinning to new `main`; merging PR #92 |
| Affected gate | `D0-P00 SOURCE` |
| Owner | Maintainer must reconcile the closeout-docs merge before merging D0 |

## D0-X05 — branch namespace

| Field | Value |
|---|---|
| Rule | `D0-X05` (AUTO-RESOLVE) |
| Stage | P0 |
| Trigger | `dev/pr15i-d0-attribution` already existed (created from `origin/main`); `dev/pr15i-d0-attribution-02` was free |
| Source identity | BASE |
| Evidence | Git branch/reflog inventory |
| Authorized action | Create only `dev/pr15i-d0-attribution-02` from BASE |
| Prohibited action not taken | Reset, force-push or overwrite the existing ref; branch from PR 15I-C source |
| Affected gate | `D0-P00 SOURCE` |
| Owner | Coding agent |

## D0-X07 — clean canonical worktree

| Field | Value |
|---|---|
| Rule | `D0-X07` (AUTO-RESOLVE) |
| Stage | P1 |
| Trigger | Detached `target/pr15i-d0/worktrees/canonical` at BASE with empty status |
| Evidence | Git worktree list and status |
| Authorized action | Run the official PR 15D harness |
| Prohibited action not taken | Timing from a dirty or staged tree |
| Affected gate | `D0-P02 CANONICAL` |
| Owner | Coding agent |

## D0-X12 / D0-X33 — canonical and paired builds fail on the frozen adapter lock

| Field | Value |
|---|---|
| Rule | `D0-X12` (HARD STOP for the canonical line) and `D0-X33` (DEFER the build blocker; do not upgrade the lock) |
| Stage | P1 / P2 |
| Trigger | `run.py` exits 5 with `X15_BUILD_FAILED`; `run.py build` exits 3 with `D0_BUILD`; both report `--locked` refusing to update `benchmarks/pr15d/adapters/quervant/Cargo.lock` |
| Observed source defect | BASE adapter lock SHA `050f9d75…` lacks `lz4_flex 0.11.6` and `twox-hash 2.1.5`, required by `quervant-core`'s default `stored-lz4` feature |
| Evidence | `target/pr15i-d0/worktrees/canonical/target/pr15i-d0/canonical-run.log`; `target/pr15i-d0/build-01.log`; disposable lock-check worktree `target/pr15i-d0/diag-lockcheck` (deliberately dirty; never timed) |
| Authorized action | Preserve the failed canonical run as `INVALID`/incomplete; record a build blocker; continue independent tooling, tests and documentation |
| Prohibited action not taken | Update `Cargo.lock`; edit a frozen benchmark; drop an engine; change trials; substitute a fake measurement; reuse historical ratios as current |
| Affected gate | `D0-P02 CANONICAL`, `D0-P03 PATCH` (build), `D0-P04 BUILD`, `D0-P07 CAMPAIGNS` |
| Owner | Maintainer: authorize an updated frozen adapter lock (or repin) before any measurement rerun |

## Mechanical compile-path addition (deviation requiring review)

| Field | Value |
|---|---|
| Classification | `D0-X27`-adjacent mechanical compiler fix; **not** an architecture or algorithm decision |
| Stage | P2 |
| Trigger | The plan's literal timer statements use `d0_probe::…` inside `search/unified.rs` and `search/execute.rs`, but Rust resolves a sibling module only as `super::d0_probe` (there is no local `d0_probe` module, unlike the local `plan` module) |
| Authorized action | Materializer adds exactly one `use super::d0_probe;` import to each of those two files in the scratch tree |
| Prohibited action not taken | Rewriting the recorder, changing a crate API, moving existing code, changing a timer statement |
| Evidence | `source_proof.py` rebuilds BASE + approved insertions + rustfmt and compares bytes; reverse deletion restores BASE; tests `S.*`; a disposable compile smoke with `--features quervant-core/pr15id0-probe` succeeded |
| Affected gate | `D0-P03 PATCH`, `D0-P04 BUILD` |
| Owner | Reviewer must accept or reject this two-line addition before any measurement rerun |

## D0-X20 — frozen nine-lane set

| Field | Value |
|---|---|
| Rule | `D0-X20` (AUTO-RESOLVE) |
| Stage | P2 |
| Trigger | Protocol lane IDs/order match the plan's nine lanes exactly |
| Evidence | `R.ScheduleAndLaneTests.test_nine_lane_order`; `protocol_v1.json` |
| Authorized action | Freeze the lane matrix in controller and verifier |
| Prohibited action not taken | Adding or reordering benchmark lanes |
| Affected gate | `D0-P01 CORPUS` |
| Owner | Coding agent |

## D0-X23 — source derivation reverse proof

| Field | Value |
|---|---|
| Rule | `D0-X23` (AUTO-RESOLVE) |
| Stage | P2 |
| Trigger | Independent rebuild of BASE + insertions + rustfmt equals the scratch tree; deleting insertions restores BASE; changed-path set is exactly six |
| Evidence | `target/pr15i-d0/source-proof-01.json` (local); `S.test_verify_derivative_accepts_the_approved_derivative`; derivative fingerprint `09d7b8cd…` |
| Authorized action | Approve the source derivation for a future build |
| Prohibited action not taken | Accepting a patch that changes an accepted line or a seventh path |
| Affected gate | `D0-P03 PATCH` |
| Owner | Coding agent / reviewer |

## D0-X34 / D0-X36 / D0-X38 — host admission

| Field | Value |
|---|---|
| Rule | `D0-X34`, `D0-X36`, `D0-X38` (AUTO-RESOLVE) at preflight |
| Trigger | native `ext4`; 12 allowed CPUs; `taskset` real pin works; host idle |
| Evidence | `target/pr15i-d0/preflight-01.json` |
| Authorized action | Proceed to the next gate |
| Prohibited action not taken | Accepting overlay/NTFS or floating affinity |
| Affected gate | `D0-P07 CAMPAIGNS` |
| Owner | Coding agent |

## D0-X71 — both measurement lines blocked

| Field | Value |
|---|---|
| Rule | `D0-X71` (HARD STOP; report `15ID0_BLOCKED`) |
| Stage | P5 |
| Trigger | Canonical three-engine campaign blocked at adapter build; paired A/Q/P campaigns blocked at the same frozen-lock build; no valid raw measurement exists |
| Evidence | This directory's reports; local `target/pr15i-d0/qa.log`; canonical run logs |
| Authorized action | Report BLOCKED with the single root cause and the smallest missing source decision |
| Prohibited action not taken | Marking D0 complete; deploying historical numbers as current; inventing stage data |
| Affected gate | `D0-P02`, `D0-P03`, `D0-P04`, `D0-P05`, `D0-P06`, `D0-P07`, `D0-P08`, `D0-P09`, `D0-P10`, `D0-P11` |
| Owner | Quervant maintainer |

## D0-X79 — external publication

| Field | Value |
|---|---|
| Rule | `D0-X79` (DEFER AND CONTINUE) |
| Stage | P5 |
| Trigger | Local Git authentication for push/PR is not assumed; no fabricated PR number is permitted |
| Authorized action | Record the branch/commit handoff; report local-only state |
| Prohibited action not taken | Force-push, bypass permissions, invent a PR |
| Affected gate | `D0-P15 EXTERNAL` |
| Owner | Maintainer |

## Discarded or incomplete attempts (preserved, never promoted)

| Attempt | Disposition | Path |
|---|---|---|
| Canonical three-engine run `canonical-three-engine-01` | INVALID/incomplete (adapter build failed; zero trials) | `target/pr15i-d0/worktrees/canonical/target/pr15i-d0/canonical-three-engine-01/` |
| Paired build `build-01` | BLOCKED before any binary/index/sample | `target/pr15i-d0/build-01.log` |
| Lock diagnostics `diag-lockcheck` | Deliberately dirty; excluded from all timing | `target/pr15i-d0/diag-lockcheck/` |
| Compile smoke `compilecheck` | Diagnostic only; proves the scratch source compiles; no timing | `target/pr15i-d0/worktrees/compilecheck/` |
| Unit-test fixtures | Temporary, removed after each test | `target/pr15i-d0/tests/` |

No valid evidence was deleted, overwritten, re-sealed or repaired.
