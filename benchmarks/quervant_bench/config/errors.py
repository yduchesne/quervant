"""Typed benchmarking error codes and their process exit categories.

The codes in :data:`CODE_TABLE` are a frozen BM-01 contract. Callers must branch
on the code/category, never on the human-readable message. Unknown conditions map
to ``BM_INTERNAL_ERROR`` and never to a success code.
"""

from __future__ import annotations

from dataclasses import dataclass

BM_OK = "BM_OK"
BM_USAGE = "BM_USAGE"
BM_SCHEMA_INVALID = "BM_SCHEMA_INVALID"
BM_SCHEMA_UNSUPPORTED = "BM_SCHEMA_UNSUPPORTED"
BM_DUPLICATE_KEY = "BM_DUPLICATE_KEY"
BM_IDENTITY_INVALID = "BM_IDENTITY_INVALID"
BM_SCOPE_MISMATCH = "BM_SCOPE_MISMATCH"
BM_UNSAFE_INPUT = "BM_UNSAFE_INPUT"
BM_FILE_MISSING = "BM_FILE_MISSING"
BM_NOT_IMPLEMENTED = "BM_NOT_IMPLEMENTED"
BM_EVIDENCE_UNAVAILABLE = "BM_EVIDENCE_UNAVAILABLE"
BM_PUBLICATION_CONFLICT = "BM_PUBLICATION_CONFLICT"
BM_ACQUISITION_PROHIBITED = "BM_ACQUISITION_PROHIBITED"
BM_INTERNAL_ERROR = "BM_INTERNAL_ERROR"

#: ``code -> (category, process exit status)``.
CODE_TABLE: dict[str, tuple[str, int]] = {
    BM_OK: ("success", 0),
    BM_USAGE: ("invalid-cli-usage", 64),
    BM_SCHEMA_INVALID: ("invalid-document", 65),
    BM_SCHEMA_UNSUPPORTED: ("invalid-document", 65),
    BM_DUPLICATE_KEY: ("invalid-document", 65),
    BM_IDENTITY_INVALID: ("invalid-identity", 65),
    BM_SCOPE_MISMATCH: ("invalid-scope", 65),
    BM_UNSAFE_INPUT: ("unsafe-input", 65),
    BM_FILE_MISSING: ("missing-input", 66),
    BM_NOT_IMPLEMENTED: ("stage-unavailable", 69),
    BM_EVIDENCE_UNAVAILABLE: ("evidence-unavailable", 69),
    BM_PUBLICATION_CONFLICT: ("publication-conflict", 73),
    BM_ACQUISITION_PROHIBITED: ("forbidden-action", 77),
    BM_INTERNAL_ERROR: ("internal-defect", 70),
}

#: Codes that describe an intentionally unavailable/blocked stage rather than a
#: defective input.
BLOCKED_CODES = frozenset(
    {
        BM_NOT_IMPLEMENTED,
        BM_EVIDENCE_UNAVAILABLE,
        BM_ACQUISITION_PROHIBITED,
        BM_PUBLICATION_CONFLICT,
    }
)

MAX_MESSAGE_BYTES = 1024


def error_spec(code: str) -> tuple[str, int]:
    """Return ``(category, exit_status)`` for a frozen code."""

    try:
        return CODE_TABLE[code]
    except KeyError as exc:  # pragma: no cover - guarded by construction
        raise ValueError(f"unknown benchmark error code: {code!r}") from exc


def bounded_message(message: str) -> str:
    """Return ``message`` truncated to the contract's UTF-8 byte budget."""

    encoded = message.encode("utf-8")
    if len(encoded) <= MAX_MESSAGE_BYTES:
        return message
    return encoded[:MAX_MESSAGE_BYTES].decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class BenchError(Exception):
    """A typed, fail-closed benchmarking error.

    ``field_path`` is a bounded logical path such as ``arms[0].arm_id``;
    ``reference`` is an optional safe relative path. Neither may leak absolute
    host paths, credentials or stack traces into standard CLI output.
    """

    code: str
    message: str
    field_path: str | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        if self.code not in CODE_TABLE:
            raise ValueError(f"unknown benchmark error code: {self.code!r}")
        object.__setattr__(self, "message", bounded_message(self.message))

    @property
    def category(self) -> str:
        return error_spec(self.code)[0]

    @property
    def exit_code(self) -> int:
        return error_spec(self.code)[1]

    @property
    def status(self) -> str:
        return "blocked" if self.code in BLOCKED_CODES else "error"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.code}: {self.message}"


def internal_error() -> BenchError:
    """Return a generic internal defect error that leaks no traceback."""

    return BenchError(
        BM_INTERNAL_ERROR,
        "unexpected internal failure; no output was published",
    )
