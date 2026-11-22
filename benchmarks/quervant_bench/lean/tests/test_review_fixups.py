"""BM-10 F1-F4 regression tests. Never build, invoke, or time real engines."""
from __future__ import annotations

import contextlib
from copy import deepcopy

import pytest

from quervant_bench.lean import artifacts, configuration, runtime, statistics


def _policy(*, seed: int = 17) -> dict:
    return {
        "blocks": 4, "slots_per_arm": 2, "samples": 3,
        "bootstrap_resamples": 100, "seed": seed, "min_blocks": 4,
        "min_gain_percent": 0, "max_regression_percent": 0,
        "max_aa_gain_percent": 15, "exclude_blocks": {}, "control_arms": [],
    }


def _samples(arms=("A", "B"), *, seed=17):
    return [
        {
            "arm_id": s["arm_id"], "block": s["block"], "position": s["position"],
            "lane_id": "lane", "oracle_ok": True,
            "samples_ns": [100 if s["arm_id"] == arms[0] else 80] * 3,
        }
        for s in statistics.schedule(arms, blocks=4, slots_per_arm=2, seed=seed)
    ]


def _lane():
    return {
        "id": "lane", "metric": "search_latency", "unit": "ns",
        "direction": "lower", "comparability": "COMPARABLE",
        "workload_id": "same-work", "cache_regime": "warm",
        "timed_operation": "exact-term-search-plus-topk-projection",
        "query_semantics": "exact-keyword-total-hits-and-ordered-doc-ids",
    }


def test_f2_seeded_schedule_is_required_not_just_block_multiplicity():
    rows = _samples()
    good = statistics.analyze(
        rows, arms=["A", "B"], baseline="A", lanes=[_lane()], policy=_policy()
    )
    assert good["lanes"]["lane"]["comparisons"]["B"]["ratio_b_over_a"] == 0.8
    reordered = deepcopy(rows)
    # Swap the two arm identities in block 1. Its counts remain 2 + 2, but
    # the seeded slot assignment is no longer the one declared in the policy.
    for item in reordered:
        if item["block"] == 1:
            item["arm_id"] = "B" if item["arm_id"] == "A" else "A"
    with pytest.raises(artifacts.ArtifactError, match="declared seeded schedule"):
        statistics.analyze(reordered, arms=["A", "B"], baseline="A",
                           lanes=[_lane()], policy=_policy())
    # Two different seeds can coincidentally generate the same small schedule.
    # Select a seed that actually produces another assignment, rather than
    # treating distinct seed values as proof of changed acquired work.
    other_seed = next(
        seed for seed in range(18, 512)
        if statistics.schedule(("A", "B"), blocks=4, slots_per_arm=2, seed=seed)
        != statistics.schedule(("A", "B"), blocks=4, slots_per_arm=2, seed=17)
    )
    with pytest.raises(artifacts.ArtifactError, match="declared seeded schedule"):
        statistics.analyze(rows, arms=["A", "B"], baseline="A",
                           lanes=[_lane()], policy=_policy(seed=other_seed))


def _valid_effect_run():
    samples = _samples()
    return {
        "status": "COMPLETE",
        "analysis": statistics.analyze(
            samples, arms=["A", "B"], baseline="A", lanes=[_lane()], policy=_policy()
        ),
        "raw_samples": samples,
        "lanes": [_lane()],
        "context": {"host": "same-host"},
        "controls": {
            "analysis": {"lanes": {"lane": {
                "comparisons": {"AA2": {"status": "PASS"}}
            }}},
            "readiness_index_pre": {"status": "clear"},
            "readiness_pre": {"status": "clear"},
            "readiness_treatment": {"status": "clear"},
            "readiness_post": {"status": "clear"},
        },
    }


def _compare(current, history):
    return statistics.compare_historical(
        current, history, lane_id="lane", treatment_arm="B"
    )


def test_f3_valid_effects_retain_run_status_ci_and_pp_difference():
    current = _valid_effect_run()
    historical = deepcopy(current)
    outcome = _compare(current, historical)
    assert outcome["status"] == "COMPARABLE"
    assert outcome["effect_change_percentage_points"] == 0
    assert outcome["current_run_status"] == "COMPLETE"
    assert outcome["historical_run_status"] == "COMPLETE"
    assert len(outcome["current_gain_ci_95_percent"]) == 2
    assert len(outcome["historical_gain_ci_95_percent"]) == 2


@pytest.mark.parametrize("invalid_field", ["status", "aa", "readiness", "oracle", "missing_raw"])
def test_f3_invalidated_or_incomplete_runs_never_yield_numeric_gain(invalid_field):
    current = _valid_effect_run()
    historical = deepcopy(current)
    if invalid_field == "status":
        historical["status"] = "INCOMPLETE"  # post-treatment host contention
    elif invalid_field == "aa":
        historical["controls"]["analysis"]["lanes"]["lane"]["comparisons"]["AA2"]["status"] = "FAIL"
    elif invalid_field == "readiness":
        historical["controls"]["readiness_post"]["status"] = "busy"
    elif invalid_field == "oracle":
        historical["raw_samples"][0]["oracle_ok"] = False
    elif invalid_field == "missing_raw":
        historical["raw_samples"] = []
    outcome = _compare(current, historical)
    assert outcome["status"] == "UNAVAILABLE"
    assert "effect_change_percentage_points" not in outcome
    # The current run being incomplete must also fail closed.
    if invalid_field == "status":
        current["status"] = "INCOMPLETE"
        outcome = _compare(current, _valid_effect_run())
        assert outcome["status"] == "UNAVAILABLE"
        assert "effect_change_percentage_points" not in outcome


@pytest.mark.parametrize("controls", [
    None, {}, {"analysis": None}, {"analysis": {"lanes": None}},
    {"analysis": {"lanes": {"lane": {"comparisons": None}}}},
])
def test_f3_malformed_control_structure_is_unavailable_not_uncaught(controls):
    historical = _valid_effect_run()
    historical["controls"] = controls
    result = _compare(_valid_effect_run(), historical)
    assert result["status"] == "UNAVAILABLE"
    assert "effect_change_percentage_points" not in result


@pytest.mark.parametrize(("field", "value"), [
    ("seed", -1), ("seed", 2**64), ("seed", True), ("seed", "17"),
    ("min_gain_percent", -0.1), ("min_gain_percent", float("nan")),
    ("max_regression_percent", -1), ("max_regression_percent", float("inf")),
    ("max_aa_gain_percent", -1), ("max_aa_gain_percent", "15"),
])
def test_f4_invalid_statistical_policy_is_rejected_at_validation(field, value):
    cfg = configuration.default_configuration(
        "retained-key", "policy-boundary", "Pre-acquisition policy validation"
    )
    cfg["policy"][field] = value
    with pytest.raises(artifacts.ArtifactError, match=r"policy\."):
        configuration.validate_configuration(cfg)


@pytest.mark.parametrize("excluded", [
    {"unknown-lane": [1]},
    {"10000/rare/k1/warm": [0]},
    {"10000/rare/k1/warm": [13]},
    {"10000/rare/k1/warm": [1, 1]},
    {"10000/rare/k1/warm": ["1"]},
])
def test_f4_rejects_bad_exclusion_policy_before_acquisition(excluded):
    cfg = configuration.default_configuration(
        "retained-key", "excluded-boundary", "Policy exclusion contract"
    )
    cfg["policy"]["exclude_blocks"] = excluded
    with pytest.raises(artifacts.ArtifactError, match="exclude_blocks"):
        configuration.validate_configuration(cfg)


def _mocked_cross(tmp_path, monkeypatch, statuses):
    cfg = configuration.default_configuration(
        "cross-engine", "readiness-phase", "Host readiness around timed phases"
    )
    cfg["policy"].update(samples=3, bootstrap_resamples=100)
    path = artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", cfg), cfg)
    lanes = [lane for lane in configuration.lanes_for(cfg)
             if lane["id"] == "10000/medium/k10/warm"]
    monkeypatch.setattr(runtime, "lanes_for", lambda config: lanes)
    monkeypatch.setattr(runtime, "create_corpus", lambda path, n: path.write_text("mock"))
    monkeypatch.setattr(runtime, "host_context", lambda scratch, check: {
        "physical_core_candidates": [(0, 0, 0), (1, 0, 1)],
    })
    monkeypatch.setattr(runtime, "pinned_controller", lambda cpu: contextlib.nullcontext())
    events = []
    pending = iter(statuses)

    def assess(*args, **kwargs):
        status = next(pending)
        events.append("readiness:" + status)
        return {"status": status, "observations": []}

    def build(*args, **kwargs):
        events.append("index")
        return {
            "index_ns": 1, "commit_ns": 1, "reopen_ns": 1,
            "index_bytes": 1, "segment_count": 1,
        }

    def fake_phase(config, actual_lanes, binaries, indexes, *, cpu, on_slot):
        phase = "control" if "AA" in config["arms"] else "treatment"
        events.append(phase)
        values = {"AA": 100, "AA2": 100, "Q": 100, "T": 120, "J": 130}
        slots = statistics.schedule(
            list(config["arms"]), blocks=config["policy"]["blocks"],
            slots_per_arm=config["policy"]["slots_per_arm"],
            seed=config["policy"]["seed"],
        )
        rows = [{
            "arm_id": x["arm_id"], "block": x["block"],
            "position": x["position"], "lane_id": lanes[0]["id"],
            "oracle_ok": True, "samples_ns": [values[x["arm_id"]]] * 3,
        } for x in slots]
        on_slot(rows)
        return rows

    def throughput(*args, **kwargs):
        events.append("throughput")
        return {
            "lane_id": lanes[0]["id"], "requests": 100,
            "serial_ops_per_second": 100, "wall_ns": 10**9,
            "status": "MEASURED",
        }

    monkeypatch.setattr(runtime, "assess_readiness", assess)
    monkeypatch.setattr(runtime, "_phase", fake_phase)
    monkeypatch.setattr(runtime, "collect_throughput", throughput)
    saved, result = runtime.run_benchmark(
        path, path.parent.parent / "results", root=tmp_path,
        programs={name: ["/mock"] for name in cfg["arms"]},
        check_host=True, index_builder=build,
    )
    return events, saved, result


def test_f1_busy_before_indexing_prevents_measuring(tmp_path, monkeypatch):
    events, saved, result = _mocked_cross(tmp_path, monkeypatch, ["busy"])
    assert events == ["readiness:busy"]
    assert result["status"] == "INCOMPLETE"
    assert "before indexing" in result["errors"][0]
    assert artifacts.load_result(saved)["status"] == "INCOMPLETE"


def test_f1_post_index_readiness_invalidates_index_metrics(tmp_path, monkeypatch):
    events, _, result = _mocked_cross(tmp_path, monkeypatch, ["clear", "busy"])
    assert events[0] == "readiness:clear"
    assert events[-1] == "readiness:busy"
    assert events.count("index") == 6  # three engines, two corpora
    assert "control" not in events
    assert result["status"] == "INCOMPLETE"
    assert "before A/A" in result["errors"][0]


def test_f1_no_throughput_after_precheck_fails(tmp_path, monkeypatch):
    events, _, result = _mocked_cross(
        tmp_path, monkeypatch, ["clear", "clear", "clear", "clear", "busy"]
    )
    assert events[-1] == "readiness:busy"
    assert "throughput" not in events
    assert result["status"] == "INCOMPLETE"
    assert "before throughput" in result["errors"][0]
    assert result["analysis"]["lanes"]


def test_f1_post_throughput_readiness_preserves_samples_but_invalidates(tmp_path, monkeypatch):
    events, saved, result = _mocked_cross(
        tmp_path, monkeypatch, ["clear", "clear", "clear", "clear", "clear", "busy"]
    )
    assert events[-1] == "readiness:busy"
    assert events.count("throughput") == 3
    assert result["status"] == "INCOMPLETE"
    assert "after throughput" in result["errors"][0]
    assert result["raw_samples"] and result["analysis"]["lanes"]
    assert artifacts.load_result(saved)["raw_samples"] == result["raw_samples"]


def test_f1_all_timed_phases_have_host_readiness_controls(tmp_path, monkeypatch):
    events, _, result = _mocked_cross(tmp_path, monkeypatch, ["clear"] * 6)
    assert result["status"] == "COMPLETE"
    assert events[0] == "readiness:clear"
    assert events.count("readiness:clear") == 6
    assert events.index("index") > events.index("readiness:clear")
    assert events.index("control") > max(i for i, item in enumerate(events[:events.index("control")]) if item == "readiness:clear")
    assert events[-1] == "readiness:clear"
    for phase in ("readiness_index_pre", "readiness_pre", "readiness_treatment",
                  "readiness_post", "readiness_throughput_pre", "readiness_throughput_post"):
        assert result["controls"][phase]["status"] == "clear"
