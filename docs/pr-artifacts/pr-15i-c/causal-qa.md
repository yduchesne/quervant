# PR 15I-C causal experiment — correctness and QA record

## 1. Candidate correctness at `CAUSAL_BC_SOURCE_SHA`

Run with `QUERVANT_PR15IC_CAUSAL_MODE=enabled` where the experimental feature is
compiled (the gate rejects an unset mode by design):

| Suite | Result |
|---|---|
| `search::unified::n_tests` (16 restored differential/parity cases) | PASS |
| `search::unified::n_extra_tests` (12 dispatch/projection/limit/concurrency cases) | PASS |
| `search::execute::c15i_physical_tests` (6 operator cases) | PASS |
| `search::execute::n_failure_tests` (2 invalid-score precedence cases) | PASS |
| `tests/pr15i_c_physical.rs` (12 public-path integration cases) | PASS |
| default-feature build (no gate) of the same suites | PASS |

The `CM-U` matrix (mode truth table, source digest, non-default feature,
shared BC binary) is implemented in `test_causal_run.py` and executed against the
real experimental adapter in separate processes; the `CV-01..CV-40` adversarial
verifier matrix is executed in `test_verify_causal.py`.

## 2. Python harness

```
python3 -m unittest discover -s benchmarks/pr15i_c -p 'test_*.py'   309 tests OK
```

245 pre-existing + 24 controller + 40 verifier.

## 3. Score / oracle parity

`raw/score_parity.json` in every campaign records all nine lanes: A (baseline
probe), B (candidate probe, mode enabled) and C (candidate probe, mode disabled)
return identical ordered keys, `total_hits` and `f64::to_bits` scores. The
verifier re-checks the recorded structure and the per-slot oracle keys/counts for
every warmup and every measured sample.

## 4. Format and provenance

12 rebuilds per campaign with identical layout/segment digests across arms;
STORED v2, codec 1, required feature `[13,1]`; 100K sentinel
15,747,551 / 1,661,455. All four campaigns share one host fingerprint, one
`rustc 1.98.1`, one filesystem (`ext4`) and one affinity mode (PINNED, adapter
CPU 0 / controller CPU 1).

## 5. Real boundary status

| Gate | Status |
|---|---|
| Local `FsDirectory` commit/reopen, PIT, compaction, deletion, concurrency | covered by the pre-existing suites run in the final QA |
| Genuine pinned RustFS + PR13 proxy | **`REAL_RUSTFS_BLOCKED`** — no Docker on the host and no verified pinned image access; no fake store was substituted and no compiled-but-ignored test is counted |

## 6. Historical exception

`benchmarks/pr15i_a::RealCampaignTests` 1F/3E reproduces at the pinned merged
base with the same raw data → `SOURCE_BOUND_HISTORICAL_ONLY` (`CA-D14`). Not
edited, not weakened, not counted green.
