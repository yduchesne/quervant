# BM-07 verification report

## 1. Exact state

| Item | Observed |
|---|---|
| Repository | `yduchesne/quervant` |
| Branch | `dev/pr-bm07` |
| Main base | `b6de92d0fb6cc6ac9b9fe718bc3f6a1ebe909c60` (merge of PR #107) |
| BM-06 reviewed ancestor | `314cafdbcdd78774a037de609d47b8427b0717db` — verified ancestor |
| Start head | `b6de92d0fb6cc6ac9b9fe718bc3f6a1ebe909c60` |
| Final implementation commit | `7364ec6a9872ff376ad35171a479bcd110761fdf` |
| Working tree | clean after commit |
| Python | 3.12.3 |
| Local PyYAML / jsonschema | 6.0.1 / 4.10.3 (CI installs pinned 6.0.3 / 4.26.0) |
| Rust stable | 1.98.1 |
| Rust MSRV | 1.85.0 |

## 2. Re-frozen trust chain

The controlled §10 re-freeze was performed once after all Python source and tests
were final. Only the source-set fields of the synthetic QA records, the per-check
evidence digests, the two parent QA documents and the three anchor fields were
updated. QA status/rosters/toolchains and the qualification profile were not
changed.

| Field | Value |
|---|---|
| Old source-set digest | `sha256:d8f782f3db1cacbc22deead7717e984027ca1039795bd22b42471c9a94b15da4` |
| New source-set digest | `sha256:a8af53867f04bca986f1f64d076ec2e037d36e4160145432fdea305d93deee97` |
| Profile digest (unchanged) | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` |
| Old framework QA anchor | `sha256:de486da134604edf53746375af66d2f1a22efff0c940c4238e4b5deeb8cc646e` |
| New framework QA anchor | `sha256:7ce79d12e53e1857fa034f7e1e886cb943f1e7a234c155091ae3a5e06b9c71ea` |
| Old source QA anchor | `sha256:e86ef1a692915a0ce9208f812774d1d8f9ff7fc3251c42a058f44d314806151a` |
| New source QA anchor | `sha256:ba4d7bcb98d1d7d10e661304c09860f30a2a26f2c8dff9f7a89118d207350f39` |
| Source roster entries | 124 |

The new `benchmarks/quervant_bench/migrations` package is in
`qualification/identity.py::SOURCE_DIRECTORIES`. `ANC-03` proves all four
migration modules are hashed and that an untracked or symlinked migration `.py`
fails closed. `F06-A-01`/`F06-A-02` and `SRC-01`…`SRC-03` pass against the new
anchors.

## 3. Catalog digests

| Catalog file | `content_digest` |
|---|---|
| `experiment.yaml` | `sha256:8b989e2f87d92a6d50b8d8d9c650972a1bb564cc61c51b68093780e0b11805d0` |
| `protocol.yaml` | `sha256:9a8220c78acca958de62671f1d11e238909ef32cefb319f3d9ba6a21353bc8fa` |
| `workloads.yaml` | `sha256:2166cab9989af7aed42345c0c6605bdc01688a5882d3a037498482af913bfdb1` |
| `adapter.yaml` | `sha256:86be09baceb25fd9673cef3499cb50c29210e10f351e9c50febb99e7e01fd1e2` |
| `analysis-profile.v1.json` | `sha256:96d797f3d35442f91e3dd0642e6db1d4c5e7303b753bfe51846953812394ab3f` |
| `policy-profile.v1.json` | `sha256:8c9eb85aa23cbb4844537835e55780054326d94537082c6194fb4f3e33821414` |
| `resource-observations.v1.json` | `sha256:818c58a17999f20f702aefc1b2469e21c07a99b603211e89c804645de4e777a0` |
| `synthetic-scenario.v1.json` | `sha256:508be513674ef11035c08c6b29f8155fe42e4f8372e4bf86f29ffb12b57be89d` |

The policy and analysis digests are bound in both `experiment.yaml` and
`protocol.yaml`; the workload digest is bound in `protocol.yaml`.

## 4. Executed local checks

| Command | Result | Evidence |
|---|---|---|
| `python -m compileall -q benchmarks/quervant_bench` | PASS | package and new modules compile |
| `PYTHONPATH=benchmarks python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_retained_key_*.py' -v` | PASS | 46 tests |
| `... -p 'test_qualification_*.py' -v` | PASS | 109 tests |
| `... -p 'test_verification_*.py' -v` | PASS | 111 tests |
| `... -p 'test_analysis_*.py' -v` | PASS | 190 tests |
| `... -p 'test_*.py' -v` | PASS | 818 tests, 1 established skip |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS | exit 0 |
| `bash benchmarks/scripts/test-scripts.sh` | PASS | 108 passed, 0 failed |
| `cargo fmt --all -- --check` | PASS | stable 1.98.1 |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS | stable |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS | stable |
| `cargo test --workspace --all-targets` | PASS | stable; RustFS tests ignored by design |
| `cargo test --workspace --all-targets --all-features` | PASS | stable; RustFS tests ignored by design |
| `cargo +1.85.0 fmt --all -- --check` | PASS | MSRV |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | MSRV, separate `CARGO_TARGET_DIR` |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS | MSRV; RustFS tests ignored by design |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS | **92.70%** line coverage (99571 lines, 7266 missed) |
| `cargo doc --workspace --all-features --no-deps` | PASS | documentation builds |
| `cargo bench --workspace --no-run` | PASS | compile-only; no executable benchmark was run |
| `git diff --check` | PASS | no whitespace errors |
| `quervant-bench run` negative path | PASS | exit 77, empty stdout, `BM_ACQUISITION_PROHIBITED` |
| Non-offline reserved verbs | PASS | exit 69, `BM_NOT_IMPLEMENTED`, no workspace access |
| Offline five verbs | PASS | canonical stdout, empty stderr, exact stage/view shapes |
| Offline read-only probes | PASS | workspace byte snapshot unchanged; producer/publication patched to raise |
| Forged/stale bundle, QA, anchor and coherent rehash | PASS | typed rejection with empty stdout |
| Real timed acquisition | **NOT RUN** | prohibited before BM-09 |
| Real RustFS service | **NOT RUN locally** | CI-owned `rustfs` job; local environment has no RustFS service |
| Push | PASS | `origin/dev/pr-bm07` updated |
| Pull request creation | **BLOCKED** | `gh` token is invalid and no `GH_TOKEN`/`GITHUB_TOKEN` is set |
| Final-head GitHub Actions | **UNVERIFIED / BLOCKED** | workflow runs on `pull_request` or push to `main`; no PR exists and the pushed branch is not `main` |

## 5. Synthetic result

- BM-03 sealed run: 1 control campaign, 2 treatment campaigns, 72 slots,
  576 lane envelopes, 1,728 samples.
- BM-04 per-lane effects: `0.940000000000`, `0.790000000000`,
  `0.815000000000` for linear, prefilter, exact-set; CIs collapse to the same
  values.
- BM-04 policy: `SELECTED_ELIGIBLE_SYNTHETIC`, selected `prefilter`, ranking
  `prefilter`, `exact-set`, `linear`; remains synthetic/simulated.
- BM-05: all nine frozen `VC-01`…`VC-09` checks pass; forged analysis and policy
  are rejected.
- BM-06: `SIMULATED_QUALIFIED`, exact 15-file bundle, seven receipt gates,
  post-publication revalidation; `REUSED_VERIFIED` without re-running BM-04/05.
- Offline CLI: `validate`, `analyze`, `verify`, `accept`, `report` all return the
  specified source-bound documents/views.

## 6. Historical status

```text
HISTORICAL_ARCHIVE=EVIDENCE_UNAVAILABLE
HISTORICAL_PROTOCOL_PARITY=SEMANTIC (scope/provenance only)
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE=BLOCKED
LEGACY_PATHS_RETIRED=NO
```

`target/pr15i-d3-c` is an empty stub. The checked-in frozen D3-C protocol digest
matches its pinned literal. `PAR-01`…`PAR-05` pass: the ledger is closed,
H01–H08 classifications match, missing/empty archives are `EVIDENCE_UNAVAILABLE`,
a synthetic stand-in cannot authenticate, and the literal
`median4([1,2,100,200]) = 2` versus `statistics.median = 51` counterexample is
recorded. H04/H05 are `NON_EQUIVALENT_CONTRACT`; no tolerance is invented.
`LEG-01`/`LEG-02` prove the historical source bytes are unchanged before and after
the read-only assessor.

## 7. Failure classifications and residual risks

No local failure remains. Unresolved external gates are classified as:

| Item | Classification | Owner / status |
|---|---|---|
| Real RustFS integration | 5 — environment/harness | CI `rustfs` job; local service absent |
| Final-head GitHub CI | 5 — environment/harness | Repository/CI owner; PR/CI blocked by invalid `gh` token |
| Historical numeric/decision parity | Not a defect: `EVIDENCE_UNAVAILABLE` + `NON_EQUIVALENT_CONTRACT` | Architecture/research owner; BLOCKED |

Residual risks remain exactly as planned:

1. Simulated values are not Quervant performance.
2. The QA fixtures are simulated L2 assertions, not CI attestations.
3. Workspace anchors are operator-provisioned local trust, not signatures.
4. BM-06/offline do not provide an atomic multi-root input snapshot.
5. The offline CLI only revalidates and displays committed outputs.
6. Historical numeric/policy parity is not inherent and the archive is missing.
7. Only native Linux/WSL2 no-follow topology is supported.
8. BM-09 still owns real full-scale qualification.

## 8. Push, pull request and CI

- Branch pushed: `origin/dev/pr-bm07`.
- Pull request: **NOT CREATED**. `gh auth status` reports an invalid token; no
  `GH_TOKEN` or `GITHUB_TOKEN` is available. This is `D51 DEFER AND CONTINUE`, not
  a waiver of CI.
- GitHub Actions: **UNVERIFIED / BLOCKED**. The workflow runs on `pull_request`
  or pushes to `main`; pushing `dev/pr-bm07` alone does not create a run, and no
  pull request could be opened. No CI conclusion is claimed.
- Final remote head: the amended report commit on `origin/dev/pr-bm07` (recorded
  in the terminal agent report). The implementation commit is
  `7364ec6a9872ff376ad35171a479bcd110761fdf`.

## 9. RF07 independent-review fixup (append-only)

This section records the follow-up review fixup. Sections 1–8 above are preserved
as the original BM-07 evidence.

| Item | Observed |
|---|---|
| Review ID | `5928282125` |
| Fixup plan | `BM07-RF07-F1` |
| Reviewed start head | `5a86da517ede00a499b9986e0acc451da360e64c` |
| Merge base with `main` | `b6de92d0fb6cc6ac9b9fe718bc3f6a1ebe909c60` |
| PR | #108, created externally after section 8 |
| Change scope | `migrations/historical_retained_key.py` + historical tests/fixtures/docs |

### 9.1 Defects fixed

- **RF07-01:** header-only three-campaign metadata previously returned
  `AUTHENTIC` with no seal, raw slots, build/host evidence or original verifier
  run. It now returns `PRESENT_UNVERIFIED`; BM-07 never returns `AUTHENTIC`.
- **RF07-02:** malformed but present JSON previously mapped to
  `EVIDENCE_UNAVAILABLE`. It now maps to `FAILED_AUTHENTICATION`; actual absence
  remains `EVIDENCE_UNAVAILABLE`.

### 9.2 Red-first evidence

Twenty-one HF07 tests were written before the production edit and executed against
`5a86da5`. The red run produced 25 failures across 13 tests. Reproduced examples:

```text
HF07-01: AUTHENTIC != PRESENT_UNVERIFIED
HF07-02: AUTHENTIC != FAILED_AUTHENTICATION
HF07-06: EVIDENCE_UNAVAILABLE != FAILED_AUTHENTICATION
HF07-19: EVIDENCE_UNAVAILABLE != FAILED_AUTHENTICATION
HF07-20: AUTHENTIC != FAILED_AUTHENTICATION
HF07-21: missing ARCHIVE_PRESENT_UNVERIFIED export
```

### 9.3 Green results

The full historical module now runs 28 tests, all passing. HF07-01…21 cover the
full state table, including mixed malformed+missing precedence, unsafe
links/sizes, no subprocess execution, source/QA chain integrity and public API
compatibility. The full Python suite runs **839 tests, 1 established skip, PASS**.
Rust stable/MSRV, 92.70% line coverage, documentation and compile-only benchmark
checks also pass.

### 9.4 Follow-up synthetic re-freeze

| Field | Value |
|---|---|
| Previous source-set digest | `sha256:a8af53867f04bca986f1f64d076ec2e037d36e4160145432fdea305d93deee97` |
| Final source-set digest | `sha256:2b0ee6ab1eb990b4fdc1d574772145e1492497680d53c273e0c753083826fe84` |
| Profile digest (unchanged) | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` |
| Previous framework QA | `sha256:7ce79d12e53e1857fa034f7e1e886cb943f1e7a234c155091ae3a5e06b9c71ea` |
| Final framework QA | `sha256:d38171fd5192328ddf51d5afcccb9b32f060676008e073e6e8c3b2d34ca4f9b3` |
| Previous source QA | `sha256:ba4d7bcb98d1d7d10e661304c09860f30a2a26f2c8dff9f7a89118d207350f39` |
| Final source QA | `sha256:23d0df650038ee0279ad4218618559133fd50eed171326508dd535082c2a0ebc` |

`F06-A-01/02`, `SRC-01…03`, `ANC-03`, `HF07-17/18` pass against the final chain.
`QA_FIXTURES=SIMULATED_ONLY`.

### 9.5 Final historical status

```text
HISTORICAL_ARCHIVE=EVIDENCE_UNAVAILABLE
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE=BLOCKED
LEGACY_PATHS_RETIRED=NO
```

Header-compatible future metadata remains `PRESENT_UNVERIFIED` and cannot promote
parity. Full historical authentication/parity still requires a separately approved
verification milestone.

### 9.6 CI status

PR #108 exists. The reviewed starting head passed its own run
(`43962121035`, success). The fixup implementation head
`9c2bf409504f41df5af8f45db85a79d116d6ddf6` passed all four required jobs in
[run `43970644323`](https://github.com/yduchesne/quervant/actions/runs/43970644323):

```text
python-contracts  success
rust              success
msrv              success
rustfs            success
```

A subsequent docs-only commit changes no source, test or QA-fixture bytes; its
own final-head run is reported separately in the terminal agent report.

## 10. RF07-F2 closeout (append-only)

The intra-campaign sibling-inspection defect is fixed on the same branch.

| Item | Observed |
|---|---|
| Fixup plan | `BM07-RF07-F2` |
| Authorized start head | `f3acd3b76c02f590ba7d0d7f87d13fca72647345` |
| Red gate | 11 failures in `HF07-22…34` new class on old head |
| Green gate | 41 historical tests; 80 retained-key; 852 full Python |
| Production delta | `_audit_campaign` only |
| Final source-set digest | `sha256:28170ada72d89f00277543a7e2b73def9367bc6a24dcb82ad0be31ebf560a659` |
| Final framework QA | `sha256:0e8408ebee8e54fe5465bc79610a07d5fd71b5f57ba584bded09b651637310e3` |
| Final source QA | `sha256:e1abe182ab046edf3cfc254932927a29346b75616919441fadaf89fe8a94f31a` |
| Profile digest | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` (unchanged) |
| Rust local gates | PASS; 92.70% line coverage |
| Historical parity | `NOT_EXECUTED`; acceptance `BLOCKED`; legacy retirement `NO` |

The final RF07-F2 source/QA fixture chain is recorded in
[review-fixup-evidence.md](review-fixup-evidence.md). Final-head hosted CI is
required on the pushed fixup SHA; prior-head success is not a substitute.
