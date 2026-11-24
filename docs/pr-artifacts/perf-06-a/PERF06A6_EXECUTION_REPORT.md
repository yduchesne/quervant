# PERF-06-A6 — Execution report: consolidated compatibility, storage and warm-performance qualification

**Overall disposition:** `PERF06_A6_VERIFICATION_BLOCKED`

Valid, complete, independently replayed warm and storage evidence was produced for
both authorized campaigns, and every numerical policy gate was evaluated. The
overall status is **VERIFICATION_BLOCKED** because the two compatibility gates
(G2 native, G3 remote) could not execute: the frozen Appendix A qualification
driver does not compile at either pinned arm, a driver-preparation defect (D08)
with production source unchanged. Per §14.3, the valid unfavorable numerical
decisions are retained separately below and are **not** replaced by the blocked
status.

- Campaign R (isolated A5 retention, E→F): **15/16** lanes MET, **1** lane NOT_MET.
- Campaign C (cumulative A0→F): **2/4** primary lanes MET, **12/12** guard lanes MET.
- Whole-index storage: both predeclared byte gates MET at both sizes; the historical
  byte model is **MODEL_CONFIRMED** (exact equality at both sizes).
- Writer resources: four single-run descriptive observations recorded; no
  acceptance threshold exists or was invented.
- Native/remote E↔F compatibility: **NOT QUALIFIED** (driver compile blocker).
- B1 remains blocked. No merge, promotion or B1 authorization is implied.

| Field | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Controller revision (`RUNNER_SHA`) | `3bb232f868cb556ce9b4273d902164c65416af0f` |
| Planning main / accepted A5 merge (F) | `3bb232f868cb556ce9b4273d902164c65416af0f` |
| `origin/main` at execution | `3bb232f868cb556ce9b4273d902164c65416af0f` (equal to F; fetch performed once) |
| Branch used | `dev/perf06-a6` (existing branch already at F, clean worktree; no similarly named branch created) |
| A6 invocation UUID | `42f4b362-5e71-43c1-850a-d92912193731` |
| Remote prefix (unused, reserved) | `perf06-a6/42f4b362-5e71-43c1-850a-d92912193731` |
| Compiler | rustc/cargo 1.98.1 (`RUSTUP_TOOLCHAIN=1.98.1`); Python 3.12.3; `LC_ALL=C` |
| Host | WSL2, Linux 6.18.33.2-microsoft-standard-WSL2, x86_64, ext4, 12 logical CPUs |

## 1. Gate ledger

| Gate | Result | Evidence |
| --- | --- | --- |
| G0 — Source/authority | **PASS** | A0/E/F objects present and ancestor-ordered; all 19 §2.2 source objects hash-match exactly; `origin/main == F`; user QA/CI exception recorded; clean worktree at start. |
| G1 — Frozen protocol | **PASS** | Plan copied verbatim (sha256 `b15790319fd6d8cefec7c8696ffa61e75baca9e4b7e858be22c57707e3ebb5b0`); four support files extracted with exact Appendix hashes; two new configurations `VALID` with distinct UUIDs; exclusive started markers for both campaigns; one invocation each. |
| G2 — Native compatibility | **BLOCKED (D08)** | Frozen driver does not compile at E or F (`E0277`, identical). No mode launched. Diagnostics preserved. |
| G3 — Remote compatibility | **BLOCKED (dependent on G2)** | Remote modes require the same binary; no container runtime was started, so no task-owned container exists to clean up. |
| G4 — R evidence validity | **PASS** | One `COMPLETE` run; 16/16 A/A controls PASS; 16 lanes complete with 768 records per phase, 5 warmups + 20 positive samples, 12/12 blocks retained; native oracles verified; readiness clear pre/post; exact replay equality; source/cache identity verified. |
| G5 — C evidence validity | **PASS** | Same checks pass for C; guard performed the R-only verification before C's marker was created. |
| G6 — Storage | **PASS** | Measured whole-index bytes; both per-size gates MET; F sizes agree across two independent builds; distinct model disposition recorded as MODEL_CONFIRMED. |
| G7 — Resources | **PASS** | Four of four prescribed build-process observations recorded with GNU time; no repetition. |
| G8 — Warm numerical disposition | **DECIDED — TARGETS NOT ALL MET** | R 15/16 MET (1 NOT_MET); C 2/4 primary MET, 12/12 guards MET; original analyzer statuses preserved. |
| G9 — Evidence/report integrity | **DELIVERED WITH BLOCKED GATES** | This report; protected paths unchanged; original A4 result objects unchanged. |
| G10 — Acceptance/promotion | **OPEN — MAINTAINER** | Includes writer tradeoff assessment and the remote-compaction residual. |

## 2. Execution exception (user-authorized)

The user directed that A5 is merged, main is to be treated as stable, the host is
idle and ready, and that unit/integration suites and quality checks need not run.
Under that exception the following are **NOT RUN — USER-AUTHORIZED STABLE-MAIN
EXCEPTION**, and their absence is **not** a BLOCKED condition:

| Waived activity | State |
| --- | --- |
| `cargo test --workspace --all-targets` (unit/integration, RustFS suites) | NOT RUN |
| `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -D warnings` (1.85.0 and stable) | NOT RUN |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | NOT RUN |
| `cargo doc --workspace --no-deps`, `cargo bench --no-run` | NOT RUN |
| Benchmark-framework / Python / shell test suites (incl. `quervant_bench.lean.tests`) | NOT RUN |
| Re-establishing A5/F1 test totals; correcting pre-merge F1 report discrepancies | NOT DONE (historical files preserved) |
| Waiting for, dispatching, retrying or cancelling CI; claiming a green run | NOT DONE |

Required operational work that **was** executed: release compilation of the two
compatibility example builds, the two ordinary benchmark campaigns through the
unchanged native CLI, the read-only verifier, and the four GNU-time observations.
No experiment override was set; `QUERVANT_PR15I_D3C_*` were absent from the
environment (`grep -c` = 0).

## 3. Source identities

| Symbol | Revision | Verified |
| --- | --- | --- |
| A0 (pre-A1 PERF-05) | `2a74017958c8ac61948f931e8745bf8134827025` | commit object present; ancestor of E |
| E (cumulative A1–A3) | `b70f624fffe0329def62701b61e997c4e303e167` | commit object present; ancestor of F |
| F (merged A5/F1) | `3bb232f868cb556ce9b4273d902164c65416af0f` | commit object present |
| Reviewed A5 PR head | `be5e4b21843cc77e22845588ec9185b5b8b4db31` | present |
| Expected pre-A5 main | `5dc5d6a0a7e8edfcf2aa27f13e85e8d4e27f6d0d` | present |

All 19 §2.2 verified-source object identities matched exactly (authoring guide,
`AGENTS.md`, `docs/BENCHMARKING.md`, PERF roadmap, the four lean harness modules,
the adapter `main.rs`, the six `quervant-core` postings/format/build/reader/merge/
remote modules, `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`, `.github/workflows/ci.yml`).
No fetch of the three arm pins was needed; `origin/main` was fetched once and was
already equal to F, so no docs-only-descendant reconciliation (D02) applied.

| Support file | Bytes | SHA-256 |
| --- | ---: | --- |
| `a6_compatibility.rs` | 22,842 | `927c4d09759c5f29cd35005e8079f77b25028bcd349ea66744b1054130e3b5fc` |
| `verify_a6_results.py` | 12,025 | `8564a68d1a46e99df3b008a69e0dadcadc053993f67751d1a118d2d2ae5964b0` |
| `measure_a6_writer.py` | 9,944 | `32aabfcdb9b485307a96e056e934d31d523652458a9ee9072e01286a0ce41194` |
| `run_a6_once.py` | 8,445 | `4fe15fcc3e79dd5329af36f8038bae549e38bd9eb1f65d86667301dee253110c` |

All four matched their Appendix source identities; no support file was edited.

## 4. Protocol and configuration identities

| Property | Campaign R (isolated retention) | Campaign C (cumulative) |
| --- | --- | --- |
| Name | `quervant-perf06a6-adaptive-warm` | `quervant-perf06a6-cumulative-warm` |
| Configuration file | `benchmarks/studies/perf-06/warm/configurations/quervant-perf06a6-adaptive-warm-2026-11-24.json` | `.../quervant-perf06a6-cumulative-warm-2026-11-24.json` |
| Configuration `configuration_id` | `74fe056d-efae-43f0-902d-b396e7f6fea2` | `76f54a53-79c6-4b0b-b691-1e3987d54e95` |
| Configuration SHA-256 | `2ca83709d071db944755b4732548c5c90c8e4361a5bbbd93559cb571ec0e138d` | `66e50aa74ba7716dc4825c4298647df9885cd586b7341088e23baee91fa42cce` |
| Freeze time (UTC) | `2026-11-24T16:45:27Z` | `2026-11-24T16:45:29Z` |
| Arms | A = E, B = F | A = A0, B = F |
| Result file | `...-001.json`, sequence 1 | `...-001.json`, sequence 1 |
| `run_id` | `68a7b2d5-2fce-46ca-adc7-fbe2a88b7fb1` | `4578ed84-d277-4967-b3b4-786e39cd4540` |
| Execution (UTC) | `2026-11-24T16:48:23Z` | `2026-11-24T16:53:55Z` |
| Result SHA-256 (before and after verification) | `eb809fa66f37b9f5c21e86baac3478ec1f47ff53a634604a053096b5e2be2638` | `04da08b5d9f4ca0f6654adf4e54579c4663cfd0fc73d2ca8d4da4b2d26584141` |
| Preparation cache key | `42182a874955802dbd3cd1fae962a9df2f90a19f980e855ae34665add0fe2c88` (BUILT) | `de9e841cd77e231b906806e00bad1a034b774ebf9d984010eda267a241ba9a94` (BUILT) |
| Preparation time (UTC) | `2026-11-24T16:49:17Z` | `2026-11-24T16:54:47Z` |
| Invocation budget consumed | 1 of 1 (`acquisition/quervant-perf06a6-adaptive-warm.started.txt`) | 1 of 1 (`acquisition/quervant-perf06a6-cumulative-warm.started.txt`) |

Both configurations were created with the exact prescribed `prepare` commands,
validated `VALID`, embed the frozen workload/policy/build/arm maps the verifier
requires, and were never modified after freeze (verified by hash before and after
all read-only analysis). Their UUIDs differ from each other and from all prior
configurations; result suffix `001` is the sequence each new configuration
received, and exactly one invocation of each occurred.

Frozen protocol actually exercised: 16 warm lanes × 12 blocks × 2 arms × 2 slots =
768 treatment records per campaign plus 768 control records, 5 warmups and 20
positive timed samples per record (30,720 recorded samples per campaign; 3,072
records / 61,440 samples across both), 10,000-resample whole-block paired
bootstrap, seed 20261122, no block pruning, A/A aliases AA/AA2 of the campaign's
own A arm.

## 5. Native E→F compatibility — BLOCKED (D08 driver-preparation defect)

Both authorized pinned example builds were attempted exactly once with the frozen
command, toolchain 1.98.1, `--release --locked`, `-p quervant-core --features s3`:

| Build | Target dir | Exit | Result |
| --- | --- | ---: | --- |
| E (`b70f624…`) | `target/perf06-a6/compat-target/E` | 101 | compile error, no binary |
| F (`3bb232f8…`) | `target/perf06-a6/compat-target/F` | 101 | compile error, no binary |

Identical failure at both arms, `crates/quervant-core/examples/perf06_a6_compatibility.rs:220`:

```text
error[E0277]: the trait bound `Array<u8, UInt<UInt<UInt<UInt<...>, ...>, ...>, ...>>: LowerHex` is not satisfied
   --> crates/quervant-core/examples/perf06_a6_compatibility.rs:220:53
    |
220 | fn digest(bytes: &[u8]) -> String { format!("{:x}", Sha256::digest(bytes)) }
```

The workspace pins `sha2 = "0.11"`, whose digest output is a hybrid-array value
without a `LowerHex` implementation; `format!("{:x}", …)` therefore cannot
format it. This is a **driver-preparation defect**, not a production defect: no
`crates/**` file in the controller branch was changed, and the engine, adapter and
harness sources remain at their pinned identities.

Consequences, exactly as §15 D08 prescribes:

- No compatibility mode was launched: `create-e`, `advance-f`, `verify-f` and all
  three remote modes have **zero** process invocations. Consequently no
  `*.stdout.jsonl` / `*.stderr.log` / `*.exit.txt` triple exists, and the six
  prescribed mode logs are absent by design rather than fabricated.
- The `NATIVE_ROOT` (`target/perf06-a6/compatibility/native-index`) was never
  created; no E index, no generation1/2/3, no immutability inventory exists.
- I did **not** repair the driver by guessing, edit its imports/APIs/formulas, or
  relax the frozen support hashes. Smallest amendment requested: an
  author-updated Appendix A `digest()` helper that hex-encodes the digest bytes
  (with a new frozen hash), or explicit authorization to apply that one-line
  change.

Preserved evidence: `compatibility/driver-build-E.log`,
`compatibility/driver-build-F.log`, `compatibility/driver-preparation-status.txt`
(driver digest, worktree HEADs, exit codes, binary presence, modes attempted).

## 6. Remote E/F compatibility — NOT ATTEMPTED (dependent on §5)

`remote-create-e`, `remote-append-f` and `remote-verify-f` all require the
qualification binary that could not be built, so the §7.4 lifecycle could not be
executed. Because no remote mode could run, the pinned RustFS topology
(`rustfs/rustfs@sha256:1803faef…a3c`, `127.0.0.1:19000`, bucket
`quervant-perf06-a6`, prefix `perf06-a6/42f4b362-5e71-43c1-850a-d92912193731`) was **not started**: launching an
owned service that nothing can connect to would have produced no evidence. No
container, volume, listener or host mount was created by this task, so there is
nothing to stop or remove (D32 not triggered).

Therefore these are **NOT QUALIFIED**: remote E creation, remote E→E+F append,
authoritative remote CURRENT verification, cold/new-process reopen from empty
workspaces, held remote PITs, and remote immutable-object survival. No fake
provider, alternate image/port, direct object upload or CURRENT edit was used.

## 7. Campaign R — isolated A5 retention (A3/E → A5/F)

Result validity: `status = COMPLETE`, `errors = []`, 16 lanes, 768 treatment +
768 control records, 12/12 blocks retained per lane per phase, 5 warmups and 20
positive samples per record, preparation oracles verified, all four readiness
observations `clear` on adapter CPU 2 (controller CPU 0), strategy marker absent
in every record, experiment-feature flag false. Both saved analyses (A/A and
treatment) were recomputed independently and compared for exact equality — PASS.

A/A control (all 16 PASS, every signed gain and the whole 95% interval inside ±15%):

| lane | AA median ns | AA2 median ns | A/A gain % | 95% CI | status |
| --- | ---: | ---: | ---: | --- | --- |
| `10000/absent/k10/warm` | 30,800 | 30,888 | -0.327 | [-1.956, +1.009] | PASS |
| `10000/absent/k100/warm` | 30,376 | 30,438 | -0.495 | [-1.574, +0.982] | PASS |
| `10000/common/k10/warm` | 2,464,664 | 2,453,564 | +0.230 | [-1.035, +1.098] | PASS |
| `10000/common/k100/warm` | 2,529,640 | 2,523,528 | -0.055 | [-0.653, +0.917] | PASS |
| `10000/medium/k10/warm` | 1,307,096 | 1,287,871 | +0.188 | [-0.795, +1.961] | PASS |
| `10000/medium/k100/warm` | 1,409,224 | 1,408,587 | -0.106 | [-1.670, +0.492] | PASS |
| `10000/rare/k10/warm` | 38,976 | 38,938 | -0.033 | [-0.384, +1.024] | PASS |
| `10000/rare/k100/warm` | 38,776 | 38,713 | +0.063 | [-0.419, +0.931] | PASS |
| `100000/absent/k10/warm` | 157,365 | 157,228 | -1.004 | [-1.349, +0.710] | PASS |
| `100000/absent/k100/warm` | 152,565 | 150,215 | +0.775 | [+0.092, +2.099] | PASS |
| `100000/common/k10/warm` | 24,826,350 | 24,760,724 | +0.165 | [-0.668, +0.877] | PASS |
| `100000/common/k100/warm` | 24,520,883 | 24,481,816 | -0.131 | [-0.653, +0.937] | PASS |
| `100000/medium/k10/warm` | 13,065,522 | 13,026,795 | +0.447 | [-2.221, +0.935] | PASS |
| `100000/medium/k100/warm` | 13,070,870 | 13,068,784 | +0.394 | [-0.981, +0.811] | PASS |
| `100000/rare/k10/warm` | 163,628 | 167,090 | -0.955 | [-5.723, +1.918] | PASS |
| `100000/rare/k100/warm` | 162,365 | 160,215 | +0.785 | [-1.965, +3.772] | PASS |

Treatment A/B with absolute block medians and the frozen A6 retention budget
(`gain ≥ −2.0` **and** `lower 95% CI ≥ −5.0`):

| lane | A = E median ns | B = F median ns | gain % | 95% CI | analyzer status | A6 retention budget |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `10000/absent/k10/warm` | 31,476 | 32,638 | -2.122 | [-21.808, +19.334] | INCONCLUSIVE | NOT_MET |
| `10000/absent/k100/warm` | 30,375 | 30,263 | +0.652 | [-1.685, +1.475] | INCONCLUSIVE | MET |
| `10000/common/k10/warm` | 2,443,788 | 2,418,813 | +1.157 | [+0.417, +1.864] | IMPROVED | MET |
| `10000/common/k100/warm` | 2,497,978 | 2,482,064 | +0.878 | [-0.680, +2.396] | INCONCLUSIVE | MET |
| `10000/medium/k10/warm` | 1,299,334 | 1,296,346 | -0.165 | [-2.095, +2.341] | INCONCLUSIVE | MET |
| `10000/medium/k100/warm` | 1,397,910 | 1,382,697 | +0.765 | [+0.244, +1.914] | IMPROVED | MET |
| `10000/rare/k10/warm` | 39,263 | 38,576 | +1.271 | [+0.674, +2.375] | IMPROVED | MET |
| `10000/rare/k100/warm` | 38,863 | 38,313 | +0.965 | [+0.350, +1.641] | IMPROVED | MET |
| `100000/absent/k10/warm` | 162,078 | 161,803 | +1.951 | [-3.513, +6.077] | INCONCLUSIVE | MET |
| `100000/absent/k100/warm` | 151,803 | 151,902 | +0.067 | [-2.840, +2.966] | INCONCLUSIVE | MET |
| `100000/common/k10/warm` | 24,683,370 | 24,355,612 | +1.078 | [+0.204, +1.858] | IMPROVED | MET |
| `100000/common/k100/warm` | 24,247,299 | 23,858,466 | +1.491 | [+0.501, +2.763] | IMPROVED | MET |
| `100000/medium/k10/warm` | 12,910,193 | 12,702,926 | +1.697 | [+0.486, +2.699] | IMPROVED | MET |
| `100000/medium/k100/warm` | 12,912,044 | 12,621,162 | +2.001 | [+0.943, +2.896] | IMPROVED | MET |
| `100000/rare/k10/warm` | 165,965 | 165,190 | +0.864 | [-2.713, +2.378] | INCONCLUSIVE | MET |
| `100000/rare/k100/warm` | 158,190 | 157,578 | +0.182 | [-2.730, +0.450] | INCONCLUSIVE | MET |

Retention decision: **15 MET / 16 lanes; 1 NOT_MET** —
`10000/absent/k10/warm` at `gain = −2.122%`, CI `[−21.808, +19.334]`. That lane
misses only the point-estimate clause (`−2.122 < −2.0`); its interval is
extremely wide because the absent-term K10 query is tens of microseconds and
machine noise dominates. The analyzer status is `INCONCLUSIVE`, not `REGRESSED`.
It is a valid unfavorable result, was preserved unaltered, and was **not**
retried, pruned or retuned.

## 8. Campaign C — cumulative A0 → F

Same validity evidence as R (exact replay equality, 4 readiness checks `clear`,
16 lanes, 768+768 records, 12/12 blocks retained everywhere, oracles verified).
The continuation guard verified R read-only and classified it **before** creating
C's started marker, then invoked C once.

A/A control (all 16 PASS):

| lane | AA median ns | AA2 median ns | A/A gain % | 95% CI | status |
| --- | ---: | ---: | ---: | --- | --- |
| `10000/absent/k10/warm` | 30,775 | 30,488 | +0.533 | [-2.551, +1.141] | PASS |
| `10000/absent/k100/warm` | 30,401 | 30,325 | -0.615 | [-2.157, +1.673] | PASS |
| `10000/common/k10/warm` | 2,577,354 | 2,570,503 | +0.442 | [-0.906, +0.910] | PASS |
| `10000/common/k100/warm` | 2,622,692 | 2,623,404 | +0.565 | [-0.957, +1.121] | PASS |
| `10000/medium/k10/warm` | 1,319,708 | 1,315,733 | +0.233 | [-1.011, +1.745] | PASS |
| `10000/medium/k100/warm` | 1,409,910 | 1,413,373 | -0.218 | [-1.327, +1.364] | PASS |
| `10000/rare/k10/warm` | 39,013 | 38,801 | -0.130 | [-0.611, +2.503] | PASS |
| `10000/rare/k100/warm` | 38,413 | 38,363 | -0.362 | [-1.623, +1.119] | PASS |
| `100000/absent/k10/warm` | 160,140 | 159,715 | +0.755 | [-2.822, +2.742] | PASS |
| `100000/absent/k100/warm` | 150,690 | 150,203 | +0.025 | [-1.812, +0.982] | PASS |
| `100000/common/k10/warm` | 26,083,953 | 25,911,036 | +0.452 | [-0.146, +1.114] | PASS |
| `100000/common/k100/warm` | 25,464,713 | 25,374,519 | +0.588 | [-0.378, +1.555] | PASS |
| `100000/medium/k10/warm` | 13,158,146 | 13,152,696 | +0.446 | [-0.110, +0.882] | PASS |
| `100000/medium/k100/warm` | 13,128,523 | 13,077,509 | +0.467 | [-1.077, +1.401] | PASS |
| `100000/rare/k10/warm` | 167,265 | 166,928 | +0.151 | [-2.960, +4.537] | PASS |
| `100000/rare/k100/warm` | 160,115 | 158,252 | +1.017 | [-0.095, +2.561] | PASS |

Treatment A/B with the preserved A4-era policy: primary lanes need
`status = IMPROVED` **and** `gain ≥ 5.0%` **and** `lower CI > 0.0`; guards need
`gain ≥ −10.0%` **and** `lower CI ≥ −10.0%`.

| lane | A = A0 median ns | B = F median ns | gain % | 95% CI | analyzer status | category | gate |
| --- | ---: | ---: | ---: | --- | --- | --- | --- |
| `10000/absent/k10/warm` | 30,576 | 30,563 | -0.163 | [-3.274, +2.117] | INCONCLUSIVE | GUARD | MET |
| `10000/absent/k100/warm` | 30,263 | 29,963 | +0.786 | [+0.074, +1.607] | IMPROVED | GUARD | MET |
| `10000/common/k10/warm` | 2,561,066 | 2,414,064 | +5.720 | [+4.278, +6.858] | IMPROVED | GUARD | MET |
| `10000/common/k100/warm` | 2,595,466 | 2,468,839 | +4.995 | [+4.021, +5.524] | IMPROVED | GUARD | MET |
| `10000/medium/k10/warm` | 1,329,734 | 1,280,921 | +3.167 | [+1.812, +4.486] | IMPROVED | GUARD | MET |
| `10000/medium/k100/warm` | 1,410,985 | 1,373,434 | +2.899 | [+2.410, +3.714] | IMPROVED | GUARD | MET |
| `10000/rare/k10/warm` | 38,801 | 38,788 | +0.259 | [-0.848, +1.077] | INCONCLUSIVE | GUARD | MET |
| `10000/rare/k100/warm` | 38,225 | 37,950 | +0.394 | [-0.098, +1.012] | INCONCLUSIVE | GUARD | MET |
| `100000/absent/k10/warm` | 156,353 | 158,052 | -0.443 | [-2.200, +2.592] | INCONCLUSIVE | GUARD | MET |
| `100000/absent/k100/warm` | 149,965 | 149,815 | +0.333 | [-0.251, +2.168] | INCONCLUSIVE | GUARD | MET |
| `100000/common/k10/warm` | 25,840,035 | 24,200,212 | +6.235 | [+5.427, +6.708] | IMPROVED | PRIMARY | MET |
| `100000/common/k100/warm` | 25,179,651 | 23,862,977 | +5.428 | [+4.984, +6.143] | IMPROVED | PRIMARY | MET |
| `100000/medium/k10/warm` | 13,085,057 | 12,685,302 | +3.129 | [+2.732, +3.425] | IMPROVED | PRIMARY | NOT_MET |
| `100000/medium/k100/warm` | 13,040,707 | 12,628,313 | +3.365 | [+2.421, +3.995] | IMPROVED | PRIMARY | NOT_MET |
| `100000/rare/k10/warm` | 164,415 | 166,965 | -0.982 | [-4.170, +1.404] | INCONCLUSIVE | GUARD | MET |
| `100000/rare/k100/warm` | 157,928 | 157,878 | +0.143 | [-1.523, +0.497] | INCONCLUSIVE | GUARD | MET |

- Primary: **2/4 MET** (`100000/common/k10` +6.235%, `100000/common/k100` +5.428%),
  **2/4 NOT_MET** (`100000/medium/k10` +3.129%, `100000/medium/k100` +3.365% —
  both `IMPROVED` with positive intervals, but below the 5% target).
- Guards: **12/12 MET**. No lane regressed; the two `medium` N=100K primaries are
  genuine partial wins rather than regressions.
- This reproduces the shape of the historical A4 outcome (2/4 primary targets) on
  a now-final A5 source; it is new evidence under new names/UUIDs, not a relabel
  of A4, and A4's stored verdict is untouched.

## 9. Whole-index storage (G6)

Sizes are the sum of regular-file lengths of freshly built one-commit benchmark
indexes (one segment each), measured by the preparation stage and re-verified
against disk and cache fingerprints. No compatibility directory containing old
generations, no `du` allocated-block figure and no manifest/state exclusion is
used.

| N | A0 bytes (C arm A) | E bytes (R arm A) | F bytes (R arm B) | F bytes (C arm B) | E − F | model 90·(N+1) | actual − model | E→F reduction | F/E | F/A0 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 1,560,111 | 2,356,869 | 1,456,779 | 1,456,779 | 900,090 | 900,090 | +0 | 38.19% | 0.6181 | 0.9338 |
| 100,000 | 15,747,551 | 23,713,222 | 14,713,132 | 14,713,132 | 9,000,090 | 9,000,090 | +0 | 37.95% | 0.6205 | 0.9343 |

Predeclared A6 byte gates (integer comparisons):

| N | 100·F ≤ 70·E | F ≤ A0 | F agreement across campaigns |
| ---: | --- | --- | --- |
| 10,000 | MET (145,677,900 ≤ 164,980,830) | MET (1,456,779 ≤ 1,560,111) | AGREE |
| 100,000 | MET (1,471,313,200 ≤ 1,659,925,540) | MET (14,713,132 ≤ 15,747,551) | AGREE |

- Both gates MET at both sizes. F removes **38.19%** (10K) / **37.95%** (100K) of
  E's whole-index bytes, comfortably inside the ≤ 0.70 ratio, and lands **6.6%**
  below the pre-A1 A0 footprint.
- F sizes agree exactly across the two independent builds in R and C
  (`1,456,779` and `14,713,132`), and the four diagnostic fresh builds in §10
  reproduce the same totals. No nondeterminism (D22 not triggered).
- **Model disposition: `MODEL_CONFIRMED`.** `E − F` equals `90 · (N + 1)` exactly
  at both sizes (diff `0`), matching the historical per-singleton-list saving
  assumption with unchanged other file lengths. Because the model closed exactly,
  the mismatch-only fingerprint inventory of §9.3 was not required and was not
  run.
- Observed totals also coincide with the plan's historical reference bytes for
  A0 (1,560,111 / 15,747,551), E (2,356,869 / 23,713,222) and projected F
  (1,456,779 / 14,713,132); these historical numbers are recorded for context
  only, not as new measurements.

## 10. Writer build-process resource observations (G7)

Four prescribed single-run observations, each wrapping the already-built E or F
release adapter with `/usr/bin/time` (GNU Time; `user_seconds`, `system_seconds`,
`max_rss_kib`, `elapsed_seconds`, `exit_status`), on the campaign R corpora at
adapter CPU 2. Boundary: the entire adapter process — startup, TSV parse, index
creation, insertion, commit, writer close, verification reopen and byte walk. This
is **not** encoder-only CPU, insert-only memory, compaction memory, query RSS,
allocation counts or OS-cache memory, and it is not isolated writer benchmarking.

| order | source | N | index_ns | commit_ns | reopen_ns | index_bytes | user s | system s | total CPU s | elapsed s | peak RSS KiB | exit |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | E | 10,000 | 19,203,106 | 146,027,927 | 30,188,081 | 2,356,869 | 0.16 | 0.02 | 0.18 | 0.22 | 43,508 | 0 |
| 2 | F | 10,000 | 19,680,014 | 117,965,379 | 21,208,938 | 1,456,779 | 0.14 | 0.01 | 0.15 | 0.18 | 41,712 | 0 |
| 3 | F | 100,000 | 203,037,335 | 1,160,382,888 | 205,881,980 | 14,713,132 | 1.53 | 0.12 | 1.65 | 1.70 | 376,212 | 0 |
| 4 | E | 100,000 | 194,497,199 | 1,449,377,790 | 306,472,183 | 23,713,222 | 1.92 | 0.11 | 2.03 | 2.08 | 394,740 | 0 |

F/E ratios (descriptive; one observation per cell, no interval, no acceptance
threshold, no statistical preservation claim):

| component | N = 10,000 E | F | F/E | N = 100,000 E | F | F/E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| insertion `index_ns` | 19203106 | 19680014 | 1.0248 | 194497199 | 203037335 | 1.0439 |
| commit `commit_ns` | 146027927 | 117965379 | 0.8078 | 1449377790 | 1160382888 | 0.8006 |
| reopen `reopen_ns` | 30188081 | 21208938 | 0.7026 | 306472183 | 205881980 | 0.6718 |
| user CPU seconds | 0.16 | 0.14 | 0.8750 | 1.92 | 1.53 | 0.7969 |
| system CPU seconds | 0.02 | 0.01 | 0.5000 | 0.11 | 0.12 | 1.0909 |
| total CPU seconds | 0.18 | 0.15 | 0.8333 | 2.03 | 1.65 | 0.8128 |
| elapsed process seconds | 0.22 | 0.18 | 0.8182 | 2.08 | 1.70 | 0.8173 |
| peak RSS KiB | 43508 | 41712 | 0.9587 | 394740 | 376212 | 0.9531 |

Readings (descriptive only): at both sizes F's commit (`~0.80×`), reopen
(`0.70×` / `0.67×`), total CPU (`0.83×` / `0.81×`), elapsed process time
(`0.82×` / `0.82×`) and peak RSS (`0.96×` / `0.95×`) are below E's, while the
narrower `index_ns` insertion figure is slightly higher (`1.02×` / `1.04×`) and
system CPU at 100K is marginally higher (`1.09×`). GNU time rounds to 0.01 s, so
the small-CPU components carry large relative rounding uncertainty; no ratio was
computed from a zero denominator and no epsilon was added. Sizes agree with §9
exactly for all four cases. The maintainer evaluates this tradeoff; the agent
invented no favorable threshold.

## 11. Read-only verification and integrity

`verify_a6_results.py` was run once after both results existed, in the same
controller checkout and environment (`RUSTUP_TOOLCHAIN=1.98.1`, `LC_ALL=C`,
`PYTHONPATH=benchmarks`), and printed `"verification": "PASS"`. It confirmed, with
no build, query, suite or artifact write:

- frozen workload, policy, build map, arm sources/modes and control roles, and
  `result["configuration"] == config` for both campaigns;
- `sequence == 1`, `status == COMPLETE`, `errors == []`, 16 lane descriptors;
- runner source == `RUNNER_SHA`; compiled arm revisions; strategy feature
  disabled; distinct controller/adapter CPUs; preparation oracles verified;
  `cache_status` in BUILT/HIT with a valid cache key and unchanged index-metric
  provenance;
- four `clear` readiness observations on the adapter CPU for each campaign;
- 768 records per phase, 48 per lane and 384 per arm, 5 warmups, `oracle_ok`,
  no strategy marker, 20 positive samples;
- independent recomputation of **both** the A/A and treatment analyses with exact
  equality against the saved analyses; all A/A lanes PASS; 12 raw/retained blocks
  and no exclusions; every treatment comparison computed with 10,000 resamples
  and 12 paired ratios;
- read-only native cache re-verification (`source_identity` + `_load_cache`) with
  matching `index_metrics`, `build_info` and `prepared_utc`;
- one segment per fresh benchmark index and positive integer
  `index_ns`/`commit_ns`/`reopen_ns`/`index_bytes`;
- distinct campaign `configuration_id`/`run_id`, identical controller/adapter CPUs
  across campaigns, and identical independently built F bytes at both sizes;
- unchanged configuration and result hashes across verification.

Integrity: protected historical objects are unchanged — A4 results remain
`c7d49358fdaf0a6f4591f7a70d3ad2d5eba2cb40` and
`dbbd5116ccbfe06a0fc8099ab2fbeee4967ccc12`. There is **zero tracked-file
delta**: every change in this task is either a new file inside the §3.1 allowlist
or a current-status amendment to one of the four allowlisted documents. No
`crates/**`, `benchmarks/quervant_bench/**`, `benchmarks/pr15d/**`, `Cargo*`,
`.cargo/**`, `rust-toolchain.toml`, `.github/**`, test, fixture, golden or
historical A1–A5/F1 artifact was modified. No raw index, binary, container data
or secret is staged.

## 12. Failures, interruptions and applied decision rows

| Observation | Row | Class | Action taken |
| --- | --- | --- | --- |
| Clean F checkout, all pins/contracts matching | D01 | AUTO-RESOLVE | Executed P0→P8 continuously, no phase-boundary permission stops |
| `origin/main == F`, no docs-only descendant | — | — | D02 not applicable; branch continued from existing `dev/perf06-a6` at F |
| All three arm pins present locally | D35 | — | No pin fetch needed; object/ancestry reads repeated only |
| Supplied driver fails to compile at E and F | **D08** | Driver-preparation defect | Preserved diagnostics; blocked G2/G3; continued independent warm/storage work; did not edit the driver |
| Generic-guide QA/CI gates suggested | D06 | AUTO-RESOLVE | Applied the user exception; recorded NOT RUN; nothing marked PASS or BLOCKED for waived checks |
| R `COMPLETE`, controls/oracles/replay valid, 1 retention lane NOT_MET | D16 | AUTO-RESOLVE | Preserved R unchanged and executed the preauthorized C once |
| C `COMPLETE`, 2/4 primaries NOT_MET, guards 12/12 | D18 | AUTO-RESOLVE | Finished resources and reporting; derived targets-not-met numerics; no rerun/revert |
| Analyzer `INCONCLUSIVE` with finite estimates on several lanes | D19 | AUTO-RESOLVE | Applied the fixed numerical R/guard rules; retained the INCONCLUSIVE labels; primary lanes without IMPROVED could not pass |
| Measured sizes differ from projection? | D21 | — | Not triggered: exact equality, MODEL_CONFIRMED |
| GNU time unavailable/invalid? | D23 | — | Not triggered: GNU time present, four valid rows |
| Any resource case failing? | D24 | — | Not triggered: 4/4 recorded |
| RustFS runtime/image/port/health unavailable | D25 | — | Not exercised: remote path was already blocked upstream by D08 |
| Remote compaction claim | D27 | — | Residual retained as NOT QUALIFIED; no compact→commit workaround attempted |

No interruption occurred during either acquisition; both ran to a published
`COMPLETE` result on the first and only authorized invocation. No process was
killed, restarted or staged twice, and the standalone `stage` command was not run
(the run path prepared and oracle-checked both arms itself).

## 13. Residuals and scientific limits

1. **Remote compaction publication is NOT QUALIFIED** and remains a
   maintainer-owned residual. Unchanged source shows `RemoteIndexWriter::compact`
   delegating to native compaction while remote commit returns early for an
   effectively no-op underlying commit before publication; that observation is not
   a runtime claim and was not worked around, so universal remote lifecycle
   qualification is not asserted.
2. **Native and remote E/F compatibility are unqualified** in this execution for
   the D08 reason, so nothing here demonstrates genuine old-writer coexistence on
   real E-produced bytes, mixed E+F segments, native compaction to a single F
   segment, held PITs across compaction, or remote cold reopen from empty
   workspaces. The `42f4b362-5e71-43c1-850a-d92912193731` remote prefix was reserved and never used.
3. Resource observations are four **single-run descriptive** process-level samples
   — not statistically qualified write benchmarking, and not a claim about
   insert-only memory, encoder CPU in isolation, or query RSS.
4. Warm effects are paired, same-campaign, warm-regime results for these sources,
   corpus, lane set (explicit doc_id sort / relevance sorting at K10/K100),
   compiler and host only. R isolates the whole A5 change, not compact framing
   separately from A5's other implementation changes; C measures the consolidated
   A1–A3+A5 change and cannot attribute gain to individual stages.
5. Smaller indexes do not by themselves prove lower query latency, lower query
   RSS, faster startup or lower writer CPU; R reports small positive/neutral
   latency effects and §10 reports lower commit/reopen/CPU/RSS at the process
   level, which are consistent with, not proof of, a storage-driven gain.
6. The one NOT_MET retention lane and the two NOT_MET cumulative primary lanes are
   preserved as valid unfavorable evidence; they are not reruns, not pruned, and
   their bounds were not relaxed after observation.
7. General QA, coverage, MSRV/stable lint matrices and CI green-ness are **NOT
   RUN** under the explicit user exception; no favorable claim rests on them.

## 14. Publication state and next decision

- Evidence committed on branch `dev/perf06-a6` with the exact tested pins
  (controller and both arms at F-lineage `3bb232f868cb556ce9b4273d902164c65416af0f`);
  the source closure for both campaigns and the compat worktrees is unchanged, so
  the delivered commit differs from the measured controller only by documentation
  and A6 artifact files (D30).
- Engine pins A0/E/F, configurations, results and the four support files are
  unchanged from their measured bytes (hash ledger in
  `verification/artifact-hashes-before.txt` / `-after.txt`).
- CI state: **NOT OBSERVED** (no dispatch, retry, cancellation or waiting
  performed under the user exception). A later failure, if any, must be disclosed
  rather than hidden; the maintainer assesses it outside this waived gate.
- **Maintainer (G10) decisions still open:** whether the 15/16 retention result,
  the 2/4 primary + 12/12 guard cumulative result, the 38%/6.6% size reductions and
  the descriptive writer tradeoff justify accepting A5/A6; and how to dispose of
  the remote-compaction-publication residual.
- **B1 does not start automatically.** No merge, release, roadmap "DONE" claim or
  promotion is implied by this report.

### Command ledger for this execution

| Command | Result |
| --- | --- |
| `git fetch origin main`; object/ancestry `cat-file`/`merge-base` reads | PASS |
| Appendix E extraction recipe (4 files, frozen hashes) | PASS |
| `python3 -m quervant_bench prepare` (R, C) | PASS — two new configurations |
| `python3 -m quervant_bench validate --config` (R, C) | `VALID`, `VALID` |
| `cargo +1.98.1 build --release --locked -p quervant-core --features s3 --example perf06_a6_compatibility` (E, F) | FAIL — driver compile error (`E0277`), no binary |
| `python3 run_a6_once.py` → `python3 -m quervant_bench run` (R) | exit 0, `COMPLETE`, result `...-001.json` |
| `python3 run_a6_once.py` → `python3 -m quervant_bench run` (C) | exit 0, `COMPLETE`, result `...-001.json` |
| `python3 verify_a6_results.py …` | `"verification": "PASS"` |
| `python3 measure_a6_writer.py …` | 4/4 recorded, `A6_WRITER_DIAGNOSTICS_RECORDED=4` |
| Six compatibility mode invocations | NOT RUN — blocked by driver build (D08) |
| RustFS launch + three remote mode invocations | NOT ATTEMPTED — dependent on driver build |
| Waived QA/coverage/lint/doc/bench suites and CI waiting | NOT RUN — user-authorized exception |
