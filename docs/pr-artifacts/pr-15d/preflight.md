# PR 15D preflight (S0)

**Status:** S0 complete with one HARD STOP and one DEFER-ENVIRONMENT.
**Repository:** `yduchesne/quervant`
**Source lock:** `28dc6c2cf95ee24d2b48a580a7cb2a7a8f7dcc6e`
**Work branch:** `dev/pr15d-comparative-qualification` (created from `main`)
**Preflight date:** 2026-10-30 (host clock)
**Authoritative plan:** `QUERVANT_PR15D_DETAILED_EXECUTION_PLAN.md`

## 1. Source and scope freeze

| Check | Result |
|---|---|
| `origin/main` == source lock | PASS — `28dc6c2cf95ee24d2b48a580a7cb2a7a8f7dcc6e` |
| `git status --porcelain` at S0 | PASS — empty (clean tracked tree) |
| PR #78 merged | PASS — `28dc6c2 Merge pull request #78 … pr15c-b-performance-qualification` |
| PR 15C-B evidence present on `main` | PASS — `benchmarks/reports/pr15c-b/`, PR15B reports unchanged |
| PR #78 predecessor commit | `8087226 docs(pr-15c-b): record the AR2-T08 CI portability fixup evidence` |
| New paths already present | NONE (`git ls-files | grep pr15d` empty) |

`docs/ROADMAP_V01.md` lines 167–186 (PR 15A–15F), `docs/BENCHMARKING.md`,
`docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `AGENTS.md` and `docs/TESTING.md`
were read. No drift in benchmark APIs, roadmap, tests, `Cargo.toml`, workflow or
benchmark infrastructure since the source lock. Classification: **X01 AUTO**
(no relevant drift; record SHA and continue).

Prior benchmark artifacts were **not** modified (X07 AUTO).

## 2. Toolchain probe

| Tool | Result |
|---|---|
| `cargo --version` | `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| `cargo +1.85.0 --version` | `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| `rustc --version` | `rustc 1.98.1 (48a229cea 2026-09-01)` |
| `python3 --version` | `Python 3.12.3` |
| `sha256sum` | `/usr/bin/sha256sum` present |
| `findmnt` | `/usr/bin/findmnt` present |
| `git` | `/usr/bin/git` present |
| `/usr/bin/time` | present |
| `cargo llvm-cov` | `/home/yduchesne/.cargo/bin/cargo-llvm-cov` present |
| `java` | **MISSING** (`java: command not found`) |
| `javac` | **MISSING** (`javac: command not found`) |
| `gradle` | **MISSING** (`gradle: command not found`) |
| Any JDK on host | **NONE** — `/usr/lib/jvm`, `/opt`, `~/.sdkman`, `find / -name javac`, and Windows `Program Files` Java locations are all absent |

### X14 DEFER-ENVIRONMENT — Lucene toolchain

JDK 21 and Gradle 8.14.3 are required by the plan. Neither is installed and no
permissible local installation is authorized. The Lucene adapter source and
Gradle pin are preserved, but **no Lucene build, smoke test or measurement was
run**, and no three-engine qualification may be claimed (X22).

### Maven artifacts are reachable

`https://repo1.maven.org/maven2/org/apache/lucene/lucene-core/9.12.3/…` returns
HTTP 200, as do `lucene-analysis-common` and `lucene-queryparser`. The blocker is
the local JDK/Gradle, not artifact availability.

## 3. X15 HARD STOP — the frozen Tantivy pin is yanked

From an isolated temporary project outside the repository:

```toml
[dependencies]
tantivy = "=0.22.0"
```

```text
$ cargo build
    Updating crates.io index
error: failed to select a version for the requirement `tantivy = "=0.22.0"`
  version 0.22.0 is yanked
location searched: crates.io index
required by package `tantivy-resolve-probe v0.0.0 (/tmp/pr15d-preflight/tantivy-resolve)`
```

Crates.io metadata confirms `0.22.0` is yanked and only `0.22.1` is currently
selectable. The plan is explicit (§0.5): if either exact dependency is
unavailable, use **X15 HARD STOP** and request a version-pin amendment; do not
upgrade opportunistically. Therefore:

- **No Tantivy adapter source was authored against an unresolvable or
  substituted pin.** Authoring against 0.22.0 would be unbuildable;
  authoring against 0.22.1 would be an unauthorized version change.
- `run.py` detects the missing adapter and records
  `X15_HARD_STOP / TANTIVY_PIN_UNRESOLVABLE`.
- Required amendment: an explicit maintainer decision selecting a
  non-yanked Tantivy version (for example a reviewed `=0.22.1` pin) or an
  approved, reproducible vendoring policy for `0.22.0`.

No production `Cargo.toml`, `Cargo.lock`, workflow or test threshold was changed
to work around this.

## 4. X16 — Gradle wrapper

The official Gradle 8.14.3 distribution checksum was obtained from
`https://services.gradle.org/distributions/gradle-8.14.3-bin.zip.sha256`:

```text
bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531
```

It is recorded in `benchmarks/pr15d/adapters/lucene/gradle/wrapper/gradle-wrapper.properties`.
No `gradlew` or `gradle-wrapper.jar` is committed because a verified official
wrapper binary cannot be obtained without a maintainer-approved download
(X16). The adapter is therefore not runnable from a bare checkout even once a
JDK is present; that is an explicit, recorded gate rather than an unverified
binary.

## 5. X11 — Quervant public API proof (exact term, sort, exact count)

Verified directly in source on the source lock:

```rust
// crates/quervant-core/src/storage/fs.rs
pub fn open(root: impl AsRef<Path>) -> Result<Self, StorageError>            // FsDirectory

// crates/quervant-core/src/index/mod.rs
pub fn create(directory: Arc<dyn Directory>, schema: Schema, registry: AnalyzerRegistry) -> IndexResult<Self>
pub fn open_existing(directory: Arc<dyn Directory>, schema: Schema, registry: AnalyzerRegistry) -> IndexResult<Self>
pub fn writer(&self) -> IndexResult<IndexWriter>
pub fn snapshot(&self) -> Arc<ReaderSnapshot>

// crates/quervant-core/src/index/writer.rs
pub fn insert(&mut self, document: Document) -> IndexResult<()>
pub fn commit(&mut self) -> IndexResult<CommitOutcome>
pub fn close(mut self) -> IndexResult<()>

// crates/quervant-core/src/index/snapshot.rs
pub fn segment_count(&self) -> usize
pub const fn document_count(&self) -> u64

// crates/quervant-core/src/search/unified.rs
pub fn new(snapshot: &'a ReaderSnapshot, schema: &'a Schema,
           registry: &'a AnalyzerRegistry, limits: SearchLimits) -> Self  // UnifiedSearcher
pub fn search(&self, request: &UnifiedRequest, budgets: &Budgets,
              cancel: &dyn Cancellation) -> SearchResult<UnifiedResponse>

// crates/quervant-core/src/contract/query.rs
Query::Term { field: String, value: FieldValue }

// crates/quervant-core/src/contract/result.rs
pub fn new(fields: Vec<SortField>) -> Self                                  // Sort
pub fn new(field: impl Into<String>, direction: SortDirection) -> Self      // SortField
pub fn new(limit: usize) -> Result<Self, QueryError>                        // TopK
Projection::Fields(Vec<String>)
```

`UnifiedResponse.total_hits` is documented as the **exact** number of matching
effective-live documents before truncation, and `Sort` always appends the
logical document key as the final tie-break. `Sort::validate` requires a
sortable (`columnar`) field, so `doc_id` is declared
`FieldOptions::new(true, true, true)` with `FieldType::Keyword`.

Classification: **X11 AUTO — exact term/sort/total APIs proved and readable.**
No wrapper API, private module, `MatchAll` fallback, `MemoryDirectory` or
production edit was introduced.

### Empirical proof (not a qualified measurement)

`benchmarks/pr15d/adapters/quervant` was built in release mode and run against
the generated 16-row canonical fixture and the 10,000-row corpus:

- 16-row build: `documents_indexed=16`, `documents_verified=16`, one segment.
- Exact-term results matched the independent oracle for all four classes:
  `absent=0`, `rare=d00000000`, `medium=d00000000,d00000008`,
  `common=7 ids`.
- 10,000-row build: `documents_indexed=10000`, `documents_verified=10000`,
  `index_bytes=3090037`, one segment; `medium` returned 1,250 hits and `common`
  4,999 hits, exactly as the oracle predicts.

These numbers are adapter-sanity evidence only. They are **not** a three-engine
qualified series and must not be published as comparative performance.

## 6. X30 — CI

`.github/workflows/ci.yml` has `rust`, `msrv` and real `rustfs` jobs but **no
JDK, Gradle or Tantivy-capable benchmark job**, and the frozen Tantivy pin is
unresolvable. Adding the benchmark gate would require installing toolchains and
would still fail on the pin. Classification: **X30 DEFER-CI**; global CI was not
modified.

## 7. Resulting rule IDs

| Rule | Decision |
|---|---|
| X01 | AUTO — source lock unchanged, no relevant drift |
| X07 | AUTO — prior benchmark artifacts untouched |
| X09 | AUTO — corpus generator is byte-deterministic (T01) |
| X11 | AUTO — public exact-term/sort/total APIs proved |
| X14 | DEFER-ENVIRONMENT — no JDK 21 / Gradle 8.14.3 |
| X15 | **HARD STOP** — `tantivy = "=0.22.0"` is yanked and unresolvable |
| X16 | HARD STOP for Lucene execution — no verified wrapper binary committed |
| X22 | DEFER-ENVIRONMENT — three-engine comparison impossible |
| X24 | DEFER-ATTESTATION — no operator idle attestation was supplied by the agent |
| X30 | DEFER-CI — no benchmark-capable CI toolchain |
| X35 | AUTO — cold regime is labelled `process_cold`, never OS-cold |

**Overall S0 gate:** not qualified to open the measurement phase. Static,
engine-neutral work (S1 corpus/oracle, S2 Quervant adapter and Lucene source,
S3/S4 harness, validator, aggregator, deterministic tests, documentation) was
completed. Real three-engine trials remain **BLOCKED**.
