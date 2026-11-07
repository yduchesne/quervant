# PR 15H-E — precondition blocked

**Status: `E_PRECONDITION_BLOCKED`.**

PR 15H-E production/tooling/baseline/campaign work was **not started**. The
mandatory predecessor gate (D closeout + exact-checkpoint hosted CI) could not be
satisfied because a PR cannot be created with the available credentials.

## D closeout verified locally

| Item | Value |
|---|---|
| D final HEAD | `b05216ee83430d4e15373912aeaf0bd18bd27d97` |
| D closeout commit | `7878caaeed8ee7a3b9dfef3191a1f57e0bd3ffcd` |
| C correction | `d4b10c18a0a906f9f22f169c6437e3f82e796401` |
| D tooling / A | `c802f965a57d5038e98006bba581c4356654baaf` |
| D candidate / rollback | `0f97779…` / `2ac85c7…` |
| D source equality | `git diff --quiet c802f96 HEAD -- unified.rs unified_plan.rs` exit 0 |
| D baseline seal | `72c8d17d…` (`--verify-only` PASS) |
| D paired seal | `902d8432…` (`--verify-only` PASS) |
| D controller tests | 49 PASS |
| D closeout diff | D docs + `BENCHMARKING.md`/`PERF_OPTIMIZATION_PLAN.md` only; no E files |

The D closeout commit was pushed non-forced to
`origin/dev/pr15h-a-linear-term-candidates` (`b05216e..7878caa`).

## Exact-checkpoint hosted CI unavailable

- GitHub API shows **0 pull requests** for the branch (`state=all`).
- GitHub API shows **0 check runs** at `7878caa`.
- `.github/workflows/ci.yml` triggers only on `push: branches: [main]` and
  `pull_request`; a non-main branch push does not start CI.
- `gh pr create` and `gh pr list` fail with **HTTP 401 Bad credentials**; no
  `GITHUB_TOKEN`/`GH_TOKEN` is present in the environment.
- No PR could be created, so `rust`/`msrv`/`rustfs` cannot run at the exact D
  closeout SHA. No CI result is claimed.

## Classification and smallest human action

This is **E-D09 → `E_PRECONDITION_BLOCKED`**: D hosted CI is mandatory before E
production. No E production file, E tooling, E baseline or E campaign was
modified or executed.

Required human action (one of):

1. Authenticate `gh` with a valid token (`gh auth login`) or create/update a PR
   from `dev/pr15h-a-linear-term-candidates` to `main`, then run the exact
   `rust`/`msrv`/`rustfs` jobs at `7878caa` (or the then-current D closeout SHA).
2. Provide an authorized CI trigger/token; then re-execute the E plan from
   stage E1 (E tooling, A baseline, candidate, correctness, size/latency
   campaign).

Human review of D can remain pending while E local work would proceed; but E
production is blocked until the exact-checkpoint CI gate passes (E-D00/E-D09).

## Residual risk

D remains a rejected, source-exactly rolled-back experiment; E has no measured
result, no v2 dictionary code, and no size/latency disposition.
