# PR 15E-A-F1 — independent-review handoff

**Status: `G11 = PENDING_REVIEW`.** This handoff describes what a *different,
authorized reviewer* must check against the **original private evidence**. The
coding agent cannot accept G11, cannot merge, and cannot authorize PR 15E-B.

## 1. Provenance

| Item | Value |
|---|---|
| PR | #82, branch `dev/pr15e-a-exact-workload-profiling`, base `main` |
| Base / merge-base | `de278e21c38bb60fa84c43951dadc7c0836787fd` (merged PR 15D-B) |
| Measured source (campaign) | `0f0091c02b3d7e057f1db10b3a12c06179f1c399` |
| Starting head of this fixup | `daabc06fdce92eafe912de04f956ceea21a92796` |
| Fixup head | the commit that introduces this file on PR #82 (parent `daabc06…`); the PR head is the authoritative value |
| Commits between measured source and this fixup | `380bec5` (report + sanitized manifest) and `daabc06` (test-only fixture isolation). Neither touches `profile.py`, the profiler transport, the oracle or production Rust |
| Published sanitized manifest | `benchmarks/reports/pr15e-a/profile-manifest.json`, SHA-256 `adfe7eadc2d948ab335e11de78edb4e86691590e464c2660e60eb37e611b4bb7` (**unchanged** by this fixup) |
| Unchanged protected blobs | `benchmarks/pr15e/profile.py` `0f8d1ab3…`, `benchmarks/pr15e/test_profile.py` `b41cc089…` (identical before and after) |

Nothing under `crates/`, `benchmarks/pr15d/`, `.github/`, `Cargo.toml`/`Cargo.lock`,
or the measured `target/pr15e/` run was modified by this fixup.

## 2. The defect and the approved CLI contract

`benchmarks/pr15e/verify.py::verify()` used to select the process exit code from
**capture completeness alone**. A complete matrix (`EVIDENCE_COMPLETE`) plus an
explicitly invalid `--analysis`, or a refused `--publish-manifest`, therefore exited
`0` — a requested operation that failed still looked like success to automation.

Normative outcome table (unchanged statuses; new exit selection):

| Case | Capture status | `--analysis` | Publication outcome | Exit | Persisted status |
|---|---|---|---:|---:|---|
| E01 | `EVIDENCE_COMPLETE` | not supplied | not requested | 0 | `EVIDENCE_COMPLETE` |
| E02 | `EVIDENCE_COMPLETE` | valid | not requested | 0 | `EVIDENCE_COMPLETE` |
| E03 | `EVIDENCE_COMPLETE` | invalid/missing | not requested | **4** | `EVIDENCE_COMPLETE`, `analysis_valid:false` |
| E04 | `EVIDENCE_COMPLETE` | not supplied/valid | newly written | 0 | `EVIDENCE_COMPLETE` |
| E05 | `EVIDENCE_COMPLETE` | not supplied/valid | identical existing file (`written:false` + `sha256`, no `code`) | 0 | `EVIDENCE_COMPLETE` |
| E06 | `EVIDENCE_COMPLETE` | not supplied/valid | refused (`code` present) | **4** | `EVIDENCE_COMPLETE` |
| E07 | `EVIDENCE_COMPLETE` | invalid | skipped (`X31_ANALYSIS_INVALID`) | **4** | `EVIDENCE_COMPLETE`, `analysis_valid:false` |
| E08 | `EVIDENCE_COMPLETE` | not supplied/valid | malformed success result | **4** | `EVIDENCE_COMPLETE` |
| E09 | `PARTIAL` | any | any/absent | **3** | `PARTIAL` |
| E10 | `BLOCKED` | any | any/absent | **3** | `BLOCKED` |
| E11 | `FAILED` | any | any/absent | **4** | `FAILED` |

Precedence: capture-completeness exit first (never upgradable); then the explicitly
requested analysis; then the requested publication. `profile.EXIT_*` constants,
`main()`/argparse, `verification.json` schema, stdout summary fields,
`evaluate()`, `validate_analysis()` and `publish_manifest()` are unchanged.

## 3. Pre-implementation correctness challenge (F1–F10)

| Invariant | How it is satisfied | Check |
|---|---|---|
| F1 status means capture completeness only | `evaluate()`/`_render_verification()` untouched; exit logic reads `payload["status"]` and does not write it | FX-01/03/05/07 |
| F2 no requested operation ⇒ 0 on complete evidence | analysis/publication checks are conditional on `args.analysis is not None` / `args.publish_manifest` | FX-01 |
| F3 valid analysis ⇒ 0 | `analysis["valid"]` inspected, not recomputed | FX-02 |
| F4 invalid/missing analysis ⇒ 4 with status kept | explicit `EXIT_FAILED` after summary emission | FX-03/04 |
| F5 refused publication ⇒ 4 | `"code" in publication` → `EXIT_FAILED` | FX-05/06 |
| F6 write and identical-bytes no-op both ⇒ 0 | `written` may be either bool; a 64-hex `sha256` is required and `code` must be absent | FX-08/09 |
| F7 incomplete/failed precedence preserved | capture exit returned first; 3 for PARTIAL/BLOCKED, 4 for FAILED | FX-07/10b |
| F8 refused publication writes nothing | `publish_manifest()` guards run before any write; unchanged | FX-05/06 (destination asserted absent) |
| F9 profiler transport/oracle/measured artifacts/Rust unchanged | protected blob SHAs and `git diff` proof below | §5 |
| F10 only an independent reviewer can close G11 | this handoff + §7; no self-approval anywhere in the tree | §7 |

The three counterexamples the plan required:

1. **`written:false` with a valid `sha256` and no `code` is a success** — it is the
   documented identical-bytes no-op returned by `publish_manifest()`; treating it as
   failure would report an idempotent rerun as broken (FX-09 asserts exit 0).
2. **`EVIDENCE_COMPLETE` must not be rewritten to `FAILED` when only the analysis is
   invalid** — completeness and requested-operation outcome are different facts;
   the persisted status stays `EVIDENCE_COMPLETE` while the exit is 4 (FX-03/04).
3. **Incomplete captures keep their nonzero precedence** — publication cannot mask a
   `PARTIAL`/`BLOCKED`/`FAILED` matrix; the capture exit is returned first
   (FX-07/10b).

## 4. Regression tests (executed)

`benchmarks/pr15e/test_verify.py::VerifyExitStatusTests` drives the real
`VERIFY.verify()` path (stdout summary captured, `verification.json` re-read) and
reuses the existing `VerifyFixture`, fixture-local `VERIFY.PUBLISH_PATH`,
`verify_args()` and the extracted `_analysis_entry`/`_write_analysis` helpers.

| Case | Result |
|---|---|
| FX-01 complete evidence, no requested operation | PASS (exit 0) |
| FX-02 valid requested analysis | PASS (exit 0) |
| FX-03 invalid requested analysis | **red pre-fix `0 != 4`** → PASS (exit 4, `EVIDENCE_COMPLETE`, `analysis_valid:false`) |
| FX-04 missing requested analysis file | **red pre-fix `0 != 4`** → PASS (exit 4) |
| FX-05 refused publication (`X31_TEST_FIXTURE`) | **red pre-fix `0 != 4`** → PASS (exit 4, no file written) |
| FX-06 invalid analysis + publication (`X31_ANALYSIS_INVALID`) | **red pre-fix `0 != 4`** → PASS (exit 4, no file written) |
| FX-07 incomplete evidence + publication | PASS (exit 3, `X31_EVIDENCE_INCOMPLETE`) |
| FX-08 newly written publication (`written:true`) | PASS (exit 0) |
| FX-09 identical existing manifest (`written:false` + sha256) | PASS (exit 0) |
| FX-10a malformed publication result | **red pre-fix `0 != 4`** → PASS (exit 4) |
| FX-10b capture integrity failure, no analysis | PASS (exit 4, `FAILED`) |
| FX-11 published manifest bytes unchanged | PASS (SHA identical before/after) |

Pre-fix red command:
`python3 -m unittest test_verify.VerifyExitStatusTests` → `Ran 11 tests … FAILED
(failures=5)` with `0 != 4` for FX-03/04/05/06/10a.
Post-fix: `Ran 11 tests … OK`.

One pre-existing expectation encoded the defect and was reconciled in the same file:
`PublicationTests.test_t43_publication_refuses_sensitive_content` asserted exit `0`
for a refused publication. It now asserts exit `4` and keeps every other assertion
(`EVIDENCE_COMPLETE`, `written:false`, `X31…`). The assertion was tightened, never
weakened.

## 5. Changed paths and protection proof

Allowed files for this fixup (only these changed):

1. `benchmarks/pr15e/verify.py` — final exit selection only.
2. `benchmarks/pr15e/test_verify.py` — new `VerifyExitStatusTests`, extracted analysis
   helpers, reconciled publication-refusal expectation.
3. `docs/pr-artifacts/pr-15e-a/test-traceability.md`.
4. `docs/pr-artifacts/pr-15e-a/decision-log.md`.
5. `docs/pr-artifacts/pr-15e-a/fixup-review-handoff.md` (this file).

Immutability checks performed at the fixup head:

```text
sha256(benchmarks/reports/pr15e-a/profile-manifest.json)
  = adfe7eadc2d948ab335e11de78edb4e86691590e464c2660e60eb37e611b4bb7   (before and after)
git rev-parse HEAD:benchmarks/pr15e/profile.py        = 0f8d1ab3…  (before and after)
git rev-parse HEAD:benchmarks/pr15e/test_profile.py   = b41cc089…  (before and after)
git diff --name-only daabc06..HEAD -- crates/ benchmarks/pr15d/ .github/ Cargo.toml Cargo.lock
  → empty
```

No capture was re-run, no attestation was recreated, no profiler was launched, and no
`target/pr15e/` evidence file was written or rewritten by this fixup.

## 6. Local gates (fixup head)

Every command below was executed through a wrapper that runs the command **with no
pipeline**, writes its stdout/stderr to a log, and records **the command's own exit
status** (`rc=$?` immediately after the command). PASS below requires: recorded
exit `0`, at least one parsed `test result:` summary (or an equivalent explicit
success marker), zero `test result: FAILED`, and zero compile diagnostics. Exit
statuses were never inferred from an `awk` summary or from a pipeline.

| Gate | Own exit | Parsed evidence |
|---|---:|---|
| `cargo test --workspace --all-targets` (stable) | 0 | 116 `test result:` summaries, 2169 passed, 0 failed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` (stable) | 0 | 116 summaries, 2173 passed, 0 failed, 75 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | 0 | 116 summaries, 2169 passed, 0 failed, 10 ignored |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 0 | 116 summaries, 2173 passed, 0 failed, 75 ignored |
| `cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` (stable, 1.85.0) | 0 / 0 | `test result: ok. 5 passed` each |
| `cargo fmt --all -- --check` (stable, 1.85.0) | 0 / 0 | empty output |
| `cargo clippy` stable/MSRV × default/all-features | 0 / 0 / 0 / 0 | 0 `error`/`warning` diagnostic lines |
| `cargo llvm-cov … --fail-under-lines 85` | 0 | **92.31 %** lines (51 738 / 4 236 missed), 87.90 % functions |
| `cargo doc --workspace --all-features --no-deps` | 0 | generation succeeded |
| `cargo bench --workspace --no-run` | 0 | **build only** — no benchmark executed |
| `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py'` | 0 | `Ran 90 tests`, `OK (skipped=1)` |
| `PR15E_RUN_REAL_INTEGRATION=1 … test_profile.RealAdapterIntegrationTest` (cwd `benchmarks/pr15e`) | 0 | `Ran 1 test`, `OK` |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | 0 | `Ran 83 tests`, `OK` |
| `bash benchmarks/scripts/test-scripts.sh` | 0 | 108 passed, 0 failed |
| `git diff --check` | 0 | no whitespace errors |

Two disclosures so the numbers are not misread:

- `cargo test --all-targets` also runs the 10 `harness = false` Criterion bench
  targets in **Criterion test mode** (one `Testing …`/`Success` pair per benchmark
  case: 74 pairs, 0 `Failed`, 0 panics, in every invocation). That mode emits no
  timing and no `time: [...]` line, so **no performance benchmark was measured**.
  This is the repository's normal `cargo test` behaviour.
- One wrapper invocation of the real-adapter test was first launched from the repo
  root and exited `1` with `ModuleNotFoundError: test_profile` — an invocation-path
  error, not a test failure. Re-run from `benchmarks/pr15e` it exited `0` with
  `Ran 1 test … OK`; the corrected run is the one reported above.

| `PR15E_RUN_REAL_INTEGRATION=1 … test_profile.RealAdapterIntegrationTest` | PASS — real adapter + real `FsDirectory` 10 K/100 K + independent oracle |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests |
| `cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` (stable and 1.85.0) | PASS — 5 + 5 |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108/108 |
| `cargo fmt --all -- --check` / `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy` stable/MSRV × default/all-features | PASS (4/4) |
| `cargo test` stable/MSRV × default/all-features | PASS — 2169 / 2173 passed, 0 failed, 75 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 92.31 % lines |
| `cargo doc --workspace --all-features --no-deps`, `cargo bench --workspace --no-run` | PASS |
| `git diff --check` | PASS |

Exact-head GitHub Actions results for the final fixup head are recorded in the PR
checks; the pre-fixup head `daabc06…` is green (`rust`, `msrv`, `rustfs`).

## 7. Reviewer protocol (private, read-only) — RV-01…RV-08

The reviewer must be a **different authorized person** with approved local access to
the original run directory. No raw profiler artifact, attestation or absolute path may
be uploaded to GitHub, CI artifacts or any unapproved recipient.

| ID | Check | Pass rule |
|---|---|---|
| RV-01 | Provenance | `prepare.json` and `prepared_digest` re-derive; `source.head_sha` = `0f0091c…`; corpus/adapter/index digests as recorded; ancestry from measured SHA to the review head contains no measured-code change |
| RV-02 | Human attestation | Compare `<run>/attestation.json` (host, exact UTC start/end, statement) with the operator's original message and with each capture's `first_utc`/`last_utc`/`attestation` block; no retroactive consent |
| RV-03 | Inventory | 20 unique capture manifests in the fixed matrix, 128 artifact records, every file present with matching SHA-256/bytes, no `failure.json`, no extra/unlisted capture directory |
| RV-04 | Oracle/semantics | Recompute per-lane `total_hits`/ordered `doc_ids` from the frozen corpus; confirm 5 warmups, request counts, single adapter PID, `clear` contention before/after |
| RV-05 | Tool reports | Sample counts ≥ 100, 786 lost samples on the 100 K common lane disclosed, heaptrack 1.5.0 preamble artifact present on all 8 allocation lanes; report digests match |
| RV-06 | Attribution | All 81 `analysis.json` entries cite real raw lines; the four hot-path categories hold; nested inclusive shares are not summed; the 49.7 M/27.3 M/34.9 M buckets remain `UNRESOLVED`; no instrumented-vs-uninstrumented performance claim |
| RV-07 | Publication/privacy | Committed manifest `adfe7ead…`, `source_sha` `0f0091c…`, 20 lanes, 128 artifacts, `PRIVATE_PENDING_REVIEW`, no host/user/absolute path |
| RV-08 | Verdict | Named reviewer issues dated PASS/REJECT/HOLD citing PR head, measured source, evidence reviewed, exceptions, residual risks, acknowledgement |

Do **not** re-run `verify.py` in place against the canonical run without first
hash-preserving the originals: it rewrites `verification.json`. Prefer read-only
hash/inventory comparison.

## 8. Residual risks the reviewer must accept or hold

WSL2 `perf` symbolization limits and 786 lost samples on one lane; truncated
heaptrack stacks (three large buckets unresolved); profiler samples include adapter
start-up and warmups; the workload is a synthetic exact-term `FsDirectory` lane and
says nothing about `doc_id`-scored BM25, RustFS-backed indexes or distributed search;
this fixup changes CLI success semantics only and does not re-validate any
measurement.

## 9. What is ready and what is not

Ready: bounded fixup commit, FX regression evidence, local gates, exact-head CI,
immutability proof, sanitized manifest and dossier.

Not ready: **G11** (independent raw-evidence acceptance), **merge**, and any
**PR 15E-B** design, approval or implementation. `PR_ACCEPTANCE = PENDING_REVIEW`;
`PR15E_B_AUTHORIZED = NO`.
