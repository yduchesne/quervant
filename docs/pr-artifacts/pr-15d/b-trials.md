# PR 15D-B — S4/S5 trial record

**Status: `BLOCKED-ATTESTATION`. No trial was run. No aggregate exists.**

## Why nothing was measured

The measurement phase requires all of the following, none of which holds in this
session:

| Gate | Requirement | State |
|---|---|---|
| X25 | A human has personally attested that the host is idle for the specific run window | **absent** — an agent cannot attest this, and I08 forbids the agent from passing `--idle-confirmed` on its own |
| X43 | Ability to push, open the PR and observe exact-head CI | **blocked** — `gh` token invalid (`HTTP 401`) |
| X40/X42 | Exact-head `rust`/`msrv` concluded and both manual dispatch modes observed | **pending** |
| S3 | Three-engine correctness suite passed on the checked-out commit *and* CI refactor committed first | source work committed locally; CI runs unobserved |

Per the plan, the agent may complete source, CI and deterministic test work
autonomously but **must not** claim a run happened. It did not.

## What was deliberately not done

- `harness/run.py` was never invoked, with or without `--trials`.
- `harness/validate.py` and `harness/aggregate.py` were never invoked, so no
  `validation.json` and no `benchmarks/reports/pr15d/pr15d-qualified.json` exist.
- No corpus was generated under `target/pr15d/corpus` for a campaign, and no run
  directory was created under `target/pr15d/runs`.
- No engine was built in release mode for measurement; no host, kernel, CPU,
  governor, cache state or time window was recorded, because no campaign host
  has been selected or attested.
- No "OS page-cache cold" claim was made or implied; `process_cold` remains
  process/reader cold only (I05).
- No contention check was run because no benchmark host was taken.

## Exact commands the operator will run, unchanged from the plan

Only after S1–S3 gates pass, on an attested idle native-filesystem host, from a
clean tree at the reviewed commit:

```bash
python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus
python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus
python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed \
  --out target/pr15d/runs/<unique-immutable-run-id> \
  --corpus target/pr15d/corpus
python3 benchmarks/pr15d/harness/validate.py \
  --run target/pr15d/runs/<unique-immutable-run-id> \
  --out target/pr15d/runs/<unique-immutable-run-id>/validation.json
python3 benchmarks/pr15d/harness/aggregate.py \
  --run target/pr15d/runs/<unique-immutable-run-id> \
  --out benchmarks/reports/pr15d/pr15d-qualified.json \
  --md docs/pr-artifacts/pr-15d/qualification.md
```

Rules that stay binding when it is run: `<unique-immutable-run-id>` is derived
from the UTC timestamp plus the full source SHA; the runner and its flag names
are the existing ones (if fresh `main` changed them, **stop and request an
amendment** rather than guessing); `validate.py` must exit 0 `QUALIFIED` before
`aggregate.py` is invoked; a partial, contended or errored campaign keeps its
raw evidence and is published as `UNQUALIFIED`, never silently re-run.

## Required waiver before this record can change

One sentence from the human operator, naming the host and the run window, e.g.
"host *X* was idle from *T0* to *T1* on *date*; I authorize the PR15D-B
measurement campaign." Without it this file stays `BLOCKED-ATTESTATION`.
