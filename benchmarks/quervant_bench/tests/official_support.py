"""Deterministic, test-only builders for the official qualification facade.

Every document produced here is structurally complete but is **never** real
evidence: it is created in a temporary directory from literal sample values, with a
test-only verifier stub and a test-only freeze. Production G0 cannot accept any of
it because the authorization/approval artefacts do not exist.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
)
from quervant_bench.qualification.identity import compute_source_set_digest
from quervant_bench.evidence.provenance import repository_root
from quervant_bench.official import admission
from quervant_bench.official import protocols
from quervant_bench.official.controls import assess_cross_engine_control
from quervant_bench.official.protocols import OfficialFreeze

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Reviewed design-template digests (independently pinned literals).
RETAINED_KEY_TEMPLATE_DIGEST = (
    "sha256:8d7feea828934307953011378a15e7afaef07dcb64a7699f74f3e546e7f8ae4f"
)
CROSS_ENGINE_TEMPLATE_DIGEST = (
    "sha256:79acac9b4273dffd6dd196f35335cc667a427a98f4786a8fb0b21a46bb3cb3b3"
)
FIXTURE_ONLY = {"fixture_only": True}

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def oracle_module() -> Any:
    return admission.load_pr15d_oracle()


def write_json(path: Path, document: Mapping[str, Any]) -> str:
    """Write one canonical document and return its content digest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_document_bytes(dict(document))
    path.write_bytes(payload)
    return content_digest(dict(document))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_corpus(root: Path) -> dict[str, Any]:
    """Write the frozen 10K/100K corpus and its manifest beneath ``root``."""

    oracle = oracle_module()
    root.mkdir(parents=True, exist_ok=True)
    for n in (10_000, 100_000):
        (root / oracle.corpus_filename(n)).write_text(oracle.build_tsv_text(n), encoding="utf-8")
    manifest = oracle.build_manifest(str(root))
    write_json(root / oracle.manifest_filename(), manifest)
    manifest_sha = oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))
    digests = {str(entry["n"]): entry["sha256"] for entry in manifest["corpora"]}
    _manifest, rows_by_n = oracle.load_and_verify(str(root))
    return {
        "dir": root,
        "manifest": manifest,
        "manifest_sha": manifest_sha,
        "digests": digests,
        "rows_by_n": rows_by_n,
    }


def sample_vector(base: int) -> list[int]:
    """Return twenty positive samples with a small deterministic spread."""

    return [base + (index % 5) for index in range(20)]


def summary(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "median": ordered[9],
        "p95": ordered[18],
        "p99": ordered[18],
        "min": ordered[0],
        "max": ordered[-1],
    }


def cross_engine_lane_descriptors() -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for n in admission.PR15D_N_VALUES:
        for class_name in admission.PR15D_CLASSES:
            field, term = admission.pr15d_lane_field(class_name)
            for k in admission.PR15D_K_VALUES:
                for regime in admission.PR15D_REGIMES:
                    lanes.append(
                        {
                            "id": admission.pr15d_lane_id(n, class_name, k),
                            "n": n,
                            "class": class_name,
                            "field": field,
                            "term": term,
                            "k": k,
                            "regime": regime,
                        }
                    )
    return lanes


def cross_engine_lane_base(engine: str, descriptor: Mapping[str, Any]) -> int:
    """Return the fixture's per-engine base latency for one descriptor."""

    base = {"quervant": 1_000, "tantivy": 1_100, "lucene": 1_050}[engine]
    size_factor = 2 if descriptor["n"] == 100_000 else 1
    regime_factor = 3 if descriptor["regime"] == "process_cold" else 1
    return base * size_factor * regime_factor + descriptor["k"]


def make_cross_engine_trial(
    *,
    engine: str,
    trial: int,
    corpus: Mapping[str, Any],
    freeze: OfficialFreeze,
    source_sha: str | None = None,
) -> dict[str, Any]:
    oracle = oracle_module()
    lanes: list[dict[str, Any]] = []
    for descriptor in cross_engine_lane_descriptors():
        expected = oracle.expected(
            corpus["rows_by_n"][descriptor["n"]],
            descriptor["field"],
            descriptor["term"],
            descriptor["k"],
        )
        samples = sample_vector(
            cross_engine_lane_base(engine, descriptor) + trial - 1
        )
        warm = descriptor["regime"] == "warm"
        lanes.append(
            {
                "id": descriptor["id"],
                "n": descriptor["n"],
                "class": descriptor["class"],
                "field": descriptor["field"],
                "term": descriptor["term"],
                "k": descriptor["k"],
                "regime": descriptor["regime"],
                "warmups": 5 if warm else 0,
                "warmup_ids": (
                    [
                        f"{descriptor['id']}:warmup:{index}"
                        for index in range(5)
                    ]
                    if warm
                    else []
                ),
                "samples_ns": samples,
                "summary_ns": summary(samples),
                "total_hits": expected["total_hits"],
                "doc_ids": expected["doc_ids"],
                "expected_total_hits": expected["total_hits"],
                "expected_doc_ids": expected["doc_ids"],
                "oracle_ok": True,
                "analyzer": "keyword-exact",
                "contention": {"pre": "clear", "post": "clear"},
                "rss_peak_bytes": None,
                "cpu_ns": None,
                "allocations": "NOT_MEASURED",
            }
        )
    builds = {
        str(n): {
            "documents_indexed": n,
            "documents_verified": n,
            "index_ns": 1_000 + n,
            "commit_ns": 500,
            "reopen_ns": 250,
            "index_bytes": 4_096 + n,
            "segment_count": 1,
        }
        for n in admission.PR15D_N_VALUES
    }
    throughput = [
        {
            "n": n,
            "requests": 100,
            "answered": 100,
            "wall_ns": 100_000_000,
            "serial_ops_per_second": round(100 * 1_000_000_000 / 100_000_000, 6),
        }
        for n in admission.PR15D_N_VALUES
    ]
    return {
        "schema": "pr15d-trial-v1",
        "trial": trial,
        "engine": engine,
        "engine_version": protocols.PR15D_ENGINE_PINS[engine]
        if protocols.PR15D_ENGINE_PINS[engine] != "workspace"
        else "quervant-0.1.0",
        "adapter_version": "1",
        "source_sha": source_sha or freeze.source_commit,
        "release_build": True,
        "host_fingerprint": "fixture-host-fingerprint",
        "filesystem": "ext4",
        "native_filesystem": True,
        "operator_idle_attested": True,
        "corpus_manifest_sha256": corpus["manifest_sha"],
        "corpus_digests": dict(corpus["digests"]),
        "analyzer_map": {"doc_id": "keyword-exact", "key": "keyword-exact", "group": "keyword-exact"},
        "build": builds,
        "lanes": lanes,
        "throughput": throughput,
        "contention": [{"phase": "pre", "n": 10_000, "state": "clear"}],
        "status": "ok",
        "qualified": True,
        "unqualified_reasons": [],
        "scored_lane": {
            "status": "SEMANTICALLY_NONCOMPARABLE",
            "reason": "fixture",
        },
    }


def make_cross_engine_run(
    *, corpus: Mapping[str, Any], freeze: OfficialFreeze
) -> dict[str, Any]:
    adapters = {
        engine: {
            "present": True,
            "engine_version": protocols.PR15D_ENGINE_PINS[engine]
            if protocols.PR15D_ENGINE_PINS[engine] != "workspace"
            else "quervant-0.1.0",
            "adapter_version": "1",
        }
        for engine in admission.PR15D_ENGINES
    }
    return {
        "schema": "pr15d-run-v1",
        "run_id": "fixture-run",
        "source_sha": freeze.source_commit,
        "workload": "pr15d_v1",
        "corpus_dir": str(corpus["dir"]),
        "corpus_manifest_sha256": corpus["manifest_sha"],
        "corpus_digests": dict(corpus["digests"]),
        "environment": {"filesystem": "ext4"},
        "host_fingerprint": "fixture-host-fingerprint",
        "adapters": adapters,
        "adapter_metadata": adapters,
        "idle_attested": True,
        "native_filesystem": True,
        "filesystem": "ext4",
        "trials": 3,
        "status": "complete",
        "qualified": True,
        "blockers": [],
        "scored_lane": {"status": "SEMANTICALLY_NONCOMPARABLE", "reason": "fixture"},
    }


def make_control_slots(prefix: str = "warm") -> list[dict[str, Any]]:
    """Return 48 deterministic Quervant/Quervant control slots (ratio 1.0)."""

    template, _ = protocols.read_approved_template(
        protocols.template_path(protocols.STUDY_CROSS_ENGINE, REPO_ROOT),
        CROSS_ENGINE_TEMPLATE_DIGEST,
    )
    order = template["schedule"]["control_order"]
    lane_ids = admission.pr15d_warm_lane_ids()
    slots: list[dict[str, Any]] = []
    for block, row in enumerate(order, start=1):
        for position, arm in enumerate(row, start=1):
            slots.append(
                {
                    "slot": (block - 1) * 4 + position,
                    "block": block,
                    "position": position,
                    "arm": arm,
                    "lanes": [
                        {"lane_id": lane_id, "samples_ns": sample_vector(1_000 + index)}
                        for index, lane_id in enumerate(lane_ids)
                    ],
                }
            )
    return slots


def make_cross_engine_control() -> dict[str, Any]:
    return assess_cross_engine_control(
        slots=make_control_slots(), warm_lane_ids=admission.pr15d_warm_lane_ids()
    )


def qa_evidence(gate: str, freeze: OfficialFreeze) -> dict[str, Any]:
    """Build a structurally complete test-only QA evidence document."""

    from quervant_bench.official import contracts as official_contracts
    from quervant_bench.official.coordinator import qa_roster_digest

    if gate == "framework-qa":
        roster = official_contracts.FRAMEWORK_QA_ROSTER
        kind = official_contracts.FRAMEWORK_QA_KIND
        toolchain = official_contracts.FRAMEWORK_TOOLCHAIN_ID
    else:
        roster = official_contracts.SOURCE_QA_ROSTER
        kind = official_contracts.SOURCE_QA_KIND
        toolchain = official_contracts.SOURCE_TOOLCHAIN_ID
    checks = [
        {
            "check_id": check_id,
            "executed": True,
            "status": "pass",
            "failed": 0,
            "mandatory_skipped": 0,
            "evidence_digest": content_digest(
                {"kind": "fixture-qa-check", "check_id": check_id}
            ),
        }
        for check_id in roster
    ]
    return {
        "kind": kind,
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "qa_gate": gate,
        "qa_roster_digest": qa_roster_digest(),
        "source_set_digest": freeze.source_file_set_digest,
        "toolchain_id": toolchain,
        "checks": checks,
    }


def parity_row(row_id: str = "fixture-row") -> dict[str, Any]:
    """Return one test-only passing parity row."""

    return {
        "row_id": row_id,
        "legacy_source_identity": "fixture-legacy-source",
        "legacy_verifier_version": "fixture-v1",
        "original_result": "executed",
        "comparison_scope": "fixture",
        "expected_equivalence": "EXACT",
        "computed_comparison": "equal",
        "approved_tolerance": "NONE",
        "reviewer_approval_id": "fixture-reviewer",
        "status": "PASS",
    }


def approved_archive(root: Path) -> tuple[Path, dict[str, str]]:
    """Create a test-only archive directory and its reviewer-approved digests."""

    from quervant_bench.evidence.hashing import sha256_regular_file

    root.mkdir(parents=True, exist_ok=True)
    (root / "run.json").write_text('{"fixture_only":true}', encoding="utf-8")
    (root / "notes.txt").write_text("fixture", encoding="utf-8")
    expected = {
        name: sha256_regular_file(root, name, max_bytes=1024)[0]
        for name in ("run.json", "notes.txt")
    }
    return root, expected


def legacy_manifest() -> dict[str, Any]:
    return read_json(REPO_ROOT / "docs/pr-artifacts/bm-09/legacy-source-manifest.json")


def cross_engine_parity(root: Path) -> dict[str, Any]:
    """Return a test-only passing cross-engine parity assessment."""

    from quervant_bench.official import historical

    archive, expected = approved_archive(root / "archive")
    return historical.assess_required_historical_parity(
        study_id="cross-engine-keyword-real-v1",
        archive_root=archive,
        cross_engine_expected=expected,
        reviewer_approval_id="fixture-reviewer",
        mapping_status="NON_EQUIVALENT_CONTRACT",
        rows=[parity_row()],
        legacy_manifest=legacy_manifest(),
    )


@dataclass(frozen=True)
class CrossEngineFixture:
    raw_root: Path
    corpus_root: Path
    freeze: OfficialFreeze
    template: Mapping[str, Any]
    control: Mapping[str, Any]
    run_json: Mapping[str, Any]
    framework_qa: Mapping[str, Any] | None = None
    source_qa: Mapping[str, Any] | None = None
    qa_evidence_root: Path | None = None


def verifier_digest(relative: str) -> str:
    """Return the real SHA-256 of one original verifier source file."""

    from quervant_bench.evidence.hashing import sha256_regular_file

    digest, _length = sha256_regular_file(
        REPO_ROOT, relative, max_bytes=64 * 1024 * 1024
    )
    return digest


def make_freeze(
    *,
    study_id: str,
    corpus_manifest_digest: str = DIGEST_C,
    design_digest: str | None = None,
    original_verifier_digest: str = DIGEST_C,
    qa_framework_digest: str = DIGEST_A,
    qa_source_digest: str = DIGEST_B,
    source_file_set_digest: str = DIGEST_B,
    run_id: str = "11111111-1111-4111-8111-111111111111",
) -> OfficialFreeze:
    """Build a test-only freeze (not an independent approval)."""

    template, digest = protocols.read_approved_template(
        protocols.template_path(study_id, REPO_ROOT),
        (
            CROSS_ENGINE_TEMPLATE_DIGEST
            if study_id == protocols.STUDY_CROSS_ENGINE
            else RETAINED_KEY_TEMPLATE_DIGEST
        ),
    )
    return OfficialFreeze(
        study_id=study_id,
        run_id=run_id,
        design_digest=design_digest or digest,
        authorization_digest=DIGEST_A,
        backend_protocol_digest=template["backend_protocol_identity"]["raw_sha256"],
        source_commit=template["source_requirements"].get("base_commit")
        or ("a" * 40),
        source_file_set_digest=source_file_set_digest,
        source_tree_sha=DIGEST_C,
        adapter_source_manifest_digest=DIGEST_A,
        binary_manifest_digest=DIGEST_B,
        corpus_manifest_digest=corpus_manifest_digest,
        original_reference_verifier_digest=original_verifier_digest,
        host_preflight_digest=DIGEST_A,
        control_schedule_digest=DIGEST_B,
        treatment_schedule_digest=DIGEST_C,
        qa_source_digest=qa_source_digest,
        qa_framework_digest=qa_framework_digest,
        operator_approval_id="fixture-operator-approval",
        independent_protocol_review_id="fixture-independent-review",
        approved_at_utc="2026-01-01T00:00:00Z",
        approved_output_root_identity="/tmp/approved-official-root",
        policy_digest=DIGEST_C,
        permitted_campaign_order=(
            ("control", "treatment")
            if study_id == protocols.STUDY_CROSS_ENGINE
            else (
                "d3c-v3r3-base-aa-01",
                "d3c-v3r3-strategies-01",
                "d3c-v3r3-strategies-02",
            )
        ),
        measurement_retries=0,
    )


def make_cross_engine_fixture(
    root: Path, *, run_id: str = "11111111-1111-4111-8111-111111111111"
) -> CrossEngineFixture:
    corpus = make_corpus(root / "corpus")
    qa = qa_evidence_sandbox(root / "qa-evidence")
    base_freeze = dataclasses.replace(
        qa.freeze,
        corpus_manifest_digest="sha256:" + corpus["manifest_sha"],
        original_reference_verifier_digest=verifier_digest(
            "benchmarks/pr15d/harness/validate.py"
        ),
        run_id=run_id,
    )
    freeze = base_freeze
    framework_qa = qa.framework_summary
    source_qa = qa.source_summary
    template, _digest = protocols.read_approved_template(
        protocols.template_path(protocols.STUDY_CROSS_ENGINE, REPO_ROOT),
        CROSS_ENGINE_TEMPLATE_DIGEST,
    )
    raw = root / "raw"
    write_json(raw / "backend" / "run.json", make_cross_engine_run(corpus=corpus, freeze=freeze))
    for trial in range(1, 4):
        for engine in admission.PR15D_TRIAL_ORDER[trial]:
            write_json(
                raw / "backend" / "trials" / f"trial-{trial}" / f"{engine}.json",
                make_cross_engine_trial(
                    engine=engine, trial=trial, corpus=corpus, freeze=freeze
                ),
            )
    write_json(
        raw / "backend" / "validation.json",
        {"schema": "pr15d-validation-v1", "status": "QUALIFIED", "errors": [], "unqualified": []},
    )
    control = make_cross_engine_control()
    write_json(raw / "control" / "control.json", control)
    return CrossEngineFixture(
        raw_root=raw,
        corpus_root=corpus["dir"],
        freeze=freeze,
        template=template,
        control=control,
        run_json=make_cross_engine_run(corpus=corpus, freeze=freeze),
        framework_qa=framework_qa,
        source_qa=source_qa,
        qa_evidence_root=qa.root,
    )


class StubVerifier:
    """Test-only original-verifier gateway with a configurable status."""

    def __init__(self, campaign_status: str = "ACQUIRED_VERIFIED", series_status: str = "PASS"):
        self.campaign_status = campaign_status
        self.series_status = series_status
        self.calls: list[str] = []

    def verify_cross_engine(self, run_root: Path, *, corpus_dir: Path | None = None) -> Any:
        from quervant_bench.official.admission import OriginalVerifierOutcome

        self.calls.append("cross-engine")
        return OriginalVerifierOutcome(status="QUALIFIED", detail="stub", report={})

    def verify_retained_key_campaign(self, campaign_dir: Path) -> Any:
        from quervant_bench.official.admission import OriginalVerifierOutcome

        self.calls.append(str(campaign_dir.name))
        return OriginalVerifierOutcome(
            status=self.campaign_status, detail="stub", report={}
        )

    def verify_retained_key_series(self, series_root: Path) -> Any:
        from quervant_bench.official.admission import OriginalVerifierOutcome

        self.calls.append("series")
        return OriginalVerifierOutcome(status=self.series_status, detail="stub", report={})


# ---------------------------------------------------------------------------
# Retained-key fixture
# ---------------------------------------------------------------------------


def retained_key_lane_records(
    *, arm: str, unit_ns: int
) -> list[dict[str, Any]]:
    marker = admission.D3C_MODE_MARKERS[arm]
    records: list[dict[str, Any]] = []
    for lane in admission.d3c_lane_keys():
        expected = admission.retained_key_oracle(lane["n"], lane["class"], lane["k"])
        samples = sample_vector(unit_ns)
        records.append(
            {
                "id": lane["lane_id"],
                "total_hits": expected["total_hits"],
                "doc_ids": expected["doc_ids"],
                "samples_ns": samples,
                "summary_ns": summary(samples),
                "mode_marker": marker,
                "adapter_pid": 4_242,
                "affinity_before": [1],
                "affinity_after": [1],
            }
        )
    return records


def retained_key_orders(template: Mapping[str, Any], campaign: str) -> list[list[str]]:
    if campaign == admission.D3C_CONTROL_NAME:
        return template["schedule"]["control_order"]
    if campaign == admission.D3C_CAMPAIGN_NAMES[0]:
        return template["schedule"]["campaign_01_order"]
    return template["schedule"]["campaign_02_order"]


def make_retained_key_campaign(
    *,
    root: Path,
    campaign: str,
    template: Mapping[str, Any],
    base_commit: str,
    experiment_commit: str,
    sentinel: int,
) -> dict[str, Any]:
    kind = "control" if campaign == admission.D3C_CONTROL_NAME else "four_arm"
    arm_names = ("A", "B") if kind == "control" else ("A", "L", "P", "H")
    base_binary = "a" * 64
    experiment_binary = base_binary if kind == "control" else "b" * 64
    arms = {}
    for arm in arm_names:
        arms[arm] = {
            "source_sha": base_commit if arm in ("A", "B") else experiment_commit,
            "binary_sha256": experiment_binary if arm in ("L", "P", "H") else base_binary,
            "binary_bytes": 1_024,
            "indexes": {
                str(n): {
                    "bytes": sentinel if n == 100_000 else 1_000,
                    "digest": "sha256:" + f"{n:064d}",
                }
                for n in admission.D3C_N_VALUES
            },
        }
    manifest = {
        "schema": "pr15i-d3c-manifest-v1",
        "kind": kind,
        "campaign": campaign,
        "protocol_sha256": protocols.D3C_PROTOCOL_RAW_SHA256.replace("sha256:", ""),
        "source_base_sha": base_commit,
        "source_experiment_sha": None if kind == "control" else experiment_commit,
        "arms": arms,
        "host_fingerprint": "fixture-d3c-host",
    }
    write_json(root / "manifest.json", manifest)
    write_json(
        root / "authorization.json",
        {
            "schema": "pr15i-d3c-authorization-v1",
            "protocol_sha256": protocols.D3C_PROTOCOL_RAW_SHA256.replace("sha256:", ""),
            "rehearsal_only": False,
        },
    )
    write_json(
        root / "raw" / "host-attestation.json",
        {"schema": "pr15i-d3c-host-v1", "host_fingerprint": "fixture-d3c-host"},
    )
    write_json(
        root / "raw" / "host-readiness.json",
        {
            "schema": "official-host-readiness-v1",
            "study_id": protocols.STUDY_RETAINED_KEY,
            "host_fingerprint": DIGEST_A,
            "adapter_cpu": 1,
            "controller_cpu": 2,
            "environment": "native-linux",
            "limits": {
                "min_interval_ms": 800,
                "max_interval_ms": 1500,
                "max_busy_permille": 250,
                "max_median_busy_permille": 100,
                "max_steal_permille": 20,
                "min_intervals": 6,
            },
            "observations": [
                {
                    "elapsed_ms": 1_000,
                    "ticks": {"1": [0, 0, 0, 100, 0, 0, 0, 0], "2": [0, 0, 0, 100, 0, 0, 0, 0]},
                    "adapter_busy_permille": 10,
                    "adapter_steal_permille": 0,
                    "controller_busy_permille": 10,
                    "controller_steal_permille": 0,
                }
            ],
            "status": "READY",
            "reasons": [],
        },
    )
    write_json(
        root / "raw" / "build-provenance.json",
        {"schema": "pr15i-d3c-build-provenance-v1"},
    )
    orders = retained_key_orders(template, campaign)
    slot_number = 0
    for block, row in enumerate(orders, start=1):
        for position, arm in enumerate(row, start=1):
            slot_number += 1
            slot = {
                "schema": "pr15i-d3c-slot-v1",
                "slot": slot_number,
                "block": block,
                "position": position,
                "arm": arm,
                "source_sha": arms[arm]["source_sha"],
                "binary_sha256": arms[arm]["binary_sha256"],
                "index_digests": {
                    str(n): arms[arm]["indexes"][str(n)]["digest"]
                    for n in admission.D3C_N_VALUES
                },
                "contention_before": {"state": "clear", "reason_codes": []},
                "contention_after": {"state": "clear", "reason_codes": []},
                "controller_affinity_before": [2],
                "controller_affinity_after": [2],
                "lanes": retained_key_lane_records(arm=arm, unit_ns=1_000),
            }
            write_json(root / "raw" / "slots" / f"slot-{slot_number:02d}.json", slot)
    summary_document = {
        "schema": "pr15i-d3c-summary-v1",
        "campaign": campaign,
        "kind": kind,
        "a_a": {"passes": True},
    }
    write_json(root / "sanitized" / "summary.json", summary_document)
    write_json(
        root / "verification.json",
        {
            "schema": "pr15i-d3c-verification-v1",
            "campaign": campaign,
            "verification": "PASS",
            "measurement_status": "ACQUIRED_VERIFIED",
        },
    )
    sealed = sorted(
        admission.walk_raw_members(
            root, exclude_any_dir=("build", "indexes", "corpus", "compile-source")
        )
    )
    seal_files = {
        relative: admission.sha256_regular_file(
            root, relative, max_bytes=admission.MAX_RAW_MEMBER_BYTES
        )[0].replace("sha256:", "", 1)
        for relative in sealed
        if relative not in ("raw/seal.json", "verification.json")
    }
    write_json(root / "raw" / "seal.json", {"files": seal_files})
    return manifest


@dataclass(frozen=True)
class RetainedKeyFixture:
    raw_root: Path
    freeze: OfficialFreeze
    template: Mapping[str, Any]
    control_assessment: Mapping[str, Any]
    framework_qa: Mapping[str, Any] | None = None
    source_qa: Mapping[str, Any] | None = None
    qa_evidence_root: Path | None = None


def make_retained_key_fixture(
    root: Path, *, run_id: str = "22222222-2222-4222-8222-222222222222"
) -> RetainedKeyFixture:
    template, digest = protocols.read_approved_template(
        protocols.template_path(protocols.STUDY_RETAINED_KEY, REPO_ROOT),
        RETAINED_KEY_TEMPLATE_DIGEST,
    )
    qa = qa_evidence_sandbox(root / "qa-evidence", study_id=protocols.STUDY_RETAINED_KEY)
    base_freeze = dataclasses.replace(
        qa.freeze,
        original_reference_verifier_digest=verifier_digest(
            "benchmarks/pr15i_d3_c/verify.py"
        ),
        run_id=run_id,
    )
    freeze = base_freeze
    framework_qa = qa.framework_summary
    source_qa = qa.source_summary
    raw = root / "raw"
    base_commit = template["source_requirements"]["base_commit"]
    experiment_commit = template["source_requirements"]["experiment_commit"]
    sentinel = template["source_requirements"]["index_100k_committed_sentinel"]
    for campaign in (admission.D3C_CONTROL_NAME, *admission.D3C_CAMPAIGN_NAMES):
        make_retained_key_campaign(
            root=raw / campaign,
            campaign=campaign,
            template=template,
            base_commit=base_commit,
            experiment_commit=experiment_commit,
            sentinel=sentinel,
        )
    from quervant_bench.official.controls import assess_retained_key_control

    control_slots = [
        read_json(raw / admission.D3C_CONTROL_NAME / "raw" / "slots" / f"slot-{index:02d}.json")
        for index in range(1, 49)
    ]
    assessment = assess_retained_key_control(
        slots=control_slots,
        lane_ids=admission.d3c_lane_ids(),
        windows=template["controls"]["windows"],
    )
    return RetainedKeyFixture(
        raw_root=raw,
        freeze=freeze,
        template=template,
        control_assessment=assessment,
        framework_qa=framework_qa,
        source_qa=source_qa,
        qa_evidence_root=qa.root,
    )


# ---------------------------------------------------------------------------
# QA pinning, fixture trust seams and TEST-ONLY external-approval simulation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QaEvidenceSandbox:
    """TEST-ONLY executed QA evidence root with 33 records and 33 logs."""

    root: Path
    freeze: OfficialFreeze
    framework_summary: Mapping[str, Any]
    source_summary: Mapping[str, Any]
    raw_root: Path


def qa_evidence_sandbox(
    root: Path,
    *,
    study_id: str = "cross-engine-keyword-real-v1",
    source_commit: str = "a" * 40,
) -> QaEvidenceSandbox:
    """Write a complete TEST-ONLY executed-QA artifact tree and pinned summaries.

    The bytes are generated fixtures (not CI evidence), but the *shape* is the real
    production contract: canonical per-check records, real log files, the frozen
    job map and G0-pinned summary digests.
    """

    from quervant_bench.official import contracts as official_contracts
    from quervant_bench.official import qa_evidence as official_qa

    source_set = compute_source_set_digest(REPO_ROOT)
    seed = make_freeze(
        study_id=study_id,
        source_file_set_digest=source_set,
        original_verifier_digest=verifier_digest(
            "benchmarks/pr15d/harness/validate.py"
        ),
        run_id="11111111-1111-4111-8111-111111111111",
    )
    seed = dataclasses.replace(seed, source_commit=source_commit)
    summaries: dict[str, dict[str, Any]] = {}
    for gate, roster, kind, toolchain in (
        (
            "framework-qa",
            official_contracts.FRAMEWORK_QA_ROSTER,
            official_contracts.FRAMEWORK_QA_KIND,
            official_contracts.FRAMEWORK_TOOLCHAIN_ID,
        ),
        (
            "source-qa",
            official_contracts.SOURCE_QA_ROSTER,
            official_contracts.SOURCE_QA_KIND,
            official_contracts.SOURCE_TOOLCHAIN_ID,
        ),
    ):
        checks: list[dict[str, Any]] = []
        for check_id in roster:
            executor, job_name = official_qa.GATE_CHECK_EXECUTORS[(gate, check_id)]
            reference = (
                "https://github.com/yduchesne/quervant/actions/runs/424242"
                if executor == "hosted-ci"
                else "operator-attested-run"
            )
            log_relative = official_qa.check_log_relative(gate, check_id)
            log_bytes = (
                f"TEST ONLY {gate} {check_id} executed by {executor}/{job_name}\n".encode()
            )
            log_path = root / log_relative
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_bytes(log_bytes)
            record = {
                "kind": official_qa.EXECUTED_CHECK_KIND,
                "schema_version": 1,
                "evidence_origin": "real",
                "qualification_scope": "official",
                "qa_gate": gate,
                "check_id": check_id,
                "source_commit": source_commit,
                "source_set_digest": source_set,
                "toolchain_id": toolchain,
                "executor": executor,
                "execution_reference": reference,
                "job_name": job_name,
                "executed": True,
                "status": "pass",
                "failed": 0,
                "mandatory_skipped": 0,
                "command_exit_code": 0,
                "log_path": log_relative,
                "log_raw_sha256": "sha256:" + hashlib.sha256(log_bytes).hexdigest(),
            }
            record_digest = write_json(
                root / official_qa.check_record_relative(gate, check_id), record
            )
            checks.append(
                {
                    "check_id": check_id,
                    "executed": True,
                    "status": "pass",
                    "failed": 0,
                    "mandatory_skipped": 0,
                    "evidence_digest": record_digest,
                }
            )
        summaries[gate] = {
            "kind": kind,
            "schema_version": 1,
            "evidence_origin": "real",
            "qualification_scope": "official",
            "qa_gate": gate,
            "qa_roster_digest": content_digest(
                {
                    "kind": "official-qa-roster",
                    "schema_version": 1,
                    "framework": list(official_contracts.FRAMEWORK_QA_ROSTER),
                    "source": list(official_contracts.SOURCE_QA_ROSTER),
                }
            ),
            "source_set_digest": source_set,
            "toolchain_id": toolchain,
            "checks": checks,
        }
    freeze = dataclasses.replace(
        seed,
        qa_framework_digest=content_digest(summaries["framework-qa"]),
        qa_source_digest=content_digest(summaries["source-qa"]),
        source_file_set_digest=source_set,
    )
    return QaEvidenceSandbox(
        root=root,
        freeze=freeze,
        framework_summary=summaries["framework-qa"],
        source_summary=summaries["source-qa"],
        raw_root=root.parent / "raw",
    )


def authorization_document(freeze: OfficialFreeze) -> dict[str, Any]:
    """Build the closed authorization document matching a fixture freeze."""

    return {
        "kind": protocols.AUTHORIZATION_KIND,
        "schema_version": 1,
        "study_id": freeze.study_id,
        "run_id": freeze.run_id,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "design_digest": freeze.design_digest,
        "backend_protocol_digest": freeze.backend_protocol_digest,
        "source_commit": freeze.source_commit,
        "source_file_set_digest": freeze.source_file_set_digest,
        "source_tree_sha": freeze.source_tree_sha,
        "adapter_source_manifest_digest": freeze.adapter_source_manifest_digest,
        "binary_manifest_digest": freeze.binary_manifest_digest,
        "corpus_manifest_digest": freeze.corpus_manifest_digest,
        "original_reference_verifier_digest": freeze.original_reference_verifier_digest,
        "host_preflight_digest": freeze.host_preflight_digest,
        "control_schedule_digest": freeze.control_schedule_digest,
        "treatment_schedule_digest": freeze.treatment_schedule_digest,
        "qa_source_digest": freeze.qa_source_digest,
        "qa_framework_digest": freeze.qa_framework_digest,
        "operator_approval_id": freeze.operator_approval_id,
        "independent_protocol_review_id": freeze.independent_protocol_review_id,
        "approved_at_utc": freeze.approved_at_utc,
        "approved_output_root_identity": freeze.approved_output_root_identity,
        "policy_digest": freeze.policy_digest,
        "permitted_campaign_order": list(freeze.permitted_campaign_order),
        "measurement_retries": 0,
    }


def authorization_observations(freeze: OfficialFreeze) -> dict[str, Any]:
    """Return the observed identity map matching a fixture authorization."""

    document = authorization_document(freeze)
    observations = {
        name: document[name] for name in protocols.OBSERVED_IDENTITY_FIELDS
    }
    observations["output_root_identity"] = document["approved_output_root_identity"]
    return observations


def production_shaped_authorization(freeze: OfficialFreeze, *, sandbox: Path):
    """Build a TEST-ONLY external-approval simulation for the production boundary.

    The authorization and its approval record live in a temporary sandbox outside
    the repository, so this exercises the real
    ``open_verified_official_authorization`` path without any real authorization.
    """

    from quervant_bench.official import authorization as official_authorization

    authorization_root = sandbox / "authorization"
    approval_root = sandbox / "approvals"
    authorization_root.mkdir(parents=True, exist_ok=True)
    approval_root.mkdir(parents=True, exist_ok=True)
    document = authorization_document(freeze)
    path = authorization_root / "authorization.v1.json"
    path.write_bytes(canonical_document_bytes(document))
    digest = content_digest(document)
    write_json(
        official_authorization.approval_record_path(approval_root, "test-only-approval"),
        {
            "kind": official_authorization.APPROVAL_RECORD_KIND,
            "schema_version": 1,
            "study_id": freeze.study_id,
            "approved_authorization_digest": digest,
            "independent_review_id": "test-only-review",
            "approved_at_utc": "2026-01-01T00:00:00Z",
        },
    )
    return official_authorization.open_verified_official_authorization(
        authorization_path=path,
        independently_approved_digest=digest,
        actual_observations=authorization_observations(freeze),
        approval_source_identity="test-only-approval",
        approval_source_root=approval_root,
    )


def fixture_authorization(
    study_id: str = "cross-engine-keyword-real-v1",
    *,
    freeze: OfficialFreeze | None = None,
    original_verifier_digest: str | None = None,
):
    """Return a fixture-only verified-authorization capability for tests."""

    from quervant_bench.official import authorization as official_authorization

    active = freeze or make_freeze(
        study_id=study_id,
        original_verifier_digest=original_verifier_digest or DIGEST_C,
    )
    return official_authorization._open_fixture_authorization(active)


def _admit_fixture_cross_engine_with_verifier(
    *,
    raw_root: Path,
    authorization,
    template: Mapping[str, Any],
    corpus_dir: Path,
    control_document: Mapping[str, Any],
    original_verifier,
):
    """Test-only Gate A entry point with an explicit verifier stub."""

    from quervant_bench.official import admission as official_admission

    return official_admission._admit_cross_engine_core(
        raw_root=raw_root,
        freeze=authorization.freeze,
        template=template,
        corpus_dir=corpus_dir,
        control_document=control_document,
        source_root=None,
        original_verifier=original_verifier,
        for_production=False,
    )


def _admit_fixture_retained_key_with_verifier(
    *,
    raw_root: Path,
    authorization,
    template: Mapping[str, Any],
    original_verifier,
):
    """Test-only Gate A entry point for the retained-key family."""

    from quervant_bench.official import admission as official_admission

    return official_admission._admit_retained_key_core(
        raw_root=raw_root,
        freeze=authorization.freeze,
        template=template,
        source_root=None,
        original_verifier=original_verifier,
        for_production=False,
    )


def fixture_historical_parity(
    study_id: str = "cross-engine-keyword-real-v1",
    *,
    fixture_only: bool = True,
):
    """Return a fixture-only verified-historical-parity record for tests."""

    from quervant_bench.official import historical as official_historical

    return official_historical._open_fixture_historical_parity(
        study_id=study_id, fixture_only=fixture_only
    )


def admit_fixture_cross_engine(fixture: CrossEngineFixture):
    """Admit one fixture cross-engine tree as a fixture-only record."""

    return _admit_fixture_cross_engine_with_verifier(
        raw_root=fixture.raw_root,
        authorization=fixture_authorization(
            protocols.STUDY_CROSS_ENGINE, freeze=fixture.freeze
        ),
        template=fixture.template,
        corpus_dir=fixture.corpus_root,
        control_document=fixture.control,
        original_verifier=StubVerifier(),
    )


def admit_fixture_retained_key(fixture: RetainedKeyFixture):
    """Admit one fixture retained-key tree as a fixture-only record."""

    return _admit_fixture_retained_key_with_verifier(
        raw_root=fixture.raw_root,
        authorization=fixture_authorization(
            protocols.STUDY_RETAINED_KEY, freeze=fixture.freeze
        ),
        template=fixture.template,
        original_verifier=StubVerifier(),
    )


def _fixture_historical_lane() -> dict[str, Any]:
    samples = sample_vector(1_000)
    return {
        "n": 10_000,
        "class": "rare",
        "k": 1,
        "regime": "warm",
        "samples_ns": samples,
        "summary_ns": summary(samples),
        "total_hits": 1,
        "doc_ids": ["d00000000"],
    }


def historical_parity_sandbox(
    root: Path, *, study_id: str = "cross-engine-keyword-real-v1"
):
    """Build a TEST-ONLY approved parity mapping/archive simulation.

    The archive holds only the mapped historical lane; the mapping is approved by a
    sandbox approval record and the comparison is recomputed from the archived
    samples by ``open_verified_historical_parity``. Nothing here is real evidence.
    """

    import hashlib

    from quervant_bench.official import historical

    archive = root / "history" / "archive"
    write_json(archive / "run.json", dict(FIXTURE_ONLY, source="fixture"))
    write_json(
        archive / "trials" / "trial-1" / "quervant.json",
        dict(FIXTURE_ONLY, lanes=[_fixture_historical_lane()]),
    )
    lane = _fixture_historical_lane()
    members = {
        name: "sha256:" + hashlib.sha256((archive / name).read_bytes()).hexdigest()
        for name in ("run.json", "trials/trial-1/quervant.json")
    }
    locator = {
        "engine": "quervant",
        "trial": 1,
        "n": 10_000,
        "class": "rare",
        "k": 1,
        "regime": "warm",
    }
    mapping = {
        "kind": "official-historical-parity-mapping",
        "schema_version": 1,
        "study_id": study_id,
        "original_verifier_digest": verifier_digest(
            "benchmarks/pr15d/harness/validate.py"
        ),
        "tolerance_identity": "exact-zero",
        "archive_member_digests": members,
        "rows": [
            {
                "row_id": "historical-rare-k1-median",
                "metric": "lane-median-ns",
                "expected": lane["summary_ns"]["median"],
                "tolerance": "0.000000",
                "locator": locator,
            },
            {
                "row_id": "historical-rare-k1-total-hits",
                "metric": "total-hits",
                "expected": 1,
                "tolerance": "0.000000",
                "locator": locator,
            },
            {
                "row_id": "historical-rare-k1-doc-ids",
                "metric": "doc-ids",
                "expected": ["d00000000"],
                "tolerance": "0.000000",
                "locator": locator,
            },
        ],
    }
    mapping_path = root / "history" / "mapping.json"
    mapping_digest = write_json(mapping_path, mapping)
    approval_root = root / "parity-approvals"
    write_json(
        approval_root / f"test-only-parity{historical.PARITY_APPROVAL_SUFFIX}",
        {
            "kind": historical.PARITY_APPROVAL_KIND,
            "schema_version": 1,
            "study_id": study_id,
            "approved_mapping_digest": mapping_digest,
            "independent_review_id": "test-only-parity-review",
            "approved_at_utc": "2026-01-01T00:00:00Z",
        },
    )
    return historical.open_verified_historical_parity(
        study_id=study_id,
        archive_root=archive,
        mapping_path=mapping_path,
        independently_approved_mapping_digest=mapping_digest,
        approval_source_root=approval_root,
        approval_source_identity="test-only-parity",
        repo_root=REPO_ROOT,
    )


def admit_production_shaped_cross_engine(fixture: CrossEngineFixture, *, sandbox: Path):
    """Admit one fixture series through the real production Gate A boundary.

    The authorization comes from a sandboxed external-approval simulation and the
    pinned original verifier really runs; no engine is launched and no measurement
    is taken.
    """

    from quervant_bench.official import admission as official_admission

    authorization = production_shaped_authorization(fixture.freeze, sandbox=sandbox)
    admitted = official_admission.admit_cross_engine_real(
        raw_root=fixture.raw_root,
        authorization=authorization,
        template=fixture.template,
        corpus_dir=fixture.corpus_root,
        control_document=fixture.control,
        source_root=REPO_ROOT,
        observed=authorization_observations(fixture.freeze),
    )
    return admitted, authorization


def published_cross_engine(root: Path):
    """Publish one TEST-ONLY bundle through the real production gate sequence."""

    from quervant_bench.official import coordinator, publication

    fixture = make_cross_engine_fixture(root / "fixture")
    admitted, authorization = admit_production_shaped_cross_engine(
        fixture, sandbox=root / "sandbox"
    )
    parity = full_historical_parity_sandbox(root / "history-full").open()
    output = root / "output"
    output.mkdir(exist_ok=True)
    result = coordinator.qualify_official_study(
        authorization=authorization,
        template=fixture.template,
        admitted=admitted,
        framework_qa=fixture.framework_qa,
        source_qa=fixture.source_qa,
        historical_parity=parity,
        output_base=output,
        qa_evidence_root=fixture.qa_evidence_root,
        source_root=REPO_ROOT,
        publish=True,
        observed=authorization_observations(fixture.freeze),
    )
    bundle = publication.load_official_bundle(
        output_base=output,
        study_id=result.study_id,
        run_id=result.run_id,
        anchors=result.anchors,
    )
    return (
        result,
        fixture,
        admitted,
        bundle.documents["analysis.json"],
        bundle.documents["policy.json"],
    )


def reopen_authorization(sandbox: Path):
    """Re-open the TEST-ONLY sandboxed authorization capability (no corpus rebuild)."""

    from quervant_bench.official import authorization as official_authorization

    path = sandbox / "authorization" / "authorization.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return official_authorization.open_verified_official_authorization(
        authorization_path=path,
        independently_approved_digest=content_digest(document),
        actual_observations={
            **{name: document[name] for name in protocols.OBSERVED_IDENTITY_FIELDS},
            "output_root_identity": document["approved_output_root_identity"],
        },
        approval_source_identity="test-only-approval",
        approval_source_root=sandbox / "approvals",
    )


# ---------------------------------------------------------------------------
# TEST-ONLY complete PR15D historical matrix (1,440 rows) and QA evidence
# ---------------------------------------------------------------------------

ENGINES = ("quervant", "tantivy", "lucene")
TRIALS = (1, 2, 3)
N_VALUES = (10_000, 100_000)
CLASSES = ("absent", "rare", "medium", "common")
TOP_K = (10, 100)
REGIMES = ("process_cold", "warm")
METRICS = (
    "lane-median-ns",
    "lane-p95-ns",
    "lane-p99-ns",
    "total-hits",
    "doc-ids",
)
_METRIC_TOKENS = {
    "lane-median-ns": "med",
    "lane-p95-ns": "p95",
    "lane-p99-ns": "p99",
    "total-hits": "hits",
    "doc-ids": "ids",
}
_REGIME_TOKENS = {"process_cold": "pc", "warm": "wm"}


def parity_row_id(engine: str, trial: int, n: int, class_name: str, k: int, regime: str, metric: str) -> str:
    return (
        f"{engine}-t{trial}-n{n}-{class_name}-k{k}-"
        f"{_REGIME_TOKENS[regime]}-{_METRIC_TOKENS[metric]}"
    )


def parity_sample_seed(engine: str, trial: int, n: int, class_name: str, k: int, regime: str) -> int:
    engine_index = ENGINES.index(engine)
    class_index = CLASSES.index(class_name)
    regime_index = REGIMES.index(regime)
    size = 2 if n == 100_000 else 1
    cold = 3 if regime == "process_cold" else 1
    return 1_000 + engine_index * 100 + trial * 10 + class_index * 2 + regime_index + size * 5 + cold * 3 + k


def parity_lane_answers(n: int, class_name: str, k: int) -> dict[str, Any]:
    """Closed-form PR15D answer set for the frozen corpus (test-only)."""

    if class_name == "absent":
        identifiers: list[str] = []
    elif class_name == "rare":
        identifiers = ["d00000000"]
    elif class_name == "medium":
        identifiers = ["d%08d" % index for index in range(0, n, 8)]
    else:
        identifiers = ["d%08d" % index for index in range(2, n, 2)]
    return {"total_hits": len(identifiers), "doc_ids": identifiers[:k]}


def parity_metric_value(metric: str, samples: list[int], answers: Mapping[str, Any]) -> Any:
    """Independent nearest-rank reference arithmetic for the test oracle."""

    ordered = sorted(samples)
    if metric == "lane-median-ns":
        return ordered[9]
    if metric == "lane-p95-ns":
        return ordered[18]
    if metric == "lane-p99-ns":
        return ordered[19]
    if metric == "total-hits":
        return answers["total_hits"]
    return list(answers["doc_ids"])


@dataclass(frozen=True)
class FullHistoricalParitySandbox:
    """TEST-ONLY complete 1,440-row historical matrix sandbox."""

    root: Path
    archive: Path
    mapping_path: Path
    approval_root: Path
    approval_identity: str
    mapping_digest: str

    def zero_hit_rows(self) -> int:
        return (
            len(ENGINES)
            * len(TRIALS)
            * len(N_VALUES)
            * len(TOP_K)
            * len(REGIMES)
        )

    def open(self):
        from quervant_bench.official import historical

        return historical.open_verified_historical_parity(
            study_id="cross-engine-keyword-real-v1",
            archive_root=self.archive,
            mapping_path=self.mapping_path,
            independently_approved_mapping_digest=self.mapping_digest,
            approval_source_root=self.approval_root,
            approval_source_identity=self.approval_identity,
            repo_root=REPO_ROOT,
        )


def full_historical_parity_sandbox(
    root: Path,
    *,
    row_filter=None,
    reverse_rows: bool = False,
    duplicate_row: bool = False,
    extra_row: bool = False,
) -> FullHistoricalParitySandbox:
    """Build a TEST-ONLY authenticated archive + complete approved mapping.

    ``row_filter``/``reverse_rows``/``duplicate_row``/``extra_row`` exist so
    negative tests can construct deliberately incomplete or malformed mappings.
    """

    from quervant_bench.official import historical

    archive = root / "history" / "archive"
    write_json(archive / "run.json", dict(FIXTURE_ONLY, source="fixture"))
    lanes_by_trial: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for trial in TRIALS:
        for engine in ENGINES:
            lanes: list[dict[str, Any]] = []
            for n in N_VALUES:
                for class_name in CLASSES:
                    field, term = ("group", "medium") if class_name == "medium" else (
                        "key",
                        {"absent": "never", "rare": "singleton", "common": "common"}[class_name],
                    )
                    for k in TOP_K:
                        for regime in REGIMES:
                            samples = sample_vector(
                                parity_sample_seed(
                                    engine, trial, n, class_name, k, regime
                                )
                            )
                            answers = parity_lane_answers(n, class_name, k)
                            lanes.append(
                                {
                                    "id": f"pr15d_v1/{n}/{class_name}/k{k}",
                                    "n": n,
                                    "class": class_name,
                                    "field": field,
                                    "term": term,
                                    "k": k,
                                    "regime": regime,
                                    "samples_ns": samples,
                                    "total_hits": answers["total_hits"],
                                    "doc_ids": answers["doc_ids"],
                                }
                            )
            write_json(
                archive / "trials" / f"trial-{trial}" / f"{engine}.json",
                dict(FIXTURE_ONLY, trial=trial, engine=engine, lanes=lanes),
            )
            lanes_by_trial.setdefault(trial, {})[engine] = lanes

    rows: list[dict[str, Any]] = []
    for engine in ENGINES:
        for trial in TRIALS:
            for n in N_VALUES:
                for class_name in CLASSES:
                    for k in TOP_K:
                        for regime in REGIMES:
                            lane = next(
                                item
                                for item in lanes_by_trial[trial][engine]
                                if item["n"] == n
                                and item["class"] == class_name
                                and item["k"] == k
                                and item["regime"] == regime
                            )
                            answers = parity_lane_answers(n, class_name, k)
                            for metric in METRICS:
                                rows.append(
                                    {
                                        "row_id": parity_row_id(
                                            engine, trial, n, class_name, k, regime, metric
                                        ),
                                        "metric": metric,
                                        "expected": parity_metric_value(
                                            metric, lane["samples_ns"], answers
                                        ),
                                        "tolerance": "0.000000",
                                        "locator": {
                                            "engine": engine,
                                            "trial": trial,
                                            "n": n,
                                            "class": class_name,
                                            "k": k,
                                            "regime": regime,
                                        },
                                    }
                                )
    rows.sort(
        key=lambda row: (
            row["locator"]["engine"],
            row["locator"]["trial"],
            row["locator"]["n"],
            row["locator"]["class"],
            row["locator"]["k"],
            row["locator"]["regime"],
            row["metric"],
        )
    )
    if row_filter is not None:
        rows = [row for row in rows if row_filter(row)]
    if reverse_rows:
        rows = list(reversed(rows))
    if duplicate_row and rows:
        rows = rows[:-1] + [dict(rows[0])]
    if extra_row:
        extra = dict(rows[0])
        extra["row_id"] = "extra-row"
        rows = rows + [extra]

    members = {
        name: "sha256:" + hashlib.sha256((archive / name).read_bytes()).hexdigest()
        for name in [
            "run.json",
            *[
                f"trials/trial-{trial}/{engine}.json"
                for trial in TRIALS
                for engine in ENGINES
            ],
        ]
    }
    mapping = {
        "kind": "official-historical-parity-mapping",
        "schema_version": 1,
        "study_id": "cross-engine-keyword-real-v1",
        "original_verifier_digest": verifier_digest(
            "benchmarks/pr15d/harness/validate.py"
        ),
        "tolerance_identity": "exact-zero",
        "archive_member_digests": members,
        "rows": rows,
    }
    mapping_path = root / "history" / "mapping.json"
    mapping_digest = write_json(mapping_path, mapping)
    approval_root = root / "parity-approvals"
    identity = "test-only-parity"
    write_json(
        approval_root / f"{identity}{historical.PARITY_APPROVAL_SUFFIX}",
        {
            "kind": historical.PARITY_APPROVAL_KIND,
            "schema_version": 1,
            "study_id": "cross-engine-keyword-real-v1",
            "approved_mapping_digest": mapping_digest,
            "independent_review_id": "test-only-parity-review",
            "approved_at_utc": "2026-01-01T00:00:00Z",
        },
    )
    return FullHistoricalParitySandbox(
        root=root,
        archive=archive,
        mapping_path=mapping_path,
        approval_root=approval_root,
        approval_identity=identity,
        mapping_digest=mapping_digest,
    )
