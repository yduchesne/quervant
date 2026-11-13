# PR 15I-D3-C — tooling freeze status

**T4: NOT FROZEN.** Source identity is `3ad6c5184fbe9c011abb731415a007e3f19d21de`;
protocol is `c7a062f85ffc2b356612ea0b47e062cb7f59c23444164c438fd2a3d9f0404002`.

Implemented and executed in this qualification pass:

- `verify.py --series-root` accepts a BASE-only control (no experimental SHA),
  enforces common BASE/protocol/profile/host identity, and requires the frozen
  experimental SHA only for both four-arm campaigns.
- `policy.py` requires one independent full-series verification before any
  policy evaluation or output.
- `run.py` predecessor validation opens the published tar, verifies the sidecar,
  campaign identity, archive digest, member names, counts and per-member hashes,
  and rejects extra/missing/substituted members.
- New `test_run.py`, `test_verify.py`, `test_micro.py`, `test_replay.py` execute
  positive and adversarial cases; `python3 -m unittest discover ...` reports
  43 passing tests.
- Rehearsal now executes 3 synthetic positives and 16 verifier negatives,
  including real publisher refusal with no archive/sidecar.
- Preflight/dry-proof passed at the final source identity.

T4 is still not frozen because the ID-by-ID V01–V60 / M01–M16 / P01–P22 /
RH-01–RH-16 matrix is not fully enumerated and executed, even though the
implemented behaviors are covered by the new suites. No official timing may be
acquired and no A/A or campaign has been run.
