# PR 14 — P4 benchmark report (`pr14_p4_v1`)

## Scope
Storage-mode comparison: Quervant local `FsDirectory` vs Quervant real RustFS.
Not a cross-engine comparison, not a production p99 estimate, no speedup claim.

## Provenance
- Source SHA (all three trials): `ab9b2d7da066ec80190dcee70a8cebfd81481b80`
  (runner commit; trial JSONs record the same SHA).
- Workload: `benchmarks/workloads/pr14_p4_v1.md`.
- Corpus: 20,000 deterministic documents, 3 immutable segments.
- Corpus digest: `80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768`.
- RustFS: pinned `rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`,
  endpoint `http://127.0.0.1:9000` (rootless Podman).
- Toolchain: stable `1.98.1`; Linux native filesystem.
- Warmups 3, measured samples 20 per configuration per trial.
- All three trials: `qualified=true`, `idle_confirmed=true`,
  `contention=clear`, `dirty=false`, distinct trial IDs `t1/t2/t3`.
- Validator: `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` PASS
  (rejects wrong count/digest, missing/duplicate workload, <3 trials, dirty tree,
  missing idle, contention present/unknown, missing measurements, <20 samples,
  <3 warmups), and the three trial reports PASS.
- Raw CSVs: `target/pr14-p4/pr14-p4-{t1,t2,t3}.csv` (untracked).
- Sanitized trial manifests: `benchmarks/reports/pr14-p4-{t1,t2,t3}.json`.

## Correctness gate
Every trial asserted the independent expected results before timing:
W01/W02 10,000; W03 2,000; W04 6,000; W05 2,500; W06 4 groups × 5,000;
W07 ordered S/F/S with aggregation. Timing was aborted on any mismatch.

## Aggregated measurements (60 samples per row: 3 trials × 20)
Values are microseconds; p99 is a sample quantile, not an SLO.

| Lane | Workload | n | p50 | p95 | p99 |
|---|---|---|---|---|---|
| local-cold | W09 (open+first query) | 60 | 2,791,865 | 3,256,871 | 3,286,073 |
| local-warm | W02 mixed | 60 | 1,346,260 | 1,446,588 | 1,456,796 |
| local-warm | W03 JSON+sort+projection | 60 | 1,183,726 | 1,242,747 | 1,253,266 |
| local-warm | W04 geo+distance sort | 60 | 1,185,522 | 1,344,568 | 1,347,164 |
| local-warm | W05 IP+time | 60 | 1,194,371 | 1,243,851 | 1,248,136 |
| local-warm | W06 aggregation | 60 | 1,412,135 | 1,460,267 | 1,461,621 |
| local-warm | W07 3-slot batch | 60 | 2,668,916 | 2,885,063 | 2,892,061 |
| remote-cold | W01 (open+first query) | 60 | 3,366,827 | 3,736,412 | 4,112,644 |
| remote-warm | W02 mixed | 60 | 1,355,753 | 1,405,939 | 1,425,736 |
| remote-warm | W03 JSON+sort+projection | 60 | 1,185,093 | 1,215,781 | 1,258,194 |
| remote-warm | W04 geo+distance sort | 60 | 1,159,450 | 1,203,056 | 1,218,657 |
| remote-warm | W05 IP+time | 60 | 1,157,692 | 1,174,207 | 1,209,331 |
| remote-warm | W06 aggregation | 60 | 1,367,564 | 1,409,101 | 1,437,548 |
| remote-warm | W07 3-slot batch | 60 | 2,631,199 | 2,673,779 | 2,686,434 |

## Observations and limitations
- Remote warm query lanes are within the observed variability of the local warm
  lanes in this environment; cold RustFS open adds the expected segment
  materialization cost. No superiority claim is made.
- Trial-to-trial variability is visible (for example remote-cold p99
  3.50–5.90 s in single-trial summaries); only the aggregated 60-sample
  quantiles are reported above.
- **W08 (forced eviction → reload → query) is not measured.** The cache
  admission path rejects a capacity that cannot retain the currently pinned set
  instead of evicting it; no explicit eviction API is exposed to this runner.
  This is a documented gap, not a pass.
- Cold/warm and local/remote samples are never pooled under one label.
- Dataset generation, indexing, commit, opening outside the named W09/W01 lanes,
  and oracle computation are outside the timed regions.
- No Lucene/Tantivy comparison was run; PR 15 owns that.

## Status
B01 (oracle gate), B02 (negative validator self-test), B03 (three independently
qualified trials for W01–W07/W09) and B04 (dirty/contended/unknown rejection)
executed. **W08 is BLOCKED by the architectural STOP** documented in
[p4-w08-stop.md](p4-w08-stop.md): `RemoteIndex` pins all segments for the whole
index lifetime and exposes no cache statistics or per-segment unpin. B03 is
therefore incomplete and **P4 is NOT ACCEPTED**.
