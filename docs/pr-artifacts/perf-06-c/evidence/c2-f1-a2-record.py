#!/usr/bin/env python3
"""One-task lossless receipt: OUT.json MODE EXPECTED_HEAD -- command argv."""
import base64
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if not __debug__:
    raise SystemExit("Do not run this recorder with -O or PYTHONOPTIMIZE.")

# Import the supplied sibling verifier without generating an untracked .pyc file.
sys.dont_write_bytecode = True
HELPER_PATH = Path(__file__).resolve().with_name("c2-f1-a2-source-freeze.py")
spec = importlib.util.spec_from_file_location("c2_f1_a2_source_freeze", HELPER_PATH)
assert spec is not None and spec.loader is not None
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)
ALLOWED_RED = {freeze.READER, freeze.STORED}


def git(*args):
    return freeze.git(*args)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    out, mode, expected, delimiter, *command = sys.argv[1:]
    assert delimiter == "--" and command
    assert mode in {"red", "pinned"}
    assert re.fullmatch(r"[0-9a-f]{40}", expected)
    root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    assert Path.cwd().resolve() == root
    if mode == "red":
        assert expected == freeze.A2_START, "RED is pinned to the reviewed A2 START"
    destination = Path(out).resolve()
    assert destination.suffix == ".json"
    try:
        relative_output = destination.relative_to(root).as_posix()
    except ValueError:
        assert mode == "pinned", "only pinned terminal receipts may be written outside the checkout"
        receipt_location = "outside-checkout"
    else:
        assert relative_output.startswith(freeze.EVIDENCE_PREFIX)
        receipt_location = "repository-evidence"
    assert not destination.exists(), "never overwrite a receipt"
    destination.parent.mkdir(parents=True, exist_ok=True)

    def identity():
        actual = git("rev-parse", "HEAD").decode().strip()
        assert actual == expected, (actual, expected)
        untracked = freeze.paths(git("ls-files", "--others", "--exclude-standard", "-z"))
        assert all(path.startswith("docs/") for path in untracked), ("untracked source/build input", untracked)
        assert all(freeze.allowed_document(path) or path == freeze.FOREIGN_DOC for path in untracked), ("unapproved untracked document", untracked)
        # Cargo reads these files even when local ignore rules hide them from Git.
        for config in [".cargo/config", ".cargo/config.toml"]:
            if os.path.lexists(root / config):
                tracked = freeze.paths(git("ls-files", "-z", "--", config))
                assert tracked == {config}, ("untracked Cargo configuration, including ignored files", config)
        changed_docs = freeze.paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", expected, "--", "docs/"))
        assert all(freeze.allowed_document(path) for path in changed_docs), ("unapproved document change", changed_docs)
        patch = git("diff", "--no-ext-diff", "--no-textconv", "--binary", expected, "--", *freeze.SOURCE_PATHS)
        changed = freeze.paths(git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", expected, "--", *freeze.SOURCE_PATHS))
        if mode == "pinned":
            assert not patch and not changed, "final QA requires committed, clean source/build inputs"
        else:
            assert changed == ALLOWED_RED, changed
            freeze.compare_red(
                freeze.blob(expected, freeze.READER),
                (root / freeze.READER).read_bytes().decode("utf-8"),
                freeze.blob(expected, freeze.STORED),
                (root / freeze.STORED).read_bytes().decode("utf-8"),
            )
        helper_hashes = {}
        for helper in [Path(__file__).resolve(), HELPER_PATH]:
            path = helper.relative_to(root).as_posix()
            assert path.startswith(freeze.EVIDENCE_PREFIX), ("helper outside prescribed artifacts", path)
            raw = helper.read_bytes()
            if mode == "pinned":
                assert freeze.blob_bytes(expected, path) == raw, ("uncommitted helper change", path)
            helper_hashes[path] = hashlib.sha256(raw).hexdigest()
        foreign = root / freeze.FOREIGN_DOC
        assert not foreign.is_symlink(), "unexpected symlink at the known foreign artifact"
        foreign_hash = hashlib.sha256(foreign.read_bytes()).hexdigest() if foreign.exists() else None
        return {"head": actual, "patch": patch, "helper_hashes": helper_hashes, "foreign_hash": foreign_hash}

    before = identity()
    env = os.environ.copy()
    removed = ["QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE", "RUST_TEST_THREADS"]
    for name in removed:
        env.pop(name, None)
    started = stamp()
    launch_error = None
    try:
        run = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        raw, command_exit = run.stdout, run.returncode
    except OSError as error:
        raw, command_exit, launch_error = b"", 127, str(error)
    ended = stamp()
    after = None
    identity_error = None
    try:
        after = identity()
        valid = after == before
        if not valid:
            identity_error = "source, helper or known foreign artifact changed during command"
    except (AssertionError, OSError, ValueError, subprocess.CalledProcessError) as error:
        valid, identity_error = False, str(error)
    payload = {
        "schema": "quervant-perf06-c2-f1-a2-receipt-v1",
        "mode": mode,
        "receipt_location": receipt_location,
        "command": command,
        "cwd": str(root),
        "source_commit": before["head"],
        "source_commit_after": after["head"] if after is not None else None,
        "source_patch_sha256": hashlib.sha256(before["patch"]).hexdigest(),
        "source_patch_base64": base64.b64encode(before["patch"]).decode("ascii"),
        "helper_scripts_sha256": before["helper_hashes"],
        "known_foreign_artifact_sha256_before": before["foreign_hash"],
        "known_foreign_artifact_sha256_after": after["foreign_hash"] if after is not None else None,
        "environment_keys_removed": removed,
        "started_utc": started,
        "ended_utc": ended,
        "command_exit_code": command_exit,
        "launch_error": launch_error,
        "source_identity_valid": valid,
        "source_identity_error": identity_error,
        "combined_output_encoding": "base64",
        "combined_output_sha256": hashlib.sha256(raw).hexdigest(),
        "combined_output_base64": base64.b64encode(raw).decode("ascii"),
    }
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
    print(json.dumps({"receipt": str(destination), "command_exit_code": command_exit, "source_identity_valid": valid}))
    sys.exit(command_exit if valid else 125)


if __name__ == "__main__":
    main()
