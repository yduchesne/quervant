# PR 14F — baseline inventory and evidence lock

**Status:** Stage A preflight completed. Benchmark qualification: **NOT RUN**
(operator idle attestation outstanding and provider prequalification pending).
PR 14 overall remains **IN PROGRESS / NOT ACCEPTED**; v0.1 is **NOT RELEASED**.

## 1. Source identity and ancestry

| Item | Value |
|---|---|
| Execution date (UTC) | 2026-10-26 |
| Baseline fetched | `git fetch origin main --prune` |
| `origin/main` at preflight | `7b1b84be381dfa1abf57210f013349ede45c5c26` |
| `origin/main` subject | `Merge pull request #66 from yduchesne/docs/pr14e-acceptance-reconciliation` |
| Local tree at preflight | clean (`git status --short` empty) |
| Working branch | `bench/pr14f-p4-qualification`, created from `origin/main` |
| Pre-existing branch observed | `dev/pr14f-final-testing` (same commit as `origin/main`, no unique commits) |
| PR 14E merge ancestry | `git merge-base --is-ancestor 7b1b84be… origin/main` → **YES** |
| Original harness source lock | `162cbfea509d5f03df4bedb89a09d9be4cafb75e` (Stage A/B commit) |
| Final measurement source lock | `7df492023397a512e400b03865a989020eff1430` (approved absolute-report-path fix) |
| PR #67 | `https://github.com/yduchesne/quervant/pull/67` (open) |
| Baseline evidence head | `4c94ba8823dac62d6397e65239db1094ce6dbfe1` (CI-verified) |
| Baseline-head CI | `rust`, `msrv`, `rustfs` success; Rust CI run 40424504536 |
| Archival evidence head | `bd1fed714c21adc5d2aeb3936db1e0b49aea3eac`; CI run 40441448948 success |
| Final binding head | advanced by this evidence commit; CI pending |

The PR 14E merge commit is the current `origin/main` tip. No `main` drift was
observed between fetch and branch creation, so X02 was not triggered.

## 2. Authoritative source inventory (before Stage B)

SHA-256 captured with `sha256sum`; line counts with `wc -l`.

| File | SHA-256 (before) | Lines |
|---|---|---|
| `benchmarks/scripts/run-pr14-p4.sh` | `bbfb8a3547cabeb129946ab05bbda21e8e767c2775fa741f09990f210ffec322` | 61 |
| `benchmarks/scripts/validate-pr14-p4.py` | `22b5bbe6ce97615e6461cd5d9e66e0f8acf5d996055bfcfeee68e7a0ba1f805c` | 229 |
| `benchmarks/scripts/check-pr07-contention.py` | `c730e72565ebccd8382b777cfc2bed9282606262133cefbfae107c67b26e4396` | 265 |
| `benchmarks/scripts/test-scripts.sh` | `2e10dcdf3c301b630584a7d7375c439076587f7d990f6c96f93877ab3f1e9c9f` | 229 |
| `crates/quervant-core/tests/pr14_bench_remote.rs` | `c6353ec036c6cd6a8d2ab6703648cfe3d8135a339e02fbcd6bc4c51b210cadec` | 684 |
| `benchmarks/workloads/pr14_p4_v1.md` | `b480666705d529c0cae1b4bb105f6357a6232de3ba51055c00f123c4e69e2360` | 46 |
| `benchmarks/reports/pr14-p4-w08-exemption.json` | `7cf7593aa74bc2062b75bcd72e0551c07af8c691f69b45c22d1ddedfced63d24` | 10 |
| `docs/pr-artifacts/pr-14/p4-w08-stop.md` | `5e140b8188bed1e4c13173b35eef72aa60b5e9466590a8730209231a85701ccb` | 81 |

`benchmarks/scripts/validate-pr14-p4.py`, `check-pr07-contention.py`, the
workload document and the W08 waiver were **not modified** by PR 14F.

## 3. Historical trial reports (read-only provenance)

`benchmarks/reports/pr14-p4-t{1,2,3}.json` are tracked. Their bytes were hashed
before any edit and are preserved unchanged:

| Report | SHA-256 | Historical source SHA |
|---|---|---|
| `pr14-p4-t1.json` | `94b89d39ff22d9cb2856a2c8c8873b9715c07bd224143ebf5e3bb26b2ca1ac20` | `ab9b2d7da066ec80190dcee70a8cebfd81481b80` |
| `pr14-p4-t2.json` | `d313e16ee4fab78e0b27909eb477a176828928080fe748ef58bb315835192864` | `ab9b2d7da066ec80190dcee70a8cebfd81481b80` |
| `pr14-p4-t3.json` | `ffac9c040841c4cc4a60cdf6daac8219edad51abcb885d0f94ac31e6b3cb9448` | `ab9b2d7da066ec80190dcee70a8cebfd81481b80` |

These records are **historical provenance only**. Their `raw_csv` values are
absolute paths from the historical maintainer host
(`…/crates/quervant-core/../../target/pr14-p4/pr14-p4-tN.csv`) and need not
exist here. Per X20 they are not edited to fake availability, and per AD-F03
they are never overwritten by fresh trials.

`target/pr14-p4/` is ignored by `.gitignore:7` (`target`), so fresh raw CSV and
redirected reports do not dirty the tracked tree (X07).

## 4. Frozen workload facts

- Workload id `pr14_p4_v1`; 20,000 deterministic documents; three immutable
  segments (`0..7000`, `7000..14000`, `14000..20000`); seed `0x14F4_2026`.
- `WARMUPS = 3`, `SAMPLES = 20` in `pr14_bench_remote.rs`.
- 14 required `(lane, workload)` pairs: `local-cold/W09`, `local-warm/W02..W07`,
  `remote-cold/W01`, `remote-warm/W02..W07`.
- W08 is **NOT APPLICABLE (APPROVED)** under the unchanged Option 2 waiver.
- Runner-recorded `hits`: W01/W02/W09 = 10000, W03 = 2000, W04 = 6000,
  W05 = 2500, W06 = 1 (batch response length), W07 = 3 (batch response length).
  The independent oracle separately asserts W06 `4 groups × 5000 = 20000` and
  W07 `S/F/S` before timing.

### Corpus digest reconciliation

The workload prose describes the digest input as
`key\0title\0host\0n\0ts\0body\0loc\0ip`. The implemented hasher in
`pr14_bench_remote.rs` updates `key`, `title`, `host`, `n` bytes and `ts` bytes
(where the `i64` `ts` value equals the `i64` `n` value) and does **not** include
`body`, `loc` or `ip`. Replicating the implementation independently yields:

```text
runner-replicated: 80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768
fixed/historical  : 80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768
```

The **emitted digest matches the fixed contract and the historical reports**, so
the Stage D digest gate (X12) is satisfied. The prose/implementation wording
mismatch is a documentation discrepancy only; PR 14F does not change the hasher
or the expected digest (AD-F02). A prose correction requires separate human
approval and is recorded in `harness-corrections.md` §5.

## 5. Detected source-visible hazards

| Hazard | Location | Disposition |
|---|---|---|
| `${diagnostic:+QUERVANT_P4_DIAGNOSTIC=1}` expands for the nonempty string `0` | old wrapper | Fixed by AD-F06 array + `env -u` (X05) |
| `for arg in "$@"` with `shift` does not consume `$1` deterministically | old wrapper | Replaced with `while (( $# > 0 )); do case "$1"` (AD-F07) |
| Fresh reports written to tracked `benchmarks/reports/` | runner | Redirected by `QUERVANT_P4_REPORT_DIR` under ignored `target/` (AD-F05/X07) |
| Wrapper does not pass `--w08-exemption` to the validator | old wrapper | Added unchanged approved manifest (AD-F12/X21) |
| Historical `raw_csv` absolute paths do not resolve here | historical JSON | Provenance only; never edited (X20) |
| `QUERVANT_P4_IDLE_CONFIRMED` is tested with `var(...).is_ok()` | runner | Pre-existing; diagnostic runs still cannot qualify. Recorded, not changed (AD-F05 forbids measurement changes) |
| `docs/TESTING.md` contains committed conflict markers (`<<<<<<< HEAD` at lines 56–59) | pre-existing on `origin/main` since "PR 7 Phase 0" | Unrelated to benchmark executables; not modified in PR 14F. Recorded for human follow-up |
| Corpus digest prose vs hasher | workload doc / runner | Resolved as above: emitted digest matches contract; prose correction deferred |
| Relative `QUERVANT_P4_REPORT_DIR` resolves under the cargo package cwd | wrapper/runner | **Discovered by t1**: report landed in `crates/quervant-core/target/…`, wrapper aborted. **Fixed** at `7df4920…` with absolute `$ROOT/target/...` paths; see `harness-corrections.md` §7 |

## 6. Provider and operator gates

- Pinned provider reference from PR 13/14B/14D evidence:
  `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
  (`rustfs/rustfs:1.0.1`). The full digest is copied from committed evidence,
  not reconstructed.
- Operator idle attestation: **NOT SUPPLIED**. A successful contention check is
  not an attestation (AD-F10). Qualified measurement remains gated (X15).
- Provider env presence and health are checked in Stage C; values and
  credentials are never printed.

## 7. Branch/commit policy

All executable harness changes and these evidence documents are committed
**before** any qualified trial. The commits after source lock may only add or
edit documentation/report files; the executable diff between the source-lock
SHA and the final evidence head must be empty (AD-F04/X18).
