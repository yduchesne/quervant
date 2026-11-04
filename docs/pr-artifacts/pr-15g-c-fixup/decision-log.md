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
