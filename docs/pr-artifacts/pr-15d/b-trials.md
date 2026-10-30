# PR 15D-B — S3/S4/S5 campaign and revalidation record

**Status: `QUALIFIED`.** The campaign was measured once; the validator was
corrected afterwards under an approved methodology amendment; the **same**
untouched raw measurements were then revalidated and aggregated. No measurement
was repeated.

## Provenance: two distinct commits

| Role | Commit |
|---|---|
| **Measurement source SHA** (the tree that was timed) | `c9e982fec5b21ca542f76d0d7940ef796a4c7474` |
| **Validator/aggregator amendment SHA** | `ffbd4b36382d88e93bd74aa2f5467f276496bfd1` |
| Docs-only commit made between the two | `c92e7678dea9444a03fa56fec3e26759e2b4492a` (4 markdown files, no executable change) |

The measurements were taken at `c9e982f` from a clean tree; `c92e767` and
`ffbd4b3` came afterwards and changed no adapter, corpus, specification,
protocol or timing code. **The benchmark campaign was never re-run.**

## Operator attestation (the authorizing evidence)

Supplied by the human operator in the working conversation, verbatim:

> "I confirm that my local benchmark host is idle, with no significant competing
> workloads, and authorize the PR 15D-B three-engine performance campaign on the
> current clean source commit."

This is the only attestation that exists. The agent did not attest idleness; it
passed `--idle-confirmed` exclusively under this authorization, for this window
and no other.

## Run identity and window

| Item | Value |
|---|---|
| Run id | `20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474` |
| Window (UTC) | `2026-10-30T22:00:25Z` → `2026-10-30T22:41:08Z` (40 m 43 s) |
| Workload | `pr15d_v1`, analyzer `keyword-exact`, N ∈ {10000, 100000}, K ∈ {10, 100} |
| Trials | 3 per engine (9 engine-trials), rotated order per trial |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Local run directory (ignored) | `target/pr15d/runs/20261030T220025Z-c9e982f…` (635 MB, preserved) |
| Samples | 32 lanes × 20 samples + 5 warmups per engine-trial; 2 throughput windows |

## S3 preflight gates (all passed before timing)

| Gate | Evidence |
|---|---|
| Clean tracked tree at an exact SHA | `git status --porcelain` empty; `HEAD = c9e982f…` |
| Native filesystem, not drvfs | `findmnt -T` → `/dev/sdd` **ext4**; `native_filesystem: true` |
| Host idle at start | `check-pr07-contention.py` → `clear`, `cpu_busy_fraction 0.002083`, 0 competing |
| No privileged action | no `sudo`, cache drop, swap/kernel change, package install |
| Headroom | 32 GB RAM, 619 GB free of 1007 GB |
| Corpus deterministic | generated twice into independent directories; all three files byte-identical |
| Independent oracle | `corpus/oracle.py` → manifest digest + `{10000: 10000, 100000: 100000}` rows |
| Adapter pins | Tantivy `=0.22.1`; Lucene `9.12.3`; `A1-CHECKSUMS.sha256` → `gradle-wrapper.jar OK`, `gradlew OK`, `gradlew.bat OK` |
| Release builds with lockfiles | quervant `785cc6ed…`, tantivy `0f78a8aa…` (runner rebuilds its own copies) |
| Toolchains | rustc/cargo 1.98.1, openjdk 21.0.12.1, javac 21.0.12.1, Gradle 8.14.3, Python 3.12.3 |

Host fingerprint (verbatim from `run.json`):

```
host_fingerprint: 4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f
kernel:           6.18.33.2-microsoft-standard-WSL2
machine:          x86_64
cpu_model:        Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz
cpu_count:        12
mem_total_bytes:  33561378816
filesystem:       ext4
wsl:              true
cgroup:           cpu_max null, memory_max null
```

**Disclosed limitation:** the host is a **WSL2 virtual machine** on a mobile
6-core/12-thread CPU. The filesystem is real ext4 (not drvfs) and the kernel is
a WSL2 kernel; virtualisation and frequency-scaling noise are therefore part of
this environment and are recorded so any reader can weigh them. No thermal or
governor control was claimed or attempted. **These numbers describe this host,
not a tuned bare-metal server.**

## Campaign command (executed once)

```bash
python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus
python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus
python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed \
  --out target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474 \
  --corpus target/pr15d/corpus
# exit 0 — run.json: status "complete", qualified true, 9/9 engine-trials qualified
```

Contention re-checked live before, after and at the end of every size block:
**54/54 records `clear`**, so `--allow-contended` was never used. Every trial
manifest records `operator_idle_attested: true`, `native_filesystem: true`,
`release_build: true`, the shared host fingerprint and corpus digest, and
per-lane `oracle_ok: true`.

## The original failure (preserved, not deleted)

The first validation, with the unamended validator:

```bash
python3 benchmarks/pr15d/harness/validate.py --run <run-dir> --out <run-dir>/validation.json
# exit 2 — status INVALID
```

```json
{"schema":"pr15d-validation-v1","status":"INVALID",
 "source_sha":"c9e982fec5b21ca542f76d0d7940ef796a4c7474",
 "unqualified":[],
 "errors":[
   {"code":"index_bytes_inconsistent","detail":"tantivy N=10000: {1: 277739, 2: 299700, 3: 298793}"},
   {"code":"index_bytes_inconsistent","detail":"tantivy N=100000: {1: 2961601, 2: 2963073, 3: 2962820}"}]}
```

That exact output is preserved inside the run directory as
`validation-initial.json` (SHA-256 `86ecd4fb74cb9da2c3548dba9798443e131ae4074075ec2466184cd93c6d638c`,
byte-identical to the original `validation.json`). Those two errors were the
**only** reported failures; `unqualified` was empty.

Cause: the validator required `index_bytes` to be **identical across the three
trials**. Quervant and Lucene are deterministic (1 segment each); Tantivy keeps 4
scheduling-dependent segments, so its byte total legitimately varies.

## The approved correction

Methodology decision (approved by the maintainer): *physical index size is a
descriptive performance measurement, not a cross-trial equality invariant.*
Different positive `index_bytes` values across independently executed trials must
not invalidate an otherwise qualified comparison, and engine behaviour must not be
modified to force identical sizes.

Applied in `ffbd4b3`:

- `validate.py` — removed only the cross-trial equality check. Per-trial
  presence, integer type and strict positivity stay enforced by `_check_build`
  (rejects missing, null, boolean, float, string, NaN, zero, negative). No
  tolerance was added; no other gate changed.
- `aggregate.py` — added `min` and `max` next to the existing `trial_values`,
  `median` and `dispersion_max_over_min`, and published an "Index artifact size
  variation" table plus a limitation bullet.
- `test_pr15d.py` — 13 new adversarial tests covering both directions (differing
  positive sizes qualify; every malformed or non-positive value is rejected).

## Revalidation of the untouched measurements (S4)

```bash
python3 benchmarks/pr15d/harness/validate.py \
  --run target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474 \
  --out target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474/validation.json
# exit 0
```

```json
{"schema":"pr15d-validation-v1","status":"QUALIFIED","errors":[],"unqualified":[],
 "trials":3,"source_sha":"c9e982fec5b21ca542f76d0d7940ef796a4c7474",
 "run_id":"20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474",
 "engines":["quervant","tantivy","lucene"]}
```

- All nine original engine-trials retained; nothing was re-measured or dropped.
- No `index_bytes_inconsistent` error remains.
- No correctness, provenance, host, contention or attestation gate was waived.
- `validation.json` (qualified) SHA-256
  `a51a7badb129acb028873cae4678c3cab801e8fade7ca13b92bf2a05ad0240ba`.

## Aggregation (S5)

```bash
python3 benchmarks/pr15d/harness/aggregate.py \
  --run target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474 \
  --out benchmarks/reports/pr15d/pr15d-qualified.json \
  --md docs/pr-artifacts/pr-15d/qualification.md
# exit 0
```

Both outputs are produced **by the aggregator only**; no statistic was hand
edited.

| Artifact | SHA-256 |
|---|---|
| `benchmarks/reports/pr15d/pr15d-qualified.json` | `8b81c09aff407165f253a460160fb9694abbe0d4b12307516b44e28e7d199bc1` |
| `docs/pr-artifacts/pr-15d/qualification.md` | `9008fe7d76f334941ccf0746db67cfdc5fdfb0621d8668d4cd7f3e425fe2c5e3` |

Reproducibility checks performed:

- `aggregate.verify_aggregate(run, checked_in_json)` → `[]` (no disagreement);
- a full re-derivation produces **byte-identical** JSON and Markdown;
- an **independent** recomputation (own nearest-rank percentile implementation,
  no harness imports) confirmed 108 statistics: every per-trial lane median, every
  lane median, every lane dispersion, every per-trial index size plus
  median/min/max/dispersion, and every throughput median — **0 problems**.

## Index-size variation, as published

| Engine | N | trial 1 | trial 2 | trial 3 | median | min | max | max/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| quervant | 10000 | 3090037 | 3090037 | 3090037 | 3090037 | 3090037 | 3090037 | 1.0 |
| quervant | 100000 | 30965025 | 30965025 | 30965025 | 30965025 | 30965025 | 30965025 | 1.0 |
| tantivy | 10000 | 277739 | 299700 | 298793 | 298793 | 277739 | 299700 | **1.079071** |
| tantivy | 100000 | 2961601 | 2963073 | 2962820 | 2962820 | 2961601 | 2963073 | **1.000497** |
| lucene | 10000 | 186052 | 186052 | 186052 | 186052 | 186052 | 186052 | 1.0 |
| lucene | 100000 | 1858642 | 1858642 | 1858642 | 1858642 | 1858642 | 1858642 | 1.0 |

Segment counts were stable at 1 / 4 / 1 for quervant / tantivy / lucene at both
sizes, so Tantivy's variation comes from segment **boundaries**, not segment
count. No tolerance and no size-parity threshold exists; the values are reported
descriptively.

## Preserved artifact digests (unchanged by this amendment)

| Artifact | SHA-256 |
|---|---|
| `run.json` | `98c8d4247bfd63a299fd0013ae6cce4079fe60e6443ec3eaf7572695d5bb7c54` |
| `validation-initial.json` (original INVALID) | `86ecd4fb74cb9da2c3548dba9798443e131ae4074075ec2466184cd93c6d638c` |
| `trials/trial-1/quervant.json` | `97ee3c48700bea71a2b2d0d2488a6e9066e686cbdfbcd3b5af95ffb2835d5769` |
| `trials/trial-2/quervant.json` | `dbb2a8be05b21f9ef94c5d49f980af3506716be6aecf753346e3ce9e2c26a448` |
| `trials/trial-3/quervant.json` | `f48b5c0619b7982bed488dca9c2e75e01cfd0a5f3432a6ea88858f6f6f9423a6` |
| `trials/trial-1/tantivy.json` | `92f7e7b20cfca1e16ef6ca53bece04c5c343dd95ebb92ef344193a1c75916121` |
| `trials/trial-2/tantivy.json` | `aa998f0b5698c00cc792f19247725c01454865d7a5e5dd834ca0c06225762025` |
| `trials/trial-3/tantivy.json` | `3bc58ff58bd372943e638b280df6bd213d956aa5c19d6af3ba7ce1f3bfef31b2` |
| `trials/trial-1/lucene.json` | `58a8333c60e811fa0eb873167b6e59364884f845523aff63d4c4cba9860f2c13` |
| `trials/trial-2/lucene.json` | `1040db69f438b5844ef3a1ba9e23873a0a82198be6f06d10ae942f1c6fdee9f1` |
| `trials/trial-3/lucene.json` | `1ac5ffbdf7ca27a1e6202a55e3e7f9cfe5d20bf5270ac10c9fd212a3a8ade363` |

All eleven digests were re-verified after the amendment and still match the
values recorded before it: **the original measurements are byte-for-byte
unchanged.**

## Reading the published result

- `benchmarks/reports/pr15d/pr15d-qualified.json` and
  `docs/pr-artifacts/pr-15d/qualification.md` report Quervant as **substantially
  slower** than Tantivy and mostly slower than Lucene on this host. That is
  published unaltered; there is no win/parity threshold (`performance_threshold_failure: false`).
- Many lanes are flagged `INCONCLUSIVE` by the frozen dispersion heuristic
  (three-trial spread > 1.10 or overlapping trial median ranges). Those are
  reported as inconclusive, never as a win.
- `process_cold` means a fresh process and unopened reader, **never** OS page-cache
  cold. `serial_ops_per_second` is a single sustained serial window, not
  multi-threaded QPS. RSS/CPU/allocation are `NOT_MEASURED`.
- Scored BM25 remains `SEMANTICALLY_NONCOMPARABLE`; no scored ratio is published.

## Standing prohibitions honoured

- No campaign re-run, no additional trials, no discarded outliers.
- No `sudo`, `drop_caches`, swap change, kernel tuning, process kill, package
  install, or thermal/governor manipulation.
- No raw corpus, index, binary or log committed; only bounded digests.
- No `--idle-confirmed` outside the attested window.
