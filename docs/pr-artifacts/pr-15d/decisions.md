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

## PR 15D-B campaign addendum (S3–S5)

The human operator supplied the attestation quoted in `b-trials.md`, so the
attestation-gated rules below resolved. The campaign ran; the frozen validator
rejected it.

| Rule | Condition observed | Evidence | Action taken |
|---|---|---|---|
| X24 | Host verified idle, not shared | `check-pr07-contention.py` `state: clear`, 0.002083 busy, 0 competing; 54/54 in-run records `clear` | AUTO — proceeded |
| X25 | **Operator idle attestation present** for this host and window | verbatim attestation quoted in `b-trials.md` | AUTO — measurement phase permitted |
| X26 | Attested window only | `--idle-confirmed` passed once, for run `20261030T220025Z-c9e982f…` | AUTO — no other window used |
| X23/X27 | Native ext4, not drvfs; recorded | `findmnt -T` → `/dev/sdd ext4`; `native_filesystem: true` | AUTO |
| X28 | Toolchains match the frozen pins; nothing substituted | rustc 1.98.1, JDK 21.0.12.1, Gradle 8.14.3, Tantivy `=0.22.1`, Lucene 9.12.3, wrapper checksums OK | AUTO |
| X29 | Source unchanged mid-campaign | tree clean at `c9e982f…` before and after | AUTO |
| X31 | 3 trials × 3 engines, all lanes, all oracles | `run.json` complete/qualified; 9/9 trial manifests qualified; 54/54 contention records clear | AUTO — reached validation |
| **X32** | **`validate.py` exited 2 — `status: INVALID`** | two `index_bytes_inconsistent` errors, Tantivy only | **STOP** — `aggregate.py` not invoked, no qualified claim, no `pr15d-qualified.json` |
| X30 | Evidence retained, not repaired | raw run dir preserved (635 MB, ignored); bounded digests recorded | STOP — classified `BLOCKED` |
| **X37** | Fixing the invariant is a methodology change | `validate.py` requires identical `index_bytes` across trials; Tantivy layout is scheduling-dependent (7.9 % spread at 10K) | **STOP** — amendment options listed in `b-trials.md`, none applied |
| X33 | No aggregator rejection to diagnose | aggregator never ran | Not reached |
| X34/X35/X36 | No result published, therefore no slow/inconclusive/metric claims | nothing published | Not applicable |
| X41/X43 | CI still unobserved; `gh` token still invalid | not re-attempted | DEFER unchanged |
| X48 | Reviewer acceptance | not yet reviewed | PENDING REVIEW |
| X99 | No unlisted condition required improvisation | scope limited to running the frozen runner and reporting | — |

Explicit non-action: the campaign was **not** re-run to obtain a coincidentally
matching Tantivy index size. Restarting for that reason would select evidence
rather than measure it, and any restart needs a new explicit run id plus a full
three-engine campaign.

## PR 15D-B index-size amendment (S1–S6)

Approved methodology decision: *physical index size is a descriptive performance
measurement, not a cross-trial equality invariant.* Different positive
`index_bytes` values across independently executed trials must not invalidate an
otherwise qualified comparison; engine behaviour must not be changed to force
identical sizes.

| Rule | Condition observed | Evidence | Action taken |
|---|---|---|---|
| Precondition | Measurement source is a known clean commit | `run.json source_sha = c9e982f…`; tree clean at timing time | AUTO — proceeded |
| Precondition | Later commit is documentation only | `git diff --name-only c9e982f c92e767` → 4 markdown files | AUTO |
| Precondition | All nine trial manifests + raw samples present | 9 manifests, 32 lanes × 20 samples + 5 warmups, 2 throughput windows each | AUTO |
| Precondition | Preserved artifact digests recorded before changes | 11 digests re-verified against `b-trials.md`; all match | AUTO |
| Precondition | Only the two Tantivy `index_bytes_inconsistent` errors | `validation-initial.json`: 2 errors, `unqualified: []` | AUTO — apply approved correction |
| Validator correction | Equality invariant is the sole blocker | `_check_build` already rejects missing/null/bool/float/str/NaN/zero/negative per trial | AUTO — removed only the equality check, no tolerance, no other semantic change |
| Aggregator | Existing `trial_values`/`median`/`dispersion_max_over_min` already supplied | `indexing[engine][N].index_bytes` | AUTO — reused; added only `min`/`max` and the variation table |
| Invalid index-size value | Any missing/null/zero/negative/float/string/bool/NaN/Infinity value | `IndexSizeAmendmentTests` (13 tests) | REJECT — `index_bytes_invalid` |
| Other validation failure | None beyond the two size errors | pre- and post-amendment validator output | Not triggered |
| Revalidation | Same raw measurements validate after correction | exit 0, `QUALIFIED`, 0 errors, 9/9 trials retained | AUTO — aggregated without remeasurement |
| Aggregation integrity | Aggregates must match independent recomputation | `verify_aggregate` → `[]`; byte-identical re-derivation; 108 independently recomputed statistics matched | AUTO — no manual statistic edit |
| Adapter/workload change | Not needed and not made | adapters, corpus, spec, protocol, `run.py` byte-identical | Not required |
| Campaign re-run | Not needed and not performed | measurement window unchanged | Not performed |
| CI | Exact-head CI still unobserved (`gh` token invalid) | not re-attempted | DEFER — no final acceptance claim |
| Unlisted condition | None arose | — | — |

Explicit non-actions: no tolerance was introduced, no index-size parity threshold
exists, no engine was modified, no trial was dropped, no outlier discarded, and
no performance statistic was hand written.

## PR 15D-B methodology/evidence/resource fixup (P0–P6)

Rule IDs are the fixup plan's matrix (X01–X99), which is a different numbering
from the A1 and 15D-B campaign logs above.

| Rule | Condition observed | Evidence | Action taken |
|---|---|---|---|
| X01 | Branch + HEAD equal the specified PR SHA; worktree clean | `HEAD 850b119…`, `origin/main 8caca76…`, `git status` empty | AUTO — locked and continued |
| X02/X03 | No main drift affecting the fix; no out-of-baseline change | `git diff --name-status origin/main...HEAD` recorded in `b-methodology-fixup.md` | Not triggered |
| X06 | Old run and all nine raw manifests present, hashes match inventory | P0 inventory table (12 files + 54 contention records) | AUTO — preserved immutably |
| X08 | Timing boundaries exactly matched the described old state | `search()` / `handle_query()` / `query()` inspected at the stated loci | AUTO — applied the exact P1 edits |
| X10/X11 | Tantivy count+top-ID loop and Lucene count+ID loop matched | source inspection | AUTO |
| X12 | Timer boundary includes projection/materialisation, excludes response serialisation | FIX-T01–T05 | AUTO |
| X13 | Source-order negative tests reject an early stop-clock and a late one | FIX-T04, FIX-T05 (mutations on copied text; tracked source re-verified unchanged) | AUTO — no false-positive acceptance |
| X14 | Real adapter build and smoke pass | three release builds + `smoke.py --sizes 10000,100000` exit 0 | AUTO |
| X15 | Tantivy document prep was inside the insert timer | `handle_build` inspection | AUTO — hoisted to `Vec<TantivyDocument>` before `Instant::now()`; no budget/thread change |
| X16 | All three document-prep boundaries now outside the ingestion timer | FIX-T14/T15 | AUTO — added derived `ingest_through_commit_ns` |
| X17 | Fixed-width IDs give identical logical order with different physical sorts | `sort_physical_keys` + FIX-T12 | AUTO — disclosed, equivalence `NOT_CLAIMED` |
| X19 | Overflow possible when forming the derived metric | FIX-T19 | AUTO — checked addition raises, never wraps |
| X20 | Report must not label `process_cold` as OS-cache-cold | limitation bullets unchanged | AUTO |
| X21 | Index size may vary across trials | preserved descriptive median/min/max/dispersion | AUTO — no equality gate |
| X22 | Old canonical aggregate/report archived byte-identically | `cmp` both files, digests recorded | AUTO |
| X23 | Archive comparison matched | `cmp` exit 0 | Not triggered |
| X30 | New Python resource tests pass on synthetic `/proc` fixtures | 29 tests OK | AUTO — real gate still pending attestation |
| X34/X35 | No real probe executed | no attestation | DEFER — resource gate pending, not zero |
| X37/X38 | **No new human attestation for a new window** | this session's only attestation covers 2026-10-30 22:00–22:41Z | **DEFER — `BLOCKED-ATTESTATION`**; no campaign, no `--idle-confirmed` |
| X43/X44 | Aggregate differs from independent recomputation | `verify_aggregate` clean on the diagnostic run only | Not triggered for the new protocol |
| X48 | GitHub credentials unavailable | `gh` token still invalid | DEFER — no CI claim |
| X52 | Independent reviewer acceptance | not yet reviewed | PENDING |
| X58/X99 | No unlisted condition arose | scope held to the allowlist | — |

Explicit non-actions: no measurement was run or re-run, no `--idle-confirmed`
was passed, no new run directory, no new validation or aggregate, no production
code, root manifest, lockfile, workflow, frozen corpus, spec or protocol change,
and no metric, threshold or dispersion rule was altered.

| Snapshot reuse | Quervant rebuilt a `ReaderSnapshot` per query while Tantivy/Lucene reused one reader | `Index::snapshot()` creates a new snapshot; adapter called it in `search()` | AUTO — one `QuerySession` snapshot per process, invalidated on build; no `crates/**` change |
| Snapshot evidence | Behaviour must be proven, not inferred from results | 5 adapter unit tests (counter, ptr identity, independence, lifetime) + 2 harness lifecycle tests | AUTO — deterministic |
