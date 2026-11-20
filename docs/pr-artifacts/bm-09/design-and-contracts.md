# BM-09 — design and contracts (preimplementation gate)

Status: **preimplementation contract**, written before the official production modules
were added. Append-only; later execution evidence belongs in
`verification-report.md`.

Baseline: `main` at `a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b` (BM-08 PR #109 merge
ancestry verified locally). Execution branch: `dev/bm09-real-qualification`.

## 1. Scope and trust boundary

BM-09 adds one **official qualification facade** on top of the existing, unmodified
real measurement backends:

| Family | Measurement backend (read/invoke only) | Original protocol identity |
| --- | --- | --- |
| retained-key | `benchmarks/pr15i_d3_c/run.py`, `verify.py` | `protocol_v3r3.json` raw SHA-256 `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`, `diagnostic_only=true` |
| cross-engine | `benchmarks/pr15d/harness/{run,validate,aggregate}.py`, `benchmarks/pr15d/corpus/oracle.py` | `benchmarks/pr15d/spec/pr15d_v1.json` |

Three origin/scope pairs stay strictly separated:

| Pair | Producer | Accepted by |
| --- | --- | --- |
| `synthetic`/`simulated` | BM-01…BM-08 | `qualification.*` synthetic loaders only |
| `real`/`historical_replay` | historical archive readers | `official.historical` only |
| `real`/`official` | `official.*` | `official.*` only |

`evidence.admission.admit_synthetic`, `qualification.contracts.require_synthetic_scope`,
`qualification.receipts.build_stage_receipt`, `analysis.*` and `verification.*`
keep their synthetic-only behaviour and are **not** widened. The official facade
reuses only: `config.codec`, `config.identity`, `config.contracts`
(`validate_receipt`, `validate_origin_scope`), `evidence.paths`/`hashing`/`archives`,
`host.capabilities`, `host.readiness`, and the *unmodified* legacy backends.

## 2. Module map and public surface

```
benchmarks/quervant_bench/official/
  contracts.py     constants, closed official-v1 records, scope predicates
  protocols.py     reviewed design templates; G0 authorization verification
  acquisition.py   typed, invocation-restricted legacy backend wrappers
  controls.py      live readiness + real A/A (cross-engine 12x4, retained-key)
  admission.py     raw evidence authenticity + inventory (Gate A)
  analysis.py      frozen per-family Gate B arithmetic/policy
  verification.py  independent Gate C recomputation (no official.analysis import)
  receipts.py      official receipt.v1 builder + gate DAG verification
  publication.py   strict official loader + shared exclusive publisher wrapper
  coordinator.py   G0 -> A -> B -> C -> D -> E orchestration
  historical.py    read-only legacy archive parity assessment
  report.py        sanitized report rendering
```

`qualification/identity.py::SOURCE_DIRECTORIES` gains
`benchmarks/quervant_bench/official`, so every new official module is inside the
reviewed source roster and the controlled synthetic QA fixture re-freeze is
mandatory once after the final Python edit.

`qualification/publication.py` gains one private helper
`publish_validated_members_atomic(...)` containing the existing byte-level
exclusive publication sequence. `publish_bundle`/`load_bundle` keep their public
signatures, synthetic validators, member inventory and fault-injection semantics.

## 3. Invariants O01–O22 and their implementation/test anchors

| ID | Invariant | Source | Primary tests |
| --- | --- | --- | --- |
| O01 | Real intake rejects synthetic/simulated, historical_replay and missing/altered scope before side effects | `official/contracts.py::require_official_scope`, `receipts.py::verify_official_receipt` | `O09-SCOPE-01..05` |
| O02 | No official pass without independently pinned G0 authorization bound to study/run/source/protocol/host/binary/corpus/output root | `official/protocols.py::verify_g0_authorization` | `O09-PRO-01..08` |
| O03 | D3-C `diagnostic_only=true` is never silently reinterpreted; the outer lock binds the frozen raw SHA and the T6 freeze receipt | `official/protocols.py`, `acquisition.py::require_retained_key_preconditions` | `O09-PRO-09..12` |
| O04 | PR15D exact 3 trials x 3 engines x 32 lanes, 20 samples, 5 warmups, 18 builds, 18 throughput windows | `official/acquisition.py::admit_cross_engine_inventory`, `admission.py` | `O09-ACQ-01..08` |
| O05 | D3-C exact control + 2 campaigns, 12 blocks, 72 lanes, A/L/P/H identity and mode markers | `official/admission.py::admit_retained_key_real` | `O09-ACQ-09..16` |
| O06 | Readiness/A-A use real observations only, never synthetic readiness | `official/controls.py` | `O09-CTL-01..12` |
| O07 | A failed readiness/A/A blocks treatment; partial directories stay durable and non-reusable | `official/coordinator.py` state machine | `O09-CTL-13..18` |
| O08 | Gate A verifies inventory, safe paths, digests, identities, every trial/campaign entry and the original verifier | `official/admission.py` | `O09-ADM-01..16` |
| O09 | Units/regimes never mixed; `process_cold` is not OS-cold; BM25/throughput excluded from warm ratios | `official/analysis.py` | `O09-ANA-01..08` |
| O10 | Frozen per-family real policy; no synthetic conclusion import; no threshold invented from data | `official/analysis.py` | `O09-ANA-09..16` |
| O11 | Gate C recomputes certified assertions from raw samples with independent code | `official/verification.py` | `O09-VER-01..18` |
| O12 | A pass receipt carries the correct status, exact input/output digests and required edges | `official/receipts.py` | `O09-REC-01..12` |
| O13 | Gate D consumes real QA evidence for the same source commit | `official/coordinator.py`, `contracts.py::validate_official_qa` | `O09-QA-01..12` |
| O14 | Gate E snapshots, publishes once atomically and re-opens/re-verifies before PASS | `official/publication.py` | `O09-PUB-01..16` |
| O15 | Same run + exact inputs => `REUSED_VERIFIED`; changed input => error, never repair | `official/publication.py::load_official_bundle` | `O09-REU-01..10` |
| O16 | Both families share one receipt builder, publisher, outcome taxonomy and manifest type | `official/receipts.py`, `publication.py`, `coordinator.py` | `O09-E2E-01..06` |
| O17 | Original legacy sources/archives/reports stay byte-identical | `official/historical.py` (read-only) | `O09-HIS-01..06` |
| O18 | Historical parity is independently verified, never inferred from new success | `official/historical.py::assess_required_historical_parity` | `O09-HIS-07..14` |
| O19 | No performance winner without frozen policy; valid inconclusive is not a false fail | `official/analysis.py::derive_official_policy` | `O09-ANA-17..20` |
| O20 | No cleanup/unsafe path destroys or overwrites authentic evidence | `official/acquisition.py`, `publication.py` | `O09-SAFE-01..12` |
| O21 | PR QA, RustFS, console entrypoint, CI and "no timing on CI" are separate verified gates | `official/report.py`, `docs/pr-artifacts/bm-09/qa-and-attestation.md` | `O09-REG-01..08` |
| O22 | Docs and `v0.1-bench COMPLETE` only after real+historical+review gates pass | `official/report.py::closeout_status` | `O09-DOC-01..06` |

## 4. Candidate false-PASS counterexamples (each must fail closed)

1. A `real/official` document with a recomputed self-hash but a synthetic or
   `historical_replay` scope → rejected by `require_official_scope`.
2. A G0 authorization whose `design_digest` equals the digest of the candidate
   template file itself, with no independently pinned digest passed by the caller
   → `verify_g0_authorization` requires an external `independent_expected_digest`
   argument; a candidate file can never supply its own trust root.
3. D3-C `diagnostic_only` promoted implicitly by relabelling
   `protocol_v3r3.json` → original bytes are hashed; a changed hash is
   `BM_IDENTITY_INVALID`, and the template requires an explicit
   `outer_mapping_approved=true` + reviewer identity.
4. `ACQUIRED_VERIFIED` control whose `a_a.passes` is false → Gate A recomputes the
   per-lane A/B ratios and rejects.
5. A quantile/median recomputed with a different interval rule than the legacy
   contract (e.g. averaging the two middle values of twenty samples) → Gate C
   independent implementation uses the original nearest-rank/even-N rule and
   compares field by field, so a mismatch blocks Gate C.
6. A forged `analysis.json` with every downstream digest coherently rehashed →
   Gate C recomputes from raw samples and compares, so a forged value is rejected.
7. A `process_cold` or throughput lane inserted into the warm eligible set →
   `official.analysis` classified sets reject the lane id.
8. An incomplete official destination (`manifest.pending` present, foreign file,
   or missing member) treated as reusable → `load_official_bundle` returns
   `BM_PUBLICATION_CONFLICT`, never `REUSED_VERIFIED`.
9. QA evidence with `executed=true` asserted by the producer but no observed CI
   run/job identity → `validate_official_qa` requires concrete run ids, exact head
   SHA and zero `mandatory_skipped`.
10. Historical parity inferred from a new real campaign → `historical.py` returns
    `EVIDENCE_UNAVAILABLE`/`BLOCKED` when the authentic archive or an approved
    mapping is missing; Gate D refuses a `pass` receipt with a blocked
    `historical-parity` input.

## 5. Decision matrix applicability (recorded at preflight)

| Rule | Observation on the execution host | Action |
| --- | --- | --- |
| M01 | HEAD equals the reviewed baseline, tracked tree clean | AUTO-RESOLVE: branch created, baseline recorded |
| M12 | `target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json` **absent** | DEFER AND CONTINUE: retained-key real acquisition BLOCKED |
| M17 | Historical `pr15i-d3-c-v3r3` archives exist under the operator's global evidence root | AUTO-RESOLVE: an isolated `HOME` namespace is required for any future retained-key run |
| M24 | No independent G0 approval exists and none can be minted by the agent | DEFER AND CONTINUE: no timed control/treatment; candidate locks only |
| M34/M53 | Adapter toolchains and historical PR15D archives are not provisioned | DEFER AND CONTINUE: cross-engine real acquisition BLOCKED |
| M55 | Authentic T7 micro/F1/policy inputs are not present | DEFER AND CONTINUE: retained-key policy `POLICY_NOT_DERIVABLE` |
| M90 | Any condition outside M01–M89 | HARD STOP |

## 6. Source-to-test map (files added)

| Test module | Covers |
| --- | --- |
| `test_official_contracts.py` | closed records, scope matrix, subject/limit rules |
| `test_official_protocols.py` | template/G0 freeze, D3-C diagnostic mapping |
| `test_official_acquisition.py` | backend wrappers, argv/env/timeout, inventory arithmetic |
| `test_official_controls.py` | readiness, A/A windows and boundaries |
| `test_official_admission.py` | raw inventory, oracle, archive security, mutation |
| `test_official_analysis.py` | Gate B arithmetic, regimes, exclusion symmetry |
| `test_official_verification.py` | independent recomputation, forged-input rejection |
| `test_official_receipts.py` | seven-gate receipt graph and cross-scope rejection |
| `test_official_publication.py` | durability seams, marker semantics, reuse |
| `test_official_coordinator.py` | lifecycle state machine, blocked gates |
| `test_official_historical.py` | read-only parity assessment |
| `test_official_scope.py` | real/synthetic/historical isolation end to end |

Every test module uses `tests/fixtures/official/` (or in-test temporary roots) with
`fixture_only=true` markers; no test launches a real engine, a real timing process
or a campaign.

---

# RF09-F1 addendum — verified external authorization

The trust model is now:

```
external approval record (closed, operator-supplied, outside the repo)
  + independently approved authorization digest
  + freshly observed source/tree/adapter/binary/corpus/host/QA/schedule identities
  -> open_verified_official_authorization(...)            (only production factory)
  -> VerifiedOfficialAuthorization (fixture_only=False)
  -> require_verified_official_authorization(...)         (revalidates at every entry point)
  -> acquisition | admission | verification | coordinator | publication
```

Additional invariants enforced by the fixup:

| ID | Invariant | Test |
| --- | --- | --- |
| FX09-01 | Only a verified external G0 creates production authorization | G0F-02, G0F-04, G0F-05 |
| FX09-02 | A caller-built `OfficialFreeze` cannot execute, attest or publish | G0F-01, G0F-02b, G0F-03 |
| FX09-05 | A fixture-only capability never becomes official | G0F-07, PUBF-07 |
| FX09-06 | QA documents match the G0-pinned digests | QAF-02, QAF-03 |
| FX09-09/10 | Parity is recomputed and externally approved, never a caller row | HPF-01, HPF-02, HPF-13, HPF-15 |
| FX09-14 | PR15D backend root is exactly `raw_root/backend` | LAY-01, LAY-02, LAY-04, LAY-05 |
| FX09-17/18 | Production Gate A runs the pinned verifier; no stub is accepted | VERF-01, VERF-02, VERF-03, VERF-04 |
| FX09-20 | No durable write before complete anchor validation | PUBF-01, PUBF-02, PUBF-03, PUBF-06 |
| FX09-23 | Legacy/BM-01–08 bytes and synthetic QA semantics unchanged | full regression + legacy manifest |

`open_verified_official_authorization` requires an approval record whose closed
shape is `{kind: official-g0-approval-record, schema_version: 1, study_id,
approved_authorization_digest, independent_review_id, approved_at_utc}`. If the
external authority uses a different format, that is an operator/reviewer decision;
the implementation accepts only this closed shape and fails closed otherwise. No
production approval record was created by this fixup.

---

# RF09-F2 addendum — admission and QA provenance

```
verified G0 (existing)
  -> pinned original verifier executed over the raw bytes
  -> VerifiedOfficialAdmission (RF09-08; sentinel-guarded, re-admitted at Gate A)
       -> Gate B / Gate C (Gate C requires the capability, not a raw record)
  -> G0-pinned QA summaries + 33 executed check records + 33 raw logs (RF09-09)
       -> read before any QA receipt, re-read after Gate C, re-read before Gate E
  -> complete 1,440-row externally approved historical mapping (RF09-10)
       -> VerifiedHistoricalParity (rechecked at Gate D)
  -> Gate D -> Gate E (existing exclusive publisher)
```

Additional invariants enforced by F2:

| ID | Invariant | Test |
| --- | --- | --- |
| F2-01 | A plain or copied `Admitted*` record cannot enter production | ADMF-03, ADMF-04 |
| F2-03 | The coordinator re-admits the raw bytes and compares all digests | ADMF-09, ADMF-10 |
| F2-04 | Re-admission is read-only (no timing, no mutation) | ADMF-11 |
| F2-07 | Each check record digest equals the G0-pinned summary entry | QAE-05, QAE-10 |
| F2-08 | Each log exists, is safe/bounded and matches its recorded SHA-256 | QAE-07..09 |
| F2-09 | Source commit, source set, toolchain, runner and zero-skip are verified | QAE-12..16 |
| F2-11 | Missing artifact blocks the QA receipt | QAE-02, QAE-04 |
| F2-12 | Exactly 1,440 ordered coordinate/metric rows are required | HPC-01..08 |
| F2-14 | `total-hits=0` is valid only for the count/ID metrics | HPC-11..13 |
| F2-15 | Expected values are re-derived; caller rows are never trusted | HPC-15 |
| F2-17 | Archive/mapping/approval/verifier are rechecked before Gate D | HPC-19, HPC-20 |
| F2-18 | Retained-key nine-K parity stays unavailable | HPC-21, HPC-22 |

---

# RF09-F3 addendum (2026-11-17) — Gate C provenance

```
verify_official_study(admitted, authorization, admission, source_root, ...)
  | exact admitted type; authorization must be VerifiedOfficialAuthorization
  | mode := authorization.fixture_only        (never admitted.fixture_only)
  | submitted.fixture_only must equal mode     -> else BM_UNSAFE_INPUT/admission
  |
  +-- production -> require VerifiedOfficialAdmission + source_root
  |                 reverify_official_admission(...)      (fresh Gate A re-admission)
  |                 _require_exact_admitted_record(submitted, fresh)
  |                     -> exact type + complete recursive dataclass equality
  |                     -> mismatch = BM_IDENTITY_INVALID/admission, before RV-01
  |                 RV-01..RV-10 run on the FRESH record
  |
  `-- fixture    -> existing bounded in-memory behaviour, never publishes
```

| ID | Invariant | Test |
| --- | --- | --- |
| F3-I01 | Production Gate C cannot certify a caller-modified record with unchanged bytes | F3-GC-02 |
| F3-I02 | Comparison covers every comparable field, not only timing vectors | F3-GC-02/03/04/06/07 |
| F3-I03 | Mode is derived from the verified authorization | F3-GC-08/09 |
| F3-I04 | A genuine production-shaped admission still verifies | F3-GC-01, O09-E2E-01/02 |
| F3-I05 | In-repo QA roots are `BM_UNSAFE_INPUT`; absent roots are `BM_FILE_MISSING` | F3-QAE-20/20B/20C |
| F3-I07 | No timed acquisition, engine launch or closeout claim | diff audit + this report |

---

# RF09-F4 addendum (2026-11-17) — persisted control authority

```
production admission (for_production=True)
  inventory = hash_raw_members(raw_root, cross_engine_member_paths(raw_root))
  parsed    = read control/control.json  (strict, no-follow, bounded)
  require sha256(canonical_document_bytes(parsed)) == reader_digest
  require exactly one inventory member: path, digest, byte_length
  require canonical_payload_bytes(supplied) == canonical_payload_bytes(parsed)
  return parsed                      # never the supplied mapping
```

| ID | Invariant | Test |
| --- | --- | --- |
| F4-I01 | A production control equals the canonical inventoried file | CP-01 |
| F4-I02 | Parsed hash, reader hash, inventory hash and length all agree | CP-12, CP-13 |
| F4-I03 | JSON values collapsed by Python equality are still rejected | CP-03, GC-02 |
| F4-I04 | No nested aliasing between caller memory and the admitted record | CP-04 |
| F4-I05 | Old capabilities cannot be rebound by disk+memory changes | CP-10 |
| F4-I08 | Missing/unsafe/malformed/oversized inputs keep their typed errors | CP-05..CP-08, CP-15 |
| F4-I09 | Fixture mode stays in-memory; retained-key and F3 guards unchanged | CP-11, F3 regressions |

Gate C adds canonical cross-engine control comparisons (capability → `control`,
submitted → `admission`) around the existing full-record equality. No new schema,
capability field, cache or bypass; `qualification/identity.py` and the fixture
rosters are untouched.

RF09-14 (ExactSet capacity accounting) is diagnosed but repaired separately.

---

# RF09-F4 Addendum A (2026-11-17) — ExactSet bounded storage

```
construction (requested K)
  set.try_reserve(K + 2)              # retained limit + one transient insertion
  scratch.try_reserve_exact(K + 1)    # retained limit incl. pagination sentinel
  T = set_capacity * 40 + scratch_capacity * size_of::<DocumentKey>()
  h_preflight(T); h_commit(T)         # charged exactly once, fixed for the query

admission (ExactSet, competitive)
  validate retained bound / counts / scratch empty / capacity >= len
  old_charge = worst.charge; old_len = worst.key.len
  peak = (N + O) + charge_new              -> h_preflight
  release = old_charge + O                 -> h_preflight_release
  if capacity == len (or forced) -> rebuild_exact_set  (same allocations, no clone)
  h_commit(N + O); heap_admit_candidate
  insert new key BEFORE removing the evicted key
  release 2 * O; live += N - O; T unchanged
```

| ID | Invariant | Tests |
| --- | --- | --- |
| A-I01 | A valid replacement never fails on a capacity change | A-U02, u43 ×20 |
| A-I02 | `T` stays fixed; no refund without deallocation | A-U01, A-U07 |
| A-I03 | Set membership equals the retained heap (incl. sentinel) | A-U07, A-U08, A-V01 |
| A-I04 | Rejection leaves heap, keys, scratch, balances and peak unchanged | A-U05, A-U06, A-U09 |
| A-I05 | Rebuild moves existing keys through fixed storage | A-U03 |
| A-I06 | Duplicates, eviction, ordering, cursor semantics preserved | A-U08, A-V01, A-V02 |
| A-I07 | Production keeps `RandomState`; no runtime hasher switch | source review; default-build tests |

Residual: the determinism fixture is toolchain-specific; permanent tests assert
semantics and ledger conservation, not bucket layout. The persisted control-slot
provenance gap and all real G0/T6/L3/parity gates remain unchanged and blocked.

---

# RF09-F4 Addendum B (2026-11-17) — Gate C family guard

```
verify_official_study(admission=capability, admitted=record)
  | exact admitted type, verified authorization, mode from authorization
  | production only:
  |   authoritative = reverify_official_admission(capability, ...)
  |   _require_exact_admitted_record(admitted, authoritative)
  |     1. exact family: type(submitted) is type(authoritative)
  |     2. full recursive dataclass equality
  |     3. cross-engine only: canonical_payload_bytes(control) equality
  |     -> all failures: BM_IDENTITY_INVALID / field "admission"
  |   admitted = authoritative
  | RV-01..RV-10 on the fresh record
```

The capability's own control mutation is still reported with field `control` by
production re-admission (`_read_bound_cross_engine_control`), so no inline
comparison is needed in Gate C. Reading `authoritative.control` only after the
family guard removes the wrong-family `AttributeError`.

| ID | Invariant | Test |
| --- | --- | --- |
| B-I01 | Wrong family fails at `admission` before family-specific access | B-P01, B-P02/P03 (both orientations + public negative) |
| B-I02 | Evidence is read-only; unsafe members fail closed | CP-08 (leaf/parent symlink, hardlink, FIFO), CP-10, GC-04 |
| B-I07 | Diagnostic bounded scope validates only its selected workload | H01–H06 executed; branch reverted on allowlist conflict |

Residual: RF09-16/17/19 unexecuted; diagnostic branch not retained; real G0/T6/L3
and historical parity unchanged and blocked.

---

## RF09-17 — ExactSet construction seam and ledger contract (append-only, 2026-11-18)

- **One owned construction path.** `State::new_with_builder` builds an empty state,
  installs the hash builder, and delegates every remaining construction step to
  `finish_construction`. Production (`for_request`/`new_for_kind`) and the test
  entrypoints (`for_test_accounted`, `for_test_accounted_with_builder`,
  `for_test_accounted_with_builder_and_fault`) all traverse the same seam, so the k
  bounds check, the reservation, the `T = set_capacity·40 + scratch_capacity·size_of::<DocumentKey>()`
  charge, and the `h_preflight`/`h_commit` pair cannot diverge between modes.
- **Reservation precondition.** `reserve_exact_set` is defined only on an empty,
  *uncharged* state: any retained key, pending scratch entry, or non-zero
  `exact_table_charged`/`exact_live_key_charged` is `CorruptIndex`
  (`"exact-set reservation requires an empty, uncharged state"`). Re-reserving a charged
  state would double-charge the structural ledger.
- **Ledger model.** The constructor commits `T` once; each admitted key commits
  `charge + key_len` (`charge = 64 + key_len`); a replacement transiently commits
  `new_len + old_len + new_charge` before releasing the evicted `charge + old_len` and
  the `2·old_len` overlap. The retained live-key charge tracks `Σ key_len` separately in
  `exact_live_key_charged`, and both sinks (`CandidateBudget` and a real
  `SlotMemoryScope`) must agree with the model after every step.
- **Test-only fault surface.** `ReserveFault::{Set, Scratch}` exists behind
  `#[cfg(test)]` and can only be passed through the seam; production cannot select a
  fault, and the local/batch rejection types remain `SearchError::ResourceLimit` and
  `QueryError::BudgetExceeded { kind: BatchMemoryBytes }` respectively.

---

## RF09-F4-B-E2 — test oracle design and bookkeeping clarification (append-only, 2026-11-18)

- **Shared independent model.** `InputRecord { key, score, charge }` is built once per
  case; `charge = 64 + key.len()` is computed from the key, never from production
  bookkeeping. `input_entry` constructs the real `MixedEntry` and asserts its charge
  equals the record. `model_insert` maintains a borrowed `Vec<&InputRecord>` best-first
  (score descending, key ascending); `model_current = T + Σcharge + Σkey_len`;
  `model_next_peak` derives the transient of one operation from the *pre-operation*
  model only. Nothing in the model reads `State`, the heap, the budget or the scope.
- **Fixed structural charge.** T is captured from the physical capacities of the
  freshly constructed, empty accounted state
  (`set_capacity·40 + scratch_capacity·size_of::<DocumentKey>()`) and then held
  constant for the case. The runtime effective capacity cannot redefine T.
- **Complete `Snapshot`.** Rejection atomicity and allocation identity are compared
  with one private struct covering set key pointers, heap `(key, score bits, charge)`,
  set/scratch lengths and capacities, scratch contents and pointer, recorded charges,
  retained bound, initial capacity, pending-rebuild flag, rebuild count and both
  ledgers. Deliberately corrupted states are snapshotted, never validated.
- **Ownership order.** Every case drops the heap and `State` first, then calls
  `finish_success`/`finish_failure` (or exercises the Drop path in U11 mode 2), then
  ends the meter borrow, and only then reads `meter.current()`/`meter.peak()`.
- **Ordering oracles.** U08 keeps the original R=3 duplicate/reappearance chain beside
  the R=2 tie chain and asserts literal best-first sequences: the model order is
  independent, and the heap order is observed through
  `heap.iter().collect::<BinaryHeap<_>>().into_sorted_vec()`, never used to build the
  expectation.
- **Bookkeeping clarification (replacement release).** Production *preflights*
  `old_charge + old_len` before the eviction to prove the release is legal. That
  preflight mutates nothing. The committed release is
  `heap_commit_release(old_charge)` **plus** `h_release(2·old_len)`, i.e. the evicted
  entry charge plus twice the evicted key length; the transient amplitude is
  `new_len + old_len + new_charge`. The earlier E1 wording implied a committed
  `old_charge+old_len` refund as well, which would double-count 2·old_len.


## BM-09 operator migration after E2 (2026-11-19)

The implementation continuation starts at
`b7ce3a478af6012c607debea090dfad0b3d2ac17`. The user authorized completing the source
migration and explicitly prohibited benchmark execution in this task. The
existing RF09 engine repairs remain the baseline; this continuation changes no
Rust engine code or frozen legacy measurement/protocol/verifier file.

The supported current design is documented in
[`../../BENCHMARK_WORKFLOW.md`](../../BENCHMARK_WORKFLOW.md). The intended
operator boundary is the two required real representative families plus their
two logical synthetic references. Native Criterion and earlier diagnostic
entrypoints retain their separate documented roles.

### Implemented ownership

- `execution/operator.py` executes only closed stage plans. Callback membership
  and ordering are fixed; failure prevents every later stage; no retry is added.
- `official/workflow.py` connects configured preparation, G0 opening, readiness,
  full control/treatment acquisition, sealed admission and later independent
  stage reopening. Synthetic configured execution uses the same stage executor.
- `cross_engine_backend.py` adds the missing complete Quervant/Quervant A/A
  producer and full raw-control verification before the existing three-engine
  measurement primitives can run. Prepared native binaries and the complete
  Lucene runtime inventory are rehashed against the approved identities.
- `retained_backend.py` and `retained_acquisition.py` preserve the frozen D3-C
  campaign order, original measurement primitives, predecessor verification,
  readiness, records and seals. Actual rebuilt executable bytes must match the
  prepared G0 bytes before any indexing or query primitive.
- `legacy_readiness.py` reads the actual unchanged D3-C record format, recomputes
  intervals and counters, and admits the legacy count/lower-median summary shape.
- `policy_inputs.py`, `retained_policy.py` and `policy_reference.py` bind authentic
  P2/F1 inputs and re-admitted raw slots, derive the frozen T7/F2 nine-K decision
  chain, and independently recompute it. Historical replay uses its mapping's
  own archived inputs, never the current-run policy capability.

### Fixed continuation and compatibility decisions

Preparation is untimed and precedes the QA records for its generated builds. A
completed preparation receives source-bound `preparation-inputs.json`. Missing
QA returns `BM_EVIDENCE_UNAVAILABLE/qa_evidence` with no authorization-input file;
repeating preparation may only rehash and finalize that exact completed build.
Partial preparation cannot be repaired or rebuilt in place. Finalization checks
actual source commit/set, the fixed QA roster, and all 33 check-record bindings;
G0 opening and acceptance retain full 66-member/log verification.

Retained analysis requires authentic policy inputs before persisting derived
records. Missing inputs leave sealed raw evidence usable by `validate` and later
continuation. No immutable underivable placeholder is written that would prevent
the same sealed run from progressing once inputs arrive.

The original BM-01 `outcome.v1` schema and registry remain byte-identical.
Configured operator results use the separate closed `outcome.v2` schema under
`config/operator_schemas`; ordinary inspection and errors preserve their existing
v1 envelope. The new validator module and schema are included in both the
applicable validator source closure and the overall source identity.

Preparation and acquisition run in owned process groups with frozen deadlines,
bounded reap/cleanup, preserved failure output and no retry. A successful
controller exit also cleans surviving owned descendants. Preparation errors cross
only a bounded private JSON result channel. No executable callback, shell
command, skip-control switch or caller PASS value is accepted from configuration.

Read-only later stages re-open approval, source, binaries, raw evidence and
policy inputs. `report` compares the existing publication with a freshly derived
manifest. The RF09 exact-family, canonical-control, full-record equality and
fresh re-admission safeguards remain in force.

No official performance result, authentic historical parity, legacy retirement,
independent acceptance, merge or v0.1-bench closeout is established by this source
migration. The execution agent's next steps are the repository workflow, not a
chat execution archive or a new implementation plan.

---

## BM09-CONTINUATION-POST-MIGRATION-1 — bounded design decisions (append-only, 2026-11-18)

- **QA prerequisite set.** Source QA answers "does this source implement the
  authorization and control boundaries correctly", not "is this run approved".
  The two new checks are executed hosted regression results over the production
  authorization, external-approval and measured-control paths; the run-specific
  facts stay with G0 and the live A/A control. Roster order is alphabetical, the
  source roster is unchanged, and the template delta is confined to
  `required_qa.framework`.
- **Campaign scope.** The reviewed sequences are a closed property of the study,
  enforced centrally in `validate_authorization` after the schema, safe-relative
  member and non-empty checks. Reordering, duplication, omission, extension or
  substitution between families is an identity failure
  (`permitted_campaign_order`), never a schema error, and it precedes every
  acquisition effect.
- **Exact-source CI.** A push trigger plus a read-only identity step distinguishes
  the tested merge `M` from the authorized source `C`: the step prints the event
  name/SHA, the PR head (when present), the checkout commit and tree, then fails
  unless the checkout commit equals the event SHA. No job, permission, command,
  service or filter changed, and the parsed workflow equals the migration baseline
  plus only these hunks.
- **Versioning.** Schema version 1 is retained: the shapes are unchanged and this
  is a correction to an unreleased contract. Old QA and old G0 pins must fail
  because the roster, template and source digests changed.


## 2026-11-19 — Approved current-baseline acceptance direction

The maintainer superseded mandatory legacy-versus-new execution proof. The new framework must produce and preserve complete current runs, report A/B effects within each run, and use compatible historical proportional effects only when authentic data is available or faithfully recoverable. Missing historical observations must not indefinitely block a current baseline. Cross-run absolute A/A, B/B or absolute A-minus-B comparisons are excluded. Environment differences remain context and do not automatically bar proportional reporting; they prevent unsupported code-only causal attribution.

Native Linux and WSL2 selection is implemented in this patch, with actual environment bound to G0 and unchanged capability/affinity/readiness constraints. The fresh current-baseline runtime/acceptance/export design is specified, not yet implemented, in `docs/BM09_COMPLETION_PLAN.md`; `docs/BENCHMARK_MIGRATION_ACCEPTANCE.md` is its normative contract. Existing v1 historical/full-policy readers remain strict. Missing micro/F1 does not prevent raw-slot ratios/CIs, but it cannot justify memory-based strategy adoption. A distinct v2 baseline verification scope must state that boundary positively.

Complete current evidence is to be preserved automatically at `benchmark-results/baselines/<baseline-uuid>/`, with a separate clean-checkout replay receipt. No mandatory legacy reference run, new micro run, manual ZIP handoff, fabricated historical receipt, historical hash change or merge is authorized by this amendment. Original scientific source pins remain visible: retained BASE/experiment are pinned variants, while cross-engine Quervant uses final source C.

---

## BM09-CURRENT-BASELINE-1 — relative effects and bounded history (append-only, 2026-11-19)

- **Projection, not estimation.** `official/relative_effects.py` adds no
  arithmetic of its own beyond the documented ratio↔percentage conversion, which
  uses exact `Decimal` values on the canonical ratio strings produced by the
  existing computations. Retained rows reuse `derive_slot_statistics` /
  `reference_slot_statistics` outputs (all six arm pairs, 72 lanes × 2 campaigns
  × 6 comparisons = 864 rows); cross-engine rows reuse the frozen descriptive
  comparison table with `quervant` as the baseline and the comparator as the
  treatment (16 lanes × 2 = 32 warm rows, no invented interval, decision
  `INCONCLUSIVE`).
- **Scale-invariant comparisons.** Effects are compared only as
  `effect_change_percentage_points`, never as historical/current absolute times.
  Comparability requires identical workload coordinates, metric, unit, direction,
  arm roles and method; environment or source differences downgrade the pair to
  `CONTEXT_CHANGED` and are recorded as context, not causality.
- **Bounded history.** `official/history.py` validates a closed inventory
  (`official-baseline-history-inputs`, schema 1) whose roles map one-to-one onto
  the family and a fixed existing reader; frozen retained archive digests are
  mandatory, so a mismatched archive is `INVALID` rather than "found". Statuses
  are disclosure only: they cannot mint a historical PASS, cannot block an
  independently verified current baseline, and cannot substitute for measurement.
- **Disclosure binding.** The history and relative-effects payloads are closed
  envelopes carrying `baseline_id`, `study_id`, `source_commit` and
  `current_raw_digest`; reopening compares all four and rejects symlinks,
  oversized files and malformed documents.
- **Scope.** The v2 profile, versioned templates and dispatch, current runtime
  freeze, transport/preservation, clean-checkout replay and the current family
  acquisitions are not part of this change and remain the next stage.

## BM09-CB1 — Steps 2–6 implementation continuation (2026-11-19)

This section continues the accepted Step 1 source at
`a92212e01763bb13e6b63e0f0957523f1fd5c00e`. It supersedes the earlier statements
that v2 wiring, runtime freeze and transport remain unimplemented. It does not
supersede the historical evidence recorded above. The maintainer authorized
implementation of Steps 2 through 6 together, with final full-host verification
and actual execution left to the coding agent. No timing or merge is part of
this authoring execution.

### Versioned execution and authority

The existing workload IDs select explicit registered version 2 templates. V1
templates, generic receipts, frozen schemas, old statistical methods and old
T6/parity/policy requirements remain intact. Configuration, authorization,
admission, analysis, verification, receipt inputs, publication and operator
outcomes all select the same profile. Mixed versions fail before acquisition or
publication effects. V2 authorization binds twenty observed identities and a
shared baseline UUID; independent approval records retain their schema 1
envelope. Only the existing independent approval factory grants live G0 authority.

The new `VerifiedCurrentRuntimeFreeze` binds the complete protected source roster,
actual Git blobs, prepared bytes, corpus, host, CPU pair, schedules and approved
output root. Preparation creates its eight-key compatibility receipt and
twenty-key envelope before QA finalization. The receipt is explicitly current,
not a reconstructed historical T6. Exact content, complete roster equality and
double descriptor observations are mandatory. A partial pair is preserved and
rejected. V1 rejects the current marker. Retained invocation, worker, readiness
and publication barriers reopen the runtime from paths and digest; forked memory
does not grant authority.

### Independent current-baseline calculations

The Step 1 decimal/proportional implementation remains the arithmetic owner.
The added numerical matrix exercises its resource limits, full-precision
intervals, hostile Decimal contexts, literal vectors, every row field, family
grids and comparison identities. For lower-is-better measurements,
`gain_percent = 100 * (1 - treatment / baseline)`; for higher-is-better metrics,
`gain_percent = 100 * (treatment / baseline - 1)`. Cross-run change is
`current_gain_percent - historical_gain_percent`, in percentage points. No
reciprocal speedup or cross-run absolute-time comparison is introduced.

V2 retained analysis carries the existing six paired-slot comparisons for all
72 lanes and both campaigns. Gate C independently reconstructs those statistics
through the reference owner. Current rows contain exactly 864 retained or 32
cross-engine effects. Missing authentic micro/F1 inputs keep policy
`NOT_EVALUATED`, with no selected arm or adoption claim, while valid current
measurements can receive `VERIFIED_CURRENT_BASELINE`. Insufficient symmetric
retained blocks produce a bound BLOCKED diagnostic, preserve the raw series and
do not authorize a retry. V1 retains its complete-policy requirement.

The disclosure capability reopens live authorization, admission and independent
verification and reconstructs both payloads. It binds policy inputs, full history
inventory, current raw digest, source/run/host identities and the exact complete
effect grid. Gate D and publication reopen that capability. Correctly shaped or
coherently rehashed caller-supplied rows do not substitute for reconstruction.

### Preserved originals and portable replay

The evidence destination is an unignored ordinary branch checkout at
`benchmark-results/baselines/<baseline-uuid>`, separate from the detached measured
source. Acquisition checkpoints each completed raw unit before later validation
or analysis. Early readiness and home-probe failures also preserve a STOPPED
checkpoint, without claiming acquisition. Secondary preservation failure cannot
hide the primary acquisition error. Existing members are immutable; identical
reuse is read-only.

Qualification adds original G0/QA records and logs, configuration/preparation and
runtime provenance, raw controls/readiness, task-owned retained published
archives, independent results, disclosures and used policy inputs. The terminal
manifest must agree with the original checkpoints and exact member inventory.
Export is bounded and rejects secret-bearing records without rewriting sealed
bytes. No build trees, executables, indexes or deterministic corpus payloads are
committed.

Offline replay verifies a clean evidence descendant of measured source, tracked
original members, source/legacy/template blobs, the original G0 observations,
all 66 QA members and the qualification graph. It regenerates the deterministic
corpus and uses the shared bounded projector for only the approved path changes.
Original validators and independent statistical/effect owners execute on those
confined views. The original raw digest is restored only as the identity used to
compare rederived records; every calculated field must still agree. The reader
does not mint live authorization/admission capabilities or open original
producer paths. `PRESERVED` and `REPLAY_VERIFIED` are distinct states. The replay
receipt is a separate committable result, not a rewritten original attestation.

Available authentic raw historical archives use the same projector and
independent calculations; summary-only effects remain `AS_REPORTED`. Original
negative availability observations are retained without reopening producer
locations. Missing history does not become a current-run gate or a historical
PASS.

### Necessary integration scope decisions

The maintainer's direct implementation authorization covers the concrete owner
corrections found during integration. Three paths beyond the old agent plan's
literal implementation allowlist were necessary:

| Owner | Executed defect / required correction |
| --- | --- |
| `official/admission.py` | A v2 authorization could reach a v1 admission template. Both live factories and private data cores now check exact profile, family and canonical design before raw/source/verifier work. |
| `config/operator_schemas/outcome.v2.schema.json` | Correct v2 preparation and operation results were rejected by the closed public output schema. Two explicit closed sibling definitions were added; every pre-existing definition is preserved. |
| `config/contracts.py` | The public outcome semantic validator also needed the explicit v2 branch, matching the new schema and registered statuses. |

No parent plan was rewritten to grant an exception. No scientific estimator,
legacy verifier, Rust module, benchmark harness, CI trigger, historical archive or
BM-01 inventory guard was relaxed. Full-host acceptance, genuine G0 approval,
both real acquisitions, committed real results, clean-checkout replay and final
independent review remain actual execution gates. Step 7 and merge are separate.

### Final-candidate pin linkage and replay issuance correction (2026-11-20)

Two additional synthetic-fixture paths are necessary consequences of the
deliberate public outcome v2 contract extension above. The generic evidence
validator's closed source roster includes `config/contracts.py` and
`config/operator_schemas/outcome.v2.schema.json`; their reviewed changes altered
that validator closure. The old synthetic trusted specification therefore failed
source verification before its admission/receipt/publication tests could execute.
This is a synthetic linkage correction, not a relaxation of source verification.

| Additional path | Exact permitted change |
| --- | --- |
| `benchmarks/quervant_bench/tests/fixtures/evidence-admission/trusted-spec.json` | Only the literal `validator.source_digest`, from `sha256:b333a16d3632c8a938230483ff9559482837cf65d49bf7c6c9e15d100f03237e` to the independently calculated closure `sha256:13f8683725f5d0960a3235acf0036018c36e41314f8f39da57f2de0014844cdc`. |
| `benchmarks/quervant_bench/tests/test_evidence_admission.py` | Only the literal `GOLDEN_SPEC_DIGEST`, from `sha256:ec19ebcf053e244aae42d5ea663b540202a4cd1de2518a376f20c608e6ee86fa` to the independently calculated canonical specification digest `sha256:2e322fdcc3c0615237f5aad169f6e83881af0241f2046f2c57bf624fa3b2608c`. |

Every other trusted-specification field and test-file byte is preserved. The
golden remains an independent literal rather than a runtime-derived expected
value. Its evidence origin remains `synthetic` and scope remains `simulated`.
The fixed historical catalog, authentic source/archive pins, original legacy
bytes and existing validation rules are unchanged. The final candidate's three
generic evidence modules execute 71 tests successfully with this corrected pair.

The narrow offline review also found a late Git-identity gap. Replay checked a
clean checkout, measured-source ancestry and source/member Git blobs before
reconstructing the two studies. Its terminal checks reobserved original members
and `HEAD`, but an unrelated untracked file or a tracked source change introduced
during replay could leave those checks unchanged and still produce a successful
receipt. The correction reuses `_verify_source_link` after the existing terminal
member and `HEAD` checks and before issuing `VerifiedBaselineEvidence`; the
returned evidence commit and checkout identity must equal their initial values.
There is no new authority factory, weaker check or receipt-based shortcut.

Three focused public `replay_baseline_evidence` boundary cases use real temporary
Git C-to-D history, the actual manifest/checkpoint/member validators and actual
receipt issuance. Before the correction, the two late-mutation cases failed with
`Exception not raised`, while the unchanged control passed. After the correction,
all three pass: either late mutation produces
`BM_UNSAFE_INPUT` / `replay_checkout` without a receipt, and the unchanged case
retains its valid identity. All 13 real-Git boundary tests pass in the final
candidate. These three cases explicitly substitute only the expensive per-study
replay hook; they do not constitute authenticated raw/statistical replay proof.
The independent raw-replay integration tests retain that separate responsibility.

The authoring receipt
`/workspace/scratch/0e14cdb0afff/steps2_6_evidence/final-candidate-verification.json`
records the isolated candidate, exact commands/log hashes and sixteen-file
correction set: the four pin/replay paths and twelve qualification linkage
fixtures. It records the initial active refresh and the later final-candidate
refresh separately; the initial receipt was preserved. The candidate source-set
digest is
`sha256:314ebfedf0a6b90e6fd33d47f8a2090279045f1dd7e8f54c70ba475262f040de`,
with unchanged profile digest
`sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c`.
When this documentation was appended, the active source-set digest remained
`sha256:fb7552ec8f1e35566208f02a2cd239ce190c7e73a4181ebfd21b87a550b4ed3e`;
the source-bound suite's files were not edited. These are bounded candidate
results, not a final full-suite result, published commit, hosted CI or real-run
acceptance claim.
