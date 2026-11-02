# PR 15E Phase 3 — targeted performance qualification

**Status: `PERF_BLOCKED_OPERATOR` — no Phase 3 timing has been executed.**

The B1 campaign's operator attestation does not cover this phase; the plan requires a
**fresh** operator idle confirmation for the Phase 3 run, and the coding agent must not
infer or synthesize one. Implementation and the full mandatory QA matrix are complete
(`phase3-execution.md`), so the measurement can start immediately once the operator
confirms idleness.

## 1. Pinned design (pre-registered)

| Item | Value |
|---|---|
| Arm A | accepted B1 source `5553c3bba268b9b268b51117e54eb256772ec19c` |
| Arm B | Phase 3 implementation head (strict descendant of arm A; recorded at run time) |
| Stage | `p3` (7 fixed warm lanes) |
| Trials | 3 independent trials per source, 5 untimed warmups + 20 measured samples per lane |
| Engine | frozen PR15D Quervant adapter built from each `--source-tree` |
| Oracle | frozen PR15D expected `total_hits`/`doc_ids`, checked untimed per lane and on every sample |
| Contention | `clear` required before **and** after every trial (else blocked, never downgraded) |
| Comparison | ratio = phase3 median / B1 median; `B_FASTER` iff all 3 paired trial ratios `< 1`, `A_FASTER` iff all `> 1`, otherwise `INCONCLUSIVE`; no speedup threshold |
| Predecessor guard | arm A must equal `5553c3b`; arm B must be a descendant; reversed/unrelated arms refused |

### Lanes

| Lane | Purpose |
|---|---|
| `n100000/rare/k100` | **primary**: one selected stored record |
| `n100000/rare/k10` | top-K control for a single selected record |
| `n10000/rare/k100` | 10K scaling control |
| `n100000/medium/k100` | 12,500 total hits, only top-K records decoded |
| `n100000/common/k100` | high-match selected-set control |
| `n100000/absent/k100` | no-projection regression sentinel |
| `n10000/common/k100` | smaller high-match control |

Reference points (B1 qualified medians, *not* Phase 3 results): 100K/K100
`rare=79,399,600 ns`, `medium=93,690,204 ns`, `common=122,106,632 ns`,
`absent=1,657,967 ns`; 10K `rare=7,242,586 ns`.

## 2. Untimed preparation already verified

* Deployment/selection path exercised end-to-end by the production integration tests
  (`pr14_projection::phase3_i01_i02/i03/i04/i05_i07`) against real `IndexWriter`,
  commits, generations, PIT, sort and cursor.
* Real RustFS, local `FsDirectory` and PR15E real-adapter integration all pass on the
  Phase 3 head (`phase3-execution.md` §4).
* The runner's `p3` stage passes its unit tests: fixed lane matrix, pinned arms,
  descendant enforcement, B1 report-shape compatibility.

## 3. Exact commands to complete qualification

Two clean, immutable worktrees are required (own Cargo target dirs); `<checkout>` is this
repository and `--out` is the fresh per-stage root. The agent will run these only after
the operator confirms idleness:

```sh
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /ABSOLUTE/PATH/B1_ACCEPTED_5553c3b \
  --stage p3 --out "$PWD/target/pr15e-b1/p3" --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /ABSOLUTE/PATH/PHASE3_HEAD \
  --stage p3 --out "$PWD/target/pr15e-b1/p3" --idle-confirmed
```

The second invocation publishes `target/pr15e-b1/p3/comparison.json` and
`comparison.md`. Raw samples, build logs, index digests and the operator attestation stay
private under `target/pr15e-b1/p3/`; only the sanitized
`benchmarks/reports/pr15e-b1/phase3-targeted-comparison.json` and this file are updated.

## 4. Reporting rules already fixed

* Report the two source SHAs, the tooling SHA, binary digests, corpus manifest SHA, host
  fingerprint, per-lane median/p95/p99, the three paired trial ratios, dispersion and the
  sign-consistency verdict.
* Compare only against the fixed accepted B1 predecessor (primary). The original
  `main`/PR 15D numbers may be quoted descriptively as a *different-session historical
  reference*, never as a newly qualified paired ratio.
* If the primary `n100000/rare/k100` lane is `A_FASTER` or `INCONCLUSIVE`, report
  `PHASE3_PERF_REVIEW_REQUIRED`, stop before Phase 4 and let the maintainer decide.
* No CPU/allocation profiling is performed; no new `perf`/Heaptrack campaign is launched.

## 5. Limitations that must travel with any Phase 3 result

* Synthetic exact-term warm `FsDirectory` workload; it says nothing about BM25 ranking
  quality, projections at remote latency, or distributed search.
* In-process adapter samples include JSON transport but exclude build and index creation.
* Wall-clock `engine_ns` only; modeled decode budgets are unchanged by design, so the
  effect is allocation/CPU work, not admissibility.
* Single host, single session; trial-paired, not cross-host.
* The `absent` lane has no stored projection work and is a regression sentinel only.
