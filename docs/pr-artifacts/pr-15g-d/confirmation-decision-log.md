# PR 15G-D confirmation decision log

| Rule | Trigger | Action | Evidence |
|---|---|---|---|
| CF-D01 | A/B/C exact ancestry, clean worktrees | Created detached measurement worktrees under ignored target | `confirmation-preflight.md` |
| CF-D10 | Frozen corpus/adapter/oracle hashes verified | Reused frozen helper unchanged | setup manifest |
| CF-D15 | Per-N index digests equal across A/B/C | Ran fixed 18-slot schedule | raw manifest |
| CF-D19 | Standing assumed-idle authorization | Recorded truthful authorization basis; real probes required | `raw/authorization.json` |
| CF-D20 | Every before/after probe `clear` | Retained all 18 slots | raw slots |
| CF-D22 | Literal 3×6 mirrored schedule | Fixed sequence, no randomization | `confirm.py`/tests |
| CF-D31/33 | Within-block and A cross-block drift within 1.25/1.50 | Proceeded to verdicts | sanitized drift |
| CF-D35/36 | Sign-consistency verdicts, mixed -> INCONCLUSIVE | Computed three pairwise comparisons independently | `confirmation-performance.md` |
| CF-D37/38 | D1 target not `B_FASTER`; guardrail `A_FASTER` | Marked D1_NOT_RECONFIRMED; no automatic rollback | CF-P01/P02 |
| CF-D39/40 | D2 incremental target PASS, guardrail FAIL | Marked D2 incremental not fully reconfirmed | CF-P03/P04 |
| CF-D41/42 | Cumulative target PASS, guardrail FAIL | Reported cumulative separately; not full acceptance | CF-P05/P06 |
| CF-D43/44 | Sanitizer passed; no prohibited strings | Published sanitized report only | `confirmation-performance.md` |
| CF-D47 | CI status not yet observed for final docs HEAD | Recorded as pending, not green | final report |
| CF-D49 | Local RustFS independent from confirmation | Existing Rust tests retained; no fake service | existing logs/CI |
| CF-D55 | Historical D1/D2 reports exist | Preserved read-only; appended confirmation | docs diff |
| CF-D58 | No post-result selective retry | Single complete campaign; retained NOT_RECONFIRMED | raw stage root |
