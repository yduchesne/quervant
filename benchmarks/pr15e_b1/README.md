# PR 15E-B1 — targeted Quervant benchmark runner

`run_targeted.py` is a deliberately narrow, Quervant-only measurement driver for
the two approved PR 15E-B1 optimizations:

| Stage | Purpose | Arm A | Arm B |
|---|---|---|---|
| `b1a` | direct effective-live-bitmap iteration | original `main` | B1a commit |
| `b1b` | binary search over decoded sorted term postings | B1a commit | B1b commit |
| `final` | compact regression control | original `main` | final B1 commit |
| `p3` | PR 15E Phase 3 selective stored materialization | accepted B1 `5553c3b` | Phase 3 commit (strict descendant) |

It is **not** a replacement for the frozen PR15D comparative qualification and it
never builds, runs or reads the Lucene or Tantivy adapters. The full PR15D matrix
(32 lanes × 3 engines × `process_cold`/`warm`) is explicitly out of scope: B1 does
not change indexing, segment encoding, remote retrieval, protocol serialization,
the pure lexical evaluator or stored projection.

## What is reused unmodified

The runner imports the frozen PR15D modules rather than re-implementing protocol
semantics, durations, corpus bytes or oracle outcomes:

* `benchmarks/pr15d/harness/run.py` — `lane_descriptors`, `build_index`,
  `measure_lane`, `read_adapter_metadata`, `check_contention`,
  `validate_query_response`, `summarize`, `AdapterProcess`, `write_json`,
  `host_fingerprint`, `collect_environment`, `NATIVE_FILESYSTEMS`.
* `benchmarks/pr15d/corpus/oracle.py` — `expected`, `load_and_verify`, frozen
  corpus filenames and N/K/class matrices.
* `benchmarks/pr15d/corpus/generate.py` — the deterministic corpus generator.

The runner pins the SHA-256 of the frozen spec, oracle, generator, harness and the
Quervant adapter sources and refuses to run (`X30_FROZEN_DRIFT`) if any of them
drift in either the tooling checkout or the measured source tree.

## Fixed lane matrix (`regime=warm`, 5 warmups + 20 measured samples per lane)

| Stage | Lanes |
|---|---|
| `b1a` | `n100000/{absent,rare,medium,common}/k100`, `n10000/{absent,common}/k100` |
| `b1b` | `n100000/{medium,common,absent,rare}/k100`, `n10000/common/k100` |
| `final` | `n10000/{absent,rare,medium,common}/k100`, `n100000/{absent,rare,medium,common}/k100`, `n100000/common/k10` |
| `p3` | `n100000/rare/k100` (primary), `n100000/rare/k10`, `n10000/rare/k100`, `n100000/medium/k100`, `n100000/common/k100`, `n100000/absent/k100`, `n10000/common/k100` |

The `p3` stage is pinned: arm A must be exactly `5553c3bba268b9b268b51117e54eb256772ec19c`
(the accepted B1 source) and arm B must be one of its descendants. Reversed, unrelated
or duplicate arms are refused (`X37_INCOMPARABLE`), and its report is labeled
`PR 15E Phase 3` with a `phase: "phase3"` discriminator. The `b1a`/`b1b`/`final`
stage definitions, labels and report shape are unchanged.

## Usage

```sh
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /abs/clean/git/worktree \
  --stage b1a \
  --out /abs/checkout/target/pr15e-b1/b1a \
  --idle-confirmed
```

* `--source-tree` must be an absolute, clean (no uncommitted tracked changes) Git
  worktree root; the runner records both its SHA and its commit time.
* `--out` is the **stage root** and must live under the gitignored
  `<checkout>/target/pr15e-b1/`. Every invocation creates a unique, never
  overwritten run directory `runs/<source-sha>/<UTC-run-id>/`.
* `--idle-confirmed` is a **real operator action**. Without it the runner exits
  `3` (`PERF_BLOCKED_OPERATOR`) before touching the filesystem; the coding agent
  must never pass it on the operator's behalf.

### Operator sequence for one stage

1. `b1a`: measure original `main`, then measure the B1a commit. The second run
   publishes `<out>/comparison.json` and `<out>/comparison.md` automatically.
2. `b1b`: measure the B1a commit, then the B1b commit.
3. `final`: measure original `main`, then the final B1 commit.

Each source tree must be a separate clean worktree (one per measured commit, with
its own Cargo target directory). Samples from different hosts are never compared:
the runner records a host fingerprint and refuses mismatched pairs.

### Output layout

```
<stage-root>/
  runs/<source-sha>/<run-id>/
    idle-confirmation.json      operator flag, host and UTC record
    setup.json                  source/build/corpus/index/environment identity
    build.log                   adapter build output (untimed)
    corpus/                     frozen TSV corpora + manifest
    indexes/n<N>/               immutable local indexes, digest-verified per trial
    contention/trial{1..3}-{before,after}.json
    trial-{1..3}.json           all 20 raw engine_ns samples per lane
    summary.json                per-lane trial medians, dispersion, hits
  comparison.json               after exactly two source runs
  comparison.md
```

Raw sample data and build logs stay under `target/` (gitignored, private). Only a
sanitized summary may be copied into `docs/pr-artifacts/pr-15e-b1/`.

## Fail-closed rules

| Rule | Refusal |
|---|---|
| `X19_PATH_ESCAPE` | `--out` outside `<checkout>/target/pr15e-b1/` |
| `X27_SOURCE` | relative/non-Git/dirty source tree, unreadable SHA |
| `X30_FROZEN_DRIFT` | frozen PR15D artefact or adapter source hash mismatch |
| `X31_FILESYSTEM` | non-native filesystem for output/index |
| `X32_STAGE` | unknown stage, unknown frozen lane, duplicate lane |
| `X33_ADAPTER_BUILD` / `X33_SAMPLE_COUNT` | adapter build failure, wrong sample count |
| `X34_CONTENTION` | non-`clear` probe before/after any trial (never treated as clear) |
| `X35_TRIAL_COUNT` / `X36_LANE_SET` | not exactly 3 trials / differing lane sets |
| `X37_INCOMPARABLE` | corpus, host, lane set, trial count, source SHA or contention mismatch |
| `X38_EXTRA_ARMS` | more than two source runs for one stage |
| `X39_RUN_DIR` / `X40_INDEX_MUTATED` | run directory collision / index bytes changed between trials |

No rule allows treating `unknown` contention as clear, skipping or re-running a
failed trial to obtain three "clean" ones, or comparing data across hosts.

## Comparison semantics (no invented threshold)

For each lane the runner reports the median-of-trial-medians, the ratio B/A, and
the three paired trial ratios. The verdict is **sign consistency only**:

* `B_FASTER` — every paired trial ratio is `< 1.0`;
* `A_FASTER` — every paired trial ratio is `> 1.0`;
* `INCONCLUSIVE` — otherwise, including any sign disagreement.

There is no "at least X% faster" gate, and a regression or an ambiguous lane is
reported as such rather than averaged into a win.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15e_b1 -p 'test_*.py' -v
```

The unit tests exercise lane selection against the frozen descriptors, source-tree
and out-path refusals, the idle-confirmation gate, frozen-hash drift, verdict math,
comparison preconditions and comparison publication. They never build Rust code,
generate a 100K corpus or time a query.
