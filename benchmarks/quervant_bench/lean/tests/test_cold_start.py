"""Single-lane process-cold startup study: deterministic/stub-only acceptance."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from quervant_bench.lean import artifacts, configuration, reporting, runtime, statistics


def _cold_fixture():
    cfg = configuration.default_configuration(
        "cross-engine", "cold-test", "Cold process startup regression",
        regime="process-cold"
    )
    cfg["policy"].update(blocks=6, slots_per_arm=2, samples=3, bootstrap_resamples=100)
    return cfg, configuration.lanes_for(cfg)[0]


def _script(tmp_path, body):
    script = tmp_path / "stub_cold_adapter.py"
    script.write_text(body, encoding="utf-8")
    return [sys.executable, "-u", str(script)]


def test_launch_to_first_reply_keeps_engine_timing_separate(tmp_path):
    cfg, lane = _cold_fixture()
    stub = _script(tmp_path, """
import json, sys, time
r = json.loads(sys.stdin.readline())
reply = {
    "schema": "pr15d-adapter-v1", "engine": "tantivy",
    "request_id": r["request_id"], "status": "ok",
    "total_hits": 1250,
    "doc_ids": [f"d{i:08d}" for i in range(0, 800, 8)],
    "engine_ns": 100, "index_open_ns": 200
}
print(json.dumps(reply), flush=True)
time.sleep(0.40)  # Deliberate post-reply shutdown delay is outside timed interval.
""")
    wall_ns, index_open_ns, engine_ns = runtime.collect_cold_start(
        stub, engine="tantivy", index_dir=tmp_path, lane=lane, config=cfg,
        arm_id="T", cpu=None, request_id="cold:1", timeout=2)
    assert index_open_ns == 200
    assert engine_ns == 100
    assert wall_ns >= index_open_ns + engine_ns
    assert wall_ns < 300_000_000, "time must stop at first reply, not delayed shutdown"


@pytest.mark.parametrize(("body", "diagnostic"), [
    ("print('not-json',flush=True)", "malformed adapter JSON reply"),
    ("import sys; sys.exit(3)", "closed before first reply"),
    ("""import json,sys
r=json.loads(sys.stdin.readline())
print(json.dumps({"schema":"pr15d-adapter-v1","engine":"tantivy",
    "request_id":r["request_id"],"status":"error"}),flush=True)
""", "disagrees with request"),
])
def test_cold_start_invalid_adapter_replies_fail_closed(tmp_path, body, diagnostic):
    cfg,lane=_cold_fixture()
    stub=_script(tmp_path,body)
    with pytest.raises(runtime.MeasurementBlocked,match=diagnostic):
        runtime.collect_cold_start(
            stub,engine="tantivy",index_dir=tmp_path,lane=lane,config=cfg,
            arm_id="T",cpu=None,request_id="cold:bad",timeout=2)


def test_cold_start_timeout_is_bounded_and_does_not_claim_measurement(tmp_path):
    cfg,lane=_cold_fixture()
    stub=_script(tmp_path,"import time; time.sleep(10)")
    with pytest.raises(runtime.MeasurementBlocked,match="first reply timed out"):
        runtime.collect_cold_start(
            stub,engine="tantivy",index_dir=tmp_path,lane=lane,config=cfg,
            arm_id="T",cpu=None,request_id="cold:timeout",timeout=0.05)



@pytest.mark.parametrize(("open_literal", "diagnostic"), [
    (None, "positive index_open_ns"),  # Missing first-query timing is invalid.
    ("true", "positive index_open_ns"),
    ("0", "positive index_open_ns"),
    ("-1", "positive index_open_ns"),
    ("1.5", "positive index_open_ns"),
    ("100000000000000000000", "index opening plus query exceeds"),
])
def test_cold_start_fails_closed_without_valid_adapter_open_timing(
        tmp_path, open_literal, diagnostic):
    cfg, lane = _cold_fixture()
    opened = "" if open_literal is None else f', "index_open_ns": {open_literal}'
    stub = _script(tmp_path, f"""
import json, sys
r = json.loads(sys.stdin.readline())
print(json.dumps({{
    "schema": "pr15d-adapter-v1", "engine": "tantivy",
    "request_id": r["request_id"], "status": "ok",
    "total_hits": 1250,
    "doc_ids": [f"d{{i:08d}}" for i in range(0, 800, 8)],
    "engine_ns": 100{opened}
}}), flush=True)
""")
    with pytest.raises(runtime.MeasurementBlocked, match=diagnostic):
        runtime.collect_cold_start(
            stub, engine="tantivy", index_dir=tmp_path, lane=lane, config=cfg,
            arm_id="T", cpu=None, request_id="cold:missing-open", timeout=2)


@pytest.mark.parametrize(("field", "corruption"), [
    ("index_open_samples_ns", None),
    ("index_open_samples_ns", [0, 200, 200]),
    ("index_open_samples_ns", [False, 200, 200]),
    ("engine_samples_ns", [100, 100]),
    ("other_overhead_samples_ns", [-1, 100, 100]),
    ("other_overhead_samples_ns", [101, 100, 100]),
])
def test_cold_analysis_rejects_missing_invalid_or_unbalanced_components(field, corruption):
    cfg, lane = _cold_fixture()
    scheduled = statistics.schedule(
        ["Q", "T", "J"], blocks=cfg["policy"]["blocks"],
        slots_per_arm=cfg["policy"]["slots_per_arm"], seed=cfg["policy"]["seed"])
    rows = [{
        "arm_id": entry["arm_id"], "block": entry["block"],
        "position": entry["position"], "lane_id": lane["id"],
        "oracle_ok": True, "samples_ns": [400] * 3,
        "index_open_samples_ns": [200] * 3,
        "engine_samples_ns": [100] * 3,
        "other_overhead_samples_ns": [100] * 3,
    } for entry in scheduled]
    if corruption is None:
        rows[0].pop(field)
    else:
        rows[0][field] = corruption
    with pytest.raises(artifacts.ArtifactError, match="cold-start"):
        statistics.analyze(rows, arms=["Q", "T", "J"], baseline="Q",
                           lanes=[lane], policy=cfg["policy"])


def test_cold_run_has_only_cold_lane_and_skips_serial_throughput(tmp_path,monkeypatch):
    cfg,lane=_cold_fixture()
    path=artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path/"studies",cfg),cfg)
    monkeypatch.setattr(runtime,"create_corpus",lambda p,n:p.write_text("synthetic"))
    monkeypatch.setattr(runtime,"host_context",lambda scratch,check:{"physical_core_candidates":[]})
    def mock_index(*args,**kwargs):
        return {"index_ns":1,"commit_ns":1,"reopen_ns":1,"index_bytes":1,"segment_count":1}
    monkeypatch.setattr(runtime,"collect_throughput",
                        lambda *a,**k:(_ for _ in ()).throw(AssertionError("no warm throughput")))
    def fake_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        assert len(lanes)==1 and lanes[0]["id"]==lane["id"]
        schedule=statistics.schedule(
            list(config["arms"]),blocks=config["policy"]["blocks"],
            slots_per_arm=config["policy"]["slots_per_arm"],seed=config["policy"]["seed"])
        rows=[{"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
               "lane_id":lane["id"],"oracle_ok":True,"warmups":0,
               "samples_ns":[400]*3,"index_open_samples_ns":[200]*3,
               "engine_samples_ns":[100]*3,"other_overhead_samples_ns":[100]*3}
              for x in schedule]
        on_slot(rows)
        return rows
    monkeypatch.setattr(runtime,"_phase",fake_phase)
    saved,result=runtime.run_benchmark(
        path,path.parent.parent/"results",root=tmp_path,
        programs={a:["/mock"] for a in cfg["arms"]},
        check_host=False,index_builder=mock_index)
    assert result["status"]=="COMPLETE"
    assert len(result["lanes"])==1
    assert result["lanes"][0]["metric"]=="cold_start_first_response_latency"
    assert "throughput_metrics" not in result
    assert len(result["raw_samples"])==6*3*2
    for record in result["raw_samples"]:
        assert record["samples_ns"]==[400]*3
        assert record["index_open_samples_ns"]==[200]*3
        assert record["engine_samples_ns"]==[100]*3
        assert record["other_overhead_samples_ns"]==[100]*3
    components=result["analysis"]["lanes"][lane["id"]]["component_absolute"]
    assert components["Q"]["index_open_ns"]["median_block_value"]==200
    assert components["Q"]["engine_ns"]["median_block_value"]==100
    assert components["Q"]["other_overhead_ns"]["median_block_value"]==100
    assert result["controls"]["analysis"]["lanes"][lane["id"]]
    report = reporting.replay_to_markdown(saved)
    assert "Cold-start timing breakdown" in report
    assert "Index open ms" in report
    assert "A/A" in report
    assert artifacts.load_result(saved)["configuration_id"]==cfg["configuration_id"]
