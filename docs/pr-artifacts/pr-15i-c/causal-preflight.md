# PR 15I-C causal experiment — preflight

Status: `PREFLIGHT_COMPLETE`
Recorded: 2026-11-08

## 1. Repository and identities

| Item | Value |
|---|---|
| Branch | `dev/pr15i-c-postings` |
| HEAD at start (`START`) | `8541c8edcf70f84c89cbea6ea6dc4c711446ec84` |
| `main` / merged accepted base (`BASE_A`) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| Historical outside-dispatch candidate (`OLD_B`) | `92a741876f6f6823d9d1792fc391dbb1bbecceb0` |
| Historical in-generic candidate | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| Old generic control | `50b56e9fe7b22bb266ca7b0d9e209500dfc785ff` |
| Working tree | clean |

`git merge-base --is-ancestor BASE_A HEAD` → 0; every pinned commit resolvable;
`git diff --quiet BASE_A HEAD -- <production/Cargo/lock/CI/PR15D/PR15I-A/PR15I-B>`
empty. The four frozen protocol files are byte-identical to `START`
(`protocol.json` `5464144…`, `noise_protocol_v1.json`, `noise_protocol_v2.json`,
`batched_protocol_v1.json` `171c30c0…`) — they are new relative to `BASE_A`
because they were added by earlier follow-ups, not by this experiment.

## 2. Toolchain, host and external boundaries

| Item | Value |
|---|---|
| `rustc` / `cargo` / MSRV | `1.98.1` / `1.98.1` / `1.85.0` |
| `python3` | 3.12.3 |
| CPUs allowed | `0..11` |
| `taskset` / `nm` / `objdump` | present |
| Native filesystem of `target/` | `ext4` |
| Container runtimes | `docker` absent, `podman` present (unused: no pinned image access verified) |
| `perf` | unavailable on this kernel → `PERF_UNAVAILABLE`, no counter claims |
| Real RustFS | `REAL_RUSTFS_BLOCKED` (see `causal-execution-status.md`) |

## 3. Baseline QA before any modification

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 check --locked -p quervant-core` | PASS |
| `cargo test --locked -p quervant-core --lib search::execute::budget_tests` | 40 passed |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | 245 passed |
| `git diff --check` | clean |

Known historical exception: `benchmarks/pr15i_a::RealCampaignTests` 1F/3E,
reproduced at merged `BASE_A` in earlier sessions with the same raw data →
`SOURCE_BOUND_HISTORICAL_ONLY` (`CA-D14`), never edited or counted green.

## 4. Source facts verified at the pinned SHAs

| Fact | Verified |
|---|---|
| `collect_mixed` normalized body SHA = `00c5a1c8…` at `BASE_A` and at `OLD_B` | yes |
| `OLD_B::execute_unified` dispatches outside `collect_mixed` | yes |
| `OLD_B::collect_exact_term_physical` is private with `#[inline(never)]` | yes |
| `execute::for_each_exact_term_score_with` present at `OLD_B` | yes |
| Candidate's 16 `n_u` + 12 `n_extra` + 6 physical + 2 failure unit tests and 12 integration tests pass after restoration | yes (`RESTORED_B_SHA`) |
| Frozen adapter `AdapterProcess` has **no** `env` parameter | yes → `CausalAdapterProcess` subclass in `causal_run.py` only |
| `--features quervant-core/pr15ic-causal` builds the frozen adapter offline | yes (verified before sampling) |

## 5. Stage 1 — restored candidate (`RESTORED_B_SHA`)

`b32523b9bb182190cb8260b00c3a81645314837f` restores exactly the seven historical
candidate files byte-for-byte (`git hash-object` equality against `OLD_B`). No
`Cargo.lock`, CI, harness or docs were restored.

## 6. Stage 2 — causal gate (`CAUSAL_BC_SOURCE_SHA`)

`658a2dde0e15c17e2b0c92278b5c922f5260fe60` adds only the empty non-default
`pr15ic-causal` feature and the `OnceLock` mode gate in `execute_unified`.
Verified behaviour on the built adapter: `enabled`/`disabled` succeed with the
oracle response, while an unset or malformed mode is a typed
`corrupt index state: invalid PR15IC causal experiment mode` error.

## 7. Next state transition

`PREFLIGHT_COMPLETE` → P3 tooling freeze, then P4 pre-measurement verification,
then the four fixed campaigns.
