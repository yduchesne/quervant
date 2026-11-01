# PR 15E-A — decision log

Every decision-matrix entry actually applied during execution, with trigger,
classification, action, evidence and the gate it affects. Rows that did not fire
are listed as `not triggered` so the log is auditable and closed.

The most restrictive rule prevailed; nothing outside the matrix was improvised.
No `X99` event occurred.

One entry (**X22**) was later resolved by an explicit maintainer-approved
exception; see **X22-AMENDMENT** below. The original X22 row is retained
unaltered so the history stays auditable.

**X15** was then resolved by an operator attestation and the full campaign ran; see
**X15-ATTESTATION** and **X21-CAMPAIGN** below.

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
- **Resolution:** the maintainer approved option (a) with hard bounds; see
  **X22-AMENDMENT**. Until that approval landed, G06/G09 stayed blocked.
- **Gate:** G06, G09.

### X22-AMENDMENT — approved heaptrack 1.5.0 startup-preamble exception

- **Authorization:** explicit maintainer fixup specification ("Approved X22
  fixup"). This is the only exception to X22 and it is scoped to the profiling
  transport, its verification, tests and documentation.
- **Implemented bounds** (`benchmarks/pr15e/profile.py`):
  1. **Version-pinned.** `preamble_applies()` requires `heaptrack --version` to
     parse as exactly `heaptrack 1.5.0`. `perf` and any other heaptrack version
     get no exception and any non-JSON line stays an X22 hard stop
     (`test_perf_rejects_heaptrack_style_output`,
     `test_preamble_exception_is_pinned_to_heaptrack_1_5_0`).
  2. **Line-exact and ordered.** `^heaptrack output will be written to
     "(?P<path>.+\.gz)"$` then `^starting application, this might take some
     time\.\.\.$`, anchored with `re.match`. Extra text, reordering, a repeated
     line, a missing line or any other startup message is rejected
     (`test_x22_heaptrack_preamble_variants_are_rejected`,
     `test_x22_heaptrack_missing_preamble_is_rejected`).
  3. **Path-validated.** The path in line 1 must normalise to exactly
     `<capture>/heaptrack.gz` and stay inside the capture directory; `..`, other
     filenames, relative paths and other directories are rejected
     (`test_preamble_validation_rejects_non_designated_paths`, modes
     `wrong-path` / `escape-path`).
  4. **Single use, before the first reply.** Consumption happens inside the first
     `ProfiledTransport.request()` after the request is written, so the exception
     cannot cover any later line; afterwards the parser is permanently strict
     (`test_x22_preamble_after_the_first_response_is_rejected`, and the retained
     `test_t22_profiler_banner_is_a_hard_stop_with_preserved_raw` with an
     unexpected banner).
  5. **Never discarded.** Both lines are written byte-for-byte (with their `\n`
     terminators) to `heaptrack-startup-preamble.txt`, recorded in the capture
     manifest as `heaptrack_startup_preamble` (`path`, `lines`, `bytes`,
     `sha256`, `heaptrack_version`) and also covered by the generic `files`
     digest list. `verify.py` requires the artifact for heaptrack 1.5.0 captures,
     re-validates both lines and the path, re-hashes the bytes against the
     manifest, and rejects the artifact on `perf` or non-1.5.0 captures
     (`test_heaptrack_1_5_0_preamble_is_required`,
     `test_tampered_preamble_content_fails`,
     `test_preamble_artifact_on_a_perf_capture_fails`).
  6. **Everything else unchanged.** Adapter schema/engine/request-id/status,
     oracle equality on every reply, the 30 s response timeout, the 1 MiB line
     cap, single-PID attribution, the 30 s profiler-exit grace and
     process-group teardown are untouched. No PR 15D asset, query implementation
     or production code was modified.
- **Real protocol-only smoke (not a capture):** heaptrack 1.5.0 + the prepared
  real adapter + prepared 10 K `FsDirectory` index →
  `target/pr15e/20261031T133039Z-19ae3d7/smoke-heaptrack-protocol/`: 8/8 replies
  matched the independent oracle, one `heaptrack.gz`, `heaptrack_print` exit 0
  with 10 allocation sites / 760 587 allocations, single adapter PID, 211-byte
  preamble artifact with SHA-256 `973435df…`. No attestation, no measured
  window, no 20-lane matrix → not a qualified profiling capture.
- **Not authorized:** shell pipelines, `heaptrack -p` attach mode, alternative
  profilers, a general stdout filter, per-line skipping beyond these two lines,
  or relaxing any other strict check.
- **Gate:** G06 is structurally unblocked; G05–G09 still require the operator
  attestation.

### X15-ATTESTATION — operator idle window supplied, campaign authorized

- **Trigger:** the maintainer replied to the request for explicit window bounds with
  `now + 2h / now + 3h`, after stating that the idle window was observed and
  profiling may start.
- **Action:** wrote `<run>/attestation.json` for run
  `20261031T164645Z-0f0091c` with `host` = `MSI`,
  `start_utc` = `2026-10-31T17:24:40Z`, `end_utc` = `2026-10-31T20:24:40Z`, the
  operator statement verbatim, plus `operator_reply_verbatim` and `window_basis`
  recording that both offered envelopes were accepted and the **3 h** envelope was
  used. No timestamp was invented: the start is the authorization instant and the
  end is the larger of the two windows the operator offered.
- **Verification:** `load_attestation()` accepted the file (host match, clock inside
  the window, more than `seconds + 120` remaining at every capture start); the
  driver re-checked the window at each profiled loop and at each capture end.
- **Evidence:** `<run>/attestation.json`; capture manifests' `attestation` block and
  `first_utc`/`last_utc`; campaign `2026-10-31T17:24:45Z … 17:44:53Z`.
- **Gate:** G04 (unblocks G05–G09).

### X21-CAMPAIGN — capture campaign, lost samples and artifact integrity

- **Trigger:** the 20 authorized captures were executed serially in the fixed order.
- **Result:** 20/20 `CAPTURED_RAW`; `verify.py` → `EVIDENCE_COMPLETE`, 0 prepare
  violations; `analysis.json` 81 entries, `analysis_valid: true`; sanitized
  manifest published (`adfe7ead…`).
- **X21 (lost samples):** the 100 K `common` `perf` capture reports
  `# Total Lost Samples: 786` and is retained as **`SAMPLED_WITH_LOSS`** with
  201 000 samples. All other `perf` captures report 0 lost samples. No exact-share
  claim is made for that lane.
- **X41 (contamination disclosure):** every `perf`/heaptrack sample includes adapter
  start-up, JSONL protocol handling and the 5 warmups. Attribution is by real stack
  path only; no stage duration is inferred.
- **X35 (overlapping stacks):** nested inclusive frames are reported separately and
  never summed; heaptrack counts are labelled allocation traffic, not bytes or RSS.
- **X33/X34 (unknowns):** the largest heaptrack bucket on 100 K
  `rare`/`medium`/`common` (49.7 M / 27.3 M / 34.9 M) is recorded
  `ATTRIBUTION_UNRESOLVED` because the recorded stack is truncated before any
  Quervant frame. No hotspot is invented for those buckets.
- **X24:** no source, binary, corpus or index changed during the campaign
  (`verify.py` re-derived every digest).
- **X28:** no capture directory was overwritten; no retry was needed.

### F1 — verifier requested-operation exit correction

- **Trigger:** `verify()` derived its process exit code from capture completeness
  alone. With `EVIDENCE_COMPLETE` captures, an explicitly invalid `--analysis` or a
  refused `--publish-manifest` still returned exit `0`, so automation could read a
  refused operation as success. Reproduced pre-fix: `FX-03/04/05/06/10a` failed with
  `0 != 4`.
- **Classification:** authorized fixup (PR 15E-A-F1). Change confined to the final
  exit selection in `benchmarks/pr15e/verify.py::verify()`.
- **Action:** capture-completeness exit keeps precedence (`PARTIAL`/`BLOCKED` → 3,
  `FAILED` → 4) and can never become success; then an explicitly supplied invalid or
  missing analysis returns `EXIT_FAILED` (4) while `verification.json.status` stays
  `EVIDENCE_COMPLETE` and `analysis_valid` stays `false`; then a requested
  publication returns `EXIT_FAILED` (4) when the outcome carries a `code`, is not a
  mapping, has a non-boolean `written`, or lacks a 64-hex `sha256`. A first write and
  an identical-bytes no-op (`written: false` **with** `sha256`) both remain
  `EXIT_OK`. No new status, exit code, schema field or publication logic.
- **Not changed:** capture completeness semantics, `verification.json` schema,
  summary stdout fields, `publish_manifest()`, `validate_analysis()`, argparse,
  `profile.py`, profiler transport (`X22`), oracle, prepared/captured artifacts,
  sampled measurements, `profile-manifest.json`
  (`adfe7eadc2d948ab335e11de78edb4e86691590e464c2660e60eb37e611b4bb7` unchanged) and
  all production Rust.
- **Consequence for existing tests:** `test_t43_publication_refuses_sensitive_content`
  had asserted exit `0` for a refused publication — the defect itself. It now
  requires exit `4` with the same `EVIDENCE_COMPLETE`/`written:false`/`X31`
  assertions (tightened, not weakened).
- **Evidence:** `docs/pr-artifacts/pr-15e-a/test-traceability.md` §5 and
  [`fixup-review-handoff.md`](fixup-review-handoff.md); 90 Python tests pass, one
  opt-in real-adapter integration test passes, PR 15D and workspace gates pass.
- **Gate:** G11 remains **`PENDING_REVIEW`** — the fixup makes the CLI fail closed; it
  does not constitute independent acceptance of the private raw evidence.

### X37 — host authorization missing while deterministic code is complete

- **Trigger:** follows from X15.
- **Classification:** DEFER AND CONTINUE.
- **Action:** committed implementation and evidence stub as
  `IMPLEMENTED_NOT_PROFILED`/`BLOCKED_ATTESTATION`; continued local QA and
  documentation instead of waiting. Resolved by **X15-ATTESTATION** once the
  operator window was supplied.
- **Evidence:** this dossier; `verification.json` `PARTIAL`.
- **Gate:** G04–G09.

### X38 — GitHub CLI credentials invalid, exact-head CI unobservable

- **Trigger:** `gh auth status` → token invalid (gh config `hosts.yml`); no
  `GITHUB_TOKEN`/`GH_TOKEN` in the environment; `gh pr create` → `HTTP 401: Bad
  credentials`.
- **Classification:** DEFER AND CONTINUE.
- **Action:** recorded the exact head, completed every local mandatory gate, and did
  not claim any CI result; the branch was verified pushed at the exact head
  (`git ls-remote` = `0f0091c…`) and a PR body was prepared for the maintainer.
- **Resolution (maintainer session):** PR #82 was opened on `0f0091c`. Its
  exact-head `Rust CI` run #278 completed **successfully** — jobs `rust`
  (formatting, clippy default/all-features, tests default/all-features, production
  line coverage ≥ 85 %, documentation, benchmark build, benchmark scripts,
  whitespace), `msrv` (1.85.0: formatting, clippy, tests) and `rustfs` (real RustFS
  S3 adapter, core remote, M1/M2/M3/M5, fault proxy/crash, critical race ×10) — all
  `success`. Observed unauthenticated via the GitHub API for the exact SHA.
- **Evidence:** PR https://github.com/yduchesne/quervant/pull/82, run
  https://github.com/yduchesne/quervant/actions/runs/41221867714,
  head `0f0091c02b3d7e057f1db10b3a12c06179f1c399`.
- **Gate:** G10 (closed).

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
| X17 | No window expired mid-campaign: the campaign finished 2 h 40 min before the attested end. |
| X18 | Contention probe was never reached (attestation gate first); the probe is exercised only by tests. |
| X19 / X20 / X21 | No capture reached the reporting stage. |
| X22 (post-amendment) | The approved exception is bounded and does not fire for `perf`, other heaptrack versions, or any line after the first reply. |
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
