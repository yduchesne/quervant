# Superseded receipts

`8b6f827` series: produced against the first `TESTED` commit
`8b6f827be93a422e858609e20c0fb96647c7c302`. After the source audit showed a
comment-only difference inside the `if !DEFERRED` branch, the accepted eager
statement block was restored verbatim and a new immutable `TESTED` commit
`6ea6b7ce049d613a29864f1eae53dea5fd61e75f` was created. Every receipt in
`../receipts/` was regenerated against the new `TESTED`.

The baseline receipts (`../receipts-baseline/`) and the red receipt
(`../receipts-red/`) are unaffected by that adjustment and remain current.

Nothing in this directory is acceptance evidence; it is retained so that no
attempt is silently overwritten.
