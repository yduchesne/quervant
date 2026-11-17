"""Deterministic, test-only builders for the official qualification facade.

Every document produced here is structurally complete but is **never** real
evidence: it is created in a temporary directory from literal sample values, with a
test-only verifier stub and a test-only freeze. Production G0 cannot accept any of
it because the authorization/approval artefacts do not exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.evidence.provenance import repository_root
from quervant_bench.official import admission
from quervant_bench.official import protocols
from quervant_bench.official.controls import assess_cross_engine_control
from quervant_bench.official.protocols import OfficialFreeze

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Reviewed design-template digests (independently pinned literals).
RETAINED_KEY_TEMPLATE_DIGEST = (
    "sha256:bf6fd040819b86b2bee317c83eb286e1e5f50400f8e19cb8490d8171d1197f44"
)
CROSS_ENGINE_TEMPLATE_DIGEST = (
    "sha256:86ac2996777ced1995969e3a8f9271aa8de324b41006456c3fd9e64568211815"
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
            "doc_count": n,
            "index_ns": 1_000 + n,
            "commit_ns": 500,
            "reopen_ns": 250,
            "index_bytes": 4_096 + n,
            "committed": True,
            "reopened": True,
            "segments": 1,
        }
        for n in admission.PR15D_N_VALUES
    }
    throughput = [
        {
            "id": admission.pr15d_lane_id(n, "medium", 10),
            "requests": 100,
            "answered": 100,
            "serial_ops_per_second": 1_000,
            "median_ns": 1_000_000,
            "total_ns": 100_000_000,
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


def published_cross_engine(root: Path):
    """Publish one test-only cross-engine bundle and return the artefacts."""

    from quervant_bench.official import analysis, coordinator

    fixture = make_cross_engine_fixture(root / "fixture")
    admitted = admission.admit_cross_engine_real(
        raw_root=fixture.raw_root,
        freeze=fixture.freeze,
        template=fixture.template,
        corpus_dir=fixture.corpus_root,
        control_document=fixture.control,
        original_verifier=StubVerifier(),
    )
    parity = cross_engine_parity(root)
    output = root / "output"
    output.mkdir(exist_ok=True)
    result = coordinator.qualify_official_study(
        freeze=fixture.freeze,
        template=fixture.template,
        admitted=admitted,
        framework_qa=qa_evidence("framework-qa", fixture.freeze),
        source_qa=qa_evidence("source-qa", fixture.freeze),
        historical_parity=parity,
        output_base=output,
        publish=True,
    )
    analysis_document, policy_document = analysis.analyze_official_study(
        admitted=admitted, template=fixture.template
    )
    return result, fixture, admitted, analysis_document, policy_document


@dataclass(frozen=True)
class CrossEngineFixture:
    raw_root: Path
    corpus_root: Path
    freeze: OfficialFreeze
    template: Mapping[str, Any]
    control: Mapping[str, Any]
    run_json: Mapping[str, Any]


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
        source_file_set_digest=DIGEST_B,
        source_tree_sha=DIGEST_C,
        adapter_source_manifest_digest=DIGEST_A,
        binary_manifest_digest=DIGEST_B,
        corpus_manifest_digest=corpus_manifest_digest,
        original_reference_verifier_digest=original_verifier_digest,
        host_preflight_digest=DIGEST_A,
        control_schedule_digest=DIGEST_B,
        treatment_schedule_digest=DIGEST_C,
        qa_source_digest=DIGEST_A,
        qa_framework_digest=DIGEST_B,
        operator_approval_id="fixture-operator-approval",
        independent_protocol_review_id="fixture-independent-review",
        approved_at_utc="2026-01-01T00:00:00Z",
        approved_output_root_identity="/tmp/approved-official-root",
        policy_digest=DIGEST_C,
        permitted_campaign_order=("fixture",),
        measurement_retries=0,
    )


def make_cross_engine_fixture(
    root: Path, *, run_id: str = "11111111-1111-4111-8111-111111111111"
) -> CrossEngineFixture:
    corpus = make_corpus(root / "corpus")
    freeze = make_freeze(
        study_id=protocols.STUDY_CROSS_ENGINE,
        corpus_manifest_digest="sha256:" + corpus["manifest_sha"],
        original_verifier_digest=verifier_digest("benchmarks/pr15d/harness/validate.py"),
        run_id=run_id,
    )
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


def make_retained_key_fixture(
    root: Path, *, run_id: str = "22222222-2222-4222-8222-222222222222"
) -> RetainedKeyFixture:
    template, digest = protocols.read_approved_template(
        protocols.template_path(protocols.STUDY_RETAINED_KEY, REPO_ROOT),
        RETAINED_KEY_TEMPLATE_DIGEST,
    )
    freeze = make_freeze(
        study_id=protocols.STUDY_RETAINED_KEY,
        original_verifier_digest=verifier_digest("benchmarks/pr15i_d3_c/verify.py"),
        run_id=run_id,
    )
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
    )
