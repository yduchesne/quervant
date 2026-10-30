# PR 15D-B — S0 preflight record

**Status:** CHECKED (preflight only). No measurement has been performed.

**Executed by:** coding agent. **Date of record:** see the commit timestamp of
this file. No human idle attestation exists for any host.

## Source lock verification

| Item | Command | Observed |
|---|---|---|
| Repository root | `pwd` | `/home/yduchesne/Dev/Github/yduchesne/quervant` |
| `HEAD` | `git rev-parse HEAD` | `8caca7682cc23c7b595fba049608e7fd843cd4dd` |
| `main` | `git rev-parse main` | `8caca7682cc23c7b595fba049608e7fd843cd4dd` |
| `origin/main` | `git ls-remote --heads origin main` | `8caca7682cc23c7b595fba049608e7fd843cd4dd` |
| Merge base | `git merge-base HEAD main` | `8caca7682cc23c7b595fba049608e7fd843cd4dd` |
| Worktree | `git status --porcelain` | empty (clean) |

`HEAD == main == origin/main == merge-base` and both equal the plan's source
lock, so **X01** applies (PR #79 merged, main matches the source lock) and the
preflight may begin.

PR #79 is merged: the locked commit is literally
`Merge pull request #79 from yduchesne/dev/pr15d-comparative-qualification`.

## Required path inventory

All paths named in plan §1 exist at the source lock:

- `.github/workflows/ci.yml`
- `benchmarks/pr15d/spec/pr15d_v1.{json,md}`
- `benchmarks/pr15d/protocol/schema.json`
- `benchmarks/pr15d/corpus/{generate.py,oracle.py}`
- `benchmarks/pr15d/adapters/{quervant,tantivy,lucene}`
- `benchmarks/pr15d/harness/{run.py,smoke.py,validate.py,aggregate.py,test_pr15d.py}`
- `benchmarks/pr15d/README.md`, `benchmarks/README.md`
- `benchmarks/scripts/test-scripts.sh`
- `docs/pr-artifacts/pr-15d/`, `docs/ROADMAP_V01.md`, `docs/BENCHMARKING.md`,
  `docs/TESTING.md`

## Frozen artifact digests at the source lock

Recorded so later drift is detectable. These files are **not** modified by this
PR (I02).

```
ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466  benchmarks/pr15d/spec/pr15d_v1.json
a0e72ac93bab4fdc0c2e6b8aaebb20231721415ea7ddaf8963da1263c54d7cb0  benchmarks/pr15d/spec/pr15d_v1.md
62bb81ad2b96162ea1d3c7eef656fa62b48ff2205c819e8715d6bb2b2f2a9eb8  benchmarks/pr15d/protocol/schema.json
d0bfd0ac7f63509f20454dd8ab96dcb50075a5293235fe894b14b60e5b86851d  benchmarks/pr15d/corpus/generate.py
4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2  benchmarks/pr15d/corpus/oracle.py
8be6c21e5a2ac41a3dc12c17ab8bc5e91080c689323f7f05015919c01ff31243  benchmarks/pr15d/harness/run.py
ffc6f7f8254744709d16b68e0ab5fcb835bb8b7cf823a9cd937552776570bdd4  benchmarks/pr15d/harness/validate.py
751cf112a140685c3cfc1c2dfd24e7c98cfd95862bccf9fc57ad85de6db82794  benchmarks/pr15d/harness/aggregate.py
f57da56d6966747a6762a85747624f4b51a8a1004e33f2f84efef3c5dd9a11bf  .github/workflows/ci.yml  (pre-change)
af235e2ec73c5b980b7c1562512cad85fb0a8b5e54aad7d994eb21533cdbcaa5  benchmarks/pr15d/harness/smoke.py  (pre-change)
8e5367333ee772b9a77a5ca0cc172276dfd539b5380e0f5640dc6b57de9d8a0c  benchmarks/pr15d/harness/test_pr15d.py  (pre-change)
```

`run.py`, `validate.py`, `aggregate.py`, the frozen spec, the protocol schema,
the corpus generator and the oracle are read-only for this PR (I02, I16). Only
`smoke.py` and `test_pr15d.py` are touched, inside the authorized S2 boundary.

## Standard CI job inventory at the source lock

`ci.yml` declared exactly four jobs: `rust`, `msrv`, `rustfs`, `pr15d-adapters`.
Triggers were `push` (branch `main`) and `pull_request`; permissions were
`contents: read`.

## Branch protection / ruleset audit (S1 gate)

`gh` credentials on this host are invalid (`HTTP 401 Bad credentials`), so the
classic branch-protection API is unreadable. The repository is public, so the
ruleset API was read unauthenticated instead:

- `GET /repos/yduchesne/quervant/rulesets` → one active ruleset,
  `Main Branch Protection` (id `24886640`), target `~DEFAULT_BRANCH`.
- `GET /repos/yduchesne/quervant/rulesets/24886640` → rules are `deletion`,
  `non_fast_forward`, and `required_status_checks` whose only entry is
  `{ "context": "rust", "integration_id": 15368 }`.
- `strict_required_status_checks_policy: false`.

**Conclusion:** `pr15d-adapters` is **not** a required status check, so **X11**
and **X12** do not apply and the isolated job may be relocated. `rust` remains
the only required check and is unchanged.

## Verified prerequisite: the A1 comparative job succeeds on the source lock

Unauthenticated Actions API, run of `Rust CI` with
`head_sha=8caca7682cc23c7b595fba049608e7fd843cd4dd` (run id `41124428333`):

| Job | Status | Conclusion |
|---|---|---|
| `pr15d-adapters` | completed | **success** |
| `rustfs` | completed | **success** |
| `rust` | in_progress | (not yet concluded when read) |
| `msrv` | in_progress | (not yet concluded when read) |

The comparative adapter job is proven working on the current main, which is the
S1 prerequisite. `rust`/`msrv` were still running at read time; per **X40** that
defers the *acceptance* decision, not the source work.

## Toolchain and host state observed

| Item | Observed |
|---|---|
| Python | 3.12.3 |
| PyYAML (local only) | 6.0.1 |
| `gh` CLI | 2.101.0, token invalid |
| `git` transport | SSH to `origin` works (`git ls-remote` succeeded) |
| Filesystem | Linux native (not drvfs/Windows) |
| Java / Gradle | not probed yet for a campaign; no measurement attempted |

## Branches

`dev/pr15d-b-comparison-qualification` did not exist locally or on `origin`, so
**X05** applies and the branch was created from the locked `main`
(`8caca7682cc23c7b595fba049608e7fd843cd4dd`). No existing work was reset.

## Preflight outcome

Preflight **PASSES** for source, scope and CI-structure work. It does **not**
authorize measurement:

- **X43 DEFER** — `gh` credentials are invalid, so workflow dispatch and PR
  creation cannot be driven by the agent; actual Actions runs for the new
  workflow remain unobserved.
- **X40 DEFER** — exact-head `rust`/`msrv` had not concluded at read time.
- **X25 DEFER** — no human has attested an idle host for any measurement window,
  so the measurement phase (S4) stays unstarted and `--idle-confirmed` was never
  and will never be passed by the agent.
