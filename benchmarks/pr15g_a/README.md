# PR 15G-A — retained column geometry targeted benchmark

This directory contains the Quervant-only before/after runner for PR 15G-A
(retained immutable column geometry). It measures the frozen PR15D Quervant
adapter on exactly nine warm lanes:

| N | classes | K |
|---|---|---|
| 10K | absent, rare, medium, common | 100 |
| 100K | absent, rare, medium, common | 100 |
| 100K | common | 10 |

## Fixed measurement design

- Arm A is pinned to merged `main` `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc`
  (PR 15F baseline). Arm B must be a distinct committed descendant.
- Corpus generation, index building, adapter source, oracle checks, five
  warmups and twenty timed samples come from the frozen, read-only PR15D /
  PR15E-B1 modules. This runner does not modify them.
- Three independent trials per arm are required. Every trial is bracketed by
  real host-contention probes; `busy` or `unknown` disqualifies the trial.
- Both arms must share a host fingerprint and corpus manifest digest, and the
  measured trees must be clean, committed worktrees on a native filesystem.
- Verdicts use sign consistency only (`B_FASTER`, `A_FASTER`,
  `INCONCLUSIVE`). No speedup threshold is invented.

## Authorization

A real operator must explicitly confirm an idle measurement window:

```sh
python3 benchmarks/pr15g_a/run.py \
  --source-tree /ABS/CLEAN/WORKTREE \
  --out /ABS/CHECKOUT/target/pr15g-a/qualified-pair-01 \
  --idle-confirmed
```

Without `--idle-confirmed` the runner exits 3 with `PERF_BLOCKED_OPERATOR`
before creating an index or starting any benchmark subprocess. The coding agent
must not synthesize this flag.

`--out` must be strictly beneath `<checkout>/target/pr15g-a/` (a realpath and
common-path check rejects symlink escapes, the stage root itself, and any path
inside tracked source). Every invocation allocates an exclusive
`runs/<source-sha>/<UTC-microsecond>/` directory and never overwrites existing
evidence. Raw captures stay under the git-ignored `target/pr15g-a/`.

## Published comparison

Once two source runs exist, the runner writes sanitized `comparison.json` and
`comparison.md` at the stage root. They contain only source SHAs, frozen input
digests, per-lane median-of-trial-medians, all paired trial ratios, verdicts,
contention qualification and limitations. Host names, users, PIDs, command
lines, absolute paths, raw trial filenames and attestation text are rejected by
the report sanitizer. Published reports are immutable; a changed source needs a
new stage root and a reviewer decision.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15g_a -p 'test_*.py' -v
```

The tests use synthetic summaries and temporary Git repositories; they never
build an adapter, generate a 100K corpus or time a query.

## Status

Local performance acceptance (P01–P04) is **BLOCKED_OPERATOR** until a genuine
operator-authorized idle campaign is executed. See
`docs/pr-artifacts/pr-15g-a/qualification.md`.
