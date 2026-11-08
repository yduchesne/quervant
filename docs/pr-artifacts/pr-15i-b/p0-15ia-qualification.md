# PR 15I-B P0 — PR 15I-A verifier requalification

**Status:** `P0_PASSED` — all twelve original size-rebuild directories are now
mandatory, raw directory inventory is symlink-safe, and the original sealed
campaign requalifies read-only with an exclusive receipt.

## Defects closed

| ID | Pre-fix behavior | Fix |
|---|---|---|
| RF-A03 / P0.2 | `_real_size_artifacts` accepted a subset of `run{1,2,3}` and returned `HISTORICALLY_ATTESTED` | All 12 directories are located through `os.lstat` component checks; all three must exist, be real directories, and all three full measurements must equal one another and the sealed manifest |
| RF-A04 / P0.3 | `_inventory_and_rehash` inspected only files under `os.walk`, so an unexpected or symlinked directory under `raw/` was invisible | Every `dirs` entry is lstat-checked (no symlinks, must be a directory) and the exact directory set is enforced: `slots`, `slots/slot-01..16`, `slots/slot-NN/contention` |
| Defense in depth | An injected `size_artifacts` seam could return a partial mapping | `verify_campaign` requires the returned mapping to equal exactly the four `INDEPENDENTLY_RE_VERIFIED` groups |
| FT-A57 | — | Partial injected mapping is rejected with `A_PROVENANCE` |

## Pre-fix reproduction (old verifier from `691b699`)

Recorded in `target/pr15i-b/p0/pre-fix-repro.json` (ignored):

```json
{
  "missing_rebuild_run2": {
    "old_verifier_qualified": true,
    "old_three_build": {
      "A/10000": "INDEPENDENTLY_RE_VERIFIED",
      "A/100000": "HISTORICALLY_ATTESTED",
      "B/10000": "INDEPENDENTLY_RE_VERIFIED",
      "B/100000": "INDEPENDENTLY_RE_VERIFIED"
    }
  },
  "symlinked_raw_directory": {"old_verifier_qualified": true}
}
```

The old code wrongly qualified a campaign missing `A/100000-run2` and a
campaign containing `raw/unexpected -> <outside directory>`.

## Post-fix acceptance

Command: `python3 benchmarks/pr15i_a/verify.py --checkout-root "$ROOT"
--campaign "$ROOT/target/pr15i-a/campaigns/paired-04" --verify-only
--receipt-out "$ROOT/target/pr15i-a/reviews/verification-15ib-p0-01.json"`

- Result: `decision=A_CANDIDATE_ACCEPTED_PENDING_QA qualified=True raw=20 aux=32 lanes=144 samples=2880`
- All four arm/size groups: `INDEPENDENTLY_RE_VERIFIED`
- Original seal SHA-256 before == after == `af7f6c1a85515dbc58c8c31a3b1b7f68dd6a9246d33747a529952b941b852b2f`
- Receipt: `target/pr15i-a/reviews/verification-15ib-p0-01.json` (exclusive create)
- Original `paired-04` was not modified or regenerated.

## Tests added (appended to the FT-A sequence)

| ID | Case | Result |
|---|---|---|
| FT-A55 | Missing `run1`, `run2`, or `run3` for A/B × 10K/100K (one and two missing) | reject `A_PROVENANCE_BLOCKED_SIZE_ARTIFACTS` |
| FT-A56 | Unexpected directory, symlink-to-outside, symlink-to-inside, dangling symlink under `raw/` | reject `A_SEAL` |
| FT-A57 | Injected partial `size_artifacts` mapping | reject `A_PROVENANCE` |
| FT-A58 | Symlinked rebuild run directory | reject `A_FORMAT` |
| FT-A59 | One rebuilt file modified after seal | reject `A_FORMAT` |
| FT-A60 | Source untouched; two verifications return identical receipts and seal | pass |

Targeted QA at the P0 commit:

- `python3 -m unittest discover -s benchmarks/pr15i_a -p 'test_*.py'` → **87 passed**
- `python3 -m py_compile benchmarks/pr15i_a/verify.py benchmarks/pr15i_a/test_verify.py` → pass
- `bash benchmarks/scripts/test-scripts.sh` → **108 passed**
- `git diff --check` → pass
- Production diff `db9007f..HEAD` for core/Cargo/CI → empty

**P0 terminal status:** `P0_PASSED`; STORED production work may proceed.
