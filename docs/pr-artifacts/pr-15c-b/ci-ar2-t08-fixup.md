# AR2-T08 CI portability fixup — evidence

Status: **NOT ACCEPTED.** Implementation and local verification are complete;
exact-new-head GitHub `rust` / `msrv` / `rustfs` re-verification and independent
reviewer acceptance are outstanding. This document is evidence only: it changes no
qualification metric and rewrites no prior report paragraph.

Plan: `QUERVANT_PR15C_B_AR2_T08_CI_FIXUP_PLAN(2).md`.
PR #78, `dev/pr15c-b-performance-qualification` → `main`.

## 1. Original failure

| Item | Value |
|---|---|
| Failing run | https://github.com/yduchesne/quervant/actions/runs/41058925753/job/124073410911?pr=78 |
| Job | `rust` — format, Clippy, tests, ≥85 % coverage, docs and bench build had already passed |
| Failing step | `Benchmark scripts` → `bash benchmarks/scripts/test-scripts.sh` |
| Reported output | `fatal: invalid object name 'origin/main'.` / `FAIL: profile-pr15b.sh must stay unmodified` / `script tests: 104 passed, 1 failed` |
| Pre-fix PR head | `f9ab245024f10a8eabf92e09f2bdc5f427e024c2` (confirmed as `refs/pull/78/head` and `refs/heads/dev/pr15c-b-performance-qualification` over the remote) |
| Fix HEAD | `68b508dee7b95b941e7dddfa5d42984b6684f635` |
| Immutable baseline | `42b19445dd79a90d8701b4306e305c6e4e44cd57` |
| Branch / tree state at edit time | `dev/pr15c-b-performance-qualification`, clean |

### Local reproduction of the exact CI failure (S0.6)

Performed in a disposable clone under `/tmp/ar2-t08/repo` — a fresh `git init` +
`git fetch --no-tags <repo> f9ab245…` + `checkout FETCH_HEAD`, i.e. **no
`refs/remotes/origin/main`** but the baseline object present, which is the CI
shape:

```text
HEAD=f9ab245024f10a8eabf92e09f2bdc5f427e024c2
origin/main -> fatal: Needed a single revision        (ABSENT, as in CI)
baseline object -> present

$ bash benchmarks/scripts/test-scripts.sh
== AR2-T08 frozen tooling identity and workload invariants ==
fatal: invalid object name 'origin/main'.
FAIL: profile-pr15b.sh must stay unmodified
script tests: 103 passed, 1 failed
```

The signature (`fatal: invalid object name 'origin/main'` plus the profiler
freeze failure) is identical to the CI log. Observed totals differ by one from the
plan's quoted `104 passed, 1 failed`: locally the suite reports 104 checks
(103 + 1) while CI reports 105, the extra check being environment-dependent in an
earlier section. The failure lines themselves are byte-identical; this discrepancy
is recorded rather than explained away.

### Both defects confirmed in source (pre-fix)

```bash
$ sed -n '851,852p;870,871p' benchmarks/scripts/test-scripts.sh   # f9ab245
run_expect "frozen workload contract unchanged" 0 \
    bash -c 'git diff --quiet origin/main -- … 2>/dev/null || [[ -z "$(git status --porcelain -- …)" ]]'
if diff <(git show origin/main:benchmarks/scripts/profile-pr15b.sh) \
    benchmarks/scripts/profile-pr15b.sh >/dev/null; then ok; else bad "…"; fi
```

Defect 1 — the harness depended on a moving `origin/main` ref that an Actions
checkout does not create. Defect 2 — the workload assertion's fallback
(`git diff … || clean working tree`) returned **PASS** whenever the tree was clean,
even for a **committed** frozen-workload or dataset change; and the process
substitution could hide `git show`'s exit status.

## 2. The two hunks

`benchmarks/scripts/test-scripts.sh` (AR2-T08 only; 30 insertions, 6 deletions):

```diff
 echo "== AR2-T08 frozen tooling identity and workload invariants =="
+AR2_FROZEN_BASE='42b19445dd79a90d8701b4306e305c6e4e44cd57'
+if git cat-file -e "${AR2_FROZEN_BASE}^{commit}" 2>/dev/null \
+    && git cat-file -e "${AR2_FROZEN_BASE}:benchmarks/scripts/profile-pr15b.sh" 2>/dev/null \
+    && git cat-file -e "${AR2_FROZEN_BASE}:benchmarks/workloads/pr15b_v1.md" 2>/dev/null; then
+    ok
+else
+    bad 'AR2-T08 immutable baseline commit or frozen paths unavailable'
+fi
 run_expect "canonical fixture digest unchanged" 0 \
     bash -c '[[ "$(sha256sum benchmarks/datasets/pr15a_v1.json | cut -d" " -f1)" == "…" ]]'
-run_expect "frozen workload contract unchanged" 0 \
-    bash -c 'git diff --quiet origin/main -- … 2>/dev/null || [[ -z "$(git status --porcelain -- …)" ]]'
+run_expect 'frozen workload contract unchanged' 0 \
+    git diff --quiet --exit-code "$AR2_FROZEN_BASE" HEAD -- \
+        benchmarks/workloads/pr15b_v1.md benchmarks/datasets
+run_expect 'frozen workload worktree unchanged' 0 \
+    git diff --quiet --exit-code HEAD -- …
+run_expect 'frozen workload staged changes absent' 0 \
+    git diff --cached --quiet --exit-code HEAD -- …
+if [[ -z "$(git ls-files --others --exclude-standard -- … )" ]]; then
+    ok
+else
+    bad 'untracked frozen workload/dataset files present'
+fi
 …
-if diff <(git show origin/main:benchmarks/scripts/profile-pr15b.sh) \
-    benchmarks/scripts/profile-pr15b.sh >/dev/null; then ok; else bad "…"; fi
+AR2_FROZEN_PROFILE_TMP="$(mktemp)" || exit 1
+if git show "$AR2_FROZEN_BASE:benchmarks/scripts/profile-pr15b.sh" \
+        >"$AR2_FROZEN_PROFILE_TMP" \
+    && cmp -s -- "$AR2_FROZEN_PROFILE_TMP" benchmarks/scripts/profile-pr15b.sh; then
+    ok
+else
+    bad 'profile-pr15b.sh must stay unmodified'
+fi
+rm -f -- "$AR2_FROZEN_PROFILE_TMP"
```

`.github/workflows/ci.yml` (`jobs.rust.steps[0]` only):

```diff
       - uses: actions/checkout@v4
+        with:
+          fetch-depth: 0
```

`grep -n origin/main benchmarks/scripts/test-scripts.sh` now returns nothing
(rule X38), so no moving ref remains.

## 3. Immutable baseline and checkout-depth proofs

```text
$ git cat-file -e 42b19445dd79a90d8701b4306e305c6e4e44cd57^{commit}   -> OK
$ git rev-parse 42b19445dd79a90d8701b4306e305c6e4e44cd57^{commit}
42b19445dd79a90d8701b4306e305c6e4e44cd57
$ git rev-parse 42b1944…:benchmarks/scripts/profile-pr15b.sh  -> 286a30347737e1883dfab9190fc32bab8b4a1dd0
$ git rev-parse 42b1944…:benchmarks/workloads/pr15b_v1.md     -> e4ec0c2626bd81d1111236fecf6d75aa49718307
$ git rev-parse 42b1944…:benchmarks/datasets/pr15a_v1.json    -> 90828bbd1bc3f4a4b0a0bb59029fe93bb64cd2f9
```

`ci.yml` parsed as YAML after the edit:

| job | checkout steps | `with` |
|---|---:|---|
| `rust` | 1 | `{'fetch-depth': 0}` |
| `msrv` | 1 | none |
| `rustfs` | 1 | none |

So the fix reason is **reference-commit availability**, not `origin/main`.

## 4. Adversarial probes (S3)

Harness: `target/ar2-t08/probes.sh` (temporary, untracked) clones a disposable
repo per probe (`git clone --local` of an isolated `git init` + `git fetch` base at
`f9ab245` with **no** `refs/remotes/origin/main`), applies exactly one mutation,
and runs `target/ar2-t08/driver.sh`, which sources the **real extracted AR2-T08
block** (`target/ar2-t08/ar2-t08-block.sh`, lines 848–898 of the modified
`test-scripts.sh`, bounded by the `AR2-T08` echo and the final
`rm -f -- "$AR2_FROZEN_PROFILE_TMP"`) under the pre-existing `ok` / `bad` /
`run_expect` helpers. The primary checkout was never mutated.

| Probe | Setup | Exit | Observed | Verdict |
|---|---|---|---|---|
| CI-T01 | clean clone, baseline present, `origin/main` absent (precondition asserted in-harness) | 0 | `block: 9 passed, 0 failed` | **AS EXPECTED (PASS)** |
| CI-T02 | depth-1 isolated repo, baseline object absent | 1 | `6 passed, 3 failed`; explicit `AR2-T08 immutable baseline commit or frozen paths unavailable` | **AS EXPECTED (FAIL, no fallback PASS)** |
| CI-T03 | committed change to `benchmarks/workloads/pr15b_v1.md`, clean tree | 1 | `FAIL: frozen workload contract unchanged (exit 1, expected 0)` | **AS EXPECTED** |
| CI-T04 | committed change to `benchmarks/datasets/pr15a_v1.md`, clean tree | 1 | `FAIL: frozen workload contract unchanged (exit 1, expected 0)` | **AS EXPECTED** |
| CI-T05 | committed change to `benchmarks/scripts/profile-pr15b.sh`, clean tree | 1 | `FAIL: profile-pr15b.sh must stay unmodified` | **AS EXPECTED** |
| CI-T06 | unstaged workload change | 1 | `FAIL: frozen workload worktree unchanged (exit 1, expected 0)` | **AS EXPECTED** |
| CI-T07 | staged dataset change | 1 | `FAIL: frozen workload worktree unchanged` + `FAIL: frozen workload staged changes absent` (`7 passed, 2 failed`) | **AS EXPECTED** |
| CI-T08 | unstaged profiler change | 1 | `FAIL: profile-pr15b.sh must stay unmodified` | **AS EXPECTED** |
| CI-T09 | untracked file under `benchmarks/datasets/` | 1 | `FAIL: untracked frozen workload/dataset files present` | **AS EXPECTED** |
| CI-T10 | canonical digest + 30 lane identifiers still validated | 0 | digest and 30-lane checks pass inside the CI-T01 set | **AS EXPECTED (PASS)** |
| CI-T11 | invalid/missing ref | 128 | `fatal: bad object 42b19445…` propagates; the harness does not swallow it | **AS EXPECTED** |
| CI-T12 | `ci.yml` structure | 0 | only `rust` has `fetch-depth: 0`; `msrv`/`rustfs` untouched | **AS EXPECTED** |
| CI-T13 | full `bash benchmarks/scripts/test-scripts.sh` on the real checkout | 0 | **`script tests: 108 passed, 0 failed`** (was 104; +4 fail-closed checks, none removed or weakened) | **AS EXPECTED** |
| CI-T14 | `git diff --check` + changed-file allowlist | 0 | clean; only `.github/workflows/ci.yml` and `benchmarks/scripts/test-scripts.sh` | **AS EXPECTED** |

Probe harness totals: **21 assertions, 0 mismatches**, runtime 2.4 s
(`target/ar2-t08/results.txt`, per-probe logs in `target/ar2-t08/probes/`).

## 5. Full local gate results (S4)

| Command | Exit | Result |
|---|---|---|
| `bash -n benchmarks/scripts/test-scripts.sh` | 0 | **PASS** |
| `bash benchmarks/scripts/test-scripts.sh` | 0 | **PASS — 108 passed, 0 failed** |
| `cargo fmt --all -- --check` | 0 | **PASS** |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | **PASS** |
| `cargo +1.85.0 check -p quervant-core` | 0 | **PASS** |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | **PASS** |
| `cargo test --workspace --all-targets --all-features` | 0 | **PASS — 2171 passed / 0 failed / 75 ignored** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 0 | **PASS — 2173 passed / 0 failed / 75 ignored** |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | **PASS — 91.81 % lines** (51738 lines, 4237 missed) |
| `cargo doc --workspace --all-features --no-deps` | 0 | **PASS**, 0 warnings |
| `cargo bench --workspace --no-run` | 0 | **PASS** |
| `git diff --check` | 0 | **PASS** |

The observed pass-count difference between the stable (2171) and MSRV (2173) runs
is the pre-existing profile-dependent test-count difference, not a regression:
both report **0 failed**, and neither is lower than the previously recorded
all-features counts.

## 6. Untouched evidence and scope

```text
$ git diff --stat f9ab245 68b508d -- crates Cargo.toml Cargo.lock benchmarks/reports \
    benchmarks/datasets benchmarks/workloads benchmarks/scripts/profile-pr15b.sh \
    benchmarks/scripts/validate-pr15b.py benchmarks/scripts/run-pr15b.sh \
    benchmarks/scripts/pr15cb-profiler-evidence.py \
    docs/pr-artifacts/pr-15c-b/qualification.md docs/pr-artifacts/pr-15c-b/comparison-qualified.md
(empty)
$ git diff --name-only f9ab245 68b508d
.github/workflows/ci.yml
benchmarks/scripts/test-scripts.sh
```

- The six qualified trials were **not** re-run, relabelled or overwritten. The
  measured commits remain `f7d6be721ba625cbd90f24cfbcd8551cc8ba309a` (before) and
  `04ad3509c86d08fe296adde1d67c19aa7c7f2651` (after), still resolvable in their
  worktrees; the published aggregates, comparison JSON/Markdown and
  `qualification.md` are byte-unchanged.
- No production `.rs`, dependency, `Cargo.lock`, fixture, workload, lane, oracle,
  digest, Criterion setting, validator, comparator, evidence file or qualification
  rule was modified. No benchmark was timed during this fixup.
- `docs/TESTING.md` still carries its pre-existing conflict markers; not edited
  (rule X33).

## 7. Gate classification

| Gate | Status |
|---|---|
| Local script + Rust + MSRV + coverage + doc + bench-build gates | **PASS** |
| Adversarial probes CI-T01–CI-T14 | **PASS (21/21 assertions)** |
| Real RustFS locally | **BLOCKED-ENVIRONMENT** — `QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance: NotPresent`; no container runtime; `127.0.0.1:9000` refuses connections. Unchanged by this fix. |
| GitHub Actions status query | **BLOCKED-ENVIRONMENT (auth)** — `gh auth status` reports the configured token is invalid, so CI status at `f9ab245`/`68b508d` could not be queried by the agent. Read-only `git ls-remote` confirms the remote PR head; the fix commit `68b508d` is **local only and has not been pushed**. |
| Exact-new-head `rust` / `msrv` / `rustfs` | **PENDING** — required before acceptance |
| Independent reviewer acceptance | **NOT GIVEN** |
| Merge / roadmap DONE | **NOT DONE** |

## 8. Acceptance status

**NOT ACCEPTED.** Outstanding, in order:

1. Push `68b508d` to `dev/pr15c-b-performance-qualification` (no force push) and
   let `rust`, `msrv` and `rustfs` run at that exact head; all three must report
   SUCCESS with the `Benchmark scripts` step green.
2. Independent reviewer confirmation of CI-I01–CI-I10 against the exact head,
   including that this fixup weakens no freeze guarantee.
3. Only then merge. Merge and roadmap DONE remain separately authorised human
   actions.
