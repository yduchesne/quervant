# PR 14E — baseline inventory and source lock

**Status: `EVIDENCE RECONCILIATION IN PROGRESS — PR 14 NOT ACCEPTED`.**
PR 14E is a documentation/evidence PR. It changes no Rust source, test, API,
format, manifest, cursor, CI workflow, dependency or roadmap status.

| Item | Value |
|---|---|
| Branch | `docs/pr14e-acceptance-reconciliation` |
| Base / branch head at P1 | `dc506f6ee28014e64fbc9070db6925b73063d9ba` (fetched `origin/main`) |
| `origin/main` at P1 | `dc506f6ee28014e64fbc9070db6925b73063d9ba` |
| Local working tree before P1 | clean (`git status --porcelain` empty) |
| PR 14D merge commit | `6d18ebed4c2a8c7d73ca9e5078019d50546cb675` — merge-base ancestor of `origin/main`: **yes** |
| PR 14D reviewed final head | `635c7f4a89c5e2e9478da23c2a533e8dc1f80e09` — ancestor of `origin/main`: **yes** |
| PR 14C merge commit (PR #62) | `2cb91be19652379b435c49a5fa4aea2ed7502de5` |
| PR 14C final head | `a61f0b8ed97be48235f9583c9b4dd6d8755c36bc` |
| PR 14B merge commit (PR #61) | `376023b53b557a30367097f29a41328c798188d4` |
| PR 14C tested baseline | `376023b53b557a30367097f29a41328c798188d4` (historical unit of the 14C crosswalk) |

No base drift occurred during preflight: the fetched `origin/main` equalled the
plan's observed SHA, so decision X01 (main advanced) was not triggered.

## 1. Ancestry and merge verification

```
$ git fetch origin --prune
$ git rev-parse origin/main
dc506f6ee28014e64fbc9070db6925b73063d9ba
$ git merge-base --is-ancestor 6d18ebed4c2a8c7d73ca9e5078019d50546cb675 origin/main  -> yes
$ git merge-base --is-ancestor 635c7f4a89c5e2e9478da23c2a533e8dc1f80e09 origin/main  -> yes
```

GitHub API verification of the PR series (unauthenticated read API, immutable
records; see `test-traceability.md` E14E-01/E14E-04/E14E-16 for URLs):

| PR | Title (truncated) | `merged` | merge commit | PR head SHA |
|---:|---|---|---|---|
| #61 | Dev/pr14b real rustfs qualification | true | `376023b` | `6cb6d47` |
| #62 | Dev/pr14c acceptance closeout | true | `2cb91be` | `a61f0b8` |
| #63 | docs: align README planned feature labels | true | `dc506f6` | `4097a02` |
| #64 | fix(pr14d): govern JSON-sort transient memory before allocation | true | `6d18ebe` | `635c7f4` |
| #65 | docs: require continuous execution in detailed PR plans | true | `80276fd` | `b66f817` |

Decisions X02 (unowned dirty tree) and X03 (PR 14D merge absent) were therefore
not triggered.

## 2. Environment

| Item | Value |
|---|---|
| Host | WSL2, `Linux 6.18.33.2-microsoft-standard-WSL2`, x86-64, 12 vCPU |
| Repository filesystem | ext4 (`/dev/sdd` → `/`), not `/mnt/c` |
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| MSRV toolchain | `cargo 1.85.0 (d73d2caf9 2024-12-31)` (`cargo +1.85.0`) |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Container runtime | `podman 4.9.3` (rootless) |
| Python | 3.12.3 |
| GitHub CLI | `gh` token **invalid** (`gh auth status` → "The token … is invalid") |
| GitHub read API | Reachable unauthenticated (HTTP 200); used for immutable commit/check-run records |
| Local RustFS provider in this run | **not started** — no fresh provider run is claimed by PR 14E |

Decision X15 applies: the invalid `gh` credential does not block CI verification,
because the immutable check-run records are readable through the public API.
Decision X16 is therefore not triggered, and `gh` 401 is no longer carried as a
current CI verdict.

## 3. Sources inspected at this head

| Area | Paths |
|---|---|
| Policy/guide | `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/ROADMAP_V01.md`, `docs/TESTING.md` |
| Historical crosswalk | `docs/pr-artifacts/pr-14c/{acceptance-reconciliation,test-traceability,validation-report,final-acceptance,resource-risk-disposition,benchmark-report,adversarial-review,baseline-inventory}.md` |
| PR 14D evidence | `docs/pr-artifacts/pr-14d/{baseline-inventory,design-and-ownership,test-traceability,validation-report,compatibility-report,resource-characterization,sr14d01-fixup,adversarial-review,final-acceptance}.md` |
| Original PR 14 generations | `docs/pr-artifacts/pr-14/{test-traceability,preimplementation-correctness-gate,corrective-test-traceability,final-design-test-traceability,remaining-test-traceability,*final-acceptance,*preflight}.md` |
| Benchmark contract | `benchmarks/workloads/pr14_p4_v1.md`, `benchmarks/scripts/validate-pr14-p4.py`, `benchmarks/scripts/run-pr14-p4.sh`, `benchmarks/reports/pr14-p4-w08-exemption.json` |
| Production code | `crates/quervant-core/src/search/{typed,unified,memory,batch_meter,projection}.rs`, `crates/quervant-core/src/segment/{json_paths,mod}.rs`, `crates/quervant-core/src/remote/{mod,transfer}.rs`, `crates/quervant-core/src/storage/*` |
| Test code | `crates/quervant-core/tests/pr14*`, `pr14a_public_cursor`, `pr11_json_*`, `pr13_remote`, `pr13_oracle`, `pr13_bench_remote`, `segment_golden` |

No path in §2 of the execution plan was missing or renamed; decision X24 was not
triggered.

## 4. Historical gate counts (unchanged, preserved verbatim)

PR 14C published 127 classified table rows at tested source
`376023b53b557a30367097f29a41328c798188d4`:

| Historical adjudication | Count |
|---|---:|
| PASS | 96 |
| SUPERSEDED WITH EVIDENCE | 11 |
| NOT APPLICABLE (APPROVED) | 2 |
| BLOCKED | 18 |
| FAIL | 0 |
| **Total** | **127** |

Re-extraction at this head reproduced exactly 127 adjudicated rows and the same
per-disposition totals (detail and parsing rule in
[acceptance-crosswalk.md](acceptance-crosswalk.md) §1). Decision X04 (row total
≠ 127) was not triggered.

The 18 historical `BLOCKED` rows are:

| # | Section | Literal ID | Historical obligation (abbreviated) |
|---:|---|---|---|
| 1 | §3 original invariants | `I13` | Zero query-time remote GET |
| 2 | §4.2 JSON | `J14` | Old-segment JSON fallback |
| 3 | §4.2 JSON | `J15` | Legacy segments |
| 4 | §5.3 corrective | `I07` | Exact `HitRef` projection identity |
| 5 | §5.3 corrective | `I12` | Zero-GET instrumentation |
| 6 | §5.3 corrective | `I16` | Final-SHA CI |
| 7 | §5.4 final design | `I8` | Exact physical hit identity |
| 8 | §5.4 final design | `I13` | No query-time remote GET |
| 9 | §6 phases | `14F` | Real-boundary RustFS + faults + benchmarks |
| 10 | §6 phases | `14G` | Final gates, CI, docs |
| 11 | §7.1 P4 V | `V11, V12` | Benchmark oracle + three qualified trials |
| 12 | §7.4 P4 B | `B01` | Correctness oracle before timing |
| 13 | §7.4 P4 B | `B03` | Three independently qualified trials |
| 14 | §7.5 P4 W | `W01–W07, W09` | Measured lanes |
| 15 | §7.6 CI | `Q01–Q06 / Q01–Q09` | Final-SHA CI Q-gates |
| 16 | §4.6 matrices | `X01–X13` | Independent local/Fake/real oracles (per-ID definitions unavailable) |
| 17 | §8 mapping | item 6 | Benchmarks |
| 18 | §8 mapping | item 7 | JSON temporary memory (`R-14A-JSON-MEM`) |

## 5. Preliminary blockers carried into Stage B/C

| Blocker | Preliminary owner | Where resolved or carried |
|---|---|---|
| Zero-GET proof for PR 14 typed/mixed/batch/pinned query execution | separate instrumentation/test approval | dossier D-01, D-05, D-08 |
| Exact physical hit identity assertion (`HitRef` / `(segment_index, doc_id)`) | separate test-only approval; no public API change authorized here | dossier D-04, D-07 |
| Legacy JSON J14/J15 dedicated coverage | PR 14E (if directly evidenced) | dossier D-02, D-03 |
| Original `X01–X13` per-ID definitions | maintainer decision | dossier D-16 |
| Three qualified P4 trials, all workload lanes | PR 14F | dossier D-09…D-14, D-17 |
| PR 14E final-head CI (`rust`, `msrv`, `rustfs`) | a PR must exist; `gh pr create` failed with HTTP 401 | `final-acceptance.md` §8 |
| Independent review + maintainer risk/acceptance signoff | maintainer | `resource-risk-reconciliation.md`, `final-acceptance.md` |

## 6. Status flags (never collapsed)

| Flag | State |
|---|---|
| IMPLEMENTED (PR 14D correction on current main) | YES |
| LOCALLY EXECUTED (PR 14E validation matrix) | YES — see `validation-report.md` |
| REAL-PROVIDER QUALIFIED (fresh PR 14E run) | **NO** — PR 14D's immutable evidence cited, not re-executed |
| BENCHMARK QUALIFIED | **NO** — 0 of 3 fresh trials; owned by PR 14F |
| CI VERIFIED (historical PR 14 line heads) | YES — immutable check-run records |
| CI VERIFIED (PR 14E head) | **NOT VERIFIED** — branch pushed, PR not created (HTTP 401), no run |
| REVIEWED | **NO** |
| HUMAN ACCEPTED | **NO** |
| MERGED | **NO** |
| PR14 DONE | **NO** |
| v0.1 RELEASED | **NO** |
