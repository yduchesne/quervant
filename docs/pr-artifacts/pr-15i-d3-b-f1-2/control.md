# PR 15I-D3-B-F1.2 — official A/A control `d3bf12-base-aa-01`

**Result: `CONTROL_QUALIFIED`, independently verified and archived.**

| Item | Value |
|---|---|
| Campaign | `d3bf12-base-aa-01` (fresh; the F1.1 control was not reused) |
| Kind | same-source A/A, both arms BASE `39dbd9f5…` |
| T3 tooling | `c86c3b1554cadbc11deaedf4de4f4d7247e1467c` |
| Protocol / manifest | `3946c1ca…` / `35f79751…` |
| Arm A / B binary | `e6363c866b2f70e22e391cd276a499de57d609b17fca63c8e71d0a82b36166b7`, 4,479,112 bytes (both) |
| Build provenance | `467c264ab97d9b4c…` |
| Host attestation | `49f224e91d27ad89…` |
| Readiness | `READY`, adapter median 19‰, controller 0‰; SHA-256 `b65f68d4…` |
| Builds / slots / records | 2 real builds, 16 slots, 144 lane records |
| Samples / warmups / probes | 2,880 / 720 / 32 all clear |
| Drift | `PASS`, zero violations |
| Independent verifier | exit 0, `verification=PASS`, `campaign_status=CONTROL_QUALIFIED`, `summary_match=true`, `a_a_passes=true`, `live_binary_rehash=PASS`, all structural statuses PASS, 60 sealed members |
| Archive | `d3bf12-base-aa-01.tar.gz`, SHA-256 `935a4d8769fa9cae85574fd1d1aae7bf03297fbcbc7ef046697374795d046253`, 62 members, exclusive sidecar, extraction/rehash PASS |

## A/A lower-median B/A ratios (all lanes inside `[0.85,1.15]`, no soft exception)

| Lane | Median B/A |
|---|---:|
| 10K absent | 1.022104 |
| 10K rare | 0.945577 |
| 10K medium | 0.998101 |
| 10K common | 0.993023 |
| 100K absent | 0.961592 |
| 100K rare | 0.997015 |
| 100K medium | 0.998331 |
| 100K common/K100 | 1.000863 |
| 100K common/K10 | 0.990059 |

Both 100K indexes are byte-identical (15,747,551 committed / 1,661,455 STORED,
digest `5734ae60591f7563…`). The verifier regenerated the frozen PR15D corpus
and confirmed every lane's exact hit count and document IDs.
