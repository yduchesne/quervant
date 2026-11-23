"""Deterministic PERF-05-C tests: no real adapter, timing, A/T/J or RustFS work."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from subprocess import CompletedProcess
from uuid import uuid4

import pytest

from quervant_bench.lean import (
    artifacts,
    cli,
    configuration,
    perf05,
    preparation,
    reporting,
    runtime,
    statistics,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
B_SHA = "ee18ed63bbeeb54b544393ee0f676987ff9987d1"
OTHER_SHA = "a" * 40
CONTROL_POLICY = {"blocks": 12, "slots_per_arm": 1, "samples": 20, "warmups": 5,
                  "bootstrap_resamples": 50, "seed": 20261122, "min_blocks": 4,
                  "min_gain_percent": 0, "max_regression_percent": 0,
                  "max_aa_gain_percent": 15, "exclude_blocks": {}, "control_arms": ["BB2"]}


def make_config(tmp_path: Path, *, revision: str = B_SHA, name: str = "quervant-perf05-b-only-warm"):
    config = configuration.default_configuration(
        "perf-05", name, "PERF-05 B-only warm test", timestamp="2026-11-23T00:00:00Z",
        regime="warm", quervant_revision=revision)
    config["policy"]["bootstrap_resamples"] = 50
    path = artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", config), config)
    return path, config


def _raw_historical_result(config, medians=None):
    medians = medians or {lane: float(Decimal(value)) for lane, value in perf05.EXPECTED_MEDIANS.items()}
    lanes = {}
    for lane_id, value in medians.items():
        lanes[lane_id] = {"arm_absolute": {"Q": {"median_block_value": value,
                                                "block_values": [value] * 12}},
                          "comparisons": {}}
    lane_ids = [lane["id"] for lane in configuration.lanes_for(config)]
    return {
        "family": "cross-engine",
        "status": "COMPLETE",
        "configuration_id": perf05.PERF05_HISTORICAL_CONFIGURATION_ID,
        "run_id": perf05.PERF05_HISTORICAL_RUN_ID,
        "analysis": {"lanes": lanes},
        "controls": {
            "analysis": {"lanes": {lane_id: {"comparisons": {"AA2": {"status": "PASS"}}}
                                   for lane_id in lane_ids}},
            "readiness_pre": {"status": "clear"},
            "readiness_index_source": "preparation stage",
        },
        "raw_samples": [{"arm_id": "Q", "lane_id": lane_id, "oracle_ok": True}
                        for lane_id in lane_ids],
        "context": {
            "source_revision": perf05.PERF05_HISTORICAL_SOURCE,
            "host": {
                "system": "Linux", "architecture": "x86_64", "filesystem": "ext4",
                "toolchains": {"rustc": "rustc 1.98.1", "cargo": "cargo 1.98.1"},
            },
            "build": {"source_revision": perf05.PERF05_HISTORICAL_SOURCE,
                      "compiler_options": "cargo --release --locked",
                      "quervant_strategy_feature_enabled": False},
        },
    }


def _historical_summary(config, medians=None):
    raw = _raw_historical_result(config, medians)
    return {
        "schema": "bm10-historical-reference-v1",
        "result_file": perf05.PERF05_HISTORICAL_RESULT,
        "git_blob_sha1": perf05.PERF05_HISTORICAL_BLOB,
        "configuration_id": perf05.PERF05_HISTORICAL_CONFIGURATION_ID,
        "run_id": perf05.PERF05_HISTORICAL_RUN_ID,
        "arm": "Q",
        "source_revision": perf05.PERF05_HISTORICAL_SOURCE,
        "mode": perf05.PERF05_HISTORICAL_MODE,
        "lanes": {
            lane_id: {"median_block_value": lane["arm_absolute"]["Q"]["median_block_value"],
                      "block_values": lane["arm_absolute"]["Q"]["block_values"]}
            for lane_id, lane in raw["analysis"]["lanes"].items()
        },
        "context": raw["context"],
    }


def _matching_context():
    return {
        "host": {
            "system": "Linux", "architecture": "x86_64", "filesystem": "ext4",
            "toolchains": {"rustc": "rustc 1.98.1", "cargo": "cargo 1.98.1"},
        },
        "build": {"compiler_options": "cargo --release --locked",
                  "quervant_strategy_feature_enabled": False},
    }


def _b_raw(config):
    rows = []
    for lane in configuration.lanes_for(config):
        for slot in statistics.schedule(["BB", "BB2"], blocks=12, slots_per_arm=1, seed=20261122):
            rows.append({"arm_id": slot["arm_id"], "block": slot["block"],
                         "position": slot["position"], "lane_id": lane["id"],
                         "oracle_ok": True, "samples_ns": [100] * 20})
    return rows


def _bb_analysis(config, median_for_lane):
    lanes = {}
    for lane in configuration.lanes_for(config):
        value = median_for_lane(lane)
        lanes[lane["id"]] = {
            "arm_absolute": {
                "BB": {"block_values": [value] * 12},
                "BB2": {"block_values": [value] * 12},
            },
            "comparisons": {"BB2": {"status": "PASS"}},
        }
    return {"lanes": lanes}


# C-U01 ---------------------------------------------------------------------
def test_c_u01_valid_perf05_configuration(tmp_path):
    path, config = make_config(tmp_path)
    assert path.parent.as_posix().endswith("/perf-05/warm/configurations")
    assert config["family"] == "perf-05"
    assert config["baseline"] == "B"
    assert set(config["arms"]) == {"B"}
    assert config["arms"]["B"] == {"engine": "quervant", "mode": "by-top-k",
                                   "source": "pinned", "revision": B_SHA}
    assert config["control"] == {"enabled": True, "baseline": "BB", "equivalent": "BB2"}
    assert config["historical_reference"]["git_blob_sha1"] == perf05.PERF05_HISTORICAL_BLOB
    assert config["historical_reference"]["source_revision"] == perf05.PERF05_HISTORICAL_SOURCE
    assert config["build"]["quervant_feature"] is None
    assert config["build"]["prefilter_profile"] == "P2"
    assert config["policy"]["slots_per_arm"] == 1
    assert config["policy"]["blocks"] == 12
    lanes = configuration.lanes_for(config)
    assert len(lanes) == 16
    assert {lane["cache_regime"] for lane in lanes} == {"warm"}
    assert configuration.validate_configuration(config) is None


# C-U02 ---------------------------------------------------------------------
def test_c_u02_invalid_perf05_configurations_are_rejected(tmp_path):
    for bad in ("HEAD", "main", "E" * 40, "f" * 39, "g" * 40, None):
        with pytest.raises(artifacts.ArtifactError):
            configuration.default_configuration(
                "perf-05", "quervant-perf05-b-only-warm", "d", regime="warm",
                quervant_revision=bad)
    with pytest.raises(artifacts.ArtifactError):
        configuration.default_configuration(
            "perf-02", "legacy", "d", baseline_revision=B_SHA, candidate_revision=B_SHA,
            quervant_revision=B_SHA)

    _, config = make_config(tmp_path)
    mutations = [
        lambda c: c["arms"].__setitem__("A", deepcopy(c["arms"]["B"])),
        lambda c: c.__setitem__("baseline", "A"),
        lambda c: c["workload"].__setitem__("regimes", ["process-cold"]),
        lambda c: c["historical_reference"].__setitem__("git_blob_sha1", "0" * 40),
        lambda c: c["historical_reference"].__setitem__("source_revision", "0" * 40),
        lambda c: c["workload"].__setitem__("top_k", [32]),
        lambda c: c["build"].__setitem__("quervant_feature", "quervant-core/pr15i-d3c-experiment"),
        lambda c: c["control"].__setitem__("enabled", False),
        lambda c: c["control"].__setitem__("baseline", "AA"),
        lambda c: c["policy"].__setitem__("slots_per_arm", 2),
        lambda c: c["policy"].__setitem__("blocks", 4),
        lambda c: c["policy"].__setitem__("samples", 10),
    ]
    for mutate in mutations:
        broken = deepcopy(config)
        mutate(broken)
        with pytest.raises(artifacts.ArtifactError):
            configuration.validate_configuration(broken)


# C-U03 ---------------------------------------------------------------------
def test_c_u03_historical_reference_is_frozen_and_read_only(tmp_path):
    _, config = make_config(tmp_path)
    summary = perf05.verify_historical_reference(REPO_ROOT, config)
    assert summary["git_blob_sha1"] == perf05.PERF05_HISTORICAL_BLOB
    assert summary["source_revision"] == perf05.PERF05_HISTORICAL_SOURCE
    assert summary["run_id"] == perf05.PERF05_HISTORICAL_RUN_ID
    assert set(summary["lanes"]) == set(perf05.EXPECTED_MEDIANS)
    assert len(summary["lanes"]) == 16
    assert all(len(value["block_values"]) == 12 for value in summary["lanes"].values())


@pytest.mark.parametrize("mutate", [
    lambda data: data["context"].__setitem__("source_revision", "0" * 40),
    lambda data: data["analysis"]["lanes"].pop("10000/absent/k10/warm"),
    lambda data: data["analysis"]["lanes"]["10000/absent/k10/warm"]["arm_absolute"]["Q"].__setitem__(
        "median_block_value", 1.0),
    lambda data: data["controls"]["analysis"]["lanes"]["10000/absent/k10/warm"]["comparisons"][
        "AA2"].__setitem__("status", "FAIL"),
    lambda data: data["controls"].__setitem__("readiness_pre", {"status": "busy"}),
])
def test_c_u03_corrupt_historical_reference_fails(tmp_path, monkeypatch, mutate):
    path, config = make_config(tmp_path)
    fixture = _raw_historical_result(config)
    mutate(fixture)
    monkeypatch.setattr(perf05, "load_result", lambda _path: fixture)
    monkeypatch.setattr(perf05.runtime, "_git", lambda root, *args: perf05.PERF05_HISTORICAL_BLOB)
    historical_path = REPO_ROOT / perf05.HISTORICAL_RELATIVE_PATH
    if not historical_path.is_file():
        pytest.skip("historical result not checked out")
    with pytest.raises(artifacts.ArtifactError):
        perf05.verify_historical_reference(REPO_ROOT, config)


# C-U04 ---------------------------------------------------------------------
def test_c_u04_builds_one_pinned_b_target_and_removes_worktree(tmp_path, monkeypatch):
    _, config = make_config(tmp_path)
    commands, targets = [], []

    def fake_run(argv, *, timeout=0, **kwargs):
        commands.append(tuple(argv))
        return CompletedProcess(argv, 0, "", "")

    def fake_build(root, target, *, engine, feature, source_root=None):
        targets.append((target, engine, feature, source_root))
        return [str(target / "release" / "pr15d-quervant-adapter")]

    monkeypatch.setattr(runtime, "_git", lambda root, *args: "c" * 40)
    monkeypatch.setattr(runtime, "_run", fake_run)
    monkeypatch.setattr(runtime, "_build_rust", fake_build)
    paths, context = runtime.build_programs(config, tmp_path, tmp_path / "scratch")
    assert set(paths) == {"B"}
    assert len(targets) == 1
    target, engine, feature, source_root = targets[0]
    assert target.name == "quervant-b"
    assert engine == "quervant" and feature is False
    assert source_root.name == "source-b"
    assert context["arm_source_revisions"] == {"B": B_SHA}
    assert context["source_revision"] == B_SHA
    assert context["quervant_strategy_feature_enabled"] is False
    adds = [x for x in commands if "add" in x]
    removals = [x for x in commands if "remove" in x]
    assert [x[-1] for x in adds] == [B_SHA]
    assert len(removals) == 1
    assert not any(part in ("tantivy", "lucene", "source-a") for x in commands for part in x)


# C-U05 ---------------------------------------------------------------------
def test_c_u05_cache_identity_rekeys_when_b_revision_changes(tmp_path, monkeypatch):
    _, config = make_config(tmp_path)

    def fake_git(root, *args):
        if args[0] == "rev-parse":
            return "c" * 40
        if args[0] == "cat-file":
            return "commit"
        if args[0] == "ls-tree":
            return f"100644 blob {'d' * 40}\t{args[-1]}"
        return ""

    monkeypatch.setattr(preparation, "_clean_source", lambda root: "c" * 40)
    monkeypatch.setattr(preparation.runtime, "_git", fake_git)
    monkeypatch.setattr(preparation.runtime, "_tool", lambda argv: "mock-version")
    first = preparation._digest(preparation.source_identity(tmp_path, config))
    changed = deepcopy(config)
    changed["arms"]["B"]["revision"] = OTHER_SHA
    second = preparation._digest(preparation.source_identity(tmp_path, changed))
    assert first != second

    missing = deepcopy(config)
    missing["arms"]["B"]["revision"] = OTHER_SHA

    def rejecting_git(root, *args):
        if args[0] == "cat-file":
            return "blob"
        return fake_git(root, *args)

    monkeypatch.setattr(preparation.runtime, "_git", rejecting_git)
    with pytest.raises(runtime.MeasurementBlocked):
        preparation.source_identity(tmp_path, missing)


# C-U06 ---------------------------------------------------------------------
def test_c_u06_bb_schedule_shape_and_seeded_balance():
    rows = statistics.schedule(["BB", "BB2"], blocks=12, slots_per_arm=1, seed=20261122)
    assert len(rows) == 24
    assert {row["block"] for row in rows} == set(range(1, 13))
    assert {row["position"] for row in rows} == {1, 2}
    assert {row["arm_id"] for row in rows} == {"BB", "BB2"}
    for block in range(1, 13):
        pair = [row["arm_id"] for row in rows if row["block"] == block]
        assert sorted(pair) == ["BB", "BB2"]


# C-U07 ---------------------------------------------------------------------
def test_c_u07_stable_and_noisy_bb_control(tmp_path):
    _, config = make_config(tmp_path)
    lanes = configuration.lanes_for(config)
    stable = _b_raw(config)
    analysis = statistics.analyze(stable, arms=["BB", "BB2"], baseline="BB",
                                  lanes=lanes, policy=CONTROL_POLICY)
    assert all(comparison["status"] == "PASS"
               for lane in analysis["lanes"].values()
               for comparison in lane["comparisons"].values())

    noisy = []
    for row in stable:
        row = deepcopy(row)
        row["samples_ns"] = [100] * 20 if row["arm_id"] == "BB" else [200] * 20
        noisy.append(row)
    noisy_analysis = statistics.analyze(noisy, arms=["BB", "BB2"], baseline="BB",
                                        lanes=lanes, policy=CONTROL_POLICY)
    assert any(comparison["status"] == "FAIL"
               for lane in noisy_analysis["lanes"].values()
               for comparison in lane["comparisons"].values())


# C-U09 / C-U10 -------------------------------------------------------------
def test_c_u09_c_u10_absolute_b_and_descriptive_historical_comparison(tmp_path):
    _, config = make_config(tmp_path)
    historical = _historical_summary(config)
    bb = _bb_analysis(config, lambda lane: 100)
    analysis = perf05.analyze_b_only(_b_raw(config), bb, historical, config, _matching_context())
    assert analysis["estimator"] == "median-of-two-b-slot-medians-per-block-v1"
    assert analysis["bootstrap_method"] == "NONE_FOR_HISTORICAL_COMPARISON"
    assert analysis["comparison_kind"] == "HISTORICAL_UNPAIRED_ABSOLUTE"
    assert analysis["context"] == {"matches": True, "differences": []}
    for lane_id, row in analysis["historical_comparison"].items():
        assert row["B"]["median_block_value"] == 100.0
        assert row["A"]["median_block_value"] == pytest.approx(float(Decimal(perf05.EXPECTED_MEDIANS[lane_id])))
        assert row["ratio_b_over_historical_a"] > 0
        assert "ratio_ci_95" not in row
        assert row["comparison_kind"] == "HISTORICAL_UNPAIRED_ABSOLUTE"
    assert analysis["disposition"] == "B_ONLY_HISTORICAL_TARGETS_MET"

    missing = deepcopy(historical)
    missing["lanes"].pop("10000/absent/k10/warm")
    with pytest.raises(artifacts.ArtifactError):
        perf05.analyze_b_only(_b_raw(config), bb, missing, config, _matching_context())


@pytest.mark.parametrize("bad_median", [0.0, -1.0, float("nan")])
def test_c_u10_invalid_historical_median_is_rejected(tmp_path, bad_median):
    _, config = make_config(tmp_path)
    historical = _historical_summary(config)
    historical["lanes"]["10000/absent/k10/warm"]["median_block_value"] = bad_median
    bb = _bb_analysis(config, lambda lane: 100)
    with pytest.raises(artifacts.ArtifactError):
        perf05.analyze_b_only(_b_raw(config), bb, historical, config, _matching_context())


# C-U11 ---------------------------------------------------------------------
def test_c_u11_target_and_guard_flags_and_context_change(tmp_path):
    _, config = make_config(tmp_path)
    strict = {lane: 100.0 for lane in perf05.EXPECTED_MEDIANS}
    historical = _historical_summary(config, medians=strict)
    at_bounds = _bb_analysis(config, lambda lane: 95.0 if lane["id"] in perf05.PRIMARY_LANES else 110.0)
    analysis = perf05.analyze_b_only(_b_raw(config), at_bounds, historical, config, _matching_context())
    assert analysis["disposition"] == "B_ONLY_HISTORICAL_TARGETS_MET"
    assert all(row["within_threshold"] for row in analysis["historical_comparison"].values())

    over = _bb_analysis(config, lambda lane: 95.01 if lane["id"] in perf05.PRIMARY_LANES else 110.0)
    analysis = perf05.analyze_b_only(_b_raw(config), over, historical, config, _matching_context())
    assert analysis["disposition"] == "B_ONLY_HISTORICAL_TARGETS_NOT_MET"

    mismatched = _matching_context()
    mismatched["host"]["filesystem"] = "tmpfs"
    analysis = perf05.analyze_b_only(
        _b_raw(config), _bb_analysis(config, lambda lane: 100.0), historical, config, mismatched)
    assert analysis["disposition"] == "B_ONLY_HISTORICAL_CONTEXT_CHANGED"
    assert analysis["context"]["matches"] is False


# C-U12 / C-U13 -------------------------------------------------------------
def _fake_index(command, *, engine, corpus_path, target, n, cpu):
    target.mkdir(parents=True, exist_ok=True)
    return {"index_ns": 1, "commit_ns": 1, "reopen_ns": 1, "index_bytes": 1, "segment_count": 1}


def test_c_u12_c_u13_failed_and_successful_b_only_run_publication(tmp_path, monkeypatch):
    path, config = make_config(tmp_path)
    fixture = _historical_summary(config)
    monkeypatch.setattr(perf05, "verify_historical_reference", lambda root, cfg: fixture)

    def failing_phase(control, lanes, binaries, indexes, *, cpu, on_slot):
        raise runtime.MeasurementBlocked("synthetic B failure")

    location, report = runtime.run_benchmark(
        path, root=tmp_path, scratch_root=tmp_path / "scratch",
        programs={"B": [str(tmp_path / "adapter")]}, check_host=False,
        invoke_phase=failing_phase, index_builder=_fake_index)
    assert report["status"] == "INCOMPLETE"
    assert report["errors"]
    assert location.name.endswith("-001.json")
    assert artifacts.load_result(location)["status"] == "INCOMPLETE"

    observed_rows = _b_raw(config)

    def stable_phase(control, lanes, binaries, indexes, *, cpu, on_slot):
        on_slot(observed_rows)
        return observed_rows

    location, report = runtime.run_benchmark(
        path, root=tmp_path, scratch_root=tmp_path / "scratch",
        programs={"B": [str(tmp_path / "adapter")]}, check_host=False,
        invoke_phase=stable_phase, index_builder=_fake_index)
    saved = artifacts.load_result(location)
    assert report["status"] == "COMPLETE"
    assert saved["status"] == "COMPLETE"
    assert saved["analysis"]["schema"] == "bm10-b-only-analysis-v1"
    assert set(saved["controls"]["analysis"]["lanes"]) == set(perf05.EXPECTED_MEDIANS)
    assert len(saved["raw_samples"]) == 384
    assert saved["sequence"] == 2
    assert saved["run_id"] != report.get("previous_run_id")
    markdown = reporting.replay_to_markdown(location)
    assert "HISTORICAL, UNPAIRED, DESCRIPTIVE" in markdown
    assert "Target: 4 primary lanes" in markdown


# C-U14 ---------------------------------------------------------------------
def test_c_u14_cli_prepare_revision_scoping(tmp_path, capsys):
    studies = tmp_path / "studies"
    assert cli.main(["prepare", "--family", "perf-05", "--name", "quervant-perf05-b-only-warm",
                     "--description", "d", "--quervant-revision", B_SHA,
                     "--studies-root", str(studies)]) == 0
    capsys.readouterr()
    for argv in (
        ["prepare", "--family", "perf-05", "--name", "no-revision", "--description", "d",
         "--studies-root", str(studies)],
        ["prepare", "--family", "perf-05", "--name", "bad-revision", "--description", "d",
         "--quervant-revision", "HEAD", "--studies-root", str(studies)],
        ["prepare", "--family", "perf-05", "--name", "upper-revision", "--description", "d",
         "--quervant-revision", "E" * 40, "--studies-root", str(studies)],
        ["prepare", "--family", "perf-02", "--name", "legacy", "--description", "d",
         "--baseline-revision", B_SHA, "--candidate-revision", B_SHA,
         "--quervant-revision", B_SHA, "--studies-root", str(studies)],
    ):
        assert cli.main(argv) == 2
        capsys.readouterr()


# C-U15 ---------------------------------------------------------------------
def test_c_u15_legacy_configurations_still_validate_read_only():
    legacy = ["retained-key", "cross-engine", "perf-02"]
    for family in legacy:
        if family == "perf-02":
            config = configuration.default_configuration(
                family, f"{family}-legacy", "d", baseline_revision=OTHER_SHA,
                candidate_revision=OTHER_SHA)
        else:
            config = configuration.default_configuration(family, f"{family}-legacy", "d")
        configuration.validate_configuration(config)
    assert "perf-05" in artifacts.STUDY_REGIMES


# C-U16 (build-side) --------------------------------------------------------
def test_c_u16_build_does_not_touch_forbidden_toolchains(tmp_path, monkeypatch):
    _, config = make_config(tmp_path)
    seen = []

    def fake_run(argv, *, timeout=0, **kwargs):
        seen.append(tuple(argv))
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(runtime, "_git", lambda root, *args: "c" * 40)
    monkeypatch.setattr(runtime, "_run", fake_run)
    monkeypatch.setattr(runtime, "_build_rust",
                        lambda root, target, *, engine, feature, source_root=None: [str(target)])
    runtime.build_programs(config, tmp_path, tmp_path / "scratch")
    flat = " ".join(part for command in seen for part in command).lower()
    for forbidden in ("tantivy", "lucene", "rustfs", "perf record", "source-a"):
        assert forbidden not in flat


# C-U08 / defensive paths ------------------------------------------------
def test_c_u08_b_only_rejects_incomplete_or_incorrect_observations(tmp_path):
    _, config = make_config(tmp_path)
    historical = _historical_summary(config)
    bb = _bb_analysis(config, lambda lane: 100)
    with pytest.raises(artifacts.ArtifactError):
        perf05.analyze_b_only([], bb, historical, config, _matching_context())

    bad = _b_raw(config)
    bad[0] = deepcopy(bad[0])
    bad[0]["oracle_ok"] = False
    with pytest.raises(artifacts.ArtifactError):
        perf05.analyze_b_only(bad, bb, historical, config, _matching_context())

    missing_arm = _bb_analysis(config, lambda lane: 100)
    for lane in missing_arm["lanes"].values():
        lane["arm_absolute"].pop("BB2")
    with pytest.raises(artifacts.ArtifactError):
        perf05.analyze_b_only(_b_raw(config), missing_arm, historical, config, _matching_context())

    failed_control = _bb_analysis(config, lambda lane: 100)
    for lane in failed_control["lanes"].values():
        lane["comparisons"]["BB2"]["status"] = "FAIL"
    with pytest.raises(artifacts.ArtifactError):
        perf05.analyze_b_only(_b_raw(config), failed_control, historical, config, _matching_context())

    assert perf05._context_differences(None, {}) == ["context unavailable"]


def test_c_u03_historical_git_failure_and_missing_reference_are_typed(tmp_path, monkeypatch):
    _, config = make_config(tmp_path)

    def boom(root, *args):
        raise OSError("git missing")

    monkeypatch.setattr(perf05.runtime, "_git", boom)
    with pytest.raises(artifacts.ArtifactError):
        perf05.verify_historical_reference(REPO_ROOT, config)

    broken = deepcopy(config)
    broken.pop("historical_reference")
    with pytest.raises(artifacts.ArtifactError):
        perf05.verify_historical_reference(REPO_ROOT, broken)
