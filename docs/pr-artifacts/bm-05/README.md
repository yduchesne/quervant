# BM-05 — Independent synthetic analysis and policy verification

Status: **implementation complete locally; remote CI pending**. This directory
records the design freeze, oracle provenance and independence audit, mutation
matrix, historical evidence status and final local verification evidence for the
BM-05 pull request.

## What BM-05 is

BM-05 adds a separable, read-only verifier that reopens a sealed BM-03 synthetic
run and independently reconstructs the BM-04 paired statistics, symmetric
whole-block exclusions, SHA-256 paired-bootstrap confidence intervals and frozen
policy decision. It compares the **complete canonical analysis and policy
documents** with its own reconstruction and returns an in-memory
`VerificationAssessment` only after every mandatory check passes.

It is not a Gate A–E receipt, not an attestation, not a persistence mechanism,
not a CLI verb and not a real performance conclusion. BM-06 owns durable gate
coordination and receipts.

## Public surface

```python
from quervant_bench.verification import VerificationAssessment, verify_synthetic_run
```

`verify_synthetic_run(...)` is keyword-only and returns
`VerificationAssessment(status="verified-synthetic", ...)`. There is no partial
success state and no `write`/`publish`/`to_receipt` method.

## Artifacts

| File | Contents |
| --- | --- |
| `design-and-contracts.md` | Pre-implementation correctness gate, invariants V01–V11, boundaries, dependency allowlist |
| `oracle-mapping.md` | Primary source → independent source map, bootstrap provenance, T7-F2 historical mapping |
| `mutation-matrix.md` | Adversarial mutation contract and executed evidence |
| `historical-parity.md` | Authentic D3-C archive availability and legacy oracle status |
| `verification-report.md` | Exact local commands, results, coverage, CI and disposition |

## Tests

```sh
PYTHONPATH=benchmarks python -m unittest discover \
  -s benchmarks/quervant_bench/tests -p 'test_verification_*.py' -v
```

The reference vectors are canonical JSON at
`benchmarks/quervant_bench/tests/fixtures/verification/reference-vectors.v1.json`.
