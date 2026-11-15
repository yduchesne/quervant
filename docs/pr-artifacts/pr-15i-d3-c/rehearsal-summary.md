# PR 15I-D3-C — synthetic rehearsal summary

Status: SYNTHETIC_REHEARSAL_ONLY. Synthetic evidence was deleted after the run.

- Positive cases: 3
- Negative cases: 16
- Publish guard: PASS (D3C_REHEARSAL_PUBLISH_FORBIDDEN)

| case | exit | status |
|---|---:|---|
| d3c-base-aa-01 | 0 | SYNTHETIC_REHEARSAL_ONLY |
| d3c-strategies-01 | 0 | SYNTHETIC_REHEARSAL_ONLY |
| d3c-strategies-02 | 0 | SYNTHETIC_REHEARSAL_ONLY |

| negative | expected | actual | exit | matched |
|---|---|---|---:|---|
| tampered-slot | V_SEAL | V_SEAL | 3 | True |
| extra-file | V_INVENTORY | V_INVENTORY | 3 | True |
| wrong-marker | V_MODE | V_MODE | 3 | True |
| oracle | V_ORACLE | V_ORACLE | 3 | True |
| summary | V_SUMMARY | V_SUMMARY | 3 | True |
| source-sha | V_SOURCE | V_SOURCE | 3 | True |
| host-identity | V_READINESS | V_READINESS | 3 | True |
| binary-provenance | V_BINARY | V_BINARY | 3 | True |
| readiness | V_READINESS | V_READINESS | 3 | True |
| affinity | V_AFFINITY | V_AFFINITY | 3 | True |
| sample-count | V_SAMPLE | V_SAMPLE | 3 | True |
| sample-median | V_SAMPLE | V_SAMPLE | 3 | True |
| lane-count | V_SLOT | V_SLOT | 3 | True |
| index-digest | V_INDEX | V_INDEX | 3 | True |
| protocol-sha | V_PROTOCOL | V_PROTOCOL | 3 | True |
| campaign-name | V_CAMPAIGN | V_CAMPAIGN | 3 | True |
