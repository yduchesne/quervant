# BM-05 — Design, contracts, invariants and boundaries

Status: **PRE_IMPLEMENTATION_CORRECTNESS_GATE=PASS** (the invariant matrix and
dependency allowlist below were written before the first production edit; this
document is retained as the frozen design record).

Baseline: `main` at `66ce06ab725ee1efed799ca8cfacb4d4934d616f`, with merged BM-04
ancestor `06373a5f64ea2162f28224d4b9dbea169274e34c` verified by
`git merge-base --is-ancestor`.

## 1. Scope and non-goals

BM-05 verifies a synthetic BM-04 analysis/policy pair. It does not compute the
primary outputs, issue receipts, persist assessments, expose a CLI verb, launch
an adapter, read a wall clock, perform network I/O, retire a historical path,
or promote synthetic results to real evidence. No timed benchmark acquisition of
any kind is performed.

## 2. Module ownership

| Module | Owns | Must never do |
| --- | --- | --- |
| `verification/contracts.py` | frozen assessment record, ordered check ids, reference v1 literals | persistence, receipt identity, optional fields |
| `verification/reference_input.py` | independent treatment traversal, seal inventory, raw byte ledger, scope/disjointness checks | BM-04 sample reconstruction, writes, repairs |
| `verification/reference_math.py` | independent medians, block values, spreads, symmetric exclusions, estimators, GM, 12dp rendering, expected analysis assembly | import primary arithmetic/pruning/format helpers |
| `verification/reference_bootstrap.py` | independent SHA-256 rejection stream, nearest-rank indexes, paired interval | import primary bootstrap, use `random`/OS entropy |
| `verification/reference_policy.py` | independent frozen policy truth table and expected policy document | call `evaluate_policy`, `_select`, primary numeric helpers |
| `verification/verify.py` | bounded orchestration, structural first-line checks, deterministic first-difference comparison, integrity recheck | mutate inputs, create files, cache success |

## 3. Public API and state model

```python
verify_synthetic_run(
    *, bundle, run_dir, scenario_root, profiles_root, resources_root,
    analysis_document, policy_document,
) -> VerificationAssessment
```

`VerificationAssessment` is a frozen dataclass with exactly:

```text
status, experiment_id, run_id, evidence_origin, qualification_scope,
analysis_digest, policy_digest, source_seal_digest, reference_id, check_ids
```

The only successful status is `verified-synthetic`; origin/scope are the literals
`synthetic`/`simulated`; `reference_id` is `independent-synthetic-v1`. The ordered
check ids are `VC-01-SCOPE` … `VC-09-POST-READ-INTEGRITY`. Any failure raises the
existing typed `BenchError`; no partial assessment exists.

Logical state transitions (in memory only):

```text
UNTRUSTED -> BOUND_INPUTS -> STRUCTURALLY_REPLAYED -> INDEPENDENTLY_DERIVED
          -> COMPARED -> INTEGRITY_RECHECKED -> VERIFIED_SYNTHETIC
                                             \-> REJECTED (typed error)
```

## 4. Input authority and processing order

1. Type checks, safe roots, run/profile/resource/scenario disjointness, synthetic
   scope, and the frozen lower-is-better nanosecond envelope — before opening the
   run.
2. Read the frozen analysis profile, policy profile and resource observations
   through existing bounded canonical readers. Assert literal v1 semantics;
   derive the baseline from the frozen policy (never `arms[0]`) and require the
   candidate order to be every declared non-baseline arm in experiment order.
3. Call `replay_sealed_synthetic` once as the structural admission gate.
4. Read `seal.json` through the BM-02 no-follow reader, enforce the 1 MiB budget,
   decode canonical bytes, validate the closed seal document, compare scenario
   and experiment identity, and build the sealed `path -> (digest, length)`
   manifest.
5. Independently enumerate `treatment campaigns × compiled slots × workload
   lanes`, read every lane envelope, compare raw byte digest/length with the
   seal, enforce the full envelope identity, and store only bounded integer
   sample tuples indexed by `(campaign, lane, block, arm, slot position)`. A
   duplicate key, missing path, extra declared path or control contamination is
   rejected.
6. Recompute statistics from those samples: slot medians, per-arm block values,
   symmetric whole-block exclusions, raw/retained point effects, block effects
   and the complete ledger. Compare every non-bootstrap analysis field with the
   supplied analysis document.
7. Recompute each analysed candidate's paired bootstrap interval and stream
   identity, assemble the complete expected analysis document (including
   identity fields), and compare it with the supplied document.
8. Recompute the complete expected policy document from the **expected** analysis,
   frozen policy and frozen resources, and compare every field.
9. Recheck output identity/digests/budgets, rehash every consumed treatment file,
   re-read the seal, re-read profiles/resources/scenario and replay the run a
   second time. Only then return the assessment.

## 5. Invariant-to-test traceability

| ID | Observable invariant | Module/stage | Positive evidence | Adversarial evidence |
| --- | --- | --- | --- | --- |
| V01 | only validated synthetic/simulated bundles enter | `verify.py` P1 | vertical: checked-in fixture; `test_v_mut_01` | `test_v_mut_18` (`BM_SCOPE_MISMATCH`) |
| V02 | frozen identities; baseline may be non-first; candidate order trusted | `verify.py` P1–P2 | `test_non_first_baseline_slice`, `test_three_arm_gm_order_reversal_slice` | `test_v_mut_08`, `test_v_mut_18` |
| V03 | complete BM-03 replay + exact sealed inventory; controls excluded | `reference_input.py` P2 | `test_v_mut_01`, `test_insufficient_retained_blocks_is_not_constructible_on_frozen_bm03` | `test_v_mut_04`, `test_v_mut_05`, `test_v_mut_06`, `test_v_mut_07`, `test_v_mut_17` |
| V04 | independent slot/block/paired arithmetic and both estimators | `reference_math.py` P3 | `test_v_math_01..09`, `test_both_estimators_are_authorized_and_verified` | `test_v_math_02` (divergent estimator), `test_v_math_05`, `test_v_math_09` |
| V05 | outcome-blind symmetric pruning and complete ledger | `reference_math.py` P3 | `test_v_prune_01`, `test_v_prune_05`, `test_v_prune_06` | `test_v_prune_02`, `test_v_prune_04`, `test_v_prune_03` |
| V06 | independent paired bootstrap, fixed stream, exact quantisation | `reference_bootstrap.py` P4 | `test_v_boot_01`, `test_v_boot_03`, `test_v_boot_08`, `test_v_boot_09` | `test_v_boot_04`, `test_v_boot_05`, `test_v_boot_06`, `test_v_boot_10`, `test_v_boot_13` |
| V07 | independent resource/threshold/precedence/filter/GM/selection and reasons | `reference_policy.py` P5 | `test_v_pol_01`, `test_v_pol_03`, `test_v_pol_05`, `test_v_pol_09`, `test_v_pol_10`, `test_v_pol_12` | `test_v_pol_02`, `test_v_pol_04`, `test_v_pol_06`, `test_v_pol_07`, `test_v_pol_08`, `test_v_pol_11`, `test_v_pol_13`, `test_v_pol_14`, `test_v_pol_16` |
| V08 | every material field/digest matches source-derived expectation; false PASS rejected | `verify.py` P6 | `test_v_mut_01`, `test_v_mut_02` | `test_v_ind_05`, `test_v_ind_06`, `test_v_ind_07`, `test_v_ind_08`, `test_v_mut_09..15` |
| V09 | no mutation/write/persistence; pre/post integrity including race | `verify.py` P6 | `test_v_mut_02`, `test_package_contains_no_write_or_receipt_helpers` | `test_v_mut_06b`, `test_v_mut_16`, `test_no_persistent_state_or_new_file_on_rejection`, `test_v_mut_17` |
| V10 | oracle independence and no silent alternative verdict | AST/runtime P7 | `test_v_ind_01..04` | `test_v_ind_05..08` |
| V11 | historical availability/parity honest; no retirement | P8 | `test_v_hist_01`, `test_v_hist_02` | `historical-parity.md` status; absent archive is not a pass |

Every invariant row is exercised by at least one positive and one adversarial
test. Insufficient-retained-block arithmetic is proven at the reference-math
level (`test_v_prune_03`) and by forged-document rejection; a **positive sealed
vertical slice is structurally impossible** on the frozen BM-03 adapter because
it replays one sample vector per arm and lane for every slot, so every
within-block spread is exactly 1. See §9 and the verification report.

## 6. Required counterexamples

| Counterexample | Plausible wrong implementation | Test that fails it |
| --- | --- | --- |
| pooling samples across slots | median of raw samples instead of mean of slot medians | `test_v_math_07` |
| reusing the primary median/estimator | same implementation both sides | `test_v_math_02` (divergent literals) plus AST/poison audit |
| first-arm baseline | baseline inferred from `arms[0]` | `test_non_first_baseline_slice`, `test_three_arm_gm_order_reversal_slice` |
| one-sided pruning | exclude only the offending arm | `test_v_prune_02` |
| outcome-dependent pruning | prune after seeing the effect | `test_v_prune_04` |
| independent arm resampling | draw baseline and candidate separately | `test_v_boot_09` |
| wrong draw order | blocked/ordered stream | `test_v_boot_10`, `test_v_boot_03` |
| truncated campaign | stop after the first campaign | full-document comparison; mutation tests |
| mixed source digest | trust supplied digests instead of raw seal | `test_v_mut_08`, `test_v_mut_06` |
| structurally valid forged CI/selection | schema-only validation | `test_v_ind_05..07`, `test_v_mut_10`, `test_v_mut_13`, `test_v_mut_14_15` |
| exact tie cutoff | `<=` instead of `<` | `test_v_pol_11` |
| filter sensitivity as pruning | exclude blocks because of a sign change | `test_v_pol_07`, `test_v_pol_08` |
| stored envelope mutation after first read | trust the first read | `test_v_mut_06b`, `test_v_mut_16` |
| insufficient blocks fabricated into an interval | invent endpoints | `test_v_prune_03`, `test_v_mut_10` |

## 7. Dependency allowlist and forbidden imports

Runtime allowlist for `verification/`:

* stdlib: `hashlib`, `decimal`, `dataclasses`, `pathlib`, `typing`,
  `collections.abc`, `re`, `json` (fixtures only);
* `quervant_bench.config.{codec,contracts,errors,identity}`;
* `quervant_bench.evidence.paths`;
* `quervant_bench.execution.{contracts,recorder,replay,scenario}`;
* `quervant_bench.protocol.{controls,schedule}`;
* `quervant_bench.analysis.contracts` — only `validate_analysis_result`,
  `validate_policy_decision`, `require_bounded_document`;
* `quervant_bench.analysis.profiles` — only `read_analysis_profile`;
* `quervant_bench.analysis.policy` — only `read_policy_profile`,
  `read_resource_observations`.

Forbidden from `verification/`: `analysis.arithmetic`, `analysis.bootstrap`,
`analysis.pruning`, `analysis.derive`, `analysis.aggregation`, `analysis.history`,
`execution.controller`, `execution.synthetic`, `cli`, `host.*`; and the specific
names `evaluate_policy`, `_select`, `analyze_synthetic_run`,
`read_treatment_samples`, `compute_paired_effect`, `bootstrap_interval`,
`apply_lane_block_exclusions`, `quantize_effect`, `format_effect`,
`median_paired_ratios`, `ratio_of_arm_medians`; no `eval`/`exec`/`__import__`/
`importlib.import_module`.

`test_verification_independence.py` enforces this with an AST audit and a runtime
poison probe that replaces the primary call sites with raising functions after
the known inputs were generated.

## 8. Boundary classification

| Boundary | State | Disposition |
| --- | --- | --- |
| campaigns | zero / one / minimum / maximum | typed rejection or exact reconstruction; campaign count must equal `required_treatments` |
| blocks | 0 / 1 / minimum / maximum / over-limit | 0 and over-limit rejected by frozen profiles; 1 allowed structurally but interval needs ≥2 retained blocks |
| retained blocks | 0 / 1 / 2 / minimum | raw estimate retained; below `max(minimum_retained,2)` → null CI/stream, insufficient status |
| candidates | 1 / many / baseline non-first | exact frozen order; shared baseline |
| thresholds | exact bound and ±1 at the 12th decimal | strict `lt`, inclusive `le`/point, no epsilon |
| tie | exact tie / just below delta / exactly at delta | tie only for `< delta`, not at delta |
| resources | absent / exactly cap / one byte over | inconclusive / eligible / ineligible |
| JSON | duplicate keys / bad canonical bytes / wrong shape | typed rejection by existing codec/validators |
| paths | symlink / escape / oversize | `BM_UNSAFE_INPUT` |
| races | bytes changed between reads | `BM_IDENTITY_INVALID`, no assessment |
| counters | uint64 near-limit injection | `BM_UNSAFE_INPUT`, no wrap |
| processes/networks/timers | not applicable | the verifier launches nothing and performs no network I/O |

## 9. Historical classification

`benchmarks/pr15i_d3_c/verify.py` is the checked-in original historical verifier
and remains read-only. The external authentic archive root
`target/pr15i-d3-c` is present but **empty**, so the status is
`EVIDENCE_UNAVAILABLE`, parity is `NOT_EXECUTED`, and no legacy path is retired.
Historical equivalence/migration remains BM-07/BM-09 work. Synthetic BM-05
success is not historical parity.

## 10. Decision matrix use

No STOP condition was triggered. The only non-routine test-construction finding
was that a positive sealed "insufficient retained blocks" vertical slice is not
constructible under the frozen BM-03 one-vector-per-arm/lane scenario contract.
This matches D39 (unlisted, no architectural choice required): the affected test
coverage is provided at the independent reference-math and mutation levels, the
limitation is documented, and no production semantics were changed.

---

## 11. RF05 review fixup (appendix)

Reviewed start head: `a5a1261f4abf74ea3b37bf062cd5bbbde4947518`.

### 11.1 Authorized cross-boundary correction

RF05-01 corrects the pairwise filter-sensitivity predicate in **both** the BM-04
primary (`analysis/policy.py`) and the independent BM-05 reference. The frozen
rule has two distinct comparators:

* individual candidate parity: compare the effect with **1** (`_sign` /
  `sign_of`, unchanged);
* candidate-to-candidate order: compare the two effects relative to each other
  (**0**), implemented by primary `_relative_order` and independently by
  `reference_math.compare_candidate_order`.

Any order change (including tie creation/removal) flags every candidate in that
campaign/lane, as before. Missing effects skip the pair; they never become zero
or equality. This is a bug fix for the written semantics, not a new policy.
BM-04 arithmetic, bootstrap, pruning, thresholds, resources, selection and
serialization are unchanged.

RF05-02 adds `format_policy_limit_12`, a nonnegative formatter used **only** for
policy `point_limit`/`ci_limit` display. Measured effects, samples, denominators
and generic `format_12` remain strict-positive.

### 11.2 Fixup invariants

| ID | Property | Evidence |
| --- | --- | --- |
| FX05-01 | parity still compares to 1 | `F05-POL-06`, `F05-REF-06`, existing `AN-POL-17/18` |
| FX05-02 | pair order compares relative magnitude | `F05-POL-01..04`, `F05-REF-01..04`, `F05-CMP-01` |
| FX05-03 | order/tie change flags every candidate in the lane | `F05-POL-08`, `F05-REF-09` |
| FX05-04 | stable order with changing distance is not sensitive | `F05-POL-02`, `F05-POL-09`, `F05-REF-02/10`, corrected `V-POL-08` |
| FX05-05 | missing effect is not zero/equality | `F05-POL-05`, `F05-REF-05` |
| FX05-06 | eligible two-candidate flip → both INCONCLUSIVE, null selection | `F05-POL-07`, `F05-REF-07` |
| FX05-07 | poisoned primary filter output rejected by reference | `F05-IND-01` plus AST/poison suites |
| FX05-08 | zero limits render exactly `0.000000000000` | `F05-NUM-01/02`, `F05-REF-08` |
| FX05-09 | zero remains invalid for samples/denominators/effects | `F05-NUM-04/05` |
| FX05-10 | sealed synthetic zero-threshold derivation verifies | `F05-VERT-01/02` |
| FX05-11 | no BM-03/historical mutation, no acquisition, verifier read-only | existing `V-IND`/`V-MUT` plus snapshots |
| FX05-12 | final-head CI is authoritative | verification report fixup section |

### 11.3 Frozen adapter limitation

The BM-03 synthetic adapter emits one sample vector per arm/lane replicated across
positions, so within-arm spread is always 1 and a symmetric-exclusion pruning
reversal cannot be produced from a sealed run. The filter-order rule is therefore
proven with hand-authored **policy-only** analysis records executed independently
through BM-04 and BM-05, plus the `F05-IND-01` poison/rejection probe. No adapter,
seal, scenario or evidence was altered, and no policy-only fixture is presented as
a sealed BM-03 run.
