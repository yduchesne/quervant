# PR 15I-C-F — performance decision

**Decision: `F_GENERIC_BOUNDARY_REJECTED`.** Additive rollback. No release
candidate, no frozen campaign, no feature merged, pushed or published.

## 1. Decision path (frozen precedence)

| Step | Requirement | Observed | Outcome |
| --- | --- | --- | --- |
| 1 | Evidence valid (source, binaries, format, oracle, score, mode, codegen, seal) | all verifier structural checks passed in all four campaigns | valid |
| 2 | A/A stable: per-lane median drift in `[0.85, 1.15]`, ≤ 1 block outside `[0.80, 1.25]` | worst medians 1.0587 / 0.9455; ≤ 1 outlier block per lane | stable |
| 3 | C reproduction: `C/A ≥ 1.15` (10K) and `≥ 1.40` (100K) on all four low-match lanes of both unbatched campaigns | 1.3856–1.8000 | reproduced |
| 4 | G neutrality: every lane `G/A ≤ 1.10` per campaign and aggregate `≤ 1.05` | four lanes at 1.36–1.77 | **rejected** |

Decision precedence therefore yields `F_GENERIC_BOUNDARY_REJECTED`. No other
interpretation (§8.5) is authorized, and none was applied.

## 2. Why the experiment is negative

- Forcing only the shared generic collector out of line (arm G, physical
  collector present but never executed) reproduces almost the whole historical
  low-match slowdown: aggregate G/A 1.44 and 1.36 at 10K absent/rare and 1.77
  and 1.73 at 100K absent/rare.
- The physical operator is therefore **not required** to produce the
  regression; the generic boundary alone is sufficient.
- Enabling the physical operator (arm P) does not remove it: P/A stays 1.42,
  1.43, 1.73, 1.70 on those lanes, and P/G is 0.97–1.04.
- On the primary common lanes P is faster than both G and A (P/A 0.80–0.87,
  P/G 0.77–0.88), but that benefit is inseparable from an out-of-line generic
  boundary that fails the neutrality gate.

This is a measured statement about arm-to-arm latency only. No cycle, cache or
instruction-level attribution is claimed: `perf` is unavailable on this host
(`PERF_UNAVAILABLE`).

## 3. Consequences

- `F_RELEASE` was not built; the frozen 16-slot campaign was not run.
- The production tree is restored byte-for-byte to `BASE_A`
  (`6f6463cb…`): all seven historical files are back to the merged PR 15I-B
  content and `crates/quervant-core/tests/pr15i_c_physical.rs` is removed.
  `git diff 6f6463cb… -- crates/` is empty.
- The non-default `pr15ic-causal` feature, the `QUERVANT_PR15IC_CAUSAL_MODE`
  switch and the F diagnostic source remain only as historical commits
  (`658a2dde…`, `5f74bb69…`); nothing references them from the current tree.
- The frozen PR 15I-C acceptance protocol
  (`benchmarks/pr15i_c/protocol.json`, SHA-256 `54641447…`) was not modified and
  its nine acceptance criteria remain unmet.
- The PR 15I-C optimization line has now been rejected five times (in-generic
  operator, outside-dispatch operator, generic-boundary fixup, batched
  candidate, and this final boundary qualification). Further attempts on this
  axis require a new human decision; this experiment authorizes none.

## 4. What would be needed to revisit

Only a new, separately approved plan could continue. It would have to explain
why a code-placement change to the *generic* collector should be accepted
without a low-match budget, which the frozen acceptance protocol does not allow,
and it would still be bound by the nine frozen acceptance lanes.
