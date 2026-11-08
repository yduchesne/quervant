# PR 15I-B P1 — historical PR 15G-E rare-lane regression attribution

**Classification:** `HISTORICAL_RARE_REGRESSION_ATTRIBUTED` (rule **H-E3**).

## Pinned historical sources

| Arm | Commit | Meaning |
|---|---|---|
| A | `ca065a212987284144d8901aa5c54de093d6dbfc` | accepted source before persisted-offset experiment |
| E | `62d35c262fa667673ee6d8701ca9ef75daf17a53` | rejected persistent-offset candidate |

Both were built read-only in detached worktrees with the frozen PR15D adapter
(`cargo build --release --locked`).

## Source-level mechanism (not inferred from timing)

In `62d35c2`:

- `segment/reader.rs::stored_docs_selected` certifies the persisted directory
  once, then on **every later certified query** calls
  `persisted_directory_view(...)` (call site line **865**).
- `persisted_directory_view` calls
  `segment/offset_directory.rs::inspect_offset_directory`.
- `inspect_offset_directory` loops `while index < entries` (line **214**) and
  reads one `u64` boundary per iteration (line **217**), with
  `entries = doc_count + 1`.

Deterministic work therefore includes `doc_count + 1` boundary reads per
certified selected query: **10,001** for 10K and **100,001** for 100K, even when
the query requests only K documents. The new v2 design must not repeat this:
after a valid certificate, only the touched 128-document compressed blocks may
be inflated, and the validated directory is retained in a metered vector.

Recorded source hashes are in `target/pr15i-b/diagnose/run-01/diagnosis.json`
(`attribution.sha256`).

## Paired timing corroboration

Benchmark-only diagnostic (`benchmarks/pr15i_b/diagnose_e.py`), frozen PR15D
corpus/oracle, 4 balanced ABBA blocks × 5 warmups × 20 samples per lane,
contention probes clear before/after:

| Lane | E/A block ratios (median of four) |
|---|---|
| 10K rare/k100 | **3.88** (historical 3.12–3.87) |
| 100K rare/k100 | **6.69** (historical 6.43–6.86) |
| 100K medium/k100 | 1.04 |

The rare-lane regression scales with `N` and is consistent with the per-query
O(N) directory scan; medium does not regress. Historical numbers remain
diagnostic only and are never mixed into PR 15I-B acceptance ratios.

## Limitations

- No dynamic Rust counter was injected into the historical tree; the work count
  is derived from the pinned source loop and call chain, as permitted by the
  plan.
- The diagnostic evidence is stored under ignored
  `target/pr15i-b/diagnose/run-01/` (sealed `diagnosis.json`).
