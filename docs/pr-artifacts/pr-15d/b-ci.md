# PR 15D-B — S1/S2 CI restructuring record

**Status:** IMPLEMENTED LOCALLY / ACTUAL GITHUB ACTIONS RUNS NOT YET OBSERVED.

This record covers only the durable CI separation (S1) and the bounded
full-correctness contract (S2). It contains **no performance claim** and no
qualified measurement.

## S1 — exact file changes

### `.github/workflows/ci.yml` (modified: deletion only)

Removed the complete `pr15d-adapters` job together with its three-line A1
comment header. Nothing else changed: the `push`/`pull_request` triggers,
`permissions: contents: read`, and the `rust`, `msrv`, `rustfs` jobs are
byte-identical to the source lock apart from the trailing whitespace at the
deletion boundary (`git diff` shows only `-` lines).

Verified after deletion:

```
git grep -n "pr15d" .github/workflows/ci.yml   -> no matches
job names in ci.yml                            -> rust, msrv, rustfs
```

### `.github/workflows/comparative-adapters.yml` (new, permanent)

| Element | Value |
|---|---|
| `name` | `Comparative Adapters` |
| `on.pull_request.paths` | `benchmarks/pr15d/**`, `.github/workflows/comparative-adapters.yml` |
| `on.workflow_dispatch.inputs.full_correctness` | `type: boolean`, `required: false`, `default: false` |
| `permissions` | `contents: read` only |
| Job `comparative-smoke` guard | `github.event_name == 'pull_request' \|\| (github.event_name == 'workflow_dispatch' && inputs.full_correctness == false)` |
| Job `comparative-full-correctness` guard | `github.event_name == 'workflow_dispatch' && inputs.full_correctness == true` |

Both jobs are self-contained (no `needs:`) and repeat the full verified build:

1. `actions/checkout@v4`
2. `sha256sum -c A1-CHECKSUMS.sha256` plus the pinned `gradle-8.14.3-bin.zip`
   and `distributionSha256Sum=bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531`
   assertions, **before** any Java invocation
3. `actions/setup-java@v4` Temurin `21`
4. `dtolnay/rust-toolchain@master` toolchain `1.98.1`
5. `cargo build --release --locked --manifest-path .../{quervant,tantivy}/Cargo.toml`
   into `target/pr15d/build/...`
6. `./gradlew --no-daemon classes installDist` with
   `PR15D_LUCENE_BUILD_DIR`
7. `python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/comparative[-full]-corpus`
8. correctness invocation (see below)

Correctness invocations:

- `comparative-smoke` — the **existing 10K** smoke, unchanged scope, no
  `--sizes`. It is explicitly not relabelled as a 16–1000 document fixture.
- `comparative-full-correctness` — `corpus/oracle.py --corpus ...` (independent
  verification of both sizes) followed by
  `harness/smoke.py --sizes 10000,100000`.

Neither job invokes `harness/run.py`, passes an idle-attestation flag, or emits
a `pr15d-qualified` artifact (I06, I08, T06, T23).

`benchmarks/README.md` was left untouched, so its path filter was deliberately
not added; the filter list is exactly the two authorized entries.

## S2 — `--sizes` contract and why X21 was not triggered

`harness/smoke.py` previously bound the corpus size in a single module constant
`N = 10000` used at four sites. The full gate is implementable mechanically
without touching adapter protocol, the oracle, control flow or default output:

- new `SIZES = (10000, 100000)`, asserted equal to `oracle.N_VALUES` by a test;
- new `parse_sizes(text)` accepting only a non-empty, comma-separated,
  duplicate-free subset of `SIZES`; `None` (the CLI default) still yields
  `[10000]`;
- `_run_engine(..., n=N)` gained a trailing keyword so the existing call sites
  and the A1 test keep working unchanged;
- `run()` loops over the selected sizes and still prints exactly one JSON
  summary line per size, so the default invocation is unchanged.

Rejections (all covered by tests): `sizes_empty` (`""`, `"  "`, `"10000,"`,
`",100000"`, `"10000,,100000"`), `sizes_unknown` (`"16"`, `"1000"`),
`sizes_duplicate` (`"10000,10000"`), `sizes_malformed` (`"1e5"`, `"-10000"`,
`"10_000"`, `"abc"`, `"10000;100000"`, `"10.0"`, non-ASCII digits),
`sizes_invalid` (non-text).

No adapter, oracle, protocol, metric or sample-count change was made. Because a
bounded mechanical extension existed, **X21 does not apply**; had it required a
control-flow redesign, the plan mandates a hard stop instead.

## Deterministic tests added (`harness/test_pr15d.py`)

| Class | Covers |
|---|---|
| `SmokeSizeSelectionTests` | default stays 10K; accepts the frozen pair; rejects unknown/empty/duplicate/malformed/non-text; `SIZES == oracle.N_VALUES` |
| `ComparativeWorkflowContractTests` | T01 (only `rust`/`msrv`/`rustfs` remain; no `pr15d`); T02/T03 (trigger paths are exactly the two authorized entries); T04/T05 (job guards match the matrix); T06 (no timed harness, no idle attestation, no qualified artifact, in either workflow); T07 (checksum precedes every Gradle invocation); T12 (full gate runs `--sizes 10000,100000` for all three engines plus the independent oracle, smoke gate stays on the default); read-only permissions and no `secrets.` |

The test file remains standard-library only; workflow checks are textual and
structural over the two files, so no new dependency was introduced.

Result: `python3 benchmarks/pr15d/harness/test_pr15d.py` → `Ran 50 tests ... OK`.

## What is *not* proven by local tests

Local parsing cannot prove GitHub trigger behaviour (plan §4). Still unobserved
and therefore not claimed:

| Test | Why unobserved |
|---|---|
| T03/T04/T05 (real trigger + dispatch modes) | `gh` token invalid (X43); no PR could be opened or workflow dispatched by the agent |
| T07/T08/T09 (real Gradle/JDK/missing-binary failures) | requires the hosted runners or a local JDK 21 + verified wrapper execution |
| T29 exact-head CI | depends on a pushed branch |

`ci.yml`'s `pr15d-adapters` job already demonstrated the identical build-and-smoke
path succeeding on the source-lock commit at run `41124428333`, which is why the
relocation is low-risk — but the relocated workflow still needs its own observed
runs before S1 is "PASS".

## Required next human action for S1

1. `gh auth login -h github.com` (the stored token is invalid), or open the PR
   manually.
2. Push `dev/pr15d-b-comparison-qualification` and open the PR so
   `comparative-smoke` runs on the exact head.
3. Run `workflow_dispatch` twice on that head — `false` then `true` — and record
   the run IDs here.

## Local end-to-end correctness evidence (S2, this host)

This is **correctness only**. No timing was recorded, no `run.py` was invoked, and
no qualified report was produced.

Toolchain on this host: `rustc 1.98.1` (stable), `1.85.0`, `1.98.1` all
installed; `openjdk 21.0.12.1` (JDK 21 present locally, which supersedes the A1
note that no JDK was available); `cargo-llvm-cov 0.9.1`.

Verified prerequisite before Java execution:

```
cd benchmarks/pr15d/adapters/lucene && sha256sum -c A1-CHECKSUMS.sha256
gradle/wrapper/gradle-wrapper.jar: OK
gradlew: OK
gradlew.bat: OK
```

Adapter builds, exactly as the workflows run them:

```
cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --target-dir target/pr15d/build/quervant
cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/tantivy/Cargo.toml  --target-dir target/pr15d/build/tantivy
PR15D_LUCENE_BUILD_DIR=$PWD/target/pr15d/build/lucene ./gradlew --no-daemon classes installDist   # BUILD SUCCESSFUL, Gradle 8.14.3
```

Corpus (generated twice, byte-identical to the frozen formula; manifest verified
by the independent oracle):

```
5cdc9341d20bdc525af7e11d3b64bcabf66af9a6eaf27c7dfaddc87280be9a8b  pr15d_v1_N10000.tsv    (546283 bytes, 10000 rows)
6ea867fe10679d12fa569822b27e58a8898d866938cf524870c84b0d80d5da4a  pr15d_v1_N100000.tsv   (5462533 bytes, 100000 rows)
69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151  pr15d_v1_manifest.json
```

Full gate — `smoke.py --sizes 10000,100000`, exit `0`:

| n | engine | documents | queries checked | segments | index bytes |
|---|---|---|---|---|---|
| 10000 | quervant | 10000 | 8 | 1 | 3090037 |
| 10000 | tantivy | 10000 | 8 | 4 | 301488 |
| 10000 | lucene | 10000 | 8 | 1 | 186052 |
| 100000 | quervant | 100000 | 8 | 1 | 30965025 |
| 100000 | tantivy | 100000 | 8 | 4 | 2961530 |
| 100000 | lucene | 100000 | 8 | 1 | 1858642 |

Both sizes emit one JSON summary line each with
`"timings_reported": false` and the same manifest digest, i.e. the `--sizes`
extension exercises the unchanged oracle path at both frozen sizes for all three
engines.

Default path — the same invocation **without** `--sizes` — exits `0` and prints
**exactly one** line with `"n": 10000`, confirming the A1 default is unchanged.
Its payload is element-for-element identical to the `n = 10000` line of the
multi-size run except Tantivy's `index_bytes` (299536 vs 301488), which is a
per-run on-disk artefact size and not a correctness field. Document counts,
query counts, segment counts and oracle results match exactly.

What this does and does not prove:

- **Proves:** the bounded `--sizes` selector works end-to-end, the frozen oracle
  accepts every lane at 10K and 100K for all three engines, and the default A1
  behaviour is preserved.
- **Does not prove:** GitHub trigger behaviour, the hosted-runner JDK/wrapper
  path, or anything about performance. Those remain `DEFER` (X42/X43).
