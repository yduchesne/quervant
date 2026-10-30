# PR 15D-B — S3/S4/S5 campaign record

**Status: `BLOCKED` — campaign executed, validator `INVALID`, no aggregate published.**

`run.py` completed all nine engine-trials and self-reported `qualified: true`, but
the frozen validator rejected the run with two `index_bytes_inconsistent` errors.
Per **X32** the aggregator was **not** invoked and no qualified report exists.

## Operator attestation (the authorizing evidence)

Supplied by the human operator in the working conversation, verbatim:

> "I confirm that my local benchmark host is idle, with no significant competing
> workloads, and authorize the PR 15D-B three-engine performance campaign on the
> current clean source commit."

This is the only attestation that exists. The agent did not attest idleness; it
passed `--idle-confirmed` exclusively under this authorization (**X26**), for this
window and no other.

## Run identity and window

| Item | Value |
|---|---|
| Source commit (clean tree) | `c9e982fec5b21ca542f76d0d7940ef796a4c7474` |
| Run id | `20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474` |
| Window (UTC) | `2026-10-30T22:00:25Z` → `2026-10-30T22:41:08Z` (40 m 43 s) |
| Workload | `pr15d_v1`, analyzer `keyword-exact`, N ∈ {10000, 100000}, K ∈ {10, 100} |
| Trials | 3 per engine (9 engine-trials), rotation order per trial |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Local run directory (ignored) | `target/pr15d/runs/20261030T220025Z-c9e982f…` (635 MB, preserved) |

## S3 preflight gates (all passed before timing)

| Gate | Evidence |
|---|---|
| Clean tracked tree at an exact SHA | `git status --porcelain` empty; `HEAD = c9e982f…` |
| Native filesystem | `findmnt -T` → `/dev/sdd` **ext4**; `native_filesystem: true` recorded |
| Filesystem is *not* drvfs | no `/mnt/c` mount involved; repo and run dir on `/` |
| Host idle at start | `check-pr07-contention.py` → `state: clear`, `cpu_busy_fraction: 0.002083`, `competing_process_count: 0` |
| No resizing / tuning / privileged action | none performed |
| Headroom | 32 GB RAM, 619 GB free of 1007 GB |
| Corpus deterministic | generated twice into independent directories; all three files byte-identical |
| Independent oracle | `corpus/oracle.py --corpus target/pr15d/corpus` → manifest digest + `{10000: 10000, 100000: 100000}` rows |
| Adapter pins | Tantivy `=0.22.1`; Lucene `9.12.3`; Gradle wrapper `A1-CHECKSUMS.sha256` → `gradle-wrapper.jar OK`, `gradlew OK`, `gradlew.bat OK` |
| Release builds with lockfiles | quervant `785cc6ed…`, tantivy `0f78a8aa…` (pre-campaign build; the runner rebuilds its own copies into the run dir) |
| Toolchains | rustc/cargo 1.98.1, openjdk 21.0.12.1, javac 21.0.12.1, Gradle 8.14.3, Python 3.12.3 |

## Host fingerprint (recorded in `run.json`)

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

**Disclosed limitation (not an exception, a provenance fact):** the host is a
**WSL2 virtual machine** on a mobile 6-core/12-thread CPU. The filesystem is real
ext4 (not drvfs), the kernel is a WSL2 kernel, and the environment is recorded
verbatim so any reader can weigh virtualisation and frequency-scaling noise. No
thermal or governor control was claimed or attempted.

## Command actually executed (S4)

```bash
python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus
python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus
python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed \
  --out target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474 \
  --corpus target/pr15d/corpus
# exit 0 — run.json: status "complete", qualified true, 9/9 engine-trials qualified
```

Contention re-checked live by the runner before, after and at the end of every
size block: **54/54 records `clear`, 0 contended**, so no contention reason was
recorded and `--allow-contended` was never used.

Every trial manifest also records `operator_idle_attested: true`,
`native_filesystem: true`, `release_build: true`, matching `host_fingerprint`,
matching `corpus_manifest_sha256`, and per-lane `oracle_ok: true` for exact
`total_hits` and `doc_ids` at both sizes.

## S5 validation — the blocker

```bash
python3 benchmarks/pr15d/harness/validate.py \
  --run target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474 \
  --out target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474/validation.json
# exit 2
```

`validation.json`:

```json
{"schema":"pr15d-validation-v1","status":"INVALID",
 "source_sha":"c9e982fec5b21ca542f76d0d7940ef796a4c7474",
 "unqualified":[],
 "errors":[
   {"code":"index_bytes_inconsistent","detail":"tantivy N=10000: {1: 277739, 2: 299700, 3: 298793}"},
   {"code":"index_bytes_inconsistent","detail":"tantivy N=100000: {1: 2961601, 2: 2963073, 3: 2962820}"}]}
```

### Root cause

`validate.py` requires `index_bytes` to be **identical across the three trials**
for the same engine and N (`len(set(sizes.values())) != 1` → error). Observed
per-trial index sizes:

| engine | trial 1 | trial 2 | trial 3 | requirement |
|---|---|---|---|---|
| quervant N=10K | 3090037 | 3090037 | 3090037 | **identical — passes** |
| quervant N=100K | 30965025 | 30965025 | 30965025 | **identical — passes** |
| lucene N=10K | 186052 | 186052 | 186052 | **identical — passes** |
| lucene N=100K | 1858642 | 1858642 | 1858642 | **identical — passes** |
| tantivy N=10K | 277739 | 299700 | 298793 | **differs (7.9 % spread)** |
| tantivy N=100K | 2961601 | 2963073 | 2962820 | **differs (0.05 % spread)** |

Tantivy produced 4 segments in every trial, but the segment boundaries — and
therefore the on-disk byte total — depend on concurrent indexing/merge
scheduling, so its artefact size is not a deterministic function of the input.
Quervant (1 segment) and Lucene (1 segment force-merged) are deterministic.

In other words the frozen invariant "repeating the build yields identical index
bytes" holds for two engines and **does not hold for Tantivy by design**. It is
an engine-property mismatch in the validator, not a data-quality defect in this
campaign: document counts, query results, oracle checks, host fingerprint,
attestation and contention records are all consistent across trials.

### Why nothing was published

- **X32** — validator nonzero: no aggregation, no qualified claim. `aggregate.py`
  was never invoked; `benchmarks/reports/pr15d/pr15d-qualified.json` does not
  exist; `docs/pr-artifacts/pr-15d/qualification.md` was not overwritten.
- **X30** — evidence retained and classified, not repaired.
- **X37** — relaxing or redefining this check is a methodology change and needs
  an approved amendment, so it was not touched.
- **S4 drift rule** — the campaign was not restarted to "try again" for a
  matching Tantivy size. Re-running until an artefact happens to match would be
  selecting evidence, not measuring, and any restart requires a new explicit run
  ID and a full three-engine campaign.

`run.py`, `validate.py` and `aggregate.py` remain byte-identical to the frozen
versions (`8be6c21e…`, `ffc6f7f8…`, `751cf112…`).

## Preserved evidence (bounded, reproducible)

Raw artifacts stay in the ignored run directory. Committed references are the
digests below only.

| Artifact | SHA-256 |
|---|---|
| `run.json` | `98c8d4247bfd63a299fd0013ae6cce4079fe60e6443ec3eaf7572695d5bb7c54` |
| `validation.json` | `86ecd4fb74cb9da2c3548dba9798443e131ae4074075ec2466184cd93c6d638c` |
| `trials/trial-1/quervant.json` | `97ee3c48700bea71a2b2d0d2488a6e9066e686cbdfbcd3b5af95ffb2835d5769` |
| `trials/trial-2/quervant.json` | `dbb2a8be05b21f9ef94c5d49f980af3506716be6aecf753346e3ce9e2c26a448` |
| `trials/trial-3/quervant.json` | `f48b5c0619b7982bed488dca9c2e75e01cfd0a5f3432a6ea88858f6f6f9423a6` |
| `trials/trial-1/tantivy.json` | `92f7e7b20cfca1e16ef6ca53bece04c5c343dd95ebb92ef344193a1c75916121` |
| `trials/trial-2/tantivy.json` | `aa998f0b5698c00cc792f19247725c01454865d7a5e5dd834ca0c06225762025` |
| `trials/trial-3/tantivy.json` | `3bc58ff58bd372943e638b280df6bd213d956aa5c19d6af3ba7ce1f3bfef31b2` |
| `trials/trial-1/lucene.json` | `58a8333c60e811fa0eb873167b6e59364884f845523aff63d4c4cba9860f2c13` |
| `trials/trial-2/lucene.json` | `1040db69f438b5844ef3a1ba9e23873a0a82198be6f06d10ae942f1c6fdee9f1` |
| `trials/trial-3/lucene.json` | `1ac5ffbdf7ca27a1e6202a55e3e7f9cfe5d20bf5270ac10c9fd212a3a8ade363` |

## What the maintainer must decide (no recommendation is applied)

The campaign itself is reusable evidence; only the validator's invariant blocks
it. Any of these needs an explicit, reviewed methodology amendment (**X37**);
the agent must not pick one:

1. **Reclassify `index_bytes` as descriptive evidence** (report per-trial values
   and dispersion) instead of a cross-trial equality invariant.
2. **Allow a documented tolerance** for engines whose layout is
   scheduling-dependent, with the tolerance and its justification recorded.
3. **Downgrade the finding from `INVALID` to `unqualified`**, keeping a qualified
   latency/throughput result while flagging artefact-size non-determinism.
4. **Freeze Tantivy's segment layout** in the adapter (single segment force-merge
   before measurement) so the invariant holds — an adapter change, so this is a
   larger amendment affecting all three engines' comparability.

If the amendment lands, this run can be re-validated and aggregated **without
re-measuring**, because the raw trial manifests are preserved and the aggregator
rederives all statistics from them (S5 reproducibility requirement).

## Standing prohibitions still honoured

- No `aggregate.py` invocation, no `pr15d-qualified.json`, no `qualification.md`
  rewrite, no performance comparison published anywhere.
- No raw corpus, index, binary or log staged in Git.
- No `sudo`, `drop_caches`, swap change, kernel tuning, process kill or package
  install.
- No `--idle-confirmed` outside the attested window; no idleness claim by the
  agent.
