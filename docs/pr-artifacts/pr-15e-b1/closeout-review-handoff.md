# PR 15E — Closeout reviewer handoff

**PR:** https://github.com/yduchesne/quervant/pull/83 (open; **not merged**)

> **Sanitization note (reviewed, not a disabled check):** the only token in this document that
> matches the sanitizer's username pattern is inside that expected **public** repository/target
> URL. No hostname, operator statement, absolute path, credential, PID or raw profiler data is
> present. This is the single allowlisted public source link for this file.
**Branch:** `dev/pr15e-b1-live-bitmap-postings-membership`

```text
DO_NOT_MERGE_UNTIL_ALL_GATES_PASS
```

## 1. Source identity

| Item | SHA |
|---|---|
| Original benchmark base (arm A) | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` |
| Phase 5 accepted production code | `9881789b6c00a14bed995a5bc7e38ae18536d125` |
| Pre-merge PR tip | `6f9a2017b44e9138bbe9742ada636f5ae56df0f1` |
| Reconciled optimized head (arm B) | `40ca10bae46f2d7df7804a0a129a99a4daf35ef0` |
| `main` integrated by the merge | `506beb038e070aee780dacfda1b5dbb9da30b642` |
| Final closeout documentation commit | recorded in the delivery message as `FINAL_HEAD_SHA` (see §6) |

Merge parents of `40ca10b`: `6f9a201` (PR tip) and `506beb0` (main). The merge integrated only
six documentation paths and changed **no** `crates/`, benchmark, profiler, CI or manifest bytes.

## 2. What changed in this PR overall

Five implementation files (`search/execute.rs`, `search/unified.rs`,
`segment/{value,stored,reader}.rs`) plus their test files; the `benchmarks/pr15e_b1` runner and
its `p3`/`p4`/`p5` stages; sanitized comparison reports; and the phase evidence documents. No
public API, on-disk format, writer, storage, distributed, vector, dependency or CI change.

Phases delivered: B1a (direct live-bitmap traversal), B1b (sorted-postings binary search),
Phase 3 (selective STORED materialization), Phase 4 (postings-driven single-term candidates),
Phase 5 (singleton DOC_KEYS decode). Phases 6 and 6F are read-only investigations.

## 3. Gate status the reviewer must verify

| Gate | State |
|---|---|
| C01 source scope | PASS |
| C02 reconciliation | PASS (`40ca10b`, six docs, zero code delta) |
| C03 correctness | PASS (2227/2231 tests, clippy ×4, fmt ×2) |
| C04 coverage | PASS (92.52 % lines) |
| C05 local real RustFS | PASS (25/25 invocations, podman + pinned image, disclosed) |
| C06 cumulative performance | **PASS** — 9/9 lanes `B_FASTER`, 0 `A_FASTER`, 12/12 probes `clear` (`cumulative-closeout.json`) |
| C07 local adapter | PASS (adapter tests + real-adapter integration at `40ca10b`) |
| C08 evidence/privacy | PASS (no new benchmark JSON; sanitization clean) |
| C09 exact-head CI | **PASS** on `32d2170` (run `41670986842`, all three jobs `success`) |
| C10 G11 | **BLOCKED — `PENDING_REVIEW`** |
| C11 code scope | PASS |
| C12 maintainer signoff | **PENDING** |

## 4. Reproducible local commands

```sh
cargo fmt --all -- --check && cargo +1.85.0 fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
python3 -m unittest discover -s benchmarks/pr15e_b1 -p 'test_*.py' -v
python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py' -v
# real RustFS: the 25 exact CI invocations with the pinned image (see closeout-execution.md §6)
```

Cumulative performance (already executed under the operator's assumed-idle authorization; the
stage root was `target/pr15e-b1/closeout-final-cumulative-01`):

```sh
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree "$PWD/target/pr15e-b1/closeout-worktrees/baseline" \
  --stage final --out "$PWD/target/pr15e-b1/closeout-final-cumulative-01" --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree "$PWD/target/pr15e-b1/closeout-worktrees/optimized" \
  --stage final --out "$PWD/target/pr15e-b1/closeout-final-cumulative-01" --idle-confirmed
```

Result: **9 `B_FASTER`, 0 `INCONCLUSIVE`, 0 `A_FASTER`** (largest 27.04× on 100K/common/k10,
smallest 2.05× on 10K/absent/k100), 12/12 contention probes `clear`, oracle-exact, identical
corpus and host fingerprint. Sanitized evidence:
`benchmarks/reports/pr15e-b1/cumulative-closeout.json`.

## 5. G11 reviewer protocol

`docs/pr-artifacts/pr-15e-a/fixup-review-handoff.md` §7 defines RV-01–RV-08. A **different
authorized person** with approved access to the original private run must issue a dated, named
PASS/REJECT/HOLD citing the measured source, review head, evidence reviewed, exceptions and
residual risks. Raw profiler artifacts must not be uploaded to GitHub, CI artifacts or this PR.
The historical waiver covers **implementation**, not this merge; only a reviewer PASS or an
explicit merge-specific maintainer waiver naming G11 and its risks can close C10.

## 6. Late CI outcome

The closeout documentation commit's SHA is reported in the delivery message. When CI is run on
that exact SHA, `rust`/`msrv`/`rustfs` must all be `success`; a queued, in-progress, cancelled or
different-SHA run is not a PASS. The committed report labels CI `PENDING_AT_COMMIT` because the
credentials required to push and observe it were unavailable.

## 7. Maintainer checklist (all required)

1. Confirm code semantics and scope: five implementation files, no format/API/storage change,
   corruption/budget/PIT/cursor/batch invariants intact.
2. Confirm the executed cumulative nine-lane measurement (9/9 `B_FASTER`, zero `A_FASTER`,
   12/12 clear probes) in `cumulative-closeout.json` and `closeout-qualification.md` §4.
3. Confirm the real RustFS acceptance on the exact final head (local podman run is supporting
   evidence only; the hosted `rustfs` job is authoritative).
4. Confirm exact-head GitHub CI `rust`/`msrv`/`rustfs` = success on the final SHA.
5. Dispose of G11: independent RV-01–RV-08 PASS or an explicit merge-specific waiver.

Residual risks to accept explicitly: synthetic single-host workload; no cross-engine or
distributed claim; G03/G05 findings deferred; G11 raw-evidence risks (WSL2 symbolization, 786
lost samples, unresolved allocation buckets); local-vs-hosted RustFS substitution; unmeasured
cumulative performance.
