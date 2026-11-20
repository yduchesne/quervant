"""Read the unchanged D3-C readiness format without promoting its status label.

The old controller stores seven raw counter snapshots, six interval metrics and
a settling interval. Recompute its exact idle-only busy formula and lower median
from those counters; preserve the original document bytes in the raw inventory.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..config.errors import BM_IDENTITY_INVALID, BenchError
from ..config.identity import validate_digest
from ..qualification.contracts import require_closed
from .protocols import D3C_PROTOCOL_RAW_SHA256


def validate_retained_readiness(document: object, *, campaign: str, requirements: Mapping[str, Any]) -> dict[str, Any]:
    def reject(message: str) -> None:
        raise BenchError(BM_IDENTITY_INVALID, message, field_path="host_readiness")

    doc = require_closed(document, "legacy-readiness", {
        "schema", "protocol_sha256", "campaign", "role_cpus", "host_fingerprint",
        "settle_monotonic_start_ns", "settle_monotonic_end_ns", "observations",
        "interval_metrics", "lower_median_busy_permille", "readiness_status",
        "failure_codes", "optional_cpu_frequency_khz", "queries_executed",
    })
    if doc["schema"] != "pr15i-d3c-host-readiness-v1" or doc["campaign"] != campaign or doc["protocol_sha256"] != D3C_PROTOCOL_RAW_SHA256.removeprefix("sha256:"):
        reject("legacy readiness is not bound to the frozen campaign/protocol")
    validate_digest("sha256:" + str(doc["host_fingerprint"]), "host_fingerprint")
    cpus = require_closed(doc["role_cpus"], "role_cpus", {"adapter", "controller"})
    if any(type(cpu) is not int or cpu < 0 for cpu in cpus.values()) or cpus["adapter"] == cpus["controller"]:
        reject("legacy readiness must observe two distinct CPU identifiers")
    start, end = doc["settle_monotonic_start_ns"], doc["settle_monotonic_end_ns"]
    if type(start) is not int or type(end) is not int or start < 0 or not 4_500_000_000 <= end - start <= 7_500_000_000:
        reject("the legacy readiness settling interval is invalid")
    observations = doc["observations"]
    if not isinstance(observations, list) or len(observations) != 7:
        reject("legacy readiness requires seven counter snapshots")
    for observation in observations:
        item = require_closed(observation, "observation", {"monotonic_ns", "cpus"})
        if type(item["monotonic_ns"]) is not int or item["monotonic_ns"] < end:
            reject("legacy readiness has an invalid sample timestamp")
        ticks = require_closed(item["cpus"], "cpus", {str(cpu) for cpu in cpus.values()})
        for values in ticks.values():
            if not isinstance(values, list) or len(values) != 8 or any(type(value) is not int or value < 0 for value in values):
                reject("legacy readiness counters must be eight nonnegative integers")
    metrics = require_closed(doc["interval_metrics"], "interval_metrics", {"adapter", "controller"})
    medians = require_closed(doc["lower_median_busy_permille"], "lower_median_busy_permille", {"adapter", "controller"})
    for role, cpu in cpus.items():
        if not isinstance(metrics[role], list) or len(metrics[role]) != 6:
            reject("legacy readiness interval metrics are incomplete")
        busy_values = []
        for index, (previous, current) in enumerate(zip(observations, observations[1:]), 1):
            elapsed = current["monotonic_ns"] - previous["monotonic_ns"]
            if not requirements["min_interval_ms"] * 1_000_000 <= elapsed <= requirements["max_interval_ms"] * 1_000_000:
                reject("legacy readiness interval duration is outside the frozen bounds")
            delta = [after - before for before, after in zip(previous["cpus"][str(cpu)], current["cpus"][str(cpu)])]
            total = sum(delta)
            if min(delta) < 0 or total <= 0:
                reject("legacy readiness counters decreased or failed to advance")
            busy = 1000 * (total - delta[3]) // total
            steal = 1000 * delta[7] // total
            if busy > requirements["max_busy_permille"] or steal > requirements["max_steal_permille"]:
                reject("legacy readiness raw counters exceed the frozen limits")
            recorded = require_closed(metrics[role][index - 1], "interval", {"interval", "actual_ms", "busy_permille", "steal_permille"})
            for name, value in (("interval", index), ("busy_permille", busy), ("steal_permille", steal)):
                if type(recorded[name]) is not int or recorded[name] != value:
                    reject("legacy readiness recorded metrics differ from raw counters")
            if type(recorded["actual_ms"]) not in (int, float) or recorded["actual_ms"] != elapsed / 1_000_000:
                reject("legacy readiness recorded duration differs from raw timestamps")
            busy_values.append(busy)
        median = sorted(busy_values)[2]
        if median > requirements["max_median_busy_permille"] or type(medians[role]) is not int or medians[role] != median:
            reject("legacy readiness median differs or exceeds the frozen limit")
    if doc["readiness_status"] != "READY" or doc["failure_codes"] != [] or type(doc["queries_executed"]) is not int or doc["queries_executed"] != 0:
        reject("legacy readiness did not complete before query acquisition")
    return dict(doc)
