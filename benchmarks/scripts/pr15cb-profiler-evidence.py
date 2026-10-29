#!/usr/bin/env python3
"""PR 15C-B profiler-evidence record writer and verifier.

The PR 15B trial validator requires a non-empty ``profiler_evidence`` string
whenever ``profiler_status`` is ``AVAILABLE``. This helper produces and then
independently re-verifies that record from **real** profiler output so
``run-pr15b.sh`` can pass it on. It is deliberately a separate, testable unit:
the frozen validator is not touched, and the runner only ever hands over a path
that this helper has already re-validated.

Subcommands
-----------
``write``
    Hash a genuinely captured artifact and atomically write
    ``<trial>/profiler/evidence.json``.
``verify``
    Re-open the record, re-stat and re-hash the artifact, and reject anything
    absent, symlinked, empty, mis-sized, mis-digested, malformed or pointing
    outside the trial's own profiler directory.

No field is invented: ``capture_exit_code`` is always ``0`` because this helper is
only invoked after the capture process exited successfully, and the artifact
identity (size + SHA-256) is always measured from the bytes on disk.

Exit codes: ``0`` accepted, ``1`` rejected, ``64`` CLI usage.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

SCHEMA = "quervant-pr15cb-profiler-evidence-v1"
EVIDENCE_DIR_NAME = "profiler"
EVIDENCE_FILE_NAME = "evidence.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REQUIRED_KEYS = frozenset(
    {
        "schema",
        "tool",
        "version",
        "workload",
        "artifact_path",
        "artifact_size_bytes",
        "artifact_sha256",
        "capture_command",
        "capture_exit_code",
    }
)


class EvidenceError(Exception):
    """Rejection of an untrustworthy evidence record."""


def digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def check_relative(relative, label):
    require(isinstance(relative, str) and relative, f"{label} is not a relative path")
    require(not os.path.isabs(relative), f"{label} must not be absolute: {relative!r}")
    require(
        os.path.normpath(relative).startswith(EVIDENCE_DIR_NAME + "/"),
        f"{label} must live under {EVIDENCE_DIR_NAME}/: {relative!r}",
    )


def check_artifact(trial, relative, label):
    check_relative(relative, label)
    path = trial / relative
    require(not path.is_symlink(), f"{label} {relative} is a symlink")
    require(path.is_file(), f"{label} {relative} is not a regular file")
    require(path.stat().st_size > 0, f"{label} {relative} is empty")
    return path


def build_record(trial, tool, version, workload, artifact, auxiliary, command):
    for name, value in (("tool", tool), ("version", version), ("workload", workload)):
        require(isinstance(value, str) and value.strip(), f"{name} must be non-empty")
    require(isinstance(command, str) and command.strip(), "command must be non-empty")
    artifact_path = check_artifact(trial, artifact, "artifact")
    record = {
        "schema": SCHEMA,
        "tool": tool,
        "version": version,
        "workload": workload,
        "artifact_path": artifact,
        "artifact_size_bytes": artifact_path.stat().st_size,
        "artifact_sha256": digest(artifact_path),
        "capture_command": command,
        "capture_exit_code": 0,
    }
    if auxiliary:
        auxiliary_path = check_artifact(trial, auxiliary, "auxiliary artifact")
        record["auxiliary_artifact_path"] = auxiliary
        record["auxiliary_artifact_size_bytes"] = auxiliary_path.stat().st_size
        record["auxiliary_artifact_sha256"] = digest(auxiliary_path)
    return record


def cmd_write(args):
    trial = pathlib.Path(args.trial).resolve()
    require(trial.is_dir(), f"trial directory does not exist: {args.trial}")
    record = build_record(
        trial, args.tool, args.version, args.workload, args.artifact, args.auxiliary, args.command
    )
    directory = trial / EVIDENCE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / EVIDENCE_FILE_NAME
    tmp = directory / (EVIDENCE_FILE_NAME + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    print(target)
    return 0


def cmd_verify(args):
    trial = pathlib.Path(args.trial).resolve()
    require(trial.is_dir(), f"trial directory does not exist: {args.trial}")
    record_path = trial / EVIDENCE_DIR_NAME / EVIDENCE_FILE_NAME
    require(not record_path.is_symlink(), "evidence.json is a symlink")
    require(record_path.is_file(), "evidence.json is absent or not a regular file")
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - any parse failure invalidates the record
        raise EvidenceError(f"evidence.json is unreadable: {error}") from error
    require(isinstance(data, dict), "evidence.json is not a JSON object")
    missing = sorted(REQUIRED_KEYS - set(data))
    require(not missing, f"evidence.json is missing keys: {missing}")
    require(data["schema"] == SCHEMA, f"unexpected evidence schema {data['schema']!r}")
    exit_code = data["capture_exit_code"]
    require(
        isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code == 0,
        f"capture_exit_code must be 0, got {exit_code!r}",
    )
    require(data["workload"] == args.workload, f"unexpected evidence workload {data['workload']!r}")
    for key in ("tool", "version", "capture_command"):
        require(
            isinstance(data[key], str) and data[key].strip(),
            f"evidence field {key} must be a non-empty string",
        )
    size = data["artifact_size_bytes"]
    require(
        isinstance(size, int) and not isinstance(size, bool) and size > 0,
        f"artifact_size_bytes must be a positive integer, got {size!r}",
    )
    sha = data["artifact_sha256"]
    require(
        isinstance(sha, str) and SHA256_RE.fullmatch(sha),
        f"artifact_sha256 must be 64 lowercase hex characters, got {sha!r}",
    )
    relative = data["artifact_path"]
    artifact = check_artifact(trial, relative, "artifact")
    require(
        artifact.stat().st_size == size,
        f"artifact {relative} size {artifact.stat().st_size} does not match recorded {size}",
    )
    require(
        digest(artifact) == sha,
        f"artifact {relative} sha256 does not match the recorded digest",
    )
    auxiliary = data.get("auxiliary_artifact_path")
    if auxiliary:
        auxiliary_path = check_artifact(trial, auxiliary, "auxiliary artifact")
        size_key = data.get("auxiliary_artifact_size_bytes")
        sha_key = data.get("auxiliary_artifact_sha256")
        require(
            isinstance(size_key, int) and size_key > 0,
            "auxiliary_artifact_size_bytes must be a positive integer",
        )
        require(
            auxiliary_path.stat().st_size == size_key,
            f"auxiliary artifact {auxiliary} size does not match the recorded size",
        )
        require(
            isinstance(sha_key, str) and SHA256_RE.fullmatch(sha_key),
            "auxiliary_artifact_sha256 must be 64 lowercase hex characters",
        )
        require(
            digest(auxiliary_path) == sha_key,
            f"auxiliary artifact {auxiliary} sha256 does not match the recorded digest",
        )
    print(
        "tool={} version={!r} artifact={} size={} sha256={}".format(
            data["tool"], data["version"], relative, size, sha[:12]
        )
    )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Write or verify a PR 15C-B profiler-evidence record."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    write = subparsers.add_parser("write", help="hash a real artifact and write evidence.json")
    write.add_argument("--trial", required=True)
    write.add_argument("--tool", required=True)
    write.add_argument("--version", required=True)
    write.add_argument("--workload", required=True)
    write.add_argument("--artifact", required=True, help="artifact path relative to the trial dir")
    write.add_argument("--auxiliary", default=None, help="auxiliary path relative to the trial dir")
    write.add_argument("--command", required=True)

    verify = subparsers.add_parser("verify", help="re-validate an existing evidence.json")
    verify.add_argument("--trial", required=True)
    verify.add_argument("--workload", default="absent")

    args = parser.parse_args()
    try:
        if args.subcommand == "write":
            return cmd_write(args)
        return cmd_verify(args)
    except EvidenceError as error:
        print(f"REJECT {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
