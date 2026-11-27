import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess as sp
import sys


def run_git(*args):
    return sp.check_output(["git", *args], stderr=sp.STDOUT)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def identity():
    return {
        "head": run_git("rev-parse", "HEAD").decode().strip(),
        "tree": run_git("rev-parse", "HEAD^{tree}").decode().strip(),
        "index_tree": run_git("write-tree").decode().strip(),
        "tracked_status_b64": base64.b64encode(
            run_git("status", "--porcelain=v1", "-z", "--untracked-files=no")
        ).decode("ascii"),
    }


def main():
    if len(sys.argv) < 5:
        raise SystemExit("record.py OUTPUT EXPECTED_COMMIT LABEL COMMAND [ARGS...]")
    out = Path(sys.argv[1])
    if not out.is_absolute() or out.exists():
        raise SystemExit("receipt path must be absolute and new")
    expected = sys.argv[2]
    label = sys.argv[3]
    argv = sys.argv[4:]
    env = os.environ.copy()
    removed = ["QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE"]
    for name in removed:
        env.pop(name, None)
    before = identity()
    if before["head"] != expected or before["tracked_status_b64"] or before["tree"] != before["index_tree"]:
        raise SystemExit("source admission failed before execution")
    start = utc()
    result = sp.run(argv, stdout=sp.PIPE, stderr=sp.STDOUT, env=env, check=False)
    end = utc()
    after = identity()
    raw = result.stdout
    valid = before == after
    receipt = {
        "schema": "quervant-perf06-c3-receipt-v1",
        "label": label,
        "cwd": os.getcwd(),
        "argv": argv,
        "removed_env_names": removed,
        "started_utc": start,
        "ended_utc": end,
        "expected_commit": expected,
        "before": before,
        "after": after,
        "source_identity_valid": valid,
        "command_exit_code": result.returncode,
        "combined_output_size": len(raw),
        "combined_output_sha256": hashlib.sha256(raw).hexdigest(),
        "combined_output_base64": base64.b64encode(raw).decode("ascii"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    sys.stdout.buffer.write(raw)
    return result.returncode if valid else 125


if __name__ == "__main__":
    sys.exit(main())
