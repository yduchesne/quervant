# BM-05 — Historical D3-C/T7 evidence status

## 1. Checked-in historical oracle inventory (read-only)

`find benchmarks/pr15i_d3_c -type f` found the original historical tooling and
tests, including `verify.py`, `analysis_v3.py`, `policy.py`, `replay.py` and
`test_verify.py`. Their SHA-256 digests and the semantic mapping to BM-05 are
recorded in `oracle-mapping.md` §6. Nothing under `benchmarks/pr15i_d3_c/` was
modified or executed.

The historical T7 estimator (`legacy-python-randrange-v1`, ratio of arm medians)
is a separate compatibility path from the new BM-04 default
(`sha256-rejection-paired-block-v1`, median-paired-ratios-v1). BM-05 never
presents one as the other and never copies PR-specific arm/lane names into
generic modules.

## 2. Authentic external archive

`analysis.history.inspect_archive(Path("target/pr15i-d3-c"))` returned:

```text
STATUS=EVIDENCE_UNAVAILABLE
HISTORICAL_SERIES_VERIFIED=NO
NUMERIC_PARITY=NOT_EXECUTED
POLICY_VERDICT_PARITY=NOT_EXECUTED
REASON=required authentic external archive not present
OWNER=BM-07/BM-09; no historical path retired by BM-04
```

The directory exists but is empty (`entry_count=0`). No original offline legacy
verifier was executed because there is no authentic archived evidence to verify.
No archive was invented, no synthetic fixture was labelled historical and no
historical path was retired.

## 3. Disposition

| Field | Value |
| --- | --- |
| `HISTORICAL_ARCHIVE` | `EVIDENCE_UNAVAILABLE` |
| `HISTORICAL_ORIGINAL_VERIFIER` | `NOT_EXECUTED` |
| `HISTORICAL_NUMERIC_PARITY` | `NOT_EXECUTED` |
| `HISTORICAL_DECISION_PARITY` | `NOT_EXECUTED` |
| `LEGACY_PATHS_RETIRED` | `NO` |

This is a documented unfulfilled optional historical check, not a fabricated
pass and not a blocker for independent **synthetic** BM-05 correctness. Any
legacy retirement or complete historical equivalence remains BM-07/BM-09 work
and is globally blocked until authentic evidence exists.

The availability-handling logic itself is exercised without mislabelling a
fixture: `test_v_hist_01_empty_archive_is_reported_unavailable_without_writing`
and `test_v_hist_02_checked_in_legacy_oracle_path_exists`.
