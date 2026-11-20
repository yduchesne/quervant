"""Read-only admission of the frozen T7/F2 retained-key policy inputs.

The capability stores paths and identities, never an asserted policy outcome.
Every use reopens the micro table and F1 receipt and re-admits the raw series.
The larger micro-table budget is local to this format; official record budgets
and the frozen legacy bytes are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from ..config.identity import validate_digest
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import open_regular_beneath, require_safe_root
from .admission import AdmittedRetainedKey, VerifiedOfficialAdmission, reverify_official_admission
from .authorization import VerifiedOfficialAuthorization
from .protocols import STUDY_RETAINED_KEY

KS = (1, 10, 32, 64, 100, 128, 256, 512, 1024)
NS = (10_000, 100_000)
CLASSES = ("absent", "rare", "medium", "common")
ARMS = ("A", "L", "P", "H")
CAMPAIGNS = ("d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02")
PROTOCOL_SHA256 = "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c"
F1_COMMIT = "38a937fdf0b09f1330f26423dabb311399c8a4cf"
F1_RECEIPT_DIGEST = "sha256:80f21e8fb7c9a76d466d749b0253f50bf8955112db0214386abbfcb9a9532ee1"
EXPERIMENT_COMMIT = "3ad6c5184fbe9c011abb731415a007e3f19d21de"
POLICY_METHOD = "retained-key-t7-f2-raw-slots-v1"
BOOTSTRAP_DRAWS = 10_000
CI_LOW_INDEX = 249
CI_HIGH_INDEX = 9749
H_LIMIT_BYTES = 2_097_152
HISTORICAL_ARCHIVE_DIGESTS = {
    "d3c-v3r3-base-aa-01": "sha256:e02ff5661ecb12d76cddedfd701decdbc4004a7e6c16a40ae09a53733a409ba6",
    "d3c-v3r3-strategies-01": "sha256:721e1f543e2a8f0b9b13e2894c22676e7e400ea2568e4a2de7976c28daa2f87e",
    "d3c-v3r3-strategies-02": "sha256:72391496dd1d458ba39fb0e347f0446048878ae4180d4cb087f41e788efa3444",
}
MAX_POLICY_INPUT_BYTES = 4 * 1024 * 1024
_CREATION = object()


def _invalid(message: str, field: str = "policy_inputs") -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _read_input(path: Path) -> tuple[dict[str, Any], str]:
    """Strict bounded JSON read, hashing exactly the bytes that were parsed."""

    path = Path(path).absolute()
    root = require_safe_root(path.parent)
    with open_regular_beneath(root, path.name) as handle:
        before = os.fstat(handle.fileno())
        if before.st_nlink != 1 or before.st_size > MAX_POLICY_INPUT_BYTES:
            raise BenchError(BM_UNSAFE_INPUT, "policy input must be a bounded, unlinked regular file")
        payload = handle.read(MAX_POLICY_INPUT_BYTES + 1)
        after = os.fstat(handle.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise BenchError(BM_UNSAFE_INPUT, "policy input changed while being read")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise BenchError(BM_SCHEMA_INVALID, "policy input repeats a JSON key")
            result[key] = value
        return result

    def bad_constant(_value: str) -> None:
        raise BenchError(BM_SCHEMA_INVALID, "policy input contains a non-finite number")

    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BenchError(BM_SCHEMA_INVALID, "policy input is not bounded strict JSON") from exc
    if not isinstance(data, dict):
        raise BenchError(BM_SCHEMA_INVALID, "policy input must be an object")
    pending = [(data, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > 64 or nodes > 100_000:
            raise BenchError(BM_UNSAFE_INPUT, "policy input exceeds its local structural budget")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise BenchError(BM_SCHEMA_INVALID, "policy input contains a non-finite number")
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    # A second path read detects a replacement after the first descriptor opened.
    if sha256_regular_file(root, path.name, max_bytes=MAX_POLICY_INPUT_BYTES)[0] != digest:
        raise _invalid("policy input changed after parsing")
    return data, digest


def validate_micro_table(document: Mapping[str, Any]) -> dict[str, int]:
    """Validate the complete 5 x 9 x 4 x 5 frozen micro grid and derive H memory."""

    records = document.get("records")
    if (document.get("schema") != "pr15i-d3c-micro-v1"
            or document.get("selected_profile") != "P2"
            or document.get("source_experiment_sha") != EXPERIMENT_COMMIT
            or not isinstance(records, list) or len(records) != 900):
        raise _invalid("micro table does not match the frozen P2/source/grid contract", "micro")
    seen: set[tuple[Any, ...]] = set()
    memory: dict[str, int] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise _invalid("micro row must be an object", "micro")
        key = (record.get("variant"), record.get("k"), record.get("key_len"), record.get("trace"))
        variant, k, length, trace = key
        if (variant not in ("linear", "P0", "P1", "P2", "exact_set")
                or type(k) is not int or k not in KS
                or type(length) is not int or length not in (8, 32, 128, 1024)
                or trace not in ("miss_stable", "duplicate_retained", "churn", "evicted_revisit", "collision_distinct")
                or key in seen):
            raise _invalid("micro table has an invalid or repeated coordinate", "micro")
        seen.add(key)
        rounds = record.get("rounds")
        if (not isinstance(rounds, list) or len(rounds) != 5
                or any(type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value <= 0 for value in rounds)):
            raise _invalid("micro row must contain five finite positive rounds", "micro")
        for name in ("set_len", "set_capacity", "key_bytes"):
            if type(record.get(name)) is not int or record[name] < 0:
                raise _invalid("micro memory counters must be nonnegative integers", "micro")
        if record["set_len"] > record["set_capacity"]:
            raise _invalid("micro set length exceeds capacity", "micro")
        if variant == "exact_set":
            memory[str(k)] = max(memory.get(str(k), 0), record["set_capacity"] * 40 + record["key_bytes"])
    if len(seen) != 900 or set(memory) != {str(k) for k in KS}:
        raise _invalid("micro table is incomplete", "micro")
    return memory


def _f1_identity(receipt: Path, source_root: Path) -> tuple[str, dict[str, str]]:
    document, digest = _read_input(receipt)
    if digest != F1_RECEIPT_DIGEST:
        raise _invalid("F1 receipt differs from the frozen receipt", "f1_receipt")
    files = document.get("files")
    if (document.get("t7_commit") != F1_COMMIT or not isinstance(files, dict)
            or set(files) != {"analysis.py", "policy.py", "verify_derived.py", "freeze.py"}):
        raise _invalid("F1 receipt has an invalid source identity", "f1_receipt")
    observed = {}
    for name, expected in sorted(files.items()):
        relative = f"benchmarks/pr15i_d3_c_t7/{name}"
        actual = sha256_regular_file(source_root, relative, max_bytes=MAX_POLICY_INPUT_BYTES)[0]
        if actual != "sha256:" + str(expected):
            raise _invalid("frozen F1 source bytes differ from the authentic receipt", "f1_receipt")
        observed[relative] = actual
    # The pinned receipt already authenticates the F1 commit and its complete file
    # set. This also works in a source export without requiring a git object DB.
    return digest, observed


@dataclass(frozen=True)
class VerifiedRetainedPolicyInputs:
    """Factory-issued path bindings; decisions are always recomputed from raw slots."""

    raw_series_root_digest: str
    micro_digest: str
    f1_receipt_digest: str
    inputs_digest: str
    fixture_only: bool
    _sentinel: object = field(default=None, repr=False, compare=False)
    _admission: Any = field(default=None, repr=False, compare=False)
    _authorization: Any = field(default=None, repr=False, compare=False)
    _template: Any = field(default=None, repr=False, compare=False)
    _source_root: Path | None = field(default=None, repr=False, compare=False)
    _micro_path: Path | None = field(default=None, repr=False, compare=False)
    _f1_receipt: Path | None = field(default=None, repr=False, compare=False)
    _observed: Any = field(default=None, repr=False, compare=False)
    _fixture_record: Any = field(default=None, repr=False, compare=False)
    _fixture_micro: Any = field(default=None, repr=False, compare=False)
    scope: str = "official"
    _historical_series_root: Path | None = field(default=None, repr=False, compare=False)
    _historical_archive_root: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._sentinel is not _CREATION:
            raise BenchError(BM_UNSAFE_INPUT, "policy inputs must come from the verified factory")
        for name in ("raw_series_root_digest", "micro_digest", "f1_receipt_digest", "inputs_digest"):
            validate_digest(getattr(self, name), name)
        if self.scope not in ("official", "historical_replay"):
            raise _invalid("unknown retained policy input scope")


def _binding(raw_digest: str, micro_digest: str, f1_digest: str, sources: Mapping[str, str]) -> str:
    return content_digest({"kind": "official-retained-policy-inputs", "schema_version": 1,
                           "method": POLICY_METHOD, "protocol_sha256": PROTOCOL_SHA256,
                           "raw_series_root_digest": raw_digest, "micro_digest": micro_digest,
                           "f1_receipt_digest": f1_digest, "f1_sources": dict(sources)})


def open_retained_policy_inputs(
    *, admitted: VerifiedOfficialAdmission, authorization: VerifiedOfficialAuthorization,
    template: Mapping[str, Any], source_root: Path, micro_json: Path,
    expected_micro_sha256: str, f1_receipt: Path, observed: Mapping[str, Any] | None = None,
) -> VerifiedRetainedPolicyInputs:
    """Authenticate actual inputs; supplied PASS fields are neither needed nor read."""

    if type(admitted) is not VerifiedOfficialAdmission or type(authorization) is not VerifiedOfficialAuthorization:
        raise BenchError(BM_UNSAFE_INPUT, "policy inputs require verified admission and authorization")
    if admitted.record.fixture_only or authorization.fixture_only or template.get("study_id") != STUDY_RETAINED_KEY:
        raise BenchError(BM_UNSAFE_INPUT, "real retained policy inputs require a production retained-key admission")
    expected = validate_digest(expected_micro_sha256, "expected_micro_sha256")
    record = reverify_official_admission(admitted, authorization=authorization, template=template,
                                         source_root=source_root, observed=observed)
    if type(record) is not AdmittedRetainedKey:
        raise _invalid("policy admission is not retained-key")
    micro, micro_digest = _read_input(micro_json)
    if micro_digest != expected:
        raise _invalid("micro table differs from its pinned digest", "micro_digest")
    validate_micro_table(micro)
    f1_digest, sources = _f1_identity(f1_receipt, require_safe_root(Path(source_root)))
    return VerifiedRetainedPolicyInputs(
        record.raw_series_root_digest, micro_digest, f1_digest,
        _binding(record.raw_series_root_digest, micro_digest, f1_digest, sources), False,
        _CREATION, admitted, authorization, dict(template), Path(source_root),
        Path(micro_json).absolute(), Path(f1_receipt).absolute(), observed,
    )


def reverify_retained_policy_inputs(
    inputs: object, *, admitted: AdmittedRetainedKey | None = None, for_production: bool = True,
) -> tuple[AdmittedRetainedKey, dict[str, int]]:
    """Reopen every input and reject a relabelled, changed, or cross-series capability."""

    if type(inputs) is not VerifiedRetainedPolicyInputs or inputs._sentinel is not _CREATION:
        raise BenchError(BM_UNSAFE_INPUT, "a verified retained policy input capability is required")
    if inputs.scope == "historical_replay":
        if for_production or inputs.fixture_only:
            raise BenchError(BM_UNSAFE_INPUT, "historical policy inputs cannot authorize official production")
        if any(path is None for path in (inputs._historical_series_root, inputs._historical_archive_root, inputs._micro_path, inputs._f1_receipt)):
            raise BenchError(BM_UNSAFE_INPUT, "historical policy input paths are unavailable")
        fresh = open_historical_retained_policy_inputs(
            series_root=inputs._historical_series_root, archive_root=inputs._historical_archive_root,
            micro_json=inputs._micro_path, expected_micro_sha256=inputs.micro_digest,
            f1_receipt=inputs._f1_receipt, source_root=inputs._source_root,
        )
        if fresh != inputs:
            raise _invalid("historical policy input identities changed")
        record = fresh._fixture_record
        micro = fresh._fixture_micro
    elif inputs.fixture_only:
        if for_production or inputs._fixture_record is None or inputs._micro_path is not None:
            raise BenchError(BM_UNSAFE_INPUT, "fixture policy inputs cannot authorize production")
        record = inputs._fixture_record
        micro = inputs._fixture_micro
        actual_micro = content_digest(micro)
        expected_inputs = _binding(record.raw_series_root_digest, actual_micro, inputs.f1_receipt_digest, {})
        if actual_micro != inputs.micro_digest or expected_inputs != inputs.inputs_digest or not record.fixture_only:
            raise _invalid("fixture policy inputs changed")
    else:
        if inputs._micro_path is None or inputs._f1_receipt is None or inputs._fixture_record is not None:
            raise BenchError(BM_UNSAFE_INPUT, "production policy inputs lack reopenable provenance")
        fresh = open_retained_policy_inputs(admitted=inputs._admission, authorization=inputs._authorization,
            template=inputs._template, source_root=inputs._source_root, micro_json=inputs._micro_path,
            expected_micro_sha256=inputs.micro_digest, f1_receipt=inputs._f1_receipt, observed=inputs._observed)
        if fresh != inputs:
            raise _invalid("policy input identity changed after admission")
        record = reverify_official_admission(inputs._admission, authorization=inputs._authorization,
            template=inputs._template, source_root=inputs._source_root, observed=inputs._observed)
        micro, digest = _read_input(inputs._micro_path)
        if digest != inputs.micro_digest:
            raise _invalid("micro table changed during read")
    if type(record) is not AdmittedRetainedKey or record.raw_series_root_digest != inputs.raw_series_root_digest:
        raise _invalid("policy inputs have a different raw series")
    if admitted is not None:
        if type(admitted) is not AdmittedRetainedKey or admitted != record:
            raise _invalid("policy record differs from re-admitted raw slots", "admission")
        # Dataclass equality alone permits numeric aliases such as 12 == 12.0.
        if json.dumps(admitted.slots, sort_keys=True, separators=(",", ":")) != json.dumps(record.slots, sort_keys=True, separators=(",", ":")):
            raise _invalid("policy slot content differs from re-admitted raw slots", "admission")
    return record, validate_micro_table(micro)


def open_historical_retained_policy_inputs(
    *, series_root: Path, archive_root: Path, micro_json: Path,
    expected_micro_sha256: str, f1_receipt: Path, source_root: Path | None = None,
) -> VerifiedRetainedPolicyInputs:
    """Authenticate old raw evidence for replay without granting official G0.

    This only reads archived evidence and runs the original read-only verifier;
    it never starts a measurement process or extracts an archive.
    """

    from ..evidence.provenance import repository_root
    from .admission import (D3C_CONTROL_NAME, OriginalVerifier, hash_raw_members,
                            inventory_digest, retained_key_member_paths)
    from .historical import audit_retained_key_archive, _read_sidecar

    raw = require_safe_root(Path(series_root))
    archives = require_safe_root(Path(archive_root))
    sources_root = require_safe_root(Path(source_root) if source_root is not None else repository_root())
    expected_micro = validate_digest(expected_micro_sha256, "expected_micro_sha256")
    micro, micro_digest = _read_input(micro_json)
    if micro_digest != expected_micro:
        raise _invalid("historical micro table differs from the approved digest", "micro_digest")
    validate_micro_table(micro)
    f1_digest, sources = _f1_identity(f1_receipt, sources_root)
    protocol_digest = sha256_regular_file(sources_root, "benchmarks/pr15i_d3_c/protocol_v3r3.json", max_bytes=MAX_POLICY_INPUT_BYTES)[0]
    if protocol_digest != "sha256:" + PROTOCOL_SHA256:
        raise _invalid("historical retained protocol bytes changed", "protocol")
    verifier_relative = "benchmarks/pr15i_d3_c/verify.py"
    supplied_verifier = sha256_regular_file(sources_root, verifier_relative, max_bytes=MAX_POLICY_INPUT_BYTES)[0]
    executed_verifier = sha256_regular_file(repository_root(), verifier_relative, max_bytes=MAX_POLICY_INPUT_BYTES)[0]
    if supplied_verifier != executed_verifier:
        raise _invalid("historical verifier executable differs from the approved source root", "original_verifier")
    members = retained_key_member_paths(raw)
    before, _ = hash_raw_members(raw, members)
    declared_members = set()
    for campaign, expected_digest in HISTORICAL_ARCHIVE_DIGESTS.items():
        audit = audit_retained_key_archive(archives, campaign)
        if audit.archive_digest != expected_digest or str(audit.manifest_protocol_digest).removeprefix("sha256:") != PROTOCOL_SHA256:
            raise _invalid("historical archive differs from frozen T7/F2 identity", "archive")
        sidecar, _ = _read_sidecar(archives, f"{campaign}.tar.gz.sha256")
        for relative, expected in sidecar["members"].items():
            member = f"{campaign}/{relative}"
            declared_members.add(member)
            if sha256_regular_file(raw, member, max_bytes=256 * 1024 * 1024)[0] != "sha256:" + str(expected):
                raise _invalid("loose historical input differs from its authentic archive", "archive")
    if set(members) != declared_members:
        raise _invalid("historical loose series has an unapproved member inventory", "archive")
    outcome = OriginalVerifier().verify_retained_key_series(raw)
    report = outcome.report
    if (outcome.status != "PASS" or report.get("full_series") is not True
            or report.get("provenance_consistent") is not True
            or report.get("control") != "ACQUIRED_VERIFIED"
            or report.get("campaigns") != ["ACQUIRED_VERIFIED", "ACQUIRED_VERIFIED"]):
        raise _invalid("original retained series verifier rejected historical raw inputs", "original_verifier")
    campaigns, slots = {}, {}
    for campaign in (D3C_CONTROL_NAME, *CAMPAIGNS):
        campaigns[campaign] = _read_input(raw / campaign / "manifest.json")[0]
        count = 48 if campaign == D3C_CONTROL_NAME else 96
        slots[campaign] = tuple(_read_input(raw / campaign / "raw" / "slots" / f"slot-{index:02d}.json")[0] for index in range(1, count + 1))
    after, _ = hash_raw_members(raw, members)
    if before != after:
        raise _invalid("historical raw series changed during replay admission")
    raw_digest = inventory_digest(before)
    record = AdmittedRetainedKey(
        raw_root=raw, campaigns=campaigns, slots=slots, control_assessment={}, inventory=tuple(before),
        raw_series_root_digest=raw_digest, comparability_digest=raw_digest,
        admission_index={"qualification_scope": "historical_replay"}, original_verifier=dict(report),
        fixture_only=True,
    )
    return VerifiedRetainedPolicyInputs(
        raw_digest, micro_digest, f1_digest, _binding(raw_digest, micro_digest, f1_digest, sources), False,
        _CREATION, _source_root=sources_root, _micro_path=Path(micro_json).absolute(),
        _f1_receipt=Path(f1_receipt).absolute(), _fixture_record=record, _fixture_micro=micro,
        scope="historical_replay", _historical_series_root=raw, _historical_archive_root=archives,
    )


def _open_fixture_retained_policy_inputs(
    *, admitted: AdmittedRetainedKey, micro: Mapping[str, Any],
) -> VerifiedRetainedPolicyInputs:
    """Private deterministic test seam; never usable by production gates."""

    import copy
    if type(admitted) is not AdmittedRetainedKey or admitted.fixture_only is not True:
        raise BenchError(BM_UNSAFE_INPUT, "fixture policy inputs require a fixture admission")
    validate_micro_table(micro)
    micro_copy = copy.deepcopy(dict(micro))
    digest = content_digest(micro_copy)
    return VerifiedRetainedPolicyInputs(
        admitted.raw_series_root_digest, digest, F1_RECEIPT_DIGEST,
        _binding(admitted.raw_series_root_digest, digest, F1_RECEIPT_DIGEST, {}), True,
        _CREATION, _fixture_record=copy.deepcopy(admitted), _fixture_micro=micro_copy,
    )
