"""Reviewed official design templates and independent G0 authorization.

Two closed design templates live outside the source roster:

* ``benchmarks/official-protocols/retained-key-topk-v1.json``
* ``benchmarks/official-protocols/cross-engine-keyword-v1.json``

A template is never its own trust root. :func:`read_approved_template` requires an
*independently pinned* digest, and :func:`verify_g0_authorization` requires a
second independently supplied digest of the run-specific authorization document
plus the actual observed source/binary/corpus/host/schedule identities.

Neither function can mint an approval: the agent computes candidate documents and
digests only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import (
    validate_digest,
    validate_semantic_id,
    validate_source_commit,
    validate_uuid4,
)
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import require_safe_root, validate_relative_member
from ..evidence.provenance import repository_root
from ..qualification.contracts import (
    bound_payload,
    document_digest,
    require_closed,
    require_kind,
    require_uint,
    require_version,
)
from . import contracts
from .contracts import (
    DECISION_INCONCLUSIVE,
    FRAMEWORK_QA_ROSTER,
    OFFICIAL_SCOPE,
    REAL_ORIGIN,
    SCHEMA_VERSION,
    SOURCE_QA_ROSTER,
    STATISTICS_CROSS_ENGINE,
    STATISTICS_RETAINED_KEY,
    VERIFIER_CHECK_IDS,
)

DESIGN_TEMPLATE_KIND = "official-design-template"
AUTHORIZATION_KIND = contracts.TEMPORARY_AUTHORIZATION_KIND

STUDY_RETAINED_KEY = "retained-key-topk-real-v1"
STUDY_CROSS_ENGINE = "cross-engine-keyword-real-v1"

#: The single reviewed campaign sequence for each official study. A control-only,
#: reordered, duplicated or extended authorization must never open acquisition.
_PERMITTED_CAMPAIGN_ORDERS: dict[str, tuple[str, ...]] = {
    STUDY_CROSS_ENGINE: ("control", "treatment"),
    STUDY_RETAINED_KEY: (
        "d3c-v3r3-base-aa-01",
        "d3c-v3r3-strategies-01",
        "d3c-v3r3-strategies-02",
    ),
}
OFFICIAL_STUDIES: tuple[str, ...] = (STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY)

TEMPLATE_FILES: dict[str, str] = {
    STUDY_RETAINED_KEY: "benchmarks/official-protocols/retained-key-topk-v1.json",
    STUDY_CROSS_ENGINE: "benchmarks/official-protocols/cross-engine-keyword-v1.json",
}

#: Frozen historical backend identities.
D3C_PROTOCOL_PATH = "benchmarks/pr15i_d3_c/protocol_v3r3.json"
D3C_PROTOCOL_RAW_SHA256 = (
    "sha256:c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c"
)
D3C_PROTOCOL_SCHEMA = "pr15i-d3c-strategy-evaluation-v1"
D3C_BASE_COMMIT = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
D3C_EXPERIMENT_COMMIT = "3ad6c5184fbe9c011abb731415a007e3f19d21de"
D3C_BACKEND = "historical-d3c-v3r3-frozen"
D3C_INDEX_100K_COMMITTED_SENTINEL = 15_747_551
D3C_CAMPAIGN_NAMES: tuple[str, ...] = ("d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02")
D3C_CONTROL_NAME = "d3c-v3r3-base-aa-01"

PR15D_SPEC_PATH = "benchmarks/pr15d/spec/pr15d_v1.json"
PR15D_BACKEND = "historical-pr15d-v1-frozen"
PR15D_ENGINES: tuple[str, ...] = ("lucene", "quervant", "tantivy")
PR15D_ENGINE_PINS: dict[str, str] = {
    "lucene": "9.12.3",
    "quervant": "workspace",
    "tantivy": "=0.22.1",
}
PR15D_TRIAL_ORDER: dict[str, tuple[str, ...]] = {
    "1": ("quervant", "tantivy", "lucene"),
    "2": ("tantivy", "lucene", "quervant"),
    "3": ("lucene", "quervant", "tantivy"),
}

#: The frozen D3-C A/A numeric windows transferred to the cross-engine control.
D3C_AA_WINDOWS: dict[str, str] = {
    "median_min": "0.850000",
    "median_max": "1.150000",
    "block_min": "0.800000",
    "block_max": "1.250000",
    "exempt_hard_min": "0.670000",
    "exempt_hard_max": "1.500000",
}
D3C_AA_SOFT_OUTLIERS = 1
D3C_DISPERSION_LIMIT = "1.100000"
D3C_MIN_RETAINED_BLOCKS = 4
D3C_BOOTSTRAP_RESAMPLES = 10_000
D3C_BOOTSTRAP_CONFIDENCE = "0.950000"
D3C_WITHIN_ARM_CAP_OTHER = "1.500000"
D3C_WITHIN_ARM_CAP_100K_MEDIUM_COMMON = "1.250000"
D3C_PREFILTER_PROFILE = "P2"

MAX_AUTHORIZATION_BYTES = 262_144

_TEMPLATE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "study_id",
        "family",
        "measurement_backend",
        "backend_protocol_identity",
        "backend_diagnostic_flag",
        "outer_protocol_mapping",
        "workload_identity",
        "source_requirements",
        "host_requirements",
        "schedule",
        "measurement",
        "controls",
        "correctness",
        "statistics",
        "policy",
        "predecessors",
        "stopping",
        "required_qa",
        "publication",
        "limitations",
    }
)

_AUTHORIZATION_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "study_id",
        "run_id",
        "evidence_origin",
        "qualification_scope",
        "design_digest",
        "backend_protocol_digest",
        "source_commit",
        "source_file_set_digest",
        "source_tree_sha",
        "adapter_source_manifest_digest",
        "binary_manifest_digest",
        "corpus_manifest_digest",
        "original_reference_verifier_digest",
        "host_preflight_digest",
        "control_schedule_digest",
        "treatment_schedule_digest",
        "qa_source_digest",
        "qa_framework_digest",
        "operator_approval_id",
        "independent_protocol_review_id",
        "approved_at_utc",
        "approved_output_root_identity",
        "policy_digest",
        "permitted_campaign_order",
        "measurement_retries",
    }
)

#: Every identity an authorization binds and a caller must also observe.
OBSERVED_IDENTITY_FIELDS: tuple[str, ...] = (
    "design_digest",
    "backend_protocol_digest",
    "source_commit",
    "source_file_set_digest",
    "source_tree_sha",
    "adapter_source_manifest_digest",
    "binary_manifest_digest",
    "corpus_manifest_digest",
    "original_reference_verifier_digest",
    "host_preflight_digest",
    "control_schedule_digest",
    "treatment_schedule_digest",
    "qa_source_digest",
    "qa_framework_digest",
    "policy_digest",
)

_DIGEST_IDENTITY_FIELDS: tuple[str, ...] = tuple(
    name for name in OBSERVED_IDENTITY_FIELDS if name != "source_commit"
)


@dataclass(frozen=True)
class OfficialFreeze:
    """Immutable, independently authorized G0 lock for one official run."""

    study_id: str
    run_id: str
    design_digest: str
    authorization_digest: str
    backend_protocol_digest: str
    source_commit: str
    source_file_set_digest: str
    source_tree_sha: str
    adapter_source_manifest_digest: str
    binary_manifest_digest: str
    corpus_manifest_digest: str
    original_reference_verifier_digest: str
    host_preflight_digest: str
    control_schedule_digest: str
    treatment_schedule_digest: str
    qa_source_digest: str
    qa_framework_digest: str
    operator_approval_id: str
    independent_protocol_review_id: str
    approved_at_utc: str
    approved_output_root_identity: str
    policy_digest: str
    permitted_campaign_order: tuple[str, ...]
    measurement_retries: int = 0

    def identity_record(self) -> dict[str, Any]:
        """Return the closed canonical identity payload of this freeze."""

        return {
            "study_id": self.study_id,
            "run_id": self.run_id,
            "design_digest": self.design_digest,
            "authorization_digest": self.authorization_digest,
            "backend_protocol_digest": self.backend_protocol_digest,
            "source_commit": self.source_commit,
            "source_file_set_digest": self.source_file_set_digest,
            "source_tree_sha": self.source_tree_sha,
            "adapter_source_manifest_digest": self.adapter_source_manifest_digest,
            "binary_manifest_digest": self.binary_manifest_digest,
            "corpus_manifest_digest": self.corpus_manifest_digest,
            "original_reference_verifier_digest": self.original_reference_verifier_digest,
            "host_preflight_digest": self.host_preflight_digest,
            "control_schedule_digest": self.control_schedule_digest,
            "treatment_schedule_digest": self.treatment_schedule_digest,
            "qa_source_digest": self.qa_source_digest,
            "qa_framework_digest": self.qa_framework_digest,
            "operator_approval_id": self.operator_approval_id,
            "independent_protocol_review_id": self.independent_protocol_review_id,
            "approved_at_utc": self.approved_at_utc,
            "policy_digest": self.policy_digest,
            "permitted_campaign_order": list(self.permitted_campaign_order),
            "measurement_retries": self.measurement_retries,
        }

    @property
    def identity_digest(self) -> str:
        """Return the canonical digest of the freeze identity payload."""

        return content_digest(self.identity_record())


def _schema(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def host_environment_matches(selector: object, observed: object) -> bool:
    """Match a reviewed host selector without relabelling the observation.

    The union is a design requirement, never an observed environment. Literal
    native-Linux and WSL2 designs retain their narrower requirements.
    """

    if type(selector) is not str or type(observed) is not str:
        return False
    if observed not in ("native-linux", "wsl2"):
        return False
    return selector == observed or selector == "native-linux-or-wsl2"


# ---------------------------------------------------------------------------
# Safe document reading
# ---------------------------------------------------------------------------


def read_canonical_json(
    path: Path,
    *,
    max_bytes: int = contracts.MAX_DOCUMENT_BYTES,
    require_canonical: bool = True,
) -> dict[str, Any]:
    """Read one strict UTF-8 JSON document with a hard byte budget.

    New official documents must be stored in canonical byte form. The unmodified
    frozen legacy backend protocol is parsed strictly but is not re-encoded, so
    its historical bytes stay byte-identical.
    """

    candidate = Path(path)
    try:
        info = os.lstat(candidate)
    except OSError as exc:
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "official document is unavailable") from exc
    if os.path.islink(candidate) or not os.path.isfile(candidate):
        raise BenchError(BM_UNSAFE_INPUT, "official document must be a regular file")
    if info.st_size > max_bytes:
        raise BenchError(
            BM_UNSAFE_INPUT, f"official document exceeds the {max_bytes}-byte budget"
        )
    try:
        payload = candidate.read_bytes()
    except OSError as exc:  # pragma: no cover - guarded by lstat
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "official document cannot be read") from exc
    if len(payload) > max_bytes:
        raise BenchError(
            BM_UNSAFE_INPUT, f"official document exceeds the {max_bytes}-byte budget"
        )
    document = loads_json(decode_text(payload))
    if not isinstance(document, Mapping):
        raise _schema("official document must be a JSON object", "document")
    if require_canonical and canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT, "official document is not stored in canonical byte form"
        )
    return dict(document)


def _decimal(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise _schema(f"{field} must be a decimal string", field)
    whole, separator, fraction = value.partition(".")
    if not separator or not whole.isdigit() or len(fraction) != 6 or not fraction.isdigit():
        raise _schema(f"{field} must carry exactly six fractional digits", field)
    return value


def _int_sequence(value: object, field: str, *, minimum: int = 1) -> list[int]:
    if not isinstance(value, list) or not value:
        raise _schema(f"{field} must be a non-empty array", field)
    result: list[int] = []
    for index, item in enumerate(value):
        observed = require_uint(item, f"{field}[{index}]")
        if observed < minimum:
            raise _schema(f"{field}[{index}] must be at least {minimum}", field)
        result.append(observed)
    return result


def _sorted_slugs(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _schema(f"{field} must be a non-empty array", field)
    result = [validate_semantic_id(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if result != sorted(result) or len(set(result)) != len(result):
        raise _identity(f"{field} must be sorted and unique", field)
    return result


def _arm_rows(value: object, field: str, arms: Sequence[str], width: int, rows: int) -> list[list[str]]:
    if not isinstance(value, list) or len(value) != rows:
        raise _schema(f"{field} must hold exactly {rows} blocks", field)
    result: list[list[str]] = []
    for block_index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != width:
            raise _schema(f"{field}[{block_index}] must hold exactly {width} slots", field)
        normalized: list[str] = []
        for slot_index, arm in enumerate(row):
            if arm not in arms:
                raise _identity(
                    f"{field}[{block_index}][{slot_index}] is not a permitted arm", field
                )
            normalized.append(str(arm))
        result.append(normalized)
    return result


# ---------------------------------------------------------------------------
# Template validation
# ---------------------------------------------------------------------------


def _validate_retained_key_template(doc: Mapping[str, Any]) -> None:
    if doc["study_id"] != STUDY_RETAINED_KEY:
        raise _identity("study_id is not the retained-key official study", "study_id")
    if doc["family"] != "retained-key":
        raise _identity("family must be 'retained-key'", "family")
    if doc["measurement_backend"] != D3C_BACKEND:
        raise _identity("measurement_backend is not the frozen D3-C backend", "measurement_backend")
    backend = require_closed(
        doc["backend_protocol_identity"],
        "backend_protocol_identity",
        frozenset({"schema", "path", "raw_sha256"}),
    )
    if backend["schema"] != D3C_PROTOCOL_SCHEMA:
        raise _identity("backend protocol schema is not the frozen D3-C schema", "schema")
    if backend["path"] != D3C_PROTOCOL_PATH:
        raise _identity("backend protocol path is not the frozen D3-C protocol", "path")
    if validate_digest(backend["raw_sha256"], "raw_sha256") != D3C_PROTOCOL_RAW_SHA256:
        raise _identity("backend protocol digest is not the frozen raw SHA-256", "raw_sha256")
    if doc["backend_diagnostic_flag"] is not True:
        raise _identity(
            "the frozen D3-C protocol declares diagnostic_only=true and it must be recorded",
            "backend_diagnostic_flag",
        )
    mapping = require_closed(
        doc["outer_protocol_mapping"],
        "outer_protocol_mapping",
        frozenset(
            {
                "reviewed",
                "diagnostic_only_disclosed",
                "new_execution_required",
                "historical_protocol_unmodified",
            }
        ),
    )
    for name in sorted(mapping):
        if mapping[name] is not True:
            raise _identity(f"outer_protocol_mapping.{name} must be true", name)

    workload = require_closed(
        doc["workload_identity"],
        "workload_identity",
        frozenset({"kind", "n_values", "classes", "k_values", "lane_count", "regime", "unit"}),
    )
    if workload["kind"] != "retained-key-topk":
        raise _identity("workload kind is not retained-key-topk", "kind")
    n_values = _int_sequence(workload["n_values"], "n_values")
    if n_values != [10_000, 100_000]:
        raise _identity("n_values must be exactly [10000, 100000]", "n_values")
    classes = [str(item) for item in workload["classes"]]
    if classes != ["absent", "rare", "medium", "common"]:
        raise _identity("classes must be the frozen four", "classes")
    k_values = _int_sequence(workload["k_values"], "k_values")
    if k_values != [1, 10, 32, 64, 100, 128, 256, 512, 1024]:
        raise _identity("k_values must be the frozen nine", "k_values")
    if require_uint(workload["lane_count"], "lane_count") != 72:
        raise _identity("lane_count must be 72", "lane_count")
    if workload["regime"] != "warm":
        raise _identity("regime must be warm", "regime")
    if workload["unit"] != contracts.OFFICIAL_UNIT:
        raise _identity("workload unit must be nanoseconds", "unit")

    source = require_closed(
        doc["source_requirements"],
        "source_requirements",
        frozenset(
            {
                "base_commit",
                "experiment_commit",
                "feature_identity",
                "index_100k_committed_sentinel",
                "corpus_manifest_sha256",
            }
        ),
    )
    validate_digest(source["corpus_manifest_sha256"], "corpus_manifest_sha256")
    if validate_source_commit(source["base_commit"], "base_commit") != D3C_BASE_COMMIT:
        raise _identity("base_commit is not the frozen base", "base_commit")
    if validate_source_commit(source["experiment_commit"], "experiment_commit") != D3C_EXPERIMENT_COMMIT:
        raise _identity("experiment_commit is not the frozen experiment source", "experiment_commit")
    if source["feature_identity"] != "pr15i-d3c-experiment":
        raise _identity("feature_identity is not the frozen feature", "feature_identity")
    if require_uint(
        source["index_100k_committed_sentinel"], "index_100k_committed_sentinel"
    ) != D3C_INDEX_100K_COMMITTED_SENTINEL:
        raise _identity("the 100K committed index sentinel differs", "index_100k_committed_sentinel")

    schedule = require_closed(
        doc["schedule"],
        "schedule",
        frozenset(
            {
                "blocks",
                "arms",
                "control_name",
                "campaign_names",
                "control_order",
                "campaign_01_order",
                "campaign_02_order",
                "schedule_seeds",
                "warmups_per_lane_slot",
                "samples_per_lane_slot",
            }
        ),
    )
    if require_uint(schedule["blocks"], "blocks") != 12:
        raise _identity("the retained-key schedule must hold twelve blocks", "blocks")
    arms = [str(item) for item in schedule["arms"]]
    if arms != ["A", "B", "H", "L", "P"]:
        raise _identity("schedule arms must be the frozen control+treatment arms", "arms")
    if schedule["control_name"] != D3C_CONTROL_NAME:
        raise _identity("control_name is not the frozen control", "control_name")
    if [str(item) for item in schedule["campaign_names"]] != list(D3C_CAMPAIGN_NAMES):
        raise _identity("campaign_names are not the frozen campaigns", "campaign_names")
    _arm_rows(schedule["control_order"], "control_order", ("A", "B"), 4, 12)
    _arm_rows(schedule["campaign_01_order"], "campaign_01_order", ("A", "L", "P", "H"), 8, 12)
    _arm_rows(schedule["campaign_02_order"], "campaign_02_order", ("A", "L", "P", "H"), 8, 12)
    seeds = require_closed(
        schedule["schedule_seeds"],
        "schedule_seeds",
        frozenset({"control", "campaign_01", "campaign_02"}),
    )
    for name in sorted(seeds):
        require_uint(seeds[name], f"schedule_seeds.{name}")
    if require_uint(schedule["warmups_per_lane_slot"], "warmups_per_lane_slot") != 5:
        raise _identity("warmups_per_lane_slot must be 5", "warmups_per_lane_slot")
    if require_uint(schedule["samples_per_lane_slot"], "samples_per_lane_slot") != 20:
        raise _identity("samples_per_lane_slot must be 20", "samples_per_lane_slot")

    measurement = require_closed(
        doc["measurement"],
        "measurement",
        frozenset({"control_slots", "treatment_slots", "lane_records", "timed_observations"}),
    )
    if require_uint(measurement["control_slots"], "control_slots") != 48:
        raise _identity("control_slots must be 48", "control_slots")
    if require_uint(measurement["treatment_slots"], "treatment_slots") != 192:
        raise _identity("treatment_slots must be 192", "treatment_slots")
    if require_uint(measurement["lane_records"], "lane_records") != 17_280:
        raise _identity("lane_records must be 17,280", "lane_records")
    if require_uint(measurement["timed_observations"], "timed_observations") != 345_600:
        raise _identity("timed_observations must be 345,600", "timed_observations")

    controls = require_closed(
        doc["controls"],
        "controls",
        frozenset({"a_a_required", "control_name", "arms", "windows", "soft_outliers"}),
    )
    if controls["a_a_required"] is not True:
        raise _identity("a real A/A control is mandatory", "a_a_required")
    if controls["control_name"] != D3C_CONTROL_NAME:
        raise _identity("controls.control_name is not the frozen control", "control_name")
    if [str(item) for item in controls["arms"]] != ["A", "B"]:
        raise _identity("controls.arms must be A/B", "arms")
    windows = require_closed(
        controls["windows"],
        "windows",
        frozenset(D3C_AA_WINDOWS),
    )
    for name in sorted(D3C_AA_WINDOWS):
        if _decimal(windows[name], name) != D3C_AA_WINDOWS[name]:
            raise _identity("A/A window is not the frozen numeric rule", "windows")
    if require_uint(controls["soft_outliers"], "soft_outliers") != D3C_AA_SOFT_OUTLIERS:
        raise _identity("soft_outliers must be the frozen one", "soft_outliers")

    correctness = require_closed(
        doc["correctness"],
        "correctness",
        frozenset({"oracle", "require_exact_answers", "require_sorted_doc_ids", "require_mode_markers"}),
    )
    if correctness["oracle"] != "benchmarks/pr15d/corpus/oracle.py":
        raise _identity("correctness.oracle is not the independent corpus oracle", "oracle")
    for name in ("require_exact_answers", "require_sorted_doc_ids", "require_mode_markers"):
        if correctness[name] is not True:
            raise _identity(f"correctness.{name} must be true", name)

    statistics = require_closed(
        doc["statistics"],
        "statistics",
        frozenset(
            {
                "method_id",
                "min_retained_blocks_per_lane",
                "within_arm_exclusion_cap_other",
                "within_arm_exclusion_cap_100k_medium_common",
                "bootstrap_resamples",
                "bootstrap_confidence",
                "four_value_median",
                "prefilter_profile",
            }
        ),
    )
    if statistics["method_id"] != STATISTICS_RETAINED_KEY:
        raise _identity("statistics.method_id is not the retained-key method", "method_id")
    if require_uint(statistics["min_retained_blocks_per_lane"], "min_retained_blocks_per_lane") != D3C_MIN_RETAINED_BLOCKS:
        raise _identity("min_retained_blocks_per_lane must be 4", "min_retained_blocks_per_lane")
    if _decimal(statistics["within_arm_exclusion_cap_other"], "cap") != D3C_WITHIN_ARM_CAP_OTHER:
        raise _identity("the within-arm cap differs from the frozen value", "within_arm_exclusion_cap_other")
    if (
        _decimal(statistics["within_arm_exclusion_cap_100k_medium_common"], "cap")
        != D3C_WITHIN_ARM_CAP_100K_MEDIUM_COMMON
    ):
        raise _identity(
            "the 100K medium/common within-arm cap differs from the frozen value",
            "within_arm_exclusion_cap_100k_medium_common",
        )
    if require_uint(statistics["bootstrap_resamples"], "bootstrap_resamples") != D3C_BOOTSTRAP_RESAMPLES:
        raise _identity("bootstrap_resamples must be 10000", "bootstrap_resamples")
    if _decimal(statistics["bootstrap_confidence"], "bootstrap_confidence") != D3C_BOOTSTRAP_CONFIDENCE:
        raise _identity("bootstrap_confidence must be 0.95", "bootstrap_confidence")
    if statistics["four_value_median"] != "sorted[1]":
        raise _identity(
            "the frozen D3-C four-value median is the lower-middle sorted[1]",
            "four_value_median",
        )
    if statistics["prefilter_profile"] != D3C_PREFILTER_PROFILE:
        raise _identity("prefilter_profile must be the frozen P2", "prefilter_profile")

    policy = require_closed(
        doc["policy"],
        "policy",
        frozenset({"policy_chain", "not_derivable_status", "tie_preference", "claim_on_tie"}),
    )
    if policy["policy_chain"] != "t7-f2-nine-k-v1":
        raise _identity("policy_chain is not the frozen nine-K chain", "policy_chain")
    if policy["not_derivable_status"] != contracts.DECISION_POLICY_NOT_DERIVABLE:
        raise _identity("not_derivable_status is not the frozen status", "not_derivable_status")
    if policy["tie_preference"] != "P":
        raise _identity("tie_preference must be the frozen P arm", "tie_preference")
    if policy["claim_on_tie"] != "TIE_PREFERENCE_NOT_PROVEN_FASTER":
        raise _identity("claim_on_tie must not claim a speed win", "claim_on_tie")

    predecessors = require_closed(
        doc["predecessors"],
        "predecessors",
        frozenset({"t6_freeze_receipt", "control_first", "publish_between_campaigns", "order"}),
    )
    if predecessors["t6_freeze_receipt"] != "target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json":
        raise _identity("the T6 freeze receipt path differs from the frozen backend", "t6_freeze_receipt")
    for name in ("control_first", "publish_between_campaigns"):
        if predecessors[name] is not True:
            raise _identity(f"predecessors.{name} must be true", name)
    order = [str(item) for item in predecessors["order"]]
    if order != [D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES]:
        raise _identity("predecessor order is not the frozen sequence", "order")


def _validate_cross_engine_template(doc: Mapping[str, Any]) -> None:
    if doc["study_id"] != STUDY_CROSS_ENGINE:
        raise _identity("study_id is not the cross-engine official study", "study_id")
    if doc["family"] != "cross-engine":
        raise _identity("family must be 'cross-engine'", "family")
    if doc["measurement_backend"] != PR15D_BACKEND:
        raise _identity("measurement_backend is not the frozen PR15D backend", "measurement_backend")
    backend = require_closed(
        doc["backend_protocol_identity"],
        "backend_protocol_identity",
        frozenset({"schema", "path", "raw_sha256"}),
    )
    if backend["schema"] != "pr15d-spec-v1":
        raise _identity("backend protocol schema is not the frozen PR15D spec", "schema")
    if backend["path"] != PR15D_SPEC_PATH:
        raise _identity("backend protocol path is not the frozen PR15D spec", "path")
    validate_digest(backend["raw_sha256"], "raw_sha256")
    if doc["backend_diagnostic_flag"] is not False:
        raise _identity("the PR15D spec is not diagnostic-only", "backend_diagnostic_flag")
    mapping = require_closed(
        doc["outer_protocol_mapping"],
        "outer_protocol_mapping",
        frozenset(
            {
                "reviewed",
                "original_backend_unchanged",
                "new_execution_required",
                "separate_aa_required",
            }
        ),
    )
    for name in sorted(mapping):
        if mapping[name] is not True:
            raise _identity(f"outer_protocol_mapping.{name} must be true", name)

    workload = require_closed(
        doc["workload_identity"],
        "workload_identity",
        frozenset(
            {
                "kind",
                "workload",
                "n_values",
                "classes",
                "k_values",
                "lane_count",
                "warm_lane_count",
                "process_cold_lane_count",
                "analyzer",
                "unit",
            }
        ),
    )
    if workload["kind"] != "cross-engine-keyword":
        raise _identity("workload kind is not cross-engine-keyword", "kind")
    if workload["workload"] != "pr15d_v1":
        raise _identity("workload is not pr15d_v1", "workload")
    if _int_sequence(workload["n_values"], "n_values") != [10_000, 100_000]:
        raise _identity("n_values must be exactly [10000, 100000]", "n_values")
    if [str(item) for item in workload["classes"]] != ["absent", "rare", "medium", "common"]:
        raise _identity("classes must be the frozen four", "classes")
    if _int_sequence(workload["k_values"], "k_values") != [10, 100]:
        raise _identity("k_values must be exactly [10, 100]", "k_values")
    if require_uint(workload["lane_count"], "lane_count") != 32:
        raise _identity("lane_count must be 32", "lane_count")
    if require_uint(workload["warm_lane_count"], "warm_lane_count") != 16:
        raise _identity("warm_lane_count must be 16", "warm_lane_count")
    if require_uint(workload["process_cold_lane_count"], "process_cold_lane_count") != 16:
        raise _identity("process_cold_lane_count must be 16", "process_cold_lane_count")
    if workload["analyzer"] != "keyword-exact":
        raise _identity("analyzer must be keyword-exact", "analyzer")
    if workload["unit"] != contracts.OFFICIAL_UNIT:
        raise _identity("workload unit must be nanoseconds", "unit")

    source = require_closed(
        doc["source_requirements"],
        "source_requirements",
        frozenset({"engines", "engine_pins", "corpus_generator", "corpus_oracle"}),
    )
    if [str(item) for item in source["engines"]] != list(PR15D_ENGINES):
        raise _identity("engines must be the frozen three-engine set", "engines")
    pins = require_closed(source["engine_pins"], "engine_pins", frozenset(PR15D_ENGINE_PINS))
    for engine in sorted(PR15D_ENGINE_PINS):
        if pins[engine] != PR15D_ENGINE_PINS[engine]:
            raise _identity(f"engine pin for {engine} differs from the frozen literal", "engine_pins")
    if source["corpus_generator"] != "benchmarks/pr15d/corpus/generate.py":
        raise _identity("corpus_generator is not the frozen generator", "corpus_generator")
    if source["corpus_oracle"] != "benchmarks/pr15d/corpus/oracle.py":
        raise _identity("corpus_oracle is not the independent oracle", "corpus_oracle")

    schedule = require_closed(
        doc["schedule"],
        "schedule",
        frozenset(
            {
                "trials",
                "trial_order",
                "warmups",
                "measured",
                "throughput_requests",
                "control_blocks",
                "control_slots_per_block",
                "control_order",
                "control_lane_count",
            }
        ),
    )
    if require_uint(schedule["trials"], "trials") != 3:
        raise _identity("trials must be exactly 3", "trials")
    order = require_closed(schedule["trial_order"], "trial_order", frozenset(PR15D_TRIAL_ORDER))
    for trial in sorted(PR15D_TRIAL_ORDER):
        if tuple(str(item) for item in order[trial]) != PR15D_TRIAL_ORDER[trial]:
            raise _identity("trial_order is not the frozen rotation", "trial_order")
    if require_uint(schedule["warmups"], "warmups") != 5:
        raise _identity("warmups must be 5", "warmups")
    if require_uint(schedule["measured"], "measured") != 20:
        raise _identity("measured must be 20", "measured")
    if require_uint(schedule["throughput_requests"], "throughput_requests") != 100:
        raise _identity("throughput_requests must be 100", "throughput_requests")
    if require_uint(schedule["control_blocks"], "control_blocks") != 12:
        raise _identity("the cross-engine A/A needs twelve blocks", "control_blocks")
    if require_uint(schedule["control_slots_per_block"], "control_slots_per_block") != 4:
        raise _identity("the cross-engine A/A needs four slots per block", "control_slots_per_block")
    _arm_rows(schedule["control_order"], "control_order", ("A", "B"), 4, 12)
    if require_uint(schedule["control_lane_count"], "control_lane_count") != 16:
        raise _identity("the cross-engine A/A must cover sixteen warm lanes", "control_lane_count")

    measurement = require_closed(
        doc["measurement"],
        "measurement",
        frozenset(
            {
                "trial_manifest_count",
                "build_records",
                "throughput_windows",
                "latency_samples",
                "control_slots",
                "control_samples",
                "trial_lane_records",
            }
        ),
    )
    expected_counts = {
        "trial_manifest_count": 9,
        "build_records": 18,
        "throughput_windows": 18,
        "latency_samples": 5_760,
        "control_slots": 48,
        "control_samples": 15_360,
        "trial_lane_records": 288,
    }
    for name, expected in expected_counts.items():
        if require_uint(measurement[name], name) != expected:
            raise _identity(f"{name} must be {expected}", name)

    controls = require_closed(
        doc["controls"],
        "controls",
        frozenset(
            {
                "a_a_required",
                "blocks",
                "slots_per_block",
                "warm_lane_count",
                "warmups",
                "samples",
                "windows",
                "soft_outliers",
            }
        ),
    )
    if controls["a_a_required"] is not True:
        raise _identity("a real A/A control is mandatory", "a_a_required")
    if require_uint(controls["blocks"], "blocks") != 12:
        raise _identity("controls.blocks must be 12", "blocks")
    if require_uint(controls["slots_per_block"], "slots_per_block") != 4:
        raise _identity("controls.slots_per_block must be 4", "slots_per_block")
    if require_uint(controls["warm_lane_count"], "warm_lane_count") != 16:
        raise _identity("controls.warm_lane_count must be 16", "warm_lane_count")
    if require_uint(controls["warmups"], "warmups") != 5:
        raise _identity("controls.warmups must be 5", "warmups")
    if require_uint(controls["samples"], "samples") != 20:
        raise _identity("controls.samples must be 20", "samples")
    windows = require_closed(controls["windows"], "windows", frozenset(D3C_AA_WINDOWS))
    for name in sorted(D3C_AA_WINDOWS):
        if _decimal(windows[name], name) != D3C_AA_WINDOWS[name]:
            raise _identity("A/A window is not the frozen numeric rule", "windows")
    if require_uint(controls["soft_outliers"], "soft_outliers") != D3C_AA_SOFT_OUTLIERS:
        raise _identity("soft_outliers must be the frozen one", "soft_outliers")

    correctness = require_closed(
        doc["correctness"],
        "correctness",
        frozenset({"oracle", "require_exact_answers", "require_sorted_doc_ids", "require_full_correctness_gate"}),
    )
    if correctness["oracle"] != "benchmarks/pr15d/corpus/oracle.py":
        raise _identity("correctness.oracle is not the independent corpus oracle", "oracle")
    for name in ("require_exact_answers", "require_sorted_doc_ids", "require_full_correctness_gate"):
        if correctness[name] is not True:
            raise _identity(f"correctness.{name} must be true", name)

    statistics = require_closed(
        doc["statistics"],
        "statistics",
        frozenset(
            {
                "method_id",
                "dispersion_limit",
                "eligible_regime",
                "excluded_lane_classes",
                "decision_status",
                "selected_arm_id",
                "performance_claim_allowed",
            }
        ),
    )
    if statistics["method_id"] != STATISTICS_CROSS_ENGINE:
        raise _identity("statistics.method_id is not the cross-engine method", "method_id")
    if _decimal(statistics["dispersion_limit"], "dispersion_limit") != D3C_DISPERSION_LIMIT:
        raise _identity("dispersion_limit must be 1.100000", "dispersion_limit")
    if statistics["eligible_regime"] != "warm":
        raise _identity("eligible_regime must be warm", "eligible_regime")
    if [str(item) for item in statistics["excluded_lane_classes"]] != list(
        contracts.EXCLUDED_LANE_CLASSES
    ):
        raise _identity("excluded_lane_classes is not the frozen exclusion set", "excluded_lane_classes")
    if statistics["decision_status"] != DECISION_INCONCLUSIVE:
        raise _identity("the frozen cross-engine decision is INCONCLUSIVE", "decision_status")
    if statistics["selected_arm_id"] is not None:
        raise _identity("no cross-engine winner may be selected in v1", "selected_arm_id")
    if statistics["performance_claim_allowed"] is not False:
        raise _identity("no cross-engine performance claim is allowed in v1", "performance_claim_allowed")

    policy = require_closed(
        doc["policy"],
        "policy",
        frozenset({"policy_chain", "decision", "report_descriptive_ratios", "significance_claim"}),
    )
    if policy["policy_chain"] != "pr15d-descriptive-three-trial-v1":
        raise _identity("policy_chain is not the frozen PR15D descriptive chain", "policy_chain")
    if policy["decision"] != DECISION_INCONCLUSIVE:
        raise _identity("policy.decision must be INCONCLUSIVE", "decision")
    if policy["report_descriptive_ratios"] is not True:
        raise _identity("descriptive ratios must remain reported", "report_descriptive_ratios")
    if policy["significance_claim"] != "none":
        raise _identity("no significance claim is permitted", "significance_claim")

    predecessors = require_closed(
        doc["predecessors"],
        "predecessors",
        frozenset({"control_first", "single_full_backend_run", "no_reduced_lane_set"}),
    )
    for name in sorted(predecessors):
        if predecessors[name] is not True:
            raise _identity(f"predecessors.{name} must be true", name)


def _validate_common_template(doc: Mapping[str, Any]) -> None:
    if doc["kind"] != DESIGN_TEMPLATE_KIND:
        raise _schema("template.kind is not the official design template", "kind")
    require_version(doc, "template")
    contracts.require_official_scope(doc)

    host = require_closed(
        doc["host_requirements"],
        "host_requirements",
        frozenset(
            {
                "environment",
                "filesystems",
                "cpu_pair_distinct_cores",
                "require_affinity",
                "max_busy_permille",
                "max_median_busy_permille",
                "max_steal_permille",
                "min_interval_ms",
                "max_interval_ms",
                "min_intervals",
                "readiness_retries",
            }
        ),
    )
    if (type(host["environment"]) is not str
            or host["environment"] not in ("native-linux", "wsl2", "native-linux-or-wsl2")):
        raise _identity("host environment must select native-linux, wsl2 or their union", "environment")
    if [str(item) for item in host["filesystems"]] != ["btrfs", "ext4", "xfs"]:
        raise _identity("host filesystems must be the frozen native set", "filesystems")
    if host["cpu_pair_distinct_cores"] is not True or host["require_affinity"] is not True:
        raise _identity("explicit affinity on distinct cores is mandatory", "host_requirements")
    for name, maximum in (
        ("max_busy_permille", 1000),
        ("max_median_busy_permille", 1000),
        ("max_steal_permille", 1000),
    ):
        if require_uint(host[name], name) > maximum:
            raise _identity(f"{name} must be a permille value", name)
    for name in ("min_interval_ms", "max_interval_ms", "min_intervals"):
        if require_uint(host[name], name) < 1:
            raise _identity(f"{name} must be positive", name)
    if require_uint(host["max_interval_ms"], "max_interval_ms") < require_uint(
        host["min_interval_ms"], "min_interval_ms"
    ):
        raise _identity("max_interval_ms must be >= min_interval_ms", "host_requirements")
    if require_uint(host["readiness_retries"], "readiness_retries") != 0:
        raise _identity("readiness_retries must be 0 (no implicit retry)", "readiness_retries")

    stopping = require_closed(
        doc["stopping"],
        "stopping",
        frozenset(
            {
                "measurement_retries",
                "on_failure",
                "allow_contended",
                "preserve_partial",
                "backend_timeout_seconds",
            }
        ),
    )
    if require_uint(stopping["backend_timeout_seconds"], "backend_timeout_seconds") < 1:
        raise _identity("backend_timeout_seconds must be positive", "backend_timeout_seconds")
    if require_uint(stopping["measurement_retries"], "measurement_retries") != 0:
        raise _identity("measurement_retries must be 0", "measurement_retries")
    if stopping["on_failure"] != "stopped-preserved":
        raise _identity("on_failure must be 'stopped-preserved'", "on_failure")
    if stopping["allow_contended"] is not False:
        raise _identity("contended acquisition is forbidden", "allow_contended")
    if stopping["preserve_partial"] is not True:
        raise _identity("partial evidence must be preserved", "preserve_partial")

    required_qa = require_closed(
        doc["required_qa"], "required_qa", frozenset({"framework", "source"})
    )
    if [str(item) for item in required_qa["framework"]] != list(FRAMEWORK_QA_ROSTER):
        raise _identity("required_qa.framework is not the frozen roster", "framework")
    if [str(item) for item in required_qa["source"]] != list(SOURCE_QA_ROSTER):
        raise _identity("required_qa.source is not the frozen roster", "source")

    publication = require_closed(
        doc["publication"],
        "publication",
        frozenset(
            {
                "output_root",
                "member_count",
                "freeze_member_count",
                "manifest_member_count",
                "exclusive",
                "reopen_verify",
            }
        ),
    )
    if publication["output_root"] != "benchmark-results/qualified-official":
        raise _identity("the official output root is not the frozen location", "output_root")
    if require_uint(publication["member_count"], "member_count") != len(contracts.MEMBER_NAMES):
        raise _identity("member_count must be 15", "member_count")
    if require_uint(publication["freeze_member_count"], "freeze_member_count") != len(
        contracts.FREEZE_MEMBERS
    ):
        raise _identity("freeze_member_count must be 13", "freeze_member_count")
    if require_uint(publication["manifest_member_count"], "manifest_member_count") != len(
        contracts.MANIFEST_MEMBERS
    ):
        raise _identity("manifest_member_count must be 14", "manifest_member_count")
    if publication["exclusive"] is not True or publication["reopen_verify"] is not True:
        raise _identity("exclusive publication and reopen verification are mandatory", "publication")

    limitations = _sorted_slugs(doc["limitations"], "limitations")
    if not limitations:
        raise _identity("limitations must not be empty", "limitations")


def validate_template(document: object) -> dict[str, Any]:
    """Validate one closed official design template for its declared family."""

    doc = require_closed(document, "template", _TEMPLATE_KEYS)
    _validate_common_template(doc)
    study_id = doc["study_id"]
    if study_id not in OFFICIAL_STUDIES:
        raise _identity("study_id is not a reviewed official study", "study_id")
    if study_id == STUDY_RETAINED_KEY:
        _validate_retained_key_template(doc)
    else:
        _validate_cross_engine_template(doc)
    bound_payload(doc, "template")
    return dict(doc)


def read_approved_template(
    path: Path, expected_digest: str
) -> tuple[dict[str, Any], str]:
    """Read a template and require the *independently pinned* approved digest.

    ``expected_digest`` must come from the reviewer's approval record. A candidate
    document can never supply its own trust root: passing the digest computed from
    the very file being read is a caller defect, not an authorization.
    """

    anchor = validate_digest(expected_digest, "expected_digest")
    document = read_canonical_json(Path(path))
    template = validate_template(document)
    digest = document_digest(template)
    if digest != anchor:
        raise _identity(
            "the design template does not match the independently approved digest",
            "expected_digest",
        )
    return template, digest


def verify_backend_protocol(template: Mapping[str, Any], repo_root: Path | None = None) -> dict[str, Any]:
    """Re-hash the frozen legacy backend protocol and cross-check the schedule.

    The historical protocol bytes are authoritative: a changed digest is an
    identity failure, never a re-pin.
    """

    root = Path(repo_root) if repo_root is not None else repository_root()
    safe_root = require_safe_root(root)
    backend = template["backend_protocol_identity"]
    relative = validate_relative_member(backend["path"])
    digest, length = sha256_regular_file(
        safe_root, relative, max_bytes=contracts.MAX_DOCUMENT_BYTES
    )
    if digest != backend["raw_sha256"]:
        raise _identity(
            "the frozen backend protocol raw digest differs from the approved template",
            "backend_protocol_digest",
        )
    if template["study_id"] != STUDY_RETAINED_KEY:
        return {
            "path": relative,
            "raw_digest": digest,
            "byte_length": length,
            "schedule_digest": content_digest(template["schedule"]),
        }

    protocol = read_canonical_json(safe_root / relative, require_canonical=False)
    if protocol.get("schema") != D3C_PROTOCOL_SCHEMA:
        raise _identity("the frozen D3-C protocol schema differs", "schema")
    schedule = template["schedule"]
    for template_key, protocol_key in (
        ("control_order", "control_order"),
        ("campaign_01_order", "campaign_01_order"),
        ("campaign_02_order", "campaign_02_order"),
    ):
        if protocol.get(protocol_key) != schedule[template_key]:
            raise _identity(
                f"the approved schedule differs from the frozen {protocol_key}",
                template_key,
            )
    if protocol.get("control_name") != schedule["control_name"]:
        raise _identity("the approved control name differs from the frozen backend", "control_name")
    if protocol.get("campaign_names") != schedule["campaign_names"]:
        raise _identity("the approved campaign names differ from the frozen backend", "campaign_names")
    if protocol.get("schedule_seeds") != schedule["schedule_seeds"]:
        raise _identity("the approved schedule seeds differ from the frozen backend", "schedule_seeds")
    if protocol.get("diagnostic_only") is not True:
        raise _identity(
            "the frozen D3-C protocol must still declare diagnostic_only=true",
            "diagnostic_only",
        )
    for key, expected in (
        ("n_values", template["workload_identity"]["n_values"]),
        ("classes", template["workload_identity"]["classes"]),
        ("k_values", template["workload_identity"]["k_values"]),
        ("blocks", template["schedule"]["blocks"]),
        ("samples_per_lane_slot", template["schedule"]["samples_per_lane_slot"]),
        ("warmups_per_lane_slot", template["schedule"]["warmups_per_lane_slot"]),
        ("source_base_sha", template["source_requirements"]["base_commit"]),
        ("source_experiment_sha", template["source_requirements"]["experiment_commit"]),
        (
            "index_100k_committed_sentinel",
            template["source_requirements"]["index_100k_committed_sentinel"],
        ),
        ("prefilter_profile", template["statistics"]["prefilter_profile"]),
        ("min_retained_blocks_per_lane", template["statistics"]["min_retained_blocks_per_lane"]),
        ("official_measurement_retries", template["stopping"]["measurement_retries"]),
        ("bootstrap_resamples", template["statistics"]["bootstrap_resamples"]),
        ("corpus_manifest_sha256", template["source_requirements"]["corpus_manifest_sha256"]),
    ):
        if key == "corpus_manifest_sha256":
            expected = str(expected).replace("sha256:", "", 1)
        if protocol.get(key) != expected:
            raise _identity(
                f"the approved template value for {key} differs from the frozen backend", key
            )
    return {
        "path": relative,
        "raw_digest": digest,
        "byte_length": length,
        "schedule_digest": content_digest(schedule),
        "protocol_schema": protocol["schema"],
    }


def validate_authorization(document: object) -> dict[str, Any]:
    """Validate one closed, run-specific official authorization document."""

    doc = require_closed(document, "authorization", _AUTHORIZATION_KEYS)
    require_version(doc, "authorization")
    require_kind(doc, AUTHORIZATION_KIND, "authorization")
    contracts.require_official_scope(doc)
    study_id = doc["study_id"]
    if study_id not in OFFICIAL_STUDIES:
        raise _identity("authorization.study_id is not a reviewed study", "study_id")
    validate_uuid4(doc["run_id"], "run_id")
    for name in _DIGEST_IDENTITY_FIELDS:
        validate_digest(doc[name], name)
    validate_source_commit(doc["source_commit"], "source_commit")
    for name in ("operator_approval_id", "independent_protocol_review_id"):
        value = doc[name]
        if not isinstance(value, str) or not value:
            raise _schema(f"{name} must be a non-empty identifier string", name)
        validate_semantic_id(value, name)
    approved = doc["approved_at_utc"]
    if not isinstance(approved, str) or not _is_utc_timestamp(approved):
        raise _schema("approved_at_utc must be a UTC timestamp", "approved_at_utc")
    root_identity = doc["approved_output_root_identity"]
    if not isinstance(root_identity, str) or not root_identity.startswith("/"):
        raise _schema(
            "approved_output_root_identity must be an absolute path identity",
            "approved_output_root_identity",
        )
    if len(root_identity.encode("utf-8")) > 4096 or any(
        ord(character) < 0x20 for character in root_identity
    ):
        raise BenchError(BM_UNSAFE_INPUT, "approved_output_root_identity is not a safe path")
    order = doc["permitted_campaign_order"]
    if not isinstance(order, list) or not order:
        raise _schema("permitted_campaign_order must be a non-empty array", "permitted_campaign_order")
    normalized_order = [validate_relative_member(item) for item in order]
    expected_order = _PERMITTED_CAMPAIGN_ORDERS.get(study_id)
    if expected_order is None or normalized_order != list(expected_order):
        raise _identity(
            "the authorized campaign order is not the reviewed sequence for this study",
            "permitted_campaign_order",
        )
    if require_uint(doc["measurement_retries"], "measurement_retries") != 0:
        raise _identity("measurement_retries must be 0", "measurement_retries")
    result = dict(doc)
    result["permitted_campaign_order"] = normalized_order
    bound_payload(result, "authorization")
    return result


def _is_utc_timestamp(value: str) -> bool:
    if len(value) != 20 or not value.endswith("Z"):
        return False
    if value[4] != "-" or value[7] != "-" or value[10] != "T":
        return False
    if value[13] != ":" or value[16] != ":":
        return False
    digits = value[:4] + value[5:7] + value[8:10] + value[11:13] + value[14:16] + value[17:19]
    return digits.isdigit()


def verify_g0_authorization(
    authorization_path: Path,
    independent_expected_digest: str,
    actual_input_observations: Mapping[str, Any],
) -> OfficialFreeze:
    """Verify a run-specific authorization against independently observed inputs.

    ``independent_expected_digest`` must be obtained from the reviewer's approval
    record, and ``actual_input_observations`` must be freshly observed by the
    caller. No value in this call is derived from the authorization document.
    """

    anchor = validate_digest(independent_expected_digest, "independent_expected_digest")
    if not isinstance(actual_input_observations, Mapping):
        raise _schema(
            "actual_input_observations must be a mapping", "actual_input_observations"
        )
    observed = dict(actual_input_observations)
    document = read_canonical_json(Path(authorization_path), max_bytes=MAX_AUTHORIZATION_BYTES)
    authorization = validate_authorization(document)
    digest = document_digest(authorization)
    if digest != anchor:
        raise _identity(
            "the authorization document does not match the independently approved digest",
            "independent_expected_digest",
        )
    for name in OBSERVED_IDENTITY_FIELDS:
        if name not in observed:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                f"the caller did not observe {name} independently",
                field_path=name,
            )
        if name == "source_commit":
            value = validate_source_commit(observed[name], name)
        else:
            value = validate_digest(observed[name], name)
        if authorization[name] != value:
            raise _identity(
                f"the observed {name} differs from the authorized identity",
                name,
            )
    output_root = observed.get("output_root_identity")
    if output_root is None:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the caller did not observe output_root_identity independently",
            field_path="output_root_identity",
        )
    if not isinstance(output_root, str) or os.path.normpath(output_root) != os.path.normpath(
        authorization["approved_output_root_identity"]
    ):
        raise _identity(
            "the observed output root differs from the authorized output root",
            "approved_output_root_identity",
        )
    return OfficialFreeze(
        study_id=authorization["study_id"],
        run_id=authorization["run_id"],
        design_digest=authorization["design_digest"],
        authorization_digest=digest,
        backend_protocol_digest=authorization["backend_protocol_digest"],
        source_commit=authorization["source_commit"],
        source_file_set_digest=authorization["source_file_set_digest"],
        source_tree_sha=authorization["source_tree_sha"],
        adapter_source_manifest_digest=authorization["adapter_source_manifest_digest"],
        binary_manifest_digest=authorization["binary_manifest_digest"],
        corpus_manifest_digest=authorization["corpus_manifest_digest"],
        original_reference_verifier_digest=authorization["original_reference_verifier_digest"],
        host_preflight_digest=authorization["host_preflight_digest"],
        control_schedule_digest=authorization["control_schedule_digest"],
        treatment_schedule_digest=authorization["treatment_schedule_digest"],
        qa_source_digest=authorization["qa_source_digest"],
        qa_framework_digest=authorization["qa_framework_digest"],
        operator_approval_id=authorization["operator_approval_id"],
        independent_protocol_review_id=authorization["independent_protocol_review_id"],
        approved_at_utc=authorization["approved_at_utc"],
        approved_output_root_identity=authorization["approved_output_root_identity"],
        policy_digest=authorization["policy_digest"],
        permitted_campaign_order=tuple(authorization["permitted_campaign_order"]),
        measurement_retries=authorization["measurement_retries"],
    )


def candidate_authorization_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical digest of a *candidate* authorization document.

    This is the digest an independent reviewer must approve out of band. It is
    deliberately named ``candidate_*`` so no caller can mistake it for approval.
    """

    return document_digest(validate_authorization(document))


def require_freeze(freeze: object, study_id: str | None = None) -> OfficialFreeze:
    """Return a validated freeze, optionally requiring a specific study."""

    if not isinstance(freeze, OfficialFreeze):
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "no independent G0 authorization is available for this work",
            field_path="authorization",
        )
    validate_digest(freeze.authorization_digest, "authorization_digest")
    validate_digest(freeze.design_digest, "design_digest")
    if study_id is not None and freeze.study_id != study_id:
        raise _identity("the authorization is for a different study", "study_id")
    if freeze.measurement_retries != 0:
        raise _identity("measurement_retries must be 0", "measurement_retries")
    return freeze


def template_path(study_id: str, repo_root: Path | None = None) -> Path:
    """Return the reviewed template location for a study."""

    if study_id not in TEMPLATE_FILES:
        raise _identity("unknown official study", "study_id")
    root = Path(repo_root) if repo_root is not None else repository_root()
    return root / TEMPLATE_FILES[study_id]


__all__ = [
    "AUTHORIZATION_KIND",
    "D3C_AA_WINDOWS",
    "D3C_BACKEND",
    "D3C_BASE_COMMIT",
    "D3C_CAMPAIGN_NAMES",
    "D3C_CONTROL_NAME",
    "D3C_EXPERIMENT_COMMIT",
    "D3C_INDEX_100K_COMMITTED_SENTINEL",
    "D3C_PROTOCOL_PATH",
    "D3C_PROTOCOL_RAW_SHA256",
    "DESIGN_TEMPLATE_KIND",
    "OBSERVED_IDENTITY_FIELDS",
    "OFFICIAL_STUDIES",
    "OfficialFreeze",
    "PR15D_BACKEND",
    "PR15D_ENGINES",
    "PR15D_ENGINE_PINS",
    "PR15D_SPEC_PATH",
    "PR15D_TRIAL_ORDER",
    "STUDY_CROSS_ENGINE",
    "STUDY_RETAINED_KEY",
    "TEMPLATE_FILES",
    "candidate_authorization_digest",
    "host_environment_matches",
    "read_approved_template",
    "read_canonical_json",
    "require_freeze",
    "template_path",
    "validate_authorization",
    "validate_template",
    "verify_backend_protocol",
    "verify_g0_authorization",
]
