# PR 15H-B fixup — decision log

| ID | Trigger | Action | Evidence |
|---|---|---|---|
| BF-D01 | Branch/HEAD matched the pinned literals | Continued in place | fixup-preflight |
| BF-D05 | Working tree clean | Proceeded | preflight |
| BF-D10 | Runner/test/source seams matched inspected code | Inserted only the prescribed changes | diff |
| BF-D12 | Sealed original B evidence available | Verified read-only with original tooling | fixup-qa |
| BF-D15 | Original tooling SHA resolves, worktree clean | Used it for historical `--verify-only` | fixup-qa |
| BF-D19 | No production behavior change | No new timed campaign; verification only | fixup-qa |
| BF-D21 | Matching lowercase 40-char tooling identities | `require_same_tooling` returns | BF-T01 |
| BF-D22/D23 | Different/missing/malformed tooling | `RunBlocked(X_TOOLING_SHA)` | BF-T02/T03/T04/T05 |
| BF-D24 | Guard placed before `os.makedirs` | Mock proof no output creation | BF-T07 |
| BF-D26 | Matching campaign still accepted | Original gate math unchanged | BF-T06/T13 |
| BF-D28 | Verify rejects mismatched sealed pair | Guard added before slot derivation | source + BF-T07 |
| BF-D31 | Exact typo in the prefix tuple | Replaced only that literal | BF-T08/T09 |
| BF-D33 | Unique `zzz` payload span | Mutated only its first payload byte | BF-U01–U06 |
| BF-D35 | Three-row ASC fixture fills K+1=2 with worst `bbb` | Proceeded | BF-U01 |
| BF-D37 | Intact `zzz` discarded with no owned tuple | Asserted counters/heap | BF-U01 |
| BF-D39 | Corrupt losing `zzz` yields exact UTF-8 error | Asserted typed error, heap unchanged | BF-U02 |
| BF-D41 | Owned decoder returns the same typed error | Independent oracle asserted | BF-U03 |
| BF-D43 | Repeat failure is idempotent | Second call identical, heap stable | BF-U06 |
| BF-D45 | Test-only constructor is `#[cfg(test)]` | Release build CI green | source/release |
| BF-D50/D51 | Actual docs prefix accepted; old typo/forbidden rejected | Scope tests | BF-T08–T12 |
| BF-D55/D58 | Relevant and full stable/MSRV QA pass | Recorded | fixup-qa |
| BF-D65 | Pinned RustFS healthy | Full matrix executed | fixup-qa |
| BF-D68 | Historical seals verify | Recorded | fixup-qa |
| BF-D71 | No production runtime change, QA passes | Commit narrow fixup on same branch | final report |
| BF-D74/D75 | Clean after commit, no push | Report `CI_PENDING` | final report |

No HARD STOP, DEFER exception, or performance-gate change occurred.
