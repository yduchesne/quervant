#!/usr/bin/env python3
"""PR 15I-B residual — extract order/absolute timing from sealed direct campaigns.

Diagnostic only; never a performance acceptance test. Reads the 16 sealed slot
records and recomputes lane medians with the frozen PR15D summarize function.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SPEC = os.path.join(ROOT, "benchmarks", "pr15e_b1", "run_targeted.py")
_spec = importlib.util.spec_from_file_location("residual_base", SPEC)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
pr15d = base.pr15d_run

LANES = ("pr15d_v1/10000/rare/k100", "pr15d_v1/10000/medium/k100",
         "pr15d_v1/100000/rare/k100", "pr15d_v1/100000/medium/k100")
EXPECTED = ((1, "A", "B", "B", "A"), (2, "B", "A", "A", "B"),
            (3, "B", "A", "A", "B"), (4, "A", "B", "B", "A"))
SCHEMA = "pr15i-b-order-diagnostic-v1"


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    root = os.path.realpath(args.checkout_root)
    campaign = os.path.realpath(args.campaign)
    out = os.path.realpath(args.out)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-b", "residual", "diagnostics"))
    if os.path.commonpath([out, allowed]) != allowed or out == allowed:
        print("out must be under target/pr15i-b/residual/diagnostics", file=sys.stderr)
        return 3
    if os.path.exists(out):
        print("out exists; use a fresh id", file=sys.stderr)
        return 3
    os.makedirs(out)
    raw = os.path.join(campaign, "raw")
    slots = []
    for index in range(1, 17):
        with open(os.path.join(raw, "slots", f"slot-{index:02d}.json"), "r", encoding="utf-8") as handle:
            slots.append(json.load(handle))
    if len(slots) != 16:
        print("slot count", file=sys.stderr)
        return 3
    keyed = {slot["slot_index"]: slot for slot in slots}
    for block, *order in EXPECTED:
        for position, arm in enumerate(order, start=1):
            slot = keyed[(block - 1) * 4 + position]
            if (slot["block"], slot["position"], slot["arm"]) != (block, position, arm):
                print("schedule mismatch", file=sys.stderr)
                return 3
    result = {"schema": SCHEMA, "campaign": os.path.basename(campaign),
              "seal_sha256": sha(os.path.join(raw, "seal.json")), "lanes": {}}
    for lane in LANES:
        records = {}
        for block, *_order in EXPECTED:
            records[block] = {}
            for arm in ("A", "B"):
                values = []
                absolutes = []
                for position in range(1, 5):
                    slot = keyed[(block - 1) * 4 + position]
                    if slot["arm"] != arm:
                        continue
                    lane_record = next(r for r in slot["trial"]["lanes"] if r["id"] == lane)
                    if len(lane_record["samples_ns"]) != 20 or lane_record["oracle_ok"] is not True:
                        print("lane record invalid", file=sys.stderr)
                        return 3
                    summary = pr15d.summarize(lane_record["samples_ns"])
                    if summary != lane_record["summary_ns"]:
                        print("summary mismatch", file=sys.stderr)
                        return 3
                    values.append(summary["median"])
                    absolutes.append({"position": position, "median_ns": summary["median"]})
                records[block][arm] = {"medians": values, "absolutes": absolutes}
        block_ratios = []
        for block, *_order in EXPECTED:
            a = sum(records[block]["A"]["medians"]) / len(records[block]["A"]["medians"])
            b = sum(records[block]["B"]["medians"]) / len(records[block]["B"]["medians"])
            block_ratios.append(b / a)
        abba = [block_ratios[i] for i in (0, 3)]
        baab = [block_ratios[i] for i in (1, 2)]
        abba_mean = sum(abba) / len(abba)
        baab_mean = sum(baab) / len(baab)
        gap = abs(abba_mean - baab_mean)
        result["lanes"][lane] = {
            "block_ratios": block_ratios,
            "abba_ratios": abba,
            "baab_ratios": baab,
            "abba_mean": abba_mean,
            "baab_mean": baab_mean,
            "schedule_gap": gap,
            "order_label": "ORDER_ASSOCIATION_OBSERVED" if gap >= 0.05 else "NOT_ESTABLISHED",
            "records": records,
        }
    payload = json.dumps(result, indent=2, sort_keys=True).encode() + b"\n"
    with open(os.path.join(out, "order-analysis.json"), "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({lane: {"block_ratios": [round(x, 6) for x in data["block_ratios"]],
                             "abba_mean": round(data["abba_mean"], 6),
                             "baab_mean": round(data["baab_mean"], 6),
                             "schedule_gap": round(data["schedule_gap"], 6),
                             "label": data["order_label"]}
                      for lane, data in result["lanes"].items()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
