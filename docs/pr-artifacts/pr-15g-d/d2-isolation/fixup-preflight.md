# D2 isolation harness fixup preflight

**Starting HEAD:** `317d60d73ccbdc6b9df8843aa91eca36a2f6b318`
**Branch:** `dev/pr15g-a-retained-column-geometry`
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**X:** `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6` (local detached worktree)
**Historical D1:** `1d2a6b0f08bf68994699e1f3e37f163347492cd1`
**Historical D1+D2:** `dae598758a433ecdc0d9af37e15194e948bbc788`
**Prior campaign:** opaque `d2-only-first-qualified`, preserved read-only

## Identity and protection

- Branch and HEAD matched the plan on entry; tree clean.
- `main` is an ancestor of the shared branch.
- A/X worktrees exist, are detached, clean and pinned.
- X is a direct child of A and changes exactly the two search files.
- The original blocked campaign and all historical reports remain untouched.

## Defects covered

1. Source identity was partially proven only by an ignored helper. The tracked
   controller will now compare exact per-file added/removed byte streams against
   historical D1→D2.
2. Drift-blocked acquisition had no verifiable final inventory because the seal
   was written after drift enforcement. The new v2 seal covers exactly 18 raw
   files and is written before drift classification.
3. `validate_raw` trusted stored `summary_ns`. It will now call frozen
   `pr15d_run.summarize()` and require all six fields to match the 20 samples.

## Counterexamples considered

- Relocated unchanged test context: allowed by exact edit streams; patch-ID is
  diagnostic only.
- One changed byte in the D2 `true` branch, reordered additions, an extra test
  assertion, or a changed deletion stream: rejected.
- Arithmetic median `10.5` for samples 1..20: rejected; frozen nearest-rank
  median is `10`.
- Missing/extra seal key, altered slot byte, legacy v1 campaign, both report
  types present, or a drifted campaign with a performance gate: rejected.
- Incomplete acquisition or invalid probe: no seal and no performance report.

Contradictions found in source: none. Frozen `summarize` is nearest-rank and
returns `count, median, p95, p99, min, max`.
