"""``quervant-bench`` command-line interface.

BM-01 operational surface is intentionally tiny:

* ``inspect`` validates a declared synthetic experiment and prints one canonical
  ``outcome.v1`` JSON document to stdout;
* ``--help`` and ``--version`` are safe;
* ``run`` is unconditionally prohibited and fails *before* opening a protocol,
  spawning a process, creating an output directory or timing anything;
* ``validate``/``analyze``/``verify``/``accept``/``report`` are typed
  ``BM_NOT_IMPLEMENTED`` placeholders owned by later BM milestones.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .config import contracts
from .config.codec import canonical_document_bytes
from .config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_INTERNAL_ERROR,
    BM_NOT_IMPLEMENTED,
    BM_OK,
    BM_USAGE,
    BenchError,
    bounded_message,
    internal_error,
)

PROG = "quervant-bench"
RESERVED_VERBS = ("validate", "analyze", "verify", "accept", "report")


class _Parser(argparse.ArgumentParser):
    """Argument parser that raises typed usage errors instead of exiting."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise BenchError(BM_USAGE, message)


def _experiments_root() -> Path:
    """Infer ``benchmarks/experiments`` from this module's location, not cwd."""

    return Path(__file__).resolve().parents[2] / "benchmarks" / "experiments"


def build_parser() -> argparse.ArgumentParser:
    """Build the frozen BM-01 verb/argument surface."""

    parser = _Parser(
        prog=PROG,
        description=(
            "Quervant benchmarking contract tool (v0.1-bench). Only 'inspect' "
            "operates; real benchmark acquisition is prohibited until BM-09."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(
        dest="verb", required=True, parser_class=_Parser
    )

    inspect = subparsers.add_parser(
        "inspect",
        help="validate a declared synthetic experiment and print its contract summary",
    )
    inspect.add_argument("--experiment", required=True, metavar="<semantic-id>")
    inspect.add_argument("--format", choices=("json",), default="json")

    validate = subparsers.add_parser(
        "validate", help="reserved: validate a run's evidence (not implemented)"
    )
    validate.add_argument("--run", required=True, metavar="<run-uuid>")
    validate.add_argument("--offline", action="store_true")

    run = subparsers.add_parser(
        "run", help="prohibited in BM-01: real acquisition is reserved for BM-09"
    )
    run.add_argument("--experiment", required=True, metavar="<semantic-id>")
    run.add_argument("--protocol", required=True, metavar="<relative-path>")
    run.add_argument("--out", required=True, metavar="<new-path>")

    for verb, help_text in (
        ("analyze", "reserved: derive statistics (not implemented)"),
        ("verify", "reserved: independent verification (not implemented)"),
        ("accept", "reserved: acceptance gates (not implemented)"),
        ("report", "reserved: normalized reporting (not implemented)"),
    ):
        command = subparsers.add_parser(verb, help=help_text)
        command.add_argument("--run", required=True, metavar="<run-uuid>")
        command.add_argument("--offline", action="store_true")

    return parser


def _write(stream: Any, document: Any) -> None:
    stream.write(canonical_document_bytes(document).decode("utf-8"))
    stream.flush()


def _emit_error(error: BenchError) -> None:
    data: dict[str, Any] = {"kind": "error-detail", "reason": error.category}
    if error.field_path:
        data["field_path"] = error.field_path
    if error.reference:
        data["reference"] = error.reference
    outcome = {
        "kind": "outcome",
        "schema_version": 1,
        "status": error.status,
        "code": error.code,
        "message": bounded_message(error.message),
        "data": data,
    }
    _write(sys.stderr, outcome)


def _run_inspect(experiment: str) -> int:
    bundle = contracts.load_experiment_bundle(experiment, _experiments_root())
    summary = contracts.build_inspect_summary(bundle)
    outcome = contracts.build_outcome(
        "ok",
        BM_OK,
        f"validated synthetic contract declaration for {bundle.experiment.experiment_id}",
        summary,
    )
    _write(sys.stdout, outcome)
    return 0


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch a parsed invocation without touching acquisition paths."""

    verb = args.verb
    if verb == "run":
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            "real benchmark acquisition is prohibited in BM-01; "
            "BM-09 owns the first real full-scale campaign",
        )
    if verb in RESERVED_VERBS:
        if getattr(args, "offline", False):
            from .migrations import offline

            _write(sys.stdout, offline.dispatch_stage(verb, args.run))
            return 0
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            f"'{verb}' is reserved and unavailable until a later BM milestone",
        )
    if verb == "inspect":
        return _run_inspect(args.experiment)
    raise BenchError(BM_USAGE, f"unknown verb: {verb!r}")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns a stable process exit status."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        parser = build_parser()
        args = parser.parse_args(arguments)
        return dispatch(args)
    except BenchError as error:
        _emit_error(error)
        return error.exit_code
    except SystemExit as exit_signal:
        code = exit_signal.code
        return int(code) if isinstance(code, int) else 0
    except KeyboardInterrupt:  # pragma: no cover - operator interruption
        _emit_error(BenchError(BM_INTERNAL_ERROR, "interrupted"))
        return 70
    except Exception:  # noqa: BLE001 - never leak a traceback in structured output
        error = internal_error()
        _emit_error(error)
        return error.exit_code
