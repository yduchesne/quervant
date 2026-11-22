"""G0-bound orchestration of the unchanged retained-key measurement primitives.

The old CLI builds inside each campaign. This bridge keeps those exact builds,
paths, timing primitives, slots, summaries and seals, and adds the missing
comparison with G0-prepared executable bytes *before* any index/query operation.
It never substitutes an old archive for a newly authorized campaign.
"""

from __future__ import annotations

import multiprocessing
import os
import time
import traceback
from pathlib import Path
from typing import Any, Mapping

from ..config.errors import BM_ACQUISITION_PROHIBITED, BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import require_safe_root
from ..evidence.provenance import repository_root
from .acquisition import _finish_owned_worker, sanitized_environment
from .authorization import VerifiedOfficialAuthorization, require_verified_official_authorization
from . import current_retained_build as current_build
from .cross_engine_backend import _fresh, _verify_cpu_pair, _write
from .protocols import D3C_CAMPAIGN_NAMES, D3C_CONTROL_NAME, STUDY_RETAINED_KEY, read_approved_template, template_path
from .retained_backend import PreparedRetainedKey, legacy_runner, load_prepared_retained_key, require_retained_namespace


def _fail(message: str, field: str = "backend", code: str = BM_IDENTITY_INVALID) -> BenchError:
    return BenchError(code, message, field_path=field)


def _require_built_binary(actual: Mapping[str, Any], expected: Mapping[str, Any], target: Path) -> None:
    """Observe bytes, do not rely on a build function's returned digest alone."""
    binary = target / "release" / "pr15d-quervant-adapter"
    if actual.get("binary") != str(binary):
        raise _fail("the rebuilt adapter is outside its fixed output path", "binary_manifest_digest")
    digest, length = sha256_regular_file(binary.parent, binary.name, max_bytes=536_870_912)
    if (digest != "sha256:" + expected["sha256"] or type(actual.get("bytes")) is not int
            or length != actual["bytes"] or length != expected["bytes"]
            or actual.get("sha256") != expected["sha256"]
            or actual.get("source_sha") != expected["source_sha"]
            or actual.get("feature") is not expected["feature"]):
        raise _fail("rebuilt executable bytes differ from G0 preparation; no query was authorized", "binary_manifest_digest")


def _build_bound_inputs(runner: Any, protocol: Mapping[str, Any], directory: Path,
                        prepared: PreparedRetainedKey, *, control: bool,
                        profile_version: int = 1) -> tuple[Any, ...]:
    """Original preparation sequence, with a pre-query binary identity barrier."""
    corpus = runner.prepare_corpus(protocol, str(directory / "corpus"))
    canonical = runner.worktree(str(directory), runner.BASE_SHA)
    current_v2 = profile_version == 2
    policy_digest = prepared.manifest.get("build_policy_digest") if current_v2 else None
    toolchain = prepared.manifest.get("toolchain") if current_v2 else None
    if current_v2 and (policy_digest is None or toolchain is None):
        raise _fail("the prepared manifest carries no current-v2 build policy", "build_policy_digest")
    a = runner.build(canonical, str(directory / "build" / "A"), False)
    if current_v2:
        current_build.require_closed_argv({"argv": a["argv"]}, source_root=Path(canonical),
                                          target_dir=directory / "build" / "A", feature=False)
        current_build.require_current_v2_build(
            {**a, "arm": "A"}, arm="A", expected_source_sha=runner.BASE_SHA, expected_feature=False,
            root=directory, policy_digest=policy_digest, expected_policy_digest=policy_digest)
    else:
        _require_built_binary(a, prepared.manifest["binaries"]["A"], directory / "build" / "A")
    if not control:
        runner.switch(canonical, runner.BASE_SHA, runner.EXPERIMENT_SHA)
    b = runner.build(canonical, str(directory / "build" / "B"), not control)
    expected_b_feature = current_build.EXPERIMENT_FEATURE if not control else False
    if current_v2:
        current_build.require_closed_argv({"argv": b["argv"]}, source_root=Path(canonical),
                                          target_dir=directory / "build" / "B", feature=expected_b_feature)
        current_build.require_current_v2_build(
            {**b, "arm": "B"}, arm="B",
            expected_source_sha=runner.EXPERIMENT_SHA if not control else runner.BASE_SHA,
            expected_feature=expected_b_feature, root=directory,
            policy_digest=policy_digest, expected_policy_digest=policy_digest)
    else:
        _require_built_binary(b, prepared.manifest["binaries"]["A" if control else "B"], directory / "build" / "B")
    if not current_v2:
        if control and (a["sha256"] != b["sha256"] or a["bytes"] != b["bytes"]):
            raise _fail("control binaries differ", "binary_manifest_digest")
        if not control and a["sha256"] == b["sha256"]:
            raise _fail("experimental binary equals BASE", "binary_manifest_digest")
    arms = {"A": a, "B": b} if control else {"A": a, "L": b, "P": b, "H": b}
    if current_v2:
        for arm, record in arms.items():
            record["arm"] = arm
            record["feature"] = (expected_b_feature if arm == "B" or arm in ("L", "P", "H") else False)
        binding = current_build.build_binding_document(
            campaign="", control=control, policy_digest=policy_digest,
            builds={**{arm: {key: record[key] for key in
                            ("arm", "source_sha", "feature", "argv", "binary", "sha256", "bytes")}
                       for arm, record in arms.items()}, "__toolchain__": toolchain})
        binding["campaign"] = directory.name
        runner.wj(str(directory / "raw" / current_build.BINDING_NAME), binding, exclusive=True)
    else:
        # This durable barrier is written before build_index or measure_lane can run.
        runner.wj(str(directory / "raw" / "official-premeasurement-binaries.json"), {
            "kind": "official-retained-premeasurement-binary-binding", "schema_version": 1,
            "binary_manifest_digest": prepared.binary_digest, "prepared_manifest": str(prepared.manifest_path),
            "query_operations_started": False, "actual_A": a, "actual_B": b,
        }, exclusive=True)
    return corpus, canonical, a, b, arms


def _execute_campaign(directory: Path, campaign: str, prepared: PreparedRetainedKey,
                      profile_version: int = 1) -> None:
    """Reuse the legacy orchestration's data shapes and its timing functions."""
    r = legacy_runner()
    protocol, protocol_sha = r.load_protocol()
    r.require_freeze(campaign)
    control = campaign == protocol["control_name"]
    current_v2 = profile_version == 2
    if not control:
        if campaign not in protocol["campaign_names"]:
            raise _fail("unknown retained-key campaign", "campaign", BM_UNSAFE_INPUT)
        if current_v2:
            from .current_retained_verifier import require_v2_predecessor
            # Same archive root the frozen controller derives from the private
            # evidence HOME, so a v2 predecessor is checked against its own
            # published archive and never against a historical v1 receipt.
            archive_root = Path(os.path.expanduser("~")) / ".local" / "share" / "quervant" / getattr(r, "EVIDENCE_REL")
            require_v2_predecessor(directory.parent, protocol["control_name"], evidence_root=archive_root,
                                   expected_policy_digest=prepared.manifest["build_policy_digest"])
            if campaign == protocol["campaign_names"][1]:
                previous = protocol["campaign_names"][0]
                require_v2_predecessor(directory.parent, previous, evidence_root=archive_root,
                                       expected_policy_digest=prepared.manifest["build_policy_digest"])
        else:
            r.verified(str(directory.parent / protocol["control_name"]), "control", protocol["control_name"])
            if campaign == protocol["campaign_names"][1]:
                previous = protocol["campaign_names"][0]
                r.verified(str(directory.parent / previous), "four_arm", previous)
    adapter_cpu, controller_cpu = r.cpus()
    (directory / "indexes").mkdir()
    corpus, canonical, a, b, arms = _build_bound_inputs(
        r, protocol, directory, prepared, control=control, profile_version=profile_version)
    h = r.harness()
    oracle = r.oracle()
    expected = {n: r.expected_for(protocol, n) for n in protocol["n_values"]}
    corpus_paths = {n: os.path.join(corpus, oracle.corpus_filename(n)) for n in protocol["n_values"]}
    indices = {}
    for arm, binary in arms.items():
        indices[arm] = {n: r.build_index(h, binary["binary"], corpus_paths[n],
            str(directory / "indexes" / f"{arm}-n{n}"), n) for n in protocol["n_values"]}
    for arm in indices:
        for n in protocol["n_values"]:
            layout = indices[arm][n]["layout"]
            if layout["digest"] != indices["A"][n]["layout"]["digest"]:
                raise _fail("arm index digests differ", "indexes")
            if n == 100000 and layout["bytes"] != protocol["index_100k_committed_sentinel"]:
                raise _fail("the 100K committed index sentinel differs", "indexes")
    r.pin(controller_cpu)
    host = r.host_record(protocol, adapter_cpu, controller_cpu, str(directory), canonical)
    host["campaign"] = campaign
    r.wj(str(directory / "raw/host-attestation.json"), host, exclusive=True)
    ready = r.readiness(protocol, adapter_cpu, controller_cpu, host["host_fingerprint"])
    ready["campaign"] = campaign
    r.wj(str(directory / "raw/host-readiness.json"), ready, exclusive=True)
    if ready["readiness_status"] != "READY":
        raise _fail("the original retained readiness gate failed", "readiness", BM_ACQUISITION_PROHIBITED)
    lanes = r.lanes(protocol)
    plan = r.control_schedule(protocol) if control else r.schedule(protocol, campaign)
    slots = []
    for entry in plan:
        arm = entry["arm"]
        binary = arms[arm]
        before_affinity = r.allowed(os.getpid())
        if before_affinity != [controller_cpu]:
            raise _fail("controller affinity changed before a slot", "affinity")
        before = r.probe(h, str(directory / "raw/contention" / f"slot-{entry['slot']:02d}-before.json"))
        measured = [r.measure_lane(protocol, arm, binary["binary"], indices[arm][lane["n"]]["dir"],
            adapter_cpu, lane, expected[lane["n"]][lane["id"]]) for lane in lanes]
        after = r.probe(h, str(directory / "raw/contention" / f"slot-{entry['slot']:02d}-after.json"))
        after_affinity = r.allowed(os.getpid())
        if after_affinity != [controller_cpu]:
            raise _fail("controller affinity changed after a slot", "affinity")
        slot = {"schema": "pr15i-d3c-slot-v1", **entry, "source_sha": binary["source_sha"],
            "binary_sha256": binary["sha256"],
            "index_digests": {str(n): indices[arm][n]["layout"]["digest"] for n in protocol["n_values"]},
            "controller_affinity_before": before_affinity, "controller_affinity_after": after_affinity,
            "contention_before": before, "contention_after": after, "lanes": measured}
        r.wj(str(directory / "raw/slots" / f"slot-{entry['slot']:02d}.json"), slot, exclusive=True)
        slots.append(slot)
    kind = "control" if control else "four_arm"
    provenance = r.build_provenance(kind, campaign, canonical, a, b, arms, indices, protocol)
    r.wj(str(directory / "raw/build-provenance.json"), provenance, exclusive=True)
    # The preceding exact checks establish the same structural condition used by
    # the frozen controller. The original summary still owns all statistical policy.
    summary = (r.summary_control(protocol, slots, lanes, protocol["blocks"]) if control else
        r.summary_campaign(protocol, slots, lanes, protocol["blocks"], campaign, True))
    manifest = {"schema": "pr15i-d3c-manifest-v1", "campaign": campaign, "kind": kind,
        "protocol_sha256": protocol_sha, "source_base_sha": r.BASE_SHA,
        "source_experiment_sha": None if control else r.EXPERIMENT_SHA,
        "prefilter_profile": protocol["prefilter_profile"],
        "arms": {arm: {"source_sha": info["source_sha"], "binary_sha256": info["sha256"],
            "binary_bytes": info["bytes"], "indexes": {str(n): indices[arm][n]["layout"] for n in protocol["n_values"]}}
            for arm, info in arms.items()},
        "build_events": provenance["events"], "host_fingerprint": host["host_fingerprint"],
        "host_attestation_sha256": r.sf(str(directory / "raw/host-attestation.json")),
        "host_readiness_sha256": r.sf(str(directory / "raw/host-readiness.json")),
        "build_provenance_sha256": r.sf(str(directory / "raw/build-provenance.json")),
        "slots": len(slots), "lanes_per_slot": len(lanes)}
    auth = {"schema": "pr15i-d3c-authorization-v1", "campaign": campaign, "kind": kind,
        "protocol_sha256": protocol_sha, "idle_confirmed": True, "rehearsal_only": False,
        "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    r.write_evidence(str(directory), manifest, summary, auth)
    if summary["status"] != "ACQUIRED_VERIFIED":
        raise _fail("the original campaign summary rejected the acquired series", "summary", BM_ACQUISITION_PROHIBITED)


def _worker(directory: Path, campaign: str, manifest_path: Path, root: Path,
            environment: Mapping[str, str], receipts: Path,
            runtime_binding: Mapping[str, Any] | None = None) -> None:
    os.setsid()
    os.environ.clear()
    os.environ.update(environment)
    with (receipts / "stdout.log").open("xb") as out, (receipts / "stderr.log").open("xb") as err:
        os.dup2(out.fileno(), 1)
        os.dup2(err.fileno(), 2)
        try:
            prepared = load_prepared_retained_key(manifest_path, root=root)
            from .runtime_freeze import open_worker_runtime_freeze, reject_current_receipt_for_v1
            if runtime_binding is None:
                reject_current_receipt_for_v1(root)
            else:
                if type(runtime_binding) is not dict or set(runtime_binding) != {"envelope_path", "digest", "profile_version"}:
                    raise _fail("worker runtime binding has an unregistered shape", "runtime_freeze")
                open_worker_runtime_freeze(root=root, envelope_path=Path(runtime_binding["envelope_path"]),
                    prepared_manifest=manifest_path, expected_digest=runtime_binding["digest"],
                    profile_version=runtime_binding["profile_version"])
            version = 2 if runtime_binding is not None else 1
            _execute_campaign(directory, campaign, prepared, version)
        except BaseException:
            traceback.print_exc()
            raise


def acquire_retained_campaign(authorization: VerifiedOfficialAuthorization, *, root: Path,
    directory: Path, campaign: str, prepared: PreparedRetainedKey,
    observed: Mapping[str, Any], official_home: Path, runtime_context: Any = None) -> Path:
    """Acquire one authorized campaign once; original predecessor checks remain."""
    freeze = require_verified_official_authorization(authorization, study_id=STUDY_RETAINED_KEY,
        for_production=True, observed=observed)
    if root.resolve() != repository_root().resolve():
        raise _fail("the configured source is not the executing checkout", "source_root")
    if campaign not in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES) or directory.name != campaign:
        raise _fail("the campaign is outside the frozen sequence", "campaign", BM_UNSAFE_INPUT)
    require_retained_namespace(root, directory)
    require_safe_root(official_home)
    if official_home.stat().st_mode & 0o777 != 0o700:
        raise _fail("the private archive home must be mode 700", "home", BM_UNSAFE_INPUT)
    fresh = load_prepared_retained_key(prepared.manifest_path, root=root)
    if fresh.binary_digest != prepared.binary_digest or fresh.binary_digest != freeze.binary_manifest_digest:
        raise _fail("prepared retained binaries differ from G0", "binary_manifest_digest")
    if fresh.manifest["corpus_digest"] != freeze.corpus_manifest_digest:
        raise _fail("prepared corpus differs from G0", "corpus_manifest_digest")
    from .runtime_freeze import require_runtime_for_freeze, reject_current_receipt_for_v1
    runtime_binding = None
    if freeze.profile_version == 2:
        current_runtime = require_runtime_for_freeze(runtime_context, freeze, root=root)
        runtime_binding = {"envelope_path": str(current_runtime._envelope_path),
                           "digest": current_runtime.digest, "profile_version": freeze.profile_version}
    else:
        reject_current_receipt_for_v1(root)
    runner = legacy_runner()
    runner.require_freeze(campaign)
    adapter_cpu, controller_cpu = runner.cpus()
    template, _ = read_approved_template(template_path(STUDY_RETAINED_KEY, root, version=freeze.profile_version), freeze.design_digest)
    if template["study_id"] != STUDY_RETAINED_KEY:
        raise _fail("the reviewed design is not the retained-key study", "study_id")
    _verify_cpu_pair(freeze, adapter_cpu, controller_cpu, template=template)
    _fresh(directory)
    receipt_parent = directory.parent / "official-worker-records"
    receipt_parent.mkdir(exist_ok=True)
    require_safe_root(receipt_parent)
    receipts = _fresh(receipt_parent / campaign)
    timeout = template["stopping"]["backend_timeout_seconds"]
    environment = sanitized_environment(official_home)
    _write(receipts / "started.json", {"campaign": campaign, "run_id": freeze.run_id,
        "authorization_digest": freeze.authorization_digest, "prepared_manifest": str(fresh.manifest_path),
        "binary_manifest_digest": fresh.binary_digest, "adapter_cpu": adapter_cpu,
        "controller_cpu": controller_cpu, "timeout_seconds": timeout})
    worker_args = (directory, campaign, fresh.manifest_path, root, environment, receipts)
    if runtime_binding is not None:
        worker_args += (runtime_binding,)
    process = multiprocessing.get_context("fork").Process(target=_worker, args=worker_args)
    started = time.time_ns()
    completed = False
    try:
        process.start()
        process.join(timeout)
        if process.is_alive():
            raise _fail("the frozen retained backend timeout elapsed", "timeout", BM_ACQUISITION_PROHIBITED)
        completed = process.exitcode == 0
    finally:
        try:
            _finish_owned_worker(process)
        finally:
            _write(receipts / "result.json", {"campaign": campaign, "start_time_ns": started,
                "end_time_ns": time.time_ns(), "exit_code": process.exitcode,
                "status": "COMPLETE" if completed else "STOPPED_PRESERVED", "retry_allowed": False})
    if process.exitcode != 0:
        raise _fail("the original retained primitives failed; partial evidence is preserved", "backend", BM_ACQUISITION_PROHIBITED)
    return directory
