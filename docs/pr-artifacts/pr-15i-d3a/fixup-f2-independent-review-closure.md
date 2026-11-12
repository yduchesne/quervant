# PR 15I-D3-A-F2 independent review closure

Status: **`REVIEW_APPROVED_WITH_DEFERRED_P2_HARDENING`**

The reviewer's P1 evidence gap is closed by a fail-closed, read-only replay
matrix. The two P2 gaps and the missing dispersion warning remain confirmed and
deferred to a future tooling revision. T0d tooling and official evidence were
not modified.

## Identities

| Item | Value |
|---|---|
| Branch | `dev/pr15i-d3a-candidate-attribution` |
| Official F2 measurement HEAD | `40fd6b92fe646f7bebe4e3076adfac9c8877696f` |
| Review-fixup base HEAD | `d730cbed4083e5719e4c986c5d018e1a532bdaa8` |
| T0d | `2c74e40d87f319c548c1f485d9b0267208311743` |
| Review-fixup commit | `2d464ac44de3dcccef8f9447cb8454a665a0de20` |
| Final HEAD | documentation follow-up commit on the same branch; see completion report |

## Command and result

```sh
python3 benchmarks/pr15i_d3a_review/replay_matrix.py \
  --out target/pr15i-d3a/review/replay-matrix-final.json
# exit 0
```

Overall result: `PASS`, 11/11 scenarios matched, 0 unexpected outcomes.
The report records `expected_scenario_count=11`, `executed_scenario_count=11`,
and `unexpected_outcome_count=0`.

## Eleven-case outcome table

| Scenario | Expected | Actual | Matched |
|---|---|---|---|
| `positive_aggregate` | PASS | PASS | yes |
| `oracle_tamper` | REJECTED / `V_ORACLE` | REJECTED / `V_ORACLE` | yes |
| `malformed_counter` | REJECTED / `V_SAMPLE_TYPE` | REJECTED / `V_SAMPLE_TYPE` | yes |
| `swapped_binary` | REJECTED / `V_BINARY` | REJECTED / `V_BINARY` | yes |
| `missing_member` | REJECTED / `V_SEAL` | REJECTED / `V_SEAL` | yes |
| `extra_member` | REJECTED / `V_SEAL` | REJECTED / `V_SEAL` | yes |
| `altered_tooling` | REJECTED / `V_SOURCES` | REJECTED / `V_SOURCES` | yes |
| `altered_protocol` | `EXPECTED_KNOWN_GAP` | `EXPECTED_KNOWN_GAP` | yes |
| `duplicate_manifest` | `EXPECTED_KNOWN_GAP` | `EXPECTED_KNOWN_GAP` | yes |
| `four_shared` | PASS, localized duplicate | PASS, localized duplicate | yes |
| `three_shared` | NOT_LOCALIZED | `D3A_CANDIDATE_STAGE_UNRESOLVED` | yes |

The positive aggregate asserts five campaigns, `control_qualified=true`,
`D3AF2_ATTRIBUTION_QUALIFIED`, `D3A_CANDIDATE_HOTSPOT_LOCALIZED`, component
`candidate_duplicate`, lanes `pr15d_v1/100000/medium/k100` and
`pr15d_v1/100000/common/k100`, and all five official run IDs.

## R2 — isolated positive replay

The positive aggregate now copies the control and all five official campaigns
into:

```text
target/pr15i-d3a/review/cases/positive-aggregate/
  aa/d3af2-base-aa-01/
  paired/d3af2-unbatched-01..05/
```

`aggregate_series()` is called only with those copied paths. The originals are
never output-bearing arguments. The harness snapshots the official
`fixup-f2/{aa,paired,aggregate}` path/hash set before and after replay; the
comparison reports `unchanged=true` with no added, removed or changed files.

## P2 findings retained and deferred

- Duplicate `raw/manifest.json` entries are still accepted by the frozen
  verifier. Actual F2 manifests contain no duplicate paths.
- An altered `authorization.json`/`sources.json` `protocol_sha256` is still
  accepted. Actual F2 artifacts contain the correct v3 hash
  `6a5eaaf8dd5ba1f9ed986a44201d742432e4f8a07b2e703949a55afba836163b` in every
  run; all archive sidecars match.
- The frozen verifier does not emit `HIGH_DISPERSION` or `max/min`. The
  review-only postprocessor reports no primary-lane MAD/median above `0.25`
  (0.84%, 0.40%, 1.36%) and preserves the original five-run statistics.

These are non-result-changing hardening items. Any change requires a new
tooling freeze; T0d remains immutable.

## Validation

| Check | Result |
|---|---|
| `python3 -m py_compile benchmarks/pr15i_d3a/*.py benchmarks/pr15i_d3a_review/*.py` | PASS |
| Frozen D3-A Python suite | PASS — 92 tests |
| Review replay tests | PASS — 13 tests |
| Review replay exit code | PASS — `0` |
| `replay_matrix.py` | PASS — exit 0, 11/11 |
| `git diff --check` | PASS |
| `git diff --exit-code 2c74e40… -- benchmarks/pr15i_d3a` | PASS — empty |
| Official evidence snapshot before/after | PASS — unchanged |
| Rust stable/MSRV fmt, Clippy, tests, docs | PASS |
| Workspace coverage | PASS — 91.96% lines, 92.68% regions, 87.48% functions |
| RustFS | not required for this local measurement review |
| Hosted CI | `CI_PENDING` |
| PR creation | `PR_NOT_CREATED` (invalid `gh` token; branch pushed by SSH) |
