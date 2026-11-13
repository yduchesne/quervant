# PR 15I-D3-C — tooling freeze status

**T4: NOT FROZEN.** The D3-C tooling is aligned to the experimental source
commit `d00daf2812457a8d0b2627cce5d74006d4c8618b` and protocol SHA-256
`d0fe4085608bb6592076c71c1b7be69977fed978369ef1eb304d8eb6b39b95f2`.

Executed on this identity:

- `preflight`: `PREFLIGHT_OK` (BASE and feature binaries distinct).
- `dry-proof`: `DRY_PROOF_OK`; markers `linear:none`, `prefilter:P2`,
  `exact_set:none`.
- synthetic rehearsal: 3 positive campaigns + 5 verifier negatives PASS, and
  an actual `publish` refusal `D3C_REHEARSAL_PUBLISH_FORBIDDEN`.
- micro: 900 records, P2, source/protocol bound.

T4 remains unfrozen because the full preset V01–V60/M01–M16/P01–P22/RH-01–RH-16
matrix, missing `test_run.py`/`test_verify.py`/`test_micro.py`/`test_replay.py`
coverage, archive/predecessor qualification and the full external-verifier
rehearsal have not completed. No official timing may be acquired from this
state, and no official A/A or campaign was run.
