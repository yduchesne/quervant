# PR 15D reports

No qualified cross-engine report exists yet. The three-engine series is
**BLOCKED** by an unresolvable frozen Tantivy pin (X15) and a missing JDK 21 /
Gradle 8.14.3 toolchain (X14), as recorded in
[`docs/pr-artifacts/pr-15d/qualification.md`](../../../docs/pr-artifacts/pr-15d/qualification.md).

Only validated, sanitized manifest-only summaries may be committed here. Raw
corpora, indexes, logs and contention probes remain under untracked
`target/pr15d/`. Never overwrite a previous qualified report; a new run always
uses a new unique id.
