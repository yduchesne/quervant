# PR 15I-D3-B — decision register

| ID | Observable condition / evidence | Action taken |
|---|---|---|
| DBX-01 | `main`/`origin/main` resolved to `39dbd9f5…`; `unified.rs` anchors matched the plan; workspace clean | Pinned BASE; created `dev/pr15i-d3b-retained-key-prefilter` |
| DBX-05 | Exactly three duplicate-check sites and one admission helper; four admission call sites | Implemented §3 exactly |
| DBX-06 | `TopK.limit == 100` | One request-local 16-word filter initialized |
| DBX-07 | `TopK.limit != 100` | Literal exact scan, no hashing, no bitset |
| DBX-08 | Active filter, one probe bit clear | Skipped only the exact scan; candidate processed normally |
| DBX-09 | Active filter, both probe bits set | Ran the literal heap scan; error only on real key equality |
| DBX-10 / DBX-11 | `Ok(true)` admission vs `Ok(false)`/`Err` | Noted the fingerprint exactly once after success; never for a loser or error |
| DBX-12 | `admissions == 256` | Permanently disabled the filter for the request |
| DBX-13 | Budget/cancellation `Err` | Propagated the original error with no filter note |
| DBX-14 | K10 bypass observed in witnesses | Accepted the source bypass only; K10 still requires its own real performance gate (not reached) |
| DBX-16 | Malformed losing borrowed sort view | Original `InvalidUtf8` error preserved before any membership check (`u16`) |
| DBX-17 | Borrowed legacy fallbacks | One effective check and at most one admission note per candidate (`u13`–`u15`) |
| DBX-18 | Exact duplicate with a forced probe collision | Exact equality wins; original `CorruptIndex` detail (`u09`, `u10`) |
| DBX-20 | No pre-existing QA failure found | No deferral needed |
| DBX-22 | Real `FsDirectory` reopen passed | Continued |
| DBX-23 | RustFS image cannot be started under podman-compose | Recorded `RUSTFS_PENDING`; continued local work; no pass claimed |
| DBX-25 | Frozen PR15D corpus/oracle/adapter unchanged | Reused verbatim; SHA-256 verified in both worktrees |
| DBX-26 | A/B index bytes compared | Byte-identical (15,747,551 / 1,661,455 sentinels) |
| DBX-27 | Synthetic V01–V28 and controller tests passed | Committed tooling freeze T0 = `155ebaf…` before any timing |
| DBX-29 | A/A control 01 did **not** qualify | No second control was run to chase noise |
| DBX-30 | Control 01 failure is structural (binary digest mismatch), not numerical | Retry **not** authorized; no `aa-02` |
| DBX-31 | Control 01 structural/integrity failure | HARD STOP: archived the control, marked `D3B_MEASUREMENT_BLOCKED`, no paired campaign |
| DBX-33 | Host idle, native ext4, affinity and contention checks passed | Official schedule executed for the control |
| DBX-34 | Exempt-lane soft-outlier rule | Frozen in the protocol and tested (`V17`–`V19`); the control needed no exception |
| DBX-35 | Paired drift gates | Not reached (no paired campaign) |
| DBX-37/38/39 | Paired decision rules | Not reached |
| DBX-41 | Threshold comparisons | Applied exact frozen integer/`Fraction`-free comparisons; no rounding |
| DBX-43 | Performance-rejected rollback | Not applicable (measurement blocked, not rejected) |
| DBX-45 | Hosted CI unavailable in this session | `CI_PENDING`; branch pushed-equivalent local commit, no merge |
| DBX-47 | Historical D3-A/D1 evidence present as documents | Used as context only; D3-B produced independent evidence |
| DBX-50 | Duplicate-path error type and detail | Verified unchanged (`u09`, `u12`–`u16`) |
| DBX-51 | Evidence archive path absent before publish | Created exclusively; no overwrite |
| DBX-54 | CI/review/RustFS acceptance incomplete | Reported as pending; implementation not merged |
| DBX-55 | Only the control attempt completed | No acceptance projected from partial evidence |
| DBX-56 | No algorithm/threshold change requested | None made |
