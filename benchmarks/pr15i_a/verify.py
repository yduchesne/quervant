#!/usr/bin/env python3
"""PR 15I-A read-only campaign verifier.

Rehashes every sealed raw file, reconstructs the arm measurements from the
sealed evidence, recomputes the frozen gate matrix and rejects any mismatch.
The verifier never creates, replaces or normalizes evidence. Exit codes:
``0`` verified, ``2`` invalid/mismatched evidence, ``3`` blocked input.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

TOOLING_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
RUNNER = os.path.join(TOOLING_ROOT, "benchmarks", "pr15i_a", "run.py")
_spec = importlib.util.spec_from_file_location("pr15i_a_controller", RUNNER)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load controller from {RUNNER}")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)

BLOCK_FILE = "blocks.json"


class VerifyError(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _load(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise VerifyError(2, f"cannot read {path}: {error}") from error


def _rehash(campaign: str) -> dict:
    seal_path = os.path.join(campaign, "raw", "seal.json")
    seal = _load(seal_path)
    if seal.get("schema") != run.SEAL_SCHEMA:
        raise VerifyError(2, "bad seal schema")
    files = seal.get("files")
    if not isinstance(files, dict) or not files:
        raise VerifyError(2, "empty seal")
    for relative, expected in files.items():
        path = os.path.join(campaign, "raw", relative)
        if not os.path.isfile(path):
            raise VerifyError(2, f"sealed file missing: {relative}")
        actual = run.sha256_file(path)
        if actual != expected:
            raise VerifyError(2, f"seal mismatch {relative}")
        if relative.startswith("../") or relative.startswith("/"):
            raise VerifyError(2, f"unsafe sealed path {relative}")
    return seal


def _reconstruct_arm(campaign: str, arm: str, blocks: dict, sizes: dict) -> dict:
    slots = []
    for index in range(1, 17):
        path = os.path.join(campaign, "raw", "slots", f"slot-{index:02d}.json")
        slots.append(_load(path))
    warm = [slot for slot in slots if slot.get("arm") == arm]
    if len(warm) != 8:
        raise VerifyError(2, f"arm {arm} does not own eight warm slots")
    binary = _load(os.path.join(campaign, "raw", "manifest.json"))
    if binary.get("sources", {}).get(arm) is None:
        raise VerifyError(2, f"manifest lacks the {arm} source")
    data = {
        "arm": arm,
        "source_sha": binary["sources"][arm],
        "sizes": {"n": sizes[arm], "indices": {}},
        "blocks": {
            kind: blocks[arm][kind] for kind in ("reopen", "build_commit", "remote")
        },
        "warm": warm,
        "oracles_ok": True,
        "feature_checks_ok": True,
        "adapter_sha256": binary["binary_sha256"][arm]["adapter"],
        "reopen_sha256": binary["binary_sha256"][arm]["reopen"],
        "remote_sha256": binary["binary_sha256"][arm]["remote"],
    }
    for slot in warm:
        for record in slot["trial"]["lanes"]:
            if record.get("oracle_ok") is not True:
                raise VerifyError(2, f"{record['id']} oracle is not ok")
            if len(record.get("samples_ns", [])) != run.MEASURED:
                raise VerifyError(2, f"{record['id']} sample count drift")
    return data


def _check_schedule(slots: list[dict]) -> None:
    if len(slots) != 16:
        raise VerifyError(2, "expected sixteen warm slots")
    expected_positions = []
    for block, order in enumerate(run.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            expected_positions.append((block, position, arm))
    actual = [
        (slot.get("block"), slot.get("position"), slot.get("arm"))
        for slot in sorted(slots, key=lambda slot: slot.get("slot_index", 0))
    ]
    if actual != expected_positions:
        raise VerifyError(2, "warm slot arm/block order does not match the frozen schedule")
    if [slot.get("slot_index") for slot in sorted(slots, key=lambda s: s["slot_index"])] != list(
        range(1, 17)
    ):
        raise VerifyError(2, "slot indices are not 1..16")


def _check_integer_size_gates(report: dict) -> None:
    sizes = report["sizes"]
    a = sizes["A"]
    b = sizes["B"]
    # Cross multiplication keeps the frozen boundaries exact.
    if not b["100000"]["sidecar_bytes"] * 4 <= a["100000"]["sidecar_bytes"] * 3:
        raise VerifyError(2, "A-P01 does not hold under exact integer arithmetic")
    if not b["100000"]["committed_index_bytes"] * 20 <= a["100000"][
        "committed_index_bytes"
    ] * 19:
        raise VerifyError(2, "A-P02 does not hold under exact integer arithmetic")
    for key in ("sidecar_bytes", "committed_index_bytes"):
        if not b["10000"][key] * 50 <= a["10000"][key] * 51:
            raise VerifyError(2, f"A-P03 does not hold for {key}")


def _check_baseline_sentinels(report: dict) -> None:
    a = report["sizes"]["A"]["100000"]
    if (
        a["committed_index_bytes"] != run.PR15I0_100K_TOTAL
        or a["sidecar_bytes"] != run.PR15I0_100K_SIDECAR
    ):
        raise VerifyError(
            2,
            "arm A 100K size does not reproduce the PR 15I0 acceptance sentinels",
        )


def _close(left, right, tolerance: float = 1e-12) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _close(left[key], right[key], tolerance) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _close(a, b, tolerance) for a, b in zip(left, right)
        )
    if isinstance(left, float) or isinstance(right, float):
        return abs(float(left) - float(right)) <= tolerance
    return left == right


def verify_campaign(checkout_root: str, campaign: str) -> dict:
    root = os.path.realpath(checkout_root)
    campaign = os.path.realpath(campaign)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-a", "campaigns"))
    if os.path.commonpath([campaign, allowed]) != allowed or campaign == allowed:
        raise VerifyError(3, "--campaign must be under target/pr15i-a/campaigns")
    run.load_protocol(root)
    _rehash(campaign)
    manifest = _load(os.path.join(campaign, "raw", "manifest.json"))
    measurements = _load(os.path.join(campaign, "raw", "measurements.json"))
    blocks = _load(os.path.join(campaign, "raw", BLOCK_FILE))
    if manifest.get("sources", {}).get("A") != measurements.get("sources", {}).get("A"):
        raise VerifyError(2, "manifest/measurement A source mismatch")
    if manifest.get("sources", {}).get("B") != measurements.get("sources", {}).get("B"):
        raise VerifyError(2, "manifest/measurement B source mismatch")
    if manifest.get("sizes") != measurements.get("sizes"):
        raise VerifyError(2, "manifest/measurement size mismatch")
    slots = [
        _load(os.path.join(campaign, "raw", "slots", f"slot-{index:02d}.json"))
        for index in range(1, 17)
    ]
    _check_schedule(slots)
    a = _reconstruct_arm(campaign, "A", blocks, manifest["sizes"])
    b = _reconstruct_arm(campaign, "B", blocks, manifest["sizes"])
    report, _details = run.derive(a, b)
    if not _close(report["gates"], measurements["gates"]):
        raise VerifyError(2, "recomputed gate matrix differs from the sealed matrix")
    if report["decision"] != measurements["decision"]:
        raise VerifyError(2, "recomputed decision differs from the sealed decision")
    for key in (
        "reopen_ratios",
        "build_commit_sum_ratios",
        "build_ratios",
        "commit_ratios",
        "rss_ratios",
        "rss_absolute_increase_bytes",
        "remote_ratios",
        "warm_ratios",
        "size_ratios",
        "sizes",
    ):
        if not _close(report[key], measurements[key]):
            raise VerifyError(2, f"recomputed {key} differs from the sealed value")
    _check_baseline_sentinels(measurements)
    if measurements["decision"] == "A_CANDIDATE_ACCEPTED_PENDING_QA":
        _check_integer_size_gates(measurements)
    results = _load(os.path.join(campaign, "sanitized", "results.json"))
    decision = _load(os.path.join(campaign, "sanitized", "decision.json"))
    if results.get("decision") != measurements["decision"]:
        raise VerifyError(2, "sanitized result decision mismatch")
    if decision.get("decision") != measurements["decision"]:
        raise VerifyError(2, "sanitized decision mismatch")
    if not _close(results.get("gates"), measurements["gates"]):
        raise VerifyError(2, "sanitized gate matrix mismatch")
    return {
        "schema": "pr15i-a-verification-v1",
        "decision": measurements["decision"],
        "files": len(_load(os.path.join(campaign, "raw", "seal.json"))["files"]),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PR 15I-A read-only verifier")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify_campaign(args.checkout_root, args.campaign)
    except run.RunBlocked as error:
        print(f"A_VERIFY_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3
    except VerifyError as error:
        print(f"A_VERIFY_FAIL: {error.detail}", file=sys.stderr)
        return error.code
    print(
        f"PR15I_A_VERIFY decision={result['decision']} VERIFIED files={result['files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
