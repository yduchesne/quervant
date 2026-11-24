"""PERF-06-A4 deterministic family-registration and qualification-policy tests.

Everything here is untimed and mocked: no real adapter, compiler, index,
filesystem cache or benchmark acquisition is executed. The only *production*
timer references are the existing framework seams already covered elsewhere;
these tests prove that `perf-06` delegates to the accepted `perf-02` two-pinned
arm paired A/B path without a new runner, estimator or timing boundary.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from subprocess import CompletedProcess
from uuid import uuid4

import pytest

from quervant_bench.lean import (artifacts, cli, configuration, preparation,
                                 runtime, statistics)

A_SHA = "a" * 40
B_SHA = "b" * 40
DESCRIPTION = (
    "PERF-06-A4 cumulative A1-A3 paired warm qualification against accepted "
    "pre-A1 PERF-05 source; independent indexes, query-only timing"
)

PRIMARY_LANES = {
    "100000/medium/k10/warm",
    "100000/medium/k100/warm",
    "100000/common/k10/warm",
    "100000/common/k100/warm",
}
TREATMENT_STATUSES = {"IMPROVED", "REGRESSED", "INCONCLUSIVE"}
OUTCOMES = {
    "PERF06_A4_PAIRED_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED",
    "PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED",
    "PERF06_A4_PAIRED_INCONCLUSIVE_REVIEW_REQUIRED",
    "PERF06_A4_INCOMPLETE_STOP",
}


def _config(tmp_path: Path, *, family: str = "perf-06",
            name: str = "quervant-perf06a-paired-warm",
            timestamp: str = "2026-11-23T10:00:00Z",
            policy: dict | None = None,
            quervant_revision: str | None = None) -> tuple[Path, dict]:
    kwargs: dict = {}
    if family in ("perf-02", "perf-06"):
        kwargs = {"baseline_revision": A_SHA, "candidate_revision": B_SHA}
    elif family == "perf-05":
        kwargs = {"quervant_revision": quervant_revision or B_SHA}
    config = configuration.default_configuration(
        family, name, DESCRIPTION, timestamp=timestamp, regime="warm", **kwargs)
    if policy:
        config["policy"].update(policy)
    path = artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", config), config)
    return path, config


def _small_policy() -> dict:
    """Same block/slot/lane topology; fewer per-slot samples for unit speed."""
    return {"blocks": 12, "slots_per_arm": 2, "samples": 5, "warmups": 2,
            "bootstrap_resamples": 1000, "min_blocks": 4}


def _mock_preparation(monkeypatch, *, oracle=None):
    """Mock compilers/corpus/indexes; keep the real cache and oracle checks."""
    calls: list[str] = []

    def source(root, config):
        return {"family": config["family"],
                "arm_source_revisions": {arm: spec["revision"]
                                         for arm, spec in config["arms"].items()},
                "configuration_hash": preparation._digest(config)}

    def build(config, root, scratch):
        calls.append("build")
        commands: dict[str, list[str]] = {}
        for arm in config["arms"]:
            binary = (scratch / "build" / f"quervant-{arm.lower()}" / "release"
                      / "pr15d-quervant-adapter")
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text(f"binary:{arm}:{config['arms'][arm]['revision']}")
            commands[arm] = [str(binary)]
        return commands, {
            "compiler_options": "cargo --release --locked",
            "quervant_strategy_feature_enabled": False,
            "arm_source_revisions": {arm: spec["revision"]
                                     for arm, spec in config["arms"].items()},
        }

    def corpus(path, n):
        calls.append(f"corpus:{n}")
        path.write_text(f"corpus:{n}")

    def index(command, *, engine, corpus_path, target, n, cpu):
        calls.append(f"index:{engine}:{n}")
        target.mkdir(parents=True)
        (target / "index.data").write_text(f"index:{command[0]}:{n}")
        return {"index_ns": 3, "commit_ns": 4, "reopen_ns": 5, "index_bytes": 6}

    def runner(argv, cpu, *, env, input_text, timeout):
        requests = [json.loads(line) for line in input_text.splitlines()]
        arm = "A" if "quervant-a" in Path(argv[0]).parts else "B"
        size = int(Path(argv[-1]).name.removeprefix("n"))
        calls.append(f"oracle:{arm}:{size}")
        rows = []
        for request in requests:
            hits, doc_ids = runtime.expected_answer(
                size, request["field"], request["term"], request["k"])
            if oracle is not None:
                hits, doc_ids = oracle(arm, size, request, hits, doc_ids)
            rows.append({"schema": runtime.ADAPTER_SCHEMA, "engine": "quervant",
                         "request_id": request["request_id"], "status": "ok",
                         "total_hits": hits, "doc_ids": doc_ids, "engine_ns": 100})
        return CompletedProcess(argv, 0, "".join(json.dumps(r) + "\n" for r in rows), "")

    monkeypatch.setattr(preparation, "source_identity", source)
    monkeypatch.setattr(runtime, "build_programs", build)
    monkeypatch.setattr(runtime, "create_corpus", corpus)
    monkeypatch.setattr(runtime, "build_index", index)
    monkeypatch.setattr(runtime, "_run_pinned", runner)
    return calls


def _mock_phase(monkeypatch, *, values: dict[str, int]):
    """Deterministic slot acquisition honouring the declared schedule."""
    def phase(config, lanes, binaries, indexes, *, cpu, on_slot):
        scheduled = statistics.schedule(
            list(config["arms"]), blocks=config["policy"]["blocks"],
            slots_per_arm=config["policy"]["slots_per_arm"],
            seed=config["policy"]["seed"])
        rows = [{"arm_id": slot["arm_id"], "block": slot["block"],
                 "position": slot["position"], "lane_id": lane["id"],
                 "warmups": config["policy"]["warmups"],
                 "samples_ns": [values[slot["arm_id"]]] * config["policy"]["samples"],
                 "oracle_ok": True, "strategy_marker": None}
                for slot in scheduled for lane in lanes]
        on_slot(rows)
        return rows

    monkeypatch.setattr(runtime, "_phase", phase)


def _no_host(monkeypatch):
    monkeypatch.setattr(runtime, "host_context", lambda path, check: {
        "physical_core_candidates": [], "filesystem": "MOCKED"})
    monkeypatch.setattr(runtime, "_git", lambda root, *args: "c" * 40)


# U01 -----------------------------------------------------------------------
def test_a4_u01_perf06_config_is_exact_paired_pinned_warm(tmp_path):
    path, config = _config(tmp_path)
    assert path.parent.as_posix().endswith("/perf-06/warm/configurations")
    assert config["family"] == "perf-06"
    assert config["baseline"] == "A"
    assert set(config["arms"]) == {"A", "B"}
    assert config["arms"]["A"] == {"engine": "quervant", "mode": "by-top-k",
                                   "source": "pinned", "revision": A_SHA}
    assert config["arms"]["B"]["revision"] == B_SHA
    assert config["control"] == {"enabled": True, "baseline": "AA", "equivalent": "AA2"}
    assert config["build"] == {"release": True, "locked": True, "baseline_ref": None,
                               "prefilter_profile": "P2", "quervant_feature": None}
    lanes = configuration.lanes_for(config)
    assert len(lanes) == 16
    assert {lane["cache_regime"] for lane in lanes} == {"warm"}
    assert {lane["timed_operation"] for lane in lanes} == {
        "exact-term-search-plus-topk-projection"}
    assert config["workload"]["top_k"] == [10, 100]
    assert config["workload"]["sizes"] == [10_000, 100_000]
    assert config["workload"]["classes"] == ["absent", "rare", "medium", "common"]
    assert config["policy"] == {
        "blocks": 12, "slots_per_arm": 2, "warmups": 5, "samples": 20,
        "bootstrap_resamples": 10_000, "seed": 20261122, "min_blocks": 4,
        "min_gain_percent": 0, "max_regression_percent": 0,
        "max_aa_gain_percent": 15, "exclude_blocks": {}, "control_arms": [],
        "readiness": {"intervals": 4, "interval_ms": 250,
                      "max_busy_percent": 25, "max_steal_percent": 2},
    }
    # Only the family (plus its freshly allocated identity) may differ from the
    # already accepted two-pinned-arm PERF-02 operational shape.
    paired = configuration.default_configuration(
        "perf-02", config["name"], DESCRIPTION, timestamp=config["created_utc"],
        baseline_revision=A_SHA, candidate_revision=B_SHA)
    for payload in (config, paired):
        for field in ("configuration_id", "created_utc"):
            payload.pop(field)
        payload.pop("family")
    assert config == paired
    assert artifacts.load_configuration(path)["configuration_id"]
    assert artifacts.result_directory(path) == path.parent.parent / "results"


# U02 -----------------------------------------------------------------------
def _valid_config() -> dict:
    return configuration.default_configuration(
        "perf-06", "quervant-perf06a-paired-warm", DESCRIPTION,
        timestamp="2026-11-23T10:00:00Z", baseline_revision=A_SHA,
        candidate_revision=B_SHA)


@pytest.mark.parametrize("mutation", [
    lambda c: c["arms"].pop("A"),
    lambda c: c["arms"].pop("B"),
    lambda c: c["arms"]["A"].__setitem__("revision", None),
    lambda c: c["arms"]["B"].__setitem__("revision", B_SHA[:39]),
    lambda c: c["arms"]["B"].__setitem__("revision", B_SHA.upper()),
    lambda c: c["arms"]["B"].__setitem__("revision", "main"),
    lambda c: c["arms"]["B"].__setitem__("source", "current"),
    lambda c: c["arms"]["B"].__setitem__("engine", "tantivy"),
    lambda c: c["arms"]["B"].__setitem__("mode", "prefilter"),
    lambda c: c["arms"]["A"].__setitem__("engine", "lucene"),
    lambda c: c["arms"].__setitem__("C", deepcopy(c["arms"]["B"])),
    lambda c: c.__setitem__("baseline", "B"),
    lambda c: c["workload"].__setitem__("regimes", ["process-cold"]),
    lambda c: c["workload"].__setitem__("top_k", [32]),
    lambda c: c["control"].__setitem__("baseline", "BB"),
    lambda c: c["control"].__setitem__("enabled", False),
    lambda c: c["build"].__setitem__("quervant_feature",
                                     "quervant-core/pr15i-d3c-experiment"),
    lambda c: c["build"].__setitem__("prefilter_profile", "P1"),
    lambda c: c["build"].__setitem__("baseline_ref", A_SHA),
    lambda c: c["build"].__setitem__("release", False),
    lambda c: c["policy"].__setitem__("control_arms", ["B"]),
    lambda c: c["policy"].__setitem__("blocks", 9),
])
def test_a4_u02_validator_rejects_unpinned_and_wrong_regime(mutation):
    config = _valid_config()
    mutation(config)
    with pytest.raises(artifacts.ArtifactError):
        configuration.validate_configuration(config)


def test_a4_u02_generation_requires_both_pinned_revisions_and_warm():
    with pytest.raises(artifacts.ArtifactError, match="pinned"):
        configuration.default_configuration("perf-06", "missing", DESCRIPTION)
    with pytest.raises(artifacts.ArtifactError, match="pinned"):
        configuration.default_configuration(
            "perf-06", "half", DESCRIPTION, baseline_revision=A_SHA)
    with pytest.raises(artifacts.ArtifactError, match="process-cold"):
        configuration.default_configuration(
            "perf-06", "cold", DESCRIPTION, regime="process-cold",
            baseline_revision=A_SHA, candidate_revision=B_SHA)
    with pytest.raises(artifacts.ArtifactError, match="only accepted for perf-05"):
        configuration.default_configuration(
            "perf-06", "feature", DESCRIPTION, quervant_revision=B_SHA)


# U03 -----------------------------------------------------------------------
def _result(config: dict, *, executed: str = "2026-11-23T12:00:00Z") -> dict:
    return {"configuration_id": config["configuration_id"], "run_id": str(uuid4()),
            "executed_utc": executed, "raw_samples": [],
            "analysis": {}, "status": "INCOMPLETE"}


def test_a4_u03_study_path_identity_and_nonoverwriting_results(tmp_path):
    path, config = _config(tmp_path)
    assert path.parent == tmp_path / "studies" / "perf-06" / "warm" / "configurations"
    results = artifacts.result_directory(path)
    assert results == tmp_path / "studies" / "perf-06" / "warm" / "results"

    # A perf-06 configuration cannot be filed under another family/regime.
    wrong = tmp_path / "studies" / "perf-02" / "warm" / "configurations"
    wrong.mkdir(parents=True)
    (wrong / path.name).write_bytes(path.read_bytes())
    with pytest.raises(artifacts.ArtifactError, match="configuration must reside"):
        artifacts.load_configuration(wrong / path.name)
    (wrong / path.name).unlink()
    with pytest.raises(artifacts.ArtifactError, match="configuration must reside"):
        artifacts.create_configuration(wrong, deepcopy(config))
    with pytest.raises(artifacts.ArtifactError, match="configuration must reside"):
        artifacts.create_configuration(
            tmp_path / "studies" / "perf-06" / "cold-start" / "configurations",
            deepcopy(config))
    assert not (tmp_path / "studies" / "perf-06" / "cold-start").exists()

    # Name and configuration UUID remain globally unique across studies.
    with pytest.raises(artifacts.ArtifactError, match="name already reserved"):
        artifacts.create_configuration(path.parent, deepcopy(config))
    duplicate = deepcopy(config)
    duplicate["name"] = "quervant-perf06a-other"
    with pytest.raises(artifacts.ArtifactError, match="ID already reserved"):
        artifacts.create_configuration(path.parent, duplicate)

    first = artifacts.publish_result(path, None, _result(config))
    second = artifacts.publish_result(
        path, None, _result(config, executed="2026-11-23T13:00:00Z"))
    assert first.name.endswith("-2026-11-23-001.json")
    assert second.name.endswith("-2026-11-23-002.json")
    assert first != second
    assert artifacts.load_result(first)["sequence"] == 1
    assert artifacts.load_result(second)["sequence"] == 2
    with pytest.raises(artifacts.ArtifactError, match="already exists"):
        artifacts._publish_exclusive(first, b"{}")
    assert artifacts.load_result(first)["sequence"] == 1


# U04 -----------------------------------------------------------------------
def _patch_build(monkeypatch, *, fail_target: str | None = None):
    commands: list[tuple[str, ...]] = []
    targets: list[tuple[Path, str, bool, Path]] = []
    monkeypatch.setattr(runtime, "_git", lambda root, *args: "c" * 40)

    def fake_run(argv, *, timeout=0, **kwargs):
        commands.append(tuple(argv))
        return CompletedProcess(argv, 0, "", "")

    def fake_build(root, target, *, engine, feature, source_root=None):
        targets.append((target, engine, feature, source_root))
        if fail_target is not None and target.name == fail_target:
            raise runtime.MeasurementBlocked("synthetic compilation failure")
        return [str(target / "release" / "pr15d-quervant-adapter")]

    monkeypatch.setattr(runtime, "_run", fake_run)
    monkeypatch.setattr(runtime, "_build_rust", fake_build)
    return commands, targets


def test_a4_u04_two_isolated_pinned_release_builds(tmp_path, monkeypatch):
    _, config = _config(tmp_path)
    commands, targets = _patch_build(monkeypatch)
    programs, context = runtime.build_programs(config, tmp_path, tmp_path / "scratch")
    assert set(programs) == {"A", "B"}
    assert programs["A"] != programs["B"]
    assert [target.name for target, *_ in targets] == ["quervant-a", "quervant-b"]
    assert all(engine == "quervant" and feature is False for _, engine, feature, _ in targets)
    assert [source.name for *_, source in targets] == ["source-a", "source-b"]
    adds = [row for row in commands if "add" in row]
    removals = [row for row in commands if "remove" in row]
    assert [row[-1] for row in adds] == [A_SHA, B_SHA]
    assert len(removals) == 2
    assert context["arm_source_revisions"] == {"A": A_SHA, "B": B_SHA}
    assert context["quervant_strategy_feature_enabled"] is False


def test_a4_u04_failed_arm_b_build_still_removes_its_worktree(tmp_path, monkeypatch):
    _, config = _config(tmp_path)
    commands, _ = _patch_build(monkeypatch, fail_target="quervant-b")
    with pytest.raises(runtime.MeasurementBlocked, match="compilation failure"):
        runtime.build_programs(config, tmp_path, tmp_path / "scratch")
    assert len([row for row in commands if "add" in row]) == 2
    assert len([row for row in commands if "remove" in row]) == 2


# U05 -----------------------------------------------------------------------
def test_a4_u05_stage_oracles_cover_both_real_roles(tmp_path, monkeypatch):
    path, config = _config(tmp_path)
    calls = _mock_preparation(monkeypatch)
    staged = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert staged["state"] == "BUILT"
    oracle_calls = [call for call in calls if call.startswith("oracle:")]
    assert sorted(oracle_calls) == ["oracle:A:10000", "oracle:A:100000",
                                   "oracle:B:10000", "oracle:B:100000"]
    assert set(staged["programs"]) == {"A", "B"}
    assert set(staged["indexes"]) == {"A", "B"}
    assert set(staged["indexes"]["A"]) == {10_000, 100_000}
    assert staged["programs"]["A"] != staged["programs"]["B"]
    assert staged["index_metrics"]["A"]["10000"]["index_bytes"] == 6
    assert not (path.parent.parent / "results").exists()


def test_a4_u05_wrong_ordered_key_in_arm_b_is_rejected_before_timing(tmp_path, monkeypatch):
    path, config = _config(tmp_path)

    def corrupt(arm, size, request, hits, doc_ids):
        if arm == "B" and size == 100_000 and request["k"] == 100 and doc_ids:
            return hits, list(reversed(doc_ids))
        return hits, doc_ids

    calls = _mock_preparation(monkeypatch, oracle=corrupt)
    with pytest.raises(runtime.MeasurementBlocked, match="independent oracle disagreement"):
        preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert "oracle:B:100000" in calls
    assert not (path.parent.parent / "results").exists()
    assert list((tmp_path / "target" / "bm10" / "prepared").iterdir()) == []


# U06 -----------------------------------------------------------------------
def test_a4_u06_stage_no_timing_then_cache_hit_and_tamper_stop(tmp_path, monkeypatch):
    path, config = _config(tmp_path)
    calls = _mock_preparation(monkeypatch)
    monkeypatch.setattr(runtime, "collect_slot",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("stage must not acquire timed slots")))
    monkeypatch.setattr(runtime, "run_benchmark",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("stage must not run the benchmark")))
    first = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    second = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert first["state"] == "BUILT" and second["state"] == "HIT"
    assert first["key"] == second["key"]
    assert first["index_metrics"] == second["index_metrics"]
    assert first["prepared_utc"] == second["prepared_utc"]
    assert len([c for c in calls if c == "build"]) == 1
    assert len([c for c in calls if c.startswith("index:")]) == 4
    assert len([c for c in calls if c.startswith("oracle:")]) == 8
    assert not (path.parent.parent / "results").exists()

    candidate = Path(second["programs"]["B"][0])
    candidate.write_text("tampered")
    with pytest.raises(runtime.MeasurementBlocked, match="cache failed validation"):
        preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert candidate.exists()
    assert len([c for c in calls if c == "build"]) == 1


# U07 -----------------------------------------------------------------------
def test_a4_u07_aa_control_aliases_use_only_a(tmp_path, monkeypatch):
    path, config = _config(tmp_path, policy=_small_policy())
    lanes = configuration.lanes_for(config)
    control = runtime._control_config(config)
    assert control["arms"] == {"AA": config["arms"]["A"], "AA2": config["arms"]["A"]}
    assert control["baseline"] == "AA"
    assert control["source_arm"] == "A"
    assert control["policy"]["control_arms"] == ["AA2"]

    captured: list[tuple[str, tuple[str, ...], dict]] = []

    def collect(config, arm_id, lanes, command, indexes, *, block, position, cpu):
        captured.append((arm_id, tuple(command), dict(indexes)))
        return [{"block": block, "position": position, "arm_id": arm_id,
                 "lane_id": lane["id"], "warmups": 5, "samples_ns": [100] * 5,
                 "oracle_ok": True, "strategy_marker": None} for lane in lanes]

    monkeypatch.setattr(runtime, "collect_slot", collect)
    binaries = {"A": ["/mock/quervant-a"], "B": ["/mock/quervant-b"]}
    indexes = {"A": {10_000: tmp_path / "A" / "10000"},
               "B": {10_000: tmp_path / "B" / "10000"}}
    rows = runtime._phase(control, lanes, binaries, indexes,
                          cpu=None, on_slot=lambda new: None)
    assert {arm for arm, _, _ in captured} == {"AA", "AA2"}
    assert all(command == ("/mock/quervant-a",) for _, command, _ in captured)
    assert all(paths == indexes["A"] for _, _, paths in captured)
    assert len(captured) == 12 * 2 * 2  # blocks * arms * slots_per_arm
    assert len(rows) == 12 * 2 * 2 * len(lanes)

    stable = statistics.analyze(rows, arms=["AA", "AA2"], baseline="AA",
                                lanes=lanes, policy=control["policy"])
    assert all(lane["comparisons"]["AA2"]["status"] == "PASS"
               for lane in stable["lanes"].values())
    noisy = [dict(row, samples_ns=[1000] * 5) if row["arm_id"] == "AA2" else row
             for row in rows]
    unstable = statistics.analyze(noisy, arms=["AA", "AA2"], baseline="AA",
                                  lanes=lanes, policy=control["policy"])
    assert all(lane["comparisons"]["AA2"]["status"] == "FAIL"
               for lane in unstable["lanes"].values())


# U08 -----------------------------------------------------------------------
def _treatment_rows(lanes, policy, treatment: dict[str, int],
                    baseline: int = 100) -> list[dict]:
    scheduled = statistics.schedule(["A", "B"], blocks=policy["blocks"],
                                    slots_per_arm=policy["slots_per_arm"],
                                    seed=policy["seed"])
    rows = []
    for slot in scheduled:
        for lane in lanes:
            value = (treatment.get(lane["id"], treatment.get("*", baseline))
                     if slot["arm_id"] == "B" else baseline)
            rows.append({"block": slot["block"], "position": slot["position"],
                         "arm_id": slot["arm_id"], "lane_id": lane["id"],
                         "warmups": policy["warmups"], "oracle_ok": True,
                         "samples_ns": [value] * policy["samples"]})
    return rows


def test_a4_u08_paired_treatment_and_invalid_schedule(tmp_path):
    _, config = _config(tmp_path, policy=_small_policy())
    lanes = configuration.lanes_for(config)
    policy = config["policy"]
    treatment = {lane: 90 for lane in PRIMARY_LANES}
    treatment["10000/absent/k10/warm"] = 120
    rows = _treatment_rows(lanes, policy, treatment)
    assert len(rows) == 12 * 2 * 2 * len(lanes)
    analysis = statistics.analyze(rows, arms=["A", "B"], baseline="A",
                                  lanes=lanes, policy=policy)
    assert analysis["estimator"] == "median-paired-ratios-v1"
    assert len(analysis["lanes"]) == 16
    primary = analysis["lanes"]["100000/medium/k10/warm"]
    assert primary["excluded_blocks"] == [] and primary["retained_blocks"] == 12
    comparison = primary["comparisons"]["B"]
    assert comparison["kind"] == "treatment"
    assert comparison["status"] == "IMPROVED"
    assert comparison["gain_percent"] == pytest.approx(10.0)
    assert len(comparison["retained_paired_ratios"]) == 12
    assert comparison["bootstrap_resamples"] == policy["bootstrap_resamples"]
    low, high = comparison["gain_ci_95_percent"]
    assert math.isfinite(low) and math.isfinite(high) and low <= 10.0 <= high
    assert analysis["lanes"]["10000/absent/k10/warm"]["comparisons"]["B"]["status"] == "REGRESSED"

    def broken(rows_in):
        return list(rows_in)

    for mutate, match in (
        (lambda r: r + [deepcopy(r[0])], "duplicate slot/lane sample"),
        (lambda r: r[:-1], "incomplete block/slot schedule|missing per-lane slot samples"),
        (lambda r: r[:1] + [dict(r[1], arm_id="A")] + r[2:],
         "slot position assigned to multiple arms|unbalanced block/slot acquisition"),
        (lambda r: r[:1] + [dict(r[1], samples_ns=r[1]["samples_ns"][:-1])] + r[2:],
         "incomplete timed sample series"),
        (lambda r: r[:1] + [dict(r[1], block=0)] + r[2:], "sample block"),
        (lambda r: r[:1] + [dict(r[1], oracle_ok=False)] + r[2:], "without verified search correctness"),
        (lambda r: r[:1] + [dict(r[1], lane_id="999999/medium/k10/warm")] + r[2:],
         "undeclared arm, lane, block or position"),
    ):
        with pytest.raises(artifacts.ArtifactError, match=match):
            statistics.analyze(broken(mutate(deepcopy(rows))), arms=["A", "B"],
                               baseline="A", lanes=lanes, policy=policy)

    # A saved unpaired historical result is never accepted as a paired baseline.
    current = {"status": "COMPLETE", "controls": {"analysis": {"lanes": {
        lane["id"]: {"comparisons": {"AA2": {"status": "PASS"}}} for lane in lanes}}},
        "raw_samples": rows, "analysis": analysis, "lanes": lanes}
    historical = {"status": "COMPLETE", "controls": current["controls"],
                  "raw_samples": rows,
                  "analysis": {"estimator": "median-paired-ratios-v1", "lanes": {}},
                  "lanes": lanes}
    verdict = statistics.compare_historical(
        current, historical, lane_id="100000/medium/k10/warm", treatment_arm="B")
    assert verdict["status"] in ("NOT_COMPARABLE", "UNAVAILABLE")


def test_a4_u08_complete_run_records_768_control_and_treatment_rows(tmp_path, monkeypatch):
    """The frozen campaign shape: 12 blocks x 2 slots x 2 roles x 16 lanes."""
    path, config = _config(tmp_path)
    assert config["policy"]["bootstrap_resamples"] == 10_000
    _mock_preparation(monkeypatch)
    _no_host(monkeypatch)
    _mock_phase(monkeypatch, values={"AA": 100, "AA2": 100, "A": 100, "B": 95})
    result_path, result = runtime.run_benchmark(path, root=tmp_path, check_host=False)
    assert result["status"] == "COMPLETE"
    assert len(result["raw_samples"]) == 12 * 2 * 2 * 16
    assert len(result["controls"]["raw_samples"]) == 12 * 2 * 2 * 16
    assert len(result["analysis"]["lanes"]) == 16
    assert len(result["controls"]["analysis"]["lanes"]) == 16
    assert all(lane["comparisons"]["AA2"]["status"] == "PASS"
               for lane in result["controls"]["analysis"]["lanes"].values())
    for lane in result["analysis"]["lanes"].values():
        assert lane["excluded_blocks"] == [] and lane["retained_blocks"] == 12
        comparison = lane["comparisons"]["B"]
        assert len(comparison["retained_paired_ratios"]) == 12
        assert comparison["bootstrap_resamples"] == 10_000
        assert comparison["status"] == "IMPROVED"
    saved = artifacts.load_result(result_path)
    assert saved["sequence"] == 1
    assert saved["family"] == "perf-06"
    assert saved["context"]["build"]["arm_source_revisions"] == {"A": A_SHA, "B": B_SHA}
    assert set(saved["index_metrics"]) == {"A", "B"}
    assert saved["context"]["preparation"]["cache_status"] == "BUILT"
    assert saved["raw_samples"][0]["warmups"] == 5
    assert all(len(row["samples_ns"]) == 20 for row in saved["raw_samples"])
    assert result_path.parent == path.parent.parent / "results"


# U09 -----------------------------------------------------------------------
def test_a4_u09_incomplete_control_publishes_unmodified_result(tmp_path, monkeypatch):
    path, config = _config(tmp_path, policy=_small_policy())
    _mock_preparation(monkeypatch)
    _no_host(monkeypatch)
    _mock_phase(monkeypatch, values={"AA": 100, "AA2": 400, "A": 100, "B": 100})
    assert runtime.run_benchmark(path, root=tmp_path, check_host=False)[1]["status"] == "INCOMPLETE"
    results = sorted((path.parent.parent / "results").glob("*.json"))
    assert len(results) == 1
    saved = artifacts.load_result(results[0])
    assert saved["status"] == "INCOMPLETE"
    assert saved["raw_samples"] == []
    assert saved["analysis"] == {}
    assert len(saved["controls"]["raw_samples"]) == 12 * 2 * 2 * 16
    assert saved["controls"]["analysis"]["lanes"]
    assert any("A/A control is unstable" in error for error in saved["errors"])
    # No automatic retry, no treatment data, no overwritten artifact.
    assert sorted((path.parent.parent / "results").glob("*.json")) == results


# U10 -----------------------------------------------------------------------
def _classify_paired(result: dict) -> str:
    """Frozen PERF-06-A4 §2.4 decision table, test-only wording of the gates."""
    analysis = result.get("analysis")
    lanes = analysis.get("lanes") if isinstance(analysis, dict) else None
    if result.get("status") != "COMPLETE" or not isinstance(lanes, dict) or len(lanes) != 16:
        return "PERF06_A4_INCOMPLETE_STOP"
    primary_failed: list[str] = []
    guard_failed: list[str] = []
    inconclusive: list[str] = []
    for lane_id, lane in lanes.items():
        comparison = (lane.get("comparisons") or {}).get("B")
        if (not isinstance(comparison, dict) or comparison.get("kind") != "treatment"
                or comparison.get("status") not in TREATMENT_STATUSES):
            inconclusive.append(lane_id)
            continue
        gain = comparison.get("gain_percent")
        interval = comparison.get("gain_ci_95_percent")
        if (isinstance(gain, bool) or not isinstance(gain, (int, float))
                or not isinstance(interval, list) or len(interval) != 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                       for x in interval)
                or not all(math.isfinite(x) for x in (gain, *interval))):
            inconclusive.append(lane_id)
            continue
        if lane_id in PRIMARY_LANES:
            if comparison["status"] != "IMPROVED" or gain < 5.0 or interval[0] <= 0.0:
                primary_failed.append(lane_id)
        elif gain < -10.0 or interval[0] < -10.0:
            guard_failed.append(lane_id)
    if inconclusive:
        return "PERF06_A4_PAIRED_INCONCLUSIVE_REVIEW_REQUIRED"
    if primary_failed or guard_failed:
        return "PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED"
    return "PERF06_A4_PAIRED_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED"


def _synthetic_result(*, gain: float, ci: tuple[float, float],
                      status: str = "IMPROVED", run_status: str = "COMPLETE",
                      overrides: dict[str, tuple] | None = None) -> dict:
    all_lanes = {f"{n}/{cls}/k{k}/warm" for n in (10_000, 100_000)
                 for cls in ("absent", "rare", "medium", "common") for k in (10, 100)}
    lanes = {}
    for lane in all_lanes:
        entry = (gain, ci, status) if lane in PRIMARY_LANES else (1.5, (-1.0, 4.0), "INCONCLUSIVE")
        if overrides and lane in overrides:
            entry = overrides[lane]
        entry_gain, entry_ci, entry_status = entry
        lanes[lane] = {"comparisons": {"B": {
            "kind": "treatment", "status": entry_status,
            "gain_percent": entry_gain, "gain_ci_95_percent": list(entry_ci),
        }}}
    return {"status": run_status, "analysis": {"lanes": lanes}}


def test_a4_u10_good_complete_result_is_not_approval():
    met = _synthetic_result(gain=7.5, ci=(3.0, 12.0))
    assert _classify_paired(met) == "PERF06_A4_PAIRED_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED"

    weak_primary = _synthetic_result(
        gain=4.9, ci=(1.0, 9.0))
    assert _classify_paired(weak_primary) == "PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED"

    zero_lower_bound = _synthetic_result(gain=8.0, ci=(0.0, 15.0))
    assert _classify_paired(zero_lower_bound) == "PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED"

    guard_at_limit = _synthetic_result(gain=7.5, ci=(3.0, 12.0), overrides={
        "10000/medium/k10/warm": (-9.999, (-10.0, -5.0), "INCONCLUSIVE")})
    assert _classify_paired(guard_at_limit) == "PERF06_A4_PAIRED_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED"

    regressed_guard = _synthetic_result(gain=7.5, ci=(3.0, 12.0), overrides={
        "100000/rare/k100/warm": (-10.01, (-14.0, -8.0), "REGRESSED")})
    assert _classify_paired(regressed_guard) == "PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED"

    weak_guard_ci = _synthetic_result(gain=7.5, ci=(3.0, 12.0), overrides={
        "10000/absent/k10/warm": (-4.0, (-12.0, 1.0), "INCONCLUSIVE")})
    assert _classify_paired(weak_guard_ci) == "PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED"

    no_ci = _synthetic_result(gain=7.5, ci=(3.0, 12.0))
    no_ci["analysis"]["lanes"]["100000/common/k10/warm"]["comparisons"]["B"].pop(
        "gain_ci_95_percent")
    assert _classify_paired(no_ci) == "PERF06_A4_PAIRED_INCONCLUSIVE_REVIEW_REQUIRED"

    missing = _synthetic_result(gain=7.5, ci=(3.0, 12.0))
    missing["analysis"]["lanes"].pop("100000/common/k100/warm")
    assert _classify_paired(missing) == "PERF06_A4_INCOMPLETE_STOP"

    incomplete = _synthetic_result(gain=7.5, ci=(3.0, 12.0), run_status="INCOMPLETE")
    assert _classify_paired(incomplete) == "PERF06_A4_INCOMPLETE_STOP"

    # A plain "COMPLETE" status plus a REGRESSED guard never means targets met.
    complete_regressed = _synthetic_result(gain=9.0, ci=(5.0, 14.0), overrides={
        "100000/common/k100/warm": (-20.0, (-25.0, -15.0), "REGRESSED")})
    assert complete_regressed["status"] == "COMPLETE"
    assert _classify_paired(complete_regressed) == (
        "PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED")
    assert {_classify_paired(x) for x in (met, weak_primary, zero_lower_bound,
                                          guard_at_limit, regressed_guard,
                                          no_ci, incomplete)} <= OUTCOMES


# U11 -----------------------------------------------------------------------
def test_a4_u11_existing_perf02_and_perf05_behavior_unchanged():
    paired = configuration.default_configuration(
        "perf-02", "legacy-paired", "Existing PERF-02 identity",
        baseline_revision=A_SHA, candidate_revision=B_SHA)
    assert paired["control"] == {"enabled": True, "baseline": "AA", "equivalent": "AA2"}
    assert paired["build"]["quervant_feature"] is None
    assert len(configuration.lanes_for(paired)) == 16
    configuration.validate_configuration(paired)

    single = configuration.default_configuration(
        "perf-05", "legacy-b-only", "Existing PERF-05 identity",
        quervant_revision=B_SHA)
    assert single["baseline"] == "B"
    assert set(single["arms"]) == {"B"}
    assert single["control"] == {"enabled": True, "baseline": "BB", "equivalent": "BB2"}
    assert single["historical_reference"]["mode"] == "historical-absolute-unpaired"
    assert single["policy"]["slots_per_arm"] == 1
    configuration.validate_configuration(single)

    with pytest.raises(artifacts.ArtifactError, match="only accepted"):
        configuration.default_configuration(
            "cross-engine", "cross", "Cross-engine rejects pinned A/B",
            baseline_revision=A_SHA, candidate_revision=B_SHA)
    with pytest.raises(artifacts.ArtifactError, match="only accepted for perf-02/perf-06"):
        configuration.default_configuration(
            "perf-05", "legacy-b-only", "PERF-05 is B-only",
            baseline_revision=A_SHA, candidate_revision=B_SHA)
    with pytest.raises(artifacts.ArtifactError, match="only accepted for perf-05"):
        configuration.default_configuration(
            "perf-06", "wrong-flag", "PERF-06 is paired",
            baseline_revision=A_SHA, candidate_revision=B_SHA,
            quervant_revision=B_SHA)
    with pytest.raises(artifacts.ArtifactError, match="family must be"):
        configuration.default_configuration("perf-07", "unknown", "Unknown family")

    # Family identity is not silently shared between paired and B-only routes.
    mixed = deepcopy(single)
    mixed["family"] = "perf-06"
    with pytest.raises(artifacts.ArtifactError, match="arm catalog"):
        configuration.validate_configuration(mixed)


# U12 -----------------------------------------------------------------------
def test_a4_u12_cli_prepare_validation_and_date(tmp_path, capsys):
    studies = tmp_path / "studies"
    assert cli.main([
        "prepare", "--family", "perf-06", "--regime", "warm",
        "--name", "quervant-perf06a-paired-warm", "--description", DESCRIPTION,
        "--baseline-revision", A_SHA, "--candidate-revision", B_SHA,
        "--studies-root", str(studies),
    ]) == 0
    printed = Path(capsys.readouterr().out.strip())
    directory = studies / "perf-06" / "warm" / "configurations"
    assert list(directory.glob("*.json")) == [printed]
    config = artifacts.load_configuration(printed)
    assert printed.name == (
        f"quervant-perf06a-paired-warm-{config['created_utc'][:10]}.json")
    assert config["created_utc"].endswith("Z")
    assert config["description"] == DESCRIPTION
    assert config["arms"]["A"]["revision"] == A_SHA
    assert config["arms"]["B"]["revision"] == B_SHA
    assert cli.main(["validate", "--config", str(printed)]) == 0
    assert capsys.readouterr().out.strip() == "VALID"

    for argv in (
        ["prepare", "--family", "perf-06", "--name", "missing-candidate",
         "--description", DESCRIPTION, "--baseline-revision", A_SHA,
         "--studies-root", str(studies)],
        ["prepare", "--family", "perf-06", "--name", "branch-name",
         "--description", DESCRIPTION, "--baseline-revision", "main",
         "--candidate-revision", B_SHA, "--studies-root", str(studies)],
        ["prepare", "--family", "perf-06", "--name", "cold", "--regime",
         "process-cold", "--description", DESCRIPTION, "--baseline-revision",
         A_SHA, "--candidate-revision", B_SHA, "--studies-root", str(studies)],
        ["prepare", "--family", "perf-06", "--name", "duplicate-name",
         "--description", DESCRIPTION, "--baseline-revision", A_SHA,
         "--candidate-revision", B_SHA, "--quervant-revision", B_SHA,
         "--studies-root", str(studies)],
    ):
        assert cli.main(argv) == 2
        capsys.readouterr()
    assert list(directory.glob("*.json")) == [printed]
    assert not (studies / "perf-06" / "cold-start").exists()
    assert not (studies / "perf-06" / "warm" / "results").exists()
