# PR 15I-D3-A performance qualification

Status: `D3A_MEASUREMENT_BLOCKED`. No candidate-hotspot or
intermediate-materialization priority is claimed.

## Qualification result

| Gate | Result |
|---|---|
| `D3A-P00` source/protocol/derivative | VERIFIED |
| `D3A-P01` A/A control | **FAILED** (attempt 01 and retry attempt 03) |
| `D3A-P02` Q/A intrusion | NOT RUN (control not qualified) |
| `D3A-P03` P/Q intrusion | NOT RUN |
| `D3A-P04` single-block guards | NOT RUN |
| `D3A-P05` A/QP index digests | NOT RUN |
| `D3A-P06` oracle | NOT RUN for campaigns |
| `D3A-P07` stage partitions | NOT RUN for campaigns |
| `D3A-P08` full campaign | NOT RUN |
| `D3A-P09` archive | failed controls archived and indexed; no qualified campaign archive |
| `D3A-P10` documentation/QA | completed honestly with blocked status |

## What is *not* concluded

- Candidate processing is not assigned a share of wall time.
- No named candidate child is declared dominant.
- No intermediate-materialization priority is declared.
- The superseded T0 campaign data is not used, even though it was measurable,
  because it predates the verifier stage-key repair and is not part of a fresh
  qualified series.

## Limits

The blocked result says nothing about the true cost decomposition. It records
that the host/stability gate did not qualify under the frozen control design.
A future authorized series must re-run the control and both paired campaigns
under one T0 with the protocol unchanged.
