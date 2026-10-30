# PR 15D acceptance

**Status: PENDING REVIEW / BLOCKED.** No independent human acceptance has been
given, and the mandatory three-engine qualification has not executed. The
coding agent is **not** claiming PR 15D is DONE.

## Deliverable state

| Area | State |
|---|---|
| S0 preflight | Complete; one HARD STOP (X15) and DEFER-ENVIRONMENT (X14/X22/X24) |
| S1 neutral corpus + oracle | Complete; deterministic and independently verified |
| S2 Quervant adapter | Complete; builds and passes the exact-term smoke |
| S2 Tantivy adapter | **Not authored** — frozen pin is yanked (X15) |
| S2 Lucene adapter | Source complete, **unbuilt/unverified** — no JDK (X14), no verified wrapper (X16) |
| S3 runner | Implemented; refuses to measure without all gates |
| S4 validator/aggregator/tests | Complete; T01–T22 deterministic suite passes |
| S5 three-engine trials | **BLOCKED** |
| S6 CI | **DEFER-CI (X30)** — unchanged |

## Local verification actually run

Working tree: `dev/pr15d-comparative-qualification` based on
`28dc6c2cf95ee24d2b48a580a7cb2a7a8f7dcc6e` (uncommitted changes at report time).

| Command | Result |
|---|---|
| `python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus` | PASS — deterministic digests |
| `python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus` | PASS |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 24 tests, 1 SKIP (T04 without a prebuilt Quervant adapter binary) |
| `PR15D_QUERVANT_BIN=… test_pr15d.py AdapterSmokeTests.test_t04_quervant_adapter_smoke` | PASS |
| `cargo build --release` in `benchmarks/pr15d/adapters/quervant` | PASS (stable 1.98.1) |
| `python3 benchmarks/pr15d/harness/run.py --out target/pr15d/runs/smoke` | BLOCKED as designed (exit 4): X15, X14, X24 |
| `python3 benchmarks/pr15d/harness/validate.py --run target/pr15d/runs/smoke …` | BLOCKED as designed (exit 3) |
| Lucene adapter build/test | BLOCKED — no JDK/Gradle (X14/X16) |
| Tantivy adapter build/test | BLOCKED — yanked pin (X15) |
| Three-engine qualified trials | BLOCKED |

Workspace gates (`cargo fmt/clippy/test/llvm-cov/doc/bench`) are unaffected:
no production Rust file, manifest, lockfile or workflow was changed. They still
must be run at final commit time; the benchmark-only adapters are outside
workspace membership.

## Independent reviewer checklist

1. **Source and artifacts.** Verify the PR head, confirm only PR 15D paths plus
   the appended `benchmarks/README.md` section changed, and confirm no
   `crates/` or production `Cargo.lock` change.
2. **Frozen evidence.** Confirm `pr15d_v1` digests, PR 15B/15C artifacts and
   versioned old workloads are unchanged.
3. **Negative validator tests.** Run `test_pr15d.py`; confirm the following are
   rejected with nonzero exit and the precise code: tampered corpus (T03),
   analyzer/ordering mismatch (T05), off-by-one total (T06), bad duration (T07),
   missing/duplicate lane (T08), missing version/source/host (T09), missing
   attestation and contention (T10), 2 trials / 19 samples (T11), failed
   build/commit/reopen (T14), OS-cold mislabel (T15), mixed host (T16), scored
   lane without proof (T17), tampered aggregate (T13), path escape (T19).
4. **Protocol.** Check `protocol/schema.json`, each adapter's `schema`,
   `engine`, `request_id`, `status`, positive `engine_ns`, exact `total_hits`,
   ascending `doc_ids`, and that failures never return zero hits.
5. **Semantics.** Confirm the mandatory lane is exact `Keyword` membership with
   `doc_id` ascending, and that no scored ratio or score claim exists.
6. **Timing hygiene.** Confirm `engine_ns` wraps only the public engine
   operation, process start/open/TSV/oracle/JSON are outside the timer,
   `process_cold` is not called OS-cold, warmups are excluded, and 20 samples
   are present.
7. **Dispersion.** Confirm aggregate marks `INCONCLUSIVE` when trial
   `max/min > 1.10` or trial-median ranges overlap, and makes no significance
   claim.
8. **CI.** Confirm no global CI threshold/test was disabled. This run is
   expected to be CI-neutral because X30 applies.
9. **Accept/reject explicitly.** Acceptance requires a maintainer decision on
   the X15 Tantivy pin amendment, JDK 21/Gradle provisioning and the X16 wrapper.
   Until then this is **BLOCKED**, never ACCEPTED.

## Requested maintainer decisions

- **X15:** select a non-yanked Tantivy pin (e.g. a reviewed `=0.22.1`) or
  approve a reproducible `0.22.0` vendoring policy.
- **X14/X16:** provision JDK 21 + Gradle 8.14.3 and approve a verified wrapper
  (or accept an explicit `gradle` executable instead of the wrapper).
- **S5:** an operator-attested, contention-checked, clean-source three-trial
  series must then be executed by a human-present operator.
