# PR 15D A1 acceptance

**Status: PENDING REVIEW / BLOCKED-ENVIRONMENT.** The A1 dependency correction
is implemented and locally verified as far as the host permits. Lucene cannot be
compiled locally (no JDK 21) and the new CI job has not run. PR 15D is not done
and no performance qualification exists.

## S7 checklist

- [x] Exact `tantivy = "=0.22.1"`, standalone locked dependency graph,
      persistent on-disk `MmapDirectory` adapter.
- [ ] JDK 21 / Lucene 9.12.3 / Gradle 8.14.3 build proven — **BLOCKED locally**
      (no JDK). Wrapper bytes are checksum-verified against official Gradle
      8.14.3 publications; CI job provisions Temurin 21. Local gate not claimed.
- [ ] 10K and 100K, **three-engine** oracle-exact counts/IDs/order — Quervant
      and Tantivy pass at 16/10K/100K; Lucene pending CI. **Partial.**
- [x] Adapter protocol and negative tests pass; no original gate weakened
      (31 Python tests, 0 failures, 0 skips with both binaries present).
- [ ] `pr15d-adapters` CI job passes on the exact reviewed SHA, and existing
      `rust`/`msrv`/`rustfs` pass. **Not executed** (no push/PR credentials).
- [x] Root production files and frozen workloads/reports unchanged; unqualified
      performance state remains honest.
- [ ] Explicit reviewer acceptance of A1 and separate future qualification of
      real 3×3 performance trials. **Not given.**

**Because two boxes cannot be truthfully checked, this is BLOCKED/PENDING
REVIEW; do not merge or mark PR 15D complete.**

## Local evidence

| Gate | Evidence |
|---|---|
| Source | `main` `28dc6c2…`; branch `dev/pr15d-comparative-qualification` |
| Tantivy pin | `=0.22.1`, `Cargo.lock` checksum `96599ea6…`, stable + MSRV check PASS |
| Gradle wrapper | JAR `7d3a4ac4…`; `-bin.zip` `bd711022…`; matches official `.sha256` and `gradle.org/release-checksums` |
| Quervant adapter | builds; 16/10K/100K indexed and reopened; 8/8 predicates exact |
| Tantivy adapter | builds; 16/10K/100K indexed and reopened; 8/8 predicates exact |
| Lucene adapter | source/static API verified against 9.12.3 sources; build **BLOCKED** |
| Three-adapter smoke | **BLOCKED** (no JDK); fail-closed negative test PASS |
| Harness tests | 31 tests PASS |
| Workspace gates | fmt/clippy (stable + MSRV), tests (2173 passed each), coverage 91.81% lines, doc, bench no-run PASS |
| Frozen files | `git diff --quiet …` over `crates/`, root Cargo, 15B/15C reports, datasets/workloads = 0 |

## Reviewer decisions requested

1. **Quervant `IndexLimits` correction.** The adapter now raises only the
   bounded pending-document/replay limits so the frozen 100K corpus can be
   indexed. It is a public-API resource configuration, not a semantic change,
   but it is outside the literal A1 adapter-file list. Approve or request revert
   (which would make the 100K lane impossible).
2. **Wrapper JAR provenance.** The plan-listed
   `services.gradle.org/.../gradle-8.14.3-wrapper.jar` binary URL returned 404.
   The committed JAR came from the official `gradle/gradle` `v8.14.3` tag and
   its SHA-256 equals both official published checksums. Confirm this is
   acceptable, or require CI regeneration/byte comparison before acceptance.
3. **CI execution.** Push the branch and let `pr15d-adapters`, `rust`, `msrv`
   and `rustfs` run on the exact head. No local Java/CI pass is claimed.
4. **Future performance series.** After A1 acceptance, a human operator must
   attest idleness and run the original PR15D 3×3 qualification; A1 explicitly
   does not authorize or produce those results.

## Note on an unedited stale paragraph

`benchmarks/README.md` still contains the historical PR 15D paragraph that says
the Tantivy `=0.22.0` pin is yanked (X15). A1 §5 does not include that file in
its edit allowlist, so it was intentionally left unchanged. The authoritative
A1 state is `benchmarks/pr15d/README.md` and the `a1-*.md` artifacts.

## Commands for the human operator

```sh
git push -u origin dev/pr15d-comparative-qualification
gh pr create \
  --title "bench(pr15d): A1 pin Tantivy 0.22.1 and qualify verified Lucene toolchain" \
  --body "See docs/pr-artifacts/pr-15d/a1-{preflight,gates,decisions,acceptance}.md. Local Lucene/CI gates are BLOCKED-ENVIRONMENT; no performance claim."
```

Do not run `run.py --trials 3 --idle-confirmed` as part of A1. That belongs to
the separately authorized performance qualification.
