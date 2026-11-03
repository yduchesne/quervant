# PR 15E — optimized three-engine campaign: execution record

**Status: `THREE_ENGINE_OPTIMIZED_QUALIFIED_REVIEW_READY`.** One complete PR 15D three-engine
campaign on optimized Quervant `40ca10b…`; validator and aggregator `QUALIFIED`; 54/54 contention
probes `clear`. Documentation/report-only task: no production, adapter, harness, frozen-input, CI,
format or dependency change. **PR #83 was not merged; G11 remains `PENDING_REVIEW`.**

## 1. P0 preflight (observed)

| Item | Value |
|---|---|
| Branch / head | `dev/pr15e-b1-live-bitmap-postings-membership` @ `41e10483dd59217595895ad5433d9ae572522cf2` (exact expected PR head; clean tree) |
| Remote branch head | identical to local head |
| `origin/main` | `506beb038e070aee780dacfda1b5dbb9da30b642` (recorded; not integrated or rebased) |
| Optimized source | `40ca10bae46f2d7df7804a0a129a99a4daf35ef0` (ancestor of the PR head) |
| Historical PR 15D source | `40a9c26a57aa23640904075e77be956ee52718bc` (context only) |
| Original base | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` |
| Protected diff `OPT..PR head` (crates, Cargo, frozen adapters/spec/corpus/protocol/run/validate/aggregate) | **empty** |
| Frozen diff `PR15D_HIST..OPT` (spec/corpus/protocol/adapters/run/validate/aggregate) | **empty** |

Input hashes recorded before the campaign (and re-checked after publication):

| File | SHA-256 (first 16) |
|---|---|
| `benchmarks/reports/pr15d/pr15d-qualified.json` | `c9e8ed722aefc4fe` |
| `benchmarks/reports/pr15e-b1/cumulative-closeout.json` | `4ee745f9deb3a270` |
| `docs/pr-artifacts/pr-15d/qualification.md` | `fc7ff7b42a117905` |
| `benchmarks/pr15d/spec/pr15d_v1.json` | `ec6c0db865845184` |

## 2. P1 measurement worktree and toolchain

The runner has no `--source-tree` option and records the `HEAD` of the checkout containing
`run.py`, so the campaign ran **inside a detached worktree at exactly `40ca10b`**:

`target/pr15d/three-engine-optimized-worktrees/opt-40ca10b-01` (first free suffix `01`; nothing
was deleted or reused), clean tracked tree, `ext4` filesystem.

| Prerequisite | Observed |
|---|---|
| Python / Rust | `3.12.3` / `rustc 1.98.1`, `cargo 1.98.1` |
| Java | OpenJDK `21.0.12.1` (`java` and `javac` both 21) |
| Lucene Gradle wrapper | `sha256sum -c A1-CHECKSUMS.sha256` → `gradle-wrapper.jar: OK`, `gradlew: OK`, `gradlew.bat: OK` |
| Tantivy pin | `tantivy = "=0.22.1"` with matching `Cargo.lock` |
| Harness self-tests | `python3 benchmarks/pr15d/harness/test_pr15d.py` → 83 tests, `OK (skipped=3)` |

## 3. P2 corpus (frozen, verified)

```sh
python3 benchmarks/pr15d/corpus/generate.py --out "$TREE/target/pr15d/three-engine-optimized-corpus"
python3 benchmarks/pr15d/corpus/oracle.py --corpus "$TREE/target/pr15d/three-engine-optimized-corpus"
```

Generated in a fresh private directory; canonical manifest SHA-256
`69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` (matches the frozen
requirement), verified with `oracle.load_and_verify` and `oracle.canonical_json_bytes`, rows
10,000 / 100,000.

## 4. P3 the complete campaign (single run)

```sh
python3 benchmarks/pr15d/harness/run.py \
  --trials 3 --corpus "$CORPUS" --out "$RUN" --idle-confirmed
```

Run root: `$TREE/target/pr15d/runs/optimized-full-01` (first free suffix). Exit code **0**.
The runner built the locked Quervant/Tantivy release adapters and the Lucene Gradle distribution
outside timed regions, created real local indexes per trial and N, rotated engine order, ran the
32-lane matrix per engine, oracle-checked every response, and performed 6 contention probes per
engine-trial. `run.json`: `status=complete`, `qualified=true`, `source_sha=40ca10b…`,
`corpus_manifest_sha256=69052c66…`, `filesystem=ext4`, `native_filesystem=true`, adapters for all
three engines.

**Idle authorization:** the maintainer's explicit assumed-idle instruction was used for
`--idle-confirmed`. It is recorded as authorization, not as an observed idleness fact. **54/54
real contention probes returned `clear`**; `--allow-contended` was never used and no probe was
modified.

## 5. P4 validation, aggregation and independent re-derivation

```sh
python3 benchmarks/pr15d/harness/validate.py --run "$RUN" --out "$RUN/validation.json"   # exit 0
python3 benchmarks/pr15d/harness/aggregate.py --run "$RUN" \
  --out "$RUN/qualified-optimized-three-engine.json" --md "$RUN/qualified-optimized-three-engine.md"  # exit 0
PYTHONPATH=…/harness python3 -c '…aggregate.verify_aggregate(…)…'   # AGGREGATE_REDERIVATION_PASS
```

Structural assertions (all passed): one source SHA across `run.json`/`validation.json`/aggregate;
`status=QUALIFIED`, `errors=[]`; 3 trials, 20 samples per lane; 32 unique `(lane, regime)` rows;
both regimes present; `score_comparison=NOT_APPLICABLE`; each lane has all three engines with 3
trial medians; each trial manifest `qualified=true`, 32 lanes, 6 contention probes all `clear`,
20 samples per lane and `oracle_ok=true`. **`THREE_ENGINE_32_LANE_VALIDATION_PASS`, 54/54 clear.**

## 6. P5/P6 publication (sanitized)

Published exactly three new files; no historical file was overwritten:

| File | Note |
|---|---|
| `benchmarks/reports/pr15e-b1/optimized-three-engine-pr15d.json` | exact copy of the qualified aggregate; SHA-256 `7a726bf41fe52bfcd5763f7992f050045c76493abdbb9573e216d8aacd6974cd` (identical to the private aggregate) |
| `docs/pr-artifacts/pr-15e-b1/optimized-three-engine-qualification.md` | report: 16 warm + 16 process-cold lanes, nine-lane historical comparison, ratios, ingestion/size/throughput, limits, A01–A12 |
| `docs/pr-artifacts/pr-15e-b1/optimized-three-engine-execution.md` | this record |

The aggregate contains no absolute paths, hostnames, usernames, credentials, attestation text or
raw samples; it carries only a host **fingerprint hash**, `run_id`, `source_sha`, filesystem type
and statistics. The publication scan used
`benchmarks/pr15e/verify.py::sensitive_hits` plus manual review; the only expected public URL in
the repository is the PR link. Raw manifests and logs remain private under the run directory
(no cleanup, compression or deletion).

Private run manifest digests (recorded in the private run directory):

| Manifest | SHA-256 |
|---|---|
| `run.json` | `137ea8072fd7cac3f98a3cf0304c05a439a76c2003751a86805912d969565ed3` |
| `validation.json` | `0a3d42e6b3cdd023ae75709585069ef1bb347402abd8cbd7ec3f02c7cad51175` |
| `qualified-optimized-three-engine.json` | `7a726bf41fe52bfcd5763f7992f050045c76493abdbb9573e216d8aacd6974cd` |
| `qualified-optimized-three-engine.md` | `6f8d64cc5084911dd66d4f92df88d2c0e50e395686c9e7420cd9a20aaab05e48` |

## 7. P7 QA and source-scope audit

Documentation/report-only task: `cargo` tests, clippy, coverage, RustFS and the PR 15E Rust QA were
**already qualified for the unchanged optimized code** and were **not** re-run as new evidence.
Executed here: `git diff --check`, `python3 -m json.tool` on the published JSON,
`python3 -m unittest discover -s benchmarks/pr15e_b1` and
`python3 benchmarks/pr15d/harness/test_pr15d.py`.

Changed-path audit: only the three allowlisted publication files. No `crates/`, `benchmarks/pr15d/`
adapter/harness/corpus/spec change, no `Cargo.toml`/`Cargo.lock`, no `.github/`, no test-source
change; all input hashes above unchanged after publication.

## 8. Failures and anomalies

None. The campaign ran once, exited 0, validated, aggregated and re-derived without retries or
lane filtering. Two conditions worth recording rather than treating as defects:

* The runner's stdout log for the run was empty; all results are in `run.json`, the per-trial
  manifests and the qualified aggregate, which are the authoritative artifacts.
* Several lanes are flagged `INCONCLUSIVE` by the canonical dispersion rule (fast Tantivy lanes
  with overlapping trial ranges). They are published with their ratios as descriptive and are not
  claimed as conclusive wins or losses.
