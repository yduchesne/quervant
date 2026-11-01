# PR 15E-B1 — performance qualification

**Status: `B1A_MEASURED` + `B1B_MEASURED` + `FINAL_QA` (targeted matrix qualified).**

Qualified on one host with 3 independent trials per measured commit, `regime=warm`,
5 warmups + 20 measured samples per lane, real `FsDirectory`, frozen PR15D corpus and
oracle, one production adapter. Every trial's contention probe was `clear` before and
after. No timing ran without the operator's explicit `--idle-confirmed` attestation.

Sanitized, committed summary: `benchmarks/reports/pr15e-b1/targeted-comparison.json`.
Raw samples, build logs, index digests, host details and the operator attestation stay
private under `target/pr15e-b1/` (gitignored).

## 1. Identity and parity

| Item | Value |
|---|---|
| Original `main` (arm A) | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` |
| B1a (arm B for `b1a`, arm A for `b1b`) | `601765fbc253cf9db3a2bfb5d594156eecb35f51` |
| B1b / final (arm B) | `79218187390487eea0ced5e193147c15cd5a1e2a` |
| Tooling revision | `ed7bf06df2985ad6d414f77b54bb03bc323a0bfb` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Host fingerprint (all 6 runs) | identical (`4f971362f029…`) |
| Adapter binary digests | baseline `aeae2254fbef…`, B1a `245178dd2ce5…`, B1b `c3a4c33d480c…` |
| Trials per source / samples per lane | 3 / 20 (all lanes, all sources) |
| Contention probes | 36/36 trials `clear` before **and** after |
| Oracle | untimed check per lane + `validate_query_response` on every sample: PASS |

The runner refused comparisons across differing corpora, hosts, lane sets or trial
counts, so all published ratios are same-host, same-corpus, paired by trial index.

## 2. Stage `b1a` — original `main` → B1a (direct live-bitmap iteration)

| Lane | A median (ns) | B median (ns) | ratio B/A | paired trial ratios | verdict |
|---|---:|---:|---:|---|---|
| `n100000/absent/k100` | 2 925 813 | 1 713 838 | 0.586 | 0.579, 0.597, 0.590 | B_FASTER |
| `n100000/rare/k100` | 82 124 424 | 77 138 752 | 0.939 | 0.990, 0.975, 0.936 | B_FASTER |
| `n100000/medium/k100` | 610 196 508 | 594 792 918 | 0.975 | 0.997, 0.989, 0.906 | B_FASTER |
| `n100000/common/k100` | 1 850 512 445 | 1 828 918 376 | 0.988 | 0.998, 0.996, 0.886 | B_FASTER |
| `n10000/absent/k100` | 314 466 | 189 142 | 0.601 | 0.661, 0.599, 0.596 | B_FASTER |
| `n10000/common/k100` | 28 253 795 | 26 799 217 | 0.949 | 0.974, 0.936, 0.830 | B_FASTER |

Consistent improvement in every lane. The largest effect is on the lanes that do the
least membership work per document (`absent`, where the removed per-live-document
allocation dominated); medium/common improve modestly because their time is dominated
by the linear postings membership scan that B1b removes.

## 3. Stage `b1b` — B1a → B1b (sorted-postings binary search)

| Lane | A median (ns) | B median (ns) | ratio B/A | paired trial ratios | verdict |
|---|---:|---:|---:|---|---|
| `n100000/medium/k100` | 600 012 756 | 91 612 642 | 0.153 | 0.161, 0.153, 0.153 | B_FASTER |
| `n100000/common/k100` | 1 829 253 986 | 122 352 957 | 0.067 | 0.066, 0.066, 0.068 | B_FASTER |
| `n100000/absent/k100` | 1 678 826 | 1 668 794 | 0.994 | 0.974, 1.006, 0.980 | INCONCLUSIVE |
| `n100000/rare/k100` | 78 500 167 | 78 145 414 | 0.995 | 1.005, 0.969, 0.979 | INCONCLUSIVE |
| `n10000/common/k100` | 26 692 066 | 11 098 558 | 0.416 | 0.434, 0.414, 0.411 | B_FASTER |

The two lanes with little or no per-document membership work are **INCONCLUSIVE**
(paired ratios change sign) and are reported as such, not as wins. The high-match
lanes improve by roughly 6.5×–15× within the same fixed workload.

## 4. Stage `final` — original `main` → B1 final (compact 9-lane control)

| Lane | A median (ns) | B median (ns) | ratio B/A | paired trial ratios | verdict |
|---|---:|---:|---:|---|---|
| `n10000/absent/k100` | 284 902 | 178 184 | 0.625 | 0.595, 0.622, 0.625 | B_FASTER |
| `n10000/rare/k100` | 7 085 724 | 7 242 586 | 1.022 | 1.003, 1.028, 0.983 | INCONCLUSIVE |
| `n10000/medium/k100` | 12 108 049 | 8 283 229 | 0.684 | 0.677, 0.689, 0.696 | B_FASTER |
| `n10000/common/k100` | 27 218 813 | 11 268 283 | 0.414 | 0.408, 0.409, 0.422 | B_FASTER |
| `n100000/absent/k100` | 2 843 978 | 1 657 967 | 0.583 | 0.581, 0.573, 0.610 | B_FASTER |
| `n100000/rare/k100` | 78 902 997 | 79 399 600 | 1.006 | 0.967, 0.988, 1.010 | INCONCLUSIVE |
| `n100000/medium/k100` | 597 132 473 | 93 690 204 | 0.157 | 0.156, 0.156, 0.160 | B_FASTER |
| `n100000/common/k100` | 1 826 182 354 | 122 106 632 | 0.067 | 0.067, 0.066, 0.067 | B_FASTER |
| `n100000/common/k10` | 1 814 828 128 | 111 954 946 | 0.062 | 0.062, 0.061, 0.062 | B_FASTER |

**7 of 9 lanes B_FASTER, 2 INCONCLUSIVE (the single-hit `rare` lanes), 0 A_FASTER.**
No lane regressed consistently, so no human accept/revert disposition (D13) is needed.
The `k10` control lane behaves like the `k100` lanes, i.e. the effect is not a
`top-k` artifact.

## 5. Interpretation limits

* In-process adapter samples include JSON transport but exclude build and index creation.
* `engine_ns` is wall-clock only; CPU counters and allocations were not measured for B1
  (no new `perf`/Heaptrack campaign). The PR15E-A allocation finding remains the
  *motivation*, not a B1 measurement.
* The `rare` lane has one matching document and is dominated by a full live-document
  scan plus scoring; its paired ratios cross 1.0 by ~1–3%, i.e. noise, and are reported
  as INCONCLUSIVE.
* The workload is a synthetic exact-term `FsDirectory` lane. It says nothing about BM25
  ranking quality, RustFS-backed indexes, projections or distributed search.
* Results are single-host, single-session, in-process. They are internally paired and
  trial-triangulated, but they are not a cross-host generalisation.
* B2/B3/B4 effects are not included; the remaining cost on high-match lanes is the
  per-live-document traversal and full matched-set scoring that B2 targets.

## 6. Reproduction

```sh
python3 benchmarks/pr15e_b1/run_targeted.py --source-tree <baseline-worktree> --stage b1a   --out <checkout>/target/pr15e-b1/b1a   --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py --source-tree <b1a-worktree>      --stage b1a   --out <checkout>/target/pr15e-b1/b1a   --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py --source-tree <b1a-worktree>      --stage b1b   --out <checkout>/target/pr15e-b1/b1b   --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py --source-tree <b1b-worktree>      --stage b1b   --out <checkout>/target/pr15e-b1/b1b   --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py --source-tree <baseline-worktree> --stage final --out <checkout>/target/pr15e-b1/final --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py --source-tree <b1b-worktree>      --stage final --out <checkout>/target/pr15e-b1/final --idle-confirmed
```

Each stage's second invocation publishes `comparison.json` and `comparison.md`.

## 7. Operator attestation record

The operator confirmed the host was idle before this campaign; the runner recorded
`operator_idle_confirmed: true` in each run directory's `idle-confirmation.json`
(private, not committed) and independently re-probed contention before and after every
trial (36/36 `clear`). The agent did not generate or infer the attestation.

## 8. Earlier state (superseded)

The first attempt at `b1a` aborted fail-closed with
`X34_CONTENTION: trial 1 before: contention state 'unknown' (probe_failed)` because the
runner had not created the probe's parent directory. That defect is fixed in
`ed7bf06` (with a regression test); no samples from the aborted run were used.
