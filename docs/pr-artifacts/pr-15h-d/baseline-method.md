# PR 15H-D — measurement method

## Campaign

- Six frozen PR15D warm lanes, in the order defined by `benchmarks/pr15h_d`.
- Baseline: 3 trials × (5 warmups + 20 samples) per lane = 360 samples,
  90 warmups, 6 clear before/after probes, 18 oracle checks.
- Paired: four mirrored blocks `A,B / B,A / B,A / A,B` = 8 slots; 960 samples,
  240 warmups, 16 clear probes, 48 oracle checks.
- Same host/WSL2 native ext4, frozen corpus, byte-identical query-only index
  digests, independent PR15D oracle.

## Statistic

Per lane/block `d = median(A 20 samples) − median(B 20 samples)` in ns;
positive means the D candidate is faster. Four deltas per lane:

- **gating:** conventional even-n arithmetic median `0.5*(sorted(d)[1]+sorted(d)[2])`;
- **supplementary:** lower median `sorted(d)[1]`.

The lower median is published but is not used for D gating.

## Frozen gates

- ≥2 of D-P1/D-P2/D-P3 conventional median `>= +2.000 ms` with ≥3/4 deltas `>0`.
- Remaining primary conventional median `>= -0.750 ms`, no delta `< -2.000 ms`.
- D-G1 `>= -0.750 ms`; D-G2/D-G3 `>= -0.250 ms`; no guard delta `< -1.000 ms`.
- Invalid oracle/corpus/index/host/provenance/contention ⇒ `MEASUREMENT_INVALID`.

A valid campaign that misses any gate is `PERFORMANCE_REJECTED_SAFE_ROLLBACK`
with the candidate reverted byte-for-byte; no threshold or lane changes.
