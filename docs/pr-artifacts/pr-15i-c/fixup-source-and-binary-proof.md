# PR 15I-C fixup — source, binary and format proof

Only the artefacts that were actually produced are listed. F1/F2 (operator
restoration) never happened, so no operator source proof exists.

## 1. Commit identities (actual local Git objects)

| Role | SHA |
|---|---|
| `MERGED_15IB_A_SHA` (baseline) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| `PREV_C_EXPERIMENT_SHA` | `395e05c629c5929f0164764c51c5a1b60b8acd1c` |
| `PREV_REJECTION_HEAD` | `a3a502cd3aeea3e2d6d1b2d95eb0baf8d19b79ed` |
| `G_CONTROL_SHA` (production change + diagnostic harness + control doc) | `50b56e9fe7b22bb266ca7b0d9e209500dfc785ff` |
| Diagnostic tooling SHA (harness defect fixes) | `7fbea7f4a43cd105fdb6939b84e6f5d02f59a863` |
| `FIXUP_IMPLEMENTATION_SHA` | **not created** — F0 precondition failed |
| `FIXUP_MEASURED_SHA` | **not created** — no candidate campaign |

Ancestry: `6f6463cb…` and `395e05c…` are both ancestors of the starting HEAD
(verified with `git merge-base --is-ancestor`).

## 2. Control diff proof

`git diff 6f6463cb… 50b56e9… -- 'crates/**'` contains exactly one production file,
`crates/quervant-core/src/search/unified.rs`, and inside it exactly one added
attribute before `fn collect_mixed`:

```
+    #[inline(never)]
```

plus three explanatory comment lines. Extracted body hashes (attributes excluded,
brace-aware extraction in `benchmarks/pr15i_c/source_proof.py`):

| Source | `collect_mixed` body SHA-256 |
|---|---|
| `6f6463cb…` | `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` |
| `50b56e9…` | `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` |

The verifier recomputes both hashes from the Git objects at verification time and
rejects any difference (`LV_BODY`), any missing/multiple inline attribute
(`LV_BOUNDARY`) and any production path outside `search/unified.rs` (`LV_SCOPE`).

## 3. Binary proof (diagnostic arms A and G)

| Item | Arm A | Arm G |
|---|---|---|
| Adapter binary SHA-256 | `805fe4e4c849529b…` (full value in the sealed manifest) | `d89a8745193c4d5e…` |
| Adapter bytes | 4,478,840 | 4,476,072 |
| Build command | `cargo build --release --offline` (frozen PR15D adapter; `--locked` cannot be used because its lockfile predates the current core dependency graph — same behaviour as the accepted PR15I-C controller) | identical |
| Toolchain | rustc/cargo `1.98.1`, workspace release profile | identical |

The verifier re-hashes the executable files and compares them to both
`raw/manifest.json` and `raw/toolchain.json`; a digest string without a file is
rejected (`LV_BINARY`).

## 4. Same-format proof

Twelve fresh builds (2 arms × {10K, 100K} × 3 attempts) were remeasured from disk
by the verifier:

* `stored_payload_version = 2`, `codec_id = 1` (LZ4) on both arms;
* required feature list contains `[13, 1]` (`0x000D` v1) on both arms;
* identical committed bytes, sidecar bytes, STORED bytes and segment SHA-256
  digest per N across arms;
* A 100K committed bytes `15,747,551` and STORED bytes `1,661,455` — the accepted
  PR15I-B sentinel reproduced exactly (`LV_SENTINEL` enforced).

## 5. Corpus proof

Frozen PR15D corpus generated once through the frozen generator; manifest
SHA-256 `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`
matches both the recorded value and the frozen constant in the verifier. Every
slot response is re-checked against the frozen oracle's `total_hits` and ordered
`doc_ids` — a stale or forged `oracle_ok` flag cannot pass.
