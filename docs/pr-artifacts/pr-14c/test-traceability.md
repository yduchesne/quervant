# PR 14C — test traceability (C01–C12, C-T01–C-T16)

**Status: `BLOCKED / NOT ACCEPTED`.** Product invariants C01–C07 and C11–C12
are evidenced; the closeout gates C08 (fresh qualified benchmarks), C09 (CI),
C10 (risk disposition = `REQUIRE SEPARATE CORRECTION`) and C-T14 keep PR 14
blocked.

Executed source SHA: `376023b53b557a30367097f29a41328c798188d4`. PR 14C changed
documentation only. All executed commands, counts and logs are in
[validation-report.md](validation-report.md); the gate crosswalk is
[acceptance-reconciliation.md](acceptance-reconciliation.md).

Expected failures (invalid PIT, expired cursor, one-under budgets, corrupt
bytes, unsupported format versions) are typed assertions **inside** positive
tests; none was converted into an ignored test.

## 1. Product invariants C01–C12

| ID | Guarantee | Executed evidence | Negative/adversarial check | Adjudication |
|---|---|---|---|---|
| C01 | Mixed lexical/typed/JSON/IP/geo query returns independent expected keys, counts and ordered scores | `real::b02` (nested And/Or/Not; survivors ordered `zfew,aonce` while key order is `aonce,zfew`); `pr14_unified_mixed` m01–m14; `pr14_compound_aggregation` t01–t03 | Score order deliberately contradicts key order in `real::b02` | PASS |
| C02 | Aggregations complete irrespective of top-K; invalid middle slot does not erase siblings | `pr14_compound_aggregation` t05/t07/t12; `pr14_batch` b08/b11/b13; `real::r08_r09_r15`; 14A `t05`, `j11` | Three-slot S/F/S shape; `top_k=1` group invariance | PASS |
| C03 | Public cursor resumes exact full ordered tuples and terminal page, scoped to same live PIT/query/sort | `pr14a_public_cursor` 26 tests; `real::b06_b07` page sizes 1 and 2 | Wrong handle → `ConflictingPit`; expired at `expires_at` → `ExpiredCursor`; changed query/sort → `CursorSortMismatch`; mutation/compaction retains old pin (`pr14a` t09, `real::r05`) | PASS |
| C04 | Budgets reject at exact+one-under work/response/memory with typed per-slot failure | `pr14_batch_memory` B10a–B13j (31); `pr14_batch_governance` 7; `real::r10_r11`; 14A `t10`, `t11`, `j10` | One-under typed `BudgetExceeded{kind}`; sibling rollback and cancellation (`b10e/b12b/b12f/b13d`) | PASS |
| C05 | Old/new generation visibility and cold remote recovery | `real::r05`, `real::r12`, `real::r13_r14`, `real::r01` (separate process, empty cache) | Writer-local workspace deleted before cold open; wrong-generation isolation `real::r03` | PASS |
| C06 | Historical *supported v1* JSON segment opens locally and remotely; invalid bytes rejected | `b18_b19_historical_json_segment_compatibility` (frozen SHA-256 `0528a62c…a02f`, writer reproduces byte-identical object); `real::b18` | Flipped payload byte rejected; major 2 → `UnsupportedFormatVersion{major:2,minor:0}` | PASS (JSON wire **v1** only; no cross-version migration claimed) |
| C07 | Faults/cancellation publish no partial durable state or partial cursor | `pr14_storage_faults` F01–F10 × 10 iterations; `pr13_remote_proxy` h06–h12; `pr13_crash_rustfs` k01–k05; 14A `t13` | 503/truncation/range corruption/CAS loss/crash at checkpoints; healthy reopen equals oracle | PASS |
| C08 | Targeted benchmark is correctness-qualified and reproducible | `validate-pr14-p4.py --self-test` PASS; historical trials validate with the W08 exemption manifest | Fresh trials not run; old `ab9b2d7` reports are provenance only | **BLOCKED** |
| C09 | Stable/MSRV gates, ≥85 % measured workspace production line coverage, final-SHA CI green | Local: fmt/clippy/tests both toolchains PASS; coverage 91.27 % lines; doc/bench build/scripts PASS. CI: none | CI on the final head not observed | **BLOCKED** (CI component) |
| C10 | `R-14A-JSON-MEM` remains visible with correctly described measurements | B20/B21 reproduced (112 B logical vs 33,675 / 110,392 / 2,518,968 B tracked peaks); [resource-risk-disposition.md](resource-risk-disposition.md) | Human decision `REQUIRE SEPARATE CORRECTION`; no RSS cap inferred; risk not accepted | **BLOCKED** (risk disposition requires correction) |
| C11 | Original historical NOT READY findings explicitly reconciled, not deleted | [acceptance-reconciliation.md](acceptance-reconciliation.md) 127 classified rows; historical files preserved; supersession notes additive | 18 rows remain `BLOCKED`, no row silently reclassified as optional | PASS (artifact); independent review pending |
| C12 | No production, disk-format, manifest, API or distributed modification | `git diff --stat` for PR 14C = `docs/pr-artifacts/pr-14c/*` + additive notes; no `crates/*/src`, `Cargo.lock`, fixtures, workload semantics or CI definitions changed | File-scope audit | PASS |

## 2. Acceptance cases C-T01–C-T16

| Case | Action | Topology | Result | Adjudication |
|---|---|---|---|---|
| C-T01 | PR 14A public cursor suite | Local `FsDirectory`, real engine | `pr14a_public_cursor` 26 passed; ordered keys, exact/one-under, typed invalid continuation | PASS |
| C-T02 | 11 real verticals individually (`--ignored --exact`) | Pinned RustFS `sha256:1803faef…6a3c` (`1.0.1`), health-verified | 11/11 PASS; `p4_child_bootstrap` only via parent | PASS |
| C-T03 | Local compound/aggregation/typed suites | Local real engine | 188 PR 14 local tests PASS (incl. `pr14_compound_aggregation` 24, `pr14_aggregation` 5) | PASS |
| C-T04 | PR 14 storage fault suites | Real RustFS + existing HTTP fault proxy | 9 cases × 10 iterations = 90 PASS; F08 separate process SIGKILL | PASS |
| C-T05 | PR 13 proxy/crash and objectstore RustFS suites | Real RustFS, separate processes where documented | proxy 7, crash 5, remote 3 real, oracle 1, geo 1, objectstore 8 + 5 → PASS | PASS |
| C-T06 | JSON v1 golden tests | Local + real RustFS | Frozen digest, byte-identical reproduction, corrupt/unsupported rejection | PASS |
| C-T07 | B20/B21 JSON memory characterization | Spawned isolated child process | 112 B logical constant; tracked peaks 33,675 / 110,392 / 2,518,968 B; no RSS/absolute-peak claim | PASS (characterization only) |
| C-T08 | Repeat targeted 14A/14B boundary tests after a harness fix | — | No test-harness change was made in PR 14C | NOT APPLICABLE |
| C-T09 | Benchmark validator self-tests | Local script | `--self-test` PASS; historical 3-trial validation PASS with exemption | PASS |
| C-T10 | 3 qualified P4 trials | Would require idle native-Linux host + pinned RustFS | Not run: human idle attestation unavailable, and acceptance is blocked by C10 | **BLOCKED** |
| C-T11 | Verify W08 exemption manifest | Validator + docs | `pr14-p4-w08-exemption.json` present, approved Option 2, required by validator; W08 never reported measured | PASS (`NOT APPLICABLE (APPROVED)`) |
| C-T12 | Stable default/all-features fmt, clippy, tests, docs, bench build, coverage | Stable 1.98.1 | 2019/2023 passed, 0 failed; coverage 91.27 % lines; doc/bench/scripts PASS | PASS (local) |
| C-T13 | MSRV 1.85.0 checks | `cargo +1.85.0` | fmt, clippy default/all-features, tests 2019/2023 passed, 0 failed | PASS |
| C-T14 | GitHub `rust`, `msrv`, `rustfs` on final PR head | GitHub Actions | No PR/CI run; `gh` token invalid, no job IDs | **BLOCKED** |
| C-T15 | Reviewer independently confirms reconciliation and no prod diff | PR review | Not performed | **PENDING** |
| C-T16 | Explicit risk decision + human merge signoff | Maintainer decision | Decision recorded: `REQUIRE SEPARATE CORRECTION`, 2026-10-24, literal instruction "proceed with option 2"; named merge signoff still required | Decision recorded; **merge signoff PENDING** |

## 3. Environment qualification per case class

| Class | Environment |
|---|---|
| Local engine | Real `FsDirectory`/`MemoryDirectory`, real writer/commit/cold reopen, stable 1.98.1 and MSRV 1.85.0 |
| Real provider | Pinned `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`, health `1.0.1`, dedicated bucket `quervant-pr14b`, per-case unique prefixes, disposable test credentials (not logged) |
| Fault injection | Existing test-only HTTP proxy (`ForwardThenDrop`, `Return503`, `TruncateBodyAfter`, range rewrite, `BlockBeforeCheckpoint`) in front of the real service, plus separate-process SIGKILL checkpoints |
| Memory characterization | Test-only tracking `#[global_allocator]` inside an explicitly spawned child process measurement window |
| Benchmark script | `validate-pr14-p4.py --self-test`; `run-pr14-p4.sh` qualified mode requires `--idle-confirmed`, clean tracked tree, provider env and contention `clear` |

## 4. What is still missing for PR 14 acceptance

1. A separately designed and approved correction for `R-14A-JSON-MEM`, with its
   own tests and re-measured B20/B21 characterization.
2. Independent evidence for the `BLOCKED` rows in
   [acceptance-reconciliation.md](acceptance-reconciliation.md) — notably I13 /
   corrective I12 / final-design I13 (zero query-time remote GET), J14/J15
   (legacy JSON fallback), corrective I07 / final-design I8 (exact physical hit
   identity) and X01–X13.
3. Three fresh qualified P4 trials on a confirmed-idle host.
4. Final-SHA CI (`rust`, `msrv`, `rustfs`) on the actual PR head.
5. Independent review and named human merge signoff.

No acceptance is claimed by this traceability document.
