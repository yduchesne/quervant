"""Untimed host-selector boundaries; no adapters, builds or live sampling."""

from __future__ import annotations

import copy
import tempfile
import unittest
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quervant_bench.config.codec import content_digest
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.host.capabilities import collect_host_capabilities
from quervant_bench.official import cross_engine_backend, operation_identity, protocols, workflow
from quervant_bench.official.operation_config import OperationConfig


class HostProvider:
    """Deterministic external host observations for the real capability reader."""

    def __init__(self, environment: str, *, missing_core: bool = False, same_core: bool = False):
        self.environment = environment
        self.missing_core = missing_core
        self.same_core = same_core

    def platform_record(self):
        if self.environment == "unsupported":
            return ("Darwin", "arm64", "23.0.0")
        kernel = "6.6.87-microsoft-standard-WSL2" if self.environment == "wsl2" else "6.6.87"
        return ("Linux", "x86_64", kernel)

    def allowed_cpu_ids(self):
        return (0, 1)

    def read_text(self, path):
        if path == "/proc/version":
            return self.platform_record()[2]
        if path.endswith("physical_package_id"):
            return "0"
        if path.endswith("core_id"):
            if self.missing_core:
                return None
            return "1" if "/cpu1/" in path and not self.same_core else "0"
        if path.endswith("thread_siblings_list"):
            return "0-1" if self.same_core else ("1" if "/cpu1/" in path else "0")
        return None


def host_template(selector="native-linux-or-wsl2", *, study_id=protocols.STUDY_CROSS_ENGINE):
    template = protocols.read_canonical_json(protocols.template_path(study_id))
    template["host_requirements"]["environment"] = selector
    return template


def cpu_config(adapter=0, controller=1):
    return OperationConfig({"adapter_cpu": adapter, "controller_cpu": controller})


class HostObservationTests(unittest.TestCase):
    def observe(self, provider, *, selector="native-linux-or-wsl2", config=None, study_id=protocols.STUDY_CROSS_ENGINE):
        with patch.object(operation_identity, "LinuxCapabilityProvider", return_value=provider):
            return operation_identity.observe_host(config or cpu_config(), host_template(selector, study_id=study_id))

    def test_union_accepts_both_hosts_and_preserves_the_observed_identity(self):
        for study_id in protocols.OFFICIAL_STUDIES:
            digests = []
            for environment in ("native-linux", "wsl2"):
                with self.subTest(study=study_id, environment=environment):
                    provider = HostProvider(environment)
                    observed = self.observe(provider, study_id=study_id)
                    self.assertEqual(observed["capabilities"], collect_host_capabilities(provider))
                    self.assertEqual(observed["capabilities"]["environment"], environment)
                    self.assertEqual((observed["adapter_cpu"], observed["controller_cpu"]), (0, 1))
                    digests.append(content_digest(observed))
            self.assertNotEqual(*digests)

    def test_literal_selectors_keep_their_existing_restriction(self):
        for study_id, selector in product(protocols.OFFICIAL_STUDIES, ("native-linux", "wsl2")):
            for observed in ("native-linux", "wsl2"):
                with self.subTest(study=study_id, selector=selector, observed=observed):
                    if selector == observed:
                        self.assertEqual(self.observe(HostProvider(observed), selector=selector, study_id=study_id)["capabilities"]["environment"], observed)
                    else:
                        with self.assertRaises(BenchError) as raised:
                            self.observe(HostProvider(observed), selector=selector, study_id=study_id)
                        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_EVIDENCE_UNAVAILABLE, "host"))

    def test_unsupported_and_incomplete_capabilities_still_fail(self):
        for study_id, provider in product(protocols.OFFICIAL_STUDIES,
                (HostProvider("unsupported"), HostProvider("native-linux", missing_core=True), HostProvider("wsl2", missing_core=True))):
            with self.subTest(study=study_id, environment=provider.environment, missing=provider.missing_core):
                with self.assertRaises(BenchError) as raised:
                    self.observe(provider, study_id=study_id)
                self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_EVIDENCE_UNAVAILABLE, "host"))

    def test_affinity_same_core_and_noninteger_cpu_rejections_remain(self):
        for study_id, environment in product(protocols.OFFICIAL_STUDIES, ("native-linux", "wsl2")):
            for config, same_core in ((cpu_config(2, 1), False), (cpu_config(0, 0), False),
                                      (cpu_config(True, 0), False), (cpu_config(0.0, 1), False),
                                      (cpu_config(), True)):
                with self.subTest(study=study_id, environment=environment, cpus=config.document, same_core=same_core):
                    with self.assertRaises(BenchError) as raised:
                        self.observe(HostProvider(environment, same_core=same_core), config=config, study_id=study_id)
                    self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_UNSAFE_INPUT, "cpu_pair"))


class CrossEngineHostIdentityTests(unittest.TestCase):
    def freeze(self, capabilities):
        observed = {"kind": "official-host-preflight", "schema_version": 1,
                    "capabilities": capabilities, "adapter_cpu": 0, "controller_cpu": 1}
        return SimpleNamespace(host_preflight_digest=content_digest(observed))

    def verify(self, capabilities, freeze=None, *, selector="native-linux-or-wsl2", adapter=0, controller=1):
        with patch.object(cross_engine_backend, "collect_host_capabilities", return_value=capabilities):
            cross_engine_backend._verify_cpu_pair(freeze or self.freeze(capabilities), adapter, controller,
                                                 template=host_template(selector))

    def test_both_hosts_require_their_exact_g0_host_identity(self):
        for environment in ("native-linux", "wsl2"):
            with self.subTest(environment=environment):
                capabilities = collect_host_capabilities(HostProvider(environment))
                self.verify(capabilities)
                changed = copy.deepcopy(capabilities)
                changed["kernel_release"] += "-changed"
                with self.assertRaises(BenchError) as raised:
                    self.verify(changed, self.freeze(capabilities))
                self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "host_preflight_digest"))

    def test_union_does_not_allow_switching_hosts_after_g0(self):
        native = collect_host_capabilities(HostProvider("native-linux"))
        wsl = collect_host_capabilities(HostProvider("wsl2"))
        with self.assertRaises(BenchError) as raised:
            self.verify(wsl, self.freeze(native))
        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_IDENTITY_INVALID, "host_preflight_digest"))

    def test_backend_rejects_unsupported_incomplete_wrong_selector_or_cpu(self):
        cases = [
            (HostProvider("unsupported"), "native-linux-or-wsl2", 0, 1),
            (HostProvider("wsl2", missing_core=True), "native-linux-or-wsl2", 0, 1),
            (HostProvider("wsl2"), "native-linux", 0, 1),
            (HostProvider("native-linux"), "wsl2", 0, 1),
            (HostProvider("wsl2"), "native-linux-or-wsl2", 2, 1),
            (HostProvider("wsl2", same_core=True), "native-linux-or-wsl2", 0, 1),
            (HostProvider("wsl2"), "native-linux-or-wsl2", True, 0),
        ]
        for provider, selector, adapter, controller in cases:
            with self.subTest(environment=provider.environment, selector=selector, cpu=(adapter, controller),
                              missing=provider.missing_core, same_core=provider.same_core):
                with self.assertRaises(BenchError) as raised:
                    self.verify(collect_host_capabilities(provider), selector=selector, adapter=adapter, controller=controller)
                self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_UNSAFE_INPUT, "cpu_pair"))


class HostReadinessSelectorTests(unittest.TestCase):
    def test_workflow_and_backend_apply_the_same_selector_to_live_readiness(self):
        cases = (
            ("native-linux-or-wsl2", "native-linux", "READY", True),
            ("native-linux-or-wsl2", "wsl2", "READY", True),
            ("native-linux", "native-linux", "READY", True),
            ("wsl2", "wsl2", "READY", True),
            ("native-linux", "wsl2", "READY", False),
            ("wsl2", "native-linux", "READY", False),
            ("native-linux-or-wsl2", "unsupported", "READY", False),
            ("native-linux-or-wsl2", "native-linux-or-wsl2", "READY", False),
            ("native-linux-or-wsl2", True, "READY", False),
            ("native-linux-or-wsl2", "wsl2", "BLOCKED", False),
        )
        for study_id, (selector, environment, status, accepted) in product(protocols.OFFICIAL_STUDIES, cases):
            with self.subTest(study=study_id, selector=selector, environment=environment, status=status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                template = host_template(selector, study_id=study_id)
                record = {"status": status, "environment": environment}
                operation = SimpleNamespace(template=template, config=cpu_config(), directory=root,
                                            authorization=SimpleNamespace(study_id=study_id))
                with patch.object(workflow.controls, "collect_real_readiness", return_value=record) as collector:
                    if accepted:
                        self.assertEqual(workflow._readiness(operation), record)
                    else:
                        with self.assertRaises(BenchError) as raised:
                            workflow._readiness(operation)
                        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_EVIDENCE_UNAVAILABLE, "host_readiness"))
                    collector.assert_called_once()
                self.assertEqual(protocols.read_canonical_json(root / "host-readiness.json"), record)
                if study_id != protocols.STUDY_CROSS_ENGINE:
                    continue
                with patch.object(cross_engine_backend, "_template", return_value=template), \
                        patch.object(cross_engine_backend, "collect_real_readiness", return_value=record) as collector:
                    if accepted:
                        self.assertEqual(cross_engine_backend._readiness(root, root / "backend-readiness.json", 0, 1), record)
                    else:
                        with self.assertRaises(BenchError) as raised:
                            cross_engine_backend._readiness(root, root / "backend-readiness.json", 0, 1)
                        self.assertEqual((raised.exception.code, raised.exception.field_path), (BM_ACQUISITION_PROHIBITED, "readiness"))
                    collector.assert_called_once()
                self.assertEqual(protocols.read_canonical_json(root / "backend-readiness.json"), record)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
