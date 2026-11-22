"""Truthfully versioned current-baseline-v2 retained-key verifier and publisher.

The frozen historical v1 verifier (``benchmarks/pr15i_d3_c/verify.py``) *requires*
the two independently compiled A/A binaries to have identical hashes. Under the
current-v2 rule that assertion is scientifically wrong: Cargo's per-unit
``-C metadata`` embeds the absolute manifest path, so two builds of the same
pinned revision from different directories differ by construction.

This module therefore reuses every *pure* helper of the frozen verifier and
re-implements only ``verify_campaign`` with exactly two documented relaxations:

* ``verify.py:230`` (control A/A ``binary_sha256``/``binary_bytes`` equality) is
  replaced by a per-build own-artifact check against the campaign's versioned
  ``current-v2-retained-premeasurement-binding`` record;
* ``verify.py:235`` (``V_AB``: "experiment equals BASE") is dropped, because the
  inequality of two independent builds is not evidence of strategy routing.

Every other check is ported unchanged; the intra-artifact requirement that
``L``/``P``/``H`` reference the *same* experimental build (``verify.py:234``)
is retained. The frozen files themselves are untouched, and the report identity
states ``bm09-current-v2-verifier`` rather than a historical v1 PASS.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from ..qualification.contracts import require_closed
from . import current_retained_build as build_policy
from .admission import _load_module
from .protocols import read_canonical_json

VERIFIER_IDENTITY = "bm09-current-v2-verifier"
SOURCE_BASES = ("checkout", "pinned-git")
VERIFICATION_SCHEMA = "bm09-current-v2-verification-v1"
ARCHIVE_SCHEMA = "pr15i-d3c-archive-v1"


def frozen_verifier() -> Any:
    """Load the frozen historical verifier for its unchanged pure helpers."""

    return _load_module("official_frozen_d3c_verifier", "benchmarks/pr15i_d3_c/verify.py")


class V2VerificationError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _reject(code: str, detail: str) -> None:
    raise V2VerificationError(code, detail)


def _policy_digest_for(directory: Path, *, expected_policy_digest: str | None,
                       source_basis: str = "checkout") -> str:
    """Recompute the policy from the campaign's own pinned source and compare.

    The source basis is selected explicitly by the execution context, never
    inferred from whether a directory happens to exist: production acquisition
    requires the campaign's own compilation checkout and fails without it, while
    offline replay derives the profile from the exact pinned revisions because its
    working copy intentionally excludes the checkout.
    """

    binding = build_policy.read_build_binding(directory / "raw" / build_policy.BINDING_NAME)
    if expected_policy_digest is not None and binding["build_policy_digest"] != expected_policy_digest:
        _reject("V2_POLICY", "the campaign build binding uses another build policy")
    declared = require_closed(dict(binding["toolchain"]), "toolchain", build_policy._TOOLCHAIN_KEYS)
    if source_basis not in SOURCE_BASES:
        _reject("V2_POLICY", "an unknown source basis was selected")
    if source_basis == "checkout":
        source = directory / "compile-source"
        if not source.is_dir():
            _reject("V2_POLICY", "the campaign has no compilation checkout")
        observed_policy = build_policy.current_v2_build_policy(source_root=source, toolchain=declared)
    else:
        observed_policy = build_policy.current_v2_build_policy(
            toolchain=declared, release_profile=_pinned_release_profile(directory)
        )
    recomputed = build_policy.build_policy_digest(observed_policy)
    if recomputed != binding["build_policy_digest"]:
        _reject("V2_POLICY", "the pinned source profile no longer matches the recorded build policy")
    if expected_policy_digest is not None and recomputed != expected_policy_digest:
        _reject("V2_POLICY", "the pinned source profile no longer matches the authorised build policy")
    return recomputed


def _pinned_release_profile(directory: Path) -> dict[str, str]:
    """Release-profile digests read from the campaign's own pinned revisions.

    A campaign produced by the measurement controller carries a ``compile-source``
    checkout, so this path is only used for a *projected* replay working copy,
    which deliberately excludes that directory. The profile is then read from the
    exact pinned revisions recorded in the campaign manifest, so the policy is
    still derived from the source the campaign was built from.
    """

    from ..evidence.provenance import repository_root

    manifest = read_canonical_json(directory / "manifest.json")
    base = manifest.get("source_base_sha")
    experiment = manifest.get("source_experiment_sha") or base
    if not isinstance(base, str) or not isinstance(experiment, str):
        raise V2VerificationError("V2_POLICY", "the campaign manifest records no pinned revisions")
    checkout = repository_root()
    try:
        base_profile = build_policy.release_profile_settings_from_git(checkout, base)
        experiment_profile = (
            base_profile if experiment == base
            else build_policy.release_profile_settings_from_git(checkout, experiment)
        )
    except BenchError as error:
        raise V2VerificationError("V2_POLICY", str(error)) from error
    if base_profile != experiment_profile:
        raise V2VerificationError("V2_POLICY", "the pinned revisions select different release profiles")
    return base_profile


def verify_campaign_v2(directory: Path, *, expected_policy_digest: str | None = None,
                       source_basis: str = "checkout") -> dict[str, Any]:
    """Verify one completed current-v2 campaign without cross-build equality."""

    frozen = frozen_verifier()
    d = Path(directory)
    if source_basis not in SOURCE_BASES:
        _reject("V2_POLICY", "an unknown source basis was selected")
    policy_digest = _policy_digest_for(d, expected_policy_digest=expected_policy_digest,
                                      source_basis=source_basis)
    p = frozen.load_protocol()
    m = frozen.rj(os.path.join(d, "manifest.json"))
    a = frozen.rj(os.path.join(d, "authorization.json"))
    if m.get("schema") != "pr15i-d3c-manifest-v1" or a.get("schema") != "pr15i-d3c-authorization-v1":
        _reject("V_MANIFEST", "schema")
    synthetic = bool(a.get("rehearsal_only")) or "rehearsal" in str(d).split(os.sep)
    if m.get("protocol_sha256") != frozen.PROTOCOL_SHA256 or a.get("protocol_sha256") != frozen.PROTOCOL_SHA256:
        _reject("V_PROTOCOL", "digest")
    kind = m["kind"]
    campaign = m["campaign"]
    if kind == "control" and campaign != p["control_name"]:
        _reject("V_CAMPAIGN", "control name")
    if kind == "four_arm" and campaign not in p["campaign_names"]:
        _reject("V_CAMPAIGN", "campaign name")
    seal = frozen.inventory(d)
    host = frozen.rj(os.path.join(d, "raw/host-attestation.json"))
    ready = frozen.rj(os.path.join(d, "raw/host-readiness.json"))
    if m.get("host_attestation_sha256") != frozen.sf(os.path.join(d, "raw/host-attestation.json")):
        _reject("V_SEAL", "host digest")
    if m.get("host_readiness_sha256") != frozen.sf(os.path.join(d, "raw/host-readiness.json")):
        _reject("V_SEAL", "readiness digest")
    if m.get("build_provenance_sha256") != frozen.sf(os.path.join(d, "raw/build-provenance.json")):
        _reject("V_SEAL", "provenance digest")
    frozen.verify_readiness(ready, host, p)
    if host.get("protocol_sha256") != frozen.PROTOCOL_SHA256:
        _reject("V_PROTOCOL", "host")
    if host.get("controller_cpu") == host.get("adapter_cpu"):
        _reject("V_AFFINITY", "same cpu")
    topo = host.get("cpu_topology")
    if not isinstance(topo, dict):
        _reject("V_HOST", "missing cpu topology")
    adapter_cpu = topo.get("adapter")
    controller_cpu = topo.get("controller")
    if not isinstance(adapter_cpu, dict) or not isinstance(controller_cpu, dict):
        _reject("V_HOST", "cpu topology shape")
    if adapter_cpu.get("cpu") != host["adapter_cpu"] or controller_cpu.get("cpu") != host["controller_cpu"]:
        _reject("V_HOST", "cpu topology identity")
    if adapter_cpu.get("package_id") != controller_cpu.get("package_id"):
        _reject("V_HOST", "cross-package pair")
    if adapter_cpu.get("core_id") == controller_cpu.get("core_id"):
        _reject("V_HOST", "SMT sibling pair")
    if adapter_cpu.get("thread_siblings") == controller_cpu.get("thread_siblings"):
        _reject("V_HOST", "same sibling set")
    roles = {x["role"] for x in host.get("filesystems", [])}
    if roles != {"repository", "campaign_output", "compile_source", "build_A", "build_B", "corpus", "indexes"}:
        _reject("V_HOST", "roles")
    for item in host["filesystems"]:
        if item["harness_fstype"] != item["findmnt_fstype"] or item["findmnt_fstype"] not in ("ext4", "xfs", "btrfs"):
            _reject("V_HOST", "fs")
    prov = frozen.rj(os.path.join(d, "raw/build-provenance.json"))
    arms = m["arms"]
    kinds = {"A", "B"} if kind == "control" else {"A", "L", "P", "H"}
    if set(arms) != kinds:
        _reject("V_BUILD", "arm set")
    binding = build_policy.read_build_binding(d / "raw" / build_policy.BINDING_NAME)
    build_policy.require_binding_matches_arms(binding, arms=arms, expected_policy_digest=policy_digest)
    if kind == "control":
        # verify.py:230 relaxation: the two independent BASE builds need not share
        # bytes; each was already bound to its own record above.
        for arm in ("A", "B"):
            if arms[arm]["source_sha"] != frozen.BASE_SHA:
                _reject("V_SOURCE", f"{arm} is not the BASE revision")
            if arms[arm].get("feature", False) is not False:
                _reject("V_BUILD", f"{arm} is not a BASE-mode build")
    else:
        for arm in ("L", "P", "H"):
            if arms[arm]["binary_sha256"] != arms["L"]["binary_sha256"]:
                _reject("V_BUILD", "L/P/H binary differ")
        if m.get("source_experiment_sha") != frozen.EXPERIMENT_SHA:
            _reject("V_SOURCE", "experiment sha")
    if m.get("source_base_sha") != frozen.BASE_SHA:
        _reject("V_SOURCE", "base sha")
    if prov.get("canonical_source_path") != os.path.join(d, "compile-source"):
        _reject("V_SOURCE", "canonical path")
    events = prov.get("events")
    if not isinstance(events, list) or {e["arm"] for e in events} != kinds:
        _reject("V_BUILD", "event arms")
    seen: set[str] = set()
    for ev in events:
        if ev["source_sha"] not in (frozen.BASE_SHA, frozen.EXPERIMENT_SHA):
            _reject("V_SOURCE", "event source")
        want_feature = kind != "control" and ev["arm"] != "A"
        if ev["feature"] != want_feature:
            _reject("V_BUILD", "feature flag")
        if ev["binary_sha256"] != arms[ev["arm"]]["binary_sha256"] or ev["binary_bytes"] != arms[ev["arm"]]["binary_bytes"]:
            _reject("V_BINARY", "event digest")
        if ev["source_sha"] != arms[ev["arm"]]["source_sha"]:
            _reject("V_SOURCE", "event arm sha")
        if ev["canonical_source"] != prov["canonical_source_path"]:
            _reject("V_SOURCE", "event path")
        if not any(x in ev["argv"] for x in ("--features",)) and want_feature:
            _reject("V_BUILD", "feature argv")
        build_policy.require_closed_argv(
            {"argv": list(ev["argv"])},
            source_root=Path(prov["canonical_source_path"]),
            target_dir=d / "build" / ev["arm"],
            feature=build_policy.FEATURE_MATRIX["B" if want_feature else "A"],
        )
        seen.add(ev["arm"])
    if seen != kinds:
        _reject("V_BUILD", "duplicate/missing events")
    digests: dict[int, set[str]] = {}
    for arm, info in arms.items():
        for n in p["n_values"]:
            lay = info["indexes"][str(n)]
            if n == 100000 and lay["bytes"] != p["index_100k_committed_sentinel"]:
                _reject("V_INDEX", "100K sentinel")
            digests.setdefault(n, set()).add(lay["digest"])
            actual = os.path.join(d, "indexes", f"{arm}-n{n}")
            if os.path.isdir(actual):
                files = []
                for root, _dirs, names in os.walk(actual):
                    for name in sorted(names):
                        full = os.path.join(root, name)
                        files.append(
                            {
                                "path": os.path.relpath(full, actual).replace(os.sep, "/"),
                                "size": os.path.getsize(full),
                                "sha256": frozen.sf(full),
                            }
                        )
                files.sort(key=lambda x: x["path"])
                if frozen.sh(frozen.cj(files)) != lay["digest"]:
                    _reject("V_INDEX", f"{arm}/n{n} layout")
    for n, values in digests.items():
        if len(values) != 1:
            _reject("V_INDEX", "arm index digests differ")
    plan = frozen.schedule(p, kind, campaign)
    ls = frozen.lanes(p)
    slots = []
    for entry in plan:
        s = frozen.rj(os.path.join(d, "raw/slots", f"slot-{entry['slot']:02d}.json"))
        if s.get("schema") != "pr15i-d3c-slot-v1" or (s["slot"], s["block"], s["position"], s["arm"]) != (
            entry["slot"],
            entry["block"],
            entry["position"],
            entry["arm"],
        ):
            _reject("V_SLOT", "address")
        arm = arms[s["arm"]]
        if s["source_sha"] != arm["source_sha"] or s["binary_sha256"] != arm["binary_sha256"]:
            _reject("V_SLOT", "binary")
        if s["index_digests"] != {str(n): arm["indexes"][str(n)]["digest"] for n in p["n_values"]}:
            _reject("V_SLOT", "index")
        for tag in ("before", "after"):
            rec = s.get(f"contention_{tag}")
            if (
                not isinstance(rec, dict)
                or rec.get("state") not in ("clear", "busy")
                or not isinstance(rec.get("reason_codes"), list)
                or not all(isinstance(x, str) for x in rec["reason_codes"])
            ):
                _reject("V_CONTENTION", f"{tag} probe")
        if s.get("controller_affinity_before") != [host["controller_cpu"]] or s.get("controller_affinity_after") != [
            host["controller_cpu"]
        ]:
            _reject("V_AFFINITY", "controller")
        recs = s["lanes"]
        if [r["id"] for r in recs] != [lane["id"] for lane in ls]:
            _reject("V_SLOT", "lane order")
        for lane, rec in zip(ls, recs):
            exp = frozen.oracle(lane["n"], lane["class"], lane["k"])
            if rec.get("total_hits") != exp["total_hits"] or rec.get("doc_ids") != exp["doc_ids"]:
                _reject("V_ORACLE", lane["id"])
            samples = rec.get("samples_ns")
            if (
                not isinstance(samples, list)
                or len(samples) != 20
                or any((isinstance(x, bool) or not isinstance(x, int) or x <= 0) for x in samples)
            ):
                _reject("V_SAMPLE", lane["id"])
            if rec["summary_ns"]["median"] != sorted(samples)[9]:
                _reject("V_SAMPLE", lane["id"])
            mode = p["arm_modes"].get(s["arm"], "BASE")
            want = (
                None
                if mode == "BASE"
                else f"PR15I_D3C_MODE=v1:{mode}:{p['prefilter_profile'] if mode == 'prefilter' else 'none'}"
            )
            if rec.get("mode_marker") != want:
                _reject("V_MODE", lane["id"])
            if rec.get("affinity_before") != [host["adapter_cpu"]] or rec.get("affinity_after") != [host["adapter_cpu"]]:
                _reject("V_AFFINITY", lane["id"])
            if not isinstance(rec.get("adapter_pid"), int) or rec["adapter_pid"] <= 0:
                _reject("V_AFFINITY", lane["id"])
        slots.append(s)
    bv = frozen.block_values(slots, ls, p["blocks"])
    structural_ok = all(len(x) == 1 for x in digests.values())
    summary = (
        frozen.summary_control(p, bv, ls, p["blocks"], slots)
        if kind == "control"
        else frozen.summary_campaign(p, bv, ls, p["blocks"], campaign, slots, structural_ok)
    )
    actual = frozen.rj(os.path.join(d, "sanitized/summary.json"))
    if frozen.cj(actual) != frozen.cj(summary):
        _reject("V_SUMMARY", "summary mismatch")
    status = "SYNTHETIC_REHEARSAL_ONLY" if synthetic else summary["status"]
    return {
        "schema": VERIFICATION_SCHEMA,
        "verifier": VERIFIER_IDENTITY,
        "campaign": campaign,
        "kind": kind,
        "verification": "PASS",
        "measurement_status": status,
        "build_policy_digest": policy_digest,
        "slots": len(slots),
        "lanes": len(ls) * len(slots),
        "samples": len(ls) * len(slots) * 20,
        "sealed_members": len(seal["files"]),
    }


def verify_series_v2(root: Path, *, expected_policy_digest: str | None = None,
                     source_basis: str = "checkout") -> dict[str, Any]:
    """Verify the control and both treatment campaigns of one current-v2 series."""

    frozen = frozen_verifier()
    p = frozen.load_protocol()
    base = frozen.confined(str(root))
    control = verify_campaign_v2(Path(frozen.confined(os.path.join(base, p["control_name"]))), expected_policy_digest=expected_policy_digest)
    reports = []
    for name in p["campaign_names"]:
        d = os.path.join(base, name)
        if not os.path.isdir(d):
            _reject("V_SERIES", f"missing {name}")
        reports.append(verify_campaign_v2(Path(frozen.confined(d)), expected_policy_digest=expected_policy_digest))
    statuses = [r["measurement_status"] for r in reports]
    manifests = [frozen.rj(os.path.join(frozen.confined(os.path.join(base, name)), "manifest.json")) for name in p["campaign_names"]]
    control_manifest = frozen.rj(os.path.join(frozen.confined(os.path.join(base, p["control_name"])), "manifest.json"))
    common_keys = ("source_base_sha", "protocol_sha256", "prefilter_profile", "host_fingerprint")
    expected = {key: control_manifest.get(key) for key in common_keys}
    if control_manifest.get("kind") != "control" or control_manifest.get("source_experiment_sha") is not None:
        _reject("V_SERIES_PROVENANCE", "control must be BASE-only")
    consistent = all(all(m.get(key) == expected[key] for key in common_keys) for m in manifests)
    if not all(m.get("source_experiment_sha") == frozen.EXPERIMENT_SHA for m in manifests):
        _reject("V_SERIES_PROVENANCE", "four-arm experiment sha differs")
    if not consistent:
        _reject("V_SERIES_PROVENANCE", "campaign provenance differs")
    ok = all(s == "ACQUIRED_VERIFIED" for s in statuses) and control["measurement_status"] == "ACQUIRED_VERIFIED"
    return {
        "schema": "bm09-current-v2-comparison-v1",
        "verifier": VERIFIER_IDENTITY,
        "verification": "PASS"
        if all(r["verification"] == "PASS" for r in reports) and control["verification"] == "PASS"
        else "FAIL",
        "control": control["measurement_status"],
        "campaigns": statuses,
        "full_series": ok,
        "provenance_consistent": consistent,
        "series_provenance": expected,
        "build_policy_digest": expected_policy_digest,
    }


def publish_campaign_v2(campaign_dir: Path, *, evidence_root: Path, expected_policy_digest: str | None = None,
                        source_basis: str = "checkout") -> dict[str, Any]:
    """Write the immutable campaign archive using the current-v2 verifier first."""

    frozen = frozen_verifier()
    d = Path(frozen.validate_dir(str(campaign_dir)))
    manifest = frozen.rj(os.path.join(d, "manifest.json"))
    if frozen.rj(os.path.join(d, "authorization.json")).get("rehearsal_only") or "rehearsal" in str(d).split(os.sep):
        _reject("V2_REHEARSAL_PUBLISH_FORBIDDEN", "synthetic")
    root = os.path.realpath(evidence_root)
    os.makedirs(root, exist_ok=True)
    archive = os.path.join(root, manifest["campaign"] + ".tar.gz")
    sidecar = archive + ".sha256"
    if os.path.exists(archive) or os.path.exists(sidecar):
        _reject("D3C_ARCHIVE_EXISTS", archive)
    report = verify_campaign_v2(d, expected_policy_digest=expected_policy_digest)
    if report.get("verification") != "PASS":
        _reject("V2_VERIFY", "verifier did not PASS")
    if report.get("measurement_status") != "ACQUIRED_VERIFIED":
        _reject("V2_QUALIFICATION", f"status {report.get('measurement_status')} != ACQUIRED_VERIFIED")
    frozen.wj(
        os.path.join(d, "verification.json"),
        {
            "schema": VERIFICATION_SCHEMA,
            "verifier": VERIFIER_IDENTITY,
            "campaign": manifest["campaign"],
            "verification": "PASS",
            "measurement_status": report["measurement_status"],
            "build_policy_digest": expected_policy_digest,
        },
    )
    temporary_archive = archive + ".tmp"
    temporary_sidecar = sidecar + ".tmp"
    if os.path.exists(temporary_archive) or os.path.exists(temporary_sidecar):
        _reject("D3C_ARCHIVE_EXISTS", temporary_archive)
    members = [rel for rel in frozen.archive_members(d) if os.path.isfile(os.path.join(d, rel))]
    try:
        with tarfile.open(temporary_archive, "w:gz") as handle:
            for rel in members:
                info = handle.gettarinfo(os.path.join(d, rel), arcname=rel)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with open(os.path.join(d, rel), "rb") as member:
                    handle.addfile(info, member)
        inventory = {rel: frozen.sf(os.path.join(d, rel)) for rel in members}
        frozen.wj(
            temporary_sidecar,
            {
                "schema": ARCHIVE_SCHEMA,
                "campaign": manifest["campaign"],
                "archive_sha256": frozen.sf(temporary_archive),
                "member_count": len(inventory),
                "members": inventory,
            },
        )
        frozen.validate_archive(temporary_archive, temporary_sidecar, manifest["campaign"], d)
        os.replace(temporary_archive, archive)
        os.replace(temporary_sidecar, sidecar)
    except BaseException:
        for path in (temporary_archive, temporary_sidecar):
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return {"status": "PUBLISHED", "archive_sha256": frozen.sf(archive), "members": len(inventory), "verifier": VERIFIER_IDENTITY}


def require_v2_predecessor(series_root: Path, campaign: str, *, evidence_root: Path, expected_policy_digest: str | None = None) -> dict[str, Any]:
    """Independently re-open a completed predecessor campaign and its archive."""

    frozen = frozen_verifier()
    p = frozen.load_protocol()
    directory = os.path.join(str(series_root), campaign)
    if not os.path.isdir(directory):
        _reject("V2_PREDECESSOR", f"missing {campaign}")
    report = verify_campaign_v2(Path(frozen.confined(directory)), expected_policy_digest=expected_policy_digest)
    if report.get("verification") != "PASS" or report.get("measurement_status") != "ACQUIRED_VERIFIED":
        _reject("V2_PREDECESSOR", f"{campaign} status {report.get('measurement_status')}")
    archive = os.path.join(str(evidence_root), campaign + ".tar.gz")
    frozen.validate_archive(archive, archive + ".sha256", campaign, frozen.confined(directory))
    del p
    return report


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--campaign-dir")
    parser.add_argument("--series-root")
    parser.add_argument("--evidence-root")
    parser.add_argument("--build-policy-digest", required=False, default=None)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.publish:
            if not args.campaign_dir or not args.evidence_root:
                parser.error("publish requires --campaign-dir and --evidence-root")
            print(json.dumps(publish_campaign_v2(Path(args.campaign_dir), evidence_root=Path(args.evidence_root),
                                                 expected_policy_digest=args.build_policy_digest),
                             sort_keys=True, separators=(",", ":")))
            return 0
        if args.campaign_dir:
            print(json.dumps(verify_campaign_v2(Path(args.campaign_dir), expected_policy_digest=args.build_policy_digest),
                             sort_keys=True, separators=(",", ":")))
            return 0
        if args.series_root:
            report = verify_series_v2(Path(args.series_root), expected_policy_digest=args.build_policy_digest)
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
            return 0 if report["full_series"] else 3
        parser.error("provide --campaign-dir or --series-root")
    except V2VerificationError as error:
        print(json.dumps({"schema": VERIFICATION_SCHEMA, "verifier": VERIFIER_IDENTITY, "verification": "FAIL",
                          "reasons": [{"code": error.code, "detail": str(error)}]},
                         sort_keys=True, separators=(",", ":")))
        return 3
    except BenchError as error:
        print(json.dumps({"schema": VERIFICATION_SCHEMA, "verifier": VERIFIER_IDENTITY, "verification": "FAIL",
                          "reasons": [{"code": error.code, "detail": str(error)}]},
                         sort_keys=True, separators=(",", ":")))
        return 3
    return 3


if __name__ == "__main__":  # pragma: no cover - console entry
    raise SystemExit(_main(sys.argv[1:]))
