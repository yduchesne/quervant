# PR 14F — qualification attempts and operator gate

**Status: `QUALIFIED CAMPAIGN — PASS` (3 of 3 trials) at source SHA
`7df492023397a512e400b03865a989020eff1430`.** Validator and strict auditor both
PASS. The earlier campaign at `162cbfea…` aborted after t1 on a harness
report-path defect; that attempt is preserved and disclosed below. PR 14F
overall remains **NOT ACCEPTED** pending a durable raw archive, final-head CI,
independent review and merge authorization.

## 1. Operator attestation

The human operator supplied the required statement on 2026-10-26:

> “I confirm that competing benchmark workloads have been stopped and that the
> machine is sufficiently idle for performance measurements. You are authorized
> to execute the three qualified PR 14F benchmark trials using
> `--idle-confirmed`.”

Campaign 1 aborted on the harness defect. The operator then approved the
minimal harness-path correction. Campaign 2 was executed under the same explicit
three-trial authorization, after the host was independently observed idle
immediately before it (load `0.19 0.07 0.21`, 100% idle CPU, 0 runnable
processes). Every trial's live contention check was `clear`. No new attestation
text was supplied for campaign 2; this timing is disclosed in
`adversarial-review.md`.

## 2. Gate state

| Gate | State | Evidence |
|---|---|---|
| Source-locked executable | **PASS** | `7df4920…`; clean tracked tree at campaign start |
| Operator authorization / idle attestation | **PASS (timing disclosed)** | §1 |
| Pinned real RustFS digest and health | **PASS** | `environment-and-provider.md`; exercised by all trials |
| Trials executed | **PASS** | `t1`, `t2`, `t3` |
| Correctness oracle before timing | **PASS** | every trial completed the independent oracle |
| Corpus digest / document count | **PASS** | `80ef5615…f8768`, 20,000 docs, all trials |
| Live contention per trial | **PASS** | `clear`; CPU busy 0.003331 / 0.004990 / 0.003744; competing 0 |
| `validate-pr14-p4.py --w08-exemption` | **PASS** | `PASS: 3 qualified pr14_p4_v1 trials` |
| `audit-pr14f-trials.py` | **PASS** | `PASS PR14F audit` |
| W08 | **NOT APPLICABLE (APPROVED)** | never measured |
| Raw evidence local package | **VERIFIED** | deterministic `tar.gz`, SHA-256 `6cef9c71…8fe66d`, 15,491 bytes, 21 members, checksums verify |
| Durable raw archive | **PASS (operator-attested)** | Google Drive `1nt02UI8…`; declared SHA-256 matches local package |
| Baseline-head CI (`4c94ba8`) | **PASS** | PR #67, Rust CI run 40424504536: `rust`, `msrv`, `rustfs` |
| Archival-head CI (`bd1fed7`) | **PASS** | PR #67, Rust CI run 40441448948: `rust`, `msrv`, `rustfs` |
| Previous final-binding-head CI (`8887541`) | **PASS** | PR #67, Rust CI run 40443185707: `rust`, `msrv`, `rustfs` |
| Current binding-head CI / review / merge | **PENDING / NOT DONE** | this binding commit advances the head; no independent review |

## 3. Attempt ledger

| Attempt | UTC window | Duration | Runner | Contention | Disposition |
|---|---|---:|---|---|---|
| `campaign-1-t1` (SHA `162cbfea…`) | 22:43:30Z–22:54:30Z | 648.53 s | PASS, `qualified=true` | clear | **UNPUBLISHABLE** — wrapper aborted on report path; artifacts preserved |
| `t1` (SHA `7df4920…`) | 23:13:35Z–23:24:03Z | 627.58 s | PASS, `qualified=true` | clear (0.003331) | **QUALIFIED** |
| `t2` (SHA `7df4920…`) | 23:24:05Z–23:33:59Z | 594.18 s | PASS, `qualified=true` | clear (0.004990) | **QUALIFIED** |
| `t3` (SHA `7df4920…`) | 23:34:01Z–23:43:48Z | 586.70 s | PASS, `qualified=true` | clear (0.003744) | **QUALIFIED** |

`t2` and `t3` from campaign 1 were never started. No trial was rejected for
correctness, provider identity, contention or data integrity.

## 4. Campaign-2 artifacts (published)

Tracked sanitized reports:

| Trial | Report | SHA-256 |
|---|---|---|
| t1 | `benchmarks/reports/pr14f-p4-7df492023397-t1.json` | `e7173b0afdee5c2bc883a030df0803810c2ac44aeb902422783ad0c5f47c27a4` |
| t2 | `benchmarks/reports/pr14f-p4-7df492023397-t2.json` | `f7d74b9e6de815c03df2a8f801b035569b6fc48e821882b633ec3b14ec69f2c8` |
| t3 | `benchmarks/reports/pr14f-p4-7df492023397-t3.json` | `8f8086eb424bdb4b766c4ee2d16b14b949c197616cc138432dec938f26de3935` |

Raw/supporting evidence is staged under the ignored directory
`target/pr14-p4/archive/7df492023397a512e400b03865a989020eff1430/`:

| Artifact | SHA-256 |
|---|---|
| `pr14-p4-t1.csv` | `e46e27d1eee9e90bd0515c58910aca89886cb1b7ff49a141f92cb3b59f40d5e9` |
| `pr14-p4-t2.csv` | `f31594b5a3a6e5d82bd6bfdfb1710e3090069644c8c5af91728d49b65f801d28` |
| `pr14-p4-t3.csv` | `6df036b37a49e6f8f75142773691e0c2b9118036343bf395f49a8e9b13bae558` |
| `pr14-p4-t1.json` | `e7173b0afdee5c2bc883a030df0803810c2ac44aeb902422783ad0c5f47c27a4` |
| `pr14-p4-t2.json` | `f7d74b9e6de815c03df2a8f801b035569b6fc48e821882b633ec3b14ec69f2c8` |
| `pr14-p4-t3.json` | `8f8086eb424bdb4b766c4ee2d16b14b949c197616cc138432dec938f26de3935` |
| `pr14-p4-contention-t1.json` | `7cf80a420622c129c1bfa50b7d65b6e211677eb14f40abd51982d4f253fd0de7` |
| `pr14-p4-contention-t2.json` | `8ee3efd02505f58c70b1774108d2668a2630285a1d0c5f1817031ae5f9f0ff99` |
| `pr14-p4-contention-t3.json` | `314d555947a21da7b9ca9a811272742095d9621218a304ad6b1908e8c36c59b2` |
| `pr14-p4-t1-run.log` | `86e37671fdcdaf3ee396af031d7787267c41cfd7a00525eb69893f8c3e465e73` |
| `pr14-p4-t2-run.log` | `408f1549c000d3658ae3825e918428acda1731db5559b4246fa87e431c090a64` |
| `pr14-p4-t3-run.log` | `d081bafcb4780f02110b0e72ed3e12febd8bc7dcad4c4228a97b22ef5af1baca` |

`SHA256SUMS` is staged alongside them. A deterministic package was created at
`target/pr14-p4/package/quervant-pr14f-p4-7df492023397-raw-evidence.tar.gz`
(SHA-256 `6cef9c713012c9040391b7a57c82027295781dcf2b42228f7912f2c5578fe66d`,
15,491 bytes, 21 members, byte-identical rebuild). Both `PACKAGE-SHA256SUMS` and
the retained `original-archive/SHA256SUMS` verify.

**RAW ARCHIVE VERIFIED — DURABLE ARCHIVE ESTABLISHED (operator-attested).** The
maintainer uploaded the package to Google Drive
(`1nt02UI8WFui4xDRv5Oxuh5RKM77oeIVY`) and declared SHA-256
`6cef9c71…8fe66d`, matching the local package. The agent could not independently
re-download it without Google credentials; remote integrity is operator-attested.
The local package remains staged under ignored `target/` for validator/auditor
revalidation.

## 5. Preserved campaign-1 artifact

The aborted campaign's t1 evidence remains under
`target/pr14-p4/attempts/162cbfea509d-t1-harness-failure/` with `SHA256SUMS`
(report `c19a3103…`, CSV `f02818f2…`, contention `40f82b2f…`, log `a89716d5…`).
It is not published and was not reused. Independent re-check confirmed 280 rows,
14 pairs × 20 samples, correct hits and positive finite durations.

## 6. Root cause and approved correction

Campaign 1 failed because `cargo test` runs the test binary with cwd
`crates/quervant-core`, so the wrapper's relative `QUERVANT_P4_REPORT_DIR`
resolved under `crates/quervant-core/target/…`. The approved minimal fix makes
both directories absolute:

```bash
report_dir="$ROOT/target/pr14-p4/reports/$source_sha"
qualification_dir="$ROOT/target/pr14-p4/qualification/$source_sha"
```

Committed as source lock `7df492023397a512e400b03865a989020eff1430`
(`fix(pr14f): use absolute report dirs for qualified campaigns`). The PATH-stub
tests now assert an absolute repository `target/` path (58 shell tests pass).
Because an executable changed, all three trials were repeated on the new SHA
(AD-F04); campaign 1's t1 was not reused.

## 7. Provider lifecycle note

The pinned RustFS container `quervant-pr14f-rustfs` was exercised by all three
campaign-2 trials (bucket creation, three commits per trial, cold opens, warm
queries). Endpoint, bucket and credential values are not recorded in tracked
evidence.
