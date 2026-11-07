# PR 15I-0 — invariant traceability

**Phase:** pre-implementation correctness gate (§3 of the execution contract).
This document maps every global invariant `I00`–`I15` to the paths that
implement or observe it, to the positive and negative test IDs `T00`–`T28`, and
to the evidence class that will actually be produced. It is written **before**
any PR 15I-0 tooling code exists, so every "new" row is a commitment that must be
satisfied later in this branch.

Evidence classes:

- **BASELINE** — already true at `BASE`; PR 15I-0 only preserves it.
- **REGRESSION** — an existing frozen suite re-executed on this branch.
- **NEW** — a PR 15I-0 test or capture that does not exist yet and must run.
- **UNPROVEN** — cannot be proven inside PR 15I-0; must be disclosed, never
  asserted.

## 1. Invariant matrix

| ID | Invariant (positive and negative) | Paths that implement/observe it | Positive tests | Negative tests | Evidence class | Unproven risk |
|---|---|---|---|---|---|---|
| I00 | Post-E production `crates/**` and lockfiles identical before/after 15I-0; no new reader/writer/codec behavior | `crates/**`, `Cargo.toml`, `Cargo.lock` | T00, T20 | T00 | BASELINE + REGRESSION | none identified |
| I01 | Measured source is an exact, clean, committed post-E baseline; historical source cannot silently replace it | `.git`, `benchmarks/pr15i_0/verify.py` | T01, T02, T03 | T02, T03 | NEW | none identified |
| I02 | Frozen PR 15D corpus/query matrix/oracle/adapters unmodified; all hits match the independent oracle | `benchmarks/pr15d/**`, `benchmarks/pr15i_0/verify.py` | T04, T05, T06 | T06 | REGRESSION + NEW | Oracle covers the frozen query matrix only, not arbitrary queries |
| I03 | Three engines measured same-host/same-corpus under the approved trial protocol; physical sort representations disclosed | `benchmarks/pr15d/harness/{run,validate}.py`, `docs/pr-artifacts/pr-15i-0/performance-attribution.md` | T05, T07 | T07 | NEW | Physical sort encodings are logically, not physically, equivalent (disclosed, `I0-X25`) |
| I04 | `--idle-confirmed` records authorization only; pre/post probes must actually clear or the run is unqualified | `benchmarks/scripts/check-pr07-contention.py`, PR 15D/15F harnesses, `verify.py` | T06, T08 | T06, T08 | NEW | Contention probe is a point-in-time process check, not a scheduler guarantee |
| I05 | All index bytes and all segment sections sum exactly to independently enumerated files; probes do not mutate inputs | `benchmarks/pr15f/reopen_probe`, PR 15F `inventory`, `verify.py` | T09, T10 | T09 | NEW | Enumeration is file-level; it cannot prove the writer wrote correct data |
| I06 | Sidecar parser consumes only envelope-verified original data; no unchecked offsets, guessed layouts or mutation | `benchmarks/pr15i_0/mutation_probe/src/*.rs` | T11, T12 | T12, T16 | NEW | none identified |
| I07 | Sidecar rows + replay + batch remainder + structural headers exactly equal payload bytes; container overhead separately reconciled | `benchmarks/pr15i_0/mutation_probe`, `result.py`-equivalent accounting in `verify.py` | T13, T14, T15 | T13, T14, T15 | NEW | v2 batch remainder is intentionally physical/opaque (`SEMANTIC_BATCH_DETAIL_NOT_VERIFIED`) |
| I08 | Corrupt, truncated, overlong, unsupported-version and unsafe-path inputs fail closed with classified nonzero exit | `mutation_probe`, `verify.py`, `run_mutation.py` | T13–T17 | each negative case | NEW | none identified |
| I09 | No generated size/speed number is labeled measured unless source, environment, oracle and seal qualify | `verify.py` gates, `summarize.py` | T18, T19 | T18, T19 | NEW | none identified |
| I10 | CPU attribution keeps exclusive and inclusive disjoint; unknown is not allocated without evidence | PR 15F `attribution.py` output; `verify.py` gate I0-P05 | T08, T18 | T18 | NEW | Inclusive shares are non-additive by construction |
| I11 | Source data, PIDs, credentials, paths and raw traces do not leak into committed sanitized reports | `summarize.py` sanitizer, committed reports | T19 | T19 | NEW | Sanitizer is pattern-based; reviewer must still read the output |
| I12 | Frozen 15I-A/B/C documents do not loosen durability, idempotency, PIT, corruption, budget or query/count semantics | `docs/pr-artifacts/pr-15i-0/architecture-15i-{a,b,c}.md`, `compatibility-matrix.md` | T21, T22, T23, T24, T25 | T22, T23, T24, T25 | NEW (docs) | Contracts are proposals; future plans must re-verify |
| I13 | Every required test exists, executes and passes in the stated topology; a historical run is not new evidence | all suites | T20, T26, T27 | T26, T27 | REGRESSION + NEW | RustFS topology requires container runtime |
| I14 | No architectural optimization is marked implemented/accepted by a measurement-only report | docs set | T21, T28 | T21, T28 | NEW (docs) | none identified |
| I15 | Missing GitHub credentials/CI never become falsely green and never suppress independent local capture | `final-report.md`, `decision-register.md` | T19, T28 | T28 | NEW | Hosted CI is externally gated |

## 2. Test-ID plan (what will actually execute)

| Test ID | Execution layer | PR 15I-0 implementation |
|---|---|---|
| T00 | shell + `verify.py` | protected-path `git diff --exit-code BASE HEAD -- crates/ Cargo.toml Cargo.lock .github/workflows benchmarks/pr15d benchmarks/pr15e benchmarks/pr15f`; gate `I0-P00` |
| T01 | shell + `verify.py` | `--source-sha` must be 40 lowercase hex and equal PR 15D/PR 15F declared sources; gate `I0-P00` |
| T02 | `test_verify.py` | malformed SHA, dirty-tree flag, source mismatch fixtures |
| T03 | `test_verify.py` | historical SHA presented as current is rejected |
| T04 | shell + `verify.py` | corpus digest equality between PR 15D run manifest and PR 15F prepared manifest; gate `I0-P01` |
| T05 | real PR 15D campaign | 3 trials × 3 engines at 10K/100K; gate `I0-P03` |
| T06 | real PR 15D validator + `test_verify.py` | oracle/contention/qualification field inspection; gate `I0-P03` |
| T07 | `test_summarize.py` | ratio computation, cross-source refusal, physical-sort caveat emission |
| T08 | real PR 15F `query-perf` + `test_verify.py` | nine lanes, sample quality, exclusive/inclusive separation; gate `I0-P05` |
| T09 | real PR 15F `inventory` | file and section reconciliation; gate `I0-P07` |
| T10 | `test_verify.py` | two inventories with different sources are refused |
| T11 | `mutation_probe` contract tests | valid v1 sidecar exact byte counts |
| T12 | `mutation_probe` tests | wrong kind, wrong section, unknown required feature, bad digest, symlink |
| T13 | `mutation_probe` tests | row-level negatives (truncation, zero revision, bad status, bad UTF-8, unsorted/duplicate keys) |
| T14 | `mutation_probe` tests | replay negatives (truncated token, short fingerprint, bad intent, zero revision, duplicate token) |
| T15 | `mutation_probe` tests | v2 opaque batch accounting, `<4` trailing bytes rejected |
| T16 | `mutation_probe` tests | oversized file, path traversal, corrupted original bytes, stale digest |
| T17 | real prepared 10K/100K capture | active-sidecar byte reconciliation; gate `I0-P08` |
| T18 | `test_summarize.py` + `test_verify.py` | inclusive-sum rejection, fabricated-latency rejection, unknown bucket preservation |
| T19 | `test_summarize.py` | qualified vs partial publication, missing allocation, privacy scan |
| T20 | workspace QA | `cargo fmt`/`clippy`/`test`/`llvm-cov`/`doc`/`bench --no-run` on stable and MSRV; gate `I0-P11` |
| T21 | docs review test | architecture docs must contain `DESIGN_PROPOSAL_ONLY` and must not claim implementation |
| T22 | docs review matrix | segment-ID ordinal is not a durable cross-generation identity |
| T23 | docs review matrix | unselected STORED corruption observability remains required |
| T24 | docs review matrix | exact counting and score parity, no early exit at K |
| T25 | docs review matrix | v1/v2 read paths, local/RustFS, PIT preserved |
| T26 | real `FsDirectory` integration | existing workspace integration suites (commit/restart/compaction/PIT) |
| T27 | real pinned RustFS | `tests/rustfs/run.sh` with `QUERVANT_PRODUCTION_S3_ADAPTER=1` |
| T28 | final report reconciliation | status labels keep `CI_PENDING`/`REVIEW_PENDING`/`NOT_MERGED` distinct |

## 3. Counterexample rehearsal (§3.3)

Each row states the *expected* behavior that PR 15I-0 must implement. These are
design commitments made before coding.

| Counterexample | Expected behavior | Where enforced |
|---|---|---|
| Truncation inside a live pointer (after the status byte, inside the `u16` segment-id prefix, or inside the final `u64` doc id) | `ByteReader` returns `SegmentError::Truncated`; probe exits nonzero with a typed class; **no** qualified JSON is written | `mutation_probe` row loop, T13 |
| Unicode key with non-ASCII bytes | key length is the UTF-8 **byte** length; the probe charges exactly that many bytes, validates UTF-8 and delegates semantic validation to the public `DocumentKey::new` | `mutation_probe` row loop, T11/T13 |
| Sidecar with payload v2 and non-empty batch | the entire remaining span starting at the batch `u32` count is charged as `batch_replay_opaque_bytes`; no nested field is decoded or invented; count is labelled `SEMANTIC_BATCH_DETAIL_NOT_VERIFIED` | `mutation_probe` v2 branch, T15 |
| Zero rows but non-empty replay | valid: `row_count = 0`, replay rows charged normally, totals still reconcile | T13 |
| Two equal keys | strict ascending byte order is required; equal keys are `Corrupt` and the probe fails closed | T13 |
| Symlink masquerading as a sidecar | refused by `symlink_metadata` on every path component **and** by the active-locator resolver; never dereferenced | T12/T16 |
| Corpus hash mismatch between PR 15D and PR 15F | combined qualification fails (`I0-P01`/`I0-P09`); each campaign may still be reported separately | `verify.py`, T04/T10 |
| Busy or unknown contention probe | campaign is preserved but marked unqualified; no retry inside the seal; no synthetic `clear` | `verify.py`, T06/T08, `I0-X11` |
| Stored/replay layout changed on newly merged source | the probe refuses to reinterpret: payload version outside `{1,2}` → `UNSUPPORTED_PAYLOAD`; unexpected framing → typed error; P4 is HARD STOPped | `I0-X20`, `I0-X22` |
| Unused sidecar objects from old generations | only the object resolved through `CURRENT → Manifest → MutationStateRef` (and cross-checked against the PR 15F inventory) is attributed as active state; obsolete objects remain counted only as filesystem footprint | `mutation_probe` resolver, T17 |

## 4. Scope-impact matrix (what PR 15I-0 may touch)

| Area | Change allowed | Enforcement |
|---|---|---|
| `crates/**`, workspace `Cargo.toml`, `Cargo.lock` | none | `git diff --exit-code BASE HEAD -- …`, gate `I0-P00` |
| `benchmarks/pr15d/**`, `benchmarks/pr15e/**`, `benchmarks/pr15f/**` | none | same diff |
| `.github/workflows/**`, release config | none | same diff |
| `benchmarks/pr15i_0/**` | new benchmark-only tooling and tests | review |
| `benchmarks/reports/pr15i-0/**` | sanitized derived JSON only | `verify.py` + privacy test |
| `docs/pr-artifacts/pr-15i-0/**` | reports and fixed design contracts | review |
| `target/pr15i-0/**`, `target/pr15d/runs/**`, `target/pr15e/**`, `target/pr15f/**` | private raw evidence, ignored by git | `git status` |

## 5. Residual unproven risks carried into the final report

1. The v2 batch replay *semantic* content is never decoded by PR 15I-0. Real
   engine acceptance comes from `Index::open` and the PR 15F reopen gate, not
   from this probe.
2. `DocumentKey`/`IdempotencyKey` semantic limits are enforced only where the
   public constructors are callable; any residual validation the production
   decoder performs beyond framing/UTF-8 is labelled
   `SEMANTIC_KEY_VALIDATION_NOT_PROVEN` if it cannot be reproduced through public
   APIs.
3. Cross-engine latency ratios are computed on logically equivalent but
   physically different sort representations. No BM25 score comparability is
   claimed anywhere.
4. RustFS conformance requires a container runtime; if unavailable the gate is
   reported `RUSTFS_ENVIRONMENT_BLOCKED`, never `SKIP`-as-pass.
5. Hosted CI and independent review are external and are reported as
   `CI_PENDING` / `REVIEW_PENDING` unless actually observed.
