# PR 15F — P0 optimized query, reopen and physical-layout attribution

This directory contains **benchmark-only** measurement tooling for P0 of
[`docs/PERF_OPTIMIZATION_PLAN.md`](../../docs/PERF_OPTIMIZATION_PLAN.md). It does
not implement, schedule or approve any P1–P5 optimization. Production crates,
on-disk formats, query planning, scoring, writer/commit/recovery semantics,
resource limits and public search APIs are unchanged.

## What is measured

1. **Query CPU (nine mandatory warm lanes).** The frozen PR 15D Quervant adapter
   runs against the frozen `pr15d_v1` corpus while `perf record -g
   --call-graph dwarf` samples the adapter process. Every warmup and every
   profiled reply is compared with the independent PR 15D oracle. An adapter or
   oracle mismatch stops the query campaign; it is never reclassified.
2. **Reopen timing and CPU.** A new standalone public-API probe
   (`reopen_probe/`) times `FsDirectory::open`, `Index::open_with_limits`,
   `Index::snapshot` and their checked sums for one iteration, 128 iterations
   (10K) or 64 iterations (100K). The campaign launches 42 independent
   single-shot processes (21 per corpus size) in a fixed alternating rotation and
   two separate CPU-sampled loop processes.
3. **Read-only physical layout.** The probe enumerates regular files under the
   prepared index, verifies each container with the public
   `segment::parse_container`, and attributes exact bytes to every public
   `SectionKind`, manifest, mutation-state sidecar and non-container metadata.
   Totals must reconcile exactly; the index bytes are hashed before and after.
4. **Optional allocation captures.** `heaptrack` is attempted only for
   `100K/rare/K100` and `100K/common/K100`. Missing or unusable heaptrack is
   recorded as `ALLOCATION_NOT_MEASURED`, never fabricated.

## Fixed query lanes

| Lane | Seconds |
|---|---:|
| 10K/{absent,rare,medium,common}/K100 | 20 each |
| 100K/{absent,rare,medium}/K100 | 30 each |
| 100K/common/K100 | 60 |
| 100K/common/K10 | 60 |

Five warmups precede each profiled window. CPU captures require at least 1,000
samples and zero lost samples. Every timed capture performs the real PR 15D
before/after `check-pr07-contention.py` probe and requires `clear` both times.
The maintenance plan's assumed-idle approval is recorded as
`authorization_basis=operator_approved_assumed_idle_for_pr15f`; it is
authorization, **not** a host observation. No PR 15E attestation is created or
synthesized.

## Commands

Run from the repository root, after the benchmark-only source is committed and
`target/pr15e/<prepared-run>` exists with the same `HEAD`:

```bash
ROOT="$(pwd -P)"
SRC="$(git rev-parse HEAD)"
SHORT="$(git rev-parse --short=8 HEAD)"
PREP="$ROOT/target/pr15e/pr15f-prepared-$SHORT-01"
OUT="$ROOT/target/pr15f/run-01"

python3 benchmarks/pr15e/profile.py prepare --out "$PREP"
python3 benchmarks/pr15f/run.py prepare --prepared-run "$PREP" --out "$OUT"
python3 benchmarks/pr15f/run.py query-perf --prepared-run "$PREP" --out "$OUT" --idle-confirmed
python3 benchmarks/pr15f/run.py reopen-single --prepared-run "$PREP" --out "$OUT" --idle-confirmed
python3 benchmarks/pr15f/run.py reopen-perf --prepared-run "$PREP" --out "$OUT" --idle-confirmed
python3 benchmarks/pr15f/run.py inventory --prepared-run "$PREP" --out "$OUT"
python3 benchmarks/pr15f/run.py allocation --prepared-run "$PREP" --out "$OUT" --idle-confirmed
python3 benchmarks/pr15f/verify.py --prepared-run "$PREP" --run "$OUT"
python3 benchmarks/pr15f/attribution.py --run "$OUT" --out "$OUT/analysis.json"
python3 benchmarks/pr15f/verify.py --prepared-run "$PREP" --run "$OUT" \
  --analysis "$OUT/analysis.json" --publish-sanitized
```

`--publish-sanitized` is accepted only when every mandatory gate is qualified.
Otherwise use `--publish-partial`, which writes an explicitly `PARTIAL` report
with every absent category recorded. Raw `perf.data`, heaptrack output, adapter
PIDs, command lines, absolute paths and contentious probe logs stay under the
ignored `target/` tree and are never published.

## Tests

```bash
python3 -m unittest discover -s benchmarks/pr15f -p 'test_*.py' -v
cargo +1.85.0 test --locked --manifest-path benchmarks/pr15f/reopen_probe/Cargo.toml
cargo test --locked --manifest-path benchmarks/pr15f/reopen_probe/Cargo.toml
```

Unit tests use injected clocks, fake profiler transports and temporary
directories. They never launch a profiler and never write into a prepared index.
The real `FsDirectory`/public-engine vertical slice is the campaign itself
(`prepare → captures → verify → attribution → publication`).

## Evidence statuses

The published summary uses these campaign labels: `QUALIFIED`, `PARTIAL`,
`BLOCKED`, `ALLOCATION_NOT_MEASURED`, and the report label
`P0_QUALIFIED_REVIEW_READY`, `P0_QUALIFIED_ALLOCATION_NOT_MEASURED`,
`P0_PARTIAL_EVIDENCE` or `P0_BLOCKED_ENVIRONMENT`. A missing or failed lane is
never silently dropped or retried inside the same campaign. Inclusive CPU shares
are reported separately from exclusive ownership and are never summed.
