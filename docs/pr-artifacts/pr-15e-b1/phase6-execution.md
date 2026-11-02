# PR 15E Phase 6 — execution record

**Status: `P6_PROFILE_BLOCKED_OPERATOR`** — source preparation and the non-timed gates pass;
the four required `perf` captures were not executed because the PR 15E-A profiler requires a
genuine, current operator-written attestation, which the maintainer's Phase 6 authorization
explicitly did not waive. The driver refused the capture fail-closed, and **no timing ran**.

## 1. P0 preflight (observed)

| Check | Observation |
|---|---|
| Branch | `dev/pr15e-b1-live-bitmap-postings-membership` |
| HEAD | `e448469d6c98d9ef4b4a827ad9567363a888a185` — exactly the required Phase 5 evidence anchor |
| `main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (unchanged) |
| Tracked tree | clean (0 entries) |
| Phase 5 tail vs measured anchor | `git diff --name-only 66b266f..HEAD -- crates/ benchmarks/pr15d/ benchmarks/pr15e/` → **no output** (docs-only tail) |
| Frozen profiler tools | `profile.py` sha256 `96eb5904b720…`, `verify.py` sha256 `ee86d6e19ff5…`, `run_targeted.py` sha256 `ae92ad31ced3…` — unchanged from the accepted tree |
| Toolchain | `python3 3.12.3`, `rustc 1.98.1`, `cargo 1.98.1` |
| Profiler tools | `perf` available only via the driver's installed versioned fallback (`perf version 6.8.12`, `origin=versioned`, `fallback=true`; the PATH wrapper is unavailable for this kernel). `heaptrack 1.5.0` present |
| Contract signatures | `prepare`, `capture`, `validate_capture_args`, `load_attestation`, `required_captures`, `parse_perf_samples`, `discover_perf`, `lane_seconds` all present with the expected behaviour; `verify.py` writes `verification.json` and exposes `sensitive_hits` |

## 2. P1 non-mutating prerequisite QA

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py' -v` | PASS (0), 1 skipped |
| `python3 -m unittest discover -s benchmarks/pr15e_b1 -p 'test_*.py' -v` | PASS (0), 64 tests |
| `cargo fmt --all -- --check` | PASS (0) |
| `cargo +1.85.0 fmt --all -- --check` | PASS (0) |

No Rust source changed, so workspace tests, clippy, coverage, real RustFS and CI are **not
applicable as new Phase 6 feature acceptance**; they remain mandatory before final PR merge and
are carried from the Phase 5 record, not re-claimed here.

## 3. P2 prepare (completed)

`python3 benchmarks/pr15e/profile.py prepare --out target/pr15e/phase6-e448469d-01` → exit 0,
`PREPARED`.

| Field | Observed |
|---|---|
| `status` | `PREPARED` |
| `source.head_sha` | `e448469d6c98d9ef4b4a827ad9567363a888a185` (matches requirement) |
| Adapter | `index_backend = FsDirectory`, analyzer `keyword-exact`, engine version `quervant-core 0.1.0`, release build from the measured tree |
| Corpus | frozen PR 15D 10K/100K regenerated and verified, manifest `69052c6627bf…` |
| Indexes | prepared for 10K and 100K and smoke-verified through the real adapter |
| `tools.perf.status` | `AVAILABLE` (versioned fallback, disclosed per D18) |
| `tools.heaptrack.status` | `AVAILABLE` |
| `attestation.json` | absent |

The first of the five fixed destinations was free and was used; no directory was deleted,
reused or symlinked.

## 4. P3 blocker — genuine operator attestation (D17)

`profile.py::load_attestation` requires an **operator-written** `<run>/attestation.json` with:

* `schema` = `pr15e-attestation-v1` (default when omitted),
* `host` equal to the current host,
* `start_utc` / `end_utc` covering the capture window with at least `seconds + slack` remaining,
* `operator_statement` containing the literal `15E-A` (the reused PR 15E-A harness name).

None exists for this run, the previous October campaign attestations are expired and must not
be reused, and the coding agent may not create, backdate or infer one. The Phase 6
authorization does not waive this dependency.

**Fail-closed evidence (no timing possible):** invoking the rare capture once produced exit `3`
with `BLOCKED_ATTESTATION: no operator attestation at <run>/attestation.json; a passed flag is
not evidence`. The driver validates the attestation **before** creating the capture directory,
before any contention probe and before spawning the profiler, so no profiled query ran and no
capture directory exists.

## 5. Required operator action to unblock

The operator (human) writes, with their own host and a real UTC window of at least the capture
duration plus slack:

```json
{
  "schema": "pr15e-attestation-v1",
  "host": "<their real hostname>",
  "start_utc": "<UTC start, e.g. 2026-11-02T10:00:00Z>",
  "end_utc": "<UTC end covering all four captures>",
  "operator_statement": "I authorize the PR 15E-A profiling harness for the PR 15E Phase 6 focused subset on this idle host for the stated window."
}
```

then runs, from the repository root on a clean tree at `e448469`:

```sh
python3 benchmarks/pr15e/profile.py capture --run target/pr15e/phase6-e448469d-01 \
  --n 100000 --class rare --k 100 --tool perf --seconds 30 --idle-confirmed
python3 benchmarks/pr15e/profile.py capture --run target/pr15e/phase6-e448469d-01 \
  --n 100000 --class absent --k 100 --tool perf --seconds 30 --idle-confirmed
python3 benchmarks/pr15e/profile.py capture --run target/pr15e/phase6-e448469d-01 \
  --n 100000 --class medium --k 100 --tool perf --seconds 30 --idle-confirmed
python3 benchmarks/pr15e/profile.py capture --run target/pr15e/phase6-e448469d-01 \
  --n 100000 --class common --k 100 --tool perf --seconds 60 --idle-confirmed
```

The window must still contain at least `seconds + slack` when each capture starts (150 s of
profiled query time in total, plus preparation and analysis overhead). If the versioned
`perf 6.8.12` cannot sample this kernel, the capture fails closed with a tool error and the
phase becomes `P6_PROFILE_BLOCKED_ENV`; it is never replaced by a synthetic measurement.

## 6. Static attribution preparation (no measurements)

Candidate frames were mapped to the fixed groups for the post-capture analysis, strictly as a
**preparation aid**, not as evidence:

| Group | Candidate frames to look for |
|---|---|
| G01 staging | `SegmentReader::open`, `GuardedSegmentReader`, `ReaderSnapshot::open_segment_reader`, metadata verification |
| G02 stats | `score::compute_stats`, dictionary lookup, field-norm length aggregation |
| G03 columns | `ColumnAccess::open`, `SegmentReader::open_columns`, `ColumnReader::open` |
| G04 keys | `doc_key_selected`, `decode_doc_key_selected`, `decode_doc_keys` |
| G05 stored/projection | `project_selected_hits`, `stored_docs_selected`, `decode_stored_selected`, skip decoding |
| G06 query/scoring | `evaluate_lexical_with`, `build_leaf_data`, `score_segment`, `sort_tuple_for_doc`, heap/cursor selection |
| G07 adapter/runtime | adapter protocol, `serde_json`, allocator, `core::str::from_utf8` |
| G08 unknown | raw addresses, truncated/unsymbolized stacks |

No share, ranking or hypothesis is asserted from this list. The Phase 4 review's
`compute_stats` suggestion remains an untested hypothesis until measured data exists.

## 7. Triggered decision rules

| Rule | Trigger | Class | Action |
|---|---|---|---|
| D01 | HEAD exactly the P5 anchor, clean tree, no Phase 5 tail in Rust/profiler paths | AR | Recorded SHAs and proceeded |
| D04 | Only line numbers/unchanged behaviour | AR | Recorded actual signatures |
| D05 | First fixed destination free | AR | Used `phase6-e448469d-01`; nothing deleted or reused |
| D18 | Versioned `perf` fallback selected by the driver | AR | Used the driver-selected binary and disclosed `origin=versioned`, `fallback=true` |
| D17 | No genuine operator attestation | DC | No timed capture; fail-closed refusal recorded; independent preparation completed |
| D26 | End of authorized Phase 6 work | HS | Stopped before any Phase 7 work; no merge |

## 8. Files changed by this phase

Only documentation: `phase6-design-and-decisions.md`, `phase6-execution.md`,
`phase6-qualification.md`, the Phase 6 section of `review-handoff.md` and the Phase 6 entry in
`decision-log.md`. No `crates/`, `benchmarks/pr15d/`, `benchmarks/pr15e/`,
`benchmarks/pr15e_b1/`, `.github/`, manifest or lock file change. No
`phase6-focused-profile.json` is published because no capture was collected — there is nothing
to summarize, and an empty "profile" artifact could be misread as a measurement.
