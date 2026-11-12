# PR 15I-D3-B-F1.2 — host readiness

## Frozen policy

- One `time.sleep(5)` settle (accepted 4,500–7,500 ms).
- Seven `/proc/stat` reads for the existing adapter/controller CPU pair; six
  1,000 ms intervals (accepted 800–1,500 ms each).
- First eight fields: `user, nice, system, idle, iowait, irq, softirq, steal`;
  iowait is non-idle; guest fields are not summed.
- `busy_permille = 1000*(total-idle)//total`, `steal_permille =
  1000*steal//total`; every interval `busy <= 250‰`, `steal <= 20‰`; lower
  median of six busy values `<= 100‰`; no retry; missing/invalid counters block.
- No engine query, no system tuning, no frequency governor change; optional
  `scaling_cur_freq` is advisory only.

## Actual observations

| Campaign | Status | adapter median (‰) | controller median (‰) | settle (ns) | observations |
|---|---|---|---:|---:|---:|---:|
| `d3bf12-base-aa-01` (control) | `READY` | 19 | 0 | 5,000,827,383 | 7 |
| `d3bf12-base-01` (paired) | `READY` | 19 | 0 | 5,001,471,482 | 7 |

The full raw tick arrays, interval metrics and per-CPU frequency advisories are
sealed in `raw/host-readiness.json` (control SHA-256 `b65f68d4…`, paired
`6b425085…`) and independently rederived by the verifier.

## Limitations

`/proc/stat` measures guest Linux CPU time, not all hypervisor/Windows
activity. A `READY` record cannot prove the host was globally idle; the frozen
contention probes and drift gates remain authoritative. If any interval,
median, duration, counter or CPU-pair check fails, the controller stops before
timing and leaves only the consumed output directory and raw status record.
