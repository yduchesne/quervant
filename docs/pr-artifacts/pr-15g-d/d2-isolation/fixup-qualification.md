# D2 isolation harness fixup — qualification

**Status:** `D2_ONLY_PERFORMANCE_REJECTED_SAFE_ROLLBACK_REVIEW_PENDING`
**Harness commit:** `74f495cc580a746ada6facda7c44363499273481`
**Source rollback:** `f51b772b653205ddf1c767850961e88a13193096`
**Campaign:** opaque `d2-only-fixup-new-campaign-01`

| Gate | Status | Evidence |
|---|---|---|
| HX-A00 identity/fresh main | PASS | preflight |
| HX-A01 tracked source proof | PASS | exact edits 15/0 + 43/1; real local X |
| HX-A02 frozen summary validation | PASS | six-field nearest-rank tests |
| HX-A03 manifest/slot validation | PASS | 16-slot identity tests |
| HX-A04 v2 sealing | PASS | exactly 18 files |
| HX-A05 blocked verification | PASS for synthetic fixture; prior v1 remains legacy | seal tests |
| HX-A06 qualified verification | PASS | campaign `--verify-only` |
| HX-A07 full HX-T matrix | **PARTIAL** | 22 isolated-D2 tests; documented residual rows |
| HX-A08 real-file integration | PASS | sealed blocked/qualified temporary campaigns |
| HX-A09 frozen/original evidence | PASS | untouched |
| HX-A10 16-slot acquisition | PASS | 144 records, 2,880 samples |
| HX-A11 drift qualification | PASS | both arms, all lanes within caps |
| HX-A12 performance verdict | **REJECTED** | DX-P01 and DX-P02 failed |
| HX-A13 disposition | PASS | exact A source restored |
| HX-A14 local Rust QA | PASS | stable/MSRV fmt, Clippy, tests; coverage 92.72% |
| HX-A15 real RustFS | PASS | pinned RustFS via podman; S3, proxy, A/B/C/D, k0, 10×k05 |
| HX-A16 exact-final-HEAD CI | PENDING | to be observed after docs commit |
| HX-A17 documentation/audit | PASS | historical files untouched |
| HX-A18 independent review | PENDING | no self-approval |

## QA commands and results

- Python: 48 passed.
- Stable and Rust 1.85 `fmt`, Clippy (default/all features), and all-feature tests: PASS.
- `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`: PASS — **92.72%**.
- `cargo doc --workspace --all-features --no-deps`: PASS.
- `cargo bench --workspace --no-run`: PASS.
- `bash benchmarks/scripts/test-scripts.sh`: PASS.
- `git diff --check`: PASS.

## Real RustFS topology

Pinned image `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
on `127.0.0.1:9000` with CI credentials. All selected suites passed:

- objectstore S3: 8
- objectstore proxy: 5
- core PR15G-A/B/C/D RustFS: 1 each
- `pr13_remote_proxy`: 7
- `pr13_crash_rustfs k0`: 5
- `pr13_crash_rustfs k05`: 10/10 runs passed

## Residual issues

- HX-T01–HX-T47 are not all individually asserted; see `fixup-test-matrix.md`.
- Exact-final-HEAD CI is not yet claimed.
- Independent review remains mandatory.
