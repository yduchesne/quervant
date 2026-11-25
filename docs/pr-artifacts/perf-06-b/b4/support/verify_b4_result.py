#!/usr/bin/env python3
import json
import math
import sys
from collections import Counter
from pathlib import Path

CONFIG, RESULT, ANALYSIS = (Path(s) for s in sys.argv[1:4])
c = json.loads(CONFIG.read_text(encoding="utf-8"))
r = json.loads(RESULT.read_text(encoding="utf-8"))
a = json.loads(ANALYSIS.read_text(encoding="utf-8"))
assert a == r["analysis"], "native read-only reanalysis disagrees"
assert r["schema"] == "benchmark-result-v1"
assert r["family"] == c["family"] == "perf-06"
assert c["name"] == "quervant-perf06b4-paired-warm"
assert c["policy"]["readiness"]["mode"] == "advisory"
assert c["policy"]["readiness"]["max_busy_percent"] == 25
assert c["policy"]["readiness"]["max_steal_percent"] == 2
assert c["policy"]["blocks"] == 12 and c["policy"]["slots_per_arm"] == 2
assert c["policy"]["warmups"] == 5 and c["policy"]["samples"] == 20
assert c["policy"]["exclude_blocks"] == {}
assert r["configuration_id"] == c["configuration_id"]
assert r["configuration"] == c
assert r["context"]["host_readiness_mode"] == "advisory"
assert r["context"]["build"]["arm_source_revisions"] == {
    k: c["arms"][k]["revision"] for k in ("A", "B")}
assert r["configuration_file"] == CONFIG.name
classes = ("absent", "rare", "medium", "common")
lanes = {f"{n}/{cls}/k{k}/warm" for n in (10000, 100000)
         for cls in classes for k in (10, 100)}
assert {x["id"] for x in r["lanes"]} == lanes
assert set(r["analysis"]["lanes"]) == lanes
assert set(r["controls"]["analysis"]["lanes"]) == lanes
assert r["status"] == "COMPLETE", f"incomplete result: {r['status']}"

def check_records(rows, arms):
    assert len(rows) == 768, f"expected 768 raw records, got {len(rows)}"
    counts = Counter()
    for x in rows:
        key = (x["lane_id"], x["arm_id"], x["block"])
        assert x["lane_id"] in lanes and x["arm_id"] in arms
        assert type(x["block"]) is int and 1 <= x["block"] <= 12
        assert type(x["position"]) is int
        assert x["oracle_ok"] is True and x["warmups"] == 5
        assert len(x["samples_ns"]) == 20
        assert all(type(t) is int and t > 0 for t in x["samples_ns"])
        counts[key] += 1
    for lane in lanes:
        for arm in arms:
            for block in range(1, 13):
                assert counts[(lane, arm, block)] == 2, (lane, arm, block)

check_records(r["raw_samples"], {"A", "B"})
check_records(r["controls"]["raw_samples"], {"AA", "AA2"})
for lane in lanes:
    aa = r["controls"]["analysis"]["lanes"][lane]["comparisons"]["AA2"]
    assert aa["status"] == "PASS", (lane, aa)
for arm in ("A", "B"):
    for n in (10000, 100000):
        m = r["index_metrics"][arm][str(n)]
        assert all(type(m[key]) is int and m[key] > 0
                   for key in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"))
        assert type(m["segment_count"]) is int and m["segment_count"] > 0
primaries = {f"100000/{cls}/k{k}/warm"
             for cls in ("common", "medium") for k in (10, 100)}
out = {"result_status": r["status"], "host_readiness_mode": "advisory",
       "primary": {}, "guard": {}, "all_targets_met": True}
for lane in sorted(lanes):
    t = r["analysis"]["lanes"][lane]["comparisons"]["B"]
    assert t["status"] in ("IMPROVED", "REGRESSED", "INCONCLUSIVE")
    point = t["gain_percent"]
    ci = t["gain_ci_95_percent"]
    assert isinstance(point, (int, float)) and math.isfinite(point)
    assert len(ci) == 2 and all(isinstance(z, (int, float)) and math.isfinite(z) for z in ci)
    assert ci[0] <= ci[1]
    passed = (t["status"] == "IMPROVED" and point >= 5 and ci[0] > 0
              if lane in primaries else point >= -10 and ci[0] >= -10)
    dest = out["primary"] if lane in primaries else out["guard"]
    dest[lane] = {"passed": passed, "native_status": t["status"],
                  "gain_percent": point, "gain_ci_95_percent": ci}
    if not passed:
        out["all_targets_met"] = False
assert len(out["primary"]) == 4 and len(out["guard"]) == 12
print(json.dumps(out, indent=2, sort_keys=True, allow_nan=False))
