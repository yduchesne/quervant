# PR 15D A1 decisions

Rule IDs follow the A1 amendment matrix (S6). First applicable rule wins.

| Rule | Observed condition | Action |
|---|---|---|
| X01 | Worktree clean; branch `dev/pr15d-comparative-qualification` at `d0c9a3a…`; `main` still `28dc6c2…` | AUTO — record and continue |
| X02 | No unrelated edits | not triggered |
| X03 | `main` did not move | not triggered |
| X04 | No protocol/workload/policy drift on `main` | not triggered |
| X05 | Branch HEAD is the exact A1-approved predecessor `d0c9a3a4…` | AUTO — work on branch |
| X06 | Ancestry unambiguous | not triggered |
| X07 | `tantivy = "=0.22.1"` resolves; stable and `cargo +1.85.0 check --locked` pass | AUTO — exact pin + standalone lock |
| X08 | Registry reachable | not triggered |
| X09 | 0.22.1 is not yanked; no incompatibility after MSRV-aware resolution | not triggered |
| X10 | Public `TermQuery` + exhaustive `Count` + `TopDocs::order_by_u64_field` + on-disk `MmapDirectory` available | AUTO — prescribed adapter |
| X11 | API is sufficient | not triggered |
| X12 | No exhaustive manual sort fallback was needed; native ordered collector and exact count are used | not triggered |
| X13 | No new direct dependency beyond benchmark-only `serde_json` already used by the Quervant adapter; root Cargo untouched | not triggered |
| X14 | Official Gradle 8.14.3 checksum endpoints reachable; strict 64-hex values recorded | AUTO — verify exact bytes |
| X15 | **Deviation:** `services.gradle.org/.../gradle-8.14.3-wrapper.jar` binary URL returned HTTP 404, while its `.sha256` endpoint is reachable | Used the official `gradle/gradle` **v8.14.3 tag** JAR; its SHA-256 equals both official published checksums. No third-party mirror. Recorded in `a1-preflight.md` and `A1-GRADLE-PROVENANCE.json` for reviewer confirmation |
| X16 | Wrapper JAR and `-bin` ZIP hashes match official values | not triggered |
| X17 | Existing `distributionSha256Sum` equals the official `-bin` checksum | AUTO — preserved |
| X18 | No conflict | not triggered |
| X19 | Official standard wrapper JAR/launchers, checksum-verified; `gradle wrapper` generation locally impossible without a JVM (X22) | AUTO with recorded provenance |
| X20 | No launcher script was manually written or edited | not triggered |
| X21 | JDK 21 is **absent** locally | not triggered |
| X22 | JDK 21 absent locally, but CI can provision via `actions/setup-java@v4` | DEFER-ENV locally; appended isolated CI job; no local Java pass claimed |
| X23 | No JDK other than 21 was used | not triggered |
| X24 | Lucene 9.12.3 build | **NOT RUN locally** (X22); CI pending |
| X25 | No compile-only API mismatch is known; static source verification found all used APIs | no local correction applied |
| X26 | No analyzer/text semantics change | not triggered |
| X27 | Quervant and Tantivy pass the same oracle at 16/10K/100K; Lucene pending CI | partial — qualification readiness not claimed |
| X28 | No adapter count/order mismatch | not triggered |
| X29 | `pr15d_v1` digests match the frozen contract | AUTO — preserved |
| X30 | No digest difference | not triggered |
| X31 | Smoke succeeds for Quervant and Tantivy (31 Python tests; 0 failures) | AUTO — recorded |
| X32 | Lucene smoke unexecutable: no JDK/distribution | DEFER-ENV — not PASS |
| X33 | Existing harness recognized Tantivy/Lucene paths with wiring only; protocol unchanged | AUTO |
| X34 | No new protocol command or schema field | not triggered |
| X35 | Existing harness had no non-timed smoke | AUTO — added prescribed `harness/smoke.py`; qualified runner untouched |
| X36 | CI patch appends only the isolated `pr15d-adapters` job | AUTO |
| X37 | `rust`, `msrv`, `rustfs` jobs byte-identical | not triggered |
| X38 | CI network/execution unknown | DEFER-ENV — job unexecuted, no synthetic pass |
| X39 | No human idle attestation exists | not triggered |
| X40 | No actual human attestation | WAIT-HUMAN — agent did not pass `--idle-confirmed` |
| X41 | Zero qualified trials | no publication |
| X42 | RSS/CPU/allocation not measured | `NOT_MEASURED` |
| X43 | Ancillary diagnostics labelled; no mixed comparison | n/a |
| X44 | No opportunistic upgrade. The MSRV-aware resolver selected older `time 0.3.45` / `uuid 1.26.1` to keep Rust 1.85; this is lockfile resolution within the frozen `tantivy = "=0.22.1"` pin, not a tool/version upgrade | AUTO, recorded |
| X45 | CI not run | acceptance pending, no merge |
| X46 | Local build/oracle/gates pass; CI and Lucene unverified | **not** “A1 implementation reviewed-pending” yet |
| X47 | Diff is within the A1 allowlist, with one documented configuration correction (Quervant `IndexLimits`), plus A1 evidence docs | AUTO with explicit disclosure |
| X48 | No unexpected production/fixture drift | not triggered |
| X49 | No GitHub push/PR authorization used | DEFER-ENV — clean committed branch + commands |
| X50 | Reviewer has not accepted | PENDING REVIEW |

## Disclosed correction beyond the literal file list

`benchmarks/pr15d/adapters/quervant/src/main.rs` now constructs an explicit,
bounded benchmark `IndexLimits` (1,000,000 pending docs; 512 MiB pending/replay
bytes) through the public `Index::create_with_limits` /
`Index::open_with_limits`. Reason: the production default
`max_pending_docs = 10_000` rejected row 10,001 of the frozen 100,000 corpus,
making T-A1-04/05 impossible. This changes **no** query, analyzer, ordering,
scoring or counting semantics; it is adapter resource configuration. A1 §5 says
“no edits to current Quervant adapter semantics”, which this preserves, but it is
not listed among the A1 adapter paths, so it is explicitly surfaced for reviewer
approval.

## Explicit non-decisions

- No `0.22.0`, range, `0.23+`, vendored yanked crate, or alternate engine. The
  lockfile does contain the transitive crate `tantivy-query-grammar 0.22.0`
  (pulled by `tantivy 0.22.1`); the **engine** crate is exactly
  `tantivy 0.22.1`. MSRV-compatible `time 0.3.45` / `uuid 1.26.1` are lockfile
  resolutions, not tool upgrades.
- No MSRV bump; no production `Cargo.toml`/`Cargo.lock` edit.
- No JDK/Gradle installation, no unverified wrapper binary.
- No spec/protocol/workload change.
- No `run.py --trials 3 --idle-confirmed`.
- No performance result, ratio or parity claim.
