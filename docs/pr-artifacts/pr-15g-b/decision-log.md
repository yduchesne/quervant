# PR 15G-B decision log

**GB_BASE_SHA:** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`

| Rule | Trigger | Action | Evidence / gate |
|---|---|---|---|
| GB-D01 (prior revision) | Old plan required 15G-A merged to `main`; `origin/main` remained at `f44d7f4...` | Revised operator-approved plan supersedes this: 15G-A is qualified on the shared branch and no main merge is required. No PR15F-based branch or cherry-pick was made. | `preflight.md`; shared tip `3329dd8…` |
| GB-D04 | Shared remote tip equals local `GB_BASE_SHA` | Pinned `GB_BASE_SHA=3329dd8…`; no fast-forward needed | `preflight.md`; GB-A00 |
| GB-D35 | Operator instructs assume-idle and authorizes `--idle-confirmed` | Timed B campaign may pass the flag; actual runner contention must still be `clear` | To be recorded in performance evidence |
| GB-D42 | Hosted CI/PR access is limited to the existing umbrella PR | Use existing PR #86; no B-only PR | To be recorded |
