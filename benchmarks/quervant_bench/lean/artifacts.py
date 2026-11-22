"""Permanent, milestone-independent benchmark artifact naming and safe publication.

No integrity attestations, hash anchors, approvals or content seals are involved.
A short, OS-level lock serializes suffix selection across dates and processes.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
CONFIG_FILE = re.compile(r"(?P<name>[a-z][a-z0-9-]*)-(?P<date>\d{4}-\d{2}-\d{2})\.json\Z")
RESULT_FILE = re.compile(r"(?P<name>[a-z][a-z0-9-]*)-(?P<date>\d{4}-\d{2}-\d{2})-(?P<sequence>\d{3})\.json\Z")
MAX_SEQUENCE = 999


class ArtifactError(ValueError):
    """User-actionable invalid artifact, collision or storage failure."""


def slug(value: object) -> str:
    if not isinstance(value, str) or len(value) > 80 or not NAME.fullmatch(value):
        raise ArtifactError("configuration name must be a lowercase hyphenated slug (1-80 characters)")
    return value


def utc_date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ArtifactError("date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ArtifactError("invalid UTC date") from error


def utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ArtifactError("timestamp must be an explicit UTC ISO 8601 string ending Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ArtifactError("invalid UTC timestamp") from error
    if parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ArtifactError("timestamp must be UTC")
    return parsed


def require_uuid(value: object, label: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ArtifactError(f"{label} must be a UUID") from error
    if str(parsed) != value:
        raise ArtifactError(f"{label} must be a canonical lowercase UUID")
    return str(parsed)


def configuration_filename(config: Mapping[str, Any]) -> str:
    name = slug(config.get("name"))
    created = utc_timestamp(config.get("created_utc"))
    require_uuid(config.get("configuration_id"), "configuration_id")
    if not isinstance(config.get("description"), str) or not config["description"].strip():
        raise ArtifactError("configuration requires a human-readable description")
    return f"{name}-{created.date().isoformat()}.json"


def load_configuration(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("configuration must be a regular, non-symlink JSON file")
    value = _read_json(path)
    if not isinstance(value, dict):
        raise ArtifactError("configuration must be an object")
    if configuration_filename(value) != path.name:
        raise ArtifactError("configuration filename does not match its name and UTC creation date")
    return value


def _read_json(path: Path) -> Any:
    try:
        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    raise ArtifactError(f"duplicate JSON key: {key}")
                result[key] = value
            return result
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ArtifactError(f"invalid numeric constant: {x}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactError(f"cannot read JSON {path}: {error}") from error


def _json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ArtifactError(f"unserializable JSON artifact: {error}") from error


def _publish_exclusive(path: Path, payload: bytes) -> None:
    """Durable write with no replacement, including concurrently contested names."""
    if path.is_symlink():
        raise ArtifactError(f"refusing symlink destination {path}")
    fd = -1
    temp: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".bm10-", dir=path.parent)
        temp = Path(name)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            os.fchmod(stream.fileno(), 0o644)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path, follow_symlinks=False)  # atomic, fails on existing output
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as error:
        raise ArtifactError(f"artifact already exists: {path.name}") from error
    except OSError as error:
        raise ArtifactError(f"artifact publication failed: {error}") from error
    finally:
        if fd != -1:
            os.close(fd)
        if temp is not None:
            temp.unlink(missing_ok=True)


@contextlib.contextmanager
def _lock(directory: Path, key: str) -> Iterator[None]:
    """Lock directory inode: no persistent lock file or other artifact."""
    if directory.is_symlink():
        raise ArtifactError("artifact directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    except OSError as error:
        raise ArtifactError(f"cannot lock artifact directory: {error}") from error


def _configuration_registry(config_dir: Path) -> dict[str, str]:
    by_name: dict[str, str] = {}
    by_id: dict[str, str] = {}
    files_for_name: set[str] = set()
    for path in sorted(config_dir.glob("*.json")):
        if not CONFIG_FILE.fullmatch(path.name):
            raise ArtifactError(f"unrecognized configuration filename: {path.name}")
        config = load_configuration(path)
        name, identity = config["name"], config["configuration_id"]
        if name in files_for_name:
            raise ArtifactError(f"multiple configuration files use name: {name}")
        files_for_name.add(name)
        if (name in by_name and by_name[name] != identity) or (identity in by_id and by_id[identity] != name):
            raise ArtifactError("configuration names and IDs must be unique and one-to-one")
        by_name[name], by_id[identity] = identity, name
    return by_name


def create_configuration(config_dir: Path, config: Mapping[str, Any]) -> Path:
    filename = configuration_filename(config)
    with _lock(config_dir, "configurations"):
        registry = _configuration_registry(config_dir)
        if config["name"] in registry:
            raise ArtifactError(f"configuration name already reserved: {config['name']}")
        if config["configuration_id"] in set(registry.values()):
            raise ArtifactError(f"configuration ID already reserved: {config['configuration_id']}")
        _publish_exclusive(config_dir / filename, _json_bytes(config))
    return config_dir / filename


def _existing_sequences(result_dir: Path, name: str, identity: str) -> set[int]:
    found: set[int] = set()
    for path in result_dir.glob("*.json"):
        match = RESULT_FILE.fullmatch(path.name)
        if match is None:
            raise ArtifactError(f"unrecognized result filename: {path.name}")
        if match["name"] != name:
            continue
        utc_date(match["date"])
        sequence = int(match["sequence"])
        if sequence == 0:
            raise ArtifactError("result sequence zero is invalid")
        data = _read_json(path)
        if not isinstance(data, dict) or data.get("configuration_id") != identity or data.get("sequence") != sequence:
            raise ArtifactError(f"existing result has inconsistent configuration identity: {path.name}")
        if (data.get("configuration_name") != name or not isinstance(data.get("configuration_file"), str) or
                not data["configuration_file"].startswith(f"{name}-") or
                utc_timestamp(data.get("executed_utc")).date() != utc_date(match["date"])):
            raise ArtifactError(f"existing result has inconsistent name or execution date: {path.name}")
        require_uuid(data.get("run_id"), "existing run_id")
        if sequence in found:
            raise ArtifactError(f"result sequence {sequence:03d} reused across dates")
        found.add(sequence)
    return found


def publish_result(config_path: Path, result_dir: Path, raw_result: Mapping[str, Any]) -> Path:
    """Assign the next cross-date sequence and publish completed results once."""
    config = load_configuration(config_path)
    registry = _configuration_registry(config_path.parent)
    name, identity = config["name"], config["configuration_id"]
    if registry.get(name) != identity:
        raise ArtifactError("configuration registry conflict")
    if raw_result.get("configuration_id") != identity:
        raise ArtifactError("result configuration_id does not match source configuration")
    require_uuid(raw_result.get("run_id"), "run_id")
    executed = utc_timestamp(raw_result.get("executed_utc"))
    if not isinstance(raw_result.get("raw_samples"), list) or not isinstance(raw_result.get("analysis"), dict):
        raise ArtifactError("result must include raw samples and completed analysis")
    with _lock(result_dir, identity):
        sequences = _existing_sequences(result_dir, name, identity)
        next_sequence = max(sequences, default=0) + 1
        if next_sequence > MAX_SEQUENCE:
            raise ArtifactError("result sequence exhausted (999); assign a new documented format revision")
        filename = f"{name}-{executed.date().isoformat()}-{next_sequence:03d}.json"
        document = {**raw_result, "configuration_name": name,
                    "configuration_file": config_path.name, "sequence": next_sequence}
        _publish_exclusive(result_dir / filename, _json_bytes(document))
    return result_dir / filename


def load_result(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("result must be a regular, non-symlink JSON file")
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ArtifactError("result must be an object")
    name = slug(data.get("configuration_name"))
    match = RESULT_FILE.fullmatch(path.name)
    if match is None or match["name"] != name:
        raise ArtifactError("result filename does not match configuration name")
    if utc_timestamp(data.get("executed_utc")).date() != utc_date(match["date"]):
        raise ArtifactError("result filename date disagrees with UTC execution timestamp")
    if data.get("sequence") != int(match["sequence"]) or not 1 <= int(match["sequence"]) <= MAX_SEQUENCE:
        raise ArtifactError("result sequence disagrees with filename")
    require_uuid(data.get("run_id"), "run_id")
    require_uuid(data.get("configuration_id"), "configuration_id")
    if not isinstance(data.get("analysis"), dict) or not isinstance(data.get("raw_samples"), list):
        raise ArtifactError("result is missing raw measurements or analysis")
    return data
