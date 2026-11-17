"""O09-CTL: live readiness sampling and exact A/A control windows."""

from __future__ import annotations

import unittest
from fractions import Fraction

from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.host.readiness import ReadinessLimits
from quervant_bench.official import controls
from quervant_bench.tests import official_support as support


def _advancing_clock():
    state = {"now": 0.0}

    def clock() -> float:
        state["now"] += 1.0
        return state["now"]

    return clock


def _limits(**overrides: int) -> ReadinessLimits:
    values = {
        "min_interval_ms": 800,
        "max_interval_ms": 1500,
        "max_busy_permille": 250,
        "max_median_busy_permille": 100,
        "max_steal_permille": 20,
        "min_intervals": 6,
    }
    values.update(overrides)
    return ReadinessLimits(**values)


class ProcStatTests(unittest.TestCase):
    def test_o09_ctl_05_proc_stat_rows_are_parsed_per_cpu(self) -> None:
        rows = controls.parse_proc_stat(
            "cpu  1 2 3 4 5 6 7 8\ncpu0 10 0 5 100 0 0 0 0\ncpu1 10 0 5 80 0 0 0 0\n"
        )
        self.assertEqual(sorted(rows), ["0", "1"])
        self.assertEqual(len(rows["0"]), 8)

    def test_o09_ctl_05b_truncated_or_nonintegral_rows_fail_closed(self) -> None:
        for text in ("cpu0 1 2 3\n", "cpu0 a 0 0 0 0 0 0 0\n"):
            with self.assertRaises(BenchError) as raised:
                controls.parse_proc_stat(text)
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_ctl_06_interval_math_boundaries(self) -> None:
        before = {"0": (0, 0, 0, 100, 0, 0, 0, 0)}
        after_one_over = {"0": (0, 0, 0, 899, 0, 0, 0, 0)}
        total, busy, steal = controls.compute_interval(before, after_one_over, 0)
        self.assertEqual(total, 799)
        self.assertEqual(busy, 0)
        self.assertEqual(steal, 0)
        after_steal = {"0": (0, 0, 0, 1080, 0, 0, 0, 20)}
        _total, _busy, steal = controls.compute_interval(before, after_steal, 0)
        self.assertEqual(steal, 20)
        self.assertEqual(_busy, 20)

    def test_o09_ctl_06b_backwards_counters_fail_closed(self) -> None:
        with self.assertRaises(BenchError) as raised:
            controls.compute_interval(
                {"0": (10, 0, 0, 100, 0, 0, 0, 0)},
                {"0": (10, 0, 0, 90, 0, 0, 0, 0)},
                0,
            )
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_ctl_07_unsupported_platform_is_rejected(self) -> None:
        class UnsupportedProvider:
            def read_text(self, path: str) -> str | None:
                if path == "/proc/version":
                    return "Linux"
                return None

            def allowed_cpu_ids(self) -> tuple[int, ...]:
                return (0, 1)

            def platform_record(self) -> tuple[str, str, str]:
                return ("Darwin", "arm64", "23.0.0")

        with self.assertRaises(BenchError) as raised:
            controls.collect_real_readiness(
                study_id="cross-engine-keyword-real-v1",
                adapter_cpu=0,
                controller_cpu=1,
                limits=_limits(),
                intervals=1,
                interval_ms=1,
                provider=UnsupportedProvider(),
            )
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_o09_ctl_08_same_cpu_pair_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            controls.sample_host(
                adapter_cpu=2,
                controller_cpu=2,
                intervals=1,
                interval_ms=1,
                read_text=lambda _path: None,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ctl_08b_wsl2_topology_is_accepted_but_reported(self) -> None:
        class WslProvider:
            def __init__(self) -> None:
                self.calls = 0

            def read_text(self, path: str) -> str | None:
                if path == "/proc/version":
                    return "Linux version 5.15 microsoft-standard-WSL2"
                if path == "/proc/stat":
                    self.calls += 1
                    idle = 100 * self.calls
                    return (
                        f"cpu0 0 0 0 {idle} 0 0 0 0\n"
                        f"cpu1 0 0 0 {idle} 0 0 0 0\n"
                    )
                if path.endswith("physical_package_id"):
                    return "0"
                if path.endswith("core_id"):
                    return "1" if "cpu1" in path else "0"
                if path.endswith("thread_siblings_list"):
                    return "0"
                return None

            def allowed_cpu_ids(self) -> tuple[int, ...]:
                return (0, 1)

            def platform_record(self) -> tuple[str, str, str]:
                return ("Linux", "x86_64", "5.15.90.1-microsoft-standard-WSL2")

        record = controls.collect_real_readiness(
            study_id="cross-engine-keyword-real-v1",
            adapter_cpu=0,
            controller_cpu=1,
            limits=_limits(min_intervals=1, min_interval_ms=1, max_interval_ms=5_000),
            intervals=1,
            interval_ms=1,
            provider=WslProvider(),
            sleep=lambda _seconds: None,
            clock=_advancing_clock(),
        )
        self.assertEqual(record["environment"], "wsl2")
        self.assertEqual(record["status"], "READY")

    def test_o09_ctl_08c_busy_host_is_blocked_not_ready(self) -> None:
        class BusyProvider:
            def __init__(self) -> None:
                self.calls = 0

            def read_text(self, path: str) -> str | None:
                if path == "/proc/version":
                    return "Linux"
                if path == "/proc/stat":
                    self.calls += 1
                    busy = 900 * self.calls
                    idle = 100 * self.calls
                    return (
                        f"cpu0 {busy} 0 0 {idle} 0 0 0 0\n"
                        f"cpu1 {busy} 0 0 {idle} 0 0 0 0\n"
                    )
                if path.endswith("physical_package_id"):
                    return "0"
                if path.endswith("core_id"):
                    return "1" if "cpu1" in path else "0"
                if path.endswith("thread_siblings_list"):
                    return "0"
                return None

            def allowed_cpu_ids(self) -> tuple[int, ...]:
                return (0, 1)

            def platform_record(self) -> tuple[str, str, str]:
                return ("Linux", "x86_64", "6.1.0")

        record = controls.collect_real_readiness(
            study_id="cross-engine-keyword-real-v1",
            adapter_cpu=0,
            controller_cpu=1,
            limits=_limits(min_intervals=1, min_interval_ms=1, max_interval_ms=5_000),
            intervals=1,
            interval_ms=1,
            provider=BusyProvider(),
            sleep=lambda _seconds: None,
            clock=_advancing_clock(),
        )
        self.assertEqual(record["status"], "BLOCKED")
        self.assertTrue(record["reasons"])


class WindowTests(unittest.TestCase):
    def _classify(self, ratios: list[str], *, exempt: bool = False) -> dict:
        return controls.classify_ratios(
            [Fraction(value) for value in ratios],
            controls.frozen_windows(),
            exempt=exempt,
        )

    def test_o09_ctl_09_median_window_inclusivity(self) -> None:
        self.assertTrue(self._classify(["0.85"] * 12)["passes"])
        self.assertTrue(self._classify(["1.15"] * 12)["passes"])
        self.assertFalse(self._classify(["0.84"] * 12)["passes"])
        self.assertFalse(self._classify(["1.16"] * 12)["passes"])

    def test_o09_ctl_10_block_window_inclusivity(self) -> None:
        self.assertTrue(self._classify(["1.0"] * 11 + ["0.80"])["passes"])
        self.assertTrue(self._classify(["1.0"] * 11 + ["1.25"])["passes"])
        self.assertFalse(self._classify(["1.0"] * 11 + ["0.79"])["passes"])
        self.assertFalse(self._classify(["1.0"] * 11 + ["1.26"])["passes"])

    def test_o09_ctl_11_exempt_hard_bounds(self) -> None:
        self.assertTrue(self._classify(["1.0"] * 11 + ["0.67"], exempt=True)["passes"])
        self.assertTrue(self._classify(["1.0"] * 11 + ["1.50"], exempt=True)["passes"])
        self.assertFalse(self._classify(["1.0"] * 11 + ["0.66"], exempt=True)["passes"])
        self.assertFalse(self._classify(["1.0"] * 11 + ["1.51"], exempt=True)["passes"])

    def test_o09_ctl_12_two_soft_outliers_are_rejected(self) -> None:
        ratios = ["1.0"] * 10 + ["0.70", "1.40"]
        self.assertFalse(self._classify(ratios, exempt=True)["passes"])
        self.assertTrue(self._classify(ratios[:-1] + ["1.0"], exempt=True)["passes"])

    def test_o09_ctl_12b_decimal_rounding_is_fixed_six_digits(self) -> None:
        self.assertEqual(controls.decimal_string(Fraction(1, 3)), "0.333333")
        self.assertEqual(controls.decimal_string(Fraction(2, 3)), "0.666667")


class ControlAssessmentTests(unittest.TestCase):
    def test_o09_ctl_01_valid_control_passes(self) -> None:
        assessment = support.make_cross_engine_control()
        self.assertTrue(assessment["a_a"]["passes"])
        self.assertEqual(assessment["slot_count"], 48)
        self.assertEqual(assessment["block_count"], 12)
        self.assertEqual(len(assessment["lanes"]), 16)

    def test_o09_ctl_02_missing_slot_is_rejected(self) -> None:
        slots = support.make_control_slots()[:-1]
        with self.assertRaises(BenchError):
            controls.assess_cross_engine_control(
                slots=slots, warm_lane_ids=support.admission.pr15d_warm_lane_ids()
            )

    def test_o09_ctl_02b_duplicate_slot_number_is_rejected(self) -> None:
        slots = support.make_control_slots()
        slots[1] = dict(slots[1], slot=slots[0]["slot"])
        with self.assertRaises(BenchError) as raised:
            controls.assess_cross_engine_control(
                slots=slots, warm_lane_ids=support.admission.pr15d_warm_lane_ids()
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ctl_03_non_ascending_or_short_lane_set_is_rejected(self) -> None:
        slots = support.make_control_slots()
        slots[0] = dict(slots[0], lanes=list(reversed(slots[0]["lanes"])))
        with self.assertRaises(BenchError) as raised:
            controls.assess_cross_engine_control(
                slots=slots, warm_lane_ids=support.admission.pr15d_warm_lane_ids()
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ctl_04_nineteen_samples_are_rejected(self) -> None:
        slots = support.make_control_slots()
        broken = [dict(lane) for lane in slots[0]["lanes"]]
        broken[0] = dict(broken[0], samples_ns=broken[0]["samples_ns"][1:])
        slots[0] = dict(slots[0], lanes=broken)
        with self.assertRaises(BenchError) as raised:
            controls.assess_cross_engine_control(
                slots=slots, warm_lane_ids=support.admission.pr15d_warm_lane_ids()
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ctl_04b_noisy_control_is_rejected(self) -> None:
        slots = support.make_control_slots()
        for slot in slots:
            if slot["arm"] == "B":
                slot["lanes"] = [
                    {"lane_id": lane["lane_id"], "samples_ns": [value * 2 for value in lane["samples_ns"]]}
                    for lane in slot["lanes"]
                ]
        assessment = controls.assess_cross_engine_control(
            slots=slots, warm_lane_ids=support.admission.pr15d_warm_lane_ids()
        )
        self.assertFalse(assessment["a_a"]["passes"])
        with self.assertRaises(BenchError) as raised:
            controls.require_control_pass(assessment)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()
