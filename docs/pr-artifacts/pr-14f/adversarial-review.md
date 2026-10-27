# PR 14F — adversarial review and negative evidence

**Verdict:** the benchmark campaign is **qualified** (3 of 3 trials, validator
and strict auditor PASS) at source SHA `7df492023397a512e400b03865a989020eff1430`.
The raw evidence package is deterministic and all checksums verify, and the
maintainer uploaded it to Google Drive with a matching declared SHA-256. PR #67
heads `4c94ba8`, `bd1fed7` and `8887541` all passed `rust`, `msrv` and `rustfs`.
PR 14F is **not accepted**: the current binding head has no CI result yet, and
there is no independent human review or merge authorization. Campaign 1 at
`162cbfea…` failed on a harness path defect and is disclosed, not hidden. This
document is an agent self-review, not independent review.

## 1. Primary negative evidence and residual gaps

1. **The durable copy is operator-attested, not agent-verified.** A
   deterministic 21-member `tar.gz` (`6cef9c71…8fe66d`, 15,491 bytes) exists
   under ignored `target/`; its checksums verify and a rebuild is
   byte-identical. The maintainer uploaded it to Google Drive and declared the
   same SHA-256. The agent could not re-download it without Google credentials
   (public endpoints returned a sign-in page), so remote integrity is
   operator-attested. This is a verification limitation, not a hash mismatch.
2. **Three heads are green; the current binding head is not yet verified.**
   PR #67 heads `4c94ba8` (run 40424504536), `bd1fed7` (run 40441448948) and
   `8887541` (run 40443185707) passed `rust`, `msrv` and `rustfs` (verified via
   the public GitHub API because local `gh` auth is invalid). The current
   documentation binding commit advances the head again; its runs are pending.
3. **No independent review or merge authorization.** The agent’s artifacts and
   this self-review are not a substitute for an independent human reviewer.
4. **Campaign 1 failed.** At `162cbfea…`, t1 ran correctly but the wrapper
   aborted because the relative report directory resolved under the cargo
   package working directory. t2/t3 never ran. The defect was fixed only after
   operator approval, with a new source lock and three fresh trials. The failed
   t1 is preserved and hashed; it was not promoted.
5. **Attestation timing.** The operator supplied the idle attestation before
   campaign 1. The corrected campaign was executed under the same explicit
   three-trial authorization after the operator approved the fix, with the host
   independently observed idle and every live contention check `clear`. A strict
   reviewer may still require a fresh attestation for a future campaign; this is
   disclosed as a process gap, not as fabricated data.
6. **No cross-engine or SLO evidence.** The workload is Quervant-local vs
   Quervant-RustFS only; the report makes no superiority or production-tail
   claim.

## 2. Harness and evidence gaps

| Gap | Severity | Detail / disposition |
|---|---|---|
| Relative report dir vs cargo cwd | **Resolved** | Campaign 1 found it; approved absolute-path fix at `7df4920`; shell tests now assert the absolute path |
| Package durability | **Resolved (operator-attested)** | Durable Google Drive copy with matching declared SHA-256; agent re-download blocked by Google authentication |
| Embedded manifest snapshot | Low | The package embeds the pre-archival manifest; the repository manifest records the package hash. The hash cannot be embedded in the package without self-reference |
| New-head CI | Medium | `4c94ba8`, `bd1fed7` and `8887541` checks are immutable and green; the current binding commit needs its own runs |
| `QUERVANT_P4_IDLE_CONFIRMED` truthiness | Medium | Runner uses `var(...).is_ok()`, so `0` reads as true. Qualified runs always set `1`; no diagnostic run was made. Fixing the runner is outside the approved scope |
| Auditor input binding | Medium | The auditor validates a report’s `raw_csv` by path/content, but the report JSON contains no CSV hash. The manifest records hashes; a later check must verify them. A substituted CSV with consistent checks is not cryptographically bound to the report |
| “Verify file hash in manifest” sequencing | Low | The audit runs before the manifest exists; hashes are computed and the manifest records them. Manifest comparison is a later invariant |
| Qualified `--trials` restriction | Low | Qualified mode rejects `--trials` ≠ 3; this prevents an unpublishable campaign but is stricter than the parser range |
| Contention detector scope | Medium | `/proc` sees this WSL guest only, not the Windows host or other WSL guests. `clear` is best-effort, as documented in `docs/BENCHMARKING.md` |
| Detector vs RustFS container | Low | The provider container is outside the runner subtree; all three samples were `clear` with 0 competing processes |
| W06/W07 CSV semantics | Medium | CSV `hits` are batch response lengths (1 and 3). The auditor checks those values; the real oracle (4 × 5,000; S/F/S) runs inside the runner and is not re-derived by the auditor |
| Corpus digest prose mismatch | Medium | The workload doc describes eight hashed fields; the runner hashes five blobs. The emitted digest matches the fixed contract and all historical reports, so X12 did not fire. Prose correction needs separate approval |
| Historical raw CSV absent | Low | Historical `raw_csv` paths do not resolve; provenance only, not re-audited |
| `stat -f` type string | Low | `stat -f` prints `ext2/ext3` for ext4; `df -T` confirms ext4 |
| `unittest discover` | Low | Hyphenated `test-pr14f-audit.py` is not importable as a module; direct invocation runs 25 tests |
| Pre-existing `docs/TESTING.md` conflict markers | Low | Committed before PR 14F; not an executable input; untouched |
| Log-based `1 passed` check | Low | Convenience check; validator/auditor inspect the actual JSON/CSV |
| Three trials only | Low | Descriptive dispersion, not statistical significance |
| Post-measurement analysis tool | Low | The percentile helper was written after the source lock and is kept only in the untracked raw archive; it cannot affect measurements. The tracked measurement-input diff is empty |

## 3. Claims explicitly not made

- No independent agent-side remote re-download of the durable archive.
- No CI result for the current binding head, independent review or merge.
- No cross-engine (Tantivy/Lucene) comparison or superiority.
- No production p99/SLO/throughput/capacity claim.
- No claim that W08 was measured or passed.
- No pooling of cold/warm or local/remote lanes.
- No claim that the historical `ab9b2d7` trials describe the current tree.
- No claim that local tests or provider health substitute for the benchmark.

## 4. Reviewer attack surface

A reviewer should independently check:

1. Source lock `7df4920…` is an ancestor of the evidence head; the executable
   diff between them is empty; campaign 1’s t1 was not reused.
2. Historical report hashes match `baseline-inventory.md` §3.
3. The three tracked reports carry `sha=7df4920…`, `qualified=true`,
   `idle_confirmed=true`, `contention=clear`, `dirty=false`.
4. The three CSVs have 280 rows each, 14 pairs × 20 samples, and the hashes
   match the manifest/archive.
5. The three contention records are `clear` and hash-match.
6. The durable archive is operator-attested; verify the declared SHA-256 and
   independently re-download the Google Drive object when credentials allow.
7. W06/W07 values are interpreted as response lengths, not group counts.
8. No cold/warm or local/remote distributions were pooled.
9. The corrected campaign’s attestation timing is acceptable, or a fresh
   attestation is required before treating the result as release evidence.
10. CI references are tied to the exact head: `4c94ba8` and `bd1fed7` are
    green; the final binding head is pending. Independent review and merge
    authorization are genuinely independent.

## 5. Final archival audit (2026-10-26/27)

This is an **agent self-audit**. It does not constitute independent human
review and must not be reported as such.

| Audit area | Check | Result |
|---|---|---|
| Source-lock integrity | `git diff 7df4920..4c94ba8` contains only `docs/` and published reports; benchmark executable/workload diff empty | **PASS** |
| Production-code changes | No `crates/*/src` changes between source lock and evidence head | **PASS** |
| Trial independence | Three distinct trial ids, three distinct reports/CSVs, identical source SHA | **PASS** |
| Correctness before timing | Runner oracle executed before timed lanes in every trial; logs show completion | **PASS** |
| Per-trial contention | Three live records, all `state=clear`, competing 0 | **PASS** |
| Statistical provenance | `benchmark-report.md` tables derived from raw CSV with the recorded nearest-rank convention; no pooled lanes | **PASS** |
| Raw artifact integrity | 21-member package; `PACKAGE-SHA256SUMS` and `original-archive/SHA256SUMS` verify; deterministic rebuild byte-identical | **PASS** |
| Raw artifact durability | Google Drive copy with matching operator-declared SHA-256; agent re-download blocked by Google auth | **PASS (operator-attested)** |
| Validator strictness | `validate-pr14-p4.py` PASS with approved W08 exemption | **PASS** |
| Auditor strictness | `audit-pr14f-trials.py` PASS; 25 negative/positive tests | **PASS** |
| Historical-report preservation | `pr14-p4-t{1,2,3}.json` hashes unchanged | **PASS** |
| W08 status | `not_applicable`, `approved=true`, `measured=false` | **PASS** |
| CI identity | PR #67 `4c94ba8`, `bd1fed7` and `8887541`: `rust`, `msrv`, `rustfs` success; current binding head pending | **PASS on three heads / PENDING on current binding head** |
| Independent review | No human reviewer signature | **NOT DONE** |
| Merge / PR 14 acceptance / v0.1 release | No merge, no acceptance, no release authorization | **NOT DONE** |

Observed residual risks: the durable Google Drive copy is operator-attested but
could not be independently re-downloaded by the agent; current binding-head CI
pending; attestation timing disclosed; `QUERVANT_P4_IDLE_CONFIRMED` truthiness;
report-to-CSV hash binding is manifest-level rather than embedded in the report;
`/proc` contention detection cannot see the Windows host or other WSL guests;
three trials give descriptive dispersion only.

## 6. SR-14F-01 fixup audit — 2026-10-27

**Finding:** the previous campaign timed remote-cold W01 before running the full
remote oracle, violating correctness-before-timing.

**Fix audit:** source lock `8cfd2fce436ea99d57d2699471ab49d2cd1a3446` runs the
unchanged oracle on the committed remote index, drops the validation snapshot
and index handle, clears only the disposable workspace cache, prints
`PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS` before the first cold stopwatch, and
asserts the pass flag inside every cold iteration. The wrapper rejects logs
without the exact marker. A source-order regression anchors inside the remote
block and rejects the old order and local-W09 false positives.

**Residual gap:** `origin/main` advanced to `18c8fca8…` during this pass; no
PR-branch executable change or rebase was made. No new qualified campaign
exists. FX17–FX20, the new archive
and the new durable upload remain blocked on a new operator attestation. The
prior campaign, CI results and Google Drive archive are historical only. This
is agent self-review, not independent review.

## 7. SR-14F-01 attempt-1 failure audit — 2026-10-27

The first corrected source lock `8cfd2fc` failed its t1 pre-cold oracle with
W01 `0 != 10000`. Root cause: `RemoteIndex::snapshot()` returns the generation
observed at `create()` time, which is empty before the three writer commits. It
is not the committed generation.

Disposition: the attempt is unqualified and preserved
(`target/pr14-p4/attempts/8cfd2fce436e-t1-oracle-snapshot-failure/`); no CSV or
report was written and t2/t3 did not run. The approved AD02 fallback was applied
under source lock `d12a975`: a fresh `RemoteIndex::open_existing` reader feeds
the untimed oracle, and its handles are dropped before the workspace reset and
cold timing.

Residual gap: the new source lock has no qualified campaign and no new
attestation. FX17–FX20, the new archive and the new durable upload remain
blocked. This remains agent self-review, not independent review.
