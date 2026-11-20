"""Validated operator commands with explicit synthetic/official scope routing.

Unconfigured acquisition remains prohibited before any effects. A closed local
operation configuration selects the supported workflow; it cannot supply an
authorization, readiness or acceptance PASS by assertion. Explicitly offline
commands retain their existing read-only synthetic behaviour.
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
    """Preserve the BM-01 surface and add explicit configured operation inputs."""

    parser = _Parser(
        prog=PROG,
        description=(
            "Quervant benchmarking operator (v0.1-bench). Real acquisition "
            "requires a closed --config and independently verified G0 approval."
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
        help="inspect a synthetic declaration or an unapproved official candidate",
    )
    inspect.add_argument("--experiment", required=True, metavar="<semantic-id>")
    inspect.add_argument("--format", choices=("json",), default="json")

    validate = subparsers.add_parser(
        "validate", help="validate configured run evidence or an explicit offline view"
    )
    validate.add_argument("--run", required=True, metavar="<run-uuid>")
    validate.add_argument("--offline", action="store_true")
    validate.add_argument("--config", metavar="<operation.json>")

    run = subparsers.add_parser(
        "run", help="execute a configured synthetic or independently authorized official study"
    )
    run.add_argument("--experiment", required=True, metavar="<semantic-id>")
    run.add_argument("--protocol", required=True, metavar="<relative-path>")
    run.add_argument("--out", required=True, metavar="<new-path>")
    run.add_argument("--config", metavar="<operation.json>")

    prepare = subparsers.add_parser(
        "prepare", help="prepare official corpus/build inputs without timing or self-approval"
    )
    prepare.add_argument("--experiment", required=True, metavar="<semantic-id>")
    prepare.add_argument("--protocol", required=True, metavar="<relative-path>")
    prepare.add_argument("--out", required=True, metavar="<new-path>")
    prepare.add_argument("--config", required=True, metavar="<operation.json>")

    for verb, help_text in (
        ("analyze", "derive statistics for a configured run or open an offline view"),
        ("verify", "independently verify a configured run or open an offline view"),
        ("accept", "apply configured acceptance gates or open an offline view"),
        ("report", "report a configured run or open an offline view"),
    ):
        command = subparsers.add_parser(verb, help=help_text)
        command.add_argument("--run", required=True, metavar="<run-uuid>")
        command.add_argument("--offline", action="store_true")
        command.add_argument("--config", metavar="<operation.json>")

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
    from .official.protocols import (
        OFFICIAL_STUDIES,
        read_canonical_json,
        template_path,
        validate_template,
        verify_backend_protocol,
    )

    if experiment in OFFICIAL_STUDIES:
        from .config.codec import content_digest

        template = validate_template(read_canonical_json(template_path(experiment)))
        backend = verify_backend_protocol(template)
        outcome = contracts.build_outcome(
            "ok", BM_OK, "validated official candidate declaration; independent approval is still required",
            {
                "kind": "official-experiment-inspection",
                "schema_version": 1,
                "experiment_id": experiment,
                "evidence_origin": "real",
                "qualification_scope": "official",
                "template_digest": content_digest(template),
                "backend_protocol_digest": backend["raw_digest"],
                "authorization_status": "INDEPENDENT_G0_REQUIRED",
                "operation_config_required": True,
            },
        )
        _write(sys.stdout, outcome)
        return 0
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
    """Dispatch only explicit configured operations; retain unconfigured guards."""

    verb = args.verb
    config = getattr(args, "config", None)
    if config is not None and not config.strip():
        raise BenchError(BM_USAGE, "--config must name a non-empty operation file", field_path="config")
    if getattr(args, "offline", False) and config is not None:
        raise BenchError(BM_USAGE, "--offline and --config are mutually exclusive", field_path="config")
    if verb == "prepare":
        from .execution.operator import dispatch_prepare

        _write(sys.stdout, dispatch_prepare(args.experiment, Path(args.protocol), Path(args.out), Path(config)))
        return 0
    if verb == "run":
        if config is not None:
            from .execution.operator import dispatch_run

            _write(sys.stdout, dispatch_run(args.experiment, Path(args.protocol), Path(args.out), Path(config)))
            return 0
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            "benchmark acquisition requires an explicit operation configuration; "
            "official acquisition additionally requires independent G0 approval",
        )
    if verb in RESERVED_VERBS:
        if config is not None:
            from .execution.operator import dispatch_stage

            _write(sys.stdout, dispatch_stage(verb, args.run, Path(config)))
            return 0
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
    parsing = True
    try:
        parser = build_parser()
        args = parser.parse_args(arguments)
        parsing = False
        return dispatch(args)
    except BenchError as error:
        _emit_error(error)
        return error.exit_code
    except SystemExit as exit_signal:
        code = exit_signal.code
        if parsing and isinstance(code, int):
            return int(code)
        # Only parser help/version may exit successfully. Legacy backend helpers
        # can use SystemExit(text) or an early integer exit: neither completes an
        # operation or supplies a validated result. Keep diagnostics private.
        error = internal_error()
        _emit_error(error)
        return error.exit_code
    except KeyboardInterrupt:  # pragma: no cover - operator interruption
        _emit_error(BenchError(BM_INTERNAL_ERROR, "interrupted"))
        return 70
    except Exception:  # noqa: BLE001 - never leak a traceback in structured output
        error = internal_error()
        _emit_error(error)
        return error.exit_code
