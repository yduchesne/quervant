# PR 15H-D — corrigendum: sealed baseline title

This is a **presentation-only** corrigendum. No sealed raw/sanitized JSON was
edited, no timing was rerun, and the D disposition is unchanged.

## Sealed baseline label

The sealed D baseline Markdown
`target/pr15h-d/baseline-01/sanitized/baseline.md` has SHA-256
`eb4f3eb3baac7be228c3fbea51ff94b87eac5be00b509947ec47bece8a6f07be`
and retains the mechanically copied historical title “PR 15H-B”. Its recorded
source/tooling SHA (`c802f965…`), six D lanes, corpus and seal are D-specific.

The sealed D paired Markdown
`target/pr15h-d/paired-01/sanitized/performance.md` (SHA-256
`59887fd134cb3dc15ab2da2fdb42d6ba6abf2c6bc229a3421c6d286239232660`) already
carries the correct “PR 15H-D” title.

The original bytes are preserved. The corrected human-facing view is
`docs/pr-artifacts/pr-15h-d/derived-summary.md`; raw seals remain authoritative.

## Binding statistic

D gating is the **conventional even-n median** of four unrounded `A − B` deltas
(`0.5*(sorted[1]+sorted[2])`). The lower median is informational only. Using
rounded display values does not change any gate.
