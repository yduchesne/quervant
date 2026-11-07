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
| `FX-31` | host idle, existing campaigns intact, no performance-code change | run full QA + requalification autonomously, no new PR 15D/15F measurement | in progress |

Remaining rules are appended as they are exercised (see §8).
