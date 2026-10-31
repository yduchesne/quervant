# PR 15E-A — decision log

Every decision-matrix entry actually applied during execution, with trigger,
classification, action, evidence and the gate it affects. Rows that did not fire
are listed as `not triggered` so the log is auditable and closed.

The most restrictive rule prevailed; nothing outside the matrix was improvised.
No `X99` event occurred.

## Applied

### X02 — merged PR 15D-B SHA differs from the authoring head

- **Trigger:** plan authored at `main` `8caca768…` / PR #81 head `f0556d3e…`; the
  actual merge is `de278e21c38bb60fa84c43951dadc7c0836787fd`.
- **Classification:** AUTO-RESOLVE.
- **Action:** recorded the actual merged SHA, inspected the required files
  (`QuerySession` one-snapshot contract, `engine_ns` materialisation wording,
  `run.py`, `oracle.py`, `pr15d-qualified.json`), and branched from the merge.
- **Evidence:** `prepare.json` `source.merge_base`; `investigation.md` §1.
- **Gate:** G00.

### X04 — pre-existing PR 15E branch

- **Trigger:** branch `dev/pr15e-profiling` existed at `de278e2`, clean, with no
  commits of its own.
- **Classification:** AUTO-RESOLVE.
- **Action:** renamed it to the prescribed `dev/pr15e-a-exact-workload-profiling`
  instead of creating a second branch; no unknown work was touched.
- **Evidence:** `git status --porcelain=v1` empty; `git log --oneline` at
  `de278e2`.
- **Gate:** G01.

### X06 — existing profiling scripts target a different fixture

- **Trigger:** `benchmarks/scripts/profile-pr15b.sh`,
  `crates/quervant-core/examples/pr15b_profile.rs`, `profile-pr07.sh` exist for
  PR 15B/PR 7 fixtures.
- **Classification:** AUTO-RESOLVE.
- **Action:** reused only their *invocation approach*; implemented the new
  `benchmarks/pr15e/` driver against the frozen PR 15D fixture. No PR 15B result is
  cited as 15D evidence.
- **Evidence:** `investigation.md` §7; `git diff --name-only` shows no change to
  those scripts.
- **Gate:** G01.

### X07 — clean committed implementation SHA available

- **Trigger:** implementation committed as `fc2c62a936cd09069d1f46ed582c247e7f78cf28`
  with an empty `git status --porcelain=v1`.
- **Classification:** AUTO-RESOLVE.
- **Action:** ran host/tool preflight and `prepare` without further reconfirmation.
- **Evidence:** `prepare.json` `source.head_sha`; §3 of `investigation.md`.
- **Gate:** G03.

### X12 — `/usr/bin/perf` wrapper unusable, pre-installed versioned binary works

- **Trigger:** `/usr/bin/perf --version` → rc 2, `WARNING: perf not found for
  kernel 6.18.33.2-microsoft`. Kernel is `6.18.33.2-microsoft-standard-WSL2`;
  installed tooling is `linux-tools-6.8.0-147`.
- **Classification:** AUTO-RESOLVE (the permitted fallback), after verifying a
  pre-installed *absolute existing executable*.
- **Action:** selected `/usr/lib/linux-tools-6.8.0-147-generic/perf` (realpath
  `/usr/lib/linux-tools-6.8.0-147/perf`), `perf version 6.8.12`, using the same
  mandated `perf record`/`perf report` invocations. No package, shim, PATH edit,
  `sudo`, or `perf_event_paranoid` change was made.
- **Evidence:** `prepare.json` `tools.perf` (wrapper diagnostics + `fallback:
  true`, `kernel`); smoke capture with 11 272 samples and 490 `quervant` symbol
  mentions in `target/pr15e/tool-smoke/`.
- **Residual:** kernel/perf version mismatch is disclosed in every report.
- **Gate:** G05.

### X15 — no new operator attestation for a PR 15E-A window

- **Trigger:** no idle-window statement naming PR 15E-A was supplied.
- **Classification:** DEFER AND CONTINUE.
- **Action:** status `BLOCKED_ATTESTATION`. Completed implementation, deterministic
  tests, real-adapter integration, local `prepare` and verification; did **not**
  pass `--idle-confirmed` as evidence, did not reuse a PR 15D-B attestation, and did
  not invent `<run>/attestation.json`. Verified that capture exits 3 with
  `BLOCKED_ATTESTATION` and creates no capture directory.
- **Evidence:** the capture attempt recorded in this session's transcript;
  `verification.json` `PARTIAL`.
- **Gate:** G04 (blocks G05/G06/G07/G08/G09).

### X22 — profiler does not transparently relay the adapter JSONL stream

- **Trigger:** `heaptrack 1.5.0` writes two informational lines to **stdout**
  before launching the debuggee:
  `heaptrack output will be written to "<prefix>.gz"` and
  `starting application, this might take some time...`. Observed with a JSONL
  stdin/stdout child (`heaptrack -o <prefix> -- python3 <jsonl-child>`): the first
  two lines read from the profiled stdout stream are those banners, not the
  adapter's replies. The proxy/driver therefore cannot receive a clean
  `pr15d-adapter-v1` stream through `heaptrack` as prescribed.
- **Classification:** HARD STOP for the affected work (the 8 heaptrack lanes).
  The blocker is isolable: `perf` lanes and all implementation/test work are
  unaffected.
- **Action:** the driver classifies the first non-JSON line as
  `X22_PROFILER_NOT_RELAYING` (hard stop), preserves `profiler-stderr.txt` and the
  probe output, writes only `failure.json`, and never writes `capture.json`.
  It did **not** skip banner lines, did not switch to process attach, did not add a
  shell pipeline, did not use a different tool, and did not create a wrapper
  executable.
- **Evidence:** `benchmarks/pr15e/README.md` §"Tool capability preflight";
  `test_profile.CaptureTests.test_t22_profiler_banner_is_a_hard_stop_with_preserved_raw`
  reproduces the exact class deterministically with a script profiler that emits
  the same banner.
- **Consequence:** G06 (8 heaptrack captures) and therefore G09 (allocation
  attribution for the four primary lanes) are blocked independently of
  attestation.
- **Smallest needed human decision:** amend the plan to authorize one of
  (a) discarding a *documented, bounded* profiler banner preamble before protocol
  parsing, (b) a different heaptrack version/behaviour with verified transparent
  relay, or (c) replacing heaptrack in the allocation lane. Any of these changes
  the fixed profiling architecture and is therefore a maintainer decision, not an
  agent choice.
- **Gate:** G06, G09.

### X37 — host authorization missing while deterministic code is complete

- **Trigger:** follows from X15.
- **Classification:** DEFER AND CONTINUE.
- **Action:** committed implementation and evidence stub as
  `IMPLEMENTED_NOT_PROFILED`/`BLOCKED_ATTESTATION`; continued local QA and
  documentation instead of waiting.
- **Evidence:** this dossier; `verification.json` `PARTIAL`.
- **Gate:** G04–G09.

### X38 — GitHub CLI credentials invalid, exact-head CI unobservable

- **Trigger:** `gh auth status` → `The token in /home/…/hosts.yml is invalid`.
- **Classification:** DEFER AND CONTINUE.
- **Action:** recorded the exact local head (`fc2c62a`), completed every local
  mandatory gate, and did not claim any CI result. Exact-head CI and the real
  RustFS regression job remain `BLOCKED_ENVIRONMENT` for this session.
- **Evidence:** QA table in [`test-traceability.md`](test-traceability.md).
- **Gate:** G10 (partially).

## Not triggered

| Rule | Why not |
|---|---|
| X01 | PR 15D-B is merged (`de278e2`) and the corrected adapter/oracle/report are present. |
| X03 | The pre-existing branch had no unknown work (handled as X04). |
| X05 | Frozen spec/classes/terms/protocol match §5 exactly (verified by `check_15d_prerequisites`). |
| X08 | Working tree was clean before `prepare` and is clean at report time. |
| X09 | Host is Linux/WSL2 on `ext4` with `/proc` available. |
| X10 / X11 / X13 | `perf` and `heaptrack`/`heaptrack_print` executables exist; the `perf` wrapper case is X12. |
| X14 | `cargo flamegraph` is installed but optional; no SVG was produced. |
| X16 / X17 | No attestation; no campaign window existed to expire. |
| X18 | Contention probe was never reached (attestation gate first); the probe is exercised only by tests. |
| X19 / X20 / X21 | No capture reached the reporting stage. |
| X23 | No engine reply was ever produced in a capture (contract is enforced and tested). |
| X24 | No source/binary/corpus/index changed after `prepare` (re-verified by `verify.py`). |
| X25 | Every rejected invocation is tested (`invalid_matrix`, `invalid_seconds`, unknown option). |
| X26 / X27 | No capture loop ran. |
| X28 | No destination was overwritten; refusals are tested. |
| X29 / X30 | No build failure; no file outside the allowlist was edited. |
| X31 | No publication was attempted from incomplete evidence; sanitizer is tested. |
| X32 | No tampered evidence exists; mismatch detection is tested. |
| X33 / X34 / X35 | No per-symbol attribution was produced, so nothing was guessed or summed. |
| X36 | The actual merged PR 15D-B report numbers were read, not the plan's illustrative ones. |
| X39 | All required Rust QA gates pass locally. |
| X40 | Two of this PR's own test expectations were corrected during development (path-symlink resolution, index-inventory key layout) — see the commit diff; no assertion was weakened. |
| X41 / X42 / X43 | No capture to disclose contamination for; no instrumentation added; the X43 path is the recorded fallback if attribution still fails later. |
| X44 | Not all required captures exist, so the "all pass" condition is false. |
| X99 | No unlisted or ambiguous condition required a workaround. |
