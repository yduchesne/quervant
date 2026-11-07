# PR 15I-A — independent review fixup

**Status:** `15IA_FIXUP_QUALIFIED_REVIEW_READY`
(`HOSTED_CI_PENDING`, `INDEPENDENT_REVIEW_PENDING`, `NOT_PUSHED`, `NOT_MERGED`)

Continuation of PR #89 on `dev/pr15i-a-mutation`. This fixup changes **no**
production Rust, on-disk format, frozen protocol/corpus, benchmark thresholds,
schedules, adapters or sealed measurements.

## 1. Observed defects

| ID | Defect | Fix |
|---|---|---|
| RF-A01 | `verify.py::_reconstruct_arm` fabricated `oracles_ok=True` / `feature_checks_ok=True`, so `A-P10`/`A-P11` could pass on unverified input | Removed the defaults. `_validate_sizes_and_features` and `_validate_slot_lanes` now establish those proofs; `_reconstruct_arm` receives `"PASS"` only from the successful validators |
| RF-A02 | `run.py::derive` sets `A-P12=PASS` unconditionally; verification merely reproduced that constant | Added `_source_proof`, `_validate_authorization`, `_validate_binaries`, `_validate_blocks`, corpus/protocol checks and a `provenance_proof` receipt predicate that must pass before gates are re-derived and compared |
| Support-1 | `_rehash` accepted any nonempty seal map and checked traversal after reading | Exact 20-key inventory, canonical relative paths, no symlink components, regular files only, strict raw-tree enumeration, hash-before-consume |
| Support-2 | 32 unsealed auxiliary contention probes were not reconciled | Each `slots/slot-NN/contention/trialN-{before,after}.json` must equal its sealed slot copy byte-for-byte |
| Support-3 | Legacy `run.py --verify-only` printed a qualification-sounding `VERIFIED` | CLI route now exits `4` with `A_USE_INDEPENDENT_VERIFIER`; it never prints `VERIFIED` |
| Support-4 | Published results could be treated as truth | Published/sanitized outputs are compared to raw evidence only after raw requalification |

## 2. Identities

| Item | Value |
|---|---|
| Branch | `dev/pr15i-a-mutation` (no upstream; `NOT_PUSHED`) |
| Pre-fix HEAD (reviewed) | `cfc550f27b15e86065700d7325dcca0cb8ca62c5` |
| Measured candidate B | `db9007fb7239a5cce94e20c7c43ac7200da8047f` |
| Accepted baseline A | `888e819d85f0cde62a5040919ac5c96feca52f1f` |
| Fixup tooling commit | `c46f3d479c62b4ed7c80f1bef4812ccd670f9ca3` |
| Independent receipt | `target/pr15i-a/reviews/verification-fixup-01.json` (ignored, exclusive create) |

`git diff db9007f..c46f3d4 -- crates/quervant-core/src crates/quervant-core/Cargo.toml Cargo.lock .github/workflows/ci.yml` is empty.

## 3. Pre-fix evidence (preserved)

- Old unit tests: `python3 -m unittest discover -s benchmarks/pr15i_a -p 'test_*.py' -v` → 28 passed.
- Old verifier: `PR15I_A_VERIFY decision=A_CANDIDATE_ACCEPTED_PENDING_QA VERIFIED files=20`, exit 0 — a shallow seal/summary comparison, not independent qualification.
- Original seal SHA-256: `af7f6c1a85515dbc58c8c31a3b1b7f68dd6a9246d33747a529952b941b852b2f` (unchanged after every fixup run).
- Published hashes before the fixup:
  `results.json 31aeef7e…b35d689`, `results.md dc9ae753…7ebbd3`,
  `decision.json d7983d0c…e7c734`, `README.md 827c646c…1b4cc3`.

## 4. Read-only inventory (paired-04)

- `raw/` contains exactly the 20 sealed primaries, `seal.json`, and 32 auxiliary contention probes (`slots/slot-NN/contention/trialN-{before,after}.json`).
- `setup/corpus/` contains the frozen 10K/100K TSVs and manifest; the canonical manifest digest is `69052c66…c681151`.
- `setup/build/{A,B}/{build,reopen,remote}/…` contains the six original executables.
- `setup/sizes/{A,B}/n{10000,100000}-run{1,2,3}` contains twelve original indexes.

## 5. Independent proof record

| Proof | Result |
|---|---|
| Exact seal inventory (20 files + seal + 32 aux) | PASS |
| Auxiliary contention ↔ sealed slot copies | 32/32 equal |
| A/B source identities, ancestry, scope allowlist | PASS |
| Frozen protocol Git blob | `6f6322053d18b2379ee98f9307769f8101591425` |
| Frozen corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Six original binary hashes | A adapter `d6db9d9a…798a6`, reopen `1e6acf7d…7f32`, remote `7f6f7c1a…39a4`; B adapter `68143d7d…916f`, reopen `072d5def…18b8`, remote `b6d67634…0880` |
| Block topology | 4 blocks × 2 samples × 3 kinds × 2 arms = 24 block records |
| Lane matrix | 16 slots × 9 lanes = 144 lane records; 720 warmups; 2,880 samples |
| Independent oracle | 144/144 lane records match the frozen PR15D oracle |
| Three-build reproducibility | All four arm/size combinations `INDEPENDENTLY_RE_VERIFIED` |
| A sidecar | payload v1, required `[(1,1),(8,1)]`, overhead 170 bytes |
| B sidecar | payload v3, required `[(1,1),(8,1),(12,1)]`, overhead 174 bytes |
| Host observation | `HISTORICAL_ATTESTATION_NOT_INDEPENDENTLY_REPRODUCED` |
| Historical authorization / environment | `RECORDED_AND_CONSISTENT` / `FINGERPRINT_CONSISTENT_NOT_RECOMPUTABLE_FROM_RAW` |

## 6. Adversarial tests

`benchmarks/pr15i_a/test_verify.py` now contains the full accepted raw schema
fixture and one surgical mutation per finding. Coverage maps directly to the
plan: FT-A01 (accepted), A02–A08c (seal/inventory/aux), A09–A11/A24 (source),
A12–A19/A25–A27/A42/A54 (provenance), A20–A23/A28–A31/A34/A44 (matrix),
A32–A33 (oracle), A35–A43 (format/feature/accounting), A45–A47 (derived/receipt),
A48 (legacy route), A49–A53 (real campaign, read-only, sentinels, statuses), plus
integer-boundary tests.

- Synthetic fixtures use a temporary fake checkout and injected read-only Git /
  corpus / size-artifact seams; they never publish results.
- `FT-A49`–`FT-A53` run against the real `paired-04` evidence unchanged.
- Total: **78 tests pass**.

Honest limitation: the sealed `state_containers` record stores **required**
features only (the original schema has no optional-feature field). Optional-only
V3 rejection is therefore proven by the Rust codec test U29; the independent
verifier rejects every recorded required-set/version mismatch it can see
(FT-A35–A38).

## 7. Original measurements (unchanged)

| Arm | n | Sidecar | Total committed |
|---|---:|---:|---:|
| A | 10K | 960,180 | 3,090,037 |
| B | 10K | 230,132 | 2,359,997 |
| A | 100K | 9,600,180 | 30,965,025 |
| B | 100K | 2,383,748 | 23,748,601 |

All twelve gates are `PASS`; decision remains
`A_CANDIDATE_ACCEPTED_PENDING_QA`. No new performance claim, threshold or
measurement was produced.

## 8. Run history

1. Pre-fix shallow verifier: exit 0, `VERIFIED files=20` (insufficient).
2. Controller iterations during the original campaign (`paired-01`–`paired-03`)
   remain preserved and invalid; `paired-04` is the sole complete campaign.
3. Hardened verifier at `c46f3d4`: exit 0, `qualified=True raw=20 aux=32
   lanes=144 samples=2880`; seal before/after identical.
4. Legacy route at `c46f3d4`: exit 4, `A_USE_INDEPENDENT_VERIFIER`, no `VERIFIED`.
5. Receipt written exclusively; a second write is refused.

## 9. Final targeted QA (at `c46f3d4`; no full workspace re-run)

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15i_a -p 'test_*.py' -v` | PASS (78) |
| `python3 -m py_compile` (run, verify, test_run, test_verify) | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| `git diff --check` | PASS |
| Production diff `db9007f..HEAD` for core/Cargo/CI | empty |
| `verify.py --verify-only` on `paired-04` | PASS, read-only |
| `run.py --verify-only` | exit 4, redirect |

The prior full QA at code HEAD `7da3e99` (92.74% line coverage, stable+MSRV
tests/clippy, docs, RustFS acceptance) remains historical evidence for the
unchanged production code. A full workspace re-run is not required for this
Python-only fixup; hosted CI against the new branch tip is the external
workspace-wide gate.

## 10. Exception matrix applied

| ID | Trigger | Action |
|---|---|---|
| FX-A01/A02 | Branch at reviewed HEAD, clean, production identical to B | Continued on the branch |
| FX-A05 | Seal hash and inventory matched | Validated read-only |
| FX-A09/A11/A13/A15/A17/A19 | Frozen sources, protocol, corpus, binaries, host fields consistent | Checked, not trusted |
| FX-A22/A24/A26/A28 | A V1 / B V3, lanes/oracle/contention consistent, `derive` reproduced | Independent PASS before gates |
| FX-A30/A31/A32 | Legacy route weak; fixture lacked fields; verifier/test defects | Redirected, extended fixture, fixed verifier only |
| FX-A34 | Original campaign passed the corrected verifier without mutation | Wrote an exclusive review receipt |
| FX-A36 | Host idle/benchmarks authorized | Recorded; no fresh campaign substituted |
| FX-A37 | Changes confined to the fixup allowlist | Committed normally |
| FX-A38/A41 | Hosted CI inaccessible; review pending | Left as separate pending statuses |

No HARD STOP was triggered; no production defect was found.

## 11. Final disposition

`15IA_FIXUP_QUALIFIED_REVIEW_READY`.

- Independent receipt: all predicates PASS; seal and original evidence unchanged.
- `HOSTED_CI_PENDING`: PR #89 CI was not queried (branch has no upstream and no
  push was performed); no green CI claim is made.
- `INDEPENDENT_REVIEW_PENDING`: human review is external.
- `NOT_MERGED`, `NOT_PUSHED`.
