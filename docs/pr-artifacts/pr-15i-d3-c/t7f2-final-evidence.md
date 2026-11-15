# T7-F2 final evidence (pre-freeze)

- Gate D acceptance run: 60/60 exact tests PASS; 11 QA commands PASS;
  manifest `target/pr15i-d3-c/t7f2/acceptance-final`.
- Two fresh read-only derivations are byte-identical:
  - analysis `2c3854e4ff02f5acc9d7837d0267ae40101180df01c7db088705451bc8df3065`
    for both runs;
  - policy `e68ce9298e3be05540f732d51408085fc0f742e5fed45db52a2e48454576be21`
    for both runs.
- Both fresh policies independently verified: `verification=PASS`, 9 rows.
- Original R3 archive/micro/F1 hashes unchanged.

## Freeze caveat

A verifier defect was found after the acceptance run: `verify_policy.py`
passed an already-existing temporary directory to F1 `verify_derived.py`.
The fix was committed, but it changed F2 source after Gate D acceptance, so the
existing freeze receipt and acceptance manifest are no longer valid for the new
bytes. No final `T7_POLICY_COMPLETE` attestation is claimed. The complete 60
test + 11 QA acceptance must be rerun against the final source, followed by a new
receipt/anchor.
