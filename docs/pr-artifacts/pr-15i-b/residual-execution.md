# PR 15I-B residual — execution

**Final disposition: `15IB_RESIDUAL_LOCAL_QUALIFIED_REVIEW_READY` (LZ4).**

| Field | Value |
|---|---|
| branch | `dev/pr15i-b-stored-blocks` |
| branch HEAD | `9da20614f58313259fcceb5ff8fa997e6afc7d7c` |
| P0_SHA | `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb` |
| archived direct LZ4 / Zstd | `67d75b58…` / `71d92f90…` |
| RESIDUAL_COMMON_LZ4 / R1–R3 | `5703a3dfd62b67bf0413b8542c420dbd5c986fe9` |
| B_LZ4_RESIDUAL_SHA | `5703a3dfd62b67bf0413b8542c420dbd5c986fe9` |
| B_ZSTD_RESIDUAL_SHA | `6bbdd73d080ce801c9bf9f7bad54012d8cff8d7f` |
| selected codec | **LZ4** |
| final code SHA | `9da20614f58313259fcceb5ff8fa997e6afc7d7c` |
| frozen protocol SHA-256 | `3a63d5b8f208ed15921c3200aaa00e940e7aa30697b1805cd7ce2fa0d86d523a` |
| corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| LZ4 seal | `b5cf7fd4c057d6880036c4d490226570c57a24398bc8909609eba825be5bf740` |
| Zstd seal | `2a589854b810379ae04e3951f8d54afe3727782fdad75fc05c9c4ae5a39b4c61` |
| campaign counts | 26 raw files, 12 rebuilds, 8 binaries, 16 slots, 144 lanes, 720 warmups, 2880 samples per campaign |

## Changes vs measured source

`git diff 5703a3d..9da2061` contains only the v2 RustFS test helper fix and the
single approved `pr15i_b_rustfs` CI invocation; core/Cargo bytes are identical.

## Remaining work / risks

- Micro-profile and 8-block same-codec diagnostic were not executed; the
  structural counters and authoritative campaigns are the evidence.
- Hosted CI and independent review remain external; no push/merge performed.
- v2 remains an experimental compressed STORED format; no distributed/vector
  capability is implied.
