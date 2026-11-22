"""Small, directly reviewable benchmark configurations (no qualification contracts)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from .artifacts import ArtifactError, configuration_filename, create_configuration

SIZES = (10_000, 100_000)
CLASSES = {"absent": ("key", "never"), "rare": ("key", "singleton"),
           "medium": ("group", "medium"), "common": ("key", "common")}
K_RETAINED = (1, 10, 32, 64, 100, 128, 256, 512, 1024)
K_CROSS = (10, 100)
BASELINE_REF = "39dbd9f571a58bea8cc03d5a406533298e809bfe"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_configuration(family: str, name: str, description: str, *,
                          timestamp: str | None = None) -> dict[str, Any]:
    """Generate one *new* immutable configuration with its own UUID."""
    if family not in ("retained-key", "cross-engine"):
        raise ArtifactError("family must be retained-key or cross-engine")
    policy = {"blocks": 12, "slots_per_arm": 2, "warmups": 5, "samples": 20,
              "bootstrap_resamples": 10_000, "seed": 20261122, "min_blocks": 4,
              "min_gain_percent": 0, "max_regression_percent": 0,
              "max_aa_gain_percent": 15, "exclude_blocks": {}, "control_arms": [],
              "readiness": {"intervals": 4, "interval_ms": 250,
                            "max_busy_percent": 25, "max_steal_percent": 2}}
    if family == "retained-key":
        arm_settings = {"A": {"engine": "quervant", "mode": "BASE", "source": "baseline"},
                        "L": {"engine": "quervant", "mode": "linear", "source": "current"},
                        "P": {"engine": "quervant", "mode": "prefilter", "source": "current"},
                        "H": {"engine": "quervant", "mode": "exact_set", "source": "current"}}
        top_k = list(K_RETAINED)
        regimes = ["warm"]
    else:
        arm_settings = {"Q": {"engine": "quervant", "mode": "by-top-k", "source": "current"},
                        "T": {"engine": "tantivy", "mode": "default", "source": "current"},
                        "J": {"engine": "lucene", "mode": "default", "source": "current"}}
        top_k = list(K_CROSS)
        regimes = ["warm", "process-cold"]
    config = {
        "schema": "benchmark-configuration-v1", "name": name, "description": description,
        "configuration_id": str(uuid4()), "created_utc": timestamp or now_utc(),
        "family": family,
        "workload": {"id": "pr15d-exact-keyword-v1", "sizes": list(SIZES),
                     "classes": list(CLASSES), "top_k": top_k, "regimes": regimes,
                     "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
                     "timed_operation": "exact-term-search-plus-topk-projection"},
        "arms": arm_settings, "baseline": "A" if family == "retained-key" else "Q",
        "control": {"enabled": True, "baseline": "AA", "equivalent": "AA2"},
        "build": {"release": True, "locked": True, "baseline_ref": BASELINE_REF if family == "retained-key" else None,
                  "prefilter_profile": "P2", "quervant_feature": "quervant-core/pr15i-d3c-experiment"},
        "policy": policy,
    }
    validate_configuration(config)
    return config


def validate_configuration(config: Mapping[str, Any]) -> None:
    """Simple shape/semantic validation, never a signature/hash/approval gate."""
    configuration_filename(config)
    if config.get("schema") != "benchmark-configuration-v1":
        raise ArtifactError("unknown benchmark configuration schema")
    family = config.get("family")
    if family not in ("retained-key", "cross-engine"):
        raise ArtifactError("unsupported benchmark family")
    workload, arms, policy = config.get("workload"), config.get("arms"), config.get("policy")
    if not isinstance(workload, dict) or not isinstance(arms, dict) or not isinstance(policy, dict):
        raise ArtifactError("workload, arms and policy must be objects")
    expected_arms = {"A", "L", "P", "H"} if family == "retained-key" else {"Q", "T", "J"}
    expected_baseline = "A" if family == "retained-key" else "Q"
    if set(arms) != expected_arms or config.get("baseline") != expected_baseline:
        raise ArtifactError("arm catalog or baseline does not match benchmark family")
    expected_engines = ({"A": "quervant", "L": "quervant", "P": "quervant", "H": "quervant"}
                        if family == "retained-key" else {"Q": "quervant", "T": "tantivy", "J": "lucene"})
    expected_modes = ({"A": "BASE", "L": "linear", "P": "prefilter", "H": "exact_set"}
                      if family == "retained-key" else {"Q": "by-top-k", "T": "default", "J": "default"})
    for arm_id, arm in arms.items():
        if (not isinstance(arm, dict) or arm.get("engine") != expected_engines[arm_id] or
                arm.get("mode") != expected_modes[arm_id]):
            raise ArtifactError(f"arm {arm_id} does not declare the required engine/strategy")
    if workload.get("sizes") != list(SIZES) or workload.get("classes") != list(CLASSES):
        raise ArtifactError("BM-10 requires both full corpus sizes and all cardinality classes")
    if workload.get("top_k") != list(K_RETAINED if family == "retained-key" else K_CROSS):
        raise ArtifactError("BM-10 requires the complete family Top-K matrix")
    if workload.get("regimes") != (["warm"] if family == "retained-key" else ["warm", "process-cold"]):
        raise ArtifactError("BM-10 requires its specified cache regimes")
    if workload.get("query_semantics") != "exact-keyword-total-hits-and-ordered-doc-ids":
        raise ArtifactError("unknown exact-keyword workload semantics")
    if workload.get("timed_operation") != "exact-term-search-plus-topk-projection":
        raise ArtifactError("unknown timed operation; cannot establish comparability")
    if (not isinstance(config.get("build"), dict) or config["build"].get("release") is not True or
            config["build"].get("locked") is not True):
        raise ArtifactError("BM-10 requires release, locked adapter builds")
    if family == "retained-key" and not re.fullmatch(r"[0-9a-f]{40}", config["build"].get("baseline_ref") or ""):
        raise ArtifactError("retained-key baseline_ref must be an explicit 40-hex Git commit")
    if config["build"].get("quervant_feature") != "quervant-core/pr15i-d3c-experiment":
        raise ArtifactError("Quervant strategy instrumentation feature must be named")
    if config["build"].get("prefilter_profile") != "P2":
        raise ArtifactError("BM-10 prefilter-active lanes require P2")
    if (not isinstance(config.get("control"), dict) or config["control"].get("enabled") is not True or
            config["control"].get("baseline") != "AA" or config["control"].get("equivalent") != "AA2"):
        raise ArtifactError("A/A control must use the two equivalent baseline roles")
    for field in ("blocks", "slots_per_arm", "samples", "warmups", "bootstrap_resamples", "min_blocks"):
        n = policy.get(field)
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise ArtifactError(f"policy.{field} must be a positive integer")
    if policy["blocks"] % len(arms) != 0 or policy["blocks"] % 2 != 0:
        raise ArtifactError("block count must support position balance in treatment and A/A")
    if policy["min_blocks"] > policy["blocks"]:
        raise ArtifactError("minimum retained block count exceeds scheduled count")
    if policy["bootstrap_resamples"] > 100_000:
        raise ArtifactError("excessive bootstrap iterations")
    seed = policy.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ArtifactError("policy.seed must be an unsigned 64-bit integer")
    for field in ("min_gain_percent", "max_regression_percent", "max_aa_gain_percent"):
        value = policy.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ArtifactError(f"policy.{field} must be a finite nonnegative number")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ArtifactError(f"policy.{field} must be a finite nonnegative number") from None
        if not number.is_finite() or number < 0:
            raise ArtifactError(f"policy.{field} must be a finite nonnegative number")
    if policy.get("control_arms") != []:
        raise ArtifactError("A/A is a separate control phase, not a treatment arm")
    readiness = policy.get("readiness")
    if not isinstance(readiness, dict):
        raise ArtifactError("policy.readiness must be a declared object")
    for key in ("intervals", "interval_ms", "max_busy_percent", "max_steal_percent"):
        n = readiness.get(key)
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ArtifactError(f"policy.readiness.{key} must be a positive integer")
    if readiness["intervals"] > 20 or readiness["interval_ms"] > 5000:
        raise ArtifactError("readiness observation budget exceeded")
    if readiness["max_busy_percent"] > 100 or readiness["max_steal_percent"] > 100:
        raise ArtifactError("readiness percentages must not exceed 100")
    excluded = policy.get("exclude_blocks", {})
    if not isinstance(excluded, dict):
        raise ArtifactError("exclude_blocks must be a map")
    lane_names = {f"{n}/{cls}/k{k}/{regime}" for n in workload["sizes"]
                  for cls in workload["classes"] for k in workload["top_k"]
                  for regime in workload["regimes"]}
    for lane, numbers in excluded.items():
        if lane not in lane_names or not isinstance(numbers, list):
            raise ArtifactError("exclude_blocks must identify declared lanes with lists")
        if (len(numbers) != len(set(str(n) for n in numbers)) or
                any(isinstance(n, bool) or not isinstance(n, int) or
                    not 1 <= n <= policy["blocks"] for n in numbers)):
            raise ArtifactError("exclude_blocks must list unique scheduled block numbers")


def lanes_for(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One lane per corpus/cardinality/Top-K/cache regime; all arms share it."""
    validate_configuration(config)
    workload = config["workload"]
    lanes: list[dict[str, Any]] = []
    for n in workload["sizes"]:
        for cls in workload["classes"]:
            field, term = CLASSES[cls]
            for k in workload["top_k"]:
                for regime in workload["regimes"]:
                    lanes.append({"id": f"{n}/{cls}/k{k}/{regime}", "workload_id": workload["id"],
                                  "n": n, "class": cls, "field": field, "term": term,
                                  "k": k, "cache_regime": regime,
                                  "query_semantics": workload["query_semantics"],
                                  "timed_operation": workload["timed_operation"],
                                  "metric": "search_latency", "unit": "ns", "direction": "lower",
                                  "comparability": "COMPARABLE"})
    return lanes


def prepare_configuration(directory: Path, *, family: str, name: str, description: str) -> Path:
    return create_configuration(directory, default_configuration(family, name, description))
