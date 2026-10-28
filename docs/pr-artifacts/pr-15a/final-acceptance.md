# PR 15A — execution status and acceptance handoff

**Status: `IN PROGRESS — LOCAL AND PROVIDER GATES PASS; CI AND INDEPENDENT
REVIEW PENDING`. This document does NOT mark PR 15A DONE and does NOT authorize
merge, v0.1 release or a tag.**

## 1. Final report table

| Item | Value |
|---|---|
| Baseline branch / SHA | `main` / `80a38643878681b2ae53f90c281b52f6aa4bd9a1` |
| PR branch | `test/pr15a-regression-compatibility` |
| Implementation head validated | `f8392db` (`test(pr15a): add fake and real RustFS v1 vertical`) |
| Evidence-only head | this commit (docs only; no executable/test/manifest change) |
| Changed files | 9 files, +3018 lines before this evidence commit; all additive |
| Production source changes | **none** (`crates/**/src/**` untouched) |
| Public API/format/manifest/cursor/segment changes | **none** |
| Dependency/lockfile changes | **none** |
| Phase P0 | **PASS** — preflight, baseline 69 tests, adversarial matrix |
| Phase P1 | **PASS** — frozen `pr15a_v1` fixture/oracle, A-T00 |
| Phase P2 | **PASS** — 14 local regression tests |
| Phase P3 | **PASS** — 3 compatibility tests + inherited golden/durability suites |
| Phase P4 | **PASS** — new fake/real vertical + all mandatory existing RustFS suites |
| Phase P5 | **PASS (LOCAL)** — all mandatory local gates; CI deferred |

## 2. Changed files

```
benchmarks/datasets/pr15a_v1.json                 new
benchmarks/datasets/pr15a_v1.md                   new
crates/quervant-core/tests/pr15a_common/mod.rs    new (test-only)
crates/quervant-core/tests/pr15a_regression.rs    new (test-only)
crates/quervant-core/tests/pr15a_compatibility.rs new (test-only)
crates/quervant-core/tests/pr15a_provider.rs      new (test-only)
docs/pr-artifacts/pr-15a/preflight.md             new
docs/pr-artifacts/pr-15a/compatibility.md         new
docs/pr-artifacts/pr-15a/provider-validation.md   new
docs/pr-artifacts/pr-15a/local-validation.md      new
docs/pr-artifacts/pr-15a/test-traceability.md     new
docs/pr-artifacts/pr-15a/final-acceptance.md      new
```

No existing test was deleted or changed from `#[ignore]` to skip execution.

## 3. Fixture freeze

| Item | Value |
|---|---|
| Version | `pr15a_v1` |
| Canonical file | `benchmarks/datasets/pr15a_v1.json` |
| SHA-256 | `104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087` |
| Git blob | `90828bbd1bc3f4a4b0a0bb59029fe93bb64cd2f9` |
| Size | 2408 bytes |
| Oracle | static Rust record table; literal hardcoded predicate sets |
| Downstream | PR 15B/15D/15E may reuse only as untimed correctness inputs |

## 4. A-I disposition summary

| ID | Source of expected values | State |
|---|---|---|
| A-I01 | frozen title/n table | **PASS (EXECUTED)** |
| A-I02 | static CIDR/timestamp/JSON state table | **PASS (EXECUTED)** |
| A-I03 | independent host tally + canonical tie rule | **PASS (EXECUTED)** |
| A-I04 | static `n` order + PR 14A typed negatives | **PASS (EXECUTED)** |
| A-I05 | frozen generation-3 table + M5 oracle | **PASS (EXECUTED)** |
| A-I06 | frozen old/new key/host table | **PASS (EXECUTED)** |
| A-I07 | frozen fixture digests + typed errors | **PASS (EXECUTED)** |
| A-I08 | same static oracle local/fake/real + GET counters | **PASS (EXECUTED)** |
| A-I09 | typed cancellation/budget/fault outcomes | **PASS (EXECUTED)** |
| A-I10 | command/SHA/count records in this dossier | **PASS (EXECUTED; CI PENDING)** |
| A-I11 | additive diff audit, no forbidden path | **PASS (EXECUTED; exact-head CI PENDING)** |

Row-level mapping is in `test-traceability.md`.

## 5. Test matrix summary

| Gate | Passed | Failed | Ignored | Evidence |
|---|---|---|---|---|
| Workspace stable default | 2072 | 0 | 10 | `local-validation.md` |
| Workspace stable all-features | 2076 | 0 | 75 | `local-validation.md` |
| Workspace MSRV default | 2072 | 0 | 10 | `local-validation.md` |
| Workspace MSRV all-features | 2076 | 0 | 75 | `local-validation.md` |
| New `pr15a_regression` | 14 | 0 | 0 | `local-validation.md` |
| New `pr15a_compatibility` | 3 | 0 | 0 | `compatibility.md` |
| New `pr15a_provider` fake | 1 | 0 | 0 | `provider-validation.md` |
| New `pr15a_provider` real | 1 | 0 | 0 | `provider-validation.md` |
| PR 14 real vertical | 13 | 0 | 0 | `provider-validation.md` |
| PR 14 real faults | 9 | 0 | 0 | `provider-validation.md` |
| PR 14G real zero GET | 1 | 0 | 0 | `provider-validation.md` |
| PR 13 proxy/crash/remote/oracles | 17 | 0 | 0 | `provider-validation.md` |

Ignored entries are generator/child/provider prerequisites; they are not
counted as passes.

## 6. Coverage and environment

| Item | Value |
|---|---|
| Coverage command | `cargo +stable llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` |
| Line coverage | **91.38 %** |
| Region / function | 91.94 % / 87.41 % |
| Floor | 85 % (unchanged) |
| Exclusions added | none |
| Stable / MSRV | 1.98.1 / 1.85.0 |
| RustFS | pinned `sha256:1803faef…6a3c`, version `1.0.1`, health `ok`, loopback `127.0.0.1:9000` |
| Test filesystem | native Linux WSL2 filesystem, not `/mnt/c` |

## 7. X-rules exercised

| Rule | Observation | Action |
|---|---|---|
| X02 | Existing PR 14A/M5 negatives exactly cover cursor/mutation/budget rows | Reused and rerun |
| X07/X35 | Authored `NOT alpha` and IPv4 `/0` expectations were arithmetically wrong | Corrected documented derivation; engine matched corrected oracle |
| X08 | Historical fixtures have valid frozen digests | Reused unchanged |
| X14 | Native Linux test filesystem | No relocation needed |
| X19 | 8-row pagination witnesses sufficient | Omitted 32-row extension |
| X22 | MSRV 1.85 present | Ran MSRV gates |
| X28 | No benchmark timing in 15A | `cargo bench --no-run` |
| X36 | Internal ignored child entrypoints | Parent harnesses only |
| X40 | Evidence-only docs after validated implementation head | Reuse executable evidence; final exact-head CI still required |

No X01/X03/X05/X06/X09/X13/X15/X17/X21/X25/X31/X32/X33/X34/X38/X39/X99
condition was observed.

## 8. Remaining blockers and required external gates

| Item | State | Owner / action |
|---|---|---|
| GitHub PR creation / push | **DEFER (ENV)** — no push/PR performed from this environment (X26) | Maintainer/agent with connected access pushes branch and opens PR |
| Exact-head CI `rust`/`msrv`/`rustfs` | **NOT RUN** — no PR head exists | Re-run on final PR SHA; this document makes no CI PASS claim |
| Independent source/evidence review | **NOT STARTED** | Independent reviewer |
| Maintainer acceptance / merge | **NOT STARTED** | Maintainer |
| v0.1 release/tag | **NOT AUTHORIZED / NOT RELEASED** | Separate maintainer authorization |

No mandatory local or real-provider gate is BLOCKED. The only open gates are
external PR/CI/review actions that this environment cannot perform.

## 9. Explicit non-claims

- PR 15A is **not DONE**.
- No merge, release or tag is authorized.
- No performance, throughput, scale or competitor-superiority claim is made.
- No skipped/ignored test is reported as PASS.
- No historical green check is substituted for fresh PR 15A execution.
