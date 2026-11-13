#!/usr/bin/env python3
"""Read-only arithmetic replay of a preserved A/A control (no measurement)."""
from __future__ import annotations
import argparse, json, math, os, sys

def slot_median(slot, lane_id):
    samples = slot["lanes_by_id"][lane_id]
    return sorted(samples)[9]

def block_arm_values(slots, lane_id):
    by = {}
    for s in slots:
        lane = next(l for l in s["lanes"] if l["id"] == lane_id)
        by.setdefault((s["arm"], s["block"]), []).append(lane["summary_ns"]["median"])
    return {key: sum(sorted(v)[:2]) // 2 if len(v) >= 2 else v[0] for key, v in by.items()}

def median4(values):
    return sorted(values)[1]

def gate_ratio(block_ratios):
    return median4(block_ratios)

def arm_aggregate_ratio(a_blocks, b_blocks):
    return median4(b_blocks) / median4(a_blocks)

def nearest_rank(values, q):
    v = sorted(values)
    return v[max(1, math.ceil(q / 100.0 * len(v))) - 1]

def deviation_stats(values):
    v = sorted(values)
    return {
        "n": len(v), "min": v[0], "median": v[len(v) // 2],
        "mean": sum(v) / len(v), "p90": nearest_rank(v, 90),
        "p95": nearest_rank(v, 95), "p99": nearest_rank(v, 99), "max": v[-1],
    }

def within_counts(deviations, limits=(5, 10, 15, 25)):
    return {str(t): sum(1 for d in deviations if d <= t / 100.0) for t in limits}

def is_exempt(n, cls):
    return n == 10000 and cls in ("absent", "rare")

def load_campaign(path):
    slots = [json.load(open(os.path.join(path, "raw", "slots", f"slot-{i:02d}.json"))) for i in range(1, 17)]
    return slots

def analyze(path):
    slots = load_campaign(path)
    lanes = slots[0]["lanes"]
    ids = [l["id"] for l in lanes]
    meta = {l["id"]: (l["n"], l["class"], l["k"]) for l in lanes}
    a = {}; b = {}; ratios = {}
    for lid in ids:
        av = block_arm_values(slots, lid)
        ab = [av[("A", i)] for i in range(1, 5)]
        bb = [av[("B", i)] for i in range(1, 5)]
        a[lid] = ab; b[lid] = bb
        ratios[lid] = [bb[i] / ab[i] for i in range(4)]
    gate = {lid: gate_ratio(ratios[lid]) for lid in ids}
    agg = {lid: arm_aggregate_ratio(a[lid], b[lid]) for lid in ids}
    gate_dev = {lid: abs(gate[lid] - 1) for lid in ids}
    agg_dev = {lid: abs(agg[lid] - 1) for lid in ids}
    return {"slots": slots, "ids": ids, "meta": meta, "A": a, "B": b,
            "block_ratios": ratios, "gate": gate, "aggregate": agg,
            "gate_dev": gate_dev, "aggregate_dev": agg_dev}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign-dir", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = analyze(a.campaign_dir)
    out = {
        "lanes": len(r["ids"]),
        "gate_deviation": deviation_stats(list(r["gate_dev"].values())),
        "aggregate_deviation": deviation_stats(list(r["aggregate_dev"].values())),
        "gate_within": within_counts(r["gate_dev"].values()),
        "aggregate_within": within_counts(r["aggregate_dev"].values()),
    }
    print(json.dumps(out, sort_keys=True) if a.json else "\n".join(f"{k}: {v}" for k, v in out.items()))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
