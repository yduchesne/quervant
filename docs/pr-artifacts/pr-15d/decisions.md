# PR 15D decisions

This record maps every decision-matrix rule exercised by the implementation to
the evidence and the resulting state. It is intentionally conservative: no rule
was reinterpreted to widen scope.

## Scope decisions (binding)

1. **Single neutral corpus.** `corpus/generate.py` and `corpus/oracle.py` are
   standard-library-only and produce/verify the same bytes for every engine.
   No adapter implements its own generator.
2. **Mandatory lane is exact, unanalyzed `Keyword` membership only.** There is
   no stemming, stop-word removal, normalization, scoring, boost or engine query
   rewrite in the mandatory lane. Results are ordered by `doc_id` ascending.
   Score comparison is `NOT_APPLICABLE`.
3. **Scored BM25 lane is `SEMANTICALLY_NONCOMPARABLE`.** No public, verified
   identical `k1=1.2`, `b=0.75`, document-statistics, length-normalization and
   tie contract was established across all three engines. It publishes zero
   scored ratios and never mixes with exact-term results (X17/T17).
4. **Storage.** Quervant uses `FsDirectory`, never `MemoryDirectory` or RustFS.
   Tantivy and Lucene are specified to use on-disk directories.
5. **Isolation.** The Quervant adapter is a standalone, independently locked
   Cargo project with `[workspace]`, depending on `quervant-core` by path. The
   production workspace `Cargo.toml`/`Cargo.lock` were not modified.
6. **No production code change.** Nothing under `crates/` was edited. The only
   existing-file edit is an appended PR 15D usage section in
   `benchmarks/README.md`.
7. **No CI change.** X30 applies: CI has no JDK/Gradle and the frozen Tantivy
   pin is unresolvable, so adding a benchmark gate would either install
   unauthorized toolchains or fail deterministically.
8. **No performance threshold.** A slower Quervant is published honestly. The
   aggregate reports `performance_threshold_failure: false` unconditionally.

## Decision-rule log

| Rule | Condition observed | Action taken |
|---|---|---|
| X01 | `main` equals the source lock; no relevant drift | AUTO — recorded SHA and continued |
| X03 | Worktree clean at S0 | AUTO — created `dev/pr15d-comparative-qualification` from `main` |
| X06 | PR #78 merged | PASS — dependent work authorized |
| X07 | Prior 15B/15C/PR07/PR14 artifacts untouched | AUTO |
| X09 | Generator repeatable with matching digests | AUTO — T01 passes |
| X10 | n/a | — |
| X11 | Public exact-term, columnar sort and exact `total_hits` APIs exist | AUTO — Quervant adapter implemented and smoke-verified |
| X12 | n/a | — |
| X13 | Not all pinned toolchains present | BLOCKED — see X14/X15 |
| X14 | No JDK 21, `javac` or Gradle; no permissible install | DEFER-ENVIRONMENT — preserved Lucene source/tests; no Lucene execution |
| X15 | `tantivy = "=0.22.0"` is yanked; fresh isolated resolution fails | **HARD STOP** — no Tantivy adapter authored; version-pin amendment requested |
| X16 | No verified official `gradlew`/wrapper JAR available | HARD STOP for Lucene execution; only the official distribution SHA is recorded |
| X17 | Not needed — `doc_id` itself is the sortable fast field | No numeric ordinal field was added |
| X18 | Only one exact-term adapter is runnable here | Not reached; no measurement phase |
| X19 | No cross-engine mismatch measured | Preserved oracle mismatch tests (T06) |
| X20 | Scored semantic compatibility not proven | DEFER-SEMANTICS — `SEMANTICALLY_NONCOMPARABLE` |
| X21 | n/a | — |
| X22 | Two engines unavailable (Tantivy hard stop, Lucene environment) | DEFER-ENVIRONMENT — no qualified three-engine comparison |
| X23 | Host filesystem is native ext4 | AUTO (recorded by `run.py`) |
| X24 | The agent cannot self-attest operator idleness | DEFER-ATTESTATION — `run.py` records `IDLE_ATTESTATION_MISSING` unless the operator passes `--idle-confirmed` |
| X25 | n/a — no trial was run | — |
| X26 | n/a — no trial was run | — |
| X27 | Clean tracked tree and recorded SHA | AUTO |
| X28 | Build/reopen verification implemented and checked | AUTO (Quervant smoke: 16/16, 10000/10000) |
| X29 | Oracle gate implemented; no real trial ran | AUTO for static tests |
| X30 | CI lacks required toolchains | DEFER-CI — no CI edit |
| X31 | Only one trial-count gate exists; no trials ran | Not reached |
| X32 | Fewer than three trials (zero) | DEFER-QUALIFICATION — diagnostic/static only |
| X33 | 20-sample contract enforced | AUTO (T11) |
| X34 | RSS/CPU/allocation not measured | `NOT_MEASURED` / `null`, never zero |
| X35 | Only process/reader cold is measured | AUTO — label `process_cold` |
| X36 | No performance claim exists | AUTO — negative results would be preserved |
| X37 | n/a — no trial series | — |
| X38 | Profilers not required for the mandatory lane | UNAVAILABLE / not used |
| X39 | No unauthorized production dependency or edit | AUTO — benchmark-only `serde_json = "=1.0.145"` is isolated in the adapter lock |
| X40 | Analyzer map enforced identical (`keyword-exact`) across engines | AUTO (T05) |
| X41 | No qualified series exists to invalidate | — |
| X42 | No push/PR was requested or claimed | DEFER-PUSH |
| X43 | n/a | — |
| X44 | n/a | — |
| X45 | No unlisted obstacle required improvisation | — |

## Explicit non-decisions

- No Tantivy version was substituted.
- No Lucene/JDK/Gradle package was installed.
- No corpus, workload, analyzer, K/N value or acceptance threshold was changed.
- No `drop_caches`, `sudo`, reboot or OS-cold claim was attempted.
- No raw qualified report was written or overwritten.

# PR 15D-B decision log

Rule IDs here are the **PR15D-B** matrix from the 15D-B execution plan, which is
a different numbering from the A1 log above. Every entry records the condition,
the evidence and the resulting action.

| Rule | Condition observed | Evidence | Action taken |
|---|---|---|---|
| X01 | PR #79 merged and `main` equals the source lock | `git rev-parse HEAD/main/origin/main` all `8caca76…`; commit subject is the PR #79 merge | AUTO — S0 begun |
| X02 | No drift affecting benchmark/CI contracts | `git diff` against lock empty at preflight | Not triggered |
| X03 | No unrelated main drift | `git status --porcelain` empty | Not triggered |
| X04 | Worktree clean | `git status --porcelain` empty | AUTO — proceeded |
| X05 | `dev/pr15d-b-comparison-qualification` unused | `git rev-parse --verify` absent locally and on `origin` | AUTO — branch created from `8caca76…` |
| X06/X07 | n/a | branch did not previously exist | Not triggered |
| X08 | No frozen file needed modification | spec/protocol/oracle/generate/run/validate/aggregate untouched | AUTO — no amendment |
| X09 | `pr15d-adapters` isolated as the last job in `ci.yml` | job inventory `rust, msrv, rustfs, pr15d-adapters` | AUTO — removed only that job and its A1 comment |
| X10 | `rust`/`msrv`/`rustfs` unchanged | deletion-only diff; tests assert job set and gate commands | AUTO — preserved |
| X11 | `pr15d-adapters` is not a required check | ruleset `24886640` requires only `context: rust` | Not triggered — relocation permitted |
| X12 | Branch rules readable | classic API 401, but public ruleset API readable | AUTO — audited without assuming |
| X13 | Workflow YAML parses | `yaml.safe_load` on both files; job/trigger/guard assertions pass | AUTO |
| X14/X15 | Trigger behaviour statically asserts path filters only | `ComparativeWorkflowContractTests` | AUTO for static contract; runtime unobserved |
| X16/X17 | `--sizes` default and full pair tested | `SmokeSizeSelectionTests` | AUTO |
| X18 | Wrapper SHA pins unchanged | `A1-CHECKSUMS.sha256` + properties greps copied verbatim into both jobs | AUTO |
| X19 | No local JDK/Gradle campaign attempted | not probed for measurement; Lucene build left to CI | DEFER — no environment claim |
| X20 | Adapter protocol already supports arbitrary corpus paths | `smoke.py` build/query ops take `corpus_path`; no protocol change needed | AUTO — reused exact CLI |
| X21 | Full 100K gate achievable with one bounded `--sizes` flag | `N = 10000` used at 4 sites; parameterized with trailing default | **Not triggered** — mechanical, no redesign |
| X22 | No 100K run attempted | measurement not authorized | Not reached |
| X23 | No timed path in any workflow | T06 test: no `run.py`, no idle flag, no qualified artifact | AUTO — none added |
| X24 | No host campaign run | no attestation | Not reached |
| X25 | **No human idle attestation exists** | this is an agent session; no human attested a host/window | **DEFER** — measurement phase not started |
| X26 | n/a | no attested window | Not triggered |
| X27 | No filesystem claim made | no measurement host selected | Not reached |
| X28/X29 | No toolchain substitution; no source change during a run | no run | Not reached |
| X30/X31/X32/X33 | No campaign exists | `target/pr15d/runs` has no PR15D-B run | Not reached — no validator/aggregator invoked |
| X34/X35/X36 | No results of any kind, slow or inconclusive | no run | Not applicable |
| X37 | No new metric, statistic or heuristic introduced | harness statistics untouched | AUTO — none proposed |
| X38 | Raw artifacts not committed | only docs, two workflows, `smoke.py`, `test_pr15d.py`, README | AUTO — bounded |
| X39 | No production code, segment format or root manifest touched | diff limited to the authorized allowlist | AUTO — in scope |
| X40 | Exact-head `rust`/`msrv` still running at preflight time (run `41124428333`) | Actions API job list | **DEFER** — no accept/merge claim |
| X41 | No exact-head CI failure to classify | no push performed | Not reached |
| X42 | Manual dispatch modes unobserved | requires a dispatched run | **DEFER** — full correctness pending |
| X43 | `gh` token invalid (`HTTP 401`) | `gh auth status`, `gh api` | **DEFER** — local commit only; no fabricated CI result |
| X44 | No memory/disk headroom decision needed | no campaign host | Not reached |
| X45 | Corpus digests not re-measured for a campaign | generator/oracle untouched; prior A1 digests unchanged | Not reached |
| X46 | Semantic oracle untouched | `oracle.py` byte-identical | AUTO |
| X47 | No extra A2 PR proposed | refactor kept inside 15D-B | AUTO |
| X48 | Reviewer acceptance | not yet reviewed | PENDING REVIEW |
| X99 | No unlisted condition obstructed authorized work | scope limited to S1/S2 | Proceeded |

## Explicit PR15D-B non-actions

- No `--idle-confirmed` was passed by the agent, and no idleness was asserted.
- No `run.py`, `validate.py` or `aggregate.py` invocation occurred.
- No `benchmarks/reports/pr15d/pr15d-qualified.json` was created.
- `qualification.md` and `acceptance.md` were **not** rewritten; there is no
  qualified result to report, and the aggregator remains the only authorized
  producer of `qualification.md`.
- No branch protection, ruleset, required check or workflow permission was
  changed.
