# BM-09 acquisition ledger and applied decision rules

Execution host observations were taken on the execution branch before any real
acquisition attempt. No timed measurement was performed.

## Decision matrix (M01–M90) — applied rules

| Rule | Trigger / evidence | Action taken | Gate affected |
| --- | --- | --- | --- |
| M01 | `git rev-parse HEAD` = `a5a8303e…` and `git status --porcelain` empty | AUTO-RESOLVE: created `dev/bm09-real-qualification`, recorded baseline, ran P0 | P0 / repo owner |
| M06 | `config.codec`, `evidence.paths`, `config.contracts.validate_receipt` inspected and reused as-is | AUTO-RESOLVE | Implementation |
| M07 | BM-03 `execute_synthetic`/`SyntheticAdapter` still refuse real adapters | AUTO-RESOLVE: unchanged; official facade never calls them | Scope |
| M08 | BM-06 `publish_bundle` hardcodes the synthetic manifest | AUTO-RESOLVE: extracted `publish_validated_members_atomic` and kept the synthetic public API and fault tests green | Publication |
| M10 | PR15D runner/validator/aggregator/oracle exist byte-identical | AUTO-RESOLVE: used read-only as the measurement backend | Cross-engine |
| M11 | `protocol_v3r3.json` has `diagnostic_only=true` | AUTO-RESOLVE: preserved and disclosed; outer mapping recorded in the template | Retained-key |
| M12 | `target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json` **absent** | DEFER AND CONTINUE: retained-key real acquisition **BLOCKED** | Retained-key Gate A |
| M17 | Historic `pr15i-d3-c-v3r3` archives exist under the operator `HOME` | AUTO-RESOLVE: an isolated `HOME` namespace is required for any future run; `probe_isolated_home` implemented and tested | Host |
| M19 | BM-08 eleven synthetic catalog pins unchanged | AUTO-RESOLVE: BM-08 regression re-run green | L2 |
| M24 | No reviewer approval record exists and none may be self-minted | DEFER AND CONTINUE: candidate template/authorization digests only, no timed control | G0 |
| M28 | The operator premise "host is idle" is not readiness evidence | DEFER: readiness must be sampled live before any control (`official.controls`) | Host |
| M34 | `target/pr15d` corpus/build artefacts absent; adapter binary set not provisioned for a measured run | DEFER AND CONTINUE: cross-engine real acquisition **BLOCKED** | Cross-engine |
| M53 | No authentic PR15D archived trial manifests on this host | DEFER AND CONTINUE: cross-engine historical parity **BLOCKED** | Parity |
| M55 | No authentic T7 micro/F1/policy series | DEFER AND CONTINUE: retained-key policy is `POLICY_NOT_DERIVABLE`, Gate C typed block, Gate D/E blocked | Retained-key |
| M74 | No local RustFS service; hosted job status not observed from this terminal | DEFER: RustFS gate remains unverified locally | Source QA |
| M76 | Console entrypoint previously skipped under an uninstalled package | AUTO-RESOLVE: installed in `target/bm09-venv` (`pip install -e ./benchmarks`); the console contract test now executes | Framework QA |
| M77 | `benchmarks/pr15d/harness/test_pr15d.py::test_t01_standard_ci_keeps_only_the_required_jobs` fails | Classified **3 (deterministic pre-existing)**: reproduced on a clean `a5a8303` worktree; the assertion predates the BM-06 `python-contracts` CI job and PR15D files may not be edited | QA reporting |
| M90 | A retained-key parity PASS would need authentic policy inputs and a reviewer | BLOCKED for that family; no improvisation | Parity |

## Preconditions verified without timing

| Check | Result | Evidence |
| --- | --- | --- |
| Frozen legacy protocol raw SHA-256 | PASS (`c6193830…6f1c`) | `official.protocols.verify_backend_protocol` |
| PR15D spec raw SHA-256 | PASS (`ec6c0db8…e466`) | same |
| D3-C T6 freeze receipt | **MISSING** | `target/pr15i-d3-c/v3r3-freeze/` does not exist |
| D3-C authentic archives (read-only) | PRESENT (3 archives + sidecars) | `~/.local/share/quervant/benchmark-evidence/pr15i-d3-c-v3r3/` |
| PR15D corpus (10K/100K) | NOT PROVISIONED | `target/pr15d/` absent |
| JDK 21 / Gradle present | PRESENT (read-only probe) | `java -version`, `which gradle` — **not** an adapter build receipt |
| Native filesystem of the checkout | ext4 | `findmnt -T .` |
| Legacy source byte identity | PASS (32 files) | `docs/pr-artifacts/bm-09/legacy-source-manifest.json` |

## Terminal acquisition outcomes

| Family | Outcome | Reason |
| --- | --- | --- |
| retained-key | `BLOCKED` | Missing T6 freeze receipt (M12) and missing independent G0 authorization (M24) |
| cross-engine | `BLOCKED` | Missing independent G0 authorization and unprovisioned corpus/adapter/binary set (M24, M34) |
| retained-key control/treatment | `NOT_EXECUTED` | G0 absent; no readiness sampling was attempted |
| cross-engine control/treatment | `NOT_EXECUTED` | G0 absent |

## Retry policy

No attempt was made, therefore no retry or partial-evidence preservation question
arises. `official.acquisition.run_backend` refuses `--allow-contended`, refuses
non-interpreter programs, never cleans an existing path and never retries; a failed
attempt would be terminal for its run UUID.

---

# RF09-F1 addendum

| Rule | Trigger | Action |
| --- | --- | --- |
| D01 | HEAD `28a2952` and merge base `a5a8303` matched exactly | AUTO-RESOLVE: proceeded on the same branch |
| D06 | All seven findings reproduced at source level | AUTO-RESOLVE: wrote red-first tests before production edits |
| D08 | Existing tests expected fake production acceptance (fixture coordinator, caller PASS rows) | AUTO-RESOLVE: retargeted to fixture-only outcomes plus production-rejection assertions; no coverage removed |
| D09/D10 | No independent G0 approval source/record exists | DEFER AND CONTINUE: all production entry points fail closed; the approval-record format is closed and validated but no production record was created |
| D14/D16 | Bare freeze / fixture capability offered to production | AUTO-RESOLVE: rejected before any effect |
| D29/D30 | No authentic historical archive or approved mapping | DEFER AND CONTINUE: parity stays BLOCKED; the comparator and approval reader are implemented and tested in a sandbox |
| D38/D39/D40 | PR15D factory wrote to `raw_root`; no exclusivity check | AUTO-RESOLVE: `raw_root/backend`, existing/symlinked backend refused |
| D42 | PR15D corpus/adapter set still absent | DEFER AND CONTINUE: no real cross-engine timing |
| D53 | Six generated egg-info files tracked | AUTO-RESOLVE: `git rm --cached` on exactly those six; ignore rule added |
| D57/D58 | New `official/authorization.py` inside the rostered directory | AUTO-RESOLVE: one re-freeze, stability re-checked |
| D61/D63 | `test_pr15d.py` T01 still fails identically on baseline; untouched-crate Rust flake | DEFER AND CONTINUE: classified PRE_EXISTING_DETERMINISTIC / FLAKY_UNTOUCHED with evidence, no waiver claimed |
| D67/D74 | T6 freeze absent; no authorization for measurement | DEFER AND CONTINUE: retained-key L3 BLOCKED; no timed command executed |
| D68 | `gh` API credentials invalid (401) | DEFER AND CONTINUE: branch pushed over SSH; final CI UNVERIFIED |

No real backend invocation occurred. `retained_key_invocations` is exercised only
through a sandboxed production-shaped authorization and the factory returns an
argv plan without executing it.
