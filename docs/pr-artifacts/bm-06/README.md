# BM-06 — Gate coordinator, QA receipts, synthetic qualification and attestation

Status: **implementation and local synthetic correctness gates complete; remote CI
unverified; independent review pending.** This directory records the design freeze,
the closed receipt/manifest contract, the QA and reuse/invalidation matrix and the
final local verification evidence for the BM-06 pull request.

## What BM-06 is

BM-06 adds one dependency-bound, independently checkable **A→B→C→D→E** qualification
chain for a sealed **synthetic** BM-03 run:

```text
Gate A  sealed BM-03 structural replay + canonical sealed-file index
Gate B  existing BM-04 analyze_synthetic_run (analysis + policy)
Gate C  existing BM-05 verify_synthetic_run (independent assessment)
Gate F  pinned framework QA evidence        \
Gate S  pinned source QA evidence            > mandatory upstream dependencies of D
Gate D  acceptance summary + receipt        /
Gate E  freeze snapshot → attestation receipt → manifest (completion marker last)
```

A published `simulated` qualification refers to exactly one verified set of sealed
source bytes, frozen analysis/policy inputs, verifier/source identities, exact QA
rosters and completed gate dependencies. Any covered byte change prevents reuse or
invalidates acceptance. A `pass` string alone is never sufficient.

## What BM-06 is **not**

- Not a real benchmark run, not real timing, not host readiness, not A/A.
- Not an official qualification and not a performance conclusion. Candidate
  `INCONCLUSIVE` or baseline-only policy decisions remain legitimate *framework*
  qualifications; they are never relabelled as a speed win.
- Not a real CI authentication mechanism. The checked-in framework/source QA
  records are **simulated L2 assertions of the qualification mechanism**: they do
  not prove that any named program actually ran, that CI passed or that the named
  RustFS acceptance executed. BM-09 owns official trust/authorization semantics.
- Not a CLI feature. `validate`/`analyze`/`verify`/`accept`/`report` remain
  `BM_NOT_IMPLEMENTED`; `quervant-bench run` still exits 77. BM-07 may activate the
  standard CLI over these library services.

## Public surface

```python
from quervant_bench.qualification import (
    QualificationResult,
    load_qualified_synthetic_run,
    qualify_synthetic_run,
)
```

Both entry points are keyword-only. `load_qualified_synthetic_run` never derives,
runs adapters or writes: it replays/re-hashes sealed evidence and rechecks every
committed receipt and artifact relationship. `qualify_synthetic_run` checks for a
committed destination **before** deriving and returns `REUSED_VERIFIED` only after
all current anchors match.

The qualification profile is checked in at
`benchmarks/quervant_bench/qualification/profiles/synthetic-framework.v1.json` and
is packaged via `benchmarks/pyproject.toml` package data.

## Artifacts

| File | Contents |
| --- | --- |
| `design-and-contracts.md` | Pre-implementation correctness gate, invariants Q01–Q16, record shapes, gate graph, failure boundaries, false-PASS mutations |
| `receipt-and-manifest-contract.md` | Exact seven-gate receipt contract, 15-file inventory, freeze/attestation/manifest algebra and digest rules |
| `qa-and-reuse-matrix.md` | Framework/source QA rosters, per-check evidence binding, trust anchors, reuse key and invalidation matrix |
| `verification-report.md` | Exact local commands, results, counts, coverage, decision-matrix actions, residual risks and disposition |

## Tests

```sh
PYTHONPATH=benchmarks python -m unittest discover \
  -s benchmarks/quervant_bench/tests -p 'test_qualification_*.py' -v
```

Pinned synthetic fixtures live at
`benchmarks/quervant_bench/tests/fixtures/qualification/` (QA evidence, per-check
records, `trust-anchors.v1.json`). The `*.py`, workflow, `pyproject.toml`,
`test-scripts.sh` and BM-01 schema source roster is deliberately excluded from the
trust fixture to avoid an impossible digest self-reference; the roster digest is an
independently reviewed literal that must be re-frozen if any covered source byte
changes.
