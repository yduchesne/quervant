"""Study-directory contract: deterministic filesystem tests, no benchmark execution."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from quervant_bench.lean import artifacts, cli, configuration, runtime


def _make(tmp_path: Path, family: str, regime: str, name: str):
    config = configuration.default_configuration(
        family, name, "Immutable study-directory test",
        timestamp="2026-11-22T09:00:00Z",
        regime="process-cold" if regime == "cold-start" else "warm",
    )
    return config, artifacts.configuration_directory(tmp_path / "studies", config)


def _result(config, *, executed="2026-11-22T12:00:00Z"):
    return {
        "configuration_id": config["configuration_id"],
        "run_id": str(uuid4()),
        "executed_utc": executed,
        "raw_samples": [], "analysis": {}, "status": "INCOMPLETE",
    }


def test_committed_configs_are_correctly_routed_and_retain_identity():
    studies_root = Path(__file__).resolve().parents[3] / "studies"
    locations = {
        "retained-key/warm": (
            "retained-key-prefilter-2026-11-22.json",
            "c5800fb9-ae02-4ee1-a726-491a44ab9857",
        ),
        "cross-engine/warm": (
            "quervant-tantivy-lucene-warm-2026-11-22.json",
            "07e54b1c-8c71-4c94-8aaf-0fb034093ef2",
        ),
        "cross-engine/cold-start": (
            "quervant-tantivy-lucene-cold-start-2026-11-22.json",
            "57e3152c-996e-46c1-b64c-d74597b191d3",
        ),
    }
    for study, (filename, identity) in locations.items():
        family, regime = study.split("/")
        path = studies_root / family / regime / "configurations" / filename
        config = artifacts.load_configuration(path)
        configuration.validate_configuration(config)
        assert config["configuration_id"] == identity
        assert artifacts.configuration_directory(studies_root, config) == path.parent
        assert artifacts.result_directory(path) == path.parent.parent / "results"
    assert not (studies_root.parent / "configurations").exists()
    assert not (studies_root.parent / "results").exists()
    assert not (studies_root / "retained-key" / "cold-start").exists()


@pytest.mark.parametrize(("family", "regime"), [
    ("retained-key", "warm"),
    ("cross-engine", "warm"),
    ("cross-engine", "cold-start"),
])
def test_prepare_routes_study_and_cli_validates_path(tmp_path, capsys, family, regime):
    root = tmp_path / "studies"
    args = ["prepare", "--family", family,
            "--regime", "process-cold" if regime == "cold-start" else "warm",
            "--name", family + "-" + regime + "-case",
            "--description", "Study path fixture", "--studies-root", str(root)]
    assert cli.main(args) == 0
    filename = Path(capsys.readouterr().out.strip())
    assert filename.parent == root / family / regime / "configurations"
    assert cli.main(["validate", "--config", str(filename)]) == 0
    assert capsys.readouterr().out.strip() == "VALID"
    assert not (root / "retained-key" / "cold-start").exists()


def test_reject_unsupported_retained_key_cold_study_without_creating_directory(tmp_path):
    root = tmp_path / "studies"
    with pytest.raises(artifacts.ArtifactError, match="only cross-engine"):
        configuration.prepare_configuration(root, family="retained-key",
                                            regime="process-cold", name="wrong",
                                            description="Unsupported")
    assert not root.exists()


def test_creation_rejects_configuration_in_another_family_or_regime(tmp_path):
    cfg, correct = _make(tmp_path, "cross-engine", "cold-start", "cold-mismatch")
    for dest in (tmp_path / "configurations",
                 tmp_path / "studies" / "cross-engine" / "warm" / "configurations",
                 tmp_path / "studies" / "retained-key" / "cold-start" / "configurations"):
        with pytest.raises(artifacts.ArtifactError, match="configuration must reside"):
            artifacts.create_configuration(dest, cfg)
    path = artifacts.create_configuration(correct, cfg)
    wrong = tmp_path / "studies" / "cross-engine" / "warm" / "configurations" / path.name
    wrong.parent.mkdir(parents=True)
    wrong.write_bytes(path.read_bytes())
    with pytest.raises(artifacts.ArtifactError, match="configuration must reside"):
        artifacts.load_configuration(wrong)


def test_name_and_id_are_unique_across_all_studies(tmp_path):
    first, first_dir = _make(tmp_path, "cross-engine", "warm", "reserved")
    artifacts.create_configuration(first_dir, first)
    other, other_dir = _make(tmp_path, "cross-engine", "cold-start", "reserved")
    with pytest.raises(artifacts.ArtifactError, match="name already reserved"):
        artifacts.create_configuration(other_dir, other)
    other["name"] = "distinct-name"
    other["configuration_id"] = first["configuration_id"]
    with pytest.raises(artifacts.ArtifactError, match="ID already reserved"):
        artifacts.create_configuration(other_dir, other)
    assert list(other_dir.glob("*.json")) == [] if other_dir.exists() else True


def test_auto_result_sibling_and_sequences_are_isolated_per_configuration(tmp_path):
    warm, warm_dir = _make(tmp_path, "cross-engine", "warm", "warm-study")
    cold, cold_dir = _make(tmp_path, "cross-engine", "cold-start", "cold-study")
    p_w = artifacts.create_configuration(warm_dir, warm)
    p_c = artifacts.create_configuration(cold_dir, cold)
    w1 = artifacts.publish_result(p_w, None, _result(warm))
    w2 = artifacts.publish_result(p_w, None, _result(warm, executed="2026-11-23T12:00:00Z"))
    c1 = artifacts.publish_result(p_c, None, _result(cold))
    assert w1.parent == warm_dir.parent / "results"
    assert c1.parent == cold_dir.parent / "results"
    assert w1.name.endswith("-2026-11-22-001.json")
    assert w2.name.endswith("-2026-11-23-002.json")
    assert c1.name.endswith("-2026-11-22-001.json")
    assert artifacts.load_result(c1)["configuration_file"] == p_c.name
    assert artifacts.load_result(w2)["configuration_id"] == warm["configuration_id"]
    assert artifacts.load_result(w2)["configuration_file"] == p_w.name
    assert not (tmp_path / "results").exists()


def test_explicit_cross_study_result_destination_fails_before_benchmark(tmp_path, monkeypatch):
    cfg, dirname = _make(tmp_path, "cross-engine", "warm", "no-misroute")
    saved = artifacts.create_configuration(dirname, cfg)
    wrong = tmp_path / "studies" / "cross-engine" / "cold-start" / "results"
    with pytest.raises(artifacts.ArtifactError, match="result directory must be"):
        artifacts.publish_result(saved, wrong, _result(cfg))
    monkeypatch.setattr(runtime, "host_context",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("started real work")))
    with pytest.raises(artifacts.ArtifactError, match="result directory must be"):
        runtime.run_benchmark(saved, wrong, root=tmp_path)
    assert not wrong.exists()


def test_cli_no_longer_accepts_flat_path_override():
    args = cli.parser()
    choices = args._subparsers._group_actions[0].choices
    with pytest.raises(SystemExit):
        choices["prepare"].parse_args(["--config-dir", "somewhere"])
    with pytest.raises(SystemExit):
        choices["run"].parse_args(["--result-dir", "somewhere"])


def test_loaded_result_can_still_be_inspected_after_copy(tmp_path):
    """Read-only analysis/report is portable even though publication is routed."""
    cfg, dirname = _make(tmp_path, "retained-key", "warm", "portable")
    source = artifacts.create_configuration(dirname, cfg)
    saved = artifacts.publish_result(source, None, _result(cfg))
    copy = tmp_path / saved.name
    copy.write_bytes(saved.read_bytes())
    assert artifacts.load_result(copy) == artifacts.load_result(saved)
