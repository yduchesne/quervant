# PR 15I-D3-C — tooling freeze status

**T4: NOT FROZEN.** The D3-C tooling is aligned to the experimental source
commit `3ad6c5184fbe9c011abb731415a007e3f19d21de` and protocol SHA-256
`c7a062f85ffc2b356612ea0b47e062cb7f59c23444164c438fd2a3d9f0404002`.

Executed on this identity:

- `preflight`: `PREFLIGHT_OK` (BASE and feature binaries distinct).
- `dry-proof`: `DRY_PROOF_OK`; markers `linear:none`, `prefilter:P2`,
  `exact_set:none`.
- synthetic rehearsal: 3 positive campaigns + 5 verifier negatives PASS, and
  an actual `publish` refusal `D3C_REHEARSAL_PUBLISH_FORBIDDEN`; the series
  verifier also requires cross-campaign source/protocol/host provenance.
- micro: 900 records, P2, source/protocol bound.

T4 remains unfrozen because the full preset V01–V60/M01–M16/P01–P22/RH-01–RH-16
matrix, missing `test_run.py`/`test_verify.py`/`test_micro.py`/`test_replay.py`
coverage, archive/predecessor qualification and the full external-verifier
rehearsal have not completed. No official timing may be acquired from this
state, and no official A/A or campaign was run.
