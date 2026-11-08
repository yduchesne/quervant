# PR 15I-B — decision log

| timestamp_utc | rule_id | trigger | source_sha | evidence_path_sha256 | action | gate | owner |
|---|---|---|---|---|---|---|---|
| 2026-11-07 | IB-D01 | `origin/main` == reviewed HEAD `691b699`, clean tree, 15I-A merged ancestor | `691b6993d15f568617f9302cca0a4677bc50df3e` | git ancestry | branched `dev/pr15i-b-stored-blocks` at BASE | §1 preflight | maintainer |
| 2026-11-07 | IB-D06 | Old verifier qualified a fixture missing `A/100000-run2` | `691b6993d15f568617f9302cca0a4677bc50df3e` | `target/pr15i-b/p0/pre-fix-repro.json` | applied mandatory 12-rebuild rule | P0 | reviewer |
| 2026-11-07 | IB-D06 | Old verifier qualified a fixture with `raw/unexpected` symlink to outside | `691b6993d15f568617f9302cca0a4677bc50df3e` | `target/pr15i-b/p0/pre-fix-repro.json` | added exact raw directory traversal | P0 | reviewer |
| 2026-11-07 | IB-D09 | All 12 original rebuild directories present and equal to the seal | `691b6993d15f568617f9302cca0a4677bc50df3e` | receipt `verification-15ib-p0-01.json` | accepted four `INDEPENDENTLY_RE_VERIFIED` groups | P0 | reviewer |
| 2026-11-07 | IB-D12 | Original seal unchanged, receipt qualified | `691b6993d15f568617f9302cca0a4677bc50df3e` | `af7f6c1a...b2f` before/after | P0-only commit; proceed to P1 | P0 | reviewer |
