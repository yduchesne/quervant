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
