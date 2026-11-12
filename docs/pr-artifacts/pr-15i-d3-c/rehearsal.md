# PR 15I-D3-C — synthetic rehearsal (partial)

**Status: 3 positive + 5 negative cases pass; the full RH-01..RH-16 matrix is
not complete.** Synthetic fixtures are verifier-execution tests only, never
measurement evidence.

- `run.py preflight`: BASE and feature-enabled adapters built from one canonical
  path; distinct SHAs `2b0d8a65…` / `87e1164d…`.
- `run.py dry-proof`: 100K index built (committed bytes sentinel), and the real
  adapter emitted exactly one marker per mode:
  `linear:none`, `prefilter:P2`, `exact_set:none`.
- `replay.py`: synthetic control `d3c-base-aa-01` and both four-arm campaigns
  verify as `SYNTHETIC_REHEARSAL_ONLY`; negatives `tampered-slot` (`V_SEAL`),
  `extra-file` (`V_INVENTORY`), `wrong-marker` (`V_MODE`), `oracle`
  (`V_ORACLE`), `summary` (`V_SUMMARY`) were rejected.
- Not yet covered: RH-08 wrong profile/readiness, RH-10 predecessor tamper,
  RH-11 two-invalid/replacement, RH-12 performance rejection, RH-13 extra
  attempt, RH-15 original-hash audit, RH-16 publish guard, and the full V/M/P
  matrices.
