# PR 15I-D3-A-F2 independent-review replay harness

This directory is **review-only**. It is outside the frozen
`benchmarks/pr15i_d3a/` tooling directory and does not change the T0d manifest or
any official evidence.

The harness copies official F2 campaigns into review-owned paths under
`target/pr15i-d3a/review/cases/`, applies controlled tampering, reseals the copy,
and invokes the frozen independent verifier. Every scenario has a declarative
expected outcome; the process exits non-zero if any expectation is unmet.

## Run

```sh
python3 benchmarks/pr15i_d3a_review/replay_matrix.py \
  --out target/pr15i-d3a/review/replay-matrix-final.json
```

Exit codes:

- `0` — all eleven scenarios match expectations.
- `1` — one or more unexpected outcomes (the JSON report is still written).
- `2` — setup, evidence loading, or harness execution failed.

## Scenarios and expectations

| Scenario | Expected |
|---|---|
| `positive_aggregate` | PASS, `D3AF2_ATTRIBUTION_QUALIFIED`, `D3A_CANDIDATE_HOTSPOT_LOCALIZED`, `candidate_duplicate`, medium/K100 + common/K100, all five runs |
| `oracle_tamper` | REJECTED, `INVALID` / `V_ORACLE` |
| `malformed_counter` | REJECTED, `INVALID` / `V_SAMPLE_TYPE` |
| `swapped_binary` | REJECTED, `INVALID` / `V_BINARY` |
| `missing_member` | REJECTED / `V_SEAL` |
| `extra_member` | REJECTED / `V_SEAL` |
| `altered_tooling` | REJECTED / `V_SOURCES` |
| `altered_protocol` | `EXPECTED_KNOWN_GAP` (frozen verifier accepts) |
| `duplicate_manifest` | `EXPECTED_KNOWN_GAP` (frozen verifier accepts) |
| `four_shared` | PASS, localized `candidate_duplicate` |
| `three_shared` | NOT_LOCALIZED, `D3A_CANDIDATE_STAGE_UNRESOLVED` |

The positive aggregate replay copies the control and all five campaigns to
`cases/positive-aggregate/{aa,paired}/` and calls `aggregate_series()` only on
those copies. It snapshots official evidence before and after and requires the
path/hash set to be unchanged.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15i_d3a_review -p 'test_*.py' -v
```

The tests cover fail-closed expectation matching, wrong rejection codes,
unexpected acceptance, missing/duplicate/extra scenarios, known-gap behavior
changes, exception handling, copied-path isolation, and snapshot change
detection. The full replay remains the integration test.
