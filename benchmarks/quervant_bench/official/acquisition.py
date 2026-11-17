"""Typed, invocation-restricted wrappers around the unmodified legacy backends.

No official code re-implements a timing loop. Acquisition only:

* checks a verified :class:`official.protocols.OfficialFreeze`;
* checks an explicit lifecycle transition and that no output path is reused;
* launches the *named* legacy CLI with explicit ``argv``, ``shell=False``, a
  sanitized environment and the backend timeout approved in the design template;
* preserves every failure record and never retries, repairs or deletes evidence.

The wrappers are read/invoke only: the historical backends keep their own
``protocol_v3r3.json``, T6 freeze requirements, predecessor checks and outputs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..evidence.paths import require_safe_root, validate_relative_member
from ..evidence.provenance import repository_root
from ..qualification.contracts import require_closed
from .authorization import (
    VerifiedOfficialAuthorization,
    require_verified_official_authorization,
)
from .protocols import (
    D3C_CAMPAIGN_NAMES,
    D3C_CONTROL_NAME,
    STUDY_CROSS_ENGINE,
    STUDY_RETAINED_KEY,
    OfficialFreeze,
    require_freeze,
)

MAX_CAPTURE_BYTES = 65_536
STATE_SCHEMA = "official-acquisition-state-v1"

D3C_RUNNER = "benchmarks/pr15i_d3_c/run.py"
D3C_VERIFIER = "benchmarks/pr15i_d3_c/verify.py"
D3C_T6_RECEIPT = "target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json"
D3C_EVIDENCE_RELATIVE = "benchmark-evidence/pr15i-d3-c-v3r3"
PR15D_RUNNER = "benchmarks/pr15d/harness/run.py"
PR15D_VALIDATOR = "benchmarks/pr15d/harness/validate.py"
PR15D_CORPUS_GENERATOR = "benchmarks/pr15d/corpus/generate.py"

#: Environment keys preserved verbatim for the legacy toolchains.
_PRESERVED_ENV = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "JAVA_HOME",
    "GRADLE_USER_HOME",
    "USER",
    "SHELL",
)

#: Ordered lifecycle states; only forward neighbours are legal.
STATE_ORDER: tuple[str, ...] = (
    "IMPLEMENTING",
    "SOURCE_FROZEN",
    "AUTHORIZATION_PENDING",
    "AUTHORIZED",
    "CONTROL_RUNNING",
    "CONTROL_ACCEPTED",
    "TREATMENT_RUNNING",
    "REAL_EVIDENCE_SEALED",
    "REAL_ACCEPTED",
    "REAL_ATTESTED",
    "HISTORICAL_PARITY_PENDING",
    "CLOSEOUT_READY",
)
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "IMPLEMENTING": frozenset({"SOURCE_FROZEN"}),
    "SOURCE_FROZEN": frozenset({"AUTHORIZATION_PENDING"}),
    "AUTHORIZATION_PENDING": frozenset({"AUTHORIZED"}),
    "AUTHORIZED": frozenset({"CONTROL_RUNNING"}),
    "CONTROL_RUNNING": frozenset({"CONTROL_ACCEPTED"}),
    "CONTROL_ACCEPTED": frozenset({"TREATMENT_RUNNING"}),
    "TREATMENT_RUNNING": frozenset({"REAL_EVIDENCE_SEALED"}),
    "REAL_EVIDENCE_SEALED": frozenset({"REAL_ACCEPTED"}),
    "REAL_ACCEPTED": frozenset({"REAL_ATTESTED"}),
    "REAL_ATTESTED": frozenset({"HISTORICAL_PARITY_PENDING"}),
    "HISTORICAL_PARITY_PENDING": frozenset({"CLOSEOUT_READY"}),
    "CLOSEOUT_READY": frozenset(),
}


def _identity(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def require_transition(current: str, target: str) -> str:
    """Require one legal forward lifecycle transition."""

    if current not in STATE_ORDER:
        raise _identity(f"unknown acquisition state: {current!r}", "state")
    if target not in STATE_ORDER:
        raise _identity(f"unknown acquisition state: {target!r}", "state")
    if target not in LEGAL_TRANSITIONS[current]:
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            f"transition {current} -> {target} is not permitted",
            field_path="state",
        )
    return target


@dataclass(frozen=True)
class BackendInvocation:
    """One fully resolved legacy backend invocation (not yet executed)."""

    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    timeout_seconds: int
    output_path: Path
    campaign: str | None

    def summary(self) -> dict[str, Any]:
        """Return a path-free canonical summary of the invocation."""

        return {
            "program": self.argv[1] if len(self.argv) > 1 else self.argv[0],
            "arguments": list(self.argv[2:]),
            "timeout_seconds": self.timeout_seconds,
            "campaign": self.campaign,
        }


@dataclass(frozen=True)
class BackendResult:
    """The durable outcome of one backend invocation."""

    invocation: BackendInvocation
    returncode: int
    stdout_tail: str
    stderr_tail: str
    output_path: Path

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def _truncate(data: bytes) -> str:
    if len(data) > MAX_CAPTURE_BYTES:
        data = data[-MAX_CAPTURE_BYTES:]
    return data.decode("utf-8", errors="replace")


def sanitized_environment(home: Path | None = None) -> dict[str, str]:
    """Return the explicit allowlisted environment for a legacy backend."""

    environment: dict[str, str] = {}
    for key in _PRESERVED_ENV:
        value = os.environ.get(key)
        if value is not None:
            environment[key] = value
    if home is not None:
        environment["HOME"] = str(home)
        environment.setdefault("XDG_DATA_HOME", str(Path(home) / ".local" / "share"))
    return environment


def _root() -> Path:
    return repository_root()


def require_retained_key_preconditions(
    freeze: OfficialFreeze, root: Path | None = None
) -> dict[str, Any]:
    """Require the original D3-C T6 freeze receipt and source ancestry.

    The historical backend keeps its own ``require_freeze``. This function is an
    additional, independent precondition: a missing or unsafe T6 receipt blocks
    the family (M12) instead of being replaced by a synthetic substitute.
    """

    require_freeze(freeze, STUDY_RETAINED_KEY)
    base = root if root is not None else _root()
    receipt_path = base / D3C_T6_RECEIPT
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the historical T6 freeze receipt is missing; retained-key acquisition is blocked",
            field_path="t6_freeze_receipt",
        )
    return {
        "t6_freeze_receipt": D3C_T6_RECEIPT,
        "archive_root_relative": D3C_EVIDENCE_RELATIVE,
    }


def probe_isolated_home(
    *, home: Path, python: str = sys.executable, timeout_seconds: int = 60
) -> dict[str, Any]:
    """Prove that an isolated ``HOME`` resolves to the intended private root.

    The probe performs no measurement, launches no engine and never mutates the
    host: it only checks ``os.path.expanduser('~')`` and the resolved archive root.
    """

    candidate = Path(home)
    if not candidate.is_absolute():
        raise BenchError(BM_UNSAFE_INPUT, "the isolated HOME must be an absolute path")
    if candidate.is_symlink():
        raise BenchError(BM_UNSAFE_INPUT, "the isolated HOME must not be a symbolic link")
    if not candidate.is_dir():
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "the isolated HOME directory is missing")
    try:
        mode = candidate.stat().st_mode & 0o777
    except OSError as exc:  # pragma: no cover - guarded above
        raise BenchError(BM_EVIDENCE_UNAVAILABLE, "the isolated HOME cannot be inspected") from exc
    if mode != 0o700:
        raise BenchError(BM_UNSAFE_INPUT, "the isolated HOME must be mode 700")
    script = (
        "import os;"
        "root = os.path.expanduser('~');"
        "assert root == os.environ['HOME'], root;"
        "print(os.path.expanduser('~/.local/share/quervant/benchmark-evidence'))"
    )
    completed = subprocess.run(
        [python, "-c", script],
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
        env=sanitized_environment(candidate),
    )
    if completed.returncode != 0:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the isolated HOME probe did not resolve to the private root",
            field_path="home",
        )
    resolved = completed.stdout.decode("utf-8", errors="replace").strip()
    expected = str(candidate / ".local" / "share" / "quervant" / "benchmark-evidence")
    if resolved != expected:
        raise _identity("the isolated archive root does not resolve as intended", "home")
    return {"home": str(candidate), "archive_root": resolved}


def require_fresh_output(
    series_root: Path, *, label: str, allow_existing_control: bool = False
) -> Path:
    """Require a never-before-created campaign path (never reused or cleaned)."""

    root = require_safe_root(series_root)
    target = root / label
    if os.path.lexists(target):
        if allow_existing_control:
            return target
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "the campaign output path already exists; a new run identity is required",
            field_path="output_path",
        )
    return target


# ---------------------------------------------------------------------------
# Retained-key (D3-C) invocations
# ---------------------------------------------------------------------------


def retained_key_invocations(
    authorization: VerifiedOfficialAuthorization,
    *,
    root: Path,
    series_root: Path,
    official_home: Path,
    timeout_seconds: int,
    observed: Mapping[str, Any] | None = None,
) -> dict[str, BackendInvocation]:
    """Return the exact ordered D3-C invocation set for one authorized run.

    The caller must supply a verified external authorization capability; a parsed
    :class:`OfficialFreeze` is not an authorization. No invocation may be selected,
    skipped or reordered: the returned dictionary is the complete sequence.
    """

    freeze = require_verified_official_authorization(
        authorization,
        study_id=STUDY_RETAINED_KEY,
        for_production=True,
        observed=observed,
    )
    require_retained_key_preconditions(freeze, root)
    runner = root / D3C_RUNNER
    verifier = root / D3C_VERIFIER
    environment = sanitized_environment(official_home)
    archive_root = str(
        official_home / ".local" / "share" / "quervant" / D3C_EVIDENCE_RELATIVE
    )
    control_dir = series_root / D3C_CONTROL_NAME
    campaign_dirs = {name: series_root / name for name in D3C_CAMPAIGN_NAMES}

    def invocation(
        argv: Sequence[str], output: Path, campaign: str | None
    ) -> BackendInvocation:
        return BackendInvocation(
            argv=(sys.executable, *argv),
            cwd=root,
            env=dict(environment),
            timeout_seconds=timeout_seconds,
            output_path=output,
            campaign=campaign,
        )

    invocations: dict[str, BackendInvocation] = {
        "preflight": invocation(
            [str(runner), "preflight", "--out", str(series_root.parent / f"preflight-{freeze.run_id}.json")],
            series_root.parent / f"preflight-{freeze.run_id}.json",
            None,
        ),
        "readiness-control": invocation([str(runner), "readiness-only"], control_dir, None),
        "control": invocation(
            [
                str(runner),
                "control",
                "--campaign",
                D3C_CONTROL_NAME,
                "--out",
                str(control_dir),
                "--idle-confirmed",
            ],
            control_dir,
            D3C_CONTROL_NAME,
        ),
        "verify-control": invocation(
            [str(verifier), "--campaign-dir", str(control_dir)], control_dir, D3C_CONTROL_NAME
        ),
        "publish-control": invocation(
            [
                str(runner),
                "publish",
                "--campaign-dir",
                str(control_dir),
                "--evidence-root",
                archive_root,
            ],
            control_dir,
            D3C_CONTROL_NAME,
        ),
    }
    for index, name in enumerate(D3C_CAMPAIGN_NAMES, start=1):
        directory = campaign_dirs[name]
        invocations[f"readiness-{name}"] = invocation(
            [str(runner), "readiness-only"], directory, None
        )
        invocations[f"campaign-{index}"] = invocation(
            [
                str(runner),
                "campaign",
                "--campaign",
                name,
                "--out",
                str(directory),
                "--idle-confirmed",
            ],
            directory,
            name,
        )
        invocations[f"verify-{name}"] = invocation(
            [str(verifier), "--campaign-dir", str(directory)], directory, name
        )
        invocations[f"publish-{name}"] = invocation(
            [
                str(runner),
                "publish",
                "--campaign-dir",
                str(directory),
                "--evidence-root",
                archive_root,
            ],
            directory,
            name,
        )
    invocations["verify-series"] = invocation(
        [str(verifier), "--series-root", str(series_root)], series_root, None
    )
    order = [
        "preflight",
        "readiness-control",
        "control",
        "verify-control",
        "publish-control",
    ]
    for index, name in enumerate(D3C_CAMPAIGN_NAMES, start=1):
        order.extend(
            [
                f"readiness-{name}",
                f"campaign-{index}",
                f"verify-{name}",
                f"publish-{name}",
            ]
        )
    order.append("verify-series")
    return {name: invocations[name] for name in order}


def run_backend(invocation: BackendInvocation, *, cwd_override: Path | None = None) -> BackendResult:
    """Execute one resolved invocation and preserve its terminal outcome."""

    argv = list(invocation.argv)
    if "--allow-contended" in argv:  # pragma: no cover - defensive
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            "official acquisition never permits contended measurements",
            field_path="argv",
        )
    if not Path(argv[0]).name.startswith("python"):
        raise BenchError(BM_UNSAFE_INPUT, "the backend must run under the approved interpreter")
    completed = subprocess.run(
        argv,
        cwd=str(cwd_override if cwd_override is not None else invocation.cwd),
        env=dict(invocation.env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=invocation.timeout_seconds,
        check=False,
        shell=False,
    )
    return BackendResult(
        invocation=invocation,
        returncode=completed.returncode,
        stdout_tail=_truncate(completed.stdout),
        stderr_tail=_truncate(completed.stderr),
        output_path=invocation.output_path,
    )


def require_backend_success(result: BackendResult, *, gate: str) -> BackendResult:
    """Require a zero exit status; a failure is terminal for the current run."""

    if result.returncode != 0:
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            f"{gate} backend exited with status {result.returncode}; the attempt is preserved and not retried",
            field_path="returncode",
        )
    return result


# ---------------------------------------------------------------------------
# Cross-engine (PR15D) invocations
# ---------------------------------------------------------------------------


def require_backend_output_root(raw_root: Path) -> Path:
    """Validate the official cross-engine output root and its ``backend/`` child.

    The official layout reserves ``raw_root`` for control artefacts and requires the
    PR15D backend to write beneath ``raw_root/backend``. An existing (or symlinked)
    backend path is never reused, cleaned or overwritten.
    """

    root = require_safe_root(Path(raw_root))
    backend = root / "backend"
    if backend.is_symlink():
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the cross-engine backend root must not be a symbolic link",
            field_path="backend",
        )
    if os.path.lexists(backend):
        raise BenchError(
            BM_PUBLICATION_CONFLICT,
            "the cross-engine backend root already exists; a new run identity is required",
            field_path="backend",
        )
    return backend


def cross_engine_invocations(
    authorization: VerifiedOfficialAuthorization,
    *,
    root: Path,
    raw_root: Path,
    corpus_dir: Path,
    timeout_seconds: int,
    observed: Mapping[str, Any] | None = None,
) -> dict[str, BackendInvocation]:
    """Return the exact PR15D invocation set (full 32-lane, 3-trial suite)."""

    freeze = require_verified_official_authorization(
        authorization,
        study_id=STUDY_CROSS_ENGINE,
        for_production=True,
        observed=observed,
    )
    backend_root = require_backend_output_root(raw_root)
    environment = sanitized_environment(Path(freeze.approved_output_root_identity).parent)
    run_argv = (
        sys.executable,
        str(root / PR15D_RUNNER),
        "--trials",
        "3",
        "--idle-confirmed",
        "--out",
        str(backend_root),
        "--corpus",
        str(corpus_dir),
    )
    return {
        "run": BackendInvocation(
            argv=run_argv,
            cwd=root,
            env=dict(environment),
            timeout_seconds=timeout_seconds,
            output_path=backend_root,
            campaign=None,
        ),
        "validate": BackendInvocation(
            argv=(
                sys.executable,
                str(root / PR15D_VALIDATOR),
                "--run",
                str(backend_root),
                "--out",
                str(backend_root / "validation.json"),
            ),
            cwd=root,
            env=dict(environment),
            timeout_seconds=timeout_seconds,
            output_path=backend_root / "validation.json",
            campaign=None,
        ),
    }


def corpus_invocation(*, root: Path, corpus_dir: Path, timeout_seconds: int) -> BackendInvocation:
    """Return the deterministic corpus generation invocation."""

    return BackendInvocation(
        argv=(
            sys.executable,
            str(root / PR15D_CORPUS_GENERATOR),
            "--out",
            str(corpus_dir),
        ),
        cwd=root,
        env=sanitized_environment(),
        timeout_seconds=timeout_seconds,
        output_path=corpus_dir,
        campaign=None,
    )


# ---------------------------------------------------------------------------
# Read-only inspection
# ---------------------------------------------------------------------------


def read_existing_raw(root: Path, relative: str, *, max_bytes: int) -> bytes:
    """Read one declared raw-evidence member without following links."""

    from ..evidence.paths import open_regular_beneath

    member = validate_relative_member(relative)
    handle = open_regular_beneath(require_safe_root(root), member)
    with handle:
        payload = handle.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "raw evidence member exceeds the approved byte budget",
            reference=member,
        )
    return payload


_STATUS_SCHEMA_KEYS = frozenset(
    {"state", "study_id", "run_id", "campaigns", "failed_gate", "reasons"}
)


def inspect_status(document: object) -> dict[str, Any]:
    """Validate a persisted acquisition status record (read-only)."""

    status = require_closed(document, "acquisition-status", _STATUS_SCHEMA_KEYS)
    if status["state"] not in STATE_ORDER:
        raise _identity("acquisition status state is not frozen", "state")
    from ..config.identity import validate_semantic_id, validate_uuid4

    validate_semantic_id(status["study_id"], "study_id")
    validate_uuid4(status["run_id"], "run_id")
    campaigns = status["campaigns"]
    if not isinstance(campaigns, list) or any(not isinstance(item, str) for item in campaigns):
        raise BenchError(BM_UNSAFE_INPUT, "campaigns must be a list of strings")
    failed = status["failed_gate"]
    if failed is not None and not isinstance(failed, str):
        raise BenchError(BM_UNSAFE_INPUT, "failed_gate must be a string or null")
    reasons = status["reasons"]
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise BenchError(BM_UNSAFE_INPUT, "reasons must be a list of strings")
    return dict(status)


__all__ = [
    "D3C_CAMPAIGN_NAMES",
    "D3C_CONTROL_NAME",
    "D3C_RUNNER",
    "D3C_T6_RECEIPT",
    "D3C_VERIFIER",
    "BackendInvocation",
    "BackendResult",
    "LEGAL_TRANSITIONS",
    "PR15D_RUNNER",
    "PR15D_VALIDATOR",
    "STATE_ORDER",
    "corpus_invocation",
    "cross_engine_invocations",
    "inspect_status",
    "probe_isolated_home",
    "read_existing_raw",
    "require_backend_output_root",
    "require_backend_success",
    "require_fresh_output",
    "require_retained_key_preconditions",
    "require_transition",
    "retained_key_invocations",
    "run_backend",
    "sanitized_environment",
]
