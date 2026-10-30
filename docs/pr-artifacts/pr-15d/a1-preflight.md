# PR 15D A1 dependency/toolchain preflight (S0)

**Status:** S0 complete. Tantivy pin unblocked; Lucene local execution remains
`BLOCKED-ENVIRONMENT` (no JDK 21). No performance qualification was run.

## 1. Source state

| Item | Value |
|---|---|
| `main` / source lock | `28dc6c2cf95ee24d2b48a580a7cb2a7a8f7dcc6e` (unchanged) |
| Branch | `dev/pr15d-comparative-qualification` |
| Branch HEAD at S0 | `d0c9a3a4f655d874b2825a502f98eb2d553928b1` (the A1-approved predecessor) |
| Worktree | clean at S0; A1 changes begin from that commit |
| Prior PR15D scope | confirmed: spec/oracle/protocol/harness/Quervant adapter/Lucene source only |
| `crates/`, root `Cargo.toml`/`Cargo.lock` | unchanged |
| `pr15d_v1` spec/oracle/protocol | unchanged |

Rule: **X01/X03/X05 AUTO** — clean worktree, exact approved branch HEAD.

## 2. Toolchain inventory

| Tool | Result |
|---|---|
| `cargo` | `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| `rustc` | `rustc 1.98.1 (48a229cea 2026-09-01)` |
| `cargo +1.85.0` | available |
| `python3` | `Python 3.12.3` |
| `java` | **missing** |
| `javac` | **missing** |
| `gradle` | missing (not needed: verified wrapper is used) |
| Any JDK on host | none found (`/usr/lib/jvm`, `/opt`, `~/.sdkman`, `find`, Windows Java paths) |

Rule: **X21 absent / X22 DEFER-ENV locally** — the Lucene adapter is not built
or executed on this host. The isolated CI job is the execution path.

## 3. Tantivy `=0.22.1` resolution (X07)

Probe project: ignored `target/pr15d/a1-probe/` with a standalone
`[workspace]`, `edition = "2021"`, `rust-version = "1.85"`,
`resolver = "3"`.

```text
$ cargo generate-lockfile
      Adding tantivy v0.22.1 (available: v0.29.0)
$ cargo check --locked
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 17.91s
```

Registry provenance and lock pin:

```text
name = "tantivy"
version = "0.22.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "96599ea6fccd844fc833fed21d2eecac2e6a7c1afd9e044057391d78b1feb141"
```

### MSRV correction

A first resolution with the default (non-MSRV-aware) resolver selected
`time 0.3.55` (requires Rust 1.88), `time-core 0.1.9` (1.88) and
`uuid 1.29.0` (1.89), and `cargo +1.85.0 check` failed. Per the A1 plan the
MSRV was **not** raised. Declaring `rust-version = "1.85"` with
`resolver = "3"` made Cargo select MSRV-compatible transitive versions:

```text
time 0.3.45, time-core 0.1.7, uuid 1.26.1
$ cargo +1.85.0 check --locked
    Finished `dev` profile … in 18.54s
```

Both stable and MSRV checks pass with the committed lockfile. No range,
`0.22.0`, `0.23+` or alternate engine was used.

Rule: **X07 AUTO**; **X13 not triggered** (no new direct package beyond the
benchmark-only JSON transport already used by the Quervant adapter).

## 4. Official Gradle 8.14.3 verification (X14/X16/X17)

Checksum endpoints fetched as strict lowercase 64-hex text:

| Artifact | Official endpoint | Value |
|---|---|---|
| wrapper JAR | `https://services.gradle.org/distributions/gradle-8.14.3-wrapper.jar.sha256` | `7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172` |
| `-bin.zip` | `https://services.gradle.org/distributions/gradle-8.14.3-bin.zip.sha256` | `bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531` |

Both values were independently corroborated on
`https://gradle.org/release-checksums/` (8.14.3 section lists the same wrapper
JAR and `-bin` ZIP checksums). The existing `distributionSha256Sum` equals the
official `-bin` checksum: **X17 AUTO**, no conflict (X18 not triggered).

Downloaded and hashed **before** any execution:

```text
gradle-8.14.3-bin.zip  sha256 = bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531  MATCH
```

ZIP safety: 323 entries, all under `gradle-8.14.3/`, zero `..`/absolute entries,
zero symlinks. Not executed locally.

### Wrapper JAR endpoint deviation (recorded for reviewer)

The plan-listed binary URL
`https://services.gradle.org/distributions/gradle-8.14.3-wrapper.jar` returned
**HTTP 404** (310-byte error page), while its `.sha256` endpoint is reachable.
The JAR was therefore fetched from the official Gradle source repository at the
8.14.3 release tag:

```text
https://raw.githubusercontent.com/gradle/gradle/v8.14.3/gradle/wrapper/gradle-wrapper.jar
sha256 = 7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172
```

That digest equals both official published checksums above. Standard launcher
scripts were fetched from the same official tag:

```text
gradlew      fb49f8cb2e5b1d83fba3dcc2c0dd0934c5655cbaf8bd1510ada7cc02692095ca
gradlew.bat  49792578a7942e08b708df3d3902ddbfc49d2203775c0161ef0c24b23fe4aeae
```

They are unmodified standard Gradle wrapper launchers (`-classpath
"$CLASSPATH" -jar "$APP_HOME/gradle/wrapper/gradle-wrapper.jar"`, `exec
"$JAVACMD" "$@"`). The JAR contains `org/gradle/wrapper/GradleWrapperMain.class`.
Provenance is recorded in `benchmarks/pr15d/adapters/lucene/A1-GRADLE-PROVENANCE.json`
and machine-checkable hashes in `A1-CHECKSUMS.sha256`.

> **Reviewer note:** local `gradle wrapper --gradle-version 8.14.3
> --distribution-type bin` generation was impossible without a JVM (X22).
> The committed assets are official 8.14.3 artifacts whose JAR digest matches
> the official publication. No third-party mirror, unverified binary or manual
> launcher edit was used. If the maintainer requires byte-for-byte generated
> wrapper output instead, CI can regenerate and compare before acceptance.

Rule: **X19 AUTO** (official standard assets, checksum-verified); X20 not
triggered.

## 5. Lucene 9.12.3 API static verification (no JDK)

Official Lucene sources (Maven Central, HTTP 200) were inspected to confirm the
adapter's API names before relying on CI:

| Symbol used | Verified in 9.12.3 |
|---|---|
| `FSDirectory.open(Path)` | yes |
| `DirectoryReader.open(Directory)` | yes |
| `IndexWriterConfig(Analyzer)` / `OpenMode.CREATE` | yes |
| `IndexWriter.addDocument`, `commit`, `close` | yes |
| `StringField(String,String,Field.Store)` | yes |
| `SortedDocValuesField(String,BytesRef)` | yes (via `BytesRef` form) |
| `StoredField(String,String)` | yes |
| `IndexSearcher.count(Query)` | yes |
| `IndexSearcher.search(Query,int,Sort)` → `TopFieldDocs` | yes |
| `IndexSearcher.storedFields()` → `StoredFields.document(int)` | yes |
| `SortField.Type.STRING` | yes |
| `KeywordAnalyzer` | yes (`lucene-analysis-common`) |

No `TextField`, no lower-bounded total and no internal doc-ID ordering is used.
Compilation itself is **not** claimed; it is delegated to the isolated CI job.

Rule: **X24 pending CI**, **X25 not needed statically**.

## 6. Frozen corpus identity

Unchanged and re-verified:

| Artifact | SHA-256 |
|---|---|
| `pr15d_v1_N10000.tsv` | `5cdc9341d20bdc525af7e11d3b64bcabf66af9a6eaf27c7dfaddc87280be9a8b` |
| `pr15d_v1_N100000.tsv` | `6ea867fe10679d12fa569822b27e58a8898d866938cf524870c84b0d80d5da4a` |
| `pr15d_v1_manifest.json` | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |

Rules: **X29 AUTO**, X30 not triggered.

## 7. Allowlisted changes

- `benchmarks/pr15d/adapters/tantivy/{Cargo.toml,Cargo.lock,src/main.rs}`
- `benchmarks/pr15d/adapters/lucene/{gradlew,gradlew.bat,gradle/wrapper/gradle-wrapper.jar,A1-CHECKSUMS.sha256,A1-GRADLE-PROVENANCE.json}`
- `benchmarks/pr15d/harness/smoke.py`; path-wiring updates to `run.py` and
  `test_pr15d.py`
- `benchmarks/pr15d/README.md`
- `.github/workflows/ci.yml` — **one appended isolated `pr15d-adapters` job**
- `docs/pr-artifacts/pr-15d/a1-*.md` and the A1 status line in `qualification.md`

No production source, root Cargo file, frozen workload/report, spec or protocol
schema was changed.
