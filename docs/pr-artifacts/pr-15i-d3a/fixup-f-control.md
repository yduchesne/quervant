# PR 15I-D3-A-F control

Status: `d3af-base-aa-01` **D3A_CONTROL_QUALIFIED** (official T0c).

- 16 slots, 2,880 timed samples, 720 warmups, 32 clear contention probes,
  2 index builds, independent oracle checks and sealed host-quiescence evidence.
- All hard `[0.67, 1.50]` bounds and the `[0.85, 1.15]` median gate passed.
- One soft outlier was tolerated under the prospectively frozen v2 policy:
  `pr15d_v1/10000/absent/k100` block 1 = `1.2507991338420292`
  (`CONTROL_SOFT_OUTLIER`, expected `[0.80, 1.25]`).
- The independent verifier recomputed the tolerated metadata from sealed slots
  and agreed; no historical T0/T0b control was reused.
- Archive: `d3af-base-aa-01.tar.gz`, SHA-256
  `3ba3c4e3e765eed51987b6c6de7021acb8c4ea50ef96582190ea498a19ce4a2c`,
  `SAME_DISK_ONLY`.
