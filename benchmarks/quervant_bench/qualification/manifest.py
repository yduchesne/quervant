"""Freeze snapshot and acyclic attestation/manifest algebra for Gate E.

The snapshot is built in memory over the first 13 durable members. The attestation
receipt depends on every upstream gate and outputs *only* the snapshot digest; it
never mentions ``manifest.json``. The final manifest embeds the snapshot, references
the attestation digest and lists all 14 published members. That breaks the hash
cycle while binding the full content-addressed set.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..config.codec import canonical_document_bytes, content_digest
from ..config.errors import BM_IDENTITY_INVALID, BenchError
from .contracts import (
    ATTESTATION_NAME,
    FREEZE_MEMBERS,
    MANIFEST_KIND,
    MANIFEST_MEMBERS,
    SNAPSHOT_KIND,
    SCHEMA_VERSION,
    bound_payload,
    validate_freeze_snapshot,
    validate_manifest,
)
from .receipts import build_stage_receipt, validator_identity, verify_stage_receipt

def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def member_record(name: str, document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the manifest/snapshot record for one canonical document member."""

    payload = canonical_document_bytes(dict(document))
    return {
        "path": name,
        "byte_length": len(payload),
        "digest": content_digest(dict(document)),
    }


def build_freeze_snapshot(
    *,
    subject: Mapping[str, Any],
    profile_digest: str,
    source_set_digest: str,
    members: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the canonical, in-memory pre-attestation freeze snapshot."""

    records = sorted(
        (
            {
                "path": member["path"],
                "byte_length": member["byte_length"],
                "digest": member["digest"],
            }
            for member in members
        ),
        key=lambda record: record["path"],
    )
    snapshot = {
        "kind": SNAPSHOT_KIND,
        "schema_version": SCHEMA_VERSION,
        "subject": dict(subject),
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "profile_digest": profile_digest,
        "source_set_digest": source_set_digest,
        "members": records,
    }
    validate_freeze_snapshot(snapshot)
    return snapshot


def build_attestation_receipt(
    *,
    subject: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]],
    profile_digest: str,
    policy_digest: str,
    source_set_digest: str,
) -> dict[str, Any]:
    """Build the acyclic attestation receipt over the frozen snapshot digest."""

    snapshot_document = validate_freeze_snapshot(snapshot)
    snapshot_digest = content_digest(snapshot_document)
    document = build_stage_receipt(
        gate="attestation",
        subject=subject,
        validator=validator_identity("attestation", source_set_digest),
        inputs={
            "freeze-snapshot": snapshot_digest,
            "source-set": source_set_digest,
            "qualification-profile": profile_digest,
        },
        dependencies=dependencies,
        outputs={"freeze-snapshot": snapshot_digest},
        profile_digest=profile_digest,
        policy_digest=policy_digest,
    )
    for entry in document["outputs"]:
        if entry["name"] != "freeze-snapshot":
            raise _fail("attestation may output only the freeze snapshot", "outputs")
    return document


def build_manifest(
    *,
    subject: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    attestation_receipt: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    profile_digest: str,
    source_set_digest: str,
) -> dict[str, Any]:
    """Build the final completion manifest for all first 14 published members."""

    snapshot_document = validate_freeze_snapshot(snapshot)
    records = sorted(
        (
            {
                "path": member["path"],
                "byte_length": member["byte_length"],
                "digest": member["digest"],
            }
            for member in members
        ),
        key=lambda record: record["path"],
    )
    if tuple(record["path"] for record in records) != MANIFEST_MEMBERS:
        raise _fail("the manifest member set is not the exact 14-file inventory", "members")
    if ATTESTATION_NAME not in {record["path"] for record in records}:
        raise _fail("the manifest must include the attestation receipt", "members")
    manifest = {
        "kind": MANIFEST_KIND,
        "schema_version": SCHEMA_VERSION,
        "subject": dict(subject),
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "profile_digest": profile_digest,
        "source_set_digest": source_set_digest,
        "freeze_snapshot": snapshot_document,
        "attestation_digest": content_digest(dict(attestation_receipt)),
        "members": records,
    }
    validate_manifest(manifest)
    bound_payload(manifest, "manifest")
    return manifest


def verify_freeze_snapshot(
    *,
    snapshot: Mapping[str, Any],
    attestation_receipt: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
    subject: Mapping[str, Any],
    profile_digest: str,
    source_set_digest: str,
) -> str:
    """Reconstruct the snapshot from committed documents and cross-check E."""

    snapshot_document = validate_freeze_snapshot(snapshot)
    if set(documents) != set(FREEZE_MEMBERS):
        raise _fail("the frozen member set is not the exact 13 documents", "members")
    reconstructed = build_freeze_snapshot(
        subject=subject,
        profile_digest=profile_digest,
        source_set_digest=source_set_digest,
        members=[member_record(name, documents[name]) for name in FREEZE_MEMBERS],
    )
    if reconstructed != snapshot_document:
        raise _fail(
            "the freeze snapshot does not match the committed member bytes", "freeze_snapshot"
        )
    outputs = attestation_receipt.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise _fail("the attestation receipt must declare one output", "outputs")
    output = outputs[0]
    if output.get("name") != "freeze-snapshot":
        raise _fail("the attestation receipt output must be the freeze snapshot", "outputs")
    if output.get("digest") != content_digest(snapshot_document):
        raise _fail(
            "the attestation output does not match the reconstructed snapshot",
            "freeze_snapshot",
        )
    for field, expected in (
        ("subject", subject),
        ("profile_digest", profile_digest),
        ("source_set_digest", source_set_digest),
    ):
        if snapshot_document[field] != expected:
            raise _fail("the freeze snapshot is not bound to the current anchors", field)
    return content_digest(snapshot_document)


def verify_attestation_graph(
    *,
    attestation_receipt: Mapping[str, Any],
    upstream: Sequence[Mapping[str, Any]],
    subject: Mapping[str, Any],
    snapshot_digest: str,
    profile_digest: str,
    policy_digest: str,
    source_set_digest: str,
) -> None:
    """Verify the exact E dependency set and that it never references the manifest."""

    for entry in attestation_receipt.get("dependencies", []):
        if entry.get("name") == "manifest" or entry.get("gate") == "manifest":
            raise _fail("the attestation must not depend on the final manifest", "dependencies")
    verify_stage_receipt(
        attestation_receipt,
        gate="attestation",
        source_set_digest=source_set_digest,
        expected_subject=subject,
        inputs={
            "freeze-snapshot": snapshot_digest,
            "source-set": source_set_digest,
            "qualification-profile": profile_digest,
        },
        outputs={"freeze-snapshot": snapshot_digest},
        dependencies=upstream,
        profile_digest=profile_digest,
        policy_digest=policy_digest,
    )


def verify_manifest_members(
    *,
    manifest: Mapping[str, Any],
    payloads: Mapping[str, bytes],
    documents: Mapping[str, Mapping[str, Any]],
) -> str:
    """Verify every manifest member against its actual canonical bytes."""

    validated = validate_manifest(manifest)
    expected_names = set(MANIFEST_MEMBERS)
    if set(payloads) != expected_names or set(documents) != expected_names:
        raise _fail("the committed member set is not the exact 14-file inventory", "members")
    for member in validated["members"]:
        name = member["path"]
        payload = payloads[name]
        if len(payload) != member["byte_length"]:
            raise _fail(f"member byte length mismatch: {name}", "members")
        if content_digest(dict(documents[name])) != member["digest"]:
            raise _fail(f"member digest mismatch: {name}", "members")
    if validated["attestation_digest"] != content_digest(dict(documents[ATTESTATION_NAME])):
        raise _fail("the manifest attestation digest is not the attestation document", "attestation_digest")
    snapshot = validated["freeze_snapshot"]
    snapshot_paths = [member["path"] for member in snapshot["members"]]
    if tuple(snapshot_paths) != FREEZE_MEMBERS:
        raise _fail("the manifest snapshot is not the exact 13-file inventory", "freeze_snapshot")
    return content_digest(dict(manifest))


__all__ = [
    "build_attestation_receipt",
    "build_freeze_snapshot",
    "build_manifest",
    "member_record",
    "verify_attestation_graph",
    "verify_freeze_snapshot",
    "verify_manifest_members",
]
