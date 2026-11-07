# PR 15I-0 — independent review fixup

**Branch:** `dev/pr15i-0-qualified-baseline` (**continued**; no new PR series)
**Reviewed HEAD:** `c9b1d37532cd9655d266ab976d7ad405376414f2`
**Accepted post-15H-E base:** `19cc5207009abdc1496473443d850487f7739e92`
**Frozen measured source:** `48e7d3a0771f9ccd1cc0bf1d07eadac4b2b5f39f`
**Frozen protocol digest:** `af828096ca3d4581a8cda50b9401b3d23df92311487acaa79966a8a0e2e0e6f8`
**Document class:** corrective verifier/publication code, adversarial tests,
source-locked requalification of **existing unaltered** raw campaigns.

This fixup changes no production Rust, no codec, no frozen benchmark harness, no
benchmark threshold and no measured performance data. It is **not** approval of
the 15I-A/B/C design proposals, which remain `DESIGN_PROPOSAL_ONLY`.

## 1. Pre-implementation record (written before any code edit)

### 1.1 Source identity at the start of the fixup

| Item | Value |
|---|---|
| Repository root | the canonical checkout (`git rev-parse --show-toplevel`) |
| Branch | `dev/pr15i-0-qualified-baseline` |
| HEAD | `c9b1d37532cd9655d266ab976d7ad405376414f2` |
| `origin/main` | `19cc5207009abdc1496473443d850487f7739e92` (= merge base with HEAD) |
| Working tree | clean (`git status --porcelain=v1` empty) |
| `c9b1d37` ancestor of HEAD | yes |
| `19cc520` (BASE) ancestor of HEAD | yes |
| `48e7d3a` (measured source) ancestor of HEAD | yes |
| Protected diff `19cc520..HEAD` (`crates/`, `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`, `.github/workflows`, `benchmarks/pr15d|pr15e|pr15f`) | **empty (exit 0)** |
| `git diff --check` | exit 0 |

Original immutable artifacts recorded before any edit (`target/`, git-ignored):

| Artifact | SHA-256 |
|---|---|
| `target/pr15i-0/pr15d-current-01/seal.json` | `d41cb54fe11ea5aa22ecda75cee325a2b6a8382585b97674c4baecaeb2be7a28` |
| `target/pr15e/pr15i0-prepared-48e7d3a0-01/seal.json` | `eb98f5c16f6ec1c47a4d2bdff999031a81921494876a620dc6ef8c75168b5581` |
| `target/pr15f/pr15i0-run-48e7d3a0-04/seal.json` | `0c97d87cfeea63cd93b3abfc3cc2882c12f6b0f7e4b1c5b05cabd024c0b68d29` |
| `target/pr15i-0/mutation-01/seal.json` | `560d866f55f11030955051bc695987acf053211c0c089c5ddedcd68bd1fccb0f` |
| `target/pr15i-0/verification-08.json` | `406d2d0f39b585408641ef77e8dae26c744ee872940f266172b67e68765e6cc5` |
| `target/pr15i-0/qa/workspace-qa.json` | `44f52ae3f71876540113d333a24d75dfbf7b3b0466e0496d3a7be5d1859aa2e1` |

All four seals report `status=QUALIFIED`, `source_sha=48e7d3a…`,
`protocol_sha256=af828096…`, `corpus_manifest_sha256=69052c66…`.

### 1.2 Invariants and assigned tests

| ID | Invariant | Tests |
|---|---|---|
| `FI-01` | `I0-P11=PASS` implies every mandatory QA command ID appears exactly once with the required flag, `status=PASS`, `exit_code=0` | `FT-01`–`FT-10` |
| `FI-02` | Optional QA commands never substitute for mandatory ones; `--only` records cannot pass | `FT-04`, `FT-09`, `FT-10` |
| `FI-03` | Coverage PASS derives from the recorded coverage command output, ≥ 85 %, matching the record | `FT-07`, `FT-08` |
| `FI-04` | Published numbers derive only from the exact four campaigns the supplied verification qualified | `FT-11`–`FT-20` |
| `FI-05` | Every input seal rehashes, is `QUALIFIED`, bound to exact source/protocol/corpus, with a safe nonempty inventory | `FT-21`–`FT-28` |
| `FI-06` | Privacy PASS requires exactly the 12 mandatory report paths plus real content inspection | `FT-29`–`FT-35` |
| `FI-07` | Public summarizer writes only the fixed PR 15I-0 destinations | `FT-36`–`FT-42` |
| `FI-08` | Verification, source identity, report digests and QA evidence stay reproducibly bound without circular hashes | `FT-43`–`FT-47` |
| `FI-09` | Workload/corpus/production/test topology unchanged; local evidence not modified | `FT-48`–`FT-51` |
| `FI-10` | An incomplete/blocked qualification never presents `15I0_QUALIFIED_REVIEW_READY` or ratios as qualified | `FT-18`, `FT-32`, `FT-44` |
| `FI-11` | CI and independent review stay separate external states | `FT-52` |

### 1.3 Observed defects and exact source locations

| ID | Defect in the reviewed source | Concrete symbol |
|---|---|---|
| `RF-01` | QA gate accepts a record with only `fmt`+`test` plus a coverage number; no exact mandatory inventory, no exit-code/flag check, no coverage provenance, no code binding | `verify.py::check_qa` (~L1359) |
| `RF-02` | Publication takes independent campaign paths and trusts another verification's `qualified` bit | `summarize.py::run` (~L810) |
| `RF-03` | Privacy gate trusts the scan's own file inventory and `PASS` label | `verify.py::check_privacy` (~L1320), `summarize.py::scan_reports` (~L784) |
| `RF-04` | Arbitrary caller output destinations are accepted and replaced | `summarize.py::run` + `write_bytes` |
| `RF-05` | Final qualification accepts `status=PARTIAL` and a missing `protocol_sha256`; no corpus binding | `verify.py::verify_seal` (~L479) |

### 1.4 Counterexamples rehearsed before coding

| Counterexample | Required behavior |
|---|---|
| QA record omits `rustfs-acceptance` but every other command passes | `I0-P11=FAIL`; no qualified summary |
| `fmt` reports `status=PASS` with `exit_code=1` | `I0-P11=FAIL` |
| Verification qualified on PR 15D campaign A, summarizer given campaign B | reject before any output write (`RF02_INPUT_MISMATCH`) |
| Privacy scan lists 11 of 12 reports and says `PASS` | `I0-P10=FAIL` |
| Seal `status=PARTIAL` in a final qualification | `I0-P09=FAIL`; original seal preserved unchanged |

### 1.5 Source-level confirmation

- `QA_COMMANDS` currently holds exactly 19 entries, all `required=True`; the
  `qa_main` real-boundary sweep adds `ignored-integration-with-real-rustfs`
  (`required=True`) → **20 mandatory IDs**. No ID collides with the sweep ID.
  (`FX-07` satisfied; a collision would be `FX-08` HARD STOP.)
- `verify.py` already exposes `require_plain_path`, `prepare_inputs`,
  `verify_seal`, `load_protocol`, `require_regular_files`, `parse_coverage_percent`
  and `redact`; the fix reuses them instead of adding parallel machinery.
- `summarize.py::REPORT_SCAN_TARGETS` already lists the exact 12 mandatory
  reports, excluding `privacy-scan.json` itself.
- No source detail conflicts with the plan. No protected path needs to change.

## 2. Applied decision-matrix rules

| Rule | Observed | Action | Result |
|---|---|---|---|
| `FX-01` | branch, ancestry and clean tree as recorded above | continue on this branch, record full SHAs | done |
| `FX-05` | all edits land inside the file allowlist | commit `81ea42f` (tooling), docs commits after | done |
| `FX-06` | the reviewed positive QA test asserted PASS on a two-command record | replaced with the complete 20-command fixture; kept a dedicated two-command negative | done (`FT-01`, `FT-04`) |
| `FX-07` | `QA_COMMANDS` has 19 entries, all required, plus the required sweep | derive the 20-identifier mandatory set at runtime | done |
| `FX-09` | the historical QA record has no `fixup_code_sha256` | left untouched; fresh `workspace-qa-fixup-01.json` produced and selected via `--qa-record` | done |
| `FX-13` | all four sealed campaigns rehash with matching source/protocol/corpus | reused as-is; no benchmark re-run | done |
| `FX-15` | `PARTIAL` / digest-less seals must not qualify | strict status, protocol and corpus binding in `verify_seal` | done (`FT-22`–`FT-25`) |
| `FX-16` | the QA fingerprint changes when controller bytes change | full QA re-run into a new record after the final code commit | done |
| `FX-19` | a stale privacy scan alone can block the first verification | not needed: publication ran before the first successful verification's privacy gate was reused; the scan was regenerated and a fresh verification was taken | n/a (kept as the documented fallback) |
| `FX-26` | verification/QA output names are immutable | `verification-fixup-01.json` preserved after its `I0-P00` failure; requalified into `verification-fixup-02.json` | done |
| `FX-27` | strict provenance requires more fixture fields | upgraded the synthetic fixtures to model an accepted run; no production bypass added | done |
| `FX-31` | host idle, campaigns intact, no performance-code change | ran the full QA matrix and requalification autonomously; no PR 15D/15F measurement re-run | done |
| `FX-32` | hosted CI unavailable (`gh` credentials invalid, no PR) | recorded `HOSTED_CI_PENDING`, no CI claim | done |
| `FX-33` | no independent acceptance supplied | recorded `REVIEW_PENDING`, no self-approval | done |
| `FX-34` | `pr14_bench_remote` (run by the QA ignored sweep) writes `benchmarks/reports/pr14-p4-diagnostic.json`, an untracked generated report, which makes `I0-P00` fail on a dirty tree | classified environment/harness side effect of an existing repository test; artifact preserved under `target/pr15i-0/qa/generated-reports/`; re-verified into the next free destination | done (see §6.4) |

## 3. Defects and fixes

| ID | Fix | Enforcement points |
|---|---|---|
| `RF-01` | `check_qa` now derives the exact 20-identifier matrix from `QA_COMMANDS` + the required sweep, rejects missing/duplicate/unknown ids, requires the source `required` flag, `status=PASS` **and** integer `exit_code=0`, proves coverage from the recorded `stdout_full` (`TOTAL` ≥ 85 %, matching within 0.005) and rejects a record whose `fixup_code_sha256` does not match the current four controller/test files. `verification_main` accepts an optional `--qa-record` confined to `target/pr15i-0/qa/*.json`, and records `observations.qa_record{path,sha256}` on success. `qa_main` now emits `fixup_code_sha256` and `qa_source_head_sha` itself. | `check_qa`, `expected_qa_matrix`, `qa_code_fingerprint`, `resolve_qa_record`, `qa_main`, `verification_main` |
| `RF-02` | `validate_verified_publication_inputs` proves, before any derivation or write: protocol identity, verification schema/controller/qualified/status/source/protocol, the exact 13-gate set with `I0-P00`–`I0-P11` PASS and `I0-P12` PASS/NOT_MEASURED, the exact four `observations.inputs` labels with current manifest digests, `seal_sha256`, `observations.seals` digests and status, cross-checked corpus identity, full seal rehash, and the QA-record digest. | `validate_verified_publication_inputs`, `summarize.run` |
| `RF-03` | `FROZEN_PRIVACY_TARGETS` (12 paths) is an independent verifier oracle; `check_privacy` requires exactly that ordered inventory, empty `problems`, valid digests, and then re-reads every report and re-runs `PRIVACY_PATTERNS` on the current bytes. `scan_reports` treats a missing/nonregular/symlinked/non-UTF-8 report as a failure and never emits `PASS` for a subset. | `FROZEN_PRIVACY_TARGETS`, `check_privacy`, `scan_reports`, `run_scan_only` |
| `RF-04` | Five fixed destinations; each validated for exact canonical spelling (absolute or repo-relative), non-symlinked existing parent, existing regular file, and no nonregular stale `*.tmp`, before any write. Rendering happens in memory, then the five allowlisted files are replaced. A mid-write I/O error reports `PUBLICATION_PARTIAL`. | `validate_output_destinations`, `summarize.run` |
| `RF-05` | `verify_seal` requires `status=QUALIFIED`, an exact valid `protocol_sha256`, an exact valid `corpus_manifest_sha256` (now an explicit argument), a nonempty sorted unique safe inventory with nonnegative lengths and valid digests, a symlink-free tree, no unlisted file, and a full rehash. The corpus digest is taken from the cross-checked PR 15D/PR 15F comparison; if it is unavailable the gate fails closed. | `verify_seal`, `verification_main` |

## 4. Pre-fix demonstrations (recorded before the change)

| Defect | Demonstration | Observed before fix | Observed after fix |
|---|---|---|---|
| `RF-01` | synthetic QA record with only `fmt` + `test` and `coverage_percent=86.5` | `I0-P11 = PASS` | `I0-P11 = FAIL` (`QA record is missing 18 mandatory command(s)`) |
| `RF-05` | seal written with `status=PARTIAL` | accepted as evidence (`verify_seal` returned the seal) | `I0-P09 = FAIL`; the partial seal file is byte-identical afterwards |
| `RF-02` | verification approved campaigns A, summarizer given B | would publish | `SummaryError: RF02_INPUT_MISMATCH`, zero output writes |
| `RF-03` | scan listing 11 of 12 reports with `status=PASS` | would pass | `I0-P10 = FAIL` |
| `RF-04` | `--out-json /tmp/out.json` | would write | `SummaryError: RF04_OUTPUT_PATH`, zero output writes |

## 5. Test traceability (`FT-01` … `FT-52`)

Controller suites: **123 tests, all passing** (`test_verify.py` 66, `test_summarize.py` 46,
`test_run_mutation.py` 11 unchanged). 49 named `test_ft*` cases implement `FT-01`–`FT-47`.

| Invariant | Tests | Result |
|---|---|---|
| `FI-01` complete QA matrix | `FT-01`, `FT-02`, `FT-03`, `FT-04`, `FT-05`, `FT-06` | PASS |
| `FI-02` optional/partial cannot substitute | `FT-04`, `FT-09`, `FT-10`, `FT-10b` | PASS |
| `FI-03` coverage provenance | `FT-07`, `FT-08` | PASS |
| `FI-04` publication binding | `FT-11`–`FT-20`, `FT-44`, `FT-46`, plus the derive/write-not-reached test | PASS |
| `FI-05` seal qualification | `FT-21`–`FT-28` | PASS |
| `FI-06` privacy completeness | `FT-29`–`FT-35` (both modules) | PASS |
| `FI-07` output confinement | `FT-36`–`FT-42`, layout-refusal test | PASS |
| `FI-08` reproducible binding | `FT-43`, `FT-45`, `FT-47` | PASS |
| `FI-09` unchanged workload/evidence | `FT-48`–`FT-51` (below) | PASS |
| `FI-10` no unqualified publication | `FT-18`, `FT-32`, `FT-44` | PASS |
| `FI-11` external states | `FT-52` (§9) | PASS |

Real-evidence tests (not synthetic):

- `FT-48` — `git diff --exit-code 19cc520..HEAD -- crates/ Cargo.toml Cargo.lock rust-toolchain.toml .github/workflows benchmarks/pr15d benchmarks/pr15e benchmarks/pr15f` → exit 0.
- `FT-49` — the four original `seal.json` SHA-256 values are unchanged before and after the fixup (§6.3).
- `FT-50` — the published 100K sentinels are identical to the original publication (§7).
- `FT-51` — the 20-command QA record executed the real stable/MSRV workspace, coverage and pinned-RustFS topology (§6).

## 6. Executed evidence

### 6.1 Fixup tooling checkpoint

`FIXUP_TOOLING_SHA = 81ea42fa6a1fb625d81fecae8a5a3e3ef16d8ba2`
(`fix(pr15i-0): enforce complete QA, seal qualification, bound publication and confined outputs`),
containing exactly the five allowlisted tooling files.

### 6.2 Fresh complete QA

| Item | Value |
|---|---|
| Record | `target/pr15i-0/qa/workspace-qa-fixup-01.json` |
| SHA-256 | `16577dc1f327d5264830b222daa4978f701d3e194eb97378a0ef9387ba7b7209` |
| Commands | 20 unique, `missing=[]`, `unknown=[]` |
| Statuses | 20 × `PASS`, 20 × `exit_code=0`, `required` flags equal the source matrix |
| `rustfs_included` | `false` (the required real-RustFS work runs inside `rustfs-acceptance` and the ignored sweep, both mandatory) |
| Coverage | recorded `93.23 %`; parsed from the real `TOTAL` row = `93.23 %` (delta 0.000) |
| Code fingerprint | `6309dc5e1a2486fbaca3b82a609b2bbdad4fd43a009562f9f2b84d084144c765`, equal to `qa_code_fingerprint` of the committed sources |
| `qa_source_head_sha` | `81ea42fa6a1fb625d81fecae8a5a3e3ef16d8ba2` (audit only) |

Command set actually executed: `ignored-integration-with-real-rustfs` (66 real
ignored tests, 0 failed), `fmt`, `clippy`, `clippy-all-features`, `test`,
`test-all-features`, `doc`, `bench-no-run`, `fmt-msrv`, `clippy-msrv`, `test-msrv`,
`probe-test`, `probe-test-msrv`, `controller-tests`, `pr15d-tests`, `pr15f-tests`,
`pr15e-tests`, `diff-check`, `rustfs-acceptance` (pinned
`rustfs/rustfs@sha256:1803faef…b6a3c` in a disposable container), `coverage`.

### 6.3 Requalification of the original campaigns

| Artifact | SHA-256 (before = after) |
|---|---|
| `pr15d-current-01/seal.json` | `d41cb54fe11ea5aa22ecda75cee325a2b6a8382585b97674c4baecaeb2be7a28` |
| `pr15i0-prepared-48e7d3a0-01/seal.json` | `eb98f5c16f6ec1c47a4d2bdff999031a81921494876a620dc6ef8c75168b5581` |
| `pr15i0-run-48e7d3a0-04/seal.json` | `0c97d87cfeea63cd93b3abfc3cc2882c12f6b0f7e4b1c5b05cabd024c0b68d29` |
| `mutation-01/seal.json` | `560d866f55f11030955051bc695987acf053211c0c089c5ddedcd68bd1fccb0f` |

No benchmark campaign was re-run: PR 15D trials, PR 15F captures and the sidecar
probe output are the original sealed bytes.

### 6.4 Verification records

| Artifact | SHA-256 | Gates | Status |
|---|---|---|---|
| `target/pr15i-0/verification-fixup-01.json` | `0d62312bde7050e82afbeeb17766c1a3495695b7cc42661dfa3352571b9b379e` | `I0-P00 = FAIL`, all others PASS | preserved evidence (`FX-26`) |
| `target/pr15i-0/verification-fixup-02.json` | `a4ca3fceb40bd12487429e554c91942cc84342a53d7279e3c7b496bb91ecc796` | `I0-P00`–`I0-P12` all `PASS` | `15I0_QUALIFIED_REVIEW_READY`, `qualified=true` |

`verification-fixup-01` failed only because the QA ignored sweep runs the
existing `pr14_bench_remote` test, which writes the untracked generated report
`benchmarks/reports/pr14-p4-diagnostic.json`; `I0-P00` correctly refused a dirty
tree. The generated artifact was preserved as
`target/pr15i-0/qa/generated-reports/pr14-p4-diagnostic-fixup-qa01.json`, the
tree was re-checked clean, and the identical command was re-run into the next
free destination. No gate was weakened and no evidence was edited.

### 6.5 Publication

| Output | SHA-256 before fixup | SHA-256 after fixup |
|---|---|---|
| `benchmarks/reports/pr15i-0/pr15i-0-summary.json` | `6412110b5657e7bae5e9eddef8e1cdfa83874011512c014eb0199b4ffb86a8af` | `5000021fb7aeb3601bd4febd5c333f230c6c48d43e68c51e5451dab2614376c4` (adds the `binding` block only) |
| `docs/pr-artifacts/pr-15i-0/measurements.md` | `25982aefac8f5ce5db16701076b84117bb8944168070b3f64322f9337ccab09f` | identical |
| `benchmarks/reports/pr15i-0/pr15i-0-summary.md` | `2a25a1473377d0f6df956a0a178f31ef30a06f7872fcbb0d8f5257141de68f04` | identical |
| `benchmarks/reports/pr15i-0/historical-context.json` | `c8ee433a6c08ddf2f314885b9f525daad05cfdc3425da21b6d37e9358226d0d8` | identical |
| `benchmarks/reports/pr15i-0/privacy-scan.json` | `82f03734…` | regenerated after publication (`PASS`, 12 files, problems `[]`) |

Numeric reconciliation sentinels from the same campaigns: 100K committed index
`30,965,025`; 100K mutation sidecar `9,600,180`; repeated segment-ID bytes
`6,600,000`; Tantivy 100K index `2,901,172`; 16 process-cold ratios still
`NOT_COMPARABLE`; every warm lane still carries
`PHYSICAL_SORT_ENCODING_DIFFERS`. No numeric drift (`FX-30` not triggered).

## 7. Self-review answers (Stage F6)

| Question | Answer | Evidence |
|---|---|---|
| Can `I0-P11` pass with 19/20 ids, a duplicate, a forged exit code or fabricated coverage? | **No** | `FT-02`, `FT-03`, `FT-04`, `FT-05`, `FT-08` |
| Can a verification for one campaign publish numbers from another directory? | **No** | `FT-12`, `FT-13`, `FT-14`, `FT-15` |
| Can a `PARTIAL` seal, absent protocol, wrong corpus hash or changed raw evidence pass? | **No** | `FT-22`–`FT-27`, `FT-46` |
| Can the privacy gate pass with 11/12 files, a stale hash or a leaking report? | **No** | `FT-29`–`FT-34` |
| Can `summarize.py` overwrite an arbitrary or historical PR file? | **No** | `FT-37`, `FT-38`, `FT-39`, `FT-41`, `FT-42` |
| Are all four sealed campaign file sets and hashes unchanged? | **Yes** | §6.3 |
| Does the final report avoid claiming fresh CPU attribution or improvements? | **Yes** | `final-report.md` §4–§6, §10 |
| Are CI, approval and merge statuses accurate? | **Yes** | `HOSTED_CI_PENDING`, `REVIEW_PENDING`, `NOT_MERGED` |

## 8. Failure classification

No mandatory failure remained at the end of the fixup. Two transient events were
classified and resolved without weakening a gate:

| Event | Category | Evidence | Disposition |
|---|---|---|---|
| `check_qa`/`verify_seal`/privacy/publication defects found by review | **feature implementation defect** | §3, §4 | fixed, covered by `FT-01`–`FT-47` |
| `verification-fixup-01` `I0-P00` dirty tree caused by the existing `pr14_bench_remote` report writer | **environment/harness** (deterministic side effect of an unchanged repository test) | §6.4 | artifact preserved, tree re-checked clean, identical command re-run into a new destination |

## 9. Status

```text
15I0_FIXUP_QUALIFIED_REVIEW_READY   (F0–F7 pass; see final-report.md for the final artifact)
HOSTED_CI_PENDING
INDEPENDENT_REVIEW_PENDING
NOT_MERGED
```

This fixup does **not** approve or implement 15I-A/B/C. Those documents remain
`DESIGN_PROPOSAL_ONLY`.

