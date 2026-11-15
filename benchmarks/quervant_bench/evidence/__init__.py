"""Reusable, read-only evidence inspection and admission primitives.

This package has no import-time side effects. It never times, schedules, extracts
archives, executes build artifacts or issues a real/official qualification.
"""

from __future__ import annotations

from .admission import AdmissionResult, admit_synthetic, reverify_admission
from .archives import ArchiveLimits, MemberDigest, inspect_tar_gz, inspect_zip
from .hashing import sha256_regular_file, sha256_stream, source_file_set_digest
from .manifests import TrustedAdmissionSpec, load_trusted_spec
from .paths import (
    list_declared_files_beneath,
    open_regular_beneath,
    validate_relative_member,
)
from .provenance import (
    VALIDATOR_SOURCE_PATHS,
    BuildFileIdentity,
    GitSourceIdentity,
    require_clean_head,
    verify_build_file,
    verify_git_commit,
    verify_validator_source,
)
from .publication import load_committed_admission, publish_admission
from .receipts import build_admission_receipt, verify_admission_receipt

__all__ = [
    "AdmissionResult",
    "ArchiveLimits",
    "BuildFileIdentity",
    "GitSourceIdentity",
    "MemberDigest",
    "TrustedAdmissionSpec",
    "VALIDATOR_SOURCE_PATHS",
    "admit_synthetic",
    "build_admission_receipt",
    "inspect_tar_gz",
    "inspect_zip",
    "list_declared_files_beneath",
    "load_committed_admission",
    "load_trusted_spec",
    "open_regular_beneath",
    "publish_admission",
    "require_clean_head",
    "reverify_admission",
    "sha256_regular_file",
    "sha256_stream",
    "source_file_set_digest",
    "validate_relative_member",
    "verify_admission_receipt",
    "verify_build_file",
    "verify_git_commit",
    "verify_validator_source",
]
