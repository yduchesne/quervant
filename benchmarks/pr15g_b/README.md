# PR 15G-B — validated STORED/DOC_KEYS offsets targeted benchmark

This directory contains the Quervant-only before/after runner for PR 15G-B
(validated random-access STORED/DOC_KEYS offsets on the shared PR 15G branch).
It measures the frozen PR15D Quervant adapter on the same nine warm lanes:

| N | classes | K |
|---|---|---|
| 10K | absent, rare, medium, common | 100 |
| 100K | absent, rare, medium, common | 100 |
| 100K | common | 10 |

## Fixed measurement design

- Arm A is pinned to the verified shared-branch pre-B tip
  `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c` (PR 15G-A complete, no merge to
  `main` required).
- Arm B must be a distinct committed descendant on the same shared branch
  containing the B offset implementation.
- Corpus generation, index building, adapter source, oracle checks, five
  warmups and twenty timed samples come from the frozen, read-only PR15D /
  PR15E-B1 modules.
- Three independent trials per arm are required. Every trial is bracketed by
  host-contention probes; `busy` or `unknown` disqualifies the trial.
- Both arms must share a host fingerprint and corpus manifest digest, and the
  measured trees must be clean committed worktrees on a native filesystem.
- Verdicts use sign consistency only. No speedup threshold is invented.
- GB-P01 and GB-P02 require `B_FASTER` on 100K and 10K rare/K100; GB-P03
  requires no other lane `A_FASTER`.

## Authorization

The operator has authorized the prescribed campaign under an assumed-idle
instruction. The runner still requires `--idle-confirmed` and still records the
real before/between/after contention probes. If a probe is `busy` or `unknown`,
the affected trial/campaign is unqualified; the assumption is not a substitute
for a clear probe.

```sh
python3 benchmarks/pr15g_b/run.py \
  --source-tree /ABS/CLEAN/WORKTREE \
  --out /ABS/CHECKOUT/target/pr15g-b/qualified-pair-01 \
  --idle-confirmed
```

`--out` must be strictly beneath `<checkout>/target/pr15g-b/`. Every invocation
allocates an exclusive `runs/<source-sha>/<UTC-microsecond>/` directory and never
overwrites existing evidence. Raw captures stay under ignored `target/pr15g-b/`.

## Published comparison

Once two source runs exist, the runner writes sanitized `comparison.json` and
`comparison.md` at the stage root. They contain source SHAs, frozen input
digests, per-lane medians, all paired trial ratios, verdicts, GB-P gate results,
contention qualification and limitations. Host names, users, PIDs, command
lines, absolute paths and raw trial filenames are rejected by the sanitizer.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15g_b -p 'test_*.py' -v
```

The tests use synthetic summaries and temporary Git repositories; they never
build an adapter, generate a 100K corpus or time a query.

## Status

Implementation/correctness evidence is recorded in
`docs/pr-artifacts/pr-15g-b/`. The authorized nine-lane campaign is run after
the B implementation commit is pinned; see `performance-qualification.md`.
