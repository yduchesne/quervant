# PR 15G-C fixup decision log

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| GF-D01 | Shared HEAD `850e0f3`, clean, ancestors verified | Pinned pre-C A `018fdd7`; no branch/main change | `preflight.md` |
| GF-D06 | Failed C reports present | Preserved read-only; new fixup namespace | `docs/pr-artifacts/pr-15g-c/` |
| GF-D07 | Four postings scans found | Replaced with prescribed two-pass design | `investigation.md` |
| GF-D09/D10 | Privileged profile/allocation data unavailable | Recorded unavailability; proceeded source-backed | `investigation.md` |
| GF-D16 | `Posting.freq` is u64; failed C cast to u32 | Pass u64 to bm25, exact f64 to admission | implementation |
| GF-D22 | Missing field stats | Score 0.0 with Some(0.0) | implementation |
| GF-D44/D45 | Assume-idle authorization; actual probes | Full campaign will use `--idle-confirmed` only if probes clear | performance report |

## Outcome decisions

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| GF-D21/D23 | Two-pass design still slower; no O(M) scratch introduced | Preserved bounded design through one campaign; no extra tuning | `performance-qualification.md` |
| GF-D24/D25 | Candidate error deferral implemented and tested | Later invalid score wins; first candidate error retained otherwise | GF-U22/U23 |
| GF-D29 | Test-only injection needed | Added thread-local `#[cfg(test)]` hooks only | GF-U21/U22/U31 |
| GF-D49 | Qualified fixup campaign failed GF-P01/P04 | Applied only prescribed §8.4 rollback; no retime/tune | `rollback.md` |
| GF-D50 | Rollback source exact and QA/CI pending | Marked C NOT ACCEPTED with safe rollback | `rollback.md` |
| GF-D52 | No executable change after measured fixup candidate except prescribed rollback | Rollback is the only post-result source change; C result remains historical | `rollback.md` |
| GF-D53 | Final docs differ from rollback code | Will verify docs-only diff and exact-head CI | final report |
