"""BM-10 error-boundary tests: no real benchmark or adapter invocation."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import json

import pytest
from quervant_bench.lean import artifacts, cli, configuration, reporting, runtime, statistics


def config_at(tmp_path):
    cfg = configuration.default_configuration("retained-key", "error-scenarios", "Boundary checks",
                                              timestamp="2026-11-21T22:00:00Z")
    return artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", cfg), cfg), cfg


def result_for(cfg):
    return {"run_id": str(uuid4()), "configuration_id": cfg["configuration_id"],
            "executed_utc": "2026-11-22T02:00:00Z", "raw_samples": [],
            "analysis": {}, "status": "INCOMPLETE"}


@pytest.mark.parametrize("bad", ["", "UPPER", "bad_name", "a--b", "-a", "a-", "../bad", "a"*81, 3])
def test_invalid_names(bad):
    with pytest.raises(artifacts.ArtifactError): artifacts.slug(bad)


@pytest.mark.parametrize("bad", ["2026-11-22T00:00:00", "2026-02-30T00:00:00Z",
                                   "2026-11-22T00:00:00+01:00", "nonsense", None])
def test_invalid_timestamps(bad):
    with pytest.raises(artifacts.ArtifactError): artifacts.utc_timestamp(bad)


@pytest.mark.parametrize("bad", ["2026-02-30", "22-11-2026"])
def test_invalid_dates(bad):
    with pytest.raises(artifacts.ArtifactError): artifacts.utc_date(bad)


def test_invalid_uuids_json_and_encoding(tmp_path):
    for value in ("not-a-uuid", str(uuid4()).upper()):
        with pytest.raises(artifacts.ArtifactError): artifacts.require_uuid(value, "id")
    bad = tmp_path / "bad.json"
    for content in ('{"key":1,"key":2}', '{"n":NaN}', '{'):
        bad.write_text(content)
        with pytest.raises(artifacts.ArtifactError): artifacts._read_json(bad)
    bad.write_bytes(b'\xff')
    with pytest.raises(artifacts.ArtifactError): artifacts._read_json(bad)
    with pytest.raises(artifacts.ArtifactError): artifacts._json_bytes({"inf": float("inf")})


def test_configuration_rejects_bad_contracts():
    base = configuration.default_configuration("retained-key", "candidate", "Description")
    modifications = [
        ("schema", "wrong"), ("baseline", "X"), ("control", {}),
        ("build", {"release": False}), ("workload", {}),
        ("policy", {"blocks": False}),
    ]
    for key, value in modifications:
        cfg = deepcopy(base); cfg[key] = value
        with pytest.raises(artifacts.ArtifactError): configuration.validate_configuration(cfg)
    bad_policy = {"blocks":11, "slots_per_arm":0, "warmups":-1,
                  "samples":0, "bootstrap_resamples":100001, "min_blocks":13,
                  "control_arms":["AA2"], "readiness":None, "exclude_blocks":[]}
    for key, value in bad_policy.items():
        cfg=deepcopy(base); cfg["policy"][key]=value
        with pytest.raises(artifacts.ArtifactError): configuration.validate_configuration(cfg)
    for key,value in (("intervals",30),("interval_ms",5001),("max_busy_percent",101),
                      ("max_steal_percent",101),("intervals",0)):
        cfg=deepcopy(base); cfg["policy"]["readiness"][key]=value
        with pytest.raises(artifacts.ArtifactError): configuration.validate_configuration(cfg)
    for key,value in (("sizes",[10000]),("classes",["rare"]),("top_k",[1]),
                      ("regimes",["warm","fake"]),("timed_operation","wrong"),
                      ("query_semantics","wrong")):
        cfg=deepcopy(base); cfg["workload"][key]=value
        with pytest.raises(artifacts.ArtifactError): configuration.validate_configuration(cfg)


def test_configuration_id_is_unique_across_names(tmp_path):
    # I-01: a configuration_id identifies exactly one immutable configuration.
    path, cfg = config_at(tmp_path)
    clone = deepcopy(cfg)
    clone["name"] = "different-name"
    clone["created_utc"] = "2026-11-23T00:00:00Z"
    with pytest.raises(artifacts.ArtifactError, match="ID already reserved"):
        artifacts.create_configuration(path.parent, clone)
    assert [p.name for p in path.parent.glob("*.json")] == [path.name]
    # The reserved configuration keeps working: results still publish and load.
    saved = artifacts.publish_result(path, path.parent.parent / "results", result_for(cfg))
    assert artifacts.load_result(saved)["configuration_id"] == cfg["configuration_id"]


def test_result_rejects_broken_id_dates_sequence_and_analysis(tmp_path,monkeypatch):
    path, cfg = config_at(tmp_path)
    root = path.parent.parent / "results"
    for field,value in (("run_id","bad"),("configuration_id",str(uuid4())),
                        ("executed_utc","bad"),("raw_samples",{}),("analysis",[])):
        entry=result_for(cfg);entry[field]=value
        with pytest.raises(artifacts.ArtifactError): artifacts.publish_result(path,root,entry)
    first=artifacts.publish_result(path,root,result_for(cfg))
    entry=artifacts.load_result(first)
    duplicate=root/f"{cfg['name']}-2026-11-23-001.json"
    duplicate.write_text(json.dumps(entry))
    with pytest.raises(artifacts.ArtifactError): artifacts.publish_result(path,root,result_for(cfg))
    duplicate.unlink()
    monkeypatch.setattr(artifacts,"MAX_SEQUENCE",1)
    with pytest.raises(artifacts.ArtifactError,match="exhausted"):
        artifacts.publish_result(path,root,result_for(cfg))
    entry["sequence"]=5;first.write_text(json.dumps(entry))
    with pytest.raises(artifacts.ArtifactError): artifacts.load_result(first)


def test_statistics_reject_invalid_rows_and_metadata():
    arms=["A","B"]; lane={"id":"L0","metric":"search_latency","unit":"ns","direction":"lower"}
    policy={"blocks":4,"slots_per_arm":2,"samples":3,"bootstrap_resamples":100,
            "seed":10,"min_blocks":4,"exclude_blocks":{},"control_arms":[]}
    rows=[{"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
           "lane_id":"L0","oracle_ok":True,"samples_ns":[100]*3}
          for x in statistics.schedule(arms,blocks=4,slots_per_arm=2,seed=10)]
    for field,value in (("arm_id","Q"),("lane_id","bogus"),("block",5),
                        ("position",5),("oracle_ok",False),("samples_ns",[1])):
        altered=deepcopy(rows);altered[0][field]=value
        with pytest.raises(artifacts.ArtifactError):
            statistics.analyze(altered,arms=arms,baseline="A",lanes=[lane],policy=policy)
    for _arms, baseline, _lanes, _policy in [
        (["A","A"],"A",[lane],policy),(["A","B"],"Q",[lane],policy),
        (arms,"A",[lane,lane],policy),(arms,"A",[{**lane,"unit":None}],policy),
        (arms,"A",[{**lane,"direction":"up"}],policy),
        (arms,"A",[lane],{**policy,"exclude_blocks":{"L0":[True]}}),
    ]:
        with pytest.raises(artifacts.ArtifactError):
            statistics.analyze(rows,arms=_arms,baseline=baseline,lanes=_lanes,policy=_policy)


def test_cli_rejects_old_certification_verbs(capsys):
    with pytest.raises(SystemExit) as error: cli.main(["accept", "--run", "x"])
    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_operator_interrupt_is_recorded_without_benchmark(tmp_path,monkeypatch):
    path,cfg=config_at(tmp_path)
    monkeypatch.setattr(runtime,"host_context",lambda scratch,check:{"physical_core_candidates":[]})
    monkeypatch.setattr(runtime,"_git",lambda *args:"sha")
    from quervant_bench.lean import preparation
    # Test the interruption *during the build*, not clean-source preflight.
    monkeypatch.setattr(preparation,"source_identity",
                        lambda root,config:{"test":"interrupted-build"})
    def interrupt(*args,**kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr(runtime,"build_programs",interrupt)
    dest,r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,check_host=False)
    assert r["status"] == "INCOMPLETE"
    assert "interrupted" in r["errors"][0]
    assert artifacts.load_result(dest)["run_id"] == r["run_id"]
