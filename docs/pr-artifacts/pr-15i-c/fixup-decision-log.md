# PR 15I-C fixup — applied decision-matrix rules

| Rule | Observed trigger | Action taken | Evidence |
|---|---|---|---|
| `FX-D01` | Branch `dev/pr15i-c-postings`, clean tree, HEAD descends from merged main and old C | Pinned SHAs and proceeded with F-00 | `fixup-preflight.md` |
| `FX-D03` | `origin/main` == merged `6f6463cb…`, no newer main | Recorded and continued the existing branch; no rebase | `fixup-preflight.md` §1 |
| `FX-D05` | Branch advanced only through the prior docs-only negative-result commit | Kept history; additive commits only | `git log` |
| `FX-D07` | `395e05c…` reachable | Would have been the only source for F1; never needed because F0 failed | —
| `FX-D09` / `FX-D13` | LZ4 STORED v2 + V3 present; protocol SHA `5464144…` frozen | Recorded, never modified | `verify_layout_diag.py` (`LV_FORMAT`, `LV_SENTINEL`) |
| `FX-D11` | Historical `paired-01` raw + receipt present locally | Verified read-only, preserved untouched; not re-sealed or blended | `fixup-preflight.md` §2 |
| `FX-D15` | Baseline preflight tests passed | Proceeded to G control without asking | `fixup-preflight.md` §3 |
| `FX-D17` | PR15I-A `RealCampaignTests` failed identically on the merged base | Recorded `SOURCE_BOUND_HISTORICAL_ONLY`; not edited, not counted | `fixup-correctness-and-qa.md` §5 |
| `FX-D18` | Generic body matched merged base exactly | Added exactly one `#[inline(never)]`; body hash unchanged | `fixup-control.md` §2 |
| `FX-D20` | Control compiled and targeted tests passed under MSRV | Froze `G_CONTROL_SHA` and ran the 8-block diagnostic | `50b56e9…` |
| `FX-D22` | Required PR15D/PR15E-B1 helper signatures present | Built the 7-lane diagnostic on the frozen adapter and helpers; no new adapter, corpus or clock | `layout_diag.py` |
| `FX-D25` | `generic-boundary-02` directory already existed from a blocked attempt | Advanced to the next unused IDs `-03`, `-04`; never reused | `target/pr15i-c/layout-diagnostics/` |
| `FX-D26` | User-authorized idle host; all 32 contention probes `clear` | Ran the complete diagnostics without asking for permission | sealed slot records |
| `FX-D30` | No symlink/extra-path condition found | `lstat` inventory enforced by the verifier | `LV_SYMLINK`, `LV_INVENTORY` |
| `FX-D32` | `generic-boundary-03` passed all seven lanes and all 56 blocks | Recorded `G_CONTROL_QUALIFIED` for that run only; did **not** treat it as feature acceptance | receipt `reports/layout-generic-boundary-03.json` |
| `FX-D33` | `generic-boundary-04` (valid, independently verified) exceeded `1.15` on two blocks | Rolled back the attribute, recorded `15IC_GENERIC_BOUNDARY_REJECTED_SAFE_ROLLBACK`, HARD STOP on operator restoration | `fixup-performance-decision.md` |
| `FX-D35` | `perf stat` unavailable (WSL kernel package missing) | Recorded `PERF_UNAVAILABLE`; used source-neutral symbol/disassembly evidence; made no microarchitectural claim | `fixup-codegen-evidence.md` §1 |
| `FX-D36`/`FX-D37` | `nm`/`objdump` available; arm A's `collect_mixed` has no standalone symbol | Recorded `SYMBOL_INLINED_OR_NOT_PRESENT` for A and the real address range for G; no "missing means absent" claim | `fixup-codegen-evidence.md` §2 |
| `FX-D38` | `llvm-objdump` unavailable, `objdump` sufficient | Did not change toolchain or install anything | same |
| `FX-D57`/`FX-D58` | No probe feature in the control or A/G builds | Measured uninstrumented release adapters; grepped no probe symbol | `fixup-control.md` §3 |
| `FX-D60` | Chosen output paths were unused | Exclusive creation only | `L_EXISTS` |
| `FX-D67` | Verifier initially disagreed with the controller (`LV_GATE: CONTROL`, then `LV_BINARY` for arm G) | Diagnosed both as harness defects (gate-key set, arm directory label) rather than trusting either side; fixed tooling, re-ran the whole diagnostic under a new ID | tooling commit `7fbea7f` |
| `FX-D72` | No container runtime for genuine RustFS | `REAL_RUSTFS_BLOCKED`; no fake substitute | `fixup-correctness-and-qa.md` §4 |
| `FX-D76` | Hosted CI not run | Reported `HOSTED_CI_PENDING` separately | final report |
| `FX-D77` | Rollback diff verified empty against merged main | Declared rollback safe only after the check passed | `fixup-execution-status.md` §2 |
| `FX-D78` | Production equals merged main and final QA green | Declared `15IC_FIXUP_REJECTED_SAFE_ROLLBACK` | final report |
| `FX-D81` | Known harness defects backed by failing checks, inside the allowed files | Fixed arm labels, worktree naming, gate comparison, seal check and symbol selection; committed a new tooling SHA; re-ran the **entire** diagnostic (`-04`) | tooling commit `7fbea7f`, `generic-boundary-04` |
| `FX-D84` | Prior report contained per-block and `leaf_decode` prose errors | Wrote additive `fixup-diagnostic-errata.md`; sealed raw untouched | `fixup-diagnostic-errata.md` |
| `FX-D85` | No push/PR/merge permission | Local commits only | final report |

## Conditions that did not occur

No `FX-D02` (dirty tree), `FX-D04` (main contract change), `FX-D06` (concurrent
production work), `FX-D08` (missing/divergent old C), `FX-D19` (generic body
drift), `FX-D23` (missing harness symbol), `FX-D27`/`FX-D28` (contention
invalidation), `FX-D31`/`FX-D64`/`FX-D65`/`FX-D66` (provenance/format/sentinel
defects), `FX-D40`, `FX-D47`, `FX-D49`, `FX-D75` or `FX-D86` STOP condition was
encountered. No rule was stretched to justify proceeding past the F0 gate.
