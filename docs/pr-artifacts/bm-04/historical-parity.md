# BM-04 — Historical D3-C / T7 parity status

**This document never claims historical parity from a synthetic fixture.** BM-04
retires no historical path, rewrites no historical evidence, runs no benchmark and
defines no universal threshold from an experiment-specific rule.

## 1. Archive inventory

| Field | Value |
| --- | --- |
| Expected archive root | `target/pr15i-d3-c/` (repository-relative, untracked, external) |
| Observed at implementation time | directory exists but contains **zero** entries |
| Original verifier | `benchmarks/pr15i_d3_c/verify.py` (read-only, present) |
| Historical sources inspected read-only | `benchmarks/pr15i_d3_c/{analysis_v3,policy,verify}.py`, `benchmarks/pr15i_d3_c_t7/{analysis,policy}.py`, `benchmarks/pr15i_d3_c_t7_f2/{oracle,verify_policy}.py` |

## 2. Status record (§15.2)

```text
STATUS=EVIDENCE_UNAVAILABLE
HISTORICAL_SERIES_VERIFIED=NO
NUMERIC_PARITY=NOT_EXECUTED
POLICY_VERDICT_PARITY=NOT_EXECUTED
REASON=required authentic external archive not present
OWNER=BM-07/BM-09; no historical path retired by BM-04
```

Decision-matrix rule applied: **D54 — DEFER AND CONTINUE**.

* This does **not** block the BM-04 synthetic L1/L2 acceptance.
* This **does** block any claim of demonstrated historical parity.
* No archive was fabricated, rewritten or replaced, and no new benchmark was run to
  substitute for the missing evidence.

Machine-checked: `benchmarks/quervant_bench/analysis/history.py::inspect_archive`
returns exactly this record for the repository state above, and
`test_analysis_history.py` asserts the six literal lines.

## 3. Method-specific separation

BM-04 implements historical arithmetic only as a **separately named, read-only**
compatibility helper. It is never reachable from a new analysis profile.

| Surface | Historical D3-C / T7 | BM-04 v1 primary |
| --- | --- | --- |
| arm block value | integer floor mean of slot medians (`sum // n`) | exact Decimal arithmetic mean |
| estimator | ratio of arm medians over retained blocks | median of per-block normalised effects |
| estimator ID | `(historical, unnamed)` | `median-paired-ratios-v1` |
| bootstrap | `random.Random(seed)`, per-replicate `randrange(nblocks)` | `sha256-rejection-paired-block-v1` counter stream |
| bootstrap statistic | ratio of median arm-block values | median of paired-block effects |
| seed identity | `SHA256(f"{protocol_sha}|{campaign}|{lane}|{num}/{den}")[:8]` | closed canonical binding payload |
| percentile indexes (R=10000) | `249 / 9749` | `249 / 9749` (same nearest-rank rule) |
| caps | 1.25 for 100k medium/common, 1.50 otherwise | profile-declared per-lane cap, `1.5` in the fixture |
| minimum retained | 4 | protocol-declared, `max(min,2)` enforced for any CI |
| tie rule | experiment-specific P/H `0.03` | frozen `tie_relative_delta` per policy |
| memory rule | experiment-specific `2097152` | profile-declared `max_bytes` |

`benchmarks/quervant_bench/analysis/bootstrap.py::legacy_bootstrap_interval`
implements the historical variant under the identifier
`legacy-python-randrange-v1`, using a **local** `random.Random` instance only.
`analysis/history.py::legacy_t7_compatibility_calculate` wraps it together with the
floor-mean block aggregate and `ratio-of-arm-medians-v1`.

Evidence: `AN-HIST-01` asserts that the historical ratio (`2.5`) and the new default
estimator (`1.0`) genuinely differ on the same three-block dataset, that the
historical seed equals the SHA-256 prefix of the frozen string, and that the
historical lane below its retained minimum rejects. `AN-HIST-06` asserts that no
primary module imports `history`, and that `bootstrap_interval` cannot produce the
legacy algorithm.

## 4. What a future parity run must prove (BM-07 owner)

If and when an authentic archive becomes available:

1. The **original** historical verifier must pass first (never a reconstructed
   fixture).
2. Compare, per lane and campaign:
   * per-slot median and per-arm block aggregate — **exact integer equality**;
   * retained block ids and exclusion trigger-arm sets — **exact set equality**;
   * ratio, GM and 95% CI — absolute numeric parity `<= 1e-9` on the historical
     floating-point output (historical JSON used floats, so byte equality across
     different formats is meaningless);
   * historical policy statuses, selected strategies, reasons and tie flags —
     **exact string equality**, only if a trusted historical policy output and its
     required memory artifact are both present.
3. If the generic BM-04 policy profile cannot express a frozen historical
   condition, classify that case `NOT_YET_MIGRATED (BM-07)` rather than pretending
   parity.

`run_legacy_verifier(archive_root, repo_root=...)` performs step 1 as a bounded,
read-only subprocess and returns `EVIDENCE_UNAVAILABLE` when either the archive or
the verifier is absent. It never invokes `run.py`, `micro.py`, `policy.py main`,
Criterion, a profiler or any measurement entry point.

## 5. Residual risks

| Risk | Severity | Disposition |
| --- | --- | --- |
| Missing genuine D3-C external archives | Medium | Explicit `EVIDENCE_UNAVAILABLE`; owner BM-07/BM-09 |
| New default estimator differs from the historical estimator | High if conflated | Distinct identifiers, dedicated compatibility helper, `AN-MATH-04` |
| Historical T7 path may depend on interpreter/`random` behaviour | Low until cross-version QA | Never claim byte-stable parity across interpreters; CI pins Python 3.12 |
| Historical policy-verifier independence not yet migrated | Medium | BM-05/07 own it; the T7-F2 oracle is **not** copied into BM-04 |

## 6. Interpreter and toolchain recorded

```text
Python  3.12.3 (local); CI `python-contracts` uses 3.12
Rust    1.98.1 stable (CI `rust`), 1.85.0 MSRV (CI `msrv`)
```

Python 3.11 compatibility is declared (`requires-python >=3.11`) but was **not**
executed locally; no cross-version bit-equality is claimed.
