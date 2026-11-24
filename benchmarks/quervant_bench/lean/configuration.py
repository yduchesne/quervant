"""Small, directly reviewable benchmark configurations (no qualification contracts)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from .artifacts import (ArtifactError, configuration_directory,
                        configuration_filename, create_configuration)

SIZES = (10_000, 100_000)
CLASSES = {"absent": ("key", "never"), "rare": ("key", "singleton"),
           "medium": ("group", "medium"), "common": ("key", "common")}
K_RETAINED = (1, 10, 32, 64, 100, 128, 256, 512, 1024)
K_CROSS = (10, 100)
BASELINE_REF = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
# The previous real study with Tantivy numeric ordinal is immutable history.
# New cross-engine runs must use the actual native doc_id string sort.
STRING_SORT_CONTRACT = "doc_id:keyword:utf8-lex-asc:v1"
STRING_SORT_TANTIVY_VERSION = "0.25.0"

# PERF-05-C: retained historical A reference and the only B-only warm study.
PERF05_HISTORICAL_RESULT = "quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json"
PERF05_HISTORICAL_BLOB = "a809f0362553e4e5c93ac1593ef478e8eef6a865"
PERF05_HISTORICAL_CONFIGURATION_ID = "c4083f1e-4ce2-4477-b282-04c4d40b187f"
PERF05_HISTORICAL_RUN_ID = "f2df1d40-2eee-4fcb-9593-ba8433e08c4a"
PERF05_HISTORICAL_SOURCE = "256501f0e700ed199f316e79d128389375177530"
PERF05_HISTORICAL_ARM = "Q"
PERF05_HISTORICAL_MODE = "historical-absolute-unpaired"
PERF05_BLOCKS = 12
PERF05_SLOTS_PER_ARM = 1
PERF05_WARMUPS = 5
PERF05_SAMPLES = 20
PERF05_SEED = 20261122
PERF05_MIN_BLOCKS = 4
PERF05_MAX_AA_GAIN_PERCENT = 15


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_configuration(family: str, name: str, description: str, *,
                          timestamp: str | None = None,
                          regime: str = "warm",
                          baseline_revision: str | None = None,
                          candidate_revision: str | None = None,
                          quervant_revision: str | None = None) -> dict[str, Any]:
    """Generate one *new* immutable configuration with its own UUID."""
    if family not in ("retained-key", "cross-engine", "perf-02", "perf-05", "perf-06"):
        raise ArtifactError("family must be retained-key, cross-engine, perf-02, perf-05 or perf-06")
    if regime not in ("warm", "process-cold") or (family != "cross-engine" and regime != "warm"):
        raise ArtifactError("only cross-engine supports a process-cold study")
    if family not in ("perf-02", "perf-06") and (baseline_revision is not None or candidate_revision is not None):
        raise ArtifactError("pinned A/B revisions are only accepted for perf-02/perf-06")
    if family == "perf-05":
        if (not isinstance(quervant_revision, str)
                or not re.fullmatch(r"[0-9a-f]{40}", quervant_revision)):
            raise ArtifactError("perf-05 requires a lowercase 40-hex pinned Quervant revision")
        if baseline_revision is not None or candidate_revision is not None:
            raise ArtifactError("perf-05 accepts only --quervant-revision")
    elif quervant_revision is not None:
        raise ArtifactError("quervant revision is only accepted for perf-05")
    policy = {"blocks": PERF05_BLOCKS if family == "perf-05" else 12,
              "slots_per_arm": PERF05_SLOTS_PER_ARM if family == "perf-05" else 2,
              "warmups": PERF05_WARMUPS, "samples": PERF05_SAMPLES,
              "bootstrap_resamples": 10_000, "seed": PERF05_SEED, "min_blocks": PERF05_MIN_BLOCKS,
              "min_gain_percent": 0, "max_regression_percent": 0,
              "max_aa_gain_percent": PERF05_MAX_AA_GAIN_PERCENT, "exclude_blocks": {}, "control_arms": [],
              "readiness": {"intervals": 4, "interval_ms": 250,
                            "max_busy_percent": 25, "max_steal_percent": 2}}
    if family == "retained-key":
        arm_settings = {"A": {"engine": "quervant", "mode": "BASE", "source": "baseline"},
                        "L": {"engine": "quervant", "mode": "linear", "source": "current"},
                        "P": {"engine": "quervant", "mode": "prefilter", "source": "current"},
                        "H": {"engine": "quervant", "mode": "exact_set", "source": "current"}}
        top_k = list(K_RETAINED)
    elif family in ("perf-02", "perf-06"):
        arm_settings = {
            "A": {"engine": "quervant", "mode": "by-top-k", "source": "pinned",
                  "revision": baseline_revision},
            "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned",
                  "revision": candidate_revision},
        }
        top_k = list(K_CROSS)
    elif family == "perf-05":
        arm_settings = {
            "B": {"engine": "quervant", "mode": "by-top-k", "source": "pinned",
                  "revision": quervant_revision},
        }
        top_k = list(K_CROSS)
    else:
        arm_settings = {"Q": {"engine": "quervant", "mode": "by-top-k", "source": "current"},
                        "T": {"engine": "tantivy", "mode": "default", "source": "current"},
                        "J": {"engine": "lucene", "mode": "default", "source": "current"}}
        top_k = [100] if regime == "process-cold" else list(K_CROSS)
    sizes = [10_000] if regime == "process-cold" else list(SIZES)
    classes = ["medium"] if regime == "process-cold" else list(CLASSES)
    timed_operation = ("process-launch-to-first-jsonl-response"
                       if regime == "process-cold" else "exact-term-search-plus-topk-projection")
    config = {
        "schema": "benchmark-configuration-v1", "name": name, "description": description,
        "configuration_id": str(uuid4()), "created_utc": timestamp or now_utc(),
        "family": family,
        "workload": {"id": "pr15d-exact-keyword-v1", "sizes": sizes,
                     "classes": classes, "top_k": top_k, "regimes": [regime],
                     "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
                     "timed_operation": timed_operation},
        "arms": arm_settings,
        "baseline": ("Q" if family == "cross-engine"
                     else "B" if family == "perf-05" else "A"),
        "control": ({"enabled": True, "baseline": "BB", "equivalent": "BB2"}
                    if family == "perf-05"
                    else {"enabled": True, "baseline": "AA", "equivalent": "AA2"}),
        "build": {"release": True, "locked": True, "baseline_ref": BASELINE_REF if family == "retained-key" else None,
                  "prefilter_profile": "P2", "quervant_feature": "quervant-core/pr15i-d3c-experiment" if family == "retained-key" else None,
                  **({"sort_contract": STRING_SORT_CONTRACT,
                      "tantivy_version": STRING_SORT_TANTIVY_VERSION}
                     if family == "cross-engine" else {})},
        "policy": policy,
    }
    if family == "perf-05":
        config["historical_reference"] = {
            "family": "cross-engine",
            "result_file": PERF05_HISTORICAL_RESULT,
            "git_blob_sha1": PERF05_HISTORICAL_BLOB,
            "configuration_id": PERF05_HISTORICAL_CONFIGURATION_ID,
            "run_id": PERF05_HISTORICAL_RUN_ID,
            "arm": PERF05_HISTORICAL_ARM,
            "source_revision": PERF05_HISTORICAL_SOURCE,
            "mode": PERF05_HISTORICAL_MODE,
        }
    validate_configuration(config)
    return config


def validate_configuration(config: Mapping[str, Any]) -> None:
    """Simple shape/semantic validation, never a signature/hash/approval gate."""
    configuration_filename(config)
    if config.get("schema") != "benchmark-configuration-v1":
        raise ArtifactError("unknown benchmark configuration schema")
    family = config.get("family")
    if family not in ("retained-key", "cross-engine", "perf-02", "perf-05", "perf-06"):
        raise ArtifactError("unsupported benchmark family")
    workload, arms, policy = config.get("workload"), config.get("arms"), config.get("policy")
    if not isinstance(workload, dict) or not isinstance(arms, dict) or not isinstance(policy, dict):
        raise ArtifactError("workload, arms and policy must be objects")
    expected_arms = ({"A", "L", "P", "H"} if family == "retained-key" else
                     {"Q", "T", "J"} if family == "cross-engine" else
                     {"B"} if family == "perf-05" else {"A", "B"})
    expected_baseline = ("Q" if family == "cross-engine"
                         else "B" if family == "perf-05" else "A")
    if set(arms) != expected_arms or config.get("baseline") != expected_baseline:
        raise ArtifactError("arm catalog or baseline does not match benchmark family")
    expected_engines = ({"A": "quervant", "L": "quervant", "P": "quervant", "H": "quervant"}
                        if family == "retained-key" else
                        {"Q": "quervant", "T": "tantivy", "J": "lucene"}
                        if family == "cross-engine" else
                        {"B": "quervant"} if family == "perf-05" else {"A": "quervant", "B": "quervant"})
    expected_modes = ({"A": "BASE", "L": "linear", "P": "prefilter", "H": "exact_set"}
                      if family == "retained-key" else
                      {"Q": "by-top-k", "T": "default", "J": "default"}
                      if family == "cross-engine" else
                      {"B": "by-top-k"} if family == "perf-05" else {"A": "by-top-k", "B": "by-top-k"})
    for arm_id, arm in arms.items():
        if (not isinstance(arm, dict) or arm.get("engine") != expected_engines[arm_id] or
                arm.get("mode") != expected_modes[arm_id]):
            raise ArtifactError(f"arm {arm_id} does not declare the required engine/strategy")
        if family in ("perf-02", "perf-05", "perf-06"):
            if (arm.get("source") != "pinned" or
                    not isinstance(arm.get("revision"), str) or
                    not re.fullmatch(r"[0-9a-f]{40}", arm["revision"])):
                raise ArtifactError(f"{family} arm {arm_id} requires a pinned 40-hex Git commit")
    regimes = workload.get("regimes")
    if regimes not in (["warm"], ["process-cold"]):
        raise ArtifactError("one study must select exactly one cache regime")
    if family != "cross-engine" and regimes != ["warm"]:
        raise ArtifactError(f"{family} supports warm measurements only")
    cold = regimes == ["process-cold"]
    expected_sizes = [10_000] if cold else list(SIZES)
    expected_classes = ["medium"] if cold else list(CLASSES)
    expected_k = ([100] if cold else list(K_RETAINED if family == "retained-key" else K_CROSS))
    if (workload.get("sizes") != expected_sizes or workload.get("classes") != expected_classes
            or workload.get("top_k") != expected_k):
        raise ArtifactError("study requires the declared warm matrix or single cold-start lane")
    if workload.get("query_semantics") != "exact-keyword-total-hits-and-ordered-doc-ids":
        raise ArtifactError("unknown exact-keyword workload semantics")
    expected_operation = ("process-launch-to-first-jsonl-response"
                          if cold else "exact-term-search-plus-topk-projection")
    if workload.get("timed_operation") != expected_operation:
        raise ArtifactError("timed_operation disagrees with selected study regime")
    if (not isinstance(config.get("build"), dict) or config["build"].get("release") is not True or
            config["build"].get("locked") is not True):
        raise ArtifactError("BM-10 requires release, locked adapter builds")
    if family in ("perf-02", "perf-05", "perf-06") and config["build"].get("baseline_ref") is not None:
        raise ArtifactError("perf-02/perf-05/perf-06 source revisions belong to their pinned arms")
    if family == "retained-key" and not re.fullmatch(r"[0-9a-f]{40}", config["build"].get("baseline_ref") or ""):
        raise ArtifactError("retained-key baseline_ref must be an explicit 40-hex Git commit")
    expected_feature = ("quervant-core/pr15i-d3c-experiment"
                        if family == "retained-key" else None)
    if config["build"].get("quervant_feature") != expected_feature:
        raise ArtifactError("Quervant strategy experiment is restricted to retained-key diagnostics")
    if config["build"].get("prefilter_profile") != "P2":
        raise ArtifactError("BM-10 prefilter-active lanes require P2")
    if family == "cross-engine":
        sort_contract = config["build"].get("sort_contract")
        if sort_contract is None:
            # Read-only validation and historical reanalysis are supported for
            # the original numeric-ordinal configuration; new measurement is not.
            if config["build"].get("tantivy_version") not in (None, "0.22.1"):
                raise ArtifactError("legacy sort contract has inconsistent Tantivy version")
        elif sort_contract == STRING_SORT_CONTRACT:
            if config["build"].get("tantivy_version") != STRING_SORT_TANTIVY_VERSION:
                raise ArtifactError("native string-sort Tantivy version must be pinned")
        else:
            raise ArtifactError("unknown cross-engine string sort contract")
    control_roles = (("BB", "BB2") if family == "perf-05" else ("AA", "AA2"))
    control_block = config.get("control")
    if (not isinstance(control_block, dict) or control_block.get("enabled") is not True or
            control_block.get("baseline") != control_roles[0] or
            control_block.get("equivalent") != control_roles[1]):
        raise ArtifactError("control must use the two equivalent baseline roles")
    if family == "perf-05":
        reference = config.get("historical_reference")
        expected_reference = {
            "family": "cross-engine",
            "result_file": PERF05_HISTORICAL_RESULT,
            "git_blob_sha1": PERF05_HISTORICAL_BLOB,
            "configuration_id": PERF05_HISTORICAL_CONFIGURATION_ID,
            "run_id": PERF05_HISTORICAL_RUN_ID,
            "arm": PERF05_HISTORICAL_ARM,
            "source_revision": PERF05_HISTORICAL_SOURCE,
            "mode": PERF05_HISTORICAL_MODE,
        }
        if reference != expected_reference:
            raise ArtifactError("perf-05 historical reference is fixed and must match exactly")
        if (policy.get("blocks") != PERF05_BLOCKS or
                policy.get("slots_per_arm") != PERF05_SLOTS_PER_ARM or
                policy.get("warmups") != PERF05_WARMUPS or
                policy.get("samples") != PERF05_SAMPLES or
                policy.get("seed") != PERF05_SEED or
                policy.get("min_blocks") != PERF05_MIN_BLOCKS or
                policy.get("max_aa_gain_percent") != PERF05_MAX_AA_GAIN_PERCENT):
            raise ArtifactError("perf-05 requires the frozen B/B schedule and thresholds")
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
                                  "metric": ("cold_start_first_response_latency"
                                             if regime == "process-cold" else "search_latency"),
                                  "unit": "ns", "direction": "lower",
                                  "comparability": "COMPARABLE"})
    return lanes


def prepare_configuration(studies_root: Path, *, family: str, name: str,
                          description: str, regime: str = "warm",
                          baseline_revision: str | None = None,
                          candidate_revision: str | None = None,
                          quervant_revision: str | None = None) -> Path:
    """Create under studies/<family>/<regime>/configurations automatically."""
    config = default_configuration(family, name, description, regime=regime,
                                   baseline_revision=baseline_revision,
                                   candidate_revision=candidate_revision,
                                   quervant_revision=quervant_revision)
    return create_configuration(configuration_directory(studies_root, config), config)
