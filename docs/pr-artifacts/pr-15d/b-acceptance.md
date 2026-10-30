# PR 15D-B — acceptance checklist

**Current disposition: `PENDING REVIEW` / partially `BLOCKED`.**

No item below may be marked complete on the strength of a local test alone.

| # | Checklist item | State | Evidence |
|---|---|---|---|
| 1 | A1 prerequisite (PR #79) verified | **PASS** | `b-preflight.md`; source lock `8caca76…`; run `41124428333` `pr15d-adapters` = success |
| 2 | No production or frozen contract diff | **PASS** | diff limited to `ci.yml`, new workflow, `smoke.py`, `test_pr15d.py`, `benchmarks/pr15d/README.md`, `docs/pr-artifacts/pr-15d/**` |
| 3 | `ci.yml` only had the comparative job removed | **PASS** | deletion-only diff; `git grep pr15d` empty; job set `rust, msrv, rustfs` |
| 4 | Comparative workflow path + manual triggers verified | **PASS (static)** | `ComparativeWorkflowContractTests`; YAML parse of both files |
| 5 | Smoke genuinely 10K | **PASS (static + local execution)** | `comparative-smoke` passes no `--sizes`; default selector is `[10000]`; default invocation prints exactly one `n: 10000` line locally |
| 6 | On-demand full genuinely 10K/100K for all engines | **PASS (static + local execution)** | `--sizes 10000,100000` + all three adapter commands + `corpus/oracle.py` in the full job; executed locally end-to-end for both sizes (see `b-ci.md`) |
| 7 | Wrapper/locks checks preserved | **PASS** | `sha256sum -c A1-CHECKSUMS.sha256` before `./gradlew` in both jobs; T07 asserts ordering |
| 8 | No timed CI | **PASS** | T06: no `run.py`, no idle flag, no qualified artifact in either workflow |
| 9 | Both actual CI modes PASS | **BLOCKED (X43/X42)** | `gh` token invalid; no dispatch or PR observation possible |
| 10 | stable/MSRV/RustFS and ≥85% coverage PASS on this head | **PARTIAL** | local stable+MSRV fmt/clippy/tests/doc/bench PASS and coverage 92.31% lines (`fail-under-lines 85` exit 0); `rustfs` real-service suite and exact-head CI still pending (X40) |
| 11 | Explicit host + operator idle attestation | **BLOCKED (X25)** | none exists; see `b-trials.md` |
| 12 | 3/3 per-engine qualified trials | **BLOCKED** | not run, by design |
| 13 | Original validator PASS | **BLOCKED** | validator not invoked; no run to validate |
| 14 | Aggregate reproducible | **BLOCKED** | aggregator not invoked; no report exists |
| 15 | No unsupported metrics or scored comparisons | **PASS** | no metrics published at all; `qualification.md`/`acceptance.md` untouched |
| 16 | Source reviewer ACCEPTED | **PENDING** | no reviewer |
| 17 | Maintainer merge approved | **PENDING** | no merge attempted |

## Reviewer focus (source review)

1. `ci.yml` — confirm the diff is deletion-only and the surviving jobs match
   `main` byte-for-byte above the boundary.
2. `comparative-adapters.yml` — confirm the `paths` list is exactly the two
   authorized entries, the two `if:` guards match the matrix, the checksum step
   precedes Gradle, and permissions stay `contents: read`.
3. `smoke.py` — confirm `parse_sizes` cannot widen beyond `SIZES`, the default is
   still `[10000]`, and per-size summaries keep one line per selected size.
4. `test_pr15d.py` — confirm no existing assertion was weakened; the new guards
   are additions only.

## Honest summary

The CI restructuring and the bounded 10K/100K correctness interface are
implemented and covered by deterministic tests. **Nothing about performance is
qualified**, no measurement was attempted, and the PR cannot be accepted until
the human-gated items (9, 10, 11) are resolved.
