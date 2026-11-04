# PR 15G-B decision log

**GB_BASE_SHA:** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`

| Rule | Trigger | Action | Evidence / gate |
|---|---|---|---|
| GB-D01 (prior revision) | Old plan required 15G-A merged to `main`; `origin/main` remained at `f44d7f4...` | Revised operator-approved plan supersedes this: 15G-A is qualified on the shared branch and no main merge is required. No PR15F-based branch or cherry-pick was made. | `preflight.md`; shared tip `3329dd8…` |
| GB-D04 | Shared remote tip equals local `GB_BASE_SHA` | Pinned `GB_BASE_SHA=3329dd8…`; no fast-forward needed | `preflight.md`; GB-A00 |
| GB-D35 | Operator instructs assume-idle and authorizes `--idle-confirmed` | Timed B campaign may pass the flag; actual runner contention must still be `clear` | To be recorded in performance evidence |
| GB-D42 | Hosted CI/PR access is limited to the existing umbrella PR | Use existing PR #86; no B-only PR | To be recorded |

## Implementation and qualification decisions

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| GB-D04 | Shared remote tip equaled local `GB_BASE_SHA=3329dd8…` | Pinned pre-B baseline; no fast-forward required | `preflight.md` |
| GB-D07 | Two test-internal failures during development (capture helper capacity assertion; shared global panic flag racing parallel tests) | Fixed only test support (fallible reserve; thread-local hook); no production contract change | focused tests PASS |
| GB-D25 | `access_budget` must be attached only after metered admission | Added `with_access_budget` after `MetadataMeter::finalize`; unmetered constructors leave `None` | `gbu19/gbu24/gbu25` |
| GB-D35 | Operator instructed assume-idle and authorized `--idle-confirmed`; actual probes subsequently clear | Ran full nine-lane pair with the flag; preserved all probe logs and labelled the authorization as assumed, not measured idle | `performance-qualification.md` |
| GB-D40 | A test-only witness commit (`4e7949a`) landed after the first exploratory campaign measured `0d0817e` | Discarded the earlier campaign as non-final; reran a complete new baseline/candidate campaign on `4e7949a` | final campaign `target/pr15g-b/qualified-pair-4e7949a-…` |
| GB-D41 | Closure docs postdate measured `4e7949a` | Verify final `git diff --name-only` is docs-only; measured source identity remains `4e7949a` | final report |
| GB-D42 | Existing umbrella PR #86, hosted CI availability | Push shared branch normally; no B-only PR; report exact-head CI status honestly | PR #86 |
