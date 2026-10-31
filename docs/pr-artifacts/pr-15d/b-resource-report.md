# PR 15D-B — supplemental CPU/RSS report

**Status: `MEASURED` for the new campaign.** These are *separate process-level
diagnostics*. They never enter `engine_ns`, the relative latency ratios or the
20-sample series. Allocations remain `NOT_MEASURED` and are not implied by peak
RSS.

| Item | Value |
|---|---|
| Run id | `20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc` |
| Measured source SHA | `40a9c26a57aa23640904075e77be956ee52718bc` |
| Probe observation HEAD | `88d25e050630ae746df55efffc39d7ecfa66f7e3` (tooling-only; `measured_path_drift: []`) |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Host fingerprint | `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f` (WSL2 kernel 6.18.33.2, ext4) |
| Operator attestation | host **MSI**, window `2026-10-31T00:50Z`–`02:50Z` |
| Probe window | `2026-10-31T01:38:52Z` → `01:40:32Z` (100 s, inside the attested window) |
| Clock resolution | `SC_CLK_TCK = 100` (10 ms per tick) |
| Probes | 18 = 3 rounds × 3 engines × {N=10 000 `rare`/K=10, N=100 000 `medium`/K=10} |
| Round order | `q→t→l`, `t→l→q`, `l→q→t`; each round uses that trial's already-built index |
| Contention | `clear` before **and** after all 18 probes (36/36 samples) |
| Stop reason | `cpu_target` for all 18 probes (≥500 ms process CPU) |
| Trial evidence | nine manifests hashed before/after; unchanged (no `X41` trip) |

## CPU per request (process CPU, ns) — 3 independent probe processes

| Engine | N | min | median | max |
|---|---:|---:|---:|---:|
| quervant | 10 000 | 7 352 941 | 7 352 941 | 7 352 941 |
| quervant | 100 000 | 600 000 000 | 610 000 000 | 610 000 000 |
| tantivy | 10 000 | 41 155 | 41 806 | 42 247 |
| tantivy | 100 000 | 205 002 | 205 930 | 206 782 |
| lucene | 10 000 | 1 012 145 | 1 103 752 | 1 199 040 |
| lucene | 100 000 | 5 000 000 | 5 102 040 | 5 208 333 |

## Peak RSS (`VmHWM`, bytes) — 3 independent probe processes

| Engine | N | min | median | max |
|---|---:|---:|---:|---:|
| quervant | 10 000 | 15 425 536 | 15 466 496 | 15 507 456 |
| quervant | 100 000 | 109 621 248 | 109 645 824 | 109 658 112 |
| tantivy | 10 000 | 6 168 576 | 6 197 248 | 6 336 512 |
| tantivy | 100 000 | 6 979 584 | 6 995 968 | 7 090 176 |
| lucene | 10 000 | 96 149 504 | 96 972 800 | 98 091 008 |
| lucene | 100 000 | 116 330 496 | 117 297 152 | 117 878 784 |

## Interpretation limits (binding)

- **Granularity.** `SC_CLK_TCK = 100` means each tick is 10 ms, so a
  CPU-per-request figure is meaningful only when many requests fit in a tick.
  Quervant at N=100 000 is the extreme case: one query exceeds the 500 ms CPU
  target, so its CPU/request value (≈0.6 s) is essentially single-request
  granularity and must not be read as a finely resolved per-query cost.
- **Process vs query.** These figures include JVM/allocator/RSS behaviour,
  syscalls and index reads for the whole process — Lucene's numbers include JVM
  warm-up and GC effects that `engine_ns` deliberately excludes.
- **Not allocations.** `VmHWM` is peak resident set size. Allocation counts and
  bytes remain `NOT_MEASURED`; no heap-only metric is substituted for RSS.
- **Virtualisation.** The host is WSL2 on a mobile 6-core/12-thread CPU; scheduler
  and frequency behaviour are part of the environment and are not normalized.
- **Identity.** Each probe proved the observed PID was the real engine process;
  for Lucene the install launcher `exec`s `java` into the same PID (verified with
  a bounded wait), and no descendant summing is performed.

## Reproduction

```bash
python3 benchmarks/pr15d/harness/resource_probe.py \
  --run target/pr15d/runs/20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc \
  --out target/pr15d/runs/<id>/resource-probe.json \
  --idle-confirmed        # only inside a human-attested window
```

A missing/unreadable `/proc`, a non-`exec`ing launcher, a shell parent, a
disappeared PID, sub-tick resolution or contention all fail closed
(`BLOCKED_ENVIRONMENT`, `X32_PID_IDENTITY`, `X36_CONTENTION`,
`BELOW_RESOLUTION`) instead of producing a fabricated number.
