# PR 15I-D0 preflight

**Status: `15ID0_BLOCKED`.**
**Disposition: no timing measurement was produced.**

## 1. Source lock

| Item | Observed |
|---|---|
| Pinned BASE | `7237bce325834d6cc1c73735697be29bc60ef16b` — *Merge pull request #91 from yduchesne/dev/pr15i-c-postings* |
| `origin/main` at execution | `4606f92e32f7d7e2419ad9a52888910747c1a44b` — *Merge pull request #92 from yduchesne/docs/pr15i-c-closeout-20261109* |
| BASE ancestor of `origin/main` | yes |
| Complete `BASE..origin/main` diff | `docs/BENCHMARKING.md`, `docs/ROADMAP.md`, `docs/pr-artifacts/pr-15i-0/architecture-15i-c.md`, `docs/pr-artifacts/pr-15i-c/closeout.md` |
| Protected diffs (`crates/`, `benchmarks/`, `Cargo.toml`, `Cargo.lock`, `.github/`, `AGENTS.md`) | zero |
| Decision rule | `D0-X83` applied: measure pinned BASE; later docs-only advance recorded for maintainer merge reconciliation |
| PR #92 | separate docs closeout; **not** merged or cherry-picked into the D0 branch |
| D0 branch | `dev/pr15i-d0-attribution-02` (the pre-existing `dev/pr15i-d0-attribution` ref existed, so `D0-X05` selected `-02`; `-02` was free) |
| D0 branch parent | `7237bce` (BASE) |
| Protected-path diff of the D0 branch | zero; `crates/`, `benchmarks/pr15d/`, `benchmarks/pr15i_c/`, `Cargo.toml`, `Cargo.lock`, `.github/` untouched |

No worktree was reset, re-based or force-pushed. The pre-existing
`dev/pr15i-d0-attribution` ref was left untouched.

## 2. Verified source anchors

All anchors in the plan were verified at BASE by exact, single-occurrence string
search inside the prescribed function regions:

| File | Anchor / symbol | State |
|---|---|---|
| `crates/quervant-core/src/search/unified.rs` | `execute_unified`, `collect_mixed`, `keyword_sort_late_eligible`, `impl Debug for UnifiedSearcher` | present |
| `crates/quervant-core/src/search/execute.rs` | `evaluate_lexical_with`, `visit_lexical_membership_with`, `mod budget_tests` | present |
| `crates/quervant-core/src/search/mod.rs` | `#[cfg(test)] mod diagnostics;` | present |
| `crates/quervant-core/Cargo.toml` | `[features]`, `default = ["stored-lz4"]` | present |
| `benchmarks/pr15d/adapters/quervant/src/main.rs` | `let result: Result<Value, AdapterError> = match op {`, `"metadata" =>` | present |

One mechanical compile-path addition was required and is recorded in the
decision log: Rust resolves a sibling module as `super::d0_probe`, not
`d0_probe`, inside `search/unified.rs` and `search/execute.rs`. The patcher adds
`use super::d0_probe;` to those two files in addition to the prescribed timer
statements. No algorithm, signature, scoring, cache, codec, reader or
cancellation behavior changed. The independent source proof still reverses every
inserted byte to BASE.

## 3. Host and toolchains

| Item | Observed |
|---|---|
| OS | Ubuntu 24.04.5 LTS on WSL2 (`*-microsoft-standard-WSL2`) |
| Filesystem | native `ext4` (findmnt; not overlay/NTFS) |
| CPU | Intel Core i7-10750H, 12 logical CPUs, affinity `0-11` |
| `taskset` | present; real pin test succeeded |
| Python | 3.12.3 |
| Rust stable | 1.98.1 (LLVM 22.1.8) |
| MSRV toolchain | 1.85.0 |
| rustfmt | 1.9.0-stable |
| JDK | OpenJDK 21.0.12.1 |
| Gradle wrapper | present with verified checksum manifest |
| `perf` / `heaptrack` | both present locally (optional evidence only) |
| `cargo-llvm-cov` | 0.9.1 |

The host was idle at preflight. No package was installed, no toolchain was
swapped and no dependency was upgraded.

## 4. Corpus and protocol

`target/pr15i-d0/corpus-src` was generated with the unmodified PR 15D generator.
The re-derived manifest SHA-256 is

```text
69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151
```

which matches the frozen protocol literal exactly. Protocol SHA-256:

```text
488985fe1b6bf10f3e7538546a50a5f40ddd3287cb91d6b3c9f6c04ee21839cb
```

Preflight source-artifact hashes (relative paths only) are recorded in the local
`target/pr15i-d0/preflight-01.json`. Two are operationally decisive:

| Artifact | SHA-256 |
|---|---|
| `benchmarks/pr15d/adapters/quervant/Cargo.lock` | `050f9d751f978277e02057a0002d1b87d6f0166d73dcadab93f4e78e26cb817d` |
| `crates/quervant-core/Cargo.toml` | `38d34224ff5ca87d5dbbde8f42216326a51593e31f37675d4d44a0030e2dfc1a` |

## 5. Blocking environment/source condition

`crates/quervant-core` declares `default = ["stored-lz4"]` and the optional
dependency `lz4_flex`. The standalone PR 15D Quervant adapter depends on
`quervant-core` with default features enabled, but its frozen `Cargo.lock` at
BASE does not contain `lz4_flex` or `twox-hash`. Both the official PR 15D
harness (`cargo build --release --locked`) and the prescribed A/Q/P build
therefore fail closed:

```text
error: cannot update the lock file .../benchmarks/pr15d/adapters/quervant/Cargo.lock
because --locked was passed to prevent this
```

A controlled `--offline` diagnostic build (a disposable lock-check worktree, not
used for timing) shows the only lock delta is the two already-declared lz4
dependencies:

```text
+ lz4_flex 0.11.6
+ twox-hash 2.1.5
```

The plan explicitly forbids fixing this by updating `Cargo.lock` (§6.2), editing
a frozen benchmark under `benchmarks/pr15d`, or substituting a different
baseline. `D0-X33` therefore records a build blocker and `D0-X71` classifies the
result as **BLOCKED**, with no fabricated substitute measurement.

A separate compile smoke (disposable worktree, lock updated only for the smoke)
proved that the instrumented derivative compiles with
`--features quervant-core/pr15id0-probe`. That smoke is **not** measurement
evidence and is not used for any ratio.

## 6. Risk challenge (plan §9.3)

| Wrong-but-plausible implementation | Why prohibited | D0 guard |
|---|---|---|
| Treating Quervant's BM25 execution and Tantivy's `Basic` numeric-sort lane as physically equivalent | only logical oracle equivalence is observed | every ratio table carries the physical-operator caveat; no scored ratio |
| Reusing the old PR 15I-C probe that rejected zero-hit queries or used a different projection | absent lanes are first-class and the frozen adapter is untouched | absent/zero-hit lane is oracle-validated by both controller and verifier |
| Letting the recorder time files/JSON output or count nested timers twice | `engine_ns` must stop before probe export; nested spans are subtracted | probe code runs after `engine_ns`; verifier requires non-negative residual and exact partition |
| Editing `collect_mixed`/`score_segment` instead of measuring them | would change the algorithm under test | insertion-only patch + independent byte reversal + `#[inline]`/`pub` checks |
| Calling the instrumented source an “unmodified baseline” | A and Q/P are distinct binaries | A/Q/P binary SHA and mode proof gates |
| Comparing 2026-10-31 PR 15I-0 numbers to fresh main as controlled pre/post evidence | different source/host/format | historical numbers labelled `NOT_CONTROLLED` and never reported as current |
| Claiming a cache opportunity is solved without checking fallback rates | `VerifiedSegmentState` does not prove caller fallback | D0 measures only; no cache change is proposed |
| Deleting failed/contended raw data or remeasuring selected slots | destroys evidence and biases ratios | append-only sealed evidence; one full repeat only under `D0-X17` |

## 7. Artifacts (local only)

All raw evidence is under ignored `target/pr15i-d0/`:

- `preflight-01.json`
- `build-01.log`
- `worktrees/canonical/target/pr15i-d0/canonical-run.status` and run logs
- `worktrees/canonical/target/pr15i-d0/canonical-three-engine-01/` (incomplete)
- `diag-lockcheck/` (deliberately dirty lock diagnostic; never timed)

No raw host path, credential or absolute source checkout is committed to Git.
