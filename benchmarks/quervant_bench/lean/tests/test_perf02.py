"""PERF-02-A Quervant-only pinned A/B study, fully mocked and untimed in CI."""
from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from quervant_bench.lean import artifacts, cli, configuration, preparation, runtime, statistics


BASE = "a" * 40
CANDIDATE = "b" * 40


def _config(tmp_path: Path, *, candidate: str = CANDIDATE):
    config = configuration.default_configuration(
        "perf-02", "quervant-sort-test", "Synthetic pinned Quervant A/B test",
        timestamp="2026-11-22T10:00:00Z", regime="warm",
        baseline_revision=BASE, candidate_revision=candidate,
    )
    config["policy"].update(blocks=4, slots_per_arm=2, samples=2,
                            warmups=2, bootstrap_resamples=100, min_blocks=4)
    file = artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", config), config
    )
    return file, config


def test_perf02_configuration_has_two_pinned_production_arms_and_16_warm_lanes(tmp_path):
    path, config = _config(tmp_path)
    assert path.parent.as_posix().endswith("/perf-02/warm/configurations")
    assert set(config["arms"]) == {"A", "B"}
    assert config["baseline"] == "A"
    assert config["arms"]["A"] == {
        "engine": "quervant", "mode": "by-top-k", "source": "pinned",
        "revision": BASE,
    }
    assert config["arms"]["B"]["revision"] == CANDIDATE
    assert config["build"]["quervant_feature"] is None
    assert config["build"]["baseline_ref"] is None
    assert len(configuration.lanes_for(config)) == 16
    assert artifacts.load_configuration(path) == config
    assert artifacts.result_directory(path) == path.parent.parent / "results"


@pytest.mark.parametrize("field,value", [
    ("revision", "main"), ("revision", "f" * 39), ("revision", "F" * 40),
    ("revision", None), ("source", "current"), ("mode", "prefilter"),
    ("engine", "tantivy"),
])
def test_perf02_rejects_unpinned_or_nonproduction_arm(tmp_path, field, value):
    _, original = _config(tmp_path)
    config = json.loads(json.dumps(original))
    config["arms"]["B"][field] = value
    with pytest.raises(artifacts.ArtifactError):
        configuration.validate_configuration(config)


def test_perf02_requires_explicit_revisions_and_warm_regime():
    with pytest.raises(artifacts.ArtifactError, match="pinned"):
        configuration.default_configuration(
            "perf-02", "missing", "Missing revisions",
        )
    with pytest.raises(artifacts.ArtifactError, match="process-cold"):
        configuration.default_configuration(
            "perf-02", "cold", "Invalid regime",
            regime="process-cold", baseline_revision=BASE,
            candidate_revision=CANDIDATE,
        )
    with pytest.raises(artifacts.ArtifactError, match="only accepted"):
        configuration.default_configuration(
            "cross-engine", "misplaced", "Wrong family",
            baseline_revision=BASE, candidate_revision=CANDIDATE,
        )


def test_perf02_a_equal_a_is_permitted_for_framework_smoke(tmp_path):
    path, config = _config(tmp_path, candidate=BASE)
    assert config["arms"]["A"]["revision"] == config["arms"]["B"]["revision"]
    assert artifacts.load_configuration(path)["configuration_id"] == config["configuration_id"]


def test_perf02_cli_prepare_passes_pinned_revisions(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "repo_root", lambda: tmp_path)
    assert cli.main([
        "prepare", "--family", "perf-02", "--name", "perf02-prepared",
        "--description", "Pinned A/B validation",
        "--studies-root", str(tmp_path / "studies"),
        "--baseline-revision", BASE, "--candidate-revision", CANDIDATE,
    ]) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.is_file()
    assert artifacts.load_configuration(path)["arms"]["B"]["revision"] == CANDIDATE
    assert cli.main(["validate", "--config", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "VALID"


def test_perf02_builds_two_isolated_pinned_release_targets_and_removes_worktrees(
        tmp_path, monkeypatch):
    _, config = _config(tmp_path)
    commands = []
    targets = []
    monkeypatch.setattr(runtime, "_git", lambda root, *args: "c" * 40)

    def fake_run(argv, *, timeout=0, **kwargs):
        commands.append(tuple(argv))
        return CompletedProcess(argv, 0, "", "")

    def fake_build(root, target, *, engine, feature, source_root=None):
        targets.append((target, engine, feature, source_root))
        return [str(target / "release" / "pr15d-quervant-adapter")]

    monkeypatch.setattr(runtime, "_run", fake_run)
    monkeypatch.setattr(runtime, "_build_rust", fake_build)
    paths, context = runtime.build_programs(config, tmp_path, tmp_path / "scratch")
    assert set(paths) == {"A", "B"}
    assert paths["A"] != paths["B"]
    assert len(targets) == 2
    assert all(x[1] == "quervant" and x[2] is False for x in targets)
    assert targets[0][0].name == "quervant-a"
    assert targets[1][0].name == "quervant-b"
    assert targets[0][3].name == "source-a"
    assert targets[1][3].name == "source-b"
    adds = [x for x in commands if "add" in x]
    removals = [x for x in commands if "remove" in x]
    assert [x[-1] for x in adds] == [BASE, CANDIDATE]
    assert len(removals) == 2
    assert context["arm_source_revisions"] == {"A": BASE, "B": CANDIDATE}
    assert context["quervant_strategy_feature_enabled"] is False


def test_perf02_build_failure_still_removes_the_active_worktree(tmp_path, monkeypatch):
    _, config = _config(tmp_path)
    commands = []
    monkeypatch.setattr(runtime, "_git", lambda root, *args: "c" * 40)

    def fake_run(argv, *, timeout=0, **kwargs):
        commands.append(tuple(argv))
        return CompletedProcess(argv, 0, "", "")

    def fake_build(root, target, *, engine, feature, source_root=None):
        if target.name == "quervant-b":
            raise runtime.MeasurementBlocked("synthetic compilation failure")
        return [str(target / "release" / "pr15d-quervant-adapter")]

    monkeypatch.setattr(runtime, "_run", fake_run)
    monkeypatch.setattr(runtime, "_build_rust", fake_build)
    with pytest.raises(runtime.MeasurementBlocked, match="compilation failure"):
        runtime.build_programs(config, tmp_path, tmp_path / "scratch")
    assert len([x for x in commands if "add" in x]) == 2
    assert len([x for x in commands if "remove" in x]) == 2


def test_perf02_source_identity_refuses_missing_or_wrong_object(tmp_path, monkeypatch):
    _, config = _config(tmp_path)
    selected = {"B": "commit"}
    monkeypatch.setattr(preparation, "_clean_source", lambda root: "c" * 40)

    def fake_git(root, *args):
        if args[:2] == ("cat-file", "-t"):
            return selected["B"] if args[-1] == CANDIDATE else "commit"
        if args[:3] == ("ls-tree", "HEAD", "--"):
            return "040000 tree " + ("d" * 40) + "\t" + args[-1]
        raise AssertionError(args)

    monkeypatch.setattr(runtime, "_git", fake_git)
    monkeypatch.setattr(runtime, "_tool", lambda argv: "mock-version")
    identity = preparation.source_identity(tmp_path, config)
    assert identity["arm_source_revisions"] == {"A": BASE, "B": CANDIDATE}
    assert identity["toolchains"]["java"] == "NOT_REQUIRED"
    selected["B"] = "blob"
    with pytest.raises(runtime.MeasurementBlocked, match="does not identify a Git commit"):
        preparation.source_identity(tmp_path, config)


def _mock_preparation(monkeypatch):
    calls = []

    def source(root, config):
        return {"source_refs": {arm: item["revision"] for arm, item in config["arms"].items()},
                "config_sha256": preparation._digest(config)}

    def build(config, root, scratch):
        calls.append("build")
        commands = {}
        for arm in config["arms"]:
            target = (scratch / "build" / f"quervant-{arm.lower()}" /
                      "release" / "pr15d-quervant-adapter")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"binary:{arm}:{config['arms'][arm]['revision']}")
            commands[arm] = [str(target)]
        return commands, {"compiler_options": "MOCKED",
                          "arm_source_revisions": {arm: config["arms"][arm]["revision"]
                                                   for arm in config["arms"]}}

    def corpus(path, n):
        path.write_text(f"corpus:{n}")

    def index(command, *, engine, corpus_path, target, n, cpu):
        calls.append(f"index:{engine}:{n}")
        target.mkdir(parents=True)
        (target / "index.data").write_text(f"index:{command[0]}:{n}")
        return {"index_ns": 3, "commit_ns": 4, "reopen_ns": 5, "index_bytes": 6}

    def oracle(config, programs, indexes, cpu):
        calls.append("oracle")
        assert set(programs) == {"A", "B"}
        assert programs["A"] != programs["B"]
        for arm in ("A", "B"):
            for n in (10_000, 100_000):
                assert (indexes[arm][n] / "index.data").is_file()

    monkeypatch.setattr(preparation, "source_identity", source)
    monkeypatch.setattr(runtime, "build_programs", build)
    monkeypatch.setattr(runtime, "create_corpus", corpus)
    monkeypatch.setattr(runtime, "build_index", index)
    monkeypatch.setattr(preparation, "_verify_oracles", oracle)
    return calls


def test_perf02_stage_reuse_fingerprint_and_tamper_fail_closed(tmp_path, monkeypatch):
    path, _ = _config(tmp_path)
    calls = _mock_preparation(monkeypatch)
    first = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    second = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert first["state"] == "BUILT" and second["state"] == "HIT"
    assert first["key"] == second["key"]
    assert list(first["programs"]) == ["A", "B"]
    assert len([x for x in calls if x == "build"]) == 1
    assert len([x for x in calls if x.startswith("index:")]) == 4
    assert calls.count("oracle") == 2
    candidate_binary = Path(first["programs"]["B"][0])
    candidate_binary.write_text("tampered")
    with pytest.raises(runtime.MeasurementBlocked, match="cache failed validation"):
        preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert candidate_binary.exists()


def test_perf02_a_equal_a_mocked_full_run_reuses_prepared_inputs(tmp_path, monkeypatch):
    path, config = _config(tmp_path, candidate=BASE)
    calls = _mock_preparation(monkeypatch)
    monkeypatch.setattr(runtime, "host_context", lambda path, check: {
        "physical_core_candidates": [], "filesystem": "MOCKED",
    })
    monkeypatch.setattr(runtime, "_git", lambda root, *args: "c" * 40)

    def phase(config, lanes, binaries, indexes, *, cpu, on_slot):
        assert set(binaries) == {"A", "B"}
        assert set(indexes) == {"A", "B"}
        assert all(x["cache_regime"] == "warm" for x in lanes)
        scheduled = statistics.schedule(
            list(config["arms"]), blocks=config["policy"]["blocks"],
            slots_per_arm=config["policy"]["slots_per_arm"], seed=config["policy"]["seed"],
        )
        rows = [
            {"arm_id": pos["arm_id"], "block": pos["block"],
             "position": pos["position"], "lane_id": lane["id"],
             "oracle_ok": True, "samples_ns": [100, 100]}
            for pos in scheduled for lane in lanes
        ]
        on_slot(rows)
        return rows

    monkeypatch.setattr(runtime, "_phase", phase)
    first_path, first = runtime.run_benchmark(path, root=tmp_path, check_host=False)
    next_path, second = runtime.run_benchmark(path, root=tmp_path, check_host=False)
    assert first["status"] == second["status"] == "COMPLETE"
    assert first["context"]["preparation"]["cache_status"] == "BUILT"
    assert second["context"]["preparation"]["cache_status"] == "HIT"
    assert second["context"]["build"]["arm_source_revisions"] == {
        "A": BASE, "B": BASE,
    }
    assert len(second["analysis"]["lanes"]) == 16
    assert len(second["raw_samples"]) == 16 * 4 * 2 * 2
    assert len(second["controls"]["raw_samples"]) == 16 * 4 * 2 * 2
    assert all(lane["comparisons"]["B"]["status"] == "INCONCLUSIVE"
               for lane in second["analysis"]["lanes"].values())
    assert all(lane["comparisons"]["AA2"]["status"] == "PASS"
               for lane in second["controls"]["analysis"]["lanes"].values())
    assert first_path != next_path
    assert artifacts.load_result(first_path)["sequence"] == 1
    assert artifacts.load_result(next_path)["sequence"] == 2
    assert "throughput_metrics" not in second
    assert calls.count("build") == 1


def test_perf02_oracle_checks_both_pinned_arms(tmp_path, monkeypatch):
    _, config = _config(tmp_path)
    commands = {"A": ["/mock/quervant-a"], "B": ["/mock/quervant-b"]}
    indexes = {arm: {n: tmp_path / arm / str(n) for n in (10_000, 100_000)}
               for arm in ("A", "B")}
    seen = []

    def process(argv, cpu, *, env, input_text, timeout):
        requests = [json.loads(item) for item in input_text.splitlines()]
        arm = Path(argv[0]).name
        size = int(Path(argv[-1]).name)
        seen.append((arm, size, len(requests)))
        output = []
        for request in requests:
            hits, doc_ids = runtime.expected_answer(
                size, request["field"], request["term"], request["k"],
            )
            output.append({
                "schema": runtime.ADAPTER_SCHEMA, "engine": "quervant",
                "request_id": request["request_id"], "status": "ok",
                "total_hits": hits, "doc_ids": doc_ids, "engine_ns": 100,
            })
        return CompletedProcess(argv, 0, "\n".join(json.dumps(x) for x in output) + "\n", "")

    monkeypatch.setattr(runtime, "_run_pinned", process)
    preparation._verify_oracles(config, commands, indexes, cpu=None)
    assert len(seen) == 4
    assert sum(x[2] for x in seen) == 32
