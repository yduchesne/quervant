# PR 4 — Phase 0 preflight and STOP report

**Branch:** `dev/analyzer-contract`
**Base / working-tree SHA:** `040b6a945e9e02c26bbf13660744ddceed177797`
(`git status --short` = clean at preflight)
**Prepared:** 2026-10-12
**Plan:** `~/Downloads/TRAWLER_PR04_DETAILED_IMPLEMENTATION_PLAN.md`
**Disposition:** **BLOCKED / NOT VERIFIED — Phase 0 human decision gate unmet. No production
code written. No merge authorization.**

## 1. Executive summary

The PR 4 plan is *conditionally executable* and its Phase 0 requires a **human-approved
T01–T08 parameter addendum before any code**. That addendum does not exist:

- `docs/decisions/PR04_ANALYZER_PARAMETER_DECISIONS.md` was **absent** at preflight; only the
  direction-level record `docs/decisions/PR04_PR05_DESIGN_GATE_APPROVAL.md` exists, and it
  states it is *"not an approval of … coding-agent implementation authorization"* and lists
  T01–T08 concrete choices as **still open**.
- Therefore plan §3 ("Do not code, choose defaults, or freeze public contracts") and §12
  STOP condition 1 apply.

The predecessor prerequisite (PR 2 merge/CI) is **satisfied**: independently verified via
the GitHub API, not inferred from the ADR or code presence (see §3). The only blocking gate
is the unresolved parameter addendum plus the dependency/crate choices it requires
(notably the MSRV interaction with ICU).

A draft, explicitly-unapproved addendum has been prepared for the human owner at
`docs/decisions/PR04_ANALYZER_PARAMETER_DECISIONS.md`. **It is not approved and authorizes
no code.**

## 2. STOP gates triggered

| Gate | Plan reference | Status |
|---|---|---|
| Required coding-agent artifact directory | §3, §10 | Created (`docs/pr-artifacts/pr-4/`). |
| T01 term bytes | §3, §12 | **OPEN — no human approval.** |
| T02 multi-value gaps | §3, §12 | **OPEN — no human approval.** |
| T03a normalization/case fold | §3, §12 | **OPEN — no human approval.** |
| T03b stopwords/stemmer + versions | §3, §12 | **OPEN — no human approval.** |
| T04 offset-correction deferral | §3, §12 | **OPEN — no human approval.** |
| T05 analyzer fingerprint/reindex policy | §3, §12 | **OPEN — no human approval.** |
| T06 IDNA/PSL/UTS #39 data + policy | §3, §12 | **OPEN — no human approval.** |
| T07 concrete limits/cancellation/errors | §3, §12 | **OPEN — no human approval.** |
| T08 term/glob/regex grammar boundary | §3, §12 | **OPEN — no human approval.** |
| Dependency/MSRV/license gate | §3 additional gate | **OPEN — this report records verified candidate data; selection needs approval.** |
| PR 2 merge/CI prerequisite | §2, §12 | **SATISFIED** (see §3). |

**Violated invariant / risk if coding proceeded:** the plan forbids the agent from choosing
analyzer parameters on the user's behalf; implementing without approval would freeze an
unapproved term/offset/normalization/dataset contract into PR 5's on-disk terms and would
violate `AGENTS.md` "no segment format freeze before approval" / "do not imply a planned
capability is implemented".

## 3. Preflight facts and independent verification

### 3.1 Repository state

- Workspace: `crates/trawler-core`, `crates/trawler-objectstore`, `crates/trawler-distributed`;
  edition 2024, MSRV `1.85`; `#![forbid(unsafe_code)]`.
- `crates/trawler-core/src/lib.rs` exports `contract` and `storage` only. **No `analysis`
  module, tokenizer, term-query preparation, segment codec, writer, reader or query executor
  exists.** PR 4 = **NOT STARTED** on this base.
- PR 3 storage is present (Directory/cache/etc.) as described on `main`.

### 3.2 Predecessor PRs (GitHub API, not inferred)

| PR | Title | State | Merged at | Merge commit | CI check |
|---|---|---|---|---|---|
| #6 | Dev/query contracts (PR 2) | closed/**merged** | 2026-10-12T03:02:13Z | `c54cbf3e673d0ceaba44472a8ea9ab60c781910d` | `rust` -> **completed/success** on head `65dcfb3a…` and on merge commit |
| #13 | Dev/storage abstraction (PR 3) | closed/**merged** | 2026-10-12T15:17:06Z | `cdbab01acc709353ea61ff0df3447921a801510e` | `rust` -> **completed/success** |
| #15 | PR 4/5 design gate approval | closed/**merged** | 2026-10-12T15:38:25Z | `040b6a945e9e02c26bbf13660744ddceed177797` | `rust` -> **completed/success** |

Evidence commands:

```bash
git merge-base --is-ancestor dev/query-contracts main && echo MERGED   # -> MERGED
curl -s https://api.github.com/repos/yduchesne/trawler/pulls/6   # state=closed, merged=true
curl -s -H 'Accept: application/vnd.github+json' \
  https://api.github.com/repos/yduchesne/trawler/commits/<sha>/check-runs  # rust: success
```

**Tracker reconciliation:** `docs/ROADMAP_V01.md` still listed PR 2 as `IN PROGRESS` and
PR 3 as `PLANNED` despite both being merged with green CI. This is a stale documentation
tracker, not a code blocker. Reconciled in this task with the evidence above (PR 2 and PR 3
rows updated to DONE with PR/merge references). **PR 4 status deliberately left `PLANNED`;
it must not be marked DONE by this STOP task.**

### 3.3 Environment

```text
rustc 1.99.0 (b940084d7 2026-09-28)
cargo 1.99.0 (5f94df478 2026-08-27)
cargo-llvm-cov 0.9.1
```

Repository CI (`.github/workflows/ci.yml`, single `rust` job) authoritative commands:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo llvm-cov --workspace --all-targets --fail-under-lines 85
cargo doc --workspace --no-deps
```

## 4. Baseline verification (no code changed)

Run from the workspace root at SHA `040b6a945e…`:

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | **PASS** (exit 0) |
| `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** (exit 0, `Finished`) |
| `cargo test --workspace --all-targets` | **PASS — 263 passed; 0 failed; 1 ignored** |
| `cargo doc --workspace --no-deps` | **PASS** (exit 0) |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | **NOT RUN** — not required for a zero-code Phase 0 STOP; no production change to cover. Gate remains open for the eventual PR 4 implementation. |

These results establish a green pre-existing baseline; any future PR 4 failure can be
classified against it (introduced regression vs pre-existing).

## 5. Dependency gate — verified data recorded

Candidate crates were checked against the crates.io API (see the addendum's dependency
table). Key finding that needs a human decision:

- `icu_casemap` **2.3.0 requires Rust 1.88**, which **exceeds the workspace MSRV 1.85**.
  `icu_casemap` **2.0.1 requires Rust 1.82** and is MSRV-compatible (license Unicode-3.0).
- `unicode-segmentation` 1.13.3 declares MSRV exactly **1.85.0**.
- `publicsuffix` 2.3.0 does **not** download the PSL; the caller commits a pinned list
  (fits "no runtime fetch + pinned dataset"). `psl` 2.1.241 embeds the list.
- No hand-written Unicode/IDNA/PSL/UTS #39 algorithm will be permitted (`AGENTS.md`).

## 6. Smallest human decision needed

Approve (or amend) the T01–T08 rows and the dependency/MSRV choices in
`docs/decisions/PR04_ANALYZER_PARAMETER_DECISIONS.md`, and complete its **Approval block**.
Specifically the minimum unblockers are:

1. T01 term representation; T02 gap/offset model; T03a/T03b normalization/stemming datasets;
   T04 deferral vs implementation; T05 fingerprint policy; T06 IDNA/PSL/UTS #39 sources and
   policy; T07 concrete limits and API shape; T08 grammar boundary.
2. D-GATE-1 (`icu_casemap` 2.0.1 vs defer case folding vs MSRV bump) and D-GATE-2/3/4
   (PSL source, pinned data versions, license confirmation).

## 7. Safe next steps

1. Human owner reviews the draft addendum and records explicit approvals.
2. On approval, execute plan Phases 1–6 with the **approved** values only, starting with
   contract-first work (`Token`/error/limits/registry + A4-01/02/07/08/10/18/19).
3. Run the full quality/coverage gate and record transcripts under `docs/pr-artifacts/pr-4/`.
4. Do not merge without explicit authorization.

## 8. Artifacts produced by this task

- `docs/decisions/PR04_ANALYZER_PARAMETER_DECISIONS.md` — draft (NOT APPROVED) addendum.
- `docs/pr-artifacts/pr-4/stop-report.md` — this report.
- `docs/ROADMAP_V01.md` — evidence-backed status reconciliation for PR 2 / PR 3 only.

**No production code, public API, default value or format was frozen.**
