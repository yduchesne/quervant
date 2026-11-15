# BM-02 — Shared evidence utilities, provenance, safe archives and admission receipts

**Status:** implementation evidence for `v0.1-bench` milestone **BM-02 (Shared
utilities, provenance, evidence admission)**. This is **not** a benchmark run, a
Gate A–E qualification, an A/A decision or a release authorization.

## 1. Source baseline

| Item | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Branch | `dev/bm02-evidence-admission` |
| Verified up-to-date main base | `bc1409ec997d66baa2ff3f403c239a598ffd87d3` (merge of BM-01 PR #102) |
| BM-01 implementation commit | `52a6557511695ffd10ca5116451234fe58751166` (ancestor of the base) |
| Milestone | `v0.1-bench` (interim; **not** v0.2) |
| Python support | `>=3.11`; CI uses 3.12 |
| New runtime dependencies | none |

BM-01 checkpoint C1 was verified present before implementation: the six v1 schemas,
`config/{codec,identity,schemas,contracts,profiles,errors}.py`, the read-only
`inspect` CLI, the legacy registry/inventory and the 82 passing L1 tests.

## 2. What BM-02 adds

A reusable, **read-only** evidence layer beside the BM-01 contracts:

```text
benchmarks/quervant_bench/
  evidence/
    paths.py        # root-confined nofollow opens; relative-name validation
    hashing.py      # raw-byte SHA-256, file snapshots, source-file-set digest
    archives.py     # bounded streaming TAR.GZ / ZIP inspection (no extraction)
    provenance.py   # pinned Git/source/build/validator identity verification
    manifests.py    # closed internal trusted-admission-spec + admission-index v1
    admission.py    # synthetic admission pipeline and full revalidation
    receipts.py     # v1 admission receipt build/verify with complete bindings
    publication.py  # exclusive, crash-aware index + receipt publication
  host/
    capabilities.py # injected read-only capability snapshot (diagnostic only)
    readiness.py    # pure readiness diagnostics (never an authorization)
```

Plus `benchmarks/quervant_bench/tests/` — 126 deterministic L1 tests and a checked-in
synthetic golden fixture tree at
`tests/fixtures/evidence-admission/`, and this artifact set.

No public CLI verb was added. `quervant-bench run` still fails with
`BM_ACQUISITION_PROHIBITED` (exit 77) before any file, clock, process or output
access. No real timed benchmark was executed in BM-02.

## 3. Golden fixture tree

| File | Purpose |
| --- | --- |
| `trusted-spec.json` | Closed trusted-admission-spec v1; the only authority for expected evidence bytes |
| `raw/evidence.json` | Synthetic record marker; explicitly contains **no** measurements |
| `raw/environment.json` | Fixed injected `native-linux` capability snapshot |
| `raw/source-lock.json` | Pinned BM-01-base commit, tree and two tracked blob digests |
| `raw/build-lock.json` | Synthetic build identity marker only (no binary) |
| `raw/adapter-lock.json` | `synthetic-smoke` adapter identity from the BM-01 catalog |
| `raw/analysis-lock.json` | Analysis identity binding; no statistics |
| `raw/schema-registry.json` | Exactly six BM-01 v1 schema URNs and raw file digests |
| `raw/qa-roster.json` | Declared QA test roster identity; **not** a QA pass |
| `archives/synthetic.tar.gz` | Tiny two-member safe TAR.GZ |
| `archives/synthetic.zip` | Tiny two-member safe `ZIP_STORED` |

The canonical digest of `trusted-spec.json` is pinned as an independent literal in
`tests/test_evidence_admission.py` (`GOLDEN_SPEC_DIGEST`). It is never computed from
the evidence directory at runtime. Regenerating any fixture requires an explicit
fixture review.

## 4. Reproduce

```sh
python -m pip install -e ./benchmarks
python -m compileall -q benchmarks/quervant_bench
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v
python benchmarks/scripts/bm-contract-inventory.py \
  --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de \
  --check docs/pr-artifacts/bm-01/legacy-inventory.json
```

The full repository QA sequence is recorded in
[verification-report.md](verification-report.md).

## 5. Prohibitions verified

* Zero real timed acquisition: no Criterion timing, profiling, pilot, A/A or
  `quervant-bench run`.
* Zero edits to the six BM-01 v1 schemas, `config/*.py`, `cli.py` behaviour, the
  BM-01 legacy inventory, or historical `benchmarks/pr*` files.
* No new public schema ID or error code.
* No custom cryptography: SHA-256 comes from the standard-library `hashlib`.
* No archive extraction, no shell invocation for Git, no unsafe path fallback.
* Only `synthetic`/`simulated` can receive a new `admission/pass` receipt. Real
  evidence is refused; historical real evidence stays read-only.
* `ADMITTED_SYNTHETIC` / `REUSED_VERIFIED` are internal API dispositions, not
  BM-01 public outcomes and not performance qualification.

## 6. Intentional deferrals

* Real acquisition, scheduling, readiness authorization and protocol freeze:
  BM-03/BM-06.
* Statistics, independent policy verification and Gate A–E chains: BM-03…BM-06.
* Real historical T7/F2 archive replay: `EVIDENCE_UNAVAILABLE` here; BM-07…BM-09
  own migration and retirement.
* First real full-scale campaign: **BM-09 only**.

See [contracts-and-threat-model.md](contracts-and-threat-model.md),
[acceptance-matrix.md](acceptance-matrix.md) and
[legacy-parity-matrix.md](legacy-parity-matrix.md).
