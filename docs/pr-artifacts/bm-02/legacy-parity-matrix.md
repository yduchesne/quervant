# BM-02 legacy parity matrix

Historical benchmark programs are **not** modified, migrated or retired by BM-02.
This matrix records deterministic fixture-level parity between reusable BM-02
primitives and the representative frozen behaviours, and explicitly classifies
every difference. Real historical archives are absent from the tracked tree and
are **not** recreated.

Legend:

* `PARITY` — the deterministic observable (member name/digest set or acceptance)
  is equivalent for the tested fixture.
* `BOTH_REJECT` — both the historical validator and the BM-02 verifier reject the
  same dangerous input.
* `NEW_STRICTER_REJECT` — the historical code accepts (or has no equivalent
  generic reader for) an input that BM-02 safely rejects. Safety is never weakened
  to force byte-level acceptance.

## Cases

| # | Case | Legacy behaviour | BM-02 behaviour | Classification | Test |
| --- | --- | --- | --- | --- | --- |
| 1 | TAR safe two members | `pr15i_d3_c_t7_f2.admission.safe_members` returns `{name: raw SHA-256}` | `inspect_tar_gz` returns the identical sorted set (prefix stripped in the comparator) | `PARITY` | `test_leg_03_tar_safe_member_sets_are_identical` |
| 2 | TAR traversal (`../`) | rejects unsafe component | rejects `BM_UNSAFE_INPUT` | `BOTH_REJECT` | `test_tar_traversal_both_reject` |
| 3 | TAR duplicate member | rejects duplicate | rejects `BM_UNSAFE_INPUT` | `BOTH_REJECT` | `test_tar_duplicate_both_reject` |
| 4 | TAR symlink member | rejects non-regular | rejects `BM_UNSAFE_INPUT` | `BOTH_REJECT` | `test_tar_symlink_both_reject` |
| 5 | TAR member over configured limit | historical hard cap is 256 MiB; a small fixture passes | injected smaller `ArchiveLimits` rejects | `NEW_STRICTER_REJECT` | `test_tar_overlength_is_new_stricter_reject` |
| 6 | TAR bad sidecar / modified archive | `validate_archive` rejects literal/sidecar mismatch | trusted expected archive/member digests reject the change | `BOTH_REJECT` | `test_tar_bad_sidecar_relative_to_archive_both_reject` |
| 7 | ZIP safe `ZIP_STORED` fixture | PR15D writes deterministic `ZIP_STORED` members with fixed timestamp/644 mode | `inspect_zip` reproduces the exact member bytes/digests and deterministic convention | `PARITY` | `test_leg_04_zip_deterministic_member_convention` |
| 8 | ZIP traversal | no generic read-only ZIP admission verifier in the frozen tools | rejects `BM_UNSAFE_INPUT` | `NEW_STRICTER_REJECT` | `test_zip_traversal_is_new_stricter_reject` |
| 9 | ZIP symlink | no generic read-only ZIP admission verifier | rejects `BM_UNSAFE_INPUT` | `NEW_STRICTER_REJECT` | `test_zip_symlink_is_new_stricter_reject` |
| 10 | ZIP duplicate member | no generic read-only ZIP admission verifier | rejects `BM_UNSAFE_INPUT` | `NEW_STRICTER_REJECT` | `test_zip_duplicate_is_new_stricter_reject` |
| 11 | ZIP member over injected limit | no generic over-limit ZIP rejection path | injected `ArchiveLimits` rejects | `NEW_STRICTER_REJECT` | `test_zip_overlimit_is_new_stricter_reject` |
| 12 | Self-reported hash with no independently pinned manifest | historical scripts require their own pinned literals/sidecars | admission rejects without a trusted spec/anchor | `NEW_STRICTER_REJECT` | `test_self_reported_hash_without_external_manifest_is_rejected` |

## Explicit non-claims

* BM-02 does **not** reproduce or verify the original T7/F2 real series, its
  gate results or its archives. Authentic historical archives under `target/` or
  external evidence roots are absent; the missing path is classified
  `EVIDENCE_UNAVAILABLE`, never PASS.
* No literal archive digest in `benchmarks/pr15i_d3_c_t7_f2/constants.py` was
  changed or reinterpreted.
* No PR15D packager code was rewritten or replaced; BM-02 only reads a tiny
  fixture modelled on its deterministic member conventions.
* The D3-C host-topology script is untouched; BM-02 host capabilities are a
  separate diagnostic schema, not a new default for frozen PR15I output.
* `NEW_STRICTER_REJECT` rows are documented exceptions, not parity claims to be
  retired by BM-02. BM-07/BM-08/BM-09 own full migrated-path parity and retirement.

## Protected historical paths

`test_leg_01_historical_tracked_files_are_unmodified` runs
`git diff --name-only <bm01-base> -- benchmarks/pr15d benchmarks/pr15i_d3_c
benchmarks/pr15i_d3_c_t7_f2 benchmarks/quervant_bench/config/schemas
docs/pr-artifacts/pr-15d` and asserts an empty result. BM-01 inventory
determinism is independently rechecked by
`test_leg_02_bm01_inventory_regenerates_byte_identically`.
