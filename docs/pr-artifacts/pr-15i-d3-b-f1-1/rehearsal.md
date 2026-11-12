# PR 15I-D3-B-F1.1 — synthetic full-verifier rehearsal

**Result: `SYNTHETIC_REHEARSAL_VERIFIER_PASS` (round-03).** This is a
**rehearsal-only** verifier test on copied historical samples. It is not a new
control, not a measurement and not publishable.

## Source and integrity

| Item | Value |
|---|---|
| Historical input | F1 `d3bf1-base-aa-01` (blocked; no verifier PASS existed) |
| Historical T1 | `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82` |
| Original sealed members | 59 |
| Original inventory SHA-256 | `d5511aec2f2d2546e83a728a08872ea6103e8c7c37db6105361eed406e86ff88` |
| Original files unchanged | **YES** (rehashed before/after; `git diff --exit-code T1` empty) |
| New protocol SHA-256 | `ae1b7d8d9ab638e70cddb1e52d0b9dd063ccdffae74826ab67728db42a095b4c` |
| T2 tooling commit | `63b30a0be451357a5edaf8399ad2e4d336e6c45b` |
| Synthetic copy | `target/pr15i-d3-b/fixup-f1-1/rehearsal/round-03/d3bf11-base-aa-01` |
| Archive published | **NO** (`publish` guard; no receipt written to history) |
| Performance claim | **NONE** |

The copy contains only the sealed members plus a synthetic
`compile-source/.git` marker file. `build/`, `indexes/`, `corpus/` and the real
F1 checkout were never copied or rebuilt. The copied samples, doc IDs, hit
counts, binary digests, index sentinels, CPU observations, contention probes and
build timestamps are byte-identical to the originals.

## Deterministic transformations (identity/attestation only)

- Campaign `d3bf1-base-aa-01` → `d3bf11-base-aa-01`; comparison
  `d3bf1-base` → `d3bf11-base`.
- `protocol_sha256` replaced everywhere with the F1.1 protocol digest.
- `manifest.tooling_sha` = T2; controller/verifier/tooling-manifest digests from
  the committed F1.1 files.
- `authorization.rehearsal_only = true`, `manifest.rehearsal_only = true`, and
  the authorization statement `SYNTHETIC_REHEARSAL_ONLY; …`.
- Build-provenance and adapter-setup paths remapped to the rehearsal
  `compile-source/`, `build/A`, `build/B`; `command_argv`, `cwd`,
  `manifest_path`, `target_dir`, `binary_path` regenerated consistently.
- Host-attestation paths remapped for the six campaign roles; repository path
  kept; kernel/CPU/filesystem facts unchanged; `host_fingerprint` recomputed
  with the corrected campaign algorithm and independently confirmed by the
  verifier.
- `manifest.environment` mirror and dependent hashes updated; controller summary
  regenerated with `run.assemble_campaign`; seal regenerated over the exact
  original 59-member path set.

## Positive full-verifier result

External command:

```sh
python3 benchmarks/pr15i_d3_b_f1_1/verify.py \
  --campaign-dir target/pr15i-d3-b/fixup-f1-1/rehearsal/round-03/d3bf11-base-aa-01
```

Exit `0`, JSON:

| Field | Value |
|---|---|
| `verification` | `PASS` |
| `campaign_status` | `CONTROL_QUALIFIED` (synthetic only) |
| `summary_match` | `true` |
| `a_a_passes` | `true` |
| `slots` | 16 |
| `member_count` | 59 |
| `live_binary_rehash` | `UNAVAILABLE_ARCHIVE` |
| `structural` | build provenance / host / affinity all `PASS` |

## Negative matrix (15/15 exact codes)

| Case | Mutation | Expected | Actual |
|---|---|---|---|
| R02 | wrong `doc_ids` in a 10K rare lane, resealed | `V_ORACLE` | `V_ORACLE` |
| R03 | wrong positive `total_hits` in a high-cardinality lane, resealed | `V_ORACLE` | `V_ORACLE` |
| R04 | boolean sample, resealed | `V_SAMPLE_TYPE` | `V_SAMPLE_TYPE` |
| R05 | root `intruder.json` | `V_INVENTORY` | `V_INVENTORY` |
| R06 | nested `unlisted/compile-source/bait` | `V_INVENTORY` | `V_INVENTORY` |
| R07 | root `compile-source` symlink | `V_SYMLINK` | `V_SYMLINK` |
| R08 | sealed `compile-source/sneak` | `V_SEAL` | `V_SEAL` |
| R09 | altered sealed slot without resealing | `V_SEAL` | `V_SEAL` |
| R10 | corrupted host fingerprint, manifest+seal updated | `V_HOST` | `V_HOST` |
| R11 | altered `allowed_cpus_before_pin`, old fingerprint retained | `V_HOST` | `V_HOST` |
| R12 | duplicated CPU, resealed | `V_HOST` | `V_HOST` |
| R13 | provenance-only binary digest change, resealed | `V_BUILD_PROVENANCE` | `V_BUILD_PROVENANCE` |
| R14 | nonexistent 40-hex tooling revision, resealed | `V_TOOLING_SHA` | `V_TOOLING_SHA` |
| R15 | wrong protocol digest in authorization, resealed | `V_PROTOCOL` | `V_PROTOCOL` |
| R16 | unsealed `verification.json` with a conflicting verdict | invariance: still `PASS`/`CONTROL_QUALIFIED` | matched |

Harness self-test: a deliberately inverted expected code (`V_INVENTORY` vs
actual `V_ORACLE`) yields `matched_expectation=false` and
`harness_fail_closed=true`; the report exit code would be nonzero.

## Pre-T2 harness corrections (preserved attempts)

Two harness-only defects were found and corrected before T2; no verifier code
was changed for either:

- `round-01`: R02 mutated a slot without resealing, so the verifier correctly
  returned `V_SEAL` instead of the expected `V_ORACLE`. The case was corrected
  to reseal (R09 remains the unsealed-seal case).
- `round-02`: R09 tried to create an existing slot file exclusively, raising
  `FileExistsError` in the harness. The case now truncates the copied file.

Both failed rounds are preserved under
`target/pr15i-d3-b/fixup-f1-1/rehearsal/{round-01,round-02}` and are not
evidence. Tooling was re-committed as T_PRE2/T_PRE3 and the complete test suite
plus rehearsal matrix was re-run; **T2 = T_PRE3** because the successful
rehearsal ran without changing any F1.1 tooling byte.
