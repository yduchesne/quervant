# PR 15F — P0 decision log

Only rules from the approved execution plan are used. Every entry records the
exact trigger, observation, action, verification and remaining gate.

| # | Rule | Trigger / observation | Classification | Action and verification | Remaining gate |
|---|---|---|---|---|---|
| 1 | D01 | `origin/main` exactly `d5f3c0563f352123ce4136d6dbd45a6091cc7aeb`; clean tracked tree | AUTO-RESOLVE | Branched `dev/pr15f-p0-query-reopen-layout-attribution` from that baseline; recorded HEAD and protected tree | none |
| 2 | D07 | `findmnt` reports native `ext4` for the checkout and `target/`; clean root | AUTO-RESOLVE | Executed the prepared measurement on that filesystem | none |
| 3 | D10 | Plan explicitly approved for execution with assumed-idle policy; every capture still ran a real before/after probe | AUTO-RESOLVE | Used the PR 15F-only `--idle-confirmed` flag and recorded `authorization_basis=operator_approved_assumed_idle_for_pr15f`; no PR 15E attestation was created | C14 review confirms provenance wording |
| 4 | D15 | `/usr/bin/perf` wrapper refused the WSL2 kernel; existing PR 15E discovery found `/usr/lib/linux-tools/6.8.0-147-generic/perf` (`perf version 6.8.12`) | AUTO-RESOLVE | Used the versioned fallback, recorded path/version and `profiler_fallback=true`; no installer, shim or root escalation | none |
| 5 | D16 | Not triggered: a usable `perf` was resolved | — | Query and reopen CPU captures were executed | none |
| 6 | D22 | `heaptrack 1.5.0` printed the exact approved two-line startup preamble | AUTO-RESOLVE | Reused the PR 15E 1.5.0 preamble validation, preserved the raw preamble and continued allocation capture | none |
| 7 | D24 | Probe schema/registry/limits are a byte-identical benchmark-only copy of the frozen adapter with pinned source hash and unit assertions | AUTO-RESOLVE | Built with its own committed `Cargo.lock` and ran it against the prepared real index | none |
| 8 | D29 | Public `parse_container` parsed every segment/manifest/mutation-state container; all byte categories reconciled | AUTO-RESOLVE | Classified exact `SectionKind` bytes and overhead; no ad-hoc parser | none |
| 9 | D32 | Observed 100K index is exactly 30,965,025 bytes, matching the historical anchor | AUTO-RESOLVE (descriptive) | Recorded the actual identity and generation match; no strict size PASS and no data normalization | none |
| 10 | D33 | Inclusive and exclusive shares overlap by construction | AUTO-RESOLVE | Published them separately; explicitly never summed; validator enforces exclusive ≤100% | none |
| 11 | D34 | The dominant `sha2` symbol appears under segment digest, manifest verification and mutation-state decode | AUTO-RESOLVE | Strict exclusive ownership marked `R08`/UNKNOWN; an allocated diagnostic was published separately and is not used for ranking | none |
| 12 | D37 | Not triggered: all nine mandatory query lanes and both reopen CPU loops were captured | — | Campaign status `QUALIFIED` | none |
| 13 | D39 | All mandatory gates qualified and both optional allocation lanes captured | AUTO-RESOLVE | Published `P0_QUALIFIED_REVIEW_READY` | C14 human review |
| 14 | D43 | SSH push succeeded, but `gh` returned `HTTP 401: Bad credentials`; no GitHub API credential exists to open a PR, and `ci.yml` triggers only on `main`/PR | DEFER AND CONTINUE | Pushed `dev/pr15f-p0-query-reopen-layout-attribution` at `3594a9f…`; recorded hosted exact-head `rust`/`msrv`/`rustfs` as **BLOCKED**, not green | C12 when a human opens the PR |
| 15 | D45 | No independent reviewer has signed off | DEFER AND CONTINUE | Handed off report and evidence; no merge or self-approval | C14 |
| 16 | D05 (analogue) | `target/pr15f/run-01` was occupied by the smoke campaign when the qualified campaign was ready | AUTO-RESOLVE | Used the next exclusive private run, `target/pr15f/run-02`; preserved `run-01` and `run-smoke-01/02` without deleting or reusing any evidence | none |
| 17 | D11 | Not triggered: all before/after contention probes in the qualified campaign were `clear` (4 reopen-single probes, 2 per reopen CPU capture, 2 per query capture, 2 allocation) | — | Captures qualified; no `--allow-contended` path exists | none |
| 18 | D18 | Not triggered: every perf lane and reopen loop had ≥1,000 samples and zero lost samples | — | No window extension or rerun was performed | none |
| 19 | D30 | Not triggered: no unknown file, bad magic, wrong container kind, digest or reconciliation failure occurred in the prepared indexes | — | Inventory qualified | none |

## Analysis-tooling correction (pre-publication)

The first smoke campaign exposed two defects in **post-capture analysis only**:

1. adapter/search umbrella frames (adapter root, `UnifiedSearcher`,
   `search_impl`, `execute_unified`) were treated as disjoint inclusive
   competitors of their own children;
2. demangled umbrella symbols were not matched by the mangled-only anchor.

Both were corrected before any evidence was published. A fresh qualified campaign
was then executed from scratch at the final measured source `80a2fd73…` into
`target/pr15f/run-02/`. Capture drivers, the reopen probe, the PR 15D adapter and
oracle, all frozen inputs, and the prepared indexes were unchanged between the
campaigns. `target/pr15f/run-01/` and the smoke runs remain private and are not
used in the report. This is an evidence-integrity disclosure, not a measurement
retry: no failed capture was replaced inside the qualified matrix.

## Explicit non-authorizations

- PR 15F does **not** authorize A1–A5, a format change, a cache, planner
  specialization, streaming/late scoring, compression or remote-layout work.
- Inclusive candidates are not estimated improvements.
- The profiling agent did not choose the future P1-versus-P3 direction; that is
  the reviewer's decision on this evidence.
