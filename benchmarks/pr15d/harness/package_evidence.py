#!/usr/bin/env python3
"""Deterministic, reviewable PR15D evidence packager.

Standard library only. Packages one completed run's raw JSON evidence into a
byte-reproducible ZIP so an independent reviewer can re-run validation and
aggregation from the original manifests.

Design constraints (fixed by the PR 15D-B fixup plan):

* only declared JSON evidence is included - never indexes, corpus TSVs,
  binaries, Gradle caches, source checkouts, credentials or process dumps;
* the archive is deterministic: ``ZIP_STORED``, a fixed per-entry timestamp and
  forward-slash relative names, so re-running on unchanged inputs produces
  byte-identical output;
* symlinks are never followed and no path may escape the run directory;
* a completed, triple-trial, three-engine, QUALIFIED run is required;
* a supplied resource-probe report is included, and is required when
  ``--require-resources`` is set - a missing mandatory metric is a BLOCKED
  result, never a silent omission;
* sensitive content is *reported*, never silently rewritten: rewriting a raw
  file would invalidate its digest and the reviewer's re-derivation.

This tool never uploads anything. Publication is a human decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile

SCHEMA_MANIFEST = "pr15d-evidence-manifest-v1"
REQUIRED_ENGINES = ("quervant", "tantivy", "lucene")
REQUIRED_TRIALS = (1, 2, 3)
REQUIRED_SIZES = (10000, 100000)
CONTENTION_PHASES = ("pre", "post", "final")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
DISPOSITION_CLEAN = "UNPUBLISHED_PENDING_REVIEW"
DISPOSITION_SENSITIVE = "BLOCKED_SENSITIVE_CONTENT"

SENSITIVE_RULES = (
    ("absolute_home_path", ("/home/", "/Users/", "/root/")),
    ("windows_path", ("C:\\", "C:/")),
    ("credential_marker", ("Bearer ", "password", "passwd", "secret", "AKIA", "api_key")),
)

REPRODUCTION_STEPS = (
    "1. Regenerate the frozen corpus with `python3 benchmarks/pr15d/corpus/generate.py --out <dir>`.",
    "2. Recreate the run layout by placing these JSON members under `target/pr15d/runs/<run_id>/`.",
    "3. If `run.json` records an absolute `corpus_dir` from another host, point it at step 1's "
    "directory in a clearly labelled temporary reconstruction; the archived bytes are unchanged.",
    "4. Run `python3 benchmarks/pr15d/harness/validate.py --run <run_dir> --out <run_dir>/validation.json`.",
    "5. Run `python3 benchmarks/pr15d/harness/aggregate.py --run <run_dir> --out <json> --md <md>` "
    "and compare the aggregate SHA-256 with the published report.",
)


class PackageError(Exception):
    """A typed, precise packaging rejection."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str, label: str) -> dict:
    try:
        with open(path, "rb") as handle:
            payload = json.loads(handle.read().decode("utf-8"))
    except FileNotFoundError as error:
        raise PackageError("missing_file", f"{label}: {path}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackageError("malformed_json", f"{label}: {error}") from error
    if not isinstance(payload, dict):
        raise PackageError("malformed_json", f"{label}: expected an object")
    return payload


def _require_regular_file(root: str, relative: str) -> str:
    """Resolve a member inside ``root`` without following symlinks outside it."""
    if os.path.isabs(relative):
        raise PackageError("unsafe_path", f"absolute member path: {relative}")
    normalised = os.path.normpath(relative)
    if normalised.startswith(".."):
        raise PackageError("unsafe_path", f"escaping member path: {relative}")
    full = os.path.join(root, normalised)
    if os.path.islink(full):
        raise PackageError("symlink_member", f"refusing to follow symlink: {relative}")
    real_root = os.path.realpath(root)
    real_full = os.path.realpath(full)
    if os.path.commonpath([real_root, real_full]) != real_root:
        raise PackageError("unsafe_path", f"member escapes the run directory: {relative}")
    if not os.path.isfile(real_full):
        raise PackageError("missing_file", f"required evidence is missing: {relative}")
    return real_full


def required_members(run_dir: str, *, require_resources: bool) -> list[str]:
    """Return the deterministic, sorted member list for one completed run."""
    run_record = _read_json(os.path.join(run_dir, "run.json"), "run.json")
    if run_record.get("status") != "complete":
        raise PackageError(
            "run_incomplete", f"run.json status is {run_record.get('status')!r}"
        )
    if run_record.get("qualified") is not True:
        raise PackageError("run_unqualified", "run.json is not qualified")
    if run_record.get("trials") != len(REQUIRED_TRIALS):
        raise PackageError("trial_count", f"run.json trials={run_record.get('trials')!r}")

    validation = _read_json(os.path.join(run_dir, "validation.json"), "validation.json")
    if validation.get("status") != "QUALIFIED":
        raise PackageError(
            "validation_not_qualified",
            f"validation.json status is {validation.get('status')!r}",
        )

    members = ["run.json", "validation.json"]
    seen: dict[str, str] = {}
    for trial in REQUIRED_TRIALS:
        for engine in REQUIRED_ENGINES:
            relative = f"trials/trial-{trial}/{engine}.json"
            manifest = _read_json(os.path.join(run_dir, relative), relative)
            if manifest.get("trial") != trial or manifest.get("engine") != engine:
                raise PackageError("trial_identity", f"{relative} is mislabelled")
            if manifest.get("qualified") is not True:
                raise PackageError("trial_unqualified", relative)
            if relative in seen:
                raise PackageError("duplicate_member", relative)
            seen[relative] = manifest.get("source_sha") or ""
            members.append(relative)
            for entry in manifest.get("contention", []):
                phase = entry.get("phase")
                size = entry.get("n")
                if phase not in CONTENTION_PHASES or size not in REQUIRED_SIZES:
                    raise PackageError(
                        "contention_topology", f"{relative}: {phase!r}/{size!r}"
                    )
                path = f"contention/trial-{trial}/{engine}/n{size}-{phase}.json"
                if path not in members:
                    members.append(path)

    sources = {value for value in seen.values() if value}
    if len(sources) != 1:
        raise PackageError("source_sha_inconsistent", f"{sorted(sources)}")

    resource = os.path.join(run_dir, "resource-probe.json")
    if os.path.exists(resource):
        members.append("resource-probe.json")
    elif require_resources:
        raise PackageError(
            "resources_missing",
            "resource-probe.json is required but absent; the CPU/RSS gate is BLOCKED",
        )

    for relative in members:
        _require_regular_file(run_dir, relative)
    return sorted(set(members))


def scan_sensitive(run_dir: str, members: list[str]) -> list[dict]:
    """Report (never rewrite) sensitive content in JSON members."""
    findings: list[dict] = []
    hostname = os.uname().nodename if hasattr(os, "uname") else ""
    for relative in members:
        if not relative.endswith(".json"):
            continue
        with open(os.path.join(run_dir, relative), "rb") as handle:
            text = handle.read().decode("utf-8", errors="replace")
        for rule, needles in SENSITIVE_RULES:
            hits = sum(text.count(needle) for needle in needles)
            if hits:
                findings.append({"path": relative, "rule": rule, "occurrences": hits})
        if hostname and len(hostname) > 3 and hostname in text:
            findings.append(
                {"path": relative, "rule": "hostname", "occurrences": text.count(hostname)}
            )
    return findings


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _archive_entries(
    run_dir: str, members: list[str], *, run_id: str, source_sha: str
) -> list[tuple[str, bytes]]:
    """Build the full, sorted archive member list.

    ``SHA256SUMS`` covers every other member (generated files included) and never
    the ZIP itself.
    """
    entries: list[tuple[str, bytes]] = []
    for relative in sorted(members):
        with open(os.path.join(run_dir, relative), "rb") as handle:
            entries.append((relative, handle.read()))
    entries.append(("README.md", _readme_bytes(run_id, source_sha)))
    entries.sort(key=lambda item: item[0])
    sums = "".join(
        f"{_sha256_bytes(payload)}  {name}\n" for name, payload in entries
    ).encode("utf-8")
    entries.append(("SHA256SUMS", sums))
    entries.sort(key=lambda item: item[0])
    return entries


def write_archive(entries: list[tuple[str, bytes]], out_path: str) -> None:
    """Write a deterministic ZIP of already-collected ``entries``."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    temporary = out_path + ".tmp"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
    os.replace(temporary, out_path)


def _readme_bytes(run_id: str, source_sha: str) -> bytes:
    lines = [
        f"# PR 15D-B evidence package — run {run_id}",
        "",
        f"Measurement source SHA: `{source_sha}`",
        "",
        "This archive contains raw JSON evidence only. It contains no indexes,",
        "corpus TSVs, binaries, Gradle caches, source checkouts or credentials.",
        "",
        "## Reproduction",
        "",
    ]
    lines.extend(f"- {step}" for step in REPRODUCTION_STEPS)
    lines += [
        "",
        "`SHA256SUMS` lists every other member by name; verify it before use.",
        "",
    ]
    return ("\n".join(lines)).encode("utf-8")


def package(run_dir: str, out_path: str, manifest_path: str, *, require_resources: bool = False) -> dict:
    run_dir = os.path.abspath(run_dir)
    if not os.path.isdir(run_dir):
        raise PackageError("missing_run", run_dir)
    run_record = _read_json(os.path.join(run_dir, "run.json"), "run.json")
    members = required_members(run_dir, require_resources=require_resources)
    findings = scan_sensitive(run_dir, members)

    run_id = run_record.get("run_id") or os.path.basename(run_dir)
    source_sha = run_record.get("source_sha") or ""
    entries = _archive_entries(run_dir, members, run_id=run_id, source_sha=source_sha)
    write_archive(entries, out_path)

    raw_manifests = []
    contention_records = []
    for relative in members:
        full = os.path.join(run_dir, relative)
        entry = {
            "path": relative,
            "sha256": _sha256_file(full),
            "bytes": os.path.getsize(full),
        }
        if relative.startswith("trials/"):
            raw_manifests.append(entry)
        elif relative.startswith("contention/"):
            contention_records.append(entry)

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "run_id": run_id,
        "source_sha": source_sha,
        "host_fingerprint": run_record.get("host_fingerprint"),
        "workload": run_record.get("workload"),
        "trials": len(REQUIRED_TRIALS),
        "engines": list(REQUIRED_ENGINES),
        "corpus_manifest_sha256": run_record.get("corpus_manifest_sha256"),
        "validation": next(
            (e for e in _entries(run_dir, members) if e["path"] == "validation.json"), None
        ),
        "resources": next(
            (e for e in _entries(run_dir, members) if e["path"] == "resource-probe.json"),
            None,
        ),
        "raw_manifests": sorted(raw_manifests, key=lambda entry: entry["path"]),
        "contention_records": sorted(
            contention_records, key=lambda entry: entry["path"]
        ),
        "members": [name for name, _ in entries],
        "package": {
            "path": os.path.abspath(out_path),
            "sha256": _sha256_file(out_path),
            "bytes": os.path.getsize(out_path),
        },
        "sensitive_findings": findings,
        "disposition": DISPOSITION_SENSITIVE if findings else DISPOSITION_CLEAN,
        "reviewer_reproduction": list(REPRODUCTION_STEPS),
        "publication_note": (
            "This manifest is not proof that a reviewer received the raw files. Hand over the "
            "verified archive (or an approved private transfer) and record that reference."
        ),
    }
    with open(manifest_path, "wb") as handle:
        handle.write(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
            + b"\n"
        )
    return manifest


def _entries(run_dir: str, members: list[str]) -> list[dict]:
    result = []
    for relative in members:
        full = os.path.join(run_dir, relative)
        result.append(
            {
                "path": relative,
                "sha256": _sha256_file(full),
                "bytes": os.path.getsize(full),
            }
        )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Package PR15D run evidence deterministically.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--require-resources",
        action="store_true",
        help="fail closed when the resource-probe report is missing",
    )
    args = parser.parse_args(argv)
    try:
        manifest = package(
            args.run, args.out, args.manifest, require_resources=args.require_resources
        )
    except PackageError as error:
        if error.code == "resources_missing":
            print(f"BLOCKED (resources): {error.detail}", file=sys.stderr)
            return 3
        print(f"PACKAGE REJECTED: {error.code}: {error.detail}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": manifest["disposition"],
                "package_sha256": manifest["package"]["sha256"],
                "package_bytes": manifest["package"]["bytes"],
                "members": len(manifest["members"]),
                "sensitive_findings": len(manifest["sensitive_findings"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
