# PR 14 — P4 pre-implementation reconciliation (P4-G0)

## Repository state
- `dev/pagination` HEAD: `57b330107f14fb37d7bcec4a1637ba497a8f48b9` (P3 accepted).
- `main`: `7ca1b2ec59fec648602e0e4a52e8f903a596f106`; merge-base: same.
- Working tree clean before edits.
- P2B 31/31 and P3 24/24 accepted baselines preserved.

## Reused components (verified)
- `quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig}`
  with `RemoteIndex::{create, open_existing}`, `RemoteIndexWriter::{insert, apply, commit}`.
- `quervant_objectstore::S3ObjectStore/S3Config` `s3` feature (production adapter).
- PR 13 real-provider suites and `tests/rustfs/compose.yaml` pinned image
  `rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`.
- `search::{UnifiedSearcher, execute_batch, AggregationRequest/Result}` and PR 14 schema.

## Real-provider topology (verified live)
- Podman rootless; container `quervant-rustfs`; endpoint `http://127.0.0.1:9000`;
  health `{"status":"ok","version":"1.0.1"}`; test-only credentials from the
  container environment (not committed, not logged).
- Executed PR 13 baseline (real provider, `--ignored --test-threads=1`):
  - `pr13_s3_rustfs` 8/8 PASS
  - `pr13_remote` real 3/3 PASS
  - `pr13_remote_proxy` 7/7 PASS
  - `pr13_proxy_rustfs` 5/5 PASS
  - `pr13_oracle` 1/1 PASS
  - `pr13_oracle_geo` 1/1 PASS
  - `pr13_crash_rustfs k0` 5/5 PASS

## Status classification
| Area | Status |
|---|---|
| PR 13 RustFS adapter/cache/proxy/crash | DONE/VERIFIED (re-executed above) |
| P2B governance, P3 aggregation | DONE/VERIFIED (accepted, kept green) |
| P4 compound vertical | NOT STARTED |
| P4 real-provider faults | NOT STARTED |
| P4 benchmark qualification | NOT STARTED |
| Final-SHA CI | PENDING (separate gate) |

## Invariant / test map
V01–V03 → R01–R07; V04/V05 → R08–R11; V06/V09 → R12–R14; V14 → R15;
V07/V08/V10 → F01–F10; V11/V12 → B01–B04. V13 is a no-format-change review.

## Counterexample checks (pre-code)
- Stale generation: reopen only the committed pointer, compare
  `reader.generation()` and keys against the local oracle (R03/R05).
- Mixed old/new docs: hold an old `Arc<ReaderSnapshot>` across a new commit and
  assert it is unchanged (R05).
- Partial download: PR 13 proxy/crash suites already reject/cleanup; P4 faults
  will reuse them (F01–F04).
- Rejected slot corrupting retained memory: `pr14_batch_memory` S/F/S and
  remote R09/R10.
- Correct top-K but wrong aggregation: compare exact groups independently of
  `top_k` (R02/R06/R08).
- Warm benchmark using cold cache / oracle bypass: B01/B02 negative validator.

## Decision
No semantic conflict with the approved P4 design. Proceed with P4-A.
No persistent-format, cursor STOP S2, distributed or vector changes.
