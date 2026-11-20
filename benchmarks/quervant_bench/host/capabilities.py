"""Read-only host capability snapshots.

A capability snapshot describes a host at one instant. It is **diagnostic** and
never a readiness decision, authorization token or acquisition permit.
"""

from __future__ import annotations

import os
import platform
import re
from typing import Protocol, runtime_checkable

from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BenchError,
)

_HARDWARE_PATH_RE = re.compile(
    r"^/sys/devices/system/cpu/cpu(?P<cpu>[0-9]{1,6})/topology/"
    r"(?P<field>physical_package_id|core_id|thread_siblings_list)$"
)
_ALLOWED_PROC_PATHS = frozenset({"/proc/version", "/proc/cpuinfo", "/proc/stat"})
_ENVIRONMENTS = ("native-linux", "wsl2", "unsupported")
_TOPOLOGY_KEYS = frozenset({"cpu", "package_id", "core_id", "siblings"})
_CAPABILITY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "environment",
        "system",
        "architecture",
        "kernel_release",
        "allowed_cpus",
        "cpu_topology",
        "missing_fields",
    }
)


@runtime_checkable
class CapabilityProvider(Protocol):
    """Injected, read-only host observation source."""

    def read_text(self, relative_system_path: str) -> str | None: ...

    def allowed_cpu_ids(self) -> tuple[int, ...]: ...

    def platform_record(self) -> tuple[str, str, str]: ...


class LinuxCapabilityProvider:
    """Read-only provider allowlisting a small set of ``/proc`` and ``/sys`` files."""

    def read_text(self, relative_system_path: str) -> str | None:
        if not isinstance(relative_system_path, str):
            return None
        if relative_system_path not in _ALLOWED_PROC_PATHS:
            if _HARDWARE_PATH_RE.fullmatch(relative_system_path) is None:
                return None
        try:
            with open(relative_system_path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return None

    def allowed_cpu_ids(self) -> tuple[int, ...]:
        getter = getattr(os, "sched_getaffinity", None)
        if getter is not None:
            try:
                return tuple(sorted(getter(0)))
            except OSError:  # pragma: no cover - defensive
                pass
        count = os.cpu_count()
        if not count:
            return ()
        return tuple(range(count))

    def platform_record(self) -> tuple[str, str, str]:
        uname = platform.uname()
        return (uname.system, uname.machine, uname.release)


def _wsl2_detected(kernel_release: str, proc_version: str | None) -> bool:
    haystacks = [kernel_release.lower()]
    if proc_version:
        haystacks.append(proc_version.lower())
    return any(
        "microsoft" in value or "wsl" in value for value in haystacks
    )


def _read_int(provider: CapabilityProvider, path: str) -> int | None:
    raw = provider.read_text(path)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except (ValueError, AttributeError):
        return None


def collect_host_capabilities(provider: CapabilityProvider) -> dict:
    """Collect a deterministic, canonicalisable capability snapshot.

    The supplied provider is the only observation source. No clock is read, no
    affinity is mutated and no subprocess is launched.
    """

    system, machine, kernel_release = provider.platform_record()
    if not all(isinstance(value, str) for value in (system, machine, kernel_release)):
        raise BenchError(
            BM_SCHEMA_INVALID, "platform_record must return three strings"
        )
    proc_version = provider.read_text("/proc/version")

    if system.lower() != "linux":
        environment = "unsupported"
    elif _wsl2_detected(kernel_release, proc_version):
        environment = "wsl2"
    else:
        environment = "native-linux"

    missing: set[str] = set()
    raw_cpus = provider.allowed_cpu_ids()
    allowed: list[int] = []
    for cpu in raw_cpus:
        if isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0:
            missing.add("allowed_cpus")
            continue
        allowed.append(cpu)
    allowed = sorted(set(allowed))
    if not allowed:
        missing.add("allowed_cpus")

    topology: list[dict] = []
    for cpu in allowed:
        base = f"/sys/devices/system/cpu/cpu{cpu}/topology"
        package_id = _read_int(provider, f"{base}/physical_package_id")
        core_id = _read_int(provider, f"{base}/core_id")
        siblings_raw = provider.read_text(f"{base}/thread_siblings_list")
        siblings = siblings_raw.strip() if siblings_raw is not None else None
        if package_id is None:
            missing.add(f"cpu_topology.cpu{cpu}.package_id")
        if core_id is None:
            missing.add(f"cpu_topology.cpu{cpu}.core_id")
        if siblings is None:
            missing.add(f"cpu_topology.cpu{cpu}.siblings")
        if package_id is None or core_id is None:
            continue
        topology.append(
            {
                "cpu": cpu,
                "package_id": package_id,
                "core_id": core_id,
                "siblings": siblings,
            }
        )

    return {
        "kind": "host-capabilities",
        "schema_version": 1,
        "environment": environment,
        "system": system,
        "architecture": machine,
        "kernel_release": kernel_release,
        "allowed_cpus": allowed,
        "cpu_topology": topology,
        "missing_fields": sorted(missing),
    }


def _mapping(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise BenchError(
            BM_SCHEMA_INVALID, f"{field} must be a JSON object", field_path=field
        )
    return value


def validate_host_capabilities(document: object) -> dict:
    """Validate the closed capability-record shape without reading the host."""

    record = _mapping(document, "host-capabilities")
    if set(record) != _CAPABILITY_KEYS:
        raise BenchError(
            BM_SCHEMA_INVALID,
            "host-capabilities must use the exact closed field set",
        )
    if record["kind"] != "host-capabilities" or record["schema_version"] != 1:
        raise BenchError(
            BM_SCHEMA_INVALID, "host-capabilities kind/version is invalid"
        )
    if record["environment"] not in _ENVIRONMENTS:
        raise BenchError(
            BM_SCHEMA_INVALID,
            "host-capabilities environment is not recognised",
            field_path="environment",
        )
    for field in ("system", "architecture", "kernel_release"):
        if not isinstance(record[field], str):
            raise BenchError(
                BM_SCHEMA_INVALID, f"{field} must be a string", field_path=field
            )
    allowed = record["allowed_cpus"]
    if not isinstance(allowed, list):
        raise BenchError(
            BM_SCHEMA_INVALID, "allowed_cpus must be an array", field_path="allowed_cpus"
        )
    previous = -1
    for index, cpu in enumerate(allowed):
        if isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0:
            raise BenchError(
                BM_SCHEMA_INVALID,
                "allowed_cpus entries must be non-negative integers",
                field_path=f"allowed_cpus[{index}]",
            )
        if cpu <= previous:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "allowed_cpus must be sorted and unique",
                field_path="allowed_cpus",
            )
        previous = cpu
    topology = record["cpu_topology"]
    if not isinstance(topology, list):
        raise BenchError(
            BM_SCHEMA_INVALID,
            "cpu_topology must be an array",
            field_path="cpu_topology",
        )
    last_cpu = -1
    for index, entry in enumerate(topology):
        item = _mapping(entry, f"cpu_topology[{index}]")
        if set(item) != _TOPOLOGY_KEYS:
            raise BenchError(
                BM_SCHEMA_INVALID,
                "cpu_topology entry must use the exact closed field set",
                field_path=f"cpu_topology[{index}]",
            )
        cpu = item["cpu"]
        if isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0:
            raise BenchError(
                BM_SCHEMA_INVALID,
                "cpu_topology.cpu must be a non-negative integer",
                field_path=f"cpu_topology[{index}].cpu",
            )
        if cpu <= last_cpu:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "cpu_topology must be sorted by cpu",
                field_path="cpu_topology",
            )
        last_cpu = cpu
        for field in ("package_id", "core_id"):
            value = item[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BenchError(
                    BM_SCHEMA_INVALID,
                    f"cpu_topology.{field} must be a non-negative integer",
                    field_path=f"cpu_topology[{index}].{field}",
                )
        if item["siblings"] is not None and not isinstance(item["siblings"], str):
            raise BenchError(
                BM_SCHEMA_INVALID,
                "cpu_topology.siblings must be a string or null",
                field_path=f"cpu_topology[{index}].siblings",
            )
    missing = record["missing_fields"]
    if not isinstance(missing, list):
        raise BenchError(
            BM_SCHEMA_INVALID,
            "missing_fields must be an array",
            field_path="missing_fields",
        )
    previous = None
    for index, value in enumerate(missing):
        if not isinstance(value, str):
            raise BenchError(
                BM_SCHEMA_INVALID,
                "missing_fields entries must be strings",
                field_path=f"missing_fields[{index}]",
            )
        if previous is not None and value <= previous:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "missing_fields must be sorted and unique",
                field_path="missing_fields",
            )
        previous = value
    return record

